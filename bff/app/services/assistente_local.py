"""Localização do WhatsApp gravada como coordenada da usina no meuPlano (pedido do Renan, 29/10/2026).

A pessoa manda a localização (📎 → Localização). O gateway entrega os números da Meta (`midia`: lat, lng, nome,
endereço); eles ficam guardados aqui na chegada e a IA lê só «[📍 localização recebida…]». Ela pergunta de qual usina
é e chama `gravar_coordenada` com a usina: os números NUNCA passam pela IA (um dígito trocado põe a usina em outra
cidade). O sistema lê a usina no meuPlano com o token DELA: sem coordenada, propõe gravar; com, propõe substituir e
diz a distância. Confirmada com o Sim, vai pela rota do app de campo (`POST /usinas/{id}/coordenada`), que confere a
permissão de lá (`meuacesso.usinas.coordenada`).
"""

import unicodedata
from math import asin, cos, radians, sin, sqrt
from time import monotonic

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
