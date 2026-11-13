"""A matriz e o diagnóstico com o caso REAL que os criou: Pirapozinho, 12–13/11/2026 (47 às 22:48, 27 nas três fases
às 03:17 nos relés dos Skids 1 e 2, os oito inversores deles sem ligar até o trip limpar; o relé do Skid 2 mudo e a
fase A do Skid 3 zerada só na medição)."""

from datetime import UTC, datetime

from app.services import diagnostico, matriz


def test_matriz_le_o_codigo_como_o_rele_escreve():
    assert matriz.do_codigo("27A").codigo == "27"
    assert matriz.do_codigo("27/59 PhB").codigo == "27"
    assert matriz.do_codigo("51G").codigo == "51N"
    assert matriz.do_codigo("50/51N").codigo == "51N"
    assert matriz.do_codigo("59N").codigo == "59N"
    assert matriz.do_codigo("86").codigo == "86"
    assert matriz.do_codigo("xyz") is None and matriz.do_codigo("") is None
    for item in matriz.MATRIZ.values():                  # todo item diz o que é, a causa e o que fazer
        assert item.o_que_e and item.causas and item.fazer and item.gravidade in ("critica", "alta", "media", "info")


def _ev(hora, codigo, evento="TRIPPED", dia=13):
    return {"timestamp": f"2026-11-{dia}T{hora}:00Z", "trip_code": codigo, "event": evento}


class _MW:
    """O meuWatt de Pirapozinho às 09:30 de 13/11 (horas em UTC: 03:17 BRT = 06:17Z)."""

    async def monitoramento_atual(self, slug):
        rele = {"is_temperature_relay": False, "model": "pextron-urp6000", "comm": True,
                "voltage_a": 7950, "voltage_b": 7960, "voltage_c": 7970, "total_active_power": 260}
        return {"relays": [
            {**rele, "name": "Relé Skid 1", "transformer_name": "TR-01", "relay_db_id": 1},
            {**rele, "name": "Relé Skid 2", "transformer_name": "TR-02", "relay_db_id": 2, "comm": False},
            {**rele, "name": "Relé Skid 3", "transformer_name": "TR-03", "relay_db_id": 3, "voltage_a": 52},
            {"name": "ABS IO SKID 1", "model": "abs-eth-io", "relay_db_id": 9},
            {**rele, "name": "Geral", "transformer_name": "TR-02", "relay_db_id": 4, "comm": False},
        ]}

    async def eventos_de_trip(self, slug, rele, n):
        if rele in (1, 2):
            return {"events": [_ev("01:48", "47", dia=13), _ev("06:17", "27A"), _ev("06:17", "27B"),
                               _ev("06:17", "27C"), _ev("10:34", "27A", "CLEARED"), _ev("10:34", "27B", "CLEARED"),
                               _ev("10:34", "27C", "CLEARED"), _ev("10:30", "47", "CLEARED")]}
        return {"events": []}


def _parada(skid, inv):
    return {"transformer_name": skid, "slot_label": inv, "stopped_at": "2026-11-13T08:46:00Z",
            "resolved_at": "2026-11-13T10:36:00Z", "cause": "never_woke_up", "materiality": "material",
            "shadow_loss_kwh": 68.5}


