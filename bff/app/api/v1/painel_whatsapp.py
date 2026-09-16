"""A tela de administração do WhatsApp, no painel.

É aqui que as credenciais da Meta são cadastradas — token, número, segredo do app e token de
verificação do webhook. Elas NÃO moram em variável de ambiente, pelo mesmo motivo que tirou
as pontes do meuWatt e do meuPlano de lá: quem configura é o gestor, e ele precisa testar —
digitar, ver se responde, corrigir. Com segredo em ambiente, cada tentativa custa um
redeploy.

O BFF não guarda nada disso: ele repassa ao gateway, que cifra e guarda no banco dele. O
token não volta por rota nenhuma — o que a tela recebe é o prefixo, o estado e a data.

**Só administrador.** Quem tem esta tela manda mensagem em nome da empresa para qualquer
cliente, e configura a porta por onde a Meta entrega. É a mesma régua de Conexões.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.clients import whatsapp as gateway
from app.core.security import administrador_atual
from app.models.user import User

router = APIRouter(prefix="/api/painel/whatsapp", tags=["painel · whatsapp"])


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
async def ler(_: User = Depends(administrador_atual)) -> dict:
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
    corpo: CredenciaisIn, gestor: User = Depends(administrador_atual)
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
async def testar(gestor: User = Depends(administrador_atual)) -> ResultadoOut:
    """Reexercita o que está gravado — o token pode ter sido revogado do outro lado."""
    try:
        r = await gateway.testar_credenciais(gestor.identificacao)
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return ResultadoOut(**r)


@router.delete("", status_code=204)
async def remover(gestor: User = Depends(administrador_atual)) -> None:
    """Apaga os segredos do gateway. O app continua existindo na Meta — revogar é lá."""
    try:
        await gateway.remover_credenciais(gestor.identificacao)
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc


@router.get("/eventos", response_model=list[EventoOut])
async def eventos(limite: int = 30, _: User = Depends(administrador_atual)) -> list[EventoOut]:
    """O histórico da configuração: quem gravou, quando, e o que o teste respondeu."""
    try:
        return [EventoOut(**e) for e in await gateway.eventos(limite)]
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
