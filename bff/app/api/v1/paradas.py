"""As paradas da usina — quanto tempo e quanta energia o dono perdeu no período.

A fonte é o **detector NOVO** de paradas do meuWatt, `GET /shadow-breakdowns/queue` — o mesmo
que a tela de Paradas de lá lê. O coletor antigo (`/plants/{slug}/breakdowns/range`, com a
reserva `alerts?status=all`) saiu em 24/10/2026: respondia 500 em todas as usinas, e a regra
da casa é nunca usá-lo. O detector pede o id NUMÉRICO da usina; o vínculo guarda o slug, e o
id vem de `GET /plants/{slug}` (o mesmo `plants.id` que o `/monitoring/all` devolve).

O que este módulo decide, e por quê:

- **Parada é a linha `material`.** O detector devolve também `blip`/`immaterial` (piscadas
  curtas, sem perda) e `data_gap` (buraco de coleta: a usina produzia e faltou leitura). A
  tela de Paradas do meuWatt não mostra nenhuma das três como parada, e a tabela ao vivo
  dele (`plant_breakdowns`, a fonte de antes) nunca as recebeu. Uma linha por inversor, como
  antes: o agrupamento por usina/skid (`groups`) é desenho da tela de lá.
- **Perda só com conta feita.** `shadow_loss_kwh` vale quando `loss_method` diz como foi
  calculada; `no_peers` (nem par saudável nem irradiância no dia) grava 0,0 sem conta
  nenhuma — e aqui vira nulo, não zero.
- **Recorte pelo dia BRT do início.** O detector devolve por SOBREPOSIÇÃO (a parada que
  cruza a borda vem inteira); contar pelo início põe cada parada num mês só — o mesmo
  critério do fechamento do mês (`energia.py`).
- **A rodada diz o que foi analisado.** `run.window_start`/`window_end` são as bordas de
  DADOS que o detector julgou. Sem rodada, ou com o período inteiro antes dela, a resposta é
  nula ("não analisado" não é "não parou"); período que começa antes dela encolhe até onde
  ela começa, com aviso; rodada parada há mais de 20 h ganha aviso.
- **Forma estranha é falha, não zero.** Linha sem id, início ou classificação derruba a
  leitura para "sem dados": descartá-la calada faria um mês com paradas sair limpo.

Limite conhecido: a parada que o operador DESCLASSIFICOU no meuWatt continua aparecendo — a
desclassificação só vem no `/shadow-breakdowns/compare`, que esta tela não lê.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import (
    _janela,
    _referencia_pedida,
    _usina_no_escopo,
    sem_monitoramento,
)
from app.core.datas import BRT
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes, vinculos

router = APIRouter(prefix="/api/v1", tags=["app · paradas"])


# ── formato ─────────────────────────────────────────────────────────────────


class ParadaOut(BaseModel):
    id: int
    #: Instante de início, ISO 8601 com fuso.
    inicio: str
    #: `None` = ainda em aberto.
    fim: str | None = None
    #: Minutos parados com sol (`off_minutes` do detector; na aberta, até a última leitura
    #: dele). `None` = o detector não trouxe o número — não é zero.
    duracao_min: float | None = None
    #: Energia perdida em kWh. `None` = o detector não fez a conta (`no_peers`) ou não trouxe.
    perda_kwh: float | None = None
    #: `parada`. O detector só publica parada; degradação (inversor produzindo abaixo dos
    #: pares) não é parada, e a tela de Paradas do meuWatt também a deixa de fora.
    tipo: str
    #: Contexto para o gestor; a tela do cliente não o mostra — análise de equipamento é
    #: trabalho da equipe, não do dono.
    equipamento: str | None = None
    em_aberto: bool
    tom: str


class ParadasOut(BaseModel):
    recorte: str
    #: A janela que o detector de fato analisou: encolhe quando ele começa depois do período.
    inicio: str
    fim: str
    #: `None` = o detector não respondeu ou não analisou o período. Zero é "não parou".
    total: int | None = None
    #: Soma dos minutos parados. `None` se alguma linha veio sem duração — somar só as
    #: que têm faria a conta parecer menor do que foi.
    tempo_parado_min: float | None = None
    #: Soma das perdas. Mesma regra: só quando TODA linha tem o número.
    perda_kwh: float | None = None
    em_aberto: int = 0
    paradas: list[ParadaOut] = []
    #: `detector` (shadow-breakdowns/queue do meuWatt) | `None` (sem leitura).
    fonte: str | None = None
    aviso: str | None = None


# ── a leitura ───────────────────────────────────────────────────────────────

#: Quanto o detector pode ficar sem avançar antes de a leitura deixar de valer "até agora".
#: É a régua do próprio meuWatt (`SIGNAL_STALE_AFTER_HOURS`): à noite ele congela no pôr do
#: sol (~12 h no inverno), e passar de 20 h é detector parado.
ATRASO_TOLERADO = timedelta(hours=20)

#: `loss_method` de quem gravou 0,0 sem ter feito conta.
SEM_CONTA = (None, "", "no_peers")

#: O id NUMÉRICO da usina no meuWatt, por slug — o detector pede o id, o vínculo guarda o slug.
#: ponytail: em memória, por processo e sem validade: o id de uma usina não muda, e um slug
#: renomeado lá já quebra todas as telas dela (o vínculo aponta para o velho).
_ID_NO_MEUWATT: dict[str, int] = {}


async def _id_no_meuwatt(cliente, slug: str) -> int:
    if slug not in _ID_NO_MEUWATT:
        _ID_NO_MEUWATT[slug] = int((await cliente.usina(slug))["id"])
    return _ID_NO_MEUWATT[slug]


def _meia_noite(dia: date) -> str:
    """O instante que abre o dia na usina — `start`/`end` do detector são instantes."""
    return datetime.combine(dia, time(), BRT).isoformat()


def _motivo(exc: Exception) -> str:
    """A frase do produto quando ele escreveu uma ("Sem acesso ao Dashboard de Paradas"),
    senão o status ou o tipo e a mensagem. Nunca o texto do `HTTPStatusError`: ele traz a URL
    do upstream, e o cliente não lê o nome do produto (`test_vocabulario_do_cliente`)."""
    if isinstance(exc, httpx.HTTPStatusError):
        codigo = exc.response.status_code
        dito = integracoes.detalhe_do_upstream(exc.response)
        return f"{codigo} — {dito}" if dito else f"respondeu {codigo}"
    return f"{type(exc).__name__}: {exc}"[:200]


# ── tradução ────────────────────────────────────────────────────────────────


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor)


def _instante(valor: Any) -> datetime | None:
    """ISO 8601 → datetime no fuso da usina. Sem fuso no texto, assume UTC — é como o
    mw-api grava `stopped_at` (timestamptz)."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(BRT)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _de_linha(linha: dict[str, Any]) -> ParadaOut | None:
    """Linha do detector → `ParadaOut`; `None` = não é parada (blip, imaterial, sem dados).

    Linha sem id, início ou classificação é forma que o produto não promete: levanta, e a
    tela diz "sem dados" em vez de contar uma parada a menos.
    """
    inicio = _instante(linha.get("stopped_at"))
    if not isinstance(linha.get("id"), int) or inicio is None or "materiality" not in linha:
        raise ValueError("linha do detector sem id, início ou classificação")
    if linha["materiality"] != "material":
        return None
    fim = _instante(linha.get("resolved_at"))
    em_aberto = fim is None
    return ParadaOut(
        id=linha["id"],
        inicio=inicio.isoformat(),
        fim=_iso(fim),
        duracao_min=_numero(linha.get("off_minutes")),
        perda_kwh=(
            None if linha.get("loss_method") in SEM_CONTA
            else _numero(linha.get("shadow_loss_kwh"))
        ),
        tipo="parada",
        equipamento=linha.get("slot_label") or linha.get("serial_number"),
        em_aberto=em_aberto,
        tom="parado" if em_aberto else "ok",
    )


