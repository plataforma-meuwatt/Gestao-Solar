"""A tela de administração do WhatsApp, no painel.

É aqui que as credenciais da Meta são cadastradas — token, número, segredo do app e token de
verificação do webhook. Elas NÃO moram em variável de ambiente, pelo mesmo motivo que tirou
as pontes do meuWatt e do meuPlano de lá: quem configura é o gestor, e ele precisa testar —
digitar, ver se responde, corrigir. Com segredo em ambiente, cada tentativa custa um
redeploy.

O BFF não guarda nada disso: ele repassa ao gateway, que cifra e guarda no banco dele. O
token não volta por rota nenhuma — o que a tela recebe é o prefixo, o estado e a data.

**Área `whatsapp`.** Quem tem esta tela manda mensagem em nome da empresa para qualquer
cliente, e configura a porta por onde a Meta entrega. É a mesma régua de Conexões: o
administrador abre sempre, e quem é atendimento só se o acesso tiver sido concedido em
Usuários do sistema.
"""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients import whatsapp as gateway
from app.core.db import get_db
from app.core.security import exige_area
from app.models.conversa_whatsapp import RegistroBot
from app.models.empresa import Empresa
from app.models.user import User

router = APIRouter(prefix="/api/painel/whatsapp", tags=["painel · whatsapp"])

#: A guarda desta tela inteira, montada uma vez: toda rota daqui exige a mesma área.
EXIGE_WHATSAPP = exige_area("whatsapp")


class CredenciaisIn(BaseModel):
    phone_number_id: str = Field(min_length=1)
    waba_id: str | None = None
    app_id: str | None = None
    #: A configuração do Embedded Signup (Facebook Login for Business → Configurations). É o
    #: que abre a janela da Meta para cada técnico conectar o número dele.
    es_config_id: str | None = None
    #: Vazio significa "não mexer": quem só corrigiu o WABA não tem mais o token para colar.
    token: str | None = None
    app_secret: str | None = None
    verify_token: str | None = None


class ResultadoOut(BaseModel):
    ok: bool
    detalhe: str


class EventoOut(BaseModel):
    evento: str
    ocorrido_em: datetime
    ator: str | None = None
    token_prefixo: str | None = None
    detalhe: str | None = None


def _erro(exc: gateway.GatewayIndisponivel) -> HTTPException:
    # 503, e não 500: o gateway estar fora ou não configurado é um estado do sistema que o
    # gestor resolve — e a frase já diz o que fazer.
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.get("")
async def ler(db: Session = Depends(get_db), _: User = Depends(EXIGE_WHATSAPP)) -> dict:
    """O que está configurado hoje. Nenhum segredo sai daqui."""
    try:
        estado = await gateway.estado()
        # Vai junto porque a tela manda cadastrar este endereço na Meta, e quem está nela
        # não tem por que saber o domínio do gateway no Railway.
        estado["webhook_url"] = gateway.url_do_webhook()
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    # O autor é o que a conta era quando gravou (e-mail ou apelido): se ela não existe mais
    # (a conta "renanmarquezini" foi juntada à de hoje em 28/09/2026), a tela diz isso.
    autor = estado.get("atualizada_por")
    if autor and db.scalar(select(User.id).where((User.email == autor) | (User.apelido == autor))) is None:
        estado["atualizada_por"] = f"{autor} (conta que não existe mais)"
    return estado


@router.put("", response_model=ResultadoOut)
async def salvar(
    corpo: CredenciaisIn, gestor: User = Depends(EXIGE_WHATSAPP)
) -> ResultadoOut:
    """Grava as credenciais — o gateway testa contra a Meta antes de aceitar.

    Responde 200 mesmo quando a Meta recusa, com `ok: false` e o motivo: o erro é do valor
    colado, não da requisição, e a tela precisa mostrar a frase inteira.
    """
    try:
        r = await gateway.salvar_credenciais(
            {**corpo.model_dump(), "ator": gestor.identificacao}
        )
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return ResultadoOut(**r)


