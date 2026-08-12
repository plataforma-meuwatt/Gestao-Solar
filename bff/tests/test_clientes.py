"""As regras de negócio do cadastro de cliente.

Cada teste aqui corresponde a um jeito de o gestor ou o sistema errar de forma que só
apareceria semanas depois — cliente vendo usina de outro, acesso entregue e ninguém
lembrando, senha que não se sabe se foi usada.
"""

import pytest

from app.core.security import conferir_senha
from app.models.user import Perfil, SenhaProvisoria, User
from app.services import clientes as svc


def test_criar_cliente_devolve_senha_que_funciona(db, administrador):
    criado = svc.criar(
        db, nome="Renan", email="Renan@Solaris.com.BR", empresa="Solaris", criado_por=administrador
    )

    assert criado.usuario.perfil is Perfil.CLIENTE
    # E-mail normalizado: senão o mesmo cliente entra duas vezes com caixas diferentes.
    assert criado.usuario.email == "renan@solaris.com.br"
    assert conferir_senha(criado.senha_provisoria, criado.usuario.senha_hash)
    # Provisória de verdade: o app obriga a trocar antes de qualquer tela.
    assert criado.usuario.trocar_senha is True


def test_senha_provisoria_nao_fica_guardada(db, administrador):
    """Ela existe no retorno e no hash — em nenhum outro lugar. É o que garante que
    nenhum GET consiga devolvê-la depois."""
    criado = svc.criar(db, nome="Renan", email="a@b.com", empresa=None, criado_por=administrador)

    registro = db.query(SenhaProvisoria).filter_by(gs_user_id=criado.usuario.id).one()
    for valor in vars(registro).values():
        assert criado.senha_provisoria != valor
    assert criado.senha_provisoria not in (criado.usuario.senha_hash or "")


def test_email_repetido_e_recusado(db, administrador):
    svc.criar(db, nome="Renan", email="a@b.com", empresa=None, criado_por=administrador)
    with pytest.raises(svc.RegraDeNegocio, match="Já existe"):
        svc.criar(db, nome="Outro", email="A@B.com", empresa=None, criado_por=administrador)


def test_regenerar_senha_invalida_a_anterior(db, administrador):
    criado = svc.criar(db, nome="Renan", email="a@b.com", empresa=None, criado_por=administrador)
    antiga = criado.senha_provisoria

    nova = svc.regenerar_senha(db, criado.usuario, administrador)

    assert nova != antiga
    assert conferir_senha(nova, criado.usuario.senha_hash)
    assert not conferir_senha(antiga, criado.usuario.senha_hash)


def test_situacao_do_acesso_acompanha_o_uso(db, administrador):
    from datetime import UTC, datetime, timedelta

    cliente = User(email="c@d.com", nome="Cliente", perfil=Perfil.CLIENTE)
    db.add(cliente)
    db.commit()

    assert svc.situacao_acesso(db, cliente) == "nunca"

    svc.regenerar_senha(db, cliente, administrador)
    assert svc.situacao_acesso(db, cliente) == "entregue"

    # Login DEPOIS da senha ter sido gerada é o que conta como usado.
    cliente.ultimo_login = datetime.now(UTC) + timedelta(minutes=1)
    db.commit()
    assert svc.situacao_acesso(db, cliente) == "usado"


def test_usina_de_outro_cliente_e_recusada(db, administrador, usinas):
    porto, _ = usinas
    um = svc.criar(db, nome="Um", email="um@a.com", empresa=None, criado_por=administrador).usuario
    dois = svc.criar(db, nome="Dois", email="dois@a.com", empresa=None, criado_por=administrador).usuario

    svc.definir_usinas(db, um, [porto.id])

    with pytest.raises(svc.RegraDeNegocio, match="Porto Ferreira.*já é de Um"):
        svc.definir_usinas(db, dois, [porto.id])


def test_conflito_nao_grava_nada(db, administrador, usinas):
    """A operação é tudo-ou-nada: gravar parcialmente deixaria o gestor sem saber o que
    entrou."""
    porto, ribeirao = usinas
    um = svc.criar(db, nome="Um", email="um@a.com", empresa=None, criado_por=administrador).usuario
    dois = svc.criar(db, nome="Dois", email="dois@a.com", empresa=None, criado_por=administrador).usuario

    svc.definir_usinas(db, um, [porto.id])

    with pytest.raises(svc.RegraDeNegocio):
        svc.definir_usinas(db, dois, [ribeirao.id, porto.id])

    assert svc.contar_usinas(db).get(dois.id, 0) == 0


def test_manter_a_propria_usina_nao_e_conflito(db, administrador, usinas):
    """Editar a lista de um cliente que já tem a usina não pode reclamar dele mesmo."""
    porto, ribeirao = usinas
    um = svc.criar(db, nome="Um", email="um@a.com", empresa=None, criado_por=administrador).usuario

    svc.definir_usinas(db, um, [porto.id])
    svc.definir_usinas(db, um, [porto.id, ribeirao.id])

    assert svc.contar_usinas(db)[um.id] == 2


def test_definir_usinas_remove_o_que_saiu(db, administrador, usinas):
    porto, ribeirao = usinas
    um = svc.criar(db, nome="Um", email="um@a.com", empresa=None, criado_por=administrador).usuario

    svc.definir_usinas(db, um, [porto.id, ribeirao.id])
    svc.definir_usinas(db, um, [ribeirao.id])

    assert svc.contar_usinas(db)[um.id] == 1


def test_usina_liberada_pode_ir_para_outro(db, administrador, usinas):
    """Cliente trocou de dono: tirar de um tem de liberar para o outro na hora."""
    porto, _ = usinas
    um = svc.criar(db, nome="Um", email="um@a.com", empresa=None, criado_por=administrador).usuario
    dois = svc.criar(db, nome="Dois", email="dois@a.com", empresa=None, criado_por=administrador).usuario

    svc.definir_usinas(db, um, [porto.id])
    svc.definir_usinas(db, um, [])
    svc.definir_usinas(db, dois, [porto.id])

    assert svc.contar_usinas(db)[dois.id] == 1
