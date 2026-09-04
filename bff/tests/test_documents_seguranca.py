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
    assert {d.id for d in saida.documentos} == {1, 2}
    assert {d.plant_id for d in saida.documentos} == {a.id, b.id}
    assert all(d.plant_id is not None for d in saida.documentos)
    assert isinstance(saida.documentos[0].publicado_em, datetime)


async def test_com_usina_id_sai_so_aquela_usina(db, usinas, dono_com_duas_usinas):
    a, _b = usinas
    saida = await meus_documentos(a.id, db, dono_com_duas_usinas)
    assert [d.id for d in saida.documentos] == [1]
    assert saida.documentos[0].plant_id == a.id
    assert saida.documentos[0].usina == a.nome


async def test_usina_id_fora_do_escopo_e_404(db, dono_com_duas_usinas):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        await meus_documentos(987654, db, dono_com_duas_usinas)
    assert e.value.status_code == 404


async def test_usina_sem_meuwatt_avisa_em_vez_de_vazar(db, usinas, dono_com_duas_usinas):
    """Vínculo só com o meuPlano: não há relatório de geração — e não há fallback para
    "todas as usinas", que devolveria os documentos das outras."""
    a, _b = usinas
    a.mw_plant_slug = None
    db.commit()
    saida = await meus_documentos(a.id, db, dono_com_duas_usinas)
    assert saida.documentos == []
    assert saida.aviso and "meuWatt" in saida.aviso
