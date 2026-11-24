"""As leituras do bot e do conector reusam a sessão da pessoa no TermoVision (24/11/2026: eram 853 entradas por dia na
conta do Renan, uma por consulta). Entra de novo quando a sessão passa de 30 min aqui, quando lá responde 401 e quando
o acesso muda."""
import httpx

from app.models.user import Perfil, User
from app.services import assistente_termovision as tv


def _tv(monkeypatch):
    lado = {"entradas": 0, "valida": None}

    def responde(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/conta/gs":
            lado["entradas"] += 1
            lado["valida"] = f"s{lado['entradas']}"
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": f"tv_sessao={lado['valida']}; Path=/"})
        cookies = dict(c.strip().split("=", 1) for c in (req.headers.get("cookie") or "").split(";") if "=" in c)
        if cookies.get("tv_sessao") != lado["valida"]:
            return httpx.Response(401, json={"detail": "sessão vencida"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})

    real = httpx.AsyncClient

    class _Cliente(real):
        def __init__(self, *a, **k):
            super().__init__(*a, transport=httpx.MockTransport(responde), **k)

    monkeypatch.setattr(httpx, "AsyncClient", _Cliente)
    monkeypatch.setattr(tv, "assercao", lambda db, user, liberado=None: "passe")
    monkeypatch.setattr(tv, "_base", lambda: "https://tv.teste")
    return lado


async def test_a_sessao_e_reusada_e_renovada_so_quando_precisa(db, monkeypatch):
    lado = _tv(monkeypatch)
    u = User(apelido="ana", nome="Ana", perfil=Perfil.TECNICO, termovision_liberado=True)
    db.add(u)
    db.commit()
    tv.esquecer(u.id)
    cliente = tv.ClienteMcp(db, u)
    for _ in range(3):
        assert (await cliente.mcp({"id": 1, "method": "tools/list"}))["result"] == {"tools": []}
    assert lado["entradas"] == 1                            # três consultas, uma entrada
    lado["valida"] = "revogada-la"                         # o TermoVision derrubou a sessão: 401, entra de novo
    assert (await cliente.mcp({"id": 1, "method": "tools/list"}))["result"] == {"tools": []}
    assert lado["entradas"] == 2
    monkeypatch.setattr(tv, "SESSAO_S", 0)                 # passou o prazo daqui: entra de novo
    await cliente.mcp({"id": 1, "method": "tools/list"})
    assert lado["entradas"] == 3
    monkeypatch.setattr(tv, "SESSAO_S", 1800)
    await tv.provisionar(db, u, True)                      # o acesso mudou: entra de novo
    await cliente.mcp({"id": 1, "method": "tools/list"})
    assert lado["entradas"] == 4
