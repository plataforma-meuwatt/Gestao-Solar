"""Comparar as usinas da carteira — geração e manutenção, lado a lado.

O pedido do dono: *"crie um dash de comparação entre usinas... quero que o cliente consiga
comparar as usinas e ver qual gera mais; para isso use PRODUTIVIDADE"* e *"já crie uma
versão de dash comparativo de manutenção"*.

Comparar é uma pergunta DIFERENTE da Visão geral. Lá se pergunta "como está tudo agora";
aqui, "qual gera mais" e "qual está atrasada" — e essa segunda pergunta exige um PERÍODO e
uma régua que não minta quando as usinas são desiguais. Daí este módulo, e não mais uma aba
de `/resumo`.

**A régua é de `services/carteira.py`, não daqui.** Ordenação, janela comum e
percentual em dia são aritmética pura e vivem lá, testados sem subir aplicação
(`tests/test_carteira_regua.py`). Este módulo COMPÕE: busca, monta as linhas e entrega os
números prontos às réguas. Reimplementar qualquer uma delas aqui criaria a segunda régua
para a mesma pergunta — que é o defeito que este arquivo inteiro existe para evitar.

**Composição INTERNA, como em `resumo.py`.** A manutenção sai de `cronograma_da_usina`,
`listar_ordens` e `listar_pendencias` chamadas como FUNÇÕES — nunca por HTTP contra o
próprio serviço. A energia lê o `generation/range` UMA vez por usina e deriva com os MESMOS
auxiliares de `plants.py` que sustentam `/plants/{id}/desempenho`: as duas telas têm de
dizer o mesmo número, e o teste `test_energia_bate_digito_a_digito_com_o_resumo` é o que
prova que continuam dizendo.

**Uma ida por usina, e nas MESMAS datas.** A Visão geral já custou 22 s por fazer ~64 idas
simultâneas. Aqui o bloco de energia faz exatamente UMA chamada de `generation/range` por
usina — ela já traz energia, capacidade, produtividade, PR, as duas disponibilidades,
perdas e irradiação. E a janela é a mesma que `/desempenho` usa (mês fechado, fim travado
em hoje), para cair no cache de 10 min já quente do upstream em vez de provocar um `miss`
a cada abertura de tela.

### As quatro regras de não mentir comparando usinas diferentes

1. **Capacidade diferente → kWh/kWp.** A PRODUTIVIDADE é o ranking padrão; a energia
   absoluta viaja ao lado respondendo a OUTRA pergunta, e cada uma vem rotulada.
2. **Data de entrada diferente → JANELA COMUM.** A interseção dos meses realmente medidos,
   impressa e NOMEANDO quem encolheu o período. Não existe coluna de comissionamento no
   meuWatt: a entrada tardia é derivada do dado, com `_meses_medidos`.
3. **Sem dado, sem capacidade ou sem PR sai do RANKING** — em vez de aparecer como zero no
   fim, que é a leitura mais injusta possível de uma ausência.
4. **Irradiação viaja junto como contexto**, porque "rende melhor" ainda contém "teve mais
   sol", e sem o par o cliente atribui à usina o que foi do céu.

### E as da manutenção

O ranking é por **atrasadas** (absoluto — independe do tamanho do contrato), nunca por
percentual puro. O percentual sai como `feitas ÷ (feitas + dispensadas + atrasadas)`:
`azul` é futuro e não pode acusar o prestador de nada, e a dispensa **nunca funde com o
feito** — apagar essa diferença era exatamente o risco que o meuPlano recusou correr. Todo
percentual vem com o denominador ao lado, e usina sem contrato ou sem cronograma publicado
aparece com o motivo escrito e FORA dos totais, cujo cabeçalho diz de quantas usinas fala.
"""

import asyncio
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.manutencao import (
    EM_CURSO,
    CronogramaOut,
    cronograma_da_usina,
    listar_ordens,
)
from app.api.v1.pendencias import CONCLUIDA, listar_pendencias
from app.api.v1.plants import (
    _chave_mes,
    _energia_do_periodo,
    _meses_entre,
    _meses_medidos,
    _numero,
    _perdas_do_periodo,
    _pr_pct,
    _resumo_por_mes,
    _tem_dado,
    usinas_do_usuario,
)
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import carteira as regua
from app.services import integracoes

router = APIRouter(prefix="/api/v1/carteira", tags=["portal · carteira"])


# ── formato ─────────────────────────────────────────────────────────────────


