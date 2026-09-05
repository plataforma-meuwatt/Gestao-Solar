"""A sonda de rotas.

Ela existe para separar quatro coisas que, sem ela, chegam ao gestor como o mesmo silêncio:
a rota que respondeu, a que sumiu do produto, a que não pôde ser testada por falta de um
parâmetro, e a que decidimos não chamar. Confundir qualquer duas delas manda alguém
investigar a coisa errada — daí os testes serem, quase todos, sobre a classificação.
"""

from datetime import date

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.core import cripto
from app.models.integracao import Integracao, IntegracaoEvento, Produto
from app.services import sonda

BASE = "https://api.meuwatt.test"
MW = "mw_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"


@pytest.fixture(autouse=True)
def _chave_de_teste(monkeypatch):
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))


@pytest.fixture
def conectado(db):
    """Uma ponte com o meuWatt já conectada por token."""
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


def _tudo_responde(mock):
    """O caminho feliz: as duas rotas de descoberta e o resto em cima do slug achado."""
    mock.get(f"{BASE}/auth/me").respond(
        200, json={"name": "Fulano", "email": "fulano@empresa.com.br"}
    )
    mock.get(f"{BASE}/plants").respond(200, json=[{"slug": "porto-ferreira", "name": "Porto"}])
    # A lista de slots antes do curinga (o respx casa na ordem de registro): é dela que
    # sai o `slot_id` da rota de detalhe — sem um item com `id`, a dependente fica pulada.
    mock.get(f"{BASE}/plants/porto-ferreira/slots").respond(
        200, json=[{"id": 1, "label": "INV-01"}]
    )
    mock.route(url__startswith=f"{BASE}/plants/porto-ferreira").respond(
        200, json={"total_generation_kwh": 120.5}
    )
    mock.get(f"{BASE}/admin/users").respond(200, json=[{"id": 1, "email": "a@b.com"}])
    mock.get(f"{BASE}/admin/user-plants").respond(200, json=[{"user_id": 1, "plant_id": 1}])


@respx.mock
async def test_caminho_feliz_exercita_todas_e_passa(db, conectado):
    _tudo_responde(respx.mock)

    v = await sonda.varrer(db, Produto.MEUWATT)

    assert v.ok
    assert all(r.situacao == "ok" for r in v.rotas if r.situacao not in ("nao_sondada",))
    # Nenhuma pulada: `/plants` entregou o slug para as que dependem dele.
    assert not [r for r in v.rotas if r.situacao == "pulada"]


@respx.mock
async def test_o_slug_descoberto_alimenta_as_rotas_seguintes(db, conectado):
    """A ordem do catálogo é funcional, não estética: `/plants` precisa vir antes."""
    _tudo_responde(respx.mock)

    v = await sonda.varrer(db, Produto.MEUWATT)

    detalhe = next(r for r in v.rotas if r.chave == "mw.slots")
    assert "porto-ferreira" in detalhe.caminho and "{slug}" not in detalhe.caminho


@respx.mock
async def test_sem_slug_as_dependentes_ficam_puladas_e_nao_falhadas(db, conectado):
    """Uma lista vazia de usinas não é falha das rotas de usina — elas não chegaram a ser
    chamadas. Reportá-las como vermelhas mandaria investigar doze rotas saudáveis."""
    respx.mock.get(f"{BASE}/auth/me").respond(200, json={"email": "f@e.com"})
    respx.mock.get(f"{BASE}/plants").respond(200, json=[])
    respx.mock.get(f"{BASE}/admin/users").respond(200, json=[])
    respx.mock.get(f"{BASE}/admin/user-plants").respond(200, json=[])

    v = await sonda.varrer(db, Produto.MEUWATT)

    dependente = next(r for r in v.rotas if r.chave == "mw.slots")
    assert dependente.situacao == "pulada"
    assert "slug" in dependente.detalhe

    # E a lista vazia aparece escrita, porque é a causa comum de tela vazia sem erro.
    plants = next(r for r in v.rotas if r.chave == "mw.plants")
    assert plants.situacao == "ok" and "sem nenhum item" in plants.detalhe


