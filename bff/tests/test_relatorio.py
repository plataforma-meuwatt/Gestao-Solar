"""O relatório de manutenção do período — o documento que o dono leva à diretoria.

O que estes testes protegem, em ordem de gravidade:

1. **Usina alheia é 404.** O `usina_id` vem do cliente; sem a cerca, trocar o número na URL
   leria o cumprimento do contrato de outro dono. E `contrato_id` de outra usina também é
   404 — ANTES de o agregado ser pedido.
2. **O período é recusado ANTES de ir ao upstream.** `de > ate`, mês futuro e mais de 24
   meses são 400 com a frase — e a fantasia do meuPlano PROVA que não foi chamada.
3. **O contrato é o mesmo da aba Cronograma.** Sem `contrato_id`, vale o consolidado mais
   recente pela régua de `_resolver_contrato` — nunca "o primeiro da lista".
4. **Nada é recalculado.** As contagens do cronograma saem como o meuPlano mandou, e
   `pct_cumprido` nulo continua nulo: "nada previsto" não é "0 % cumprido".
5. **Um vocabulário só.** OS `APROVADA` é "Concluída"/ok aqui como na aba Ordens; criticidade
   vira um dos seis tons; equipamento NÃO sai (é o nível que o dono disse não querer); a
   frase de "não publicado" é a mesma da aba Cronograma.
6. **PDF vazio é 502 com frase**, não um arquivo de zero bytes que o navegador abre em branco.

A fantasia do agregado segue a FORMA REAL de `relatorio_manutencao.montar` do meuPlano
(dispensas no topo, `cronograma_motivo`, `concluida_em_aprox`…), para a tradução ser
testada contra o que chega, não contra o que se imaginou. Nada de rede.
"""

from datetime import date, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import relatorio as mod
from app.api.v1.manutencao import NAO_PUBLICADO
from app.api.v1.relatorio import (
    MESES_MAX,
    ProblemasPorOsOut,
    pdf_do_relatorio,
    periodo_pedido,
    relatorio_de_manutencao,
    traduzir,
)
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess


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


def _erro_http(status: int, corpo: object) -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", "https://meuplano.exemplo/api/v1/meuacesso/visao-cliente/x")
    resposta = httpx.Response(status, json=corpo, request=pedido)
    return httpx.HTTPStatusError("erro", request=pedido, response=resposta)


#: Os contratos da usina como `vc_contratos` os devolve. O PRIMEIRO da lista é o que só tem
#: rascunho — de propósito: prova que o padrão não é `contratos[0]`.
CONTRATOS = [
    {"id": 78, "numero": 1300, "title": "O&M 2027 (em negociação)",
     "start_date": "2027-03-01", "end_date": "2028-02-28", "vigente": False,
     "versao_consolidada": None},
    {"id": 77, "numero": 1203, "title": "O&M 2026",
     "start_date": "2026-03-01", "end_date": "2027-02-28", "vigente": True,
     "versao_consolidada": 2},
]

