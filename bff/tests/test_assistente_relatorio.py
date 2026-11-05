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
