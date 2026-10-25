"""O assistente do WhatsApp — o Gestão Solar é o GUARDIÃO.

1. A mensagem chega pelo gateway (`/api/v1/interno/whatsapp/evento`).
2. O número é casado com uma conta do Gestão Solar (`gs_users.telefone`). Sem conta, não há
   conversa: o bot é uma tecnologia do Gestão Solar.
3. Um orquestrador (DeepSeek, uma chamada por rodada) escolhe as ferramentas:
   - GERAÇÃO → API do meuWatt (`assistente_geracao`), só das usinas concedidas;
   - MANUTENÇÃO → o assistente do meuPlano, falando como esta pessoa (`manutencao`).
   Sempre com o token PRÓPRIO da pessoa (regra do dono, 23/10/2026): sem o dela, aquela
   parte não responde — nunca cai no da empresa nem no da plataforma.
4. A resposta, os PDFs e os gráficos saem pelo gateway.

Velocidade: pergunta de manutenção que só precisou do meuPlano volta DIRETO — a resposta
dele não passa por uma segunda rodada aqui.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, Sequence

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.clients import whatsapp
from app.core import cripto
from app.core.config import get_settings
from app.core.datas import hora_brt
from app.core.db import SessionLocal
from app.core.telefone import normalizar
from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
from app.models.user import User
from app.services import assistente_geracao as ger
from app.services import assistente_helper as helper

log = logging.getLogger("gs.assistente")

MAX_RODADAS = 6
HISTORICO = 20                # mensagens guardadas (user + assistant)
TETO_RESULTADO = 14000        # caracteres de cada resultado de ferramenta que vão ao modelo

DESCONHECIDO = ("Este é o bot do Gestão Solar e só atende números cadastrados. "
                "Peça à sua empresa de O&M para cadastrar este telefone na sua conta do Gestão Solar.")
NAO_LIBERADO = ("Seu acesso ao bot do WhatsApp ainda não foi liberado. "
                "Peça ao gerente da sua empresa de O&M para liberar na sua conta, "
                "com o seu token do meuWatt ou do meuPlano.")
LIMPAR = {"/novo", "novo", "/reset", "zerar", "limpar", "limpar contexto"}


# --------------------------------------------------------------------------- identidade
def conta_do_telefone(db: Session, telefone: str) -> User | None:
    """O número casa com UMA conta ativa — tolerante ao nono dígito (DDD + 8 finais)."""
    try:
        alvo = normalizar(telefone)
    except Exception:                                      # noqa: BLE001
        return None
    if not alvo:
        return None
    dig = alvo.lstrip("+")
    contas = db.scalars(select(User).where(User.ativo, User.telefone.isnot(None))).all()
    exatas = [u for u in contas if u.telefone == alvo]
    if len(exatas) == 1:
        return exatas[0]

    def chave(d: str):
        d = d.lstrip("+")
        return (d[2:4], d[-8:]) if d.startswith("55") and len(d) >= 12 else None

    cands = [u for u in contas if chave(u.telefone) == chave(dig)]
    return cands[0] if len(cands) == 1 else None


# --------------------------------------------------------------------------- manutenção
_MANUTENCAO = {"type": "function", "function": {
    "name": "manutencao",
    "description": ("Pergunta ao meuPlano (manutenção/O&M): ordens de serviço, cronograma, pendências, estoque, "
                    "spare parts, documentos e projetos da usina. Passe a pergunta COMPLETA, com usina e período."),
    "parameters": {"type": "object", "properties": {"pergunta": {"type": "string"}}, "required": ["pergunta"]}}}


#: Documento ASSINADO com o certificado digital da pessoa é ação. No meuPlano, a ferramenta de
#: PDF assina dentro de uma LEITURA (sem proposta, sem "Confirmar"), e o Gestão Solar não teria
#: como pedir a senha depois: ela é pedida AQUI, antes de o pedido sair (avaliação 11).
ASSINATURA = re.compile(r"(?i)\bassin(?:a|e|ar|em|ad[oa]s?|aturas?)\b|\bcertificado\s+digital")
#: A pergunta sobre o ESTADO ("a OS 1638 já foi assinada?", "faltam assinar quais?") é leitura —
#: se não trouxer verbo de pedido. "Pode assinar a OS?" e "me manda o PDF assinado?" são pedidos
#: com ponto de interrogação, e o "?" sozinho não separa um do outro.
_ESTADO = re.compile(r"(?i)\b(?:foi|foram|est[áa]|est[ãa]o|t[áa]|ficou|ficaram|j[áa])\s+(?:\w+\s+){0,2}?assinad[oa]s?\b"
                     r"|\bfalta(?:m|va)?\s+assinar\b|\b(?:tem|t[êe]m|h[áa]|status|situa[çc][ãa]o)\s+(?:d[ae]\s+)?assinaturas?\b")
_PEDIDO = re.compile(r"(?i)\b(?:pode|podem|poderia|consegue|conseguiria|d[áa]\s+pra|tem\s+como|manda|mande|me\s+passa|"
                     r"envia|envie|gera|gere|gerar|faz|fa[çc]a|quero|queria|preciso|assina|assine|assinem)\b")


def _pede_assinatura(texto: str) -> bool:
    """Pedido de documento ASSINADO ("me manda o PDF da OS assinado", "pode assinar a OS?"), e não
    pergunta sobre o estado da assinatura ("a OS 1638 já foi assinada?" — avaliação 12). Na dúvida,
    é pedido: o que custa é um SIM a mais, e não um documento assinado sem a pessoa saber."""
    t = texto or ""
    return bool(ASSINATURA.search(t)) and not (_ESTADO.search(t) and not _PEDIDO.search(t))


async def manutencao(ctx: ger.Contexto, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    pedido = a.get("pergunta") or ""
    ctx.credencial = ctx.credencial or _e_de_credencial(pedido)
    pergunta = pedido + "\n\n(Resposta para WhatsApp: curta, sem tabela.)"
    # A API de lá é sem estado: a conversa vai junto. Sem ela, o "sim" a uma proposta do próprio
    # meuPlano ("Confirma que eu crie assim?") chegava lá sozinho, e ele recomeçava do zero.
    mensagens = [*ctx.historico[-HISTORICO_MEUPLANO:], {"role": "user", "content": pergunta}]
    if _pede_assinatura(pedido) or _pede_assinatura(ctx.pedido):
        return _assinatura_com_senha(ctx, pedido, mensagens)
    ctx.db.commit()                                       # solta a conexão: o meuPlano leva até 2 min
    r = await _perguntar_ao_meuplano(mp, mensagens)
    ctx.segredos.extend(str(v) for v in r.pop("segredos", None) or [] if v)
    return _proposta_do_meuplano(ctx, r, mensagens) if r.get("type") == "proposal" else r


async def _perguntar_ao_meuplano(mp, mensagens: list[dict]) -> dict:
    """Um turno do assistente do meuPlano: `{texto}`, `{erro}` ou a proposta crua de lá."""
    run_id = await mp.assistente_chat(None, mensagens)
    for _ in range(60):                                   # até ~2 min
        await asyncio.sleep(2)
        r = await mp.assistente_run(None, run_id)
        if r.get("status") == "DONE":
            if r.get("type") == "proposal":
                return r
            # as senhas que o turno revelou (o meuPlano novo as entrega): somem daqui pelo VALOR
            return {"texto": r.get("text") or "", **({"segredos": r["segredos"]} if "segredos" in r else {})}
        if r.get("status") == "ERROR":
            return {"erro": r.get("error") or "O meuPlano não conseguiu responder."}
    return {"erro": "O meuPlano demorou demais para responder."}


def _assinatura_com_senha(ctx: ger.Contexto, pedido: str, mensagens: list[dict]) -> dict:
    """O pedido com assinatura digital só vai ao meuPlano depois de a pessoa CONFIRMAR (SIM)."""
    from app.services.vinculos import SemConexao, cliente_meuplano

    async def executar(db: Session, user: User, telefone: str) -> str:
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        db.commit()                                       # solta a conexão: o meuPlano leva até 2 min
        r = await _perguntar_ao_meuplano(mp, mensagens)
        if r.get("erro"):
            return f"❌ {r['erro']} Nada foi assinado."
        if r.get("type") == "proposal":
            return "O meuPlano pediu outra confirmação para isso: peça de novo, em partes. Nada foi assinado."
        return r.get("texto") or "O meuPlano não respondeu nada."

    resumo = f"Assinar com o seu certificado (ASSINATURA DIGITAL) o que você pediu ao meuPlano: «{pedido[:300]}»"
    return helper.propor(ctx, resumo, PRAZO_PROPOSTA_MP_S, executar, parte="bot_meuplano", confirmacao="sim")


#: Quantas mensagens da conversa vão ao meuPlano junto com a pergunta.
HISTORICO_MEUPLANO = 8
#: Quanto vale a proposta do meuPlano esperando o SIM (é para ler o resumo com calma).
PRAZO_PROPOSTA_MP_S = 600


#: Os números que a pessoa procura na tela, com o nome que ela usa ("sessao_id" é do sistema).
_NUMEROS = {"os_id": "OS", "task_id": "tarefa"}


def _o_que_nasceu(dados: Any, resumo: str = "") -> str:
    """O número do que o meuPlano criou ("OS 1639, PROGRAMADA") — sem ele a pessoa não acha
    na tela o que acabou de pedir. O que o resumo já diz não se repete."""
    if not isinstance(dados, dict):
        return ""
    partes = [f"{rotulo} {dados[k]}" for k, rotulo in _NUMEROS.items()
              if dados.get(k) and not re.search(rf"(?<!\d){dados[k]}(?!\d)", resumo)]
    if dados.get("status") and str(dados["status"]) not in resumo:
        partes.append(str(dados["status"]))
    return f" ({', '.join(partes)})" if partes else ""


def _desfecho_do_meuplano(resumo: str, dados: Any) -> str:
    """O que a pessoa lê depois do Sim — o RESULTADO que o meuPlano devolveu, não a proposta repetida
    (avaliação 22: desinstalar 2 inversores voltou "1 removido; 1 bloqueado" e o bot dizia "✅ Feito").
    - `erro` com 200 (o handler recusou sem gravar: "Não dá para apagar 'X': está em uso…") → ❌;
    - falha de item (`erros`: lá, todo handler que engole falha item a item a devolve — desinstalar, criar e
      apagar ligação de rede) → ⚠️ em parte, com os motivos; ❌ se todo contador do que deu certo é zero;
    - senão ✅, com o resultado dele quando vem."""
    dados = dados if isinstance(dados, dict) else {}
    if dados.get("erro"):
        return f"❌ O meuPlano recusou: {str(dados['erro']).rstrip('. ')}. Nada foi feito."
    texto = resumo + _o_que_nasceu(dados, resumo)
    if dados.get("resumo"):
        texto = f"{resumo.rstrip('. ')}{_o_que_nasceu(dados, resumo)} — resultado: {str(dados['resumo']).rstrip('. ')}."
    erros = dados.get("erros") or []
    if erros:
        if not dados.get("resumo"):
            texto = f"{resumo.rstrip('. ')} — {len(erros)} item(ns) com falha."
        motivos = [str(e["detail"]) for e in erros if isinstance(e, dict) and e.get("detail")]
        lista = "".join(f"\n• {m}" for m in motivos[:5]) + (f"\n• … e mais {len(motivos) - 5}" if len(motivos) > 5 else "")
        # todo contador do que deu certo em zero ("0 equipamento(s) removido(s)"): nada foi feito — "EM PARTE" mentia
        # (avaliação 23). O que foi pulado por já estar vazio não é feito.
        contadores = [v for k, v in dados.items() if type(v) is int and not k.startswith("pulados")]
        if contadores and not any(contadores):
            return f"❌ O meuPlano recusou: {texto}{lista}\n\nNada foi feito."
        return f"⚠️ Feito EM PARTE no meuPlano: {texto}{lista}"
    return f"✅ Feito no meuPlano: {texto}"


def _o_que_ficou(p: Any) -> str:
    """O que do pedido da pessoa foi feito e o que não foi, quando um passo falha — nas palavras
    DELA, nunca a instrução que o bot mandou ao meuPlano (avaliação 13)."""
    de = f"Do seu pedido «{p.pedido[:200]}»" if p.pedido else "Do seu pedido"
    if p.feitos:
        return (f"{de}, antes disso já foi feito: {'; '.join(p.feitos)}. O resto não foi feito — confira e peça de "
                "novo o que faltar.")
    return f"{de}, nada além disso foi feito — confira e peça de novo o que faltar."


#: O campo de acesso com nome de senha (o mesmo critério do meuPlano para o que ele revela).
_CHAVE_DE_SENHA = re.compile(r"(?i)senha|passw|pwd|\bpin\b|chave|token|segredo|secret|community")


def _valores_secretos(args: Any) -> list[str]:
    """Os valores de senha de uma proposta do meuPlano — os `campos` de gravar ou alterar um acesso, marcados como
    segredo ou com nome de senha. A prévia de lá já os esconde; a mensagem da pessoa e o log, não."""
    campos = args.get("campos") if isinstance(args, dict) else None
    return [str(c["valor"]) for c in campos if isinstance(c, dict) and c.get("valor")
            and (c.get("is_segredo") or _CHAVE_DE_SENHA.search(str(c.get("chave") or "")))] if isinstance(campos, list) else []


def _proposta_do_meuplano(ctx: ger.Contexto, r: dict, conversa: list[dict] | None = None,
                          feitos: tuple[str, ...] = ()) -> dict:
    """Ação do assistente do meuPlano (criar/concluir OS, lançar o dia, lembrete…) volta como
    PROPOSTA: nada foi gravado lá. A pessoa confirma com SIM (pedido do dono, 24/10/2026: a senha
    de atuação é para equipamento — "desligar, ligar, gravar" —, e o bot a cobrava para concluir
    uma OS); o Gestão Solar chama o `/assistant/apply` de lá com o token DELA — é o "Confirmar" da
    web, e o meuPlano revalida os argumentos e a permissão. `conversa` deixa o bot seguir para o
    próximo passo do mesmo pedido depois de feito."""
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuplano

    acao, args = r.get("action") or "", r.get("args") or {}
    previa = r.get("preview") or {}
    resumo = previa.get("summary") or acao or "ação no meuPlano"
    ctx.digitados.extend(_valores_secretos(args))          # "salve a senha do Wi-Fi: rede / X" — o X some de tudo

    async def executar(db: Session, user: User, telefone: str) -> str:
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()                                   # solta a conexão enquanto o meuPlano grava
            feito = await mp.assistente_aplicar(None, acao, args)
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                motivo = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
                return f"❌ O meuPlano recusou: {motivo}. Nada foi feito."
            # 5xx é erro NO MEIO: lá a rota grava antes do passo que quebra (a OS 1843 ficou vazia
            # com "nada foi feito" na tela, 24/10/2026). E o texto da exceção não vai à pessoa.
            log.warning("assistente: o meuPlano deu %s ao aplicar %s: %s", e.response.status_code, acao,
                        detalhe_do_upstream(e.response))
            return ("⚠️ O meuPlano deu erro no meio da ação — ela PODE ter sido gravada em parte. Confira no "
                    "meuPlano antes de pedir de novo.")
        except httpx.HTTPError:
            return ("⚠️ O meuPlano não respondeu a tempo — a ação PODE ter sido gravada. "
                    "Confira no meuPlano antes de pedir de novo.")
        return _desfecho_do_meuplano(resumo, (feito or {}).get("data"))

    linhas = [ln.get("text") for ln in previa.get("lines") or []]
    # Até 15 linhas no resumo; o resto, dito — a pessoa não confirma o que não viu (avaliação 20)
    detalhes = linhas[:15] + ([f"… e mais {len(linhas) - 15} — veja a lista inteira no meuPlano antes de confirmar"]
                              if len(linhas) > 15 else [])
    proposta = helper.propor(ctx, resumo, PRAZO_PROPOSTA_MP_S, executar, detalhes, previa.get("warnings") or [],
                             parte="bot_meuplano", confirmacao="sim", conversa=conversa, feitos=feitos,
                             acao=(acao, args))
    proposta["detalhes"], proposta["avisos"] = detalhes, previa.get("warnings") or []
    return proposta


FERRAMENTAS = {**ger.FERRAMENTAS, "manutencao": (manutencao, _MANUTENCAO), **helper.FERRAMENTAS}


#: Mensagem mais velha que isto não é respondida (fica no log como `atrasada`).
MAX_ATRASO = timedelta(hours=2)


def _enviada_em(ocorrida_em: str | None) -> datetime | None:
    """A hora em que a PESSOA mandou (a da Meta), não a em que chegou aqui."""
    if not ocorrida_em:
        return None
    try:
        quando = datetime.fromisoformat(ocorrida_em)
    except ValueError:
        return None
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


def _atrasada(ocorrida_em: str | None) -> bool:
    quando = _enviada_em(ocorrida_em)
    return quando is not None and datetime.now(UTC) - quando > MAX_ATRASO


# --------------------------------------------------------------------------- log
#: "senha: 1234", "a senha do cadeado é ab12", "PIN 4821": o valor sai do log (o adm e o gerente
#: leem o log; a conversa com a pessoa continua inteira). Só com separador ou com dígito logo
#: depois — "[senha de atuação]" e "a senha de vocês" ficam como estão, e "a senha de novo até
#: as 14:32" também (o trecho até o ":" não tem número). O valor nunca começa em "[": os
#: marcadores do bot ("Senha:[senha oculta]") ficam inteiros (avaliação 11). E tem 3 caracteres
#: ou mais, sem o trecho atravessar o fim da frase: "a senha é a mesma" e "senha de atuação. Quem
#: define isso é o gerente" ficam inteiros (avaliação 13).
_DE_ACESSO = r"(?=[ \t]+d[eoa]s?[ \t]+(?:port[ãa]o|porteira|cadeado|porta|acesso|cofre|guarita|cerca))"
#: O verbo que liga a senha ao valor ("é", "ficou", "será") e o adjetivo que pode vir antes ("a senha NOVA ficou X" —
#: avaliação 24).
_LIGA = r"(?:\b(?:é|eh|ficou|fica|ser[áa]|virou|era)\b)"
_ADJ = r"(?:\s+(?:nova|antiga|atual|padr[ãa]o|certa|correta|tempor[áa]ria|provis[óo]ria))?"
_SEGREDO = re.compile(r"(?i)\b(senha|password|pin|segredo|c[óo]digo" + _DE_ACESSO + r")\b"
                      # "do inversor 13", "do IP 10.1.130.2": dígito pode, ponto só entre dígitos — o fim da frase
                      # não ("senha de atuação. Quem define é Marcos" fica inteiro — avaliação 13; "senha do
                      # inversor 13 é 4821" passava em claro)
                      # O ":" depois de número só com espaço em seguida ("Senha do inversor 13: 4821" passava em
                      # claro — avaliação 23); a hora ("até as 14:32") não tem espaço e fica inteira.
                      r"((?:\s+d[eoa]s?\s+(?:[^\n:=.!?;]|(?<=\d)\.(?=\d)){1,40}?)?" + _ADJ + r"\s*"
                      r"(?:" + _LIGA + r"\s*[:=]?|(?<!\d)[:=]|:(?=\s))\s*)"
                      r"(?![\[:=])"
                      r"([^\s,;]{3,}?)"
                      r"(?=[.!?]*(?:\s|$|[,;]))")
#: "senha 1234", "PIN ab12": três caracteres ou mais — "PIN 3 do conector" e "senha 2 vezes" são
#: dado técnico e prosa, não segredo.
_SEGREDO_NUM = re.compile(r"(?i)\b(senha|password|pin)(\s+)(?!\[)(?=[^\s,;]{3})([^\s,;]*?\d[^\s,;]*?)"
                          r"(?=[.!?]*(?:\s|$|[,;]))")
#: "Altere a senha do cadeado de pirapozinho para 3262" (estava em claro no log de produção,
#: avaliação 9). Com "para/pra" o valor precisa ter dígito: "senha para o gerente" é prosa.
_SEGREDO_PARA = re.compile(r"(?i)\b(senha|password|pin|segredo|c[óo]digo" + _DE_ACESSO + r")\b"
                           r"((?:\s+d[eoa]s?\s+[^\n:=]{1,40}?)?\s+(?:para|pra)\s+)"
                           r"(?!\[)([^\s,;]*?\d[^\s,;]*?)(?=[.!?]*(?:\s|$|[,;]))")
#: O NÚMERO inteiro, com qualquer pontuação antes e com os grupos ("senha,482913",
#: "senha/482913", "pin 482 913", "senha do cadeado 3262", "o código do portão 4455" — em claro
#: no log até a avaliação 10), de 3 dígitos ou mais. "código" e "combinação" só de
#: porta/portão/cadeado/cofre: "código de erro 2043" e "combinação de strings 12" são dado útil.
#: Hora ("até as 14:32") não é segredo.
_SEGREDO_NUMERO = re.compile(
    r"(?i)\b(senha|password|pin|segredo|combina[çc][ãa]o" + _DE_ACESSO + r"|c[óo]digo" + _DE_ACESSO + r")\b"
    r"((?:[ \t]+d[eoa]s?[ \t]+(?:[^\W\d_][\w\-]*[ \t]+){0,3}?[^\W\d_][\w\-]*)?[ \t]*"
    r"(?:\b(?:é|eh|para|pra)\b)?[ \t:=,;/.\-(]*)"
    # o número escrito de qualquer jeito, pelo mesmo leitor da senha: "(482) 913" e "quatro 8 dois 9 um 3"
    # ficavam pela metade ("•••• 913" — avaliação 21)
    r"(" + helper.NUMERO.pattern + r")(?!\d|[:h]\d)")


#: A seta ou o travessão LOGO depois da palavra ("Senha – 482913", "Senha → Huawei@123", "senha -> Changeme1") e a
#: palavra no meio de uma lista de credenciais ("Usuário admin / senha changeme", "admin | senha x") — avaliação 24.
#: O travessão depois de "senha de atuação — sem ela…" é prosa (não vem logo depois da palavra).
_SEGREDO_SETA = re.compile(r"(?i)\b(senha|password|pin)(\s*(?:->|=>|→|–|—)\s*)(?!\[)([^\s,;]{3,}?)"
                           r"(?=[.!?]*(?:\s|$|[,;]))")
_SEGREDO_LISTA = re.compile(r"(?i)(?:(?<=[/|·•][ \t])|(?<=[/|·•]))(senha|password|pin)([ \t]+)(?!(?:d[eoa]s?)\b)(?!\[)"
                            r"([^\s,;]{3,}?)(?=[.!?]*(?:\s|$|[,;]))")
#: O segundo segredo da mesma frase ("a senha do 3 é •••• e do 4 é sungrow4").
_SEGREDO_EM_SEGUIDA = re.compile(r"(••••)(\s+e\s+d[eoa]s?\s+[^\n:=.!?;]{1,40}?\s*(?:\bé\b|:)\s*)(?!\[)"
                                 r"([^\s,;]{3,}?)(?=[.!?]*(?:\s|$|[,;]))")
#: O número logo depois de "senha da OS", "senha do IP"… é o IDENTIFICADOR, não o segredo; e data e IP nunca
#: são o segredo (avaliação 22: "senha da OS ••••" e datas sumiam do log).
_IDENTIFICADOR = re.compile(r"\b(?:os|ip|uc|usina|inversor|tarefa|ponto|string|n[óo]|protocolo|contrato|chamado|item)"
                            r"[ \t]*$", re.IGNORECASE)


#: As palavras COMUNS — artigo, preposição, pronome, advérbio, o verbo do dia a dia e as palavras do próprio assunto
#: (senha, nível, ficha, cofre, gerente…). Logo depois de "senha …:", a palavra comum é PROSA ("Senha: você não tem
#: nível", "Credenciais: ficam no cofre", "Senha — fale com o Kewyn"; avaliação 26: 10 de 10 eram comidas), e é nela que o
#: valor TERMINA ("a senha é changeme para o usuário admin": só o "changeme" some). Lista FECHADA: o valor é o que não
#: está nela ("changeme", "admin", "Huawei@123").
_COMUNS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas num numa por pelo pela pelos pelas para pra pro com sem sob
sobre entre até ate após apos antes depois desde contra ao aos à às disso desse dessa deste desta nisso nesse nessa neste
nesta e ou mas nem que se como quando onde porque pois porém porem então entao logo assim enquanto embora caso conforme
também tambem já ja ainda só so apenas somente mesmo mesma mesmos mesmas mais menos muito muita muitos muitas pouco pouca
bem mal aqui ali lá la aí ai agora hoje ontem amanhã amanha sempre nunca talvez acima abaixo dentro fora perto longe sim
não nao direto inclusive exatamente eu você voce vocês voces ele ela eles elas nós me te lhe lhes meu minha meus minhas
seu sua seus suas dele dela deles delas nosso nossa este esta estes estas esse essa esses essas aquele aquela aqueles
aquelas isto isso aquilo cada todo toda todos todas tudo nada ninguém ninguem alguém alguem algum alguma alguns algumas
nenhum nenhuma outro outra outros outras qual quais quem quanto quanta qualquer é eh são sao era eram foi foram ser será
sera seria sido está estão estao estava estar tem têm tinha ter há ha havia houve pode podem poder deve devem precisa
precisam preciso fica ficam ficou ficar vai vão vao vou ir vem faz fazer feito feita diz sabe sei quer pede pedir peça
peca fale falar consulte consultar cadastre cadastrar cadastrou confirme confirmar confirma veja ver vê ve use usar usa
entre entrar mande mandar manda acesse acessar ligue ligar abra abrir troque trocar troca trocou mude mudar mudou defina
definir informe informar procure procurar pergunte perguntar chame chamar verifique verificar confira conferir solicite
solicitar passe passar digite digitar envie enviar aguarde aguardar tente tentar existe existem consta segue seguir
continua continuar recebe receber cuida guarda libera ajuda senha senhas acesso acessos nível nivel níveis niveis gerente
técnico tecnico técnica cliente clientes usuário usuario usuários usuarios dono dona pessoa pessoas equipe empresa ficha
cofre aba sistema conta contas meuplano meuwatt helper bot whatsapp web site tela página pagina app aplicativo ação acao
ações acoes pedido mensagem resposta equipamento equipamentos usina usinas inversor modelo fábrica fabrica cadastro
registro informação informacao dados caso vez vezes dia dias semana hora horas minuto minutos tempo momento engano
problema dúvida duvida motivo segurança seguranca regra permissão permissao gerência gerencia suporte administrador
plataforma operação operacao manutenção manutencao campo nota observação observacao lista código codigo número numero
valor definida definido pessoal secreta secreto individual única unica numérica numerica nova novo antiga antigo igual
diferente errada errado certa certo correta correto válida valida inválida invalida pedida necessária necessaria
obrigatória obrigatoria padrão padrao comparada conferida enviada mandada escondida guardada cifrada criptografada
trocada alterada usada exigida solicitada cadastrada configurada digitada dita temporária temporaria provisória
provisoria bloqueada bloqueado desconhecida desconhecido forte fraca longa curta fornecida informada expirada vencida
incorreta segura seguro fácil facil difícil dificil simples opcional disponível disponivel possível possivel
impossível impossivel responsabilidade critério criterio vale ok okay beleza obrigado obrigada valeu combinado
entendi entendido pronto claro favor infelizmente felizmente atualmente normalmente geralmente provavelmente realmente
basta depende segundo olha olhe lembre lembrando atenção atencao importante obs aviso cuidado recomendo sugiro evite
serve funciona expirou venceu bloqueou acabou chegou contate contato escreva responda clique toque selecione escolha
insira coloque utilize criar rede login logins wi-fi wifi smartlogger roteador datalogger logger container cadeado
portão portao o&m ufv cliente técnico diga dizer desligar gravar grave ler leia escrever alterar altere mudar fechar
feche crie apagar apague remover remova instalar configurar configure testar teste concluir conclua registrar registre
lançar lance programar aprovar executar responder ajustar ajuste buscar busque encontrar encontrei achar olhar trata
parâmetro parâmetros linha linhas resumo prazo botão botões frase dado data relé caixa alarme alarmes comunicação
leitura escrita equipe chave chaves pin pins password credencial credenciais
""".split())
#: O número seguido da unidade é tamanho, contagem ou medida, não o segredo ("O PIN é 4 dígitos", "Senha errada 5 vezes",
#: "140 °C", "250 kWp").
_UNIDADE = {"dígitos", "digitos", "dígito", "digito", "caracteres", "letras", "números", "numeros", "vezes", "minutos",
            "min", "horas", "dias", "tentativas"}
