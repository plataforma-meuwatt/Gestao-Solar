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
