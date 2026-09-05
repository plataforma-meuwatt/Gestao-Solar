# -*- coding: utf-8 -*-
"""Talk Solar — a API.

Contrato completo em `docs/API.md`. Este arquivo IMPLEMENTA aquele documento; quando os dois
divergirem, é bug — corrija os dois no mesmo commit.

Duas regras atravessam tudo aqui:

1. **404 para o que é alheio, nunca 403.** Quem não pode ver um canal privado não deve nem
   descobrir que ele existe.
2. **A Talk Solar não sabe o que é uma usina.** Todo alvo é `tipo` + `id` opacos; o rótulo e a
   URL vêm do sistema dono e ficam CONGELADOS na citação.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import (Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import arquivos, config, integracao, sessao as sess
from .config import get_db
from .hub import hub
from .models import (Anexo, App, Base, Canal, Citacao, Entrega, Membro, Mensagem, Sessao,
                     Usuario)
from .webhooks import iniciar_worker

log = logging.getLogger("talksolar")

app = FastAPI(
    title="Talk Solar",
    description="O mensageiro da equipe de O&M solar — by Gestão Solar. "
                "Identidade e vocabulário emprestados dos sistemas integrados.",
    version="0.1.0",
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])


@app.on_event("startup")
def ao_subir() -> None:
    faltas = config.checar_producao()
    for f in faltas:
        log.warning("configuracao_pendente: %s", f)
    iniciar_worker()


# =============================================================== saúde
@app.get("/saude", tags=["serviço"])
def saude(db: Session = Depends(get_db)):
    """Diz a verdade sobre este servidor — inclusive o que está mal configurado.

    Um `/saude` que só responde "ok" serve para o balanceador e para mais ninguém. Este
    responde o que faltou configurar, que é a pergunta de quem acabou de implantar.
    """
    try:
        db.execute(func.now())
        banco = "ok"
    except Exception as e:                   # noqa: BLE001
        banco = f"erro: {type(e).__name__}"
    return {"servico": "talk-solar", "versao": app.version, "banco": banco,
            "storage": config.STORAGE, "pendencias_de_config": config.checar_producao()}


# =============================================================== sessão
class SessaoIn(BaseModel):
    app: str
    token: str
    dispositivo: Optional[str] = None


class RefreshIn(BaseModel):
    refresh: str


def _app_por_slug(db: Session, slug: str) -> App:
    a = db.query(App).filter(App.slug == (slug or "").strip().lower()).first()
    if a is None or not a.ativo:
        # a lista dos integrados vai no erro de propósito: quem está integrando precisa saber
        # se o slug que digitou existe, e isso não é segredo
        integrados = [x.slug for x in db.query(App).filter(App.ativo.is_(True)).all()]
        raise HTTPException(404, f"Sistema '{slug}' não integrado. Integrados: {integrados}")
    return a


@app.post("/v1/sessao", tags=["sessão"])
def abrir_sessao(payload: SessaoIn, db: Session = Depends(get_db)):
    """Troca o token do sistema hospedeiro por uma sessão da Talk Solar (docs/API.md §1.1)."""
    a = _app_por_slug(db, payload.app)
    dados = integracao.resolver_identidade(a, payload.token)
    u = integracao.espelhar_usuario(db, a, dados)
    token, refresh = sess.abrir_sessao(db, u, payload.dispositivo)
    db.commit()
    return {"token": token, "refresh": refresh,
            "usuario": {"id": u.id, "nome": u.nome, "email": u.email,
                        "app": a.slug, "externo_id": u.externo_id}}


@app.post("/v1/sessao/refresh", tags=["sessão"])
def renovar_sessao(payload: RefreshIn, db: Session = Depends(get_db)):
    token, u = sess.renovar(db, payload.refresh)
    db.commit()
    return {"token": token, "usuario": {"id": u.id, "nome": u.nome}}


@app.post("/v1/sessao/logout", status_code=204, tags=["sessão"])
def encerrar_sessao(payload: RefreshIn, db: Session = Depends(get_db)):
    sess.revogar(db, payload.refresh)
    db.commit()


# =============================================================== ajudantes
def _pode_ver(db: Session, c: Canal, u: Usuario) -> bool:
    """Canal PÚBLICO é legível por toda a empresa DAQUELE sistema, mesmo por quem não entrou.

    É o que separa um mensageiro de trabalho de um monte de grupos de WhatsApp: o histórico é
    patrimônio do time, não do grupinho. Privado e DM, o oposto.
    """
    if c.app_id != u.app_id:
        return False                          # sistemas diferentes não se enxergam
    if c.tipo == "publico":
        return True
    return db.query(Membro.id).filter(Membro.canal_id == c.id,
                                      Membro.usuario_id == u.id).first() is not None


def _canal(db: Session, cid: int, u: Usuario) -> Canal:
    c = db.get(Canal, cid)
    if c is None or not _pode_ver(db, c, u):
        raise HTTPException(404, "Conversa não encontrada")
    return c


def _membros_ids(db: Session, cid: int) -> List[int]:
    return [m[0] for m in db.query(Membro.usuario_id).filter(Membro.canal_id == cid).all()]


def _nomes(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {u.id: u.nome for u in db.query(Usuario).filter(Usuario.id.in_(set(ids))).all()}


def _anexos_de(db: Session, ids: list[int], base: str) -> dict[int, list]:
    if not ids:
        return {}
    out: dict[int, list] = {}
    for a in db.query(Anexo).filter(Anexo.mensagem_id.in_(ids)).all():
        out.setdefault(a.mensagem_id, []).append({
            "id": a.id, "nome": a.nome, "tipo": a.tipo, "bytes": a.bytes,
            "imagem": (a.tipo or "").startswith("image/"),
            "largura": a.largura, "altura": a.altura,
            "url": arquivos.url(a.caminho, base),
            "thumb_url": arquivos.url(a.thumb_caminho or a.caminho, base),
        })
    return out


def _citacoes_de(db: Session, ids: list[int]) -> dict[int, list]:
    if not ids:
        return {}
    out: dict[int, list] = {}
    for c in db.query(Citacao).filter(Citacao.mensagem_id.in_(ids)).all():
        out.setdefault(c.mensagem_id, []).append(
            {"tipo": c.alvo_tipo, "id": c.alvo_id, "label": c.label, "url": c.url})
    return out


def _msg_out(m: Mensagem, nomes: dict, anexos: dict, refs: dict, respostas: dict) -> dict:
    return {
        "id": m.id, "canal_id": m.canal_id,
        "autor": {"id": m.usuario_id, "nome": nomes.get(m.usuario_id or 0)},
        "conteudo": "" if m.apagada_em else m.conteudo,
        "responde_a": m.responde_a, "respostas": respostas.get(m.id, 0),
        "do_sistema": m.do_sistema,
        "editada": m.editada_em is not None, "apagada": m.apagada_em is not None,
        "criada_em": m.criada_em.isoformat() + "Z",
        # apagar é MARCAR, não sumir — mas o conteúdo, o anexo e a citação somem do retorno
        "anexos": [] if m.apagada_em else anexos.get(m.id, []),
        "refs": [] if m.apagada_em else refs.get(m.id, []),
    }


def _gravar_citacoes(db: Session, app_row: App, u: Usuario, m: Mensagem, refs: list) -> None:
    """Grava as citações CONFERINDO os alvos com o sistema dono.

    Id inexistente é recusado em silêncio: um marcador que leva a lugar nenhum é pior do que
    marcador nenhum. Quando o sistema não expõe `refs_label_url`, o rótulo do cliente é aceito —
    é uma concessão consciente, e está dita em docs/API.md §4.3.
    """
    if not refs:
        return
    pedidos = []
    for r in refs[:config.MAX_CITACOES]:
        tipo, rid = str((r or {}).get("tipo") or ""), (r or {}).get("id")
        if tipo and rid not in (None, ""):
            pedidos.append({"tipo": tipo, "id": str(rid), "label": (r or {}).get("label")})
    if not pedidos:
        return
    conhecidos = integracao.rotular_alvos(
        app_row, u.externo_id, [{"tipo": p["tipo"], "id": p["id"]} for p in pedidos])
    vistos = set()
    for p in pedidos:
        chave = (p["tipo"], p["id"])
        if chave in vistos:
            continue
        info = conhecidos.get(chave)
        if info is None and conhecidos:
            continue                          # o sistema respondeu e não conhece este alvo
        vistos.add(chave)
        db.add(Citacao(mensagem_id=m.id, app_id=app_row.id, alvo_tipo=p["tipo"],
                       alvo_id=p["id"],
                       label=(info or {}).get("label") or p.get("label"),
                       url=(info or {}).get("url")))


def _avisar(db: Session, app_row: App, canal: Canal, m: Mensagem, u: Usuario,
            n_anexos: int, mencoes: list) -> None:
    """Enfileira os webhooks do sistema dono (docs/API.md §5)."""
    base = {
        "canal": {"id": canal.id, "nome": canal.nome,
                  "alvo": ({"app": app_row.slug, "tipo": canal.alvo_tipo, "id": canal.alvo_id}
                           if canal.alvo_tipo else None)},
        "mensagem": {"id": m.id, "conteudo": m.conteudo,
                     "autor": {"externo_id": u.externo_id, "nome": u.nome},
                     "anexos": n_anexos,
                     "refs": [{"tipo": c.alvo_tipo, "id": c.alvo_id}
                              for c in db.query(Citacao).filter(Citacao.mensagem_id == m.id)]},
    }
    integracao.enfileirar(db, app_row, "mensagem.criada",
                          {"evento": "mensagem.criada",
                           "em": datetime.utcnow().isoformat() + "Z", **base})
    if mencoes:
        alvos = {x.externo_id for x in db.query(Usuario).filter(Usuario.id.in_(mencoes))}
        integracao.enfileirar(db, app_row, "mencao.criada",
                              {"evento": "mencao.criada",
                               "em": datetime.utcnow().isoformat() + "Z",
                               "mencionados": sorted(alvos), **base})


# =============================================================== canais
class CanalIn(BaseModel):
    nome: str
    tipo: str = "publico"
    topico: Optional[str] = None
    membros: List[int] = []


class DMIn(BaseModel):
    usuarios: List[int]


class AlvoIn(BaseModel):
    tipo: str
    id: str


@app.get("/v1/canais", tags=["conversa"])
def listar_canais(db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    """Os canais do usuário + os públicos do sistema dele, com não lidas e prévia.

    Tudo em consultas de LOTE: uma ida ao banco por canal deixaria a lista lenta com 30 canais,
    que é pouco.
    """
    meus = {m.canal_id: m for m in db.query(Membro).filter(Membro.usuario_id == u.id).all()}
    canais = (db.query(Canal)
              .filter(Canal.app_id == u.app_id, Canal.arquivado_em.is_(None),
                      or_(Canal.tipo == "publico", Canal.id.in_(meus.keys() or {-1})))
              .order_by(Canal.id.desc()).all())
    ids = [c.id for c in canais]
    ultimas = dict(db.query(Mensagem.canal_id, func.max(Mensagem.id))
                   .filter(Mensagem.canal_id.in_(ids or [-1]))
                   .group_by(Mensagem.canal_id).all()) if ids else {}
    previas = {m.canal_id: m for m in db.query(Mensagem).filter(
        Mensagem.id.in_(list(ultimas.values()) or [-1])).all()}
    # não lidas = quantas mensagens têm id maior que a última que a pessoa leu
    naolidas: dict[int, int] = {}
    if meus:
        for cid, n in (db.query(Mensagem.canal_id, func.count(Mensagem.id))
                       .filter(Mensagem.canal_id.in_(list(meus.keys())))
                       .group_by(Mensagem.canal_id, Mensagem.id).all()):
            naolidas[cid] = naolidas.get(cid, 0)
        for cid, m in meus.items():
            naolidas[cid] = (db.query(func.count(Mensagem.id))
                             .filter(Mensagem.canal_id == cid,
                                     Mensagem.id > (m.ultima_lida_id or 0),
                                     Mensagem.usuario_id != u.id).scalar() or 0)
    pessoas_dm = {}
    dms = [c.id for c in canais if c.tipo == "dm"]
    if dms:
        for mb in db.query(Membro).filter(Membro.canal_id.in_(dms)).all():
            pessoas_dm.setdefault(mb.canal_id, []).append(mb.usuario_id)
    nomes = _nomes(db, [i for v in pessoas_dm.values() for i in v])
    saida = []
    for c in canais:
        prev = previas.get(ultimas.get(c.id, -1))
        saida.append({
            "id": c.id, "tipo": c.tipo, "nome": c.nome, "topico": c.topico,
            "membro": c.id in meus, "nao_lidas": naolidas.get(c.id, 0),
            "ultima_em": prev.criada_em.isoformat() + "Z" if prev else None,
            "ultima_previa": (prev.conteudo[:80] if prev and prev.conteudo
                              else ("(arquivo)" if prev else None)),
            "alvo": ({"tipo": c.alvo_tipo, "id": c.alvo_id, "label": c.alvo_label,
                      "url": c.alvo_url} if c.alvo_tipo else None),
            "pessoas": [{"id": i, "nome": nomes.get(i)} for i in pessoas_dm.get(c.id, [])],
        })
    return saida


@app.post("/v1/canais", status_code=201, tags=["conversa"])
def criar_canal(payload: CanalIn, db: Session = Depends(get_db),
                u: Usuario = Depends(sess.usuario_atual)):
    if payload.tipo not in ("publico", "privado"):
        raise HTTPException(400, "tipo deve ser 'publico' ou 'privado'")
    c = Canal(app_id=u.app_id, tipo=payload.tipo, nome=payload.nome.strip()[:120],
              topico=(payload.topico or "").strip()[:300] or None, criado_por=u.id)
    db.add(c); db.flush()
    db.add(Membro(canal_id=c.id, usuario_id=u.id, papel="dono"))
    for uid in {int(x) for x in payload.membros if int(x) != u.id}:
        alvo = db.get(Usuario, uid)
        if alvo is not None and alvo.app_id == u.app_id:
            db.add(Membro(canal_id=c.id, usuario_id=uid))
    db.commit()
    return {"id": c.id, "tipo": c.tipo, "nome": c.nome, "membro": True}


@app.post("/v1/canais/dm", tags=["conversa"])
def abrir_dm(payload: DMIn, db: Session = Depends(get_db),
             u: Usuario = Depends(sess.usuario_atual)):
    """Abre (ou RETOMA) a conversa direta. Idempotente: a mesma dupla cai sempre no mesmo lugar
    — senão o histórico se parte em vários canais iguais."""
    alvos = {int(x) for x in payload.usuarios if int(x) != u.id}
    if not alvos:
        raise HTTPException(400, "Escolha com quem conversar.")
    todos = alvos | {u.id}
    for c in (db.query(Canal).filter(Canal.tipo == "dm", Canal.app_id == u.app_id)
              .join(Membro, Membro.canal_id == Canal.id)
              .filter(Membro.usuario_id == u.id).all()):
        if set(_membros_ids(db, c.id)) == todos:
            return {"id": c.id, "tipo": "dm", "membro": True}
    c = Canal(app_id=u.app_id, tipo="dm", criado_por=u.id)
    db.add(c); db.flush()
    for uid in todos:
        db.add(Membro(canal_id=c.id, usuario_id=uid))
    db.commit()
    return {"id": c.id, "tipo": "dm", "membro": True}


@app.post("/v1/canais/do-alvo", tags=["conversa"])
def canal_do_alvo(payload: AlvoIn, db: Session = Depends(get_db),
                  u: Usuario = Depends(sess.usuario_atual)):
    """O canal DAQUELA usina/OS — abre o que existe, cria se não houver. IDEMPOTENTE.

    É o que faz o botão "conversar sobre isto" ter um destino único. Sem ele, cada pessoa cria
    o seu grupo da mesma usina e a conversa se parte em cinco lugares.
    """
    a = sess.app_do_usuario(db, u)
    info = integracao.rotular_alvos(a, u.externo_id, [{"tipo": payload.tipo, "id": payload.id}])
    dados = info.get((payload.tipo, str(payload.id)))
    if a.refs_label_url and dados is None:
        raise HTTPException(404, "Este item não existe (ou não é seu) no sistema de origem.")
    c = (db.query(Canal).filter(Canal.app_id == a.id, Canal.alvo_tipo == payload.tipo,
                                Canal.alvo_id == str(payload.id),
                                Canal.arquivado_em.is_(None)).first())
    novo = c is None
    if novo:
        c = Canal(app_id=a.id, tipo="publico", alvo_tipo=payload.tipo, alvo_id=str(payload.id),
                  alvo_label=(dados or {}).get("label"), alvo_url=(dados or {}).get("url"),
                  nome=((dados or {}).get("label") or f"{payload.tipo} {payload.id}")[:120],
                  criado_por=u.id)
        db.add(c); db.flush()
        db.add(Membro(canal_id=c.id, usuario_id=u.id, papel="dono"))
        integracao.enfileirar(db, a, "canal.criado", {
            "evento": "canal.criado", "em": datetime.utcnow().isoformat() + "Z",
            "canal": {"id": c.id, "nome": c.nome,
                      "alvo": {"app": a.slug, "tipo": c.alvo_tipo, "id": c.alvo_id}}})
    elif not db.query(Membro.id).filter(Membro.canal_id == c.id,
                                        Membro.usuario_id == u.id).first():
        db.add(Membro(canal_id=c.id, usuario_id=u.id))
    db.commit()
    return {"id": c.id, "tipo": c.tipo, "nome": c.nome, "membro": True, "novo": novo,
            "alvo": {"tipo": c.alvo_tipo, "id": c.alvo_id, "label": c.alvo_label,
                     "url": c.alvo_url}}


@app.post("/v1/canais/{cid}/entrar", status_code=204, tags=["conversa"])
def entrar(cid: int, db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    c = _canal(db, cid, u)
    if c.tipo == "dm":
        raise HTTPException(400, "Conversa direta não aceita novos participantes.")
    if not db.query(Membro.id).filter(Membro.canal_id == cid, Membro.usuario_id == u.id).first():
        db.add(Membro(canal_id=cid, usuario_id=u.id))
        db.commit()


@app.post("/v1/canais/{cid}/sair", status_code=204, tags=["conversa"])
def sair(cid: int, db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    db.query(Membro).filter(Membro.canal_id == cid,
                            Membro.usuario_id == u.id).delete(synchronize_session=False)
    db.commit()


@app.post("/v1/canais/{cid}/lido", status_code=204, tags=["conversa"])
def marcar_lido(cid: int, payload: dict, db: Session = Depends(get_db),
                u: Usuario = Depends(sess.usuario_atual)):
    m = db.query(Membro).filter(Membro.canal_id == cid, Membro.usuario_id == u.id).first()
    if m is not None:
        m.ultima_lida_id = max(int(payload.get("ultima_id") or 0), m.ultima_lida_id or 0)
        db.commit()


# =============================================================== mensagens
class MensagemIn(BaseModel):
    conteudo: str = ""
    responde_a: Optional[int] = None
    refs: List[dict] = []
    mencoes: List[int] = []


@app.get("/v1/canais/{cid}/mensagens", tags=["conversa"])
def listar_mensagens(cid: int, request: Request, antes: Optional[int] = None,
                     limite: int = Query(50, le=200), thread_de: Optional[int] = None,
                     db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    _canal(db, cid, u)
    q = db.query(Mensagem).filter(Mensagem.canal_id == cid)
    q = (q.filter(Mensagem.responde_a == thread_de) if thread_de
         else q.filter(Mensagem.responde_a.is_(None)))
    if antes:
        q = q.filter(Mensagem.id < antes)
    msgs = q.order_by(Mensagem.id.desc()).limit(limite).all()
    msgs.reverse()
    if not msgs:
        return []
    ids = [m.id for m in msgs]
    base = str(request.base_url)
    respostas = dict(db.query(Mensagem.responde_a, func.count(Mensagem.id))
                     .filter(Mensagem.responde_a.in_(ids))
                     .group_by(Mensagem.responde_a).all())
    return [_msg_out(m, _nomes(db, [x.usuario_id for x in msgs if x.usuario_id]),
                     _anexos_de(db, ids, base), _citacoes_de(db, ids), respostas) for m in msgs]


@app.post("/v1/canais/{cid}/mensagens", status_code=201, tags=["conversa"])
async def enviar(cid: int, payload: MensagemIn, request: Request,
                 db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    c = _canal(db, cid, u)
    a = sess.app_do_usuario(db, u)
    texto = (payload.conteudo or "").strip()
    if not texto:
        raise HTTPException(400, "Mensagem vazia.")
    # escrever num canal público em que não entrou = entrar (é o que a pessoa quis dizer)
    if not db.query(Membro.id).filter(Membro.canal_id == cid, Membro.usuario_id == u.id).first():
        db.add(Membro(canal_id=cid, usuario_id=u.id))
    m = Mensagem(canal_id=cid, usuario_id=u.id, conteudo=texto, responde_a=payload.responde_a)
    db.add(m); db.flush()
    _gravar_citacoes(db, a, u, m, payload.refs)
    _avisar(db, a, c, m, u, 0, payload.mencoes)
    db.commit(); db.refresh(m)
    saida = _msg_out(m, {u.id: u.nome}, _anexos_de(db, [m.id], str(request.base_url)),
                     _citacoes_de(db, [m.id]), {})
    await hub.publicar(_membros_ids(db, cid) or [u.id],
                       {"tipo": "mensagem", "canal": cid, "msg": saida})
    return saida


@app.post("/v1/canais/{cid}/mensagens/anexos", status_code=201, tags=["conversa"])
async def enviar_com_anexos(cid: int, request: Request,
                            arquivos_up: List[UploadFile] = File(..., alias="arquivos"),
                            conteudo: str = Form(""), responde_a: Optional[int] = Form(None),
                            refs: str = Form(""), db: Session = Depends(get_db),
                            u: Usuario = Depends(sess.usuario_atual)):
    """Mensagem COM arquivos — mensagem e anexos na MESMA requisição.

    Não existe "sobe o arquivo e depois liga": no caminho de dois passos, uma falha no meio
    deixa arquivo órfão no storage ou mensagem vazia na conversa, e as duas coisas só aparecem
    para alguém já incomodado. O `conteudo` pode ser VAZIO — mandar só a foto é o gesto mais
    comum de quem está em campo.
    """
    c = _canal(db, cid, u)
    a = sess.app_do_usuario(db, u)
    ups = [x for x in (arquivos_up or []) if x is not None]
    if not ups:
        raise HTTPException(400, "Nenhum arquivo.")
    if len(ups) > config.MAX_ARQUIVOS:
        raise HTTPException(400, f"No máximo {config.MAX_ARQUIVOS} arquivos por mensagem.")

    # LÊ E VALIDA TUDO ANTES de gravar o primeiro byte: recusar o 8º depois de subir 7 deixaria
    # no storage sete arquivos que ninguém mais liga a coisa nenhuma
    lidos = []
    for up in ups:
        dados = await up.read()
        tipo = up.content_type or "application/octet-stream"
        erro = arquivos.validar(tipo, len(dados))
        if erro:
            raise HTTPException(400, f"{up.filename}: {erro}")
        lidos.append((up.filename or "arquivo", tipo, dados))

    if not db.query(Membro.id).filter(Membro.canal_id == cid, Membro.usuario_id == u.id).first():
        db.add(Membro(canal_id=cid, usuario_id=u.id))
    m = Mensagem(canal_id=cid, usuario_id=u.id, conteudo=(conteudo or "").strip(),
                 responde_a=responde_a)
    db.add(m); db.flush()
    try:
        _gravar_citacoes(db, a, u, m, json.loads(refs) if refs else [])
    except (ValueError, TypeError):
        pass                                  # citação malformada não derruba a mensagem
    for nome, tipo, dados in lidos:
        guardado = arquivos.guardar(cid, dados, nome, tipo)
        db.add(Anexo(mensagem_id=m.id, nome=nome[:255], tipo=tipo, **guardado))
    _avisar(db, a, c, m, u, len(lidos), [])
    db.commit(); db.refresh(m)
    saida = _msg_out(m, {u.id: u.nome}, _anexos_de(db, [m.id], str(request.base_url)),
                     _citacoes_de(db, [m.id]), {})
    await hub.publicar(_membros_ids(db, cid) or [u.id],
                       {"tipo": "mensagem", "canal": cid, "msg": saida})
    return saida


@app.patch("/v1/mensagens/{mid}", tags=["conversa"])
def editar(mid: int, payload: dict, request: Request, db: Session = Depends(get_db),
           u: Usuario = Depends(sess.usuario_atual)):
    m = db.get(Mensagem, mid)
    if m is None or m.apagada_em:
        raise HTTPException(404, "Mensagem não encontrada")
    if m.usuario_id != u.id:
        raise HTTPException(403, "Só quem escreveu edita.")
    m.conteudo = (payload.get("conteudo") or "").strip()
    m.editada_em = datetime.utcnow()
    db.commit()
    return _msg_out(m, {u.id: u.nome}, _anexos_de(db, [m.id], str(request.base_url)),
                    _citacoes_de(db, [m.id]), {})


@app.delete("/v1/mensagens/{mid}", status_code=204, tags=["conversa"])
def apagar(mid: int, db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    """Apagar é MARCAR. Numa conversa de trabalho o buraco precisa ser visível — senão a
    leitura de amanhã entende errado o que sobrou."""
    m = db.get(Mensagem, mid)
    if m is None:
        raise HTTPException(404, "Mensagem não encontrada")
    if m.usuario_id != u.id:
        raise HTTPException(403, "Só quem escreveu apaga.")
    m.apagada_em = datetime.utcnow()
    db.commit()


# =============================================================== pessoas e alvos
@app.get("/v1/pessoas", tags=["conversa"])
def pessoas(db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    """Quem existe para conversar — só do MESMO sistema. Sistemas não se enxergam."""
    return [{"id": x.id, "nome": x.nome, "email": x.email}
            for x in db.query(Usuario).filter(Usuario.app_id == u.app_id,
                                              Usuario.ativo.is_(True),
                                              Usuario.id != u.id).order_by(Usuario.nome).all()]


@app.get("/v1/refs/buscar", tags=["citação"])
def buscar_refs(q: str = Query(..., min_length=2), db: Session = Depends(get_db),
                u: Usuario = Depends(sess.usuario_atual)):
    """Repassa a busca ao sistema dono. O recorte de visibilidade é DELE (docs/API.md §4.2)."""
    return integracao.buscar_alvos(sess.app_do_usuario(db, u), u.externo_id, q)


@app.get("/v1/refs/{tipo}/{alvo_id}/mensagens", tags=["citação"])
def conversa_do_alvo(tipo: str, alvo_id: str, request: Request,
                     limite: int = Query(30, le=100), db: Session = Depends(get_db),
                     u: Usuario = Depends(sess.usuario_atual)):
    """"O que já se falou sobre isto" — a pergunta inversa da citação, e metade do valor dela.

    Só devolve mensagem de canal que a pessoa pode ver: citar não fura a visibilidade.
    """
    mids = [c.mensagem_id for c in db.query(Citacao)
            .filter(Citacao.app_id == u.app_id, Citacao.alvo_tipo == tipo,
                    Citacao.alvo_id == str(alvo_id))
            .order_by(Citacao.id.desc()).limit(limite * 3).all()]
    if not mids:
        return []
    msgs = (db.query(Mensagem).filter(Mensagem.id.in_(mids), Mensagem.apagada_em.is_(None))
            .order_by(Mensagem.id.desc()).all())
    canais = {c.id: c for c in db.query(Canal).filter(
        Canal.id.in_({m.canal_id for m in msgs})).all()}
    visiveis = [m for m in msgs
                if m.canal_id in canais and _pode_ver(db, canais[m.canal_id], u)][:limite]
    if not visiveis:
        return []
    ids = [m.id for m in visiveis]
    base = str(request.base_url)
    return [_msg_out(m, _nomes(db, [x.usuario_id for x in visiveis if x.usuario_id]),
                     _anexos_de(db, ids, base), _citacoes_de(db, ids), {}) for m in visiveis]


# =============================================================== webhook de volta
@app.post("/v1/webhooks/{slug}", tags=["integração"])
async def webhook_de_volta(slug: str, request: Request, db: Session = Depends(get_db)):
    """O SISTEMA avisa a Talk Solar (docs/API.md §6).

    Vira uma mensagem DE SISTEMA no canal daquele alvo — é como a OS conta, na própria
    conversa, que foi fechada, sem ninguém digitar.

    A assinatura é conferida ANTES de ler o corpo: sem isso, quem descobrisse a URL escreveria
    na conversa da empresa.
    """
    a = _app_por_slug(db, slug)
    corpo = await request.body()
    if not integracao.confere_assinatura(corpo, a.secret,
                                         request.headers.get("X-Talk-Assinatura", "")):
        raise HTTPException(401, "Assinatura inválida.")
    try:
        dados = json.loads(corpo or b"{}")
    except ValueError:
        raise HTTPException(400, "Corpo não é JSON.")

    alvo = dados.get("alvo") or {}
    texto = (dados.get("texto") or "").strip()
    if not texto or not alvo.get("tipo") or alvo.get("id") in (None, ""):
        raise HTTPException(400, "Informe `alvo.tipo`, `alvo.id` e `texto`.")
    c = (db.query(Canal).filter(Canal.app_id == a.id, Canal.alvo_tipo == str(alvo["tipo"]),
                                Canal.alvo_id == str(alvo["id"]),
                                Canal.arquivado_em.is_(None)).first())
    if c is None:
        # sem canal, não há onde postar — e criar um canal por evento encheria a lista de
        # conversas vazias. Responde 204 para o sistema não ficar reenviando.
        return {"ok": True, "postado": False, "motivo": "ainda não há conversa sobre este item"}
    m = Mensagem(canal_id=c.id, usuario_id=None, conteudo=texto[:2000], do_sistema=True)
    db.add(m); db.commit(); db.refresh(m)
    saida = _msg_out(m, {}, {}, {}, {})
    if not dados.get("silencioso"):
        await hub.publicar(_membros_ids(db, c.id), {"tipo": "mensagem", "canal": c.id,
                                                    "msg": saida})
    return {"ok": True, "postado": True, "mensagem_id": m.id}


# =============================================================== tempo real
@app.websocket("/v1/ws")
async def tempo_real(ws: WebSocket, token: str = Query("")):
    """A conexão viva. Só de SAÍDA: nada do que o cliente manda por aqui é obedecido.

    Tudo o que muda estado passa pelos endpoints, com as mesmas conferências. Um WebSocket que
    aceita comandos é uma segunda API sem as mesmas regras — e é sempre a esquecida.
    """
    db = config.sessao_direta()
    try:
        u = sess.usuario_do_ws(db, token)
        if u is None:
            await ws.close(code=4401)
            return
        uid = u.id
    finally:
        db.close()
    await ws.accept()
    await hub.entrar(uid, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:                          # noqa: BLE001
        pass
    finally:
        await hub.sair(uid, ws)


# =============================================================== arquivos locais
@app.get("/arquivos/{caminho:path}", tags=["serviço"])
def servir_arquivo(caminho: str):
    """Só existe no modo `local` (desenvolvimento). Com Supabase, a URL é assinada e vai
    direto para o storage — o servidor não fica no meio do caminho da foto."""
    if config.STORAGE != "local":
        raise HTTPException(404, "Não encontrado")
    from pathlib import Path
    p = (Path(config.STORAGE_DIR) / caminho).resolve()
    raiz = Path(config.STORAGE_DIR).resolve()
    if raiz not in p.parents or not p.exists():
        raise HTTPException(404, "Não encontrado")   # nada de subir a árvore com ../
    return FileResponse(p)


# =============================================================== administração
@app.get("/v1/admin/webhooks/entregas", tags=["integração"])
def entregas(estado: Optional[str] = None, limite: int = Query(50, le=200),
             db: Session = Depends(get_db), u: Usuario = Depends(sess.usuario_atual)):
    """As tentativas de entrega — a resposta para "por que o meuWatt não recebeu?".

    Cada tentativa com corpo, status e hora. Uma flag `entregue: bool` responderia "não" e mais
    nada.
    """
    q = db.query(Entrega).filter(Entrega.app_id == u.app_id)
    if estado:
        q = q.filter(Entrega.estado == estado)
    return [{"id": e.id, "evento": e.evento, "ref": e.ref, "estado": e.estado,
             "tentativas": e.tentativas, "http_status": e.http_status,
             "resposta": (e.resposta or "")[:200],
             "criada_em": e.criada_em.isoformat() + "Z",
             "proxima_em": e.proxima_em.isoformat() + "Z" if e.proxima_em else None}
            for e in q.order_by(Entrega.id.desc()).limit(limite).all()]
