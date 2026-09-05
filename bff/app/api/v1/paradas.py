"""As paradas da usina — quanto tempo e quanta energia o dono perdeu no período.

É a primeira tela do portal que não tem espelho no aplicativo, e o motivo é um defeito
alheio: `GET /plants/{slug}/breakdowns/range` do meuWatt responde **500 em produção**. O
detalhe do inversor (`equipamentos.py`) já avisa que o histórico de paradas ficou de fora
por isso, e a sonda marca `mw.breakdowns` em vermelho desde então.

Causa provável, lida no código do mw-api e **não verificada em execução**: o router recebe
`start`/`end` como `date` e os converte com `.isoformat()` antes de chamar
`list_breakdowns_range(start: str, end: str)`, que os usa em
`text("… pb.stopped_at::date BETWEEN :start AND :end")`. Sob asyncpg, um parâmetro
comparado a `date` precisa chegar como `datetime.date` — a string cai num erro de tipo que
o servidor devolve como 500. O conserto é lá (tipar `date` e não converter); aqui a
resposta é não depender dele:

- **Fonte primária** é o `breakdowns/range`, que já vem recortado por período e com o
  tempo parado calculado pelo produto de origem.
- **Fonte reserva** é `alerts?status=all`, que lista os MESMOS eventos (a tabela é uma só,
  `plant_breakdowns`) sem filtro de período e paginado — o corte por data e a paginação
  ficam com o BFF.

O contrato que sai daqui é **o mesmo nas duas fontes**. Quando o mw-api voltar a responder,
a fonte troca sozinha, e a tela não muda nem precisa saber. O campo `fonte` diz de onde veio
para o gestor conseguir conferir; o `aviso` diz ao cliente que a energia perdida pode vir
de estimativa.

Uma falha da primária é lembrada por uma hora, em memória: sem isso, cada página aberta
gastaria uma chamada que se sabe que vai falhar — e esperaria o timeout dela — antes de ir
à reserva. É o mesmo raciocínio do cache de autorização da ficha (`manutencao.py`):
memória do processo, não do sistema; num deploy com duas instâncias cada uma aprende por
conta própria, e isso é aceitável para um defeito que dura semanas.
"""

import asyncio
import time
from datetime import UTC, date, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import _janela, _referencia_pedida, _usina_no_escopo
from app.core.datas import BRT
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · paradas"])


# ── formato ─────────────────────────────────────────────────────────────────


class ParadaOut(BaseModel):
    id: int
    #: Instante de início, ISO 8601 com fuso.
    inicio: str
    #: `None` = ainda em aberto.
    fim: str | None = None
    #: Minutos parados. `None` quando o produto de origem não soube calcular (o alerta
    #: sem janela solar, por exemplo) — não é zero.
    duracao_min: float | None = None
    #: Energia perdida em kWh. `None` = o upstream não trouxe o número.
    perda_kwh: float | None = None
    #: `parada` (inversor sem produzir) ou `degradacao` (produzindo abaixo dos pares).
    tipo: str
    #: Contexto para o gestor; a tela do cliente não o mostra — análise de equipamento é
    #: trabalho da equipe, não do dono.
    equipamento: str | None = None
    em_aberto: bool
    tom: str


class ParadasOut(BaseModel):
    recorte: str
    inicio: str
    fim: str
    #: `None` = nenhuma das duas fontes respondeu. Zero é "não parou".
    total: int | None = None
    #: Soma dos minutos parados. `None` se alguma linha veio sem duração — somar só as
    #: que têm faria a conta parecer menor do que foi.
    tempo_parado_min: float | None = None
    #: Soma das perdas. Mesma regra: só quando TODA linha tem o número.
    perda_kwh: float | None = None
    em_aberto: int = 0
    paradas: list[ParadaOut] = []
    #: `paradas` (breakdowns/range) | `alertas` (alerts?status=all) | `None` (nada respondeu).
    fonte: str | None = None
    aviso: str | None = None


# ── a memória da fonte primária ─────────────────────────────────────────────

#: Segundos durante os quais a primária não é tentada de novo depois de falhar.
INDISPONIVEL_POR_SEG = 3600.0

#: Teto de espera da fonte primária. Ela TEM substituta, então esperar os 30 s do cliente
#: não compra nada: o `breakdowns/range` leva de 16 a 23 s para admitir o 500 (medido nas
#: 7 usinas do escopo), e a Visão geral pede paradas das sete de uma vez.
ESPERA_DA_PRIMARIA_SEG = 6.0

#: Instante (`time.monotonic`) até o qual a primária é considerada fora. Um valor só, e
#: não um por usina: o defeito está na consulta do mw-api, não no dado de uma usina.
_primaria_fora_ate: float | None = None

