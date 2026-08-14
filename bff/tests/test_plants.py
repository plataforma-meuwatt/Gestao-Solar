"""As usinas do dono: quem enxerga o quê, e que cor a usina ganha.

Duas coisas são testadas aqui porque as duas são silenciosas quando quebram. O escopo
erra para o lado de mostrar a usina de outro cliente — ninguém reclama, porque quem viu
demais não sabe que viu. E o tom erra para o lado do verde: uma usina que parou de
comunicar aparece "Gerando" e o dono só descobre na conta de luz.

Nada de rede: os upstreams não entram, e o que se exercita é a regra que mora no BFF.
"""

import pytest

from app.api.v1.plants import UsinaOut, _tom, _usina_no_escopo, usinas_do_usuario
from app.core.security import gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from fastapi import HTTPException


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


# ── escopo ──────────────────────────────────────────────────────────────────


def test_ve_apenas_as_usinas_concedidas(db, dono, usinas):
    a, b = usinas
    _conceder(db, dono, a)

    visiveis = usinas_do_usuario(db, dono)

    assert [u.id for u in visiveis] == [a.id]


def test_sem_concessao_nao_ve_nada(db, dono, usinas):
    assert usinas_do_usuario(db, dono) == []


def test_usina_desligada_no_painel_sai_do_aplicativo(db, dono, usinas):
    """`PlantLink.ativo` é o interruptor do gestor: desligar tira do app sem mexer nas
    concessões — e sem elas serem perdidas quando religar."""
    a, _ = usinas
    _conceder(db, dono, a)
    a.ativo = False
    db.commit()

    assert usinas_do_usuario(db, dono) == []

    a.ativo = True
    db.commit()
    assert [u.id for u in usinas_do_usuario(db, dono)] == [a.id]


def test_usina_de_outro_cliente_responde_404_e_nao_403(db, dono, usinas):
    """403 confirmaria que aquela usina existe. Quem troca o número na URL não pode
    aprender nada com a resposta."""
    a, b = usinas
    _conceder(db, dono, a)

    with pytest.raises(HTTPException) as erro:
        _usina_no_escopo(db, dono, b.id)

    assert erro.value.status_code == 404


def test_usina_inexistente_responde_igual_a_usina_alheia(db, dono, usinas):
    """As duas negativas têm de ser indistinguíveis, senão a diferença vira um oráculo
    de quais ids existem."""
    a, b = usinas
    _conceder(db, dono, a)

    with pytest.raises(HTTPException) as alheia:
        _usina_no_escopo(db, dono, b.id)
    with pytest.raises(HTTPException) as fantasma:
        _usina_no_escopo(db, dono, 99999)

    assert alheia.value.status_code == fantasma.value.status_code
    assert alheia.value.detail == fantasma.value.detail


def test_usina_concedida_passa_pelo_escopo(db, dono, usinas):
    a, _ = usinas
    _conceder(db, dono, a)

    assert _usina_no_escopo(db, dono, a.id).id == a.id


# ── tom ─────────────────────────────────────────────────────────────────────


def _usina(**campos) -> UsinaOut:
    base = dict(id=1, nome="Teste", tom="", situacao="", tem_meuwatt=True, tem_meuplano=True)
    return UsinaOut(**{**base, **campos})


def test_sem_comunicacao_nunca_fica_verde():
    """A regressão que importa: potência nula é "não sabemos", e "não sabemos" não pode
    ser desenhado como usina saudável."""
    tom, situacao = _tom(_usina(potencia_kw=None))

    assert tom == "semDados"
    assert situacao == "Sem comunicação"


def test_disponibilidade_baixa_fica_vermelha_mesmo_gerando():
    """Gerar não é estar bem: metade dos inversores fora ainda produz número positivo."""
    tom, _ = _tom(_usina(potencia_kw=120.0, disponibilidade_pct=40.0))

    assert tom == "parado"


def test_potencia_zero_e_sem_geracao_e_nao_falha():
    """De noite toda usina marca zero. Vermelho aqui seria alarme falso diário."""
    tom, situacao = _tom(_usina(potencia_kw=0.0))

    assert tom == "semDados"
    assert situacao == "Sem geração agora"


def test_geracao_parcial_alerta():
    tom, _ = _tom(_usina(potencia_kw=100.0, disponibilidade_pct=75.0))

    assert tom == "alerta"


def test_usina_saudavel_fica_verde():
    tom, situacao = _tom(_usina(potencia_kw=100.0, disponibilidade_pct=98.0))

    assert tom == "ok"
    assert situacao == "Gerando"


def test_gerando_sem_disponibilidade_conhecida_ainda_e_ok():
    """O meuPlano pode não ter respondido a disponibilidade. Potência positiva basta para
    dizer que está gerando — o que não se sabe não vira alarme."""
    tom, _ = _tom(_usina(potencia_kw=100.0, disponibilidade_pct=None))

    assert tom == "ok"


def test_todo_tom_existe_nos_tokens_do_aplicativo():
    """O contrato de verdade dos tons é `app/src/theme/tokens.ts`: a tela faz `tons[tom]`,
    e um nome que não existe lá não pinta cor errada — não pinta cor nenhuma. Este teste
    lê o arquivo do app porque a régua mora nele, não aqui.

    Foi assim que `sem-dados` apareceu: nome plausível, quatro telas sem cor.
    """
    import re
    from pathlib import Path

    tokens = Path(__file__).resolve().parents[2] / "app" / "src" / "theme" / "tokens.ts"
    bloco = re.search(r"export const tons = \{(.*?)\n\}", tokens.read_text("utf-8"), re.S)
    assert bloco, "o bloco `export const tons` sumiu de tokens.ts — o contrato mudou de lugar"
    conhecidos = set(re.findall(r"^\s*(\w+):", bloco.group(1), re.M))

    casos = [
        _usina(potencia_kw=None),
        _usina(potencia_kw=0.0),
        _usina(potencia_kw=120.0, disponibilidade_pct=40.0),
        _usina(potencia_kw=100.0, disponibilidade_pct=75.0),
        _usina(potencia_kw=100.0, disponibilidade_pct=98.0),
    ]
    emitidos = {_tom(u)[0] for u in casos}

    assert emitidos <= conhecidos, f"tons sem cor no app: {sorted(emitidos - conhecidos)}"


