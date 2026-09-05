"""A grade do ano — os defeitos que ela existe para não deixar voltar.

Todos os números daqui foram MEDIDOS contra a conta do dono (usuário 2, 7 usinas) em
05/09/2026, e o cenário é a carteira real reduzida a quatro usinas — uma de cada situação
que existe hoje. Nada é hipotético.

**1. A tela não pode refazer a conta da conformidade.** O `previsto_ate_hoje` de Porto
Ferreira é **31**, e é a soma de 13 (agosto, `fechado`) **+ 18** (setembro, `corrente` — o
`mes_referencia`). Quem somasse só os meses `fechado` chegaria a 13 e mostraria 100 % onde
o meuPlano diz 41,9 %. Foi exatamente essa aritmética recomeçada num segundo lugar que
produziu **"13 de 270" numa tela e "41,9 %" na outra**, no mesmo dia, para a mesma usina.
`test_a_soma_das_celulas_bate_com_o_recorte_de_vigencia` é o cadeado: os dois números que
esta rota entrega para a MESMA pergunta têm de ser o mesmo número.

**2. `ate` não pode ser um mês futuro.** Medido: pedir `2026-01..2026-12` ao
`/manutencao/relatorio` responde **400 "ate não pode ser um mês futuro."**. A linha anual
da manutenção declara a janela real (`janeiro..mês corrente`), e a tela a imprime ao lado
do número.

**3. Ausência tem cinco nomes, não um.** Hoje a tela diz "Sem arquivo anexado" para duas
situações e não tem frase para a terceira — que é a que acontece. Aqui `publicado`,
`fechamento_sem_arquivo`, `sem_fechamento`, `sem_monitoramento` e `indisponivel` são
estados distintos, e o teste das quatro células prova que continuam sendo.

**4. O mês é o do período coberto.** Os fechamentos 35 e 36 cobrem agosto e foram
publicados em 05/09; agrupar pela data de envio poria agosto na coluna de setembro.

**5. A queda de uma usina não pode apagar as outras seis.**
"""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import relatorios_ano
from app.api.v1.relatorios_ano import RelatoriosAnoOut, grade_do_ano
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

#: O dia em que tudo aqui foi medido. Fixo de propósito: a janela do ano anual e a
#: classificação `corrente`/`futuro` dependem de "hoje", e um teste que muda de resposta
#: em 1º de outubro não guarda defeito nenhum.
HOJE = date(2026, 9, 5)


# ── o cenário: a carteira real, reduzida a uma usina por situação ────────────


#: O `meses_estado` REAL de Porto Ferreira, copiado da medição. Repare no par que sustenta
#: o teste 1: agosto `fechado` com 13 previstos, setembro `corrente` com 18 — 13 + 18 = 31,
#: que é o `previsto_ate_hoje` do mesmo payload.
MESES_ESTADO = [
    {"mes": "2026-08", "situacao": "fechado", "previsto": 13, "cumprido": 13},
    {"mes": "2026-09", "situacao": "corrente", "previsto": 18, "cumprido": 0},
    {"mes": "2026-10", "situacao": "futuro", "previsto": 13, "cumprido": 0},
    {"mes": "2026-11", "situacao": "futuro", "previsto": 31, "cumprido": 0},
    {"mes": "2026-12", "situacao": "futuro", "previsto": 18, "cumprido": 0},
    {"mes": "2027-01", "situacao": "futuro", "previsto": 13, "cumprido": 0},
    {"mes": "2027-02", "situacao": "futuro", "previsto": 13, "cumprido": 0},
    {"mes": "2027-03", "situacao": "futuro", "previsto": 18, "cumprido": 0},
    {"mes": "2027-04", "situacao": "futuro", "previsto": 13, "cumprido": 0},
    {"mes": "2027-05", "situacao": "futuro", "previsto": 13, "cumprido": 0},
    {"mes": "2027-06", "situacao": "futuro", "previsto": 93, "cumprido": 0},
    {"mes": "2027-07", "situacao": "futuro", "previsto": 13, "cumprido": 0},
]

