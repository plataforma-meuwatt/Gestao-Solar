"""A ponte do Gestão Solar com cada produto.

Antes isto vivia no `.env` (`MEUWATT_SERVICE_PASSWORD` e companhia). Passou para o banco
por um motivo prático: quem configura é o gestor, pela tela, e ele precisa **testar** —
digitar, ver se responde, corrigir. Um segredo em variável de ambiente exige redeploy a
cada tentativa.

Hoje a ponte se estabelece por **token pessoal**: alguém gera um token na própria conta
do meuWatt e do meuPlano e cola aqui. É melhor que usuário e senha em três pontos que
importam — o BFF nunca vê a senha de ninguém, trocar a senha lá não derruba a integração,
e o acesso é revogável do lado de origem, por quem o emitiu, sem depender deste sistema.

As colunas `usuario_servico` / `senha_cifrada` continuam existindo para as conexões
gravadas antes disso. Elas são o caminho antigo: funcionam, mas a tela empurra para o
token e não oferece mais criar uma conexão por senha.

Nem senha nem token são lidos de volta pela tela. Entram, são cifrados e somem; o painel
mostra o prefixo do token, de quem ele é, e o resultado do último teste.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Produto(StrEnum):
    MEUWATT = "meuwatt"
    MEUPLANO = "meuplano"


class EstadoTeste(StrEnum):
    NUNCA = "nunca"
    OK = "ok"
    FALHOU = "falhou"


class Integracao(Base):
    """Uma linha por produto conectado. `produto` é a chave — não há duas do mesmo."""

    __tablename__ = "gs_integracoes"

    # Dois índices, e não um `UniqueConstraint(produto, empresa_id)`: no Postgres dois
    # NULL não colidem, então o único composto deixaria passar DUAS linhas de plataforma
    # para o mesmo produto — que é exatamente a ambiguidade que ele deveria impedir.
    __table_args__ = (
        Index(
            "uq_gs_integracao_empresa",
            "produto",
            "empresa_id",
            unique=True,
            postgresql_where=text("empresa_id IS NOT NULL"),
            sqlite_where=text("empresa_id IS NOT NULL"),
        ),
        Index(
            "uq_gs_integracao_plataforma",
            "produto",
            unique=True,
            postgresql_where=text("empresa_id IS NULL"),
            sqlite_where=text("empresa_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Uma linha por (produto, empresa) — e a unicidade mora em dois índices parciais,
    #: declarados em `__table_args__`. O `unique=True` que estava aqui era de quando
    #: existia UMA credencial por produto no sistema inteiro: com ele, a segunda empresa
    #: não conseguia gravar a conta dela, e o erro chegava como violação de constraint.
    produto: Mapped[Produto] = mapped_column(
        Enum(Produto, native_enum=False, length=20), index=True
    )

    #: De qual empresa é esta credencial. **Nulo = da plataforma**, que é o caso de hoje:
    #: um token de serviço lê o meuWatt e o meuPlano para todo mundo.
    #:
    #: A coluna entra sem uso de propósito. A pergunta "cada O&M usa a conta dela nos
    #: produtos, ou a da plataforma?" ainda não tem resposta, e com ela as duas cabem;
    #: sem ela, a segunda resposta vira migração no meio do caminho.
    empresa_id: Mapped[int | None] = mapped_column(
        ForeignKey("gs_empresas.id", ondelete="RESTRICT"), index=True, nullable=True
    )

    base_url: Mapped[str] = mapped_column(String(500))

    # ── caminho antigo: conta de serviço com senha ──────────────────────────────
    # Anuláveis desde que o token existe: uma conexão nova não tem usuário nem senha.
    usuario_servico: Mapped[str | None] = mapped_column(String(255), nullable=True)
    senha_cifrada: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── caminho atual: token pessoal colado pelo gestor ─────────────────────────
    token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `mw_pat_a1b2`, em claro. É por ele que o gestor confere se o token gravado aqui é
    #: o mesmo que ele vê na lista do produto — sem isso, "qual dos meus tokens é este?"
    #: não tem resposta, e revogar vira tentativa e erro.
    token_prefixo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: De quem é o token, respondido pelo próprio produto no momento em que foi gravado.
    #: Colar o token da pessoa errada é um engano silencioso: a conexão fica verde e o
    #: escopo de usinas vem menor, o que só aparece semanas depois como usina faltando.
    token_dono_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_dono_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_gravado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    # Resultado do último teste. Guardado para o painel abrir já dizendo o estado, sem
    # bater nos upstreams a cada carregamento de página.
    estado: Mapped[EstadoTeste] = mapped_column(
        Enum(EstadoTeste, native_enum=False, length=20), default=EstadoTeste.NUNCA
    )
    testada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detalhe_teste: Mapped[str | None] = mapped_column(Text, nullable=True)
    usinas_visiveis: Mapped[int | None] = mapped_column(nullable=True)

    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def por_token(self) -> bool:
        """A conexão nova. `False` = linha antiga, ainda por usuário e senha."""
        return bool(self.token_cifrado)


class IntegracaoEvento(Base):
    """O que aconteceu com cada ponte, em ordem.

    O estado guardado na `Integracao` responde "está funcionando agora?". Esta tabela
    responde a outra pergunta, que só aparece quando algo quebra: "desde quando, e o que
    mudou antes disso?". Sem ela, um token trocado por engano na quinta-feira é
    indistinguível de um produto que saiu do ar — os dois aparecem como o mesmo cartão
    vermelho, e a conversa vira memória de quem mexeu.

    Append-only por convenção: nada no código atualiza ou apaga uma linha daqui.
    """

    __tablename__ = "gs_integracao_eventos"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto: Mapped[Produto] = mapped_column(
        Enum(Produto, native_enum=False, length=20), index=True
    )
    #: token_gravado | token_removido | teste_ok | teste_falhou | senha_gravada
    evento: Mapped[str] = mapped_column(String(30))
    ocorrido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    #: Quem mexeu, do lado do Gestão Solar.
    ator_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Qual token estava em jogo — nunca o valor, só o prefixo.
    token_prefixo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    usinas_visiveis: Mapped[int | None] = mapped_column(Integer, nullable=True)
