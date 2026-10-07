"""O portão do técnico: o WhatsApp Business DELE, e mais nada.

O técnico da empresa de O&M entra no painel para conectar o número dele pelo Embedded
Signup da Meta. É esse número que o help-desk do meuPlano passa a usar nas conversas dos
tickets dele (fase T4 de `docs/PLANO_WHATSAPP_TECNICOS.md`).

**Nenhuma rota daqui recebe id de conta.** O técnico é quem está logado: `gs_user_id` e
`empresa_id` saem da sessão e vão para o gateway. Um id no corpo seria a forma de um
técnico conectar — ou desconectar — o número de outro.

**O `code` vive 30 segundos na Meta.** O navegador entrega assim que a janela fecha, e esta
rota repassa na hora; nada aqui pode ficar entre os dois (fila, confirmação, outra tela).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.clients import whatsapp as gateway
from app.core.db import get_db
from app.core.security import tecnico_atual
from app.models.integracao import Produto
from app.models.user import User
from app.services import empresas, vinculos

router = APIRouter(prefix="/api/tecnico", tags=["técnico"])

#: O evento do Embedded Signup quando o número veio do aplicativo do celular — conferido
#: na documentação da Meta em 07/10/2026. É ele que diz ao gateway para NÃO registrar.
EVENTO_COEXISTENCIA = "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"


def _erro(exc: gateway.GatewayIndisponivel) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


class MeuPlanoOut(BaseModel):
    #: Sem a conta do meuPlano ligada, o número conecta mas não tem a que ticket servir:
    #: é ela que diz "este é o usuário 42 de lá". Quem liga é o gerente, em Usuários.
    vinculado: bool
    nome: str | None = None
    email: str | None = None


class EuOut(BaseModel):
    nome: str
    apelido: str
    empresa: str | None = None
    meuplano: MeuPlanoOut


@router.get("/eu", response_model=EuOut)
def eu(db: Session = Depends(get_db), tecnico: User = Depends(tecnico_atual)) -> EuOut:
    v = vinculos.obter(db, tecnico.id, Produto.MEUPLANO)
    empresa = empresas.por_id(db, tecnico.empresa_id) if tecnico.empresa_id else None
    return EuOut(
        nome=tecnico.nome,
        apelido=tecnico.apelido,
        empresa=empresa.nome if empresa else None,
        meuplano=MeuPlanoOut(
            vinculado=v is not None,
            nome=v.usuario_remoto_nome if v else None,
            email=v.usuario_remoto_email if v else None,
        ),
    )


class ContaOut(BaseModel):
    phone_number_id: str
    numero_exibicao: str | None = None
    nome_verificado: str | None = None
    coexistencia: bool
    estado: str
    detalhe: str | None = None
    conectada_em: datetime
    desconectada_em: datetime | None = None


class WhatsappOut(BaseModel):
    #: `app_id` e `config_id` abrem a janela da Meta no navegador; `pronto` é falso
    #: enquanto o administrador da plataforma não completou a configuração do app.
    app_id: str | None = None
    config_id: str | None = None
    #: A versão da Graph que o gateway usa — o `FB.init` do navegador fala a mesma.
    versao: str | None = None
    pronto: bool
    contas: list[ContaOut]


@router.get("/whatsapp", response_model=WhatsappOut)
async def meu_whatsapp(tecnico: User = Depends(tecnico_atual)) -> WhatsappOut:
    try:
        cfg = await gateway.configuracao_das_contas()
        contas = await gateway.contas_de(tecnico.id)
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return WhatsappOut(**cfg, contas=[ContaOut(**c) for c in contas])


class ConectarIn(BaseModel):
    code: str = Field(min_length=1)
    waba_id: str = Field(min_length=1)
    phone_number_id: str = Field(min_length=1)
    business_id: str | None = None
    #: O `event` que a janela da Meta devolveu (`FINISH`, `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`…).
    evento: str | None = None


class ResultadoOut(BaseModel):
    ok: bool
    detalhe: str


@router.post("/whatsapp", response_model=ResultadoOut)
async def conectar(corpo: ConectarIn, tecnico: User = Depends(tecnico_atual)) -> ResultadoOut:
    """Responde 200 com `ok: false` quando a Meta recusa: o erro é do fluxo, não da
    requisição, e a tela precisa da frase inteira."""
    try:
        r = await gateway.conectar_conta(
            {
                "code": corpo.code,
                "waba_id": corpo.waba_id,
                "phone_number_id": corpo.phone_number_id,
                "business_id": corpo.business_id,
                "coexistencia": corpo.evento == EVENTO_COEXISTENCIA,
                "gs_user_id": tecnico.id,
                "empresa_id": tecnico.empresa_id,
                "ator": tecnico.identificacao,
            }
        )
    except gateway.GatewayIndisponivel as exc:
        raise _erro(exc) from exc
    return ResultadoOut(**r)


@router.delete("/whatsapp/{phone_number_id}", status_code=204)
async def desconectar(phone_number_id: str, tecnico: User = Depends(tecnico_atual)) -> None:
    try:
        await gateway.desconectar_conta(phone_number_id, tecnico.id, tecnico.identificacao)
    except gateway.GatewayIndisponivel as exc:
        # O 404 do gateway ("não é desta conta") chega aqui como frase: devolvê-lo como 404
        # mantém número de outro e número inexistente indistinguíveis.
        if exc.status == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        raise _erro(exc) from exc
