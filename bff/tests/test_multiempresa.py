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
from sqlalchemy import func, select

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
    # UMA empresa no sistema — a segunda é apagada, não desativada: desativar não devolve
    # o atalho (ver o teste abaixo). É o cenário da migração, em que a credencial da
    # plataforma ainda é legitimamente a da única empresa.
    db.delete(b)
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

    # E DESLIGAR a outra não devolve o atalho — este teste já afirmou o contrário, e
    # estava errado. A credencial da plataforma pertence à conta de alguém: com duas
    # empresas cadastradas, ninguém sabe a qual delas. Desativar a primeira faria a
    # segunda ler a carteira da primeira com o token da primeira, que é exatamente o
    # vazamento que a trava existe para impedir. Uma trava que se desarma sozinha não é
    # trava. (Revisão de isolamento, 30/09/2026.)
    b.ativa = False
    db.commit()
    with pytest.raises(RuntimeError):
        integracoes.obter(db, Produto.MEUWATT, a.id)

    # A saída é conectar a conta DA empresa, não mexer no cadastro da outra.
    db.add(Integracao(produto=Produto.MEUWATT, base_url="https://api.meuwatt.com.br", empresa_id=a.id))
    db.commit()
    assert integracoes.obter(db, Produto.MEUWATT, a.id).empresa_id == a.id


# ---------------------------------------------------------------- o gerente


def test_o_gerente_nasce_dentro_da_empresa_e_ja_entra(db, duas_empresas, administrador):
    """Defeito guardado: a fundação inteira ficar sem porta de entrada. A tela de Usuários
    do sistema só cria staff da plataforma, então sem esta rota não havia como existir um
    `gestor_empresa` — e o portão dele nunca seria usado por ninguém."""
    from app.api.v1.painel import EntrarIn, entrar
    from app.api.v1.painel_empresas import GerenteIn, criar_gerente

    a, _b = duas_empresas
    criado = criar_gerente(
        a.id, GerenteIn(nome="Maria Gerente", apelido="maria.om"), db=db, gestor=administrador
    )
    assert criado.apelido == "maria.om" and criado.senha

    # A senha entregue funciona, e a sessão sai no portão da empresa certa.
    sessao = entrar(EntrarIn(apelido="maria.om", senha=criado.senha), db=db)
    assert sessao.escopo == "empresa" and sessao.empresa_id == a.id


def test_a_tela_da_plataforma_recusa_criar_gerente_sem_empresa(db, administrador):
    """Um gerente criado na tela de Usuários do sistema nasceria sem empresa — uma conta
    que parece pronta e que `gestor_empresa_atual` recusa. A rota diz onde criar."""
    from app.api.v1.painel_usuarios import MembroIn, criar

    with pytest.raises(HTTPException) as erro:
        criar(
            MembroIn(
                nome="Sem Empresa",
                apelido="sem.empresa",
                perfil=Perfil.GESTOR_EMPRESA,
                senha="senha-12345",
            ),
            db=db,
            admin=administrador,
        )
    assert erro.value.status_code == 400
    assert "Empresas de O&M" in erro.value.detail


# ------------------------------------------------- o vínculo com os produtos


def test_o_vinculo_e_do_gerente_e_sai_da_sessao(db, carteiras):
    """Correção de rumo do dono, 28/09/2026: **quem casa a empresa é quem tem o token**, e
    isso é o gerente — a plataforma cadastra a empresa e o usuário dela, e não tem
    credencial no meuWatt nem no meuPlano. Usar a credencial de serviço para montar a lista
    mostraria a carteira de quem a gerou, que não é a do inquilino.

    E a empresa vem da SESSÃO: uma rota de empresa que aceitasse o id de outra deixaria
    qualquer gerente apontar a empresa do vizinho para a dele.
    """
    from app.api.v1.empresa import VinculoIn, salvar_vinculos

    _a, _b, gerente = carteiras
    depois = salvar_vinculos(VinculoIn(mw_enterprise_id=1, mp_tenant_id=7), db=db, gerente=gerente)
    assert depois.mw_enterprise_id == 1 and depois.mp_tenant_id == 7

    # Campo ausente mantém; `null` explícito descasa — a régua de `mw_micro_plant_id`.
    depois = salvar_vinculos(VinculoIn(mp_tenant_id=9), db=db, gerente=gerente)
    assert depois.mw_enterprise_id == 1 and depois.mp_tenant_id == 9
    depois = salvar_vinculos(VinculoIn(mw_enterprise_id=None, mp_tenant_id=9), db=db, gerente=gerente)
    assert depois.mw_enterprise_id is None


def test_a_mesma_empresa_do_produto_nao_vincula_em_duas(db, carteiras, duas_empresas):
    """Duas linhas apontando para a mesma empresa de um produto seriam dois inquilinos
    lendo a mesma carteira. E a recusa NÃO diz de quem é o vínculo: o gerente de um
    inquilino não deve descobrir os nomes dos outros por tentativa."""
    from app.api.v1.empresa import VinculoIn, salvar_vinculos

    a, b, gerente = carteiras
    b.mw_enterprise_id = 42
    db.commit()

    with pytest.raises(HTTPException) as erro:
        salvar_vinculos(VinculoIn(mw_enterprise_id=42), db=db, gerente=gerente)
    assert erro.value.status_code == 409
    assert b.nome not in erro.value.detail, "o nome da outra empresa vazou na mensagem"


def test_a_plataforma_nao_casa_empresa(db):
    """A trava do desenho novo: as rotas de catálogo e de vínculo saíram do painel. Sem
    token, a plataforma não tem o que listar — e listar com a credencial de serviço
    mostraria a carteira de quem a gerou."""
    from app.api.v1 import painel_empresas

    assert not hasattr(painel_empresas, "catalogo")
    assert not hasattr(painel_empresas, "salvar_vinculos")


def test_promover_conta_existente_a_gerente(db, duas_empresas, administrador, carteiras):
    """"Criar gerente" não serve para quem já está no sistema: a conta traz usinas
    concedidas, tokens de produto e histórico, e recriá-la perderia tudo."""
    from app.api.v1.painel_empresas import tornar_gerente

    a, _b = duas_empresas
    cliente = db.scalar(select(User).where(User.apelido == "cliente.b"))

    saida = tornar_gerente(a.id, cliente.apelido, db=db, gestor=administrador)
    assert saida.perfil == "gestor_empresa"
    db.refresh(cliente)
    assert cliente.empresa_id == a.id and cliente.abre_empresa


