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


def _privada() -> str:
    """A chave em PEM de verdade, com quebras de linha.

    A chave viaja por variável de ambiente, onde quebra de linha é um transtorno: o
    Railway e o Render guardam texto multilinha com `\\n` literal, que é como ela sai da
    ferramenta de geração e como ela é colada no painel. Em PEM cru isso é lixo — a
    biblioteca recusa com `InvalidByte(0, 92)`, o código do caractere `\\`, uma frase que
    não diz a ninguém que o problema é o formato da variável.

    Os dois produtos já faziam esta normalização ao LER a chave pública
    (`mw-api/src/auth/external.py`, `meuPlano/.../external_identity.py`). O lado que
    ASSINA não fazia, e a assimetria só apareceria na primeira tentativa real de login —
    com a chave certa configurada e um erro falando de bytes.
    """
    return (get_settings().gs_sso_private_key or "").replace("\\n", "\n")


#: O meuGuarda (CFTV das usinas) e o TermoVision (inspeção térmica) só RECEBEM o login: não são um `Produto` (não têm
#: token nem conexão aqui), então a audiência deles mora fora de `AUDIENCIA`. Eles casam a pessoa pelo APELIDO e
#: decidem o que ela pode lá; por isso a asserção leva também o perfil, o portão, a empresa e se o gerente liberou o
#: acesso (spec do meuGuarda em `/root/DEVV/CFTV/docs/bot-gs.md`, "Pedido 2"; o TermoVision, pedido do dono 11/11/2026,
#: "igual meuguarda"). O do TermoVision leva também o id da pessoa no meuPlano: é como ele reconhecia quem já entrava.
MEUGUARDA = "meuguarda"
TERMOVISION = "termovision"
SO_LOGIN = (MEUGUARDA, TERMOVISION)

#: Os quatro sistemas que entram pelo GS ("Plano Casa GS", 24/11/2026: o GS é o pai): o nome que a tela mostra (o
#: DESTINO do botão, onde a pessoa vai cair, com a marca dele) e os endereços aceitos como `volta`. Lista FIXA: um
#: `volta` livre seria redirecionamento aberto, e o passe (dois minutos, uso único) iria parar no site de quem montou o
#: link. Nada de endereço morto: `meuplano.meuwatt.com.br` saiu (morreu com o Railway; quem o registrasse receberia os
#: passes do meuPlano).
SISTEMAS: dict[str, tuple[str, frozenset[str]]] = {
    "meuwatt": ("meuWatt", frozenset({"app.meuwatt.com.br"})),
    "meuplano": ("meuPlano", frozenset({"app.meuplano.solar"})),
    "meuguarda": ("meuGuarda", frozenset({"meuguarda.gestao.solar", "meuguarda.177.153.20.214.sslip.io"})),
    # O meuGuarda também recebe a do TermoVision (12/11/2026, pedido do meuGuarda pela queixa do dono: "já estamos no
    # Gestão Solar justamente para centralizar e tu me pede senha"): o botão "Importar do TermoVision" do mapa leva a
    # pessoa por aqui, e o servidor do meuGuarda usa a asserção UMA vez para copiar o orto e sai. É a exceção consciente
    # à regra de um produto não reapresentar a asserção no outro (`AUDIENCIA`): os dois são da família e a pessoa
    # clicou. Só nesta direção, só para os endereços do meuGuarda.
    # o mapa embutido (Plano Casa GS, R6): o cookie de lá é SameSite=Lax, então o iframe mora no MESMO site da página de
    # cima (termovision.meuwatt.com.br no meuWatt, termovision.meuplano.solar no meuPlano); a janelinha aberta de dentro
    # dele volta para esses endereços
    "termovision": ("TermoVision", frozenset({"termovision.gestao.solar", "app.termovision.tech",
                                              "termovision.meuwatt.com.br", "termovision.meuplano.solar",
                                              "meuguarda.gestao.solar", "meuguarda.177.153.20.214.sslip.io"})),
    # o helper (botão dos portões, 28/11/2026): recebe o passe do meuWatt (ele troca no `/auth/gestao-solar` de lá)
    "helper": ("helper", frozenset({"helper.gestao.solar", "dev-helper.gestao.solar"})),
}

