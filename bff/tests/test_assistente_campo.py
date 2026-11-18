"""O técnico em CAMPO pelo WhatsApp (Renan, 18/11/2026): a coordenada de um equipamento ("câmera 1" + a localização), a
plaqueta lida da foto e a foto guardada no equipamento do meuPlano. A câmera vai ao meuGuarda (dono da posição dela); o
resto, ao mapa da usina (o do meuWatt, que o meuPlano mostra). O nome que não existe volta com a lista, e renomear a
câmera entra na mesma ação, com o Sim."""

import json

import httpx
import pytest

from app.models.empresa import Empresa
from app.models.user import Perfil, User, VinculoProduto
from app.services import assistente
from app.services import assistente_campo as campo
from app.services import assistente_fotos as fotos
from app.services import assistente_geracao as ger
from app.services import assistente_helper as helper
from app.services import assistente_local as local
from app.services import vinculos

LAT, LNG = -22.1234567, -47.7654321


_N = iter(range(10, 99))


def _conta(db, telefone=None, **bot):
    emp = db.query(Empresa).filter_by(nome="O&M de campo").one_or_none() or Empresa(nome="O&M de campo")
    db.add(emp)
    db.commit()
    n = next(_N)
    u = User(apelido=f"diogo{n}", nome="Diogo", perfil=Perfil.GESTOR_EMPRESA, telefone=telefone or f"+55179973701{n}",
             empresa_id=emp.id, **bot)
    db.add(u)
    db.commit()
    if bot.get("bot_meuplano"):
        db.add(VinculoProduto(gs_user_id=u.id, produto="meuplano", usuario_remoto_id="9", token_cifrado="x"))
        db.commit()
    return u


def _ctx(db, **bot):
    u = _conta(db, **({"bot_meuplano": True, "bot_meuguarda": True, "meuguarda_liberado": True} | bot))
    _localizacao(u.telefone)
    return ger.Contexto(db=db, user=u, telefone=u.telefone)


def _localizacao(tel):
    local._RECEBIDAS.clear()
    local.guardar(tel, {"midia": {"lat": LAT, "lng": LNG, "nome": "", "endereco": ""}})


class _MeuPlano:
    def __init__(self):
        self.previa = {"achados": [{"node_id": 51, "nome": "Inversor 03", "tipo": "inversor", "tipo_rotulo": "Inversor",
                                    "local": "Skid 1", "equipment_id": 510, "no_mapa": {"lat": -22.1235, "lng": -47.7655},
                                    "desenhado_como": None}], "parecidos": []}
        self.marcados, self.fotos = [], []
        self.usinas_ = [{"id": 4, "name": "UFV PEREIRAS", "latitude": -22.1230, "longitude": -47.7650}]

    async def permissoes(self):
        return {local.PERMISSAO}

    async def usinas(self):
        return self.usinas_

    async def ponto_no_mapa_previa(self, usina_id, nome):
        return self.previa

    async def equipamento_pelo_nome(self, usina_id, nome):
        return self.previa

    async def marcar_no_mapa(self, usina_id, node_id, lat, lng, novo_nome=None, apelido=None):
        self.marcados.append((usina_id, node_id, lat, lng, novo_nome, apelido))
        return {"ok": True, "avisos": []}

    async def foto_no_equipamento(self, eid, nome, conteudo, tipo, legenda):
        self.fotos.append((eid, nome, conteudo, tipo, legenda))
        return {"id": 1}


@pytest.fixture
def meuplano(monkeypatch):
    falso = _MeuPlano()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: falso)
    return falso


