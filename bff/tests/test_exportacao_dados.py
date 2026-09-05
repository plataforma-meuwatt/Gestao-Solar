"""Baixar os dados brutos da usina — a ponte do portal com a aba Downloads do meuWatt.

O dono (05/09/2026): *"coloque no site a nova feature de download dos dados que agora tem no
meuWatt"*.

O que estes testes protegem, em ordem de gravidade:

1. **A usina tem de ser desta pessoa**, e a recusa acontece ANTES de qualquer ida ao
   upstream: a planilha é a série histórica inteira de uma usina, e deixar passar aqui é
   vazamento em lote. E o portão certo é o do lado meuWatt (`_usina_no_escopo`), não o da
   manutenção — a usina monitorada SEM contrato de manutenção tem direito aos próprios
   números.
2. **O `{slug}` nunca vem do corpo**, e é conferido antes de virar URL. Ele é interpolado
   numa rota da mw-api chamada com o PAT do dono, que é a forma exata que já custou caro em
   `documents.py`: `../../../admin/users` normalizava e devolvia os bytes.
3. **O arquivo atravessa em fluxo, byte a byte.** Materializá-lo aqui guardaria ~5 MiB por
   cliente na memória deste processo e de novo no corpo do Starlette.
4. **Limite estourado é ESPERA ou REGRA, nunca "erro de ponte".** O 429 do meuWatt vem em
   `{"error": …}` (medido: sem `Retry-After`), que `detalhe_do_upstream` não alcança; o 400
   vem em `{"detail": {"motivo", "message"}}`, e o `motivo` é o que a tela traduz.
5. **Nome de arquivo não derruba a resposta.** Cabeçalho HTTP é latin-1 no Starlette, e
   "Ribeirão Bonito" já derrubou a ficha em PDF uma vez — antes do CORS, fazendo a tela
   acusar a internet do cliente por um defeito nosso.

Nada de rede: a mw-api entra por `respx`, com o cliente REAL por cima — assim o caminho de
fluxo (`httpx.stream`) é exercitado de verdade, e não uma fantasia dele.
"""

import asyncio
import gzip
from datetime import timedelta

import pytest
import respx
from fastapi import HTTPException

from app.api.v1 import pacotes
from app.api.v1.exportacao import (
    MOTIVO_ESPERA,
    _VAGAS,
    OpcoesOut,
    PedidoIn,
    _nome_do_arquivo,
    arquivo_de_dados,
    opcoes_de_exportacao,
)
from app.clients.meuwatt import MeuWattClient
from app.core.datas import hoje
from app.core.security import gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

BASE = "https://api.meuwatt.test"

#: Um XLSX de mentira, com a assinatura de ZIP de verdade — é o que se compara byte a byte.
XLSX = b"PK\x03\x04" + b"a planilha inteira, exatamente como o meuWatt a escreveu" * 200

#: As opções como a mw-api as devolve (`RawExportOptions`), copiadas da produção de Porto
#: Ferreira em 05/09/2026 — inclusive `umidade`, que NÃO é variável exportável e mesmo assim
#: viaja dentro de `colunas`.
OPCOES = {
    "plant": {"id": 9378, "slug": "porto-ferreira", "name": "Porto Ferreira",
              "capacity_kwp": 7402.5},
    "skids": [
        {"id": 1, "name": "SKID-01", "capacity_kwp": 1500.2, "slots": [
            {"key": "slot:170", "label": "Inv 13", "serial_number": "GR2579042017",
             "capacity_kwp": 375.06},
            {"key": "slot:150", "label": "Inv 01", "serial_number": None,
             "capacity_kwp": 375.06},
        ]},
    ],
    "estacao": {"disponivel": True,
                "colunas": {"poa": True, "ghi": True, "temp_modulo": False,
                            "temp_ambiente": False, "vento": False, "umidade": False},
                "temp_ambiente_rele": True},
    "fronteira": {"leitores": [
        {"id": 14, "name": "Leitor Concessionaria Porto Ferreira SKID 1",
         "wh_per_pulse": 0.3, "rtc": 20.0, "rtp": 70.0},
    ]},
    "sistema": {"pr": True, "produtividade": True},
    "retencao": {"snapshots_desde": "2026-03-06", "ssu_desde": "2024-09-05"},
    "limites": {"native": 7, "5m": 31, "15m": 92, "1h": 366, "1d": 366,
                "max_celulas": 2000000},
}


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


