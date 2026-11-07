"""Bot: o RELATÓRIO da OS em PDF (pedido do Renan, 04/11/2026: "se tiver, enviar o relatório salvo; se não tiver, ele
gera e envia; se tiver, ele pede o que quer"). O meuPlano é falso aqui: o que se prova é a decisão do bot — perguntar
quando há salvo, gerar quando não há, mandar o que a pessoa escolheu — e que o arquivo sai como DOCUMENTO."""

from types import SimpleNamespace

import httpx
import pytest

from app.services import assistente_fotos as fotos
from app.services import assistente_geracao as ger
from app.services import assistente_relatorio as rel


def _erro(st: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://meuplano.test/x")
    return httpx.HTTPStatusError(str(st), request=req, response=httpx.Response(st, request=req))


class MP:
    """O meuPlano de mentira: os relatórios salvos da OS, o job da IA e o que foi pedido."""

    def __init__(self, salvos=(), estados=("rodando", "pronto"), falha=None, falha_gerar=None):
        self.salvos, self.estados, self.falha, self.falha_gerar = list(salvos), list(estados), falha, falha_gerar
        self.pedidos = []

    async def relatorios_da_os(self, os_id):
        self.pedidos.append(("lista", os_id))
        if self.falha:
            raise _erro(self.falha)
        return self.salvos

    async def relatorio_pdf(self, rid):
        self.pedidos.append(("pdf", rid))
        return f"%PDF-{rid}".encode()

    async def relatorio_ia(self, os_id, instrucao):
        self.pedidos.append(("gerar", os_id, instrucao))
        if self.falha_gerar:
            raise _erro(self.falha_gerar)
        return "job1"

    async def relatorio_ia_estado(self, job):
        st = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
        return {"status": st, "etapa": "escrevendo", "doc_id": 71 if st == "pronto" else None,
                "erro": "a IA caiu" if st == "erro" else None}

    async def fatos_da_os(self, os_id):
        self.pedidos.append(("lista_fatos", os_id))
        if self.falha:
            raise _erro(self.falha)
        return []

    async def criar_fato(self, os_id, texto):
        self.pedidos.append(("fato_texto", os_id, texto))
        return {"id": 600}

    async def criar_fato_arquivo(self, os_id, nome, conteudo, tipo, texto):
        self.pedidos.append(("fato", os_id, nome, conteudo, texto))
        return {"id": 500 + len(self.pedidos)}

    async def publicar_relatorio(self, doc_id):
        self.pedidos.append(("publicar", doc_id))
        return {"id": 99, "titulo": "Relatório técnico — OS #1878"}

    async def link_publico_relatorio(self, rid):
        self.pedidos.append(("link", rid))
        return {"url": f"https://app.meuplano.solar/publico/compartilhamento/tok{rid}"}


SALVOS = [{"id": 7, "titulo": "Relatório para a diretoria", "atualizado_em": "2026-11-04T17:20:00", "criado_por": "Renan"},
          {"id": 5, "titulo": "Relatório técnico — OS #1878", "atualizado_em": "2026-11-03T12:00:00", "criado_por": "Renan"}]


@pytest.fixture
def chat(monkeypatch):
    enviados = []

    async def enviar(**kw):
        enviados.append(kw)
        return {"ok": True}

    monkeypatch.setattr("app.clients.whatsapp.enviar_conteudo", enviar)
    monkeypatch.setattr(rel, "ESPERA_S", 0)
    return enviados


def _ctx():
    return ger.Contexto(db=SimpleNamespace(commit=lambda: None), user=SimpleNamespace(id=1), telefone="+5516999998888")


async def _rodar(monkeypatch, mp, **a):
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    ctx = _ctx()
    return await rel.relatorio_da_os(ctx, {"os": 1878, **a}), ctx


async def test_com_salvo_pergunta_e_nao_manda_nada(monkeypatch, chat):
    mp = MP(SALVOS)
    r, ctx = await _rodar(monkeypatch, mp)
    assert [x["id"] for x in r["relatorios_salvos"]] == [7, 5] and "PERGUNTE" in r["nota"]
    assert r["relatorios_salvos"][0]["de"] != "—"                  # a data de lá (UTC sem fuso) chega legível
    assert chat == [] and ctx.enviados == [] and mp.pedidos == [("lista", 1878)]   # nem manda nem gera


async def test_sem_salvo_gera_e_manda(monkeypatch, chat):
    mp = MP([], estados=("rodando", "rodando", "pronto"))
    r, ctx = await _rodar(monkeypatch, mp, instrucao="curto, para a diretoria")
    assert ("gerar", 1878, "curto, para a diretoria") in mp.pedidos and ("publicar", 71) in mp.pedidos
    assert r["relatorio"] == "novo" and r["enviado_no_chat"] and "aba Relatórios" in r["salvo_na_os"]
    assert chat[0]["tipo"] == "document" and chat[0]["mime"] == "application/pdf" and chat[0]["arquivo"] == b"%PDF-99"
    assert "/" not in chat[0]["filename"] and chat[0]["filename"].endswith(".pdf") and ctx.enviados == [chat[0]["filename"]]


async def test_salvo_manda_o_escolhido_ou_o_mais_recente(monkeypatch, chat):
    r, _ = await _rodar(monkeypatch, MP(SALVOS), escolha="salvo", relatorio_id="5")
    assert r["relatorio"] == "salvo" and chat[-1]["arquivo"] == b"%PDF-5"
    r, _ = await _rodar(monkeypatch, MP(SALVOS), escolha="salvo")
    assert chat[-1]["arquivo"] == b"%PDF-7" and r["titulo"] == "Relatório para a diretoria"


async def test_novo_gera_mesmo_com_salvo(monkeypatch, chat):
    mp = MP(SALVOS)
    r, _ = await _rodar(monkeypatch, mp, escolha="novo")
    assert r["relatorio"] == "novo" and ("gerar", 1878, "") in mp.pedidos and chat[-1]["arquivo"] == b"%PDF-99"


async def test_salvo_sem_salvo_nao_inventa(monkeypatch, chat):
    mp = MP([])
    r, _ = await _rodar(monkeypatch, mp, escolha="salvo")
    assert "não tem relatório salvo" in r["erro"] and chat == [] and all(p[0] == "lista" for p in mp.pedidos)


@pytest.mark.parametrize("st,trecho", [(404, "não está no alcance"), (403, "papel desta pessoa")])
async def test_recusa_do_meuplano_chega_dita(monkeypatch, chat, st, trecho):
    r, _ = await _rodar(monkeypatch, MP(falha=st))
    assert trecho in r["erro"] and chat == []


async def test_sem_permissao_de_gerar(monkeypatch, chat):
    r, _ = await _rodar(monkeypatch, MP([], falha_gerar=403))
    assert "gera relatório de OS" in r["erro"] and chat == []


async def test_ia_que_falha_ou_demora(monkeypatch, chat):
    r, _ = await _rodar(monkeypatch, MP([], estados=("rodando", "erro")))
    assert "a IA caiu" in r["erro"] and chat == []
    monkeypatch.setattr(rel, "PRAZO_GERAR_S", -1)
    r, _ = await _rodar(monkeypatch, MP([], estados=("rodando",)))
    assert "não ficou pronto" in r["erro"] and chat == []


def test_o_bot_conhece_a_ferramenta_e_so_quem_tem_o_meuplano_a_recebe():
    from app.services import assistente

    com = SimpleNamespace(bot_ativo={"bot_meuplano"}, perfil=None)
    sem = SimpleNamespace(bot_ativo={"bot_meuwatt"}, perfil=None)
    for nome in ("relatorio_da_os", "informacoes_do_relatorio"):
        assert nome in assistente.FERRAMENTAS
        assert nome in assistente.permitidas(com) and nome not in assistente.permitidas(sem)


async def test_prompt_e_imagens_de_apoio_viram_fatos_e_relatorio_novo(monkeypatch, chat):
    """ "gere o relatório da OS com o prompt xxx, segue imagens de apoio": é AÇÃO (as fotos entram na OS) — espera o Sim;
    depois dele as fotos vão às informações do relatório (com a legenda), saem da espera, e o relatório é NOVO, gerado
    com elas, mesmo com um salvo na OS."""
    async def baixar(mid):
        return f"jpeg-{mid}".encode(), "image/jpeg"

    monkeypatch.setattr("app.clients.whatsapp.baixar_midia", baixar)
    tel = "+5516999998888"
    monkeypatch.setitem(fotos._RECEBIDAS, tel, [{"id": 11, "legenda": "oscilografia", "em": fotos.monotonic()},
                                                {"id": 12, "legenda": "", "em": fotos.monotonic()}])
    capt = _captura_propor(monkeypatch)
    mp = MP(SALVOS)
    r, ctx = await _rodar(monkeypatch, mp, instrucao="foco na falta entre B e C", fotos_de_apoio=True)
    assert "OS #1878" in r["proposta_pendente"] and "2 foto(s)" in capt["resumo"] and capt["k"]["confirmacao"] == "sim"
    assert "foco na falta entre B e C" in capt["resumo"]
    assert mp.pedidos == [("lista", 1878)] and chat == [] and len(fotos.recebidas(tel)) == 2   # nada antes do Sim
    msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1), tel)
    fatos_criados = [p for p in mp.pedidos if p[0] == "fato"]
    assert [(p[1], p[3], p[4]) for p in fatos_criados] == [(1878, b"jpeg-11", "oscilografia"),
                                                           (1878, b"jpeg-12", "Imagem enviada pelo WhatsApp")]
    assert fotos.recebidas(tel) == [] and ("gerar", 1878, "foco na falta entre B e C") in mp.pedidos
    # as fotos entram ANTES de gerar (a IA de lá as vê), e o PDF chega como documento
    assert mp.pedidos.index(fatos_criados[-1]) < mp.pedidos.index(("gerar", 1878, "foco na falta entre B e C"))
    assert msg.startswith("✅ 2 foto(s) entraram") and chat[-1]["tipo"] == "document" and chat[-1]["arquivo"] == b"%PDF-99"


