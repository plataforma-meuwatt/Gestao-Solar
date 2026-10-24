"""Empresas de O&M — a tela da PLATAFORMA que cria e desliga inquilino.

Fica em `/api/painel/*` porque é da plataforma: quem abre isto vê a lista inteira de
empresas, e nenhuma delas deve saber que as outras existem. A área é `empresas`, do grupo
Sistema, pelo mesmo motivo de `conexoes`: criar inquilino é decisão de quem administra.

**Desligar, não apagar.** `ativa=false` tira a empresa de operação — o gerente dela para
de entrar na requisição seguinte — e preserva usina, cliente e histórico. Apagar levaria
junto o que alguém ainda precisa auditar, e a chave estrangeira é `RESTRICT` justamente
para o banco recusar a tentativa em vez de arrastar o resto.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.apelido import ApelidoInvalido, normalizar as normalizar_apelido
from app.core.security import exige_area, gerar_hash_senha, gerar_senha_provisoria
from app.core.telefone import exibir as exibir_telefone
from app.models.empresa import Empresa, MembroDaEmpresa
from app.models.integracao import Integracao, Produto
from app.models.plant import PlantLink
from app.models.user import BOT_TOKEN, Perfil, User, UserPlantAccess, VinculoProduto
from app.services import empresas as svc
from app.services import pessoas

router = APIRouter(prefix="/api/painel", tags=["painel · empresas"])

EXIGE_EMPRESAS = exige_area("empresas")


class EmpresaOut(BaseModel):
    id: int
    nome: str
    documento: str | None = None
    ativa: bool
    #: Quem é da empresa (de origem ou também dela), por papel — a lista responde "quem
    #: está aqui dentro?" sem abrir a empresa.
    usuarios: int = 0
    gerentes: int = 0
    tecnicos: int = 0
    donos: int = 0
    usinas: int = 0
    #: Para qual empresa de cada produto esta linha aponta. Sem nenhum dos dois ela é
    #: fantasma: aparece na lista e todas as telas dela vêm vazias.
    mw_enterprise_id: int | None = None
    mp_tenant_id: int | None = None
    #: O estado da conta DA EMPRESA em cada produto (`ok` · `falhou` · `nunca`), ou nulo se
    #: o gerente ainda não conectou. Só o estado: o token é dela, e o adm não tem token.
    conexao_meuwatt: str | None = None
    conexao_meuplano: str | None = None


def _saida(db: Session, e: Empresa) -> EmpresaOut:
    por_papel = dict(
        db.execute(
            select(User.perfil, func.count())
            .where(svc.contas_da_empresa(e.id), User.perfil.not_in(pessoas.DA_PLATAFORMA))
            .group_by(User.perfil)
        ).all()
    )
    conexoes = {
        i.produto: (i.estado.value if i.token_cifrado or i.senha_cifrada else None)
        for i in db.scalars(select(Integracao).where(Integracao.empresa_id == e.id)).all()
    }
    return EmpresaOut(
        id=e.id,
        nome=e.nome,
        documento=e.documento,
        ativa=e.ativa,
        mw_enterprise_id=e.mw_enterprise_id,
        mp_tenant_id=e.mp_tenant_id,
        conexao_meuwatt=conexoes.get(Produto.MEUWATT),
        conexao_meuplano=conexoes.get(Produto.MEUPLANO),
        usuarios=sum(por_papel.values()),
        gerentes=por_papel.get(Perfil.GESTOR_EMPRESA, 0),
        tecnicos=por_papel.get(Perfil.TECNICO, 0),
        donos=por_papel.get(Perfil.CLIENTE, 0),
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


@router.get("/empresas/{empresa_id}", response_model=EmpresaOut)
def detalhe(
    empresa_id: int, db: Session = Depends(get_db), _gestor: User = Depends(EXIGE_EMPRESAS)
) -> EmpresaOut:
    return _saida(db, svc.por_id(db, empresa_id))


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
    #: Ausente = não mexe nas contas. A tela da empresa põe e tira usuário pela lista de
    #: usuários dela (que sabe de quem é de mais de uma empresa); aqui fica só a usina.
    clientes: list[int] | None = None


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
        *(
            [(User, User.empresa_id, set(body.clientes), [User.perfil.not_in(pessoas.DA_PLATAFORMA)])]
            if body.clientes is not None
            else []
        ),
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
    """Uma conta, como a plataforma a vê: papel, empresas, celular, o bot e se a pessoa tem
    o token dela — nunca o token."""

    id: int
    nome: str
    apelido: str
    perfil: str
    ativo: bool
    email: str | None = None
    ultimo_login: datetime | None = None
    #: `(17) 9 9737-7626`
    telefone: str | None = None
    #: Usinas concedidas a esta pessoa (as desta empresa, quando a lista é de uma empresa).
    usinas: int = 0
    #: O que o gerente liberou no assistente (`bot_meuwatt`, `bot_meuplano`, `bot_helper`)
    #: e o que responde de fato — liberado E com o token PRÓPRIO da pessoa.
    bot: list[str] = []
    bot_ativo: list[str] = []
    #: Em quais produtos a pessoa tem o token DELA (`meuwatt`, `meuplano`). Só o fato — e de
    #: quem o produto disse que ele é (`tokens_de`), nunca o valor nem o prefixo.
    tokens: list[str] = []
    tokens_de: dict[str, str] = {}
    #: A empresa que cuida da conta, quando não é a desta lista (usuário em mais de uma).
    cuidada_por: str | None = None
    #: As OUTRAS empresas desta conta.
    outras_empresas: list[str] = []
    #: Se esta conta está no MEU grupo de papéis — é a que aparece em "Trocar papel".
    minha: bool = False


def resumo_das_contas(
    db: Session, contas: list[User], gestor: User, empresa_id: int | None = None,
    nomes: dict[int, str] | None = None, membro: dict[int, list[int]] | None = None,
) -> list[UsuarioDaEmpresaOut]:
    """A linha de cada conta, montada num lugar só para a lista da empresa e a lista de
    todos os usuários não divergirem. Com `empresa_id`, as usinas contadas são as dela.
    `nomes` e `membro` já lidos por quem chama poupam duas idas ao banco (~200 ms cada)."""
    if not contas:
        return []
    ids = [c.id for c in contas]
    if nomes is None:
        nomes = {e.id: e.nome for e in db.scalars(select(Empresa)).all()}
    if membro is None:
        membro = {}
        for uid, eid in db.execute(
            select(MembroDaEmpresa.user_id, MembroDaEmpresa.empresa_id)
            .where(MembroDaEmpresa.user_id.in_(ids))
            .order_by(MembroDaEmpresa.id)
        ).all():
            membro.setdefault(uid, []).append(eid)
    consulta = (
        select(UserPlantAccess.user_id, func.count())
        .join(PlantLink, PlantLink.id == UserPlantAccess.plant_link_id)
        .where(UserPlantAccess.user_id.in_(ids))
        .group_by(UserPlantAccess.user_id)
    )
    if empresa_id is not None:
        consulta = consulta.where(
            (PlantLink.empresa_id == empresa_id) | PlantLink.empresa_id.is_(None)
        )
    usinas = dict(db.execute(consulta).all())
    tokens: dict[int, list[str]] = {}
    tokens_de: dict[int, dict[str, str]] = {}
    for v in db.scalars(select(VinculoProduto).where(VinculoProduto.gs_user_id.in_(ids))).all():
        if v.token_cifrado:
            tokens.setdefault(v.gs_user_id, []).append(str(v.produto))
            tokens_de.setdefault(v.gs_user_id, {})[str(v.produto)] = (
                v.usuario_remoto_nome or v.usuario_remoto_email or f"id {v.usuario_remoto_id}"
            )

    saida = []
    for c in contas:
        todas = ([c.empresa_id] if c.empresa_id else []) + membro.get(c.id, [])
        saida.append(
            UsuarioDaEmpresaOut(
                id=c.id,
                nome=c.nome,
                apelido=c.apelido,
                perfil=c.perfil.value,
                ativo=c.ativo,
                email=c.email,
                ultimo_login=c.ultimo_login,
                telefone=exibir_telefone(c.telefone),
                usinas=usinas.get(c.id, 0),
                bot=[campo for campo in BOT_TOKEN if getattr(c, campo)],
                # O mesmo que `User.bot_ativo`, com os tokens já lidos acima (uma ida ao
                # banco para todas as contas, e não uma por conta).
                bot_ativo=sorted(
                    campo for campo, produto in BOT_TOKEN.items()
                    if getattr(c, campo) and produto in tokens.get(c.id, [])
                ) if c.telefone else [],
                tokens=sorted(tokens.get(c.id, [])),
                tokens_de=tokens_de.get(c.id, {}),
                cuidada_por=(
                    nomes.get(c.empresa_id)
                    if empresa_id is not None and c.empresa_id != empresa_id
                    else None
                ),
                outras_empresas=[nomes[e] for e in todas if e != empresa_id and e in nomes],
                minha=gestor.pessoa_id is not None and c.pessoa_id == gestor.pessoa_id,
            )
        )
    return saida


@router.get("/empresas/{empresa_id}/usuarios", response_model=list[UsuarioDaEmpresaOut])
def usuarios_da_empresa(
    empresa_id: int, db: Session = Depends(get_db), gestor: User = Depends(EXIGE_EMPRESAS)
) -> list[UsuarioDaEmpresaOut]:
    """Quem é desta empresa — gerentes, técnicos e donos de usina, inclusive quem é dela E
    de outra (usuário em mais de uma empresa).

    A plataforma gere o gerente AQUI, e não em Usuários do sistema: aquela tela é do staff
    da plataforma, e misturar as duas coisas já deixava um clique errado promover o gerente
    de um inquilino a administrador do sistema inteiro.
    """
    svc.por_id(db, empresa_id)
    contas = list(
        db.scalars(
            select(User)
            .where(svc.contas_da_empresa(empresa_id), User.perfil.not_in(pessoas.DA_PLATAFORMA))
            .order_by(User.nome)
        ).all()
    )
    return resumo_das_contas(db, contas, gestor, empresa_id)


class UsuarioPatch(BaseModel):
    ativo: bool | None = None
    #: Define uma senha nova. Some da resposta: quem a define é quem a entrega.
    senha: str | None = None
    #: O papel DENTRO da empresa: dono de usina, gerente ou técnico.
    perfil: Perfil | None = None


#: Os papéis que existem dentro de uma empresa. Os da plataforma não se dão por aqui.
PAPEIS_DA_EMPRESA = (Perfil.CLIENTE, Perfil.GESTOR_EMPRESA, Perfil.TECNICO)


def _conta_desta_empresa(db: Session, empresa_id: int, usuario_id: int) -> User:
    alvo = db.get(User, usuario_id)
    if alvo is None or empresa_id not in svc.empresas_da_conta(db, alvo):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada nesta empresa.")
    if alvo.perfil in (Perfil.ATENDIMENTO, Perfil.ADMINISTRADOR):
        # Conta da plataforma com empresa gravada (acontece: um administrador que também é
        # dono de usina). Ela não se administra por aqui.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Esta é uma conta da plataforma. Administre-a em Usuários.",
        )
    return alvo


@router.patch("/empresas/{empresa_id}/usuarios/{usuario_id}", response_model=UsuarioDaEmpresaOut)
def editar_usuario_da_empresa(
    empresa_id: int,
    usuario_id: int,
    body: UsuarioPatch,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_EMPRESAS),
) -> UsuarioDaEmpresaOut:
    """Desativa, reativa, redefine a senha ou muda o papel de quem é da empresa.

    **Só mexe em quem é DESTA empresa** — o id vem da URL e a conta é conferida contra ele.
    Sem essa checagem, trocar o número na barra de endereço redefiniria a senha de qualquer
    conta do sistema a partir de uma tela de empresa.
    """
    svc.por_id(db, empresa_id)
    alvo = _conta_desta_empresa(db, empresa_id, usuario_id)
    if body.ativo is False or (body.perfil is not None and body.perfil is not Perfil.GESTOR_EMPRESA):
        svc.exigir_outro_gerente_em_todas(db, alvo)

    if body.ativo is not None:
        alvo.ativo = body.ativo
    if body.senha:
        if len(body.senha) < 8:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A senha precisa de pelo menos 8 caracteres."
            )
        alvo.senha_hash = gerar_hash_senha(body.senha)
    if body.perfil is not None and body.perfil is not alvo.perfil:
        if body.perfil not in PAPEIS_DA_EMPRESA:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Dentro da empresa só existem dono de usina, gerente e técnico.",
            )
        if alvo.perfil is Perfil.CLIENTE and db.scalar(
            select(UserPlantAccess.id).where(UserPlantAccess.user_id == alvo.id).limit(1)
        ):
            # Gerente e técnico não recebem concessão (o gerente vê a carteira inteira; o
            # técnico, só o WhatsApp dele): trocar o papel com usina concedida deixaria a
            # concessão órfã, disputando a usina com o dono dela.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Esta pessoa ainda recebe usinas como dona. Tire as usinas dela antes de "
                "mudar o papel.",
            )
        alvo.perfil = body.perfil
    db.commit()
    return resumo_das_contas(db, [alvo], gestor, empresa_id)[0]


class NovoUsuarioIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None
    perfil: Perfil = Perfil.CLIENTE


class NovoUsuarioOut(BaseModel):
    id: int
    nome: str
    apelido: str
    #: A senha provisória, mostrada UMA vez — entregue com o APELIDO, que é o que autentica.
    senha: str


@router.post("/empresas/{empresa_id}/usuarios", response_model=NovoUsuarioOut, status_code=201)
def criar_usuario_da_empresa(
    empresa_id: int,
    body: NovoUsuarioIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_EMPRESAS),
) -> NovoUsuarioOut:
    """Cria um usuário DENTRO da empresa: dono de usina, gerente ou técnico. A empresa é o
    caminho da rota, então o vínculo é obrigatório por construção."""
    from app.services import clientes

    svc.por_id(db, empresa_id)
    if body.perfil not in PAPEIS_DA_EMPRESA:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Dentro da empresa só existem dono de usina, gerente e técnico.",
        )
    try:
        criado = clientes.criar(
            db,
            nome=body.nome,
            apelido=body.apelido,
            email=str(body.email) if body.email else None,
            empresa=None,
            criado_por=gestor,
        )
    except clientes.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    criado.usuario.empresa_id = empresa_id
    criado.usuario.perfil = body.perfil
    db.commit()
    return NovoUsuarioOut(
        id=criado.usuario.id,
        nome=criado.usuario.nome,
        apelido=criado.usuario.apelido,
        senha=criado.senha_provisoria,
    )


@router.put("/empresas/{empresa_id}/usuarios/{usuario_id}", response_model=UsuarioDaEmpresaOut)
def por_usuario_na_empresa(
    empresa_id: int,
    usuario_id: int,
    db: Session = Depends(get_db),
    gestor: User = Depends(EXIGE_EMPRESAS),
) -> UsuarioDaEmpresaOut:
    """Põe uma conta que JÁ EXISTE nesta empresa — sem tirar das outras (usuário em mais de
    uma empresa). Sem empresa nenhuma, esta passa a ser a de origem (a que cuida da conta)."""
    conta = db.get(User, usuario_id)
    if conta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada.")
    svc.por_na_empresa(db, conta, empresa_id, gestor)
    db.commit()
    return resumo_das_contas(db, [conta], gestor, empresa_id)[0]


@router.delete("/empresas/{empresa_id}/usuarios/{usuario_id}", status_code=204)
def tirar_usuario_da_empresa(
    empresa_id: int,
    usuario_id: int,
    db: Session = Depends(get_db),
    _gestor: User = Depends(EXIGE_EMPRESAS),
) -> None:
    """Tira a conta desta empresa — e as usinas que ela recebia daqui. A conta continua
    existindo (e nas outras empresas dela); não se apaga ninguém por esta tela."""
    conta = db.get(User, usuario_id)
    if conta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada.")
    svc.exigir_outro_gerente(db, empresa_id, conta)
    svc.tirar_da_empresa(db, conta, empresa_id)
    db.commit()


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

    return resumo_das_contas(db, [conta], gestor, empresa_id)[0]


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
