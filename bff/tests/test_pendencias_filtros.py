"""O prazo certo da pendência, e os campos que a tela nova pode receber — sem os que não pode.

Dois defeitos guardados aqui, e um terceiro que é uma cerca.

**1. O prazo estava no lugar errado.** No meuPlano, quem digita o prazo de uma pendência
digita a *previsão de conclusão*, que mora em `extra.previsao_conclusao`; `end_date` é o
campo genérico do contêiner, herdado do funil, e na maioria das pendências está vazio. A
coluna "Prazo" da lista, o campo do detalhe e o board público de lá leem
`extra.previsao_conclusao || end_date`. Este BFF lia só o `end_date` — então pendência com
previsão preenchida saía **sem prazo**, nunca podia vencer, e o cartão do portal marcava
**"Prazo vencido: 0"** com a pendência atrasada visível na tabela logo abaixo. Um cartão
que diz zero é pior do que um cartão ausente: ele afirma.

**2. Os números do topo e as colunas do quadro tinham de fechar.** O kanban do cliente tem
três colunas (Aguardando · Em andamento · Concluída) e os cartões contam o mesmo conjunto.
`aguardando + em_andamento + concluidas == total` é invariante, e vale inclusive quando o
meuPlano ganha um estado que este BFF ainda não conhece — senão a pendência some do quadro
sem sair da conta. A armadilha fina: `situacao` troca para "Prazo vencido" quando a data
passa, e uma coluna que seguisse a *frase* faria a pendência atrasada — justo a que importa
— desaparecer das três colunas. Por isso `coluna` deriva só do status.

**3. Nada de dentro do meuPlano atravessa por acidente.** A rota `visao-cliente` devolve o
`ContainerOut` INTEIRO: `extra`, `fields`, `delegados`, `created_by`, `req_done/req_total`,
`processo_de_*`, `tags`, `parecer_html`. Quem corta é `_pendencia_out`, escolhendo campo a
campo. O teste de chaves abaixo é a única coisa que impede o meuPlano acrescentar um campo
interno e ele nascer publicado no portal do cliente.

Nada de rede: o cliente do meuPlano entra como fantasia.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.pendencias as p
from app.api.v1.pendencias import (
    PendenciaDetalheOut,
    PendenciaOut,
    _faixa_parada,
    _prazo,
    _pendencia_out,
    detalhar_pendencia,
    listar_pendencias,
)
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

HOJE = date.today()
ONTEM = HOJE - timedelta(days=1)
SEMANA_QUE_VEM = HOJE + timedelta(days=7)
LINK = PlantLink(id=9, mw_plant_slug="porto-ferreira", mp_usina_id=1, nome="Porto Ferreira")


@pytest.fixture(autouse=True)
def limpa_cache():
    p._autorizacoes.clear()
    p._em_voo.clear()
    yield
    p._autorizacoes.clear()
    p._em_voo.clear()


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


def _bruto(id_=1, usina_id=1, *, status="ABERTO", previsao=None, end_date=None,
           **resto) -> dict[str, Any]:
    """Um container como a rota `visao-cliente` do meuPlano o devolve."""
    extra = dict(resto.pop("extra", {}) or {})
    if previsao is not None:
        extra["previsao_conclusao"] = previsao
    return {
        "id": id_, "numero": 1000 + id_, "kind": "pendencia", "usina_id": usina_id,
        "title": f"Pendência {id_}", "status": status, "shareable": True,
        "end_date": end_date,
        "created_at": "2026-08-01T12:00:00Z",
        "extra": extra,
        **resto,
    }


class ClienteFalso:
    def __init__(self, por_usina, detalhes=None):
        self.por_usina = por_usina
        self.detalhes = detalhes or {}

    async def vc_pendencias(self, usina_id):
        resposta = self.por_usina.get(usina_id)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if resposta is not None else []

    async def vc_pendencia(self, cid):
        return self.detalhes[cid]


def _instala(monkeypatch, cliente):
    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.pendencias.integracoes.cliente_meuplano", _cliente)
    return cliente


# ── 1. o prazo ──────────────────────────────────────────────────────────────


def test_previsao_no_extra_e_o_prazo_quando_nao_ha_end_date():
    """O defeito do print: previsão preenchida, `end_date` vazio, prazo saía em travessão.

    É a forma MAIS COMUM da pendência no meuPlano — o campo do detalhe grava no `extra`, e
    `end_date` só é preenchido por quem edita a coluna genérica do funil.
    """
    out = _pendencia_out(_bruto(previsao="2026-08-31", end_date=None), LINK, date(2026, 9, 5))

    assert out.prazo == date(2026, 8, 31)
    assert (out.situacao, out.tom) == ("Prazo vencido", "parado")


def test_com_os_dois_preenchidos_vence_a_previsao():
    """A previsão é o que a equipe combinou com o cliente; `end_date` é o campo do funil.
    Invertida a ordem, uma pendência replanejada mostraria a data velha."""
    dados = _bruto(previsao="2026-09-30", end_date="2026-08-31")

    assert _prazo(dados) == date(2026, 9, 30)
    assert _pendencia_out(dados, LINK, date(2026, 9, 5)).prazo == date(2026, 9, 30)


def test_end_date_continua_valendo_quando_nao_ha_previsao():
    """A reserva não pode ter sido perdida no caminho: pendência antiga só tem `end_date`."""
    out = _pendencia_out(_bruto(end_date="2026-08-31"), LINK, date(2026, 9, 5))

    assert out.prazo == date(2026, 8, 31)
    assert out.tom == "parado"


def test_previsao_futura_nao_deixa_o_end_date_vencido_pintar_de_vermelho():
    """O erro espelhado: prazo REPLANEJADO para a frente, `end_date` velho para trás. Lendo
    o campo errado, a tela cobraria uma pendência que está no prazo combinado."""
    out = _pendencia_out(
        _bruto(previsao=SEMANA_QUE_VEM.isoformat(), end_date=ONTEM.isoformat()), LINK, HOJE
    )

    assert out.prazo == SEMANA_QUE_VEM
    assert (out.situacao, out.tom) == ("Aguardando", "alerta")


@pytest.mark.parametrize("extra", [None, {}, {"previsao_conclusao": None},
                                   {"previsao_conclusao": ""}, {"previsao_conclusao": "sem data"},
                                   "isto não é um dicionário"])
def test_previsao_ausente_ou_ilegivel_cai_no_end_date_sem_estourar(extra):
    """`extra` é JSON livre no meuPlano: pode vir nulo, vazio, com texto no lugar da data —
    ou nem ser um dicionário. Nenhuma dessas formas pode derrubar a lista inteira, e todas
    caem na reserva."""
    dados = {**_bruto(end_date="2026-08-31"), "extra": extra}

    assert _prazo(dados) == date(2026, 8, 31)


def test_sem_prazo_nenhum_o_campo_e_nulo_e_nunca_vence():
    out = _pendencia_out(_bruto(), LINK, HOJE)

    assert out.prazo is None
    assert out.situacao == "Aguardando"


@pytest.mark.asyncio
async def test_prazo_vencido_conta_a_previsao_do_extra(db, dono, usinas, monkeypatch):
    """O cartão "Prazo vencido: 0" do print. As três primeiras estão atrasadas; a quarta
    concluiu (fora), a quinta tem prazo à frente (fora)."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    u = minha.mp_usina_id
    _instala(monkeypatch, ClienteFalso({u: [
        _bruto(1, u, previsao=ONTEM.isoformat()),
        _bruto(2, u, previsao=ONTEM.isoformat(), status="EM_ANDAMENTO"),
        _bruto(3, u, end_date=ONTEM.isoformat()),
        _bruto(4, u, previsao=ONTEM.isoformat(), status="CONCLUIDO"),
        _bruto(5, u, previsao=SEMANA_QUE_VEM.isoformat()),
    ]}))

    saida = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert saida.prazo_vencido == 3
    assert [x.id for x in saida.pendencias if x.tom == "parado"] == [1, 2, 3]
    # E o cartão fala do MESMO conjunto que as linhas vermelhas da tabela.
    assert saida.prazo_vencido == sum(1 for x in saida.pendencias if x.tom == "parado")