async def test_fotos_que_entraram_e_relatorio_que_falhou_sao_ditos(monkeypatch, chat):
    """Gerar falha DEPOIS de as fotos entrarem: o bot diz que elas entraram — nunca "nada foi feito" (revisão
    adversarial, 05/11/2026). E sem nenhuma foto dentro, não gera um relatório sem as evidências pedidas."""
    from app.clients import whatsapp

    async def baixar(mid):
        if mid == 99:
            raise whatsapp.GatewayIndisponivel("fora")
        return b"jpeg", "image/jpeg"

    monkeypatch.setattr("app.clients.whatsapp.baixar_midia", baixar)
    tel = "+5516999998888"
    for falha, trecho in ((403, "papel desta pessoa"), (None, "a IA caiu")):
        monkeypatch.setitem(fotos._RECEBIDAS, tel, [{"id": 31, "legenda": "", "em": fotos.monotonic()}])
        capt = _captura_propor(monkeypatch)
        mp = MP([], falha_gerar=falha, estados=("rodando", "erro"))
        await _rodar(monkeypatch, mp, fotos_de_apoio=True)
        msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1), tel)
        assert msg.startswith("⚠️ 1 foto(s) entraram") and trecho in msg and "Nada foi feito" not in msg and chat == []
    monkeypatch.setitem(fotos._RECEBIDAS, tel, [{"id": 99, "legenda": "", "em": fotos.monotonic()}])
    capt = _captura_propor(monkeypatch)
    mp = MP([])
    await _rodar(monkeypatch, mp, fotos_de_apoio=True)
    msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1), tel)
    assert msg.startswith("❌ Nenhuma foto entrou") and not [p for p in mp.pedidos if p[0] == "gerar"]


