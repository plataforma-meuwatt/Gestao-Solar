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

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gateway.core.config import get_settings
from gateway.core.db import get_db
from gateway.core.seguranca import CABECALHO_CHAVE_INTERNA, chave_interna_confere
from gateway.core.telefone import TelefoneInvalido, normalizar
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


class BotaoIn(BaseModel):
    #: O que volta no toque (`interactive.button_reply.id`) — o título é o que a pessoa lê.
    id: str = Field(min_length=1, max_length=256)
    titulo: str = Field(min_length=1, max_length=20)


class FormularioIn(BaseModel):
    """Opções para MARCAR (caixas de seleção), no formulário publicado `gs_escolha_multipla` (WhatsApp Flow, tela
    ESCOLHA). O que a pessoa marca volta como `midia.formulario` = `{escolhidos: [índices], flow_token}`."""
    token: str = Field(min_length=8, max_length=64)
    titulo: str = Field(min_length=1, max_length=300)
    opcoes: list[str] = Field(min_length=1, max_length=200)
    marcados: list[str] = Field(default_factory=list)
    aviso: str = Field(default="", max_length=300)
    #: UMA escolha numa lista suspensa (`gs_escolha_uma`, tela UMA, até 200): o `rotulo` (até 30 letras) é o que a
    #: lista mostra, a opção inteira vai embaixo; volta `{escolhido: índice}`. Sem `uma`, caixas de marcar (até 20).
    uma: bool = False
    rotulos: list[str] = Field(default_factory=list)


#: Os formulários de escolha, criados e publicados uma vez na conta da Meta (29/10/2026).
FLOW_ESCOLHA = "gs_escolha_multipla"
FLOW_UMA = "gs_escolha_uma"


class CadastroIn(BaseModel):
    """O formulário de CADASTRO de pessoa (`gs_cadastro_pessoa`, tela CADASTRO; pedido do dono, 29/10/2026: "quando
    eu pedir cadastro, abrir um formulário com os campos necessários"): nome, e-mail, celular e o papel em cada
    sistema. As listas de papéis vêm do BFF (lá mora o cadastro), por sistema (`meuplano`, `meuwatt`, `gs`), e o que
    volta é `midia.formulario` = `{nome, email, celular, meuplano, meuwatt, gs, flow_token}`."""
    token: str = Field(min_length=8, max_length=64)
    nome: str = Field(default="", max_length=150)
    email: str = Field(default="", max_length=150)
    celular: str = Field(default="", max_length=30)
    papeis: dict[str, list[BotaoIn]]
    escolhidos: dict[str, str] = Field(default_factory=dict)


#: O formulário de cadastro, publicado na conta da Meta (29/10/2026).
FLOW_CADASTRO = "gs_cadastro_pessoa"
_SISTEMAS = {"meuplano": "mp", "meuwatt": "mw", "gs": "gs"}            # campo do formulário → nome no Flow


class ConteudoIn(BaseModel):
    """A RESPOSTA do assistente: texto, um arquivo (documento/imagem) em base64, ou um texto com
    até 3 BOTÕES de resposta ("Sim"/"Não" para confirmar uma ação — o toque volta como mensagem
    com o título do botão)."""
    telefone: str
    tipo: str = Field(pattern="^(text|document|image|botoes|formulario)$")
    texto: str | None = Field(default=None, max_length=4096)
    arquivo_b64: str | None = None
    filename: str | None = None
    mime: str | None = None
    origem: str | None = None
    botoes: list[BotaoIn] | None = Field(default=None, max_length=3)
    formulario: FormularioIn | None = None
    cadastro: CadastroIn | None = None
    #: O que fica GUARDADO aqui no lugar do `texto`, que vai inteiro à Meta: a resposta sem as senhas que ela
    #: revela (o bot pede ao meuPlano a senha de um equipamento; a pessoa recebe, o banco daqui não guarda).
    guardar: str | None = Field(default=None, max_length=4096)


