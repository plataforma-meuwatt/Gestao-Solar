"""Relatório de manutenção do período — o que o dono da usina leva para a diretoria.

O dono (texto de origem do portal): *"o relatório de manutenção do meuPlano (que vamos
criar)"*. Não existia em lado nenhum: o meuPlano tinha PDF de OS, de tarefa, de cronograma
e de comissionamento — nada que respondesse, num documento só, **"neste período, o contrato
foi cumprido?"**. O agregado nasceu lá (`visao-cliente/…/relatorio-manutencao`, lido do
próprio ATIVO), e este router é a porta dele para o portal.

Quatro decisões que moldam este arquivo:

**Nada é recalculado.** As contagens do cronograma (previstas, executadas, dispensadas,
atrasadas) vêm de `asset_compliance` do meuPlano — do histórico do ativo, não de contar
tarefas. Somar aqui produziria uma segunda verdade sobre a mesma pergunta, e o dono veria
números diferentes na tela e no PDF sem saber em qual acreditar. `pct_cumprido` nulo
continua nulo: "nada previsto" não é "0 % cumprido".

**Só o vocabulário que já existe.** Situação de OS, de tarefa e parecer saem dos mesmos
mapas de `manutencao.py` (`SITUACAO`, `SITUACAO_TAREFA`, `PARECER`); criticidade vira um
dos seis tons. Uma OS `APROVADA` é "Concluída" aqui como é na aba Ordens — dois rótulos para
o mesmo estado seriam duas telas discordando.

**O contrato é o MESMO da aba Cronograma.** `contrato_id` passa por `_resolver_contrato`
(a régua do cronograma): informado, tem de ser desta usina — 404 antes de qualquer ida ao
agregado; ausente, vale o contrato com cronograma consolidado mais recente, vigente primeiro.
O meuPlano também sabe escolher sozinho, mas por outra ordem (a consolidação mais recente,
vigente ou não) — e o cliente que troca de aba não pode ver o relatório de um contrato e o
cronograma de outro sem ter escolhido nada.

**O período é conferido ANTES de ir ao upstream.** `de > ate`, mês futuro ou mais de 24
meses respondem 400 na hora, com a frase — sem gastar uma ida de segundos ao meuPlano para
receber um 422 achatado em 502.

Sem nível de equipamento, de propósito: análise de equipamento é trabalho da Splendor; o
cliente corporativo quer saber se a manutenção anda, e o PDF da tarefa fica linkado para
quem quiser descer.
"""

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.manutencao import (
    NAO_PUBLICADO,
    ContratoOut,
    OrdemOut,
    _data,
    _erro_do_upstream,
    _categoria_da_linha,
    _inteiro,
    _link_do_escopo,
    _ordem_out,
    _pdf,
    _resolver_contrato,
    _tarefa_out,
    _texto,
)
from app.api.v1.pendencias import _data as _data_pura
from app.api.v1.pendencias import _situacao_da_pendencia
from app.api.v1.plants import _instante_medida
from app.core.datas import agora as agora_na_usina
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · manutenção"])


# ══════════════════════════════════════════════════════════════════════════════
# Saída
# ══════════════════════════════════════════════════════════════════════════════


class PeriodoOut(BaseModel):
    #: Competências "YYYY-MM", inclusivas.
    de: str
    ate: str


class LinhaCronogramaRelatorioOut(BaseModel):
    """Uma atividade do contrato, contada só nos meses do período.

    As cinco contagens somam `previstas`: executadas + dispensadas + atrasadas + no_prazo +
    sem_ativo. É assim que o meuPlano fecha o total, e é assim que a tela confere.
    """

    plan_item_id: int | None = None
    nome: str
    #: 'ensaio' | 'servico' | 'checklist' — o selo da linha, como no cronograma.
    categoria: str | None = None
    previstas: int = 0
    executadas: int = 0
    dispensadas: int = 0
    atrasadas: int = 0
    #: Previsto e ainda no prazo (azul/laranja no meuPlano) — não é atraso.
    no_prazo: int = 0
    #: Previsto sem equipamento para executar (X num item que não cobre ativo nenhum). O
    #: meuPlano não o esconde, e este lado também não: sem ele o total não fecharia.
    sem_ativo: int = 0