@pytest.fixture
def minha(db, dono, usinas):
    """A usina do dono: Porto Ferreira, `mw_plant_slug='porto-ferreira'`."""
    porto, _outra = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=porto.id))
    db.commit()
    return porto


@pytest.fixture
def alheia(usinas):
    _porto, outra = usinas
    return outra


@pytest.fixture
def acentuada(db, dono, usinas):
    """A segunda usina, no escopo desta pessoa — "Ribeirão Bonito", com til e ã."""
    _porto, outra = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=outra.id))
    db.commit()
    return outra


@pytest.fixture
def ponte(monkeypatch):
    """O cliente REAL do meuWatt, apontado para o endereço de teste e com token fixo.

    Token fixo para não haver login: o que se quer exercitar é o transporte, não a sessão.
    """
    cliente = MeuWattClient(base_url=BASE, token="mw_pat_teste")

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.exportacao.integracoes.cliente_meuwatt", _cliente)
    return cliente


def _sentinela():
    """Uma rota que responde 200 a QUALQUER caminho da mw-api.

    Existe para os testes de "não deve chegar ao upstream" terem prova, e não silêncio: sem
    ela, um pedido que vazasse não casaria com rota nenhuma, o `respx` estouraria, o `except`
    da rota transformaria isso em 502 — e o teste passaria pelo motivo errado. Foi assim que
    a primeira versão do teste do slug envenenado sobreviveu à mutação que apagava a guarda.

    ⛔ Chamada DENTRO do teste, e não numa `fixture`. Fixture roda antes de `@respx.mock`
    tirar o instantâneo do roteador global, então a rota não seria desfeita no fim — este
    coringa vazaria para todos os testes seguintes da sessão e responderia XLSX no lugar do
    JSON que eles esperavam. Aconteceu: metade deste arquivo falhou de uma vez, e a suíte
    pendurou.
    """
    return respx.mock.route(host="api.meuwatt.test").respond(200, content=XLSX)


@pytest.fixture
def pedido():
    return PedidoIn(
        inicio="2026-08-01", fim="2026-08-31", passo="1h",
        inversores={"variaveis": ["geracao"]},
    )


async def _juntar(resposta) -> bytes:
    return b"".join([p async for p in resposta.body_iterator])


# ══════════════════════════════════════════════════════════════════════════════
# Escopo — a recusa antes da rede
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_usina_de_outro_cliente_nao_exporta_e_nem_chega_ao_upstream(
    db, dono, alheia, ponte, pedido
):
    """A planilha é a série histórica inteira de uma usina. Deixar passar aqui é vazamento
    em lote — e conferir depois ainda gastaria a credencial de serviço (e uma das dez vagas
    do minuto) para descobrir o que já se sabia."""
    sentinela = _sentinela()
    for chamada in (
        opcoes_de_exportacao(usina_id=alheia.id, db=db, usuario=dono),
        arquivo_de_dados(pedido=pedido, usina_id=alheia.id, db=db, usuario=dono),
    ):
        with pytest.raises(HTTPException) as e:
            await chamada
        assert e.value.status_code == 404

    assert not sentinela.called


@respx.mock
async def test_usina_monitorada_sem_manutencao_exporta_os_proprios_numeros(
    db, dono, usinas, ponte
):
    """⛔ O portão é o do lado meuWatt, não o da manutenção.

    `_link_do_escopo` (de `manutencao.py`) exige `mp_usina_id` e recusa com "esta usina não
    tem manutenção contratada" — frase e regra de OUTRO produto. Isto aqui é geração: quem só
    tem monitoramento tem direito aos próprios números. Hoje as seis usinas monitoradas do
    banco também têm meuPlano, então o defeito passaria despercebido por muito tempo.
    """
    so_monitorada = PlantLink(
        mw_plant_slug="so-monitorada", mp_usina_id=None, nome="Só monitorada"
    )
    db.add(so_monitorada)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=so_monitorada.id))
    db.commit()
    respx.mock.get(f"{BASE}/plants/so-monitorada/exports/raw/options").respond(
        200, json=OPCOES
    )

    saida = await opcoes_de_exportacao(usina_id=so_monitorada.id, db=db, usuario=dono)

    assert saida.usina.nome == "Só monitorada"


