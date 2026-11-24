"""A porta dos sistemas da família (Plano Casa GS, 24/11/2026: "o GS é o pai"): o meuWatt, o meuPlano, o meuGuarda e o
TermoVision leem, pelo servidor deles, o que o GS guarda da pessoa e das usinas, em nome de quem está com a tela aberta.

A prova é a chave do sistema (`X-Sistema` + `X-Chave-Interna`, a mesma do repasse do login, `acessos.repasse`) e a
pessoa vem em `X-Usuario-GS` (o `sub` do passe) e `X-Empresa-GS` (o `empresa_id` do passe; opcional, sem ele vale a
empresa de origem). A chave sozinha não fala por ninguém: a pessoa tem de estar ativa, com aquele sistema liberado no
GS e a empresa dela ativa. Quem não serve é 404 com a mesma frase (a porta não confirma quem existe).

- `GET /usinas-da-pessoa`: a RENOVAÇÃO da sessão de cada sistema (o plano: "sessões curtas que se renovam pelo GS, sem
  pedir senha; desligar a pessoa no GS derruba as sessões dela em todos os sistemas"): quem é e as usinas que vê, no
  formato do passe v2 (`usinas` / `todas_as_usinas` / `usinas_fora`), calculado na hora. 404 = a sessão acaba lá.
- `GET /usinas[?ids=12,15]` e `GET /usinas/{gs}`: as usinas que a pessoa vê, com o código do GS, a mesma usina em cada
  sistema e os dados básicos (nome, cidade, UF, kWp, endereço, coordenada). A plataforma vê todas, a O&M as da empresa,
  o dono as dele. O TermoVision, que usa a lista para ligar o mapa, segue com a régua dele (`interno_termovision`: só a
  O&M, com entrada recente).
- `POST /passe/termovision`: o passe do TermoVision para o mapa embutido no meuWatt e no meuPlano (o mapa mora no
  TermoVision; os outros mostram a tela dele). É uma credencial: só para quem tem o TermoVision liberado E entrou no
  sistema que pede pelo GS, ela mesma (um passe com o IP dela), nas últimas 12 h. A sessão aberta pela senha do próprio
  sistema não conta: o GS não a viu.
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import _empresa_ativa
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import acessos, empresas, login_externo, pessoas

NOMES = {"meuwatt": "meuWatt", "meuplano": "meuPlano", "meuguarda": "meuGuarda", "termovision": "TermoVision"}
_NAO = "Pessoa ou usina não encontrada."
#: há quanto tempo a pessoa entrou no sistema pelo GS para ele pedir uma credencial por ela
JANELA_DO_PASSE = timedelta(hours=12)
_O_E_M = (Perfil.GESTOR_EMPRESA, Perfil.TECNICO)

router = APIRouter(prefix="/api/v1/interno", tags=["interno · sistemas da família"])


def sistema(request: Request) -> str:
    """Quem chama, provado pela chave dele."""
    dono = acessos.repasse(request)
    if dono:
        return dono
    dito = (request.headers.get("x-sistema") or "").strip().lower()
    if dito in NOMES and not acessos.chave_do_sistema(dito):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Porta interna do {NOMES[dito]} não configurada ({dito.upper()}_CHAVE_INTERNA ausente).")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave inválida.")


def pessoa(db: Session, request: Request, do_sistema: str) -> User:
    """A pessoa de `X-Usuario-GS`, ativa e com aquele sistema liberado no GS."""
    texto = (request.headers.get("x-usuario-gs") or "").strip()
    u = db.get(User, int(texto)) if texto.isdecimal() else None
    if u is None or not u.ativo or do_sistema not in login_externo.liberados(u):
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return u


def empresa_do_pedido(db: Session, u: User, x_empresa_gs: str | None) -> int | None:
    """A empresa em que a pessoa opera: a do passe (`X-Empresa-GS`) ou a de origem, ativa e dela. A plataforma não tem
    empresa; o dono, a de origem."""
    if u.perfil in pessoas.DA_PLATAFORMA:
        return None
    texto = (x_empresa_gs or "").strip()
    if u.perfil not in _O_E_M:                             # o dono: a empresa que o atende, ativa
        try:
            _empresa_ativa(db, u)
        except HTTPException as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO) from exc
        return u.empresa_id
    pedida = int(texto) if texto.isdecimal() else (u.empresa_id if not texto else None)
    ativas = set(db.scalars(select(Empresa.id).where(Empresa.id.in_(empresas.empresas_da_conta(db, u) or [-1]),
                                                     Empresa.ativa)))
    if pedida is None or pedida not in ativas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return pedida


def da_empresa(db: Session, empresa_id: int, so_ativas: bool = True) -> list[PlantLink]:
    q = select(PlantLink).where(PlantLink.empresa_id == empresa_id)
    return list(db.scalars((q.where(PlantLink.ativo) if so_ativas else q).order_by(PlantLink.nome)).all())


def visiveis(db: Session, u: User, empresa_id: int | None) -> list[PlantLink]:
    """As usinas ligadas que a pessoa vê: a plataforma todas, a O&M as da empresa, o dono as concedidas (a régua do
    portal)."""
    if u.perfil in pessoas.DA_PLATAFORMA:
        return list(db.scalars(select(PlantLink).where(PlantLink.ativo).order_by(PlantLink.nome)).all())
    if u.perfil in _O_E_M:
        return da_empresa(db, empresa_id)
    from app.api.v1.plants import usinas_do_usuario
    return usinas_do_usuario(db, u)


class RefMeuWatt(BaseModel):
    slug: str


class RefMeuPlano(BaseModel):
    id: int


class RefTermoVision(BaseModel):
    codigo: str


class UsinaDoGS(BaseModel):
    gs: int
    #: o código que todos os sistemas mostram, para todo mundo achar a mesma ("GS-0012")
    codigo: str
    nome: str
    empresa: str | None = None
    #: a MESMA usina em cada sistema (nulo = não está lá)
    meuwatt: RefMeuWatt | None = None
    meuplano: RefMeuPlano | None = None
    termovision: RefTermoVision | None = None
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    endereco: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    #: quando um dado básico mudou por último (`?alteradas_desde=` relê só as que mudaram)
    atualizado_em: datetime | None = None


def codigo(gs: int) -> str:
    return f"GS-{gs:04d}"


def saida(db: Session, u: PlantLink) -> UsinaDoGS:
    e = db.get(Empresa, u.empresa_id) if u.empresa_id else None
    return UsinaDoGS(
        gs=u.id, codigo=codigo(u.id), nome=u.nome, empresa=e.nome if e else None,
        meuwatt=RefMeuWatt(slug=u.mw_plant_slug) if u.mw_plant_slug else None,
        meuplano=RefMeuPlano(id=u.mp_usina_id) if u.mp_usina_id is not None else None,
        termovision=RefTermoVision(codigo=u.tv_codigo) if u.tv_codigo else None,
        cidade=u.cidade, uf=u.uf, kwp=u.kwp, endereco=u.endereco, latitude=u.latitude, longitude=u.longitude,
        atualizado_em=u.atualizado_em)


def _pedido(db: Session, request: Request) -> tuple[User, list[PlantLink]]:
    """A pessoa e as usinas que ela vê. O TermoVision usa a lista para ligar e importar o mapa: a régua de lá."""
    quem = sistema(request)
    if quem == "termovision":
        from app.api.v1 import interno_termovision as tv
        u = tv._pessoa(db, request.headers.get("x-usuario-gs"))
        return u, da_empresa(db, tv._empresa(db, u, request.headers.get("x-empresa-gs")))
    u = pessoa(db, request, quem)
    return u, visiveis(db, u, empresa_do_pedido(db, u, request.headers.get("x-empresa-gs")))


def _as_do_pedido(db: Session, request: Request) -> list[PlantLink]:
    return _pedido(db, request)[1]


@router.get("/usinas", response_model=list[UsinaDoGS])
def usinas(request: Request, ids: str | None = None, alteradas_desde: datetime | None = None,
           db: Session = Depends(get_db)) -> list[UsinaDoGS]:
    todas = _as_do_pedido(db, request)
    if ids is not None:
        pedidas = {int(x) for x in ids.split(",") if x.strip().isdecimal()}
        todas = [u for u in todas if u.id in pedidas]
    if alteradas_desde is not None:
        desde = alteradas_desde if alteradas_desde.tzinfo else alteradas_desde.replace(tzinfo=UTC)
        todas = [u for u in todas if u.atualizado_em is not None and _com_fuso(u.atualizado_em) >= desde]
    return [saida(db, u) for u in todas]


def _com_fuso(quando: datetime) -> datetime:
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


@router.get("/usinas/{gs}", response_model=UsinaDoGS)
def usina(gs: int, request: Request, db: Session = Depends(get_db)) -> UsinaDoGS:
    link = next((u for u in _as_do_pedido(db, request) if u.id == gs), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    return saida(db, link)


class PessoaOut(BaseModel):
    gs: int
    apelido: str
    nome: str
    email: str | None = None
    perfil: str
    empresa_id: int | None = None
    #: os sistemas que a pessoa abre pelo GS agora (a mesma régua dos botões)
    sistemas: list[str]
    #: como no passe v2: a lista (`gs` + o id no sistema que pergunta), ou todas (a plataforma), ou fora (sem a lista)
    usinas: list[dict] | None = None
    todas_as_usinas: bool = False
    usinas_fora: bool = False
    lido_em: datetime


@router.get("/usinas-da-pessoa", response_model=PessoaOut)
def usinas_da_pessoa(request: Request, db: Session = Depends(get_db)) -> PessoaOut:
    quem = sistema(request)
    u = pessoa(db, request, quem)
    empresa = empresa_do_pedido(db, u, request.headers.get("x-empresa-gs"))
    v2 = login_externo.extras_v2(db, u, quem, empresa)
    return PessoaOut(gs=u.id, apelido=u.apelido, nome=u.nome, email=u.email, perfil=u.perfil.value,
                     empresa_id=v2.get("empresa_id"), sistemas=login_externo.liberados(u), usinas=v2.get("usinas"),
                     todas_as_usinas=bool(v2.get("todas_as_usinas")), usinas_fora=bool(v2.get("usinas_fora")),
                     lido_em=datetime.now(UTC))


class PasseOut(BaseModel):
    assertion: str
    expira_em: datetime


@router.post("/passe/termovision", response_model=PasseOut)
def passe_do_termovision(request: Request, db: Session = Depends(get_db)) -> PasseOut:
    quem = sistema(request)
    if quem == "termovision":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "O TermoVision não pede passe para ele mesmo.")
    u = pessoa(db, request, quem)
    if not u.entra_no_termovision:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    empresa = empresa_do_pedido(db, u, request.headers.get("x-empresa-gs"))
    if acessos._ip_dito(request) is None:                  # o registro e o limite são da pessoa, não do servidor
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta o IP da pessoa (X-Usuario-IP).")
    recente = db.scalar(select(AcessoGS.id).where(
        AcessoGS.gs_user_id == u.id, AcessoGS.sistema == quem, AcessoGS.acao == "passe", AcessoGS.ok,
        AcessoGS.ip != "", AcessoGS.em >= datetime.now(UTC) - JANELA_DO_PASSE).limit(1))
    if recente is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Esta pessoa não entrou no {NOMES[quem]} pelo Gestão Solar nas últimas 12 horas: "
                            "entre pelo GS.")
    try:
        assercao = login_externo.assinar_login(u, login_externo.TERMOVISION, pessoas.escopo_do_perfil(u.perfil),
                                               empresa, login_externo.meuplano_id_de(db, u.id), db=db)
    except login_externo.SemChave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    acessos.registrar(db, request, acao="passe", sistema=login_externo.TERMOVISION, user=u,
                      motivo=f"mapa embutido no {NOMES[quem]}")
    return PasseOut(assertion=assercao, expira_em=datetime.now(UTC) + login_externo.VALIDADE)


@router.get("/usinas/{gs}/mapa/objetos")
async def objetos_do_mapa(gs: int, request: Request, db: Session = Depends(get_db)) -> dict:
    """Os objetos do mapa do GS desta usina (o mapa único, que mora no meuWatt), para o "Importar do GS" do TermoVision:
    cada um com a geometria (GeoJSON, [lng, lat]), a origem e a mesma coisa em cada sistema (o objeto e a ligação dele
    no meuWatt, o nó do meuPlano). Lido com a conta da pessoa (a dela, senão a da empresa: a régua do portal). Sem
    leitura do meuWatt é erro (502), nunca uma lista vazia que parece certa; o que faltou ao lado vai em `avisos`."""
    import asyncio
    from zoneinfo import ZoneInfo

    import httpx

    from app.services.vinculos import SemConexao, cliente_meuplano, cliente_meuwatt

    u, todas = _pedido(db, request)
    link = next((x for x in todas if x.id == gs), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    slug = link.mw_plant_slug
    saida_ = {"usina": {"gs": link.id, "codigo": codigo(link.id), "nome": link.nome,
                        "meuwatt": {"slug": slug} if slug else None},
              "lido_em": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds"),
              "objetos": [], "avisos": []}
    if not slug:
        saida_["avisos"].append("Esta usina não está ligada ao meuWatt, onde mora o mapa do GS: não há objetos.")
        return saida_
    try:
        mw = cliente_meuwatt(db, u.id)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"O mapa do GS não pôde ser lido: {exc}") from exc
    mp = None
    if link.mp_usina_id is not None:
        try:
            mp = cliente_meuplano(db, u.id)
        except SemConexao:
            saida_["avisos"].append("Sem a conexão com o meuPlano: os objetos vão sem o nó do meuPlano.")
    db.commit()                                            # solta a conexão enquanto os sistemas respondem

    async def _nada() -> None:
        return None

    mapa, slots, do_mp = await asyncio.gather(
        mw.mapa(slug), mw.slots(slug), mp.mapa_da_usina(link.mp_usina_id) if mp else _nada(), return_exceptions=True)
    if isinstance(mapa, Exception) or not isinstance(mapa, dict) or not isinstance(mapa.get("objetos"), list):
        como = (f"respondeu {mapa.response.status_code}" if isinstance(mapa, httpx.HTTPStatusError) else
                "não respondeu" if isinstance(mapa, Exception) else "respondeu num formato inesperado")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"O mapa do GS não pôde ser lido agora (o meuWatt {como}).")
    rotulo = {}
    if isinstance(slots, list):
        rotulo = {x.get("id"): x.get("label") or (f"Inv {x['position']}" if x.get("position") else None)
                  for x in slots if isinstance(x, dict)}
    else:
        saida_["avisos"].append("Os inversores do meuWatt não foram lidos: os objetos vão sem o nome do inversor.")
    nos: dict = {}
    if isinstance(do_mp, dict) and isinstance(do_mp.get("objetos"), list) and not do_mp.get("aviso"):
        nos = {o.get("id"): o.get("node_id") for o in do_mp["objetos"] if isinstance(o, dict) and o.get("node_id")}
    elif mp is not None:
        saida_["avisos"].append("O meuPlano não respondeu agora: os objetos vão sem o nó do meuPlano.")
    for o in mapa["objetos"]:
        if not isinstance(o, dict) or o.get("id") is None:
            continue
        saida_["objetos"].append({
            "id": str(o["id"]), "tipo": o.get("tipo"), "nome": o.get("nome"), "geometria": o.get("geometria"),
            "origem": o.get("origem"),
            "refs": {"meuwatt": {"id": o["id"], "slug": slug, "slot_id": o.get("slot_id"),
                                 "inversor": rotulo.get(o.get("slot_id")), "entrada": o.get("string_number"),
                                 "transformer_id": o.get("transformer_id")},
                     "meuplano": {"node": nos[o["id"]]} if o["id"] in nos else None},
            "atualizado_em": o.get("atualizado_em")})
    return saida_


#: o campo da usina do GS que guarda o id dela em cada sistema que cria usina (o meuGuarda usa o número do GS)
REFERENCIA = {"meuwatt": "mw_plant_slug", "meuplano": "mp_usina_id", "termovision": "tv_codigo"}
#: para mudar um dado básico pelo sistema, a pessoa entrou nele pelo GS, ela mesma, há no máximo 30 dias
JANELA_DE_EDITAR = timedelta(days=30)


def _equipe(db: Session, request: Request) -> tuple[str, User, list[PlantLink]]:
    """Quem muda dados da usina: a equipe da O&M (gerente e técnico) e a plataforma, que entrou no sistema que pede pelo
    GS há no máximo 30 dias (a chave vazada não fala por quem não usa aquele sistema)."""
    quem = sistema(request)
    u, todas = _pedido(db, request)
    if u.perfil not in _O_E_M and u.perfil not in pessoas.DA_PLATAFORMA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Os dados da usina são mudados pela equipe da O&M.")
    if quem != "termovision":                              # o TermoVision já confere a entrada dele (12 h)
        recente = db.scalar(select(AcessoGS.id).where(
            AcessoGS.gs_user_id == u.id, AcessoGS.sistema == quem, AcessoGS.acao == "passe", AcessoGS.ok,
            AcessoGS.ip != "", AcessoGS.em >= datetime.now(UTC) - JANELA_DE_EDITAR).limit(1))
        if recente is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Para mudar os dados da usina no GS pelo {NOMES[quem]}, entre nele pelo Gestão Solar.")
    return quem, u, todas


class DadosIn(BaseModel):
    """Só o que veio muda; a coordenada vai em par."""
    model_config = {"extra": "forbid"}
    nome: str | None = None
    endereco: str | None = None
    cidade: str | None = None
    uf: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    kwp: float | None = None


class AlteradaOut(BaseModel):
    usina: UsinaDoGS
    #: os campos que mudaram (vazio = já estava assim)
    alterados: list[str]


@router.patch("/usinas/{gs}", response_model=AlteradaOut)
def alterar_usina(gs: int, body: DadosIn, request: Request, db: Session = Depends(get_db)) -> AlteradaOut:
    from app.services import dados_da_usina
    quem, u, todas = _equipe(db, request)
    link = next((x for x in todas if x.id == gs), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    try:
        feitos = dados_da_usina.alterar(db, link, body.model_dump(exclude_unset=True), por=u, sistema=quem)
    except dados_da_usina.DadoInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    db.refresh(link)
    return AlteradaOut(usina=saida(db, link), alterados=feitos)


class RegistroIn(BaseModel):
    model_config = {"extra": "forbid"}
    nome: str
    #: o id da usina no sistema que registra: o slug no meuWatt, o número no meuPlano, o código no TermoVision
    referencia: str
    cidade: str | None = None
    uf: str | None = None
    endereco: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    kwp: float | None = None


class RegistroOut(BaseModel):
    #: criada (nasceu no GS), ligada (o id de lá já é de uma usina do GS), a_confirmar (o gerente decide),
    #: descartada (o gerente descartou este registro)
    situacao: str
    usina: UsinaDoGS | None = None
    parecidas: list[dict] = []


def _referencia(quem: str, texto: str):
    texto = (texto or "").strip()
    if quem == "meuplano":
        if not texto.isdecimal():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A referência do meuPlano é o número da usina.")
        return int(texto)
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", texto) or (quem == "termovision" and len(texto) > 40):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A referência tem letras, números, - e _.")
    return texto


@router.post("/usinas", response_model=RegistroOut)
def registrar_usina(body: RegistroIn, request: Request, db: Session = Depends(get_db)) -> RegistroOut:
    """A usina criada no sistema que pede entra no GS (o plano: "se parecer uma que já existe (nome e distância), fica
    'a confirmar' e o gerente da O&M decide; se não parecer nenhuma, nasce nova"). Pedir de novo é idempotente e é como
    o sistema sabe o que o gerente decidiu. 201 criada, 202 a confirmar, 200 ligada ou descartada."""
    from fastapi.responses import JSONResponse

    from app.models.plant import UsinaAConfirmar
    from app.services import dados_da_usina

    quem = sistema(request)
    if quem not in REFERENCIA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este sistema usa as usinas do GS: não cria usina.")
    _, u, _ = _equipe(db, request)
    empresa = empresa_do_pedido(db, u, request.headers.get("x-empresa-gs"))
    if quem == "termovision" or empresa is None:           # a régua do TV não passa pela de cima; a plataforma diz qual
        texto = (request.headers.get("x-empresa-gs") or "").strip()
        empresa = int(texto) if texto.isdecimal() else empresa
        if empresa is None or db.get(Empresa, empresa) is None or not db.get(Empresa, empresa).ativa:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Diga de qual empresa de O&M é a usina (X-Empresa-GS).")
    campo = REFERENCIA[quem]
    ref = _referencia(quem, body.referencia)
    dados = body.model_dump(exclude={"referencia"})
    try:
        limpos = {c: dados_da_usina._limpo(c, v) for c, v in dados.items()}
        if (limpos["latitude"] is None) != (limpos["longitude"] is None):
            raise dados_da_usina.DadoInvalido("A coordenada vai inteira: latitude e longitude juntas.")
    except dados_da_usina.DadoInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    ja = db.scalar(select(PlantLink).where(getattr(PlantLink, campo) == ref))
    if ja is not None:
        if ja.empresa_id != empresa:
            raise HTTPException(status.HTTP_409_CONFLICT, "Esta usina já está no GS por outra empresa.")
        return RegistroOut(situacao="ligada", usina=saida(db, ja))
    pedido = db.scalar(select(UsinaAConfirmar).where(UsinaAConfirmar.sistema == quem,
                                                     UsinaAConfirmar.referencia == str(ref)))
    if pedido is not None:
        if pedido.decisao == "descartada":
            return RegistroOut(situacao="descartada")
        if pedido.decisao is None:
            return JSONResponse(status_code=202, content=RegistroOut(
                situacao="a_confirmar", parecidas=pedido.parecidas).model_dump(mode="json"))
    parecidas = dados_da_usina.parecidas(db, empresa, limpos["nome"], limpos["latitude"], limpos["longitude"])
    if parecidas:
        db.add(UsinaAConfirmar(empresa_id=empresa, sistema=quem, referencia=str(ref), dados=limpos,
                               parecidas=parecidas, pedido_por_id=u.id))
        db.commit()
        return JSONResponse(status_code=202, content=RegistroOut(
            situacao="a_confirmar", parecidas=parecidas).model_dump(mode="json"))
    link = dados_da_usina.criar(db, empresa=empresa, dados=limpos, campo=campo, ref=ref, por=u, sistema=quem)
    db.commit()
    db.refresh(link)
    return JSONResponse(status_code=201, content=RegistroOut(situacao="criada", usina=saida(db, link))
                        .model_dump(mode="json"))
