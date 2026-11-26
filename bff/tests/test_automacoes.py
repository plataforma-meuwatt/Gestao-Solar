"""As automações (Plano Assistente GS, 26/11/2026): gatilho, condição, ação e entrega, com o "nunca enganar".

O dono: "tudo é gatilho, ação e onde enviar". Cada teste é um pedaço do que ele pediu: o horário que dispara uma vez,
o lembrete, a tensão do relé "por mais de 10 min" (pela hora da LEITURA), a regra que fica cega e avisa, o "voltou" só
confirmado, o ensaio, o "todas menos X", a entrega (WhatsApp só na janela, push, ou espera a próxima mensagem), a IA
que só lê, a trava da volta e a gente na usina com OS aberta.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.automacao import Automacao, AutomacaoDisparo
from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
from app.models.empresa import Empresa
from app.models.permissao import Dispositivo
from app.models.plant import PlantLink
from app.models.user import Perfil, User, VinculoProduto
from app.services import automacoes as auto
from app.services import push, vinculos

T0 = datetime(2026, 11, 26, 14, 0, tzinfo=UTC)          # 11:00 em Brasília


class _MW:
    """O meuWatt de mentira: o que cada rota devolve, por usina."""

    def __init__(self):
        self.leit: dict = {}
        self.mon: dict = {}
        self.ativos: list = []
        self.chamadas: list = []

    async def leituras(self, slug):
        self.chamadas.append(("leituras", slug))
        return self.leit[slug]

    async def monitoramento_atual(self, slug):
        self.chamadas.append(("monitoramento", slug))
        return self.mon[slug]

    async def alertas(self, slug, status="active", limit=200):
        return {"alerts": self.ativos}


@pytest.fixture
def mundo(db, monkeypatch):
    emp = Empresa(nome="Splendor")
    db.add(emp)
    db.commit()
    piraz = PlantLink(mw_plant_slug="pirapozinho", mp_usina_id=39, nome="Pirapozinho", empresa_id=emp.id, ativo=True)
    tiete = PlantLink(mw_plant_slug="tiete", mp_usina_id=502, nome="Tiete", empresa_id=emp.id, ativo=True)
    db.add_all([piraz, tiete])
    renan = User(apelido="renan", email="r@x.com", nome="Renan", perfil=Perfil.GESTOR_EMPRESA, empresa_id=emp.id,
                 telefone="+5517997377626", bot_meuwatt=True, bot_meuplano=True, ativo=True)
    db.add(renan)
    db.commit()
    db.add_all([VinculoProduto(gs_user_id=renan.id, produto=p, usuario_remoto_id="1", token_cifrado="x")
                for p in ("meuwatt", "meuplano")])
    db.commit()
    db.refresh(renan)
    mw = _MW()
    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda db_, uid, so_proprio=False: mw)
    saidas: dict = {"whatsapp": [], "push": []}

    async def _enviar(**k):
        saidas["whatsapp"].append(k)
        return {"ok": True, "wamid": f"wamid-{len(saidas['whatsapp'])}"}

    async def _push(tokens, titulo, corpo, dados=None):
        saidas["push"].append({"titulo": titulo, "corpo": corpo, "dados": dados})
        return push.Resultado(enviados=len(tokens))

    from app.clients import whatsapp

    monkeypatch.setattr(whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(push, "enviar", _push)
    return {"db": db, "emp": emp, "piraz": piraz, "tiete": tiete, "renan": renan, "mw": mw, "saidas": saidas}


def _janela(db, user, quando):
    """A pessoa falou com o bot (a mensagem DELA abre a janela de 24 h)."""
    db.add(RegistroBot(telefone=user.telefone, gs_user_id=user.id, resultado="respondeu", em=quando))
    db.commit()


def _acordar(db, regra):
    """A regra acorda na próxima volta (a sessão da suíte não faz autoflush: sem o commit, o UPDATE não vê)."""
    regra.proxima_em = None
    db.commit()


def _disparos(db, regra=None):
    q = db.query(AutomacaoDisparo)
    if regra is not None:
        q = q.filter_by(automacao_id=regra.id)
    return q.order_by(AutomacaoDisparo.id).all()


def _rele(valores, quando, estado="ok", marcadas=()):
    return {"relays": [{"name": "Relé Skid 1", "readings": [
        {"key": f"voltage_{f}", "unit": "V", "value": v, "status": estado, "last_valid_at": quando.isoformat(),
         **({"mark": {"ignored": True}} if f in marcadas else {})} for f, v in zip("abc", valores)]}]}


def _mon(quando, sol=True, **extra):
    return {"data_at": quando.isoformat(), "in_solar_window": sol, "inverters": [], "temp_sensors": [], **extra}


# ── horário e lembrete ──────────────────────────────────────────────────────


async def test_horario_dispara_uma_vez_e_reagenda(mundo):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    _janela(db, renan, T0 - timedelta(hours=1))
    regra = auto.criar(db, renan, nome="Ver alarmes", gatilho={"tipo": "horario", "hora": "11:30", "dias": None},
                       acao={"tipo": "mensagem", "texto": "ver os alarmes"}, agora=T0)
    assert auto._hora(regra.proxima_em) == "11:30"
    await auto.rodar_tique(db, T0 + timedelta(minutes=30, seconds=5))
    await auto.rodar_tique(db, T0 + timedelta(minutes=30, seconds=30))      # a mesma hora não manda de novo
    assert [d.status for d in _disparos(db, regra)] == ["enviada"]
    assert len(s["whatsapp"]) == 1 and "ver os alarmes" in s["whatsapp"][0]["texto"]
    assert "pausa a regra" in s["whatsapp"][0]["texto"]                       # a regra que repete diz como parar
    assert auto._utc(regra.proxima_em) == T0 + timedelta(days=1, minutes=30)  # amanhã no mesmo horário


async def test_lembrete_toca_uma_vez_e_conclui_e_atrasado_diz_a_hora(mundo):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    _janela(db, renan, T0)
    em = (T0 + timedelta(hours=1)).isoformat()
    regra = auto.criar(db, renan, nome="Lembrete", gatilho={"tipo": "uma_vez", "em": em},
                       acao={"tipo": "mensagem", "texto": "ver a geração"}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(hours=1, minutes=20))           # o servidor estava fora 20 min
    assert regra.situacao == "concluida" and regra.proxima_em is None
    texto = s["whatsapp"][0]["texto"]
    assert texto.startswith("⏰ Lembrete: ver a geração") and "(era para 12:00)" in texto
    assert "pausa a regra" not in texto


async def test_lembrete_no_passado_e_recusado(mundo):
    with pytest.raises(auto.RegraInvalida, match="já passou"):
        auto.criar(mundo["db"], mundo["renan"], nome="x", gatilho={"tipo": "uma_vez", "em": (T0 - timedelta(hours=1)).isoformat()},
                   acao={"tipo": "mensagem", "texto": "x"}, agora=T0)


async def test_horario_perdido_mais_de_60_min_avisa_e_reagenda(mundo):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    _janela(db, renan, T0)
    regra = auto.criar(db, renan, nome="Resumo", gatilho={"tipo": "horario", "hora": "11:30", "dias": None},
                       acao={"tipo": "mensagem", "texto": "x"}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(hours=3))
    [d] = _disparos(db, regra)
    assert d.evento == "perdida" and "não rodou a tempo" in d.texto
    assert auto._utc(regra.proxima_em) == T0 + timedelta(days=1, minutes=30)


# ── leitura: duração, cegueira, "voltou" ────────────────────────────────────


def _regra_tensao(db, renan, piraz, situacao="ligada"):
    return auto.criar(db, renan, nome="Tensão Skid 1", situacao=situacao, agora=T0,
                      gatilho={"tipo": "leitura", "grandeza": "tensao_rele", "alvo": "Relé Skid 1", "operador": "<",
                               "limite": 1000, "duracao_min": 10},
                      acao={"tipo": "mensagem"}, escopo={"usinas": [piraz.id]})


async def test_tensao_so_avisa_depois_de_10_min_seguidos_pela_hora_da_leitura(mundo):
    db, renan, mw, s = mundo["db"], mundo["renan"], mundo["mw"], mundo["saidas"]
    _janela(db, renan, T0)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    for minuto in (0, 4, 9):                                  # sem tensão, mas ainda não 10 min
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([0, 0, 0], t), _mon(t)
        _acordar(db, regra)
        await auto.rodar_tique(db, t + timedelta(seconds=20))
    assert _disparos(db, regra) == []
    t = T0 + timedelta(minutes=10)
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([0, 0, 0], t), _mon(t)
    _acordar(db, regra)
    await auto.rodar_tique(db, t + timedelta(seconds=20))
    [d] = _disparos(db, regra)
    assert d.evento == "disparo" and "sem tensão nas três fases há 10 min" in d.texto and "0/0/0 V" in d.texto
    assert "desde 11:00" in d.texto and "leitura das 11:10" in d.texto


async def test_voltou_so_depois_de_10_min_normal_e_rearma(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    _janela(db, renan, T0)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    regra.gatilho = {**regra.gatilho, "duracao_min": 0}

    async def ler(minuto, valores):
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele(valores, t), _mon(t)
        _acordar(db, regra)
        await auto.rodar_tique(db, t + timedelta(seconds=20))

    await ler(0, [0, 0, 0])
    await ler(2, [7900, 7910, 7905])                          # uma leitura boa NÃO é volta
    await ler(8, [7900, 7910, 7905])
    assert [d.evento for d in _disparos(db, regra)] == ["disparo"]
    await ler(12, [7900, 7910, 7905])                         # 10 min seguidos normal
    assert [d.evento for d in _disparos(db, regra)] == ["disparo", "voltou"]
    await ler(14, [0, 0, 0])                                  # rearmou: a queda nova avisa de novo
    assert [d.evento for d in _disparos(db, regra)] == ["disparo", "voltou", "disparo"]


async def test_fase_zerada_avisa_e_fase_marcada_ja_sei_nao_conta(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    _janela(db, renan, T0)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    regra.gatilho = {**regra.gatilho, "duracao_min": 0}
    leit = _rele([0, 7900, 7910], T0, marcadas=("a",))       # a fase A é «já sei» (o relé não lê)
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = leit, _mon(T0)
    await auto.rodar_tique(db, T0 + timedelta(seconds=20))
    assert _disparos(db, regra) == []
    leit["relays"][0]["readings"][1].update(value=3, status="zeroed")       # a fase B zerou de verdade
    _acordar(db, regra)
    await auto.rodar_tique(db, T0 + timedelta(seconds=40))
    [d] = _disparos(db, regra)
    assert "fase B zerada" in d.texto


async def test_sem_dado_com_sol_vira_cega_uma_vez_e_avisa_quando_volta(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    _janela(db, renan, T0)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    velho = T0 - timedelta(minutes=30)
    for minuto in (0, 10, 21, 25):                            # o relé mudo, com sol
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([None, None, None], velho, estado="no_comm"), _mon(t)
        _acordar(db, regra)
        await auto.rodar_tique(db, t)
    cegas = [d for d in _disparos(db, regra) if d.evento == "cega"]
    assert len(cegas) == 1 and "A regra está cega" in cegas[0].texto and "falta de energia" in cegas[0].texto
    t = T0 + timedelta(minutes=30)
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([7900, 7900, 7900], t), _mon(t)
    _acordar(db, regra)
    await auto.rodar_tique(db, t + timedelta(seconds=10))
    assert [d.evento for d in _disparos(db, regra)] == ["cega", "enxergou"]


async def test_de_noite_o_coletor_dorme_e_a_regra_nao_se_diz_cega(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    regra = _regra_tensao(db, renan, mundo["piraz"])
    for minuto in (0, 30, 60):
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"] = _rele([None, None, None], T0 - timedelta(hours=3), estado="unknown")
        mw.mon["pirapozinho"] = _mon(T0 - timedelta(hours=3), sol=False)
        _acordar(db, regra)
        await auto.rodar_tique(db, t)
    assert _disparos(db, regra) == []


async def test_sem_o_token_do_dono_a_regra_fica_cega_com_o_motivo(mundo, monkeypatch):
    db, renan = mundo["db"], mundo["renan"]
    _janela(db, renan, T0)

    def _sem(db_, uid, so_proprio=False):
        assert so_proprio is True                             # nunca o token da empresa
        raise vinculos.SemConexao("sem token")

    monkeypatch.setattr(vinculos, "cliente_meuwatt", _sem)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    for minuto in (0, 25):
        _acordar(db, regra)
        await auto.rodar_tique(db, T0 + timedelta(minutes=minuto))
    [d] = _disparos(db, regra)
    assert d.evento == "cega" and "token do meuWatt" in d.texto


async def test_ensaio_manda_so_o_primeiro_e_guarda_os_outros(mundo):
    db, renan, mw, s = mundo["db"], mundo["renan"], mundo["mw"], mundo["saidas"]
    _janela(db, renan, T0)
    regra = _regra_tensao(db, renan, mundo["piraz"], situacao="ensaio")
    regra.gatilho = {**regra.gatilho, "duracao_min": 0}
    for minuto, v in ((0, 0), (12, 7900), (23, 7900), (30, 0)):   # cai, volta (10 min seguidos), cai de novo
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([v, v, v], t), _mon(t)
        _acordar(db, regra)
        await auto.rodar_tique(db, t + timedelta(seconds=5))
    ds = _disparos(db, regra)
    assert [d.status for d in ds] == ["enviada", "simulada", "simulada"] and all(d.ensaio for d in ds)
    assert len(s["whatsapp"]) == 1 and s["whatsapp"][0]["texto"].startswith("[ensaio]")
    assert f"liga a regra {regra.id}" in s["whatsapp"][0]["texto"]
    assert auto.segurados(db, regra) == 2


# ── escopo, recorte e entrega ───────────────────────────────────────────────


async def test_todas_menos_x_pega_a_usina_nova_e_deixa_a_tirada_de_fora(mundo):
    db, renan, emp = mundo["db"], mundo["renan"], mundo["emp"]
    regra = auto.criar(db, renan, nome="Paradas", agora=T0, gatilho={"tipo": "leitura", "grandeza": "usina_parada"},
                       acao={"tipo": "mensagem"}, escopo={"todas": True, "menos": [mundo["tiete"].id]})
    nova = PlantLink(mw_plant_slug="nova", nome="Nova", empresa_id=emp.id, ativo=True)
    db.add(nova)
    db.commit()
    assert {u.nome for u in auto.usinas_da_regra(db, regra, renan)} == {"Pirapozinho", "Nova"}


async def test_regra_de_parada_ligada_tira_a_pessoa_do_aviso_antigo(mundo):
    db, renan = mundo["db"], mundo["renan"]
    regra = auto.criar(db, renan, nome="Paradas", agora=T0, situacao="ensaio",
                       gatilho={"tipo": "leitura", "grandeza": "usina_parada"}, acao={"tipo": "mensagem"},
                       escopo={"todas": True, "menos": [mundo["tiete"].id]})
    assert not auto.tem_regra_de_parada_ligada(db, renan.id)  # em ensaio o aviso antigo continua
    auto.mudar(db, regra, "ligada")
    assert auto.tem_regra_de_parada_ligada(db, renan.id)


async def test_parada_avisa_os_inversores_e_de_novo_quando_para_mais_um(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    _janela(db, renan, T0)
    regra = auto.criar(db, renan, nome="Paradas", agora=T0, gatilho={"tipo": "leitura", "grandeza": "usina_parada"},
                       acao={"tipo": "mensagem"}, escopo={"usinas": [mundo["piraz"].id]})
    desde = (datetime.now(UTC) - timedelta(minutes=40)).isoformat()   # a régua do aviso conta pelo relógio

    def inv(i):
        return {"id": f"slot-{i}", "name": f"Inv {i}", "serial_number": f"SN{i}", "down": True, "down_since": desde,
                "status": "fault"}

    mw.ativos = [{"kind": "stop", "sn": f"SN{i}", "estimated_loss_kwh": 30} for i in (13, 14)]
    mw.mon["pirapozinho"] = _mon(T0, inverters=[inv(13)])
    await auto.rodar_tique(db, T0)
    mw.mon["pirapozinho"] = _mon(T0 + timedelta(minutes=2), inverters=[inv(13), inv(14)])
    _acordar(db, regra)
    await auto.rodar_tique(db, T0 + timedelta(minutes=2))
    ds = _disparos(db, regra)
    assert [d.evento for d in ds] == ["disparo", "disparo"]
    assert "Inv 13" in ds[0].texto and "mais um inversor parou" in ds[1].texto


async def test_fora_da_janela_vai_pelo_push_e_sem_aparelho_espera_a_proxima_mensagem(mundo):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    _janela(db, renan, T0 - timedelta(days=2))               # a janela fechou
    r1 = auto.criar(db, renan, nome="A", gatilho={"tipo": "uma_vez", "em": (T0 + timedelta(minutes=1)).isoformat()},
                    acao={"tipo": "mensagem", "texto": "um"}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=1))
    assert _disparos(db, r1)[0].status == "adiada" and s["whatsapp"] == []
    db.add(Dispositivo(user_id=renan.id, token="ExponentPushToken[1]", plataforma="android"))
    db.commit()
    r2 = auto.criar(db, renan, nome="B", gatilho={"tipo": "uma_vez", "em": (T0 + timedelta(minutes=2)).isoformat()},
                    acao={"tipo": "mensagem", "texto": "dois"}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=2))
    d2 = _disparos(db, r2)[0]
    assert d2.status == "enviada" and d2.canal == "push" and s["push"][0]["corpo"].startswith("⏰ Lembrete: dois")


async def test_o_que_esperou_sai_na_proxima_mensagem_e_o_vencido_e_contado(mundo):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    regra = auto.criar(db, renan, nome="A", gatilho={"tipo": "horario", "hora": "11:30"},
                       acao={"tipo": "mensagem", "texto": "x"}, agora=T0)
    agora = datetime.now(UTC)
    db.add_all([AutomacaoDisparo(automacao_id=regra.id, user_id=renan.id, evento="disparo", chave="k1", texto="velho",
                                 status="adiada", em=agora - timedelta(hours=30)),
                AutomacaoDisparo(automacao_id=regra.id, user_id=renan.id, evento="disparo", chave="k2", texto="novo",
                                 status="adiada", em=agora - timedelta(hours=2))])
    db.commit()
    assert await auto.entregar_adiadas(db, renan) == 1
    texto = s["whatsapp"][0]["texto"]
    assert "novo" in texto and "velho" not in texto and "Ficaram 1 aviso que venceram" in texto
    assert {d.chave: d.status for d in _disparos(db, regra)} == {"k1": "venceu", "k2": "entregue"}


async def test_o_aviso_entra_na_conversa_e_no_log_sem_abrir_a_janela(mundo):
    db, renan = mundo["db"], mundo["renan"]
    _janela(db, renan, T0 - timedelta(hours=23))
    regra = auto.criar(db, renan, nome="A", gatilho={"tipo": "uma_vez", "em": (T0 + timedelta(minutes=1)).isoformat()},
                       acao={"tipo": "mensagem", "texto": "ver a geração"}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=1))
    from app.services import assistente

    conv = db.query(ConversaWhatsapp).one()
    historico, _, _ = assistente._ler_conversa(conv)
    assert historico[-1]["role"] == "assistant" and f"[aviso automático · regra {regra.id}" in historico[-1]["content"]
    assert db.query(RegistroBot).filter_by(resultado="automacao").count() == 1
    # a linha do aviso é a mais nova do Log, mas a janela continua sendo a da última mensagem DELE
    assert not auto.na_janela(db, renan, T0 + timedelta(hours=1, minutes=1))


async def test_a_ia_de_uma_automacao_nao_propoe_acao(mundo):
    from app.services import assistente_geracao as ger
    from app.services import assistente_helper as helper

    ctx = ger.Contexto(db=mundo["db"], user=mundo["renan"], telefone="+5517997377626", automacao=True)

    async def executar(db, user, telefone):
        raise AssertionError("não roda")

    r = helper.propor(ctx, "Abrir uma OS", 600, executar, parte=None, confirmacao="sim")
    assert "erro" in r and helper.PENDENTES.get(mundo["renan"].id) is None


async def test_a_trava_impede_duas_voltas_de_pegar_a_mesma_regra(mundo):
    db, renan = mundo["db"], mundo["renan"]
    regra = _regra_tensao(db, renan, mundo["piraz"])
    assert auto.pegar_devidas(db, T0) == [regra.id]
    assert auto.pegar_devidas(db, T0 + timedelta(minutes=1)) == []           # a outra volta não pega
    assert auto.pegar_devidas(db, T0 + timedelta(minutes=11)) == [regra.id]  # o deploy morreu no meio: volta sozinha


async def test_uma_regra_quebrada_nao_para_as_outras(mundo, monkeypatch):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    _janela(db, renan, T0)
    ruim = auto.criar(db, renan, nome="Ruim", gatilho={"tipo": "horario", "hora": "11:01"},
                      acao={"tipo": "desconhecida"}, escopo={"todas": True}, agora=T0)
    boa = auto.criar(db, renan, nome="Boa", gatilho={"tipo": "horario", "hora": "11:01"},
                     acao={"tipo": "mensagem", "texto": "ok"}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=1, seconds=5))
    # a de horário que quebra vai à próxima hora marcada (tentar a cada 5 min rodaria "a de hoje" de madrugada)
    assert ruim.ultimo_erro and auto._utc(ruim.proxima_em) == T0 + timedelta(days=1, minutes=1)
    assert [d.evento for d in _disparos(db, boa)] == ["disparo"]
    assert [d.evento for d in _disparos(db, ruim)] == ["erro"]


# ── gente na usina (meuGuarda) com OS aberta (meuPlano) ─────────────────────


async def test_gente_na_usina_com_os_aberta_avisa_uma_vez_por_os_por_dia(mundo, monkeypatch):
    db, renan, s = mundo["db"], mundo["renan"], mundo["saidas"]
    renan.meuguarda_liberado = True
    db.commit()
    _janela(db, renan, T0)
    eventos = [{"id": 1, "usina_id": 7, "tipo": "pessoa", "camera": "Perímetro 03",
                "aberto_em": (T0 - timedelta(minutes=1)).isoformat()}]

    class _MG:
        async def usinas(self):
            return [{"id": 7, "nome": "Pirapozinho", "gs_usina_id": mundo["piraz"].id}]

        async def alarmes_desde(self, de, limite=300):
            return eventos

    class _MP:
        async def ordens_servico(self, usina_id, status=None):
            return [{"id": 1638, "name": "Roçagem", "status": "EM_EXECUCAO"}] if status == "EM_EXECUCAO" else []

    from app.services import assistente_meuguarda as mg

    monkeypatch.setattr(mg, "cliente", lambda user: _MG())
    monkeypatch.setattr(mg, "disponivel", lambda user: True)
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: _MP())
    regra = auto.criar(db, renan, nome="Gente", agora=T0, gatilho={"tipo": "camera", "tipos": list(auto.GENTE)},
                       condicoes=[{"tipo": "os_aberta"}], acao={"tipo": "mensagem"}, escopo={"todas": True})
    await auto.rodar_tique(db, T0)
    eventos.append({"id": 2, "usina_id": 7, "tipo": "linha_cruzada", "camera": "Perímetro 04",
                    "aberto_em": T0.isoformat()})
    _acordar(db, regra)
    await auto.rodar_tique(db, T0 + timedelta(minutes=1))
    [d] = _disparos(db, regra)
    assert "Perímetro 03" in d.texto and "OS 1638" in d.texto and "Roçagem" in d.texto


async def test_gente_na_usina_sem_os_aberta_nao_avisa(mundo, monkeypatch):
    db, renan = mundo["db"], mundo["renan"]
    renan.meuguarda_liberado = True
    db.commit()

    class _MG:
        async def usinas(self):
            return [{"id": 7, "nome": "Pirapozinho", "gs_usina_id": mundo["piraz"].id}]

        async def alarmes_desde(self, de, limite=300):
            return [{"id": 1, "usina_id": 7, "tipo": "pessoa", "camera": "P3", "aberto_em": T0.isoformat()}]

    class _MP:
        async def ordens_servico(self, usina_id, status=None):
            return []

    from app.services import assistente_meuguarda as mg

    monkeypatch.setattr(mg, "cliente", lambda user: _MG())
    monkeypatch.setattr(mg, "disponivel", lambda user: True)
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: _MP())
    regra = auto.criar(db, renan, nome="Gente", agora=T0, gatilho={"tipo": "camera"},
                       condicoes=[{"tipo": "os_aberta"}], acao={"tipo": "mensagem"}, escopo={"todas": True})
    await auto.rodar_tique(db, T0)
    assert _disparos(db, regra) == []


# ── resumo da geração (a função fixa) e o teste ─────────────────────────────


async def test_resumo_da_geracao_sem_ia_e_sem_dado_nunca_vira_zero(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    mw.mon["pirapozinho"] = _mon(T0, energy_today_kwh=12340.0, capacity_kwp=3640.0, plant_pr_today=0.81)
    mw.mon["tiete"] = _mon(T0, energy_today_kwh=None)
    texto = await auto.resumo_geracao(db, auto._Volta(agora=T0 + timedelta(minutes=1)), renan,
                                      [mundo["piraz"], mundo["tiete"]])
    assert "Pirapozinho: 12.340 kWh · 3,39 kWh/kWp · PR 81%" in texto
    assert "Tiete: sem dados de energia" in texto and "Tiete: 0" not in texto


async def test_testar_mostra_o_que_sairia_sem_mandar_nada(mundo):
    db, renan, mw, s = mundo["db"], mundo["renan"], mundo["mw"], mundo["saidas"]
    regra = _regra_tensao(db, renan, mundo["piraz"])
    agora = datetime.now(UTC)
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([7900, 7910, 7905], agora), _mon(agora)
    texto = await auto.testar(db, regra)
    assert "Relé Skid 1" in texto and "dentro do limite" in texto
    assert s["whatsapp"] == [] and s["push"] == [] and (regra.estado or {}).get("alvos") is None


# ── a tela do gerente (oem-gs › Automações) ─────────────────────────────────


def test_o_gerente_ve_e_mexe_so_nas_regras_da_empresa_dele(mundo):
    from fastapi import HTTPException

    from app.api.v1 import empresa_automacoes as rotas

    db, renan = mundo["db"], mundo["renan"]
    outra = Empresa(nome="Outra O&M")
    db.add(outra)
    db.commit()
    estranho = User(apelido="estranho", email="e@x.com", nome="Estranho", perfil=Perfil.GESTOR_EMPRESA,
                    empresa_id=outra.id, ativo=True)
    db.add(estranho)
    db.commit()
    minha = auto.criar(db, renan, nome="Minha", gatilho={"tipo": "horario", "hora": "19:00"},
                       acao={"tipo": "resumo_geracao"}, escopo={"todas": True}, agora=T0)
    dela = auto.criar(db, estranho, nome="Dela", gatilho={"tipo": "horario", "hora": "19:00"},
                      acao={"tipo": "mensagem", "texto": "x"}, agora=T0)
    lista = rotas.listar(db=db, gerente=renan)
    assert [r.nome for r in lista.regras] == ["Minha"] and lista.regras[0].quando.startswith("todo dia às 19:00")
    assert rotas.mudar(minha.id, rotas.MudarIn(situacao="pausada"), db=db, gerente=renan).situacao == "pausada"
    for chamada in (lambda: rotas.mudar(dela.id, rotas.MudarIn(situacao="pausada"), db=db, gerente=renan),
                    lambda: rotas.apagar(dela.id, db=db, gerente=renan),
                    lambda: rotas.disparos(dela.id, db=db, gerente=renan)):
        with pytest.raises(HTTPException) as e:
            chamada()
        assert e.value.status_code == 404                     # de outra empresa: 404 sem nome
    assert dela.situacao == "ligada" and dela.apagada_em is None
    rotas.apagar(minha.id, db=db, gerente=renan)
    assert rotas.listar(db=db, gerente=renan).regras == []


async def test_ao_nascer_do_sol_o_ultimo_dado_da_vespera_nao_faz_a_regra_se_dizer_cega(mundo):
    """Pirapozinho, 26/11: o último dado era da 01:23. Contar o prazo dele diria "cega" toda manhã, antes de o coletor
    voltar: o prazo conta de quando a regra NOTOU a falta, com a usina acordada."""
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    regra = _regra_tensao(db, renan, mundo["piraz"])
    vespera = T0 - timedelta(hours=9)
    for minuto, sol in ((0, False), (30, False), (60, True), (70, True)):   # acorda aos 60; o coletor volta aos 75
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"] = _rele([None, None, None], vespera, estado="unknown")
        mw.mon["pirapozinho"] = _mon(vespera, sol=sol)
        _acordar(db, regra)
        await auto.rodar_tique(db, t)
    t = T0 + timedelta(minutes=75)
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([7900, 7900, 7900], t), _mon(t)
    _acordar(db, regra)
    await auto.rodar_tique(db, t + timedelta(seconds=10))
    assert _disparos(db, regra) == []


async def test_a_tela_diz_onde_esta_cega_a_agenda_os_avisos_e_recusa_ligar_lembrete_vencido(mundo):
    from fastapi import HTTPException

    from app.api.v1 import empresa_automacoes as rotas

    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    _janela(db, renan, T0)
    regra = auto.criar(db, renan, nome="Paradas", agora=T0, gatilho={"tipo": "leitura", "grandeza": "usina_parada"},
                       acao={"tipo": "mensagem"}, escopo={"todas": True})
    velho = T0 - timedelta(hours=1)
    for minuto in (0, 21):                                    # Pirapozinho calado, Tietê lendo
        mw.mon["pirapozinho"], mw.mon["tiete"] = _mon(velho), _mon(T0 + timedelta(minutes=minuto))
        _acordar(db, regra)
        await auto.rodar_tique(db, T0 + timedelta(minutes=minuto))
    [r] = rotas.listar(db=db, gerente=renan).regras
    assert r.situacao_rotulo == "Ligada · cega" and r.cega.startswith("Cega em Pirapozinho desde")
    assert r.cega.endswith("a outra lê") and r.onde == "todas as usinas" and r.entrega_rotulo == "WhatsApp e aplicativo"
    assert r.agenda_rotulo.startswith("Última conferência:") and r.situacao_ajuda == "Os avisos saem para a pessoa."
    [d] = rotas.disparos(regra.id, db=db, gerente=renan)
    assert d.evento_rotulo == "Ficou cega (sem dado)" and d.usina == "Pirapozinho" and d.status_rotulo == "Enviado"
    lista = rotas.listar(db=db, gerente=renan)
    assert lista.motor.agora is not None and lista.motor.ligado is False   # a suíte não liga o motor
    # o lembrete que já passou da hora não liga: dispararia na hora
    lembrete = auto.criar(db, renan, nome="L", gatilho={"tipo": "uma_vez", "em": (T0 + timedelta(minutes=5)).isoformat()},
                          acao={"tipo": "mensagem", "texto": "x"}, agora=T0)
    lembrete.situacao, lembrete.proxima_em = "pausada", datetime.now(UTC) - timedelta(minutes=1)   # a rota usa o relógio
    db.commit()
    with pytest.raises(HTTPException) as e:
        rotas.mudar(lembrete.id, rotas.MudarIn(situacao="ligada"), db=db, gerente=renan)
    assert e.value.status_code == 409 and "já passou" in e.value.detail
    assert rotas._linhas_da_leitura({"fases": {"a": {"valor": 0, "estado": "ok"}}, "leitura_em": T0.isoformat()}) == [
        "Fase A: 0 V (ok)", "Leitura de 26/11 11:00"]


# ── o que a reavaliação do plano cobrou (26/11): cada afirmação do documento com o seu teste ──────────────


async def test_de_dia_a_regra_se_diz_cega_uns_20_min_depois_da_ultima_leitura(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    _janela(db, renan, T0)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    for minuto in (0, 5, 10):                                 # lendo bem, acordada desde as 11:00
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([7900, 7900, 7900], t), _mon(t)
        _acordar(db, regra)
        await auto.rodar_tique(db, t)
    ultima = T0 + timedelta(minutes=10)                       # o relé cala às 11:10
    for minuto in (25, 31):
        t = T0 + timedelta(minutes=minuto)
        mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([7900, 7900, 7900], ultima), _mon(t)
        _acordar(db, regra)
        await auto.rodar_tique(db, t)
    [d] = _disparos(db, regra)
    assert d.evento == "cega" and "desde 11:10" in d.texto and auto._utc(d.em) is not None


async def test_sem_usina_no_recorte_a_regra_fica_cega_e_diz_por_que(mundo):
    db, renan = mundo["db"], mundo["renan"]
    _janela(db, renan, T0)
    regra = auto.criar(db, renan, nome="X", agora=T0, gatilho={"tipo": "leitura", "grandeza": "usina_parada"},
                       acao={"tipo": "mensagem"}, escopo={"usinas": [999]})   # usina que ele não vê
    for minuto in (0, 21):
        _acordar(db, regra)
        await auto.rodar_tique(db, T0 + timedelta(minutes=minuto))
    [d] = _disparos(db, regra)
    assert d.evento == "cega" and "nenhuma usina desta regra está no seu recorte" in d.texto


async def test_o_teto_de_ia_vira_erro_e_a_regra_vai_para_a_proxima_hora_marcada(mundo, monkeypatch):
    db, renan = mundo["db"], mundo["renan"]
    _janela(db, renan, T0)
    monkeypatch.setattr(auto, "_ia_hoje", lambda db_, dono, agora: auto.IA_POR_DIA)
    regra = auto.criar(db, renan, nome="Análise", gatilho={"tipo": "horario", "hora": "11:30"},
                       acao={"tipo": "ia", "prompt": "analisa"}, escopo={"todas": True}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=30, seconds=5))
    [d] = _disparos(db, regra)
    assert d.evento == "erro" and "análises da IA hoje" in d.texto
    assert auto._utc(regra.proxima_em) == T0 + timedelta(days=1, minutes=30)   # não tenta de novo de madrugada


async def test_o_teto_de_leituras_da_volta_adia_a_regra_para_a_volta_seguinte(mundo, monkeypatch):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    monkeypatch.setattr(auto, "MAX_LEITURAS_POR_VOLTA", 0)
    regra = _regra_tensao(db, renan, mundo["piraz"])
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([0, 0, 0], T0), _mon(T0)
    await auto.rodar_tique(db, T0)
    assert mw.chamadas == [] and auto._utc(regra.proxima_em) == T0 + timedelta(seconds=auto.VOLTA_S)
    assert _disparos(db, regra) == []


async def test_a_condicao_que_nao_vale_deixa_registro_sem_mandar_nada(mundo):
    db, renan, mw, s = mundo["db"], mundo["renan"], mundo["mw"], mundo["saidas"]
    _janela(db, renan, T0)
    mw.mon["pirapozinho"] = _mon(T0, plant_pr_today=0.81)
    regra = auto.criar(db, renan, nome="PR", gatilho={"tipo": "horario", "hora": "11:30"},
                       acao={"tipo": "resumo_geracao"}, condicoes=[{"tipo": "pr_dia", "operador": "<", "limite": 70}],
                       escopo={"usinas": [mundo["piraz"].id]}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=30, seconds=5))
    [d] = _disparos(db, regra)
    assert d.evento == "nao_valeu" and d.status == "simulada" and "Pirapozinho: PR 81% (limite 70%)" in d.texto
    assert s["whatsapp"] == [] and s["push"] == []


async def test_o_resumo_atrasado_diz_a_hora_que_era(mundo):
    db, renan, mw, s = mundo["db"], mundo["renan"], mundo["mw"], mundo["saidas"]
    _janela(db, renan, T0)
    mw.mon["pirapozinho"] = _mon(T0 + timedelta(minutes=50), energy_today_kwh=1000.0, capacity_kwp=3640.0)
    auto.criar(db, renan, nome="Resumo", gatilho={"tipo": "horario", "hora": "11:30"}, acao={"tipo": "resumo_geracao"},
               escopo={"usinas": [mundo["piraz"].id]}, agora=T0)
    await auto.rodar_tique(db, T0 + timedelta(minutes=50))
    assert "(era para 11:30; atrasou)" in s["whatsapp"][0]["texto"]


async def test_o_lembrete_que_nao_sai_em_1_h_desiste_com_o_erro_registrado(mundo, monkeypatch):
    db, renan = mundo["db"], mundo["renan"]
    _janela(db, renan, T0)
    regra = auto.criar(db, renan, nome="L", gatilho={"tipo": "uma_vez", "em": (T0 + timedelta(minutes=1)).isoformat()},
                       acao={"tipo": "ia", "prompt": "analisa"}, escopo={"todas": True}, agora=T0)
    monkeypatch.setattr(auto, "_ia_hoje", lambda db_, dono, agora: auto.IA_POR_DIA)   # a ação quebra sempre
    await auto.rodar_tique(db, T0 + timedelta(minutes=1))
    assert regra.situacao == "ligada" and auto._utc(regra.proxima_em) == T0 + timedelta(minutes=6)   # tenta de novo
    await auto.rodar_tique(db, T0 + timedelta(minutes=70))
    assert regra.situacao == "concluida" and regra.proxima_em is None and regra.ultimo_erro       # passou de 1 h: desiste
    assert {d.evento for d in _disparos(db, regra)} == {"erro"}


async def test_a_leitura_e_dividida_entre_as_regras_do_mesmo_dono_na_mesma_volta(mundo):
    db, renan, mw = mundo["db"], mundo["renan"], mundo["mw"]
    for nome in ("A", "B"):
        _regra_tensao(db, renan, mundo["piraz"]).nome = nome
    db.commit()
    mw.leit["pirapozinho"], mw.mon["pirapozinho"] = _rele([7900, 7900, 7900], T0), _mon(T0)
    await auto.rodar_tique(db, T0)
    assert sorted(mw.chamadas) == [("leituras", "pirapozinho"), ("monitoramento", "pirapozinho")]   # uma vez cada
