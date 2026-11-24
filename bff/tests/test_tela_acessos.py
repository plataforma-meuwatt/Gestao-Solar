"""A tela Acessos (24/11/2026, "o GS é o detentor dos acessos, quero a auditoria completa dos logs de acessos de cada
pessoa"): o gerente vê só a empresa dele (inclusive quem é membro dela vindo de outra), a plataforma vê tudo, os filtros
correm no servidor, o vocabulário sai pronto (o rótulo segue o resultado; quem e por quem em palavras) e cada mudança de
acesso feita por outra pessoa fica registrada com quem fez."""
from datetime import UTC, date, datetime, timedelta

from app.api.v1 import empresa as rotas
from app.api.v1.empresa import acessos_da_empresa
from app.api.v1.painel_acessos import acessos_da_plataforma
from app.models.acesso import AcessoGS
from app.models.empresa import Empresa, MembroDaEmpresa
from app.models.user import Perfil, User
from app.services import acessos

UA_CELULAR = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36"


def _cenario(db):
    a, b = Empresa(nome="Splendor O&M"), Empresa(nome="Outra O&M")
    db.add_all([a, b])
    db.commit()
    gerente = User(apelido="gerente.a", nome="Gerente A", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id)
    dono_a = User(apelido="dono.a", nome="Dono A", perfil=Perfil.CLIENTE, empresa_id=a.id)
    dono_b = User(apelido="dono.b", nome="Dono B", perfil=Perfil.CLIENTE, empresa_id=b.id)
    membro = User(apelido="tec.b", nome="Técnico B", perfil=Perfil.TECNICO, empresa_id=b.id)   # de B, membro de A
    adm = User(apelido="adm.p", nome="Admin P", perfil=Perfil.ADMINISTRADOR)
    db.add_all([gerente, dono_a, dono_b, membro, adm])
    db.commit()
    db.add(MembroDaEmpresa(empresa_id=a.id, user_id=membro.id))
    agora = datetime.now(UTC)
    db.add_all([
        AcessoGS(gs_user_id=dono_a.id, login="dono.a", acao="entrou", sistema="gs", ok=True,
                 motivo="aplicativo ou portal", ip="200.1.1.1", aparelho=UA_CELULAR, em=agora - timedelta(minutes=4)),
        AcessoGS(gs_user_id=dono_a.id, login="dono.a", acao="passe", sistema="termovision", ok=True,
                 motivo="já dentro do GS", ip="200.1.1.1", aparelho=UA_CELULAR, em=agora - timedelta(minutes=3)),
        AcessoGS(gs_user_id=dono_a.id, login="dono.a", acao="passe", sistema="termovision", ok=False,
                 motivo="pelo bot", ip="", aparelho="", em=agora - timedelta(minutes=2)),
        AcessoGS(gs_user_id=dono_a.id, login="dono.a", acao="recusado", sistema="gs", ok=False,
                 motivo="senha errada", ip="200.9.9.9", aparelho="python-httpx/0.27", em=agora - timedelta(minutes=1)),
        AcessoGS(gs_user_id=dono_a.id, acao="senha", sistema="gs", ok=True, motivo="senha de entrar redefinida",
                 por_id=adm.id, em=agora - timedelta(seconds=30)),
        AcessoGS(gs_user_id=membro.id, login="tec.b", acao="entrou", sistema="gs", ok=True, motivo="pelo oem-gs",
                 ip="7.7.7.7", em=agora),
        AcessoGS(gs_user_id=dono_b.id, login="dono.b", acao="entrou", sistema="gs", ok=True, motivo="", ip="1.1.1.1",
                 aparelho="", em=agora),
        AcessoGS(gs_user_id=None, login="? abc", acao="recusado", sistema="gs", ok=False,
                 motivo="login de conta nenhuma", ip="9.9.9.9", aparelho="", em=agora),
        AcessoGS(gs_user_id=None, login="", acao="bloqueado", sistema="gs", ok=False,
                 motivo="bloqueado: 30 senhas erradas deste IP em 15 min", ip="9.9.9.9", em=agora),
        AcessoGS(gs_user_id=None, login="velho.apagado", acao="entrou", sistema="gs", ok=True, motivo="", em=agora),
        AcessoGS(gs_user_id=dono_a.id, login="dono.a", acao="entrou", sistema="gs", ok=True, motivo="antigo",
                 ip="200.1.1.1", aparelho="", em=agora - timedelta(days=40)),
    ])
    db.commit()
    return a, b, gerente, dono_a, dono_b, membro, adm


