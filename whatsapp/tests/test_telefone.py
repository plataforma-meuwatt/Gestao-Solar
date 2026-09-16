"""O número entra de qualquer jeito e sai de um jeito só.

Mesmos casos do teste do BFF, de propósito: a regra é copiada entre os dois serviços (eles
não compartilham código), e testar os dois lados é o que faz uma divergência aparecer em
vermelho em vez de virar mensagem enviada para o número errado.
"""

import pytest

from gateway.core.telefone import TelefoneInvalido, mesma_pessoa, normalizar, para_envio


@pytest.mark.parametrize(
    "digitado",
    ["16999998888", "+55 16 99999-8888", "5516999998888", "(16) 9 9999-8888", "  16 99999 8888  "],
)
def test_todas_as_grafias_viram_o_mesmo_numero(digitado):
    assert normalizar(digitado) == "+5516999998888"


def test_celular_antigo_ganha_o_nono_digito():
    assert normalizar("(16) 9999-8888") == "+5516999998888"


def test_fixo_nao_ganha_nono_digito():
    assert normalizar("(16) 3372-1234") == "+551633721234"


def test_para_envio_tira_o_mais():
    """A Graph recusa o `+`: o campo `to` é só dígitos, com DDI."""
    assert para_envio("+5516999998888") == "5516999998888"


@pytest.mark.parametrize("digitado", ["99998888", "16 9999", "(00) 99999-8888", "telefone"])
def test_o_que_nao_da_para_normalizar_e_recusado(digitado):
    with pytest.raises(TelefoneInvalido):
        normalizar(digitado)


def test_wa_id_sem_nono_digito_casa_com_cadastro_que_tem():
    """A Meta manda o `wa_id` brasileiro às vezes sem o 9 — comparar inteiro não casaria."""
    assert mesma_pessoa("551699998888", "+5516999998888")
    assert mesma_pessoa("5516999998888", "+5516999998888")
    assert not mesma_pessoa("5511999998888", "+5516999998888")
    assert not mesma_pessoa("5516999998888", None)
