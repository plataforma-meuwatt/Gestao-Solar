"""Gestão de clientes, equipe e diagnóstico.

O caminho que o gestor percorre: cadastra o cliente, vincula as contas dele nos dois
produtos, escolhe as usinas, copia a senha provisória e confere no diagnóstico que o dado
chega certo dos dois lados.

A senha provisória aparece **uma vez**, na resposta que a gera. Nenhum GET aqui a devolve.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.apelido import ApelidoInvalido
from app.core.apelido import normalizar as normalizar_apelido
from app.core.db import get_db
from app.core.security import administrador_atual, gerar_hash_senha, gestor_atual
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess, VinculoProduto
from app.services import clientes as svc
from app.services import integracoes

router = APIRouter(prefix="/api/painel", tags=["painel · clientes"])


def _cliente(db: Session, cliente_id: int) -> User:
    usuario = db.get(User, cliente_id)
    if usuario is None or usuario.perfil is not Perfil.CLIENTE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado")
    return usuario


# ---------------------------------------------------------------- listagem


class VinculoOut(BaseModel):
    produto: str
    usuario_remoto_id: str
    email: str | None = None
    nome: str | None = None
    vinculado_em: datetime


class ClienteResumo(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    empresa: str | None = None
    ativo: bool
    usinas: int
    produtos: list[str]
    acesso: str


@router.get("/clientes", response_model=list[ClienteResumo])
def listar_clientes(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[ClienteResumo]:
    lista = db.scalars(
        select(User).where(User.perfil == Perfil.CLIENTE).order_by(User.nome)
    ).all()
    totais = svc.contar_usinas(db)

    vinculos: dict[int, list[str]] = {}
    for v in db.scalars(select(VinculoProduto)).all():
        vinculos.setdefault(v.gs_user_id, []).append(v.produto)

    return [
        ClienteResumo(
            id=c.id,
            nome=c.nome,
            apelido=c.apelido,
            email=c.email,
            empresa=c.empresa,
            ativo=c.ativo,
            usinas=totais.get(c.id, 0),
            produtos=sorted(vinculos.get(c.id, [])),
            acesso=svc.situacao_acesso(db, c),
        )
        for c in lista
    ]


# ------------------------------------------------------------------- criar


class ClienteIn(BaseModel):
    nome: str = Field(min_length=2)
    #: Com o que ele entra no aplicativo. Não precisa parecer com o e-mail.
    apelido: str = Field(min_length=3)
    #: Continua sendo pedido porque é a chave que acha a conta dele no meuWatt e no
    #: meuPlano — sem ele o vínculo com os produtos vira busca manual. Mas não autentica.
    email: EmailStr | None = None
    empresa: str | None = None


class ClienteCriadoOut(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    # Aparece só aqui, uma vez. Nenhum outro endpoint devolve isto.
    senha_provisoria: str


@router.post("/clientes", response_model=ClienteCriadoOut, status_code=201)
def criar_cliente(
    body: ClienteIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(gestor_atual),
) -> ClienteCriadoOut:
    try:
        criado = svc.criar(
            db,
            nome=body.nome,
            apelido=body.apelido,
            email=str(body.email) if body.email else None,
            empresa=body.empresa,
            criado_por=gestor,
        )
    except svc.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return ClienteCriadoOut(
        id=criado.usuario.id,
        nome=criado.usuario.nome,
        apelido=criado.usuario.apelido,
        email=criado.usuario.email,
        senha_provisoria=criado.senha_provisoria,
    )


class SenhaOut(BaseModel):
    senha_provisoria: str


@router.post("/clientes/{cliente_id}/senha", response_model=SenhaOut)
def regenerar_senha(
    cliente_id: int,
    db: Session = Depends(get_db),
    gestor: User = Depends(gestor_atual),
) -> SenhaOut:
    cliente = _cliente(db, cliente_id)
    return SenhaOut(senha_provisoria=svc.regenerar_senha(db, cliente, gestor))


# ----------------------------------------------------------------- detalhe


class UsinaDoCliente(BaseModel):
    plant_link_id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    tem_meuwatt: bool
    tem_meuplano: bool


class ClienteDetalhe(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    empresa: str | None = None
    ativo: bool
    acesso: str
    trocar_senha: bool
    ultimo_login: datetime | None = None
    vinculos: list[VinculoOut]
    usinas: list[UsinaDoCliente]


@router.get("/clientes/{cliente_id}", response_model=ClienteDetalhe)
def detalhe_cliente(
    cliente_id: int, db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> ClienteDetalhe:
    cliente = _cliente(db, cliente_id)

    usinas = db.scalars(
        select(PlantLink)
        .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
        .where(UserPlantAccess.user_id == cliente.id)
        .order_by(PlantLink.nome)
    ).all()

    return ClienteDetalhe(
        id=cliente.id,
        nome=cliente.nome,
        apelido=cliente.apelido,
        email=cliente.email,
        empresa=cliente.empresa,
        ativo=cliente.ativo,
        acesso=svc.situacao_acesso(db, cliente),
        trocar_senha=cliente.trocar_senha,
        ultimo_login=cliente.ultimo_login,
        vinculos=[
            VinculoOut(
                produto=v.produto,
                usuario_remoto_id=v.usuario_remoto_id,
                email=v.usuario_remoto_email,
                nome=v.usuario_remoto_nome,
                vinculado_em=v.vinculado_em,
            )
            for v in cliente.vinculos
        ],
        usinas=[
            UsinaDoCliente(
                plant_link_id=u.id,
                nome=u.nome,
                cidade=u.cidade,
                uf=u.uf,
                tem_meuwatt=u.tem_meuwatt,
                tem_meuplano=u.tem_meuplano,
            )
            for u in usinas
        ],
    )


class ClientePatch(BaseModel):
    nome: str | None = None
    empresa: str | None = None
    ativo: bool | None = None


@router.patch("/clientes/{cliente_id}", response_model=ClienteResumo)
def editar_cliente(
    cliente_id: int,
    body: ClientePatch,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> ClienteResumo:
    cliente = _cliente(db, cliente_id)
    if body.nome is not None:
        cliente.nome = body.nome.strip()
    if body.empresa is not None:
        cliente.empresa = body.empresa.strip() or None
    if body.ativo is not None:
        cliente.ativo = body.ativo
    db.commit()

    return ClienteResumo(
        id=cliente.id,
        nome=cliente.nome,
        apelido=cliente.apelido,
        email=cliente.email,
        empresa=cliente.empresa,
        ativo=cliente.ativo,
        usinas=svc.contar_usinas(db).get(cliente.id, 0),
        produtos=sorted(v.produto for v in cliente.vinculos),
        acesso=svc.situacao_acesso(db, cliente),
    )


# ---------------------------------------------------------------- vínculos


class UsuarioRemotoOut(BaseModel):
    id: str
    email: str | None = None
    nome: str | None = None


@router.get("/produtos/{produto}/usuarios", response_model=UsuarioRemotoOut | None)
async def procurar_usuario(
    produto: Produto,
    email: str,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> UsuarioRemotoOut | None:
    """Acha a conta daquele e-mail no produto. `null` quer dizer que não existe lá — o
    gestor segue sem vincular, e a aba correspondente fica vazia no app."""
    try:
        achado = await svc.procurar_usuario(db, produto, email)
    except Exception as exc:  # noqa: BLE001 — o motivo real ajuda o gestor
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return UsuarioRemotoOut(**achado) if achado else None


class VincularIn(BaseModel):
    usuario_remoto_id: str
    email: str | None = None
    nome: str | None = None


@router.put("/clientes/{cliente_id}/vinculos/{produto}", response_model=VinculoOut)
def vincular_produto(
    cliente_id: int,
    produto: Produto,
    body: VincularIn,
    db: Session = Depends(get_db),
    gestor: User = Depends(gestor_atual),
) -> VinculoOut:
    cliente = _cliente(db, cliente_id)
    v = svc.vincular(
        db,
        cliente,
        produto,
        usuario_remoto_id=body.usuario_remoto_id,
        email=body.email,
        nome=body.nome,
        por=gestor,
    )
    return VinculoOut(
        produto=v.produto,
        usuario_remoto_id=v.usuario_remoto_id,
        email=v.usuario_remoto_email,
        nome=v.usuario_remoto_nome,
        vinculado_em=v.vinculado_em,
    )


@router.delete("/clientes/{cliente_id}/vinculos/{produto}", status_code=204)
def desvincular_produto(
    cliente_id: int,
    produto: Produto,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> None:
    svc.desvincular(db, _cliente(db, cliente_id), produto)


# ------------------------------------------------------------------ usinas


class UsinaSugeridaOut(BaseModel):
    plant_link_id: int
    nome: str
    origem: list[str]
    ja_concedida: bool
    dono_atual: str | None = None


@router.get("/clientes/{cliente_id}/usinas-sugeridas", response_model=list[UsinaSugeridaOut])
async def sugerir_usinas(
    cliente_id: int, db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[UsinaSugeridaOut]:
    cliente = _cliente(db, cliente_id)
    return [
        UsinaSugeridaOut(
            plant_link_id=u.plant_link_id,
            nome=u.nome,
            origem=u.origem,
            ja_concedida=u.ja_concedida,
            dono_atual=u.dono_atual,
        )
        for u in await svc.usinas_sugeridas(db, cliente)
    ]


class UsinasIn(BaseModel):
    plant_link_ids: list[int]


@router.put("/clientes/{cliente_id}/usinas", status_code=204)
def definir_usinas(
    cliente_id: int,
    body: UsinasIn,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> None:
    try:
        svc.definir_usinas(db, _cliente(db, cliente_id), body.plant_link_ids)
    except svc.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# -------------------------------------------------------------- diagnóstico


class BlocoDiagnostico(BaseModel):
    ok: bool
    detalhe: str
    itens: list[dict] = []


class DiagnosticoOut(BaseModel):
    cliente: str
    usinas: list[UsinaDoCliente]
    meuwatt: BlocoDiagnostico
    meuplano: BlocoDiagnostico


@router.get("/clientes/{cliente_id}/diagnostico", response_model=DiagnosticoOut)
async def diagnostico(
    cliente_id: int, db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> DiagnosticoOut:
    """Responde "o dado está chegando certo dos dois lados?" sem precisar abrir o app.

    Cada bloco falha sozinho: uma ponte fora não impede ver a outra, e o erro real aparece
    em vez de uma tela vazia.
    """
    cliente = _cliente(db, cliente_id)
    usinas = db.scalars(
        select(PlantLink)
        .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
        .where(UserPlantAccess.user_id == cliente.id)
        .order_by(PlantLink.nome)
    ).all()

    mw = await _diagnostico_meuwatt(db, usinas)
    mp = await _diagnostico_meuplano(db, usinas)

    return DiagnosticoOut(
        cliente=cliente.nome,
        usinas=[
            UsinaDoCliente(
                plant_link_id=u.id,
                nome=u.nome,
                cidade=u.cidade,
                uf=u.uf,
                tem_meuwatt=u.tem_meuwatt,
                tem_meuplano=u.tem_meuplano,
            )
            for u in usinas
        ],
        meuwatt=mw,
        meuplano=mp,
    )


async def _diagnostico_meuwatt(db: Session, usinas: list[PlantLink]) -> BlocoDiagnostico:
    alvos = [u for u in usinas if u.mw_plant_slug]
    if not alvos:
        return BlocoDiagnostico(ok=False, detalhe="Nenhuma usina deste cliente existe no meuWatt.")

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001
        return BlocoDiagnostico(ok=False, detalhe=str(exc))

    hoje = date.today()
    itens = []
    for u in alvos:
        try:
            diario = await cliente.geracao_diaria(u.mw_plant_slug, hoje)
            itens.append(
                {
                    "usina": u.nome,
                    "origem": f"GET /plants/{u.mw_plant_slug}/generation/daily",
                    "energia_hoje_kwh": diario.get("total_generation_kwh")
                    or diario.get("generation_kwh"),
                    "disponibilidade_pct": diario.get("plant_availability_pct"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            itens.append({"usina": u.nome, "erro": f"{type(exc).__name__}: {exc}"})

    falhas = [i for i in itens if "erro" in i]
    return BlocoDiagnostico(
        ok=not falhas,
        detalhe=f"{len(itens) - len(falhas)} de {len(itens)} usina(s) responderam.",
        itens=itens,
    )


async def _diagnostico_meuplano(db: Session, usinas: list[PlantLink]) -> BlocoDiagnostico:
    alvos = [u for u in usinas if u.mp_usina_id]
    if not alvos:
        return BlocoDiagnostico(
            ok=False, detalhe="Nenhuma usina deste cliente existe no meuPlano."
        )

    try:
        cliente = await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        return BlocoDiagnostico(ok=False, detalhe=str(exc))

    itens = []
    for u in alvos:
        try:
            ordens = await cliente.ordens_servico(u.mp_usina_id)
            itens.append(
                {
                    "usina": u.nome,
                    "origem": f"GET /meuacesso/service-orders?plant_id={u.mp_usina_id}",
                    "ordens_de_servico": len(ordens),
                    "recentes": [o.get("titulo") or o.get("numero") for o in ordens[:3]],
                }
            )
        except Exception as exc:  # noqa: BLE001
            itens.append({"usina": u.nome, "erro": f"{type(exc).__name__}: {exc}"})

    falhas = [i for i in itens if "erro" in i]
    return BlocoDiagnostico(
        ok=not falhas,
        detalhe=f"{len(itens) - len(falhas)} de {len(itens)} usina(s) responderam.",
        itens=itens,
    )


# ------------------------------------------------------------------- equipe


class MembroOut(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    perfil: str
    ativo: bool
    ultimo_login: datetime | None = None


@router.get("/equipe", response_model=list[MembroOut])
def listar_equipe(
    db: Session = Depends(get_db), _: User = Depends(administrador_atual)
) -> list[MembroOut]:
    lista = db.scalars(
        select(User).where(User.perfil != Perfil.CLIENTE).order_by(User.nome)
    ).all()
    return [
        MembroOut(
            id=m.id,
            nome=m.nome,
            apelido=m.apelido,
            email=m.email,
            perfil=m.perfil.value,
            ativo=m.ativo,
            ultimo_login=m.ultimo_login,
        )
        for m in lista
    ]


class MembroIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None
    perfil: Perfil = Perfil.ATENDIMENTO
    senha: str = Field(min_length=8)


@router.post("/equipe", response_model=MembroOut, status_code=201)
def criar_membro(
    body: MembroIn,
    db: Session = Depends(get_db),
    _: User = Depends(administrador_atual),
) -> MembroOut:
    if body.perfil is Perfil.CLIENTE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Use a tela de clientes para criar um cliente."
        )
    try:
        apelido = normalizar_apelido(body.apelido)
    except ApelidoInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if db.scalar(select(User).where(User.apelido == apelido)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"O apelido “{apelido}” já está em uso."
        )

    membro = User(
        apelido=apelido,
        email=str(body.email).strip().lower() if body.email else None,
        nome=body.nome.strip(),
        perfil=body.perfil,
        senha_hash=gerar_hash_senha(body.senha),
    )
    db.add(membro)
    db.commit()
    db.refresh(membro)
    return MembroOut(
        id=membro.id,
        nome=membro.nome,
        apelido=membro.apelido,
        email=membro.email,
        perfil=membro.perfil.value,
        ativo=membro.ativo,
    )


class MembroPatch(BaseModel):
    perfil: Perfil | None = None
    ativo: bool | None = None


@router.patch("/equipe/{membro_id}", response_model=MembroOut)
def editar_membro(
    membro_id: int,
    body: MembroPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(administrador_atual),
) -> MembroOut:
    membro = db.get(User, membro_id)
    if membro is None or membro.perfil is Perfil.CLIENTE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membro não encontrado")

    # Rebaixar ou desativar a si mesmo tranca o painel para fora — e se for o último
    # administrador, tranca para todo mundo.
    if membro.id == admin.id and (body.ativo is False or body.perfil is Perfil.ATENDIMENTO):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Você não pode remover o próprio acesso de administrador.",
        )

    if body.perfil is not None:
        membro.perfil = body.perfil
    if body.ativo is not None:
        membro.ativo = body.ativo

    restantes = db.scalar(
        select(User).where(
            User.perfil == Perfil.ADMINISTRADOR, User.ativo, User.id != membro.id
        )
    )
    if restantes is None and membro.perfil is not Perfil.ADMINISTRADOR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Precisa sobrar ao menos um administrador ativo.",
        )

    db.commit()
    db.refresh(membro)
    return MembroOut(
        id=membro.id,
        nome=membro.nome,
        apelido=membro.apelido,
        email=membro.email,
        perfil=membro.perfil.value,
        ativo=membro.ativo,
        ultimo_login=membro.ultimo_login,
    )