#: A fantasia do JSON do meuPlano (`relatorio_manutencao.montar`), NA FORMA REAL, com os
#: casos de canto que importam: `pct_cumprido` nulo, OS APROVADA, problema com equipamento
#: (que não pode sair), pendência com prazo vencido e outra concluída.
AGREGADO = {
    "cabecalho": {
        "usina_id": 1, "usina": "Porto Ferreira",
        "cliente": "Eldorado", "executora": "Splendor",
        "contrato": {"id": 77, "numero": 1203, "titulo": "O&M 2026",
                     "start_date": "2026-03-01", "end_date": "2027-02-28", "status": None},
        "periodo": {"de": "2026-03", "ate": "2026-08",
                    "meses": ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]},
        "gerado_em": "2026-09-04T12:00:00",
    },
    "cronograma": {
        "cronograma_id": 40, "versao": 2, "anchor_month": "2026-03",
        "consolidated_at": "2026-03-02T10:00:00",
        "meses": ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
        "previsto": 10, "feito": 7, "dispensado": 1, "atrasado": 1, "no_prazo": 0, "sem_ativo": 1,
        "pct_cumprido": None,
        "linhas": [
            {"plan_item_id": 5, "nome": "Termografia", "type_code": "inversor", "categoria": "ensaio",
             "periodicity_value": 1, "periodicity_unit": "MONTH",
             "previsto": 6, "feito": 5, "dispensado": 0, "atrasado": 1, "no_prazo": 0, "sem_ativo": 0,
             "meses": {"2026-03": "verde"}},
            {"plan_item_id": 9, "nome": "Limpeza do quadro", "type_code": "quadro_eletrico",
             "categoria": "servico", "periodicity_value": 3, "periodicity_unit": "MONTH",
             "previsto": 4, "feito": 2, "dispensado": 1, "atrasado": 0, "no_prazo": 0, "sem_ativo": 1,
             "meses": {"2026-05": "verde_ressalva"}},
        ],
    },
    "cronograma_motivo": None,
    # NO TOPO, como o meuPlano manda — não dentro de `cronograma`.
    "dispensas": [{"plan_item_id": 9, "atividade": "Limpeza do quadro", "mes": "2026-05",
                   "escopo": "mes", "motivo": "CFTV ainda não finalizado"}],
    "ordens": [
        {"id": 1016, "name": "Preventiva agosto", "objetivo": None, "classification": "PREVENTIVA",
         "status": "APROVADA", "technician_name": "Diogo", "scheduled_date": "2026-08-10",
         "closed_at": "2026-08-10T18:00:00", "approved_at": "2026-08-12T09:00:00",
         "data_efetiva": "2026-08-12T09:00:00",
         "execution_minutes": 300, "task_count": 2, "task_realized_count": 2,
         "conclusao_gerente": "Tudo conforme.", "contrato_id": 77,
         "tarefas": [
             {"id": 6940, "name": "Termografia", "kind": "PHYSICAL_TESTS", "status": "APROVADA",
              "feita": True, "plan_type_label": "Inversor", "plan_item_name": "Termografia",
              "equipment_name": "Inversor 03", "equipamentos": 5, "contract_month": "2026-08",
              "verdict_status": "APPROVED"},
             {"id": 6941, "name": "Limpeza", "kind": "CUSTOM_SERVICE", "status": "REALIZADA",
              "feita": True, "plan_type_label": "Quadro", "plan_item_name": None,
              "equipment_name": "QGBT 1", "equipamentos": 1, "contract_month": "2026-08",
              "verdict_status": None},
         ]},
    ],
    "em_curso": [
        {"id": 1030, "name": "Corretiva relé", "objetivo": None, "classification": "CORRETIVA",
         "status": "EM_EXECUCAO", "task_count": 3, "task_realized_count": 1, "tarefas": []},
    ],
    "pareceres": {"aprovados": 4, "com_ressalva": 1, "reprovados": 0, "sem_parecer": 2,
                  "ordens_consideradas": 2, "ordens_em_curso_fora": 1},
    "problemas": {
        "total": 3,
        "ordens_consideradas": 2,
        "ordens_em_curso_fora": 1,
        "por_criticidade": {"urgente": 1, "alto": 2},
        "por_os": [{"os_id": 1016, "objetivo": "Preventiva agosto", "total": 3, "urgentes": 1,
                    "por_criticidade": {"urgente": 1, "alto": 2},
                    "equipamento": "Inversor 03"}],
    },
    "pendencias": {
        "abertas_no_fim": 1, "concluidas_no_periodo": 1,
        "abertas": [{"id": 501, "numero": 8801, "titulo": "Trocar fusível do skid 2",
                     "status": "ABERTO", "priority": None, "criticidade": "alta",
                     "criada_em": "2026-03-10T09:00:00", "prazo": "2020-01-01",
                     "atualizada_em": "2026-08-01T09:00:00", "concluida_em_aprox": None,
                     "cobrada_pelo_cliente": True}],
        "concluidas": [{"id": 502, "numero": 8802, "titulo": "Relatório de PR",
                        "status": "CONCLUIDO", "priority": None, "criticidade": None,
                        "criada_em": "2026-03-12T09:00:00", "prazo": "2026-05-01",
                        "atualizada_em": "2026-04-20T10:00:00",
                        "concluida_em_aprox": "2026-04-20T10:00:00",
                        "cobrada_pelo_cliente": False}],
    },
    "fotos_total": 41,
}