class JanelaOut(BaseModel):
    """O período efetivamente comparado — e o que ele deixou de fora.

    Sem este bloco a tela mostraria um ranking de doze meses contra um de quatro sem
    nenhum sinal de que os dois não são comparáveis. `encolhida_por` NOMEIA a usina cuja
    entrada tardia (ou cujo buraco de medição) reduziu a interseção: sem o nome, o cliente
    lê "jun a set" e não tem como saber por que o ano virou quatro meses.
    """

    de: str
    ate: str
    #: Todos os meses do período pedido, em ordem.
    meses: list[str] = []
    #: A interseção dos meses REALMENTE medidos por todas as usinas com dado.
    meses_comuns: list[str] = []
    #: "ago de 2026", "jun a set de 2026" — a frase que a tela carimba no cabeçalho.
    rotulo: str | None = None
    #: A interseção cobre o período inteiro. Falso = a comparação é mais estreita.
    completa: bool = True
    #: Quem tirou mês da interseção — só entra a usina que não mediu um mês que OUTRA
    #: mediu, da mordida maior para a menor (`services.carteira.QuemEncolheu`).
    encolhida_por: list[str] = []
    #: Usinas sem UM mês medido no período: saem da comparação em vez de virar zero.
    fora_da_comparacao: list[str] = []
    #: Usinas cujo detalhe mensal não veio: entram, mas a cobertura não foi conferida.
    #: "Não sabemos" não é "não tem" — fundir as duas sumiria com a usina.
    sem_detalhe: list[str] = []
    #: Quantas usinas a janela cobre. É o "de N" dos totais. Só tem sentido quando
    #: `cobertura_conferida` — sem o bloco de energia ninguém foi ao upstream perguntar que
    #: meses cada usina mediu, e o zero aqui significa "não perguntei", não "nenhuma".
    comparaveis: int = 0
    #: Alguém REALMENTE conferiu a cobertura mês a mês (= o bloco de energia foi pedido).
    #: Falso: a janela é a PEDIDA, e a tela não pode escrever "N de M usinas entram nesta
    #: comparação" — foi assim que o rodapé de manutenção passou a dizer "0 de 7" embaixo de
    #: uma tabela com usina ranqueada em 1º.
    cobertura_conferida: bool = False
    #: A frase pronta, quando há o que explicar. Nulo quando a janela é a pedida.
    nota: str | None = None
    #: `ate` foi travado em hoje. Pedir o mês inteiro em curso é legítimo e comum — o que
    #: não pode é a comparação fingir que mediu o futuro.
    truncada_em_hoje: bool = False


class UsinaEnergiaOut(BaseModel):
    """A geração de UMA usina no período, do jeito que a comparação precisa."""

    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None

    capacidade_kwp: float | None = None
    #: Energia do PERÍODO PEDIDO. É o mesmo número de `/plants/{id}/desempenho` e o mesmo
    #: que `/api/v1/resumo` soma — a mesma pergunta não pode ter duas respostas no portal.
    energia_kwh: float | None = None
    #: Energia só dos meses da JANELA COMUM. Igual a `energia_kwh` quando a janela cobre o
    #: período inteiro, que é sempre o caso de um mês só.
    energia_comparavel_kwh: float | None = None
    #: kWh/kWp — o ranking padrão, e a única régua que sobrevive a capacidades diferentes.
    produtividade_kwh_kwp: float | None = None
    #: Nulo sem POA medida: o upstream devolve `0.0` por construção, e 0 % de PR não é uma
    #: medição, é a ausência dela.
    pr_pct: float | None = None
    disponibilidade_real_pct: float | None = None
    disponibilidade_contratual_pct: float | None = None
    #: Zero aqui é legítimo (houve dado e não houve perda). Nulo é "não houve dado".
    perdas_paradas_kwh: float | None = None
    #: Contexto obrigatório do ranking: "rende melhor" ainda contém "teve mais sol".
    irradiacao_hpoa: float | None = None
    irradiacao_ghi: float | None = None
    #: Paradas sem classificação no período — a ressalva da disponibilidade contratual.
    paradas_pendentes: int | None = None

    #: Os meses que ESTA usina mediu dentro do período. É deles que sai a janela comum.
    meses_medidos: list[str] = []
    #: Por que esta usina não tem número. Ela continua na lista (travessão na tela) e fica
    #: fora de todo ranking e de todo total.
    motivo: str | None = None


class TotaisEnergiaOut(BaseModel):
    """Os totais da carteira — em DUAS populações, nomeadas, nunca misturadas.

    A armadilha que este bloco existe para desarmar: `energia_kwh` é do PERÍODO PEDIDO e de
    TODAS as usinas com medição; `produtividade_kwh_kwp` sai da JANELA COMUM e só das usinas
    que têm capacidade declarada. Postos lado a lado sem rótulo, os três não fecham entre si
    — o leitor divide energia por capacidade, acha 536,6 e lê 380,1 logo ao lado. Por isso os
    equivalentes da janela comum viajam com nome próprio, e é deles que a tela faz manchete.
    """

    #: De quantas usinas este total fala. Sem ele, "3,2 GWh" parece a carteira inteira.
    usinas_no_total: int = 0
    #: Σ do período PEDIDO, de todas as usinas com medição — outra pergunta que a manchete.
    energia_kwh: float | None = None
    #: Σ da capacidade de TODAS as usinas, inclusive as que ficaram fora da comparação.
    capacidade_kwp: float | None = None
    #: Σ energia da JANELA COMUM, só das `usinas_no_total`. É o numerador da produtividade.
    energia_comparavel_kwh: float | None = None
    #: Σ capacidade das MESMAS usinas do numerador. É o denominador da produtividade.
    capacidade_comparavel_kwp: float | None = None
    #: Σ energia comparável ÷ Σ capacidade — só das usinas que têm os dois.
    produtividade_kwh_kwp: float | None = None
    perdas_paradas_kwh: float | None = None


