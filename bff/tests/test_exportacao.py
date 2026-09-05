"""Baixar os dados brutos da usina — a ponte para a aba Downloads da mw-api.

O dono: *"quero ter esses dados no Gestão Solar"*. São duas rotas, e os três defeitos que
elas podem ter são invisíveis num diff e caros em produção. É deles que este arquivo trata:

1. **O `{slug}` é interpolado numa URL chamada com a credencial de SERVIÇO.** É a mesma
   forma que já custou caro em `documents.py`, onde `?tipo=../../../admin/users` normalizava
   e devolvia os bytes da plataforma inteira. Aqui o slug só pode sair de
   `PlantLink.mw_plant_slug` — resolvido pelo `usina_id` (int nosso) dentro do escopo — e o
   corpo do POST atravessa como modelo TIPADO, nunca como `dict` repassado cru. O upstream
   valida, mas o BFF não pode ser o lugar por onde entra o que ninguém olhou.

2. **O arquivo atravessa em FLUXO.** O teto do servidor é ~5,3 MiB por arquivo (2.000.000
   células × 2,78 bytes/célula, medidos), e o risco nunca foi *um* arquivo: é N clientes ×
   5 MiB. `Response(content=…)` — o padrão dos PDFs unitários — guardaria o corpo inteiro na
   memória deste processo e de novo na do Starlette, e isso só aparece sob concorrência,
   nunca num teste de caminho feliz. E o `Content-Length` só pode viajar quando o corpo sai
   daqui do mesmo tamanho que entrou: `aiter_bytes()` devolve os bytes JÁ DECODIFICADOS, e
   repassar o comprimento do comprimido faria o navegador cortar a planilha no número
   prometido — arquivo corrompido, sem nenhum erro na tela.

3. **A recusa do meuWatt tem de chegar com a razão.** O 400 dele vem em
   `{"detail": {motivo, message}}` com códigos estáveis; o 429 do balde de 10/minuto vem em
   `{"error": …}` — que `detalhe_do_upstream` não alcança, porque só lê `detail`/`message`/
   `erro`. Achatar os dois num 502 genérico faria a tela oferecer "Tentar de novo" num
   `muito_grande` (repetir dá exatamente o mesmo resultado) e chamar de defeito uma espera.

Nada de rede: o meuWatt entra por `respx`, com o cliente REAL do BFF por cima — assim o
caminho de fluxo (`httpx.stream`) é exercitado de verdade, e não uma fantasia dele.
"""

import gzip
import json

import httpx
import pytest
import respx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import exportacao
from app.api.v1.exportacao import (
    MOTIVO_ESPERA,
    InversoresIn,
    PedidoIn,
    arquivo_de_dados,
    opcoes_de_exportacao,
)
from app.clients.meuwatt import MeuWattClient
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

#: O endereço do meuWatt no teste. As URLs abaixo são as que a rota TEM de montar — se ela
#: montar outra, a chamada não casa com nenhuma rota do `respx` e o teste falha por si.
BASE = "https://mw.teste"
OPCOES = f"{BASE}/plants/porto-ferreira/exports/raw/options"
ARQUIVO = f"{BASE}/plants/porto-ferreira/exports/raw"

#: Um XLSX é um ZIP: começa com `PK\x03\x04`. Basta isso para provar que os bytes
#: atravessaram sem reembalagem.
XLSX = b"PK\x03\x04planilha-de-dados-brutos"

#: A seleção mais simples que o contrato aceita: um mês, de hora em hora, só a geração dos
#: inversores. `series` fica de fora de propósito — ver o teste do bloco ausente.
PEDIDO = {
    "inicio": "2026-08-01",
    "fim": "2026-08-31",
    "passo": "1h",
    "inversores": {"variaveis": ["geracao"]},
}


# ── o cenário ───────────────────────────────────────────────────────────────