@respx.mock
async def test_rota_que_sumiu_e_falha_essencial(db, conectado):
    """404 numa rota essencial é o caso que a sonda existe para pegar: token válido,
    conexão verde, e uma tela do app que abriria vazia."""
    _tudo_responde(respx.mock)
    # Mesmo padrão já registrado em `_tudo_responde`: o respx SUBSTITUI a rota no lugar
    # (mantendo a posição antes do curinga) em vez de acrescentar outra — é o que deixa
    # este 404 valer sem que o curinga de `/plants/porto-ferreira*` o engula.
    respx.mock.get(f"{BASE}/plants/porto-ferreira/slots").respond(404, json={"detail": "sumiu"})

    v = await sonda.varrer(db, Produto.MEUWATT)

    alvo = next(r for r in v.rotas if r.chave == "mw.slots")
    assert alvo.situacao == "falhou" and alvo.status == 404
    # A frase do produto é repassada, não reescrita.
    assert alvo.detalhe == "sumiu"
    assert not v.ok


@respx.mock
async def test_falha_secundaria_nao_derruba_a_ponte(db, conectado):
    """Faturas fora do ar é um recurso a menos, não uma ponte quebrada — e a diferença
    muda o que o gestor faz a seguir."""
    respx.mock.get(f"{BASE}/plants/porto-ferreira/utility-bills").respond(500)
    _tudo_responde(respx.mock)

    v = await sonda.varrer(db, Produto.MEUWATT)

    assert v.ok
    assert "secundárias" in v.detalhe


@respx.mock
async def test_a_fronteira_esta_no_catalogo_e_e_exercitada_com_o_ano(db, conectado):
    """`ssu-readers/monthly-totals` sustenta o 'medido na fronteira', a perda até o ponto
    de entrega e a conciliação com a conta de energia. Sem linha aqui, ela sumiria num
    deploy do meuWatt e o Painel abriria com três blocos escondidos, sem ninguém saber
    por quê. É secundária de propósito: usina sem medidor é estado normal."""
    fronteira = respx.mock.get(f"{BASE}/plants/porto-ferreira/ssu-readers/monthly-totals")
    fronteira.respond(200, json={"year": 2026, "by_month": {"8": 158.1}})
    _tudo_responde(respx.mock)

    v = await sonda.varrer(db, Produto.MEUWATT)

    alvo = next(r for r in v.rotas if r.chave == "mw.ssu_mensal")
    assert alvo.situacao == "ok" and not alvo.essencial
    # O ano vem do contexto da varredura, como as datas das outras rotas.
    assert fronteira.calls.last.request.url.params["year"] == str(date.today().year)


@respx.mock
async def test_as_rotas_com_efeito_colateral_nao_sao_chamadas(db, conectado):
    """Declaradas e não exercitadas, com o motivo. Omiti-las daria a impressão de que a
    lista está completa."""
    _tudo_responde(respx.mock)

    v = await sonda.varrer(db, Produto.MEUWATT)

    portal = next(r for r in v.rotas if r.chave == "mw.portal")
    assert portal.situacao == "nao_sondada" and portal.detalhe
    # A prova é o que NÃO foi para a rede.
    assert all("/reports/portal" not in str(c.request.url) for c in respx.mock.calls)


@respx.mock
async def test_a_forma_da_resposta_e_registrada_sem_o_conteudo(db, conectado):
    """Os campos aparecem; os valores, não. A sonda é ferramenta de infraestrutura — não
    tem por que despejar dado de geração de cliente na tela."""
    _tudo_responde(respx.mock)

    v = await sonda.varrer(db, Produto.MEUWATT)

    plants = next(r for r in v.rotas if r.chave == "mw.plants")
    assert set(plants.campos) == {"slug", "name"}
    assert plants.itens == 1
    assert "porto-ferreira" not in str(plants.campos)


async def test_sem_conexao_a_sonda_explica_em_vez_de_falhar(db):
    v = await sonda.varrer(db, Produto.MEUWATT)

    assert not v.ok and not v.rotas
    assert "não está configurada" in v.detalhe


