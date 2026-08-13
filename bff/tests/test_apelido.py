"""A regra do apelido.

Ele é a identidade: um apelido aceito por engano vira uma segunda conta parecida em vez de
um erro na tela, e ninguém percebe até dois "renans" aparecerem na lista da equipe.
"""

import pytest

from app.core.apelido import ApelidoInvalido, normalizar, sugerir


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("renanmarquezini", "renanmarquezini"),
        ("renan.marquezini", "renan.marquezini"),
        # Caixa e espaço nas pontas são indulgência deliberada: quem digita "Renan " na
        # tela de entrada quis dizer `renan`, e recusar isso seria implicância.
        ("  Renan.Marquezini  ", "renan.marquezini"),
        ("joao_silva", "joao_silva"),
        ("ana-paula", "ana-paula"),
        ("abc", "abc"),
    ],
)
def test_aceita(entrada, esperado):
    assert normalizar(entrada) == esperado


@pytest.mark.parametrize(
    "entrada,pedaco_da_mensagem",
    [
        ("", "Informe"),
        ("   ", "Informe"),
        (None, "Informe"),
        ("ab", "pelo menos"),
        ("x" * 33, "passa de"),
        ("renan marquezini", "espaço"),
        # As pontas e a repetição pegam o erro de digitação que passaria por nome válido.
        (".renan", "letras sem acento"),
        ("renan.", "letras sem acento"),
        ("renan..marquezini", "letras sem acento"),
        ("renan@empresa.com", "letras sem acento"),
        ("renân", "letras sem acento"),
    ],
)
def test_recusa(entrada, pedaco_da_mensagem):
    with pytest.raises(ApelidoInvalido, match=pedaco_da_mensagem):
        normalizar(entrada)


def test_apelidos_parecidos_sao_contas_diferentes():
    """`renanmarquezini` e `renan.marquezini` são o gestor e o cliente — a mesma pessoa em
    dois papéis. O ponto é significativo e não pode ser normalizado para fora."""
    assert normalizar("renanmarquezini") != normalizar("renan.marquezini")


@pytest.mark.parametrize(
    "base,esperado",
    [
        ("renan@splendoroem.com.br", "renan"),
        ("renan.marquezini@empresa.com", "renan.marquezini"),
        ("João Silva", "joao.silva"),
        # Acento vira a letra sem acento, não some: `joão` é `joao`, nunca `joo`.
        ("João", "joao"),
        ("Maria da Conceição", "maria.da.conceicao"),
        ("ab", ""),  # curto demais para virar apelido — a tela deixa o campo em branco
        ("!!!", ""),
    ],
)
def test_sugere(base, esperado):
    assert sugerir(base) == esperado


def test_sugestao_sempre_passa_pela_validacao():
    """A sugestão preenche o campo; o servidor é quem valida. Uma sugestão que o próprio
    validador recusa faria a tela propor algo impossível de salvar."""
    for base in ("João Silva", "renan@splendoroem.com.br", "ANA_PAULA@x.com", "z..z@y.com"):
        proposto = sugerir(base)
        if proposto:
            assert normalizar(proposto) == proposto
