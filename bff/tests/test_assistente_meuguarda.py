"""As câmeras e os alarmes das usinas (meuGuarda) no bot do WhatsApp (pedido do dono, 11/11/2026: "integrar já, criar
rotina de teste e ligar para todos"). Especificação: `/root/DEVV/CFTV/docs/bot-gs.md`.

A parte `bot_meuguarda` não pede token: o meuGuarda confere a sessão do GS da própria pessoa.
"""
import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.user import Perfil, User, VinculoProduto
from app.services import cadastro


def _conta(db, apelido="tecnico.um", perfil=Perfil.TECNICO, telefone="+5517997371111", **bot):
    emp = db.query(Empresa).filter_by(nome="O&M das câmeras").one_or_none() or Empresa(nome="O&M das câmeras")
    db.add(emp)
    db.commit()
    u = User(apelido=apelido, nome=apelido.title(), perfil=perfil, telefone=telefone, empresa_id=emp.id, **bot)
    db.add(u)
    db.commit()
    return u


def test_a_parte_das_cameras_liga_sem_token_e_so_com_celular(db):
    conta = _conta(db)
    cadastro.liberar_bot(conta, "bot_meuguarda", True)
    assert conta.bot_ativo == {"bot_meuguarda"} and conta.bot_liberado
    # a do meuPlano continua pedindo o token dela
    with pytest.raises(HTTPException):
        cadastro.liberar_bot(conta, "bot_meuplano", True)

    sem_celular = _conta(db, "sem.celular", telefone=None)
    with pytest.raises(HTTPException) as e:
        cadastro.liberar_bot(sem_celular, "bot_meuguarda", True)
    assert "celular" in e.value.detail


async def test_apagar_o_celular_desliga_as_cameras_junto(db):
    conta = _conta(db, bot_meuguarda=True)
    await cadastro.gravar(db, conta, conta.empresa_id, telefone="")
    assert not conta.bot_meuguarda and conta.bot_ativo == set()


async def test_o_gerente_liga_e_desliga_pela_tela_bot_do_whatsapp(db):
    from app.api.v1 import empresa as rotas

    gerente = _conta(db, "gerente.um", Perfil.GESTOR_EMPRESA, "+5517997372222")
    tecnico = _conta(db, bot_meuguarda=True)
    db.add(VinculoProduto(gs_user_id=tecnico.id, produto="meuwatt", usuario_remoto_id="1", token_cifrado="x"))
    db.commit()
    out = await rotas.editar_conta_da_empresa(tecnico.id, rotas.ContaPatch(bot_meuguarda=False), db, gerente)
    assert out.bot_meuguarda is False and not db.get(User, tecnico.id).bot_meuguarda


# ── as ferramentas, com o meuGuarda simulado ────────────────────────────────
import httpx  # noqa: E402

from app.services import assistente  # noqa: E402
from app.services import assistente_geracao as ger  # noqa: E402
from app.services import assistente_helper as helper  # noqa: E402
from app.services import assistente_meuguarda as mg  # noqa: E402

_NOMES = ["Dome SKID 01", "Perímetro 01", "Perímetro 03", "Térmica 01", "Térmica 02", "Térmica 11"]
USINA = {"id": 1, "nome": "UFV Pereiras", "gs_usina_id": 2, "com_sinal": True, "cameras": 6, "cameras_online": 5,
         "alarmes_abertos": 2}


def _recusa(st, frase):
    pedido = httpx.Request("POST", "https://mg.test/x")
    return httpx.HTTPStatusError("x", request=pedido, response=httpx.Response(st, json={"detail": frase}, request=pedido))


class _MeuGuarda:
    def __init__(self):
        self.permissoes = ["cameras.ver", "cameras.aovivo.ver", "alarmes.ver", "alarmes.tratar"]
        self.cams = [{"id": i, "nome": n, "tipo": "camera", "canais": 2 if "Térmica" in n else 1, "online": i != 5,
                      "deteccao_desligada_ate": None, "alarmes_abertos": 0, "ultimo_evento": None}
                     for i, n in enumerate(_NOMES, 1)] + [{"id": 99, "nome": "NVR", "tipo": "nvr", "canais": 32}]
        self.deteccoes, self.foto_falha = [], None

    async def eu(self):
        return {"permissoes": self.permissoes, "usinas": [1]}

    async def usinas(self):
        return [USINA]

    async def cameras(self, usina_id):
        return self.cams

    async def alarmes(self):
        return [{"usina": "UFV Pereiras", "camera": "Perímetro 01", "tipo": "veiculo", "prioridade": 1,
                 "aberto_em": "2026-11-11T20:21:01+00:00"}]

    async def link(self, camera_id, canal=1):
        return {"url": f"https://mg.test/ver/tok-{camera_id}-{canal}", "expira_em": "2026-11-11T20:40:00+00:00",
                "camera": "x"}

    async def foto(self, camera_id, canal=1):
        if self.foto_falha:
            raise self.foto_falha
        return b"\xff\xd8jpeg", "isapi"

    async def deteccao(self, usina_id, ligada, camera_ids, minutos, motivo):
        self.deteccoes.append((usina_id, ligada, camera_ids, minutos, motivo))
        return {"ok": True, "cameras": len(camera_ids), "desligada_ate": "2099-01-01T21:00:00+00:00"}


