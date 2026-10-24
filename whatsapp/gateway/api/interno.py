"""A porta do BFF — credenciais, envio e consulta.

Quem chama é um servidor, não um humano: a autenticação é a chave em cabeçalho
(`X-Chave-Interna`), no mesmo padrão de `bff/app/api/v1/avisos.py`. Sem a chave configurada,
a porta recusa tudo — falhar fechado é o único padrão aceitável para um endpoint que manda
mensagem para o celular de gente.

É por aqui que a tela de administração do WhatsApp, no painel, grava as credenciais: o
painel fala com o BFF, o BFF fala com o gateway. O token nunca volta por nenhuma destas
rotas — o que sai é o prefixo, o estado e a data do último teste.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gateway.core.config import get_settings
from gateway.core.db import get_db
from gateway.core.seguranca import CABECALHO_CHAVE_INTERNA, chave_interna_confere
from gateway.models.mensagem import Mensagem, WebhookEvento
from gateway.services import contas as svc_contas
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
    #: A configuração do Embedded Signup — o que abre a janela da Meta para o técnico.
    es_config_id: str | None = None
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
        es_config_id=corpo.es_config_id,
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


class ConteudoIn(BaseModel):
    """A RESPOSTA do assistente: texto, ou um arquivo (documento/imagem) em base64."""
    telefone: str
    tipo: str = Field(pattern="^(text|document|image)$")
    texto: str | None = Field(default=None, max_length=4096)
    arquivo_b64: str | None = None
    filename: str | None = None
    mime: str | None = None
    origem: str | None = None


@router.post("/conteudo", response_model=EnvioOut, dependencies=[Depends(_porta)])
async def enviar_conteudo(corpo: ConteudoIn, db: Session = Depends(get_db)) -> EnvioOut:
    """Responde dentro da janela de 24 h. Arquivo sobe na Meta antes e vai pelo `media_id`."""
    import base64
    from gateway.meta import graph
    try:
        if corpo.tipo == "text":
            if not (corpo.texto or "").strip():
                raise ValueError("Texto vazio.")
            conteudo = {"body": corpo.texto, "preview_url": False}
        else:
            if not corpo.arquivo_b64:
                raise ValueError("Falta o arquivo.")
            cred = svc_envio.credencial_de_envio(db)
            media_id, erro = await graph.subir_midia(
                token=cred.token or "", phone_number_id=cred.phone_number_id or "",
                raw=base64.b64decode(corpo.arquivo_b64), mime=corpo.mime or "application/pdf",
                filename=corpo.filename or "arquivo")
            if not media_id:
                return EnvioOut(id=0, ok=False, status="falhou", erro=erro)
            conteudo = {"id": media_id}
            if corpo.tipo == "document":
                conteudo["filename"] = corpo.filename or "arquivo"
            if corpo.texto:
                conteudo["caption"] = corpo.texto[:1024]
        r = await svc_envio.enviar_conteudo(
            db, telefone=corpo.telefone, tipo=corpo.tipo, conteudo=conteudo,
            texto=corpo.texto if corpo.tipo == "text" else (corpo.filename or corpo.texto),
            origem=corpo.origem)
    except svc_envio.EnvioIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return EnvioOut(id=r.id, ok=r.ok, wamid=r.wamid, status=r.status, erro=r.erro)


class DigitandoIn(BaseModel):
    wamid: str


@router.post("/digitando", status_code=204, dependencies=[Depends(_porta)])
async def digitando(corpo: DigitandoIn, db: Session = Depends(get_db)) -> None:
    """Lida + "digitando…" na mensagem recebida. Sem credencial, não faz nada."""
    from gateway.meta import graph
    try:
        cred = svc_envio.credencial_de_envio(db)
    except svc_envio.EnvioIndisponivel:
        return
    await graph.digitando(token=cred.token or "", phone_number_id=cred.phone_number_id or "",
                          wamid=corpo.wamid)


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


# ── contas: o WhatsApp Business de cada técnico ─────────────────────────────
#
# `gs_user_id` vem do BFF, que o tira da SESSÃO do técnico — nunca de um campo que o
# navegador preencheu. Aqui ele é confiado porque só o BFF passa por esta porta.


class ConectarIn(BaseModel):
    #: Vive 30 segundos na Meta: o BFF repassa assim que o navegador entrega.
    code: str = Field(min_length=1)
    waba_id: str = Field(min_length=1)
    phone_number_id: str = Field(min_length=1)
    business_id: str | None = None
    #: O evento do Embedded Signup foi `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`.
    coexistencia: bool = False
    gs_user_id: int
    empresa_id: int | None = None
    ator: str | None = None


class ContaOut(BaseModel):
    phone_number_id: str
    waba_id: str
    numero_exibicao: str | None = None
    nome_verificado: str | None = None
    coexistencia: bool
    estado: str
    detalhe: str | None = None
    conectada_em: datetime
    desconectada_em: datetime | None = None


@router.get("/contas/configuracao", dependencies=[Depends(_porta)])
def configuracao_das_contas(db: Session = Depends(get_db)) -> dict:
    """App e configuração do Embedded Signup — o que o navegador precisa. Sem segredo."""
    return svc_contas.configuracao(db)


@router.get("/contas", response_model=list[ContaOut], dependencies=[Depends(_porta)])
def listar_contas(gs_user_id: int, db: Session = Depends(get_db)) -> list[ContaOut]:
    return [ContaOut.model_validate(c, from_attributes=True) for c in svc_contas.listar(db, gs_user_id)]


@router.post("/contas", response_model=ResultadoOut, dependencies=[Depends(_porta)])
async def conectar_conta(corpo: ConectarIn, db: Session = Depends(get_db)) -> ResultadoOut:
    """Troca o code, confere, assina o webhook e só então grava."""
    r = await svc_contas.conectar(
        db,
        code=corpo.code,
        waba_id=corpo.waba_id,
        phone_number_id=corpo.phone_number_id,
        business_id=corpo.business_id,
        coexistencia=corpo.coexistencia,
        gs_user_id=corpo.gs_user_id,
        empresa_id=corpo.empresa_id,
        ator=corpo.ator,
    )
    return ResultadoOut(ok=r.ok, detalhe=r.detalhe)


@router.delete("/contas/{phone_number_id}", status_code=204, dependencies=[Depends(_porta)])
async def desconectar_conta(
    phone_number_id: str, gs_user_id: int, ator: str | None = None, db: Session = Depends(get_db)
) -> None:
    # 404 sem dizer de quem é: número de outra conta e número inexistente respondem igual.
    if not await svc_contas.desconectar(
        db, phone_number_id=phone_number_id, gs_user_id=gs_user_id, ator=ator
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Número não encontrado nesta conta.")


# ── a senha de atuação digitada sai daqui ───────────────────────────────────

OCULTO = "[senha de atuação]"


def _sem_o_texto(corpo, wamid: str, texto: str):
    """A entrega crua da Meta com o texto da mensagem `wamid` trocado (cópia nova: a coluna
    é JSON, e só uma atribuição faz o SQLAlchemy gravar)."""
    import copy

    novo = copy.deepcopy(corpo)
    for entrada in (novo or {}).get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            for msg in ((mudanca.get("value") or {}).get("messages") or []):
                if msg.get("id") == wamid and isinstance(msg.get("text"), dict):
                    msg["text"]["body"] = texto
    return novo


class OcultarIn(BaseModel):
    #: O texto SEM a senha ("pode ligar, senha [senha oculta]"). Ausente: some a mensagem inteira.
    texto: str | None = Field(default=None, max_length=4096)


@router.post("/mensagens/{mensagem_id}/ocultar", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(_porta)])
def ocultar_texto(mensagem_id: int, corpo: OcultarIn | None = None, db: Session = Depends(get_db)) -> None:
    """Tira a senha de atuação de uma mensagem RECEBIDA — da linha e da entrega crua da Meta. O
    BFF chama logo depois de achar a senha (pedido do dono, 24/10/2026: o bot pede senha para
    atuar); guardada aqui, ela ficaria em claro no banco. Fica o texto sem a senha."""
    from sqlalchemy import Text, cast

    m = db.get(Mensagem, mensagem_id)
    if m is None or m.direcao != "entrada":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mensagem recebida não encontrada.")
    texto = (corpo.texto if corpo and corpo.texto else None) or OCULTO
    m.texto = texto
    if m.wamid:
        desde = datetime.now(UTC) - timedelta(days=2)
        for ev in db.scalars(select(WebhookEvento).where(
            WebhookEvento.recebido_em >= desde, cast(WebhookEvento.corpo, Text).contains(m.wamid)
        )):
            ev.corpo = _sem_o_texto(ev.corpo, m.wamid, texto)
    db.commit()


# ── saúde do canal ──────────────────────────────────────────────────────────


class SaudeOut(BaseModel):
    """O que diz se o bot está OUVINDO — não só se está configurado. Em 10/2026 a tela dizia
    "webhook pronto" enquanto 40 mensagens estavam presas aqui por um erro de banco."""

    #: Entregas da Meta não aplicadas há mais de 2 min, nas últimas 24 h (a varredura passa a
    #: cada 60 s; a que desistiu depois de 10 tentativas sai da conta em 24 h, senão o alarme
    #: ficaria vermelho para sempre por uma entrega antiga).
    eventos_parados: int
    #: Dessas, as que já falharam (com o último erro).
    eventos_com_erro: int
    ultimo_erro: str | None = None
    #: Mensagens recebidas que o BFF ainda não recebeu de nós.
    mensagens_sem_aviso: int
    ultima_recebida_em: datetime | None = None
    ultima_enviada_em: datetime | None = None
    #: A última que a Meta disse ter entregado.
    ultima_entregue_em: datetime | None = None


@router.get("/saude", response_model=SaudeOut, dependencies=[Depends(_porta)])
def saude(db: Session = Depends(get_db)) -> SaudeOut:
    agora = datetime.now(UTC)
    janela = (agora - timedelta(hours=24), agora - timedelta(minutes=2))
    parados = WebhookEvento.processado_em.is_(None) & WebhookEvento.recebido_em.between(*janela)
    ultimo_erro = db.scalar(
        select(WebhookEvento.erro).where(parados, WebhookEvento.erro.is_not(None)).order_by(WebhookEvento.id.desc()).limit(1)
    )
    return SaudeOut(
        eventos_parados=db.scalar(select(func.count()).select_from(WebhookEvento).where(parados)) or 0,
        eventos_com_erro=db.scalar(
            select(func.count()).select_from(WebhookEvento).where(parados, WebhookEvento.erro.is_not(None))
        ) or 0,
        ultimo_erro=ultimo_erro,
        mensagens_sem_aviso=db.scalar(
            select(func.count()).select_from(Mensagem).where(
                Mensagem.direcao == "entrada", Mensagem.notificada_bff_em.is_(None),
                Mensagem.criada_em.between(*janela),
            )
        ) or 0,
        ultima_recebida_em=db.scalar(select(func.max(Mensagem.ocorrida_em)).where(Mensagem.direcao == "entrada")),
        ultima_enviada_em=db.scalar(select(func.max(Mensagem.ocorrida_em)).where(Mensagem.direcao == "saida")),
        ultima_entregue_em=db.scalar(
            select(func.max(Mensagem.status_em)).where(
                Mensagem.direcao == "saida", Mensagem.status.in_(["entregue", "lida"])
            )
        ),
    )
