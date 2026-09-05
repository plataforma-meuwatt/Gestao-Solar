"""A régua da carteira — `app/services/carteira.py`.

O que se protege aqui é a aritmética de comparar usinas DIFERENTES: capacidades
diferentes, datas de entrada diferentes e contratos diferentes. Cada teste guarda uma
forma específica de a comparação produzir um ranking que acusa a usina errada — todas
elas plausíveis, nenhuma delas visível na tela depois de pronta.

Nada aqui sobe aplicação nem toca rede: as funções são puras, e é por isso que a parte
perigosa do produto pode ser testada com aritmética, não com fixtures de HTTP.
"""

import math

import pytest

from app.services import carteira

#: O ano inteiro, como o endpoint da carteira o pede.
ANO = [f"2026-{m:02d}" for m in range(1, 13)]


def _meses(inicio: int, fim: int) -> list[str]:
    return [f"2026-{m:02d}" for m in range(inicio, fim + 1)]


def _relatorio(por_mes: dict[str, float | None]) -> dict:
    """Um `generation/range` do mw-api, reduzido ao que a régua lê."""
    return {
        "monthly_summaries": [
            {"month": f"{mes}-01", "generation_kwh": kwh} for mes, kwh in por_mes.items()
        ]
    }


# ── janela comum ───────────────────────────────────────────────────────────


def test_janela_comum_de_tres_usinas_corta_no_periodo_da_mais_nova():
    """Comparar 12 meses de uma com 5 meses de outra e chamar o resultado de "o ano".

    Sem o corte, a usina que entrou em agosto aparece com 5/12 da energia das irmãs e o
    ranking a coloca em último — quando ela pode ser a que mais rende por kWp. A janela
    tem de ser a INTERSEÇÃO do que foi medido, e a tela tem de dizer qual usina a
    encolheu, senão o cliente lê "abr a set" e conclui que o portal perdeu dados.
    """
    janela = carteira.janela_comum(
        {
            "Ribeirão Bonito": _meses(1, 12),
            "Pirapozinho": _meses(4, 12),
            "Porto Ferreira": _meses(8, 12),
        },
        intervalo=ANO,
    )

    assert janela.meses == _meses(8, 12)
    assert len(janela.meses) == 5
    assert janela.rotulo == "ago a dez de 2026"
    assert janela.comparaveis == 3

    # Quem mais encolheu vem primeiro, e é nomeado na frase que a tela imprime.
    assert janela.encolheram[0].usina == "Porto Ferreira"
    assert janela.encolheram[0].meses_medidos == 5
    assert janela.encolheram[0].meses_faltando == 7
    assert [q.usina for q in janela.encolheram] == ["Porto Ferreira", "Pirapozinho"]
    assert "Porto Ferreira" in janela.aviso
    assert "5 dos 12 meses" in janela.aviso


def test_usina_sem_medicao_nenhuma_nao_apaga_a_janela_das_outras():
    """Uma usina desligada zerando a tela inteira.

    Interseção com conjunto vazio é conjunto vazio: se a usina sem medição participasse,
    o período comum das outras seis sumiria e a carteira abriria em branco por causa de
    uma. Ela sai para `fora` — e o motivo é escrito, senão ela simplesmente desaparece
    da lista sem ninguém saber por quê.
    """
    janela = carteira.janela_comum(
        {"Boa Vista": _meses(1, 12), "Nova": _meses(6, 12), "Desligada": []},
        intervalo=ANO,
    )

    assert janela.meses == _meses(6, 12)  # a vazia não encurtou nada
    assert janela.fora == ["Desligada"]
    assert "Desligada" in janela.aviso
    assert janela.comparaveis == 2  # o cabeçalho dos totais fala de 2 usinas, não de 3


