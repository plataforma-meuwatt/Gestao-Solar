"""Cadastrar uma pessoa nos três sistemas pelo bot (pedido do Renan, 29/10/2026). O que se protege:

- só o gerente da O&M tem as ferramentas; nada grava antes do Sim;
- o bot PROCURA antes e diz o que já existe em cada sistema (como se fez à mão com o Diogo e o Michel);
- aproveitar conta é aproveitar a MESMA (o meuWatt vincula pelo e-mail dela, o meuPlano só acrescenta a empresa);
- conta do GS de fora da empresa não se aproveita (é da plataforma);
- o token da pessoa vai direto para o GS: nunca aparece no WhatsApp, no log nem para a IA;
- recusa de um produto não derruba os outros, e o token que o GS recusa é revogado.
"""

import httpx
import pytest

from app.models.conversa_whatsapp import RegistroBot
from app.models.plant import PlantLink
from app.models.user import Perfil, User, VinculoProduto
from app.services import assistente, assistente_cadastro as cad, login_externo, vinculos
from app.services import assistente_geracao as ger
from app.services import assistente_helper as h
from tests.test_assistente_whatsapp import _conta, _empresa, bot_local  # noqa: F401 (bot_local é fixture)

SEGREDOS = ("mw_pat_SEGREDO", "mp_pat_SEGREDO", "SESSAO-MW", "SESSAO-MP")


def _erro(codigo, detalhe):
    req = httpx.Request("POST", "http://produto")
    return httpx.HTTPStatusError(str(codigo), request=req,
                                 response=httpx.Response(codigo, json={"detail": detalhe}, request=req))


class _MeuWatt:
    def __init__(self):
        self.contas = [{"id": 34, "email": "marcos.cunha@splendorenergia.com.br", "name": "Marcos Vinicius",
                        "is_active": True, "gerivel": True},
                       {"id": 29, "email": "marcos@meuwatt.com.br", "name": "Marcos", "is_active": True, "gerivel": True},
                       {"id": 1, "email": "root@meuwatt.com.br", "name": "Raiz", "is_active": True, "gerivel": False}]
        self.equipe = {1: [{"id": 18, "user_id": 34, "role": "operator", "active": True}]}
        self.gravou, self.recusa = [], None

    async def usuarios(self, apenas_ativos=True):
        return self.contas

    async def empresas_om(self):
        return [{"id": 1, "name": "SplendorOEM"}]

    async def funcionarios(self, eid):
        return self.equipe.get(eid, [])

    async def provisionar(self, subject, email, nome, vincular_existente):
        if self.recusa:
            raise _erro(403, self.recusa)
        conta = next((c for c in self.contas if c["email"] == email), None)
        if conta and not vincular_existente:
            raise _erro(400, f"Já existe uma conta no meuWatt com o e-mail {email}")
        self.gravou.append(("provisionar", subject, email, vincular_existente))
        if conta is None:
            conta = {"id": 99, "email": email, "name": nome, "is_active": True, "gerivel": True}
            self.contas.append(conta)
            return {"user_id": 99, "criado": True}
        return {"user_id": conta["id"], "criado": False}

    async def por_na_empresa(self, eid, uid, papel):
        self.gravou.append(("na_empresa", eid, uid, papel))
        f = {"id": 70, "user_id": uid, "role": papel}
        self.equipe.setdefault(eid, []).append(f)
        return f

    async def conceder_usinas(self, eid, fid, ids):
        self.gravou.append(("usinas", fid, sorted(ids)))

    async def usinas(self):
        return [{"id": 9371, "slug": "ibitinga"}, {"id": 5, "slug": "de-outra-empresa"}]

    async def entrar_pelo_gs(self, assercao):
        self.gravou.append(("entrar", assercao))
        return "SESSAO-MW"

    async def emitir_token(self, sessao, nome):
        assert sessao == "SESSAO-MW" and nome == cad.NOME_DO_TOKEN
        return {"id": 5, "token": "mw_pat_SEGREDO"}

    async def revogar_token(self, sessao, tid):
        self.gravou.append(("revogar", tid))

    async def sair(self, sessao):
        self.gravou.append(("sair",))