class ClienteFalso:
    """O meuPlano como fantasia: grava o que foi pedido e devolve o agregado."""

    def __init__(self, agregado=AGREGADO, pdf=b"%PDF-1.4 fingido", erro=None, contratos=CONTRATOS):
        self.agregado = agregado
        self.pdf = pdf
        self.erro = erro
        self.contratos = contratos
        self.pedidos: list[tuple] = []
        self.contratos_pedidos: list[int] = []

    async def vc_contratos(self, usina_id):
        self.contratos_pedidos.append(usina_id)
        return self.contratos

    async def vc_relatorio(self, usina_id, de, ate, container_id=None):
        self.pedidos.append(("json", usina_id, de, ate, container_id))
        if self.erro:
            raise self.erro
        return self.agregado

    async def vc_relatorio_pdf(self, usina_id, de, ate, container_id=None):
        self.pedidos.append(("pdf", usina_id, de, ate, container_id))
        if self.erro:
            raise self.erro
        return self.pdf


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    """O dono enxerga Porto Ferreira; Ribeirão Bonito é de outro cliente."""
    minha, _outra = usinas
    _conceder(db, dono, minha)
    cliente = ClienteFalso()

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.relatorio.integracoes.cliente_meuplano", _cliente)
    # Hoje fixo: os testes de período não podem virar a meia-noite de setembro.
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 4))
    return cliente


# ── período ──────────────────────────────────────────────────────────────────


def test_periodo_padrao_e_os_ultimos_doze_meses(cenario):
    assert periodo_pedido(None, None) == ("2025-10", "2026-09")


def test_periodo_explicito_passa_inteiro(cenario):
    assert periodo_pedido("2026-01", "2026-08") == ("2026-01", "2026-08")


def test_so_de_informado_vai_ate_o_mes_atual(cenario):
    assert periodo_pedido("2026-06", None) == ("2026-06", "2026-09")


@pytest.mark.parametrize(
    ("de", "ate", "trecho"),
    [
        ("2026-08", "2026-03", "depois de"),
        ("2026-01", "2026-10", "futuro"),
        ("2024-01", "2026-06", f"{MESES_MAX} meses"),
        ("2026/01", "2026-06", "YYYY-MM"),
        ("2026-13", "2026-06", "YYYY-MM"),
        ("2026-01", "agosto", "YYYY-MM"),
    ],
)
def test_periodo_invalido_e_400_com_a_frase(cenario, de, ate, trecho):
    with pytest.raises(HTTPException) as e:
        periodo_pedido(de, ate)
    assert e.value.status_code == 400
    assert trecho in e.value.detail


def test_vinte_e_quatro_meses_exatos_passam(cenario):
    assert periodo_pedido("2024-10", "2026-09") == ("2024-10", "2026-09")


# ── escopo, contrato e upstream ─────────────────────────────────────────────


async def test_de_depois_de_ate_nao_vai_ao_upstream(db, dono, usinas, cenario):
    minha, _ = usinas
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(minha.id, "2026-08", "2026-03", None, db, dono)
    assert e.value.status_code == 400
    # A prova: nenhuma ida ao meuPlano — nem para os contratos.
    assert cenario.pedidos == [] and cenario.contratos_pedidos == []


async def test_usina_alheia_e_404(db, dono, usinas, cenario):
    """404, não 403: confirmar que a usina existe já seria contar demais."""
    _, alheia = usinas
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(alheia.id, None, None, None, db, dono)
    assert e.value.status_code == 404
    assert cenario.pedidos == [] and cenario.contratos_pedidos == []


async def test_o_periodo_e_o_contrato_chegam_ao_upstream(db, dono, usinas, cenario):
    minha, _ = usinas
    await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", 77, db, dono)
    assert cenario.pedidos == [("json", minha.mp_usina_id, "2026-03", "2026-08", 77)]


