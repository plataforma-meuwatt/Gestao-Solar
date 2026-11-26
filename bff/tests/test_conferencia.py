"""Fase 5 (docs/USINA_NASCE_NO_GS.md): a usina do meuWatt/meuPlano que não está no GS vai à fila "A confirmar", uma
vez; a ligada, a já na fila e a decidida não voltam; produto mudo não derruba."""
import asyncio

from app.models.empresa import Empresa
from app.models.plant import PlantLink, UsinaAConfirmar
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