#: O `_cronograma_out` do meuPlano de Porto Ferreira, com o recorte de vigência real. O
#: contrato começa em AGOSTO de 2026 e vai até julho de 2027 — de janeiro a julho de 2026
#: não há nada combinado, e é isso que a célula sem `manutencao` diz.
MATRIZ = {
    "status": "CONSOLIDATED",
    "version": 1,
    "month_labels": [m["mes"] for m in MESES_ESTADO],
    # Uma linha basta: a grade do ano não lê `rows` (ela lê `meses_estado`), mas um
    # consolidado sem nenhuma atividade tem aviso próprio lá em `cronograma_da_usina` — e
    # o cronograma real de Porto Ferreira tem 94 linhas.
    "rows": [
        {
            "plan_item_id": 77,
            "name": "Termografia",
            "type_code": "inversor",
            "periodicity_value": 4,
            "periodicity_unit": "ano",
            "expected_per_year": 4,
            "months": {"1": 1},
            "cell_status": {"1": "verde"},
        }
    ],
    "mes_referencia": "2026-09",
    "previsto_ate_hoje": 31,
    "cumprido_ate_hoje": 13,
    "pct_ate_hoje": 41.9,
    "previsto_no_contrato": 269,
    "meses_estado": MESES_ESTADO,
}


class PortalFalso:
    """O `/reports/portal` do meuWatt, com a forma e os números medidos hoje."""

    def __init__(self, quebrado: bool = False):
        self.quebrado = quebrado
        self.chamadas = 0

    async def portal_relatorios(self):
        self.chamadas += 1
        if self.quebrado:
            raise httpx.ConnectError("ponte fora do ar")
        return {
            "reports": [
                # Agosto, publicado em SETEMBRO, com as duas peças e os pesos reais.
                {
                    "id": 35,
                    "name": "Fechamento agosto",
                    "plant_slug": "porto-ferreira",
                    "period": "MENSAL",
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-31",
                    "sent_at": "2026-09-05T12:56:09.914048Z",
                    "files": [
                        {"kind": "geracao", "filename": "g.pdf", "size_bytes": 2686172},
                        {"kind": "paradas", "filename": "p.pdf", "size_bytes": 2604352},
                    ],
                },
                # Agosto de Pereiras: só o Resumo Executivo, 43.238 B.
                {
                    "id": 36,
                    "name": "Fechamento agosto",
                    "plant_slug": "pereiras",
                    "period": "MENSAL",
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-31",
                    "sent_at": "2026-09-05T12:56:07.999069Z",
                    "files": [
                        {"kind": "resumo", "filename": "Resumo.pdf", "size_bytes": 43238}
                    ],
                },
                # O caso que é MAIORIA no acervo: fechamento publicado e sem peça nenhuma.
                {
                    "id": 18,
                    "name": "Fechamento maio",
                    "plant_slug": "pereiras",
                    "period": "MENSAL",
                    "date_from": "2026-05-01",
                    "date_to": "2026-05-31",
                    "sent_at": "2026-06-15T13:42:18.269326Z",
                    "files": [],
                },
                # Usina de outro cliente: o corte por slug é a barreira contra o vazamento
                # e esta leva não pode tê-la afrouxado.
                {
                    "id": 9,
                    "name": "Fechamento março",
                    "plant_slug": "usina-de-outro-cliente",
                    "period": "MENSAL",
                    "date_from": "2026-03-01",
                    "date_to": "2026-03-31",
                    "sent_at": "2026-04-30T03:14:30.560731Z",
                    "files": [{"kind": "geracao", "filename": "x.pdf", "size_bytes": 99}],
                },
            ]
        }


class MeuPlanoFalso:
    """Contratos e cronograma. `derruba` é a usina que estoura, para o teste do isolamento."""

    def __init__(self, derruba: int | None = None):
        self.derruba = derruba
        self.pedidos: list[tuple[str, int]] = []

    async def vc_contratos(self, usina_id):
        self.pedidos.append(("contratos", usina_id))
        if usina_id == self.derruba:
            raise httpx.ConnectError("meuPlano fora do ar")
        return [
            {
                "id": 690 + usina_id,
                "numero": 100 + usina_id,
                "title": f"O&M {usina_id}",
                "start_date": "2026-08-01",
                "end_date": "2027-07-31",
                "vigente": True,
                # Só Porto Ferreira (mp 1) tem consolidado — as outras 5 usinas com
                # manutenção medidas hoje estão sem cronograma publicado.
                "versao_consolidada": 1 if usina_id == 1 else None,
            }
        ]

    async def vc_cronograma(self, usina_id, container_id):
        self.pedidos.append(("cronograma", usina_id))
        if usina_id != 1:
            pedido = httpx.Request("GET", "https://meuplano.exemplo/cronograma")
            raise httpx.HTTPStatusError(
                "404",
                request=pedido,
                response=httpx.Response(404, json={"detail": "sem consolidado"}, request=pedido),
            )
        return MATRIZ


