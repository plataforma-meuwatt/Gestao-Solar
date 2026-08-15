"""O disparador dos avisos por push.

É uma rota, e não um laço interno do processo, por duas razões práticas: o
Railway pode rodar mais de uma instância, e duas instâncias com laço próprio
mandariam o aviso em dobro; e uma rota é chamável na hora, o que torna possível
testar sem esperar o relógio.

**A autenticação não é de usuário.** Quem chama é um agendador, que não tem
login. A porta é um segredo em variável de ambiente (`AVISOS_TOKEN`), conferido
com comparação de tempo constante. **Sem a variável configurada a rota recusa
tudo** — falhar fechado é o único padrão aceitável para um endpoint que envia
mensagem ao celular de todo mundo.
"""

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.permissao import AvisoEnviado, Dispositivo
from app.services import avisos, push

router = APIRouter(prefix="/api/v1/interno", tags=["interno · avisos"])


class DisparoOut(BaseModel):
    #: Avisos que caberiam agora, antes da trava de repetição.
    candidatos: int = 0
    #: Bloqueados por já terem sido enviados. Alto é sinal de saúde, não de erro.
    repetidos: int = 0
    enviados: int = 0
    #: Aparelhos que o Expo declarou mortos e que foram apagados.
    dispositivos_removidos: int = 0
    #: Sem ninguém com permissão, ou sem aparelho registrado.
    sem_destino: int = 0
    erros: list[str] = []


def _porta(x_avisos_token: str | None = Header(default=None)) -> None:
    esperado = os.environ.get("AVISOS_TOKEN") or ""
    if not esperado:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Disparo de avisos não configurado (AVISOS_TOKEN ausente).",
        )
    # `compare_digest` em vez de `==`: a comparação ingênua vaza o segredo pelo tempo
    # de resposta, um caractere por vez.
    if not hmac.compare_digest(x_avisos_token or "", esperado):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido.")


@router.post("/avisos/paradas", response_model=DisparoOut, dependencies=[Depends(_porta)])
async def disparar_avisos_de_parada(
    simular: bool = False,
    db: Session = Depends(get_db),
) -> DisparoOut:
    """Avisa quem tem permissão sobre os inversores parados nas usinas dele.

    `simular=true` percorre tudo e devolve a contagem sem enviar nem gravar — é como
    conferir a régua antes de acordar alguém às três da manhã.
    """
    saida = DisparoOut()

    candidatos = await avisos.paradas_por_usuario(db)
    saida.candidatos = len(candidatos)
    if not candidatos:
        return saida

    # Uma consulta para todas as chaves, em vez de uma por aviso: numa usina com
    # dez inversores parados e cinco clientes, seriam cinquenta idas ao banco.
    ja_enviados = set(
        db.execute(
            select(AvisoEnviado.user_id, AvisoEnviado.chave).where(
                AvisoEnviado.chave.in_([c.chave for c in candidatos])
            )
        ).all()
    )

    novos = [c for c in candidatos if (c.usuario.id, c.chave) not in ja_enviados]
    saida.repetidos = len(candidatos) - len(novos)
    if not novos:
        return saida

    # Agrupado por pessoa: os tokens dela são os mesmos para todos os avisos, e
    # consultá-los por aviso repetiria a query.
    por_usuario: dict[int, list[avisos.AvisoDeParada]] = {}
    for c in novos:
        por_usuario.setdefault(c.usuario.id, []).append(c)

    mortos: set[str] = set()
    for lista in por_usuario.values():
        pessoa = lista[0].usuario
        tokens = avisos.tokens_do_usuario(db, pessoa)
        if not tokens:
            # Tem permissão e nunca abriu o app, ou negou o aviso no Android. Não é
            # erro — e não marcamos como enviado, para que ele receba quando registrar.
            saida.sem_destino += len(lista)
            continue

        for aviso in lista:
            titulo, corpo, dados = avisos.texto_do_aviso(aviso)
            if simular:
                saida.enviados += 1
                continue

            resultado = await push.enviar(tokens, titulo, corpo, dados)
            saida.enviados += resultado.enviados
            saida.erros.extend(resultado.erros)
            mortos.update(resultado.invalidos)

            # A trava é gravada mesmo quando a entrega falhou por rede: reenviar em
            # laço um aviso que o Expo recusou transformaria uma falha em enxurrada.
            # Se a parada persistir, o `down_since` continua o mesmo — e é justamente
            # esse o caso em que não se deve avisar de novo.
            db.add(AvisoEnviado(user_id=pessoa.id, chave=aviso.chave))

    if not simular:
        for token in mortos:
            db.execute(
                Dispositivo.__table__.delete().where(Dispositivo.token == token)
            )
        saida.dispositivos_removidos = len(mortos)
        db.commit()

    return saida