def _no_periodo(parada: ParadaOut, inicio: date, fim: date) -> bool:
    """Pelo DIA de início, no fuso da usina."""
    dia = datetime.fromisoformat(parada.inicio).date()
    return inicio <= dia <= fim


def _soma_se_todas(valores: list[float | None]) -> float | None:
    if any(v is None for v in valores):
        return None
    return round(sum(v for v in valores if v is not None), 2)


def _consolidar(saida: ParadasOut, paradas: list[ParadaOut], fonte: str) -> ParadasOut:
    paradas.sort(key=lambda p: p.inicio, reverse=True)
    saida.paradas = paradas
    saida.fonte = fonte
    saida.total = len(paradas)
    saida.em_aberto = sum(1 for p in paradas if p.em_aberto)
    saida.tempo_parado_min = _soma_se_todas([p.duracao_min for p in paradas])
    saida.perda_kwh = _soma_se_todas([p.perda_kwh for p in paradas])
    return saida


# ── rota ────────────────────────────────────────────────────────────────────


@router.get("/plants/{plant_link_id}/paradas", response_model=ParadasOut)
async def paradas_da_usina(
    plant_link_id: int,
    recorte: str = "mes",
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ParadasOut:
    """Paradas cujo início cai no mês ou no ano de `referencia` (qualquer dia do período).

    Nunca é 5xx por causa do upstream: detector fora do ar, sem rodada ou em forma estranha
    dá `total=None` com o aviso, e a tela mostra "sem dados" — não "nenhuma parada", que
    seria mentir para o lado bom.
    """
    if recorte not in ("mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'mes' ou 'ano'.")

    link: PlantLink = _usina_no_escopo(db, usuario, plant_link_id)
    inicio, fim = _janela(recorte, _referencia_pedida(referencia))
    saida = ParadasOut(recorte=recorte, inicio=inicio.isoformat(), fim=fim.isoformat())

    if not link.mw_plant_slug:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, sem_monitoramento(link, "o histórico de paradas")
        )

    try:
        cliente = vinculos.cliente_meuwatt(db, usuario.id)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Monitoramento indisponível: {exc}"
        return saida

    try:
        plant_id = await _id_no_meuwatt(cliente, link.mw_plant_slug)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Falha ao ler o detector de paradas do monitoramento: {_motivo(exc)}."
        return saida
    await ler_do_detector(cliente, plant_id, saida)
    return saida