class UsinaManutencaoOut(BaseModel):
    """A manutenção de UMA usina na janela — pela conformidade do ATIVO, não por contar
    tarefas. A cor da célula vem do meuPlano e é repassada; recalcular aqui daria uma
    segunda resposta para a mesma pergunta."""

    id: int
    nome: str
    contrato: str | None = None
    contrato_id: int | None = None

    #: Σ das ocorrências previstas nos meses da janela. Nulo sem cronograma consolidado —
    #: que é diferente de "nada previsto".
    previsto: int | None = None
    feitas: int | None = None
    #: Dispensa registrada com motivo. NUNCA se soma a `feitas`.
    dispensadas: int | None = None
    atrasadas: int | None = None
    #: `feitas + dispensadas + atrasadas`. Viaja junto porque todo percentual desta tela
    #: aparece com o denominador ao lado ("13 de 31") — sozinho, 41,9 % não quer dizer nada.
    denominador: int | None = None
    #: `feitas ÷ denominador × 100`. Nulo quando o denominador é zero: não há o que cumprir.
    cumprimento_pct: float | None = None
    #: "13 de 31" — o que a tela imprime AO LADO do percentual, montado pela régua. Dois
    #: percentuais sem denominador na mesma tela é o defeito que produziu "13 de 270" numa
    #: aba e "41,9 %" na outra, para uma usina sem uma única atividade atrasada.
    cumprimento_rotulo: str | None = None
    #: "18 ainda no prazo — fora da conta." Nulo quando nada foi excluído.
    fora_da_conta: str | None = None

    os_em_andamento: int | None = None
    pendencias_abertas: int | None = None
    pendencias_vencidas: int | None = None
    pendencias_cobradas: int | None = None
    #: Das abertas, as de criticidade `critica`. Não existe campo de urgência na OS que
    #: chega a este BFF (`OrdemOut` não tem prioridade); inventar um seria fabricar dado.
    pendencias_criticas: int | None = None

    #: "Cronograma não publicado neste contrato", "Sem contrato de O&M cadastrado" — o
    #: travessão da tela vem com o porquê escrito, e a usina fica fora dos totais.
    motivo: str | None = None


class TotaisManutencaoOut(BaseModel):
    usinas_no_total: int = 0
    previsto: int | None = None
    feitas: int | None = None
    dispensadas: int | None = None
    atrasadas: int | None = None
    denominador: int | None = None
    cumprimento_pct: float | None = None
    #: "31 de 74" — o denominador viaja com o percentual também no total.
    cumprimento_rotulo: str | None = None
    os_em_andamento: int | None = None
    pendencias_abertas: int | None = None
    pendencias_vencidas: int | None = None


class ItemRankingOut(BaseModel):
    #: 1 = melhor. Empate DIVIDE a posição (1, 1, 3) — ver `services.carteira.ranking`:
    #: desempatar por nome coroaria uma usina pela inicial dela.
    posicao: int
    usina_id: int
    usina: str
    valor: float
    empatado: bool = False
    #: O "de N" que acompanha todo percentual. Nulo nos rankings que não são percentuais.
    denominador: int | None = None


class RankingOut(BaseModel):
    #: `produtividade` | `energia` | `pr` | `atrasadas` | `cumprimento` | `pendencias_vencidas`
    chave: str
    titulo: str
    #: A pergunta que ESTE ranking responde, na voz do cliente. Vem de
    #: `services.carteira.PERGUNTAS` quando a régua já a redigiu — a tela nunca escreve a
    #: sua, senão "produtividade" vira "eficiência" numa e "rendimento" noutra.
    pergunta: str
    #: A frase que desarma a leitura errada deste ranking. Nulo quando não há armadilha.
    nota: str | None = None
    unidade: str | None = None
    #: `desc` = maior primeiro.
    ordem: str = "desc"
    itens: list[ItemRankingOut] = []
    #: Usinas que ficaram DE FORA deste ranking, com o motivo — "sem PR (sem POA medida)".
    #: Sem esta lista, a ausência vira suspeita de erro da tela.
    fora: list[str] = []


class BlocoEnergiaOut(BaseModel):
    usinas: list[UsinaEnergiaOut] = []
    totais: TotaisEnergiaOut = TotaisEnergiaOut()
    rankings: list[RankingOut] = []


class BlocoManutencaoOut(BaseModel):
    usinas: list[UsinaManutencaoOut] = []
    totais: TotaisManutencaoOut = TotaisManutencaoOut()
    rankings: list[RankingOut] = []
    #: Os meses que ESTAS contagens usaram — sempre os do período PEDIDO. Viajam aqui porque
    #: com `blocos=tudo` a `janela` do topo é a interseção da ENERGIA, e carimbá-la sobre
    #: números contados noutro intervalo daria duas respostas para "de que período é isto".
    meses: list[str] = []
    #: A frase do intervalo acima, pronta ("jan a set de 2026").
    rotulo: str | None = None


class ComparativoOut(BaseModel):
    janela: JanelaOut
    energia: BlocoEnergiaOut | None = None
    manutencao: BlocoManutencaoOut | None = None
    #: Quantas usinas o escopo desta pessoa tem. É o "de N" de tudo o que está acima.
    usinas_no_escopo: int = 0
    aviso: str | None = None


# ── período ─────────────────────────────────────────────────────────────────


def _data_pedida(valor: str, campo: str) -> date:
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{campo} deve estar no formato YYYY-MM-DD."
        ) from None


def _periodo(de: str | None, ate: str | None) -> tuple[date, date, bool]:
    """`(início, fim, fim foi travado em hoje)`.

    Ausente = o mês corrente até hoje — a mesma janela que `/plants/{id}/desempenho`
    monta para `recorte=mes`, de propósito: assim as duas telas caem na MESMA entrada do
    cache de 10 min do upstream em vez de provocar um `miss` cada.

    `ate` no futuro é TRAVADO em hoje, não recusado: pedir "o mês em curso" é legítimo e é
    o que a tela faz o mês inteiro. `de` no futuro é recusado — não há nada a comparar.
    """
    hoje = hoje_na_usina()
    inicio = _data_pedida(de, "de") if de else hoje.replace(day=1)
    fim_pedido = _data_pedida(ate, "ate") if ate else hoje
    if inicio > hoje:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "de não pode ser futura.")
    if fim_pedido < inicio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ate não pode ser anterior a de.")
    fim = min(fim_pedido, hoje)
    return inicio, fim, fim < fim_pedido


