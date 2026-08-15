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
from datetime import UTC, date, datetime, timedelta
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

    #: O trafo/skid a que este inversor pertence (`meter_name` no meuWatt). `None` quando
    #: a usina não tem a estrutura cadastrada — aí a tela mostra uma seção só.
    skid: str | None = None
    #: Quanto este inversor se afasta da mediana dos irmãos, em %. Negativo = produzindo
    #: menos. Vem pronto do meuWatt (`median_deviation`); não é calculado aqui.
    desvio_mediana_pct: float | None = None


class ReleProtecaoOut(BaseModel):
    """Relé de proteção: as flags e as três fases.

    Todo campo elétrico é `float | None`. Relé sem comunicação devolve `None`, e `None`
    vira travessão na tela — nunca zero, que num relé se lê como "sem tensão na fase",
    que é uma emergência e não uma falha de leitura.
    """

    id: str
    nome: str
    modelo: str | None = None
    skid: str | None = None
    comunicando: bool = False

    tensao_a: float | None = None
    tensao_b: float | None = None
    tensao_c: float | None = None
    corrente_a: float | None = None
    corrente_b: float | None = None
    corrente_c: float | None = None
    potencia_a: float | None = None
    potencia_b: float | None = None
    potencia_c: float | None = None
    potencia_total: float | None = None
    reativo_kvar: float | None = None
    frequencia_hz: float | None = None

    #: Flags de trip ATIVAS agora. Lista vazia = nenhuma; é o estado bom.
    flags: list[str] = []
    #: Funções de proteção habilitadas no aparelho (50, 51, 27, 59…).
    funcoes: list[str] = []
    medido_em: datetime | None = None


class ReleTemperaturaOut(BaseModel):
    """Relé/sensor de temperatura: as bobinas e o ambiente.

    `s1`/`s2`/`s3` são os três sensores do aparelho — nas usinas com trafo a seco, as três
    bobinas. `maxima_*` é a máxima que o próprio aparelho registrou no dia; vem dele, não
    é o máximo da série que o app viu.
    """

    id: str
    nome: str
    skid: str | None = None
    comunicando: bool = False

    s1: float | None = None
    s2: float | None = None
    s3: float | None = None
    ambiente: float | None = None
    maxima_s1: float | None = None
    maxima_s2: float | None = None
    maxima_s3: float | None = None
    maxima_ambiente: float | None = None

    #: O que o aparelho publica sobre cada bobina, do jeito que ele publica. O conteúdo
    #: varia por modelo, então não é reinterpretado aqui — a tela mostra rótulo e valor.
    bobinas: list[dict[str, Any]] = []
    medido_em: datetime | None = None


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

    #: Os relés vêm da MESMA resposta de `monitoring/current` que os inversores — não
    #: custam chamada extra. Lista vazia = a usina não tem esse equipamento cadastrado.
    reles_protecao: list[ReleProtecaoOut] = []
    reles_temperatura: list[ReleTemperaturaOut] = []


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


class PontoCurva(BaseModel):
    """Um bucket de 5 min da curva do dia. `kw` nunca é estimado."""

    hora: str
    kw: float


class EquipamentoDetalheOut(EquipamentoOut):
    usina: str
    plant_id: int

    #: Curva de potência do dia, do `charts/intraday`. Lista vazia = o upstream não
    #: devolveu leitura para ESTE inversor hoje — a tela diz isso, não desenha reta no
    #: zero. Bucket em que o aparelho não mediu não vira ponto.
    curva: list[PontoCurva] = []

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


def _so_janela_solar(curva: list[PontoCurva]) -> list[PontoCurva]:
    """Corta as pontas mortas da curva de potência — madrugada e noite.

    Mesma regra da curva da usina: só as PONTAS. Um zero no meio do dia é o inversor
    que caiu, que é o achado mais importante deste gráfico; cortá-lo esconderia o
    defeito. Curva inteira em zero volta como está — houve leitura, de zero.
    """
    primeiro = next((i for i, p in enumerate(curva) if p.kw > 0), None)
    if primeiro is None:
        return curva
    ultimo = len(curva) - 1 - next(i for i, p in enumerate(reversed(curva)) if p.kw > 0)
    return curva[primeiro : ultimo + 1]


