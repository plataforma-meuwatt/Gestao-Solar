"""Localização do WhatsApp gravada como coordenada da usina no meuPlano (pedido do Renan, 29/10/2026), ou reconhecida
como o LUGAR onde a pessoa parou, para a lista de lugares não recomendados (12/11/2026, no fim do arquivo).

A pessoa manda a localização (📎 → Localização). O gateway entrega os números da Meta (`midia`: lat, lng, nome,
endereço); eles ficam guardados aqui na chegada e a IA lê só «[📍 localização recebida…]». Ela pergunta de qual usina
é e chama `gravar_coordenada` com a usina: os números NUNCA passam pela IA (um dígito trocado põe a usina em outra
cidade). O sistema lê a usina no meuPlano com o token DELA: sem coordenada, propõe gravar; com, propõe substituir e
diz a distância. Confirmada com o Sim, vai pela rota do app de campo (`POST /usinas/{id}/coordenada`), que confere a
permissão de lá (`meuacesso.usinas.coordenada`).
"""

import re
import unicodedata
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from time import monotonic
from urllib.parse import unquote
from zoneinfo import ZoneInfo

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


def _m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371000.0 * asin(sqrt(h))


def _metros(m: float) -> str:
    return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.1f} km".replace(".", ",")


def _distancia(lat1: float, lng1: float, lat2: float, lng2: float) -> str:
    return _metros(_m(lat1, lng1, lat2, lng2))


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


# ── o LUGAR da localização e a lista de lugares não recomendados (12/11/2026, o dono: "parei em um posto agora … pela
# localização eu quero que o bot sugira o local … aí eu falo, esse lugar não é recomendado, por isso. Aí fica lá tipo na
# lista negra de locais"). Quem procura é o meuPlano (Google, ou o OSM de reserva); os números do lugar ficam aqui,
# guardados com a localização, e a IA escolhe pelo número da lista: ela nunca escreve coordenada.

PERMISSAO_FROTA = "gestao.veiculos.usar"
#: Até onde a usina conta como "aqui" (a usina é grande e a coordenada gravada é um ponto dela).
USINA_PERTO_M = 2000
_BRT = ZoneInfo("America/Sao_Paulo")


def _data(iso: str | None) -> str:
    """A data em Brasília: o meuPlano manda em UTC (a marcação das 22h não pode sair com o dia seguinte)."""
    try:
        t = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(_BRT).strftime("%d/%m/%Y")


def _marcado(m: dict) -> str:
    quem = ", ".join(x for x in (m.get("por"), _data(m.get("em"))) if x)
    return f"{m.get('motivo')}" + (f" ({quem})" if quem else "")


def _marcas_do_lugar(loc: dict, lugar: dict) -> list[dict]:
    """As marcações da empresa que são DESTE lugar: as que o meuPlano casou com ele, ou o mesmo nome a até 60 m (o lugar
    que a pessoa disse pelo nome, fora da lista do mapa)."""
    ids = set(lugar.get("nao_recomendado_ids") or [])
    return [m for m in loc.get("marcados") or [] if m.get("id") in ids or (
        _sem_acento(m.get("nome")) == _sem_acento(lugar.get("nome")) and m.get("lat") is not None
        and _m(m["lat"], m["lng"], lugar["lat"], lugar["lng"]) <= 60)]


