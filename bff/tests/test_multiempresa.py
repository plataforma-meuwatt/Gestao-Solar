"""O recorte por empresa — o que não pode voltar a acontecer.

Cada teste diz, na primeira linha, qual defeito ele impede. Os dois caros são o mesmo
defeito com duas roupas: **uma consulta sem recorte** e **um recorte que o cliente escolhe**.
Nenhum dos dois dá erro em desenvolvimento, onde só existe uma empresa — os dois entregam
o dado do vizinho no dia em que entra a segunda.

As guardas são chamadas direto, com a sessão e o token no lugar das dependências do
FastAPI: é o mesmo código que roda na requisição, sem subir servidor.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from app.core.security import (
    criar_token,
    criar_token_empresa,
    criar_token_painel,
    gerar_hash_senha,
    gestor_atual,
    gestor_empresa_atual,
    usuario_atual,
)
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import empresas as svc


def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture
def duas_empresas(db):
    a = Empresa(nome="Splendor O&M")
    b = Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    return a, b


@pytest.fixture
def carteiras(db, duas_empresas):
    """Duas empresas, uma usina e um cliente em cada. O cenário mínimo do vazamento."""
    a, b = duas_empresas
    usina_a = PlantLink(nome="Usina da A", empresa_id=a.id, mw_plant_slug="usina-a")
    usina_b = PlantLink(nome="Usina da B", empresa_id=b.id, mw_plant_slug="usina-b")
    gerente_a = User(
        apelido="gerente.a",
        nome="Gerente A",
        perfil=Perfil.GESTOR_EMPRESA,
        empresa_id=a.id,
        senha_hash=gerar_hash_senha("senha-1234"),
    )
    cliente_b = User(
        apelido="cliente.b", nome="Cliente B", perfil=Perfil.CLIENTE, empresa_id=b.id
    )
    db.add_all([usina_a, usina_b, gerente_a, cliente_b])
    db.commit()
    return a, b, gerente_a


# --------------------------------------------------------------------- o recorte


def test_o_gerente_so_alcanca_a_propria_empresa(db, carteiras):
    """Defeito guardado: a consulta sai sem `where` de empresa e a lista traz a carteira
    inteira da plataforma. Em desenvolvimento, com uma empresa só, ela parece correta."""
    _a, _b, gerente = carteiras
    usinas = db.scalars(
        svc.no_escopo(select(PlantLink), PlantLink.empresa_id, gerente)
    ).all()
    assert [u.nome for u in usinas] == ["Usina da A"]


def test_a_plataforma_alcanca_tudo(db, carteiras, administrador):
    """O outro lado da mesma régua: quem é da plataforma não recebe filtro nenhum."""
    usinas = db.scalars(
        svc.no_escopo(select(PlantLink), PlantLink.empresa_id, administrador)
    ).all()
    assert sorted(u.nome for u in usinas) == ["Usina da A", "Usina da B"]


def test_o_inquilino_nao_escolhe_a_empresa_que_ve(db, carteiras):
    """Defeito guardado, e o mais caro: aceitar `empresa` de quem chama. Trocar o número
    leria a carteira do concorrente, e o servidor não teria como saber que não devia."""
    a, b, gerente = carteiras
    usinas = db.scalars(
        svc.no_escopo(select(PlantLink), PlantLink.empresa_id, gerente, empresa_pedida=b.id)
    ).all()
    assert [u.nome for u in usinas] == ["Usina da A"], "o pedido do inquilino foi obedecido"


def test_a_plataforma_pode_ver_como_uma_empresa(db, carteiras, administrador):
    """O "ver como" da tela de suporte — só para quem é da plataforma."""
    _a, b, _g = carteiras
    usinas = db.scalars(
        svc.no_escopo(select(PlantLink), PlantLink.empresa_id, administrador, empresa_pedida=b.id)
    ).all()
    assert [u.nome for u in usinas] == ["Usina da B"]


def test_conta_de_inquilino_sem_empresa_e_recusada(db):
    """Defeito guardado: `empresa_id` nulo virar "sem filtro". Uma conta de inquilino sem
    vínculo tem de parar na porta, nunca ver tudo."""
    orfa = User(apelido="orfa", nome="Órfã", perfil=Perfil.GESTOR_EMPRESA)
    db.add(orfa)
    db.commit()
    with pytest.raises(HTTPException) as erro:
        svc.no_escopo(select(PlantLink), PlantLink.empresa_id, orfa)
    assert erro.value.status_code == 403


# --------------------------------------------------------------------- os portões


def test_cada_token_abre_so_o_proprio_portao(db, carteiras, administrador):
    """Defeito guardado: um portão novo que aceita a sessão dos outros. A promessa é
    'token de um portão é recusado nos demais', e ela vale nas seis combinações."""
    _a, _b, gerente = carteiras
    cliente = db.scalar(select(User).where(User.apelido == "cliente.b"))

    t_painel = _cred(criar_token_painel(administrador.id)[0])
    t_empresa = _cred(criar_token_empresa(gerente.id)[0])
    t_cliente = _cred(criar_token(cliente.id)[0])

    # Cada guarda aceita o seu.
    assert gestor_atual(cred=t_painel, db=db).id == administrador.id
    assert gestor_empresa_atual(cred=t_empresa, db=db).id == gerente.id
    assert usuario_atual(cred=t_cliente, db=db).id == cliente.id

    # E recusa os outros dois.
    for guarda, alheios in (
        (gestor_atual, (t_empresa, t_cliente)),
        (gestor_empresa_atual, (t_painel, t_cliente)),
        (usuario_atual, (t_painel, t_empresa)),
    ):
        for token in alheios:
            with pytest.raises(HTTPException) as erro:
                guarda(cred=token, db=db)
            assert erro.value.status_code in (401, 403)


def test_o_gerente_nao_abre_o_painel_da_plataforma(db, carteiras):
    """O perfil novo não herda o painel: `abre_painel` continua sendo dos dois perfis da
    plataforma, e é ele que `gestor_atual` confere."""
    _a, _b, gerente = carteiras
    assert gerente.abre_empresa and not gerente.abre_painel
    with pytest.raises(HTTPException):
        gestor_atual(cred=_cred(criar_token_painel(gerente.id)[0]), db=db)


def test_gerente_de_empresa_desativada_nao_entra(db, carteiras):
    """Desligar a empresa tem de valer na requisição seguinte, sem esperar o token
    expirar — é o que faz `ativa=false` ser uma decisão operável."""
    from app.api.v1.painel import EntrarIn, entrar

    a, _b, _g = carteiras
    a.ativa = False
    db.commit()
    with pytest.raises(HTTPException) as erro:
        entrar(EntrarIn(apelido="gerente.a", senha="senha-1234"), db=db)
    assert erro.value.status_code == 403


def test_uma_porta_de_login_entrega_o_token_do_portao_certo(db, carteiras, administrador):
    """Defeito guardado: duas portas de login — a mesma regra escrita duas vezes, e a
    segunda esquecendo de conferir conta ativa. Autenticar é uma coisa só; o que muda é
    o token que sai."""
    from app.api.v1.painel import EntrarIn, entrar

    do_gerente = entrar(EntrarIn(apelido="gerente.a", senha="senha-1234"), db=db)
    assert do_gerente.escopo == "empresa"
    assert do_gerente.empresa == "Splendor O&M"
    assert gestor_empresa_atual(cred=_cred(do_gerente.token), db=db).apelido == "gerente.a"

    do_admin = entrar(EntrarIn(apelido="admin", senha="admin-1234"), db=db)
    assert do_admin.escopo == "painel" and do_admin.empresa is None
    assert gestor_atual(cred=_cred(do_admin.token), db=db).apelido == "admin"

    # E a mensagem não conta qual dos motivos falhou.
    for apelido, senha in (("nao-existe", "x"), ("gerente.a", "senha-errada")):
        with pytest.raises(HTTPException) as erro:
            entrar(EntrarIn(apelido=apelido, senha=senha), db=db)
        assert erro.value.status_code == 401
        assert erro.value.detail == "Apelido ou senha inválidos"


# ------------------------------------------------------------------- o cadastro


def test_nome_repetido_e_recusado_mesmo_com_outra_grafia(db):
    """Defeito guardado, e é o que o texto livre em `gs_users.empresa` permitia:
    "Splendor O&M" e "splendor o&m" viravam duas empresas."""
    svc.criar(db, "Splendor O&M")
    db.commit()
    with pytest.raises(HTTPException) as erro:
        svc.criar(db, "  splendor o&m  ")
    assert erro.value.status_code == 409


def test_area_de_empresas_existe_no_catalogo():
    """Área ausente do catálogo faz `exige_area` estourar na importação do módulo — o que
    é deliberado, mas o sintoma chega como "o painel inteiro parou de subir"."""
    from app.services import areas_painel

    assert "empresas" in areas_painel.CHAVES


# --------------------------------------------------------------- a carteira


def test_atribuir_carteira_nao_rouba_o_que_e_de_outra_empresa(db, carteiras, administrador):
    """Defeito guardado: a tela manda o id de uma usina que é de OUTRA empresa e a
    atribuição a transfere. O dono aparece escrito ao lado de cada linha, então marcar o
    item de outro é engano — e engano não pode mover carteira."""
    from app.api.v1.painel_empresas import CarteiraIn, carteira, salvar_carteira

    a, b, _g = carteiras
    da_b = [u for u in carteira(b.id, db=db, _gestor=administrador).usinas if u.empresa_id == b.id]
    assert da_b, "cenário inválido: a empresa B precisa ter usina"

    salvar_carteira(
        a.id,
        CarteiraIn(usinas=[u.id for u in da_b], clientes=[]),
        db=db,
        _gestor=administrador,
    )

    depois = {u.id: u.empresa_id for u in carteira(b.id, db=db, _gestor=administrador).usinas}
    for u in da_b:
        assert depois[u.id] == b.id, "a usina mudou de dono por um id no corpo da requisição"


def test_tirar_da_carteira_deixa_sem_dono(db, carteiras, administrador):
    """O que sai da lista fica sem dono — reversível e visível —, nunca em outra empresa."""
    from app.api.v1.painel_empresas import CarteiraIn, carteira, salvar_carteira

    a, _b, _g = carteiras
    depois = salvar_carteira(
        a.id, CarteiraIn(usinas=[], clientes=[]), db=db, _gestor=administrador
    )
    da_a = [u for u in depois.usinas if u.nome == "Usina da A"]
    assert da_a and da_a[0].empresa_id is None


# ------------------------------------------------------- credencial por empresa


def test_a_credencial_da_empresa_nao_sobrescreve_a_da_plataforma(db, duas_empresas):
    """Defeito guardado: `salvar_token` usar o atalho de `obter`, achar a linha da
    plataforma e gravar o token da empresa em cima dela. A plataforma perderia a
    credencial com que monta o catálogo, e ninguém ligaria uma coisa à outra."""
    from app.models.integracao import Integracao, Produto
    from app.services import integracoes

    a, b = duas_empresas
    # Uma empresa ativa: é o cenário da migração, em que o atalho para a credencial da
    # plataforma ainda é legítimo (a trava dele tem teste próprio, logo abaixo).
    b.ativa = False
    db.add(Integracao(produto=Produto.MEUWATT, base_url="https://api.meuwatt.com.br"))
    db.commit()

    # A leitura da empresa, sem linha própria, cai na da plataforma — o atalho da migração.
    assert integracoes.obter(db, Produto.MEUWATT, a.id).empresa_id is None

    db.add(Integracao(produto=Produto.MEUWATT, base_url="https://api.meuwatt.com.br", empresa_id=a.id))
    db.commit()

    da_empresa = integracoes.obter(db, Produto.MEUWATT, a.id)
    da_plataforma = integracoes.obter(db, Produto.MEUWATT)
    assert da_empresa.empresa_id == a.id
    assert da_plataforma.empresa_id is None
    assert da_empresa.id != da_plataforma.id


def test_com_duas_empresas_o_atalho_da_plataforma_e_recusado(db, duas_empresas):
    """A trava que se arma sozinha. Com UMA empresa, a credencial da plataforma é a dela e
    o atalho é correto. Com DUAS, ela é de uma das duas — e usá-la para a outra devolveria
    a carteira do concorrente. A recusa é ruidosa de propósito: parar é melhor do que
    responder dado errado."""
    from app.models.integracao import Integracao, Produto
    from app.services import integracoes

    a, b = duas_empresas
    db.add(Integracao(produto=Produto.MEUWATT, base_url="https://api.meuwatt.com.br"))
    db.commit()

    with pytest.raises(RuntimeError) as erro:
        integracoes.obter(db, Produto.MEUWATT, a.id)
    assert "conexão dela" in str(erro.value)

    # Desligar uma delas devolve o sistema ao caso de uma empresa só, e o atalho volta.
    b.ativa = False
    db.commit()
    assert integracoes.obter(db, Produto.MEUWATT, a.id) is not None
