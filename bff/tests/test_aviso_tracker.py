"""O aviso de TRACKER TRAVADO, por push (pedido do dono, 08/11/2026).

O meuWatt detecta e guarda os travamentos e os comandos do helper (mw-api 4b9fadb); daqui sai o toque: travou, o
comando não destravou ("agir manualmente") e a volta, uma vez cada.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.api.v1 import avisos as rota_avisos
from app.core.security import gerar_hash_senha
from app.models.permissao import Dispositivo, Permissao
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import avisos

AGORA = datetime.now(UTC)


def _iso(minutos_atras: float) -> str:
    return (AGORA - timedelta(minutes=minutos_atras)).isoformat()


def _inc(id_, situacao, inicio, fim=None, **extra):
    return {"id": id_, "slave_id": 7, "row": 1, "label": "C7·F1", "started_at": _iso(inicio),
            "ended_at": None if fim is None else _iso(fim), "duration_min": inicio - (fim or 0),
            "angle_start": 53.92, "situacao": situacao, "evento": None, **extra}


def test_a_regua_de_cada_aviso():
    travado = avisos.avisos_de_tracker(6, "Ibitinga", {"travados": 1, "incidents": [_inc(3, "travado", 25)]}, None,
                                       AGORA)
    [(chave, titulo, corpo, depois)] = travado
    assert chave == "6:tracker:3:travado" and titulo == "Ibitinga · tracker travado" and depois is None
    assert corpo.startswith("C7·F1 em falha a 53,9° desde ")

    ev = {"acao": "reset", "por": "Renan", "enviado_em": _iso(30)}
    [(c, t, b, d)] = avisos.avisos_de_tracker(6, "Ibitinga", {"incidents": [
        _inc(3, "helper_manual", 100, 20, evento=ev)]}, None, AGORA)
    assert c == "6:tracker:3:volta" and t == "Ibitinga · tracker destravado" and d == "6:tracker:3:travado"
    assert "pelo helper por Renan" in b and "ficou travado 1h20" in b

    [(_, t, b, d)] = avisos.avisos_de_tracker(6, "Ibitinga", {"incidents": [_inc(3, "pendente", 100, 20)]}, None,
                                              AGORA)
    assert t == "Ibitinga · tracker voltou" and "Falta classificar" in b and d is None   # a pendência sempre avisa

    # Velho demais não é notícia: aberto há 4 dias, voltou há 2.
    assert avisos.avisos_de_tracker(6, "I", {"incidents": [_inc(1, "travado", 4 * 1440)]}, None, AGORA) == []
    assert avisos.avisos_de_tracker(6, "I", {"incidents": [_inc(1, "pendente", 3000, 2880)]}, None, AGORA) == []


def test_nao_voltou_so_do_que_ainda_esta_travado():
    abertos = {"travados": 1, "incidents": [_inc(3, "travado", 60)]}
    eventos = {"events": [{"id": 9, "acao": "nao_voltou", "slave_id": 7, "row": 1, "enviado_em": _iso(20)},
                          {"id": 8, "acao": "nao_voltou", "slave_id": 2, "row": 1, "enviado_em": _iso(20)},
                          {"id": 7, "acao": "nao_voltou", "slave_id": 7, "row": 1, "enviado_em": _iso(90)},
                          {"id": 6, "acao": "reset", "slave_id": 7, "row": 1, "enviado_em": _iso(25)}]}
    saida = avisos.avisos_de_tracker(6, "Ibitinga", abertos, eventos, AGORA)
    nv = [s for s in saida if s[0].endswith(":nao_voltou")]
    # o 8 é de outro tracker (que não está travado) e o 7 é de antes deste travamento
    assert [s[0] for s in nv] == ["6:tracker_evento:9:nao_voltou"]
    assert nv[0][1] == "Ibitinga · tracker não voltou" and nv[0][2].endswith("Agir manualmente.")


class _MeuWatt:
    def __init__(self):
        self.incidentes = {"travados": 0, "incidents": []}
        self.eventos_lidos = 0

    async def trackers_travamentos(self, slug, inicio, fim):
        return self.incidentes

    async def trackers_comandos(self, slug, inicio, fim):
        self.eventos_lidos += 1
        return {"events": []}


@pytest.fixture
def cenario(db, monkeypatch):
    pessoa = User(apelido="renan.marquezini", nome="Renan", perfil=Perfil.CLIENTE,
                  senha_hash=gerar_hash_senha("x-1234"))
    db.add(pessoa)
    db.commit()
    ibitinga = PlantLink(id=6, nome="Ibitinga", mw_plant_slug="ibitinga", ativo=True)
    db.add(ibitinga)
    db.add(Dispositivo(user_id=pessoa.id, token="ExponentPushToken[x]", visto_em=AGORA))
    db.commit()
    mw = _MeuWatt()
    monkeypatch.setattr(avisos, "usinas_do_usuario", lambda db_, u: [ibitinga])
    monkeypatch.setattr(avisos.vinculos, "obter", lambda db_, uid, produto: object())
    monkeypatch.setattr(avisos.vinculos, "cliente_meuwatt", lambda db_, uid: mw)
    enviados = []

    async def _enviar(tokens, titulo, corpo, dados=None):
        enviados.append((titulo, corpo, dados))
        return type("R", (), {"enviados": len(tokens), "erros": [], "invalidos": []})()

    async def _nada(db_):
        return []

    monkeypatch.setattr(rota_avisos.push, "enviar", _enviar)
    monkeypatch.setattr(avisos, "paradas_por_usuario", _nada)
    monkeypatch.setattr(avisos, "sem_comunicacao_por_usuario", _nada)
    return pessoa, mw, enviados


async def test_travou_e_voltou_um_toque_cada_so_para_quem_o_gestor_deu(db, cenario):
    pessoa, mw, enviados = cenario
    mw.incidentes = {"travados": 1, "incidents": [_inc(3, "travado", 25)]}
    assert (await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)).enviados == 0   # sem a permissão
    db.add(Permissao(user_id=pessoa.id, categoria="notificacao", subcategoria="tracker_travado"))
    db.commit()

    r = await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)
    assert r.enviados == 1 and enviados[-1][0] == "Ibitinga · tracker travado"
    assert enviados[-1][2] == {"tipo": "tracker_travado", "usina_id": 6} and mw.eventos_lidos == 1
    r = await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)
    assert r.enviados == 0 and r.repetidos == 1                                    # o mesmo travamento não repete

    mw.incidentes = {"travados": 0, "incidents": [_inc(3, "automatico", 60, 5, evento={
        "acao": "reset", "enviado_em": _iso(8)}), _inc(4, "automatico", 40, 10)]}
    r = await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)
    # a volta do 3 (que ele viu travar) sai; a do 4, que travou e voltou sozinho sem ninguém saber, não acorda ninguém
    assert r.enviados == 1 and enviados[-1][0] == "Ibitinga · tracker destravado"
    assert "destravado automático pelo helper" in enviados[-1][1]
    assert mw.eventos_lidos == 2                                  # os comandos só se leem com tracker travado