#: Os blocos que o comparativo sabe montar. Pedir um só é o que deixa a família de Geração
#: abrir sem esperar o meuPlano, e a de Manutenção sem esperar o meuWatt.
TODOS_OS_BLOCOS = frozenset({"energia", "manutencao"})


def _blocos_pedidos(valor: str | None) -> frozenset[str]:
    """Ausente ou "tudo" = os dois. Nome desconhecido é recusado COM a frase: silenciar
    devolveria uma tela vazia sem nenhuma explicação para o bloco que não veio."""
    if valor is None or valor.strip().lower() in {"", "tudo", "todos"}:
        return TODOS_OS_BLOCOS
    pedidos = {p.strip().lower() for p in valor.split(",") if p.strip()}
    desconhecidos = pedidos - TODOS_OS_BLOCOS
    if desconhecidos or not pedidos:
        aceitos = ", ".join(sorted(TODOS_OS_BLOCOS))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Bloco desconhecido: {', '.join(sorted(desconhecidos)) or valor}. "
            f"Use {aceitos} ou tudo.",
        )
    return frozenset(pedidos)


def _falha(resultado: Any) -> str | None:
    """A frase de uma exceção apanhada pelo `gather`, ou `None` quando o bloco respondeu."""
    if isinstance(resultado, HTTPException):
        return str(resultado.detail)
    if isinstance(resultado, BaseException):
        return str(resultado) or resultado.__class__.__name__
    return None


def _somar(valores: list[float | None]) -> float | None:
    """Soma do que existe; nulo quando nada existe. Zero só sai daqui se alguém mediu zero."""
    com_dado = [v for v in valores if v is not None]
    return round(sum(com_dado), 2) if com_dado else None


def _somar_inteiros(valores: list[int | None]) -> int | None:
    com_dado = [v for v in valores if v is not None]
    return sum(com_dado) if com_dado else None


def _ranking(
    chave: str,
    candidatos: list[tuple[int, str, float | None, int | None, str]],
    *,
    titulo: str | None = None,
    pergunta: str | None = None,
    unidade: str | None = None,
    nota: str | None = None,
    maior_e_melhor: bool = True,
) -> RankingOut:
    """Um ranking a partir de `(id, nome, valor, denominador, motivo da ausência)`.

    A ORDENAÇÃO é de `services.carteira.ranking` — casca fina de propósito. É lá que moram
    o descarte da ausência (valor nulo NUNCA vira zero no fim da lista: um zero fabricado
    num ranking é a acusação mais barata que uma tela pode fazer, e a mais difícil de o
    cliente desconfiar, porque parece um número), a guarda contra `NaN`/`bool` e o empate
    que divide a posição. O que este invólucro acrescenta é só o que a régua pura não pode
    saber: o `usina_id` da rota e a frase do motivo de cada ausência.

    Título e pergunta vêm de `PERGUNTAS` quando a régua já os redigiu; os rankings que ela
    ainda não nomeia (PR, cumprimento, pendências vencidas) passam o texto aqui — e quem
    for acrescentá-los lá deve remover o texto local, não deixar os dois.
    """
    definicao = regua.PERGUNTAS.get(chave)
    saida = RankingOut(
        chave=chave,
        titulo=titulo or (definicao.rotulo if definicao else chave),
        pergunta=pergunta or (definicao.pergunta if definicao else ""),
        nota=nota or (definicao.nota if definicao else None),
        unidade=unidade if unidade is not None else (definicao.unidade if definicao else None),
        ordem="desc" if maior_e_melhor else "asc",
    )
    nomes = {i: n for i, n, _, _, _ in candidatos}
    denominadores = {i: d for i, _, _, d, _ in candidatos}
    linhas = [{"id": i, chave: v} for i, _, v, _, _ in candidatos]
    saida.itens = [
        ItemRankingOut(
            posicao=posto.posicao,
            usina_id=posto.chave,
            usina=nomes[posto.chave],
            valor=round(posto.valor, 2),
            empatado=posto.empatado,
            denominador=denominadores[posto.chave],
        )
        for posto in regua.ranking(
            chave, linhas, identidade="id", maior_e_melhor=maior_e_melhor
        )
    ]
    ranqueados = {i.usina_id for i in saida.itens}
    saida.fora = [f"{n} — {motivo}" for i, n, _, _, motivo in candidatos if i not in ranqueados]
    return saida


# ── energia ─────────────────────────────────────────────────────────────────


def _capacidade(relatorio: Any) -> float | None:
    """`total_capacity_kwp` — característica FÍSICA da usina, declarada pelo meuWatt.

    Não se soma a capacidade dos inversores que estão falando: ela encolhe quando um
    aparelho emudece, e uma capacidade que muda com o estado do Modbus é o denominador
    errado para um ranking de kWh/kWp — a usina com inversor mudo apareceria em primeiro.
    """
    if not isinstance(relatorio, dict):
        return None
    return _numero(relatorio.get("total_capacity_kwp")) or None


