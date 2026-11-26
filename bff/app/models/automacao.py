"""Automações e memória do bot (Plano Assistente GS, 26/11/2026; o dono: "tudo é gatilho, ação e onde enviar").

**Uma regra é uma linha**, com as cinco partes em JSON (gatilho, condições, escopo, ação, entrega): gatilho novo é
código em `services/automacoes.py`, sem migração. O lembrete é a mesma linha, com gatilho de uma vez só.

**Toda saída vira linha em `gs_automacao_disparos`**, inclusive em ensaio e a que não saiu ("nunca enganar": o registro
responde "por que eu não recebi"). A chave descreve o EVENTO (o episódio da leitura, o horário do dia), não a volta do
motor: a única (regra, chave, destinatário, ensaio) é o que impede o mesmo aviso de sair duas vezes.

**A memória é da pessoa**: o que ela pediu para o bot lembrar, cifrado (`core.cripto`), visível só a ela.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Automacao(Base):
    __tablename__ = "gs_automacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: O dono: é com o token DELE que a regra lê, e é ele quem recebe (Fase 1).
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    #: A empresa de origem do dono na criação: o recorte da tela do gerente.
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("gs_empresas.id", ondelete="SET NULL"), nullable=True,
                                                   index=True)
    nome: Mapped[str] = mapped_column(String(160))
    #: As palavras da pessoa ao pedir ("me avisa se a tensão do relé de Pirapozinho cair por mais de 10 min").
    texto_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    gatilho: Mapped[dict] = mapped_column(JSON)
    condicoes: Mapped[list] = mapped_column(JSON, default=list)
    escopo: Mapped[dict] = mapped_column(JSON, default=dict)
    acao: Mapped[dict] = mapped_column(JSON)
    entrega: Mapped[dict] = mapped_column(JSON, default=dict)
    #: ensaio | ligada | pausada | concluida (o lembrete que já tocou).
    situacao: Mapped[str] = mapped_column(String(20), index=True)
    #: A memória da regra entre as voltas: o episódio de cada alvo, desde quando está cega, o cursor das câmeras.
    estado: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Quando a regra acorda de novo (a hora marcada; na leitura, a próxima volta).
    proxima_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    #: A trava: a volta que pegou a regra a segura até aqui (outra volta, ou outro processo, não a pega).
    rodando_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultima_volta_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: bot | tela
    origem: Mapped[str] = mapped_column(String(20), default="bot", server_default="bot")
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Apagar não some com o registro dos disparos: a regra fica, marcada.
    apagada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomacaoDisparo(Base):
    __tablename__ = "gs_automacao_disparos"
    __table_args__ = (UniqueConstraint("automacao_id", "chave", "user_id", "ensaio", name="uq_gs_automacao_disparo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    automacao_id: Mapped[int] = mapped_column(ForeignKey("gs_automacoes.id", ondelete="CASCADE"), index=True)
    #: Quem recebe (ou receberia).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True)
    plant_link_id: Mapped[int | None] = mapped_column(ForeignKey("gs_plant_links.id", ondelete="SET NULL"),
                                                      nullable=True)
    em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    #: disparo | voltou | cega | enxergou | sem_dado | perdida | erro | teste
    evento: Mapped[str] = mapped_column(String(20))
    ensaio: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    chave: Mapped[str] = mapped_column(String(200))
    texto: Mapped[str] = mapped_column(Text)
    #: Os valores lidos e a hora deles: o que provou o disparo.
    leitura: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: whatsapp | push | whatsapp+push | adiado | nenhum
    canal: Mapped[str | None] = mapped_column(String(30), nullable=True)
    #: enviada | falhou | adiada | entregue | venceu | simulada | recusada
    status: Mapped[str] = mapped_column(String(20))
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    notificacao_id: Mapped[int | None] = mapped_column(ForeignKey("gs_notificacoes_enviadas.id", ondelete="SET NULL"),
                                                       nullable=True)
    entregue_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoriaBot(Base):
    __tablename__ = "gs_bot_memorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    #: instrucao ("responda curto") | vocabulario ("PF = Porto Ferreira") | anotacao ("o Thiago cuida de Tietê")
    tipo: Mapped[str] = mapped_column(String(20))
    texto_cifrado: Mapped[str] = mapped_column(Text)
    #: bot | tela
    origem: Mapped[str] = mapped_column(String(20), default="bot", server_default="bot")
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    apagada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
