"""Renovação da sessão do cliente — e o que ela recusa.

O portal do cliente fica aberto semanas no notebook; `POST /api/v1/auth/renovar` troca um
token ainda válido por um novo de 30 dias para a pessoa não cair na tela de entrada no
meio do uso. O que estes testes protegem, em ordem de gravidade:

1. **Sessão de painel não renova como cliente.** É a mesma cerca de `usuario_atual`: um
   token do gestor não pode virar, por renovação, um token de cliente em nome dele.
2. **Sem token, nada.** Renovar sem sessão seria emitir sessão de graça.
3. **O token novo vence DEPOIS do velho** e é aceito pelas rotas do cliente — senão a
   renovação é decoração.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import ALGORITMO, criar_token, criar_token_painel, gerar_hash_senha
from app.main import app
from app.models.user import Perfil, User


@pytest.fixture
def cliente_http(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def dono(db):
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


def _token_cliente_vencendo_em(user_id: int, dias: int) -> str:
    """Um token de cliente legítimo, só que com menos vida — é o cenário real da
    renovação (o portal chama quando falta menos de uma semana). Emitir com a mesma
    chave e o mesmo formato de `criar_token`, sem o `escopo`, é o que o torna 'de cliente'."""
    expira = datetime.now(UTC) + timedelta(days=dias)
    return jwt.encode(
        {"sub": str(user_id), "exp": expira}, get_settings().gs_jwt_secret, algorithm=ALGORITMO
    )


def _exp(token: str) -> int:
    return int(jwt.decode(token, get_settings().gs_jwt_secret, algorithms=[ALGORITMO])["exp"])


def test_sem_token_nao_renova(cliente_http):
    assert cliente_http.post("/api/v1/auth/renovar").status_code == 401


def test_token_de_painel_nao_renova_como_cliente(cliente_http, administrador):
    token, _ = criar_token_painel(administrador.id)

    r = cliente_http.post("/api/v1/auth/renovar", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert "painel" in r.json()["detail"].lower()


def test_token_vencido_nao_renova(cliente_http, dono):
    """Aqui é senha de novo: o vencimento é o único corte que um token perdido tem."""
    token = _token_cliente_vencendo_em(dono.id, dias=-1)

    r = cliente_http.post("/api/v1/auth/renovar", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401


def test_conta_desativada_nao_renova(cliente_http, db, dono):
    dono.ativo = False
    db.commit()
    # Ler `dono.id` DEPOIS do commit reabre a conexão na thread do teste: com o SQLite em
    # memória, a primeira consulta feita pela thread do TestClient cairia num banco vazio.
    token, _ = criar_token(dono.id)

    r = cliente_http.post("/api/v1/auth/renovar", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401


def test_renova_e_o_token_novo_vence_depois_do_velho(cliente_http, dono):
    velho = _token_cliente_vencendo_em(dono.id, dias=3)

    r = cliente_http.post("/api/v1/auth/renovar", headers={"Authorization": f"Bearer {velho}"})

    assert r.status_code == 200
    corpo = r.json()
    novo = corpo["token"]
    assert novo != velho
    assert _exp(novo) > _exp(velho), "renovar tem de EMPURRAR o vencimento"
    # O perfil vem junto, no mesmo formato do login — o portal guarda o par e segue.
    assert corpo["usuario"]["apelido"] == "renan.marquezini"
    assert corpo["usuario"]["trocar_senha"] is False
    assert corpo["expira_em"]

    # O token novo abre as rotas do cliente e NÃO abre o painel: é indistinguível de um
    # login recente.
    eu = cliente_http.get("/api/v1/auth/eu", headers={"Authorization": f"Bearer {novo}"})
    assert eu.status_code == 200
    painel = cliente_http.get("/api/painel/usinas", headers={"Authorization": f"Bearer {novo}"})
    assert painel.status_code == 403


def test_renovar_nao_emite_sessao_de_painel(cliente_http, dono):
    """O token renovado não pode carregar `escopo` — senão a renovação viraria um jeito
    de fabricar sessão de gestor a partir de uma sessão de cliente."""
    velho, _ = criar_token(dono.id)

    r = cliente_http.post("/api/v1/auth/renovar", headers={"Authorization": f"Bearer {velho}"})

    dados = jwt.decode(r.json()["token"], get_settings().gs_jwt_secret, algorithms=[ALGORITMO])
    assert "escopo" not in dados
    assert dados["sub"] == str(dono.id)
