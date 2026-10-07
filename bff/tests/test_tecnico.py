"""O técnico: um portão só dele, e o WhatsApp dele — nada além.

Fase T1 de `docs/PLANO_WHATSAPP_TECNICOS.md`. O técnico entra no painel para conectar o
número dele ao help-desk do meuPlano. O que estes testes guardam é o que faria disso uma
escalada: o técnico abrindo rota de gerente, de plataforma ou de cliente, ou mexendo no
número de outra pessoa.

As guardas são chamadas direto, com o token montado aqui — o mesmo código da requisição,
sem subir servidor (o padrão de `test_escalada_e_isolamento.py`).
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1 import tecnico as rotas
from app.core.security import (
    criar_token,
    criar_token_empresa,
    criar_token_painel,
    criar_token_tecnico,
    gerar_hash_senha,
    gestor_atual,
    gestor_empresa_atual,
    tecnico_atual,
    usuario_atual,
)
from app.models.empresa import Empresa
from app.models.user import Perfil, User
from app.services import pessoas


def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture
def cenario(db):
    emp = Empresa(nome="Splendor O&M")
    db.add(emp)
    db.flush()
    gerente = User(apelido="gerente", nome="Gerente", perfil=Perfil.GESTOR_EMPRESA,
                   empresa_id=emp.id, senha_hash=gerar_hash_senha("gerente-1234"))
    tecnico = User(apelido="tecnico.a", nome="Técnico A", perfil=Perfil.TECNICO,
                   empresa_id=emp.id, senha_hash=gerar_hash_senha("tecnico-1234"))
    db.add_all([gerente, tecnico])
    db.commit()
    return emp, gerente, tecnico


# ── o portão ────────────────────────────────────────────────────────────────


def test_o_token_do_tecnico_nao_abre_nenhum_outro_portao(db, cenario):
    """Escopo novo nasce recusado: os três portões leem a claim antes do perfil."""
    _emp, _gerente, tecnico = cenario
    token, _ = criar_token_tecnico(tecnico.id)

    for guarda in (gestor_empresa_atual, gestor_atual, usuario_atual):
        with pytest.raises(HTTPException) as erro:
            guarda(_cred(token), db=db)
        assert erro.value.status_code in (401, 403), guarda.__name__

    assert tecnico_atual(_cred(token), db=db).id == tecnico.id


def test_nenhum_outro_token_abre_o_portao_do_tecnico(db, cenario):
    _emp, gerente, tecnico = cenario
    for token, _ in (
        criar_token_empresa(gerente.id),
        criar_token_painel(gerente.id),
        criar_token(tecnico.id),  # o do aplicativo, mesmo sendo do próprio técnico
    ):
        with pytest.raises(HTTPException):
            tecnico_atual(_cred(token), db=db)


def test_token_de_tecnico_emitido_para_gerente_nao_vale(db, cenario):
    """A claim certa com o perfil errado: a guarda confere os dois."""
    _emp, gerente, _tecnico = cenario
    token, _ = criar_token_tecnico(gerente.id)
    with pytest.raises(HTTPException) as erro:
        tecnico_atual(_cred(token), db=db)
    assert erro.value.status_code == 403


def test_tecnico_sem_empresa_ou_com_empresa_desativada_nao_entra(db, cenario):
    emp, _gerente, tecnico = cenario
    token, _ = criar_token_tecnico(tecnico.id)

    emp.ativa = False
    db.commit()
    with pytest.raises(HTTPException) as erro:
        tecnico_atual(_cred(token), db=db)
    assert "desativada" in erro.value.detail

    emp.ativa = True
    tecnico.empresa_id = None
    db.commit()
    with pytest.raises(HTTPException) as erro:
        tecnico_atual(_cred(token), db=db)
    assert "nenhuma empresa" in erro.value.detail


def test_o_login_unico_emite_a_sessao_do_tecnico(db, cenario):
    from jose import jwt

    from app.api.v1.painel import EntrarIn, entrar
    from app.core.config import get_settings

    r = entrar(EntrarIn(apelido="tecnico.a", senha="tecnico-1234"), db=db)
    assert r.escopo == "tecnico" and r.empresa == "Splendor O&M"
    assert jwt.decode(r.token, get_settings().gs_jwt_secret, algorithms=["HS256"])["escopo"] == "tecnico"
    assert pessoas.escopo_do_perfil(Perfil.TECNICO) == "tecnico"


# ── o gerente cria; o técnico não recebe usina ─────────────────────────────


def test_o_gerente_cria_tecnico_na_empresa_dele(db, cenario, monkeypatch):
    from app.api.v1.empresa import ClienteIn, criar_cliente

    emp, gerente, _ = cenario
    criado = criar_cliente(
        ClienteIn(nome="Técnico B", apelido="tecnico.b", perfil=Perfil.TECNICO),
        db=db, gerente=gerente,
    )
    conta = db.get(User, criado.id)
    assert conta.perfil is Perfil.TECNICO and conta.empresa_id == emp.id


def test_tecnico_nao_recebe_usina(db, cenario):
    from app.api.v1.empresa import UsinasDoClienteIn, definir_usinas_do_cliente

    _emp, gerente, tecnico = cenario
    with pytest.raises(HTTPException) as erro:
        definir_usinas_do_cliente(tecnico.id, UsinasDoClienteIn(plant_link_ids=[]), db=db, gerente=gerente)
    assert erro.value.status_code == 400


# ── o WhatsApp: a conta é SEMPRE a da sessão ───────────────────────────────


async def test_conectar_manda_o_tecnico_da_sessao_e_reconhece_a_coexistencia(cenario, monkeypatch):
    emp, _gerente, tecnico = cenario
    enviado = {}

    async def conectar_conta(dados):
        enviado.update(dados)
        return {"ok": True, "detalhe": "Conectado."}

    monkeypatch.setattr(rotas.gateway, "conectar_conta", conectar_conta)
    r = await rotas.conectar(
        rotas.ConectarIn(code="c", waba_id="w", phone_number_id="p",
                         evento="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"),
        tecnico=tecnico,
    )
    assert r.ok
    assert enviado["gs_user_id"] == tecnico.id and enviado["empresa_id"] == emp.id
    assert enviado["coexistencia"] is True


async def test_numero_de_outro_responde_404(cenario, monkeypatch):
    _emp, _gerente, tecnico = cenario

    async def recusa(*a, **k):
        raise rotas.gateway.GatewayIndisponivel("Número não encontrado nesta conta.", status=404)

    monkeypatch.setattr(rotas.gateway, "desconectar_conta", recusa)
    with pytest.raises(HTTPException) as erro:
        await rotas.desconectar("p", tecnico=tecnico)
    assert erro.value.status_code == 404


def test_nenhuma_rota_do_tecnico_aceita_id_de_conta():
    """Um `gs_user_id` vindo de quem chama seria a forma de mexer no número de outro."""
    import inspect

    for nome in ("eu", "meu_whatsapp", "conectar", "desconectar"):
        parametros = inspect.signature(getattr(rotas, nome)).parameters
        assert not {"gs_user_id", "usuario_id", "user_id"} & set(parametros), nome
    assert "gs_user_id" not in rotas.ConectarIn.model_fields
