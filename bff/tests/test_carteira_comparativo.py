"""`GET /api/v1/carteira/comparativo` — comparar usinas é onde o número mente com mais
facilidade, porque a comparação parece objetiva mesmo quando os dois lados não são o mesmo.

Os defeitos que estes testes guardam, um por um:

* **custo** — o comparativo fazendo mais de uma ida ao `generation/range` por usina. Foi
  esse tipo de multiplicação que fez a Visão geral levar 22 s com ~64 chamadas.
* **duas respostas para a mesma pergunta** — a energia daqui divergindo da de
  `/api/v1/resumo` (que passa por `desempenho_da_usina`). Esta semana uma tela disse
  −64,3 % e outra +101,7 % da mesma usina; é a lição mais cara do projeto.
* **zero fabricado** — usina com o upstream em erro aparecendo com 0 no fim do ranking, que
  se lê como "essa é a pior", em vez de sair da lista com o motivo escrito.
* **escopo** — usina de outro dono entrando na comparação. Aqui não há nem parâmetro de
  usina: o teste prova que passar um id qualquer na query não muda nada.
* **capacidade diferente** — o ranking padrão sendo energia absoluta, que só diz qual é a
  maior usina, e não qual rende melhor.
* **entrada tardia** — a usina que começou a medir em junho puxando o ano inteiro para
  baixo, sem a tela dizer que a janela encolheu e por causa de quem.
* **"13 de 270"** — dividir por um ano que ainda não aconteceu. O denominador é
  `feitas + dispensadas + atrasadas`, e ele viaja impresso ao lado do percentual.
* **dispensa virando feito** — a distinção que o meuPlano recusou apagar.

As funções irmãs (cronograma, ordens, pendências, e os auxiliares de `plants`) rodam DE
VERDADE; o que é fantasia são os dois upstreams.
"""

from datetime import date

import pytest
from fastapi import HTTPException

from app.api.v1 import paradas as modulo_paradas
from app.api.v1.carteira import _contar_cronograma, comparativo
from app.api.v1.manutencao import CelulaOut, CronogramaOut, LinhaCronogramaOut
from app.api.v1.resumo import resumo
from app.services import carteira as regua_modulo
from app.core.security import criar_token, gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

#: Agosto de 2026 — o mês fechado que o cliente olha em setembro. É a MESMA janela que
#: `/plants/{id}/desempenho?recorte=mes` monta, de propósito: é o que faz o comparativo
#: cair no cache já quente do upstream em vez de provocar um `miss` por abertura de tela.
DE = "2026-08-01"
ATE = "2026-08-31"
REFERENCIA = date(2026, 8, 14)


@pytest.fixture(autouse=True)
def _primaria_de_pe():
    """A memória de "fonte primária fora" é global ao processo (usada por `paradas`, que o
    `/resumo` deste arquivo exercita); um teste não herda a queda que outro provocou."""
    modulo_paradas.esquecer_indisponibilidade()
    yield
    modulo_paradas.esquecer_indisponibilidade()


