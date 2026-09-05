"""Baixar TODAS as fichas de um período — o pacote de PDFs da manutenção.

O dono (04/09/2026): *"eu fiz a inspeção de agosto de Porto Ferreira; de alguma forma eu
preciso conseguir baixar TODOS os PDFs das tarefas. Se eu fizer corretiva, quero poder ver
também. Preciso de filtros."*

O que estes testes protegem, em ordem de gravidade:

1. **A usina tem de ser desta pessoa** — e a recusa acontece ANTES de qualquer ida ao
   upstream. Um pacote é um monte de laudos assinados de uma vez; deixar passar aqui é
   vazamento em lote, e a checagem tardia ainda gastaria a credencial de serviço para
   descobrir o que já se sabia.
2. **O ZIP é repassado, não remontado.** Os bytes que o cliente arquiva têm de ser os que o
   meuPlano gerou — reembalar aqui significaria abrir cada PDF e assinar de novo por eles.
3. **Os cabeçalhos chegam ao navegador.** Em origem cruzada, cabeçalho fora de
   `Access-Control-Expose-Headers` é invisível ao JavaScript: o portal baixaria a parte 1
   de 2 sem descobrir que existe uma parte 2.
4. **Nome de arquivo não derruba a resposta.** Cabeçalho HTTP é latin-1 no Starlette, e
   "Ribeirão Bonito" já derrubou a ficha em PDF uma vez — antes do CORS, fazendo a tela
   acusar a internet do cliente por um defeito nosso.
5. **Falha do upstream vira a frase certa.** 404 é "não há ficha neste filtro"; um 500 é
   erro de ponte, e confundi-los manda o cliente procurar o que não existe.

Nada de rede: o meuPlano entra por `respx`, com o cliente REAL por cima — assim o caminho
de fluxo (`httpx.stream`) é exercitado de verdade, e não uma fantasia dele.
"""

import gzip

import httpx
import pytest
import respx
from fastapi import HTTPException

from app.api.v1.pacotes import (
    CABECALHOS_EXPOSTOS,
    _nome_do_pacote,
    andamento_do_preparo,
    inventario_de_fichas,
    pacote_de_fichas,
    preparar_fichas,
)
from app.clients.meuplano import MeuPlanoClient
from app.core.security import gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

BASE = "https://api.meuplano.test"
VC = f"{BASE}/api/v1/meuacesso/visao-cliente/usinas"

#: Um ZIP de mentira, mas com a assinatura de verdade — é o que se compara byte a byte.
ZIP = b"PK\x03\x04" + b"o pacote inteiro, exatamente como o meuPlano montou" * 40


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
    """A usina do dono (Porto Ferreira, `mp_usina_id=1`). A outra fica fora do escopo."""
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
    """O cliente REAL do meuPlano, apontado para o endereço de teste e com token fixo.

    Token fixo para não haver login: o que se quer exercitar é o transporte, não a sessão.
    """
    cliente = MeuPlanoClient(base_url=BASE, token="mp_pat_teste")

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.pacotes.integracoes.cliente_meuplano", _cliente)
    return cliente


#: O índice como o meuPlano o devolve — uma OS preventiva e uma corretiva avulsa.
INDICE = {
    "ordens": [
        {
            "os_id": 1016,
            "numero": 665,
            "classificacao": "PREVENTIVA",
            "situacao": "EM_EXECUCAO",
            "data_efetiva": "2026-08-14T09:00:00",
            "titulo": "O&M mensal",
            "task_count": 2,
            "task_realized_count": 2,
            "tarefas": [
                {"task_id": 6710, "nome": "Inversores — 08/2026",
                 "equipamento": "Skid 01 > INV-01", "status": "REALIZADA",
                 "pronta": True, "bytes": 2_686_172},
                {"task_id": 6711, "nome": "Cercamento — 08/2026",
                 "equipamento": "Perímetro", "status": "REALIZADA",
                 "pronta": False, "bytes": None},
            ],
        },
        {
            "os_id": 1044,
            "classificacao": "CORRETIVA",
            "situacao": "APROVADA",
            "data_efetiva": "2026-08-22T15:30:00",
            "titulo": "Troca de fusível",
            "tarefas": [{"task_id": 7001, "nome": "Substituição", "pronta": True,
                         "bytes": 120_000}],
        },
    ],
    "total_fichas": 3,
    "prontas": 2,
    "bytes_estimados": 2_806_172,
    "total_sem_filtro": 3,
    "partes": [{"numero": 1, "fichas": 3, "bytes": 2_806_172}],
}