_MEDIDA = re.compile(r"[ \t]*(?:%|°|(?:k?Wh?p?|MWh?|kV|V|A|mA|Hz)\b)")


def _e_prosa(m: re.Match) -> bool:
    """O que vem depois de "senha … é/:" é PROSA, não o segredo: a palavra comum ("é definida no oem-gs", "é pessoal",
    "agora é X" — o "agora" não é a senha; avaliação 26: sumia o "agora" e ficava a senha)."""
    return m.group(3).strip(_BORDA).lower() in _COMUNS


#: O ASSUNTO de acesso: senha, PIN, credencial, login, cadeado, Wi-Fi, a chave da rede/do portão, "entre com", "dados de
#: acesso"… (avaliação 27: a senha de texto livre — wiki, OS, relato — vinha sem a palavra "senha": "o cadeado abre com
#: 3262", "rede ufv-tiete / changeme", "login admin / X"). A LINHA assim tem todo valor escondido (`_sem_credencial`); e,
#: no turno que trata do assunto, o texto livre da resposta fica fora do log. Não conta o conceito do bot (`_DO_BOT`).
_CREDENCIAL = re.compile(r"(?i)\b(?:senhas?|passwords?|pass|passwd|pwd|pins?|credenc\w*|passcodes?|logins?|logar|"
                         r"cadeados?|wi-?fi|acessos|dados de acesso|acesso (?:d[oa]s?|ao|à|web|remoto|ssh|snmp)|"
                         r"usu[áa]rio e senha|usu[áa]rio:? \S+(?:,| /)|entr(?:e|ar|a|o) (?:com|no|na)|"
                         r"chaves? (?:d[aoe]s? )?(?:wi-?fi|rede|acesso|port[ãa]o|porta|cadeado|cofre)|chave (?:é|:))"
                         r"(?!\w)")                         # "passo" não é "pass", "pino" não é "pin"