def test_sem_detalhe_mensal_nao_e_o_mesmo_que_sem_medicao():
    """Fundir "não sei" com "não tem" faz uma usina sumir por falha do upstream.

    `None` (o upstream não mandou `monthly_summaries`) e `[]` (mandou, e nenhum mês tem
    geração) são respostas diferentes. Se `None` virasse `[]`, a usina cujo detalhe
    falhou seria excluída da comparação como se estivesse parada. Ela entra, e a tela
    declara que a cobertura dela não pôde ser conferida.
    """
    janela = carteira.janela_comum(
        {"Com detalhe": _meses(3, 12), "Sem detalhe": None},
        intervalo=ANO,
    )

    assert janela.sem_detalhe == ["Sem detalhe"]
    assert janela.fora == []
    assert janela.meses == _meses(3, 12)  # o "não sei" não constrange a interseção
    assert "Sem detalhe" in janela.aviso
    assert janela.comparaveis == 2


def test_janelas_disjuntas_dizem_que_nao_ha_periodo_comum():
    """Ranking mudo: lista vazia sem uma linha de explicação.

    Duas usinas com medição em meses que não se cruzam não têm comparação possível.
    Devolver `[]` calado faria a tela mostrar um comparativo vazio, que se lê como
    "o portal quebrou" — quando o correto é dizer que não existe período comum.
    """
    janela = carteira.janela_comum(
        {"Primeiro semestre": _meses(1, 3), "Segundo semestre": _meses(7, 9)},
        intervalo=ANO,
    )

    assert janela.meses == []
    assert janela.rotulo is None
    assert "Não há período comum" in janela.aviso


def test_janela_completa_nao_inventa_aviso():
    """Frase de recorte onde não houve recorte.

    Quando todas mediram o período inteiro, não há nada a explicar — e um aviso
    permanente na tela treina o cliente a ignorar avisos, inclusive os que importam.
    """
    janela = carteira.janela_comum(
        {"A": _meses(1, 12), "B": _meses(1, 12)}, intervalo=ANO
    )

    assert janela.meses == ANO
    assert janela.encolheram == []
    assert janela.aviso is None


def test_meses_como_texto_grita_em_vez_de_sumir_com_a_usina():
    """`str` é uma `Sequence[str]`: passar "2026-01" no lugar de ["2026-01"] não é erro
    de tipo para o Python.

    Sem a guarda, a régua iteraria os CARACTERES, descartaria todos por serem curtos e
    mandaria a usina para `fora` — ela desapareceria da comparação com a etiqueta
    "sem medição no período", que é uma acusação, não um erro de programação visível.
    """
    with pytest.raises(TypeError, match="Sozinha"):
        carteira.janela_comum({"Sozinha": "2026-01"})


# ── quais meses foram realmente medidos ────────────────────────────────────


def test_mes_zerado_pelo_upstream_nao_conta_como_medido():
    """O zero fabricado antes do início da série — o defeito que a janela existe para pegar.

    O rollup do mw-api devolve `generation_kwh: 0.0` para os meses ANTERIORES ao início
    da medição: Porto Ferreira, que mede desde junho, recebe janeiro a maio zerados. Se
    a régua da carteira aceitasse esse zero como medição, a janela comum das sete usinas
    daria sempre o ano inteiro — a janela ficaria ligada e inútil ao mesmo tempo — e
    Porto Ferreira entraria com cinco meses de zero no numerador, rendendo metade das
    irmãs numa comparação que ninguém conseguiria contestar.
    """
    porto = _relatorio(
        {f"2026-{m:02d}": 0.0 for m in range(1, 6)}
        | {f"2026-{m:02d}": 320_000.0 for m in range(6, 13)}
    )

    medidos = carteira.meses_medidos_por_usina({"Porto Ferreira": porto}, ANO)

    assert medidos["Porto Ferreira"] == _meses(6, 12)
    assert "2026-01" not in medidos["Porto Ferreira"]


