"""O que aconteceu com as usinas desta pessoa.

Aqui não há caixa de entrada. Os dois produtos têm a sua, mas as duas são escopadas ao
dono do token — o BFF usa um token de serviço, então pedir as notificações *dele* traria a
caixa de quem gerou o token, não a do cliente. Servir isso seria vazamento.

O que existe, e é honesto, é montar a lista a partir dos **fatos** que já sabemos ler: os
alertas ativos no meuWatt, as ordens de serviço em aberto no meuPlano e as mensalidades
vencidas do próprio BFF. Nenhum desses precisa da sessão do cliente no upstream: todos
saem do escopo de usinas que o gestor concedeu a ele.

Uma consequência a assumir de frente: **não há "marcar como lida"**. Os endpoints que
existem nos dois produtos gravam na caixa do dono do token, ou seja, marcariam lido para a
pessoa errada. Enquanto for assim, a lista é um retrato do que está aberto agora — e a
tela diz isso, em vez de oferecer um botão que mentiria.
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.billing import _assinaturas_do_usuario
from app.api.v1.equipamentos import _instante
from app.api.v1.plants import usinas_do_usuario
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.billing import SituacaoFatura
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · notificações"])


class NotificacaoOut(BaseModel):
    id: str
    #: `acao` pede providência de alguém; `sistema` é informativo. A tela separa os dois.
    grupo: str
    tom: str
    titulo: str
    resumo: str
    #: Quando o fato aconteceu. A tela formata como "há 2 h" com `quando()`.
    em: datetime | None = None
    plant_id: int | None = None
    usina: str | None = None


class NotificacoesOut(BaseModel):
    notificacoes: list[NotificacaoOut] = []
    #: Quantas pedem providência. É o número da bolinha no avatar.
    acoes: int = 0
    aviso: str | None = None


#: `_row_to_alert` grava `sn = row.serial_number or "plant"`. O literal marca uma parada
#: da USINA inteira, não de um inversor — anunciá-la como "Inversor parado · plant" erra
#: no escopo e ainda entrega uma palavra em inglês ao dono da usina.
SEM_INVERSOR = "plant"


MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def _competencia_legivel(competencia: str) -> str:
    """`2026-08` é formato de máquina. Quem tem uma usina lê "agosto de 2026"."""
    try:
        ano, mes = competencia.split("-")
        return f"{MESES[int(mes) - 1]} de {ano}"
    except (ValueError, IndexError):
        return competencia


def _descreve(a: dict[str, Any]) -> tuple[str, str | None]:
    """Título e detalhe de um alerta, em português e no escopo certo.

    Duas coisas que **não** dá para tirar daqui, e a auditoria pegou as duas depois de eu
    tentar:

    - **A etiqueta do slot.** `alerts/service.py` produz `slot_label`, mas `AlertDetail`
      não o declara e a rota usa `response_model` — o FastAPI descarta o campo antes de
      ele sair do mw-api. Ler `a["slot_label"]` devolve `None` para sempre. A etiqueta
      existe em `InverterDailyEntry.slot_label`, do relatório diário; buscá-la custaria
      uma chamada por alerta, e o número de série já identifica o aparelho.
    - **A causa da parada.** `notification` é `f"Breakdown ({row.type})"`, e `type` é
      `equipment | plant` — o escopo, não o motivo. A causa mora na coluna `cause`, que
      `/alerts` não expõe. Traduzir "equipment" para português seria inventar sentido.

    O que sobra é honesto: dizer QUEM parou e deixar o motivo de fora, em vez de repassar
    `"Breakdown (equipment)"` — inglês e sem informação — para quem tem uma usina.
    """
    serie = str(a.get("sn") or "").strip()
    degradacao = str(a.get("kind") or "stop") == "degradation"

    if serie == SEM_INVERSOR or not serie:
        return ("Usina gerando abaixo do esperado" if degradacao else "Usina parada"), None

    titulo = f"{'Gerando abaixo do esperado' if degradacao else 'Inversor parado'} · {serie}"
    return titulo, None


async def _alertas_da_usina(cliente, link: PlantLink) -> list[NotificacaoOut]:
    """Alertas ativos no meuWatt.

    `kind='degradation'` é inversor **produzindo abaixo do esperado** — perda real, mas
    não é parada. O mw-api é explícito em que contagens de parada devem excluí-la, e aqui
    a distinção vira a cor: vermelho para quem parou, âmbar para quem está caindo.
    """
    resposta = await cliente.alertas(link.mw_plant_slug)
    alertas = resposta.get("alerts") if isinstance(resposta, dict) else resposta
    if not isinstance(alertas, list):
        return []

    saida: list[NotificacaoOut] = []
    for a in alertas:
        if not a.get("is_active", True):
            continue
        degradacao = str(a.get("kind") or "stop") == "degradation"
        titulo, causa = _descreve(a)
        perda = a.get("estimated_loss_kwh")

        detalhes = [link.nome]
        if causa:
            detalhes.append(causa)
        if isinstance(perda, (int, float)) and perda > 0:
            detalhes.append(f"perda estimada {perda:.0f} kWh".replace(".", ","))

        saida.append(
            NotificacaoOut(
                id=f"mw-{a.get('id')}",
                grupo="acao",
                tom="alerta" if degradacao else "parado",
                titulo=titulo,
                resumo=" · ".join(detalhes),
                em=_instante(a.get("started_at")),
                plant_id=link.id,
                usina=link.nome,
            )
        )
    return saida


#: Os estados terminais de `ServiceOrderStatus` no meuPlano
#: (`backend/app/models/tasks.py`). O enum é fechado: ABERTA · PROGRAMADA · EM_EXECUCAO ·
#: FECHADA · APROVADA · CANCELADA.
#:
#: A primeira versão desta lista foi escrita de memória e continha quatro nomes que não
#: existem em lugar nenhum (CONCLUIDA, FINALIZADA, REPROVADA, CANCELADO), enquanto omitia
#: os dois terminais que existem de fato — FECHADA e APROVADA. Funcionava por acidente,
#: porque `closed_at` é testado antes; teria falhado na primeira OS terminal sem data de
#: fechamento. Adivinhar nome de estado é o mesmo erro que adivinhar nome de campo.
STATUS_FECHADO = {"FECHADA", "APROVADA", "CANCELADA"}


def _esta_aberta(o: dict[str, Any]) -> bool:
    if o.get("closed_at"):
        return False
    return str(o.get("status") or "").strip().upper() not in STATUS_FECHADO


async def _ordens_da_usina(cliente, link: PlantLink) -> list[NotificacaoOut]:
    """Ordens de serviço realmente em aberto no meuPlano."""
    ordens = await cliente.ordens_servico(link.mp_usina_id)
    if not isinstance(ordens, list):
        return []

    saida: list[NotificacaoOut] = []
    for o in [x for x in ordens if _esta_aberta(x)][:5]:
        # `ServiceOrderOut` não tem título: o que descreve o serviço é `objetivo`. Sem
        # ele, a lista virava "Serviço em aberto · 1005" — o número da OS, que não diz
        # nada a quem é dono da usina e não trabalha no meuPlano.
        objetivo = (o.get("objetivo") or "").strip()
        numero = o.get("id")
        status = (o.get("status") or "").strip()

        detalhes = [link.nome]
        if status:
            detalhes.append(status)
        if o.get("task_count"):
            feitas = o.get("task_realized_count") or 0
            detalhes.append(f"{feitas}/{o['task_count']} tarefas")

        saida.append(
            NotificacaoOut(
                id=f"mp-{numero}",
                grupo="acao",
                tom="alerta",
                titulo=objetivo or f"Serviço em aberto · OS {numero}",
                resumo=" · ".join(detalhes),
                em=_instante(o.get("created_at") or o.get("criado_em")),
                plant_id=link.id,
                usina=link.nome,
            )
        )
    return saida


@router.get("/notifications", response_model=NotificacoesOut)
async def minhas_notificacoes(
    db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)
) -> NotificacoesOut:
    """A lista do que está aberto, das usinas desta pessoa.

    Cada fonte falha por conta própria: o meuWatt fora do ar não esconde a mensalidade
    vencida, e vice-versa.
    """
    links = usinas_do_usuario(db, usuario)
    saida: list[NotificacaoOut] = []
    falhas: list[str] = []

    com_mw = [l for l in links if l.mw_plant_slug]
    if com_mw:
        try:
            mw = await integracoes.cliente_meuwatt(db)
            for r in await asyncio.gather(
                *(_alertas_da_usina(mw, l) for l in com_mw), return_exceptions=True
            ):
                if isinstance(r, list):
                    saida.extend(r)
                else:
                    falhas.append("alertas do meuWatt")
        except Exception:  # noqa: BLE001
            falhas.append("alertas do meuWatt")

    com_mp = [l for l in links if l.mp_usina_id]
    if com_mp:
        try:
            mp = await integracoes.cliente_meuplano(db)
            for r in await asyncio.gather(
                *(_ordens_da_usina(mp, l) for l in com_mp), return_exceptions=True
            ):
                if isinstance(r, list):
                    saida.extend(r)
                else:
                    falhas.append("serviços do meuPlano")
        except Exception:  # noqa: BLE001
            falhas.append("serviços do meuPlano")

    # Mensalidade é do próprio BFF: não depende de ponte nenhuma, e por isso aparece
    # mesmo quando os dois upstreams estão fora.
    hoje = hoje_na_usina()
    for a in _assinaturas_do_usuario(db, usuario):
        produto = a.produto.value if hasattr(a.produto, "value") else str(a.produto)
        for f in a.faturas:
            situacao = f.situacao(hoje)
            if situacao is SituacaoFatura.VENCIDO:
                dias = (hoje - f.vencimento).days
                saida.append(
                    NotificacaoOut(
                        id=f"fatura-{f.id}",
                        grupo="acao",
                        tom="parado",
                        titulo=f"Mensalidade vencida · {produto}",
                        resumo=f"{_competencia_legivel(f.competencia)} · vencida há {dias} dias",
                        em=datetime.combine(f.vencimento, datetime.min.time(), tzinfo=UTC),
                    )
                )
            elif situacao is SituacaoFatura.A_VENCER:
                saida.append(
                    NotificacaoOut(
                        id=f"fatura-{f.id}",
                        grupo="sistema",
                        tom="alerta",
                        titulo=f"Mensalidade a vencer · {produto}",
                        resumo=f"{_competencia_legivel(f.competencia)} · vence em {f.vencimento:%d/%m}",
                        em=datetime.combine(f.vencimento, datetime.min.time(), tzinfo=UTC),
                    )
                )

    # Mais recente primeiro; sem data vai para o fim, porque "quando" é o eixo da tela.
    saida.sort(key=lambda n: (n.em is not None, n.em or datetime.min.replace(tzinfo=UTC)), reverse=True)

    return NotificacoesOut(
        notificacoes=saida,
        acoes=sum(1 for n in saida if n.grupo == "acao"),
        aviso=f"Não foi possível consultar: {', '.join(sorted(set(falhas)))}." if falhas else None,
    )