_DO_BOT = re.compile(r"(?i)senha de atua|\[(?:senha|n[úu]mero) ")      # "sua senha do SmartLogger é X" não é do bot
#: Na linha do assunto, todo separador pode trazer o valor — também a vírgula e a barra ("usuário admin, X", "admin / X")
#: e o verbo que liga a senha ao valor ("continua X", "virou X"). O ":" entre dois números é a hora ("14:32").
_SEPARADOR = re.compile(r"(?i)\*{0,2}[ \t]*(?:(?<!\d)[:=]|[:=](?!\d))\*{0,2}|[ \t]*(?:->|=>|→|–|—|\||,)|[ \t]+/|"
                        r"[ \t]+(?:é|eh|s[ãa]o|ficou|fica|era|ser[áa]|virou|continua|segue|permanece|passou a ser|"
                        r"mudou para)\b")
#: …e a palavra de senha seguida do valor, sem separador ("a senha changeme", "chave X", "PIN ab12", "login admin").
_PALAVRA_DE_SENHA = re.compile(r"(?i)\b(?:senhas?|passwords?|pass|passwd|pwd|pins?|chaves?|logins?)\b\*{0,2}(?=[ \t])")
#: A palavra de ENCHIMENTO entre o separador e o valor ("é a X", "é sempre X", "é ainda X" — avaliação 27).
_ENCHIMENTO = {"a", "o", "as", "os", "um", "uma", "sempre", "ainda", "também", "tambem", "mesmo", "mesma", "só", "so",
               "apenas", "agora", "hoje", "igual"}
_DETERMINANTE = {"a", "o", "as", "os", "um", "uma"}
#: A pontuação e o Markdown em volta da palavra ("**Nova@2024**", "`X`", "(não"); "•": o que já foi escondido.
_BORDA = "*_`'\"«»“”()[]{}<>.,;:!?•"
_CODIGO = re.compile(r"`([^`\n]+)`")
#: Dentro do BLOCO de credenciais (abaixo de "Senhas:"), o separador da linha de valor ("• SL1: X", "- SL1 → X",
#: "a do SL2 é X"), o marcador de lista e a cerca do bloco de código.
_SEP_DO_BLOCO = re.compile(r"(?i)[ \t]*(?:(?<!\d)[:=]|[:=](?!\d))\*{0,2}|[ \t]+(?:é|eh|s[ãa]o)\b|[ \t]*(?:->|=>|→|–|—|\|)")
_MARCADOR = re.compile(r"[ \t]*(?:(?:[-*•·]|\d+[.)])[ \t]+)?")
_CERCA = re.compile(r"[ \t]*(?:```|~~~)")
#: O que tem letra e número mas é NOME, não senha: o código de equipamento ("INV-13", "QGBT-02", "SUN2000", "L2"),
#: o e-mail, o endereço, o dinheiro ("R$1.500") e o número de OS/tarefa ("OS#1638").
_NAO_E_SENHA = re.compile(r"^(?:[A-Z]{1,8}[-_]?\d{1,6}[A-Z]?|[^@\s]+@[^@\s]+\.[a-z]{2,}|\S*(?:://|www\.)\S*|R\$\S*|"
                          r"[A-Za-z]*#\d+)$")
_ENDERECO = re.compile(r"\S*(?:://|www\.)\S*|[^@\s]+@[^@\s]+\.[a-z]{2,}")


def _palavras(trecho: str) -> list[str]:
    """As palavras do trecho, sem a pontuação e o Markdown em volta e sem o artigo — a palavra INTEIRA: "Nova@2024"
    não é a palavra comum "nova" (avaliação 26)."""
    return [p for p in (t.strip(_BORDA).lower() for t in trecho.split()) if p and p not in _DETERMINANTE]


def _onde_esta_o_valor(trecho: str, pular: bool = False) -> tuple[int, int] | None:
    """Onde está o VALOR que vem no começo de `trecho` (início e fim); None quando não há valor — a primeira palavra é
    comum ou é tamanho ("4 dígitos"). O valor são as palavras fora de `_COMUNS` até a primeira comum ou o fim da frase:
    "changeme para o usuário admin" → "changeme"; "SL1 Huawei@123, SL2 Changeme1" → tudo. `pular`: um enchimento antes
    do valor não é prosa ("é a changeme", "é sempre X")."""
    tokens = list(re.finditer(r"\S+", trecho))
    inicio = fim = None
    for i, m in enumerate(tokens):
        nucleo = m.group(0).strip(_BORDA + "/|·—–-").lower()
        if not nucleo:                                     # "/", "|", "—" e o •••• já posto: ligam os valores…
            if m.group(0).endswith((".", "!", "?", ";")):  # …mas o fim da frase fecha ("Senha: ••••. Kewyn tem…")
                break
            continue
        if pular and fim is None and nucleo in _ENCHIMENTO and i + 1 < len(tokens):
            pular = False
            continue
        if nucleo in _COMUNS or (fim is None and (len(nucleo) < 3 or helper._data_ou_ip(nucleo) or nucleo.isdigit()
                                                  and i + 1 < len(tokens)
                                                  and tokens[i + 1].group(0).strip(_BORDA).lower() in _UNIDADE)):
            break                                          # "PIN 3 do conector", "4 dígitos", "senha 24/10": não é ela
        inicio = m.start() if inicio is None else inicio
        fim = m.end()
        if m.group(0).endswith((".", "!", "?", ";")):      # o fim da frase fecha o valor
            break
    return None if fim is None else (inicio, fim)


def _esconde_valor(linha: str, pos: int, pular: bool = False) -> str | None:
    """A linha com o valor que começa em `pos` trocado por ••••, guardadas a pontuação e o Markdown em volta; None se
    não há valor."""
    onde = _onde_esta_o_valor(linha[pos:], pular)
    if onde is None:
        return None
    ini, fim = pos + onde[0], pos + onde[1]
    m = re.match(r"([*_`'\"«“(\[]*)(.*?)([*_`'\"»”)\].,;:!?]*)$", linha[ini:fim], re.DOTALL)
    return linha[:ini] + m.group(1) + "••••" + m.group(3) + linha[fim:]