@pytest.fixture
def dono(db):
    u = User(
        apelido="dono",
        email="dono@exemplo.com.br",
        nome="Dono",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def minha(db, dono, usinas):
    """Porto Ferreira, concedida a esta pessoa. A outra usina fica fora do escopo."""
    porto, _outra = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=porto.id))
    db.commit()
    return porto


@pytest.fixture
def alheia(usinas):
    _porto, outra = usinas
    return outra


@pytest.fixture
def ponte(monkeypatch):
    """O cliente REAL do meuWatt, apontado para o endereço de teste e com token fixo.

    Token fixo para não haver login: o que se exercita aqui é o transporte e o escopo, não
    a sessão de serviço.
    """
    cliente = MeuWattClient(base_url=BASE, token="mw_pat_teste")

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr(exportacao.integracoes, "cliente_meuwatt", _cliente)
    return cliente


@pytest.fixture
def http(db, dono, minha, ponte):
    """Só o router da exportação, com o banco do teste.

    É por aqui que se prova o **422**: a validação do FastAPI acontece antes do corpo da
    rota, e chamar a função direto (como fazem os outros testes deste arquivo) passaria por
    cima justamente do portão que se quer medir.
    """
    aplicacao = FastAPI()
    aplicacao.include_router(exportacao.router)
    aplicacao.dependency_overrides[get_db] = lambda: db
    cliente = TestClient(aplicacao)
    token, _ = criar_token(dono.id)
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


async def _juntar(resposta) -> bytes:
    return b"".join([p async for p in resposta.body_iterator])


async def _pedacos(resposta) -> list[bytes]:
    """Os pedaços como chegaram, sem juntá-los — é a fronteira entre eles que interessa."""
    return [p async for p in resposta.body_iterator]


# ══════════════════════════════════════════════════════════════════════════════
# A cerca
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_a_usina_de_outro_cliente_e_404_e_a_recusa_nao_diz_proibido(
    db, dono, alheia, ponte
):
    """404 e nunca 403: responder "proibido" confirmaria que aquela usina existe, e quem
    trocou o número na URL não tem por que ganhar essa informação.

    A prova de que a recusa é LOCAL é o que não foi para a rede. Se ela acontecesse depois
    da ida ao upstream, a credencial de serviço já teria sido gasta para descobrir o que o
    banco daqui sabia — e, pior, o `{slug}` de outro cliente já teria virado URL.

    As duas rotas passam pelo mesmo portão: as opções também dizem quantos inversores a
    usina tem e desde quando existe o acervo dela.
    """
    with pytest.raises(HTTPException) as e:
        await arquivo_de_dados(
            pedido=PedidoIn(**PEDIDO), usina_id=alheia.id, db=db, usuario=dono
        )

    assert e.value.status_code == 404
    assert "proibid" not in str(e.value.detail).lower()
    assert respx.mock.calls.call_count == 0

    with pytest.raises(HTTPException) as e2:
        await opcoes_de_exportacao(usina_id=alheia.id, db=db, usuario=dono)

    assert e2.value.status_code == 404
    assert respx.mock.calls.call_count == 0


@respx.mock
async def test_usina_sem_monitoramento_e_404_nomeando_o_servico_ausente(
    db, dono, minha, ponte
):
    """Vínculo só com o meuPlano (é o caso da UFV Leme): não há slug, e sem slug não há URL.

    A frase nomeia o SERVIÇO ausente — "monitoramento" —, nunca o produto: o cliente do
    portal não conhece "meuWatt", e dizer o nome interno o mandaria procurar uma coisa que
    ele não contratou. E a recusa continua sendo 404, o mesmo tom do escopo: um cliente que
    só tem manutenção não precisa descobrir que existe uma ponte do outro lado.
    """
    minha.mw_plant_slug = None
    db.commit()

    with pytest.raises(HTTPException) as e:
        await arquivo_de_dados(
            pedido=PedidoIn(**PEDIDO), usina_id=minha.id, db=db, usuario=dono
        )

    assert e.value.status_code == 404
    assert "monitoramento" in e.value.detail
    assert "meuWatt" not in e.value.detail
    assert respx.mock.calls.call_count == 0