async def _lugares(ctx, loc: dict, *, refazer_parcial: bool = True) -> dict:
    """O que há em volta da localização, perguntado ao meuPlano (fica com ela; o que falhou se pergunta de novo, e o que
    veio em parte também — menos ao marcar, quando o número que a pessoa disse vale contra a lista que ela VIU). A usina
    perto vem à parte: sem a frota (403) ou com o mapa fora, a usina segue sendo sugerida. {"erro": …} se nada.
    `loc` só muda no fim, de uma vez: as ferramentas de uma rodada rodam juntas, e uma não pode ler a lista pela metade
    da outra."""
    from app.services.vinculos import SemConexao, cliente_meuplano
    if "lugares" in loc and not loc.get("mapa_erro") and not (refazer_parcial and loc.get("incompleto")):
        return loc
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano (e o Google) responde
    try:
        usinas = await mp.usinas()
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora."}
    novo = {"usinas": sorted(((u, d) for u in usinas if u.get("latitude") is not None and u.get("longitude") is not None
                              for d in [_m(loc["lat"], loc["lng"], u["latitude"], u["longitude"])]
                              if d <= USINA_PERTO_M), key=lambda x: x[1]),
            "lugares": [], "endereco": None, "marcados": [], "mapa_erro": None, "incompleto": False,
            "marcados_lidos": False}
    try:
        perto = await mp.lugares_perto(loc["lat"], loc["lng"])
    except httpx.HTTPStatusError as e:
        novo["mapa_erro"] = ("o papel desta pessoa no meuPlano não usa a frota, e é por ela que se procura o lugar (o "
                             "gestor da O&M pode liberar)" if e.response.status_code == 403
                             else "o meuPlano não conseguiu procurar o lugar agora")
    except httpx.HTTPError:
        novo["mapa_erro"] = "o meuPlano não respondeu a tempo"
    else:
        if perto.get("fonte") == "erro":
            novo["mapa_erro"] = "o mapa (Google/OpenStreetMap) não respondeu agora"
        elif perto.get("fonte") == "none":
            novo["mapa_erro"] = "a procura de lugares não está ligada no meuPlano"
        novo.update(lugares=perto.get("lugares") or [], endereco=perto.get("endereco"),
                    marcados=perto.get("nao_recomendados_perto") or [], incompleto=bool(perto.get("incompleto")),
                    marcados_lidos=True)
    loc.update(novo)
    return loc


FERRAMENTA_LUGAR = {"type": "function", "function": {
    "name": "lugar_da_localizacao",
    "description": ("QUE LUGAR é a localização que a pessoa mandou («[📍 localização recebida…]»): a usina dela ali perto, "
                    "os estabelecimentos em volta (posto, restaurante, hotel…), do mais perto ao mais longe, e os que a "
                    "equipe já marcou como NÃO RECOMENDADOS ali. Use quando ela manda a localização sem dizer que é a "
                    "coordenada de uma usina."),
    "parameters": {"type": "object", "properties": {}}}}


async def lugar_da_localizacao(ctx, a: dict) -> dict:
    loc = recebida(ctx.telefone)
    if loc is None:
        return {"erro": "Não há localização recebida (ela fica guardada 30 min). Peça que a pessoa mande de novo pelo "
                        "📎 → Localização."}
    loc = await _lugares(ctx, loc)
    if "erro" in loc:
        return loc
    out: dict = {}
    if loc["usinas"]:
        out["usinas_perto"] = [f"{u.get('name')} (a {_metros(d)})" for u, d in loc["usinas"]]
    out["lugares"] = []
    for i, c in enumerate(loc["lugares"], 1):
        marcas = _marcas_do_lugar(loc, c)
        out["lugares"].append(f"{i}. {c.get('nome')}" + "".join(f", {x}" for x in (c.get("tipo"), c.get("endereco")) if x)
                              + f", a {_metros(c.get('distancia_m') or 0)}"
                              + (" — ⚠️ NÃO RECOMENDADO pela equipe: " + "; ".join(_marcado(m) for m in marcas)
                                 if marcas else ""))
    nos_lugares = {m.get("id") for c in loc["lugares"] for m in _marcas_do_lugar(loc, c)}
    ja = [m for m in loc["marcados"] if m.get("id") not in nos_lugares]
    if ja:
        out["nao_recomendados_aqui"] = [f"{m.get('nome')}: {_marcado(m)}, a {_metros(m.get('distancia_m') or 0)}"
                                        for m in ja]
    if loc["mapa_erro"]:
        out["sem_mapa"] = f"Não deu para ver os lugares em volta: {loc['mapa_erro']}. Diga isso e pergunte o nome do lugar."
    elif not loc["lugares"]:
        out["sem_lugar"] = ("O mapa " + ("respondeu só em parte e " if loc["incompleto"] else "")
                            + "não trouxe estabelecimento com nome aqui"
                            + (f"; o endereço é {loc['endereco']}" if loc.get("endereco") else "")
                            + ". Pergunte o nome do lugar.")
    elif loc["incompleto"]:
        out["aviso"] = ("O mapa respondeu só em parte: a lista pode não ter o lugar onde ela está. Diga isso ao "
                        "perguntar.")
    out["como"] = ("Pergunte se ela está no 1º lugar da lista (na usina, se houver usina perto) e, confirmado, o que ela "
                   "quer fazer com ele. Avise o que está NÃO RECOMENDADO. Não escreva coordenada.")
    return out


