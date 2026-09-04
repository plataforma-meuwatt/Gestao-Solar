"""O cronograma que o CLIENTE vê: só o consolidado, dentro do contrato certo.

Três defeitos que estes testes impedem de voltar:

1. **O contrato era chutado.** `MeuPlanoClient.cronograma` pegava `contratos()[0]` — o
   primeiro que o banco devolvesse. Com dois contratos na usina, o cliente via a matriz de
   um deles sem ninguém ter decidido qual. Agora a regra é explícita (`_contrato_padrao`):
   o consolidado, vigente, de início mais recente — e `contrato_id` na URL escolhe outro.
2. **Rascunho chegava como contrato.** A rota interna do meuPlano cria o DRAFT v1 ao ser
   lida e o devolve. A rota `visao-cliente` responde 404 quando só há rascunho; aqui isso
   vira 200 com matriz vazia e a frase de não publicado — a tela distingue "não há
   combinado" de "combinado e nada feito" sem derrubar a página do cliente.
3. **O PDF nunca saía.** `/cronograma/pdf` chamava o upstream sem `container_id`, que lá
   é obrigatório: 422 achatado em 502 "Não deu para gerar". Agora o PDF passa pelo mesmo
   resolvedor de contrato e leva o id.

E a cerca: `contrato_id` de OUTRA usina é 404 local, antes de qualquer ida ao meuPlano —
o 404 do upstream para "contrato alheio" seria idêntico ao de "sem consolidado", e os dois
virariam a frase de não publicado. Nada de rede: o cliente do meuPlano entra como fantasia.
"""

from datetime import date

import httpx
import pytest
from fastapi import HTTPException

from app.api.v1.manutencao import (
    NAO_PUBLICADO,
    ContratoOut,
    _contrato_padrao,
    cronograma_da_usina,
    listar_contratos,
    pdf_do_cronograma,
)
from app.core.security import gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess


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


def _erro_http(status: int, path: str) -> httpx.HTTPStatusError:
    """Como o cliente REAL falha: `raise_for_status` com a resposta dentro."""
    pedido = httpx.Request("GET", f"https://meuplano.exemplo{path}")
    resposta = httpx.Response(status, json={"detail": "sem consolidado"}, request=pedido)
    return httpx.HTTPStatusError(str(status), request=pedido, response=resposta)


#: O `_cronograma_out` do meuPlano, reduzido ao que a leitura usa. A linha tem os três
#: estados que a tela precisa separar: feito, dispensado (verde_ressalva) e atrasado.
MATRIZ = {
    "status": "CONSOLIDATED",
    "version": 2,
    "month_labels": ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
                     "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"],
    "rows": [
        {
            "plan_item_id": 77, "name": "Termografia", "type_code": "inversor",
            "screen_categoria": "ensaio", "periodicity_value": 4, "periodicity_unit": "ano",
            "expected_per_year": 4,
            "months": {"1": 1, "4": 1, "7": 1, "10": 1},
            "cell_status": {"1": "verde", "4": "verde_ressalva", "7": "vermelho", "10": "azul"},
        }
    ],
}


