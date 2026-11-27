"""oem-gs › Usinas › Equipamentos: a sugestão de qual nó do meuPlano é qual dispositivo (pelo número, pela ordem, só
dentro do transformador cujo nó se sabe, sem os tipos que não são candidatos) e as duas rotas do gerente: a tela (os
dispositivos em árvore, os candidatos lidos do meuPlano, a sugestão que nunca se aplica sozinha, o meuPlano fora) e o
salvar (um nó é uma posição só, a troca num pedido, o nó nulo, o nó conferido contra o meuPlano, o histórico com quem)."""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import empresa_dispositivos as rotas
from app.core.db import get_db
from app.main import app
from app.models.empresa import Empresa
from app.models.plant import DeviceLink, HistoricoDaUsina, PlantLink
from app.models.user import Perfil, User
from app.services import sugestao_de_nos as sug


def _no(id_, tipo, codigo, nome, pai=None, ordem=0, caminho=None):
    return {"id": id_, "parent_id": pai, "type_code": tipo, "code": codigo, "display_name": nome,
            "path": caminho or f"Pereiras > {nome}", "display_order": ordem, "node_kind": "PONTO_FUNCIONAL"}


def _arvore():
    """Dois skids, como Pereiras: cada um com o trafo, um trafo auxiliar e os inversores numa pasta."""
    nos = [_no(1, "usina", "PER", "Pereiras", caminho="Pereiras")]
    for s, base in ((1, 100), (2, 200)):
        nos += [_no(base, "skid", f"SK-{s}", f"Skid {s}", pai=1, ordem=s, caminho=f"Pereiras > Skid {s}"),
                _no(base + 1, "transformador_potencia", f"TR-S{s}", f"Trafo do Skid {s}", pai=base, ordem=1,
                    caminho=f"Pereiras > Skid {s} > Trafo do Skid {s}"),
                _no(base + 2, "transformador_auxiliar", f"TA-S{s}", f"Trafo auxiliar {s}", pai=base, ordem=2),
                _no(base + 3, "grupo", f"INVS-S{s}", "Inversores", pai=base, ordem=3),
                _no(base + 9, "abrigo_inversor", f"AB-S{s}", f"Abrigo {s}", pai=base + 3, ordem=9),
                _no(base + 8, "inversor_hibrido", f"IH-S{s}", f"Híbrido {s}", pai=base + 3, ordem=8)]
        nos += [_no(base + 10 + i, "inversor", f"INV-S{s}-0{i}", f"Inversor S{s}-0{i}", pai=base + 3, ordem=i,
                    caminho=f"Pereiras > Skid {s} > Inversores > Inversor S{s}-0{i}") for i in (1, 2, 3)]
    return nos


def _d(gd, tipo, nome, pai=None, node_id=None, ativo=True):
    return {"gd": gd, "tipo": tipo, "nome": nome, "pai": pai, "ativo": ativo, "node_id": node_id}


def _dispositivos():
    return [_d(1, "transformador", "TR-01"), _d(2, "transformador", "TR-02"),
            _d(11, "inversor", "INV12", 1), _d(12, "inversor", "INV16", 1), _d(13, "inversor", "INV14", 1),
            _d(21, "inversor", "INV01", 2), _d(22, "inversor", "INV03", 2), _d(23, "inversor", "INV02", 2)]


# --------------------------------------------------------------------------- a sugestão (funções puras)
def test_so_os_tipos_candidatos_entram_e_na_ordem_da_arvore():
    nos = _arvore()
    assert [n["id"] for n in sug.candidatos(nos, "transformador")] == [101, 201]         # o auxiliar não
    assert [n["id"] for n in sug.candidatos(nos, "inversor")] == [111, 211, 112, 212, 113, 213]   # híbrido e abrigo não
    assert sug.candidatos(nos, "string") == []
    assert (sug.numero("TR-01"), sug.numero("INV-S1-01"), sug.numero(None, "Skid 2"), sug.numero("Trafo")) == (1, 1, 2, None)


