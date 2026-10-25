"""O aviso de usina SEM COMUNICAÇÃO, que a própria pessoa liga no aplicativo.

Pereiras, 25/10/2026: sem dado desde as 02:28, com sol e os 12 inversores em "erro de comunicação", e nenhum app tocou,
porque parada é o que o detector afirma e sem dado ele não afirma nada. Pedido do dono: poder ligar ele mesmo o aviso.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import avisos as rota_avisos
from app.core.db import get_db
from app.core.security import criar_token, criar_token_painel, gerar_hash_senha
from app.main import app
from app.models.permissao import AvisoEnviado, Dispositivo, Permissao
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import avisos

#: Agora de verdade: com uma data fixa o teste quebraria dias depois (o de paradas quebrou assim, avaliação 28).
AGORA = datetime.now(UTC)
CHAVE = "notificacao.usina_sem_comunicacao"


def _monitor(minutos_sem_dado: float | None, sol: bool = True) -> dict:
    data = None if minutos_sem_dado is None else (AGORA - timedelta(minutes=minutos_sem_dado)).isoformat()
    return {"in_solar_window": sol, "data_at": data, "plant_sleeping": True, "inverters": []}


def test_com_sol_trinta_minutos_sem_dado_e_sem_comunicacao():
    """A régua: com sol e 30 min ou mais sem dado. A noite, o dado fresco e a queda de dias não avisam."""
    assert avisos.sem_dado_desde(_monitor(379), AGORA) == _monitor(379)["data_at"]     # Pereiras, 25/10
    assert avisos.sem_dado_desde(_monitor(30), AGORA) is not None
    assert avisos.sem_dado_desde(_monitor(29), AGORA) is None                          # ainda pode ser atraso
    assert avisos.sem_dado_desde(_monitor(2), AGORA) is None                           # as outras cinco usinas
    assert avisos.sem_dado_desde(_monitor(379, sol=False), AGORA) is None              # noite não é queda
    assert avisos.sem_dado_desde(_monitor(5 * 24 * 60), AGORA) is None                 # histórico, não notícia
    assert avisos.sem_dado_desde(_monitor(None), AGORA) is None and avisos.sem_dado_desde(None, AGORA) is None


@pytest.fixture
def pessoa(db):
    u = User(apelido="renan.marquezini", nome="Renan", perfil=Perfil.CLIENTE, senha_hash=gerar_hash_senha("x-1234"))
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def http(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _cab(u):
    return {"Authorization": f"Bearer {criar_token(u.id)[0]}"}


def _parada(db, u):
    db.add(Permissao(user_id=u.id, categoria="notificacao", subcategoria="usina_parada"))
    db.commit()


def test_a_pessoa_liga_e_desliga_no_app_se_ja_tem_o_aviso_de_parada(db, http, pessoa):
    """A chave é da pessoa, mas só vale para quem o gestor já deu o aviso de parada; e o gestor, ao salvar as concessões
    no painel, não apaga a escolha dela."""
    assert http.put(f"/api/v1/me/permissoes/{CHAVE}", json={"ativo": True}, headers=_cab(pessoa)).status_code == 403
    assert http.put("/api/v1/me/permissoes/notificacao.usina_parada", json={"ativo": True},
                    headers=_cab(pessoa)).status_code == 404          # a de parada é do gestor, não se liga pelo app
    _parada(db, pessoa)
    assert http.put(f"/api/v1/me/permissoes/{CHAVE}", json={"ativo": True}, headers=_cab(pessoa)).status_code == 204
    assert CHAVE in http.get("/api/v1/me/permissoes", headers=_cab(pessoa)).json()["permissoes"]

    admin = User(apelido="admin", nome="Admin", perfil=Perfil.ADMINISTRADOR, senha_hash=gerar_hash_senha("a-1234"))
    db.add(admin)
    db.commit()
    r = http.put(f"/api/painel/clientes/{pessoa.id}/permissoes", json={"permissoes": ["notificacao.usina_parada"]},
                 headers={"Authorization": f"Bearer {criar_token_painel(admin.id)[0]}"})
    assert r.status_code == 204, r.text
    assert CHAVE in http.get("/api/v1/me/permissoes", headers=_cab(pessoa)).json()["permissoes"]

    assert http.put(f"/api/v1/me/permissoes/{CHAVE}", json={"ativo": False}, headers=_cab(pessoa)).status_code == 204
    assert CHAVE not in http.get("/api/v1/me/permissoes", headers=_cab(pessoa)).json()["permissoes"]


class _MeuWatt:
    def __init__(self, por_slug):
        self.por_slug, self.lidas = por_slug, []

    async def monitoramento_atual(self, slug):
        self.lidas.append(slug)
        return self.por_slug[slug]


@pytest.fixture
def cenario(db, pessoa, monkeypatch):
    pereiras = PlantLink(id=2, nome="Pereiras", mw_plant_slug="pereiras", ativo=True)
    tiete = PlantLink(id=5, nome="Tietê", mw_plant_slug="tiete", ativo=True)
    db.add_all([pereiras, tiete])
    db.add(Dispositivo(user_id=pessoa.id, token="ExponentPushToken[x]", visto_em=AGORA))
    db.commit()
    mw = _MeuWatt({"pereiras": _monitor(379), "tiete": _monitor(2)})
    monkeypatch.setattr(avisos, "usinas_do_usuario", lambda db_, u: [pereiras, tiete])
    monkeypatch.setattr(avisos.vinculos, "obter", lambda db_, uid, produto: object())
    monkeypatch.setattr(avisos.vinculos, "cliente_meuwatt", lambda db_, uid: mw)
    enviados = []

    async def _enviar(tokens, titulo, corpo, dados=None):
        enviados.append((titulo, corpo, dados))
        return type("R", (), {"enviados": len(tokens), "erros": [], "invalidos": []})()

    monkeypatch.setattr(rota_avisos.push, "enviar", _enviar)

    async def _sem_paradas(db_):
        return []

    monkeypatch.setattr(avisos, "paradas_por_usuario", _sem_paradas)
    return pessoa, mw, enviados


async def test_so_quem_ligou_e_tem_o_aviso_de_parada_recebe(db, cenario):
    pessoa, mw, _ = cenario
    assert await avisos.sem_comunicacao_por_usuario(db) == []                # não ligou
    db.add(Permissao(user_id=pessoa.id, categoria="notificacao", subcategoria="usina_sem_comunicacao"))
    db.commit()
    assert await avisos.sem_comunicacao_por_usuario(db) == []                # sem o de parada, a escolha não vale
    _parada(db, pessoa)
    [aviso] = await avisos.sem_comunicacao_por_usuario(db)
    assert aviso.usina.nome == "Pereiras" and aviso.chave.startswith("2:sem_dado:")
    assert sorted(mw.lidas) == ["pereiras", "tiete"]                        # cada usina lida uma vez só


async def test_o_push_sai_uma_vez_por_queda(db, cenario):
    """Um toque por queda: a chave leva o último dado da usina, então a próxima volta não repete; a próxima queda,
    depois de o dado voltar, avisa de novo."""
    pessoa, mw, enviados = cenario
    _parada(db, pessoa)
    db.add(Permissao(user_id=pessoa.id, categoria="notificacao", subcategoria="usina_sem_comunicacao"))
    db.commit()
    r = await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)
    assert r.enviados == 1 and len(enviados) == 1
    titulo, corpo, dados = enviados[0]
    assert titulo == "Pereiras · sem comunicação"
    assert corpo.startswith("Sem dado desde ") and "comunicação ou falta de energia" in corpo
    assert dados == {"tipo": "usina_sem_comunicacao", "usina_id": 2}
    r = await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)
    assert r.enviados == 0 and r.repetidos == 1 and len(enviados) == 1       # a mesma queda não repete
    mw.por_slug["pereiras"] = _monitor(45)                                    # o dado voltou e caiu de novo
    r = await rota_avisos.disparar_avisos_de_parada(simular=False, db=db)
    assert r.enviados == 1 and len(enviados) == 2
    assert db.query(AvisoEnviado).count() == 2