@pytest.fixture
def meuguarda(monkeypatch):
    falso = _MeuGuarda()
    monkeypatch.setattr(mg, "cliente", lambda user: falso)
    return falso


def _ctx(db, **bot):
    u = _conta(db, bot_meuguarda=True, **bot)
    return ger.Contexto(db=db, user=u, telefone=u.telefone)


def test_o_nome_falado_casa_sem_inventar():
    ks = [{"nome": n} for n in [*_NOMES, "Térmica 03"]]
    acha = lambda t: (mg.escolher(ks, t)[0] or {}).get("nome")  # noqa: E731
    assert acha("perímetro 3") == "Perímetro 03" and acha("a câmera da termica 2") == "Térmica 02"
    assert acha("Térmica 1") == "Térmica 01" and acha("dome 1") == "Dome SKID 01" and acha("TERMICA 11") == "Térmica 11"
    assert acha("3") is None and acha("perímetro") is None and acha("câmera 99") is None   # ambíguo ou inexistente
    assert {k["nome"] for k in mg.escolher(ks, "perímetro")[1]} == {"Perímetro 01", "Perímetro 03"}


def test_as_ferramentas_vem_com_a_parte_e_o_perfil(db):
    tecnico = _conta(db, bot_meuguarda=True)
    assert set(mg.FERRAMENTAS) <= set(assistente.permitidas(tecnico))
    assert "câmeras de segurança" in assistente._sistema(ger.Contexto(db=db, user=tecnico, telefone="x"))
    sem = _conta(db, "sem.cameras", telefone="+5517997373333", bot_meuguarda=False)
    assert not set(mg.FERRAMENTAS) & set(assistente.permitidas(sem))
    # sem a parte, a IA não ouve o nome das ferramentas (chamava `foto_camera` fora da lista no banco de perguntas)
    prompt = assistente._sistema(ger.Contexto(db=db, user=sem, telefone="x"))
    assert "foto_camera" not in prompt and "não está liberada para esta pessoa" in prompt
    # a plataforma não usa o bot: sem portão no meuGuarda, sem ferramenta
    adm = _conta(db, "adm.um", Perfil.ADMINISTRADOR, "+5517997374444", bot_meuguarda=True)
    assert not set(mg.FERRAMENTAS) & set(assistente.permitidas(adm))


def test_a_sessao_e_a_da_propria_pessoa_no_portao_do_perfil(db):
    from jose import jwt

    from app.core.config import get_settings

    for perfil, portao, escopo in ((Perfil.GESTOR_EMPRESA, "empresa", "empresa"), (Perfil.TECNICO, "tecnico", "tecnico"),
                                   (Perfil.CLIENTE, "cliente", None)):
        u = _conta(db, f"p.{portao}", perfil, None)
        c = mg.cliente(u)
        token = c._cabecalhos["Authorization"].removeprefix("Bearer ")
        dados = jwt.decode(token, get_settings().gs_jwt_secret, algorithms=["HS256"])
        assert c._cabecalhos["X-Portao"] == portao and dados["sub"] == str(u.id) and dados.get("escopo") == escopo


async def test_estado_das_cameras(db, meuguarda):
    r = await mg.cameras(_ctx(db), {"usina": "pereiras"})
    assert r["usina"] == "UFV Pereiras" and len(r["cameras"]) == 6            # o NVR não é câmera
    meuguarda.cams[1]["deteccao_desligada_ate"] = "2099-01-01T21:00:00+00:00"
    meuguarda.cams[1]["deteccao_por"], meuguarda.cams[1]["deteccao_motivo"] = "Renan", "roçagem"
    r = await mg.cameras(_ctx(db, apelido="t2", telefone="+5517997375555"), {})
    assert r["cameras"][1]["alarme"] == "desligado até 01/01 18:00 por Renan (roçagem)"
    assert r["alarmes_abertos"]["total"] == 1 and r["alarmes_abertos"]["por_tipo"] == {"veiculo": 1}