@pytest.fixture
def carteira(db):
    """Quatro usinas, uma por situação real da carteira de hoje.

    * **Porto Ferreira** — monitorada, com fechamento de agosto (2 peças) e o único
      cronograma consolidado.
    * **Pereiras** — monitorada, fechamento de agosto com 1 peça e o de maio **sem peça**.
    * **Ibitinga** — monitorada, contratada, e **nenhum fechamento**.
    * **UFV Leme** — sem monitoramento e sem manutenção.
    """
    linhas = [
        PlantLink(mw_plant_slug="porto-ferreira", mp_usina_id=1, nome="Porto Ferreira"),
        PlantLink(mw_plant_slug="pereiras", mp_usina_id=2, nome="Pereiras"),
        PlantLink(mw_plant_slug="ibitinga", mp_usina_id=6, nome="Ibitinga"),
        PlantLink(mw_plant_slug=None, mp_usina_id=None, nome="UFV Leme"),
    ]
    db.add_all(linhas)
    db.commit()
    return linhas


@pytest.fixture
def dono(db, carteira):
    u = User(
        apelido="dono",
        email="dono@exemplo.com.br",
        nome="Dono",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    for usina in carteira:
        db.add(UserPlantAccess(user_id=u.id, plant_link_id=usina.id))
    db.commit()
    return u


@pytest.fixture
def cenario(monkeypatch, dono):
    """Os dois upstreams como fantasia, e o relógio parado em 05/09/2026."""
    portal = PortalFalso()
    plano = MeuPlanoFalso()

    async def _mw(_db):
        return portal

    async def _mp(_db):
        return plano

    monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _mw)
    monkeypatch.setattr("app.api.v1.manutencao.integracoes.cliente_meuplano", _mp)
    monkeypatch.setattr(relatorios_ano, "hoje_na_usina", lambda: HOJE)
    return portal, plano


async def _grade(db, dono, ano: int = 2026) -> RelatoriosAnoOut:
    saida = await grade_do_ano(ano=ano, db=db, usuario=dono)
    assert isinstance(saida, RelatoriosAnoOut)
    return saida


def _usina(saida: RelatoriosAnoOut, nome: str):
    return next(u for u in saida.usinas if u.nome == nome)


def _celula(saida: RelatoriosAnoOut, nome: str, mes: str):
    return next(c for c in _usina(saida, nome).meses if c.mes == mes)


# ── 1. o BFF não refaz uma única conta da conformidade ──────────────────────


async def test_a_soma_das_celulas_bate_com_o_recorte_de_vigencia(db, dono, cenario):
    """O DEFEITO: recalcular aqui cria a TERCEIRA resposta para "está sendo feito?".

    A régua "até hoje" do meuPlano inclui o mês CORRENTE, e é isso que faz 31 e não 13.
    Se alguém trocar o repasse por uma soma local — a tentação óbvia, já que as células
    estão logo ali —, os dois números que esta mesma resposta entrega para a mesma
    pergunta passam a discordar, e este teste acusa.
    """
    saida = await _grade(db, dono)
    porto = _usina(saida, "Porto Ferreira")

    # Os cinco campos do recorte, exatamente como o meuPlano os mandou.
    assert porto.mes_referencia == "2026-09"
    assert porto.previsto_ate_hoje == 31
    assert porto.cumprido_ate_hoje == 13
    assert porto.pct_ate_hoje == 41.9
    assert porto.previsto_no_contrato == 269

    # E a identidade: Σ do previsto dos meses até o `mes_referencia` (inclusive) é o
    # próprio `previsto_ate_hoje`. Uma pergunta, um número.
    ate = porto.mes_referencia
    soma = sum(
        c.manutencao.previsto
        for c in porto.meses
        if c.manutencao is not None
        and c.manutencao.previsto is not None
        and c.mes <= ate
    )
    assert soma == porto.previsto_ate_hoje, (
        "as células e o recorte discordam — alguém voltou a fazer a conta neste BFF"
    )

    cumpridos = sum(
        c.manutencao.cumprido
        for c in porto.meses
        if c.manutencao is not None
        and c.manutencao.cumprido is not None
        and c.mes <= ate
    )
    assert cumpridos == porto.cumprido_ate_hoje