def test_a_divergencia_com_plants_meses_medidos_e_deliberada():
    """Guarda contra alguém "consertar" a régua da carteira para bater com a de `plants`.

    `plants._meses_medidos` aceita o mês zerado (ele só pergunta se o campo existe) — e
    está certo no contexto dele, onde `_janela_do_acumulado` aplica o filtro extra depois.
    A carteira não tem esse segundo filtro, então a estritude mora na própria régua. Este
    teste prova que as duas discordam DE PROPÓSITO, nomeando o mês em que discordam.
    """
    from app.api.v1 import plants

    porto = _relatorio(
        {"2026-01": 0.0, "2026-06": 310_000.0, "2026-07": 298_000.0}
    )
    meses = ["2026-01", "2026-06", "2026-07"]

    laxo = plants._meses_medidos(porto, meses)
    estrito = carteira.meses_medidos_por_usina({"Porto": porto}, meses)["Porto"]

    assert "2026-01" in laxo, "se plants passou a recusar o zero, revise o comentário desta régua"
    assert "2026-01" not in estrito
    assert estrito == ["2026-06", "2026-07"]


def test_sem_monthly_summaries_a_resposta_e_nulo_e_nao_lista_vazia():
    """Ausência de detalhe respondida como "mediu nada".

    Sem `monthly_summaries` não dá para saber quais meses a usina cobriu. Devolver `[]`
    aqui a mandaria para `fora` da comparação — puni-la por uma falha do upstream.
    """
    medidos = carteira.meses_medidos_por_usina(
        {"Muda": {}, "Sem lista": {"monthly_summaries": None}, "Vazia": _relatorio({"2026-01": 0.0})},
        ANO,
    )

    assert medidos["Muda"] is None
    assert medidos["Sem lista"] is None
    assert medidos["Vazia"] == []  # veio detalhe, e nele não há um mês sequer com geração


def test_rotulo_com_buraco_declara_o_buraco():
    """"abr a jun" afirmando três meses quando são dois.

    A interseção de várias usinas fura com facilidade — basta uma delas perder maio. Um
    rótulo de intervalo esconde o furo e o cliente soma três meses de contrato sobre uma
    conta de dois.
    """
    assert carteira.rotulo_de_meses(["2026-04", "2026-06"]) == "abr a jun de 2026 (sem mai)"
    assert carteira.rotulo_de_meses(["2026-09"]) == "set de 2026"
    assert carteira.rotulo_de_meses(["2025-11", "2025-12", "2026-01"]) == "nov/2025 a jan/2026"
    assert carteira.rotulo_de_meses([]) is None


# ── ranking ────────────────────────────────────────────────────────────────


def test_ranking_de_pr_ignora_usina_com_pr_nulo():
    """Usina sem PR aparecendo em último lugar como se tivesse o pior PR da carteira.

    Ausência ordenada como zero é a mentira mais barata de um comparativo: a linha existe,
    o número existe, e ele diz o contrário do dado. Quem não tem o número sai da lista.
    """
    linhas = [
        {"usina": "A", "pr_pct": 82.4},
        {"usina": "Sem PR", "pr_pct": None},
        {"usina": "C", "pr_pct": 79.1},
    ]

    posicoes = carteira.ranking("pr_pct", linhas)

    assert [p.chave for p in posicoes] == ["A", "C"]
    assert "Sem PR" not in [p.chave for p in posicoes]
    assert [p.posicao for p in posicoes] == [1, 2]
    assert posicoes[0].valor == 82.4


def test_ranking_exclui_usina_cujo_campo_nem_veio():
    """Chave ausente no dicionário lida como zero.

    `linha.get(chave)` devolve `None` tanto para "veio nulo" quanto para "não veio" — e
    os dois casos têm a mesma resposta certa: fora do ranking.
    """
    posicoes = carteira.ranking("produtividade", [{"usina": "A", "produtividade": 118.2}, {"usina": "B"}])

    assert [p.chave for p in posicoes] == ["A"]