def test_trafos_pelo_numero_e_inversores_pelo_numero_ou_pela_ordem():
    s = sug.sugerir(_dispositivos(), _arvore())
    # os transformadores: "TR-01" e "TR-S1" têm o mesmo número
    assert (s[1], s[2]) == ({"node_id": 101, "base": "numero", "motivo": "pelo número"},
                            {"node_id": 201, "base": "numero", "motivo": "pelo número"})
    # os inversores do TR-01 (12, 16, 14) não têm os números dos nós (1, 2, 3): pela ordem, dentro do skid do trafo
    assert [(gd, s[gd]["node_id"], s[gd]["base"]) for gd in (11, 12, 13)] == [
        (11, 111, "ordem"), (12, 112, "ordem"), (13, 113, "ordem")]
    assert s[11]["motivo"] == "pela ordem, entre os inversores de TR-01"
    # os do TR-02 (1, 3, 2) têm: pelo número, e não pela ordem do GS
    assert [(gd, s[gd]["node_id"], s[gd]["base"]) for gd in (21, 22, 23)] == [
        (21, 211, "numero"), (22, 213, "numero"), (23, 212, "numero")]


def test_quantidades_diferentes_nao_tem_sugestao():
    nos = [n for n in _arvore() if n["id"] != 113]         # o skid 1 tem só dois nós de inversor para três dispositivos
    s = sug.sugerir(_dispositivos(), nos)
    assert {1, 2, 21, 22, 23} == set(s)                    # o grupo do TR-01 fica sem sugestão; o resto, não
    s = sug.sugerir(_dispositivos()[:1] + _dispositivos()[2:], _arvore())     # um transformador para dois nós
    assert s == {}                                         # sem o trafo, os inversores também não têm onde procurar


def test_trafos_pela_ordem_quando_os_numeros_nao_batem():
    disp = [_d(5, "transformador", "Trafo Norte"), _d(3, "transformador", "Trafo Sul")]
    s = sug.sugerir(disp, _arvore())
    assert (s[3], s[5]) == ({"node_id": 101, "base": "ordem", "motivo": "pela ordem"},
                            {"node_id": 201, "base": "ordem", "motivo": "pela ordem"})          # pelo número do GS
    disp = [_d(1, "transformador", "TR-01"), _d(2, "transformador", "TR-01 B")]                # o número repetido
    assert {gd: x["base"] for gd, x in sug.sugerir(disp, _arvore()).items()} == {1: "ordem", 2: "ordem"}


def test_inversores_so_debaixo_do_trafo_cujo_no_se_sabe():
    disp = _dispositivos()
    disp[0]["node_id"] = 201                               # o gerente confirmou o TR-01 no nó do Skid 2
    s = sug.sugerir(disp, _arvore())
    assert s[2] == {"node_id": 101, "base": "ordem", "motivo": "pela ordem"}       # sobrou um para um: o outro nó
    assert 1 not in s                                      # o confirmado não ganha sugestão
    assert [s[gd]["node_id"] for gd in (11, 12, 13)] == [211, 212, 213]            # os do TR-01 vêm do Skid 2
    assert [s[gd]["node_id"] for gd in (21, 22, 23)] == [111, 113, 112]
    # o nó já confirmado sai dos candidatos, e o inversor que já tem nó não ganha sugestão
    disp = _dispositivos()
    disp[2]["node_id"] = 113
    s = sug.sugerir(disp, _arvore())
    assert 11 not in s and [s[gd]["node_id"] for gd in (12, 13)] == [111, 112]
    # o ausente não entra na conta; o inversor sem pai não tem grupo
    disp = _dispositivos() + [_d(31, "inversor", "INV99"), _d(32, "inversor", "INV04", 2, ativo=False)]
    s = sug.sugerir(disp, _arvore())
    assert 31 not in s and 32 not in s and len(s) == 8


def test_um_lugar_com_dois_trafos_nao_e_grupo_de_nenhum():
    nos = [_no(1, "usina", "U", "Usina", caminho="Usina"),
           _no(2, "transformador_potencia", "TR-1", "Trafo 1", pai=1, ordem=1),
           _no(3, "transformador_potencia", "TR-2", "Trafo 2", pai=1, ordem=2),
           _no(4, "inversor", "INV-1", "Inversor 1", pai=1, ordem=3), _no(5, "inversor", "INV-2", "Inversor 2", pai=1, ordem=4)]
    disp = [_d(1, "transformador", "TR-01"), _d(2, "transformador", "TR-02"), _d(3, "inversor", "INV1", 1),
            _d(4, "inversor", "INV2", 2)]
    assert set(sug.sugerir(disp, nos)) == {1, 2}           # os trafos sim; os inversores estão debaixo dos dois
    s = sug.sugerir(disp[:1] + disp[2:3], [n for n in nos if n["id"] not in (3, 5)])   # um trafo só, no topo: é dele
    assert s[3] == {"node_id": 4, "base": "numero", "motivo": "pelo número, entre os inversores de TR-01"}