# ── 2. as colunas e os contadores ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_as_tres_colunas_fecham_com_o_total(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    u = minha.mp_usina_id
    _instala(monkeypatch, ClienteFalso({u: [
        _bruto(1, u), _bruto(2, u),
        _bruto(3, u, status="EM_ANDAMENTO"),
        _bruto(4, u, status="CONCLUIDO"),
    ]}))

    s = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert (s.aguardando, s.em_andamento, s.concluidas) == (2, 1, 1)
    assert s.aguardando + s.em_andamento + s.concluidas == s.total == 4
    assert s.abertas == s.aguardando + s.em_andamento == 3


@pytest.mark.asyncio
async def test_estado_desconhecido_nao_some_do_quadro(db, dono, usinas, monkeypatch):
    """Se o meuPlano ganhar um estado novo, a pendência tem de continuar em alguma coluna.
    Fora das três, ela sumiria do kanban e o cliente pararia de ver o que cobrou."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    u = minha.mp_usina_id
    _instala(monkeypatch, ClienteFalso({u: [_bruto(1, u, status="PARADO"), _bruto(2, u)]}))

    s = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert s.aguardando + s.em_andamento + s.concluidas == s.total == 2
    assert {x.coluna for x in s.pendencias} == {"aguardando"}
    # O rótulo cru continua visível — para alguém reparar no estado novo.
    assert [x.situacao for x in s.pendencias if x.id == 1] == ["Parado"]


def test_prazo_vencido_continua_na_coluna_aguardando():
    """A armadilha: `situacao` vira "Prazo vencido", mas a coluna é onde a pendência MORA.
    Uma coluna derivada da frase faria a pendência atrasada — justo a que importa — cair
    fora das três colunas do quadro."""
    out = _pendencia_out(_bruto(previsao=ONTEM.isoformat()), LINK, HOJE)

    assert (out.situacao, out.tom, out.coluna) == ("Prazo vencido", "parado", "aguardando")


@pytest.mark.asyncio
async def test_cobradas_abertas_conta_so_o_que_o_cliente_pediu_e_nao_voltou(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    u = minha.mp_usina_id
    marca = {"cobrada_pelo_cliente": True}
    _instala(monkeypatch, ClienteFalso({u: [
        _bruto(1, u, extra=marca),
        _bruto(2, u, extra=marca, status="EM_ANDAMENTO"),
        _bruto(3, u, extra=marca, status="CONCLUIDO"),
        _bruto(4, u),  # do time, não dele
    ]}))

    s = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert s.cobradas_abertas == 2
    assert s.abertas == 3, "abertas conta o time todo; cobradas_abertas, só a marca dele"


@pytest.mark.asyncio
async def test_usina_que_falhou_zera_os_contadores_novos_tambem(db, dono, usinas, monkeypatch):
    """Um total parcial parece completo. A regra já valia para `total`/`abertas`; os
    contadores novos não podem ter aberto uma exceção."""
    minha, outra = usinas
    _conceder(db, dono, minha)
    _conceder(db, dono, outra)
    _instala(monkeypatch, ClienteFalso({
        minha.mp_usina_id: [_bruto(1, minha.mp_usina_id)],
        outra.mp_usina_id: httpx.ReadTimeout("demorou"),
    }))

    s = await listar_pendencias(usina_id=None, db=db, usuario=dono)

    assert (s.aguardando, s.em_andamento, s.cobradas_abertas, s.prazo_vencido) == (None,) * 4
    assert s.total is None and s.aviso


# ── 3. a cerca dos campos ───────────────────────────────────────────────────

#: O que o meuPlano manda no `ContainerOut` e NÃO pode chegar ao portal do cliente. Feed e
#: checklist são conversa interna; `processo_de_*` revela de que sinistro/contrato a
#: pendência nasceu; `created_by` é nome de quem trabalha aqui; `extra` é JSON livre onde
#: cabe qualquer coisa que alguém resolveu guardar.
PROIBIDOS = ("comments", "comentarios", "requirements", "req_done", "req_total", "tags",
             "delegado", "delegados", "created_by", "processo_de_id", "processo_kind",
             "processo_numero", "processo_titulo", "extra", "fields", "parecer_html",
             "display_order", "pipeline_id", "require_os_to_close")


def test_pendencia_out_nao_carrega_nenhum_campo_interno():
    chaves = set(PendenciaOut.model_fields)

    vazados = sorted(k for k in PROIBIDOS if k in chaves)
    assert not vazados, f"campo interno publicado ao cliente: {vazados}"


def test_o_detalhe_tambem_nao_carrega():
    """`PendenciaDetalheOut` herda de `PendenciaOut` — um campo interno acrescentado lá
    apareceria nos dois lugares."""
    chaves = set(PendenciaDetalheOut.model_fields)

    assert not sorted(k for k in PROIBIDOS if k in chaves)
    # O que ELE pode ter a mais é escolhido e nomeado.
    assert chaves - set(PendenciaOut.model_fields) == {
        "descricao", "parecer", "documentos_publicados", "ordens"
    }


def test_a_lista_de_campos_e_fechada():
    """Um campo acrescentado sem passar por aqui reprova. É deliberadamente incômodo: o
    upstream devolve o container inteiro, e a diferença entre "o cliente vê" e "o cliente
    não vê" é exatamente esta lista."""
    assert set(PendenciaOut.model_fields) == {
        "id", "numero", "usina", "usina_id", "titulo", "cobrada_pelo_cliente", "etapa",
        "status", "situacao", "tom", "coluna", "criticidade", "criticidade_tom",
        "criticidade_rank", "responsavel", "aberta_em", "prazo", "ultima_atividade_em",
        "faixa_parada", "concluida_em", "equipamento", "equip_count", "parent_id",
        "child_count", "documentos", "os_count",
    }


