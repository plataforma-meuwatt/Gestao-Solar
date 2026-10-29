"""Bot: o Excel de energia diária por inversor vai como ARQUIVO no WhatsApp, com o veredito da
validação contra a plataforma do inversor (mw-api `exports/energia_diaria.py`). Diferença acima de
0,5% tem de chegar à pessoa como "precisam ser revisados" — não pode sumir no caminho."""

from datetime import date

from app.services import assistente_geracao as ger

PF = {"porto-ferreira": {"id": 9378, "nome": "Porto Ferreira", "slug": "porto-ferreira"}}


class MW:
    def __init__(self, validacao):
        self.validacao, self.pedidos = validacao, []

    async def energia_diaria(self, slug, inicio, fim):
        self.pedidos.append((slug, inicio, fim))
        return b"PK-xlsx", {"validacao": self.validacao, "erro_pct": "0.800",
                            "mensagem": "Os dados precisam ser revisados: a usina difere 0,80% da plataforma"}


async def test_manda_o_xlsx_e_repassa_o_revisar(monkeypatch):
    enviados = []

    async def enviar(**kw):
        enviados.append(kw)
        return {"ok": True}

    monkeypatch.setattr("app.clients.whatsapp.enviar_conteudo", enviar)
    mw = MW("revisar")
    ctx = ger.Contexto(db=None, user=None, telefone="+5516999998888", mw=mw, usinas=PF)
    r = await ger.excel_energia_diaria(ctx, {"usina": "porto", "inicio": "2026-10-01", "fim": "2026-10-27"})

    assert mw.pedidos == [("porto-ferreira", date(2026, 10, 1), date(2026, 10, 27))]
    assert enviados[0]["tipo"] == "document" and enviados[0]["arquivo"] == b"PK-xlsx"
    assert enviados[0]["mime"].endswith("spreadsheetml.sheet") and enviados[0]["filename"].endswith(".xlsx")
    assert r["enviado_no_chat"] and r["validacao"] == "revisar"
    assert "precisam ser revisados" in r["mensagem_da_validacao"] and "REVISADOS" in r["nota"]
    assert ctx.enviados == [r["arquivo"]]


async def test_sem_datas_e_o_mes_ate_hoje(monkeypatch):
    async def enviar(**kw):
        return {"ok": True}

    monkeypatch.setattr("app.clients.whatsapp.enviar_conteudo", enviar)
    monkeypatch.setattr(ger, "hoje", lambda: date(2026, 10, 29))
    mw = MW("ok")
    await ger.excel_energia_diaria(ger.Contexto(db=None, user=None, telefone="+55", mw=mw, usinas=PF), {})
    assert mw.pedidos == [("porto-ferreira", date(2026, 10, 1), date(2026, 10, 29))]


def test_o_bot_conhece_a_ferramenta():
    from app.services import assistente

    assert "excel_energia_diaria" in assistente.FERRAMENTAS