@respx.mock
async def test_usina_sem_monitoramento_diz_isso_e_nao_inventa_uma_url(
    db, dono, usinas, ponte, pedido
):
    """UFV Leme existe no banco com `mw_plant_slug` nulo. Sem esta guarda a URL viraria
    `/plants//exports/raw`, que a mw-api resolveria para outra rota."""
    sentinela = _sentinela()
    sem_ponte = PlantLink(mw_plant_slug=None, mp_usina_id=251, nome="UFV Leme")
    db.add(sem_ponte)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=sem_ponte.id))
    db.commit()

    with pytest.raises(HTTPException) as e:
        await arquivo_de_dados(pedido=pedido, usina_id=sem_ponte.id, db=db, usuario=dono)

    assert e.value.status_code == 404
    assert "monitoramento" in e.value.detail
    assert not sentinela.called


@respx.mock
async def test_slug_torto_no_banco_nao_vira_caminho_para_outra_rota(
    db, dono, ponte, pedido
):
    """A lição de `documents.py`, paga uma vez: o slug é interpolado numa URL da mw-api
    chamada com o PAT do dono, e `../../../admin/users` normaliza para outra rota e devolve
    os bytes. O campo é digitado por gente na tela de Conexões — a defesa tem de existir
    também aqui, no lugar que monta a URL."""
    sentinela = _sentinela()
    envenenada = PlantLink(
        mw_plant_slug="../../../admin/users", mp_usina_id=9, nome="Envenenada"
    )
    db.add(envenenada)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=envenenada.id))
    db.commit()

    with pytest.raises(HTTPException) as e:
        await arquivo_de_dados(pedido=pedido, usina_id=envenenada.id, db=db, usuario=dono)

    assert e.value.status_code == 502
    assert not sentinela.called


# ══════════════════════════════════════════════════════════════════════════════
# Opções
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_opcoes_trazem_o_que_a_usina_tem_com_o_nome_deste_sistema(
    db, dono, minha, ponte
):
    """A tela desabilita o impossível DIZENDO por quê — e para isso precisa saber que esta
    estação mede POA e GHI e não mede vento. O nome é o do vínculo: a mesma usina não pode
    sair com um nome aqui e outro na aba ao lado."""
    respx.mock.get(f"{BASE}/plants/porto-ferreira/exports/raw/options").respond(
        200, json=OPCOES
    )

    saida = await opcoes_de_exportacao(usina_id=minha.id, db=db, usuario=dono)

    assert isinstance(saida, OpcoesOut)
    assert (saida.usina.id, saida.usina.nome) == (minha.id, "Porto Ferreira")
    assert saida.skids[0].nome == "SKID-01"
    assert [s.chave for s in saida.skids[0].series] == ["slot:170", "slot:150"]
    assert saida.skids[0].series[0].rotulo == "Inv 13"
    # `umidade` não é variável exportável e mesmo assim atravessa: `colunas` é dicionário
    # aberto de propósito, senão a chave sumiria em silêncio no dia em que virasse exportável.
    assert saida.estacao.colunas["umidade"] is False
    assert saida.estacao.colunas["poa"] is True
    assert saida.leitores[0].nome.startswith("Leitor Concessionaria")
    assert saida.retencao.snapshots_desde.isoformat() == "2026-03-06"
    # Os tetos vêm do SERVIDOR, não de uma constante nossa: dois números para a mesma
    # pergunta divergiriam no primeiro ajuste feito do outro lado.
    assert saida.limites["5m"] == 31 and saida.limites["max_celulas"] == 2_000_000


@respx.mock
async def test_opcoes_nao_vazam_o_slug_nem_o_nome_do_upstream(db, dono, minha, ponte):
    """O `slug` é transporte para a mw-api, não informação de tela; e o `plant.name` de lá
    é um segundo nome para a mesma usina."""
    respx.mock.get(f"{BASE}/plants/porto-ferreira/exports/raw/options").respond(
        200, json=OPCOES
    )

    corpo = (await opcoes_de_exportacao(usina_id=minha.id, db=db, usuario=dono)).model_dump()

    assert "slug" not in str(corpo)


# ══════════════════════════════════════════════════════════════════════════════
# O pedido que sobe
# ══════════════════════════════════════════════════════════════════════════════


