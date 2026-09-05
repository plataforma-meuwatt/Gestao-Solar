"""O painel de energia do dono — o dashboard do meuWatt, recortado para o cliente.

Duas coisas moram aqui, e as duas existem por **um motivo só: a agregação não pode
acontecer no navegador do cliente.**

No meuWatt, a tabela "Unidades Consumidoras · geração hoje" é montada na tela, cruzando
`daily.inverters[].transformer_id` com os pontos de 5 em 5 minutos de `charts/intraday`,
que vêm **por número de série**. Repetir isso no portal significaria mandar a série
intradiária inteira, inversor por inversor, para o navegador de quem não é da equipe —
peso e, pior, a estrutura interna do produto de origem (seriais, ids de transformador)
saindo pela rede.

Então o corte é aqui:

- do `intraday` sai **a curva somada da usina** e, por UC, a **faísca já reamostrada em
  15 minutos** — nunca a série por inversor;
- a UC é identificada por **nome** e por um **índice estável da resposta**. O
  `transformer_id` do meuWatt não atravessa, e o número de série de inversor também não:
  o rótulo do inversor nos eventos é a etiqueta que o operador deu ao slot e, na falta
  dela, a posição na lista do monitoramento.

Regra 0 em todo canto: ausência é `None` e vira travessão na tela. Inversor que não
reportou naquele bucket não vira zero; UC sem PR não vira 0%; mês sem fatura não vira 0
MWh — fatura ainda não emitida é estado, não erro.

**Inversor sem transformador não some.** Ele cai num grupo "Sem UC" — some-lo faria a
soma das UCs não bater com a geração da usina, que é justamente a conferência que o dono
faz de olho.
"""

import asyncio
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import (
    _chave_mes,
    _diario_por_mes,
    _esperado_manual_por_mes,
    _janela,
    _meses_entre,
    _meses_medidos,
    _referencia_pedida,
    _rotulo_de_meses,
    _usina_monitorada,
)
from app.core.datas import BRT
from app.core.datas import agora as agora_na_usina
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1/energia", tags=["app · energia"])


#: Referência de mercado para o Performance Ratio, em %. Sai do servidor para a tela não
#: reinventar o limiar — é a mesma linha de 80 % que o meuWatt desenha no ranking por UC.
PR_REFERENCIA_PCT = 80.0

#: Passo da faísca por UC, em minutos. O intraday vem de 5 em 5; reamostrar em 15 corta o
#: corpo da resposta em três sem mudar o desenho de um traço de 200 px de largura.
PASSO_FAISCA_MIN = 15

#: Potência a partir da qual um inversor conta como "gerando agora", em kW. É a régua do
#: próprio meuWatt: abaixo disso é ruído de madrugada, não produção.
PISO_GERANDO_KW = 5.0

#: Rótulo do grupo que recolhe inversor sem transformador cadastrado.
SEM_UC = "Sem UC"


# ── leitura defensiva do upstream ───────────────────────────────────────────


def _numero(valor: Any) -> float | None:
    """Número ou nada. Texto, `None` e `NaN` de JSON caem em `None` — nunca em zero."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    convertido = float(valor)
    if convertido != convertido:  # NaN
        return None
    return convertido


def _lista(valor: Any) -> list[dict[str, Any]]:
    if not isinstance(valor, list):
        return []
    return [i for i in valor if isinstance(i, dict)]


def _texto(valor: Any) -> str | None:
    if isinstance(valor, str):
        limpo = valor.strip()
        return limpo or None
    return None


def _arredondar(valor: float | None, casas: int = 2) -> float | None:
    return None if valor is None else round(valor, casas)


# ── formato · dia ───────────────────────────────────────────────────────────


class PontoCurva(BaseModel):
    hora: str
    #: Soma da potência dos inversores que mediram neste bucket, em kW.
    kw: float
    #: Irradiância no plano dos módulos, W/m². `None` quando a usina não tem estação.
    poa: float | None = None


class EventoDoDia(BaseModel):
    #: Hora de início, "HH:MM" no fuso da usina.
    hora: str
    #: A etiqueta do slot dada pelo operador; na falta dela, a posição do inversor na
    #: lista do monitoramento. O número de série NUNCA sai daqui.
    inversor: str
    evento: str
    #: `None` quando o produto de origem não soube dizer quanto durou.
    duracao_min: float | None = None
    #: "HH:MM" da resolução; `None` enquanto o evento está em curso.
    resolvido_em: str | None = None
    em_curso: bool = False


class UnidadeDoDia(BaseModel):
    #: Índice estável desta UC dentro da resposta. É por ele que a tela referencia a
    #: unidade sem precisar do id do transformador do meuWatt.
    indice: int
    nome: str
    #: Capacidade instalada da UC, em kWp. `None` = não cadastrada.
    kwp: float | None = None
    inversores: int = 0
    #: Potência no último bucket em que a UC teve leitura. `None` = nenhuma leitura.
    potencia_agora_kw: float | None = None
    #: `potencia_agora_kw` sobre a capacidade, em %. `None` sem um dos dois.
    pct_capacidade: float | None = None
    #: Energia da UC no dia, em kWh. `None` = o monitoramento não trouxe o número.
    energia_kwh: float | None = None
    #: Inversores operando (sem falha e com produção) e total do grupo.
    ok: int = 0
    total: int = 0
    #: Potência média em cada fatia de 15 min, alinhada a `faisca_horas`. `None` numa
    #: posição = a UC não reportou naquela fatia; é lacuna, não zero.
    faisca: list[float | None] = []


class DiaOut(BaseModel):
    dia: str
    #: Energia da usina no dia, em kWh. `None` = sem leitura.
    gerado_kwh: float | None = None
    #: Maior potência instantânea do dia, em kW, e a hora dela.
    pico_kw: float | None = None
    pico_hora: str | None = None
    #: Potência no último bucket com leitura, em kW.
    potencia_agora_kw: float | None = None
    inversores_gerando: int | None = None
    inversores_total: int | None = None
    #: Disponibilidade energética real do dia, em %.
    disponibilidade_pct: float | None = None
    #: PR do dia em %. `None` quando não há estação **ou** quando o próprio meuWatt
    #: descartou a leitura — e aí `pr_descartado` é `True`, para a tela escrever
    #: "descartada" em vez de desenhar zero.
    pr_pct: float | None = None
    pr_descartado: bool = False
    #: Irradiância agora (W/m²) e as acumuladas do dia (kWh/m²). Nulas sem estação.
    hpoa_agora: float | None = None
    hpoa_acumulada: float | None = None
    ghi_acumulada: float | None = None
    #: A usina TEM estação solarimétrica — pergunta de CADASTRO, respondida pela mesma
    #: lista `weather_stations` de `monitoring/current` que a tela de equipamentos usa
    #: (`/plants/{id}/equipamentos`). O ativo é permanente: ele não deixa de existir às
    #: 03h só porque ainda não houve sol. `False` faz a tela dizer "sem estação".
    tem_estacao: bool = False
    #: A estação MEDIU alguma coisa neste dia. É o outro lado da pergunta, e é o que
    #: separa "não existe" de "ainda não mediu": às 03h10 de um dia com estação isto é
    #: `False` e `tem_estacao` continua `True`. Antes os dois eram o mesmo campo, e de
    #: madrugada a tela negava uma estação que existe.
    estacao_com_leitura: bool = False
    #: Quando o cadastro não pôde ser lido (o `monitoring/current` caiu), `tem_estacao`
    #: cai na leitura do dia — que é o comportamento antigo — e isto fica `True` para a
    #: tela não afirmar "não tem estação" com base num palpite.
    estacao_indefinida: bool = False
    curva: list[PontoCurva] = []
    #: Vazio = operação sem incidentes. É estado, não falta de dado.
    eventos: list[EventoDoDia] = []
    ucs: list[UnidadeDoDia] = []
    #: As horas ("HH:MM") das fatias da faísca. Uma só para todas as UCs, para a tela
    #: desenhá-las na mesma escala de tempo.
    faisca_horas: list[str] = []
    aviso: str | None = None


# ── formato · unidades ──────────────────────────────────────────────────────


class SerieDaUnidade(BaseModel):
    indice: int
    nome: str
    #: Um valor por dia de `serie_dias`, em kWh. `None` = sem leitura naquele dia.
    valores: list[float | None] = []


class UnidadeDoPeriodo(BaseModel):
    indice: int
    nome: str
    capacidade_kwp: float | None = None
    inversores: int = 0
    geracao_kwh: float | None = None
    #: Participação da UC na geração do período, em %. `None` quando a usina não gerou.
    share_pct: float | None = None
    #: kWh/kWp no período.
    produtividade: float | None = None
    #: PR da UC em %. `None` quando o monitoramento não pareou o dado — nunca 0.
    pr_pct: float | None = None
    disponibilidade_real_pct: float | None = None
    disponibilidade_contratual_pct: float | None = None
    #: MWh faturados pela distribuidora nesta UC no período. `None` = fatura ainda não
    #: emitida, que é estado e não erro.
    faturado_mwh: float | None = None


class MaiorUnidade(BaseModel):
    nome: str
    share_pct: float | None = None


class UnidadesOut(BaseModel):
    recorte: str
    inicio: str
    fim: str
    ucs_ativas: int = 0
    capacidade_total_kwp: float | None = None
    energia_periodo_kwh: float | None = None
    maior: MaiorUnidade | None = None
    ucs: list[UnidadeDoPeriodo] = []
    #: Datas da série diária por UC ("YYYY-MM-DD").
    serie_dias: list[str] = []
    serie: list[SerieDaUnidade] = []
    #: Os três rankings, cada um como a ordem dos `indice` — do maior para o menor. Sai
    #: pronto do servidor para as três listas não divergirem entre telas.
    ranking_geracao: list[int] = []
    ranking_pr: list[int] = []
    ranking_produtividade: list[int] = []
    pr_referencia_pct: float = PR_REFERENCIA_PCT
    #: `None` = nenhuma fatura emitida para o período. "Parcial" = faltam UCs.
    faturas_situacao: str | None = None
    aviso: str | None = None


# ── UC: o cruzamento que não pode ir para o navegador ───────────────────────


def _rotulos_de_inversor(inversores: list[dict[str, Any]]) -> dict[str, str]:
    """Número de série → rótulo apresentável.

    A etiqueta do slot é o que o operador escreveu e o que o dono reconhece. Sem ela,
    a posição na lista do monitoramento — que é a mesma ordem que o meuWatt exibe. O
    serial fica DENTRO do BFF: é identificador interno do produto de origem e não tem
    por que atravessar até o navegador do cliente.
    """
    rotulos: dict[str, str] = {}
    for posicao, inv in enumerate(inversores, start=1):
        sn = _texto(inv.get("sn")) or _texto(inv.get("serial_number"))
        if sn is None:
            continue
        rotulos[sn] = _texto(inv.get("slot_label")) or f"Inversor {posicao}"
    return rotulos


def _grupos_de_uc(
    transformadores: list[dict[str, Any]], inversores: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Uma entrada por UC, na ordem em que o monitoramento as devolve, mais o "Sem UC".

    O grupo extra só nasce quando há inversor órfão. Ele existe porque a soma das UCs
    tem de fechar com a geração da usina: um inversor descartado por não ter
    transformador cadastrado sumiria da conta sem deixar rastro.
    """
    grupos: list[dict[str, Any]] = []
    por_id: dict[Any, dict[str, Any]] = {}
    por_nome: dict[str, dict[str, Any]] = {}

    for t in transformadores:
        nome = _texto(t.get("name")) or "UC sem nome"
        grupo = {
            "nome": nome,
            "kwp": _numero(t.get("total_capacity_kwp")),
            "energia_kwh": _numero(t.get("total_yield_kwh")),
            "inversores_declarados": t.get("inverter_count"),
            "sns": [],
            "membros": [],
            "bruto": t,
        }
        grupos.append(grupo)
        if t.get("id") is not None:
            por_id[t["id"]] = grupo
        por_nome[nome] = grupo

    orfaos: dict[str, Any] | None = None
    for inv in inversores:
        alvo = por_id.get(inv.get("transformer_id"))
        if alvo is None:
            nome = _texto(inv.get("transformer_name"))
            alvo = por_nome.get(nome) if nome else None
        if alvo is None:
            if orfaos is None:
                orfaos = {
                    "nome": SEM_UC,
                    "kwp": None,
                    "energia_kwh": None,
                    "inversores_declarados": None,
                    "sns": [],
                    "membros": [],
                    "bruto": {},
                }
                grupos.append(orfaos)
            alvo = orfaos
        alvo["membros"].append(inv)
        sn = _texto(inv.get("sn")) or _texto(inv.get("serial_number"))
        if sn:
            alvo["sns"].append(sn)

    # Energia e capacidade que o monitoramento NÃO trouxe prontas saem da soma dos
    # próprios inversores do grupo. Vale para o "Sem UC", que nunca vem pronto — é a
    # única fonte que ele tem —, e vale também para uma UC de verdade cujo transformador
    # veio sem `total_yield_kwh`: sem isso ela sairia em travessão com os inversores dela
    # medindo, e a soma das UCs deixaria de fechar com a geração da usina, que é
    # justamente a conferência que o dono faz de olho. Sobrepor número que o upstream JÁ
    # deu seria o contrário — duas contas para o mesmo valor, divergindo com o tempo.
    for grupo in grupos:
        if not grupo["membros"]:
            continue
        if grupo["energia_kwh"] is None:
            medidas = [
                e
                for e in (
                    _numero(i.get("daily_yield_kwh")) if "daily_yield_kwh" in i
                    else _numero(i.get("total_yield_kwh"))
                    for i in grupo["membros"]
                )
                if e is not None
            ]
            grupo["energia_kwh"] = sum(medidas) if medidas else None
        if grupo["kwp"] is None:
            conhecidas = [
                c
                for c in (_numero(i.get("capacity_kwp")) for i in grupo["membros"])
                if c is not None
            ]
            grupo["kwp"] = sum(conhecidas) if conhecidas else None

    return grupos


def _faisca_por_uc(
    pontos: list[dict[str, Any]], sn_por_uc: list[list[str]]
) -> tuple[list[str], list[list[float | None]]]:
    """Curva de cada UC reamostrada em fatias de `PASSO_FAISCA_MIN`.

    Devolve as horas das fatias **uma vez** e, para cada UC, a lista alinhada a elas.
    Alinhar importa: sem isso, a posição 4 de uma UC seria 09h e a de outra 11h, e as
    faíscas da tabela não se comparariam.

    Fatia em que a UC não teve nenhum inversor medindo vira `None`, não 0 — é lacuna de
    comunicação, e um vale desenhado no lugar diria "parou" para quem só olha a linha.
    """
    if not pontos or not sn_por_uc:
        return [], [[] for _ in sn_por_uc]

    uc_por_sn: dict[str, int] = {}
    for indice, sns in enumerate(sn_por_uc):
        for sn in sns:
            uc_por_sn[sn] = indice

    # fatia "HH:MM" → por UC → (soma de kW, nº de buckets somados)
    somas: dict[str, dict[int, list[float]]] = {}
    ordem: list[str] = []
    for p in pontos:
        hora = _texto(p.get("time"))
        if hora is None or len(hora) < 5:
            continue
        try:
            hh, mm = int(hora[:2]), int(hora[3:5])
        except ValueError:
            continue
        fatia = f"{hh:02d}:{(mm // PASSO_FAISCA_MIN) * PASSO_FAISCA_MIN:02d}"
        if fatia not in somas:
            somas[fatia] = {}
            ordem.append(fatia)

        # Um bucket de 5 min: soma por UC antes de acumular na fatia, senão a média
        # sairia por leitura de inversor em vez de por instante.
        no_bucket: dict[int, float] = {}
        for inv in _lista(p.get("inverters")):
            sn = _texto(inv.get("serial_number")) or _texto(inv.get("sn"))
            if sn is None:
                continue
            indice = uc_por_sn.get(sn)
            if indice is None:
                continue
            kw = _numero(inv.get("power_kw"))
            if kw is None:
                continue
            no_bucket[indice] = no_bucket.get(indice, 0.0) + kw
        for indice, kw in no_bucket.items():
            somas[fatia].setdefault(indice, []).append(kw)

    horas = sorted(ordem)
    faiscas: list[list[float | None]] = []
    for indice in range(len(sn_por_uc)):
        serie: list[float | None] = []
        for fatia in horas:
            valores = somas.get(fatia, {}).get(indice)
            serie.append(round(sum(valores) / len(valores), 2) if valores else None)
        faiscas.append(serie)
    return horas, faiscas


def _potencia_agora_por_uc(
    pontos: list[dict[str, Any]], sn_por_uc: list[list[str]]
) -> list[float | None]:
    """Potência de cada UC no ÚLTIMO bucket em que ela teve inversor medindo.

    Não é o último bucket do dia: à noite ninguém publica, e ler dali daria `None` para
    todo mundo. Também não é o último valor positivo — a UC que acabou de cair mostra
    zero, que é a verdade, e não a potência de meia hora atrás.
    """
    uc_por_sn: dict[str, int] = {}
    for indice, sns in enumerate(sn_por_uc):
        for sn in sns:
            uc_por_sn[sn] = indice

    ultima: list[float | None] = [None] * len(sn_por_uc)
    for p in pontos:
        no_bucket: dict[int, float] = {}
        for inv in _lista(p.get("inverters")):
            sn = _texto(inv.get("serial_number")) or _texto(inv.get("sn"))
            if sn is None:
                continue
            indice = uc_por_sn.get(sn)
            if indice is None:
                continue
            kw = _numero(inv.get("power_kw"))
            if kw is None:
                continue
            no_bucket[indice] = no_bucket.get(indice, 0.0) + kw
        for indice, kw in no_bucket.items():
            ultima[indice] = round(kw, 2)
    return ultima


def _curva_da_usina(intraday: Any) -> tuple[list[PontoCurva], bool]:
    """Soma dos inversores por bucket + se a usina tem estação.

    Bucket em que ninguém mediu não vira ponto: é lacuna, não zero. E a estação é
    decidida olhando o dia inteiro — o upstream preenche `poa` com 0 quando não há
    sensor, e um dia inteiro de zeros desenhado vira uma linha rasteira com cara de
    medição.
    """
    curva: list[PontoCurva] = []
    tem_estacao = False
    for p in _lista(intraday.get("points") if isinstance(intraday, dict) else None):
        hora = _texto(p.get("time"))
        if hora is None:
            continue
        soma = 0.0
        mediu = False
        for inv in _lista(p.get("inverters")):
            kw = _numero(inv.get("power_kw"))
            if kw is not None:
                soma += kw
                mediu = True
        poa = _numero(p.get("poa"))
        if poa is not None and poa > 0:
            tem_estacao = True
        if not mediu and (poa is None or poa <= 0):
            continue
        curva.append(PontoCurva(hora=hora, kw=round(soma, 2), poa=poa))

    if not tem_estacao:
        for ponto in curva:
            ponto.poa = None
    return curva, tem_estacao


def _eventos(alertas: list[dict[str, Any]], rotulos: dict[str, str]) -> list[EventoDoDia]:
    """`alert_timeline` do dia → a tabela de eventos, sem serial nem id de inversor."""
    saida: list[EventoDoDia] = []
    for a in alertas:
        inicio = _texto(a.get("started_at"))
        if inicio is None:
            continue
        sn = _texto(a.get("sn")) or ""
        rotulo = _texto(a.get("slot_label")) or rotulos.get(sn) or "Inversor"
        resolvido = _texto(a.get("resolved_at"))
        saida.append(
            EventoDoDia(
                hora=_hora_curta(inicio),
                inversor=rotulo,
                evento=(
                    _texto(a.get("notification"))
                    or _texto(a.get("message"))
                    or "Parada do inversor"
                ),
                duracao_min=_arredondar(_numero(a.get("duration_minutes")), 1),
                resolvido_em=_hora_curta(resolvido) if resolvido else None,
                em_curso=bool(a.get("is_active")) or resolvido is None,
            )
        )
    saida.sort(key=lambda e: e.hora)
    return saida