async def test_sem_pedir_as_fotos_elas_ficam_esperando(monkeypatch, chat):
    tel = "+5516999998888"
    monkeypatch.setitem(fotos._RECEBIDAS, tel, [{"id": 21, "legenda": "", "em": fotos.monotonic()}])
    mp = MP([])
    await _rodar(monkeypatch, mp, escolha="novo")
    assert not [p for p in mp.pedidos if p[0] == "fato"] and len(fotos.recebidas(tel)) == 1


async def test_auto_com_prompt_nao_pergunta_qual(monkeypatch, chat):
    mp = MP(SALVOS)
    r, _ = await _rodar(monkeypatch, mp, instrucao="para a diretoria")
    assert r["relatorio"] == "novo" and "relatorios_salvos" not in r


# ------------------------------------------------- as INFORMAÇÕES DO RELATÓRIO pelo bot, sem gerar (com o Sim)
def _captura_propor(monkeypatch):
    capt = {}

    def propor(ctx, resumo, prazo, executar, detalhes=(), **k):
        capt.update(resumo=resumo, executar=executar, k=k)
        return {"proposta_pendente": resumo}
    monkeypatch.setattr("app.services.assistente_helper.propor", propor)
    return capt


async def test_informacoes_texto_e_fotos_so_depois_do_sim(monkeypatch, chat):
    async def baixar(mid):
        return f"jpeg-{mid}".encode(), "image/jpeg"

    monkeypatch.setattr("app.clients.whatsapp.baixar_midia", baixar)
    tel = "+5516999998888"
    monkeypatch.setitem(fotos._RECEBIDAS, tel, [{"id": 31, "legenda": "trip no relé", "em": fotos.monotonic()}])
    capt = _captura_propor(monkeypatch)
    mp = MP([])
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.informacoes_do_relatorio(_ctx(), {"os": 1878, "texto": "o relé marcou 12 kA na fase B", "fotos": True})
    assert "OS #1878" in r["proposta_pendente"] and "1 foto" in capt["resumo"] and capt["k"]["confirmacao"] == "sim"
    assert not [p for p in mp.pedidos if p[0] in ("fato", "fato_texto")]          # nada grava antes do Sim
    msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1), tel)
    assert msg.startswith("✅") and "Informações do relatório da OS #1878" in msg
    assert ("fato_texto", 1878, "o relé marcou 12 kA na fase B") in mp.pedidos
    assert [(p[3], p[4]) for p in mp.pedidos if p[0] == "fato"] == [(b"jpeg-31", "trip no relé")] and fotos.recebidas(tel) == []