# ── o formato que o meuWatt manda ───────────────────────────────────────────


def test_potencia_soma_os_inversores_e_converte_para_kw():
    """`monitoring/current` NÃO traz total da usina — traz `inverters[]`, cada um com
    `active_power` em watts (`InverterMonitoring` no mw-api).

    A primeira versão desta leitura procurava `total_power_kw` no topo da resposta. O
    campo não existe, então toda usina saía com potência nula e a tela inteira dizia
    "Sem comunicação" — com o meuWatt respondendo normalmente.
    """
    from app.api.v1.plants import _potencia_da_usina

    resposta = {"inverters": [{"active_power": 92400.0}, {"active_power": 88100.0}]}

    assert _potencia_da_usina(resposta) == 180.5


def test_sem_inversores_a_potencia_e_nula_e_nao_zero():
    from app.api.v1.plants import _potencia_da_usina

    assert _potencia_da_usina({"inverters": []}) is None
    assert _potencia_da_usina({}) is None


def test_inversor_sem_leitura_nao_derruba_a_soma():
    """Um inversor mudo não zera a usina: soma o que veio e segue."""
    from app.api.v1.plants import _potencia_da_usina

    resposta = {"inverters": [{"active_power": 50000.0}, {"active_power": None}]}

    assert _potencia_da_usina(resposta) == 50.0


def test_apenas_falha_e_comunicacao_contam_como_parado():
    """`bedtime` é a usina dormindo, e `alert` é aviso com o inversor gerando. Contar
    qualquer um dos dois pintaria a tela de vermelho todo fim de tarde."""
    from app.api.v1.plants import _parados

    inversores = [
        {"status": "normal"},
        {"status": "alert"},
        {"status": "bedtime"},
        {"status": "fault"},
        {"status": "communication_error"},
    ]

    assert _parados(inversores) == 2


def test_estados_conferem_com_a_lista_do_mw_api():
    """A régua é o schema do produto de origem, não a memória de quem escreveu isto.

    Se o mw-api renomear um estado, este teste falha aqui em vez de a contagem de
    inversores parados silenciosamente virar zero em produção.
    """
    import re
    from pathlib import Path

    from app.api.v1.plants import DORMINDO, PARADO

    schema = Path("C:/dev/meuWatt/mw-api/src/monitoring/schemas.py")
    if not schema.exists():
        pytest.skip("mw-api não está ao lado; a régua só existe na máquina de quem tem os dois")

    linha = re.search(r"status: str\s*#\s*(.+)", schema.read_text("utf-8"))
    assert linha, "o comentário com os estados sumiu de InverterMonitoring.status"
    conhecidos = set(re.findall(r'"(\w+)"', linha.group(1)))

    assert PARADO <= conhecidos, f"estado que o mw-api não conhece: {sorted(PARADO - conhecidos)}"
    assert DORMINDO in conhecidos


# ── pelo HTTP, como o aplicativo chama ──────────────────────────────────────


@pytest.fixture
def cliente_http(db):
    """A API de verdade, com o banco do teste no lugar do Postgres.

    Aqui os upstreams **não** estão configurados, e é de propósito: é o cenário em que a
    ponte está fora do ar. A promessa escrita no módulo é que isso não derruba a resposta,
    e promessa que ninguém exercita é decoração.
    """
    from fastapi.testclient import TestClient

    from app.core.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _autenticado(cliente, usuario):
    from app.core.security import criar_token

    token, _ = criar_token(usuario.id)
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


def test_sem_token_nao_lista_usina(cliente_http):
    assert cliente_http.get("/api/v1/plants").status_code in (401, 403)


def test_ponte_fora_do_ar_ainda_entrega_a_lista(cliente_http, db, dono, usinas):
    """Meia tela com aviso honesto é melhor do que tela de erro — e muito melhor do que
    tela de zeros, que se lê como "não gerou nada"."""
    a, _ = usinas
    _conceder(db, dono, a)

    r = _autenticado(cliente_http, dono).get("/api/v1/plants")

    assert r.status_code == 200
    corpo = r.json()
    assert [u["nome"] for u in corpo["usinas"]] == ["Porto Ferreira"]

    usina = corpo["usinas"][0]
    assert usina["tom"] == "semDados"
    assert usina["potencia_kw"] is None, "sem upstream o campo é nulo, jamais 0"
    assert corpo["potencia_agora_kw"] is None
    assert corpo["aviso"], "a tela precisa poder dizer por que os números não vieram"


def test_lista_vazia_explica_o_motivo(cliente_http, dono):
    r = _autenticado(cliente_http, dono).get("/api/v1/plants")

    assert r.status_code == 200
    assert r.json()["usinas"] == []
    assert "concedida" in r.json()["aviso"]


def test_detalhe_de_usina_alheia_responde_404(cliente_http, db, dono, usinas):
    a, b = usinas
    _conceder(db, dono, a)

    cliente = _autenticado(cliente_http, dono)

    assert cliente.get(f"/api/v1/plants/{a.id}").status_code == 200
    assert cliente.get(f"/api/v1/plants/{b.id}").status_code == 404
