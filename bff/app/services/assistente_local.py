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
# guardados com a localização, e a IA escolhe pelo número da lista: ela nunca escreve coordenada. Desde 16/11/2026 a
# marcação também diz o lugar RECOMENDADO (o dono mandou a localização de uma lanchonete e pediu "salve essa lanchonete
# como maravilhosa"; o bot só sabia o não recomendado).

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
    """Uma marcação, curta: "★ 5 · maravilhosa (Renan, 16/11/2026)" (o preço e as notas vão na média do lugar; o
    recomendado pode vir sem comentário, e a de antes de 17/11 sem estrelas)."""
    quem = ", ".join(x for x in (m.get("por"), _data(m.get("em"))) if x)
    texto = " · ".join(x for x in (f"★ {m['estrelas']}" if m.get("estrelas") else "", m.get("motivo") or "") if x)
    return " ".join(x for x in (texto, f"({quem})" if quem else "") if x)


def _decimal_br(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _avaliacoes(marcas: list[dict]) -> str:
    """O que a equipe disse do lugar, de TODAS as marcações dele: « — média da equipe: ★ 4,5 (2 avaliações) · preço
    médio R$ 32,50 · comida 4,5 — 👍 RECOMENDADO pela equipe: … — ⚠️ NÃO RECOMENDADO pela equipe: …» (o dono,
    17/11/2026: "média de preço, as estrelas, notas")."""
    from app.services.assistente_formulario import NOTAS_DO_LUGAR, reais

    def media(valores: list) -> float | None:
        return sum(valores) / len(valores) if valores else None

    estrelas = [m["estrelas"] for m in marcas if m.get("estrelas")]
    precos = [m["preco_medio"] for m in marcas if m.get("preco_medio") is not None]
    preco = media(precos)
    if preco is not None:     # a média com 2 casas ("R$ 35,33"), menos a do litro, que tem 3 ("R$ 6,245")
        preco = round(preco, 3 if any(round(v * 100, 6) != round(v * 100) for v in precos) else 2)
    notas = {k: media([n for m in marcas if (n := (m.get("notas") or {}).get(k))]) for k in NOTAS_DO_LUGAR}
    partes = [f"★ {_decimal_br(media(estrelas))} ({len(estrelas)} {'avaliação' if len(estrelas) == 1 else 'avaliações'})"
              if estrelas else "", f"preço médio {reais(preco)}" if preco is not None else "",
              *(f"{k} {_decimal_br(v)}" for k, v in notas.items() if v is not None)]
    texto = " · ".join(x for x in partes if x)
    return (f" — média da equipe: {texto}" if texto else "") + "".join(
        f" — {rotulo} pela equipe: " + "; ".join(_marcado(m) for m in ms)
        for rec, rotulo in ((True, "👍 RECOMENDADO"), (False, "⚠️ NÃO RECOMENDADO"))
        if (ms := [m for m in marcas if bool(m.get("recomendado")) == rec]))


#: Até onde duas marcações sem o id do mapa e com o mesmo nome são o MESMO lugar (dois "Posto Graal" em estradas
#: diferentes não se misturam).
MESMO_LUGAR_M = 200


def _por_lugar(marcas: list[dict]) -> list[list[dict]]:
    """As marcações agrupadas por LUGAR (cada pessoa tem a sua): o id do mapa, ou o mesmo nome a até MESMO_LUGAR_M."""
    def o_mesmo(m: dict, g: dict) -> bool:
        if m.get("place_id") and g.get("place_id"):
            return m["place_id"] == g["place_id"]
        return (_sem_acento(m.get("nome")) == _sem_acento(g.get("nome")) and None not in (m.get("lat"), g.get("lat"))
                and _m(m["lat"], m["lng"], g["lat"], g["lng"]) <= MESMO_LUGAR_M)

    lugares: list[list[dict]] = []
    for m in marcas:
        g = next((g for g in lugares if o_mesmo(m, g[0])), None)
        lugares.append([m]) if g is None else g.append(m)
    return lugares


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
                    "os estabelecimentos em volta (posto, restaurante, hotel…), do mais perto ao mais longe, e o que a "
                    "equipe já marcou ali (RECOMENDADO ou NÃO RECOMENDADO, com a média de estrelas e de preço). Use "
                    "quando ela manda a localização sem dizer que é a coordenada de uma usina."),
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
                              + f", a {_metros(c.get('distancia_m') or 0)}" + _avaliacoes(marcas))
    nos_lugares = {m.get("id") for c in loc["lugares"] for m in _marcas_do_lugar(loc, c)}
    ja = [m for m in loc["marcados"] if m.get("id") not in nos_lugares]
    if ja:
        out["marcados_aqui"] = [f"{g[0].get('nome')}, a {_metros(min(m.get('distancia_m') or 0 for m in g))}"
                                f"{_avaliacoes(g)}" for g in _por_lugar(ja)]
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
    # o GPS da cidade erra 10 a 20 m: o mais perto nem sempre é onde ela está (São Roque, 16/11: o 1º era uma repartição
    # e ela estava no 2º, a lanchonete)
    out["como"] = ("Pergunte em qual lugar ela está: o 1º da lista (a usina, se houver usina perto) e, na mesma linha, os "
                   "outros nomes da lista. Confirmado, se ela ainda não disse, pergunte o que quer com ele. Avise o que a "
                   "equipe já marcou ali. Não escreva coordenada.")
    return out