async def test_informacoes_sem_nada_ou_os_fora_do_alcance(monkeypatch, chat):
    capt = _captura_propor(monkeypatch)
    monkeypatch.setitem(fotos._RECEBIDAS, "+5516999998888", [])
    r = await rel.informacoes_do_relatorio(_ctx(), {"os": 1878, "fotos": True})
    assert "Não há o que registrar" in r["erro"] and not capt
    mp = MP(falha=404)
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.informacoes_do_relatorio(_ctx(), {"os": 1878, "texto": "x"})
    assert "não está no alcance" in r["erro"] and not capt


async def test_foto_que_nao_entra_diz_o_porque_sem_jargao(monkeypatch, chat):
    """Uma foto que não baixa e outra cujo envio demora não derrubam a terceira; o porquê vai na língua de quem lê, e a
    que pode ter entrado é dita (senão a pessoa manda de novo e ela fica duas vezes)."""
    from app.clients import whatsapp

    async def baixar(mid):
        if mid == 41:
            raise whatsapp.GatewayIndisponivel("fora")
        return f"jpeg-{mid}".encode(), "image/jpeg"

    class MPLento(MP):
        async def criar_fato_arquivo(self, os_id, nome, conteudo, tipo, texto):
            if conteudo == b"jpeg-42":
                raise httpx.ReadTimeout("demorou")
            return await super().criar_fato_arquivo(os_id, nome, conteudo, tipo, texto)

    monkeypatch.setattr("app.clients.whatsapp.baixar_midia", baixar)
    tel = "+5516999998888"
    monkeypatch.setitem(fotos._RECEBIDAS, tel, [{"id": i, "legenda": "", "em": fotos.monotonic()} for i in (41, 42, 43)])
    capt = _captura_propor(monkeypatch)
    mp = MPLento([])
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    await rel.informacoes_do_relatorio(_ctx(), {"os": 1878, "fotos": True})
    msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1), tel)
    assert msg.startswith("⚠️ Registrei 1 foto(s)") and "não consegui baixar do WhatsApp" in msg
    assert "pode ter entrado: confira" in msg and "Error" not in msg and "Timeout" not in msg
    assert [f["id"] for f in fotos.recebidas(tel)] == [41, 42]                    # só a que entrou sai da espera


# --------------------------------------------------------------------------- usina SEM CADASTRO (dono, 07/11/2026)
PASTA = "https://drive.google.com/drive/folders/17K3-tzuAWzmtWXUBK1M2r_2DwT5GvISY"


