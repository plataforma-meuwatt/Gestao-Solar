"""O gráfico de geração do bot (`assistente_geracao.grafico`): a avaliação de 17/11/2026 pegou o eixo em "11-01" (que se
lê 11 de janeiro), o título com a data ISO e o texto sem nenhum número."""

import types

from app.clients import whatsapp
from app.services import assistente_geracao as ger


async def test_barras_de_energia_com_data_do_brasil_e_numeros(monkeypatch):
    enviados = []

    async def geracao(ctx, a):
        return {"usina": "Pirapozinho", "inicio": "2026-11-01", "fim": "2026-11-17", "inversores_do_melhor_ao_pior": [],
                "dias": [{"data": f"2026-11-{d:02d}", "energia_kwh": 14000.0 + d, "pr_pct": None} for d in range(1, 18)]}

    async def envia(**kw):
        enviados.append(kw)
        return {"ok": True}

    monkeypatch.setattr(ger, "geracao", geracao)
    monkeypatch.setattr(whatsapp, "enviar_conteudo", envia)
    r = await ger.grafico(ger.Contexto(db=None, user=types.SimpleNamespace(id=7), telefone="+5517999990000"),
                          {"tipo": "geracao_diaria"})
    assert r["grafico"] == "Pirapozinho · kWh · 01/11 a 17/11/2026" and enviados[0]["arquivo"][:4] == b"\x89PNG"
    assert r["maior"] == ["17/11", 14017.0] and r["menor"] == ["01/11", 14001.0] and r["total"] == 238153.0
