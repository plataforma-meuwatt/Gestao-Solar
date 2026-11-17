"""CONECTOR DO CLAUDE, UM SÓ — o Claude da pessoa (claude.ai, app, desktop, Claude Code) consulta os sistemas da família
pelo Gestão Solar, como o bot do WhatsApp. O dono, 17/11/2026: "E se fizer isso como se fosse mcp do gestao solar ai
fica um so para todos sistemas. Igual é o bot hoje".

1. **Login com a conta do Gestão Solar** (OAuth 2.1 + PKCE S256, o que o claude.ai exige). `GET /oauth/authorize` guarda
   o pedido em memória e mostra a página daqui mesmo (apelido e senha, de qualquer portão); `POST /oauth/authorize`
   confere a senha como o login, e o código vai SÓ ao endereço de retorno do Claude conferido na ida. `/oauth/token`
   troca código + verificador pelo token `gs_mcp_…` (90 dias; daqui só sai o hash, `gs_mcp_tokens`). Conta ou empresa
   desativada derruba o token na hora. Pedidos e códigos em memória: a API roda um worker só (Dockerfile); um deploy no
   meio só obriga a pessoa a clicar de novo.
2. **O que se lê é o que o bot responde** à pessoa: o produto liberado pelo gerente E com o token PRÓPRIO dela
   (`User.bot_ativo`; regra do dono de 23/10/2026). Cada produto tem o próprio conector (`/mcp` do mw-api e do
   meuPlano), com a própria lista e o próprio recorte; aqui só se repassa, com o token da pessoa. A pessoa lê o nome
   do SERVIÇO, nunca o do produto (`tests/test_vocabulario_do_cliente.py`): as ferramentas ganham o prefixo
   `monitoramento_…` / `manutencao_…`, e o texto que vem de lá passa por `_sem_marca`. Serviço que não abre vira uma
   ferramenta que diz por quê — nunca some calado.
3. **Só consulta**: os dois conectores de lá só leem. Ação (helper, meuGuarda, criar OS) segue no bot, com a senha de
   atuação e o Sim.
"""

import asyncio
import hashlib
import html
import re
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import _conta_com_empresa, _empresa_ativa, conferir_senha
from app.core.tokens_produto import NOME
from app.models.integracao import Produto
from app.models.mcp import TokenMcp
from app.models.user import User
from app.services import vinculos

router = APIRouter(tags=["Conector do Claude"])

#: Retorno do OAuth do conector no claude.ai — endereço EXATO. O Claude Code volta pelo loopback (porta alta).
CALLBACKS_CLAUDE = {"https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"}
_LOOPBACK = {"localhost", "127.0.0.1"}
PEDIDO_TTL = 600  # da página aberta até o clique
CODIGO_TTL = 300  # do clique até o Claude trocar o código
TOKEN_DIAS = 90
PREFIXO = "gs_mcp_"
_VIVOS_POR_CONTA = 20  # o 21º derruba o mais velho
_FALHAS_MAX, _FALHAS_JANELA = 5, 900  # 5 senhas erradas no mesmo apelido = 15 min parado
_VERSOES = ("2025-06-18", "2025-03-26", "2024-11-05")
_TETO_LOTE = 20

#: serviço (o prefixo das ferramentas) → (o produto de origem, o nome que a pessoa lê). A ordem é a da lista.
SERVICOS: dict[str, tuple[Produto, str]] = {"monitoramento": (Produto.MEUWATT, "Monitoramento"),
                                            "manutencao": (Produto.MEUPLANO, "Manutenção")}

