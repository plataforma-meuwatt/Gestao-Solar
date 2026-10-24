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

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from app.clients.helper_bot import HelperBot
from app.core.config import get_settings
from app.core.security import conferir_senha
from app.services import assistente_geracao as ger

#: A mensagem INTEIRA é uma tentativa de senha: só o número, ou "senha 482913", "confirmo 482913".
SENHA = re.compile(r"^\s*(?:confirmo|senha)?\s*[:\-]?\s*(\d{6,8})\s*[.!]?\s*$", re.IGNORECASE)  # sobre `normalizar`
COM_PALAVRA = re.compile(r"^\s*(?:confirmo|senha)\b", re.IGNORECASE)
#: CANDIDATO a senha: número de 6 a 8 dígitos solto em qualquer ponto da mensagem (a senha tem
#: 6 a 8). "OS 1639" e "2025" não são candidatos e seguem para a conversa como sempre.
CANDIDATO = re.compile(r"(?<!\d)(\d{6,8})(?!\d)")
#: O que a IA, o histórico e o log veem no lugar de um candidato (certo OU errado: um dígito
#: errado entregaria os outros cinco).
OCULTO = "[número oculto]"
#: Para a pessoa SEM cadastro (a conta não foi conferida): mensagem que pode ser senha.
NUMERO = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
FRASE_CURTA = 80
#: Números conferidos por mensagem: cada conferência custa ~0,45 s (pbkdf2, 600 mil voltas).
MAX_CONFERIDOS = 3
#: "não", "cancela", "esquece"… com uma ação esperando: desarma, e o SISTEMA responde.
CANCELA = re.compile(r"^\s*(?:n[ãa]o\b|cancel|desist|esquec|para\b|pare\b|deixa\b)", re.IGNORECASE)
#: O que fica no log, no histórico e no gateway no lugar da senha digitada.
OCULTA = "[senha de atuação]"
TENTATIVAS = 5
BLOQUEIO_S = 15 * 60
TETO_RESPOSTA = 12000
SEM_SENHA = ("Você ainda não tem senha de atuação — sem ela o bot só lê. Peça ao gerente da sua "
             "O&M para definir no oem-gs (Bot do WhatsApp). Nada foi feito.")
#: A MESMA frase para a senha certa e para a errada, sem ação esperando: senão, mandar números
#: até a frase mudar descobriria a senha.
NADA_ESPERANDO = ("Não há ação esperando senha (o pedido vale poucos minutos). Nada foi feito — se era "
                  "outra coisa, escreva com palavras.")
BLOQUEADO = "Ações bloqueadas por senha errada por 15 minutos. Nada foi feito."
#: O que vai ao pé da resposta quando uma mensagem que não era só a senha derrubou a ação.
ACAO_CANCELADA = ("(A ação que esperava a sua senha foi cancelada. Para executar uma ação, mande só a "
                  "senha, sem outras palavras.)")
PARTE_DESLIGADA = "Essa parte do bot foi desligada pelo gerente da O&M enquanto a ação esperava. Nada foi feito."
CANCELADO = "Cancelado: a ação não será executada. Nada foi feito."


@dataclass
class Pendente:
    resumo: str
    expira: float
    #: Executa a ação confirmada — (db, conta, telefone) → a frase que vai ao WhatsApp.
    executar: Callable[[Any, Any, str], Awaitable[str]]
    prazo_s: int = 120
    detalhes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    #: A parte do bot que a ação usa (`bot_helper`, `bot_meuplano`): conferida de novo na
    #: hora da senha — o gerente pode desligá-la no meio.
    parte: str = "bot_helper"


#: A ação que cada pessoa (id da conta) tem esperando a senha — uma por vez.
#: ponytail: em memória, um processo só (o uvicorn da API roda com um worker); com mais de
#: um, isto vai para o banco. A proposta vale minutos: perder no deploy é aceitável.
PENDENTES: dict[int, Pendente] = {}
#: Conferências que falharam por conta (quantas, desde quando), e até quando as ações estão
#: bloqueadas. Em memória: um reinício zera — e cada tentativa ainda exige o celular da pessoa.
_ERROS: dict[int, tuple[int, float]] = {}
_BLOQUEIO: dict[int, float] = {}


