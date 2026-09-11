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

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.core.db import get_db
from app.core.security import (
    conferir_senha,
    criar_token,
    gerar_hash_senha,
    usuario_atual,
)
from app.models.integracao import Produto
from app.models.user import User, UserPlantAccess, VinculoProduto

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


class LoginIn(BaseModel):
    apelido: str
    senha: str


class LoginOut(BaseModel):
    token: str
    expira_em: datetime
    usuario: UsuarioOut


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
        empresa=usuario.empresa,
        tem_meuwatt=Produto.MEUWATT.value in produtos,
        tem_meuplano=Produto.MEUPLANO.value in produtos,
        nivel_acesso=usuario.nivel_acesso,
        usinas=usinas,
        trocar_senha=usuario.trocar_senha,
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    usuario = db.scalar(
        select(User).where(User.apelido == (body.apelido or "").strip().lower())
    )

    # Mensagem única para conta inexistente, senha errada e conta desativada — quem tenta
    # adivinhar não aprende qual das três aconteceu.
    if (
        usuario is None
        or not usuario.ativo
        or not conferir_senha(body.senha, usuario.senha_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Apelido ou senha inválidos")

    usuario.ultimo_login = datetime.now(UTC)
    db.commit()

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


@router.post("/trocar-senha", status_code=204)
def trocar_senha(
    body: TrocarSenhaIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> None:
    """Fecha o ciclo da senha provisória entregue pelo gestor.

    Exige a senha atual mesmo com a sessão já autenticada: um celular desbloqueado e
    esquecido na mesa não deve bastar para trocar a senha e trancar o dono para fora.
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
    db.commit()


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


@router.post("/produtos/{produto}/assercao", response_model=AssercaoOut)
def assercao_para_produto(
    produto: Produto, body: AssercaoIn, db: Session = Depends(get_db)
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

    usuario = db.scalar(
        select(User).where(User.apelido == (body.apelido or "").strip().lower())
    )
    # Mesma mensagem única do /login: quem tenta adivinhar não aprende qual dos três
    # motivos aconteceu.
    if (
        usuario is None
        or not usuario.ativo
        or not conferir_senha(body.senha, usuario.senha_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Apelido ou senha inválidos")

    try:
        assercao = login_externo.assinar(usuario, produto)
    except login_externo.SemChave as exc:
        # 503 e não 500: não é defeito, é uma instalação sem a chave configurada, e a
        # frase diz qual variável falta.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    usuario.ultimo_login = datetime.now(UTC)
    db.commit()
    return AssercaoOut(assertion=assercao, nome=usuario.nome)
