"""Entrada do aplicativo — o dono da usina.

Separada da entrada do painel (`painel.entrar`) mesmo compartilhando a tabela de usuários,
porque as duas respondem perguntas diferentes:

- O painel devolve uma sessão curta, de escopo `painel`, e só aceita quem administra.
- Aqui a sessão é longa (o app fica semanas aberto no celular) e só aceita quem NÃO
  administra por este caminho — um token do app não abre o painel, e é o `escopo` no JWT
  que garante isso (ver `core/security.gestor_atual`).

Quem autentica é o apelido. O e-mail continua no cadastro porque é ele que encontra a
conta da pessoa no meuWatt e no meuPlano, mas não serve para entrar: ver `core/apelido.py`.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.painel import CodigoIn, DuasEtapasOut
from app.api.v1.plants import usinas_do_usuario
from app.core.config import get_settings
from app.core.tokens_produto import NOME
from app.core.db import get_db
from app.models.empresa import Empresa
from app.core.security import (
    conferir_senha,
    criar_token,
    gerar_hash_senha,
    usuario_atual,
)
from app.models.integracao import Produto
from app.models.user import User, UserPlantAccess, VinculoProduto

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["app · autenticação"])


class UsuarioOut(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    empresa: str | None = None
    #: Que abas o app deve mostrar. Sem vínculo com um produto, a aba correspondente
    #: abriria vazia sem explicar por quê — melhor ela não existir.
    tem_meuwatt: bool
    tem_meuplano: bool
    nivel_acesso: int
    #: Quantas usinas o gestor concedeu. Zero é uma situação legítima e diagnosticável
    #: (cliente cadastrado, usinas ainda não concedidas), e o app avisa em vez de
    #: mostrar uma lista vazia sem contexto.
    usinas: int
    #: Enquanto verdadeiro, o app leva para a troca de senha antes de qualquer tela.
    trocar_senha: bool
    #: Se a pessoa entra no meuGuarda (o gerente libera no oem-gs; a plataforma sempre). O meuGuarda lê daqui e recusa
    #: o falso; ausente conta como liberado lá.
    meuguarda: bool = True


class LoginIn(BaseModel):
    apelido: str
    senha: str


class LoginOut(BaseModel):
    #: vazios quando falta o código da verificação em duas etapas (`duas_etapas`, R12)
    token: str = ""
    expira_em: datetime | None = None
    usuario: UsuarioOut | None = None
    duas_etapas: DuasEtapasOut | None = None


def _perfil(db: Session, usuario: User) -> UsuarioOut:
    produtos = {
        v.produto
        for v in db.scalars(
            select(VinculoProduto).where(VinculoProduto.gs_user_id == usuario.id)
        ).all()
    }
    # A MESMA contagem que a aba Usinas faz. Sem o filtro de `PlantLink.ativo`, o Perfil
    # dizia "Usinas 4" e a lista mostrava 3: desligar uma usina no painel preserva a
    # concessão de propósito (para religar sem refazer nada), então a concessão continua
    # existindo enquanto a usina some do aplicativo. Contar as duas coisas com réguas
    # diferentes fazia o app se contradizer sobre um número que o dono confere de relance.
    usinas = len(usinas_do_usuario(db, usuario))
    return UsuarioOut(
        id=usuario.id,
        nome=usuario.nome,
        apelido=usuario.apelido,
        email=usuario.email,
        # o campo antigo é texto livre e ficou vazio nas contas novas: vale a empresa de O&M
        empresa=usuario.empresa or (db.get(Empresa, usuario.empresa_id).nome if usuario.empresa_id else None),
        tem_meuwatt=Produto.MEUWATT.value in produtos,
        tem_meuplano=Produto.MEUPLANO.value in produtos,
        nivel_acesso=usuario.nivel_acesso,
        usinas=usinas,
        trocar_senha=usuario.trocar_senha,
        meuguarda=usuario.entra_no_meuguarda,
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db), request: Request = None) -> LoginOut:
    from app.services import acessos

    # o login ou o e-mail (24/11/2026); a frase única para conta inexistente, senha errada e conta desativada — quem
    # tenta adivinhar não aprende qual das três aconteceu. O motivo vai só ao registro de acessos.
    usuario = acessos.entrar_ou_recusar(db, request, body.apelido, body.senha)
    from app.services import duas_etapas
    if duas_etapas.exigida(usuario):                       # R12: o gerente e a plataforma passam pelo código
        from app.api.v1.painel import pedir_codigo
        return LoginOut(duas_etapas=pedir_codigo(db, usuario, "cliente"))
    return _sessao_do_cliente(db, request, usuario, body.apelido, "aplicativo ou portal")


@router.post("/login/codigo", response_model=LoginOut)
def login_com_codigo(body: CodigoIn, db: Session = Depends(get_db), request: Request = None) -> LoginOut:
    """O segundo passo do login do portal e do aplicativo: o código do autenticador."""
    from app.api.v1.painel import conta_do_codigo
    usuario = conta_do_codigo(db, request, body, "cliente")
    return _sessao_do_cliente(db, request, usuario, usuario.apelido,
                              "aplicativo ou portal, com a verificação em duas etapas")


def _sessao_do_cliente(db: Session, request: Request | None, usuario: User, login: str, motivo: str) -> LoginOut:
    from app.services import acessos
    usuario.ultimo_login = datetime.now(UTC)
    db.commit()
    acessos.registrar(db, request, acao="entrou", user=usuario, login=login, motivo=motivo)
    token, expira = criar_token(usuario.id)
    return LoginOut(token=token, expira_em=expira, usuario=_perfil(db, usuario))


@router.get("/eu", response_model=UsuarioOut)
def eu(db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)) -> UsuarioOut:
    """Revalida a sessão guardada no celular e devolve o perfil atualizado.

    O app chama isto ao abrir: o token dura 30 dias e, nesse intervalo, o gestor pode ter
    concedido uma usina nova ou vinculado um produto. Sem esta chamada o app decidiria
    quais abas mostrar com base no que era verdade no dia do login.
    """
    return _perfil(db, usuario)


@router.post("/renovar", response_model=LoginOut)
def renovar(db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)) -> LoginOut:
    """Sessão deslizante: troca um token de cliente ainda válido por um novo de 30 dias.

    O portal do cliente fica semanas aberto numa aba do notebook. Sem isto, o token vencia
    no meio do uso e a pessoa caía na tela de entrada sem ter feito nada — e um cliente
    corporativo que precisa digitar senha todo mês deixa de abrir o portal. O cliente
    (app ou portal) chama aqui quando `expira_em` está perto, e guarda o novo par.

    O que a renovação NÃO faz, de propósito: não aceita token vencido (aí é senha de novo —
    é o único corte que um token perdido tem), não aceita sessão de painel (a guarda
    `usuario_atual` já recusa), e não cria tabela nova — `criar_token` é a mesma emissão do
    login, então o token novo é indistinguível de um login recente.
    """
    token, expira = criar_token(usuario.id)
    return LoginOut(token=token, expira_em=expira, usuario=_perfil(db, usuario))


class TrocarSenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str


class SessaoNovaOut(BaseModel):
    """A sessão nova DESTE aparelho depois de trocar a senha (as outras foram encerradas)."""
    token: str
    expira_em: datetime


@router.post("/trocar-senha", response_model=SessaoNovaOut)
def trocar_senha(
    body: TrocarSenhaIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
    request: Request = None,
) -> SessaoNovaOut:
    """Fecha o ciclo da senha provisória entregue pelo gestor.

    Exige a senha atual mesmo com a sessão já autenticada: um celular desbloqueado e
    esquecido na mesa não deve bastar para trocar a senha e trancar o dono para fora.

    Senha trocada encerra TODAS as sessões (a de quem roubou a senha, as dos sistemas, a ligação do Claude); este
    aparelho continua com a sessão nova que volta aqui (R12).
    """
    if not conferir_senha(body.senha_atual, usuario.senha_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A senha atual não confere.")
    if len(body.senha_nova) < 8:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A senha nova precisa de pelo menos 8 caracteres."
        )
    if body.senha_nova == body.senha_atual:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A senha nova precisa ser diferente da atual."
        )

    usuario.senha_hash = gerar_hash_senha(body.senha_nova)
    usuario.trocar_senha = False
    from app.services import acessos, sessoes
    sessoes.encerrar_todas(db, usuario, por=usuario, motivo="trocou a própria senha")
    db.commit()
    acessos.registrar(db, request, acao="senha", user=usuario,
                      motivo="trocou a própria senha; as outras sessões foram encerradas")
    token, expira = criar_token(usuario.id)
    return SessaoNovaOut(token=token, expira_em=expira)


# ─────────────────────── entrar nos produtos com esta conta ───────────────────
#
# O caminho de "Entrar com Gestão Solar", visto do lado de cá.
#
# O produto (meuWatt/meuPlano) NUNCA vê a senha do Gestão Solar: a tela de login dele
# manda apelido e senha PARA CÁ, recebe de volta uma asserção assinada e válida por dois
# minutos, e é ela que apresenta ao próprio backend. Três consequências que valem a
# ida-e-volta extra:
#
# * a senha daqui é conferida aqui, por quem tem o hash;
# * o produto só precisa da chave PÚBLICA — não há segredo para combinar entre três
#   repositórios que sobem separados;
# * revogar o acesso de alguém é desativar a conta aqui, e vale para os dois produtos no
#   mesmo instante.
#
# A asserção não é uma sessão: ela só serve para o produto reconhecer a pessoa e emitir a
# sessão DELE. Quem não estiver vinculado lá é recusado lá — ver `services/vinculos.py`.


class AssercaoIn(BaseModel):
    apelido: str
    senha: str


class AssercaoOut(BaseModel):
    assertion: str
    #: Só para a tela do produto poder dizer "entrando como Fulano" antes de trocar a
    #: asserção por sessão. Não substitui nada: quem decide o que a pessoa vê é o produto.
    nome: str


#: O SITE de cada produto — não a API. É para lá que o navegador do cliente vai.
def _enderecos_web() -> dict[Produto, str]:
    s = get_settings()
    return {Produto.MEUWATT: s.meuwatt_web_url, Produto.MEUPLANO: s.meuplano_web_url}


class DestinoOut(BaseModel):
    """Para onde mandar o navegador para a pessoa cair logada do outro lado."""

    url: str
    nome: str


@router.post("/produtos/{produto}/entrar", response_model=DestinoOut)
def entrar_no_produto(
    produto: Produto, db: Session = Depends(get_db), usuario: User = Depends(usuario_atual), request: Request = None
) -> DestinoOut:
    """O cliente já está logado AQUI e quer abrir o produto sem digitar nada de novo.

    Diferente de `/assercao`: lá a pessoa apresenta apelido e senha (é a tela de login do
    produto chamando de fora); aqui ela já provou quem é nesta sessão, e o que falta é
    carregar essa prova para o outro lado.

    A asserção viaja no **fragmento** da URL (`#assercao=`), nunca na query. O fragmento
    não é enviado ao servidor: não entra em log de acesso, não vaza pelo `Referer` e não
    fica no histórico do proxy. Ela vale dois minutos e uma vez só — mas dois minutos num
    log são dois minutos a mais do que o necessário.

    Quem recusa alguém não vinculado é o PRODUTO, não esta rota. Antecipar a recusa aqui
    obrigaria o Gestão Solar a manter uma cópia de um estado que é de lá, e ela erraria
    justamente no dia em que alguém vinculasse a conta e o botão continuasse dizendo não.
    """
    from app.services import login_externo

    try:
        assercao = login_externo.assinar(usuario, produto, db=db)
    except login_externo.SemChave as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    from app.services import acessos
    acessos.registrar(db, request, acao="passe", sistema=produto.value, user=usuario, motivo="botão do portal")
    destino = _enderecos_web().get(produto) or ""
    return DestinoOut(url=f"{destino.rstrip('/')}/#assercao={assercao}", nome=NOME[produto])


@router.post("/produtos/{produto}/assercao", response_model=AssercaoOut)
def assercao_para_produto(
    produto: str, body: AssercaoIn, db: Session = Depends(get_db), request: Request = None
) -> AssercaoOut:
    """Confere a senha do Gestão Solar e assina quem é esta conta, para aquele produto.

    A asserção é emitida para UM produto (`aud`): a do meuWatt não vale no meuPlano. Sem
    essa separação, um produto comprometido poderia reapresentar no outro a asserção que
    recebeu e entrar lá como a pessoa.

    Emite mesmo que a conta ainda não esteja conectada àquele produto. É deliberado: quem
    sabe se existe vínculo é o produto, e antecipar a recusa aqui obrigaria este endpoint
    a manter uma cópia de um estado que é de lá.
    """
    from app.services import login_externo

    if produto not in login_externo.SO_LOGIN and produto not in {p.value for p in Produto}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    from app.services import acessos

    # Mesma régua e mesma frase do /login (o login ou o e-mail). O IP é o do servidor do produto, que chama por trás.
    # o servidor do outro sistema chama esta rota: da casa, ele fica fora do limite por IP (`acessos._da_casa`); quem
    # chama de fora tem os dois limites
    usuario = acessos.entrar_ou_recusar(db, request, body.apelido, body.senha, sistema=produto)

    # a empresa desligada não entra, em nenhum sistema (24/11/2026: antes o meuWatt e o meuPlano passavam)
    from app.core.security import _empresa_ativa
    _empresa_ativa(db, usuario)
    from app.services import duas_etapas
    if duas_etapas.exigida(usuario):                       # R12: a tela de senha do sistema não pede o código
        acessos.registrar(db, request, acao="recusado", sistema=produto, user=usuario, ok=False,
                          motivo="senha certa, mas a conta usa a verificação em duas etapas: pelo botão do GS")
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Esta conta usa a verificação em duas etapas: entre pelo botão “Entrar com o Gestão "
                            "Solar”. A senha está certa.")
    if produto in login_externo.SO_LOGIN:
        # O meuGuarda e o TermoVision (a tela de entrar deles, servidor a servidor: o TermoVision pediu, 11/11/2026, que
        # o apelido e a senha do GS valham direto lá). A mesma asserção do redirecionamento, com o portão do perfil.
        from app.services import pessoas

        try:
            assercao = login_externo.assinar_login(
                usuario, produto, pessoas.escopo_do_perfil(usuario.perfil), usuario.empresa_id,
                login_externo.meuplano_id_de(db, usuario.id) if produto == login_externo.TERMOVISION else None,
                db=db)
        except login_externo.SemChave as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    else:
        try:
            assercao = login_externo.assinar(usuario, Produto(produto), db=db)
        except login_externo.SemChave as exc:
            # 503 e não 500: não é defeito, é uma instalação sem a chave configurada, e a
            # frase diz qual variável falta.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    usuario.ultimo_login = datetime.now(UTC)
    db.commit()
    acessos.registrar(db, request, acao="passe", sistema=produto, user=usuario, login=body.apelido,
                      motivo="login e senha do GS na tela do sistema")
    return AssercaoOut(assertion=assercao, nome=usuario.nome)


# ------------------------------------------------- o "esqueci a senha" (Plano Casa GS, R12)


class CanaisDeSenhaOut(BaseModel):
    #: o número do WhatsApp do GS (mande "esqueci a senha" daqui, do celular cadastrado); nulo = não pôde ser lido agora
    whatsapp: str | None = None
    #: dá para pedir o link por e-mail (há remetente)
    email: bool = False


@router.get("/senha/canais", response_model=CanaisDeSenhaOut)
async def canais_de_senha() -> CanaisDeSenhaOut:
    from app.services import esqueci_a_senha
    return CanaisDeSenhaOut(whatsapp=await esqueci_a_senha.numero_do_bot(), email=esqueci_a_senha.email_disponivel())


class EsqueciIn(BaseModel):
    email: str


def _pedido_por_email(email: str, ip: str) -> None:
    """O pedido do link por e-mail, DEPOIS da resposta (`BackgroundTasks`): procurar a conta, emitir o link e mandar o
    e-mail. A resposta é a mesma, no mesmo tempo, exista a conta ou não (não confirma e-mail a quem tenta). A falha do
    remetente fica no Registro de acessos, nunca na tela."""
    from app.core.db import SessionLocal
    from app.services import acessos, esqueci_a_senha
    db = SessionLocal()
    try:
        contas = esqueci_a_senha.contas_do_email(db, email)
        if len(contas) != 1:                               # duas contas com o mesmo e-mail: só pelo WhatsApp (o número
            return                                         # diz qual); nenhuma: nada
        u = contas[0]
        token = esqueci_a_senha.emitir(db, u, "email")
        db.commit()
        try:
            esqueci_a_senha.mandar_email(u.email, esqueci_a_senha.link(token))
            acessos.registrar(db, None, acao="senha", user=u, motivo=f"pediu o link de senha nova (e-mail, de {ip})")
        except Exception:                                  # noqa: BLE001 — o remetente falhou
            log.warning("esqueci a senha: o e-mail não saiu", exc_info=True)
            acessos.registrar(db, None, acao="senha", user=u, ok=False,
                              motivo=f"pediu o link de senha nova (e-mail, de {ip}), e o e-mail não saiu")
    finally:
        db.close()


@router.post("/senha/esqueci", status_code=202)
def esqueci_a_senha_por_email(body: EsqueciIn, tarefas: BackgroundTasks, db: Session = Depends(get_db),
                              request: Request = None) -> dict:
    """O link por e-mail. A resposta é a mesma, no mesmo tempo, exista a conta ou não: o trabalho que depende da conta
    vai depois dela. O limite é o das senhas erradas (por e-mail e lugar)."""
    from app.services import acessos, esqueci_a_senha
    if not esqueci_a_senha.email_disponivel():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "O link por e-mail ainda não está disponível: mande \"esqueci a senha\" ao WhatsApp do GS.")
    email = (body.email or "").strip().lower()
    if (porque := acessos.barrado(request, email, db=db)) is not None:
        acessos.recusar_barrado(db, request, email, porque=porque)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, acessos.BARRADO)
    acessos.contar_erro(request, email)                    # cada pedido conta: e-mail em massa para no limite
    tarefas.add_task(_pedido_por_email, email, acessos._ip(request) or "sem IP")
    return {"ok": True}


class NovaSenhaIn(BaseModel):
    token: str
    senha: str


@router.post("/senha/nova", status_code=204)
def nova_senha(body: NovaSenhaIn, db: Session = Depends(get_db), request: Request = None) -> None:
    """A senha nova pelo link do "esqueci a senha". As sessões abertas da pessoa acabam (inclusive as dos sistemas)."""
    from app.services import acessos, esqueci_a_senha, sessoes
    try:
        u = esqueci_a_senha.trocar(db, body.token, body.senha)
    except esqueci_a_senha.LinkInvalido as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    sessoes.encerrar_todas(db, u, por=u, motivo="senha nova pelo esqueci a senha")
    db.commit()
    acessos.registrar(db, request, acao="senha", user=u, por=u,
                      motivo="senha nova pelo link do esqueci a senha; as sessões abertas foram encerradas")