async def test_somar_so_os_meses_fechados_daria_outro_numero(db, dono, cenario):
    """A armadilha, escrita para ninguém "consertar" o teste acima pelo lado errado.

    `fechado` sozinho é 13; o recorte é 31 porque inclui o mês em curso. Quem trocar a
    identidade acima por esta soma está reintroduzindo o defeito, não corrigindo-o.
    """
    saida = await _grade(db, dono)
    porto = _usina(saida, "Porto Ferreira")

    fechados = sum(
        c.manutencao.previsto
        for c in porto.meses
        if c.manutencao is not None and c.manutencao.situacao == "fechado"
    )
    assert fechados == 13
    assert fechados != porto.previsto_ate_hoje


async def test_a_celula_repassa_o_meses_estado_sem_tocar(db, dono, cenario):
    """Situação, previsto e cumprido chegam como vieram — inclusive o `93` de junho/2027,
    que está fora do ano pedido e por isso NÃO aparece na grade de 2026."""
    saida = await _grade(db, dono)

    agosto = _celula(saida, "Porto Ferreira", "2026-08").manutencao
    assert agosto is not None
    assert (agosto.situacao, agosto.previsto, agosto.cumprido) == ("fechado", 13, 13)

    setembro = _celula(saida, "Porto Ferreira", "2026-09").manutencao
    assert setembro is not None
    assert (setembro.situacao, setembro.previsto, setembro.cumprido) == ("corrente", 18, 0)


async def test_mes_fora_do_contrato_nao_vira_zero(db, dono, cenario):
    """O DEFEITO: um bloco de zeros em janeiro se leria como "previsto e não feito".

    O contrato de Porto Ferreira começa em agosto de 2026. De janeiro a julho não há nada
    combinado — e ausência de combinado é nulo, não zero.
    """
    saida = await _grade(db, dono)
    for mes in ("2026-01", "2026-07"):
        assert _celula(saida, "Porto Ferreira", mes).manutencao is None
    assert _celula(saida, "Porto Ferreira", "2026-08").manutencao is not None


# ── 2. `ate` nunca é um mês futuro ──────────────────────────────────────────


async def test_a_janela_anual_da_manutencao_para_no_mes_corrente(db, dono, cenario):
    """O DEFEITO: `ate=2026-12` num ano em curso é 400 garantido no primeiro toque.

    Medido: `/manutencao/relatorio?de=2026-01&ate=2026-12` responde
    **400 "ate não pode ser um mês futuro."**.
    """
    saida = await _grade(db, dono)
    anual = _usina(saida, "Porto Ferreira").anual.manutencao

    assert anual.disponivel is True
    assert anual.de == "2026-01"
    assert anual.ate == "2026-09"  # o mês corrente, não dezembro


async def test_nenhuma_usina_declara_janela_no_futuro(db, dono, cenario):
    """A varredura: nem uma linha da grade pode oferecer um `ate` que o meuPlano recusa."""
    saida = await _grade(db, dono)
    corrente = HOJE.strftime("%Y-%m")
    for u in saida.usinas:
        if u.anual.manutencao.ate is not None:
            assert u.anual.manutencao.ate <= corrente, u.nome


async def test_ano_ja_fechado_cobre_os_doze_meses(db, dono, cenario):
    """Num ano passado a janela é o ano inteiro — o corte é em hoje, não em dezembro."""
    saida = await _grade(db, dono, ano=2025)
    anual = _usina(saida, "Porto Ferreira").anual.manutencao
    assert (anual.de, anual.ate) == ("2025-01", "2025-12")


async def test_ano_que_ainda_nao_comecou_diz_isso(db, dono, cenario):
    saida = await _grade(db, dono, ano=2027)
    anual = _usina(saida, "Porto Ferreira").anual.manutencao
    assert anual.disponivel is False
    assert anual.de is None and anual.ate is None
    assert anual.motivo


async def test_usina_sem_manutencao_nao_oferece_relatorio(db, dono, cenario):
    saida = await _grade(db, dono)
    anual = _usina(saida, "UFV Leme").anual.manutencao
    assert anual.disponivel is False
    assert "não tem manutenção contratada" in (anual.motivo or "")