def _sem_forma_de_senha(trecho: str, forte: bool = False) -> str:
    """A palavra com cara de senha some: com minúscula, número e símbolo ("Huawei@123", "Solar#2026x" — `forte`, valendo
    em qualquer texto; avaliação 27: "S3=139,5", "PR=82,5%", "MPPT1+MPPT2", "2043@INV-13", "CB-03#2" sumiam) ou, na
    linha do assunto de acesso, letra e número ("Changeme1", "pw1111"). Fica o que é nome (`_NAO_E_SENHA`)."""
    def troca(m: re.Match) -> str:
        nucleo = m.group(0).strip(_BORDA)
        if (len(nucleo) < (6 if forte else 4) or _NAO_E_SENHA.match(nucleo) or not re.search(r"\d", nucleo)
                or not re.search(r"[a-zß-ÿ]" if forte else r"[^\W\d_]", nucleo)
                or (forte and not re.search(r"[@#$&*!]", nucleo))):
            return m.group(0)
        return m.group(0).replace(nucleo, "••••")
    return re.sub(r"\S+", troca, trecho)


def _sem_numero_solto(linha: str) -> str:
    """Na linha do assunto de acesso, o número de 3 dígitos ou mais é o segredo ("o cadeado abre com 3262") — menos o
    identificador ("OS 1721", "tarefa 8873"), a data, a hora, o IP e a medida ("140 °C", "250 kWp", "5 vezes")."""
    def troca(m: re.Match) -> str:
        if (_IDENTIFICADOR.search(linha[:m.start()]) or helper._data_ou_ip(m.group(0)) or _MEDIDA.match(linha, m.end())
                or re.match(r"[ \t]+(?:" + "|".join(_UNIDADE) + r")\b", linha[m.end():], re.IGNORECASE)):
            return m.group(0)
        return "••••"
    return re.sub(r"(?<![\w.,/:#@$•-])\d{3,}(?![\w.,/:@•-]?\d)", troca, linha)


def _sem_credencial(linha: str) -> str:
    """A linha que é assunto de acesso: some o VALOR depois de cada separador e de cada palavra de senha (até a primeira
    palavra comum, pulando um enchimento), o número solto, a palavra com letra e número e o valor entre crases. Fica a
    prosa ("Senha: você não tem nível", "Senha — fale com o Kewyn"), o endereço e o e-mail, e o conceito do bot."""
    if _DO_BOT.search(linha):
        return linha
    guardados: list[str] = []                              # endereço e e-mail não têm valor dentro (o ":" do https)

    def guarda(m: re.Match) -> str:
        guardados.append(m.group(0))
        return f"\x00{len(guardados) - 1}\x00"
    linha = _ENDERECO.sub(guarda, linha)
    linha = _CODIGO.sub(lambda m: m.group(0) if _CREDENCIAL.search(m.group(1)) else "`••••`", linha)
    pos = 0
    while candidatos := [m for m in (_SEPARADOR.search(linha, pos), _PALAVRA_DE_SENHA.search(linha, pos)) if m]:
        m = min(candidatos, key=lambda x: x.end())
        novo = _esconde_valor(linha, m.end(), pular=True)
        linha, pos = (novo, m.end() + 4) if novo is not None else (linha, m.end())
    linha = _sem_forma_de_senha(_sem_numero_solto(linha))
    return re.sub(r"\x00(\d+)\x00", lambda m: guardados[int(m.group(1))], linha)


def _sem_credenciais(texto: str, todas: bool = False) -> str:
    """Linha a linha: a do assunto de acesso (ou, com `todas`, cada linha) por `_sem_credencial`; e a linha de credencial
    que TERMINA em ":" ("Senhas:", "**Senha do SmartLogger:**", "As credenciais são:") abre um BLOCO até o fim da
    resposta: o valor vem nas linhas de baixo — em lista, no bloco de código ou sozinho (avaliação 26). No bloco, a
    linha de valor perde o valor depois do separador, a curta (menos de 4 palavras) o valor que ela é, e a frase, a
    palavra com cara de senha. A prosa fica inteira ("- SmartLogger: só o admin vê")."""
    saida, bloco, cerca = [], False, False
    for linha in texto.split("\n"):
        if _CERCA.match(linha):
            cerca = not cerca
            saida.append(linha)
        elif bloco and cerca and linha.strip():
            saida.append("••••")                            # o bloco de código abaixo de "Senhas:" é todo valor
        elif (todas or _CREDENCIAL.search(linha)) and not _DO_BOT.search(linha):
            mascarada = _sem_credencial(linha)
            if todas and mascarada == linha and len(_palavras(linha)) < 4:
                mascarada = _esconde_valor(linha, 0) or linha  # na mensagem do assunto, a linha curta é o valor
            saida.append(mascarada)
            bloco = bloco or (bool(_CREDENCIAL.search(linha)) and linha.rstrip(" \t*_").endswith(":"))
        elif not bloco or not linha.strip():
            saida.append(linha)
        else:
            marcador = _MARCADOR.match(linha).group(0)
            conteudo = linha[len(marcador):]
            sep = None if cerca else _SEP_DO_BLOCO.search(conteudo)
            if cerca:
                novo = "••••"
            elif sep is not None:
                novo = _esconde_valor(conteudo, sep.end())
            elif len(_palavras(conteudo)) < 4:
                novo = _esconde_valor(conteudo, 0)
            else:
                novo = _sem_forma_de_senha(conteudo)
            saida.append(marcador + (novo if novo is not None else conteudo))
    return "\n".join(saida)


def _so_tracos(linha: str) -> bool:
    return "-" in linha and all(set(c.strip()) <= set("-: ") for c in linha.split("|"))


def _sem_coluna_de_senha(texto: str) -> str:
    """A tabela com COLUNA de senha ("| Equipamento | Usuário | Senha |", ou sem a barra da frente e com a linha de
    traços embaixo — avaliação 26): o valor dela some nas linhas de baixo."""
    linhas, colunas = texto.split("\n"), None             # None: fora de tabela; senão, as colunas de senha
    for i, linha in enumerate(linhas):
        if "|" not in linha:
            colunas = None
            continue
        celulas = linha.split("|")
        if colunas is None:
            if linha.lstrip().startswith("|") or (i + 1 < len(linhas) and _so_tracos(linhas[i + 1])):
                colunas = {j for j, c in enumerate(celulas) if _CREDENCIAL.search(c) and not _DO_BOT.search(c)}
        elif colunas and not _so_tracos(linha):
            linhas[i] = "|".join(" •••• " if j in colunas and c.strip() else c for j, c in enumerate(celulas))
    return "\n".join(linhas)


def _e_de_credencial(texto: str) -> bool:
    """O texto trata de acesso (`_CREDENCIAL`) — sem contar o conceito do bot ("senha de atuação", os marcadores)."""
    return bool(_CREDENCIAL.search(_DO_BOT.sub(" ", texto or "")))


#: O texto LIVRE (da IA ou do meuPlano) de um turno que trata de acesso não vai ao log nem à cópia do gateway: a senha de
#: texto livre (wiki, OS, relato) não está na lista do meuPlano, e a máscara pelo formato sempre deixa um formato
#: escapar (avaliação 27). Os blocos do sistema (o resumo da ação, o ✅) ficam.
RESPOSTA_OMITIDA = ("[resposta fora do log: trata de acesso ou senha de equipamento — a pessoa recebeu a resposta "
                    "inteira; o meuPlano registra cada senha do cofre que revela]")


def _sem_valores(texto: str, valores: Sequence[str]) -> str:
    """Cada VALOR conhecido (a senha que o meuPlano revelou no turno, a que a pessoa mandou gravar) some, onde estiver e
    escrito como estiver — o valor inteiro, de 3 caracteres ou mais ("123" não come o "1234" da OS)."""
    for v in sorted({v for v in valores if v and len(v) >= 3}, key=len, reverse=True):
        texto = re.sub(rf"(?<!\w){re.escape(v)}(?!\w)", "••••", texto)
    return texto


def _sem_segredos(texto: str, valores: Sequence[str] = (), credencial: bool = False) -> str:
    """O texto como fica guardado (log, gateway): sem os valores conhecidos e sem o que tem forma de segredo. Com
    `credencial` (a mensagem de um turno que trata de acesso — "grava aí: SL2, usuário admin, changeme"), cada linha
    passa pela máscara do assunto, como a linha que fala de senha."""
    texto = _sem_valores(texto, valores)
    # O do número primeiro: os outros mascaram só o primeiro grupo ("pin •••• 913").
    texto = _SEGREDO_NUMERO.sub(
        lambda m: m.group(0) if (len(helper._so_digitos(m.group(3))) < 3 or helper._data_ou_ip(m.group(3))
                                 or _IDENTIFICADOR.search(m.group(2))) else m.group(1) + m.group(2) + "••••", texto)
    for padrao in (_SEGREDO, _SEGREDO_SETA, _SEGREDO_LISTA, _SEGREDO_EM_SEGUIDA):
        texto = padrao.sub(lambda m: m.group(0) if helper._data_ou_ip(m.group(3)) or _e_prosa(m) or _DO_BOT.search(m.group(0))
                           else m.group(1) + m.group(2) + "••••", texto)
    for padrao in (_SEGREDO_PARA, _SEGREDO_NUM):
        texto = padrao.sub(lambda m: m.group(0) if helper._data_ou_ip(m.group(3)) else m.group(1) + m.group(2) + "••••",
                           texto)
    return _sem_forma_de_senha(_sem_credenciais(_sem_coluna_de_senha(texto), todas=credencial), forte=True)


def _registrar(db: Session, telefone: str, user: User | None, resultado: str, *,
               pergunta: str | None = None, resposta: str | None = None,
               ferramentas: list[str] | None = None, inicio: float | None = None,
               erro: str | None = None, em: datetime | None = None, valores: Sequence[str] = (),
               credencial: bool = False) -> None:
    """Uma linha no log do bot (adm-gs → Log do bot). Falhar aqui nunca derruba a resposta.

    ponytail: guarda tudo, sem expurgo; quando o volume pesar, apaga o que passou de 90 dias.
    """
    try:
        db.add(RegistroBot(
            telefone=telefone[:20], gs_user_id=user.id if user else None,
            empresa_id=user.empresa_id if user else None, resultado=resultado,
            ferramentas=",".join(dict.fromkeys(ferramentas or [])) or None,
            pergunta=(pergunta or None) and _sem_segredos(pergunta, valores, credencial)[:4000],
            resposta=(resposta or None) and (resposta if resposta == RESPOSTA_OMITIDA
                                             else _sem_segredos(resposta, valores))[:8000],
            duracao_ms=int((monotonic() - inicio) * 1000) if inicio else None,
            erro=(erro or None) and _sem_segredos(erro, valores)[:1000],
            **({"em": em} if em else {}),
        ))
        db.commit()
    except Exception:                                      # noqa: BLE001
        log.warning("assistente: não gravou o log do bot", exc_info=True)
        db.rollback()


def permitidas(user) -> list[str]:
    """As ferramentas que a IA RECEBE para esta pessoa — liberadas pelo gerente, por produto,
    E com o token dela (`User.bot_ativo`). A que não vem na lista não existe para o modelo
    (nem para `_executar`)."""
    nomes: list[str] = []
    ativo = user.bot_ativo
    if "bot_meuwatt" in ativo:
        nomes += list(ger.FERRAMENTAS)
    if "bot_meuplano" in ativo:
        nomes.append("manutencao")
    if "bot_helper" in ativo and helper.configurado():
        nomes += list(helper.FERRAMENTAS)
    return nomes


