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
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.clients import whatsapp
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
    pergunta = pedido + "\n\n(Resposta para WhatsApp: curta, sem tabela.)"
    # A API de lá é sem estado: a conversa vai junto. Sem ela, o "sim" a uma proposta do próprio
    # meuPlano ("Confirma que eu crie assim?") chegava lá sozinho, e ele recomeçava do zero.
    mensagens = [*ctx.historico[-HISTORICO_MEUPLANO:], {"role": "user", "content": pergunta}]
    if _pede_assinatura(pedido) or _pede_assinatura(ctx.pedido):
        return _assinatura_com_senha(ctx, pedido, mensagens)
    ctx.db.commit()                                       # solta a conexão: o meuPlano leva até 2 min
    r = await _perguntar_ao_meuplano(mp, mensagens)
    return _proposta_do_meuplano(ctx, r, mensagens) if r.get("type") == "proposal" else r


async def _perguntar_ao_meuplano(mp, mensagens: list[dict]) -> dict:
    """Um turno do assistente do meuPlano: `{texto}`, `{erro}` ou a proposta crua de lá."""
    run_id = await mp.assistente_chat(None, mensagens)
    for _ in range(60):                                   # até ~2 min
        await asyncio.sleep(2)
        r = await mp.assistente_run(None, run_id)
        if r.get("status") == "DONE":
            return r if r.get("type") == "proposal" else {"texto": r.get("text") or ""}
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


def _o_que_ficou(p: Any) -> str:
    """O que do pedido da pessoa foi feito e o que não foi, quando um passo falha — nas palavras
    DELA, nunca a instrução que o bot mandou ao meuPlano (avaliação 13)."""
    de = f"Do seu pedido «{p.pedido[:200]}»" if p.pedido else "Do seu pedido"
    if p.feitos:
        return (f"{de}, antes disso já foi feito: {'; '.join(p.feitos)}. O resto não foi feito — confira e peça de "
                "novo o que faltar.")
    return f"{de}, nada além disso foi feito — confira e peça de novo o que faltar."


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
        return f"✅ Feito no meuPlano: {resumo}" + _o_que_nasceu((feito or {}).get("data"), resumo)

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
_SEGREDO = re.compile(r"(?i)\b(senha|password|pin|segredo|c[óo]digo)\b"
                      r"((?:\s+d[eoa]s?\s+[^\n:=\d.!?;]{1,30}?)?\s*(?:(?:\bé\b|\beh\b)\s*[:=]?|[:=])\s*)(?![\[:=])"
                      r"([^\s,;]{3,}?)"
                      r"(?=[.!?]*(?:\s|$|[,;]))")
#: "senha 1234", "PIN ab12": três caracteres ou mais — "PIN 3 do conector" e "senha 2 vezes" são
#: dado técnico e prosa, não segredo.
_SEGREDO_NUM = re.compile(r"(?i)\b(senha|password|pin)(\s+)(?!\[)(?=[^\s,;]{3})([^\s,;]*?\d[^\s,;]*?)"
                          r"(?=[.!?]*(?:\s|$|[,;]))")
#: "Altere a senha do cadeado de pirapozinho para 3262" (estava em claro no log de produção,
#: avaliação 9). Com "para/pra" o valor precisa ter dígito: "senha para o gerente" é prosa.
_SEGREDO_PARA = re.compile(r"(?i)\b(senha|password|pin|segredo|c[óo]digo)\b"
                           r"((?:\s+d[eoa]s?\s+[^\n:=]{1,40}?)?\s+(?:para|pra)\s+)"
                           r"(?!\[)([^\s,;]*?\d[^\s,;]*?)(?=[.!?]*(?:\s|$|[,;]))")
