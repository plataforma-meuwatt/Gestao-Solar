"""As rotas do motor de notificações e da bateria de autoteste.

Três portas, para três chamadores diferentes:

- **`POST /api/v1/interno/notificacoes/disparar`** — o agendador. Mesma régua de
  `avisos.py`: segredo em cabeçalho (`X-Avisos-Token`), comparação em tempo constante e
  falha-fechado sem a variável configurada.
- **`POST /api/painel/notificacoes/disparar`** — o gestor, pela tela, quando quer rodar
  agora em vez de esperar o agendador. Exige a área `notificacoes`.
- **`POST /api/painel/autoteste`** — a bateria que prova o caminho inteiro sem alterar
  nada. Exige a área `diagnostico`, porque é disso que se trata.

O disparo é **idempotente**: a trava está em `gs_notificacoes_enviadas` (único por
`user_id + chave`), então chamar duas vezes não manda duas vezes. É o que permite ao
agendador rodar de dez em dez minutos sem coordenação nenhuma.
"""

import hmac
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import exige_area
from app.models.user import User
from app.services import autoteste as bateria
from app.services import motor

router = APIRouter(tags=["notificações · motor"])

EXIGE_NOTIFICACOES = exige_area("notificacoes")
EXIGE_DIAGNOSTICO = exige_area("diagnostico")


def _porta(x_avisos_token: str | None = Header(default=None)) -> None:
    esperado = os.environ.get("AVISOS_TOKEN") or ""
    if not esperado:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Disparo não configurado (AVISOS_TOKEN ausente).",
        )
    if not hmac.compare_digest(x_avisos_token or "", esperado):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido.")


class LinhaOut(BaseModel):
    tipo: str
    chave: str
    usuario: str
    usina: str
    situacao: str
    detalhe: str | None = None


class DisparoOut(BaseModel):
    #: Quantos acontecimentos os coletores encontraram — antes de qualquer filtro de pessoa.
    eventos: int
    enviadas: int
    falhas: int
    #: Bloqueadas pela trava de repetição. Número alto é sinal de saúde, não de erro.
    repetidas: int
    simuladas: int
    avisos: list[str]
    linhas: list[LinhaOut]


def _saida(rel: motor.Relatorio) -> DisparoOut:
    return DisparoOut(
        eventos=rel.eventos,
        enviadas=rel.enviadas,
        falhas=rel.falhas,
        repetidas=rel.repetidas,
        simuladas=rel.simuladas,
        avisos=rel.avisos,
        linhas=[
            LinhaOut(
                tipo=l.tipo,
                chave=l.chave,
                usuario=l.usuario,
                usina=l.usina,
                situacao=l.situacao,
                detalhe=l.detalhe,
            )
            for l in rel.linhas
        ],
    )


@router.post(
    "/api/v1/interno/notificacoes/disparar",
    response_model=DisparoOut,
    dependencies=[Depends(_porta)],
)
async def disparar_interno(
    simular: bool = False,
    tipos: str | None = None,
    db: Session = Depends(get_db),
) -> DisparoOut:
    """O agendador chama isto. `tipos` separa por vírgula; ausente vale todos."""
    escolhidos = [t.strip() for t in tipos.split(",")] if tipos else None
    return _saida(await motor.disparar(db, tipos=escolhidos, simular=simular))


@router.post("/api/painel/notificacoes/disparar", response_model=DisparoOut)
async def disparar_do_painel(
    simular: bool = True,
    tipos: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(EXIGE_NOTIFICACOES),
) -> DisparoOut:
    """O gestor rodando agora.

    `simular` vem **ligado por padrão**, ao contrário da rota do agendador: um clique
    distraído na tela não pode mandar mensagem para cliente. Quem quer enviar de verdade
    desliga a simulação explicitamente.
    """
    escolhidos = [t.strip() for t in tipos.split(",")] if tipos else None
    return _saida(await motor.disparar(db, tipos=escolhidos, simular=simular))


class ItemOut(BaseModel):
    chave: str
    titulo: str
    situacao: str
    detalhe: str
    evidencia: dict[str, Any] = {}


class AutotesteOut(BaseModel):
    executado_em: datetime
    duracao_ms: int
    passou: bool
    resumo: dict[str, int]
    itens: list[ItemOut]


@router.post("/api/painel/autoteste", response_model=AutotesteOut)
async def autoteste(
    db: Session = Depends(get_db), _: User = Depends(EXIGE_DIAGNOSTICO)
) -> AutotesteOut:
    """Roda a bateria inteira contra o ambiente real. Não envia nada, não grava nada."""
    r = await bateria.executar(db)
    return AutotesteOut(
        executado_em=r.executado_em,
        duracao_ms=r.duracao_ms,
        passou=r.passou,
        resumo=r.resumo,
        itens=[
            ItemOut(
                chave=i.chave,
                titulo=i.titulo,
                situacao=i.situacao,
                detalhe=i.detalhe,
                evidencia=i.evidencia,
            )
            for i in r.itens
        ],
    )
