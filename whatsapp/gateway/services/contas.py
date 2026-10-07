"""Conectar, listar e desconectar o WhatsApp Business de cada técnico.

## A ordem da conexão, e por que nada é gravado antes do fim

1. trocar o `code` pelo token — o code vive 30 s, por isso o BFF chama na hora;
2. conferir que o número pertence àquela WABA, com o token novo;
3. assinar o webhook do app da plataforma na WABA (`subscribed_apps`);
4. fora da coexistência, registrar o número com um PIN nosso; DENTRO dela, pedir os
   contatos e o histórico do celular (`smb_app_data`) — e nunca registrar.

Só depois disso a linha é gravada. É a mesma regra de `credenciais.salvar`: gravar
primeiro deixaria na tela um número "conectado" que não recebe nada.

## Um número, um dono

`phone_number_id` é UNIQUE em `wa_contas`. Se o número já está conectado por OUTRA conta,
a conexão é recusada antes de falar com a Meta: aceitar seria entregar ao técnico B a
conversa do técnico A — e é exatamente o balaio que o `MULTIEMPRESA.md` existe para evitar.
Um número DESCONECTADO pode ser assumido por outra conta: o dono anterior saiu dele.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.core import cripto
from gateway.meta import graph
from gateway.meta.payload import AvisoDeConta
from gateway.models.conta import Conta
from gateway.services import credenciais
from gateway.services.credenciais import Resultado

log = logging.getLogger(__name__)

#: Os eventos de `account_update` que tiram o número do ar para nós.
EVENTOS_DE_DESCONEXAO = ("PARTNER_REMOVED", "PARTNER_APP_UNINSTALLED", "ACCOUNT_OFFBOARDED")

#: O motivo da Meta, dito para o técnico. Ele precisa saber o que FAZER, não o código.
_MOTIVO = {
    "PRIMARY_INACTIVITY": (
        "O WhatsApp Business do celular ficou cerca de 14 dias sem abrir e a Meta "
        "desconectou o número. Abra o aplicativo no celular e conecte de novo."
    ),
    "CHANGE_NUMBER": "O número foi trocado no aplicativo do celular. Conecte o número novo.",
    "USER_RE_REGISTERED": (
        "O número foi registrado de novo em outro aparelho e a Meta o desconectou. "
        "Conecte de novo."
    ),
}


def _por_numero(db: Session, phone_number_id: str) -> Conta | None:
    return db.scalar(select(Conta).where(Conta.phone_number_id == phone_number_id))


def configuracao(db: Session) -> dict[str, Any]:
    """O que o navegador precisa para abrir a janela da Meta. Nenhum segredo."""
    p = credenciais.em_uso(db)
    return {
        "app_id": p.app_id,
        "config_id": p.es_config_id,
        "pronto": bool(p.app_id and p.app_secret and p.es_config_id),
    }


def listar(db: Session, gs_user_id: int) -> list[Conta]:
    return list(
        db.scalars(
            select(Conta).where(Conta.gs_user_id == gs_user_id).order_by(Conta.conectada_em.desc())
        ).all()
    )


async def conectar(
    db: Session,
    *,
    code: str,
    waba_id: str,
    phone_number_id: str,
    gs_user_id: int,
    empresa_id: int | None,
    coexistencia: bool,
    business_id: str | None = None,
    ator: str | None = None,
) -> Resultado:
    plataforma = credenciais.em_uso(db)
    if not (plataforma.app_id and plataforma.app_secret):
        return Resultado(
            False,
            "O app da plataforma na Meta ainda não está configurado (App ID e segredo do "
            "app). Peça ao administrador para completar a tela do WhatsApp.",
        )
    if not cripto.disponivel():
        return Resultado(False, "GATEWAY_ENCRYPTION_KEY não configurada no serviço.")

    existente = _por_numero(db, phone_number_id)
    if existente is not None and existente.gs_user_id != gs_user_id and existente.conectada:
        # Antes de falar com a Meta: o code é descartável, a conversa do outro técnico não.
        return Resultado(
            False,
            "Este número já está conectado por outra conta. Peça que ela o desconecte "
            "antes de conectar aqui.",
        )

    token, erro = await graph.trocar_code(
        app_id=plataforma.app_id, app_secret=plataforma.app_secret, code=code
    )
    if erro or not token:
        return Resultado(False, f"A Meta recusou a conexão: {erro}")

    numeros, erro = await graph.listar_numeros(token=token, waba_id=waba_id)
    if erro:
        return Resultado(False, f"A Meta não deixou ler a conta conectada: {erro}")
    numero = next((n for n in numeros if str(n.get("id")) == phone_number_id), None)
    if numero is None:
        return Resultado(False, "O número escolhido não pertence à conta conectada.")

    erro = await graph.assinar_waba(token=token, waba_id=waba_id)
    if erro:
        return Resultado(False, f"A Meta recusou ligar as mensagens deste número: {erro}")

    pin = None
    detalhe = "Conectado."
    if coexistencia:
        # O número segue no celular: registrar seria tirá-lo de lá. Os dois syncs trazem
        # contatos e 6 meses de conversa, e têm de acontecer em 24 h. Falha aqui não
        # desfaz a conexão — as mensagens novas já chegam —, mas o técnico precisa saber.
        falhas = [
            f"{tipo}: {e}"
            for tipo in ("smb_app_state_sync", "history")
            if (e := await graph.sincronizar_aplicativo(
                token=token, phone_number_id=phone_number_id, tipo=tipo
            ))
        ]
        if falhas:
            detalhe = (
                "Conectado, mas o histórico do celular não veio (" + "; ".join(falhas) + "). "
                "As mensagens novas chegam normalmente. Para trazer o histórico, desconecte "
                "e conecte de novo em até 24 horas."
            )
    else:
        pin = f"{secrets.randbelow(10**6):06d}"
        erro = await graph.registrar_numero(token=token, phone_number_id=phone_number_id, pin=pin)
        if erro:
            return Resultado(False, f"A Meta recusou registrar o número: {erro}")

    conta = existente or Conta(phone_number_id=phone_number_id)
    conta.waba_id = waba_id
    conta.business_id = business_id
    conta.numero_exibicao = numero.get("display_phone_number")
    conta.nome_verificado = numero.get("verified_name")
    conta.coexistencia = coexistencia
    conta.token_cifrado = cripto.cifrar(token)
    conta.token_prefixo = token[:7]
    conta.pin_cifrado = cripto.cifrar(pin) if pin else conta.pin_cifrado
    conta.gs_user_id = gs_user_id
    conta.empresa_id = empresa_id
    conta.estado = "conectada"
    conta.detalhe = detalhe
    conta.conectada_em = datetime.now(UTC)
    conta.desconectada_em = None
    db.add(conta)
    credenciais.registrar(
        db, "conta_conectada", ator=ator, token_prefixo=conta.token_prefixo,
        detalhe=f"{conta.numero_exibicao or phone_number_id} — conta {gs_user_id}",
    )
    db.commit()
    return Resultado(True, detalhe)


async def desconectar(
    db: Session, *, phone_number_id: str, gs_user_id: int, ator: str | None = None
) -> bool:
    """Tira o número daqui. Devolve `False` se ele não é desta conta — e a rota diz 404.

    Desassinar o webhook é melhor esforço: se a Meta não responder, o número sai daqui do
    mesmo jeito, e o que ainda chegar dele cai em "número desconhecido" e não é repassado.
    """
    conta = _por_numero(db, phone_number_id)
    if conta is None or conta.gs_user_id != gs_user_id:
        return False
    if conta.token_cifrado:
        erro = await graph.desassinar_waba(token=cripto.decifrar(conta.token_cifrado), waba_id=conta.waba_id)
        if erro:
            log.warning("contas: desassinar a WABA %s falhou: %s", conta.waba_id, erro)
    _desligar(conta, "Desconectado pelo técnico.")
    credenciais.registrar(
        db, "conta_desconectada", ator=ator,
        detalhe=f"{conta.numero_exibicao or phone_number_id} — conta {gs_user_id}",
    )
    db.commit()
    return True


def _desligar(conta: Conta, detalhe: str) -> None:
    conta.estado = "desconectada"
    conta.token_cifrado = None
    conta.detalhe = detalhe
    conta.desconectada_em = datetime.now(UTC)


def aplicar_aviso(db: Session, aviso: AvisoDeConta) -> int:
    """`account_update` da Meta. Devolve quantas contas mudaram. NÃO faz commit.

    O `ACCOUNT_OFFBOARDED` documentado não traz `waba_id`, e aí não há como saber qual
    número caiu: fica no evento cru (`wa_webhook_eventos`), e não se chuta um.
    """
    if aviso.evento not in EVENTOS_DE_DESCONEXAO or not aviso.waba_id:
        return 0
    detalhe = _MOTIVO.get(aviso.motivo or "", f"A Meta desconectou o número ({aviso.evento}).")
    contas = db.scalars(
        select(Conta).where(Conta.waba_id == aviso.waba_id, Conta.estado == "conectada")
    ).all()
    for conta in contas:
        _desligar(conta, detalhe)
        credenciais.registrar(db, "conta_desconectada", ator="meta", detalhe=detalhe)
    return len(contas)