class DispensaOut(BaseModel):
    """Uma ocorrência dispensada COM motivo — 'feito' e 'dispensado' nunca se fundem."""

    atividade: str
    mes: str
    motivo: str | None = None


class CronogramaRelatorioOut(BaseModel):
    status: str | None = None
    versao: int | None = None
    consolidado_em: datetime | None = None
    previstas: int = 0
    executadas: int = 0
    dispensadas: int = 0
    atrasadas: int = 0
    no_prazo: int = 0
    sem_ativo: int = 0
    #: (executadas + dispensadas) / previstas, calculado no meuPlano. NULO quando nada
    #: estava previsto — e fica nulo: a tela mostra "—", nunca "0 %".
    pct_cumprido: float | None = None
    #: A frase que reconcilia este bloco com a aba Cronograma. As duas telas respondiam
    #: "está sendo feito?" com números diferentes — "13 de 270" lá, "cumprido 41,9%" sobre
    #: 31 previstas aqui — porque o relatório conta só os meses do período em que o
    #: contrato existe, e o período pedido começava 9 meses ANTES da vigência. Os dois
    #: números estavam certos; ninguém dizia o recorte. Nula quando período ⊆ contrato.
    recorte: str | None = None
    #: Σ de X do contrato inteiro (12 meses) — o denominador da aba Cronograma, para quem
    #: quiser conferir a conta sem trocar de tela.
    previstas_no_contrato: int | None = None
    linhas: list[LinhaCronogramaRelatorioOut] = []
    dispensas: list[DispensaOut] = []


class PareceresOut(BaseModel):
    """Contagem dos pareceres das fichas executadas no período."""

    aprovados: int = 0
    com_ressalva: int = 0
    reprovados: int = 0
    sem_parecer: int = 0
    #: De quantas ordens ENCERRADAS sai a contagem, e quantas em curso ficaram de fora.
    #: Sem isto o relatório se contradizia numa página só: a OS em curso mostrava
    #: "Aprovado com ressalva" e o agregado dizia "com ressalva 0". Os dois números
    #: estavam certos; faltava dizer o recorte. A frase pronta é o `recorte`, para tela e
    #: PDF lerem a mesma coisa.
    ordens_consideradas: int = 0
    ordens_em_curso_fora: int = 0
    recorte: str | None = None


#: Criticidade do meuPlano (`nulo|baixo|alto|urgente`, vocabulário do modelo) → tom e
#: rótulo. É SEMPRE uma chave de `tons` do portal — nome fora da lista não pinta cor
#: errada: não pinta cor nenhuma.
CRITICIDADE: dict[str, tuple[str, str]] = {
    "urgente": ("Urgente", "parado"),
    "alto": ("Alto", "multiplos"),
    "baixo": ("Baixo", "alerta"),
    "nulo": ("Sem criticidade", "semDados"),
}
#: A ordem em que a tela lista — do mais grave para o menos.
ORDEM_CRITICIDADE = ("urgente", "alto", "baixo", "nulo")


class CriticidadeOut(BaseModel):
    criticidade: str
    rotulo: str
    total: int = 0
    tom: str = "semDados"


class ProblemasPorOsOut(BaseModel):
    """Os problemas que as fichas de UMA OS acharam — em número, sem equipamento."""

    os_id: int | None = None
    objetivo: str
    total: int = 0
    urgentes: int = 0
    tom: str = "semDados"


class ProblemasOut(BaseModel):
    total: int = 0
    por_criticidade: list[CriticidadeOut] = []
    por_os: list[ProblemasPorOsOut] = []
    #: Mesmo recorte dos pareceres (ver `PareceresOut`).
    ordens_consideradas: int = 0
    ordens_em_curso_fora: int = 0
    recorte: str | None = None


class PendenciaResumoOut(BaseModel):
    """Uma pendência compartilhada, como aparece no relatório: nº, título, situação, prazo."""

    id: int | None = None
    numero: int | None = None
    titulo: str
    status: str | None = None
    situacao: str = "—"
    tom: str = "semDados"
    #: A que o CLIENTE marcou como cobrada — o mesmo `extra.cobrada_pelo_cliente` da aba de
    #: Pendências; o relatório a destaca pela mesma razão que a aba a lista primeiro.
    cobrada_pelo_cliente: bool = False
    prazo: date | None = None
    #: Aproximada: o meuPlano não carimba a conclusão da pendência e usa a última
    #: alteração dela (`concluida_em_aprox`). A tela diz "por volta de".
    concluida_em: date | None = None