def test_o_administrador_nao_se_rebaixa_a_gerente(db, duas_empresas, administrador):
    """Ele perderia o painel no mesmo instante, e a saída seria outro administrador ou o
    banco. O caminho certo é uma conta para cada papel."""
    from app.api.v1.painel_empresas import tornar_gerente

    a, _b = duas_empresas
    with pytest.raises(HTTPException) as erro:
        tornar_gerente(a.id, administrador.apelido, db=db, gestor=administrador)
    assert erro.value.status_code == 400


# ------------------------------------------------------ os papéis de uma pessoa


@pytest.fixture
def com_tres_papeis(db, duas_empresas, administrador):
    """O caso do dono: a mesma pessoa administra a plataforma, gerencia a O&M e é dona de
    uma usina. Três contas, um humano."""
    from app.models.pessoa import Pessoa

    a, _b = duas_empresas
    pessoa = Pessoa(nome="Renan")
    db.add(pessoa)
    db.flush()
    gerente = User(
        apelido="renan.om",
        nome="Renan (O&M)",
        perfil=Perfil.GESTOR_EMPRESA,
        empresa_id=a.id,
        pessoa_id=pessoa.id,
        senha_hash=gerar_hash_senha("om-12345"),
    )
    cliente = User(
        apelido="renan.dono",
        nome="Renan (usina)",
        perfil=Perfil.CLIENTE,
        empresa_id=a.id,
        pessoa_id=pessoa.id,
        senha_hash=gerar_hash_senha("dono-12345"),
    )
    administrador.pessoa_id = pessoa.id
    db.add_all([gerente, cliente])
    db.commit()
    return administrador, gerente, cliente


def test_descer_de_papel_nao_pede_senha(db, com_tres_papeis):
    """O conforto que motivou tudo: provada a senha de uma conta, as irmãs de alcance
    menor ficam a um clique."""
    from app.services import pessoas

    admin, gerente, cliente = com_tres_papeis
    assert pessoas.trocar(db, admin, "renan.om", None).id == gerente.id
    assert pessoas.trocar(db, admin, "renan.dono", None).id == cliente.id


def test_subir_para_a_plataforma_sempre_pede_a_senha(db, com_tres_papeis):
    """Defeito guardado, e é o caro: sem esta regra, uma sessão de aplicativo roubada —
    celular emprestado, token copiado — viraria sessão de administrador sem ninguém
    precisar saber nenhuma senha."""
    from app.services import pessoas

    admin, _gerente, cliente = com_tres_papeis

    with pytest.raises(HTTPException) as erro:
        pessoas.trocar(db, cliente, admin.apelido, None)
    assert erro.value.status_code == 401
    assert "senha" in erro.value.detail.lower()

    with pytest.raises(HTTPException):
        pessoas.trocar(db, cliente, admin.apelido, "senha-errada")

    assert pessoas.trocar(db, cliente, admin.apelido, "admin-1234").id == admin.id


def test_nao_se_troca_para_conta_de_outra_pessoa(db, com_tres_papeis, carteiras):
    """404 e não 403: dizer "existe, mas não é sua" confirmaria o apelido a quem está
    tentando descobrir apelidos."""
    from app.services import pessoas

    _admin, gerente, _cliente = com_tres_papeis
    with pytest.raises(HTTPException) as erro:
        pessoas.trocar(db, gerente, "gerente.a", None)
    assert erro.value.status_code == 404


def test_cada_papel_sai_com_o_token_do_portao_dele(db, com_tres_papeis):
    """A troca não funde papéis: ela entrega a sessão do OUTRO portão, e o token continua
    sendo recusado nos demais."""
    from app.services import pessoas

    admin, gerente, cliente = com_tres_papeis

    t_admin = _cred(pessoas.emitir(admin)[0])
    t_gerente = _cred(pessoas.emitir(gerente)[0])
    t_cliente = _cred(pessoas.emitir(cliente)[0])

    assert gestor_atual(cred=t_admin, db=db).id == admin.id
    assert gestor_empresa_atual(cred=t_gerente, db=db).id == gerente.id
    assert usuario_atual(cred=t_cliente, db=db).id == cliente.id

    with pytest.raises(HTTPException):
        gestor_atual(cred=t_gerente, db=db)
    with pytest.raises(HTTPException):
        usuario_atual(cred=t_admin, db=db)


def test_sem_agrupamento_a_pessoa_tem_um_papel_so(db, administrador):
    """Inventar irmãs por semelhança de nome ou de e-mail seria adivinhar identidade — e
    errar aqui abre a conta de alguém para outra pessoa."""
    from app.services import pessoas

    assert [c.id for c in pessoas.contas_da_pessoa(db, administrador)] == [administrador.id]
    with pytest.raises(HTTPException) as erro:
        pessoas.trocar(db, administrador, "quem.for", None)
    assert erro.value.status_code == 404


def test_agrupar_contas_de_pessoas_diferentes_e_recusado(db, com_tres_papeis, carteiras):
    """Fundir dois humanos num só faria a conta de um virar alcançável pela senha do
    outro — exatamente o que este módulo não pode permitir por engano."""
    from app.services import pessoas

    _admin, gerente, _cliente = com_tres_papeis
    outro = db.scalar(select(User).where(User.apelido == "gerente.a"))
    outro.pessoa_id = 999  # já agrupado noutra pessoa
    db.flush()

    with pytest.raises(HTTPException) as erro:
        pessoas.agrupar(db, [gerente, outro], "Mistura")
    assert erro.value.status_code == 409


def test_o_gerente_nao_aparece_na_tela_do_staff_da_plataforma(db, duas_empresas, administrador):
    """Defeito guardado: o gerente de um inquilino aparecia em Usuários do sistema por
    herança do filtro `!= CLIENTE` — misturado com quem administra a plataforma. Uma linha
    errada ali o promoveria a administrador do sistema inteiro."""
    from app.api.v1.painel_empresas import GerenteIn, criar_gerente
    from app.api.v1.painel_usuarios import listar

    a, _b = duas_empresas
    criar_gerente(a.id, GerenteIn(nome="Gerente", apelido="ger.um"), db=db, gestor=administrador)

    apelidos = {m.apelido for m in listar(db=db, _=administrador)}
    assert "ger.um" not in apelidos
    assert administrador.apelido in apelidos