async def test_sem_contrato_id_vale_o_consolidado_e_nao_o_primeiro_da_lista(db, dono, usinas, cenario):
    """A régua da aba Cronograma: o 78 vem primeiro na lista e só tem rascunho; o
    relatório sai do 77, que é o consolidado — e o cabeçalho diz qual foi."""
    minha, _ = usinas
    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)
    assert cenario.pedidos == [("json", minha.mp_usina_id, "2026-03", "2026-08", 77)]
    assert saida.contrato and saida.contrato.id == 77
    assert saida.contrato.vigente is True and saida.contrato.versao_cronograma == 2


async def test_contrato_de_outra_usina_e_404_antes_do_agregado(db, dono, usinas, cenario):
    """O id chega do cliente; a lista de contratos DESTA usina é a cerca."""
    minha, _ = usinas
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", 999, db, dono)
    assert e.value.status_code == 404
    assert "nesta usina" in e.value.detail
    assert cenario.pedidos == []


async def test_usina_sem_contrato_ainda_sai_com_as_ordens(db, dono, usinas, cenario):
    """Sem contrato não há cronograma — mas há OSs e pendências, e a frase explica o bloco
    que falta. O agregado é pedido sem `container_id` (o meuPlano não tem o que escolher)."""
    minha, _ = usinas
    cenario.contratos = []
    cenario.agregado = {**AGREGADO, "cronograma": None, "cronograma_motivo": "sem_contrato",
                        "cabecalho": {**AGREGADO["cabecalho"], "contrato": None}}
    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)
    assert cenario.pedidos == [("json", minha.mp_usina_id, "2026-03", "2026-08", None)]
    assert saida.contrato is None and saida.cronograma is None
    assert saida.aviso and "não tem contrato" in saida.aviso
    assert len(saida.ordens) == 1


async def test_404_do_upstream_passa_com_a_frase(db, dono, usinas, cenario):
    """Contrato válido aqui, mas o meuPlano diz que não: a frase dele é o que o cliente
    precisa ler — não um 502 genérico."""
    minha, _ = usinas
    cenario.erro = _erro_http(404, {"detail": "Contrato não encontrado nesta usina"})
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", 77, db, dono)
    assert e.value.status_code == 404
    assert "Contrato" in e.value.detail


async def test_timeout_do_upstream_e_504(db, dono, usinas, cenario):
    minha, _ = usinas
    cenario.erro = httpx.ReadTimeout("demorou")
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(minha.id, None, None, None, db, dono)
    assert e.value.status_code == 504


async def test_falha_ao_ler_os_contratos_nao_vira_404(db, dono, usinas, cenario):
    """A lista de contratos fora do ar é problema da ponte (502/504), não "usina sem
    contrato" — senão a tela diria que não há contrato quando o que há é o meuPlano caído."""
    minha, _ = usinas

    async def _cai(_usina_id):
        raise httpx.ReadTimeout("demorou")

    cenario.vc_contratos = _cai
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(minha.id, None, None, None, db, dono)
    assert e.value.status_code == 504
    assert cenario.pedidos == []


async def test_corpo_sem_forma_e_502(db, dono, usinas, cenario):
    minha, _ = usinas
    cenario.agregado = "isso não é um relatório"
    with pytest.raises(HTTPException) as e:
        await relatorio_de_manutencao(minha.id, None, None, None, db, dono)
    assert e.value.status_code == 502


# ── tradução ────────────────────────────────────────────────────────────────


