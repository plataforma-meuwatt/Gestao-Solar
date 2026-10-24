"""As paradas do portal, lidas do detector NOVO do meuWatt (`/shadow-breakdowns/queue`).

O que se protege aqui é a HONESTIDADE do número, não a beleza da tela:

1. A resposta vem do detector, pelo id NUMÉRICO da usina, e diz isso (`fonte`).
2. Só a linha `material` é parada: blip, imaterial e "sem dados" não entram na conta.
3. Perda sem conta feita (`no_peers`, que grava 0,0) é nula, não zero; e o total também.
4. O recorte é pelo dia BRT do início — o detector devolve por sobreposição.
5. "Não analisado" não é "não parou": sem rodada, ou com o período antes dela, o total é
   nulo; período que começa antes dela encolhe com aviso; detector parado ganha aviso.
6. Detector fora do ar ou em forma estranha → `total=None` + aviso, com 200.

Nada de rede: o cliente do meuWatt é uma subclasse que responde da memória.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.meuwatt import MeuWattClient
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.main import app
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

#: Agosto de 2026 — passado em relação a qualquer dia em que este teste rode.
REFERENCIA = "2026-08-15"

#: Uma rodada do detector como a de produção em 24/10/2026: de 01/02/2026 (meia-noite BRT)
#: até agora.
RODADA = {"run_id": 89, "plant_id": 9378, "plant_slug": "porto-ferreira",
          "window_start": "2026-02-01T03:00:00Z", "window_end": "2026-10-24T14:16:46Z"}


def _erro_http(status: int, detalhe: str = "Internal Server Error") -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", "https://api.meuwatt.test/shadow-breakdowns/queue")
    resposta = httpx.Response(status, json={"detail": detalhe}, request=pedido)
    return httpx.HTTPStatusError("erro", request=pedido, response=resposta)


class ClienteFalso(MeuWattClient):
    """Responde `usina` e `paradas_detector` da memória, e anota o que foi pedido."""

    def __init__(self, linhas=None, rodada=RODADA, erro=None):
        super().__init__(base_url="https://api.meuwatt.test", token="mw_pat_teste")
        self.linhas = linhas or []
        self.rodada = rodada
        self.erro = erro
        self.pedidos: list[tuple] = []
        self.usinas_pedidas: list[str] = []

    async def usina(self, slug):
        self.usinas_pedidas.append(slug)
        return {"id": 9378, "slug": slug, "name": "Porto Ferreira"}

    async def paradas_detector(self, plant_id, inicio, fim):
        self.pedidos.append((plant_id, inicio, fim))
        if self.erro:
            raise self.erro
        return {"run": self.rodada, "rows": self.linhas, "groups": [],
                "fleet_by_transformer": {}}


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
    def _cliente(_db, _cliente_id=None):
        return cliente

    monkeypatch.setattr("app.api.v1.paradas.vinculos.cliente_meuwatt", _cliente)
    return cliente


def _linha(id_, inicio, fim=None, off=120, perda=50.0, metodo="peer",
           materialidade="material", **extra):
    """Uma linha com a forma REAL do detector (Porto Ferreira, 23/10/2026)."""
    linha = {
        "id": id_, "plant_id": 9378, "slot_id": 100 + id_, "slot_label": f"Inv {id_}",
        "transformer_name": "SKID-01", "serial_number": f"SN{id_}", "transformer_id": 1,
        "stopped_at": inicio, "resolved_at": fim,
        "resolution_reason": "still_open" if fim is None else "production_resumed",
        "cause": "zero_active_power", "read_status_basis": "zero_while_reachable",
        "materiality": materialidade, "off_minutes": off, "shadow_loss_kwh": perda,
        "loss_method": metodo, "group_id": None, "evidence": {}, "detector_version": "v12",
    }
    linha.update(extra)
    return linha


def _ler(http, cabecalho, usina, consulta=f"referencia={REFERENCIA}"):
    r = http.get(f"/api/v1/plants/{usina.id}/paradas?{consulta}", headers=cabecalho)
    assert r.status_code == 200, r.text
    return r.json()


# ── a leitura ───────────────────────────────────────────────────────────────


def test_detector_responde_e_a_resposta_diz_de_onde_veio(http, cabecalho, minha, monkeypatch):
    cliente = _usar(monkeypatch, ClienteFalso([
        _linha(1, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z", off=120, perda=50),
        _linha(2, "2026-08-20T09:00:00Z", "2026-08-20T09:30:00Z", off=30, perda=12.5),
    ]))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["fonte"] == "detector"
    assert corpo["total"] == 2
    assert corpo["tempo_parado_min"] == 150
    assert corpo["perda_kwh"] == 62.5
    assert corpo["em_aberto"] == 0
    assert corpo["aviso"] is None
    # Mais recente primeiro.
    assert [p["id"] for p in corpo["paradas"]] == [2, 1]
    assert corpo["paradas"][0]["tipo"] == "parada"
    assert corpo["paradas"][0]["tom"] == "ok"
    assert corpo["paradas"][1]["inicio"] == "2026-08-03T09:00:00-03:00"
    assert corpo["inicio"] == "2026-08-01" and corpo["fim"] == "2026-08-31"
    # O detector pede o id NUMÉRICO, e a janela em instantes BRT com o fim exclusivo.
    assert cliente.pedidos == [
        (9378, "2026-08-01T00:00:00-03:00", "2026-09-01T00:00:00-03:00")
    ]


def test_so_a_linha_material_e_parada(http, cabecalho, minha, monkeypatch):
    """Blip e imaterial são piscadas sem perda; `data_gap` é a usina produzindo sem leitura
    (inclusive a linha "Usina inteira — sem dados", sem slot). Nenhuma é parada na tela de
    Paradas do meuWatt — e nenhuma pode virar parada na do dono."""
    _usar(monkeypatch, ClienteFalso([
        _linha(1, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z"),
        _linha(2, "2026-08-04T12:00:00Z", "2026-08-04T12:03:00Z", off=3, perda=0.0,
               materialidade="blip"),
        _linha(3, "2026-08-05T12:00:00Z", "2026-08-05T12:04:00Z", off=4, perda=0.1,
               materialidade="immaterial"),
        _linha(4, "2026-08-06T12:00:00Z", "2026-08-06T13:00:00Z", off=60, perda=0.0,
               metodo=None, materialidade="data_gap", cause="no_data", slot_id=None,
               slot_label=None),
    ]))

    corpo = _ler(http, cabecalho, minha)

    assert [p["id"] for p in corpo["paradas"]] == [1]
    assert corpo["total"] == 1 and corpo["tempo_parado_min"] == 120


def test_perda_sem_conta_feita_e_nula_e_nao_zero(http, cabecalho, minha, monkeypatch):
    """`no_peers`: nem par saudável nem irradiância — o detector grava 0,0 sem conta
    nenhuma. Zero ali diria "não perdeu nada"; nulo diz "não sabemos". E o total, que
    somaria só as outras, também fica nulo."""
    _usar(monkeypatch, ClienteFalso([
        _linha(1, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z", perda=50),
        _linha(2, "2026-08-04T12:00:00Z", "2026-08-04T14:00:00Z", perda=0.0, metodo="no_peers"),
    ]))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] == 2
    assert corpo["paradas"][0]["perda_kwh"] is None
    assert corpo["paradas"][1]["perda_kwh"] == 50
    assert corpo["perda_kwh"] is None


def test_parada_em_aberto_nao_tem_fim_e_conta_como_aberta(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso([
        _linha(1, "2026-08-25T15:00:00Z", None, off=95, perda=3.0),
    ]))

    corpo = _ler(http, cabecalho, minha)

    aberta = corpo["paradas"][0]
    assert aberta["em_aberto"] is True and aberta["fim"] is None and aberta["tom"] == "parado"
    assert corpo["em_aberto"] == 1


def test_sem_nenhuma_parada_o_total_e_zero_e_nao_nulo(http, cabecalho, minha, monkeypatch):
    """Zero paradas é medição: o detector analisou e não havia nada. Nulo é outra coisa."""
    _usar(monkeypatch, ClienteFalso([]))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["fonte"] == "detector"
    assert corpo["total"] == 0
    assert corpo["tempo_parado_min"] == 0
    assert corpo["perda_kwh"] == 0


def test_recorte_pelo_dia_de_inicio_na_usina(http, cabecalho, minha, monkeypatch):
    """O detector devolve tudo o que SOBREPÕE a janela. Fica no mês a parada que COMEÇOU
    nele, no fuso da usina: 01/09 01:00 UTC ainda é 31/08 na usina (entra); 01/08 00:30 UTC
    ainda é 31/07 (sai); a que veio de julho e terminou em agosto é de julho (sai)."""
    _usar(monkeypatch, ClienteFalso([
        _linha(1, "2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z"),
        _linha(2, "2026-08-01T00:30:00Z", "2026-08-01T01:00:00Z"),
        _linha(3, "2026-07-30T12:00:00Z", "2026-08-02T12:00:00Z"),
        _linha(4, "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z"),
    ]))

    corpo = _ler(http, cabecalho, minha)

    assert [p["id"] for p in corpo["paradas"]] == [1, 4]


# ── o que o detector analisou ───────────────────────────────────────────────


def test_sem_rodada_do_detector_e_nulo_e_nao_zero(http, cabecalho, minha, monkeypatch):
    """`run: null` = nenhuma rodada cobre a janela. A lista vazia que vem junto NÃO é
    "nenhuma parada" — ninguém olhou."""
    _usar(monkeypatch, ClienteFalso([], rodada=None))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None and corpo["fonte"] is None
    assert "não analisou" in corpo["aviso"]


def test_periodo_inteiro_antes_da_rodada_e_nulo(http, cabecalho, minha, monkeypatch):
    """Janeiro, com o detector começando em 01/02: a rodada é escolhida (ela encosta na
    borda), mas não analisou um dia sequer do mês."""
    _usar(monkeypatch, ClienteFalso([]))

    corpo = _ler(http, cabecalho, minha, "referencia=2026-01-15")

    assert corpo["total"] is None
    assert "não analisou" in corpo["aviso"]


def test_periodo_que_comeca_antes_da_rodada_encolhe_e_avisa(http, cabecalho, minha, monkeypatch):
    """O ano de 2026 com o detector desde 01/02: janeiro não foi analisado. A janela diz
    até onde ele foi, em vez de o ano parecer inteiro."""
    _usar(monkeypatch, ClienteFalso([_linha(1, "2026-03-03T12:00:00Z", "2026-03-03T14:00:00Z")]))

    corpo = _ler(http, cabecalho, minha, f"recorte=ano&referencia={REFERENCIA}")

    assert corpo["inicio"] == "2026-02-01" and corpo["fim"] == "2026-12-31"
    assert corpo["total"] == 1
    assert "a partir de 01/02/2026" in corpo["aviso"]


def test_detector_parado_ha_mais_de_20h_avisa_ate_quando_analisou(
    http, cabecalho, minha, monkeypatch
):
    _usar(monkeypatch, ClienteFalso(
        [], rodada={**RODADA, "window_end": "2026-08-20T12:00:00Z"}
    ))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] == 0
    assert "analisou até 20/08/2026 às 09:00" in corpo["aviso"]


def test_rodada_que_cobre_o_periodo_nao_avisa(http, cabecalho, minha, monkeypatch):
    """Parar no pôr do sol é normal (a noite de inverno tem ~12 h): até 20 h, sem aviso."""
    _usar(monkeypatch, ClienteFalso(
        [], rodada={**RODADA, "window_end": "2026-08-31T09:00:00Z"}
    ))

    assert _ler(http, cabecalho, minha)["aviso"] is None


# ── falhas ──────────────────────────────────────────────────────────────────


def test_detector_fora_do_ar_da_total_nulo_com_aviso_e_200(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(erro=httpx.ReadTimeout("demorou")))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None and corpo["fonte"] is None and corpo["paradas"] == []
    assert "detector de paradas" in corpo["aviso"] and "ReadTimeout" in corpo["aviso"]


def test_recusa_do_detector_traz_a_frase_do_produto(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso(erro=_erro_http(403, "Sem acesso ao Dashboard de Paradas")))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None
    assert "403 — Sem acesso ao Dashboard de Paradas" in corpo["aviso"]


def test_erro_http_sem_frase_nao_leva_a_url_do_upstream(http, cabecalho, minha, monkeypatch):
    """O texto do `HTTPStatusError` traz a URL do upstream — com o nome do produto, que o
    cliente não lê (`test_vocabulario_do_cliente`). Sem frase do produto, só o status."""
    pedido = httpx.Request("GET", "https://api.meuwatt.test/shadow-breakdowns/queue")
    erro = httpx.HTTPStatusError(
        "Server error '502 Bad Gateway' for url 'https://api.meuwatt.test/shadow-breakdowns/queue'",
        request=pedido, response=httpx.Response(502, text="<html>gateway</html>", request=pedido),
    )
    _usar(monkeypatch, ClienteFalso(erro=erro))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None
    assert "respondeu 502" in corpo["aviso"] and "meuwatt" not in corpo["aviso"].lower()


def test_linha_em_forma_estranha_e_falha_e_nao_parada_a_menos(http, cabecalho, minha, monkeypatch):
    """Um `materiality` renomeado não pode virar "nenhuma parada": a linha que não se
    classifica derruba a leitura para "sem dados"."""
    sem_classe = _linha(1, "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
    del sem_classe["materiality"]
    _usar(monkeypatch, ClienteFalso([sem_classe]))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None
    assert "ValueError" in corpo["aviso"]


def test_rodada_em_forma_estranha_e_aviso_e_nao_500(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso([], rodada=["não", "é", "objeto"]))

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None and "detector de paradas" in corpo["aviso"]


def test_ponte_nao_configurada_e_aviso_e_nao_500(http, cabecalho, minha, monkeypatch):
    def _sem_ponte(_db, _cliente_id=None):
        raise RuntimeError("A ponte com o meuWatt não está configurada.")

    monkeypatch.setattr("app.api.v1.paradas.vinculos.cliente_meuwatt", _sem_ponte)

    corpo = _ler(http, cabecalho, minha)

    assert corpo["total"] is None
    assert "meuWatt" in corpo["aviso"]


def test_o_id_da_usina_e_perguntado_uma_vez_so(http, cabecalho, minha, monkeypatch):
    """O id de uma usina não muda: a segunda tela não paga de novo o `/plants/{slug}`."""
    cliente = _usar(monkeypatch, ClienteFalso([]))

    _ler(http, cabecalho, minha)
    _ler(http, cabecalho, minha, "referencia=2026-07-15")

    assert cliente.usinas_pedidas == ["porto-ferreira"]
    assert [p[0] for p in cliente.pedidos] == [9378, 9378]


# ── recorte e período ───────────────────────────────────────────────────────


def test_recorte_ano_pede_o_ano_inteiro(http, cabecalho, minha, monkeypatch):
    cliente = _usar(monkeypatch, ClienteFalso(
        [_linha(1, "2026-02-03T12:00:00Z", "2026-02-03T14:00:00Z")],
        rodada={**RODADA, "window_start": "2025-11-01T03:00:00Z"},
    ))

    corpo = _ler(http, cabecalho, minha, f"recorte=ano&referencia={REFERENCIA}")

    assert corpo["inicio"] == "2026-01-01" and corpo["fim"] == "2026-12-31"
    assert corpo["total"] == 1 and corpo["aviso"] is None
    assert cliente.pedidos[0][1:] == ("2026-01-01T00:00:00-03:00", "2027-01-01T00:00:00-03:00")


def test_periodo_futuro_e_400(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso([]))

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?referencia=2099-01-01", headers=cabecalho)

    assert r.status_code == 400


def test_recorte_desconhecido_e_400(http, cabecalho, minha, monkeypatch):
    _usar(monkeypatch, ClienteFalso([]))

    r = http.get(f"/api/v1/plants/{minha.id}/paradas?recorte=dia", headers=cabecalho)

    assert r.status_code == 400


# ── escopo ──────────────────────────────────────────────────────────────────


def test_usina_sem_monitoramento_e_404(http, cabecalho, db, dono, monkeypatch):
    so_meuplano = PlantLink(mw_plant_slug=None, mp_usina_id=9, nome="Só manutenção")
    db.add(so_meuplano)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=so_meuplano.id))
    db.commit()
    _usar(monkeypatch, ClienteFalso([]))

    r = http.get(
        f"/api/v1/plants/{so_meuplano.id}/paradas?referencia={REFERENCIA}", headers=cabecalho
    )

    assert r.status_code == 404


def test_usina_de_outro_dono_e_404(http, cabecalho, minha, usinas, monkeypatch):
    _, alheia = usinas
    _usar(monkeypatch, ClienteFalso([]))

    r = http.get(f"/api/v1/plants/{alheia.id}/paradas?referencia={REFERENCIA}", headers=cabecalho)

    assert r.status_code == 404


def test_sem_sessao_e_401(http, minha):
    assert http.get(f"/api/v1/plants/{minha.id}/paradas").status_code == 401


def test_o_coletor_antigo_saiu_do_cliente_e_da_sonda():
    """Regra da casa: nunca o coletor antigo. Sem método nem linha no catálogo, chamá-lo de
    novo reprova o inverso da sonda (todo caminho do cliente tem de estar no catálogo)."""
    from app.services import sonda

    assert not hasattr(MeuWattClient, "paradas")
    assert not [r for r in sonda.MEUWATT if "breakdowns/range" in r.caminho]