def test_editar_gerente_pela_tela_do_staff_e_recusado(db, duas_empresas, administrador):
    """A mesma trava, do outro lado: mesmo sabendo o id, a rota do staff não mexe em conta
    que não é da plataforma."""
    from app.api.v1.painel_empresas import GerenteIn, criar_gerente
    from app.api.v1.painel_usuarios import MembroPatch, editar

    a, _b = duas_empresas
    novo = criar_gerente(a.id, GerenteIn(nome="Gerente Dois", apelido="ger.dois"), db=db, gestor=administrador)

    with pytest.raises(HTTPException) as erro:
        editar(novo.id, MembroPatch(perfil=Perfil.ADMINISTRADOR), db=db, admin=administrador)  # type: ignore[arg-type]
    assert erro.value.status_code == 404


def test_criar_gerente_marcando_que_e_meu_ja_agrupa(db, duas_empresas, administrador):
    """O caso do dono: administrar a plataforma e gerenciar a O&M. Marcando "é minha", a
    conta nasce no mesmo grupo e o seletor de papel já a mostra — sem uma segunda tela para
    alguém esquecer."""
    from app.api.v1.painel_empresas import GerenteIn, criar_gerente
    from app.services import pessoas

    a, _b = duas_empresas
    criado = criar_gerente(
        a.id, GerenteIn(nome="Eu, gerente", apelido="eu.om", minha=True), db=db, gestor=administrador
    )
    assert criado.agrupada

    db.refresh(administrador)
    apelidos = {c.apelido for c in pessoas.contas_da_pessoa(db, administrador)}
    assert apelidos == {administrador.apelido, "eu.om"}

    # E a troca já funciona para baixo, sem senha.
    assert pessoas.trocar(db, administrador, "eu.om", None).apelido == "eu.om"


def test_a_empresa_so_administra_quem_e_dela(db, duas_empresas, administrador):
    """Defeito guardado: trocar o número na barra de endereço e redefinir a senha de
    qualquer conta do sistema a partir de uma tela de empresa."""
    from app.api.v1.painel_empresas import GerenteIn, UsuarioPatch, criar_gerente, editar_usuario_da_empresa

    a, b = duas_empresas
    da_b = criar_gerente(b.id, GerenteIn(nome="Da B", apelido="ger.b"), db=db, gestor=administrador)

    with pytest.raises(HTTPException) as erro:
        editar_usuario_da_empresa(
            a.id, da_b.id, UsuarioPatch(senha="outra-senha-123"), db=db, gestor=administrador
        )
    assert erro.value.status_code == 404


def test_o_aviso_do_catalogo_traz_a_frase_do_produto(db, duas_empresas, administrador, monkeypatch):
    """Defeito guardado, visto na tela do dono em 28/09/2026: o aviso trazia o `str()` da
    exceção do httpx — "Client error '401 Unauthorized' for url 'https://.../admin/tenants'
    For more information check: https://developer.mozilla.org/..." —, com a URL interna do
    upstream e um convite a ler documentação de HTTP. A frase que resolvia estava do outro
    lado: "Token revogado. Emita um novo no meuPlano.".
    """
    import httpx

    from app.api.v1 import empresa as api_empresa
    from app.models.integracao import Produto

    resposta = httpx.Response(
        401,
        json={"detail": "Token revogado. Emita um novo no meuPlano."},
        request=httpx.Request("GET", "https://meuplano.exemplo/api/v1/meuacesso/admin/tenants"),
    )
    erro = httpx.HTTPStatusError("Client error '401 Unauthorized'", request=resposta.request, response=resposta)

    aviso = api_empresa._aviso(Produto.MEUPLANO, erro)
    assert "Token revogado" in aviso
    assert "developer.mozilla.org" not in aviso
    assert "meuplano.exemplo" not in aviso, "a URL interna do upstream foi para a tela"


def test_cada_portao_troca_a_propria_senha(db, carteiras, administrador):
    """Defeito guardado: a troca da própria senha só existia para o CLIENTE
    (`/api/v1/auth/trocar-senha`, que recusa sessão com escopo). Quem administra a
    plataforma e quem gerencia uma empresa não tinha como trocar a senha pela tela — a
    saída era outro administrador ou o banco. Pior na conta que nasce com senha
    provisória: ela fica com a senha que alguém digitou e viu.
    """
    from app.api.v1.sessao import SenhaIn, trocar_a_propria_senha
    from app.core.security import conferir_senha

    _a, _b, gerente = carteiras

    trocar_a_propria_senha(
        SenhaIn(senha_atual="senha-1234", senha_nova="senha-nova-999"), db=db, usuario=gerente
    )
    db.refresh(gerente)
    assert conferir_senha("senha-nova-999", gerente.senha_hash)

    # A senha atual é exigida mesmo com a sessão autenticada: um computador destravado e
    # esquecido não pode bastar para trancar o dono para fora.
    with pytest.raises(HTTPException) as erro:
        trocar_a_propria_senha(
            SenhaIn(senha_atual="chute", senha_nova="outra-senha-1"), db=db, usuario=administrador
        )
    assert erro.value.status_code == 400
    assert "não confere" in erro.value.detail

    # E as regras óbvias continuam valendo.
    for atual, nova, trecho in (
        ("admin-1234", "curta", "8 caracteres"),
        ("admin-1234", "admin-1234", "diferente"),
    ):
        with pytest.raises(HTTPException) as erro:
            trocar_a_propria_senha(SenhaIn(senha_atual=atual, senha_nova=nova), db=db, usuario=administrador)
        assert trecho in erro.value.detail


# --------------------------------------- o gerente opera a empresa dele sozinho


async def test_o_gerente_traz_usina_e_ela_nasce_da_empresa_dele(db, carteiras):
    """Defeito guardado, e o dono esbarrou nele: as telas do gerente eram só LEITURA — ele
    via "nenhuma usina" e a tela mandava falar com a plataforma. Mas é ele quem tem o token
    e enxerga a carteira nos produtos; a plataforma não tem credencial nenhuma."""
    from app.api.v1.empresa import UsinaIn, salvar_usina

    a, _b, gerente = carteiras
    nova = await salvar_usina(
        UsinaIn(mw_slug="usina-nova", nome="Usina Nova", no_app=True), db=db, gerente=gerente
    )
    assert nova.plant_link_id is not None

    trazida = db.get(PlantLink, nova.plant_link_id)
    assert trazida.empresa_id == a.id, "a usina nasceu sem dono ou com o dono errado"


