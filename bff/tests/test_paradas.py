"""As paradas do portal: uma fonte que responde 500 e uma reserva que diz a verdade.

O que se protege aqui é a HONESTIDADE do número, não a bonita da tela:

1. Quando a fonte primária (`breakdowns/range`) responde, a resposta vem dela e diz isso.
2. Quando ela cai (5xx/timeout), a reserva (`alerts?status=all`) assume com o MESMO
   contrato — e a primária não é tentada de novo por uma hora, porque cada tentativa
   custaria uma chamada falha por página aberta.
3. A reserva vem paginada e sem período: 503 alertas em duas páginas são lidos inteiros,
   e só os do período ficam.
4. Soma só o que existe: uma linha sem perda deixa o total de perda nulo, não menor.
5. As duas fontes fora → `total=None` + aviso, com 200. "Sem dados" ≠ "nenhuma parada".

Nada de rede: o cliente do meuWatt é uma subclasse que responde da memória — mas herda o
`alertas_todos` REAL, porque a paginação é o que se quer exercitar.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import paradas as modulo
from app.clients.meuwatt import MeuWattClient
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.main import app
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

#: Agosto de 2026 — passado em relação a qualquer dia em que este teste rode.
REFERENCIA = "2026-08-15"


def _erro_http(status: int) -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", "https://api.meuwatt.test/plants/x/breakdowns/range")
    resposta = httpx.Response(status, json={"detail": "Internal Server Error"}, request=pedido)
    return httpx.HTTPStatusError("erro", request=pedido, response=resposta)


class ClienteFalso(MeuWattClient):
    """Responde `paradas` e `alertas` da memória; `alertas_todos` é o de verdade."""

    def __init__(self, breakdowns=None, alertas=None, erro_paradas=None, erro_alertas=None):
        super().__init__(base_url="https://api.meuwatt.test", token="mw_pat_teste")
        self.breakdowns = breakdowns
        self.lista_alertas = alertas or []
        self.erro_paradas = erro_paradas
        self.erro_alertas = erro_alertas
        self.chamadas_paradas = 0
        self.paginas_pedidas: list[int] = []

    async def paradas(self, slug, inicio, fim):
        self.chamadas_paradas += 1
        if self.erro_paradas:
            raise self.erro_paradas
        return {
            "plant": slug,
            "start": inicio.isoformat(),
            "end": fim.isoformat(),
            "total": len(self.breakdowns),
            "breakdowns": self.breakdowns,
        }

    async def alertas(self, slug, status="active", limit=500, offset=0):
        self.paginas_pedidas.append(offset)
        if self.erro_alertas:
            raise self.erro_alertas
        pagina = self.lista_alertas[offset : offset + limit]
        return {"plant": slug, "total": len(self.lista_alertas), "alerts": pagina}


@pytest.fixture(autouse=True)
def _primaria_lembrada_de_nada():
    """A memória "primária fora por 1 h" é do processo — e o processo é o mesmo entre os
    testes. Cada um começa sem lembrança."""
    modulo.esquecer_indisponibilidade()
    yield
    modulo.esquecer_indisponibilidade()


@pytest.fixture
def dono(db):
    u = User(
        apelido="dono",
        nome="Dono",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
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


@pytest.fixture
def cabecalho(dono):
    token, _ = criar_token(dono.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def minha(db, dono, usinas):
    a, _ = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=a.id))
    db.commit()
    return a


def _usar(monkeypatch, cliente: ClienteFalso) -> ClienteFalso:
    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.paradas.integracoes.cliente_meuwatt", _cliente)
    return cliente


def _breakdown(id_, inicio, fim=None, off=120.0, loss=50.0, solved=True, **extra):
    linha = {
        "id": id_, "sn": f"SN{id_}", "slot_label": f"INV-{id_}", "type": "inverter",
        "stopped_at": inicio, "resolved_at": fim, "off_time_minutes": off,
        "solved": solved,
    }
    if loss is not None:
        linha["loss_kwh"] = loss
    linha.update(extra)
    return linha


def _alerta(id_, inicio, fim=None, ativo=False, dur=60.0, loss=10.0, kind="stop"):
    return {
        "id": id_, "inverter_id": 1, "sn": f"SN{id_}", "model": None,
        "transformer_name": None, "kind": kind, "status": 0, "notification": None,
        "message": None, "started_at": inicio, "resolved_at": fim, "is_active": ativo,
        "duration_minutes": dur, "estimated_loss_kwh": loss,
    }


# ── fonte primária ──────────────────────────────────────────────────────────


def test_primaria_responde_e_a_resposta_diz_de_onde_veio(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(breakdowns=[
        _breakdown(1, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z", off=120, loss=50),
        _breakdown(2, "2026-08-20T09:00:00Z", "2026-08-20T09:30:00Z", off=30, loss=12.5),
    ]))

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho)

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["fonte"] == "paradas"
    assert corpo["total"] == 2
    assert corpo["tempo_parado_min"] == 150
    assert corpo["perda_kwh"] == 62.5
    assert corpo["em_aberto"] == 0
    assert corpo["aviso"] is None
    # Mais recente primeiro.
    assert [p["id"] for p in corpo["paradas"]] == [2, 1]
    assert corpo["paradas"][0]["tipo"] == "parada"
    assert corpo["paradas"][0]["tom"] == "ok"
    assert corpo["inicio"] == "2026-08-01" and corpo["fim"] == "2026-08-31"


def test_perda_fica_nula_quando_uma_linha_veio_sem_perda(http, cabecalho, minha, monkeypatch):
    """Somar só as que têm faria a perda parecer menor do que foi. Nulo é honesto."""
    _usar(monkeypatch, ClienteFalso(breakdowns=[
        _breakdown(1, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z", loss=50),
        _breakdown(2, "2026-08-04T12:00:00Z", "2026-08-04T14:00:00Z", loss=None),
    ]))

    corpo = http.get(
        f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    ).json()

    assert corpo["total"] == 2
    assert corpo["perda_kwh"] is None
    assert corpo["paradas"][0]["perda_kwh"] is None
    assert corpo["paradas"][1]["perda_kwh"] == 50


def test_sem_nenhuma_parada_o_total_e_zero_e_nao_nulo(http, cabecalho, minha, monkeypatch):
    """Zero paradas é medição: a fonte respondeu e não havia nada. Nulo é outra coisa."""
    _usar(monkeypatch, ClienteFalso(breakdowns=[]))

    corpo = http.get(
        f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    ).json()

    assert corpo["fonte"] == "paradas"
    assert corpo["total"] == 0
    assert corpo["tempo_parado_min"] == 0
    assert corpo["perda_kwh"] == 0


# ── a troca de fonte ────────────────────────────────────────────────────────


def test_primaria_com_500_cai_na_reserva_e_nao_e_tentada_de_novo(http, cabecalho, minha, monkeypatch):
    cliente = _usar(monkeypatch, ClienteFalso(
        erro_paradas=_erro_http(500),
        alertas=[_alerta(7, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z")],
    ))
    url = f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}"

    primeira = http.get(url, headers=cabecalho).json()
    assert primeira["fonte"] == "alertas"
    assert primeira["total"] == 1
    assert primeira["aviso"] and "estimada" in primeira["aviso"]
    assert cliente.chamadas_paradas == 1

    segunda = http.get(url, headers=cabecalho).json()
    assert segunda["fonte"] == "alertas"
    # A primária falhou há segundos — não se gasta outra chamada nela.
    assert cliente.chamadas_paradas == 1


def test_tempo_esgotado_na_primaria_tambem_e_fonte_fora(http, cabecalho, minha, monkeypatch):
    cliente = _usar(monkeypatch, ClienteFalso(
        erro_paradas=httpx.ReadTimeout("demorou"),
        alertas=[_alerta(7, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z")],
    ))
    url = f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}"

    assert http.get(url, headers=cabecalho).json()["fonte"] == "alertas"
    http.get(url, headers=cabecalho)
    assert cliente.chamadas_paradas == 1


def test_4xx_da_primaria_nao_a_tira_do_ar_por_uma_hora(http, cabecalho, minha, monkeypatch):
    """Um 404 é a fonte recusando ESTE pedido, não a fonte caída: na próxima chamada ela é
    tentada de novo (a reserva assume só desta vez)."""
    cliente = _usar(monkeypatch, ClienteFalso(
        erro_paradas=_erro_http(404),
        alertas=[_alerta(7, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z")],
    ))
    url = f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}"

    assert http.get(url, headers=cabecalho).json()["fonte"] == "alertas"
    http.get(url, headers=cabecalho)
    assert cliente.chamadas_paradas == 2


def test_reserva_le_todas_as_paginas_e_recorta_pelo_periodo(http, cabecalho, minha, monkeypatch):
    """503 alertas em duas páginas (500 + 3). Só 3 são de agosto; um deles ainda está aberto."""
    fora = [_alerta(i, "2026-05-01T12:00:00Z", "2026-05-01T13:00:00Z") for i in range(1, 501)]
    dentro = [
        _alerta(9001, "2026-08-02T12:00:00Z", "2026-08-02T13:00:00Z"),
        _alerta(9002, "2026-08-25T15:00:00Z", None, ativo=True, dur=None, loss=3.0),
        # 01/09 01:00 UTC ainda é 31/08 22:00 na usina — entra em agosto, como no mw-api.
        _alerta(9003, "2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z"),
    ]
    cliente = _usar(monkeypatch, ClienteFalso(erro_paradas=_erro_http(500), alertas=fora + dentro))

    corpo = http.get(
        f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    ).json()

    assert cliente.paginas_pedidas == [0, 500]
    assert corpo["fonte"] == "alertas"
    assert corpo["total"] == 3
    assert [p["id"] for p in corpo["paradas"]] == [9003, 9002, 9001]
    aberta = corpo["paradas"][1]
    assert aberta["em_aberto"] is True and aberta["fim"] is None and aberta["tom"] == "parado"
    assert corpo["em_aberto"] == 1
    # A aberta não tem duração: o total de tempo parado fica nulo, a perda soma.
    assert corpo["tempo_parado_min"] is None
    assert corpo["perda_kwh"] == 23.0


def test_degradacao_vem_com_o_tipo_certo(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(
        erro_paradas=_erro_http(500),
        alertas=[_alerta(1, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z", kind="degradation")],
    ))

    corpo = http.get(
        f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    ).json()

    assert corpo["paradas"][0]["tipo"] == "degradacao"


def test_alerta_de_outro_tipo_nao_vira_parada(http, cabecalho, minha, monkeypatch):
    """`kind` é texto livre no schema do mw-api. Um tipo que este lado não conhece não pode
    cair em "parada" por padrão — só `stop` e `degradation` (e o ausente, que o schema
    trata como `stop`) entram na conta do dono."""
    _usar(monkeypatch, ClienteFalso(
        erro_paradas=_erro_http(500),
        alertas=[
            _alerta(1, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z", kind="communication"),
            _alerta(2, "2026-08-11T12:00:00Z", "2026-08-11T13:00:00Z", kind="stop"),
            {**_alerta(3, "2026-08-12T12:00:00Z", "2026-08-12T13:00:00Z"), "kind": None},
        ],
    ))

    corpo = http.get(
        f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    ).json()

    assert [p["id"] for p in corpo["paradas"]] == [3, 2]
    assert corpo["total"] == 2


def test_as_duas_fontes_fora_da_total_nulo_com_aviso_e_200(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(
        erro_paradas=_erro_http(500), erro_alertas=httpx.ReadTimeout("demorou")
    ))

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho)

    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] is None
    assert corpo["fonte"] is None
    assert corpo["paradas"] == []
    assert corpo["aviso"] and "não respondeu" in corpo["aviso"]


def test_ponte_nao_configurada_e_aviso_e_nao_500(http, cabecalho, minha, monkeypatch):
    async def _sem_ponte(_db):
        raise RuntimeError("A ponte com o meuWatt não está configurada.")

    monkeypatch.setattr("app.api.v1.paradas.integracoes.cliente_meuwatt", _sem_ponte)

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?referencia={REFERENCIA}", headers=cabecalho)

    assert r.status_code == 200
    assert r.json()["total"] is None
    assert "meuWatt" in r.json()["aviso"]


# ── recorte e período ───────────────────────────────────────────────────────


def test_recorte_ano_cobre_o_ano_inteiro(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(breakdowns=[
        _breakdown(1, "2026-02-03T12:00:00Z", "2026-02-03T14:00:00Z"),
    ]))

    corpo = http.get(
        f"/api/v1/plants/{minha.id}/paradas?recorte=ano&referencia={REFERENCIA}",
        headers=cabecalho,
    ).json()

    assert corpo["inicio"] == "2026-01-01" and corpo["fim"] == "2026-12-31"
    assert corpo["total"] == 1


def test_periodo_futuro_e_400(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(breakdowns=[]))

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?referencia=2099-01-01", headers=cabecalho)

    assert r.status_code == 400


def test_recorte_desconhecido_e_400(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(breakdowns=[]))

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?recorte=dia", headers=cabecalho)

    assert r.status_code == 400


# ── escopo ──────────────────────────────────────────────────────────────────


def test_usina_sem_monitoramento_e_404(http, cabecalho, db, dono, monkeypatch):
    so_meuplano = PlantLink(mw_plant_slug=None, mp_usina_id=9, nome="Só manutenção")
    db.add(so_meuplano)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=so_meuplano.id))
    db.commit()
    _usar(monkeypatch, ClienteFalso(breakdowns=[]))

    r = http.get(
        f"/api/v1/plants/{so_meuplano.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    )

    assert r.status_code == 404


def test_usina_de_outro_dono_e_404(http, cabecalho, minha, usinas, monkeypatch):
    _, alheia = usinas
    _usar(monkeypatch, ClienteFalso(breakdowns=[]))

    r = http.get(f"/api/v1/plants/{alheia.id}/paradas?referencia={REFERENCIA}", headers=cabecalho)

    assert r.status_code == 404


def test_sem_sessao_e_401(http, minha):
    assert http.get(f"/api/v1/plants/{minha.id}/paradas").status_code == 401