def test_bloco_ausente_nao_viaja_e_series_nula_nao_vira_lista_vazia():
    """⛔ Nulo em `series` é "não mexi", e é diferente de "listei todas": com nulo, o inversor
    comissionado no meio do período entra sozinho. Se o campo viajasse como `null` explícito
    o upstream leria igual — mas um default de lista VAZIA significaria "nenhuma série", um
    arquivo sem coluna nenhuma."""
    # `exclude_none=True` é exatamente o que `MeuWattClient.export_raw` faz com o modelo — é
    # ele que transforma "campo nulo" em "chave ausente", que é a única forma de dizer
    # "bloco fora" no contrato da mw-api.
    corpo = PedidoIn(
        inicio="2026-08-01", fim="2026-08-31", passo="15m",
        inversores={"variaveis": ["geracao", "potencia"], "agrupamento": "skid"},
    ).para_o_upstream().model_dump(mode="json", exclude_none=True)

    assert corpo["start_date"] == "2026-08-01" and corpo["end_date"] == "2026-08-31"
    assert corpo["start_time"] == "00:00" and corpo["end_time"] == "23:59"
    assert corpo["step"] == "15m"
    assert corpo["inversores"] == {
        "variaveis": ["geracao", "potencia"], "agrupamento": "skid"
    }
    assert "series" not in corpo["inversores"]
    for ausente in ("estacao", "fronteira", "sistema"):
        assert ausente not in corpo


def test_horario_impossivel_nao_atravessa():
    """`25:70` chegaria ao upstream como 422 depois de queimar uma das dez vagas do minuto —
    e o BFF não pode ser o lugar por onde entra o que ninguém olhou."""
    with pytest.raises(ValueError):
        PedidoIn(inicio="2026-08-01", fim="2026-08-01", hora_inicio="25:70")


# ══════════════════════════════════════════════════════════════════════════════
# O pedido impossível — recusado AQUI, sem gastar a vaga de todo mundo
# ══════════════════════════════════════════════════════════════════════════════
#
# O DEFEITO QUE ESTA SEÇÃO INTEIRA GUARDA, medido em 05/09/2026: o balde da mw-api é
# `key_func=get_remote_address` — por IP —, todo o portal sai pelo mesmo egress do Railway, e
# **a recusa também consome vaga**. Dez pedidos com a data invertida, que ela devolve em
# milissegundos sem gerar arquivo nenhum, esgotam o minuto; o décimo primeiro pedido —
# válido, de outro cliente — leva 429. O semáforo `_VAGAS` não protege contra isso: a recusa
# atravessa depressa e devolve a vaga na hora. A única defesa é não perguntar.
#
# Por isso cada teste aqui prova DUAS coisas: a resposta certa e o contador do upstream em
# ZERO. Só a primeira metade passaria com a validação feita do outro lado.


@respx.mock
async def test_data_invertida_morre_aqui_e_nao_gasta_vaga_do_balde(db, dono, minha, ponte):
    """DEFEITO: deixar a mw-api recusar o que é aritmética nossa.

    Este é o pedido exato que foi medido a trancar o balde: dez destes, e o décimo primeiro
    cliente do minuto — que pediu certo — leva 429 por culpa de quem brincou com as datas.
    """
    sentinela = _sentinela()
    invertido = PedidoIn(
        inicio="2026-08-31", fim="2026-08-01", passo="1h",
        inversores={"variaveis": ["geracao"]},
    )

    resposta = await arquivo_de_dados(
        pedido=invertido, usina_id=minha.id, db=db, usuario=dono
    )

    assert resposta.status_code == 400
    assert '"motivo":"periodo_invalido"' in resposta.body.decode().replace(", ", ",")
    assert sentinela.call_count == 0, "gastou uma das dez vagas do minuto à toa"


@respx.mock
async def test_periodo_maior_que_o_maior_teto_morre_aqui(db, dono, minha, ponte):
    """DEFEITO: mandar ao upstream um período que NENHUM passo aceita.

    Recusar acima de 366 dias não é adivinhar o teto do servidor — é saber que não existe
    teto que o comporte. O teto POR PASSO continua vindo em `limites`, e é a tela que o
    aplica: repeti-lo aqui daria dois números para a mesma pergunta, e o daqui seria o que
    envelhece calado.
    """
    sentinela = _sentinela()
    dois_anos = PedidoIn(
        inicio="2024-01-01", fim="2026-01-01", passo="1d",
        fronteira={"variaveis": ["energia"]},
    )

    resposta = await arquivo_de_dados(
        pedido=dois_anos, usina_id=minha.id, db=db, usuario=dono
    )

    assert resposta.status_code == 400
    assert '"motivo":"passo_excede_limite"' in resposta.body.decode().replace(", ", ",")
    assert sentinela.call_count == 0


