"""A central de notificações: o funil, e as três formas de não receber.

Cada teste aqui é um jeito de o cliente NÃO receber — e todos são silenciosos em produção,
porque ninguém repara no aviso que não chegou. É por isso que eles existem:

* nada nasce ligado;
* usina que não é do cliente não pode ser marcada (seria vazar o nome da usina de outro);
* tirar a usina do cliente apaga a preferência dela;
* sem telefone ou sem aceite, nada sai — e a tela diz qual dos dois falta.
"""

import pytest

from app.core.security import gerar_hash_senha
from app.models.notificacao import NotificacaoPreferencia
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import clientes as svc_clientes
from app.services import notificacoes as svc


@pytest.fixture
def cliente(db, usinas):
    """Um cliente com as duas usinas concedidas, telefone e aceite — o caso feliz."""
    u = User(
        apelido="cliente.teste",
        email="cliente@exemplo.com",
        nome="Cliente Teste",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
        telefone="+5516999998888",
    )
    db.add(u)
    db.commit()
    for usina in usinas:
        db.add(UserPlantAccess(user_id=u.id, plant_link_id=usina.id))
    db.commit()
    return u


def _aceitar(db, cliente, gestor):
    svc.registrar_aceite(db, cliente, aceito=True, por=gestor)


def test_cliente_novo_nao_recebe_nada(db, cliente):
    """Nada nasce ligado: sem o gestor marcar, a matriz está vazia."""
    assert svc.marcadas(db, cliente) == set()


def test_marcar_grava_o_par_tipo_e_usina(db, cliente, usinas, administrador):
    svc.definir(db, cliente, [("parada", usinas[0].id)], por=administrador)
    assert svc.marcadas(db, cliente) == {("parada", usinas[0].id)}


def test_marcar_de_novo_substitui_a_lista_inteira(db, cliente, usinas, administrador):
    """A tela manda o estado final — não há conceder e revogar separados."""
    svc.definir(db, cliente, [("parada", usinas[0].id)], por=administrador)
    svc.definir(db, cliente, [("energia_mes", usinas[1].id)], por=administrador)
    assert svc.marcadas(db, cliente) == {("energia_mes", usinas[1].id)}


def test_tipo_fora_do_catalogo_e_recusado(db, cliente, usinas, administrador):
    """Gravar caladamente criaria linha que nenhum motor lê: chave ligada, nada chegando."""
    with pytest.raises(svc.RegraDeNegocio):
        svc.definir(db, cliente, [("inventado", usinas[0].id)], por=administrador)


def test_usina_de_outro_cliente_e_recusada(db, cliente, administrador):
    """Avisar sobre usina que ele não abre é vazamento — o nome dela na tela de bloqueio."""
    alheia = PlantLink(mw_plant_slug="alheia", nome="Usina de Outro")
    db.add(alheia)
    db.commit()
    with pytest.raises(svc.RegraDeNegocio):
        svc.definir(db, cliente, [("parada", alheia.id)], por=administrador)


def test_recusa_a_lista_toda_quando_um_par_e_invalido(db, cliente, usinas, administrador):
    """Gravar o resto deixaria o gestor com metade do que marcou e sem saber qual metade."""
    with pytest.raises(svc.RegraDeNegocio):
        svc.definir(
            db,
            cliente,
            [("parada", usinas[0].id), ("inventado", usinas[1].id)],
            por=administrador,
        )
    assert svc.marcadas(db, cliente) == set()


def test_tirar_a_usina_do_cliente_apaga_as_preferencias_dela(
    db, cliente, usinas, administrador
):
    """Reconceder a usina meses depois não pode ressuscitar aviso que ninguém marcou."""
    svc.definir(
        db,
        cliente,
        [("parada", usinas[0].id), ("energia_dia", usinas[1].id)],
        por=administrador,
    )
    svc_clientes.definir_usinas(db, cliente, [usinas[1].id])

    assert svc.marcadas(db, cliente) == {("energia_dia", usinas[1].id)}
    assert db.query(NotificacaoPreferencia).count() == 1


def test_sem_telefone_nao_e_apto(db, cliente, administrador):
    cliente.telefone = None
    db.commit()
    assert svc.apto(cliente) is False
    assert "telefone" in svc.motivo_de_nao_receber(cliente).lower()


def test_sem_aceite_nao_e_apto(db, cliente):
    """A Meta proíbe a empresa iniciar conversa sem o aceite — e o gestor precisa ver isso."""
    assert cliente.whatsapp_aceite_em is None
    assert svc.apto(cliente) is False
    assert "aceite" in svc.motivo_de_nao_receber(cliente).lower()


def test_conta_desativada_nao_e_apta(db, cliente, administrador):
    _aceitar(db, cliente, administrador)
    cliente.ativo = False
    db.commit()
    assert svc.apto(cliente) is False


def test_com_telefone_e_aceite_fica_apto(db, cliente, administrador):
    _aceitar(db, cliente, administrador)
    assert svc.apto(cliente) is True
    assert svc.motivo_de_nao_receber(cliente) is None
    assert cliente.whatsapp_aceite_por == administrador.id


def test_retirar_o_aceite_nao_apaga_as_preferencias(db, cliente, usinas, administrador):
    """Cliente que pede para sair volta a não receber — sem perder o que já estava escolhido."""
    _aceitar(db, cliente, administrador)
    svc.definir(db, cliente, [("parada", usinas[0].id)], por=administrador)

    svc.registrar_aceite(db, cliente, aceito=False, por=administrador)

    assert svc.apto(cliente) is False
    assert svc.marcadas(db, cliente) == {("parada", usinas[0].id)}


def test_destinatarios_aplica_os_tres_filtros(db, cliente, usinas, administrador):
    """É a função que o motor vai chamar: quem está marcado, tem a usina, e está apto."""
    svc.definir(db, cliente, [("parada", usinas[0].id)], por=administrador)

    # Marcado, mas sem aceite ainda.
    assert svc.destinatarios(db, "parada", usinas[0].id) == []

    _aceitar(db, cliente, administrador)
    assert [u.id for u in svc.destinatarios(db, "parada", usinas[0].id)] == [cliente.id]

    # Outro tipo e outra usina não arrastam ninguém junto.
    assert svc.destinatarios(db, "energia_dia", usinas[0].id) == []
    assert svc.destinatarios(db, "parada", usinas[1].id) == []


def test_destinatarios_para_de_incluir_quem_perdeu_a_usina(
    db, cliente, usinas, administrador
):
    """Entre marcar e enviar pode ter passado um mês — a concessão é conferida no envio."""
    _aceitar(db, cliente, administrador)
    svc.definir(db, cliente, [("parada", usinas[0].id)], por=administrador)

    db.query(UserPlantAccess).filter(
        UserPlantAccess.user_id == cliente.id,
        UserPlantAccess.plant_link_id == usinas[0].id,
    ).delete()
    db.commit()

    assert svc.destinatarios(db, "parada", usinas[0].id) == []


def test_catalogo_cobre_os_seis_tipos_combinados(db):
    """A tela promete seis avisos; o catálogo é quem os define."""
    assert {t.tipo for t in svc.CATALOGO} == {
        "parada",
        "os_iniciada",
        "os_finalizada",
        "energia_dia",
        "energia_semana",
        "energia_mes",
    }
    for t in svc.CATALOGO:
        assert t.origem in {"meuWatt", "meuPlano"}
        assert t.descricao.strip()
