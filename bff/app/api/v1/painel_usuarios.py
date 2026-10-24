"""Usuários do sistema — quem opera o painel, e o que cada um abre.

Esta é a tela do **staff**, não a de clientes: aqui nascem as contas que entram em
`/entrar` do painel, com apelido e senha. Cliente é `painel_clientes.py`, e um não vira
o outro (`POST` recusa perfil `cliente`, `PATCH` não acha quem for cliente).

**A tela inteira é de administrador**, e isso não é uma área concedível — ver o item 3 de
`services/areas_painel`: conceder "mexer em quem administra" a quem não administra é
conceder tudo, porque a pessoa se promove no primeiro clique.

O que se concede aqui são as ÁREAS de cada membro: Clientes, Usinas, Diagnóstico,
Notificações, Rotas, Conexões e WhatsApp. Administrador abre todas por perfil e não tem
linha gravada — por isso a tela desenha as caixinhas dele marcadas e desligadas, em vez
de fingir que dá para desmarcar.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.apelido import ApelidoInvalido
from app.core.apelido import normalizar as normalizar_apelido
from app.core.db import get_db
from app.core.security import administrador_atual, gerar_hash_senha
from app.api.v1.painel_empresas import UsuarioDaEmpresaOut, resumo_das_contas
from app.models.acesso_painel import AcessoPainel
from app.models.empresa import Empresa, MembroDaEmpresa
from app.models.pessoa import Pessoa
from app.models.user import Perfil, User
from app.services import areas_painel, pessoas

#: Os perfis desta tela. Cliente tem a tela dele; gerente de empresa, a da empresa —
#: e essa separação é a mesma dos portões: o que não é da plataforma não se administra aqui.
DA_PLATAFORMA = (Perfil.ATENDIMENTO, Perfil.ADMINISTRADOR)

router = APIRouter(prefix="/api/painel", tags=["painel · usuários do sistema"])


class AreaOut(BaseModel):
    chave: str
    rotulo: str
    descricao: str
    grupo: str


@router.get("/areas", response_model=list[AreaOut])
def catalogo_de_areas(_: User = Depends(administrador_atual)) -> list[AreaOut]:
    """Tudo que pode ser concedido. É a fonte das caixinhas da tela.

    Devolver o catálogo inteiro, e não só o concedido, é o que permite desenhar o que
    FALTA conceder — uma lista só do concedido não teria como mostrar o resto.
    """
    return [
        AreaOut(chave=a.chave, rotulo=a.rotulo, descricao=a.descricao, grupo=a.grupo)
        for a in areas_painel.CATALOGO
    ]


class MembroOut(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    perfil: str
    ativo: bool
    ultimo_login: datetime | None = None
    #: O que está GRAVADO para esta pessoa. Vem vazio para administrador, que abre tudo
    #: por perfil — ver o docstring do módulo.
    areas: list[str] = []


def _membro_out(db: Session, m: User) -> MembroOut:
    return MembroOut(
        id=m.id,
        nome=m.nome,
        apelido=m.apelido,
        email=m.email,
        perfil=m.perfil.value,
        ativo=m.ativo,
        ultimo_login=m.ultimo_login,
        areas=sorted(areas_painel.concedidas(db, m)),
    )


@router.get("/usuarios", response_model=list[MembroOut])
def listar(
    db: Session = Depends(get_db), _: User = Depends(administrador_atual)
) -> list[MembroOut]:
    # Só o staff da PLATAFORMA. O gerente de uma empresa de O&M também não é cliente, mas
    # não é desta lista: ele aparecia aqui por herança do `!= CLIENTE`, misturado com quem
    # administra o sistema — e uma linha errada nesta tela o promoveria a administrador da
    # plataforma inteira. Ele é gerido na ficha da empresa dele.
    lista = db.scalars(
        select(User).where(User.perfil.in_(DA_PLATAFORMA)).order_by(User.nome)
    ).all()
    return [_membro_out(db, m) for m in lista]


class MembroIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None
    perfil: Perfil = Perfil.ATENDIMENTO
    senha: str = Field(min_length=8)
    #: Com o que a pessoa já nasce podendo abrir. Vazio é o padrão e é honesto: conta nova
    #: sem área entra no painel e não vê nada além do aviso de que falta acesso — melhor
    #: do que herdar em silêncio o que o último membro tinha.
    areas: list[str] = []


@router.post("/usuarios", response_model=MembroOut, status_code=201)
def criar(
    body: MembroIn,
    db: Session = Depends(get_db),
    admin: User = Depends(administrador_atual),
) -> MembroOut:
    if body.perfil is Perfil.CLIENTE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Dono de usina se cadastra na página da empresa que cuida dele (Empresas → a empresa → Novo usuário)."
        )
    if body.perfil is Perfil.GESTOR_EMPRESA:
        # Esta tela é do staff da PLATAFORMA, e um gerente sem empresa não entra em lugar
        # nenhum: `gestor_empresa_atual` o recusa. Criá-lo aqui produziria uma conta que
        # parece pronta e não abre nada — por isso o caminho é a tela da empresa, onde o
        # vínculo é obrigatório por construção.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "O gerente de uma empresa de O&M é criado dentro da empresa, em Empresas de O&M.",
        )
    try:
        apelido = normalizar_apelido(body.apelido)
    except ApelidoInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if db.scalar(select(User).where(User.apelido == apelido)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"O apelido “{apelido}” já está em uso."
        )

    membro = User(
        apelido=apelido,
        email=str(body.email).strip().lower() if body.email else None,
        nome=body.nome.strip(),
        perfil=body.perfil,
        senha_hash=gerar_hash_senha(body.senha),
    )
    db.add(membro)
    db.flush()

    if body.areas:
        try:
            areas_painel.definir(db, membro, set(body.areas), admin)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    db.commit()
    db.refresh(membro)
    return _membro_out(db, membro)


class MembroPatch(BaseModel):
    perfil: Perfil | None = None
    ativo: bool | None = None
    #: A lista COMPLETA de áreas, não um acréscimo: o que não vier é revogado. É o mesmo
    #: contrato da tela de permissões do cliente — a tela manda o estado das caixinhas.
    #: Ausente (`None`) não mexe em acesso nenhum.
    areas: list[str] | None = None


@router.patch("/usuarios/{membro_id}", response_model=MembroOut)
def editar(
    membro_id: int,
    body: MembroPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(administrador_atual),
) -> MembroOut:
    membro = db.get(User, membro_id)
    if membro is None or membro.perfil not in DA_PLATAFORMA:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")

    # Rebaixar ou desativar a si mesmo tranca o painel para fora — e se for o último
    # administrador, tranca para todo mundo.
    if membro.id == admin.id and (body.ativo is False or body.perfil is Perfil.ATENDIMENTO):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Você não pode remover o próprio acesso de administrador.",
        )

    if body.perfil is not None:
        membro.perfil = body.perfil
    if body.ativo is not None:
        membro.ativo = body.ativo

    if body.areas is not None:
        try:
            areas_painel.definir(db, membro, set(body.areas), admin)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    restantes = db.scalar(
        select(User).where(
            User.perfil == Perfil.ADMINISTRADOR, User.ativo, User.id != membro.id
        )
    )
    if restantes is None and membro.perfil is not Perfil.ADMINISTRADOR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Precisa sobrar ao menos um administrador ativo.",
        )

    db.commit()
    db.refresh(membro)
    return _membro_out(db, membro)


class SenhaIn(BaseModel):
    senha: str = Field(min_length=8)


@router.put("/usuarios/{membro_id}/senha", status_code=204)
def redefinir_senha(
    membro_id: int,
    body: SenhaIn,
    db: Session = Depends(get_db),
    _: User = Depends(administrador_atual),
) -> None:
    """Quem administra define a senha nova, do mesmo jeito que definiu a primeira.

    Não é a senha provisória do cliente (`POST /clientes/{id}/senha`): o painel não tem
    tela de troca de senha para o staff, então uma senha sorteada seria a senha dele para
    sempre. Aqui o administrador combina a senha com a pessoa, como no cadastro.

    Sessões já abertas continuam valendo até expirar — o token do painel não é
    revogável. Para tirar alguém de dentro agora, desative a conta.
    """
    membro = db.get(User, membro_id)
    if membro is None or membro.perfil not in DA_PLATAFORMA:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")

    membro.senha_hash = gerar_hash_senha(body.senha)
    db.commit()


# --------------------------------------------------------------------- pessoas


class ContaParaAgrupar(BaseModel):
    id: int
    apelido: str
    nome: str
    perfil: str
    empresa: str | None = None
    pessoa_id: int | None = None
    pessoa_nome: str | None = None


@router.get("/pessoas/contas", response_model=list[ContaParaAgrupar])
def contas_para_agrupar(
    db: Session = Depends(get_db), _admin: User = Depends(administrador_atual)
) -> list[ContaParaAgrupar]:
    """TODAS as contas do sistema, para dizer quais são do mesmo humano.

    Inclui cliente, gerente e staff na mesma lista de propósito: o agrupamento existe
    justamente para atravessar os três — quem administra a plataforma também é dono de
    usina, e é essa a combinação que não se resolvia sem sair e entrar de novo.
    """
    empresas = {e.id: e.nome for e in db.scalars(select(Empresa)).all()}
    pessoas_nome = {p.id: p.nome for p in db.scalars(select(Pessoa)).all()}
    return [
        ContaParaAgrupar(
            id=u.id,
            apelido=u.apelido,
            nome=u.nome,
            perfil=u.perfil.value,
            empresa=empresas.get(u.empresa_id) if u.empresa_id else None,
            pessoa_id=u.pessoa_id,
            pessoa_nome=pessoas_nome.get(u.pessoa_id) if u.pessoa_id else None,
        )
        for u in db.scalars(select(User).order_by(User.nome)).all()
    ]


class AgruparIn(BaseModel):
    nome: str = Field(min_length=2)
    #: Os apelidos que são do mesmo humano. Dois ou mais — agrupar uma conta sozinha não
    #: muda nada e só criaria linha órfã em `gs_pessoas`.
    apelidos: list[str] = Field(min_length=2)


class PessoaOut(BaseModel):
    id: int
    nome: str
    contas: list[str]


@router.post("/pessoas", response_model=PessoaOut, status_code=201)
def agrupar_contas(
    body: AgruparIn, db: Session = Depends(get_db), _admin: User = Depends(administrador_atual)
) -> PessoaOut:
    """Diz que estas contas são da mesma pessoa.

    Só administrador: agrupar é conceder um caminho de troca entre contas, e quem puder
    fazê-lo junta a própria conta à de alguém com mais poder. Por isso não é área
    concedível — é a mesma régua de Usuários do sistema.
    """
    apelidos = [a.strip().lower() for a in body.apelidos if a and a.strip()]
    contas = list(db.scalars(select(User).where(User.apelido.in_(apelidos))).all())
    if len(contas) != len(set(apelidos)):
        achados = {c.apelido for c in contas}
        faltando = sorted(set(apelidos) - achados)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Não achei: {', '.join(faltando)}."
        )

    pessoa = pessoas.agrupar(db, contas, body.nome)
    db.commit()
    return PessoaOut(id=pessoa.id, nome=pessoa.nome, contas=sorted(c.apelido for c in contas))


@router.delete("/pessoas/{apelido}", status_code=204)
def desagrupar(
    apelido: str, db: Session = Depends(get_db), _admin: User = Depends(administrador_atual)
) -> None:
    """Tira esta conta do grupo. As outras continuam juntas.

    Existe porque agrupar errado é o tipo de engano que precisa ser desfeito na hora: a
    conta agrupada por engano fica alcançável pela senha de outra pessoa.
    """
    conta = db.scalar(select(User).where(User.apelido == apelido.strip().lower()))
    if conta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada.")
    conta.pessoa_id = None
    db.commit()


# ------------------------------------------------- todas as contas (o inverso de Empresas)


class EmpresaDaContaOut(BaseModel):
    id: int
    nome: str
    #: A empresa que cuida da conta (senha, celular, tokens e bot). As outras só a têm.
    origem: bool


class ContaOut(UsuarioDaEmpresaOut):
    #: Administrador ou atendimento: entra no adm-gs, não é de empresa nenhuma.
    da_plataforma: bool = False
    #: As telas do adm que esta conta da plataforma abre (vazio = todas, se administrador).
    areas: list[str] = []
    #: As empresas desta conta, a de origem primeiro. Vazio numa conta que não é da
    #: plataforma = conta SEM empresa: nenhum gerente a enxerga — falta pôr numa empresa.
    empresas: list[EmpresaDaContaOut] = []
    #: O texto livre de antes de `gs_empresas` ("Eninsa"), só para a conta SEM empresa: é a
    #: pista de onde ela deveria estar.
    empresa_antiga: str | None = None


@router.get("/contas", response_model=list[ContaOut])
def todas_as_contas(
    db: Session = Depends(get_db), admin: User = Depends(administrador_atual)
) -> list[ContaOut]:
    """TODAS as contas — a tela Usuários do adm-gs, o inverso de Empresas: cada pessoa com
    a(s) empresa(s) dela, sem travar ninguém numa empresa só (pedido do dono, 23/10/2026).

    A equipe da plataforma vem junto, marcada; ela continua sendo administrada pelas rotas
    de `/usuarios`, que não aceitam conta de empresa (e vice-versa, `PATCH /contas/{id}`).
    """
    # Poucas idas ao banco no total, e não algumas por conta: o banco fica nos EUA, e cada
    # ida custa ~150 ms (a lista levava 4,6 s — auditoria de 24/10/2026).
    contas = list(db.scalars(select(User).order_by(User.nome)).all())
    nomes = {e.id: e.nome for e in db.scalars(select(Empresa)).all()}
    membro: dict[int, list[int]] = {}
    for uid, eid in db.execute(
        select(MembroDaEmpresa.user_id, MembroDaEmpresa.empresa_id).order_by(MembroDaEmpresa.id)
    ).all():
        membro.setdefault(uid, []).append(eid)
    resumo = {r.id: r for r in resumo_das_contas(db, contas, admin, nomes=nomes, membro=membro)}
    areas: dict[int, set[str]] = {}
    for uid, area in db.execute(select(AcessoPainel.user_id, AcessoPainel.area)).all():
        areas.setdefault(uid, set()).add(area)
    saida = []
    for c in contas:
        plataforma = c.perfil in DA_PLATAFORMA
        ids = [] if plataforma else list(
            dict.fromkeys(([c.empresa_id] if c.empresa_id else []) + membro.get(c.id, []))
        )
        saida.append(
            ContaOut(
                **resumo[c.id].model_dump(),
                da_plataforma=plataforma,
                areas=sorted(areas.get(c.id, set()) & areas_painel.CHAVES) if plataforma else [],
                empresas=[
                    EmpresaDaContaOut(id=i, nome=nomes[i], origem=i == c.empresa_id)
                    for i in ids
                    if i in nomes
                ],
                empresa_antiga=c.empresa if not plataforma and not ids else None,
            )
        )
    return saida


class ContaPatch(BaseModel):
    ativo: bool | None = None
    #: Senha nova, definida por quem administra e entregue à pessoa com o apelido.
    senha: str | None = Field(default=None, min_length=8)


@router.patch("/contas/{conta_id}", response_model=ContaOut)
def editar_conta(
    conta_id: int,
    body: ContaPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(administrador_atual),
) -> ContaOut:
    """Renova a senha ou desativa/reativa uma conta de EMPRESA (ou sem empresa ainda) — a
    renovação de senha que a plataforma faz por quem esqueceu. Conta da plataforma tem as
    travas dela em `/usuarios/{id}` (ninguém tira o próprio acesso, sobra um administrador)."""
    conta = db.get(User, conta_id)
    if conta is None or conta.perfil in DA_PLATAFORMA:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada.")
    if body.ativo is not None:
        conta.ativo = body.ativo
    if body.senha:
        conta.senha_hash = gerar_hash_senha(body.senha)
    db.commit()
    return next(c for c in todas_as_contas(db=db, admin=admin) if c.id == conta.id)