def _irradiacao(relatorio: Any) -> tuple[float | None, float | None]:
    """`irradiation.{hpoa, hghi}`. Zero é o valor por construção quando não há estação —
    e não uma medição de "não houve sol"."""
    if not isinstance(relatorio, dict):
        return None, None
    bruto = relatorio.get("irradiation")
    if not isinstance(bruto, dict):
        return None, None
    poa = _numero(bruto.get("hpoa"))
    ghi = _numero(bruto.get("hghi"))
    return (poa if poa and poa > 0 else None, ghi if ghi and ghi > 0 else None)


def _paradas_pendentes(relatorio: Any) -> int | None:
    if not isinstance(relatorio, dict):
        return None
    valor = relatorio.get("pending_classification_count")
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _energia_dos_meses(relatorio: Any, meses: list[str]) -> float | None:
    """Σ `monthly_summaries[].generation_kwh` dos meses pedidos.

    É o único jeito de recortar a energia na janela comum sem uma segunda ida ao upstream
    — o rollup mensal já vem na MESMA resposta que traz o total do período.
    """
    por_mes = _resumo_por_mes(relatorio)
    valores = [
        v
        for m in meses
        if (v := _numero((por_mes.get(m) or {}).get("generation_kwh"))) is not None
    ]
    return round(sum(valores), 2) if valores else None


def _linha_de_energia(link: PlantLink, relatorio: Any, meses: list[str]) -> UsinaEnergiaOut:
    """Uma usina montada a partir do `range`, com os MESMOS auxiliares de `plants.py`."""
    linha = UsinaEnergiaOut(id=link.id, nome=link.nome, cidade=link.cidade, uf=link.uf)
    linha.capacidade_kwp = _capacidade(relatorio)
    if not _tem_dado(relatorio):
        linha.motivo = "O monitoramento não tem medição desta usina no período."
        return linha

    linha.energia_kwh = _energia_do_periodo(relatorio)
    linha.pr_pct = _pr_pct(relatorio)
    linha.disponibilidade_real_pct = _numero(relatorio.get("availability_real_pct"))
    linha.disponibilidade_contratual_pct = _numero(relatorio.get("availability_contratual_pct"))
    linha.perdas_paradas_kwh = _perdas_do_periodo(relatorio)
    linha.irradiacao_hpoa, linha.irradiacao_ghi = _irradiacao(relatorio)
    linha.paradas_pendentes = _paradas_pendentes(relatorio)
    # `or meses` é a mesma queda de `desempenho_da_usina`: sem `monthly_summaries` não há
    # como alinhar, e inventar alinhamento seria pior do que a comparação larga.
    linha.meses_medidos = _meses_medidos(relatorio, meses) or list(meses)
    if linha.energia_kwh is None:
        linha.motivo = "O monitoramento não devolveu geração para este período."
    return linha


def _janela_de(comum: regua.JanelaComum, inicio: date, fim: date, meses: list[str],
               truncada: bool) -> JanelaOut:
    """A `JanelaComum` da régua traduzida no contrato da rota — sem recalcular nada."""
    return JanelaOut(
        de=inicio.isoformat(), ate=fim.isoformat(), meses=meses,
        meses_comuns=list(comum.meses),
        rotulo=comum.rotulo or regua.rotulo_de_meses(meses),
        completa=bool(comum.meses) and len(comum.meses) == len(meses),
        encolhida_por=[q.usina for q in comum.encolheram],
        fora_da_comparacao=sorted(comum.fora),
        sem_detalhe=sorted(comum.sem_detalhe),
        comparaveis=comum.comparaveis,
        cobertura_conferida=True,
        nota=comum.aviso,
        truncada_em_hoje=truncada,
    )


