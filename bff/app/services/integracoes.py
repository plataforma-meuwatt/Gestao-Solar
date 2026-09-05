"""Lê a configuração das pontes, sabe testá-las e guarda o que aconteceu com cada uma.

O teste é o coração do painel: sem ele o gestor cola um token e fica no escuro até alguma
tela do app falhar. Aqui ele descobre na hora — e com o motivo certo, porque "token
revogado", "token do produto errado", "endereço errado" e "servidor fora do ar" pedem
correções diferentes e, sem esse recorte, todas aparecem como um 401 mudo.

O diagnóstico tem três camadas, da mais barata para a mais cara:

1. **formato** (`core/tokens_produto`) — prefixo e dígito verificador, sem sair da máquina.
   Pega o token colado no campo errado e a cópia truncada, que são os enganos prováveis.
2. **identidade** (`quem_sou_eu`) — de quem é o token. Colar o token da pessoa errada é o
   engano silencioso: a conexão fica verde e o escopo de usinas vem menor, o que só
   aparece semanas depois como usina faltando na tela de alguém.
3. **alcance** (`usinas`) — quantas usinas aquela credencial enxerga. Uma credencial pode
   ser aceita e não ver nada, o que faria o app abrir vazio sem erro nenhum.

Gravar exige passar pelas três. É deliberado: substituir uma conexão que funciona por um
token não verificado troca um problema visível por um invisível.
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.meuplano import MeuPlanoClient
from app.clients.meuwatt import MeuWattClient
from app.core.cripto import SegredoInvalido, cifrar, decifrar
from app.core.tokens_produto import NOME, TokenInvalido, prefixo_visivel, validar
from app.models.integracao import EstadoTeste, Integracao, IntegracaoEvento, Produto


class ResultadoTeste:
    """O que o painel mostra depois de testar. `ok` decide a cor; `detalhe` explica."""

    def __init__(
        self,
        ok: bool,
        detalhe: str,
        usinas: int | None = None,
        dono_nome: str | None = None,
        dono_email: str | None = None,
    ) -> None:
        self.ok = ok
        self.detalhe = detalhe
        self.usinas = usinas
        self.dono_nome = dono_nome
        self.dono_email = dono_email


def obter(db: Session, produto: Produto) -> Integracao | None:
    return db.scalar(select(Integracao).where(Integracao.produto == produto))


def listar(db: Session) -> dict[Produto, Integracao | None]:
    """Sempre devolve as duas chaves — a tela mostra o produto não configurado também."""
    existentes = {i.produto: i for i in db.scalars(select(Integracao)).all()}
    return {p: existentes.get(p) for p in Produto}


def registrar_evento(
    db: Session,
    produto: Produto,
    evento: str,
    *,
    ator_email: str | None = None,
    token_prefixo: str | None = None,
    detalhe: str | None = None,
    usinas: int | None = None,
) -> None:
    """Uma linha no histórico da ponte. Não faz commit — acompanha quem chamou."""
    db.add(
        IntegracaoEvento(
            produto=produto,
            evento=evento,
            ator_email=ator_email,
            token_prefixo=token_prefixo,
            detalhe=detalhe,
            usinas_visiveis=usinas,
        )
    )


def historico(db: Session, produto: Produto, limite: int = 20) -> list[IntegracaoEvento]:
    return list(
        db.scalars(
            select(IntegracaoEvento)
            .where(IntegracaoEvento.produto == produto)
            .order_by(IntegracaoEvento.ocorrido_em.desc(), IntegracaoEvento.id.desc())
            .limit(limite)
        ).all()
    )


# ── clientes ────────────────────────────────────────────────────────────────


def _cliente(produto: Produto, base_url: str, token: str) -> MeuWattClient | MeuPlanoClient:
    classe = MeuWattClient if produto is Produto.MEUWATT else MeuPlanoClient
    return classe(base_url=base_url.rstrip("/"), token=token)


def _exigir_credencial(integracao, produto_nome: str) -> None:
    """Uma ponte ATIVA sem credencial nenhuma é configuração pela metade — e precisa dizer isso.

    Sem esta guarda, `decifrar(None)` estoura com `'NoneType' object has no attribute 'encode'`,
    que atravessa a ponte inteira e chega ao cliente como **"meuWatt indisponível: 'NoneType'
    object has no attribute 'encode'"** — uma frase que não diz o que houve nem o que fazer.
    Aconteceu em 04/09/2026, na tela de Energia do portal do cliente: o produto do outro lado
    estava no ar e o que faltava era a credencial gravada aqui.

    A frase certa aponta o lugar do conserto: quem lê é a equipe, e o conserto é reconectar em
    Painel → Conexões.
    """
    if not integracao.token_cifrado and not integracao.senha_cifrada:
        raise RuntimeError(
            f"A conexão com o {produto_nome} está ativa mas sem credencial gravada. "
            f"Reconecte em Painel → Conexões."
        )


async def cliente_meuwatt(db: Session) -> MeuWattClient:
    """Cliente já autenticado com o que estiver gravado — token, de preferência."""
    integracao = obter(db, Produto.MEUWATT)
    if integracao is None or not integracao.ativa:
        raise RuntimeError("A ponte com o meuWatt não está configurada.")
    _exigir_credencial(integracao, "meuWatt")
    if integracao.token_cifrado:
        return MeuWattClient(
            base_url=integracao.base_url, token=decifrar(integracao.token_cifrado)
        )
    return MeuWattClient(
        base_url=integracao.base_url,
        usuario=integracao.usuario_servico,
        senha=decifrar(integracao.senha_cifrada),
    )


#: O cliente do meuPlano, guardado enquanto a configuração não muda.
#:
#: Cada `MeuPlanoClient` novo é uma sessão nova: quando a ponte usa usuário e senha (e não
#: token fixo), a primeira chamada dele FAZ LOGIN. Criar um por requisição era invisível
#: enquanto cada tela pedia uma coisa — até a ficha passar a mostrar sessenta e uma fotos, e
#: cada miniatura virar um login. Guardado aqui, o token de serviço é reaproveitado e o
#: `_service_token` do cliente continua fazendo o seu trabalho.
#:
#: A chave inclui a configuração cifrada: mexer na credencial em "Painel → Conexões" muda a
#: chave e o cliente velho é abandonado no mesmo instante — sem invalidação manual para
#: alguém esquecer de chamar.
_clientes_meuplano: dict[tuple, MeuPlanoClient] = {}


async def cliente_meuplano(db: Session) -> MeuPlanoClient:
    integracao = obter(db, Produto.MEUPLANO)
    if integracao is None or not integracao.ativa:
        raise RuntimeError("A ponte com o meuPlano não está configurada.")
    _exigir_credencial(integracao, "meuPlano")

    chave = (integracao.base_url, integracao.token_cifrado, integracao.usuario_servico,
             integracao.senha_cifrada)
    guardado = _clientes_meuplano.get(chave)
    if guardado is not None:
        return guardado

    if integracao.token_cifrado:
        cliente = MeuPlanoClient(
            base_url=integracao.base_url, token=decifrar(integracao.token_cifrado)
        )
    else:
        cliente = MeuPlanoClient(
            base_url=integracao.base_url,
            usuario=integracao.usuario_servico,
            senha=decifrar(integracao.senha_cifrada),
        )
    # Um por configuração; trocar a credencial troca a chave. O dicionário não cresce.
    _clientes_meuplano.clear()
    _clientes_meuplano[chave] = cliente
    return cliente


# ── diagnóstico ─────────────────────────────────────────────────────────────


def detalhe_do_upstream(resposta: httpx.Response) -> str | None:
    """A frase que o produto escreveu. Vale ouro: é lá que mora "token revogado" e
    "expirado em 3 de março" — o BFF só a repassa, sem tentar reescrevê-la.

    Pública porque a sonda (`services/sonda.py`) precisa exatamente da mesma leitura: uma
    segunda cópia divergiria no dia em que um dos produtos mudasse o nome do campo.
    """
    try:
        corpo = resposta.json()
    except Exception:
        return None
    if isinstance(corpo, dict):
        valor = corpo.get("detail") or corpo.get("message") or corpo.get("erro")
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def _traduzir(exc: Exception, produto: Produto) -> ResultadoTeste:
    """Transforma a falha em uma frase acionável. Cada ramo aponta para uma correção
    diferente, que é a razão de existirem separados."""
    nome = NOME[produto]

    if isinstance(exc, httpx.ConnectError):
        return ResultadoTeste(
            False,
            f"Não foi possível alcançar o endereço do {nome}. Confira a URL — costuma "
            "ser http em vez de https, uma barra a mais ou o domínio errado.",
        )
    if isinstance(exc, httpx.TimeoutException):
        return ResultadoTeste(False, f"O {nome} não respondeu a tempo. Tente de novo em instantes.")
    if isinstance(exc, httpx.HTTPStatusError):
        codigo = exc.response.status_code
        dito = detalhe_do_upstream(exc.response)
        if codigo in (401, 403):
            # O produto já explica em português (revogado, expirado, conta desativada).
            return ResultadoTeste(False, dito or f"O {nome} recusou este token.")
        if codigo == 404:
            return ResultadoTeste(
                False,
                f"O endereço respondeu, mas não é a API do {nome} (404 na rota de "
                "identificação). Confira a URL.",
            )
        if codigo >= 500:
            return ResultadoTeste(
                False, f"O {nome} respondeu {codigo} — problema do lado dele, não do token."
            )
        return ResultadoTeste(False, dito or f"O {nome} respondeu {codigo}.")

    return ResultadoTeste(False, f"{type(exc).__name__}: {exc}")


def _nome_e_email(perfil: dict) -> tuple[str | None, str | None]:
    """Os dois produtos respondem `/me` com formatos parecidos, mas não iguais."""
    if not isinstance(perfil, dict):
        return None, None
    nome = perfil.get("name") or perfil.get("nome")
    email = perfil.get("email")
    return (nome or None), (email or None)


async def _exercitar(produto: Produto, base_url: str, token: str) -> ResultadoTeste:
    """Usa o token de verdade: identifica o dono e conta o que ele enxerga."""
    cliente = _cliente(produto, base_url, token)
    try:
        perfil = await cliente.quem_sou_eu()
        usinas = await cliente.usinas()
    except Exception as exc:  # noqa: BLE001 — o painel precisa mostrar qualquer falha
        return _traduzir(exc, produto)

    dono_nome, dono_email = _nome_e_email(perfil)
    quantidade = len(usinas or [])
    quem = dono_nome or dono_email or "conta sem nome"

    if quantidade == 0:
        return ResultadoTeste(
            False,
            f"Token aceito ({quem}), mas esta conta não enxerga nenhuma usina no "
            f"{NOME[produto]}. Dê acesso a ela lá — do jeito que está, o aplicativo "
            "abriria vazio sem apresentar erro.",
            usinas=0,
            dono_nome=dono_nome,
            dono_email=dono_email,
        )

    return ResultadoTeste(
        True,
        f"Conectado como {quem}. {quantidade} usina(s) visíveis.",
        usinas=quantidade,
        dono_nome=dono_nome,
        dono_email=dono_email,
    )


# ── endereço ────────────────────────────────────────────────────────────────


class EnderecoInvalido(ValueError):
    """A mensagem é para quem digitou o endereço."""


def normalizar_endereco(base_url: str) -> str:
    """Devolve o endereço pronto para uso, ou levanta `EnderecoInvalido`.

    Completa o `https://` quando falta. Copiar um domínio de onde ele aparece sem
    esquema — a barra do navegador, o painel do Railway, um e-mail — é o caminho normal,
    e recusar `meuplano.up.railway.app` por causa disso seria implicância: não há
    ambiguidade nenhuma sobre o que a pessoa quis dizer.

    Sem esta função o valor chegava cru ao httpx, que respondia
    `UnsupportedProtocol: Request URL is missing an 'http://' or 'https://' protocol` —
    uma frase de biblioteca, em inglês, vazando para a tela do gestor. O erro era dele,
    a mensagem tinha de ser para ele.
    """
    endereco = (base_url or "").strip().rstrip("/")
    if not endereco:
        raise EnderecoInvalido("Informe o endereço da API antes de conectar.")

    if "://" not in endereco:
        endereco = f"https://{endereco}"
    elif not endereco.startswith(("http://", "https://")):
        esquema = endereco.split("://", 1)[0]
        raise EnderecoInvalido(
            f"O endereço começa com '{esquema}://', que não é um endereço de API. "
            "Use https:// (ou http:// para um servidor local)."
        )

    host = endereco.split("://", 1)[1]
    if not host or "/" in host.split("?")[0][:1] or " " in host:
        raise EnderecoInvalido("O endereço não parece um domínio válido.")
    return endereco


# ── gravação ────────────────────────────────────────────────────────────────


async def salvar_token(
    db: Session,
    produto: Produto,
    base_url: str,
    token: str,
    ator_email: str | None = None,
) -> ResultadoTeste:
    """Verifica o token contra o produto e só então grava.

    Verificar antes de gravar é o ponto: se o token não serve, a conexão anterior — que
    podia estar funcionando — continua de pé. Gravar primeiro e testar depois deixaria o
    gestor com as duas coisas quebradas e nenhuma forma de voltar.
    """
    try:
        endereco = normalizar_endereco(base_url)
    except EnderecoInvalido as exc:
        # Para antes da rede e antes do banco: a conexão anterior não é tocada.
        return ResultadoTeste(False, str(exc))

    try:
        limpo = validar(produto, token)
    except TokenInvalido as exc:
        # Nem chega à rede: o formato já respondeu.
        registrar_evento(
            db, produto, "teste_falhou", ator_email=ator_email, detalhe=str(exc)
        )
        db.commit()
        return ResultadoTeste(False, str(exc))

    resultado = await _exercitar(produto, endereco, limpo)
    prefixo = prefixo_visivel(limpo)

    if not resultado.ok:
        registrar_evento(
            db,
            produto,
            "teste_falhou",
            ator_email=ator_email,
            token_prefixo=prefixo,
            detalhe=resultado.detalhe,
            usinas=resultado.usinas,
        )
        db.commit()
        return resultado

    integracao = obter(db, produto)
    if integracao is None:
        integracao = Integracao(produto=produto, base_url=endereco)
        db.add(integracao)

    anterior = integracao.token_prefixo
    integracao.base_url = endereco
    integracao.token_cifrado = cifrar(limpo)
    integracao.token_prefixo = prefixo
    integracao.token_dono_nome = resultado.dono_nome
    integracao.token_dono_email = resultado.dono_email
    integracao.token_gravado_em = datetime.now(UTC)
    integracao.ativa = True
    # A conta de serviço antiga sai de cena junto: manter a senha cifrada de alguém no
    # banco depois que ela deixou de ser usada é guardar risco sem contrapartida.
    integracao.usuario_servico = None
    integracao.senha_cifrada = None

    _gravar_resultado(db, integracao, resultado)
    registrar_evento(
        db,
        produto,
        "token_gravado",
        ator_email=ator_email,
        token_prefixo=prefixo,
        detalhe=(
            f"token de {resultado.dono_nome or resultado.dono_email or 'conta sem nome'}"
            + (f" (substituiu {anterior})" if anterior and anterior != prefixo else "")
        ),
        usinas=resultado.usinas,
    )
    db.commit()
    return resultado


def remover_token(db: Session, produto: Produto, ator_email: str | None = None) -> None:
    """Desconecta deste lado. Não revoga nada no produto de origem — quem emitiu o token
    continua com ele válido lá, e é lá que ele deve ser revogado de verdade. A tela diz
    isso, porque a diferença importa: remover aqui não fecha a porta, só para de usá-la.
    """
    integracao = obter(db, produto)
    if integracao is None:
        return
    prefixo = integracao.token_prefixo
    integracao.token_cifrado = None
    integracao.token_prefixo = None
    integracao.token_dono_nome = None
    integracao.token_dono_email = None
    integracao.token_gravado_em = None
    integracao.estado = EstadoTeste.NUNCA
    integracao.testada_em = None
    integracao.detalhe_teste = None
    integracao.usinas_visiveis = None
    registrar_evento(db, produto, "token_removido", ator_email=ator_email, token_prefixo=prefixo)
    db.commit()


def salvar(
    db: Session,
    produto: Produto,
    base_url: str,
    usuario: str,
    senha: str | None,
    ator_email: str | None = None,
) -> Integracao:
    """Caminho ANTIGO, por conta de serviço. Mantido para as conexões gravadas antes do
    token e para o teste que ainda as exercita; a tela não oferece mais criar assim.

    `senha=None` preserva a que já está gravada — é o que permite corrigir só o endereço
    sem redigitar a credencial.
    """
    integracao = obter(db, produto)

    if integracao is None:
        if not senha:
            raise ValueError("A senha é obrigatória ao configurar a integração pela primeira vez.")
        integracao = Integracao(produto=produto, base_url="", usuario_servico="", senha_cifrada="")
        db.add(integracao)

    # `EnderecoInvalido` é um `ValueError` — o router já o transforma em 400 com a frase.
    integracao.base_url = normalizar_endereco(base_url)
    integracao.usuario_servico = usuario
    if senha:
        integracao.senha_cifrada = cifrar(senha)

    # Qualquer alteração invalida o teste anterior: a credencial pode ter mudado.
    integracao.estado = EstadoTeste.NUNCA
    integracao.testada_em = None
    integracao.detalhe_teste = None
    integracao.usinas_visiveis = None

    registrar_evento(db, produto, "senha_gravada", ator_email=ator_email, detalhe=usuario)
    db.commit()
    db.refresh(integracao)
    return integracao


# ── teste ───────────────────────────────────────────────────────────────────


async def testar(db: Session, produto: Produto, ator_email: str | None = None) -> ResultadoTeste:
    """Exercita a credencial gravada contra o produto e registra o que aconteceu."""
    integracao = obter(db, produto)
    if integracao is None:
        return ResultadoTeste(False, "Integração ainda não configurada.")

    if integracao.token_cifrado:
        try:
            token = decifrar(integracao.token_cifrado)
        except SegredoInvalido as exc:
            return _registrar(db, integracao, ResultadoTeste(False, str(exc)), ator_email)
        resultado = await _exercitar(produto, integracao.base_url, token)
        # O dono pode ter mudado de nome no produto; a tela mostra o valor atual.
        if resultado.ok:
            integracao.token_dono_nome = resultado.dono_nome or integracao.token_dono_nome
            integracao.token_dono_email = resultado.dono_email or integracao.token_dono_email
        return _registrar(db, integracao, resultado, ator_email)

    return _registrar(db, integracao, await _testar_por_senha(integracao, produto), ator_email)


async def _testar_por_senha(integracao: Integracao, produto: Produto) -> ResultadoTeste:
    """O caminho antigo, preservado para as conexões que ainda não migraram."""
    if not integracao.senha_cifrada:
        return ResultadoTeste(
            False, "Esta conexão não tem credencial gravada. Cole um token para conectar."
        )
    try:
        senha = decifrar(integracao.senha_cifrada)
    except SegredoInvalido as exc:
        return ResultadoTeste(False, str(exc))

    classe = MeuWattClient if produto is Produto.MEUWATT else MeuPlanoClient
    cliente = classe(base_url=integracao.base_url)
    try:
        dados = await cliente.autenticar(integracao.usuario_servico, senha)
        if not dados:
            return ResultadoTeste(False, f"Credencial recusada pelo {NOME[produto]}.")
        usinas = await cliente.usinas(token=dados["access_token"])
    except Exception as exc:  # noqa: BLE001 — o painel precisa mostrar qualquer falha
        return _traduzir(exc, produto)

    quantidade = len(usinas or [])
    if quantidade == 0:
        return ResultadoTeste(
            False,
            "Credencial aceita, mas esta conta não enxerga nenhuma usina. "
            "Dê acesso a ela no produto de origem.",
            usinas=0,
        )
    return ResultadoTeste(True, f"Conectado. {quantidade} usina(s) visíveis.", usinas=quantidade)


def _gravar_resultado(db: Session, integracao: Integracao, resultado: ResultadoTeste) -> None:
    integracao.estado = EstadoTeste.OK if resultado.ok else EstadoTeste.FALHOU
    integracao.testada_em = datetime.now(UTC)
    integracao.detalhe_teste = resultado.detalhe
    integracao.usinas_visiveis = resultado.usinas


def _registrar(
    db: Session,
    integracao: Integracao,
    resultado: ResultadoTeste,
    ator_email: str | None = None,
) -> ResultadoTeste:
    _gravar_resultado(db, integracao, resultado)
    registrar_evento(
        db,
        integracao.produto,
        "teste_ok" if resultado.ok else "teste_falhou",
        ator_email=ator_email,
        token_prefixo=integracao.token_prefixo,
        detalhe=resultado.detalhe,
        usinas=resultado.usinas,
    )
    db.commit()
    return resultado
