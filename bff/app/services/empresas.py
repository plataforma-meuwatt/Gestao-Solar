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
from sqlalchemy import Select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.models.empresa import Empresa
from app.models.user import User


def da_plataforma(usuario: User) -> bool:
    """A conta é do staff da plataforma — alcança todas as empresas.

    Hoje é o mesmo conjunto que abre o painel, e é por isso que a pergunta é feita à
    propriedade que já existe em vez de a uma lista de perfis repetida aqui.
    """
    return usuario.abre_painel


def empresa_exigida(usuario: User) -> int:
    """A empresa desta conta de inquilino. Recusa quem não tem — nunca devolve "todas"."""
    if usuario.empresa_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta conta não está ligada a nenhuma empresa. Peça a quem administra a "
            "plataforma para vinculá-la.",
        )
    return usuario.empresa_id


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