async def _bloco_energia(
    links: list[PlantLink], inicio: date, fim: date, meses: list[str], db: Session,
    truncada: bool,
) -> tuple[BlocoEnergiaOut, JanelaOut]:
    """`(bloco, janela efetivamente comparada)`. UMA ida ao `range` por usina."""
    bloco = BlocoEnergiaOut()
    monitoradas = [l for l in links if l.mw_plant_slug]
    linhas: list[UsinaEnergiaOut] = [
        UsinaEnergiaOut(
            id=l.id, nome=l.nome, cidade=l.cidade, uf=l.uf,
            motivo="Esta usina não está ligada ao monitoramento.",
        )
        for l in links
        if not l.mw_plant_slug
    ]
    # Sem nenhuma usina medida não há interseção nenhuma — e a janela DIZ isso em vez de
    # devolver o período pedido como se ele tivesse sido conferido.
    janela_cheia = _janela_de(regua.JanelaComum(), inicio, fim, meses, truncada)
    if not monitoradas:
        bloco.usinas = sorted(linhas, key=lambda u: u.nome)
        janela_cheia.nota = "Nenhuma das suas usinas está ligada ao monitoramento."
        return bloco, janela_cheia

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001 — a ponte fora não derruba o outro bloco
        linhas.extend(
            UsinaEnergiaOut(id=l.id, nome=l.nome, cidade=l.cidade, uf=l.uf,
                            motivo=f"Monitoramento indisponível: {exc}")
            for l in monitoradas
        )
        bloco.usinas = sorted(linhas, key=lambda u: u.nome)
        janela_cheia.nota = f"Monitoramento indisponível: {exc}"
        return bloco, janela_cheia

    # UMA chamada por usina, e só esta: o `range` já traz energia, capacidade,
    # produtividade, PR, as duas disponibilidades, perdas e irradiação.
    respostas = await asyncio.gather(
        *(cliente.geracao_periodo(l.mw_plant_slug, inicio, fim) for l in monitoradas),
        return_exceptions=True,
    )

    for link, resposta in zip(monitoradas, respostas, strict=True):
        if (motivo := _falha(resposta)) is not None:
            linhas.append(UsinaEnergiaOut(id=link.id, nome=link.nome, cidade=link.cidade,
                                          uf=link.uf, motivo=f"Monitoramento: {motivo}"))
            continue
        linhas.append(_linha_de_energia(link, resposta, meses))

    # A JANELA COMUM sai da régua pura, alimentada com os relatórios CRUS: é ela que sabe
    # que um mês zerado é medidor mudo (o rollup do upstream fabrica `0.0` para os meses
    # anteriores ao início da série), e que "sem detalhe mensal" não é "não mediu".
    por_id = {l.id: l for l in linhas}
    respondeu = {
        link.nome: resposta
        for link, resposta in zip(monitoradas, respostas, strict=True)
        if por_id[link.id].energia_kwh is not None
    }
    comum = regua.janela_comum(
        regua.meses_medidos_por_usina(respondeu, meses), intervalo=meses
    )
    janela = _janela_de(comum, inicio, fim, meses, truncada)
    comuns = list(comum.meses)
    # A energia comparável é a dos meses da interseção. Quando a interseção é o período
    # inteiro — sempre, num mês só — ela é o próprio total, e nenhum número muda.
    recortar = bool(comuns) and len(comuns) < len(meses)
    for link, resposta in zip(monitoradas, respostas, strict=True):
        linha = por_id[link.id]
        if linha.energia_kwh is None:
            continue
        linha.energia_comparavel_kwh = (
            _energia_dos_meses(resposta, comuns) if recortar else linha.energia_kwh
        )
        if recortar:
            base = linha.energia_comparavel_kwh
            linha.produtividade_kwh_kwp = (
                round(base / linha.capacidade_kwp, 2)
                if base is not None and linha.capacidade_kwp
                else None
            )
        else:
            # O número do PRÓPRIO upstream (`total_gen ÷ total_cap`) — não um segundo
            # cálculo nosso, que divergiria dele na primeira mudança de régua lá.
            bruta = _numero(resposta.get("productivity")) if isinstance(resposta, dict) else None
            linha.produtividade_kwh_kwp = round(bruta, 2) if bruta and bruta > 0 else None

    # Quem a régua excluiu (nenhum mês medido no período) perde os números de comparação:
    # deixá-los seria comparar o total de um período com o de outro.
    for nome in comum.fora:
        for linha in linhas:
            if linha.nome == nome:
                linha.energia_comparavel_kwh = None
                linha.produtividade_kwh_kwp = None
                linha.motivo = linha.motivo or "Sem medição no período comparado."

    linhas.sort(key=lambda u: u.nome)
    bloco.usinas = linhas

    comparaveis = [l for l in linhas if l.energia_comparavel_kwh is not None]
    com_capacidade = [l for l in comparaveis if l.capacidade_kwp]
    bloco.totais = TotaisEnergiaOut(
        usinas_no_total=len(comparaveis),
        energia_kwh=_somar([l.energia_kwh for l in linhas]),
        capacidade_kwp=_somar([l.capacidade_kwp for l in linhas]),
        perdas_paradas_kwh=_somar([l.perdas_paradas_kwh for l in linhas]),
    )
    if com_capacidade:
        energia = sum(l.energia_comparavel_kwh for l in com_capacidade)  # type: ignore[misc]
        capacidade = sum(l.capacidade_kwp for l in com_capacidade)  # type: ignore[misc]
        # Numerador e denominador saem JUNTOS com a razão: é o que permite à tela imprimir
        # os três e o leitor refazer a conta na cabeça sem chegar a um quarto número.
        bloco.totais.energia_comparavel_kwh = round(energia, 2)
        bloco.totais.capacidade_comparavel_kwp = round(capacidade, 2)
        bloco.totais.produtividade_kwh_kwp = round(energia / capacidade, 2) if capacidade else None

    def _motivo(l: UsinaEnergiaOut, falta: str) -> str:
        return l.motivo or falta

    # A ordem é a da tela: `ORDENACAO_PADRAO` é produtividade, e não energia — abrir por
    # energia entregaria todo dia o mesmo pódio, o das usinas maiores, e a pergunta "qual
    # rende melhor" nunca chegaria a ser feita.
    bloco.rankings = [
        _ranking(
            "produtividade",
            [(l.id, l.nome, l.produtividade_kwh_kwp, None,
              _motivo(l, "sem capacidade instalada declarada")) for l in linhas],
        ),
        _ranking(
            "energia",
            [(l.id, l.nome, l.energia_comparavel_kwh, None,
              _motivo(l, "sem geração medida no período")) for l in linhas],
        ),
        # `PERGUNTAS` ainda não nomeia o PR: o texto é local até que ela o faça.
        _ranking(
            "pr",
            [(l.id, l.nome, l.pr_pct, None,
              _motivo(l, "sem PR (o período não tem irradiância medida)")) for l in linhas],
            titulo="Performance Ratio",
            pergunta="Qual usina converte melhor o sol que recebeu?",
            unidade="%",
            nota="Sem POA medida não há PR — a usina sai do ranking, não vai para o fim dele.",
        ),
    ]
    assert bloco.rankings[0].chave == regua.ORDENACAO_PADRAO
    return bloco, janela