def _tem_estacao_no_cadastro(atual: Any) -> bool | None:
    """A usina tem estação solarimétrica CADASTRADA? `None` = não deu para saber.

    Lê a mesma lista `weather_stations` de `monitoring/current` que a tela de equipamentos
    monta (`equipamentos._estacoes`) — o cadastro do ativo, não a medição do dia. A
    resposta é "de agora", e é assim que tem de ser: a estação é um APARELHO instalado na
    usina, e ela não passa a não existir num dia em que não mediu.

    `None` (a leitura falhou) é diferente de `False`: quem chama volta à régua antiga — a
    de haver irradiação no dia — em vez de afirmar ausência que não conferiu.
    """
    if not isinstance(atual, dict):
        return None
    estacoes = atual.get("weather_stations")
    if not isinstance(estacoes, list):
        return None
    return any(isinstance(e, dict) for e in estacoes)


def _hora_curta(instante: str) -> str:
    """"2026-08-14T09:32:00-03:00" → "09:32". Formato desconhecido volta como veio."""
    if "T" in instante and len(instante) >= 16:
        return instante[11:16]
    return instante


# ── rota · o dia ────────────────────────────────────────────────────────────


@router.get("/usinas/{plant_link_id}/dia", response_model=DiaOut)
async def dia_da_usina(
    plant_link_id: int,
    data: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> DiaOut:
    """A operação de um dia: números do dia, curva de potência e irradiância, eventos e
    a tabela por unidade consumidora.

    Três leituras em paralelo, e só a primeira é indispensável: os números do dia
    (`generation/daily`), a curva (`charts/intraday`) e o CADASTRO dos ativos
    (`monitoring/current`), de onde sai apenas a resposta "esta usina tem estação
    solarimétrica?". A terceira entrou porque a existência de um aparelho não pode ser
    deduzida da medição de um dia: às 03h10 não há sol, e a régua antiga fazia a tela
    escrever "esta usina não tem estação solarimétrica" sobre uma usina que tem — e que na
    véspera mediu 7,1 kWh/m².

    Uma queda do monitoramento vira 200 com `aviso` e campos nulos — a tela mostra
    travessão e diz o que faltou, em vez de uma página de erro ou, pior, de zeros.
    """
    link = _usina_monitorada(db, usuario, plant_link_id)
    referencia = _referencia_pedida(data)
    saida = DiaOut(dia=referencia.isoformat())

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        diario, intraday, atual = await asyncio.gather(
            cliente.geracao_diaria(link.mw_plant_slug, referencia),
            cliente.intraday(link.mw_plant_slug, referencia),
            # O CADASTRO dos ativos — daqui sai só a resposta "esta usina tem estação
            # solarimétrica?". É a mesma leitura que a tela de equipamentos já faz, e ela
            # entra porque a existência do aparelho não pode ser deduzida da medição do
            # dia: às 03h10 não há sol, e a régua antiga negava a estação de Porto
            # Ferreira, que existe e mediu 7,1 kWh/m² na véspera.
            cliente.monitoramento_atual(link.mw_plant_slug),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Monitoramento indisponível: {exc}"
        return saida

    if isinstance(diario, BaseException) or not isinstance(diario, dict):
        motivo = diario if isinstance(diario, BaseException) else "resposta inesperada"
        saida.aviso = f"Monitoramento indisponível: {motivo}"
        return saida
    if isinstance(intraday, BaseException) or not isinstance(intraday, dict):
        # A curva é acessório: sem ela ainda há números do dia, eventos e energia por UC.
        saida.aviso = "A curva do dia não veio; os números do dia continuam valendo."
        intraday = {}

    inversores = _lista(diario.get("inverters"))
    pontos = _lista(intraday.get("points"))

    saida.gerado_kwh = _arredondar(_numero(diario.get("total_generation_kwh")))
    saida.disponibilidade_pct = _arredondar(_numero(diario.get("availability_real_pct")))
    saida.inversores_total = len(inversores) or None

    # DUAS perguntas, dois campos. "Existe estação?" é cadastro e vem de
    # `monitoring/current`; "mediu hoje?" é o dia e vem da irradiação da curva. Enquanto
    # eram um campo só, um pedido às 03h10 respondia "esta usina não tem estação
    # solarimétrica" sobre a MESMA usina que no dia anterior devolveu hpoa 7,1.
    saida.curva, saida.estacao_com_leitura = _curva_da_usina(intraday)
    cadastrada = _tem_estacao_no_cadastro(atual)
    saida.estacao_indefinida = cadastrada is None
    saida.tem_estacao = saida.estacao_com_leitura if cadastrada is None else cadastrada
    if saida.curva:
        pico = max(saida.curva, key=lambda p: p.kw)
        saida.pico_kw = pico.kw
        saida.pico_hora = pico.hora

    # "Agora" é o último bucket com leitura de inversor — não o último do dia, que à
    # noite vem vazio, nem o de maior potência.
    for p in pontos:
        medindo = [k for k in (_numero(i.get("power_kw")) for i in _lista(p.get("inverters"))) if k is not None]
        if not medindo:
            continue
        poa = _numero(p.get("poa"))
        saida.potencia_agora_kw = round(sum(medindo), 2)
        saida.inversores_gerando = sum(1 for k in medindo if k > PISO_GERANDO_KW)
        saida.hpoa_agora = poa if saida.estacao_com_leitura else None

    # Os NÚMEROS medidos seguem a leitura, não o cadastro: o upstream devolve `0.0` de
    # irradiação tanto para a usina sem sensor quanto para a madrugada de quem tem, e
    # publicar esse zero seria dar a ele o peso de medição. Estação cadastrada sem leitura
    # ainda no dia sai em travessão — com `estacao_com_leitura` falso ao lado, que é o que
    # deixa a tela escrever "a estação ainda não mediu hoje".
    if saida.estacao_com_leitura:
        irradiacao = diario.get("irradiation")
        if isinstance(irradiacao, dict):
            saida.hpoa_acumulada = _arredondar(_numero(irradiacao.get("hpoa")))
            saida.ghi_acumulada = _arredondar(_numero(irradiacao.get("hghi")))
        pr_flag = _texto(diario.get("pr_flag"))
        if pr_flag:
            # O meuWatt descartou a leitura do dia. `None` + a bandeira: a tela escreve
            # "descartada". O `performance_ratio` que vem junto é 0 fabricado.
            saida.pr_descartado = True
        else:
            pr = _numero(diario.get("performance_ratio"))
            saida.pr_pct = _arredondar(pr * 100, 1) if pr else None

    saida.eventos = _eventos(
        _lista(diario.get("alert_timeline")), _rotulos_de_inversor(inversores)
    )

    grupos = _grupos_de_uc(_lista(diario.get("transformers")), inversores)
    sn_por_uc = [g["sns"] for g in grupos]
    saida.faisca_horas, faiscas = _faisca_por_uc(pontos, sn_por_uc)
    potencias = _potencia_agora_por_uc(pontos, sn_por_uc)

    for indice, grupo in enumerate(grupos):
        membros = grupo["membros"]
        ok = sum(
            1
            for i in membros
            if not i.get("is_faulty") and (_numero(i.get("daily_yield_kwh")) or 0) > 0
        )
        declarados = grupo["inversores_declarados"]
        total = len(membros) or (declarados if isinstance(declarados, int) else 0)
        kwp = grupo["kwp"]
        potencia = potencias[indice]
        saida.ucs.append(
            UnidadeDoDia(
                indice=indice,
                nome=grupo["nome"],
                kwp=_arredondar(kwp),
                inversores=total,
                potencia_agora_kw=potencia,
                pct_capacidade=(
                    _arredondar(min(100.0, max(0.0, potencia / kwp * 100)), 1)
                    if potencia is not None and kwp
                    else None
                ),
                energia_kwh=_arredondar(grupo["energia_kwh"]),
                ok=ok,
                total=total,
                faisca=faiscas[indice],
            )
        )

    if not saida.curva and saida.gerado_kwh is None and saida.aviso is None:
        saida.aviso = "O monitoramento não devolveu leitura para este dia."
    return saida


# ── rota · unidades consumidoras ────────────────────────────────────────────


def _fechar_participacao_em_cem(ucs: list[UnidadeDoPeriodo]) -> None:
    """Faz a coluna de participação somar exatamente 100,0 % — maior resto.

    Arredondar cada UC isoladamente para uma casa dava uma coluna que o cliente soma com o
    dedo e não fecha: Porto Ferreira publicava **100,1 %** em cinco UCs e Tietê 99,9 % —
    "quanto desta usina é meu?" respondida por uma tabela que se desmente sozinha.

    O ajuste é de arredondamento, nunca de dado: distribui os décimos que sobram entre as
    UCs de maior resto, uma casa decimal por vez. A soma dos `geracao_kwh` (o número que é
    medição) não é tocada. Sem participação medida em alguma UC, nada é ajustado — não se
    fecha em 100 % uma coluna que já está incompleta.
    """
    com_share = [u for u in ucs if u.share_pct is not None]
    if not com_share or len(com_share) != len(ucs):
        return
    decimos = [round((u.share_pct or 0.0) * 10) for u in com_share]
    sobra = 1000 - sum(decimos)
    if sobra:
        # Quem tem mais energia absorve o décimo sobrando — o maior número é o que menos
        # se altera em termos relativos.
        ordem = sorted(
            range(len(com_share)),
            key=lambda i: com_share[i].geracao_kwh or 0.0,
            reverse=(sobra > 0),
        )
        passo = 1 if sobra > 0 else -1
        for i in range(abs(sobra)):
            decimos[ordem[i % len(ordem)]] += passo
    for uc, d in zip(com_share, decimos, strict=True):
        uc.share_pct = round(d / 10, 1)


def _serie_da_uc(bruto: dict[str, Any]) -> dict[str, float]:
    """`transformers[].daily_generation` → {data: kWh}. Ausente = dicionário vazio."""
    serie: dict[str, float] = {}
    for ponto in _lista(bruto.get("daily_generation")):
        dia = _texto(ponto.get("t"))
        valor = _numero(ponto.get("y"))
        if dia is None or valor is None:
            continue
        serie[dia[:10]] = serie.get(dia[:10], 0.0) + valor
    return serie


def _faturado_por_uc(
    faturas: Any, inicio: date, fim: date
) -> tuple[dict[Any, float], dict[str, float], bool]:
    """MWh faturados no período, por id de transformador — e o mesmo por NOME, quando o
    upstream o oferece.

    O id não sai daqui: serve só para casar a fatura com a UC dentro do BFF. O terceiro
    valor diz se alguma fatura foi encontrada — nenhuma não é erro, é fatura ainda não
    emitida.
    """
    por_id: dict[Any, float] = {}
    por_nome: dict[str, float] = {}
    achou = False
    itens = faturas.get("bills") if isinstance(faturas, dict) else faturas
    for b in _lista(itens):
        ano, mes = b.get("year"), b.get("month")
        if not isinstance(ano, int) or not isinstance(mes, int):
            continue
        if not (inicio.year, inicio.month) <= (ano, mes) <= (fim.year, fim.month):
            continue
        mwh = _numero(b.get("billed_mwh"))
        if mwh is None:
            continue
        achou = True
        if b.get("transformer_id") is not None:
            por_id[b["transformer_id"]] = por_id.get(b["transformer_id"], 0.0) + mwh
        nome = _texto(b.get("transformer_name"))
        if nome:
            por_nome[nome] = por_nome.get(nome, 0.0) + mwh
    return por_id, por_nome, achou


def unidades_do_periodo(
    relatorio: dict[str, Any],
    faturas: Any,
    *,
    recorte: str,
    inicio: date,
    fim: date,
) -> UnidadesOut:
    """O comparativo por UC a partir do `generation/range` — sem tocar na rede.

    Está fora da rota de propósito: é o quarto recorte do painel de energia — a mesma
    pergunta do Mensal e do Anual, vista por unidade consumidora — e ganhou endereço
    próprio para a tela carregá-lo sem arrastar o resto do painel. A conta mora aqui, em
    um lugar só: duas contas para o mesmo comparativo divergiriam com o tempo.
    """
    saida = UnidadesOut(recorte=recorte, inicio=inicio.isoformat(), fim=fim.isoformat())
    grupos = _grupos_de_uc(
        _lista(relatorio.get("transformers")), _lista(relatorio.get("inverters"))
    )
    por_id, por_nome, achou_fatura = _faturado_por_uc(faturas, inicio, fim)

    total_gerado = 0.0
    tem_geracao = False
    for grupo in grupos:
        # A energia que o upstream não trouxe pronta já veio somada dos membros dentro de
        # `_grupos_de_uc` — refazê-la aqui seria a segunda conta do mesmo número.
        if grupo["energia_kwh"] is not None:
            total_gerado += grupo["energia_kwh"]
            tem_geracao = True

    dias = sorted({d for g in grupos for d in _serie_da_uc(g["bruto"])})
    capacidades: list[float] = []
    faltou_fatura = False

    for indice, grupo in enumerate(grupos):
        bruto = grupo["bruto"]
        energia = grupo["energia_kwh"]
        kwp = grupo["kwp"]
        if kwp is not None:
            capacidades.append(kwp)

        produtividade = _numero(bruto.get("productivity"))
        if produtividade is None and energia is not None and kwp:
            produtividade = energia / kwp
        pr = _numero(bruto.get("performance_ratio"))

        faturado = por_id.get(bruto.get("id"))
        if faturado is None:
            faturado = por_nome.get(grupo["nome"])
        if faturado is None and grupo["nome"] != SEM_UC:
            faltou_fatura = True

        declarados = bruto.get("inverter_count")
        saida.ucs.append(
            UnidadeDoPeriodo(
                indice=indice,
                nome=grupo["nome"],
                capacidade_kwp=_arredondar(kwp),
                inversores=len(grupo["membros"])
                or (declarados if isinstance(declarados, int) else 0),
                geracao_kwh=_arredondar(energia),
                share_pct=(
                    _arredondar(energia / total_gerado * 100, 1)
                    if energia is not None and total_gerado > 0
                    else None
                ),
                produtividade=_arredondar(produtividade),
                # PR chega como razão 0–1 e sai em %. Zero não é PR medido: é o campo
                # ausente do upstream, e vira travessão.
                pr_pct=_arredondar(pr * 100, 1) if pr else None,
                disponibilidade_real_pct=_arredondar(
                    _numero(bruto.get("availability_real_pct"))
                ),
                disponibilidade_contratual_pct=_arredondar(
                    _numero(bruto.get("availability_contratual_pct"))
                ),
                faturado_mwh=_arredondar(faturado, 3),
            )
        )
        serie = _serie_da_uc(bruto)
        if serie:
            saida.serie.append(
                SerieDaUnidade(
                    indice=indice,
                    nome=grupo["nome"],
                    valores=[_arredondar(serie.get(d)) for d in dias],
                )
            )

    saida.serie_dias = dias
    saida.ucs_ativas = len(saida.ucs)
    saida.capacidade_total_kwp = _arredondar(sum(capacidades)) if capacidades else None
    saida.energia_periodo_kwh = _arredondar(total_gerado) if tem_geracao else None
    _fechar_participacao_em_cem(saida.ucs)

    if saida.ucs and tem_geracao:
        maior = max(saida.ucs, key=lambda u: u.geracao_kwh or 0.0)
        if maior.geracao_kwh is not None:
            saida.maior = MaiorUnidade(nome=maior.nome, share_pct=maior.share_pct)

    def _ordem(chave) -> list[int]:
        """Só entra no ranking quem tem o número. UC sem PR fica de fora da lista de
        PR — em vez de aparecer no fim como se tivesse zero."""
        com_dado = [u for u in saida.ucs if chave(u) is not None]
        return [u.indice for u in sorted(com_dado, key=lambda u: chave(u), reverse=True)]

    saida.ranking_geracao = _ordem(lambda u: u.geracao_kwh)
    saida.ranking_pr = _ordem(lambda u: u.pr_pct)
    saida.ranking_produtividade = _ordem(lambda u: u.produtividade)

    if achou_fatura:
        saida.faturas_situacao = "Parcial" if faltou_fatura else "Emitida"
    if not saida.ucs:
        saida.aviso = "O monitoramento não devolveu unidades consumidoras nesta usina."
    return saida


@router.get("/usinas/{plant_link_id}/unidades", response_model=UnidadesOut)
async def unidades_da_usina(
    plant_link_id: int,
    recorte: str = "mes",
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> UnidadesOut:
    """Comparativo entre as unidades consumidoras da usina, no mês ou no ano.

    É o recorte `unidades` do painel de energia — a mesma conta, servida também por
    endereço próprio para a tela poder carregá-lo sem o resto do painel.
    """
    if recorte not in ("mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'mes' ou 'ano'.")

    link = _usina_monitorada(db, usuario, plant_link_id)
    inicio, fim = _janela(recorte, _referencia_pedida(referencia))
    # Até hoje, e não até o fim do período: o `range` fabrica dias vazios no futuro, e
    # eles entrariam na série diária por UC como buracos que não existem.
    fim = min(fim, hoje_na_usina())

    vazio = UnidadesOut(recorte=recorte, inicio=inicio.isoformat(), fim=fim.isoformat())
    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001
        vazio.aviso = f"Monitoramento indisponível: {exc}"
        return vazio

    relatorio, faturas = await asyncio.gather(
        cliente.geracao_periodo(link.mw_plant_slug, inicio, fim),
        # Mês e ano cabem sempre dentro de um ano civil, então o ano vai no pedido: sem
        # ele o upstream devolve o histórico inteiro de faturas para o BFF recortar um
        # ano dele.
        cliente.faturas_concessionaria(link.mw_plant_slug, inicio.year),
        return_exceptions=True,
    )
    if isinstance(relatorio, BaseException) or not isinstance(relatorio, dict):
        motivo = relatorio if isinstance(relatorio, BaseException) else "resposta inesperada"
        vazio.aviso = f"Monitoramento indisponível: {motivo}"
        return vazio
    if isinstance(faturas, BaseException):
        # A conta de energia é acessório: sem ela a coluna fica em travessão, e o
        # comparativo entre UCs continua de pé.
        faturas = []

    return unidades_do_periodo(
        relatorio, faturas, recorte=recorte, inicio=inicio, fim=fim
    )


# ════════════════════════════════════════════════════════════════════════════
# O PAINEL — o dashboard do meuWatt no mês e no ano
# ════════════════════════════════════════════════════════════════════════════
#
# Quase tudo do Mensal e do Anual sai de UMA resposta do meuWatt
# (`generation/range`) cruzada com o projeto (PVsyst), a fronteira (SSU) e as faturas. E é
# exatamente por isso que o recorte acontece aqui: aquela resposta carrega
# `chart_data.daily_generation` indexado por NÚMERO DE SÉRIE, `transformers[].id`,
# `alert_timeline[].sn` e `daily_pr_flags` com o nome interno do descarte — estrutura de
# outro sistema, que não tem por que atravessar a ponte nem prender a tela a um formato
# que não é nosso. Um ano de uma usina de vinte inversores também é payload grande; o
# upstream limita a 366 dias e cacheia dez minutos porque a resposta é cara.
#
# CINCO DECISÕES DECLARADAS, porque cada uma tinha duas saídas defensáveis:
#
# 0. UMA JANELA SÓ, E ELA VIAJA NA RESPOSTA. Todo acumulado do painel — medido, projeto,
#    previsto, perdida, fronteira, faturado, irradiação — soma os MESMOS meses, e a lista
#    deles sai em `janela` para a tela poder dizer de onde o número veio. A janela é a de
#    `/plants/{id}/desempenho`, chamando a MESMA função (`plants._meses_medidos`), e o
#    projeto é a MESMA meta (`plants._esperado_diario_por_mes`/`_esperado_manual_por_mes`,
#    em `e_grid`): "a usina está batendo o projeto?" é uma pergunta só e não pode ter duas
#    respostas no mesmo portal. Enquanto teve, Porto Ferreira/2026 exibia 36 % de
#    atingimento no painel e 101,7 % na tela de desempenho — e o desencontro aparecia nas
#    sete usinas. O mês em curso ENTRA, com a meta rateada até hoje (é o que a tela de
#    desempenho faz, e é por isso que o cartão passou a fechar com a soma da coluna). A
#    única conta com janela própria é a conciliação, que depende de a fatura já existir —
#    e ela declara a dela em `conciliacao.meses`.
#
# 1. DISPONIBILIDADE. Vale o número PRONTO do upstream (`availability_real_pct` e
#    `availability_contratual_pct`) — a mesma régua que `/plants/{id}/desempenho` já usa.
#    Nada é recalculado aqui; existe um segundo caminho no meuWatt (re-derivar de
#    `daily_summaries`) e os dois discordam em pontos percentuais no mesmo mês.
#
#    O detalhe que só a produção revelou: o `monthly_summaries[]` do `range` do ANO **não
#    é** esse número. Em Porto Ferreira, agosto de 2026, o rollup do ano dizia 99,99 % e o
#    cabeçalho do `range` de agosto — o que a tela de desempenho publica — dizia 99,89 %.
#    Ler o rollup faria o cliente ver um valor no mês e outro no ano para o MESMO mês, num
#    número de teor contratual. Por isso a linha do ano é CONFERIDA mês a mês
#    (`_conferir_disponibilidade_mensal`): as mesmas leituras que o recorte `mes` faz, em
#    paralelo, só nos meses medidos, com o rollup de rede de segurança. O campo `regra`
#    viaja na resposta para a tela declarar a fórmula ao lado do número.
#
# 2. PREVISTO PELA METEOROLOGIA. Sai sempre que existir, com `previsto_origem` dizendo se
#    veio do PVsyst diário ou da correção manual (EARRAY × irradiação medida ÷ irradiação
#    do projeto). O meuWatt esconde o card quando a origem é a manual; aqui ele aparece
#    com a procedência escrita, porque esconder do cliente um número que existe é pior do
#    que mostrá-lo dizendo de onde veio. Ausente continua ausente — nulo, nunca zero.
#
# 3. FRONTEIRA QUE NÃO COBRE A USINA. O total do medidor é real e pode ser PARCIAL (ver
#    `PERDA_FRONTEIRA_MAX_PCT`). Quando a diferença para os inversores não cabe numa perda
#    de transformação e linha, o número continua saindo — é medição —, mas marcado com
#    `fronteira_parcial` e sem a subtração: chamar 20 % de "perda" seria inventar um
#    diagnóstico, e classificar isso como divergência de fatura mandaria o cliente cobrar
#    da distribuidora um defeito do aparelho dele.
#
# 4. SENTINELA DE TEMPERATURA. O relé marca ausência com número — `-100.0` e `0.0` —, e nem
#    o mw-api nem o dashboard do meuWatt filtram. Some o que é fisicamente impossível (por
#    ponto) e o campo cuja série INTEIRA do período é zero cravado (por série, ver
#    `TEMPERATURA_CAMPOS`); uma leitura plausível qualquer e tudo atravessa como veio,
#    porque corrigir medição plausível seria inventar dado.


#: Tolerância contratual da conciliação com a conta de energia, em pontos percentuais. É a
#: mesma do meuWatt, e vai na resposta para a tela escrevê-la ao lado do resultado em vez
#: de repetir a constante em TypeScript.
TOLERANCIA_CONCILIACAO_PCT = 1.0

#: Faixa terrestre da temperatura, em °C. O relé de temperatura marca ausência com
#: SENTINELA NUMÉRICA, e nem o mw-api nem o dashboard do meuWatt a filtram. Porto
#: Ferreira, agosto de 2026, devolveu sete leituras — seis em `0.0` e uma em `-100.0` — e
#: a média que sairia na tela do cliente era **−14,3 °C**.
#:
#: O corte aqui é o único que se sustenta em fato, não em palpite: −100 °C não existe em
#: lugar nenhum do planeta (o recorde mundial de frio é −89,2 °C, na Antártida; o de
#: calor, 56,7 °C). O que cai fora da faixa é ausência de leitura e vira nulo. O que está
#: dentro atravessa como veio: "corrigir" medição plausível seria inventar dado.
TEMPERATURA_MIN_C = -90.0
TEMPERATURA_MAX_C = 90.0

#: O OUTRO SENTINELA DO MESMO RELÉ: `0.0` exato. Filtrar só o −100 deixava passar o zero, e
#: o recorte `ano` de Porto Ferreira publicava "TEMPERATURA AMBIENTE 0,0 °C, máxima 0,0 °C"
#: ao lado de "TEMPERATURA DO MÓDULO 33,8 °C" — e 0,0 nas linhas de julho e agosto da tabela
#: meteorológica. Medido no upstream para 2026 inteiro: das 13 leituras de `t_amb` que
#: existem, os únicos valores são `0.0` (12 vezes) e `-100.0` (1 vez); NENHUMA na faixa
#: plausível. Zero graus num agosto do interior paulista é indefensável diante da diretoria
#: do cliente, e num painel que em todo o resto sabe dizer "não sei" era o único número
#: inventado.
#:
#: ⛔ A régua é POR SÉRIE, nunca por ponto — e é o que a torna honesta. Descartar todo `0.0`
#: apagaria uma medição legítima (existe 0 °C em serra no inverno). O que não existe é uma
#: série INTEIRA de zeros exatos: sensor que mede oscila. Então o campo é anulado apenas
#: quando, depois de tirados os impossíveis, TUDO o que sobrou do período é zero exato. Uma
#: única leitura diferente e os zeros voltam a valer, porque aí eles podem ser reais.
#:
#: O conserto do relé é na origem; aqui o dever é não repassar o defeito como medição.
TEMPERATURA_CAMPOS = ("t_amb", "t_amb_max", "t_mod", "t_mod_max")

#: Faixa plausível da perda entre o inversor e o ponto de entrega, em %. É perda de
#: transformação e de linha; a referência de projeto do próprio meuWatt é 1,50 %, e nem
#: uma usina malcuidada chega a dois dígitos.
#:
#: Fora desta faixa os dois números não estão medindo o mesmo conjunto. O total da
#: fronteira vem de `MAX(leitura) − MIN(leitura)` por medidor dentro do mês (mw-api,
#: `ssu-readers/monthly-totals`): medidor instalado no meio do período, medidor a menos ou
#: leitura falhada devolvem um total REAL e PARCIAL. Porto Ferreira mediu 846 MWh na
#: fronteira contra 1.065 MWh nos inversores em agosto de 2026 — "perda de 20,5 %" — e
#: 166 MWh contra 963 MWh em julho, que daria "perda de 82,8 %". Publicar isso como perda
#: repetiria, com número de verdade, o erro do antigo `medido × 0,987` que o meuWatt
#: removeu: um número inventado vestido de medição.
PERDA_FRONTEIRA_MIN_PCT = -1.0
PERDA_FRONTEIRA_MAX_PCT = 10.0

#: Quantos meses do recorte `ano` são conferidos ao mesmo tempo. A leitura de cada mês é a
#: MESMA que o recorte `mes` faz — o upstream a cacheia por dez minutos, e as duas telas
#: se aproveitam —, mas doze pedidos simultâneos por causa de uma tela é pressão gratuita.
CONFERENCIAS_SIMULTANEAS = 4

#: A janela em que um inversor DEVE estar de pé. Fora dela ele está desligado por projeto,
#: não por defeito — contar a noite como indisponibilidade pintaria de vermelho toda usina
#: do mundo. É o mesmo recorte do meuWatt (06h–18h, latitudes brasileiras).
HORA_SOLAR_INICIO = 6
HORA_SOLAR_FIM = 18

#: Nomes por extenso e curtos, para os rótulos do período.
_MESES = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
_MES_CURTO = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
              "Jul", "Ago", "Set", "Out", "Nov", "Dez")


# ── formato · painel ────────────────────────────────────────────────────────


class DesviosOut(BaseModel):
    """Os três desvios estruturais, COM SINAL: `(aferido − referência) ÷ referência`.

    Positivo = acima da referência. Lidos como "perda" eles vinham invertidos, e uma usina
    que batia o projeto exibia "perda de −3%" — duplo negativo que ninguém lê.
    """

    medido_vs_projeto_pct: float | None = None
    medido_vs_previsto_pct: float | None = None
    #: O efeito do clima: quanto a irradiação real afastou o previsto do projeto.
    previsto_vs_projeto_pct: float | None = None
    #: A COMPARAÇÃO DE IRRADIAÇÃO — medida contra a do projeto, nos dois planos. É o que
    #: separa "o sol não veio" de "a usina não rendeu": os três desvios acima comparam
    #: energia, e sozinhos não dizem qual das duas coisas aconteceu. O dashboard de origem
    #: mostra estas duas caixas no lugar das de previsto quando a usina tem POA/GHI de
    #: projeto cadastrados; aqui elas convivem, porque esconder informação que existe é o
    #: contrário do que o dono pediu ("com todas as informações").
    hpoa_vs_projeto_pct: float | None = None
    ghi_vs_projeto_pct: float | None = None


class ConciliacaoOut(BaseModel):
    """Fronteira medida × fatura emitida. É a receita do proprietário, não um KPI."""

    fronteira_mwh: float | None = None
    faturado_mwh: float | None = None
    diferenca_mwh: float | None = None
    diferenca_pct: float | None = None
    #: `Conciliado` · `Pequena divergência` · `Divergência relevante`. Nulo quando falta um
    #: dos dois lados — fatura ainda não emitida é ESTADO, não erro — e nulo também quando
    #: a fronteira é parcial: classificar cobertura incompleta como "divergência relevante"
    #: mandaria o cliente cobrar da distribuidora um erro que é do medidor dele.
    situacao: str | None = None
    tolerancia_pct: float = TOLERANCIA_CONCILIACAO_PCT
    #: Os meses ("YYYY-MM") que a conciliação cobre — os que têm medidor E fatura. Ela é a
    #: única conta do painel com janela PRÓPRIA, e por isso a declara: a fatura de um mês
    #: recém-fechado leva semanas para ser emitida, e somar a fronteira de um mês cuja
    #: fatura não existe inventaria uma "divergência" do tamanho daquele mês. Vazio no
    #: recorte `mes`, onde a janela é o próprio mês.
    meses: list[str] = []


class DiaDoMes(BaseModel):
    """Um dia do mês. `futuro` é o que faz a barra sair tracejada em vez de rasteira."""

    dia: int
    data: str
    medido_kwh: float | None = None
    projeto_kwh: float | None = None
    #: PR do dia em %. Nulo quando o dia não tem PR — e `pr_descartado` diz se foi o
    #: monitoramento que a descartou por implausibilidade. Dia sem PR NÃO vira 0%.
    pr_pct: float | None = None
    pr_descartado: bool = False
    futuro: bool = False


class MesDoAno(BaseModel):
    """Um mês do ano — a linha do detalhamento e da conciliação mês a mês."""

    mes: str
    rotulo: str
    medido_kwh: float | None = None
    projeto_kwh: float | None = None
    previsto_kwh: float | None = None
    desvio_vs_projeto_pct: float | None = None
    pr_pct: float | None = None
    disponibilidade_real_pct: float | None = None
    disponibilidade_contratual_pct: float | None = None
    perdida_kwh: float | None = None
    perdida_externa_kwh: float | None = None
    fronteira_mwh: float | None = None
    faturado_mwh: float | None = None
    #: De onde saiu a disponibilidade desta linha: `mes_conferido` (o cabeçalho do `range`
    #: daquele mês — a mesma leitura que o recorte `mes` e `/plants/{id}/desempenho?
    #: recorte=mes` publicam) ou `rollup_do_ano` (o `monthly_summaries`, rede de segurança
    #: de quando a leitura do mês não veio). Os dois discordam no upstream — Porto
    #: Ferreira, agosto/2026: 99,89 % contra 99,99 % —, e num número de teor contratual a
    #: tela precisa poder dizer de onde o dela saiu.
    disponibilidade_origem: str | None = None
    #: O mês entrou no acumulado do período (ver `PainelOut.janela`).
    no_acumulado: bool = False
    em_curso: bool = False
    futuro: bool = False


class MesForaDoAcumulado(BaseModel):
    """Um mês do período que NÃO entrou no acumulado, e por quê."""

    mes: str
    rotulo: str
    #: `futuro` (o mês ainda não começou) · `sem_medicao` (o monitoramento não mediu nada
    #: nele — série que ainda não começava, usina fora do ar) · `sem_detalhe_mensal` (há
    #: geração nos dias, mas o resumo mensal do upstream não traz o mês).
    motivo: str


class JanelaOut(BaseModel):
    """QUAIS meses entraram no acumulado — e quais ficaram de fora, com o motivo.

    Existe porque o conserto de um número sem dizer de onde ele saiu vira a próxima
    pergunta do cliente. É a mesma lição do relatório de manutenção do meuPlano, que dava
    duas respostas para "está sendo feito?" até declarar `meses_do_cronograma` e
    `meses_fora_do_cronograma`.

    **Todos os acumulados do painel saem desta janela** — medido, projeto, previsto,
    perdida, fronteira, faturado e irradiação. A única exceção declarada é a conciliação,
    que tem janela própria (`ConciliacaoOut.meses`) porque depende de a fatura já existir.
    """

    #: Os meses ("YYYY-MM") somados no acumulado, em ordem.
    meses: list[str] = []
    fora: list[MesForaDoAcumulado] = []
    #: "jun a set de 2026" — pronto para a tela escrever ao lado do número.
    rotulo: str | None = None
    #: A janela cobre menos do que o período pedido; a tela precisa dizer isso.
    parcial: bool = False
    regra: str


class TotaisOut(BaseModel):
    #: Medido, projeto e a razão entre eles — os três na MESMA janela (`PainelOut.janela`).
    medido_kwh: float | None = None
    #: O projeto do PERÍODO INTEIRO — a meta do ano/mês, futuro incluído. É a única linha
    #: do bloco fora da janela do acumulado, e está aqui de propósito: "quanto o projeto
    #: prevê para 2026" é outra pergunta, não a mesma comparada com meio ano de medição.
    projeto_kwh: float | None = None
    #: O projeto NA JANELA DO ACUMULADO — o par de `medido_kwh`, e o denominador do
    #: atingimento.
    projeto_ate_hoje_kwh: float | None = None
    #: Projeção linear do fechamento, só no período em curso. Nulo em período fechado:
    #: prever o passado não é previsão.
    tendencia_kwh: float | None = None


class PontoMeteo(BaseModel):
    #: `YYYY-MM-DD` no mês, `YYYY-MM` no ano.
    chave: str
    rotulo: str
    hpoa: float | None = None
    hpoa_projeto: float | None = None
    ghi: float | None = None
    #: A PARCELA do projeto no plano horizontal — a mesma que `meteo.ghi_projeto` soma.
    #: Ela existia no acumulado e não existia aqui: o cartão publicava
    #: `GHI 969,5 · projeto 988,2 kWh/m²` e o "Sol medido × projeto −1,9 %" saía dele, com
    #: a tabela abaixo sem uma única coluna de onde os 988,2 pudessem ter vindo. É o mesmo
    #: defeito que o HPOA tinha, consertado de um lado e deixado do outro na mesma página.
    ghi_projeto: float | None = None
    t_amb: float | None = None
    t_mod: float | None = None
    t_mod_max: float | None = None


class MeteoOut(BaseModel):
    """As condições do período. Sai da MESMA resposta da geração, sem chamada extra."""

    #: Sem estação solarimétrica não há irradiação medida — e sem ela não há PR. É o
    #: portão que faz a tela esconder o bloco em vez de desenhar quatro travessões.
    tem_estacao: bool = False
    #: A temperatura ambiente vem de relé; a do módulo, da estação. Uma pode faltar.
    tem_sensor_temperatura: bool = False
    hpoa: float | None = None
    ghi: float | None = None
    #: `hpoa ÷ ghi` — quanto o plano inclinado ganha sobre o horizontal.
    razao: float | None = None
    #: A irradiação de PROJETO do período, na MESMA janela do medido (ver
    #: `_irradiacao_de_projeto`). No plano dos módulos e no horizontal.
    #:
    #: No recorte `ano` ela só sai quando cobre TODOS os meses do acumulado: uma
    #: referência de quatro meses ao lado de uma medição de sete devolve "+176 % de sol",
    #: que foi o que a tela publicou. Referência incompleta não vira comparação.
    hpoa_projeto: float | None = None
    ghi_projeto: float | None = None
    #: `pvsyst_diario` ou `mensal_digitado`. O diário tem célula por dia/mês na tabela; o
    #: digitado é um número do mês inteiro e por isso a coluna sai em travessão — sem esta
    #: procedência o cliente via um "Acumulado do período" que não vinha de parcela
    #: nenhuma visível.
    hpoa_projeto_origem: str | None = None
    ghi_projeto_origem: str | None = None
    t_amb_media: float | None = None
    t_amb_max: float | None = None
    t_mod_media: float | None = None
    t_mod_max: float | None = None
    pontos: list[PontoMeteo] = []


class FaixaTecnica(BaseModel):
    """Um trecho contínuo de dias no mesmo estado — as duas pontas incluídas.

    A matriz do meuWatt é dia a dia, e foi assim que esta saiu na primeira volta: num ano
    de Porto Ferreira (20 inversores × 247 dias) a resposta pesava **246 KB**, mais do que
    os 223 KB do payload cru que este módulo existe para recortar. E era desperdício puro:
    cinco meses inteiros antes do início da série repetiam "sem dado" cinco mil vezes.
    Em faixas a mesma informação cabe em poucos quilobytes, sem perder um dia sequer — e é
    a forma que a barra desenhada realmente precisa, porque ela pinta trechos, não pontos.
    """

    de: str
    ate: str
    dias: int
    #: `operando` · `potencia_zero` · `falha_comunicacao` · `nao_instalado` · `sem_dado`.
    estado: str


class InversorTecnico(BaseModel):
    #: A etiqueta que o operador deu à POSIÇÃO. Nunca o número de série: ele identifica um
    #: aparelho no inventário de outro sistema e não diz nada ao dono da usina.
    nome: str
    disponibilidade_pct: float | None = None
    faixas: list[FaixaTecnica] = []


class DisponibilidadeTecnicaOut(BaseModel):
    """Tempo de pé por inversor — uma régua DIFERENTE da dos cartões.

    O aviso não é enfeite: os cartões medem disponibilidade ENERGÉTICA (kWh perdidos) e
    esta mede TEMPO. Os dois percentuais não batem, e publicá-los lado a lado sem dizer
    isso entregaria ao cliente dois números contraditórios num documento de teor
    contratual.
    """

    aviso: str
    #: As pontas do eixo, para a tela desenhar a barra sem ter de varrer as faixas.
    primeiro_dia: str
    ultimo_dia: str
    inversores: list[InversorTecnico] = []


class RegraOut(BaseModel):
    """As fórmulas em linguagem de cliente. A tela imprime; não recalcula nada."""

    disponibilidade: str
    contratual: str
    perda_distribuida: str
    origem: str


class PainelOut(BaseModel):
    recorte: str
    referencia: str
    inicio: str
    fim: str
    rotulo: str
    #: Período ainda aberto — há dias futuros, e o fechamento é projeção.
    em_curso: bool = False
    #: Dia do mês (recorte `mes`) até onde há medição. Nulo em período fechado.
    dia_de_corte: int | None = None

    capacidade_kwp: float | None = None

    # ── geração ──────────────────────────────────────────────────────────
    medido_inversores_kwh: float | None = None
    #: A medição do OUTRO aparelho (SSU), no ponto de entrega. Nulo sem medidor — e nunca
    #: o antigo `medido × 0,987`, que o próprio meuWatt removeu por ser um número
    #: inventado vestido de medição.
    medido_fronteira_kwh: float | None = None
    #: Quanto se perde entre o inversor e a fronteira, em %. Só com os dois medidos, e só
    #: quando a diferença entre eles é fisicamente uma perda (ver `PERDA_FRONTEIRA_MAX_PCT`).
    perda_inv_fronteira_pct: float | None = None
    #: A fronteira medida NÃO cobre a mesma usina que os inversores — medidor instalado no
    #: meio do período, medidor a menos, leitura falhada. O número continua saindo, porque
    #: é medição de verdade, mas a tela precisa rotulá-lo como parcial e não pode subtraí-lo
    #: do medido: a diferença não é perda.
    fronteira_parcial: bool = False
    #: Os meses da janela que REALMENTE têm leitura de medidor — a janela do acumulado de
    #: fronteira, que pode ser mais curta que a da geração. Em Porto Ferreira o cartão
    #: `MEDIDO (FRONTEIRA) 1.132,9 MWh` aparecia sob o rótulo "acumulado · jun a set", e a
    #: coluna somava jul+ago+set: junho está na janela e não tem medidor. Vazio ou igual à
    #: janela inteira = nada a declarar. Mesmo princípio de `conciliacao.meses`.
    fronteira_meses: list[str] = []
    #: A meta do PERÍODO INTEIRO (o mês fechado, o ano de doze meses) — o alvo, futuro
    #: incluído. Não é o denominador de nada: para comparar existe o proporcional.
    projeto_kwh: float | None = None
    #: A meta NA JANELA DO ACUMULADO (ver `janela`) — o par de `medido_inversores_kwh` e o
    #: denominador de `atingimento_pct` e de `desvios.medido_vs_projeto_pct`.
    projeto_proporcional_kwh: float | None = None
    #: `medido ÷ projeto` na janela, em %. É EXATAMENTE o `pct_do_projeto` de
    #: `/plants/{id}/desempenho` — mesma janela, mesma fonte (`e_grid`), mesmo
    #: arredondamento —, porque é a mesma pergunta feita pelo mesmo cliente no mesmo
    #: portal. Enquanto eram duas contas, Porto Ferreira/2026 exibia 36 % numa tela e
    #: 101,7 % na outra.
    atingimento_pct: float | None = None
    #: `pvsyst_diario`, `mensal_digitado` ou `misto` — de onde veio a meta. O diário tem
    #: célula por dia/mês na tabela; o digitado é um número do mês, e aí a coluna sai em
    #: travessão sem que o total esteja errado.
    projeto_origem: str | None = None
    previsto_kwh: float | None = None
    #: `pvsyst_diario` ou `manual_corrigido` — de onde veio o previsto.
    previsto_origem: str | None = None

    # ── performance ──────────────────────────────────────────────────────
    produtividade_kwh_kwp: float | None = None
    pr_pct: float | None = None
    disponibilidade_real_pct: float | None = None
    disponibilidade_contratual_pct: float | None = None
    #: Paradas ainda sem causa classificada. Enquanto houver, a contratual está incompleta.
    paradas_pendentes: int = 0
    perdida_kwh: float | None = None
    perdida_externa_kwh: float | None = None

    desvios: DesviosOut = DesviosOut()
    conciliacao: ConciliacaoOut = ConciliacaoOut()
    totais: TotaisOut = TotaisOut()
    meteo: MeteoOut = MeteoOut()
    #: De onde saíram os acumulados. A tela imprime; ver `JanelaOut`.
    janela: JanelaOut
    regra: RegraOut

    dias: list[DiaDoMes] = []
    meses: list[MesDoAno] = []

    #: Os meses do ano que TÊM medição, para o seletor pular os vazios. Preenchido só no
    #: recorte `ano`, que é onde a informação chega de graça — pedi-la no recorte `mes`
    #: custaria uma segunda leitura do ano inteiro a cada troca de mês, e é assim que o
    #: próprio meuWatt faz (o Anual alimenta o seletor do Mensal). Nulo = "não consultado
    #: neste recorte" (a tela libera os meses passados); `[]` = consultado e nenhum mês
    #: tem dado.
    meses_disponiveis: list[str] | None = None

    disponibilidade_tecnica: DisponibilidadeTecnicaOut | None = None

    aviso: str | None = None


_REGRA = RegraOut(
    disponibilidade=(
        "Disponibilidade = energia medida ÷ energia esperada, sendo a energia esperada a "
        "soma da energia medida com a energia perdida em paradas."
    ),
    contratual=(
        "A disponibilidade contratual desconta a energia perdida por causa externa — "
        "aquela que estava fora do alcance da manutenção."
    ),
    perda_distribuida=(
        "Uma parada que atravessa vários dias tem a perda distribuída entre eles, "
        "proporcional à luz de cada dia. Parada ainda sem causa classificada não entra na "
        "conta da disponibilidade contratual."
    ),
    origem=(
        "Os percentuais vêm prontos do monitoramento — a mesma conta que alimenta o "
        "restante do portal, para o mesmo mês não ter dois números."
    ),
)


# ── leitura do relatório do período ─────────────────────────────────────────


def _dicionario(valor: Any) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _data(valor: Any) -> date | None:
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if not isinstance(valor, str) or len(valor) < 10:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        return None


def _instante_local(valor: Any) -> datetime | None:
    """Instante ISO do upstream, no fuso da usina e SEM fuso declarado.

    O meuWatt carimba em UTC; a janela solar é local. Converter para o horário de Brasília
    antes de descartar o fuso é o que faz uma parada das 15h aparecer no dia certo — sem
    isso, uma parada do fim da tarde escorregaria para o dia seguinte.
    """
    if isinstance(valor, datetime):
        bruto = valor
    elif isinstance(valor, str) and valor:
        try:
            bruto = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if bruto.tzinfo is None:
        return bruto
    return bruto.astimezone(BRT).replace(tzinfo=None)


def _tem_medicao(relatorio: Any) -> bool:
    """Se o `range` mediu alguma coisa. É o campo que o próprio upstream usa para saber se
    os totais têm lastro — sem ele, `total_generation_kwh` é `0.0` por construção, e esse
    zero se lê como "não gerou"."""
    dias = _dicionario(relatorio).get("days_with_data")
    return isinstance(dias, (int, float)) and not isinstance(dias, bool) and dias > 0


def _capacidade(relatorio: Any) -> float | None:
    total = _numero(_dicionario(relatorio).get("total_capacity_kwp"))
    if total and total > 0:
        return round(total, 2)
    soma = sum(
        _numero(i.get("capacity_kwp")) or 0.0
        for i in _lista(_dicionario(relatorio).get("inverters"))
    )
    return round(soma, 2) if soma > 0 else None


def _diarios(relatorio: Any) -> dict[str, dict[str, Any]]:
    """`daily_summaries[]` → `{'YYYY-MM-DD': linha}`."""
    return {
        linha["date"][:10]: linha
        for linha in _lista(_dicionario(relatorio).get("daily_summaries"))
        if isinstance(linha.get("date"), str) and len(linha["date"]) >= 10
    }


def _mensais(relatorio: Any) -> dict[str, dict[str, Any]]:
    """`monthly_summaries[]` → `{'YYYY-MM': linha}` — o rollup canônico do servidor."""
    return {
        linha["month"][:7]: linha
        for linha in _lista(_dicionario(relatorio).get("monthly_summaries"))
        if isinstance(linha.get("month"), str) and len(linha["month"]) >= 7
    }


def _grafico(relatorio: Any) -> dict[str, Any]:
    return _dicionario(_dicionario(relatorio).get("chart_data"))


def _irradiacao_por_dia(relatorio: Any) -> dict[str, tuple[float | None, float | None]]:
    return {
        p["t"][:10]: (_numero(p.get("hpoa")), _numero(p.get("hghi")))
        for p in _lista(_grafico(relatorio).get("daily_irradiation"))
        if isinstance(p.get("t"), str) and len(p["t"]) >= 10
    }


def _temperatura(valor: Any) -> float | None:
    """Temperatura, ou nada. Leitura fora da faixa terrestre é o sentinela do relé.

    Ver `TEMPERATURA_MIN_C`: a série chega com `-100.0` no lugar de "não mediu", e uma
    média com esse valor dentro publicaria como medição um número que não existe.
    """
    lido = _numero(valor)
    if lido is None or not (TEMPERATURA_MIN_C <= lido <= TEMPERATURA_MAX_C):
        return None
    return lido


def _serie_muda(valores: list[float]) -> bool:
    """A série inteira é `0.0` exato — o outro sentinela do relé (ver `TEMPERATURA_CAMPOS`).

    Sensor que mede oscila. Um período em que TODA leitura sobrevivente é zero cravado não
    está medindo: está repetindo o valor de fábrica. Uma única leitura diferente e a série
    volta a valer inteira, zeros incluídos — aí eles podem ser frio de verdade.
    """
    return bool(valores) and all(v == 0.0 for v in valores)


def _temperatura_por_dia(relatorio: Any) -> dict[str, dict[str, float | None]]:
    """`daily_temperature[]` → `{'YYYY-MM-DD': {campo: °C ou None}}`, já sem sentinela.

    Duas peneiras, e as duas precisam existir: a da FAIXA tira o impossível ponto a ponto
    (−100 °C), a da SÉRIE tira o relé mudo, que fala zero. Sozinha, a primeira deixava a
    tela do cliente afirmar 0,0 °C de média e de máxima.
    """
    por_dia = {
        p["t"][:10]: {campo: _temperatura(p.get(campo)) for campo in TEMPERATURA_CAMPOS}
        for p in _lista(_grafico(relatorio).get("daily_temperature"))
        if isinstance(p.get("t"), str) and len(p["t"]) >= 10
    }
    for campo in TEMPERATURA_CAMPOS:
        sobreviventes = [d[campo] for d in por_dia.values() if d[campo] is not None]
        if _serie_muda(sobreviventes):
            for d in por_dia.values():
                d[campo] = None
    return por_dia


def _pr_por_dia(relatorio: Any) -> dict[str, float]:
    """`daily_pr[]` → `{'YYYY-MM-DD': razão 0–1}`, só onde a razão é positiva."""
    saida: dict[str, float] = {}
    for p in _lista(_grafico(relatorio).get("daily_pr")):
        chave = p.get("t")
        pr = _numero(p.get("pr"))
        if isinstance(chave, str) and len(chave) >= 10 and pr is not None and pr > 0:
            saida[chave[:10]] = pr
    return saida


def _dias_com_pr_descartada(relatorio: Any) -> set[str]:
    """Os dias em que o monitoramento DESCARTOU a PR por implausibilidade.

    Só o conjunto de datas atravessa a ponte: o nome interno do descarte
    (`implausivel_alta`) é vocabulário do outro sistema e não diz nada ao cliente.
    """
    return {
        p["t"][:10]
        for p in _lista(_grafico(relatorio).get("daily_pr_flags"))
        if isinstance(p.get("t"), str) and len(p["t"]) >= 10 and p.get("flag")
    }


def _pr_do_periodo(relatorio: Any) -> float | None:
    """PR do período em %. O upstream devolve razão 0–1 e devolve `0.0` por construção
    quando não há irradiância medida — zero de PR não é medição, é a ausência dela."""
    if not _tem_medicao(relatorio):
        return None
    pr = _numero(_dicionario(relatorio).get("performance_ratio"))
    return round(pr * 100, 1) if pr and pr > 0 else None


def _disponibilidade(relatorio: Any, campo: str) -> float | None:
    return _numero(_dicionario(relatorio).get(campo)) if _tem_medicao(relatorio) else None


def _paradas_pendentes(relatorio: Any) -> int:
    valor = _dicionario(relatorio).get("pending_classification_count")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else 0


# ── projeto e previsto ──────────────────────────────────────────────────────


def _manual_por_mes(manual: Any) -> dict[int, dict[str, Any]]:
    """`rows[].{month, e_grid, poa, ghi, …}` → `{mês: linha}`."""
    return {
        linha["month"]: linha
        for linha in _lista(_dicionario(manual).get("rows"))
        if isinstance(linha.get("month"), int)
        and not isinstance(linha["month"], bool)
        and 1 <= linha["month"] <= 12
    }


def _projeto_por_dia(pvsyst: Any) -> dict[str, float]:
    """O projeto de cada dia. `{'YYYY-MM-DD': kWh}` — a linha da barra tracejada.

    **É `e_grid`, e não `e_array`.** `e_array` é a energia do ARRANJO, antes do inversor;
    `e_grid` é a que chega ao ponto de entrega. O número com que ela é comparada aqui é a
    geração dos INVERSORES, então `e_grid` é o par certo — e é o que
    `/plants/{id}/desempenho` lê desde sempre (`plants._esperado_diario_por_mes`).

    Ler `e_array` fazia duas coisas ruins ao mesmo tempo: inflava a referência (a usina
    parecia pior do que é) e dava ao portal DUAS respostas para "quanto o projeto
    esperava" — a do painel e a da tela de desempenho, no mesmo portal, para o mesmo
    cliente. A correção por indisponibilidade/derating saiu junto pelo mesmo motivo: a
    tela de desempenho não a aplica, e um projeto corrigido de um lado e cru do outro é a
    mesma pergunta com duas respostas. Se ela precisar voltar, volta nos DOIS lugares.
    """
    saida: dict[str, float] = {}
    for linha in _lista(_dicionario(pvsyst).get("rows")):
        dia = _data(linha.get("date"))
        kwh = _numero(linha.get("e_grid"))
        if dia is not None and kwh is not None:
            saida[dia.isoformat()] = kwh
    return saida


def _meta_por_mes(
    pvsyst: Any, manual: Any, ano: int, inicio: date, fim: date
) -> dict[str, float]:
    """A meta do projeto de cada mês entre `inicio` e `fim` — a MESMA de `/desempenho`.

    Não é uma segunda conta: são as duas funções puras que `plants._meta_do_projeto`
    compõe (`_diario_por_mes` e `_esperado_manual_por_mes`), rodadas aqui sobre
    os payloads que o painel JÁ tem em mãos — sem uma chamada nova à rede. Reusar as
    funções, em vez de reescrever a regra, é o que garante que o painel e a tela de
    desempenho respondam com o MESMO número, e não com um parecido.

    Três regras vêm de lá e são deliberadas: a fonte DIÁRIA manda (é dia a dia, então
    respeita "até hoje" sem rateio) e a MENSAL digitada só entra nos meses que a diária
    não cobre; o mês em que `fim` cai sai rateado pelos dias decorridos, porque comparar a
    meta inteira com meio mês medido diria "abaixo do esperado" sem que nada estivesse
    errado; e o mês cuja série DIÁRIA está incompleta cede a vez à mensal, quando ela
    existe (ver `plants._diario_por_mes` — foi o maio de 13 dias de Ibitinga fazendo a
    usina publicar `+60,1 %` num mês e 2,4 pontos a mais no ano inteiro).
    """
    diario, incompletos = _diario_por_mes(pvsyst, inicio, fim)
    meta = dict(diario)
    for chave, kwh in _esperado_manual_por_mes(manual, ano, fim).items():
        if chave in incompletos:
            meta[chave] = kwh
        else:
            meta.setdefault(chave, kwh)
    # Arredondado no mapa, e não só na saída: a célula da tabela e o cartão do acumulado
    # somam os MESMOS números, e o cliente que confere a coluna com o dedo fecha a conta.
    return {chave: round(kwh, 2) for chave, kwh in meta.items()}


def _globinc_por_dia(pvsyst: Any) -> dict[str, float]:
    """A irradiação de projeto no plano dos módulos, dia a dia. Só existe na importação
    diária do PVsyst — a entrada mensal carrega POA, que é a referência do mês."""
    saida: dict[str, float] = {}
    for linha in _lista(_dicionario(pvsyst).get("rows")):
        dia = _data(linha.get("date"))
        valor = _numero(linha.get("globinc"))
        if dia is not None and valor:
            saida[dia.isoformat()] = valor
    return saida


def _previsto_manual(
    linha: dict[str, Any] | None, hpoa_medida: float, ghi_medida: float
) -> float | None:
    """Meta do mês × (irradiação medida ÷ irradiação do projeto), do cadastro manual.

    Preferência pelo plano inclinado (POA), que é o mesmo plano da estação; o horizontal
    (GHI) é a segunda opção. Sem irradiação de projeto cadastrada não há correção — e
    inventar uma seria pior do que não ter o número.

    A base é `e_grid`, a MESMA do projeto (ver `_projeto_por_dia`). Corrigir `e_array` e
    pôr o resultado ao lado de um projeto em `e_grid` compararia energia do arranjo com
    energia entregue — dois lugares diferentes da usina, na mesma faixa de cartões.
    """
    if not linha:
        return None
    base = _numero(linha.get("e_grid"))
    if base is None or base <= 0:
        return None
    poa = _numero(linha.get("poa"))
    if poa and poa > 0 and hpoa_medida > 0:
        return base * (hpoa_medida / poa)
    ghi = _numero(linha.get("ghi"))
    if ghi and ghi > 0 and ghi_medida > 0:
        return base * (ghi_medida / ghi)
    return None


# ── contas de tela ──────────────────────────────────────────────────────────


def _desvio(aferido: float | None, referencia: float | None) -> float | None:
    """`(aferido − referência) ÷ referência`, em %. Referência nula ou zero não compara."""
    if aferido is None or referencia is None or referencia <= 0:
        return None
    return round((aferido - referencia) / referencia * 100, 2)


def _atingimento(medido: float | None, projeto: float | None) -> float | None:
    """`medido ÷ projeto`, em %, com UMA casa.

    A casa decimal não é detalhe: é a de `plants._situacao_do_projeto`, e é o que faz este
    número ser IGUAL ao `pct_do_projeto` de `/plants/{id}/desempenho` em vez de parecido.
    """
    if medido is None or projeto is None or projeto <= 0:
        return None
    return round(medido / projeto * 100, 1)


def _situacao_da_conciliacao(diferenca_pct: float | None) -> str | None:
    if diferenca_pct is None:
        return None
    absoluta = abs(diferenca_pct)
    if absoluta < TOLERANCIA_CONCILIACAO_PCT:
        return "Conciliado"
    if absoluta < 2 * TOLERANCIA_CONCILIACAO_PCT:
        return "Pequena divergência"
    return "Divergência relevante"


def _perda_ate_a_fronteira(
    fronteira_kwh: float | None, medido_kwh: float | None
) -> tuple[float | None, bool]:
    """`(perda em %, a fronteira é parcial?)` — ver `PERDA_FRONTEIRA_MAX_PCT`.

    Faltar um dos dois lados é ausência, não cobertura parcial: sem medidor de fronteira a
    usina simplesmente não tem esse número, e dizer "parcial" ali seria acusar de defeito
    um aparelho que não existe.
    """
    if fronteira_kwh is None or not medido_kwh or medido_kwh <= 0:
        return None, False
    perda = round((1 - fronteira_kwh / medido_kwh) * 100, 2)
    if PERDA_FRONTEIRA_MIN_PCT <= perda <= PERDA_FRONTEIRA_MAX_PCT:
        return perda, False
    return None, True


def _conciliacao(
    fronteira_mwh: float | None,
    faturado_mwh: float | None,
    *,
    parcial: bool = False,
    meses: list[str] | None = None,
) -> ConciliacaoOut:
    diferenca = (
        round(fronteira_mwh - faturado_mwh, 3)
        if fronteira_mwh is not None and faturado_mwh is not None and not parcial
        else None
    )
    pct = (
        round(diferenca / faturado_mwh * 100, 2)
        if diferenca is not None and faturado_mwh and faturado_mwh > 0
        else None
    )
    return ConciliacaoOut(
        fronteira_mwh=fronteira_mwh,
        faturado_mwh=faturado_mwh,
        diferenca_mwh=diferenca,
        diferenca_pct=pct,
        situacao=_situacao_da_conciliacao(pct),
        meses=meses or [],
    )


def _faturado_por_mes(faturas: Any) -> dict[int, float]:
    """Soma de `billed_mwh` por mês. Mês sem fatura fica FORA do mapa — "ainda não
    emitida" e "faturou zero" são coisas diferentes, e a segunda quase nunca é verdade."""
    itens = faturas.get("bills") if isinstance(faturas, dict) else faturas
    saida: dict[int, float] = {}
    for fatura in _lista(itens):
        mes = fatura.get("month")
        mwh = _numero(fatura.get("billed_mwh"))
        if isinstance(mes, int) and not isinstance(mes, bool) and mwh is not None:
            saida[mes] = round(saida.get(mes, 0.0) + mwh, 3)
    return saida


def _fronteira_do_mes(fronteira: Any, mes: int) -> float | None:
    """A fronteira daquele mês, em MWh. Zero é ausência de leitura, não medição de zero:
    o mapa do upstream simplesmente não traz o mês sem leitura."""
    if not isinstance(fronteira, dict):
        return None
    valor = _numero(fronteira.get(mes))
    return valor if valor and valor > 0 else None


def _soma(valores: list[float | None]) -> float | None:
    """Soma o que existe. Lista sem nenhum valor devolve NULO, não zero — "não mediu" e
    "mediu zero" são coisas diferentes."""
    presentes = [v for v in valores if v is not None]
    return round(sum(presentes), 2) if presentes else None


def _irradiacao_de_projeto(
    diario: float, manual: float | None, fator: float
) -> float | None:
    """A irradiação de projeto do período, na MESMA janela do medido.

    Duas fontes, nesta ordem: a soma do PVsyst DIÁRIO já recortada pela janela (é a mais
    exata, dia a dia) e, na falta dela, o valor MENSAL digitado na página de projeto,
    prorateado pelo `fator` — que é o mesmo dia-de-corte ÷ dias-do-mês do projeto de
    energia. Sem nenhuma das duas não há projeto de irradiação, e inventar um seria pior
    do que não ter: o desvio simplesmente não sai.

    A janela importa mais aqui do que parece. No mês em curso a irradiação MEDIDA é
    parcial; comparar com o projeto do mês inteiro devolveria "−48 % de irradiação" no dia
    15 de todo mês, todo mês.
    """
    if diario > 0:
        return round(diario, 2)
    if manual and manual > 0:
        return round(manual * fator, 2)
    return None


def _meteo(
    *, pontos: list[PontoMeteo], hpoa: float, ghi: float,
    hpoa_projeto: float | None, ghi_projeto: float | None = None,
    hpoa_projeto_origem: str | None = None, ghi_projeto_origem: str | None = None,
    agregar: list[PontoMeteo] | None = None,
) -> MeteoOut:
    """Os KPIs de meteorologia, derivados dos pontos que já foram montados.

    `agregar` é o subconjunto de `pontos` que entra nos ACUMULADOS e nas médias — a
    janela do painel. `pontos` continua vindo inteiro, porque a tabela mostra o período
    todo; o que não pode é a média sair de um conjunto e o total de outro.
    """
    contados = pontos if agregar is None else agregar
    ambientes = [p.t_amb for p in contados if p.t_amb is not None]
    modulos = [p.t_mod for p in contados if p.t_mod is not None]
    modulos_max = [p.t_mod_max for p in contados if p.t_mod_max is not None]
    return MeteoOut(
        tem_estacao=hpoa > 0 or ghi > 0,
        tem_sensor_temperatura=bool(ambientes or modulos),
        hpoa=_arredondar(hpoa) if hpoa > 0 else None,
        ghi=_arredondar(ghi) if ghi > 0 else None,
        razao=round(hpoa / ghi, 3) if hpoa > 0 and ghi > 0 else None,
        hpoa_projeto=_arredondar(hpoa_projeto) if hpoa_projeto else None,
        ghi_projeto=_arredondar(ghi_projeto) if ghi_projeto else None,
        hpoa_projeto_origem=hpoa_projeto_origem if hpoa_projeto else None,
        ghi_projeto_origem=ghi_projeto_origem if ghi_projeto else None,
        t_amb_media=_arredondar(sum(ambientes) / len(ambientes), 1) if ambientes else None,
        t_amb_max=_arredondar(max(ambientes), 1) if ambientes else None,
        t_mod_media=_arredondar(sum(modulos) / len(modulos), 1) if modulos else None,
        t_mod_max=_arredondar(max(modulos_max), 1) if modulos_max else None,
        pontos=pontos,
    )


# ── a janela do acumulado ───────────────────────────────────────────────────


def _janela_do_acumulado(
    relatorio: Any, meses: list[str], medidos: dict[int, float]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Quais meses entram no acumulado — e quais ficam de fora, com o motivo.

    **É a régua canônica do portal**, a mesma linha de `/plants/{id}/desempenho`:

        comparaveis = _meses_medidos(relatorio, meses) or meses

    — "a meta soma os MESMOS meses que a medição cobre, nunca o intervalo inteiro". O
    painel passou a chamar a MESMA função (`plants._meses_medidos`) em vez de reescrever
    a regra, porque a pergunta é uma só: "de quanto a usina está atingindo o projeto?".
    Enquanto eram duas contas, Porto Ferreira/2026 exibia 36 % no painel e 101,7 % em
    `/desempenho` — e o mesmo desencontro aparecia nas sete usinas.

    Um acréscimo, e ele é o conserto: o mês sem medição sai também do DENOMINADOR. O
    rollup do upstream traz `generation_kwh: 0.0` para os meses anteriores ao início da
    série (Porto Ferreira mede desde junho e recebe janeiro a maio zerados), e
    `_meses_medidos` — que só pergunta se o campo existe — os aceitava. Eles entravam no
    projeto e não na medição: era exatamente daí que saía o 36 %. Numerador e denominador
    passam a sair da MESMA lista, que é a única forma de a razão entre eles significar
    alguma coisa. Onde o mês zerado não tem meta cadastrada — o caso das usinas medidas —
    as duas leituras coincidem e o número é o mesmo dos dois lados.

    Sem `monthly_summaries` (o upstream não mandou o detalhe) o canônico devolve lista
    vazia e vale o intervalo inteiro, também como lá; o filtro da medição continua de pé.
    """
    canonicos = _meses_medidos(relatorio, meses) or meses
    dentro: list[str] = []
    fora: list[tuple[str, str]] = []
    for mes in meses:
        if medidos.get(int(mes[5:7])) is None:
            fora.append((mes, "sem_medicao"))
        elif mes in canonicos:
            dentro.append(mes)
        else:
            # O mês tem geração nos buckets diários, mas o detalhe mensal do upstream não
            # o lista. Ficar de fora é o que mantém o painel igual à tela de desempenho, e
            # o motivo diz que a razão é o detalhe que faltou — não a usina.
            fora.append((mes, "sem_detalhe_mensal"))
    return dentro, fora


def _janela_out(
    dentro: list[str], fora: list[tuple[str, str]], regra: str
) -> JanelaOut:
    return JanelaOut(
        meses=dentro,
        fora=[
            MesForaDoAcumulado(
                mes=m, rotulo=f"{_MES_CURTO[int(m[5:7]) - 1]}/{m[:4]}", motivo=motivo
            )
            for m, motivo in fora
        ],
        rotulo=_rotulo_de_meses(dentro) if dentro else None,
        parcial=bool(fora),
        regra=regra,
    )


#: A frase que a tela escreve ao lado do acumulado do ano.
_REGRA_JANELA_ANO = (
    "O acumulado soma só os meses com medição, e o projeto soma os MESMOS meses — o mês "
    "em curso entra com a meta rateada até hoje. Mês sem medição não entra em nenhum dos "
    "dois lados: ele derrubaria o atingimento sem que nada tivesse acontecido."
)

_REGRA_JANELA_MES = (
    "O acumulado vai do dia 1 até o último dia medido, e o projeto é rateado até o mesmo "
    "dia — comparar o mês inteiro do projeto com meio mês medido acusaria de doente uma "
    "usina em dia."
)


# ── disponibilidade técnica (tempo de pé por inversor) ──────────────────────


def _estado_do_evento(notificacao: Any) -> str:
    texto = (_texto(notificacao) or "").lower()
    if "comm" in texto or "comunic" in texto:
        return "falha_comunicacao"
    if "not_installed" in texto or "nao_instalado" in texto:
        return "nao_instalado"
    return "potencia_zero"


def _estado_do_dia(dia: date, eventos: list[dict[str, Any]]) -> str | None:
    """O estado da parada mais longa que cobriu a janela solar do dia. `None` = nenhuma."""
    meia_noite = datetime.combine(dia, datetime.min.time())
    abertura = meia_noite.replace(hour=HORA_SOLAR_INICIO)
    fechamento = meia_noite.replace(hour=HORA_SOLAR_FIM)

    pior_estado: str | None = None
    pior_duracao = 0.0
    for evento in eventos:
        comeco = _instante_local(evento.get("started_at"))
        if comeco is None:
            continue
        # Parada ainda aberta cobre o resto da janela — é o que ela está fazendo.
        fim = _instante_local(evento.get("resolved_at")) or fechamento
        de, ate = max(comeco, abertura), min(fim, fechamento)
        duracao = (ate - de).total_seconds()
        if duracao > pior_duracao:
            pior_duracao = duracao
            pior_estado = _estado_do_evento(evento.get("notification"))
    return pior_estado


def _disponibilidade_tecnica(
    relatorio: Any, inicio: date, fim_medido: date, dias_com_dado: set[str]
) -> DisponibilidadeTecnicaOut | None:
    """Um estado por inversor e por dia, recortado à janela solar.

    Simplificação declarada em relação ao meuWatt, que pinta FRAÇÕES do dia: aqui cada dia
    recebe UM estado — o da parada mais longa que cobriu a janela solar daquele dia. Uma
    matriz de frações de um ano inteiro é payload que o navegador do cliente não precisa
    carregar para responder "esse inversor ficou de pé?".

    O inversor entra pelo nome da POSIÇÃO. O número de série é a chave do inventário do
    meuWatt e serve só para casar o evento com o inversor aqui dentro.
    """
    inversores = _lista(_dicionario(relatorio).get("inverters"))
    if not inversores:
        return None

    eventos_por_serie: dict[str, list[dict[str, Any]]] = {}
    for evento in _lista(_dicionario(relatorio).get("alert_timeline")):
        serie = _texto(evento.get("sn"))
        if serie:
            eventos_por_serie.setdefault(serie, []).append(evento)

    calendario = [inicio + timedelta(days=n) for n in range((fim_medido - inicio).days + 1)]
    rotulos = _rotulos_de_inversor(inversores)

    linhas: list[InversorTecnico] = []
    for posicao, inversor in enumerate(inversores, start=1):
        serie = _texto(inversor.get("sn"))
        eventos = eventos_por_serie.get(serie, []) if serie else []
        instalado = _data(inversor.get("installed_at"))
        removido = _data(inversor.get("deleted_at"))
        # Inversor que não produziu NADA no período inteiro e não gerou evento nenhum
        # apareceria como 100% disponível — o defeito é justamente ele estar morto.
        sem_producao = (_numero(inversor.get("total_yield_kwh")) or 0.0) <= 0

        estados: list[tuple[date, str]] = []
        operando = 0
        contados = 0
        for dia in calendario:
            if (instalado and dia < instalado) or (removido and dia > removido):
                estados.append((dia, "nao_instalado"))
                continue
            if dia.isoformat() not in dias_com_dado:
                estados.append((dia, "sem_dado"))
                continue

            contados += 1
            estado = _estado_do_dia(dia, eventos)
            if estado is None:
                estado = "potencia_zero" if sem_producao else "operando"
            if estado == "operando":
                operando += 1
            estados.append((dia, estado))

        linhas.append(
            InversorTecnico(
                nome=rotulos.get(serie or "") or f"Inversor {posicao}",
                disponibilidade_pct=(
                    _arredondar(operando / contados * 100, 1) if contados else None
                ),
                faixas=_faixas(estados),
            )
        )

    return DisponibilidadeTecnicaOut(
        aviso=(
            "Aqui a disponibilidade é TÉCNICA: quanto tempo cada inversor ficou de pé "
            "dentro da janela de sol. Ela não bate com a disponibilidade dos cartões "
            "acima, que é energética — mede a energia perdida, não o tempo parado."
        ),
        primeiro_dia=inicio.isoformat(),
        ultimo_dia=fim_medido.isoformat(),
        inversores=linhas,
    )


def _faixas(estados: list[tuple[date, str]]) -> list[FaixaTecnica]:
    """Dias consecutivos no mesmo estado viram uma faixa só. Nenhum dia se perde: a soma
    de `dias` das faixas é sempre o tamanho do período."""
    saida: list[FaixaTecnica] = []
    for dia, estado in estados:
        if saida and saida[-1].estado == estado:
            saida[-1].ate = dia.isoformat()
            saida[-1].dias += 1
        else:
            saida.append(
                FaixaTecnica(de=dia.isoformat(), ate=dia.isoformat(), dias=1, estado=estado)
            )
    return saida


# ── o painel ────────────────────────────────────────────────────────────────


def _rotulo_do_periodo(recorte: str, alvo: date) -> str:
    if recorte == "ano":
        return str(alvo.year)
    return f"{_MESES[alvo.month - 1]} / {alvo.year}"


def _painel_sem_dados(
    recorte: str, alvo: date, inicio: date, fim: date, em_curso: bool, aviso: str
) -> PainelOut:
    """A tela abre vazia e dizendo o motivo — nunca com zeros, que se leem como medição."""
    return PainelOut(
        recorte=recorte,
        referencia=alvo.isoformat(),
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        rotulo=_rotulo_do_periodo(recorte, alvo),
        em_curso=em_curso,
        janela=_janela_out(
            [], [], _REGRA_JANELA_ANO if recorte == "ano" else _REGRA_JANELA_MES
        ),
        regra=_REGRA,
        aviso=aviso,
    )


@router.get("/usinas/{plant_link_id}/painel", response_model=PainelOut)
async def painel_de_geracao(
    plant_link_id: int,
    recorte: str = "mes",
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> PainelOut:
    """O painel do mês ou do ano: geração, performance, conciliação e meteorologia.

    Cinco fontes do meuWatt, buscadas em paralelo e todas dispensáveis menos a primeira: o
    relatório do período (`generation/range`), o projeto diário e o mensal digitado
    (PVsyst), a fronteira medida (SSU) e as faturas da distribuidora. Qualquer uma fora do
    ar tira o bloco dela da tela e escreve um aviso; **nenhuma derruba a resposta** — nem
    a primeira, que devolve 200 com os campos nulos.

    O `range` é pedido só até HOJE de propósito: no futuro ele fabrica dias vazios, e um
    zero fabricado se lê como "não gerou". Os dias futuros do mês aparecem em `dias` com
    `futuro=true` e `medido_kwh` nulo — é o que faz a barra sair tracejada. O PVsyst, ao
    contrário, é pedido pelo período INTEIRO: a referência de projeto do dia 30 existe
    mesmo que o dia 30 ainda não tenha acontecido, e é dela que sai o total do mês.
    """
    if recorte not in ("mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'mes' ou 'ano'.")

    link = _usina_monitorada(db, usuario, plant_link_id)
    hoje = hoje_na_usina()
    alvo = _referencia_pedida(referencia)
    inicio, fim = _janela(recorte, alvo)
    fim_medido = min(fim, hoje)
    em_curso = inicio <= hoje <= fim

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001 — sem ponte a tela ainda abre, vazia e honesta
        return _painel_sem_dados(
            recorte, alvo, inicio, fim, em_curso, f"Monitoramento indisponível: {exc}"
        )

    relatorio, pvsyst, manual, fronteira, faturas = await asyncio.gather(
        cliente.geracao_periodo(link.mw_plant_slug, inicio, fim_medido),
        cliente.pvsyst(link.mw_plant_slug, inicio, fim),
        cliente.pvsyst_manual(link.mw_plant_slug, alvo.year),
        cliente.ssu_totais_mensais(link.mw_plant_slug, alvo.year),
        cliente.faturas_concessionaria(link.mw_plant_slug, alvo.year),
        return_exceptions=True,
    )

    if isinstance(relatorio, BaseException) or not isinstance(relatorio, dict):
        motivo = relatorio if isinstance(relatorio, BaseException) else "resposta inesperada"
        return _painel_sem_dados(
            recorte, alvo, inicio, fim, em_curso, f"Monitoramento indisponível: {motivo}"
        )

    avisos: list[str] = []
    if isinstance(pvsyst, BaseException):
        avisos.append("a meta diária do projeto não veio")
        pvsyst = {}
    if isinstance(manual, BaseException):
        avisos.append("a meta mensal do projeto não veio")
        manual = {}
    if isinstance(fronteira, BaseException):
        avisos.append("a medição na fronteira não veio")
        fronteira = {}
    if isinstance(faturas, BaseException):
        avisos.append("as faturas da distribuidora não vieram")
        faturas = []
    if not _tem_medicao(relatorio):
        avisos.append("o monitoramento não tem medição neste período")

    comum = dict(
        alvo=alvo,
        inicio=inicio,
        fim=fim,
        fim_medido=fim_medido,
        hoje=hoje,
        em_curso=em_curso,
        relatorio=relatorio,
        pvsyst=pvsyst,
        manual=manual,
        fronteira=fronteira if isinstance(fronteira, dict) else {},
        faturas=faturas,
    )
    if recorte == "mes":
        painel = _painel_do_mes(**comum)
    else:
        painel = _painel_do_ano(
            **comum,
            disponibilidade_mensal=await _conferir_disponibilidade_mensal(
                cliente,
                link.mw_plant_slug,
                sorted(_medido_por_mes(relatorio, alvo.year)),
                alvo.year,
                hoje,
            ),
        )
    if avisos:
        painel.aviso = "Faltou parte dos dados: " + " · ".join(avisos) + "."
    return painel


# ── recorte MÊS ─────────────────────────────────────────────────────────────


def _painel_do_mes(
    *,
    alvo: date,
    inicio: date,
    fim: date,
    fim_medido: date,
    hoje: date,
    em_curso: bool,
    relatorio: dict[str, Any],
    pvsyst: Any,
    manual: Any,
    fronteira: dict[Any, Any],
    faturas: Any,
) -> PainelOut:
    dias_no_mes = fim.day
    dia_de_corte = hoje.day if em_curso else None

    manual_do_ano = _manual_por_mes(manual)
    linha_manual = manual_do_ano.get(alvo.month)

    projeto_diario = _projeto_por_dia(pvsyst)
    globinc = _globinc_por_dia(pvsyst)
    diarios = _diarios(relatorio)
    irradiacao = _irradiacao_por_dia(relatorio)
    temperatura = _temperatura_por_dia(relatorio)
    pr_diario = _pr_por_dia(relatorio)
    pr_descartada = _dias_com_pr_descartada(relatorio)

    dias: list[DiaDoMes] = []
    pontos: list[PontoMeteo] = []
    hpoa_medida = 0.0
    ghi_medida = 0.0
    for numero in range(1, dias_no_mes + 1):
        dia = date(alvo.year, alvo.month, numero)
        chave = dia.isoformat()
        futuro = dia > hoje
        linha = diarios.get(chave)
        hpoa, ghi = irradiacao.get(chave, (None, None))
        hpoa_medida += hpoa or 0.0
        ghi_medida += ghi or 0.0
        # Dia cuja PR o monitoramento descartou não tem PR — nem a que veio junto na
        # série. Deixar o valor passar seria publicar como medição o número que o próprio
        # produto de origem classificou como implausível.
        descartado = chave in pr_descartada
        pr = None if descartado else pr_diario.get(chave)

        dias.append(
            DiaDoMes(
                dia=numero,
                data=chave,
                medido_kwh=(
                    None if futuro or linha is None
                    else _arredondar(_numero(linha.get("generation_kwh")))
                ),
                projeto_kwh=_arredondar(projeto_diario.get(chave)),
                pr_pct=_arredondar(pr * 100, 1) if pr is not None else None,
                pr_descartado=descartado,
                futuro=futuro,
            )
        )
        temp = temperatura.get(chave, {})
        pontos.append(
            PontoMeteo(
                chave=chave,
                rotulo=f"{numero:02d}",
                hpoa=hpoa,
                hpoa_projeto=globinc.get(chave),
                ghi=ghi,
                t_amb=temp.get("t_amb"),
                t_mod=temp.get("t_mod"),
                t_mod_max=temp.get("t_mod_max"),
            )
        )

    medido = _numero(relatorio.get("total_generation_kwh")) if _tem_medicao(relatorio) else None

    # O PROJETO, pela régua canônica do portal (`_meta_por_mes` → as funções puras que
    # `/plants/{id}/desempenho` usa): a fonte DIÁRIA manda e a MENSAL digitada só entra no
    # mês que a diária não cobre. Duas janelas, e a distinção é o que impede o número de
    # mentir: `projeto` é o mês INTEIRO (a meta) e `proporcional` para no último dia
    # medido (o denominador da comparação).
    chave_do_mes = _chave_mes(alvo)
    projeto = _meta_por_mes(pvsyst, manual, alvo.year, inicio, fim).get(chave_do_mes)
    proporcional = _meta_por_mes(pvsyst, manual, alvo.year, inicio, fim_medido).get(
        chave_do_mes
    )
    # A procedência tem de acompanhar a TROCA: mês cuja série diária está incompleta cede a
    # vez à mensal em `_meta_por_mes`, e dizer "pvsyst_diario" aqui seria carimbar a fonte
    # errada no número que a tela publica.
    _diario_mes, _incompletos_mes = _diario_por_mes(pvsyst, inicio, fim)
    projeto_origem = (
        "pvsyst_diario"
        if chave_do_mes in _diario_mes and chave_do_mes not in _incompletos_mes
        else ("mensal_digitado" if projeto is not None else None)
    )

    # A IRRADIAÇÃO DE PROJETO, na mesma janela do medido — é o que permite separar "o sol
    # não veio" de "a usina não rendeu". No mês em curso o PVsyst diário é somado só até o
    # último dia medido; o valor mensal digitado, quando é a única fonte, entra prorateado
    # pelo mesmo dia de corte do projeto de energia.
    fator_do_periodo = (dia_de_corte / dias_no_mes) if (em_curso and dia_de_corte) else 1.0
    globinc_na_janela = sum(
        valor for chave, valor in globinc.items()
        if (dia_globinc := _data(chave)) is not None
        and dia_globinc.year == alvo.year and dia_globinc.month == alvo.month
        and (not em_curso or dia_globinc <= fim_medido)
    )
    hpoa_projeto = _irradiacao_de_projeto(
        globinc_na_janela, _numero(_dicionario(linha_manual).get("poa")), fator_do_periodo)
    ghi_projeto = _irradiacao_de_projeto(
        0.0, _numero(_dicionario(linha_manual).get("ghi")), fator_do_periodo)
    hpoa_projeto_origem = "pvsyst_diario" if globinc_na_janela > 0 else "mensal_digitado"

    previsto = _previsto_manual(linha_manual, hpoa_medida, ghi_medida)
    origem: str | None = "manual_corrigido" if previsto is not None else None
    if previsto is None:
        # Sem correção pela meteo digitada, o previsto é o próprio projeto na janela do
        # medido — o MESMO `proporcional` do cartão ao lado. Antes era uma segunda soma
        # dos mesmos dias, que só podia divergir com o tempo.
        if proporcional:
            previsto, origem = proporcional, projeto_origem

    resumo = _dicionario(relatorio.get("summary"))
    perdida = _numero(resumo.get("total_lost_kwh")) if _tem_medicao(relatorio) else None
    perdida_externa = (
        _numero(resumo.get("total_lost_externa_kwh")) if _tem_medicao(relatorio) else None
    )

    fronteira_mwh = _fronteira_do_mes(fronteira, alvo.month)
    fronteira_kwh = fronteira_mwh * 1000 if fronteira_mwh is not None else None
    perda_fronteira, fronteira_parcial = _perda_ate_a_fronteira(fronteira_kwh, medido)
    faturado = _faturado_por_mes(faturas).get(alvo.month)
    capacidade = _capacidade(relatorio)

    return PainelOut(
        recorte="mes",
        referencia=alvo.isoformat(),
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        rotulo=_rotulo_do_periodo("mes", alvo),
        em_curso=em_curso,
        dia_de_corte=dia_de_corte,
        capacidade_kwp=capacidade,
        medido_inversores_kwh=_arredondar(medido),
        medido_fronteira_kwh=_arredondar(fronteira_kwh),
        perda_inv_fronteira_pct=perda_fronteira,
        fronteira_parcial=fronteira_parcial,
        fronteira_meses=[chave_do_mes] if fronteira_mwh is not None else [],
        projeto_kwh=_arredondar(projeto),
        projeto_proporcional_kwh=_arredondar(proporcional),
        atingimento_pct=_atingimento(medido, proporcional),
        projeto_origem=projeto_origem,
        previsto_kwh=_arredondar(previsto),
        previsto_origem=origem,
        produtividade_kwh_kwp=(
            _arredondar(medido / capacidade)
            if medido is not None and capacidade else None
        ),
        pr_pct=_pr_do_periodo(relatorio),
        disponibilidade_real_pct=_disponibilidade(relatorio, "availability_real_pct"),
        disponibilidade_contratual_pct=_disponibilidade(
            relatorio, "availability_contratual_pct"
        ),
        paradas_pendentes=_paradas_pendentes(relatorio),
        perdida_kwh=_arredondar(perdida),
        perdida_externa_kwh=_arredondar(perdida_externa),
        desvios=DesviosOut(
            medido_vs_projeto_pct=_desvio(medido, proporcional),
            medido_vs_previsto_pct=_desvio(medido, previsto),
            # Mesma régua do recorte `ano`: sem correção pela meteo medida, previsto e
            # projeto são o mesmo número e o desvio seria `0,0 %` por construção — um
            # "efeito do clima" onde clima nenhum foi medido.
            previsto_vs_projeto_pct=(
                _desvio(previsto, proporcional) if origem == "manual_corrigido" else None
            ),
            hpoa_vs_projeto_pct=_desvio(hpoa_medida or None, hpoa_projeto),
            ghi_vs_projeto_pct=_desvio(ghi_medida or None, ghi_projeto),
        ),
        conciliacao=_conciliacao(
            _arredondar(fronteira_mwh, 3), faturado, parcial=fronteira_parcial
        ),
        totais=TotaisOut(
            medido_kwh=_arredondar(medido),
            projeto_kwh=_arredondar(projeto),
            projeto_ate_hoje_kwh=_arredondar(proporcional),
            # Projeção linear do fechamento: o medido de hoje na proporção que o projeto
            # do mês inteiro guarda com o projeto até hoje.
            tendencia_kwh=(
                round(medido * projeto / proporcional, 2)
                if em_curso and medido is not None and projeto and proporcional
                else None
            ),
        ),
        meteo=_meteo(
            pontos=pontos,
            hpoa=hpoa_medida,
            ghi=ghi_medida,
            hpoa_projeto=hpoa_projeto,
            ghi_projeto=ghi_projeto,
            hpoa_projeto_origem=hpoa_projeto_origem,
            ghi_projeto_origem="mensal_digitado",
        ),
        dias=dias,
        janela=_janela_out(
            [chave_do_mes] if medido is not None else [],
            [] if medido is not None else [(chave_do_mes, "sem_medicao")],
            _REGRA_JANELA_MES,
        ),
        regra=_REGRA,
    )


# ── recorte ANO ─────────────────────────────────────────────────────────────


def _medido_por_mes(relatorio: Any, ano: int) -> dict[int, float]:
    """Quanto cada mês do ano mediu, em kWh. Mês sem medição fica FORA do mapa.

    O rollup do servidor (`monthly_summaries`) manda, e os buckets diários entram só onde
    ele não cobre — assim o mês não some por falta de detalhe.

    Mês MEDIDO é mês com geração acima de zero. O rollup traz linha para os meses
    anteriores ao início da série com `generation_kwh: 0.0` — Porto Ferreira, cuja medição
    começa em junho, devolve janeiro a maio zerados. Aceitar esse zero como medição
    colocaria cinco meses inexistentes no seletor, publicaria "gerou 0 kWh" onde ninguém
    mediu e pintaria −100 % de desvio contra o projeto.
    """
    do_rollup: dict[int, float] = {}
    for chave, linha in _mensais(relatorio).items():
        mes = _data(f"{chave}-01")
        valor = _numero(_dicionario(linha).get("generation_kwh"))
        if mes and mes.year == ano and valor is not None:
            do_rollup[mes.month] = valor

    do_diario: dict[int, float] = {}
    for chave, linha in _diarios(relatorio).items():
        dia = _data(chave)
        if dia and dia.year == ano:
            gerado = _numero(linha.get("generation_kwh")) or 0.0
            do_diario[dia.month] = do_diario.get(dia.month, 0.0) + gerado

    saida: dict[int, float] = {}
    for numero in range(1, 13):
        medido = do_rollup.get(numero)
        if medido is None:
            medido = do_diario.get(numero)
        if medido is not None and medido > 0:
            saida[numero] = medido
    return saida


async def _conferir_disponibilidade_mensal(
    cliente: Any, slug: str, meses: list[int], ano: int, hoje: date
) -> dict[int, tuple[float | None, float | None]]:
    """A disponibilidade de cada mês medido, pela régua de quem já está no ar.

    **Por que uma leitura por mês, e não o rollup que já veio junto.** O `monthly_summaries`
    do `range` do ANO e o cabeçalho do `range` daquele MÊS discordam — e é o cabeçalho que
    `/plants/{id}/desempenho` publica desde sempre. Medido em Porto Ferreira, agosto de
    2026: cabeçalho 99,89 %, rollup 99,99 %. Sem esta conferência o cliente abriria o mês
    de agosto lendo 99,89 % e o ano lendo 99,99 % na linha de agosto — o produto se
    contradizendo dentro da mesma tela, num número de teor contratual.

    Não dá para reproduzir o cabeçalho a partir do que o `range` do ano traz: nem os
    diários nem o rollup o explicam sozinhos (em julho o cabeçalho segue o rollup; em
    agosto, os diários). O upstream compõe as duas fontes lá dentro, e a única maneira
    honesta de exibir o mesmo número é pedir o mesmo número.

    É barato: só os meses que TÊM medição, em paralelo, e são exatamente as leituras que o
    recorte `mes` faz — o upstream as cacheia por dez minutos e as duas telas se
    aproveitam. Porto Ferreira/2026: quatro leituras, 0,75 s. Mês que falhar volta sem
    resposta e o chamador cai no rollup.
    """
    portao = asyncio.Semaphore(CONFERENCIAS_SIMULTANEAS)

    async def _de_um_mes(numero: int) -> tuple[int, Any]:
        primeiro = date(ano, numero, 1)
        if primeiro > hoje:  # mês que ainda não começou não tem o que conferir
            return numero, None
        ultimo = date(ano, numero, monthrange(ano, numero)[1])
        async with portao:
            try:
                return numero, await cliente.geracao_periodo(slug, primeiro, min(ultimo, hoje))
            except Exception:  # noqa: BLE001 — mês que falha cai no rollup, sem derrubar a tela
                return numero, None

    saida: dict[int, tuple[float | None, float | None]] = {}
    for numero, relatorio in await asyncio.gather(*(_de_um_mes(m) for m in meses)):
        if isinstance(relatorio, dict) and _tem_medicao(relatorio):
            saida[numero] = (
                _numero(relatorio.get("availability_real_pct")),
                _numero(relatorio.get("availability_contratual_pct")),
            )
    return saida


def _painel_do_ano(
    *,
    alvo: date,
    inicio: date,
    fim: date,
    fim_medido: date,
    hoje: date,
    em_curso: bool,
    relatorio: dict[str, Any],
    pvsyst: Any,
    manual: Any,
    fronteira: dict[Any, Any],
    faturas: Any,
    disponibilidade_mensal: dict[int, tuple[float | None, float | None]] | None = None,
) -> PainelOut:
    ano = alvo.year
    conferida = disponibilidade_mensal or {}
    manual_do_ano = _manual_por_mes(manual)

    diarios = _diarios(relatorio)
    mensais = _mensais(relatorio)
    medidos = _medido_por_mes(relatorio, ano)
    irradiacao = _irradiacao_por_dia(relatorio)
    temperatura = _temperatura_por_dia(relatorio)
    faturado_do_ano = _faturado_por_mes(faturas)

    # A META, pela régua canônica do portal (as funções puras de `plants.py` que
    # `/plants/{id}/desempenho` usa). Duas janelas: `meta_ate_hoje` para no último dia
    # medido — o mês em curso sai rateado — e `meta_do_ano` vai até 31/12, porque "quanto
    # o projeto prevê para o ano" é outra pergunta e continua na tela.
    meta_ate_hoje = _meta_por_mes(pvsyst, manual, ano, inicio, fim_medido)
    meta_do_ano = _meta_por_mes(pvsyst, manual, ano, inicio, fim)
    # Só os meses que a diária cobre INTEIROS contam como origem `pvsyst_diario` —
    # os incompletos foram trocados pela mensal em `_meta_por_mes`.
    _diario_ano, _incompletos_ano = _diario_por_mes(pvsyst, inicio, fim)
    diario_por_mes = {m: v for m, v in _diario_ano.items() if m not in _incompletos_ano}

    # Acumuladores por mês do ano pedido. Tudo o que vem por DIA é somado aqui uma vez só.
    hpoa: dict[int, float] = {}
    hpoa_projeto: dict[int, float] = {}
    ghi: dict[int, float] = {}
    ambientes: dict[int, list[float]] = {}
    modulos: dict[int, list[float]] = {}
    modulos_max: dict[int, float] = {}
    pr_numerador: dict[int, float] = {}
    pr_denominador: dict[int, float] = {}
    perdida_diaria: dict[int, float] = {}
    perdida_ext_diaria: dict[int, float] = {}
    dias_com_dado: set[str] = set()

    def _no_ano(chave: str) -> date | None:
        dia = _data(chave)
        return dia if dia and dia.year == ano else None

    # O projeto de irradiação para no último dia medido, como a meta de energia: no mês em
    # curso a medição é parcial, e um projeto de mês inteiro do outro lado devolveria
    # "faltou sol" todo dia 15 de todo mês.
    for chave, valor in _globinc_por_dia(pvsyst).items():
        if (dia := _no_ano(chave)) and dia <= fim_medido:
            hpoa_projeto[dia.month] = hpoa_projeto.get(dia.month, 0.0) + valor
    for chave, linha in diarios.items():
        if not (dia := _no_ano(chave)):
            continue
        gerado = _numero(linha.get("generation_kwh")) or 0.0
        perdida_diaria[dia.month] = perdida_diaria.get(dia.month, 0.0) + (
            _numero(linha.get("lost_kwh")) or 0.0
        )
        perdida_ext_diaria[dia.month] = perdida_ext_diaria.get(dia.month, 0.0) + (
            _numero(linha.get("lost_kwh_externa")) or 0.0
        )
        if gerado > 0:
            dias_com_dado.add(chave)
    for chave, (h, g) in irradiacao.items():
        if not (dia := _no_ano(chave)):
            continue
        hpoa[dia.month] = hpoa.get(dia.month, 0.0) + (h or 0.0)
        ghi[dia.month] = ghi.get(dia.month, 0.0) + (g or 0.0)
    for chave, temp in temperatura.items():
        if not (dia := _no_ano(chave)):
            continue
        if temp.get("t_amb") is not None:
            ambientes.setdefault(dia.month, []).append(temp["t_amb"])
        if temp.get("t_mod") is not None:
            modulos.setdefault(dia.month, []).append(temp["t_mod"])
        if temp.get("t_mod_max") is not None:
            modulos_max[dia.month] = max(
                modulos_max.get(dia.month, temp["t_mod_max"]), temp["t_mod_max"]
            )
    # PR do mês = Σ(PR_dia · POA_dia) ÷ Σ(POA_dia), sobre a MESMA série diária que o
    # servidor usa no headline. Uma média simples daria peso igual a um dia nublado e a um
    # de céu limpo — e produziria um quarto número de PR dentro do mesmo produto.
    for chave, pr in _pr_por_dia(relatorio).items():
        if not (dia := _no_ano(chave)):
            continue
        poa = (irradiacao.get(chave) or (None, None))[0] or 0.0
        if poa > 0:
            pr_numerador[dia.month] = pr_numerador.get(dia.month, 0.0) + pr * poa
            pr_denominador[dia.month] = pr_denominador.get(dia.month, 0.0) + poa

    # ── A JANELA, antes de qualquer acumulado ────────────────────────────────
    # Ela é o conserto: numerador e denominador saem da MESMA lista de meses. Ver
    # `_janela_do_acumulado` — é a régua de `/plants/{id}/desempenho`, chamada e não
    # reescrita, mais o descarte do mês que o rollup zera.
    meses_do_periodo = _meses_entre(_chave_mes(inicio), _chave_mes(fim_medido))
    dentro, fora = _janela_do_acumulado(relatorio, meses_do_periodo, medidos)
    fora += [
        (f"{ano:04d}-{numero:02d}", "futuro")
        for numero in range(1, 13)
        if f"{ano:04d}-{numero:02d}" not in meses_do_periodo
    ]
    fora.sort(key=lambda item: item[0])
    no_acumulado = set(dentro)

    meses: list[MesDoAno] = []
    pontos: list[PontoMeteo] = []
    disponiveis: list[str] = []
    #: O projeto de irradiação POR MÊS, na forma em que ele aparece na tabela — é a mesma
    #: parcela que o acumulado soma.
    hpoa_projeto_do_mes: dict[int, float] = {}
    ghi_projeto_do_mes: dict[int, float] = {}
    for numero in range(1, 13):
        chave_mes = f"{ano:04d}-{numero:02d}"
        primeiro = date(ano, numero, 1)
        ultimo = date(ano, numero, monthrange(ano, numero)[1])
        futuro = primeiro > hoje
        mes_em_curso = not futuro and ultimo > hoje
        # Fração do mês já decorrida — o mesmo rateio que a meta de energia recebe em
        # `_esperado_manual_por_mes`, aplicado à irradiação digitada para os dois lados da
        # comparação cobrirem os mesmos dias.
        fator_mes = (
            hoje.day / monthrange(ano, numero)[1] if mes_em_curso else 1.0
        )

        # A geração e a perda vêm do rollup canônico do servidor (`monthly_summaries`), com
        # os buckets do diário entrando só onde ele não cobre. A régua de "mês medido" mora
        # em `_medido_por_mes`, para o seletor e a linha da tabela nunca discordarem.
        rollup = mensais.get(chave_mes)
        medido = medidos.get(numero)
        if medido is not None:
            disponiveis.append(chave_mes)
        # Perda e disponibilidade acompanham a medição: sem mês medido não há o que ter
        # perdido, e a linha zerada do rollup traria 100 % de disponibilidade num mês em
        # que a usina nem estava sendo monitorada.
        perdida = perdida_ext = None
        real = contratual = None
        if medido is not None:
            perdida = _numero(_dicionario(rollup).get("lost_kwh"))
            if perdida is None:
                perdida = perdida_diaria.get(numero)
            perdida_ext = _numero(_dicionario(rollup).get("lost_externa_kwh"))
            if perdida_ext is None:
                perdida_ext = perdida_ext_diaria.get(numero)
            # A conferência mês a mês manda (ver `_conferir_disponibilidade_mensal`): é o
            # mesmo número que o recorte `mes` e `/plants/{id}/desempenho` publicam. O
            # rollup é a rede de segurança de quando aquela leitura não veio.
            real, contratual = conferida.get(numero) or (None, None)
            origem_disp = "mes_conferido"
            if real is None:
                real = _numero(_dicionario(rollup).get("availability_real_pct"))
                origem_disp = "rollup_do_ano"
            if contratual is None:
                contratual = _numero(_dicionario(rollup).get("availability_contratual_pct"))
                origem_disp = "rollup_do_ano"
        else:
            origem_disp = None

        # O PROJETO da linha: dentro da janela vale a meta ATÉ HOJE (o mês em curso sai
        # rateado, e é assim que a coluna soma exatamente o cartão do acumulado); fora
        # dela vale a meta do mês inteiro, que é o alvo e não entra em conta nenhuma.
        linha_manual = manual_do_ano.get(numero)
        projeto_mes = (
            meta_ate_hoje.get(chave_mes)
            if chave_mes in no_acumulado
            else meta_do_ano.get(chave_mes)
        )
        previsto_mes = _previsto_manual(linha_manual, hpoa.get(numero, 0.0), ghi.get(numero, 0.0))
        if previsto_mes is None:
            previsto_mes = projeto_mes

        fronteira_mes = _fronteira_do_mes(fronteira, numero)
        meses.append(
            MesDoAno(
                mes=chave_mes,
                rotulo=_MES_CURTO[numero - 1],
                medido_kwh=_arredondar(medido),
                projeto_kwh=_arredondar(projeto_mes),
                previsto_kwh=_arredondar(previsto_mes),
                desvio_vs_projeto_pct=_desvio(medido, projeto_mes),
                pr_pct=(
                    _arredondar(pr_numerador[numero] / pr_denominador[numero] * 100, 1)
                    if pr_denominador.get(numero) else None
                ),
                disponibilidade_real_pct=real,
                disponibilidade_contratual_pct=contratual,
                perdida_kwh=_arredondar(perdida),
                perdida_externa_kwh=_arredondar(perdida_ext),
                fronteira_mwh=_arredondar(fronteira_mes, 3),
                faturado_mwh=faturado_do_ano.get(numero),
                disponibilidade_origem=origem_disp,
                no_acumulado=chave_mes in no_acumulado,
                em_curso=mes_em_curso,
                futuro=futuro,
            )
        )
        # A CÉLULA do projeto de irradiação carrega o MESMO valor que entra no acumulado —
        # PVsyst diário quando existe, valor mensal digitado (rateado no mês em curso)
        # quando não. Enquanto a coluna vinha só do diário e o total só do digitado, a
        # tabela exibia "Acumulado do período · HPOA PROJETO 174,6" com as doze parcelas
        # em travessão: um total que não saía de nada visível.
        hpoa_projeto_mes = hpoa_projeto.get(numero) or (
            (_numero(_dicionario(linha_manual).get("poa")) or 0.0) * fator_mes
        )
        ghi_projeto_mes = (
            _numero(_dicionario(linha_manual).get("ghi")) or 0.0
        ) * fator_mes
        if hpoa_projeto_mes:
            hpoa_projeto_do_mes[numero] = hpoa_projeto_mes
        if ghi_projeto_mes:
            ghi_projeto_do_mes[numero] = ghi_projeto_mes
        pontos.append(
            PontoMeteo(
                chave=chave_mes,
                rotulo=_MES_CURTO[numero - 1],
                hpoa=_arredondar(hpoa[numero]) if hpoa.get(numero) else None,
                hpoa_projeto=_arredondar(hpoa_projeto_mes) if hpoa_projeto_mes else None,
                ghi=_arredondar(ghi[numero]) if ghi.get(numero) else None,
                ghi_projeto=_arredondar(ghi_projeto_mes) if ghi_projeto_mes else None,
                t_amb=(
                    _arredondar(sum(ambientes[numero]) / len(ambientes[numero]), 1)
                    if ambientes.get(numero) else None
                ),
                t_mod=(
                    _arredondar(sum(modulos[numero]) / len(modulos[numero]), 1)
                    if modulos.get(numero) else None
                ),
                t_mod_max=_arredondar(modulos_max.get(numero), 1),
            )
        )

    # ── OS ACUMULADOS, todos da MESMA janela ─────────────────────────────────
    # Antes eram três janelas convivendo na mesma tela: o cartão somava os meses fechados,
    # a tabela mostrava também o mês em curso (o cliente somava a coluna com o dedo e ela
    # não batia: em Porto Ferreira faltavam exatamente os 128.037 kWh de setembro) e o
    # previsto somava "os meses com medição". Agora há uma lista só, e ela viaja na
    # resposta (`janela`) para a tela poder dizer de onde o número saiu.
    contados = [m for m in meses if m.mes in no_acumulado]
    medido_ytd = _soma([m.medido_kwh for m in contados])
    projeto_ytd = _soma([m.projeto_kwh for m in contados])
    projeto_ano = _soma([meta_do_ano.get(m.mes) for m in meses])
    previsto_ytd = _soma([m.previsto_kwh for m in contados])
    fronteira_ytd = _soma([m.fronteira_mwh for m in contados])
    fronteira_ytd_kwh = fronteira_ytd * 1000 if fronteira_ytd is not None else None
    perda_fronteira, fronteira_parcial = _perda_ate_a_fronteira(fronteira_ytd_kwh, medido_ytd)

    # A CONCILIAÇÃO é a única conta com janela própria, e por isso ela a declara. Fatura
    # ainda não emitida é ESTADO, não erro: pôr a fronteira de um mês cujo faturamento a
    # distribuidora nem fechou inventaria uma "divergência relevante" do tamanho daquele
    # mês, e mandaria o cliente cobrar da distribuidora um mês que ainda não chegou.
    conciliaveis = [
        m for m in contados if m.fronteira_mwh is not None and m.faturado_mwh is not None
    ]
    conciliada_fronteira = _soma([m.fronteira_mwh for m in conciliaveis])
    conciliada_faturado = _soma([m.faturado_mwh for m in conciliaveis])

    # A IRRADIAÇÃO do projeto só sai quando cobre TODOS os meses do acumulado. Ela vinha de
    # um conjunto (os meses com PVsyst diário) e era comparada com a medição de outro (os
    # meses com estação): Porto Ferreira publicava "+176,6 % de sol", como se agosto
    # tivesse recebido quase o triplo da irradiação prevista. Referência que cobre parte
    # do período não vira comparação — e a tela mostra a medição sozinha, que é verdade.
    hpoa_projeto_ytd = (
        _soma([hpoa_projeto_do_mes.get(int(m[5:7])) for m in dentro])
        if dentro and all(int(m[5:7]) in hpoa_projeto_do_mes for m in dentro)
        else None
    )
    ghi_projeto_ytd = (
        _soma([ghi_projeto_do_mes.get(int(m[5:7])) for m in dentro])
        if dentro and all(int(m[5:7]) in ghi_projeto_do_mes for m in dentro)
        else None
    )
    hpoa_ytd = sum(hpoa.get(int(m[5:7]), 0.0) for m in dentro)
    ghi_ytd = sum(ghi.get(int(m[5:7]), 0.0) for m in dentro)
    # A procedência da referência: diário onde ele existe em TODOS os meses contados,
    # digitado quando algum deles caiu no valor mensal.
    hpoa_origem = (
        "pvsyst_diario"
        if dentro and all(hpoa_projeto.get(int(m[5:7])) for m in dentro)
        else "mensal_digitado"
    )

    capacidade = _capacidade(relatorio)
    projeto_origem = (
        "pvsyst_diario"
        if dentro and all(m in diario_por_mes for m in dentro)
        else ("mensal_digitado" if projeto_ytd is not None else None)
    )
    previsto_origem = _origem_do_previsto_anual(manual_do_ano, hpoa, ghi, projeto_origem)

    return PainelOut(
        recorte="ano",
        referencia=alvo.isoformat(),
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        rotulo=_rotulo_do_periodo("ano", alvo),
        em_curso=em_curso,
        capacidade_kwp=capacidade,
        medido_inversores_kwh=medido_ytd,
        medido_fronteira_kwh=_arredondar(fronteira_ytd_kwh),
        perda_inv_fronteira_pct=perda_fronteira,
        fronteira_parcial=fronteira_parcial,
        fronteira_meses=[m.mes for m in contados if m.fronteira_mwh is not None],
        # `projeto_kwh` é a meta do PERÍODO INTEIRO em todo recorte — é o que o próprio
        # campo promete no `PainelOut`. Aqui ele recebia `projeto_ytd`, virando cópia exata
        # de `projeto_proporcional_kwh`, e a meta do ano inteiro só existia em
        # `totais.projeto_kwh`: um mesmo campo devolvia o mês FECHADO no recorte `mes` e um
        # ano PARCIAL no recorte `ano`. Nenhuma tela lia assim hoje — e é exatamente a
        # armadilha "uma pergunta, duas respostas" que esta leva existe para fechar.
        projeto_kwh=projeto_ano,
        projeto_proporcional_kwh=projeto_ytd,
        atingimento_pct=_atingimento(medido_ytd, projeto_ytd),
        projeto_origem=projeto_origem,
        previsto_kwh=previsto_ytd,
        previsto_origem=previsto_origem,
        produtividade_kwh_kwp=(
            _arredondar(medido_ytd / capacidade)
            if medido_ytd is not None and capacidade else None
        ),
        pr_pct=_pr_do_periodo(relatorio),
        disponibilidade_real_pct=_disponibilidade(relatorio, "availability_real_pct"),
        disponibilidade_contratual_pct=_disponibilidade(
            relatorio, "availability_contratual_pct"
        ),
        paradas_pendentes=_paradas_pendentes(relatorio),
        perdida_kwh=_soma([m.perdida_kwh for m in contados]),
        perdida_externa_kwh=_soma([m.perdida_externa_kwh for m in contados]),
        desvios=DesviosOut(
            medido_vs_projeto_pct=_desvio(medido_ytd, projeto_ytd),
            medido_vs_previsto_pct=_desvio(medido_ytd, previsto_ytd),
            # "O efeito do clima" só existe quando houve correção pela irradiação medida.
            # Sem ela o previsto É o projeto, e este desvio saía `+0,0 %` — uma medição de
            # clima afirmada em quatro usinas que não têm estação nenhuma.
            previsto_vs_projeto_pct=(
                _desvio(previsto_ytd, projeto_ytd)
                if previsto_origem == "manual_corrigido" else None
            ),
            hpoa_vs_projeto_pct=_desvio(hpoa_ytd or None, hpoa_projeto_ytd),
            ghi_vs_projeto_pct=_desvio(ghi_ytd or None, ghi_projeto_ytd),
        ),
        conciliacao=_conciliacao(
            _arredondar(conciliada_fronteira, 3),
            conciliada_faturado,
            parcial=fronteira_parcial,
            meses=[m.mes for m in conciliaveis],
        ),
        totais=TotaisOut(
            medido_kwh=medido_ytd,
            projeto_kwh=projeto_ano,
            projeto_ate_hoje_kwh=projeto_ytd,
            tendencia_kwh=None,
        ),
        meteo=_meteo(
            pontos=pontos,
            hpoa=hpoa_ytd,
            ghi=ghi_ytd,
            hpoa_projeto=hpoa_projeto_ytd,
            ghi_projeto=ghi_projeto_ytd,
            hpoa_projeto_origem=hpoa_origem,
            ghi_projeto_origem="mensal_digitado",
            agregar=[p for p in pontos if p.chave in no_acumulado],
        ),
        meses=meses,
        meses_disponiveis=disponiveis,
        janela=_janela_out(dentro, fora, _REGRA_JANELA_ANO),
        disponibilidade_tecnica=_disponibilidade_tecnica(
            relatorio, inicio, fim_medido, dias_com_dado
        ),
        regra=_REGRA,
    )


def _origem_do_previsto_anual(
    manual_do_ano: dict[int, dict[str, Any]],
    hpoa: dict[int, float],
    ghi: dict[int, float],
    projeto_origem: str | None,
) -> str | None:
    """De onde veio o previsto do ano. Basta um mês corrigido pela meteo digitada para a
    origem ser a manual — é o que a tela precisa escrever ao lado do número.

    ⛔ **Sem correção, a origem é a DO PROJETO** — porque sem correção o previsto É o
    projeto (o mesmo `previsto = proporcional` do recorte `mes`, ali com a origem certa).
    Isto dizia `"pvsyst_diario" if meta else None`, e a frase que a tela escreve para essa
    origem é *"da meta diária do projeto, corrigida pela irradiação medida"*. Em Ouro Fino,
    Pereiras, Pirapozinho e Tietê — quatro das sete usinas, **nenhuma** com uma linha de
    PVsyst diário e **nenhuma** com estação — a tela publicava, lado a lado:
    `PROJETO 2.379,8 MWh · do valor mensal digitado no projeto` e `PREVISTO 2.379,8 MWh ·
    da meta diária do projeto, corrigida pela irradiação medida`. Dois rótulos, o mesmo
    byte, e uma correção que nunca houve. E a mesma usina se contradizia entre as abas: no
    recorte `mes` este mesmo código já escrevia `mensal_digitado`.
    """
    for mes, linha in manual_do_ano.items():
        if _previsto_manual(linha, hpoa.get(mes, 0.0), ghi.get(mes, 0.0)) is not None:
            return "manual_corrigido"
    return projeto_origem


# ── o fechamento do mês ─────────────────────────────────────────────────────
#
# A §1 e a §5 da aba Relatório do meuWatt, e nada mais. Não é um sexto recorte da mesma
# pergunta: é **a resposta**, e ela só existe travada no MÊS.
#
# O que entra é o que as outras quatro abas NÃO respondem:
#
# - **energia potencial** (medido + perdido em paradas) e o desvio dela contra o projeto —
#   o único par de números do meuWatt inteiro que separa "faltou sol" de "a usina parou".
#   Hoje o cliente lê `−7 %` na aba Mês e não tem como saber de qual dos dois se trata;
# - **as causas e os eventos com a classificação** — sem elas a
#   `disponibilidade_contratual_pct` que o portal já publica é um número de teor contratual
#   sem nenhuma justificativa ao lado;
# - **as horas paradas COM o denominador** — `141h38 de 4.090h possíveis`. Um absoluto sem
#   denominador em documento contratual é sempre lido para o lado mais alarmante;
# - **as considerações gerais do mês**, somente leitura. É a única coisa da aba que não é
#   aritmética: todo o resto o cliente infere, isto ele não pode;
# - **a timeline curada**, quando existe. Mês sem curadoria não tem a seção — é o
#   comportamento certo, não uma limitação.
#
# Fica DELIBERADAMENTE de fora tudo o que já é Mês / Ano / Unidades / comparativo (os
# gráficos diários, os rankings por UC, skid e inversor) e **a fábrica de PDF inteira**:
# capa, contracapa, branding, QR, cabeçalho corrente, ganchos de impressão. O dono foi
# explícito — "os dashs do meuWatt SEM a opção de gerar PDF, mas com todas as informações".
# O painel mostra número VIVO do mês que o cliente está olhando; a tela Relatórios entrega
# documento FECHADO e assinado. Republicar o PDF aqui seria a terceira cópia do mesmo
# conteúdo, e a que envelhece.
#
# ⚠️ **A perda tem UMA fonte.** `perdida_kwh` é o `summary.total_lost_kwh` que já sustenta
# a nossa disponibilidade — não a conta paralela do `useReportParadas` do meuWatt, que
# recorta ao período e é suppression-aware e por isso DIVERGE dela (medido na Pirapozinho:
# cabeçalho 30,98 MWh contra donut 29,90 MWh). As causas são lidas dos alertas, que é outra
# janela, e **por isso a resposta declara as duas** (`perda_origem`, `causas_origem`,
# `causas_total_kwh`, `causas_conferem`) em vez de reescalar uma pela outra: rateio produz
# um número que ninguém mediu, e a casa proíbe número inventado. Quando os dois não podem
# ser o mesmo, a tela diz de que janela cada um saiu.


#: Período do vocabulário do upstream para as observações. O fechamento é sempre mensal.
PERIODO_MENSAL = "MENSAL"

#: A seção da caixa de texto que é dirigida AO CLIENTE. As outras (`dash:detalhamento`,
#: `dash:ucs`, `dash:paradas`, `dash:meteo`, `dash:desvio`) são conversa interna de
#: operação e não atravessam — só esta é o fechamento que o dono lê.
SECAO_DAS_CONSIDERACOES = "dash:gerais"

#: Rótulo da parada que o operador ainda não classificou. Não é uma causa: é a ausência
#: dela, e escondê-la do ranking esconderia justamente a energia sem explicação.
SEM_CLASSIFICACAO = "Não classificada"

#: Rótulo do inversor que PRODUZIU abaixo dos pares. Não é parada — os kWh contam, as
#: horas offline não (o aparelho estava ligado).
BAIXA_GERACAO = "Baixa geração"

#: Tolerância, em %, entre a perda do monitoramento e a soma das causas lidas dos alertas.
#: Acima dela `causas_conferem` sai falso e a tela é obrigada a dizer de que janela cada
#: número saiu.
TOLERANCIA_DAS_CAUSAS_PCT = 1.0


class CausaOut(BaseModel):
    """Uma fatia do ranking de causas — por que a usina parou e quanto isso custou."""

    categoria: str
    eventos: int
    #: Energia perdida atribuída a esta causa, recortada ao mês. `None` = o upstream não
    #: trouxe o número em nenhum dos eventos da categoria.
    energia_kwh: float | None = None
    #: Horas paradas somadas por inversor afetado. `None` quando algum evento da categoria
    #: veio sem duração — somar só os que têm faria a conta parecer menor do que foi.
    horas: float | None = None
    #: A causa estava fora do alcance da manutenção. É o que a contratual desconta.
    externa: bool = False
    #: `False` = o operador ainda não classificou estes eventos.
    classificada: bool = False


class EventoDeParada(BaseModel):
    """Uma parada do mês, com a causa e a classificação.

    **A contagem é por parada, não por evento agrupado por escopo.** O agrupamento
    "usina / skid / inversor" do meuWatt mora no front dele e nos endpoints
    `/shadow-breakdowns`, que respondem 403 ao nosso token de serviço — replicá-lo daqui
    seria inventar um segundo detector, que divergiria do primeiro na primeira mudança.
    """

    #: Dia BRT de início, `YYYY-MM-DD`. É o mesmo critério de recorte de
    #: `api/v1/paradas.py` (`stopped_at::date`), para as duas telas cortarem igual.
    inicio: str
    #: Dia BRT do fim. `None` = ainda em aberto.
    fim: str | None = None
    em_aberto: bool = False
    #: `parada` (inversor sem produzir) ou `degradacao` (produzindo abaixo dos pares).
    tipo: str = "parada"
    #: A UC afetada, pelo nome. `None` = o upstream não resolveu o transformador.
    unidade: str | None = None
    #: O motivo classificado pelo operador. `None` = ainda não classificada.
    causa: str | None = None
    origem: str | None = None
    externa: bool = False
    classificada: bool = False
    #: Quantos inversores a parada atingiu. Só passa de 1 quando o próprio meuWatt agrupou
    #: as linhas (`manual_group_id`, que é agrupamento PERSISTIDO no banco dele).
    inversores_afetados: int = 1
    horas: float | None = None
    energia_kwh: float | None = None


class MarcoOut(BaseModel):
    """Um card da timeline curada. Conteúdo 100 % autorado pela operação."""

    id: str
    #: Instante do marco, ISO. Hora 00:00 = marco "de dia inteiro".
    em: str
    #: `parada | retomada | normalizado | recorrente | degradacao | manutencao | info`.
    tom: str
    chip: str
    titulo: str
    sub: str | None = None
    #: Os marcos do MESMO evento compartilham o grupo (parada → retomada → normalizado).
    grupo: str | None = None


class TimelineOut(BaseModel):
    #: O operador ligou a seção para este mês. `False` = a seção não existe no mês, e a
    #: tela não desenha uma espinha vazia.
    exibir: bool = False
    marcos: list[MarcoOut] = []


class ConsideracoesOut(BaseModel):
    """O fechamento narrativo do mês, escrito pela equipe. Somente leitura no portal:
    escrever é trabalho de operação."""

    texto: str
    autor: str | None = None
    #: Instante da última edição, ISO.
    em: str | None = None


class RegraDoFechamentoOut(BaseModel):
    potencial: str
    perda: str
    horas: str
    causas: str


class RelatorioMesOut(BaseModel):
    referencia: str
    inicio: str
    fim: str
    rotulo: str
    em_curso: bool = False
    dia_de_corte: int | None = None

    # ── os números que vêm do painel, sem recontar ───────────────────────
    #: Cópia do painel do mesmo mês — está aqui para o potencial ser CONFERÍVEL na própria
    #: resposta, não para ser uma segunda medição.
    medido_inversores_kwh: float | None = None
    perdida_kwh: float | None = None
    projeto_proporcional_kwh: float | None = None
    medido_vs_projeto_pct: float | None = None

    # ── o par que separa clima de parada ─────────────────────────────────
    #: `medido + perdido em paradas` — o que a usina teria entregue se não tivesse parado.
    potencial_kwh: float | None = None
    #: `(potencial − projeto) ÷ projeto`, em %. O cartão mais valioso da aba: com ele bom e
    #: o `medido_vs_projeto_pct` ruim, o mês foi de paradas — não de falta de sol.
    potencial_vs_projeto_pct: float | None = None

    #: Quanto da geração do mês se perdeu: `perdida ÷ (base + perdida)`, em %.
    perda_pct: float | None = None
    #: `fronteira` ou `inversor` — sobre qual medição o percentual acima foi tirado. A
    #: fronteira manda quando existe e cobre o mês inteiro; sai declarado porque as duas
    #: bases dão números diferentes para a mesma pergunta.
    perda_base: str | None = None
    #: De onde veio `perdida_kwh`. É o mesmo número que sustenta a disponibilidade.
    perda_origem: str | None = None

    # ── a régua do tempo ─────────────────────────────────────────────────
    #: Horas paradas somadas por inversor afetado, no recorte diurno. `None` quando algum
    #: evento veio sem duração.
    horas_paradas: float | None = None
    #: O denominador: horas de sol decorridas × nº de inversores. Sem ele, `141h` soam
    #: como uma semana parada.
    horas_possiveis: float | None = None
    #: Quantos inversores entraram no denominador. O percentual nunca sai sem ele.
    inversores_considerados: int | None = None
    #: Eventos cuja duração o monitoramento não soube calcular — é o motivo de
    #: `horas_paradas` sair em travessão.
    eventos_sem_duracao: int = 0

    # ── o porquê ─────────────────────────────────────────────────────────
    causas: list[CausaOut] = []
    eventos: list[EventoDeParada] = []
    #: `alertas` = as paradas foram lidas; `None` = não foram, e `causas`/`eventos` vazios
    #: significam "não sei", não "não parou".
    paradas_origem: str | None = None
    #: A soma de `causas[].energia_kwh`. Vem de OUTRA janela que a `perdida_kwh`.
    causas_total_kwh: float | None = None
    causas_origem: str | None = None
    #: As duas leituras da mesma perda batem dentro de `TOLERANCIA_DAS_CAUSAS_PCT`.
    #: `None` = falta um dos lados para comparar.
    causas_conferem: bool | None = None
    eventos_agrupamento: str

    consideracoes: ConsideracoesOut | None = None
    timeline: TimelineOut = TimelineOut()

    regra: RegraDoFechamentoOut
    aviso: str | None = None


_REGRA_DO_FECHAMENTO = RegraDoFechamentoOut(
    potencial=(
        "Energia potencial = energia medida + energia perdida em paradas. É o que a usina "
        "teria entregue se não tivesse parado."
    ),
    perda=(
        "A energia perdida é a mesma que sustenta a disponibilidade do portal — um número "
        "só para a mesma pergunta."
    ),
    horas=(
        "As horas paradas somam o tempo de CADA inversor afetado, só no período diurno: "
        "uma parada de 1h que atinge 3 inversores soma 3h. O total possível é multiplicado "
        "pela mesma régua — horas de sol decorridas × nº de inversores."
    ),
    causas=(
        "As causas vêm da classificação feita pela equipe. Parada ainda sem causa aparece "
        "como não classificada, e não é distribuída entre as demais."
    ),
)

#: A frase que a tela imprime ao lado da lista de eventos. Está aqui, e não no portal,
#: porque é a declaração de uma limitação REAL da fonte — se ela mudar, muda no servidor.
AGRUPAMENTO_DOS_EVENTOS = (
    "Uma linha por parada registrada pelo monitoramento. Paradas que a equipe agrupou "
    "aparecem numa linha só, com o número de inversores atingidos."
)


# ── leitura das paradas classificadas ───────────────────────────────────────


def _dia_brt(valor: Any) -> date | None:
    """O dia da usina em que o instante caiu. `_instante_local` converte o carimbo UTC do
    meuWatt para o fuso da usina antes — sem isso, uma parada do fim da tarde escorregaria
    para o dia seguinte."""
    instante = _instante_local(valor)
    return instante.date() if instante else None


def _perda_no_mes(parada: dict[str, Any], inicio: date, fim: date) -> float | None:
    """A perda da parada, recortada ao mês.

    `daily_losses` são as fatias por dia BRT do próprio motor de perdas (Σ = a perda da
    parada). Com elas, a parada que atravessa a virada do mês entra só com o pedaço daqui
    — sem estimar nada. Sem elas vale a perda inteira, que é o que o upstream sabe dizer.
    """
    fatias = _lista(parada.get("daily_losses"))
    if fatias:
        soma = 0.0
        houve = False
        for fatia in fatias:
            dia = _data(fatia.get("d"))
            kwh = _numero(fatia.get("kwh"))
            if dia is None or kwh is None or not (inicio <= dia <= fim):
                continue
            soma += kwh
            houve = True
        return round(soma, 2) if houve else None
    return _numero(parada.get("estimated_loss_kwh"))


def _e_degradacao(parada: dict[str, Any]) -> bool:
    return str(parada.get("kind") or "stop") == "degradation"


def _classificacao(parada: dict[str, Any]) -> tuple[str, str | None, bool, bool]:
    """`(categoria, origem, externa, classificada)` de uma parada.

    Degradação tem categoria própria: o inversor estava PRODUZINDO, e chamar isso de
    parada misturaria duas coisas que o cliente precisa distinguir.
    """
    if _e_degradacao(parada):
        return BAIXA_GERACAO, _texto(parada.get("origem")), False, True
    motivo = _texto(parada.get("motivo")) or _texto(parada.get("causa"))
    if motivo is None:
        return SEM_CLASSIFICACAO, None, False, False
    return motivo, _texto(parada.get("origem")), bool(parada.get("is_external_cause")), True


def _grupos_de_parada(
    paradas: list[dict[str, Any]], inicio: date, fim: date
) -> list[list[dict[str, Any]]]:
    """As paradas do mês, agrupadas SÓ pelo `manual_group_id`.

    Esse identificador é agrupamento persistido no banco do meuWatt (a equipe juntou as
    linhas à mão) — não a dedução do front dele, que não alcançamos. Parada sem ele é uma
    linha sozinha, e é assim que a lista fica honesta: nunca inventamos um agrupamento,
    nunca escondemos um que a equipe fez.
    """
    grupos: dict[str, list[dict[str, Any]]] = {}
    soltas: list[list[dict[str, Any]]] = []
    for parada in paradas:
        dia = _dia_brt(parada.get("started_at"))
        if dia is None or not (inicio <= dia <= fim):
            continue
        chave = _texto(parada.get("manual_group_id"))
        if chave:
            grupos.setdefault(chave, []).append(parada)
        else:
            soltas.append([parada])
    return sorted(
        [*grupos.values(), *soltas],
        key=lambda g: min(str(p.get("started_at") or "") for p in g),
    )


def _evento_do_grupo(
    grupo: list[dict[str, Any]], inicio: date, fim: date
) -> EventoDeParada:
    """Uma linha da lista de eventos, a partir das paradas agrupadas pela equipe."""
    # A classificação do grupo é a da primeira linha classificada — a equipe classifica o
    # grupo, não cada inversor. Nenhuma classificada, e o grupo é "não classificada".
    classificados = [p for p in grupo if _classificacao(p)[3]]
    categoria, origem, externa, classificada = _classificacao(
        classificados[0] if classificados else grupo[0]
    )
    degradacao = all(_e_degradacao(p) for p in grupo)

    comecos = [d for d in (_dia_brt(p.get("started_at")) for p in grupo) if d]
    fins = [_dia_brt(p.get("resolved_at")) for p in grupo]
    em_aberto = any(
        bool(p.get("is_active")) if "is_active" in p else p.get("resolved_at") is None
        for p in grupo
    )

    duracoes = [_numero(p.get("duration_minutes")) for p in grupo]
    horas = (
        None
        if any(d is None for d in duracoes)
        else round(sum(d for d in duracoes if d is not None) / 60, 2)
    )
    perdas = [_perda_no_mes(p, inicio, fim) for p in grupo]
    presentes = [p for p in perdas if p is not None]
    unidade = next(
        (_texto(p.get("transformer_name")) for p in grupo if _texto(p.get("transformer_name"))),
        None,
    )

    return EventoDeParada(
        inicio=min(comecos).isoformat(),
        fim=(None if em_aberto or any(f is None for f in fins) else max(fins).isoformat()),
        em_aberto=em_aberto,
        tipo="degradacao" if degradacao else "parada",
        unidade=unidade,
        causa=None if categoria == SEM_CLASSIFICACAO else categoria,
        origem=origem,
        externa=externa,
        classificada=classificada,
        inversores_afetados=len(grupo),
        # Degradação não tem hora offline: o aparelho estava ligado, só rendendo menos. Os
        # kWh dela continuam contando — a energia foi perdida do mesmo jeito.
        horas=0.0 if degradacao else horas,
        energia_kwh=round(sum(presentes), 2) if presentes else None,
    )


def _causas(eventos: list[EventoDeParada]) -> list[CausaOut]:
    """O ranking de causas, por energia perdida. Uma linha por categoria."""
    acumulado: dict[str, dict[str, Any]] = {}
    for evento in eventos:
        rotulo = (
            BAIXA_GERACAO
            if evento.tipo == "degradacao"
            else (evento.causa or SEM_CLASSIFICACAO)
        )
        linha = acumulado.setdefault(
            rotulo,
            {
                "eventos": 0,
                "energia": [],
                "horas": [],
                "externa": evento.externa,
                "classificada": evento.classificada,
            },
        )
        linha["eventos"] += 1
        linha["energia"].append(evento.energia_kwh)
        linha["horas"].append(evento.horas)

    saida = [
        CausaOut(
            categoria=rotulo,
            eventos=linha["eventos"],
            energia_kwh=_soma(linha["energia"]),
            # Mesma régua de `api/v1/paradas.py`: falta uma duração, o total da categoria
            # sai em travessão em vez de parecer menor do que foi.
            horas=(
                None
                if any(h is None for h in linha["horas"])
                else round(sum(h for h in linha["horas"] if h is not None), 2)
            ),
            externa=linha["externa"],
            classificada=linha["classificada"],
        )
        for rotulo, linha in acumulado.items()
    ]
    # Por energia perdida, do maior para o menor — a categoria sem número vai para o fim,
    # nunca para o topo com um zero que ninguém mediu.
    return sorted(saida, key=lambda c: (c.energia_kwh is None, -(c.energia_kwh or 0.0)))


def _horas_possiveis(
    relatorio: dict[str, Any], inicio: date, fim_medido: date, agora: datetime
) -> tuple[float | None, int | None]:
    """`(horas-inversor de sol decorridas, nº de inversores)` — o denominador da régua.

    A mesma janela solar que o monitoramento usa para recortar a duração das paradas
    (`daily_solar_windows`), multiplicada pelo número de inversores: é o que faz numerador
    e denominador nunca usarem réguas diferentes. No mês em curso o dia de hoje entra só
    até agora — contá-lo inteiro faria a fração parada parecer menor do que é.
    """
    transformadores = _lista(relatorio.get("transformers"))
    inversores = sum(
        int(_numero(t.get("inverter_count")) or 0) for t in transformadores
    ) or len(_lista(relatorio.get("inverters")))
    if inversores <= 0:
        return None, None

    minutos = 0.0
    for janela in _lista(relatorio.get("daily_solar_windows")):
        dia = _data(janela.get("date"))
        if dia is None or not (inicio <= dia <= fim_medido):
            continue
        nascer = _instante_local(janela.get("sunrise_utc"))
        por = _instante_local(janela.get("sunset_utc"))
        if nascer is not None and por is not None and por > nascer:
            fecha = min(por, agora) if dia == agora.date() else por
            if fecha > nascer:
                minutos += (fecha - nascer).total_seconds() / 60
            continue
        # Sem o par nascer/pôr, o upstream ainda diz quanto durou o dia — só não dá para
        # recortar em "agora", e o dia de hoje entra inteiro.
        duracao = _numero(janela.get("duration_min"))
        if duracao is not None and duracao > 0:
            minutos += duracao

    if minutos <= 0:
        return None, inversores
    return round(minutos * inversores / 60, 1), inversores


def _consideracoes(observacoes: Any) -> ConsideracoesOut | None:
    """A caixa `dash:gerais` do mês. Ausente = a seção não existe, e isso não é erro.

    Várias observações na mesma seção: vale a mais recente. O meuWatt trata a caixa como
    um DOCUMENTO único do mês ("Última edição por Fulano em dd/mm"), não como uma
    conversa — publicar todas as versões aqui seria mostrar rascunho como fechamento.
    """
    candidatas = [
        o
        for o in _lista(observacoes)
        if _texto(o.get("section")) == SECAO_DAS_CONSIDERACOES and _texto(o.get("body"))
    ]
    if not candidatas:
        return None
    escolhida = max(
        candidatas, key=lambda o: str(o.get("updated_at") or o.get("created_at") or "")
    )
    editado = _instante_local(escolhida.get("updated_at") or escolhida.get("created_at"))
    return ConsideracoesOut(
        texto=_texto(escolhida.get("body")) or "",
        autor=_texto(escolhida.get("user_name")),
        em=editado.isoformat() if editado else None,
    )


def _timeline(bruta: Any) -> TimelineOut:
    """A timeline curada, se a equipe ligou a seção para o mês.

    `show_in_report` falso — ou mês nunca curado, que o upstream devolve como falso e sem
    marcos — significa que a seção **não existe** naquele mês. É decisão de produto do
    meuWatt, e ela atravessa: uma espinha vazia é pior que seção nenhuma.
    """
    corpo = _dicionario(bruta)
    if not corpo.get("show_in_report"):
        return TimelineOut()
    marcos: list[MarcoOut] = []
    for bruto in _lista(corpo.get("milestones")):
        identidade = _texto(bruto.get("id"))
        instante = _instante_local(bruto.get("at"))
        tom = _texto(bruto.get("tone"))
        titulo = _texto(bruto.get("title"))
        if not identidade or instante is None or not tom or not titulo:
            continue
        marcos.append(
            MarcoOut(
                id=identidade,
                em=instante.isoformat(),
                tom=tom,
                chip=_texto(bruto.get("chip")) or "",
                titulo=titulo,
                sub=_texto(bruto.get("sub")),
                grupo=_texto(bruto.get("group")),
            )
        )
    # A ORDEM DO ARRAY é conteúdo autoral: o editor do meuWatt reordena por setas e o
    # servidor de lá NÃO re-ordena por data. Reordenar aqui reescreveria a narrativa.
    return TimelineOut(exibir=True, marcos=marcos)


def _fechamento_sem_dados(
    alvo: date, inicio: date, fim: date, em_curso: bool, aviso: str
) -> RelatorioMesOut:
    """A aba abre vazia e dizendo o motivo — nunca com zeros, que se leem como medição."""
    return RelatorioMesOut(
        referencia=alvo.isoformat(),
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        rotulo=_rotulo_do_periodo("mes", alvo),
        em_curso=em_curso,
        eventos_agrupamento=AGRUPAMENTO_DOS_EVENTOS,
        regra=_REGRA_DO_FECHAMENTO,
        aviso=aviso,
    )


@router.get("/usinas/{plant_link_id}/relatorio-mes", response_model=RelatorioMesOut)
async def relatorio_do_mes(
    plant_link_id: int,
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> RelatorioMesOut:
    """O fechamento do mês: potencial, causas, horas com denominador e as considerações.

    **Travado no mês**, sem `recorte`: o fechamento narrativo de um ano não existe — as
    considerações, a timeline e a classificação das paradas são todas escritas mês a mês.

    **Compõe o painel, não o reescreve.** Os números de geração saem do MESMO
    `_painel_do_mes` que responde `/painel` — daí `potencial_kwh` ser exatamente
    `medido_inversores_kwh + perdida_kwh` do painel do mesmo mês, e não um parecido. Três
    leituras entram além das cinco do painel: as paradas classificadas, as observações e a
    timeline curada. **Nenhuma delas derruba a resposta**: cada uma fora do ar tira o seu
    bloco e escreve um aviso.
    """
    link = _usina_monitorada(db, usuario, plant_link_id)
    hoje = hoje_na_usina()
    alvo = _referencia_pedida(referencia)
    inicio, fim = _janela("mes", alvo)
    fim_medido = min(fim, hoje)
    em_curso = inicio <= hoje <= fim

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001 — sem ponte a aba ainda abre, vazia e honesta
        return _fechamento_sem_dados(
            alvo, inicio, fim, em_curso, f"Monitoramento indisponível: {exc}"
        )

    (
        relatorio,
        pvsyst,
        manual,
        fronteira,
        faturas,
        paradas,
        observacoes,
        timeline,
    ) = await asyncio.gather(
        cliente.geracao_periodo(link.mw_plant_slug, inicio, fim_medido),
        cliente.pvsyst(link.mw_plant_slug, inicio, fim),
        cliente.pvsyst_manual(link.mw_plant_slug, alvo.year),
        cliente.ssu_totais_mensais(link.mw_plant_slug, alvo.year),
        cliente.faturas_concessionaria(link.mw_plant_slug, alvo.year),
        cliente.paradas_classificadas(link.mw_plant_slug),
        cliente.observacoes(link.mw_plant_slug, PERIODO_MENSAL, inicio),
        cliente.timeline_de_paradas(link.mw_plant_slug, alvo.year, alvo.month),
        return_exceptions=True,
    )

    if isinstance(relatorio, BaseException) or not isinstance(relatorio, dict):
        motivo = relatorio if isinstance(relatorio, BaseException) else "resposta inesperada"
        return _fechamento_sem_dados(
            alvo, inicio, fim, em_curso, f"Monitoramento indisponível: {motivo}"
        )

    avisos: list[str] = []
    if isinstance(pvsyst, BaseException):
        avisos.append("a meta diária do projeto não veio")
        pvsyst = {}
    if isinstance(manual, BaseException):
        avisos.append("a meta mensal do projeto não veio")
        manual = {}
    if isinstance(fronteira, BaseException):
        avisos.append("a medição na fronteira não veio")
        fronteira = {}
    if isinstance(faturas, BaseException):
        avisos.append("as faturas da distribuidora não vieram")
        faturas = []
    if isinstance(paradas, BaseException) or not isinstance(paradas, list):
        avisos.append("as paradas classificadas não vieram")
        paradas = None
    if isinstance(observacoes, BaseException):
        avisos.append("as considerações do mês não vieram")
        observacoes = []
    if isinstance(timeline, BaseException):
        avisos.append("a timeline de paradas não veio")
        timeline = {}

    # O painel do MESMO mês, montado pela MESMA função que responde `/painel`. É o que faz
    # o potencial daqui e o medido de lá serem o mesmo byte em vez de dois números
    # parecidos — a lição que custou "−64,3 % numa tela e +101,7 % na outra".
    painel = _painel_do_mes(
        alvo=alvo,
        inicio=inicio,
        fim=fim,
        fim_medido=fim_medido,
        hoje=hoje,
        em_curso=em_curso,
        relatorio=relatorio,
        pvsyst=pvsyst,
        manual=manual,
        fronteira=fronteira if isinstance(fronteira, dict) else {},
        faturas=faturas,
    )

    medido = painel.medido_inversores_kwh
    perdida = painel.perdida_kwh
    potencial = (
        round(medido + perdida, 2) if medido is not None and perdida is not None else None
    )

    # A BASE da perda: a fronteira manda quando existe e cobre o mês inteiro — é o ponto de
    # entrega, onde a energia de fato chegou. Fronteira PARCIAL não serve de base: a
    # diferença dela para o medido não é perda, é medidor a menos.
    if painel.medido_fronteira_kwh is not None and not painel.fronteira_parcial:
        base_kwh, perda_base = painel.medido_fronteira_kwh, "fronteira"
    elif medido is not None:
        base_kwh, perda_base = medido, "inversor"
    else:
        base_kwh, perda_base = None, None
    perda_pct = (
        round(perdida / (base_kwh + perdida) * 100, 2)
        if perdida is not None and base_kwh is not None and (base_kwh + perdida) > 0
        else None
    )

    eventos = (
        [_evento_do_grupo(g, inicio, fim) for g in _grupos_de_parada(paradas, inicio, fim)]
        if paradas is not None
        else []
    )
    causas = _causas(eventos)
    causas_total = _soma([c.energia_kwh for c in causas]) if causas else None
    horas = [e.horas for e in eventos]
    horas_possiveis, inversores = _horas_possiveis(
        relatorio, inicio, fim_medido, agora_na_usina().replace(tzinfo=None)
    )

    return RelatorioMesOut(
        referencia=alvo.isoformat(),
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        rotulo=painel.rotulo,
        em_curso=em_curso,
        dia_de_corte=painel.dia_de_corte,
        medido_inversores_kwh=medido,
        perdida_kwh=perdida,
        projeto_proporcional_kwh=painel.projeto_proporcional_kwh,
        medido_vs_projeto_pct=painel.desvios.medido_vs_projeto_pct,
        potencial_kwh=potencial,
        potencial_vs_projeto_pct=_desvio(potencial, painel.projeto_proporcional_kwh),
        perda_pct=perda_pct,
        perda_base=perda_base if perda_pct is not None else None,
        perda_origem="monitoramento" if perdida is not None else None,
        horas_paradas=(
            None
            if (not eventos or any(h is None for h in horas))
            else round(sum(h for h in horas if h is not None), 2)
        ),
        horas_possiveis=horas_possiveis,
        inversores_considerados=inversores,
        eventos_sem_duracao=sum(1 for e in eventos if e.horas is None),
        causas=causas,
        eventos=eventos,
        paradas_origem="alertas" if paradas is not None else None,
        causas_total_kwh=causas_total,
        causas_origem="alertas" if paradas is not None else None,
        causas_conferem=(
            None
            if causas_total is None or not perdida
            else abs(causas_total - perdida) / perdida * 100 <= TOLERANCIA_DAS_CAUSAS_PCT
        ),
        eventos_agrupamento=AGRUPAMENTO_DOS_EVENTOS,
        consideracoes=_consideracoes(observacoes),
        timeline=_timeline(timeline),
        regra=_REGRA_DO_FECHAMENTO,
        aviso=("Faltou parte dos dados: " + " · ".join(avisos) + "." if avisos else None),
    )
