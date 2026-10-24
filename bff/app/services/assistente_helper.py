"""O helper pelo assistente do WhatsApp — atuar na usina (pedido do dono, 23/10/2026).

O helper (mw-modbus-helper) fala com os equipamentos da usina e faz pelo bot o que a web
faz, como a pessoa — identidade = o token do meuWatt DELA (regra: cada um com o SEU token).

**Ação nunca é executada pela IA.** Leitura volta na hora. Escrita volta do helper como
PROPOSTA (nada rodou); aqui ela ganha um código de 4 dígitos e fica esperando. Só quando a
PESSOA responde `CONFIRMO <código>` — conferido por este código, antes de qualquer modelo —
o Gestão Solar chama `confirmar`. O modelo não tem ferramenta de confirmar: ele só mostra o
resumo e o código.

O mesmo `propor` serve à proposta do assistente do meuPlano (criar OS, lançar o dia…):
`assistente.manutencao` guarda o `/assistant/apply` de lá, e o CONFIRMO é um só.
"""
from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from app.clients.helper_bot import HelperBot
from app.core.config import get_settings
from app.services import assistente_geracao as ger

#: `CONFIRMO 1234` (com ou sem espaço, maiúscula ou não).
CONFIRMACAO = re.compile(r"^\s*confirmo\s*(\d{4})\s*[.!]?\s*$", re.IGNORECASE)
TETO_RESPOSTA = 12000


@dataclass
class Pendente:
    resumo: str
    codigo: str
    expira: float
    #: Executa a ação confirmada — (db, conta, telefone) → a frase que vai ao WhatsApp.
    executar: Callable[[Any, Any, str], Awaitable[str]]


#: A ação que cada pessoa (id da conta) tem esperando confirmação — uma por vez.
#: ponytail: em memória, um processo só (o uvicorn da API roda com um worker); com mais de
#: um, isto vai para o banco. A proposta vale minutos: perder no deploy é aceitável.
PENDENTES: dict[int, Pendente] = {}


def propor(user_id: int, resumo: str, prazo_s: int, executar) -> dict:
    """Guarda a ação desta pessoa com um código e devolve o que o modelo mostra. Nada rodou."""
    codigo = f"{secrets.randbelow(10000):04d}"
    PENDENTES[user_id] = Pendente(resumo, codigo, monotonic() + prazo_s, executar)
    return {
        "proposta_pendente": resumo,
        "codigo": codigo,
        "vale_por_s": prazo_s,
        "instrucao": ("NADA foi executado. Mostre o resumo à pessoa e peça que ela responda exatamente "
                      f"'CONFIRMO {codigo}' em até {prazo_s // 60 or 1} min para executar. Nunca diga que fez."),
    }

_catalogo: tuple[float, dict[str, Any]] | None = None


def configurado() -> bool:
    s = get_settings()
    return bool(s.helper_bot_url and s.helper_bot_chave)


def _cliente(ctx_ou_db, user) -> HelperBot:
    from app.models.integracao import Produto
    from app.services.vinculos import token_do_cliente

    db = getattr(ctx_ou_db, "db", ctx_ou_db)
    s = get_settings()
    return HelperBot(
        s.helper_bot_url, s.helper_bot_chamador, s.helper_bot_chave,
        token_do_cliente(db, user.id, Produto.MEUWATT, so_proprio=True),
    )


def _corta(dados: Any) -> Any:
    import json

    texto = json.dumps(dados, ensure_ascii=False, default=str)
    return dados if len(texto) <= TETO_RESPOSTA else {"resposta_cortada": texto[:TETO_RESPOSTA]}


async def usina_helper_catalogo(ctx: ger.Contexto, a: dict) -> dict:
    """As rotas do helper (iguais para todo mundo): guardadas 10 min."""
    from app.services.vinculos import SemConexao

    global _catalogo
    if _catalogo is None or monotonic() - _catalogo[0] > 600:
        try:
            d = await _cliente(ctx, ctx.user).ferramentas()
        except SemConexao as e:
            return {"erro": f"Helper indisponível: {e}"}
        if not d.get("ok"):
            return {"erro": d.get("error") or d.get("reason") or "O helper não respondeu."}
        _catalogo = (monotonic(), {k: d.get(k) for k in ("rotas", "leitura_post", "escrita", "bloqueadas")})
    return _catalogo[1]


