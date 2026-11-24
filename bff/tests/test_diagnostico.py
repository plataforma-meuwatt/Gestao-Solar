"""A matriz e o diagnóstico com o caso REAL que os criou: Pirapozinho, 12–13/11/2026 (47 às 22:48, 27 nas três fases
às 03:17 nos relés dos Skids 1 e 2, os oito inversores deles sem ligar até o trip limpar; o relé do Skid 2 mudo e a
fase A do Skid 3 zerada só na medição)."""

import itertools
from datetime import UTC, datetime

from app.services import diagnostico, matriz

_ids = itertools.count(1)


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


def _lido(nome, skid, rid, comm="ok", va=7950.0, fase_a="ok", pot=260.0, marca_a=None, marca_comm=None, ultima=None):
    """Um relé como a tela Leituras do meuWatt devolve: o `status` de cada leitura é a regra DE LÁ."""
    return {"relay_id": rid, "name": nome, "model": "pextron-urp6000", "transformer_name": skid, "last_read_at": ultima,
            "readings": [{"key": "comm", "status": comm, "value": None, "mark": marca_comm},
                         {"key": "voltage_a", "status": fase_a, "value": va, "mark": marca_a},
                         {"key": "voltage_b", "status": "ok", "value": 7960.0, "mark": None},
                         {"key": "voltage_c", "status": "ok", "value": 7970.0, "mark": None},
                         {"key": "total_active_power", "status": "ok", "value": pot, "mark": None}]}


class _MW:
    """O meuWatt de Pirapozinho às 09:30 de 13/11 (horas em UTC: 03:17 BRT = 06:17Z)."""

    async def leituras(self, slug):
        return {"read_evidence": "ok", "relays": [
            _lido("Relé Skid 1", "TR-01", 1),
            _lido("Relé Skid 2", "TR-02", 2, comm="no_comm"),
            _lido("Relé Skid 3", "TR-03", 3, va=52.0, fase_a="zeroed"),
            _lido("Geral", "TR-02", 4, comm="no_comm"),
        ]}

    async def eventos_de_trip(self, slug, rele, n):
        if rele in (1, 2):
            return {"events": [_ev("01:48", "47", dia=13), _ev("06:17", "27A"), _ev("06:17", "27B"),
                               _ev("06:17", "27C"), _ev("10:34", "27A", "CLEARED"), _ev("10:34", "27B", "CLEARED"),
                               _ev("10:34", "27C", "CLEARED"), _ev("10:30", "47", "CLEARED")]}
        return {"events": []}

    async def verificacao_da_parada(self, plant_id, grupo=None, linha=None):
        """A matriz do meuWatt: os inversores que não ligaram com o relé sem corrente são parada (R5)."""
        return {"row": "R5", "result": "Parada: zerou tudo, e o relé confirma", "kind": "parada", "checks": {}}


