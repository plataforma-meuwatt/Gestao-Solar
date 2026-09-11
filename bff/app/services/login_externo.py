"""Fazer os produtos aceitarem "Entrar com Gestão Solar".

## As duas metades do mesmo gesto

Quando o cliente cola o token dele no Gestão Solar, duas coisas passam a ser verdade e
convém não confundi-las:

1. **O GS lê os produtos como ele.** Basta o token. É `services/vinculos.py`.
2. **Ele entra nos produtos com a senha do GS.** Para isso o produto precisa gravar, do
   lado dele, que a conta N do Gestão Solar é aquele usuário — e é o que este módulo pede.

A segunda depende da primeira e não o contrário: sem o token não há o que provar.

## Por que o produto acredita

Duas provas apresentadas juntas, e cada uma cobre o buraco da outra:

* **o token do próprio usuário**, no cabeçalho `Authorization`. Prova que quem pede é dono
  daquela conta no produto — ninguém vincula a conta de outra pessoa sem ter o token dela.
* **uma asserção assinada em RS256** pela chave privada desta instalação. Prova que a
  conta do Gestão Solar citada existe mesmo e é a que diz ser. Sem ela, quem roubasse um
  token poderia apontá-lo para uma conta do GS inventada e passar a entrar no produto como
  a vítima — trocando um acesso revogável e limitado por um login inteiro.

O produto exige as duas. Uma sozinha não vincula.

## O que a asserção carrega

    iss  'gestao-solar'     quem assinou
    aud  'meuwatt'          para quem — a do meuPlano não vale no meuWatt
    sub  '<gs_users.id>'    a identidade, que é o id da conta AQUI
    jti  uuid               uso único, contra repetição
    exp  ~2 min             janela curta: ela viaja para ser usada na hora
    email, name             o que o cadastro daqui afirma

`sub` é o id, nunca o e-mail. No Gestão Solar quem autentica é o apelido; o e-mail é
contato opcional e pode se repetir entre duas contas da mesma pessoa (ela pode ser gestora
e, separadamente, dona de uma usina). Casar por e-mail deixaria qualquer um entrar como
você, bastando criar uma conta aqui com o seu endereço.

## Falhar sem quebrar

Nada aqui levanta exceção para quem chama. Uma chave não configurada, um produto fora do
ar ou uma versão antiga da API do outro lado não podem invalidar uma conexão que já foi
provada boa — o token continua servindo para ler. O que não pode é a falha passar calada:
toda saída é uma frase para a tela, e o vínculo só marca `login_externo_em` quando o
produto confirmou.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from jose import jwt
from sqlalchemy.orm import Session

from app.clients.http import sessao
from app.core.config import get_settings
from app.core.tokens_produto import NOME
from app.models.integracao import Produto
from app.models.user import User
from app.services import integracoes

logger = logging.getLogger(__name__)

#: Quem é o destinatário de cada asserção. Uma assinada para o meuWatt é recusada pelo
#: meuPlano, e vice-versa: sem isso, um produto comprometido poderia reapresentar a
#: asserção que recebeu no outro e entrar lá como a pessoa.
AUDIENCIA: dict[Produto, str] = {
    Produto.MEUWATT: "meuwatt",
    Produto.MEUPLANO: "meuplano",
}

#: Onde cada produto recebe o pedido de vínculo.
ROTA_VINCULO: dict[Produto, str] = {
    Produto.MEUWATT: "/auth/external/link",
    Produto.MEUPLANO: "/api/v1/meuacesso/auth/external/link",
}

#: A asserção viaja para ser usada no mesmo instante. Dois minutos cobrem relógios
#: levemente fora de sincronia sem deixar um valor interceptado útil por muito tempo.
VALIDADE = timedelta(minutes=2)


class SemChave(RuntimeError):
    """A instalação não tem chave de assinatura. É configuração ausente, não erro."""


def assinar(usuario: User, produto: Produto) -> str:
    """A asserção que prova, para aquele produto, quem é esta conta do Gestão Solar."""
    s = get_settings()
    if not s.gs_sso_private_key:
        raise SemChave(
            "GS_SSO_PRIVATE_KEY não configurada — o Gestão Solar não consegue assinar a "
            "identidade desta conta. Gere um par de chaves e informe a privada aqui e a "
            "pública no produto."
        )

    agora = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": s.gs_sso_issuer,
            "aud": AUDIENCIA[produto],
            "sub": str(usuario.id),
            "jti": str(uuid.uuid4()),
            "iat": int(agora.timestamp()),
            "exp": int((agora + VALIDADE).timestamp()),
            "email": usuario.email,
            "name": usuario.nome,
        },
        s.gs_sso_private_key,
        algorithm="RS256",
    )


async def habilitar(
    db: Session,
    *,
    cliente: User,
    produto: Produto,
    base_url: str,
    token: str,
) -> str | None:
    """Pede ao produto que passe a aceitar o login desta conta.

    Devolve `None` quando deu certo, ou a frase que a tela deve mostrar quando não deu.
    Nunca levanta: ver "Falhar sem quebrar", no topo.
    """
    from app.services import vinculos  # noqa: PLC0415 — circular no topo

    nome = NOME[produto]

    try:
        assercao = assinar(cliente, produto)
    except SemChave as exc:
        logger.warning("login externo indisponível (%s): %s", produto.value, exc)
        return (
            f"A conta lê o {nome} normalmente, mas o login via Gestão Solar não foi "
            f"habilitado: esta instalação não tem chave de assinatura configurada "
            f"(GS_SSO_PRIVATE_KEY)."
        )

    url = f"{base_url.rstrip('/')}{ROTA_VINCULO[produto]}"
    try:
        c = sessao(base_url.rstrip("/"))
        r = await c.post(
            url,
            # O token do usuário é a outra metade da prova: o produto confere que quem
            # pede é dono da conta antes de aceitar a identidade que a asserção afirma.
            headers={"Authorization": f"Bearer {token}"},
            json={"assertion": assercao},
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        codigo = exc.response.status_code
        dito = integracoes.detalhe_do_upstream(exc.response)
        if codigo == 404:
            # A rota não existe ainda naquele produto. É o estado normal enquanto o
            # deploy do outro lado não saiu, e merece uma frase que diga isso em vez de
            # "404".
            return (
                f"A conta lê o {nome} normalmente, mas esta versão do {nome} ainda não "
                f"sabe receber login do Gestão Solar."
            )
        return f"O {nome} recusou habilitar o login: {dito or f'respondeu {codigo}'}."
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira frase, nenhuma explode
        falha = integracoes.traduzir_falha(exc, produto)
        return f"A conta lê o {nome} normalmente, mas o login não foi habilitado: {falha.detalhe}"

    vinculo = vinculos.obter(db, cliente.id, produto)
    if vinculo is not None:
        vinculo.login_externo_em = datetime.now(UTC)
        db.commit()
    return None