@pytest.fixture
def dono(db):
    u = User(
        apelido="diretor",
        email="diretor@exemplo.com.br",
        nome="Diretor",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def alheio(db):
    """Outro cliente, com a própria usina. Nada dele pode aparecer na comparação do dono."""
    u = User(
        apelido="outro",
        email="outro@exemplo.com.br",
        nome="Outro",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


def _conceder(db, usuario, usina):
    db.add(UserPlantAccess(user_id=usuario.id, plant_link_id=usina.id))
    db.commit()


# ── os upstreams como fantasia ──────────────────────────────────────────────


def _range(
    *,
    energia: float,
    capacidade: float,
    meses: dict[str, float],
    pr: float | None = 0.81,
    poa: float = 150.0,
):
    """Um `generation/range` com a forma real do mw-api (`RangeGenerationReport`)."""
    return {
        "total_generation_kwh": energia,
        "total_capacity_kwp": capacidade,
        "productivity": round(energia / capacidade, 4) if capacidade else 0.0,
        "performance_ratio": pr if pr is not None else 0.0,
        "irradiation": {"hpoa": poa, "hghi": poa * 0.9},
        "days_with_data": 31,
        "availability_real_pct": 98.2,
        "availability_contratual_pct": 99.1,
        "pending_classification_count": 2,
        "summary": {"total_lost_kwh": 50.0},
        "monthly_summaries": [
            {"month": m, "generation_kwh": v} for m, v in meses.items()
        ],
    }


class MeuWattFalso:
    """Conta cada ida ao `generation/range` — é o contador do aceite de custo.

    Porto Ferreira é a usina GRANDE (mais energia absoluta) e Ribeirão Bonito é a EFICIENTE
    (mais kWh/kWp). É esse par que separa "qual gera mais" de "qual rende mais": comparar
    por energia coroaria a errada.
    """

    def __init__(self):
        self.chamadas_range: list[str] = []
        self.fora_para: set[str] = set()
        #: Meses medidos por usina, para o teste da janela comum.
        self.meses: dict[str, dict[str, float]] = {}

    async def geracao_periodo(self, slug, inicio, fim):
        self.chamadas_range.append(slug)
        if slug in self.fora_para:
            raise RuntimeError("meuWatt caiu")
        if slug in self.meses:
            meses = self.meses[slug]
            return _range(
                energia=round(sum(meses.values()), 2),
                capacidade=1000.0 if slug == "porto-ferreira" else 500.0,
                meses=meses,
            )
        if slug == "porto-ferreira":
            # 9.500 kWh sobre 1.000 kWp = 9,5 kWh/kWp.
            return _range(energia=9500.0, capacidade=1000.0, meses={"2026-08": 9500.0})
        # 6.000 kWh sobre 500 kWp = 12,0 kWh/kWp: menos energia, mais produtividade.
        return _range(
            energia=6000.0, capacidade=500.0, meses={"2026-08": 6000.0}, pr=None
        )

    async def pvsyst(self, slug, inicio, fim):
        """Só o `/resumo` a consulta (para a meta do projeto). O comparativo NÃO — meta não
        é pergunta de comparação, e cada ida a mais é um `miss` de cache por usina."""
        if slug != "porto-ferreira":
            return {"rows": [], "years": [], "count": 0}
        return {
            "rows": [
                {"date": f"2026-08-{d:02d}", "e_grid": 300.0, "e_array": 320.0, "globinc": 5.0}
                for d in range(1, 32)
            ],
            "years": [2026],
            "count": 31,
        }

    async def pvsyst_manual(self, slug, ano):
        return {"year": ano, "rows": []}

    async def paradas(self, slug, inicio, fim, timeout=None):
        return {"plant": slug, "total": 0, "breakdowns": []}


class MeuPlanoFalso:
    """Porto Ferreira (mp 1) tem cronograma consolidado; Ribeirão Bonito (mp 2) só tem
    rascunho — o caso "não publicado", que precisa sair com travessão e motivo, e FORA dos
    totais, nunca como "0 atrasadas" (que se lê como "está tudo em dia")."""

    def __init__(self):
        self.sem_consolidado: set[int] = {2}
        self.fora_para: set[int] = set()

    def _garante(self, usina_id):
        if usina_id in self.fora_para:
            raise RuntimeError("meuPlano não respondeu")

    async def ordens_servico(self, usina_id, status=None):
        self._garante(usina_id)
        return [
            {"id": 1, "plant_id": usina_id, "status": "EM_EXECUCAO", "name": "Preventiva agosto"},
            {"id": 2, "plant_id": usina_id, "status": "APROVADA", "name": "Corretiva do relé",
             "closed_at": "2026-08-03T18:00:00Z"},
        ]

    async def vc_contratos(self, usina_id):
        self._garante(usina_id)
        return [{"id": 20 + usina_id, "numero": 200 + usina_id, "title": "O&M 2026",
                 "start_date": "2026-03-01", "end_date": "2027-02-28", "vigente": True,
                 "versao_consolidada": 2}]

    async def vc_cronograma(self, usina_id, container_id):
        self._garante(usina_id)
        if usina_id in self.sem_consolidado:
            import httpx

            pedido = httpx.Request("GET", "http://falso/cronograma")
            raise httpx.HTTPStatusError(
                "sem consolidado", request=pedido,
                response=httpx.Response(404, request=pedido),
            )
        # Âncora em março: o mês 6 do contrato é agosto. A janela de agosto vê só ele.
        meses = [f"2026-{m:02d}" for m in range(3, 13)] + ["2027-01", "2027-02"]
        return {
            "status": "CONSOLIDATED", "version": 2, "month_labels": meses,
            "rows": [
                {"plan_item_id": 1, "name": "Termografia", "periodicity_value": 1,
                 "periodicity_unit": "mes", "expected_per_year": 12,
                 "months": {str(i): 1 for i in range(1, 13)},
                 # Agosto (mês 6) = vermelho: uma atrasada dentro da janela.
                 "cell_status": {"1": "verde", "2": "verde", "3": "verde_ressalva",
                                 "4": "vermelho", "5": "verde", "6": "vermelho",
                                 "7": "azul", "8": "azul"}},
                {"plan_item_id": 2, "name": "Limpeza", "periodicity_value": 6,
                 "periodicity_unit": "mes", "expected_per_year": 2,
                 "months": {"1": 1, "6": 1},
                 # Agosto (mês 6) = verde_ressalva: dispensa, que NUNCA vira feito.
                 "cell_status": {"1": "verde", "6": "verde_ressalva"}},
                # Três ocorrências previstas para agosto e ainda NO PRAZO (`azul`): é o
                # "270" do "13 de 270". Elas contam no previsto e NÃO no denominador.
                {"plan_item_id": 3, "name": "Inspeção termográfica", "periodicity_value": 1,
                 "periodicity_unit": "mes", "expected_per_year": 12,
                 "months": {"6": 3}, "cell_status": {"6": "azul"}},
            ],
        }

    async def vc_pendencias(self, usina_id):
        self._garante(usina_id)
        return [
            {"id": 1, "numero": 1001, "usina_id": usina_id, "title": "Alambrado caído",
             "status": "ABERTO", "shareable": True, "end_date": "2026-08-01",
             "criticidade": "critica", "extra": {"cobrada_pelo_cliente": True},
             "created_at": "2026-07-01T12:00:00Z"},
            {"id": 2, "numero": 1002, "usina_id": usina_id, "title": "Limpeza dos módulos",
             "status": "EM_ANDAMENTO", "shareable": True, "extra": {},
             "created_at": "2026-07-10T12:00:00Z"},
            {"id": 3, "numero": 1003, "usina_id": usina_id, "title": "Troca de fusível",
             "status": "CONCLUIDO", "shareable": True, "extra": {},
             "created_at": "2026-06-01T12:00:00Z"},
            # Interna: nunca chega ao cliente, em bloco nenhum.
            {"id": 4, "numero": 1004, "usina_id": usina_id, "title": "Interna",
             "status": "ABERTO", "shareable": False, "extra": {},
             "created_at": "2026-07-01T12:00:00Z"},
        ]


async def _agora_falso(cliente, link, dia):
    """O tempo real de `listar_usinas` (usado só pelo `/resumo` da comparação)."""
    return {"potencia_kw": 300.0, "capacidade_kwp": 1000.0, "energia_hoje_kwh": 1200.0}


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

    monkeypatch.setattr("app.services.integracoes.cliente_meuwatt", _mw)
    monkeypatch.setattr("app.services.integracoes.cliente_meuplano", _mp)
    monkeypatch.setattr("app.api.v1.plants._dados_meuwatt", _agora_falso)
    # `hoje` é lido em três módulos por caminhos diferentes; travá-lo em 31/08/2026 é o que
    # deixa a janela de agosto ser um mês FECHADO (sem o `min(fim, hoje)` cortar o mês).
    for alvo in ("app.api.v1.carteira.hoje_na_usina", "app.api.v1.plants.hoje_na_usina"):
        monkeypatch.setattr(alvo, lambda: date(2026, 8, 31))
    return {"porto": porto, "ribeirao": ribeirao, "meuwatt": meuwatt, "meuplano": meuplano}


def _usina(bloco, nome):
    return next(u for u in bloco.usinas if u.nome == nome)


def _ranking(bloco, chave):
    return next(r for r in bloco.rankings if r.chave == chave)


# ── custo: uma ida por usina ────────────────────────────────────────────────


async def test_energia_faz_exatamente_uma_ida_ao_range_por_usina(db, dono, usinas, cenario):
    """O defeito guardado: o comparativo multiplicando idas ao upstream.

    Sete usinas → sete chamadas de `generation/range`, nem uma a mais. O `range` já traz
    energia, capacidade, produtividade, PR, as duas disponibilidades, perdas e irradiação;
    qualquer segunda ida por usina é conta paga duas vezes — foi assim que a Visão geral
    chegou a 22 s. E `pvsyst` não é chamado: meta de projeto não é pergunta de comparação.
    """
    extras = [
        PlantLink(mw_plant_slug=f"usina-{i}", mp_usina_id=10 + i, nome=f"Usina {i}")
        for i in range(3, 8)
    ]
    db.add_all(extras)
    db.commit()
    for u in extras:
        _conceder(db, dono, u)

    meuwatt = cenario["meuwatt"]
    meuwatt.chamadas_range.clear()
    chamadas_pvsyst: list[str] = []
    original_pvsyst = meuwatt.pvsyst

    async def _contando(slug, inicio, fim):
        chamadas_pvsyst.append(slug)
        return await original_pvsyst(slug, inicio, fim)

    meuwatt.pvsyst = _contando

    saida = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)

    assert saida.usinas_no_escopo == 7
    assert len(saida.energia.usinas) == 7                    # 1 linha por usina do escopo
    assert len(meuwatt.chamadas_range) == 7                  # e 1 chamada por usina
    assert sorted(meuwatt.chamadas_range) == sorted(
        {u.mw_plant_slug for u in [cenario["porto"], cenario["ribeirao"], *extras]}
    )
    assert chamadas_pvsyst == []


# ── a mesma pergunta, o mesmo número ────────────────────────────────────────


async def test_energia_bate_digito_a_digito_com_o_resumo(db, dono, cenario):
    """O defeito guardado: dois números para a mesma pergunta no mesmo portal.

    A Visão geral soma a energia do mês passando por `desempenho_da_usina`; o comparativo
    lê o `range` uma vez e deriva com os MESMOS auxiliares de `plants.py`. Se algum dia
    alguém trocar a régua num dos dois lados, este teste é quem acusa — foi a divergência
    de −64,3 % contra +101,7 % que ensinou a colocar a guarda aqui e não na revisão.
    """
    comp = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)
    vis = await resumo(referencia=REFERENCIA.isoformat(), blocos="energia", db=db, usuario=dono)

    por_nome = {u.nome: u.energia_mes_kwh for u in vis.usinas}
    for linha in comp.energia.usinas:
        assert linha.energia_kwh == por_nome[linha.nome], linha.nome

    assert comp.energia.totais.energia_kwh == vis.energia_mes_kwh
    assert comp.energia.totais.energia_kwh == 15500.0