class PendenciasRelatorioOut(BaseModel):
    #: Abertas no FIM do período (o que ainda cobra alguém).
    abertas: list[PendenciaResumoOut] = []
    #: Concluídas DENTRO do período.
    concluidas: list[PendenciaResumoOut] = []


class RelatorioOut(BaseModel):
    usina: str
    #: `id` do vínculo neste sistema — é por ele que o portal navega.
    usina_id: int
    #: A organização dona da usina e a que executa o O&M — como o meuPlano as cadastrou.
    #: Nulos quando o vínculo não está declarado lá; a tela não inventa.
    cliente: str | None = None
    executora: str | None = None
    #: O contrato que rege o relatório — no MESMO formato do seletor de contratos.
    contrato: ContratoOut | None = None
    periodo: PeriodoOut
    #: Nulo = o contrato não tem cronograma consolidado, ou a usina não tem contrato — o
    #: motivo vai em `aviso`, com a frase que a tela mostra no lugar do bloco.
    cronograma: CronogramaRelatorioOut | None = None
    #: OSs encerradas (FECHADA | APROVADA) no período, com as tarefas dentro.
    ordens: list[OrdemOut] = []
    #: OSs ainda em curso hoje — contexto, não conformidade.
    em_curso: list[OrdemOut] = []
    pareceres: PareceresOut = PareceresOut()
    problemas: ProblemasOut = ProblemasOut()
    pendencias: PendenciasRelatorioOut = PendenciasRelatorioOut()
    #: Quantas fotos as fichas do período carregam. Nulo = o meuPlano não contou.
    fotos: int | None = None
    gerado_em: datetime
    aviso: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Período
# ══════════════════════════════════════════════════════════════════════════════

#: Teto de competências num relatório só. Acima disso o agregado no meuPlano deixa de
#: caber numa ida (e num PDF que alguém leia).
MESES_MAX = 24
#: Sem `de`/`ate`, o relatório é dos últimos 12 meses — o que se leva a uma reunião anual.
MESES_PADRAO = 12


def _competencia(valor: str, nome: str) -> tuple[int, int]:
    """`(ano, mês)` de um "YYYY-MM". 400 com a frase quando não é isso."""
    try:
        ano, mes = valor.split("-")
        a, m = int(ano), int(mes)
        if not (1 <= m <= 12) or len(ano) != 4:
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(400, f"{nome} deve estar no formato YYYY-MM.") from None
    return a, m


def _indice(am: tuple[int, int]) -> int:
    return am[0] * 12 + (am[1] - 1)


def _rotulo(indice: int) -> str:
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def periodo_pedido(de: str | None, ate: str | None) -> tuple[str, str]:
    """As competências do relatório, validadas ANTES de qualquer ida ao upstream.

    Padrão = últimos `MESES_PADRAO` meses terminando no mês corrente na usina (fuso das
    usinas, não do servidor — ver `app/core/datas`). Recusa `de > ate`, mês futuro e mais
    de `MESES_MAX` meses; cada recusa diz o que foi, porque o 422 do meuPlano chegaria
    aqui achatado num 502 sem frase útil.
    """
    hoje = hoje_na_usina()
    atual = _indice((hoje.year, hoje.month))

    fim = _indice(_competencia(ate, "ate")) if ate else atual
    inicio = _indice(_competencia(de, "de")) if de else fim - (MESES_PADRAO - 1)

    if fim > atual:
        raise HTTPException(400, "ate não pode ser um mês futuro.")
    if inicio > fim:
        raise HTTPException(400, "de não pode ser depois de ate.")
    if fim - inicio + 1 > MESES_MAX:
        raise HTTPException(400, f"O relatório cobre no máximo {MESES_MAX} meses.")
    return _rotulo(inicio), _rotulo(fim)


