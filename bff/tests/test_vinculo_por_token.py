"""A conta do cliente conectada pelo token dele.

O que estes testes guardam é a mudança de fundo: o vínculo deixou de ser uma **afirmação
do gestor** e passou a ser uma **resposta do produto**. Três consequências, e cada uma
tem um teste porque cada uma já falhou na vida real ou falharia em silêncio:

1. **A identidade vem do produto, não do formulário.** O `usuario_remoto_id` gravado é o
   que o upstream respondeu ao token apresentado. Era aqui que morava o engano antigo:
   alguém digitava o e-mail errado, o painel gravava, e a discrepância só aparecia
   semanas depois como usina faltando na tela de alguém.
2. **Verificar antes de gravar.** Token recusado não toca o vínculo anterior — quem tinha
   uma conexão funcionando continua com ela.
3. **Ler e entrar são coisas separadas.** O login no produto pode falhar sozinho (chave
   de assinatura ausente, produto sem a rota ainda) sem invalidar uma conexão provada
   boa — mas nunca em silêncio.

E, como em `test_conexao_por_token.py`, que o valor do token não fique em claro no banco.
"""

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import cripto
from app.models.integracao import Integracao, Produto
from app.models.user import Perfil, User, VinculoProduto
from app.services import login_externo, vinculos

#: Guardada antes de qualquer substituição — ver `_sem_login_externo`.
HABILITAR_REAL = login_externo.habilitar

MW = "mw_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"
MP = "mp_pat_FhKANi2Ee1IqJuvvz3jCLI18f8ATEnNJ3ZKQcz"
#: Um segundo token do meuWatt, para o caso de substituição.
MW2 = "mw_pat_gg4ZTOXBiFVQPfPYqiTMc7OHgWTmIfyG2VbN0Q"


@pytest.fixture(autouse=True)
def _chave_de_teste(monkeypatch):
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))


@pytest.fixture(autouse=True)
def _sem_login_externo(monkeypatch):
    """Por padrão, habilitar o login no produto é um não-evento.

    Os testes de conexão tratam de conectar; o que acontece com o login tem os seus, mais
    abaixo. Sem esta substituição todos eles sairiam à rede.
    """

    async def _nada(db, **kw):
        return None

    monkeypatch.setattr(login_externo, "habilitar", _nada)


@pytest.fixture
def cliente(db):
    c = User(apelido="janderson", email="janderson@eninsa.com.br", nome="Janderson", perfil=Perfil.CLIENTE)
    db.add(c)
    db.commit()
    return c


@pytest.fixture(autouse=True)
def _enderecos(db):
    """O endereço de cada produto continua sendo do sistema — sem ele não há para onde ir."""
    db.add(Integracao(produto=Produto.MEUWATT, base_url="https://api.meuwatt.com.br"))
    db.add(Integracao(produto=Produto.MEUPLANO, base_url="https://meuplano.up.railway.app"))
    db.commit()


class _Upstream:
    """Um produto de mentira: responde a identidade e as usinas que lhe mandarem responder."""

    def __init__(self, identidade=None, usinas=None, erro=None):
        self._identidade = identidade or {"id": "45", "nome": "Janderson", "email": "janderson@eninsa.com.br"}
        self._usinas = usinas if usinas is not None else [{"slug": "porto-ferreira", "id": 1}]
        self._erro = erro

    async def identidade(self, token=None):
        if self._erro:
            raise self._erro
        return self._identidade

    async def usinas(self, token=None):
        if self._erro:
            raise self._erro
        return self._usinas


def _responde(monkeypatch, **kw):
    upstream = _Upstream(**kw)
    monkeypatch.setattr(vinculos, "MeuWattClient", lambda **_: upstream)
    monkeypatch.setattr(vinculos, "MeuPlanoClient", lambda **_: upstream)
    return upstream


# ── 1. a identidade vem do produto ───────────────────────────────────────────


class TestIdentidadeVemDoProduto:
    async def test_grava_quem_o_produto_disse_que_e(self, db, cliente, administrador, monkeypatch):
        _responde(monkeypatch)

        r = await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        assert r.ok
        v = vinculos.obter(db, cliente.id, Produto.MEUWATT)
        # Nada disso foi digitado: veio da resposta ao token.
        assert v.usuario_remoto_id == "45"
        assert v.usuario_remoto_nome == "Janderson"
        assert v.usinas_visiveis == 1
        assert v.estado == "ok"

    async def test_o_token_nao_fica_em_claro(self, db, cliente, administrador, monkeypatch):
        _responde(monkeypatch)
        await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        v = vinculos.obter(db, cliente.id, Produto.MEUWATT)
        assert MW not in (v.token_cifrado or "")
        # O prefixo, sim: é por ele que se acha o token certo na lista do produto para
        # revogar. Sem isso, revogar vira tentativa e erro.
        assert v.token_prefixo == "mw_pat_1xNq"
        assert cripto.decifrar(v.token_cifrado) == MW

    async def test_o_token_volta_utilizavel_para_ler_como_o_cliente(
        self, db, cliente, administrador, monkeypatch
    ):
        _responde(monkeypatch)
        await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)
        assert vinculos.token_do_cliente(db, cliente.id, Produto.MEUWATT) == MW


# ── 2. verificar antes de gravar ─────────────────────────────────────────────


