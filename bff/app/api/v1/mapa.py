"""O MAPA ÚNICO da usina — gestao.solar/mapa/<usina> (o dono, 18/11/2026: "o mapa pode ser tipo gestao.solar/mapa/usina
… todos usam o mesmo … o meuGuarda só consome o mapa"; escolheu: página no GS, a O&M edita, o dono da usina só vê).

De onde vem cada coisa — nada fica guardado aqui:
- o voo (ortomosaico) e a posição de cada equipamento moram no mapa do meuWatt; o meuPlano o lê e liga cada objeto ao
  equipamento da árvore (`GET /usinas/{id}/mapa` de lá, a ligação pela origem `meuplano:node:<id>` ou pelo nome). Aqui a
  leitura é a desse mapa, com o token da PESSOA, senão o da empresa que a atende (`vinculos.token_do_cliente`, a régua
  do portal) — nunca uma credencial de plataforma;
- marcar e mover é da O&M (gerente e técnico), com o token PESSOAL do meuPlano de quem edita: a permissão dele lá
  (`meuacesso.usinas.coordenada`) decide, e o histórico diz quem foi. A posição vai ao mapa do meuWatt pela rota do
  meuPlano (`POST /usinas/{id}/mapa/ponto`), sem segunda cópia em lugar nenhum.

Quem abre: as três sessões do GS valem (a do portal, a do gerente e a do técnico). O dono vê as usinas dele; a O&M, as da
empresa dela.

As CAMADAS (o dono, 18/11/2026: "quero que todos possam editar, todos é mw, mp e mg … cadastrar as strings, inversores,
trafos, etc tudo no mapa … um sistema de filtro realmente top"): cada camada se edita com a permissão do produto dela —
a do monitoramento (string, inversor, trafo, mesa…) grava no mapa do meuWatt com o token do meuWatt DA PESSOA (o papel
de operação na usina, lá, decide); a da manutenção (o equipamento da árvore, câmera incluída) pelo meuPlano, como acima.
A COR de cada objeto vem do estado que o meuWatt calcula (`/plants/{slug}/mapa/estado`); sem essa leitura, nenhum
objeto é pintado de "ok" (regra "nunca enganar").
"""

from __future__ import annotations

import math

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.core.db import get_db
from app.core.security import _bearer, gestor_empresa_atual, tecnico_atual, usuario_atual
from app.api.v1.manutencao import MANUTENCAO, MONITORAMENTO
from app.clients.meuplano import ORIGEM_NO_MAPA
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import empresas, integracoes

router = APIRouter(prefix="/api/v1/mapa", tags=["mapa"])

_O_E_M = (Perfil.GESTOR_EMPRESA, Perfil.TECNICO)