# ══════════════════════════════════════════════════════════════════════════════
# Tradução do agregado do meuPlano
# ══════════════════════════════════════════════════════════════════════════════
#
# O contrato do upstream (`services/maintenance/relatorio_manutencao.montar`) é lido com
# tolerância a nome: `_pega(d, "executadas", "feito")` aceita o primeiro que existir. É
# deliberado — o agregador nasceu junto com este router, em repositórios diferentes, e
# um campo renomeado lá não pode apagar uma seção inteira aqui sem aviso. O que NÃO é
# tolerado é inventar: chave ausente vira nulo/zero de contagem, nunca um número
# derivado de outro.
#
# A forma real, conferida em `relatorio_manutencao.montar` (04/09/2026): `cabecalho`
# (usina, cliente, executora, contrato, periodo, gerado_em); `cronograma` (previsto/feito/
# dispensado/atrasado/no_prazo/sem_ativo, pct_cumprido, linhas) ou nulo com
# `cronograma_motivo` = sem_contrato | sem_cronograma_consolidado; `dispensas` NO TOPO, não
# dentro do cronograma; `ordens`/`em_curso` com `tarefas`; `pareceres`; `problemas`
# (por_criticidade como dict, por_os); `pendencias` (abertas/concluidas, com
# `concluida_em_aprox` e `cobrada_pelo_cliente`); `fotos_total`.


def _pega(d: Any, *chaves: str) -> Any:
    if not isinstance(d, dict):
        return None
    for k in chaves:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _contagem(d: Any, *chaves: str) -> int:
    return _inteiro(_pega(d, *chaves)) or 0


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _bool(valor: Any) -> bool | None:
    return valor if isinstance(valor, bool) else None


def _contrato(cabecalho: Any) -> ContratoOut | None:
    """O contrato como o cabeçalho do agregado o descreve. Sem id não há contrato."""
    c = _pega(cabecalho, "contrato")
    if not isinstance(c, dict):
        return None
    ident = _inteiro(c.get("id"))
    if ident is None:
        return None
    return ContratoOut(
        id=ident,
        numero=_inteiro(c.get("numero")),
        titulo=_texto(_pega(c, "titulo", "title")),
        inicio=_data(_pega(c, "inicio", "start_date", "vigencia_inicio")),
        fim=_data(_pega(c, "fim", "end_date", "vigencia_fim")),
        vigente=_bool(c.get("vigente")),
        versao_cronograma=_inteiro(_pega(c, "versao_cronograma", "versao_consolidada")),
    )


#: `cronograma_motivo` do meuPlano → a frase que a tela mostra no lugar do bloco. A de
#: "não publicado" é a MESMA da aba Cronograma (`NAO_PUBLICADO`): o cliente que troca de
#: aba lê a mesma explicação para o mesmo estado.
MOTIVO_SEM_CRONOGRAMA: dict[str, str] = {
    "sem_contrato": "Esta usina não tem contrato de manutenção cadastrado.",
    "sem_cronograma_consolidado": NAO_PUBLICADO,
}


#: Meses em português para a frase do recorte — os mesmos rótulos curtos do resto do BFF.
_MES_CURTO = ("jan", "fev", "mar", "abr", "mai", "jun",
              "jul", "ago", "set", "out", "nov", "dez")


def _mes_por_extenso(ym: Any) -> str | None:
    """'2026-07' → 'jul/2026'. Competência malformada não vira frase (some da explicação)."""
    if not isinstance(ym, str) or len(ym) < 7:
        return None
    try:
        ano, mes = int(ym[:4]), int(ym[5:7])
    except ValueError:
        return None
    if not 1 <= mes <= 12:
        return None
    return f"{_MES_CURTO[mes - 1]}/{ano}"


def _recorte_do_cronograma(dentro: Any, fora: Any, no_contrato: int | None) -> str | None:
    """A frase que diz de QUAIS meses saiu a porcentagem — e por que ela difere da aba
    Cronograma.

    Sem ela, o cliente lia "cumprido 41,9%" sob o rótulo "Outubro de 2025 a Setembro de
    2026" e "13 de 270 previstas" na outra aba, sem nada explicando que o contrato só
    existe em 2 dos 12 meses pedidos. Quando o período inteiro cabe no contrato não há o
    que reconciliar, e a frase não aparece — aviso que sempre aparece ninguém lê.
    """
    dentro_lista = [m for m in (dentro or []) if isinstance(m, str)]
    fora_lista = [m for m in (fora or []) if isinstance(m, str)]
    if not fora_lista:
        return None
    if not dentro_lista:
        return (
            "Nenhum mês do período pedido está dentro da vigência deste contrato — "
            "escolha um período que cubra a vigência para ver o cumprimento."
        )
    inicio = _mes_por_extenso(dentro_lista[0])
    fim = _mes_por_extenso(dentro_lista[-1])
    janela = f"{inicio} a {fim}" if inicio and fim and inicio != fim else (inicio or fim or "")
    frase = (
        f"Contagem feita só sobre os {len(dentro_lista)} "
        f"{'mês' if len(dentro_lista) == 1 else 'meses'} do período em que este contrato "
        f"está vigente ({janela}); os outros {len(fora_lista)} ficaram de fora."
    )
    if no_contrato:
        frase += f" O contrato inteiro prevê {no_contrato} atividades no ano."
    return frase