class _MeuPlano:
    def __init__(self):
        self.contas = [{"id": 587, "email": "marcos@splendoroem.com.br", "name": "Marcos Vinicus", "phone": None,
                        "role": "cliente", "owner_ids": [8], "active": True}]
        self.gravou, self.recusa_vinculo = [], None

    async def usuarios_admin(self):
        return self.contas

    async def criar_usuario_admin(self, dados):
        self.gravou.append(("criar", dados))
        return {"id": 1500}

    async def atualizar_usuario_admin(self, uid, dados):
        self.gravou.append(("atualizar", uid, dados))
        return {}

    async def provisionar_identidade(self, uid, assercao):
        self.gravou.append(("provisionar", uid, assercao))
        return {}

    async def vinculo_na_organizacao(self, org, uid, dados):
        if self.recusa_vinculo:
            raise _erro(400, self.recusa_vinculo)
        self.gravou.append(("vinculo", org, uid, dados))
        return {}

    async def entrar_pelo_gs(self, assercao):
        return "SESSAO-MP"

    async def emitir_token(self, sessao, nome):
        assert sessao == "SESSAO-MP"
        return {"id": 7, "token": "mp_pat_SEGREDO"}

    async def revogar_token(self, sessao, tid):
        self.gravou.append(("revogar", tid))


@pytest.fixture
def cenario(db, bot_local, monkeypatch):
    emp = _empresa(db)
    emp.mw_enterprise_id, emp.mp_tenant_id = 1, 3
    db.add(PlantLink(nome="UFV Ibitinga", empresa_id=emp.id, mw_plant_slug="ibitinga", ativo=True))
    gerente = _conta(db, "renan.marquezini", "+5517997377626")
    gerente.perfil = Perfil.GESTOR_EMPRESA
    db.commit()
    mw, mp, ligados = _MeuWatt(), _MeuPlano(), []
    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda db_, uid, so_proprio=False: mw)
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    monkeypatch.setattr(login_externo, "assinar", lambda conta, produto: f"assercao:{conta.id}:{produto.value}")

    async def _conectar(db_, conta, produto, token, *, por):
        ligados.append((conta.apelido, produto.value, token, por.apelido))
        if (conta.apelido, produto.value) in cenario_recusa:
            return vinculos.ResultadoConexao(ok=False, detalhe="este token é de outra pessoa")
        db_.add(VinculoProduto(gs_user_id=conta.id, produto=produto.value, usuario_remoto_id="9", token_cifrado="c"))
        db_.commit()
        return vinculos.ResultadoConexao(ok=True, detalhe="ok", usinas_visiveis=6)

    cenario_recusa: set = set()
    monkeypatch.setattr(vinculos, "conectar", _conectar)
    monkeypatch.setattr(h, "configurado", lambda: True)
    h.PENDENTES.clear()
    import types
    return types.SimpleNamespace(gerente=gerente, mw=mw, mp=mp, ligados=ligados, bot=bot_local, recusa=cenario_recusa,
                                 ctx=ger.Contexto(db=db, user=gerente, telefone=gerente.telefone))


async def _sim(cenario):
    h.mostrada(cenario.gerente.id)
    await assistente.atender({"id": 900, "telefone": cenario.gerente.telefone, "wa_id": "1", "tipo": "text",
                              "texto": "Sim"})
    return cenario.bot.enviados[-1]


def test_so_o_gerente_da_o_e_m_tem_as_ferramentas_de_cadastro(db, cenario):
    assert {"procurar_pessoa", "cadastrar_pessoa"} <= set(assistente.permitidas(cenario.gerente))
    tecnico = _conta(db, "tecnico.um", "+5517996495795")
    tecnico.perfil = Perfil.TECNICO
    db.commit()
    assert not {"procurar_pessoa", "cadastrar_pessoa"} & set(assistente.permitidas(tecnico))