# ── comparar usinas desiguais ───────────────────────────────────────────────


async def test_o_ranking_padrao_e_produtividade_e_a_energia_e_outra_pergunta(db, dono, cenario):
    """O defeito guardado: coroar a usina MAIOR como a que "rende mais".

    Porto Ferreira gera 9.500 kWh (mais energia); Ribeirão Bonito gera 6.000 kWh em metade
    da capacidade, e rende 12,0 kWh/kWp contra 9,5. Os dois rankings existem e dizem, cada
    um, a que pergunta respondem — porque as duas perguntas são legítimas e a resposta é
    diferente.
    """
    saida = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)

    produtividade = _ranking(saida.energia, "produtividade")
    assert [i.usina for i in produtividade.itens] == ["Ribeirão Bonito", "Porto Ferreira"]
    assert [i.valor for i in produtividade.itens] == [12.0, 9.5]
    assert produtividade.unidade == "kWh/kWp"
    # A tela abre pela produtividade, não pela energia: abrir por energia entregaria todo
    # dia o mesmo pódio — o das usinas maiores — e a pergunta "qual rende melhor" nunca
    # chegaria a ser feita. E o texto é o da régua, escrito num lugar só.
    assert saida.energia.rankings[0].chave == regua_modulo.ORDENACAO_PADRAO
    assert produtividade.pergunta == regua_modulo.PERGUNTAS["produtividade"].pergunta
    assert produtividade.nota and "irradiação" in produtividade.nota

    energia = _ranking(saida.energia, "energia")
    assert [i.usina for i in energia.itens] == ["Porto Ferreira", "Ribeirão Bonito"]
    assert energia.pergunta != produtividade.pergunta

    # Contexto obrigatório: "rende melhor" ainda contém "teve mais sol".
    assert _usina(saida.energia, "Ribeirão Bonito").irradiacao_hpoa == 150.0
    # Σ comparável ÷ Σ capacidade — não a média das produtividades, que ignoraria o porte.
    assert saida.energia.totais.produtividade_kwh_kwp == round(15500.0 / 1500.0, 2)
    assert saida.energia.totais.usinas_no_total == 2


