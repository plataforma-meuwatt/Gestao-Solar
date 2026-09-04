"""Pendências do portal do cliente — e as duas cercas que impedem ler a pasta interna.

O dono (09/2026): *"se tiver alguma pendência que ele cobrou a gente, ele quer ver lá, igual
tem no meuPlano, mas de forma mais simples"*. O risco desta aba é o mesmo das ordens, com
um agravante: a pendência tem `shareable`, e o token de serviço da ponte é de quem MANDA na
usina — para ele, o filtro do meuPlano é no-op. Uma pendência interna ("cliente não pagou a
NF de julho") chegaria ao portal do próprio cliente sem que ninguém reclamasse.

O que estes testes protegem, em ordem de gravidade:

1. **`shareable` é re-filtrado aqui**, mesmo que o upstream já tenha filtrado.
2. **O detalhe confere o escopo** antes de devolver — 404, nunca 403.
3. **O documento só sai se estiver entre os publicados** daquela pendência autorizada.
4. **Nenhuma URL devolvida aponta para o meuPlano** nem carrega token.
5. **A tradução é do servidor**: prazo vencido é vermelho, e o contador some (nulo) quando
   alguma usina não respondeu.

Nada de rede: o cliente do meuPlano entra como fantasia.
"""

from datetime import date, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.api.v1.pendencias as p
from app.api.v1.pendencias import (
    _pendencia_out,
    _situacao_da_pendencia,
    detalhar_pendencia,
    documento_da_pendencia,
    html_para_texto,
    listar_pendencias,
)
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess

HOJE = date.today()
MEUPLANO = "https://meuplano.exemplo"


@pytest.fixture(autouse=True)
def limpa_cache():
    p._autorizacoes.clear()
    p._em_voo.clear()
    yield
    p._autorizacoes.clear()
    p._em_voo.clear()