def _cronograma(bruto: Any, dispensas_brutas: Any) -> CronogramaRelatorioOut | None:
    """O bloco do cronograma. `dispensas_brutas` vem à parte porque o meuPlano as põe no
    topo do agregado, não dentro do bloco — lidas de dentro, a seção sairia sempre vazia."""
    if not isinstance(bruto, dict):
        return None
    linhas: list[LinhaCronogramaRelatorioOut] = []
    for r in bruto.get("linhas") or []:
        if not isinstance(r, dict):
            continue
        linhas.append(
            LinhaCronogramaRelatorioOut(
                plan_item_id=_inteiro(r.get("plan_item_id")),
                nome=_texto(_pega(r, "nome", "name", "conjunto_nome")) or "Atividade",
                # Mesmo tradutor da aba Cronograma (fonte única): sem ele o relatório
                # que vai à diretoria estampava 'INSPECAO' e 'ensaio' ao lado de
                # 'Inspeção' e 'Ensaio' na outra tela do mesmo portal.
                categoria=_categoria_da_linha(
                    {"screen_categoria": _pega(r, "categoria", "screen_categoria"),
                     "checklist_natureza": r.get("checklist_natureza")}
                )[0],
                previstas=_contagem(r, "previstas", "previsto"),
                executadas=_contagem(r, "executadas", "feito", "feitas"),
                dispensadas=_contagem(r, "dispensadas", "dispensado"),
                atrasadas=_contagem(r, "atrasadas", "atrasado"),
                no_prazo=_contagem(r, "no_prazo"),
                sem_ativo=_contagem(r, "sem_ativo"),
            )
        )
    # Aceita também dispensas dentro do bloco, para o dia em que o agregado as mover.
    fonte_dispensas = dispensas_brutas if isinstance(dispensas_brutas, list) else bruto.get("dispensas")
    dispensas = [
        DispensaOut(
            atividade=_texto(_pega(d, "atividade", "nome")) or "Atividade",
            mes=_texto(_pega(d, "mes", "month")) or "",
            motivo=_texto(d.get("motivo")),
        )
        for d in (fonte_dispensas or [])
        if isinstance(d, dict)
    ]
    totais = bruto.get("totais") if isinstance(bruto.get("totais"), dict) else bruto
    consolidado_em = _instante_medida(_pega(bruto, "consolidado_em", "consolidated_at"))
    no_contrato = _inteiro(_pega(bruto, "previsto_no_contrato"))
    return CronogramaRelatorioOut(
        # O agregado só traz o bloco quando há versão CONSOLIDADA — o carimbo de
        # consolidação é a prova; sem ele, o status fica o que o upstream disser (ou nulo).
        status=_texto(bruto.get("status")) or ("CONSOLIDATED" if consolidado_em else None),
        versao=_inteiro(_pega(bruto, "versao", "version")),
        consolidado_em=consolidado_em,
        previstas=_contagem(totais, "previstas", "previsto"),
        executadas=_contagem(totais, "executadas", "feito", "feitas"),
        dispensadas=_contagem(totais, "dispensadas", "dispensado"),
        atrasadas=_contagem(totais, "atrasadas", "atrasado"),
        no_prazo=_contagem(totais, "no_prazo"),
        sem_ativo=_contagem(totais, "sem_ativo"),
        # Repassado, não recalculado — e nulo fica nulo (ver o cabeçalho do módulo).
        pct_cumprido=_numero(_pega(totais, "pct_cumprido")),
        recorte=_recorte_do_cronograma(
            bruto.get("meses_do_cronograma"),
            bruto.get("meses_fora_do_cronograma"),
            no_contrato,
        ),
        previstas_no_contrato=no_contrato,
        linhas=linhas,
        dispensas=dispensas,
    )