def _curva_do_serial(intraday: Any, serial: str | None) -> list[PontoCurva]:
    """`points[].inverters[]` → curva deste inversor.

    O upstream só inclui no ponto os inversores que MEDIRAM naquele bucket. Quem não
    mediu fica de fora aqui também: a lacuna é informação, e preenchê-la com zero diria
    "estava gerando nada" quando a verdade é "não sabemos".
    """
    if not serial or not isinstance(intraday, dict):
        return []
    pontos = intraday.get("points")
    if not isinstance(pontos, list):
        return []
    curva: list[PontoCurva] = []
    for ponto in pontos:
        if not isinstance(ponto, dict):
            continue
        hora = ponto.get("time")
        inversores = ponto.get("inverters")
        if not isinstance(hora, str) or not isinstance(inversores, list):
            continue
        for i in inversores:
            if not isinstance(i, dict) or str(i.get("serial_number")) != str(serial):
                continue
            kw = i.get("power_kw")
            if isinstance(kw, (int, float)):
                curva.append(PontoCurva(hora=hora, kw=round(float(kw), 2)))
            break
    return curva


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
        agora_resp, diario, intraday = await asyncio.gather(
            cliente.monitoramento_atual(link.mw_plant_slug),
            cliente.geracao_diaria(link.mw_plant_slug, hoje_na_usina()),
            # A curva entra na MESMA viagem: em paralelo não custa latência, e sem ela
            # a tela do inversor abre sem gráfico.
            cliente.intraday(link.mw_plant_slug),
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
        curva=_so_janela_solar(_curva_do_serial(intraday, str(serie) if serie else None)),
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


def _texto(valor: Any) -> str | None:
    """Texto do upstream, ou `None`. String vazia é ausência, não conteúdo."""
    if valor is None:
        return None
    limpo = str(valor).strip()
    return limpo or None


def _lista_de_textos(valor: Any) -> list[str]:
    """Lista de rótulos vinda do upstream, filtrando o que não é texto útil."""
    if not isinstance(valor, list):
        return []
    saida: list[str] = []
    for item in valor:
        if isinstance(item, str) and item.strip():
            saida.append(item.strip())
        elif isinstance(item, dict):
            # Algumas funções de proteção chegam como objeto; o rótulo é o que interessa.
            rotulo = _texto(item.get("name") or item.get("code") or item.get("label"))
            if rotulo:
                saida.append(rotulo)
    return saida


def _reles(agora_resp: dict[str, Any]) -> tuple[list[ReleProtecaoOut], list[ReleTemperaturaOut]]:
    """Separa os relés de proteção dos de temperatura, na resposta de `monitoring/current`.

    O meuWatt publica os dois na mesma lista `relays` e marca a diferença com
    `is_temperature_relay`; os sensores de temperatura vêm ainda numa segunda lista,
    `temp_sensors`, que é a que traz bobina e máxima. Um relé de temperatura aparece nas
    duas — por isso os de proteção são filtrados por `is_temperature_relay` falso, senão
    ele sairia duplicado, uma vez em cada seção.
    """
    protecao: list[ReleProtecaoOut] = []
    for r in agora_resp.get("relays") or []:
        if not isinstance(r, dict) or r.get("is_temperature_relay"):
            continue
        protecao.append(
            ReleProtecaoOut(
                id=str(r.get("id") or "relay"),
                nome=_texto(r.get("name")) or "Relé",
                modelo=_texto(r.get("model")),
                skid=_texto(r.get("transformer_name")),
                comunicando=bool(r.get("comm")),
                tensao_a=_numero(r.get("voltage_a")),
                tensao_b=_numero(r.get("voltage_b")),
                tensao_c=_numero(r.get("voltage_c")),
                corrente_a=_numero(r.get("current_a")),
                corrente_b=_numero(r.get("current_b")),
                corrente_c=_numero(r.get("current_c")),
                potencia_a=_numero(r.get("active_power_a")),
                potencia_b=_numero(r.get("active_power_b")),
                potencia_c=_numero(r.get("active_power_c")),
                potencia_total=_numero(r.get("total_active_power")),
                reativo_kvar=_numero(r.get("reactive_power")),
                frequencia_hz=_numero(r.get("frequency")),
                flags=_lista_de_textos(r.get("trip_flags")),
                funcoes=_lista_de_textos(r.get("protection_functions")),
                medido_em=_instante(r.get("timestamp")),
            )
        )

    temperatura: list[ReleTemperaturaOut] = []
    for t in agora_resp.get("temp_sensors") or []:
        if not isinstance(t, dict):
            continue
        temperatura.append(
            ReleTemperaturaOut(
                id=str(t.get("id") or "temp"),
                nome=_texto(t.get("name")) or "Sensor de temperatura",
                skid=_texto(t.get("transformer_name")),
                comunicando=bool(t.get("comm")),
                s1=_numero(t.get("temp_s1")),
                s2=_numero(t.get("temp_s2")),
                s3=_numero(t.get("temp_s3")),
                ambiente=_numero(t.get("temp_ambient")),
                maxima_s1=_numero(t.get("temp_max_s1")),
                maxima_s2=_numero(t.get("temp_max_s2")),
                maxima_s3=_numero(t.get("temp_max_s3")),
                maxima_ambiente=_numero(t.get("temp_max_ambient")),
                bobinas=[b for b in (t.get("coils") or []) if isinstance(b, dict)],
                medido_em=_instante(t.get("timestamp")),
            )
        )

    return protecao, temperatura


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
    reles_protecao, reles_temperatura = _reles(agora_resp)
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
            # `meter_name` é o nome do transformador no meuWatt — o skid. Vazio vira
            # `None` para a tela cair na seção única em vez de criar um grupo sem nome.
            skid=(str(inv.get("meter_name")).strip() or None) if inv.get("meter_name") else None,
            desvio_mediana_pct=_numero(inv.get("median_deviation")),
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
        reles_protecao=reles_protecao,
        reles_temperatura=reles_temperatura,
    )