@router.post("/testar", response_model=ResultadoOut)
async def testar(gestor: User = Depends(EXIGE_WHATSAPP)) -> ResultadoOut:
    """Reexercita o que está gravado — o token pode ter sido revogado do outro lado."""
    try:
        r = await gateway.testar_credenciais(gestor.identificacao)
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return ResultadoOut(**r)


@router.delete("", status_code=204)
async def remover(gestor: User = Depends(EXIGE_WHATSAPP)) -> None:
    """Apaga os segredos do gateway. O app continua existindo na Meta — revogar é lá."""
    try:
        await gateway.remover_credenciais(gestor.identificacao)
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc


class NumeroOut(BaseModel):
    id: str
    numero: str | None = None
    nome: str | None = None
    qualidade: str | None = None
    verificado: str | None = None


@router.get("/numeros", response_model=list[NumeroOut])
async def numeros(_: User = Depends(EXIGE_WHATSAPP)) -> list[NumeroOut]:
    """Os números que a conta da Meta tem, para a tela não pedir id de cabeça.

    Foi assim que o primeiro cadastro saiu errado: o número de TESTE foi gravado no lugar
    do comercial, e o teste de envio respondeu "ok" — porque enviar usa o id do número, e
    ele existia. A tela listando o que a conta tem é o que fecha essa porta.
    """
    try:
        brutos = await gateway.numeros()
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return [
        NumeroOut(
            id=str(n.get("id")),
            numero=n.get("display_phone_number"),
            nome=n.get("verified_name"),
            qualidade=n.get("quality_rating"),
            verificado=n.get("code_verification_status"),
        )
        for n in brutos
    ]


class TemplateOut(BaseModel):
    nome: str
    situacao: str
    categoria: str | None = None
    idioma: str | None = None
    #: O texto do corpo, com os `{{1}}` como a Meta os guarda — é o que diz quantos
    #: parâmetros o modelo espera, e mandar a quantidade errada é recusa na hora do envio.
    corpo: str | None = None
    parametros: int = 0


@router.get("/templates", response_model=list[TemplateOut])
async def templates(_: User = Depends(EXIGE_WHATSAPP)) -> list[TemplateOut]:
    """Os modelos aprovados — e os reprovados também.

    Esconder um modelo recusado faria o gestor procurar por que o robô não manda nada,
    quando a resposta está escrita na Meta: o modelo foi rejeitado.
    """
    try:
        brutos = await gateway.templates()
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc

    saida: list[TemplateOut] = []
    for t in brutos:
        corpo = None
        for c in t.get("components") or []:
            if isinstance(c, dict) and c.get("type") == "BODY":
                corpo = c.get("text")
        saida.append(
            TemplateOut(
                nome=str(t.get("name")),
                situacao=str(t.get("status")),
                categoria=t.get("category"),
                idioma=t.get("language"),
                corpo=corpo,
                parametros=len(re.findall(r"\{\{\s*\d+\s*\}\}", corpo or "")),
            )
        )
    return saida


class TesteIn(BaseModel):
    telefone: str = Field(min_length=8)
    template: str = Field(min_length=1, max_length=80)
    parametros: list[str] = []
    idioma: str = "pt_BR"


class TesteEnvioOut(BaseModel):
    ok: bool
    wamid: str | None = None
    status: str
    erro: str | None = None


@router.post("/enviar-teste", response_model=TesteEnvioOut)
async def enviar_teste(corpo: TesteIn, gestor: User = Depends(EXIGE_WHATSAPP)) -> TesteEnvioOut:
    """Manda um modelo para um número escolhido, pela tela.

    É o único envio que não passa pelo motor de notificações, e existe para provar a ponte
    inteira — credencial, template aprovado, cobrança e entrega — antes de qualquer cliente
    depender dela. A origem fica marcada como `painel` no histórico, para nunca ser
    confundida com aviso automático.
    """
    try:
        r = await gateway.enviar_template(
            telefone=corpo.telefone,
            template=corpo.template,
            parametros=corpo.parametros,
            origem=f"painel:{gestor.apelido}",
        )
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return TesteEnvioOut(
        ok=bool(r.get("ok")),
        wamid=r.get("wamid"),
        status=str(r.get("status")),
        erro=r.get("erro"),
    )


