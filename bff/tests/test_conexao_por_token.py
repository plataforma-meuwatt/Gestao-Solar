"""A conexão por token: validação de formato, gravação e diagnóstico.

Três coisas são verificadas aqui, e as três existem por causa de um mesmo problema — um
401 do upstream não diz nada a quem está olhando a tela:

1. **O formato pega o engano antes da rede.** Token do produto errado e cópia truncada
   são os dois enganos prováveis de quem tem dois valores longos na área de transferência
   e duas caixas parecidas na tela.
2. **Verificar antes de gravar.** Se o token não serve, a conexão anterior — que podia
   estar funcionando — continua de pé. Gravar primeiro e testar depois deixaria o gestor
   com as duas coisas quebradas e nenhum caminho de volta.
3. **Cada falha tem a sua frase.** Recusado, endereço errado, servidor fora e "aceito mas
   não vê usina nenhuma" pedem correções diferentes.

Também se verifica que o valor do token nunca aparece em claro no banco nem no histórico.
"""

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import cripto
from app.core.tokens_produto import TAMANHO, TokenInvalido, prefixo_visivel, valido, validar
from app.models.integracao import EstadoTeste, Integracao, IntegracaoEvento, Produto
from app.services import integracoes

# Tokens de exemplo com dígito verificador correto, gerados pelo formato dos produtos.
# Fixos no arquivo de propósito: se o formato mudar de um lado só, estes param de valer e
# o teste acusa — que é exatamente o alarme que se quer.
MW = "mw_pat_1xNq7BRe4VjtKjjVeAKiQDOPhoccF47X00gaAL"
MP = "mp_pat_FhKANi2Ee1IqJuvvz3jCLI18f8ATEnNJ3ZKQcz"


@pytest.fixture(autouse=True)
def _chave_de_teste(monkeypatch):
    """Cifra com chave descartável — o .env de teste não tem GS_ENCRYPTION_KEY."""
    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))


# ── 1. formato ───────────────────────────────────────────────────────────────


class TestFormato:
    def test_aceita_o_token_do_proprio_produto(self):
        assert validar(Produto.MEUWATT, MW) == MW
        assert validar(Produto.MEUPLANO, MP) == MP
        assert valido(Produto.MEUWATT, MW) and valido(Produto.MEUPLANO, MP)

    def test_campos_trocados_dizem_exatamente_isso(self):
        """O engano provável da tela: dois valores parecidos, duas caixas parecidas."""
        with pytest.raises(TokenInvalido, match="token do meuPlano.*campo é do meuWatt"):
            validar(Produto.MEUWATT, MP)
        with pytest.raises(TokenInvalido, match="token do meuWatt.*campo é do meuPlano"):
            validar(Produto.MEUPLANO, MW)

    def test_copia_cortada_diz_que_esta_cortada(self):
        with pytest.raises(TokenInvalido, match="cortada"):
            validar(Produto.MEUWATT, MW[:-3])

    def test_caractere_trocado_cai_no_verificador(self):
        trocado = MW[:12] + ("A" if MW[12] != "A" else "B") + MW[13:]
        assert len(trocado) == TAMANHO  # tamanho certo: só o verificador acusa
        with pytest.raises(TokenInvalido, match="verificador"):
            validar(Produto.MEUWATT, trocado)

    def test_lixo_e_vazio(self):
        for ruim in ("", "   ", "senha123", "Bearer " + MW):
            assert not valido(Produto.MEUWATT, ruim)

    def test_espacos_em_volta_sao_tolerados(self):
        assert validar(Produto.MEUWATT, f"  {MW}\n") == MW

    def test_prefixo_visivel_identifica_sem_revelar(self):
        p = prefixo_visivel(MW)
        assert p == "mw_pat_1xNq" and p not in ("", MW)
        assert MW[len(p):] not in p


# ── 2. gravação ──────────────────────────────────────────────────────────────