async def test_a_camera_vai_ao_mapa_unico_e_o_nome_dito_corrige_o_cadastro(db, meuplano):
    """O dono, 18/11/2026: "câmera 1" não existe → o bot mostra os nomes e corrige; a posição vai ao mapa único (o
    meuGuarda só consome)."""
    ctx = _ctx(db)
    meuplano.previa = {"achados": [], "parecidos": [
        {"node_id": 71, "nome": "Perímetro 01", "tipo": "camera", "tipo_rotulo": "Câmera", "local": "Poste 1"},
        {"node_id": 72, "nome": "Térmica 01", "tipo": "camera", "tipo_rotulo": "Câmera", "local": "Poste 2"}]}
    r = await campo.posicionar_equipamento(ctx, {"usina": "pereiras", "equipamento": "câmera 1"})
    assert r["nomes_no_meuplano"] == [{"node_id": 71, "nome": "Perímetro 01", "local": "Poste 1"},
                                      {"node_id": 72, "nome": "Térmica 01", "local": "Poste 2"}]
    assert "`apelido`" in r["como_seguir"] and "nunca se renomeia" in r["como_seguir"] and ctx.proposta is None
    # o nome da câmera é do meuGuarda (o dono, 18/11/2026): mesmo pedido como "renomear", o nome dito vira APELIDO
    r = await campo.posicionar_equipamento(ctx, {"usina": "pereiras", "equipamento": "câmera 1", "node_id": 71,
                                                 "renomear_para": "câmera 1"})
    p = ctx.proposta
    assert r["proposta_pendente"] == "Marcar Perímetro 01 (Câmera) de UFV PEREIRAS no mapa da usina"
    assert p.parte == "bot_meuplano" and p.detalhes[0] == "Apelido: 'câmera 1' (o nome 'Perímetro 01' fica)"
    feito = await helper._rodar(p, db, ctx.user, ctx.telefone)
    assert meuplano.marcados == [(4, 71, LAT, LNG, None, "câmera 1")] and feito.startswith("✅ Perímetro 01 marcado")
    assert local.recebida(ctx.telefone) is None                         # a localização foi usada


async def test_sem_localizacao_e_a_localizacao_longe_da_usina_nao_gravam(db, meuplano):
    ctx = _ctx(db)
    local._RECEBIDAS.clear()
    assert "localização" in (await campo.posicionar_equipamento(ctx, {"usina": "pereiras", "equipamento": "x"}))["erro"]
    _localizacao(ctx.telefone)
    meuplano.usinas_[0].update(latitude=-22.30, longitude=-47.76)      # a ~20 km: a do posto, não a do equipamento
    r = await campo.posicionar_equipamento(ctx, {"usina": "pereiras", "equipamento": "inversor 3"})
    assert "da usina UFV PEREIRAS: não é a do equipamento" in r["erro"] and ctx.proposta is None and not meuplano.marcados


async def test_o_equipamento_vai_ao_mapa_da_usina(db, meuplano):
    ctx = _ctx(db)
    r = await campo.posicionar_equipamento(ctx, {"usina": "pereiras", "equipamento": "inversor 3"})
    p = ctx.proposta
    assert r["proposta_pendente"] == "Marcar Inversor 03 (Inversor) de UFV PEREIRAS no mapa da usina"
    assert p.parte == "bot_meuplano" and p.detalhes[0].startswith("Hoje no mapa:")
    feito = await helper._rodar(p, db, ctx.user, ctx.telefone)
    assert meuplano.marcados == [(4, 51, LAT, LNG, None, None)] and feito.startswith("✅ Inversor 03 marcado no mapa")
    # desenhado como área: não é substituído; sem o nome: os parecidos voltam
    meuplano.previa["achados"][0]["desenhado_como"] = "Polygon"
    ctx2 = _ctx(db)
    assert "desenhado" in (await campo.posicionar_equipamento(ctx2, {"usina": "pereiras", "equipamento": "inversor 3"}))["erro"]
    meuplano.previa = {"achados": [], "parecidos": [{"node_id": 1, "nome": "Inversor 01", "local": "Skid 1"}]}
    r = await campo.posicionar_equipamento(ctx2, {"usina": "pereiras", "equipamento": "inversor 9"})
    assert r["nomes_no_meuplano"] == [{"node_id": 1, "nome": "Inversor 01", "local": "Skid 1"}] and ctx2.proposta is None


