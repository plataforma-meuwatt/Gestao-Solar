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
from time import monotonic
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import whatsapp
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.telefone import normalizar
from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
from app.models.user import User
from app.services import assistente_geracao as ger

log = logging.getLogger("gs.assistente")

MAX_RODADAS = 6
HISTORICO = 20                # mensagens guardadas (user + assistant)
TETO_RESULTADO = 14000        # caracteres de cada resultado de ferramenta que vão ao modelo

DESCONHECIDO = ("Este é o assistente do Gestão Solar e só atende números cadastrados. "
                "Peça à sua empresa de O&M para cadastrar este telefone na sua conta do Gestão Solar.")
NAO_LIBERADO = ("Seu acesso ao assistente do WhatsApp ainda não foi liberado. "
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
    run_id = await mp.assistente_chat(None, [{"role": "user", "content": pergunta}])
    for _ in range(60):                                   # até ~2 min
        await asyncio.sleep(2)
        r = await mp.assistente_run(None, run_id)
        if r.get("status") == "DONE":
            if r.get("type") == "proposal":
                return {"texto": "Essa ação precisa ser confirmada no meuPlano (site ou app).",
                        "proposta": (r.get("preview") or {}).get("summary")}
            return {"texto": r.get("text") or ""}
        if r.get("status") == "ERROR":
            return {"erro": r.get("error") or "O meuPlano não conseguiu responder."}
    return {"erro": "O meuPlano demorou demais para responder."}


FERRAMENTAS = {**ger.FERRAMENTAS, "manutencao": (manutencao, _MANUTENCAO)}


# --------------------------------------------------------------------------- log
def _registrar(db: Session, telefone: str, user: User | None, resultado: str, *,
               pergunta: str | None = None, resposta: str | None = None,
               ferramentas: list[str] | None = None, inicio: float | None = None,
               erro: str | None = None) -> None:
    """Uma linha no log do bot (adm-gs → Log do bot). Falhar aqui nunca derruba a resposta.

    ponytail: guarda tudo, sem expurgo; quando o volume pesar, apaga o que passou de 90 dias.
    """
    try:
        db.add(RegistroBot(
            telefone=telefone[:20], gs_user_id=user.id if user else None,
            empresa_id=user.empresa_id if user else None, resultado=resultado,
            ferramentas=",".join(dict.fromkeys(ferramentas or [])) or None,
            pergunta=(pergunta or None) and pergunta[:2000],
            resposta=(resposta or None) and resposta[:2000],
            duracao_ms=int((monotonic() - inicio) * 1000) if inicio else None,
            erro=(erro or None) and erro[:1000],
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
    # helper: a chave já existe; as ferramentas de atuar na usina entram quando ficarem prontas
    return nomes


# --------------------------------------------------------------------------- orquestrador
def _sistema(ctx: ger.Contexto) -> str:
    usinas = ", ".join(u["nome"] for u in ctx.usinas.values()) or "nenhuma com monitoramento"
    ativo = ctx.user.bot_ativo
    # O helper (atuar na usina) fica FORA até as ferramentas dele existirem: dizer ao modelo
    # que está liberado o convidaria a confirmar uma ação que não aconteceu.
    areas = [n for n, c in (("geração/monitoramento (meuWatt)", "bot_meuwatt"),
                            ("manutenção (meuPlano)", "bot_meuplano")) if c in ativo]
    return f"""Você é o assistente do Gestão Solar no WhatsApp. Hoje é {ger.hoje().isoformat()} (America/Sao_Paulo).
Fala com {ctx.user.nome} ({ctx.user.apelido}). Usinas com monitoramento liberadas: {usinas}.
Liberado para esta pessoa: {", ".join(areas) or "nada"}. Pergunta de área NÃO liberada: diga que o acesso
a essa parte não está liberado e que o gerente da O&M pode liberar — não tente responder de outro jeito.

- Geração, inversores, PR, produtividade, irradiação, PVsyst, paradas de inversor, relatório/gráfico do
  monitoramento → ferramentas de geração. Manutenção (OS, cronograma, pendências, estoque, documentos,
  projetos) → `manutencao`. Pergunta que mistura → chame as duas.
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


async def atender(evento: dict) -> None:
    """Um turno inteiro. Roda em segundo plano: o gateway já recebeu 202."""
    telefone = evento.get("telefone") or ("+" + evento.get("wa_id", ""))
    texto = (evento.get("texto") or "").strip()
    db = SessionLocal()
    fim = asyncio.Event()
    inicio = monotonic()
    user: User | None = None
    ctx: ger.Contexto | None = None
    try:
        user = conta_do_telefone(db, telefone)
        if user is None:
            if evento.get("tipo") in ("text", "audio", "button", "interactive"):
                await _texto(telefone, DESCONHECIDO)
                _registrar(db, telefone, None, "sem_conta", pergunta=texto, resposta=DESCONHECIDO)
            return
        if not user.bot_liberado:
            await _texto(telefone, NAO_LIBERADO)
            _registrar(db, telefone, user, "nao_liberado", pergunta=texto, resposta=NAO_LIBERADO)
            return
        if not texto:
            await _texto(telefone, "Por enquanto eu entendo só mensagem de texto.")
            _registrar(db, telefone, user, "sem_texto", pergunta=f"[{evento.get('tipo') or 'mídia'}]")
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
            await _texto(telefone, "🧹 Conversa zerada. Pode mandar um pedido novo.")
            _registrar(db, telefone, user, "zerou", pergunta=texto, inicio=inicio)
            return
        historico = json.loads(conv.mensagens or "[]")
        historico.append({"role": "user", "content": texto})
        ctx = ger.Contexto(db=db, user=user, telefone=telefone)
        await ger.preparar(ctx)
        if not get_settings().deepseek_api_key:
            resposta = "O assistente está desligado neste ambiente (falta a chave da IA)."
        else:
            resposta = await responder(ctx, historico)
        historico.append({"role": "assistant", "content": resposta})
        conv.mensagens = json.dumps(historico[-HISTORICO:], ensure_ascii=False)
        conv.gs_user_id = user.id
        db.commit()
        fim.set()
        await tarefa
        await _texto(telefone, para_whatsapp(resposta))
        _registrar(db, telefone, user, "respondeu", pergunta=texto, resposta=resposta,
                   ferramentas=ctx.ferramentas, inicio=inicio)
    except Exception as exc:                               # noqa: BLE001
        log.exception("assistente: turno falhou (%s)", evento.get("wamid"))
        db.rollback()
        fim.set()
        _registrar(db, telefone, user, "erro", pergunta=texto,
                   ferramentas=ctx.ferramentas if ctx else None, inicio=inicio,
                   erro=f"{type(exc).__name__}: {exc}")
        try:
            await _texto(telefone, "Tive um problema para responder agora. Tente de novo em instantes.")
        except Exception:                                  # noqa: BLE001
            pass
    finally:
        fim.set()
        db.close()