@respx.mock
async def test_o_maior_teto_conhecido_ainda_sobe_e_quem_decide_e_o_servidor(
    db, dono, minha, ponte
):
    """⛔ O CONTRÁRIO do teste acima — e é ele que impede a guarda de virar um muro.

    366 dias é o maior teto da tabela da mw-api (`1h` e `1d`), então um pedido de exatamente
    366 dias **tem de subir**: é lá que se decide se o passo escolhido o comporta. Sem este
    teste, apertar a constante por engano (`>=` no lugar de `>`, ou 365) recusaria aqui um
    pedido perfeitamente válido, e a tela dirá "impossível" sobre algo que o servidor aceita.
    É o modo de falha desta defesa: proteger demais.
    """
    rota = respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        200, content=XLSX
    )
    no_limite = PedidoIn(
        inicio="2025-09-05", fim="2026-09-05", passo="1d",
        fronteira={"variaveis": ["energia"]},
    )
    assert (no_limite.fim - no_limite.inicio).days + 1 == 366

    resposta = await arquivo_de_dados(
        pedido=no_limite, usina_id=minha.id, db=db, usuario=dono
    )

    assert await _juntar(resposta) == XLSX
    assert rota.called, "quem julga o teto por passo é o servidor, não esta guarda"


@respx.mock
async def test_janela_que_fecha_antes_de_abrir_morre_aqui(db, dono, minha, ponte):
    """DEFEITO: subir uma janela vazia — mesmo dia, hora final antes da inicial.

    É a conta de `build_window` do outro lado, e é nossa também: a janela é contínua e o fim
    é inclusivo do minuto, então a inversão só fecha a janela quando as duas datas são o
    mesmo dia. Com o fim um dia à frente, QUALQUER par de horários dá janela positiva — e por
    isso a segunda metade deste teste existe: 18:00 de um dia até 06:00 do seguinte é uma
    noite inteira, e recusá-la seria a guarda protegendo demais.
    """
    sentinela = _sentinela()
    de_tras_para_frente = PedidoIn(
        inicio="2026-08-10", fim="2026-08-10",
        hora_inicio="18:00", hora_fim="06:00", passo="15m",
        inversores={"variaveis": ["geracao"]},
    )

    resposta = await arquivo_de_dados(
        pedido=de_tras_para_frente, usina_id=minha.id, db=db, usuario=dono
    )

    assert resposta.status_code == 400
    assert '"motivo":"periodo_invalido"' in resposta.body.decode().replace(", ", ",")
    assert sentinela.call_count == 0

    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(200, content=XLSX)
    a_noite = PedidoIn(
        inicio="2026-08-10", fim="2026-08-11",
        hora_inicio="18:00", hora_fim="06:00", passo="15m",
        inversores={"variaveis": ["geracao"]},
    )
    assert await _juntar(
        await arquivo_de_dados(pedido=a_noite, usina_id=minha.id, db=db, usuario=dono)
    ) == XLSX


@respx.mock
async def test_pedido_sem_bloco_nenhum_morre_aqui(db, dono, minha, ponte):
    """DEFEITO: gastar 35,6 s do worker único do meuWatt e uma vaga do minuto para descobrir
    que o cliente não escolheu nada.

    Bloco PRESENTE e vazio (`variaveis: []`) morre um degrau antes, no `min_length=1` do
    modelo — a segunda metade deste teste é o que prova que os DOIS caminhos estão fechados.
    """
    sentinela = _sentinela()

    resposta = await arquivo_de_dados(
        pedido=PedidoIn(inicio="2026-08-01", fim="2026-08-31", passo="1d"),
        usina_id=minha.id, db=db, usuario=dono,
    )

    assert resposta.status_code == 400
    assert '"motivo":"sem_blocos"' in resposta.body.decode().replace(", ", ",")
    assert sentinela.call_count == 0

    with pytest.raises(ValueError):
        PedidoIn(inicio="2026-08-01", fim="2026-08-31", inversores={"variaveis": []})
    assert sentinela.call_count == 0


@respx.mock
async def test_periodo_que_comeca_no_futuro_morre_aqui_no_fuso_da_usina(
    db, dono, minha, ponte
):
    """DEFEITO: julgar "futuro" pelo relógio ERRADO.

    O contêiner roda em UTC e as usinas estão em BRT. Com `date.today()`, das 21h à
    meia-noite de Brasília o servidor já virou o dia — e um pedido que começa HOJE seria
    recusado como "no futuro" três horas por noite, todas as noites. É o mesmo defeito que
    `core/datas.py` existe para não repetir, reaparecendo numa guarda nova. Por isso a
    segunda metade: hoje, no fuso da usina, tem de subir.
    """
    sentinela = _sentinela()
    amanha = hoje() + timedelta(days=1)

    resposta = await arquivo_de_dados(
        pedido=PedidoIn(
            inicio=amanha.isoformat(), fim=amanha.isoformat(), passo="1d",
            fronteira={"variaveis": ["energia"]},
        ),
        usina_id=minha.id, db=db, usuario=dono,
    )

    assert resposta.status_code == 400
    assert '"motivo":"periodo_invalido"' in resposta.body.decode().replace(", ", ",")
    assert sentinela.call_count == 0

    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(200, content=XLSX)
    de_hoje = PedidoIn(
        inicio=hoje().isoformat(), fim=hoje().isoformat(), passo="1d",
        fronteira={"variaveis": ["energia"]},
    )
    assert await _juntar(
        await arquivo_de_dados(pedido=de_hoje, usina_id=minha.id, db=db, usuario=dono)
    ) == XLSX


