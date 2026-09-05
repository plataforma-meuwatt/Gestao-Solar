# -*- coding: utf-8 -*-
"""A ponte com os sistemas: identidade, busca de alvos e webhooks.

**É o coração do produto** — e a razão de a Talk Solar não ter cadastro de usuário nem saber o
que é uma usina. Tudo o que é domínio de alguém é perguntado a quem sabe.

Uma regra atravessa o arquivo inteiro: **quando o sistema hospedeiro falha, a Talk Solar diz de
quem é a culpa.** Um 502 com "o meuPlano não respondeu em 8 s" resolve-se em minutos; um 500
genérico vira meia hora de gente olhando o log errado.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import config
from .models import App, Entrega, Usuario


# ------------------------------------------------------------------ assinatura
def assinar(corpo: bytes, secret: str) -> str:
    """`sha256=<hex>` do corpo CRU. É o que prova que a chamada veio de quem diz ter vindo."""
    return "sha256=" + hmac.new(secret.encode(), corpo, hashlib.sha256).hexdigest()


def confere_assinatura(corpo: bytes, secret: str, recebida: str) -> bool:
    """`compare_digest` (e não `==`) porque comparação comum vaza o segredo pelo TEMPO."""
    return hmac.compare_digest(assinar(corpo, secret), (recebida or "").strip())


# ------------------------------------------------------------------ identidade
def resolver_identidade(app: App, token: str) -> dict:
    """De quem é este token? — a única pergunta que TODO sistema integrado precisa responder.

    Falha aqui não é 500: ou o token é inválido (401) ou o sistema não respondeu (502). A
    diferença importa porque a primeira é do usuário e a segunda é de quem opera.
    """
    try:
        r = httpx.post(app.identidade_url, json={"token": token},
                       headers={"X-Talk-Secret": app.secret},
                       timeout=config.TIMEOUT_IDENTIDADE)
    except httpx.RequestError as e:
        raise HTTPException(502, f"{app.nome} não respondeu ({type(e).__name__}). "
                                 f"A Talk Solar não consegue confirmar quem é você agora.")
    if r.status_code == 401:
        raise HTTPException(401, f"O {app.nome} não reconheceu este login.")
    if r.status_code >= 400:
        raise HTTPException(502, f"{app.nome} respondeu {r.status_code} ao confirmar a "
                                 f"identidade.")
    dados = r.json() if r.content else {}
    if not dados.get("externo_id"):
        raise HTTPException(502, f"{app.nome} respondeu sem `externo_id` — contrato quebrado "
                                 f"(ver docs/API.md §4.1).")
    if dados.get("ativo") is False:
        raise HTTPException(401, "Sua conta está inativa neste sistema.")
    return dados


def espelhar_usuario(db: Session, app: App, dados: dict) -> Usuario:
    """Cria ou ATUALIZA o espelho. Nome e e-mail são reescritos a cada entrada.

    Reescrever é o ponto: quem casou e mudou de nome no sistema hospedeiro não pode continuar
    aparecendo com o nome antigo aqui — o espelho não tem vida própria.
    """
    u = (db.query(Usuario)
         .filter(Usuario.app_id == app.id,
                 Usuario.externo_id == str(dados["externo_id"])).first())
    if u is None:
        u = Usuario(app_id=app.id, externo_id=str(dados["externo_id"]),
                    nome=dados.get("nome") or "sem nome")
        db.add(u)
    u.nome = dados.get("nome") or u.nome
    u.email = dados.get("email") or u.email
    u.avatar_url = dados.get("avatar_url") or u.avatar_url
    u.ativo = dados.get("ativo", True)
    u.visto_em = datetime.utcnow()
    db.flush()
    return u


# ------------------------------------------------------------------ alvos citáveis
def buscar_alvos(app: App, externo_id: str, termo: str, limite: int = 6) -> list[dict]:
    """O que ESTE usuário pode citar. O recorte de visibilidade é do SISTEMA, não daqui.

    Sem `refs_busca_url` a resposta é vazia — e a tela mostra "este sistema ainda não permite
    citar", que é a verdade, em vez de um erro.
    """
    if not app.refs_busca_url:
        return []
    try:
        r = httpx.post(app.refs_busca_url,
                       json={"externo_id": externo_id, "q": termo, "limite": limite},
                       headers={"X-Talk-Secret": app.secret}, timeout=config.TIMEOUT_BUSCA)
        if r.status_code >= 400:
            return []
        itens = (r.json() or {}).get("itens") or []
    except (httpx.RequestError, ValueError):
        return []                       # busca é conveniência: nunca derruba a conversa
    limpos = []
    for i in itens[:limite * 5]:
        if not i.get("tipo") or i.get("id") in (None, ""):
            continue
        limpos.append({"app": app.slug, "tipo": str(i["tipo"])[:30], "id": str(i["id"])[:60],
                       "label": (i.get("label") or "")[:200], "url": (i.get("url") or "")[:400]})
    return limpos


def rotular_alvos(app: App, externo_id: str, alvos: list[dict]) -> dict[tuple, dict]:
    """Como se chamam estes alvos, AGORA — vira o rótulo congelado da citação.

    Sem `refs_label_url` devolve vazio, e quem chama decide: na criação de canal isso é 400 (não
    se cria canal de um alvo que ninguém confirma existir); na citação, o rótulo do cliente é
    aceito — e o docstring diz que isso é uma concessão, não um projeto.
    """
    if not app.refs_label_url or not alvos:
        return {}
    try:
        r = httpx.post(app.refs_label_url,
                       json={"externo_id": externo_id, "alvos": alvos},
                       headers={"X-Talk-Secret": app.secret}, timeout=config.TIMEOUT_BUSCA)
        if r.status_code >= 400:
            return {}
        itens = (r.json() or {}).get("itens") or []
    except (httpx.RequestError, ValueError):
        return {}
    return {(str(i.get("tipo")), str(i.get("id"))): {
        "label": (i.get("label") or "")[:200], "url": (i.get("url") or "")[:400]}
        for i in itens if i.get("tipo") and i.get("id") is not None}


# ------------------------------------------------------------------ webhooks (saída)
def enfileirar(db: Session, app: App, evento: str, payload: dict) -> Optional[Entrega]:
    """Registra o aviso PARA DEPOIS. Não manda aqui.

    A entrega acontece no worker (`webhooks.py`) por um motivo prático: se o meuWatt estiver
    fora do ar, quem manda a mensagem não pode esperar 10 s por isso. A conversa é síncrona; o
    aviso é assíncrono.
    """
    if not app.webhook_url or not app.ativo:
        return None
    if app.webhook_eventos and evento not in app.webhook_eventos:
        return None
    e = Entrega(app_id=app.id, evento=evento, ref=uuid.uuid4().hex, payload=payload,
                estado="pendente", proxima_em=datetime.utcnow())
    db.add(e)
    return e


def entregar(db: Session, e: Entrega) -> bool:
    """Uma tentativa. `True` = entregue; `False` = fica para o próximo reenvio."""
    app = db.get(App, e.app_id)
    if app is None or not app.webhook_url:
        e.estado, e.terminada_em = "falhou", datetime.utcnow()
        e.resposta = "app sem webhook_url"
        return False
    corpo = json.dumps(e.payload, ensure_ascii=False).encode()
    e.tentativas += 1
    try:
        r = httpx.post(app.webhook_url, content=corpo, timeout=config.TIMEOUT_WEBHOOK,
                       headers={
                           "Content-Type": "application/json",
                           "X-Talk-Evento": e.evento,
                           "X-Talk-Entrega": e.ref,
                           "X-Talk-Assinatura": assinar(corpo, app.secret),
                       })
        e.http_status = r.status_code
        e.resposta = (r.text or "")[:500]
        ok = 200 <= r.status_code < 300
    except httpx.RequestError as ex:
        e.http_status, e.resposta, ok = None, f"{type(ex).__name__}: {ex}"[:500], False

    if ok:
        e.estado, e.terminada_em, e.proxima_em = "entregue", datetime.utcnow(), None
        return True
    # a espera cresce; depois da última, a entrega fica marcada como falha VISÍVEL
    idx = e.tentativas - 1
    if idx < len(config.REENVIOS_SEG):
        e.proxima_em = datetime.utcnow() + timedelta(seconds=config.REENVIOS_SEG[idx])
    else:
        e.estado, e.terminada_em, e.proxima_em = "falhou", datetime.utcnow(), None
    return False