def _numero(termo: str) -> int | None:
    """O número da lista ("1", "1º", "#2"), ou None se é um nome."""
    t = (termo or "").strip(" .#º°")
    return int(t) if t.isdigit() else None


def _escolher_lugar(lugares: list[dict], termo: str) -> tuple[dict | None, list[dict]]:
    """O lugar pelo número da lista ou pelo nome: (o escolhido, ou None e os candidatos)."""
    t = _sem_acento(termo)
    if (n := _numero(termo)) is not None:
        return (lugares[n - 1], []) if 1 <= n <= len(lugares) else (None, [])
    achados = [c for c in lugares if t and (t in _sem_acento(c.get("nome")) or _sem_acento(c.get("nome")) in t)]
    return (achados[0], achados) if len(achados) == 1 else (None, achados)


FERRAMENTA_MARCAR = {"type": "function", "function": {
    "name": "marcar_lugar_nao_recomendado",
    "description": ("Põe na lista de LUGARES NÃO RECOMENDADOS da equipe o lugar da localização que a pessoa mandou, com o "
                    "motivo nas palavras dela. Passe o número da lista de `lugar_da_localizacao` (ou o nome que ela "
                    "disse, se o lugar não está na lista): os números do lugar vêm do sistema, nunca os escreva. Sem o "
                    "motivo, pergunte por que não é recomendado."),
    "parameters": {"type": "object", "properties": {
        "lugar": {"type": "string", "description": "o número da lista ou o nome do lugar"},
        "motivo": {"type": "string", "description": "por que não é recomendado, nas palavras dela"}},
        "required": ["lugar", "motivo"]}}}