@router.post("/conteudo", response_model=EnvioOut, dependencies=[Depends(_porta)])
async def enviar_conteudo(corpo: ConteudoIn, db: Session = Depends(get_db)) -> EnvioOut:
    """Responde dentro da janela de 24 h. Arquivo sobe na Meta antes e vai pelo `media_id`."""
    import base64
    from gateway.meta import graph
    tipo = corpo.tipo
    try:
        if corpo.tipo == "text":
            if not (corpo.texto or "").strip():
                raise ValueError("Texto vazio.")
            conteudo = {"body": corpo.texto, "preview_url": False}
        elif corpo.tipo == "botoes":
            if not (corpo.texto or "").strip() or not corpo.botoes:
                raise ValueError("Botões pedem o texto e pelo menos um botão.")
            if len(corpo.texto) > 1024:
                raise ValueError("O texto da mensagem com botões vai até 1024 caracteres.")
            tipo = "interactive"
            conteudo = {"type": "button", "body": {"text": corpo.texto}, "action": {"buttons": [
                {"type": "reply", "reply": {"id": b.id, "title": b.titulo}} for b in corpo.botoes]}}
        elif corpo.tipo == "formulario":
            f, c = corpo.formulario, corpo.cadastro
            if (f is None) == (c is None) or not (corpo.texto or "").strip() or len(corpo.texto) > 1024:
                raise ValueError("Formulário pede as opções (ou o cadastro) e o texto (até 1024 caracteres).")
            if f is not None and f.uma:
                nome, tela, cta, token = FLOW_UMA, "UMA", "Escolher outra", f.token
                rotulos = [(f.rotulos[i] if i < len(f.rotulos) else o) or o for i, o in enumerate(f.opcoes)]
                dados = {"titulo": f.titulo,
                         "opcoes": [{"id": str(i), "title": t[:30], "description": o[:300]}
                                    for i, (t, o) in enumerate(zip(rotulos, f.opcoes))],
                         "atual": str(f.opcoes.index(f.marcados[0])) if f.marcados and f.marcados[0] in f.opcoes
                         else "0"}
            elif f is not None:
                if len(f.opcoes) > 20:
                    raise ValueError("As caixas de marcar vão até 20 opções.")
                nome, tela, cta, token = FLOW_ESCOLHA, "ESCOLHA", "Marcar", f.token
                dados = {"titulo": f.titulo, "aviso": f.aviso or " ",
                         # o título de cada opção vai até 30 caracteres; o que volta é o índice
                         "opcoes": [{"id": str(i), "title": o[:30]} for i, o in enumerate(f.opcoes)],
                         "marcados": [str(f.opcoes.index(m)) for m in f.marcados if m in f.opcoes]}
            else:
                nome, tela, cta, token = FLOW_CADASTRO, "CADASTRO", "Preencher", c.token
                dados = {"nome": c.nome, "email": c.email, "celular": c.celular}
                for campo, curto in _SISTEMAS.items():
                    lista = [{"id": o.id, "title": o.titulo} for o in c.papeis.get(campo) or []]
                    if not lista:
                        raise ValueError(f"Faltam os papéis de {campo}.")
                    ids = {o["id"] for o in lista}
                    dados[f"papeis_{curto}"] = lista
                    dados[curto] = c.escolhidos.get(campo) if c.escolhidos.get(campo) in ids else lista[0]["id"]
            cred = svc_envio.credencial_de_envio(db)
            flow_id, erro = await graph.id_do_flow(token=cred.token or "", waba_id=cred.waba_id or "", nome=nome)
            if not flow_id:
                return EnvioOut(id=0, ok=False, status="falhou", erro=erro)
            tipo = "interactive"
            conteudo = {"type": "flow", "body": {"text": corpo.texto}, "action": {"name": "flow", "parameters": {
                "flow_message_version": "3", "flow_token": token, "flow_id": flow_id, "flow_cta": cta,
                "flow_action": "navigate", "flow_action_payload": {"screen": tela, "data": dados}}}}
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
            db, telefone=corpo.telefone, tipo=tipo, conteudo=conteudo,
            texto=(corpo.guardar or corpo.texto) if corpo.tipo in ("text", "botoes", "formulario")
            else (corpo.filename or corpo.guardar or corpo.texto),
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
    """Tira a senha de uma mensagem — da linha e, se RECEBIDA, da entrega crua da Meta. O BFF chama logo
    depois de achar a senha de atuação (pedido do dono, 24/10/2026) ou a de equipamento; guardada aqui,
    ela ficaria em claro no banco. Fica o texto sem a senha. A mensagem que SAIU também (a limpeza das
    antigas — avaliação 27)."""
    from sqlalchemy import Text, cast

    m = db.get(Mensagem, mensagem_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mensagem não encontrada.")
    texto = (corpo.texto if corpo and corpo.texto else None) or OCULTO
    m.texto = texto
    if m.wamid and m.direcao == "entrada":
        desde = datetime.now(UTC) - timedelta(days=2)
        for ev in db.scalars(select(WebhookEvento).where(
            WebhookEvento.recebido_em >= desde, cast(WebhookEvento.corpo, Text).contains(m.wamid)
        )):
            ev.corpo = _sem_o_texto(ev.corpo, m.wamid, texto)
    db.commit()


class MascararIn(BaseModel):
    telefone: str
    #: Os valores a esconder (as senhas que o bot só soube depois: o meuPlano as revelou, ou a pessoa as mandou gravar).
    valores: list[str] = Field(max_length=50)
    horas: int = Field(default=24, ge=1, le=72)


@router.post("/mensagens/mascarar", dependencies=[Depends(_porta)])
def mascarar(corpo: MascararIn, db: Session = Depends(get_db)) -> dict:
    """Esconde VALORES (••••) nas mensagens recentes do número, nos dois sentidos, e na entrega crua da Meta: a senha
    de equipamento que a pessoa mandou gravar numa mensagem sem a palavra "senha" só fica conhecida no turno seguinte,
    quando vira a proposta do meuPlano."""
    import re

    from sqlalchemy import Text, cast

    valores = sorted({v for v in corpo.valores if v and len(v) >= 3}, key=len, reverse=True)
    if not valores:
        return {"alteradas": 0}
    padrao = re.compile("|".join(rf"(?<!\w){re.escape(v)}(?!\w)" for v in valores))
    desde = datetime.now(UTC) - timedelta(hours=corpo.horas)
    try:
        telefone = normalizar(corpo.telefone)
    except TelefoneInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    alteradas = 0
    for m in db.scalars(select(Mensagem).where(Mensagem.telefone == telefone, Mensagem.ocorrida_em >= desde)):
        if not m.texto or not padrao.search(m.texto):
            continue
        m.texto = padrao.sub("••••", m.texto)
        alteradas += 1
        if m.direcao == "entrada" and m.wamid:
            for ev in db.scalars(select(WebhookEvento).where(
                WebhookEvento.recebido_em >= desde, cast(WebhookEvento.corpo, Text).contains(m.wamid)
            )):
                ev.corpo = _sem_o_texto(ev.corpo, m.wamid, m.texto)
    db.commit()
    return {"alteradas": alteradas}


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


@router.get("/mensagens/{mensagem_id}/midia", dependencies=[Depends(_porta)])
async def midia_da_mensagem(mensagem_id: int, db: Session = Depends(get_db)) -> Response:
    """O arquivo de uma mensagem RECEBIDA (a nota de voz que o bot transcreve), baixado da Meta
    na hora. Nada fica guardado aqui: só o id do arquivo, que é da Meta."""
    from gateway.meta import graph

    m = db.get(Mensagem, mensagem_id)
    if m is None or m.direcao != "entrada" or not (m.midia or {}).get("id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mensagem sem arquivo.")
    try:
        cred = svc_envio.credencial_de_envio(db)
    except svc_envio.EnvioIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    conteudo, tipo, erro = await graph.baixar_midia(token=cred.token or "", media_id=m.midia["id"])
    if conteudo is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, erro or "A Meta não entregou o arquivo.")
    return Response(content=conteudo, media_type=tipo or (m.midia.get("mime") or "application/octet-stream"))