# ── manutenção ──────────────────────────────────────────────────────────────


def _contar_cronograma(cro: CronogramaOut, meses: set[str]) -> dict[str, int] | None:
    """As contagens do cronograma DENTRO da janela, ou `None` sem versão consolidada.

    `status` nulo cobre os dois casos em que não há o que contar — o contrato não tem
    cronograma publicado, ou o meuPlano não respondeu — e nos dois a resposta é "não sei",
    nunca "zero". Os meses são comparados como texto (`YYYY-MM`), porque a âncora do
    contrato pode não ser janeiro; e mês do cronograma fora da janela pedida não entra,
    que é o recorte de vigência que impede o "13 de 270" de voltar.
    """
    if cro.status is None:
        return None
    previsto = feitas = dispensadas = atrasadas = no_prazo = 0
    for linha in cro.linhas:
        for celula in linha.meses:
            if celula.mes not in meses:
                continue
            previsto += celula.previsto
            feitas += int(celula.feito)
            dispensadas += int(celula.dispensado)
            atrasadas += int(celula.atrasado)
            # `azul` = previsto e ainda no prazo. É CONTADO para ser DECLARADO fora da
            # conta (ver `regua.cumprimento`), nunca para entrar no denominador: lá dentro
            # ele acusaria o prestador de não ter feito o que ainda não venceu.
            if celula.estado == "azul":
                no_prazo += celula.previsto or 1
    return {
        "previsto": previsto,
        "feitas": feitas,
        "dispensadas": dispensadas,
        "atrasadas": atrasadas,
        "no_prazo": no_prazo,
    }


async def _manutencao_da_usina(
    link: PlantLink, meses: set[str], db: Session, usuario: User
) -> UsinaManutencaoOut:
    """Cronograma, ordens e pendências de UMA usina — em paralelo, cada um falhando por
    conta própria. O cronograma sem versão não apaga a contagem de OS."""
    linha = UsinaManutencaoOut(id=link.id, nome=link.nome)
    cro, ordens, pend = await asyncio.gather(
        cronograma_da_usina(usina_id=link.id, db=db, usuario=usuario),
        listar_ordens(usina_id=link.id, limite=300, db=db, usuario=usuario),
        listar_pendencias(usina_id=link.id, db=db, usuario=usuario),
        return_exceptions=True,
    )

    motivos: list[str] = []
    if (falha := _falha(cro)) is not None:
        motivos.append(f"Cronograma: {falha}")
    else:
        linha.contrato = cro.contrato
        linha.contrato_id = cro.contrato_id
        contagens = _contar_cronograma(cro, meses)
        if contagens is None:
            motivos.append(cro.aviso or "Cronograma não publicado neste contrato.")
        else:
            conta = regua.cumprimento(
                contagens["feitas"], contagens["dispensadas"], contagens["atrasadas"],
                no_prazo=contagens["no_prazo"],
            )
            linha.previsto = contagens["previsto"]
            linha.feitas = conta.feito
            linha.dispensadas = conta.dispensado
            linha.atrasadas = conta.atrasado
            linha.denominador = conta.denominador
            linha.cumprimento_pct = conta.pct
            linha.cumprimento_rotulo = conta.rotulo
            linha.fora_da_conta = conta.excluidos

    if (falha := _falha(ordens)) is not None:
        motivos.append(f"Ordens: {falha}")
    elif ordens.total is not None:
        linha.os_em_andamento = sum(
            1 for o in ordens.ordens if (o.status or "").strip().upper() in EM_CURSO
        )
    elif ordens.aviso:
        motivos.append(f"Ordens: {ordens.aviso}")

    if (falha := _falha(pend)) is not None:
        motivos.append(f"Pendências: {falha}")
    elif pend.abertas is not None:
        abertas = [p for p in pend.pendencias if (p.status or "").strip().upper() not in CONCLUIDA]
        linha.pendencias_abertas = pend.abertas
        linha.pendencias_vencidas = pend.prazo_vencido
        linha.pendencias_cobradas = sum(1 for p in abertas if p.cobrada_pelo_cliente)
        linha.pendencias_criticas = sum(
            1 for p in abertas if (p.criticidade or "").strip().lower() == "critica"
        )
    elif pend.aviso:
        motivos.append(f"Pendências: {pend.aviso}")

    linha.motivo = " · ".join(motivos) or None
    return linha