def _empresa(db, gerente, **f):
    return acessos_da_empresa(db=db, gerente=gerente, **f)


def _plataforma(db, adm, **f):
    return acessos_da_plataforma(db=db, _=adm, **f)


def test_o_gerente_ve_a_empresa_dele_com_os_membros_e_a_plataforma_ve_tudo(db):
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    da_empresa = _empresa(db, gerente)
    assert {x.usuario_id for x in da_empresa.acessos} == {dono_a.id, membro.id}   # nem a B, nem as sem conta
    tudo = _plataforma(db, adm)
    assert {x.usuario_id for x in tudo.acessos} == {dono_a.id, dono_b.id, membro.id, None}
    assert {x.usuario_id for x in _plataforma(db, adm, empresa_id=b.id).acessos} == {dono_b.id, membro.id}
    # o catálogo dos sistemas vem inteiro, não só os que aparecem no resultado
    assert {s.chave for s in da_empresa.sistemas} >= {"gs", "meuwatt", "meuplano", "meuguarda", "termovision"}


def test_o_rotulo_segue_o_resultado_e_o_quem_vem_pronto(db):
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    linhas = {(x.acao, x.ok, x.quem): x for x in _plataforma(db, adm).acessos}
    assert linhas[("passe", True, "Dono A (dono.a)")].acao_rotulo == "Passe entregue ao sistema"
    assert linhas[("passe", False, "Dono A (dono.a)")].acao_rotulo == "O sistema recusou o passe"
    assert linhas[("bloqueado", False, "Vários logins, do mesmo lugar")].acao_rotulo == "Bloqueado"
    assert ("recusado", False, "Login que não é conta") in linhas
    assert ("entrou", True, "Conta apagada (velho.apagado)") in linhas


def test_quem_fez_a_mudanca_a_empresa_nao_ve_a_conta_da_plataforma(db):
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    senha_emp = next(x for x in _empresa(db, gerente).acessos if x.acao == "senha")
    senha_adm = next(x for x in _plataforma(db, adm).acessos if x.acao == "senha")
    assert senha_emp.por == "equipe da plataforma" and senha_adm.por == "Admin P (adm.p)"


def test_filtros_no_servidor(db):
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    recusas = _empresa(db, gerente, so_recusas=True).acessos
    assert {(x.acao_rotulo, x.aparelho) for x in recusas} == {("Recusado", "servidor de outro sistema"),
                                                             ("O sistema recusou o passe", "registrado pelo próprio GS")}
    tv = _empresa(db, gerente, sistema="termovision").acessos
    assert [(x.acao_rotulo, x.aparelho) for x in tv] == [("O sistema recusou o passe", "registrado pelo próprio GS"),
                                                         ("Passe entregue ao sistema", "Chrome no Android")]
    assert [x.quem for x in _empresa(db, gerente, busca="7.7.7").acessos] == ["Técnico B (tec.b)"]   # IP
    assert {x.quem for x in _empresa(db, gerente, busca="dono a").acessos} == {"Dono A (dono.a)"}     # nome
    assert _empresa(db, gerente, busca="100%_").acessos == []                                         # curinga literal
    so_ele = _empresa(db, gerente, usuario_id=membro.id)
    assert so_ele.pessoa == "Técnico B (tec.b)" and {x.usuario_id for x in so_ele.acessos} == {membro.id}
    de_fora = _empresa(db, gerente, usuario_id=dono_b.id)                  # pessoa de outra empresa: nada, nem o nome
    assert de_fora.pessoa is None and de_fora.acessos == []
    hoje = date.today()
    recentes = _empresa(db, gerente, de=hoje - timedelta(days=1), ate=hoje + timedelta(days=1)).acessos
    assert "antigo" not in [x.motivo for x in recentes]                  # o de 40 dias atrás fica fora
    assert [x.em for x in recentes] == sorted([x.em for x in recentes], reverse=True)   # do mais novo ao mais velho


