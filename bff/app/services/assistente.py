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
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import httpx
from sqlalchemy import select
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


async def manutencao(ctx: ger.Contexto, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    pergunta = (a.get("pergunta") or "") + "\n\n(Resposta para WhatsApp: curta, sem tabela.)"
    # A API de lá é sem estado: a conversa vai junto. Sem ela, o "sim" a uma proposta do próprio
    # meuPlano ("Confirma que eu crie assim?") chegava lá sozinho, e ele recomeçava do zero.
    mensagens = [*ctx.historico[-HISTORICO_MEUPLANO:], {"role": "user", "content": pergunta}]
    ctx.db.commit()                                       # solta a conexão: o meuPlano leva até 2 min
    run_id = await mp.assistente_chat(None, mensagens)
    for _ in range(60):                                   # até ~2 min
        await asyncio.sleep(2)
        r = await mp.assistente_run(None, run_id)
        if r.get("status") == "DONE":
            if r.get("type") == "proposal":
                return _proposta_do_meuplano(ctx, r)
            return {"texto": r.get("text") or ""}
        if r.get("status") == "ERROR":
            return {"erro": r.get("error") or "O meuPlano não conseguiu responder."}
    return {"erro": "O meuPlano demorou demais para responder."}


#: Quantas mensagens da conversa vão ao meuPlano junto com a pergunta.
HISTORICO_MEUPLANO = 8
#: Quanto vale a proposta do meuPlano esperando a senha de atuação (é para ler o resumo com calma).
PRAZO_PROPOSTA_MP_S = 600


def _o_que_nasceu(dados: Any) -> str:
    """O número do que o meuPlano criou ("OS 1639, PROGRAMADA") — sem ele a pessoa não acha
    na tela o que acabou de pedir."""
    if not isinstance(dados, dict):
        return ""
    partes = [f"OS {dados['os_id']}"] if dados.get("os_id") else []
    partes += [f"{k}: {v}" for k, v in dados.items() if k.endswith("_id") and k != "os_id" and v]
    if dados.get("status"):
        partes.append(str(dados["status"]))
    return f" ({', '.join(partes)})" if partes else ""


def _proposta_do_meuplano(ctx: ger.Contexto, r: dict) -> dict:
    """Ação do assistente do meuPlano (criar OS, lançar o dia, lembrete…) volta como PROPOSTA:
    nada foi gravado lá. Espera a mesma SENHA DE ATUAÇÃO do helper; confirmada pela pessoa, o
    Gestão Solar chama o `/assistant/apply` de lá com o token DELA — é o "Confirmar" da web,
    e o meuPlano revalida os argumentos e a permissão."""
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
            return f"❌ O meuPlano recusou: {detalhe_do_upstream(e.response) or e.response.status_code}. Nada foi feito."
        except httpx.HTTPError:
            return ("⚠️ O meuPlano não respondeu a tempo — a ação PODE ter sido gravada. "
                    "Confira no meuPlano antes de pedir de novo.")
        return f"✅ Feito no meuPlano: {resumo}" + _o_que_nasceu((feito or {}).get("data"))

    detalhes = [ln.get("text") for ln in previa.get("lines") or []][:15]
    proposta = helper.propor(ctx, resumo, PRAZO_PROPOSTA_MP_S, executar, detalhes, previa.get("warnings") or [],
                             parte="bot_meuplano")
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
#: depois — "[senha de atuação]" e "a senha de vocês" ficam como estão.
_SEGREDO = re.compile(r"(?i)\b(senha|password|pin|segredo|c[óo]digo)\b"
                      r"((?:\s+d[eoa]s?\s+[^\n:=]{1,30}?)?\s*(?:\bé\b|\beh\b|:|=)\s*)([^\s,;]+?)(?=[.!?]*(?:\s|$|[,;]))")
_SEGREDO_NUM = re.compile(r"(?i)\b(senha|password|pin)(\s+)([^\s,;]*?\d[^\s,;]*?)(?=[.!?]*(?:\s|$|[,;]))")


def _sem_segredos(texto: str) -> str:
    texto = _SEGREDO.sub(lambda m: m.group(1) + m.group(2) + "••••", texto)
    return _SEGREDO_NUM.sub(lambda m: m.group(1) + m.group(2) + "••••", texto)


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
- Ação (helper ou meuPlano: ligar, desligar, gravar, criar) NUNCA é executada por você: a ferramenta devolve
  `proposta_pendente`. Mostre o resumo (e os detalhes) e peça a SENHA DE ATUAÇÃO da pessoa — quem confere é o
  sistema. Nunca peça a senha de login, nunca escreva uma senha, nunca diga que fez. Ler não pede senha.
- Números SÓ das ferramentas; `None` = sem dados (diga isso), nunca zero. Nunca invente usina nem valor.
- Período: calcule as datas a partir de hoje. Compare usinas pela produtividade (kWh/kWp).
- Responda curto, em português do Brasil, formato WhatsApp (*negrito*, listas curtas): o número pedido
  primeiro, depois 2–4 linhas de contexto. Sem bastidor de dados, sem menu de opções no fim.
- Arquivo/gráfico com `enviado_no_chat: true` já chegou: só confirme, não repita link.
- Fora dessas duas áreas, diga com gentileza que não consegue ajudar."""


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


async def responder(ctx: ger.Contexto, historico: list[dict]) -> str:
    msgs: list[dict] = [{"role": "system", "content": _sistema(ctx)}, *historico]
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
async def _digitando_enquanto(wamid: str | None, fim: asyncio.Event) -> None:
    """Mantém o "digitando…" (a Meta apaga aos 25 s) até a resposta sair."""
    while wamid and not fim.is_set():
        try:
            await whatsapp.digitando(wamid)
        except Exception:                                  # noqa: BLE001
            return
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


async def _texto(telefone: str, texto: str) -> None:
    for i in range(0, len(texto), 3900):
        await whatsapp.enviar_conteudo(telefone=telefone, tipo="text", texto=texto[i:i + 3900])


#: Uma conversa por vez por número. Duas mensagens seguidas ("Serviço novo" e, 8 s depois,
#: "amanhã ele volta para terminar", 24/10/2026) rodavam juntas: o bot respondeu as duas em
#: paralelo, se contradisse, e a última a terminar regravou a conversa sem a outra.
#: ponytail: em memória (a API roda num processo só); com mais de um worker, trava no banco.
_TRAVAS: dict[str, asyncio.Lock] = {}


async def atender(evento: dict) -> None:
    """Um turno inteiro. Roda em segundo plano: o gateway já recebeu 202. As mensagens do
    mesmo número esperam a vez, na ordem em que chegaram (o `Lock` acorda em fila)."""
    chave = evento.get("wa_id") or evento.get("telefone") or ""
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


async def _ocultar_no_gateway(mensagem_id: Any) -> None:
    """A senha digitada sai também do gateway (a linha da mensagem e a entrega crua da Meta)."""
    if not mensagem_id:
        return
    try:
        await whatsapp.ocultar_texto(int(mensagem_id))
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
    try:
        user = conta_do_telefone(db, telefone)
        # A senha, conferida UMA vez e fora do laço da API: todo número de 6 a 8 dígitos de
        # quem tem senha de atuação é candidato — certo ou errado, não vai à IA, ao log, ao
        # histórico nem ao gateway, em nenhum caminho (nem nos que saem logo abaixo).
        analise = await helper.analisar(user, texto)
        seguro = texto
        if analise.candidatos:
            seguro = helper.mascarar(texto)
            pergunta = seguro
            await _ocultar_no_gateway(evento.get("id"))
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
        # "Qualquer outra mensagem cancela": toda mensagem que não é APENAS a senha derruba a ação
        # que a esperava — antes de "limpar" e de áudio/imagem, que saem logo abaixo.
        esperava = False if analise.pura or helper.SENHA.match(helper.normalizar(texto)) else helper.desarmar(user.id)
        nota = f"\n\n{helper.ACAO_CANCELADA}" if esperava else ""
        if not texto:
            await _texto(telefone, "Por enquanto eu entendo só mensagem de texto." + nota)
            _registrar(db, telefone, user, "sem_texto", pergunta=f"[{evento.get('tipo') or 'mídia'}]", em=enviada)
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
        historico.append({"role": "user", "content": seguro})
        # A SENHA DE ATUAÇÃO é conferida aqui, antes de qualquer modelo: a IA nunca a vê nem
        # confirma nada. Tratada como senha, a mensagem sai do histórico, do log e do gateway;
        # o desfecho entra no histórico, para a conversa seguinte saber o que foi feito.
        resposta = await helper.confirmar_por_mensagem(db, user, telefone, texto, analise, esperava)
        if resposta is not None and helper.SENHA.match(helper.normalizar(texto)):
            historico[-1]["content"] = helper.OCULTA
        elif resposta is None:
            ctx = ger.Contexto(db=db, user=user, telefone=telefone, historico=historico[:-1])
            await ger.preparar(ctx)
            if not get_settings().deepseek_api_key:
                resposta = "O bot está desligado neste ambiente (falta a chave da IA)."
            else:
                resposta = await responder(ctx, historico)
            resposta += nota
            if ctx.proposta is not None:
                # O que a pessoa confirma com a senha é texto do SISTEMA, não da IA.
                resposta += "\n\n" + helper.bloco_da_proposta(ctx.proposta)
        historico.append({"role": "assistant", "content": resposta})
        conv.mensagens = json.dumps(historico[-HISTORICO:], ensure_ascii=False)
        conv.gs_user_id = user.id
        db.commit()
        fim.set()
        await tarefa
        await _texto(telefone, para_whatsapp(resposta))
        _registrar(db, telefone, user, "respondeu", pergunta=historico[-2]["content"], resposta=resposta,
                   ferramentas=ctx.ferramentas if ctx else ["senha_de_atuacao"], inicio=inicio, em=enviada)
    except Exception as exc:                               # noqa: BLE001
        log.exception("assistente: turno falhou (%s)", evento.get("wamid"))
        db.rollback()
        fim.set()
        _registrar(db, telefone, user, "erro", pergunta=pergunta,
                   ferramentas=ctx.ferramentas if ctx else None, inicio=inicio, em=enviada,
                   erro=f"{type(exc).__name__}: {exc}")
        try:
            await _texto(telefone, "Tive um problema para responder agora. Tente de novo em instantes.")
        except Exception:                                  # noqa: BLE001
            pass
    finally:
        fim.set()
        db.close()
