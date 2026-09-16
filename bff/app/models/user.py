"""Quem usa o Gestão Solar.

Uma tabela só para cliente e gestor: os dois entram com apelido e senha, e o que muda é o
`perfil`. Separar em duas tabelas duplicaria autenticação, senha e sessão para ganhar
nada — a diferença entre eles é o que a tela abre, não como entram.

Quem autentica é o **apelido**, não o e-mail (ver `core/apelido.py`). O motivo é concreto:
a mesma pessoa pode ser o gestor do sistema e, separadamente, o dono de uma usina que ele
atende. São dois papéis, dois conjuntos de poderes e duas contas — e com o e-mail como
chave a segunda seria recusada como duplicada.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.plant import PlantLink


class Perfil(StrEnum):
    """O que a conta abre.

    `cliente` entra no app e vê as usinas dele. `atendimento` abre o painel e cuida de
    cliente e diagnóstico. `administrador` faz tudo, inclusive mexer nas pontes com os
    produtos e na própria equipe — é a conta que, se comprometida, dá acesso às
    credenciais de serviço dos dois sistemas.
    """

    CLIENTE = "cliente"
    ATENDIMENTO = "atendimento"
    ADMINISTRADOR = "administrador"


class User(Base):
    __tablename__ = "gs_users"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Como esta conta entra. Único, minúsculo, validado em `core/apelido.py`.
    apelido: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    #: Contato — e, no cliente, a chave que acha a conta dele no meuWatt e no meuPlano.
    #: Opcional porque não é o que autentica: uma conta de gestor pode não ter e-mail
    #: próprio, e duas contas da mesma pessoa podem compartilhar o mesmo.
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    nome: Mapped[str] = mapped_column(String(255))
    empresa: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Em E.164 (`+5516999998888`), normalizado em `core/telefone.py` — um número, um
    #: formato. É para onde as notificações vão; sem ele não há destino.
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Quando o gestor registrou que o cliente aceitou receber mensagens no WhatsApp. A
    #: autorização é a cláusula do contrato; esta coluna é o registro de que ela existe.
    #: Nulo = não recebe nada, por mais que esteja marcado na central.
    whatsapp_aceite_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    whatsapp_aceite_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    perfil: Mapped[Perfil] = mapped_column(
        Enum(Perfil, native_enum=False, length=20), default=Perfil.CLIENTE
    )

    senha_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Enquanto verdadeiro, o app leva o cliente para a troca de senha antes de qualquer
    # tela. É o que fecha o ciclo da senha provisória entregue pelo gestor.
    trocar_senha: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Espelho do `AppUser.nivel_acesso` do meuPlano (0-5), usado para decidir se o
    # assistente pode revelar uma credencial. Fonte da verdade continua sendo lá.
    nivel_acesso: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    acessos: Mapped[list["UserPlantAccess"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )
    # `foreign_keys` é obrigatório aqui: VinculoProduto aponta duas vezes para gs_users —
    # o cliente dono do vínculo e o gestor que o criou. Sem isto o SQLAlchemy não sabe
    # qual das duas define a relação.
    vinculos: Mapped[list["VinculoProduto"]] = relationship(
        back_populates="usuario",
        cascade="all, delete-orphan",
        foreign_keys="VinculoProduto.gs_user_id",
    )

    @property
    def identificacao(self) -> str:
        """Como esta conta aparece num registro de auditoria.

        Prefere o e-mail, que alcança a pessoa fora do sistema; cai no apelido quando não
        há e-mail, para a linha do histórico nunca ficar sem autor.
        """
        return self.email or self.apelido

    @property
    def abre_painel(self) -> bool:
        return self.perfil in (Perfil.ATENDIMENTO, Perfil.ADMINISTRADOR)

    @property
    def e_administrador(self) -> bool:
        return self.perfil is Perfil.ADMINISTRADOR


class VinculoProduto(Base):
    """A conta deste cliente em cada produto — e o token com que se lê por ela.

    Guarda o e-mail e o nome de lá junto do id: o painel precisa mostrar *quem* foi
    vinculado sem ir buscar no upstream a cada carregamento de tela, e o registro
    continua legível mesmo se a conta sumir de lá.

    O token é o que faz desta linha um vínculo PROVADO em vez de digitado. O gestor não
    afirma mais "este cliente é aquela conta": ele apresenta o token da pessoa, o produto
    responde de quem ele é, e o `usuario_remoto_id` vem dessa resposta. Um engano de
    digitação deixou de ser possível — o que resta é colar o token de outra pessoa, e aí
    o nome que aparece na tela é o dela.

    Da mesma linha saem duas consequências que vale a pena distinguir:

    * **ler** — o BFF chama os produtos com este token, como o cliente, e recebe
      exatamente o escopo que ele teria lá. É o que substitui as rotas administrativas de
      "quais usinas o usuário N vê", que só conheciam concessões explícitas e por isso
      mentiam sobre quem enxerga usina pela regra da organização.
    * **entrar** — o produto grava que esta conta do Gestão Solar é aquele usuário dele e
      passa a aceitar "Entrar com Gestão Solar". `login_externo_em` marca quando isso foi
      confirmado; fica nulo quando o token serve para ler mas o registro da identidade
      ainda não aconteceu — o produto estava fora do ar, por exemplo.
    """

    __tablename__ = "gs_vinculos_produto"
    __table_args__ = (UniqueConstraint("gs_user_id", "produto", name="uq_usuario_produto"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    produto: Mapped[str] = mapped_column(String(20))

    usuario_remoto_id: Mapped[str] = mapped_column(String(64))
    usuario_remoto_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usuario_remoto_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── o token do próprio cliente ──────────────────────────────────────────────
    #: Cifrado (Fernet). Entra, some, e nunca volta pela tela — nem para quem o colou.
    #: Quem precisar dele de novo gera outro no produto.
    token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `mw_pat_a1b2`, em claro. É por ele que se reconhece, na lista de tokens do produto,
    #: qual é este — sem isso, revogar o token certo vira tentativa e erro.
    token_prefixo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    token_gravado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── resultado do último teste ───────────────────────────────────────────────
    #: `nunca` | `ok` | `falhou`. Guardado para a ficha do cliente abrir já dizendo o
    #: estado, sem bater nos dois upstreams a cada carregamento.
    estado: Mapped[str] = mapped_column(String(20), default="nunca", server_default="nunca")
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    usinas_visiveis: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Quando o produto confirmou que aceita o login desta conta do Gestão Solar.
    login_externo_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    vinculado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    vinculado_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )

    usuario: Mapped["User"] = relationship(back_populates="vinculos", foreign_keys=[gs_user_id])

    @property
    def conectado(self) -> bool:
        """Tem token gravado — o BFF consegue ler os produtos como este cliente."""
        return bool(self.token_cifrado)

    @property
    def login_externo(self) -> bool:
        """O produto aceita "Entrar com Gestão Solar" para esta conta."""
        return self.login_externo_em is not None


class SenhaProvisoria(Base):
    """Registro de que um acesso foi entregue — não a senha.

    A senha só existe no `senha_hash` do usuário e no momento em que o painel a exibe.
    Esta tabela responde a pergunta operacional: "entreguei o acesso a este cliente? ele
    já usou?" — que é o que evita cobrar alguém que nunca recebeu nada.
    """

    __tablename__ = "gs_senhas_provisorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    gs_user_id: Mapped[int] = mapped_column(
        ForeignKey("gs_users.id", ondelete="CASCADE"), index=True
    )
    gerada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    gerada_por: Mapped[int | None] = mapped_column(
        ForeignKey("gs_users.id", ondelete="SET NULL"), nullable=True
    )
    usada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserPlantAccess(Base):
    """A que usinas este usuário tem direito.

    Para cliente, é o que o gestor definiu no painel — e uma usina só pode estar em um
    cliente (a regra é aplicada no serviço, não no banco, para a mensagem de erro poder
    dizer de quem é a usina).
    """

    __tablename__ = "gs_user_plant_access"
    __table_args__ = (UniqueConstraint("user_id", "plant_link_id", name="uq_user_plant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("gs_users.id", ondelete="CASCADE"), index=True)
    plant_link_id: Mapped[int] = mapped_column(ForeignKey("gs_plant_links.id", ondelete="CASCADE"))
    concedido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    usuario: Mapped["User"] = relationship(back_populates="acessos")
    usina: Mapped["PlantLink"] = relationship()