async def test_o_bot_procura_antes_e_diz_o_que_ja_existe_em_cada_sistema(db, cenario):
    orfa = _conta(db, "marcos.cunha", "+5513900000000")
    orfa.empresa_id, orfa.email = None, "marcos@splendoroem.com.br"
    db.commit()
    r = await cad.procurar_pessoa(cenario.ctx, {"nome": "Marcos", "email": "marcos@splendoroem.com.br",
                                                "telefone": "+55 13 99638-9918"})
    assert r["gestao_solar"]["na_sua_empresa"] == []
    assert any("fora da sua empresa" in f for f in r["gestao_solar"]["fora_da_sua_empresa"])
    achadas = {c["conta"]: c for c in r["meuwatt"]["contas"]}
    assert set(achadas) == {34, 29} and achadas[34]["empresas"] == ["SplendorOEM: operador"]   # pelo 1º nome
    assert [c["conta"] for c in r["meuplano"]["contas"]] == [587]                               # pelo e-mail
    assert r["meuwatt"]["empresa_da_sua_o_e_m"] == 1 and r["meuplano"]["organizacao_da_sua_empresa"] == 3
    assert cenario.mw.gravou == [] and cenario.mp.gravou == []                                  # procurar só lê


async def test_pessoa_nova_nos_tres_sistemas_so_com_o_sim_e_sem_o_token_aparecer(db, cenario):
    r = await cad.cadastrar_pessoa(cenario.ctx, {
        "nome": "Michel Renan", "email": "tecnico1@splendoroem.com.br", "telefone": "+55 17 99649-5795",
        "gs_perfil": "tecnico", "mw_papel": "field_employee", "mp_papel": "tecnico_campo", "bot": ["meuwatt", "meuplano"]})
    assert r["proposta_pendente"] == "Cadastrar Michel Renan (tecnico1@splendoroem.com.br)"
    assert db.query(User).filter_by(apelido="michel.renan").count() == 0                       # nada antes do Sim
    assert cenario.mw.gravou == [] and cenario.mp.gravou == []
    desfecho = await _sim(cenario)
    assert desfecho.startswith("✅ Cadastro de Michel Renan feito:"), desfecho
    michel = db.query(User).filter_by(apelido="michel.renan").one()
    assert (michel.perfil, michel.empresa_id, michel.telefone) == (Perfil.TECNICO, cenario.gerente.empresa_id,
                                                                   "+5517996495795")
    assert michel.bot_ativo == {"bot_meuwatt", "bot_meuplano"} and not michel.senha_atuacao_hash
    assert ("na_empresa", 1, 99, "field_employee") in cenario.mw.gravou
    assert ("usinas", 70, [9371]) in cenario.mw.gravou            # só as usinas da empresa no GS
    assert ("provisionar", str(michel.id), "tecnico1@splendoroem.com.br", False) in cenario.mw.gravou
    assert cenario.mw.gravou[-1] == ("sair",)                     # a sessão aberta para o token é fechada
    assert cenario.mp.gravou[0] == ("criar", {"email": "tecnico1@splendoroem.com.br", "name": "Michel Renan",
                                              "role": "tecnico_campo", "phone": "(17) 9 9649-5795", "owner_ids": [3]})
    assert ("provisionar", 1500, f"assercao:{michel.id}:meuplano") in cenario.mp.gravou
    assert sorted(cenario.ligados) == [("michel.renan", "meuplano", "mp_pat_SEGREDO", "renan.marquezini"),
                                       ("michel.renan", "meuwatt", "mw_pat_SEGREDO", "renan.marquezini")]
    vistos = [*cenario.bot.enviados, *cenario.bot.guardados, *cenario.bot.llm,
              *(f"{x.pergunta} {x.resposta}" for x in db.query(RegistroBot))]
    assert not [v for v in vistos for s in SEGREDOS if s in str(v)]


async def test_aproveitar_e_a_mesma_conta_em_cada_sistema(db, cenario):
    await cad.cadastrar_pessoa(cenario.ctx, {
        "nome": "Marcos Vinicius", "email": "marcos@splendoroem.com.br", "telefone": "+55 13 99638-9918",
        "gs_perfil": "gestor_empresa", "mw_papel": "system_admin", "mw_conta": 34, "mp_papel": "admin_tenant",
        "mp_conta": 587})
    assert "meuWatt: aproveitar a conta #34 (marcos.cunha@splendorenergia.com.br)" in "\n".join(
        h.PENDENTES[cenario.gerente.id].detalhes)
    desfecho = await _sim(cenario)
    marcos = db.query(User).filter_by(apelido="marcos.vinicius").one()
    # o meuWatt vincula pelo e-mail DA CONTA aproveitada; ele já era operador lá: o papel não é trocado
    assert ("provisionar", str(marcos.id), "marcos.cunha@splendorenergia.com.br", True) in cenario.mw.gravou
    assert not [g for g in cenario.mw.gravou if g[0] == "na_empresa"]
    assert "já era operador lá: o papel não foi trocado" in desfecho
    # o meuPlano acrescenta a empresa, sem tirar a que a pessoa já tinha, e não cria outra conta
    assert ("atualizar", 587, {"role": "admin_tenant", "owner_ids": [3, 8], "phone": "(13) 9 9638-9918"}) in cenario.mp.gravou
    assert not [g for g in cenario.mp.gravou if g[0] == "criar"]