# --------------------------------------------------------------------------- orquestrador
def _sistema(ctx: ger.Contexto) -> str:
    usinas = (f"o meuWatt não respondeu agora ({ctx.mw_falha}) — geração indisponível nesta mensagem"
              if ctx.mw_falha else ", ".join(u["nome"] for u in ctx.usinas.values()) or "nenhuma com monitoramento")
    ativo = ctx.user.bot_ativo
    areas = [n for n, c in (("geração/monitoramento (meuWatt)", "bot_meuwatt"),
                            ("manutenção (meuPlano)", "bot_meuplano"),
                            ("a usina ao vivo pelo helper", "bot_helper")) if c in ativo
             and (c != "bot_helper" or helper.configurado())]
    return f"""Você é o assistente do Gestão Solar no WhatsApp. Hoje é {ger.hoje().isoformat()} (America/Sao_Paulo).
Fala com {ctx.user.nome} ({ctx.user.apelido}). Usinas com monitoramento liberadas: {usinas}.
Liberado para esta pessoa: {", ".join(areas) or "nada"}. Pergunta de área NÃO liberada: diga que o acesso
a essa parte não está liberado e que o gerente da O&M pode liberar — não tente responder de outro jeito.

- Geração, inversores, PR, produtividade, irradiação, PVsyst, paradas de inversor, relatório/gráfico do
  monitoramento → ferramentas de geração. Manutenção (OS, cronograma, pendências, estoque, documentos,
  projetos) → `manutencao`. Pergunta que mistura → chame as duas.
- Equipamento AO VIVO (ler inversor/relé/caixa agora, testar comunicação, alarmes do campo) ou AÇÃO na usina →
  `usina_helper`. Criar ou alterar no meuPlano (abrir OS, lançar o dia, lembrete) → `manutencao`, com o pedido
  completo e já confirmado pela pessoa.
- "[senha oculta]" numa mensagem = a pessoa escreveu a senha de atuação no meio da frase: ela foi escondida e
  NÃO confirma nada (a senha só vale sozinha, numa mensagem só dela). "[número oculto]" = número que o sistema
  escondeu sem conferir (a frase tinha mais de 3 números longos, ou a pessoa passou do limite da hora): peça
  para reenviar numa frase com até 3 números (ex.: "a UC é 1234567") — nunca o número sozinho, que vale como
  tentativa de senha.
- Ação NUNCA é executada por você: a ferramenta devolve `proposta_pendente`, e o SISTEMA põe o resumo e o pedido
  de confirmação ao pé da sua resposta. No meuPlano (criar ou concluir OS, lançar o dia, lembrete) a pessoa
  confirma com SIM — NÃO fale de senha. Só ação no EQUIPAMENTO pelo helper (ligar, desligar, gravar parâmetro)
  pede a SENHA DE ATUAÇÃO; fale dela só nesse caso. Nunca peça a senha de login, nunca escreva uma senha,
  nunca diga que fez. Ler não pede nada.
- Pedido de vários passos no meuPlano ("crie a OS e conclua a 1638"): mande o pedido INTEIRO numa chamada de
  `manutencao`; o meuPlano propõe um passo por vez e, a cada SIM, o sistema segue para o próximo.
- Números SÓ das ferramentas; `None` = sem dados (diga isso), nunca zero. Nunca invente usina nem valor.
- Período: calcule as datas a partir de hoje. Compare usinas pela produtividade (kWh/kWp).
- Responda curto, em português do Brasil, formato WhatsApp (*negrito*, listas curtas): o número pedido
  primeiro, depois 2–4 linhas de contexto. Sem bastidor de dados, sem menu de opções no fim.
- Arquivo/gráfico com `enviado_no_chat: true` já chegou: só confirme, não repita link.
- Fora dessas áreas, diga com gentileza que não consegue ajudar."""


async def _llm(mensagens: list[dict], ferramentas: list[dict]) -> dict:
    s = get_settings()
    corpo: dict[str, Any] = {"model": s.llm_model, "messages": mensagens, "temperature": 0.2}
    if ferramentas:
        corpo.update(tools=ferramentas, tool_choice="auto")
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{s.llm_base_url.rstrip('/')}/chat/completions",
                         headers={"Authorization": f"Bearer {s.deepseek_api_key}"}, json=corpo)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


async def _executar(ctx: ger.Contexto, chamada: dict) -> dict:
    nome = chamada["function"]["name"]
    ctx.ferramentas.append(nome)
    if nome not in permitidas(ctx.user):
        return {"erro": "Essa parte não está liberada para você. O gerente da sua O&M pode liberar."}
    try:
        args = json.loads(chamada["function"].get("arguments") or "{}")
        fn = FERRAMENTAS[nome][0]
        return await fn(ctx, args)
    except ger.Recusa as e:
        return {"erro": str(e)}
    except KeyError:
        return {"erro": f"Ferramenta desconhecida: {nome}"}
    except Exception as e:                                 # noqa: BLE001 — uma ferramenta não derruba o turno
        log.warning("ferramenta %s falhou", nome, exc_info=True)
        return {"erro": f"{type(e).__name__}: {str(e)[:300]}"}


#: O que a IA ouve quando a mensagem desta vez derrubou a ação que esperava: sem isso ela podia
#: responder "vou fechar a OS" com "(foi cancelada)" logo embaixo (avaliação 16).
CANCELADA_PARA_A_IA = ("\n- NESTA MENSAGEM: a ação «{resumo}», que esperava a confirmação da pessoa, foi CANCELADA por "
                       "esta mensagem — nada foi feito. Não diga que vai executá-la nem que a fez; se a pessoa ainda "
                       "quiser (ou corrigiu algo), proponha de novo pela ferramenta.")


async def responder(ctx: ger.Contexto, historico: list[dict], aviso: str = "") -> str:
    """`aviso`: o que o sistema diz à IA só nesta mensagem (`CANCELADA_PARA_A_IA`)."""
    msgs: list[dict] = [{"role": "system", "content": _sistema(ctx) + aviso}, *historico]
    ferramentas = [FERRAMENTAS[n][1] for n in permitidas(ctx.user)]
    for _ in range(MAX_RODADAS):
        ctx.db.commit()                                   # solta a conexão enquanto a IA pensa
        m = await _llm(msgs, ferramentas)
        chamadas = m.get("tool_calls") or []
        if not chamadas:
            return (m.get("content") or "").strip() or "Não consegui montar a resposta. Pode reformular?"
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": chamadas})
        resultados = await asyncio.gather(*(_executar(ctx, c) for c in chamadas))
        # Atalho de velocidade: só o meuPlano foi chamado e respondeu → a resposta dele É a resposta.
        if len(chamadas) == 1 and chamadas[0]["function"]["name"] == "manutencao" and resultados[0].get("texto"):
            return resultados[0]["texto"]
        for c, res in zip(chamadas, resultados):
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps(res, ensure_ascii=False, default=str)[:TETO_RESULTADO]})
    return "A pergunta ficou grande demais para uma resposta só — pode dividir em partes?"


# --------------------------------------------------------------------------- transporte
async def _digitando_enquanto(wamid: str | None, fim: asyncio.Event, ja_avisou: bool = False) -> None:
    """Mantém o "digitando…" (a Meta apaga aos 25 s) até a resposta sair. `ja_avisou`: quem chama
    mandou o primeiro aviso (para ele sair antes de qualquer espera)."""
    while wamid and not fim.is_set():
        try:
            if not ja_avisou:
                await whatsapp.digitando(wamid)
        except Exception:                                  # noqa: BLE001
            return
        ja_avisou = False
        try:
            await asyncio.wait_for(fim.wait(), 20)
        except TimeoutError:
            pass


def para_whatsapp(texto: str) -> str:
    """Markdown de site → WhatsApp: **x** e títulos viram *x*, tabela vira linhas com "·"."""
    import re
    linhas = []
    for ln in texto.splitlines():
        t = ln.strip()
        if re.fullmatch(r"\|?[\s:|-]+\|?", t) and "-" in t:      # |---|:--:| separador de tabela
            continue
        if t.startswith("|") and t.endswith("|"):
            ln = " · ".join(c.strip() for c in t.strip("|").split("|") if c.strip())
        ln = re.sub(r"^#{1,6}\s*(.+)$", r"**\1**", ln)
        linhas.append(ln)
    out = re.sub(r"\*\*(.+?)\*\*", r"*\1*", "\n".join(linhas))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


#: Os botões do resumo de ação do meuPlano (dono, 24/10/2026: "ao invés de digitar sim, tem como
#: enviar botão, sim e não?"). O toque volta como mensagem com o título — "Sim" confirma, "Não"
#: cancela, pelo mesmo caminho do que se digita.
def botoes_sim_nao(codigo: str) -> list[dict]:
    """Os botões de UM resumo: o id leva o código dele, e o toque num resumo antigo não confirma a
    ação de agora (`helper.botao_antigo`)."""
    return [{"id": f"sim:{codigo}", "titulo": "Sim"}, {"id": f"nao:{codigo}", "titulo": "Não"}]


def _guardado(texto: str, valores: Sequence[str], omitir: bool = False) -> str | None:
    """O que o gateway GUARDA da mensagem que sai: sem as senhas (a pessoa recebe a inteira) — e, com `omitir` (o texto
    livre de um turno que trata de acesso), o aviso no lugar dele; None quando é igual."""
    g = RESPOSTA_OMITIDA if omitir else _sem_segredos(texto, valores)
    return g if g != texto else None


async def _botoes(telefone: str, corpo: str, codigo: str, valores: Sequence[str] = ()) -> bool:
    """O resumo da ação com os botões Sim / Não. O corpo de uma mensagem com botões vai até 1024
    caracteres: o resumo maior vai antes, em texto. Gateway que recusa botões: vai em texto."""
    saiu = True
    if len(corpo) > 1024:
        saiu = await _texto(telefone, corpo, valores)
        corpo = "Confirma a ação acima?"
    try:
        r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="botoes", texto=corpo,
                                           botoes=botoes_sim_nao(codigo), guardar=_guardado(corpo, valores))
    except whatsapp.GatewayIndisponivel:
        log.warning("assistente: o gateway recusou os botões; o resumo vai em texto", exc_info=True)
        return await _texto(telefone, corpo, valores) and saiu
    return bool((r or {}).get("ok")) and saiu


async def _texto(telefone: str, texto: str, valores: Sequence[str] = (), omitir: bool = False) -> bool:
    """Manda em pedaços de 3.900. Devolve se TODOS saíram (o gateway responde `ok: false` quando a
    Meta recusa, sem erro HTTP)."""
    saiu = True
    for i in range(0, len(texto), 3900):
        pedaco = texto[i:i + 3900]
        r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="text", texto=pedaco,
                                           guardar=_guardado(pedaco, valores, omitir))
        saiu = saiu and bool((r or {}).get("ok"))
    return saiu


#: Uma conversa por vez por número. Duas mensagens seguidas ("Serviço novo" e, 8 s depois,
#: "amanhã ele volta para terminar", 24/10/2026) rodavam juntas: o bot respondeu as duas em
#: paralelo, se contradisse, e a última a terminar regravou a conversa sem a outra.
#: ponytail: em memória (a API roda num processo só); com mais de um worker, trava no banco.
_TRAVAS: dict[str, asyncio.Lock] = {}


#: O que não é mensagem para o bot: reação (👍 no resumo), figurinha e avisos do próprio
#: WhatsApp. Não responde e NÃO cancela a ação que espera a senha — o 👍 no resumo cancelava, e
#: a senha mandada em seguida recebia "não há ação esperando" (avaliação 11).
IGNORADOS = {"reaction", "sticker", "system", "ephemeral", "request_welcome"}
#: As mensagens já atendidas (id do gateway): o aviso imediato e a varredura de lá podem repetir
#: uma entrega, e a mesma mensagem não pode ser respondida (nem confirmada) duas vezes.
_ATENDIDAS: OrderedDict[Any, None] = OrderedDict()


async def atender(evento: dict) -> None:
    """Um turno inteiro. Roda em segundo plano: o gateway já recebeu 202. As mensagens do
    mesmo número esperam a vez, na ordem em que chegaram (o `Lock` acorda em fila)."""
    if evento.get("tipo") in IGNORADOS - {"reaction"}:     # a reação ao resumo esperando o Sim é perguntada de novo
        return
    if evento.get("id") is not None:
        if evento["id"] in _ATENDIDAS:
            return
        _ATENDIDAS[evento["id"]] = None
        while len(_ATENDIDAS) > 2000:
            _ATENDIDAS.popitem(last=False)
    chave = evento.get("wa_id") or evento.get("telefone") or ""
    # Quando entrou na fila: a senha que chegou antes de o resumo da ação sair não vale.
    evento = {**evento, "_chegou": monotonic()}
    async with _TRAVAS.setdefault(chave, asyncio.Lock()):
        await _atender(evento)


def _empresa_fora(db: Session, user: User) -> str | None:
    """"Desligar a empresa" para o bot também — o adm promete que "param de entrar na hora".
    Conta sem empresa não é atendida: ninguém responde por ela (avaliação de 24/10/2026)."""
    from app.models.empresa import Empresa

    if user.empresa_id is None:
        return ("Sua conta não está em nenhuma empresa de O&M no Gestão Solar, então o bot não "
                "atende. Fale com a sua O&M.")
    empresa = db.get(Empresa, user.empresa_id)
    if empresa is None or not empresa.ativa:
        return ("O acesso da sua empresa ao Gestão Solar está desligado, então o bot não atende. "
                "Fale com a sua O&M.")
    return None