def _ordem_com_tarefas(o: dict[str, Any], link: PlantLink) -> OrdemOut:
    """A OS no MESMO formato da aba Ordens, com as tarefas que o agregado já trouxe.

    `itens=None` quando o meuPlano não mandou a lista (não deu para buscar) ≠ `[]`
    (OS sem tarefa) — a diferença é a mesma de `detalhar_ordem`.
    """
    saida = _ordem_out(o, link)
    tarefas = _pega(o, "tarefas", "tasks", "itens")
    if isinstance(tarefas, list):
        itens = [_tarefa_out(t) for t in tarefas if isinstance(t, dict)]
        itens.sort(key=lambda t: (t.grupo or "￿", t.nome))
        saida.itens = itens
    return saida


def _ordens(lista: Any, link: PlantLink) -> list[OrdemOut]:
    if not isinstance(lista, list):
        return []
    return [_ordem_com_tarefas(o, link) for o in lista if isinstance(o, dict) and o.get("id")]


def _ordens_no_plural(n: int) -> str:
    return "1 ordem" if n == 1 else f"{n} ordens"


def _recorte(bruto: Any) -> tuple[int, int, str | None]:
    """`(consideradas, em curso de fora, frase)` — de onde sai um agregado do período.

    A frase é montada aqui, e não na tela, porque tela e PDF precisam dizer a MESMA coisa:
    o agregado conta as fichas das ordens ENCERRADAS, e a ordem que ainda está em execução
    aparece na lista acima sem entrar na conta. Enquanto isso ficava implícito, o relatório
    exibia "Aprovado com ressalva" e "com ressalva 0" na mesma página.
    """
    consideradas = _contagem(bruto, "ordens_consideradas")
    fora = _contagem(bruto, "ordens_em_curso_fora")
    if not consideradas and not fora:
        return 0, 0, None
    frase = f"Conta as fichas de {_ordens_no_plural(consideradas)} "
    frase += "encerrada" if consideradas == 1 else "encerradas"
    frase += " no período."
    if fora:
        frase += (
            f" {_ordens_no_plural(fora)} ainda em execução aparece acima e não entra nesta "
            "conta: enquanto a ordem não encerra, o parecer ainda pode mudar."
        )
    return consideradas, fora, frase


def _pareceres(bruto: Any) -> PareceresOut:
    consideradas, fora, frase = _recorte(bruto)
    return PareceresOut(
        aprovados=_contagem(bruto, "aprovados", "aprovado"),
        com_ressalva=_contagem(bruto, "com_ressalva", "ressalva"),
        reprovados=_contagem(bruto, "reprovados", "reprovado"),
        sem_parecer=_contagem(bruto, "sem_parecer", "sem"),
        ordens_consideradas=consideradas,
        ordens_em_curso_fora=fora,
        recorte=frase,
    )


def _tom_dos_problemas(total: int, urgentes: int) -> str:
    if urgentes > 0:
        return "parado"
    if total > 0:
        return "alerta"
    return "ok"


def _problemas(bruto: Any) -> ProblemasOut:
    """Os achados das fichas, agregados por criticidade e por OS.

    O equipamento NÃO sai daqui, mesmo que o upstream o mande: é o nível de análise que o
    dono disse não querer. Por criticidade a lista sai SEMPRE com as quatro faixas, na
    ordem do mais grave — a tela não precisa saber o vocabulário para montar a barra.
    """
    if not isinstance(bruto, dict):
        return ProblemasOut()
    por = bruto.get("por_criticidade")
    contagens: dict[str, int] = {}
    if isinstance(por, dict):
        contagens = {str(k).lower(): _inteiro(v) or 0 for k, v in por.items()}
    elif isinstance(por, list):
        for item in por:
            if isinstance(item, dict):
                chave = _texto(item.get("criticidade"))
                if chave:
                    contagens[chave.lower()] = _contagem(item, "total")
    faixas = [
        CriticidadeOut(criticidade=c, rotulo=CRITICIDADE[c][0],
                       total=contagens.get(c, 0), tom=CRITICIDADE[c][1])
        for c in ORDEM_CRITICIDADE
    ]
    por_os: list[ProblemasPorOsOut] = []
    for p in bruto.get("por_os") or []:
        if not isinstance(p, dict):
            continue
        total = _contagem(p, "total")
        urgentes = _contagem(p, "urgentes")
        por_os.append(
            ProblemasPorOsOut(
                os_id=_inteiro(p.get("os_id")),
                objetivo=(_texto(_pega(p, "objetivo", "name")) or f"OS {p.get('os_id')}"),
                total=total,
                urgentes=urgentes,
                tom=_tom_dos_problemas(total, urgentes),
            )
        )
    consideradas, fora, frase = _recorte(bruto)
    return ProblemasOut(
        total=_contagem(bruto, "total"),
        por_criticidade=faixas,
        por_os=por_os,
        ordens_consideradas=consideradas,
        ordens_em_curso_fora=fora,
        recorte=frase,
    )