# ── Comparação entre skids ──────────────────────────────────────────────────
#
# A pergunta que esta rota responde é "algum skid está produzindo menos que os
# outros?", e a resposta honesta exige normalizar por capacidade: um skid de
# 1,2 MWp gera mais que um de 0,8 MWp sem que isso seja defeito nenhum. O que
# compara é **kWh por kWp** — energia específica.
#
# A junção é por número de série: `monitoring/current` diz a que trafo cada
# inversor pertence, e `generation/range` diz quanta energia cada série produziu
# no período. Nenhum dos dois sozinho responde a pergunta.


class SkidOut(BaseModel):
    nome: str
    inversores: int
    #: Soma da capacidade dos inversores do skid. `None` = o meuWatt não informou.
    capacidade_kwp: float | None = None
    energia_kwh: float | None = None
    #: kWh por kWp no período. É por aqui que skids de tamanhos diferentes se comparam.
    especifica: float | None = None
    #: Afastamento da mediana dos skids, em %. Negativo = produziu menos.
    desvio_pct: float | None = None


class InversorNoRankingOut(BaseModel):
    nome: str
    serial: str | None = None
    skid: str | None = None
    energia_kwh: float | None = None
    especifica: float | None = None
    desvio_pct: float | None = None


class ComparativoOut(BaseModel):
    recorte: str
    inicio: str
    fim: str
    skids: list[SkidOut] = []
    #: Todos os inversores, ordenados do pior desvio para o melhor — o topo é o que
    #: pede atenção. Ordenar assim é o que transforma a lista em diagnóstico.
    inversores: list[InversorNoRankingOut] = []
    aviso: str | None = None


def _mediana(valores: list[float]) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2


def _desvio(valor: float | None, referencia: float | None) -> float | None:
    """Afastamento percentual da referência. `None` quando não há o que comparar."""
    if valor is None or not referencia:
        return None
    return round((valor - referencia) / referencia * 100, 1)


