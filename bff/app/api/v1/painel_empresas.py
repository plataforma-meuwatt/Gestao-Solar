"""Empresas de O&M — a tela da PLATAFORMA que cria e desliga inquilino.

Fica em `/api/painel/*` porque é da plataforma: quem abre isto vê a lista inteira de
empresas, e nenhuma delas deve saber que as outras existem. A área é `empresas`, do grupo
Sistema, pelo mesmo motivo de `conexoes`: criar inquilino é decisão de quem administra.

**Desligar, não apagar.** `ativa=false` tira a empresa de operação — o gerente dela para
de entrar na requisição seguinte — e preserva usina, cliente e histórico. Apagar levaria
junto o que alguém ainda precisa auditar, e a chave estrangeira é `RESTRICT` justamente
para o banco recusar a tentativa em vez de arrastar o resto.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.apelido import ApelidoInvalido, normalizar as normalizar_apelido
from app.core.security import exige_area, gerar_hash_senha, gerar_senha_provisoria
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import empresas as svc
from app.services import pessoas

router = APIRouter(prefix="/api/painel", tags=["painel · empresas"])

EXIGE_EMPRESAS = exige_area("empresas")


class EmpresaOut(BaseModel):
    id: int
    nome: str
    documento: str | None = None
    ativa: bool
    #: Contagens para a lista responder "posso desligar?" sem abrir a empresa.
    usuarios: int = 0
    usinas: int = 0
    #: Para qual empresa de cada produto esta linha aponta. Sem nenhum dos dois ela é
    #: fantasma: aparece na lista e todas as telas dela vêm vazias.
    mw_enterprise_id: int | None = None
    mp_tenant_id: int | None = None


def _saida(db: Session, e: Empresa) -> EmpresaOut:
    return EmpresaOut(
        id=e.id,
        nome=e.nome,
        documento=e.documento,
        ativa=e.ativa,
        mw_enterprise_id=e.mw_enterprise_id,
        mp_tenant_id=e.mp_tenant_id,
        usuarios=db.scalar(
            select(func.count()).select_from(User).where(User.empresa_id == e.id)
        )
        or 0,
        usinas=db.scalar(
            select(func.count()).select_from(PlantLink).where(PlantLink.empresa_id == e.id)
        )
        or 0,
    )


@router.get("/empresas", response_model=list[EmpresaOut])
def listar(
    db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> list[EmpresaOut]:
    empresas = db.scalars(select(Empresa).order_by(Empresa.nome)).all()
    return [_saida(db, e) for e in empresas]


class EmpresaIn(BaseModel):
    nome: str
    documento: str | None = None


@router.post("/empresas", response_model=EmpresaOut, status_code=201)
def criar(
    body: EmpresaIn, db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> EmpresaOut:
    empresa = svc.criar(db, body.nome, body.documento)
    db.commit()
    return _saida(db, empresa)


class EmpresaPatch(BaseModel):
    nome: str | None = None
    documento: str | None = None
    ativa: bool | None = None


@router.patch("/empresas/{empresa_id}", response_model=EmpresaOut)
def editar(
    empresa_id: int,
    body: EmpresaPatch,
    db: Session = Depends(get_db),
    _gestor: User = Depends(EXIGE_EMPRESAS),
) -> EmpresaOut:
    empresa = svc.por_id(db, empresa_id)
    if body.nome is not None:
        empresa.nome = body.nome.strip() or empresa.nome
    if body.documento is not None:
        empresa.documento = body.documento.strip() or None
    if body.ativa is not None:
        empresa.ativa = body.ativa
    db.commit()
    return _saida(db, empresa)


# ------------------------------------------------------------------- carteira


class ItemDaCarteira(BaseModel):
    id: int
    nome: str
    detalhe: str | None = None
    #: De qual empresa é hoje. `null` = de ninguém — o estado de tudo o que existia antes
    #: do multiempresa, e o motivo de esta tela existir.
    empresa_id: int | None = None
    empresa_nome: str | None = None


class CarteiraOut(BaseModel):
    usinas: list[ItemDaCarteira]
    clientes: list[ItemDaCarteira]


def _nomes(db: Session) -> dict[int, str]:
    return {e.id: e.nome for e in db.scalars(select(Empresa)).all()}


@router.get("/empresas/{empresa_id}/carteira", response_model=CarteiraOut)
def carteira(
    empresa_id: int, db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> CarteiraOut:
    """Tudo o que PODE ser atribuído, com o dono atual de cada item ao lado.

    A lista é a do sistema inteiro, e não só a desta empresa, porque a pergunta que a tela
    responde é "de quem é o quê" — e mostrar apenas o que já é dela esconderia exatamente
    o que falta atribuir. O dono atual vem escrito: mudar usina de empresa é uma decisão,
    não um clique distraído.

    # ponytail: carrega tudo de uma vez. Com 17 usinas e 7 clientes é uma consulta; se um
    # dia forem milhares, isto vira busca paginada — e aí a tela também muda.
    """
    svc.por_id(db, empresa_id)  # 404 se a empresa não existe
    nomes = _nomes(db)

    usinas = [
        ItemDaCarteira(
            id=u.id,
            nome=u.nome,
            detalhe=" · ".join(p for p in (u.cidade, u.uf) if p) or None,
            empresa_id=u.empresa_id,
            empresa_nome=nomes.get(u.empresa_id) if u.empresa_id else None,
        )
        for u in db.scalars(select(PlantLink).order_by(PlantLink.nome)).all()
    ]
    clientes = [
        ItemDaCarteira(
            id=c.id,
            nome=c.nome,
            detalhe=c.apelido,
            empresa_id=c.empresa_id,
            empresa_nome=nomes.get(c.empresa_id) if c.empresa_id else None,
        )
        for c in db.scalars(
            select(User).where(User.perfil.in_([Perfil.CLIENTE, Perfil.GESTOR_EMPRESA])).order_by(User.nome)
        ).all()
    ]
    return CarteiraOut(usinas=usinas, clientes=clientes)


class CarteiraIn(BaseModel):
    #: As listas COMPLETAS do que passa a ser desta empresa. O que sai delas fica **sem
    #: dono** — e não volta para outra empresa por conta própria, porque adivinhar o
    #: destino de um item removido seria decidir no lugar de quem decide.
    usinas: list[int]
    clientes: list[int]


@router.put("/empresas/{empresa_id}/carteira", response_model=CarteiraOut)
def salvar_carteira(
    empresa_id: int,
    body: CarteiraIn,
    db: Session = Depends(get_db),
    _gestor: User = Depends(EXIGE_EMPRESAS),
) -> CarteiraOut:
    """Grava de quem é o quê.

    Duas regras que não devem ser "simplificadas":

    - **Só mexe no que é desta empresa ou de ninguém.** Um item que pertence a OUTRA
      empresa é ignorado em silêncio, e é assim de propósito: a tela mostra o dono atual
      ao lado de cada linha, então marcar o item de outro é engano, e um engano não pode
      transferir carteira. Para mudar de dono, tira-se lá e põe-se aqui — dois passos,
      duas decisões.
    - **Tirar da lista deixa sem dono, não em outra empresa.** É reversível e visível: o
      item volta a aparecer como "de ninguém" na próxima abertura da tela.
    """
    svc.por_id(db, empresa_id)

    # Conta da PLATAFORMA nunca ganha empresa por aqui. Sem este filtro, marcar um
    # administrador em `clientes` gravava `empresa_id` nele — e a partir daí ele aparecia
    # na lista do gerente daquela empresa, que trocava a senha dele e entrava no painel
    # como administrador. A guarda em `_conta_da_empresa` fecha a saída; esta fecha a
    # entrada, para o estado nem existir. (Revisão adversarial, 30/09/2026.)
    for modelo, coluna, escolhidos, extra in (
        (PlantLink, PlantLink.empresa_id, set(body.usinas), []),
        (User, User.empresa_id, set(body.clientes), [User.perfil.not_in(pessoas.DA_PLATAFORMA)]),
    ):
        for item in db.scalars(
            select(modelo).where(coluna.is_(None) | (coluna == empresa_id), *extra)
        ).all():
            item.empresa_id = empresa_id if item.id in escolhidos else None

    db.commit()
    return carteira(empresa_id, db=db, _gestor=_gestor)


# -------------------------------------------------------------------- gerente


class GerenteIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None
    #: "Esta conta é minha": agrupa a conta nova com a de quem está criando, e é o que faz
    #: o seletor "Trocar papel" aparecer. Sem isso, quem administra a plataforma e também
    #: gerencia uma empresa teria de sair e entrar de novo a cada troca — que é justamente
    #: o que o agrupamento existe para evitar.
    minha: bool = False


class GerenteOut(BaseModel):
    id: int
    nome: str
    apelido: str
    #: A conta nova ficou no seu grupo de papéis — o seletor "Trocar papel" já a mostra.
    agrupada: bool = False
    #: A senha provisória, mostrada UMA vez. Não é guardada em texto e não há como
    #: recuperá-la: quem perder, redefine. É o mesmo desenho da senha do cliente.
    senha: str


@router.post("/empresas/{empresa_id}/gerente", response_model=GerenteOut, status_code=201)
def criar_gerente(
    empresa_id: int,
    body: GerenteIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_EMPRESAS),
) -> GerenteOut:
    """Cria o gerente DESTA empresa.

    O gerente nasce aqui, e não na tela de Usuários do sistema, porque lá ele nasceria sem
    empresa — e uma conta de inquilino sem vínculo não entra em lugar nenhum
    (`gestor_empresa_atual` a recusa). Seria uma conta que parece pronta e não abre nada.
    Aqui o vínculo é obrigatório por construção: a empresa é o caminho da rota.

    A senha sai na resposta e some depois: é entregue ao gerente junto com o **apelido**,
    que é o que autentica. Mandar o e-mail junto convidaria a tentar entrar com ele, que é
    exatamente o que não funciona.
    """
    empresa = svc.por_id(db, empresa_id)

    try:
        apelido = normalizar_apelido(body.apelido)
    except ApelidoInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if db.scalar(select(User).where(User.apelido == apelido)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"O apelido “{apelido}” já está em uso.")

    senha = gerar_senha_provisoria()
    gerente = User(
        apelido=apelido,
        email=str(body.email).strip().lower() if body.email else None,
        nome=body.nome.strip(),
        perfil=Perfil.GESTOR_EMPRESA,
        empresa_id=empresa.id,
        senha_hash=gerar_hash_senha(senha),
    )
    db.add(gerente)
    db.flush()

    if body.minha:
        # Agrupar na hora, e não numa segunda tela: quem marca isto está dizendo "sou eu",
        # e obrigá-lo a repetir a informação em Usuários do sistema é o tipo de passo que
        # se esquece — a conta fica criada e o seletor de papel não aparece.
        pessoas.agrupar(db, [gestor, gerente], gestor.nome)

    db.commit()
    db.refresh(gerente)

    return GerenteOut(
        id=gerente.id,
        nome=gerente.nome,
        apelido=gerente.apelido,
        senha=senha,
        agrupada=body.minha,
    )


class UsuarioDaEmpresaOut(BaseModel):
    id: int
    nome: str
    apelido: str
    perfil: str
    ativo: bool
    #: Se esta conta está no MEU grupo de papéis — é a que aparece em "Trocar papel".
    minha: bool = False


@router.get("/empresas/{empresa_id}/usuarios", response_model=list[UsuarioDaEmpresaOut])
def usuarios_da_empresa(
    empresa_id: int, db: Session = Depends(get_db), gestor: User = Depends(EXIGE_EMPRESAS)
) -> list[UsuarioDaEmpresaOut]:
    """Quem é desta empresa — gerentes e clientes.

    A plataforma gere o gerente AQUI, e não em Usuários do sistema: aquela tela é do staff
    da plataforma, e misturar as duas coisas já deixava um clique errado promover o gerente
    de um inquilino a administrador do sistema inteiro.
    """
    svc.por_id(db, empresa_id)
    return [
        UsuarioDaEmpresaOut(
            id=u.id,
            nome=u.nome,
            apelido=u.apelido,
            perfil=u.perfil.value,
            ativo=u.ativo,
            minha=gestor.pessoa_id is not None and u.pessoa_id == gestor.pessoa_id,
        )
        for u in db.scalars(
            select(User).where(User.empresa_id == empresa_id).order_by(User.nome)
        ).all()
    ]


class UsuarioPatch(BaseModel):
    ativo: bool | None = None
    #: Define uma senha nova. Some da resposta: quem a define é quem a entrega.
    senha: str | None = None


@router.patch("/empresas/{empresa_id}/usuarios/{usuario_id}", response_model=UsuarioDaEmpresaOut)
def editar_usuario_da_empresa(
    empresa_id: int,
    usuario_id: int,
    body: UsuarioPatch,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_EMPRESAS),
) -> UsuarioDaEmpresaOut:
    """Desativa, reativa ou redefine a senha de quem é da empresa.

    **Só mexe em quem é DESTA empresa** — o id vem da URL e a conta é conferida contra ele.
    Sem essa checagem, trocar o número na barra de endereço redefiniria a senha de qualquer
    conta do sistema a partir de uma tela de empresa.
    """
    svc.por_id(db, empresa_id)
    alvo = db.get(User, usuario_id)
    if alvo is None or alvo.empresa_id != empresa_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada nesta empresa.")
    if alvo.perfil in (Perfil.ATENDIMENTO, Perfil.ADMINISTRADOR):
        # Conta da plataforma com empresa gravada (acontece: um administrador que também é
        # dono de usina). Ela não se administra por aqui.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Esta é uma conta da plataforma. Administre-a em Usuários do sistema.",
        )

    if body.ativo is not None:
        alvo.ativo = body.ativo
    if body.senha:
        if len(body.senha) < 8:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A senha precisa de pelo menos 8 caracteres."
            )
        alvo.senha_hash = gerar_hash_senha(body.senha)
    db.commit()

    return UsuarioDaEmpresaOut(
        id=alvo.id,
        nome=alvo.nome,
        apelido=alvo.apelido,
        perfil=alvo.perfil.value,
        ativo=alvo.ativo,
        minha=gestor.pessoa_id is not None and alvo.pessoa_id == gestor.pessoa_id,
    )


@router.put("/empresas/{empresa_id}/gerente/{apelido}", response_model=UsuarioDaEmpresaOut)
def tornar_gerente(
    empresa_id: int,
    apelido: str,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_EMPRESAS),
) -> UsuarioDaEmpresaOut:
    """Faz de uma conta JÁ EXISTENTE o gerente desta empresa.

    Existe porque "criar gerente" não serve para quem já está no sistema: a conta traz
    usinas concedidas, tokens de produto e histórico, e recriá-la perderia tudo isso.

    **A própria conta é recusada.** Quem administra a plataforma e se rebaixasse a gerente
    perderia o painel no mesmo instante — e a única saída seria outro administrador ou o
    banco. O caminho certo é ter uma conta para cada papel.
    """
    svc.por_id(db, empresa_id)
    conta = db.scalar(select(User).where(User.apelido == apelido.strip().lower()))
    if conta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada.")
    if conta.id == gestor.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Você perderia o painel no mesmo instante. Use uma conta separada para o "
            "papel de gerente.",
        )

    conta.perfil = Perfil.GESTOR_EMPRESA
    conta.empresa_id = empresa_id
    db.commit()

    return UsuarioDaEmpresaOut(
        id=conta.id,
        nome=conta.nome,
        apelido=conta.apelido,
        perfil=conta.perfil.value,
        ativo=conta.ativo,
        minha=gestor.pessoa_id is not None and conta.pessoa_id == gestor.pessoa_id,
    )


class ContaLivreOut(BaseModel):
    apelido: str
    nome: str
    perfil: str
    empresa: str | None = None


@router.get("/contas-livres", response_model=list[ContaLivreOut])
def contas_livres(
    db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> list[ContaLivreOut]:
    """Contas que podem virar gerente de uma empresa.

    Mostra TODAS as que não são da plataforma, com a empresa atual ao lado quando houver:
    esconder as que já têm empresa faria a tela mentir sobre quem existe, e mover alguém de
    uma empresa para outra é uma decisão legítima de quem administra.
    """
    empresas = {e.id: e.nome for e in db.scalars(select(Empresa)).all()}
    return [
        ContaLivreOut(
            apelido=u.apelido,
            nome=u.nome,
            perfil=u.perfil.value,
            empresa=empresas.get(u.empresa_id) if u.empresa_id else None,
        )
        for u in db.scalars(
            select(User)
            .where(User.perfil.in_([Perfil.CLIENTE, Perfil.GESTOR_EMPRESA]))
            .order_by(User.nome)
        ).all()
    ]