#: Enquanto a primária não provar que responde, só UMA tentativa por vez. Sem isto as sete
#: usinas da Visão geral saem juntas e as sete pagam a mesma descoberta; com isto a
#: primeira paga (no máximo `ESPERA_DA_PRIMARIA_SEG`) e as demais já leem o circuito
#: aberto. Depois do primeiro sucesso o portão sai do caminho — serializar uma fonte
#: saudável seria trocar um defeito por outro.
_portao_primaria = asyncio.Lock()
_primaria_confirmada = False


def _primaria_disponivel() -> bool:
    return _primaria_fora_ate is None or time.monotonic() >= _primaria_fora_ate


def _marcar_primaria_fora() -> None:
    global _primaria_fora_ate
    _primaria_fora_ate = time.monotonic() + INDISPONIVEL_POR_SEG


def _marcar_primaria_boa() -> None:
    global _primaria_confirmada
    _primaria_confirmada = True


def esquecer_indisponibilidade() -> None:
    """Volta a tentar a primária na próxima chamada. Para testes e para quem operar."""
    global _primaria_fora_ate, _primaria_confirmada
    _primaria_fora_ate = None
    _primaria_confirmada = False


def _e_falha_da_fonte(exc: BaseException) -> bool:
    """5xx e tempo esgotado são a fonte fora; um 4xx é um pedido que ela recusou (usina
    inexistente, período inválido) e não justifica parar de perguntar por uma hora."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


# ── tradução ────────────────────────────────────────────────────────────────


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return float(valor)


def _instante(valor: Any) -> datetime | None:
    """ISO 8601 → datetime no fuso da usina. Sem fuso no texto, assume UTC — é como o
    mw-api grava `stopped_at` (timestamptz) e serializa sem o sufixo."""
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


#: Os `kind` de `AlertDetail` que são parada de verdade (`mw-api/src/alerts/schemas.py`:
#: `kind: str = "stop"`, e o detector só grava `stop` ou `degradation`). O campo é texto
#: livre no schema: se um dia o meuWatt passar a listar outro tipo de evento no mesmo
#: endpoint (comunicação, estação), ele NÃO pode virar "parada" na tela do dono — por
#: isso a lista é fechada aqui e o desconhecido fica de fora, em vez de cair num padrão.
KINDS_DE_PARADA = {"stop": "parada", "degradation": "degradacao"}


def _tipo(valor: Any) -> str | None:
    """`stop`/`degradation` → tipo do portal; ausente conta como `stop` (é o padrão do
    schema); qualquer outro valor é "não é parada" e a linha é descartada."""
    if valor in (None, ""):
        return "parada"
    return KINDS_DE_PARADA.get(str(valor))


def _de_breakdown(linha: dict[str, Any]) -> ParadaOut | None:
    """`BreakdownRangeRow` → `ParadaOut`.

    A linha desta rota NÃO traz `kind` (só `type`, que é inversor/planta — outro eixo).
    Tudo o que sai de `/breakdowns` é parada por definição da tabela; `degradation` só
    aparece se o produto de origem passar a publicar o `kind` também aqui.
    """
    inicio = _instante(linha.get("stopped_at"))
    if inicio is None or not isinstance(linha.get("id"), int):
        return None
    fim = _instante(linha.get("resolved_at"))
    em_aberto = linha.get("solved") is False or (fim is None and linha.get("solved") is None)
    return ParadaOut(
        id=linha["id"],
        inicio=inicio.isoformat(),
        fim=_iso(fim),
        duracao_min=_numero(linha.get("off_time_minutes")),
        perda_kwh=_numero(linha.get("loss_kwh")),
        tipo=_tipo(linha.get("kind")) or "parada",
        equipamento=linha.get("slot_label") or linha.get("sn"),
        em_aberto=em_aberto,
        tom="parado" if em_aberto else "ok",
    )


def _de_alerta(alerta: dict[str, Any]) -> ParadaOut | None:
    """`AlertDetail` → `ParadaOut`. `duration_minutes` vem nulo quando o mw-api não tem
    janela solar para calcular — fica nulo aqui também. Alerta de `kind` fora de
    `KINDS_DE_PARADA` não vira linha: a reserva lista TODOS os alertas da usina, e só
    parada e degradação são paradas."""
    inicio = _instante(alerta.get("started_at"))
    if inicio is None or not isinstance(alerta.get("id"), int):
        return None
    tipo = _tipo(alerta.get("kind"))
    if tipo is None:
        return None
    fim = _instante(alerta.get("resolved_at"))
    em_aberto = bool(alerta.get("is_active")) if "is_active" in alerta else fim is None
    return ParadaOut(
        id=alerta["id"],
        inicio=inicio.isoformat(),
        fim=_iso(fim),
        duracao_min=_numero(alerta.get("duration_minutes")),
        perda_kwh=_numero(alerta.get("estimated_loss_kwh")),
        tipo=tipo,
        equipamento=alerta.get("slot_label") or alerta.get("sn"),
        em_aberto=em_aberto,
        tom="parado" if em_aberto else "ok",
    )


def _no_periodo(parada: ParadaOut, inicio: date, fim: date) -> bool:
    """Pelo DIA de início, no fuso da usina — o mesmo critério do `breakdowns/range`
    (`stopped_at::date BETWEEN`), para as duas fontes recortarem igual."""
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


# ── as fontes ───────────────────────────────────────────────────────────────


async def _pela_primaria(cliente, slug: str, inicio: date, fim: date) -> list[ParadaOut]:
    resposta = await cliente.paradas(slug, inicio, fim, timeout=ESPERA_DA_PRIMARIA_SEG)
    linhas = resposta.get("breakdowns") if isinstance(resposta, dict) else resposta
    if not isinstance(linhas, list):
        raise ValueError("breakdowns/range respondeu sem a lista de paradas")
    # O upstream JÁ recortou por `stopped_at::date` — e no fuso do banco dele, que não
    # se sabe se é o da usina. Recortar de novo aqui, pelo dia em BRT, deixaria cair a
    # parada da virada do mês (01/09 01:00 UTC = 31/08 22:00 na usina) nos DOIS meses:
    # o de agosto não a recebe do upstream e o de setembro a descartaria. O que a fonte
    # primária diz que é do período, é do período.
    return [p for p in (_de_breakdown(l) for l in linhas if isinstance(l, dict)) if p]


async def _pela_reserva(cliente, slug: str, inicio: date, fim: date) -> list[ParadaOut]:
    alertas = await cliente.alertas_todos(slug, status="all")
    # `_de_alerta` já descarta o que não é `stop`/`degradation`; aqui só o período.
    paradas = [p for p in (_de_alerta(a) for a in alertas if isinstance(a, dict)) if p]
    return [p for p in paradas if _no_periodo(p, inicio, fim)]


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

    Nunca é 5xx por causa do upstream: as duas fontes fora do ar dão `total=None` com o
    aviso, e a tela mostra "sem dados" — não "nenhuma parada", que seria mentir para o
    lado bom.
    """
    if recorte not in ("mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'mes' ou 'ano'.")

    link: PlantLink = _usina_no_escopo(db, usuario, plant_link_id)
    inicio, fim = _janela(recorte, _referencia_pedida(referencia))
    saida = ParadasOut(recorte=recorte, inicio=inicio.isoformat(), fim=fim.isoformat())

    if not link.mw_plant_slug:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Esta usina não está ligada ao monitoramento."
        )

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Monitoramento indisponível: {exc}"
        return saida

    slug = link.mw_plant_slug
    motivo_primaria: str | None = None

    if _primaria_disponivel():
        # O portão só existe enquanto a primária não se provou. Quem chega junto espera a
        # decisão de quem entrou (segundos, não a espera cheia) e depois relê o circuito:
        # se o primeiro descobriu o 500, este nem tenta.
        portao = _portao_primaria if not _primaria_confirmada else None
        if portao is not None:
            await portao.acquire()
        try:
            if _primaria_disponivel():
                paradas = await _pela_primaria(cliente, slug, inicio, fim)
                _marcar_primaria_boa()
                return _consolidar(saida, paradas, "paradas")
        except Exception as exc:  # noqa: BLE001
            if _e_falha_da_fonte(exc):
                _marcar_primaria_fora()
            motivo_primaria = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            if portao is not None:
                portao.release()

    try:
        _consolidar(saida, await _pela_reserva(cliente, slug, inicio, fim), "alertas")
    except Exception as exc:  # noqa: BLE001
        partes = ["O monitoramento não respondeu as paradas deste período."]
        if motivo_primaria:
            partes.append(f"paradas: {motivo_primaria}")
        partes.append(f"alertas: {type(exc).__name__}: {exc}"[:200])
        saida.aviso = " · ".join(partes)
        return saida

    # A reserva lista os eventos, mas a perda é ESTIMADA pelo produto de origem (pares
    # saudáveis ou POA × PR) e a duração depende da janela solar. Dizer isso é o que
    # separa "número do relatório" de "número de acompanhamento".
    saida.aviso = (
        "Lido do histórico de alertas: a energia perdida é estimada pelo monitoramento."
    )
    return saida