# --------------------------------------------------------------------------- as rotas do gerente
@pytest.fixture
def c(db, monkeypatch):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    per = PlantLink(nome="Pereiras", empresa_id=a.id, mw_plant_slug="pereiras", mp_usina_id=7)
    so_mw = PlantLink(nome="Só no meuWatt", empresa_id=a.id, mw_plant_slug="so-mw")
    de_b = PlantLink(nome="Da Outra", empresa_id=b.id, mw_plant_slug="da-outra", mp_usina_id=9)
    g = User(apelido="gerente.a", nome="Gerente A", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id)
    g_b = User(apelido="gerente.b", nome="Gerente B", perfil=Perfil.GESTOR_EMPRESA, empresa_id=b.id)
    db.add_all([per, so_mw, de_b, g, g_b])
    db.commit()
    tr1 = DeviceLink(plant_link_id=per.id, tipo="transformador", nome="TR-01", mw_ref="trafo:41")
    tr2 = DeviceLink(plant_link_id=per.id, tipo="transformador", nome="TR-02", mw_ref="trafo:42")
    db.add_all([tr1, tr2])
    db.commit()
    invs = [DeviceLink(plant_link_id=per.id, tipo="inversor", nome=nome, mw_ref=f"inv:{90 + i}", pai_id=pai.id)
            for i, (nome, pai) in enumerate((("INV12", tr1), ("INV16", tr1), ("INV14", tr1), ("INV01", tr2),
                                             ("INV03", tr2), ("INV02", tr2)))]
    fora = DeviceLink(plant_link_id=per.id, tipo="inversor", nome="INV99", mw_ref="inv:99", pai_id=tr1.id, ativo=False)
    da_outra = DeviceLink(plant_link_id=de_b.id, tipo="inversor", nome="INV01", mw_ref="inv:500")
    db.add_all([*invs, fora, da_outra])
    db.commit()
    estado = {"nos": _arvore(), "erro": None, "pedidos": []}

    class Mp:
        async def nos_da_usina(self, usina_id):
            estado["pedidos"].append(usina_id)
            if estado["erro"]:
                raise estado["erro"]
            return estado["nos"]

    async def cliente(db_, empresa_id):
        if empresa_id != a.id:
            raise RuntimeError("Esta empresa ainda não conectou a conta dela no meuPlano (oem-gs → Conexões).")
        return Mp()
    monkeypatch.setattr(rotas.integracoes, "cliente_meuplano", cliente)
    return dict(per=per, so_mw=so_mw, de_b=de_b, g=g, g_b=g_b, tr1=tr1, tr2=tr2, invs=invs, fora=fora,
                da_outra=da_outra, estado=estado)


def _ver(db, c, usina=None, quem=None):
    return asyncio.run(rotas.equipamentos_da_usina((usina or c["per"]).id, db, quem or c["g"]))


def _gravar(db, c, *pares, usina=None, quem=None):
    corpo = rotas.NosIn(nos=[{"gd": getattr(d, "id", d), "node_id": n} for d, n in pares])
    return asyncio.run(rotas.gravar_nos_da_usina((usina or c["per"]).id, corpo, db, quem or c["g"]))


def _todos(out):
    for d in out.dispositivos:
        yield d
        yield from d.filhos


def _nos(out) -> dict:
    return {d.nome: d.no.id if d.no else None for d in _todos(out)}