@respx.mock
async def test_o_slug_da_url_vem_do_vinculo_e_o_corpo_nao_o_alcanca(db, dono, minha, ponte):
    """O defeito de `documents.py`, na sua forma nova.

    Lá o `?tipo=` era texto livre e ia parar em `/reports/{id}/files/{kind}`, chamado com o
    token de administrador: `../../../admin/users` normalizava para outra rota da mw-api e
    devolvia os bytes. Aqui o alvo é o `{slug}` de `/plants/{slug}/exports/raw` — e o corpo
    do POST, que é a única coisa que o cliente controla livremente, é o vetor óbvio.

    Duas trancas, e este teste mede as duas ao mesmo tempo: o slug sai do `PlantLink`
    resolvido pelo `usina_id`, e o corpo é um modelo TIPADO — campo que o modelo não
    conhece é descartado na porta, e por isso nunca chega perto de virar URL nem de viajar
    para o upstream como se fosse do contrato.
    """
    rota = respx.mock.post(ARQUIVO).respond(200, content=XLSX)
    veneno = dict(PEDIDO) | {
        "slug": "../../../admin/users",
        "plant_slug": "usina-de-outro-cliente",
        "start_date": "1970-01-01",
    }

    resposta = await arquivo_de_dados(
        pedido=PedidoIn(**veneno), usina_id=minha.id, db=db, usuario=dono
    )
    await _juntar(resposta)

    assert rota.called
    url = str(respx.mock.calls[0].request.url)
    assert url == ARQUIVO, "a URL tem de ser montada com o slug do vínculo"
    assert "admin" not in url and ".." not in url

    corpo = json.loads(respx.mock.calls[0].request.content)
    assert "slug" not in corpo and "plant_slug" not in corpo
    # `start_date` é campo do upstream: o veneno tentou passar por dentro do vocabulário
    # dele. O que viaja é o que a NOSSA tradução escreveu, a partir de `inicio`.
    assert corpo["start_date"] == "2026-08-01"


def test_passo_fora_dos_cinco_e_422_daqui_sem_tocar_no_upstream(http):
    """O passo escolhe a granularidade e casa com um teto de dias do outro lado. Texto livre
    aqui seria um parâmetro nosso alimentando a rota de lá — e, o que é pior, gastaria uma
    das dez vagas por minuto do balde (que é por IP: todo o portal sai pelo mesmo endereço)
    para receber um 422 que este processo já sabia dar.

    A recusa é **422 e não 502**: 502 se leria como queda do monitoramento, mandando o
    cliente esperar por um defeito que está no pedido. O contador do dublê é a prova de que
    ninguém atravessou a ponte.

    O segundo pedido é a outra metade da mesma tranca: a lista é fechada, mas os cinco
    passos legítimos passam. Um 422 ali seria a granularidade recusada por engano.
    """
    with respx.mock:
        rota = respx.mock.post(ARQUIVO).respond(200, content=XLSX)

        r = http.post(
            "/api/v1/energia/dados/arquivo",
            params={"usina_id": 1},
            json=dict(PEDIDO) | {"passo": "7m"},
        )

        assert r.status_code == 422, r.text
        assert rota.call_count == 0, "o passo recusado não pode ter atravessado a ponte"

        ok = http.post(
            "/api/v1/energia/dados/arquivo",
            params={"usina_id": 1},
            json=dict(PEDIDO) | {"passo": "native"},
        )

        assert ok.status_code != 422, "um dos cinco passos legítimos foi recusado na porta"
        assert rota.call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# A recusa do meuWatt, traduzida
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_o_motivo_da_recusa_atravessa_mas_a_frase_do_operador_nao(db, dono, minha, ponte):
    """`muito_grande` é regra violada, não falha de transporte — e a tela precisa saber a
    diferença para escolher entre `Erro` (com "Tentar de novo") e `Aviso` (sem). Oferecer
    repetição num pedido que estourou o orçamento de células seria crueldade: repetir dá
    exatamente o mesmo resultado.

    Por isso o `motivo` viaja no primeiro nível do corpo. O `message`, não: ele foi escrito
    para o operador da mw-api e fala em balde, snapshots, SSU e no número de células do
    orçamento interno. Quem escreve para o cliente é o portal — a mesma régua que já vale
    para `classificacao` e `situacao` na aba Ordens.
    """
    respx.mock.post(ARQUIVO).respond(
        400,
        json={
            "detail": {
                "motivo": "muito_grande",
                "message": "O pedido gera 2.400.000 células; o orçamento é de 2.000.000.",
            }
        },
    )

    resposta = await arquivo_de_dados(
        pedido=PedidoIn(**PEDIDO), usina_id=minha.id, db=db, usuario=dono
    )

    assert resposta.status_code == 400, "não pode virar 502: o pedido é que está errado"
    corpo = json.loads(bytes(resposta.body))
    assert corpo["motivo"] == "muito_grande"
    assert "células" not in corpo["detail"]
    assert "2.000.000" not in bytes(resposta.body).decode()