def _upstream(monkeypatch, *, perfil=None, usinas=None, erro=None):
    """Substitui o cliente do produto por um que responde o combinado."""

    class ClienteFalso:
        def __init__(self, *a, **kw):
            pass

        async def quem_sou_eu(self, token=None):
            if erro is not None:
                raise erro
            return perfil or {"name": "Fulano", "email": "fulano@empresa.com.br"}

        async def usinas(self, token=None):
            if erro is not None:
                raise erro
            return usinas if usinas is not None else [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(integracoes, "_cliente", lambda produto, base_url, token: ClienteFalso())


async def test_conecta_grava_cifrado_e_identifica_o_dono(db, monkeypatch):
    _upstream(monkeypatch)
    r = await integracoes.salvar_token(
        db, Produto.MEUWATT, "https://api.meuwatt.com.br/", MW, ator_email="admin@gs.local"
    )

    assert r.ok and r.usinas == 2 and r.dono_nome == "Fulano"
    assert "Fulano" in r.detalhe  # a tela mostra de quem é o token

    linha = integracoes.obter(db, Produto.MEUWATT)
    assert linha.por_token and linha.estado is EstadoTeste.OK
    assert linha.base_url == "https://api.meuwatt.com.br"  # barra final normalizada
    assert linha.token_prefixo == "mw_pat_1xNq"
    assert linha.token_dono_email == "fulano@empresa.com.br"
    assert cripto.decifrar(linha.token_cifrado) == MW


async def test_o_token_nunca_fica_em_claro_no_banco(db, monkeypatch):
    """A garantia que justifica cifrar: um dump do Postgres do BFF não pode entregar
    acesso aos dois outros sistemas."""
    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)

    linha = integracoes.obter(db, Produto.MEUWATT)
    for valor in (linha.token_cifrado, linha.token_prefixo, linha.detalhe_teste or ""):
        assert MW not in valor
    for e in db.query(IntegracaoEvento).all():
        assert MW not in (e.detalhe or "") and MW not in (e.token_prefixo or "")


async def test_token_do_produto_errado_nem_chega_na_rede(db, monkeypatch):
    def explode(*a, **kw):
        raise AssertionError("não devia ter chamado o upstream")

    monkeypatch.setattr(integracoes, "_cliente", explode)
    r = await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MP)

    assert not r.ok and "token do meuPlano" in r.detalhe
    assert integracoes.obter(db, Produto.MEUWATT) is None  # nada gravado


async def test_token_ruim_nao_derruba_a_conexao_que_funcionava(db, monkeypatch):
    """O ponto central de verificar antes de gravar."""
    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)

    # agora o upstream recusa o token novo
    resposta = httpx.Response(401, json={"detail": "Token revogado. Emita um novo no meuWatt."})
    _upstream(monkeypatch, erro=httpx.HTTPStatusError("401", request=None, response=resposta))
    outro = "mw_pat_" + MW[7:]  # mesmo valor: o que importa é a resposta do upstream
    r = await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", outro)

    assert not r.ok and "revogado" in r.detalhe
    linha = integracoes.obter(db, Produto.MEUWATT)
    assert cripto.decifrar(linha.token_cifrado) == MW  # o antigo continua lá
    assert linha.estado is EstadoTeste.OK


async def test_conectar_por_token_apaga_a_senha_de_servico_antiga(db, monkeypatch):
    """Guardar a senha de alguém depois que ela deixou de ser usada é guardar risco sem
    contrapartida."""
    db.add(
        Integracao(
            produto=Produto.MEUWATT,
            base_url="https://api",
            usuario_servico="servico@empresa.com.br",
            senha_cifrada=cripto.cifrar("senha-antiga"),
        )
    )
    db.commit()

    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)

    linha = integracoes.obter(db, Produto.MEUWATT)
    assert linha.usuario_servico is None and linha.senha_cifrada is None


async def test_desconectar_limpa_o_token_e_o_estado(db, monkeypatch):
    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)
    integracoes.remover_token(db, Produto.MEUWATT, ator_email="admin@gs.local")

    linha = integracoes.obter(db, Produto.MEUWATT)
    assert not linha.por_token and linha.token_prefixo is None
    assert linha.estado is EstadoTeste.NUNCA and linha.usinas_visiveis is None


# ── 3. diagnóstico: cada falha com a sua frase ───────────────────────────────