class MPDrive(MP):
    """O meuPlano de mentira da usina sem cadastro: a prévia da pasta, as usinas, o funil, o Word da OS."""

    def __init__(self, documentos=("medicoes.xlsx",), usinas=None, docs_word=None, **k):
        super().__init__([], **k)
        self.documentos, self.docs_word = list(documentos), docs_word
        self.lista_usinas = usinas if usinas is not None else [{"id": 5, "name": "UFV Ouro Fino"},
                                                               {"id": 3001, "name": "Usinas sem cadastro"}]

    async def drive_previa(self, link):
        self.pedidos.append(("previa", link))
        return {"pasta": "UFV_Ouro_Fino_2", "fotos": 54, "videos": 5, "outros": 0, "documentos": self.documentos}

    async def usinas(self):
        return self.lista_usinas

    async def ordens_servico(self, usina_id, status=None):
        self.pedidos.append(("ordens", usina_id))
        return getattr(self, "ordens", [])

    async def funil_de_servicos_adicionais(self):
        return {"id": 50}

    async def criar_container(self, pid, dados):
        self.pedidos.append(("container", pid, dados))
        return {"id": 2300}

    async def criar_os(self, dados):
        self.pedidos.append(("os", dados))
        return {"id": 1900}

    async def relatorio_ia(self, os_id, instrucao, drive=None):
        self.pedidos.append(("gerar", os_id, instrucao, drive))
        return "job1"

    async def relatorio_ia_estado(self, job):
        e = await super().relatorio_ia_estado(job)
        return {**e, "link": "https://app.meuplano.solar/word/71" if e["status"] == "pronto" else None,
                "resposta": "Tirei a foto do marimbondo." if e["status"] == "pronto" else None}

    async def documentos_word_da_os(self, os_id):
        self.pedidos.append(("words", os_id))
        return self.docs_word or []

    async def alterar_relatorio(self, doc_id, pedido):
        self.pedidos.append(("alterar", doc_id, pedido))
        return "job2"


def _ctx_drive(pedido, historico=()):
    c = _ctx()
    c.pedido, c.historico = pedido, list(historico)
    c.user.nome = "Renan"
    return c


async def test_sem_cadastro_pede_o_contexto_quando_a_pasta_nao_traz_documento(monkeypatch, chat):
    capt = _captura_propor(monkeypatch)
    mp = MPDrive(documentos=())
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.relatorio_sem_cadastro(_ctx_drive(f"quero um relatório de usina sem cadastro {PASTA}"), {})
    assert "Falta o CONTEXTO" in r["erro"] and capt == {}
    # com o contexto escrito, ou com documento na pasta, segue para o Sim
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {"contexto": "Ensaio do trafo do SKID 3 para a Eldorado"})
    assert "proposta_pendente" in r
    mp.documentos = ["medicoes.xlsx"]                                            # a pasta traz o contexto
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {})
    assert "proposta_pendente" in r


async def test_sem_cadastro_so_usa_a_pasta_que_a_pessoa_mandou(monkeypatch, chat):
    capt = _captura_propor(monkeypatch)
    mp = MPDrive()
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.relatorio_sem_cadastro(_ctx_drive("faz o relatório de usina sem cadastro"), {"link": PASTA})
    assert "Falta o link da PASTA" in r["erro"] and mp.pedidos == []            # a IA não inventa a pasta
    antes = [{"role": "user", "content": f"as fotos: {PASTA}?usp=sharing"}, {"role": "assistant", "content": "ok"}]
    r = await rel.relatorio_sem_cadastro(_ctx_drive("é de Ouro Fino 2, ensaio do trafo", antes),
                                         {"link": PASTA.replace("17K3", "17K4"), "contexto": "ensaio do trafo"})
    assert ("previa", PASTA) in mp.pedidos and "proposta_pendente" in r