@pytest.fixture
def dono(db):
    u = User(
        apelido="renan.marquezini",
        email="renan@exemplo.com.br",
        nome="Renan",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


def _conceder(db, usuario, usina):
    db.add(UserPlantAccess(user_id=usuario.id, plant_link_id=usina.id))
    db.commit()


def _nao_existe(path: str) -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", f"{MEUPLANO}/api/v1/meuacesso{path}")
    resposta = httpx.Response(404, json={"detail": "não existe"}, request=pedido)
    return httpx.HTTPStatusError("404", request=pedido, response=resposta)


def _pendencia(id_, usina_id, *, shareable=True, status="ABERTO", prazo=None, extra=None,
               ultima=None, **resto):
    return {
        "id": id_, "numero": 1000 + id_, "kind": "pendencia", "usina_id": usina_id,
        "title": f"Pendência {id_}", "status": status, "shareable": shareable,
        "end_date": prazo.isoformat() if prazo else None,
        "created_at": "2026-08-01T12:00:00Z",
        "last_activity_at": ultima,
        "extra": extra or {},
        "responsaveis": [{"id": 7, "name": "Diogo"}],
        "criticidade": resto.pop("criticidade", None),
        "doc_count": 1,
        "os_count": 0,
        **resto,
    }


class ClienteFalso:
    """O meuPlano como fantasia. `por_usina` é o que a rota `visao-cliente` devolve para
    cada usina; `detalhes` é o detalhe por id (com documentos e ordens dentro)."""

    def __init__(self, por_usina, detalhes=None, documentos=None):
        self.por_usina = por_usina
        self.detalhes = detalhes or {}
        self.documentos = documentos or {}
        self.chamadas_de_detalhe = 0

    async def vc_pendencias(self, usina_id):
        resposta = self.por_usina.get(usina_id)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if resposta is not None else []

    async def vc_pendencia(self, cid):
        self.chamadas_de_detalhe += 1
        if cid not in self.detalhes:
            raise _nao_existe(f"/visao-cliente/pendencias/{cid}")
        return self.detalhes[cid]

    async def vc_documento(self, cid, did):
        return self.documentos[(cid, did)]


def _instala(monkeypatch, cliente):
    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.pendencias.integracoes.cliente_meuplano", _cliente)
    return cliente


# ── lista ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_nao_compartilhavel_nao_sai_mesmo_que_o_upstream_a_mande(db, dono, usinas, monkeypatch):
    """A segunda cerca: três vieram, uma é interna, saem duas."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({minha.mp_usina_id: [
        _pendencia(1, minha.mp_usina_id),
        _pendencia(2, minha.mp_usina_id, shareable=False),
        _pendencia(3, minha.mp_usina_id, status="CONCLUIDO"),
    ]}))

    saida = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert sorted(x.id for x in saida.pendencias) == [1, 3]
    assert saida.total == 2
    assert saida.abertas == 1
    assert saida.concluidas == 1
    assert saida.prazo_vencido == 0


@pytest.mark.asyncio
async def test_pendencia_de_outra_usina_no_corpo_da_resposta_nao_sai(db, dono, usinas, monkeypatch):
    """`usina_id` tem de ser o do vínculo perguntado — o upstream respondendo pela usina
    errada (ou uma ponte apontada para a rota interna) não passa."""
    minha, outra = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({minha.mp_usina_id: [
        _pendencia(1, minha.mp_usina_id),
        _pendencia(2, outra.mp_usina_id),
    ]}))

    saida = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert [x.id for x in saida.pendencias] == [1]


@pytest.mark.asyncio
async def test_prazo_vencido_vira_tom_parado_so_se_nao_concluiu(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    ontem = HOJE - timedelta(days=1)
    _instala(monkeypatch, ClienteFalso({minha.mp_usina_id: [
        _pendencia(1, minha.mp_usina_id, prazo=ontem),
        _pendencia(2, minha.mp_usina_id, prazo=ontem, status="CONCLUIDO"),
        _pendencia(3, minha.mp_usina_id, prazo=HOJE + timedelta(days=3), status="EM_ANDAMENTO"),
    ]}))

    saida = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)
    por_id = {x.id: x for x in saida.pendencias}

    assert (por_id[1].situacao, por_id[1].tom) == ("Prazo vencido", "parado")
    assert (por_id[2].situacao, por_id[2].tom) == ("Concluída", "semDados")
    assert (por_id[3].situacao, por_id[3].tom) == ("Em andamento", "ok")
    assert saida.prazo_vencido == 1


def test_traducao_de_situacao_e_criticidade():
    """Vocabulário do servidor: a tela nunca reinterpreta."""
    assert _situacao_da_pendencia({"status": "ABERTO"}, HOJE) == ("ABERTO", "Aguardando", "alerta")
    # Estado desconhecido não vira "—": vira o próprio código, para alguém reparar.
    assert _situacao_da_pendencia({"status": "PARADO"}, HOJE)[1:] == ("Parado", "semDados")
    link = PlantLink(id=9, mw_plant_slug="x", mp_usina_id=1, nome="Usina X")
    for cru, tom in (("critica", "parado"), ("alta", "multiplos"), ("media", "alerta"), ("baixa", "semDados")):
        out = _pendencia_out(_pendencia(1, 1, criticidade=cru), link, HOJE)
        assert (out.criticidade, out.criticidade_tom) == (cru, tom)
    assert _pendencia_out(_pendencia(1, 1), link, HOJE).criticidade_tom is None


def test_cobrada_pelo_cliente_vem_do_extra_e_nunca_do_shareable():
    """`Compart.` é padrão TRUE no meuPlano; compartilhável sozinho não diz "cobrada"."""
    link = PlantLink(id=9, mw_plant_slug="x", mp_usina_id=1, nome="Usina X")
    assert _pendencia_out(_pendencia(1, 1), link, HOJE).cobrada_pelo_cliente is False
    assert _pendencia_out(_pendencia(1, 1, extra={"cobrada_pelo_cliente": True}), link, HOJE).cobrada_pelo_cliente is True
    # A rota `visao-cliente` pode mandar o campo já resolvido.
    assert _pendencia_out(_pendencia(1, 1, cobrada_pelo_cliente=True), link, HOJE).cobrada_pelo_cliente is True


@pytest.mark.asyncio
async def test_ordem_e_ultima_atividade_primeiro(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({minha.mp_usina_id: [
        _pendencia(1, minha.mp_usina_id, ultima="2026-08-10T10:00:00Z"),
        _pendencia(2, minha.mp_usina_id, ultima=None, created_at=None),
        _pendencia(3, minha.mp_usina_id, ultima="2026-09-01T10:00:00Z"),
    ]}))

    saida = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert [x.id for x in saida.pendencias] == [3, 1, 2], "sem data vai para o fim"


@pytest.mark.asyncio
async def test_usina_fora_do_escopo_responde_404(db, dono, usinas, monkeypatch):
    minha, outra = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({}))

    with pytest.raises(HTTPException) as e:
        await listar_pendencias(usina_id=outra.id, db=db, usuario=dono)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_usina_sem_meuplano_avisa_e_total_fica_nulo(db, dono, usinas, monkeypatch):
    """Não é 404: a usina é dela. A tela precisa explicar por que está vazia."""
    minha, _ = usinas
    minha.mp_usina_id = None
    db.commit()
    _conceder(db, dono, minha)
    cliente = _instala(monkeypatch, ClienteFalso({}))

    saida = await listar_pendencias(usina_id=minha.id, db=db, usuario=dono)

    assert saida.total is None
    assert saida.aviso and "meuPlano" in saida.aviso
    assert saida.usinas_com_manutencao == 0

    # E sem `usina_id`, com nenhuma usina ligada: mesma frase, nenhuma ida ao upstream.
    saida = await listar_pendencias(usina_id=None, db=db, usuario=dono)
    assert saida.total is None and saida.aviso
    assert cliente.chamadas_de_detalhe == 0


@pytest.mark.asyncio
async def test_uma_usina_que_falhou_zera_os_contadores_e_avisa(db, dono, usinas, monkeypatch):
    """Somar só quem respondeu daria um total que parece completo e não é."""
    minha, outra = usinas
    _conceder(db, dono, minha)
    _conceder(db, dono, outra)
    _instala(monkeypatch, ClienteFalso({
        minha.mp_usina_id: [_pendencia(1, minha.mp_usina_id)],
        outra.mp_usina_id: httpx.ReadTimeout("demorou"),
    }))

    saida = await listar_pendencias(usina_id=None, db=db, usuario=dono)

    assert [x.id for x in saida.pendencias] == [1], "o que veio, sai"
    assert saida.total is None and saida.abertas is None and saida.prazo_vencido is None
    assert saida.aviso and outra.nome in saida.aviso


# ── detalhe ─────────────────────────────────────────────────────────────────


def _detalhe(usina_id, **resto):
    base = _pendencia(10, usina_id, extra={"cobrada_pelo_cliente": True}, **resto)
    base["parecer_html"] = "<p>Trocamos o disjuntor.</p><p>Falta o <b>laudo</b>.</p>"
    base["documentos"] = [
        {"id": 501, "container_id": 10, "filename": "laudo.pdf", "visivel_cliente": True,
         "created_at": "2026-08-20T09:00:00Z", "url": f"{MEUPLANO}/interno/501"},
        {"id": 502, "container_id": 10, "filename": "rascunho.docx", "visivel_cliente": False,
         "created_at": "2026-08-21T09:00:00Z", "url": f"{MEUPLANO}/interno/502"},
        {"id": 503, "container_id": 10, "filename": "laudo-v1.pdf", "visivel_cliente": True,
         "is_current": False, "created_at": "2026-08-19T09:00:00Z"},
    ]
    base["ordens"] = [
        {"id": 1016, "plant_id": usina_id, "objetivo": "Troca do disjuntor",
         "status": "APROVADA", "task_count": 3, "task_realized_count": 3},
    ]
    return base


@pytest.mark.asyncio
async def test_detalhe_traz_parecer_documentos_publicados_e_ordens(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({}, detalhes={10: _detalhe(minha.mp_usina_id)}))

    saida = await detalhar_pendencia(cid=10, db=db, usuario=dono)

    assert saida.id == 10 and saida.usina_id == minha.id
    assert saida.cobrada_pelo_cliente is True
    assert saida.parecer == "Trocamos o disjuntor.\n\nFalta o laudo."
    assert [d.id for d in saida.documentos_publicados] == [501], "só publicado E vigente"
    assert saida.documentos_publicados[0].url == "/api/v1/manutencao/pendencias/10/documentos/501"
    assert [o.id for o in saida.ordens] == [1016]
    assert saida.ordens[0].situacao == "Concluída"
    assert not hasattr(saida, "comments") and not hasattr(saida, "requirements")


@pytest.mark.asyncio
async def test_nenhuma_url_aponta_para_o_meuplano_nem_carrega_token(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({}, detalhes={10: _detalhe(minha.mp_usina_id)}))

    saida = await detalhar_pendencia(cid=10, db=db, usuario=dono)

    texto = saida.model_dump_json()
    assert MEUPLANO not in texto
    assert "token" not in texto.lower()


@pytest.mark.asyncio
async def test_detalhe_de_usina_fora_do_escopo_responde_404(db, dono, usinas, monkeypatch):
    minha, outra = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({}, detalhes={10: _detalhe(outra.mp_usina_id)}))

    with pytest.raises(HTTPException) as e:
        await detalhar_pendencia(cid=10, db=db, usuario=dono)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_detalhe_nao_compartilhavel_responde_404(db, dono, usinas, monkeypatch):
    """Mesmo dentro do escopo: a segunda cerca vale no detalhe também."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({}, detalhes={10: _detalhe(minha.mp_usina_id, shareable=False)}))

    with pytest.raises(HTTPException) as e:
        await detalhar_pendencia(cid=10, db=db, usuario=dono)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_detalhe_inexistente_responde_404(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({}, detalhes={}))

    with pytest.raises(HTTPException) as e:
        await detalhar_pendencia(cid=99, db=db, usuario=dono)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_detalhe_em_envelope_container_tambem_abre(db, dono, usinas, monkeypatch):
    """A rota `visao-cliente` pode responder `{container, documentos, ordens}`."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    cheio = _detalhe(minha.mp_usina_id)
    envelope = {"container": {k: v for k, v in cheio.items() if k not in ("documentos", "ordens")},
                "documentos": cheio["documentos"], "ordens": cheio["ordens"]}
    _instala(monkeypatch, ClienteFalso({}, detalhes={10: envelope}))

    saida = await detalhar_pendencia(cid=10, db=db, usuario=dono)

    assert saida.id == 10 and [d.id for d in saida.documentos_publicados] == [501]


# ── HTML → texto ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("html, esperado", [
    ("<p>a<br>b</p>", "a\nb"),
    ("<p>a</p><p></p><p></p><p>b</p>", "a\n\nb"),
    ("<ul><li>um</li><li>dois &amp; tr&ecirc;s</li></ul>", "um\ndois & três"),
    ("texto <b>forte</b> <script>alert(1)</script>", "texto forte alert(1)"),
    ("   ", None),
    (None, None),
])
def test_parecer_html_vira_texto_com_quebras(html, esperado):
    assert html_para_texto(html) == esperado


# ── documento ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_documento_publicado_sai_inline_e_privado(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    cliente = _instala(monkeypatch, ClienteFalso(
        {}, detalhes={10: _detalhe(minha.mp_usina_id)},
        documentos={(10, 501): (b"%PDF-1.4 laudo", "application/pdf")},
    ))

    r = await documento_da_pendencia(cid=10, did=501, db=db, usuario=dono)

    assert r.body == b"%PDF-1.4 laudo"
    assert r.media_type == "application/pdf"
    assert "private" in r.headers["cache-control"]
    assert r.headers["content-disposition"].startswith("inline;")
    assert cliente.chamadas_de_detalhe == 1


@pytest.mark.asyncio
async def test_documento_fora_da_lista_publicada_responde_404(db, dono, usinas, monkeypatch):
    """O download do meuPlano é aberto por id — este portão é o que impede ler o rascunho."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso(
        {}, detalhes={10: _detalhe(minha.mp_usina_id)},
        documentos={(10, 502): (b"rascunho interno", "application/octet-stream")},
    ))

    with pytest.raises(HTTPException) as e:
        await documento_da_pendencia(cid=10, did=502, db=db, usuario=dono)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_dois_documentos_da_mesma_pendencia_custam_uma_autorizacao(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    detalhe = _detalhe(minha.mp_usina_id)
    detalhe["documentos"].append({"id": 504, "filename": "foto.jpg", "visivel_cliente": True,
                                  "created_at": "2026-08-22T09:00:00Z"})
    cliente = _instala(monkeypatch, ClienteFalso(
        {}, detalhes={10: detalhe},
        documentos={(10, 501): (b"%PDF", "application/pdf"), (10, 504): (b"\xff\xd8", "image/jpeg")},
    ))

    await documento_da_pendencia(cid=10, did=501, db=db, usuario=dono)
    await documento_da_pendencia(cid=10, did=504, db=db, usuario=dono)

    assert cliente.chamadas_de_detalhe == 1


@pytest.mark.asyncio
async def test_a_autorizacao_guardada_e_por_usuario(db, dono, usinas, monkeypatch):
    """A chave inclui quem pediu: o cache de um dono não abre a pendência para outro."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    outro = User(apelido="vizinho", nome="Vizinho", perfil=Perfil.CLIENTE,
                 senha_hash=gerar_hash_senha("x-1234"))
    db.add(outro)
    db.commit()
    _instala(monkeypatch, ClienteFalso(
        {}, detalhes={10: _detalhe(minha.mp_usina_id)},
        documentos={(10, 501): (b"%PDF", "application/pdf")},
    ))

    await documento_da_pendencia(cid=10, did=501, db=db, usuario=dono)
    with pytest.raises(HTTPException) as e:
        await documento_da_pendencia(cid=10, did=501, db=db, usuario=outro)
    assert e.value.status_code == 404


# ── pelo HTTP ───────────────────────────────────────────────────────────────


@pytest.fixture
def cliente_http(db):
    """Uma aplicação só com este router: o que se testa aqui é a rota e o portão dela, e o
    `app.main` inteiro entra por `test_billing_api`. Montar a mínima mantém este arquivo
    imune a um router vizinho quebrado no meio de um deploy."""
    app = FastAPI()
    app.include_router(p.router)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_sem_sessao_e_401_e_rota_irma_inexistente_e_404(cliente_http):
    """O par que prova o deploy: a rota nova recusa sem token, a inexistente não existe."""
    assert cliente_http.get("/api/v1/manutencao/pendencias").status_code == 401
    assert cliente_http.get("/api/v1/manutencao/pendenciaz").status_code == 404


def test_nome_de_arquivo_fora_do_latin1_nao_derruba_o_download(db, dono, usinas, monkeypatch, cliente_http):
    """O nome vem do upload da equipe. "Laudo – térmico.pdf" (travessão do Word) não cabe
    em latin-1, que é como o Starlette codifica cabeçalho — sem o RFC 5987 isso era 500
    depois de o arquivo já ter sido baixado do meuPlano."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    detalhe = _detalhe(minha.mp_usina_id)
    detalhe["documentos"][0]["filename"] = 'Laudo – "térmico" — Skid 02.pdf'
    _instala(monkeypatch, ClienteFalso(
        {}, detalhes={10: detalhe},
        documentos={(10, 501): (b"%PDF-1.4 laudo", "application/pdf")},
    ))
    token, _ = criar_token(dono.id)

    r = cliente_http.get("/api/v1/manutencao/pendencias/10/documentos/501",
                         headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    assert r.content == b"%PDF-1.4 laudo"
    disposicao = r.headers["content-disposition"]
    assert disposicao.startswith('inline; filename="Laudo _ termico _ Skid 02.pdf"')
    assert "filename*=UTF-8''Laudo%20%E2%80%93%20t%C3%A9rmico%20%E2%80%94%20Skid%2002.pdf" in disposicao


def test_pelo_http_com_sessao_de_cliente(db, dono, usinas, monkeypatch, cliente_http):
    minha, _ = usinas
    _conceder(db, dono, minha)
    _instala(monkeypatch, ClienteFalso({minha.mp_usina_id: [
        _pendencia(1, minha.mp_usina_id, prazo=HOJE - timedelta(days=2)),
    ]}))
    token, _ = criar_token(dono.id)

    r = cliente_http.get(f"/api/v1/manutencao/pendencias?usina_id={minha.id}",
                         headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["total"] == 1 and corpo["prazo_vencido"] == 1
    assert corpo["pendencias"][0]["tom"] == "parado"
    assert corpo["pendencias"][0]["usina_id"] == minha.id
    assert isinstance(corpo["pendencias"][0]["aberta_em"], str)
    assert corpo["pendencias"][0]["prazo"] == (HOJE - timedelta(days=2)).isoformat()