async def test_o_relatorio_sai_no_vocabulario_do_portal(db, dono, usinas, cenario):
    minha, _ = usinas
    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)

    assert saida.usina == "Porto Ferreira" and saida.usina_id == minha.id
    assert saida.cliente == "Eldorado" and saida.executora == "Splendor"
    assert saida.periodo.de == "2026-03" and saida.periodo.ate == "2026-08"
    assert saida.contrato and saida.contrato.id == 77 and saida.contrato.numero == 1203
    assert saida.contrato.inicio == date(2026, 3, 1)
    assert saida.aviso is None

    # Contagens REPASSADAS, não recalculadas — e o nulo fica nulo.
    c = saida.cronograma
    assert c is not None
    assert (c.previstas, c.executadas, c.dispensadas, c.atrasadas, c.sem_ativo) == (10, 7, 1, 1, 1)
    assert c.previstas == c.executadas + c.dispensadas + c.atrasadas + c.no_prazo + c.sem_ativo
    assert c.pct_cumprido is None
    assert c.status == "CONSOLIDATED" and c.versao == 2
    assert [l.nome for l in c.linhas] == ["Termografia", "Limpeza do quadro"]
    assert c.linhas[1].dispensadas == 1 and c.linhas[1].sem_ativo == 1
    # As dispensas vêm do TOPO do agregado e caem dentro do bloco do cronograma.
    assert c.dispensas[0].motivo == "CFTV ainda não finalizado"
    assert c.dispensas[0].atividade == "Limpeza do quadro" and c.dispensas[0].mes == "2026-05"

    # OS APROVADA é "Concluída"/ok — o mesmo mapa da aba Ordens.
    assert len(saida.ordens) == 1
    os_ = saida.ordens[0]
    assert os_.situacao == "Concluída" and os_.tom == "ok" and os_.status == "APROVADA"
    assert os_.objetivo == "Preventiva agosto"  # `objetivo` nulo cai em `name`
    assert os_.itens is not None and len(os_.itens) == 2
    termo = next(t for t in os_.itens if t.nome == "Termografia")
    assert termo.parecer == "Aprovado" and termo.feita is True
    assert termo.equipamento == "Inversor 03"

    assert len(saida.em_curso) == 1 and saida.em_curso[0].situacao == "Em execução"
    assert saida.em_curso[0].itens == []

    assert (saida.pareceres.aprovados, saida.pareceres.com_ressalva,
            saida.pareceres.reprovados, saida.pareceres.sem_parecer) == (4, 1, 0, 2)

    assert saida.fotos == 41
    assert saida.gerado_em.year == 2026 and saida.gerado_em.month == 9


async def test_problemas_saem_agregados_e_sem_equipamento(db, dono, usinas, cenario):
    """O upstream mandou `equipamento` por OS; ele NÃO sai — é o nível que o dono não quer.
    E as quatro faixas saem sempre, mesmo as que o agregado não mencionou."""
    minha, _ = usinas
    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)

    p = saida.problemas
    assert p.total == 3
    assert [f.criticidade for f in p.por_criticidade] == ["urgente", "alto", "baixo", "nulo"]
    assert [f.tom for f in p.por_criticidade] == ["parado", "multiplos", "alerta", "semDados"]
    assert [f.total for f in p.por_criticidade] == [1, 2, 0, 0]
    assert p.por_os[0].urgentes == 1 and p.por_os[0].tom == "parado"
    assert "equipamento" not in ProblemasPorOsOut.model_fields
    assert "equipamento" not in p.por_os[0].model_dump()


async def test_pendencias_com_prazo_vencido_e_concluidas(db, dono, usinas, cenario):
    minha, _ = usinas
    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)

    aberta = saida.pendencias.abertas[0]
    assert aberta.numero == 8801 and aberta.tom == "parado" and aberta.situacao == "Prazo vencido"
    assert aberta.cobrada_pelo_cliente is True
    concluida = saida.pendencias.concluidas[0]
    # Concluída depois do prazo NÃO é alarme: já foi resolvida.
    assert concluida.situacao == "Concluída" and concluida.tom == "semDados"
    assert concluida.concluida_em == date(2026, 4, 20)  # de `concluida_em_aprox`
    assert concluida.cobrada_pelo_cliente is False


def test_sem_cronograma_consolidado_a_frase_e_a_da_aba_cronograma(usinas, monkeypatch):
    """Contrato só com rascunho: o bloco fica nulo e o aviso é EXATAMENTE o da aba
    Cronograma — o cliente que troca de aba lê a mesma explicação. As outras seções
    continuam saindo, e nada vira zero."""
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 4))
    minha, _ = usinas
    bruto = {**AGREGADO, "cronograma": None, "cronograma_motivo": "sem_cronograma_consolidado"}
    saida = traduzir(bruto, minha, ("2026-03", "2026-08"))
    assert saida.cronograma is None
    assert saida.aviso == NAO_PUBLICADO
    assert saida.ordens and saida.fotos == 41