#: Os que só existem em http (só pela VPN, sem certificado ainda). O passe vai no FRAGMENTO, que não sai do navegador;
#: o helper já recebia essa mesma asserção por http no formulário "Entrar com o Gestão Solar" dele.
SO_HTTP = frozenset({"helper"})


def entradas() -> dict[str, str]:
    """Onde cada sistema recebe o passe vindo dos botões do GS (a `volta` padrão)."""
    s = get_settings()
    return {"meuwatt": f"{s.meuwatt_web_url.rstrip('/')}/", "meuplano": f"{s.meuplano_web_url.rstrip('/')}/",
            "meuguarda": f"{s.meuguarda_web_url.rstrip('/')}/",
            "termovision": f"{s.termovision_web_url.rstrip('/')}/entrar.html"}


def liberados(usuario: User) -> list[str]:
    """Os sistemas que esta conta abre pelo GS, na ordem dos botões. O meuWatt e o meuPlano pela ligação com a conta
    de lá (só então eles aceitam o passe); o meuGuarda e o TermoVision pelo acesso que o gerente liberou."""
    return [p for p, ok in (("meuwatt", usuario.entra_no_meuwatt), ("meuplano", usuario.entra_no_meuplano),
                            ("meuguarda", usuario.entra_no_meuguarda), ("termovision", usuario.entra_no_termovision))
            if ok]


def assinar(usuario: User, produto: Produto, db: Session | None = None, empresa_id: int | None = None) -> str:
    """A asserção que prova, para aquele produto, quem é esta conta do Gestão Solar. Com `db`, o passe v2 (abaixo)."""
    aud = AUDIENCIA[produto]
    return _assinar(usuario, aud, extras_v2(db, usuario, aud, empresa_id) if db is not None else None)



#: o teto do passe: o meuGuarda e o TermoVision recusam asserção com mais de 8.000 caracteres; acima disto a lista de
#: usinas sai e o passe diz que ficou de fora (`usinas_fora`)
TETO_USINAS = 4000


def extras_v2(db: Session, usuario: User, audiencia: str, empresa_id: int | None = None, *, teto: bool = True) -> dict:
    """O passe v2 (24/11/2026, "Plano Casa GS": o GS diz quem entra e QUAIS USINAS vê). Vai em toda asserção, ao lado do
    que cada produto já lia: `v`, o login, o perfil, a empresa e as usinas.

    - `usinas`: `[{"gs": 12, "id": <no sistema>}]` (no meuWatt o slug, no meuPlano o id da usina, no meuGuarda e no
      TermoVision o número do GS), as da EMPRESA da sessão para a O&M (quem está em duas empresas leva só as da que está
      operando) e as concedidas para o dono. Lista vazia = nenhuma.
    - a plataforma (administrador, atendimento) vê todas: `todas_as_usinas: true`, sem a lista.
    - sem conseguir ler, ou grande demais para o teto: sem a lista e com `usinas_fora: true` (nunca "nenhuma"). A
      renovação (`GET /usinas-da-pessoa`, `teto=False`) não vai numa asserção: leva a lista inteira.
    Quem ainda não usa as usinas daqui segue com as dele; o produto que passar a usar lê isto, nunca uma cópia."""
    import json

    from app.api.v1.mapa import usinas_do_mapa  # noqa: PLC0415 — circular no topo
    from app.models.user import Perfil

    empresa = empresa_id if empresa_id is not None else (getattr(usuario, "empresa_da_sessao", None)
                                                          or usuario.empresa_id)
    from app.core.security import criar_token_sistema  # noqa: PLC0415 — circular no topo
    extra: dict = {"v": 2, "apelido": usuario.apelido, "perfil": usuario.perfil.value, "empresa_id": empresa,
                   # a sessão da pessoa NESTE sistema: ele a devolve em `X-Sessao-GS` quando lê pela porta dos sistemas
                   "sessao_gs": criar_token_sistema(usuario.id, audiencia)}
    if getattr(usuario, "proprietaria_id", None):          # R11: de qual dona de usina a pessoa é
        from app.models.empresa import Proprietaria  # noqa: PLC0415
        p = db.get(Proprietaria, usuario.proprietaria_id)
        if p is not None:                                  # o formato da porta (`interno_sistemas.proprietaria_de`)
            extra["proprietaria"] = {"id": p.id, "nome": p.nome,
                                     "meuplano": {"id": p.mp_owner_id} if p.mp_owner_id else None}
    if usuario.perfil in (Perfil.ADMINISTRADOR, Perfil.ATENDIMENTO):
        extra["todas_as_usinas"] = True
        return extra
    campo = {"meuwatt": "mw_plant_slug", "meuplano": "mp_usina_id"}.get(audiencia)
    try:
        # a régua da porta dos sistemas (`interno_sistemas.visiveis`): a O&M leva TODAS as usinas da empresa da sessão,
        # também as fora do aplicativo (a que só existe no TermoVision nasce assim); o dono, as concedidas e ligadas
        from app.api.v1.interno_sistemas import visiveis  # noqa: PLC0415 — circular no topo
        links = (visiveis(db, usuario, empresa) if usuario.perfil in (Perfil.GESTOR_EMPRESA, Perfil.TECNICO)
                 else usinas_do_mapa(db, usuario))
    except Exception:                                      # noqa: BLE001 — sem a lista, o passe segue dizendo isso
        logger.warning("passe: não leu as usinas de %s", usuario.apelido, exc_info=True)
        extra["usinas_fora"] = True
        return extra
    lista = [{"gs": u.id, "id": getattr(u, campo) if campo else u.id} for u in links
             if (getattr(u, campo) if campo else u.id) is not None]
    if teto and len(json.dumps(lista)) > TETO_USINAS:
        extra["usinas_fora"] = True
    else:
        extra["usinas"] = lista
    return extra


