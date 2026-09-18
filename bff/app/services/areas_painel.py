"""O catálogo de áreas do painel, e a checagem de quem abre o quê.

Uma área é uma tela (ou um grupo de telas que só fazem sentido juntas) que se
concede a alguém do staff. O catálogo mora em código pela mesma razão do catálogo
de permissões do aplicativo: tela nova é semanal, e um enum no Postgres cobraria
uma migration por tela.

Três regras que sustentam o desenho, e que não devem ser "simplificadas":

1. **Administrador abre tudo, sem linha nenhuma no banco.** O perfil é o
   superusuário. Depender de concessão para o administrador faria um clique
   errado trancar o painel para todo mundo, e a saída seria linha de comando.
2. **Ausência de linha é ausência de acesso.** Atendimento nasce sem nada e
   recebe o que o administrador marcar. Não há área "que todo mundo tem".
3. **A tela de Usuários do sistema NÃO é uma área concedível.** Ela fica em
   `administrador_atual` e ponto. Conceder "mexer em quem administra" a quem não
   administra é conceder tudo por tabela: a pessoa se promove a administrador no
   primeiro clique, e a régua inteira acima vira decoração.

O que o banco aceita e o catálogo não conhece é inofensivo por construção: a tela
só oferece o que está listado aqui, o `PUT` recusa chave desconhecida, e
`pode()` compara contra esta lista — linha órfã não abre nada.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.acesso_painel import AcessoPainel
from app.models.user import User


@dataclass(frozen=True)
class Area:
    chave: str
    #: O nome da tela, igual ao que aparece no menu — para o administrador reconhecer
    #: o que está concedendo sem traduzir.
    rotulo: str
    #: O que a pessoa passa a poder fazer, em uma frase.
    descricao: str
    #: Bloco do menu: `Operação` (o dia a dia) ou `Sistema` (o que quebra tudo).
    grupo: str


CATALOGO: list[Area] = [
    Area(
        chave="clientes",
        rotulo="Clientes",
        descricao=(
            "Cadastrar cliente, entregar senha provisória, vincular as contas dele no "
            "meuWatt e no meuPlano e conceder usinas."
        ),
        grupo="Operação",
    ),
    Area(
        chave="usinas",
        rotulo="Usinas",
        descricao=(
            "O inventário de usinas e a conciliação entre os dois produtos: casar, "
            "ligar e desligar usina para o aplicativo."
        ),
        grupo="Operação",
    ),
    Area(
        chave="diagnostico",
        rotulo="Diagnóstico",
        descricao="Conferir se o dado chega dos dois produtos para cada cliente.",
        grupo="Operação",
    ),
    Area(
        chave="notificacoes",
        rotulo="Notificações do cliente",
        descricao=(
            "A central de cada cliente: contato, aceite de WhatsApp e o que ele "
            "recebe. Não inclui o número da empresa."
        ),
        grupo="Operação",
    ),
    Area(
        chave="rotas",
        rotulo="Rotas",
        descricao="A sonda que exercita as rotas do meuWatt e do meuPlano.",
        grupo="Sistema",
    ),
    Area(
        chave="conexoes",
        rotulo="Conexões com os produtos",
        descricao=(
            "Os tokens com que o painel lê o meuWatt e o meuPlano. Quem abre isto "
            "troca a credencial de leitura de todo o sistema."
        ),
        grupo="Sistema",
    ),
    Area(
        chave="whatsapp",
        rotulo="WhatsApp da empresa",
        descricao=(
            "O número por onde TODAS as notificações saem: token da Meta, segredo do "
            "app e endereço do webhook."
        ),
        grupo="Sistema",
    ),
]

CHAVES = {a.chave for a in CATALOGO}


def area(chave: str) -> Area | None:
    return next((a for a in CATALOGO if a.chave == chave), None)


def concedidas(db: Session, usuario: User) -> set[str]:
    """O que está gravado para esta pessoa — sem o atalho do administrador.

    É o que a tela de Usuários do sistema desenha nas caixinhas: mostrar as sete
    marcadas para um administrador esconderia que elas vêm do perfil, e desmarcar
    uma não faria nada.
    """
    return set(
        db.scalars(select(AcessoPainel.area).where(AcessoPainel.user_id == usuario.id)).all()
    )


def efetivas(db: Session, usuario: User) -> set[str]:
    """O que esta pessoa abre de fato. É esta que o menu e as guardas consultam."""
    if usuario.e_administrador:
        return set(CHAVES)
    return concedidas(db, usuario) & CHAVES


def pode(db: Session, usuario: User, chave: str) -> bool:
    """Checagem única, para nenhuma rota reimplementar a regra do seu jeito."""
    if usuario.e_administrador:
        return True
    return db.scalar(
        select(AcessoPainel.id).where(
            AcessoPainel.user_id == usuario.id, AcessoPainel.area == chave
        )
    ) is not None


def definir(db: Session, membro: User, chaves: set[str], por: User) -> set[str]:
    """Substitui os acessos deste membro pela lista enviada. Não faz commit.

    Chave fora do catálogo estoura em `ValueError` em vez de ser gravada calada:
    uma linha que nenhuma guarda consulta deixaria a caixinha ligada na tela e a
    pessoa tomando 403 — a pior combinação possível.
    """
    desconhecidas = chaves - CHAVES
    if desconhecidas:
        raise ValueError(f"Área desconhecida: {', '.join(sorted(desconhecidas))}.")

    atuais = concedidas(db, membro)

    for chave in atuais - chaves:
        db.execute(
            delete(AcessoPainel).where(
                AcessoPainel.user_id == membro.id, AcessoPainel.area == chave
            )
        )
    for chave in chaves - atuais:
        db.add(AcessoPainel(user_id=membro.id, area=chave, concedido_por=por.id))
    return chaves