def quem_abre(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    """A sessão do portal (dono), a do gerente ou a do técnico: cada guarda confere a sua, e a primeira que aceita vale."""
    for guarda in (usuario_atual, gestor_empresa_atual, tecnico_atual):
        try:
            return guarda(cred, db)
        except HTTPException:
            continue
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")


def usinas_do_mapa(db: Session, user: User) -> list[PlantLink]:
    """O dono: as dele (a régua do portal). A O&M: as da empresa — o técnico também, que trabalha nelas."""
    if user.perfil in _O_E_M:
        minhas = empresas.empresas_da_conta(db, user)
        return list(db.scalars(select(PlantLink).where(PlantLink.empresa_id.in_(minhas or [-1]), PlantLink.ativo)
                               .order_by(PlantLink.nome)).all())
    return usinas_do_usuario(db, user)


def _usina(db: Session, user: User, usina_id: int) -> PlantLink:
    link = next((u for u in usinas_do_mapa(db, user) if u.id == usina_id), None)
    if link is None:                                       # 404 e não 403: não confirma que a usina existe
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
    return link


def _edita(user: User, produto: Produto = Produto.MEUPLANO) -> str | None:
    """Por que esta pessoa NÃO edita a camada deste produto (None = edita; a permissão de lá decide o resto)."""
    if user.perfil not in _O_E_M:
        return "O mapa é editado pela equipe de O&M."
    if not user.tem_token(produto):
        servico = MANUTENCAO if produto == Produto.MEUPLANO else MONITORAMENTO
        return f"Para editar esta camada, a sua conta precisa do token do {servico} (o gerente cola em Usuários)."
    return None


async def _estado(db: Session, user: User, slug: str | None) -> tuple[dict | None, str | None, bool]:
    """O estado de cada objeto, lido no monitoramento (o token da pessoa, senão o da empresa: a régua do portal).
    (estado, aviso, a rota existe): sem leitura, `None` e o porquê — a tela não pinta nada de "ok". A rota ausente
    (404) também diz que o monitoramento ainda não move nem liga desenho (vieram juntos)."""
    if not slug:
        return None, None, False
    from app.services.vinculos import SemConexao, cliente_meuwatt
    try:
        mw = cliente_meuwatt(db, user.id)
    except SemConexao:
        return None, "O estado dos equipamentos não pôde ser lido: falta a conexão com o monitoramento.", False
    db.commit()
    try:
        bruto = await mw.mapa_estado(slug)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, "O estado dos equipamentos (alarme, string com problema) ainda não está disponível.", False
        return None, "O estado dos equipamentos não pôde ser lido agora.", True
    except httpx.HTTPError:
        return None, "O estado dos equipamentos não pôde ser lido agora.", True
    if not isinstance(bruto, dict) or not isinstance(bruto.get("objetos"), list):
        return None, "O estado dos equipamentos veio num formato inesperado.", True
    campos = ("estado", "motivo", "desde", "leitura_em", "equipamento", "conhecido")
    por_objeto = {int(o["objeto_id"]): {k: o.get(k) for k in campos}
                  for o in bruto["objetos"] if isinstance(o, dict) and str(o.get("objeto_id", "")).isdigit()}
    # `lido_em` é a hora do CÁLCULO; `dados_de`/`leitura_em`, a do dado — a tela mostra a do dado
    return ({"lido_em": bruto.get("lido_em"), "dados_de": bruto.get("dados_de"), "dia": bruto.get("dia"),
             "objetos": por_objeto}, None, True)


def _do_upstream(exc: httpx.HTTPError, quem: str) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        frase = integracoes.detalhe_do_upstream(exc.response)
        codigo = exc.response.status_code
        if codigo == 422:
            codigo = 400
        return HTTPException(codigo if codigo in (400, 403, 404, 409, 424) else status.HTTP_502_BAD_GATEWAY,
                             frase or f"O {quem} respondeu {codigo}.")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"O {quem} não respondeu agora.")


class UsinaDoMapa(BaseModel):
    id: int
    nome: str
    mp_usina_id: int | None = None
    mw_slug: str | None = None


