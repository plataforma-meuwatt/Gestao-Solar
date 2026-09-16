"""Mandar mensagem — e deixar registro do que aconteceu, inclusive quando falha.

A linha nasce `pendente` ANTES da chamada à Meta. Se a Graph recusar, ela vira `falhou` com
o código e a frase; se a rede cair no meio, ela fica `pendente` e alguém consegue ver que
houve tentativa. Gravar só depois do sucesso deixaria o pior caso — o envio que ninguém
sabe se saiu — sem rastro nenhum.

O `wamid` só existe depois de a Meta aceitar, e é por ele que os avisos de status voltam
(`enviada → entregue → lida`). Entre a resposta da Graph e o primeiro status pode passar um
tempo; a mensagem fica `enviada`, que é a verdade: saiu daqui, ninguém confirmou entrega.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from gateway.core.telefone import TelefoneInvalido, normalizar
from gateway.meta import graph
from gateway.models.mensagem import Mensagem
from gateway.services import credenciais


class EnvioIndisponivel(RuntimeError):
    """Sem credencial gravada. A rota responde 503 com esta frase, não 500."""


@dataclass
class Envio:
    id: int
    ok: bool
    wamid: str | None
    status: str
    erro: str | None


async def enviar_template(
    db: Session,
    *,
    telefone: str,
    template: str,
    parametros: list[str],
    idioma: str = "pt_BR",
    origem: str | None = None,
) -> Envio:
    cred = credenciais.em_uso(db)
    if not cred.envio_pronto:
        raise EnvioIndisponivel(
            "WhatsApp ainda não configurado: cadastre o token e o número na tela de "
            "administração do WhatsApp, no painel."
        )

    try:
        destino = normalizar(telefone)
    except TelefoneInvalido as exc:
        raise ValueError(str(exc)) from exc
    if not destino:
        raise ValueError("Telefone vazio.")

    agora = datetime.now(UTC)
    mensagem = Mensagem(
        direcao="saida",
        wa_id=destino.lstrip("+"),
        telefone=destino,
        tipo="template",
        template=template,
        texto=" · ".join(str(p) for p in parametros) or None,
        ocorrida_em=agora,
        status="pendente",
        status_em=agora,
        origem=origem,
    )
    db.add(mensagem)
    db.commit()
    db.refresh(mensagem)

    r = await graph.enviar_template(
        token=cred.token or "",
        phone_number_id=cred.phone_number_id or "",
        telefone=destino,
        template=template,
        parametros=parametros,
        idioma=idioma,
    )

    if r.ok:
        mensagem.wamid = r.wamid
        mensagem.status = "enviada"
    else:
        mensagem.status = "falhou"
        mensagem.erro_codigo = r.erro_codigo
        mensagem.erro_detalhe = r.erro_detalhe
    mensagem.status_em = datetime.now(UTC)
    db.commit()

    return Envio(
        id=mensagem.id,
        ok=r.ok,
        wamid=mensagem.wamid,
        status=mensagem.status,
        erro=mensagem.erro_detalhe,
    )