# ══════════════════════════════════════════════════════════════════════════════
# A cerca
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_usina_de_outro_cliente_e_404_sem_tocar_no_upstream(db, dono, alheia, ponte):
    """404 e não 403: dizer "proibido" confirmaria que a usina existe. E a prova de que
    a recusa é local é o que NÃO foi para a rede."""
    with pytest.raises(HTTPException) as e:
        await inventario_de_fichas(usina_id=alheia.id, de="2026-08", ate="2026-08",
                                   db=db, usuario=dono)

    assert e.value.status_code == 404
    assert respx.mock.calls.call_count == 0


@respx.mock
async def test_o_pacote_de_outra_usina_tambem_para_aqui(db, dono, alheia, ponte):
    """O download é o caminho que mais dói se escapar: um ZIP é um monte de laudos."""
    with pytest.raises(HTTPException) as e:
        await pacote_de_fichas(usina_id=alheia.id, de="2026-08", ate="2026-08",
                               db=db, usuario=dono)

    assert e.value.status_code == 404
    assert respx.mock.calls.call_count == 0


@respx.mock
async def test_o_andamento_do_preparo_passa_pelo_mesmo_portao(db, dono, alheia, ponte):
    """Sem esta checagem, trocar o número do preparo devolveria o andamento — e os ids de
    tarefa — do pacote de outro cliente."""
    with pytest.raises(HTTPException) as e:
        await andamento_do_preparo(preparo_id="abc", usina_id=alheia.id, db=db, usuario=dono)

    assert e.value.status_code == 404
    assert respx.mock.calls.call_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# Inventário
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_inventario_lista_as_fichas_com_a_classificacao_traduzida(db, dono, minha, ponte):
    """`SERVICOS_ADICIONAIS` cru já chegou à tela do relatório ao lado da mesma OS
    traduzida na lista de ordens. Aqui a tradução é a MESMA de `manutencao.py`."""
    rota = respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas").respond(200, json=INDICE)

    saida = await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                       db=db, usuario=dono)

    assert saida.total == 3 and saida.prontas == 2
    assert [o.os_id for o in saida.ordens] == [1016, 1044]
    # O nome vem de `titulo`, que é como o índice do meuPlano o entrega — parar em
    # `name`/`objetivo` faria a lista inteira sair como "OS 1016", "OS 1044".
    assert [o.objetivo for o in saida.ordens] == ["O&M mensal", "Troca de fusível"]
    assert saida.ordens[0].classificacao == "Preventiva"
    assert saida.ordens[0].classificacao_codigo == "PREVENTIVA"
    assert saida.ordens[1].classificacao == "Corretiva"
    # A régua da situação é a da aba Ordens, com contagem de tarefa e tudo.
    assert saida.ordens[0].situacao == "Executada · aguardando verificação"
    assert saida.ordens[1].situacao == "Concluída"
    # A ficha que ainda não tem PDF aparece, e diz que não tem.
    assert [f.pronta for f in saida.ordens[0].fichas] == [True, False]
    assert saida.ordens[0].fichas[1].bytes is None
    assert saida.partes and saida.partes[0].numero == 1
    # O período conferido aqui é o que foi para o upstream.
    params = rota.calls.last.request.url.params
    assert params["de"] == "2026-08" and params["ate"] == "2026-08"