@router.get("/usinas", response_model=list[UsinaDoMapa])
def listar(db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> list[UsinaDoMapa]:
    """As usinas que esta pessoa abre no mapa — e a ponte para o endereço vindo de outro produto
    (`/mapa?meuplano=<id>` do meuPlano, `?meuwatt=<slug>` do meuWatt)."""
    return [UsinaDoMapa(id=u.id, nome=u.nome, mp_usina_id=u.mp_usina_id, mw_slug=u.mw_plant_slug)
            for u in usinas_do_mapa(db, user)]


@router.get("/usinas/{usina_id}")
async def mapa_da_usina(usina_id: int, db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> dict:
    """O mapa: o pino e o contorno da usina, o voo, cada equipamento marcado (com o nó do meuPlano que ele é) e se esta
    pessoa pode editar. O meuWatt fora ou recusando vira `aviso` — nunca um mapa vazio que parece certo."""
    link = _usina(db, user, usina_id)
    por_que = _edita(user)
    mon = _edita(user, Produto.MEUWATT)
    base = {"usina": {"id": link.id, "nome": link.nome}, "pode_editar": por_que is None, "por_que_nao_edita": por_que,
            # cada camada com a permissão do produto dela (None = edita); o monitoramento só com o mapa LIDO (abaixo)
            "edicao": {"monitoramento": mon or "O mapa desta usina não foi lido agora: desenhar fica para depois.",
                       "manutencao": por_que},
            "mapa": None, "aviso": None, "estado": None, "estado_aviso": None, "mapa_completo": False}
    if link.mp_usina_id is None:
        return {**base, "aviso": f"Esta usina ainda não está ligada ao {MANUTENCAO}: o mapa dela ainda não existe."}
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        cliente = cliente_meuplano(db, user.id)
    except SemConexao as exc:
        return {**base, "aviso": str(exc)}
    db.commit()                                            # solta a conexão enquanto o meuPlano responde
    try:
        mapa = await cliente.mapa_da_usina(link.mp_usina_id)
    except httpx.HTTPError as exc:
        return {**base, "aviso": _do_upstream(exc, MANUTENCAO).detail}
    aviso = mapa.get("aviso")
    if aviso and user.perfil not in _O_E_M:                # o motivo de lá cita os produtos: ao dono, o serviço
        aviso = "O mapa desta usina não pôde ser lido agora: o voo e as marcações voltam quando o serviço responder."
    # nada a pintar sem objeto: o estado nem é pedido (e o "completo" só serve a quem já tem objeto para mover/ligar)
    estado, estado_aviso, completo = (await _estado(db, user, mapa.get("slug")) if mapa.get("objetos")
                                      else (None, None, False))
    if mon is None:
        # a leitura vem do mapa que a manutenção liga; a escrita, da usina daqui: só com os dois iguais (e lidos), senão
        # o desenho sumiria da tela
        slug = mapa.get("slug")
        base["edicao"]["monitoramento"] = (
            # o mapa veio com aviso (o monitoramento recusou ou caiu): os objetos não foram lidos — o desenho sumiria
            "O mapa desta usina não foi lido agora: desenhar fica para depois." if mapa.get("aviso") else
            None if slug and slug == link.mw_plant_slug else
            "O mapa desta usina ainda não está ligado ao monitoramento: desenhar fica para depois de ligar."
            if not slug or not link.mw_plant_slug else
            "Esta usina está ligada a outra usina do monitoramento do que o mapa que se lê: fale com a plataforma antes"
            " de desenhar.")
    return {**base, "mapa": mapa, "aviso": aviso, "estado": estado, "estado_aviso": estado_aviso, "mapa_completo": completo}


def _meuplano_da_pessoa(db: Session, user: User):
    from app.services.vinculos import SemConexao, cliente_meuplano
    if (motivo := _edita(user)) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, motivo)
    try:
        return cliente_meuplano(db, user.id, so_proprio=True)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/usinas/{usina_id}/equipamentos")
async def equipamentos(usina_id: int, nome: str, db: Session = Depends(get_db),
                       user: User = Depends(quem_abre)) -> dict:
    """O equipamento pelo nome (o "Câmera 01" acha com "câmera 1"), para marcar no mapa — como a pessoa (O&M)."""
    link = _usina(db, user, usina_id)
    if link.mp_usina_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina não está ligada ao {MANUTENCAO}.")
    if not (nome or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Diga o nome do equipamento.")
    mp = _meuplano_da_pessoa(db, user)
    db.commit()
    try:
        return await mp.equipamento_pelo_nome(link.mp_usina_id, nome.strip()[:120])
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MANUTENCAO) from exc


class PontoIn(BaseModel):
    node_id: int
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@router.post("/usinas/{usina_id}/ponto")
async def marcar(usina_id: int, body: PontoIn, db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> dict:
    """Marca (ou move) o equipamento no mapa — como a pessoa (O&M), pela rota do meuPlano; a posição vai ao mapa do
    meuWatt, a única."""
    link = _usina(db, user, usina_id)
    if link.mp_usina_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina não está ligada ao {MANUTENCAO}.")
    mp = _meuplano_da_pessoa(db, user)
    db.commit()
    try:
        return await mp.marcar_no_mapa(link.mp_usina_id, body.node_id, body.lat, body.lng)
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MANUTENCAO) from exc


# ─────────────────────────────── a camada do MONITORAMENTO (string, inversor, trafo, mesa…), 18/11/2026

#: o que se desenha nesta camada (os tipos do mapa de lá; a câmera e o equipamento da árvore vão pela manutenção)
TIPOS_DESENHO = ("string", "inversor", "caixa_juncao", "transformador", "subestacao", "estacao", "mesa",
                 "tracker_fileira", "outro")


#: a que equipamento cada tipo pode se ligar (a régua do monitoramento, `plant_map/schemas.py` de lá)
LIGA = {"slot_id": {"string", "mesa", "inversor"}, "string_number": {"string", "mesa"},
        "transformer_id": {"transformador", "subestacao"}}


class _Ligacao(BaseModel):
    """A vaga do inversor (`slot_id`), a entrada dele (`string_number`) e o trafo — o que dá cor ao desenho."""
    slot_id: int | None = Field(None, ge=1)
    string_number: int | None = Field(None, ge=1, le=64)
    transformer_id: int | None = Field(None, ge=1)


class ObjetoNovoIn(_Ligacao):
    tipo: str
    nome: str | None = Field(None, max_length=80)
    geometria: dict


class ObjetoPatchIn(_Ligacao):
    tipo: str | None = None
    nome: str | None = Field(None, max_length=80)
    geometria: dict | None = None


def _vertice(p) -> list[float]:
    if (not isinstance(p, list) or len(p) != 2
            or not all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in p)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Desenho inválido: cada ponto é [longitude, latitude].")
    return [float(p[0]), float(p[1])]


def _geometria(g: dict | None) -> dict | None:
    """Ponto, linha ou área em [lon, lat], cada vértice refeito como dois números (nada além vai ao banco); os limites
    (quantos vértices, dentro do mundo) o monitoramento confere."""
    if g is None:
        return None
    tipo, c = g.get("type"), g.get("coordinates")
    try:
        if tipo == "Point":
            coords = _vertice(c)
        elif tipo == "LineString" and isinstance(c, list):
            coords = [_vertice(p) for p in c]
        elif tipo == "Polygon" and isinstance(c, list):
            coords = [[_vertice(p) for p in anel] for anel in c if isinstance(anel, list)]
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Desenho inválido: ponto, linha ou área.")
    except (TypeError, OverflowError) as exc:                  # o inteiro gigante não vira float: 400, não 500
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Desenho inválido: ponto, linha ou área.") from exc
    return {"type": tipo, "coordinates": coords}


def _ligacao_que_nao_cabe(tipo: str, o: dict) -> str | None:
    """A ligação que o objeto já tem e que não cabe no tipo novo (o monitoramento a soltaria calado)."""
    for campo, cabe in LIGA.items():
        if o.get(campo) is not None and tipo not in cabe:
            return campo
    if o.get("gateway_id") is not None and tipo != "tracker_fileira":
        return "gateway_id"
    return None


def _monitoramento_da_pessoa(db: Session, user: User, usina_id: int) -> tuple[PlantLink, object]:
    """A usina (com a ligação ao monitoramento) e o cliente com o token PRÓPRIO de quem edita."""
    link = _usina(db, user, usina_id)
    if (motivo := _edita(user, Produto.MEUWATT)) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, motivo)
    if not link.mw_plant_slug:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina não está ligada ao {MONITORAMENTO}.")
    from app.services.vinculos import SemConexao, cliente_meuwatt
    try:
        mw = cliente_meuwatt(db, user.id, so_proprio=True)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return link, mw


