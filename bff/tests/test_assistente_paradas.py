"""Classificar as paradas pelo WhatsApp, passo a passo (dono, 07/11/2026: "Caíram várias usinas hoje, quero um fluxo
HIPER COMPLETO e DIDÁTICO no WhatsApp para eu classificar as paradas sem precisar ir no site").

O passo a passo é do SISTEMA (não da IA), o estado mora no banco e só se grava no meuWatt com o Confirmar. O meuWatt
aqui é falso: `/queue`, `/compare` e `/breakdown-options` montados no teste, e o que seria gravado fica anotado.
"""

from datetime import UTC, datetime, time, timedelta

import httpx
import pytest

from app.clients.meuwatt import MeuWattClient
from app.core.datas import BRT
from app.models.fluxo_paradas import FluxoParadas
from app.models.plant import PlantLink
from app.models.user import Perfil, User, VinculoProduto
from app.services import assistente
from app.services import assistente_geracao as ger
from app.services import assistente_helper as helper
from app.services import assistente_paradas as par

TEL = "+5517997377626"


def _hoje(h: int, m: int) -> str:
    """O instante de hoje (BRT), em UTC — como o meuWatt devolve."""
    return datetime.combine(ger.hoje(), time(h, m), BRT).astimezone(UTC).isoformat()


def _linha(i, slot, inv, skid, ini, fim, perda, grupo=None, materialidade="material"):
    return {"id": i, "slot_id": slot, "slot_label": inv, "transformer_name": skid, "serial_number": f"SN{slot}",
            "stopped_at": ini, "resolved_at": fim, "resolution_reason": "production_resumed",
            "cause": "zero_active_power", "materiality": materialidade, "off_minutes": 49,
            "shadow_loss_kwh": perda, "loss_method": "peers", "group_id": grupo}


def _par(sid, live, slot, inv, skid, ini, fim, classificada=None, **mais):
    return {"shadow_id": sid, "live_id": live, "slot_id": slot, "slot_label": inv, "transformer_name": skid,
            "live_stopped_at": ini, "live_resolved_at": fim, "live_classified_at": classificada, **mais}


RODADA = {"run_id": 1, "window_start": "2026-06-01T03:00:00Z", "window_end": _hoje(23, 0)}

#: Pereiras: 3 inversores do Skid 1 caíram juntos às 10:42 (o grupo do detector), o INV-07 às 14:10, o INV-08 já
#: classificado no site, e uma piscada (blip) que não é parada.
PEREIRAS_FILA = {"run": RODADA, "groups": [{"id": 7, "group_kind": "spatial_skid", "latest_end": _hoje(11, 31)}],
                 "rows": [_linha(101, 1, "INV-01", "Skid 1", _hoje(10, 42), _hoje(11, 31), 400.0, grupo=7),
                          _linha(102, 2, "INV-02", "Skid 1", _hoje(10, 42), _hoje(11, 31), 410.0, grupo=7),
                          _linha(103, 3, "INV-03", "Skid 1", _hoje(10, 43), _hoje(11, 30), 420.0, grupo=7),
                          _linha(104, 7, "INV-07", "Skid 2", _hoje(14, 10), _hoje(14, 40), 90.5),
                          _linha(105, 8, "INV-08", "Skid 2", _hoje(15, 0), _hoje(15, 20), 30.0),
                          _linha(106, 9, "INV-09", "Skid 2", _hoje(16, 0), _hoje(16, 2), 0.1, materialidade="blip")]}
PEREIRAS_PARES = {"pairs": [_par(101, 5001, 1, "INV-01", "Skid 1", _hoje(10, 42), _hoje(11, 31)),
                            _par(102, 5002, 2, "INV-02", "Skid 1", _hoje(10, 42), _hoje(11, 31)),
                            _par(103, 5003, 3, "INV-03", "Skid 1", _hoje(10, 43), _hoje(11, 30)),
                            _par(104, 5004, 7, "INV-07", "Skid 2", _hoje(14, 10), _hoje(14, 40)),
                            _par(105, 5005, 8, "INV-08", "Skid 2", _hoje(15, 0), _hoje(15, 20),
                                 classificada=_hoje(16, 0))],
                  "live_suppressed_rows": []}
TIETE_FILA = {"run": RODADA, "groups": [], "rows": [_linha(201, 21, "INV-1.1", "TR-1", _hoje(9, 0), _hoje(9, 50), None)]}
TIETE_PARES = {"pairs": [_par(201, 6001, 21, "INV-1.1", "TR-1", _hoje(9, 0), _hoje(9, 50))],
               "live_suppressed_rows": []}

TAXONOMIA = {
    "motivo": [{"id": 1, "label": "Falta de rede", "parent_ids": [], "is_external": True},
               {"id": 2, "label": "Falha em equipamento", "parent_ids": [], "is_external": False}],
    "origem": [{"id": 10, "label": "Concessionária", "parent_ids": [1], "is_external": False},
               {"id": 11, "label": "Inversor", "parent_ids": [2], "is_external": False},
               {"id": 12, "label": "Transformador", "parent_ids": [2], "is_external": False}],
    "causa": [{"id": 20, "label": "Desligamento programado", "parent_ids": [10], "is_external": False},
              {"id": 21, "label": "Queda de tensão", "parent_ids": [10], "is_external": False},
              {"id": 22, "label": "IGBT queimado", "parent_ids": [11], "is_external": False}],
    "causa_raiz": [{"id": 30, "label": "Manutenção da rede", "parent_ids": [20], "is_external": False},
                   {"id": 31, "label": "Descarga atmosférica", "parent_ids": [21, 22], "is_external": False},
                   {"id": 32, "label": "Desgaste", "parent_ids": [22], "is_external": False}],
}


class MeuWattFalso(MeuWattClient):
    def __init__(self):
        super().__init__(base_url="https://api.meuwatt.test", token="mw_pat_teste")
        self.filas = {9378: PEREIRAS_FILA, 9379: TIETE_FILA}
        self.pares = {9378: PEREIRAS_PARES, 9379: TIETE_PARES}
        self.taxonomia = TAXONOMIA
        self.gravadas: list[tuple[list[int], dict]] = []
        self.desclassificadas: list[tuple[str, int, str]] = []
        self.recusa: Exception | None = None
        self.so_grava: int | None = None                   # quantas o meuWatt grava (escopo da pessoa)
        self.compare_falha = False                         # o /compare não responde (na releitura antes de gravar)
        self.sumiu = False                                 # o suppress responde 404 (a parada sumiu do meuWatt)

    async def usinas(self, token=None):
        return [{"slug": "pereiras", "name": "UFV Pereiras", "id": 9378},
                {"slug": "tiete", "name": "UFV Tietê", "id": 9379}]

    async def paradas_detector(self, plant_id, inicio, fim):
        return self.filas[plant_id]

    async def paradas_casadas(self, plant_id, inicio, fim):
        if self.compare_falha:
            raise httpx.ReadTimeout("o meuWatt demorou")
        return self.pares[plant_id]

    async def opcoes_de_parada(self):
        return self.taxonomia

    async def classificar_paradas(self, ids, classificacao):
        if self.recusa:
            raise self.recusa
        self.gravadas.append((list(ids), classificacao))
        return {"updated": len(ids) if self.so_grava is None else self.so_grava}

    async def desclassificar_parada(self, slug, live_id, nota):
        if self.recusa:
            raise self.recusa
        if self.sumiu:
            pedido = httpx.Request("POST", "https://api.meuwatt.test/x")
            raise httpx.HTTPStatusError("404", request=pedido, response=httpx.Response(404, request=pedido))
        self.desclassificadas.append((slug, live_id, nota))