@router.get("/eventos", response_model=list[EventoOut])
async def eventos(limite: int = 30, _: User = Depends(EXIGE_WHATSAPP)) -> list[EventoOut]:
    """O histórico da configuração: quem gravou, quando, e o que o teste respondeu."""
    try:
        return [EventoOut(**e) for e in await gateway.eventos(limite)]
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc


# ------------------------------------------------------------------ log do bot

#: Área própria: quem lê o log lê as perguntas e respostas das pessoas — não é o mesmo que
#: configurar o número.
EXIGE_BOT = exige_area("bot")


class RegistroBotOut(BaseModel):
    """Uma mensagem que chegou ao assistente, e o que ele fez com ela."""

    id: int
    em: datetime
    telefone: str
    usuario_id: int | None = None
    usuario: str | None = None
    apelido: str | None = None
    empresa: str | None = None
    #: `respondeu` · `sem_conta` · `nao_liberado` · `sem_texto` · `zerou` · `erro`
    resultado: str
    ferramentas: list[str] = []
    pergunta: str | None = None
    resposta: str | None = None
    duracao_ms: int | None = None
    erro: str | None = None


def registros_do_bot(
    db: Session, *, empresa_id: int | None = None, usuario_id: int | None = None,
    resultado: str | None = None, limite: int = 200,
) -> list[RegistroBotOut]:
    """O log, do mais novo para o mais velho. Uma fonte para o adm-gs (tudo) e o oem-gs
    (só as contas da empresa)."""
    # Pela hora em que a pessoa mandou: a mensagem que chegou atrasada entra no lugar dela.
    consulta = (
        select(RegistroBot)
        .order_by(RegistroBot.em.desc(), RegistroBot.id.desc())
        .limit(max(1, min(limite, 500)))
    )
    if empresa_id is not None:
        consulta = consulta.where(RegistroBot.empresa_id == empresa_id)
    if usuario_id is not None:
        consulta = consulta.where(RegistroBot.gs_user_id == usuario_id)
    if resultado:
        consulta = consulta.where(RegistroBot.resultado == resultado)
    linhas = db.scalars(consulta).all()
    contas = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.id.in_({r.gs_user_id for r in linhas if r.gs_user_id}))
        ).all()
    }
    nomes = {e.id: e.nome for e in db.scalars(select(Empresa)).all()}
    return [
        RegistroBotOut(
            id=r.id, em=r.em, telefone=r.telefone, usuario_id=r.gs_user_id,
            usuario=contas[r.gs_user_id].nome if r.gs_user_id in contas else None,
            apelido=contas[r.gs_user_id].apelido if r.gs_user_id in contas else None,
            empresa=nomes.get(r.empresa_id) if r.empresa_id else None,
            resultado=r.resultado,
            ferramentas=[f for f in (r.ferramentas or "").split(",") if f],
            pergunta=r.pergunta, resposta=r.resposta, duracao_ms=r.duracao_ms, erro=r.erro,
        )
        for r in linhas
    ]


@router.get("/bot/registros", response_model=list[RegistroBotOut])
def log_do_bot(
    empresa_id: int | None = None,
    usuario_id: int | None = None,
    resultado: str | None = None,
    limite: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(EXIGE_BOT),
) -> list[RegistroBotOut]:
    """O log do assistente do WhatsApp (adm-gs → Log do bot): tudo, ou recortado por
    empresa, pessoa ou resultado. Inclui os números sem cadastro que tentaram falar."""
    return registros_do_bot(
        db, empresa_id=empresa_id, usuario_id=usuario_id, resultado=resultado, limite=limite
    )