# ── 3. as ausências têm nomes diferentes ────────────────────────────────────


async def test_quatro_celulas_tres_estados_nenhum_vazio_mudo(db, dono, cenario):
    """O DEFEITO medido: hoje as três ausências chegam à tela como a mesma frase muda.

    As quatro células são as reais do acervo de 05/09/2026.
    """
    saida = await _grade(db, dono)

    porto_ago = _celula(saida, "Porto Ferreira", "2026-08").energia
    assert porto_ago.estado == "publicado"
    assert porto_ago.documento_id == 35
    assert [p.tipo for p in porto_ago.pecas] == ["geracao", "paradas"]

    pereiras_ago = _celula(saida, "Pereiras", "2026-08").energia
    assert pereiras_ago.estado == "publicado"
    assert [p.tipo for p in pereiras_ago.pecas] == ["resumo"]

    # Fechado, publicado, e sem peça nenhuma: NÃO é "ninguém publicou".
    pereiras_maio = _celula(saida, "Pereiras", "2026-05").energia
    assert pereiras_maio.estado == "fechamento_sem_arquivo"
    assert pereiras_maio.documento_id == 18
    assert pereiras_maio.pecas == []

    # Nenhum fechamento: a única das cinco que é ausência de dado.
    assert _celula(saida, "Ibitinga", "2026-08").energia.estado == "sem_fechamento"


async def test_usina_sem_monitoramento_nao_finge_que_ninguem_publicou(db, dono, cenario):
    """O quinto nome. Sem ele, UFV Leme apareceria com 12 meses de `sem_fechamento` —
    uma acusação a quem publica, por uma usina que nem está ligada ao meuWatt."""
    saida = await _grade(db, dono)
    leme = _usina(saida, "UFV Leme")
    assert leme.tem_monitoramento is False
    assert {c.energia.estado for c in leme.meses} == {"sem_monitoramento"}
    assert leme.anual.energia.estado == "sem_monitoramento"


async def test_ponte_do_monitoramento_fora_nao_vira_ninguem_publicou(db, dono, monkeypatch):
    """O DEFEITO: achatar "não sabemos" em "não tem" afirma o contrário da verdade.

    E a prova do isolamento entre as famílias: com a geração fora, o cronograma de Porto
    Ferreira continua inteiro na mesma resposta.
    """
    portal = PortalFalso(quebrado=True)
    plano = MeuPlanoFalso()
    monkeypatch.setattr(
        "app.api.v1.documents.integracoes.cliente_meuwatt", lambda _db: _pronto(portal)
    )
    monkeypatch.setattr(
        "app.api.v1.manutencao.integracoes.cliente_meuplano", lambda _db: _pronto(plano)
    )
    monkeypatch.setattr(relatorios_ano, "hoje_na_usina", lambda: HOJE)

    saida = await _grade(db, dono)

    assert saida.aviso and "indispon" in saida.aviso.lower()
    assert {c.energia.estado for c in _usina(saida, "Porto Ferreira").meses} == {"indisponivel"}
    # A outra família passou inteira: 31 continua sendo 31.
    assert _usina(saida, "Porto Ferreira").previsto_ate_hoje == 31


async def _pronto(valor):
    """`cliente_meuwatt`/`cliente_meuplano` são corrotinas; isto as imita numa linha."""
    return valor


async def test_o_peso_do_arquivo_viaja_ate_a_celula(db, dono, cenario):
    """O DEFEITO: sem o peso, quem está no 3G toca sem saber se são dois segundos ou dois
    minutos. Sessenta vezes de diferença entre a menor e a maior peça do acervo."""
    saida = await _grade(db, dono)
    porto = _celula(saida, "Porto Ferreira", "2026-08").energia
    assert {p.tipo: p.bytes for p in porto.pecas} == {
        "geracao": 2686172,
        "paradas": 2604352,
    }
    assert _celula(saida, "Pereiras", "2026-08").energia.pecas[0].bytes == 43238


async def test_o_fechamento_do_ano_de_geracao_nao_existe_e_a_celula_diz(db, dono, cenario):
    """A aba Anual do meuWatt cria a linha, mas o gerador de PDF de lá só roda para
    MENSAL: em produção há **zero linhas ANUAL**. Um botão morto seria pior que a frase."""
    saida = await _grade(db, dono)
    anual = _usina(saida, "Porto Ferreira").anual.energia
    assert anual.disponivel is False
    assert anual.estado == "sem_fechamento"
    assert anual.motivo and "anual" in anual.motivo.lower()
    assert anual.pecas == []