def test_a_tela_traz_a_arvore_os_candidatos_e_a_sugestao_sem_gravar_nada(db, c):
    out = _ver(db, c)
    assert (out.usina_codigo, out.usina_nome, out.meuplano_lido, out.aviso) == (f"GS-{c['per'].id:04d}", "Pereiras",
                                                                               True, None)
    assert (out.ligados, out.total) == (0, 9)
    assert [(d.nome, d.codigo, d.tipo_rotulo, [f.nome for f in d.filhos]) for d in out.dispositivos] == [
        ("TR-01", f"GD-{c['tr1'].id:06d}", "Transformador", ["INV12", "INV16", "INV14", "INV99"]),
        ("TR-02", f"GD-{c['tr2'].id:06d}", "Transformador", ["INV01", "INV03", "INV02"])]
    por_nome = {d.nome: d for d in _todos(out)}
    assert por_nome["TR-01"].sugestao.model_dump() == {"node_id": 101, "base": "numero", "motivo": "pelo número"}
    assert (por_nome["INV12"].sugestao.node_id, por_nome["INV12"].sugestao.base) == (111, "ordem")
    assert (por_nome["INV03"].sugestao.node_id, por_nome["INV03"].sugestao.base) == (213, "numero")
    assert por_nome["INV99"].ativo is False and por_nome["INV99"].sugestao is None       # o ausente: marcado, sem palpite
    assert [x.id for x in out.candidatos["transformador"]] == [101, 201]
    assert out.candidatos["inversor"][0].model_dump() == {
        "id": 111, "codigo": "INV-S1-01", "nome": "Inversor S1-01", "local": "Skid 1 > Inversores",
        "rotulo": "Inversor S1-01 · INV-S1-01 · Skid 1 > Inversores"}
    assert c["estado"]["pedidos"] == [7]                   # lido com o número da usina NO meuPlano
    assert db.query(DeviceLink).filter(DeviceLink.mp_node_id.isnot(None)).count() == 0   # a sugestão não se aplica só
    assert db.query(HistoricoDaUsina).count() == 0


def test_as_strings_so_entram_na_contagem(db, c):
    """A tela é dos transformadores e dos inversores: as strings (centenas por usina) não viram lista."""
    inv = c["invs"][0]
    db.add_all([DeviceLink(plant_link_id=c["per"].id, tipo="string", nome=f"String {n}", mw_ref=f"str:90:{n}",
                           pai_id=inv.id, ativo=n != 9) for n in (1, 2, 7, 9)])
    db.commit()
    out = _ver(db, c)
    assert (out.strings, out.strings_ligadas, out.ligados, out.total) == (3, 0, 0, 9)   # a ausente não conta
    assert {d.tipo for d in _todos(out)} == {"transformador", "inversor"}
    inv12 = next(d for d in _todos(out) if d.nome == "INV12")
    assert (inv12.filhos, inv12.strings, inv12.strings_ligadas) == ([], 3, 0)
    assert all((d.strings, d.strings_ligadas) == (0, 0) for d in _todos(out) if d.nome != "INV12")
    assert set(out.candidatos) == {"transformador", "inversor", "rele", "estacao", "medidor_ssu", "gateway"}
    # a rotina do meuPlano ligou duas (e a ausente, que não entra na conta): a conta vem do índice, sem ler o meuPlano
    for ref, no in (("str:90:1", 9001), ("str:90:7", 9007), ("str:90:9", 9009)):
        db.query(DeviceLink).filter_by(mw_ref=ref).one().mp_node_id = no
    db.commit()
    c["estado"]["erro"] = ConnectionError("fora")
    out = _ver(db, c)
    inv12 = next(d for d in _todos(out) if d.nome == "INV12")
    assert (out.strings, out.strings_ligadas, inv12.strings, inv12.strings_ligadas) == (3, 2, 3, 2)
    assert (out.ligados, out.total) == (0, 9)             # o "x de y ligados" segue sendo dos trafos e inversores
    c["estado"]["erro"] = None
    out = _gravar(db, c, (c["tr1"], 101))
    assert (out.strings, out.strings_ligadas, out.ligados, out.total) == (3, 2, 1, 9)
    # a pessoa não liga nem desliga string por aqui
    s = db.query(DeviceLink).filter_by(mw_ref="str:90:1").one()
    for no in (111, None):
        with pytest.raises(HTTPException) as e:
            _gravar(db, c, (c["tr2"], 201), (s, no))
        assert e.value.status_code == 400 and "As strings não se ligam aqui" in e.value.detail
    db.expire_all()
    assert s.mp_node_id == 9001 and c["tr2"].mp_node_id is None