class SaudeDoCanalOut(BaseModel):
    """Se o bot está OUVINDO — e não só configurado. Em 10/2026 a tela dizia "webhook pronto"
    enquanto 40 mensagens ficaram presas no gateway por um erro de banco, por mais de um dia."""

    ouvindo: bool
    #: A frase que resume (ex.: "3 entregas paradas no gateway — StringDataRightTruncation").
    resumo: str
    eventos_parados: int | None = None
    eventos_com_erro: int | None = None
    ultimo_erro: str | None = None
    mensagens_sem_aviso: int | None = None
    ultima_recebida_em: datetime | None = None
    ultima_entregue_em: datetime | None = None
    #: A última vez que o BOT respondeu alguém (o log daqui).
    ultima_resposta_em: datetime | None = None
    #: O helper responde ao bot agora? `None` = não configurado neste ambiente.
    helper_alcancavel: bool | None = None
    helper_resumo: str | None = None
    #: A causa, curta ("VPN das usinas parada" / "helper fora do ar"), para o selo.
    helper_rotulo: str | None = None


@router.get("/saude", response_model=SaudeDoCanalOut)
async def saude_do_canal(db: Session = Depends(get_db), _: User = Depends(EXIGE_BOT)) -> SaudeDoCanalOut:
    return await saude_atual(db)


async def saude_atual(db: Session) -> SaudeDoCanalOut:
    """A conta do canal inteiro (o número é UM, o da plataforma) — o oem-gs lê o `ouvindo`."""
    import asyncio

    from app.services import assistente_helper

    async def _helper() -> tuple[bool | None, str]:
        try:
            return await assistente_helper.alcancavel()
        except Exception as exc:                           # noqa: BLE001 — o selo nunca derruba a tela
            return False, f"Não deu para conferir o helper: {exc}"

    # Gateway e helper ao mesmo tempo: um depois do outro, o selo levava 2,7 s (avaliação 10).
    saida, helper = await asyncio.gather(_saude_do_canal(db), _helper())
    saida.helper_alcancavel, saida.helper_resumo = helper
    saida.helper_rotulo = assistente_helper.rotulo_do_helper(*helper)
    return saida


async def _saude_do_canal(db: Session) -> SaudeDoCanalOut:
    ultima_resposta = db.scalar(
        select(func.max(RegistroBot.em)).where(RegistroBot.resultado == "respondeu")
    )
    try:
        g = await gateway.saude()
    except gateway.GatewayIndisponivel as exc:
        return SaudeDoCanalOut(ouvindo=False, resumo=f"O gateway não respondeu: {exc}",
                               ultima_resposta_em=ultima_resposta)
    parados, sem_aviso = g.get("eventos_parados") or 0, g.get("mensagens_sem_aviso") or 0
    if parados or sem_aviso:
        partes = []
        if parados:
            partes.append(f"{parados} entrega(s) da Meta parada(s) no gateway")
        if sem_aviso:
            partes.append(f"{sem_aviso} mensagem(ns) que o bot ainda não recebeu")
        resumo = " · ".join(partes) + (f" — último erro: {g['ultimo_erro']}" if g.get("ultimo_erro") else "")
    else:
        resumo = "Ouvindo: nada parado no gateway."
    return SaudeDoCanalOut(
        ouvindo=not (parados or sem_aviso),
        resumo=resumo,
        eventos_parados=parados,
        eventos_com_erro=g.get("eventos_com_erro"),
        ultimo_erro=g.get("ultimo_erro"),
        mensagens_sem_aviso=sem_aviso,
        ultima_recebida_em=g.get("ultima_recebida_em"),
        ultima_entregue_em=g.get("ultima_entregue_em"),
        ultima_resposta_em=ultima_resposta,
    )