async def test_conexao_por_senha_pede_token(db):
    """O caminho antigo não serve aqui: a sonda usa o token direto, sem sessão a renovar."""
    db.add(
        Integracao(
            produto=Produto.MEUPLANO,
            base_url=BASE,
            usuario_servico="servico@empresa.com",
            senha_cifrada=cripto.cifrar("segredo"),
            ativa=True,
        )
    )
    db.commit()

    v = await sonda.varrer(db, Produto.MEUPLANO)

    assert not v.ok and "token pessoal" in v.detalhe


@respx.mock
async def test_produto_fora_do_ar_nao_derruba_a_varredura(db, conectado):
    """Uma varredura que estoura na primeira recusa não diria quantas rotas estão fora."""
    respx.mock.route(host="api.meuwatt.test").mock(
        side_effect=httpx.ConnectError("sem rota para o host")
    )

    v = await sonda.varrer(db, Produto.MEUWATT)

    exercitadas = [r for r in v.rotas if r.situacao in ("ok", "falhou", "pulada")]
    assert exercitadas and not v.ok
    # As duas de descoberta falham de verdade; as dependentes ficam puladas por falta do
    # slug — nunca uma exceção subindo e apagando o relatório inteiro.
    assert next(r for r in v.rotas if r.chave == "mw.plants").situacao == "falhou"


def test_o_catalogo_cobre_o_que_os_clientes_chamam():
    """Uma rota usada em `clients/` e ausente do catálogo é um ponto cego: ela quebraria
    sem a sonda dizer nada. Este teste é o alarme quando alguém adiciona uma e esquece."""
    import inspect

    from app.clients import meuplano, meuwatt

    for modulo, catalogo in (
        (meuwatt, sonda.MEUWATT),
        (meuplano, sonda.MEUPLANO),
    ):
        fonte = inspect.getsource(modulo)
        # Só os caminhos fixos: os montados com f-string variável não dão para casar por
        # texto, e é justamente por isso que o catálogo é escrito à mão.
        for rota in catalogo:
            raiz = rota.caminho.split("{")[0].rstrip("/")
            assert raiz in fonte, f"{rota.caminho} não aparece em {modulo.__name__}"


# ----------------------------------------------------------------- o sentido inverso
#
# O teste acima confere catálogo → cliente e passa por PREFIXO: `/api/v1/meuacesso/tasks`
# casa com o fonte mesmo quando o cliente já chama `/tasks/{id}/ficha`, `/tasks/{id}/
# fotos/{fid}` e `/tasks/{id}/pdf/view` sem nenhuma delas constar. Foi assim que cinco
# rotas do meuPlano e uma do meuWatt viveram meses fora da sonda com o alarme "verde".
# Daí o inverso: todo caminho que o cliente monta tem de existir no catálogo.


def _caminhos_do_cliente(modulo) -> set[str]:
    """Os caminhos que o módulo monta, como MOLDES: `{...}` vira `{}`.

    Lidos da árvore sintática, não do texto: string constante que começa com `/` e
    f-string que começa com `/` ou com `{self.base_url}/`. Docstrings e comentários não
    entram — nenhum começa com barra —, então um exemplo citado numa explicação não vira
    falso positivo.
    """
    import ast
    import inspect
    import re

    def molde(no: ast.AST) -> str | None:
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            return no.value
        if isinstance(no, ast.JoinedStr):
            partes = []
            for pedaco in no.values:
                if isinstance(pedaco, ast.Constant):
                    partes.append(str(pedaco.value))
                else:
                    partes.append("{}")
            return "".join(partes)
        return None

    achados: set[str] = set()

    def visitar(no: ast.AST) -> None:
        texto = molde(no)
        if texto is not None:
            if texto.startswith("{}/"):
                texto = texto[2:]
            if re.match(r"^/[a-z]", texto):
                achados.add(re.sub(r"\{[^}]*\}", "{}", texto))
            # Uma f-string é um caminho só: descer nos pedaços dela renderia "/alerts"
            # e "/slots/" soltos, que não são rota nenhuma.
            return
        for filho in ast.iter_child_nodes(no):
            visitar(filho)

    visitar(ast.parse(inspect.getsource(modulo)))
    return achados


def _moldes_do_catalogo(catalogo) -> set[str]:
    import re

    return {re.sub(r"\{[^}]*\}", "{}", r.caminho) for r in catalogo}


