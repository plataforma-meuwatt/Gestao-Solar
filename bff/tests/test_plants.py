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
    base = dict(
        id=1, nome="Teste", tom="", situacao="", tem_meuwatt=True, tem_meuplano=True
    )
    return UsinaOut(**{**base, **campos})


def test_sem_dado_de_geracao_nunca_fica_verde():
    """Potência nula é "não sabemos", e "não sabemos" não pode ser desenhado como usina
    saudável.

    A frase mudou de "Sem comunicação" para "Sem dados de geração", e a diferença é o
    conserto: potência nula significa que a consulta ao meuWatt não trouxe número — não
    que a usina esteja muda. Quem responde por mudez é `sem_comunicacao`, que lê o estado
    dos inversores, porque o mw-api entrega potência zero (nunca nula) para quem não tem
    leitura. Este teste chegou a afirmar o contrário, e afirmava algo inalcançável.
    """
    tom, situacao = _tom(_usina(potencia_kw=None))

    assert tom == "semDados"
    assert situacao == "Sem dados de geração"


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


def test_inversor_parado_pinta_a_usina_de_vermelho():
    """O buraco central da régua de cor, e o que o app existe para responder.

    `_tom` julgava só desempenho e **nunca consultava falha**: uma usina com inversor em
    parada material aberta e disponibilidade de 95% saía verde "Gerando". No mesmo minuto,
    o meuWatt mostrava falha — e a aba Notificações deste próprio aplicativo já dizia
    "Inversor parado". O app se desmentia sozinho.

    A ordem correta é a de `plantStatusOf` no mw-fe: dormindo → sem dados → FALHA →
    alerta → gerando. Fato antes de média, porque média esconde fato.
    """
    tom, situacao = _tom(
        _usina(potencia_kw=800.0, disponibilidade_pct=95.0, inversores_parados=1)
    )

    assert tom == "parado"
    assert situacao == "1 inversor parado"


def test_falha_vence_disponibilidade_alta():
    """Três de quatro inversores parados com disponibilidade em 100% — o caso que os
    auditores reproduziram e que saía verde."""
    tom, _ = _tom(
        _usina(potencia_kw=200.0, disponibilidade_pct=100.0, inversores_parados=3)
    )

    assert tom == "parado"


def test_mudez_parcial_e_ambar_e_nao_verde():
    """Inversor calado não é parada, mas também não é normalidade."""
    tom, situacao = _tom(
        _usina(potencia_kw=500.0, disponibilidade_pct=98.0, inversores_mudos=1)
    )

    assert tom == "alerta"
    assert "sem comunicação" in situacao


def test_a_ordem_bate_com_a_do_meuwatt():
    """A régua é do produto de origem, não desta casa: dormindo vence tudo, e falha vence
    desempenho. Se as duas se invertessem de novo, a usina apagada ficaria vermelha toda
    noite ou a usina quebrada ficaria verde o dia todo."""
    dormindo = _usina(
        potencia_kw=0.0,
        disponibilidade_pct=0.0,
        inversores_parados=2,
        fora_da_janela_solar=True,
    )

    assert _tom(dormindo)[0] == "semDados", "dormindo vence falha"

    quebrada = _usina(potencia_kw=800.0, disponibilidade_pct=99.0, inversores_parados=1)

    assert _tom(quebrada)[0] == "parado", "falha vence desempenho"


def test_de_madrugada_nao_acende_faixa_vermelha():
    """O alarme falso que rodava oito horas por dia.

    O mw-api calcula `avail_pct = 100 if measured > 0 else 0` quando não há geração
    esperada — ou seja, **zero para toda usina da meia-noite até começar a gerar**. Com o
    teste de disponibilidade antes do de janela solar, a tela inicial anunciava "usina com
    problema · Disponibilidade baixa" todas as noites.

    Faixa vermelha que não corresponde a problema real é pior do que faixa nenhuma: da
    segunda vez que o dono abre e não encontra nada errado, ele para de olhar — e é o que
    o docstring de `_atencao` diz, com todas as letras.
    """
    tom, situacao = _tom(
        _usina(potencia_kw=0.0, disponibilidade_pct=0.0, fora_da_janela_solar=True)
    )

    assert tom == "semDados"
    assert situacao == "Fora da janela solar"