def test_aviso_do_upstream_tem_precedencia_sobre_o_motivo(usinas, monkeypatch):
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 4))
    minha, _ = usinas
    bruto = {**AGREGADO, "cronograma": None, "cronograma_motivo": "sem_cronograma_consolidado",
             "aviso": "Frase que o meuPlano escreveu."}
    assert traduzir(bruto, minha, ("2026-03", "2026-08")).aviso == "Frase que o meuPlano escreveu."


def test_pct_cumprido_zero_de_verdade_continua_zero(usinas, monkeypatch):
    """O oposto do nulo: 0 % cumprido é resposta legítima e não pode virar '—'."""
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 4))
    minha, _ = usinas
    bruto = {**AGREGADO, "cronograma": {**AGREGADO["cronograma"], "pct_cumprido": 0.0}}
    saida = traduzir(bruto, minha, ("2026-03", "2026-08"))
    assert saida.cronograma is not None and saida.cronograma.pct_cumprido == 0.0


def test_agregado_vazio_nao_derruba_a_tradução(usinas, monkeypatch):
    """Um upstream que mandou só o cabeçalho ainda produz um relatório legível — com os
    blocos vazios, e não com uma exceção."""
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 4))
    minha, _ = usinas
    saida = traduzir({}, minha, ("2026-01", "2026-06"))
    assert saida.periodo.de == "2026-01" and saida.cronograma is None
    assert saida.ordens == [] and saida.problemas.total == 0
    assert saida.pendencias.abertas == [] and saida.contrato is None
    assert saida.gerado_em is not None and saida.aviso


def test_contagem_no_lugar_da_lista_de_pendencias_nao_quebra(usinas, monkeypatch):
    """`abertas_no_fim` é CONTAGEM no agregado real; sem a lista, sai vazio — nunca uma
    exceção por iterar um inteiro."""
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 4))
    minha, _ = usinas
    bruto = {**AGREGADO, "pendencias": {"abertas_no_fim": 3, "concluidas_no_periodo": 1}}
    saida = traduzir(bruto, minha, ("2026-03", "2026-08"))
    assert saida.pendencias.abertas == [] and saida.pendencias.concluidas == []


# ── PDF ─────────────────────────────────────────────────────────────────────


async def test_pdf_chega_inline_com_o_nome_do_periodo(db, dono, usinas, cenario):
    minha, _ = usinas
    resposta = await pdf_do_relatorio(minha.id, "2026-03", "2026-08", None, db, dono)
    assert resposta.media_type == "application/pdf"
    assert resposta.body.startswith(b"%PDF")
    disposicao = resposta.headers["content-disposition"]
    assert disposicao.startswith("inline") and "2026-03-2026-08" in disposicao
    # O MESMO contrato do JSON — tela e documento nunca divergem.
    assert cenario.pedidos == [("pdf", minha.mp_usina_id, "2026-03", "2026-08", 77)]


async def test_pdf_vazio_e_502_com_frase(db, dono, usinas, cenario):
    minha, _ = usinas
    cenario.pdf = b""
    with pytest.raises(HTTPException) as e:
        await pdf_do_relatorio(minha.id, None, None, None, db, dono)
    assert e.value.status_code == 502
    assert "vazio" in e.value.detail


async def test_pdf_de_usina_alheia_e_404(db, dono, usinas, cenario):
    _, alheia = usinas
    with pytest.raises(HTTPException) as e:
        await pdf_do_relatorio(alheia.id, None, None, None, db, dono)
    assert e.value.status_code == 404
    assert cenario.pedidos == []


