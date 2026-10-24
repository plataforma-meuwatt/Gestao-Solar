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
#: Um número de 4 a 8 dígitos solto numa frase ("a senha é 4821", "sim, 4821").
NUMERO = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
FRASE_CURTA = 80
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


def parece_senha(texto: str) -> bool:
    """Mensagem que PODE ser a senha: nunca vai em claro ao log, nem se der erro no meio."""
    texto = texto or ""
    return SENHA.match(texto) is not None or (len(texto) <= FRASE_CURTA and len(NUMERO.findall(texto)) == 1)


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


async def alcancavel() -> tuple[bool | None, str]:
    """Se o helper responde agora (túnel + filtro + serviço). `None` = não configurado aqui.
    Usa o `ferramentas`, que só confere a chave do chamador: a plataforma não tem token."""
    if not configurado():
        return None, "O helper não está configurado neste ambiente."
    s = get_settings()
    d = await HelperBot(s.helper_bot_url, s.helper_bot_chamador, s.helper_bot_chave, "").ferramentas(espera_s=6)
    if d.get("ok"):
        return True, "Helper alcançável: o bot lê e comanda as usinas por ele."
    return False, f"Helper fora do alcance do bot: {d.get('error') or d.get('reason') or 'sem resposta'}"


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


def _usinas_pedidas(rota: str, corpo: dict) -> set[str]:
    """As usinas que o pedido toca (`slug`, `plant_id`, `slugs`, e o mesmo na query do GET)."""
    from urllib.parse import parse_qs, urlsplit

    nomes = [corpo.get("slug"), corpo.get("plant_id"), *(corpo.get("slugs") or [])]
    for k, v in parse_qs(urlsplit(rota).query).items():
        if k in ("slug", "plant_id", "slugs"):
            nomes += v
    return {str(n).strip() for n in nomes if n not in (None, "")}