async def test_o_gerente_nao_mexe_na_usina_de_outra_empresa(db, carteiras):
    """404, e não 403: dizer "existe, mas é de outra" já contaria o que existe na carteira
    do vizinho."""
    from app.api.v1.empresa import UsinaIn, salvar_usina

    _a, b, gerente = carteiras
    da_b = db.scalar(select(PlantLink).where(PlantLink.empresa_id == b.id))

    with pytest.raises(HTTPException) as erro:
        await salvar_usina(
            UsinaIn(plant_link_id=da_b.id, mw_slug="usina-b", nome="Roubada"),
            db=db,
            gerente=gerente,
        )
    assert erro.value.status_code == 404

    # E o identificador de produto de outra empresa é recusado sem dizer de quem é.
    with pytest.raises(HTTPException) as erro:
        await salvar_usina(UsinaIn(mw_slug="usina-b", nome="Outra tentativa"), db=db, gerente=gerente)
    assert erro.value.status_code == 409
    assert b.nome not in erro.value.detail


async def test_o_gerente_cadastra_cliente_e_concede_usinas(db, carteiras):
    """O fluxo inteiro do lado da empresa, que é o que o dono precisava: cadastrar o dono
    de usina e entregar a ele as usinas DA EMPRESA."""
    from app.api.v1.empresa import (
        ClienteIn,
        UsinaIn,
        UsinasDoClienteIn,
        criar_cliente,
        definir_usinas_do_cliente,
        listar_clientes,
        salvar_usina,
    )

    a, _b, gerente = carteiras
    usina = await salvar_usina(UsinaIn(mw_slug="nova-1", nome="Nova 1"), db=db, gerente=gerente)

    criado = criar_cliente(ClienteIn(nome="Dona Maria", apelido="dona.maria"), db=db, gerente=gerente)
    assert criado.senha

    definir_usinas_do_cliente(
        criado.id, UsinasDoClienteIn(plant_link_ids=[usina.plant_link_id]), db=db, gerente=gerente
    )

    na_lista = {c.apelido: c for c in listar_clientes(db=db, gerente=gerente)}
    assert na_lista["dona.maria"].usinas == 1

    # O cliente nasceu NA EMPRESA — é isso que o faz aparecer para este gerente e mais
    # ninguém.
    conta = db.scalar(select(User).where(User.apelido == "dona.maria"))
    assert conta.empresa_id == a.id


def test_nao_se_concede_usina_de_outra_empresa(db, carteiras):
    """Defeito guardado: um id na requisição concederia a usina de outra empresa, e o dono
    dela veria no aplicativo dados de uma carteira que não é a sua."""
    from app.api.v1.empresa import ClienteIn, UsinasDoClienteIn, criar_cliente, definir_usinas_do_cliente

    _a, b, gerente = carteiras
    da_b = db.scalar(select(PlantLink).where(PlantLink.empresa_id == b.id))
    criado = criar_cliente(ClienteIn(nome="Cliente Novo", apelido="cli.novo"), db=db, gerente=gerente)

    with pytest.raises(HTTPException) as erro:
        definir_usinas_do_cliente(
            criado.id, UsinasDoClienteIn(plant_link_ids=[da_b.id]), db=db, gerente=gerente
        )
    assert erro.value.status_code == 404


async def test_usina_sem_dono_e_ADOTADA_e_nao_recusada(db, carteiras):
    """Defeito guardado, e travou o dono na primeira tentativa: as usinas cadastradas
    ANTES do multiempresa estão sem dono, e o código tratava "sem dono" como "de outra
    empresa". As 7 usinas reais ficavam inalcançáveis, com a mensagem "já pertence a outra
    empresa" — que era falsa: ela não pertencia a ninguém.

    Trazer para a empresa é adotar a linha que existe, nunca criar uma segunda para a
    mesma usina.
    """
    from app.api.v1.empresa import UsinaIn, salvar_usina

    a, _b, gerente = carteiras
    orfa = PlantLink(nome="Órfã", mw_plant_slug="orfa-slug")
    db.add(orfa)
    db.commit()
    id_antes = orfa.id

    trazida = await salvar_usina(
        UsinaIn(mw_slug="orfa-slug", nome="Órfã", no_app=True), db=db, gerente=gerente
    )
    assert trazida.plant_link_id == id_antes, "criou uma segunda linha em vez de adotar"

    db.refresh(orfa)
    assert orfa.empresa_id == a.id
    assert db.scalar(
        select(func.count()).select_from(PlantLink).where(PlantLink.mw_plant_slug == "orfa-slug")
    ) == 1


async def test_casar_as_duas_pontas_na_mesma_linha(db, carteiras):
    """"Esta usina do meuWatt é aquela do meuPlano" — o que faltava na tela do gerente.

    É a MESMA operação de trazer: gravar o estado desejado da usina. Separada em
    "vincular" e "ligar", a tela chamaria duas rotas e a segunda poderia falhar depois da
    primeira, deixando a usina casada e fora do aplicativo.
    """
    from app.api.v1.empresa import UsinaIn, salvar_usina

    a, _b, gerente = carteiras
    so_mw = await salvar_usina(UsinaIn(mw_slug="so-mw", nome="Só meuWatt"), db=db, gerente=gerente)
    assert so_mw.origem == "meuwatt"

    casada = await salvar_usina(
        UsinaIn(plant_link_id=so_mw.plant_link_id, mw_slug="so-mw", mp_usina_id=77, nome="Casada"),
        db=db,
        gerente=gerente,
    )
    assert casada.origem == "ambos" and casada.mp_usina_id == 77
    assert db.get(PlantLink, casada.plant_link_id).empresa_id == a.id


# ------------------------------------- o cliente que não tem conta nos produtos