# ══════════════════════════════════════════════════════════════════════════════
# O arquivo
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_a_planilha_atravessa_byte_a_byte(db, dono, minha, ponte, pedido):
    """O XLSX nasce no meuWatt, que tem as séries e a aba "Leia-me" com unidades e fontes —
    é ela que permite a tela ser curta. Aqui os bytes só atravessam."""
    rota = respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        200, content=XLSX,
        headers={"content-type":
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    )

    resposta = await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)

    assert await _juntar(resposta) == XLSX
    assert resposta.media_type.endswith("spreadsheetml.sheet")
    # Content-Length repassado: sem ele a barra do navegador fica cega.
    assert resposta.headers["content-length"] == str(len(XLSX))
    assert resposta.headers["cache-control"] == "no-store"
    # O pedido subiu no vocabulário da mw-api, e o slug veio do banco.
    assert rota.calls.last.request.url.path == "/plants/porto-ferreira/exports/raw"


@respx.mock
async def test_corpo_comprimido_nao_leva_o_tamanho_do_comprimido(
    db, dono, minha, ponte, pedido
):
    """`aiter_bytes` devolve o corpo DECODIFICADO. Repassar o `Content-Length` do comprimido
    faria o navegador cortar a planilha no número prometido — arquivo corrompido, e nenhum
    erro na tela."""
    comprimido = gzip.compress(XLSX)
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        200, content=comprimido,
        headers={"content-encoding": "gzip", "content-length": str(len(comprimido))},
    )

    resposta = await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)

    assert await _juntar(resposta) == XLSX
    assert "content-length" not in resposta.headers


def test_nome_com_til_nao_derruba_a_resposta(acentuada):
    """Cabeçalho HTTP é latin-1 no Starlette: "Ribeirão Bonito" cru estoura
    `UnicodeEncodeError` ao montar o `Content-Disposition` — ANTES do CORS, então o navegador
    vê "falha de rede" e o cliente acusa a própria internet por um defeito do servidor.
    Aconteceu de verdade nas 17 fichas da OS 1016."""
    nome = _nome_do_arquivo(
        acentuada,
        PedidoIn(inicio="2026-08-01", fim="2026-08-31", passo="1h"),
    )

    assert nome == "dados-ribeirao-bonito-2026-08-01_2026-08-31-1h.xlsx"
    nome.encode("latin-1")  # a prova: é isto que o Starlette faz


def test_o_nome_do_arquivo_chega_ao_navegador():
    """Em origem cruzada o navegador ESCONDE do JavaScript todo cabeçalho fora de
    `Access-Control-Expose-Headers`. Sem esta linha o portal recebe os bytes e salva um
    arquivo sem nome."""
    assert "Content-Disposition" in pacotes.CABECALHOS_EXPOSTOS


# ══════════════════════════════════════════════════════════════════════════════
# Os limites — espera, regra e ponte são três coisas
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_limite_de_pedidos_vira_espera_e_nao_erro(db, dono, minha, ponte, pedido):
    """O balde da mw-api é `key_func=get_remote_address` — por IP, não por token —, e todo o
    portal sai pelo mesmo egress do Railway: são 10 exportações por minuto para TODOS os
    clientes somados. Medido em 05/09/2026: o corpo vem em `{"error": …}`, que
    `detalhe_do_upstream` (que lê `detail`/`message`/`erro`) não alcança, e SEM `Retry-After`.

    Sem esta tradução o 429 cairia no ramo genérico e chegaria à tela como 502 "a ponte
    falhou" — mandando o cliente reclamar de um defeito que não existe, quando bastava
    esperar.
    """
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        429, json={"error": "Rate limit exceeded: 10 per 1 minute"}
    )

    resposta = await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)

    assert resposta.status_code == 429
    corpo = resposta.body.decode()
    assert MOTIVO_ESPERA in corpo and "minuto" in corpo
    assert resposta.headers["retry-after"] == "60"