async def usina_helper(ctx: ger.Contexto, a: dict) -> dict:
    rota = (a.get("rota") or "").strip()
    if not rota.startswith("/api/"):
        return {"erro": "Informe a rota do helper, começando com /api/ (veja usina_helper_catalogo)."}
    corpo = a.get("corpo") if isinstance(a.get("corpo"), dict) else {}
    # GET é leitura no helper (o catálogo `/api/devices`, `/api/healthcheck/state?id=…`): POST
    # numa rota GET virava "escrita", pedia senha e dava 404 (avaliação de 24/10/2026).
    metodo = "GET" if str(a.get("metodo") or "").upper() == "GET" else "POST"
    # O recorte do Gestão Solar vale aqui também: o token do meuWatt pode enxergar mais usinas
    # do que o gerente (ou o dono) liberou para esta conta.
    from app.api.v1.plants import usinas_do_usuario

    liberadas = {p.mw_plant_slug for p in usinas_do_usuario(ctx.db, ctx.user) if p.mw_plant_slug}
    fora = _usinas_pedidas(rota, corpo) - liberadas
    if fora:
        return {"erro": f"Usina não liberada para você no Gestão Solar: {', '.join(sorted(fora))}."}
    from app.services.vinculos import SemConexao

    try:
        cliente = _cliente(ctx, ctx.user)
    except SemConexao as e:
        return {"erro": f"Helper indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o helper lê
    d = await cliente.chamar(rota, corpo, origem=f"whatsapp {ctx.telefone}", metodo=metodo)
    if not d.get("ok"):
        return {"erro": d.get("error") or d.get("reason") or "O helper recusou.", "motivo": d.get("reason")}
    if d.get("tipo") == "leitura" and rota.split("?")[0] == "/api/registry/plants":
        resposta = d.get("resposta") if isinstance(d.get("resposta"), dict) else {}
        resposta["plants"] = [p for p in resposta.get("plants") or []
                              if isinstance(p, dict) and p.get("api_slug") in liberadas]
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
    if r.get("reason") == "proposta_inexistente":
        return ("⌛ O pedido expirou no helper (ele vale 2 minutos) — nada foi feito. Peça de novo e mande "
                "a senha logo em seguida.")
    releitura = _leitura_curta((r.get("releitura") or {}).get("resposta"))
    if not r.get("ok"):
        resposta = r.get("resposta") if isinstance(r.get("resposta"), dict) else {}
        motivo = r.get("error") or resposta.get("error") or r.get("reason") or ""
        texto = f"❌ Não executado: {resumo}. {motivo}".strip()
    else:
        texto = f"✅ Executado: {r.get('resumo') or resumo}."
    return texto + (f"\nReleitura do equipamento: {releitura}" if releitura else "")


#: Chaves de leitura que não dizem nada a quem lê no celular.
_RUIDO = {"ok", "raw", "regs", "registers", "hex", "bytes", "debug", "ms", "duracao_ms", "host", "port", "slave"}


def _leitura_curta(dados: Any, limite: int = 10) -> str:
    """A releitura em uma linha: até `limite` valores simples (`chave: valor`). O formato de
    cada driver é dele; aqui só se evita mandar o JSON cru ao WhatsApp."""
    pares: list[str] = []

    def andar(v: Any, prefixo: str = "") -> None:
        if len(pares) >= limite:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                if str(k).lower() not in _RUIDO:
                    andar(x, f"{prefixo}{k}" if not prefixo else f"{prefixo}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v[:limite]):
                andar(x, f"{prefixo}[{i}]")
        elif v is not None and prefixo:
            pares.append(f"{prefixo}: {v}")

    if isinstance(dados, dict) and dados.get("ok") is False:
        return f"falhou — {dados.get('error') or 'sem detalhe'}"
    andar(dados)
    return " · ".join(pares)


async def confirmar_por_mensagem(db, user, telefone: str, texto: str) -> str | None:
    """A SENHA DE ATUAÇÃO → executa a ação pendente desta pessoa. `None` = a mensagem não é
    senha e segue para a conversa. Quem chama tira do log, do histórico e do gateway toda
    mensagem tratada aqui.

    Sem ação esperando, a resposta é a mesma com a senha certa ou errada: senão, mandar
    números até a frase mudar descobriria a senha. Com ação esperando, cada erro conta, e
    `TENTATIVAS` erros bloqueiam as ações por `BLOQUEIO_S`."""
    texto = texto or ""
    pendente = PENDENTES.get(user.id)
    if pendente is not None and monotonic() > pendente.expira:
        PENDENTES.pop(user.id, None)
        pendente = None
    m = SENHA.match(texto)
    if m is not None:
        tentativa = m.group(1)
    elif pendente is not None and user.senha_atuacao_hash and parece_senha(texto):
        # Com ação esperando, a senha escrita numa frase ("a senha é 4821", "sim, 4821") é
        # tentativa também — senão ela ia à IA e ao log em claro (avaliação de 24/10/2026).
        tentativa = NUMERO.findall(texto)[0]
    else:
        return None
    if not user.senha_atuacao_hash:
        # Número solto de quem não tem senha é só um número: segue a conversa.
        return SEM_SENHA if pendente is not None or COM_PALAVRA.match(texto) else None
    if pendente is None:
        return ("Recebi só um número. Se era a senha de atuação: não há ação esperando (o pedido vale "
                "poucos minutos) e nada foi feito. Se era outra coisa, escreva com palavras.")
    if monotonic() < _BLOQUEIO.get(user.id, 0):
        return "Ações bloqueadas por senha errada. Tente de novo mais tarde. Nada foi feito."
    if not conferir_senha(tentativa, user.senha_atuacao_hash):
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
         "/api/read, /api/healthcheck/start, /api/alarms/feed, /api/abs/status; GET com a consulta na própria "
         "rota: /api/devices, /api/healthcheck/state?id=<id>."}

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
            "metodo": {"type": "string", "enum": ["POST", "GET"],
                       "description": "POST (padrão) ou GET — use o método que o catálogo diz para a rota. "
                                      "GET é sempre leitura: /api/devices (os comandos e ações de cada equipamento), "
                                      "/api/healthcheck/state?id=<id> (o resultado do teste de comunicação)."},
            "corpo": {"type": "object", "description": "O JSON que a tela da web mandaria (ex.: {\"slug\": \"pirapozinho\"})."},
        }, "required": ["rota"]}}}),
}
