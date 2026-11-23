"""'Processar <usina>' pelo WhatsApp: o TermoVision organiza o voo, roda os ortomosaicos e devolve o link (pedido do dono,
23/11/2026: "eu quero enviar no whats 'Processar ibitinga' aí o sistema vai organizar as pastas, falar que deu certo,
no meio do caminho manda um link público com os status, quando acabar, ele manda um link público com o ortomosaico").

Contrato: `docs/contrato-gs-processar.md` do repositório do TermoVision (outro projeto, outro terminal; quem muda avisa).
- Quem pede é a PESSOA: o GS assina a asserção dela (`login_externo.assinar_login`, a mesma do "Entrar com o Gestão
  Solar") e o TermoVision abre a sessão dela; a plataforma nunca. Sem o TermoVision liberado, a ferramenta não existe.
- Ler as opções volta na hora; pedir o processamento é AÇÃO com o Sim (roda horas nos PCs e pode criar a usina).
- O andamento chega no aviso (`api/v1/termovision_aviso.py`): ele só RELÊ o andamento no TermoVision pelo token de um
  pedido daqui (`gs_processamentos_tv`) e manda uma mensagem curta quando a etapa muda.
"""

import logging
import unicodedata

import httpx

from app.core.config import get_settings
from app.models.processamento_tv import ProcessamentoTV
from app.models.user import Perfil
from app.services import assistente_helper as helper
from app.services import login_externo

log = logging.getLogger(__name__)

PRAZO_S = 600
_PORTAO = {Perfil.GESTOR_EMPRESA: "empresa", Perfil.TECNICO: "tecnico", Perfil.CLIENTE: "cliente"}
AVISO = "/api/v1/interno/termovision/processar"


def _base() -> str:
    return get_settings().termovision_api_url.rstrip("/")


def disponivel(user) -> bool:
    return user.perfil in _PORTAO and bool(user.termovision_liberado)


def assercao(db, user, liberado: bool | None = None) -> str:
    """A asserção da pessoa para o TermoVision (2 min, uso único). `liberado` sobrepõe o acesso (desligar)."""
    a = login_externo.assinar_login(user, login_externo.TERMOVISION, _PORTAO.get(user.perfil, "painel"),
                                    getattr(user, "empresa_da_sessao", None) or user.empresa_id,
                                    login_externo.meuplano_id_de(db, user.id))
    if liberado is None:
        return a
    import jwt                                             # o mesmo token, só com o acesso do momento
    dados = jwt.decode(a, options={"verify_signature": False})
    dados[login_externo.TERMOVISION] = liberado
    return jwt.encode(dados, login_externo._privada(), algorithm="RS256")


def _detalhe(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except ValueError:
        d = None
    return d if isinstance(d, str) and d else f"o TermoVision respondeu {r.status_code}"


async def _entrar(c: httpx.AsyncClient, db, user) -> str | None:
    """Abre a sessão da pessoa no cliente `c` (o cookie fica nele). Devolve o erro em português, ou None."""
    try:
        r = await c.post(f"{_base()}/api/conta/gs", json={"assercao": assercao(db, user)})
    except login_externo.SemChave as e:
        return str(e)
    except httpx.HTTPError:
        return "O TermoVision não respondeu agora. Nada foi feito: tente de novo em alguns minutos."
    return None if r.status_code < 300 else f"O TermoVision recusou a entrada desta pessoa: {_detalhe(r)}."


def _nome(s: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                            if unicodedata.category(c) != "Mn").split())


def _dona(opcoes: dict, pedida: str | None) -> tuple[dict | None, str | None]:
    empresas = opcoes.get("empresas") or []
    if pedida:
        achadas = [e for e in empresas if _nome(pedida) in _nome(e["nome"])]
        if len(achadas) == 1:
            return achadas[0], None
        return None, (f"Empresa '{pedida}' não é uma das que esta pessoa escolhe: "
                      + ", ".join(e["nome"] for e in empresas) + ". Pergunte qual.")
    if len(empresas) == 1:
        return empresas[0], None
    sugerida = next((e for e in empresas if e["id"] == opcoes.get("dona_sugerida")), None)
    if sugerida:
        return sugerida, None
    return None, "De quem é a usina nova? Pergunte, com as opções: " + ", ".join(e["nome"] for e in empresas) + "."


