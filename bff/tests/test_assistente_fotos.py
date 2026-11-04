"""Fotos do WhatsApp anexadas numa tarefa do meuPlano. Pedido do Renan (26/10/2026): "Quero poder enviar uma ou mais
fotos para qualquer tarefa em aberto para técnico, ou até mesmo em análise e/ou concluída para gestores". Antes o bot
respondia "por aqui eu não recebo anexos".
"""

import asyncio
import json
import re
from types import SimpleNamespace

import httpx
import pytest

from app.models.conversa_whatsapp import RegistroBot
from app.models.user import Perfil
from app.services import assistente
from app.services import assistente_fotos as fotos
from app.services import assistente_geracao as ger
from app.services import assistente_helper as h
from app.services import vinculos
from tests.test_assistente_whatsapp import _conta, bot_local  # noqa: F401 (bot_local é fixture)


@pytest.mark.parametrize("status,tecnico,gestor", [
    ("PREVISTA", True, True), ("PLANEJADA", True, True), ("PROGRAMADA", True, True), ("EM_ANDAMENTO", True, True),
    ("REALIZADA", False, True), ("APROVADA", False, True), ("CANCELADA", False, False), (None, False, False)])
def test_o_tecnico_anexa_na_tarefa_em_aberto_e_o_gestor_tambem_em_analise_e_concluida(status, tecnico, gestor):
    assert (fotos.recusa(SimpleNamespace(perfil=Perfil.TECNICO), status) is None) is tecnico
    assert (fotos.recusa(SimpleNamespace(perfil=Perfil.GESTOR_EMPRESA), status) is None) is gestor


def _erro(codigo, detalhe=""):
    req = httpx.Request("POST", "http://meuplano")
    return httpx.HTTPStatusError(str(codigo), request=req, response=httpx.Response(codigo, json={"detail": detalhe},
                                                                                   request=req))


class _MeuPlano:
    def __init__(self):
        self.tarefas = {t["id"]: t for t in (
            {"id": 9331, "name": "Roçagem embaixo dos módulos", "status": "EM_ANDAMENTO", "os_id": 1845,
             "plant_name": "UFV Pirapozinho"},
            {"id": 9332, "name": "Limpeza de módulos", "status": "APROVADA", "os_id": 1845, "plant_name": "UFV Pirapozinho"},
        )}
        self.anexos, self.recusa, self.destinos = [], None, []
        #: a ficha de cada tarefa (a 9332, aprovada, foi emitida: não recebe anexo); sem ficha, o meuPlano dá 400
        self.fichas = {9331: {"test_asset_id": 70, "session_id": 500, "session_status": "IN_PROGRESS"},
                       9332: {"test_asset_id": 71, "session_id": 501, "session_status": "FINALIZED"}}

    async def tarefa(self, tid):
        if tid not in self.tarefas:
            raise _erro(404)
        return self.tarefas[tid]

    async def tarefas_da_ordem(self, so_id):
        return [t for t in self.tarefas.values() if t["os_id"] == so_id]

    async def anexar_na_tarefa(self, tid, nome, conteudo, tipo, descricao, autor):
        if self.recusa:
            raise _erro(403, self.recusa)
        self.anexos.append((tid, nome, conteudo, tipo, descricao, autor))
        self.destinos.append("anexos da tarefa")
        return {"id": len(self.anexos)}

    async def abrir_ficha(self, tid, autor):
        if tid not in self.fichas:
            raise _erro(400, "Tarefa sem equipamento — sem formulário de ensaio.")
        return self.fichas[tid]

    async def anexar_na_ficha(self, ficha, nome, conteudo, tipo, descricao, autor):
        if self.recusa:
            raise _erro(403, self.recusa)
        tid = next(t for t, f in self.fichas.items() if f is ficha)
        self.anexos.append((tid, nome, conteudo, tipo, descricao, autor))
        self.destinos.append("ficha")
        return {"id": len(self.anexos)}