# ── 4. o mês é o do período coberto ─────────────────────────────────────────


async def test_agosto_publicado_em_setembro_cai_na_coluna_de_agosto(db, dono, cenario):
    """O DEFEITO: a lista vem ordenada por `publicado_em`, e agrupar por ela poria o
    fechamento de agosto na gaveta de setembro — o cliente não acharia o que procurou."""
    saida = await _grade(db, dono)

    assert _celula(saida, "Porto Ferreira", "2026-08").energia.documento_id == 35
    assert _celula(saida, "Porto Ferreira", "2026-09").energia.estado == "sem_fechamento"
    # E o carimbo do envio continua visível, para a tela poder mostrar os dois.
    assert (
        _celula(saida, "Porto Ferreira", "2026-08").energia.publicado_em or ""
    ).startswith("2026-09-05")


async def test_o_corte_por_usina_nao_mistura_fechamentos(db, dono, cenario):
    """O 36 é de Pereiras e o 35 é de Porto Ferreira: nenhum aparece na linha do outro."""
    saida = await _grade(db, dono)
    ids = {
        u.nome: {c.energia.documento_id for c in u.meses if c.energia.documento_id}
        for u in saida.usinas
    }
    assert ids["Porto Ferreira"] == {35}
    assert ids["Pereiras"] == {36, 18}
    assert ids["Ibitinga"] == set()


async def test_documento_de_outro_cliente_nunca_entra_na_grade(db, dono, cenario):
    """A barreira do vazamento é a de `meus_documentos`, e esta rota a herda por compor
    por dentro. O documento 9 é de uma usina que não é desta conta."""
    saida = await _grade(db, dono)
    todos = {c.energia.documento_id for u in saida.usinas for c in u.meses}
    assert 9 not in todos


async def test_documento_de_outro_ano_nao_entra(db, dono, cenario):
    """Maio de 2026 existe na grade de 2026 e some da de 2025 — sem virar erro."""
    de_2025 = await _grade(db, dono, ano=2025)
    assert {c.energia.estado for c in _usina(de_2025, "Pereiras").meses} == {"sem_fechamento"}


# ── 5. a queda de uma usina não apaga as outras ─────────────────────────────


async def test_uma_usina_derrubada_nao_leva_as_outras(db, dono, monkeypatch):
    """O DEFEITO: um `gather` sem `return_exceptions` faria a queda de uma usina virar 500
    para a carteira inteira — a tela do cliente em branco por causa de uma linha."""
    portal = PortalFalso()
    plano = MeuPlanoFalso(derruba=2)  # Pereiras
    monkeypatch.setattr(
        "app.api.v1.documents.integracoes.cliente_meuwatt", lambda _db: _pronto(portal)
    )
    monkeypatch.setattr(
        "app.api.v1.manutencao.integracoes.cliente_meuplano", lambda _db: _pronto(plano)
    )
    monkeypatch.setattr(relatorios_ano, "hoje_na_usina", lambda: HOJE)

    saida = await _grade(db, dono)

    assert len(saida.usinas) == 4
    assert _usina(saida, "Pereiras").aviso_manutencao
    # As outras respondem inteiras, inclusive a geração de quem caiu.
    assert _usina(saida, "Porto Ferreira").aviso_manutencao is None
    assert _usina(saida, "Porto Ferreira").previsto_ate_hoje == 31
    assert _celula(saida, "Pereiras", "2026-08").energia.estado == "publicado"


async def test_cronograma_nao_publicado_e_um_aviso_nao_um_buraco(db, dono, cenario):
    """5 das 6 usinas com manutenção medidas hoje estão sem cronograma publicado. É estado
    normal de início de contrato, e a linha aparece com a frase — não some da grade."""
    saida = await _grade(db, dono)
    ibitinga = _usina(saida, "Ibitinga")
    assert ibitinga.tem_manutencao is True
    assert ibitinga.cronograma_status is None
    assert ibitinga.aviso_manutencao and "publicou" in ibitinga.aviso_manutencao
    assert all(c.manutencao is None for c in ibitinga.meses)


# ── a forma da grade e o custo ──────────────────────────────────────────────