def test_o_dia_e_o_de_brasilia(db):
    """23:30 de Brasília do dia 10 é 02:30 UTC do dia 11: é do dia 10."""
    a, b, gerente, dono_a, *_ = _cenario(db)
    db.add(AcessoGS(gs_user_id=dono_a.id, login="dono.a", acao="entrou", sistema="gs", motivo="à noite",
                    em=datetime(2026, 11, 11, 2, 30, tzinfo=UTC)))
    db.commit()
    assert "à noite" in [x.motivo for x in _empresa(db, gerente, de=date(2026, 11, 10), ate=date(2026, 11, 10)).acessos]
    assert "à noite" not in [x.motivo for x in _empresa(db, gerente, de=date(2026, 11, 11), ate=date(2026, 11, 11)).acessos]


async def test_a_mudanca_de_acesso_pelo_gerente_fica_registrada_com_quem_fez(db):
    a, b, gerente, dono_a, *_ = _cenario(db)
    await rotas.editar_conta_da_empresa(dono_a.id, rotas.ContaPatch(ativo=False, senha_atuacao="482913",
                                                                    meuguarda_liberado=True), db, gerente)
    linha = next(x for x in _empresa(db, gerente).acessos if x.acao == "acesso")
    assert linha.acao_rotulo == "Acesso mudado" and linha.por == "Gerente A (gerente.a)"
    assert linha.motivo == ("conta desativada; senha de atuação do bot definida; meuGuarda liberado "
                            "(oem-gs, usuários)")
    n = len(_empresa(db, gerente).acessos)
    await rotas.editar_conta_da_empresa(dono_a.id, rotas.ContaPatch(ativo=False), db, gerente)   # nada mudou: nada
    assert len(_empresa(db, gerente).acessos) == n


