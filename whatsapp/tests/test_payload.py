"""Ler o corpo da Meta sem quebrar com o que ele traz de verdade.

Os payloads aqui são a forma real: tudo aninhado em listas, o nome do perfil numa lista
irmã, o timestamp em epoch como TEXTO. Cada teste corresponde a um jeito de o parser errar
calado — e calado é o que importa: mensagem perdida não dá erro em lugar nenhum.
"""

from datetime import UTC, datetime

from gateway.meta import payload


def _entrega(*valores: dict) -> dict:
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": v} for v in valores]}]}


def test_mensagem_de_texto_com_nome_do_perfil():
    corpo = _entrega(
        {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "5516999998888", "profile": {"name": "Renan"}}],
            "messages": [
                {
                    "from": "5516999998888",
                    "id": "wamid.AAA",
                    "timestamp": "1789000000",
                    "type": "text",
                    "text": {"body": "quanto minha usina gerou?"},
                }
            ],
        }
    )
    leitura = payload.ler(corpo)

    assert len(leitura.mensagens) == 1
    m = leitura.mensagens[0]
    assert m.wamid == "wamid.AAA"
    assert m.texto == "quanto minha usina gerou?"
    assert m.nome_perfil == "Renan"
    assert m.ocorrida_em == datetime.fromtimestamp(1789000000, tz=UTC)


def test_varias_entregas_no_mesmo_corpo():
    """Todos os níveis são listas — percorrer com [0] funciona no exemplo e falha no uso."""
    corpo = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "551199990000", "id": "wamid.A", "timestamp": "1789000000",
                                 "type": "text", "text": {"body": "um"}}
                            ]
                        }
                    },
                    {
                        "value": {
                            "messages": [
                                {"from": "551199991111", "id": "wamid.B", "timestamp": "1789000001",
                                 "type": "text", "text": {"body": "dois"}}
                            ]
                        }
                    },
                ]
            },
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid.C", "status": "delivered", "timestamp": "1789000002"}
                            ]
                        }
                    }
                ]
            },
        ]
    }
    leitura = payload.ler(corpo)
    assert [m.wamid for m in leitura.mensagens] == ["wamid.A", "wamid.B"]
    assert [s.wamid for s in leitura.status] == ["wamid.C"]


def test_tipo_sem_texto_entra_com_o_tipo_preenchido():
    """Áudio não vira mensagem vazia nem some: quem exibe escreve "Áudio"."""
    corpo = _entrega(
        {
            "messages": [
                {"from": "5516999998888", "id": "wamid.AUD", "timestamp": "1789000000",
                 "type": "audio", "audio": {"id": "midia-123"}}
            ]
        }
    )
    m = payload.ler(corpo).mensagens[0]
    assert m.tipo == "audio" and m.texto is None
    # O id do arquivo fica guardado: é com ele que o bot baixa a nota de voz para transcrever.
    assert m.midia == {"id": "midia-123", "mime": None, "nome": None, "legenda": None}


def test_documento_guarda_nome_e_legenda_e_reacao_nao_tem_arquivo():
    corpo = _entrega({"messages": [
        {"from": "5516999998888", "id": "wamid.DOC", "timestamp": "1789000000", "type": "document",
         "document": {"id": "m-9", "mime_type": "application/pdf", "filename": "projeto.pdf", "caption": "o novo"}},
        {"from": "5516999998888", "id": "wamid.REA", "timestamp": "1789000001", "type": "reaction",
         "reaction": {"message_id": "wamid.X", "emoji": "👍"}},
    ]})
    doc, reacao = payload.ler(corpo).mensagens
    assert doc.midia == {"id": "m-9", "mime": "application/pdf", "nome": "projeto.pdf", "legenda": "o novo"}
    assert reacao.tipo == "reaction" and reacao.midia is None


def test_resposta_de_botao_vira_texto():
    corpo = _entrega(
        {
            "messages": [
                {"from": "5516999998888", "id": "wamid.BTN", "timestamp": "1789000000",
                 "type": "interactive",
                 "interactive": {"type": "button_reply", "button_reply": {"id": "sim:a1b2c3d4", "title": "Sim"}}}
            ]
        }
    )
    m = payload.ler(corpo).mensagens[0]
    # O título é o texto; o id diz de QUAL resumo era o botão (avaliação 13).
    assert (m.texto, m.botao) == ("Sim", "sim:a1b2c3d4")


def test_status_traduzido_e_erro_lido():
    corpo = _entrega(
        {
            "statuses": [
                {"id": "wamid.X", "status": "failed", "timestamp": "1789000000",
                 "errors": [{"code": 131047, "title": "Re-engagement message",
                             "error_data": {"details": "fora da janela de 24 h"}}]}
            ]
        }
    )
    s = payload.ler(corpo).status[0]
    assert s.status == "falhou"
    assert s.erro_codigo == "131047"
    assert "24 h" in s.erro_detalhe


def test_corpo_torto_nao_levanta():
    """A Meta muda formato sem avisar; o que não dá para ler é ignorado, não explode."""
    for corpo in ({}, {"entry": None}, {"entry": [{"changes": "nada"}]}, {"entry": [{}]}):
        leitura = payload.ler(corpo)
        assert leitura.mensagens == [] and leitura.status == []


def test_mensagem_sem_id_ou_sem_remetente_e_descartada():
    """Sem `wamid` não há idempotência possível — gravar criaria linha que se duplica."""
    corpo = _entrega({"messages": [{"timestamp": "1789000000", "type": "text"}]})
    assert payload.ler(corpo).mensagens == []