INSTRUCOES = (
    "O Gestão Solar reúne os serviços das usinas solares de quem está conectado. Cada ferramenta começa pelo serviço: "
    "monitoramento_… (geração, PR, paradas, alarmes, strings, relés, trackers, gêmeo digital, relatórios) e "
    "manutencao_… (ordens de serviço, tarefas, cronograma, relatórios de manutenção). Nas instruções de cada serviço, "
    "abaixo, o nome da ferramenta vem sem o prefixo. Tudo é SÓ LEITURA e recortado pelo acesso da pessoa. Responda "
    "com datas em dd/mm/aaaa, números no formato brasileiro e horário de Brasília."
)
# o nome do produto que vem de lá (descrição, instrução, recusa) vira o do serviço, com o artigo certo
_MASCULINO = {"do": "da", "no": "na", "ao": "à", "pelo": "pela", "o": "a", "um": "uma"}
_MARCAS = [
    (re.compile(rf"\b(do|no|ao|pelo|o|um|Do|No|Ao|Pelo|O|Um)\s+{NOME[Produto.MEUPLANO]}\b"),
     lambda m: (_MASCULINO[m.group(1).lower()].capitalize() if m.group(1)[0].isupper()
                else _MASCULINO[m.group(1)]) + " manutenção"),
    (re.compile(rf"\b{NOME[Produto.MEUPLANO]}\b"), lambda m: "manutenção"),
    (re.compile(rf"\b{NOME[Produto.MEUWATT]}\b"), lambda m: "monitoramento"),
]

# ponytail: memória do processo (1 worker); com réplicas, vira tabela.
_pedidos: dict[str, dict] = {}  # pedido -> {desafio, redirect, state, exp}
_codigos: dict[str, dict] = {}  # sha256(código) -> {user_id, desafio, redirect, exp}
_falhas: dict[str, list[float]] = {}  # apelido -> horários das senhas erradas


class _Falhou(RuntimeError):
    """O produto não atendeu; a mensagem é a frase para a pessoa."""


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def destino_permitido(url: str) -> bool:
    try:
        u = urlparse(url or "")
        porta = u.port
    except ValueError:
        return False
    if u.username or u.password or u.fragment:
        return False
    if u.scheme == "http" and u.hostname in _LOOPBACK and porta and 1024 < porta <= 65535:
        return True
    return u.scheme == "https" and porta is None and f"https://{u.hostname}{u.path}" in CALLBACKS_CLAUDE


def _com_query(url: str, **q) -> str:
    q = {k: v for k, v in q.items() if v}
    return url + ("&" if "?" in url else "?") + urlencode(q) if q else url


def _desafio_ok(code_challenge: str) -> bool:
    """base64url(SHA-256) — 43 caracteres que decodificam em 32 bytes."""
    try:
        return len(urlsafe_b64decode(code_challenge + "=" * (-len(code_challenge) % 4))) == 32
    except ValueError:
        return False


def _limpar_vencidos() -> None:
    agora = time.time()
    for d in (_pedidos, _codigos):
        for k in [k for k, v in d.items() if v["exp"] < agora]:
            d.pop(k, None)
    for k in [k for k, v in _falhas.items() if not v or v[-1] < agora - _FALHAS_JANELA]:
        _falhas.pop(k, None)


def _base(request: Request) -> str:
    return "https://api.gestao.solar" if get_settings().producao else str(request.base_url).rstrip("/")