@pytest.mark.asyncio
async def test_pelo_json_da_rota_nenhum_campo_interno_atravessa(db, dono, usinas, monkeypatch):
    """A cerca valendo de ponta a ponta: o upstream manda o container INTEIRO e o JSON que
    sai não tem nada dele."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({minha.mp_usina_id: [_bruto(
        1, minha.mp_usina_id,
        extra={"previsao_conclusao": "2026-09-30", "anotacao_interna": "cliente não pagou"},
        req_total=4, req_done=1, created_by="diogo@splendor",
        delegados=[{"id": 3, "name": "Diogo"}], tags=[{"id": 1, "name": "urgente"}],
        processo_de_id=77, processo_titulo="Sinistro do vendaval",
        fields=[{"id": 1, "name": "margem", "value": "12%"}],
        parecer_html="<p>interno</p>",
    )]}))

    s = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)
    texto = s.model_dump_json()

    assert "cliente não pagou" not in texto
    assert "Sinistro do vendaval" not in texto and "diogo@splendor" not in texto
    assert "urgente" not in texto and "margem" not in texto
    # E o que ele PODE ver do `extra` continua chegando, traduzido.
    assert s.pendencias[0].prazo == date(2026, 9, 30)


# ── 4. criticidade ──────────────────────────────────────────────────────────


def test_criticidade_rank_ordena_do_pior_para_o_melhor():
    ranks = {c: _pendencia_out(_bruto(criticidade=c), LINK, HOJE).criticidade_rank
             for c in ("critica", "alta", "media", "baixa")}

    assert ranks["critica"] < ranks["alta"] < ranks["media"] < ranks["baixa"]
    assert list(ranks.values()) == [0, 1, 2, 3]


def test_sem_criticidade_vai_para_o_fim_da_ordem_e_nao_some_dela():
    out = _pendencia_out(_bruto(), LINK, HOJE)

    assert out.criticidade is None and out.criticidade_tom is None
    assert out.criticidade_rank == 4
    piores = [_pendencia_out(_bruto(criticidade=c), LINK, HOJE).criticidade_rank
              for c in ("critica", "baixa")]
    assert out.criticidade_rank > max(piores)


def test_criticidade_desconhecida_mantem_o_rotulo_e_vai_para_o_fim():
    """Vocabulário novo no meuPlano não pode fazer a pendência sumir da ordenação."""
    out = _pendencia_out(_bruto(criticidade="catastrofica"), LINK, HOJE)

    assert out.criticidade == "catastrofica"
    assert out.criticidade_tom is None and out.criticidade_rank == 4


def test_ordenar_pelo_rank_poe_a_critica_primeiro():
    fila = [_pendencia_out(_bruto(i, criticidade=c), LINK, HOJE)
            for i, c in enumerate(("baixa", None, "critica", "media", "alta"))]

    assert [x.criticidade for x in sorted(fila, key=lambda x: x.criticidade_rank)] == [
        "critica", "alta", "media", "baixa", None
    ]


# ── 5. faixa de parada ──────────────────────────────────────────────────────


@pytest.mark.parametrize("dias, esperado", [
    (0, "hoje"), (1, "7d"), (7, "7d"), (8, "30d"), (30, "30d"), (31, "+30d"), (400, "+30d"),
])
def test_faixa_parada_por_dias_desde_a_ultima_atividade(dias, esperado):
    hoje = date(2026, 9, 5)
    ultima = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc) - timedelta(days=dias)

    assert _faixa_parada(ultima, hoje) == esperado


def test_sem_atividade_datada_a_faixa_e_nula():
    """"+30d" seria acusar a equipe de abandono a partir de um campo que o upstream não
    mandou. Ausência é nulo, e a tela mostra travessão."""
    assert _faixa_parada(None, HOJE) is None
    assert _pendencia_out(_bruto(), LINK, HOJE).faixa_parada is None


def test_a_faixa_e_lida_no_fuso_da_usina():
    """O comentário das 22h de ontem chega como 01h UTC de hoje. Contado em UTC, um trabalho
    de ontem à noite viraria "hoje" — e a tela diria que alguém mexeu hoje sem ninguém ter
    mexido."""
    ontem_a_noite_brt = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)  # 04/09 22h em BRT

    assert _faixa_parada(ontem_a_noite_brt, date(2026, 9, 5)) == "7d"


def test_atividade_no_futuro_nao_vira_faixa_negativa():
    """Relógio adiantado no upstream não pode produzir uma faixa que não existe."""
    frente = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)

    assert _faixa_parada(frente, date(2026, 9, 5)) == "hoje"


# ── 6. equipamento e subitens ───────────────────────────────────────────────


def test_equipamento_principal_e_contagem_vem_do_upstream():
    out = _pendencia_out(
        _bruto(principal="Inversor 03", equip_count=4, parent_id=None, child_count=2),
        LINK, HOJE,
    )

    assert (out.equipamento, out.equip_count) == ("Inversor 03", 4)
    assert (out.parent_id, out.child_count) == (None, 2)


def test_equipamento_cai_no_rotulo_do_campo_antigo():
    """Pendência criada pelo campo de equipamento único (antes do vínculo N:N) não tem
    `principal` — e ficaria sem equipamento na tela por um detalhe de cadastro."""
    out = _pendencia_out(_bruto(equipment_label="Trafo 01"), LINK, HOJE)

    assert out.equipamento == "Trafo 01"


def test_subitem_carrega_o_pai_para_nao_aparecer_como_outra_cobranca():
    """O cliente vê o filho quando o pai é compartilhável. Sem `parent_id` ele apareceria
    solto na lista, como se fosse uma segunda cobrança."""
    out = _pendencia_out(_bruto(2, parent_id=1, child_count=0), LINK, HOJE)

    assert out.parent_id == 1 and out.child_count == 0


def test_sem_equipamento_os_campos_ficam_nulos_e_nao_zerados():
    """Zero é "nenhum equipamento vinculado"; nulo é "o upstream não contou". A tela
    escolhe travessão ou "0" a partir dessa diferença."""
    out = _pendencia_out(_bruto(), LINK, HOJE)

    assert out.equipamento is None and out.equip_count is None
    assert out.parent_id is None and out.child_count is None


# ── 7. pelo HTTP ────────────────────────────────────────────────────────────


@pytest.fixture
def cliente_http(db):
    app = FastAPI()
    app.include_router(p.router)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_pela_rota_o_prazo_do_extra_chega_e_conta(db, dono, usinas, monkeypatch, cliente_http):
    minha, _ = usinas
    _conceder(db, dono, minha)
    u = minha.mp_usina_id
    _instala(monkeypatch, ClienteFalso({u: [
        _bruto(1, u, previsao=ONTEM.isoformat(), principal="Inversor 03", equip_count=2,
               criticidade="alta", last_activity_at="2026-01-02T10:00:00Z"),
        _bruto(2, u, status="EM_ANDAMENTO"),
    ]}))
    token, _ = criar_token(dono.id)

    r = cliente_http.get(f"/api/v1/manutencao/pendencias?usina_id={minha.id}",
                         headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["prazo_vencido"] == 1
    assert corpo["aguardando"] + corpo["em_andamento"] + corpo["concluidas"] == corpo["total"]
    linha = next(x for x in corpo["pendencias"] if x["id"] == 1)
    assert linha["prazo"] == ONTEM.isoformat()
    assert (linha["coluna"], linha["tom"]) == ("aguardando", "parado")
    assert (linha["equipamento"], linha["equip_count"]) == ("Inversor 03", 2)
    assert linha["criticidade_rank"] == 1 and linha["faixa_parada"] == "+30d"


@pytest.mark.asyncio
async def test_o_detalhe_usa_a_mesma_regua_de_prazo_que_a_lista(db, dono, usinas, monkeypatch):
    """Duas telas, uma resposta: abrir a pendência não pode mostrar um prazo diferente do
    que a lista mostrou na linha de cima."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    u = minha.mp_usina_id
    bruto = _bruto(10, u, previsao=ONTEM.isoformat(), end_date=None)
    _instala(monkeypatch, ClienteFalso({u: [bruto]}, detalhes={10: bruto}))

    lista = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)
    detalhe = await detalhar_pendencia(cid=10, db=db, usuario=dono)

    assert detalhe.prazo == lista.pendencias[0].prazo == ONTEM
    assert detalhe.tom == lista.pendencias[0].tom == "parado"
    assert detalhe.coluna == "aguardando"
