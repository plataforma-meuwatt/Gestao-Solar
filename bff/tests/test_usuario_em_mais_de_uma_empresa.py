"""Um usuário em mais de uma empresa — pedido do dono (23/10/2026): "um usuário pode estar
em mais de uma empresa (podemos ver se dá certo mesmo)".

Dá certo assim, e é o que estes testes provam:

- a conta tem UMA empresa de origem (`gs_users.empresa_id`, quem cuida da conta: senha,
  celular, tokens e bot) e pode ser TAMBÉM de outras (`gs_usuario_empresas`), com o mesmo
  papel;
- as duas empresas a veem na lista de usuários; o adm vê as duas na linha dela;
- o gerente da outra empresa concede as usinas DELA sem tocar nas da origem, e não mexe na
  conta (senha, celular, token);
- o gerente que é de duas empresas troca de empresa no oem-gs, e a sessão vale só enquanto
  ele continuar sendo de lá.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.security import criar_token_empresa, gerar_hash_senha, gestor_empresa_atual
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import empresas


def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture
def cenario(db, administrador):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Eninsa")
    db.add_all([a, b])
    db.commit()
    usina_a = PlantLink(nome="Usina da A", empresa_id=a.id, mw_plant_slug="usina-a")
    usina_b = PlantLink(nome="Usina da B", empresa_id=b.id, mw_plant_slug="usina-b")
    ger_a = User(apelido="ger.a", nome="Ger A", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id,
                 senha_hash=gerar_hash_senha("senha-1234"))
    ger_b = User(apelido="ger.b", nome="Ger B", perfil=Perfil.GESTOR_EMPRESA, empresa_id=b.id)
    dono = User(apelido="dono", nome="Dono", perfil=Perfil.CLIENTE, empresa_id=a.id)
    db.add_all([usina_a, usina_b, ger_a, ger_b, dono])
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=usina_a.id))
    db.commit()
    return a, b, usina_a, usina_b, ger_a, ger_b, dono


async def test_o_dono_em_duas_empresas_aparece_nas_duas_e_cada_uma_concede_as_suas(db, cenario, administrador):
    from app.api.v1.empresa import (
        UsinasDoClienteIn,
        definir_usinas_do_cliente,
        usuarios_detalhados,
        usinas_do_usuario,
    )
    from app.api.v1.plants import usinas_do_usuario as escopo

    a, b, usina_a, usina_b, _ger_a, ger_b, dono = cenario
    empresas.por_na_empresa(db, dono, b.id, administrador)
    db.commit()
    assert empresas.empresas_da_conta(db, dono) == [a.id, b.id]

    # A lista do gerente da B traz o dono, marcado como cuidado pela A.
    linha = next(u for u in await usuarios_detalhados(db=db, gerente=ger_b) if u.id == dono.id)
    assert linha.cuidada_por == "Splendor O&M"
    assert linha.usinas == 0  # a usina que ele recebe da A não é contada (nem mostrada) na B

    # A B concede a usina DELA, e a da A continua lá.
    definir_usinas_do_cliente(dono.id, UsinasDoClienteIn(plant_link_ids=[usina_b.id]), db=db, gerente=ger_b)
    assert {u.id for u in escopo(db, dono)} == {usina_a.id, usina_b.id}
    # O "salvar" da B com a lista vazia tira só a da B.
    definir_usinas_do_cliente(dono.id, UsinasDoClienteIn(plant_link_ids=[]), db=db, gerente=ger_b)
    assert {u.id for u in escopo(db, dono)} == {usina_a.id}
    # E a tela da B não mostra (nem o nome) a usina que ele recebe da A.
    assert usinas_do_usuario(dono.id, db=db, gerente=ger_b) == []


async def test_a_outra_empresa_nao_mexe_na_conta_so_concede(db, cenario, administrador):
    """Senha, celular, token e bot são de quem cuida da conta (a de origem): duas empresas
    trocando a senha da mesma pessoa abririam a carteira de uma para o gerente da outra."""
    from app.api.v1.empresa import ContaPatch, editar_conta_da_empresa

    _a, b, *_resto, ger_b, dono = cenario
    empresas.por_na_empresa(db, dono, b.id, administrador)
    db.commit()
    with pytest.raises(HTTPException) as erro:
        await editar_conta_da_empresa(dono.id, ContaPatch(senha="outra-senha-1"), db, ger_b)
    assert erro.value.status_code == 404


def test_o_gerente_de_duas_empresas_troca_de_empresa(db, cenario, administrador):
    from app.api.v1.sessao import TrocaDeEmpresaIn, empresas_da_sessao, trocar_de_empresa

    a, b, _ua, _ub, ger_a, _ger_b, _dono = cenario
    token, _ = criar_token_empresa(ger_a.id)
    # Uma empresa só: o seletor nem aparece (a lista tem uma).
    assert [e.id for e in empresas_da_sessao(cred=_cred(token), db=db)] == [a.id]

    empresas.por_na_empresa(db, ger_a, b.id, administrador)
    db.commit()
    lista = empresas_da_sessao(cred=_cred(token), db=db)
    assert [(e.id, e.origem, e.atual) for e in lista] == [(a.id, True, True), (b.id, False, False)]

    nova = trocar_de_empresa(TrocaDeEmpresaIn(empresa_id=b.id), cred=_cred(token), db=db)
    assert nova.empresa == "Eninsa"
    eu = gestor_empresa_atual(cred=_cred(nova.token), db=db)
    assert empresas.empresa_exigida(eu) == b.id

    # Tirado da B, a sessão de lá para na requisição seguinte — sem esperar expirar.
    empresas.tirar_da_empresa(db, ger_a, b.id)
    db.commit()
    db.expire_all()
    with pytest.raises(HTTPException) as erro:
        gestor_empresa_atual(cred=_cred(nova.token), db=db)
    assert erro.value.status_code == 403


def test_nao_se_troca_para_empresa_que_nao_e_da_conta(db, cenario):
    from app.api.v1.sessao import TrocaDeEmpresaIn, trocar_de_empresa

    _a, b, _ua, _ub, ger_a, _ger_b, _dono = cenario
    token, _ = criar_token_empresa(ger_a.id)
    with pytest.raises(HTTPException) as erro:
        trocar_de_empresa(TrocaDeEmpresaIn(empresa_id=b.id), cred=_cred(token), db=db)
    assert erro.value.status_code == 404


def test_sair_da_empresa_leva_as_usinas_dela_e_a_proxima_vira_a_de_origem(db, cenario, administrador):
    a, b, usina_a, usina_b, _ger_a, _ger_b, dono = cenario
    empresas.por_na_empresa(db, dono, b.id, administrador)
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=usina_b.id))
    db.commit()

    empresas.tirar_da_empresa(db, dono, a.id)
    db.commit()
    assert dono.empresa_id == b.id and empresas.empresas_da_conta(db, dono) == [b.id]
    assert {x.plant_link_id for x in db.query(UserPlantAccess).filter_by(user_id=dono.id)} == {usina_b.id}


def test_conta_da_plataforma_nao_entra_em_empresa(db, cenario, administrador):
    a, *_ = cenario
    with pytest.raises(HTTPException) as erro:
        empresas.por_na_empresa(db, administrador, a.id, administrador)
    assert erro.value.status_code == 400


def test_o_adm_ve_empresas_e_usuarios_dos_dois_lados(db, cenario, administrador):
    """A tela do adm: a empresa mostra quem é dela (inclusive o gerente — o renan.marquezini
    que sumia na lista de Clientes), e a lista de usuários mostra a(s) empresa(s) de cada um."""
    from app.api.v1.painel_empresas import detalhe, usuarios_da_empresa
    from app.api.v1.painel_usuarios import todas_as_contas

    a, b, _ua, _ub, ger_a, _ger_b, dono = cenario
    empresas.por_na_empresa(db, dono, b.id, administrador)
    orfao = User(apelido="orfao", nome="Sem Empresa", perfil=Perfil.CLIENTE)
    db.add(orfao)
    db.commit()

    da_a = {u.apelido: u for u in usuarios_da_empresa(a.id, db=db, gestor=administrador)}
    assert set(da_a) == {"ger.a", "dono"} and da_a["dono"].outras_empresas == ["Eninsa"]
    assert detalhe(a.id, db=db, _gestor=administrador).gerentes == 1

    contas = {c.apelido: c for c in todas_as_contas(db=db, admin=administrador)}
    assert [(e.nome, e.origem) for e in contas["dono"].empresas] == [("Splendor O&M", True), ("Eninsa", False)]
    assert [e.nome for e in contas["ger.a"].empresas] == ["Splendor O&M"]
    assert contas["orfao"].empresas == [] and not contas["orfao"].da_plataforma
    assert contas[administrador.apelido].da_plataforma and contas[administrador.apelido].empresas == []


def test_o_ultimo_gerente_nao_sai_da_empresa_sem_outro(db, cenario, administrador):
    """Sem gerente, ninguém opera a empresa no oem-gs — e a saída seria a plataforma."""
    from app.api.v1.painel_empresas import UsuarioPatch, editar_usuario_da_empresa, tirar_usuario_da_empresa

    a, _b, _ua, _ub, ger_a, _ger_b, _dono = cenario
    for tentativa in (
        lambda: editar_usuario_da_empresa(a.id, ger_a.id, UsuarioPatch(perfil=Perfil.CLIENTE), db=db, gestor=administrador),
        lambda: editar_usuario_da_empresa(a.id, ger_a.id, UsuarioPatch(ativo=False), db=db, gestor=administrador),
        lambda: tirar_usuario_da_empresa(a.id, ger_a.id, db=db, _gestor=administrador),
    ):
        with pytest.raises(HTTPException) as erro:
            tentativa()
        assert erro.value.status_code == 400 and "único gerente" in erro.value.detail

    outro = User(apelido="ger.a2", nome="Ger A2", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id)
    db.add(outro)
    db.commit()
    assert editar_usuario_da_empresa(a.id, ger_a.id, UsuarioPatch(ativo=False), db=db, gestor=administrador).ativo is False


def test_conta_sem_empresa_mostra_a_pista_do_cadastro_antigo(db, cenario, administrador):
    from app.api.v1.painel_usuarios import todas_as_contas

    db.add(User(apelido="janderson", nome="Janderson", perfil=Perfil.CLIENTE, empresa="Eninsa"))
    db.commit()
    conta = next(c for c in todas_as_contas(db=db, admin=administrador) if c.apelido == "janderson")
    assert conta.empresas == [] and conta.empresa_antiga == "Eninsa"