def _resumo_saiu(db: Session, user: User, saiu: bool) -> None:
    """A ação NOVA desta pessoa (o resumo acabou de ir): a senha/o SIM só valem depois da saída,
    marcada na hora do banco; se a mensagem não saiu, a pessoa não viu o resumo, e nada fica
    esperando."""
    p = helper.PENDENTES.get(user.id)
    if p is None or p.mostrada_em is not None:
        return
    if saiu:
        helper.mostrada(user.id, _agora_do_banco(db))
    else:
        helper.desarmar(user.id)


#: O fim do pedido, quando a resposta é SÓ isso ("Não há próximo passo.", "Pronto, não falta nada.", "Seu pedido está
#: completo.", "Pronto! Posso ajudar em algo mais?"): o bot encerra calado. Qualquer coisa além disso — "Não há mais
#: tarefas pendentes na OS 1638, que já pode ser fechada" — é pedida de novo e, sem o passo, a pessoa fica sabendo
#: (avaliação 23: procurar o fim em qualquer parte do texto calava o resto do pedido; avaliação 22: tomar só o
#: começo virava alarme falso). O sinal que o bot PEDE é "Não há próximo passo": a regra 7 do IA.MD do meuPlano
#: proíbe o modelo de lá de escrever "pronto" e "feito".
#: (avaliação 24: as variações naturais — "Não há próximos passos.", "Nenhum próximo passo.", "Sem próximo passo.",
#: "Não há próximo passo a propor.", "Não, não há próximo passo." — viravam pedido de novo e aviso.)
_PASSO = (r"(?:mais |outros? |pr[óo]xim[oa]s? )?passos?(?: (?:pendentes?|a (?:propor|seguir|fazer)|restantes?|"
          r"(?:para|n)[oe]?s?t?[ea]? (?:seu |este |esse |o )?pedido|no seu pedido))?")
_FRASE_FIM = (r"(?:n[ãa]o (?:h[áa]|existe|tem|resta) " + _PASSO + r"|(?:nenhum|sem) " + _PASSO + r"|"
              r"n[ãa]o h[áa] mais nada(?: a fazer)?|pronto|n[ãa]o|nada mais(?: a fazer)?|"
              r"tudo (?:feito|pronto|certo|conclu[ií]do|ok|resolvido|finalizado)|n[ãa]o falta (?:mais )?nada|"
              r"(?:o )?(?:seu )?pedido (?:est[áa] |foi )?(?:completo|conclu[ií]do|finalizado|atendido)|era s[óo] isso|"
              r"isso [ée] tudo|fim|feito)")
_SO_O_FIM = re.compile(rf"^\W*{_FRASE_FIM}(?:\W+{_FRASE_FIM})*\W*$", re.IGNORECASE)
#: A pergunta de cortesia SOZINHA ("Posso ajudar em algo mais?") não muda o fim — "Quer que eu feche a 1638 também
#: ou algo mais?" não é cortesia.
_CORTESIA = re.compile(r"(?:^|(?<=[.!?,;\n—–]))\s*(?:(?:(?:posso|consigo) (?:te )?ajudar (?:em|com) (?:algo|mais alguma "
                       r"coisa)(?: mais)?|(?:precisa|quer|deseja|gostaria)(?: de)? (?:algo|mais alguma coisa)(?: mais)?|"
                       r"(?:mais )?alguma coisa(?: mais)?|algo mais)\s*\?+|"
                       # a cortesia afirmada ("Estou à disposição.", "Se precisar de algo mais, é só pedir.")
                       r"(?:estou|fico|sigo) (?:à|a) disposi[çc][ãa]o[.!]*|(?:se precisar de (?:algo|mais alguma coisa)"
                       r"(?: mais)?|qualquer (?:coisa|d[úu]vida)),? (?:é só|basta) (?:pedir|chamar|falar|mandar)[.!]*)",
                       re.IGNORECASE)
#: O que se PEDE ao meuPlano depois de um passo feito — um STATUS, não um texto para o bot interpretar (avaliações 22 a 27:
#: ler a prosa de lá por palavras errava nos dois sentidos — "Não há mais nada a fazer nela" virava alarme; "A OS 1638
#: está EM_EXECUCAO" saía como fim). Ou a ferramenta do próximo passo, ou UMA destas linhas.
_STATUS_PEDIDO = ("Se não tem, responda numa linha só, começando por uma destas palavras: FEITO — o meu pedido inteiro "
                  "está feito; FALTA: o que ficou por fazer e por quê; PERGUNTA: o dado que você precisa de mim.")
#: O pedido de novo quando o meuPlano repropõe o passo que acabou de ser feito.
_REPETIU = ("Esse passo acabou de ser feito. Se o meu pedido tem outro passo, chame AGORA a ferramenta dele (um "
            "só), para eu confirmar com o botão. " + _STATUS_PEDIDO)
#: …e quando ele responde em texto, fora do status.
_EM_TEXTO = ("Não descreva em texto: se o meu pedido tem outro passo, chame AGORA a ferramenta dele (um só), para eu "
             "confirmar com o botão. " + _STATUS_PEDIDO)
#: O status na resposta: FEITO, FALTA/NÃO DÁ ou PERGUNTA no começo, e o que vem depois.
#: Só na forma do status — a palavra sozinha ou com ":"/"—" —, para o texto que COMEÇA assim ("Faltam 2 passos do que
#: você pediu — aqui está a proposta…", o uso real de 24/10) ser pedido de novo, e não tomado como o status.
_STATUS = re.compile(r"^\W*(feito|falta|n[ãa]o d[áa]|pergunta)\b\**\s*(?:[:—–]\**\s*(.*)|[.!]?\**\s*)$",
                     re.IGNORECASE | re.DOTALL)
#: Sem o status (o meuPlano respondeu em texto duas vezes), o bot não adivinha pela prosa: diz que não conseguiu
#: confirmar, com o que foi feito e o que o meuPlano disse; o log fica "a conferir".
NAO_CONFIRMOU = "O meuPlano não propôs outro passo e não confirmou se o seu pedido terminou"


def _so_o_fim(texto: str) -> bool:
    return bool(_SO_O_FIM.match(_CORTESIA.sub("", texto)))


async def _seguir_no_meuplano(db: Session, user: User, telefone: str, p: Any, feito: str,
                              revelados: list | None = None, digitados: list | None = None) -> str:
    """Depois de uma ação do meuPlano feita, o próximo passo do MESMO pedido: lá é uma proposta por
    vez, e "crie a OS e conclua a 1638" voltava só com a criação — o resto se perdia (24/10/2026).
    O meuPlano propõe o próximo passo ou diz o STATUS do pedido (`_STATUS_PEDIDO`: FEITO, FALTA: …, PERGUNTA: …);
    em texto, é pedido de novo, uma vez; sem o status, a pessoa fica sabendo que não se confirmou o fim. Sem
    resposta de lá, que o resto do pedido não foi feito (avaliação 13). `revelados`/`digitados` recebem as
    senhas que esses passos trouxeram (o log e o gateway as escondem — avaliação 27)."""
    from app.services.vinculos import SemConexao, cliente_meuplano

    def nao_seguiu(motivo: Any) -> str:
        pedido = f" «{p.pedido[:200]}»" if p.pedido else ""
        return (f"⚠️ Não consegui pedir ao meuPlano o resto do seu pedido{pedido}: {motivo}. O resto não foi "
                "feito — confira e peça de novo o que faltar.")

    try:
        mp = cliente_meuplano(db, user.id, so_proprio=True)
    except SemConexao as e:
        return nao_seguiu(e)
    # O pedido nas palavras da pessoa vai junto: a IA pode ter mandado ao meuPlano só uma parte dele
    # (dividiu em duas chamadas, e a 2ª foi recusada), e o resto sumia calado (avaliação 15).
    pedido = f" O meu pedido inteiro: «{p.pedido}»." if p.pedido else ""
    conversa = [*p.conversa, {"role": "assistant", "content": f"Proposta confirmada pela pessoa: {p.resumo}"},
                {"role": "user", "content": f"{feito}.{pedido} Se o meu pedido tem outro passo, chame AGORA a "
                                            "ferramenta dele (um só), para eu confirmar com o botão. " + _STATUS_PEDIDO}]
    feitos = tuple(f.rstrip(". ") for f in (*p.feitos, feito.removeprefix("✅ Feito no meuPlano: ")))
    de = f"Do seu pedido «{p.pedido[:200]}»" if p.pedido else "Do seu pedido"
    ja = f"{de}, já foi feito: {'; '.join(feitos)}."
    antes, repetiu, texto = "", False, ""                  # o texto da 1ª resposta, fora do status
    for tentativa in range(2):
        db.commit()                                       # solta a conexão: o meuPlano leva até 2 min
        try:
            r = await _perguntar_ao_meuplano(mp, conversa)
        except Exception:                                  # noqa: BLE001 — o feito já foi dito
            log.warning("assistente: não seguiu para o próximo passo no meuPlano", exc_info=True)
            return nao_seguiu("ele não respondeu")
        if revelados is not None:
            revelados.extend(str(v) for v in r.get("segredos") or [] if v)
        if r.get("erro"):
            return nao_seguiu(str(r["erro"]).rstrip(". "))
        texto = ""
        if r.get("type") == "proposal":
            if p.acao is None or (r.get("action") or "", r.get("args") or {}) != p.acao:
                ctx = ger.Contexto(db=db, user=user, telefone=telefone, pedido=p.pedido)
                _proposta_do_meuplano(ctx, r, conversa, feitos=feitos)
                if digitados is not None:
                    digitados.extend(ctx.digitados)
                return helper.bloco_da_proposta(ctx.proposta) if ctx.proposta is not None else ""
            # O meuPlano propôs de novo o passo que acabou de ser feito (mesma ação, mesmos argumentos):
            # oferecer seria pedir à pessoa para fazê-lo duas vezes (avaliação 16), e calar escondia o resto
            # do pedido (avaliação 21) — pede de novo.
            log.warning("assistente: o meuPlano repropôs a ação que acabou de ser feita (%s)", p.acao[0])
            de_novo, repetiu = _REPETIU, tentativa == 0
        else:
            texto = (r.get("texto") or "").strip()
            if (status := _STATUS.match(texto)) is not None:
                palavra, dito = status.group(1).lower(), (status.group(2) or "").strip() or antes
                if palavra == "feito":                     # acabou; o que ele disse vai como informação
                    return (f"O meuPlano não propôs outro passo do seu pedido — nada está esperando o seu Sim — e "
                            f"disse:\n\n{dito}") if dito else ""
                if palavra == "pergunta":
                    return (f"O próximo passo do seu pedido precisa de uma resposta sua — nada está esperando o seu "
                            f"Sim. {ja} O meuPlano perguntou:\n\n{dito}")
                return (f"⚠️ O resto do seu pedido não ficou feito — nada está esperando o seu Sim. {ja} O meuPlano "
                        f"disse:\n\n{dito}")
            if not texto or _so_o_fim(texto):
                if tentativa == 0 or (repetiu and not antes):
                    return ""                              # só o fim (também depois do passo repetido): calado
                texto = ""
                break                                      # o fim solto depois de um texto: o status não veio
            # O próximo passo veio em TEXTO ("aqui está a proposta… confirmando os dois, eu fecho a 1638"):
            # não há o que confirmar, e repassar a promessa deixou o pedido do dono parado no meio — a 1638
            # não foi fechada (uso real de 24/10/2026, avaliação 19). Pede de novo, uma vez, o status.
            de_novo = _EM_TEXTO
        if tentativa == 0:
            antes = texto
            conversa = [*conversa, {"role": "assistant", "content": texto or f"(propus de novo: {p.resumo})"},
                        {"role": "user", "content": de_novo}]
    final = texto or antes
    if not final:
        return (f"⚠️ O meuPlano não trouxe outro passo depois deste. {ja} Se faltava algo, peça de novo.")
    if re.search(rf"{helper._PERGUNTA.pattern}\W*$", final):
        return (f"O próximo passo do seu pedido precisa de uma resposta sua — nada está esperando o seu Sim. {ja} O "
                f"meuPlano perguntou:\n\n{final}")
    return (f"{NAO_CONFIRMOU} — nada está esperando o seu Sim. {ja} Ele disse:\n\n{final}\n\nConfira no meuPlano; "
            "se faltava algo, peça de novo.")


