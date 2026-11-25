"""O "já sei" pelo bot (dono, 14/11/2026): `marcar_leitura` propõe com o Sim e grava no meuWatt com o token da pessoa,
SEM apagar a observação nem o prazo que a tela Leituras já tinha (o PUT de lá troca a marcação inteira)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import assistente_geracao as ger
from app.services import assistente_helper as h


class _MW:
    def __init__(self, marca, pode=True):
        self.marca, self.pode = marca, pode

    async def leituras(self, slug):
        return {"can_mark": self.pode, "relays": [{"relay_id": 21, "name": "Relé Skid 3", "transformer_name": "TR-03", "readings": [
            {"key": "voltage_a", "label": "Tensão fase A", "status": "zeroed", "value": 52.0, "mark": self.marca,
             "alert_hint": "o bot avisa a fase zerada"},
            {"key": "current_a", "label": "Corrente fase A", "status": "ok", "value": 40.0, "mark": None,
             "alert_hint": None}]}]}


class _Grava:
    """O cliente do meuWatt com o token da pessoa, na hora do Sim: relê a marcação (`atual`) e grava."""
    def __init__(self):
        self.pedidos, self.atual = [], None

    async def leituras(self, slug):
        return {"relays": [{"relay_id": 21, "readings": [{"key": "voltage_a", "mark": self.atual}]}]} if self.atual else {}

    async def marcar_leitura(self, *args):
        self.pedidos.append(args)


@pytest.fixture
def grava(monkeypatch):
    g = _Grava()
    monkeypatch.setattr("app.services.vinculos.cliente_meuwatt", lambda db, uid, so_proprio=False: g)
    return g


def _ctx(marca, uid):
    user = SimpleNamespace(id=uid, senha_atuacao_hash=None, bot_ativo=["bot_meuwatt"])
    return ger.Contexto(db=None, user=user, telefone="+5517997377626", mw=_MW(marca),
                        usinas={"pirapozinho": {"id": 9376, "nome": "Pirapozinho", "slug": "pirapozinho"}})


async def _sim(ctx):
    p = h.PENDENTES.pop(ctx.user.id)
    return p, await p.executar(None, ctx.user, ctx.telefone)


async def test_ja_sei_sem_observacao_nova_mantem_a_da_tela_e_o_prazo(grava):
    tela = {"ignored": False, "note": "OS 2001 aberta", "expires_at": None}
    ctx = _ctx(tela, 9101)
    r = await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a"})
    assert r["proposta_pendente"] == "Marcar «já sei» no meuWatt: Relé Skid 3 · Tensão fase A (Pirapozinho)"
    p, fim = await _sim(ctx)
    assert grava.pedidos == [("pirapozinho", 21, "voltage_a", True, "OS 2001 aberta", None)] and fim.startswith("✅")

    vence = (datetime.now(UTC) + timedelta(days=3)).isoformat()      # um prazo que ainda não venceu
    ctx = _ctx({"ignored": True, "note": "OS 2001 aberta", "expires_at": vence}, 9102)
    await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "TR-03", "leitura": "voltage_a",
                                   "observacao": "relé trocado na terça"})
    await _sim(ctx)
    assert grava.pedidos[-1] == ("pirapozinho", 21, "voltage_a", True, "relé trocado na terça", vence)


async def test_tirar_o_ja_sei_deixa_a_observacao(grava):
    ctx = _ctx({"ignored": True, "note": "OS 2001 aberta", "expires_at": "2026-11-21T12:00:00+00:00"}, 9103)
    r = await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a", "ja_sei": False})
    assert r["proposta_pendente"].startswith("Tirar o «já sei»")
    await _sim(ctx)
    assert grava.pedidos == [("pirapozinho", 21, "voltage_a", False, "OS 2001 aberta", None)]
    with pytest.raises(ger.Recusa):                       # sem X não há o que tirar
        await ger.marcar_leitura(_ctx(None, 9104), {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a",
                                                    "ja_sei": False})


async def test_quem_nao_opera_a_usina_ouve_antes_do_sim(grava):
    ctx = _ctx(None, 9105)
    ctx.mw = _MW(None, pode=False)
    with pytest.raises(ger.Recusa, match="não marca leituras"):
        await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a"})
    assert 9105 not in h.PENDENTES and grava.pedidos == []


async def test_leituras_usina_mostra_o_rele_mudo_uma_vez_como_a_tela():
    class Mudo(_MW):
        async def leituras(self, slug):
            return {"can_mark": True, "relays": [{"relay_id": 19, "name": "Relé Skid 2", "transformer_name": "TR-02",
                    "readings": [{"key": k, "label": k, "status": "no_comm", "value": None, "mark": None}
                                 for k in ger.LEITURAS_RELE]}]}
    r = await ger.leituras_usina(_ctx(None, 9106).__class__(db=None, user=None, telefone="", mw=Mudo(None),
                                 usinas={"p": {"id": 1, "nome": "Pirapozinho", "slug": "p"}}), {"usina": "p"})
    assert [x["leitura"] for x in r["reles"][0]["leituras"]] == ["comm"]


async def test_so_a_observacao_e_o_prazo(grava):
    ctx = _ctx(None, 9107)
    r = await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a", "ja_sei": False,
                                       "observacao": "TP trocado ontem, de olho"})
    assert r["proposta_pendente"].startswith("Gravar a observação")
    _, fim = await _sim(ctx)
    assert grava.pedidos[-1] == ("pirapozinho", 21, "voltage_a", False, "TP trocado ontem, de olho", None)
    assert "observação gravada" in fim
    ctx = _ctx(None, 9108)
    await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a", "dias": 7})
    await _sim(ctx)
    assert grava.pedidos[-1][3] is True and grava.pedidos[-1][5] is not None             # vence em 7 dias
    with pytest.raises(ger.Recusa):
        await ger.marcar_leitura(_ctx(None, 9109), {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a",
                                                    "dias": 900})


async def test_reles_usa_o_valor_e_a_comunicacao_da_tela_leituras():
    class MW(_MW):
        async def monitoramento_atual(self, slug):
            return {"relays": [{"relay_db_id": 21, "name": "Relé Skid 3", "transformer_name": "TR-03",
                                "model": "pextron-urp6000", "comm": False, "voltage_a": 7950.0}]}

        async def eventos_de_trip(self, slug, rid, n):
            return {"events": []}

        async def leituras(self, slug):
            return {"can_mark": True, "relays": [{"relay_id": 21, "readings": [
                {"key": "comm", "status": "ok", "value": None},
                {"key": "voltage_a", "status": "blank", "value": None}]}]}   # snapshot atrasado: sem valor de agora
    c = _ctx(None, 9110)
    c.mw = MW(None)
    r = (await ger.reles(c, {"usina": "pirapozinho"}))["reles"][0]
    assert r["comunica"] is True and r["tensao_v"][0] is None                 # nunca o 7.950 velho do monitoramento


async def test_o_sim_rele_a_marcacao_e_nao_apaga_o_que_a_tela_editou_depois(grava):
    ctx = _ctx({"ignored": False, "note": "nota velha", "expires_at": None}, 9111)
    await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a"})
    grava.atual = {"ignored": False, "note": "nota que a tela gravou depois", "expires_at": None}
    await _sim(ctx)
    assert grava.pedidos[-1][4] == "nota que a tela gravou depois"


async def test_x_numa_leitura_que_o_bot_nao_avisa_nao_promete_calar(grava):
    ctx = _ctx(None, 9112)
    await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "current_a"})
    p = h.PENDENTES.pop(ctx.user.id)
    assert "Fica registrado (o bot não avisa esta leitura)." in p.detalhes


async def test_o_prazo_que_vence_ate_o_sim_vira_sem_prazo_e_o_bot_diz(grava, monkeypatch):
    vence = "2026-11-14T12:00:00+00:00"
    ctx = _ctx({"ignored": True, "note": "OS 2001", "expires_at": vence}, 9113)
    await ger.marcar_leitura(ctx, {"usina": "pirapozinho", "rele": "skid 3", "leitura": "voltage_a"})
    grava.atual = {"ignored": False, "note": "OS 2001", "expires_at": None}      # o GET já não traz a vencida
    import datetime as dt
    class Depois(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 11, 14, 12, 5, tzinfo=dt.UTC)
    monkeypatch.setattr(ger, "datetime", Depois)
    _, fim = await _sim(ctx)
    assert grava.pedidos[-1][5] is None and "já tinha vencido" in fim