async def processar_usina(ctx, a: dict) -> dict:
    pasta = (a.get("usina") or "").strip()
    if not pasta:
        return {"erro": "Falta o nome da usina (a pasta no drive de envio). Pergunte."}
    db, user = ctx.db, ctx.user
    async with httpx.AsyncClient(timeout=30) as c:
        erro = await _entrar(c, db, user)
        if erro:
            return {"erro": erro}
        try:
            r = await c.get(f"{_base()}/api/processar/opcoes", params={"pasta": pasta})
        except httpx.HTTPError:
            return {"erro": "O TermoVision não respondeu agora. Nada foi feito."}
    if r.status_code >= 300:
        return {"erro": f"{_detalhe(r)}. Nada foi feito."}
    o = r.json()
    usina, envio = o.get("usina"), o.get("no_envio") or {}
    if (o.get("usinas_com_o_nome") or 0) > 1:
        return {"erro": f"Há {o['usinas_com_o_nome']} usinas com o nome '{pasta}' no TermoVision: diga isso, não escolha."}
    if o.get("processando"):
        nome = (usina or {}).get("nome") or pasta
        link = f" Andamento: {o['status_url']}" if o.get("status_url") else ""
        return {"erro": f"{nome} já está sendo processada: não abri outro.{link}"}
    if not usina and not envio.get("arquivos"):
        return {"erro": f"Não achei a usina nem a pasta '{pasta}' no drive de envio do TermoVision. As fotos vão numa "
                        f"pasta com o nome da usina, no drive de envio da empresa; depois é só pedir de novo."}
    dona = None
    if not usina:
        dona, erro = _dona(o, a.get("dona"))
        if erro:
            return {"erro": erro, "empresas": [e["nome"] for e in o.get("empresas") or []]}
    nome = (usina or {}).get("nome") or pasta
    resumo = f"Processar {nome} no TermoVision" + ("" if usina else f" (usina NOVA, de {dona['nome']})")
    detalhes = [f"{envio.get('arquivos') or 0} arquivo(s) novos no drive de envio",
                "Organiza as fotos, roda os ortomosaicos e o mapa de temperatura nos PCs (pode levar horas)",
                "Mando o link do andamento agora e aviso a cada etapa"]
    corpo = {"pasta": pasta, "avisar_url": get_settings().gs_api_publica.rstrip("/") + AVISO,
             **({"dona": dona["id"]} if dona else {})}

    async def executar(db, user, telefone: str) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            erro = await _entrar(c, db, user)
            if erro:
                return f"❌ {erro}"
            try:
                r = await c.post(f"{_base()}/api/processar", json=corpo)
            except httpx.TimeoutException:
                return "⚠️ O TermoVision não respondeu a tempo: o pedido PODE ter entrado. Peça de novo em alguns minutos."
            except httpx.HTTPError:
                return "❌ O TermoVision não respondeu. Nada foi feito."
        if r.status_code == 409:
            return f"⏳ {_detalhe(r)}"
        if r.status_code >= 300:
            return f"❌ {_detalhe(r)}. Nada foi feito."
        d = r.json()
        db.add(ProcessamentoTV(token=d["token"], gs_user_id=user.id, telefone=telefone,
                               usina=(d.get("usina") or {}).get("nome") or nome))
        db.commit()
        return (f"✅ {(d.get('usina') or {}).get('nome') or nome} entrou para processar. "
                f"Andamento: {d['status_url']}\nAviso aqui a cada etapa.")

    return helper.propor(ctx, resumo, PRAZO_S, executar, detalhes, parte=None, confirmacao="sim")


FERRAMENTA = {"type": "function", "function": {
    "name": "processar_usina",
    "description": ("PROCESSAR um voo no TermoVision: 'Processar Ibitinga'. Organiza as fotos que estão no drive de "
                    "envio, roda os ortomosaicos (RGB e térmico) e o mapa de temperatura e devolve o link. É AÇÃO: o "
                    "sistema mostra o resumo e a pessoa confirma com Sim. Usina nova: se houver mais de uma empresa, "
                    "a ferramenta pede a dona; pergunte e chame de novo com `dona`."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "o nome como a pessoa disse (a pasta no drive de envio)"},
        "dona": {"type": "string", "description": "a empresa dona da usina NOVA, só quando a ferramenta pedir"}},
        "required": ["usina"]}}}

FERRAMENTAS = {"processar_usina": (processar_usina, FERRAMENTA)}


def permitidas(user) -> list[str]:
    return list(FERRAMENTAS) if disponivel(user) else []


# --------------------------------------------------------------------------- o aviso de cada etapa
def mensagem(p: dict) -> tuple[str, str]:
    """(a chave do momento, a frase). A mesma chave de antes não vira mensagem nova."""
    usina, estado = p.get("usina") or "a usina", p.get("estado")
    if estado == "concluido":
        return "concluido", f"✅ {usina} pronta: {_base()}{p.get('link_final') or ''}"
    if estado == "erro":
        e = next((x for x in p.get("etapas") or [] if x.get("estado") == "erro"), {})
        onde = f" em {e['titulo']}" if e.get("titulo") else ""
        return "erro", f"❌ O processamento de {usina} parou{onde}: {p.get('erro') or e.get('erro') or 'sem motivo dito'}"
    if estado == "cancelado":
        return "cancelado", f"⏹️ O processamento de {usina} foi cancelado."
    etapas = p.get("etapas") or []
    i, e = next(((i, x) for i, x in enumerate(etapas) if x.get("estado") == "rodando"), (None, None))
    if e is None:
        return f"{estado}", ""
    texto = f" ({e['texto']})" if e.get("texto") else ""
    return f"rodando:{i}", f"🛠️ {usina}: {e['titulo']}, etapa {i + 1} de {len(etapas)}{texto}"


async def provisionar(db, user, liberado: bool) -> str | None:
    """Liga (cria ou acha) ou desliga a conta da pessoa no TermoVision. Devolve o erro, ou None."""
    if user.perfil not in _PORTAO:
        return None                                        # a plataforma nunca nasce lá
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{_base()}/api/conta/gs/provisionar", json={"assercao": assercao(db, user, liberado)})
    except (httpx.HTTPError, login_externo.SemChave) as e:
        log.warning("termovision: provisionar %s falhou: %s", user.apelido, e)
        return "o TermoVision não respondeu"
    if r.status_code >= 300:
        log.warning("termovision: provisionar %s recusado: %s", user.apelido, _detalhe(r))
        return _detalhe(r)
    log.info("termovision: provisionar %s → %s", user.apelido, r.json().get("acao"))
    return None