@pytest.fixture
def cenario(db, bot_local, monkeypatch):
    """A IA de mentira: a foto com "tarefa N" ou "OS N" na legenda (ou o número depois) vira `anexar_fotos`; sem
    dizer onde, ela pergunta. O meuPlano e o gateway também de mentira."""
    mp = _MeuPlano()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    monkeypatch.setattr(fotos, "JUNTAR_S", 0)
    baixadas = []

    async def _baixar(mid):
        baixadas.append(mid)
        return f"JPG{mid}".encode(), "image/jpeg"

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None, obrigatoria=False, **k):
        if obrigatoria:                                    # o resto do pedido, depois do Sim: só as fotos
            return {"content": "", "tool_calls": [{"id": "r1", "type": "function", "function": {
                "name": "fim_do_pedido", "arguments": json.dumps({"situacao": "feito"})}}]}
        ultima = msgs[-1]
        if ultima["role"] == "tool":
            return {"content": json.loads(ultima["content"]).get("erro") or "Certo."}
        bot_local.llm.append(ultima["content"])
        if m := re.search(r"(tarefa|os)\s*(\d+)", ultima["content"], re.I):
            chave = "os" if m[1].lower() == "os" else "tarefa"
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "anexar_fotos", "arguments": json.dumps({chave: int(m[2])})}}]}
        return {"content": "Em qual tarefa ou OS eu anexo?"}

    monkeypatch.setattr(assistente.whatsapp, "baixar_midia", _baixar)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    fotos._RECEBIDAS.clear()
    return SimpleNamespace(mp=mp, baixadas=baixadas, bot=bot_local)


def _pessoa(db, perfil=Perfil.TECNICO):
    p = _conta(db, "kewyn", "+5517997367733")
    p.perfil = perfil
    db.commit()
    return p


def _foto(p, n, legenda=""):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "image", "texto": None,
            "midia": {"mime": "image/jpeg", "legenda": legenda}}


