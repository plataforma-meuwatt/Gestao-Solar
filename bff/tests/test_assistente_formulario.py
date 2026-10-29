"""Opções do meuPlano viram um formulário de MARCAR no WhatsApp. Pedido do Renan (29/10/2026): "não tem como ele
enviar a lista e eu clico só nas que quero deixar?"."""

import json

import pytest

from app.clients import whatsapp
from app.services import assistente
from app.services import assistente_formulario as formulario
from app.services import assistente_geracao as ger
from app.services import vinculos
from tests.test_assistente_whatsapp import _conta, bot_local  # noqa: F401 (bot_local é fixture)

ESCOLHA = {"titulo": "Centros de custo do Comissionamento #1736 «UFV Mairinque»",
           "opcoes": ["Lavagem", "Manutenção Preventiva", "Roçagem"], "marcados": ["Roçagem"],
           "responda": "Deixe marcados nos centros de custo do contrato #1736", "aviso": "Nenhum marcado = todos liberados."}


@pytest.fixture
def cenario(db, bot_local, monkeypatch):
    """A IA de mentira manda tudo ao meuPlano; o meuPlano de mentira responde com a escolha na 1ª pergunta."""
    forms, perguntas, escolha = [], [], {"valor": ESCOLHA}
    enviar = whatsapp.enviar_conteudo

    async def _enviar(**k):
        if k.get("tipo") == "formulario":
            forms.append(k)
            return {"ok": escolha.get("gateway_ok", True)}
        return await enviar(**k)

    async def _perguntar(mp, mensagens):
        perguntas.append(mensagens[-1]["content"].split("\n\n(Resposta para WhatsApp")[0])
        return {"texto": "Marque no formulário.", **({"escolha": escolha["valor"]} if len(perguntas) == 1 else {})}

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": json.loads(msgs[-1]["content"]).get("texto", "")}
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "manutencao", "arguments": json.dumps({"pergunta": msgs[-1]["content"]})}}]}

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente, "_perguntar_ao_meuplano", _perguntar)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: object())
    formulario._ABERTOS.clear()
    return forms, perguntas, escolha


def _texto(p, n, texto):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "text", "texto": texto}


def _marcou(p, n, token, *ids):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "interactive", "texto": None,
            "midia": {"formulario": {"escolhidos": list(ids), "flow_token": token}}}


async def test_as_opcoes_vao_num_formulario_e_o_que_volta_segue_como_pedido(db, bot_local, cenario):
    forms, perguntas, _ = cenario
    p = _conta(db, "renan", "+5517997377626")
    await assistente.atender(_texto(p, 1, "Quero mudar os centros de custo do 1736"))
    assert bot_local.enviados[-1] == "Marque no formulário."           # a resposta, e depois o formulário
    f = forms[0]["formulario"]
    assert (f["opcoes"], f["marcados"], f["titulo"]) == (ESCOLHA["opcoes"], ["Roçagem"], ESCOLHA["titulo"])
    # o de outro envio (token de outro formulário) não vale, e o aberto continua valendo
    await assistente.atender(_marcou(p, 2, "token-de-outro", "1"))
    assert bot_local.enviados[-1] == formulario.VENCIDO and len(perguntas) == 1
    # o que a pessoa marcou volta em palavras, em ordem, e vai ao meuPlano como o pedido dela
    await assistente.atender(_marcou(p, 4, f["token"], "2", "0", "9", "x"))
    assert perguntas[-1] == "Deixe marcados nos centros de custo do contrato #1736: Lavagem, Roçagem"
    # o mesmo formulário de novo (ou um antigo) não vale
    await assistente.atender(_marcou(p, 5, f["token"], "1"))
    assert bot_local.enviados[-1] == formulario.VENCIDO and len(perguntas) == 2


async def test_nada_marcado_e_todos_liberados(db, bot_local, cenario):
    forms, perguntas, _ = cenario
    p = _conta(db, "renan", "+5517997377626")
    await assistente.atender(_texto(p, 1, "centros de custo do 1736"))
    await assistente.atender(_marcou(p, 2, forms[0]["formulario"]["token"]))
    assert perguntas[-1].endswith("#1736: todos liberados (nenhum marcado)")


async def test_sem_o_formulario_vai_a_lista_em_texto(db, bot_local, cenario):
    forms, _, escolha = cenario
    escolha["gateway_ok"] = False
    p = _conta(db, "renan", "+5517997377626")
    await assistente.atender(_texto(p, 1, "centros de custo do 1736"))
    assert bot_local.enviados[-1] == formulario.em_texto(ESCOLHA)
    assert "• Roçagem ✔" in bot_local.enviados[-1] and "• Lavagem\n" in bot_local.enviados[-1]
    assert formulario._ABERTOS == {}


@pytest.mark.parametrize("ruim", [None, {"opcoes": [], "responda": "x"}, {"opcoes": ["a"] * 21, "responda": "x"},
                                  {"opcoes": ["a"]}])
async def test_escolha_torta_nao_vira_formulario(db, bot_local, cenario, ruim):
    forms, _, escolha = cenario
    escolha["valor"] = ruim
    p = _conta(db, "renan", "+5517997377626")
    await assistente.atender(_texto(p, 1, "centros de custo do 1736"))
    assert forms == [] and bot_local.enviados[-1] == "Marque no formulário."