@dataclass
class Analise:
    """O que a mensagem tem de senha, olhado UMA vez por mensagem."""

    #: Números de 6 a 8 dígitos (depois de juntar "482 913"): escondidos, certos ou errados.
    candidatos: list[str] = field(default_factory=list)
    #: A mensagem é APENAS a senha ("482913", "senha 482-913") — a única que é tentativa.
    pura: bool = False
    acertou: bool = False
    bloqueada: bool = False


#: "482 913", "482-913", "482.913" → "482913": a senha com separador vazava inteira.
_SEPARADOR = re.compile(r"(?<=\d)[ .\-](?=\d)")


def normalizar(texto: str) -> str:
    return _SEPARADOR.sub("", texto or "")


async def analisar(user, texto: str) -> Analise:
    """Esconde todo candidato e confere a senha SÓ quando a mensagem é apenas ela — fora do
    laço da API (`to_thread`: o pbkdf2 leva ~0,45 s). Número dentro de frase (UC, CEP,
    protocolo… ou a senha escrita no meio de "não faça") nunca é conferido: não conta erro, não
    bloqueia ninguém e não vira oráculo; só some da IA, do log, do histórico e do gateway."""
    if user is None or not user.senha_atuacao_hash:
        return Analise()
    normal = normalizar(texto)
    candidatos = list(dict.fromkeys(CANDIDATO.findall(normal)))
    m = SENHA.match(normal)
    if m is None:
        return Analise(candidatos)
    if monotonic() < _BLOQUEIO.get(user.id, 0):
        return Analise(candidatos, pura=True, bloqueada=True)
    acertou = await asyncio.to_thread(conferir_senha, m.group(1), user.senha_atuacao_hash)
    return Analise(candidatos, pura=True, acertou=acertou)


def mascarar(texto: str) -> str:
    return CANDIDATO.sub(OCULTO, normalizar(texto))


def desarmar(user_id: int) -> bool:
    """Tira a ação que esperava a senha. Devolve se havia uma (valendo)."""
    p = PENDENTES.pop(user_id, None)
    return p is not None and monotonic() <= p.expira


def _contar_falhas(user_id: int, falhas: int) -> int:
    """Toda tentativa errada conta (a mensagem que é só o número), com ou sem ação esperando.
    Zera depois de `BLOQUEIO_S` sem erro. Devolve o total; no limite, bloqueia."""
    total, desde = _ERROS.get(user_id, (0, monotonic()))
    if monotonic() - desde > BLOQUEIO_S:
        total, desde = 0, monotonic()
    total += falhas
    if total >= TENTATIVAS:
        _ERROS.pop(user_id, None)
        PENDENTES.pop(user_id, None)
        _BLOQUEIO[user_id] = monotonic() + BLOQUEIO_S
    else:
        _ERROS[user_id] = (total, desde)
    return total


def parece_senha(texto: str) -> bool:
    """Mensagem que PODE ser a senha, para os caminhos em que a conta ainda não foi conferida
    (número sem cadastro, erro no meio): nunca vai em claro ao log."""
    texto = texto or ""
    return SENHA.match(texto) is not None or (len(texto) <= FRASE_CURTA and len(NUMERO.findall(texto)) == 1)


def validar_senha_atuacao(senha: str) -> str:
    """6 a 8 números, sem repetir nem seguir em sequência (111111, 123456, 654321). Devolve
    limpa. Seis no mínimo: a senha anda numa conversa de WhatsApp, e cada dígito a mais
    multiplica por dez o trabalho de quem tentar adivinhar."""
    s = (senha or "").strip()
    if not re.fullmatch(r"\d{6,8}", s):
        raise ValueError("A senha de atuação tem de 6 a 8 números.")
    passos = {int(b) - int(a) for a, b in zip(s, s[1:])}
    if passos in ({0}, {1}, {-1}):
        raise ValueError("Senha fácil demais (número repetido ou em sequência). Escolha outra.")
    return s


def nova_senha(user_id: int) -> None:
    """Senha trocada: zera as tentativas erradas e o bloqueio."""
    _ERROS.pop(user_id, None)
    _BLOQUEIO.pop(user_id, None)


