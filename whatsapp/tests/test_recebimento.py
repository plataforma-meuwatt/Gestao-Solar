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


# ── outubro de 2026: um evento que estoura não pode calar o bot ──────────────


def test_wamid_de_82_caracteres_cabe(db):
    """A Meta passou a mandar `wamid` de 82 caracteres; a coluna tinha 80."""
    from gateway.models.mensagem import Mensagem as M

    assert M.__table__.c.wamid.type.length >= 82


def test_evento_que_estoura_no_banco_nao_trava_os_outros(db, monkeypatch):
    """O INSERT estourava no commit, FORA do try: o evento ficava com `tentativas=0` e a
    volta inteira caía. Agora o erro fica no evento e os seguintes andam."""
    ruim = recebimento.guardar(db, _corpo_mensagem(wamid="wamid.RUIM"))
    bom = recebimento.guardar(db, _corpo_mensagem(wamid="wamid.BOM", texto="oi"))
    original = recebimento._aplicar_mensagem

    def _estoura_no_ruim(sessao, m):
        if m.wamid == "wamid.RUIM":
            raise RuntimeError("StringDataRightTruncation simulado")
        return original(sessao, m)

    monkeypatch.setattr(recebimento, "_aplicar_mensagem", _estoura_no_ruim)
    assert recebimento.varrer(db) == 2
    db.refresh(ruim)
    db.refresh(bom)
    assert ruim.processado_em is None and ruim.tentativas == 1 and "Truncation" in ruim.erro
    assert bom.processado_em is not None
    assert db.scalar(select(Mensagem).where(Mensagem.wamid == "wamid.BOM")) is not None


def test_evento_que_falha_sempre_sai_da_fila_depois_de_10_tentativas(db):
    evento = recebimento.guardar(db, _corpo_mensagem(wamid="wamid.X"))
    evento.tentativas = recebimento.MAX_TENTATIVAS
    db.commit()
    assert recebimento.varrer(db) == 0


async def test_aviso_ao_bff_roda_mesmo_se_a_varredura_cair(db, monkeypatch):
    """O defeito que calou o bot: varrer e avisar no MESMO try — varrer caía, avisar nunca rodava."""
    from gateway import main
    from gateway.services import notificacao_bff

    chamados = []

    def _cai(_db):
        raise RuntimeError("varredura ruim")

    async def _avisa(_db):
        chamados.append("mensagens")
        return 1

    async def _status(_db):
        chamados.append("status")
        return 0

    monkeypatch.setattr(main.recebimento, "varrer", _cai)
    monkeypatch.setattr(notificacao_bff, "avisar_pendentes", _avisa)
    monkeypatch.setattr(notificacao_bff, "avisar_status_pendentes", _status)
    assert await main.uma_volta(db) == (0, 1)
    assert chamados == ["mensagens", "status"]
