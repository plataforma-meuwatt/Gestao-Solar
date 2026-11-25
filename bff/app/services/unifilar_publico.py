"""O unifilar do helper num link público, temporário e só de ver (o Renan, 25/11/2026: "me dê o diagrama unifilar da
usina X … um link público e temporário do diagrama unifilar que a gente fez pelo helper Splendor, mostrando o que tá
ligado e o que não tá … nesse link não posso atuar, apenas ver; para atuar, eu envio pelo WhatsApp e vejo ao vivo").

O desenho é do helper (`web/static/unifilar.{html,js,css}`, o modo "somente ver" desde o 2.51.0, ligado pela meta
`mw-uf-ver`): o GS busca os três arquivos pelo túnel do bot (o filtro do srvclaude deixa passar só esses três, com a
chave do chamador) e o documento pela porta do bot (`/api/religa/documento` com `publico`, leitura: sem IP, porta,
endereço Modbus nem série), com o token do meuWatt de QUEM
PEDIU o link. Nenhum comando passa por aqui: comandar continua sendo pelo WhatsApp, com a senha de atuação.

O link é assinado aqui, sem tabela: a pessoa, a usina do GS e a hora. Vale `VALIDADE_S`, cai com o "encerrar todas"
dela e, a cada leitura, confere de novo que ela segue com o helper liberado no bot e a usina no recorte dela.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from app.core.datas import BRT

VALIDADE_S = 2 * 3600
ARQUIVOS = ("unifilar.html", "unifilar.js", "unifilar.css")
#: a página relê a cada 15 s e cada visita pede os três arquivos: guardados 1 min, o túnel não carrega cada visita
_GUARDADOS: dict[str, tuple[float, bytes, str]] = {}


def _assinatura(corpo: str) -> str:
    chave = ("unifilar-publico:" + get_settings().gs_jwt_secret).encode()
    return base64.urlsafe_b64encode(hmac.new(chave, corpo.encode(), hashlib.sha256).digest()[:18]).decode()


def criar(user_id: int, usina_id: int, agora: float | None = None) -> tuple[str, datetime]:
    """O link (o pedaço que vai no endereço) e quando ele vence."""
    em = int(time.time() if agora is None else agora)
    corpo = f"{user_id}.{usina_id}.{em:x}"
    return f"{corpo}.{_assinatura(corpo)}", datetime.fromtimestamp(em + VALIDADE_S, UTC)


def ler(token: str, agora: float | None = None) -> tuple[int, int, int] | None:
    """(pessoa, usina, quando foi emitido) do link assinado aqui e no prazo; senão None."""
    try:
        u, p, em, assinatura = token.split(".")
        if not hmac.compare_digest(assinatura.encode(), _assinatura(f"{u}.{p}.{em}").encode()):
            return None
        pessoa, usina, emitido = int(u), int(p), int(em, 16)
    except ValueError:
        return None
    idade = (time.time() if agora is None else agora) - emitido
    return (pessoa, usina, emitido) if 0 <= idade < VALIDADE_S else None


def pessoa_e_usina(db, token: str):
    """(pessoa, usina do GS, quando vence) do link que ainda vale para ela: assinado e no prazo, emitido depois de um
    "encerrar todas", a conta ativa, o helper liberado no bot e a usina no recorte do bot dela, com o slug do meuWatt."""
    from app.models.user import User
    from app.services import assistente_geracao as ger

    lido = ler(token)
    if lido is None:
        return None
    uid, pid, emitido = lido
    u = db.get(User, uid)
    if u is None or not u.ativo or "bot_helper" not in u.bot_ativo:
        return None
    if u.sessoes_desde is not None:
        fim = u.sessoes_desde if u.sessoes_desde.tzinfo else u.sessoes_desde.replace(tzinfo=UTC)
        if emitido < fim.timestamp():
            return None
    usina = next((p for p in ger.usinas_do_bot(db, u) if p.id == pid and p.mw_plant_slug), None)
    return (u, usina, datetime.fromtimestamp(emitido + VALIDADE_S, UTC)) if usina else None


async def arquivo(nome: str) -> tuple[bytes, str] | None:
    """Um dos três arquivos da página do helper, pelo túnel. Sem resposta, None."""
    s = get_settings()
    if nome not in ARQUIVOS or not (s.helper_bot_url and s.helper_bot_chave):
        return None
    if (g := _GUARDADOS.get(nome)) and time.monotonic() - g[0] < 60:
        return g[1], g[2]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{s.helper_bot_url.rstrip('/')}/static/{nome}",
                            headers={"X-MW-Bot-Chamador": s.helper_bot_chamador, "X-MW-Bot-Chave": s.helper_bot_chave})
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content:
        return None
    _GUARDADOS[nome] = (time.monotonic(), r.content, r.headers.get("content-type") or "application/octet-stream")
    return r.content, _GUARDADOS[nome][2]


async def pronto() -> bool:
    """O helper já tem o modo "somente ver" (2.51.0). Sem ele a página pediria as rotas da tela do helper, que não
    existem aqui: o link sairia quebrado."""
    js = await arquivo("unifilar.js")
    return bool(js) and b"mw-uf-ver" in js[0]


def pagina(html: bytes, vence: datetime) -> bytes | None:
    """A página do helper com as metas do modo "somente ver" (o documento ao lado, a hora em que o link vence) e sem
    rastro. None = a página do helper mudou e as metas não têm onde entrar."""
    metas = ('<meta name="mw-uf-ver" content="documento">'
             f'<meta name="mw-uf-ate" content="{vence.astimezone(BRT).isoformat(timespec="seconds")}">'
             '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">')
    texto = (html.decode("utf-8").replace('href="/static/unifilar.css"', 'href="unifilar.css"')
             .replace('src="/static/unifilar.js"', 'src="unifilar.js"'))
    for ancora in ('<meta charset="utf-8">', "<head>"):
        if ancora in texto:
            return texto.replace(ancora, ancora + metas, 1).encode("utf-8")
    return None