async def test_pdf_com_periodo_invalido_nao_vai_ao_upstream(db, dono, usinas, cenario):
    minha, _ = usinas
    futuro = (date(2026, 9, 4) + timedelta(days=60)).strftime("%Y-%m")
    with pytest.raises(HTTPException) as e:
        await pdf_do_relatorio(minha.id, None, futuro, None, db, dono)
    assert e.value.status_code == 400
    assert cenario.pedidos == []


# ── pelo HTTP ───────────────────────────────────────────────────────────────


@pytest.fixture
def cliente_http(db):
    """Uma aplicação só com este router — o que se testa é a rota e o portão dela."""
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_sem_sessao_e_401_e_rota_irma_inexistente_e_404(cliente_http):
    """O par que prova o deploy: a rota nova recusa sem token, a inexistente não existe."""
    assert cliente_http.get("/api/v1/manutencao/relatorio?usina_id=1").status_code == 401
    assert cliente_http.get("/api/v1/manutencao/relatorio/pdf?usina_id=1").status_code == 401
    assert cliente_http.get("/api/v1/manutencao/relatoriox?usina_id=1").status_code == 404


def test_pelo_http_com_sessao_de_cliente(db, dono, usinas, cenario, cliente_http):
    minha, _ = usinas
    token, _ = criar_token(dono.id)

    r = cliente_http.get(
        f"/api/v1/manutencao/relatorio?usina_id={minha.id}&de=2026-03&ate=2026-08",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["usina_id"] == minha.id and corpo["contrato"]["id"] == 77
    assert corpo["cronograma"]["pct_cumprido"] is None
    assert corpo["ordens"][0]["situacao"] == "Concluída"
    assert corpo["pendencias"]["abertas"][0]["tom"] == "parado"

    r = cliente_http.get(
        f"/api/v1/manutencao/relatorio?usina_id={minha.id}&de=2026-08&ate=2026-03",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400 and "depois de" in r.json()["detail"]


# ── o recorte dos agregados ─────────────────────────────────────────────────
#
# O relatório se contradizia numa página só: exibia "Aprovado com ressalva" na OS EM CURSO
# e, logo abaixo, "COM RESSALVA 0" e "as fichas não registraram problema nenhum". Os dois
# números estavam certos — o agregado é das ordens ENCERRADAS —, mas ninguém dizia isso ao
# leitor. A frase vem pronta do BFF para que tela e PDF digam a MESMA coisa.


async def test_os_agregados_dizem_de_quantas_ordens_saem(db, dono, usinas, cenario):
    minha, _ = usinas
    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)

    for bloco in (saida.pareceres, saida.problemas):
        assert bloco.ordens_consideradas == 2
        assert bloco.ordens_em_curso_fora == 1
        assert bloco.recorte is not None
        assert "2 ordens encerradas no período" in bloco.recorte
        assert "1 ordem ainda em execução" in bloco.recorte


async def test_sem_ordem_em_curso_a_frase_nao_fala_de_execucao(db, dono, usinas, cenario):
    """Aviso que aparece sempre vira ruído: sem OS aberta, a ressalva não é dita."""
    minha, _ = usinas
    cenario.agregado = {
        **cenario.agregado,
        "pareceres": {"aprovados": 4, "com_ressalva": 0, "reprovados": 0, "sem_parecer": 0,
                      "ordens_consideradas": 3, "ordens_em_curso_fora": 0},
    }

    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)

    assert saida.pareceres.recorte == "Conta as fichas de 3 ordens encerradas no período."


async def test_upstream_antigo_sem_os_campos_nao_inventa_frase(db, dono, usinas, cenario):
    """Um meuPlano que ainda não manda o recorte não vira "0 ordens" na tela."""
    minha, _ = usinas
    cenario.agregado = {
        **cenario.agregado,
        "pareceres": {"aprovados": 1, "com_ressalva": 0, "reprovados": 0, "sem_parecer": 0},
    }

    saida = await relatorio_de_manutencao(minha.id, "2026-03", "2026-08", None, db, dono)

    assert saida.pareceres.recorte is None
    assert saida.pareceres.aprovados == 1


# ── o denominador tem escopo, e ele é dito ──────────────────────────────────


