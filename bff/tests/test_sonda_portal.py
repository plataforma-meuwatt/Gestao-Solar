"""A sonda vigiando a FORMA de `/reports/portal`.

O defeito que estes testes guardam é um ponto cego, não um erro de conta: `mw.portal`
estava com `sonda=False` — por uma razão boa, que continua verdadeira (com o token de
serviço a rota devolve a pré-visualização do gestor, e um verde ali não provaria que o
cliente enxerga os relatórios dele). A consequência é que a rota que sustenta a aba de
Relatórios inteira nunca era exercitada, e o modo de falha desta família é exatamente o
que passa por baixo do alarme: **200, um campo renomeado, a aba esvazia e nada acende**.
Se `files[].kind` virar `type` amanhã, a aba morre, a grade do ano fica sem eixo, e a
sonda continua verde.

Daí a linha ter voltado para a varredura declarando o contrato de forma que o BFF lê em
`api/v1/documents.py`. O que estes testes travam:

- que a rota é chamada de verdade, e os 9 campos aparecem conferidos na tela;
- que a falta de um deles é **vermelho com o nome escrito** — a prova de que reprova;
- que fechamento sem arquivo publicado **não** é vermelho (é estado real: medido em
  05/09/2026, 2 de 7 fechamentos tinham peça);
- que o verde continua não prometendo o recorte do cliente — esse é do BFF.
"""

import pytest
import respx
from cryptography.fernet import Fernet

from app.core import cripto
from app.models.integracao import Integracao, Produto
from app.services import sonda
from tests.test_sonda import BASE, MW, PORTAL_COMO_HOJE, _tudo_responde

#: Os 9 campos de que o BFF depende, um por um. Escritos aqui à mão de propósito: se
#: alguém tirar um do catálogo por engano, este teste diz qual sumiu — se ele lesse a
#: própria tupla do catálogo, concordaria com o engano.
OS_NOVE = [
    "reports[].id",
    "reports[].plant_slug",
    "reports[].period",
    "reports[].date_from",
    "reports[].date_to",
    "reports[].sent_at",
    "reports[].files[].kind",
    "reports[].files[].filename",
    "reports[].files[].size_bytes",
]


@pytest.fixture(autouse=True)
def _chave_de_teste(monkeypatch):
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))


@pytest.fixture
def conectado(db):
    linha = Integracao(
        produto=Produto.MEUWATT,
        base_url=BASE,
        token_cifrado=cripto.cifrar(MW),
        token_prefixo="mw_pat_1xNq",
        ativa=True,
    )
    db.add(linha)
    db.commit()
    return linha


async def _portal(db, conectado, corpo):
    """Varre com `/reports/portal` respondendo `corpo`, e devolve a linha dela."""
    _tudo_responde(respx.mock)
    respx.mock.get(f"{BASE}/reports/portal").respond(200, json=corpo)
    v = await sonda.varrer(db, Produto.MEUWATT)
    return next(r for r in v.rotas if r.chave == "mw.portal"), v


def test_a_rota_do_portal_declara_os_nove_campos_do_bff():
    """O catálogo é o contrato escrito. Sem esta lista, a linha voltaria para a varredura
    conferindo só o envelope `{plants, reports}` — que é 200 mesmo quando tudo por dentro
    mudou de nome."""
    rota = next(r for r in sonda.MEUWATT if r.chave == "mw.portal")

    assert rota.sonda, "a rota que sustenta a aba de Relatórios não pode ficar fora"
    assert not rota.essencial, "forma quebrada é alarme, não ponte caída"
    assert list(rota.campos_exigidos) == OS_NOVE