_ORDINAIS = {"primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3, "quarto": 4,
             "quarta": 4, "quinto": 5, "quinta": 5}


def _numero(termo: str) -> int | None:
    """O número da lista ("1", "1º", "#2", "o 2", "nº 2", "o segundo"), ou None se é um nome."""
    t = _sem_acento(termo).strip(" .#°")
    t = re.sub(r"^(?:o|a|no|n\.|numero|lugar)\s+", "", t).strip(" .#°")
    if m := re.fullmatch(r"(\d{1,2})\s*[oa]?", t):
        return int(m[1])
    return _ORDINAIS.get(t)


#: O TIPO do lugar não o escolhe na lista ("o posto", "essa lanchonete"): só uma palavra do NOME.
_TIPOS_DE_LUGAR = {"auto", "posto", "lanchonete", "lanches", "restaurante", "churrascaria", "pizzaria", "hamburgueria",
                   "padaria", "mercado", "supermercado", "hotel", "pousada", "loja", "oficina", "borracharia", "lugar",
                   "local", "esse", "essa", "este", "esta", "aqui", "como", "isso", "bar", "cafe", "ponto", "parada"}
#: as palavras de ligação: com elas e os tipos, o termo não diz QUAL lugar é ("essa lanchonete aqui")
_LIGACOES = {"o", "a", "os", "as", "de", "da", "do", "das", "dos", "na", "no", "em", "um", "uma", "ali", "la", "ai"}


def _palavras(t: str | None) -> set[str]:
    return {p for p in re.findall(r"\w+", _sem_acento(t)) if len(p) >= 4}


def _so_tipo(termo: str) -> bool:
    """O termo só diz o tipo ("essa lanchonete", "o posto aqui"): não é o nome de lugar nenhum."""
    return all(p in _TIPOS_DE_LUGAR or p in _LIGACOES for p in re.findall(r"\w+", _sem_acento(termo)))


