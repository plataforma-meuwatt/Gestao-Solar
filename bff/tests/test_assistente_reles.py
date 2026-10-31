"""Skid parado: o bot não conclui "não há trip" do que não leu (dono, 31/10/2026, Pirapozinho: "o skid 2 tá parado",
e o bot respondeu "não há trip ativo, não tem religamento a fazer" com 3 dos 4 relés sem resposta)."""

from datetime import datetime, timedelta, timezone

from app.services import assistente_geracao as ger
from app.services import assistente_helper as h


class _MeuWattFalso:
    def __init__(self):
        self.agora = datetime.now(timezone.utc)

    async def monitoramento_atual(self, slug):
        return {"data_at": "2026-10-31T22:15:00Z", "plant_sleeping": True, "relays": [
            {"relay_db_id": 19, "name": "Relé Skid 2", "model": "pextron-urp6000", "transformer_name": "TR-02",
             "comm": False, "is_temperature_relay": False},
            {"relay_db_id": 18, "name": "Relé Skid 1", "model": "pextron-urp6000", "transformer_name": "TR-01",
             "comm": True, "is_temperature_relay": False, "voltage_a": 7865.6, "voltage_b": 7804.7, "voltage_c": 7888.1,
             "current_a": 0.0, "current_b": 0.0, "current_c": 0.0, "total_active_power": 0.0},
            {"relay_db_id": 62, "name": "TEMP-SKID-02", "model": "electron-ep4-iot", "is_temperature_relay": True},
            {"relay_db_id": 73, "name": "ABS IO SKID 2", "model": "abs-eth-io", "is_temperature_relay": False}]}

    async def eventos_de_trip(self, slug, relay_id, limite=50):
        if relay_id == 18:
            raise RuntimeError("fora")
        velho = (self.agora - timedelta(days=10)).isoformat()
        return [{"timestamp": (self.agora - timedelta(days=3)).isoformat(), "trip_code": "86", "event": "CLEARED"},
                {"timestamp": (self.agora - timedelta(hours=1)).isoformat(), "trip_code": "86", "event": "TRIPPED"},
                {"timestamp": velho, "trip_code": "27A", "event": "TRIPPED"}]


async def test_os_reles_de_protecao_com_o_estado_e_os_trips(db):
    ctx = ger.Contexto(db=db, user=None, telefone="+5517997377626", mw=_MeuWattFalso(),
                       usinas={"pirapozinho": {"id": 9376, "nome": "Pirapozinho", "slug": "pirapozinho"}})
    r = await ger.reles(ctx, {"usina": "pirapo"})
    assert [x["rele"] for x in r["reles"]] == ["Relé Skid 2", "Relé Skid 1"]      # sem o térmico e o módulo de IO
    skid2, skid1 = r["reles"]
    assert skid2["comunica"] is False and "DESCONHECIDO" in r["nota"] and r["noite"] is True
    assert [t["evento"] for t in skid2["trips"]] == ["disparou"]                    # só os dos últimos 2 dias
    assert skid1["trips"] is None and skid1["tensao_v"] == [7865.6, 7804.7, 7888.1]  # histórico que não leu: nulo


def test_o_que_a_leitura_do_helper_nao_permite_concluir():
    assert h._nota_da_leitura("/api/alarms/trips", {"trips": []}) == h.NOTA_TRIPS
    assert h._nota_da_leitura("/api/reenergize/config", {"ok": True, "skids": []}) == h.SEM_RELIGAMENTO
    assert h._nota_da_leitura("/api/reenergize/config", {"ok": True, "skids": [{"id": 1}]}) is None
    assert h._nota_da_leitura("/api/read", {"ok": False, "error": "sem resposta"}) == h.DESCONHECIDO
    assert h._nota_da_leitura("/api/read", {"ok": True}) is None
