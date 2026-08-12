"""Cadastro de cliente, vínculo com os produtos e concessão de usinas.

É o que o gestor faz no painel, do outro lado da tela. Três regras moram aqui e não podem
sair daqui:

1. **A senha provisória aparece uma vez.** É devolvida na resposta que a gera e nunca mais
   — nem por GET, nem por listagem. Se o gestor perder, gera outra.
2. **Uma usina tem um dono só.** Vincular a um segundo cliente é recusado com o nome de
   quem já a tem, porque o erro comum é cadastrar duas vezes o mesmo cliente com e-mails
   diferentes, e o sintoma seria dado de usina aparecendo para quem não deveria.
3. **O painel não cria conta nos produtos.** Ele vincula a conta que já existe lá.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import gerar_hash_senha, gerar_senha_provisoria
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import (
    Perfil,
    SenhaProvisoria,
    User,
    UserPlantAccess,
    VinculoProduto,
)
from app.services import integracoes


class RegraDeNegocio(Exception):
    """Erro que o gestor consegue corrigir sozinho — a mensagem vai direto para a tela."""


# --------------------------------------------------------------------- criar


@dataclass
class ClienteCriado:
    usuario: User
    senha_provisoria: str


def criar(
    db: Session, *, nome: str, email: str, empresa: str | None, criado_por: User
) -> ClienteCriado:
    email = email.strip().lower()

    if db.scalar(select(User).where(User.email == email)) is not None:
        raise RegraDeNegocio(f"Já existe uma conta com o e-mail {email}.")

    senha = gerar_senha_provisoria()
    usuario = User(
        email=email,
        nome=nome.strip(),
        empresa=(empresa or "").strip() or None,
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha(senha),
        trocar_senha=True,
    )
    db.add(usuario)
    db.flush()

    db.add(SenhaProvisoria(gs_user_id=usuario.id, gerada_por=criado_por.id))
    db.commit()
    db.refresh(usuario)

    return ClienteCriado(usuario=usuario, senha_provisoria=senha)


def regenerar_senha(db: Session, cliente: User, gerada_por: User) -> str:
    """Nova senha provisória. Invalida a anterior por consequência — o hash é substituído."""
    senha = gerar_senha_provisoria()
    cliente.senha_hash = gerar_hash_senha(senha)
    cliente.trocar_senha = True
    db.add(SenhaProvisoria(gs_user_id=cliente.id, gerada_por=gerada_por.id))
    db.commit()
    return senha


def situacao_acesso(db: Session, cliente: User) -> str:
    """`nunca` · `entregue` · `usado` — o que a lista de clientes mostra na coluna Acesso."""
    ultima = db.scalar(
        select(SenhaProvisoria)
        .where(SenhaProvisoria.gs_user_id == cliente.id)
        .order_by(SenhaProvisoria.gerada_em.desc())
        .limit(1)
    )
    if ultima is None:
        return "nunca"
    if cliente.ultimo_login is not None and cliente.ultimo_login > ultima.gerada_em:
        return "usado"
    return "entregue"


# ------------------------------------------------------------------ vínculos


async def procurar_usuario(db: Session, produto: Produto, email: str) -> dict[str, Any] | None:
    """Acha a conta daquele e-mail no produto.

    O meuPlano tem busca por e-mail; o meuWatt não tem — lá é preciso listar e filtrar
    aqui. Por isso a assimetria: não é escolha de projeto, é o que cada API oferece.
    """
    email = email.strip().lower()

    if produto is Produto.MEUPLANO:
        cliente = await integracoes.cliente_meuplano(db)
        achado = await cliente.procurar_usuario_por_email(email)
        if not achado:
            return None
        return {
            "id": str(achado.get("id")),
            "email": achado.get("email"),
            "nome": achado.get("name") or achado.get("nome"),
        }

    cliente_mw = await integracoes.cliente_meuwatt(db)
    for u in await cliente_mw.usuarios():
        if (u.get("email") or "").strip().lower() == email:
            return {"id": str(u.get("id")), "email": u.get("email"), "nome": u.get("name")}
    return None


def vincular(
    db: Session,
    cliente: User,
    produto: Produto,
    *,
    usuario_remoto_id: str,
    email: str | None,
    nome: str | None,
    por: User,
) -> VinculoProduto:
    vinculo = db.scalar(
        select(VinculoProduto).where(
            VinculoProduto.gs_user_id == cliente.id,
            VinculoProduto.produto == produto.value,
        )
    )
    if vinculo is None:
        vinculo = VinculoProduto(gs_user_id=cliente.id, produto=produto.value)
        db.add(vinculo)

    vinculo.usuario_remoto_id = usuario_remoto_id
    vinculo.usuario_remoto_email = email
    vinculo.usuario_remoto_nome = nome
    vinculo.vinculado_por = por.id
    vinculo.vinculado_em = datetime.now(UTC)
    db.commit()
    db.refresh(vinculo)
    return vinculo


def desvincular(db: Session, cliente: User, produto: Produto) -> None:
    vinculo = db.scalar(
        select(VinculoProduto).where(
            VinculoProduto.gs_user_id == cliente.id,
            VinculoProduto.produto == produto.value,
        )
    )
    if vinculo is not None:
        db.delete(vinculo)
        db.commit()


# -------------------------------------------------------------------- usinas


@dataclass
class UsinaSugerida:
    plant_link_id: int
    nome: str
    origem: list[str]
    ja_concedida: bool
    dono_atual: str | None


async def usinas_sugeridas(db: Session, cliente: User) -> list[UsinaSugerida]:
    """O que cada produto diz que aquele usuário vê, traduzido para as usinas do BFF.

    Sugestão, não decisão: o gestor confirma. E cada usina vem marcada com quem já é dono,
    para o conflito aparecer antes de tentar salvar.
    """
    vinculos = {
        v.produto: v
        for v in db.scalars(
            select(VinculoProduto).where(VinculoProduto.gs_user_id == cliente.id)
        ).all()
    }

    slugs_mw: set[str] = set()
    ids_mp: set[int] = set()

    if Produto.MEUWATT.value in vinculos:
        try:
            mw = await integracoes.cliente_meuwatt(db)
            slugs_mw = set(await mw.plantas_do_usuario(vinculos[Produto.MEUWATT.value].usuario_remoto_id))
        except Exception:  # noqa: BLE001 — a tela abre mesmo com uma ponte fora
            slugs_mw = set()

    if Produto.MEUPLANO.value in vinculos:
        try:
            mp = await integracoes.cliente_meuplano(db)
            ids_mp = set(await mp.usinas_do_usuario(vinculos[Produto.MEUPLANO.value].usuario_remoto_id))
        except Exception:  # noqa: BLE001
            ids_mp = set()

    concedidas = {
        a.plant_link_id
        for a in db.scalars(
            select(UserPlantAccess).where(UserPlantAccess.user_id == cliente.id)
        ).all()
    }
    donos = _donos_por_usina(db, exceto=cliente.id)

    saida: list[UsinaSugerida] = []
    for link in db.scalars(select(PlantLink).where(PlantLink.ativo)).all():
        origem = []
        if link.mw_plant_slug and link.mw_plant_slug in slugs_mw:
            origem.append("meuWatt")
        if link.mp_usina_id and link.mp_usina_id in ids_mp:
            origem.append("meuPlano")
        if not origem and link.id not in concedidas:
            continue
        saida.append(
            UsinaSugerida(
                plant_link_id=link.id,
                nome=link.nome,
                origem=origem,
                ja_concedida=link.id in concedidas,
                dono_atual=donos.get(link.id),
            )
        )
    return saida


def definir_usinas(db: Session, cliente: User, plant_link_ids: list[int]) -> None:
    """Substitui a lista inteira. Recusa a operação toda se qualquer usina for de outro —
    parcial deixaria o gestor sem saber o que entrou e o que não."""
    donos = _donos_por_usina(db, exceto=cliente.id)
    conflitos = [
        f"“{db.get(PlantLink, pid).nome}” já é de {donos[pid]}"
        for pid in plant_link_ids
        if pid in donos
    ]
    if conflitos:
        raise RegraDeNegocio(
            "Cada usina pertence a um cliente só. " + "; ".join(conflitos) + "."
        )

    atuais = {
        a.plant_link_id: a
        for a in db.scalars(
            select(UserPlantAccess).where(UserPlantAccess.user_id == cliente.id)
        ).all()
    }
    desejadas = set(plant_link_ids)

    for pid, acesso in atuais.items():
        if pid not in desejadas:
            db.delete(acesso)
    for pid in desejadas - set(atuais):
        db.add(UserPlantAccess(user_id=cliente.id, plant_link_id=pid))

    db.commit()


def _donos_por_usina(db: Session, exceto: int) -> dict[int, str]:
    """Mapa usina → nome do cliente dono, ignorando o cliente em edição."""
    linhas = db.execute(
        select(UserPlantAccess.plant_link_id, User.nome)
        .join(User, User.id == UserPlantAccess.user_id)
        .where(UserPlantAccess.user_id != exceto, User.perfil == Perfil.CLIENTE)
    ).all()
    return {pid: nome for pid, nome in linhas}


def contar_usinas(db: Session) -> dict[int, int]:
    """Quantas usinas cada cliente tem — numa query só, para a lista não fazer N+1."""
    linhas = db.execute(
        select(UserPlantAccess.user_id, func.count(UserPlantAccess.id)).group_by(
            UserPlantAccess.user_id
        )
    ).all()
    return {uid: total for uid, total in linhas}