async def ler_do_detector(cliente, plant_id: int, saida: ParadasOut) -> list[dict[str, Any]]:
    """As paradas do período de `saida` (`inicio`/`fim`), pelo detector: preenche `saida` e
    devolve as linhas cruas das paradas que entraram. É a régua ÚNICA — a tela de Paradas e o
    bot do WhatsApp (`assistente_geracao.paradas`, que mostra causa e inversor) contam a mesma
    parada, a mesma perda e o mesmo "não analisado"."""
    inicio, fim = date.fromisoformat(saida.inicio), date.fromisoformat(saida.fim)
    try:
        resposta = await cliente.paradas_detector(
            plant_id, _meia_noite(inicio), _meia_noite(fim + timedelta(days=1))
        )
        pares = [(p, linha) for linha in resposta["rows"] if (p := _de_linha(linha))]
        run = resposta.get("run") or {}
        desde, ate = _instante(run.get("window_start")), _instante(run.get("window_end"))
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Falha ao ler o detector de paradas do monitoramento: {_motivo(exc)}."
        return []

    if desde is None or ate is None or desde.date() > fim:
        saida.aviso = "O detector de paradas do monitoramento não analisou este período."
        return []

    avisos: list[str] = []
    if desde.date() > inicio:
        inicio = desde.date()
        saida.inicio = inicio.isoformat()
        avisos.append(
            f"O detector de paradas do monitoramento analisa a partir de {inicio:%d/%m/%Y}; "
            "antes disso não há leitura."
        )
    borda = min(datetime.combine(fim + timedelta(days=1), time(), BRT), datetime.now(BRT))
    if borda - ate > ATRASO_TOLERADO:
        avisos.append(
            f"O detector de paradas do monitoramento analisou até {ate:%d/%m/%Y às %H:%M}; "
            "o que aconteceu depois ainda não entrou."
        )

    dentro = [(p, linha) for p, linha in pares if _no_periodo(p, inicio, fim)]
    _consolidar(saida, [p for p, _ in dentro], "detector")
    saida.aviso = " ".join(avisos) or None
    return [linha for _, linha in dentro]
