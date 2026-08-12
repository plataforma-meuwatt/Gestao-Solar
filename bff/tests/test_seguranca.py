"""As duas garantias que o painel precisa manter: senha não volta de hash, e segredo não
volta de texto cifrado."""

import pytest

from app.core.security import conferir_senha, gerar_hash_senha


def test_hash_confere_a_senha_certa():
    h = gerar_hash_senha("painel-dev-1234")
    assert conferir_senha("painel-dev-1234", h)


def test_hash_recusa_senha_errada():
    h = gerar_hash_senha("painel-dev-1234")
    assert not conferir_senha("painel-dev-12345", h)
    assert not conferir_senha("", h)


def test_hash_nao_contem_a_senha():
    """Óbvio, mas é a regressão que importa: um dia alguém pode 'simplificar' o formato."""
    h = gerar_hash_senha("segredo-visivel")
    assert "segredo-visivel" not in h


def test_dois_hashes_da_mesma_senha_diferem():
    """Sal aleatório: senhas iguais não podem produzir o mesmo hash, senão um vazamento
    revela quem compartilha senha."""
    assert gerar_hash_senha("igual") != gerar_hash_senha("igual")


def test_hash_ausente_ou_corrompido_recusa_em_silencio():
    """Conta sem senha definida e hash quebrado devolvem o mesmo `False` de senha errada —
    quem tenta entrar não aprende qual dos casos aconteceu."""
    assert not conferir_senha("qualquer", None)
    assert not conferir_senha("qualquer", "lixo")
    assert not conferir_senha("qualquer", "bcrypt$1$aa$bb")


def test_cifra_ida_e_volta(monkeypatch):
    from cryptography.fernet import Fernet

    from app.core import cripto

    chave = Fernet.generate_key().decode()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave.encode()))

    cifrado = cripto.cifrar("senha-de-servico")
    assert "senha-de-servico" not in cifrado
    assert cripto.decifrar(cifrado) == "senha-de-servico"


def test_cifra_com_chave_trocada_falha_alto(monkeypatch):
    """Trocar a GS_ENCRYPTION_KEY não pode devolver lixo silencioso — tem de estourar,
    para o painel dizer ao gestor que precisa reconfigurar."""
    from cryptography.fernet import Fernet

    from app.core import cripto

    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(Fernet.generate_key()))
    cifrado = cripto.cifrar("segredo")

    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(Fernet.generate_key()))
    with pytest.raises(cripto.SegredoInvalido):
        cripto.decifrar(cifrado)