@respx.mock
async def test_o_portal_e_exercitado_e_os_nove_campos_aparecem_conferidos(db, conectado):
    """Antes desta mudança a linha era `nao_sondada` e nada ia para a rede. Agora vai — e
    o que a tela mostra são os campos conferidos, não o envelope."""
    alvo, _ = await _portal(db, conectado, PORTAL_COMO_HOJE)

    assert alvo.situacao == "ok", alvo.detalhe
    assert alvo.status == 200
    assert alvo.campos == OS_NOVE
    assert "9 campos" in alvo.detalhe
    # A prova de que saiu para a rede — o oposto exato do teste que a guardava antes.
    assert any("/reports/portal" in str(c.request.url) for c in respx.mock.calls)


@respx.mock
@pytest.mark.parametrize("campo", ["size_bytes", "kind", "filename"])
async def test_campo_que_some_do_arquivo_pinta_vermelho_com_o_nome(db, conectado, campo):
    """A prova de que REPROVA. Tirar `size_bytes` de uma resposta simulada — o campo que o
    BFF ainda nem consome, e que a tela vai mostrar para quem está no 3G — tem de deixar a
    linha vermelha nomeando o campo, não verde por descuido."""
    corpo = {
        "plants": PORTAL_COMO_HOJE["plants"],
        "reports": [
            {**r, "files": [{k: v for k, v in f.items() if k != campo} for f in r["files"]]}
            for r in PORTAL_COMO_HOJE["reports"]
        ],
    }

    alvo, v = await _portal(db, conectado, corpo)

    assert alvo.situacao == "falhou"
    assert f"reports[].files[].{campo}" in alvo.detalhe
    assert "forma mudou" in alvo.detalhe
    # Secundária: a forma quebrada acende o alarme sem declarar a ponte caída.
    assert v.ok and "secundárias" in v.detalhe


@respx.mock
async def test_campo_que_some_do_fechamento_pinta_vermelho_com_o_nome(db, conectado):
    """Mesma prova um nível acima: `sent_at` é lido sem `.get` em `documents.py` — se ele
    virar outro nome, a aba inteira estoura no upstream. O 200 não pode continuar verde."""
    corpo = {
        "plants": PORTAL_COMO_HOJE["plants"],
        "reports": [
            {k: v for k, v in r.items() if k != "sent_at"}
            for r in PORTAL_COMO_HOJE["reports"]
        ],
    }

    alvo, _ = await _portal(db, conectado, corpo)

    assert alvo.situacao == "falhou"
    assert "reports[].sent_at" in alvo.detalhe
    # Só o que faltou é nomeado: os outros oito não entram na frase e viram ruído.
    assert "reports[].id" not in alvo.detalhe


@respx.mock
async def test_o_envelope_que_sumiu_nomeia_os_nove(db, conectado):
    """`reports` renomeado é o pior caso — e o único em que `_resumir` sozinho já via algo
    estranho. Aqui os nove entram na frase porque nenhum sobrou."""
    alvo, _ = await _portal(db, conectado, {"plants": [], "fechamentos": []})

    assert alvo.situacao == "falhou"
    for caminho in OS_NOVE:
        assert caminho in alvo.detalhe


@respx.mock
async def test_fechamento_sem_arquivo_publicado_nao_e_vermelho(db, conectado):
    """O estado real do acervo, e o falso alarme que ele produziria. Medido em 05/09/2026:
    2 de 7 fechamentos tinham peça — se ninguém publicar PDF nenhum, isso é decisão de
    quem publica, não forma quebrada. A linha fica verde e DIZ o que não deu para conferir,
    em vez de mentir que conferiu."""
    corpo = {
        "plants": PORTAL_COMO_HOJE["plants"],
        "reports": [{**r, "files": []} for r in PORTAL_COMO_HOJE["reports"]],
    }

    alvo, _ = await _portal(db, conectado, corpo)

    assert alvo.situacao == "ok"
    assert "não veio nenhum item nesse nível" in alvo.detalhe
    assert "reports[].files[].kind" in alvo.detalhe
    # Os seis do fechamento foram conferidos de verdade; os três do arquivo, não.
    assert alvo.campos == OS_NOVE[:6]


