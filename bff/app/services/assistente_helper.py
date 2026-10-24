"""O helper pelo assistente do WhatsApp — atuar na usina (pedido do dono, 23/10/2026).

O helper (mw-modbus-helper) fala com os equipamentos da usina e faz pelo bot o que a web
faz, como a pessoa — identidade = o token do meuWatt DELA (regra: cada um com o SEU token).

**Ação nunca é executada pela IA, e só roda com a SENHA DE ATUAÇÃO da pessoa** (pedido do
dono, 24/10/2026: "o bot peça senha para qualquer ação que envolva atuação — desligar,
ligar, gravar; ler não precisa"). Leitura volta na hora. Escrita volta do helper como
PROPOSTA (nada rodou) e fica esperando aqui; quando a pessoa manda a senha dela — conferida
por este código, antes de qualquer modelo, contra `User.senha_atuacao_hash` — o Gestão
Solar chama `confirmar` com `confirmado_por="pin"` (o contrato do helper: quem pede a senha
é o chamador). O modelo não vê a senha nem tem ferramenta de confirmar; `assistente._atender`
tira a mensagem do log, do histórico e do gateway.

O mesmo `propor` serve à proposta do assistente do meuPlano (criar OS, lançar o dia…):
`assistente.manutencao` guarda o `/assistant/apply` de lá, e a senha é uma só.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from app.clients.helper_bot import HelperBot
from app.core.config import get_settings
from app.core.security import conferir_senha
from app.services import assistente_geracao as ger

#: Mensagem que é uma SENHA: só números (4 a 8), com ou sem "confirmo"/"senha" na frente.
SENHA = re.compile(r"^\s*(?:confirmo|senha)?\s*[:\-]?\s*(\d{4,8})\s*[.!]?\s*$", re.IGNORECASE)
COM_PALAVRA = re.compile(r"^\s*(?:confirmo|senha)\b", re.IGNORECASE)
#: O que fica no log, no histórico e no gateway no lugar da senha digitada.
OCULTA = "[senha de atuação]"
TENTATIVAS = 5
BLOQUEIO_S = 15 * 60
TETO_RESPOSTA = 12000
SEM_SENHA = ("Você ainda não tem senha de atuação — sem ela o bot só lê. Peça ao gerente da sua "
             "O&M para definir no oem-gs (Bot do WhatsApp). Nada foi feito.")


@dataclass
class Pendente:
    resumo: str
    expira: float
    #: Executa a ação confirmada — (db, conta, telefone) → a frase que vai ao WhatsApp.
    executar: Callable[[Any, Any, str], Awaitable[str]]


#: A ação que cada pessoa (id da conta) tem esperando a senha — uma por vez.
#: ponytail: em memória, um processo só (o uvicorn da API roda com um worker); com mais de
#: um, isto vai para o banco. A proposta vale minutos: perder no deploy é aceitável.
PENDENTES: dict[int, Pendente] = {}
#: Senha errada seguida por conta, e até quando as ações estão bloqueadas. Em memória: um
#: reinício zera — e ainda é preciso o celular da pessoa para cada tentativa.
_ERROS: dict[int, int] = {}
_BLOQUEIO: dict[int, float] = {}


def validar_senha_atuacao(senha: str) -> str:
    """4 a 8 números, sem repetir nem seguir em sequência (1111, 1234, 4321). Devolve limpa."""
    s = (senha or "").strip()
    if not re.fullmatch(r"\d{4,8}", s):
        raise ValueError("A senha de atuação tem de 4 a 8 números.")
    passos = {int(b) - int(a) for a, b in zip(s, s[1:])}
    if passos in ({0}, {1}, {-1}):
        raise ValueError("Senha fácil demais (número repetido ou em sequência). Escolha outra.")
    return s


def nova_senha(user_id: int) -> None:
    """Senha trocada: zera as tentativas erradas e o bloqueio."""
    _ERROS.pop(user_id, None)
    _BLOQUEIO.pop(user_id, None)


def propor(user, resumo: str, prazo_s: int, executar) -> dict:
    """Guarda a ação desta pessoa e devolve o que o modelo mostra. Nada rodou. Sem senha de
    atuação cadastrada nem guarda: a ação não teria como ser confirmada."""
    if not user.senha_atuacao_hash:
        PENDENTES.pop(user.id, None)
        return {"proposta_pendente": resumo, "sem_senha_de_atuacao": True,
                "instrucao": ("NADA foi executado, e não pode ser: esta pessoa ainda não tem SENHA DE ATUAÇÃO. "
                              "Mostre o resumo e diga que o gerente da O&M define a senha dela no oem-gs "
                              "(Bot do WhatsApp). Leitura continua liberada.")}
    PENDENTES[user.id] = Pendente(resumo, monotonic() + prazo_s, executar)
    return {
        "proposta_pendente": resumo,
        "vale_por_s": prazo_s,
        "instrucao": ("NADA foi executado. Mostre o resumo e peça à pessoa que responda com a SENHA DE "
                      f"ATUAÇÃO dela (só números) em até {prazo_s // 60 or 1} min. Quem confere é o sistema, "
                      "não você: nunca peça a senha de login, nunca escreva nem invente senha, nunca diga "
                      "que fez."),
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


def _enxuga(v: Any) -> Any:
    """Item de lista fica só com os campos simples (id, nome, slug…)."""
    if isinstance(v, dict):
        return {k: _enxuga(x) for k, x in v.items()}
    if isinstance(v, list):
        return [{k: x for k, x in i.items() if not isinstance(x, (dict, list))} if isinstance(i, dict) else i
                for i in v]
    return v


def _corta(dados: Any) -> Any:
    """Cabe no modelo. O `/api/registry/plants` tem ~18 mil caracteres por 6 usinas (gateways,
    alvos): cortado no meio, o bot perdia as últimas usinas e o status. Grande, as listas
    perdem o aninhado — o detalhe de UM item se pede na rota dele."""
    import json

    if len(json.dumps(dados, ensure_ascii=False, default=str)) <= TETO_RESPOSTA:
        return dados
    enxuto = _enxuga(dados)
    texto = json.dumps(enxuto, ensure_ascii=False, default=str)
    if len(texto) <= TETO_RESPOSTA:
        return {**enxuto, "aviso": "Resposta grande: campos aninhados omitidos; peça o detalhe pela rota do item."}
    return {"status_http": dados.get("status_http"), "resposta_cortada": texto[:TETO_RESPOSTA]}


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
        cliente = _cliente(ctx, ctx.user)
    except SemConexao as e:
        return {"erro": f"Helper indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o helper lê
    d = await cliente.chamar(rota, corpo, origem=f"whatsapp {ctx.telefone}")
    if not d.get("ok"):
        return {"erro": d.get("error") or d.get("reason") or "O helper recusou.", "motivo": d.get("reason")}
    if d.get("tipo") == "proposta":
        proposta, resumo = d["proposta"], d.get("resumo") or rota

        async def executar(db, user, telefone: str) -> str:
            try:
                cliente = _cliente(db, user)
            except SemConexao as e:
                return f"❌ Não executado: {e}"
            db.commit()                                   # o lote pode levar até ~150 s
            return _desfecho(resumo, await cliente.confirmar(proposta, "pin", f"whatsapp {telefone}"))

        return propor(ctx.user, resumo, int(d.get("expira_em_s") or 120), executar)
    return _corta({"status_http": d.get("status_http"), "resposta": d.get("resposta")})


_ESTADO = {"ok": "✅ confirmado", "ja": "já estava", "falhou": "❌ falhou", "incerto": "⚠️ incerto",
           "nao_enviado": "não enviado"}


def _desfecho(resumo: str, r: dict) -> str:
    """O que o helper fez, em texto de WhatsApp — o ajuste em massa item por item, com a
    conferência da leitura final (o "OLHE, deu certo" da tela)."""
    if r.get("incerto") and not r.get("resultado"):
        return (f"⚠️ {resumo}: sem resposta — a ação PODE ter chegado. Confira a leitura antes de repetir. "
                f"{r.get('error') or ''}").strip()
    res = r.get("resultado")
    if isinstance(res, dict) and res.get("itens"):
        linhas = [f"• {i.get('nome')} {i.get('sigla') or i.get('campo')}: {i.get('antes')} → {i.get('valor')} "
                  f"{i.get('unidade') or ''} — {_ESTADO.get(i.get('st'), i.get('st'))}".replace("  ", " ")
                  for i in res["itens"]]
        if (res.get("conferencia") or {}).get("tudo_confirmado"):
            fim = "✅ A leitura final confere com tudo."
        elif r.get("acompanhe"):
            fim = "⏳ O envio ainda não terminou — peça o andamento em instantes."
        else:
            fim = "⚠️ A leitura final NÃO confere em tudo — veja os itens."
        return "\n".join([f"{resumo}:", *linhas, fim])
    if not r.get("ok"):
        return f"❌ Não executado: {resumo}. {r.get('error') or r.get('reason') or ''}".strip()
    return f"✅ Executado: {r.get('resumo') or resumo}."


async def confirmar_por_mensagem(db, user, telefone: str, texto: str) -> str | None:
    """A SENHA DE ATUAÇÃO → executa a ação pendente desta pessoa. `None` = a mensagem não é
    senha e segue para a conversa. Quem chama tira do log, do histórico e do gateway toda
    mensagem tratada aqui.

    Sem ação esperando, a resposta é a mesma com a senha certa ou errada: senão, mandar
    números até a frase mudar descobriria a senha. Com ação esperando, cada erro conta, e
    `TENTATIVAS` erros bloqueiam as ações por `BLOQUEIO_S`."""
    m = SENHA.match(texto or "")
    if m is None:
        return None
    pendente = PENDENTES.get(user.id)
    if pendente is not None and monotonic() > pendente.expira:
        PENDENTES.pop(user.id, None)
        pendente = None
    if not user.senha_atuacao_hash:
        # Número solto de quem não tem senha é só um número: segue a conversa.
        return SEM_SENHA if pendente is not None or COM_PALAVRA.match(texto) else None
    if pendente is None:
        return "Não há ação esperando senha (o pedido vale poucos minutos). Nada foi feito — peça de novo."
    if monotonic() < _BLOQUEIO.get(user.id, 0):
        return "Ações bloqueadas por senha errada. Tente de novo mais tarde. Nada foi feito."
    if not conferir_senha(m.group(1), user.senha_atuacao_hash):
        erros = _ERROS[user.id] = _ERROS.get(user.id, 0) + 1
        if erros < TENTATIVAS:
            return f"Senha não confere ({erros} de {TENTATIVAS}). Nada foi feito."
        _ERROS.pop(user.id, None)
        PENDENTES.pop(user.id, None)
        _BLOQUEIO[user.id] = monotonic() + BLOQUEIO_S
        return (f"Senha errada {TENTATIVAS} vezes: o pedido foi descartado e as ações ficam bloqueadas por "
                f"{BLOQUEIO_S // 60} min. Nada foi feito.")
    _ERROS.pop(user.id, None)
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
                        "AJUSTE EM MASSA (mesmos parâmetros em vários relés): /api/massa/plano {slug, plant_id} lê; "
                        "com valores e selecionados devolve o plano (mostre-o); /api/massa/start com o MESMO corpo "
                        "vira UMA ação para o lote; /api/massa/state {job} dá o andamento. "
                        "AÇÃO (ajustar, ligar, desligar, resetar, comandar, gravar) NÃO é executada: volta uma "
                        "proposta, e só roda com a SENHA DE ATUAÇÃO que a pessoa manda."),
        "parameters": {"type": "object", "properties": {
            "rota": _ROTA,
            "corpo": {"type": "object", "description": "O JSON que a tela da web mandaria (ex.: {\"slug\": \"pirapozinho\"})."},
        }, "required": ["rota"]}}}),
}