def _escolher_lugar(lugares: list[dict], termo: str) -> tuple[dict | None, list[dict]]:
    """O lugar pelo número da lista ou pelo nome: (o escolhido, ou None e os candidatos). Sem o nome inteiro, vale uma
    palavra dele ("maravilhosa browdog" → «Browdog - Hamburguer Defumado», São Roque 16/11), nunca o tipo nem uma
    palavra do ENDEREÇO dos lugares da lista ("a lanchonete de São Roque" escolhia a «PAV são roque», uma repartição)."""
    t = _sem_acento(termo)
    if (n := _numero(termo)) is not None:
        return (lugares[n - 1], []) if 1 <= n <= len(lugares) else (None, [])
    if t and _so_tipo(termo):
        # só o tipo ("a padaria", "o posto"): vale o TIPO que o mapa dá ao lugar, se um só da lista é desse tipo — nunca
        # um pedaço do nome ("bar" não é a «JF Barbearia», "o ponto" não é a «PAV são roque, Ponto SP»)
        tipos = set(re.findall(r"\w+", t)) & _TIPOS_DE_LUGAR
        achados = [c for c in lugares if tipos & set(re.findall(r"\w+", _sem_acento(c.get("tipo"))))]
        return (achados[0], achados) if len(achados) == 1 else (None, achados)
    # o termo como PALAVRAS do nome ("bar" não escolhe a «JF Barbearia»)
    achados = [] if not t else [
        c for c in lugares if re.search(rf"\b{re.escape(t)}\b", _sem_acento(c.get("nome"))) or (
            _sem_acento(c.get("nome")) and _sem_acento(c.get("nome")) in t)]
    if not achados:
        do_endereco = set().union(*(_palavras(c.get("endereco")) for c in lugares))
        palavras = _palavras(termo) - _TIPOS_DE_LUGAR - do_endereco
        achados = [c for c in lugares if palavras & _palavras(c.get("nome"))]
    return (achados[0], achados) if len(achados) == 1 else (None, achados)


FERRAMENTA_AVALIAR = {"type": "function", "function": {
    "name": "avaliar_lugar",
    "description": ("SALVA ou AVALIA, na lista de lugares da equipe, o LUGAR onde a pessoa está (posto, restaurante, "
                    "hotel…), pela localização que ela mandou: quando ela pede para salvar, guardar ou avaliar o lugar, "
                    "diz que é bom («salve essa lanchonete», «ótimo, recomendo») ou que não é recomendado. A localização "
                    "de uma USINA não é isto: é `gravar_coordenada`. O sistema manda o formulário de avaliação (recomenda ou não, "
                    "estrelas, preço médio, notas, comentário), que grava quando ela envia: não pergunte nada disso. "
                    "Passe o número da lista de `lugar_da_localizacao` ou o NOME do lugar que ela disse (os números do "
                    "lugar vêm do sistema, nunca os escreva) e só o que ela disse: `recomenda`, `estrelas`, `preco`, "
                    "`comentario` (o motivo, se não recomenda)."),
    "parameters": {"type": "object", "properties": {
        "lugar": {"type": "string", "description": "o número da lista ou o nome do lugar"},
        "recomenda": {"type": "boolean", "description": "true se ela disse que é bom; false se disse que não recomenda"},
        "estrelas": {"type": "integer", "description": "de 1 a 5, se ela disse"},
        "preco": {"type": "number", "description": "o preço médio em R$, se ela disse"},
        "comentario": {"type": "string", "description": "o que ela disse do lugar (o motivo, se não recomenda)"},
        "fora_da_lista": {"type": "boolean", "description": ("true só quando ela confirmou que o lugar NÃO é nenhum "
                                                             "da lista e disse o nome dele")},
        "sem_formulario": {"type": "boolean", "description": (
            "true SÓ quando ela diz que o formulário não abriu, pede para salvar sem ele, ou responde por texto o "
            "formulário que JÁ recebeu: aí vai o resumo com o Sim, com o que ela disse. Estrelas e preço ditos no "
            "pedido vão nos campos, e o formulário vem preenchido")}},
        "required": ["lugar"]}}}
SEM_FORMULARIO = ("Não consegui abrir o formulário de avaliação agora. Diga se recomenda o lugar (e, se não, por quê), "
                  "que eu preparo para salvar com o Sim.")
SEM_FORMULARIO_COM_SIM = "Não consegui abrir o formulário de avaliação agora. Para salvar o que você disse, toque em Sim."


def _rotulo(recomendado: bool) -> str:
    return "recomendado" if recomendado else "não recomendado"


