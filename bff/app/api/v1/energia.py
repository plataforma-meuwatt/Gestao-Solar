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
    _janela,
    _referencia_pedida,
    _usina_monitorada,
)
from app.core.datas import BRT
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
    #: `False` faz a tela dizer "sem estação" em vez de desenhar uma curva rasteira.
    tem_estacao: bool = False
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

    Uma queda do monitoramento vira 200 com `aviso` e campos nulos — a tela mostra
    travessão e diz o que faltou, em vez de uma página de erro ou, pior, de zeros.
    """
    link = _usina_monitorada(db, usuario, plant_link_id)
    referencia = _referencia_pedida(data)
    saida = DiaOut(dia=referencia.isoformat())

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        diario, intraday = await asyncio.gather(
            cliente.geracao_diaria(link.mw_plant_slug, referencia),
            cliente.intraday(link.mw_plant_slug, referencia),
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

    saida.curva, saida.tem_estacao = _curva_da_usina(intraday)
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
        saida.hpoa_agora = poa if saida.tem_estacao else None

    if saida.tem_estacao:
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
# QUATRO DECISÕES DECLARADAS, porque cada uma tinha duas saídas defensáveis:
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
    em_curso: bool = False
    futuro: bool = False


class TotaisOut(BaseModel):
    medido_kwh: float | None = None
    projeto_kwh: float | None = None
    #: O projeto rateado pelos dias já decorridos — comparar mês inteiro com meio mês
    #: acusaria de doente uma usina em dia.
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
    hpoa_projeto: float | None = None
    ghi_projeto: float | None = None
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
    projeto_kwh: float | None = None
    projeto_proporcional_kwh: float | None = None
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


def _ajustado(bruto: float, indisponibilidade: Any, derating: Any) -> float:
    """O EARRAY do projeto descontado da indisponibilidade e do derating declarados.

    É a mesma correção que o meuWatt aplica em todas as telas de geração: comparar o
    medido com um projeto que ignora a parada programada e a degradação declarada faz a
    usina parecer pior do que é.
    """
    indisp = max(0.0, 1 - (_numero(indisponibilidade) or 0.0) / 100)
    derat = max(0.0, 1 - (_numero(derating) or 0.0) / 100)
    return bruto * indisp * derat


def _manual_por_mes(manual: Any) -> dict[int, dict[str, Any]]:
    """`rows[].{month, e_array, poa, ghi, derating, …}` → `{mês: linha}`."""
    return {
        linha["month"]: linha
        for linha in _lista(_dicionario(manual).get("rows"))
        if isinstance(linha.get("month"), int)
        and not isinstance(linha["month"], bool)
        and 1 <= linha["month"] <= 12
    }


def _projeto_por_dia(pvsyst: Any, derating_do_mes: dict[int, Any]) -> dict[str, float]:
    """O projeto de cada dia, já ajustado. `{'YYYY-MM-DD': kWh}`."""
    saida: dict[str, float] = {}
    for linha in _lista(_dicionario(pvsyst).get("rows")):
        dia = _data(linha.get("date"))
        bruto = _numero(linha.get("e_array"))
        if dia is not None and bruto is not None:
            saida[dia.isoformat()] = _ajustado(
                bruto, linha.get("indisponibilidade"), derating_do_mes.get(dia.month)
            )
    return saida


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
    """EARRAY × (irradiação medida ÷ irradiação do projeto), do cadastro manual.

    Preferência pelo plano inclinado (POA), que é o mesmo plano da estação; o horizontal
    (GHI) é a segunda opção. Sem irradiação de projeto cadastrada não há correção — e
    inventar uma seria pior do que não ter o número.
    """
    if not linha:
        return None
    earray = _numero(linha.get("e_array"))
    if earray is None or earray <= 0:
        return None
    poa = _numero(linha.get("poa"))
    if poa and poa > 0 and hpoa_medida > 0:
        return earray * (hpoa_medida / poa)
    ghi = _numero(linha.get("ghi"))
    if ghi and ghi > 0 and ghi_medida > 0:
        return earray * (ghi_medida / ghi)
    return None


# ── contas de tela ──────────────────────────────────────────────────────────


def _desvio(aferido: float | None, referencia: float | None) -> float | None:
    """`(aferido − referência) ÷ referência`, em %. Referência nula ou zero não compara."""
    if aferido is None or referencia is None or referencia <= 0:
        return None
    return round((aferido - referencia) / referencia * 100, 2)


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
    fronteira_mwh: float | None, faturado_mwh: float | None, *, parcial: bool = False
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
) -> MeteoOut:
    """Os KPIs de meteorologia, derivados dos pontos que já foram montados."""
    ambientes = [p.t_amb for p in pontos if p.t_amb is not None]
    modulos = [p.t_mod for p in pontos if p.t_mod is not None]
    modulos_max = [p.t_mod_max for p in pontos if p.t_mod_max is not None]
    return MeteoOut(
        tem_estacao=hpoa > 0 or ghi > 0,
        tem_sensor_temperatura=bool(ambientes or modulos),
        hpoa=_arredondar(hpoa) if hpoa > 0 else None,
        ghi=_arredondar(ghi) if ghi > 0 else None,
        razao=round(hpoa / ghi, 3) if hpoa > 0 and ghi > 0 else None,
        hpoa_projeto=_arredondar(hpoa_projeto) if hpoa_projeto else None,
        ghi_projeto=_arredondar(ghi_projeto) if ghi_projeto else None,
        t_amb_media=_arredondar(sum(ambientes) / len(ambientes), 1) if ambientes else None,
        t_amb_max=_arredondar(max(ambientes), 1) if ambientes else None,
        t_mod_media=_arredondar(sum(modulos) / len(modulos), 1) if modulos else None,
        t_mod_max=_arredondar(max(modulos_max), 1) if modulos_max else None,
        pontos=pontos,
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
    derating = {mes: linha.get("derating") for mes, linha in manual_do_ano.items()}

    projeto_diario = _projeto_por_dia(pvsyst, derating)
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

    # Projeto: o EARRAY mensal digitado é a fonte canônica; a soma dos dias importados só
    # entra onde não há entrada manual. A importação diária costuma cobrir o mês pela
    # metade, e somá-la como se fosse o mês inteiro rebaixaria o projeto sem motivo.
    earray = _numero(_dicionario(linha_manual).get("e_array")) or 0.0
    soma_diaria = sum(projeto_diario.get(d.data, 0.0) for d in dias)
    projeto = earray if earray > 0 else (soma_diaria if soma_diaria > 0 else None)
    proporcional = (
        round(projeto * dia_de_corte / dias_no_mes, 2)
        if projeto is not None and em_curso and dia_de_corte
        else projeto
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

    previsto = _previsto_manual(linha_manual, hpoa_medida, ghi_medida)
    origem: str | None = "manual_corrigido" if previsto is not None else None
    if previsto is None:
        # Sem correção pela meteo digitada, o previsto é o próprio PVsyst diário — na
        # mesma janela do medido, senão a comparação seria de meio mês contra um mês.
        base = sum(
            kwh for chave, kwh in projeto_diario.items()
            if (_data(chave) or date.max) <= fim_medido
        ) if em_curso else soma_diaria
        if base > 0:
            previsto, origem = base, "pvsyst_diario"

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
        projeto_kwh=_arredondar(projeto),
        projeto_proporcional_kwh=_arredondar(proporcional),
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
            previsto_vs_projeto_pct=_desvio(previsto, proporcional),
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
        ),
        dias=dias,
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
    derating = {mes: linha.get("derating") for mes, linha in manual_do_ano.items()}

    diarios = _diarios(relatorio)
    mensais = _mensais(relatorio)
    medidos = _medido_por_mes(relatorio, ano)
    irradiacao = _irradiacao_por_dia(relatorio)
    temperatura = _temperatura_por_dia(relatorio)
    faturado_do_ano = _faturado_por_mes(faturas)

    # Acumuladores por mês do ano pedido. Tudo o que vem por DIA é somado aqui uma vez só.
    projeto: dict[int, float] = {}
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

    for chave, kwh in _projeto_por_dia(pvsyst, derating).items():
        if dia := _no_ano(chave):
            projeto[dia.month] = projeto.get(dia.month, 0.0) + kwh
    for chave, valor in _globinc_por_dia(pvsyst).items():
        if dia := _no_ano(chave):
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

    meses: list[MesDoAno] = []
    pontos: list[PontoMeteo] = []
    disponiveis: list[str] = []
    for numero in range(1, 13):
        chave_mes = f"{ano:04d}-{numero:02d}"
        primeiro = date(ano, numero, 1)
        ultimo = date(ano, numero, monthrange(ano, numero)[1])
        futuro = primeiro > hoje
        mes_em_curso = not futuro and ultimo > hoje

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
            if real is None:
                real = _numero(_dicionario(rollup).get("availability_real_pct"))
            if contratual is None:
                contratual = _numero(_dicionario(rollup).get("availability_contratual_pct"))

        linha_manual = manual_do_ano.get(numero)
        earray = _numero(_dicionario(linha_manual).get("e_array")) or 0.0
        projeto_mes = earray if earray > 0 else projeto.get(numero)
        previsto_mes = _previsto_manual(linha_manual, hpoa.get(numero, 0.0), ghi.get(numero, 0.0))
        if previsto_mes is None:
            previsto_mes = projeto.get(numero)

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
                em_curso=mes_em_curso,
                futuro=futuro,
            )
        )
        pontos.append(
            PontoMeteo(
                chave=chave_mes,
                rotulo=_MES_CURTO[numero - 1],
                hpoa=_arredondar(hpoa[numero]) if hpoa.get(numero) else None,
                hpoa_projeto=(
                    _arredondar(hpoa_projeto[numero]) if hpoa_projeto.get(numero) else None
                ),
                ghi=_arredondar(ghi[numero]) if ghi.get(numero) else None,
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

    # O acumulado do ano soma só os meses FECHADOS: incluir o mês em curso compararia meio
    # mês medido com o projeto inteiro dele e rebaixaria o ano sem que nada tivesse
    # acontecido. É a mesma janela deliberada do meuWatt.
    fechados = [m for m in meses if not m.futuro and not m.em_curso]
    medido_ytd = _soma([m.medido_kwh for m in fechados])
    projeto_ytd = _soma([m.projeto_kwh for m in fechados])
    projeto_ano = _soma([m.projeto_kwh for m in meses])
    previsto_ytd = _soma([m.previsto_kwh for m in meses if m.medido_kwh is not None])
    # A fronteira e a fatura seguem a MESMA janela do medido — os meses fechados. Somar a
    # fronteira do ano inteiro poria lado a lado, na mesma faixa de cartões, um acumulado
    # com o mês em curso e outro sem ele; e na conciliação inflaria a diferença com um mês
    # cuja fatura a distribuidora ainda nem emitiu.
    fronteira_ytd = _soma([m.fronteira_mwh for m in fechados])
    fronteira_ytd_kwh = fronteira_ytd * 1000 if fronteira_ytd is not None else None
    faturado_ytd = _soma([m.faturado_mwh for m in fechados])
    perda_fronteira, fronteira_parcial = _perda_ate_a_fronteira(fronteira_ytd_kwh, medido_ytd)

    # A irradiação de projeto do ano acompanha a MEDIDA mês a mês: só entram os meses em que
    # a estação mediu. Somar o projeto de doze meses contra a medição de sete devolveria uma
    # "queda de irradiação" que é só o calendário. Onde não há PVsyst diário, vale o valor
    # mensal digitado — nunca os dois, para não contar o mesmo mês duas vezes.
    meses_com_hpoa = {mes for mes, valor in hpoa.items() if valor > 0}
    meses_com_ghi = {mes for mes, valor in ghi.items() if valor > 0}
    hpoa_projeto_ytd = _irradiacao_de_projeto(
        sum(valor for mes, valor in hpoa_projeto.items() if mes in meses_com_hpoa),
        sum((_numero(manual_do_ano.get(mes, {}).get("poa")) or 0.0) for mes in meses_com_hpoa),
        1.0)
    ghi_projeto_ytd = _irradiacao_de_projeto(
        0.0,
        sum((_numero(manual_do_ano.get(mes, {}).get("ghi")) or 0.0) for mes in meses_com_ghi),
        1.0)

    capacidade = _capacidade(relatorio)

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
        projeto_kwh=projeto_ytd,
        projeto_proporcional_kwh=projeto_ytd,
        previsto_kwh=previsto_ytd,
        previsto_origem=_origem_do_previsto_anual(manual_do_ano, hpoa, ghi, projeto),
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
        perdida_kwh=_soma([m.perdida_kwh for m in fechados]),
        perdida_externa_kwh=_soma([m.perdida_externa_kwh for m in fechados]),
        desvios=DesviosOut(
            medido_vs_projeto_pct=_desvio(medido_ytd, projeto_ytd),
            medido_vs_previsto_pct=_desvio(medido_ytd, previsto_ytd),
            previsto_vs_projeto_pct=_desvio(previsto_ytd, projeto_ytd),
            hpoa_vs_projeto_pct=_desvio(sum(hpoa.values()) or None, hpoa_projeto_ytd),
            ghi_vs_projeto_pct=_desvio(sum(ghi.values()) or None, ghi_projeto_ytd),
        ),
        conciliacao=_conciliacao(
            _arredondar(fronteira_ytd, 3), faturado_ytd, parcial=fronteira_parcial
        ),
        totais=TotaisOut(
            medido_kwh=medido_ytd,
            projeto_kwh=projeto_ano,
            projeto_ate_hoje_kwh=projeto_ytd,
            tendencia_kwh=None,
        ),
        meteo=_meteo(
            pontos=pontos,
            hpoa=sum(hpoa.values()),
            ghi=sum(ghi.values()),
            hpoa_projeto=hpoa_projeto_ytd,
            ghi_projeto=ghi_projeto_ytd,
        ),
        meses=meses,
        meses_disponiveis=disponiveis,
        disponibilidade_tecnica=_disponibilidade_tecnica(
            relatorio, inicio, fim_medido, dias_com_dado
        ),
        regra=_REGRA,
    )


def _origem_do_previsto_anual(
    manual_do_ano: dict[int, dict[str, Any]],
    hpoa: dict[int, float],
    ghi: dict[int, float],
    projeto: dict[int, float],
) -> str | None:
    """De onde veio o previsto do ano. Basta um mês corrigido pela meteo digitada para a
    origem ser a manual — é o que a tela precisa escrever ao lado do número."""
    for mes, linha in manual_do_ano.items():
        if _previsto_manual(linha, hpoa.get(mes, 0.0), ghi.get(mes, 0.0)) is not None:
            return "manual_corrigido"
    return "pvsyst_diario" if projeto else None