#: Quantas senhas conhecidas a conversa guarda (para o log e o gateway as esconderem nos turnos seguintes).
SEGREDOS_DA_CONVERSA = 20


def _ler_conversa(conv: ConversaWhatsapp) -> tuple[list[dict], list[str], list[str]]:
    """A conversa guardada e as senhas que ela já conhece. Cifrada desde a avaliação 26: a senha que o meuPlano revela e
    a que a pessoa manda gravar ficam nela — o turno seguinte precisa delas ("manda de novo"; "o nível é L1" e a
    proposta de gravar nasce com o valor) —, mas não em claro no banco. A antiga, em texto, ainda se lê."""
    bruto = conv.mensagens or "[]"
    try:
        dados = json.loads(bruto if bruto.lstrip().startswith(("[", "{")) else cripto.decifrar(bruto))
    except Exception:                                      # noqa: BLE001 — chave trocada: a conversa recomeça
        log.warning("assistente: não abriu a conversa guardada (%s); recomeça", conv.telefone, exc_info=True)
        return [], [], []
    if isinstance(dados, list):
        return dados, [], []
    return (list(dados.get("m") or []), [str(v) for v in dados.get("s") or []],
            [str(v) for v in dados.get("d") or []])


def _gravar_conversa(conv: ConversaWhatsapp, historico: list[dict], revelados: Sequence[str],
                     digitados: Sequence[str]) -> None:
    """`revelados`: as senhas que o meuPlano revelou (saem do histórico que vai ao meuPlano e à IA — ele as revela de
    novo, com registro); `digitados`: as que a pessoa mandou gravar (ficam: "o nível é L2" refaz a proposta com elas)."""
    conv.mensagens = cripto.cifrar(json.dumps(
        {"m": historico[-HISTORICO:], "s": list(dict.fromkeys(revelados))[-SEGREDOS_DA_CONVERSA:],
         "d": list(dict.fromkeys(digitados))[-SEGREDOS_DA_CONVERSA:]}, ensure_ascii=False))


def _para_fora(mensagens: list[dict], revelados: Sequence[str]) -> list[dict]:
    """O histórico que vai ao meuPlano e à IA, sem as senhas que o meuPlano já revelou (avaliação 27: voltavam em claro
    a cada turno — e lá ficavam gravadas)."""
    return [{**m, "content": _sem_valores(m.get("content") or "", revelados)} for m in mensagens]


async def _apagar_os_valores_de_antes(db: Session, user: User, telefone: str, novos: list[str]) -> None:
    """A senha que só ficou conhecida agora (o meuPlano a revelou; a proposta de gravar a trouxe) sai também do que foi
    guardado ANTES: as linhas do log da pessoa e as mensagens do gateway das últimas 24 h ("grava aí: SL2, usuário
    admin, changeme" — sem a palavra "senha" — só vira valor conhecido quando a proposta nasce)."""
    desde = datetime.now(UTC) - timedelta(hours=24)
    try:
        for r in db.scalars(select(RegistroBot).where(RegistroBot.gs_user_id == user.id, RegistroBot.em >= desde)):
            for campo in ("pergunta", "resposta", "erro"):
                valor = getattr(r, campo)
                if valor:
                    setattr(r, campo, _sem_valores(valor, novos))
        db.commit()
    except Exception:                                      # noqa: BLE001 — a resposta já saiu
        log.warning("assistente: não apagou as senhas do log de antes", exc_info=True)
        db.rollback()
    try:
        await whatsapp.mascarar(telefone, novos)
    except Exception:                                      # noqa: BLE001
        log.warning("assistente: não apagou as senhas do gateway", exc_info=True)


def _guardar(db: Session) -> None:
    """Grava a conversa. Falhar aqui não derruba o turno: a ação confirmada já rodou, e o
    resultado dela tem de chegar à pessoa — "Tente de novo" depois de criar a OS a criaria em
    dobro (avaliação 15). A conversa fica sem esta troca."""
    try:
        db.commit()
    except Exception:                                      # noqa: BLE001
        log.warning("assistente: não gravou a conversa", exc_info=True)
        db.rollback()


def _agora_do_banco(db: Session) -> datetime:
    """A hora do BANCO, não a deste servidor: a KingHost bloqueia o NTP e o relógio daqui anda
    ~17 s atrasado — e a senha é comparada com a hora da Meta, que é a certa (avaliação 11: a
    senha mandada até 17 s ANTES do resumo valia). No SQLite dos testes, a hora daqui."""
    if db.get_bind().dialect.name == "postgresql":
        try:
            return db.scalar(text("SELECT now()"))
        except Exception:                                  # noqa: BLE001 — o turno já respondeu
            log.warning("assistente: sem a hora do banco; vale a daqui", exc_info=True)
    return datetime.now(UTC)


async def _ouvir(db: Session, user: User, evento: dict) -> tuple[str, str | None]:
    """A nota de voz em texto, pelo meuPlano (o mesmo Whisper da entrada por voz do app de
    campo), com o token DA PESSOA. Devolve (texto, por que não deu)."""
    from app.services.vinculos import SemConexao, cliente_meuplano

    try:
        mp = cliente_meuplano(db, user.id, so_proprio=True)
    except SemConexao:
        return "", ("Para eu ouvir áudio, a sua conta precisa do token do meuPlano (o gerente cola em oem-gs → "
                    "Bot do WhatsApp). Por enquanto, mande em texto.")
    db.commit()                                            # solta a conexão enquanto baixa e transcreve
    try:
        await whatsapp.digitando(evento.get("wamid") or "")
    except Exception:                                      # noqa: BLE001 — o "digitando" é enfeite
        pass
    try:
        conteudo, tipo = await whatsapp.baixar_midia(int(evento["id"]))
        texto = await mp.transcrever(conteudo, tipo)
    except Exception:                                      # noqa: BLE001
        log.warning("assistente: não transcreveu o áudio (mensagem %s)", evento.get("id"), exc_info=True)
        return "", "Não consegui ouvir esse áudio agora — mande de novo ou em texto."
    return (texto, None) if texto else ("", "Não entendi nada nesse áudio — mande de novo ou em texto.")


async def _ocultar_no_gateway(mensagem_id: Any, texto: str) -> None:
    """A senha digitada sai também do gateway (a linha da mensagem e a entrega crua da Meta):
    fica o texto sem ela — a frase continua legível."""
    if not mensagem_id:
        return
    try:
        await whatsapp.ocultar_texto(int(mensagem_id), texto)
    except Exception:                                      # noqa: BLE001 — não derruba a resposta
        log.warning("assistente: não ocultou a senha no gateway (mensagem %s)", mensagem_id, exc_info=True)