async def test_sem_cadastro_propoe_e_so_cria_depois_do_sim(monkeypatch, chat):
    capt = _captura_propor(monkeypatch)
    mp = MPDrive()
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {"servico": "ensaio do trafo do SKID 3",
                                                             "contexto": "Cliente Eldorado; trafo de 500 kVA"})
    resumo = capt["resumo"]
    assert "proposta_pendente" in r and capt["k"]["confirmacao"] == "sim"
    assert "«Usinas sem cadastro»" in resumo and "«UFV Ouro Fino 2: ensaio do trafo do SKID 3»" in resumo
    assert "54 foto(s) e 1 documento(s); 5 vídeo(s) ficam só no link" in resumo
    assert [p[0] for p in mp.pedidos] == ["previa", "ordens"]                    # nada criado antes do Sim
    msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1, nome="Renan"), "+55")
    assert msg.startswith("✅") and "OS #1900" in msg and "https://app.meuplano.solar/word/71" in msg
    _, pid, card = next(p for p in mp.pedidos if p[0] == "container")
    assert pid == 50 and card["usina_id"] == 3001 and card["kind"] == "servico_adicional"
    os_ = next(p[1] for p in mp.pedidos if p[0] == "os")
    assert os_["container_id"] == 2300 and os_["plant_id"] == 3001 and PASTA in os_["notes"] and "Eldorado" in os_["notes"]
    assert ("gerar", 1900, "", PASTA) in mp.pedidos


async def test_sem_cadastro_sem_a_usina_guarda_ou_com_o_relatorio_que_falha(monkeypatch, chat):
    capt = _captura_propor(monkeypatch)
    mp = MPDrive(usinas=[{"id": 5, "name": "UFV Ouro Fino"}])
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {})
    assert "Usinas sem cadastro" in r["erro"] and capt == {}
    mp = MPDrive(estados=("rodando", "erro"))
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {})
    msg = await capt["executar"](SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1, nome="Renan"), "+55")
    assert msg.startswith("⚠️ A OS #1900") and "a IA caiu" in msg and "gera o relatório da OS 1900" in msg


WORDS = [{"id": 70, "formato": "docx", "updated_at": "2026-11-07T10:00:00", "versao_atual": 2},
         {"id": 71, "formato": "docx", "updated_at": "2026-11-07T12:30:00", "versao_atual": 5},
         {"id": 72, "formato": "xlsx", "updated_at": "2026-11-07T13:00:00"}]


async def test_alterar_vai_ao_word_mais_recente_e_o_link_sai_pelo_sistema(monkeypatch, chat):
    mp = MPDrive(docs_word=WORDS)
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    ctx = _ctx_drive("tira a foto do marimbondo")
    r = await rel.alterar_relatorio(ctx, {"os": 1900, "pedido": "tira a foto do marimbondo"})
    assert ("alterar", 71, "tira a foto do marimbondo") in mp.pedidos and r["o_que_mudou"] == "Tirei a foto do marimbondo."
    assert ctx.rodape == ["📝 Word: https://app.meuplano.solar/word/71"]
    mp = MPDrive(docs_word=[])
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.alterar_relatorio(_ctx_drive("x"), {"os": 1900, "pedido": "x"})
    assert "não tem relatório em Word" in r["erro"]


async def test_manda_o_pdf_e_o_word_de_agora(monkeypatch, chat):
    mp = MPDrive(docs_word=WORDS)
    r, _ = await _rodar(monkeypatch, mp, escolha="word")
    assert ("publicar", 71) in mp.pedidos and chat[-1]["arquivo"] == b"%PDF-99" and r["versao_do_word"] == 5
    assert not [p for p in mp.pedidos if p[0] == "gerar"]


async def test_o_link_publico_vai_no_lugar_do_arquivo_com_qualquer_escolha(monkeypatch, chat):
    """Dono, 07/11/2026: "quero opção de enviar o relatório com link público"."""
    mp = MPDrive(docs_word=WORDS)
    r, ctx = await _rodar(monkeypatch, mp, escolha="word", link_publico=True)
    assert ("publicar", 71) in mp.pedidos and ("link", 99) in mp.pedidos and not chat and "link_publico" in r
    assert ctx.rodape == ["🔗 Link público: https://app.meuplano.solar/publico/compartilhamento/tok99"]
    assert not [p for p in mp.pedidos if p[0] == "pdf"]
    mp = MP(SALVOS)
    r, ctx = await _rodar(monkeypatch, mp, escolha="salvo", relatorio_id=5, link_publico=True)
    assert ("link", 5) in mp.pedidos and not chat and ctx.rodape[0].endswith("/tok5")


def test_as_ferramentas_novas_sao_de_quem_tem_o_meuplano():
    from app.services import assistente
    com = SimpleNamespace(bot_ativo={"bot_meuplano"}, perfil=None)
    sem = SimpleNamespace(bot_ativo={"bot_meuwatt"}, perfil=None)
    for nome in ("relatorio_sem_cadastro", "alterar_relatorio"):
        assert nome in assistente.permitidas(com) and nome not in assistente.permitidas(sem)