def test_amanhecendo_com_pouca_geracao_tambem_nao_alarma():
    """O mesmo zero de disponibilidade sobrevive aos primeiros minutos de sol."""
    tom, _ = _tom(
        _usina(potencia_kw=0.5, disponibilidade_pct=0.0, fora_da_janela_solar=True)
    )

    assert tom != "parado"


def test_disponibilidade_baixa_ainda_alarma_durante_o_dia():
    """A correção não pode ter desligado o alarme de verdade: com sol e gerando, 40% de
    disponibilidade continua vermelho."""
    tom, situacao = _tom(
        _usina(potencia_kw=120.0, disponibilidade_pct=40.0, fora_da_janela_solar=False)
    )

    assert tom == "parado"
    assert situacao == "Disponibilidade baixa"


def test_inversor_em_falha_declarada_conta_mesmo_com_status_normal():
    """`down` é o estado canônico, e ignorá-lo deixava passar o pior caso.

    O schema do mw-api diz no comentário do campo que é o flag que o front deve consumir
    para o vermelho "em falha", em vez de re-derivar da potência; o mw-fe faz
    `i.down || i.status === 'fault'`. Sem ele, um inversor com parada material aberta e
    status Modbus ainda `normal` saía VERDE no aplicativo enquanto o meuWatt o mostrava em
    falha — mesma usina, mesmo minuto, duas respostas.
    """
    from app.api.v1.plants import _parados

    inversores = [
        {"status": "normal", "down": True},   # parada aberta que o status ainda não reflete
        {"status": "normal", "down": False},
        {"status": "normal", "down": None},   # detector não sabe: vale o status
        {"status": "fault", "down": None},
    ]

    assert _parados(inversores) == 2


def test_capacidade_e_potencia_excluem_os_mesmos_inversores():
    """Numerador e denominador têm de concordar sobre quem conta.

    O mudo já saía da potência; se ficasse na capacidade, a usina com dois de três
    inversores calados mostraria a potência de um sobre a capacidade de três — uma
    porcentagem sistematicamente subestimada, rotulada "% da capacidade instalada".
    """
    from app.api.v1.plants import _capacidade_dos_inversores, _potencia_da_usina

    agora = {
        "inverters": [
            {"active_power": 80000.0, "capacity_kwp": 100.0, "status": "normal"},
            {"active_power": 99000.0, "capacity_kwp": 100.0, "status": "communication_error"},
        ]
    }

    potencia = _potencia_da_usina(agora)
    capacidade = _capacidade_dos_inversores(agora)

    assert potencia == 80.0, "o mudo não soma potência (o mw-api mantém o valor velho)"
    assert capacidade == 100.0, "nem capacidade — senão o percentual sai subestimado"
    assert round(potencia / capacidade * 100) == 80


# ── o que separa "mudo" de "dormindo" ───────────────────────────────────────


def test_usina_muda_nao_se_confunde_com_usina_dormindo():
    """A regressão mais cara que este arquivo protege.

    O mw-api coage `active_power` para 0 quando não há leitura, e o campo é obrigatório no
    schema. Logo a potência NUNCA chega nula, e a versão anterior — que inferia "sem
    comunicação" de `potencia_kw is None` — tinha esse ramo inalcançável: uma usina
    inteiramente muda ao meio-dia caía em "Sem geração agora", indistinguível de usina
    dormindo, e não acendia faixa nenhuma na tela inicial.
    """
    from app.api.v1.plants import _sem_comunicacao

    muda = {"inverters": [{"status": "communication_error"}, {"status": "communication_error"}]}
    dormindo = {"inverters": [{"status": "bedtime"}, {"status": "bedtime"}]}

    assert _sem_comunicacao(muda) is True
    assert _sem_comunicacao(dormindo) is False


def test_uma_usina_com_um_inversor_falando_nao_esta_muda():
    from app.api.v1.plants import _sem_comunicacao

    parcial = {"inverters": [{"status": "communication_error"}, {"status": "normal"}]}

    assert _sem_comunicacao(parcial) is False