@respx.mock
async def test_regra_violada_preserva_o_motivo_e_nao_ecoa_a_frase_do_operador(
    db, dono, minha, ponte, pedido
):
    """A mw-api recusa com `{"detail": {"motivo", "message"}}` — e o `message` foi escrito
    para o operador DE LÁ, que fala em balde, snapshots e SSU. O que atravessa é o `motivo`,
    num vocabulário fechado; a frase do cliente nasce no portal.

    O código também é preservado: 400 do meuWatt vira 400 daqui. Achatá-lo em 502 faria a
    tela oferecer "Tentar de novo" num `muito_grande` — repetir daria exatamente o mesmo
    resultado, e oferecer o botão seria crueldade.
    """
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        400,
        json={"detail": {"motivo": "muito_grande",
                         "message": "O arquivo teria ≈ 2.400.000 células (limite 2.000.000)."}},
    )

    resposta = await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)

    assert resposta.status_code == 400
    corpo = resposta.body.decode()
    assert '"motivo":"muito_grande"' in corpo.replace(", ", ",")
    assert "células" not in corpo and "2.000.000" not in corpo


@respx.mock
async def test_motivo_desconhecido_nao_atravessa_cru(db, dono, minha, ponte, pedido):
    """Um motivo novo do outro lado chegaria à tela como uma palavra que ela não sabe
    traduzir — e o cliente leria `bloco_estranho` na cara. Nulo é honesto: "recusou, e não
    sabemos dizer por quê nesta versão"."""
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        400, json={"detail": {"motivo": "bloco_estranho", "message": "algo novo"}}
    )

    resposta = await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)

    assert resposta.status_code == 400
    assert '"motivo":null' in resposta.body.decode().replace(", ", ",")


@respx.mock
async def test_queda_do_upstream_continua_sendo_falha_de_ponte(
    db, dono, minha, ponte, pedido
):
    """500 do meuWatt não é regra violada: é a ponte. Confundir os dois faria a tela pedir ao
    cliente que reduzisse o período de um pedido que estava perfeito — e um erro de ponte
    ganha "Tentar de novo", que uma regra violada não pode ganhar.

    O produto é nomeado na frase: sem o `MONITORAMENTO`, uma queda do meuWatt chegaria ao
    portal como "a manutenção respondeu 500", apontando o dedo para o serviço errado.
    """
    rota = respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw")

    rota.respond(500, text="boom")
    with pytest.raises(HTTPException) as e:
        await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)
    assert e.value.status_code == 502
    assert "boom" in e.value.detail  # a frase do upstream sobrevive quando existe

    rota.respond(503, json={})
    with pytest.raises(HTTPException) as e:
        await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)
    assert e.value.status_code == 502
    assert "monitoramento" in e.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# A fila
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_cliente_que_desiste_solta_a_vaga_e_nao_pendura_a_conexao(
    db, dono, minha, ponte, pedido
):
    """A vaga do semáforo é o recurso mais escasso deste caminho: são duas, e o `render.yaml`
    da mw-api fixa `workers=1`. Se ela não fosse solta junto com o fluxo, dois clientes que
    desistem no meio estrangulariam o portal inteiro até o prazo de leitura de 120 s — e a
    conexão com o meuWatt ficaria ocupando uma vaga do keep-alive."""
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(200, content=XLSX)

    resposta = await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)
    corpo = resposta.body_iterator
    assert await corpo.__anext__()  # começou a receber…
    await corpo.aclose()            # …e o cliente sumiu

    # A prova é poder tomar as DUAS vagas de novo, sem esperar.
    for _ in range(2):
        await asyncio.wait_for(_VAGAS.acquire(), 0.5)
    for _ in range(2):
        _VAGAS.release()


@respx.mock
async def test_recusa_do_upstream_tambem_devolve_a_vaga(db, dono, minha, ponte, pedido):
    """O caminho de recusa sai por `return`, não por `yield`: se ele esquecesse de fechar a
    pilha, dez pedidos grandes demais seguidos travariam o portal sem nenhum download ter
    acontecido."""
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(
        400, json={"detail": {"motivo": "sem_blocos", "message": "nada selecionado"}}
    )

    await arquivo_de_dados(pedido=pedido, usina_id=minha.id, db=db, usuario=dono)

    for _ in range(2):
        await asyncio.wait_for(_VAGAS.acquire(), 0.5)
    for _ in range(2):
        _VAGAS.release()


