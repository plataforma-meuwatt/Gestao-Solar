"""O cliente da exportação de dados brutos do meuWatt — a aba "Baixar dados".

A rota do meuWatt é síncrona e cara: ela gera o XLSX inteiro ANTES de responder, e o
cabeçalho só chega aos 35,6 s no pedido mais pesado que ela mesma permite (medido em Porto
Ferreira, 20 inversores, produção). Isso põe três armadilhas no caminho deste cliente, e
cada teste aqui guarda uma delas:

1. **O prazo.** `integracoes.cliente_meuwatt` constrói o `MeuWattClient` sem `timeout`, e a
   assinatura cai em 30 s. Pelo caminho normal, a exportação estoura `ReadTimeout` antes de
   o servidor terminar — e o cliente veria "a internet falhou" num arquivo que estava
   pronto para chegar.
2. **A memória.** `r.content` guardaria o arquivo inteiro aqui e de novo no corpo que o
   portal devolve. O teto do servidor é ≈ 5,3 MiB por arquivo; o risco nunca foi um
   arquivo, é N clientes ao mesmo tempo.
3. **A razão do "não".** O meuWatt recusa com `{"detail": {motivo, message}}` (e o limite
   de 10/min com `{"error": ...}`). Se o corpo do erro não for lido antes de o fluxo
   fechar, quem traduz recebe uma exceção muda e a tela diz "erro" onde deveria dizer "este
   pedido daria 2,4 milhões de células".

Nada de rede: o meuWatt entra por `respx`, com o cliente REAL por cima — o caminho de
fluxo (`httpx.stream`) é exercitado de verdade, não uma fantasia dele.
"""

import json

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from pydantic import BaseModel

from app.clients.meuwatt import MeuWattClient
from app.core import cripto
from app.models.integracao import Integracao, Produto
from app.services import sonda

BASE = "https://api.meuwatt.test"
RAW = f"{BASE}/plants/porto-ferreira/exports/raw"
OPCOES = f"{BASE}/plants/porto-ferreira/exports/raw/options"

#: Um XLSX de mentira com a assinatura de verdade (é um ZIP) — o que se compara byte a byte.
XLSX = b"PK\x03\x04" + b"a planilha inteira, exatamente como o meuWatt escreveu" * 40

#: As opções como Porto Ferreira as devolve (05/09/2026), recortadas ao que a sonda vigia.
OPCOES_COMO_HOJE = {
    "plant": {"id": 9378, "slug": "porto-ferreira", "name": "Porto Ferreira"},
    "skids": [{"id": 1, "name": "SKID-01",
               "slots": [{"key": "slot:170", "label": "Inv 13"}]}],
    "retencao": {"snapshots_desde": "2026-03-06", "ssu_desde": "2024-09-05"},
    "limites": {"native": 7, "5m": 31, "15m": 92, "1h": 366, "1d": 366,
                "max_celulas": 2000000},
}


class _PedidoDeMentira(BaseModel):
    """Espelha o pouco de `RawExportRequest` de que este cliente depende: um modelo
    tipado, com blocos opcionais que somem quando ninguém os pediu."""

    start_date: str = "2026-08-01"
    end_date: str = "2026-08-31"
    step: str = "15m"
    inversores: dict | None = None
    estacao: dict | None = None
    fronteira: dict | None = None
    sistema: dict | None = None


class _CorpoQueAvisa(httpx.AsyncByteStream):
    """Um corpo que registra o instante em que alguém o consome. É o instrumento do teste
    de fluxo: sem ele, "não materializou" seria uma afirmação sobre o código, não sobre o
    que aconteceu."""

    def __init__(self, dados: bytes) -> None:
        self._dados = dados
        self.consumido = False

    async def __aiter__(self):
        self.consumido = True
        for i in range(0, len(self._dados), 512):
            yield self._dados[i : i + 512]


@pytest.fixture
def cliente() -> MeuWattClient:
    return MeuWattClient(base_url=BASE, token="mw_pat_teste")


# ── 1. o prazo ──────────────────────────────────────────────────────────────


@respx.mock
async def test_o_prazo_de_leitura_cobre_os_35_segundos_medidos(cliente):
    """DEFEITO QUE ESTE TESTE GUARDA: a exportação sair pelo teto padrão do cliente (30 s)
    e estourar `ReadTimeout` no pedido mais pesado que o próprio meuWatt aceita.

    Medido em produção, no MESMO pedido (5 min × 31 d, todos os blocos) e em três
    ocasiões: 35,6 s, 34,3 s e 27,2 s até o CABEÇALHO, porque a geração inteira precede a
    resposta. Trinta segundos reprovam a maior delas, e a dispersão mostra que a margem
    contra o padrão não é só apertada: é instável — na medição de 05/09/2026 ela já não
    existe. O teto tem de ser explícito e folgado — e o de CONECTAR tem de continuar curto,
    senão um destino fora do ar prende a tela por dois minutos em vez de falhar depressa.
    """
    rota = respx.mock.post(RAW).respond(200, content=XLSX)

    async with cliente.export_raw("porto-ferreira", _PedidoDeMentira()):
        pass

    prazo = rota.calls.last.request.extensions["timeout"]
    assert prazo["read"] >= 35.6, "o pior caso MEDIDO tem de caber, com folga"
    assert prazo["connect"] <= 10.0, "destino fora do ar falha depressa"


