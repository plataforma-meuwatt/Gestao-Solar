"""O motor: quem recebe, o que impede repetir, e o que o log guarda.

Os coletores são substituídos por um evento fixo — o que se prova aqui é a metade que o
sistema controla: destinatários, trava de repetição, gravação e trilha de status. Bater no
meuWatt para descobrir se um inversor está parado é trabalho da bateria de autoteste, que
roda contra o ambiente real.
"""

from datetime import UTC, datetime

import pytest

from app.models.contato import ContatoPreferencia, ContatoUsina
from app.models.notificacao import NotificacaoEnviada, NotificacaoPreferencia
from app.models.user import Perfil, User, UserPlantAccess
from app.services import motor
from app.services import notificacoes as catalogo

EVENTO = motor.Evento(
    tipo="parada",
    plant_link_id=0,  # trocado pelo fixture
    chave="parada:teste:1",
    parametros=["Porto Ferreira", "Inversor 3", "14:12"],
)


@pytest.fixture
def cenario(db, usinas, administrador):
    """Uma usina, um cliente apto com o aviso marcado, e um contato apto idem."""
    usina, _ = usinas
    cliente = User(
        apelido="dono",
        nome="Dono da Usina",
        perfil=Perfil.CLIENTE,
        telefone="+5516999990000",
        whatsapp_aceite_em=datetime.now(UTC),
    )
    db.add(cliente)
    db.commit()
    db.add(UserPlantAccess(user_id=cliente.id, plant_link_id=usina.id))
    db.add(NotificacaoPreferencia(user_id=cliente.id, tipo="parada", plant_link_id=usina.id))

    contato = ContatoUsina(
        plant_link_id=usina.id,
        nome="Engenheiro da planta",
        telefone="+5516988880000",
        papel="Engenheiro",
        aceite_em=datetime.now(UTC),
        aceite_por=administrador.id,
    )
    db.add(contato)
    db.commit()
    db.add(ContatoPreferencia(contato_id=contato.id, tipo="parada"))
    db.commit()
    return usina, cliente, contato


@pytest.fixture
def envio_falso(monkeypatch):
    """Guarda o que teria sido enviado, e responde como o gateway responde."""
    enviados: list[dict] = []

    async def fake(*, telefone, template, parametros, origem=None):
        enviados.append(
            {"telefone": telefone, "template": template, "parametros": parametros, "origem": origem}
        )
        return {"ok": True, "wamid": f"wamid-{len(enviados)}", "status": "enviada", "erro": None}

    monkeypatch.setattr(motor.gateway, "enviar_template", fake)
    return enviados


def _coletor_fixo(usina_id: int):
    async def coletar(db, rel):
        return [
            motor.Evento(
                tipo="parada",
                plant_link_id=usina_id,
                chave=EVENTO.chave,
                parametros=EVENTO.parametros,
            )
        ]

    return coletar


@pytest.mark.asyncio
async def test_avisa_o_cliente_e_os_contatos_da_usina(db, cenario, envio_falso, monkeypatch):
    """O que substituiu o grupo de WhatsApp: cada pessoa recebe no privado."""
    usina, cliente, contato = cenario
    monkeypatch.setitem(motor.COLETORES, "parada", _coletor_fixo(usina.id))

    rel = await motor.disparar(db, tipos=["parada"])

    assert rel.enviadas == 2
    assert {e["telefone"] for e in envio_falso} == {cliente.telefone, contato.telefone}
    assert {e["template"] for e in envio_falso} == {"gs_usina_parada"}

    linhas = db.query(NotificacaoEnviada).all()
    assert len(linhas) == 2
    # Uma linha por destinatário, cada uma na sua coluna — é o que mantém o log por pessoa.
    assert {(l.user_id, l.contato_id) for l in linhas} == {(cliente.id, None), (None, contato.id)}
    assert {l.status for l in linhas} == {"enviada"}
    assert all(l.wamid for l in linhas)