def test_reles_estacoes_e_medidores_vem_em_grupos(db, c):
    per, tr1 = c["per"], c["tr1"]
    antes = _ver(db, c)
    assert antes.grupos == []                              # sem nenhum, a tela é a de sempre
    db.add_all([DeviceLink(plant_link_id=per.id, tipo="rele", nome="Relé do TR-01", mw_ref="rele:5", pai_id=tr1.id,
                           mp_node_id=101),
                DeviceLink(plant_link_id=per.id, tipo="rele", nome="Relé geral", mw_ref="rele:6", ativo=False),
                DeviceLink(plant_link_id=per.id, tipo="estacao", nome="Estação 1", mw_ref="est:3", mp_node_id=70000),
                DeviceLink(plant_link_id=per.id, tipo="medidor_ssu", nome="Fronteira", mw_ref="ssu:9")])
    db.commit()
    out = _ver(db, c)
    assert [(g.tipo, g.titulo, [(i.nome, i.ativo, i.debaixo_de, i.no.model_dump() if i.no else None) for i in g.itens])
            for g in out.grupos] == [
        ("rele", "Relés de proteção", [("Relé do TR-01", True, "TR-01", {"id": 101, "rotulo": "Trafo do Skid 1 · TR-S1 · Skid 1"}),
                                       ("Relé geral", False, None, None)]),
        ("estacao", "Estações meteorológicas", [("Estação 1", True, None, {"id": 70000, "rotulo": None})]),
        ("medidor_ssu", "Medidores da fronteira", [("Fronteira", True, None, None)])]
    assert out.grupos[0].itens[0].codigo.startswith("GD-")
    # as linhas de transformador e inversor, a conta de ligados e a das strings não mudam com eles
    assert (out.dispositivos, out.candidatos, out.total, out.strings) == (antes.dispositivos, antes.candidatos, 9, 0)
    assert out.ligados == antes.ligados == 0