def test_tom_de_usina_muda_e_sem_comunicacao():
    """Fecha o circuito: o campo tem de chegar ao tom, senão a correção não vale nada."""
    tom, situacao = _tom(_usina(potencia_kw=0.0, sem_comunicacao=True))

    assert tom == "semDados"
    assert situacao == "Sem comunicação"


def test_inversor_silenciado_fica_fora_das_somas():
    """O meuWatt exclui `ignored` da potência da usina
    (`mw-fe/src/pages/home/inicioData.ts`). Divergir faz a mesma usina mostrar número
    diferente nos dois produtos, e o dono não tem como saber em qual acreditar."""
    from app.api.v1.plants import (
        _capacidade_dos_inversores,
        _contam,
        _parados,
        _potencia_da_usina,
    )

    agora = {
        "inverters": [
            {"active_power": 100000.0, "capacity_kwp": 100.0, "status": "normal"},
            {"active_power": 50000.0, "capacity_kwp": 50.0, "status": "fault", "ignored": True},
        ]
    }

    assert _potencia_da_usina(agora) == 100.0, "o silenciado não soma potência"
    assert _capacidade_dos_inversores(agora) == 100.0, "nem na soma de recurso"
    assert _parados(_contam(agora)) == 0, "nem aparece como parada — foi decisão de quem opera"


def test_zero_de_geracao_continua_zero():
    """`or` mataria o zero: uma usina que de fato gerou 0 kWh viraria "não sabemos". Aqui
    zero é informação — e é o que distingue "não gerou" de "não medimos"."""
    from app.api.v1.plants import _numero

    assert _numero(0.0) == 0.0
    assert _numero(None) is None


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


def test_so_falha_conta_como_parado():
    """Parado é `fault`, e só.

    `bedtime` é a usina dormindo; `alert` é aviso com o inversor gerando; e
    `communication_error` é **mudo, não parado** — o mw-fe o pinta de âmbar, não de
    vermelho, e `equipamentos.py` o classifica como `semDados`. Enquanto este arquivo
    contava mudo como parada, a faixa vermelha "1 inversor parado" no detalhe da usina
    levava a uma tela de Equipamentos que contava zero: duas telas discordando sobre o
    mesmo aparelho.
    """
    from app.api.v1.plants import _parados

    inversores = [
        {"status": "normal"},
        {"status": "alert"},
        {"status": "bedtime"},
        {"status": "fault"},
        {"status": "communication_error"},
    ]

    assert _parados(inversores) == 1


def test_as_duas_telas_classificam_o_mesmo_inversor_igual():
    """A régua da lista de usinas e a da tela de equipamentos têm de coincidir.

    São arquivos diferentes com mapas próprios, e foi assim que a divergência nasceu.
    Este teste compara os dois diretamente.
    """
    from app.api.v1.equipamentos import TOM_POR_ESTADO
    from app.api.v1.plants import MUDO, PARADO

    for estado in PARADO:
        assert TOM_POR_ESTADO.get(estado) == "parado", f"{estado} deveria ser parado nas duas"

    assert TOM_POR_ESTADO.get(MUDO) == "semDados", "mudo é semDados nas duas telas"


def test_estados_conferem_com_a_lista_do_mw_api():
    """A régua é o schema do produto de origem, não a memória de quem escreveu isto.

    Se o mw-api renomear um estado, este teste falha aqui em vez de a contagem de
    inversores parados silenciosamente virar zero em produção.
    """
    import re
    from pathlib import Path

    from app.api.v1.plants import DORMINDO, MUDO, PARADO

    schema = Path("C:/dev/meuWatt/mw-api/src/monitoring/schemas.py")
    if not schema.exists():
        pytest.skip("mw-api não está ao lado; a régua só existe na máquina de quem tem os dois")

    linha = re.search(r"status: str\s*#\s*(.+)", schema.read_text("utf-8"))
    assert linha, "o comentário com os estados sumiu de InverterMonitoring.status"
    conhecidos = set(re.findall(r'"(\w+)"', linha.group(1)))

    assert PARADO <= conhecidos, f"estado que o mw-api não conhece: {sorted(PARADO - conhecidos)}"
    assert DORMINDO in conhecidos
    assert MUDO in conhecidos