#: O NÚMERO inteiro, com qualquer pontuação antes e com os grupos ("senha,482913",
#: "senha/482913", "pin 482 913", "senha do cadeado 3262", "o código do portão 4455" — em claro
#: no log até a avaliação 10), de 3 dígitos ou mais. "código" e "combinação" só de
#: porta/portão/cadeado/cofre: "código de erro 2043" e "combinação de strings 12" são dado útil.
#: Hora ("até as 14:32") não é segredo.
_DE_ACESSO = r"(?=[ \t]+d[eoa]s?[ \t]+(?:port[ãa]o|porteira|cadeado|porta|acesso|cofre|guarita|cerca))"
_SEGREDO_NUMERO = re.compile(
    r"(?i)\b(senha|password|pin|segredo|combina[çc][ãa]o" + _DE_ACESSO + r"|c[óo]digo" + _DE_ACESSO + r")\b"
    r"((?:[ \t]+d[eoa]s?[ \t]+(?:[^\W\d_][\w\-]*[ \t]+){0,3}?[^\W\d_][\w\-]*)?[ \t]*"
    r"(?:\b(?:é|eh|para|pra)\b)?[ \t:=,;/.\-]*)"
    r"(\d+(?:(?:\s{1,2}|\s?[.\-/–—]\s?)\d+)*)(?!\d|[:h]\d)")


def _sem_segredos(texto: str) -> str:
    # O do número primeiro: os outros mascaram só o primeiro grupo ("pin •••• 913").
    texto = _SEGREDO_NUMERO.sub(
        lambda m: m.group(0) if len(re.sub(r"\D", "", m.group(3))) < 3 else m.group(1) + m.group(2) + "••••", texto)
    for padrao in (_SEGREDO, _SEGREDO_PARA, _SEGREDO_NUM):
        texto = padrao.sub(lambda m: m.group(1) + m.group(2) + "••••", texto)
    return texto


def _registrar(db: Session, telefone: str, user: User | None, resultado: str, *,
               pergunta: str | None = None, resposta: str | None = None,
               ferramentas: list[str] | None = None, inicio: float | None = None,
               erro: str | None = None, em: datetime | None = None) -> None:
    """Uma linha no log do bot (adm-gs → Log do bot). Falhar aqui nunca derruba a resposta.

    ponytail: guarda tudo, sem expurgo; quando o volume pesar, apaga o que passou de 90 dias.
    """
    try:
        db.add(RegistroBot(
            telefone=telefone[:20], gs_user_id=user.id if user else None,
            empresa_id=user.empresa_id if user else None, resultado=resultado,
            ferramentas=",".join(dict.fromkeys(ferramentas or [])) or None,
            pergunta=(pergunta or None) and _sem_segredos(pergunta)[:4000],
            resposta=(resposta or None) and _sem_segredos(resposta)[:8000],
            duracao_ms=int((monotonic() - inicio) * 1000) if inicio else None,
            erro=(erro or None) and erro[:1000],
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


async def _botoes(telefone: str, corpo: str, codigo: str) -> bool:
    """O resumo da ação com os botões Sim / Não. O corpo de uma mensagem com botões vai até 1024
    caracteres: o resumo maior vai antes, em texto. Gateway que recusa botões: vai em texto."""
    saiu = True
    if len(corpo) > 1024:
        saiu = await _texto(telefone, corpo)
        corpo = "Confirma a ação acima?"
    try:
        r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="botoes", texto=corpo,
                                           botoes=botoes_sim_nao(codigo))
    except whatsapp.GatewayIndisponivel:
        log.warning("assistente: o gateway recusou os botões; o resumo vai em texto", exc_info=True)
        return await _texto(telefone, corpo) and saiu
    return bool((r or {}).get("ok")) and saiu


async def _texto(telefone: str, texto: str) -> bool:
    """Manda em pedaços de 3.900. Devolve se TODOS saíram (o gateway responde `ok: false` quando a
    Meta recusa, sem erro HTTP)."""
    saiu = True
    for i in range(0, len(texto), 3900):
        r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="text", texto=texto[i:i + 3900])
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
    if evento.get("tipo") in IGNORADOS:
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


