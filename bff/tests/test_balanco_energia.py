"""O balanço de energia do bot (`balanco_energia`): inversores × medidor × conta, por skid, com as perdas, o parecer e
o gráfico. O dono, 17/11/2026: "comparar … a medição dos inversores de cada skid vs o medido pelo medidor particular …
com a conta de energia tbm … a tabela com as perdas … a diferença geralmente é 2% mas não é regra … período
personalizado, mês fechado … sempre o parecer". Números de Porto Ferreira (outubro e 17/11/2026, o dia em que o skid 2
gerou sem comunicar)."""

import io
import types
import zipfile
from datetime import UTC, date, datetime

import pytest

from app.clients import whatsapp
from app.services import assistente_geracao as ger

INV = {"SKID-01": 181330.97, "SKID-02": 182958.4, "SKID-03": 182739.5, "SKID-04": 182197.0, "SKID-05": 179978.5}
MED = {"SKID-01": 179908.199, "SKID-02": 182062.997, "SKID-03": 180721.758, "SKID-04": 181164.941, "SKID-05": 178721.592}
TID = {n: 55 + i for i, n in enumerate(INV, 1)}


class _Agora(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 17, 22, 0, tzinfo=UTC).astimezone(tz) if tz else datetime(2026, 11, 17, 22, 0)


class _Mw:
    def __init__(self, inv=None, med=None, contas=(), lacunas=None, ate=None, dias_inv=None, parada=None, notas=()):
        self.inv, self.med, self.contas = inv or INV, med or MED, list(contas)
        self.lacunas, self.ate, self.dias_inv, self.parada, self.notas = lacunas or {}, ate or {}, dias_inv or {}, \
            parada or {}, notas

    async def geracao_periodo(self, slug, ini, fim):
        self.periodo = (ini, fim)
        dias = (fim - ini).days + 1
        return {"days_in_range": dias, "total_generation_kwh": round(sum(self.inv.values()), 1),
                "transformers": [{"id": TID[n], "name": n, "total_yield_kwh": v, "total_lost_kwh": self.parada.get(n, 0)}
                                 for n, v in self.inv.items()],
                "inverters": [{"slot_label": f"Inv {TID[n]}", "transformer_id": TID[n],
                               "days_with_data": self.dias_inv.get(n, dias)} for n in self.inv]}

    async def fronteira_periodo(self, slug, ini, fim):
        return {"totals": {"injection_kwh": round(sum(self.med.values()), 3), "estimated_kwh": 0},
                "readers": [{"transformer_id": TID[n], "transformer_name": n, "injection_kwh": v,
                             "data_until": self.ate.get(n, "2026-11-17T19:00:00-03:00"),
                             "long_gaps": self.lacunas.get(n, []),
                             "days": [{"date": f"{ini:%Y-%m-%d}", "injection_kwh": v}]} for n, v in self.med.items()]}

    async def energia_diaria(self, slug, ini, fim):
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as w:
            w.writestr("xl/sharedStrings.xml", "<sst>" + "".join(f"<si><t>{n}</t></si>" for n in self.notas) + "</sst>")
        return z.getvalue(), {"validacao": "ok", "mensagem": "Dados conferidos com a plataforma (Huawei FusionSolar): "
                                                            "diferença de 0,00% (limite 0,50%)."}

    async def faturas_concessionaria(self, slug, ano):
        return [c for c in self.contas if c["year"] == ano]


@pytest.fixture
def enviados(monkeypatch):
    lista = []

    async def envia(**kw):
        lista.append(kw)
        return {"ok": True}

    monkeypatch.setattr(whatsapp, "enviar_conteudo", envia)
    monkeypatch.setattr(ger, "hoje", lambda: date(2026, 11, 17))
    monkeypatch.setattr(ger, "datetime", _Agora)
    return lista


def _ctx(mw):
    return ger.Contexto(db=None, user=types.SimpleNamespace(), telefone="+5517999990000", mw=mw,
                        usinas={"porto-ferreira": {"nome": "Porto Ferreira", "slug": "porto-ferreira"}})