@respx.mock
async def test_as_opcoes_tem_prazo_proprio_e_curto(cliente):
    """DEFEITO: as opções herdarem o prazo da exportação. Elas são o lado BARATO do par
    (1,2 s medidos contra 35,6 s), e é com elas que a tela abre — esperar dois minutos por
    uma fonte que já provou responder em segundos é deixar a tela pendurada à toa."""
    rota = respx.mock.get(OPCOES).respond(200, json={"skids": [], "limites": {"5m": 31}})

    await cliente.export_options("porto-ferreira")

    assert rota.calls.last.request.extensions["timeout"]["read"] <= 20.0


# ── 2. a memória ────────────────────────────────────────────────────────────


@respx.mock
async def test_o_arquivo_nao_e_materializado_pelo_cliente(cliente):
    """DEFEITO: trocar o fluxo por `r.content` e guardar o XLSX inteiro na memória deste
    processo — e de novo no corpo que o portal devolve.

    A prova não é sobre o código: é sobre o corpo, que só é consumido DEPOIS que quem
    chamou decide consumi-lo. Se o cliente lesse por conta própria, `consumido` já seria
    verdadeiro na entrada do contexto.
    """
    corpo = _CorpoQueAvisa(XLSX)
    respx.mock.post(RAW).mock(return_value=httpx.Response(200, stream=corpo))

    async with cliente.export_raw("porto-ferreira", _PedidoDeMentira()) as r:
        assert not corpo.consumido, "o cliente leu o arquivo sozinho"
        pedacos = [p async for p in r.aiter_bytes()]

    assert corpo.consumido
    assert b"".join(pedacos) == XLSX, "os bytes que chegam são os que o meuWatt escreveu"


# ── 3. a razão do "não" ─────────────────────────────────────────────────────


@respx.mock
async def test_a_recusa_chega_legivel_para_quem_traduz(cliente):
    """DEFEITO: fechar o fluxo sem ler o corpo do erro, deixando quem traduz com uma
    exceção muda (`httpx.ResponseNotRead`).

    O meuWatt recusa com um `motivo` estável (`muito_grande`, `passo_excede_limite`,
    `fora_da_retencao`…) — e é esse código, não o `message` escrito para o operador de lá,
    que a tela traduz para o cliente. Sem o corpo, "este pedido daria 2,4 milhões de
    células" vira "erro ao baixar".
    """
    respx.mock.post(RAW).respond(
        400,
        json={
            "detail": {
                "motivo": "muito_grande",
                "message": "O arquivo teria ≈ 2.400.000 células (limite 2.000.000).",
            }
        },
    )

    with pytest.raises(httpx.HTTPStatusError) as erro:
        async with cliente.export_raw("porto-ferreira", _PedidoDeMentira()):
            pass  # pragma: no cover — o 400 estoura na entrada do contexto

    assert erro.value.response.json()["detail"]["motivo"] == "muito_grande"


@respx.mock
async def test_o_limite_de_dez_por_minuto_tambem_chega_legivel(cliente):
    """DEFEITO: o 429 do limite virar uma exceção muda e a tela dizer "erro" onde deveria
    dizer "espere um minuto".

    O balde do meuWatt é por IP (`key_func=get_remote_address`), e todo o portal sai pelo
    mesmo endereço: são 10 exportações por minuto para TODOS os clientes somados. Medido: o
    corpo vem em `{"error": ...}` e **sem `Retry-After`** — então a frase de espera é
    escrita deste lado, e para isso o corpo precisa existir.
    """
    respx.mock.post(RAW).respond(429, json={"error": "Rate limit exceeded: 10 per 1 minute"})

    with pytest.raises(httpx.HTTPStatusError) as erro:
        async with cliente.export_raw("porto-ferreira", _PedidoDeMentira()):
            pass  # pragma: no cover

    assert erro.value.response.status_code == 429
    assert "Rate limit" in erro.value.response.json()["error"]


# ── 4. o que atravessa a ponte ──────────────────────────────────────────────


@respx.mock
async def test_bloco_ausente_nao_atravessa_como_nulo(cliente):
    """DEFEITO: mandar `"estacao": null` no corpo em vez de omitir o bloco.

    No contrato do meuWatt, **bloco ausente não entra no arquivo** — e é o `exclude_none`
    que preserva essa semântica. Mandar nulo é dizer a mesma coisa apenas enquanto o
    upstream for gentil com nulos, e o contrato não promete essa gentileza.
    """
    rota = respx.mock.post(RAW).respond(200, content=XLSX)

    async with cliente.export_raw(
        "porto-ferreira",
        _PedidoDeMentira(inversores={"variaveis": ["geracao"], "agrupamento": "lista"}),
    ):
        pass

    corpo = json.loads(rota.calls.last.request.content)
    assert corpo["inversores"] == {"variaveis": ["geracao"], "agrupamento": "lista"}
    assert "estacao" not in corpo and "fronteira" not in corpo and "sistema" not in corpo


