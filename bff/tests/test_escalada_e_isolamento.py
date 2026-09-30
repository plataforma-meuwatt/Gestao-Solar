"""O que a revisão de 30/09/2026 achou — e o que não pode voltar.

Cinco leituras independentes do código (becos, invariantes, isolamento multiempresa,
contrato front×back e adversarial de autorização) apontaram os mesmos dois pontos por
caminhos diferentes. Cada teste aqui é um deles, e a primeira linha diz qual.

As rotas são chamadas direto, com a sessão no lugar das dependências do FastAPI: é o
mesmo código que roda na requisição, sem subir servidor.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from app.core.security import (
    criar_token,
    criar_token_empresa,
    gerar_hash_senha,
    gestor_empresa_atual,
    usuario_atual,
)
from app.models.empresa import Empresa
from app.models.integracao import EstadoTeste, Integracao, Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User


def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture
def cenario(db):
    """Uma empresa, o gerente dela — e um ADMINISTRADOR com a empresa gravada.

    O último é a pré-condição do ataque, e é estado real: o comentário de
    `painel_empresas.py` diz "acontece (um administrador que também é dono de usina)", e
    `PUT /empresas/{id}/carteira` gravava `empresa_id` em qualquer conta marcada.
    """
    emp = Empresa(nome="Splendor O&M")
    db.add(emp)
    db.flush()
    gerente = User(
        apelido="gerente", nome="Gerente", perfil=Perfil.GESTOR_EMPRESA,
        empresa_id=emp.id, senha_hash=gerar_hash_senha("gerente-1234"),
    )
    admin = User(
        apelido="admin.plataforma", nome="Admin", perfil=Perfil.ADMINISTRADOR,
        empresa_id=emp.id, senha_hash=gerar_hash_senha("admin-1234"),
    )
    db.add_all([gerente, admin])
    db.commit()
    return emp, gerente, admin


# ------------------------------------------------- 1. a escalada de privilégio


def test_o_gerente_nao_troca_a_senha_de_uma_conta_da_PLATAFORMA(db, cenario):
    """O furo: `PATCH /api/empresa/usuarios/{id}` conferia só a empresa, e a rota-irmã da
    plataforma já recusava perfil de plataforma desde sempre. Com a senha trocada, o
    gerente entrava em `/api/painel/entrar` como administrador — a conta que guarda as
    credenciais de TODOS os inquilinos."""
    from app.api.v1.empresa import ContaPatch, editar_conta_da_empresa

    _emp, gerente, admin = cenario
    antes = admin.senha_hash

    with pytest.raises(HTTPException) as erro:
        editar_conta_da_empresa(
            admin.id, ContaPatch(senha="escolhida-pelo-atacante"), db=db, gerente=gerente
        )
    assert erro.value.status_code == 404
    assert "plataforma" not in erro.value.detail.lower(), "não confirma que a conta existe"
    db.refresh(admin)
    assert admin.senha_hash == antes


def test_o_gerente_nao_desativa_nem_conecta_token_em_conta_da_PLATAFORMA(db, cenario):
    """As rotas-irmãs do mesmo arquivo, com a mesma raiz: todas conferiam só a empresa."""
    from app.api.v1.empresa import (
        ContaPatch,
        UsinasDoClienteIn,
        definir_usinas_do_cliente,
        desconectar_conta_do_cliente,
        editar_conta_da_empresa,
        usinas_do_usuario,
    )

    _emp, gerente, admin = cenario
    for chamada in (
        lambda: editar_conta_da_empresa(admin.id, ContaPatch(ativo=False), db=db, gerente=gerente),
        lambda: desconectar_conta_do_cliente(admin.id, Produto.MEUWATT, db=db, gerente=gerente),
        lambda: usinas_do_usuario(admin.id, db=db, gerente=gerente),
        lambda: definir_usinas_do_cliente(
            admin.id, UsinasDoClienteIn(plant_link_ids=[]), db=db, gerente=gerente
        ),
    ):
        with pytest.raises(HTTPException) as erro:
            chamada()
        assert erro.value.status_code == 404
    db.refresh(admin)
    assert admin.ativo is True


def test_conta_da_plataforma_nao_aparece_na_lista_do_gerente(db, cenario):
    """O gerente descobria o alvo sozinho: as duas listagens recortavam por `empresa_id` e
    o docstring afirmava que conta de plataforma tem `empresa_id` nulo — o que a carteira
    desmentia."""
    from app.api.v1.empresa import listar_usuarios, usuarios_detalhados

    _emp, gerente, admin = cenario
    for lista in (
        listar_usuarios(db=db, gerente=gerente),
        usuarios_detalhados(db=db, gerente=gerente),
    ):
        apelidos = {u.apelido for u in lista}
        assert "gerente" in apelidos
        assert "admin.plataforma" not in apelidos


def test_a_carteira_da_empresa_nao_adota_conta_da_plataforma(db, cenario):
    """A entrada do ataque: `PUT /empresas/{id}/carteira` gravava `empresa_id` em qualquer
    id marcado em `clientes`, sem olhar o perfil. Fechar só a saída deixaria o estado
    existindo — e o próximo caminho a esquecer a guarda o encontraria pronto."""
    from app.api.v1.painel_empresas import CarteiraIn, salvar_carteira

    emp, _gerente, admin = cenario
    admin.empresa_id = None
    db.commit()

    salvar_carteira(
        emp.id, CarteiraIn(usinas=[], clientes=[admin.id]), db=db, _gestor=admin
    )
    db.refresh(admin)
    assert admin.empresa_id is None, "administrador não entra na carteira de inquilino"


# ------------------------------------------------- 2. a empresa desativada


def test_empresa_desativada_para_de_ler_pelo_aplicativo(db, cenario):
    """`painel.entrar` recusava o gerente de empresa desativada, e só ele: `auth.login`
    emitia token de aplicativo para a mesma conta, com 30 dias e renovação sem fim, e a
    carteira inteira continuava respondendo. Desativar a empresa só escondia o botão.

    A conferência mora em `usuario_atual` porque ali passam TODAS as requisições
    autenticadas — inclusive as de um token emitido antes da desativação.
    """
    emp, gerente, _admin = cenario
    cliente = User(apelido="dono", nome="Dono", perfil=Perfil.CLIENTE, empresa_id=emp.id)
    db.add(cliente)
    db.commit()

    token_app, _ = criar_token(cliente.id)
    token_emp, _ = criar_token_empresa(gerente.id)
    assert usuario_atual(cred=_cred(token_app), db=db).id == cliente.id

    emp.ativa = False
    db.commit()

    for guarda, token in ((usuario_atual, token_app), (gestor_empresa_atual, token_emp)):
        with pytest.raises(HTTPException) as erro:
            guarda(cred=_cred(token), db=db)
        assert erro.value.status_code == 403
        assert "desativada" in erro.value.detail


def test_conta_da_plataforma_nao_e_barrada_por_empresa(db, administrador):
    """`empresa_id` nulo é conta da plataforma, e ela não tem empresa para conferir."""
    token, _ = criar_token(administrador.id)
    assert usuario_atual(cred=_cred(token), db=db).id == administrador.id


# ------------------------------------------------- 3. identidade e recorte das pontes


def test_o_inquilino_nao_le_QUEM_gerou_a_credencial_da_plataforma(db, cenario):
    """Sem linha própria, a empresa cai na credencial da plataforma (atalho da migração) —
    e a tela de Conexões entregava nome, e-mail e prefixo do token de quem a gerou. O
    estado ela precisa saber; a identidade é de outra conta."""
    from app.api.v1.empresa import listar_conexoes

    emp, gerente, _admin = cenario
    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url="https://api.meuwatt.com.br",
            token_prefixo="mw_pat_ABCD",
            token_dono_nome="Dono da Plataforma",
            token_dono_email="dono@plataforma.local",
            estado=EstadoTeste.OK,
        )
    )
    db.commit()

    mw = next(c for c in listar_conexoes(db=db, gerente=gerente) if c.produto == "meuwatt")
    assert mw.configurada is True and mw.propria is False
    assert mw.token_dono_nome is None
    assert mw.token_dono_email is None
    assert mw.token_prefixo is None
    assert mw.base_url is None


def test_a_lista_de_pontes_do_app_e_a_da_empresa_do_cliente(db, cenario):
    """`listar` era `select(Integracao)` sem recorte, chaveado por produto: a última linha
    vencia por acaso. Um cliente da empresa A lia o estado da ponte da B — "Conectado" com
    a dele quebrada — e o painel da plataforma podia mostrar o token de um inquilino."""
    from app.services import integracoes

    emp, _gerente, _admin = cenario
    outra = Empresa(nome="Outra O&M")
    db.add(outra)
    db.flush()
    db.add_all([
        Integracao(produto=Produto.MEUWATT, base_url="https://p", estado=EstadoTeste.FALHOU),
        Integracao(produto=Produto.MEUWATT, base_url="https://a", empresa_id=emp.id, estado=EstadoTeste.OK),
        Integracao(produto=Produto.MEUWATT, base_url="https://b", empresa_id=outra.id, estado=EstadoTeste.FALHOU),
    ])
    db.commit()

    assert integracoes.listar(db, emp.id)[Produto.MEUWATT].base_url == "https://a"
    assert integracoes.listar(db, outra.id)[Produto.MEUWATT].base_url == "https://b"
    assert integracoes.listar(db)[Produto.MEUWATT].base_url == "https://p"


# ------------------------------------------------- 4. usina: micro, nome e par


async def test_a_micro_usina_de_outra_empresa_nao_e_casada_aqui(db, cenario):
    """`casar_micro_usina` procurava o par anterior só DENTRO da empresa, enquanto
    `salvar_usina` confere globalmente. Duas empresas apontando para a mesma micro fazem
    o motor distribuir o alerta real de uma como se fosse da outra: ele lê o MICRO com a
    credencial da plataforma e mapeia por `mw_micro_plant_id` sem recorte."""
    from app.api.v1.empresa import MicroVinculoIn, casar_micro_usina

    emp, gerente, _admin = cenario
    outra = Empresa(nome="Outra O&M")
    db.add(outra)
    db.flush()
    db.add_all([
        PlantLink(nome="Da outra", empresa_id=outra.id, mw_micro_plant_id=77),
        PlantLink(nome="Minha", empresa_id=emp.id, mw_plant_slug="minha"),
    ])
    db.commit()
    minha = db.scalar(select(PlantLink).where(PlantLink.nome == "Minha"))

    with pytest.raises(HTTPException) as erro:
        casar_micro_usina(77, MicroVinculoIn(plant_link_id=minha.id), db=db, gerente=gerente)
    assert erro.value.status_code == 409
    assert "outra empresa" in erro.value.detail
    db.refresh(minha)
    assert minha.mw_micro_plant_id is None


async def test_ligar_e_desligar_nao_apaga_o_par_com_a_micro(db, cenario):
    """O gêmeo do painel documenta que um front publicado antes do campo não o manda, e
    cada "Ligar/Desligar" apagaria o par em silêncio. A cópia da empresa gravava sempre."""
    from app.api.v1.empresa import UsinaIn, salvar_usina

    emp, gerente, _admin = cenario
    link = PlantLink(nome="Casada", empresa_id=emp.id, mw_plant_slug="casada", mw_micro_plant_id=31)
    db.add(link)
    db.commit()

    await salvar_usina(
        UsinaIn(plant_link_id=link.id, mw_slug="casada", nome="Casada", no_app=False),
        db=db, gerente=gerente,
    )
    db.refresh(link)
    assert link.ativo is False
    assert link.mw_micro_plant_id == 31, "o par sobreviveu ao Desligar"


def test_usina_sem_nome_e_recusada_como_no_painel(db):
    """`nome: str` aceitava "": limpar o campo e clicar fora gravava usina sem rótulo em
    toda parte — catálogo, lista de concessão e carteira. O gêmeo do painel já barrava."""
    from pydantic import ValidationError

    from app.api.v1.empresa import UsinaIn

    with pytest.raises(ValidationError):
        UsinaIn(mw_slug="x", nome="")


async def test_nao_se_reivindica_usina_que_o_seu_token_nao_enxerga(db, cenario, monkeypatch):
    """O corpo é JSON: um `mw_slug` digitado à mão gravava na carteira desta empresa a
    usina de outra. Não vazava leitura — quem lê é o token —, mas ocupava o identificador:
    a dona passava a receber "já pertence a outra empresa" ao trazer a própria usina, e o
    par 201 × 409 virava oráculo de quem tem o quê."""
    from app.api.v1 import empresa as api
    from app.services import integracoes

    emp, gerente, _admin = cenario

    class Fake:
        async def usinas(self):
            return [{"slug": "minha-usina", "id": 1}]

    async def fake_mw(db, empresa_id=None):
        return Fake()

    monkeypatch.setattr(integracoes, "cliente_meuwatt", fake_mw)

    with pytest.raises(HTTPException) as erro:
        await api.salvar_usina(
            api.UsinaIn(mw_slug="usina-de-terceiros", nome="Reivindicada"),
            db=db, gerente=gerente,
        )
    assert erro.value.status_code == 404
    assert "seu meuWatt" in erro.value.detail

    trazida = await api.salvar_usina(
        api.UsinaIn(mw_slug="minha-usina", nome="Minha"), db=db, gerente=gerente
    )
    assert trazida.plant_link_id is not None