async def test_sem_pr_sai_do_ranking_com_motivo_em_vez_de_virar_zero(db, dono, cenario):
    """O defeito guardado: a usina sem POA medida aparecendo com PR 0 % no fim da lista.

    Um zero fabricado num ranking é a acusação mais barata que uma tela pode fazer, e a
    mais difícil de o cliente desconfiar — parece um número. Ela sai da lista e o motivo
    fica escrito ao lado.
    """
    saida = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)

    assert _usina(saida.energia, "Ribeirão Bonito").pr_pct is None
    pr = _ranking(saida.energia, "pr")
    assert [i.usina for i in pr.itens] == ["Porto Ferreira"]
    assert any("Ribeirão Bonito" in f for f in pr.fora)
    assert any("PR" in f for f in pr.fora)


async def test_usina_com_upstream_em_erro_sai_com_aviso_e_fora_dos_rankings(db, dono, cenario):
    """O caso do aceite: a usina cujo monitoramento caiu não aparece com zero em lugar
    nenhum — nem em ranking, nem em total —, mas continua na LISTA com o motivo. Sumir
    também seria mentir: o cliente contaria as linhas e acharia que perdeu uma usina."""
    cenario["meuwatt"].fora_para = {"ribeirao-bonito"}
    saida = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)

    caida = _usina(saida.energia, "Ribeirão Bonito")
    assert caida.energia_kwh is None
    assert caida.produtividade_kwh_kwp is None
    assert caida.motivo and "meuWatt caiu" in caida.motivo
    for chave in ("produtividade", "energia", "pr"):
        rk = _ranking(saida.energia, chave)
        assert "Ribeirão Bonito" not in [i.usina for i in rk.itens], chave
        assert any("Ribeirão Bonito" in f for f in rk.fora), chave

    assert saida.energia.totais.energia_kwh == 9500.0
    assert saida.energia.totais.usinas_no_total == 1