def test_aparelho_em_palavras():
    assert acessos.aparelho_curto("") == "não informado"
    assert acessos.aparelho_curto("Expo/1017565 CFNetwork/1568 Darwin/24.0.0") == "aplicativo"
    assert acessos.aparelho_curto("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 "
                                  "Safari/537.36 Edg/131.0") == "Edge no Windows"
    assert acessos.aparelho_curto("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                                  "Version/18.0 Mobile/15E148 Safari/604.1") == "Safari no iPhone"


def test_conjunto_em_palavras():
    assert acessos.conjunto("usinas", {"Tietê"}, {"Ibitinga", "Tietê"}) == ["usinas: liberadas Ibitinga"]
    assert acessos.conjunto("usinas", {"A"}, {"A"}) == []
    longo = acessos.conjunto("usinas", set(), {f"Usina número {i:03d}" for i in range(20)})
    assert longo == ["usinas: 20 liberada(s), 0 tirada(s)"]


# ── cada mudança de acesso fica registrada, com quem fez (a segunda avaliação, 24/11/2026) ──────────────────────────
def _linhas(db, conta_id):
    return [x for x in acessos.listar(db, usuario_id=conta_id) if x["acao"] == "acesso"]


def test_a_equipe_da_plataforma_criada_e_editada_fica_registrada(db):
    from app.api.v1 import painel_usuarios as rotas_p
    adm = User(apelido="adm.p", nome="Admin P", perfil=Perfil.ADMINISTRADOR)
    outro = User(apelido="adm.q", nome="Admin Q", perfil=Perfil.ADMINISTRADOR)
    db.add_all([adm, outro])
    db.commit()
    novo = rotas_p.criar(rotas_p.MembroIn(nome="Atendente", apelido="atend.um", senha="senha-boa-123",
                                          areas=["acessos"]), db, adm)
    criado = _linhas(db, novo.id)
    assert criado[0]["motivo"] == ("conta criada: atendimento da plataforma; telas do adm-gs: liberadas Registro de "
                                   "acessos (adm-gs, equipe da plataforma)") and criado[0]["por"] == "Admin P (adm.p)"
    rotas_p.editar(novo.id, rotas_p.MembroPatch(ativo=False, areas=[]), db, adm)
    assert _linhas(db, novo.id)[0]["motivo"] == ("conta desativada; telas do adm-gs: tiradas Registro de acessos "
                                                 "(adm-gs, equipe da plataforma)")


def test_permissoes_e_empresa_da_pessoa_ficam_registradas(db):
    from app.api.v1 import painel_empresas as rotas_e
    from app.api.v1 import permissoes as rotas_perm
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    rotas_perm.definir_permissoes(dono_a.id, rotas_perm.PermissoesIn(permissoes=["notificacao.usina_parada"]), db, adm)
    assert _linhas(db, dono_a.id)[0]["motivo"] == "permissões: liberadas Usina parada (adm-gs, clientes)"
    rotas_e.por_usuario_na_empresa(b.id, dono_a.id, db, adm)
    assert _linhas(db, dono_a.id)[0]["motivo"] == "entrou na empresa Outra O&M (adm-gs, empresas)"
    novo = rotas_e.criar_usuario_da_empresa(a.id, rotas_e.NovoUsuarioIn(nome="Dona Nova", apelido="dona.nova"), db, adm)
    assert _linhas(db, novo.id)[0]["motivo"] == "conta criada: dono de usina (adm-gs, empresas)"


async def test_a_empresa_nao_ve_o_que_a_outra_empresa_da_pessoa_mudou(db):
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    gerente_b = User(apelido="gerente.b", nome="Gerente B", perfil=Perfil.GESTOR_EMPRESA, empresa_id=b.id)
    db.add(gerente_b)
    db.commit()
    acessos.mudou(db, membro, gerente_b, ["usinas: liberadas Usina Secreta de B"], "oem-gs, usuários",
                  empresa_id=b.id)
    acessos.mudou(db, membro, gerente, ["celular trocado"], "oem-gs, usuários", empresa_id=a.id)
    vista_a = [x for x in _empresa(db, gerente, usuario_id=membro.id).acessos if x.acao == "acesso"]
    assert [(x.motivo, x.por) for x in vista_a] == [
        ("celular trocado (oem-gs, usuários)", "Gerente A (gerente.a)"),
        ("mudança de acesso feita na outra empresa da pessoa", "a outra empresa da pessoa")]
    assert _empresa(db, gerente, busca="secreta").acessos == []           # o que está escondido não se acha
    assert {x.empresa for x in _empresa(db, gerente).acessos} == {None}   # nem o nome da outra empresa
    vista_b = [x for x in _empresa(db, gerente_b, usuario_id=membro.id).acessos if x.acao == "acesso"]
    assert ("usinas: liberadas Usina Secreta de B (oem-gs, usuários)", "Gerente B (gerente.b)") in [
        (x.motivo, x.por) for x in vista_b]
    # a busca pelo nome de quem fez: a empresa acha o gerente dela, não o da outra nem a plataforma
    assert {x.motivo for x in _empresa(db, gerente, busca="gerente a").acessos} == {"celular trocado (oem-gs, usuários)"}
    assert _empresa(db, gerente, busca="gerente b").acessos == []
    assert _empresa(db, gerente, busca="admin p").acessos == []
    assert [x.por for x in _plataforma(db, adm, busca="admin p").acessos] == ["Admin P (adm.p)"]


def test_o_periodo_padrao_e_o_do_servidor(db):
    a, b, gerente, dono_a, *_ = _cenario(db)
    padrao = _empresa(db, gerente)
    from app.core.datas import hoje
    assert padrao.de == hoje() - timedelta(days=30) and "antigo" not in [x.motivo for x in padrao.acessos]
    tudo = _empresa(db, gerente, todo_periodo=True)
    assert tudo.de is None and "antigo" in [x.motivo for x in tudo.acessos]


def test_quem_e_das_duas_empresas_e_a_plataforma_na_outra_empresa_nao_vazam(db):
    """O gerente das duas empresas mudando algo em B, e a plataforma pondo a pessoa em B: A não lê o que foi."""
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)
    dos_dois = User(apelido="gerente.ab", nome="Gerente AB", perfil=Perfil.GESTOR_EMPRESA, empresa_id=a.id)
    db.add(dos_dois)
    db.commit()
    db.add(MembroDaEmpresa(empresa_id=b.id, user_id=dos_dois.id))
    db.commit()
    acessos.mudou(db, membro, dos_dois, ["usinas: liberadas Outra Usina de B"], "oem-gs, usuários", empresa_id=b.id)
    acessos.mudou(db, membro, adm, ["entrou na empresa Concorrente B"], "adm-gs, empresas", empresa_id=b.id)
    vista_a = [(x.motivo, x.por) for x in _empresa(db, gerente, usuario_id=membro.id).acessos if x.acao == "acesso"]
    assert vista_a == [("mudança de acesso feita na outra empresa da pessoa", "equipe da plataforma"),
                       ("mudança de acesso feita na outra empresa da pessoa", "a outra empresa da pessoa")]
    assert _empresa(db, gerente, busca="concorrente").acessos == []
    assert _empresa(db, gerente, busca="gerente ab").acessos == []