def test_alertas_vem_em_envelope_e_nao_em_lista():
    """`/plants/{slug}/alerts` devolve `AlertListResponse{plant, total, alerts[]}`.

    Testar `isinstance(resposta, list)` fazia `alertas_ativos` ficar nulo para sempre — a
    tela dizia "não consultamos" com a resposta na mão, e a chamada acontecia à toa.
    """
    from app.api.v1.plants import _numero_inteiro

    envelope = {"plant": "Ibitinga", "total": 3, "alerts": [{}, {}, {}]}

    assert _numero_inteiro(envelope.get("total"), envelope.get("alerts")) == 3


def test_alertas_sem_total_caem_no_tamanho_da_lista():
    from app.api.v1.plants import _numero_inteiro

    assert _numero_inteiro(None, [{}, {}]) == 2
    assert _numero_inteiro(None, None) is None


def test_capacidade_vem_declarada_pelo_meuwatt():
    """Capacidade instalada é característica FÍSICA da usina, e o meuWatt a declara em
    `DailyGenerationReport.total_capacity_kwp` — na mesma resposta que já se lê.

    Somá-la dos inversores que estão falando **fabricava** o número: a capacidade da usina
    encolhia quando um inversor emudecia. Uma usina de 3 × 600 kWp com um mudo publicava
    1200 kWp; com todos mudos, "capacidade não informada". E esse valor é a manchete de
    quatro superfícies do aplicativo.
    """
    from app.api.v1.plants import _capacidade_declarada

    diario = {"total_capacity_kwp": 1800.0}

    assert _capacidade_declarada(diario) == 1800.0


def test_capacidade_declarada_nao_encolhe_com_inversor_mudo():
    """O caso que a auditoria reproduziu rodando o código."""
    from app.api.v1.plants import _capacidade_declarada, _capacidade_dos_inversores

    diario = {"total_capacity_kwp": 1800.0}
    agora = {
        "inverters": [
            {"capacity_kwp": 600.0, "status": "normal"},
            {"capacity_kwp": 600.0, "status": "normal"},
            {"capacity_kwp": 600.0, "status": "communication_error"},
        ]
    }

    assert _capacidade_dos_inversores(agora) == 1200.0, "a soma encolhe — por isso não vale"
    assert _capacidade_declarada(diario) == 1800.0, "a declarada é a verdade da usina"


def test_sem_relatorio_a_capacidade_e_nula_e_nao_zero():
    from app.api.v1.plants import _capacidade_declarada

    assert _capacidade_declarada({}) is None
    assert _capacidade_declarada(None) is None


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


def test_disponibilidade_de_usina_muda_e_nula_e_nao_cem():
    """O 100% fabricado pelo denominador vazio.

    O mw-api calcula `avail = soma_ponderada / peso if peso > 0 else 100.0`, e o laço pula
    inversor que não está comunicando. Com a usina inteira muda, o peso fica zero e o
    campo sai **100.0** — a tela mostraria "energia hoje 0 kWh · disponibilidade 100%",
    que é uma contradição apresentada com a maior tranquilidade possível.
    """
    from app.api.v1.plants import _tom

    muda = _usina(potencia_kw=0.0, disponibilidade_pct=None, sem_comunicacao=True)

    tom, situacao = _tom(muda)

    assert tom == "semDados"
    assert situacao == "Sem comunicação"
    assert muda.disponibilidade_pct is None, "100% com ninguém falando é número fabricado"


def test_capacidade_nao_cai_para_a_soma_que_encolhe():
    """A soma dos inversores foi removida do caminho de produção.

    Ela existe como diagnóstico — `_capacidade_dos_inversores` — mas não serve de recurso
    quando o relatório diário falha: `_capacidade_declarada` chama essa soma de fabricar o
    número, e uma fabricação não deixa de ser fabricação porque a outra fonte caiu. Sem
    capacidade conhecida, a tela diz "capacidade não informada".
    """
    import inspect

    from app.api.v1 import plants

    fonte = inspect.getsource(plants.listar_usinas)

    assert "capacidade_dos_inversores" not in fonte, (
        "a soma que encolhe voltou a alimentar a capacidade exibida"
    )
