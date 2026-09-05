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


def test_as_pecas_validas_sao_as_tres_do_fechamento():
    """Um fechamento tem três peças, e a lista é fechada por isso — não por precaução
    genérica. O Resumo Executivo era a terceira que o docstring antigo antecipava: a
    mw-api já a publicava (`_FILE_KINDS`) e o download daqui a recusava. Ela entrou
    ACRESCENTANDO um valor; afrouxar o tipo reabriria a travessia acima."""
    assert set(MeuWattClient.PECAS) == {"geracao", "paradas", "resumo"}


def test_a_rota_do_app_tambem_fecha_o_tipo():
    """Defesa em profundidade: a rota recusa pelo tipo antes mesmo de o cliente ser
    chamado. Verifica a assinatura, porque é ela que o FastAPI usa para validar."""
    import typing

    from app.api.v1.documents import arquivo_do_documento

    anotacao = typing.get_type_hints(arquivo_do_documento)["tipo"]

    assert typing.get_origin(anotacao) is typing.Literal, (
        "o parâmetro `tipo` voltou a ser texto livre — é ele que entra na URL do upstream"
    )
    assert set(typing.get_args(anotacao)) == {"geracao", "paradas", "resumo"}


def test_a_rota_e_o_cliente_conhecem_as_MESMAS_pecas():
    """As duas listas são a mesma regra escrita duas vezes, de propósito (defesa em
    profundidade). Se divergirem, o cliente recusa uma peça que a rota aceita — e o
    cliente vê 503 "não foi possível baixar" onde a peça simplesmente não é conhecida."""
    import typing

    from app.api.v1.documents import arquivo_do_documento

    anotacao = typing.get_type_hints(arquivo_do_documento)["tipo"]
    assert set(typing.get_args(anotacao)) == set(MeuWattClient.PECAS)


# ── recorte por usina (portal do cliente) ───────────────────────────────────
#
# A tela de Relatórios do portal é POR USINA, e passou a pedir `?usina_id=`. O filtro só
# ESTREITA o corte por `mw_plant_slug` — nunca o substitui. Fora do escopo é 404, pela mesma
# razão das outras rotas: "proibido" confirmaria que a usina existe.

from datetime import datetime

from app.api.v1.documents import meus_documentos
from app.core.security import gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess


class _PortalFalso:
    """O `/reports/portal` do meuWatt com token de admin: devolve TODAS as usinas."""

    async def portal_relatorios(self):
        return {"reports": [
            {"id": 1, "name": "Fechamento agosto", "plant_slug": "porto-ferreira",
             "period": "MENSAL", "date_from": "2026-08-01", "date_to": "2026-08-31",
             "sent_at": "2026-09-02T10:00:00", "files": [{"kind": "geracao", "filename": "g.pdf"}]},
            {"id": 2, "name": "Fechamento agosto", "plant_slug": "ribeirao-bonito",
             "period": "MENSAL", "date_from": "2026-08-01", "date_to": "2026-08-31",
             "sent_at": "2026-09-02T10:00:00", "files": []},
            {"id": 3, "name": "Fechamento agosto", "plant_slug": "usina-de-outro-cliente",
             "period": "MENSAL", "date_from": "2026-08-01", "date_to": "2026-08-31",
             "sent_at": "2026-09-02T10:00:00", "files": []},
            # O caso real do relatório 36 (Pereiras/agosto): o ÚNICO arquivo é o Resumo
            # Executivo. Peça faltando é o estado comum, não o excepcional.
            {"id": 4, "name": "Fechamento julho", "plant_slug": "porto-ferreira",
             "period": "MENSAL", "date_from": "2026-07-01", "date_to": "2026-07-31",
             "sent_at": "2026-08-02T10:00:00",
             "files": [{"kind": "resumo", "filename": "Resumo Executivo.pdf"}]},
        ]}


@pytest.fixture
def dono_com_duas_usinas(db, usinas, monkeypatch):
    u = User(apelido="dono", email="dono@exemplo.com.br", nome="Dono",
             perfil=Perfil.CLIENTE, senha_hash=gerar_hash_senha("cliente-1234"))
    db.add(u)
    db.commit()
    for usina in usinas:
        db.add(UserPlantAccess(user_id=u.id, plant_link_id=usina.id))
    db.commit()

    async def _cliente(_db):
        return _PortalFalso()

    monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _cliente)
    return u


async def test_sem_filtro_saem_as_usinas_do_escopo_com_plant_id(db, usinas, dono_com_duas_usinas):
    saida = await meus_documentos(None, db, dono_com_duas_usinas)
    a, b = usinas
    # A usina do outro cliente (id 3) nunca sai — o corte por slug é a barreira.
    assert {d.id for d in saida.documentos} == {1, 2, 4}
    assert {d.plant_id for d in saida.documentos} == {a.id, b.id}
    assert all(d.plant_id is not None for d in saida.documentos)
    assert isinstance(saida.documentos[0].publicado_em, datetime)


async def test_com_usina_id_sai_so_aquela_usina(db, usinas, dono_com_duas_usinas):
    a, _b = usinas
    saida = await meus_documentos(a.id, db, dono_com_duas_usinas)
    # Mais recente primeiro; a usina do outro cliente e a segunda usina ficam de fora.
    assert [d.id for d in saida.documentos] == [1, 4]
    assert saida.documentos[0].plant_id == a.id
    assert saida.documentos[0].usina == a.nome