def _parada(skid, inv):
    return {"id": next(_ids), "plant_id": 9376, "group_id": None, "transformer_name": skid, "slot_label": inv,
            "stopped_at": "2026-11-13T08:46:00Z",
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
    assert "Verificação do meuWatt: Parada: zerou tudo, e o relé confirma (linha R5 do mapa)." in rede.texto()
    assert rede.chave == "diag:pirapozinho:27:TR-01+TR-02:2026-11-13T08:46"

    assert por["RELE_SEM_COMUNICACAO"].skids == ["TR-02"]
    assert por["RELE_SEM_COMUNICACAO"].titulo == "Relé Skid 2 e relé Geral sem comunicação"   # um aviso por skid
    assert len({a.chave for a in achados}) == len(achados)    # a trava é (pessoa, chave): chave repetida quebra o envio
    assert rede.push()[1].endswith("concessionária. Fazer: " + rede.fazer[0])
    tp = por["FASE_ZERO_MEDICAO"]
    assert tp.skids == ["TR-03"] and "52 V / 7.960 V / 7.970 V" in tp.texto() and "260 kW" in tp.texto()
    assert len(rede.chave) <= 120 and tp.chave.startswith("diag:pirapozinho:FASE_ZERO_MEDICAO:A:TR-03:")   # a fase B que zerar depois avisa também


async def test_sem_trip_e_nao_ligou_e_trip_ativo_e_desarmado():
    class Sem(_MW):
        async def leituras(self, slug):                  # o skid desarmado: o relé dele não mede energia passando
            lido = await super().leituras(slug)
            lido["relays"][2] = _lido("Relé Skid 3", "TR-03", 3, pot=0.0)
            return lido

        async def eventos_de_trip(self, slug, rele, n):
            # Skid 1 sem trip; Skid 3 com 86 que disparou e não limpou (desarmado agora).
            return {"events": [_ev("06:00", "86")]} if rele == 3 else {"events": []}

    achados = await diagnostico.diagnosticar(Sem(), {"slug": "p", "nome": "P"}, [_parada("TR-01", "Inv 11")],
                                             agora=datetime(2026, 11, 13, 12, 30, tzinfo=UTC))
    por = {a.codigo: a for a in achados}
    assert por["NAO_LIGOU"].skids == ["TR-01"] and "sem trip" in por["NAO_LIGOU"].causa
    assert por["86"].titulo == "skid DESARMADO agora" and por["86"].skids == ["TR-03"]
    assert achados[0].codigo == "86"                     # o crítico primeiro

    # Pereiras, 13/11: o coletor perdeu o dado dos inversores 9 min, sem trip. Não é parada, não vira achado.
    comm = {**_parada("TR-01", "INV11"), "cause": "communication_failure"}
    assert not [a for a in await diagnostico.diagnosticar(Sem(), {"slug": "p", "nome": "P"}, [comm],
                                                         agora=datetime(2026, 11, 13, 12, 30, tzinfo=UTC))
                if a.skids == ["TR-01"]]


async def test_sem_a_tela_leituras_a_reserva_avisa_os_trips_e_diz_o_que_nao_conferiu():
    """O /readings fora (ou o GS publicado antes do meuWatt): a causa da parada pelos trips segue; relé mudo e fase
    zerada não (sem a tela não há o «já sei», e o aviso marcado sairia de novo): ficam "não conferidos" para o bot."""
    class SemLeituras(_MW):
        async def leituras(self, slug):
            raise RuntimeError("404 /plants/pirapozinho/readings")

        async def monitoramento_atual(self, slug):
            rele = {"model": "pextron-urp6000", "comm": True, "voltage_a": 7950, "voltage_b": 7960, "voltage_c": 7970,
                    "total_active_power": 260, "last_read_at": "2026-11-13T12:29:00Z", "timestamp": "2026-11-13T12:29:00Z"}
            return {"relays": [{**rele, "relay_db_id": 1, "name": "Relé Skid 1", "transformer_name": "TR-01"},
                               {**rele, "relay_db_id": 2, "name": "Relé Skid 2", "transformer_name": "TR-02",
                                "comm": False, "last_read_at": "2026-11-13T11:00:00Z"},
                               {**rele, "relay_db_id": 3, "name": "Relé Skid 3", "transformer_name": "TR-03",
                                "voltage_a": 52},
                               {"relay_db_id": 9, "name": "ABS IO SKID 1", "model": "abs-eth-io"}]}

    info = {}
    achados = await diagnostico.diagnosticar(SemLeituras(), {"slug": "pirapozinho", "nome": "Pirapozinho"},
                                             [_parada("TR-01", "Inv 11")],
                                             agora=datetime(2026, 11, 13, 12, 30, tzinfo=UTC), info=info)
    assert {a.codigo for a in achados} == {"27"} and achados[0].skids == ["TR-01"]
    assert info == {"leituras": "reserva", "nao_conferidos": ["Relé Skid 2"]}


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


async def test_rele_mudo_e_fase_zerada_vem_do_meuwatt_e_o_x_cala():
    """O estado de cada leitura é a regra da tela Leituras do meuWatt (15 min sem leitura válida; Tietê, 13/11: uma
    leitura vazia de um minuto não é relé mudo). O X "já sei" de lá (o dono, 14/11: o relé do Skid 3 de Pirapozinho
    está com defeito e não lê a fase A) faz o achado sair conhecido, e a varredura não avisa."""
    class Tiete(_MW):
        def __init__(self, *reles):
            self.reles = reles

        async def leituras(self, slug):
            return {"relays": list(self.reles)}

        async def eventos_de_trip(self, slug, rele, n):
            return {"events": []}

    agora = datetime(2026, 11, 13, 16, 22, tzinfo=UTC)
    u = {"slug": "tiete", "nome": "Tietê"}
    assert await diagnostico.diagnosticar(Tiete(_lido("TR-03", "TR-03", 26)), u, [], agora=agora) == []
    mudo, = await diagnostico.diagnosticar(Tiete(_lido("TR-03", "TR-03", 26, comm="no_comm",
                                                       ultima="2026-11-13T16:07:00Z")), u, [], agora=agora)
    assert mudo.codigo == "RELE_SEM_COMUNICACAO" and mudo.conhecido is None
    # Sem a evidência do monitoramento, a hora vem da linha da comunicação (a consulta de 48 h do meuWatt).
    sem_hora = {**_lido("TR-03", "TR-03", 26, comm="no_comm"), "last_read_at": None}
    sem_hora["readings"][0]["last_valid_at"] = "2026-11-13T15:00:00Z"
    m2, = await diagnostico.diagnosticar(Tiete(sem_hora), u, [], agora=agora)
    assert m2.evidencias[0].endswith("12:00.")                     # nunca "nas últimas 48 h" com a hora conhecida
    assert mudo.evidencias[0].startswith("Sem leitura válida no meuWatt desde ")
    assert mudo.evidencias[0].endswith("13:07.")                # outro dia sai "13/11 13:07"

    # à noite o relé mede ruído de 10 a 12 kW: isso não é "skid gerando" (a fase zerada saía entre 00h e 02h30)
    assert await diagnostico.diagnosticar(Tiete(_lido("Relé Skid 3", "TR-03", 21, va=0.0, fase_a="zeroed", pot=12.6)),
                                          u, [], agora=agora) == []
    x = {"ignored": True, "note": "Relé com defeito, não lê a fase A", "user_name": "Renan", "created_at": "2026-11-13T12:00:00Z"}
    fase, = await diagnostico.diagnosticar(Tiete(_lido("Relé Skid 3", "TR-03", 21, va=52.0, fase_a="zeroed", marca_a=x)),
                                           u, [], agora=agora)
    assert fase.codigo == "FASE_ZERO_MEDICAO" and fase.conhecido.startswith("Relé com defeito, não lê a fase A (Renan, ")
    escondida = {"ignored": True, "note": None, "user_name": None, "created_at": None}   # quem lê não opera a usina
    oculto, = await diagnostico.diagnosticar(Tiete(_lido("Relé Skid 3", "TR-03", 21, va=52.0, fase_a="zeroed",
                                                         marca_a=escondida)), u, [], agora=agora)
    assert oculto.conhecido.startswith("a equipe marcou que já sabe")          # nunca "sem observação" sem saber
    assert fase.conhecido.endswith("09:00)")
    assert "Já sabido (marcado no meuWatt): Relé com defeito" in fase.texto() and fase.para_ia()["ja_sabido"]
    noite, = await diagnostico.diagnosticar(Tiete(_lido("Relé Skid 3", "TR-03", 21, va=52.0, fase_a="zeroed", pot=0.0),
                                                 _lido("Geral", "TR-03", 17, comm="no_comm")), u, [], agora=agora)
    assert noite.codigo == "RELE_SEM_COMUNICACAO"         # sem o skid gerando, a fase zerada não é a MEDIÇÃO

    # Dois relés mudos no mesmo skid, um marcado e o outro não: o aviso sai (um deles ninguém sabia).
    sabido = {**x, "note": "Geral desligado para manutenção"}
    um, = await diagnostico.diagnosticar(Tiete(_lido("Relé Skid 2", "TR-02", 19, comm="no_comm", marca_comm=sabido),
                                               _lido("Geral", "TR-02", 17, comm="no_comm")), u, [], agora=agora)
    assert um.titulo == "Relé Skid 2 e relé Geral sem comunicação" and um.conhecido is None
    os_dois, = await diagnostico.diagnosticar(Tiete(_lido("Relé Skid 2", "TR-02", 19, comm="no_comm", marca_comm=sabido),
                                                    _lido("Geral", "TR-02", 17, comm="no_comm", marca_comm=sabido)),
                                              u, [], agora=agora)
    assert os_dois.conhecido and os_dois.conhecido.startswith("Geral desligado")


R9 = {"row": "R9", "result": "Não é parada: nuvem ou fim de tarde", "kind": "nao_parada"}
R1 = {"row": "R1", "result": "Problema de comunicação: a energia está saindo pelo relé", "kind": "comunicacao"}
R8 = {"row": "R8", "result": "Parada para avaliar: começou lenta e não voltou", "kind": "avaliar"}
R4 = {"row": "R4", "result": "Parada", "kind": "parada"}


class _Matriz(_MW):
    """O meuWatt de 23/11/2026 com a matriz de lá (os vereditos que ela deu às 18:30)."""

    def __init__(self, vereditos, reles=(), trips=None, falha=False):
        self.vereditos, self.reles, self.trips, self.falha, self.pedidos = vereditos, reles, trips or {}, falha, []

    async def leituras(self, slug):
        return {"relays": list(self.reles)}

    async def eventos_de_trip(self, slug, rele, n):
        return {"events": self.trips.get(rele, [])}

    async def verificacao_da_parada(self, plant_id, grupo=None, linha=None):
        self.pedidos.append(grupo if grupo is not None else linha)
        if self.falha:
            raise RuntimeError("503 Service Unavailable")
        return {**self.vereditos[grupo if grupo is not None else linha], "checks": {}}


def _linha(i, skid, grupo, ini, fim, causa="zero_active_power"):
    return {"id": i, "plant_id": 9377, "group_id": grupo, "transformer_name": skid, "slot_label": f"Inv {i}",
            "stopped_at": f"2026-11-23T{ini}:00Z", "resolved_at": fim and f"2026-11-23T{fim}:00Z", "cause": causa,
            "materiality": "material", "shadow_loss_kwh": 0.1}


async def test_parada_e_o_que_a_matriz_do_meuwatt_diz():
    """O dono, 23/11/2026: "Não foi parada, só vamos mostrar no whats o que for realmente parada. Já temos uma matriz".
    Tietê 16:41: os 10 inversores a zero com tensão nos relés, sem trip e sem falha do inversor = R9 (nuvem ou fim de
    tarde) no meuWatt, e saíram três avisos de parada. Pereiras: a falha de leitura com a energia saindo pelo relé (R1),
    o fim da tarde (R8, para avaliar) e o 27 "disparado" com o skid gerando também viraram aviso."""
    diagnostico._VEREDITOS.clear()
    tiete = [_linha(i, f"TR-0{1 + i % 3}", 29039, "19:41", "19:52") for i in range(10)]
    info, mw, u = {}, _Matriz({29039: R9}), {"slug": "tiete", "nome": "Tietê"}
    assert await diagnostico.diagnosticar(mw, u, tiete, agora=datetime(2026, 11, 23, 20, tzinfo=UTC), info=info) == []
    np, = info["nao_paradas"]                            # a hora sai com o dia quando o teste roda em outro dia
    assert np["desde"].endswith("16:41") and np["ate"].endswith("16:52")
    assert {k: np[k] for k in ("skids", "inversores", "veredito")} == {
        "skids": ["TR-01", "TR-02", "TR-03"], "inversores": 10,
        "veredito": "Não é parada: nuvem ou fim de tarde (linha R9 do mapa)"}
    await diagnostico.diagnosticar(mw, u, tiete, agora=datetime(2026, 11, 23, 20, 10, tzinfo=UTC))
    assert mw.pedidos == [29039]                         # encerrada: a volta seguinte não pergunta de novo

    pereiras = ([_linha(100 + i, "TR-01" if i < 8 else "TR-02", 29036, "15:29", "19:40", "communication_failure")
                 for i in range(12)] + [_linha(200 + i, "TR-01" if i < 8 else "TR-02", 29037, "19:46", None)
                                        for i in range(12)])
    vinte_e_sete = {9: [_ev("17:48", f"27{f}", dia=23) for f in "ABC"]}     # disparou às 14:48 e não limpou
    gerando = [_lido("UFV 01", "TR-01", 11, pot=13.0), _lido("UFV 02", "TR-02", 9, pot=6.0)]
    mw = _Matriz({29036: R1, 29037: R8}, gerando, vinte_e_sete)
    u = {"slug": "pereiras", "nome": "Pereiras"}
    assert await diagnostico.diagnosticar(mw, u, pereiras, agora=datetime(2026, 11, 23, 20, tzinfo=UTC)) == []
    await diagnostico.diagnosticar(mw, u, pereiras, agora=datetime(2026, 11, 23, 20, 10, tzinfo=UTC))
    assert mw.pedidos == [29036, 29037, 29037]           # a aberta é conferida a cada volta (a duração entra)

    # O mesmo 27 com o relé do skid sem medir energia passando: o disjuntor abriu, e o aviso sai como antes.
    aberto = _Matriz({29036: R1, 29037: R8}, [gerando[0], _lido("UFV 02", "TR-02", 9, pot=0.0)], vinte_e_sete)
    desarmado, = await diagnostico.diagnosticar(aberto, u, pereiras, agora=datetime(2026, 11, 23, 20, tzinfo=UTC))
    assert desarmado.codigo == "27" and desarmado.titulo == "skid DESARMADO agora" and desarmado.skids == ["TR-02"]

    # Parada de verdade (R4): o aviso sai, com o veredito da matriz na prova.
    real = [_linha(300, "TR-02", None, "16:00", None)]
    a, = await diagnostico.diagnosticar(_Matriz({300: R4}, gerando), u, real, agora=datetime(2026, 11, 23, 17, tzinfo=UTC))
    assert a.codigo == "PARADA:zero_active_power" and "Verificação do meuWatt: Parada (linha R4 do mapa)." in a.texto()

    # A verificação não respondeu: "não consegui conferir" não é "não é parada". Sai como antes, e diz isso.
    b, = await diagnostico.diagnosticar(_Matriz({}, gerando, falha=True), u, real,
                                        agora=datetime(2026, 11, 23, 17, tzinfo=UTC))
    assert b.codigo == "PARADA:zero_active_power" and "Verificação do meuWatt indisponível agora" in b.texto()
    # O meuWatt renomeou o campo: a forma estranha também não cala a parada.
    c, = await diagnostico.diagnosticar(_Matriz({300: {"row": "R4", "result": "Parada", "tipo": "parada"}}, gerando), u,
                                        real, agora=datetime(2026, 11, 23, 17, tzinfo=UTC))
    assert "Verificação do meuWatt indisponível agora" in c.texto()


R6 = {"row": "R6", "result": "Parada para avaliar: zerou tudo, sem queda abrupta e sem o relé para confirmar",
      "kind": "avaliar"}
R3 = {"row": "R3", "result": "Falha de comunicação: avaliar", "kind": "comunicacao"}
R5 = {"row": "R5", "result": "Parada: zerou tudo, e o relé confirma", "kind": "parada"}


def _manha(i, inv, skid, frota, ini, fim, causa="never_woke_up", grupo=None):
    """Uma linha do detector de Pereiras em 24/11/2026 (horas em UTC: 05:31 BRT = 08:31Z), com a frota do skid."""
    return {"id": i, "plant_id": 9373, "group_id": grupo, "transformer_name": skid, "slot_label": inv,
            "stopped_at": f"2026-11-24T{ini}:00Z", "resolved_at": fim and f"2026-11-24T{fim}:00Z", "cause": causa,
            "materiality": "material", "shadow_loss_kwh": 5.0, "inversores_no_skid": frota}


async def test_livro_1_dois_dj_bt_nao_desligam_juntos():
    """O livro do bot (`docs/LIVRO_DO_BOT.md`), lição 1, o dono em 24/11/2026: "Dois DJ BT diferentes desligados juntos
    logo de manhã. Isso é praticamente impossível. Se não ver trip, mas também não tiver comunicação, é bem provável que
    seja trip". Pereiras 24/11 07:07: "sem trip … disjuntor de BT aberto" no TR-01 e no TR-02, com os relés do TR-01
    mudos desde 23/11 14:42 e oito dos doze inversores gerando desde 05:20."""
    diagnostico._VEREDITOS.clear()
    agora, u = datetime(2026, 11, 24, 10, 7, tzinfo=UTC), {"slug": "pereiras", "nome": "Pereiras"}
    mudos = [_lido("UFV Pereiras - UFV 01 - 1000kVA", "TR-01", 11, comm="no_comm", ultima="2026-11-23T17:42:00Z"),
             _lido("UFV Pereiras - Geral - 1500kVA", "TR-01", 12, comm="no_comm")]
    ufv02 = _lido("UFV Pereiras - UFV 02 - 500kVA", "TR-02", 9, pot=6.0)
    manha = [_manha(1, "INV15", "TR-01", 8, "08:31", "09:50"),
             _manha(2, "INV16", "TR-01", 8, "09:02", "09:50", "zero_active_power"),
             _manha(3, "INV21", "TR-02", 4, "08:31", "09:40")]
    manha += [_manha(10 + n, f"INV{n}", "TR-01" if n < 20 else "TR-02", 8 if n < 20 else 4, "09:33", "09:51",
                     "communication_failure", 29122) for n in (12, 13, 14, 17, 18, 22, 23, 24)]

    # A matriz do meuWatt (R6, R3, R1): nada disso é parada. Só o relé mudo avisa.
    real = await diagnostico.diagnosticar(_Matriz({1: R6, 2: R3, 3: R6, 29122: R1}, [*mudos, ufv02]), u, manha,
                                          agora=agora)
    assert [a.codigo for a in real] == ["RELE_SEM_COMUNICACAO"]

    # Sem a matriz: um aviso para os dois skids, que diz o que se sabe (havia tensão) e nunca "sem trip" nem DJ BT.
    diagnostico._VEREDITOS.clear()                       # o veredito das encerradas ficou guardado acima
    a = next(x for x in await diagnostico.diagnosticar(_Matriz({}, [*mudos, ufv02], falha=True), u, manha, agora=agora)
             if x.codigo == "NAO_LIGOU")
    t = a.texto()
    assert a.skids == ["TR-01", "TR-02"] and a.chave == "diag:pereiras:NAO_LIGOU:TR-01+TR-02:2026-11-24T08:31"
    assert "havia tensão: não é trip nem DJ BT (lição 1 do livro do bot)" in a.causa and "isolação baixa" in a.causa
    assert "sem trip" not in t.lower() and "disjuntor de BT" not in t and "INV12" not in t   # leitura não é parada
    assert "TR-01: 2 de 8 inversor(es) (INV15, INV16) parado(s) desde " in t and "TR-02: 1 de 4 inversor(es) (INV21)" in t
    assert "Relé UFV Pereiras - UFV 01 - 1000kVA sem comunicação desde 23/11 14:42: o trip não aparece." in t
    assert "Relé UFV Pereiras - Geral - 1500kVA sem comunicação nas últimas 48 h: o trip não aparece." in t

    # A usina inteira sem ligar de manhã, com relé mudo: dois DJ BT juntos não, o provável é trip. Um aviso só.
    tudo = ([_manha(100 + n, f"INV{n}", "TR-01", 8, "08:31", None) for n in range(11, 19)]
            + [_manha(200 + n, f"INV{n}", "TR-02", 4, "08:31", None) for n in range(21, 25)])
    parada = {p["id"]: R5 for p in tudo}
    b, = [x for x in await diagnostico.diagnosticar(_Matriz(parada, [*mudos, ufv02]), u, tudo, agora=agora)
          if x.codigo == "NAO_LIGOU"]
    assert b.skids == ["TR-01", "TR-02"] and b.causa.startswith("2 skids inteiros pararam juntos, e dois DJ BT não "
                                                                "desligam juntos (lição 1 do livro do bot)")
    assert "o provável é trip" in b.causa and "disjuntor de BT" not in b.texto()
    # Os relés lendo, sem trip: a causa é comum (a rede ou a proteção geral), ainda não o DJ BT de cada um.
    lendo = [_lido("UFV 01", "TR-01", 11, pot=0.0), _lido("UFV 02", "TR-02", 9, pot=0.0)]
    c, = await diagnostico.diagnosticar(_Matriz(parada, lendo), u, tudo, agora=agora)
    assert "a causa é comum aos skids (a rede ou a proteção geral)" in c.causa and "disjuntor de BT" not in c.texto()

    # Um skid inteiro: com o relé mudo, provável trip; lendo e sem trip, aí sim o DJ BT.
    so_01 = [p for p in tudo if p["transformer_name"] == "TR-01"]
    d, = [x for x in await diagnostico.diagnosticar(_Matriz(parada, [*mudos, ufv02]), u, so_01, agora=agora)
          if x.codigo == "NAO_LIGOU"]
    assert d.causa == "o skid inteiro parou e não há como ver trip: o provável é trip (lição 1 do livro do bot)"
    e, = await diagnostico.diagnosticar(_Matriz(parada, lendo), u, so_01, agora=agora)
    assert "sem trip no relé dele, que está lendo: falta de tensão no AC do inversor (disjuntor de BT aberto)" in e.causa

    # O histórico de trips que não veio também não é "sem trip"; nem o skid sem relé no meuWatt.
    class SemHistorico(_Matriz):
        async def eventos_de_trip(self, slug, rele, n):
            raise RuntimeError("500 Internal Server Error")

    f, = await diagnostico.diagnosticar(SemHistorico(parada, lendo), u, so_01, agora=agora)
    assert "o provável é trip" in f.causa and "O histórico de trips do relé UFV 01 não veio: o trip não aparece." in f.texto()
    g, = await diagnostico.diagnosticar(_Matriz(parada, [ufv02]), u, so_01, agora=agora)
    assert "o provável é trip" in g.causa and "O skid não tem relé de proteção no meuWatt: o trip não aparece." in g.texto()


def test_livro_do_bot_tem_as_licoes_que_o_diagnostico_cita():
    """A lição citada no aviso existe no livro (o número no código e o texto do dono no livro não se perdem)."""
    import re
    from pathlib import Path

    livro = (Path(__file__).resolve().parents[2] / "docs" / "LIVRO_DO_BOT.md").read_text()
    citadas = set(re.findall(r"lição (\d+) do livro do bot", Path(diagnostico.__file__).read_text()))
    assert citadas and all(re.search(rf"^## Lição {n} · ", livro, re.M) for n in citadas)