async def _atender(evento: dict) -> None:
    telefone = evento.get("telefone") or ("+" + evento.get("wa_id", ""))
    texto = (evento.get("texto") or "").strip()
    enviada = _enviada_em(evento.get("ocorrida_em"))      # o log mostra quando a pessoa MANDOU
    # Mensagem com cara de senha nunca vai em claro ao log, nem se der erro no meio.
    pergunta = helper.OCULTA if helper.parece_senha(texto) else texto
    db = SessionLocal()
    # O turno solta a conexão antes de cada espera longa (IA, meuPlano, helper): sem expirar
    # os objetos, o commit não custa uma ida ao banco (~200 ms) para reler a conta.
    db.expire_on_commit = False
    fim = asyncio.Event()
    inicio = monotonic()
    user: User | None = None
    ctx: ger.Contexto | None = None
    valores: list[str] = []                                # as senhas conhecidas: somem do log e do gateway
    # A ação que esta mensagem pode confirmar, e se a resposta do turno já saiu: depois de a ação
    # rodar, um erro nunca vira "Tente de novo" (avaliação 15).
    executada: helper.Pendente | None = None
    respondeu = False
    try:
        user = conta_do_telefone(db, telefone)
        if evento.get("tipo") == "reaction":
            # O 👍 no resumo da ação do meuPlano era ignorado em silêncio e a ação vencia sem aviso (avaliação 22):
            # não confirma, mas o sistema pergunta de novo, com os botões. Fora disso, a reação segue ignorada.
            de_novo = (helper.de_novo_para_reacao(user.id) if user is not None and user.bot_liberado
                       and _empresa_fora(db, user) is None and not _atrasada(evento.get("ocorrida_em")) else None)
            if de_novo is not None:
                await _botoes(telefone, de_novo, helper.PENDENTES[user.id].codigo)
                _registrar(db, telefone, user, "respondeu", pergunta="[reação ao resumo]", resposta=de_novo,
                           ferramentas=["confirmacao"], inicio=inicio, em=enviada)
            return
        # A senha, conferida UMA vez e fora do laço da API, antes de qualquer saída: a mensagem
        # que É a senha some inteira; numa frase, só a senha some ("[senha oculta]") — e do
        # gateway sai só ela, não a frase. Com uma ação do meuPlano esperando o SIM, o número
        # sozinho é conversa (`e_tentativa`), decidido aqui, antes de a ação ser desarmada.
        tentativa = user is not None and helper.e_tentativa(user, texto)
        analise = await helper.analisar(user, texto, tentativa)
        seguro = helper.OCULTA if analise.pura else helper.mascarar(texto, analise)
        if user is not None:
            pergunta = seguro                              # analisada: a UC e o protocolo ficam legíveis
        if seguro != texto:
            pergunta = seguro
            await _ocultar_no_gateway(evento.get("id"), seguro)
        if _atrasada(evento.get("ocorrida_em")):
            # Mensagem que ficou presa (gateway fora, fila travada) e chegou horas depois:
            # responder agora seria conversar com o passado. Fica no log, sem resposta.
            _registrar(db, telefone, user, "atrasada", pergunta=pergunta or f"[{evento.get('tipo') or 'mídia'}]",
                       em=enviada,
                       erro=f"Chegou ao bot só em {hora_brt(datetime.now(UTC).isoformat())} (o canal ficou parado) "
                            "— não respondida.")
            return
        if user is None:
            if evento.get("tipo") in ("text", "audio", "button", "interactive"):
                await _texto(telefone, DESCONHECIDO)
                _registrar(db, telefone, None, "sem_conta", pergunta=pergunta, resposta=DESCONHECIDO, em=enviada)
            return
        fora = _empresa_fora(db, user)
        if fora is not None:
            await _texto(telefone, fora)
            _registrar(db, telefone, user, "nao_liberado", pergunta=pergunta, resposta=fora, em=enviada, erro=fora)
            return
        if not user.bot_liberado:
            await _texto(telefone, NAO_LIBERADO)
            _registrar(db, telefone, user, "nao_liberado", pergunta=pergunta, resposta=NAO_LIBERADO, em=enviada)
            return
        if evento.get("tipo") in ("audio", "voice") and not texto:
            # A nota de voz vira texto e segue como texto — inclusive a senha dita em voz alta,
            # que nunca é repetida em claro (avaliação 11: o bot anterior no número ouvia áudio).
            texto, falha = await _ouvir(db, user, evento)
            if texto:
                tentativa = helper.e_tentativa(user, texto)
                analise = await helper.analisar(user, texto, tentativa)
                seguro = helper.OCULTA if analise.pura else helper.mascarar(texto, analise)
                await _texto(telefone, f"🎙️ _{seguro}_")
                seguro = pergunta = f"🎙️ {seguro}"
            else:
                desarmada = helper.desarmar(user.id, "[áudio]")
                await _texto(telefone, falha + (f"\n\n{helper.cancelada(desarmada)}" if desarmada else ""))
                _registrar(db, telefone, user, "sem_texto", pergunta="[áudio]", resposta=falha, em=enviada)
                return
        aviso_do_botao = (helper.resposta_ao_botao(user.id, evento.get("botao"))
                          if evento.get("tipo") == "interactive" else None)
        if aviso_do_botao is not None:
            # O Sim/Não que não é do resumo de agora (antigo, vencido, ou a ação se perdeu num
            # deploy): não confirma, não cancela e não vai à IA (avaliações 13 e 14).
            await _texto(telefone, aviso_do_botao)
            _registrar(db, telefone, user, "respondeu", pergunta=pergunta, resposta=aviso_do_botao,
                       ferramentas=["confirmacao"], inicio=inicio, em=enviada)
            return
        # Toda mensagem que não é APENAS a senha (ou o SIM da ação do meuPlano) derruba a ação que a
        # esperava — antes de "limpar" e de áudio/imagem. Menos:
        # - o "valeu" (só ciência) que saiu do celular ANTES de o resumo chegar: não é resposta a ele
        #   (avaliação 14). "Cancela" e "não, é o 12" de antes derrubam (avaliação 15);
        # - a afirmativa que não é um SIM limpo ("Sim, pode deixar") com a ação do meuPlano esperando:
        #   nem confirma nem derruba — o sistema pergunta de novo, sem ir à IA (avaliação 16).
        confirma = helper.responde_sim(user.id, texto)
        antes = helper.mandada_antes_do_resumo(user.id, texto, evento.get("_chegou"), enviada)
        de_novo = None if confirma or antes else helper.pergunta_de_novo(user.id, texto)
        if de_novo is not None:
            esperando = helper.PENDENTES.get(user.id)       # vencida, já saiu: vai só o texto
            await (_botoes(telefone, de_novo, esperando.codigo) if esperando is not None else _texto(telefone, de_novo))
            _registrar(db, telefone, user, "respondeu", pergunta=pergunta, resposta=de_novo,
                       ferramentas=["confirmacao"], inicio=inicio, em=enviada)
            return
        desarmada = None if tentativa or confirma or antes else helper.desarmar(user.id, seguro or "[mídia]")
        esperava = desarmada is not None
        nota = f"\n\n{helper.cancelada(desarmada)}" if esperava else ""
        if not texto:
            nome = (evento.get("midia") or {}).get("nome")
            aviso = (f"Recebi o arquivo «{nome}», mas pelo WhatsApp eu ainda não abro arquivos. Se era um pedido, "
                     "escreva ou mande em áudio." if nome else
                     "Por enquanto eu entendo texto e áudio — imagem, vídeo e arquivo ainda não.")
            await _texto(telefone, aviso + nota)
            _registrar(db, telefone, user, "sem_texto", pergunta=f"[{evento.get('tipo') or 'mídia'}]", resposta=aviso,
                       em=enviada)
            return
        tarefa = asyncio.create_task(_digitando_enquanto(evento.get("wamid"), fim))
        conv = db.scalar(select(ConversaWhatsapp).where(ConversaWhatsapp.telefone == user.telefone))
        if conv is None:
            conv = ConversaWhatsapp(telefone=user.telefone, gs_user_id=user.id, mensagens="[]")
            db.add(conv)
        elif conv.gs_user_id != user.id:
            # O número mudou de conta (ex.: saiu do admin e foi para o gerente): a conversa
            # é da CONTA, e o histórico da outra não pode entrar no contexto desta.
            conv.mensagens = "[]"
            conv.gs_user_id = user.id
        if texto.lower() in LIMPAR:
            conv.mensagens = "[]"
            db.commit()
            fim.set()
            await _texto(telefone, "🧹 Conversa zerada. Pode mandar um pedido novo." + nota)
            _registrar(db, telefone, user, "zerou", pergunta=texto, inicio=inicio, em=enviada)
            return
        historico, revelados, digitados = _ler_conversa(conv)
        conhecidos = valores = [*revelados, *digitados]
        entrada = {"role": "user", "content": seguro}      # o que vai ao log (a senha já trocada)
        historico.append(entrada)
        # A SENHA DE ATUAÇÃO é conferida aqui, antes de qualquer modelo: a IA nunca a vê nem
        # confirma nada. Tratada como senha, a mensagem sai do histórico, do log e do gateway;
        # o desfecho entra no histórico, para a conversa seguinte saber o que foi feito.
        executada = helper.PENDENTES.get(user.id)         # a ação que esta mensagem pode confirmar
        texto_da_ia, bloco_sim, erro_do_resto, livre, a_conferir = "", None, None, "", False
        resposta = await helper.confirmar_por_mensagem(db, user, telefone, texto, analise, esperava,
                                                       chegou=evento.get("_chegou"), mandada_em=enviada,
                                                       tentativa=tentativa)
        if resposta == helper.CANCELADO and desarmada is not None and desarmada.feitos:
            # O passo cancelado não desfaz os de antes: "Nada foi feito" escondia a OS que o passo
            # anterior criou (avaliação 15).
            resposta = f"{helper.CANCELADO_PASSO} {_o_que_ficou(desarmada)}"
        falhou = resposta is not None and resposta.startswith(("❌", "⚠️"))
        if falhou and executada is not None and executada.conversa is not None:
            # O resto do pedido não some calado (avaliação 12: "crie a OS e conclua a 1638" — a
            # criação falhou e a conclusão nem foi lembrada), dito com as palavras da pessoa.
            resposta += "\n\n" + _o_que_ficou(executada)
        if resposta is not None and helper.digitos_da_senha(texto) is not None:
            historico[-1]["content"] = helper.OCULTA
        elif resposta is None:
            ctx = ger.Contexto(db=db, user=user, telefone=telefone, historico=_para_fora(historico[:-1], revelados),
                               pedido=seguro)
            await ger.preparar(ctx)
            if not get_settings().deepseek_api_key:
                resposta = "O bot está desligado neste ambiente (falta a chave da IA)."
            else:
                livre = resposta = await responder(
                    ctx, [*_para_fora(historico[:-1], revelados), historico[-1]],
                    CANCELADA_PARA_A_IA.format(resumo=desarmada.resumo) if desarmada is not None else "")
            resposta += nota
            if analise.escondeu_senha:
                resposta += ("\n\n(Escondi a sua senha de atuação desta mensagem: ela é só para equipamento — "
                             "ação do meuPlano se confirma com Sim. Nada foi executado.)"
                             if desarmada is not None and desarmada.confirmacao == "sim" else
                             "\n\n(Escondi a sua senha de atuação desta mensagem: ela só vale sozinha, numa "
                             "mensagem só dela. Nada foi executado.)")
            if ctx.proposta is not None:
                # O que a pessoa confirma é texto do SISTEMA, não da IA — e a ação do meuPlano vai
                # com os botões Sim / Não, numa mensagem só dela.
                bloco = helper.bloco_da_proposta(ctx.proposta)
                if ctx.proposta.confirmacao == "sim":
                    texto_da_ia, bloco_sim = resposta, bloco
                resposta += "\n\n" + bloco
        historico.append({"role": "assistant", "content": resposta})
        if ctx is not None:
            revelados, digitados = [*revelados, *ctx.segredos], [*digitados, *ctx.digitados]
        valores = list(dict.fromkeys([*revelados, *digitados]))
        # O turno que TRATA de acesso (a pergunta da pessoa, a da IA ao meuPlano ou a resposta): o texto livre fica fora
        # do log e da cópia do gateway; a mensagem da pessoa, na máscara do assunto (avaliação 27).
        assunto = (ctx is not None and ctx.credencial) or _e_de_credencial(seguro) or _e_de_credencial(livre)
        resposta_log = RESPOSTA_OMITIDA + resposta[len(livre):] if assunto and livre else resposta
        _gravar_conversa(conv, historico, revelados, digitados)
        conv.gs_user_id = user.id
        _guardar(db)
        fim.set()
        await tarefa
        if bloco_sim is not None:
            saiu = (await _texto(telefone, para_whatsapp(texto_da_ia), valores, omitir=assunto and bool(livre))
                    if texto_da_ia.strip() else True)
            saiu = await _botoes(telefone, bloco_sim, ctx.proposta.codigo, valores) and saiu
        else:
            saiu = await _texto(telefone, para_whatsapp(resposta), valores, omitir=assunto and bool(livre))
        respondeu = True
        _resumo_saiu(db, user, saiu)
        if (executada is not None and executada.conversa is not None and resposta.startswith("✅")
                and helper.PENDENTES.get(user.id) is not executada):
            # O próximo passo do MESMO pedido ("crie a OS e conclua a 1638"): lá é uma proposta por vez,
            # e leva de 20 a 65 s — o "digitando…" volta logo depois do ✅ (avaliação 13).
            fim_seguinte, avisou = asyncio.Event(), False
            if evento.get("wamid"):
                try:
                    await whatsapp.digitando(evento["wamid"])  # já: o ✅ saiu e vem mais
                    avisou = True
                except Exception:                          # noqa: BLE001 — o aviso não segura o passo
                    log.warning("assistente: sem o digitando do próximo passo", exc_info=True)
            digitando = asyncio.create_task(_digitando_enquanto(evento.get("wamid"), fim_seguinte, avisou))
            mais_revelados, mais_digitados = [], []
            try:
                seguinte = await _seguir_no_meuplano(db, user, telefone, executada, resposta,
                                                     mais_revelados, mais_digitados)
            finally:
                fim_seguinte.set()
                await digitando
            if seguinte.startswith("⚠️"):
                erro_do_resto = seguinte
            a_conferir = seguinte.startswith(NAO_CONFIRMOU)
            if seguinte:
                # as senhas que o PRÓXIMO PASSO revelou também somem (avaliação 27: ficavam no log e no gateway)
                revelados, digitados = [*revelados, *mais_revelados], [*digitados, *mais_digitados]
                valores = list(dict.fromkeys([*revelados, *digitados]))
                sobre_acesso = _e_de_credencial(seguinte)
                historico.append({"role": "assistant", "content": seguinte})
                _gravar_conversa(conv, historico, revelados, digitados)
                _guardar(db)
                proxima = helper.PENDENTES.get(user.id)
                if proxima is not None and proxima.mostrada_em is None and proxima.confirmacao == "sim":
                    _resumo_saiu(db, user, await _botoes(telefone, seguinte, proxima.codigo, valores))  # com botões
                else:
                    _resumo_saiu(db, user, await _texto(telefone, para_whatsapp(seguinte), valores, omitir=sobre_acesso))
                resposta += "\n\n" + seguinte
                resposta_log += "\n\n" + (RESPOSTA_OMITIDA if sobre_acesso else seguinte)
        # A ação confirmada que FALHOU — ou o resto do pedido que não veio — aparece como erro no
        # log (aparecia verde, "Respondeu").
        erro = resposta.split("\n")[0] if falhou else erro_do_resto
        _registrar(db, telefone, user, "erro" if erro else ("a_conferir" if a_conferir else "respondeu"),
                   pergunta=entrada["content"], resposta=resposta_log,
                   ferramentas=ctx.ferramentas if ctx else
                   ["senha_de_atuacao" if tentativa else "confirmacao"],
                   inicio=inicio, em=enviada, erro=erro, valores=valores, credencial=assunto)
        # a mensagem da pessoa, no gateway, também sem a senha de equipamento (a de atuação já saiu antes)
        if (guardada := _sem_segredos(seguro, valores, assunto)) != seguro:
            await _ocultar_no_gateway(evento.get("id"), guardada)
        if novos := [v for v in valores if v not in conhecidos]:
            await _apagar_os_valores_de_antes(db, user, telefone, novos)
    except Exception as exc:                               # noqa: BLE001
        log.exception("assistente: turno falhou (%s)", evento.get("wamid"))
        db.rollback()
        fim.set()
        if user is not None:
            _resumo_saiu(db, user, False)                  # o resumo não chegou: nada fica esperando
        _registrar(db, telefone, user, "erro", pergunta=pergunta,
                   ferramentas=ctx.ferramentas if ctx else None, inicio=inicio, em=enviada,
                   erro=f"{type(exc).__name__}: {exc}", credencial=True,
                   valores=[*valores, *(ctx.segredos + ctx.digitados if ctx is not None else [])])
        try:
            # A ação confirmada JÁ rodou (ou estourou no meio): o resultado dela chega à pessoa, e
            # nunca "Tente de novo" — repetir criaria a OS em dobro (avaliação 15).
            if executada is None or executada.desfecho is None:
                await _texto(telefone, "Tive um problema para responder agora. Tente de novo em instantes.")
            elif not respondeu:
                await _texto(telefone, para_whatsapp(executada.desfecho))
            elif executada.conversa is not None and executada.desfecho.startswith("✅"):
                # O ✅ saiu e o turno quebrou antes de saber se o pedido tinha mais passos: silêncio
                # deixava a pessoa esperando o resto.
                feito = "; ".join([*executada.feitos, executada.resumo])
                await _texto(telefone, para_whatsapp(
                    f"⚠️ Não consegui conferir se o seu pedido tinha mais passos. Já foi feito: {feito}. "
                    "Se faltava algo, peça de novo."))
        except Exception:                                  # noqa: BLE001
            pass
    finally:
        fim.set()
        db.close()
