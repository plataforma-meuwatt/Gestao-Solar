"""O download de relatório não pode virar uma chave-mestra da mw-api.

Em auditoria independente descobriu-se que `GET /api/v1/documents/{id}/file` aceitava
`?tipo=` como texto livre, e esse texto ia parar na URL do upstream:

    f"{base_url}/reports/{report_id}/files/{kind}"

A chamada usa o token de serviço, que costuma ser de **administrador**. Com
`tipo=../../../admin/users`, a URL normaliza para outra rota da mw-api e os bytes voltam
para o cliente. Um único documento em mãos dava a qualquer cliente autenticado leitura da
plataforma inteira — usinas de todos os outros, usuários, tudo — contornando de uma vez
toda a disciplina de escopo do resto do BFF.

A travessia é o que estes testes protegem. São dois níveis de propósito: a rota recusa
pelo tipo (`Literal`), e o cliente recusa de novo — para que um chamador futuro não
reabra o buraco sem perceber.
"""

import pytest

from app.clients.meuwatt import MeuWattClient, MeuWattError

#: O ataque real, verificado contra o httpx do projeto: normaliza para /admin/users.
TRAVESSIA = "../../../admin/users"


@pytest.fixture
def cliente() -> MeuWattClient:
    return MeuWattClient(base_url="https://api.meuwatt.com.br", token="pat_qualquer")


@pytest.mark.asyncio
async def test_travessia_de_caminho_e_recusada(cliente):
    """O caso que estava aberto. Recusa ANTES de qualquer rede."""
    with pytest.raises(MeuWattError):
        await cliente.arquivo_relatorio(5, TRAVESSIA)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "peca",
    [
        "../admin",
        "..%2f..%2fadmin",
        "geracao/../../plants",
        "",
        "GERACAO",  # o upstream distingue caixa; aceitar aqui mascararia um 404
        "relatorio.pdf",
    ],
)
async def test_qualquer_peca_fora_da_lista_e_recusada(cliente, peca):
    with pytest.raises(MeuWattError):
        await cliente.arquivo_relatorio(5, peca)


def test_as_pecas_validas_sao_as_duas_do_fechamento():
    """Um fechamento tem duas peças, e a lista é fechada por isso — não por precaução
    genérica. Se o meuWatt passar a publicar uma terceira, ela entra aqui de propósito."""
    assert set(MeuWattClient.PECAS) == {"geracao", "paradas"}


def test_a_rota_do_app_tambem_fecha_o_tipo():
    """Defesa em profundidade: a rota recusa pelo tipo antes mesmo de o cliente ser
    chamado. Verifica a assinatura, porque é ela que o FastAPI usa para validar."""
    import typing

    from app.api.v1.documents import arquivo_do_documento

    anotacao = typing.get_type_hints(arquivo_do_documento)["tipo"]

    assert typing.get_origin(anotacao) is typing.Literal, (
        "o parâmetro `tipo` voltou a ser texto livre — é ele que entra na URL do upstream"
    )
    assert set(typing.get_args(anotacao)) == {"geracao", "paradas"}
