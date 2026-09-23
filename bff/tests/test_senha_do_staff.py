"""Redefinir a senha de quem entra no painel.

Os testes chamam a rota diretamente, com a sessão e o administrador no lugar das
dependências do FastAPI — é o mesmo código que roda na requisição, sem subir servidor.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.painel_usuarios import SenhaIn, redefinir_senha
from app.core.security import conferir_senha, gerar_hash_senha
from app.models.user import Perfil, User


def test_senha_nova_entra_e_a_antiga_nao(db, administrador, atendente):
    redefinir_senha(atendente.id, SenhaIn(senha="nova-senha-123"), db=db, _=administrador)

    db.refresh(atendente)
    assert conferir_senha("nova-senha-123", atendente.senha_hash)
    assert not conferir_senha("atende-1234", atendente.senha_hash)


def test_administrador_redefine_outro_administrador(db, administrador):
    """O caso que motivou a rota: um colega administrador esqueceu a senha, e a única
    saída era o script na linha de comando."""
    colega = User(
        apelido="colega",
        nome="Colega",
        perfil=Perfil.ADMINISTRADOR,
        senha_hash=gerar_hash_senha("esquecida-1234"),
    )
    db.add(colega)
    db.commit()

    redefinir_senha(colega.id, SenhaIn(senha="lembrada-1234"), db=db, _=administrador)

    db.refresh(colega)
    assert conferir_senha("lembrada-1234", colega.senha_hash)


def test_cliente_nao_passa_por_aqui(db, administrador):
    """Cliente tem senha provisória, pela tela de clientes. Por esta rota ele não existe —
    a mesma régua do PATCH."""
    cliente = User(
        apelido="cliente",
        nome="Cliente",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(cliente)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        redefinir_senha(cliente.id, SenhaIn(senha="outra-senha-123"), db=db, _=administrador)
    assert exc.value.status_code == 404

    db.refresh(cliente)
    assert conferir_senha("cliente-1234", cliente.senha_hash)


def test_usuario_inexistente_e_404(db, administrador):
    with pytest.raises(HTTPException) as exc:
        redefinir_senha(9999, SenhaIn(senha="nova-senha-123"), db=db, _=administrador)
    assert exc.value.status_code == 404


def test_senha_curta_e_recusada():
    """O mesmo mínimo do cadastro: oito caracteres."""
    with pytest.raises(ValidationError):
        SenhaIn(senha="curta")
