"""O recorte por empresa — a fonte ÚNICA do alcance de cada conta.

Toda consulta que devolve dado de empresa passa por `no_escopo`. A regra não é copiada
para dentro das rotas, e isso não é estilo: uma consulta que esquece o filtro **funciona
perfeitamente em desenvolvimento**, onde só existe uma empresa, e entrega o dado do
vizinho no dia em que entra a segunda. Não dá erro, não dá log, não dá exceção — dá a
conversa de um cliente na tela de outro.

É o mesmo desenho de `usinas_do_usuario` (`api/v1/plants.py`), que já protege o escopo de
usina do cliente: um lugar para conferir, um lugar para auditar, um lugar para consertar.

**O nulo é lido em UM lugar, aqui.** `empresa_id` nulo significa "conta da plataforma", e
só a combinação com o perfil o torna alcance total. Uma conta de inquilino sem empresa é
recusada em vez de ver tudo: falhar fechado é a única leitura segura de um dado faltando.
"""

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.models.empresa import Empresa, MembroDaEmpresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import notificacoes


def da_plataforma(usuario: User) -> bool:
    """A conta é do staff da plataforma — alcança todas as empresas.

    Hoje é o mesmo conjunto que abre o painel, e é por isso que a pergunta é feita à
    propriedade que já existe em vez de a uma lista de perfis repetida aqui.
    """
    return usuario.abre_painel


def empresa_exigida(usuario: User) -> int:
    """A empresa em que esta conta de inquilino está OPERANDO. Recusa quem não tem — nunca
    devolve "todas".

    É a da sessão quando a conta é de mais de uma empresa e trocou de empresa no oem-gs
    (`empresa_da_sessao`, posto pela guarda depois de conferir que a conta é mesmo de lá);
    senão, a de origem.
    """
    empresa = getattr(usuario, "empresa_da_sessao", None) or usuario.empresa_id
    if empresa is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta conta não está ligada a nenhuma empresa. Peça a quem administra a "
            "plataforma para vinculá-la.",
        )
    return empresa


def empresas_da_conta(db: Session, usuario: User) -> list[int]:
    """Todas as empresas desta conta: a de origem primeiro, depois as outras
    (`gs_usuario_empresas`). Conta da plataforma não tem nenhuma."""
    ids = [usuario.empresa_id] if usuario.empresa_id is not None else []
    for e in db.scalars(
        select(MembroDaEmpresa.empresa_id)
        .where(MembroDaEmpresa.user_id == usuario.id)
        .order_by(MembroDaEmpresa.id)
    ).all():
        if e not in ids:
            ids.append(e)
    return ids


def contas_da_empresa(empresa_id: int):
    """O filtro de "quem é desta empresa": a de origem OU membro dela. Um lugar só, para a
    lista do adm e a do gerente não divergirem sobre quem aparece."""
    return or_(
        User.empresa_id == empresa_id,
        User.id.in_(select(MembroDaEmpresa.user_id).where(MembroDaEmpresa.empresa_id == empresa_id)),
    )


def no_escopo(
    stmt: Select, coluna: InstrumentedAttribute, usuario: User, empresa_pedida: int | None = None
) -> Select:
    """Aplica o recorte de empresa a um SELECT.

    `empresa_pedida` só é aceita de quem é da plataforma — é o "ver como" da tela de
    suporte. Vindo de um inquilino, é ignorada de propósito: um parâmetro de empresa numa
    rota de empresa é a definição de vazamento, e recusar com erro ensinaria que o
    parâmetro existe.
    """
    if da_plataforma(usuario):
        return stmt if empresa_pedida is None else stmt.where(coluna == empresa_pedida)
    return stmt.where(coluna == empresa_exigida(usuario))


def por_id(db: Session, empresa_id: int) -> Empresa:
    empresa = db.get(Empresa, empresa_id)
    if empresa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Empresa não encontrada.")
    return empresa


