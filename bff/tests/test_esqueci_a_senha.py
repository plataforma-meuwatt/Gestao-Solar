"""O "esqueci a senha" (Plano Casa GS, R12): pelo WhatsApp do bot, do celular cadastrado, para qualquer conta (com o bot
liberado ou não), um link de 30 minutos e uma vez só, que não fica no Log do bot nem na cópia do gateway; a senha nova
encerra as sessões abertas; o e-mail só com remetente, e a resposta não confirma conta a quem tenta."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import conferir_senha, gerar_hash_senha
from app.main import app
from app.models.conversa_whatsapp import RegistroBot
from app.models.empresa import Empresa
from app.models.sessao import RedefinicaoDeSenha
from app.models.user import Perfil, User
from app.services import esqueci_a_senha


@pytest.fixture
def conta(db):
    a = Empresa(nome="Splendor O&M")
    db.add(a)
    db.commit()
    u = User(apelido="dono", nome="Dono", perfil=Perfil.CLIENTE, empresa_id=a.id, telefone="+5517999990000",
             email="dono@x.com", senha_hash=gerar_hash_senha("senha-antiga-1"))
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def http(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_o_pedido_exato_e_so_ele():
    for sim in ("Esqueci a senha!", "esqueci minha senha do GS", "Nova senha.", "perdi a senha", "Redefinir senha"):
        assert esqueci_a_senha.pediu(sim), sim
    for nao in ("esqueci a senha do inversor", "qual a senha do wifi?", "esqueci", "senha", ""):
        assert not esqueci_a_senha.pediu(nao), nao


def test_o_link_troca_a_senha_uma_vez_e_encerra_as_sessoes(http, conta, db):
    token = esqueci_a_senha.emitir(db, conta, "whatsapp")
    db.commit()
    assert esqueci_a_senha.link(token).endswith(f"/nova-senha#t={token}")
    assert db.query(RedefinicaoDeSenha).one().token_hash != token                  # só o hash fica
    assert http.post("/api/v1/auth/senha/nova", json={"token": token, "senha": "curta"}).status_code == 400
    assert http.post("/api/v1/auth/senha/nova", json={"token": token, "senha": "senha-nova-123"}).status_code == 204
    db.refresh(conta)
    assert conferir_senha("senha-nova-123", conta.senha_hash) and conta.sessoes_desde is not None
    r = http.post("/api/v1/auth/senha/nova", json={"token": token, "senha": "outra-senha-9"})
    assert r.status_code == 400 and ("já foi usado" in r.json()["detail"] or "venceu" in r.json()["detail"])
    # o novo link mata o de antes; o vencido não vale
    t1 = esqueci_a_senha.emitir(db, conta, "whatsapp")
    t2 = esqueci_a_senha.emitir(db, conta, "whatsapp")
    db.commit()
    assert http.post("/api/v1/auth/senha/nova", json={"token": t1, "senha": "senha-nova-456"}).status_code == 400
    db.query(RedefinicaoDeSenha).filter(RedefinicaoDeSenha.usada_em.is_(None)).update(
        {"expira_em": datetime.now(UTC) - timedelta(minutes=1)})
    db.commit()
    db.expire_all()                                       # a rota usa esta mesma sessão (o teste): relê do banco
    assert http.post("/api/v1/auth/senha/nova", json={"token": t2, "senha": "senha-nova-456"}).status_code == 400


def test_o_email_so_com_remetente_e_sem_confirmar_conta(http, conta, db, monkeypatch):
    from app.services import acessos
    for t in (acessos._erros, acessos._por_ip, acessos._avisados):
        t.clear()
    assert http.post("/api/v1/auth/senha/esqueci", json={"email": "dono@x.com"}).status_code == 503
    monkeypatch.setattr(get_settings(), "gs_smtp_host", "smtp.exemplo")
    monkeypatch.setattr(get_settings(), "gs_smtp_remetente", "nao-responda@gestao.solar")
    mandados = []
    monkeypatch.setattr(esqueci_a_senha, "mandar_email", lambda para, link: mandados.append((para, link)))
    import app.core.db as banco
    monkeypatch.setattr(banco, "SessionLocal", lambda: db)       # o trabalho depois da resposta usa o banco do teste
    assert http.post("/api/v1/auth/senha/esqueci", json={"email": "DONO@x.com"}).status_code == 202
    assert http.post("/api/v1/auth/senha/esqueci", json={"email": "ninguem@x.com"}).status_code == 202   # a mesma
    assert [p for p, _ in mandados] == ["dono@x.com"] and "/nova-senha#t=" in mandados[0][1]


def test_o_bot_manda_o_link_pelo_celular_cadastrado_sem_guardar(db, conta, monkeypatch):
    from app.services import assistente
    enviados = []

    async def enviar(**k):
        enviados.append(k)
        return {"ok": True}

    async def nada(*a, **k):
        return None
    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", enviar)
    monkeypatch.setattr(assistente, "_ocultar_no_gateway", nada)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    assert not conta.bot_liberado                                                   # vale sem o bot liberado
    asyncio.run(assistente._atender({"id": 91, "telefone": "+5517999990000", "tipo": "text",
                                     "texto": "Esqueci a senha!", "ocorrida_em": datetime.now(UTC).isoformat()}))
    assert len(enviados) == 1 and "/nova-senha#t=" in enviados[0]["texto"]
    token = enviados[0]["texto"].split("#t=")[1].split()[0]
    guardado = enviados[0].get("guardar")
    assert isinstance(guardado, str) and guardado and token not in guardado     # o gateway guarda a cópia SEM o link
    #                                                                             (sem `guardar`, guardaria o texto todo)
    reg = db.query(RegistroBot).one()
    assert token not in (reg.pergunta or "") + (reg.resposta or "") and reg.ferramentas == "esqueci_a_senha"
    assert esqueci_a_senha.conta_do_link(db, token)[1].id == conta.id


def test_esqueci_com_acao_de_equipamento_esperando_fala_da_senha_de_atuacao(db, conta, monkeypatch):
    """Com uma ação do helper esperando a senha de ATUAÇÃO, "esqueci a senha" é dela: o link de entrar no GS não a
    resolve. A ação cai e o bot diz quem a define (o gerente)."""
    from time import monotonic

    from app.services import assistente
    from app.services import assistente_helper as helper
    enviados = []

    async def enviar(**k):
        enviados.append(k)
        return {"ok": True}

    async def nada(*a, **k):
        return None
    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", enviar)
    monkeypatch.setattr(assistente, "_ocultar_no_gateway", nada)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    helper.PENDENTES[conta.id] = helper.Pendente(resumo="Desligar o inversor 13", expira=monotonic() + 300,
                                                 executar=nada)
    try:
        asyncio.run(assistente._atender({"id": 92, "telefone": "+5517999990000", "tipo": "text",
                                         "texto": "esqueci a senha", "ocorrida_em": datetime.now(UTC).isoformat()}))
    finally:
        helper.PENDENTES.pop(conta.id, None)
    assert len(enviados) == 1 and "senha de atuação" in enviados[0]["texto"] and "/nova-senha" not in enviados[0]["texto"]
    assert db.query(RedefinicaoDeSenha).count() == 0                             # nenhum link de entrar foi emitido
