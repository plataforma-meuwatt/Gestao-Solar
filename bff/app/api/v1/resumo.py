"""A Visão geral do portal do cliente — a carteira inteira, numa chamada.

É a primeira tela que o cliente corporativo vê, e ela responde cinco perguntas de uma vez:
gerei o esperado este mês? tem algo parado? a manutenção anda? e o que eu cobrei, anda?
No navegador isso seriam seis chamadas por usina e cinco spinners que chegam fora de
ordem; aqui o BFF monta tudo e o portal desenha UM skeleton.

Duas decisões sustentam o módulo:

**Composição INTERNA, nunca reconsulta.** Cada bloco é a função do router que já responde
aquela pergunta na tela dela — `listar_usinas`, `desempenho_da_usina`, `paradas_da_usina`,
`listar_ordens`, `cronograma_da_usina`, `listar_pendencias`. O número do topo tem de ser
exatamente o que a tela da usina mostra; calculado em dois lugares, os dois divergiriam
no dia em que alguém mudasse um deles, e a tela mais visível do portal passaria a se
contradizer. É o mesmo princípio de `home.inicio`.

**Cada bloco que falha vira nulo com aviso — e os totais somam só quem tem dado.** Uma
usina com o meuPlano fora do ar não pode aparecer com "0 OS em andamento" (que se lê como
"nada acontecendo"), nem derrubar a resposta das outras. Nulo é ausência; zero é medição.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.manutencao import (
    EM_CURSO,
    CronogramaOut,
    OrdensOut,
    cronograma_da_usina,
    listar_ordens,
)
from app.api.v1.paradas import paradas_da_usina
from app.api.v1.pendencias import listar_pendencias
from app.api.v1.plants import (
    UsinaOut,
    _referencia_pedida,
    _situacao_do_projeto,
    desempenho_da_usina,
    listar_usinas,
    usinas_do_usuario,
)
from app.core.datas import BRT
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["app · visão geral"])


# ── formato ─────────────────────────────────────────────────────────────────


class ManutencaoDaUsinaOut(BaseModel):
    """A manutenção de UMA usina até o mês de referência.

    Os quatro contadores do cronograma vêm nulos quando não há versão consolidada — que é
    diferente de "nada previsto". A tela escreve "cronograma não publicado", não "0".
    """

    #: Σ das ocorrências previstas nos meses do contrato até o mês de referência.
    previsto_ate_mes: int | None = None
    #: Células `verde` (executado) até o mês.
    feitos: int | None = None
    #: Células `verde_ressalva` — dispensa registrada com motivo. Nunca se soma a `feitos`
    #: sem dizer: apagar essa diferença era o risco que o meuPlano recusou correr.
    dispensados: int | None = None
    #: Células `vermelho` até o mês.
    atrasados: int | None = None
    #: OS ainda pedindo algo de alguém — a MESMA régua (`EM_CURSO`) da aba Ordens.
    os_em_andamento: int | None = None


class UsinaResumoOut(BaseModel):
    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    #: Situação operacional AGORA, pela régua de `plants._tom`. Um dos seis tons.
    tom: str
    situacao: str

    potencia_kw: float | None = None
    #: A potência instalada declarada (kWp). É o tamanho da usina, não a leitura de agora —
    #: entra para o cabeçalho da carteira poder dizer de quantos MWp ela é. Nulo quando nem o
    #: meuWatt nem o vínculo do painel declaram capacidade.
    capacidade_kwp: float | None = None
    energia_mes_kwh: float | None = None
    #: A meta do projeto (PVsyst cadastrado no meuWatt) para o mês. Sem cadastro, nulo —
    #: e a tela diz "sem meta", nunca 100%.
    esperado_mes_kwh: float | None = None
    pct: float | None = None

    paradas_mes: int | None = None
    #: Nulo também quando ALGUMA parada veio sem duração — somar só as que têm faria a
    #: conta parecer menor do que foi (regra de `paradas.ParadasOut`).
    tempo_parado_min: float | None = None

    manutencao: ManutencaoDaUsinaOut | None = None
    pendencias_abertas: int | None = None

    #: Por que algum bloco desta usina veio nulo. Só falha real entra aqui.
    aviso: str | None = None


class ManutencaoResumoOut(BaseModel):
    """Só existe quando ALGUMA usina respondeu; dentro dele, cada contador soma as usinas
    que trouxeram aquele dado e fica nulo quando nenhuma trouxe. Nulo ≠ zero."""

    os_em_andamento: int | None = None
    #: OS encerradas dentro do mês de referência (`closed_at`, com `approved_at` de recuo).
    os_concluidas_mes: int | None = None
    #: Nulo quando nenhuma usina tem cronograma consolidado — não é "zero atrasado".
    atrasados_total: int | None = None


class PendenciasResumoOut(BaseModel):
    abertas: int
    prazo_vencido: int | None = None
    #: Das abertas, as marcadas "Cobrada pelo cliente" no meuPlano — as que ELE abriu.
    cobradas_abertas: int | None = None


class AtencaoResumoOut(BaseModel):
    """O que está pedindo olho, em ordem de gravidade. A lista vazia é a boa notícia.

    **Uma faixa é uma ESPÉCIE de problema, não uma usina.** Antes cada usina gerava a sua
    faixa, e uma carteira de sete com a mesma queda de geração abria a Visão geral com sete
    tarjas idênticas — a primeira tela inteira dizendo a mesma coisa sete vezes. Sete alertas
    iguais é zero alerta: o olho aprende a pular o bloco, e a parada em aberto que estava no
    meio dele some junto.

    Agora as ocorrências da mesma `especie` viram UMA faixa, com a `contagem` e as usinas
    nomeadas no `detalhe`. A espécie que aparece numa usina só continua nomeando a usina no
    `titulo` — é o caso excepcional, e é o que merece faixa própria.

    O agrupamento é aqui, e não na tela, porque o que muda com ele é a FRASE: "4 pendências
    com prazo vencido" contra "Ouro Fino tem 2 pendências com prazo vencido". Frase que o
    cliente lê é dado da API — a tela que a montasse a partir de um código teria a sua
    própria gramática, e duas telas com gramáticas próprias discordam.
    """

    tom: str
    #: A frase do grupo. É o que a tela imprime em destaque, pronta.
    titulo: str
    detalhe: str | None = None
    #: Rota do portal para onde o clique leva. Numa faixa de várias usinas, a rota da lista.
    rota: str
    #: O que o botão de ação diz. Vem pronto pelo mesmo motivo do `titulo`.
    acao: str = "Abrir"
    #: Quantas ocorrências a faixa resume — o número do quadrado à esquerda.
    contagem: int = 1
    #: A chave estável da espécie. A tela NÃO a imprime; serve a teste e a depuração.
    especie: str = "outro"


class ResumoOut(BaseModel):
    referencia_mes: str
    atualizado_em: datetime

    potencia_agora_kw: float | None = None
    energia_mes_kwh: float | None = None
    esperado_mes_kwh: float | None = None
    #: Só das usinas que têm energia E meta — as sem meta ficam fora do numerador e do
    #: denominador, senão a carteira inteira pareceria abaixo do esperado.
    pct_do_esperado: float | None = None
    #: A régua de `plants._situacao_do_projeto`, aplicada ao conjunto.
    tom: str
    situacao: str

    usinas: list[UsinaResumoOut] = []
    #: Quantas usinas trouxeram energia do mês. É o "de N" dos totais.
    usinas_com_dado: int = 0

    manutencao: ManutencaoResumoOut | None = None
    pendencias: PendenciasResumoOut | None = None
    atencao: list[AtencaoResumoOut] = []

    aviso: str | None = None


# ── leitura ─────────────────────────────────────────────────────────────────


def _no_mes(instante: Any, referencia_mes: str) -> bool:
    """O instante cai no mês de referência — no fuso da usina, não no do servidor. Uma OS
    fechada às 22h do dia 31 em Brasília já é dia 1 em UTC, e mudaria de mês."""
    if isinstance(instante, datetime):
        if instante.tzinfo is not None:
            instante = instante.astimezone(BRT)
        return instante.strftime("%Y-%m") == referencia_mes
    if isinstance(instante, date):
        return instante.strftime("%Y-%m") == referencia_mes
    return False


# ── blocos por usina ────────────────────────────────────────────────────────
#
# Cada bloco devolve um dicionário com o que conseguiu, ou levanta — e quem levanta é
# apanhado em `_resumo_da_usina`, que transforma a exceção em "bloco nulo + aviso".
# `HTTPException` entra nesse saco de propósito: `_link_do_escopo` responde 404 para a
# usina sem meuPlano e `_usina_monitorada` para a usina sem meuWatt; para a Visão geral
# isso é só "esta usina não tem esse bloco", não um erro da resposta inteira.


async def _bloco_energia(
    link: PlantLink, referencia: date, db: Session, usuario: User
) -> dict[str, Any]:
    """Energia do mês × meta do projeto, da MESMA função que a tela da usina usa."""
    d = await desempenho_da_usina(
        link.id, recorte="mes", referencia=referencia.isoformat(), db=db, usuario=usuario
    )
    return {
        "energia": d.energia_kwh,
        "esperado": d.esperado_projeto_kwh,
        "pct": d.pct_do_projeto,
        # O aviso só interessa quando explica um vazio: sem energia, ou sem meta por
        # queda da fonte. "Sem meta cadastrada" é situação, não aviso — vai em `pct` nulo.
        "aviso": d.aviso if d.energia_kwh is None or d.esperado_projeto_kwh is None else None,
    }


async def _bloco_paradas(
    link: PlantLink, referencia: date, db: Session, usuario: User
) -> dict[str, Any]:
    p = await paradas_da_usina(
        link.id, recorte="mes", referencia=referencia.isoformat(), db=db, usuario=usuario
    )
    return {
        "total": p.total,
        "tempo_parado_min": p.tempo_parado_min,
        "em_aberto": p.em_aberto,
        "aviso": p.aviso if p.total is None else None,
    }


def _contar_ordens(ordens: OrdensOut, referencia_mes: str) -> tuple[int, int]:
    """`(em andamento, concluídas no mês)`.

    Em andamento é `EM_CURSO`, a régua da aba Ordens — a Visão geral não pode dizer "2"
    onde a aba diz "3". Concluída é o que já SAIU de `EM_CURSO` (aprovada pelo gestor) e
    foi encerrada dentro do mês, pela data de fechamento e, na falta dela, pela de
    aprovação. As duas contas não se sobrepõem: uma OS `FECHADA` aguardando verificação
    conta como em andamento, e só; contá-la também como concluída faria o cliente ver
    "1 em andamento · 1 concluída" com uma única OS na usina.
    """
    em_andamento = 0
    concluidas = 0
    for o in ordens.ordens:
        chave = (o.status or "").strip().upper()
        if chave in EM_CURSO:
            em_andamento += 1
        elif chave != "CANCELADA" and _no_mes(o.fechada_em or o.aprovada_em, referencia_mes):
            concluidas += 1
    return em_andamento, concluidas


def _contar_cronograma(cro: CronogramaOut, referencia_mes: str) -> dict[str, int] | None:
    """As quatro contagens do cronograma até o mês de referência, ou `None` sem versão.

    `status` nulo cobre os dois casos em que não há o que contar — o contrato não tem
    cronograma consolidado, ou o meuPlano não respondeu — e nos dois a resposta certa é
    "não sei", não "zero". Os meses são comparados como texto: `CronogramaOut.meses` são
    `YYYY-MM` na ordem do contrato, e a âncora pode não ser janeiro.
    """
    if cro.status is None:
        return None
    previsto = feitos = dispensados = atrasados = 0
    for linha in cro.linhas:
        for celula in linha.meses:
            if celula.mes > referencia_mes:
                continue
            previsto += celula.previsto
            feitos += int(celula.feito)
            dispensados += int(celula.dispensado)
            atrasados += int(celula.atrasado)
    return {
        "previsto_ate_mes": previsto,
        "feitos": feitos,
        "dispensados": dispensados,
        "atrasados": atrasados,
    }


async def _bloco_manutencao(
    link: PlantLink, referencia_mes: str, db: Session, usuario: User
) -> dict[str, Any]:
    """OS e cronograma da usina — duas idas ao meuPlano, em paralelo, cada uma falhando
    por conta própria. O cronograma sem versão não apaga a contagem de OS."""
    ordens, cro = await asyncio.gather(
        listar_ordens(usina_id=link.id, limite=300, db=db, usuario=usuario),
        cronograma_da_usina(usina_id=link.id, db=db, usuario=usuario),
    )
    avisos: list[str] = []
    saida: dict[str, Any] = {"os_em_andamento": None, "os_concluidas_mes": None}
    if ordens.total is not None:
        saida["os_em_andamento"], saida["os_concluidas_mes"] = _contar_ordens(ordens, referencia_mes)
    elif ordens.aviso:
        avisos.append(ordens.aviso)

    contagens = _contar_cronograma(cro, referencia_mes)
    if contagens is not None:
        saida.update(contagens)
    elif cro.aviso:
        avisos.append(cro.aviso)

    if saida["os_em_andamento"] is None and contagens is None:
        # Nada veio: o bloco inteiro é nulo, e o aviso diz por quê.
        raise RuntimeError(" · ".join(avisos) or "a manutenção não respondeu")
    saida["aviso"] = " · ".join(avisos) or None
    return saida


async def _bloco_pendencias(link: PlantLink, db: Session, usuario: User) -> dict[str, Any]:
    p = await listar_pendencias(usina_id=link.id, db=db, usuario=usuario)
    if p.abertas is None:
        return {"abertas": None, "prazo_vencido": None, "cobradas_abertas": None, "aviso": p.aviso}
    # "Cobrada" é a marca que a equipe põe na pendência que o CLIENTE abriu; aberta é o
    # que ainda não concluiu — a mesma leitura de `status` que `listar_pendencias` faz.
    cobradas = sum(
        1
        for i in p.pendencias
        if i.cobrada_pelo_cliente and (i.status or "").strip().upper() != "CONCLUIDO"
    )
    return {
        "abertas": p.abertas,
        "prazo_vencido": p.prazo_vencido,
        "cobradas_abertas": cobradas,
        "aviso": None,
    }


def _falha(resultado: Any) -> str | None:
    """A frase de uma exceção apanhada pelo `gather`, ou `None` quando o bloco respondeu."""
    if isinstance(resultado, HTTPException):
        return str(resultado.detail)
    if isinstance(resultado, BaseException):
        return str(resultado) or resultado.__class__.__name__
    return None


#: As ondas em que a Visão geral pode ser pedida. "energia" = geração + paradas (meuWatt,
#: rápido); "manutencao" = cronograma + ordens + pendências (meuPlano, cinco idas por
#: usina). Pedir tudo de uma vez é o padrão — e continua valendo para quem já chamava.
TODOS_OS_BLOCOS = frozenset({"energia", "manutencao"})


@dataclass
class _Recorte:
    """Uma usina montada, mais o que só serve aos totais e à faixa de atenção — números
    que não são campos da usina na tela e não têm por que virar campo do contrato."""

    usina: UsinaResumoOut
    os_concluidas_mes: int | None = None
    paradas_em_aberto: int | None = None
    pendencias: dict[str, Any] = field(default_factory=dict)


async def _nada() -> None:
    """O bloco que esta onda não pediu. Devolve `None`, que os montadores abaixo já leem
    como "sem dado" — diferente de exceção, que viraria aviso de falha na tela."""
    return None


async def _resumo_da_usina(
    base: UsinaOut, link: PlantLink, referencia: date, db: Session, usuario: User,
    blocos: frozenset[str] = TODOS_OS_BLOCOS,
) -> _Recorte:
    """Os blocos pedidos de uma usina, em paralelo, cada um nulo se falhar.

    `blocos` existe por causa do tempo: a carteira inteira levava 22 s contra os upstreams
    reais e a Visão geral tem UM esqueleto — o cliente corporativo olhava meio minuto de
    tela cinza na PRIMEIRA tela do portal. Energia (meuWatt) responde em segundos;
    manutenção e pendências (meuPlano, cinco idas por usina) é que arrastam. Separados em
    duas ondas, a tabela aparece cedo e as colunas de manutenção preenchem depois.
    """
    referencia_mes = referencia.strftime("%Y-%m")
    energia, paradas, manutencao, pendencias = await asyncio.gather(
        _bloco_energia(link, referencia, db, usuario) if "energia" in blocos else _nada(),
        _bloco_paradas(link, referencia, db, usuario) if "energia" in blocos else _nada(),
        _bloco_manutencao(link, referencia_mes, db, usuario) if "manutencao" in blocos else _nada(),
        _bloco_pendencias(link, db, usuario) if "manutencao" in blocos else _nada(),
        return_exceptions=True,
    )

    u = UsinaResumoOut(
        id=base.id, nome=base.nome, cidade=base.cidade, uf=base.uf,
        tom=base.tom, situacao=base.situacao, potencia_kw=base.potencia_kw,
        capacidade_kwp=base.capacidade_kwp,
    )
    recorte = _Recorte(usina=u)
    avisos: list[str] = []
    if base.aviso:
        avisos.append(base.aviso)

    if energia is None:
        pass                              # onda que não pediu este bloco
    elif (motivo := _falha(energia)) is not None:
        avisos.append(f"Energia: {motivo}")
    else:
        u.energia_mes_kwh = energia["energia"]
        u.esperado_mes_kwh = energia["esperado"]
        u.pct = energia["pct"]
        if energia["aviso"]:
            avisos.append(f"Energia: {energia['aviso']}")

    if paradas is None:
        pass                              # onda que não pediu este bloco
    elif (motivo := _falha(paradas)) is not None:
        avisos.append(f"Paradas: {motivo}")
    else:
        u.paradas_mes = paradas["total"]
        u.tempo_parado_min = paradas["tempo_parado_min"]
        recorte.paradas_em_aberto = paradas["em_aberto"]
        if paradas["aviso"]:
            avisos.append(f"Paradas: {paradas['aviso']}")

    if manutencao is None:
        pass                              # onda que não pediu este bloco
    elif (motivo := _falha(manutencao)) is not None:
        avisos.append(f"Manutenção: {motivo}")
    else:
        u.manutencao = ManutencaoDaUsinaOut(
            previsto_ate_mes=manutencao.get("previsto_ate_mes"),
            feitos=manutencao.get("feitos"),
            dispensados=manutencao.get("dispensados"),
            atrasados=manutencao.get("atrasados"),
            os_em_andamento=manutencao.get("os_em_andamento"),
        )
        recorte.os_concluidas_mes = manutencao.get("os_concluidas_mes")
        if manutencao.get("aviso"):
            avisos.append(f"Manutenção: {manutencao['aviso']}")

    if pendencias is None:
        pass                              # onda que não pediu este bloco
    elif (motivo := _falha(pendencias)) is not None:
        avisos.append(f"Pendências: {motivo}")
    else:
        u.pendencias_abertas = pendencias["abertas"]
        recorte.pendencias = pendencias
        if pendencias["aviso"]:
            avisos.append(f"Pendências: {pendencias['aviso']}")

    u.aviso = " · ".join(avisos) or None
    return recorte


# ── atenção ─────────────────────────────────────────────────────────────────

_PESO_DO_TOM = {"parado": 0, "multiplos": 1, "alerta": 2, "tempoRuim": 3, "semDados": 4, "ok": 5}


@dataclass
class _Ocorrencia:
    """Um problema numa usina, antes de virar faixa. `quantas` é o que a usina contribui
    para a contagem do grupo: duas paradas em aberto em Tiete contam duas, não uma."""

    especie: str
    tom: str
    usina: str
    quantas: int
    rota_da_usina: str


#: Como cada espécie se escreve, no singular e no plural, e para onde ela leva.
#:
#: `um` recebe a usina e a contagem dela; `muitos` recebe a contagem total e o número de
#: usinas. As duas frases existem porque elas dizem coisas diferentes: uma parada em aberto
#: numa usina é um fato sobre AQUELA usina; catorze espalhadas por seis são um fato sobre a
#: carteira, e nomear uma delas no título esconderia as outras cinco.
_ESPECIES: dict[str, dict[str, Any]] = {
    "usina_parada": {
        "tom": "parado",
        "sufixo": "",
        "acao": "Abrir usina",
        "um": lambda u, n: f"{u} está parada",
        "muitos": lambda n, k: f"{k} usinas paradas",
    },
    "parada_aberta": {
        "tom": "parado",
        "sufixo": "/energia/paradas",
        "acao": "Abrir paradas",
        "um": lambda u, n: f"{u} tem {n} parada{'s' if n > 1 else ''} em aberto",
        "muitos": lambda n, k: f"{n} paradas em aberto em {k} usinas",
    },
    "atividade_atrasada": {
        "tom": "alerta",
        "sufixo": "/manutencao/cronograma",
        "acao": "Ver cronograma",
        "um": lambda u, n: (
            f"{u} tem {n} atividade{'s' if n > 1 else ''} "
            f"atrasada{'s' if n > 1 else ''} no cronograma"
        ),
        "muitos": lambda n, k: f"{n} atividades atrasadas no cronograma, em {k} usinas",
    },
    "pendencia_vencida": {
        "tom": "alerta",
        "sufixo": "/manutencao/pendencias",
        "acao": "Ver pendências",
        "um": lambda u, n: f"{u} tem {n} pendência{'s' if n > 1 else ''} com prazo vencido",
        "muitos": lambda n, k: f"{n} pendências com prazo vencido, em {k} usinas",
    },
    "abaixo_do_esperado": {
        "tom": "alerta",
        "sufixo": "",
        "acao": "Comparar usinas",
        "um": lambda u, n: f"{u} ficou bem abaixo do esperado no mês",
        "muitos": lambda n, k: f"{k} usinas ficaram bem abaixo do esperado no mês",
    },
}

#: Onde uma espécie espalhada por várias usinas pode ser vista inteira. Espécie sem tela de
#: carteira cai na Visão geral, que é onde a tabela por usina está.
_ROTA_DA_CARTEIRA: dict[str, str] = {
    "atividade_atrasada": "/comparar/manutencao",
    "pendencia_vencida": "/comparar/manutencao",
    "abaixo_do_esperado": "/comparar/energia",
}


#: Quantas usinas o detalhe nomeia antes de resumir o resto. Acima disso a linha vira uma
#: parede de nomes e deixa de ser lida — e quem quer a lista inteira tem a tabela abaixo.
_NOMES_NO_DETALHE = 3


def _detalhe_das_usinas(ocorrencias: list[_Ocorrencia]) -> str:
    """"2 em Ouro Fino · 2 em Pereiras" — ou, com muitas, "… e outras 4"."""
    partes = [
        (o.usina if o.quantas == 1 else f"{o.quantas} em {o.usina}")
        for o in ocorrencias[:_NOMES_NO_DETALHE]
    ]
    resto = len(ocorrencias) - _NOMES_NO_DETALHE
    if resto > 0:
        partes.append(f"e outras {resto}")
    return " · ".join(partes)


def _atencao(recortes: list[_Recorte]) -> list[AtencaoResumoOut]:
    """As faixas do topo, só sobre fato: usina parada, parada em aberto, atividade
    atrasada no contrato, pendência com prazo vencido, geração bem abaixo da meta.

    Uma faixa vermelha que não corresponde a problema real é pior do que nenhuma: da
    segunda vez que o cliente abrir e não encontrar nada de errado, ele para de olhar.

    E uma faixa REPETIDA tem o mesmo efeito, pelo caminho oposto: sete tarjas iguais na
    primeira tela ensinam o olho a pular o bloco inteiro. Por isso as ocorrências da mesma
    espécie saem daqui já reunidas numa faixa só — ver `AtencaoResumoOut`.
    """
    ocorrencias: list[_Ocorrencia] = []
    for r in recortes:
        u = r.usina
        rota = f"/usinas/{u.id}"

        def anotar(especie: str, quantas: int) -> None:
            ocorrencias.append(_Ocorrencia(
                especie=especie, tom=_ESPECIES[especie]["tom"],
                usina=u.nome, quantas=quantas, rota_da_usina=rota,
            ))

        if u.tom == "parado":
            anotar("usina_parada", 1)
        if r.paradas_em_aberto:
            anotar("parada_aberta", r.paradas_em_aberto)
        if u.manutencao and u.manutencao.atrasados:
            anotar("atividade_atrasada", u.manutencao.atrasados)
        if r.pendencias.get("prazo_vencido"):
            anotar("pendencia_vencida", r.pendencias["prazo_vencido"])

        # Só o "bem abaixo" acende faixa; "abaixo" já está na cor do número, e faixa
        # demais é faixa ignorada.
        _, tom_energia, _frase = _situacao_do_projeto(u.energia_mes_kwh, u.esperado_mes_kwh)
        if tom_energia == "parado":
            anotar("abaixo_do_esperado", 1)

    saida: list[AtencaoResumoOut] = []
    for especie, regra in _ESPECIES.items():
        do_grupo = [o for o in ocorrencias if o.especie == especie]
        if not do_grupo:
            continue
        # Maior primeiro: numa faixa que resume seis usinas, é a pior que dá o nome ao
        # detalhe — e é nela que o cliente clica.
        do_grupo.sort(key=lambda o: -o.quantas)
        total = sum(o.quantas for o in do_grupo)
        uma_usina = len(do_grupo) == 1
        saida.append(AtencaoResumoOut(
            tom=regra["tom"],
            titulo=(
                regra["um"](do_grupo[0].usina, do_grupo[0].quantas)
                if uma_usina
                else regra["muitos"](total, len(do_grupo))
            ),
            # Numa usina só o título já diz tudo; repetir o nome embaixo é ruído.
            detalhe=None if uma_usina else _detalhe_das_usinas(do_grupo),
            # Com uma usina, a rota é a dela; com várias, não há uma usina para abrir, e a
            # tela da carteira é o único destino honesto.
            rota=(
                f"{do_grupo[0].rota_da_usina}{regra['sufixo']}"
                if uma_usina
                else _ROTA_DA_CARTEIRA.get(especie, "/")
            ),
            acao=regra["acao"],
            contagem=total,
            especie=especie,
        ))

    # Estável: a ordem de gravidade primeiro e, dentro dela, a ordem das espécies.
    saida.sort(key=lambda a: _PESO_DO_TOM.get(a.tom, 9))
    return saida



# ── rota ────────────────────────────────────────────────────────────────────


def _somar(valores: list[float | None]) -> float | None:
    """Soma do que existe; `None` quando nada existe. Zero só sai daqui se alguém mediu zero."""
    com_dado = [v for v in valores if v is not None]
    return round(sum(com_dado), 2) if com_dado else None


def _somar_inteiros(valores: list[int | None]) -> int | None:
    com_dado = [v for v in valores if v is not None]
    return sum(com_dado) if com_dado else None


def _blocos_pedidos(valor: str | None) -> frozenset[str]:
    """"energia", "manutencao" ou os dois separados por vírgula. Ausente ou "tudo" = tudo.
    Nome desconhecido é recusado com a frase — silenciar viraria uma tela sem explicação
    para colunas vazias."""
    if valor is None or valor.strip().lower() in {"", "tudo", "todos"}:
        return TODOS_OS_BLOCOS
    pedidos = {p.strip().lower() for p in valor.split(",") if p.strip()}
    desconhecidos = pedidos - TODOS_OS_BLOCOS
    if desconhecidos or not pedidos:
        aceitos = ", ".join(sorted(TODOS_OS_BLOCOS))
        raise HTTPException(400, f"Bloco desconhecido: {', '.join(sorted(desconhecidos)) or valor}. Use {aceitos} ou tudo.")
    return frozenset(pedidos)


@router.get("/resumo", response_model=ResumoOut)
async def resumo(
    referencia: str | None = None,
    blocos: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ResumoOut:
    """A carteira no mês de referência (qualquer dia do mês; ausente = hoje; futuro = 400).

    `listar_usinas` é chamado uma vez para todas — ele já consulta o meuWatt em paralelo
    — e os outros blocos correm em paralelo por usina. Em série, três usinas a quatro
    upstreams cada dariam uma tela de vinte segundos.

    `blocos` pede uma ONDA só: `energia` (geração e paradas) ou `manutencao` (cronograma,
    ordens e pendências); ausente = as duas, como sempre foi. Existe porque a Visão geral
    levava 22 s contra os upstreams reais, com um esqueleto único — a primeira tela do
    portal ficava meio minuto cinza. Em duas ondas a tabela aparece com a energia e as
    colunas de manutenção preenchem depois, sem que nenhum número deixe de ser do servidor.
    """
    data = _referencia_pedida(referencia)
    referencia_mes = data.strftime("%Y-%m")
    pedidos = _blocos_pedidos(blocos)
    lista = await listar_usinas(db=db, usuario=usuario)

    saida = ResumoOut(
        referencia_mes=referencia_mes,
        # O horário do DADO, não o da resposta: é ele que a tela carimba no selo.
        atualizado_em=lista.medido_em or lista.atualizado_em,
        potencia_agora_kw=lista.potencia_agora_kw,
        tom="semDados",
        situacao="Sem dados de geração no período",
        aviso=lista.aviso,
    )
    if not lista.usinas:
        return saida

    # `listar_usinas` já é o escopo desta pessoa; os vínculos vêm da mesma consulta de
    # escopo, nunca de um id que chegou pela rede.
    links = {l.id: l for l in usinas_do_usuario(db, usuario)}
    recortes: list[_Recorte] = list(await asyncio.gather(
        *(
            _resumo_da_usina(base, links[base.id], data, db, usuario, pedidos)
            for base in lista.usinas
            if base.id in links
        )
    ))
    usinas = [r.usina for r in recortes]
    saida.usinas = usinas

    # Energia: os totais somam quem tem dado; o percentual e a cor, só quem tem dado E
    # meta — pela mesma régua da tela da usina, aplicada ao conjunto.
    saida.usinas_com_dado = sum(1 for u in usinas if u.energia_mes_kwh is not None)
    saida.energia_mes_kwh = _somar([u.energia_mes_kwh for u in usinas])
    saida.esperado_mes_kwh = _somar([u.esperado_mes_kwh for u in usinas])
    comparaveis = [u for u in usinas if u.energia_mes_kwh is not None and u.esperado_mes_kwh]
    if comparaveis:
        energia = _somar([u.energia_mes_kwh for u in comparaveis])
        meta = _somar([u.esperado_mes_kwh for u in comparaveis])
        saida.pct_do_esperado, saida.tom, saida.situacao = _situacao_do_projeto(energia, meta)
    else:
        _, saida.tom, saida.situacao = _situacao_do_projeto(saida.energia_mes_kwh, None)

    # Manutenção: só existe agregado se alguma usina respondeu.
    com_manutencao = [r for r in recortes if r.usina.manutencao is not None]
    if com_manutencao:
        saida.manutencao = ManutencaoResumoOut(
            os_em_andamento=_somar_inteiros(
                [r.usina.manutencao.os_em_andamento for r in com_manutencao]  # type: ignore[union-attr]
            ),
            os_concluidas_mes=_somar_inteiros([r.os_concluidas_mes for r in com_manutencao]),
            atrasados_total=_somar_inteiros(
                [r.usina.manutencao.atrasados for r in com_manutencao]  # type: ignore[union-attr]
            ),
        )

    com_pendencias = [r.pendencias for r in recortes if r.pendencias.get("abertas") is not None]
    if com_pendencias:
        saida.pendencias = PendenciasResumoOut(
            abertas=sum(p["abertas"] for p in com_pendencias),
            prazo_vencido=_somar_inteiros([p.get("prazo_vencido") for p in com_pendencias]),
            cobradas_abertas=_somar_inteiros([p.get("cobradas_abertas") for p in com_pendencias]),
        )

    saida.atencao = _atencao(recortes)
    return saida
