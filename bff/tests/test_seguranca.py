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


# ── os dois portões não se confundem ──────────────────────────────────────────
#
# A promessa "um token do app não abre o painel, e vice-versa" era cumprida pela metade:
# `gestor_atual` recusava o token do cliente, mas `usuario_atual` lia só o `sub` e deixava
# o token do painel entrar em `/api/v1/*` em nome do gestor. Com o portal do cliente e o
# painel em domínios separados, uma sessão não pode valer nos dois.


@pytest.fixture
def cliente_http(db):
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def dono(db):
    from app.models.user import Perfil, User

    u = User(
        apelido="renan.marquezini",
        email="renan@exemplo.com.br",
        nome="Renan",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


def _com(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_token_de_painel_nao_abre_rota_de_cliente(cliente_http, administrador):
    """O caso que estava aberto. O gestor, com a sessão do painel colada, tomava 200 em
    `/api/v1/auth/eu` — e, se tivesse usina concedida, veria a usina pelo portal."""
    from app.core.security import criar_token_painel

    token, _ = criar_token_painel(administrador.id)

    r = cliente_http.get("/api/v1/auth/eu", headers=_com(token))

    assert r.status_code == 401
    assert r.json()["detail"] == "Esta sessão é do painel do gestor"


def test_token_de_cliente_abre_rota_de_cliente(cliente_http, dono):
    from app.core.security import criar_token

    token, _ = criar_token(dono.id)

    r = cliente_http.get("/api/v1/auth/eu", headers=_com(token))

    assert r.status_code == 200
    assert r.json()["apelido"] == "renan.marquezini"


def test_token_de_cliente_segue_sem_abrir_o_painel(cliente_http, dono):
    """A metade que já valia continua valendo: fechar um lado não pode abrir o outro."""
    from app.core.security import criar_token

    token, _ = criar_token(dono.id)

    assert cliente_http.get("/api/painel/usinas", headers=_com(token)).status_code == 403


def test_qualquer_escopo_desconhecido_e_recusado_pelo_cliente(cliente_http, dono):
    """A cerca testa a PRESENÇA da claim, não o valor `painel`: um escopo inventado no
    futuro nasce recusado, em vez de entrar por omissão."""
    from jose import jwt

    from app.core.config import get_settings
    from app.core.security import ALGORITMO

    token = jwt.encode(
        {"sub": str(dono.id), "escopo": "novo-portao"},
        get_settings().gs_jwt_secret,
        algorithm=ALGORITMO,
    )

    assert cliente_http.get("/api/v1/auth/eu", headers=_com(token)).status_code == 401