@respx.mock
async def test_o_terceiro_pedido_espera_a_vaga_em_vez_de_correr_junto(
    db, dono, minha, ponte, pedido, monkeypatch
):
    """DEFEITO QUE ESTE TESTE GUARDA: o semáforo existir e não segurar ninguém.

    Sem ele, dez cliques simultâneos no portal viram dez exportações simultâneas contra um
    servidor de **um worker só**, e queimam num golpe as dez vagas do minuto que o meuWatt
    concede ao IP inteiro do portal — o décimo primeiro cliente leva um 429 que não provocou.
    Medido na rota real: três pedidos ao mesmo tempo, os dois primeiros terminam juntos e o
    terceiro só depois que uma vaga volta.

    A prova aqui é de ORDEM, não de tempo: o terceiro não pode ter resposta enquanto os dois
    primeiros seguram as vagas, e tem de recebê-la assim que um deles termina. Cronometrar
    seria medir a máquina; isto mede a fila.
    """
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(200, content=XLSX)
    # Semáforo NOVO, criado no laço deste teste — um `asyncio.Semaphore` só se amarra a um
    # laço quando alguém precisa ESPERAR nele, que é exatamente o que se provoca aqui.
    monkeypatch.setattr("app.api.v1.exportacao._VAGAS", asyncio.Semaphore(2))
    # Curto para o teste falhar depressa se a vaga nunca voltar, em vez de pendurar 45 s.
    monkeypatch.setattr("app.api.v1.exportacao._ESPERA_MAX_SEG", 2.0)

    async def baixar():
        return await arquivo_de_dados(
            pedido=pedido, usina_id=minha.id, db=db, usuario=dono
        )

    # Dois em voo: a vaga só é solta quando o último pedaço do corpo sai.
    primeiro, segundo = await baixar(), await baixar()

    terceiro = asyncio.create_task(baixar())
    await asyncio.sleep(0.1)
    assert not terceiro.done(), "o terceiro correu junto — a fila não segurou ninguém"

    assert await _juntar(primeiro) == XLSX  # uma vaga volta…
    resposta = await asyncio.wait_for(terceiro, 2.0)  # …e o terceiro entra
    assert await _juntar(resposta) == XLSX
    assert resposta.status_code == 200, "esperar não é ser recusado"

    await _juntar(segundo)  # devolve a segunda vaga


@respx.mock
async def test_fila_cheia_responde_espere_em_vez_de_pendurar_o_cliente(
    db, dono, minha, ponte, pedido, monkeypatch
):
    """A espera na fila tem teto — e o teto existe por causa de um defeito REAL.

    Ao ensaiar a mutação que não devolvia a vaga na recusa, a suíte não falhou: ela PAROU.
    Com a espera infinita, uma vaga vazada faz o processo atender dois downloads e nunca mais
    nenhum, sem erro em lugar nenhum e sem nada nos registros — o pior defeito possível,
    porque é invisível. Com teto, o mesmo vazamento vira "tente em um minuto": ruim, mas dito.

    A resposta é a MESMA do 429 do meuWatt de propósito. Para quem pediu é a mesma situação:
    nada quebrou, o pedido continua válido, repetir daqui a pouco funciona.
    """
    respx.mock.post(f"{BASE}/plants/porto-ferreira/exports/raw").respond(200, content=XLSX)
    monkeypatch.setattr("app.api.v1.exportacao._ESPERA_MAX_SEG", 0.05)
    # Um semáforo NOVO, criado dentro do laço deste teste. Um `asyncio.Semaphore` só se
    # amarra a um laço quando alguém precisa ESPERAR nele — e é justamente o que este teste
    # provoca. Usar o do módulo o amarraria ao laço daqui, e o `pytest-asyncio` cria um por
    # teste: o próximo que disputasse a vaga morreria com "bound to a different event loop",
    # um defeito do TESTE que se leria como defeito da rota.
    ocupado = asyncio.Semaphore(2)
    monkeypatch.setattr("app.api.v1.exportacao._VAGAS", ocupado)
    for _ in range(2):  # as duas vagas ocupadas por quem chegou antes
        await ocupado.acquire()

    resposta = await arquivo_de_dados(
        pedido=pedido, usina_id=minha.id, db=db, usuario=dono
    )

    assert resposta.status_code == 429
    assert MOTIVO_ESPERA in resposta.body.decode()
    assert resposta.headers["retry-after"] == "60"
