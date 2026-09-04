"""Os clientes dos upstreams que o portal do cliente consome — só o que é comportamento
DESTE lado, não do produto de origem: o caminho exato, os parâmetros, o que acontece num
redirect e como um envelope vira lista.

Toda resposta é do respx; nenhum teste toca a rede.
"""

import respx
from httpx import Response

from app.clients.meuplano import MeuPlanoClient
from app.clients.meuwatt import MeuWattClient

MP = "https://api.meuplano.test"
MW = "https://api.meuwatt.test"
BUCKET = "https://bucket.armazenamento.test"


def _meuplano() -> MeuPlanoClient:
    return MeuPlanoClient(base_url=MP, token="mp_pat_teste")


def _meuwatt() -> MeuWattClient:
    return MeuWattClient(base_url=MW, token="mw_pat_teste")


@respx.mock
async def test_vc_documento_segue_o_redirect_e_nao_leva_o_bearer_ao_bucket():
    """A rota de download do meuPlano responde 302 para uma URL assinada de OUTRO host.
    O cliente tem de voltar com os bytes do arquivo — e o `Authorization` do meuPlano
    não pode viajar junto: a URL assinada já é a credencial, e o token de serviço num
    log do bucket seria vazamento."""
    respx.mock.get(f"{MP}/api/v1/meuacesso/pipelines/containers/7/documents/9/download").mock(
        return_value=Response(302, headers={"location": f"{BUCKET}/docs/9.pdf?assinatura=x"})
    )
    arquivo = respx.mock.get(f"{BUCKET}/docs/9.pdf").mock(
        return_value=Response(200, content=b"%PDF-1.4 teste",
                              headers={"content-type": "application/pdf"})
    )

    conteudo, tipo = await _meuplano().vc_documento(7, 9)

    assert conteudo.startswith(b"%PDF") and tipo == "application/pdf"
    assert arquivo.called
    assert "authorization" not in arquivo.calls[0].request.headers


@respx.mock
async def test_vc_documento_sem_tipo_declarado_cai_em_octet_stream():
    """Um bucket que não diz o tipo não pode virar `None` no cabeçalho da resposta do
    BFF — o navegador precisa de algum tipo para decidir o que fazer com o arquivo."""
    respx.mock.get(f"{MP}/api/v1/meuacesso/pipelines/containers/7/documents/9/download").mock(
        return_value=Response(200, content=b"xyz", headers={"content-type": ""})
    )

    _, tipo = await _meuplano().vc_documento(7, 9)

    assert tipo in ("", "application/octet-stream")


@respx.mock
async def test_vc_contratos_normaliza_lista_e_envelope():
    """O meuPlano ora devolve lista, ora envelope paginado — o resto do BFF nunca deve
    precisar saber qual dos dois veio."""
    rota = respx.mock.get(f"{MP}/api/v1/meuacesso/visao-cliente/usinas/3/contratos")

    rota.mock(return_value=Response(200, json=[{"id": 1, "versao_consolidada": 2}]))
    assert await _meuplano().vc_contratos(3) == [{"id": 1, "versao_consolidada": 2}]

    rota.mock(return_value=Response(200, json={"items": [{"id": 5}], "total": 1}))
    assert await _meuplano().vc_contratos(3) == [{"id": 5}]

    rota.mock(return_value=Response(200, json={"items": None, "total": 0}))
    assert await _meuplano().vc_contratos(3) == []


@respx.mock
async def test_vc_pendencias_e_vc_pendencia_batem_no_router_visao_cliente():
    """O caminho é o do router que aplica o corte do cliente SEMPRE — nunca o do funil
    interno (`/pipelines/global/pendencia/containers`), que devolve tudo a quem manda."""
    lista = respx.mock.get(f"{MP}/api/v1/meuacesso/visao-cliente/usinas/3/pendencias").mock(
        return_value=Response(200, json=[{"id": 11, "shareable": True}])
    )
    detalhe = respx.mock.get(f"{MP}/api/v1/meuacesso/visao-cliente/pendencias/11").mock(
        return_value=Response(200, json={"id": 11, "documentos": []})
    )

    cliente = _meuplano()
    assert (await cliente.vc_pendencias(3))[0]["id"] == 11
    assert (await cliente.vc_pendencia(11))["id"] == 11
    assert lista.called and detalhe.called
    assert not [c for c in respx.mock.calls if "pipelines/global" in str(c.request.url)]