async def test_token_conectado_e_tirado_e_empresa_desligada_ficam_no_registro(db, monkeypatch):
    """A revisão final de 24/11: o token decide com que conta a pessoa entra no produto, e desligar a empresa corta a
    entrada de todos dela — os dois são mudança de acesso."""
    from app.api.v1 import painel_empresas as rotas_e
    from app.models.integracao import Produto
    from app.models.user import VinculoProduto
    from app.services import vinculos
    a, b, gerente, dono_a, dono_b, membro, adm = _cenario(db)

    async def conectar(db_, conta, produto, token, por):
        db_.add(VinculoProduto(gs_user_id=conta.id, produto=produto.value, usuario_remoto_id="9", token_cifrado="x"))
        db_.commit()
        return vinculos.ResultadoConexao(ok=True, detalhe="ok")
    monkeypatch.setattr(vinculos, "conectar", conectar)
    await rotas.conectar_conta_do_cliente(dono_a.id, Produto.MEUWATT, rotas.ConectarClienteIn(token="mw_pat_x"), db, gerente)
    rotas.desconectar_conta_do_cliente(dono_a.id, Produto.MEUWATT, db, gerente)
    motivos = [x["motivo"] for x in _linhas(db, dono_a.id)]
    assert "token do meuWatt conectado (oem-gs, usuários)" in motivos
    assert "token do meuWatt tirado (oem-gs, usuários)" in motivos
    rotas_e.editar(a.id, rotas_e.EmpresaPatch(ativa=False), db, adm)
    for conta in (gerente, dono_a, membro):                               # os da empresa e o membro vindo de outra
        assert "empresa Splendor O&M desativada (adm-gs, empresas)" in [x["motivo"] for x in _linhas(db, conta.id)]
    assert not [x for x in _linhas(db, dono_b.id) if "desativada" in x["motivo"]]