@router.get("/saude", response_model=SaudeOut, dependencies=[Depends(_porta)])
def saude(db: Session = Depends(get_db)) -> SaudeOut:
    agora = datetime.now(UTC)
    janela = (agora - timedelta(hours=24), agora - timedelta(minutes=2))
    parados = WebhookEvento.processado_em.is_(None) & WebhookEvento.recebido_em.between(*janela)
    com_erro = parados & WebhookEvento.erro.is_not(None)
    # UMA ida ao banco: eram sete, uma atrás da outra (~200 ms cada, o banco está nos EUA), e
    # o selo "Bot ouvindo" levava 2,5 s para aparecer (avaliação 10).
    linha = db.execute(select(
        select(func.count()).select_from(WebhookEvento).where(parados).scalar_subquery(),
        select(func.count()).select_from(WebhookEvento).where(com_erro).scalar_subquery(),
        select(WebhookEvento.erro).where(com_erro).order_by(WebhookEvento.id.desc()).limit(1).scalar_subquery(),
        select(func.count()).select_from(Mensagem).where(
            Mensagem.direcao == "entrada", Mensagem.notificada_bff_em.is_(None),
            Mensagem.criada_em.between(*janela),
        ).scalar_subquery(),
        select(func.max(Mensagem.ocorrida_em)).where(Mensagem.direcao == "entrada").scalar_subquery(),
        select(func.max(Mensagem.ocorrida_em)).where(Mensagem.direcao == "saida").scalar_subquery(),
        select(func.max(Mensagem.status_em)).where(
            Mensagem.direcao == "saida", Mensagem.status.in_(["entregue", "lida"])
        ).scalar_subquery(),
    )).one()
    return SaudeOut(
        eventos_parados=linha[0] or 0,
        eventos_com_erro=linha[1] or 0,
        ultimo_erro=linha[2],
        mensagens_sem_aviso=linha[3] or 0,
        ultima_recebida_em=linha[4],
        ultima_enviada_em=linha[5],
        ultima_entregue_em=linha[6],
    )