async def _objeto_editavel(mw, slug: str, objeto_id: int, mexe_na_forma: bool, apagando: bool = False) -> dict:
    """O objeto tem de existir na usina; o ponto de um equipamento da árvore move pelo "Marcar" (a manutenção); o
    desenho que veio do voo não muda de forma aqui (a próxima importação o refaria)."""
    try:
        mapa = await mw.mapa(slug)
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MONITORAMENTO) from exc
    o = next((x for x in (mapa or {}).get("objetos") or [] if x.get("id") == objeto_id), None)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esse objeto não está mais no mapa: atualize a tela.")
    origem = str(o.get("origem") or "")
    if origem.startswith(ORIGEM_NO_MAPA):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse ponto é de um equipamento da manutenção: use Mover.")
    if apagando and origem.startswith("termovision:"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse desenho veio do voo: não se apaga por aqui (a próxima "
                                                      "importação o traria de volta, sem a ligação).")
    if mexe_na_forma and origem.startswith("termovision:"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse desenho veio do voo: a forma não muda por aqui.")
    return o


@router.post("/usinas/{usina_id}/objetos")
async def desenhar(usina_id: int, body: ObjetoNovoIn, db: Session = Depends(get_db),
                   user: User = Depends(quem_abre)) -> dict:
    """Um objeto novo da camada do monitoramento, como a pessoa."""
    if body.tipo not in TIPOS_DESENHO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tipo que não se desenha nesta camada.")
    link, mw = _monitoramento_da_pessoa(db, user, usina_id)
    objeto = {"tipo": body.tipo, "nome": (body.nome or "").strip() or None, "geometria": _geometria(body.geometria),
              **{k: getattr(body, k) for k in LIGA if getattr(body, k) is not None}}
    try:
        return await mw.mapa_criar(link.mw_plant_slug, objeto)
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MONITORAMENTO) from exc


@router.patch("/usinas/{usina_id}/objetos/{objeto_id}")
async def alterar(usina_id: int, objeto_id: int, body: ObjetoPatchIn, db: Session = Depends(get_db),
                  user: User = Depends(quem_abre)) -> dict:
    """O nome, o tipo ou a forma de um objeto da camada do monitoramento, como a pessoa."""
    if body.tipo is not None and body.tipo not in TIPOS_DESENHO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tipo que não se desenha nesta camada.")
    link, mw = _monitoramento_da_pessoa(db, user, usina_id)
    nome = (body.nome or "").strip() or None
    campos = {k: v for k, v in (("tipo", body.tipo), ("nome", nome), ("geometria", _geometria(body.geometria)))
              if v is not None}
    # a ligação vai quando veio no corpo — nula inclusive (soltar)
    campos.update({k: getattr(body, k) for k in LIGA if k in body.model_fields_set})
    if not campos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nada a mudar.")
    o = await _objeto_editavel(mw, link.mw_plant_slug, objeto_id, "geometria" in campos)
    if "tipo" in campos and (campo := _ligacao_que_nao_cabe(campos["tipo"], {**o, **campos})) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, (
            "Esta fileira está ligada ao controlador do tracker: o tipo dela não muda por aqui." if campo == "gateway_id"
            else "Este desenho está ligado a um equipamento que não cabe no tipo novo: solte a ligação antes de mudar"
                 " o tipo."))
    try:
        out = await mw.mapa_alterar(link.mw_plant_slug, objeto_id, campos)
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MONITORAMENTO) from exc
    # o que voltou é o que ficou: campo que o monitoramento ignorou NÃO vira "gravado" (regra "nunca enganar")
    nao = [k for k, v in campos.items() if isinstance(out, dict) and out.get(k) != v]
    if nao:
        nomes = {"geometria": "a nova posição", "nome": "o nome", "tipo": "o tipo", "slot_id": "a ligação ao inversor",
                 "string_number": "a ligação à string", "transformer_id": "a ligação ao trafo"}
        raise HTTPException(status.HTTP_409_CONFLICT, "Não ficou gravado: " + ", ".join(nomes[k] for k in nao)
                            + ". O monitoramento ainda não aceita essa mudança.")
    return out