def propor(ctx, resumo: str, prazo_s: int, executar, detalhes=(), avisos=(), parte: str = "bot_helper") -> dict:
    """Guarda a ação desta pessoa e devolve o que o modelo mostra. Nada rodou.

    - Sem senha de atuação cadastrada nem guarda: a ação não teria como ser confirmada.
    - UMA ação por mensagem: a segunda é recusada (antes, só a última ficava armada e a IA
      descrevia as duas).
    - O texto que a pessoa confirma é do SISTEMA, não da IA: `bloco_da_proposta` é acrescentado
      ao pé da resposta, com o resumo exato, os avisos e o prazo (`assistente._atender`)."""
    user = ctx.user
    if not user.senha_atuacao_hash:
        PENDENTES.pop(user.id, None)
        return {"proposta_pendente": resumo, "sem_senha_de_atuacao": True,
                "instrucao": ("NADA foi executado, e não pode ser: esta pessoa ainda não tem SENHA DE ATUAÇÃO. "
                              "Mostre o resumo e diga que o gerente da O&M define a senha dela no oem-gs "
                              "(Bot do WhatsApp). Leitura continua liberada.")}
    if ctx.proposta is not None:
        return {"erro": "Uma ação por vez: já há uma esperando a senha nesta mensagem. Fale só dela."}
    p = Pendente(resumo, monotonic() + prazo_s, executar, prazo_s, [d for d in detalhes if d], [a for a in avisos if a],
                 parte)
    PENDENTES[user.id] = ctx.proposta = p
    return {
        "proposta_pendente": resumo,
        "vale_por_s": prazo_s,
        "instrucao": ("NADA foi executado. O SISTEMA acrescenta ao fim da sua resposta o resumo exato da ação e "
                      "o pedido da SENHA DE ATUAÇÃO: diga em uma linha o que será feito e não repita o resumo. "
                      "Nunca peça a senha de login, nunca escreva nem invente senha, nunca diga que fez."),
    }


def bloco_da_proposta(p: Pendente) -> str:
    """O que a pessoa confirma com a senha — escrito pelo sistema, palavra por palavra."""
    linhas = ["🔒 *Ação esperando a sua senha de atuação*", f"• {p.resumo}"]
    linhas += [f"  – {d}" for d in p.detalhes]
    linhas += [f"⚠️ {a}" for a in p.avisos]
    # A hora-limite, e não "em até 2 min": o prazo corre desde a proposta, e a IA leva de 17 a
    # 65 s para responder.
    from datetime import datetime, timedelta

    from app.core.datas import BRT

    limite = datetime.now(BRT) + timedelta(seconds=max(0.0, p.expira - monotonic()))
    linhas.append(f"Para executar, responda só com a senha até as {limite:%H:%M}. Qualquer outra mensagem cancela.")
    return "\n".join(linhas)

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
    bot = HelperBot(s.helper_bot_url, s.helper_bot_chamador, s.helper_bot_chave, "")
    d = await bot.ferramentas(espera_s=6)
    if not d.get("ok"):
        return False, f"Helper fora do alcance do bot: {d.get('error') or d.get('reason') or 'sem resposta'}"
    # O túnel responder não prova que as USINAS respondem: o Modbus sai pela VPN do servidor do
    # helper, e ela ficou 11 h sem contato em 24/10/2026 com este selo verde.
    rede = await bot.rede()
    idade = rede.get("vpn_ultimo_contato_s")
    if not rede.get("ok"):
        return False, "Helper responde, mas não deu para conferir a rede até as usinas (VPN)."
    if idade is None:
        return False, "Helper responde, mas a rede até as usinas (VPN) nunca fez contato."
    if idade > VPN_PARADA_S:
        return False, (f"Helper responde, mas a rede até as usinas (VPN) está sem contato há {_duracao(idade)}: "
                       "leitura e comando de equipamento não chegam lá.")
    return True, "Helper e rede das usinas no ar: o bot lê e comanda as usinas por ele."


#: O wg0 renova o contato a cada 25 s (PersistentKeepalive); 5 min sem contato é rede parada.
VPN_PARADA_S = 300


def _duracao(segundos: int) -> str:
    return f"{segundos // 3600} h" if segundos >= 3600 else f"{max(1, segundos // 60)} min"


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


#: Campos que trazem o SLUG da usina num item de resposta do helper (o `plant_id` dele é o
#: slug). Nome de exibição não entra: "Pirapozinho" não é "pirapozinho" e o item sumiria.
_CAMPOS_DE_USINA = ("api_slug", "slug", "plant_id")