def criar(db: Session, nome: str, documento: str | None = None) -> Empresa:
    """Cadastra a empresa. Não faz commit — quem chama decide a transação."""
    nome = (nome or "").strip()
    if not nome:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "O nome da empresa é obrigatório.")
    ja_existe = db.query(Empresa).filter(Empresa.nome.ilike(nome)).first()
    if ja_existe is not None:
        # Comparação sem diferenciar maiúsculas: "Splendor O&M" e "splendor o&m" são a
        # mesma empresa cadastrada duas vezes, que é exatamente o que o texto livre
        # em `gs_users.empresa` permitia e este modelo existe para impedir.
        raise HTTPException(status.HTTP_409_CONFLICT, f"Já existe uma empresa chamada “{ja_existe.nome}”.")
    empresa = Empresa(nome=nome, documento=(documento or None))
    db.add(empresa)
    db.flush()
    return empresa


def por_na_empresa(db: Session, conta: User, empresa_id: int, por: User | None = None) -> None:
    """Põe a conta nesta empresa (decisão da plataforma). Sem empresa de origem, esta vira a
    de origem; com, ela entra como OUTRA empresa da conta. Não faz commit."""
    if conta.perfil in (Perfil.ADMINISTRADOR, Perfil.ATENDIMENTO):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Conta da plataforma não é de empresa: ela já vê todas.",
        )
    por_id(db, empresa_id)
    if empresa_id in empresas_da_conta(db, conta):
        return
    if conta.empresa_id is None:
        conta.empresa_id = empresa_id
        return
    db.add(MembroDaEmpresa(user_id=conta.id, empresa_id=empresa_id, criado_por=por.id if por else None))


def tirar_da_empresa(db: Session, conta: User, empresa_id: int) -> None:
    """Tira a conta desta empresa — e o que ela recebia DELA (as usinas concedidas). Saindo
    da de origem, a próxima empresa dela passa a ser a de origem. Não faz commit."""
    if empresa_id not in empresas_da_conta(db, conta):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta conta não é desta empresa.")

    daqui = db.scalars(
        select(UserPlantAccess)
        .join(PlantLink, PlantLink.id == UserPlantAccess.plant_link_id)
        .where(UserPlantAccess.user_id == conta.id, PlantLink.empresa_id == empresa_id)
    ).all()
    notificacoes.limpar_usinas(db, conta.id, [a.plant_link_id for a in daqui])
    for acesso in daqui:
        db.delete(acesso)

    membro = db.scalar(
        select(MembroDaEmpresa).where(
            MembroDaEmpresa.user_id == conta.id, MembroDaEmpresa.empresa_id == empresa_id
        )
    )
    if membro is not None:
        db.delete(membro)
    if conta.empresa_id == empresa_id:
        proxima = db.scalar(
            select(MembroDaEmpresa)
            .where(MembroDaEmpresa.user_id == conta.id, MembroDaEmpresa.empresa_id != empresa_id)
            .order_by(MembroDaEmpresa.id)
        )
        conta.empresa_id = proxima.empresa_id if proxima else None
        if proxima is not None:
            db.delete(proxima)


def exigir_outro_gerente(db: Session, empresa_id: int, conta: User) -> None:
    """Recusa tirar da empresa o ÚLTIMO gerente ativo dela (rebaixar, desativar ou tirar):
    sem gerente, ninguém opera a empresa no oem-gs, e a saída seria a plataforma."""
    if conta.perfil is not Perfil.GESTOR_EMPRESA or not conta.ativo:
        return
    outros = db.scalar(
        select(func.count()).select_from(User).where(
            contas_da_empresa(empresa_id), User.perfil == Perfil.GESTOR_EMPRESA, User.ativo,
            User.id != conta.id,
        )
    ) or 0
    if not outros:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "É o único gerente ativo desta empresa: sem ele, ninguém opera a empresa no oem-gs. "
            "Crie ou promova outro gerente antes.",
        )
