"""A bateria que prova o caminho das notificações, de ponta a ponta, quando alguém pedir.

Não é teste de unidade: roda **contra o ambiente de verdade**, com as credenciais de
verdade, e responde a pergunta que nenhum `pytest` responde — *está tudo ligado AGORA?*
O `pytest` prova que o código faz o que promete; esta bateria prova que o mundo em volta
dele continua no lugar: token válido, número certo, modelo aprovado, cliente apto.

Três regras de desenho, e as três existem para a bateria poder ser rodada a qualquer
momento, inclusive num dia de trabalho:

- **Nada é alterado.** Nenhum envio real, nenhuma linha gravada. O motor roda em
  `simular=True`, que percorre coletores, destinatários e travas sem mandar mensagem.
- **Cada item diz o que fazer.** Um `falha` sem frase acionável vira chamado; por isso
  cada verificação devolve `detalhe` no imperativo.
- **`alerta` não é `falha`.** Falta de cliente apto num sistema recém-configurado é
  esperado; token vencido não é. Misturar os dois faz o verde perder o sentido.

O roteiro em prosa — o que cada item prova e o que fazer quando ele acende — está em
`docs/ROTEIRO_DE_TESTES.md`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients import whatsapp as gateway
from app.models.notificacao import NotificacaoEnviada, NotificacaoPreferencia
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import motor
from app.services import notificacoes as catalogo

OK, ALERTA, FALHA = "ok", "alerta", "falha"


@dataclass
class Item:
    chave: str
    titulo: str
    situacao: str
    detalhe: str
    #: O que foi observado — números, nomes, ids. É o que permite comparar duas execuções.
    evidencia: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resultado:
    executado_em: datetime
    duracao_ms: int
    itens: list[Item]

    @property
    def resumo(self) -> dict[str, int]:
        return {
            "ok": sum(1 for i in self.itens if i.situacao == OK),
            "alerta": sum(1 for i in self.itens if i.situacao == ALERTA),
            "falha": sum(1 for i in self.itens if i.situacao == FALHA),
        }

    @property
    def passou(self) -> bool:
        """Verde é ausência de falha. Alerta não reprova — ver o docstring do módulo."""
        return all(i.situacao != FALHA for i in self.itens)


# ── verificações ────────────────────────────────────────────────────────────


def _banco(db: Session) -> Item:
    try:
        clientes = db.scalar(
            select(func.count(User.id)).where(User.perfil == Perfil.CLIENTE)
        )
        usinas = db.scalar(select(func.count(PlantLink.id)).where(PlantLink.ativo))
    except Exception as exc:  # noqa: BLE001
        return Item("banco", "Banco de dados", FALHA, f"O banco não respondeu: {exc}")
    return Item(
        "banco",
        "Banco de dados",
        OK,
        "Responde.",
        {"clientes": clientes, "usinas_ativas": usinas},
    )


async def _credencial() -> tuple[Item, dict[str, Any] | None]:
    try:
        estado = await gateway.estado()
    except Exception as exc:  # noqa: BLE001
        return (
            Item(
                "credencial",
                "Credencial do WhatsApp",
                FALHA,
                f"O gateway não respondeu: {exc}. Confira se o serviço está no ar e se a "
                "chave interna é a mesma nos dois lados.",
            ),
            None,
        )

    if not estado.get("configurada"):
        return (
            Item(
                "credencial",
                "Credencial do WhatsApp",
                FALHA,
                "Nada cadastrado. Grave token e número em Painel → WhatsApp.",
            ),
            estado,
        )
    if estado.get("estado") != "ok":
        return (
            Item(
                "credencial",
                "Credencial do WhatsApp",
                FALHA,
                f"O último teste falhou: {estado.get('detalhe') or 'sem detalhe'}. "
                "Gere um token permanente novo e grave de novo.",
            ),
            estado,
        )
    return (
        Item(
            "credencial",
            "Credencial do WhatsApp",
            OK,
            str(estado.get("detalhe") or "Conectada."),
            {
                "phone_number_id": estado.get("phone_number_id"),
                "waba_id": estado.get("waba_id"),
                "envio_pronto": estado.get("envio_pronto"),
                "webhook_pronto": estado.get("webhook_pronto"),
            },
        ),
        estado,
    )


async def _numero_confere(estado: dict[str, Any] | None) -> Item:
    """O número gravado é mesmo um número desta conta — e qual deles.

    Existe por um erro real: o número de TESTE foi gravado no lugar do comercial e o teste
    de conexão respondeu "ok", porque enviar usa o id e aquele id existia. Só comparando
    com a lista da conta isso aparece.
    """
    if not estado or not estado.get("configurada"):
        return Item("numero", "Número em uso", ALERTA, "Sem credencial para conferir.")
    try:
        numeros = await gateway.numeros()
    except Exception as exc:  # noqa: BLE001
        return Item(
            "numero",
            "Número em uso",
            ALERTA,
            f"Não deu para listar os números da conta: {exc}. Confira o WABA ID.",
        )

    em_uso = str(estado.get("phone_number_id") or "")
    achado = next((n for n in numeros if str(n.get("id")) == em_uso), None)
    if achado is None:
        return Item(
            "numero",
            "Número em uso",
            FALHA,
            "O número gravado não está nesta conta do WhatsApp. Confira o Phone Number ID "
            "e o WABA ID em Painel → WhatsApp — provavelmente um deles é da conta de teste.",
            {"gravado": em_uso, "na_conta": [str(n.get("id")) for n in numeros]},
        )
    return Item(
        "numero",
        "Número em uso",
        OK,
        f"{achado.get('display_phone_number')} — {achado.get('verified_name')}.",
        {
            "id": em_uso,
            "numero": achado.get("display_phone_number"),
            "nome": achado.get("verified_name"),
            "qualidade": achado.get("quality_rating"),
        },
    )


async def _templates() -> Item:
    """Cada tipo do catálogo precisa de um modelo APROVADO com o nome combinado."""
    try:
        lista = await gateway.templates()
    except Exception as exc:  # noqa: BLE001
        return Item(
            "templates",
            "Modelos de mensagem",
            FALHA,
            f"Não deu para listar os modelos: {exc}. Sem modelo aprovado, nenhum aviso sai.",
        )

    por_nome = {str(t.get("name")): str(t.get("status")) for t in lista}
    faltando, pendentes = [], []
    for tipo, nome in motor.TEMPLATE_POR_TIPO.items():
        situacao = por_nome.get(nome)
        if situacao is None:
            faltando.append(f"{nome} ({tipo})")
        elif situacao != "APPROVED":
            pendentes.append(f"{nome}: {situacao}")

    evidencia = {"na_conta": por_nome, "esperados": motor.TEMPLATE_POR_TIPO}
    if faltando:
        return Item(
            "templates",
            "Modelos de mensagem",
            FALHA,
            "Faltam modelos na Meta: " + ", ".join(faltando)
            + ". Crie com esses nomes exatos, categoria Utilidade, idioma Português (BR).",
            evidencia,
        )
    if pendentes:
        return Item(
            "templates",
            "Modelos de mensagem",
            ALERTA,
            "Modelos ainda não aprovados: " + ", ".join(pendentes) + ".",
            evidencia,
        )
    return Item(
        "templates",
        "Modelos de mensagem",
        OK,
        f"Os {len(motor.TEMPLATE_POR_TIPO)} modelos estão aprovados.",
        evidencia,
    )


def _catalogo_consistente() -> Item:
    """O catálogo de tipos e a tabela de modelos têm de casar, nos dois sentidos."""
    tipos = set(catalogo.TIPOS)
    com_modelo = set(motor.TEMPLATE_POR_TIPO)
    sem_modelo = tipos - com_modelo
    orfaos = com_modelo - tipos
    if sem_modelo or orfaos:
        return Item(
            "catalogo",
            "Catálogo × modelos",
            FALHA,
            (
                f"Tipos sem modelo: {', '.join(sorted(sem_modelo)) or 'nenhum'}. "
                f"Modelos sem tipo: {', '.join(sorted(orfaos)) or 'nenhum'}."
            ),
        )
    return Item("catalogo", "Catálogo × modelos", OK, f"{len(tipos)} tipos, todos com modelo.")


def _clientes_aptos(db: Session) -> Item:
    """Quem pode receber: ativo, com telefone e com o aceite registrado."""
    clientes = list(db.scalars(select(User).where(User.perfil == Perfil.CLIENTE)).all())
    aptos = [c for c in clientes if catalogo.apto(c)]
    impedidos: dict[str, int] = {}
    for c in clientes:
        motivo = catalogo.motivo_de_nao_receber(c)
        if motivo:
            impedidos[motivo] = impedidos.get(motivo, 0) + 1

    if not clientes:
        return Item("clientes", "Clientes aptos", ALERTA, "Não há cliente cadastrado.")
    if not aptos:
        return Item(
            "clientes",
            "Clientes aptos",
            ALERTA,
            "Nenhum cliente pode receber: " + "; ".join(f"{k} ({v})" for k, v in impedidos.items()),
            {"clientes": len(clientes), "aptos": 0, "impedimentos": impedidos},
        )
    return Item(
        "clientes",
        "Clientes aptos",
        OK,
        f"{len(aptos)} de {len(clientes)} cliente(s) podem receber.",
        {"clientes": len(clientes), "aptos": len(aptos), "impedimentos": impedidos},
    )


def _preferencias(db: Session) -> Item:
    """A matriz tipo × usina × cliente, e o fantasma que ela pode guardar.

    Preferência de uma usina que não é mais do cliente é linha morta: ela não envia nada
    (o motor reconfere o escopo) e engana quem lê a tela.
    """
    total = db.scalar(select(func.count(NotificacaoPreferencia.id))) or 0
    orfas = db.scalar(
        select(func.count(NotificacaoPreferencia.id))
        .select_from(NotificacaoPreferencia)
        .outerjoin(
            UserPlantAccess,
            (UserPlantAccess.user_id == NotificacaoPreferencia.user_id)
            & (UserPlantAccess.plant_link_id == NotificacaoPreferencia.plant_link_id),
        )
        .where(UserPlantAccess.id.is_(None))
    ) or 0

    if total == 0:
        return Item(
            "preferencias",
            "Preferências marcadas",
            ALERTA,
            "Ninguém marcou aviso nenhum. Nenhuma notificação vai sair.",
            {"total": 0},
        )
    if orfas:
        return Item(
            "preferencias",
            "Preferências marcadas",
            ALERTA,
            f"{orfas} marcação(ões) apontam para usina que não é mais do cliente. "
            "Elas não enviam nada e confundem a tela — vale limpar.",
            {"total": total, "orfas": orfas},
        )
    return Item(
        "preferencias",
        "Preferências marcadas",
        OK,
        f"{total} marcação(ões), todas com a usina ainda concedida.",
        {"total": total, "orfas": 0},
    )


async def _motor_simulado(db: Session) -> Item:
    """O caminho inteiro sem mandar nada: coletores, destinatários e travas.

    É o item que prova que o motor CONSEGUE trabalhar hoje — lê os upstreams, casa com a
    matriz e chega até a porta do envio. Zero evento não é falha: pode simplesmente não
    haver nada acontecendo agora, que é o estado desejável de uma usina.
    """
    try:
        rel = await motor.disparar(db, simular=True)
    except Exception as exc:  # noqa: BLE001
        return Item("motor", "Motor (simulação)", FALHA, f"O motor levantou exceção: {exc}")

    detalhe = (
        f"{rel.eventos} evento(s) encontrados, {rel.simuladas} mensagem(ns) sairiam, "
        f"{rel.repetidas} já tinham sido avisadas."
    )
    situacao = ALERTA if rel.avisos else OK
    if rel.avisos:
        detalhe += " Avisos: " + " · ".join(rel.avisos[:5])
    return Item(
        "motor",
        "Motor (simulação)",
        situacao,
        detalhe,
        {
            "eventos": rel.eventos,
            "sairiam": rel.simuladas,
            "repetidas": rel.repetidas,
            "avisos": rel.avisos,
        },
    )


def _log(db: Session) -> Item:
    """O log responde por si: quantas saíram, quantas falharam, quantas foram lidas."""
    desde = datetime.now(UTC) - timedelta(days=7)
    linhas = list(
        db.scalars(select(NotificacaoEnviada).where(NotificacaoEnviada.criada_em >= desde)).all()
    )
    if not linhas:
        return Item(
            "log",
            "Log de notificações (7 dias)",
            ALERTA,
            "Nenhuma notificação foi registrada nos últimos 7 dias.",
            {"total": 0},
        )
    por_status: dict[str, int] = {}
    for l in linhas:
        por_status[l.status] = por_status.get(l.status, 0) + 1
    falhas = por_status.get("falhou", 0)
    situacao = FALHA if falhas and falhas == len(linhas) else (ALERTA if falhas else OK)
    return Item(
        "log",
        "Log de notificações (7 dias)",
        situacao,
        f"{len(linhas)} registro(s): " + ", ".join(f"{k} {v}" for k, v in sorted(por_status.items())),
        {"total": len(linhas), "por_status": por_status},
    )


async def executar(db: Session) -> Resultado:
    """Roda a bateria inteira. Nada é alterado, nada é enviado."""
    comeco = time.perf_counter()
    itens: list[Item] = [_banco(db)]

    item_credencial, estado = await _credencial()
    itens.append(item_credencial)
    itens.append(await _numero_confere(estado))
    itens.append(await _templates())
    itens.append(_catalogo_consistente())
    itens.append(_clientes_aptos(db))
    itens.append(_preferencias(db))
    itens.append(await _motor_simulado(db))
    itens.append(_log(db))

    return Resultado(
        executado_em=datetime.now(UTC),
        duracao_ms=int((time.perf_counter() - comeco) * 1000),
        itens=itens,
    )