@respx.mock
async def test_o_balde_estourado_vira_espera_e_nao_erro(db, dono, minha, ponte):
    """O limite da mw-api é `10/minute` **por IP** (`key_func=get_remote_address`), e todo
    o portal sai pelo mesmo endereço do Railway: são dez exportações por minuto para todos
    os clientes somados. Medido em 05/09/2026: o corpo vem em `{"error": …}` e SEM
    `Retry-After`.

    Esse corpo é o defeito silencioso. `detalhe_do_upstream` só lê `detail`, `message` e
    `erro` — `error` não está na lista —, então sem tratamento próprio o 429 cairia no ramo
    genérico e chegaria ao cliente como **502**: uma espera de um minuto disfarçada de
    ponte quebrada, com a frase em inglês do limitador de lá ou nenhuma frase.
    """
    respx.mock.post(ARQUIVO).respond(
        429, json={"error": "Rate limit exceeded: 10 per 1 minute"}
    )

    resposta = await arquivo_de_dados(
        pedido=PedidoIn(**PEDIDO), usina_id=minha.id, db=db, usuario=dono
    )

    assert resposta.status_code == 429, "não pode virar 502: não há defeito nenhum aqui"
    corpo = json.loads(bytes(resposta.body))
    assert corpo["motivo"] == MOTIVO_ESPERA
    assert "minuto" in corpo["detail"]
    assert "Rate limit exceeded" not in bytes(resposta.body).decode()