def test_cliente_sem_token_le_com_o_da_empresa(db, carteiras, duas_empresas):
    """Pergunta do dono, 29/09/2026: *"o cliente precisa colocar o token dele ou passa
    para mim?"*. Nenhum dos dois: o dono da usina costuma NÃO ter conta no meuWatt nem no
    meuPlano, e exigir um token dele tornaria impossível cadastrar quem só existe aqui.

    Quem tem conta nos produtos é a empresa que o atende. O que o cliente VÊ continua sendo
    o que foi concedido a ele — o token só diz com que credencial a leitura acontece.
    """
    from app.core.cripto import cifrar
    from app.models.integracao import Integracao, Produto
    from app.services import vinculos

    a, _b = duas_empresas
    cliente = User(apelido="sem.token", nome="Sem Token", perfil=Perfil.CLIENTE, empresa_id=a.id)
    db.add(cliente)
    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url="https://api.meuwatt.test",
            empresa_id=a.id,
            token_cifrado=cifrar("mw_pat_da_empresa"),
        )
    )
    db.commit()

    assert vinculos.token_do_cliente(db, cliente.id, Produto.MEUWATT) == "mw_pat_da_empresa"


def test_o_token_do_proprio_cliente_tem_preferencia(db, duas_empresas):
    """Quando existe, o dele é melhor: carrega o escopo que o produto já aplica, incluindo
    usina que a pessoa vê por pertencer a uma organização de lá."""
    from app.core.cripto import cifrar
    from app.models.integracao import Integracao, Produto
    from app.models.user import VinculoProduto
    from app.services import vinculos

    a, _b = duas_empresas
    cliente = User(apelido="com.token", nome="Com Token", perfil=Perfil.CLIENTE, empresa_id=a.id)
    db.add(cliente)
    db.flush()
    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url="https://api.meuwatt.test",
            empresa_id=a.id,
            token_cifrado=cifrar("mw_pat_da_empresa"),
        )
    )
    db.add(
        VinculoProduto(
            gs_user_id=cliente.id,
            produto=Produto.MEUWATT,
            usuario_remoto_id="9",
            token_cifrado=cifrar("mw_pat_do_cliente"),
        )
    )
    db.commit()

    assert vinculos.token_do_cliente(db, cliente.id, Produto.MEUWATT) == "mw_pat_do_cliente"


def test_cliente_sem_empresa_nao_cai_na_credencial_da_plataforma(db):
    """A trava do atalho: cliente sem empresa lendo com a credencial da PLATAFORMA leria a
    carteira de outra gente com a credencial de quem construiu o sistema."""
    from app.core.cripto import cifrar
    from app.models.integracao import Integracao, Produto
    from app.services import vinculos

    solto = User(apelido="solto", nome="Solto", perfil=Perfil.CLIENTE)
    db.add(solto)
    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url="https://api.meuwatt.test",
            token_cifrado=cifrar("mw_pat_da_PLATAFORMA"),
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as erro:
        vinculos.token_do_cliente(db, solto.id, Produto.MEUWATT)
    assert erro.value.status_code == 424


async def test_a_micro_usina_pertence_a_uma_usina_so(db, carteiras):
    """Pedido do dono: levar as micro usinas (Solis, Canadian, TSUN) para cá. Elas não são
    um quarto formato de usina — casam com uma que já existe, e servem a uma coisa: o aviso
    de parada delas chegar ao dono.

    Casar a mesma micro na segunda usina desfaria o primeiro par em silêncio, e o aviso
    passaria a chegar em nome da usina errada.
    """
    from app.api.v1.empresa import MicroVinculoIn, UsinaIn, casar_micro_usina, salvar_usina

    a, _b, gerente = carteiras
    u1 = await salvar_usina(UsinaIn(mw_slug="u-1", nome="Usina 1"), db=db, gerente=gerente)
    u2 = await salvar_usina(UsinaIn(mw_slug="u-2", nome="Usina 2"), db=db, gerente=gerente)

    casar_micro_usina(7, MicroVinculoIn(plant_link_id=u1.plant_link_id), db=db, gerente=gerente)
    assert db.get(PlantLink, u1.plant_link_id).mw_micro_plant_id == 7

    with pytest.raises(HTTPException) as erro:
        casar_micro_usina(7, MicroVinculoIn(plant_link_id=u2.plant_link_id), db=db, gerente=gerente)
    assert erro.value.status_code == 409 and "Usina 1" in erro.value.detail

    # Descasar libera a micro para outra usina.
    casar_micro_usina(7, MicroVinculoIn(plant_link_id=None), db=db, gerente=gerente)
    casar_micro_usina(7, MicroVinculoIn(plant_link_id=u2.plant_link_id), db=db, gerente=gerente)
    assert db.get(PlantLink, u1.plant_link_id).mw_micro_plant_id is None
    assert db.get(PlantLink, u2.plant_link_id).mw_micro_plant_id == 7


def test_micro_usina_nao_casa_com_usina_de_outra_empresa(db, carteiras):
    from app.api.v1.empresa import MicroVinculoIn, casar_micro_usina

    _a, b, gerente = carteiras
    da_b = db.scalar(select(PlantLink).where(PlantLink.empresa_id == b.id))
    with pytest.raises(HTTPException) as erro:
        casar_micro_usina(9, MicroVinculoIn(plant_link_id=da_b.id), db=db, gerente=gerente)
    assert erro.value.status_code == 404


# ---------------------------------------------------- "não mostrar esta usina"


def test_ocultar_tira_da_lista_e_volta(db, carteiras):
    """Pedido do dono: o token da empresa alcança 23 usinas e boa parte não interessa. Sem
    "não mostrar", elas ficam para sempre na lista de trazer.

    É preferência de TELA: não apaga nada, não sai do produto e não muda o que ninguém vê
    no aplicativo.
    """
    from app.api.v1.empresa import OcultarIn, listar_ocultas, mostrar_todas, ocultar_usina
    from app.models.integracao import Produto
    from app.models.usina_oculta import UsinaOculta

    a, _b, gerente = carteiras
    ocultar_usina(OcultarIn(mw_slug="nao-quero"), db=db, gerente=gerente)
    ocultar_usina(OcultarIn(mp_usina_id=99), db=db, gerente=gerente)
    # Ocultar duas vezes a mesma não duplica linha — o gerente clica de novo porque a tela
    # demorou, e isso não é erro dele.
    ocultar_usina(OcultarIn(mw_slug="nao-quero"), db=db, gerente=gerente)

    assert len(listar_ocultas(db=db, gerente=gerente)) == 2
    assert db.scalar(
        select(func.count()).select_from(UsinaOculta).where(UsinaOculta.empresa_id == a.id)
    ) == 2

    mostrar_todas(db=db, gerente=gerente)
    assert listar_ocultas(db=db, gerente=gerente) == []