async def test_janela_comum_encolhe_e_nomeia_quem_encolheu(db, dono, cenario):
    """O defeito guardado: comparar o ano inteiro de uma usina com quatro meses de outra.

    Ribeirão Bonito só passa a medir em junho. A comparação passa a valer sobre jun–ago, a
    tela DIZ isso e NOMEIA quem encolheu — sem o nome, o cliente lê "jun a ago" num pedido
    de seis meses e não tem como saber por quê. Não há coluna de comissionamento no
    meuWatt: a entrada tardia é derivada do dado.
    """
    cenario["meuwatt"].meses = {
        "porto-ferreira": {f"2026-{m:02d}": 1000.0 * m for m in range(3, 9)},
        "ribeirao-bonito": {f"2026-{m:02d}": 500.0 * m for m in range(6, 9)},
    }
    saida = await comparativo(de="2026-03-01", ate=ATE, blocos="energia", db=db, usuario=dono)

    assert saida.janela.meses == [f"2026-{m:02d}" for m in range(3, 9)]
    assert saida.janela.meses_comuns == ["2026-06", "2026-07", "2026-08"]
    assert saida.janela.completa is False
    assert saida.janela.encolhida_por == ["Ribeirão Bonito"]
    assert saida.janela.comparaveis == 2
    assert "Ribeirão Bonito" in (saida.janela.nota or "")
    assert "3 dos 6 meses" in (saida.janela.nota or "")
    assert saida.janela.rotulo == "jun a ago de 2026"

    porto = _usina(saida.energia, "Porto Ferreira")
    # O total do período pedido continua sendo o total (a mesma resposta de /desempenho)…
    assert porto.energia_kwh == sum(1000.0 * m for m in range(3, 9))
    # …e o que entra na comparação é só a janela comum.
    assert porto.energia_comparavel_kwh == 6000.0 + 7000.0 + 8000.0
    assert porto.produtividade_kwh_kwp == round(21000.0 / 1000.0, 2)

    ribeirao = _usina(saida.energia, "Ribeirão Bonito")
    assert ribeirao.energia_comparavel_kwh == 3000.0 + 3500.0 + 4000.0
    # Igualada a janela, as duas rendem 21,0 kWh/kWp — 21.000/1.000 e 10.500/500. Sem o
    # recorte, Porto Ferreira levaria 39,0 contra 21,0 por ter medido três meses a mais:
    # o pódio seria de quem está ligada há mais tempo, não de quem rende melhor.
    assert ribeirao.produtividade_kwh_kwp == round(10500.0 / 500.0, 2)
    assert porto.produtividade_kwh_kwp == ribeirao.produtividade_kwh_kwp
    # E a energia absoluta continua respondendo à outra pergunta — "qual é a maior".
    assert _ranking(saida.energia, "energia").itens[0].usina == "Porto Ferreira"


# ── manutenção ──────────────────────────────────────────────────────────────


async def test_denominador_impresso_e_dispensa_nao_vira_feito(db, dono, cenario):
    """Os dois defeitos mais caros da manutenção, num teste só.

    (1) "13 de 270": dividir por um ano que ainda não aconteceu. O denominador é
    `feitas + dispensadas + atrasadas` — `azul` (futuro) fica fora — e ele viaja IMPRESSO
    ao lado do percentual, para 41,9 % nunca aparecer sozinho.
    (2) A dispensa nunca funde com o feito: em agosto há uma atrasada (Termografia) e uma
    dispensada (Limpeza), então é 0 de 2, e não 1 de 2.
    """
    saida = await comparativo(de=DE, ate=ATE, blocos="manutencao", db=db, usuario=dono)

    porto = _usina(saida.manutencao, "Porto Ferreira")
    assert porto.feitas == 0
    assert porto.dispensadas == 1
    assert porto.atrasadas == 1
    assert porto.denominador == 2
    assert porto.cumprimento_pct == 0.0
    # O previsto do mês é 5 — mas o denominador é 2. As três ocorrências ainda no prazo
    # contam no combinado e NÃO na cobrança: no denominador, elas fariam o percentual
    # despencar sozinho todo dia 1º, sem ninguém ter deixado de trabalhar.
    assert porto.previsto == 5

    # O denominador NUNCA viaja sozinho: sai impresso ao lado do percentual, na linha e
    # no total, montado pela régua — a tela não redige "13 de 31".
    assert porto.cumprimento_rotulo == "0 de 2"
    # E o que está no prazo é DECLARADO fora da conta, senão "0 %" pareceria abandono.
    assert porto.fora_da_conta and "no prazo" in porto.fora_da_conta
    assert saida.manutencao.totais.cumprimento_rotulo == "0 de 2"

    cumprimento = _ranking(saida.manutencao, "cumprimento")
    item = next(i for i in cumprimento.itens if i.usina == "Porto Ferreira")
    assert item.denominador == 2          # o "de N" nunca sai sem o percentual
    assert cumprimento.ordem == "asc"     # pior primeiro


