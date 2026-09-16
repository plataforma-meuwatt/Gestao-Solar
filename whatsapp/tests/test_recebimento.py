"""O que a entrega da Meta vira no banco — e o que NÃO vira duas vezes.

Três formas de errar que estes testes fecham, todas silenciosas em produção:

* reentrega virando segunda mensagem no celular de alguém;
* status atrasado fazendo a tela dizer "enviada" sobre mensagem já lida;
* evento que falhou no meio ficando para sempre invisível.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from gateway.models.mensagem import Mensagem, WebhookEvento, avanca
from gateway.services import recebimento


def _corpo_mensagem(wamid="wamid.AAA", texto="olá", wa_id="5516999998888") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa_id, "profile": {"name": "Renan"}}],
                            "messages": [
                                {"from": wa_id, "id": wamid, "timestamp": "1789000000",
                                 "type": "text", "text": {"body": texto}}
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _corpo_status(wamid: str, status: str, quando: str = "1789000100") -> dict:
    return {
        "entry": [
            {"changes": [{"value": {"statuses": [{"id": wamid, "status": status, "timestamp": quando}]}}]}
        ]
    }


def test_mensagem_recebida_vira_linha(db):
    evento = recebimento.guardar(db, _corpo_mensagem())
    recebimento.processar(db, evento)

    m = db.scalar(select(Mensagem))
    assert m.wamid == "wamid.AAA"
    assert m.direcao == "entrada"
    assert m.telefone == "+5516999998888"
    assert m.nome_perfil == "Renan"
    assert m.status == "recebida"
    assert evento.processado_em is not None


def test_reentrega_da_meta_nao_duplica(db):
    """A Meta reenvia o que demora a responder. Reenvio não pode virar segunda mensagem."""
    for _ in range(3):
        evento = recebimento.guardar(db, _corpo_mensagem())
        recebimento.processar(db, evento)

    assert db.query(Mensagem).count() == 1
    assert db.query(WebhookEvento).count() == 3  # as entregas ficam registradas


def test_status_avanca_mas_nao_regride(db):
    evento = recebimento.guardar(db, _corpo_mensagem(wamid="wamid.OUT"))
    recebimento.processar(db, evento)
    m = db.scalar(select(Mensagem))
    m.direcao = "saida"
    m.status = "enviada"
    db.commit()

    recebimento.processar(db, recebimento.guardar(db, _corpo_status("wamid.OUT", "read")))
    assert db.scalar(select(Mensagem)).status == "lida"

    # O aviso de entrega chega DEPOIS do de leitura com frequência. Regravar faria a tela
    # dizer "entregue" sobre uma mensagem que o cliente já leu.
    recebimento.processar(db, recebimento.guardar(db, _corpo_status("wamid.OUT", "delivered")))
    assert db.scalar(select(Mensagem)).status == "lida"


def test_falha_grava_codigo_e_motivo(db):
    evento = recebimento.guardar(db, _corpo_mensagem(wamid="wamid.F"))
    recebimento.processar(db, evento)
    m = db.scalar(select(Mensagem))
    m.direcao, m.status = "saida", "enviada"
    db.commit()

    corpo = {
        "entry": [
            {"changes": [{"value": {"statuses": [
                {"id": "wamid.F", "status": "failed", "timestamp": "1789000200",
                 "errors": [{"code": 131026, "title": "Message undeliverable"}]}
            ]}}]}
        ]
    }
    recebimento.processar(db, recebimento.guardar(db, corpo))

    m = db.scalar(select(Mensagem))
    assert m.status == "falhou" and m.erro_codigo == "131026"


def test_status_de_mensagem_desconhecida_nao_inventa_linha(db):
    """O número pode ser usado por outro sistema — status alheio não é mensagem nossa."""
    recebimento.processar(db, recebimento.guardar(db, _corpo_status("wamid.DESCONHECIDA", "delivered")))
    assert db.query(Mensagem).count() == 0


def test_varredura_retoma_o_que_ficou_pendente(db):
    """Deploy no meio do processamento: a linha fica, e a varredura a pega."""
    evento = recebimento.guardar(db, _corpo_mensagem(wamid="wamid.PEND"))
    assert evento.processado_em is None

    assert recebimento.varrer(db) == 1
    assert db.query(Mensagem).count() == 1
    # Segunda volta não tem o que fazer.
    assert recebimento.varrer(db) == 0


def test_evento_com_corpo_impossivel_fica_marcado_e_nao_derruba(db):
    evento = WebhookEvento(corpo={"entry": "isto não é lista"})
    db.add(evento)
    db.commit()

    recebimento.processar(db, evento)
    # Não levantou, e o parser simplesmente não achou nada para gravar.
    assert db.query(Mensagem).count() == 0
    assert evento.processado_em is not None


def test_ordem_do_status_e_explicita():
    assert avanca("pendente", "enviada")
    assert avanca("enviada", "entregue")
    assert not avanca("lida", "entregue")
    assert avanca("enviada", "falhou")
    # Depois de falhar, um status antigo não ressuscita a mensagem.
    assert not avanca("falhou", "entregue")
    assert not avanca("enviada", "inventado")


def test_hora_vem_da_meta_e_nao_do_servidor(db):
    evento = recebimento.guardar(db, _corpo_mensagem())
    recebimento.processar(db, evento)
    m = db.scalar(select(Mensagem))

    # O SQLite destes testes não guarda fuso — em produção a coluna é `timestamptz` —, então
    # depois do commit a leitura volta ingênua. O que o teste protege é o INSTANTE: a hora é
    # a que a Meta mandou no `timestamp`, e não a do relógio do servidor ao processar. É ela
    # que conta a janela de 24 h, e um evento reprocessado amanhã não pode "rejuvenescer".
    lida = m.ocorrida_em
    if lida.tzinfo is None:
        lida = lida.replace(tzinfo=UTC)
    assert lida == datetime.fromtimestamp(1789000000, tz=UTC)
