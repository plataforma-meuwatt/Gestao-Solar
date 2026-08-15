"""Permissões: o que o gestor concede, e o que o app pergunta.

Duas audiências no mesmo arquivo, de propósito — conceder e consultar têm de
falar do mesmo catálogo, e separá-las em módulos convidaria a duas listas de
permissões que divergem com o tempo.

**A permissão do gestor e a permissão do Android são coisas diferentes, e as
duas precisam existir.** O gestor decide se aquela pessoa *deve* receber avisos
de usina parada; o sistema operacional decide se o aplicativo *pode* mostrar
aviso nenhum. Uma sem a outra não entrega nada, e é por isso que o app registra
o aparelho só depois de o Android autorizar, e o BFF só envia para quem tem a
concessão.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import gestor_atual, usuario_atual
from app.models.permissao import Dispositivo, Permissao
from app.models.user import User
from app.services import permissoes as catalogo

router = APIRouter(tags=["permissões"])


# ── formato ─────────────────────────────────────────────────────────────────


class ItemOut(BaseModel):
    categoria: str
    categoria_rotulo: str
    subcategoria: str
    rotulo: str
    descricao: str
    #: Só preenchido nas rotas por usuário; no catálogo puro não há a quem se referir.
    concedida: bool | None = None


class MinhasPermissoesOut(BaseModel):
    #: Só o que ESTA pessoa tem. O app não recebe o catálogo inteiro: saber que existe
    #: uma permissão que ele não tem não muda nada na tela e vaza o roadmap.
    permissoes: list[str] = []


class DispositivoIn(BaseModel):
    #: `ExponentPushToken[...]`, vindo do `expo-notifications`.
    token: str = Field(min_length=10, max_length=255)
    plataforma: str | None = Field(default=None, max_length=16)
    versao_app: str | None = Field(default=None, max_length=32)


class PermissoesIn(BaseModel):
    #: A lista COMPLETA do que a pessoa deve ter, no formato `categoria.subcategoria`.
    #: É substituição, não acréscimo: mandar a lista inteira evita o par
    #: conceder/revogar e o estado intermediário em que a tela e o banco discordam.
    permissoes: list[str] = []


# ── app ─────────────────────────────────────────────────────────────────────


@router.get("/api/v1/me/permissoes", response_model=MinhasPermissoesOut)
def minhas_permissoes(
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> MinhasPermissoesOut:
    """O que esta pessoa pode receber. Lista vazia = nada foi concedido."""
    pares = catalogo.permissoes_do_usuario(db, usuario)
    return MinhasPermissoesOut(permissoes=sorted(f"{c}.{s}" for c, s in pares))


@router.post("/api/v1/me/dispositivos", status_code=204)
def registrar_dispositivo(
    corpo: DispositivoIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> None:
    """Registra (ou reencosta) o aparelho desta pessoa para receber push.

    O mesmo token pode reaparecer sob OUTRO usuário: aparelho emprestado, ou dois
    logins no mesmo celular. Nesse caso o dono muda — quem está logado agora é quem
    recebe. Criar uma segunda linha faria o aparelho receber os avisos dos dois.
    """
    existente = db.scalar(select(Dispositivo).where(Dispositivo.token == corpo.token))
    agora = datetime.now(UTC)

    if existente is None:
        db.add(
            Dispositivo(
                user_id=usuario.id,
                token=corpo.token,
                plataforma=corpo.plataforma,
                versao_app=corpo.versao_app,
                visto_em=agora,
            )
        )
    else:
        existente.user_id = usuario.id
        existente.plataforma = corpo.plataforma or existente.plataforma
        existente.versao_app = corpo.versao_app or existente.versao_app
        existente.visto_em = agora
    db.commit()


@router.delete("/api/v1/me/dispositivos/{token}", status_code=204)
def esquecer_dispositivo(
    token: str,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> None:
    """Chamado no logout. Sem isto, o celular continuaria recebendo avisos de uma
    conta que já saiu — inclusive depois de outra pessoa entrar nele."""
    db.execute(
        delete(Dispositivo).where(
            Dispositivo.token == token, Dispositivo.user_id == usuario.id
        )
    )
    db.commit()


# ── painel ──────────────────────────────────────────────────────────────────


@router.get("/api/painel/permissoes/catalogo", response_model=list[ItemOut])
def listar_catalogo(_: User = Depends(gestor_atual)) -> list[ItemOut]:
    """Tudo que pode ser concedido. É a fonte da tela do painel."""
    return [
        ItemOut(
            categoria=i.categoria,
            categoria_rotulo=catalogo.CATEGORIAS.get(i.categoria, i.categoria),
            subcategoria=i.subcategoria,
            rotulo=i.rotulo,
            descricao=i.descricao,
        )
        for i in catalogo.CATALOGO
    ]


@router.get("/api/painel/clientes/{cliente_id}/permissoes", response_model=list[ItemOut])
def permissoes_do_cliente(
    cliente_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> list[ItemOut]:
    """O catálogo inteiro, marcando o que este cliente já tem.

    Devolver o catálogo inteiro, e não só o concedido, é o que permite à tela
    desenhar as chaves desligadas — uma lista só com o concedido não teria como
    mostrar o que falta conceder.
    """
    cliente = db.get(User, cliente_id)
    if cliente is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    tem = catalogo.permissoes_do_usuario(db, cliente)
    return [
        ItemOut(
            categoria=i.categoria,
            categoria_rotulo=catalogo.CATEGORIAS.get(i.categoria, i.categoria),
            subcategoria=i.subcategoria,
            rotulo=i.rotulo,
            descricao=i.descricao,
            concedida=(i.categoria, i.subcategoria) in tem,
        )
        for i in catalogo.CATALOGO
    ]


@router.put("/api/painel/clientes/{cliente_id}/permissoes", status_code=204)
def definir_permissoes(
    cliente_id: int,
    corpo: PermissoesIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(gestor_atual),
) -> None:
    """Substitui as permissões do cliente pela lista enviada."""
    cliente = db.get(User, cliente_id)
    if cliente is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")

    desejadas: set[tuple[str, str]] = set()
    for chave in corpo.permissoes:
        categoria, _, subcategoria = chave.partition(".")
        # Recusa o que não está no catálogo em vez de gravar calado. Gravar criaria
        # uma linha que nenhuma checagem consulta — o gestor veria a chave ligada e o
        # cliente não receberia nada, que é a pior combinação possível.
        if catalogo.item(categoria, subcategoria) is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Permissão desconhecida: {chave!r}."
            )
        desejadas.add((categoria, subcategoria))

    atuais = catalogo.permissoes_do_usuario(db, cliente)

    for categoria, subcategoria in atuais - desejadas:
        db.execute(
            delete(Permissao).where(
                Permissao.user_id == cliente.id,
                Permissao.categoria == categoria,
                Permissao.subcategoria == subcategoria,
            )
        )
    for categoria, subcategoria in desejadas - atuais:
        db.add(
            Permissao(
                user_id=cliente.id,
                categoria=categoria,
                subcategoria=subcategoria,
                concedida_por=gestor.id,
            )
        )
    db.commit()