@respx.mock
async def test_um_numero_ambiguo_nao_vira_numero_de_contrato(db, dono, minha, ponte):
    """A OS 1016 do índice traz `numero: 665` e nenhum `contrato_numero`. Adivinhar já
    custou caro: o drawer da pendência imprimia "OS #665" para o contrato 665 enquanto a
    lista chamava a MESMA ordem de "OS 1016" — toda ordem daquele contrato virava a mesma."""
    ordens = [
        INDICE["ordens"][0],
        {**INDICE["ordens"][1], "contrato_numero": 665},
    ]
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas").respond(
        200, json={**INDICE, "ordens": ordens}
    )

    saida = await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                       db=db, usuario=dono)

    assert saida.ordens[0].contrato_numero is None
    assert saida.ordens[1].contrato_numero == 665


@respx.mock
async def test_filtro_de_corretiva_chega_ao_upstream(db, dono, minha, ponte):
    """*"Se eu fizer corretiva, quero poder ver também."* O eixo de período do índice é o
    do relatório, não `contract_month` — que é nulo em corretiva avulsa e devolveria vazio."""
    rota = respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas").respond(
        200,
        json={**INDICE, "ordens": [INDICE["ordens"][1]], "total_fichas": 1, "prontas": 1,
              "total_sem_filtro": 3},
    )

    saida = await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                       classificacao="corretiva", db=db, usuario=dono)

    assert rota.calls.last.request.url.params["classificacao"] == "CORRETIVA"
    assert saida.total == 1
    assert saida.filtros["classificacao"] == "CORRETIVA"


@respx.mock
async def test_filtro_desconhecido_e_recusado_antes_do_upstream(db, dono, minha, ponte):
    """400 com a frase daqui, e não um 422 do meuPlano achatado em 502 sem dizer o quê.
    E o valor nunca vira parâmetro de uma rota dele feita com a nossa credencial."""
    for campo, valor in (("classificacao", "urgentissima"), ("situacao", "quase")):
        with pytest.raises(HTTPException) as e:
            await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                       db=db, usuario=dono, **{campo: valor})
        assert e.value.status_code == 400 and campo in e.value.detail

    assert respx.mock.calls.call_count == 0


@respx.mock
async def test_filtro_que_zera_diz_que_foi_o_filtro(db, dono, minha, ponte):
    """"Nenhuma ficha neste filtro" e "nenhuma ficha no período" mandam o cliente fazer
    coisas diferentes — limpar o filtro ou procurar outro mês."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas").respond(
        200, json={"ordens": [], "total_fichas": 0, "prontas": 0, "total_sem_filtro": 17}
    )

    saida = await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                       busca="turbina", db=db, usuario=dono)

    assert saida.total == 0 and saida.total_sem_filtro == 17
    assert saida.aviso == "Nenhuma ficha neste filtro."


@respx.mock
async def test_indice_sem_partes_ainda_oferece_um_download(db, dono, minha, ponte):
    """Sem esta rede, um upstream que não calcule partes deixaria o portal com o
    inventário cheio e nenhum botão de baixar."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas").respond(
        200, json={k: v for k, v in INDICE.items() if k != "partes"}
    )

    saida = await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                       db=db, usuario=dono)

    assert [p.numero for p in saida.partes] == [1]
    assert saida.partes[0].fichas == 3


@respx.mock
async def test_periodo_invalido_para_antes_do_upstream(db, dono, minha, ponte):
    """A mesma régua do relatório de manutenção — 24 meses, sem mês futuro, `de` antes de
    `ate`. Uma segunda cópia divergiria da tela ao lado."""
    with pytest.raises(HTTPException) as e:
        await inventario_de_fichas(usina_id=minha.id, de="2026-09", ate="2026-08",
                                   db=db, usuario=dono)
    assert e.value.status_code == 400
    assert respx.mock.calls.call_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# Preparo
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_preparar_devolve_o_numero_de_acompanhamento(db, dono, minha, ponte):
    rota = respx.mock.post(f"{VC}/{minha.mp_usina_id}/fichas/preparar").respond(
        200, json={"preparo_id": "p-9", "total": 17, "prontas": 14}
    )

    saida = await preparar_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                  db=db, usuario=dono)

    assert saida.preparo_id == "p-9" and saida.total == 17 and saida.prontas == 14
    assert saida.concluido is False
    assert rota.calls.last.request.url.params["de"] == "2026-08"


