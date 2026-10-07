"""O WhatsApp Business de cada técnico: conectar, rotear pelo número e desconectar.

Três defeitos que estes testes fecham, todos silenciosos em produção:

* um número conectado por DUAS contas — a conversa do técnico A aparecendo para o B;
* um número gravado como "conectado" sem o webhook assinado — a tela diz que está tudo
  certo e nenhuma mensagem chega;
* a Meta desconectando o número (celular parado 14 dias) e a tela continuando verde.

Nenhum teste fala com a Meta: a Graph entra por substituição, e cada substituta anota o
que foi chamado — porque na coexistência o que NÃO pode ser chamado (`/register`) importa
tanto quanto o que deve.
"""

import pytest
from sqlalchemy import select

from gateway.core import cripto
from gateway.meta import graph
from gateway.models.conta import Conta
from gateway.models.mensagem import Mensagem, WebhookEvento
from gateway.services import contas, recebimento

NUMERO = "1111222233334444"
WABA = "5555666677778888"
TECNICO_A = 41
TECNICO_B = 42


@pytest.fixture
def meta(monkeypatch):
    """Uma Meta que aceita tudo e anota as chamadas. O teste muda o que precisar."""
    chamadas: list[str] = []

    async def trocar_code(**k):
        chamadas.append("trocar_code")
        return "EAAGtokenDoTecnico", None

    async def listar_numeros(**k):
        chamadas.append("listar_numeros")
        return [{"id": NUMERO, "display_phone_number": "+55 16 99999-0001",
                 "verified_name": "Técnico A"}], None

    async def assinar_waba(**k):
        chamadas.append("assinar_waba")
        return None

    async def desassinar_waba(**k):
        chamadas.append("desassinar_waba")
        return None

    async def registrar_numero(**k):
        chamadas.append("registrar_numero")
        return None

    async def sincronizar_aplicativo(**k):
        chamadas.append(f"sync:{k['tipo']}")
        return None

    for nome, f in list(locals().items()):
        if callable(f) and nome != "monkeypatch":
            monkeypatch.setattr(graph, nome, f)
    return chamadas


async def _conectar(db, gs_user_id=TECNICO_A, coexistencia=True):
    return await contas.conectar(
        db, code="code-de-30s", waba_id=WABA, phone_number_id=NUMERO,
        gs_user_id=gs_user_id, empresa_id=7, coexistencia=coexistencia, ator="tecnico.a",
    )


async def test_coexistencia_conecta_sem_registrar_e_pede_o_historico(db, credencial, meta):
    """Registrar um número que está no celular o tiraria de lá — a Meta proíbe."""
    credencial.es_config_id = "cfg"
    r = await _conectar(db)
    assert r.ok, r.detalhe

    assert "registrar_numero" not in meta
    assert meta[:3] == ["trocar_code", "listar_numeros", "assinar_waba"]
    assert {"sync:smb_app_state_sync", "sync:history"} <= set(meta)

    conta = db.scalar(select(Conta))
    assert conta.gs_user_id == TECNICO_A and conta.empresa_id == 7
    assert conta.coexistencia and conta.conectada
    assert conta.numero_exibicao == "+55 16 99999-0001"
    assert cripto.decifrar(conta.token_cifrado) == "EAAGtokenDoTecnico"
    assert conta.pin_cifrado is None


async def test_fora_da_coexistencia_registra_com_pin_guardado(db, credencial, meta):
    r = await _conectar(db, coexistencia=False)
    assert r.ok
    assert "registrar_numero" in meta and not any(c.startswith("sync:") for c in meta)
    pin = cripto.decifrar(db.scalar(select(Conta)).pin_cifrado)
    assert len(pin) == 6 and pin.isdigit()


async def test_numero_de_outra_conta_e_recusado_antes_da_meta(db, credencial, meta):
    """Aceitar entregaria ao técnico B a conversa do técnico A."""
    assert (await _conectar(db, TECNICO_A)).ok
    meta.clear()

    r = await _conectar(db, TECNICO_B)
    assert not r.ok and "outra conta" in r.detalhe
    assert meta == [], "falou com a Meta antes de recusar"
    assert db.scalar(select(Conta)).gs_user_id == TECNICO_A


async def test_numero_desconectado_pode_ser_assumido(db, credencial, meta):
    assert (await _conectar(db, TECNICO_A)).ok
    assert await contas.desconectar(db, phone_number_id=NUMERO, gs_user_id=TECNICO_A)
    r = await _conectar(db, TECNICO_B)
    assert r.ok
    assert db.scalar(select(Conta)).gs_user_id == TECNICO_B


