"""Trocar de papel — a rota que atravessa os três portões.

É o único lugar do sistema que aceita sessão de qualquer portão, e por um motivo estreito:
ela não devolve dado nenhum. Recebe um token válido, confere que a conta de destino é do
mesmo humano e emite o token DAQUELE portão. Nada de empresa, nada de usina, nada de
cliente passa por aqui.

A guarda é montada à mão em vez de reusar `usuario_atual`/`gestor_atual`/`gestor_empresa_atual`:
cada uma delas recusa, de propósito, as sessões dos outros dois — e essa recusa é o que
sustenta a separação. Uma quarta guarda que aceita todas não a enfraquece **porque não
serve dado**; o que ela faz é dizer quem está falando.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import (
    ALGORITMO,
    conferir_senha,
    criar_token,
    criar_token_empresa,
    criar_token_entrada,
    criar_token_painel,
    criar_token_tecnico,
    gerar_hash_senha,
)
from app.models.empresa import Empresa
from app.models.user import User
from app.services import empresas, pessoas

from app.api.v1.painel import DuasEtapasOut  # noqa: E402

router = APIRouter(prefix="/api/sessao", tags=["sessão · papéis"])

_bearer = HTTPBearer(auto_error=False)
#: os escopos que são sessão de um portão (None = o app e o portal do dono de usina)
_ESCOPOS_DE_SESSAO = (None, "painel", "empresa", "tecnico")


def _sessao(cred: HTTPAuthorizationCredentials | None, db: Session, aceita_entrada: bool = False,
            request: Request | None = None) -> tuple[User, dict]:
    """Quem está falando, e o que o token diz (escopo, empresa da sessão). A sessão de ENTRADA (`criar_token_entrada`)
    só vale onde se pede (`aceita_entrada`): sem isso, trocar de papel com ela emitiria a sessão inteira de um portão."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO])
        usuario = db.get(User, int(dados["sub"]))
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc
    # Lista FECHADA dos tokens que são sessão de uma pessoa num portão (o do app/portal não tem escopo). O desafio da
    # duas etapas (`2fa`, sai só com a senha) e o `sessao_gs` de um sistema (`sistema:*`, vai em todo passe) NÃO são:
    # com eles, trocar a senha ou de papel pulava o código (avaliação de 24/11/2026).
    escopo = dados.get("escopo")
    if escopo not in _ESCOPOS_DE_SESSAO and not (escopo == "entrada" and aceita_entrada):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")

    if usuario is None or not usuario.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    from app.core.security import _sessao_viva
    _sessao_viva(db, dados, usuario, request)              # com o pedido: a lista de sessões diz de onde e de qual aparelho
    return usuario, dados


