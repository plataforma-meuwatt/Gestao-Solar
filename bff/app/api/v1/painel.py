"""API do painel do gestor.

Duas responsabilidades: configurar as pontes com os produtos, e casar as usinas dos dois
lados. A página web em `app/web/` consome estes endpoints.

Tudo aqui exige `gestor_atual` — sessão de escopo `painel`, conta com `is_gestor`.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    conferir_senha,
    criar_token_painel,
    gestor_atual,
)
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import User
from app.services import conciliacao, integracoes

router = APIRouter(prefix="/api/painel", tags=["painel"])


# ----------------------------------------------------------------------- entrada


class EntrarIn(BaseModel):
    email: str
    senha: str


class EntrarOut(BaseModel):
    token: str
    expira_em: datetime
    nome: str


@router.post("/entrar", response_model=EntrarOut)
def entrar(body: EntrarIn, db: Session = Depends(get_db)) -> EntrarOut:
    usuario = db.scalar(select(User).where(User.email == body.email.strip().lower()))

    # Mensagem única para conta inexistente, senha errada e conta sem cargo: quem tenta
    # adivinhar não aprende qual das três aconteceu.
    if (
        usuario is None
        or not usuario.ativo
        or not usuario.is_gestor
        or not conferir_senha(body.senha, usuario.senha_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")

    token, expira = criar_token_painel(usuario.id)
    return EntrarOut(token=token, expira_em=expira, nome=usuario.nome)


# ------------------------------------------------------------------- integrações


class IntegracaoOut(BaseModel):
    produto: str
    configurada: bool
    base_url: str | None = None
    usuario_servico: str | None = None
    estado: str
    detalhe: str | None = None
    testada_em: datetime | None = None
    usinas_visiveis: int | None = None


class IntegracaoIn(BaseModel):
    base_url: str = Field(min_length=4)
    usuario_servico: str = Field(min_length=3)
    # Vazia mantém a que já está gravada — é o que permite corrigir o endereço sem
    # redigitar a credencial.
    senha: str | None = None


@router.get("/integracoes", response_model=list[IntegracaoOut])
def listar_integracoes(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[IntegracaoOut]:
    saida = []
    for produto, integracao in integracoes.listar(db).items():
        if integracao is None:
            saida.append(IntegracaoOut(produto=produto.value, configurada=False, estado="nunca"))
        else:
            saida.append(
                IntegracaoOut(
                    produto=produto.value,
                    configurada=True,
                    base_url=integracao.base_url,
                    usuario_servico=integracao.usuario_servico,
                    estado=integracao.estado.value,
                    detalhe=integracao.detalhe_teste,
                    testada_em=integracao.testada_em,
                    usinas_visiveis=integracao.usinas_visiveis,
                )
            )
    return saida


@router.put("/integracoes/{produto}", response_model=IntegracaoOut)
def salvar_integracao(
    produto: Produto,
    body: IntegracaoIn,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> IntegracaoOut:
    try:
        integracao = integracoes.salvar(
            db, produto, body.base_url, body.usuario_servico, body.senha
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return IntegracaoOut(
        produto=produto.value,
        configurada=True,
        base_url=integracao.base_url,
        usuario_servico=integracao.usuario_servico,
        estado=integracao.estado.value,
    )


class TesteOut(BaseModel):
    ok: bool
    detalhe: str
    usinas_visiveis: int | None = None


@router.post("/integracoes/{produto}/testar", response_model=TesteOut)
async def testar_integracao(
    produto: Produto,
    db: Session = Depends(get_db),
    _: User = Depends(gestor_atual),
) -> TesteOut:
    resultado = await integracoes.testar(db, produto)
    return TesteOut(ok=resultado.ok, detalhe=resultado.detalhe, usinas_visiveis=resultado.usinas)


# ------------------------------------------------------------------ conciliação


class UsinaLado(BaseModel):
    id: str
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None


class CandidatoOut(BaseModel):
    mp_usina_id: int
    nome: str
    pontos: float
    motivos: list[str]


class LinhaConciliacao(BaseModel):
    mw_slug: str
    mw_nome: str
    vinculado_a: int | None = None
    candidatos: list[CandidatoOut]


class ConciliacaoOut(BaseModel):
    meuwatt: list[UsinaLado]
    meuplano: list[UsinaLado]
    linhas: list[LinhaConciliacao]
    aviso: str | None = None


@router.get("/conciliacao", response_model=ConciliacaoOut)
async def carregar_conciliacao(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> ConciliacaoOut:
    """As duas listas, os vínculos já salvos e as sugestões para o que falta."""
    usinas_mw: list[dict[str, Any]] = []
    usinas_mp: list[dict[str, Any]] = []
    avisos: list[str] = []

    try:
        cliente_mw = await integracoes.cliente_meuwatt(db)
        usinas_mw = await cliente_mw.usinas()
    except Exception as exc:  # noqa: BLE001 — a tela precisa abrir mesmo com uma ponte fora
        avisos.append(f"meuWatt indisponível: {exc}")

    try:
        cliente_mp = await integracoes.cliente_meuplano(db)
        usinas_mp = await cliente_mp.usinas()
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"meuPlano indisponível: {exc}")

    vinculos = {
        link.mw_plant_slug: link.mp_usina_id
        for link in db.scalars(select(PlantLink)).all()
        if link.mw_plant_slug
    }

    sugestoes = conciliacao.sugerir(usinas_mw, usinas_mp)

    return ConciliacaoOut(
        meuwatt=[
            UsinaLado(
                id=u.get("slug", ""),
                nome=u.get("name") or "",
                cidade=u.get("city"),
                uf=u.get("state"),
                kwp=u.get("capacity_kwp"),
            )
            for u in usinas_mw
        ],
        meuplano=[
            UsinaLado(
                id=str(u.get("id", "")),
                nome=u.get("name") or u.get("nome") or "",
                cidade=u.get("city") or u.get("cidade"),
                uf=u.get("uf"),
                kwp=u.get("potencia_kwp"),
            )
            for u in usinas_mp
        ],
        linhas=[
            LinhaConciliacao(
                mw_slug=s.mw_slug,
                mw_nome=s.mw_nome,
                vinculado_a=vinculos.get(s.mw_slug),
                candidatos=[
                    CandidatoOut(
                        mp_usina_id=c.mp_usina_id,
                        nome=c.nome,
                        pontos=c.pontos,
                        motivos=c.motivos,
                    )
                    for c in s.candidatos
                ],
            )
            for s in sugestoes
        ],
        aviso=" · ".join(avisos) if avisos else None,
    )


class VincularIn(BaseModel):
    mw_slug: str
    # Nulo desfaz o vínculo — é o caso da usina que só existe de um lado.
    mp_usina_id: int | None = None
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None


@router.post("/conciliacao/vincular")
def vincular(
    body: VincularIn, db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> dict[str, str]:
    """Grava o par confirmado. Uma usina do meuPlano só pode pertencer a um vínculo — dois
    slugs apontando para a mesma usina misturaria dados de duas plantas."""
    if body.mp_usina_id is not None:
        conflito = db.scalar(
            select(PlantLink).where(
                PlantLink.mp_usina_id == body.mp_usina_id,
                PlantLink.mw_plant_slug != body.mw_slug,
            )
        )
        if conflito is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Esta usina do meuPlano já está vinculada a “{conflito.nome}”. "
                "Desfaça o outro vínculo antes.",
            )

    link = db.scalar(select(PlantLink).where(PlantLink.mw_plant_slug == body.mw_slug))
    if link is None:
        link = PlantLink(mw_plant_slug=body.mw_slug, nome=body.nome)
        db.add(link)

    link.mp_usina_id = body.mp_usina_id
    link.nome = body.nome
    link.cidade = body.cidade
    link.uf = body.uf
    link.kwp = body.kwp
    db.commit()

    return {"situacao": "vinculada" if body.mp_usina_id else "desvinculada"}