@pytest.mark.parametrize(
    "erro, esperado",
    [
        (httpx.ConnectError("recusou"), "alcançar o endereço"),
        (httpx.TimeoutException("demorou"), "não respondeu a tempo"),
        (
            httpx.HTTPStatusError("404", request=None, response=httpx.Response(404)),
            "não é a API",
        ),
        (
            httpx.HTTPStatusError("500", request=None, response=httpx.Response(500)),
            "problema do lado dele",
        ),
    ],
)
async def test_cada_falha_aponta_para_uma_correcao_diferente(db, monkeypatch, erro, esperado):
    _upstream(monkeypatch, erro=erro)
    r = await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)
    assert not r.ok and esperado in r.detalhe


async def test_a_frase_do_upstream_e_repassada_inteira(db, monkeypatch):
    """"Token expirado em 2026-03-03" vale muito mais do que "credencial recusada" — e
    quem sabe disso é o produto, não o BFF."""
    dito = "Token expirado em 2026-03-03. Emita um novo no meuWatt."
    resposta = httpx.Response(401, json={"detail": dito})
    _upstream(monkeypatch, erro=httpx.HTTPStatusError("401", request=None, response=resposta))

    r = await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)
    assert r.detalhe == dito


async def test_token_aceito_que_nao_ve_usina_nenhuma_e_falha(db, monkeypatch):
    """Sem esta checagem o aplicativo abriria vazio, sem erro nenhum — o pior modo de
    falhar, porque parece que está funcionando."""
    _upstream(monkeypatch, usinas=[])
    r = await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)

    assert not r.ok and r.usinas == 0
    assert "não enxerga nenhuma usina" in r.detalhe
    assert integracoes.obter(db, Produto.MEUWATT) is None  # não grava conexão inútil


async def test_endereco_vazio_para_antes_de_tudo(db):
    r = await integracoes.salvar_token(db, Produto.MEUWATT, "  ", MW)
    assert not r.ok and "endereço" in r.detalhe


# ── 4. histórico ─────────────────────────────────────────────────────────────


async def test_historico_registra_o_sucesso_e_a_falha(db, monkeypatch):
    """O estado diz se funciona agora; o histórico diz desde quando parou — que é o que
    separa "trocaram o token na quinta" de "o produto saiu do ar"."""
    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW, ator_email="a@gs")

    _upstream(monkeypatch, erro=httpx.ConnectError("fora"))
    await integracoes.testar(db, Produto.MEUWATT, ator_email="b@gs")

    eventos = integracoes.historico(db, Produto.MEUWATT)
    tipos = [e.evento for e in eventos]
    assert tipos == ["teste_falhou", "token_gravado"]  # mais recente primeiro
    assert eventos[0].ator_email == "b@gs" and eventos[1].ator_email == "a@gs"
    assert eventos[1].usinas_visiveis == 2


async def test_historico_de_um_produto_nao_mistura_com_o_do_outro(db, monkeypatch):
    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)
    await integracoes.salvar_token(db, Produto.MEUPLANO, "https://api", MP)

    assert len(integracoes.historico(db, Produto.MEUWATT)) == 1
    assert len(integracoes.historico(db, Produto.MEUPLANO)) == 1


# ── 5. o cliente autenticado que o resto do BFF usa ─────────────────────────


async def test_o_resto_do_bff_recebe_um_cliente_com_o_token(db, monkeypatch):
    _upstream(monkeypatch)
    await integracoes.salvar_token(db, Produto.MEUWATT, "https://api", MW)

    cliente = await integracoes.cliente_meuwatt(db)
    assert cliente._token_fixo == MW
    assert await cliente._token_servico() == MW  # sem login: o token é a credencial


async def test_conexao_antiga_por_senha_continua_funcionando(db):
    """A migração não pode derrubar quem ainda não trocou."""
    db.add(
        Integracao(
            produto=Produto.MEUPLANO,
            base_url="https://api",
            usuario_servico="servico@empresa.com.br",
            senha_cifrada=cripto.cifrar("senha-antiga"),
        )
    )
    db.commit()

    cliente = await integracoes.cliente_meuplano(db)
    assert cliente._token_fixo is None
    assert cliente._usuario == "servico@empresa.com.br"
    assert cliente._senha == "senha-antiga"