def test_empate_divide_a_posicao():
    """Coroar uma usina por causa da inicial do nome, ou da ordem em que o upstream respondeu.

    Dois valores iguais são um empate. Desempatar por alfabeto premia o "A"; desempatar
    pela ordem de resposta faz o pódio mudar entre dois carregamentos da mesma tela.
    """
    posicoes = carteira.ranking(
        "kwh",
        [{"usina": "A", "kwh": 100.0}, {"usina": "B", "kwh": 120.0}, {"usina": "C", "kwh": 100.0}],
    )

    assert [(p.chave, p.posicao) for p in posicoes] == [("B", 1), ("A", 2), ("C", 2)]
    assert posicoes[1].empatado and posicoes[2].empatado
    assert not posicoes[0].empatado


def test_ranking_recusa_nan_e_booleano():
    """`NaN` embaralhando a lista inteira em silêncio, e `True` ordenando como 1.

    `NaN` não é igual nem a si mesmo: dentro de um `sorted` ele não levanta erro — ele
    corrompe a ordem dos vizinhos, e o pódio sai aleatório sem nenhum sinal na tela.
    `bool` é subclasse de `int`, então um campo booleano entraria no ranking valendo 1.
    """
    linhas = [
        {"usina": "A", "v": 10.0},
        {"usina": "NaN", "v": float("nan")},
        {"usina": "Bool", "v": True},
        {"usina": "Inf", "v": float("inf")},
        {"usina": "Texto", "v": "12"},
        {"usina": "B", "v": 20.0},
    ]

    posicoes = carteira.ranking("v", linhas)

    assert [p.chave for p in posicoes] == ["B", "A"]
    assert all(not math.isnan(p.valor) for p in posicoes)


def test_ranking_de_atraso_ordena_do_pior_para_o_melhor():
    """Ranking de manutenção premiando quem tem MAIS atividades atrasadas.

    A régua de "melhor" muda com a pergunta: em energia o maior vence, em atraso o maior
    é o problema. A inversão é do servidor, para as duas telas não a escreverem de jeitos
    diferentes.
    """
    linhas = [{"usina": "A", "atrasadas": 2}, {"usina": "B", "atrasadas": 9}, {"usina": "C", "atrasadas": 0}]

    piores = carteira.ranking("atrasadas", linhas, maior_e_melhor=False)

    assert [p.chave for p in piores] == ["C", "A", "B"]
    assert carteira.PERGUNTAS["atraso"].maior_e_melhor is False


def test_ranking_vazio_quando_ninguem_tem_o_numero():
    """Lista de zeros no lugar de lista vazia.

    Se nenhuma usina tem PR, o ranking de PR não existe — e sete linhas com 0 % seriam
    lidas como sete usinas com o PR no chão.
    """
    assert carteira.ranking("pr_pct", [{"usina": "A", "pr_pct": None}, {"usina": "B", "pr_pct": None}]) == []


# ── cumprimento da manutenção ──────────────────────────────────────────────


def test_pct_em_dia_com_tudo_feito_e_cem():
    """A conta básica do cumprimento."""
    assert carteira.pct_em_dia(13, 0, 0) == 100.0


def test_pct_em_dia_sem_denominador_e_nulo_e_nunca_zero():
    """0 % onde a resposta certa é "não se aplica".

    Contrato sem nada cobrável no período (tudo ainda no prazo, ou cronograma recém
    publicado) tem denominador zero. Devolver `0.0` acusaria o prestador de não ter feito
    nada; a REGRA 0 do produto manda devolver ausência e a tela mostrar travessão.
    """
    assert carteira.pct_em_dia(0, 0, 0) is None


def test_dispensado_entra_no_denominador_e_nunca_no_numerador():
    """Fundir "feito" com "dispensado" — a diferença que o cliente mais quer ver.

    Dispensa é combinada e tem motivo, mas não é serviço executado. Somá-la ao numerador
    (que é o que `pct_cumprido` faz do lado do meuPlano, por responder outra pergunta)
    faria um mês inteiro de dispensas aparecer como 100 % executado.
    """
    assert carteira.pct_em_dia(6, 6, 0) == 50.0
    assert carteira.pct_em_dia(0, 4, 0) == 0.0  # nada feito, e o zero aqui é medido
    assert carteira.pct_em_dia(9, 0, 3) == 75.0


