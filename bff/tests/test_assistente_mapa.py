"""A foto do mapa único pelo bot (o dono, 18/11/2026: "o bot manda um print com a string pintada e a posição dela, nome
etc."): o objeto pelo nome dito NA ORDEM ("U1-3S22" não é "U3-1S22"), também com a palavra do tipo junto; a foto da
própria página do mapa aberta como a pessoa (sessão de 5 min, só leitura, só na origem do portal) e só com o objeto em
destaque na legenda; a legenda que a página desenhou; o estado com o porquê e a hora ("Normal" só com dado fresco); e a
posição em Google Maps e Waze ao pé da resposta — também quando a foto não sai. Nenhum teste abre um navegador: a
`foto()` roda contra uma página falsa."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import playwright.async_api
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1 import mapa as api_mapa
from app.core import security
from app.models.empresa import Empresa
from app.models.user import Perfil, User, VinculoProduto
from app.services import assistente
from app.services import assistente_geracao as ger
from app.services import assistente_mapa as mapa
from app.services import vinculos

FAIXA = {"type": "Polygon", "coordinates": [[[-46.37, -22.30], [-46.36, -22.30], [-46.36, -22.29], [-46.37, -22.29],
                                             [-46.37, -22.30]]]}
PONTO = {"type": "Point", "coordinates": [-46.5, -22.5]}
OBJETOS = [{"id": 501, "tipo": "string", "nome": "U1-3S22", "geometria": FAIXA},
           {"id": 502, "tipo": "string", "nome": "U3-1S22", "geometria": FAIXA},
           {"id": 7, "tipo": "outro", "nome": None, "node_id": 70, "node_nome": "Câmera 01", "node_tipo": "camera",
            "geometria": PONTO},
           {"id": 8, "tipo": "inversor", "nome": "INV-13", "geometria": PONTO},
           {"id": 10, "tipo": "transformador", "nome": "TR-02", "geometria": PONTO},
           {"id": 9, "tipo": "outro", "nome": "Poste", "node_id": 77, "geometria": {"type": "Polygon", "coordinates": []}}]
AGORA = datetime.now(UTC)
RECENTE = (AGORA - timedelta(minutes=3)).isoformat()
LEGENDA = "Ouro Fino · U1-3S22 (String) · Em alarme: String sem corrente no dia."


# ── achar o objeto
def test_centro_do_ponto_da_linha_e_do_contorno():
    assert mapa.centro(PONTO) == (-22.5, -46.5)
    assert mapa.centro({"type": "LineString", "coordinates": [[-46.0, -22.0], [-46.2, -22.2]]}) == (-22.1, -46.1)
    lat, lng = mapa.centro(FAIXA)                         # o vértice que fecha o contorno não pesa duas vezes
    assert (round(lat, 3), round(lng, 3)) == (-22.295, -46.365)
    assert mapa.centro({"type": "Polygon", "coordinates": []}) is None and mapa.centro(None) is None


def test_o_nome_casa_na_ordem_e_pelo_tipo():
    estado = {501: {"equipamento": "Inv 13 · string 26 (6S26)"}}

    def ids(termo):
        return [o["id"] for o in mapa.achar(OBJETOS, estado, termo)[0]]

    assert ids("u1-3s22") == [501] and ids("U3-1S22") == [502]   # os números na ordem: nunca a string vizinha
    assert ids("string U1-3S22") == [501] and ids("a string U1-3S22") == [501]   # com a palavra do tipo junto
    assert ids("trafo 2") == [10]                                 # só os números, entre os daquele tipo
    assert ids("Inv 13 string 26") == [501] and ids("string 26 do inversor 13") == [501]
    assert ids("Inv 26 string 13") == []                          # a ordem trocada é OUTRA string
    assert ids("câmera 1") == [7] and ids("câmera 7") == []        # "câmera 7" não é o "Inversor 7"
    assert ids("inversor 13") == [8]                             # o nome pelo começo da palavra: INV-13
    assert mapa.achar(OBJETOS, estado, "câmera 9") == ([], ["Câmera 01"])   # sem achado: os do tipo pedido


def test_situacao_com_motivo_e_hora_e_normal_so_com_dado_fresco():
    def s(e, porque=None):
        return mapa.situacao(e, porque, AGORA)

    assert s({"estado": "alarme", "motivo": "Sem corrente.", "leitura_em": RECENTE}).startswith(
        "Em alarme: Sem corrente. (dado de ")
    assert s({"estado": "ok", "leitura_em": RECENTE}).startswith("Normal (dado de ")
    velho = (AGORA - timedelta(hours=3)).isoformat()
    assert s({"estado": "ok", "leitura_em": velho}).startswith("sem cor: o último dado é de ")
    assert s({"estado": "ok"}) == "sem cor: o estado veio sem a hora do dado"
    assert s({"estado": "manutencao", "leitura_em": RECENTE}) == "sem cor: estado desconhecido (manutencao)"
    assert s(None, "o estado dos equipamentos ainda não está disponível") == (
        "sem cor: o estado dos equipamentos ainda não está disponível")
    assert s(None) == "sem cor: este equipamento ainda não está ligado ao monitoramento"


# ── a aba da foto
def test_a_aba_abre_a_pagina_do_destaque_e_grava_a_sessao_so_no_portal():
    url = mapa.alvo(31, 501)
    assert url == "https://gestao.solar/usinas/31/mapa?destaque=501&print=1"
    js = mapa.guardar_sessao({"token": "t"}, url)
    assert "location.origin === \"https://gestao.solar\"" in js and "'gs_portal_sessao'" in js
    assert '\\"token\\": \\"t\\"' in js                              # o JSON da sessão vai como TEXTO no localStorage


@pytest.mark.parametrize("metodo,fica", [("POST", False), ("PATCH", False), ("DELETE", False), ("GET", True),
                                         ("HEAD", True)])
async def test_a_aba_so_le(metodo, fica):
    feito = []

    class Rota:
        request = SimpleNamespace(method=metodo, url="https://api.gestao.solar/api/v1/auth/renovar")

        async def abort(self):
            feito.append("recusou")

        async def continue_(self):
            feito.append("seguiu")

    await mapa._so_leitura(Rota())
    assert feito == (["seguiu"] if fica else ["recusou"])


class _PW:
    """O Playwright falso: a página que a `foto()` vê, com o que existe nela e os eventos na ordem."""

    def __init__(self, existe=('#mapa-unico[data-pronto="1"]',), legenda=LEGENDA, fechar_preso=False, demora=0.0):
        self.existe, self.legenda, self.fechar_preso, self.demora, self.eventos = set(existe), legenda, fechar_preso, demora, []

    def __call__(self):
        pw = self

        class Loc:
            def __init__(self, sels):
                self.sels = sels

            def or_(self, outro):
                return Loc(self.sels + outro.sels)

            @property
            def first(self):
                return self

            async def wait_for(self, timeout=None):
                await asyncio.sleep(pw.demora)
                if not pw.existe & set(self.sels):
                    raise TimeoutError("nada apareceu")

            async def count(self):
                return int(bool(pw.existe & set(self.sels)))

            async def inner_text(self):
                return pw.legenda if self.sels == ["#mapa-unico-foto > div"] else "Não deu para carregar · 401"

            async def screenshot(self, **k):
                return b"jpeg"

        class Pagina:
            async def goto(self, url, **k):
                pw.eventos.append(("goto", url))

            def locator(self, sel):
                return Loc([sel])

            def get_by_text(self, texto):
                return Loc([f"texto:{texto}"])

            async def wait_for_timeout(self, ms):
                pass

        class Contexto:
            async def add_init_script(self, js):
                pw.eventos.append(("script", js))

            async def route(self, padrao, f):
                pw.eventos.append(("rota", padrao))

            async def new_page(self):
                return Pagina()

        class Navegador:
            async def new_context(self, **k):
                return Contexto()

            async def close(self):
                pw.eventos.append("fechou")
                if pw.fechar_preso:
                    await asyncio.sleep(3600)

        class Chromium:
            async def launch(self):
                pw.eventos.append("abriu")
                return Navegador()

        class Gerente:
            async def __aenter__(self):
                return SimpleNamespace(chromium=Chromium())

            async def __aexit__(self, *a):
                return False

        return Gerente()


@pytest.fixture
def pagina(monkeypatch):
    monkeypatch.setattr(mapa, "_UMA_POR_VEZ", asyncio.Semaphore(1))   # cada teste com a sua trava (o seu laço)

    def montar(**k):
        pw = _PW(**k)
        monkeypatch.setattr(playwright.async_api, "async_playwright", pw)
        return pw
    return montar


async def test_foto_sai_com_a_legenda_que_a_pagina_desenhou(pagina):
    pw = pagina()
    assert await mapa.foto(31, 501, {"token": "t"}, "U1-3S22") == (b"jpeg", LEGENDA)
    script = next(v for e, v in [x for x in pw.eventos if isinstance(x, tuple)] if e == "script")
    assert "location.origin" in script and ("rota", "**/api/**") in pw.eventos
    assert ("goto", "https://gestao.solar/usinas/31/mapa?destaque=501&print=1") in pw.eventos
    assert pw.eventos[-1] == "fechou"


@pytest.mark.parametrize("cenario,motivo", [
    ({"legenda": "Ouro Fino"}, "em destaque"),                                   # a página não achou o objeto
    ({"legenda": "Ouro Fino · U3-1S22 (String)"}, "em destaque"),                 # achou OUTRO
    ({"existe": ('#mapa-unico[data-voo="falhou"]',)}, "voo"),
    ({"existe": ("texto:Não deu para carregar",)}, "deu erro"),
    ({"existe": ()}, "nada apareceu")])
async def test_foto_nao_sai_sem_o_destaque_o_voo_ou_a_pagina(pagina, cenario, motivo):
    pw = pagina(**cenario)
    with pytest.raises((RuntimeError, TimeoutError), match=motivo):
        await mapa.foto(31, 501, {"token": "t"}, "U1-3S22")
    assert pw.eventos[-1] == "fechou"                              # o Chromium fecha também na falha


async def test_chromium_preso_nao_prende_a_trava(pagina, monkeypatch):
    monkeypatch.setattr(mapa, "FECHAR_S", 0.05)
    pagina(fechar_preso=True)
    await asyncio.wait_for(mapa.foto(31, 501, {"token": "t"}, "U1-3S22"), 2)
    assert not mapa._UMA_POR_VEZ.locked()


async def test_uma_foto_por_vez(pagina):
    pw = pagina(demora=0.02)
    await asyncio.gather(mapa.foto(31, 501, {}, "U1-3S22"), mapa.foto(31, 501, {}, "U1-3S22"))
    abre_fecha = [e for e in pw.eventos if e in ("abriu", "fechou")]
    assert abre_fecha == ["abriu", "fechou", "abriu", "fechou"]   # a segunda só abre depois de a primeira fechar


# ── quem recebe e com que sessão
def _conta(db, **bot):
    emp = db.query(Empresa).filter_by(nome="O&M do mapa").one_or_none() or Empresa(nome="O&M do mapa")
    db.add(emp)
    db.commit()
    n = db.query(User).count() + 1
    u = User(apelido=f"mapa{n}", nome="Ana", perfil=Perfil.GESTOR_EMPRESA, telefone=f"+551799730{n:04d}",
             empresa_id=emp.id, **bot)
    db.add(u)
    db.commit()
    for produto in ("meuplano", "meuwatt"):
        if bot.get(f"bot_{produto}"):
            db.add(VinculoProduto(gs_user_id=u.id, produto=produto, usuario_remoto_id="9", token_cifrado="x"))
    db.commit()
    db.refresh(u)
    return u


def test_a_sessao_da_foto_dura_5_minutos_e_abre_o_portal(db):
    u = _conta(db)
    s = mapa._sessao(SimpleNamespace(db=db, user=u))
    assert s["usuario"]["id"] == u.id
    assert datetime.fromisoformat(s["expira_em"]) - datetime.now(UTC) <= timedelta(minutes=5)
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=s["token"])
    assert security.usuario_atual(cred, db).id == u.id            # a guarda do portal aceita
    assert security.criar_token(u.id, minutos=0)[1] <= datetime.now(UTC)   # 0 é zero, não os 30 dias


def test_so_quem_tem_os_dois_tokens_recebe_a_ferramenta(db):
    assert "mapa_equipamento" not in assistente.permitidas(_conta(db, bot_meuplano=True))
    assert "mapa_equipamento" in assistente.permitidas(_conta(db, bot_meuplano=True, bot_meuwatt=True))


# ── a ferramenta inteira (a `foto()` substituída)
@pytest.fixture
def fontes(db, monkeypatch):
    link = SimpleNamespace(id=31, nome="Ouro Fino", mp_usina_id=451)
    monkeypatch.setattr(api_mapa, "usinas_do_mapa", lambda db, user: [link])
    f = SimpleNamespace(mapa={"slug": "of", "vinculado": True, "objetos": OBJETOS}, estado=None, estado_erro=404,
                        enviar={"ok": True}, enviados=[], fotos=[], foto_erro=None, previa={"achados": []})

    class MP:
        async def mapa_da_usina(self, usina_id):
            assert usina_id == 451
            if f.mapa is None:
                raise httpx.ConnectError("fora")
            return f.mapa

        async def ponto_no_mapa_previa(self, usina_id, nome):
            return f.previa

    class MW:
        async def mapa_estado(self, slug):
            if f.estado is None:
                raise httpx.HTTPStatusError(str(f.estado_erro), request=httpx.Request("GET", "x"),
                                            response=httpx.Response(f.estado_erro))
            return f.estado

    def proprio(cliente):
        def fabrica(db, uid, so_proprio=False):
            assert so_proprio, "o bot lê com o token DELA"
            return cliente()
        return fabrica

    monkeypatch.setattr(vinculos, "cliente_meuplano", proprio(MP))
    monkeypatch.setattr(vinculos, "cliente_meuwatt", proprio(MW))

    async def enviar(**k):
        f.enviados.append(k)
        if isinstance(f.enviar, Exception):
            raise f.enviar
        return f.enviar

    async def foto(usina_id, objeto_id, sessao, esperado):
        f.fotos.append((usina_id, objeto_id, sorted(sessao), esperado))
        if f.foto_erro:
            raise f.foto_erro
        return b"\xff\xd8jpeg", LEGENDA

    monkeypatch.setattr(mapa.whatsapp, "enviar_conteudo", enviar)
    monkeypatch.setattr(mapa, "foto", foto)
    f.ctx = ger.Contexto(db=db, user=_conta(db), telefone="+5517997300001")
    return f


async def _pedir(f, equipamento="U1-3S22"):
    return await mapa.mapa_equipamento(f.ctx, {"usina": "ouro fino", "equipamento": equipamento})


async def test_a_foto_vai_com_a_legenda_da_pagina_o_equipamento_e_a_posicao_no_pe(fontes):
    fontes.estado = {"dados_de": RECENTE, "objetos": [{"objeto_id": 501, "estado": "alarme", "leitura_em": RECENTE,
                                                       "motivo": "String sem corrente no dia.",
                                                       "equipamento": "Inv 13 · string 26 (6S26)"}]}
    out = await _pedir(fontes)
    assert fontes.fotos == [(31, 501, ["expira_em", "token", "usuario"], "U1-3S22")]
    assert out["enviado_no_chat"] and fontes.enviados[0]["tipo"] == "image"
    assert fontes.enviados[0]["texto"] == f"🗺️ {LEGENDA} · Inv 13 · string 26 (6S26)"
    assert out["situacao"].startswith("Em alarme: String sem corrente no dia. (dado de ")
    assert "maps.google.com/?q=-22.295000,-46.365000" in fontes.ctx.rodape[0] and "waze.com" in fontes.ctx.rodape[0]
    assert "-22.29" not in str({k: v for k, v in out.items() if k != "posicao"})   # a IA não recebe os números


async def test_sem_estado_a_ia_ouve_por_que(fontes):
    out = await _pedir(fontes)                                         # a rota do estado ainda não existe (404)
    assert out["situacao"] == "sem cor: o estado dos equipamentos ainda não está disponível"
    fontes.estado = {"dados_de": RECENTE, "objetos": []}                # existe, mas o objeto não está ligado
    out = await _pedir(fontes)
    assert out["situacao"] == "sem cor: este equipamento ainda não está ligado ao monitoramento"


async def test_mapa_que_nao_foi_lido_nunca_vira_vazio(fontes):
    fontes.mapa = {"slug": "of", "vinculado": True, "objetos": [], "aviso": "O meuWatt recusou o token."}
    assert (await _pedir(fontes))["erro"] == "O mapa de Ouro Fino do GS não pôde ser lido agora: O meuWatt recusou o token."
    fontes.mapa = {"vinculado": False, "objetos": []}
    assert "não está ligado ao monitoramento" in (await _pedir(fontes))["erro"]
    fontes.mapa = None
    assert (await _pedir(fontes))["erro"] == "O mapa de Ouro Fino do GS não pôde ser lido agora."
    assert fontes.fotos == []


async def test_sem_a_foto_a_posicao_sai_assim_mesmo(fontes):
    fontes.foto_erro = TimeoutError("o fundo não carregou")
    out = await _pedir(fontes)
    assert out["erro"] == "A foto do mapa não saiu agora; os links vão ao pé da sua resposta."
    assert fontes.enviados == [] and "Google Maps" in fontes.ctx.rodape[0]


async def test_com_outra_foto_saindo_diz_que_foi_a_fila(fontes, monkeypatch):
    monkeypatch.setattr(mapa, "_UMA_POR_VEZ", asyncio.Semaphore(1))
    fontes.foto_erro = TimeoutError("esperou a vez")
    await mapa._UMA_POR_VEZ.acquire()
    try:
        out = await _pedir(fontes)
    finally:
        mapa._UMA_POR_VEZ.release()
    assert "outra foto do mapa estava saindo" in out["erro"]


@pytest.mark.parametrize("resposta", [{"ok": False}, None, RuntimeError("gateway fora")])
async def test_whatsapp_que_nao_recebe_nao_vira_enviado(fontes, resposta):
    fontes.enviar = resposta
    out = await _pedir(fontes)
    assert out["enviado_no_chat"] is False and out["erro"].startswith("O WhatsApp não recebeu a foto")
    assert out["equipamento"] == "U1-3S22" and fontes.ctx.enviados == []


async def test_senha_provisoria_diz_o_motivo_sem_tentar_a_foto(fontes):
    fontes.ctx.user.trocar_senha = True
    out = await _pedir(fontes)
    assert "senha provisória" in out["erro"] and fontes.fotos == [] and "Google Maps" in fontes.ctx.rodape[0]


async def test_desenho_sem_posicao_nao_tira_foto_nem_promete_link(fontes):
    out = await _pedir(fontes, "Poste")
    assert out["erro"] == "O desenho de Poste não tem posição legível no mapa: sem foto e sem link."
    assert fontes.fotos == [] and fontes.ctx.rodape == []


async def test_o_apelido_do_meuplano_acha_o_objeto(fontes):
    fontes.previa = {"achados": [{"node_id": 70, "nome": "Câmera da entrada"}]}
    await _pedir(fontes, "a câmera da entrada")
    assert [(x[1], x[3]) for x in fontes.fotos] == [(7, "Câmera 01")]   # a legenda conferida pelo nome do nó


async def test_ambiguo_ou_ausente_pergunta_com_os_nomes(fontes):
    out = await _pedir(fontes, "câmera 9")
    assert "não está no mapa de Ouro Fino" in out["erro"] and out["opcoes"] == ["Câmera 01"]
    fontes.mapa = {"slug": "of", "vinculado": True, "objetos": OBJETOS + [{"id": 600, "nome": "U1-3S22",
                                                                           "geometria": FAIXA}]}
    out = await _pedir(fontes)
    assert "é ambíguo" in out["erro"] and out["opcoes"] == ["U1-3S22"] and fontes.fotos == []


# ── R13 do Plano Casa GS (24/11/2026): "Primeiro o bot consulta no GS, senão tiver, consulta no termovision, se tiver em
#    ambos, o GS é quem vale"
@pytest.fixture
def tv_fake(fontes, monkeypatch):
    from app.services import assistente_termovision as tv
    fontes.ctx.user.termovision_liberado = True
    fontes.ctx.db.commit()
    chamadas, resposta = [], {"valor": None}

    async def localizar(db, user, usina, alvo):
        chamadas.append((usina, alvo))
        return resposta["valor"]
    monkeypatch.setattr(tv, "localizar", localizar)
    return SimpleNamespace(chamadas=chamadas, resposta=resposta)


ACHADO = {"tipo": "mesa", "rotulo": "Mesa 12", "centro": {"lat": -22.27, "lng": -46.36}, "raio_m": 8, "fileira": "F3",
          "link": "https://app.termovision.tech/app.html?usina=of2&foco=-22.27,-46.36&r=8&rotulo=Mesa%2012&tipo=mesa"}


async def test_no_gs_vale_o_gs_e_o_termovision_nem_e_chamado(fontes, tv_fake):
    out = await _pedir(fontes)                                   # a U1-3S22 está no mapa do GS
    assert out["equipamento"] == "U1-3S22" and tv_fake.chamadas == []


async def test_sem_no_gs_acha_no_termovision_com_o_link_que_abre_nele(fontes, tv_fake):
    tv_fake.resposta["valor"] = {"nome": "UFV Ouro Fino 2", "achados": [ACHADO], "total": 1, "sugestoes": []}
    out = await _pedir(fontes, "mesa 12")
    assert tv_fake.chamadas == [("Ouro Fino", "mesa 12")]           # sem o vínculo do mapa, pelo nome da usina
    assert out["equipamento"] == "Mesa 12" and out["usina"] == "UFV Ouro Fino 2" and out["fileira"] == "F3"
    assert "TermoVision" in out["de_onde"] and fontes.fotos == []   # sem foto: a foto é do mapa do GS
    pe = fontes.ctx.rodape[-1]
    assert ACHADO["link"] in pe and "maps.google" in pe.lower() or "google.com/maps" in pe
    assert "waze" in pe.lower()


async def test_nem_no_gs_nem_no_termovision_pergunta_com_os_parecidos_dos_dois(fontes, tv_fake):
    tv_fake.resposta["valor"] = {"nome": "UFV Ouro Fino 2", "achados": [], "total": 0, "sugestoes": ["Mesa 21"]}
    out = await _pedir(fontes, "câmera 9")
    assert "também não está no mapa do TermoVision" in out["erro"] and out["opcoes"] == ["Câmera 01", "Mesa 21"]
    tv_fake.resposta["valor"] = {"nome": "UFV Ouro Fino 2", "total": 2, "sugestoes": [],
                                 "achados": [ACHADO, {**ACHADO, "rotulo": "Mesa 12B"}]}
    out = await _pedir(fontes, "mesa 12")
    assert "ambíguo no mapa do TermoVision" in out["erro"] and out["opcoes"] == ["Mesa 12", "Mesa 12B"]
    tv_fake.resposta["valor"] = {"erro": "o TermoVision não respondeu agora"}
    out = await _pedir(fontes, "mesa 12")
    assert "E no TermoVision: o TermoVision não respondeu agora" in out["erro"]


async def test_usina_que_so_existe_no_termovision_e_mapa_do_gs_fora(fontes, tv_fake):
    tv_fake.resposta["valor"] = {"nome": "Arealva", "achados": [{**ACHADO, "rotulo": "U2-1S05", "tipo": "string"}],
                                 "total": 1}
    out = await mapa.mapa_equipamento(fontes.ctx, {"usina": "Arealva", "equipamento": "U2-1S05"})
    assert tv_fake.chamadas[-1] == ("Arealva", "U2-1S05") and out["usina"] == "Arealva"
    assert "não está no GS" in out["de_onde"]
    fontes.mapa = None                                          # o mapa do GS não responde: vai ao TermoVision, e diz
    out = await _pedir(fontes, "mesa 12")
    assert "não pôde ser lido" in out["de_onde"]


async def test_quem_nao_tem_o_termovision_fica_so_com_o_gs(fontes, tv_fake):
    fontes.ctx.user.termovision_liberado = False
    fontes.ctx.db.commit()
    out = await _pedir(fontes, "mesa 12")
    assert tv_fake.chamadas == [] and "não está no mapa de Ouro Fino do GS" in out["erro"]



async def test_sem_o_token_da_manutencao_vai_ao_termovision(fontes, tv_fake, monkeypatch):
    def sem(db, uid, so_proprio=False):
        raise vinculos.SemConexao("o token desta pessoa sumiu")
    monkeypatch.setattr(vinculos, "cliente_meuplano", sem)
    tv_fake.resposta["valor"] = {"nome": "UFV Ouro Fino 2", "achados": [ACHADO], "total": 1}
    out = await _pedir(fontes, "mesa 12")
    assert tv_fake.chamadas == [("Ouro Fino", "mesa 12")] and out["equipamento"] == "Mesa 12"
    assert "não abriu para esta conta" in out["de_onde"]