async def _bloco_manutencao(
    links: list[PlantLink], meses: set[str], db: Session, usuario: User
) -> BlocoManutencaoOut:
    bloco = BlocoManutencaoOut()
    com_manutencao = [l for l in links if l.mp_usina_id]
    linhas: list[UsinaManutencaoOut] = [
        UsinaManutencaoOut(
            id=l.id, nome=l.nome, motivo="Esta usina não tem manutenção contratada."
        )
        for l in links
        if not l.mp_usina_id
    ]
    if com_manutencao:
        linhas.extend(
            await asyncio.gather(
                *(_manutencao_da_usina(l, meses, db, usuario) for l in com_manutencao)
            )
        )
    linhas.sort(key=lambda u: u.nome)
    bloco.usinas = linhas
    bloco.meses = sorted(meses)
    bloco.rotulo = regua.rotulo_de_meses(bloco.meses)

    # Só entra nos totais quem tem cronograma consolidado — a usina sem contrato publicado
    # apareceria como "0 atrasadas", que se lê como "está tudo em dia".
    com_cronograma = [l for l in linhas if l.denominador is not None]
    conta = regua.cumprimento(
        _somar_inteiros([l.feitas for l in com_cronograma]) or 0,
        _somar_inteiros([l.dispensadas for l in com_cronograma]) or 0,
        _somar_inteiros([l.atrasadas for l in com_cronograma]) or 0,
    )
    bloco.totais = TotaisManutencaoOut(
        usinas_no_total=len(com_cronograma),
        previsto=_somar_inteiros([l.previsto for l in com_cronograma]),
        feitas=conta.feito if com_cronograma else None,
        dispensadas=conta.dispensado if com_cronograma else None,
        atrasadas=conta.atrasado if com_cronograma else None,
        denominador=conta.denominador if com_cronograma else None,
        cumprimento_pct=conta.pct if com_cronograma else None,
        cumprimento_rotulo=conta.rotulo if com_cronograma else None,
        os_em_andamento=_somar_inteiros([l.os_em_andamento for l in linhas]),
        pendencias_abertas=_somar_inteiros([l.pendencias_abertas for l in linhas]),
        pendencias_vencidas=_somar_inteiros([l.pendencias_vencidas for l in linhas]),
    )

    def _motivo(l: UsinaManutencaoOut, falta: str) -> str:
        return l.motivo or falta

    bloco.rankings = [
        # Absoluto de propósito (`PERGUNTAS["atraso"]`): o percentual sozinho premia o
        # contrato pequeno, e uma usina com 2 de 4 atrasadas (50 %) não é pior do que uma
        # com 30 de 300 (10 %). `maior_e_melhor=False` — aqui mais é pior.
        _ranking(
            "atraso",
            [(l.id, l.nome, float(l.atrasadas) if l.atrasadas is not None else None, None,
              _motivo(l, "sem cronograma consolidado")) for l in linhas],
            maior_e_melhor=False,
        ),
        _ranking(
            "cumprimento",
            [(l.id, l.nome, l.cumprimento_pct, l.denominador,
              _motivo(l, "sem cronograma consolidado")) for l in linhas],
            titulo="Cumprimento do cronograma",
            pergunta="Que fatia do que já era cobrável foi executada?",
            unidade="%",
            nota=(
                "Executadas sobre executadas + dispensadas + atrasadas. O que ainda está "
                "no prazo fica fora da conta, e o denominador vem sempre ao lado."
            ),
            maior_e_melhor=False,
        ),
        _ranking(
            "pendencias_vencidas",
            [(l.id, l.nome,
              float(l.pendencias_vencidas) if l.pendencias_vencidas is not None else None,
              None, _motivo(l, "as pendências não responderam")) for l in linhas],
            titulo="Pendências com prazo vencido",
            pergunta="Onde o prazo combinado já passou?",
            unidade="pendências",
            maior_e_melhor=False,
        ),
    ]
    return bloco


# ── rota ────────────────────────────────────────────────────────────────────


@router.get("/comparativo", response_model=ComparativoOut)
async def comparativo(
    de: str | None = None,
    ate: str | None = None,
    blocos: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ComparativoOut:
    """As usinas desta pessoa comparadas no período — geração, manutenção, ou as duas.

    **Não existe parâmetro de usina.** O conjunto comparado é sempre `usinas_do_usuario`;
    não há id vindo pela rede que possa acrescentar uma usina alheia à comparação, nem
    sequer para ela sair "vazia" — o que já entregaria o nome de uma usina de outro dono.

    `de`/`ate` ausentes = o mês corrente até hoje, que é a mesma janela de
    `/plants/{id}/desempenho?recorte=mes` — as duas telas caem na mesma entrada do cache do
    upstream. `blocos` pede uma família só (`energia` ou `manutencao`), do jeito que o menu
    do portal já separa: quem cobra kWh não abre OS, e a família de Geração não tem por que
    esperar as cinco idas por usina que a manutenção custa.
    """
    inicio, fim, truncada = _periodo(de, ate)
    pedidos = _blocos_pedidos(blocos)
    meses = _meses_entre(_chave_mes(inicio), _chave_mes(fim))
    links = sorted(usinas_do_usuario(db, usuario), key=lambda l: l.nome)

    # Sem o bloco de energia não há como saber quais meses cada usina mediu: a janela
    # declarada é a PEDIDA, e a tela não afirma uma interseção que ninguém conferiu.
    janela = JanelaOut(
        de=inicio.isoformat(), ate=fim.isoformat(), meses=meses, meses_comuns=meses,
        rotulo=regua.rotulo_de_meses(meses), truncada_em_hoje=truncada,
    )
    saida = ComparativoOut(janela=janela, usinas_no_escopo=len(links))
    if not links:
        saida.aviso = "Você ainda não tem usina liberada."
        if "energia" in pedidos:
            saida.energia = BlocoEnergiaOut()
        if "manutencao" in pedidos:
            saida.manutencao = BlocoManutencaoOut()
        return saida

    # Os dois blocos em paralelo: um deles fora do ar não segura o outro na tela.
    tarefas: list[Any] = []
    if "energia" in pedidos:
        tarefas.append(_bloco_energia(links, inicio, fim, meses, db, truncada))
    if "manutencao" in pedidos:
        tarefas.append(_bloco_manutencao(links, set(meses), db, usuario))
    resultados = list(await asyncio.gather(*tarefas))

    if "energia" in pedidos:
        saida.energia, saida.janela = resultados.pop(0)
    if "manutencao" in pedidos:
        saida.manutencao = resultados.pop(0)

    return saida