# ── 5. as duas rotas na sonda ───────────────────────────────────────────────


def test_a_exportacao_esta_no_catalogo_e_o_post_fica_de_fora():
    """DEFEITO: as rotas novas sumirem num deploy do meuWatt sem a sonda dizer nada — e o
    seu contrário, a sonda POSTAR nelas.

    O POST fica declarado e não exercitado por dois motivos medidos: o executor da sonda
    nunca envia corpo JSON (um POST sem corpo responde 422 e viraria vermelho por culpa da
    sonda), e cada sondagem queimaria uma das 10 vagas do minuto e até 34 s do worker único
    do meuWatt. Declarada e não chamada é honesto; omitida daria a impressão de lista
    completa.
    """
    opcoes = next(r for r in sonda.MEUWATT if r.chave == "mw.export_options")
    assert opcoes.sonda and not opcoes.essencial
    # E vigiando FORMA, não só status: os três caminhos são os que `exportacao._opcoes` lê.
    assert set(opcoes.campos_exigidos) == {
        "skids[].slots[].key",
        "limites.max_celulas",
        "retencao.snapshots_desde",
    }

    bruto = next(r for r in sonda.MEUWATT if r.chave == "mw.export_raw")
    assert bruto.metodo == "POST"
    assert not bruto.sonda and bruto.nao_sondada_porque


@respx.mock
async def test_a_varredura_pede_as_opcoes_e_nunca_gera_o_arquivo(db, monkeypatch):
    """A prova do teste acima é o que vai — e o que NÃO vai — para a rede numa varredura."""
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))

    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url=BASE,
            token_cifrado=cripto.cifrar("mw_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"),
            token_prefixo="mw_pat_1xNq",
            ativa=True,
        )
    )
    db.commit()

    respx.mock.get(f"{BASE}/auth/me").respond(200, json={"email": "f@e.com"})
    respx.mock.get(f"{BASE}/plants").respond(200, json=[{"slug": "porto-ferreira"}])
    opcoes = respx.mock.get(OPCOES).respond(200, json=OPCOES_COMO_HOJE)
    respx.mock.route(host="api.meuwatt.test").respond(200, json={})

    v = await sonda.varrer(db, Produto.MEUWATT)

    assert next(r for r in v.rotas if r.chave == "mw.export_options").situacao == "ok"
    assert opcoes.called

    bruto = next(r for r in v.rotas if r.chave == "mw.export_raw")
    assert bruto.situacao == "nao_sondada"
    assert not [c for c in respx.mock.calls if c.request.method == "POST"]


@respx.mock
async def test_opcoes_que_respondem_200_com_a_forma_trocada_ficam_vermelhas(db, monkeypatch):
    """DEFEITO QUE ESTE TESTE GUARDA: a sonda ficar VERDE num deploy do meuWatt que renomeia
    um campo das opções — e a tela "Baixar dados" abrir quebrada sem nada acender.

    Este é o modo de falha da família, e ele não é "sumir": a rota continua respondendo 200.
    Se `max_celulas` virar outro nome, a tela deixa de saber o orçamento e para de impedir o
    pedido grande demais — que aí vai ao meuWatt, gasta uma das dez vagas do minuto de TODOS
    os clientes e volta recusado. Sem `campos_exigidos`, `_resumir` registraria
    `["plant", "skids", …]` e a linha ficaria verde.
    """
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))
    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url=BASE,
            token_cifrado=cripto.cifrar("mw_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"),
            token_prefixo="mw_pat_1xNq",
            ativa=True,
        )
    )
    db.commit()

    trocada = json.loads(json.dumps(OPCOES_COMO_HOJE))
    trocada["limites"]["maximo_de_celulas"] = trocada["limites"].pop("max_celulas")

    respx.mock.get(f"{BASE}/auth/me").respond(200, json={"email": "f@e.com"})
    respx.mock.get(f"{BASE}/plants").respond(200, json=[{"slug": "porto-ferreira"}])
    respx.mock.get(OPCOES).respond(200, json=trocada)
    respx.mock.route(host="api.meuwatt.test").respond(200, json={})

    v = await sonda.varrer(db, Produto.MEUWATT)

    linha = next(r for r in v.rotas if r.chave == "mw.export_options")
    assert linha.status == 200, "o produto respondeu — o que mudou foi a forma"
    assert linha.situacao == "falhou"
    assert "limites.max_celulas" in linha.detalhe, "a linha tem de DIZER o que faltou"