async def test_sem_cronograma_publicado_fica_fora_dos_totais_com_o_motivo(db, dono, cenario):
    """O defeito guardado: a usina sem cronograma consolidado aparecendo com "0 atrasadas",
    que se lê como "está tudo em dia" — a leitura mais errada possível de "não combinamos
    nada ainda". Ela sai com travessão, com o motivo escrito, e FORA dos totais — cujo
    cabeçalho diz de quantas usinas ele fala."""
    saida = await comparativo(de=DE, ate=ATE, blocos="manutencao", db=db, usuario=dono)

    ribeirao = _usina(saida.manutencao, "Ribeirão Bonito")
    assert ribeirao.atrasadas is None
    assert ribeirao.denominador is None
    assert ribeirao.cumprimento_pct is None
    assert ribeirao.motivo

    assert saida.manutencao.totais.usinas_no_total == 1
    assert saida.manutencao.totais.atrasadas == 1
    assert "Ribeirão Bonito" not in [
        i.usina for i in _ranking(saida.manutencao, "atraso").itens
    ]
    # …mas as pendências dela responderam, e continuam contando.
    assert ribeirao.pendencias_abertas == 2
    assert ribeirao.pendencias_criticas == 1
    assert saida.manutencao.totais.pendencias_abertas == 4


async def test_ranking_de_manutencao_e_por_atrasadas_absolutas(db, dono, cenario):
    """O ranking padrão da manutenção é o ABSOLUTO de atrasadas: o percentual sozinho
    premia o contrato pequeno, e uma usina com 2 de 4 atrasadas não é pior do que uma com
    30 de 300. O texto vem de `services.carteira.PERGUNTAS`, não daqui — se cada tela
    redigir o seu, "atrasada" vira "vencida" numa e "pendente" noutra."""
    saida = await comparativo(de=DE, ate=ATE, blocos="manutencao", db=db, usuario=dono)

    atraso = _ranking(saida.manutencao, "atraso")
    assert saida.manutencao.rankings[0].chave == "atraso"      # é o primeiro da tela
    assert atraso.pergunta == regua_modulo.PERGUNTAS["atraso"].pergunta
    assert atraso.nota == regua_modulo.PERGUNTAS["atraso"].nota
    assert atraso.ordem == "asc"        # mais atraso é PIOR: a régua inverte a leitura
    assert atraso.itens[0].usina == "Porto Ferreira"
    assert atraso.itens[0].valor == 1.0


async def test_meuplano_fora_do_ar_nao_zera_nada(db, dono, cenario):
    """Mesma regra do `/resumo`: upstream caído vira nulo com aviso, nunca zero."""
    cenario["meuplano"].fora_para = {2}
    saida = await comparativo(de=DE, ate=ATE, blocos="manutencao", db=db, usuario=dono)

    ribeirao = _usina(saida.manutencao, "Ribeirão Bonito")
    assert ribeirao.atrasadas is None
    assert ribeirao.pendencias_abertas is None
    assert ribeirao.os_em_andamento is None
    assert ribeirao.motivo
    assert _usina(saida.manutencao, "Porto Ferreira").os_em_andamento == 1


# ── blocos e escopo ─────────────────────────────────────────────────────────


async def test_sem_blocos_os_dois_vem(db, dono, cenario):
    saida = await comparativo(de=DE, ate=ATE, db=db, usuario=dono)
    assert saida.energia is not None
    assert saida.manutencao is not None
    assert saida.energia.usinas and saida.manutencao.usinas


async def test_bloco_de_energia_nao_toca_no_meuplano(db, dono, cenario):
    """A família de Geração não espera as cinco idas por usina que a manutenção custa —
    é a mesma razão das ondas do `/resumo`."""
    chamadas: list[int] = []
    meuplano = cenario["meuplano"]
    original = meuplano.ordens_servico

    async def _contando(usina_id, status=None):
        chamadas.append(usina_id)
        return await original(usina_id, status)

    meuplano.ordens_servico = _contando

    saida = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)
    assert chamadas == []
    assert saida.manutencao is None


async def test_bloco_desconhecido_recusa_com_a_frase(db, dono, cenario):
    with pytest.raises(HTTPException) as erro:
        await comparativo(de=DE, ate=ATE, blocos="financeiro", db=db, usuario=dono)
    assert erro.value.status_code == 400
    assert "financeiro" in erro.value.detail


