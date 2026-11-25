"""O link público do unifilar (`services/unifilar_publico`): a página do helper no modo "somente ver", os dois arquivos
dela e o documento, lido pela porta do bot com o token do meuWatt de quem pediu o link. Só leitura: nada aqui comanda,
e cada pedido confere de novo se o link ainda vale para a pessoa."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import unifilar_publico as up

router = APIRouter(prefix="/publico/unifilar", tags=["público · unifilar só de ver"])

_SEM_RASTRO = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow",
               "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"}
_PAGINA = {**_SEM_RASTRO, "Content-Security-Policy": (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")}
VENCEU = "Este link do unifilar venceu."
PECA_OUTRO = "Peça outro pelo WhatsApp do Gestão Solar."


def _aviso(titulo: str, texto: str, status: int) -> HTMLResponse:
    corpo = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        "<title>Unifilar da usina</title><style>"
        ":root{--fundo:#f4f6f8;--cartao:#fff;--texto:#1d2733;--fraco:#5b6775;--borda:#d5dbe1}"
        "@media (prefers-color-scheme:dark){:root{--fundo:#0f1419;--cartao:#1a2129;--texto:#e6ebf0;--fraco:#9aa7b4;"
        "--borda:#2e3843}}"
        "body{margin:0;background:var(--fundo);color:var(--texto);font:16px/1.5 system-ui,sans-serif}"
        "main{max-width:420px;margin:12vh auto;padding:0 16px}"
        "section{background:var(--cartao);border:1px solid var(--borda);border-radius:12px;padding:24px}"
        "h1{font-size:20px;margin:0 0 8px}p{color:var(--fraco);margin:0}</style></head><body><main><section>"
        f"<h1>{titulo}</h1><p>{texto}</p></section></main></body></html>"
    )
    return HTMLResponse(corpo, status_code=status, headers={
        **_SEM_RASTRO, "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})


@router.get("/{token}", include_in_schema=False)
def sem_barra(token: str) -> RedirectResponse:
    """Os arquivos e o documento são relativos à página: ela mora na "pasta" do link."""
    return RedirectResponse(f"{token}/", status_code=307)


@router.get("/{token}/", include_in_schema=False)
async def pagina(token: str, db: Session = Depends(get_db)) -> Response:
    achado = up.pessoa_e_usina(db, token)
    db.commit()
    if achado is None:
        return _aviso(VENCEU, PECA_OUTRO, 410)
    html = await up.arquivo("unifilar.html")
    corpo = up.pagina(html[0], achado[2]) if html and await up.pronto() else None
    if corpo is None:
        return _aviso("O unifilar não abriu agora.", "O helper não respondeu. Tente de novo em instantes.", 503)
    return HTMLResponse(corpo, headers=_PAGINA)


@router.get("/{token}/documento", include_in_schema=False)
async def documento(token: str, ler: int = 0, db: Session = Depends(get_db)) -> JSONResponse:
    """O mesmo JSON que o `/api/religa/documento` dá à tela do helper. 410 = o link não vale mais (a página para)."""
    from app.services import assistente_helper as helper
    from app.services.vinculos import SemConexao

    achado = up.pessoa_e_usina(db, token)
    if achado is None:
        db.commit()
        return JSONResponse({"ok": False, "error": VENCEU}, status_code=410, headers=_SEM_RASTRO)
    u, usina, _ = achado
    try:
        cliente = helper._cliente(db, u)
    except SemConexao as e:
        db.commit()
        return JSONResponse({"ok": False, "error": f"helper indisponível: {e}"}, status_code=503, headers=_SEM_RASTRO)
    slug = usina.mw_plant_slug
    db.commit()                                           # solta a conexão: o helper leva até ~30 s lendo
    d = await cliente.chamar("/api/religa/documento", {"slug": slug, "ler": bool(ler)}, origem="link do unifilar (GS)")
    r = d.get("resposta") if isinstance(d.get("resposta"), dict) else None
    if d.get("ok") and d.get("tipo") == "leitura" and r is not None:
        return JSONResponse(r, headers=_SEM_RASTRO)
    motivo = (r or {}).get("error") or d.get("error") or d.get("reason") or "o helper não respondeu"
    return JSONResponse({"ok": False, "error": motivo}, status_code=502, headers=_SEM_RASTRO)


@router.get("/{token}/{nome}", include_in_schema=False)
async def arquivo(token: str, nome: str) -> Response:
    if nome not in ("unifilar.js", "unifilar.css") or up.ler(token) is None:
        return Response(status_code=404, headers=_SEM_RASTRO)
    a = await up.arquivo(nome)
    if a is None:
        return Response(status_code=502, headers=_SEM_RASTRO)
    return Response(a[0], media_type=a[1], headers=_SEM_RASTRO)
