"""A porta dos sistemas da família (Plano Casa GS, 24/11/2026: "o GS é o pai"): o meuWatt, o meuPlano, o meuGuarda e o
TermoVision leem, pelo servidor deles, o que o GS guarda da pessoa e das usinas, em nome de quem está com a tela aberta.

A prova é a chave do sistema (`X-Sistema` + `X-Chave-Interna`, a mesma do repasse do login, `acessos.repasse`) e a
pessoa vem em `X-Usuario-GS` (o `sub` do passe), `X-Empresa-GS` (o `empresa_id` do passe; opcional, sem ele vale a
empresa de origem) e `X-Sessao-GS` (o `sessao_gs` do passe: a sessão dela NESTE sistema). A chave sozinha não fala por
ninguém: a pessoa tem de estar ativa, com aquele sistema liberado no GS, a empresa ativa e a sessão do passe valendo
(encerrar as sessões dela no GS a encerra aqui também). Na transição, sem `X-Sessao-GS`, vale quem entrou pelo GS (no
GS ou naquele sistema, ela mesma, com o IP dela) nos últimos 60 dias. Quem não serve é 404 com a mesma frase (a porta
não confirma quem existe). Cada leitura entra no Registro de acessos, uma linha por pessoa, sistema e hora.

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
- `GET /maquina/usinas[?alteradas_desde=]`: a porta da MÁQUINA, a única que a chave abre sozinha (a rotina do servidor
  do sistema, sem ninguém na tela, mantendo a cópia dele do vínculo). A chave segue sem falar por ninguém: não lê nada
  de pessoa, só as linhas do índice ligadas ao PRÓPRIO sistema, com os dados básicos e a referência dele (nem a empresa,
  nem a proprietária, nem a mesma usina nos outros sistemas). Uma linha por sistema e hora no Registro de acessos.
"""
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import _empresa_ativa
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa
from app.models.plant import HistoricoDaUsina, PlantLink
from app.models.user import Perfil, User
from app.services import acessos, empresas, login_externo, pessoas

NOMES = {"meuwatt": "meuWatt", "meuplano": "meuPlano", "meuguarda": "meuGuarda", "termovision": "TermoVision"}
_NAO = "Pessoa ou usina não encontrada."
#: há quanto tempo a pessoa entrou no sistema pelo GS para ele pedir uma credencial por ela
JANELA_DO_PASSE = timedelta(hours=12)
#: a transição, enquanto o sistema não manda o `X-Sessao-GS`: quem entrou pelo GS há no máximo isto
JANELA_SEM_SESSAO = timedelta(days=60)
_O_E_M = (Perfil.GESTOR_EMPRESA, Perfil.TECNICO)
BRASILIA = ZoneInfo("America/Sao_Paulo")
log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/interno", tags=["interno · sistemas da família"])


def sistema(request: Request) -> str:
    """Quem chama, provado pela chave dele. Sem a chave certa, 401 (e nada diz qual chave está configurada)."""
    dono = acessos.repasse(request)
    if dono:
        return dono
    dito = (request.headers.get("x-sistema") or "").strip().lower()
    if dito in NOMES and not acessos.chave_do_sistema(dito):
        log.warning("porta dos sistemas: %s sem chave configurada (%s_CHAVE_INTERNA)", dito, dito.upper())
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave inválida.")