async def test_a_plaqueta_e_lida_pela_ia_com_visao(db, monkeypatch):
    ctx = _ctx(db)
    fotos._RECEBIDAS[ctx.telefone] = [{"id": "m1", "legenda": "plaqueta do DJ geral", "em": __import__("time").monotonic(),
                              "video": False}]

    async def baixar(mid):
        assert mid == "m1"
        return b"\xff\xd8jpeg", "image/jpeg"
    vistas = []

    async def _llm(msgs, ferramentas, teto_s=None):
        vistas.append(msgs[0]["content"])
        return {"content": json.dumps([{"foto": 1, "legivel": True, "equipamento": "disjuntor", "fabricante": "Schneider",
                                         "modelo": "NSX630", "serie": "AB123", "dados": {"In": "630 A"}}])}
    monkeypatch.setattr(campo.whatsapp, "baixar_midia", baixar)
    monkeypatch.setattr(assistente, "_llm", _llm)
    r = await campo.ler_plaqueta(ctx, {"o_que_e": "DJ geral"})
    assert r["leitura"][0]["modelo"] == "NSX630" and "manutencao" in r["como_seguir"]
    partes = vistas[0]
    assert partes[1]["image_url"]["url"].startswith("data:image/jpeg;base64,") and "DJ geral" in partes[0]["text"]
    assert "plaqueta do DJ geral" in partes[0]["text"]

    async def torta(msgs, ferramentas, teto_s=None):
        return {"content": "não consegui"}
    monkeypatch.setattr(assistente, "_llm", torta)
    assert "Não consegui ler" in (await campo.ler_plaqueta(ctx, {}))["erro"]


async def test_a_foto_vai_para_a_ficha_do_equipamento(db, meuplano, monkeypatch):
    ctx = _ctx(db)
    agora = __import__("time").monotonic()
    fotos._RECEBIDAS[ctx.telefone] = [{"id": "m1", "legenda": "", "em": agora, "video": False},
                             {"id": "m2", "legenda": "etiqueta", "em": agora, "video": False}]

    async def baixar(mid):
        return mid.encode(), "image/jpeg"
    monkeypatch.setattr(campo.whatsapp, "baixar_midia", baixar)
    r = await campo.fotos_no_equipamento(ctx, {"usina": "pereiras", "equipamento": "inversor 3"})
    assert r["proposta_pendente"] == "Guardar 2 foto(s) na ficha de Inversor 03 (UFV PEREIRAS)"
    feito = await helper._rodar(ctx.proposta, db, ctx.user, ctx.telefone)
    assert feito == "✅ 2 foto(s) guardada(s) na ficha de Inversor 03."
    assert [(f[0], f[2], f[4]) for f in meuplano.fotos] == [(510, b"m1", "Foto enviada pelo WhatsApp"), (510, b"m2", "etiqueta")]
    assert fotos.recebidas(ctx.telefone) == []


def test_quem_recebe_as_ferramentas_e_o_roteamento(db):
    com_mp = _conta(db, bot_meuplano=True)
    assert set(campo.FERRAMENTAS) <= set(assistente.permitidas(com_mp))
    so_cameras = _conta(db, bot_meuguarda=True, meuguarda_liberado=True)
    assert not set(campo.FERRAMENTAS) & set(assistente.permitidas(so_cameras))   # o cadastro e o mapa são do meuPlano
    texto = assistente._sistema(ger.Contexto(db=db, user=com_mp, telefone=com_mp.telefone))
    assert "CADASTRO e REDE em campo" in texto and "`posicionar_equipamento`" in texto and "`ler_plaqueta`" in texto
    assert "mapa único da usina, a câmera inclusive" in texto
    assert "INTEIRA" in assistente._MANUTENCAO["function"]["description"]
