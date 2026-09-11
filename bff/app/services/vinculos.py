"""A conta de cada cliente nos produtos, conectada pelo token dele.

## O que mudou, e por quê

Antes o vínculo era uma **afirmação do gestor**: ele buscava um e-mail no produto, achava
uma conta, e o BFF gravava "o cliente 7 daqui é o usuário 45 de lá". A partir disso o
Gestão Solar lia tudo com UMA credencial de serviço e, para saber o que cada cliente
enxerga, perguntava aos produtos por rotas administrativas: *"quais usinas o usuário 45
tem?"*.

Essa pergunta é indireta, e a indireção errou em produção. O Janderson enxerga a UFV
Porto Ferreira no meuPlano porque pertence à Eninsa, e não porque alguém lhe concedeu a
usina uma a uma; a rota administrativa só conhece concessões explícitas, devolveu lista
vazia, e o painel concluiu "nenhuma plataforma indicou usinas para este cliente" sobre
alguém que vê sete. O dado estava certo dos dois lados — errada era a pergunta.

Agora o vínculo é **estabelecido pelo próprio token do cliente**. Ele cola o token que
gerou no produto, o BFF apresenta esse token e pergunta "de quem é você?", e o produto
responde. Daí saem duas coisas de uma vez:

* o `usuario_remoto_id` deixa de ser palpite e passa a ser resposta;
* a leitura deixa de ser por procuração: o BFF chama os produtos **como o cliente**, e
  recebe exatamente o escopo que ele veria lá, pela mesma regra que o produto usa no seu
  próprio site. Não há mais tradução para errar.

## O que continua sendo de serviço

UMA coisa só: o **catálogo de usinas** (`painel.carregar_conciliacao`). Ela lista tudo o
que existe nos dois produtos — inclusive usina que nenhum cliente tem ainda, que é
justamente o ponto de partida para conceder. Nenhum token de cliente enxerga isso, por
definição, então a credencial administrativa continua em `gs_integracoes`, junto do
endereço de cada produto.

Tudo o mais migrou. Inclusive o que não era óbvio:

* **as 41 leituras do aplicativo** — energia, equipamentos, paradas, manutenção,
  relatórios, documentos, carteira, notificações, pendências, pacotes, exportação. A
  autorização sempre foi local (a concessão de usina vive aqui); o que mudou é que a
  LEITURA deixou de ser por procuração;
* **o diagnóstico do cliente**, que lia com a credencial da equipe e por isso respondia
  "o que EU vejo" a uma pergunta que é "o que ELE vê" — dois resultados que só divergem
  quando há problema, ou seja, exatamente quando a tela é aberta;
* **os avisos de parada**, que continuam lendo cada usina uma única vez, mas agora pelo
  token de alguém que tem acesso a ela (ver `services/avisos.py`).

## Ordem das operações

Verificar antes de gravar, como em `integracoes.salvar_token` e pelo mesmo motivo: se o
token não serve, o vínculo anterior — que podia estar funcionando — continua de pé.
Gravar primeiro e testar depois deixaria o gestor com as duas coisas quebradas.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.meuplano import MeuPlanoClient
from app.clients.meuwatt import MeuWattClient
from app.core.cripto import SegredoInvalido, cifrar, decifrar
from app.core.tokens_produto import NOME, TokenInvalido, prefixo_visivel, validar
from app.models.integracao import Produto
from app.models.user import User, VinculoProduto
from app.services import integracoes


@dataclass
class ResultadoConexao:
    """O que a tela mostra depois de tentar conectar. `ok` decide a cor; `detalhe` explica."""

    ok: bool
    detalhe: str
    usuario_remoto_id: str | None = None
    nome: str | None = None
    email: str | None = None
    usinas_visiveis: int | None = None
    #: O produto passou a aceitar "Entrar com Gestão Solar" para esta conta. Separado de
    #: `ok` de propósito: a conexão pode servir para ler e o login não ter sido habilitado
    #: (produto fora do ar, chave de assinatura ausente), e quem lê a tela precisa
    #: distinguir as duas coisas para saber o que consertar.
    login_externo: bool = False
    aviso_login: str | None = None


def obter(db: Session, cliente_id: int, produto: Produto) -> VinculoProduto | None:
    return db.scalar(
        select(VinculoProduto).where(
            VinculoProduto.gs_user_id == cliente_id,
            VinculoProduto.produto == produto.value,
        )
    )


def listar(db: Session, cliente_id: int) -> dict[Produto, VinculoProduto | None]:
    """Sempre as duas chaves — a ficha do cliente mostra o produto não conectado também,
    que é justamente o que o gestor precisa ver para agir."""
    existentes = {
        Produto(v.produto): v
        for v in db.scalars(
            select(VinculoProduto).where(VinculoProduto.gs_user_id == cliente_id)
        ).all()
        if v.produto in (p.value for p in Produto)
    }
    return {p: existentes.get(p) for p in Produto}


# ── ler como o cliente ──────────────────────────────────────────────────────


class SemConexao(HTTPException):
    """O cliente não tem token para este produto.

    `HTTPException` e não um erro qualquer porque este é o estado normal de um cliente
    recém-cadastrado, e ele atravessa TODAS as telas do aplicativo — que agora leem com o
    token da pessoa. Como `RuntimeError` ele chegaria ao app como 500, indistinguível de
    defeito, e a equipe iria procurar bug onde só falta um passo do cadastro.

    **424 Failed Dependency**, que é literalmente o caso: o pedido está correto e o que
    falta é uma dependência dele. Não é 401 (quem pede está autenticado aqui), não é 403
    (não é falta de permissão) e não é 404 (o recurso existe, só não há como alcançá-lo).

    `__str__` devolve a mensagem crua: o `HTTPException` do FastAPI imprime
    `"424: ..."`, e quem já fazia `str(exc)` para montar a frase da tela passaria a
    mostrar o número do status no meio do texto.
    """

    def __init__(self, mensagem: str) -> None:
        super().__init__(status_code=424, detail=mensagem)

    def __str__(self) -> str:
        return str(self.detail)


def token_do_cliente(db: Session, cliente_id: int, produto: Produto) -> str:
    vinculo = obter(db, cliente_id, produto)
    if vinculo is None or not vinculo.token_cifrado:
        raise SemConexao(
            f"Este cliente ainda não conectou a conta do {NOME[produto]}. "
            f"Abra a ficha dele e cole o token."
        )
    try:
        return decifrar(vinculo.token_cifrado)
    except SegredoInvalido as exc:
        raise SemConexao(
            f"O token do {NOME[produto]} deste cliente não abre com a chave atual. "
            f"Cole o token de novo na ficha dele."
        ) from exc


def _endereco(db: Session, produto: Produto) -> str:
    """O endereço do produto continua sendo do sistema, não do cliente: é a mesma API para
    todo mundo, e guardá-la por pessoa seria copiar o mesmo valor N vezes para que N-1
    delas pudessem ficar desatualizadas."""
    integracao = integracoes.obter(db, produto)
    if integracao is None or not integracao.base_url:
        raise SemConexao(
            f"O endereço da API do {NOME[produto]} não está configurado. "
            f"Ajuste em Painel → Conexões."
        )
    return integracao.base_url


def cliente_meuwatt(db: Session, cliente_id: int) -> MeuWattClient:
    """Um cliente da mw-api que fala **como** este cliente."""
    return MeuWattClient(
        base_url=_endereco(db, Produto.MEUWATT),
        token=token_do_cliente(db, cliente_id, Produto.MEUWATT),
    )


def cliente_meuplano(db: Session, cliente_id: int) -> MeuPlanoClient:
    """O gêmeo do meuPlano. Sem cache por configuração como em `integracoes`: ali o cliente
    de serviço é um só e valia guardar; aqui é um por pessoa, e o token fixo não faz login
    nenhum — não há sessão a reaproveitar."""
    return MeuPlanoClient(
        base_url=_endereco(db, Produto.MEUPLANO),
        token=token_do_cliente(db, cliente_id, Produto.MEUPLANO),
    )


# ── conectar ────────────────────────────────────────────────────────────────


async def _exercitar(produto: Produto, base_url: str, token: str) -> ResultadoConexao:
    """Usa o token de verdade: descobre de quem é e quanto ele alcança.

    As duas perguntas são necessárias e respondem coisas diferentes. A identidade impede o
    engano silencioso de colar o token de outra pessoa — a conexão ficaria verde e o
    escopo viria errado, o que só apareceria semanas depois como usina faltando. O alcance
    impede o oposto: uma credencial aceita que não enxerga nada abriria o aplicativo vazio,
    sem erro nenhum na tela.
    """
    classe = MeuWattClient if produto is Produto.MEUWATT else MeuPlanoClient
    upstream = classe(base_url=base_url, token=token)

    try:
        quem = await upstream.identidade()
        usinas = await upstream.usinas()
    except Exception as exc:  # noqa: BLE001 — a tela precisa mostrar qualquer falha
        falha = integracoes.traduzir_falha(exc, produto)
        return ResultadoConexao(ok=False, detalhe=falha.detalhe)

    remoto_id = (quem.get("id") or "").strip()
    nome, email = quem.get("nome"), quem.get("email")
    quantidade = len(usinas or [])
    apelido = nome or email or "conta sem nome"

    if not remoto_id:
        # Sem id não há vínculo: é ele que fica gravado e é por ele que o produto
        # reconhece a pessoa depois. Gravar sem id daria uma linha que não serve para nada.
        return ResultadoConexao(
            ok=False,
            detalhe=(
                f"O {NOME[produto]} aceitou o token mas não disse a qual conta ele "
                "pertence. Sem isso não dá para vincular — pode ser uma versão antiga da "
                "API do outro lado."
            ),
        )

    if quantidade == 0:
        return ResultadoConexao(
            ok=False,
            detalhe=(
                f"Token aceito ({apelido}), mas esta conta não enxerga nenhuma usina no "
                f"{NOME[produto]}. Dê acesso a ela lá — do jeito que está, o aplicativo "
                "abriria vazio sem apresentar erro."
            ),
            usuario_remoto_id=remoto_id,
            nome=nome,
            email=email,
            usinas_visiveis=0,
        )

    return ResultadoConexao(
        ok=True,
        detalhe=f"Conectado como {apelido}. {quantidade} usina(s) visíveis.",
        usuario_remoto_id=remoto_id,
        nome=nome,
        email=email,
        usinas_visiveis=quantidade,
    )


async def conectar(
    db: Session,
    cliente: User,
    produto: Produto,
    token: str,
    *,
    por: User,
) -> ResultadoConexao:
    """Confere o token contra o produto e, só então, grava o vínculo.

    Depois de gravar, tenta habilitar o login via Gestão Solar no produto. Essa segunda
    parte é BEST-EFFORT de propósito: ela depende de a chave de assinatura estar
    configurada e de o produto estar no ar, e nenhuma das duas coisas justifica recusar
    uma conexão que já foi provada boa. O que não pode acontecer é a falha passar calada —
    daí `aviso_login`, que a tela mostra ao lado do vínculo.
    """
    try:
        limpo = validar(produto, token)
    except TokenInvalido as exc:
        # Nem chega à rede: o formato já respondeu, e com a frase certa.
        return ResultadoConexao(ok=False, detalhe=str(exc))

    try:
        endereco = _endereco(db, produto)
    except SemConexao as exc:
        return ResultadoConexao(ok=False, detalhe=str(exc))

    resultado = await _exercitar(produto, endereco, limpo)
    if not resultado.ok:
        return resultado

    vinculo = obter(db, cliente.id, produto)
    if vinculo is None:
        vinculo = VinculoProduto(gs_user_id=cliente.id, produto=produto.value)
        db.add(vinculo)

    vinculo.usuario_remoto_id = resultado.usuario_remoto_id or ""
    vinculo.usuario_remoto_nome = resultado.nome
    vinculo.usuario_remoto_email = resultado.email
    vinculo.token_cifrado = cifrar(limpo)
    vinculo.token_prefixo = prefixo_visivel(limpo)
    vinculo.token_gravado_em = datetime.now(UTC)
    vinculo.estado = "ok"
    vinculo.detalhe = resultado.detalhe
    vinculo.usinas_visiveis = resultado.usinas_visiveis
    vinculo.vinculado_por = por.id
    vinculo.vinculado_em = datetime.now(UTC)
    db.commit()
    db.refresh(vinculo)

    from app.services import login_externo  # noqa: PLC0415 — circular no topo

    aviso = await login_externo.habilitar(
        db, cliente=cliente, produto=produto, base_url=endereco, token=limpo
    )
    db.refresh(vinculo)
    resultado.login_externo = vinculo.login_externo
    resultado.aviso_login = aviso
    return resultado


async def testar(db: Session, cliente: User, produto: Produto) -> ResultadoConexao:
    """Reexercita o token já gravado e atualiza o estado.

    Existe porque um token que funcionava pode parar sozinho — revogado do outro lado,
    conta desativada, usina tirada da pessoa. Sem este botão, a equipe só descobre pelo
    cliente reclamando que o aplicativo abriu vazio.
    """
    vinculo = obter(db, cliente.id, produto)
    if vinculo is None or not vinculo.token_cifrado:
        return ResultadoConexao(
            ok=False, detalhe=f"Este cliente não tem conta conectada no {NOME[produto]}."
        )

    try:
        token = decifrar(vinculo.token_cifrado)
        endereco = _endereco(db, produto)
    except (SegredoInvalido, SemConexao) as exc:
        return ResultadoConexao(ok=False, detalhe=str(exc))

    resultado = await _exercitar(produto, endereco, token)
    vinculo.estado = "ok" if resultado.ok else "falhou"
    vinculo.detalhe = resultado.detalhe
    vinculo.usinas_visiveis = resultado.usinas_visiveis
    # A identidade é reconfirmada a cada teste: se o token foi regerado por outra pessoa
    # com o mesmo prefixo — ou se a conta foi renomeada lá —, a tela passa a dizer a
    # verdade em vez de repetir o que era verdade no dia em que foi colado.
    if resultado.usuario_remoto_id:
        vinculo.usuario_remoto_id = resultado.usuario_remoto_id
        vinculo.usuario_remoto_nome = resultado.nome
        vinculo.usuario_remoto_email = resultado.email
    db.commit()

    # Testar TAMBÉM retenta habilitar o login, quando ele ainda não está de pé.
    #
    # Sem isto, a conexão feita antes de a chave de assinatura existir ficava com o login
    # desabilitado PARA SEMPRE: `conectar` é o único lugar que tentava, e ninguém recola
    # um token que está funcionando. A pessoa configurava a chave depois — que é a ordem
    # normal das coisas — e nada acontecia, sem nenhum caminho na tela para consertar
    # além de desconectar e conectar de novo.
    #
    # Só quando falta, e só quando o token acabou de ser aprovado: retentar um login que
    # já está de pé é uma chamada inútil por clique.
    if resultado.ok and not vinculo.login_externo:
        from app.services import login_externo  # noqa: PLC0415 — circular no topo

        resultado.aviso_login = await login_externo.habilitar(
            db, cliente=cliente, produto=produto, base_url=endereco, token=token
        )
        db.refresh(vinculo)

    resultado.login_externo = vinculo.login_externo
    return resultado


def desconectar(db: Session, cliente: User, produto: Produto) -> None:
    """Apaga o vínculo inteiro — token junto.

    Não guarda o token "para o caso de reconectar": ele continua valendo do lado do
    produto até ser revogado lá, e um segredo guardado sem uso é risco sem contrapartida.
    Reconectar é colar de novo.
    """
    vinculo = obter(db, cliente.id, produto)
    if vinculo is not None:
        db.delete(vinculo)
        db.commit()