def _pendencia(p: dict[str, Any], hoje: date) -> PendenciaResumoOut:
    """Uma pendência no MESMO vocabulário da tela de Pendências do portal.

    A régua (ABERTO → Aguardando/alerta, EM_ANDAMENTO → Em andamento/ok, CONCLUIDO →
    Concluída/semDados, prazo vencido e não concluída → parado) mora em `pendencias.py` e é
    importada, não recopiada: uma pendência "Prazo vencido" numa aba e "Aguardando" na outra
    é o tipo de divergência que destrói a confiança nas duas.
    """
    # O agregado nomeia o prazo como `prazo` (o container, como `end_date`); a régua lê
    # `end_date`, então o apelido é normalizado antes.
    normalizada = {**p, "end_date": _pega(p, "end_date", "prazo")}
    cru, frase, tom = _situacao_da_pendencia(normalizada, hoje)
    extra = p.get("extra") if isinstance(p.get("extra"), dict) else {}
    return PendenciaResumoOut(
        id=_inteiro(p.get("id")),
        numero=_inteiro(p.get("numero")),
        titulo=_texto(_pega(p, "titulo", "title")) or f"Pendência {p.get('numero') or p.get('id')}",
        status=cru,
        situacao=frase,
        tom=tom,
        cobrada_pelo_cliente=bool(_pega(p, "cobrada_pelo_cliente") or extra.get("cobrada_pelo_cliente")),
        prazo=_data_pura(normalizada.get("end_date")),
        concluida_em=_data_pura(
            _pega(p, "concluida_em", "concluida_em_aprox", "closed_at", "concluido_em")
        ),
    )


def _pendencias(bruto: Any, hoje: date) -> PendenciasRelatorioOut:
    if not isinstance(bruto, dict):
        return PendenciasRelatorioOut()

    def lista(*chaves: str) -> list[PendenciaResumoOut]:
        itens = _pega(bruto, *chaves)
        # As chaves `abertas_no_fim`/`concluidas_no_periodo` são CONTAGENS no agregado real;
        # só uma lista serve aqui — a contagem é o tamanho dela.
        return [_pendencia(p, hoje) for p in (itens if isinstance(itens, list) else []) if isinstance(p, dict)]

    return PendenciasRelatorioOut(
        abertas=lista("abertas", "abertas_no_fim"),
        concluidas=lista("concluidas", "concluidas_no_periodo"),
    )