async def _sim(db, p, n):
    h.mostrada(p.id)
    await assistente.atender({"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "text", "texto": "Sim"})


async def test_o_album_vira_uma_resposta_e_as_fotos_entram_na_tarefa_com_o_sim(db, cenario):
    p = _pessoa(db)
    # o álbum: uma mensagem por foto, a legenda só na primeira, as três antes de a primeira ser atendida
    await asyncio.gather(*(assistente.atender(_foto(p, i, "tarefa 9331" if i == 1 else "")) for i in (1, 2, 3)))
    assert cenario.bot.llm == ["[📷 3 foto(s) recebida(s), ainda não anexada(s)] tarefa 9331"]   # a IA, uma vez
    assert h.PENDENTES[p.id].resumo == "Anexar 3 foto(s) na ficha da tarefa #9331 «Roçagem embaixo dos módulos»"
    assert h.PENDENTES[p.id].detalhes == ["OS 1845 · UFV Pirapozinho"] and cenario.mp.anexos == []   # nada antes do Sim
    await _sim(db, p, 4)
    assert cenario.bot.enviados[-1] == "✅ 3 foto(s) anexada(s) na ficha da tarefa #9331 (Fotos e anexos)."
    assert cenario.mp.destinos == ["ficha"] * 3          # onde a equipe procura a foto de campo (04/11/2026)
    assert [(t, c, d, a) for t, _, c, _, d, a in cenario.mp.anexos] == [
        (9331, b"JPG1", "tarefa 9331", "Kewyn"), (9331, b"JPG2", "Foto enviada pelo WhatsApp", "Kewyn"),
        (9331, b"JPG3", "Foto enviada pelo WhatsApp", "Kewyn")]
    assert fotos.recebidas(p.telefone) == []                                  # anexadas não voltam numa próxima vez
    log = [r.pergunta for r in db.query(RegistroBot).order_by(RegistroBot.id)]
    assert log[:2] == ["[📷 foto]", "[📷 foto]"] and log[2].startswith("[📷 3 foto(s)")


async def test_sem_dizer_onde_o_bot_pergunta_e_a_resposta_seguinte_anexa(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_foto(p, 1))
    assert cenario.bot.enviados == ["Em qual tarefa ou OS eu anexo?"] and p.id not in h.PENDENTES
    await assistente.atender({"id": 2, "telefone": p.telefone, "wa_id": "1", "tipo": "text", "texto": "na OS 1845"})
    assert h.PENDENTES[p.id].resumo.startswith("Anexar 1 foto(s) na ficha da tarefa #9331")   # a única da OS que o técnico pode
    await _sim(db, p, 3)
    assert [a[0] for a in cenario.mp.anexos] == [9331]


async def test_o_tecnico_nao_anexa_na_tarefa_concluida_e_o_gestor_anexa(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_foto(p, 1, "tarefa 9332"))
    assert "#9332 está concluída: nela só o gestor da O&M anexa foto" in cenario.bot.enviados[-1]
    assert p.id not in h.PENDENTES
    p.perfil = Perfil.GESTOR_EMPRESA
    db.commit()
    await assistente.atender(_foto(p, 2, "tarefa 9332"))
    assert h.PENDENTES[p.id].resumo.startswith("Anexar 2 foto(s) na ficha da tarefa #9332")


async def test_a_situacao_e_conferida_de_novo_no_sim_e_a_recusa_do_meuplano_chega_inteira(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_foto(p, 1, "tarefa 9331"))
    cenario.mp.tarefas[9331]["status"] = "REALIZADA"                # o técnico concluiu enquanto esperava o Sim
    await _sim(db, p, 2)
    # (o 2º parágrafo é o resto do pedido, que não some calado)
    assert cenario.bot.enviados[-1].split("\n\n")[0] == ("❌ A tarefa #9331 está em análise: nela só o gestor da O&M "
                                                          "anexa foto. Nenhuma foto foi anexada.")
    cenario.mp.tarefas[9331]["status"] = "EM_ANDAMENTO"
    cenario.mp.recusa = "Sem permissão para editar tarefas"
    await assistente.atender(_foto(p, 3, "tarefa 9331"))
    await _sim(db, p, 4)
    assert cenario.bot.enviados[-1].split("\n\n")[0] == ("❌ O meuPlano recusou: Sem permissão para editar tarefas. "
                                                          "Nenhuma foto foi anexada.")
    assert len(fotos.recebidas(p.telefone)) == 2 and cenario.mp.anexos == []   # nada se perdeu: dá para tentar de novo


async def test_sem_a_parte_do_meuplano_a_ferramenta_nao_existe(db, cenario):
    p = _pessoa(db)
    p.bot_meuplano = False
    db.commit()
    assert "anexar_fotos" not in assistente.permitidas(p)
    db.refresh(p)
    p.bot_meuplano = True
    assert "anexar_fotos" in assistente.permitidas(p)


async def test_tarefa_sem_ficha_que_receba_vai_aos_anexos_e_o_fim_diz_onde(db, cenario):
    p = _pessoa(db, Perfil.GESTOR_EMPRESA)
    cenario.mp.tarefas[9333] = {"id": 9333, "name": "Visita", "status": "EM_ANDAMENTO", "os_id": 1846,
                                "plant_name": "UFV TIETE"}
    for n, tarefa in ((1, 9333), (3, 9332)):             # 9333 sem ficha (400); a da 9332 foi emitida ao cliente
        await assistente.atender(_foto(p, n, f"tarefa {tarefa}"))
        await _sim(db, p, n + 1)
        assert cenario.bot.enviados[-1] == f"✅ 1 foto(s) anexada(s) nos Anexos da tarefa #{tarefa}, não na ficha."
    assert cenario.mp.destinos == ["anexos da tarefa"] * 2


async def test_a_foto_e_o_texto_logo_depois_sao_um_pedido_so(db, cenario, monkeypatch):
    """04/11/2026: as fotos sem legenda e, 8 s depois, "anexe essas fotos na tarefa…": o bot respondia às fotos
    ("em qual tarefa?") e só depois ao texto, um turno atrás da pessoa."""
    p = _pessoa(db)
    monkeypatch.setattr(assistente, "ESPERA_FOTO_S", 1.0)
    vistas = []

    async def _llm(msgs, ferramentas=None, **k):
        vistas.append([m["content"] for m in msgs if m["role"] == "user"])
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "anexar_fotos", "arguments": json.dumps({"tarefa": 9331})}}]} if len(vistas) == 1 else \
            {"content": "Certo."}

    monkeypatch.setattr(assistente, "_llm", _llm)
    texto = {"id": 9, "telefone": p.telefone, "wa_id": "1", "tipo": "text", "texto": "anexe na roçagem, tarefa 9331"}

    async def _depois():
        await asyncio.sleep(0.3)
        await assistente.atender(texto)

    await asyncio.gather(assistente.atender(_foto(p, 1)), _depois())
    assert vistas[0] == ["[📷 1 foto(s) recebida(s), ainda não anexada(s)]", texto["texto"]]   # uma volta, os dois
    assert "Em qual tarefa" not in " ".join(str(e) for e in cenario.bot.enviados)
    assert h.PENDENTES[p.id].pedido.endswith(texto["texto"])
    log = [(r.pergunta, r.resposta) for r in db.query(RegistroBot).order_by(RegistroBot.id)]
    assert log[0] == ("[📷 1 foto(s) recebida(s), ainda não anexada(s)]", assistente.JUNTADA)