async def test_usina_id_fora_do_escopo_e_404(db, dono_com_duas_usinas):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        await meus_documentos(987654, db, dono_com_duas_usinas)
    assert e.value.status_code == 404


async def test_o_resumo_executivo_aparece_na_listagem(db, usinas, dono_com_duas_usinas):
    """A listagem sempre soube da terceira peça — ela é montada por iteração sobre
    `files`. Era só o DOWNLOAD que recusava, e é isso que este arquivo protege."""
    a, _b = usinas
    saida = await meus_documentos(a.id, db, dono_com_duas_usinas)
    so_resumo = next(d for d in saida.documentos if d.id == 4)
    assert [x.tipo for x in so_resumo.arquivos] == ["resumo"]


# ── o download das três peças, e o que fazer quando o upstream recusa ────────

import httpx

from app.api.v1.documents import arquivo_do_documento


class _DownloadFalso(_PortalFalso):
    """O mesmo portal, mais o download — que devolve bytes ou o erro combinado."""

    def __init__(self, erro: int | None = None) -> None:
        self.erro = erro
        self.pedidos: list[tuple[int, str]] = []

    async def arquivo_relatorio(self, report_id: int, kind: str) -> bytes:
        self.pedidos.append((report_id, kind))
        if self.erro is not None:
            pedido = httpx.Request("GET", f"https://x/reports/{report_id}/files/{kind}")
            raise httpx.HTTPStatusError(
                f"{self.erro}", request=pedido,
                response=httpx.Response(self.erro, request=pedido),
            )
        return b"%PDF-1.7 conteudo"


@pytest.fixture
def com_download(monkeypatch):
    """Devolve uma função que instala o cliente falso e entrega o espião."""

    def _instalar(erro: int | None = None) -> _DownloadFalso:
        falso = _DownloadFalso(erro)

        async def _cliente(_db):
            return falso

        monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _cliente)
        return falso

    return _instalar


async def test_o_resumo_executivo_agora_baixa(db, usinas, dono_com_duas_usinas, com_download):
    """O pedido do dono: os TRÊS PDFs consolidados. Este era o que faltava."""
    espiao = com_download()
    r = await arquivo_do_documento(4, "resumo", db, dono_com_duas_usinas)
    assert r.status_code == 200
    assert r.media_type == "application/pdf"
    assert r.body.startswith(b"%PDF-")
    assert espiao.pedidos == [(4, "resumo")]
    # As três peças de um fechamento não podem chegar com o mesmo nome de arquivo.
    assert "relatorio-4-resumo.pdf" in r.headers["content-disposition"]


async def test_peca_que_o_fechamento_nao_tem_e_404_sem_ir_ao_upstream(
    db, usinas, dono_com_duas_usinas, com_download
):
    """A segunda tranca: o documento 1 só tem geração. Pedir o resumo dele não vira
    chamada ao meuWatt — e a resposta não confirma o que existe do outro lado."""
    from fastapi import HTTPException

    espiao = com_download()
    with pytest.raises(HTTPException) as e:
        await arquivo_do_documento(1, "resumo", db, dono_com_duas_usinas)
    assert e.value.status_code == 404
    assert espiao.pedidos == []


@pytest.mark.parametrize("recusa", [403, 404])
async def test_relatorio_despublicado_e_404_com_frase_propria(
    db, usinas, dono_com_duas_usinas, com_download, recusa
):
    """Reabrir um fechamento zera o "enviado ao cliente" mas NÃO apaga os arquivos: o
    link guardado passa a responder 403/404 lá em cima. Isso é uma decisão de quem
    publica, não uma queda — o 503 genérico mandava a pessoa procurar defeito.

    A frase cobre os dois casos porque o 404 também é "a peça saiu do fechamento":
    medido em produção, o relatório 36 serve o Resumo e responde 404 na Geração.
    """
    from fastapi import HTTPException

    com_download(recusa)
    with pytest.raises(HTTPException) as e:
        await arquivo_do_documento(4, "resumo", db, dono_com_duas_usinas)
    assert e.value.status_code == 404
    assert "não está mais publicado" in e.value.detail
    # Nunca a frase de indisponibilidade: quem lê precisa saber que não é defeito.
    assert "Não foi possível baixar" not in e.value.detail


async def test_falha_do_upstream_continua_503(db, usinas, dono_com_duas_usinas, com_download):
    """Defeito lá em cima segue sendo indisponibilidade — não pode virar "não existe",
    que faria o cliente parar de tentar."""
    from fastapi import HTTPException

    com_download(500)
    with pytest.raises(HTTPException) as e:
        await arquivo_do_documento(4, "resumo", db, dono_com_duas_usinas)
    assert e.value.status_code == 503


async def test_usina_sem_meuwatt_avisa_em_vez_de_vazar(db, usinas, dono_com_duas_usinas):
    """Vínculo só com o meuPlano: não há relatório de geração — e não há fallback para
    "todas as usinas", que devolveria os documentos das outras."""
    a, _b = usinas
    a.mw_plant_slug = None
    db.commit()
    saida = await meus_documentos(a.id, db, dono_com_duas_usinas)
    assert saida.documentos == []
    # A frase nomeia o SERVIÇO ausente, nunca o produto (ver `test_vocabulario_do_cliente.py`).
    assert saida.aviso and "monitoramento" in saida.aviso
    assert "meuWatt" not in saida.aviso
