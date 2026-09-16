"""O telefone entra de qualquer jeito e sai de um jeito só.

O que estes testes protegem: o mesmo número digitado de cinco formas tem de virar UMA linha.
Sem isso, "(16) 99999-8888" e "+5516999998888" seriam dois destinos, e o dia do envio
descobriria isso do pior jeito — mandando duas vezes, ou nenhuma.
"""

import pytest

from app.core.telefone import TelefoneInvalido, e_celular, exibir, normalizar


@pytest.mark.parametrize(
    "digitado",
    [
        "16999998888",
        "+55 16 99999-8888",
        "5516999998888",
        "(16) 9 9999-8888",
        "  16 99999 8888  ",
    ],
)
def test_todas_as_grafias_do_mesmo_celular_viram_o_mesmo_numero(digitado):
    assert normalizar(digitado) == "+5516999998888"


def test_celular_antigo_de_oito_digitos_ganha_o_nono():
    """Número de 2015 continua circulando em cadastro — o 9 na frente é o que ele virou."""
    assert normalizar("(16) 9999-8888") == "+5516999998888"


def test_fixo_nao_ganha_nono_digito():
    """Fixo começa em 2-5 e tem oito dígitos. Acrescentar o 9 criaria um número inexistente."""
    assert normalizar("(16) 3372-1234") == "+551633721234"
    assert e_celular("+551633721234") is False


def test_celular_e_reconhecido_como_celular():
    assert e_celular("+5516999998888") is True


def test_vazio_vira_nada():
    """Apagar o telefone é legítimo: o cliente pede para sair e o campo volta a ficar vazio."""
    assert normalizar(None) is None
    assert normalizar("   ") is None


@pytest.mark.parametrize(
    "digitado",
    [
        "99998888",          # sem DDD
        "16 9999",           # curto demais
        "551699999888899",   # longo demais
        "(00) 99999-8888",   # DDD que não existe
        "telefone",          # sem dígito nenhum
    ],
)
def test_o_que_nao_dá_para_normalizar_é_recusado(digitado):
    """Recusar é melhor que adivinhar: o gestor corrige na hora, em vez de descobrir no envio."""
    with pytest.raises(TelefoneInvalido):
        normalizar(digitado)


def test_exibicao_volta_ao_formato_que_se_lê():
    assert exibir("+5516999998888") == "(16) 9 9999-8888"
    assert exibir("+551633721234") == "(16) 3372-1234"
    assert exibir(None) is None
