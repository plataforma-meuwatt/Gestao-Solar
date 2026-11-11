"""O relatório mensal pelo bot quando a equipe ainda não o emitiu (o Renan, 11/11/2026: "somente quando pedir por
WhatsApp ou bot … será enviado, porém, com marca 'relatório não revisado'"): sem relatório no mês, o bot pede o PDF não
revisado ao gerador do srvclaude (pelo túnel, com o token do meuWatt DA PESSOA) e manda com a marca; com relatório
emitido, manda o arquivo de sempre; resumo executivo não tem versão não revisada."""

from types import SimpleNamespace

from app.services import assistente_geracao as ger


class MW:
    def __init__(self, rel=None):
        self.rel = rel

    async def relatorio_existente(self, slug, periodo, de):
        return self.rel

    async def arquivo_relatorio(self, rid, kind):
        return b"%PDF-emitido"


def _ctx(rel=None):
    ctx = ger.Contexto(db=SimpleNamespace(), user=SimpleNamespace(id=7), telefone="+5517999990000", mw=MW(rel))
    ctx.usinas = {"tiete": {"nome": "Tiete", "slug": "tiete"}}
    return ctx


def _patch(monkeypatch, pdf=b"%PDF-nao-revisado", erro=None, token="mw_pat_dela"):
    enviados, pedidos = [], []

    async def enviar(**k):
        enviados.append(k)
        return {"ok": True}

    async def gera(base, chamador, chave, tok, usina, mes, doc, espera_s=560):
        pedidos.append((tok, usina, mes, doc))
        return (pdf, f"{doc} - Tiete - NÃO REVISADO.pdf", None) if pdf else (None, None, erro)

    monkeypatch.setattr("app.clients.whatsapp.enviar_conteudo", enviar)
    monkeypatch.setattr("app.clients.helper_bot.relatorio_nao_revisado", gera)
    monkeypatch.setattr("app.services.vinculos.token_do_cliente", lambda db, uid, prod, so_proprio=False: token)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(
        helper_bot_url="http://10.0.1.1:18080", helper_bot_chamador="gestao-solar", helper_bot_chave="k"))
    monkeypatch.setattr(ger, "_usina", lambda ctx, nome: ctx.usinas["tiete"])
    return enviados, pedidos


async def test_sem_relatorio_vai_o_nao_revisado_com_o_token_dela(monkeypatch):
    enviados, pedidos = _patch(monkeypatch)
    ctx = _ctx()
    r = await ger.relatorio_pdf(ctx, {"usina": "tiete", "mes": "2026-10", "tipo": "geracao"})
    assert pedidos == [("mw_pat_dela", "tiete", "2026-10", "geracao")]
    assert r["nao_revisado"] is True and r["enviado_no_chat"] is True and "NÃO FOI REVISADO" in r["nota"]
    assert enviados[0]["tipo"] == "text" and "NÃO REVISADA" in enviados[0]["texto"]        # o aviso de que demora
    assert enviados[1]["tipo"] == "document" and enviados[1]["arquivo"] == b"%PDF-nao-revisado"
    assert "RELATÓRIO NÃO REVISADO" in enviados[1]["texto"] and ctx.enviados == [enviados[1]["filename"]]


async def test_anexo_de_paradas_sem_aviso_de_espera(monkeypatch):
    enviados, pedidos = _patch(monkeypatch)
    await ger.relatorio_pdf(_ctx(), {"usina": "tiete", "mes": "2026-10", "tipo": "paradas"})
    assert pedidos[0][3] == "paradas" and [e["tipo"] for e in enviados] == ["document"]


async def test_relatorio_emitido_vai_o_de_sempre(monkeypatch):
    enviados, pedidos = _patch(monkeypatch)
    rel = {"id": 55, "files": [{"kind": "geracao", "filename": "Relatorio-Geracao.pdf"}]}
    r = await ger.relatorio_pdf(_ctx(rel), {"usina": "tiete", "mes": "2026-10", "tipo": "geracao"})
    assert pedidos == [] and r.get("nao_revisado") is None
    assert enviados[0]["arquivo"] == b"%PDF-emitido"


async def test_resumo_nao_tem_versao_nao_revisada(monkeypatch):
    enviados, pedidos = _patch(monkeypatch)
    r = await ger.relatorio_pdf(_ctx(), {"usina": "tiete", "mes": "2026-10", "tipo": "resumo"})
    assert pedidos == [] and enviados == [] and "Não há relatório" in r["erro"]


async def test_gerador_falhou_diz_por_que(monkeypatch):
    enviados, _ = _patch(monkeypatch, pdf=None, erro="o documento não ficou pronto a tempo")
    r = await ger.relatorio_pdf(_ctx(), {"usina": "tiete", "mes": "2026-10", "tipo": "paradas"})
    assert "não ficou pronto a tempo" in r["erro"] and enviados == []