def meuplano_id_de(db: Session, usuario_id: int) -> int | None:
    """O id da pessoa no meuPlano a que o cadastro do GS está ligado (o TermoVision reconhecia quem entrava por ele)."""
    from app.services import cadastro  # noqa: PLC0415 — circular no topo

    v = cadastro.vinculo_meuplano(db, usuario_id)
    return int(v.usuario_remoto_id) if v and str(v.usuario_remoto_id).isdigit() else None


def assinar_login(usuario: User, produto: str, portao: str, empresa_id: int | None,
                  meuplano_id: int | None = None, db: Session | None = None, liberado: bool | None = None) -> str:
    """A asserção do "Entrar com o Gestão Solar" de um produto de `SO_LOGIN`. `portao`: cliente, empresa, tecnico ou
    painel — o da sessão que pediu; `empresa_id`: a empresa em que ela está operando; `<produto>`: se o gerente
    liberou o acesso (falso = o produto recusa)."""
    extra = {"apelido": usuario.apelido, "perfil": usuario.perfil.value, "portao": portao, "empresa_id": empresa_id}
    if produto == MEUGUARDA:
        extra[MEUGUARDA] = usuario.entra_no_meuguarda
    elif produto == TERMOVISION:                         # `liberado`: o acesso do momento (desligar no provisionar)
        extra.update({TERMOVISION: usuario.entra_no_termovision if liberado is None else liberado,
                      "meuplano_id": meuplano_id})
    else:
        raise ValueError(produto)
    if db is not None:                                     # o passe v2 por cima, sem trocar o que o produto já lia
        extra = {**extras_v2(db, usuario, produto, empresa_id), **extra}
    return _assinar(usuario, produto, extra)


def _assinar(usuario: User, audiencia: str, extra: dict | None = None) -> str:
    s = get_settings()
    if not s.gs_sso_private_key:
        raise SemChave(
            "GS_SSO_PRIVATE_KEY não configurada: o Gestão Solar não consegue assinar a "
            "identidade desta conta. Gere um par de chaves e informe a privada aqui e a "
            "pública no produto."
        )

    agora = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": s.gs_sso_issuer,
            "aud": audiencia,
            "sub": str(usuario.id),
            "jti": str(uuid.uuid4()),
            "iat": int(agora.timestamp()),
            "exp": int((agora + VALIDADE).timestamp()),
            "email": usuario.email,
            "name": usuario.nome,
            **(extra or {}),
        },
        _privada(),
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