@respx.mock
async def test_preparo_chega_a_dezessete_de_dezessete(db, dono, minha, ponte):
    """O caso do dono: a OS 1016 tem 17 tarefas, e "todos" quer dizer 17."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/preparo/p-9").respond(
        200, json={"total": 17, "prontas": 17, "concluido": True, "erros": []}
    )

    saida = await andamento_do_preparo(preparo_id="p-9", usina_id=minha.id,
                                       db=db, usuario=dono)

    assert (saida.prontas, saida.total) == (17, 17)
    assert saida.concluido is True and saida.aviso is None


@respx.mock
async def test_ficha_que_nao_gerou_aparece_escrita(db, dono, minha, ponte):
    """Omitir seria voltar ao "baixei todos e vieram três": o portal precisa dizer qual
    ficha ficou de fora, e por quê."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/preparo/p-9").respond(
        200,
        json={"total": 17, "prontas": 16, "concluido": True,
              "erros": [{"task_id": 6711, "motivo": "o arquivo sumiu do armazenamento"}]},
    )

    saida = await andamento_do_preparo(preparo_id="p-9", usina_id=minha.id,
                                       db=db, usuario=dono)

    assert saida.erros[0]["task_id"] == 6711
    assert saida.aviso and "sai sem" in saida.aviso


@respx.mock
async def test_preparo_que_parou_no_meio_nao_se_diz_pronto(db, dono, minha, ponte):
    """`concluido` sozinho engana: o meuPlano marca o preparo abandonado como encerrado
    com um `erro`. Sem o estado próprio, a tela ofereceria o download de um pacote com
    menos fichas do que o cliente pediu — em silêncio."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/preparo/p-9").respond(
        200,
        json={"total": 17, "prontas": 9, "concluido": True, "status": "error",
              "erro": "o preparo parou sem terminar — peça de novo", "expira_em": 1800},
    )

    saida = await andamento_do_preparo(preparo_id="p-9", usina_id=minha.id,
                                       db=db, usuario=dono)

    assert saida.estado == "falhou"
    assert saida.erro and "peça de novo" in saida.erro
    assert saida.aviso == saida.erro
    assert saida.expira_em == 1800


@respx.mock
async def test_preparo_ja_em_andamento_nao_se_diz_novo(db, dono, minha, ponte):
    """Pedido IGUAL enquanto um roda devolve o MESMO número. O portal reconecta ao
    andamento em vez de anunciar que começou algo — e não duplica o trabalho lá."""
    respx.mock.post(f"{VC}/{minha.mp_usina_id}/fichas/preparar").respond(
        200, json={"preparo_id": "p-9", "total": 17, "prontas": 5, "ja_em_andamento": True}
    )

    saida = await preparar_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                  db=db, usuario=dono)

    assert saida.ja_em_andamento is True and saida.preparo_id == "p-9"


@respx.mock
async def test_outro_preparo_em_curso_e_409_com_a_frase_do_meuplano(db, dono, minha, ponte):
    """409 é estado, não defeito: dois preparos em paralelo gerariam a mesma ficha duas
    vezes. Achatá-lo num 502 mandaria o cliente procurar um problema que não existe."""
    respx.mock.post(f"{VC}/{minha.mp_usina_id}/fichas/preparar").respond(
        409, json={"detail": "Já há um preparo de fichas em andamento nesta usina."}
    )

    with pytest.raises(HTTPException) as e:
        await preparar_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                              db=db, usuario=dono)

    assert e.value.status_code == 409
    assert "em andamento" in e.value.detail


@respx.mock
async def test_periodo_sem_ficha_para_de_preparar_com_a_frase_do_meuplano(db, dono, minha, ponte):
    """404 do upstream passa com a frase dele: "não há o que preparar" é uma resposta,
    não uma falha da ponte."""
    respx.mock.post(f"{VC}/{minha.mp_usina_id}/fichas/preparar").respond(
        404, json={"detail": "Nenhuma ficha no período com estes filtros."}
    )

    with pytest.raises(HTTPException) as e:
        await preparar_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                              db=db, usuario=dono)

    assert e.value.status_code == 404 and "Nenhuma ficha" in e.value.detail


@respx.mock
async def test_preparo_expirado_manda_preparar_de_novo(db, dono, minha, ponte):
    """O meuPlano guarda o preparo em memória, com prazo. Expirar não é defeito — e o que
    já foi gerado é reaproveitado por impressão digital."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/preparo/p-9").respond(
        404, json={"detail": "job desconhecido"}
    )

    with pytest.raises(HTTPException) as e:
        await andamento_do_preparo(preparo_id="p-9", usina_id=minha.id, db=db, usuario=dono)

    assert e.value.status_code == 404 and "de novo" in e.value.detail