@router.get("/plants/{plant_link_id}/comparativo", response_model=ComparativoOut)
async def comparativo_da_usina(
    plant_link_id: int,
    recorte: str = "dia",
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ComparativoOut:
    """Energia por skid e por inversor no período, com o desvio de cada um."""
    from app.api.v1.plants import _janela, _referencia_pedida  # noqa: PLC0415

    if recorte not in ("dia", "mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'dia', 'mes' ou 'ano'.")

    link = _usina_no_escopo(db, usuario, plant_link_id)
    alvo = _referencia_pedida(referencia)
    inicio, fim = (alvo, alvo) if recorte == "dia" else _janela(recorte, alvo)
    saida = ComparativoOut(recorte=recorte, inicio=inicio.isoformat(), fim=fim.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        agora_resp, relatorio = await asyncio.gather(
            cliente.monitoramento_atual(link.mw_plant_slug),
            cliente.geracao_periodo(link.mw_plant_slug, inicio, fim),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuWatt indisponível: {exc}"
        return saida

    if not isinstance(agora_resp, dict) or not isinstance(relatorio, dict):
        saida.aviso = "Não foi possível montar a comparação agora."
        return saida

    # Série → (nome, skid, capacidade). O cadastro vem do estado de agora; a energia,
    # do relatório do período.
    cadastro: dict[str, dict[str, Any]] = {}
    for inv in agora_resp.get("inverters") or []:
        if not isinstance(inv, dict) or inv.get("ignored"):
            continue
        serie = inv.get("serial_number")
        if not serie:
            continue
        cadastro[str(serie)] = {
            "nome": _texto(inv.get("name")) or str(serie),
            "skid": _texto(inv.get("meter_name")),
            "capacidade": _numero(inv.get("capacity_kwp")) or None,
        }

    if not cadastro:
        saida.aviso = "O meuWatt não devolveu inversores para comparar."
        return saida

    # Energia por série no período — o eixo oposto do mesmo `chart_data` que a rota de
    # geração soma por data.
    energia_por_serie: dict[str, float] = {}
    chart = relatorio.get("chart_data")
    series = chart.get("daily_generation") if isinstance(chart, dict) else None
    if isinstance(series, dict):
        for serie, pontos in series.items():
            if not isinstance(pontos, list):
                continue
            total = 0.0
            mediu = False
            for p in pontos:
                if isinstance(p, dict) and isinstance(p.get("y"), (int, float)):
                    total += float(p["y"])
                    mediu = True
            if mediu:
                energia_por_serie[str(serie)] = total

    if not energia_por_serie:
        saida.aviso = "O monitoramento não devolveu energia por inversor neste período."
        return saida

    # ── Por skid ──
    por_skid: dict[str, dict[str, Any]] = {}
    for serie, info in cadastro.items():
        # Inversor sem energia no período NÃO entra como zero: pode ter sido instalado
        # depois, e um zero inventado puxaria a média do skid para baixo.
        energia = energia_por_serie.get(serie)
        if energia is None:
            continue
        nome_skid = info["skid"] or "Sem skid definido"
        grupo = por_skid.setdefault(
            nome_skid, {"inversores": 0, "capacidade": 0.0, "energia": 0.0, "tem_cap": True}
        )
        grupo["inversores"] += 1
        grupo["energia"] += energia
        if info["capacidade"]:
            grupo["capacidade"] += info["capacidade"]
        else:
            # Um inversor sem capacidade contamina a específica do skid inteiro: a
            # energia dele entra no numerador e a capacidade não entra no denominador,
            # inflando o resultado. Melhor não publicar a específica desse skid.
            grupo["tem_cap"] = False

    skids: list[SkidOut] = []
    for nome, g in por_skid.items():
        cap = g["capacidade"] if g["tem_cap"] and g["capacidade"] > 0 else None
        skids.append(
            SkidOut(
                nome=nome,
                inversores=g["inversores"],
                capacidade_kwp=round(cap, 2) if cap else None,
                energia_kwh=round(g["energia"], 2),
                especifica=round(g["energia"] / cap, 3) if cap else None,
            )
        )

    mediana_skid = _mediana([s.especifica for s in skids if s.especifica is not None])
    for s in skids:
        s.desvio_pct = _desvio(s.especifica, mediana_skid)
    skids.sort(key=lambda s: s.nome)
    saida.skids = skids

    # ── Por inversor ──
    linhas: list[InversorNoRankingOut] = []
    for serie, info in cadastro.items():
        energia = energia_por_serie.get(serie)
        if energia is None:
            continue
        cap = info["capacidade"]
        linhas.append(
            InversorNoRankingOut(
                nome=info["nome"],
                serial=serie,
                skid=info["skid"],
                energia_kwh=round(energia, 2),
                especifica=round(energia / cap, 3) if cap else None,
            )
        )

    mediana_inv = _mediana([linha.especifica for linha in linhas if linha.especifica is not None])
    for linha in linhas:
        linha.desvio_pct = _desvio(linha.especifica, mediana_inv)

    # Pior desvio primeiro. Quem não tem desvio calculável vai para o fim: sem
    # capacidade não há comparação, e fingir desvio zero o esconderia no meio da lista.
    linhas.sort(key=lambda linha: (linha.desvio_pct is None, linha.desvio_pct or 0))
    saida.inversores = linhas
    return saida


# ── Curvas dos relés e histórico de flags ───────────────────────────────────
#
# Três rotas, todas com a mesma forma: a série do dia escolhido, vinda dos
# `charts/intraday/*` do meuWatt, mais o que só faz sentido em cada aparelho —
# a máxima no relé de temperatura, as flags no de proteção.
#
# `serie` é sempre `list[float | None]` alinhada a `horas`: bucket em que o
# aparelho não mediu vira `None` na posição, e a linha do gráfico se interrompe
# ali. Encolher a lista tiraria o alinhamento com o eixo; preencher com zero
# diria que a bobina esfriou de repente.


class SerieOut(BaseModel):
    rotulo: str
    #: Alinhada a `horas`; `None` = sem leitura naquele bucket.
    valores: list[float | None] = []


class CurvaEquipamentoOut(BaseModel):
    dia: str
    horas: list[str] = []
    series: list[SerieOut] = []
    aviso: str | None = None


def _serie_alinhada(
    pontos: list[dict[str, Any]], horas: list[str], campo: str
) -> list[float | None]:
    """Extrai um campo dos pontos e alinha ao eixo de horas."""
    por_hora = {
        str(p.get("time")): _numero(p.get(campo))
        for p in pontos
        if isinstance(p, dict) and p.get("time")
    }
    return [por_hora.get(h) for h in horas]


@router.get(
    "/plants/{plant_link_id}/reles/temperatura/{sensor_id}/curva",
    response_model=CurvaEquipamentoOut,
)
async def curva_do_rele_de_temperatura(
    plant_link_id: int,
    sensor_id: str,
    dia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> CurvaEquipamentoOut:
    """Temperatura das bobinas e do ambiente ao longo do dia escolhido."""
    from app.api.v1.plants import _referencia_pedida  # noqa: PLC0415

    link = _usina_no_escopo(db, usuario, plant_link_id)
    alvo = _referencia_pedida(dia)
    saida = CurvaEquipamentoOut(dia=alvo.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        bruto = await cliente.intraday_temperatura(link.mw_plant_slug, alvo)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuWatt indisponível: {exc}"
        return saida

    sensores = bruto.get("sensors") if isinstance(bruto, dict) else None
    alvo_sensor = next(
        (s for s in sensores or [] if isinstance(s, dict) and str(s.get("id")) == sensor_id),
        None,
    )
    if alvo_sensor is None:
        saida.aviso = "O monitoramento não devolveu leitura deste sensor neste dia."
        return saida

    pontos = [p for p in (alvo_sensor.get("points") or []) if isinstance(p, dict)]
    saida.horas = [str(p["time"]) for p in pontos if p.get("time")]
    if not saida.horas:
        saida.aviso = "O monitoramento não devolveu leitura deste sensor neste dia."
        return saida

    for campo, rotulo in (
        ("temp_s1", "Bobina 1"),
        ("temp_s2", "Bobina 2"),
        ("temp_s3", "Bobina 3"),
        ("temp_ambient", "Ambiente"),
    ):
        valores = _serie_alinhada(pontos, saida.horas, campo)
        # Sensor de três bobinas numa usina que só tem duas devolve S3 nulo o dia
        # inteiro. Publicar a série vazia criaria uma legenda para uma linha que não
        # existe — e o dono procuraria o defeito numa bobina que não está instalada.
        if any(v is not None for v in valores):
            saida.series.append(SerieOut(rotulo=rotulo, valores=valores))

    return saida


class MaximaDoDiaOut(BaseModel):
    dia: str
    #: Maior temperatura entre as bobinas naquele dia. `None` = sem leitura no dia.
    maxima: float | None = None


class MaximasOut(BaseModel):
    inicio: str
    fim: str
    dias: list[MaximaDoDiaOut] = []
    #: A maior de todas no intervalo, e em que dia ela aconteceu.
    pico: float | None = None
    pico_em: str | None = None
    aviso: str | None = None


@router.get(
    "/plants/{plant_link_id}/reles/temperatura/{sensor_id}/maximas",
    response_model=MaximasOut,
)
async def maximas_do_rele_de_temperatura(
    plant_link_id: int,
    sensor_id: str,
    dias: int = 7,
    ate: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> MaximasOut:
    """A temperatura mais alta de cada dia, num intervalo escolhido.

    Uma chamada de intraday por dia. O teto de 31 é o que segura a conta: cada dia é
    uma viagem ao meuWatt, e um pedido de "último ano" viraria 365 chamadas em série
    numa tela de celular.
    """
    from app.api.v1.plants import _referencia_pedida  # noqa: PLC0415

    if dias < 1 or dias > 31:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "dias deve estar entre 1 e 31.")

    link = _usina_no_escopo(db, usuario, plant_link_id)
    fim = _referencia_pedida(ate)
    inicio = fim - timedelta(days=dias - 1)
    saida = MaximasOut(inicio=inicio.isoformat(), fim=fim.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        # Em paralelo: 31 dias em série seriam 31 latências somadas.
        respostas = await asyncio.gather(
            *[
                cliente.intraday_temperatura(link.mw_plant_slug, inicio + timedelta(days=i))
                for i in range(dias)
            ],
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuWatt indisponível: {exc}"
        return saida

    for i, resposta in enumerate(respostas):
        d = inicio + timedelta(days=i)
        maxima: float | None = None
        if isinstance(resposta, dict):
            sensores = resposta.get("sensors") or []
            alvo_sensor = next(
                (s for s in sensores if isinstance(s, dict) and str(s.get("id")) == sensor_id),
                None,
            )
            for p in (alvo_sensor or {}).get("points") or []:
                if not isinstance(p, dict):
                    continue
                for campo in ("temp_s1", "temp_s2", "temp_s3"):
                    v = _numero(p.get(campo))
                    if v is not None and (maxima is None or v > maxima):
                        maxima = v
        # Dia sem leitura entra com `None`, e não some da lista: a falha de um dia é
        # informação, e omiti-lo faria o eixo mentir sobre o intervalo pedido.
        saida.dias.append(MaximaDoDiaOut(dia=d.isoformat(), maxima=maxima))

    com_leitura = [d for d in saida.dias if d.maxima is not None]
    if com_leitura:
        melhor = max(com_leitura, key=lambda d: d.maxima or 0)
        saida.pico, saida.pico_em = melhor.maxima, melhor.dia
    else:
        saida.aviso = "Nenhum dia do intervalo tem leitura deste sensor."
    return saida


@router.get(
    "/plants/{plant_link_id}/reles/protecao/{rele_id}/curva",
    response_model=CurvaEquipamentoOut,
)
async def curva_do_rele_de_protecao(
    plant_link_id: int,
    rele_id: str,
    dia: str | None = None,
    grandeza: str = "tensao",
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> CurvaEquipamentoOut:
    """Tensão, corrente ou potência das três fases ao longo do dia."""
    from app.api.v1.plants import _referencia_pedida  # noqa: PLC0415

    campos = {
        "tensao": (("voltage_a", "Fase A"), ("voltage_b", "Fase B"), ("voltage_c", "Fase C")),
        "corrente": (("current_a", "Fase A"), ("current_b", "Fase B"), ("current_c", "Fase C")),
        "potencia": (
            ("active_power_a", "Fase A"),
            ("active_power_b", "Fase B"),
            ("active_power_c", "Fase C"),
            ("total_active_power", "Total"),
        ),
    }
    if grandeza not in campos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "grandeza deve ser 'tensao', 'corrente' ou 'potencia'."
        )

    link = _usina_no_escopo(db, usuario, plant_link_id)
    alvo = _referencia_pedida(dia)
    saida = CurvaEquipamentoOut(dia=alvo.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        bruto = await cliente.intraday_rele(link.mw_plant_slug, alvo)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuWatt indisponível: {exc}"
        return saida

    reles = bruto.get("relays") if isinstance(bruto, dict) else None
    # O app conhece o relé como `relay-{id}` (é assim que o monitoring publica); a série
    # intraday o identifica pelo id cru. Aceitar as duas formas evita obrigar a tela a
    # saber dessa diferença.
    cru = rele_id.removeprefix("relay-")
    alvo_rele = next(
        (
            r
            for r in reles or []
            if isinstance(r, dict) and str(r.get("id")) in (rele_id, cru)
        ),
        None,
    )
    if alvo_rele is None:
        saida.aviso = "O monitoramento não devolveu leitura deste relé neste dia."
        return saida

    pontos = [p for p in (alvo_rele.get("points") or []) if isinstance(p, dict)]
    saida.horas = [str(p["time"]) for p in pontos if p.get("time")]
    if not saida.horas:
        saida.aviso = "O monitoramento não devolveu leitura deste relé neste dia."
        return saida

    for campo, rotulo in campos[grandeza]:
        valores = _serie_alinhada(pontos, saida.horas, campo)
        if any(v is not None for v in valores):
            saida.series.append(SerieOut(rotulo=rotulo, valores=valores))

    return saida


class EventoDeTripOut(BaseModel):
    quando: datetime | None = None
    codigo: str | None = None
    evento: str | None = None
    de: str | None = None
    para: str | None = None


class HistoricoDeFlagsOut(BaseModel):
    rele: str | None = None
    eventos: list[EventoDeTripOut] = []
    aviso: str | None = None


@router.get(
    "/plants/{plant_link_id}/reles/protecao/{rele_id}/flags",
    response_model=HistoricoDeFlagsOut,
)
async def historico_de_flags(
    plant_link_id: int,
    rele_id: str,
    limite: int = 50,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> HistoricoDeFlagsOut:
    """Histórico de flags do relé, mais recente primeiro."""
    link = _usina_no_escopo(db, usuario, plant_link_id)
    saida = HistoricoDeFlagsOut()

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    # A rota do upstream exige o id NUMÉRICO; o app carrega `relay-{id}`.
    cru = rele_id.removeprefix("relay-")
    if not cru.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Identificador de relé inválido.")

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        bruto = await cliente.eventos_de_trip(link.mw_plant_slug, int(cru), max(1, min(limite, 200)))
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuWatt indisponível: {exc}"
        return saida

    if not isinstance(bruto, dict):
        saida.aviso = "Histórico de flags indisponível."
        return saida

    saida.rele = _texto(bruto.get("relay_name"))
    for e in bruto.get("events") or []:
        if not isinstance(e, dict):
            continue
        saida.eventos.append(
            EventoDeTripOut(
                quando=_instante(e.get("timestamp")),
                codigo=_texto(e.get("trip_code")),
                evento=_texto(e.get("event")),
                de=_texto(e.get("previous_value")),
                para=_texto(e.get("current_value")),
            )
        )

    if not saida.eventos:
        saida.aviso = "Este relé não tem histórico de flags registrado."
    return saida


# ── Corrente por string ─────────────────────────────────────────────────────


@router.get(
    "/plants/{plant_link_id}/equipamentos/{equipamento_id}/strings",
    response_model=CurvaEquipamentoOut,
)
async def curva_das_strings(
    plant_link_id: int,
    equipamento_id: str,
    dia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> CurvaEquipamentoOut:
    """Corrente de cada string do inversor ao longo do dia.

    O eixo é o mesmo para todas as strings, o que é justamente a graça: string com
    problema descola das irmãs na mesma hora do dia, e isso só se vê sobrepondo.
    """
    from app.api.v1.plants import _referencia_pedida  # noqa: PLC0415

    link = _usina_no_escopo(db, usuario, plant_link_id)
    alvo = _referencia_pedida(dia)
    saida = CurvaEquipamentoOut(dia=alvo.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        # O serial é o que identifica o inversor na série intraday; o app carrega o
        # `slot-N`. A tradução exige o estado de agora, então as duas vão juntas.
        agora_resp, bruto = await asyncio.gather(
            cliente.monitoramento_atual(link.mw_plant_slug),
            cliente.intraday_strings(link.mw_plant_slug, alvo),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuWatt indisponível: {exc}"
        return saida

    if not isinstance(agora_resp, dict) or not isinstance(bruto, dict):
        saida.aviso = "Não foi possível ler as strings agora."
        return saida

    inv = next(
        (
            i
            for i in agora_resp.get("inverters") or []
            if isinstance(i, dict) and str(i.get("id")) == equipamento_id
        ),
        None,
    )
    serial = str(inv.get("serial_number")) if inv and inv.get("serial_number") else None
    if not serial:
        saida.aviso = "Este inversor não tem número de série no monitoramento."
        return saida

    # `points[].inverters[]` → `{hora: [correntes]}` só deste inversor.
    horas: list[str] = []
    por_hora: dict[str, list[float | None]] = {}
    largura = 0
    for p in bruto.get("points") or []:
        if not isinstance(p, dict) or not p.get("time"):
            continue
        alvo_inv = next(
            (
                i
                for i in p.get("inverters") or []
                if isinstance(i, dict) and str(i.get("serial_number")) == serial
            ),
            None,
        )
        if alvo_inv is None:
            continue
        correntes = [_numero(c) for c in (alvo_inv.get("strings") or [])]
        if not correntes:
            continue
        hora = str(p["time"])
        horas.append(hora)
        por_hora[hora] = correntes
        largura = max(largura, len(correntes))

    if not horas:
        saida.aviso = "O monitoramento não devolveu corrente de string deste inversor neste dia."
        return saida

    # Fora da janela solar não há corrente de string: as pontas do dia são zeros que
    # espremem o gráfico útil no meio. O corte é nas PONTAS — string que zera ao
    # meio-dia é o achado, e continua na série.
    def _tem_corrente(h: str) -> bool:
        return any(v is not None and v > 0 for v in por_hora[h])

    inicio_util = next((i for i, h in enumerate(horas) if _tem_corrente(h)), None)
    if inicio_util is not None:
        fim_util = len(horas) - 1 - next(
            i for i, h in enumerate(reversed(horas)) if _tem_corrente(h)
        )
        horas = horas[inicio_util : fim_util + 1]

    saida.horas = horas
    for indice in range(largura):
        valores = [
            (por_hora[h][indice] if indice < len(por_hora[h]) else None) for h in horas
        ]
        # String que não mediu o dia inteiro não vira legenda: o inversor publica a
        # lista no tamanho do modelo, e entradas não usadas chegam nulas sempre.
        if any(v is not None for v in valores):
            saida.series.append(SerieOut(rotulo=f"PV{indice + 1}", valores=valores))

    return saida