class TestVerificarAntesDeGravar:
    async def test_formato_errado_nem_chega_a_rede(self, db, cliente, administrador, monkeypatch):
        def _explode(**_):
            raise AssertionError("não deveria ter saído à rede")

        monkeypatch.setattr(vinculos, "MeuWattClient", _explode)

        r = await vinculos.conectar(db, cliente, Produto.MEUWATT, MP, por=administrador)

        assert not r.ok
        assert "token do meuPlano" in r.detalhe
        assert vinculos.obter(db, cliente.id, Produto.MEUWATT) is None

    async def test_token_recusado_nao_derruba_a_conexao_anterior(
        self, db, cliente, administrador, monkeypatch
    ):
        _responde(monkeypatch)
        await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)
        antes = vinculos.obter(db, cliente.id, Produto.MEUWATT).token_cifrado

        recusa = httpx.HTTPStatusError(
            "401",
            request=httpx.Request("GET", "https://api.meuwatt.com.br/auth/me"),
            response=httpx.Response(401, json={"detail": "Token revogado"}),
        )
        _responde(monkeypatch, erro=recusa)
        r = await vinculos.conectar(db, cliente, Produto.MEUWATT, MW2, por=administrador)

        assert not r.ok
        assert "revogado" in r.detalhe
        # O que estava de pé continua de pé: é a razão de a ordem ser esta.
        assert vinculos.obter(db, cliente.id, Produto.MEUWATT).token_cifrado == antes

    async def test_conta_que_nao_ve_usina_nenhuma_e_recusada_com_o_motivo(
        self, db, cliente, administrador, monkeypatch
    ):
        # Aceita e vazia é o pior desfecho: o aplicativo abriria sem erro e sem nada.
        _responde(monkeypatch, usinas=[])

        r = await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        assert not r.ok
        assert "não enxerga nenhuma usina" in r.detalhe
        assert vinculos.obter(db, cliente.id, Produto.MEUWATT) is None

    async def test_produto_que_nao_diz_de_quem_e_o_token_e_recusado(
        self, db, cliente, administrador, monkeypatch
    ):
        # Sem id não há vínculo: é ele que fica gravado e é por ele que o produto
        # reconhece a pessoa depois.
        _responde(monkeypatch, identidade={"id": "", "nome": "Alguém", "email": None})

        r = await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        assert not r.ok
        assert "não disse a qual conta" in r.detalhe


# ── 3. ler e entrar são coisas separadas ─────────────────────────────────────


class TestLoginEhOutraCoisa:
    async def test_falha_do_login_nao_invalida_a_conexao(
        self, db, cliente, administrador, monkeypatch
    ):
        _responde(monkeypatch)

        async def _sem_chave(db_, **kw):
            return "sem chave de assinatura configurada"

        monkeypatch.setattr(login_externo, "habilitar", _sem_chave)

        r = await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        # A conexão vale: o token foi provado bom e serve para ler.
        assert r.ok
        assert vinculos.obter(db, cliente.id, Produto.MEUWATT).conectado
        # E a outra metade não passa calada.
        assert r.aviso_login == "sem chave de assinatura configurada"
        assert r.login_externo is False

    async def test_sem_chave_o_modulo_diz_e_nao_levanta(self, db, cliente, monkeypatch):
        # A função REAL, não a substituição do `_sem_login_externo`: o que este teste
        # verifica é justamente o comportamento que os outros dispensam.
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "gs_sso_private_key", "")

        aviso = await HABILITAR_REAL(
            db, cliente=cliente, produto=Produto.MEUWATT, base_url="https://x", token=MW
        )

        assert aviso is not None and "GS_SSO_PRIVATE_KEY" in aviso


# ── testar e desconectar ─────────────────────────────────────────────────────


class TestTestarEDesconectar:
    async def test_testar_reconfirma_a_identidade(self, db, cliente, administrador, monkeypatch):
        _responde(monkeypatch)
        await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        # A conta foi renomeada lá. Repetir o que era verdade no dia em que o token foi
        # colado faria a tela mentir sobre o presente.
        _responde(monkeypatch, identidade={"id": "45", "nome": "Janderson Diego", "email": "j@e.com.br"})
        r = await vinculos.testar(db, cliente, Produto.MEUWATT)

        assert r.ok
        assert vinculos.obter(db, cliente.id, Produto.MEUWATT).usuario_remoto_nome == "Janderson Diego"

    async def test_testar_marca_falhou_sem_apagar_o_token(
        self, db, cliente, administrador, monkeypatch
    ):
        _responde(monkeypatch)
        await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        _responde(monkeypatch, erro=httpx.ConnectError("sem rota"))
        r = await vinculos.testar(db, cliente, Produto.MEUWATT)

        v = vinculos.obter(db, cliente.id, Produto.MEUWATT)
        assert not r.ok and v.estado == "falhou"
        # O produto estar fora do ar não é motivo para jogar fora a credencial.
        assert v.token_cifrado is not None

    async def test_desconectar_apaga_o_vinculo_inteiro(
        self, db, cliente, administrador, monkeypatch
    ):
        _responde(monkeypatch)
        await vinculos.conectar(db, cliente, Produto.MEUWATT, MW, por=administrador)

        vinculos.desconectar(db, cliente, Produto.MEUWATT)

        assert vinculos.obter(db, cliente.id, Produto.MEUWATT) is None
        # Nem um resto cifrado: guardar segredo sem uso é risco sem contrapartida.
        assert db.query(VinculoProduto).count() == 0

    def test_ler_sem_token_diz_o_que_fazer(self, db, cliente):
        with pytest.raises(vinculos.SemConexao, match="cole o token"):
            vinculos.token_do_cliente(db, cliente.id, Produto.MEUWATT)
