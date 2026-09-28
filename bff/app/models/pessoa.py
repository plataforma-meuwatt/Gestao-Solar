"""A pessoa — o humano por trás das contas.

Uma conta é um PAPEL, não uma pessoa: `renanmarquezini` administra a plataforma,
`renan.marquezini` é dono de usina, e os dois são o mesmo humano. Isso já era verdade
antes desta tabela (é por isso que quem autentica é o apelido e não o e-mail), mas o
sistema não sabia — cada conta vivia sozinha, e trocar de papel era sair e entrar de novo.

Esta tabela é só o agrupamento. **Ela não carrega poder nenhum**: nenhuma consulta de
autorização passa por aqui, e uma sessão continua sendo de UMA conta, com UM perfil e UM
escopo. Fundir os papéis numa sessão só seria desfazer a separação que o portão de cada
lado existe para garantir — e a tela não teria como dizer em que papel a pessoa está.

O que ela habilita é a troca: provada a senha de uma conta, as irmãs ficam ao alcance de
um clique (`services/pessoas.trocar`), com uma exceção deliberada — **subir para uma conta
da plataforma sempre pede a senha de novo**. Sem isso, uma sessão de app roubada viraria
uma sessão de administrador sem que ninguém precisasse saber nenhuma senha.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Pessoa(Base):
    """Um humano, com uma ou mais contas."""

    __tablename__ = "gs_pessoas"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Só para a tela dizer de quem são as contas. O nome que vale em cada tela continua
    #: sendo o da CONTA — um gerente pode assinar diferente do dono de usina.
    nome: Mapped[str] = mapped_column(String(255))
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