async def test_usina_de_outro_dono_nunca_entra_nem_por_id_na_query(
    db, dono, alheio, usinas, cenario
):
    """O defeito guardado: um id vindo pela rede acrescentando usina alheia à comparação.

    A rota NÃO TEM parâmetro de usina — o conjunto é sempre `usinas_do_usuario`. O teste
    passa o id da usina alheia como query solta e prova que ela não aparece em lista, total
    nem ranking; e que nem o NOME dela vaza, que já seria informação demais.
    """
    alheia = PlantLink(mw_plant_slug="usina-secreta", mp_usina_id=99, nome="Usina Secreta")
    db.add(alheia)
    db.commit()
    _conceder(db, alheio, alheia)

    saida = await comparativo(de=DE, ate=ATE, db=db, usuario=dono)

    corpo = saida.model_dump_json()
    assert "Usina Secreta" not in corpo
    assert "usina-secreta" not in corpo
    assert {u.nome for u in saida.energia.usinas} == {"Porto Ferreira", "Ribeirão Bonito"}
    assert saida.usinas_no_escopo == 2
    assert "usina-secreta" not in cenario["meuwatt"].chamadas_range


async def test_de_futura_e_400_e_ate_futura_e_travada_em_hoje(db, dono, cenario):
    """Pedir "o mês em curso" é legítimo o mês inteiro — `ate` no futuro trava em hoje e a
    tela é avisada. Já `de` no futuro não tem nada a comparar, e é recusado."""
    with pytest.raises(HTTPException) as erro:
        await comparativo(de="2099-01-01", db=db, usuario=dono)
    assert erro.value.status_code == 400

    saida = await comparativo(de=DE, ate="2026-09-30", blocos="energia", db=db, usuario=dono)
    assert saida.janela.ate == "2026-08-31"
    assert saida.janela.truncada_em_hoje is True

    with pytest.raises(HTTPException) as erro:
        await comparativo(de=ATE, ate=DE, db=db, usuario=dono)
    assert erro.value.status_code == 400


async def test_sem_usina_concedida_responde_vazio_com_aviso(db, dono, usinas, cenario, monkeypatch):
    outro = User(apelido="novato", email="novato@x.com", nome="Novato",
                 perfil=Perfil.CLIENTE, senha_hash=gerar_hash_senha("x-1234"))
    db.add(outro)
    db.commit()

    saida = await comparativo(de=DE, ate=ATE, db=db, usuario=outro)
    assert saida.usinas_no_escopo == 0
    assert saida.energia.usinas == []
    assert saida.manutencao.usinas == []
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
    assert _contar_cronograma(_cronograma(None), {"2026-08"}) is None


def test_cronograma_conta_so_os_meses_da_janela():
    """A âncora do contrato é março; a janela pedida é maio–julho. Nem os meses de antes
    nem os de depois entram — é esse recorte que impede o denominador de virar o ano."""
    cro = _cronograma("CONSOLIDATED", "verde", "verde", "verde_ressalva", "vermelho",
                      "verde", "azul", "verde")
    assert _contar_cronograma(cro, {"2026-05", "2026-06", "2026-07"}) == {
        "previsto": 3, "feitas": 1, "dispensadas": 1, "atrasadas": 1, "no_prazo": 0
    }
    # `azul` (agosto, mês 6) é CONTADO — para ser declarado fora da conta, nunca somado.
    assert _contar_cronograma(cro, {"2026-08"})["no_prazo"] == 1
    assert _contar_cronograma(cro, {"2026-08"})["feitas"] == 0


async def test_a_regua_e_a_de_services_carteira_e_nao_uma_copia(db, dono, cenario, monkeypatch):
    """O defeito guardado: a rota reimplementando a ordenação, a janela comum ou o
    percentual em dia em vez de chamar `services/carteira.py`.

    Uma segunda régua para a mesma pergunta é como nasce a contradição entre duas telas:
    ela passa nos testes no dia em que é escrita e diverge no dia em que só uma das duas
    é corrigida. A prova aqui é direta — as três funções da régua são vigiadas, e a rota
    tem de passar por todas; se tivesse cópia própria, alguma não seria chamada.
    """
    from app.api.v1 import carteira as rota

    assert rota.regua is regua_modulo
    chamou: list[str] = []

    for nome in ("ranking", "cumprimento", "janela_comum"):
        original = getattr(regua_modulo, nome)

        def _vigiada(*a, _nome=nome, _original=original, **k):
            chamou.append(_nome)
            return _original(*a, **k)

        monkeypatch.setattr(regua_modulo, nome, _vigiada)

    await comparativo(de=DE, ate=ATE, db=db, usuario=dono)
    assert set(chamou) == {"ranking", "cumprimento", "janela_comum"}