def pessoa(db: Session, request: Request, do_sistema: str, *, o_que: str = "") -> User:
    """A pessoa de `X-Usuario-GS`, ativa, com aquele sistema liberado no GS e a sessão DELA naquele sistema valendo
    (`X-Sessao-GS`; na transição, a entrada pelo GS nos últimos 60 dias). `o_que` vai ao Registro de acessos."""
    from app.core.security import conferir_token_sistema
    texto = (request.headers.get("x-usuario-gs") or "").strip()
    u = db.get(User, int(texto)) if texto.isdecimal() else None
    from app.services import duas_etapas
    if u is None or not u.ativo or do_sistema not in login_externo.liberados(u) or duas_etapas.pendente(u):
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)  # pendente: exige o código e não cadastrou (sessão velha)
    sessao = (request.headers.get("x-sessao-gs") or "").strip()
    if sessao:
        if not conferir_token_sistema(db, sessao, u, do_sistema, request):
            raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)        # encerrada ou de outra pessoa: a sessão acaba
    elif db.scalar(select(AcessoGS.id).where(
            AcessoGS.gs_user_id == u.id, AcessoGS.ok, AcessoGS.acao.in_(("entrou", "passe")), AcessoGS.ip != "",
            AcessoGS.sistema.in_(("gs", do_sistema)), AcessoGS.em >= desde_a_ultima_entrada(u, JANELA_SEM_SESSAO)
            ).limit(1)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    if o_que:
        acessos.registrar(db, request, acao="leitura", sistema=do_sistema, user=u, agrupar_s=3600,
                          motivo=f"{NOMES[do_sistema]} leu pela porta dos sistemas: {o_que}"
                                 + ("" if sessao else " (sem a sessão do passe)"))
    return u


def desde_a_ultima_entrada(u: User, janela: timedelta) -> datetime:
    """De quando vale a entrada pelo GS sem a sessão do passe: a janela, e nunca antes de um "encerrar todas" (ou de
    uma senha nova): a entrada de antes dele não fala mais pela pessoa."""
    desde = datetime.now(UTC) - janela
    fim = u.sessoes_desde
    if fim is not None:
        fim = fim if fim.tzinfo else fim.replace(tzinfo=UTC)
        desde = max(desde, fim)
    return desde


def _sessao_renovada(db: Session, request: Request, u: User, quem: str) -> str | None:
    """O `sessao_gs` novo da mesma sessão (o `X-Sessao-GS` já foi conferido em `pessoa`): quem usa o sistema todo dia
    não sai no 60º dia. A linha da sessão ganha o prazo novo."""
    from jose import jwt

    from app.core.config import get_settings
    from app.core.security import ALGORITMO, DIAS_DA_SESSAO_DE_SISTEMA, criar_token_sistema
    from app.models.sessao import SessaoGS
    token = (request.headers.get("x-sessao-gs") or "").strip()
    if not token:
        return None
    sid = jwt.decode(token, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]).get("sid")
    if not isinstance(sid, str) or not sid:
        return None
    linha = db.get(SessaoGS, sid[:32])
    if linha is not None:
        linha.expira_em = datetime.now(UTC) + timedelta(days=DIAS_DA_SESSAO_DE_SISTEMA)
        db.commit()
    return criar_token_sistema(u.id, quem, sid=sid)


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
    """As usinas que a pessoa vê: a plataforma todas, a O&M as da empresa (também as fora do aplicativo, como a que só
    existe no TermoVision: `ativo` diz), o dono as concedidas e ligadas (a régua do portal)."""
    if u.perfil in pessoas.DA_PLATAFORMA:
        return list(db.scalars(select(PlantLink).order_by(PlantLink.nome)).all())
    if u.perfil in _O_E_M:
        return da_empresa(db, empresa_id, so_ativas=False)
    from app.api.v1.plants import usinas_do_usuario
    return usinas_do_usuario(db, u)


def usina_da_pessoa(db: Session, u: User, gs: int, x_empresa_gs: str | None) -> PlantLink | None:
    """A usina que a pessoa vê: na empresa do passe e, para a O&M de mais de uma empresa, numa outra empresa ATIVA dela
    (o mapa embutido aberto com o passe de uma empresa, numa usina da outra: antes dava 404)."""
    empresa = empresa_do_pedido(db, u, x_empresa_gs)
    link = next((x for x in visiveis(db, u, empresa) if x.id == gs), None)
    if link is None and u.perfil in _O_E_M:
        outras = db.scalars(select(Empresa.id).where(
            Empresa.id.in_([e for e in empresas.empresas_da_conta(db, u) if e != empresa] or [-1]), Empresa.ativa)).all()
        link = next((x for e in outras for x in da_empresa(db, e, so_ativas=False) if x.id == gs), None)
    return link


class RefMeuWatt(BaseModel):
    slug: str


class RefMeuPlano(BaseModel):
    id: int


class RefTermoVision(BaseModel):
    codigo: str


class ProprietariaDoGS(BaseModel):
    id: int
    nome: str
    #: a organização PROPRIETARIA no meuPlano, quando ligada
    meuplano: RefMeuPlano | None = None


