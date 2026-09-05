# -*- coding: utf-8 -*-
"""Talk Solar — o banco.

Prefixo `ts_` em tudo: este projeto vai morar no banco do Gestão Solar, ao lado das tabelas
dele. Um prefixo próprio é a diferença entre "as tabelas do Talk Solar" e "umas tabelas
soltas que ninguém sabe de quem são" no dia em que alguém abrir o Supabase.

O QUE ESTE BANCO **NÃO** GUARDA — e é a decisão que define o produto:

· **senha e cadastro de usuário.** Três sistemas com login próprio não podem virar quatro.
  `ts_usuarios` é um ESPELHO: a chave é o par (app, id externo), e nome/e-mail são
  reescritos a cada entrada com o que o sistema hospedeiro disser.
· **o domínio de ninguém.** Não há tabela de usina, de OS, de tarefa. A citação guarda
  `tipo` + `id` OPACOS, mais o rótulo e a URL que o sistema devolveu — congelados.

O que se ganha: o Talk Solar sobe, cai e é reimplantado sem tocar em nenhum outro sistema; e
integrar o quarto sistema não mexe no schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class App(Base):
    """Um sistema integrado: meuPlano, meuWatt, Gestão Solar.

    É aqui que se cadastra um sistema novo — e é a ÚNICA coisa que se cadastra. As três URLs
    são o contrato inteiro (docs/API.md §4); só a primeira é obrigatória.

    O `secret` faz os dois lados: assina o webhook que sai e autentica a chamada que a Talk
    Solar faz ao sistema (`X-Talk-Secret`). Um segredo por sistema — vazar o do meuWatt não
    dá acesso ao meuPlano.
    """
    __tablename__ = "ts_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(30), unique=True)      # meuplano | meuwatt | gestaosolar
    nome: Mapped[str] = mapped_column(String(80))
    secret: Mapped[str] = mapped_column(String(80))
    #: (1) de quem é este token? — o único obrigatório
    identidade_url: Mapped[str] = mapped_column(String(400))
    #: (2) o que este usuário pode citar? (sem ele, não há citação)
    refs_busca_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    #: (3) como se chama este alvo? (sem ele, o rótulo vem do cliente — que pode mentir)
    refs_label_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    #: para onde a Talk Solar avisa que houve conversa
    webhook_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    webhook_eventos: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Usuario(Base):
    """O ESPELHO de uma pessoa. Não é cadastro: quem manda é o sistema hospedeiro.

    `externo_id` é STRING de propósito — um sistema usa int, outro usa UUID. A Talk Solar não
    tem opinião sobre isso, e não precisa ter.
    """
    __tablename__ = "ts_usuarios"
    __table_args__ = (UniqueConstraint("app_id", "externo_id", name="uq_ts_usuario"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("ts_apps.id", ondelete="CASCADE"), index=True)
    externo_id: Mapped[str] = mapped_column(String(60))
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    visto_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Sessao(Base):
    """O aparelho conectado. É o que faz a sessão não cair no meio do expediente.

    O JWT dura horas; este registro dura meses e é revogável um a um. Sem ele, um app que fica
    aberto o dia inteiro pediria senha toda tarde — e um mensageiro que pede senha é um
    mensageiro que ninguém usa.
    """
    __tablename__ = "ts_sessoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("ts_usuarios.id", ondelete="CASCADE"), index=True)
    #: guardamos o SHA-256; o valor em claro aparece uma vez, na criação
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    dispositivo: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    usada_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revogada_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Canal(Base):
    """O lugar da conversa.

    `publico` — qualquer pessoa DO MESMO SISTEMA lê o histórico, mesmo sem ter entrado. É o que
    separa um mensageiro de trabalho de um monte de grupos de WhatsApp: o histórico é
    patrimônio do time, não do grupinho.
    `privado` — só membro (e o não-membro recebe 404, nunca 403).
    `dm` — conversa direta, sem nome.

    `alvo_tipo`/`alvo_id`: o canal INTEIRO é de uma usina/OS. É o que faz a conversa nascer no
    lugar certo, em vez de num grupo genérico que ninguém sabe para que serve.
    """
    __tablename__ = "ts_canais"
    __table_args__ = (Index("ix_ts_canal_alvo", "app_id", "alvo_tipo", "alvo_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("ts_apps.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(10), default="publico")   # publico|privado|dm
    nome: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    topico: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    alvo_tipo: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    alvo_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    alvo_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    alvo_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    criado_por: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ts_usuarios.id", ondelete="SET NULL"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    arquivado_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Membro(Base):
    """Quem participa — e até onde já leu.

    `ultima_lida_id` em vez de uma linha por mensagem por pessoa: o "não lido" é uma comparação
    de id, não uma tabela que cresce com gente × mensagens.
    """
    __tablename__ = "ts_membros"
    __table_args__ = (UniqueConstraint("canal_id", "usuario_id", name="uq_ts_membro"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canal_id: Mapped[int] = mapped_column(ForeignKey("ts_canais.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("ts_usuarios.id", ondelete="CASCADE"), index=True)
    papel: Mapped[str] = mapped_column(String(10), default="membro")   # dono|membro
    ultima_lida_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    silenciado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    entrou_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Mensagem(Base):
    """Uma mensagem. `responde_a` preenchido = resposta dentro de uma thread.

    Apagar é MARCAR (`apagada_em`), não sumir: numa conversa de trabalho o buraco precisa ser
    visível, senão a leitura de amanhã entende errado o que sobrou.
    """
    __tablename__ = "ts_mensagens"
    __table_args__ = (Index("ix_ts_msg_canal", "canal_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canal_id: Mapped[int] = mapped_column(ForeignKey("ts_canais.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ts_usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    conteudo: Mapped[str] = mapped_column(Text, default="")
    responde_a: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ts_mensagens.id", ondelete="CASCADE"), nullable=True, index=True)
    #: mensagem escrita pelo SISTEMA (webhook de volta: "OS fechada"), não por gente
    do_sistema: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    editada_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    apagada_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Anexo(Base):
    """Arquivo de uma mensagem. Nasce COM `mensagem_id` — nunca existe anexo órfão.

    `thumb_path` só para imagem: é o que permite a foto aparecer na conversa sem baixar 4 MB
    por rolagem. `largura`/`altura` evitam o texto abaixo saltar enquanto a imagem carrega.
    """
    __tablename__ = "ts_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mensagem_id: Mapped[int] = mapped_column(
        ForeignKey("ts_mensagens.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(255))
    caminho: Mapped[str] = mapped_column(String(500))
    thumb_caminho: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tipo: Mapped[str] = mapped_column(String(100))
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    largura: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    altura: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Citacao(Base):
    """O que a mensagem CITA, no vocabulário do sistema dono do alvo.

    `label` e `url` são CONGELADOS: a conversa de ontem mostra o nome que a coisa tinha ontem,
    e a citação sobrevive ao registro apagado. O índice por alvo responde a pergunta inversa —
    *"o que já se falou sobre esta OS?"* —, que é metade do valor de citar.
    """
    __tablename__ = "ts_citacoes"
    __table_args__ = (Index("ix_ts_citacao_alvo", "app_id", "alvo_tipo", "alvo_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mensagem_id: Mapped[int] = mapped_column(
        ForeignKey("ts_mensagens.id", ondelete="CASCADE"), index=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("ts_apps.id", ondelete="CASCADE"))
    alvo_tipo: Mapped[str] = mapped_column(String(30))
    alvo_id: Mapped[str] = mapped_column(String(60))
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Entrega(Base):
    """Uma TENTATIVA de entregar um webhook. Append-only.

    Tabela e não flag porque a pergunta que se faz é *"por que o meuWatt não recebeu?"* — e ela
    só tem resposta com o corpo, o status e a hora de CADA tentativa. Uma coluna
    `entregue: bool` responde "não" e mais nada.
    """
    __tablename__ = "ts_entregas"
    __table_args__ = (Index("ix_ts_entrega_pendente", "estado", "proxima_em"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("ts_apps.id", ondelete="CASCADE"), index=True)
    evento: Mapped[str] = mapped_column(String(40))
    #: o uuid que vai no cabeçalho — é por ele que o outro lado fica idempotente
    ref: Mapped[str] = mapped_column(String(40), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(12), default="pendente")  # pendente|entregue|falhou
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    proxima_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resposta: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    terminada_em: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