class ClienteFalso:
    """O meuPlano como fantasia: contratos por usina e o cronograma só dos consolidados."""

    def __init__(self, contratos_por_usina, consolidados):
        self.contratos_por_usina = contratos_por_usina
        #: {container_id: matriz}. Quem não está aqui só tem rascunho → 404 como o real.
        self.consolidados = consolidados
        self.pedidos: list[tuple[str, int, int]] = []

    async def vc_contratos(self, usina_id):
        return self.contratos_por_usina.get(usina_id, [])

    async def vc_cronograma(self, usina_id, container_id):
        self.pedidos.append(("cronograma", usina_id, container_id))
        if container_id not in self.consolidados:
            raise _erro_http(404, f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/cronograma")
        return self.consolidados[container_id]

    async def vc_cronograma_pdf(self, usina_id, container_id):
        self.pedidos.append(("pdf", usina_id, container_id))
        if container_id not in self.consolidados:
            raise _erro_http(404, f"/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/cronograma/pdf/view")
        return b"%PDF-1.4 fingido"


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    """Porto Ferreira (mp 1) tem DOIS contratos: o 10 (encerrado, consolidado v1) e o 20
    (vigente, consolidado v2). Ribeirão Bonito (mp 2) tem o 30, só em rascunho."""
    porto, ribeirao = usinas
    _conceder(db, dono, porto)
    _conceder(db, dono, ribeirao)
    cliente = ClienteFalso(
        contratos_por_usina={
            1: [
                {"id": 10, "numero": 100, "title": "O&M 2025", "start_date": "2025-03-01",
                 "end_date": "2026-02-28", "vigente": False, "versao_consolidada": 1},
                {"id": 20, "numero": 200, "title": "O&M 2026", "start_date": "2026-03-01",
                 "end_date": "2027-02-28", "vigente": True, "versao_consolidada": 2},
            ],
            2: [
                {"id": 30, "numero": 300, "title": "O&M Ribeirão", "start_date": "2026-01-01",
                 "end_date": None, "vigente": True, "versao_consolidada": None},
            ],
        },
        consolidados={10: {**MATRIZ, "version": 1}, 20: MATRIZ},
    )

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.manutencao.integracoes.cliente_meuplano", _cliente)
    return cliente


# ── contrato padrão ─────────────────────────────────────────────────────────


def _c(ident, vigente=None, inicio=None, versao=None):
    return ContratoOut(id=ident, vigente=vigente, inicio=inicio, versao_cronograma=versao)


def test_o_padrao_e_o_consolidado_vigente_mais_recente():
    escolhido = _contrato_padrao([
        _c(1, vigente=True, inicio=date(2026, 3, 1), versao=None),      # vigente, mas rascunho
        _c(2, vigente=False, inicio=date(2025, 3, 1), versao=1),        # consolidado, encerrado
        _c(3, vigente=True, inicio=date(2024, 1, 1), versao=3),         # consolidado, vigente, antigo
        _c(4, vigente=True, inicio=date(2026, 1, 1), versao=2),         # consolidado, vigente, recente
    ])
    assert escolhido is not None and escolhido.id == 4


def test_sem_consolidado_o_padrao_ainda_aponta_um_contrato():
    """Para a resposta carregar `contrato_id` e o aviso falar de um contrato real."""
    escolhido = _contrato_padrao([_c(1, vigente=False), _c(2, vigente=True)])
    assert escolhido is not None and escolhido.id == 2


def test_sem_contrato_nenhum_nao_ha_padrao():
    assert _contrato_padrao([]) is None


# ── GET /manutencao/contratos ───────────────────────────────────────────────


async def test_lista_os_contratos_da_usina_com_a_versao_consolidada(db, dono, cenario, usinas):
    porto, _ = usinas
    saida = await listar_contratos(porto.id, db, dono)
    assert saida.usina_id == porto.id
    assert [(c.id, c.versao_cronograma) for c in saida.contratos] == [(10, 1), (20, 2)]
    assert saida.contratos[1].inicio == date(2026, 3, 1)
    assert saida.contratos[1].vigente is True
    assert saida.aviso is None


async def test_usina_fora_do_escopo_nao_lista(db, dono, cenario):
    with pytest.raises(HTTPException) as e:
        await listar_contratos(9999, db, dono)
    assert e.value.status_code == 404


# ── GET /manutencao/cronograma ──────────────────────────────────────────────


async def test_dois_contratos_sem_contrato_id_escolhe_o_consolidado_mais_recente(
    db, dono, cenario, usinas
):
    porto, _ = usinas
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.contrato_id == 20
    assert saida.contrato == "O&M 2026"
    assert saida.status == "CONSOLIDATED" and saida.versao == 2
    assert cenario.pedidos == [("cronograma", 1, 20)]


async def test_contrato_id_escolhe_outro_contrato_da_mesma_usina(db, dono, cenario, usinas):
    porto, _ = usinas
    saida = await cronograma_da_usina(porto.id, 10, db, dono)
    assert saida.contrato_id == 10 and saida.versao == 1
    assert cenario.pedidos == [("cronograma", 1, 10)]


async def test_contrato_de_outra_usina_e_404_sem_ir_ao_upstream(db, dono, cenario, usinas):
    """O 30 é do Ribeirão. Pedi-lo em Porto Ferreira é 404 AQUI — nem 502, nem a frase de
    não publicado, e o meuPlano nem chega a ser consultado sobre o cronograma."""
    porto, _ = usinas
    with pytest.raises(HTTPException) as e:
        await cronograma_da_usina(porto.id, 30, db, dono)
    assert e.value.status_code == 404
    assert cenario.pedidos == []


async def test_so_rascunho_vira_200_com_aviso_e_matriz_vazia(db, dono, cenario, usinas):
    _, ribeirao = usinas
    saida = await cronograma_da_usina(ribeirao.id, None, db, dono)
    assert saida.linhas == [] and saida.status is None
    assert saida.contrato_id == 30           # a tela sabe DE QUAL contrato está falando
    assert saida.aviso == NAO_PUBLICADO


async def test_a_matriz_e_repassada_e_dispensado_nao_vira_feito(db, dono, cenario, usinas):
    """`verde_ressalva` é dispensa: conta como cumprido no ano, mas a célula NÃO é ✓."""
    porto, _ = usinas
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.meses[0] == "2026-03"       # a âncora do contrato, não janeiro
    linha = saida.linhas[0]
    por_mes = {c.mes: c for c in linha.meses}
    assert por_mes["2026-03"].feito and not por_mes["2026-03"].dispensado
    assert por_mes["2026-06"].dispensado and not por_mes["2026-06"].feito
    assert por_mes["2026-06"].estado == "verde_ressalva"
    assert por_mes["2026-09"].atrasado
    assert not por_mes["2026-12"].feito and por_mes["2026-12"].previsto == 1
    assert linha.feitos == 2 and linha.previsto_ano == 4
    assert saida.previsto_ano == 4 and saida.feitos_ano == 2


async def test_usina_sem_contrato_avisa_sem_derrubar(db, dono, usinas, monkeypatch):
    porto, _ = usinas
    _conceder(db, dono, porto)
    cliente = ClienteFalso(contratos_por_usina={}, consolidados={})

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.manutencao.integracoes.cliente_meuplano", _cliente)
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.contrato_id is None and saida.linhas == []
    assert "não tem contrato" in (saida.aviso or "")


# ── GET /manutencao/cronograma/pdf ──────────────────────────────────────────


async def test_o_pdf_leva_o_container_id_do_contrato_padrao(db, dono, cenario, usinas):
    """O defeito de origem: o upstream exige `container_id` e o BFF não mandava."""
    porto, _ = usinas
    resposta = await pdf_do_cronograma(porto.id, None, db, dono)
    assert resposta.body.startswith(b"%PDF")
    assert resposta.media_type == "application/pdf"
    assert cenario.pedidos == [("pdf", 1, 20)]


async def test_o_pdf_de_contrato_so_em_rascunho_e_404_com_a_frase(db, dono, cenario, usinas):
    _, ribeirao = usinas
    with pytest.raises(HTTPException) as e:
        await pdf_do_cronograma(ribeirao.id, None, db, dono)
    assert e.value.status_code == 404
    assert e.value.detail == NAO_PUBLICADO


async def test_o_pdf_de_contrato_alheio_e_404(db, dono, cenario, usinas):
    porto, _ = usinas
    with pytest.raises(HTTPException) as e:
        await pdf_do_cronograma(porto.id, 30, db, dono)
    assert e.value.status_code == 404
    assert cenario.pedidos == []
