# -*- coding: utf-8 -*-
"""Talk Solar — configuração e conexão.

Tudo por variável de ambiente, sem nenhum valor de produção no código. É o que permite este
mesmo commit rodar na máquina do programador, no serviço do Railway e (um dia) em outro lugar,
sem editar arquivo.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

#: O BANCO — o do Gestão Solar. As tabelas do Talk Solar têm prefixo `ts_` e convivem com as
#: dele sem se misturar. Sem `DATABASE_URL` cai num SQLite local, para o `npm start` de quem
#: acabou de clonar funcionar antes de ter credencial nenhuma.
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./talksolar.db"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

#: Assina o JWT das sessões. Em produção é OBRIGATÓRIA — ver `checar_producao()`.
JWT_SECRET = os.getenv("TALK_JWT_SECRET") or "desenvolvimento-nao-use-em-producao"
JWT_HORAS = int(os.getenv("TALK_JWT_HORAS") or 12)
SESSAO_DIAS = int(os.getenv("TALK_SESSAO_DIAS") or 90)

#: Storage dos anexos. `local` grava em disco (bom para desenvolver); `supabase` usa o Storage
#: do projeto do Gestão Solar. O código de quem chama é o mesmo nos dois.
STORAGE = os.getenv("TALK_STORAGE") or "local"
STORAGE_DIR = os.getenv("TALK_STORAGE_DIR") or str(Path(__file__).resolve().parents[1] / "arquivos")
SUPABASE_URL = os.getenv("SUPABASE_URL") or ""
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or ""
SUPABASE_BUCKET = os.getenv("TALK_BUCKET") or "talksolar"

#: Quem pode abrir o app pelo navegador. `*` em desenvolvimento; em produção, a lista.
CORS = [x.strip() for x in (os.getenv("TALK_CORS") or "*").split(",") if x.strip()]

MAX_ARQUIVO_MB = int(os.getenv("TALK_MAX_ARQUIVO_MB") or 25)
MAX_ARQUIVOS = int(os.getenv("TALK_MAX_ARQUIVOS") or 10)
MAX_CITACOES = int(os.getenv("TALK_MAX_CITACOES") or 10)

#: Quanto se espera o sistema hospedeiro. Curto de propósito: se o meuPlano está lento, a
#: Talk Solar tem de dizer isso rápido (502) em vez de segurar a tela de todo mundo.
TIMEOUT_IDENTIDADE = float(os.getenv("TALK_TIMEOUT_IDENTIDADE") or 8)
TIMEOUT_BUSCA = float(os.getenv("TALK_TIMEOUT_BUSCA") or 5)
TIMEOUT_WEBHOOK = float(os.getenv("TALK_TIMEOUT_WEBHOOK") or 10)

#: Reenvio do webhook: imediato, 30 s, 2 min, 10 min, 1 h. Depois disso fica registrado como
#: falho e aparece no painel — silêncio seria pior do que a falha.
REENVIOS_SEG = [30, 120, 600, 3600]

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    **({"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else
       {"pool_size": int(os.getenv("DB_POOL_SIZE") or 5), "max_overflow": 2, "pool_recycle": 240}),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def checar_producao() -> list[str]:
    """O que está faltando para isto ser produção. Chamado no boot e exposto em `/saude`.

    Subir com o segredo de desenvolvimento é a falha que ninguém percebe até alguém forjar um
    token — então o servidor DIZ, alto, no log e na saúde.
    """
    faltas = []
    if JWT_SECRET == "desenvolvimento-nao-use-em-producao":
        faltas.append("TALK_JWT_SECRET não definida (qualquer um forja uma sessão)")
    if DATABASE_URL.startswith("sqlite"):
        faltas.append("DATABASE_URL não definida (usando SQLite local)")
    if STORAGE == "local":
        faltas.append("TALK_STORAGE=local — os anexos somem a cada deploy do Railway")
    if CORS == ["*"]:
        faltas.append("TALK_CORS aberto para qualquer origem")
    return faltas


def sessao_direta() -> Session:
    """Uma sessão fora do ciclo de requisição (worker de webhook, scripts)."""
    return SessionLocal()