async def test_nada_e_gravado_se_o_webhook_nao_for_assinado(db, credencial, meta, monkeypatch):
    """Gravar primeiro deixaria na tela um número 'conectado' que não recebe nada."""
    async def recusa(**k):
        return "(#200) Permissions error"

    monkeypatch.setattr(graph, "assinar_waba", recusa)
    r = await _conectar(db)
    assert not r.ok and "Permissions" in r.detalhe
    assert db.scalar(select(Conta)) is None


async def test_numero_de_outra_waba_e_recusado(db, credencial, meta, monkeypatch):
    """O navegador manda `waba_id` e `phone_number_id` juntos; o par tem de bater."""
    async def outra(**k):
        return [{"id": "999", "display_phone_number": "+55 11 0000-0000"}], None

    monkeypatch.setattr(graph, "listar_numeros", outra)
    r = await _conectar(db)
    assert not r.ok and "não pertence" in r.detalhe
    assert "assinar_waba" not in meta


async def test_sem_app_da_plataforma_nem_tenta(db, meta):
    r = await _conectar(db)
    assert not r.ok and "app da plataforma" in r.detalhe
    assert meta == []


async def test_desconectar_numero_de_outro_responde_como_inexistente(db, credencial, meta):
    assert (await _conectar(db, TECNICO_A)).ok
    assert not await contas.desconectar(db, phone_number_id=NUMERO, gs_user_id=TECNICO_B)
    assert db.scalar(select(Conta)).conectada


# ── o webhook roteado pelo número ───────────────────────────────────────────


def _evento(db, corpo) -> WebhookEvento:
    evento = recebimento.guardar(db, corpo)
    recebimento.processar(db, evento)
    return evento


def _change(field, value):
    return {"entry": [{"changes": [{"field": field, "value": value}]}]}


def test_mensagem_recebida_guarda_por_qual_numero_passou(db):
    _evento(db, _change("messages", {
        "metadata": {"phone_number_id": NUMERO},
        "messages": [{"from": "5516988887777", "id": "wamid.IN1", "timestamp": "1789000000",
                      "type": "text", "text": {"body": "o inversor chegou"}}],
    }))
    m = db.scalar(select(Mensagem))
    assert m.direcao == "entrada" and m.phone_number_id == NUMERO


def test_eco_do_celular_entra_como_saida_enviada(db):
    """Sem isto a timeline do ticket teria só o que o fabricante disse."""
    corpo = _change("smb_message_echoes", {
        "metadata": {"phone_number_id": NUMERO},
        "message_echoes": [{"from": "5516999990001", "to": "5516988887777", "id": "wamid.ECO1",
                            "timestamp": "1789000100", "type": "text",
                            "text": {"body": "mandei pelo celular"}}],
    })
    _evento(db, corpo)
    _evento(db, corpo)  # reentrega

    ecos = db.scalars(select(Mensagem)).all()
    assert len(ecos) == 1, "a reentrega do eco duplicou a mensagem"
    eco = ecos[0]
    assert eco.direcao == "saida" and eco.origem == "celular" and eco.status == "enviada"
    assert eco.wa_id == "5516988887777", "o contato é o `to` do eco, não o `from`"
    assert eco.texto == "mandei pelo celular" and eco.phone_number_id == NUMERO


async def test_celular_parado_desconecta_e_a_tela_diz_o_que_fazer(db, credencial, meta):
    assert (await _conectar(db)).ok
    _evento(db, _change("account_update", {
        "event": "PARTNER_REMOVED",
        "waba_info": {"waba_id": WABA, "owner_business_id": "1"},
        "disconnection_info": {"reason": "PRIMARY_INACTIVITY", "initiated_by": "SYSTEM"},
    }))
    conta = db.scalar(select(Conta))
    assert not conta.conectada and conta.token_cifrado is None
    assert "14 dias" in conta.detalhe


def test_offboarded_sem_waba_nao_chuta_numero(db):
    """O `ACCOUNT_OFFBOARDED` documentado não diz qual WABA — derrubar uma seria chute."""
    db.add(Conta(phone_number_id=NUMERO, waba_id=WABA, gs_user_id=TECNICO_A,
                 token_cifrado=cripto.cifrar("t"), estado="conectada"))
    db.commit()
    _evento(db, _change("account_update", {"event": "ACCOUNT_OFFBOARDED"}))
    assert db.scalar(select(Conta)).conectada