class UsinaDoGS(BaseModel):
    gs: int
    #: o código que todos os sistemas mostram, para todo mundo achar a mesma ("GS-0012")
    codigo: str
    nome: str
    empresa: str | None = None
    #: o número da empresa de O&M dona da usina no GS (o `empresa_id` do passe)
    empresa_id: int | None = None
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
    #: no aplicativo do GS (falso = desligada lá, ou só no TermoVision); o resto da família a vê assim mesmo
    ativo: bool = True
    #: quando um dado básico mudou por último (`?alteradas_desde=` relê só as que mudaram)
    atualizado_em: datetime | None = None
    #: a DONA da usina (R11), quando cadastrada
    proprietaria: ProprietariaDoGS | None = None


def codigo(gs: int) -> str:
    return f"GS-{gs:04d}"


def proprietaria_de(db: Session, proprietaria_id: int | None) -> ProprietariaDoGS | None:
    from app.models.empresa import Proprietaria
    p = db.get(Proprietaria, proprietaria_id) if proprietaria_id else None
    return ProprietariaDoGS(id=p.id, nome=p.nome, meuplano=RefMeuPlano(id=p.mp_owner_id) if p.mp_owner_id else None
                            ) if p is not None else None


def saida(db: Session, u: PlantLink) -> UsinaDoGS:
    e = db.get(Empresa, u.empresa_id) if u.empresa_id else None
    return UsinaDoGS(
        gs=u.id, codigo=codigo(u.id), nome=u.nome, empresa=e.nome if e else None, empresa_id=u.empresa_id,
        meuwatt=RefMeuWatt(slug=u.mw_plant_slug) if u.mw_plant_slug else None,
        meuplano=RefMeuPlano(id=u.mp_usina_id) if u.mp_usina_id is not None else None,
        termovision=RefTermoVision(codigo=u.tv_codigo) if u.tv_codigo else None,
        cidade=u.cidade, uf=u.uf, kwp=u.kwp, endereco=u.endereco, latitude=u.latitude, longitude=u.longitude,
        ativo=bool(u.ativo), atualizado_em=u.atualizado_em, proprietaria=proprietaria_de(db, u.proprietaria_id))


def _pedido(db: Session, request: Request, o_que: str = "") -> tuple[User, list[PlantLink]]:
    """A pessoa e as usinas que ela vê. O TermoVision usa a lista para ligar e importar o mapa: a régua de lá."""
    quem = sistema(request)
    if quem == "termovision":
        from app.api.v1 import interno_termovision as tv
        u = tv._pessoa(db, request.headers.get("x-usuario-gs"))
        todas = da_empresa(db, tv._empresa(db, u, request.headers.get("x-empresa-gs")), so_ativas=False)
        if o_que:
            acessos.registrar(db, request, acao="leitura", sistema=quem, user=u, agrupar_s=3600,
                              motivo=f"TermoVision leu pela porta dos sistemas: {o_que}")
        return u, todas
    u = pessoa(db, request, quem, o_que=o_que)
    return u, visiveis(db, u, empresa_do_pedido(db, u, request.headers.get("x-empresa-gs")))


def _as_do_pedido(db: Session, request: Request, o_que: str = "") -> list[PlantLink]:
    return _pedido(db, request, o_que)[1]


@router.get("/usinas", response_model=list[UsinaDoGS])
def usinas(request: Request, response: Response, ids: str | None = None, alteradas_desde: datetime | None = None,
           db: Session = Depends(get_db)) -> list[UsinaDoGS]:
    """`X-GS-Lido-Em` (o relógio do GS): para reler só o que mudou, mande este valor (menos 1 min de folga) no
    `alteradas_desde` da próxima vez. Sem fuso, `alteradas_desde` é de Brasília."""
    _lido_em(response)
    todas = _as_do_pedido(db, request, "as usinas")
    if ids is not None:
        pedidas = {int(x) for x in ids.split(",") if x.strip().isdecimal()}
        todas = [u for u in todas if u.id in pedidas]
    return [saida(db, u) for u in _alteradas(todas, _desde(alteradas_desde))]


def _com_fuso(quando: datetime) -> datetime:
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


def _lido_em(response: Response) -> None:
    """O relógio do GS no `X-GS-Lido-Em`, marcado ANTES de ler: o que mudar durante a leitura volta na próxima."""
    response.headers["X-GS-Lido-Em"] = datetime.now(UTC).isoformat(timespec="seconds")