async def usina_helper(ctx: ger.Contexto, a: dict) -> dict:
    rota = (a.get("rota") or "").strip()
    if not rota.startswith("/api/"):
        return {"erro": "Informe a rota do helper, começando com /api/ (veja usina_helper_catalogo)."}
    corpo = a.get("corpo") if isinstance(a.get("corpo"), dict) else {}
    from app.services.vinculos import SemConexao

    try:
        d = await _cliente(ctx, ctx.user).chamar(rota, corpo, origem=f"whatsapp {ctx.telefone}")
    except SemConexao as e:
        return {"erro": f"Helper indisponível: {e}"}
    if not d.get("ok"):
        return {"erro": d.get("error") or d.get("reason") or "O helper recusou.", "motivo": d.get("reason")}
    if d.get("tipo") == "proposta":
        proposta, resumo = d["proposta"], d.get("resumo") or rota

        async def executar(db, user, telefone: str) -> str:
            try:
                r = await _cliente(db, user).confirmar(proposta, "codigo_whatsapp", f"whatsapp {telefone}")
            except SemConexao as e:
                return f"❌ Não executado: {e}"
            if not r.get("ok"):
                return f"❌ Não executado: {resumo}. {r.get('error') or r.get('reason') or ''}".strip()
            if r.get("incerto"):
                return (f"⚠️ {resumo}: o equipamento não respondeu — a ação PODE ter chegado. "
                        "Confira a leitura antes de repetir.")
            return f"✅ Executado: {r.get('resumo') or resumo}."

        return propor(ctx.user.id, resumo, int(d.get("expira_em_s") or 120), executar)
    return _corta({"status_http": d.get("status_http"), "resposta": d.get("resposta")})


async def confirmar_por_mensagem(db, user, telefone: str, texto: str) -> str | None:
    """`CONFIRMO 1234` → executa a ação pendente desta pessoa. `None` = não é confirmação."""
    m = CONFIRMACAO.match(texto or "")
    if m is None:
        return None
    pendente = PENDENTES.get(user.id)
    if pendente is None or monotonic() > pendente.expira:
        PENDENTES.pop(user.id, None)
        return "Não há ação esperando confirmação (ela vale poucos minutos). Nada foi feito — peça de novo."
    if m.group(1) != pendente.codigo:
        return "O código não confere com a ação pendente. Nada foi feito."
    PENDENTES.pop(user.id, None)          # uma vez só, aconteça o que acontecer
    return await pendente.executar(db, user, telefone)


_ROTA = {"type": "string", "description": "Rota do helper, ex.: /api/registry/plants, /api/registry/devices, "
         "/api/read, /api/healthcheck/start, /api/healthcheck/state, /api/alarms/feed, /api/abs/status."}

FERRAMENTAS = {
    "usina_helper_catalogo": (usina_helper_catalogo, {"type": "function", "function": {
        "name": "usina_helper_catalogo",
        "description": ("O que dá para pedir ao helper (a ferramenta de campo que fala com os equipamentos da "
                        "usina): rotas de leitura, de escrita e exemplos de corpo. Chame quando não souber a rota."),
        "parameters": {"type": "object", "properties": {}}}}),
    "usina_helper": (usina_helper, {"type": "function", "function": {
        "name": "usina_helper",
        "description": ("A USINA AO VIVO pelo helper — os equipamentos via Modbus (inversores, relés, SmartLogger, "
                        "caixas ABS, térmica): ler, testar a comunicação (healthcheck), alarmes. Comece por "
                        "/api/registry/plants (libera as usinas da pessoa) e /api/registry/devices {slug}. "
                        "AÇÃO (ajustar, ligar, desligar, resetar, comandar) NÃO é executada: volta um código, e só a "
                        "pessoa confirma respondendo CONFIRMO <código>."),
        "parameters": {"type": "object", "properties": {
            "rota": _ROTA,
            "corpo": {"type": "object", "description": "O JSON que a tela da web mandaria (ex.: {\"slug\": \"pirapozinho\"})."},
        }, "required": ["rota"]}}}),
}