async def marcar_lugar_nao_recomendado(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    loc = recebida(ctx.telefone)
    if loc is None:
        return {"erro": "Não há localização recebida (ela fica guardada 30 min). Peça que a pessoa mande de novo pelo "
                        "📎 → Localização, de onde ela está."}
    termo, motivo = (a.get("lugar") or "").strip(), " ".join((a.get("motivo") or "").split())
    if not motivo:
        return {"erro": "Falta o motivo: pergunte por que o lugar não é recomendado."}
    if not termo:
        return {"erro": "Falta o lugar: pergunte qual é."}
    loc = await _lugares(ctx, loc, refazer_parcial=False)
    if "erro" in loc:
        return loc
    lugar, candidatos = _escolher_lugar(loc["lugares"], termo)
    if lugar is None and (candidatos or _numero(termo) is not None):
        return {"erro": f"O lugar '{termo}' " + ("é ambíguo" if candidatos else "não está na lista") + ": pergunte qual é.",
                "opcoes": [c.get("nome") for c in (candidatos or loc["lugares"])]}
    if lugar is None:                                   # o nome que a pessoa disse, no ponto que ela mandou
        lugar = {"nome": termo, "endereco": loc.get("endereco") or loc.get("rotulo") or None, "lat": loc["lat"],
                 "lng": loc["lng"], "fonte": "manual"}
    corpo = {k: lugar.get(k) for k in ("nome", "endereco", "tipo", "lat", "lng", "place_id", "fonte")}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        if PERMISSAO_FROTA not in (await mp.permissoes()):
            return {"erro": "O papel desta pessoa no meuPlano não usa a frota, e a lista de lugares é dela. Nada foi "
                            "gravado: o gestor da O&M pode liberar."}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi gravado."}
    nome = corpo["nome"]
    # o que já está na lista sobre ESTE lugar vai no resumo: o motivo do colega fica (cada um tem a sua marcação), e o
    # da própria pessoa é trocado pelo novo — o ✅ diz qual era
    linhas = [corpo["endereco"], *(f"Já na lista: {_marcado(m)}" for m in _marcas_do_lugar(loc, lugar)),
              f"Motivo: {motivo}", _mapa(corpo["lat"], corpo["lng"]),
              "Não deu para ver a lista agora: se você já marcou este lugar, o motivo novo substitui o seu."
              if not loc.get("marcados_lidos") else ""]

    async def executar(db, user, telefone: str) -> str:
        from app.services.integracoes import detalhe_do_upstream
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
            r = await mp.marcar_lugar_nao_recomendado(corpo, motivo)
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        except httpx.HTTPStatusError as e:
            motivo_ = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
            return f"❌ O meuPlano recusou: {motivo_}. Nada foi gravado."
        except httpx.HTTPError:
            return f"⚠️ O meuPlano não respondeu a tempo: {nome} PODE ter entrado na lista. Confira."
        if r.get("id") is not None and r.get("lat") is not None:
            # a marcação nova entra na lista guardada (refazer a busca mudaria o número que a pessoa viu)
            loc["marcados"] = [m for m in loc.get("marcados") or [] if m.get("id") != r["id"]] + [
                {**r, "distancia_m": round(_m(loc["lat"], loc["lng"], r["lat"], r["lng"]))}]
            if any(c is lugar for c in loc.get("lugares") or []) and r["id"] not in lugar.get("nao_recomendado_ids", []):
                lugar["nao_recomendado_ids"] = [*lugar.get("nao_recomendado_ids", []), r["id"]]
        if r.get("ja_tinha"):
            return (f"✅ {nome} já estava na sua lista de lugares não recomendados: o seu motivo de antes "
                    f"(«{r.get('motivo_anterior')}») foi trocado por este.")
        return f"✅ {nome} está na lista de lugares não recomendados da equipe."

    return helper.propor(ctx, f"Marcar como NÃO RECOMENDADO: {nome}", PRAZO_S, executar, linhas,
                         parte="bot_meuplano", confirmacao="sim")


FERRAMENTA_LISTA_LUGARES = {"type": "function", "function": {
    "name": "lugares_nao_recomendados",
    "description": ("A lista de LUGARES NÃO RECOMENDADOS da equipe (posto, restaurante, hotel…), com o motivo, quem "
                    "marcou e quando. Use quando perguntarem quais lugares evitar ou o que está na lista."),
    "parameters": {"type": "object", "properties": {
        "busca": {"type": "string", "description": "parte do nome, da cidade ou do motivo, para ver só esses"}}}}}
#: Até onde a lista vai inteira na resposta da ferramenta (o teto dela, em `assistente`, é 14.000 letras).
TETO_LISTA = 12000


async def lugares_nao_recomendados(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        lista = await mp.lugares_nao_recomendados()
    except httpx.HTTPStatusError as e:
        return {"erro": "O papel desta pessoa no meuPlano não vê a frota, e a lista de lugares é dela."
                if e.response.status_code == 403 else "O meuPlano não conseguiu ler a lista agora."}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora."}
    busca = _sem_acento(a.get("busca") or "")
    if busca:
        lista = [m for m in lista if busca in _sem_acento(" ".join(str(m.get(k) or "")
                                                                  for k in ("nome", "endereco", "motivo")))]
    if not lista:
        return {"lugares": [], "nota": f"Nenhum lugar com '{a['busca']}' na lista." if busca else
                "A lista está vazia: ninguém da equipe marcou lugar ainda."}
    # sem o endereço (o do OSM tem 100+ letras); e o que não couber é DITO, com o jeito de ver, nunca cortado calado
    linhas, usado = [], 0
    for m in lista:
        linha = f"{m.get('nome')}: {_marcado(m)}"
        if usado + len(linha) > TETO_LISTA:
            break
        linhas.append(linha)
        usado += len(linha) + 4
    out = {"total": len(lista), "lugares": linhas}
    if len(linhas) < len(lista):
        out["faltam"] = (f"Mais {len(lista) - len(linhas)} lugares não couberam aqui: diga quantos são e peça o nome, a "
                         "cidade ou o motivo para procurar (`busca`).")
    return out