@respx.mock
async def test_vc_relatorio_so_manda_container_id_quando_escolhido():
    """`container_id=None` não pode ir como texto "None" na URL — o meuPlano leria como
    id inválido e responderia 422 em vez de escolher o contrato consolidado sozinho."""
    rota = respx.mock.get(
        f"{MP}/api/v1/meuacesso/visao-cliente/usinas/3/relatorio-manutencao"
    ).mock(return_value=Response(200, json={"ordens": []}))

    await _meuplano().vc_relatorio(3, "2026-01", "2026-08")
    assert "container_id" not in rota.calls[0].request.url.params
    assert rota.calls[0].request.url.params["de"] == "2026-01"

    await _meuplano().vc_relatorio(3, "2026-01", "2026-08", container_id=42)
    assert rota.calls[1].request.url.params["container_id"] == "42"


@respx.mock
async def test_pvsyst_pede_o_periodo_em_iso_e_devolve_o_envelope_cru():
    """A meta do projeto vem do meuWatt como veio — a soma por recorte é de quem chama,
    e uma resposta sem linhas (`count: 0`) chega intacta para virar "sem meta"."""
    from datetime import date

    rota = respx.mock.get(f"{MW}/plants/porto/pvsyst").mock(
        return_value=Response(200, json={"rows": [], "years": [], "count": 0})
    )

    dados = await _meuwatt().pvsyst("porto", date(2026, 8, 1), date(2026, 8, 31))

    assert dados["count"] == 0 and dados["rows"] == []
    params = rota.calls[0].request.url.params
    assert params["start"] == "2026-08-01" and params["end"] == "2026-08-31"


@respx.mock
async def test_alertas_pede_uma_pagina_com_limite_e_offset():
    """Sem `limit` o upstream corta em 100 calado; o cliente sempre pede a página inteira
    e deixa o `offset` explícito para `alertas_todos` avançar."""
    rota = respx.mock.get(f"{MW}/plants/porto/alerts").mock(
        return_value=Response(200, json={"plant": "porto", "total": 0, "alerts": []})
    )

    await _meuwatt().alertas("porto", status="all", offset=500)

    params = rota.calls[0].request.url.params
    assert params["status"] == "all" and params["limit"] == "500" and params["offset"] == "500"


@respx.mock
async def test_alertas_todos_avanca_o_offset_ate_a_pagina_vir_incompleta():
    """Duas páginas (500 cheia + 3) têm de virar 503 eventos com DUAS idas ao upstream —
    nem uma a menos (a usina com 130 paradas que chegava com 30 a menos) nem uma a mais
    (uma terceira página vazia pedida à toa)."""
    cheia = [{"id": i, "kind": "stop"} for i in range(500)]
    resto = [{"id": 500 + i, "kind": "stop"} for i in range(3)]

    def por_offset(request):
        offset = int(request.url.params.get("offset", "0"))
        pagina = cheia if offset == 0 else resto if offset == 500 else []
        return Response(200, json={"plant": "porto", "total": 503, "alerts": pagina})

    rota = respx.mock.get(f"{MW}/plants/porto/alerts").mock(side_effect=por_offset)

    todos = await _meuwatt().alertas_todos("porto", status="all")

    assert len(todos) == 503 and todos[-1]["id"] == 502
    assert [c.request.url.params["offset"] for c in rota.calls] == ["0", "500"]


@respx.mock
async def test_alertas_todos_para_no_teto_se_o_upstream_nunca_esvazia():
    """Um upstream que devolvesse sempre uma página cheia (offset ignorado) prenderia o
    cliente num laço infinito. O teto de 20 páginas é a proteção — e vale mais que a
    completude: dez mil eventos é mais do que qualquer usina acumulou."""
    cheia = [{"id": i} for i in range(500)]
    rota = respx.mock.get(f"{MW}/plants/porto/alerts").mock(
        return_value=Response(200, json={"plant": "porto", "total": 999999, "alerts": cheia})
    )

    todos = await _meuwatt().alertas_todos("porto", status="all")

    assert rota.call_count == 20 and len(todos) == 20 * 500


@respx.mock
async def test_alertas_todos_com_resposta_sem_lista_devolve_vazio_e_nao_estoura():
    """Uma resposta com formato inesperado (envelope sem `alerts`) é "nada veio", não uma
    exceção: a fonte reserva das paradas precisa degradar em aviso, não em 502."""
    respx.mock.get(f"{MW}/plants/porto/alerts").mock(
        return_value=Response(200, json={"plant": "porto"})
    )

    assert await _meuwatt().alertas_todos("porto", status="all") == []
