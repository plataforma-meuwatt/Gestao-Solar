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

    async def usinas(self, token=None):
        return [{"slug": "pereiras", "name": "UFV Pereiras", "id": 9378},
                {"slug": "tiete", "name": "UFV Tietê", "id": 9379}]

    async def paradas_detector(self, plant_id, inicio, fim):
        return self.filas[plant_id]

    async def paradas_casadas(self, plant_id, inicio, fim):
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
            self.ultima = r
        return r

    def opcoes(self) -> dict[str, str]:
        """Título → id de tudo o que dá para tocar na última leva de mensagens."""
        saida = {}
        for m in self.ultima:
            saida.update({t: i for i, t in m.get("botoes") or []})
            saida.update({li["titulo"]: li["id"] for li in (m.get("lista") or {}).get("linhas") or []})
        return saida

    async def toca(self, titulo, botao=None):
        ident = botao or self.opcoes()[titulo]
        self.ultima = await par.tratar(self.db, self.user, TEL,
                                       {"tipo": "interactive", "texto": titulo, "botao": ident, "wamid": "w"}, titulo)
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
    await c.diz("O que caiu hoje?")
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
    await c.diz("xyz")
    assert c.texto.startswith("Não entendi.") and "*Passo 1 de 4 · Motivo:*" in c.texto
    await c.diz("falha")                                                      # pedaço: casa só uma
    assert "*Passo 2 de 4 · Origem:*" in c.texto
    await c.diz("voltar")
    await c.diz("fa")                                                         # curto demais para pedaço
    assert c.texto.startswith("Não entendi.")
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
    c.ultima = await par.tratar(db, dono, TEL, {"tipo": "interactive", "texto": None, "wamid": "w",
                                                "midia": {"formulario": {"escolhido": "12", "flow_token": form["token"]}}},
                                "")
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
    r = await par.tratar(db, dono, TEL, {"tipo": "text", "texto": "classificar paradas"}, "classificar paradas")
    assert "não está liberada para você" in par.texto_de(r)
    assert await par.tratar(db, dono, TEL, {"tipo": "text", "texto": "oi"}, "oi") is None   # o resto vai à IA