async def test_pirapozinho_rede_rele_mudo_e_tp():
    paradas = [_parada("TR-01", f"Inv 1{i}") for i in range(1, 5)] + [_parada("TR-02", f"Inv 2{i}") for i in range(1, 5)]
    achados = await diagnostico.diagnosticar(_MW(), {"slug": "pirapozinho", "nome": "Pirapozinho"}, paradas,
                                             agora=datetime(2026, 11, 13, 12, 30, tzinfo=UTC))
    por = {a.codigo: a for a in achados}
    assert set(por) == {"27", "RELE_SEM_COMUNICACAO", "FASE_ZERO_MEDICAO"}

    rede = por["27"]                                      # um achado só para os dois skids: o mesmo trip
    assert sorted(rede.skids) == ["TR-01", "TR-02"] and rede.resolvido_em is not None
    assert "03:17" in rede.causa and "47" in rede.causa and "REDE" in rede.causa
    assert "05:46" in rede.texto() and "07:36" in rede.texto() and "274 kWh" in rede.texto()
    assert rede.chave == "diag:pirapozinho:27:TR-01+TR-02:2026-11-13T08:46"

    assert por["RELE_SEM_COMUNICACAO"].skids == ["TR-02"]
    assert por["RELE_SEM_COMUNICACAO"].titulo == "Relé Skid 2 e relé Geral sem comunicação"   # um aviso por skid
    assert len({a.chave for a in achados}) == len(achados)    # a trava é (pessoa, chave): chave repetida quebra o envio
    assert rede.push()[1].endswith("concessionária. Fazer: " + rede.fazer[0])
    tp = por["FASE_ZERO_MEDICAO"]
    assert tp.skids == ["TR-03"] and "52 V / 7.960 V / 7.970 V" in tp.texto() and "260 kW" in tp.texto()
    assert len(rede.chave) <= 120 and tp.chave.startswith("diag:pirapozinho:FASE_ZERO_MEDICAO:TR-03:")


async def test_sem_trip_e_nao_ligou_e_trip_ativo_e_desarmado():
    class Sem(_MW):
        async def eventos_de_trip(self, slug, rele, n):
            # Skid 1 sem trip; Skid 3 com 86 que disparou e não limpou (desarmado agora).
            return {"events": [_ev("06:00", "86")]} if rele == 3 else {"events": []}

    achados = await diagnostico.diagnosticar(Sem(), {"slug": "p", "nome": "P"}, [_parada("TR-01", "Inv 11")],
                                             agora=datetime(2026, 11, 13, 12, 30, tzinfo=UTC))
    por = {a.codigo: a for a in achados}
    assert por["NAO_LIGOU"].skids == ["TR-01"] and "sem trip" in por["NAO_LIGOU"].causa
    assert por["86"].titulo == "skid DESARMADO agora" and por["86"].skids == ["TR-03"]
    assert achados[0].codigo == "86"                     # o crítico primeiro


async def test_helper_le_o_rele_mudo_e_os_inversores():
    class Helper:
        def __init__(self):
            self.lidos = []

        async def rede(self):
            return {"ok": True, "vpn_ultimo_contato_s": 5}

        async def chamar(self, rota, corpo, origem, metodo="POST"):
            if rota == "/api/registry/devices":
                return {"resposta": {"devices": [
                    {"category": "relay", "name": "Relé Skid 2", "driver": "pextron_urp6000", "group": "TR-02",
                     "ip": "10.1.130.2", "port": 5020, "slave": 3},
                    {"category": "inverter", "tag": "Inv 21", "driver": "huawei_sun2000", "group": "TR-02",
                     "ip": "10.1.130.242", "port": None, "slave": 15},
                    {"category": "relay", "name": "ABS IO SKID 2", "driver": "abs_eth_io", "group": None}]}}
            if rota == "/api/read":
                self.lidos.append(corpo["read_cmd"])
                if corpo["read_cmd"] == "funcoes_ativas":
                    return {"resposta": {"ok": False, "error": "o equipamento (slave 3) não respondeu — confira"}}
                return {"resposta": {"ok": True, "estado": "Grid-On (running)", "hora_partida": "2026-11-13 07:37:02",
                                     "falha_ativa": False, "alarmes_ativos": False}}
            return {"ok": True}

    import app.services.assistente_helper as ah
    ah._VPN = None
    rele = diagnostico.Achado("RELE_SEM_COMUNICACAO", "x", "media", "P", ["TR-02"], None)
    parou = diagnostico.Achado("27", "x", "alta", "P", ["TR-02"], datetime(2026, 11, 13, 8, 46, tzinfo=UTC))
    h = Helper()
    await diagnostico.com_helper(h, "p", [rele, parou])
    assert h.lidos == ["funcoes_ativas", "status_falhas"]
    assert rele.evidencias == ["Helper agora: o Relé Skid 2 também não responde (o equipamento (slave 3) não "
                               "respondeu)."]
    assert parou.evidencias[0].startswith("Helper agora: Inv 21: Grid-On (running), partiu às")
