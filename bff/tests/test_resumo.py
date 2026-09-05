"""A Visão geral — `GET /api/v1/resumo` — é composição, e composição erra em silêncio.

O que se protege aqui é a REGRA 0 na sua forma mais perigosa: uma usina cujo meuPlano não
respondeu tem de sair com a manutenção NULA e um aviso, nunca com "0 OS em andamento" —
que o cliente lê como "nada acontecendo". E os totais do topo somam só quem tem dado: uma
usina sem meta de projeto não entra no percentual, senão a carteira inteira pareceria
abaixo do esperado por causa de uma meta que ninguém cadastrou.

As funções irmãs (desempenho, paradas, ordens, cronograma, pendências) rodam DE VERDADE
aqui; o que é fantasia são os dois upstreams. Assim o teste pega o dia em que um irmão
mudar de contrato e a Visão geral passar a ler o campo errado.
"""

from datetime import date

import pytest
from fastapi import HTTPException

from app.api.v1 import paradas as modulo_paradas
from app.api.v1.resumo import _contar_cronograma, _no_mes, resumo
from app.api.v1.manutencao import CelulaOut, CronogramaOut, LinhaCronogramaOut
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

#: Um dia de agosto: o mês fechado que o cliente olha em setembro.
REFERENCIA = date(2026, 8, 14)


@pytest.fixture(autouse=True)
def _primaria_de_pe():
    """A memória de "fonte primária fora" é global ao processo; um teste não pode herdar
    a indisponibilidade que outro provocou."""
    modulo_paradas.esquecer_indisponibilidade()
    yield
    modulo_paradas.esquecer_indisponibilidade()