def _tons(d):
    return [(p["tom"], p["texto"]) for p in d["parecer"]]


async def test_outubro_perdas_normais_o_skid_que_destoa_e_a_conta_que_falta(enviados):
    mw = _Mw(notas=["2026-10: os valores do meuWatt foram gravados a partir da Huawei em 03/11/2026"])
    d = await ger.balanco_energia(_ctx(mw), {"usina": "porto ferreira", "mes": "2026-10"})
    assert mw.periodo == (date(2026, 10, 1), date(2026, 10, 31)) and d["meses_com_conta"] == ["10/2026"]
    s1 = d["skids"][0]
    assert (s1["inversores_kwh"], s1["medidor_kwh"], s1["perda_ate_o_medidor_kwh"], s1["perda_ate_o_medidor_pct"]) == \
        (181331.0, 179908.2, 1422.8, 0.78)
    textos = " | ".join(t for _, t in _tons(d))
    assert ("ok", "Perda dos inversores até o medidor: 0,49% a 1,10% por skid (0,73% no total); abaixo dos ~2% "
                  "comuns.") in _tons(d)
    assert "SKID-03 perde mais que os outros skids (1,10% × 0,64% na mediana)" in textos
    assert "Falta a conta de 10/2026 no meuWatt: SKID-01, SKID-02, SKID-03, SKID-04, SKID-05" in textos
    assert "em 2026-10 os valores do meuWatt foram corrigidos a partir da própria plataforma" in textos
    g = enviados[-1]                                         # o gráfico vai junto, só com as séries que existem
    assert g["tipo"] == "image" and g["arquivo"][:4] == b"\x89PNG" and "inversores × medidor por skid" in g["texto"]


async def test_com_a_conta_o_medidor_concilia_pela_regua_do_portal(enviados):
    contas = [{"transformer_id": TID[n], "year": 2026, "month": 10, "billed_mwh": round(v / 1000, 2)} for n, v in MED.items()]
    d = await ger.balanco_energia(_ctx(_Mw(contas=contas)), {"usina": "porto", "mes": "2026-10"})
    assert all(x["conciliacao"] == "Conciliado" for x in d["skids"]) and d["total"]["conta_kwh"] == 902570.0   # 179,91 + 182,06 + 180,72 + 181,16 + 178,72 MWh
    assert any(t.startswith("Medidor × conta: conciliado em SKID-01") for _, t in _tons(d))
    assert "conta" in enviados[-1]["texto"]


async def test_hoje_o_skid_que_gerou_sem_comunicar_e_o_medidor_parado(enviados):
    """17/11/2026: o skid 2 sem comunicação mas gerando (o dono: "vc vai concluir isso"), e o medidor do skid 1 parado
    desde as 06:18. Nenhum dos dois vira perda."""
    inv = {**{n: 7700.0 for n in INV}, "SKID-02": 0.0}
    med = {**{n: 7650.0 for n in INV}, "SKID-01": 39.5, "SKID-02": 7704.9}
    mw = _Mw(inv=inv, med=med, ate={"SKID-01": "2026-11-17T06:18:37-03:00"}, parada={"SKID-02": 6978.0})
    d = await ger.balanco_energia(_ctx(mw), {"usina": "porto", "inicio": "2026-11-17", "fim": "2026-11-17"})
    s1, s2 = d["skids"][:2]
    assert s1["perda_ate_o_medidor_pct"] is None and "medidor sem leitura desde 17/11 06:18" in s1["falta_dado"]
    assert s2["perda_ate_o_medidor_pct"] is None and d["total"]["perda_ate_o_medidor_pct"] is None
    assert ("problema", "SKID-02: os inversores não mandaram dado (0 kWh no meuWatt), mas o medidor marcou 7.705 kWh: o "
                        "skid GEROU sem comunicar — é falha de comunicação, não parada (o meuWatt contou 6.978 kWh de "
                        "parada).") in _tons(d)
    assert ("problema", "SKID-01: sem conclusão da perda, falta dado — medidor sem leitura desde 17/11 06:18.") in _tons(d)
    assert d["meses_com_conta"] == [] and any("só entra em mês inteiro" in t for _, t in _tons(d))


