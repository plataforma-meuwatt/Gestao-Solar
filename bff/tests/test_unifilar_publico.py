"""O unifilar num link público, temporário e só de ver (o Renan, 25/11/2026): o link assinado vence, cai com o
"encerrar todas" e com o helper tirado; a página é a do helper no modo "somente ver"; o documento vem pela porta do bot
com o token da pessoa; e o link sai pelo pé da resposta, fora do Log do bot."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services import assistente_geracao as ger
from app.services import assistente_helper as h
from app.services import unifilar_publico as up

HTML = (b'<!doctype html>\n<html lang="pt-BR"><head><meta charset="utf-8">\n<title>Unifilar da usina</title>\n'
        b'<link rel="stylesheet" href="/static/unifilar.css">\n</head><body>\n<script src="/static/unifilar.js"></script>')


def test_link_assinado_vence_e_nao_aceita_mexida():
    token, vence = up.criar(2, 14, agora=1_000_000)
    assert up.ler(token, agora=1_000_000 + 60) == (2, 14, 1_000_000)
    assert vence == datetime.fromtimestamp(1_000_000 + up.VALIDADE_S, UTC)
    assert up.ler(token, agora=1_000_000 + up.VALIDADE_S) is None                 # venceu
    assert up.ler(token, agora=1_000_000 - 1) is None                             # do futuro
    u, p, em, assinatura = token.split(".")
    assert up.ler(f"{u}.15.{em}.{assinatura}", agora=1_000_000) is None           # outra usina com a mesma assinatura
    for lixo in ("", "abc", "1.2.3", "1.2.zz.x", token + ".1"):
        assert up.ler(lixo, agora=1_000_000) is None


def test_pagina_do_helper_ganha_as_metas_e_os_caminhos_relativos():
    vence = datetime(2026, 11, 25, 21, 30, tzinfo=UTC)
    texto = up.pagina(HTML, vence).decode()
    assert '<meta charset="utf-8"><meta name="mw-uf-ver" content="documento">' in texto
    assert '<meta name="mw-uf-ate" content="2026-11-25T18:30:00-03:00">' in texto
    assert 'href="unifilar.css"' in texto and 'src="unifilar.js"' in texto and "/static/" not in texto
    assert up.pagina(b"<html><body>mudou</body></html>", vence) is None


@pytest.fixture
def pessoa(db, monkeypatch):
    u = User(apelido="renan.marquezini", nome="Renan", perfil=Perfil.GESTOR_EMPRESA, senha_hash="x", bot_helper=True)
    p = PlantLink(mw_plant_slug="pirapozinho", nome="Pirapozinho")
    db.add_all([u, p])
    db.commit()
    monkeypatch.setattr(User, "bot_ativo", property(lambda self: {"bot_helper"} if self.bot_helper else set()))
    monkeypatch.setattr(ger, "usinas_do_bot", lambda db_, user: [p])
    return u, p


def test_o_link_cai_com_encerrar_todas_e_com_o_helper_tirado(db, pessoa):
    u, p = pessoa
    token, _ = up.criar(u.id, p.id)
    assert up.pessoa_e_usina(db, token)[1].id == p.id
    u.sessoes_desde = datetime.now(UTC) + timedelta(seconds=5)                  # "encerrar todas" depois do link
    db.commit()
    assert up.pessoa_e_usina(db, token) is None
    u.sessoes_desde, u.bot_helper = None, False
    db.commit()
    assert up.pessoa_e_usina(db, token) is None
    u.bot_helper = True
    db.commit()
    assert up.pessoa_e_usina(db, up.criar(u.id, p.id + 1)[0]) is None            # usina fora do recorte
    from app.models.empresa import Empresa
    e = Empresa(nome="Splendor O&M")
    db.add(e)
    db.commit()
    u.empresa_id = e.id
    db.commit()
    assert up.pessoa_e_usina(db, token) is not None
    e.ativa = False                                                              # desativar a empresa para tudo
    db.commit()
    assert up.pessoa_e_usina(db, token) is None


@pytest.fixture
def cliente(db, pessoa, monkeypatch):
    chamadas = []

    class Helper:
        async def chamar(self, rota, corpo, origem, metodo="POST"):
            chamadas.append((rota, corpo))
            return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": {"ok": True, "documento": {"x": 1}}}

    async def _arquivo(nome):
        return {"unifilar.html": (HTML, "text/html"), "unifilar.js": (b"/* mw-uf-ver */", "text/javascript"),
                "unifilar.css": (b"body{}", "text/css")}.get(nome)

    monkeypatch.setattr(up, "arquivo", _arquivo)
    monkeypatch.setattr(h, "_cliente", lambda db_, user: Helper())
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app), chamadas
    finally:
        app.dependency_overrides.clear()


def test_pagina_documento_e_arquivos_do_link(cliente, pessoa):
    c, chamadas = cliente
    token, _ = up.criar(pessoa[0].id, pessoa[1].id)
    r = c.get(f"/publico/unifilar/{token}/")
    assert r.status_code == 200 and 'name="mw-uf-ver"' in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"] and r.headers["cache-control"] == "no-store"
    assert c.get(f"/publico/unifilar/{token}", follow_redirects=False).headers["location"] == f"{token}/"
    d = c.get(f"/publico/unifilar/{token}/documento?ler=1")
    assert d.status_code == 200 and d.json() == {"ok": True, "documento": {"x": 1}}
    assert chamadas == [("/api/religa/documento", {"slug": "pirapozinho", "ler": True, "publico": True})]
    assert c.get(f"/publico/unifilar/{token}/unifilar.js").text == "/* mw-uf-ver */"
    assert c.get(f"/publico/unifilar/{token}/religa.js").status_code == 404      # só os dois arquivos da página


def test_link_vencido_nao_le_nada(cliente):
    c, chamadas = cliente
    vencido, _ = up.criar(1, 1, agora=datetime.now(UTC).timestamp() - up.VALIDADE_S - 1)
    r = c.get(f"/publico/unifilar/{vencido}/")
    assert r.status_code == 410 and "venceu" in r.text and "color-scheme:dark" in r.text
    assert c.get(f"/publico/unifilar/{vencido}/documento?ler=1").status_code == 410
    assert c.get(f"/publico/unifilar/{vencido}/unifilar.js").status_code == 404
    assert chamadas == []


def test_helper_sem_o_modo_somente_ver_nao_abre(cliente, pessoa, monkeypatch):
    c, _ = cliente

    async def _velho(nome):
        return (HTML, "text/html") if nome == "unifilar.html" else (b"/* sem o modo */", "text/javascript")
    monkeypatch.setattr(up, "arquivo", _velho)
    token, _ = up.criar(pessoa[0].id, pessoa[1].id)
    r = c.get(f"/publico/unifilar/{token}/")
    assert r.status_code == 503 and "não abriu" in r.text


async def test_o_bot_manda_o_link_pelo_pe_da_resposta(db, pessoa, monkeypatch):
    u, p = pessoa

    async def _pronto():
        return True

    async def _vpn(cliente):
        return None

    class Helper:
        doc = {"equipamentos": [{"id": "dj_bt_skid1"}], "avisos": ["o Relé Geral não tem disjuntor no mapa do helper"]}
        pedidos = []

        async def chamar(self, rota, corpo, origem, metodo="POST"):
            self.pedidos.append((rota, corpo))
            return {"ok": True, "tipo": "leitura", "resposta": {"ok": True, "documento": self.doc}}
    helper = Helper()
    monkeypatch.setattr(up, "pronto", _pronto)
    monkeypatch.setattr(h, "_cliente", lambda ctx, user: helper)
    monkeypatch.setattr(h, "_vpn_parada", _vpn)
    ctx = ger.Contexto(db=db, user=u, telefone="+5517997377626")
    r = await h.diagrama_unifilar(ctx, {"usina": "pirapozinho"})
    assert r["link_enviado_pelo_sistema"] and "publico/unifilar/" not in str(r)   # a IA não vê o link
    assert r["o_desenho_avisa"] == helper.doc["avisos"]
    assert helper.pedidos == [("/api/religa/documento", {"slug": "pirapozinho", "ler": False, "publico": True})]
    url = ctx.segredos[0]
    assert url in ctx.rodape[0] and url.endswith("/")
    assert up.ler(url.rstrip("/").rsplit("/", 1)[1])[:2] == (u.id, p.id)

    helper.doc = {"equipamentos": []}                                      # a usina sem desenho no helper
    ctx = ger.Contexto(db=db, user=u, telefone="+5517997377626")
    r = await h.diagrama_unifilar(ctx, {"usina": "pirapozinho"})
    assert "não abriu no helper" in r["erro"] and not ctx.segredos and not ctx.rodape

    async def _fora():
        return False
    helper.doc = {"equipamentos": [{"id": "x"}]}
    monkeypatch.setattr(up, "pronto", _fora)
    ctx = ger.Contexto(db=db, user=u, telefone="+5517997377626")
    assert "erro" in await h.diagrama_unifilar(ctx, {"usina": "pirapozinho"}) and not ctx.segredos and not ctx.rodape


def test_limpar_os_trips_diz_cada_rele():
    """"Limpar os trips da usina" (helper 2.51.4): executado mesmo com o `ok` falso (o helper só dá ok quando tudo
    apagou), e cada relé com o que aconteceu, pela releitura dele."""
    resposta = {"ok": False, "todos": True, "resultado": "6 relés lidos; 2 com luz de desarme receberam o comando",
                "itens": [{"rele": "7SR10 SKID 1", "sent": True, "limpo": True, "resultado": "a luz apagou"},
                          {"rele": "7SR10 SKID 2", "sent": True, "limpo": False, "resultado": "a luz CONTINUA acesa"},
                          {"rele": "7SR10 SKID 3", "sent": False, "limpo": None,
                           "resultado": "o relé não respondeu à leitura: NADA enviado"},
                          {"rele": "7SR10 SKID 4", "sent": False, "limpo": True, "resultado": "já estava sem luz"}]}
    texto = h._desfecho("LIMPAR a luz de desarme de TODOS os relés da usina porto-ferreira.",
                        {"ok": False, "tipo": "execucao", "resposta": resposta})
    linhas = texto.splitlines()
    assert linhas[0] == "LIMPAR a luz de desarme de TODOS os relés da usina porto-ferreira:"
    assert linhas[1] == resposta["resultado"] and "Não executado" not in texto
    assert linhas[2:6] == ["✅ 7SR10 SKID 1: a luz apagou", "❌ 7SR10 SKID 2: a luz CONTINUA acesa",
                           "⚠️ 7SR10 SKID 3: o relé não respondeu à leitura: NADA enviado",
                           "✅ 7SR10 SKID 4: já estava sem luz"]
    assert linhas[-1].startswith("⚠️ Nem tudo apagou")
    tudo = {**resposta, "ok": True, "itens": resposta["itens"][:1]}
    assert h._desfecho("LIMPAR…", {"ok": True, "resposta": tudo}).endswith("✅ Tudo o que tinha luz de desarme apagou.")
    assert h._aceite("/api/religa/limpar", {"slug": "porto-ferreira", "disjuntor": "todos"}) == h._ACEITE_LIMPAR


async def test_a_proposta_de_limpar_vai_com_o_link_do_unifilar(db, pessoa, monkeypatch):
    u, p = pessoa
    u.senha_atuacao_hash = "x"
    db.commit()

    class Helper:
        async def chamar(self, rota, corpo, origem, metodo="POST"):
            return {"ok": True, "tipo": "proposta", "proposta": "P1", "resumo": "LIMPAR … de TODOS os relés",
                    "expira_em_s": 120}

    async def _pronto():
        return True

    async def _nada(*a, **k):
        return None
    monkeypatch.setattr(up, "pronto", _pronto)
    monkeypatch.setattr(h, "_cliente", lambda ctx, user: Helper())
    monkeypatch.setattr(h, "_vpn_parada", _nada)
    ctx = ger.Contexto(db=db, user=u, telefone="+5517997377626")
    r = await h.usina_helper(ctx, {"rota": "/api/religa/limpar", "corpo": {"slug": "pirapozinho", "disjuntor": "todos"}})
    assert r["proposta_pendente"] and ctx.rodape and "Acompanhe ao vivo no unifilar de Pirapozinho" in ctx.rodape[0]
    assert ctx.segredos and ctx.segredos[0] in ctx.rodape[0]                 # o link sai do Log do bot
    h.PENDENTES.pop(u.id, None)
    ctx = ger.Contexto(db=db, user=u, telefone="+5517997377626")             # ler não leva link
    monkeypatch.setattr(Helper, "chamar", lambda self, *a, **k: _leitura())

    async def _leitura():
        return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": {"ok": True}}
    await h.usina_helper(ctx, {"rota": "/api/religa/painel", "corpo": {"slug": "pirapozinho"}})
    assert not ctx.rodape and not ctx.segredos