@respx.mock
async def test_andamento_conferido_noutra_replica_chega_com_a_saida_a_mao(db, dono, minha, ponte):
    """O meuPlano roda com mais de uma réplica e o preparo vive na memória de quem o abriu.
    Quando o poll cai noutra instância, ela CONFERE o andamento no armazenamento em vez de
    dar 404 — e diz que conferiu. A tela precisa dos dois campos: o número, que é verdadeiro,
    e o aviso, que é o que lhe permite oferecer "preparar de novo" em vez de girar sem fim
    atrás de um trabalho que pode ter morrido junto com a réplica."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/preparo/p-9").respond(
        200,
        json={"total": 17, "prontas": 14, "concluido": False, "status": "running",
              "conferido_no_armazenamento": True,
              "aviso": "Andamento conferido no armazenamento (quem está preparando é outro "
                       "servidor). Se o número parar de subir, peça para preparar de novo."},
    )

    saida = await andamento_do_preparo(preparo_id="p-9", usina_id=minha.id,
                                       db=db, usuario=dono)

    assert saida.conferido_no_armazenamento is True
    assert saida.estado == "andando" and saida.prontas == 14 and saida.total == 17
    assert saida.aviso and "outro servidor" in saida.aviso


# ══════════════════════════════════════════════════════════════════════════════
# O pacote
# ══════════════════════════════════════════════════════════════════════════════


async def _juntar(resposta) -> bytes:
    return b"".join([p async for p in resposta.body_iterator])


@respx.mock
async def test_o_zip_atravessa_byte_a_byte(db, dono, minha, ponte):
    """Nada de reembalar: o pacote é o documento que o cliente arquiva, e os bytes que ele
    recebe têm de ser os que o meuPlano gerou."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        200,
        content=ZIP,
        headers={"content-type": "application/zip", "X-Incluidos": "17",
                 "X-Omitidos": "0", "X-Partes": "1", "content-length": str(len(ZIP))},
    )

    resposta = await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                      db=db, usuario=dono)

    assert await _juntar(resposta) == ZIP
    assert resposta.media_type == "application/zip"
    # Content-Length repassado: sem ele a barra do navegador fica cega num arquivo grande.
    assert resposta.headers["content-length"] == str(len(ZIP))


@respx.mock
async def test_corpo_comprimido_nao_leva_o_tamanho_do_comprimido(db, dono, minha, ponte):
    """`aiter_bytes` devolve o corpo DECODIFICADO. Repassar o `Content-Length` do
    comprimido faria o navegador cortar o ZIP no número prometido — arquivo corrompido,
    sem nenhum erro na tela."""
    comprimido = gzip.compress(ZIP)
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        200, content=comprimido,
        headers={"content-encoding": "gzip", "content-length": str(len(comprimido))},
    )

    resposta = await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                      db=db, usuario=dono)
    corpo = await _juntar(resposta)

    assert corpo == ZIP
    assert "content-length" not in resposta.headers


