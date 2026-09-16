"""Credenciais: testar antes de gravar. Envio: registrar antes de mandar.

As duas regras existem pelo mesmo motivo — o estado do banco não pode mentir sobre o que
aconteceu. Uma credencial gravada sem teste deixa o gestor achando que configurou; um envio
sem linha prévia some quando a rede cai no meio.
"""

import pytest

from gateway.core import cripto
from gateway.meta import graph
from gateway.models.credencial import Credencial
from gateway.models.mensagem import Mensagem
from gateway.services import credenciais as svc
from gateway.services import envio as svc_envio
from tests.conftest import APP_SECRET, TOKEN, VERIFY_TOKEN


def _resultado_ok(*a, **k):
    async def _f(*_a, **_k):
        return svc.Resultado(True, "Conectado como Splendor · +55 16 99999-8888.", 1)

    return _f


@pytest.fixture
def meta_aceita(monkeypatch):
    monkeypatch.setattr(svc, "_exercitar", _resultado_ok())


@pytest.fixture
def meta_recusa(monkeypatch):
    async def _f(*_a, **_k):
        return svc.Resultado(False, "A Meta recusou o token.")

    monkeypatch.setattr(svc, "_exercitar", _f)


async def test_gravar_so_depois_de_a_meta_confirmar(db, meta_aceita):
    r = await svc.salvar(
        db,
        phone_number_id="1352387357947608",
        token=TOKEN,
        app_secret=APP_SECRET,
        verify_token=VERIFY_TOKEN,
        ator="renanmarquezini",
    )
    assert r.ok

    estado = svc.estado(db)
    assert estado["envio_pronto"] and estado["webhook_pronto"]
    assert estado["token_prefixo"] == TOKEN[:7]
    # O token em claro não volta por rota nenhuma.
    assert "token" not in estado


async def test_token_recusado_nao_derruba_o_que_ja_valia(db, credencial, meta_recusa):
    """Gravar primeiro e testar depois deixaria o gestor sem credencial nenhuma."""
    r = await svc.salvar(db, phone_number_id="999", token="token-ruim", app_secret=None,
                         verify_token=None, ator="renanmarquezini")
    assert not r.ok

    db.refresh(credencial)
    assert cripto.decifrar(credencial.token_cifrado) == TOKEN
    assert credencial.phone_number_id == "1352387357947608"


async def test_campo_de_segredo_vazio_significa_nao_mexer(db, credencial, meta_aceita):
    """Quem só corrigiu o WABA não tem mais o token para colar de novo."""
    await svc.salvar(db, phone_number_id=credencial.phone_number_id, token=None,
                     app_secret=None, verify_token=None, waba_id="outro-waba", ator="alguem")

    db.refresh(credencial)
    assert credencial.waba_id == "outro-waba"
    assert cripto.decifrar(credencial.token_cifrado) == TOKEN
    assert cripto.decifrar(credencial.app_secret_cifrado) == APP_SECRET


async def test_remover_apaga_segredo_e_mantem_historico(db, credencial):
    svc.remover(db, ator="renanmarquezini")

    estado = svc.estado(db)
    assert not estado["envio_pronto"] and not estado["webhook_pronto"]
    assert estado["phone_number_id"] == "1352387357947608"  # o registro de que houve fica
    assert any(e.evento == "removida" for e in svc.historico(db))


def test_em_uso_decifra_e_o_cache_solta_ao_invalidar(db, credencial):
    atual = svc.em_uso(db)
    assert atual.token == TOKEN and atual.app_secret == APP_SECRET

    svc.remover(db, ator="alguem")
    # `remover` invalida o cache; sem isso o webhook seguiria aceitando o segredo velho.
    assert svc.em_uso(db).app_secret is None


async def test_envio_grava_a_linha_antes_e_marca_o_wamid(db, credencial, monkeypatch):
    async def _graph(**_k):
        return graph.Resposta(ok=True, wamid="wamid.ENVIADA")

    monkeypatch.setattr(graph, "enviar_template", _graph)

    r = await svc_envio.enviar_template(
        db, telefone="(16) 99999-8888", template="gs_parada", parametros=["Porto Ferreira"],
        origem="bff",
    )

    assert r.ok and r.status == "enviada"
    m = db.get(Mensagem, r.id)
    assert m.wamid == "wamid.ENVIADA" and m.direcao == "saida" and m.telefone == "+5516999998888"


async def test_recusa_da_meta_vira_linha_falhou_com_motivo(db, credencial, monkeypatch):
    async def _graph(**_k):
        return graph.Resposta(ok=False, erro_codigo="131047", erro_detalhe="fora da janela")

    monkeypatch.setattr(graph, "enviar_template", _graph)

    r = await svc_envio.enviar_template(db, telefone="+5516999998888", template="gs_parada",
                                        parametros=[])
    assert not r.ok
    m = db.get(Mensagem, r.id)
    assert m.status == "falhou" and m.erro_codigo == "131047"


async def test_sem_credencial_o_envio_diz_o_que_falta(db):
    with pytest.raises(svc_envio.EnvioIndisponivel) as erro:
        await svc_envio.enviar_template(db, telefone="+5516999998888", template="x", parametros=[])
    assert "tela de administração" in str(erro.value)


async def test_telefone_impossivel_e_recusado_antes_de_gastar_rede(db, credencial):
    with pytest.raises(ValueError):
        await svc_envio.enviar_template(db, telefone="123", template="x", parametros=[])
    assert db.query(Mensagem).count() == 0


def test_credencial_sem_nada_configurado_diz_isso(db):
    estado = svc.estado(db)
    assert estado == {
        "configurada": False,
        "envio_pronto": False,
        "webhook_pronto": False,
        "estado": "nunca",
        "cifragem_disponivel": True,
    }


def test_linha_nasce_com_escopo_unico(db):
    """Um número, uma linha: duas linhas divergindo em silêncio é o que a UNIQUE impede."""
    db.add(Credencial(phone_number_id="1"))
    db.commit()
    db.add(Credencial(phone_number_id="2"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()