def _preco_br(v: float | None) -> str:
    """O preço como o formulário mostra ("35,50"; o litro, "6,299")."""
    from app.services.assistente_formulario import reais
    return "" if v is None else reais(v).removeprefix("R$ ").replace(".", "")


async def _gravar(db, user, corpo: dict, av: dict, loc: dict | None, lugar: dict | None,
                  campos: tuple = ("estrelas", "preco_medio", "notas")) -> tuple[str, dict | None]:
    """Grava a marcação da pessoa no meuPlano: (o que dizer, o que ficou gravado — None se não gravou). `campos`: os da
    avaliação que VÃO, vazios inclusive (o formulário manda os três); o que não vai, lá fica como estava."""
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuplano
    nome, recomendado = corpo["nome"], bool(av.get("recomendado"))
    avaliacao = {k: av.get(k) for k in campos}
    try:
        mp = cliente_meuplano(db, user.id, so_proprio=True)
        db.commit()
        r = await mp.marcar_lugar(corpo, av.get("motivo") or "", recomendado, **avaliacao)
    except SemConexao as e:
        return f"❌ Não executado: {e}", None
    except httpx.HTTPStatusError as e:
        motivo_ = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
        return f"❌ O meuPlano recusou: {motivo_}. Nada foi gravado.", None
    except httpx.HTTPError:
        return f"⚠️ O meuPlano não respondeu a tempo: {nome} PODE ter entrado na lista. Confira.", None
    da_lista = lugar is not None and loc is not None and any(c is lugar for c in loc.get("lugares") or [])
    if loc is not None and r.get("id") is not None and r.get("lat") is not None and (
            da_lista or _m(loc["lat"], loc["lng"], r["lat"], r["lng"]) <= MESMO_LUGAR_M):
        # a marcação nova entra na lista guardada (refazer a busca mudaria o número que a pessoa viu) — só a DESTA
        # localização: o formulário vale 12 h, e o lugar avaliado de longe não é "aqui" (4ª avaliação, 17/11)
        loc["marcados"] = [m for m in loc.get("marcados") or [] if m.get("id") != r["id"]] + [
            {**r, "distancia_m": round(_m(loc["lat"], loc["lng"], r["lat"], r["lng"]))}]
        if da_lista and r["id"] not in lugar.get("nao_recomendado_ids", []):
            lugar["nao_recomendado_ids"] = [*lugar.get("nao_recomendado_ids", []), r["id"]]
    if not r.get("ja_tinha"):
        return f"✅ {nome} está na lista de lugares {'recomendados' if recomendado else 'não recomendados'} da equipe.", r
    era = r.get("recomendado_anterior")
    if era is not None and bool(era) != recomendado:
        return f"✅ {nome}: a sua marcação mudou de {_rotulo(bool(era))} para {_rotulo(recomendado)}.", r
    return f"✅ {nome}: a sua avaliação foi atualizada.", r


