"""Localização do WhatsApp gravada como coordenada da usina no meuPlano (pedido do Renan, 29/10/2026).

A pessoa manda a localização (📎 → Localização). O gateway entrega os números da Meta (`midia`: lat, lng, nome,
endereço); eles ficam guardados aqui na chegada e a IA lê só «[📍 localização recebida…]». Ela pergunta de qual usina
é e chama `gravar_coordenada` com a usina: os números NUNCA passam pela IA (um dígito trocado põe a usina em outra
cidade). O sistema lê a usina no meuPlano com o token DELA: sem coordenada, propõe gravar; com, propõe substituir e
diz a distância. Confirmada com o Sim, vai pela rota do app de campo (`POST /usinas/{id}/coordenada`), que confere a
permissão de lá (`meuacesso.usinas.coordenada`).
"""

import re
import unicodedata
from math import asin, cos, radians, sin, sqrt
from time import monotonic
from urllib.parse import unquote

import httpx

from app.services import assistente_helper as helper

#: A última localização de cada número. ponytail: em memória, como as fotos (`assistente_fotos`); o deploy esquece.
_RECEBIDAS: dict[str, dict] = {}
VALIDADE_S = 30 * 60
PRAZO_S = 600
PERMISSAO = "meuacesso.usinas.coordenada"


def e_local(evento: dict) -> bool:
    m = evento.get("midia") or {}
    return evento.get("tipo") == "location" and isinstance(m.get("lat"), (int, float)) \
        and isinstance(m.get("lng"), (int, float))


def guardar(telefone: str, evento: dict) -> None:
    agora = monotonic()
    for velho in [t for t, l in _RECEBIDAS.items() if agora - l["em"] >= VALIDADE_S]:
        del _RECEBIDAS[velho]
    m = evento["midia"]
    _RECEBIDAS[telefone] = {"lat": float(m["lat"]), "lng": float(m["lng"]), "em": agora,
                            "rotulo": ", ".join(str(x).strip() for x in (m.get("nome"), m.get("endereco")) if x)}


def recebida(telefone: str) -> dict | None:
    loc = _RECEBIDAS.get(telefone)
    return loc if loc is not None and monotonic() - loc["em"] < VALIDADE_S else None


def _ponto(lat: float, lng: float) -> str:
    return f"{lat:.6f}, {lng:.6f}"


def _mapa(lat: float, lng: float) -> str:
    return f"https://maps.google.com/?q={lat:.6f},{lng:.6f}"


def _waze(lat: float, lng: float) -> str:
    return f"https://waze.com/ul?ll={lat:.6f},{lng:.6f}&navigate=yes"


#: Link do Google Maps no texto (06/11/2026, dono: "eu quero que o bot entenda links Google Maps"; o bot respondia que
#: não abria link). O SISTEMA lê o ponto do link, como o da localização do 📎: a IA não escreve número.
LINK = re.compile(r"https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|(?:www\.)?google\.[a-z.]+/maps|maps\.google\.[a-z.]+)"
                  r"[^\s<>]*", re.I)
#: O PINO do lugar (!3d…!4d…) e, sem ele, o ponto pedido (q=, query=, ll=, destination=, /place/, /search/). O "@" é
#: a câmera do mapa, não um ponto: não vale.
_PINO = re.compile(r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)")
_PEDIDO = re.compile(r"(?:[?&](?:q|query|ll|destination|daddr)=|/place/|/search/)(-?\d{1,2}\.\d+),\s*\+?(-?\d{1,3}\.\d+)")


def _ponto_da_url(url: str) -> tuple[float, float] | None:
    u = unquote(unquote(url)).replace("+", " ")
    m = _PINO.search(u) or _PEDIDO.search(u)
    if m is None:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


async def _ponto_do_link(url: str) -> tuple[float, float] | None:
    """O ponto do link; o curto (maps.app.goo.gl) é seguido, só para endereço do Google, até 3 saltos."""
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as c:
            for _ in range(3):
                if (ponto := _ponto_da_url(url)) is not None:
                    return ponto
                r = await c.get(url)
                destino = r.headers.get("location")
                if not r.is_redirect or not destino or not LINK.match(destino):
                    return None
                url = destino
    except httpx.HTTPError:
        return None
    return _ponto_da_url(url)


#: As COORDENADAS escritas (11/11/2026, o dono: "eu mandei coordenada, ele deveria entender e gravar"; o bot respondia que
#: coordenada em texto não valia). Decimal com 4 casas ou mais (o "Copiar coordenadas" do Google Maps dá 5 a 7; número de
#: energia não chega a 4), ponto ou vírgula decimal, separadas por vírgula, ponto e vírgula ou espaço; ou em graus, minutos
#: e segundos (22°16'48.8"S 51°31'31.7"W; O e L em português).
_NUM = r"[-−]?\d{1,3}[.,]\d{4,}"
_PAR = re.compile(rf"(?<![\w.,/=-])({_NUM})\s*(?:[,;]\s*|\s+)({_NUM})(?![\w.,])")
_GMS_UM = r"(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:[\"″]|'')?\s*"
_GMS = re.compile(_GMS_UM + r"([NSns])[\s,;]+" + _GMS_UM + r"([LOWElowe])")


