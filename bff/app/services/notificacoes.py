"""A central de notificações: o catálogo, o funil e quem pode receber.

## O funil

Começa na PESSOA e afunila na USINA. O cliente com dez usinas escolhe de quais quer cada
aviso — parada das duas que operam no limite, energia mensal de todas. O caminho inverso
(usina primeiro) obrigaria a escolher tudo ou nada por tipo, e quem recebe demais desliga o
canal inteiro, calando também o aviso que importava.

## Três filtros, todos obrigatórios

1. **Preferência marcada** — o gestor marcou este tipo para esta usina. Nada nasce ligado.
2. **A usina é do cliente** — só usina concedida (`gs_user_plant_access`) pode ser marcada,
   e tirar a usina do cliente apaga as preferências dela. Avisar sobre usina que ele não
   pode nem abrir seria vazamento: o nome da usina de outro cliente na tela de bloqueio.
3. **Telefone e aceite** — sem número não há destino; sem o aceite registrado, a Meta
   proíbe a empresa de iniciar conversa. Falta de qualquer um dos dois é motivo escrito na
   tela, não silêncio.

## O catálogo mora em código

Tipo novo é uma linha em `CATALOGO`, sem migração — a mesma escolha de
`services/permissoes.py`, pelo mesmo motivo: tipo novo aparece toda semana. A `origem` de
cada um não é enfeite: ela diz de qual produto o gatilho vem, e é o que impede alguém
prometer na tela um aviso que nenhum sistema sabe disparar.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.notificacao import NotificacaoEnviada, NotificacaoPreferencia
from app.models.plant import PlantLink
from app.models.user import User, UserPlantAccess


@dataclass(frozen=True)
class TipoDeNotificacao:
    tipo: str
    rotulo: str
    #: O que o cliente vai receber, em uma frase — é o que o gestor lê ao decidir.
    descricao: str
    #: De onde vem o gatilho: `meuWatt`, `meuPlano`. Aparece na tela.
    origem: str


CATALOGO: list[TipoDeNotificacao] = [
    TipoDeNotificacao(
        tipo="parada",
        rotulo="Usina parada",
        descricao=(
            "Uma mensagem por usina quando um equipamento para de gerar e continua parado "
            "por 15 minutos, dizendo o que parou."
        ),
        origem="meuWatt",
    ),
    TipoDeNotificacao(
        tipo="os_iniciada",
        rotulo="Início de manutenção",
        descricao="Quando o técnico inicia a ordem de serviço na usina.",
        origem="meuPlano",
    ),
    TipoDeNotificacao(
        tipo="os_finalizada",
        rotulo="Fim de operação",
        descricao="Quando o técnico finaliza a ordem de serviço.",
        origem="meuPlano",
    ),
    TipoDeNotificacao(
        tipo="energia_dia",
        rotulo="Energia do dia",
        descricao="No fim do ciclo solar, quanto a usina gerou no dia.",
        origem="meuWatt",
    ),
    TipoDeNotificacao(
        tipo="energia_semana",
        rotulo="Energia da semana",
        descricao="No sábado, no fim do ciclo solar, o total de domingo a sábado.",
        origem="meuWatt",
    ),
    TipoDeNotificacao(
        tipo="energia_mes",
        rotulo="Energia do mês",
        descricao="No fim do último dia do mês, o total do mês.",
        origem="meuWatt",
    ),
]

TIPOS: dict[str, TipoDeNotificacao] = {t.tipo: t for t in CATALOGO}


class RegraDeNegocio(Exception):
    """Erro que o gestor corrige sozinho — a frase vai direto para a tela."""


# ── quem pode receber ───────────────────────────────────────────────────────


def motivo_de_nao_receber(cliente: User) -> str | None:
    """`None` quando a conta está apta. Senão, a frase que falta resolver.

    Devolve o PRIMEIRO impedimento, não a lista: o gestor resolve um de cada vez, e três
    frases de uma vez fazem a tela parecer quebrada em vez de incompleta.
    """
    if not cliente.ativo:
        return "A conta está desativada."
    if not cliente.telefone:
        return "Falta o telefone do cliente."
    if cliente.whatsapp_aceite_em is None:
        return "Falta registrar o aceite do cliente (cláusula do contrato)."
    return None


def apto(cliente: User) -> bool:
    return motivo_de_nao_receber(cliente) is None


def registrar_aceite(db: Session, cliente: User, *, aceito: bool, por: User) -> None:
    """Marca (ou desmarca) que o cliente concordou em receber mensagens no WhatsApp.

    O aceite é do CONTRATO: a cláusula que ele assinou é a autorização, e o gestor registra
    aqui que ela existe. Desmarcar é caminho legítimo — cliente que pede para sair volta a
    não receber nada, sem precisar apagar as preferências que ele escolheu.
    """
    if aceito:
        if cliente.whatsapp_aceite_em is None:
            cliente.whatsapp_aceite_em = datetime.now(UTC)
            cliente.whatsapp_aceite_por = por.id
    else:
        cliente.whatsapp_aceite_em = None
        cliente.whatsapp_aceite_por = None
    db.commit()


# ── preferências ────────────────────────────────────────────────────────────


def usinas_do_cliente(db: Session, cliente: User) -> list[PlantLink]:
    """As usinas concedidas a ele — o universo do que pode ser marcado."""
    return list(
        db.scalars(
            select(PlantLink)
            .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
            .where(UserPlantAccess.user_id == cliente.id)
            .order_by(PlantLink.nome)
        ).all()
    )


def marcadas(db: Session, cliente: User) -> set[tuple[str, int]]:
    """Os pares `(tipo, usina)` que este cliente tem marcados."""
    return {
        (p.tipo, p.plant_link_id)
        for p in db.scalars(
            select(NotificacaoPreferencia).where(
                NotificacaoPreferencia.user_id == cliente.id
            )
        ).all()
    }


def definir(
    db: Session, cliente: User, pares: list[tuple[str, int]], *, por: User
) -> None:
    """Substitui as preferências do cliente pela lista inteira.

    Substituição, e não conceder/revogar separados, pelo mesmo motivo das permissões: a
    tela manda o estado final e não existe momento em que banco e tela discordam.

    Recusa a operação toda quando um par é inválido — tipo fora do catálogo ou usina que
    não é do cliente. Gravar o resto deixaria o gestor com metade do que ele marcou e
    nenhum jeito de saber qual metade.
    """
    permitidas = {u.id for u in usinas_do_cliente(db, cliente)}

    desejados: set[tuple[str, int]] = set()
    for tipo, plant_link_id in pares:
        if tipo not in TIPOS:
            raise RegraDeNegocio(f"Tipo de notificação desconhecido: {tipo!r}.")
        if plant_link_id not in permitidas:
            usina = db.get(PlantLink, plant_link_id)
            nome = f"“{usina.nome}”" if usina else f"id {plant_link_id}"
            raise RegraDeNegocio(
                f"A usina {nome} não é deste cliente — conceda a usina antes de marcar o aviso."
            )
        desejados.add((tipo, plant_link_id))

    atuais = marcadas(db, cliente)

    for tipo, plant_link_id in atuais - desejados:
        db.execute(
            delete(NotificacaoPreferencia).where(
                NotificacaoPreferencia.user_id == cliente.id,
                NotificacaoPreferencia.tipo == tipo,
                NotificacaoPreferencia.plant_link_id == plant_link_id,
            )
        )
    for tipo, plant_link_id in desejados - atuais:
        db.add(
            NotificacaoPreferencia(
                user_id=cliente.id,
                tipo=tipo,
                plant_link_id=plant_link_id,
                criada_por=por.id,
            )
        )
    db.commit()


def limpar_usinas(db: Session, user_id: int, plant_link_ids: list[int]) -> int:
    """Apaga as preferências destas usinas para este cliente. Devolve quantas saíram.

    Chamado quando a usina deixa de ser dele: sem isto, reconceder a mesma usina meses
    depois traria de volta avisos que ninguém marcou — e o gestor não teria como saber que
    a linha antiga continuava lá.
    """
    if not plant_link_ids:
        return 0
    resultado = db.execute(
        delete(NotificacaoPreferencia).where(
            NotificacaoPreferencia.user_id == user_id,
            NotificacaoPreferencia.plant_link_id.in_(plant_link_ids),
        )
    )
    return int(resultado.rowcount or 0)


# ── o funil, para o motor ───────────────────────────────────────────────────


def destinatarios(db: Session, tipo: str, plant_link_id: int) -> list[User]:
    """Quem deve receber ESTE aviso DESTA usina — já com os três filtros aplicados.

    É a função que o motor de envio vai chamar. Ela existe agora, com a central, porque a
    regra de quem recebe é a mesma com ou sem envio: a tela mostra o que ela responderia.
    """
    pessoas = db.scalars(
        select(User)
        .join(NotificacaoPreferencia, NotificacaoPreferencia.user_id == User.id)
        .join(UserPlantAccess, UserPlantAccess.user_id == User.id)
        .where(
            NotificacaoPreferencia.tipo == tipo,
            NotificacaoPreferencia.plant_link_id == plant_link_id,
            # A concessão da usina é conferida de novo aqui, e não só na marcação: entre
            # marcar e enviar pode ter passado um mês, e a usina pode ter mudado de dono.
            UserPlantAccess.plant_link_id == plant_link_id,
            User.ativo,
        )
    ).all()
    return [p for p in pessoas if apto(p)]


def ja_enviada(db: Session, user_id: int, chave: str) -> bool:
    return (
        db.scalar(
            select(NotificacaoEnviada.id).where(
                NotificacaoEnviada.user_id == user_id,
                NotificacaoEnviada.chave == chave,
            )
        )
        is not None
    )


def historico(db: Session, cliente: User, limite: int = 50) -> list[NotificacaoEnviada]:
    return list(
        db.scalars(
            select(NotificacaoEnviada)
            .where(NotificacaoEnviada.user_id == cliente.id)
            .order_by(NotificacaoEnviada.criada_em.desc())
            .limit(limite)
        ).all()
    )