def test_a_pessoa_liga_o_no_do_rele_da_estacao_e_do_medidor(db, c):
    """São poucos e não há regra segura para casar sozinho: a pessoa escolhe o nó, com a regra de sempre."""
    per, tr1 = c["per"], c["tr1"]
    c["estado"]["nos"] = _arvore() + [
        _no(301, "rele_protecao", "RP-1", "Relé de proteção", pai=100, ordem=1, caminho="Pereiras > Skid 1 > Relé de proteção"),
        _no(302, "rele_temperatura", "RT-1", "Relé de temperatura", pai=100, ordem=2,
            caminho="Pereiras > Skid 1 > Relé de temperatura"),
        _no(303, "rele_temperatura", "RT-2", "Relé de temperatura", pai=200, ordem=2,
            caminho="Pereiras > Skid 2 > Relé de temperatura"),
        _no(311, "estação solarimétrica", "EST-1", "Estação solarimétrica", pai=1, ordem=5),
        _no(312, "piranometro", "PIR-1", "Piranômetro", pai=311, ordem=1, caminho="Pereiras > Estação solarimétrica > Piranômetro"),
        _no(313, "datalogger", "DL-1", "Datalogger", pai=311, ordem=2),
        _no(321, "medidor_energia", "MED-1", "Medidor da fronteira", pai=1, ordem=6),
        _no(341, "gateway", "GW-1", "Gateway", pai=100, ordem=8, caminho="Pereiras > Skid 1 > Gateway"),
        _no(342, "gateway", "GW-2", "Gateway", pai=200, ordem=8, caminho="Pereiras > Skid 2 > Gateway"),
        _no(343, "gateway_io", "GIO-1", "Gateway de I/O", pai=100, ordem=9),
        _no(331, "rele", "RX", "Relé de outro tipo", pai=1, ordem=7)]
    rele = DeviceLink(plant_link_id=per.id, tipo="rele", nome="Relé do TR-01", mw_ref="rele:5", pai_id=tr1.id)
    geral = DeviceLink(plant_link_id=per.id, tipo="rele", nome="Relé geral", mw_ref="rele:6", ativo=False)
    est = DeviceLink(plant_link_id=per.id, tipo="estacao", nome="Estação 1", mw_ref="est:3")
    ssu = DeviceLink(plant_link_id=per.id, tipo="medidor_ssu", nome="Fronteira", mw_ref="ssu:9")
    s = DeviceLink(plant_link_id=per.id, tipo="string", nome="String 1", mw_ref="str:90:1", pai_id=c["invs"][0].id)
    gw = DeviceLink(plant_link_id=per.id, tipo="gateway", nome="ABS Skid 1", mw_ref="gw:7")
    db.add_all([rele, geral, est, ssu, s, gw])
    db.commit()
    out = _ver(db, c)
    # os candidatos de cada tipo, pelo tipo do nó no meuPlano, com o lugar no rótulo (há nós de mesmo nome)
    assert {t: [x.id for x in lista] for t, lista in out.candidatos.items()} == {
        "transformador": [101, 201], "inversor": [111, 211, 112, 212, 113, 213], "rele": [301, 302, 303],
        "estacao": [312, 313, 311], "medidor_ssu": [321], "gateway": [341, 342]}
    assert [x.rotulo for x in out.candidatos["gateway"]] == ["Gateway · GW-1 · Skid 1", "Gateway · GW-2 · Skid 2"]
    assert [(g.tipo, g.titulo) for g in out.grupos][-1] == ("gateway", "Gateways")      # o quarto grupo, por último
    assert [x.rotulo for x in out.candidatos["rele"]] == [
        "Relé de proteção · RP-1 · Skid 1", "Relé de temperatura · RT-1 · Skid 1", "Relé de temperatura · RT-2 · Skid 2"]
    assert all(i.no is None for g in out.grupos for i in g.itens)       # nada é ligado sozinho, e não há sugestão
    # liga os quatro num salvar (o ausente também), com o histórico de quem fez
    out = _gravar(db, c, (rele, 302), (geral, 301), (est, 311), (ssu, 321), (tr1, 101))
    assert out.grupos[-1].itens[0].no is None              # o gateway não veio no pedido: fica como está
    assert {i.nome: i.no.model_dump() for g in out.grupos[:-1] for i in g.itens} == {
        "Relé do TR-01": {"id": 302, "rotulo": "Relé de temperatura · RT-1 · Skid 1"},
        "Relé geral": {"id": 301, "rotulo": "Relé de proteção · RP-1 · Skid 1"},
        "Estação 1": {"id": 311, "rotulo": "Estação solarimétrica · EST-1"},
        "Fronteira": {"id": 321, "rotulo": "Medidor da fronteira · MED-1"}}
    assert (out.ligados, out.total) == (1, 9)              # a conta do alto segue sendo dos trafos e inversores
    linhas = [(h.campo, h.antes, h.depois, h.por_id) for h in db.query(HistoricoDaUsina).order_by(HistoricoDaUsina.id)]
    assert len(linhas) == 5 and linhas[0] == (
        "no_do_dispositivo", f"GD-{rele.id:06d} Relé do TR-01: sem nó",
        f"GD-{rele.id:06d} Relé do TR-01: nó 302 (Relé de temperatura)", c["g"].id)
    # a troca num salvar, e o nó nulo desliga; o que não veio fica
    out = _gravar(db, c, (rele, 301), (geral, 302), (ssu, None), (gw, 342))
    assert {i.nome: i.no.id if i.no else None for g in out.grupos for i in g.itens} == {
        "Relé do TR-01": 301, "Relé geral": 302, "Estação 1": 311, "Fronteira": None, "ABS Skid 1": 342}
    assert out.grupos[-1].itens[0].no.rotulo == "Gateway · GW-2 · Skid 2"
    for pares, codigo_http, frase in (
            ([(rele, 302)], 409, f"O nó 302 já está no equipamento GD-{geral.id:06d}"),     # um nó é uma posição só
            ([(ssu, 311)], 400, "não é um medidor de energia desta usina"),               # o nó da estação
            ([(rele, 331)], 400, "não é um relé desta usina"),                            # o tipo que não é candidato
            ([(rele, 111)], 400, "não é um relé desta usina"),                            # um nó de inversor
            ([(est, 9999)], 400, "não é uma estação desta usina"),
            ([(gw, 343)], 400, "não é um gateway desta usina"),                           # o gateway de I/O é outro tipo
            ([(gw, 301)], 400, "não é um gateway desta usina"),
            ([(c["invs"][0], 303)], 400, "não é um inversor desta usina"),                # e o inversor não pega relé
            ([(est, 313), (s, 111)], 400, "As strings não se ligam aqui")):               # a string segue de fora
        with pytest.raises(HTTPException) as e:
            _gravar(db, c, *pares)
        assert e.value.status_code == codigo_http and frase in e.value.detail, (pares, e.value.detail)
    db.expire_all()
    assert (rele.mp_node_id, est.mp_node_id, ssu.mp_node_id, s.mp_node_id, gw.mp_node_id) == (301, 311, None, None, 342)
    # sem o meuPlano, desligar pode; ligar, não
    c["estado"]["erro"] = ConnectionError("fora")
    with pytest.raises(HTTPException) as e:
        _gravar(db, c, (ssu, 321))
    assert e.value.status_code == 502
    assert _gravar(db, c, (est, None)).grupos[1].itens[0].no is None