def _desde(alteradas_desde: datetime | None) -> datetime | None:
    """O `alteradas_desde` com fuso (sem fuso, é de Brasília)."""
    if alteradas_desde is None:
        return None
    return alteradas_desde if alteradas_desde.tzinfo else alteradas_desde.replace(tzinfo=BRASILIA)


def _alteradas(todas: list[PlantLink], desde: datetime | None) -> list[PlantLink]:
    """As que tiveram um dado básico (ou um vínculo) mudado de `desde` para cá; sem `desde`, todas."""
    if desde is None:
        return todas
    return [u for u in todas if u.atualizado_em is not None and _com_fuso(u.atualizado_em) >= desde]


@router.get("/usinas/{gs}", response_model=UsinaDoGS)
def usina(gs: int, request: Request, db: Session = Depends(get_db)) -> UsinaDoGS:
    link = next((u for u in _as_do_pedido(db, request, f"a usina {codigo(gs)}") if u.id == gs), None)
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
    #: a proprietária de que o dono de usina é (R11), como no passe
    proprietaria: ProprietariaDoGS | None = None
    #: como no passe v2: a lista (`gs` + o id no sistema que pergunta), ou todas (a plataforma), ou fora (sem a lista)
    usinas: list[dict] | None = None
    todas_as_usinas: bool = False
    usinas_fora: bool = False
    lido_em: datetime
    #: a renovação da sessão: veio `X-Sessao-GS` válido, volta um novo, da MESMA sessão, valendo 60 dias a contar de
    #: agora (guardem este no lugar do outro). Sem o cabeçalho (a transição), nulo.
    sessao_gs: str | None = None


