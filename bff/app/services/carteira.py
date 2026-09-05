"""A régua da CARTEIRA — comparar usinas sem acusar a usina errada.

Comparar sete usinas é fácil de fazer e fácil de fazer errado. As três armadilhas são
sempre as mesmas, e todas produzem um número que *parece* certo:

1. **Capacidade diferente.** Somar kWh e ordenar coroa a maior usina, sempre. Quem "gera
   mais" e quem "rende melhor" são DUAS perguntas, e cada uma tem a sua régua: energia
   absoluta (kWh) e produtividade (kWh/kWp). Aqui elas são nomeadas em `PERGUNTAS`, para
   a tela não inventar o texto e o cliente saber qual está lendo.
2. **Data de entrada diferente.** Porto Ferreira mede desde junho; comparar o ano dela
   com o ano de quem mede desde janeiro faz a comparação parecer com o ano das duas e ser
   o ano de uma só. `janela_comum` corta todas ao mesmo período — a interseção dos meses
   REALMENTE medidos — e diz, por escrito, qual usina encolheu o período.
3. **Ausência lida como zero.** Usina sem PR não é usina com PR zero; ela é usina sem PR.
   `ranking` a deixa FORA da lista em vez de a jogar no último lugar, e `pct_em_dia`
   devolve `None` — nunca `0.0` — quando não há denominador.

Tudo aqui é **função pura**: sem HTTP, sem banco, sem `datetime.now()`. Quem compõe é o
endpoint da carteira, que chama `desempenho_da_usina`/`cronograma_da_usina` como funções
e entrega os números prontos a estas réguas. É o mesmo desenho de `resumo.py`, e é o que
permite testar a parte perigosa — a aritmética da comparação — sem subir aplicação.

⚠️ **Uma divergência deliberada com `plants._meses_medidos`**, documentada em
`_meses_medidos_de_um`: aqui o mês zerado NÃO conta como medido. É a diferença entre a
janela comum funcionar e ela mentir.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PERGUNTAS",
    "ORDENACAO_PADRAO",
    "Pergunta",
    "Cumprimento",
    "JanelaComum",
    "PostoDoRanking",
    "QuemEncolheu",
    "cumprimento",
    "janela_comum",
    "meses_medidos_por_usina",
    "pct_em_dia",
    "ranking",
    "rotulo_de_meses",
    "rotulos",
]


# ── as duas perguntas (e a terceira, da manutenção) ─────────────────────────


@dataclass(frozen=True)
class Pergunta:
    """O texto de UMA pergunta da carteira, escrito num lugar só.

    A tela não redige nenhuma destas frases: se cada tela escrever a sua, "produtividade"
    vira "eficiência" numa e "rendimento" noutra, e o cliente passa a achar que são três
    números diferentes.
    """

    #: Identificador estável, usado na URL (`?ordenar=produtividade`).
    chave: str
    #: A pergunta do cliente, na voz dele.
    pergunta: str
    #: O rótulo da coluna/eixo.
    rotulo: str
    #: A unidade, ou `None` quando é contagem.
    unidade: str | None
    #: Por que esta régua existe — a frase que desarma a leitura errada.
    nota: str
    #: `True` quando o maior valor é o melhor. Atraso é o contrário.
    maior_e_melhor: bool = True


PERGUNTAS: dict[str, Pergunta] = {
    "energia": Pergunta(
        chave="energia",
        pergunta="Qual usina gera mais?",
        rotulo="Energia gerada",
        unidade="kWh",
        nota=(
            "Volume absoluto: a usina maior gera mais por ser maior. "
            "Para saber qual rende melhor, ordene por produtividade."
        ),
    ),
    "produtividade": Pergunta(
        chave="produtividade",
        pergunta="Qual usina rende melhor?",
        rotulo="Produtividade",
        unidade="kWh/kWp",
        nota=(
            "Energia dividida pela capacidade instalada — é o que permite comparar "
            "usinas de tamanhos diferentes. Ainda contém o sol de cada lugar: "
            "veja a irradiação ao lado antes de concluir."
        ),
    ),
    "atraso": Pergunta(
        chave="atraso",
        pergunta="Qual usina está mais atrasada na manutenção?",
        rotulo="Atividades atrasadas",
        unidade=None,
        nota=(
            "Contagem absoluta, que não depende do tamanho do contrato. "
            "O percentual em dia vem ao lado, sempre com o denominador."
        ),
        maior_e_melhor=False,
    ),
}

#: A carteira abre ordenada por PRODUTIVIDADE, não por energia. Abrir por energia
#: entregaria todo dia o mesmo pódio — o das usinas maiores — e a pergunta "qual rende
#: melhor" nunca seria feita.
ORDENACAO_PADRAO = "produtividade"


def rotulos() -> dict[str, Pergunta]:
    """As perguntas da carteira, para a tela e o app lerem do servidor.

    Devolve uma cópia rasa: `Pergunta` é congelado, mas o dicionário do módulo não pode
    ser mutável por quem consome — um `pop()` distraído no endpoint apagaria a coluna
    para todo mundo.
    """
    return dict(PERGUNTAS)


# ── leitura dos números que chegam do upstream ──────────────────────────────


def _numero(valor: Any) -> float | None:
    """Texto/decimal do upstream → `float`; qualquer outra coisa é ausência.

    Cópia deliberada de `plants._numero`. Vive aqui para este módulo não importar a
    camada de rota (FastAPI + banco) só para converter número — o teste de paridade
    guarda as duas implementações juntas.
    """
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _ranqueavel(valor: Any) -> float | None:
    """O valor entra no ranking, ou não entra de jeito nenhum.

    Mais estrito que `_numero` em dois pontos, e os dois já morderam:
    `bool` é `int` em Python (`True` ordenaria como 1) e `NaN` não é igual nem a si
    mesmo — num `sorted` ele embaralha a lista inteira sem levantar erro, e o pódio sai
    aleatório sem ninguém perceber.
    """
    if isinstance(valor, bool) or valor is None:
        return None
    if not isinstance(valor, (int, float)):
        return None
    numero = float(valor)
    if math.isnan(numero) or math.isinf(numero):
        return None
    return numero


def _contagem(valor: Any) -> int | None:
    """Contagem inteira e não-negativa, ou ausência.

    Contagem negativa é defeito de quem produziu o número, não dado: em vez de propagar
    um percentual impossível, a régua devolve ausência e a tela mostra travessão.
    """
    if isinstance(valor, bool) or not isinstance(valor, int):
        return None
    return valor if valor >= 0 else None


# ── meses realmente medidos ─────────────────────────────────────────────────

#: Meses em português — os mesmos de `plants._MES_CURTO`, para os dois lados do portal
#: escreverem "abr a set de 2026" com as mesmas três letras.
_MES_CURTO = ("jan", "fev", "mar", "abr", "mai", "jun",
              "jul", "ago", "set", "out", "nov", "dez")


def _resumo_por_mes(relatorio: Any) -> dict[str, dict[str, Any]]:
    """`monthly_summaries[]` → `{'YYYY-MM': linha}`. Mês ausente é ausência."""
    saida: dict[str, dict[str, Any]] = {}
    if not isinstance(relatorio, dict):
        return saida
    linhas = relatorio.get("monthly_summaries")
    if not isinstance(linhas, list):
        return saida
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        mes = linha.get("month")
        if isinstance(mes, str) and len(mes) >= 7:
            saida[mes[:7]] = linha
    return saida


def _meses_medidos_de_um(relatorio: Any, meses: Sequence[str]) -> list[str] | None:
    """Dos meses pedidos, os que ESTA usina realmente mediu — ou `None` se não dá para saber.

    ⚠️ **Mais estrito que `plants._meses_medidos`, de propósito.** Lá o mês conta como
    medido quando o campo `generation_kwh` existe; aqui ele precisa existir **e ser maior
    que zero**. A diferença não é preciosismo: o rollup do upstream fabrica
    `generation_kwh: 0.0` para os meses ANTERIORES ao início da série — Porto Ferreira,
    que mede desde junho, recebe janeiro a maio zerados. `plants._meses_medidos` os
    aceita (e por isso o painel precisou do filtro extra de `_janela_do_acumulado`).

    Se a carteira herdasse essa leniência, a janela comum de sete usinas daria sempre o
    intervalo inteiro, Porto Ferreira entraria com cinco meses de zero no numerador e a
    comparação diria que ela rende um terço das irmãs. A janela comum existe exatamente
    para esse caso; aceitar o zero fabricado a desligaria em silêncio.

    Uma usina fotovoltaica com medição viva não fecha um mês inteiro em 0,000 kWh — nem
    em dezembro, nem parada. Um mês zerado é medidor mudo, e "não sei" é a leitura
    honesta dele.

    Três respostas, e elas são diferentes:

    * `None`  — o upstream não mandou `monthly_summaries`: **não sabemos** quais meses
      ela cobriu. Não constrange a janela; a tela avisa.
    * `[]`    — veio detalhe e nenhum mês tem geração: ela **não mediu nada** no período
      e fica fora da comparação.
    * lista   — os meses medidos, na ordem pedida.
    """
    por_mes = _resumo_por_mes(relatorio)
    if not por_mes:
        return None
    medidos: list[str] = []
    for mes in meses:
        valor = _numero((por_mes.get(mes) or {}).get("generation_kwh"))
        if valor is not None and valor > 0:
            medidos.append(mes)
    return medidos


def meses_medidos_por_usina(
    relatorios: Mapping[str, Any], meses: Sequence[str]
) -> dict[str, list[str] | None]:
    """`{usina: relatório do range}` → `{usina: meses medidos}`, preservando "não sei".

    O valor é `None` quando o upstream não mandou o detalhe mensal daquela usina — e
    `None` **não é** lista vazia: uma quer dizer "não sabemos", a outra "não mediu nada",
    e `janela_comum` trata as duas de formas diferentes. Fundi-las faria uma usina cujo
    detalhe falhou desaparecer da comparação como se estivesse desligada.
    """
    return {nome: _meses_medidos_de_um(relatorio, meses) for nome, relatorio in relatorios.items()}


def rotulo_de_meses(meses: Sequence[str]) -> str | None:
    """`['2026-04', …, '2026-09']` → "abr a set de 2026". Vazio → `None`.

    Os três formatos são os de `plants._rotulo_de_meses` — mês único, mesmo ano, e
    virada de ano — com **um acréscimo**: quando a lista tem BURACO, o rótulo diz qual.
    A interseção de várias usinas fura com facilidade (basta uma delas perder maio), e
    "abr a set" sobre cinco meses afirmaria seis. O buraco é escrito, não escondido.
    """
    limpos = sorted({m[:7] for m in meses if isinstance(m, str) and len(m) >= 7})
    if not limpos:
        return None
    primeiro, ultimo = limpos[0], limpos[-1]
    nome = lambda c: _MES_CURTO[int(c[5:7]) - 1]  # noqa: E731
    if primeiro == ultimo:
        base = f"{nome(primeiro)} de {primeiro[:4]}"
    elif primeiro[:4] == ultimo[:4]:
        base = f"{nome(primeiro)} a {nome(ultimo)} de {ultimo[:4]}"
    else:
        base = f"{nome(primeiro)}/{primeiro[:4]} a {nome(ultimo)}/{ultimo[:4]}"

    faltando = [m for m in _intervalo_entre(primeiro, ultimo) if m not in set(limpos)]
    if faltando:
        return f"{base} (sem {', '.join(nome(m) for m in faltando)})"
    return base


def _intervalo_entre(primeiro: str, ultimo: str) -> list[str]:
    """Todos os "YYYY-MM" de `primeiro` a `ultimo`, inclusive."""
    ano, mes = int(primeiro[:4]), int(primeiro[5:7])
    fim = (int(ultimo[:4]), int(ultimo[5:7]))
    saida: list[str] = []
    while (ano, mes) <= fim:
        saida.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return saida


@dataclass(frozen=True)
class QuemEncolheu:
    """Uma usina que tirou meses da janela comum, com o tamanho da mordida."""

    usina: str
    #: Meses que ela mediu, dentro do intervalo pedido.
    meses_medidos: int
    #: Meses que as outras têm e ela não — o que ela custou à comparação.
    meses_faltando: int


@dataclass(frozen=True)
class JanelaComum:
    """O período em que TODAS as usinas comparadas têm medição — e o que ficou de fora."""

    #: A interseção, ordenada. Vazia quando não há período comum.
    meses: list[str] = field(default_factory=list)
    #: "abr a set de 2026", ou `None` quando não há janela.
    rotulo: str | None = None
    #: Quem encolheu o período, da mordida maior para a menor.
    encolheram: list[QuemEncolheu] = field(default_factory=list)
    #: Usinas sem um único mês medido: ficam FORA da comparação (não viram zero).
    fora: list[str] = field(default_factory=list)
    #: Usinas cujo detalhe mensal não veio: entram, mas sem confirmar a cobertura.
    sem_detalhe: list[str] = field(default_factory=list)
    #: A frase que a tela imprime. Nunca `None` quando algo foi recortado ou excluído.
    aviso: str | None = None
    #: Quantas usinas a janela cobre — o cabeçalho dos totais diz "de N usinas", porque
    #: um total que não diz de quantas usinas fala é um número sem denominador.
    comparaveis: int = 0


def janela_comum(
    meses_por_usina: Mapping[str, Sequence[str] | None],
    *,
    intervalo: Sequence[str] | None = None,
) -> JanelaComum:
    """A interseção dos meses medidos — o único recorte em que comparar é honesto.

    Recebe o que `meses_medidos_por_usina` devolve. `intervalo` é o período que o cliente
    pediu; serve para a frase dizer "5 dos 12 meses", que é o que dá tamanho ao recorte.

    Quatro decisões, e cada uma existe por um jeito específico de mentir:

    * **Usina sem nenhum mês medido não zera a janela.** Se ela entrasse na interseção, o
      conjunto vazio dela apagaria o período de todas as outras e a tela abriria em
      branco por causa de uma usina desligada. Ela sai para `fora`, com aviso.
    * **Usina sem detalhe mensal (`None`) não constrange nada.** "Não sabemos" não é
      "não tem"; ela entra na comparação e a tela diz que a cobertura dela não foi
      conferida.
    * **A interseção pode ser vazia com todo mundo medindo** (janelas disjuntas). Nesse
      caso a resposta é "não há período comum", por escrito — não uma lista vazia muda.
    * **Quem encolheu é nomeado.** Sem o nome, o cliente lê "abr a set" e conclui que o
      portal perdeu dados; com o nome, ele entende que uma usina entrou depois.
    """
    participantes: dict[str, list[str]] = {}
    fora: list[str] = []
    sem_detalhe: list[str] = []

    for nome, meses in meses_por_usina.items():
        if meses is None:
            sem_detalhe.append(nome)
            continue
        if isinstance(meses, str):
            # `str` É uma `Sequence[str]`, então passar "2026-01" no lugar de ["2026-01"]
            # não é erro de tipo: a régua iteraria os CARACTERES, descartaria todos por
            # serem curtos e mandaria a usina para `fora` — ela sumiria da comparação com
            # a etiqueta "sem medição no período". Erro de quem chama grita aqui.
            raise TypeError(
                f"meses de {nome!r} vieram como texto; a régua espera uma lista de 'YYYY-MM'"
            )
        limpos = sorted({m[:7] for m in meses if isinstance(m, str) and len(m) >= 7})
        if limpos:
            participantes[nome] = limpos
        else:
            fora.append(nome)

    pedidos = sorted({m[:7] for m in (intervalo or []) if isinstance(m, str) and len(m) >= 7})

    if not participantes:
        # Ninguém para intersectar. Se alguém entrou sem detalhe, o intervalo pedido é a
        # melhor janela disponível — é o mesmo caminho de `plants`: sem detalhe, vale o
        # intervalo inteiro. Sem ninguém, não há janela nenhuma.
        meses_finais = list(pedidos) if sem_detalhe else []
        return JanelaComum(
            meses=meses_finais,
            rotulo=rotulo_de_meses(meses_finais),
            fora=fora,
            sem_detalhe=sem_detalhe,
            aviso=_aviso_da_janela(meses_finais, [], fora, sem_detalhe, pedidos, len(participantes)),
            comparaveis=len(sem_detalhe),
        )

    uniao: set[str] = set()
    for lista in participantes.values():
        uniao |= set(lista)
    intersecao = set.intersection(*(set(v) for v in participantes.values()))
    meses_finais = sorted(intersecao)

    encolheram = sorted(
        (
            QuemEncolheu(
                usina=nome,
                meses_medidos=len(lista),
                meses_faltando=len(uniao - set(lista)),
            )
            for nome, lista in participantes.items()
            if uniao - set(lista)
        ),
        key=lambda q: (-q.meses_faltando, q.meses_medidos),
    )

    return JanelaComum(
        meses=meses_finais,
        rotulo=rotulo_de_meses(meses_finais),
        encolheram=encolheram,
        fora=fora,
        sem_detalhe=sem_detalhe,
        aviso=_aviso_da_janela(
            meses_finais, encolheram, fora, sem_detalhe, pedidos, len(participantes)
        ),
        comparaveis=len(participantes) + len(sem_detalhe),
    )


def _aviso_da_janela(
    meses: Sequence[str],
    encolheram: Sequence[QuemEncolheu],
    fora: Sequence[str],
    sem_detalhe: Sequence[str],
    pedidos: Sequence[str],
    participantes: int,
) -> str | None:
    """A frase da janela — nomeando quem encolheu e quem saiu.

    `None` só quando nada foi recortado nem excluído: aí a comparação cobre o período
    pedido inteiro e não há o que explicar.
    """
    partes: list[str] = []

    if not meses:
        if participantes:
            partes.append(
                "Não há período comum: as usinas selecionadas não têm um único mês "
                "medido em comum, e comparar somas de períodos diferentes daria um "
                "ranking sem significado."
            )
        else:
            partes.append("Nenhuma usina com medição no período selecionado.")
    elif pedidos and len(meses) < len(pedidos):
        frase = (
            f"Comparação feita na janela comum das usinas — {rotulo_de_meses(meses)}, "
            f"{len(meses)} dos {len(pedidos)} meses do período."
        )
        if encolheram:
            maior = encolheram[0]
            frase += (
                f" Quem mais encolheu o período foi {maior.usina}, "
                f"com {maior.meses_medidos} mês(es) medido(s)."
            )
        partes.append(frase)
    elif encolheram:
        partes.append(
            f"Janela comum: {rotulo_de_meses(meses)}. "
            f"Quem mais encolheu o período foi {encolheram[0].usina}."
        )

    if fora:
        partes.append(
            f"Fora da comparação por não ter medição no período: {', '.join(sorted(fora))}."
        )
    if sem_detalhe:
        partes.append(
            "Sem detalhe mensal do monitoramento, a cobertura não pôde ser conferida em: "
            f"{', '.join(sorted(sem_detalhe))}."
        )
    return " ".join(partes) if partes else None


# ── ranking ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PostoDoRanking:
    """Uma linha classificada: quem, quanto, em que lugar."""

    #: A identidade da linha (nome ou id da usina), como veio.
    chave: Any
    valor: float
    #: 1 = melhor. Empate divide a posição (1, 1, 3).
    posicao: int
    #: `True` quando outra usina tem exatamente o mesmo valor.
    empatado: bool = False


def ranking(
    chave: str,
    linhas: Sequence[Mapping[str, Any]],
    *,
    identidade: str = "usina",
    maior_e_melhor: bool = True,
) -> list[PostoDoRanking]:
    """Ordena as linhas por `chave` — **excluindo quem não tem o número**.

    A regra que dá nome a este módulo: *ausência nunca é ordenada como zero*. Uma usina
    sem PR cadastrado apareceria em último lugar num ranking de PR, e o cliente leria
    "esta usina tem o pior PR da carteira" onde o dado correto é "esta usina não tem PR".
    Ela sai da lista; a tela mostra o travessão e o motivo.

    `maior_e_melhor=False` inverte a régua para as perguntas em que mais é pior — o
    ranking de atrasadas da manutenção é o caso.

    **Empate divide a posição** (1, 1, 3). Desempatar por ordem alfabética coroaria uma
    usina por causa da inicial do nome; e desempatar pela ordem em que o upstream
    respondeu faria o pódio mudar entre dois carregamentos da mesma tela.
    """
    candidatos: list[tuple[Any, float]] = []
    for linha in linhas:
        if not isinstance(linha, Mapping):
            continue
        valor = _ranqueavel(linha.get(chave))
        if valor is None:
            continue
        candidatos.append((linha.get(identidade), valor))

    # `sorted` é estável: em empate, a ordem de entrada é preservada — mas a POSIÇÃO
    # publicada é a mesma para os dois, que é o que a tela mostra.
    ordenados = sorted(candidatos, key=lambda par: par[1], reverse=maior_e_melhor)

    quantos = Counter(valor for _, valor in ordenados)
    saida: list[PostoDoRanking] = []
    posicao = 0
    anterior: float | None = None
    for indice, (identificador, valor) in enumerate(ordenados):
        if anterior is None or valor != anterior:
            posicao = indice + 1
            anterior = valor
        saida.append(
            PostoDoRanking(
                chave=identificador,
                valor=valor,
                posicao=posicao,
                empatado=quantos[valor] > 1,
            )
        )
    return saida


# ── cumprimento da manutenção ──────────────────────────────────────────────


def pct_em_dia(feito: Any, dispensado: Any, atrasado: Any) -> float | None:
    """`feito / (feito + dispensado + atrasado)`, em porcentagem — ou `None`.

    O denominador é a decisão inteira desta função, e ele tem duas exclusões e uma
    inclusão, cada uma com motivo:

    * **`no_prazo` fica de fora.** É atividade prevista para um mês que ainda não chegou.
      No denominador, ela acusaria o prestador de não ter feito o que ainda não venceu —
      e o percentual cairia sozinho todo dia 1º, sem ninguém ter deixado de trabalhar.
    * **`sem_ativo` fica de fora.** É um X no cronograma que não cobre equipamento
      nenhum: cadastro NOSSO, não serviço não prestado. Cobrar por ele é cobrar do
      prestador um erro da nossa árvore.
    * **`dispensado` fica DENTRO do denominador e FORA do numerador.** Dispensa é
      combinada e tem motivo, mas não é serviço executado. Somá-la a `feito` — que é o
      que `pct_cumprido` faz do lado do meuPlano — apagaria a diferença entre o que foi
      feito e o que foi perdoado, que é justamente a diferença que o cliente quer ver.

    ⚠️ **Por isso este número NÃO é o `pct_cumprido` do relatório de manutenção**
    (`relatorio.py`, `(executadas + dispensadas) / previstas`). São duas perguntas
    diferentes — "quanto foi executado do que era cobrável" e "quanto do contrato foi
    cumprido" — e é obrigatório que a tela imprima o denominador de cada uma ao lado do
    percentual (use `cumprimento`, que já o monta). Dois percentuais sem denominador na
    mesma tela é exatamente o defeito que produziu "13 de 270" numa aba e "41,9 %" na
    outra, para uma usina sem uma única atividade atrasada.

    Denominador zero devolve `None`, nunca `0.0`: nada cobrável no período é "não se
    aplica", e 0 % se lê como "não fizeram nada".
    """
    f, d, a = _contagem(feito), _contagem(dispensado), _contagem(atrasado)
    if f is None or d is None or a is None:
        return None
    denominador = f + d + a
    if denominador == 0:
        return None
    return round(100.0 * f / denominador, 1)


@dataclass(frozen=True)
class Cumprimento:
    """O percentual em dia COM o denominador e o que ficou de fora dele.

    A tela não deve montar esta frase sozinha: o percentual sem o denominador ao lado é
    a forma mais rápida de a carteira contradizer o relatório de manutenção.
    """

    pct: float | None
    feito: int | None
    dispensado: int | None
    atrasado: int | None
    #: `feito + dispensado + atrasado`, ou `None` quando alguma contagem falta.
    denominador: int | None
    #: "13 de 13" — o que vai ao lado do percentual. "—" quando não há conta.
    rotulo: str
    #: "18 no prazo e 2 sem ativo estão fora da conta", ou `None`.
    excluidos: str | None = None


def cumprimento(
    feito: Any,
    dispensado: Any,
    atrasado: Any,
    *,
    no_prazo: Any = 0,
    sem_ativo: Any = 0,
) -> Cumprimento:
    """`pct_em_dia` embrulhado com o denominador e a frase das exclusões.

    `no_prazo` e `sem_ativo` entram só para serem DECLARADOS — nunca para serem
    somados. Sem essa frase, um contrato com 18 atividades ainda no prazo mostra "100 %"
    e o cliente entende "o ano está fechado", quando o ano mal começou.
    """
    f, d, a = _contagem(feito), _contagem(dispensado), _contagem(atrasado)
    pct = pct_em_dia(feito, dispensado, atrasado)
    denominador = None if (f is None or d is None or a is None) else f + d + a

    rotulo = "—" if (f is None or not denominador) else f"{f} de {denominador}"

    fora: list[str] = []
    np_, sa = _contagem(no_prazo), _contagem(sem_ativo)
    if np_:
        fora.append(f"{np_} ainda no prazo")
    if sa:
        fora.append(f"{sa} sem equipamento cadastrado")
    excluidos = f"{' e '.join(fora)} — fora da conta." if fora else None

    return Cumprimento(
        pct=pct,
        feito=f,
        dispensado=d,
        atrasado=a,
        denominador=denominador,
        rotulo=rotulo,
        excluidos=excluidos,
    )
