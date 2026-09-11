"""O relatório mensal de MANUTENÇÃO atravessando o BFF — os defeitos que isto guarda.

Tudo aqui foi medido em **06/09/2026** contra `https://meuplano.up.railway.app` com o PAT
de serviço da ponte, e contra a carteira do dono (usuário 2, 7 usinas). Nada é hipotético.

**0. O estado de hoje é VAZIO, e vazio não é defeito.** Medido: as três usinas consultadas
(Porto Ferreira 19, Ibitinga 37, Pereiras 4) responderam `200 {"itens": []}`, e os ids que
existem no painel interno (14, 61, 84) respondem **404** na porta do cliente. Os 26
relatórios de agosto/2026 estão todos em `rascunho`. O corte do meuPlano está funcionando
exatamente como escrito — e a consequência é que a família nova nasce vazia. A tela precisa
distinguir "respondeu e não há nada liberado" de "não deu para perguntar", e é por isso que
a ausência do mapa (`mensais is None`) não é a mesma coisa que a lista vazia.

**1. O corte é o STATUS, e ele NÃO mora aqui.** No meuPlano o ciclo é *Gerado → A aprovar →
Aprovado → Liberado p/ envio → Enviado*, e só os dois últimos (`enviado`, `expedido`)
atravessam `visao-cliente`. A armadilha é o degrau chamado **"aprovado"**: ele parece
liberado e não é — um relatório aprovado pode voltar para revisão, e o cliente não pode ter
visto um número que mudou. A defesa deste lado não é reimplementar a régua (isso daria uma
segunda resposta para "pode mostrar?", e a errada entregaria o documento): é **não conhecer
outra porta**. `test_o_bff_so_conhece_a_porta_do_cliente` bate um cliente que explode em
qualquer método diferente de `vc_relatorios_mensais`.

**2. `documentos` não pode ter mudado um byte.** A família nova entra por ADIÇÃO. Se a
lista de geração mudar de forma, a aba de Relatórios do aplicativo — que lê esta rota com
cache em disco — quebra para quem já tem o arquivo velho gravado.

**3. A etiqueta tem de cobrir a família nova.** O `ETag` é o sha256 do corpo. Se alguém o
recalcular só sobre `documentos` — a "otimização" óbvia, já que era assim que ele nasceu —,
o `304` passa a servir um acervo mensal velho **para sempre**, e ninguém descobre: a tela
continua desenhando, só nunca atualiza.

**4. A cor da célula do ano não pode depender do documento.** `marcaDaManutencao` responde
*"foi feito?"* a partir de `situacao`/`previsto`/`cumprido`. O PDF responde *"há papel sobre
isso?"*. Se a existência do documento pintasse a célula, a grade responderia duas perguntas
com uma cor só — e hoje, com zero liberados, ela ficaria inteira em travessão.

**5. Dois documentos, uma ordem só.** Executivo antes do técnico, no portal e no
aplicativo. A diretoria é o destino que o próprio meuPlano declara para o executivo; uma
ordem por frente daria duas respostas para a mesma pergunta.

**6. Nome de funcionário não sai para o cliente.** `aprovado_por` vem na resposta do
meuPlano e para aqui: publicá-lo entrega o organograma interno da executora e cria endereço
para cobrança pessoal.
"""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import documents, relatorios_ano
from app.api.v1.documents import (
    RelatorioMensalOut,
    documentos_de_geracao,
    mensais_das_usinas,
    meus_documentos,
)
from app.api.v1.relatorios_ano import RelatoriosAnoOut, grade_do_ano
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

#: O dia em que tudo aqui foi medido. Fixo: `corrente`/`futuro` dependem de "hoje", e um
#: teste que muda de resposta em 1º de outubro não guarda defeito nenhum.
HOJE = date(2026, 9, 5)


def _liberado(
    rid: int,
    mp_usina_id: int,
    competencia: str,
    tipo: str,
    liberado_em: str = "2026-09-06T11:02:33.412000",
) -> dict:
    """Uma linha do `_liberado_out` do meuPlano, com os oito campos que ele manda.

    Conferido no código de lá (`visao_cliente_relatorios.py:_liberado_out`) em 06/09/2026:
    `id`, `usina_id`, `competencia`, `tipo`, `liberado_em`, `aprovado_em`, `aprovado_por`,
    `apurado_em`. Os três últimos vêm de propósito no cenário — é justamente o que **não**
    pode chegar à tela.
    """
    return {
        "id": rid,
        "usina_id": mp_usina_id,
        "competencia": competencia,
        "tipo": tipo,
        "liberado_em": liberado_em,
        "aprovado_em": "2026-09-05T18:00:00",
        "aprovado_por": "Paulo Renan Nunes Marquezini",
        "apurado_em": "2026-09-01T04:10:00",
    }