async def test_o_link_vai_pelo_sistema_e_fica_fora_do_log(db, meuguarda):
    ctx = _ctx(db)
    r = await mg.ver_camera(ctx, {"camera": "perimetro 3"})
    assert r["link_enviado_pelo_sistema"] and "url" not in r and "https" not in str(r)
    assert ctx.rodape and "https://mg.test/ver/tok-3-1" in ctx.rodape[0]
    assert "tok-3-1" not in assistente._sem_segredos("\n\n".join(ctx.rodape), ctx.segredos)
    # ambígua: pergunta, não escolhe
    r = await mg.ver_camera(ctx, {"camera": "térmica"})
    assert "ambígua" in r["erro"] and len(r["opcoes"]) == 3


async def test_a_foto_chega_no_chat_e_a_demora_do_pc_e_dita(db, meuguarda, monkeypatch):
    enviados = []

    async def _enviar(**k):
        enviados.append(k)
        return {"ok": True}

    monkeypatch.setattr(mg.whatsapp, "enviar_conteudo", _enviar)
    ctx = _ctx(db)
    r = await mg.foto_camera(ctx, {"camera": "Térmica 02", "canal": 2})
    assert r["enviado_no_chat"] and enviados[0]["tipo"] == "image" and enviados[0]["arquivo"] == b"\xff\xd8jpeg"
    meuguarda.foto_falha = _recusa(504, "O PC da usina não respondeu a tempo. Tente de novo em instantes.")
    r = await mg.foto_camera(ctx, {"camera": "Térmica 02"})
    assert "PC da usina não respondeu" in r["erro"]
    meuguarda.foto_falha = _recusa(403, "Seu papel não permite: ver ao vivo")
    assert (await mg.foto_camera(ctx, {"camera": "Térmica 02"}))["erro"] == \
        "O meuGuarda recusou: Seu papel não permite: ver ao vivo."


async def test_desligar_o_alarme_pede_o_motivo_e_o_sim(db, meuguarda):
    ctx = _ctx(db)
    r = await mg.alarme_cameras(ctx, {"ligar": False, "cameras": ["perímetro 1", "perímetro 3"], "horas": 4})
    assert "motivo" in r["erro"] and ctx.proposta is None and not meuguarda.deteccoes
    r = await mg.alarme_cameras(ctx, {"ligar": False, "cameras": ["perímetro 1", "perímetro 3"], "horas": 4,
                                      "motivo": "tem gente roçando"})
    p = ctx.proposta
    assert r["proposta_pendente"] == "Desligar o alarme de 2 câmeras de UFV Pereiras, por 4 h"
    assert p.confirmacao == "sim" and p.parte == "bot_meuguarda" and not meuguarda.deteccoes
    assert p.detalhes == ["Perímetro 01, Perímetro 03", "Motivo: tem gente roçando"]
    assert helper.e_sim("Sim", p.resumo) and helper.e_sim("Pode desligar", p.resumo)
    assert not helper.e_sim("Pode ligar", p.resumo)
    feito = await helper._rodar(p, db, ctx.user, ctx.telefone)
    assert meuguarda.deteccoes == [(1, False, [2, 3], 240, "tem gente roçando")]
    assert feito.startswith("✅ Alarme de 2 câmeras de UFV Pereiras desligado até 01/01 18:00")


async def test_a_parte_desligada_no_meio_nao_executa(db, meuguarda):
    ctx = _ctx(db)
    await mg.alarme_cameras(ctx, {"ligar": True, "cameras": ["todas"]})
    assert ctx.proposta.resumo == "Ligar de novo o alarme de 6 câmeras de UFV Pereiras"
    ctx.user.bot_meuguarda = False                        # o gerente desligou enquanto a ação esperava
    assert await helper._rodar(ctx.proposta, db, ctx.user, ctx.telefone) == helper.PARTE_DESLIGADA
    assert meuguarda.deteccoes == []


async def test_sem_a_permissao_de_la_nem_propoe(db, meuguarda):
    meuguarda.permissoes = ["cameras.ver"]
    ctx = _ctx(db)
    r = await mg.alarme_cameras(ctx, {"ligar": False, "cameras": ["Térmica 01"], "motivo": "manutenção na câmera"})
    assert "não liga nem desliga alarme" in r["erro"] and ctx.proposta is None
    r = await mg.alarme_cameras(ctx, {"ligar": False, "cameras": ["Câmera 99"], "motivo": "manutenção na câmera"})
    assert ctx.proposta is None