def test_sem_o_meuplano_os_dispositivos_vem_assim_mesmo(db, c):
    c["invs"][0].mp_node_id = 111
    db.commit()
    c["estado"]["erro"] = RuntimeError("timeout")
    for erro, frase in ((ConnectionError("fora"), "não respondeu"), (ValueError("x"), "não respondeu")):
        c["estado"]["erro"] = erro
        out = _ver(db, c)
        assert out.meuplano_lido is False and frase in out.aviso and out.total == 9 and out.ligados == 1
        assert out.candidatos == dict.fromkeys(("transformador", "inversor", "rele", "estacao", "medidor_ssu", "gateway"), [])
        assert all(d.sugestao is None for d in _todos(out))
        assert next(d for d in _todos(out) if d.nome == "INV12").no.model_dump() == {"id": 111, "rotulo": None}
    out = _ver(db, c, usina=c["so_mw"])                    # a usina que não está no meuPlano: nem pergunta
    assert out.meuplano_lido is False and "não está ligada ao meuPlano" in out.aviso and out.total == 0
    out = _ver(db, c, usina=c["de_b"], quem=c["g_b"])      # a empresa sem a conta do meuPlano: a frase de Conexões
    assert out.meuplano_lido is False and "Conexões" in out.aviso and out.total == 1
    # sem o meuPlano, desligar pode (não há o que conferir); ligar, não
    assert _nos(_gravar(db, c, (c["invs"][0], None)))["INV12"] is None
    c["estado"]["erro"] = ConnectionError("fora")
    with pytest.raises(HTTPException) as e:
        _gravar(db, c, (c["invs"][0], 111))
    assert e.value.status_code == 502 and "Nada foi gravado" in e.value.detail


def test_salvar_grava_so_o_que_veio_com_quem_fez_no_historico(db, c):
    tr1, tr2, invs = c["tr1"], c["tr2"], c["invs"]
    out = _gravar(db, c, (tr1, 101), (invs[0], 111), (invs[1], 112))
    assert (out.ligados, out.total) == (3, 9)
    assert _nos(out) == {"TR-01": 101, "TR-02": None, "INV12": 111, "INV16": 112, "INV14": None, "INV99": None,
                         "INV01": None, "INV03": None, "INV02": None}
    por_nome = {d.nome: d for d in _todos(out)}
    assert por_nome["TR-01"].no.rotulo == "Trafo do Skid 1 · TR-S1 · Skid 1" and por_nome["TR-01"].sugestao is None
    assert por_nome["INV14"].sugestao.node_id == 113       # o que sobrou do grupo
    linhas = [(h.campo, h.antes, h.depois, h.por_id, h.sistema) for h in
              db.query(HistoricoDaUsina).filter_by(plant_link_id=c["per"].id).order_by(HistoricoDaUsina.id)]
    assert linhas == [
        ("no_do_dispositivo", f"GD-{tr1.id:06d} TR-01: sem nó", f"GD-{tr1.id:06d} TR-01: nó 101 (Trafo do Skid 1)",
         c["g"].id, "gs"),
        ("no_do_dispositivo", f"GD-{invs[0].id:06d} INV12: sem nó",
         f"GD-{invs[0].id:06d} INV12: nó 111 (Inversor S1-01)", c["g"].id, "gs"),
        ("no_do_dispositivo", f"GD-{invs[1].id:06d} INV16: sem nó",
         f"GD-{invs[1].id:06d} INV16: nó 112 (Inversor S1-02)", c["g"].id, "gs")]
    # o mesmo de novo não muda nada e não escreve histórico; o que não veio fica
    marcas = {x.id: x.atualizado_em for x in db.query(DeviceLink)}
    _gravar(db, c, (tr1, 101), (invs[0], 111))
    db.expire_all()
    assert {x.id: x.atualizado_em for x in db.query(DeviceLink)} == marcas and db.query(HistoricoDaUsina).count() == 3
    # a troca num pedido só, e o nó nulo desliga
    out = _gravar(db, c, (invs[0], 112), (invs[1], 111), (tr1, None))
    assert (_nos(out)["INV12"], _nos(out)["INV16"], _nos(out)["TR-01"]) == (112, 111, None)
    assert db.query(HistoricoDaUsina).count() == 6
    ultimo = db.query(HistoricoDaUsina).order_by(HistoricoDaUsina.id.desc()).first()
    assert ultimo.depois.endswith("TR-01: sem nó") and ultimo.antes.endswith("nó 101 (Trafo do Skid 1)")
    assert tr2.mp_node_id is None and c["per"].mp_usina_id == 7