async def test_conta_do_gs_de_fora_da_empresa_e_do_meuwatt_que_nao_administra_nao_se_aproveitam(db, cenario):
    orfa = _conta(db, "marcos.cunha", "+5513900000000")
    orfa.empresa_id = None
    db.commit()
    r = await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Marcos", "gs_perfil": "gestor_empresa", "gs_conta": orfa.id})
    assert "não é da sua empresa" in r["erro"]
    r = await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Marcos", "gs_perfil": "gestor_empresa",
                                                 "mw_papel": "system_admin", "mw_conta": 1})
    assert "não está entre as que você administra" in r["erro"]
    assert cenario.gerente.id not in h.PENDENTES


async def test_a_recusa_de_um_produto_nao_derruba_os_outros_e_o_token_recusado_e_revogado(db, cenario):
    cenario.mw.recusa = "Provisionar conta é restrito a administradores"
    cenario.recusa.add(("diogo", "meuplano"))
    await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Diogo", "apelido": "diogo", "email": "diogo@x.com",
                                             "gs_perfil": "tecnico", "mw_papel": "field_employee",
                                             "mp_papel": "tecnico_campo"})
    desfecho = await _sim(cenario)
    assert desfecho.startswith("⚠️ Cadastro de Diogo feito EM PARTE:")
    assert "❌ meuWatt: Provisionar conta é restrito a administradores" in desfecho
    assert "❌ meuPlano: o GS recusou o token (este token é de outra pessoa); ele foi revogado" in desfecho
    assert ("revogar", 7) in cenario.mp.gravou
    assert db.query(User).filter_by(apelido="diogo").one().perfil == Perfil.TECNICO      # o GS ficou


async def test_sem_o_proprio_token_o_bot_nao_mexe_no_produto(db, cenario, monkeypatch):
    def _sem(*a, **k):
        raise vinculos.SemConexao("sem token")
    monkeypatch.setattr(vinculos, "cliente_meuwatt", _sem)
    r = await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Ana", "email": "ana@x.com", "gs_perfil": "tecnico",
                                                 "mw_papel": "field_employee"})
    assert "Você não tem o seu token do meuWatt" in r["erro"]


async def test_quem_nao_e_gerente_ouve_nao_ate_chamando_a_ferramenta_e_no_sim(db, cenario):
    tecnico = _conta(db, "tecnico.um", "+5517996495795")
    tecnico.perfil = Perfil.TECNICO
    db.commit()
    ctx = ger.Contexto(db=db, user=tecnico, telefone=tecnico.telefone)
    assert "Só o gerente" in (await cad.procurar_pessoa(ctx, {"nome": "Marcos"}))["erro"]
    assert "Só o gerente" in (await cad.cadastrar_pessoa(ctx, {"nome": "Marcos", "gs_perfil": "tecnico"}))["erro"]
    # deixou de ser gerente entre o resumo e o Sim: nada é feito
    await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Ana Paula", "gs_perfil": "tecnico"})
    cenario.gerente.perfil = Perfil.TECNICO
    db.commit()
    assert await _sim(cenario) == "❌ Só o gerente da O&M cadastra pessoas pelo bot. Nada foi feito."
    assert db.query(User).filter_by(apelido="ana.paula").count() == 0