async def test_a_micro_usina_sozinha_ja_e_uma_usina(db, carteiras):
    """Correção do dono, 29/09/2026: *"a micro usina não preciso casar com nada"*. Há
    cliente cujo único monitoramento é o portal do fabricante — exigir par no meuWatt o
    deixaria de fora do sistema."""
    from app.api.v1.empresa import UsinaIn, salvar_usina

    a, _b, gerente = carteiras
    so_micro = await salvar_usina(
        UsinaIn(mw_micro_plant_id=42, nome="Só no portal do fabricante"), db=db, gerente=gerente
    )
    assert so_micro.origem == "micro"
    assert so_micro.mw_micro_plant_id == 42

    trazida = db.get(PlantLink, so_micro.plant_link_id)
    assert trazida.empresa_id == a.id
    assert trazida.mw_plant_slug is None and trazida.mp_usina_id is None


async def test_usina_sem_nenhum_identificador_e_recusada(db, carteiras):
    """O corolário do dado morto: linha que não aponta para nada em produto nenhum é
    fantasma — aparece na lista e todas as telas dela vêm vazias."""
    from app.api.v1.empresa import UsinaIn, salvar_usina

    _a, _b, gerente = carteiras
    with pytest.raises(HTTPException) as erro:
        await salvar_usina(UsinaIn(nome="Fantasma"), db=db, gerente=gerente)
    assert erro.value.status_code == 400


def test_a_usina_so_do_MICRO_nao_e_classificada_como_meuPlano(db, carteiras):
    """Defeito guardado, e o dono o viu na tela: as 5 micro usinas apareceram no grupo
    "Só no meuPlano". `conciliacao.montar` só conhece os dois produtos e classifica como
    meuPlano tudo o que não tem slug — a origem tem de vir do LINK quando a usina já está
    aqui.
    """
    from app.api.v1.empresa import _origem

    micro = PlantLink(nome="Só micro", mw_micro_plant_id=9, empresa_id=carteiras[0].id)
    so_mp = PlantLink(nome="Só meuPlano", mp_usina_id=5, empresa_id=carteiras[0].id)
    nos_dois = PlantLink(
        nome="Nos dois", mw_plant_slug="s", mp_usina_id=6, mw_micro_plant_id=1,
        empresa_id=carteiras[0].id,
    )
    db.add_all([micro, so_mp, nos_dois])
    db.commit()

    assert _origem(micro) == "micro"
    assert _origem(so_mp) == "meuplano"
    # Com os dois produtos, a micro é detalhe do monitoramento — não muda a origem.
    assert _origem(nos_dois) == "ambos"


async def test_a_concessao_e_do_dono_de_usina_e_a_tela_le_antes_de_salvar(db, carteiras):
    """Defeito guardado, e o dono esbarrou nele: *"só consigo puxar as usinas da conta do
    gerente, mas não consigo atribuir aos usuários"*. A concessão é a de quem RECEBE a
    usina no aplicativo — o dono dela —, e a tela precisa ler o que já está concedido
    antes de salvar, porque a gravação é a lista completa.
    """
    from app.api.v1.empresa import (
        UsinaIn,
        UsinasDoClienteIn,
        definir_usinas_do_cliente,
        salvar_usina,
        usinas_do_usuario,
    )

    a, _b, gerente = carteiras
    u = await salvar_usina(UsinaIn(mw_slug="p-1", nome="Para o dono"), db=db, gerente=gerente)
    dono = db.scalar(select(User).where(User.apelido == "cliente.b"))
    dono.empresa_id = a.id
    db.commit()

    # Abre vazia, e é por isso que a tela precisa desta rota antes de salvar.
    assert usinas_do_usuario(dono.id, db=db, gerente=gerente) == []

    definir_usinas_do_cliente(
        dono.id, UsinasDoClienteIn(plant_link_ids=[u.plant_link_id]), db=db, gerente=gerente
    )
    concedidas = usinas_do_usuario(dono.id, db=db, gerente=gerente)
    assert [c.plant_link_id for c in concedidas] == [u.plant_link_id]
    assert concedidas[0].da_empresa is True


def test_nao_se_le_a_concessao_de_conta_de_outra_empresa(db, carteiras, duas_empresas):
    from app.api.v1.empresa import usinas_do_usuario

    _a, b, gerente = carteiras
    de_outra = db.scalar(select(User).where(User.empresa_id == b.id, User.perfil == Perfil.CLIENTE))
    with pytest.raises(HTTPException) as erro:
        usinas_do_usuario(de_outra.id, db=db, gerente=gerente)
    assert erro.value.status_code == 404


def test_a_lista_de_usuarios_aguenta_conta_com_token_proprio(db, carteiras, duas_empresas):
    """Defeito guardado, e derrubou a tela inteira com 500 em produção:
    `VinculoProduto.produto` é TEXTO no banco, e não o enum `Produto` — diferente de
    `Integracao.produto`, que é `Enum(...)`. O código chamou `.value` nele.

    Os dois modelos se parecem o bastante para enganar, e nenhum teste exercitava a lista
    com uma conta que TEM token próprio — que é justamente o caso do dono.
    """
    from app.api.v1.empresa import usuarios_detalhados
    from app.core.cripto import cifrar
    from app.models.integracao import Produto
    from app.models.user import VinculoProduto

    a, _b = duas_empresas
    _x, _y, gerente = carteiras
    cliente = User(apelido="com.conta", nome="Com Conta", perfil=Perfil.CLIENTE, empresa_id=a.id)
    db.add(cliente)
    db.flush()
    db.add(
        VinculoProduto(
            gs_user_id=cliente.id,
            produto=Produto.MEUWATT,
            usuario_remoto_id="11",
            token_cifrado=cifrar("mw_pat_dele"),
        )
    )
    db.commit()

    por_apelido = {u.apelido: u for u in usuarios_detalhados(db=db, gerente=gerente)}
    assert por_apelido["com.conta"].produtos == ["meuwatt"]
    # E quem não tem token próprio diz isso com uma lista vazia — é o caso comum.
    assert por_apelido[gerente.apelido].produtos == []


# ------------------------------------------- a concessão herdada, e o vazamento