async def test_a_taxa_de_cumprimento_diz_de_quais_meses_saiu(db, dono, usinas, cenario):
    """O portal dava DUAS respostas para "está sendo feito?": a aba Cronograma dizia
    "13 de 270 previstas" e o relatório estampava "cumprido 41,9%" com 31 previstas, sob o
    rótulo "Outubro de 2025 a Setembro de 2026" — período que começa 9 meses ANTES da
    vigência do contrato. Os dois números estavam certos; faltava a frase que reconcilia."""
    cenario.agregado = {
        **AGREGADO,
        "cronograma": {
            **AGREGADO["cronograma"],
            "meses_do_cronograma": ["2026-07", "2026-08"],
            "meses_fora_do_cronograma": ["2025-10", "2025-11", "2025-12"],
            "previsto_no_contrato": 270,
        },
    }
    saida = await relatorio_de_manutencao(
        usina_id=usinas[0].id, de="2025-10", ate="2026-08", db=db, usuario=dono
    )
    recorte = saida.cronograma.recorte
    assert recorte is not None
    assert "2 meses" in recorte and "jul/2026 a ago/2026" in recorte
    assert "3 ficaram de fora" in recorte
    assert "270" in recorte                       # o total do contrato, para conferir
    assert saida.cronograma.previstas_no_contrato == 270


async def test_periodo_dentro_do_contrato_nao_ganha_frase(db, dono, usinas, cenario):
    """Aviso que sempre aparece ninguém lê: quando o período cabe na vigência não há
    diferença a explicar."""
    cenario.agregado = {
        **AGREGADO,
        "cronograma": {**AGREGADO["cronograma"],
                       "meses_do_cronograma": ["2026-07", "2026-08"],
                       "meses_fora_do_cronograma": [], "previsto_no_contrato": 270},
    }
    saida = await relatorio_de_manutencao(
        usina_id=usinas[0].id, de="2026-07", ate="2026-08", db=db, usuario=dono
    )
    assert saida.cronograma.recorte is None


async def test_periodo_todo_fora_da_vigencia_e_dito_sem_rodeio(db, dono, usinas, cenario):
    cenario.agregado = {
        **AGREGADO,
        "cronograma": {**AGREGADO["cronograma"], "meses_do_cronograma": [],
                       "meses_fora_do_cronograma": ["2025-10", "2025-11"],
                       "previsto_no_contrato": 270},
    }
    saida = await relatorio_de_manutencao(
        usina_id=usinas[0].id, de="2025-10", ate="2025-11", db=db, usuario=dono
    )
    assert "Nenhum mês do período" in (saida.cronograma.recorte or "")


async def test_o_relatorio_le_o_mesmo_vocabulario_da_aba_ordens(db, dono, usinas, cenario):
    """A OS 969 saía "OS 969 · SERVICOS_ADICIONAIS" no relatório e "Instalação da
    Comunicação · Serviços adicionais" na lista — a mesma ordem, no mesmo portal."""
    cenario.agregado = {
        **AGREGADO,
        "ordens": [{**AGREGADO["ordens"][0], "id": 969, "name": None, "objetivo": None,
                    "container_title": "Instalação da Comunicação", "container_numero": 665,
                    "classification": "SERVICOS_ADICIONAIS", "tarefas": []}],
        "cronograma": {**AGREGADO["cronograma"], "linhas": [
            {**AGREGADO["cronograma"]["linhas"][0], "categoria": "INSPECAO"},
        ]},
    }
    saida = await relatorio_de_manutencao(
        usina_id=usinas[0].id, de="2026-03", ate="2026-08", db=db, usuario=dono
    )
    ordem = saida.ordens[0]
    assert ordem.objetivo == "Instalação da Comunicação"
    assert ordem.classificacao == "Serviços adicionais"
    assert ordem.contrato_numero == 665           # o contrato, com o nome certo
    assert ordem.id == 969                        # e a OS pelo id, que é o número dela
    # A categoria da linha também sai traduzida — "INSPECAO" era o que ia para a tela.
    assert saida.cronograma.linhas[0].categoria == "Inspeção"