def _decimal(t: str) -> float:
    return float(t.replace("−", "-").replace(",", "."))


def _coordenadas(texto: str) -> tuple[tuple[float, float], int] | None:
    """O ponto escrito no texto e onde ele termina, ou None. Os links ficam de fora (o deles é lido pelo link)."""
    t = re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), texto or "")
    if m := _GMS.search(t):
        g = m.groups()
        lat = (int(g[0]) + int(g[1]) / 60 + _decimal(g[2]) / 3600) * (-1 if g[3] in "Ss" else 1)
        lng = (int(g[4]) + int(g[5]) / 60 + _decimal(g[6]) / 3600) * (-1 if g[7] in "OoWw" else 1)
    elif m := _PAR.search(t):
        lat, lng = _decimal(m.group(1)), _decimal(m.group(2))
    else:
        return None
    return ((lat, lng), m.end()) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


async def do_link(telefone: str, texto: str) -> str:
    """O texto com a marca de localização depois do link do Google Maps ou das coordenadas escritas (o ponto fica
    guardado, como o do 📎)."""
    m = LINK.search(texto or "")
    if m is None:
        achado = _coordenadas(texto)
        if achado is None:
            return texto
        (lat, lng), fim = achado
        guardar(telefone, {"midia": {"lat": lat, "lng": lng}})
        return texto[:fim] + " [📍 localização recebida pelas coordenadas escritas, ainda não gravada]" + texto[fim:]
    ponto = await _ponto_do_link(m.group(0).rstrip(".,;)"))
    if ponto is None:
        marca = " [🔗 link do Google Maps sem um ponto que eu consiga ler: peça a localização pelo 📎 → Localização]"
    else:
        guardar(telefone, {"midia": {"lat": ponto[0], "lng": ponto[1]}})
        marca = " [📍 localização recebida pelo link do Google Maps, ainda não gravada]"
    return texto[:m.end()] + marca + texto[m.end():]


def so_link(texto: str) -> bool:
    """A mensagem é só o link (ou só as coordenadas): o pedido costuma vir logo depois, como na foto sem legenda."""
    t = (texto or "").strip()
    return bool(LINK.fullmatch(t) or _PAR.fullmatch(t) or _GMS.fullmatch(t))


def mensagem(telefone: str) -> str:
    """O que a IA lê no lugar da localização."""
    loc = recebida(telefone) or {}
    return "[📍 localização recebida, ainda não gravada" + (f": {loc['rotulo']}" if loc.get("rotulo") else "") + "]"


def _distancia(lat1: float, lng1: float, lat2: float, lng2: float) -> str:
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    m = 2 * 6371000.0 * asin(sqrt(h))
    return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.1f} km".replace(".", ",")


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower().strip()


def _rotulo_da_usina(u: dict) -> str:
    extra = ", ".join(x for x in ("esporádica" if u.get("is_commissioning") else "", u.get("city") or "") if x)
    return f"{u.get('name')} (id {u.get('id')}{', ' + extra if extra else ''})"


def escolher(usinas: list[dict], termo: str) -> tuple[dict | None, list[dict]]:
    """A usina pelo nome (ou pelo id que a lista de opções mostra): (a escolhida, ou None e as candidatas)."""
    t = _sem_acento(str(termo))
    if t.isdigit():
        por_id = [u for u in usinas if str(u.get("id")) == t]
        if por_id:
            return por_id[0], por_id
    achadas = [u for u in usinas if t and t in _sem_acento(u.get("name") or "")]
    exatas = [u for u in achadas if _sem_acento(u.get("name") or "") == t]
    for grupo in (achadas, exatas):
        if len(grupo) == 1:
            return grupo[0], grupo
    return None, achadas


FERRAMENTA = {"type": "function", "function": {
    "name": "gravar_coordenada",
    "description": ("Grava a LOCALIZAÇÃO que a pessoa mandou por aqui (a mensagem dela aparece como «[📍 localização "
                    "recebida…]») como a coordenada da usina no meuPlano. Passe só a usina: os números vêm da própria "
                    "localização, nunca os escreva. Se a usina já tem coordenada, a ação é SUBSTITUIR e o resumo mostra "
                    "a distância. Sem saber a usina, pergunte qual é."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "nome da usina (ou o id das opções)"}},
        "required": ["usina"]}}}


