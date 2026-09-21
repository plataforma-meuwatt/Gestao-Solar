"""A porta do BFF — credenciais, envio e consulta.

Quem chama é um servidor, não um humano: a autenticação é a chave em cabeçalho
(`X-Chave-Interna`), no mesmo padrão de `bff/app/api/v1/avisos.py`. Sem a chave configurada,
a porta recusa tudo — falhar fechado é o único padrão aceitável para um endpoint que manda
mensagem para o celular de gente.

É por aqui que a tela de administração do WhatsApp, no painel, grava as credenciais: o
painel fala com o BFF, o BFF fala com o gateway. O token nunca volta por nenhuma destas
rotas — o que sai é o prefixo, o estado e a data do último teste.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from gateway.core.config import get_settings
from gateway.core.db import get_db
from gateway.core.seguranca import CABECALHO_CHAVE_INTERNA, chave_interna_confere
from gateway.models.mensagem import Mensagem
from gateway.services import credenciais as svc
from gateway.services import envio as svc_envio

router = APIRouter(prefix="/interno", tags=["interno"])


def _porta(x_chave_interna: str | None = Header(default=None, alias=CABECALHO_CHAVE_INTERNA)) -> None:
    esperada = get_settings().whatsapp_chave_interna
    if not esperada:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Porta interna não configurada (WHATSAPP_CHAVE_INTERNA ausente).",
        )
    if not chave_interna_confere(esperada, x_chave_interna):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chave inválida.")


# ── credenciais ─────────────────────────────────────────────────────────────


class CredenciaisIn(BaseModel):
    phone_number_id: str = Field(min_length=1)
    waba_id: str | None = None
    app_id: str | None = None
    #: Vazio significa "não mexer": o gestor que só corrigiu o WABA não tem mais o token.
    token: str | None = None
    app_secret: str | None = None
    verify_token: str | None = None
    #: Quem está gravando, como o painel informou — vai para o histórico.
    ator: str | None = None


class ResultadoOut(BaseModel):
    ok: bool
    detalhe: str


class EventoOut(BaseModel):
    evento: str
    ocorrido_em: datetime
    ator: str | None = None
    token_prefixo: str | None = None
    detalhe: str | None = None


@router.get("/credenciais", dependencies=[Depends(_porta)])
def ler_credenciais(db: Session = Depends(get_db)) -> dict:
    """O estado da configuração. Nenhum segredo sai daqui."""
    return svc.estado(db)


@router.put("/credenciais", response_model=ResultadoOut, dependencies=[Depends(_porta)])
async def gravar_credenciais(corpo: CredenciaisIn, db: Session = Depends(get_db)) -> ResultadoOut:
    """Testa contra a Meta e só então grava. Recusa não derruba a credencial anterior."""
    r = await svc.salvar(
        db,
        phone_number_id=corpo.phone_number_id,
        token=corpo.token,
        app_secret=corpo.app_secret,
        verify_token=corpo.verify_token,
        waba_id=corpo.waba_id,
        app_id=corpo.app_id,
        ator=corpo.ator,
    )
    return ResultadoOut(ok=r.ok, detalhe=r.detalhe)


@router.post("/credenciais/testar", response_model=ResultadoOut, dependencies=[Depends(_porta)])
async def testar_credenciais(ator: str | None = None, db: Session = Depends(get_db)) -> ResultadoOut:
    """Reexercita o que está gravado — o token pode ter sido revogado do outro lado."""
    r = await svc.testar(db, ator=ator)
    return ResultadoOut(ok=r.ok, detalhe=r.detalhe)


@router.delete("/credenciais", status_code=204, dependencies=[Depends(_porta)])
def remover_credenciais(ator: str | None = None, db: Session = Depends(get_db)) -> None:
    """Apaga os segredos daqui. O app segue existindo na Meta — revogar é lá."""
    svc.remover(db, ator=ator)


@router.get("/credenciais/eventos", response_model=list[EventoOut], dependencies=[Depends(_porta)])
def historico(limite: int = 30, db: Session = Depends(get_db)) -> list[EventoOut]:
    return [
        EventoOut(
            evento=e.evento,
            ocorrido_em=e.ocorrido_em,
            ator=e.ator,
            token_prefixo=e.token_prefixo,
            detalhe=e.detalhe,
        )
        for e in svc.historico(db, min(max(limite, 1), 200))
    ]


# ── o que a conta tem ───────────────────────────────────────────────────────


@router.get("/numeros", dependencies=[Depends(_porta)])
async def numeros(db: Session = Depends(get_db)) -> list[dict]:
    """Os números da conta, com o id que vai no campo do painel."""
    try:
        return await svc.numeros(db)
    except svc.ListagemIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/templates", dependencies=[Depends(_porta)])
async def templates(db: Session = Depends(get_db)) -> list[dict]:
    """Os modelos de mensagem, aprovados ou não."""
    try:
        return await svc.templates(db)
    except svc.ListagemIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


# ── envio ───────────────────────────────────────────────────────────────────


class TemplateIn(BaseModel):
    telefone: str = Field(min_length=8)
    template: str = Field(min_length=1, max_length=80)
    parametros: list[str] = []
    idioma: str = "pt_BR"
    #: Quem pediu: `bff`, `robo`… Aparece no histórico e separa o que o motor mandou.
    origem: str | None = None


class EnvioOut(BaseModel):
    id: int
    ok: bool
    wamid: str | None = None
    status: str
    erro: str | None = None


@router.post("/templates", response_model=EnvioOut, dependencies=[Depends(_porta)])
async def enviar_template(corpo: TemplateIn, db: Session = Depends(get_db)) -> EnvioOut:
    """Manda um template aprovado.

    Responde 200 mesmo quando a Meta recusa, com `ok: false` e o motivo: a recusa é um
    resultado do envio, não uma falha da requisição, e quem chamou precisa da frase inteira
    para mostrar ao gestor.
    """
    try:
        r = await svc_envio.enviar_template(
            db,
            telefone=corpo.telefone,
            template=corpo.template,
            parametros=corpo.parametros,
            idioma=corpo.idioma,
            origem=corpo.origem,
        )
    except svc_envio.EnvioIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return EnvioOut(id=r.id, ok=r.ok, wamid=r.wamid, status=r.status, erro=r.erro)


class MensagemOut(BaseModel):
    id: int
    wamid: str | None = None
    direcao: str
    wa_id: str
    telefone: str | None = None
    tipo: str
    template: str | None = None
    texto: str | None = None
    status: str
    status_em: datetime | None = None
    erro_codigo: str | None = None
    erro_detalhe: str | None = None
    ocorrida_em: datetime


@router.get("/mensagens/{mensagem_id}", response_model=MensagemOut, dependencies=[Depends(_porta)])
def ler_mensagem(mensagem_id: int, db: Session = Depends(get_db)) -> MensagemOut:
    """O estado de uma mensagem — é assim que o BFF acompanha a entrega."""
    m = db.get(Mensagem, mensagem_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mensagem não encontrada.")
    return MensagemOut(
        id=m.id,
        wamid=m.wamid,
        direcao=m.direcao,
        wa_id=m.wa_id,
        telefone=m.telefone,
        tipo=m.tipo,
        template=m.template,
        texto=m.texto,
        status=m.status,
        status_em=m.status_em,
        erro_codigo=m.erro_codigo,
        erro_detalhe=m.erro_detalhe,
        ocorrida_em=m.ocorrida_em,
    )