@router.get("/usinas/{usina_id}/ligacoes")
async def ligacoes(usina_id: int, db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> dict:
    """As vagas de inversor da usina e as strings de cada uma: a quem um desenho pode se ligar (só leitura)."""
    link = _usina(db, user, usina_id)
    if not link.mw_plant_slug:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esta usina não está ligada ao {MONITORAMENTO}.")
    from app.services.vinculos import SemConexao, cliente_meuwatt
    try:
        mw = cliente_meuwatt(db, user.id)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    import asyncio
    bruto, slots = await asyncio.gather(mw.strings_por_vaga(link.mw_plant_slug), mw.slots(link.mw_plant_slug),
                                        return_exceptions=True)
    if isinstance(bruto, BaseException):
        raise _do_upstream(bruto, MONITORAMENTO) if isinstance(bruto, httpx.HTTPError) else bruto
    trafo_da_vaga = {s.get("id"): s.get("transformer_id") for s in slots or [] if isinstance(s, dict)} \
        if not isinstance(slots, BaseException) else {}
    vagas = []
    for inv in (bruto or {}).get("inverters") or []:
        if inv.get("slot_id") is None:
            continue                                         # sem vaga não há a quem ligar (o desenho segue a vaga)
        vagas.append({"slot_id": inv["slot_id"], "rotulo": inv.get("label") or inv.get("serial_number") or f"vaga {inv['slot_id']}",
                      "trafo": inv.get("transformer_name"), "transformer_id": trafo_da_vaga.get(inv["slot_id"]),
                      "strings": sorted({int(x["number"]) for x in inv.get("strings") or [] if str(x.get("number", "")).isdigit()})})
    # os trafos: o id pela vaga, o nome pelas strings (o mesmo trafo para todas as vagas dele)
    trafos: dict[int, str] = {}
    for v in vagas:
        if v["transformer_id"] is not None:
            trafos.setdefault(v["transformer_id"], v["trafo"] or f"trafo {v['transformer_id']}")
    return {"vagas": vagas, "trafos": [{"transformer_id": k, "nome": n} for k, n in sorted(trafos.items(), key=lambda kv: kv[1])],
            "trafos_aviso": "Os trafos não puderam ser lidos agora." if isinstance(slots, BaseException) else None}


@router.delete("/usinas/{usina_id}/objetos/{objeto_id}", status_code=204)
async def apagar(usina_id: int, objeto_id: int, db: Session = Depends(get_db), user: User = Depends(quem_abre)) -> None:
    link, mw = _monitoramento_da_pessoa(db, user, usina_id)
    await _objeto_editavel(mw, link.mw_plant_slug, objeto_id, False, apagando=True)
    try:
        await mw.mapa_apagar(link.mw_plant_slug, objeto_id)
    except httpx.HTTPError as exc:
        raise _do_upstream(exc, MONITORAMENTO) from exc
