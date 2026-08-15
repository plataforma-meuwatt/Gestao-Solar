"""Os inversores de uma usina.

Esta tela chegou a mostrar oito inversores chamados INV-01 a INV-08, todos
"SUN2000-100KTL", dois "parados há 3 h 10" — para qualquer usina, de qualquer cliente.
Era o andaime do desenho, e ficou no lugar do dado.

Duas armadilhas do upstream, ambas capazes de trocar o inversor de lugar em silêncio:

**Os identificadores não se conversam.** `monitoring.inverters[].id` é `slot-N` (a posição
física); `daily.inverters[].id` é o id interno do inversor. Casar as duas listas por `id`
pareia aparelhos diferentes — o casamento correto é por **número de série**.

**Nulo e zero não são a mesma coisa, e aqui a diferença é cara.** Um inversor sem
comunicação com `potencia_kw = 0` se lê como "está lá, parado, sem gerar"; o que ele está
é mudo. A distinção decide se o dono manda alguém ao campo.
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import _numero, _usina_no_escopo
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · equipamentos"])


#: `InverterMonitoring.status` no mw-api é uma lista fechada. O mapa é explícito para que
#: um estado novo do upstream apareça como "semDados" — e não seja pintado de verde por
#: um `else` otimista.
TOM_POR_ESTADO = {
    "normal": "ok",
    "alert": "alerta",
    "fault": "parado",
    "communication_error": "semDados",
    "bedtime": "semDados",
}


class EquipamentoOut(BaseModel):
    #: `slot-N`: a posição física, que sobrevive à troca do aparelho. É a chave da rota de
    #: detalhe justamente por isso — o número de série muda quando o inversor é trocado.
    id: str
    nome: str
    serial: str | None = None
    modelo: str | None = None

    tom: str
    situacao: str

    potencia_kw: float | None = None
    capacidade_kwp: float | None = None
    pct_capacidade: int | None = None
    energia_hoje_kwh: float | None = None
    temperatura_c: float | None = None

    parado_desde: datetime | None = None
    #: Minutos, para a tela formatar com `duracao()` em vez de receber frase pronta.
    parado_ha_min: int | None = None

    #: Silenciado pelo operador no meuWatt. Não entra nas contagens: é uma decisão de
    #: quem opera, e contá-lo como problema é discutir com essa decisão toda vez.
    ignorado: bool = False


class EquipamentosOut(BaseModel):
    usina: str
    #: Nulo = não consultamos. Zero seria "usina sem inversor", que não existe.
    total: int | None = None
    parados: int | None = None
    alerta: int | None = None
    #: Mudos de verdade — sem comunicação. Não inclui os que estão dormindo.
    sem_dados: int | None = None
    #: Fora da janela solar. Estado esperado, e por isso separado do problema.
    dormindo: int | None = None
    ignorados: int | None = None

    #: Quando o dado foi MEDIDO, não quando respondemos. É o que o selo de horário mostra.
    atualizado_em: datetime | None = None
    aviso: str | None = None
    equipamentos: list[EquipamentoOut] = []


def _situacao(
    estado: str,
    ignorado: bool,
    parado_ha_min: int | None,
    em_falha: bool | None = None,
    alarme: str | None = None,
    codigo_falha: Any = None,
) -> tuple[str, str]:
    """A cor e a frase, decididas aqui para as duas telas dizerem a mesma coisa.

    `em_falha` é o `down` do mw-api, o estado canônico de parada. Sem ele, esta tela lia
    só o `status` enquanto a lista de usinas já consultava `down` — e o resultado era o
    pior padrão possível: a faixa vermelha "1 inversor parado" abria numa lista onde o
    MESMO inversor aparecia verde, "Gerando". Faixa vermelha que abre em tela verde
    destrói a confiança nas duas.
    """
    if ignorado:
        return "semDados", "Ignorado no monitoramento"

    # `down` vence o status: é o detector afirmando parada material aberta, e o status
    # Modbus pode ainda dizer `normal`. Tri-estado — `None` é "não sei", e aí vale o
    # status.
    if em_falha is True and estado != "bedtime":
        estado = "fault"

    # Alarme do fabricante e código de falha decodificado são sinais próprios, e o mw-fe
    # os considera junto com o estado. Lendo só o `status`, um inversor com código de
    # falha ativo e registrador ainda em `normal` saía VERDE "Gerando" — aqui e no card da
    # usina — enquanto o meuWatt o mostrava em alerta.
    if estado == "normal" and (alarme or codigo_falha):
        return "alerta", (str(alarme).strip() if alarme else "Código de falha ativo")

    tom = TOM_POR_ESTADO.get(estado, "semDados")
    if estado == "fault":
        if parado_ha_min is None:
            return tom, "Parado"
        horas, minutos = divmod(parado_ha_min, 60)
        quando = f"{horas} h {minutos:02d}" if horas else f"{minutos} min"
        return tom, f"Parado há {quando}"
    if estado == "communication_error":
        return tom, "Sem comunicação"
    if estado == "bedtime":
        return tom, "Fora da janela solar"
    if estado == "alert":
        return tom, "Em alerta"
    if estado == "normal":
        return tom, "Gerando"

    # Estado que o mw-api passou a emitir e este mapa ainda não conhece. O tom já é
    # `semDados` pelo `.get` acima; a frase precisa acompanhar. Dizer "Gerando" aqui
    # entregaria cinza de "não sei" com texto de "está tudo bem" — exatamente o else
    # otimista que o comentário de `TOM_POR_ESTADO` promete evitar.
    return tom, "Estado desconhecido"


def _instante(valor: Any) -> datetime | None:
    """Data do upstream, que chega como texto ISO — não como `datetime`.

    Sem esta conversão o horário da medição viajava nulo e o selo da tela ficava vazio,
    dando a impressão de dado sem procedência justamente na tela que existe para mostrar
    procedência.
    """
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    if not valor:
        return None
    try:
        d = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _minutos_parado(desde: Any, agora: datetime) -> tuple[datetime | None, int | None]:
    inicio = _instante(desde)
    if inicio is None:
        return None, None
    return inicio, max(0, int((agora - inicio).total_seconds() // 60))


def _modelos_por_serial(diario: Any) -> dict[str, str]:
    """Modelo e energia do dia vêm do relatório diário, que é outra chamada.

    O casamento é por **série**, nunca por id: `monitoring.id` é `slot-N` e `daily.id` é o
    id interno do inversor. São espaços diferentes, e parear por eles troca um aparelho
    por outro sem nenhum erro aparecer.
    """
    if not isinstance(diario, dict):
        return {}
    saida: dict[str, str] = {}
    for i in diario.get("inverters") or []:
        serie = i.get("sn") or i.get("serial_number")
        if serie and i.get("model"):
            saida[str(serie)] = str(i["model"])
    return saida


def _energia_por_serial(diario: Any) -> dict[str, float]:
    """Energia do dia por inversor, pulando quem não mediu.

    `build_daily_report` sintetiza `daily_yield_kwh = 0.0` para o slot que ainda não
    reportou ou que está sem comunicação, e marca a linha com `is_communicating: False` /
    `diagnosis` justamente para o front distinguir. Repassar esse zero produzia o card
    mais contraditório do aplicativo: potência em travessão — porque ali a mudez É
    respeitada — e, na linha de baixo, "hoje 0,0 kWh". O app admitia não saber a potência
    e afirmava a energia, sobre o mesmo aparelho, no mesmo cartão.

    É a disciplina que já existe um nível acima (`_potencia_da_usina`, `sem_comunicacao`)
    descendo para o inversor.
    """
    if not isinstance(diario, dict):
        return {}

    saida: dict[str, float] = {}
    for i in diario.get("inverters") or []:
        if not isinstance(i, dict) or i.get("is_communicating") is False:
            continue
        diagnostico = str(i.get("diagnosis") or "").strip().upper()
        if diagnostico in {"NO_COMMUNICATION", "NO_REPORT"}:
            continue
        serie = i.get("sn") or i.get("serial_number")
        valor = _numero(i.get("daily_yield_kwh"))
        if serie and valor is not None:
            saida[str(serie)] = valor
    return saida


class EntradaOut(BaseModel):
    """Uma entrada MPPT do inversor."""

    numero: int
    tensao_v: float | None = None
    corrente_a: float | None = None


class EquipamentoDetalheOut(EquipamentoOut):
    usina: str
    plant_id: int

    #: Do próprio aparelho, quando o upstream souber.
    fabricante_alerta: str | None = None
    causa_parada: str | None = None
    #: `down` é tri-estado no mw-api: nulo é "o detector não sabe", e não "está bem".
    em_falha: bool | None = None

    performance_pct: float | None = None
    #: Quanto este inversor se afasta da mediana dos irmãos. Negativo = abaixo.
    desvio_mediana: float | None = None
    medido_em: datetime | None = None
    transformador: str | None = None

    entradas: list[EntradaOut] = []
    #: Corrente de cada string, na ordem física. Nulo dentro da lista = sem leitura.
    strings_a: list[float | None] = []

    aviso: str | None = None


@router.get(
    "/plants/{plant_link_id}/equipamentos/{equipamento_id}",
    response_model=EquipamentoDetalheOut,
)
async def detalhe_do_equipamento(
    plant_link_id: int,
    equipamento_id: str,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> EquipamentoDetalheOut:
    """Um inversor, com o que o meuWatt sabe dele agora.

    O identificador é a **posição** (`slot-12`), não a série: quando o aparelho é trocado,
    a posição continua a mesma e o histórico da tela não se parte ao meio.

    Fica de fora, por não existir no upstream: PR por inversor (é por usina, precisa da
    irradiância da estação), potência nominal AC (o que existe é capacidade CC instalada) e
    histórico de paradas do equipamento — este último depende de `breakdowns/range`, que
    responde 500 em produção.
    """
    link = _usina_no_escopo(db, usuario, plant_link_id)

    if not link.mw_plant_slug:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Esta usina não está ligada ao meuWatt."
        )

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        agora_resp, diario = await asyncio.gather(
            cliente.monitoramento_atual(link.mw_plant_slug),
            cliente.geracao_diaria(link.mw_plant_slug, hoje_na_usina()),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"meuWatt indisponível: {exc}"
        ) from exc

    inversores = agora_resp.get("inverters") if isinstance(agora_resp, dict) else None
    if not isinstance(inversores, list):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "O meuWatt não devolveu inversores."
        )

    inv = next((i for i in inversores if str(i.get("id")) == equipamento_id), None)
    if inv is None:
        # 404 e não 403, como no resto: negar não pode confirmar que existe.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado.")

    agora = datetime.now(UTC)
    estado = str(inv.get("status") or "").strip().lower()
    ignorado = bool(inv.get("ignored"))
    desde, minutos = _minutos_parado(inv.get("down_since"), agora)
    tom, situacao = _situacao(
        estado, ignorado, minutos, inv.get("down"), inv.get("alert_text"), inv.get("fault")
    )
    if estado == "bedtime":
        desde, minutos = None, None

    serie = inv.get("serial_number")
    watts = _numero(inv.get("active_power"))
    potencia = None if estado == "communication_error" else (
        round(watts / 1000, 2) if watts is not None else None
    )
    capacidade = _numero(inv.get("capacity_kwp")) or None

    detalhe = EquipamentoDetalheOut(
        id=str(inv.get("id")),
        usina=link.nome,
        plant_id=link.id,
        nome=str(inv.get("name") or serie or "—"),
        serial=str(serie) if serie else None,
        modelo=_modelos_por_serial(diario).get(str(serie)) if serie else None,
        tom=tom,
        situacao=situacao,
        potencia_kw=potencia,
        capacidade_kwp=capacidade,
        energia_hoje_kwh=_energia_por_serial(diario).get(str(serie)) if serie else None,
        temperatura_c=_numero(inv.get("temperature")),
        parado_desde=desde,
        parado_ha_min=minutos,
        ignorado=ignorado,
        fabricante_alerta=inv.get("alert_text"),
        causa_parada=inv.get("down_cause"),
        em_falha=inv.get("down"),
        performance_pct=_numero(inv.get("performance")),
        desvio_mediana=_numero(inv.get("median_deviation")),
        medido_em=_instante(inv.get("timestamp")),
        transformador=inv.get("meter_name"),
        entradas=[
            EntradaOut(
                numero=int(m.get("mppt") or 0),
                tensao_v=_numero(m.get("voltage")),
                corrente_a=_numero(m.get("current")),
            )
            for m in (inv.get("mppts") or [])
            if isinstance(m, dict)
        ],
        strings_a=[_numero(s) for s in (inv.get("strings") or [])],
        aviso=None if isinstance(diario, dict) else "Energia do dia indisponível.",
    )
    if detalhe.potencia_kw is not None and capacidade:
        detalhe.pct_capacidade = max(0, min(100, round(detalhe.potencia_kw / capacidade * 100)))
    return detalhe


@router.get("/plants/{plant_link_id}/equipamentos", response_model=EquipamentosOut)
async def equipamentos_da_usina(
    plant_link_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> EquipamentosOut:
    """Os inversores desta usina, com o estado de agora.

    A autorização vem de `_usina_no_escopo`: o cliente manda o id do vínculo, nunca o slug
    do meuWatt — e o vínculo é conferido contra o que foi concedido a ele.
    """
    link = _usina_no_escopo(db, usuario, plant_link_id)

    if not link.mw_plant_slug:
        return EquipamentosOut(
            usina=link.nome,
            aviso="Esta usina não está ligada ao meuWatt, de onde vêm os inversores.",
        )

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        agora_resp, diario = await asyncio.gather(
            cliente.monitoramento_atual(link.mw_plant_slug),
            cliente.geracao_diaria(link.mw_plant_slug, hoje_na_usina()),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001 — a tela abre com o aviso
        return EquipamentosOut(usina=link.nome, aviso=f"meuWatt indisponível: {exc}")

    if not isinstance(agora_resp, dict):
        return EquipamentosOut(
            usina=link.nome, aviso="Não foi possível ler o estado dos inversores agora."
        )

    inversores = agora_resp.get("inverters")
    if not isinstance(inversores, list):
        return EquipamentosOut(usina=link.nome, aviso="O meuWatt não devolveu inversores.")

    modelos = _modelos_por_serial(diario)
    energias = _energia_por_serial(diario)
    agora = datetime.now(UTC)

    saida: list[EquipamentoOut] = []
    for inv in inversores:
        estado = str(inv.get("status") or "").strip().lower()
        ignorado = bool(inv.get("ignored"))
        desde, minutos = _minutos_parado(inv.get("down_since"), agora)
        tom, situacao = _situacao(
            estado, ignorado, minutos, inv.get("down"), inv.get("alert_text"), inv.get("fault")
        )
        # Dormindo não exibe "parado há N h": o detector mantém aberta a parada da tarde, e
        # o card acabava com "Parado há 14 h" logo abaixo do chip "Fora da janela solar" —
        # desmentindo-se a si mesmo, todas as noites.
        if estado == "bedtime":
            desde, minutos = None, None

        serie = inv.get("serial_number")
        watts = _numero(inv.get("active_power"))
        # Sem comunicação a potência é desconhecida, não zero — a diferença decide se
        # alguém vai ao campo.
        potencia = None if estado == "communication_error" else (
            round(watts / 1000, 2) if watts is not None else None
        )
        capacidade = _numero(inv.get("capacity_kwp")) or None

        e = EquipamentoOut(
            id=str(inv.get("id") or f"slot-{inv.get('slave_id')}"),
            nome=str(inv.get("name") or serie or "—"),
            serial=str(serie) if serie else None,
            modelo=modelos.get(str(serie)) if serie else None,
            tom=tom,
            situacao=situacao,
            potencia_kw=potencia,
            capacidade_kwp=capacidade,
            energia_hoje_kwh=energias.get(str(serie)) if serie else None,
            temperatura_c=_numero(inv.get("temperature")),
            parado_desde=desde,
            parado_ha_min=minutos,
            ignorado=ignorado,
        )
        if e.potencia_kw is not None and capacidade:
            e.pct_capacidade = max(0, min(100, round(e.potencia_kw / capacidade * 100)))
        saida.append(e)

    ativos = [e for e in saida if not e.ignorado]

    # `bedtime` fica FORA da contagem de "sem dados": de noite a usina inteira entra nesse
    # estado, e contá-la faria o topo da tela anunciar "4 sem dados" todo fim de tarde —
    # alarme diário para o que é o comportamento esperado do sol.
    dormindo = sum(1 for e in ativos if e.situacao == "Fora da janela solar")
    mudos = sum(1 for e in ativos if e.tom == "semDados") - dormindo

    return EquipamentosOut(
        usina=link.nome,
        # `len(ativos)`, e não `len(saida)`: a tela da usina conta sem os silenciados
        # (plants.py, via `_contam`). Contar diferente fazia "3 inversores" numa tela e
        # "2" na outra, para a mesma usina.
        total=len(ativos),
        parados=sum(1 for e in ativos if e.tom == "parado"),
        alerta=sum(1 for e in ativos if e.tom == "alerta"),
        sem_dados=max(0, mudos),
        dormindo=dormindo,
        ignorados=sum(1 for e in saida if e.ignorado),
        # A leitura mais recente entre os inversores. O `timestamp` do envelope é
        # `datetime.now()` no mw-api, congelado por cache — hora da requisição, não da
        # medição.
        atualizado_em=max(
            (m for m in (_instante(i.get("timestamp")) for i in inversores) if m is not None),
            default=None,
        ),
        aviso=None if isinstance(diario, dict) else "Energia do dia indisponível.",
        equipamentos=saida,
    )