def _erro_oauth(erro: str, desc: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": erro, "error_description": desc})


def servicos(usuario: User) -> list[str]:
    """Os serviços que o Claude desta pessoa lê: os que o bot responde a ela (liberado + token próprio)."""
    ativos = usuario.bot_ativo
    return [s for s, (produto, _nome) in SERVICOS.items() if f"bot_{produto.value}" in ativos]


def _sem_marca(texto: str) -> str:
    for padrao, troca in _MARCAS:
        texto = padrao.sub(troca, texto)
    return texto


# ============================================================================ OAuth
@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def recurso_protegido(request: Request):
    b = _base(request)
    return {"resource": f"{b}/mcp", "authorization_servers": [b], "bearer_methods_supported": ["header"]}


@router.get("/.well-known/oauth-authorization-server")
def servidor_autorizacao(request: Request):
    b = _base(request)
    return {
        "issuer": b,
        "authorization_endpoint": f"{b}/oauth/authorize",
        "token_endpoint": f"{b}/oauth/token",
        "registration_endpoint": f"{b}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@router.post("/oauth/register")
async def registrar_cliente(request: Request):
    """Registro dinâmico (RFC 7591) sem estado: quem protege é o destino do código e o PKCE."""
    try:
        corpo = await request.json()
    except ValueError:
        corpo = {}
    uris = corpo.get("redirect_uris") if isinstance(corpo, dict) else None
    if not uris or not isinstance(uris, list) or not all(isinstance(u, str) and destino_permitido(u) for u in uris):
        return _erro_oauth("invalid_redirect_uri", "Destino de retorno não permitido.")
    return JSONResponse(
        status_code=201,
        content={
            "client_id": "gestao-solar-mcp",
            "client_name": str(corpo.get("client_name") or "Claude")[:80],
            "redirect_uris": uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


def _pagina(pedido: str | None, erro: str | None = None, status: int = 200) -> HTMLResponse:
    """A página do login: daqui mesmo, sem script, sem moldura (ninguém a embute para roubar o clique)."""
    aviso = f'<p class="erro">{html.escape(erro)}</p>' if erro else ""
    form = "" if pedido is None else (
        '<form method="post" action="/oauth/authorize">'
        f'<input type="hidden" name="pedido" value="{html.escape(pedido)}">'
        '<label>Apelido<input name="apelido" autocomplete="username" autocapitalize="none" required></label>'
        '<label>Senha<input name="senha" type="password" autocomplete="current-password" required></label>'
        '<button name="acao" value="autorizar">Autorizar</button>'
        '<button name="acao" value="cancelar" class="nao" formnovalidate>Cancelar</button></form>'
    )
    corpo = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        "<title>Conectar o Claude</title><style>"
        ":root{--fundo:#f4f6f8;--cartao:#fff;--texto:#1d2733;--fraco:#5b6775;--borda:#d5dbe1;--cor:#0b7a4b;--erro:#b42318}"
        "@media (prefers-color-scheme:dark){:root{--fundo:#0f1419;--cartao:#1a2129;--texto:#e6ebf0;--fraco:#9aa7b4;"
        "--borda:#2e3843;--cor:#2fb57a;--erro:#ff8a7a}}"
        "body{margin:0;background:var(--fundo);color:var(--texto);font:16px/1.5 system-ui,sans-serif}"
        "main{max-width:420px;margin:8vh auto;padding:24px 16px}"
        "section{background:var(--cartao);border:1px solid var(--borda);border-radius:12px;padding:24px}"
        "h1{font-size:20px;margin:0 0 8px}p{color:var(--fraco);margin:0 0 16px}"
        "label{display:block;margin:0 0 12px;font-weight:600}"
        "input{display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:10px;font:inherit;"
        "color:var(--texto);background:var(--fundo);border:1px solid var(--borda);border-radius:8px}"
        "button{font:inherit;padding:10px 16px;border-radius:8px;border:0;background:var(--cor);color:#fff;"
        "margin:4px 8px 0 0;cursor:pointer}button.nao{background:transparent;color:var(--fraco);border:1px solid var(--borda)}"
        ".erro{color:var(--erro);font-weight:600}</style></head><body><main><section>"
        "<h1>Conectar o Claude ao Gestão Solar</h1>"
        "<p>O Claude vai <b>consultar</b>, em seu nome, o que a sua conta enxerga no monitoramento e na manutenção. "
        "Só leitura: ele não muda nada nos sistemas.</p>"
        f"{aviso}{form}</section></main></body></html>"
    )
    return HTMLResponse(
        corpo,
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/oauth/authorize")
def autorizar(
    response_type: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    state: str = "",
):
    if not destino_permitido(redirect_uri):
        # destino ruim NÃO recebe redirect (seria entregar o erro — e o state — a terceiro)
        return _erro_oauth("invalid_request", "Destino de retorno não permitido.")
    if response_type != "code" or code_challenge_method != "S256" or not _desafio_ok(code_challenge):
        return RedirectResponse(
            _com_query(redirect_uri, error="invalid_request", error_description="Use response_type=code com PKCE S256.",
                       state=state),
            status_code=302,
        )
    _limpar_vencidos()
    if len(_pedidos) > 1000:
        return _erro_oauth("temporarily_unavailable", "Muitos pedidos abertos; tente em instantes.", 503)
    pedido = secrets.token_urlsafe(24)
    _pedidos[pedido] = {"desafio": code_challenge, "redirect": redirect_uri, "state": state[:500],
                        "exp": time.time() + PEDIDO_TTL}
    return _pagina(pedido)


@router.post("/oauth/authorize")
def aprovar(
    pedido: str = Form(""),
    apelido: str = Form(""),
    senha: str = Form(""),
    acao: str = Form(""),
    db: Session = Depends(get_db),
):
    """A pessoa decide com a senha do Gestão Solar. O código só vai ao destino conferido na ida."""
    _limpar_vencidos()
    p = _pedidos.get(pedido)
    if p is None:
        return _pagina(None, "Este pedido expirou. Volte ao Claude e clique em Conectar de novo.", 400)
    if acao != "autorizar":
        _pedidos.pop(pedido, None)
        return RedirectResponse(_com_query(p["redirect"], error="access_denied", state=p["state"]), status_code=303)
    nome = (apelido or "").strip().lower()
    agora = time.time()
    recentes = [t for t in _falhas.get(nome, []) if t > agora - _FALHAS_JANELA]
    if len(recentes) >= _FALHAS_MAX:
        return _pagina(pedido, "Muitas senhas erradas para este apelido. Espere 15 minutos.", 429)
    usuario = db.scalar(select(User).where(User.apelido == nome))
    # a mesma frase para conta inexistente, senha errada e conta desativada, como no login
    if usuario is None or not usuario.ativo or not conferir_senha(senha, usuario.senha_hash):
        _falhas[nome] = [*recentes, agora]
        return _pagina(pedido, "Apelido ou senha inválidos.", 401)
    _falhas.pop(nome, None)
    try:
        _empresa_ativa(db, usuario)
    except HTTPException as e:
        return _pagina(pedido, str(e.detail), 403)
    if not servicos(usuario):
        return _pagina(
            pedido,
            "Sua conta ainda não tem o monitoramento nem a manutenção liberados para consulta. O gerente da O&M libera "
            "em Usuários (oem-gs), com o seu token de cada serviço.",
            403,
        )
    _pedidos.pop(pedido, None)
    codigo = secrets.token_urlsafe(32)
    _codigos[_hash(codigo)] = {"user_id": usuario.id, "desafio": p["desafio"], "redirect": p["redirect"],
                               "exp": agora + CODIGO_TTL}
    return RedirectResponse(_com_query(p["redirect"], code=codigo, state=p["state"]), status_code=303)


@router.post("/oauth/token")
def trocar(
    grant_type: str = Form(""),
    code: str = Form(""),
    code_verifier: str = Form(""),
    redirect_uri: str = Form(""),
    db: Session = Depends(get_db),
):
    if grant_type != "authorization_code":
        return _erro_oauth("unsupported_grant_type", "Só authorization_code.")
    _limpar_vencidos()
    c = _codigos.pop(_hash(code), None)  # sai na 1ª tentativa, certa ou errada: o código vale uma vez
    feito = urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    if c is None or not secrets.compare_digest(feito, c["desafio"]) or (redirect_uri and redirect_uri != c["redirect"]):
        return _erro_oauth("invalid_grant", "Autorização inválida ou expirada.")
    agora = datetime.now(UTC)
    vivos = [t for t in db.scalars(select(TokenMcp).where(TokenMcp.user_id == c["user_id"],
                                                          TokenMcp.revogado_em.is_(None)).order_by(TokenMcp.id))
             if _aware(t.expira_em) > agora]
    for velho in vivos[: max(0, len(vivos) - _VIVOS_POR_CONTA + 1)]:
        velho.revogado_em = agora
    bruto = PREFIXO + secrets.token_urlsafe(32)
    db.add(TokenMcp(user_id=c["user_id"], token_hash=_hash(bruto), expira_em=agora + timedelta(days=TOKEN_DIAS)))
    db.commit()
    return JSONResponse(
        content={"access_token": bruto, "token_type": "Bearer", "expires_in": TOKEN_DIAS * 86400},
        headers={"Cache-Control": "no-store"},
    )


# ============================================================================ repasse aos produtos
def _cliente(db: Session, usuario: User, servico: str):
    produto = SERVICOS[servico][0]
    criar = vinculos.cliente_meuwatt if produto is Produto.MEUWATT else vinculos.cliente_meuplano
    return criar(db, usuario.id, so_proprio=True)


async def _repassa(cli, rotulo: str, metodo: str, params: dict) -> dict:
    """Uma mensagem ao conector do produto, com o token da pessoa; o `result` de lá ou `_Falhou`."""
    try:
        r = await cli.mcp({"jsonrpc": "2.0", "id": 1, "method": metodo, "params": params})
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            try:
                motivo = e.response.json().get("error_description") or ""
            except ValueError:
                motivo = ""
            raise _Falhou(f"{rotulo}: o token desta pessoa foi recusado{f' ({motivo})' if motivo else ''}. O gerente "
                          "da O&M cola o token de novo em Usuários (oem-gs).") from e
        raise _Falhou(f"{rotulo}: erro {e.response.status_code} agora. Tente de novo em instantes.") from e
    except (httpx.HTTPError, ValueError) as e:
        raise _Falhou(f"{rotulo}: não respondeu agora. Tente de novo em instantes.") from e
    if not isinstance(r, dict):
        raise _Falhou(f"{rotulo}: resposta fora do formato.")
    if r.get("error"):
        raise _Falhou(f"{rotulo}: {(r['error'] or {}).get('message') or 'erro'}")
    return r.get("result") or {}


def _motivo(e: Exception) -> str:
    return _sem_marca(str(e.detail) if isinstance(e, HTTPException) else str(e))


def _erro(texto: str) -> dict:
    return {"content": [{"type": "text", "text": texto}], "isError": True}


async def _ferramentas(db: Session, usuario: User) -> list[dict]:
    async def de(servico: str) -> list[dict]:
        rotulo = SERVICOS[servico][1]
        try:
            res = await _repassa(_cliente(db, usuario, servico), rotulo, "tools/list", {})
        except (_Falhou, HTTPException) as e:
            return [{"name": f"{servico}_indisponivel",
                     "description": f"[{rotulo}] Não abriu agora para esta conta: {_motivo(e)} Chame esta ferramenta "
                                    "para conferir de novo e diga isso à pessoa.",
                     "inputSchema": {"type": "object", "properties": {}}}]
        return [{**t, "name": f"{servico}_{t['name']}",
                 "description": f"[{rotulo}] {_sem_marca(t.get('description') or '')}".strip()}
                for t in res.get("tools") or [] if isinstance(t, dict) and t.get("name")]

    listas = await asyncio.gather(*(de(s) for s in servicos(usuario)))
    return [t for lista in listas for t in lista]


async def _chamar(db: Session, usuario: User, nome: str, args: Any) -> dict:
    servico, _, ferramenta = nome.partition("_")
    if servico not in SERVICOS or not ferramenta:
        return _erro(f"Ferramenta desconhecida: {nome}")
    rotulo = SERVICOS[servico][1]
    if servico not in servicos(usuario):
        return _erro(f"{rotulo}: esta conta não tem o serviço liberado para consulta no Gestão Solar (o gerente da "
                     "O&M libera em Usuários, com o token da pessoa).")
    try:
        cli = _cliente(db, usuario, servico)
        if ferramenta == "indisponivel":
            await _repassa(cli, rotulo, "tools/list", {})
            return _erro(f"{rotulo}: respondeu agora. Desconecte e conecte o Gestão Solar de novo no Claude para "
                         "carregar as ferramentas.")
        res = await _repassa(cli, rotulo, "tools/call",
                             {"name": ferramenta, "arguments": args if isinstance(args, dict) else {}})
    except (_Falhou, HTTPException) as e:  # HTTPException = SemConexao: o token próprio sumiu ou não abre
        return _erro(_motivo(e))
    if res.get("isError"):  # a recusa de lá chega com o nome do serviço
        res = {**res, "content": [{**c, "text": _sem_marca(c["text"])} if c.get("type") == "text" else c
                                  for c in res.get("content") or []]}
    return res


async def _instrucoes(db: Session, usuario: User) -> str:
    async def de(servico: str) -> str:
        rotulo = SERVICOS[servico][1]
        try:
            res = await _repassa(_cliente(db, usuario, servico), rotulo, "initialize",
                                 {"protocolVersion": _VERSOES[0], "capabilities": {},
                                  "clientInfo": {"name": "Gestão Solar", "version": "1.0"}})
        except (_Falhou, HTTPException) as e:
            return f"{rotulo}: não abriu agora ({_motivo(e)})."
        return f"{rotulo} (ferramentas {servico}_…): {_sem_marca(res.get('instructions') or '')}".strip()

    partes = await asyncio.gather(*(de(s) for s in servicos(usuario)))
    if not partes:
        return INSTRUCOES + "\n\nEsta conta não tem nenhum serviço liberado para consulta: o gerente da O&M libera " \
                            "em Usuários (oem-gs)."
    return INSTRUCOES + "\n\n" + "\n\n".join(partes)


async def _responder(db: Session, usuario: User, msg: dict) -> dict | None:
    metodo, mid, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:  # notificação (initialized, cancelled…): sem resposta
        return None
    if not isinstance(p, dict):
        p = {}
    if metodo == "initialize":
        pedida = p.get("protocolVersion")
        res = {
            "protocolVersion": pedida if pedida in _VERSOES else _VERSOES[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "Gestão Solar", "version": "1.0"},
            "instructions": await _instrucoes(db, usuario),
        }
    elif metodo == "ping":
        res = {}
    elif metodo == "tools/list":
        res = {"tools": await _ferramentas(db, usuario)}
    elif metodo == "tools/call":
        res = await _chamar(db, usuario, str(p.get("name") or ""), p.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Método desconhecido: {metodo}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def _sem_login(request: Request, motivo: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "invalid_token", "error_description": motivo},
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{_base(request)}/.well-known/oauth-protected-resource"'},
    )


def _quem(db: Session, request: Request) -> User | JSONResponse:
    cab = request.headers.get("Authorization", "")
    if not cab.lower().startswith("bearer "):
        return _sem_login(request, "Conecte o Gestão Solar para continuar.")
    linha = db.scalar(select(TokenMcp).where(TokenMcp.token_hash == _hash(cab.split(" ", 1)[1].strip())))
    agora = datetime.now(UTC)
    if linha is None or linha.revogado_em is not None or _aware(linha.expira_em) <= agora:
        return _sem_login(request, "Conexão expirada ou desfeita. Conecte o Gestão Solar de novo no Claude.")
    usuario = _conta_com_empresa(db, linha.user_id)
    if usuario is None or not usuario.ativo:
        return _sem_login(request, "Esta conta do Gestão Solar está desativada.")
    try:
        _empresa_ativa(db, usuario)
    except HTTPException as e:
        return _sem_login(request, str(e.detail))
    if linha.ultimo_uso_em is None or _aware(linha.ultimo_uso_em) < agora - timedelta(minutes=10):
        linha.ultimo_uso_em = agora
        db.commit()
    return usuario


@router.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})  # sem stream SSE: servidor sem estado


@router.post("/mcp")
async def mcp(request: Request, db: Session = Depends(get_db)):
    usuario = _quem(db, request)
    if isinstance(usuario, JSONResponse):
        return usuario
    try:
        corpo = await request.json()
    except ValueError:
        corpo = None
    if isinstance(corpo, list) and len(corpo) > _TETO_LOTE:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {
            "code": -32600, "message": f"No máximo {_TETO_LOTE} por pedido."}})
    if isinstance(corpo, list):
        respostas = [await _responder(db, usuario, m) for m in corpo if isinstance(m, dict)]
        saida = [r for r in respostas if r]
    elif isinstance(corpo, dict):
        saida = await _responder(db, usuario, corpo)
    else:
        return JSONResponse(status_code=400,
                            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}})
    if not saida:
        return Response(status_code=202)
    return JSONResponse(content=saida)