# ══════════════════════════════════════════════════════════════════════════════
# O arquivo
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_a_planilha_atravessa_em_pedacos_e_o_tamanho_so_viaja_se_for_o_mesmo(
    db, dono, minha, ponte
):
    """Duas coisas que só falham longe do caminho feliz.

    **Os pedaços.** Com `Response(content=…)` o corpo inteiro passaria pela memória deste
    processo e de novo pela do Starlette — e o teste ainda ficaria verde, porque o cliente
    recebe os mesmos bytes. A prova de que o fluxo é fluxo é a FRONTEIRA entre os pedaços:
    três entram, três saem. Materializar juntaria os três num só.

    **O tamanho.** `aiter_bytes()` devolve os bytes já DECODIFICADOS. Se um proxy no meio
    comprimir o XLSX, o `Content-Length` do cabeçalho é o do comprimido e o corpo é o do
    original: o navegador cortaria a planilha no número prometido e salvaria um arquivo
    corrompido sem nenhum erro na tela. Sem o cabeçalho a barra de progresso fica cega, que
    é o mal menor — e é por isso que ele só é repassado sob `identity`.
    """
    pedacos = [b"PK\x03\x04parte-um", b"parte-dois", b"parte-tres"]
    inteiro = b"".join(pedacos)
    comprimido = gzip.compress(inteiro)

    async def _tres():
        for p in pedacos:
            yield p

    respx.mock.post(ARQUIVO).side_effect = [
        httpx.Response(
            200,
            content=_tres(),
            headers={
                "content-length": str(len(inteiro)),
                "content-encoding": "identity",
                "content-type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            },
        ),
        httpx.Response(
            200,
            content=comprimido,
            headers={
                "content-encoding": "gzip",
                "content-length": str(len(comprimido)),
            },
        ),
    ]

    resposta = await arquivo_de_dados(
        pedido=PedidoIn(**PEDIDO), usina_id=minha.id, db=db, usuario=dono
    )
    vistos = await _pedacos(resposta)

    assert vistos == pedacos, "o corpo foi materializado: chegou num pedaço só"
    assert resposta.headers["content-length"] == str(len(inteiro))
    # O nome do arquivo é o do produto que o cliente abriu, e ASCII: cabeçalho HTTP é
    # latin-1 no Starlette, e "Ribeirão Bonito" já derrubou a ficha em PDF uma vez.
    assert "dados-porto-ferreira-2026-08-01_2026-08-31-1h.xlsx" in (
        resposta.headers["content-disposition"]
    )

    comprimida = await arquivo_de_dados(
        pedido=PedidoIn(**PEDIDO), usina_id=minha.id, db=db, usuario=dono
    )

    assert await _juntar(comprimida) == inteiro
    assert "content-length" not in comprimida.headers


@respx.mock
async def test_bloco_ausente_nao_viaja_e_nulo_nao_e_lista_vazia(db, dono, minha, ponte):
    """*"Bloco ausente não entra no arquivo"* é o contrato do meuWatt, e a única forma de
    dizê-lo é OMITIR a chave.

    Mandar `"estacao": null` parece a mesma coisa e não é: depender de o upstream tratar
    nulo como ausente é apostar numa gentileza que o contrato não promete, e um dia em que
    ele passar a validar o bloco recebido a planilha ganharia colunas que ninguém pediu —
    ou um 400 `bloco_indisponivel` numa usina sem estação, por causa de um `null` que o
    cliente não escreveu.

    O mesmo raciocínio protege `series`. Nulo ali significa "não mexi": o inversor
    comissionado no meio do período entra sozinho. Uma lista explícita congela o conjunto no
    que a tela viu, e `[]` seria pior ainda — "nenhuma série", uma planilha sem colunas.
    Por isso a chave tem de estar AUSENTE, e não presente valendo nulo.

    Fecha com a tradução do vocabulário: o portal fala `inicio`/`fim`/`passo`, e é aqui que
    isso vira `start_date`/`end_date`/`step` — num lugar só, para que o dia em que a mw-api
    renomear um campo seja um dia em que uma linha muda, não cinco telas.
    """
    respx.mock.post(ARQUIVO).respond(200, content=XLSX)

    pedido = PedidoIn(
        inicio="2026-08-01",
        fim="2026-08-31",
        passo="1h",
        inversores=InversoresIn(variaveis=["geracao"]),
    )
    resposta = await arquivo_de_dados(
        pedido=pedido, usina_id=minha.id, db=db, usuario=dono
    )
    await _juntar(resposta)

    corpo = json.loads(respx.mock.calls[0].request.content)

    assert "inversores" in corpo
    for fora in ("estacao", "fronteira", "sistema"):
        assert fora not in corpo, f"o bloco `{fora}` viajou sem ninguém ter pedido"
    assert "series" not in corpo["inversores"], (
        "`series` ausente é 'todas'; presente e nulo é a mesma frase dita de um jeito que o "
        "contrato não promete honrar"
    )
    assert corpo["start_date"] == "2026-08-01"
    assert corpo["end_date"] == "2026-08-31"
    assert corpo["step"] == "1h"
    # Os horários acompanham sempre: o upstream os ignora no passo diário, e omiti-los
    # deixaria a janela do passo fino começar onde o default de lá quisesse.
    assert corpo["start_time"] == "00:00" and corpo["end_time"] == "23:59"