async def test_a_grade_tem_doze_colunas_em_ordem(db, dono, cenario):
    saida = await _grade(db, dono)
    assert saida.meses == [f"2026-{m:02d}" for m in range(1, 13)]
    for u in saida.usinas:
        assert [c.mes for c in u.meses] == saida.meses


async def test_uma_ida_por_familia_e_nao_uma_por_mes(db, dono, cenario):
    """O DEFEITO que a rota existe para evitar: perguntar mês a mês custou 9 chamadas,
    3.511 ms e 84,5 KB para extrair um número por mês.

    A geração é UMA ida para a carteira inteira; a manutenção é uma por usina COM
    manutenção — nunca uma por célula.
    """
    portal, plano = cenario
    await _grade(db, dono)

    assert portal.chamadas == 1
    cronogramas = [p for p in plano.pedidos if p[0] == "cronograma"]
    # 3 usinas com manutenção; a 4ª (UFV Leme) não tem e não é perguntada.
    assert len(cronogramas) <= 3
    assert {u for _, u in cronogramas} <= {1, 2, 6}
    # E NENHUM pedido de relatório: a grade DECLARA a janela, quem a pede é a tela — o
    # `MeuPlanoFalso` nem tem o método, então uma chamada viraria erro visível.
    assert {tipo for tipo, _ in plano.pedidos} == {"contratos", "cronograma"}


async def test_a_grade_nao_pede_relatorio_nenhum_ao_meuplano(db, dono, cenario):
    """O DEFEITO que o 400 do meuPlano cobraria: montar `ate=2026-12` num ano em curso.

    A rota não chama `/manutencao/relatorio` — ela diz que janela ele cobriria. Logo,
    zero respostas 400: não há chamada para levar 400. O que este teste guarda é que a
    grade não passe a chamá-lo por dentro (o que reintroduziria a alternativa de 9 idas e
    3.511 ms que a rota existe para substituir).
    """
    import pathlib

    fonte = pathlib.Path(relatorios_ano.__file__).read_text(encoding="utf-8")
    linhas_de_codigo = [
        l for l in fonte.splitlines() if not l.lstrip().startswith(("#", '"', "*"))
    ]
    corpo = "\n".join(linhas_de_codigo)
    assert "relatorio_de_manutencao" not in corpo
    assert "vc_relatorio" not in corpo


async def test_a_resposta_cabe_no_bolso_de_quem_esta_em_campo(db, dono, cenario):
    """O teto é 15 KB. Foi por não caber que a alternativa (127 KB de cronograma por
    usina, dos quais 880 B servem) foi descartada.

    O corpo medido é o que sai pela PORTA, sem os nulos. Contra a carteira real (7 usinas,
    2026): **15.724 B com os nulos escritos e 9.863 B sem** — a grade é 84 células e a
    maioria é ausência, então mais de um terço do corpo eram as palavras `null`.
    """
    saida = await _grade(db, dono)
    assert len(saida.model_dump_json(exclude_none=True).encode("utf-8")) < 15_000


# ── ETag ────────────────────────────────────────────────────────────────────


@pytest.fixture
def http(db, dono, cenario):
    """A aplicação REAL — `app.main.app` —, não um `FastAPI()` montado aqui.

    O DEFEITO que isto guarda já aconteceu, e custou a entrega: o router existia, tinha 30
    testes verdes e **não estava montado no `main.py`**. Todos os testes passavam porque
    cada um montava o seu próprio aplicativo; em produção a tela do ano respondia
    **404 Not Found**. Um teste que constrói o seu próprio servidor prova que o código do
    router funciona e não prova que alguém consegue chamá-lo — que é a única coisa que o
    dono vê.
    """
    from app.main import app as aplicacao

    aplicacao.dependency_overrides[get_db] = lambda: db
    cliente = TestClient(aplicacao)
    token, _ = criar_token(dono.id)
    cliente.headers["Authorization"] = f"Bearer {token}"
    try:
        yield cliente
    finally:
        aplicacao.dependency_overrides.clear()


def test_a_rota_esta_montada_na_aplicacao_de_verdade():
    """O cadeado explícito, sem cenário nem banco: o caminho existe em `app.main.app`.

    Se alguém apagar a linha do `include_router`, é este teste que diz o nome do que
    sumiu — em vez de trinta testes verdes e um 404 no celular.
    """
    from app.main import app as aplicacao

    assert "/api/v1/relatorios/ano" in [r.path for r in aplicacao.routes]