async def avaliar_lugar(ctx, a: dict) -> dict:
    from app.services.assistente_formulario import NOTAS_DO_LUGAR
    from app.services.vinculos import SemConexao, cliente_meuplano
    loc = recebida(ctx.telefone)
    if loc is None:
        return {"erro": "Não há localização recebida (ela fica guardada 30 min). Peça que a pessoa mande de novo pelo "
                        "📎 → Localização, de onde ela está."}
    termo = (a.get("lugar") or "").strip()
    if not termo:
        return {"erro": "Falta o lugar: pergunte qual é."}
    loc = await _lugares(ctx, loc, refazer_parcial=False)
    if "erro" in loc:
        return loc
    lugar, candidatos = _escolher_lugar(loc["lugares"], termo)
    if lugar is None and not candidatos and _numero(termo) is None:
        # o lugar que a equipe já marcou aqui perto, mesmo fora da lista do mapa ("a borracharia do Zé"): uma marcação
        # por lugar (cada pessoa tem a sua, e duas do mesmo lugar não são "dois lugares")
        unicos = list({m.get("place_id") or _sem_acento(m.get("nome")): m for m in loc.get("marcados") or []}.values())
        marcado, _ = _escolher_lugar(unicos, termo)
        if marcado is not None:
            lugar = {k: marcado.get(k) for k in ("nome", "endereco", "tipo", "lat", "lng", "place_id", "fonte")}
    if lugar is None:
        nomes = [c.get("nome") for c in (candidatos or loc["lugares"])]
        if candidatos:
            return {"erro": f"'{termo}' pode ser mais de um lugar: pergunte qual é.", "opcoes": nomes}
        if _numero(termo) is not None:
            return {"erro": f"Não há o número {_numero(termo)} na lista: pergunte qual é.", "opcoes": nomes}
        if _so_tipo(termo):
            return {"erro": f"'{termo}' não diz qual lugar é: pergunte em qual da lista ela está, ou o nome dele.",
                    "opcoes": nomes}
        if loc["lugares"] and not a.get("fora_da_lista"):
            # (17/11/2026) o nome que não casa com a lista do mapa virava um lugar novo com as palavras dela
            return {"erro": f"'{termo}' não está na lista do mapa: pergunte se é um destes. Se ela disser que é outro "
                            "lugar, chame de novo com fora_da_lista=true e o nome que ela disse.", "opcoes": nomes}
        lugar = {"nome": termo, "endereco": loc.get("endereco") or loc.get("rotulo") or None, "lat": loc["lat"],
                 "lng": loc["lng"], "fonte": "manual"}
    corpo = {k: lugar.get(k) for k in ("nome", "endereco", "tipo", "lat", "lng", "place_id", "fonte")}
    nome = corpo["nome"]
    if ctx.avaliacao is not None and ctx.avaliacao["nome"] != nome:
        return {"erro": f"Um lugar por vez: o formulário de {ctx.avaliacao['nome']} já vai nesta resposta. Diga que este "
                        "fica para depois."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        eu = await mp.eu()
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi gravado."}
    if PERMISSAO_FROTA not in set(eu.get("permissions") or []):
        return {"erro": "O papel desta pessoa no meuPlano não usa a frota, e a lista de lugares é dela. Nada foi "
                        "gravado: o gestor da O&M pode liberar."}
    # a avaliação de ANTES desta pessoa neste lugar vem no formulário (reavaliar não começa do zero nem apaga)
    minha = next((m for m in _marcas_do_lugar(loc, lugar)
                  if m.get("por_id") is not None and str(m["por_id"]) == str(eu.get("user_id"))), None) or {}
    antes = bool(minha["recomendado"]) if "recomendado" in minha else None
    texto_antes = minha.get("motivo") or ""
    disse_recomenda = a["recomenda"] if isinstance(a.get("recomenda"), bool) else None
    recomenda = disse_recomenda if disse_recomenda is not None else antes
    mudou = disse_recomenda is not None and antes is not None and disse_recomenda != antes
    disse = " ".join((a.get("comentario") or "").split())
    estrelas = a.get("estrelas") if isinstance(a.get("estrelas"), int) and 1 <= a["estrelas"] <= 5 else None
    preco = a.get("preco") if isinstance(a.get("preco"), (int, float)) and 0 <= a["preco"] <= 100000 else None
    av = {
        "nome": nome, "lugar": corpo, "ref": lugar, "recomenda": "" if recomenda is None else ("sim" if recomenda else "nao"),
        # o texto de antes só volta na caixa da MESMA opinião: o "maravilhosa" de quem recomendava não vira o motivo
        # obrigatório de quem agora não recomenda (a avaliação independente de 17/11); e nem as estrelas e notas
        "comentario": disse if disse and disse_recomenda is not False else (
            texto_antes if antes is True and disse_recomenda is not False else ""),
        "motivo": disse if disse and disse_recomenda is False else (
            texto_antes if antes is False and disse_recomenda is not True else ""),
        "estrelas": estrelas or (None if mudou else minha.get("estrelas")),
        "preco": _preco_br(preco if preco is not None else minha.get("preco_medio")),
        "notas": {} if mudou else {k: str(n) for k, n in (minha.get("notas") or {}).items() if k in NOTAS_DO_LUGAR},
        # o que ela DISSE agora, para o Sim de reserva: lá, o que não vier fica como estava (o comentário de antes,
        # se a opinião é a mesma, vai junto: senão o Sim o apagaria)
        "dito": {"recomendado": disse_recomenda, "estrelas": estrelas, "preco_medio": preco, "notas": None,
                 "motivo": disse or (texto_antes if antes is not None and antes == disse_recomenda else ""),
                 # quem muda de opinião não leva as estrelas e as notas da outra (a 3ª avaliação independente de 17/11)
                 "limpar": ("estrelas", "notas") if mudou else ()},
        "antes": antes}
    if a.get("sem_formulario"):
        return reserva(ctx, av) or {"erro": "Para salvar sem o formulário, falta ela dizer se recomenda o lugar (e, se "
                                            "não, o motivo): pergunte."}
    ctx.avaliacao = av
    return {"lugar": nome, "formulario": "O sistema manda o formulário de avaliação logo depois da sua resposta: diga "
            "em UMA linha curta que é para tocar em Avaliar. Não pergunte nada: o formulário pergunta."}


def reserva(ctx, av: dict) -> dict | None:
    """O Sim com o que a pessoa DISSE, sem o formulário (ele não abriu, ou ela pediu sem): o resultado de
    `helper.propor`, ou None se ela não disse se recomenda (ou, no não, o motivo) e não há o que propor."""
    dito = dict(av["dito"])
    if dito["recomendado"] is None and av.get("antes") is not None and (
            dito["estrelas"] or dito["preco_medio"] is not None or dito["motivo"]):
        # "não abriu, 4 estrelas": disse algo novo e não repetiu a opinião — vale a dela de antes
        dito["recomendado"] = av["antes"]
    if dito["recomendado"] is None or (not dito["recomendado"] and not dito["motivo"]):
        return None
    from app.services.assistente_formulario import reais
    rec, corpo = dito["recomendado"], av["lugar"]
    campos = tuple(dict.fromkeys([*(k for k in ("estrelas", "preco_medio") if dito[k] is not None),
                                  *dito.get("limpar", ())]))
    linhas = [corpo["endereco"], f"★ {dito['estrelas']}" if dito["estrelas"] else "",
              ("As notas de antes saem (a opinião mudou)" if dito["estrelas"] else
               "As estrelas e as notas de antes saem (a opinião mudou)") if dito.get("limpar") else "",
              f"Preço médio: {reais(dito['preco_medio'])}" if dito["preco_medio"] is not None else "",
              (f"Comentário: {dito['motivo']}" if rec else f"Motivo: {dito['motivo']}") if dito["motivo"] else "",
              _mapa(corpo["lat"], corpo["lng"])]

    async def executar(db, user, telefone: str) -> str:
        from app.services.assistente_formulario import em_palavras
        feito, salvo = await _gravar(db, user, corpo, dito, recebida(telefone), av.get("ref"), campos)
        return f"{feito}\n{em_palavras(salvo)}" if salvo is not None else feito

    return helper.propor(ctx, f"Marcar como {_rotulo(rec).upper()}: {av['nome']}", PRAZO_S, executar, linhas,
                         parte="bot_meuplano", confirmacao="sim")


async def pelo_formulario(ctx, av: dict) -> str:
    """O formulário de avaliação respondido: grava no meuPlano sem passar pela IA (enviar é a confirmação, como o Sim).
    A confirmação diz o que FICOU gravado; se nada gravou, o formulário volta preenchido com o que ela mandou."""
    from app.services.assistente_formulario import em_palavras
    if "bot_meuplano" not in ctx.user.bot_ativo:
        return "❌ A parte do meuPlano no seu bot está desligada: nada foi gravado. O gestor da O&M pode religar."
    feito, salvo = await _gravar(ctx.db, ctx.user, av["lugar"], av, recebida(ctx.telefone), av.get("ref"))
    if salvo is not None:
        return f"{feito}\n{em_palavras(salvo)}"
    if feito.startswith("❌"):
        rec = bool(av.get("recomendado"))
        ctx.avaliacao = {
            "nome": av["nome"], "lugar": av["lugar"], "ref": av.get("ref"), "recomenda": "sim" if rec else "nao",
            "comentario": (av.get("motivo") or "") if rec else "", "motivo": "" if rec else (av.get("motivo") or ""),
            "estrelas": av.get("estrelas"), "preco": _preco_br(av.get("preco_medio")),
            "notas": {k: str(n) for k, n in (av.get("notas") or {}).items()},
            "dito": {"recomendado": av.get("recomendado"), "motivo": av.get("motivo") or "",
                     "estrelas": av.get("estrelas"), "preco_medio": av.get("preco_medio")}}
        return f"{feito} O formulário vai de novo, preenchido com o que você mandou."
    return feito


FERRAMENTA_LISTA_LUGARES = {"type": "function", "function": {
    "name": "lugares_da_equipe",
    "description": ("A lista de lugares que a equipe marcou (posto, restaurante, hotel…): por lugar, a média da equipe "
                    "(estrelas, preço, notas) de TODAS as avaliações, e quem recomenda e quem não (com o comentário ou "
                    "o motivo). Use quando perguntarem onde parar ou comer, quais lugares evitar ou o que está na lista."),
    "parameters": {"type": "object", "properties": {
        "quais": {"type": "string", "enum": ["recomendados", "nao_recomendados"],
                  "description": "só os lugares que alguém recomenda (ou que alguém não recomenda); sem isto, todos"},
        "busca": {"type": "string", "description": "parte do nome, da cidade ou do motivo, para ver só esses"}}}}}
#: Até onde a lista vai inteira na resposta da ferramenta (o teto dela, em `assistente`, é 14.000 letras).
TETO_LISTA = 12000


async def lugares_da_equipe(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        lista = await mp.lugares_marcados()
    except httpx.HTTPStatusError as e:
        return {"erro": "O papel desta pessoa no meuPlano não vê a frota, e a lista de lugares é dela."
                if e.response.status_code == 403 else "O meuPlano não conseguiu ler a lista agora."}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora."}

    # um LUGAR por linha, com TODAS as marcações dele: a média e o "quem não recomenda" nunca saem pela metade
    lugares = _por_lugar(lista)
    if a.get("quais") in ("recomendados", "nao_recomendados"):
        quer = a["quais"] == "recomendados"
        lugares = [g for g in lugares if any(bool(m.get("recomendado")) == quer for m in g)]
    busca = _sem_acento(a.get("busca") or "")
    if busca:
        lugares = [g for g in lugares if any(busca in _sem_acento(" ".join(str(m.get(k) or "") for k in (
            "nome", "endereco", "motivo"))) for m in g)]
    if not lugares:
        return {"lugares": [], "nota": f"Nenhum lugar com '{a['busca']}' na lista." if busca else
                "Nenhum lugar assim na lista." if a.get("quais") else
                "A lista está vazia: ninguém da equipe marcou lugar ainda."}
    # o endereço curto (o do Google) diz a cidade; o do OSM tem 100+ letras e fica de fora. O que não couber é DITO,
    # com o jeito de ver, nunca cortado calado
    linhas, usado = [], 0
    for g in lugares:
        end = next((m["endereco"] for m in g if m.get("endereco") and len(m["endereco"]) <= 70), None)
        linha = f"{g[0].get('nome')}" + (f" ({end})" if end else "") + _avaliacoes(g)
        if usado + len(linha) > TETO_LISTA:
            break
        linhas.append(linha)
        usado += len(linha) + 4
    out = {"total": len(lugares), "lugares": linhas}
    if len(linhas) < len(lugares):
        out["faltam"] = (f"Mais {len(lugares) - len(linhas)} lugares não couberam aqui: diga quantos são e peça o nome, "
                         "a cidade ou o motivo para procurar (`busca`).")
    return out