@router.get("/usinas-da-pessoa", response_model=PessoaOut)
def usinas_da_pessoa(request: Request, db: Session = Depends(get_db)) -> PessoaOut:
    quem = sistema(request)
    u = pessoa(db, request, quem, o_que="a renovação (quem é e as usinas)")
    empresa = empresa_do_pedido(db, u, request.headers.get("x-empresa-gs"))
    v2 = login_externo.extras_v2(db, u, quem, empresa, teto=False)   # não vai numa asserção: a lista inteira
    return PessoaOut(sessao_gs=_sessao_renovada(db, request, u, quem),gs=u.id, apelido=u.apelido, nome=u.nome, email=u.email, perfil=u.perfil.value,
                     empresa_id=v2.get("empresa_id"), sistemas=login_externo.liberados(u), usinas=v2.get("usinas"),
                     proprietaria=proprietaria_de(db, u.proprietaria_id),
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
        AcessoGS.ip != "", AcessoGS.em >= desde_a_ultima_entrada(u, JANELA_DO_PASSE)).limit(1))
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

    if sistema(request) == "termovision" and (request.headers.get("x-sessao-gs") or "").strip():
        # o mapa EMBUTIDO (fase 1 do mapa novo, o "libere" do Renan em 25/11/2026): lê quem vê a usina na lista do GS,
        # pela sessão do passe (o dono também); sem ela, a régua do "Importar do GS" (a O&M, passe de 12 h)
        u = pessoa(db, request, "termovision", o_que=f"o mapa da usina {codigo(gs)}")
        link = usina_da_pessoa(db, u, gs, request.headers.get("x-empresa-gs"))
    else:
        u, todas = _pedido(db, request, f"o mapa da usina {codigo(gs)}")
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
    if u.perfil not in _O_E_M and u.perfil is not Perfil.ADMINISTRADOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Os dados da usina são mudados pela equipe da O&M.")
    if quem != "termovision":                              # o TermoVision já confere a entrada dele (12 h)
        recente = db.scalar(select(AcessoGS.id).where(
            AcessoGS.gs_user_id == u.id, AcessoGS.sistema == quem, AcessoGS.acao == "passe", AcessoGS.ok,
            AcessoGS.ip != "", AcessoGS.em >= desde_a_ultima_entrada(u, JANELA_DE_EDITAR)).limit(1))
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

    from sqlalchemy.exc import IntegrityError

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

    def ja_decidido() -> RegistroOut | JSONResponse | None:
        """O que já existe para esta usina de lá: ligada a uma usina do GS, a confirmar ou descartada."""
        ja = db.scalar(select(PlantLink).where(getattr(PlantLink, campo) == ref))
        if ja is not None:
            if ja.empresa_id != empresa:
                raise HTTPException(status.HTTP_409_CONFLICT, OUTRA_EMPRESA)
            return RegistroOut(situacao="ligada", usina=saida(db, ja))
        pedidos = list(db.scalars(select(UsinaAConfirmar).where(UsinaAConfirmar.sistema == quem,
                                                                UsinaAConfirmar.referencia == str(ref))))
        # o de OUTRA empresa esperando o gerente de lá bloqueia (nada dele vaza); o que ela descartou ("não é nossa"),
        # não: fica na lista de descartados dela, e esta empresa tem o próprio pedido
        if any(x.empresa_id != empresa and x.decisao is None for x in pedidos):
            raise HTTPException(status.HTTP_409_CONFLICT, OUTRA_EMPRESA)
        pedido = next((x for x in pedidos if x.empresa_id == empresa), None)
        if pedido is None:
            return None
        if pedido.decisao is None:
            return JSONResponse(status_code=202, content=RegistroOut(
                situacao="a_confirmar", parecidas=_parecidas_daqui(db, pedido.parecidas, empresa)).model_dump(mode="json"))
        if pedido.decisao == "descartada":
            return RegistroOut(situacao="descartada")
        db.delete(pedido)                                  # decidido, e o vínculo saiu depois: pede de novo
        db.flush()
        return None

    if (r := ja_decidido()) is not None:
        return r
    parecidas = dados_da_usina.parecidas(db, empresa, limpos["nome"], limpos["latitude"], limpos["longitude"])
    try:
        if parecidas:
            db.add(UsinaAConfirmar(empresa_id=empresa, sistema=quem, referencia=str(ref), dados=limpos,
                                   parecidas=parecidas, pedido_por_id=u.id))
            db.commit()
            return JSONResponse(status_code=202, content=RegistroOut(
                situacao="a_confirmar", parecidas=parecidas).model_dump(mode="json"))
        link = dados_da_usina.criar(db, empresa=empresa, dados=limpos, campo=campo, ref=ref, por=u, sistema=quem)
        db.commit()
    except IntegrityError:                                 # o mesmo pedido ao mesmo tempo: responde o que ficou
        db.rollback()
        if (r := ja_decidido()) is not None:
            return r
        raise
    db.refresh(link)
    return JSONResponse(status_code=201, content=RegistroOut(situacao="criada", usina=saida(db, link))
                        .model_dump(mode="json"))


#: a usina de lá já está no GS (ou esperando a confirmação) por outra empresa
OUTRA_EMPRESA = "Esta usina já foi registrada no GS por outra empresa."


def _parecidas_daqui(db: Session, parecidas: list[dict], empresa: int) -> list[dict]:
    """As parecidas gravadas no pedido que ainda são desta empresa (a que saiu dela não se nomeia)."""
    daqui = set(db.scalars(select(PlantLink.id).where(PlantLink.empresa_id == empresa)))
    return [p for p in parecidas or [] if p.get("gs") in daqui]


# --------------------------------------------------------------------------- a porta da máquina (só a chave do sistema)
class UsinaDaMaquina(BaseModel):
    """A usina do índice para o servidor do sistema: os dados básicos e a referência DELE. Sem a empresa, sem a
    proprietária e sem a mesma usina nos outros sistemas (a chave não aprende o que é dos outros)."""
    gs: int
    codigo: str
    nome: str
    #: das três, só a do sistema que chama vai na resposta (as outras nem como nulo)
    meuwatt: RefMeuWatt | None = None
    meuplano: RefMeuPlano | None = None
    termovision: RefTermoVision | None = None
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    endereco: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    #: no aplicativo do GS (falso = desligada lá); vem assim mesmo, para o sistema ficar sabendo
    ativo: bool = True
    atualizado_em: datetime | None = None


class DesligadaDaMaquina(BaseModel):
    """O vínculo que SAIU: esta referência do sistema que chama deixou de ser desta usina do GS."""
    gs: int
    codigo: str
    #: a referência que saiu (só a do sistema que chama)
    meuwatt: RefMeuWatt | None = None
    meuplano: RefMeuPlano | None = None
    termovision: RefTermoVision | None = None
    desligada_em: datetime


