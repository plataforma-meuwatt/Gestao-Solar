"""Ponte ativa sem credencial diz o que houve — não `'NoneType' object has no attribute 'encode'`.

O caso (04/09/2026): a tela de Energia do portal do cliente, recém-publicada, mostrou em quatro
lugares diferentes a frase **"meuWatt indisponível: 'NoneType' object has no attribute
'encode'"**. O produto do outro lado estava no ar; o que faltava era a credencial gravada aqui.
`decifrar(None)` estourava lá no fundo e o erro atravessava a ponte inteira até o cliente — uma
mensagem que não diz o que aconteceu nem onde se conserta.

O que estes testes protegem:

1. **Sem token e sem senha, a mensagem aponta o conserto** (Painel → Conexões).
2. **A checagem vale para os dois produtos** — o meuPlano tem exatamente o mesmo caminho.
3. **Com credencial, nada muda**: a guarda não pode barrar quem está configurado.
"""

import asyncio

import pytest

from app.services import integracoes


class _Fake:
    """Uma integração como o banco a devolve — só os campos que a guarda olha."""

    def __init__(self, token=None, senha=None):
        self.ativa = True
        self.base_url = 'https://exemplo.invalido'
        self.token_cifrado = token
        self.senha_cifrada = senha
        self.usuario_servico = 'servico' if senha else None


def test_meuwatt_sem_credencial_diz_o_que_falta(monkeypatch):
    monkeypatch.setattr(integracoes, 'obter', lambda db, p: _Fake())
    with pytest.raises(RuntimeError) as e:
        asyncio.run(integracoes.cliente_meuwatt(None))
    assert 'meuWatt' in str(e.value) and 'sem credencial' in str(e.value)
    assert 'encode' not in str(e.value), 'o erro cru não pode vazar'


def test_meuplano_sem_credencial_diz_o_que_falta(monkeypatch):
    monkeypatch.setattr(integracoes, 'obter', lambda db, p: _Fake())
    with pytest.raises(RuntimeError) as e:
        asyncio.run(integracoes.cliente_meuplano(None))
    assert 'meuPlano' in str(e.value) and 'sem credencial' in str(e.value)


def test_com_token_a_guarda_nao_atrapalha(monkeypatch):
    """A guarda protege de configuração pela metade — não pode barrar quem está pronto."""
    monkeypatch.setattr(integracoes, 'obter', lambda db, p: _Fake(token='cifrado'))
    monkeypatch.setattr(integracoes, 'decifrar', lambda v: 'token-em-claro')
    cli = asyncio.run(integracoes.cliente_meuwatt(None))
    assert cli is not None