def traduzir(
    bruto: dict[str, Any],
    link: PlantLink,
    periodo: tuple[str, str],
    contrato: ContratoOut | None = None,
) -> RelatorioOut:
    """O agregado do meuPlano no vocabulário do portal. Puro — sem rede, testável.

    `contrato` é o resolvido pela régua do cronograma (tem `vigente`/`versao_cronograma`,
    que o cabeçalho do agregado não traz); sem ele, vale o que o cabeçalho descreve.
    """
    hoje = hoje_na_usina()
    cabecalho = bruto.get("cabecalho") if isinstance(bruto.get("cabecalho"), dict) else bruto
    periodo_bruto = _pega(cabecalho, "periodo")
    de = _texto(_pega(periodo_bruto, "de")) or periodo[0]
    ate = _texto(_pega(periodo_bruto, "ate")) or periodo[1]
    cronograma = _cronograma(bruto.get("cronograma"), bruto.get("dispensas"))
    aviso = _texto(bruto.get("aviso"))
    if aviso is None and cronograma is None:
        motivo = _texto(bruto.get("cronograma_motivo"))
        aviso = MOTIVO_SEM_CRONOGRAMA.get(motivo or "", NAO_PUBLICADO)
    return RelatorioOut(
        usina=link.nome,
        usina_id=link.id,
        cliente=_texto(_pega(cabecalho, "cliente")),
        executora=_texto(_pega(cabecalho, "executora")),
        contrato=contrato or _contrato(cabecalho),
        periodo=PeriodoOut(de=de, ate=ate),
        cronograma=cronograma,
        ordens=_ordens(bruto.get("ordens"), link),
        em_curso=_ordens(bruto.get("em_curso"), link),
        pareceres=_pareceres(bruto.get("pareceres")),
        problemas=_problemas(bruto.get("problemas")),
        pendencias=_pendencias(bruto.get("pendencias"), hoje),
        fotos=_inteiro(_pega(bruto, "fotos_total", "fotos")),
        gerado_em=(
            _instante_medida(_pega(cabecalho, "gerado_em") or bruto.get("gerado_em"))
            or agora_na_usina()
        ),
        aviso=aviso,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Rotas
# ══════════════════════════════════════════════════════════════════════════════


async def _preparar(
    db: Session, usuario: User, usina_id: int, de: str | None, ate: str | None,
    contrato_id: int | None,
) -> tuple[PlantLink, tuple[str, str], Any, ContratoOut | None]:
    """Escopo, período, ponte e contrato — nesta ordem, e nada ao meuPlano antes dos dois
    primeiros.

    Usina alheia responde 404 (regra de `_link_do_escopo`: "proibido" confirmaria que ela
    existe); período inválido responde 400 com a frase. Só depois a ponte é aberta e o
    contrato é resolvido pela régua do cronograma: `contrato_id` de outra usina é 404 aqui,
    sem chegar ao agregado; ausente, é o consolidado mais recente. Usina SEM contrato não é
    erro — o relatório sai com as OSs e as pendências, e o cronograma explica por que falta.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    periodo = periodo_pedido(de, ate)
    try:
        cliente = await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Manutenção indisponível: {exc}") from exc
    try:
        contrato, _aviso = await _resolver_contrato(cliente, link, contrato_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para ler os contratos desta usina") from exc
    return link, periodo, cliente, contrato


@router.get("/manutencao/relatorio", response_model=RelatorioOut)
async def relatorio_de_manutencao(
    usina_id: int,
    de: str | None = None,
    ate: str | None = None,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> RelatorioOut:
    """O relatório de manutenção do período, para ler na tela.

    `contrato_id` é o id do contrato NO meuPlano (o mesmo que o seletor de contrato do
    cronograma usa) e segue a régua da aba Cronograma — ver o cabeçalho do módulo.
    """
    link, periodo, cliente, contrato = await _preparar(db, usuario, usina_id, de, ate, contrato_id)
    try:
        bruto = await cliente.vc_relatorio(
            link.mp_usina_id, periodo[0], periodo[1], contrato.id if contrato else None
        )
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para montar o relatório de manutenção") from exc
    if not isinstance(bruto, dict):
        raise HTTPException(502, "O relatório veio sem conteúdo. Tente de novo em instantes.")
    return traduzir(bruto, link, periodo, contrato)


@router.get("/manutencao/relatorio/pdf")
async def pdf_do_relatorio(
    usina_id: int,
    de: str | None = None,
    ate: str | None = None,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """O mesmo relatório em PDF — gerado do MESMO JSON no meuPlano, então tela = documento.

    Chega com a sessão no cabeçalho, como todo arquivo deste BFF: o portal baixa por
    `fetch` + Bearer e abre o blob — token nunca vai em URL.
    """
    link, periodo, cliente, contrato = await _preparar(db, usuario, usina_id, de, ate, contrato_id)
    try:
        conteudo = await cliente.vc_relatorio_pdf(
            link.mp_usina_id, periodo[0], periodo[1], contrato.id if contrato else None
        )
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para gerar o relatório de manutenção em PDF") from exc
    if not conteudo:
        raise HTTPException(502, "O PDF veio vazio. Tente de novo em instantes.")
    nome = f"Relatorio-manutencao-{link.nome}-{periodo[0]}-{periodo[1]}.pdf"
    return _pdf(conteudo, nome)
