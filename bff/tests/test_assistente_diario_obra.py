"""Fotos do WhatsApp no DIÁRIO DE OBRA (27/11/2026): a foto com a frase da obra ("hoje concretamos 40 estacas da quadra
B") vai junto da anotação que o meuPlano propõe (`anotar_diario_de_obra`); depois do Sim, cada foto sobe em
`POST /rdo/{rdo_id}/fotos` com o `registro_id` da anotação e o token da pessoa. Outra ação (conta de energia, fechar OS)
não leva as fotos."""

import httpx
import pytest

from app.clients import whatsapp
from app.services import assistente
from app.services import assistente_fotos as fotos
from app.services import assistente_geracao as ger
from app.services import assistente_helper as h
from app.services import vinculos
from tests.test_assistente_whatsapp import _conta  # noqa: F401

PROPOSTA = {"action": "anotar_diario_de_obra",
            "args": {"obra": "Cerca Ibitinga", "texto": "concretamos 40 estacas da quadra B", "quantidade": 40},
            "preview": {"summary": "Anotar no diário da obra Cerca Ibitinga (27/11/2026)",
                        "lines": [{"kind": "obra", "text": "Obra: Cerca Ibitinga"},
                                  {"kind": "etapa", "text": "Etapa: Estacas quadra B"}]}}


class _MeuPlano:
    def __init__(self, falha_em=(), acao_falha=False):
        self.aplicadas, self.fotos, self.falha_em, self.acao_falha = [], [], set(falha_em), acao_falha

    async def assistente_aplicar(self, token, acao, args):
        self.aplicadas.append(acao)
        if self.acao_falha:
            req = httpx.Request("POST", "https://mp/api/v1/meuacesso/assistant/apply")
            raise httpx.HTTPStatusError("400", request=req, response=httpx.Response(
                400, request=req, json={"detail": "Nenhuma etapa da obra casa 'quadra Z'."}))
        if acao == "anotar_diario_de_obra":
            return {"data": {"rdo_id": 77, "registro_id": 555, "mensagem": "Anotado."}}
        return {"data": {}}

    async def foto_no_diario(self, rdo_id, registro_id, nome, conteudo, tipo, legenda):
        if conteudo in self.falha_em:
            req = httpx.Request("POST", f"https://mp/api/v1/meuacesso/rdo/{rdo_id}/fotos")
            raise httpx.HTTPStatusError("400", request=req, response=httpx.Response(
                400, request=req, json={"detail": "Arquivo vazio."}))
        self.fotos.append((rdo_id, registro_id, conteudo, tipo, legenda))
        return {"id": len(self.fotos)}


@pytest.fixture
def cena(db, monkeypatch):
    def montar(mp):
        monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)

        async def _baixar(mid):
            return f"JPG{mid}".encode(), "image/jpeg"
        monkeypatch.setattr(whatsapp, "baixar_midia", _baixar)
        dono = _conta(db, "dono", "+5517997377626")
        fotos._RECEBIDAS.pop(dono.telefone, None)
        for i in (11, 12):
            fotos.guardar(dono.telefone, {"id": i, "tipo": "image",
                                          "midia": {"legenda": "hoje concretamos 40 estacas da quadra B" if i == 11 else ""}})
        return dono
    yield montar
    fotos._RECEBIDAS.clear()


async def test_foto_e_texto_da_obra_vao_juntos_e_sobem_com_o_registro(db, cena):
    mp = _MeuPlano()
    dono = cena(mp)
    out = assistente._proposta_do_meuplano(ger.Contexto(db=db, user=dono, telefone=dono.telefone), PROPOSTA)
    assert out["detalhes"][-1] == "📷 2 foto(s) vão junto, ligada(s) a esta anotação"
    h.mostrada(dono.id)
    resposta = await h.confirmar_por_mensagem(db, dono, dono.telefone, "Sim")
    assert mp.aplicadas == ["anotar_diario_de_obra"]
    assert [(r, g, c) for r, g, c, _, _ in mp.fotos] == [(77, 555, b"JPG11"), (77, 555, b"JPG12")]
    assert resposta.startswith("✅ Feito no meuPlano: Anotar no diário")
    assert resposta.endswith("📷 2 foto(s) ligada(s) à etapa Estacas quadra B.")
    assert fotos.recebidas(dono.telefone) == []          # não vão de novo para outro lugar


async def test_foto_que_nao_sobe_e_dita(db, cena):
    mp = _MeuPlano(falha_em={b"JPG12"})
    dono = cena(mp)
    assistente._proposta_do_meuplano(ger.Contexto(db=db, user=dono, telefone=dono.telefone), PROPOSTA)
    h.mostrada(dono.id)
    resposta = await h.confirmar_por_mensagem(db, dono, dono.telefone, "Sim")
    assert len(mp.fotos) == 1
    assert "⚠️ 1 foto(s) de 2 ligada(s) à etapa Estacas quadra B; NÃO subiram:\n• foto 2: o meuPlano recusou " \
           "(Arquivo vazio)" in resposta
    assert [f["id"] for f in fotos.recebidas(dono.telefone)] == [12]   # a que não subiu fica para mandar de novo


async def test_anotacao_recusada_nao_sobe_foto_e_diz(db, cena):
    mp = _MeuPlano(acao_falha=True)
    dono = cena(mp)
    assistente._proposta_do_meuplano(ger.Contexto(db=db, user=dono, telefone=dono.telefone), PROPOSTA)
    h.mostrada(dono.id)
    resposta = await h.confirmar_por_mensagem(db, dono, dono.telefone, "Sim")
    assert mp.fotos == [] and resposta.startswith("❌ O meuPlano recusou")
    assert "As 2 foto(s) NÃO foram ao diário." in resposta


async def test_outra_acao_nao_leva_as_fotos(db, cena):
    """A conta de energia, anexar na tarefa, fechar OS: as fotos seguem o caminho de sempre."""
    mp = _MeuPlano()
    dono = cena(mp)
    out = assistente._proposta_do_meuplano(ger.Contexto(db=db, user=dono, telefone=dono.telefone),
                                           {"action": "fechar_os", "args": {"os_id": 1638},
                                            "preview": {"summary": "Fechar a OS 1638"}})
    assert not any("📷" in d for d in out["detalhes"])
    h.mostrada(dono.id)
    resposta = await h.confirmar_por_mensagem(db, dono, dono.telefone, "Sim")
    assert mp.fotos == [] and "📷" not in resposta and len(fotos.recebidas(dono.telefone)) == 2