def _fora_do_catalogo(modulo, catalogo) -> set[str]:
    return _caminhos_do_cliente(modulo) - _moldes_do_catalogo(catalogo)


def test_todo_caminho_do_cliente_esta_no_catalogo():
    """Cliente → catálogo, molde a molde. Uma rota nova no cliente sem linha aqui falha
    na hora, com o caminho escrito — não meses depois, na tela do cliente."""
    from app.clients import meuplano, meuwatt

    assert _fora_do_catalogo(meuwatt, sonda.MEUWATT) == set()
    assert _fora_do_catalogo(meuplano, sonda.MEUPLANO) == set()


def test_o_inverso_reprova_quando_uma_rota_some_do_catalogo():
    """A prova de que o teste acima pega o esquecimento: tirar UMA linha do catálogo faz
    exatamente o molde dela aparecer como fora."""
    from app.clients import meuplano

    alvo = next(r for r in sonda.MEUPLANO if r.chave == "mp.tarefa_ficha")
    sem_ela = [r for r in sonda.MEUPLANO if r is not alvo]

    assert _fora_do_catalogo(meuplano, sem_ela) == {"/api/v1/meuacesso/tasks/{}/ficha"}


# ── o cronograma do cliente na sonda ────────────────────────────────────────

MP_BASE = "https://api.meuplano.test"
MP = "mp_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"


@pytest.fixture
def meuplano_conectado(db):
    linha = Integracao(
        produto=Produto.MEUPLANO,
        base_url=MP_BASE,
        token_cifrado=cripto.cifrar(MP),
        token_prefixo="mp_pat_1xNq",
        ativa=True,
    )
    db.add(linha)
    db.commit()
    return linha


@respx.mock
async def test_o_cronograma_sondado_e_o_do_contrato_consolidado(db, meuplano_conectado):
    """A rota de cliente responde 404 para contrato só em rascunho. A sonda tem de escolher
    um contrato COM versão consolidada — senão o vermelho seria culpa da sonda, não do
    produto. Aqui o primeiro contrato da lista é rascunho de propósito."""
    respx.mock.get(f"{MP_BASE}/api/v1/meuacesso/usinas").respond(
        200, json=[{"id": 7, "name": "Porto Ferreira"}]
    )
    respx.mock.get(f"{MP_BASE}/api/v1/meuacesso/visao-cliente/usinas/7/contratos").respond(
        200,
        json=[
            {"id": 30, "numero": 300, "versao_consolidada": None},
            {"id": 20, "numero": 200, "versao_consolidada": 2},
        ],
    )
    cronograma = respx.mock.get(
        f"{MP_BASE}/api/v1/meuacesso/visao-cliente/usinas/7/cronograma"
    ).respond(200, json={"status": "CONSOLIDATED", "rows": []})
    # o resto do catálogo responde vazio — registrado por ÚLTIMO: o respx casa na ordem
    respx.mock.route(host="api.meuplano.test").respond(200, json={})

    v = await sonda.varrer(db, Produto.MEUPLANO)

    r = next(r for r in v.rotas if r.chave == "mp.cronograma")
    assert r.situacao == "ok", r.detalhe
    assert cronograma.calls.last.request.url.params["container_id"] == "20"
    # o PDF não é sondado, mas o caminho declarado já é o da visão do cliente
    pdf = next(r for r in v.rotas if r.chave == "mp.pdf_cronograma")
    assert pdf.situacao == "nao_sondada" and "visao-cliente" in pdf.caminho


@respx.mock
async def test_sem_contrato_consolidado_o_cronograma_fica_pulado(db, meuplano_conectado):
    respx.mock.get(f"{MP_BASE}/api/v1/meuacesso/usinas").respond(200, json=[{"id": 7}])
    respx.mock.get(f"{MP_BASE}/api/v1/meuacesso/visao-cliente/usinas/7/contratos").respond(
        200, json=[{"id": 30, "numero": 300, "versao_consolidada": None}]
    )
    respx.mock.route(host="api.meuplano.test").respond(200, json={})

    v = await sonda.varrer(db, Produto.MEUPLANO)

    r = next(r for r in v.rotas if r.chave == "mp.cronograma")
    assert r.situacao == "pulada" and "vc_container_id" in (r.detalhe or "")