# --------------------------------------------------------------------------- a lista e a REGRA 1 (dono, 07/11/2026)
OS_GUARDA = [{"id": 1995, "name": "UFV Ouro Fino 2: ensaio do transformador", "status": "ABERTA",
              "created_at": "2026-11-07T09:00:00", "notes": f"Contexto.\n\nFotos e vídeos do serviço (Google Drive): {PASTA}"},
             {"id": 1990, "name": "Pereiras: limpeza", "status": "FECHADA", "created_at": "2026-11-05T09:00:00",
              "notes": "sem pasta"}]


class MPGuarda(MPDrive):
    def __init__(self, ordens=(), **k):
        super().__init__(**k)
        self.ordens = list(ordens)


async def test_a_lista_das_os_sem_cadastro_vem_do_meuplano_agora(monkeypatch, chat):
    mp = MPGuarda(OS_GUARDA)
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.os_sem_cadastro(_ctx_drive("lista as OS sem usina"), {})
    assert ("ordens", 3001) in mp.pedidos and r["total"] == 2 and [o["os"] for o in r["os"]] == [1995, 1990]
    assert r["os"][0]["da_pasta_do_drive"] and not r["os"][1]["da_pasta_do_drive"]
    r = await rel.os_sem_cadastro(_ctx_drive("x"), {"busca": "ouro fino"})
    assert [o["os"] for o in r["os"]] == [1995]


async def test_pasta_que_ja_tem_os_o_sistema_avisa_e_nao_propoe(monkeypatch, chat):
    capt = _captura_propor(monkeypatch)
    mp = MPGuarda(OS_GUARDA)
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {"contexto": "ensaio do trafo"})
    assert [o["os"] for o in r["ja_existe"]] == [1995] and capt == {}           # a OS que existe AGORA, não a de memória
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {"contexto": "ensaio do trafo", "nova": True})
    assert "proposta_pendente" in r                                                # ela disse que quer outra
    mp = MPGuarda([OS_GUARDA[1]])                                                  # a OS da pasta foi apagada
    monkeypatch.setattr("app.services.vinculos.cliente_meuplano", lambda db, uid, so_proprio=False: mp)
    r = await rel.relatorio_sem_cadastro(_ctx_drive(PASTA), {"contexto": "ensaio do trafo"})
    assert "proposta_pendente" in r


def test_regra_1_resposta_que_cita_registro_sem_consultar():
    from app.services.assistente import de_memoria
    assert de_memoria("Esse relatório já existe: é a OS #1996.", "https://drive… Ouro fino 2")
    assert de_memoria("A OS 1995 é a de Ouro Fino?", "o de ouro fino")
    assert not de_memoria("Fecho a OS 1638?", "fecha a 1638")                     # o número que a pessoa escreveu
    assert not de_memoria("De qual usina é a localização?", "📍")


async def test_regra_1_a_resposta_de_memoria_nao_sai_a_ia_consulta_antes(monkeypatch, chat):
    from app.services import assistente
    vistos = []

    async def _llm(msgs, ferramentas=None, obrigatoria=False):
        vistos.append(obrigatoria)
        if len(vistos) == 1:
            return {"content": "Esse relatório já existe: é a OS #1996."}         # de memória
        if len(vistos) == 2:
            assert msgs[-1]["content"].startswith("[sistema] REGRA 1")
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "os_sem_cadastro", "arguments": "{}"}}]}
        return {"content": "Achei a OS 1995 desta pasta."}

    async def _lista(ctx, a):
        return {"total": 1, "os": [{"os": 1995}]}

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(assistente, "_sistema", lambda ctx: "")
    monkeypatch.setitem(assistente.FERRAMENTAS, "os_sem_cadastro", (_lista, rel.FERRAMENTA_LISTA))
    ctx = _ctx_drive(PASTA)
    ctx.user.bot_ativo, ctx.user.perfil, ctx.ferramentas = {"bot_meuplano"}, None, []
    r = await assistente.responder(ctx, [{"role": "user", "content": PASTA}])
    assert r == "Achei a OS 1995 desta pasta." and vistos == [False, True, False] and ctx.ferramentas == ["os_sem_cadastro"]
