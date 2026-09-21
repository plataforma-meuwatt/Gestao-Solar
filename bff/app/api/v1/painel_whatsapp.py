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

from app.clients import whatsapp as gateway
from app.core.security import exige_area
from app.models.user import User

router = APIRouter(prefix="/api/painel/whatsapp", tags=["painel · whatsapp"])

#: A guarda desta tela inteira, montada uma vez: toda rota daqui exige a mesma área.
EXIGE_WHATSAPP = exige_area("whatsapp")


class CredenciaisIn(BaseModel):
    phone_number_id: str = Field(min_length=1)
    waba_id: str | None = None
    app_id: str | None = None
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
async def ler(_: User = Depends(EXIGE_WHATSAPP)) -> dict:
    """O que está configurado hoje. Nenhum segredo sai daqui."""
    try:
        estado = await gateway.estado()
        # Vai junto porque a tela manda cadastrar este endereço na Meta, e quem está nela
        # não tem por que saber o domínio do gateway no Railway.
        estado["webhook_url"] = gateway.url_do_webhook()
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
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
