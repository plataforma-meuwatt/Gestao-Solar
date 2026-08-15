"""O catálogo de permissões do aplicativo, e a checagem.

O catálogo mora em código, e não no banco, por uma razão prática: permissão nova
é o tipo de coisa que aparece toda semana, e um enum no Postgres exigiria
migração a cada uma. Em código, adicionar uma permissão é acrescentar uma linha
aqui — o painel passa a oferecê-la e o app passa a respeitá-la, sem tocar no
esquema.

A contrapartida é que o banco aceita um par `(categoria, subcategoria)` que este
catálogo não conhece. Isso é inofensivo por construção: o painel só oferece o que
está listado aqui, e `tem_permissao` compara contra a linha existente — uma linha
órfã concede algo que nenhum código consulta.

**Ausência de linha é ausência de permissão.** Não há permissão implícita, nem
"todo mundo tem por padrão". Se o gestor não conceder, o cliente não recebe — que
é exatamente a regra que vale para as usinas.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permissao import Permissao
from app.models.user import User


@dataclass(frozen=True)
class ItemDoCatalogo:
    categoria: str
    subcategoria: str
    #: O que o gestor lê na tela ao conceder.
    rotulo: str
    #: Por que essa permissão existe, em uma frase — para o gestor decidir sem adivinhar.
    descricao: str


#: Categoria → rótulo legível. Fica separado para o painel agrupar sem inventar nome.
CATEGORIAS = {
    "notificacao": "Notificações",
}

CATALOGO: list[ItemDoCatalogo] = [
    ItemDoCatalogo(
        categoria="notificacao",
        subcategoria="usina_parada",
        rotulo="Usina parada",
        descricao=(
            "Envia um aviso no celular quando um inversor da usina para de gerar, "
            "mesmo com o aplicativo fechado."
        ),
    ),
]


def item(categoria: str, subcategoria: str) -> ItemDoCatalogo | None:
    return next(
        (
            i
            for i in CATALOGO
            if i.categoria == categoria and i.subcategoria == subcategoria
        ),
        None,
    )


def permissoes_do_usuario(db: Session, usuario: User) -> set[tuple[str, str]]:
    """Os pares concedidos a esta pessoa, prontos para comparação."""
    linhas = db.scalars(
        select(Permissao).where(Permissao.user_id == usuario.id)
    ).all()
    return {(p.categoria, p.subcategoria) for p in linhas}


def tem_permissao(db: Session, usuario: User, categoria: str, subcategoria: str) -> bool:
    """Checagem única, para nenhuma tela reimplementar a regra do seu jeito."""
    return (
        db.scalar(
            select(Permissao.id).where(
                Permissao.user_id == usuario.id,
                Permissao.categoria == categoria,
                Permissao.subcategoria == subcategoria,
            )
        )
        is not None
    )


def usuarios_com_permissao(db: Session, categoria: str, subcategoria: str) -> list[User]:
    """Quem deve receber um aviso desta categoria.

    Usuário inativo fica de fora: desligar a conta tem de silenciar o push junto,
    senão alguém desligado continua sabendo o que acontece nas usinas.
    """
    return list(
        db.scalars(
            select(User)
            .join(Permissao, Permissao.user_id == User.id)
            .where(
                Permissao.categoria == categoria,
                Permissao.subcategoria == subcategoria,
                User.ativo,
            )
        ).all()
    )