class MaquinaOut(BaseModel):
    usinas: list[UsinaDaMaquina]
    #: só com `alteradas_desde` (na leitura inteira, o que não veio em `usinas` não está ligado)
    desligadas: list[DesligadaDaMaquina]


def _ref(quem: str, valor) -> dict:
    """A referência no formato da porta, no campo do sistema (`{"meuwatt": {"slug": …}}`)."""
    if quem == "meuplano":
        return {quem: RefMeuPlano(id=int(valor))}
    if quem == "termovision":
        return {quem: RefTermoVision(codigo=str(valor))}
    return {quem: RefMeuWatt(slug=str(valor))}


def _desligadas(db: Session, quem: str, desde: datetime) -> list[DesligadaDaMaquina]:
    """As referências do sistema que deixaram a usina do GS de `desde` para cá, pelo histórico por campo (a troca de
    vínculo grava uma linha com o antes). A que voltou para a mesma usina não conta; a que foi para OUTRA usina sai
    daqui e a outra vem em `usinas`."""
    campo = REFERENCIA[quem]
    linhas = db.execute(
        select(HistoricoDaUsina, PlantLink).join(PlantLink, PlantLink.id == HistoricoDaUsina.plant_link_id)
        .where(HistoricoDaUsina.campo == campo, HistoricoDaUsina.antes.isnot(None))
        .order_by(HistoricoDaUsina.em, HistoricoDaUsina.id)).all()
    saiu: dict[tuple[int, str], DesligadaDaMaquina] = {}
    for h, link in linhas:
        agora = getattr(link, campo)
        if _com_fuso(h.em) < desde or (agora is not None and str(agora) == h.antes):
            continue
        if quem == "meuplano" and not h.antes.isdecimal():
            continue
        saiu[(link.id, h.antes)] = DesligadaDaMaquina(gs=link.id, codigo=codigo(link.id),
                                                      desligada_em=_com_fuso(h.em), **_ref(quem, h.antes))
    return sorted(saiu.values(), key=lambda d: (d.gs, d.desligada_em))


@router.get("/maquina/usinas", response_model=MaquinaOut, response_model_exclude_unset=True)
def usinas_da_maquina(request: Request, response: Response, alteradas_desde: datetime | None = None,
                      db: Session = Depends(get_db)) -> MaquinaOut:
    """A porta da máquina: a rotina do servidor do sistema lê, só com a chave dele, as usinas do índice ligadas a ELE
    (para manter a cópia dele do vínculo sem ninguém na tela). Nenhum cabeçalho de pessoa é lido. Vêm também as
    desligadas no aplicativo (`ativo` falso). `alteradas_desde` e `X-GS-Lido-Em` são os de `GET /usinas`; com
    `alteradas_desde` vêm ainda as `desligadas` (o vínculo que saiu: apliquem antes das `usinas`). O meuGuarda, que usa
    o número do GS, não tem o que ler aqui: 403."""
    quem = sistema(request)
    if quem not in REFERENCIA:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este sistema usa as usinas do GS: não tem usina ligada a ele.")
    _lido_em(response)
    acessos.registrar(db, request, acao="leitura", sistema=quem, agrupar_s=3600,
                      motivo=f"{NOMES[quem]} leu pela porta da máquina (só a chave, sem pessoa): as usinas ligadas a ele")
    campo, desde = REFERENCIA[quem], _desde(alteradas_desde)
    ligadas = list(db.scalars(select(PlantLink).where(getattr(PlantLink, campo).isnot(None))
                              .order_by(PlantLink.nome, PlantLink.id)).all())
    return MaquinaOut(
        usinas=[UsinaDaMaquina(gs=u.id, codigo=codigo(u.id), nome=u.nome, cidade=u.cidade, uf=u.uf, kwp=u.kwp,
                               endereco=u.endereco, latitude=u.latitude, longitude=u.longitude, ativo=bool(u.ativo),
                               atualizado_em=u.atualizado_em, **_ref(quem, getattr(u, campo)))
                for u in _alteradas(ligadas, desde)],
        desligadas=_desligadas(db, quem, desde) if desde is not None else [])