def test_o_cliente_nunca_ve_usina_de_OUTRA_empresa_mesmo_concedida(db, carteiras, duas_empresas):
    """A trava que faltava, e é a causa raiz de verdade: a CONCESSÃO sozinha deixou de
    bastar quando o sistema virou multiempresa. Uma linha antiga apontando para usina que
    hoje é de outro inquilino faria o dono ver, no aplicativo, a carteira de um
    concorrente — e nada na tela indicaria isso.
    """
    from app.api.v1.plants import usinas_do_usuario as escopo_do_app
    from app.models.user import UserPlantAccess

    a, b = duas_empresas
    cliente = User(apelido="da.a", nome="Da A", perfil=Perfil.CLIENTE, empresa_id=a.id)
    db.add(cliente)
    da_a = PlantLink(nome="Minha", mw_plant_slug="minha", empresa_id=a.id)
    da_b = PlantLink(nome="Do concorrente", mw_plant_slug="dele", empresa_id=b.id)
    orfa = PlantLink(nome="Herdada", mw_plant_slug="herdada")  # sem dono
    db.add_all([da_a, da_b, orfa])
    db.flush()
    for u in (da_a, da_b, orfa):
        db.add(UserPlantAccess(user_id=cliente.id, plant_link_id=u.id))
    db.commit()

    nomes = {u.nome for u in escopo_do_app(db, cliente)}
    assert "Minha" in nomes
    assert "Do concorrente" not in nomes, "a usina de outra empresa vazou para o cliente"
    # A sem dono continua: é o estado de quem existia antes do multiempresa, e esconder o
    # que a pessoa já via seria tirar funcionalidade por causa de migração pendente.
    assert "Herdada" in nomes


def test_a_herdada_e_ADOTADA_e_a_frase_que_travou_o_dono_nao_existe_mais(db, carteiras):
    """A garantia pedida em 30/09/2026: "Esta usina ainda não é da sua empresa" não pode
    voltar por caminho nenhum.

    A usina sem dono é de antes do multiempresa. Esta tela a mostra MARCADA, porque
    alguém da empresa já a recebe — e mandá-la de volta no "salvar" é o clique mais comum
    que existe aqui. A versão anterior respondia com um 409 que mandava "trazer em
    Usinas", onde ela não aparecia: o catálogo sai do upstream, e uma herdada só do
    meuPlano não tem `mw_slug`. Quem já a enxerga é dono dela; adotar é gravar o que já
    era verdade.
    """
    from app.api.v1.empresa import UsinasDoClienteIn, definir_usinas_do_cliente
    from app.models.user import UserPlantAccess

    a, _b, gerente = carteiras
    orfa = PlantLink(nome="UFV Herdada", mw_plant_slug="ufv-herdada")
    dono = db.scalar(select(User).where(User.apelido == "cliente.b"))
    dono.empresa_id = a.id
    db.add(orfa)
    db.flush()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=orfa.id))
    db.commit()

    definir_usinas_do_cliente(
        dono.id, UsinasDoClienteIn(plant_link_ids=[orfa.id]), db=db, gerente=gerente
    )
    db.refresh(orfa)
    assert orfa.empresa_id == a.id, "a herdada que a empresa já enxerga passa a ser dela"


def test_a_orfa_que_ninguem_desta_empresa_recebe_continua_404(db, carteiras):
    """A adoção é estreita de propósito. Sem isto, o campo viraria "reivindique qualquer
    usina órfã por número" — e o 404 é sem nome para não entregar a carteira do vizinho a
    quem chuta."""
    from app.api.v1.empresa import UsinasDoClienteIn, definir_usinas_do_cliente

    a, _b, gerente = carteiras
    orfa = PlantLink(nome="Órfã de ninguém", mw_plant_slug="orfa-de-ninguem")
    dono = db.scalar(select(User).where(User.apelido == "cliente.b"))
    dono.empresa_id = a.id
    db.add(orfa)
    db.commit()

    with pytest.raises(HTTPException) as erro:
        definir_usinas_do_cliente(
            dono.id, UsinasDoClienteIn(plant_link_ids=[orfa.id]), db=db, gerente=gerente
        )
    assert erro.value.status_code == 404
    assert "Órfã de ninguém" not in erro.value.detail
    assert "não é da sua empresa" not in erro.value.detail


async def test_a_tela_enxerga_a_concessao_herdada(db, carteiras):
    """Sem o `da_empresa`, a herdada ia junto no "salvar" e voltava como erro sem nome — o
    gerente não tinha como saber qual caixa desmarcar."""
    from app.api.v1.empresa import UsinaIn, salvar_usina, usinas_do_usuario
    from app.models.user import UserPlantAccess

    a, _b, gerente = carteiras
    minha = await salvar_usina(UsinaIn(mw_slug="da-casa", nome="Da casa"), db=db, gerente=gerente)
    orfa = PlantLink(nome="Herdada", mw_plant_slug="herdada-2")
    db.add(orfa)
    db.flush()
    db.add_all([
        UserPlantAccess(user_id=gerente.id, plant_link_id=minha.plant_link_id),
        UserPlantAccess(user_id=gerente.id, plant_link_id=orfa.id),
    ])
    db.commit()

    por_nome = {c.nome: c for c in usinas_do_usuario(gerente.id, db=db, gerente=gerente)}
    assert por_nome["Da casa"].da_empresa is True
    assert por_nome["Herdada"].da_empresa is False


def test_o_gerente_cria_dono_de_usina_e_outro_gerente(db, carteiras):
    """O botão que faltava na tela de Usuários. São os dois únicos papéis que existem
    dentro de uma empresa — os da plataforma não se criam daqui, e pedi-los seria dar a um
    inquilino a chave do sistema inteiro."""
    from app.api.v1.empresa import ClienteIn, criar_cliente

    a, _b, gerente = carteiras
    dono = criar_cliente(ClienteIn(nome="Dono Novo", apelido="dono.novo"), db=db, gerente=gerente)
    colega = criar_cliente(
        ClienteIn(nome="Colega", apelido="colega.om", perfil=Perfil.GESTOR_EMPRESA),
        db=db,
        gerente=gerente,
    )

    por_apelido = {u.apelido: u for u in db.scalars(select(User)).all()}
    assert por_apelido["dono.novo"].perfil is Perfil.CLIENTE
    assert por_apelido["colega.om"].perfil is Perfil.GESTOR_EMPRESA
    assert por_apelido["colega.om"].empresa_id == a.id
    assert dono.senha and colega.senha

    with pytest.raises(HTTPException) as erro:
        criar_cliente(
            ClienteIn(nome="Chefe", apelido="chefe", perfil=Perfil.ADMINISTRADOR),
            db=db,
            gerente=gerente,
        )
    assert erro.value.status_code == 400


