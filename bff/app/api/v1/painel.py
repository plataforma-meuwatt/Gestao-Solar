"""API do painel: entrada, pontes com os produtos e conciliação de usinas.

A gestão de clientes vive em `painel_clientes.py`.

Tudo aqui exige `gestor_atual` — sessão de escopo `painel`, perfil que abre o painel. O
que mexe em credencial de serviço sobe para `administrador_atual`.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    administrador_atual,
    conferir_senha,
    criar_token_painel,
    gestor_atual,
)
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
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
    perfil: str


@router.post("/entrar", response_model=EntrarOut)
def entrar(body: EntrarIn, db: Session = Depends(get_db)) -> EntrarOut:
    usuario = db.scalar(select(User).where(User.email == body.email.strip().lower()))

    # Mensagem única para conta inexistente, senha errada e perfil sem acesso ao painel:
    # quem tenta adivinhar não aprende qual das três aconteceu.
    if (
        usuario is None
        or not usuario.ativo
        or not usuario.abre_painel
        or not conferir_senha(body.senha, usuario.senha_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")

    usuario.ultimo_login = datetime.now(UTC)
    db.commit()

    token, expira = criar_token_painel(usuario.id)
    # O perfil vai na resposta para a barra lateral esconder o que atendimento não abre.
    # É conforto de interface, não segurança: o backend recusa de qualquer forma.
    return EntrarOut(
        token=token, expira_em=expira, nome=usuario.nome, perfil=usuario.perfil.value
    )


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
    # Como esta ponte se autentica. `False` = linha antiga, por conta de serviço — a tela
    # mostra o aviso de migração em cima dela.
    por_token: bool = False
    token_prefixo: str | None = None
    token_dono_nome: str | None = None
    token_dono_email: str | None = None
    token_gravado_em: datetime | None = None


class IntegracaoIn(BaseModel):
    base_url: str = Field(min_length=4)
    usuario_servico: str = Field(min_length=3)
    # Vazia mantém a que já está gravada — é o que permite corrigir o endereço sem
    # redigitar a credencial.
    senha: str | None = None


class TokenIn(BaseModel):
    base_url: str = Field(min_length=4)
    #: O valor colado pelo gestor. Sem `min_length` apertado de propósito: quem valida é
    #: `core/tokens_produto`, que sabe dizer POR QUE está errado — "faltam caracteres" é
    #: uma resposta melhor do que um 422 do Pydantic dizendo "string curta".
    token: str = Field(min_length=1)


class EventoOut(BaseModel):
    evento: str
    ocorrido_em: datetime
    ator_email: str | None = None
    token_prefixo: str | None = None
    detalhe: str | None = None
    usinas_visiveis: int | None = None


def _integracao_out(produto: Produto, integracao) -> IntegracaoOut:
    if integracao is None:
        return IntegracaoOut(produto=produto.value, configurada=False, estado="nunca")
    return IntegracaoOut(
        produto=produto.value,
        configurada=True,
        base_url=integracao.base_url,
        usuario_servico=integracao.usuario_servico,
        estado=integracao.estado.value,
        detalhe=integracao.detalhe_teste,
        testada_em=integracao.testada_em,
        usinas_visiveis=integracao.usinas_visiveis,
        por_token=integracao.por_token,
        token_prefixo=integracao.token_prefixo,
        token_dono_nome=integracao.token_dono_nome,
        token_dono_email=integracao.token_dono_email,
        token_gravado_em=integracao.token_gravado_em,
    )


@router.get("/integracoes", response_model=list[IntegracaoOut])
def listar_integracoes(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[IntegracaoOut]:
    return [_integracao_out(p, i) for p, i in integracoes.listar(db).items()]


@router.put("/integracoes/{produto}", response_model=IntegracaoOut)
def salvar_integracao(
    produto: Produto,
    body: IntegracaoIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> IntegracaoOut:
    """Caminho ANTIGO, por conta de serviço. Mantido para não quebrar o que já está
    gravado; a tela oferece o token."""
    try:
        integracao = integracoes.salvar(
            db, produto, body.base_url, body.usuario_servico, body.senha,
            ator_email=usuario.email,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return _integracao_out(produto, integracao)


class TesteOut(BaseModel):
    ok: bool
    detalhe: str
    usinas_visiveis: int | None = None
    #: De quem é o token que respondeu. A tela mostra isto ao lado do resultado porque
    #: "conectado" com a pessoa errada é um sucesso enganoso.
    dono_nome: str | None = None
    dono_email: str | None = None


@router.post("/integracoes/{produto}/testar", response_model=TesteOut)
async def testar_integracao(
    produto: Produto,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> TesteOut:
    resultado = await integracoes.testar(db, produto, ator_email=usuario.email)
    return TesteOut(
        ok=resultado.ok,
        detalhe=resultado.detalhe,
        usinas_visiveis=resultado.usinas,
        dono_nome=resultado.dono_nome,
        dono_email=resultado.dono_email,
    )


@router.put("/integracoes/{produto}/token", response_model=TesteOut)
async def conectar_por_token(
    produto: Produto,
    body: TokenIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> TesteOut:
    """Cola um token pessoal e conecta.

    Responde com o resultado do teste, não com a integração: o que o gestor precisa
    saber neste instante é se funcionou e como quem. Se não funcionou, nada foi gravado
    — a conexão anterior continua de pé (ver `integracoes.salvar_token`).
    """
    resultado = await integracoes.salvar_token(
        db, produto, body.base_url, body.token, ator_email=usuario.email
    )
    return TesteOut(
        ok=resultado.ok,
        detalhe=resultado.detalhe,
        usinas_visiveis=resultado.usinas,
        dono_nome=resultado.dono_nome,
        dono_email=resultado.dono_email,
    )


@router.delete("/integracoes/{produto}/token", response_model=IntegracaoOut)
def desconectar_token(
    produto: Produto,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> IntegracaoOut:
    """Para de usar o token deste lado. NÃO o revoga no produto de origem — só quem o
    emitiu pode fazer isso, lá. A tela avisa, porque a diferença importa."""
    integracoes.remover_token(db, produto, ator_email=usuario.email)
    return _integracao_out(produto, integracoes.obter(db, produto))


@router.get("/integracoes/{produto}/eventos", response_model=list[EventoOut])
def historico_integracao(
    produto: Produto,
    db: Session = Depends(get_db),
    _: User = Depends(administrador_atual),
) -> list[EventoOut]:
    """O que já aconteceu com esta ponte. Responde "desde quando parou?", que o estado
    atual sozinho não responde."""
    return [
        EventoOut(
            evento=e.evento,
            ocorrido_em=e.ocorrido_em,
            ator_email=e.ator_email,
            token_prefixo=e.token_prefixo,
            detalhe=e.detalhe,
            usinas_visiveis=e.usinas_visiveis,
        )
        for e in integracoes.historico(db, produto)
    ]


# ---------------------------------------------------------------------- usinas


class UsinaOut(BaseModel):
    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    tem_meuwatt: bool
    tem_meuplano: bool
    dono_id: int | None = None
    dono_nome: str | None = None


@router.get("/usinas", response_model=list[UsinaOut])
def listar_usinas(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[UsinaOut]:
    """As usinas que o Gestão Solar conhece, e de quem é cada uma.

    Responde à pergunta que a conciliação não responde: *esta usina chega em alguém?* Uma
    usina casada nos dois lados e sem dono é invisível no aplicativo, e sem esta lista o
    gestor só descobriria isso pelo cliente reclamando.
    """
    donos = {
        pid: (uid, nome)
        for pid, uid, nome in db.execute(
            select(UserPlantAccess.plant_link_id, User.id, User.nome)
            .join(User, User.id == UserPlantAccess.user_id)
            .where(User.perfil == Perfil.CLIENTE)
        ).all()
    }

    saida = []
    for link in db.scalars(select(PlantLink).where(PlantLink.ativo).order_by(PlantLink.nome)).all():
        dono = donos.get(link.id)
        saida.append(
            UsinaOut(
                id=link.id,
                nome=link.nome,
                cidade=link.cidade,
                uf=link.uf,
                kwp=link.kwp,
                tem_meuwatt=link.tem_meuwatt,
                tem_meuplano=link.tem_meuplano,
                dono_id=dono[0] if dono else None,
                dono_nome=dono[1] if dono else None,
            )
        )
    return saida


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