@respx.mock
async def test_cliente_que_desiste_no_meio_nao_deixa_conexao_pendurada(db, dono, minha, ponte):
    """Num pacote de dezenas de megabytes o cliente desiste — e o contexto do fluxo tem de
    fechar com o gerador, senão a conexão com o meuPlano fica ocupando uma vaga do
    keep-alive até o prazo de leitura de cinco minutos."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        200, content=ZIP
    )

    resposta = await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                      db=db, usuario=dono)
    corpo = resposta.body_iterator
    assert await corpo.__anext__()  # começou a receber…
    await corpo.aclose()            # …e o cliente sumiu

    # A prova é o silêncio: fechar de novo não estoura, e o fluxo já foi encerrado.
    await corpo.aclose()


@respx.mock
async def test_as_contagens_e_a_parte_chegam_ao_cliente(db, dono, minha, ponte):
    """E declaradas em `Access-Control-Expose-Headers`: o portal roda em outro domínio, e
    cabeçalho fora dessa lista o navegador simplesmente esconde do JavaScript."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        200, content=ZIP,
        headers={"X-Incluidos": "9", "X-Omitidos": "1", "X-Partes": "2",
                 "X-Total-Fichas": "17"},
    )

    resposta = await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                      parte=2, db=db, usuario=dono)
    await _juntar(resposta)

    assert resposta.headers["x-incluidos"] == "9"
    assert resposta.headers["x-omitidos"] == "1"
    assert resposta.headers["x-parte"] == "2"
    assert resposta.headers["x-partes"] == "2"
    # É por `X-Total-Fichas`, repetido em toda parte, que o portal confere que a soma do
    # que baixou fecha com o que o inventário prometeu.
    assert resposta.headers["x-total-fichas"] == "17"
    expostos = resposta.headers["access-control-expose-headers"]
    for nome in ("X-Incluidos", "X-Omitidos", "X-Parte", "X-Partes", "X-Total-Fichas",
                 "Content-Disposition"):
        assert nome in expostos


def test_o_cors_do_servico_expoe_os_mesmos_cabecalhos():
    """A lista tem UMA fonte. Duas divergiriam no dia em que um cabeçalho fosse
    acrescentado — e a falha seria invisível: o corpo chega, o cabeçalho some."""
    from app.main import app

    cors = next(m for m in app.user_middleware if "CORSMiddleware" in str(m))
    assert cors.kwargs["expose_headers"] == CABECALHOS_EXPOSTOS
    assert "X-Partes" in CABECALHOS_EXPOSTOS


@respx.mock
async def test_a_parte_pedida_vai_para_o_upstream(db, dono, minha, ponte):
    rota = respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        200, content=ZIP, headers={"X-Partes": "3"}
    )

    resposta = await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                      parte=3, classificacao="corretiva", db=db, usuario=dono)
    await _juntar(resposta)

    params = rota.calls.last.request.url.params
    assert params["parte"] == "3" and params["classificacao"] == "CORRETIVA"


@respx.mock
async def test_nome_de_usina_com_acento_produz_cabecalho_valido(db, dono, usinas, ponte):
    """"Ribeirão Bonito" num cabeçalho latin-1 é o defeito que já derrubou a ficha em PDF —
    e, por subir antes do CORS, fazia o portal culpar a internet do cliente."""
    _porto, outra = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=outra.id))
    db.commit()
    respx.mock.get(f"{VC}/{outra.mp_usina_id}/fichas/pacote/view").respond(
        200, content=ZIP, headers={"X-Partes": "2"}
    )

    resposta = await pacote_de_fichas(usina_id=outra.id, de="2026-07", ate="2026-08",
                                      parte=1, db=db, usuario=dono)
    await _juntar(resposta)

    cabecalho = resposta.headers["content-disposition"]
    cabecalho.encode("latin-1")  # não estoura: é o que o protocolo aceita
    assert 'filename="fichas-ribeirao-bonito-2026-07_2026-08-parte1de2.zip"' in cabecalho
    assert "filename*=UTF-8''" in cabecalho