@respx.mock
async def test_acervo_vazio_nao_e_vermelho_mas_e_dito(db, conectado):
    """Sem nenhum fechamento não há forma a conferir. Vermelho aqui mandaria investigar o
    meuWatt por causa de uma conta nova."""
    alvo, _ = await _portal(db, conectado, {"plants": [], "reports": []})

    assert alvo.situacao == "ok"
    assert "não veio nenhum item nesse nível" in alvo.detalhe
    # Sem nada conferido, o retrato volta a ser o do envelope: quem lê a tela vê que a
    # resposta chegou e estava vazia, em vez de uma lista de campos em branco que se
    # confundiria com "a rota não respondeu".
    assert alvo.campos == ["plants", "reports"]


@respx.mock
async def test_um_fechamento_com_arquivo_basta_para_conferir(db, conectado):
    """A varredura procura um item que resolva o caminho, e não julga pelo primeiro da
    lista. Sem isso, o acervo real (o fechamento mais antigo é o sem peça) daria "não deu
    para conferir" para sempre, e os três campos do arquivo nunca seriam vigiados."""
    assert PORTAL_COMO_HOJE["reports"][0]["files"] == [], (
        "o primeiro fechamento do cenário tem de ser o SEM arquivo — é o que dá sentido "
        "a este teste"
    )

    alvo, _ = await _portal(db, conectado, PORTAL_COMO_HOJE)

    assert alvo.situacao == "ok" and alvo.campos == OS_NOVE


@respx.mock
async def test_valor_de_cliente_nao_atravessa_para_a_tela(db, conectado):
    """A sonda vigia forma. O nome do arquivo, o slug da usina e o peso em bytes ficam do
    lado de lá — a tela de infraestrutura mostra os caminhos conferidos, não o conteúdo."""
    alvo, _ = await _portal(db, conectado, PORTAL_COMO_HOJE)

    retrato = " ".join(alvo.campos) + " " + (alvo.detalhe or "")
    for valor in ("porto-ferreira", "geracao.pdf", "2686172", "Agosto/2026"):
        assert valor not in retrato


@respx.mock
async def test_o_verde_nao_promete_o_recorte_do_cliente(db, conectado):
    """O que este verde NÃO prova, escrito em teste para não se perder no comentário: a
    resposta que a sonda aprova é a do gestor, com fechamentos de usinas que não são desta
    conta. O corte por `mw_plant_slug` é do BFF, e é o `documents.py` que o faz."""
    corpo = {
        "plants": PORTAL_COMO_HOJE["plants"],
        "reports": [
            *PORTAL_COMO_HOJE["reports"],
            {**PORTAL_COMO_HOJE["reports"][1], "id": 99, "plant_slug": "usina-de-outro"},
        ],
    }

    alvo, _ = await _portal(db, conectado, corpo)

    # Verde com um fechamento de OUTRA usina no meio: a sonda não sabe, e não deve saber.
    assert alvo.situacao == "ok"
    assert "usina-de-outro" not in " ".join(alvo.campos) + " " + (alvo.detalhe or "")
    # E ela não conta fechamentos: `itens` fica vazio para esta rota, de modo que a linha
    # não possa ser lida como "o cliente tem N relatórios" — que seria três, e é errado.
    assert alvo.itens is None
    # A rota é secundária justamente porque o verde dela é sobre forma, não sobre escopo.
    assert not next(r for r in sonda.MEUWATT if r.chave == "mw.portal").essencial


def test_a_forma_declarada_nao_criou_rota_nova_no_catalogo():
    """A vigilância entrou sem inventar chamada nenhuma: o cliente não ganhou método novo,
    e o teste inverso por AST (`test_sonda.py`) continua valendo sem linha nova."""
    from app.clients import meuwatt

    from tests.test_sonda import _fora_do_catalogo

    assert _fora_do_catalogo(meuwatt, sonda.MEUWATT) == set()
    assert len([r for r in sonda.MEUWATT if r.chave == "mw.portal"]) == 1