def test_cliente_no_painel_ouve_ONDE_entrar_e_nao_senha_invalida(db, carteiras, duas_empresas):
    """Defeito guardado, e o dono o viveu: criou uma conta de dono de usina, anotou a
    senha, tentou no painel e leu "apelido ou senha inválidos". Passou a procurar defeito
    na senha, que estava certa — só o endereço é que era outro.

    A mensagem única continua para quem NÃO provou a senha. Quem provou é o dono da conta,
    e dizer-lhe onde entrar não ensina nada a quem está adivinhando.
    """
    from app.api.v1.painel import EntrarIn, entrar

    a, _b = duas_empresas
    dono = User(
        apelido="dona.usina",
        nome="Dona da Usina",
        perfil=Perfil.CLIENTE,
        empresa_id=a.id,
        senha_hash=gerar_hash_senha("senha-certa-1"),
    )
    db.add(dono)
    db.commit()

    with pytest.raises(HTTPException) as erro:
        entrar(EntrarIn(apelido="dona.usina", senha="senha-certa-1"), db=db)
    assert erro.value.status_code == 403
    assert "aplicativo" in erro.value.detail and "senha está certa" in erro.value.detail

    # E com a senha ERRADA continua a frase única, sem contar que a conta existe.
    with pytest.raises(HTTPException) as erro:
        entrar(EntrarIn(apelido="dona.usina", senha="chute"), db=db)
    assert erro.value.status_code == 401
    assert erro.value.detail == "Apelido ou senha inválidos"


async def test_o_gerente_ve_a_carteira_inteira_sem_concessao(db, carteiras, duas_empresas):
    """A causa raiz que a prova em produção revelou: eu tinha feito o gerente depender de
    concessão, e isso o punha a COMPETIR com os clientes pela mesma usina. A regra da casa
    é "cada usina pertence a um cliente só", então conceder ao gerente o que já era de um
    dono era recusado — e a recusa estava certa. O erro era a premissa.

    Gerente vê a carteira da empresa por ser gerente. Uma concessão para ele seria uma
    segunda verdade sobre o mesmo fato.
    """
    from app.api.v1.empresa import UsinaIn, UsinasDoClienteIn, definir_usinas_do_cliente, salvar_usina
    from app.api.v1.plants import usinas_do_usuario as escopo_do_app

    a, _b, gerente = carteiras
    u1 = await salvar_usina(UsinaIn(mw_slug="c-1", nome="Carteira 1"), db=db, gerente=gerente)
    u2 = await salvar_usina(UsinaIn(mw_slug="c-2", nome="Carteira 2"), db=db, gerente=gerente)

    # Sem conceder nada a ele, as duas já aparecem — mais a que a fixture criou.
    nomes = {u.nome for u in escopo_do_app(db, gerente)}
    assert {"Carteira 1", "Carteira 2"} <= nomes

    # E o dono de usina recebe a MESMA usina sem conflito com o gerente.
    cliente = db.scalar(select(User).where(User.apelido == "cliente.b"))
    cliente.empresa_id = a.id
    db.commit()
    definir_usinas_do_cliente(
        cliente.id, UsinasDoClienteIn(plant_link_ids=[u1.plant_link_id]), db=db, gerente=gerente
    )
    assert {u.nome for u in escopo_do_app(db, cliente)} == {"Carteira 1"}

    # Conceder ao gerente é recusado com a frase que explica por quê.
    with pytest.raises(HTTPException) as erro:
        definir_usinas_do_cliente(
            gerente.id, UsinasDoClienteIn(plant_link_ids=[u2.plant_link_id]), db=db, gerente=gerente
        )
    assert erro.value.status_code == 400 and "já vê todas" in erro.value.detail


async def test_a_MICRO_aparece_no_app_do_gerente(db, carteiras):
    """O pedido, em uma frase: as micro usinas têm de aparecer no aplicativo do gerente.

    Duas coisas precisam ser verdade ao mesmo tempo, e cada uma quebrou uma vez hoje:
    a usina só-MICRO existe como usina (não é complemento de outra), e o gerente vê a
    carteira da empresa sem depender de concessão.
    """
    from app.api.v1.empresa import UsinaIn, salvar_usina
    from app.api.v1.plants import usinas_do_usuario as escopo_do_app

    _a, _b, gerente = carteiras
    await salvar_usina(UsinaIn(mw_micro_plant_id=1, nome="Micro do Sítio"), db=db, gerente=gerente)
    await salvar_usina(UsinaIn(mw_micro_plant_id=2, nome="Micro do Stuqui"), db=db, gerente=gerente)

    nomes = {u.nome for u in escopo_do_app(db, gerente)}
    assert {"Micro do Sítio", "Micro do Stuqui"} <= nomes, "micro usina fora do app do gerente"


def test_o_gerente_nunca_mais_ouve_que_a_usina_nao_e_da_empresa(db, carteiras):
    """A garantia que o dono pediu: o erro que o travou não pode voltar por caminho nenhum.

    Ele nascia de uma premissa errada — gerente dependendo de concessão. Com a premissa
    corrigida, a rota recusa a tentativa ANTES de olhar usina, com a frase que explica; e
    a tela não oferece mais o botão. São duas portas, e a de baixo é esta.
    """
    from app.api.v1.empresa import UsinasDoClienteIn, definir_usinas_do_cliente

    _a, _b, gerente = carteiras
    orfa = PlantLink(nome="UFV Leme", mw_plant_slug="ufv-leme-teste")
    db.add(orfa)
    db.commit()

    # Mesmo mandando a usina órfã — o caso exato que ele viu — a resposta é sobre o
    # PAPEL, não sobre a usina: não há o que conceder a um gerente.
    with pytest.raises(HTTPException) as erro:
        definir_usinas_do_cliente(
            gerente.id, UsinasDoClienteIn(plant_link_ids=[orfa.id]), db=db, gerente=gerente
        )
    assert erro.value.status_code == 400
    assert "já vê todas as usinas" in erro.value.detail
    assert "não é da sua empresa" not in erro.value.detail