def test_a_revisita_custa_304_e_zero_byte(http):
    """O DEFEITO: sem `ETag`, o cache em disco do app ou baixa tudo de novo ou mostra o
    velho, sem poder perguntar "mudou?". É o único item da leva que muda de verdade a vida
    de quem tem rede ruim."""
    primeira = http.get("/api/v1/relatorios/ano?ano=2026")
    assert primeira.status_code == 200
    etag = primeira.headers.get("ETag")
    assert etag

    segunda = http.get("/api/v1/relatorios/ano?ano=2026", headers={"If-None-Match": etag})
    assert segunda.status_code == 304
    assert segunda.content == b""


def test_o_etag_fraco_de_um_proxy_ainda_casa(http):
    """`If-None-Match` é uma LISTA e pode vir com o prefixo `W/`. Comparar a string crua
    faria a revalidação falhar em silêncio: nada quebra e o 304 nunca acontece — o defeito
    mais caro de diagnosticar, porque a tela continua certa e só a rede continua cara."""
    etag = http.get("/api/v1/relatorios/ano?ano=2026").headers["ETag"]
    resposta = http.get(
        "/api/v1/relatorios/ano?ano=2026",
        headers={"If-None-Match": f'W/{etag}, "outra-coisa"'},
    )
    assert resposta.status_code == 304


def test_o_corpo_que_sai_pela_porta_nao_carrega_a_palavra_null(http):
    """O DEFEITO: 37 % do corpo medido eram nulos escritos — 15.724 B contra 9.863 B na
    carteira real. Zero, porém, continua saindo: `previsto: 0` é resposta, não ausência.

    Também é a prova de que a impressão digital do ETag é a DESTE texto, e não a de um
    corpo que ninguém recebe.
    """
    resposta = http.get("/api/v1/relatorios/ano?ano=2026")
    corpo = resposta.json()

    porto = next(u for u in corpo["usinas"] if u["nome"] == "Porto Ferreira")
    janeiro = next(c for c in porto["meses"] if c["mes"] == "2026-01")
    # Mês fora do contrato: a chave some, em vez de viajar como `null`.
    assert "manutencao" not in janeiro
    assert janeiro["energia"]["estado"] == "sem_fechamento"
    assert "documento_id" not in janeiro["energia"]

    setembro = next(c for c in porto["meses"] if c["mes"] == "2026-09")
    # Zero é resposta e continua escrito.
    assert setembro["manutencao"]["cumprido"] == 0
    assert b"null" not in resposta.content


def test_ano_fora_do_alcance_e_recusado_com_frase(http):
    resposta = http.get("/api/v1/relatorios/ano?ano=1")
    assert resposta.status_code == 400
    assert "Ano fora do alcance" in resposta.json()["detail"]


async def test_quem_nao_tem_usina_recebe_grade_vazia_e_nao_erro(db, cenario):
    """Conta sem nenhuma concessão: 12 colunas e nenhuma linha. Vazio nomeado, não 500."""
    outro = User(
        apelido="sem-usina",
        email="sem@exemplo.com.br",
        nome="Sem usina",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(outro)
    db.commit()

    saida = await grade_do_ano(ano=2026, db=db, usuario=outro)

    assert isinstance(saida, RelatoriosAnoOut)
    assert saida.usinas == []
    assert len(saida.meses) == 12
    # Sem usina ligada ao monitoramento, o aviso é esse — e não "a ponte caiu".
    assert saida.aviso and "monitoramento" in saida.aviso


# ── a sonda não ganha linha nenhuma ─────────────────────────────────────────


def test_nenhum_metodo_novo_nasceu_em_clients(db):
    """A rota compõe por DENTRO, chamando funções — nunca HTTP contra o próprio serviço.

    A consequência é que o catálogo da sonda não muda, e a prova é por AST: este módulo
    não pode importar nada de `app.clients`. Se alguém trocar a composição por uma chamada
    ao próprio BFF (ou por um método novo de cliente), este teste acusa antes de a sonda
    passar a mentir sobre a cobertura.
    """
    import ast
    import pathlib

    fonte = pathlib.Path(relatorios_ano.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    importados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.append(no.module)

    assert not [m for m in importados if m.startswith("app.clients")], importados
    assert "httpx" not in importados, "a grade voltou a falar HTTP por conta própria"