# ── classificar os eventos em massa ─────────────────────────────────────────
@pytest.fixture
def com_eventos(meuguarda):
    meuguarda.contagens, meuguarda.lotes = [], []

    async def contar(filtro):
        meuguarda.contagens.append(filtro)
        return {"total": 257, "por_camera": [{"nome": "Perímetro 01", "n": 171}, {"nome": "Térmica 03", "n": 84},
                                             {"nome": "Dome SKID 02", "n": 2}],
                "por_tipo": [{"tipo": "pessoa", "n": 252}, {"tipo": "veiculo", "n": 5}]}

    async def classificar_lote(filtro, classificacao, motivo):
        meuguarda.lotes.append((filtro, classificacao, motivo))
        return {"classificados": 257, "cameras": 3}

    meuguarda.contar, meuguarda.classificar_lote = contar, classificar_lote
    return meuguarda


async def test_classificar_em_massa_mostra_quantos_e_espera_o_sim(db, com_eventos, monkeypatch):
    from datetime import date

    monkeypatch.setattr("app.core.datas.hoje", lambda: date(2026, 11, 11))
    ctx = _ctx(db)
    r = await mg.classificar_eventos(ctx, {"classificacao": "manutencao", "motivo": "pessoa trabalhando",
                                           "usina": "Pereiras"})
    assert r["proposta_pendente"] == "Classificar 257 eventos de UFV Pereiras como equipe/manutenção"
    p = ctx.proposta
    assert p.detalhes == ["Câmeras: Perímetro 01 (171), Térmica 03 (84), Dome SKID 02 (2)",
                          "Tipos: pessoa (252), veiculo (5)", "Período: 11/11", "Motivo: pessoa trabalhando"]
    # o filtro do dia inteiro de Brasília, só os sem classificação, e nada gravado antes do Sim
    assert com_eventos.contagens == [{"usina_id": 1, "de": "2026-11-11T00:00:00-03:00",
                                      "ate": "2026-11-12T00:00:00-03:00", "so_sem_classificacao": True}]
    assert com_eventos.lotes == [] and p.parte == "bot_meuguarda" and p.confirmacao == "sim"
    assert helper.e_sim("Sim", p.resumo) and helper.e_sim("Pode desclassificar", p.resumo)
    feito = await helper._rodar(p, db, ctx.user, ctx.telefone)
    assert com_eventos.lotes == [(com_eventos.contagens[0], "manutencao", "pessoa trabalhando")]
    assert feito == "✅ 257 eventos de UFV Pereiras classificados como equipe/manutenção. Motivo: pessoa trabalhando."


async def test_classificar_por_camera_tipo_e_periodo(db, com_eventos):
    ctx = _ctx(db)
    await mg.classificar_eventos(ctx, {"classificacao": "falso", "motivo": "vento nas árvores", "cameras": ["perímetro 1"],
                                       "tipos": ["veiculo"], "de": "2026-11-09", "ate": "2026-11-10"})
    assert com_eventos.contagens[0] == {"usina_id": 1, "de": "2026-11-09T00:00:00-03:00",
                                        "ate": "2026-11-11T00:00:00-03:00", "so_sem_classificacao": True,
                                        "camera_ids": [2], "tipos": ["veiculo"]}
    assert ctx.proposta.detalhes[2] == "Período: 09/11 a 10/11"


async def test_classificar_sem_motivo_sem_classe_ou_sem_evento_nao_propoe(db, com_eventos):
    ctx = _ctx(db)
    assert "motivo" in (await mg.classificar_eventos(ctx, {"classificacao": "falso", "motivo": ""}))["erro"]
    assert "classificação" in (await mg.classificar_eventos(ctx, {"classificacao": "x", "motivo": "vento forte"}))["erro"]

    async def nada(filtro):
        return {"total": 0, "por_camera": [], "por_tipo": []}

    com_eventos.contar = nada
    r = await mg.classificar_eventos(ctx, {"classificacao": "falso", "motivo": "vento forte"})
    assert r["nenhum_evento"] and ctx.proposta is None and com_eventos.lotes == []
    com_eventos.permissoes = ["alarmes.ver"]
    r = await mg.classificar_eventos(ctx, {"classificacao": "falso", "motivo": "vento forte"})
    assert "não classifica eventos" in r["erro"]
