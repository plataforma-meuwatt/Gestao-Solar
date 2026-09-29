"""Micro usina (MICRO do meuWatt): o vínculo e o aviso de parada.

O que se protege:

- **O coletor lê os alertas confirmados do MICRO** e gera um evento "parada" por usina
  daqui casada com aquela micro usina — com a chave do EPISÓDIO do meuWatt, para a mesma
  parada nunca avisar duas vezes.
- **Credencial de serviço**, e só ela: sem ponte configurada o coletor cala (aviso no
  relatório), nunca inventa "parou".
- **Usina sem interesse não gera chamada**: o motor só pergunta ao meuWatt se alguém marcou
  o aviso de parada numa usina casada com micro usina.
- **O vínculo micro não se apaga sozinho**: o painel manda o estado inteiro da linha a cada
  "Ligar/Desligar"; um painel publicado antes deste campo não o manda, e isso não pode
  descasar a micro usina em silêncio.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.api.v1 import painel
from app.core import cripto
from app.models.integracao import Integracao, Produto
from app.models.notificacao import NotificacaoEnviada, NotificacaoPreferencia
from app.models.user import Perfil, User, UserPlantAccess
from app.services import conciliacao, motor

BASE = "https://api.meuwatt.test"
MW = "mw_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"


@pytest.fixture(autouse=True)
def _chave_de_teste(monkeypatch):
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))


@pytest.fixture
def ponte(db):
    """A credencial de serviço do meuWatt gravada em Painel → Conexões."""
    db.add(Integracao(produto=Produto.MEUWATT, base_url=BASE, token_cifrado=cripto.cifrar(MW),
                      token_prefixo="mw_pat_1xNq", ativa=True))
    db.commit()


@pytest.fixture
def cenario(db, usinas):
    """Porto Ferreira casada com a micro usina 7 e um cliente que marcou o aviso de parada."""
    usina, _ = usinas
    usina.mw_micro_plant_id = 7
    cliente = User(apelido="dono", nome="Dono", perfil=Perfil.CLIENTE, telefone="+5516999990000",
                   whatsapp_aceite_em=datetime.now(UTC))
    db.add(cliente)
    db.commit()
    db.add(UserPlantAccess(user_id=cliente.id, plant_link_id=usina.id))
    db.add(NotificacaoPreferencia(user_id=cliente.id, tipo="parada", plant_link_id=usina.id))
    db.commit()
    return usina, cliente


def _alerta(**kw):
    base = {"id": 12, "key": "micro:12", "active": True, "kind": "offline", "kind_label": "Sem comunicação",
            "plant_id": 7, "plant_name": "UFV Sitio", "station_name": "UFV Sitio Canadian",
            "provider": "canadian", "started_at": "2026-09-28T17:20:00Z"}
    base.update(kw)
    return base


@respx.mock
async def test_alerta_da_micro_usina_vira_evento_de_parada(db, ponte, cenario):
    usina, _ = cenario
    rota = respx.get(f"{BASE}/micro/alerts", params={"active": "true"}).respond(
        200, json=[_alerta(), _alerta(id=13, key="micro:13", plant_id=99)])
    rel = motor.Relatorio()

    eventos = await motor._coletar_parada_micro(db, rel)

    assert rota.call_count == 1
    assert [(e.tipo, e.plant_link_id, e.chave) for e in eventos] == [("parada", usina.id, "parada:micro:12")]
    nome, equipamento, hora = eventos[0].parametros
    assert nome == "Porto Ferreira"
    assert equipamento == "UFV Sitio Canadian (sem comunicação)"
    assert hora  # formato conferido em test_hora_em_brasilia
    assert rel.avisos == []


@respx.mock
async def test_sem_ponte_cala_e_avisa(db, cenario):
    rel = motor.Relatorio()
    assert await motor._coletar_parada_micro(db, rel) == []
    assert rel.avisos and "MICRO" in rel.avisos[0]


@respx.mock
async def test_sem_interesse_nao_pergunta_ao_meuwatt(db, ponte, usinas):
    usina, _ = usinas
    usina.mw_micro_plant_id = 7  # casada, mas ninguém marcou o aviso de parada
    db.commit()
    rota = respx.get(f"{BASE}/micro/alerts").respond(200, json=[_alerta()])
    assert await motor._coletar_parada_micro(db, motor.Relatorio()) == []
    assert rota.call_count == 0


@respx.mock
async def test_o_motor_entrega_uma_vez_por_episodio(db, ponte, cenario, monkeypatch):
    """Pelo caminho inteiro do tipo "parada": template de parada, e a segunda volta não repete."""
    _, cliente = cenario
    enviados = []

    async def fake(*, telefone, template, parametros, origem=None):
        enviados.append((telefone, template, parametros))
        return {"ok": True, "wamid": f"w{len(enviados)}", "status": "enviada", "erro": None}

    monkeypatch.setattr(motor.gateway, "enviar_template", fake)
    respx.get(f"{BASE}/micro/alerts").respond(200, json=[_alerta()])

    await motor.disparar(db, tipos=["parada"])
    rel = await motor.disparar(db, tipos=["parada"])

    assert [(t, tpl) for t, tpl, _ in enviados] == [(cliente.telefone, "gs_usina_parada")]
    assert rel.repetidas == 1
    assert db.query(NotificacaoEnviada).one().chave == "parada:micro:12"


def test_hora_em_brasilia():
    # O "hoje" da função é em BRASÍLIA, e o teste montava a hora em UTC: entre 00:00 e
    # 03:00 UTC os dois calendários discordam, e o teste reprovava sozinho de madrugada —
    # foi o que aconteceu em 29/09/2026. O instante de referência agora nasce em BRT.
    agora = datetime.now(motor.BRT)
    hoje = agora.replace(hour=12, minute=5, second=0, microsecond=0)
    assert motor._hora_brt(hoje.isoformat()) == "12:05"
    antes = (agora - timedelta(days=10)).replace(hour=20, minute=17)
    assert motor._hora_brt(antes.isoformat()).count("/") == 1  # outro dia leva a data
    assert motor._hora_brt(None) == "—"


# ── o vínculo no painel ─────────────────────────────────────────────────────


def _salvar(db, admin, link, **extra):
    corpo = {"plant_link_id": link.id, "mw_slug": link.mw_plant_slug, "mp_usina_id": link.mp_usina_id,
             "nome": link.nome, "no_app": True, **extra}
    return painel.salvar_usina(painel.UsinaIn(**corpo), db=db, _=admin)


def test_casar_manter_e_descasar_a_micro_usina(db, administrador, usinas):
    usina, _ = usinas
    assert _salvar(db, administrador, usina, mw_micro_plant_id=7).mw_micro_plant_id == 7
    # Painel antigo, sem o campo: "Ligar/Desligar" não pode descasar.
    assert _salvar(db, administrador, usina, no_app=False).mw_micro_plant_id == 7
    # `null` explícito descasa.
    assert _salvar(db, administrador, usina, mw_micro_plant_id=None).mw_micro_plant_id is None


def test_duas_usinas_nao_apontam_para_a_mesma_micro_usina(db, administrador, usinas):
    a, b = usinas
    _salvar(db, administrador, a, mw_micro_plant_id=7)
    with pytest.raises(HTTPException) as erro:
        _salvar(db, administrador, b, mw_micro_plant_id=7)
    assert erro.value.status_code == 409 and "Porto Ferreira" in erro.value.detail


def test_a_linha_da_conciliacao_carrega_a_micro_usina(usinas):
    a, _ = usinas
    a.mw_micro_plant_id = 7
    linha = next(l for l in conciliacao.montar([], [], [a]) if l.plant_link_id == a.id)
    assert linha.mw_micro_plant_id == 7


@respx.mock
async def test_catalogo_de_micro_usinas_pela_credencial_de_servico(db, ponte):
    rota = respx.get(f"{BASE}/micro/plants", params={"live": "false"}).respond(200, json={
        "plants": [{"id": 1, "name": "UFV Sitio", "capacity_kwp": 124.32,
                    "stations": [{"name": "UFV Sitio Solis"}, {"name": "UFV Sitio Canadian"}]}],
        "errors": []})
    r = await painel.micro_usinas(db=db, _=None)
    assert rota.called
    assert [(u.id, u.nome, u.estacoes) for u in r.usinas] == [(1, "UFV Sitio", ["UFV Sitio Solis", "UFV Sitio Canadian"])]
    assert r.aviso is None


@respx.mock
async def test_catalogo_sem_acesso_abre_vazio_com_aviso(db, ponte):
    respx.get(f"{BASE}/micro/plants").mock(return_value=httpx.Response(403, json={"detail": "Acesso negado"}))
    r = await painel.micro_usinas(db=db, _=None)
    assert r.usinas == [] and r.aviso and "MICRO" in r.aviso