def _recusa_403() -> httpx.HTTPStatusError:
    pedido = httpx.Request("POST", "https://api.meuwatt.test/breakdowns/classify-bulk")
    resposta = httpx.Response(403, json={"detail": "Seu papel nesta usina não altera a classificação de paradas"},
                              request=pedido)
    return httpx.HTTPStatusError("403", request=pedido, response=resposta)


@pytest.fixture
def mw(monkeypatch, db):
    from app.services import vinculos

    falso = MeuWattFalso()
    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda *a, **k: falso)
    monkeypatch.setattr(ger, "usinas_do_bot", lambda db, user: [
        PlantLink(mw_plant_slug="pereiras", nome="UFV Pereiras"), PlantLink(mw_plant_slug="tiete", nome="UFV Tietê")])

    async def _digitando(wamid):
        return None

    monkeypatch.setattr(par.whatsapp, "digitando", _digitando)
    return falso


@pytest.fixture
def dono(db):
    from app.models.empresa import Empresa

    emp = Empresa(nome="O&M do bot")
    db.add(emp)
    db.commit()
    u = User(apelido="renan", email="renan@x.com", nome="Renan", perfil=Perfil.GESTOR_EMPRESA, telefone=TEL,
             bot_meuwatt=True, empresa_id=emp.id)
    db.add(u)
    db.commit()
    db.add(VinculoProduto(gs_user_id=u.id, produto="meuwatt", usuario_remoto_id="1", token_cifrado="x"))
    db.commit()
    db.refresh(u)
    return u


class Conversa:
    """Fala com o fluxo como o WhatsApp: texto ou toque num botão/linha da última mensagem."""

    def __init__(self, db, user):
        self.db, self.user, self.ultima = db, user, []

    async def diz(self, texto):
        r = await par.tratar(self.db, self.user, TEL, {"tipo": "text", "texto": texto, "wamid": "w"}, texto)
        if r is not None:
            self.ultima, self.avancou = r
            return self.ultima
        return None

    def opcoes(self) -> dict[str, str]:
        """Título → id de tudo o que dá para tocar na última leva de mensagens."""
        saida = {}
        for m in self.ultima:
            saida.update({t: i for i, t in m.get("botoes") or []})
            saida.update({li["titulo"]: li["id"] for li in (m.get("lista") or {}).get("linhas") or []})
        return saida

    async def toca(self, titulo, botao=None):
        ident = botao or self.opcoes()[titulo]
        self.ultima, self.avancou = await par.tratar(
            self.db, self.user, TEL, {"tipo": "interactive", "texto": titulo, "botao": ident, "wamid": "w"}, titulo)
        return self.ultima

    @property
    def texto(self) -> str:
        return par.texto_de(self.ultima)


# --------------------------------------------------------------------------------------------- as unidades
def test_as_unidades_sao_as_da_tela_de_paradas():
    """A porta de `build_shadow_units`/`a_classificar`: o grupo do detector é UMA parada com os três `live_id`; a já
    classificada, a piscada e a desclassificada ficam de fora; a parada só ao vivo (sem par no detector) entra."""
    pares = {**PEREIRAS_PARES, "pairs": [*PEREIRAS_PARES["pairs"],
                                         _par(None, 5009, 9, "INV-09", "Skid 2", _hoje(17, 0), _hoje(17, 30))],
             "live_suppressed_rows": [{"live_id": 4999, "slot_id": 7, "stopped_at": _hoje(14, 0),
                                       "resolved_at": _hoje(15, 0)}]}
    pend = par.a_classificar(par.unidades(PEREIRAS_FILA, pares))
    assert [u["live_ids"] for u in pend] == [[5001, 5002, 5003], [5009]]      # o INV-07 foi desclassificado
    grupo = pend[0]
    assert [m["inversor"] for m in grupo["membros"]] == ["INV-01", "INV-02", "INV-03"] and grupo["grupo"] == "spatial_skid"
    sem_desclassificar = par.a_classificar(par.unidades(PEREIRAS_FILA, PEREIRAS_PARES))
    assert [u["live_ids"] for u in sem_desclassificar] == [[5001, 5002, 5003], [5004]]   # o 5005 já classificado


def test_grupo_manual_junta_e_baixa_geracao_nao_entra():
    """O agrupamento manual da tela (`live_manual_group_id`) faz uma parada só; a Baixa Geração nunca é a classificar."""
    pares = {"pairs": [_par(104, 5004, 7, "INV-07", "Skid 2", _hoje(14, 10), _hoje(14, 40), live_manual_group_id="m1"),
                       _par(105, 5005, 8, "INV-08", "Skid 2", _hoje(15, 0), _hoje(15, 20), live_manual_group_id="m1"),
                       _par(101, 5001, 1, "INV-01", "Skid 1", _hoje(10, 42), _hoje(11, 31), live_kind="degradation")],
             "live_suppressed_rows": []}
    fila = {**PEREIRAS_FILA, "groups": [], "rows": [{**r, "group_id": None} for r in PEREIRAS_FILA["rows"][:5]]}
    pend = par.a_classificar(par.unidades(fila, pares))
    assert [u["live_ids"] for u in pend if u["live_ids"]] == [[5004, 5005]]
    # o INV-02 e o INV-03 não têm parada ao vivo casada: são "a classificar", mas não há onde gravar (o resumo diz)
    assert [u["chave"] for u in pend if not u["live_ids"]] == ["s102", "s103"]


# --------------------------------------------------------------------------------------------- o começo
async def test_o_resumo_do_dia_por_usina_com_os_botoes(db, dono, mw):
    c = Conversa(db, dono)
    assert await c.diz("O que caiu hoje?") is None                          # pergunta: vai à IA
    await c.diz("o que caiu hoje")
    t = c.texto
    assert "*2* parada(s) em 2 usina(s)" not in t and "*3* parada(s) em 2 usina(s)" in t
    assert "*UFV Pereiras*: 2 · INV-01, INV-02 e INV-03 (Skid 1) 10:42; INV-07 (Skid 2) 14:10" in t
    assert "perda estimada 1.320 kWh" in t                                   # 400 + 410 + 420 + 90,5
    assert "*UFV Tietê*: 1" in t and "perda estimada" not in t.split("Tietê")[1].split("\n")[0]   # sem conta: nada
    assert "Já classificadas no período: 1." in t
    assert list(c.opcoes()) == ["Classificar agora", "Só uma usina", "Depois"]
    assert db.query(FluxoParadas).count() == 1                               # o estado está no BANCO


async def test_sem_nada_a_classificar_diz_e_nao_abre_o_fluxo(db, dono, mw):
    mw.pares = {9378: {**PEREIRAS_PARES, "pairs": [{**p, "live_classified_at": _hoje(18, 0)}
                                                   for p in PEREIRAS_PARES["pairs"]]},
                9379: {**TIETE_PARES, "pairs": [{**p, "live_classified_at": _hoje(18, 0)} for p in TIETE_PARES["pairs"]]}}
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    assert c.texto.startswith("✅ Nenhuma parada a classificar · hoje") and "Já classificadas: 4." in c.texto
    assert db.query(FluxoParadas).count() == 0


