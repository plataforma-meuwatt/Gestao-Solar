"""O balanço de energia no bot (`balanco_energia`): a conta e o parecer vêm do meuWatt (`/energy-balance`, a mesma da
aba Balanço do Excel e do Claude); aqui, o período (mês fechado ou livre), o gráfico e o que cabe a quem pergunta — só o
gestor manda conta (o dono, 17/11/2026: "jamais o cliente pode enviar algo, eu gestor sim")."""

import types
from datetime import date

import pytest

from app.clients import whatsapp
from app.models.user import Perfil
from app.services import assistente_geracao as ger

SKIDS = [{"skid": "SKID-01", "inversores_kwh": 181331.0, "medidor_kwh": 179908.2, "conta_kwh": None},
         {"skid": "SKID-02", "inversores_kwh": 182958.4, "medidor_kwh": 182063.0, "conta_kwh": None}]
FALTA = {"tom": "atencao", "texto": "Falta a conta de 10/2026 no meuWatt: SKID-01, SKID-02."}


class _Mw:
    def __init__(self, skids=SKIDS, parecer=(FALTA,)):
        self.skids, self.parecer = skids, list(parecer)

    async def balanco_energia(self, slug, ini, fim, fabricante=True):
        self.pedido = (slug, ini, fim, fabricante)
        return {"usina": "Porto Ferreira", "inicio": ini.isoformat(), "fim": fim.isoformat(), "ate_agora": False,
                "meses_com_conta": ["2026-10"], "skids": self.skids, "total": {"skid": "Total"},
                "parecer": [dict(p) for p in self.parecer], "fontes": "…"}


@pytest.fixture
def enviados(monkeypatch):
    lista = []

    async def envia(**kw):
        lista.append(kw)
        return {"ok": True}

    monkeypatch.setattr(whatsapp, "enviar_conteudo", envia)
    monkeypatch.setattr(ger, "hoje", lambda: date(2026, 11, 17))
    return lista


def _ctx(mw, perfil=Perfil.GESTOR_EMPRESA):
    return ger.Contexto(db=None, user=types.SimpleNamespace(perfil=perfil), telefone="+5517999990000", mw=mw,
                        usinas={"porto-ferreira": {"nome": "Porto Ferreira", "slug": "porto-ferreira"}})


async def test_mes_fechado_le_do_meuwatt_e_manda_o_grafico(enviados):
    mw = _Mw()
    d = await ger.balanco_energia(_ctx(mw), {"usina": "porto", "mes": "2026-10"})
    assert mw.pedido == ("porto-ferreira", date(2026, 10, 1), date(2026, 10, 31), True)
    assert d["periodo"] == "01/10/2026 a 31/10/2026" and d["skids"] == SKIDS
    g = enviados[-1]                                    # só as séries que existem: sem conta, o gráfico não a promete
    assert g["arquivo"][:4] == b"\x89PNG" and "inversores × medidor por skid" in g["texto"] and d["grafico_enviado"]


async def test_so_o_gestor_ouve_que_pode_mandar_o_pdf(enviados):
    gestor = await ger.balanco_energia(_ctx(_Mw()), {"usina": "porto", "mes": "2026-10"})
    assert gestor["parecer"][-1]["texto"].startswith("Se tiver o PDF da conta, mande por aqui")
    cliente = await ger.balanco_energia(_ctx(_Mw(), Perfil.CLIENTE), {"usina": "porto", "mes": "2026-10"})
    assert cliente["parecer"] == [FALTA] and not any("PDF" in p["texto"] for p in cliente["parecer"])
    sem_falta = await ger.balanco_energia(_ctx(_Mw(parecer=())), {"usina": "porto", "mes": "2026-10"})
    assert sem_falta["parecer"] == []


async def test_periodo_livre_e_mes_que_nao_comecou(enviados):
    mw = _Mw()
    await ger.balanco_energia(_ctx(mw), {"usina": "porto", "inicio": "2026-11-01", "fim": "2026-11-15"})
    assert mw.pedido[1:3] == (date(2026, 11, 1), date(2026, 11, 15))
    await ger.balanco_energia(_ctx(mw), {"usina": "porto", "mes": "2026-11"})
    assert mw.pedido[2] == date(2026, 11, 17)                                  # o mês corrente vai até hoje
    with pytest.raises(ger.Recusa):
        await ger.balanco_energia(_ctx(mw), {"usina": "porto", "mes": "2026-12"})


def test_o_grafico_agrupado_desenha():
    png = ger._desenhar_grupos(["SKID-01", "SKID-02"], {"Inversores": [181.3, 183.0], "Medidor": [179.9, None]},
                               "Porto Ferreira · out/2026", "MWh")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