def _so_liberadas(dados: Any, liberadas: set[str]) -> Any:
    """Tira das listas os itens de usina fora do recorte (o item que diz a usina num campo de
    texto que não está em `liberadas`). O resto da resposta fica como veio."""
    if isinstance(dados, dict):
        return {k: _so_liberadas(v, liberadas) for k, v in dados.items()}
    if isinstance(dados, list):
        saida = []
        for item in dados:
            if isinstance(item, dict) and any(
                isinstance(item.get(c), str) and item[c] and item[c] not in liberadas for c in _CAMPOS_DE_USINA
            ):
                continue
            saida.append(_so_liberadas(item, liberadas))
        return saida
    return dados


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
    liberadas = {p.mw_plant_slug for p in ger.usinas_do_bot(ctx.db, ctx.user) if p.mw_plant_slug}
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
    if d.get("tipo") == "leitura":
        # Leitura que não nomeia a usina (`/api/alarms/feed`, a lista de usinas…) volta com o
        # que o TOKEN enxerga: os itens de usina fora do recorte do Gestão Solar saem aqui.
        d["resposta"] = _so_liberadas(d.get("resposta"), liberadas)
    if d.get("tipo") == "proposta":
        proposta, resumo = d["proposta"], d.get("resumo") or rota

        async def executar(db, user, telefone: str) -> str:
            try:
                cliente = _cliente(db, user)
            except SemConexao as e:
                return f"❌ Não executado: {e}"
            db.commit()                                   # o lote pode levar até ~150 s
            return _desfecho(resumo, await cliente.confirmar(proposta, "pin", f"whatsapp {telefone}"))

        return propor(ctx, resumo, int(d.get("expira_em_s") or 120), executar)
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


async def confirmar_por_mensagem(db, user, telefone: str, texto: str, analise: Analise | None = None,
                                 esperava: bool = False) -> str | None:
    """A mensagem que é APENAS a senha de atuação → executa a ação esperando. `None` = segue
    para a conversa (com os candidatos já escondidos por quem chama).

    Quem chama (`assistente._atender`) DESARMA a ação antes, em toda mensagem que não é só a
    senha — frase, "limpar", áudio, imagem: "qualquer outra mensagem cancela" é o que o bloco
    da ação promete, e "não faça! senha 482913" executava (avaliação de 24/10/2026).

    - Bloqueada: a tentativa recebe `BLOQUEADO`, certa ou errada.
    - Certa: executa — se a parte do bot ainda estiver ligada —, ou `NADA_ESPERANDO`.
    - Errada: conta; `TENTATIVAS` erros bloqueiam por `BLOQUEIO_S`. Sem ação esperando, a frase
      é a mesma da certa.
    - "não"/"cancela" com uma ação que acabou de ser desarmada: `CANCELADO`, pelo sistema."""
    normal = normalizar(texto)
    if SENHA.match(normal) is None:
        return CANCELADO if esperava and CANCELA.match(normal) else None
    analise = analise or await analisar(user, texto)
    pendente = PENDENTES.get(user.id)
    if pendente is not None and monotonic() > pendente.expira:
        PENDENTES.pop(user.id, None)
        pendente = None
    if not user.senha_atuacao_hash:
        return SEM_SENHA if pendente is not None or COM_PALAVRA.match(normal) else None
    if analise.bloqueada:
        return BLOQUEADO
    if analise.acertou:
        if pendente is None:
            return NADA_ESPERANDO
        PENDENTES.pop(user.id, None)      # uma vez só, aconteça o que acontecer
        _ERROS.pop(user.id, None)
        if pendente.parte not in user.bot_ativo:
            return PARTE_DESLIGADA
        return await pendente.executar(db, user, telefone)
    total = _contar_falhas(user.id, 1)
    if total >= TENTATIVAS:
        return (f"Senha errada {TENTATIVAS} vezes: o pedido foi descartado e as ações ficam bloqueadas por "
                f"{BLOQUEIO_S // 60} min. Nada foi feito.")
    return f"Senha não confere ({total} de {TENTATIVAS}). Nada foi feito." if pendente else NADA_ESPERANDO


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