#: O fim do pedido dito em texto ("Pronto.", "Não há mais passos", "Tudo feito") — não é falha (avaliação 20).
_FIM_DO_PEDIDO = re.compile(r"^\W*(?:pronto|tudo (?:feito|certo|pronto)|n[ãa]o h[áa] (?:mais|outro|pr[óo]ximo)|"
                            r"nada mais|era s[óo] isso|sem mais passos)\b", re.IGNORECASE)


async def _seguir_no_meuplano(db: Session, user: User, telefone: str, p: Any, feito: str) -> str:
    """Depois de uma ação do meuPlano feita, o próximo passo do MESMO pedido: lá é uma proposta por
    vez, e "crie a OS e conclua a 1638" voltava só com a criação — o resto se perdia (24/10/2026).
    O meuPlano decide se há próximo; havendo, vira outra proposta com SIM. Sem próximo, nada. Sem
    resposta de lá, a pessoa fica sabendo que o resto do pedido não foi feito (avaliação 13)."""
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
                {"role": "user", "content": f"{feito}.{pedido} Se o meu pedido tinha mais passos, proponha o "
                                            "próximo agora; se não tinha, responda só: Pronto."}]
    feitos = tuple(f.rstrip(". ") for f in (*p.feitos, feito.removeprefix("✅ Feito no meuPlano: ")))
    de = f"Do seu pedido «{p.pedido[:200]}»" if p.pedido else "Do seu pedido"
    for tentativa in range(2):
        db.commit()                                       # solta a conexão: o meuPlano leva até 2 min
        try:
            r = await _perguntar_ao_meuplano(mp, conversa)
        except Exception:                                  # noqa: BLE001 — o feito já foi dito
            log.warning("assistente: não seguiu para o próximo passo no meuPlano", exc_info=True)
            return nao_seguiu("ele não respondeu")
        if r.get("erro"):
            return nao_seguiu(str(r["erro"]).rstrip(". "))
        if r.get("type") == "proposal":
            if p.acao is not None and (r.get("action") or "", r.get("args") or {}) == p.acao:
                # O meuPlano propôs de novo o passo que acabou de ser feito (mesma ação, mesmos
                # argumentos): oferecer seria pedir à pessoa para fazê-lo duas vezes (avaliação 16). Depois
                # do pedido de novo, o resto do pedido não veio — e isso se diz (avaliação 20).
                log.warning("assistente: o meuPlano repropôs a ação que acabou de ser feita (%s)", p.acao[0])
                return "" if tentativa == 0 else (f"O meuPlano não trouxe outro passo depois deste. {de}, já foi "
                                                  f"feito: {'; '.join(feitos)}. Se faltava algo, peça de novo.")
            ctx = ger.Contexto(db=db, user=user, telefone=telefone, pedido=p.pedido)
            _proposta_do_meuplano(ctx, r, conversa, feitos=feitos)
            return helper.bloco_da_proposta(ctx.proposta) if ctx.proposta is not None else ""
        texto = (r.get("texto") or "").strip()
        if not texto or _FIM_DO_PEDIDO.match(texto):
            return ""
        # O próximo passo veio em TEXTO ("aqui está a proposta… confirmando os dois, eu fecho a 1638"):
        # não há o que confirmar, e repassar a promessa deixou o pedido do dono parado no meio — a 1638
        # não foi fechada (uso real de 24/10/2026, avaliação 19). Pede de novo, uma vez, pela ferramenta.
        conversa = [*conversa, {"role": "assistant", "content": texto},
                    {"role": "user", "content": "Não descreva em texto: chame AGORA a ferramenta do próximo passo "
                                                "(um só), para eu confirmar com o botão. Se falta um dado para isso, "
                                                "pergunte em UMA frase qual. Se não há próximo passo, responda só: "
                                                "Pronto."}]
    # Texto de novo: a pergunta do meuPlano ("qual a data de término?") vai INTEIRA, como pergunta; o
    # resto, como aviso de que o passo não ficou pronto — nunca a promessa "confirmando os dois…" solta.
    pergunta = texto.rstrip().endswith("?")
    return (f"{'' if pergunta else '⚠️ '}O próximo passo do seu pedido ainda não ficou pronto para confirmar — nada "
            f"está esperando o seu Sim. {de}, já foi feito: {'; '.join(feitos)}. O meuPlano disse:\n\n{texto}")


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
    # A ação que esta mensagem pode confirmar, e se a resposta do turno já saiu: depois de a ação
    # rodar, um erro nunca vira "Tente de novo" (avaliação 15).
    executada: helper.Pendente | None = None
    respondeu = False
    try:
        user = conta_do_telefone(db, telefone)
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
        historico = json.loads(conv.mensagens or "[]")
        entrada = {"role": "user", "content": seguro}      # o que vai ao log (a senha já trocada)
        historico.append(entrada)
        # A SENHA DE ATUAÇÃO é conferida aqui, antes de qualquer modelo: a IA nunca a vê nem
        # confirma nada. Tratada como senha, a mensagem sai do histórico, do log e do gateway;
        # o desfecho entra no histórico, para a conversa seguinte saber o que foi feito.
        executada = helper.PENDENTES.get(user.id)         # a ação que esta mensagem pode confirmar
        texto_da_ia, bloco_sim, erro_do_resto = "", None, None
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
            ctx = ger.Contexto(db=db, user=user, telefone=telefone, historico=historico[:-1], pedido=seguro)
            await ger.preparar(ctx)
            if not get_settings().deepseek_api_key:
                resposta = "O bot está desligado neste ambiente (falta a chave da IA)."
            else:
                resposta = await responder(ctx, historico, CANCELADA_PARA_A_IA.format(resumo=desarmada.resumo)
                                           if desarmada is not None else "")
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
        conv.mensagens = json.dumps(historico[-HISTORICO:], ensure_ascii=False)
        conv.gs_user_id = user.id
        _guardar(db)
        fim.set()
        await tarefa
        if bloco_sim is not None:
            saiu = await _texto(telefone, para_whatsapp(texto_da_ia)) if texto_da_ia.strip() else True
            saiu = await _botoes(telefone, bloco_sim, ctx.proposta.codigo) and saiu
        else:
            saiu = await _texto(telefone, para_whatsapp(resposta))
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
            try:
                seguinte = await _seguir_no_meuplano(db, user, telefone, executada, resposta)
            finally:
                fim_seguinte.set()
                await digitando
            if seguinte.startswith("⚠️"):
                erro_do_resto = seguinte
            if seguinte:
                historico.append({"role": "assistant", "content": seguinte})
                conv.mensagens = json.dumps(historico[-HISTORICO:], ensure_ascii=False)
                _guardar(db)
                proxima = helper.PENDENTES.get(user.id)
                if proxima is not None and proxima.mostrada_em is None and proxima.confirmacao == "sim":
                    _resumo_saiu(db, user, await _botoes(telefone, seguinte, proxima.codigo))  # com botões
                else:
                    _resumo_saiu(db, user, await _texto(telefone, para_whatsapp(seguinte)))
                resposta += "\n\n" + seguinte
        # A ação confirmada que FALHOU — ou o resto do pedido que não veio — aparece como erro no
        # log (aparecia verde, "Respondeu").
        erro = resposta.split("\n")[0] if falhou else erro_do_resto
        _registrar(db, telefone, user, "erro" if erro else "respondeu", pergunta=entrada["content"],
                   resposta=resposta, ferramentas=ctx.ferramentas if ctx else
                   ["senha_de_atuacao" if tentativa else "confirmacao"],
                   inicio=inicio, em=enviada, erro=erro)
    except Exception as exc:                               # noqa: BLE001
        log.exception("assistente: turno falhou (%s)", evento.get("wamid"))
        db.rollback()
        fim.set()
        if user is not None:
            _resumo_saiu(db, user, False)                  # o resumo não chegou: nada fica esperando
        _registrar(db, telefone, user, "erro", pergunta=pergunta,
                   ferramentas=ctx.ferramentas if ctx else None, inicio=inicio, em=enviada,
                   erro=f"{type(exc).__name__}: {exc}")
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