def test_um_no_e_uma_posicao_so_e_o_no_tem_de_ser_do_tipo_e_da_usina(db, c):
    tr1, invs = c["tr1"], c["invs"]
    _gravar(db, c, (invs[0], 111))
    for pares, codigo_http, frase in (
            ([(invs[1], 111)], 409, f"O nó 111 já está no equipamento GD-{invs[0].id:06d}"),   # sem tirar o outro de lá
            ([(invs[1], 112), (invs[2], 112)], 400, "mais de um equipamento"),
            ([(invs[1], 112), (invs[1], 113)], 400, "mais de uma vez"),
            ([(invs[1], 101)], 400, "não é um inversor desta usina"),                        # o nó de transformador
            ([(tr1, 102)], 400, "não é um transformador desta usina"),                       # o trafo auxiliar
            ([(invs[1], 108)], 400, "não é um inversor desta usina"),                        # o inversor híbrido
            ([(invs[1], 9999)], 400, "não é um inversor desta usina"),                       # o nó que não é da usina
            ([(c["da_outra"], 112)], 404, "não encontrado nesta usina"),                     # o dispositivo de outra usina
            ([(invs[1], 112), (999999, 113)], 404, "não encontrado nesta usina")):
        with pytest.raises(HTTPException) as e:
            _gravar(db, c, *pares)
        assert e.value.status_code == codigo_http and frase in e.value.detail, (pares, e.value.detail)
    db.expire_all()
    assert _nos(_ver(db, c))["INV16"] is None and db.query(HistoricoDaUsina).count() == 1      # nada foi gravado
    # o nó que está num dispositivo de OUTRA usina também recusa
    c["da_outra"].mp_node_id = 113
    db.commit()
    with pytest.raises(HTTPException) as e:
        _gravar(db, c, (invs[2], 113))
    assert e.value.status_code == 409 and f"GD-{c['da_outra'].id:06d}" in e.value.detail
    # o ausente pode ser ligado e desligado pela pessoa
    assert _nos(_gravar(db, c, (c["fora"], 112)))["INV99"] == 112


def test_so_o_gerente_da_empresa_da_usina(db, c):
    for chamada in (lambda: _ver(db, c, quem=c["g_b"]), lambda: _gravar(db, c, (c["tr1"], 101), quem=c["g_b"]),
                    lambda: _ver(db, c, usina=c["de_b"]), lambda: _gravar(db, c, (c["da_outra"], None), usina=c["de_b"])):
        with pytest.raises(HTTPException) as e:
            chamada()
        assert e.value.status_code == 404 and e.value.detail == "Usina não encontrada nesta empresa"
    assert db.query(DeviceLink).filter(DeviceLink.mp_node_id.isnot(None)).count() == 0
    # pela porta HTTP, sem a sessão do gerente, as duas rotas não abrem
    app.dependency_overrides[get_db] = lambda: db
    try:
        http = TestClient(app)
        url = f"/api/empresa/usinas/{c['per'].id}/dispositivos"
        assert http.get(url).status_code in (401, 403)
        assert http.put(url + "/nos", json={"nos": []}).status_code in (401, 403)
        assert http.get(url, headers={"X-Sistema": "meuplano", "X-Chave-Interna": "x"}).status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