async def test_medidor_acima_dos_inversores_aponta_o_lado_dos_inversores(enviados):
    mw = _Mw(med={**MED, "SKID-02": 197000.0}, parada={"SKID-02": 8767.0})
    d = await ger.balanco_energia(_ctx(mw), {"usina": "porto", "mes": "2026-10"})
    assert d["skids"][1]["medidor_nao_cobre_os_inversores"]
    assert any(t.startswith("SKID-02: o medidor marcou 7,7% a MAIS que os inversores") and "8.767 kWh de parada" in t
               for _, t in _tons(d))


async def test_perda_acima_do_comum_e_alta(enviados):
    mw = _Mw(med={**MED, "SKID-04": INV["SKID-04"] * 0.97, "SKID-05": INV["SKID-05"] * 0.95})
    d = await ger.balanco_energia(_ctx(mw), {"usina": "porto", "mes": "2026-10"})
    tons = _tons(d)
    assert ("atencao", "SKID-04 perde 3,00% até o medidor, acima dos ~2% comuns: vale conferir o transformador, os cabos "
                       "e o medidor desse skid.") in tons
    assert any(tom == "problema" and t.startswith("SKID-05 perde 5,00%") for tom, t in tons)


async def test_queda_de_noite_nao_e_falta_e_a_de_dia_e(enviados):
    noite = [{"start": "2026-10-09T19:16:00-03:00", "end": "2026-10-09T22:46:00-03:00"}]
    dia = [{"start": "2026-10-10T10:00:00-03:00", "end": "2026-10-10T12:00:00-03:00"}]
    mw = _Mw(lacunas={n: noite for n in INV} | {"SKID-04": dia}, dias_inv={"SKID-05": 29})
    d = await ger.balanco_energia(_ctx(mw), {"usina": "porto", "mes": "2026-10"})
    falta = {x["skid"]: x["falta_dado"] for x in d["skids"]}
    assert falta["SKID-01"] is None and "10/10 10:00 a 10/10 12:00" in falta["SKID-04"]
    assert "Inv 60 com 29 de 31 dias" in falta["SKID-05"]
    assert ("info", "Os medidores ficaram sem leitura só de noite em 09/10: sem efeito na energia.") in _tons(d)


def test_periodo_mes_fechado_ou_livre(monkeypatch):
    monkeypatch.setattr(ger, "hoje", lambda: date(2026, 11, 17))
    assert ger._periodo_balanco({"mes": "2026-10"}) == (date(2026, 10, 1), date(2026, 10, 31), [date(2026, 10, 1)])
    assert ger._periodo_balanco({"mes": "2026-11"}) == (date(2026, 11, 1), date(2026, 11, 17), [])   # não fechou
    assert ger._periodo_balanco({"inicio": "2026-09-01", "fim": "2026-10-31"})[2] == [date(2026, 9, 1), date(2026, 10, 1)]
    assert ger._periodo_balanco({"inicio": "2026-10-05", "fim": "2026-10-20"})[2] == []            # mês pela metade
    with pytest.raises(ger.Recusa):
        ger._periodo_balanco({"mes": "2026-12"})


def test_queda_de_dia_ou_de_noite():
    def h(s):
        return datetime.fromisoformat(s)
    assert not ger._de_dia(h("2026-11-09T19:16:00-03:00"), h("2026-11-09T22:46:00-03:00"))
    assert ger._de_dia(h("2026-11-09T17:00:00-03:00"), h("2026-11-09T19:00:00-03:00"))
    assert ger._de_dia(h("2026-11-09T20:00:00-03:00"), h("2026-11-10T07:00:00-03:00"))   # atravessa a manhã