@pytest.mark.asyncio
async def test_rodar_de_novo_nao_manda_de_novo(db, cenario, envio_falso, monkeypatch):
    """A trava é do EVENTO, não da execução: o agendador roda a cada dez minutos."""
    usina, _, _ = cenario
    monkeypatch.setitem(motor.COLETORES, "parada", _coletor_fixo(usina.id))

    await motor.disparar(db, tipos=["parada"])
    rel = await motor.disparar(db, tipos=["parada"])

    assert rel.enviadas == 0
    assert rel.repetidas == 2
    assert len(envio_falso) == 2  # nada novo saiu
    assert db.query(NotificacaoEnviada).count() == 2


@pytest.mark.asyncio
async def test_simular_percorre_tudo_e_nao_envia(db, cenario, envio_falso, monkeypatch):
    """É o modo que a bateria de autoteste usa: prova o caminho sem acordar ninguém."""
    usina, _, _ = cenario
    monkeypatch.setitem(motor.COLETORES, "parada", _coletor_fixo(usina.id))

    rel = await motor.disparar(db, tipos=["parada"], simular=True)

    assert rel.simuladas == 2
    assert rel.enviadas == 0
    assert envio_falso == []
    assert db.query(NotificacaoEnviada).count() == 0


@pytest.mark.asyncio
async def test_sem_aceite_ninguem_recebe(db, cenario, envio_falso, monkeypatch):
    """Ausência de aceite silencia, por mais que a preferência esteja marcada."""
    usina, cliente, contato = cenario
    cliente.whatsapp_aceite_em = None
    contato.aceite_em = None
    db.commit()
    monkeypatch.setitem(motor.COLETORES, "parada", _coletor_fixo(usina.id))

    rel = await motor.disparar(db, tipos=["parada"])

    assert rel.enviadas == 0
    assert envio_falso == []


@pytest.mark.asyncio
async def test_falha_da_meta_vira_linha_no_log(db, cenario, monkeypatch):
    """O log existe para responder POR QUE não chegou — e isso exige gravar a recusa."""
    usina, _, _ = cenario
    monkeypatch.setitem(motor.COLETORES, "parada", _coletor_fixo(usina.id))

    async def recusa(*, telefone, template, parametros, origem=None):
        return {"ok": False, "wamid": None, "status": "falhou", "erro": "131047: fora da janela"}

    monkeypatch.setattr(motor.gateway, "enviar_template", recusa)
    rel = await motor.disparar(db, tipos=["parada"])

    assert rel.falhas == 2
    linhas = db.query(NotificacaoEnviada).all()
    assert {l.status for l in linhas} == {"falhou"}
    assert all("131047" in (l.erro or "") for l in linhas)


@pytest.mark.asyncio
async def test_usina_de_outro_cliente_nao_gera_aviso(db, cenario, envio_falso, monkeypatch):
    """Escopo é reconferido no envio: entre marcar e enviar, a usina pode ter mudado de dono."""
    usina, cliente, _ = cenario
    db.query(UserPlantAccess).filter(UserPlantAccess.user_id == cliente.id).delete()
    db.commit()
    monkeypatch.setitem(motor.COLETORES, "parada", _coletor_fixo(usina.id))

    rel = await motor.disparar(db, tipos=["parada"])

    # O contato da usina continua recebendo: ele é da USINA, e não do cliente que saiu.
    assert {e["telefone"] for e in envio_falso} == {"+5516988880000"}
    assert rel.enviadas == 1


def test_status_so_anda_para_frente(db, cenario):
    """Entregas da Meta chegam fora de ordem; um 'entregue' atrasado não pode apagar 'lida'."""
    _, cliente, _ = cenario
    linha = NotificacaoEnviada(
        user_id=cliente.id, tipo="parada", chave="x", canal="whatsapp",
        destino=cliente.telefone, status="enviada", wamid="w1",
    )
    db.add(linha)
    db.commit()

    assert motor.registrar_status(db, "w1", "lida") is True
    assert motor.registrar_status(db, "w1", "entregue") is False
    db.refresh(linha)
    assert linha.status == "lida"


def test_status_de_wamid_desconhecido_nao_estoura(db):
    """O mesmo número manda teste da tela e atendimento humano: nem todo wamid é aviso."""
    assert motor.registrar_status(db, "nao-existe", "entregue") is False