async def gravar_coordenada(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    loc = recebida(ctx.telefone)
    if loc is None:
        return {"erro": "Não há localização recebida (ela fica guardada 30 min). Peça que a pessoa mande de novo pelo "
                        "📎 → Localização."}
    if not (a.get("usina") or "").strip():
        return {"erro": "Falta a usina: pergunte à pessoa de qual usina é a localização."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    try:
        if PERMISSAO not in (await mp.permissoes()):
            return {"erro": "O papel desta pessoa no meuPlano não marca coordenada de usina. Nada foi gravado: o "
                            "gestor da O&M pode liberar."}
        usina, candidatas = escolher(await mp.usinas(), a["usina"])
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi gravado."}
    if usina is None:
        return {"erro": f"Usina '{a['usina']}' " + ("é ambígua" if candidatas else "não está entre as dela")
                        + ": pergunte qual é.",
                "opcoes": [_rotulo_da_usina(u) for u in candidatas]}
    uid, nome = int(usina["id"]), usina.get("name")
    lat, lng = loc["lat"], loc["lng"]
    nova = _ponto(lat, lng) + (f" ({loc['rotulo']})" if loc["rotulo"] else "")
    tem_numero = usina.get("latitude") is not None and usina.get("longitude") is not None
    tem = tem_numero or bool((usina.get("coordinates") or "").strip())
    if not tem:
        resumo, linhas = f"Gravar a coordenada da usina {nome}", [f"Local: {nova}", _mapa(lat, lng)]
    else:
        gravada = (f"{_ponto(usina['latitude'], usina['longitude'])} (a "
                   f"{_distancia(usina['latitude'], usina['longitude'], lat, lng)} da nova)"
                   if tem_numero else usina["coordinates"].strip())
        resumo = f"SUBSTITUIR a coordenada da usina {nome}"
        linhas = [f"Gravada hoje: {gravada}", f"Nova: {nova}", _mapa(lat, lng)]

    async def executar(db, user, telefone: str) -> str:
        from app.services.integracoes import detalhe_do_upstream
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
            r = await mp.marcar_coordenada(uid, lat, lng, substituir=tem)
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        except httpx.HTTPStatusError as e:
            motivo = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
            if e.response.status_code == 409:
                return (f"⚠️ Enquanto você confirmava, gravaram outra coordenada na usina {nome}: {motivo}. Nada foi "
                        "mudado. Mande a localização de novo para substituir.")
            return f"❌ O meuPlano recusou: {motivo}. Nada foi gravado."
        except httpx.HTTPError:
            return f"⚠️ O meuPlano não respondeu a tempo: a coordenada da usina {nome} PODE ter sido gravada. Confira."
        if _RECEBIDAS.get(telefone, {}).get("em") == loc["em"]:
            del _RECEBIDAS[telefone]
        if r.get("ja_tinha") and not tem:
            return f"✅ {r.get('mensagem') or 'A usina já tinha essa coordenada.'}"
        return f"✅ Coordenada da usina {nome} {'substituída' if tem else 'gravada'} no meuPlano: {_ponto(lat, lng)}."

    return helper.propor(ctx, resumo, PRAZO_S, executar, linhas, parte="bot_meuplano", confirmacao="sim")


FERRAMENTA_LER = {"type": "function", "function": {
    "name": "local_da_usina",
    "description": ("A LOCALIZAÇÃO de uma usina (coordenada, onde fica, como chegar), a gravada no meuPlano. O SISTEMA "
                    "manda à pessoa, ao pé da sua resposta, o link do Google Maps e o do Waze: não escreva os links nem "
                    "os números. Use sempre que pedirem a localização, a coordenada, o mapa ou o caminho de uma usina."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "nome da usina (ou o id das opções)"}},
        "required": ["usina"]}}}


async def local_da_usina(ctx, a: dict) -> dict:
    """A coordenada da usina em Google Maps e Waze (06/11/2026, dono: "toda vez que eu pedir uma loc ele deve me enviar
    formato Google Maps e formato Waze"). Os links são texto do sistema, ao pé da resposta (`ctx.rodape`)."""
    from app.services.vinculos import SemConexao, cliente_meuplano
    if not (a.get("usina") or "").strip():
        return {"erro": "Falta a usina: pergunte qual."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    try:
        usina, candidatas = escolher(await mp.usinas(), a["usina"])
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora."}
    if usina is None:
        return {"erro": f"Usina '{a['usina']}' " + ("é ambígua" if candidatas else "não está entre as dela")
                        + ": pergunte qual é.",
                "opcoes": [_rotulo_da_usina(u) for u in candidatas]}
    nome, lat, lng = usina.get("name"), usina.get("latitude"), usina.get("longitude")
    if lat is None or lng is None:
        return {"erro": f"A usina {nome} não tem coordenada gravada no meuPlano. Para gravar, a pessoa manda a "
                        "localização (📎 → Localização) ou um link do Google Maps e diz a usina."}
    ctx.rodape.append(f"📍 *{nome}*\nGoogle Maps: {_mapa(lat, lng)}\nWaze: {_waze(lat, lng)}")
    return {"usina": nome, "enviado": "O sistema manda os links do Google Maps e do Waze ao pé da sua resposta: "
                                      "não os escreva. Responda numa linha curta."}