def sessao_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Quem está falando, venha do portão que vier. Não autoriza nada por si."""
    return _sessao(cred, db, request=request)[0]


class ContaOut(BaseModel):
    apelido: str
    nome: str
    #: `painel`, `empresa` ou `cliente` — o portão que esta conta abre.
    escopo: str
    perfil: str
    empresa: str | None = None
    #: A conta desta sessão.
    atual: bool = False
    #: Trocar para esta conta exige a senha dela. Verdadeiro nas contas da PLATAFORMA:
    #: sem isso, uma sessão de aplicativo roubada viraria sessão de administrador sem
    #: ninguém precisar saber nenhuma senha.
    exige_senha: bool = False
    #: Trocar para esta conta exige o código do autenticador dela: a conta exige a verificação em duas etapas (R12;
    #: sem isso, a sessão do dono virava a do gerente sem o código).
    exige_codigo: bool = False


@router.get("/papeis", response_model=list[ContaOut])
def papeis(
    db: Session = Depends(get_db), usuario: User = Depends(sessao_atual)
) -> list[ContaOut]:
    """Os papéis desta pessoa. Sem agrupamento, devolve só o papel atual."""
    from app.services import duas_etapas
    return [
        ContaOut(
            apelido=c.apelido,
            nome=c.nome,
            escopo=pessoas.escopo_do_perfil(c.perfil),
            perfil=c.perfil.value,
            empresa=pessoas.nome_da_empresa(db, c),
            atual=c.id == usuario.id,
            exige_senha=c.perfil in pessoas.DA_PLATAFORMA,
            exige_codigo=c.id != usuario.id and duas_etapas.exigida(c),
        )
        for c in pessoas.contas_da_pessoa(db, usuario)
    ]


class TrocaIn(BaseModel):
    apelido: str
    #: Só quando o destino é da plataforma. Ver a regra em `services/pessoas`.
    senha: str | None = None
    #: E o código do autenticador dela (a verificação em duas etapas, R12), quando a conta de destino a exige.
    codigo: str | None = None


class TrocaOut(BaseModel):
    token: str
    expira_em: datetime
    apelido: str
    nome: str
    escopo: str
    perfil: str
    empresa: str | None = None


@router.post("/trocar", response_model=TrocaOut)
def trocar(
    body: TrocaIn, db: Session = Depends(get_db), usuario: User = Depends(sessao_atual), request: Request = None
) -> TrocaOut:
    """Emite a sessão do outro papel da MESMA pessoa.

    A sessão anterior não é invalidada: as duas valem até expirar, cada uma no portão
    dela. Derrubá-la seria impedir o caso que motivou tudo isto — o painel da plataforma
    aberto numa aba e o da empresa em outra.
    """
    from app.services import acessos
    chave = f"papel:{usuario.id}"                          # por conta (e lugar), não por alvo: sondar nomes não cria chaves
    if acessos.barrado(request, chave, por_ip=False):      # a senha de subir para a plataforma também tem limite
        if acessos._uma_vez(f"{chave}|barrado"):
            acessos.registrar(db, request, acao="bloqueado", user=usuario, ok=False,
                              motivo="troca de papel: 10 senhas erradas em 15 min")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, acessos.BARRADO)
    try:
        destino = pessoas.trocar(db, usuario, body.apelido, body.senha)
    except HTTPException as e:
        acessos.contar_erro(request, chave)                # 404 (conta que não é dela) também conta, sem linha
        if e.status_code == status.HTTP_401_UNAUTHORIZED:  # só a senha errada entra no registro
            acessos.registrar(db, request, acao="recusado", user=usuario, ok=False,
                              motivo="troca de papel: senha errada")
        raise
    from app.services import duas_etapas
    if duas_etapas.exigida(destino):                       # a conta que exige o código pede o código, venha de onde vier
        if not duas_etapas.ativa(destino):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Esta conta ainda não cadastrou a verificação em duas etapas: entre nela pelo login "
                                "uma vez para cadastrar o autenticador.")
        if duas_etapas.bloqueada(destino):                 # o limite da CONTA de destino, de qualquer lugar
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, acessos.BARRADO)
        if not (body.codigo or "").strip():                # sem código não é palpite: pede, sem contar erro (senão
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,   # 10 cliques travavam o código do gerente)
                                "Informe o código do autenticador desta conta"
                                + (" e a senha." if destino.perfil in pessoas.DA_PLATAFORMA else "."))
        if not duas_etapas.conferir(destino, body.codigo):
            db.rollback()
            acessos.contar_erro(request, chave)
            duas_etapas.errou(db, request, destino)
            acessos.registrar(db, request, acao="recusado", user=usuario, ok=False,
                              motivo="troca de papel: código da verificação em duas etapas errado")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "Para entrar nesta conta, informe o código do autenticador dela"
                                + (" e a senha." if destino.perfil in pessoas.DA_PLATAFORMA else "."))
        db.commit()
    acessos.registrar(db, request, acao="entrou", user=destino, por=usuario,   # `por`: a conta de onde veio
                      motivo=f"trocou de papel, para o {acessos.PORTAO[pessoas.escopo_do_perfil(destino.perfil)]}")
    token, expira = pessoas.emitir(destino)
    return TrocaOut(
        token=token,
        expira_em=expira,
        apelido=destino.apelido,
        nome=destino.nome,
        escopo=pessoas.escopo_do_perfil(destino.perfil),
        perfil=destino.perfil.value,
        empresa=pessoas.nome_da_empresa(db, destino),
    )


class SenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str


@router.post("/sair", status_code=204)
def sair(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> None:
    """Sair: a sessão deste token deixa de valer no servidor (não só no aparelho). Sessão que já venceu ou sem número
    (de antes das sessões) não dá erro: sair é sempre possível."""
    from app.models.sessao import SessaoGS
    from app.services import sessoes
    try:
        usuario, dados = _sessao(cred, db, aceita_entrada=True)
    except HTTPException:
        return
    sid = dados.get("sid")
    s = db.get(SessaoGS, sid[:32]) if isinstance(sid, str) else None
    if s is not None and s.gs_user_id == usuario.id:
        sessoes.encerrar(db, s, por=usuario, motivo="saiu")
        db.commit()


class SessaoNovaOut(BaseModel):
    """A sessão nova DESTE aparelho depois de trocar a senha (as outras foram encerradas), do mesmo portão."""
    token: str
    expira_em: datetime


@router.post("/senha", response_model=SessaoNovaOut)
def trocar_a_propria_senha(
    body: SenhaIn, cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db),
    request: Request = None,
) -> SessaoNovaOut:
    """Trocar a PRÓPRIA senha, venha a sessão do portão que vier.

    Existia só para o cliente (`/api/v1/auth/trocar-senha`, que recusa sessão com escopo),
    então quem administra a plataforma e quem gerencia uma empresa não tinha como trocar a
    própria senha pela tela — a única saída era pedir a outro administrador, ou o banco. É
    especialmente ruim para a conta que nasce com senha provisória: ela fica com a senha
    que alguém digitou e viu.

    **Exige a senha atual mesmo com a sessão autenticada**, pela mesma razão da rota do
    app: um computador destravado e esquecido não deve bastar para trocar a senha e
    trancar o dono para fora.

    Senha trocada encerra TODAS as sessões (a de quem roubou a senha, as dos sistemas, a ligação do Claude), e este
    aparelho segue com a sessão nova que volta aqui, do mesmo portão (R12).
    """
    usuario, dados = _sessao(cred, db, request=request)
    if not conferir_senha(body.senha_atual, usuario.senha_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A senha atual não confere.")
    if len(body.senha_nova) < 8:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A senha nova precisa de pelo menos 8 caracteres."
        )
    if body.senha_nova == body.senha_atual:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A senha nova precisa ser diferente da atual."
        )

    usuario.senha_hash = gerar_hash_senha(body.senha_nova)
    # Fecha o ciclo da senha provisória também aqui: sem isto, a conta que trocou pela
    # tela do painel continuaria sendo empurrada para a troca no aplicativo.
    usuario.trocar_senha = False
    from app.services import acessos, sessoes
    sessoes.encerrar_todas(db, usuario, por=usuario, motivo="trocou a própria senha")
    db.commit()
    acessos.registrar(db, request, acao="senha", user=usuario,
                      motivo="trocou a própria senha; as outras sessões foram encerradas")
    escopo, empresa = dados.get("escopo"), dados.get("empresa")
    token, expira = (criar_token_painel(usuario.id) if escopo == "painel"
                     else criar_token_empresa(usuario.id, empresa) if escopo == "empresa"
                     else criar_token_tecnico(usuario.id, empresa) if escopo == "tecnico"
                     else criar_token(usuario.id))
    return SessaoNovaOut(token=token, expira_em=expira)


# ── um usuário em mais de uma empresa ───────────────────────────────────────


class EmpresaDaContaOut(BaseModel):
    id: int
    nome: str
    ativa: bool
    #: A empresa que cuida da CONTA (senha, celular, tokens e bot).
    origem: bool
    #: A que esta sessão está operando.
    atual: bool


@router.get("/empresas", response_model=list[EmpresaDaContaOut])
def empresas_da_sessao(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db), request: Request = None
) -> list[EmpresaDaContaOut]:
    """As empresas desta conta — o seletor "Trocar empresa" do oem-gs só aparece com duas ou mais."""
    usuario, dados = _sessao(cred, db, request=request)
    atual = dados.get("empresa") or usuario.empresa_id
    ids = empresas.empresas_da_conta(db, usuario)
    por_id = {e.id: e for e in db.scalars(select(Empresa).where(Empresa.id.in_(ids))).all()}
    return [
        EmpresaDaContaOut(
            id=i, nome=por_id[i].nome, ativa=por_id[i].ativa,
            origem=i == usuario.empresa_id, atual=i == atual,
        )
        for i in ids
        if i in por_id
    ]


class TrocaDeEmpresaIn(BaseModel):
    empresa_id: int


@router.post("/empresa", response_model=TrocaOut)
def trocar_de_empresa(
    body: TrocaDeEmpresaIn,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> TrocaOut:
    """Passa a operar OUTRA empresa da mesma conta — o gerente (ou o técnico) de mais de uma
    O&M. A sessão nova vale para a empresa escolhida; a guarda confere a cada requisição
    que a conta continua sendo de lá."""
    usuario, dados = _sessao(cred, db, request=request)
    escopo = dados.get("escopo")
    if escopo not in ("empresa", "tecnico"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Só o gerente e o técnico trocam de empresa.")
    if body.empresa_id not in empresas.empresas_da_conta(db, usuario):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta conta não é desta empresa.")
    empresa = empresas.por_id(db, body.empresa_id)
    if not empresa.ativa:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta empresa está desligada.")

    outra = None if body.empresa_id == usuario.empresa_id else body.empresa_id
    emitir = criar_token_empresa if escopo == "empresa" else criar_token_tecnico
    token, expira = emitir(usuario.id, outra)
    return TrocaOut(
        token=token, expira_em=expira, apelido=usuario.apelido, nome=usuario.nome,
        escopo=escopo, perfil=usuario.perfil.value, empresa=empresa.nome,
    )


# ─────────────────────── "Entrar com o Gestão Solar" no meuGuarda ───────────────────────
#
# Pedido do dono (11/11/2026): "eu clico, o Gestão Solar autentica e boa". A página `/entrar/meuguarda?volta=` dos três
# portões (gs, oem-gs, adm-gs) chama esta rota com a sessão daquele portão e manda o navegador para a `volta` com a
# asserção no FRAGMENTO (`#assercao=`), como o `entrar_no_produto` do meuWatt e do meuPlano. Mora aqui porque é a rota
# que atravessa os portões e não devolve dado: só diz QUEM está falando — e de qual portão.

#: Para onde o passe de cada sistema pode ir, e o nome que a tela mostra: a lista mora em `login_externo.SISTEMAS`
#: (fixa: um `volta` livre seria redirecionamento aberto, e o passe iria parar no site de quem montou o link).
from app.services.login_externo import SISTEMAS as VOLTAS  # noqa: E402


def _volta(produto: str, volta: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    nome, hosts = VOLTAS[produto]
    try:
        u = urlsplit((volta or "").strip())
        valida = u.scheme == "https" and u.netloc in hosts
    except ValueError:
        valida = False
    if not valida:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Esse endereço de volta não é do {nome}.")
    return urlunsplit(("https", u.netloc, u.path or "/", u.query, ""))


def _escopo(cred: HTTPAuthorizationCredentials | None) -> str | None:
    """O escopo de um token que já passou por `_sessao`."""
    return jwt.get_unverified_claims(cred.credentials).get("escopo") if cred else None


def _conta_do_portao(cred: HTTPAuthorizationCredentials | None, db: Session,
                     request: Request | None = None) -> tuple[User, str]:
    """A conta e o portão da sessão, conferidos pela GUARDA daquele portão (empresa ativa, perfil, empresa da sessão):
    a do meuGuarda não pode ser mais frouxa que a do próprio portão."""
    from app.core.security import _empresa_ativa, gestor_atual, gestor_empresa_atual, tecnico_atual, usuario_atual

    usuario, dados = _sessao(cred, db, aceita_entrada=True, request=request)
    escopo = dados.get("escopo")
    if escopo == "entrada":                                # a do gestao.solar: o portão vem do perfil
        _empresa_ativa(db, usuario)
        return usuario, pessoas.escopo_do_perfil(usuario.perfil)
    guarda = {None: usuario_atual, "empresa": gestor_empresa_atual, "tecnico": tecnico_atual,
              "painel": gestor_atual}.get(escopo)
    if guarda is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    return guarda(cred, db), escopo or "cliente"


def _entradas() -> dict[str, str]:
    """Onde cada sistema recebe o passe (os botões dos portões mandam para cá, já logado)."""
    from app.services.login_externo import entradas
    return entradas()


def _passe(db: Session, usuario: User, produto: str, portao: str, empresa: int | None) -> str:
    """O passe daquele sistema: o meuWatt e o meuPlano pela asserção de sempre (`assinar`), o meuGuarda e o
    TermoVision pela do login (`assinar_login`); os quatro com o passe v2 (login, perfil, empresa e usinas)."""
    from app.models.integracao import Produto
    from app.services import login_externo

    if produto in login_externo.SO_LOGIN:
        meuplano_id = login_externo.meuplano_id_de(db, usuario.id) if produto == login_externo.TERMOVISION else None
        return login_externo.assinar_login(usuario, produto, portao, empresa, meuplano_id, db=db)
    return login_externo.assinar(usuario, Produto(produto), db=db, empresa_id=empresa)


class ProdutoOut(BaseModel):
    produto: str
    nome: str
    #: A `volta` para o `POST /api/sessao/{produto}`: a entrada do produto.
    url: str
    #: Abrir a `url` DIRETO, sem passe (o helper: http só pela VPN; a pessoa entra lá com o login do GS).
    direto: bool = False


@router.get("/produtos", response_model=list[ProdutoOut])
def produtos_da_sessao(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db), request: Request = None
) -> list[ProdutoOut]:
    """Os produtos que esta pessoa abre pelo Gestão Solar (o gerente liberou): os botões dos três portões."""
    usuario, _ = _conta_do_portao(cred, db, request)
    entradas = _entradas()
    from app.core.config import get_settings
    from app.services.login_externo import liberados
    lista = [ProdutoOut(produto=p, nome=VOLTAS[p][0], url=entradas[p]) for p in liberados(usuario)]
    # o helper: para quem o gerente liberou o helper no bot e que entra no meuWatt (o helper loga pelo meuWatt)
    if usuario.bot_helper and usuario.entra_no_meuwatt:
        lista.append(ProdutoOut(produto="helper", nome="helper", url=f"{get_settings().helper_web_url.rstrip('/')}/",
                                direto=True))
    return lista


class EntrarIn(BaseModel):
    volta: str


class EntrarOut(BaseModel):
    #: vazio quando falta o código da verificação em duas etapas (`duas_etapas`, R12)
    url: str = ""
    #: A sessão de ENTRADA do gestao.solar (nova a cada uso: a validade corre do último uso), quando a pessoa entrou
    #: com a senha ali ou veio com ela. Só gera asserção: nenhum portão a aceita.
    entrada: str | None = None
    entrada_expira_em: datetime | None = None
    duas_etapas: DuasEtapasOut | None = None


class EntrarComSenhaIn(BaseModel):
    apelido: str
    senha: str
    volta: str


@router.get("/{produto}/volta", status_code=204)
def conferir_volta(produto: str, volta: str) -> None:
    """A página de entrar confere o endereço de volta AO ABRIR (24/11/2026, achado do meuPlano): com um endereço que não
    é do sistema, ela nem mostra o formulário. A conferência que vale continua sendo a da entrega do passe."""
    if produto not in VOLTAS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    _volta(produto, volta)


@router.post("/{produto}/com-senha", response_model=EntrarOut)
def entrar_no_produto_com_senha(produto: str, body: EntrarComSenhaIn, db: Session = Depends(get_db),
                                request: Request = None) -> EntrarOut:
    """A entrada ÚNICA do produto, para QUALQUER conta (equipe da O&M, dono de usina, plataforma), em
    `gestao.solar/entrar/<produto>` sem sessão: o apelido e a senha do GS, e a asserção já na `volta`. Pedido do dono
    (pelo TermoVision, 11/11/2026): "no final é tudo o mesmo login: a tela principal deve aceitar todos". O portão vem
    do perfil, como na tela de entrar do próprio produto (`auth.assercao_para_produto`)."""
    from app.core.security import _empresa_ativa
    from app.services import acessos, login_externo, pessoas

    if produto not in VOLTAS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    volta = _volta(produto, body.volta)
    usuario = acessos.entrar_ou_recusar(db, request, body.apelido, body.senha, sistema=produto)  # login ou e-mail
    _empresa_ativa(db, usuario)
    from app.services import duas_etapas
    if duas_etapas.exigida(usuario):                       # R12: o gerente e a plataforma passam pelo código
        from app.api.v1.painel import pedir_codigo
        return EntrarOut(duas_etapas=pedir_codigo(db, usuario, f"produto:{produto}"))
    return _passe_com_entrada(db, request, usuario, produto, volta, body.apelido, "entrada do GS com login e senha")


class CodigoDaEntradaIn(BaseModel):
    desafio: str
    codigo: str
    volta: str


@router.post("/{produto}/com-senha/codigo", response_model=EntrarOut)
def entrar_no_produto_com_codigo(produto: str, body: CodigoDaEntradaIn, db: Session = Depends(get_db),
                                 request: Request = None) -> EntrarOut:
    """O segundo passo da entrada única: o código do autenticador."""
    from app.api.v1.painel import CodigoIn, conta_do_codigo
    from app.core.security import _empresa_ativa

    if produto not in VOLTAS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    volta = _volta(produto, body.volta)
    usuario = conta_do_codigo(db, request, CodigoIn(desafio=body.desafio, codigo=body.codigo), f"produto:{produto}")
    _empresa_ativa(db, usuario)
    return _passe_com_entrada(db, request, usuario, produto, volta, usuario.apelido,
                              "entrada do GS com login, senha e a verificação em duas etapas")


def _passe_com_entrada(db: Session, request: Request | None, usuario: User, produto: str, volta: str, login: str,
                       motivo: str) -> EntrarOut:
    from app.services import acessos, login_externo, pessoas
    try:
        assercao = _passe(db, usuario, produto, pessoas.escopo_do_perfil(usuario.perfil), usuario.empresa_id)
    except login_externo.SemChave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    usuario.ultimo_login = datetime.now(UTC)
    db.commit()
    acessos.registrar(db, request, acao="passe", sistema=produto, user=usuario, login=login, motivo=motivo)
    entrada, expira = criar_token_entrada(usuario.id)
    return EntrarOut(url=f"{volta}#assercao={assercao}", entrada=entrada, entrada_expira_em=expira)


@router.post("/{produto}", response_model=EntrarOut)
def entrar_no_produto(
    produto: str,
    body: EntrarIn,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> EntrarOut:
    """A asserção do produto (meuGuarda, TermoVision) para quem está logado aqui, no endereço de volta dele. Declarada
    por ÚLTIMO neste arquivo: as rotas fixas de cima (`/trocar`, `/senha`…) vêm antes dela."""
    from app.services import acessos, login_externo

    if produto not in VOLTAS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    volta = _volta(produto, body.volta)
    usuario, portao = _conta_do_portao(cred, db, request)
    empresa = getattr(usuario, "empresa_da_sessao", None) or usuario.empresa_id
    try:
        assercao = _passe(db, usuario, produto, portao, empresa)
    except login_externo.SemChave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    acessos.registrar(db, request, acao="passe", sistema=produto, user=usuario,
                      motivo=f"já dentro do GS ({acessos.PORTAO.get('entrada' if _escopo(cred) == 'entrada' else portao, portao)})")
    if _escopo(cred) == "entrada":                          # renova: 30 dias a partir do último uso, a MESMA sessão
        sid = jwt.get_unverified_claims(cred.credentials).get("sid")   # já conferido em `_sessao`
        entrada, expira = criar_token_entrada(usuario.id, sid=sid if isinstance(sid, str) else None)
        from app.models.sessao import SessaoGS
        linha = db.get(SessaoGS, sid[:32]) if isinstance(sid, str) and sid else None
        if linha is not None:
            linha.expira_em = expira
            db.commit()
        return EntrarOut(url=f"{volta}#assercao={assercao}", entrada=entrada, entrada_expira_em=expira)
    return EntrarOut(url=f"{volta}#assercao={assercao}")