def test_o_nome_do_pacote_omite_a_parte_quando_ha_uma_so():
    """"parte1de1" no nome faria o cliente procurar a parte 2 que não existe."""
    from app.models.plant import PlantLink

    link = PlantLink(mw_plant_slug="porto-ferreira", mp_usina_id=1, nome="Porto Ferreira")
    assert _nome_do_pacote(link, "2026-08", "2026-08", 1, 1) == "fichas-porto-ferreira-2026-08.zip"
    assert _nome_do_pacote(link, "2026-01", "2026-08", 2, 4).endswith("-parte2de4.zip")


# ══════════════════════════════════════════════════════════════════════════════
# Quando o meuPlano recusa
# ══════════════════════════════════════════════════════════════════════════════


@respx.mock
async def test_404_do_upstream_vira_frase_propria(db, dono, minha, ponte):
    """"Não existe pacote" é uma resposta que o cliente precisa ler literalmente — e não
    pode chegar como "erro ao baixar", que manda procurar defeito onde não há."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        404, json={"detail": "nenhuma ficha no período"}
    )

    with pytest.raises(HTTPException) as e:
        await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                               db=db, usuario=dono)

    assert e.value.status_code == 404
    # A frase é a DELE: o 404 tanto pode ser "nenhuma ficha" quanto "esta parte não
    # existe", e escolher uma aqui mandaria metade dos casos procurar a coisa errada.
    assert e.value.detail == "nenhuma ficha no período"


@respx.mock
async def test_parte_que_nao_existe_diz_isso_e_nao_outra_coisa(db, dono, minha, ponte):
    """Pedir a parte 5 de um pacote de 2 é engano do cliente, e ele precisa ler qual foi."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(
        404, json={"detail": "Este pacote tem 2 partes; a 5 não existe."}
    )

    with pytest.raises(HTTPException) as e:
        await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                               parte=5, db=db, usuario=dono)

    assert e.value.status_code == 404 and "2 partes" in e.value.detail


@respx.mock
async def test_defeito_do_upstream_e_erro_de_ponte_nao_ausencia(db, dono, minha, ponte):
    """500 do meuPlano é falha da ponte (502 pela régua única de `_erro_do_upstream`), não
    "não encontrado" — confundir os dois manda o cliente desistir de um pacote que existe."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").respond(500)

    with pytest.raises(HTTPException) as e:
        await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                               db=db, usuario=dono)

    assert e.value.status_code == 502
    assert e.value.status_code != 404


@respx.mock
async def test_upstream_que_nao_responde_vira_504(db, dono, minha, ponte):
    """Prazo de leitura de 300 s existe porque o pacote demora a começar; estourá-lo é
    "demorou demais", não "quebrou"."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas/pacote/view").mock(
        side_effect=httpx.ReadTimeout("demorou")
    )

    with pytest.raises(HTTPException) as e:
        await pacote_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                               db=db, usuario=dono)

    assert e.value.status_code == 504


@respx.mock
async def test_indice_em_formato_desconhecido_nao_vira_tela_vazia(db, dono, minha, ponte):
    """Uma lista onde se esperava um objeto significa que o contrato mudou. Devolver
    inventário zerado esconderia isso atrás de "não há ficha neste período"."""
    respx.mock.get(f"{VC}/{minha.mp_usina_id}/fichas").respond(200, json=[])

    with pytest.raises(HTTPException) as e:
        await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                   db=db, usuario=dono)

    assert e.value.status_code == 502


async def test_sem_ponte_configurada_a_tela_sabe_o_que_falta(db, dono, minha, monkeypatch):
    """503 e a frase do que falta — não um 500 genérico que manda investigar o servidor."""
    async def _sem_ponte(_db):
        raise RuntimeError("A ponte com o meuPlano não está configurada.")

    monkeypatch.setattr("app.api.v1.pacotes.integracoes.cliente_meuplano", _sem_ponte)

    with pytest.raises(HTTPException) as e:
        await inventario_de_fichas(usina_id=minha.id, de="2026-08", ate="2026-08",
                                   db=db, usuario=dono)

    assert e.value.status_code == 503 and "não está configurada" in e.value.detail