async def test_so_uma_usina_e_usina_no_pedido(db, dono, mw):
    c = Conversa(db, dono)
    await c.diz("classificar as paradas de hoje")
    await c.toca("Só uma usina")
    assert set(c.opcoes()) == {"UFV Pereiras (2)", "UFV Tietê (1)"}
    await c.toca("UFV Tietê (1)")
    assert "*Parada 1 de 1*" in c.texto and "INV-1.1" in c.texto
    await c.diz("classificar paradas de pereiras")                           # começar de novo troca, avisando
    assert c.texto.startswith("(Comecei de novo") and "· UFV Pereiras" in c.texto and "Tietê" not in c.texto


# --------------------------------------------------------------------------------------------- a cascata
async def _ate_o_motivo(c):
    await c.diz("classificar paradas")
    await c.toca("Classificar agora")
    assert "*Parada 1 de 3*" in c.texto and "INV-01, INV-02 e INV-03 (Skid 1)" in c.texto
    assert "Juntei os inversores que caíram ao mesmo tempo" in c.texto and "4 coisas" in c.texto
    await c.toca("Classificar")


async def test_a_cascata_filtra_pelo_pai(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    assert "*Passo 1 de 4 · Motivo:* o que aconteceu?" in c.texto
    assert list(c.opcoes()) == ["Falta de rede", "Falha em equipamento"]
    await c.toca("Falha em equipamento")
    assert "*Passo 2 de 4 · Origem:* onde aconteceu?" in c.texto
    assert list(c.opcoes()) == ["Inversor", "Transformador"]                  # nunca a Concessionária (pai 1)


async def test_uma_opcao_so_escolhe_sozinha_e_diz(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    await c.toca("Falta de rede")
    assert "✔️ Origem: Concessionária (a única opção para «Falta de rede»)." in c.texto
    assert "*Passo 3 de 4 · Causa:*" in c.texto and list(c.opcoes()) == ["Desligamento programado", "Queda de tensão"]


async def test_confirmar_grava_nos_live_ids_e_oferece_as_outras(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    await c.toca("Falta de rede")
    await c.diz("DESLIGAMENTO programado")                                   # digitado, com caixa trocada
    assert "✔️ Causa raiz: Manutenção da rede" in c.texto and "*Causa externa?*" in c.texto
    assert "NÃO conta contra a disponibilidade" in c.texto                   # o motivo é externo no cadastro
    await c.toca("Sim, externa")
    await c.diz("a rede caiu e religou sozinha")
    await c.toca("Sem OS")
    assert "📋 *Confere antes de gravar*" in c.texto and "• Observação: a rede caiu e religou sozinha" in c.texto
    assert mw.gravadas == []                                                 # nada sem o Confirmar
    await c.toca("Confirmar")
    assert mw.gravadas == [([5001, 5002, 5003], {
        "motivo": "Falta de rede", "origem": "Concessionária", "causa": "Desligamento programado",
        "causa_raiz": "Manutenção da rede", "ordem_servico": None, "observacoes": "a rede caiu e religou sozinha",
        "is_external_cause": True})]
    assert "✅ Gravado no meuWatt: INV-01, INV-02 e INV-03 (Skid 1), UFV Pereiras (3 parada(s) ao vivo)." in c.texto
    assert "Há mais 1 parada(s) de *UFV Pereiras*" in c.texto and "INV-07 (Skid 2) · 14:10" in c.texto
    await c.toca("Aplicar às 1")
    assert mw.gravadas[1][0] == [5004] and mw.gravadas[1][1] == mw.gravadas[0][1]
    assert "Mesma classificação gravada em mais 1 parada(s)" in c.texto and "*Parada 3 de 3*" in c.texto
    await c.diz("pular")
    assert c.texto.startswith("🏁 Pronto: 2 classificada(s), 0 marcada(s) como não-parada, 1 pulada(s)")
    assert db.query(FluxoParadas).count() == 0


async def test_corrigir_e_cancelar_no_confere(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    for passo in ("Falha em equipamento", "Inversor"):
        await c.toca(passo)
    assert "✔️ Causa: IGBT queimado" in c.texto and set(c.opcoes()) == {"Descarga atmosférica", "Desgaste"}
    await c.diz("2")                                                          # o número da opção
    assert "CONTA na disponibilidade" in c.texto
    await c.diz("sim")
    await c.toca("Sem observação")
    await c.diz("OS 1638")
    assert "• OS: OS 1638" in c.texto and "• Causa externa: não, conta na disponibilidade" in c.texto
    await c.toca("Corrigir")
    assert "Vamos refazer esta parada." in c.texto and "*Passo 1 de 4 · Motivo:*" in c.texto
    await c.toca("Falta de rede")
    await c.toca("Queda de tensão")
    await c.toca("Sim, externa")
    await c.toca("Sem observação")
    await c.toca("Sem OS")
    await c.toca("Cancelar")
    assert mw.gravadas == [] and "Cancelado: nada foi gravado" in c.texto and "*Parada 2 de 3*" in c.texto


# --------------------------------------------------------------------------------------------- voltar, pular, parar
async def test_voltar_pular_e_parar(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    await c.toca("Falha em equipamento")
    await c.diz("voltar")
    assert "*Passo 1 de 4 · Motivo:*" in c.texto and "(Falha em equipamento)" not in c.texto
    await c.toca("Voltar") if "Voltar" in c.opcoes() else await c.diz("voltar")
    assert "*Parada 1 de 3*" in c.texto
    await c.diz("voltar")
    assert c.texto.startswith("Já estamos no começo desta parada.")
    await c.toca("Um por um")
    assert "Separei em 3 parada(s), uma por inversor." in c.texto and "*Parada 1 de 5*" in c.texto
    await c.diz("pular")
    assert "*Parada 2 de 5*" in c.texto and "INV-02" in c.texto
    await c.diz("parar")
    assert c.texto.startswith("⏸️ Parei aqui. 0 classificada(s), 0 marcada(s) como não-parada, 1 pulada(s).")
    assert "Ficaram 5 para classificar" in c.texto and db.query(FluxoParadas).count() == 0
    assert await c.diz("pular") is None                                       # fluxo fechado: o texto vai à IA


async def test_um_por_um_grava_so_no_inversor_da_vez(db, dono, mw):
    """Separado, cada inversor grava na parada ao vivo DELE — nunca no id do detector, nem nas dos outros dois."""
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    await c.toca("Classificar agora")
    await c.toca("Um por um")
    assert "INV-01 (Skid 1)" in c.texto and "INV-02" not in c.texto
    await c.toca("Classificar")
    for passo in ("Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS", "Confirmar"):
        await c.toca(passo)
    assert [ids for ids, _ in mw.gravadas] == [[5001]]
    assert "Gravado no meuWatt: INV-01 (Skid 1), UFV Pereiras (1 parada(s) ao vivo)" in c.texto
    assert "Há mais 3 parada(s)" in c.texto                                  # INV-02, INV-03 e INV-07, mesmo dia


async def test_resposta_digitada_que_nao_casa(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    assert await c.diz("xyz") is None                                         # não é desta pergunta: vai à IA
    await c.diz("falha")                                                      # pedaço: casa só uma
    assert "*Passo 2 de 4 · Origem:*" in c.texto
    await c.diz("voltar")
    assert await c.diz("fa") is None                                          # curto demais para pedaço
    # pergunta de outro assunto, com a classificação aberta: vai à IA (o fluxo continua esperando)
    assert await c.diz("qual foi a geração de Pereiras ontem comparada com o mês passado?") is None
    assert db.query(FluxoParadas).count() == 1


# --------------------------------------------------------------------------------------------- não foi parada
async def test_nao_foi_parada_desclassifica_com_a_nota(db, dono, mw):
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    await c.toca("Classificar agora")
    await c.toca("Não foi parada")
    assert "*Não foi parada?*" in c.texto
    await c.toca("Comunicação")
    assert "📋 *Confere:* marcar como NÃO foi parada" in c.texto and mw.desclassificadas == []
    await c.toca("Confirmar")
    nota = "Falha de comunicação (não foi parada)"
    assert mw.desclassificadas == [("pereiras", 5001, nota), ("pereiras", 5002, nota), ("pereiras", 5003, nota)]
    assert "✅ Marcada como NÃO foi parada no meuWatt (3 parada(s) ao vivo)" in c.texto
    await c.toca("Não foi parada")
    await c.diz("o logger travou e voltou sozinho")                           # "Outro: escreva"
    assert "• Motivo: o logger travou e voltou sozinho" in c.texto


# --------------------------------------------------------------------------------------------- o meuWatt recusa
async def test_403_do_meuwatt_explicado_e_encerra(db, dono, mw):
    mw.recusa = _recusa_403()
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    for passo in ("Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS", "Confirmar"):
        await c.toca(passo)
    assert c.texto.startswith("❌ Nada foi gravado: o meuWatt recusou («Seu papel nesta usina não altera")
    assert "administrador do sistema e o operador da usina" in c.texto and "⏸️ Parei aqui" in c.texto
    assert db.query(FluxoParadas).count() == 0


async def test_gravacao_parcial_diz_quantas_ficaram_de_fora(db, dono, mw):
    mw.so_grava = 2
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    for passo in ("Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS", "Confirmar"):
        await c.toca(passo)
    assert "⚠️ Gravei em 2 de 3" in c.texto


async def test_ja_classificada_no_site_nao_e_sobrescrita(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    for passo in ("Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS"):
        await c.toca(passo)
    mw.pares[9378] = {**PEREIRAS_PARES, "pairs": [{**p, "live_classified_at": _hoje(18, 0)}
                                                  for p in PEREIRAS_PARES["pairs"]]}
    await c.toca("Confirmar")
    assert mw.gravadas == [] and c.texto.startswith("Essa parada já foi classificada")


# --------------------------------------------------------------------------------------------- estado e botões
async def test_o_estado_vem_do_banco_e_vence(db, dono, mw):
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    velho = c.opcoes()["Classificar agora"]
    await c.toca("Classificar agora")
    await c.toca("Classificar agora", botao=velho)                            # botão de uma pergunta anterior
    assert c.texto.startswith("Esse botão é de uma pergunta anterior. Sigo daqui:") and "*Parada 1 de 3*" in c.texto
    f = db.query(FluxoParadas).one()
    f.expira_em = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    await c.toca("Classificar")
    assert c.texto == par.VENCIDO and db.query(FluxoParadas).count() == 0


async def test_mais_de_3_opcoes_vao_em_lista_e_mais_de_10_no_formulario(db, dono, mw):
    mw.taxonomia = {**TAXONOMIA, "motivo": [{"id": i, "label": f"Motivo número {i}", "parent_ids": [],
                                             "is_external": False} for i in range(1, 6)]}
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    lista = c.ultima[0]["lista"]
    assert len(lista["linhas"]) == 5 and lista["linhas"][0]["titulo"] == "Motivo número 1"
    assert all(li["id"].startswith("pc:") for li in lista["linhas"])
    mw.taxonomia = {**TAXONOMIA, "motivo": [{"id": 100 + i, "label": f"Motivo {i}", "parent_ids": [],
                                             "is_external": False} for i in range(1, 13)] + TAXONOMIA["motivo"]}
    await c.diz("parar")
    await _ate_o_motivo(c)
    form = c.ultima[0]["formulario"]
    assert form["uma"] and len(form["opcoes"]) == 14 and "1. Motivo 1" in c.ultima[0]["alternativa"]
    # a resposta do formulário (Flow `gs_escolha_uma`) volta com o token DESTE fluxo e o índice
    c.ultima, _ = await par.tratar(db, dono, TEL, {"tipo": "interactive", "texto": None, "wamid": "w",
                                                   "midia": {"formulario": {"escolhido": "12",
                                                                            "flow_token": form["token"]}}}, "")
    assert "*Passo 3 de 4 · Causa:*" in c.texto and "(Falta de rede › Concessionária)" in c.texto


# --------------------------------------------------------------------------------------------- dentro do bot
async def test_o_toque_do_fluxo_nao_cai_no_botao_antigo_e_cancela_a_acao(db, dono, mw, monkeypatch):
    """Todo toque interativo que não era o Sim/Não da ação esperando caía no "botão de resumo antigo". O do fluxo vem
    antes; e, com uma ação do meuPlano esperando o Sim, o toque do fluxo a derruba (e diz)."""
    enviados = []

    async def _enviar(**k):
        enviados.append(k)
        return {"ok": True}

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    await assistente.atender({"telefone": TEL, "tipo": "text", "texto": "classificar paradas", "wamid": "w1", "id": 1})
    assert enviados[-1]["tipo"] == "botoes" and "Paradas a classificar" in enviados[-1]["texto"]
    botao = next(b["id"] for b in enviados[-1]["botoes"] if b["titulo"] == "Classificar agora")

    class _Contexto:
        user = dono
        pedido = "crie a OS"
        proposta = None

    async def _nada(*a):
        return "✅ feito"

    helper.propor(_Contexto(), "Criar a OS em Pereiras", 600, _nada, parte=None, confirmacao="sim")
    helper.mostrada(dono.id, datetime.now(UTC) - timedelta(seconds=5))
    await assistente.atender({"telefone": TEL, "tipo": "interactive", "texto": "Classificar agora", "botao": botao,
                              "wamid": "w2", "id": 2})
    ultima = enviados[-1]
    assert "*Parada 1 de 3*" in ultima["texto"] and helper.BOTAO_ANTIGO not in ultima["texto"]
    assert helper.ACAO_CANCELADA_SIM in ultima["texto"] and dono.id not in helper.PENDENTES
    # e o toque num botão `pc:` sem fluxo aberto não vira "confirmação" de nada
    db.query(FluxoParadas).delete()
    db.commit()
    await assistente.atender({"telefone": TEL, "tipo": "interactive", "texto": "Classificar", "botao": "pc:abc:cl",
                              "wamid": "w3", "id": 3})
    assert enviados[-1]["texto"] == par.VENCIDO


async def test_a_ia_comeca_o_fluxo_e_o_resumo_sai_pelo_sistema(db, dono, mw, monkeypatch):
    rodadas = []

    async def _llm(msgs, ferramentas=None, **k):
        rodadas.append(msgs)
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "classificar_paradas", "arguments": '{"usina": "tiete"}'}}]}

    monkeypatch.setattr(assistente, "_llm", _llm)
    ctx = ger.Contexto(db=db, user=dono, telefone=TEL)
    await ger.preparar(ctx)
    r = await assistente.responder(ctx, [{"role": "user", "content": "bora ver o que parou no tietê"}])
    assert len(rodadas) == 1 and ctx.fluxo and r == par.texto_de(ctx.fluxo)
    assert "Paradas a classificar · hoje" in r and "UFV Tietê" in r and "Pereiras" not in r
    assert "classificar_paradas" in assistente.permitidas(dono) and "paradas_a_classificar" in assistente.permitidas(dono)


async def test_sem_o_meuwatt_liberado_explica(db, dono, mw):
    dono.bot_meuwatt = False
    db.commit()
    r, _ = await par.tratar(db, dono, TEL, {"tipo": "text", "texto": "classificar paradas"}, "classificar paradas")
    assert "não está liberada para você" in par.texto_de(r)
    assert await par.tratar(db, dono, TEL, {"tipo": "text", "texto": "oi"}, "oi") is None   # o resto vai à IA


# ============================================================================================= revisão adversarial
async def _ate_o_confere(c, *passos):
    await _ate_o_motivo(c)
    for passo in passos:
        await (c.toca(passo) if passo in c.opcoes() else c.diz(passo))


async def test_1_digitar_o_titulo_do_botao_da_causa_externa_nao_inverte(db, dono, mw):
    """O texto alternativo do bot manda digitar «Não, conta»: com motivo externo, isso é NÃO externa (conta na
    disponibilidade). As palavras soltas ("não" + "conta") gravavam o contrário."""
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão")
    await c.diz("Não, conta")                                                 # o motivo é externo no cadastro
    for passo in ("Sem observação", "Sem OS", "Confirmar"):
        await c.toca(passo)
    assert mw.gravadas[-1][1]["is_external_cause"] is False
    await c.diz("parar")
    c2 = Conversa(db, dono)
    await _ate_o_confere(c2, "Falha em equipamento", "Inversor", "Desgaste")
    await c2.diz("Não, é externa")                                            # o motivo NÃO é externo
    for passo in ("Sem observação", "Sem OS", "Confirmar"):
        await c2.toca(passo)
    assert mw.gravadas[-1][1]["is_external_cause"] is True


class PeloBot:
    """Fala com o bot inteiro (`assistente.atender`), como o gateway: texto ou toque no botão/linha mais recente."""

    def __init__(self, db, monkeypatch):
        self.enviados, self.n = [], 0

        async def _enviar(**k):
            self.enviados.append(k)
            return {"ok": True}

        monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
        monkeypatch.setattr(assistente, "ESPERA_TEXTO_S", 0.0)          # sem esperar a mensagem seguinte
        monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
        monkeypatch.setattr(db, "close", lambda: None)

    async def manda(self, texto):
        self.n += 1
        await assistente.atender({"telefone": TEL, "tipo": "text", "texto": texto, "wamid": f"w{self.n}",
                                  "id": self.n})

    def botao(self, titulo):
        for e in reversed(self.enviados):
            for b in [*(e.get("botoes") or []), *((e.get("lista") or {}).get("linhas") or [])]:
                if b["titulo"] == titulo:
                    return b["id"]
        raise KeyError(titulo)

    async def toca(self, titulo, botao=None):
        self.n += 1
        await assistente.atender({"telefone": TEL, "tipo": "interactive", "texto": titulo,
                                  "botao": botao or self.botao(titulo), "wamid": f"w{self.n}", "id": self.n})


async def test_2_a_senha_de_atuacao_na_observacao_nao_vai_ao_meuwatt_nem_ao_gateway(db, dono, mw, monkeypatch):
    """«religou depois que digitei 482913 no painel», com 482913 a senha de atuação: ia em claro na observação do
    meuWatt e no Confere guardado pelo gateway. E a cópia do gateway passa pela máscara de sempre (`_guardado`)."""
    from app.core.security import gerar_hash_senha

    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    bot = PeloBot(db, monkeypatch)
    await bot.manda("classificar paradas")
    for passo in ("Classificar agora", "Classificar", "Falta de rede", "Queda de tensão", "Sim, externa"):
        await bot.toca(passo)
    await bot.manda("religou depois que digitei 482913 no painel")
    await bot.toca("Sem OS")
    await bot.toca("Confirmar")
    assert mw.gravadas[-1][1]["observacoes"] == "religou depois que digitei [senha oculta] no painel"
    assert not [e for e in bot.enviados if "482913" in (e.get("texto") or "") + (e.get("guardar") or "")]
    # o que a pessoa escreveu e não é a senha de atuação chega a ela inteiro, e a cópia guardada sai sem o número
    await bot.toca("Uma a uma")
    for passo in ("Classificar", "Falta de rede", "Queda de tensão", "Sim, externa"):
        await bot.toca(passo)
    await bot.manda("a senha do portão é 4321")
    await bot.toca("Sem OS")
    confere = bot.enviados[-1]
    assert "a senha do portão é 4321" in confere["texto"] and "4321" not in (confere.get("guardar") or "4321")


async def test_3_sem_reler_o_meuwatt_nao_grava(db, dono, mw):
    """O /compare não respondeu na releitura: gravar por cima do que o site classificou é pior que pedir de novo."""
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS")
    mw.compare_falha = True
    await c.toca("Confirmar")
    assert mw.gravadas == [] and c.texto.startswith("❌ Não consegui conferir no meuWatt")
    assert "Confirmar" in c.opcoes()                                          # a mesma pergunta, para tentar de novo
    mw.compare_falha = False
    await c.toca("Confirmar")
    assert len(mw.gravadas) == 1 and "Há mais 1 parada(s)" in c.texto
    mw.compare_falha = True
    await c.toca("Aplicar às 1")
    assert len(mw.gravadas) == 1 and c.texto.startswith("❌ Não consegui conferir no meuWatt")


async def test_4_toque_velho_nao_derruba_a_acao_que_espera(db, dono, mw, monkeypatch):
    """Botão de pergunta anterior, ou de classificação vencida, não confirma nem cancela nada (avaliações 13 e 14)."""
    bot = PeloBot(db, monkeypatch)
    await bot.manda("classificar paradas")
    velho = bot.botao("Classificar agora")
    await bot.toca("Classificar agora")

    class _Ctx:
        user, pedido, proposta = dono, "crie a OS", None

    async def _nada(*a):
        return "✅ feito"

    helper.propor(_Ctx(), "Criar a OS em Pereiras", 600, _nada, parte=None, confirmacao="sim")
    helper.mostrada(dono.id, datetime.now(UTC) - timedelta(seconds=5))
    await bot.toca("Classificar agora", botao=velho)                          # pergunta anterior
    assert "pergunta anterior" in bot.enviados[-1]["texto"] and dono.id in helper.PENDENTES
    assert helper.ACAO_CANCELADA_SIM not in bot.enviados[-1]["texto"]
    db.query(FluxoParadas).delete()
    db.commit()
    await bot.toca("Classificar", botao=bot.botao("Classificar"))             # classificação vencida
    assert bot.enviados[-1]["texto"] == par.VENCIDO and dono.id in helper.PENDENTES


async def test_5_com_a_classificacao_aberta_a_conversa_vai_a_ia(db, dono, mw):
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    assert await c.diz("sim") is None                                         # «sim» solto não começa a classificar
    await c.toca("Classificar agora")
    await c.toca("Classificar")
    for conversa in ("bom dia", "obrigado", "geração de hoje", "e Tietê?"):
        assert await c.diz(conversa) is None, conversa
    for passo in ("Falta de rede", "Queda de tensão", "Sim, externa"):
        await c.toca(passo)
    assert await c.diz("qual a geração de Pereiras hoje?") is None            # pergunta não é observação
    await c.toca("Sem observação")
    assert await c.diz("religou às 11h") is None                              # não é número de OS
    await c.diz("classificar as paradas de hoje")                             # nem isso: é começar de novo
    assert c.texto.startswith("(Comecei de novo") and "Paradas a classificar · hoje" in c.texto


def _envelhece(db, minutos=31):
    """A última pergunta do fluxo foi há `minutos`."""
    f = db.query(FluxoParadas).one()
    estado = par.json.loads(f.estado)
    estado["em"] = (datetime.now(UTC) - timedelta(minutes=minutos)).isoformat()
    f.estado = par.json.dumps(estado)
    db.commit()


async def test_5_sem_o_meuwatt_so_responde_o_que_e_da_classificacao(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    dono.bot_meuwatt = False
    db.commit()
    assert await c.diz("oi") is None                                          # o resto (meuPlano…) segue para a IA
    r = await c.diz("Falta de rede")
    assert "não está liberada para você" in par.texto_de(r)


async def test_6_pergunta_e_data_incerta_nao_comecam(db, dono, mw):
    c = Conversa(db, dono)
    for frase in ("quantas paradas faltam classificar hoje?", "o que caiu hoje?",
                  "classificar as paradas de anteontem", "classificar as paradas do dia 03/11",
                  "classificar as paradas do mês passado", "paradas de Pereiras"):
        assert await c.diz(frase) is None, frase
    assert db.query(FluxoParadas).count() == 0
    await c.diz("classificar as paradas de ontem")
    assert c.texto.startswith("✅ Nenhuma parada a classificar · ontem")     # o período lido é ontem
    await c.diz("classificar paradas")
    tok = par.json.loads(db.query(FluxoParadas).one().estado)["tok"]
    assert await c.diz("a parada de ontem já foi classificada?") is None      # não reinicia a aberta
    assert par.json.loads(db.query(FluxoParadas).one().estado)["tok"] == tok


async def test_7_aplicar_as_outras_mostra_a_observacao_e_a_os(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa")
    await c.diz("trip do religador 52")
    await c.diz("OS 1638")
    await c.toca("Confirmar")
    assert "• Observação: trip do religador 52" in c.texto and "• OS: OS 1638" in c.texto
    assert "inclusive a observação e a OS" in c.texto


async def test_8_pular_depois_de_gravar_e_uma_a_uma(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS",
                         "Confirmar")
    await c.diz("pular")                                                      # a gravada não vira pulada
    assert "*Parada 2 de 3*" in c.texto
    await c.diz("parar")
    assert "1 classificada(s), 0 marcada(s) como não-parada, 0 pulada(s)" in c.texto and "Ficaram 2" in c.texto


async def test_9_usina_que_saiu_do_alcance_nao_e_gravada(db, dono, mw, monkeypatch):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS")
    monkeypatch.setattr(ger, "usinas_do_bot", lambda db, user: [PlantLink(mw_plant_slug="tiete", nome="UFV Tietê")])
    await c.toca("Confirmar")
    assert mw.gravadas == [] and "UFV Pereiras não está mais liberada para você" in c.texto
    assert "Pulei as 2 parada(s) dela" in c.texto and "INV-1.1" in c.texto    # segue na usina que ela ainda vê


def test_10_linha_ao_vivo_absorvida_e_desclassificada_sem_par():
    """Duas regras da porta que nenhum teste vigiava: a linha ao vivo que o detector ABSORVEU (`covered_by_shadow_id`)
    é desta parada (grava nela, e se estiver classificada a parada está classificada); e a desclassificação que cobre
    só parte de uma parada SEM par ao vivo já a tira da fila."""
    absorvida = _par(None, 5010, 7, "INV-07", "Skid 2", _hoje(14, 15), _hoje(14, 25), covered_by_shadow_id=104)
    pares = {**PEREIRAS_PARES, "pairs": [*PEREIRAS_PARES["pairs"], absorvida]}
    pend = par.a_classificar(par.unidades(PEREIRAS_FILA, pares))
    assert [u["live_ids"] for u in pend] == [[5001, 5002, 5003], [5004, 5010]]
    pares["pairs"][-1] = {**absorvida, "live_classified_at": _hoje(18, 0)}
    assert [u["live_ids"] for u in par.a_classificar(par.unidades(PEREIRAS_FILA, pares))] == [[5001, 5002, 5003]]
    # INV-07 sem par ao vivo e 1/3 dele desclassificado: fora da fila; COM par, 1/3 não basta
    sem_par = {"pairs": [p for p in PEREIRAS_PARES["pairs"] if p["shadow_id"] != 104],
               "live_suppressed_rows": [{"live_id": 4999, "slot_id": 7, "stopped_at": _hoje(14, 10),
                                         "resolved_at": _hoje(14, 20)}]}
    assert "s104" not in [u["chave"] for u in par.a_classificar(par.unidades(PEREIRAS_FILA, sem_par))]
    com_par = {**sem_par, "pairs": PEREIRAS_PARES["pairs"]}
    assert "s104" in [u["chave"] for u in par.a_classificar(par.unidades(PEREIRAS_FILA, com_par))]


async def test_a_contar_as_pendentes_tem_o_mesmo_teto(db, dono, mw):
    ctx = ger.Contexto(db=db, user=dono, telefone=TEL)
    await ger.preparar(ctx)
    hoje = ger.hoje()
    with pytest.raises(ger.Recusa):
        await par.paradas_a_classificar(ctx, {"inicio": (hoje - timedelta(days=60)).isoformat(),
                                              "fim": hoje.isoformat()})


async def test_b_observacao_em_duas_mensagens_nao_vira_os(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa")
    await c.diz("a rede caiu")
    await c.diz("e voltou sozinha 10 min depois")
    assert c.texto.startswith("Juntei à observação: «a rede caiu e voltou sozinha 10 min depois».")
    await c.toca("Sem OS")
    assert "• Observação: a rede caiu e voltou sozinha 10 min depois" in c.texto and "• OS: nenhuma" in c.texto


async def test_c_nada_gravado_nao_sai_como_feito(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS",
                         "Confirmar")
    mw.pares[9378] = {**PEREIRAS_PARES, "pairs": [{**p, "live_classified_at": _hoje(18, 0)}
                                                  for p in PEREIRAS_PARES["pairs"]]}
    await c.toca("Aplicar às 1")
    assert c.texto.startswith("Nada foi gravado: as 1 já tinham sido classificadas") and "✅" not in c.texto
    mw.sumiu = True
    await c.toca("Não foi parada")                                            # a de Tietê
    await c.toca("Comunicação")
    await c.toca("Confirmar")
    assert c.texto.startswith("Nada foi desclassificado") and "✅" not in c.texto


async def test_d_um_por_um_deixa_de_fora_a_piscada(db, dono, mw):
    fila = {**PEREIRAS_FILA, "rows": [*PEREIRAS_FILA["rows"][:2],
                                      {**PEREIRAS_FILA["rows"][2], "materiality": "blip"}, *PEREIRAS_FILA["rows"][3:]]}
    mw.filas[9378] = fila
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    await c.toca("Classificar agora")
    await c.toca("Um por um")
    assert "Separei em 2 parada(s), uma por inversor. 1 só piscou (não é parada) e ficou de fora." in c.texto
    assert "*Parada 1 de 4*" in c.texto


async def test_e_acao_armada_junto_com_a_classificacao_nao_fica_esperando(db, dono, mw, monkeypatch):
    async def _llm(msgs, ferramentas=None, **k):
        return {"content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "manutencao", "arguments": '{"pergunta": "x"}'}},
            {"id": "c2", "type": "function", "function": {"name": "classificar_paradas", "arguments": "{}"}}]}

    async def _manutencao(ctx, a):
        async def _nada(*x):
            return "✅"
        return helper.propor(ctx, "Criar a OS em Pereiras", 600, _nada, parte=None, confirmacao="sim")

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setitem(assistente.FERRAMENTAS, "manutencao", (_manutencao, assistente._MANUTENCAO))
    dono.bot_meuplano = True
    db.add(VinculoProduto(gs_user_id=dono.id, produto="meuplano", usuario_remoto_id="1", token_cifrado="x"))
    db.commit()
    db.refresh(dono)
    ctx = ger.Contexto(db=db, user=dono, telefone=TEL)
    await ger.preparar(ctx)
    r = await assistente.responder(ctx, [{"role": "user", "content": "crie a OS e classifique as paradas"}])
    assert ctx.proposta is None and dono.id not in helper.PENDENTES
    assert "Paradas a classificar" in r and "A ação «Criar a OS em Pereiras» não ficou esperando o seu Sim" in r


# ============================================================================================= 2ª revisão (regressões)
async def test_r1_numero_que_nao_e_a_senha_e_a_os_e_nao_conta_erro(db, dono, mw, monkeypatch):
    """Quem tem senha de atuação e digita «202611» na pergunta da OS: o número não é a senha (conferido), então é a OS —
    tratá-lo como tentativa contava erro de senha («Não há ação esperando senha») e, em 5, bloqueava as ações. A senha
    CERTA nunca vira OS."""
    from app.core.security import gerar_hash_senha

    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    bot = PeloBot(db, monkeypatch)
    await bot.manda("classificar paradas")
    for passo in ("Classificar agora", "Classificar", "Falta de rede", "Queda de tensão", "Sim, externa",
                  "Sem observação"):
        await bot.toca(passo)
    await bot.manda("482913")                                                 # a senha certa: não é a OS
    assert "• OS:" not in bot.enviados[-1]["texto"]
    await bot.manda("202611")
    assert "• OS: 202611" in bot.enviados[-1]["texto"]
    assert not [e for e in bot.enviados if helper.NADA_ESPERANDO[:30] in (e.get("texto") or "")][1:]
    assert dono.id not in helper._ERROS
    await bot.toca("Confirmar")
    assert mw.gravadas[-1][1]["ordem_servico"] == "202611"


async def test_r2_observacao_que_comeca_com_palavra_de_pedido_e_observacao(db, dono, mw):
    """Só a pergunta («?») ou o pedido de começar a classificar desviam o texto da observação — nunca a 1ª palavra."""
    frases = ("Quando a equipe chegou o inversor já tinha religado", "Como sempre, a concessionária desligou",
              "Faz 2 dias que o disjuntor desarma", "Me avisaram que foi raio", "manda o relatório de outubro")
    for frase in frases:
        c = Conversa(db, dono)
        await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa")
        assert await c.diz(frase) is not None, frase
        await c.toca("Sem OS")
        assert f"• Observação: {frase}" in c.texto
        await c.diz("parar")


async def test_r3_na_pergunta_da_os_o_numero_e_a_os_e_concordancia_nao_vira_observacao(db, dono, mw):
    """Depois de «a rede caiu», dentro dos 60 s: «sim» e «ok» não são o resto da observação; o número é a OS («a OS é a
    1638», «nº 1638»; «1638 e 1640» guarda as duas — o campo do meuWatt é texto, e a pessoa confere)."""
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa")
    await c.diz("a rede caiu")
    await c.diz("sim")                                                        # «tem OS?» — sim: qual?
    assert c.texto.startswith("Qual o número da OS?")
    assert await c.diz("ok") is None                                          # concordância não é observação
    await c.diz("a OS é a 1638")
    assert "• Observação: a rede caiu\n" in c.texto and "• OS: 1638" in c.texto
    for frase, os_ in (("nº 1638", "1638"), ("1638 e 1640", "1638, 1640"), ("OS 1638", "OS 1638")):
        await c.toca("Corrigir")
        for passo in ("Falta de rede", "Queda de tensão", "Sim, externa"):
            await c.toca(passo)
        await c.diz("trip no religador")
        await c.diz(frase)
        assert "• Observação: trip no religador\n" in c.texto and f"• OS: {os_}" in c.texto, frase


async def test_r4_titulo_opcao_parar_e_sim_nao_valem_as_12h(db, dono, mw):
    """A janela de 30 min é só do TEXTO LIVRE. O título do botão, a opção exata, «parar» e o sim/não da pergunta da vez
    valem enquanto o fluxo vale — senão a resposta certa ia à IA sem contexto e o fluxo não parava por texto."""
    c = Conversa(db, dono)
    await _ate_o_motivo(c)
    _envelhece(db)
    await c.diz("Falta de rede")                                              # opção exata, 31 min depois
    assert "*Passo 3 de 4 · Causa:*" in c.texto
    for passo in ("Queda de tensão", "Sim, externa"):
        await c.toca(passo)
    _envelhece(db)
    assert await c.diz("a rede caiu") is None                                 # texto livre velho: conversa
    await c.diz("Sem observação")                                             # o título do botão vale
    await c.diz("Sem OS")
    await c.diz("sim")                                                        # o sim do Confere grava
    assert len(mw.gravadas) == 1 and "Há mais 1 parada(s)" in c.texto
    await c.diz("sim")                                                        # o sim das outras aplica
    assert len(mw.gravadas) == 2
    await c.diz("sim")                                                        # o sim do cartão classifica
    assert "*Passo 1 de 4 · Motivo:*" in c.texto
    _envelhece(db, 60 * 11)
    await c.diz("parar")
    assert c.texto.startswith("⏸️ Parei aqui") and db.query(FluxoParadas).count() == 0


async def test_r4_nao_no_confere_e_nas_outras(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS")
    await c.diz("não")                                                        # o não do Confere cancela
    assert mw.gravadas == [] and "Cancelado: nada foi gravado" in c.texto and "*Parada 2 de 3*" in c.texto
    await c.diz("parar")
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS",
                         "Confirmar")
    assert "Há mais 1 parada(s)" in c.texto
    await c.diz("não")                                                        # o não das outras é «Uma a uma»
    assert len(mw.gravadas) == 1 and "*Parada 2 de 3*" in c.texto


async def test_usina_no_resumo_so_pelo_nome_inteiro(db, dono, mw):
    c = Conversa(db, dono)
    await c.diz("classificar paradas")
    assert await c.diz("pere") is None                                        # pedaço não escolhe usina
    await c.diz("pereiras")
    assert "*Parada 1 de 2*" in c.texto and "UFV Pereiras" in c.texto


async def test_copia_do_gateway_no_teto_dele(monkeypatch):
    """A máscara troca «123» por «••••»: num texto perto de 4.096 a cópia passava do teto do gateway (422) e a mensagem
    inteira caía."""
    chamadas = []

    async def _enviar(**k):
        chamadas.append(k)
        return {"ok": True}

    monkeypatch.setattr(par.whatsapp, "enviar_conteudo", _enviar)
    texto = "• senha 123 " * 340
    await par.enviar(TEL, [{"texto": texto, "lista": {"botao": "Ver", "secao": "x", "linhas": []}}],
                     guardar=lambda t: assistente._guardado(t, []))
    await par.enviar(TEL, [{"texto": texto}], guardar=lambda t: assistente._guardado(t, []))
    assert chamadas and all(len(c.get("guardar") or "") <= 4096 for c in chamadas)
    assert all("123" not in (c.get("guardar") or "") for c in chamadas)


# ============================================================================================= 3ª revisão
async def _ate_o_confere_pelo_bot(bot):
    await bot.manda("classificar paradas")
    for passo in ("Classificar agora", "Classificar", "Falta de rede", "Queda de tensão", "Sim, externa",
                  "Sem observação", "Sem OS"):
        await bot.toca(passo)
    assert "📋 *Confere antes de gravar*" in bot.enviados[-1]["texto"]


async def test_3a_sim_solto_depois_de_outra_resposta_do_bot_nao_grava(db, dono, mw, monkeypatch):
    """(A) O Confere aberto; a pessoa pergunta outra coisa, o bot responde, e o «sim» seguinte é para ELE — não grava
    nem o «não» descarta. O toque no botão Confirmar continua valendo."""
    async def _llm(msgs, ferramentas=None, **k):
        return {"content": "Hoje gerou bem."}

    monkeypatch.setattr(assistente, "_llm", _llm)
    bot = PeloBot(db, monkeypatch)
    await _ate_o_confere_pelo_bot(bot)
    await bot.manda("e a geração de hoje?")                                   # vai à IA: o bot responde outra coisa
    await bot.manda("sim")
    await bot.manda("não")
    assert mw.gravadas == [] and par.json.loads(db.query(FluxoParadas).one().estado)["etapa"] == "conferir"
    await bot.toca("Confirmar")
    assert len(mw.gravadas) == 1


async def test_3a_sim_solto_horas_depois_nao_grava_nem_aplica(db, dono, mw, monkeypatch):
    bot = PeloBot(db, monkeypatch)
    await _ate_o_confere_pelo_bot(bot)
    _envelhece(db, 120)
    await bot.manda("sim")                                                    # 2 h depois
    assert mw.gravadas == []
    await bot.toca("Confirmar")
    assert len(mw.gravadas) == 1 and "Há mais 1 parada(s)" in bot.enviados[-1]["texto"]
    _envelhece(db, 90)
    await bot.manda("ok")                                                     # 90 min depois, nas outras
    assert len(mw.gravadas) == 1


async def test_3b_acao_vencida_fica_com_o_sim(db, dono, mw, monkeypatch):
    """(B) A ação do meuPlano VENCEU sem resposta; o «sim» é para ela (o helper diz que venceu), não grava as paradas.
    (2, abaixo) A ação de equipamento vencida e a senha com um dígito errado («482914») na pergunta da OS: não vira a
    OS — a quase-senha iria ao meuWatt e o erro de senha não contaria."""
    from time import monotonic

    bot = PeloBot(db, monkeypatch)
    await _ate_o_confere_pelo_bot(bot)

    class _Ctx:
        user, pedido, proposta = dono, "crie a OS", None

    async def _nada(*a):
        return "✅ feito"

    helper.propor(_Ctx(), "Criar a OS em Pereiras", 600, _nada, parte=None, confirmacao="sim")
    helper.mostrada(dono.id, datetime.now(UTC) - timedelta(minutes=11))
    helper.PENDENTES[dono.id].expira = monotonic() - 1                       # venceu
    await bot.manda("sim")
    assert mw.gravadas == [] and "venceu" in bot.enviados[-1]["texto"]


async def test_2_quase_senha_com_acao_de_equipamento_vencida_nao_vira_os(db, dono, mw, monkeypatch):
    from app.core.security import gerar_hash_senha
    from time import monotonic

    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    bot = PeloBot(db, monkeypatch)
    await bot.manda("classificar paradas")
    for passo in ("Classificar agora", "Classificar", "Falta de rede", "Queda de tensão", "Sim, externa",
                  "Sem observação"):
        await bot.toca(passo)

    class _Ctx:
        user, pedido, proposta = dono, "desliga o 3", None

    async def _nada(*a):
        return "✅ feito"

    helper.propor(_Ctx(), "Desligar o inversor 3", 120, _nada, parte=None, confirmacao="senha")
    helper.mostrada(dono.id, datetime.now(UTC) - timedelta(minutes=3))
    helper.PENDENTES[dono.id].expira = monotonic() - 1
    await bot.manda("482914")
    assert not [e for e in bot.enviados if "482914" in (e.get("texto") or "") + (e.get("guardar") or "")]
    assert par.json.loads(db.query(FluxoParadas).one().estado)["etapa"] == "os"


def test_resumo_so_escolhe_usina_pelo_nome_exato():
    estado = {"etapa": "resumo", "titulos": {}, "todas": [{"usina": "boa"}],
              "usinas": {"boa": {"nome": "UFV Boa Esperança"}}}
    assert par._acao_do_texto(estado, "boa", "boa") is None and par._acao_do_texto(estado, "1", "1") is None
    assert par._acao_do_texto(estado, "boa esperanca", "Boa Esperança") == "o0"


async def test_horario_logo_depois_da_observacao_nao_e_os(db, dono, mw):
    c = Conversa(db, dono)
    await _ate_o_confere(c, "Falta de rede", "Queda de tensão", "Sim, externa")
    await c.diz("a rede caiu")
    await c.diz("10:42")
    assert "OS" not in c.texto.split("\n")[0] and c.texto.startswith("Juntei à observação: «a rede caiu 10:42».")
    assert await c.diz("11h") is not None and "a rede caiu 10:42 11h" in c.texto


# ============================================================================================= 4ª revisão
def _aviso_do_motor(db, quando, user_id=None, destino=TEL, status="enviada", chave="parada:tiete:1"):
    """O que `motor._entregar` grava ao mandar o template («Tietê parou às 10:08») — ele não passa pelo Log do bot."""
    from app.models.notificacao import NotificacaoEnviada

    db.add(NotificacaoEnviada(user_id=user_id, tipo="parada", chave=chave, destino=destino, status=status,
                              criada_em=quando))
    db.commit()


async def test_4_aviso_do_motor_depois_da_pergunta_tira_a_validade_do_sim_solto(db, dono, mw, monkeypatch):
    """O Confere saiu; o motor manda «Tietê parou»; o «ok» da pessoa é para o AVISO e não grava a classificação. Idem o
    «sim» na pergunta das outras (pelo número: o contato da usina com o mesmo celular) e no «não foi parada». O aviso que
    saiu ANTES da pergunta não conta; o aviso que falhou não chegou."""
    bot = PeloBot(db, monkeypatch)
    _aviso_do_motor(db, datetime.now(UTC) - timedelta(minutes=30), user_id=dono.id, chave="parada:tiete:0")
    await _ate_o_confere_pelo_bot(bot)
    _aviso_do_motor(db, datetime.now(UTC), user_id=dono.id, status="falhou", chave="parada:tiete:9")
    await bot.manda("sim")                                                    # o aviso antigo e o que falhou: vale
    assert len(mw.gravadas) == 1 and "Há mais 1 parada(s)" in bot.enviados[-1]["texto"]
    _aviso_do_motor(db, datetime.now(UTC) + timedelta(seconds=1), destino=TEL)   # pelo número, sem a conta
    await bot.manda("sim")
    assert len(mw.gravadas) == 1                                              # não aplicou às outras
    await bot.toca("Uma a uma")
    await bot.toca("Classificar")
    for passo in ("Falta de rede", "Queda de tensão", "Sim, externa", "Sem observação", "Sem OS"):
        await bot.toca(passo)
    _aviso_do_motor(db, datetime.now(UTC) + timedelta(seconds=1), user_id=dono.id, chave="parada:tiete:2")
    await bot.manda("ok")                                                     # o «ok» é para o aviso
    assert len(mw.gravadas) == 1
    await bot.toca("Confirmar")                                               # o botão continua valendo
    assert len(mw.gravadas) == 2
    await bot.toca("Não foi parada")                                          # Tietê
    await bot.toca("Comunicação")
    _aviso_do_motor(db, datetime.now(UTC) + timedelta(seconds=1), user_id=dono.id, chave="parada:tiete:3")
    await bot.manda("sim")
    assert mw.desclassificadas == []
