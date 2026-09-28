"""A empresa de O&M — o inquilino do sistema, e o VÍNCULO entre os dois produtos.

Até aqui o Gestão Solar era de um inquilino só: a operação de quem o construiu. Usina,
integração e conversa não tinham dono, e `gs_users.empresa` era **texto livre** — com o
qual nada pode ser filtrado, porque "Splendor O&M" e "Splendor OM" são a mesma empresa
para o olho e duas para o banco.

**O nulo é a plataforma.** Conta de `atendimento` ou `administrador` não pertence a
empresa nenhuma: `empresa_id` nulo diz isso, e não "vê todas". Quem decide o alcance é o
perfil, e a leitura acontece num lugar só — `services/empresas.no_escopo`. Espalhar
`if empresa_id is None` pelas consultas seria reescrever a regra em cada uma delas, e é
na cópia esquecida que o dado do vizinho aparece.

**Desligar não apaga.** `ativa` tira a empresa de operação preservando usina, cliente e
histórico. Apagar linha de empresa levaria junto o que outra pessoa precisa auditar.

## O cadastro NÃO nasce aqui — ele é casado aqui

O meuWatt tem `enterprises` (com usina e funcionário pendurados nela) e o meuPlano tem
`tenants`. **Os dois são independentes, e é assim de propósito**: alguém pode contratar só
a manutenção e nunca existir no monitoramento. Nenhum dos dois é "o certo".

O que falta, e é o que esta tabela faz, é dizer **que aquela empresa de lá e aquela de lá
são a mesma, e é esta aqui**. É exatamente o papel de `gs_plant_links` para usinas, com os
mesmos três casos: nos dois produtos, só no meuWatt, só no meuPlano.

**Corolário do dado morto** (o mesmo do `CLAUDE.md`): uma empresa sem nenhum dos dois
vínculos é fantasma — ela aparece na lista e todas as telas dela vêm vazias, porque não há
upstream de onde ler. Ter só um dos dois é legítimo; ter nenhum não é.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Empresa(Base):
    """Uma empresa de O&M que opera dentro da plataforma."""

    __tablename__ = "gs_empresas"

    # Únicos PARCIAIS, como em `gs_integracoes`: no Postgres dois NULL não colidem, então
    # um `unique=True` na coluna bastaria — mas o índice parcial diz a intenção por
    # escrito, e é o mesmo desenho já usado na tabela vizinha.
    __table_args__ = (
        Index(
            "uq_gs_empresa_mw",
            "mw_enterprise_id",
            unique=True,
            postgresql_where=text("mw_enterprise_id IS NOT NULL"),
            sqlite_where=text("mw_enterprise_id IS NOT NULL"),
        ),
        Index(
            "uq_gs_empresa_mp",
            "mp_tenant_id",
            unique=True,
            postgresql_where=text("mp_tenant_id IS NOT NULL"),
            sqlite_where=text("mp_tenant_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Como a empresa se chama para quem a atende. Único: duas linhas com o mesmo nome
    #: são o mesmo cadastro feito duas vezes, e foi exatamente isso que o texto livre
    #: em `gs_users.empresa` permitia.
    nome: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    #: CNPJ, quando houver. Não é a chave: empresa nova costuma ser cadastrada antes de
    #: alguém procurar o documento, e uma obrigatoriedade aqui adiaria o cadastro.
    documento: Mapped[str | None] = mapped_column(String(20), nullable=True)

    #: A empresa no meuWatt (`enterprises.id`). Única: duas linhas daqui apontando para a
    #: mesma empresa de lá seriam dois inquilinos lendo a mesma carteira.
    mw_enterprise_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    #: A empresa no meuPlano (`tenants.id`). Também única, e independente da de cima: os
    #: dois cadastros não se conhecem, e quem diz que são a mesma empresa é esta linha.
    mp_tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