async def test_janela_comum_nao_afirma_intersecao_que_ninguem_conferiu(db, dono, cenario):
    """A janela é a PEDIDA quando o bloco de energia não foi pedido: sem os meses medidos
    de cada usina, afirmar uma interseção seria inventar a conferência."""
    saida = await comparativo(de="2026-03-01", ate=ATE, blocos="manutencao", db=db, usuario=dono)
    assert saida.janela.meses_comuns == saida.janela.meses
    assert saida.janela.completa is True


async def test_sem_energia_a_janela_DIZ_que_ninguem_conferiu_a_cobertura(db, dono, cenario):
    """O defeito guardado: `comparaveis` ficando no default 0 sem ninguém ter perguntado.

    Com `blocos=manutencao` nenhuma ida ao monitoramento acontece, então não há como saber
    que meses cada usina mediu — e `comparaveis: 0` significa "não perguntei", não
    "nenhuma". O portal lia o zero como resposta e escrevia "0 de 7 usinas da sua carteira
    entram nesta comparação" logo abaixo de uma tabela com usina ranqueada em 1º. Agora a
    própria janela declara que a conferência não houve, e a frase só sai quando houve.
    """
    so_manut = await comparativo(de=DE, ate=ATE, blocos="manutencao", db=db, usuario=dono)
    assert so_manut.janela.cobertura_conferida is False

    com_energia = await comparativo(de=DE, ate=ATE, blocos="energia", db=db, usuario=dono)
    assert com_energia.janela.cobertura_conferida is True
    assert com_energia.janela.comparaveis == com_energia.energia.totais.usinas_no_total


async def test_a_manutencao_declara_o_PROPRIO_intervalo(db, dono, cenario):
    """Com `blocos=tudo` a `janela` do topo é a interseção da ENERGIA — e as contagens da
    manutenção saem do período PEDIDO. Sem o intervalo viajando dentro do bloco, o rótulo de
    uma janela carimbaria números contados noutra: duas respostas para "de que período é
    isto"."""
    saida = await comparativo(de=DE, ate=ATE, blocos="manutencao", db=db, usuario=dono)
    assert saida.manutencao.meses == saida.janela.meses
    assert saida.manutencao.rotulo == regua_modulo.rotulo_de_meses(saida.manutencao.meses)


async def test_os_tres_numeros_do_cartao_saem_da_MESMA_populacao(db, dono, cenario):
    """O defeito guardado, e é o mais caro desta tela.

    `energia_kwh` é do período PEDIDO e de TODAS as usinas; a produtividade sai da JANELA
    COMUM e só das que têm capacidade. Impressos lado a lado sem rótulo, os três não fecham:
    o leitor divide energia por capacidade e acha um número que não é o que está escrito ao
    lado. Agora o numerador e o denominador da razão viajam com nome próprio, e a divisão
    feita de cabeça bate — que é a única prova que o cliente consegue fazer sozinho.
    """
    # A janela PRECISA encolher aqui: com todas as usinas medindo o período inteiro, a soma
    # do período e a da janela comum dão o mesmo número e o teste passaria com o defeito de
    # pé. Ribeirão Bonito entra em junho — é o que separa as duas somas.
    cenario["meuwatt"].meses = {
        "porto-ferreira": {f"2026-{m:02d}": 1000.0 * m for m in range(3, 9)},
        "ribeirao-bonito": {f"2026-{m:02d}": 500.0 * m for m in range(6, 9)},
    }
    saida = await comparativo(de="2026-03-01", ate=ATE, blocos="energia", db=db, usuario=dono)
    t = saida.energia.totais
    assert saida.janela.completa is False
    assert t.energia_comparavel_kwh != t.energia_kwh

    assert t.energia_comparavel_kwh is not None
    assert t.capacidade_comparavel_kwp is not None
    assert t.produtividade_kwh_kwp == round(
        t.energia_comparavel_kwh / t.capacidade_comparavel_kwp, 2
    )
    # E o numerador é a soma das MESMAS usinas que entraram no total — nem uma a mais.
    comparaveis = [
        u for u in saida.energia.usinas
        if u.energia_comparavel_kwh is not None and u.capacidade_kwp
    ]
    assert t.energia_comparavel_kwh == round(
        sum(u.energia_comparavel_kwh for u in comparaveis), 2
    )
    assert t.capacidade_comparavel_kwp == round(sum(u.capacidade_kwp for u in comparaveis), 2)


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
    """O par que prova o deploy: a rota nova responde 401 sem token e uma parecida que não
    existe responde 404. Se as duas dessem o mesmo, não daria para saber se subiu."""
    assert cliente_http.get("/api/v1/carteira/comparativo").status_code == 401
    assert cliente_http.get("/api/v1/carteira/comparativox").status_code == 404

    token, _ = criar_token(dono.id)
    r = cliente_http.get(
        "/api/v1/carteira/comparativo?blocos=energia",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["energia"]["usinas"] == []