#: O acervo do cenário, por `mp_usina_id`. Porto Ferreira (mp 1) tem os dois documentos de
#: agosto e os dois de julho; Pereiras (mp 2) tem só o técnico; Ibitinga (mp 6) respondeu
#: **vazio**, que é o estado real de toda a base hoje.
ACERVO = {
    1: [
        # Chegam do meuPlano em ordem de competência decrescente, e dentro do mês na ordem
        # em que a query de lá os devolveu — técnico primeiro. A ordem do cliente é OUTRA,
        # e é o BFF que a impõe: se o cenário já viesse ordenado, o teste da ordem não
        # provaria nada.
        _liberado(14, 1, "2026-08", "tecnico"),
        _liberado(61, 1, "2026-08", "executivo"),
        _liberado(9, 1, "2026-07", "tecnico", "2026-08-04T09:15:00"),
        _liberado(10, 1, "2026-07", "executivo", "2026-08-04T09:15:00"),
    ],
    2: [_liberado(84, 2, "2026-08", "tecnico")],
    6: [],
}


class MeuWattFalso:
    """O `/reports/portal`, com dois fechamentos reais. Não muda nesta leva."""

    async def portal_relatorios(self):
        return {
            "reports": [
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
                {
                    "id": 36,
                    "name": "Fechamento agosto",
                    "plant_slug": "pereiras",
                    "period": "MENSAL",
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-31",
                    "sent_at": "2026-09-05T12:56:07.999069Z",
                    "files": [{"kind": "resumo", "filename": "Resumo.pdf", "size_bytes": 43238}],
                },
                # Usina de outro cliente — o corte por slug é a barreira e nada desta leva
                # pode tê-lo afrouxado.
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


#: O `meses_estado` do cenário: o contrato começa em AGOSTO de 2026. De janeiro a julho não
#: há nada combinado — e é aí que mora o teste do documento fora do contrato.
MESES_ESTADO = [
    {"mes": "2026-08", "situacao": "fechado", "previsto": 13, "cumprido": 13},
    {"mes": "2026-09", "situacao": "corrente", "previsto": 18, "cumprido": 0},
    {"mes": "2026-10", "situacao": "futuro", "previsto": 13, "cumprido": 0},
    {"mes": "2026-11", "situacao": "futuro", "previsto": 31, "cumprido": 0},
    {"mes": "2026-12", "situacao": "futuro", "previsto": 18, "cumprido": 0},
]

MATRIZ = {
    "status": "CONSOLIDATED",
    "version": 1,
    "month_labels": [m["mes"] for m in MESES_ESTADO],
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
    "previsto_no_contrato": 93,
    "meses_estado": MESES_ESTADO,
}


class MeuPlanoFalso:
    """Cronograma e acervo mensal. `derruba` é o `mp_usina_id` que estoura."""

    def __init__(self, acervo: dict | None = None, derruba: int | None = None):
        self.acervo = ACERVO if acervo is None else acervo
        self.derruba = derruba
        self.pedidos: list[int] = []

    async def vc_contratos(self, usina_id):
        return [
            {
                "id": 690 + usina_id,
                "numero": 100 + usina_id,
                "title": f"O&M {usina_id}",
                "start_date": "2026-08-01",
                "end_date": "2026-12-31",
                "vigente": True,
                "versao_consolidada": 1 if usina_id == 1 else None,
            }
        ]

    async def vc_cronograma(self, usina_id, container_id):
        if usina_id != 1:
            pedido = httpx.Request("GET", "https://meuplano.exemplo/cronograma")
            raise httpx.HTTPStatusError(
                "404",
                request=pedido,
                response=httpx.Response(404, json={"detail": "sem consolidado"}, request=pedido),
            )
        return MATRIZ

    async def vc_relatorios_mensais(self, usina_id):
        self.pedidos.append(usina_id)
        if usina_id == self.derruba:
            raise httpx.ConnectError("meuPlano fora do ar")
        return list(self.acervo.get(usina_id, []))


class PortaUnica(MeuPlanoFalso):
    """Um cliente que só admite a porta do cliente. Qualquer outra chamada explode.

    É o cadeado do corte: `visao-cliente` é onde o meuPlano aplica `status in ('enviado',
    'expedido')` incondicionalmente. Se alguém deste lado trocar para a rota interna
    `/relatorios` — que devolve rascunho, "a aprovar" e o enganoso "aprovado" —, o teste
    acusa em vez de o cliente receber um documento que ninguém liberou.
    """

    def __getattr__(self, nome):  # só chamado quando o atributo NÃO existe na classe
        raise AssertionError(
            f"o BFF chamou `{nome}` — a única porta do relatório mensal é "
            "`vc_relatorios_mensais` (visao-cliente), onde o corte por status é do meuPlano"
        )


@pytest.fixture
def carteira(db):
    """Três usinas com manutenção (36 células no ano) e uma sem nenhuma das duas pontes."""
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


def _montar(monkeypatch, plano, meuwatt=None):
    def _mw(_db, _cliente_id=None):
        return meuwatt or MeuWattFalso()

    def _mp(_db, _cliente_id=None):
        return plano

    monkeypatch.setattr("app.api.v1.documents.vinculos.cliente_meuwatt", _mw)
    monkeypatch.setattr("app.api.v1.documents.vinculos.cliente_meuplano", _mp)
    monkeypatch.setattr("app.api.v1.manutencao.vinculos.cliente_meuplano", _mp)
    monkeypatch.setattr(relatorios_ano, "hoje_na_usina", lambda: HOJE)
    return plano


@pytest.fixture
def cenario(monkeypatch, dono):
    return _montar(monkeypatch, MeuPlanoFalso())


@pytest.fixture
def http(db, dono, cenario):
    """Só o router de documentos — um router alheio quebrado no meio de uma edição não
    pode derrubar este arquivo. Mesma postura do `test_documents_eixo.py`."""
    aplicacao = FastAPI()
    aplicacao.include_router(documents.router)
    aplicacao.dependency_overrides[get_db] = lambda: db
    cliente = TestClient(aplicacao)
    token, _ = criar_token(dono.id)
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


def _usina(saida: RelatoriosAnoOut, nome: str):
    return next(u for u in saida.usinas if u.nome == nome)


def _celula(saida: RelatoriosAnoOut, nome: str, mes: str):
    return next(c for c in _usina(saida, nome).meses if c.mes == mes)


# ── 0. vazio é o estado de hoje, e ele não é falha ──────────────────────────


async def test_acervo_vazio_nao_e_falha_e_nao_inventa_nada(db, dono, monkeypatch):
    """O DEFEITO: tratar "nada liberado" como erro, ou preencher com série gerada.

    Medido em 06/09/2026: as 22 usinas visíveis ao PAT respondem `{"itens": []}`. A
    resposta correta é lista vazia e **nenhum aviso** — ausência de documento não é falha,
    e um aviso aqui faria a tela acusar defeito onde a equipe só não liberou ainda.
    """
    plano = _montar(monkeypatch, MeuPlanoFalso(acervo={1: [], 2: [], 6: []}))
    saida = await meus_documentos(None, db, dono)

    assert saida.mensais == []
    assert saida.aviso_mensais is None
    # E perguntou às três usinas com manutenção — não deixou de perguntar por atalho.
    assert sorted(plano.pedidos) == [1, 2, 6]


async def test_usina_que_nao_respondeu_nao_e_usina_sem_documento(db, dono, monkeypatch):
    """O DEFEITO: achatar "não sabemos" em "não há".

    São coisas diferentes e só a segunda é ausência. No mapa do fan-out, a usina que caiu
    fica **fora** do dicionário; a que respondeu vazio entra com lista vazia. Sem essa
    distinção a grade do ano diria "nenhum relatório publicado" para uma usina cujo
    servidor não respondeu.
    """
    _montar(monkeypatch, MeuPlanoFalso(derruba=2))
    from app.api.v1.plants import usinas_do_usuario

    por_usina, aviso = await mensais_das_usinas(db, usinas_do_usuario(db, dono), dono)

    ids = {l.nome: l.id for l in usinas_do_usuario(db, dono)}
    assert ids["Pereiras"] not in por_usina, "usina que caiu não pode virar 'sem documento'"
    assert por_usina[ids["Ibitinga"]] == [], "usina que respondeu vazio entra com lista vazia"
    assert aviso and "Pereiras" in aviso, "o aviso nomeia QUAL usina faltou"
    assert "Porto Ferreira" not in aviso


# ── 1. o corte do status é do meuPlano, e este lado não conhece outra porta ──


async def test_o_bff_so_conhece_a_porta_do_cliente(db, dono, monkeypatch):
    """O DEFEITO: buscar o acervo por uma rota que não aplica o corte por status.

    O degrau "aprovado" **não** é liberado — é conversa interna, e um relatório aprovado
    pode voltar para revisão. A rota interna `/relatorios` devolve os cinco status; a
    `visao-cliente` devolve só `enviado`/`expedido`. Este teste explode se alguém trocar a
    porta, em vez de o cliente descobrir por um número que mudou depois de publicado.
    """
    _montar(monkeypatch, PortaUnica())
    saida = await meus_documentos(None, db, dono)
    # Pereiras antes de Porto Ferreira (alfabética), e dentro de cada usina o executivo
    # antes do técnico: os dois documentos de uma usina são um cartão só.
    assert [r.id for r in saida.mensais if r.competencia == "2026-08"] == [84, 61, 14]


async def test_nome_de_funcionario_nao_atravessa(db, dono, cenario):
    """O DEFEITO: repassar `aprovado_por` — nome de gente da executora — ao cliente.

    Publicá-lo entrega o organograma interno e cria endereço para cobrança pessoal.
    `aprovado_em` e `apurado_em` também ficam de fora: "quando os números foram
    calculados" não é "de quando é este documento", e três datas na mesma linha fazem o
    leitor não saber qual responde à pergunta dele. Uma data visível: `liberado_em`.
    """
    saida = await meus_documentos(None, db, dono)
    assert saida.mensais, "o cenário tem acervo — senão este teste não prova nada"

    for r in saida.mensais:
        campos = r.model_dump()
        assert set(campos) == {"id", "usina_id", "usina", "competencia", "tipo", "liberado_em"}

    corpo = saida.model_dump_json()
    assert "Marquezini" not in corpo
    assert "aprovado_por" not in corpo and "apurado_em" not in corpo


# ── 2. `documentos` não mudou um byte ───────────────────────────────────────


#: O contrato da família de GERAÇÃO, congelado. Se esta lista precisar mudar, alguém mudou
#: a forma que o aplicativo já tem gravada em disco — e o cache velho passa a não casar.
GERACAO_CONGELADA = [
    {
        "id": 35,
        "nome": "Fechamento agosto",
        "usina": "Porto Ferreira",
        "periodo": "MENSAL",
        "de": date(2026, 8, 1),
        "ate": date(2026, 8, 31),
        "arquivos": [
            {"tipo": "geracao", "nome": "g.pdf", "bytes": 2686172},
            {"tipo": "paradas", "nome": "p.pdf", "bytes": 2604352},
        ],
        "competencia": "2026-08",
        "ano": None,
    },
    {
        "id": 36,
        "nome": "Fechamento agosto",
        "usina": "Pereiras",
        "periodo": "MENSAL",
        "de": date(2026, 8, 1),
        "ate": date(2026, 8, 31),
        "arquivos": [{"tipo": "resumo", "nome": "Resumo.pdf", "bytes": 43238}],
        "competencia": "2026-08",
        "ano": None,
    },
]


async def test_a_familia_da_geracao_nao_mudou_um_byte(db, dono, cenario):
    """O DEFEITO: a família nova entrar por MODIFICAÇÃO em vez de por adição.

    A aba de Relatórios do aplicativo lê esta rota com cache em disco. Um campo renomeado
    ou uma peça a menos quebra a tela de quem já tem o arquivo antigo gravado — e o modo de
    falha desta família é justamente o 200 com campo trocado, que nenhum código de status
    denuncia.
    """
    saida = await meus_documentos(None, db, dono)

    magro = [
        {k: v for k, v in d.model_dump().items() if k not in ("plant_id", "publicado_em")}
        for d in saida.documentos
    ]
    assert magro == GERACAO_CONGELADA
    # O corte por slug continua de pé: a usina do outro cliente não sai.
    assert {d.id for d in saida.documentos} == {35, 36}
    assert saida.aviso is None


async def test_a_geracao_sobrevive_a_queda_do_meuplano(db, dono, monkeypatch):
    """O DEFEITO: a queda de uma família apagar a outra.

    E o motivo de cada uma viaja no campo DELA. Foi juntá-los num campo só que fez o
    aplicativo arrancar o prefixo com expressão regular e mostrar a frase da manutenção na
    aba de geração (ver `UsinaAnoOut.aviso_manutencao`).
    """

    class Explode(MeuPlanoFalso):
        async def vc_relatorios_mensais(self, usina_id):
            raise httpx.ConnectError("meuPlano fora do ar")

    _montar(monkeypatch, Explode())
    saida = await meus_documentos(None, db, dono)

    assert [d.id for d in saida.documentos] == [35, 36], "a geração inteira, apesar da queda"
    assert saida.aviso is None, "o campo da geração não pode carregar motivo de outra família"
    assert saida.aviso_mensais and "Porto Ferreira" in saida.aviso_mensais
    assert saida.mensais == []


# ── 3. a etiqueta cobre a família nova ──────────────────────────────────────


def test_a_etiqueta_muda_quando_so_o_acervo_mensal_muda(http, monkeypatch):
    """O DEFEITO: recalcular o `ETag` só sobre `documentos`.

    É a "otimização" óbvia, porque foi assim que ele nasceu. O estrago é invisível: o
    `304` passa a servir um acervo mensal velho para sempre, a tela continua desenhando e
    ninguém descobre — só nunca atualiza. Aqui a geração fica IDÊNTICA de propósito: só o
    mensal muda, e a etiqueta tem de mudar com ele.
    """
    primeira = http.get("/api/v1/documents")
    assert primeira.status_code == 200
    etiqueta = primeira.headers["ETag"]
    assert primeira.json()["mensais"], "o cenário precisa ter acervo para o teste valer"

    # A mesma pergunta, com a etiqueta na mão: 304 e zero byte.
    assert http.get("/api/v1/documents", headers={"If-None-Match": etiqueta}).status_code == 304

    # Agora só o acervo mensal muda — a geração continua a mesma.
    _montar(monkeypatch, MeuPlanoFalso(acervo={1: [], 2: [], 6: []}))
    segunda = http.get("/api/v1/documents", headers={"If-None-Match": etiqueta})
    assert segunda.status_code == 200, "o 304 estaria servindo um acervo mensal velho"
    assert segunda.headers["ETag"] != etiqueta
    assert segunda.json()["mensais"] == []
    assert segunda.json()["documentos"] == primeira.json()["documentos"]


# ── 4. a cor da célula do ano não depende do documento ──────────────────────


def _marcas(saida: RelatoriosAnoOut) -> dict[tuple[str, str], tuple]:
    """Os três campos de que a cor da célula sai — e só eles.

    Bloco ausente e bloco sem conformidade dão a MESMA leitura de propósito: é assim que a
    função de cor os enxerga (`?? '—'` dos dois lados). O que o teste guarda é a cor, e a
    existência do bloco é assunto de `test_documento_de_mes_fora_do_contrato_nao_some`.
    """
    return {
        (u.nome, c.mes): (
            (None, None, None)
            if c.manutencao is None
            else (c.manutencao.situacao, c.manutencao.previsto, c.manutencao.cumprido)
        )
        for u in saida.usinas
        for c in u.meses
    }


async def test_a_marca_da_celula_nao_depende_do_documento(db, dono, monkeypatch):
    """O DEFEITO: a existência do PDF pintar a célula do ano.

    A cor responde "foi feito?" (conformidade, do `meses_estado` do meuPlano); o documento
    responde "há papel sobre isso?". Uma cor só para duas perguntas é a lição de "13 de
    270" numa tela e "41,9 %" na outra — e hoje, com zero relatórios liberados, a grade
    ficaria inteira em travessão. As 36 células das três usinas com manutenção têm de
    sair idênticas com e sem acervo.
    """
    _montar(monkeypatch, MeuPlanoFalso(acervo={1: [], 2: [], 6: []}))
    sem = _marcas(await grade_do_ano(ano=2026, db=db, usuario=dono))

    _montar(monkeypatch, MeuPlanoFalso())
    com = await grade_do_ano(ano=2026, db=db, usuario=dono)

    # As três usinas com manutenção × 12 meses. O número está escrito para ninguém
    # "consertar" este teste esvaziando a carteira.
    comparadas = [k for k in sem if k[0] != "UFV Leme"]
    assert len(comparadas) == 36
    for chave in comparadas:
        assert sem[chave] == _marcas(com)[chave], f"a cor mudou por causa do documento em {chave}"

    # E a oferta chegou de fato — senão o teste acima passaria por não haver documento.
    agosto = _celula(com, "Porto Ferreira", "2026-08")
    assert [(m.tipo, m.relatorio_id) for m in agosto.manutencao.mensais] == [
        ("executivo", 61),
        ("tecnico", 14),
    ]


async def test_documento_de_mes_fora_do_contrato_nao_some_da_grade(db, dono, monkeypatch):
    """O DEFEITO: o relatório entregue desaparecer quando a vigência vira.

    `meses_estado` cobre a janela do contrato ATUAL (aqui, agosto a dezembro de 2026). Um
    relatório de **julho** é real — o meuPlano gera todo mês para quem tem contrato — e a
    célula de julho não tem bloco de manutenção. Sem tratamento, o documento sumiria da
    grade do ano em que ele foi entregue. O bloco nasce trazendo SÓ o documento: nenhuma
    situação, nenhum previsto, nenhum cumprido — logo, nenhuma conta e nenhuma cor.
    """
    _montar(monkeypatch, MeuPlanoFalso())
    saida = await grade_do_ano(ano=2026, db=db, usuario=dono)

    julho = _celula(saida, "Porto Ferreira", "2026-07")
    assert julho.manutencao is not None, "o relatório de julho sumiria da grade"
    assert [(m.tipo, m.relatorio_id) for m in julho.manutencao.mensais] == [
        ("executivo", 10),
        ("tecnico", 9),
    ]
    # E o bloco não inventa conformidade nenhuma para um mês fora do contrato.
    assert julho.manutencao.situacao is None
    assert julho.manutencao.previsto is None
    assert julho.manutencao.cumprido is None

    # Um mês sem contrato E sem documento continua sem bloco algum.
    assert _celula(saida, "Porto Ferreira", "2026-03").manutencao is None


async def test_a_falha_do_mensal_nao_vira_frase_de_cronograma(db, dono, monkeypatch):
    """O DEFEITO: o motivo de uma família viajar no campo de outra.

    Já aconteceu neste módulo: o aplicativo arrancava o prefixo "Manutenção:" com
    expressão regular e mostrava a frase nas duas abas. "Não deu para buscar o relatório
    mensal" e "a equipe ainda não publicou o cronograma" respondem a perguntas diferentes,
    e quem lê a segunda achando que é a primeira conclui que a manutenção não foi feita.
    """
    _montar(monkeypatch, MeuPlanoFalso(derruba=2))
    saida = await grade_do_ano(ano=2026, db=db, usuario=dono)

    pereiras = _usina(saida, "Pereiras")
    assert pereiras.aviso_mensais and "Pereiras" in pereiras.aviso_mensais
    # O cronograma dela também falha (não tem consolidado) — e a frase é OUTRA.
    assert "relatórios mensais" not in (pereiras.aviso_manutencao or "")

    porto = _usina(saida, "Porto Ferreira")
    assert porto.aviso_mensais is None, "a queda de uma usina não contamina as outras"
    assert porto.aviso_manutencao is None
    assert _celula(saida, "Porto Ferreira", "2026-08").manutencao.mensais


# ── 5. dois documentos, uma ordem só ────────────────────────────────────────


async def test_executivo_antes_do_tecnico_e_o_mes_mais_novo_primeiro(db, dono, cenario):
    """O DEFEITO: cada frente escolher a sua ordem.

    A diretoria é o destino que o próprio meuPlano declara para o executivo ("nível gestor
    que tem cinco minutos"); o técnico é o laudo. Duas ordens dariam duas respostas para a
    mesma pergunta — e o cenário entrega o técnico primeiro de propósito, para provar que
    quem ordena é este lado.
    """
    saida = await meus_documentos(None, db, dono)

    porto = [(r.competencia, r.tipo) for r in saida.mensais if r.usina == "Porto Ferreira"]
    assert porto == [
        ("2026-08", "executivo"),
        ("2026-08", "tecnico"),
        ("2026-07", "executivo"),
        ("2026-07", "tecnico"),
    ]


async def test_os_dois_documentos_de_uma_usina_ficam_juntos(db, dono, cenario):
    """O DEFEITO: ordenar por TIPO antes de por usina, e partir o cartão ao meio.

    Os dois documentos de um mês são **um cartão com duas linhas** — é a forma que o
    aplicativo já desenha em `PECAS`/`detalheDaPeca`. Uma ordem por tipo primeiro daria
    "executivo de Porto Ferreira, técnico de Pereiras, técnico de Porto Ferreira" na mesma
    faixa de agosto, e a segunda linha do cartão apareceria embaixo do cartão de outra
    usina.
    """
    saida = await meus_documentos(None, db, dono)
    de_agosto = [(r.usina, r.tipo) for r in saida.mensais if r.competencia == "2026-08"]
    assert de_agosto == [
        ("Pereiras", "tecnico"),
        ("Porto Ferreira", "executivo"),
        ("Porto Ferreira", "tecnico"),
    ]
    # Nenhuma usina aparece em dois blocos separados dentro do mesmo mês.
    nomes = [u for u, _ in de_agosto]
    assert len(set(nomes)) == len([i for i, n in enumerate(nomes) if i == 0 or n != nomes[i - 1]])


async def test_a_ordem_e_estavel_entre_chamadas_iguais(db, dono, cenario):
    """O DEFEITO: uma ordem que dependa da chegada das respostas em paralelo.

    A etiqueta da resposta é o sha256 do corpo. Se a ordem oscilasse, o `ETag` mudaria sem
    nada ter mudado, a revalidação nunca daria 304 — e ninguém descobriria, porque a tela
    continuaria certa e só a rede continuaria cara.
    """
    a = await meus_documentos(None, db, dono)
    b = await meus_documentos(None, db, dono)
    assert [(r.usina, r.competencia, r.tipo) for r in a.mensais] == [
        (r.usina, r.competencia, r.tipo) for r in b.mensais
    ]
    assert a.model_dump_json() == b.model_dump_json()


# ── 6. escopo e identidade dos ids ──────────────────────────────────────────


async def test_o_usina_id_do_mensal_e_o_do_vinculo_nao_o_do_meuplano(db, dono, carteira, cenario):
    """O DEFEITO: devolver o id do meuPlano num campo que a tela usa como id do vínculo.

    Os dois são inteiros pequenos. Trocá-los abriria a usina errada sem erro nenhum — a
    tela pediria `/manutencao/ordens?usina_id=1` achando que é Porto Ferreira. O acervo do
    cenário traz `usina_id` do meuPlano em cada item, e ele **não** pode ser o que sai.
    """
    porto = next(l for l in carteira if l.nome == "Porto Ferreira")
    saida = await meus_documentos(None, db, dono)

    do_porto = [r for r in saida.mensais if r.usina == "Porto Ferreira"]
    assert do_porto
    assert {r.usina_id for r in do_porto} == {porto.id}
    # O id do relatório, esse sim, é o do meuPlano — é ele que a rota do PDF aceita.
    assert {r.id for r in do_porto} == {14, 61, 9, 10}


async def test_o_filtro_por_usina_recorta_o_mensal_tambem(db, dono, carteira, monkeypatch):
    """O DEFEITO: o `?usina_id=` recortar só a geração e devolver o mensal da carteira toda.

    A tela de Relatórios do portal do cliente é por usina. Um acervo mensal que ignorasse o
    filtro poria os documentos de outra usina na tela desta — e ainda pagaria as sete idas
    ao meuPlano que o filtro existe para evitar.
    """
    plano = _montar(monkeypatch, MeuPlanoFalso())
    pereiras = next(l for l in carteira if l.nome == "Pereiras")
    saida = await meus_documentos(pereiras.id, db, dono)

    assert {r.usina for r in saida.mensais} == {"Pereiras"}
    assert [r.id for r in saida.mensais] == [84]
    assert plano.pedidos == [2], "perguntou só à usina pedida"


async def test_usina_fora_do_escopo_e_404_antes_de_qualquer_ida(db, dono, monkeypatch):
    """O DEFEITO: a família nova furar a barreira que é a razão de existir deste módulo.

    404 e não 403 — "proibido" confirmaria que a usina existe. E antes de qualquer ida à
    rede: quem trocou o número na URL não pode nem provocar tráfego em nome de outro.
    """
    plano = _montar(monkeypatch, MeuPlanoFalso())
    with pytest.raises(HTTPException) as e:
        await meus_documentos(987654, db, dono)
    assert e.value.status_code == 404
    assert plano.pedidos == []


async def test_usina_sem_manutencao_nao_e_perguntada_nem_vira_aviso(db, dono, carteira, monkeypatch):
    """O DEFEITO: tratar "não tem manutenção contratada" como falha.

    Não é: é ausência de contrato. UFV Leme não tem nenhuma das duas pontes — a geração
    avisa que falta monitoramento, e o mensal simplesmente não pergunta nem inventa frase.
    """
    plano = _montar(monkeypatch, MeuPlanoFalso())
    leme = next(l for l in carteira if l.nome == "UFV Leme")
    saida = await meus_documentos(leme.id, db, dono)

    assert saida.mensais == []
    assert saida.aviso_mensais is None
    assert plano.pedidos == []
    # A geração continua explicando a ausência DELA, com o vocabulário do cliente.
    assert saida.aviso and "monitoramento" in saida.aviso
    assert "meuWatt" not in saida.aviso


async def test_a_frase_da_geracao_nao_muda_numa_carteira_de_uma_usina(db, monkeypatch):
    """O DEFEITO: deduzir "veio filtro?" do TAMANHO da lista de usinas.

    A separação das duas famílias partiu a listagem em duas funções, e a interna recebe
    `links` já recortado. Inferir o recorte de `len(links) == 1` faz a frase trocar para
    quem tem **uma** usina e não pediu filtro nenhum — o aplicativo já tem "nenhuma das
    suas usinas" gravado em cache, e a mudança chegaria sem ninguém ter pedido.
    """
    sozinha = PlantLink(mw_plant_slug=None, mp_usina_id=None, nome="Única")
    db.add(sozinha)
    db.commit()
    u = User(
        apelido="so-uma",
        email="so-uma@exemplo.com.br",
        nome="Uma",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    db.add(UserPlantAccess(user_id=u.id, plant_link_id=sozinha.id))
    db.commit()
    _montar(monkeypatch, MeuPlanoFalso())

    sem_filtro = await meus_documentos(None, db, u)
    assert sem_filtro.aviso.startswith("Nenhuma das suas usinas")

    com_filtro = await meus_documentos(sozinha.id, db, u)
    assert com_filtro.aviso.startswith("Esta usina")


# ── 7. quem chama por dentro não paga a segunda ida ─────────────────────────


async def test_autorizar_um_download_nao_custa_uma_ida_por_usina(db, dono, monkeypatch):
    """O DEFEITO: cada PDF de geração passar a custar sete round-trips ao meuPlano.

    `arquivo_do_documento` chama a listagem só para refazer a autorização — e o acervo
    mensal não diz nada sobre um PDF de geração. A grade do ano tem o mesmo problema pelo
    outro lado: ela pede o mensal por conta própria, e chamar a rota inteira buscaria a
    mesma família duas vezes no mesmo pedido.
    """
    plano = _montar(monkeypatch, MeuPlanoFalso())

    saida = await documentos_de_geracao(None, db, dono)
    assert [d.id for d in saida.documentos] == [35, 36]
    assert saida.mensais == []
    assert plano.pedidos == [], "autorizar um download não pode ir ao meuPlano"

    from app.api.v1.documents import arquivo_do_documento

    with pytest.raises(HTTPException) as e:
        await arquivo_do_documento(9, "geracao", db, dono)  # documento de outro cliente
    assert e.value.status_code == 404
    assert plano.pedidos == []


async def test_a_grade_do_ano_pergunta_uma_vez_por_usina(db, dono, monkeypatch):
    """O DEFEITO: buscar o acervo mensal duas vezes no mesmo pedido.

    A grade compõe a geração e o mensal por dentro. Se ela chamasse a rota `/documents`
    (que já compõe o mensal) e ainda fizesse o fan-out dela, seriam catorze idas ao
    meuPlano onde bastam sete — numa tela que o dono abre no carro.
    """
    plano = _montar(monkeypatch, MeuPlanoFalso())
    await grade_do_ano(ano=2026, db=db, usuario=dono)
    assert sorted(plano.pedidos) == [1, 2, 6]


# ── 8. o item malformado não vira card que não abre ─────────────────────────


@pytest.mark.parametrize(
    "quebrado",
    [
        {"usina_id": 1, "competencia": "2026-08", "tipo": "tecnico"},  # sem id
        {"id": 5, "usina_id": 1, "tipo": "tecnico"},  # sem competência
        {"id": 5, "usina_id": 1, "competencia": "2026-08"},  # sem tipo
        {"id": 5, "usina_id": 1, "competencia": "2026-08", "tipo": "   "},  # tipo em branco
        "isto não é um objeto",
    ],
)
async def test_item_sem_identidade_nao_vira_card(db, dono, monkeypatch, quebrado):
    """O DEFEITO: desenhar um cartão cujo toque não abre nada.

    `id`, `competencia` e `tipo` são a identidade do documento: sem eles não há o que
    abrir, nem em que mês pendurar, nem como rotular. Descartar é a resposta — inventar um
    id ou um "mês desconhecido" seria número inventado (Regra 0).
    """
    _montar(monkeypatch, MeuPlanoFalso(acervo={1: [quebrado], 2: [], 6: []}))
    saida = await meus_documentos(None, db, dono)
    assert saida.mensais == []
    assert saida.aviso_mensais is None, "item malformado não é a usina fora do ar"


async def test_tipo_novo_do_meuplano_chega_a_tela(db, dono, monkeypatch):
    """O DEFEITO: um mapa deste lado engolir um terceiro tipo de relatório.

    `tipo` é repassado CRU e só a ORDEM o conhece — o desconhecido vai para o fim da lista,
    depois do executivo e do técnico, mas chega. Um mapa que devolvesse `None` faria o
    documento novo do meuPlano sumir da tela sem ninguém saber por quê.
    """
    _montar(
        monkeypatch,
        MeuPlanoFalso(
            acervo={
                1: [
                    _liberado(70, 1, "2026-08", "ambiental"),
                    _liberado(14, 1, "2026-08", "tecnico"),
                    _liberado(61, 1, "2026-08", "executivo"),
                ],
                2: [],
                6: [],
            }
        ),
    )
    saida = await meus_documentos(None, db, dono)
    assert [r.tipo for r in saida.mensais] == ["executivo", "tecnico", "ambiental"]


def test_o_modelo_do_mensal_nao_aceita_ausencia_de_identidade():
    """Cinto do lado do formato: os três campos de identidade são obrigatórios.

    Se um dia alguém der um default a `competencia` ("") para "simplificar", o card volta a
    poder nascer sem mês — e o descarte de `_mensal_out` deixa de ser a última defesa.
    """
    with pytest.raises(Exception):
        RelatorioMensalOut(id=1, usina_id=1, usina="X", tipo="tecnico")  # sem competência