async def test_conta_do_gs_ja_ligada_a_outra_do_meuwatt_nao_vira_a_que_se_pediu(db, cenario, monkeypatch):
    async def _ja_ligada(subject, email, nome, vincular_existente):
        return {"user_id": 29, "criado": False}            # o meuWatt devolve a conta já ligada a este GS
    monkeypatch.setattr(cenario.mw, "provisionar", _ja_ligada)
    await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Marcos Vinicius", "gs_perfil": "gestor_empresa",
                                             "mw_papel": "system_admin", "mw_conta": 34})
    desfecho = await _sim(cenario)
    assert "❌ meuWatt: a conta do GS já estava ligada a outra conta do meuWatt (#29); nada mudou lá" in desfecho
    assert not [g for g in cenario.mw.gravou if g[0] in ("na_empresa", "entrar")]


def test_senha_de_cadeado_vai_ao_meuplano_e_a_ia_nao_recusa_sozinha(db, cenario):
    """29/10/2026: "Qual a senha do cadeado de tiete" ouvia "não passo credencial de acesso físico" sem o bot perguntar
    ao meuPlano (0 ferramentas, 3 de 3 na IA real). A frase "nunca escreva uma senha", escrita para a senha de atuação
    e a de login, era lida como proibição de qualquer senha. Quem decide é o meuPlano, pelo nível da pessoa."""
    s = assistente._sistema(cenario.ctx)
    assert "nunca escreva uma senha" not in s
    assert "cadeado, portão, cofre, Wi-Fi" in s and "SEMPRE `manutencao`" in s and "Nunca recuse por conta própria" in s


async def test_prestador_so_no_meuplano_sem_conta_no_gs(db, cenario):
    """29/10/2026: "cadastrar o Thiago Marquezini no meuPlano como prestador de serviço para a Splendor, que possa
    assumir tarefas dentro das OS". Lá é o vínculo `terceiro` (Permissão "Prestador (terceiro)": executa as tarefas,
    sem financeiro, equipe e estoque), PJ. Sem perfil no GS, o GS não é tocado: sem conta, token e bot."""
    contas_gs = db.query(User).count()
    r = await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Thiago Marquezini", "email": "thiago@x.com",
                                                 "telefone": "35 99931-8670", "mp_papel": "prestador"})
    assert r["proposta_pendente"] == "Cadastrar Thiago Marquezini (thiago@x.com)"
    assert h.PENDENTES[cenario.gerente.id].detalhes == [
        "meuPlano: conta nova (thiago@x.com) como prestador de serviço (terceiro) da sua empresa: assume e executa "
        "tarefas das OS, celular (35) 9 9931-8670"]
    assert cenario.mp.gravou == []
    desfecho = await _sim(cenario)
    assert cenario.mp.gravou == [
        ("criar", {"email": "thiago@x.com", "name": "Thiago Marquezini", "role": "leitura",
                   "phone": "(35) 9 9931-8670", "owner_ids": [3]}),
        ("vinculo", 3, 1500, {"member_role": "terceiro", "tipo_vinculo": "PJ"})]
    assert desfecho == ("✅ Cadastro de Thiago Marquezini feito:\n• ✅ meuPlano: conta nova #1500 como prestador de "
                        "serviço (terceiro)\n" + cad.SENHA_DO_MP)
    assert db.query(User).count() == contas_gs and cenario.ligados == []


async def test_prestador_aproveitado_guarda_o_papel_global_e_a_recusa_diz_o_que_ficou(db, cenario):
    await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Marcos", "mp_papel": "prestador", "mp_conta": 587})
    cenario.mp.recusa_vinculo = "Sem permissão"
    desfecho = await _sim(cenario)
    assert cenario.mp.gravou == [("atualizar", 587, {"owner_ids": [3, 8]})]      # o papel global de lá fica
    assert desfecho == ("⚠️ Cadastro de Marcos feito EM PARTE:\n• ❌ meuPlano: a conta #587 está na sua empresa, mas o "
                        "papel de prestador não entrou (Sem permissão): troque em Minha Empresa → Equipe")


@pytest.mark.parametrize("pedido", [{"mw_papel": "field_employee", "email": "a@x.com"}, {"bot": ["meuplano"]},
                                    {"gs_conta": 1}, {}, {"gs_perfil": "chefe", "mp_papel": "prestador"}])
async def test_sem_perfil_no_gs_so_o_meuplano_e_aceito(db, cenario, pedido):
    r = await cad.cadastrar_pessoa(cenario.ctx, {"nome": "Ana", **pedido})
    assert r["erro"].startswith("Falta o perfil no GS") and cenario.gerente.id not in h.PENDENTES
