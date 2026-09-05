# -*- coding: utf-8 -*-
"""A sessão da Talk Solar: JWT curto + refresh longo e revogável.

Por que dois valores em vez de um token eterno: o app de PC fica ABERTO O DIA INTEIRO. Com um
token curto sozinho, todo mundo é deslogado no meio da tarde; com um token eterno, revogar o
acesso de quem foi desligado da empresa vira impossível. Curto para usar, longo para renovar,
e o longo morre quando alguém manda.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .config import get_db
from .models import App, Sessao, Usuario


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def criar_jwt(u: Usuario) -> str:
    agora = datetime.utcnow()
    return jwt.encode({"sub": str(u.id), "app": u.app_id, "nome": u.nome,
                       "iat": agora, "exp": agora + timedelta(hours=config.JWT_HORAS)},
                      config.JWT_SECRET, algorithm="HS256")


def abrir_sessao(db: Session, u: Usuario, dispositivo: Optional[str]) -> tuple[str, str]:
    """Devolve `(jwt, refresh)`. O refresh em claro aparece UMA vez: o banco guarda o hash."""
    refresh = secrets.token_urlsafe(36)
    db.add(Sessao(usuario_id=u.id, refresh_hash=_hash(refresh),
                  dispositivo=(dispositivo or "")[:120] or None))
    db.flush()
    return criar_jwt(u), refresh


def renovar(db: Session, refresh: str) -> tuple[str, Usuario]:
    s = db.query(Sessao).filter(Sessao.refresh_hash == _hash(refresh)).first()
    if s is None or s.revogada_em is not None:
        raise HTTPException(401, "Sessão encerrada. Entre de novo.")
    # sessão parada há muito tempo é sessão esquecida — em PC compartilhado, um risco
    limite = datetime.utcnow() - timedelta(days=config.SESSAO_DIAS)
    if (s.usada_em or s.criada_em) < limite:
        s.revogada_em = datetime.utcnow()
        raise HTTPException(401, "Sessão expirada por inatividade. Entre de novo.")
    u = db.get(Usuario, s.usuario_id)
    if u is None or not u.ativo:
        raise HTTPException(401, "Conta inativa.")
    s.usada_em = datetime.utcnow()
    return criar_jwt(u), u


def revogar(db: Session, refresh: str) -> None:
    s = db.query(Sessao).filter(Sessao.refresh_hash == _hash(refresh)).first()
    if s is not None and s.revogada_em is None:
        s.revogada_em = datetime.utcnow()


def _do_token(db: Session, token: str) -> Usuario:
    try:
        dados = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sessão vencida.")
    except jwt.PyJWTError:
        raise HTTPException(401, "Token inválido.")
    u = db.get(Usuario, int(dados.get("sub", 0)))
    if u is None or not u.ativo:
        raise HTTPException(401, "Conta inativa.")
    return u


def usuario_atual(request: Request, db: Session = Depends(get_db)) -> Usuario:
    """A dependency de tudo. O `Bearer` é obrigatório — não existe rota anônima de conversa."""
    cab = request.headers.get("Authorization") or ""
    if not cab.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado.")
    return _do_token(db, cab[7:].strip())


def usuario_do_ws(db: Session, token: str) -> Optional[Usuario]:
    """O WebSocket recebe o token na URL — a API do navegador não deixa mandar cabeçalho.
    É a limitação da plataforma, não uma escolha: o token é o mesmo e é validado igual."""
    try:
        return _do_token(db, token)
    except HTTPException:
        return None


def app_do_usuario(db: Session, u: Usuario) -> App:
    app = db.get(App, u.app_id)
    if app is None or not app.ativo:
        raise HTTPException(403, "Este sistema não está mais integrado.")
    return app