@pytest.fixture
def dono(db):
    u = User(
        apelido="renan.marquezini",
        email="renan@exemplo.com.br",
        nome="Renan",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


def _conceder(db, usuario, usina):
    db.add(UserPlantAccess(user_id=usuario.id, plant_link_id=usina.id))
    db.commit()


# ── os upstreams como fantasia ───────────────────────────────────────────────


class MeuWattFalso:
    """Porto Ferreira tem meta de projeto; Ribeirão Bonito não tem PVsyst cadastrado."""

    def __init__(self, fora_do_ar: bool = False):
        self.fora_do_ar = fora_do_ar

    async def geracao_periodo(self, slug, inicio, fim):
        if self.fora_do_ar:
            raise RuntimeError("meuWatt caiu")
        energia = 9500.0 if slug == "porto-ferreira" else 4000.0
        return {"total_generation_kwh": energia, "days_with_data": 14,
                "performance_ratio": 0.81, "availability_real_pct": 98.2,
                "availability_contratual_pct": 99.1, "summary": {"total_lost_kwh": 50.0},
                "monthly_summaries": []}

    async def pvsyst(self, slug, inicio, fim):
        if slug != "porto-ferreira":
            return {"rows": [], "years": [], "count": 0}
        linhas = [
            {"date": f"2026-08-{d:02d}", "globinc": 5.0, "e_array": 700.0, "e_grid": 700.0}
            for d in range(1, 15)
        ]
        return {"rows": linhas, "years": [2026], "count": len(linhas)}

    async def pvsyst_manual(self, slug, ano):
        return {"year": ano, "rows": []}

    async def paradas(self, slug, inicio, fim, timeout=None):
        if slug != "porto-ferreira":
            return {"plant": slug, "total": 0, "breakdowns": []}
        return {
            "plant": slug, "total": 2,
            "breakdowns": [
                {"id": 1, "stopped_at": "2026-08-05T10:00:00-03:00",
                 "resolved_at": "2026-08-05T12:00:00-03:00", "off_time_minutes": 120,
                 "loss_kwh": 50.0, "solved": True, "type": "inverter"},
                # Em aberto e sem duração: é o que deixa `tempo_parado_min` nulo.
                {"id": 2, "stopped_at": "2026-08-20T09:00:00-03:00", "resolved_at": None,
                 "off_time_minutes": None, "loss_kwh": None, "solved": False, "type": "inverter"},
            ],
        }


class MeuPlanoFalso:
    """Porto Ferreira (mp 1) responde tudo; Ribeirão Bonito (mp 2) está fora do ar."""

    def __init__(self, fora_para: set[int] = frozenset({2})):
        self.fora_para = set(fora_para)

    def _garante(self, usina_id):
        if usina_id in self.fora_para:
            raise RuntimeError("meuPlano não respondeu")

    async def ordens_servico(self, usina_id, status=None):
        self._garante(usina_id)
        return [
            {"id": 1, "plant_id": usina_id, "status": "EM_EXECUCAO", "name": "Preventiva agosto",
             "task_count": 3, "task_realized_count": 1, "scheduled_date": "2026-08-10"},
            {"id": 2, "plant_id": usina_id, "status": "APROVADA", "name": "Corretiva do relé",
             "closed_at": "2026-08-03T18:00:00Z", "approved_at": "2026-08-05T10:00:00Z"},
            # Encerrada em julho: fora do mês de referência.
            {"id": 3, "plant_id": usina_id, "status": "APROVADA", "name": "Preventiva julho",
             "closed_at": "2026-07-20T18:00:00Z"},
        ]

    async def vc_contratos(self, usina_id):
        self._garante(usina_id)
        return [{"id": 20, "numero": 200, "title": "O&M 2026", "start_date": "2026-03-01",
                 "end_date": "2027-02-28", "vigente": True, "versao_consolidada": 2}]

    async def vc_cronograma(self, usina_id, container_id):
        self._garante(usina_id)
        meses = [f"2026-{m:02d}" for m in range(3, 13)] + ["2027-01", "2027-02"]
        return {
            "status": "CONSOLIDATED", "version": 2, "month_labels": meses,
            "rows": [{
                "plan_item_id": 1, "name": "Termografia", "periodicity_value": 1,
                "periodicity_unit": "mes", "expected_per_year": 12,
                "months": {str(i): 1 for i in range(1, 13)},
                # mar..ago = meses 1..6 até a referência; set em diante fica fora.
                "cell_status": {"1": "verde", "2": "verde", "3": "verde_ressalva",
                                "4": "vermelho", "5": "verde", "6": "azul", "7": "azul"},
            }],
        }

    async def vc_pendencias(self, usina_id):
        self._garante(usina_id)
        return [
            {"id": 1, "numero": 1001, "usina_id": usina_id, "title": "Alambrado caído",
             "status": "ABERTO", "shareable": True, "end_date": "2026-08-01",
             "extra": {"cobrada_pelo_cliente": True}, "created_at": "2026-07-01T12:00:00Z"},
            {"id": 2, "numero": 1002, "usina_id": usina_id, "title": "Limpeza dos módulos",
             "status": "EM_ANDAMENTO", "shareable": True, "extra": {},
             "created_at": "2026-07-10T12:00:00Z"},
            {"id": 3, "numero": 1003, "usina_id": usina_id, "title": "Troca de fusível",
             "status": "CONCLUIDO", "shareable": True, "extra": {"cobrada_pelo_cliente": True},
             "created_at": "2026-06-01T12:00:00Z"},
            # Interna: nunca chega ao cliente, em bloco nenhum.
            {"id": 4, "numero": 1004, "usina_id": usina_id, "title": "Interna", "status": "ABERTO",
             "shareable": False, "extra": {}, "created_at": "2026-07-01T12:00:00Z"},
        ]


async def _agora_falso(cliente, link, dia):
    """O tempo real de `listar_usinas`, sem a forma do monitoramento do meuWatt."""
    return {"potencia_kw": 300.0 if link.mw_plant_slug == "porto-ferreira" else 120.0,
            "capacidade_kwp": 1000.0, "energia_hoje_kwh": 1200.0}


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    porto, ribeirao = usinas
    _conceder(db, dono, porto)
    _conceder(db, dono, ribeirao)
    meuwatt = MeuWattFalso()
    meuplano = MeuPlanoFalso()

    async def _mw(_db):
        return meuwatt

    async def _mp(_db):
        return meuplano

    # Um patch no módulo `integracoes` vale para TODOS os irmãos: cada um o consulta na
    # hora da chamada.
    monkeypatch.setattr("app.services.integracoes.cliente_meuwatt", _mw)
    monkeypatch.setattr("app.services.integracoes.cliente_meuplano", _mp)
    monkeypatch.setattr("app.api.v1.plants._dados_meuwatt", _agora_falso)
    return {"porto": porto, "ribeirao": ribeirao, "meuwatt": meuwatt, "meuplano": meuplano}


def _por_nome(saida, nome):
    return next(u for u in saida.usinas if u.nome == nome)


# ── composição ──────────────────────────────────────────────────────────────


async def test_meuplano_fora_do_ar_em_uma_usina_nao_derruba_a_outra(db, dono, cenario):
    """O caso do aceite: uma usina com o meuPlano caído sai com manutenção NULA e aviso;
    a outra sai completa; os totais somam só quem respondeu."""
    saida = await resumo(referencia=REFERENCIA.isoformat(), db=db, usuario=dono)

    ribeirao = _por_nome(saida, "Ribeirão Bonito")
    assert ribeirao.manutencao is None
    assert ribeirao.pendencias_abertas is None
    assert "Manutenção" in (ribeirao.aviso or "")
    assert "Pendências" in (ribeirao.aviso or "")

    porto = _por_nome(saida, "Porto Ferreira")
    assert porto.manutencao is not None
    assert porto.manutencao.os_em_andamento == 1        # a EM_EXECUCAO
    assert porto.manutencao.previsto_ate_mes == 6       # mar..ago do contrato
    assert porto.manutencao.feitos == 3
    assert porto.manutencao.dispensados == 1            # verde_ressalva ≠ feito
    assert porto.manutencao.atrasados == 1
    assert porto.pendencias_abertas == 2                # a interna (shareable=False) não conta

    assert saida.manutencao is not None
    assert saida.manutencao.os_em_andamento == 1
    assert saida.manutencao.os_concluidas_mes == 1      # a de julho fica fora
    assert saida.manutencao.atrasados_total == 1
    assert saida.pendencias is not None
    assert saida.pendencias.abertas == 2
    assert saida.pendencias.prazo_vencido == 1
    assert saida.pendencias.cobradas_abertas == 1       # a cobrada concluída não é "aberta"


async def test_usina_sem_meta_fica_fora_do_percentual(db, dono, cenario):
    """Ribeirão Bonito gera mas não tem PVsyst: o esperado dela é nulo, e o percentual da
    carteira é o de Porto Ferreira sozinha — sem a usina sem meta puxar a conta para baixo."""
    saida = await resumo(referencia=REFERENCIA.isoformat(), db=db, usuario=dono)

    porto = _por_nome(saida, "Porto Ferreira")
    ribeirao = _por_nome(saida, "Ribeirão Bonito")
    assert ribeirao.energia_mes_kwh == 4000.0
    assert ribeirao.esperado_mes_kwh is None
    assert ribeirao.pct is None

    assert saida.usinas_com_dado == 2
    assert saida.energia_mes_kwh == 13500.0
    assert saida.esperado_mes_kwh == porto.esperado_mes_kwh
    assert saida.pct_do_esperado == porto.pct
    assert saida.tom == "ok"
    assert saida.situacao == "Dentro do esperado"
    assert saida.potencia_agora_kw == 420.0


async def test_nenhum_campo_vira_zero_onde_a_fonte_faltou(db, dono, cenario):
    """A tentação da composição: `or 0` num campo ausente. Tudo o que faltou tem de ser
    nulo — inclusive o tempo parado quando UMA parada veio sem duração."""
    saida = await resumo(referencia=REFERENCIA.isoformat(), db=db, usuario=dono)

    ribeirao = _por_nome(saida, "Ribeirão Bonito").model_dump()
    for campo in ("esperado_mes_kwh", "pct", "manutencao", "pendencias_abertas"):
        assert ribeirao[campo] is None, campo

    porto = _por_nome(saida, "Porto Ferreira")
    assert porto.paradas_mes == 2
    assert porto.tempo_parado_min is None


async def test_atencao_aponta_a_rota_de_cada_problema(db, dono, cenario):
    saida = await resumo(referencia=REFERENCIA.isoformat(), db=db, usuario=dono)

    porto = _por_nome(saida, "Porto Ferreira")
    rotas = {a.rota: a for a in saida.atencao}
    assert f"/usinas/{porto.id}/paradas" in rotas
    assert rotas[f"/usinas/{porto.id}/paradas"].tom == "parado"
    assert "1 parada em aberto" == rotas[f"/usinas/{porto.id}/paradas"].detalhe
    assert f"/usinas/{porto.id}/cronograma" in rotas
    assert f"/usinas/{porto.id}/pendencias" in rotas
    # O vermelho vem antes do âmbar — a lista já sai na ordem em que a tela a desenha.
    tons = [a.tom for a in saida.atencao]
    assert tons == sorted(tons, key=lambda t: {"parado": 0, "alerta": 1}[t])


async def test_meuwatt_fora_deixa_a_energia_nula_e_a_manutencao_de_pe(db, dono, cenario):
    """Falha do meuWatt não apaga o que veio do meuPlano — e vice-versa."""
    cenario["meuwatt"].fora_do_ar = True
    saida = await resumo(referencia=REFERENCIA.isoformat(), db=db, usuario=dono)

    porto = _por_nome(saida, "Porto Ferreira")
    assert porto.energia_mes_kwh is None
    assert "Energia" in (porto.aviso or "")
    assert porto.manutencao is not None
    assert saida.energia_mes_kwh is None
    assert saida.usinas_com_dado == 0
    assert saida.tom == "semDados"


async def test_referencia_futura_e_400(db, dono, cenario):
    with pytest.raises(HTTPException) as erro:
        await resumo(referencia="2099-01-01", db=db, usuario=dono)
    assert erro.value.status_code == 400


async def test_sem_usina_concedida_responde_vazio_com_aviso(db, dono, usinas, monkeypatch):
    saida = await resumo(referencia=REFERENCIA.isoformat(), db=db, usuario=dono)

    assert saida.usinas == []
    assert saida.manutencao is None
    assert saida.pendencias is None
    assert saida.aviso


# ── as réguas isoladas ──────────────────────────────────────────────────────


def _cronograma(status, *estados):
    meses = [f"2026-{m:02d}" for m in range(3, 13)] + ["2027-01", "2027-02"]
    celulas = [
        CelulaOut(mes=m, previsto=1, estado=e, feito=e == "verde",
                  dispensado=e == "verde_ressalva", atrasado=e == "vermelho")
        for m, e in zip(meses, list(estados) + [None] * (12 - len(estados)), strict=True)
    ]
    return CronogramaOut(usina="X", usina_id=1, status=status, meses=meses,
                         linhas=[LinhaCronogramaOut(nome="Termografia", meses=celulas)])


def test_cronograma_sem_versao_conta_nulo_e_nao_zero():
    assert _contar_cronograma(_cronograma(None), "2026-08") is None


def test_cronograma_conta_so_ate_o_mes_de_referencia_na_ordem_do_contrato():
    """A âncora é março; setembro em diante não entra na conta de agosto."""
    cro = _cronograma("CONSOLIDATED", "verde", "verde_ressalva", "vermelho", "azul",
                      "verde", "azul", "verde", "verde")
    contagens = _contar_cronograma(cro, "2026-08")
    assert contagens == {"previsto_ate_mes": 6, "feitos": 2, "dispensados": 1, "atrasados": 1}


def test_o_mes_da_conclusao_e_o_da_usina_nao_o_do_servidor():
    """22h do dia 31 em Brasília é 01h do dia 1 em UTC. A OS fechou em agosto."""
    from datetime import UTC, datetime

    assert _no_mes(datetime(2026, 9, 1, 1, 0, tzinfo=UTC), "2026-08")
    assert not _no_mes(datetime(2026, 9, 1, 1, 0, tzinfo=UTC), "2026-09")
    assert _no_mes(date(2026, 8, 31), "2026-08")
    assert not _no_mes(None, "2026-08")


# ── a porta ─────────────────────────────────────────────────────────────────


@pytest.fixture
def cliente_http(db):
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_a_rota_exige_sessao_e_a_irma_inexistente_e_404(cliente_http, dono):
    """O par que prova o deploy: a rota nova responde 401 sem token; uma parecida que não
    existe responde 404. Se as duas dessem o mesmo, não daria para saber se subiu."""
    assert cliente_http.get("/api/v1/resumo").status_code == 401
    assert cliente_http.get("/api/v1/resumox").status_code == 404

    token, _ = criar_token(dono.id)
    r = cliente_http.get("/api/v1/resumo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["usinas"] == []