def test_no_prazo_e_sem_ativo_ficam_fora_do_denominador_mas_sao_declarados():
    """O percentual caindo sozinho todo dia 1º, e a cobrança de um erro da nossa árvore.

    `no_prazo` é atividade de um mês que ainda não chegou: no denominador, ela acusa o
    prestador de não ter feito o que ainda não venceu. `sem_ativo` é X de cronograma que
    não cobre equipamento nenhum — cadastro nosso. Nenhum dos dois entra na conta; os
    dois são DECLARADOS, senão "100 %" se lê como "o ano está fechado".
    """
    resultado = carteira.cumprimento(13, 0, 0, no_prazo=18, sem_ativo=2)

    assert resultado.pct == 100.0
    assert resultado.denominador == 13
    assert resultado.rotulo == "13 de 13"
    assert "18 ainda no prazo" in resultado.excluidos
    assert "2 sem equipamento cadastrado" in resultado.excluidos


def test_cumprimento_imprime_o_denominador_ao_lado_do_percentual():
    """Percentual solto na tela — o defeito que produziu "13 de 270" numa aba e "41,9 %" na outra.

    Dois percentuais de cumprimento convivem no portal (este e o `pct_cumprido` do
    relatório) porque respondem a perguntas diferentes. O que impede a contradição é o
    denominador impresso ao lado de cada um; por isso ele sai pronto do servidor.
    """
    resultado = carteira.cumprimento(13, 5, 13)

    assert resultado.pct == 41.9
    assert resultado.rotulo == "13 de 31"
    assert resultado.excluidos is None


def test_cumprimento_sem_contagem_mostra_travessao():
    """"0 de 0" apresentado como resultado, onde não houve medição nenhuma."""
    resultado = carteira.cumprimento(None, None, None)

    assert resultado.pct is None
    assert resultado.denominador is None
    assert resultado.rotulo == "—"


def test_contagem_negativa_vira_ausencia_e_nao_percentual_impossivel():
    """Contagem negativa do upstream virando percentual negativo na cara do cliente."""
    assert carteira.pct_em_dia(-1, 0, 5) is None
    assert carteira.cumprimento(-1, 0, 5).rotulo == "—"


# ── os rótulos das perguntas ───────────────────────────────────────────────


def test_rotulos_nomeia_as_duas_perguntas_da_energia():
    """A tela inventando o texto — e "produtividade" virando "eficiência" numa aba e
    "rendimento" noutra, até o cliente achar que são três números.

    Também trava o padrão de ordenação: abrir por energia entregaria todo dia o mesmo
    pódio (o das usinas maiores) e a pergunta "qual rende melhor" nunca seria feita.
    """
    perguntas = carteira.rotulos()

    assert perguntas["energia"].unidade == "kWh"
    assert perguntas["energia"].pergunta == "Qual usina gera mais?"
    assert perguntas["produtividade"].unidade == "kWh/kWp"
    assert perguntas["produtividade"].pergunta == "Qual usina rende melhor?"
    assert "irradiação" in perguntas["produtividade"].nota
    assert carteira.ORDENACAO_PADRAO == "produtividade"


def test_rotulos_devolve_copia_e_nao_o_catalogo_vivo():
    """Um `pop()` distraído no endpoint apagando a coluna para todos os clientes."""
    carteira.rotulos().pop("energia")

    assert "energia" in carteira.rotulos()


@pytest.mark.parametrize("chave", ["energia", "produtividade", "atraso"])
def test_toda_pergunta_tem_nota_explicando_a_leitura_errada(chave):
    """Rótulo sem a frase que desarma a conclusão apressada.

    "Qual gera mais" sem "a maior gera mais por ser maior" faz o diretor cobrar a usina
    pequena por um número que só descreve o tamanho dela.
    """
    pergunta = carteira.PERGUNTAS[chave]

    assert pergunta.nota.strip()
    assert pergunta.chave == chave
