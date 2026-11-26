"""Fase 5 (docs/USINA_NASCE_NO_GS.md): a usina do meuWatt/meuPlano que não está no GS vai à fila "A confirmar", uma
vez; a ligada, a já na fila e a decidida não voltam; produto mudo não derruba."""
import asyncio

from app.models.empresa import Empresa
from app.models.plant import HistoricoDaUsina, PlantLink, UsinaAConfirmar
from app.services import conferencia


def test_conferencia_poe_na_fila_o_que_falta_no_gs(db, monkeypatch):
    e = Empresa(nome="Splendor O&M")
    db.add(e)
    db.commit()
    db.add(PlantLink(nome="Ouro Fino", empresa_id=e.id, mp_usina_id=451, mw_plant_slug="ouro-fino"))
    db.commit()

    class Mw:
        async def _get(self, caminho):
            return [{"slug": "ouro-fino", "name": "Ouro Fino"}, {"slug": "nova-mw", "name": "UFV Nova MW", "state": "SP"}]

    class Mp:
        async def usinas(self):
            return [{"id": 451, "name": "Ouro Fino"}, {"id": 852, "name": "UFV Itatiba", "uf": "SP"}]

    async def mw(db_, eid):
        return Mw()

    async def mp(db_, eid):
        return Mp()

    async def sem_proprietarias(*a, **k):
        return []
    monkeypatch.setattr(conferencia.integracoes, "cliente_meuwatt", mw)
    monkeypatch.setattr(conferencia.integracoes, "cliente_meuplano", mp)
    monkeypatch.setattr(conferencia.proprietarias, "importar_do_meuplano", sem_proprietarias)
    assert asyncio.run(conferencia.conferir(db, e.id)) == ["UFV Nova MW (meuwatt)", "UFV Itatiba (meuplano)"]
    assert {(x.sistema, x.referencia) for x in db.query(UsinaAConfirmar)} == {("meuwatt", "nova-mw"), ("meuplano", "852")}
    assert asyncio.run(conferencia.conferir(db, e.id)) == []                 # já na fila: não duplica

    async def mudo(db_, eid):
        raise RuntimeError("fora")
    monkeypatch.setattr(conferencia.integracoes, "cliente_meuwatt", mudo)
    assert asyncio.run(conferencia.conferir(db, e.id)) == []


def test_conferencia_grava_o_kwp_do_meuwatt_na_usina_ligada(db, monkeypatch):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    ouro = PlantLink(nome="Ouro Fino", empresa_id=a.id, mw_plant_slug="ouro-fino", kwp=4000.0)
    tiete = PlantLink(nome="Tietê", empresa_id=a.id, mw_plant_slug="tiete")
    sem = PlantLink(nome="Pereiras", empresa_id=a.id, mw_plant_slug="pereiras", kwp=3000.0)
    de_b = PlantLink(nome="Da Outra", empresa_id=b.id, mw_plant_slug="da-outra", kwp=100.0)
    db.add_all([ouro, tiete, sem, de_b])
    db.commit()
    de_la = [{"slug": "ouro-fino", "name": "Ouro Fino", "total_capacity_kwp": 5012.4},
             {"slug": "tiete", "name": "Tietê", "capacity_kwp": 2500},
             {"slug": "pereiras", "name": "Pereiras", "total_capacity_kwp": 0},      # sem strings lá: o do GS fica
             {"slug": "da-outra", "name": "Da Outra", "total_capacity_kwp": 999.0}]  # de outra empresa: não é mexida

    class Mw:
        async def _get(self, caminho):
            return de_la

    async def mw(db_, eid):
        return Mw()

    async def mudo(*a_, **k):
        raise RuntimeError("fora")

    async def sem_proprietarias(*a_, **k):
        return []
    monkeypatch.setattr(conferencia.integracoes, "cliente_meuwatt", mw)
    monkeypatch.setattr(conferencia.integracoes, "cliente_meuplano", mudo)
    monkeypatch.setattr(conferencia.proprietarias, "importar_do_meuplano", sem_proprietarias)

    def linhas():
        return [(h.plant_link_id, h.campo, h.antes, h.depois, h.sistema, h.por_id)
                for h in db.query(HistoricoDaUsina).order_by(HistoricoDaUsina.id)]

    assert asyncio.run(conferencia.conferir(db, a.id)) == []                 # todas ligadas: nada vai à fila
    for u in (ouro, tiete, sem, de_b):
        db.refresh(u)
    assert (ouro.kwp, tiete.kwp, sem.kwp, de_b.kwp) == (5012.4, 2500.0, 3000.0, 100.0)
    assert linhas() == [(ouro.id, "kwp", "4000.0", "5012.4", "meuwatt", None),
                        (tiete.id, "kwp", None, "2500.0", "meuwatt", None)]
    assert asyncio.run(conferencia.conferir(db, a.id)) == [] and len(linhas()) == 2   # igual: sem linha nova
    de_la[0]["total_capacity_kwp"] = 6000.0
    monkeypatch.setattr(conferencia.integracoes, "cliente_meuwatt", mudo)    # meuWatt fora: o guardado fica
    assert asyncio.run(conferencia.conferir(db, a.id)) == []
    db.refresh(ouro)
    assert ouro.kwp == 5012.4 and len(linhas()) == 2
