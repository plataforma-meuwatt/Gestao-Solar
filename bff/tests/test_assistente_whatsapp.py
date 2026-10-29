"""O assistente do WhatsApp: quem é a pessoa, e o atalho da manutenção.

O Gestão Solar é o guardião: o número tem de casar com UMA conta daqui, ou não há conversa.
"""

import pytest

from app.models.user import Perfil, User, VinculoProduto
from app.services import assistente
from app.services import assistente_geracao as ger


def _conversa_em_claro(db) -> str:
    """A conversa guardada, DECIFRADA (no banco ela fica cifrada desde a avaliação 26): o que o bot vai ler dela."""
    import json

    from app.models.conversa_whatsapp import ConversaWhatsapp

    return json.dumps(assistente._ler_conversa(db.query(ConversaWhatsapp).one())[0], ensure_ascii=False)


def _token(db, conta, *produtos):
    """O token PRÓPRIO da conta (o valor não importa: o bot só confere que existe)."""
    db.add_all([VinculoProduto(gs_user_id=conta.id, produto=p, usuario_remoto_id="1", token_cifrado="x")
                for p in produtos])
    db.commit()
    db.refresh(conta)


def _empresa(db):
    """A O&M ativa de quem fala com o bot — conta sem empresa (ou de empresa desligada) não é
    atendida."""
    from app.models.empresa import Empresa

    emp = db.query(Empresa).filter_by(nome="O&M do bot").one_or_none()
    if emp is None:
        emp = Empresa(nome="O&M do bot")
        db.add(emp)
        db.commit()
    return emp


def _conta(db, apelido, telefone, ativo=True, bot=True):
    u = User(apelido=apelido, email=f"{apelido}@x.com", nome=apelido.title(), perfil=Perfil.CLIENTE,
             telefone=telefone, ativo=ativo, bot_meuplano=bot, bot_meuwatt=bot, empresa_id=_empresa(db).id)
    db.add(u)
    db.commit()
    if bot:
        _token(db, u, "meuwatt", "meuplano")
    return u


def test_o_numero_casa_com_a_conta_mesmo_sem_o_nono_digito(db):
    dono = _conta(db, "dono", "+5517997377626")
    assert assistente.conta_do_telefone(db, "+5517997377626").id == dono.id
    # o WhatsApp às vezes entrega o número antigo, sem o 9
    assert assistente.conta_do_telefone(db, "+551797377626").id == dono.id
    assert assistente.conta_do_telefone(db, "+5516997377626") is None   # outro DDD


def test_numero_ambiguo_ou_de_conta_inativa_nao_e_atendido(db):
    _conta(db, "a", "+5517997377626")
    _conta(db, "b", "+551797377626")          # mesmo DDD e 8 finais
    assert assistente.conta_do_telefone(db, "+5517997377626") is not None  # exato desempata
    _conta(db, "c", "+5511912345678", ativo=False)
    assert assistente.conta_do_telefone(db, "+5511912345678") is None


async def test_numero_desconhecido_recebe_o_aviso_e_nada_mais(db, monkeypatch):
    enviados = []

    async def _enviar(**k):
        enviados.append(k)
        return {"ok": True}

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    await assistente.atender({"telefone": "+5511900000000", "tipo": "text", "texto": "oi", "wamid": "w1"})
    assert [e["texto"] for e in enviados] == [assistente.DESCONHECIDO]
    # cadastrado mas sem a chave do gerente: nem chega à IA
    _conta(db, "sem.bot", "+5511900000000", bot=False)
    await assistente.atender({"telefone": "+5511900000000", "tipo": "text", "texto": "oi", "wamid": "w2"})
    assert enviados[-1]["texto"] == assistente.NAO_LIBERADO


async def test_pergunta_so_de_manutencao_volta_direto_do_meuplano(db, monkeypatch):
    """Velocidade: o orquestrador decide numa rodada e a resposta do meuPlano É a resposta."""
    chamadas_llm = []

    async def _llm(msgs, ferramentas=None):
        chamadas_llm.append(msgs)
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "manutencao", "arguments": '{"pergunta": "OS abertas de Pereiras"}'}}]}

    async def _manutencao(ctx, a):
        assert a["pergunta"] == "OS abertas de Pereiras"
        return {"texto": "Pereiras tem 2 OS abertas."}

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setitem(assistente.FERRAMENTAS, "manutencao", (_manutencao, assistente._MANUTENCAO))
    ctx = ger.Contexto(db=db, user=_conta(db, "dono", "+5517997377626"), telefone="+5517997377626")
    r = await assistente.responder(ctx, [{"role": "user", "content": "tem OS aberta em Pereiras?"}])
    assert r == "Pereiras tem 2 OS abertas." and len(chamadas_llm) == 1


async def test_erro_de_uma_ferramenta_vira_frase_para_o_modelo(db, monkeypatch):
    rodadas = iter([
        {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {"name": "geracao", "arguments": '{"usina": "x"}'}}]},
        {"content": "Não achei essa usina."},
    ])
    vistos = []

    async def _llm(msgs, ferramentas=None):
        vistos.append(msgs[-1])
        return next(rodadas)

    monkeypatch.setattr(assistente, "_llm", _llm)
    ctx = ger.Contexto(db=db, user=_conta(db, "dono", "+5517997377626"), telefone="+5517997377626")
    assert await assistente.responder(ctx, [{"role": "user", "content": "geração da x"}]) == "Não achei essa usina."
    assert vistos[-1]["role"] == "tool" and "erro" in vistos[-1]["content"]


@pytest.mark.parametrize("vivo,parcial,esperado", [(12375.0, 641.5, 12375.0)])
def test_hoje_sai_da_leitura_ao_vivo(vivo, parcial, esperado):
    h = ger.hoje().isoformat()
    r = {"start_date": h, "total_generation_kwh": parcial, "total_capacity_kwp": 1000,
         "daily_summaries": [{"date": h, "generation_kwh": parcial}],
         "inverters": [{"sn": "A", "total_yield_kwh": parcial}],
         "chart_data": {"daily_generation": {"A": [{"t": h, "y": parcial}]}}}
    ger._hoje_ao_vivo(r, {"energy_today_kwh": vivo, "inverters": [{"serial_number": "A", "energy_today_kwh": vivo}]})
    assert r["total_generation_kwh"] == esperado and r["inverters"][0]["total_yield_kwh"] == esperado
    assert r["daily_summaries"][0]["generation_kwh"] == esperado


def test_markdown_do_meuplano_vira_formato_de_whatsapp():
    t = "# OS na Pirapozinho\n\n**2 abertas**\n\n| Nº | Status |\n|:--:|:---|\n| 1601 | PROGRAMADA |"
    assert assistente.para_whatsapp(t) == "*OS na Pirapozinho*\n\n*2 abertas*\n\nNº · Status\n1601 · PROGRAMADA"


async def test_o_bot_le_com_o_token_dela_e_so_o_que_o_gs_concede(db, monkeypatch, usinas):
    """O token PRÓPRIO enxerga duas usinas; o GS concedeu uma: o bot fala só da concedida."""
    from app.models.user import UserPlantAccess
    from app.services import integracoes, vinculos

    class _MW:
        async def usinas(self):
            return [{"slug": "porto-ferreira", "name": "Porto", "id": 1},
                    {"slug": "ribeirao-bonito", "name": "RB", "id": 2}]

    async def _da_plataforma(*_a, **_k):
        raise AssertionError("o bot não lê com a credencial da plataforma")

    def _o_dela(db_, conta_id, *, so_proprio=False):
        assert so_proprio and conta_id == dono.id
        return _MW()

    monkeypatch.setattr(integracoes, "cliente_meuwatt", _da_plataforma)
    monkeypatch.setattr(vinculos, "cliente_meuwatt", _o_dela)
    dono = _conta(db, "dono", "+5517997377626")
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=usinas[0].id))
    db.commit()
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    await ger.preparar(ctx)
    assert set(ctx.usinas) == {"porto-ferreira"}


async def test_gerente_poe_celular_e_libera_o_bot_sem_repetir_numero(db, monkeypatch):
    """Celular de outra conta é recusado (o bot ficaria sem saber quem é); sem celular não libera."""
    from fastapi import HTTPException

    from app.api.v1.empresa import ContaPatch, editar_conta_da_empresa
    from app.models.empresa import Empresa

    emp = Empresa(nome="O&M")
    db.add(emp)
    db.commit()
    gerente = User(apelido="ger", email="g@x.com", nome="Ger", perfil=Perfil.GESTOR_EMPRESA, empresa_id=emp.id)
    cli = User(apelido="cli", email="c@x.com", nome="Cli", perfil=Perfil.CLIENTE, empresa_id=emp.id)
    db.add_all([gerente, cli])
    db.commit()
    _conta(db, "outro", "+5517997377626")

    with pytest.raises(HTTPException) as e:
        await editar_conta_da_empresa(cli.id, ContaPatch(bot_meuplano=True), db, gerente)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await editar_conta_da_empresa(cli.id, ContaPatch(telefone="(17) 99737-7626"), db, gerente)
    assert e.value.status_code == 409
    # celular certo, mas sem o token DELA: não libera
    with pytest.raises(HTTPException) as e:
        await editar_conta_da_empresa(cli.id, ContaPatch(telefone="(16) 99999-8888", bot_meuwatt=True), db, gerente)
    assert e.value.status_code == 400 and "token do meuWatt" in e.value.detail
    _token(db, cli, "meuwatt")
    r = await editar_conta_da_empresa(cli.id, ContaPatch(telefone="(16) 99999-8888", bot_meuwatt=True), db, gerente)
    assert r.telefone == "(16) 9 9999-8888" and r.bot_meuwatt and not r.bot_meuplano
    # o helper (com a porta dele configurada) reconhece a pessoa pelo token do meuWatt
    from app.services import assistente_helper

    monkeypatch.setattr(assistente_helper, "configurado", lambda: True)
    r = await editar_conta_da_empresa(cli.id, ContaPatch(bot_helper=True, bot_meuwatt=True), db, gerente)
    assert r.bot_helper
    # o meuPlano pede o token dele
    with pytest.raises(HTTPException):
        await editar_conta_da_empresa(cli.id, ContaPatch(bot_meuplano=True), db, gerente)
    r = await editar_conta_da_empresa(cli.id, ContaPatch(telefone=""), db, gerente)
    assert r.telefone is None and not (r.bot_meuwatt or r.bot_meuplano or r.bot_helper)


async def test_so_as_ferramentas_dos_produtos_liberados_chegam_a_ia(db, monkeypatch):
    """Liberado só meuWatt: a IA nem recebe a de manutenção — e se pedir, é recusada."""
    so_mw = _conta(db, "so.mw", "+5511911112222")
    so_mw.bot_meuplano = False
    db.commit()
    vistas = []

    async def _llm(msgs, ferramentas=None):
        vistas.append({f["function"]["name"] for f in ferramentas or []})
        if len(vistas) == 1:
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "manutencao", "arguments": '{"pergunta": "OS"}'}}]}
        return {"content": "Manutenção não liberada."}

    monkeypatch.setattr(assistente, "_llm", _llm)
    ctx = ger.Contexto(db=db, user=so_mw, telefone=so_mw.telefone)
    assert await assistente.responder(ctx, [{"role": "user", "content": "tem OS?"}]) == "Manutenção não liberada."
    assert "manutencao" not in vistas[0] and "geracao" in vistas[0]


async def test_o_bot_nunca_le_com_o_token_da_empresa(db, monkeypatch):
    """Regra do dono: cada um usa o bot com o SEU token. O aplicativo cai no da empresa; o bot,
    não — o assistente do meuPlano responderia ao cliente com a carteira inteira dela."""
    from cryptography.fernet import Fernet

    from app.core import cripto
    from app.models.empresa import Empresa
    from app.models.integracao import Integracao, Produto
    from app.services import vinculos

    chave = Fernet.generate_key()
    monkeypatch.setattr(cripto, "_fernet", lambda: Fernet(chave))
    emp = Empresa(nome="O&M")
    db.add(emp)
    db.commit()
    db.add_all([Integracao(produto=Produto.MEUPLANO, base_url="https://mp"),        # o endereço
                Integracao(produto=Produto.MEUPLANO, base_url="https://mp", empresa_id=emp.id, ativa=True,
                           token_cifrado=cripto.cifrar("mp_pat_DaEmpresa"))])
    cli = User(apelido="cli", email="c@x.com", nome="Cli", perfil=Perfil.CLIENTE, empresa_id=emp.id,
               telefone="+5516999998888", bot_meuplano=True)
    db.add(cli)
    db.commit()

    assert vinculos.token_do_cliente(db, cli.id, Produto.MEUPLANO) == "mp_pat_DaEmpresa"   # o app
    with pytest.raises(vinculos.SemConexao):
        vinculos.token_do_cliente(db, cli.id, Produto.MEUPLANO, so_proprio=True)            # o bot
    assert not cli.bot_liberado and assistente.permitidas(cli) == []
    r = await assistente.manutencao(ger.Contexto(db=db, user=cli, telefone=cli.telefone), {"pergunta": "OS?"})
    assert "token do meuPlano" in r["erro"]


def test_sem_o_token_a_parte_liberada_fica_parada_e_o_resto_do_cadastro_salva(db):
    """Token removido depois de liberar: a parte para (não some da tela) e salvar o cadastro
    não trava por isso. Colar o token de novo a religa."""
    from app.services import cadastro

    u = _conta(db, "dono", "+5517997377626")
    assert u.bot_ativo == {"bot_meuwatt", "bot_meuplano"}
    db.delete(next(v for v in u.vinculos if v.produto == "meuplano"))
    db.commit()
    db.refresh(u)
    assert u.bot_ativo == {"bot_meuwatt"} and assistente.permitidas(u) == list(ger.FERRAMENTAS)
    cadastro.liberar_bot(u, "bot_meuplano", True)          # já estava ligada: não reconfere
    assert u.bot_meuplano


async def test_cada_mensagem_vira_uma_linha_no_log_do_bot(db, monkeypatch):
    """O que o dono pediu para o adm-gs: "vejo log dos bots". Número sem cadastro, conta sem
    liberação e a resposta entram — com quem, a empresa, a pergunta e as ferramentas."""
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot

    async def _enviar(**k):
        return {"ok": True}

    async def _llm(msgs, ferramentas=None):
        if len([m for m in msgs if m.get("role") == "tool"]) == 0:
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "manutencao", "arguments": '{"pergunta": "OS abertas"}'}}]}
        return {"content": "ok"}

    async def _manutencao(ctx, a):
        return {"texto": "*2 OS abertas*"}

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente.whatsapp, "digitando", _nada)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setitem(assistente.FERRAMENTAS, "manutencao", (_manutencao, assistente.FERRAMENTAS["manutencao"][1]))
    monkeypatch.setattr(ger, "preparar", _nada)
    monkeypatch.setattr(assistente.get_settings(), "deepseek_api_key", "x")

    await assistente.atender({"telefone": "+5511900000001", "tipo": "text", "texto": "oi", "wamid": "w1"})
    dono = _conta(db, "dono", "+5517997377626")
    # O número estava numa conversa de OUTRA conta: o histórico dela não entra nesta.
    db.add(ConversaWhatsapp(telefone=dono.telefone, gs_user_id=dono.id + 999,
                            mensagens='[{"role": "user", "content": "segredo da outra conta"}]'))
    db.commit()
    await assistente.atender({"telefone": "+5517997377626", "tipo": "text", "texto": "OS abertas?", "wamid": "w2"})

    linhas = db.query(RegistroBot).order_by(RegistroBot.id).all()
    assert [(r.resultado, r.gs_user_id) for r in linhas] == [("sem_conta", None), ("respondeu", dono.id)]
    assert linhas[1].pergunta == "OS abertas?" and linhas[1].ferramentas == "manutencao"
    # o texto livre do meuPlano fica fora do log (avaliação 28); a pessoa recebeu "*2 OS abertas*"
    assert linhas[1].resposta == assistente.RESPOSTA_OMITIDA and linhas[1].duracao_ms is not None
    conversa = db.query(ConversaWhatsapp).one()
    assert conversa.gs_user_id == dono.id and "segredo da outra conta" not in _conversa_em_claro(db)


# ── o helper pelo bot: ação só com CONFIRMO <código>, conferido pelo Gestão Solar ──────


@pytest.fixture(autouse=True)
def _sem_portao_do_catalogo(request, monkeypatch):
    """O portão "nunca chutar" (driver/comando fora do catálogo) tem os testes dele, marcados com
    `portao`; nos outros os pedidos falsos não trazem driver."""
    from app.services import assistente_helper

    monkeypatch.setattr(assistente_helper, "_drivers", None)
    if "portao" not in request.keywords:
        async def livre(*_a, **_k):
            return None
        monkeypatch.setattr(assistente_helper, "_comando_inexistente", livre)


class _HelperFalso:
    def __init__(self):
        self.confirmadas = []

    async def chamar(self, rota, corpo, origem, metodo="POST"):
        if rota == "/api/act":
            return {"ok": True, "tipo": "proposta", "proposta": "P-1", "resumo": "Desligar o inversor 3", "expira_em_s": 120}
        return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": {"plants": ["pirapozinho"]}}

    async def confirmar(self, proposta, confirmado_por, origem):
        self.confirmadas.append((proposta, confirmado_por))
        return {"ok": True, "tipo": "execucao", "resumo": "Desligar o inversor 3", "status_http": 200}

    async def ferramentas(self):
        return {"ok": True, "rotas": []}


@pytest.fixture
def helper_ligado(monkeypatch):
    from app.services import assistente_helper

    falso = _HelperFalso()
    monkeypatch.setattr(assistente_helper, "_cliente", lambda db, user: falso)
    monkeypatch.setattr(assistente_helper, "configurado", lambda: True)
    assistente_helper.PENDENTES.clear()
    return falso


async def test_acao_do_helper_so_roda_com_a_senha_de_atuacao_da_propria_pessoa(db, helper_ligado):
    """Pedido do dono (24/10/2026): "o bot peça senha para qualquer ação que envolva atuação
    (desligar, ligar, gravar); ler não precisa"."""
    from app.core.security import gerar_hash_senha
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    outro = _conta(db, "outro", "+5517997370000")
    for u in (dono, outro):
        u.bot_helper = True
        u.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    assert {"usina_helper", "usina_helper_catalogo"} <= set(assistente.permitidas(dono))
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)

    # Leitura passa direto, sem senha; ação NÃO roda — fica esperando a senha.
    assert (await h.usina_helper(ctx, {"rota": "/api/registry/plants"}))["status_http"] == 200
    proposta = await h.usina_helper(ctx, {"rota": "/api/act", "corpo": {"acao": "off"}})
    assert "NADA foi executado" in proposta["instrucao"] and "SENHA DE" in proposta["instrucao"]
    assert "codigo" not in proposta and helper_ligado.confirmadas == []
    h.mostrada(dono.id)                                    # o resumo saiu (o que `_atender` marca)

    # Outra pessoa, com a MESMA senha, não executa a ação de ninguém.
    assert "não há ação esperando" in (await h.confirmar_por_mensagem(db, outro, outro.telefone, "482913")).lower()
    assert "não confere" in await h.confirmar_por_mensagem(db, dono, dono.telefone, "483913")
    assert helper_ligado.confirmadas == []
    # A senha certa, da própria pessoa: executa UMA vez, e diz ao helper como confirmou.
    assert (await h.confirmar_por_mensagem(db, dono, dono.telefone, "confirmo 482913")).startswith("✅")
    assert helper_ligado.confirmadas == [("P-1", "pin")]
    assert "não há ação esperando" in (await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913")).lower()
    # Mensagem comum não é senha.
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "qual a geração de hoje?") is None


async def test_sem_senha_de_atuacao_o_bot_so_le(db, helper_ligado):
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    dono.bot_helper = True
    db.commit()
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    proposta = await h.usina_helper(ctx, {"rota": "/api/act", "corpo": {"acao": "off"}})
    assert proposta["sem_senha_de_atuacao"] and dono.id not in h.PENDENTES
    assert "não tem senha de atuação" in await h.confirmar_por_mensagem(db, dono, dono.telefone, "confirmo 482913")
    # Número solto de quem não tem senha é só um número: segue para a conversa.
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "2024") is None
    assert helper_ligado.confirmadas == []


async def test_senha_errada_bloqueia_e_sem_acao_a_resposta_nao_entrega_a_senha(db, helper_ligado):
    """Sem ação esperando, senha certa e errada recebem a MESMA frase (senão mandar números até
    a frase mudar descobriria a senha). TODA conferência que falha conta — a de antes da ação
    também —, e 5 falhas descartam e bloqueiam."""
    from app.core.security import gerar_hash_senha
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    dono.bot_helper, dono.senha_atuacao_hash = True, gerar_hash_senha("482913")
    db.commit()
    certa = await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913")
    errada = await h.confirmar_por_mensagem(db, dono, dono.telefone, "111222")
    assert certa == errada

    def turno():
        return ger.Contexto(db=db, user=dono, telefone=dono.telefone)

    await h.usina_helper(turno(), {"rota": "/api/act", "corpo": {"acao": "off"}})
    h.mostrada(dono.id)
    for i in range(2, h.TENTATIVAS):                    # a errada de cima já contou 1
        assert f"({i} de {h.TENTATIVAS})" in await h.confirmar_por_mensagem(db, dono, dono.telefone, "000111")
    assert "bloqueadas" in await h.confirmar_por_mensagem(db, dono, dono.telefone, "000111")
    await h.usina_helper(turno(), {"rota": "/api/act", "corpo": {"acao": "off"}})
    h.mostrada(dono.id)
    assert "bloqueadas" in await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913")
    assert helper_ligado.confirmadas == []
    h.nova_senha(dono.id)                                  # o gerente define outra: zera o bloqueio
    assert (await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913")).startswith("✅")


def test_a_senha_de_atuacao_nao_pode_ser_facil():
    from app.services.assistente_helper import validar_senha_atuacao

    for ruim in ("4821", "48213", "123456789", "12a456", "111111", "123456", "987654"):
        with pytest.raises(ValueError):
            validar_senha_atuacao(ruim)
    assert validar_senha_atuacao(" 482913 ") == "482913"


async def test_liberar_o_helper_pede_a_porta_configurada_e_o_token_do_meuwatt(db, monkeypatch):
    from fastapi import HTTPException

    from app.services import assistente_helper, cadastro

    conta = _conta(db, "sem.mw", "+5517997371111", bot=False)
    monkeypatch.setattr(assistente_helper, "configurado", lambda: False)
    with pytest.raises(HTTPException) as e:
        cadastro.liberar_bot(conta, "bot_helper", True)
    assert e.value.status_code == 400 and "helper" in e.value.detail
    monkeypatch.setattr(assistente_helper, "configurado", lambda: True)
    with pytest.raises(HTTPException) as e:
        cadastro.liberar_bot(conta, "bot_helper", True)
    assert "token do meuWatt" in e.value.detail
    _token(db, conta, "meuwatt")
    cadastro.liberar_bot(conta, "bot_helper", True)
    assert conta.bot_helper and "bot_helper" in conta.bot_ativo


async def test_mensagem_que_chegou_horas_depois_nao_e_respondida(db, monkeypatch):
    """24/10/2026: a fila do gateway travou e havia mensagens de dois dias antes esperando.
    Destravada, o bot responderia ao passado — agora fica no log como `atrasada`."""
    from datetime import UTC, datetime, timedelta

    from app.models.conversa_whatsapp import RegistroBot

    enviados = []

    async def _enviar(**k):
        enviados.append(k)
        return {"ok": True}

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    dono = _conta(db, "dono", "+5517997377626")
    velha = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    await assistente.atender({"telefone": dono.telefone, "tipo": "text", "texto": "oi", "wamid": "w1", "ocorrida_em": velha})
    assert enviados == []
    linha = db.query(RegistroBot).one()
    assert (linha.resultado, linha.gs_user_id) == ("atrasada", dono.id)
    # O log mostra a hora em que a pessoa MANDOU (dois dias atrás), não a da chegada.
    enviada = linha.em if linha.em.tzinfo else linha.em.replace(tzinfo=UTC)
    assert abs((enviada - datetime.fromisoformat(velha)).total_seconds()) < 1
    assert "Chegou ao bot só em" in linha.erro


# ── o meuPlano pelo bot: a proposta de lá (criar OS…) também só roda com CONFIRMO ───────


class _MeuPlanoFalso:
    def __init__(self):
        self.conversas, self.aplicadas = [], []

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        return 1

    async def assistente_run(self, token, run_id):
        return {"status": "DONE", "type": "proposal", "action": "criar_ordem_servico",
                "args": {"usina_id": 37, "nome": "Roçagem de 5 ruas"},
                "preview": {"summary": "Abrir a OS 'Roçagem de 5 ruas' na UFV Ibitinga",
                            "lines": [{"kind": "os", "text": "Técnico: Michel"}], "warnings": []}}

    async def assistente_aplicar(self, token, acao, args):
        self.aplicadas.append((acao, args))
        return {"ok": True, "message": "Ação aplicada.", "data": {"os_id": 1639, "status": "PROGRAMADA"}}


async def test_a_os_que_o_meuplano_propoe_e_criada_com_o_sim_da_pessoa_sem_senha(db, monkeypatch):
    """Ação do meuPlano (criar/concluir OS) confirma com SIM — a senha de atuação é para
    equipamento ("desligar, ligar, gravar"). Em 24/10/2026 o bot cobrava a senha para concluir uma
    OS de quem nem tinha senha, e repetia isso a cada resposta. A conversa vai junto ao meuPlano."""
    from app.services import assistente_helper as h
    from app.services import vinculos

    falso = _MeuPlanoFalso()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db, uid, so_proprio=False: falso)

    async def _sem_espera(_):
        return None

    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    dono = _conta(db, "dono", "+5517997377626")                 # SEM senha de atuação
    outro = _conta(db, "outro", "+5517997370000")
    antes = [{"role": "user", "content": "Serviço novo"}, {"role": "assistant", "content": "Confirma que eu crie assim?"}]
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone, historico=antes)

    proposta = await assistente.manutencao(ctx, {"pergunta": "Sim, crie a OS"})
    assert falso.conversas[0][:2] == antes and falso.conversas[0][-1]["content"].startswith("Sim, crie a OS")
    assert "NADA foi executado" in proposta["instrucao"] and "Não fale de senha" in proposta["instrucao"]
    assert "SENHA DE ATUAÇÃO" not in proposta["instrucao"]
    assert "sem_senha_de_atuacao" not in proposta and proposta["detalhes"] == ["Técnico: Michel"]
    bloco = h.bloco_da_proposta(ctx.proposta)
    assert "toque em *Sim*" in bloco and "senha" not in bloco
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "sim") == h.ANTES_DO_RESUMO_SIM.format(
        limite=h._limite(ctx.proposta))                         # o resumo ainda não tinha saído
    h.mostrada(dono.id)

    assert await h.confirmar_por_mensagem(db, outro, outro.telefone, "sim") is None   # o SIM de outro é só conversa
    feito = await h.confirmar_por_mensagem(db, dono, dono.telefone, "Sim!")
    assert feito.startswith("✅ Feito no meuPlano") and "(OS 1639, PROGRAMADA)" in feito
    assert falso.aplicadas == [("criar_ordem_servico", {"usina_id": 37, "nome": "Roçagem de 5 ruas"})]
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "sim") is None     # uma vez só


class _MeuPlanoEmPassos:
    """O assistente do meuPlano: uma proposta por vez, e "Pronto." quando acabou."""

    def __init__(self):
        self.aplicadas, self.conversas = [], []
        self.respostas = [
            {"status": "DONE", "type": "proposal", "action": "criar_ordem_servico", "args": {"nome": "Roçagem"},
             "preview": {"summary": "Abrir a OS 'Roçagem de 5 ruas' na UFV Ibitinga", "lines": [], "warnings": []}},
            {"status": "DONE", "type": "proposal", "action": "mudar_status_os", "args": {"os_id": 1638},
             "preview": {"summary": "Mover a OS 1638 para CONCLUÍDA", "lines": [], "warnings": []}},
            {"status": "DONE", "type": "message", "text": "Pronto."},
        ]

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        return len(self.conversas)

    async def assistente_run(self, token, run_id):
        return self.respostas[run_id - 1]

    async def assistente_aplicar(self, token, acao, args):
        self.aplicadas.append(acao)
        return {"ok": True, "data": {"os_id": 1639, "status": "PROGRAMADA"} if acao == "criar_ordem_servico" else {}}


async def test_criar_a_os_e_concluir_a_outra_vira_dois_sim_em_sequencia(db, bot_local, monkeypatch):
    """A conversa do dono (24/10/2026): "Crie a OS e a tarefa. A OS 1638 mova para concluída" voltava
    só com a criação, cobrando senha. Agora: SIM cria, o bot segue sozinho para o próximo passo do
    mesmo pedido, SIM conclui — e ninguém fala de senha."""
    import json as _json

    from app.services import vinculos

    falso = _MeuPlanoEmPassos()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: falso)

    async def _sem_espera(_):
        return None

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": "Vou abrir a OS."}
        if msgs[-1]["content"].lower().startswith("crie"):
            return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
                "name": "manutencao", "arguments": _json.dumps({"pergunta": msgs[-1]["content"]})}}]}
        return {"content": "Entendi."}

    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    _resto(monkeypatch, *SEGUE_E_ACABA)
    dono = _conta(db, "dono", "+5517997377626")                 # SEM senha de atuação
    await assistente.atender(_ev(dono, 1, "Crie a OS e a tarefa. A OS 1638 mova para concluída"))
    # A fala da IA em texto, e o resumo numa mensagem só dele, com os botões Sim / Não.
    assert bot_local.enviados[-2] == "Vou abrir a OS." and bot_local.tipos[-2] == ("text", [])
    assert "Abrir a OS" in bot_local.enviados[-1] and bot_local.tipos[-1] == ("botoes", ["Sim", "Não"])
    # O toque no botão chega como mensagem `interactive` com o título e o id ("sim:<código do resumo>").
    from app.services import assistente_helper as h

    await assistente.atender({**_ev(dono, 2, "Sim"), "tipo": "interactive", "botao": f"sim:{h.PENDENTES[dono.id].codigo}"})
    assert falso.aplicadas == ["criar_ordem_servico"]
    assert bot_local.enviados[-2].startswith("✅ Feito no meuPlano") and "(OS 1639" in bot_local.enviados[-2]
    assert "Mover a OS 1638 para CONCLUÍDA" in bot_local.enviados[-1]
    assert bot_local.tipos[-1] == ("botoes", ["Sim", "Não"])
    assert "OS 1639" in falso.conversas[1][-1]["content"]      # o meuPlano sabe o que já foi feito
    await assistente.atender(_ev(dono, 3, "sim"))
    assert falso.aplicadas == ["criar_ordem_servico", "mudar_status_os"]
    assert bot_local.enviados[-1].startswith("✅ Feito no meuPlano: Mover a OS 1638")   # "Pronto." não vira mensagem
    assert not any("senha" in m.lower() for m in bot_local.enviados)


def test_resposta_grande_do_helper_perde_o_aninhado_e_nao_as_usinas():
    """O `/api/registry/plants` real: ~18 mil caracteres por 6 usinas. Cortado no meio, o bot
    via 4 usinas e nenhum status."""
    from app.services.assistente_helper import _corta

    usinas = [{"id": i, "label": f"Usina {i}", "api_slug": f"u{i}", "gateways": [{"ip": "10.0.0.1"} for _ in range(300)]}
              for i in range(6)]
    r = _corta({"status_http": 200, "resposta": {"ok": True, "plants": usinas}})
    assert r["status_http"] == 200 and [u["api_slug"] for u in r["resposta"]["plants"]] == [f"u{i}" for i in range(6)]
    assert "gateways" not in r["resposta"]["plants"][0] and "aviso" in r
    assert _corta({"status_http": 200, "resposta": {"x": 1}}) == {"status_http": 200, "resposta": {"x": 1}}


async def test_mensagens_seguidas_do_mesmo_numero_esperam_a_vez(db, monkeypatch):
    """24/10/2026: "Serviço novo" e, 8 s depois, "amanhã ele volta para terminar" rodaram
    juntas — duas respostas que se contradiziam, e a conversa ficou sem uma das trocas."""
    import asyncio

    rodando, sobreposicao = [], []

    async def _llm(msgs, ferramentas=None):
        if rodando:
            sobreposicao.append(msgs[-1]["content"])
        rodando.append(1)
        await asyncio.sleep(0.05)
        rodando.pop()
        return {"content": f"resposta a {msgs[-1]['content']}"}

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _nada)
    monkeypatch.setattr(assistente.whatsapp, "digitando", _nada)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    monkeypatch.setattr(assistente.get_settings(), "deepseek_api_key", "x")
    dono = _conta(db, "dono", "+5517997377626")

    await asyncio.gather(
        assistente.atender({"telefone": dono.telefone, "wa_id": "5517997377626", "tipo": "text", "texto": "Serviço novo"}),
        assistente.atender({"telefone": dono.telefone, "wa_id": "5517997377626", "tipo": "text", "texto": "amanhã ele volta"}),
    )
    assert sobreposicao == []
    conversa = [m["content"] for m in __import__("json").loads(_conversa_em_claro(db))]
    assert conversa == ["Serviço novo", "resposta a Serviço novo", "amanhã ele volta", "resposta a amanhã ele volta"]


# ── avaliação de 24/10/2026: empresa desligada, meuWatt fora, a senha fora do log ──────


@pytest.fixture
def bot_local(db, monkeypatch):
    """O turno inteiro (`atender`) contra o banco de teste, com o gateway e a IA de mentira."""
    import types

    estado = types.SimpleNamespace(enviados=[], ocultadas=[], textos_ocultados=[], llm=[], tipos=[], botoes=[],
                                   guardados=[], mascarados=[])

    async def _enviar(**k):
        estado.enviados.append(k.get("texto"))
        estado.guardados.append(k.get("guardar") or k.get("texto"))
        estado.tipos.append((k.get("tipo"), [b["titulo"] for b in k.get("botoes") or []]))
        estado.botoes.append([b["id"] for b in k.get("botoes") or []])
        return {"ok": True}

    async def _ocultar(mid, texto=None):
        estado.ocultadas.append(mid)
        estado.textos_ocultados.append(texto)

    async def _mascarar(telefone, valores):
        estado.mascarados.append((telefone, valores))

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        estado.llm.append(msgs[-1]["content"])
        return {"content": "resposta da IA"}

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente.whatsapp, "digitando", _nada)
    monkeypatch.setattr(assistente.whatsapp, "ocultar_texto", _ocultar)
    monkeypatch.setattr(assistente.whatsapp, "mascarar", _mascarar)
    monkeypatch.setattr(assistente, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(assistente.get_settings(), "deepseek_api_key", "x")
    return estado


async def test_empresa_desligada_ou_conta_sem_empresa_cala_o_bot(db, bot_local, monkeypatch):
    """"Desligar" a empresa no adm promete que a gente dela para de entrar NA HORA — o bot
    respondia normalmente."""
    from app.models.conversa_whatsapp import RegistroBot

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _conta(db, "dono", "+5517997377626")
    _empresa(db).ativa = False
    db.commit()
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "oi"})
    sem = _conta(db, "sem.empresa", "+5517997370000")
    sem.empresa_id = None
    db.commit()
    await assistente.atender({"id": 2, "telefone": sem.telefone, "wa_id": "2", "tipo": "text", "texto": "oi"})

    assert bot_local.llm == []
    assert "desligado" in bot_local.enviados[0] and "nenhuma empresa" in bot_local.enviados[1]
    assert [r.resultado for r in db.query(RegistroBot).order_by(RegistroBot.id)] == ["nao_liberado"] * 2


async def test_meuwatt_fora_nao_cala_a_manutencao(db, bot_local, monkeypatch):
    """Com o meuWatt fora (ou o token dele revogado), uma pergunta de manutenção recebia
    "Tive um problema para responder agora": a lista de usinas era pedida sem tratar erro."""
    import httpx

    from app.models.conversa_whatsapp import RegistroBot
    from app.models.plant import PlantLink
    from app.models.user import UserPlantAccess
    from app.services import vinculos

    class _MwFora:
        async def usinas(self):
            raise httpx.ConnectError("sem rota")

    dono = _conta(db, "dono", "+5517997377626")
    usina = PlantLink(nome="Usina", mw_plant_slug="usina", empresa_id=dono.empresa_id)
    db.add(usina)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=usina.id))
    db.commit()
    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda db_, uid, so_proprio=False: _MwFora())

    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "OS abertas?"})
    assert bot_local.enviados == ["resposta da IA"]
    assert db.query(RegistroBot).one().resultado == "respondeu"
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    await ger.preparar(ctx)
    assert ctx.mw_falha and ctx.mw is None
    with pytest.raises(ger.Recusa, match="não respondeu agora"):
        ger._usina(ctx, "Usina")


async def test_a_senha_nao_vai_a_ia_nem_ao_log_nem_ao_historico(db, bot_local, helper_ligado):
    from app.core.security import gerar_hash_senha
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    dono.bot_helper, dono.senha_atuacao_hash = True, gerar_hash_senha("482913")
    db.commit()
    await h.usina_helper(ger.Contexto(db=db, user=dono, telefone=dono.telefone),
                         {"rota": "/api/act", "corpo": {"acao": "off"}})
    h.mostrada(dono.id)
    await assistente.atender({"id": 77, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "482913"})

    assert bot_local.llm == [] and helper_ligado.confirmadas == [("P-1", "pin")]
    assert bot_local.ocultadas == [77] and bot_local.enviados[0].startswith("✅")
    linha = db.query(RegistroBot).one()
    assert linha.pergunta == h.OCULTA and linha.ferramentas == "senha_de_atuacao"
    conversa = _conversa_em_claro(db)
    assert "482913" not in conversa and h.OCULTA in conversa


async def test_a_linha_do_log_tem_a_hora_em_que_a_pessoa_mandou(db, bot_local, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.models.conversa_whatsapp import RegistroBot

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _conta(db, "dono", "+5517997377626")
    mandou = datetime.now(UTC) - timedelta(minutes=1)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "oi",
                              "ocorrida_em": mandou.isoformat()})
    em = db.query(RegistroBot).one().em
    assert abs(((em if em.tzinfo else em.replace(tzinfo=UTC)) - mandou).total_seconds()) < 1


def test_o_ajuste_em_massa_volta_item_por_item_com_a_conferencia():
    from app.services.assistente_helper import _desfecho

    r = {"ok": True, "resultado": {"fase": "fim", "conferencia": {"tudo_confirmado": True}, "itens": [
        {"nome": "TEMP-SKID-01", "sigla": "trd", "antes": 3, "valor": 2, "unidade": "s", "st": "ok"},
        {"nome": "TEMP-SKID-02", "sigla": "trd", "antes": 2, "valor": 2, "unidade": "s", "st": "ja"},
    ]}}
    texto = _desfecho("Ajuste em massa em 2 relés", r)
    assert "TEMP-SKID-01 trd: 3 → 2 s: ✅ confirmado" in texto and "já estava" in texto
    assert texto.endswith("✅ A leitura final confere com tudo.")
    r["resultado"]["conferencia"]["tudo_confirmado"] = False
    assert "NÃO confere" in _desfecho("Ajuste", r)
    assert "PODE ter chegado" in _desfecho("Desligar o inversor 3", {"ok": False, "incerto": True})


async def test_o_helper_que_nao_responde_a_tempo_e_incerto_e_nao_falha():
    """A confirmação do lote espera até ~150 s; com 60 s o bot dizia "tive um problema" com
    a ação rodando — e a pessoa mandaria de novo."""
    import httpx
    import respx

    from app.clients.helper_bot import HelperBot

    with respx.mock:
        respx.post("http://helper.test/api/bot/confirmar").mock(side_effect=httpx.ReadTimeout("lento"))
        respx.post("http://helper.test/api/bot/chamar").mock(side_effect=httpx.ConnectError("fora"))
        bot = HelperBot("http://helper.test", "gestao-solar", "chave", "tok")
        r = await bot.confirmar("P-1", "pin", "whatsapp")
        assert r["incerto"] and not r["ok"]
        assert (await bot.chamar("/api/read", {}, "whatsapp"))["reason"] == "helper_fora"


# ── avaliação de 24/10/2026 (5ª): GET no helper, senha em frase, motivo e releitura, recorte ──


class _HelperComGet(_HelperFalso):
    def __init__(self):
        super().__init__()
        self.chamadas = []

    async def chamar(self, rota, corpo, origem, metodo="POST"):
        self.chamadas.append((metodo, rota))
        if metodo == "GET":
            return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": {"drivers": ["huawei"]}}
        if rota == "/api/registry/plants":
            return {"ok": True, "tipo": "leitura", "status_http": 200,
                    "resposta": {"plants": [{"api_slug": "pirapozinho"}, {"api_slug": "de-outro"}]}}
        return await super().chamar(rota, corpo, origem, metodo)


@pytest.fixture
def helper_com_get(monkeypatch):
    from app.services import assistente_helper

    falso = _HelperComGet()
    monkeypatch.setattr(assistente_helper, "_cliente", lambda db, user: falso)
    monkeypatch.setattr(assistente_helper, "configurado", lambda: True)
    return falso


def _dono_com_usina(db, slug="pirapozinho"):
    from app.core.security import gerar_hash_senha
    from app.models.plant import PlantLink
    from app.models.user import UserPlantAccess

    dono = _conta(db, "dono", "+5517997377626")
    dono.bot_helper, dono.senha_atuacao_hash = True, gerar_hash_senha("482913")
    usina = PlantLink(nome="Pirapozinho", mw_plant_slug=slug, empresa_id=dono.empresa_id)
    db.add(usina)
    db.commit()
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=usina.id))
    db.commit()
    return dono


async def test_leitura_get_do_helper_nao_pede_senha(db, helper_com_get):
    """`GET /api/devices` (o catálogo de ações) ia como POST: o helper o tomava por escrita, o
    bot pedia a senha e o helper respondia 404."""
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    r = await h.usina_helper(ctx, {"rota": "/api/devices", "metodo": "GET"})
    assert r["status_http"] == 200 and "proposta_pendente" not in r and dono.id not in h.PENDENTES
    assert helper_com_get.chamadas == [("GET", "/api/devices")]


async def test_o_helper_respeita_as_usinas_liberadas_no_gestao_solar(db, helper_com_get):
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    lista = await h.usina_helper(ctx, {"rota": "/api/registry/plants"})
    assert [p["api_slug"] for p in lista["resposta"]["plants"]] == ["pirapozinho"]
    recusa = await h.usina_helper(ctx, {"rota": "/api/read", "corpo": {"plant_id": "de-outro"}})
    assert "não liberada" in recusa["erro"]
    recusa_get = await h.usina_helper(ctx, {"rota": "/api/healthcheck/state?plant_id=de-outro", "metodo": "GET"})
    assert "não liberada" in recusa_get["erro"]
    assert ("POST", "/api/read") not in helper_com_get.chamadas


async def test_a_senha_numa_frase_nao_executa_some_e_cancela(db, bot_local, helper_com_get, monkeypatch):
    """Só a mensagem que é APENAS a senha executa (avaliação 8): "a senha é 482913" cancela a
    ação, e o número some da IA, do log, do histórico e do gateway."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 9, "telefone": dono.telefone, "wa_id": "1", "tipo": "text",
                              "texto": "a senha é 482913"})
    assert helper_com_get.confirmadas == [] and dono.id not in h.PENDENTES
    assert bot_local.llm == [f"a senha é {h.SENHA_OCULTA}"] and bot_local.ocultadas == [9]
    assert bot_local.textos_ocultados == [f"a senha é {h.SENHA_OCULTA}"]       # o gateway guarda a frase sem a senha
    assert "Escondi a sua senha de atuação" in bot_local.enviados[0]
    assert h.ACAO_CANCELADA in bot_local.enviados[0]
    assert "482913" not in db.query(RegistroBot).one().pergunta
    assert "482913" not in _conversa_em_claro(db)


def test_a_falha_diz_o_motivo_e_o_sucesso_traz_a_releitura():
    from app.services.assistente_helper import _desfecho

    falha = _desfecho("Desligar INV-03", {"ok": False, "resposta": {"ok": False, "error": "write-protect ATIVO"},
                                          "releitura": {"status_http": 200, "resposta": {"status": "ligado"}}})
    assert "write-protect ATIVO" in falha and "Releitura do equipamento: status: ligado" in falha
    ok = _desfecho("Desligar INV-03", {"ok": True, "resumo": "Desligar INV-03",
                                       "releitura": {"status_http": 200, "resposta": {"ok": True, "status": "desligado",
                                                                                      "potencia_kw": 0}}})
    assert ok.startswith("✅ Executado") and "status: desligado · potencia_kw: 0" in ok
    assert "expirou" in _desfecho("Desligar INV-03", {"ok": False, "reason": "proposta_inexistente"})


async def test_ferramenta_nao_liberada_nao_roda_mesmo_que_a_ia_peca(db):
    """A IA só recebe as ferramentas liberadas; se ainda assim pedir outra, `_executar` recusa."""
    dono = _conta(db, "dono", "+5517997377626")
    dono.bot_meuwatt = False
    db.commit()
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    r = await assistente._executar(ctx, {"id": "c1", "function": {"name": "geracao", "arguments": "{}"}})
    assert "não está liberada" in r["erro"]


async def test_o_selo_do_helper_sem_token_de_ninguem(monkeypatch):
    """Com o cliente de verdade: "Authorization: Bearer " vazio derrubava a requisição (500)."""
    import httpx
    import respx

    from app.core.config import get_settings
    from app.services import assistente_helper as h

    s = get_settings()
    monkeypatch.setattr(s, "helper_bot_url", "http://helper.test")
    monkeypatch.setattr(s, "helper_bot_chave", "chave")
    with respx.mock:
        rota = respx.post("http://helper.test/api/bot/ferramentas").mock(return_value=httpx.Response(200, json={"ok": True}))
        rede = respx.post("http://helper.test/api/bot/rede").mock(
            return_value=httpx.Response(200, json={"ok": True, "vpn_ultimo_contato_s": 20}))
        assert (await h.alcancavel())[0] is True
        enviados = rota.calls.last.request.headers
        assert "authorization" not in enviados and enviados["x-mw-bot-chave"] == "chave"
        # O túnel responde, mas a VPN até as usinas está parada há 11 h: o selo NÃO fica verde.
        rede.mock(return_value=httpx.Response(200, json={"ok": True, "vpn_ultimo_contato_s": 42000}))
        alcancavel, frase = await h.alcancavel()
        assert alcancavel is False and "VPN" in frase and "11 h" in frase
        rota.mock(side_effect=httpx.ConnectError("fora"))
        assert (await h.alcancavel())[0] is False


# ── avaliação de 24/10/2026 (6ª): a senha em qualquer frase, "cancela", o texto do sistema ──


async def _armar(db, dono, rota="/api/act"):
    from app.services import assistente_helper as h

    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    await h.usina_helper(ctx, {"rota": rota, "corpo": {"plant_id": "pirapozinho", "acao": "off"}})
    h.mostrada(dono.id)                                    # o resumo saiu (o que `_atender` marca)
    return ctx


async def test_a_senha_em_qualquer_frase_nunca_vai_a_ia_nem_ao_log(db, bot_local, helper_com_get, monkeypatch):
    """S1: frase com a senha e SEM ação esperando; S4: frase de 100 caracteres com a senha e
    COM ação esperando. Nenhuma executa, e o número nunca chega à IA, ao log, ao histórico nem
    ao gateway."""
    from app.models.conversa_whatsapp import RegistroBot

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _dono_com_usina(db)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text",
                              "texto": "sim, pode fazer. senha 482913 ok"})
    await _armar(db, dono)
    longa = "olha, pode desligar sim o inversor que eu pedi agora há pouco, confirmo tudo, a senha é 482913 obrigado"
    assert len(longa) > 80
    await assistente.atender({"id": 2, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": longa})

    assert helper_com_get.confirmadas == [] and all("482913" not in m for m in bot_local.llm)
    assert bot_local.ocultadas == [1, 2]
    assert all("482913" not in (r.pergunta or "") for r in db.query(RegistroBot))
    assert "482913" not in _conversa_em_claro(db)


async def test_cancela_desarma_e_a_senha_depois_nao_executa(db, bot_local, helper_com_get):
    """S6: depois de "não, cancela isso" a ação continuava armada — e a senha a executava."""
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "não, cancela isso"})
    await assistente.atender({"id": 2, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "482913"})
    assert bot_local.enviados[0] == h.CANCELADO and bot_local.enviados[1] == h.NADA_ESPERANDO
    assert helper_com_get.confirmadas == [] and bot_local.llm == []


async def test_outra_pergunta_desarma_sem_contar_erro_de_senha(db, bot_local, helper_com_get):
    """S3: "troca para o inversor 1001" virava "Senha não confere (1 de 5)" e sumia da IA."""
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text",
                              "texto": "espera, troca para o inversor 1001"})
    assert bot_local.llm == ["espera, troca para o inversor 1001"]
    assert "foi cancelada" in bot_local.enviados[0] and dono.id not in h.PENDENTES and dono.id not in h._ERROS


async def test_o_texto_que_se_confirma_e_do_sistema_e_e_uma_acao_por_vez(db, bot_local, helper_com_get, monkeypatch):
    """N3: a pessoa confirmava o texto escrito pela IA. N7: duas propostas na mesma mensagem."""
    import json as _json

    from app.services import assistente_helper as h

    chamadas = iter([
        {"content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "usina_helper", "arguments": _json.dumps(
                {"rota": "/api/act", "corpo": {"plant_id": "pirapozinho"}})}},
            {"id": "b", "type": "function", "function": {"name": "usina_helper", "arguments": _json.dumps(
                {"rota": "/api/act", "corpo": {"plant_id": "pirapozinho"}})}}]},
        {"content": "Vou desligar tudo, inclusive o que você não pediu."},
    ])

    vistos = []

    async def _llm(msgs, ferramentas=None):
        vistos.extend(m["content"] for m in msgs if m.get("role") == "tool")
        return next(chamadas)

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _dono_com_usina(db)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "desliga o inversor 3"})
    assert sum("Uma ação por vez" in v for v in vistos) == 1     # a segunda proposta foi recusada
    final = bot_local.enviados[0]
    assert "Ação esperando a sua senha de atuação" in final and "• Desligar o inversor 3" in final
    assert final.count("•") == 1 and h.PENDENTES[dono.id].resumo == "Desligar o inversor 3"


def test_o_log_nao_guarda_o_segredo_que_o_meuplano_revelou():
    from app.services.assistente import _sem_segredos

    assert _sem_segredos("A senha do cadeado é ab12, e o PIN 4821.") == "A senha do cadeado é ••••, e o PIN ••••."
    assert _sem_segredos("[senha de atuação]") == "[senha de atuação]"


async def test_a_resposta_ao_pedido_de_senha_fica_fora_do_log(db, bot_local, monkeypatch):
    """O meuPlano revela a senha do equipamento a quem tem nível e a escreve do jeito que quiser (lista, linha de baixo,
    bloco de código): a resposta a um pedido de SENHA ou ACESSO fica fora do Log do bot — pela pergunta que a IA fez,
    mesmo quando a pessoa não disse "senha" —, e a pessoa a recebe inteira (avaliação 26)."""
    import json as _json

    from app.models.conversa_whatsapp import RegistroBot
    from app.services import vinculos

    respostas = iter(["**Senhas dos SmartLoggers:**\n• SL1: Huawei@123\n• SL2: Changeme1", "2 OS abertas: 1638 e 1843."])
    perguntas = iter(["Quais os acessos dos SmartLoggers da UFV Ibitinga?", "OS abertas da UFV Ibitinga"])

    class _MP:
        async def assistente_chat(self, token, mensagens):
            self.texto = next(respostas)
            return 7

        async def assistente_run(self, token, run_id):
            return {"status": "DONE", "type": "message", "text": self.texto}

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": _json.loads(msgs[-1]["content"])["texto"]}
        if msgs[-1]["content"] == "obrigado":
            return {"content": "De nada! A OS 1638 segue aberta."}            # sem o meuPlano: o texto fica no log
        return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
            "name": "manutencao", "arguments": _json.dumps({"pergunta": next(perguntas)})}}]}

    mp = _MP()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    monkeypatch.setattr(assistente.asyncio, "sleep", _nada)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "como entro nos SL de Ibitinga?"))
    assert "Huawei@123" in bot_local.enviados[-1] and "Changeme1" in bot_local.enviados[-1]
    await assistente.atender(_ev(dono, 2, "e as OS abertas?"))
    await assistente.atender(_ev(dono, 3, "obrigado"))
    linhas = db.query(RegistroBot).order_by(RegistroBot.id).all()
    # o que passou pelo meuPlano fica fora do log, trate ou não de acesso (avaliação 28); o resto fica
    assert [(r.pergunta, r.resposta) for r in linhas] == [
        ("como entro nos SL de Ibitinga?", assistente.RESPOSTA_OMITIDA), ("e as OS abertas?", assistente.RESPOSTA_OMITIDA),
        ("obrigado", "De nada! A OS 1638 segue aberta.")]
    assert all(assistente._e_de_credencial(p) for p in (
        "Qual a senha do SL1?", "Me passa o login do SmartLogger", "dados de acesso do ABS", "o acesso web do SL2",
        "Qual a chave do Wi-Fi?", "Como abro o cadeado do portão?", "Como eu entro no SmartLogger 1?",
        "entre com admin / X", "usuário admin, X", "a chave é ufvtiete", "Wi-Fi da UFV Tietê: rede x / y",
        "Wi-Fi:rede-ufv / changeme", "grava aí: Wi-Fi de Porto Ferreira, rede rede-ufv, changeme", "Para entrar no SmartLogger 1: usuário admin, X.",
        "grava aí: SmartLogger 2 de Pereiras, usuário admin, changeme", "Quais os acessos dos SmartLoggers da UFV?",
        "**Acessos:**", "Acesso: admin / X", "acesso ao sistema do ABS", "entre com o usuário instalador"))
    assert not any(assistente._e_de_credencial(p) for p in (
        "OS abertas da UFV Ibitinga", "Qual a geração de hoje?", "Feche a OS 1638", "o próximo passo do pedido",
        "o pino 3 do conector", "a chave seccionadora QS-01 abriu",
        "Ação esperando a sua senha de atuação até as 14:32", "[senha oculta]",
        # o que a 1ª versão tomava por acesso, no Log de produção (a resposta inteira saía do log)
        "técnico Michel (usuário 92, técnico de campo)", "a mensagem entra na fila", "Ele entra no turno amanhã", "tempo por local (Corredores, Perímetro, Acessos); Rendimento por dia",
        "as 5 ruas são corredores ou acessos/aceiro?", "O técnico não teve acesso à usina, o portão estava trancado",
        "Ele entra com a equipe amanhã", "o by-pass do inversor 13"))


def test_o_log_esconde_a_senha_das_linhas_de_baixo():
    """A linha que termina em ":" ("Senhas:", "**Senha do SmartLogger:**", "As credenciais são:") e o valor nas linhas
    de baixo — em lista, no bloco de código, sozinho —, a tabela sem a barra da frente, "Pass:"/"Pwd:", a senha que
    começa com palavra de prosa ("Nova@2024") e o valor entre crases antes da palavra: 11 de 15 passavam (avaliação 26)."""
    from app.services.assistente import _sem_segredos

    for texto, guardado in (
        ("**Senha do SmartLogger:**\n`Huawei@123`", "**Senha do SmartLogger:**\n`••••`"),
        ("**Senhas dos SmartLoggers:**\n• SL1: Huawei@123\n• SL2: Changeme1",
         "**Senhas dos SmartLoggers:**\n• SL1: ••••\n• SL2: ••••"),
        ("Senhas:\n- SL1 → Huawei@123\n- SL2 → Changeme1", "Senhas:\n- SL1 → ••••\n- SL2 → ••••"),
        ("As credenciais são:\n- usuário: admin\n- Huawei@123", "As credenciais são:\n- usuário: ••••\n- ••••"),
        ("Equipamento | Usuário | Senha\n--- | --- | ---\nSL1 | admin | Huawei@123",
         "Equipamento | Usuário | Senha\n--- | --- | ---\nSL1 | admin | •••• "),
        ("**Senha:** Nova@2024", "**Senha:** ••••"),
        ("Use `Huawei@123` (senha padrão de fábrica).", "Use `••••` (senha padrão de fábrica)."),
        ("Login: admin\nPass: Huawei@123", "Login: ••••\nPass: ••••"),          # na linha do acesso, o usuário também
        ("Pwd: Huawei@123", "Pwd: ••••"),
        ("A senha está abaixo:\n```\nHuawei@123\n```", "A senha está abaixo:\n```\n••••\n```"),
        ("Para o inversor 13 a senha é a de fábrica:\nHuawei@123", "Para o inversor 13 a senha é a de fábrica:\n••••"),
        ("Senhas:\n\nPara o SL2, use Changeme1 no acesso web.",
         "Senhas:\n\nPara o SL2, use •••• no acesso web."),
        ("A senha está abaixo:\n```\nentre com admin e changeme na tela\n```", "A senha está abaixo:\n```\n••••\n```"),
        ("**Senha do SL1:** Huawei@123", "**Senha do SL1:** ••••"),        # o ":" depois do número separa
    ):
        assert _sem_segredos(texto) == guardado, texto
    for prosa in (
        "Senha:\nNão encontrei a senha desse equipamento no meuPlano.",
        "**Senha:**\nSó quem tem nível 3 vê a senha. Peça ao gerente.",
        "A senha é definida no oem-gs.\nA OS 1638 foi fechada.",
        "Senhas:\n- a do SL1 é a mesma do SL2\n- a do ABS é pessoal",
        "Senha:\nNão cadastrada.",
        "| Equipamento | Senha |\n|---|---|\n| SL1 | |",
        "Ligue o SL1:\n- admin abre a tela\n- 2 vezes o reset",
        "A senha de atuação vale até as 14:32.",
    ):
        assert _sem_segredos(prosa) == prosa, prosa


def test_o_erro_do_log_tambem_esconde_a_senha(db):
    from app.models.conversa_whatsapp import RegistroBot

    assistente._registrar(db, "+5517997377626", None, "erro", erro="⚠️ … e disse: Senha do SL1: Huawei@123")
    assert db.query(RegistroBot).one().erro == "⚠️ … e disse: Senha do SL1: ••••"


# ── avaliação de 24/10/2026 (7ª): técnico, adivinhar a senha, bordas ──────────────────


async def test_o_tecnico_usa_o_helper_nas_usinas_da_empresa(db, helper_com_get):
    """O técnico não recebe usina no aplicativo; pelo bot, o recorte dele é a carteira da
    empresa — senão geração e helper nunca respondiam, com a tela dizendo "Respondendo"."""
    from app.models.plant import PlantLink
    from app.models.user import Perfil
    from app.services import assistente_helper as h

    tec = _conta(db, "tec", "+5517997370001")
    tec.perfil, tec.bot_helper = Perfil.TECNICO, True
    db.add(PlantLink(nome="Pirapozinho", mw_plant_slug="pirapozinho", empresa_id=tec.empresa_id))
    db.commit()
    assert [p.mw_plant_slug for p in ger.usinas_do_bot(db, tec)] == ["pirapozinho"]
    ctx = ger.Contexto(db=db, user=tec, telefone=tec.telefone)
    r = await h.usina_helper(ctx, {"rota": "/api/read", "corpo": {"plant_id": "pirapozinho"}})
    assert "erro" not in r


async def test_numero_em_frase_so_esconde_a_senha_e_nunca_conta_erro(db, helper_com_get):
    """Avaliação 9: IP, data, CEP, UC e protocolo sumiam da IA para quem tem senha. Agora só a
    SENHA conferida some; frase nunca conta erro nem bloqueia. E o oráculo tem teto: passadas
    `CONFERENCIAS_POR_HORA` conferências na hora, todo candidato some sem conferir."""
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    texto = "lê o 10.1.130.2 da UC 1234567 (protocolo 7654321) de 24/10/2026, CEP 14801-000, senha 482 913"
    analise = await h.analisar(dono, texto)
    assert not analise.pura and analise.escondeu_senha
    assert h.mascarar(texto, analise) == ("lê o 10.1.130.2 da UC 1234567 (protocolo 7654321) de 24/10/2026, "
                                          f"CEP 14801-000, senha {h.SENHA_OCULTA}")
    for i in range(h.CONFERENCIAS_POR_HORA):
        await h.confirmar_por_mensagem(db, dono, dono.telefone, f"a UC {1000000 + i}?", await h.analisar(dono, f"a UC {1000000 + i}?"))
    assert dono.id not in h._ERROS and dono.id not in h._BLOQUEIO
    # O teto: depois dele, nada é conferido e todo candidato some.
    sobra = await h.analisar(dono, "a UC 7777777 e a 482913")
    assert [m for _, _, m in sobra.trechos] == [h.OCULTO, h.OCULTO]


async def test_sem_acao_esperando_a_senha_numa_frase_some_e_o_numero_comum_fica(db, bot_local, helper_com_get, monkeypatch):
    """ "a 482913" (a senha) some e a pessoa é avisada; "a 482914" (outro número) chega à IA como
    está, sem contar erro nem bloquear ninguém. Na cópia GUARDADA, o número sem nome some, como todo número com cara
    de segredo (avaliação 28): por isso o gateway é chamado também para a 2ª."""
    from app.services import assistente_helper as h

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _dono_com_usina(db)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "a 482913"})
    await assistente.atender({"id": 2, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "a 482914"})
    assert bot_local.llm == [f"a {h.SENHA_OCULTA}", "a 482914"] and bot_local.ocultadas == [1, 2]
    assert "Escondi a sua senha de atuação" in bot_local.enviados[0]
    assert "482913" not in _conversa_em_claro(db) and dono.id not in h._ERROS


async def test_a_conferencia_da_senha_sai_do_laco_da_api(db, monkeypatch):
    """O pbkdf2 leva ~0,45 s: dentro do laço assíncrono, travava a API inteira."""
    from app.core.security import gerar_hash_senha
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    em_thread = []
    original = h.asyncio.to_thread

    async def _to_thread(fn, *a):
        em_thread.append(fn.__name__)
        return await original(fn, *a)

    monkeypatch.setattr(h.asyncio, "to_thread", _to_thread)
    assert (await h.analisar(dono, "senha 482913")).acertou and em_thread == ["conferir_senha"]


async def test_a_senha_some_do_gateway_ate_nos_caminhos_que_saem_cedo(db, bot_local):
    from datetime import UTC, datetime, timedelta

    from app.core.security import gerar_hash_senha
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    velha = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await assistente.atender({"id": 5, "telefone": dono.telefone, "wa_id": "1", "tipo": "text",
                              "texto": "pode ligar, senha 482913", "ocorrida_em": velha})
    assert bot_local.ocultadas == [5] and bot_local.enviados == []
    linha = db.query(RegistroBot).one()
    assert linha.resultado == "atrasada" and "482913" not in linha.pergunta and h.SENHA_OCULTA in linha.pergunta


async def test_parte_desligada_no_meio_nao_executa(db, helper_com_get):
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    dono.bot_helper = False                                # o gerente desligou o helper dela
    db.commit()
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913") == h.PARTE_DESLIGADA
    assert helper_com_get.confirmadas == []


async def test_o_bloco_diz_a_hora_limite(db, helper_com_get):
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    ctx = await _armar(db, dono)
    bloco = h.bloco_da_proposta(ctx.proposta)
    assert "responda só com a senha até as" in bloco and "em até" not in bloco


async def test_o_selo_fica_vermelho_sem_contato_com_a_vpn(monkeypatch):
    from app.services import assistente_helper as h

    monkeypatch.setattr(h, "configurado", lambda: True)
    respostas = iter([{"ok": True, "vpn_ultimo_contato_s": None}, {"ok": False}])

    class _Falso:
        def __init__(self, *a):
            pass

        async def ferramentas(self, espera_s=120):
            return {"ok": True}

        async def rede(self):
            return next(respostas)

    monkeypatch.setattr(h, "HelperBot", _Falso)
    vpn, nao_conferida = await h.alcancavel(), await h.alcancavel()
    assert vpn == (False, "Helper responde, mas a rede até as usinas (VPN) nunca fez contato.")
    assert nao_conferida[0] is False
    # a causa curta do selo (avaliação 17: dizia "helper fora do ar" quando era a VPN)
    assert h.rotulo_do_helper(*vpn) == "VPN das usinas parada"
    assert h.rotulo_do_helper(False, "Helper fora do alcance do bot: sem resposta") == "Helper fora do ar"
    # e a VPN que não deu para conferir não é "parada" (avaliação 18)
    assert h.rotulo_do_helper(*nao_conferida) == "VPN das usinas não conferida"
    assert h.rotulo_do_helper(True, "Helper e rede das usinas no ar") is None and h.rotulo_do_helper(None, "") is None


def test_leitura_sem_usina_nomeada_vem_so_com_as_liberadas():
    from app.services.assistente_helper import _so_liberadas

    feed = {"ok": True, "alarmes": [{"plant_id": "pirapozinho", "msg": "trip"}, {"plant_id": "de-outro", "msg": "x"},
                                    {"msg": "sem usina"}]}
    assert _so_liberadas(feed, {"pirapozinho"})["alarmes"] == [{"plant_id": "pirapozinho", "msg": "trip"},
                                                               {"msg": "sem usina"}]


# ── avaliação de 24/10/2026 (8ª): "qualquer outra mensagem cancela" vale mesmo ─────────


async def test_nao_faca_com_a_senha_nao_executa(db, bot_local, helper_com_get):
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text",
                              "texto": "não, cancela! a senha é 482913, mas NÃO faça"})
    # Frase com mais que o "não" vai à IA (avaliação 12: a correção se perdia), com a ação já caída.
    assert helper_com_get.confirmadas == [] and bot_local.ocultadas == [1] and "482913" not in bot_local.llm[-1]
    assert len(bot_local.enviados) == 1 and h.ACAO_CANCELADA in bot_local.enviados[0]


async def test_limpar_e_audio_cancelam_a_acao(db, bot_local, helper_com_get):
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "limpar"})
    await assistente.atender({"id": 2, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "482913"})
    await _armar(db, dono)
    await assistente.atender({"id": 3, "telefone": dono.telefone, "wa_id": "1", "tipo": "audio", "texto": None})
    await assistente.atender({"id": 4, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "482913"})
    assert helper_com_get.confirmadas == []
    assert bot_local.enviados[0].endswith(h.ACAO_CANCELADA) and bot_local.enviados[1] == h.NADA_ESPERANDO
    assert bot_local.enviados[2].endswith(h.ACAO_CANCELADA) and bot_local.enviados[3] == h.NADA_ESPERANDO


async def test_a_senha_com_separador_e_reconhecida_e_nao_vaza(db, bot_local, helper_com_get):
    """ "482 913" e "482-913" iam inteiros à IA, ao histórico e ao meuPlano."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "482 913"})
    assert helper_com_get.confirmadas == [("P-1", "pin")] and bot_local.llm == [] and bot_local.ocultadas == [1]
    escritas = ("senha 482-913", "482,913", "482  913", "482_913", "482 - 913", "482 . 913", "482–913")
    for i, escrita in enumerate(escritas, start=2):
        await _armar(db, dono)
        await assistente.atender({"id": i, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": escrita})
    assert len(helper_com_get.confirmadas) == 1 + len(escritas)
    # Lista e data com espaço não são a senha (avaliação 12).
    assert h.digitos_da_senha("12, 13, 14") is None and h.digitos_da_senha("24 / 10 / 2026") is None
    assert all("913" not in (r.pergunta or "") for r in db.query(RegistroBot))
    assert "913" not in _conversa_em_claro(db)


# ── avaliação 10 (24/10/2026): a senha em frase com pontuação, e a senha antes do resumo ──


def _ia_que_desliga(monkeypatch, pensando=None, chamou=None):
    """A IA de mentira: "desliga …" vira um pedido de ação ao helper; o resto, "Entendi"."""
    import json as _json

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": "Certo."}
        if msgs[-1]["content"].lower().startswith("desliga"):
            if chamou is not None:
                chamou.set()
            if pensando is not None:
                await pensando.wait()                      # a IA leva de 17 a 65 s
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "usina_helper",
                "arguments": _json.dumps({"rota": "/api/act", "corpo": {"plant_id": "pirapozinho"}})}}]}
        return {"content": "Entendi."}

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)


def _ev(dono, n, texto, quando=None):
    e = {"id": n, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": texto}
    return {**e, "ocorrida_em": quando} if quando else e


async def test_a_senha_mandada_antes_de_o_resumo_chegar_nao_executa(db, bot_local, helper_com_get, monkeypatch):
    """"desliga o inversor 13" e, sem esperar o bot, a senha: as duas saem do celular no mesmo
    minuto, e a segunda — esperando a vez — executava um resumo que a pessoa nunca leu. A hora
    da Meta (`ocorrida_em`) diz que ela saiu antes do resumo; a ação continua esperando."""
    from datetime import UTC, datetime

    from app.services import assistente_helper as h

    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    antes = datetime.now(UTC).isoformat()
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13", antes))
    assert "Ação esperando a sua senha" in bot_local.enviados[-1]
    await assistente.atender(_ev(dono, 2, "482913", antes))
    assert helper_com_get.confirmadas == [] and "antes de o resumo" in bot_local.enviados[-1]
    assert dono.id in h.PENDENTES and dono.id not in h._ERROS
    await assistente.atender(_ev(dono, 3, "482913", datetime.now(UTC).isoformat()))
    assert helper_com_get.confirmadas == [("P-1", "pin")] and bot_local.enviados[-1].startswith("✅")


async def test_a_senha_que_entrou_na_fila_antes_do_resumo_nao_executa(db, bot_local, helper_com_get, monkeypatch):
    """O caso real, sem depender do relógio da Meta: a senha chega enquanto a IA ainda pensa
    no pedido e espera a vez na fila do número — entrou ANTES de o resumo sair."""
    import asyncio as aio

    from app.services import assistente_helper as h

    pensando, chamou = aio.Event(), aio.Event()
    _ia_que_desliga(monkeypatch, pensando, chamou)
    dono = _dono_com_usina(db)
    pedido = aio.create_task(assistente.atender(_ev(dono, 1, "desliga o inversor 13")))
    await chamou.wait()
    senha = aio.create_task(assistente.atender(_ev(dono, 2, "482913")))
    for _ in range(3):
        await aio.sleep(0)                                 # a senha entra na fila do número
    pensando.set()
    await aio.gather(pedido, senha)
    assert "Ação esperando a sua senha" in bot_local.enviados[0]
    assert helper_com_get.confirmadas == [] and "antes de o resumo" in bot_local.enviados[1]
    assert dono.id in h.PENDENTES


async def test_o_resumo_que_nao_saiu_nao_deixa_acao_esperando(db, bot_local, helper_com_get, monkeypatch):
    """A Meta recusou o envio (o gateway responde `ok: false`): a pessoa não viu o resumo, e
    senha nenhuma pode confirmá-lo."""
    from app.services import assistente_helper as h

    async def _recusado(**k):
        bot_local.enviados.append(k.get("texto"))
        return {"ok": False, "status": "falhou"}

    _ia_que_desliga(monkeypatch)
    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _recusado)
    dono = _dono_com_usina(db)
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13"))
    assert dono.id not in h.PENDENTES
    await assistente.atender(_ev(dono, 2, "482913"))
    assert helper_com_get.confirmadas == [] and bot_local.enviados[-1] == h.NADA_ESPERANDO


async def test_a_senha_em_frase_some_com_qualquer_pontuacao_e_alem_do_limite(db, monkeypatch):
    """"Senha:482913", "senha,482913", "senha/482913" e a senha como 4º número da frase iam em
    claro à IA, ao histórico e ao log. O que não é a senha continua legível."""
    import re

    from app.services import assistente_helper as h

    monkeypatch.setattr(h, "conferir_senha", lambda d, guardado: d == "482913")
    dono = _dono_com_usina(db)
    for frase in ["Senha:482913 pode executar", "ok senha:482913", "senha,482913 vai", "minha senha/482913",
                  "ok:482913", "veja (482913)", "pode executar 482 913", "pode ir 482.913", "executa 4829-13",
                  "PIN 482913 agora", "a senha é 482913, 123 é a UC", "Senha:482913, 123",
                  "UCs 1234567, 2345678, 3456789 e a senha 482913",
                  "UCs 1234567, 2345678, 3456789, 4567890 e 482913",
                  "pin 482 913, UCs 1234567, 2345678, 3456789"]:
        h._CONFERENCIAS.clear()
        visto = h.mascarar(frase, await h.analisar(dono, frase))
        assert "482913" not in re.sub(r"[ .,_\-]", "", visto), (frase, visto)
    # O número logo depois de "senha" é conferido PRIMEIRO: reconhecido como a senha (e a pessoa
    # é avisada), em vez de sumir como "[número oculto]" por ser o 4º da frase.
    h._CONFERENCIAS.clear()
    frase = "UCs 1234567, 2345678, 3456789 e a senha 482913"
    assert h.mascarar(frase, await h.analisar(dono, frase)).endswith("a senha [senha oculta]")
    for frase, legivel in [
        ("o IP 10.1.130.2 e o 192.168.100.200 não respondem, senha 482913", ("10.1.130.2", "192.168.100.200")),
        ("data 24/10/2026, valor 1.500.000 e R$ 3,50; UC 1234567", ("24/10/2026", "1.500.000", "1234567")),
        ("inversores 13 15 20 parados; liga às 10:30 de 24-10-2026", ("13 15 20", "10:30", "24-10-2026")),
    ]:
        h._CONFERENCIAS.clear()
        visto = h.mascarar(frase, await h.analisar(dono, frase))
        assert all(p in visto for p in legivel), (frase, visto)


def test_o_log_esconde_o_numero_do_segredo_em_qualquer_forma():
    from app.services import assistente_helper as h
    from app.services.assistente import _sem_segredos

    for texto, guardado in [
        ("senha do cadeado 3262", "senha do cadeado ••••"),
        ("o código do portão 4455", "o código do portão ••••"),
        ("senha,482913 vai", "senha,•••• vai"),
        ("minha senha/482913", "minha senha/••••"),
        ("pin 482 913", "pin ••••"),
        ("Altere a senha do cadeado de pirapozinho para 3262", "Altere a senha do cadeado de pirapozinho para ••••"),
        ("a combinação do cadeado é 3262", "a combinação do cadeado é ••••"),
        ("senha 482 - 913 ok", "senha •••• ok"),                  # separador com espaço (avaliação 12)
        ("a senha é: 482 / 913", "a senha é: ••••"),
        # o trecho "do …" com número ("do inversor 13", "do IP …") passava em claro (avaliação 22)
        ("senha do inversor 13 é 4821", "senha do inversor 13 é ••••"),
        ("a senha do IP 10.1.130.2 é admin123", "a senha do IP 10.1.130.2 é ••••"),
        # o ":" depois do número do equipamento (avaliação 23: passavam em claro)
        ("Senha do inversor 13: 4821", "Senha do inversor 13: ••••"),
        ("Senha do SmartLogger 2: Huawei@123", "Senha do SmartLogger 2: ••••"),
        ("PIN do ABS 3: 1234", "PIN do ABS 3: ••••"),
        ("senha do cadeado do portão 2: 3262", "senha do cadeado do portão 2: ••••"),
        ("a senha é morango e o usuário é admin", "a senha é •••• e o usuário é ••••"),
    ]:
        assert _sem_segredos(texto) == guardado
    for texto in ["código de erro 2043 no inversor 3", "o código da OS 1639", "Senha não confere (2 de 5). Nada foi feito.",
                  h.ANTES_DO_RESUMO.format(limite="14:32"), "mande a senha de novo até as 14:32.",
                  "Para executar, responda só com a senha até as 14:32. Qualquer outra mensagem cancela.",
                  "🔒 *Ação esperando a sua senha de atuação*\n• Desligar o inversor 3", "[senha oculta]",
                  # o número do IDENTIFICADOR e a data não são o segredo (avaliação 22: sumiam do log)
                  "a senha da OS 1638 é a mesma de ontem", "nova senha 24/10", "senha do IP 10.1.130.2",
                  # a prosa — inclusive o aviso do próprio bot — fica inteira (avaliação 23: saía comida)
                  "Vence em 24/10/2026, a senha de atuação é definida no oem-gs",
                  "(Escondi a sua senha de atuação desta mensagem: ela é só para equipamento — ação do meuPlano se "
                  "confirma com Sim. Nada foi executado.)",
                  "(Escondi a sua senha de atuação desta mensagem: ela só vale sozinha, numa mensagem só dela.)",
                  "Sua senha de atuação é pessoal, não a passe a ninguém.", "a senha é comparada com a hora da Meta"]:
        assert _sem_segredos(texto) == texto


async def test_equipamento_pelo_ip_so_com_a_usina_liberada_junto(db, helper_com_get):
    """O helper confere o IP contra TODAS as usinas do token quando o pedido não diz a usina
    — mais do que o Gestão Solar liberou para a pessoa."""
    from app.services import assistente_helper as h

    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    for pedido in ({"rota": "/api/smartlogger/status", "corpo": {"ip": "10.1.130.2"}},
                   {"rota": "/api/abs/status", "corpo": {"ips": ["10.1.130.2"]}},
                   {"rota": "/api/abs/status?ip=10.1.130.2", "metodo": "GET"}):
        assert "usina junto" in (await h.usina_helper(ctx, pedido))["erro"]
    r = await h.usina_helper(ctx, {"rota": "/api/smartlogger/status", "corpo": {"ip": "10.1.130.2", "slug": "de-outro"}})
    assert "não liberada" in r["erro"] and helper_com_get.chamadas == []
    r = await h.usina_helper(ctx, {"rota": "/api/smartlogger/status", "corpo": {"ip": "10.1.130.2", "slug": "pirapozinho"}})
    assert "erro" not in r and helper_com_get.chamadas == [("POST", "/api/smartlogger/status")]


# ── avaliação 11 (24/10/2026): relógio, prazo, reação, entrega repetida, áudio ───────────


async def test_a_senha_e_comparada_com_a_hora_do_banco_e_nao_com_o_relogio_atrasado(
        db, bot_local, helper_com_get, monkeypatch):
    """O relógio da KingHost anda ~17 s atrás (NTP bloqueado lá). Com ele, a senha mandada 7 s
    ANTES de o resumo chegar parecia 10 s depois — e executava. A saída do resumo é marcada na
    hora do BANCO, a mesma régua da hora da Meta."""
    from datetime import UTC, datetime, timedelta

    from app.services import assistente_helper as h

    _ia_que_desliga(monkeypatch)
    certa = datetime.now(UTC) + timedelta(seconds=17)       # a hora certa; a daqui está 17 s atrás
    monkeypatch.setattr(assistente, "_agora_do_banco", lambda db_: certa)
    dono = _dono_com_usina(db)
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13"))
    await assistente.atender(_ev(dono, 2, "482913", (certa - timedelta(seconds=7)).isoformat()))
    assert helper_com_get.confirmadas == [] and "antes de o resumo" in bot_local.enviados[-1]
    assert dono.id in h.PENDENTES


async def test_a_senha_depois_do_prazo_diz_que_venceu_certa_ou_errada(db, bot_local, helper_com_get, monkeypatch):
    """A senha que chega depois do prazo recebia "Não há ação esperando senha", sem dizer que
    venceu. Agora diz — com a MESMA frase para a certa e para a errada (sem oráculo)."""
    import re
    from time import monotonic

    from app.services import assistente_helper as h

    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    for n, senha in ((1, "482913"), (3, "111222")):
        await assistente.atender(_ev(dono, n, "desliga o inversor 13"))
        h.PENDENTES[dono.id].expira = monotonic() - 1
        await assistente.atender(_ev(dono, n + 1, senha))
        assert "venceu" in bot_local.enviados[-1] and dono.id not in h.PENDENTES
    # a mesma frase (a hora de cada uma pode virar o minuto entre as duas voltas)
    assert re.sub(r"\d\d:\d\d", "HH:MM", bot_local.enviados[-1]) == re.sub(r"\d\d:\d\d", "HH:MM", bot_local.enviados[-3])
    assert helper_com_get.confirmadas == []


async def test_reacao_e_figurinha_nao_cancelam_a_acao_nem_ganham_resposta(db, bot_local, helper_com_get, monkeypatch):
    """O 👍 no resumo cancelava a ação ("Por enquanto eu entendo só mensagem de texto") e a
    senha mandada em seguida recebia "não há ação esperando" (avaliação 11)."""
    from app.services import assistente_helper as h

    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13"))
    enviadas = len(bot_local.enviados)
    for n, tipo in ((2, "reaction"), (3, "sticker")):
        await assistente.atender({"id": n, "telefone": dono.telefone, "wa_id": "1", "tipo": tipo, "texto": None})
    assert len(bot_local.enviados) == enviadas and dono.id in h.PENDENTES
    await assistente.atender(_ev(dono, 4, "482913"))
    assert helper_com_get.confirmadas == [("P-1", "pin")]


async def test_a_reacao_ao_resumo_que_espera_o_sim_faz_perguntar_de_novo(db, bot_local, monkeypatch):
    """Avaliação 22: o 👍 (reação) no resumo da ação do meuPlano era ignorado em silêncio, e a ação vencia sem
    aviso. Não confirma (pode ser só "vi"), mas o sistema pergunta de novo, com os botões do MESMO resumo."""
    from app.services import assistente_helper as h

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie a OS"))
    codigo, enviadas = h.PENDENTES[dono.id].codigo, len(bot_local.enviados)
    await assistente.atender({"id": 2, "telefone": dono.telefone, "wa_id": "1", "tipo": "reaction", "texto": None})
    assert falso.aplicadas == [] and dono.id in h.PENDENTES                       # não confirmou nem caiu
    assert len(bot_local.enviados) == enviadas + 1 and "O *Sim* vale para TUDO isto" in bot_local.enviados[-1]
    assert bot_local.botoes[-1] == [f"sim:{codigo}", f"nao:{codigo}"]
    h.PENDENTES.clear()                                                           # sem ação esperando: nada
    await assistente.atender({"id": 3, "telefone": dono.telefone, "wa_id": "1", "tipo": "reaction", "texto": None})
    assert len(bot_local.enviados) == enviadas + 1


async def test_a_mesma_entrega_duas_vezes_e_atendida_uma_vez_so(db, bot_local, helper_com_get, monkeypatch):
    """O gateway avisa na hora e, se o aviso falhar, a varredura repete: a mesma mensagem (a
    senha, inclusive) não pode ser processada duas vezes."""
    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13"))
    senha = _ev(dono, 2, "482913")
    await assistente.atender(senha)
    enviadas = len(bot_local.enviados)
    await assistente.atender(senha)
    assert len(bot_local.enviados) == enviadas and helper_com_get.confirmadas == [("P-1", "pin")]


class _TranscricaoFalsa:
    def __init__(self, texto):
        self.texto, self.ouvidos = texto, []

    async def transcrever(self, conteudo, tipo):
        self.ouvidos.append((conteudo, tipo))
        return self.texto


def _audio(monkeypatch, texto, *, com_token=True):
    from app.services import vinculos

    falso = _TranscricaoFalsa(texto)

    def _mp(db_, uid, so_proprio=False):
        assert so_proprio, "o áudio é transcrito com o token DA PESSOA"
        if not com_token:
            raise vinculos.SemConexao("sem token do meuPlano")
        return falso

    async def _baixar(mensagem_id):
        return b"OGG", "audio/ogg"

    monkeypatch.setattr(vinculos, "cliente_meuplano", _mp)
    monkeypatch.setattr(assistente.whatsapp, "baixar_midia", _baixar)
    return falso


def _ev_audio(dono, n):
    return {"id": n, "telefone": dono.telefone, "wa_id": "1", "tipo": "audio", "texto": None,
            "midia": {"mime": "audio/ogg"}}


async def test_a_nota_de_voz_vira_texto_e_segue_como_texto(db, bot_local, helper_com_get, monkeypatch):
    """O bot anterior no mesmo número transcrevia áudio; este respondia "só texto"."""
    from app.models.conversa_whatsapp import RegistroBot

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    falso = _audio(monkeypatch, "quanto gerou pirapozinho hoje?")
    dono = _dono_com_usina(db)
    await assistente.atender(_ev_audio(dono, 1))
    assert falso.ouvidos == [(b"OGG", "audio/ogg")]
    assert bot_local.enviados[0] == "🎙️ _quanto gerou pirapozinho hoje?_"
    assert bot_local.llm == ["🎙️ quanto gerou pirapozinho hoje?"] and bot_local.enviados[1] == "resposta da IA"
    assert db.query(RegistroBot).one().pergunta == "🎙️ quanto gerou pirapozinho hoje?"


async def test_a_senha_dita_no_audio_confirma_e_nunca_volta_em_claro(db, bot_local, helper_com_get, monkeypatch):
    from app.models.conversa_whatsapp import RegistroBot

    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13"))
    _audio(monkeypatch, "4 8 2 9 1 3")
    await assistente.atender(_ev_audio(dono, 2))
    assert helper_com_get.confirmadas == [("P-1", "pin")]
    tudo = " ".join(bot_local.enviados) + " ".join(r.pergunta or "" for r in db.query(RegistroBot))
    assert "482913" not in tudo.replace(" ", "") and "🎙️ _[senha de atuação]_" in bot_local.enviados


async def test_audio_sem_token_do_meuplano_explica_e_cancela_a_acao(db, bot_local, helper_com_get, monkeypatch):
    from app.services import assistente_helper as h

    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    await assistente.atender(_ev(dono, 1, "desliga o inversor 13"))
    _audio(monkeypatch, "qualquer", com_token=False)
    await assistente.atender(_ev_audio(dono, 2))
    assert "token do meuPlano" in bot_local.enviados[-1] and "foi cancelada" in bot_local.enviados[-1]
    assert dono.id not in h.PENDENTES and helper_com_get.confirmadas == []


async def test_arquivo_recebido_diz_o_nome_e_que_ainda_nao_abre(db, bot_local, monkeypatch):
    dono = _dono_com_usina(db)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "document", "texto": None,
                              "midia": {"mime": "application/pdf", "nome": "projeto.pdf"}})
    assert "«projeto.pdf»" in bot_local.enviados[0] and "ainda não abro arquivos" in bot_local.enviados[0]


async def test_a_senha_soletrada_com_barra_ou_por_extenso_e_reconhecida(db, monkeypatch):
    """"4 8 2 9 1 3" (o ditado por voz), "482/913", "482 9 13", espaço não separável, dígito de
    largura cheia e por extenso passavam em claro — e, sozinhos, cancelavam a ação em vez de
    contar como tentativa (avaliação 11). Data, IP, lista e o que não pode ser senha, não."""
    import re

    from app.services import assistente_helper as h

    monkeypatch.setattr(h, "conferir_senha", lambda d, guardado: d == "482913")
    dono = _dono_com_usina(db)
    for so_ela in ["4 8 2 9 1 3", "4, 8, 2, 9, 1, 3", "senha 482/913", "senha: 482 9 13", "482 913",
                   "*482913*", "482913?", "４８２９１３", "quatro oito dois nove um três",
                   "quatro 8 dois 9 um 3", "(482) 913", "(482913)",               # avaliação 20
                   "4️⃣8️⃣2️⃣9️⃣1️⃣3️⃣"]:                                              # avaliação 21
        assert h.digitos_da_senha(so_ela) == "482913", so_ela
    for nao in ["24/10/2026", "2026-10-24", "10.1.130.2", "12, 13, 14", "123456", "111111", "2026"]:
        assert h.digitos_da_senha(nao) is None, nao
    for frase in ["a senha é quatro oito dois nove um três", "pode ir 4 8 2 9 1 3", "minha senha 482/913 ok",
                  "vai 482 913 ok", "tenta ４８２９１３ aí",
                  "a senha é quatro 8 dois 9 um 3", "liga (482) 913 aí", "a senha é 4️⃣8️⃣2️⃣9️⃣1️⃣3️⃣ ok"]:
        h._CONFERENCIAS.clear()
        visto = h.mascarar(frase, await h.analisar(dono, frase))
        assert "482913" not in re.sub(r"\D", "", visto) and "quatro" not in visto, (frase, visto)
        assert "\u20e3" not in visto, visto                               # nem o enfeite do último dígito


def test_o_log_esconde_o_segredo_escrito_do_jeito_que_se_escreve():
    """Avaliação 24 (regressão do 425fd06): a "prosa" era adivinhada pela forma da palavra e deixava em claro "a senha
    do SmartLogger é changeme para o usuário admin"; e a seta, o travessão, o "ficou", a lista de credenciais e o
    segundo segredo da frase passavam. A prosa agora é uma lista POSITIVA; o resto some."""
    import re

    from app.services.assistente import _sem_segredos

    for texto in ["A senha do SmartLogger é <<changeme>> para o usuário admin.", "A senha do portão é <<morango>> desde ontem.",
                  "Senha do wifi da usina: <<solarman>> (padrão de fábrica).",
                  "A senha do datalogger é <<admin>> mesmo, nunca trocaram.", "senha: <<huawei>> no SmartLogger 2",
                  "A senha do cadeado é <<girassol>> com G maiúsculo? Não, minúsculo.",
                  "O PIN do ABS é <<abcd>> em todas as caixas.", "Senha – <<482913>>", "Senha → <<Huawei@123>>",
                  "senha -> <<Changeme1>>", "A senha nova ficou <<Solar#2026>>", "Usuário admin / senha <<changeme>>",
                  "Login: admin | Senha: <<Changeme>>", "a senha do SmartLogger 3 é <<sungrow>> e do 4 é <<sungrow4>>",
                  # o jeito que o meuPlano escreve a credencial que o IA.MD de lá manda exibir (avaliação 25: 20 de 22)
                  "**Senha:** <<Huawei@123>>", "*Senha:* <<Huawei@123>>", "- **Senha:** <<Huawei@123>>",
                  "**Senha**: <<Huawei@123>>", "• Usuário: admin\n• **Senha:** <<Solar#2026>>",
                  "SmartLogger 1 — **usuário** admin · **senha** <<Huawei@123>>",
                  "| usuario | admin |\n| senha | <<Huawei@123>> |", "As senhas: SL1 <<Huawei@123>>, SL2 <<Sungrow@2>>",
                  "Senhas dos SmartLoggers — SL1: <<Huawei@123>>; SL2: <<Sungrow@2>>",
                  "A senha padrão de fábrica do SmartLogger é <<Changeme>>", "Senha padrão do SmartLogger: <<Changeme>>",
                  "Senha atual do roteador: <<Splendor2024>>", "senha (SmartLogger 1): <<Huawei@123>>",
                  "login admin e senha <<changeme>>", "A senha que usamos no SmartLogger é <<Huawei@123>>",
                  "A senha para entrar no SmartLogger é <<Huawei@123>>",
                  "Credenciais do SmartLogger: admin / <<Huawei@123>>",
                  "Wi-Fi da usina — SSID UFV-Ibitinga, senha <<splendor>>", "A senha do Wi-Fi é a <<splendor2024>>",
                  "Senha nova: <<Solar#2026>>", "Sua senha do SmartLogger é <<Huawei@123>>",   # "sua" não isenta
                  # a tabela com COLUNA de senha
                  "| Equipamento | Usuário | Senha |\n|---|---|---|\n| SL1 | admin | <<Huawei@123>> |\n"
                  "| SL2 | admin | <<Sungrow@2>> |"]:
        limpo, segredos = re.sub(r"<<|>>", "", texto), re.findall(r"<<(.+?)>>", texto)
        assert not [v for v in segredos if v in _sem_segredos(limpo)], (texto, _sem_segredos(limpo))
    for texto in ["Sua senha de atuação é pessoal, não a passe a ninguém.",
                  "A senha de atuação é definida no oem-gs pelo gerente.",
                  "(Escondi a sua senha de atuação desta mensagem: ela é só para equipamento — ação do meuPlano se "
                  "confirma com Sim.)", "A senha é a mesma do meuPlano.",
                  "Você ainda não tem senha de atuação — sem ela o bot não comanda equipamento pelo helper.",
                  "Senha não confere (1 de 5). Nada foi feito.", "A ação esperava a sua resposta até as 14:32 e venceu.",
                  "Código do alarme: 2043", "o código de erro é E-2043",          # "código" só de porta/cadeado
                  # o que se diz DA senha, sem dizê-la (avaliação 25)
                  "A senha era antiga e foi trocada.", "A senha ficou bloqueada no SmartLogger.",
                  "A senha do SmartLogger é desconhecida: não há registro.", "Sua senha é forte.", "A senha é longa demais.",
                  "O PIN é 4 dígitos.", "A senha fica a critério do gerente.",
                  "A senha do roteador é fornecida pela operadora.", "Senha: não cadastrada no meuPlano.",
                  "Senha: sem registro.", "A senha do inversor é a de fábrica.", "A senha da OS 1638 não existe.",
                  "Senha errada 5 vezes: as ações ficam bloqueadas por 15 min.", "Senha bloqueada: tente amanhã.",
                  "Senha de atuação: peça ao gerente da sua O&M."]:          # o conceito do bot, nunca o valor
        assert _sem_segredos(texto) == texto, (texto, _sem_segredos(texto))


def test_o_log_nao_estraga_o_marcador_nem_esconde_dado_tecnico():
    """"Senha:[senha oculta]" virava "Senha:•••• oculta]"; "PIN 3 do conector" e "strings 12"
    viravam "••••" (avaliação 11)."""
    from app.services.assistente import _sem_segredos

    for texto in ["Senha:[senha oculta] pode executar", "a senha é [senha oculta], ok?", "pin=[número oculto] vai",
                  "minha senha é: [senha oculta]", "a senha é a mesma do login?", "o código é o mesmo de ontem",
                  "você ainda não tem senha de atuação. Quem define isso é o gerente da O&M",
                  "Você ainda não tem senha de atuação. Quem define é Marcos, o gerente.",
                  "Combinação de strings 12 e 13 com corrente baixa", "PIN 3 do conector MC4",
                  "senha 2 vezes errada", "código de erro 2043"]:
        assert _sem_segredos(texto) == texto
    assert _sem_segredos("a senha do wifi é Solar@2024") == "a senha do wifi é ••••"
    # o número inteiro, escrito como a senha se escreve ("•••• 913" e "•••• 8 dois 9 um 3" — avaliação 21)
    for segredo in ("(482) 913", "quatro 8 dois 9 um 3", "4 8 2 9 1 3", "482.913"):
        assert _sem_segredos(f"a senha do cadeado é {segredo}, ok") in ("a senha do cadeado é ••••, ok",
                                                                         "a senha do cadeado é (••••, ok"), segredo
    assert _sem_segredos("minha senha é: 4821x") == "minha senha é: ••••"


async def test_documento_assinado_no_meuplano_so_sai_com_o_sim(db, monkeypatch):
    """No meuPlano a ferramenta de PDF assina com o certificado da pessoa dentro de uma LEITURA
    — "me manda o PDF da OS assinado" saía sem confirmação nenhuma (avaliação 11). O pedido de
    assinatura só vai ao meuPlano depois do SIM da pessoa."""
    from app.core.security import gerar_hash_senha
    from app.services import assistente_helper as h
    from app.services import vinculos

    pedidos = []

    class _MP:
        async def assistente_chat(self, token, mensagens):
            pedidos.append(mensagens[-1]["content"])
            return 7

        async def assistente_run(self, token, run_id):
            return {"status": "DONE", "type": "message", "text": "PDF da OS 1639 assinado: https://x/pdf"}

    async def _sem_espera(_):
        return None

    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: _MP())
    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    dono = _conta(db, "dono", "+5517997377626")
    dono.bot_meuplano, dono.senha_atuacao_hash = True, gerar_hash_senha("482913")
    db.commit()
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    r = await assistente.manutencao(ctx, {"pergunta": "me manda o PDF da OS 1639 assinado"})
    assert "NADA foi executado" in r["instrucao"] and pedidos == []
    assert "ASSINATURA DIGITAL" in h.PENDENTES[dono.id].resumo
    # Sem a palavra na pergunta da IA, mas com ela no pedido da pessoa: também.
    h.PENDENTES.clear()
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone, pedido="quero com meu certificado digital")
    r = await assistente.manutencao(ctx, {"pergunta": "PDF da OS 1639"})
    assert "NADA foi executado" in r["instrucao"] and pedidos == []
    h.mostrada(dono.id)
    feito = await h.confirmar_por_mensagem(db, dono, dono.telefone, "sim")
    assert feito.startswith("PDF da OS 1639 assinado") and pedidos == ["PDF da OS 1639" + assistente.PARA_O_WHATSAPP]
    # Leitura comum continua sem senha.
    r = await assistente.manutencao(ger.Contexto(db=db, user=dono, telefone=dono.telefone), {"pergunta": "OS abertas?"})
    assert r == {"texto": "PDF da OS 1639 assinado: https://x/pdf"} and len(pedidos) == 2


async def test_o_botao_nao_cancela_a_acao_do_meuplano(db, bot_local, monkeypatch):
    import json as _json

    from app.services import assistente_helper as h
    from app.services import vinculos

    falso = _MeuPlanoEmPassos()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: falso)

    async def _sem_espera(_):
        return None

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": "Vou abrir a OS."}
        return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
            "name": "manutencao", "arguments": _json.dumps({"pergunta": msgs[-1]["content"]})}}]}

    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "Crie a OS"))
    await assistente.atender({**_ev(dono, 2, "Não"), "tipo": "interactive", "botao": f"nao:{h.PENDENTES[dono.id].codigo}"})
    assert bot_local.enviados[-1] == h.CANCELADO and dono.id not in h.PENDENTES and falso.aplicadas == []


async def test_gateway_que_recusa_botoes_manda_o_resumo_em_texto(db, bot_local, monkeypatch):
    """Gateway antigo (sem o tipo `botoes`) responde 422: o resumo vai em texto, e a ação espera."""
    import json as _json

    from app.clients.whatsapp import GatewayIndisponivel
    from app.services import assistente_helper as h
    from app.services import vinculos

    falso = _MeuPlanoEmPassos()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: falso)

    async def _enviar(**k):
        if k.get("tipo") == "botoes":
            raise GatewayIndisponivel("422", status=422)
        bot_local.enviados.append(k.get("texto"))
        return {"ok": True}

    async def _sem_espera(_):
        return None

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": "Vou abrir a OS."}
        return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
            "name": "manutencao", "arguments": _json.dumps({"pergunta": msgs[-1]["content"]})}}]}

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "Crie a OS"))
    assert "Abrir a OS" in bot_local.enviados[-1] and h.PENDENTES[dono.id].mostrada_em is not None


# ── avaliação 12 (24/10/2026): o SIM do jeito que se fala, a correção, o 500 no meio e a assinatura ──


def _resto(monkeypatch, *decisoes, vistos=None):
    """A IA de mentira do RESTO do pedido (`assistente._decidir_o_resto`): cada decisão é (ferramenta, argumentos), na
    ordem; acabadas, ela não chama ferramenta nenhuma (o bot diz que não conseguiu conferir). `vistos` recebe as
    mensagens de cada decisão."""
    import json as _json

    fila = list(decisoes)

    async def _decidir(msgs):
        if vistos is not None:
            vistos.append(msgs)
        if not fila:
            return {"content": "ok"}
        nome, args = fila.pop(0)
        return {"content": "", "tool_calls": [{"id": f"r{len(fila)}", "type": "function", "function": {
            "name": nome, "arguments": _json.dumps(args)}}]}

    monkeypatch.setattr(assistente, "_decidir_o_resto", _decidir)


#: O resto mais comum: pedir ao meuPlano o passo que falta e, depois dele, o fim.
SEGUE_E_ACABA = (("proximo_passo", {"passo": "Mover a OS 1638 para concluída"}), ("fim_do_pedido", {"situacao": "feito"}))


def _ia_que_pede_ao_meuplano(monkeypatch, falso, vistos):
    """A IA de mentira: "crie …" vai ao meuPlano (`falso`); o resto, "Entendi." — e anota o que viu."""
    import json as _json

    from app.services import vinculos

    async def _sem_espera(_):
        return None

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            return {"content": "Vou abrir a OS."}
        vistos.append(msgs[-1]["content"])
        if msgs[-1]["content"].lower().startswith("crie"):
            return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
                "name": "manutencao", "arguments": _json.dumps({"pergunta": msgs[-1]["content"]})}}]}
        return {"content": "Entendi."}

    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: falso)
    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    _resto(monkeypatch, *SEGUE_E_ACABA)


async def test_sim_com_palavras_confirma_e_nao_com_correcao_vai_a_ia(db, bot_local, monkeypatch):
    """"Sim, pode criar" — o jeito comum de dizer sim — derrubava a ação do meuPlano e mandava usar
    a SENHA; "Não, o técnico é o Diogo" virava só "Cancelado", e a correção se perdia."""
    from app.services import assistente_helper as h

    falso, vistos = _MeuPlanoEmPassos(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, vistos)
    dono = _conta(db, "dono", "+5517997377626")                 # SEM senha de atuação
    await assistente.atender(_ev(dono, 1, "Crie a OS e a tarefa. A OS 1638 mova para concluída"))
    await assistente.atender(_ev(dono, 2, "Sim, pode criar"))
    assert falso.aplicadas == ["criar_ordem_servico"] and "Mover a OS 1638" in bot_local.enviados[-1]
    await assistente.atender(_ev(dono, 3, "Não, o técnico é o Diogo e a data é amanhã"))
    assert vistos[-1] == "Não, o técnico é o Diogo e a data é amanhã"        # a correção foi à IA
    assert bot_local.enviados[-1].endswith(h.ACAO_CANCELADA_SIM) and dono.id not in h.PENDENTES
    assert falso.aplicadas == ["criar_ordem_servico"]
    assert not any("senha" in (m or "").lower() for m in bot_local.enviados)
    for sim in ("Sim", "sim!", "Pode sim", "Confirmado", "Isso mesmo", "ok", "👍",
                "Confirmar", "pode confirmar", "Aprovado", "De acordo", "tá certo"):
        assert h.e_sim(sim), sim
    # o verbo, só o da AÇÃO (avaliação 18: "Pode criar" confirmava "APAGAR 3 itens")
    assert h.e_sim("Pode lançar", "Lançar o dia 23/10 na tarefa 8873") and h.e_sim("Sim, pode abrir", "Abrir a OS 1639")
    assert h.e_sim("Sim, crie a OS 1639", "Abrir a OS 1639")    # o número, só o do resumo (avaliação 15)
    for outra in ("Sim, mas troque o técnico", "Pode me mandar o relatório", "sim?", "Segue o protocolo 1234", "",
                  "de jeito nenhum", "tá errado"):
        assert not h.e_sim(outra), outra
    for nao in ("Não", "não quero", "cancela", "deixa pra lá"):
        assert h.so_cancela(nao), nao
    for correcao in ("Não, o técnico é o Diogo", "não é amanhã", "Nao, corredores"):
        assert not h.so_cancela(correcao), correcao


class _MeuPlanoQueQuebra(_MeuPlanoEmPassos):
    """O /assistant/apply de 24/10/2026: gravou a OS e quebrou no passo seguinte (500)."""

    async def assistente_aplicar(self, token, acao, args):
        import httpx

        req = httpx.Request("POST", "https://mp/api/v1/meuacesso/assistant/apply")
        raise httpx.HTTPStatusError("500", request=req, response=httpx.Response(500, request=req, json={
            "detail": "Erro ao aplicar a ação: 'Depends' object has no attribute 'all'"}))


async def test_erro_500_do_meuplano_diz_que_pode_ter_gravado_e_lembra_o_resto_do_pedido(db, bot_local, monkeypatch):
    """A OS 1843 ficou criada e vazia, e o bot disse "Nada foi feito" com o erro de Python cru; a
    conclusão da 1638 (o resto do pedido) sumiu calada, e o log mostrava "Respondeu"."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    _ia_que_pede_ao_meuplano(monkeypatch, _MeuPlanoQueQuebra(), [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "Crie a OS e a tarefa. A OS 1638 mova para concluída"))
    await assistente.atender(_ev(dono, 2, "Sim"))
    falha = bot_local.enviados[-1]
    assert falha.startswith("⚠️") and "PODE ter sido gravada" in falha and "OS 1638" in falha
    assert "Nada foi feito" not in falha and "Depends" not in falha and dono.id not in h.PENDENTES
    linha = db.query(RegistroBot).order_by(RegistroBot.id.desc()).first()
    assert linha.resultado == "erro" and linha.erro.startswith("⚠️")


async def test_sem_senha_o_numero_com_o_sim_esperando_e_conversa(db, bot_local, monkeypatch):
    """Quem não tem senha (o Renan) e responde a proposta do meuPlano com um número (a UC, o
    protocolo que a IA pediu) ouvia "sem senha o bot só lê" — falso, e de novo a senha numa ação
    que pede SIM. O número vai à IA, e a ação que esperava cai sem falar de senha."""
    from app.services import assistente_helper as h

    falso, vistos = _MeuPlanoEmPassos(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, vistos)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "Crie a OS e a tarefa"))
    await assistente.atender(_ev(dono, 2, "4829137"))
    assert vistos[-1] == "4829137" and bot_local.enviados[-1].endswith(h.ACAO_CANCELADA_SIM)
    assert falso.aplicadas == [] and "equipamento" in h.SEM_SENHA


async def test_pergunta_sobre_a_assinatura_e_leitura_e_o_pedido_com_interrogacao_pede_sim(db, monkeypatch):
    """"A OS 1638 já foi assinada?" virava ação ("com a sua ASSINATURA DIGITAL") e nem saía; e
    "Pode assinar a OS 1639?" é pedido, apesar do "?" — o meuPlano assina dentro de uma leitura."""
    from app.services import vinculos

    pedidos = []

    class _MP:
        async def assistente_chat(self, token, mensagens):
            pedidos.append(mensagens[-1]["content"])
            return 1

        async def assistente_run(self, token, run_id):
            return {"status": "DONE", "type": "message", "text": "Sim, assinada em 20/10."}

    async def _sem_espera(_):
        return None

    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: _MP())
    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    dono = _conta(db, "dono", "+5517997377626")
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    r = await assistente.manutencao(ctx, {"pergunta": "A OS 1638 já foi assinada pelo cliente?"})
    assert r == {"texto": "Sim, assinada em 20/10."} and len(pedidos) == 1
    for pedido in ("Pode assinar a OS 1639?", "Consegue me mandar o PDF assinado?", "Tem como assinar a OS?",
                   "assina a OS pra mim", "Já está assinada? Se não, assine", "Assinada?",
                   "Manda o PDF assinado do contrato da OS 1639"):
        assert assistente._pede_assinatura(pedido), pedido
    for leitura in ("Foi assinada?", "Quem assinou a OS?", "As OS de ontem estão assinadas?", "Quais OS faltam assinar?",
                    "Qual o status da assinatura da OS 1638?",
                    # o signatário de um contrato (29/10/2026: virou "Assinar com o seu certificado… Criar um contrato")
                    "Criar um contrato de comissionamento. Ainda não tenho: vigência, valor e quem assina/gerencia",
                    "Quem vai assinar o contrato?", "Falta a data de assinatura e o signatário",
                    # 29/10/2026 de novo (Mairinque): o resto do contrato "fica para o site"
                    "Criar o contrato de COMISSIONAMENTO para a usina Mairinque. Centros de custo: todos. "
                    "Vigência, valor, pagamento, documento e assinatura ficam pendentes"):
        assert not assistente._pede_assinatura(leitura), leitura


class _MeuPlanoQueRecusa(_MeuPlanoEmPassos):
    """Fechar a OS com tarefa pendente: 409 com a frase de lá, que termina em ponto (o ensaio contra o
    meuPlano real, 24/10/2026)."""

    async def assistente_aplicar(self, token, acao, args):
        import httpx

        req = httpx.Request("POST", "https://mp/api/v1/meuacesso/assistant/apply")
        raise httpx.HTTPStatusError("409", request=req, response=httpx.Response(409, request=req, json={
            "detail": "Conclua todas as tarefas antes de fechar a OS. Pendentes: 1 de 1."}))


async def test_o_que_o_meuplano_responde_chega_em_texto_de_gente(db, monkeypatch):
    """O ensaio contra o meuPlano real mostrou "Pendentes: 1 de 1.. Nada foi feito." e
    "(OS 1638, task_id: 8873, sessao_id: 4131)" — nome de campo do sistema na mensagem."""
    from app.services import assistente_helper as h
    from app.services import vinculos

    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: _MeuPlanoQueRecusa())
    dono = _conta(db, "dono", "+5517997377626")
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    assistente._proposta_do_meuplano(ctx, {"action": "fechar_os", "args": {"os_id": 1638},
                                           "preview": {"summary": "Fechar a OS 1638"}})
    h.mostrada(dono.id)
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "Sim") == (
        "❌ O meuPlano recusou: Conclua todas as tarefas antes de fechar a OS. Pendentes: 1 de 1. Nada foi feito.")
    assert assistente._o_que_nasceu({"os_id": 1638, "task_id": 8873, "sessao_id": 4131}) == " (OS 1638, tarefa 8873)"
    # O que o resumo do meuPlano já diz não se repete (avaliação 13: "(OS 1638, tarefa 8873)" duas vezes).
    assert assistente._o_que_nasceu({"os_id": 1638, "task_id": 8873}, "Concluir a ficha (tarefa 8873, OS 1638)") == ""
    assert assistente._o_que_nasceu({"os_id": 1638, "status": "FECHADA"}, "Fechar a OS 1638") == " (FECHADA)"
    assert assistente._o_que_nasceu({"os_id": 16381}, "Fechar a OS 1638") == " (OS 16381)"
    assert assistente._o_que_nasceu({"os_id": 9, "status": "FECHADA"}, "Mover a OS 9 para FECHADA") == ""


# ── avaliação 13 (24/10/2026): o pedido de vários passos quando um passo falha, o botão antigo ──


PEDIDO_DOIS_PASSOS = "Crie a OS e a tarefa. A OS 1638 mova para concluída"


class _MeuPlanoDoisPassos:
    """1º criar a OS (nasce a 1843); 2º o próximo passo. `segundo`: "proposta" (fechar a 1638) ou
    "erro" (o modelo de lá falhou). `falha_2`: o status do apply no 2º passo (409 = a 1638 tem tarefa
    pendente, como no ensaio contra o meuPlano real; 500 = erro no meio)."""

    def __init__(self, segundo="proposta", falha_2=None, eventos=None):
        self.aplicadas, self.conversas, self.segundo, self.falha_2 = [], [], segundo, falha_2
        self.eventos = eventos if eventos is not None else []

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        self.eventos.append("meuplano_chat")
        return len(self.conversas)

    async def assistente_run(self, token, run_id):
        if run_id == 1:
            return {"status": "DONE", "type": "proposal", "action": "criar_ordem_servico", "args": {"usina_id": 37},
                    "preview": {"summary": "Criar OS em UFV Ibitinga com 1 tarefa(s)", "lines": [], "warnings": []}}
        if self.segundo == "erro":
            return {"status": "ERROR", "error": "O modelo não respondeu."}
        return {"status": "DONE", "type": "proposal", "action": "fechar_os", "args": {"os_id": 1638},
                "preview": {"summary": "Fechar a OS 1638", "lines": [], "warnings": []}}

    async def assistente_aplicar(self, token, acao, args):
        import httpx

        if acao == "fechar_os" and self.falha_2:
            req = httpx.Request("POST", "https://mp/api/v1/meuacesso/assistant/apply")
            raise httpx.HTTPStatusError(str(self.falha_2), request=req, response=httpx.Response(
                self.falha_2, request=req, json={"detail": "Conclua todas as tarefas antes de fechar a OS. Pendentes: 1 de 1."}))
        self.aplicadas.append(acao)
        return {"ok": True, "data": {"os_id": 1843, "status": "PROGRAMADA"} if acao == "criar_ordem_servico"
                else {"os_id": 1638, "status": "FECHADA"}}


class _MeuPlanoQueEscreve(_MeuPlanoDoisPassos):
    """O próximo passo em TEXTO (uso real de 24/10/2026: "Faltam 2 passos… aqui está a proposta…
    Confirmando os dois, eu fecho a 1638"). `depois`: o que o meuPlano responde a cada pedido seguinte
    — um texto, ou "proposta" (fechar a 1638)."""

    def __init__(self, *depois):
        super().__init__()
        self.depois = list(depois)

    async def assistente_run(self, token, run_id):
        if run_id == 1:
            return await super().assistente_run(token, run_id)
        r = self.depois.pop(0)
        if isinstance(r, dict):
            return r
        if r == "proposta":
            return {"status": "DONE", "type": "proposal", "action": "fechar_os", "args": {"os_id": 1638},
                    "preview": {"summary": "Fechar a OS 1638", "lines": [], "warnings": []}}
        return {"status": "DONE", "type": "message", "text": r}


TEXTO_DO_MEUPLANO = ("Faltam 2 passos do que você pediu — aqui está a proposta: **1) Fechar a OS 1638** (roçagem "
                     "09/2026). Confirmando os dois, eu fecho a 1638 e registro a 1843.")


def _toque(dono, n, sim=True):
    """O toque no botão do resumo que está esperando: o id leva o código dele."""
    from app.services import assistente_helper as h

    return {**_ev(dono, n, "Sim" if sim else "Não"), "tipo": "interactive",
            "botao": f"{'sim' if sim else 'nao'}:{h.PENDENTES[dono.id].codigo}"}


async def test_falha_num_passo_seguinte_diz_o_pedido_da_pessoa_e_o_que_ja_foi_feito(db, bot_local, monkeypatch):
    """O 2º passo ("fechar a 1638") falhou: a resposta citava como "o pedido" a instrução INTERNA que
    o bot mandou ao meuPlano ("✅ Feito… Se o meu pedido tinha mais passos, proponha o próximo")."""
    from app.models.conversa_whatsapp import RegistroBot

    for status, comeco in ((409, "❌ O meuPlano recusou"), (500, "⚠️")):
        from app.services import assistente_helper as h

        h.PENDENTES.clear()
        _ia_que_pede_ao_meuplano(monkeypatch, _MeuPlanoDoisPassos(falha_2=status), [])
        dono = _conta(db, f"dono{status}", f"+55179973{status:05d}")
        await assistente.atender(_ev(dono, status * 10 + 1, PEDIDO_DOIS_PASSOS))
        await assistente.atender(_toque(dono, status * 10 + 2))
        assert "Fechar a OS 1638" in bot_local.enviados[-1]
        await assistente.atender(_toque(dono, status * 10 + 3))
        falha = bot_local.enviados[-1]
        assert falha.startswith(comeco) and "proponha o próximo" not in falha and "Feito no meuPlano" not in falha
        assert (f"Do seu pedido «{PEDIDO_DOIS_PASSOS}», antes disso já foi feito: Criar OS em UFV Ibitinga com 1 tarefa(s) "
                "(OS 1843, PROGRAMADA). O resto não foi feito") in falha
        assert db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().resultado == "erro"


async def test_proximo_passo_em_texto_volta_a_ia_e_nunca_e_repassado(db, bot_local, monkeypatch):
    """Uso real de 24/10/2026 (avaliação 19): depois do Sim, o próximo passo veio em TEXTO ("confirmando os dois, eu fecho
    a 1638") e o bot o repassou, sem botões, e a 1638 não foi fechada. Agora o texto de lá volta à IA, que pede o passo
    de novo; e, se ela não decide, a pessoa lê que não se conferiu o resto do pedido (log "a conferir")."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    falso = _MeuPlanoQueEscreve(TEXTO_DO_MEUPLANO, "proposta")
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    decisoes = []
    _resto(monkeypatch, ("proximo_passo", {"passo": "Mover a OS 1638 para concluída"}),
           ("proximo_passo", {"passo": "Fechar a OS 1638"}), vistos=decisoes)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    await assistente.atender(_toque(dono, 2))
    assert h.PENDENTES[dono.id].resumo == "Fechar a OS 1638"                    # pronto para o botão
    assert not any("Confirmando os dois" in m for m in bot_local.enviados)       # a promessa não chegou à pessoa
    assert "Confirmando os dois" in decisoes[-1][-1]["content"]                  # chegou à IA, como resultado

    h.PENDENTES.clear()
    falso = _MeuPlanoQueEscreve(TEXTO_DO_MEUPLANO)
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    _resto(monkeypatch, ("proximo_passo", {"passo": "Fechar a OS 1638"}))       # e depois a IA não decide
    dono2 = _conta(db, "dono2", "+5517997370000")
    await assistente.atender(_ev(dono2, 3, PEDIDO_DOIS_PASSOS))
    await assistente.atender(_toque(dono2, 4))
    aviso = bot_local.enviados[-1]
    assert aviso.startswith(assistente.NAO_CONFIRMOU) and dono2.id not in h.PENDENTES
    assert "Criar OS em UFV Ibitinga" in aviso and "Confirmando os dois" not in aviso and ".." not in aviso
    assert db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().resultado == "a_conferir"


async def test_o_resto_do_pedido_e_a_decisao_da_ia_nunca_a_prosa_do_meuplano(db, bot_local, monkeypatch):
    """Depois de um passo feito, a IA decide numa chamada de ferramenta: o próximo passo (o meuPlano propõe) ou o fim
    (feito, falta, pergunta). Antes o meuPlano respondia um status em texto que a regra 7 do IA.MD de lá proíbe
    ("feito"), e o pedido de UM passo, feito, terminava numa 2ª mensagem dizendo que não se confirmou (avaliação 28).
    O texto da IA (o motivo, a pergunta) vai à pessoa e fica fora do log; o estado vai ao log."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    criar = {"status": "DONE", "type": "proposal", "action": "criar_ordem_servico", "args": {"usina_id": 37},
             "preview": {"summary": "Criar OS em UFV Ibitinga com 1 tarefa(s)", "lines": [], "warnings": []}}
    falta = ("fim_do_pedido", {"situacao": "falta", "texto": "A OS 1638 ainda tem a tarefa 8873 sem data de término"})
    pergunta = ("fim_do_pedido", {"situacao": "pergunta", "texto": "Qual foi a data de término da roçagem?"})
    feito = ("fim_do_pedido", {"situacao": "feito"})
    passo = ("proximo_passo", {"passo": "Fechar a OS 1638"})
    ja = "Já foi feito: Criar OS em UFV Ibitinga com 1 tarefa(s) (OS 1843, PROGRAMADA)."
    # (as decisões, o que o meuPlano responde a cada passo pedido, o que a pessoa lê depois do ✅ (None: nada), o log,
    #  quantas vezes se perguntou ao meuPlano, o que fica no log no lugar do texto da IA)
    casos = (([feito], (), None, "respondeu", 1, None),                                  # o pedido de um passo: calado
             ([passo], ("proposta",), "• Fechar a OS 1638", "respondeu", 2, None),
             ([falta], (), f"⚠️ A OS 1638 ainda tem a tarefa 8873 sem data de término. {ja}", "erro", 1,
              "o motivo foi à pessoa e está fora do log"),
             ([pergunta], (), "Qual foi a data de término da roçagem?", "respondeu", 1, "a pergunta está fora do log"),
             # o pedido também perguntava algo ("e quantas OS sobraram?"): a resposta vai, sem ⚠️, e fica fora do log
             ([("fim_do_pedido", {"situacao": "feito", "texto": "Em Ibitinga ficaram 2 OS abertas: 1843 e 1900."})], (),
              "Em Ibitinga ficaram 2 OS abertas: 1843 e 1900.", "respondeu", 1, "a resposta ao resto do pedido"),
             ([passo, passo], (TEXTO_DO_MEUPLANO, "proposta"), "• Fechar a OS 1638", "respondeu", 3, None),
             ([passo, feito], ("A OS 1638 foi fechada.",), None, "respondeu", 2, None),
             ([passo, feito], (criar,), None, "respondeu", 2, None),                     # o mesmo passo de novo: a IA sabe
             ([passo], (TEXTO_DO_MEUPLANO,), assistente.NAO_CONFIRMOU, "a_conferir", 2, None),   # a IA não decidiu
             ([("fim_do_pedido", {"situacao": "pergunta"})], (), assistente.NAO_CONFIRMOU, "a_conferir", 1, None),
             ([("fim_do_pedido", {"situacao": "talvez"})], (), assistente.NAO_CONFIRMOU, "a_conferir", 1, None),
             ([passo, passo, passo], (TEXTO_DO_MEUPLANO,) * 3, assistente.NAO_CONFIRMOU, "a_conferir", 4, None))
    for n, (decisoes, depois, espera, resultado, perguntas, no_log) in enumerate(casos):
        h.PENDENTES.clear()
        falso = _MeuPlanoQueEscreve(*depois)
        _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
        vistos = []
        _resto(monkeypatch, *decisoes, vistos=vistos)
        dono = _conta(db, f"dono{n}", f"+55179973770{n:02d}")
        await assistente.atender(_ev(dono, 10 * n + 1, PEDIDO_DOIS_PASSOS))
        antes = len(bot_local.enviados)
        await assistente.atender(_toque(dono, 10 * n + 2))
        saidas = bot_local.enviados[antes:]
        assert saidas[0].startswith("✅ Feito no meuPlano: Criar OS"), n
        if espera is None:
            assert len(saidas) == 1, (n, saidas)                       # nada mais a dizer
        else:
            assert espera in saidas[-1] and saidas[-1].startswith("⚠️") == (resultado != "respondeu"), (n, saidas[-1])
        log = db.query(RegistroBot).order_by(RegistroBot.id.desc()).first()
        assert log.resultado == resultado and len(falso.conversas) == perguntas, n
        assert not any("Faltam 2 passos" in m for m in saidas), n         # a prosa de lá nunca é repassada
        if no_log:
            assert no_log in log.resposta and decisoes[0][1]["texto"] not in log.resposta, n
        # a IA decide com o pedido da pessoa e o que já foi feito
        assert PEDIDO_DOIS_PASSOS in vistos[0][0]["content"] and "Criar OS em UFV Ibitinga" in vistos[0][0]["content"]
        if depois == (criar,):                                       # o mesmo passo de novo: a IA ficou sabendo
            assert "propôs de novo o passo que acabou de ser feito" in vistos[1][-1]["content"], n


async def test_a_decisao_do_resto_exige_ferramenta_e_o_modo_sem_raciocinio():
    """`tool_choice="required"` volta 400 no modo de raciocínio do DeepSeek (conferido em 25/10/2026): a decisão do resto
    pede a ferramenta e desliga o raciocínio; a conversa comum, não."""
    import httpx

    from app.core.config import get_settings

    corpos = []

    class _Resposta:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "", "tool_calls": []}}]}

    class _Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            corpos.append(json)
            return _Resposta()

    original, httpx.AsyncClient = httpx.AsyncClient, _Cliente
    try:
        await assistente._decidir_o_resto([{"role": "user", "content": "x"}])
        await assistente._llm([{"role": "user", "content": "x"}], [assistente._MANUTENCAO])
        await assistente._llm([{"role": "user", "content": "x"}], [assistente._MANUTENCAO], nenhuma=True)
    finally:
        httpx.AsyncClient = original
    resto, comum, sem_ferramenta = corpos
    assert sem_ferramenta["tool_choice"] == "none"                     # as consultas acabaram: só texto
    assert resto["tool_choice"] == "required" and resto["thinking"] == {"type": "disabled"}
    assert [f["function"]["name"] for f in resto["tools"]] == ["proximo_passo", "fim_do_pedido"]
    assert comum["tool_choice"] == "auto" and "thinking" not in comum
    assert resto["model"] == get_settings().llm_model


def test_o_resumo_diz_quantas_linhas_ficaram_de_fora():
    """Num APAGAR de 20 itens, só 15 apareciam no que a pessoa confirmava, sem aviso (avaliação 20)."""
    import types

    from app.services import assistente_geracao as ger

    ctx = ger.Contexto(db=None, user=types.SimpleNamespace(id=1, bot_ativo=["meuplano"]), telefone="+55",
                       pedido="apaga")
    r = {"action": "apagar_nos", "args": {"node_ids": list(range(20))},
         "preview": {"summary": "APAGAR 20 item(ns) — 20 nó(s) no total (cascata).",
                     "lines": [{"text": f"Inversor {i} (INV-{i})"} for i in range(1, 21)], "warnings": []}}
    out = assistente._proposta_do_meuplano(ctx, r)
    assert len(out["detalhes"]) == 16 and out["detalhes"][-1].startswith("… e mais 5. Veja")


async def test_o_resto_do_pedido_que_nao_vem_e_dito(db, bot_local, monkeypatch):
    """O meuPlano não deu o próximo passo (erro do modelo de lá, ou passou de 2 min): a pessoa
    recebia só o "✅ Feito" da OS nova, e nada dizia que a 1638 ficou sem fazer."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.services import assistente_helper as h

    _ia_que_pede_ao_meuplano(monkeypatch, _MeuPlanoDoisPassos(segundo="erro"), [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    n = len(bot_local.enviados)
    await assistente.atender(_toque(dono, 2))
    feito, aviso = bot_local.enviados[n:]
    assert feito.startswith("✅ Feito no meuPlano: Criar OS")
    assert aviso == (f"⚠️ Não consegui pedir ao meuPlano o resto do seu pedido «{PEDIDO_DOIS_PASSOS}» (O modelo não "
                     "respondeu). Já foi feito: Criar OS em UFV Ibitinga com 1 tarefa(s) (OS 1843, PROGRAMADA). Confira "
                     "e peça de novo o que faltar.")
    linha = db.query(RegistroBot).order_by(RegistroBot.id.desc()).first()
    assert linha.resultado == "erro" and linha.erro == aviso and dono.id not in h.PENDENTES


async def test_o_digitando_volta_logo_depois_do_feito(db, bot_local, monkeypatch):
    """O próximo passo leva de 20 a 65 s no meuPlano, e o "digitando…" já tinha sido desligado: a
    pessoa via o ✅ e nada dizia que vinha mais."""
    eventos = []
    _ia_que_pede_ao_meuplano(monkeypatch, _MeuPlanoDoisPassos(eventos=eventos), [])

    async def _digitando(wamid):
        eventos.append("digitando")

    enviar = assistente.whatsapp.enviar_conteudo

    async def _enviar(**k):
        eventos.append("envio:" + (k.get("texto") or "")[:1])
        return await enviar(**k)

    monkeypatch.setattr(assistente.whatsapp, "digitando", _digitando)
    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender({**_ev(dono, 1, PEDIDO_DOIS_PASSOS), "wamid": "wamid.1"})
    eventos.clear()
    await assistente.atender({**_toque(dono, 2), "wamid": "wamid.2"})
    i_feito = eventos.index("envio:✅")
    assert eventos[i_feito + 1:i_feito + 3] == ["digitando", "meuplano_chat"]


async def test_o_botao_de_um_resumo_antigo_nao_confirma_a_acao_de_agora(db, bot_local, monkeypatch):
    """O botão mandava sempre "sim": o toque no Sim de um resumo antigo (a OS que a pessoa desistiu
    de criar) confirmava a ação esperando AGORA. Agora o id leva o código do resumo."""
    from app.services import assistente_helper as h

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie a OS"))
    codigo = h.PENDENTES[dono.id].codigo
    assert bot_local.botoes[-1] == [f"sim:{codigo}", f"nao:{codigo}"]   # o id que volta no toque
    toque_a = _toque(dono, 2)                              # o Sim do resumo A, guardado
    await assistente.atender(_toque(dono, 3, sim=False))   # desistiu de A
    assert bot_local.enviados[-1] == h.CANCELADO
    await assistente.atender(_ev(dono, 4, "crie: feche a 1638"))   # resumo B: fechar a OS 1638
    # O Sim de A diz que a própria pessoa o cancelou (avaliação 16); o sem código, que é de um resumo antigo.
    for velho, aviso in ((toque_a, h.CANCELADA_PELA_MENSAGEM.format(trecho="Não")),
                         ({**_ev(dono, 5, "Sim"), "tipo": "interactive"}, h.BOTAO_ANTIGO)):
        await assistente.atender(velho)
        assert bot_local.enviados[-1] == aviso and falso.aplicadas == []
    assert dono.id in h.PENDENTES                          # a ação de agora continua esperando
    await assistente.atender(_toque(dono, 6))
    assert falso.aplicadas == ["fechar_os"]


async def test_quem_tem_senha_e_responde_um_numero_a_acao_do_meuplano_nao_ouve_de_senha(db, bot_local, monkeypatch):
    """Ação do meuPlano (confirma com Sim) e a pessoa — que TEM senha — manda um número: virava
    tentativa de senha ("Senha não confere (1 de 5)") e contava para o bloqueio. Agora é conversa; e
    se o número for a senha, ela some como numa frase, sem executar nada."""
    from app.core.security import gerar_hash_senha
    from app.services import assistente_helper as h

    falso, vistos = _MeuPlanoDoisPassos(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, vistos)
    dono = _conta(db, "dono", "+5517997377626")
    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    for numero, a_ia_ve in (("4829137", "4829137"), ("482913", "[senha oculta]")):
        await assistente.atender(_ev(dono, len(vistos) + 10, "crie a OS"))
        await assistente.atender(_ev(dono, len(vistos) + 20, numero))
        assert vistos[-1] == a_ia_ve and bot_local.enviados[-1].count(h.ACAO_CANCELADA_SIM) == 1
        assert "Senha não confere" not in bot_local.enviados[-1] and dono.id not in h._ERROS
    assert "ação do meuPlano se confirma com Sim" in bot_local.enviados[-1] and falso.aplicadas == []
    assert h.e_tentativa(dono, "482913")                   # sem ação do meuPlano esperando, é tentativa


def test_a_migracao_poe_em_erro_a_confirmacao_que_falhou(db):
    """A linha do Sim que deixou a OS 1843 vazia ficou verde ("Respondeu"); a resposta da IA que
    começa por ❌ não é ação e fica como está."""
    import importlib.util
    import types
    from pathlib import Path

    from app.models.conversa_whatsapp import RegistroBot

    caminho = next(Path(__file__).parents[1].glob("alembic/versions/d0e2f4a6b8c1_*.py"))
    spec = importlib.util.spec_from_file_location("mig_erro", caminho)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    db.add_all([
        RegistroBot(telefone="+5517997377626", resultado="respondeu", ferramentas="confirmacao",
                    resposta="❌ O meuPlano recusou: Erro ao aplicar a ação. Nada foi feito.\n\nDo pedido…"),
        RegistroBot(telefone="+5517997377626", resultado="respondeu", ferramentas="manutencao",
                    resposta="❌ Não achei a usina."),
        RegistroBot(telefone="+5517997377626", resultado="respondeu", ferramentas="confirmacao",
                    resposta="✅ Feito no meuPlano: Fechar a OS 1638"),
    ])
    db.commit()
    mig.op = types.SimpleNamespace(get_bind=db.connection)
    mig.upgrade()
    db.commit()
    assert [(r.resultado, r.erro) for r in db.query(RegistroBot).order_by(RegistroBot.id)] == [
        ("erro", "❌ O meuPlano recusou: Erro ao aplicar a ação. Nada foi feito."),
        ("respondeu", None), ("respondeu", None)]


def test_a_migracao_poe_em_erro_a_linha_59_e_tira_a_promessa_da_conversa(db):
    """A linha 59 (o resto do pedido que parou no meio) ficou "Respondeu", e a promessa "confirmando
    os dois" seguia no que a IA lê (avaliação 20). A resposta do log e as outras falas ficam."""
    import importlib.util
    import json
    import types
    from pathlib import Path

    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot

    caminho = next(Path(__file__).parents[1].glob("alembic/versions/f5a7c9e1b3d4_*.py"))
    spec = importlib.util.spec_from_file_location("mig_59", caminho)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    resposta = f"✅ Feito no meuPlano: Concluir Roçagem\n\nFaltam 2 passos…\n\n{mig.PROMESSA}.\n\nQuer a pendência?"
    turnos = [{"role": "user", "content": "Sim"}, {"role": "assistant", "content": "✅ Feito no meuPlano: Concluir"},
              {"role": "assistant", "content": f"Faltam 2 passos…\n\n{mig.PROMESSA}."}]
    db.add_all([
        RegistroBot(id=58, telefone="+5517997377626", resultado="respondeu", ferramentas="confirmacao",
                    resposta=resposta),                    # o mesmo texto em outra linha: fica
        RegistroBot(id=59, telefone="+5517997377626", resultado="respondeu", ferramentas="confirmacao",
                    resposta=resposta),
        ConversaWhatsapp(telefone="+5517997377626", mensagens=json.dumps(turnos, ensure_ascii=False)),
        ConversaWhatsapp(telefone="+5517000000000", mensagens='[{"role": "user", "content": "oi"}]'),
    ])
    db.commit()
    mig.op = types.SimpleNamespace(get_bind=db.connection)
    mig.upgrade()
    db.commit()
    db.expire_all()
    assert [(r.id, r.resultado, r.erro, r.resposta) for r in db.query(RegistroBot).order_by(RegistroBot.id)] == [
        (58, "respondeu", None, resposta), (59, "erro", mig.ERRO, resposta)]
    conversas = {c.telefone: json.loads(c.mensagens) for c in db.query(ConversaWhatsapp)}
    assert conversas["+5517997377626"] == [*turnos[:2], {"role": "assistant", "content": mig.NOTA}]
    assert conversas["+5517000000000"] == [{"role": "user", "content": "oi"}]


# ── avaliação 14 (24/10/2026): "para" é parar, o "valeu" de antes do resumo, o toque depois do deploy ──


class _MeuPlanoQueDemora(_MeuPlanoDoisPassos):
    """O 2º passo só volta quando `segura` for liberado (o modelo de lá leva de 20 a 65 s)."""

    def __init__(self, segura):
        super().__init__()
        self.segura = segura

    async def assistente_run(self, token, run_id):
        if run_id > 1:
            await self.segura.wait()
        return await super().assistente_run(token, run_id)


async def test_mensagem_mandada_antes_do_resumo_nao_derruba_o_proximo_passo(db, bot_local, monkeypatch):
    """O dono toca Sim, recebe o ✅ e, enquanto o bot busca o próximo passo, manda "valeu": o resumo
    do passo 2 saía e o "valeu" — mandado ANTES dele existir — o derrubava logo em seguida."""
    import asyncio

    from app.services import assistente_helper as h

    ceder = asyncio.sleep                                 # o de verdade: cede a vez ao turno da fila
    segura = asyncio.Event()
    falso = _MeuPlanoQueDemora(segura)
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    monkeypatch.setattr(assistente.asyncio, "sleep", lambda s: ceder(0))
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    sim = asyncio.create_task(assistente.atender(_toque(dono, 2)))
    for _ in range(50):                                   # o ✅ saiu; o bot espera o meuPlano
        await ceder(0)
        if any((m or "").startswith("✅") for m in bot_local.enviados):
            break
    valeu = asyncio.create_task(assistente.atender(_ev(dono, 3, "valeu")))   # mandado agora
    for _ in range(5):
        await ceder(0)
    segura.set()
    await sim
    await valeu
    assert dono.id in h.PENDENTES and h.PENDENTES[dono.id].resumo == "Fechar a OS 1638"
    assert not any("foi cancelada" in (m or "") for m in bot_local.enviados)
    await assistente.atender(_toque(dono, 4))
    assert falso.aplicadas == ["criar_ordem_servico", "fechar_os"]


async def test_para_e_parar_e_os_sins_comuns_confirmam(db, bot_local, monkeypatch):
    """"Ok, para tudo!" EXECUTAVA (o "para" tinha virado palavra neutra); "Tá bom", "Tudo certo",
    "Pode mandar", "Exatamente", "Joia" e o 👍🏽 derrubavam a ação."""
    from app.services import assistente_helper as h

    for sim in ("Tá bom", "ta bom", "Tudo certo", "Tudo bem", "Pode mandar", "Vai lá", "Fechou", "Uhum",
                "Sim sim", "Sim, é isso", "Exatamente", "Joia", "Com certeza", "👍🏽", "👍🏻"):
        assert h.e_sim(sim), sim
    for nao in ("Ok, para tudo!", "Beleza, para por aí", "Isso, para", "Pode fazer para mim", "Sim, mas espera",
                "Ok, não"):
        assert not h.e_sim(nao), nao
    # A lista de neutras é fechada: palavra de PARAR nunca entra nela (foi assim que "para" entrou).
    for parar in ("para", "pare", "parar", "não", "nao", "mas", "espera", "espere", "cancela", "calma", "pera"):
        assert parar not in h._NEUTRAS, parar
    for i, frase in enumerate(("Ok, para tudo!", "Tá bom"), start=1):
        h.PENDENTES.clear()
        falso = _MeuPlanoDoisPassos()
        _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
        dono = _conta(db, f"dono{i}", f"+5517997370{i:03d}")
        await assistente.atender(_ev(dono, 10 * i, PEDIDO_DOIS_PASSOS))
        await assistente.atender(_ev(dono, 10 * i + 1, frase))
        assert falso.aplicadas == ([] if "para" in frase else ["criar_ordem_servico"]), frase


async def test_o_toque_depois_do_deploy_e_o_nao_vencido_dizem_o_que_houve(db, bot_local, monkeypatch):
    """Depois de um deploy (a ação esperando vive em memória), o Sim do ÚLTIMO resumo respondia
    "Esse botão é de um resumo antigo"; e o Não de um resumo vencido ia à IA (o Sim dizia que venceu)."""
    from time import monotonic

    from app.services import assistente_helper as h

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    toque = _toque(dono, 2)
    h.PENDENTES.clear()                                  # o deploy
    await assistente.atender(toque)
    assert bot_local.enviados[-1] == h.BOTAO_SEM_ACAO and falso.aplicadas == []
    await assistente.atender(_ev(dono, 3, PEDIDO_DOIS_PASSOS))
    h.PENDENTES[dono.id].expira = monotonic() - 1        # venceu
    await assistente.atender(_toque(dono, 4, sim=False))
    assert bot_local.enviados[-1].startswith("A ação esperava a sua resposta até as") and dono.id not in h.PENDENTES


# ── avaliação 15 (24/10/2026): a correção de antes do resumo, o sim com outro número, o resultado que
#    sempre chega, o toque repetido, o passo cancelado, a IA que divide o pedido, a trilha do helper ──


async def test_correcao_mandada_antes_do_resumo_derruba_a_acao(db, bot_local, helper_com_get, monkeypatch):
    """"desliga o inversor 13" e, com a IA ainda pensando, "não, espera! é o 12": a correção não
    derrubava a ação (toda mensagem de antes do resumo era poupada), e a senha seguinte desligava o 13.
    Só a CIÊNCIA ("valeu", "ok, aguardo") mandada antes do resumo é poupada."""
    import asyncio as aio

    from app.services import assistente_helper as h

    pensando, chamou = aio.Event(), aio.Event()
    _ia_que_desliga(monkeypatch, pensando, chamou)
    dono = _dono_com_usina(db)
    pedido = aio.create_task(assistente.atender(_ev(dono, 1, "desliga o inversor 13")))
    await chamou.wait()
    correcao = aio.create_task(assistente.atender(_ev(dono, 2, "não, espera! é o inversor 12, não o 13")))
    for _ in range(3):
        await aio.sleep(0)                                 # a correção entra na fila do número
    pensando.set()
    await aio.gather(pedido, correcao)
    assert "Ação esperando a sua senha" in bot_local.enviados[0]
    assert dono.id not in h.PENDENTES and bot_local.enviados[1].endswith(h.ACAO_CANCELADA)
    await assistente.atender(_ev(dono, 3, "482913"))
    assert helper_com_get.confirmadas == [] and bot_local.enviados[-1] == h.NADA_ESPERANDO
    for ciencia in ("valeu", "Obrigado!", "ok, aguardo", "Fico no aguardo", "👍", "valeuuu", "muito obrigada"):
        assert h.so_ciencia(ciencia), ciencia
    for outra in ("cancela", "não", "não, é o 12", "ok?", "Ok, para tudo", "", "valeu, cancela", "ok 1638"):
        assert not h.so_ciencia(outra), outra


async def test_cancela_mandado_enquanto_o_bot_busca_o_proximo_passo_derruba_o_passo(db, bot_local, monkeypatch):
    """Sim no 1º passo; enquanto o bot busca o 2º no meuPlano, a pessoa manda "cancela": o 2º passo
    aparecia com os botões e continuava armado (o "cancela" ia à IA como conversa)."""
    import asyncio

    from app.services import assistente_helper as h

    ceder = asyncio.sleep
    segura = asyncio.Event()
    falso = _MeuPlanoQueDemora(segura)
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    monkeypatch.setattr(assistente.asyncio, "sleep", lambda s: ceder(0))
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    sim = asyncio.create_task(assistente.atender(_toque(dono, 2)))
    for _ in range(50):                                   # o ✅ saiu; o bot espera o meuPlano
        await ceder(0)
        if any((m or "").startswith("✅") for m in bot_local.enviados):
            break
    cancela = asyncio.create_task(assistente.atender(_ev(dono, 3, "cancela")))
    for _ in range(5):
        await ceder(0)
    segura.set()
    await sim
    await cancela
    assert "Fechar a OS 1638" in bot_local.enviados[-2] and dono.id not in h.PENDENTES
    assert bot_local.enviados[-1].startswith(h.CANCELADO_PASSO) and "OS 1843" in bot_local.enviados[-1]
    assert falso.aplicadas == ["criar_ordem_servico"]


async def test_o_sim_com_outro_numero_nao_confirma_a_acao_de_agora(db, bot_local, monkeypatch):
    """O resumo diz "Fechar a OS 1638" e a pessoa responde "Pode fechar a 1640": qualquer número
    valia como palavra neutra, e a 1638 era fechada. Número fora do resumo não confirma."""
    from app.services import assistente_helper as h

    for frase in ("Pode fechar a 1640", "Faz a 1639 e a 1640", "Sim, a 1640", "Ok, pode abrir a OS 1700"):
        assert not h.e_sim(frase, "Fechar a OS 1638"), frase
    assert h.e_sim("Pode fechar a 1638", "Fechar a OS 1638") and h.e_sim("Sim, a OS 1638", "Fechar a OS 1638")
    falso, vistos = _MeuPlanoDoisPassos(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, vistos)
    dono = _conta(db, "dono", "+5517997377626")
    assistente._proposta_do_meuplano(ger.Contexto(db=db, user=dono, telefone=dono.telefone),
                                     {"action": "fechar_os", "args": {"os_id": 1638},
                                      "preview": {"summary": "Fechar a OS 1638"}})
    h.mostrada(dono.id)
    await assistente.atender(_ev(dono, 1, "Pode fechar a 1640"))
    assert falso.aplicadas == [] and vistos[-1] == "Pode fechar a 1640"     # foi à IA, como pedido novo
    assert bot_local.enviados[-1].endswith(h.ACAO_CANCELADA_SIM) and dono.id not in h.PENDENTES


async def test_os_sins_comuns_confirmam_e_palavra_de_parar_nunca(db, bot_local, monkeypatch):
    """"Ótimo", "Sim, está correto", "Opa, pode", "Valeu, pode fazer", "Simm" e "Sim, pode criar a OS de
    Ibitinga" cancelavam a ação. Palavra do resumo conta como neutra — menos a de parar, que nunca
    confirma, nem quando está no resumo ("Mover a OS 1638 PARA concluída")."""
    from app.services import assistente_helper as h

    ibitinga = "Criar OS em UFV Ibitinga com 1 tarefa(s)"
    for sim in ("Ótimo", "Sim, está correto", "Opa, pode", "Valeu, pode fazer", "Simm", "Siiim, pode",
                "Sim, pode criar a OS de Ibitinga"):
        assert h.e_sim(sim, ibitinga), sim
    for nao in ("Valeu", "Ok, nããão", "Sim, mas só a 1638", "Sim, pode criar a OS de Pereiras"):
        assert not h.e_sim(nao, ibitinga), nao
    for nao, acao in (("Ok, para tudo!", "Mover a OS 1638 para CONCLUÍDA"), ("Sim, sem a tarefa", "Criar OS sem tarefa"),
                      ("Pode, só a 1638", "Fechar só a OS 1638 e a 1640")):
        assert not h.e_sim(nao, acao), nao
    for lista in (h._AFIRMA, h._ANTES, h._NEUTRAS, h._CIENCIA):
        assert lista.isdisjoint(h._PARAR), lista & h._PARAR
    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie a OS"))
    await assistente.atender(_ev(dono, 2, "Sim, pode criar a OS de Ibitinga"))
    assert falso.aplicadas == ["criar_ordem_servico"]


class _MeuPlanoQueLe:
    """O meuPlano que propõe pelo que LÊ: fechar a 1638 só se a última mensagem falar dela."""

    def __init__(self):
        self.aplicadas, self.conversas = [], []

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        return len(self.conversas)

    async def assistente_run(self, token, run_id):
        if "1638" in self.conversas[run_id - 1][-1]["content"] and "fechar_os" not in self.aplicadas:
            return {"status": "DONE", "type": "proposal", "action": "fechar_os", "args": {"os_id": 1638},
                    "preview": {"summary": "Fechar a OS 1638", "lines": [], "warnings": []}}
        if self.aplicadas:
            return {"status": "DONE", "type": "message", "text": "Pronto."}
        return {"status": "DONE", "type": "proposal", "action": "criar_ordem_servico", "args": {"usina_id": 37},
                "preview": {"summary": "Criar OS em UFV Ibitinga com 1 tarefa(s)", "lines": [], "warnings": []}}

    async def assistente_aplicar(self, token, acao, args):
        self.aplicadas.append(acao)
        return {"ok": True, "data": {"os_id": 1843 if acao == "criar_ordem_servico" else 1638}}


async def test_a_ia_que_divide_o_pedido_ouve_sim_e_o_resto_vai_ao_meuplano(db, bot_local, monkeypatch):
    """A IA dividiu o pedido em duas chamadas: a 2ª ouvia "esperando a SENHA" (a ação do meuPlano pede
    Sim), e depois do Sim o meuPlano não sabia do resto — respondia "Pronto." e a 1638 sumia calada."""
    import json as _json

    from app.services import assistente_helper as h

    falso, vistos = _MeuPlanoQueLe(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])

    async def _llm(msgs, ferramentas=None):
        if msgs[-1]["role"] == "tool":
            vistos.extend(m["content"] for m in msgs if m["role"] == "tool")
            return {"content": "Vou criar a OS."}
        return {"content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "manutencao", "arguments": _json.dumps(
                {"pergunta": "Crie uma OS de roçagem em Ibitinga com o Michel"})}},
            {"id": "b", "type": "function", "function": {"name": "manutencao", "arguments": _json.dumps(
                {"pergunta": "Mova a OS 1638 para concluída"})}}]}

    monkeypatch.setattr(assistente, "_llm", _llm)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    assert any("esperando o Sim" in v for v in vistos) and not any("esperando a senha" in v for v in vistos)
    await assistente.atender(_toque(dono, 2))
    assert falso.aplicadas == ["criar_ordem_servico"] and "Fechar a OS 1638" in bot_local.enviados[-1]
    assert PEDIDO_DOIS_PASSOS in falso.conversas[-1][-1]["content"]     # o pedido da pessoa foi junto
    await assistente.atender(_toque(dono, 3))
    assert falso.aplicadas == ["criar_ordem_servico", "fechar_os"] and dono.id not in h.PENDENTES


async def test_falha_ao_gravar_a_conversa_nao_engole_o_resultado_da_acao(db, bot_local, monkeypatch):
    """O Sim cria a OS no meuPlano e a gravação da conversa cai logo depois (pooler cheio): a pessoa
    recebia "Tente de novo em instantes" e não o ✅ — e repetir criaria a OS em dobro."""
    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    commit, cair = db.commit, []

    def _commit():
        if cair:
            cair.clear()
            raise RuntimeError("server closed the connection unexpectedly")
        return commit()

    aplicar = falso.assistente_aplicar

    async def _aplicar(token, acao, args):
        feito = await aplicar(token, acao, args)
        cair.append(1)                                    # a próxima ida ao banco cai
        return feito

    monkeypatch.setattr(falso, "assistente_aplicar", _aplicar)
    monkeypatch.setattr(db, "commit", _commit)
    await assistente.atender(_toque(dono, 2))
    assert falso.aplicadas == ["criar_ordem_servico"]
    assert any((m or "").startswith("✅ Feito no meuPlano: Criar OS") for m in bot_local.enviados)
    assert not any("Tente de novo" in (m or "") for m in bot_local.enviados)
    assert "Fechar a OS 1638" in bot_local.enviados[-1]          # e o pedido segue para o próximo passo


async def test_o_resultado_que_nao_saiu_vai_de_novo_e_nunca_tente_de_novo(db, bot_local, monkeypatch):
    """Depois de a ação rodar, um erro no turno (o gateway caiu ao mandar o ✅) mandava "Tente de novo"
    — um convite a criar a OS em dobro. Agora vai o resultado da ação."""
    from app.clients.whatsapp import GatewayIndisponivel

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie a OS"))
    enviar, caiu = assistente.whatsapp.enviar_conteudo, []

    async def _enviar(**k):
        if (k.get("texto") or "").startswith("✅") and not caiu:
            caiu.append(1)
            raise GatewayIndisponivel("Não foi possível falar com o gateway de WhatsApp: tempo esgotado")
        return await enviar(**k)

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    await assistente.atender(_toque(dono, 2))
    assert falso.aplicadas == ["criar_ordem_servico"] and caiu
    assert bot_local.enviados[-1].startswith("✅ Feito no meuPlano: Criar OS")
    assert not any("Tente de novo" in (m or "") for m in bot_local.enviados)


async def test_quebra_depois_do_feito_diz_que_o_resto_pode_faltar(db, bot_local, monkeypatch):
    """O ✅ saiu e o turno quebrou ao buscar o próximo passo do pedido: a pessoa ficava sem resposta
    nenhuma, esperando o resto."""
    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))

    async def _quebra(*a, **k):
        raise RuntimeError("o banco caiu")

    monkeypatch.setattr(assistente, "_seguir_no_meuplano", _quebra)
    n = len(bot_local.enviados)
    await assistente.atender(_toque(dono, 2))
    feito, aviso = bot_local.enviados[n:]
    assert feito.startswith("✅ Feito no meuPlano: Criar OS") and falso.aplicadas == ["criar_ordem_servico"]
    assert aviso == ("⚠️ Não consegui conferir se o seu pedido tinha mais passos. Já foi feito: Criar OS em UFV "
                     "Ibitinga com 1 tarefa(s). Se faltava algo, peça de novo.")


async def test_quebra_depois_de_um_passo_recusado_nao_diz_que_foi_feito(db, bot_local, monkeypatch):
    falso = _MeuPlanoDoisPassos(falha_2=409)
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    await assistente.atender(_toque(dono, 2))
    real, vezes = assistente._resumo_saiu, []

    def _quebra_uma_vez(db, user, saiu):
        if not vezes:
            vezes.append(1)
            raise RuntimeError("o banco caiu")
        return real(db, user, saiu)

    monkeypatch.setattr(assistente, "_resumo_saiu", _quebra_uma_vez)
    await assistente.atender(_toque(dono, 3))
    assert vezes and bot_local.enviados[-1].startswith("❌ O meuPlano recusou")


async def test_o_toque_de_novo_no_sim_de_uma_acao_feita_diz_que_ja_foi(db, bot_local, monkeypatch):
    """Toque duplo (ou um toque minutos depois) no Sim de um resumo JÁ executado ouvia "Nada foi feito
    — se ainda quiser, peça de novo", logo abaixo do ✅ da mesma ação."""
    import asyncio

    from app.services import assistente_helper as h

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    toque = _toque(dono, 2)
    await asyncio.gather(assistente.atender(toque), assistente.atender({**toque, "id": 3}))
    ja = bot_local.enviados[-1]
    assert ja.startswith("Essa ação já foi confirmada") and "✅ Feito no meuPlano: Criar OS" in ja and "OS 1843" in ja
    assert "Nada foi feito" not in ja and falso.aplicadas == ["criar_ordem_servico"]
    await assistente.atender({**toque, "id": 4, "texto": "Não", "botao": toque["botao"].replace("sim:", "nao:")})
    assert bot_local.enviados[-1] == ja and falso.aplicadas == ["criar_ordem_servico"]
    assert h.PENDENTES[dono.id].resumo == "Fechar a OS 1638"     # o passo seguinte continua esperando


async def test_nao_no_segundo_passo_diz_o_que_o_primeiro_ja_fez(db, bot_local, monkeypatch):
    """Sim no 1º passo (a OS 1843 nasce), Não no 2º: "Cancelado… Nada foi feito" escondia a OS 1843."""
    from app.services import assistente_helper as h

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    await assistente.atender(_toque(dono, 2))
    await assistente.atender(_toque(dono, 3, sim=False))
    resposta = bot_local.enviados[-1]
    assert resposta.startswith(h.CANCELADO_PASSO) and "Nada foi feito" not in resposta
    assert (f"Do seu pedido «{PEDIDO_DOIS_PASSOS}», antes disso já foi feito: Criar OS em UFV Ibitinga com 1 tarefa(s) "
            "(OS 1843, PROGRAMADA)") in resposta
    assert falso.aplicadas == ["criar_ordem_servico"] and dono.id not in h.PENDENTES


async def test_a_trilha_de_auditoria_do_helper_so_traz_as_usinas_liberadas(db, helper_com_get, monkeypatch):
    """`GET /api/audit/list` diz a usina em `plant`, campo que o recorte não olhava: os eventos de usina
    NÃO liberada passavam inteiros (com e-mail e IP de quem fez)."""
    from app.services import assistente_helper as h

    eventos = [{"id": 1, "plant": "pirapozinho", "email": "a@x.com"}, {"id": 2, "plant": "de-outro", "email": "b@y.com"},
               {"id": 3, "plant": None, "action": "login"}]
    chamar = helper_com_get.chamar

    async def _chamar(rota, corpo, origem, metodo="POST"):
        if rota.startswith("/api/audit/list"):
            return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": {"ok": True, "events": eventos}}
        return await chamar(rota, corpo, origem, metodo)

    monkeypatch.setattr(helper_com_get, "chamar", _chamar)
    dono = _dono_com_usina(db)
    r = await h.usina_helper(ger.Contexto(db=db, user=dono, telefone=dono.telefone),
                             {"rota": "/api/audit/list?limit=50", "metodo": "GET"})
    assert [e["id"] for e in r["resposta"]["events"]] == [1, 3]


# ── avaliação 16 (24/10/2026): o sim do jeito que se fala, a afirmativa ambígua, a IA avisada do
#    cancelamento, o toque depois de a própria mensagem cancelar, o passo que se repete ──


class _MeuPlanoQueRepete:
    """O assistente do meuPlano que propõe `acao` com os argumentos de cada vez (`args_por_vez`), e
    depois "Pronto." — o resumo é o de lá, montado com os argumentos."""

    def __init__(self, *args_por_vez, acao="fechar_os", resumo="Fechar a OS {os_id} (Roçagem)"):
        self.args_por_vez, self.acao, self.resumo = args_por_vez, acao, resumo
        self.aplicadas, self.conversas, self.linhas = [], [], []

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        return len(self.conversas)

    async def assistente_run(self, token, run_id):
        if run_id > len(self.args_por_vez):
            return {"status": "DONE", "type": "message", "text": "Pronto."}
        args = self.args_por_vez[run_id - 1]
        return {"status": "DONE", "type": "proposal", "action": self.acao, "args": dict(args),
                "preview": {"summary": self.resumo.format(**args), "lines": [{"text": t} for t in self.linhas],
                            "warnings": []}}

    async def assistente_aplicar(self, token, acao, args):
        self.aplicadas.append((acao, args))
        return {"ok": True, "data": {}}


TROCAR = "Trocar o equipamento de 1 ponto(s) por Huawei SUN2000-100KTL."


def test_as_afirmativas_comuns_confirmam_qualquer_resumo_e_trocar_so_o_do_resumo():
    """"Sim, com certeza", "Sim, sem problema", "Claro que sim" e "Sim senhor" CANCELAVAM a ação ("com", "que",
    "senhor" não eram neutras; "sem" é de restringir) — e "Sim, com certeza" confirmava "Criar OS… com…" só
    porque o resumo tinha "com". "Pode trocar" nunca confirmava "Trocar o equipamento…"."""
    from app.services import assistente_helper as h

    resumos = ("Fechar a OS 1638", "Criar OS em UFV Ibitinga com 1 tarefa(s)", TROCAR)
    for frase in ("Sim, com certeza", "Com certeza", "Sim, sem problema", "Sem problemas", "Pode sim, sem problemas",
                  "Sim, sem problema nenhum", "Sim, sem dúvida", "Sem duvida", "Claro que sim", "Claro que pode",
                  "Sim senhor", "Sim, senhora", "Por favor", "Sim, por favor", "Afirmativo", "Tranquilo, pode"):
        for resumo in resumos:
            assert h.e_sim(frase, resumo), (frase, resumo)
    for frase in ("Com certeza não", "Sem problema, mas amanhã", "Claro que não", "Sim senhor, cancela",
                  "Sem dúvida nenhuma, só a 1638", "Por favor, para", "Sim, sem a tarefa"):
        for resumo in resumos:
            assert not h.e_sim(frase, resumo), (frase, resumo)
    for frase in ("Pode trocar", "Sim, pode trocar", "Pode trocar o equipamento"):
        assert h.e_sim(frase, TROCAR) and not h.e_sim(frase, "Fechar a OS 1638"), frase   # fora do resumo, é correção
    # Negar, parar e restringir nunca são isentados, nem quando estão no resumo.
    for frase, resumo in (("Ok, para tudo!", "Mover a OS 1638 para CONCLUÍDA"), ("Sim, nada pendente", "Fechar: nada pendente"),
                          ("Pode, só a 1638", "Fechar só a OS 1638 e a 1640"), ("Pode, sem a tarefa", "Criar OS sem tarefa"),
                          ("Pode trocar por outro", TROCAR), ("Sim, mas pode trocar", TROCAR)):
        assert not h.e_sim(frase, resumo), frase
    for lista in (h._AFIRMA, h._ANTES, h._NEUTRAS, h._CIENCIA):
        assert lista.isdisjoint(h._PARAR), lista & h._PARAR


async def test_o_sim_do_jeito_que_se_fala_confirma_a_acao_no_turno(db, bot_local, monkeypatch):
    from app.services import assistente_helper as h

    for i, (frase, acao, args, resumo) in enumerate((
            ("Sim, com certeza", "fechar_os", {"os_id": 1638}, "Fechar a OS {os_id} (Roçagem)"),
            ("Pode trocar", "trocar_equipamento", {"node_ids": [11260], "model_id": 7}, TROCAR)), start=1):
        h.PENDENTES.clear()
        falso = _MeuPlanoQueRepete(args, acao=acao, resumo=resumo)
        _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
        dono = _conta(db, f"dono{i}", f"+551799737000{i}")
        await assistente.atender(_ev(dono, 10 * i, "crie"))
        await assistente.atender(_ev(dono, 10 * i + 1, frase))
        assert falso.aplicadas == [(acao, args)], frase
    assert not any("foi cancelada" in (m or "") for m in bot_local.enviados)


def test_o_verbo_da_acao_e_o_sim_falado_confirmam_e_assunto_novo_vai_a_ia():
    """Avaliação 17: "Fecha", "Feche", "Não tem problema" e "Top" cancelavam o "Fechar a OS 1638"; e
    um pedido novo curto que começa por "Ok/Pode" ("Ok, e Pereiras", "Pode mandar o PDF") era
    ENGOLIDO — o sistema só repetia "toque em Sim" e a IA nunca via o pedido."""
    from app.services import assistente_helper as h

    fechar = "Fechar a OS 1638 (Roçagem): as 1 tarefa(s) estão concluídas."
    criar = "Criar OS em UFV Ibitinga com 1 tarefa(s), programada para 2026-10-23 com Michel."
    trocar = "Trocar o equipamento do ponto 11260 pelo 8615."
    r = h._resposta_ao_resumo
    for t in ("Fecha", "Feche", "Fecha aí", "Pode fechar ela", "Não tem problema", "Vai em frente",
              "Pode ir em frente", "Sim, só isso", "Sim, nada a acrescentar", "Top", "Boa", "Massa", "Yes", "Si"):
        assert r(t, fechar) == "sim", t
    assert r("Troque", trocar) == "sim" and r("Cria", criar) == "sim"
    # o verbo é o da AÇÃO (o primeiro do resumo): "Fecha" não cria OS, "Conclua" não casa com "concluídas"
    for t, resumo in (("Fecha", criar), ("Conclua", fechar), ("Fecha a 1640", fechar), ("Troque o técnico", criar),
                      ("Não tem problema se não fechar", fechar), ("Feche não", fechar)):
        assert r(t, resumo) == "outra", t
    for t in ("Ok, e Pereiras", "Pode mandar o PDF", "Beleza, geração de hoje", "Ok, qual o técnico", "Pode ver Pereiras"):
        assert r(t, fechar) == "outra", t                                 # assunto novo: vai à IA
    for t in ("Sim, pode deixar", "Ok, vou ver"):
        assert r(t, fechar) == "duvida", t                                # sem assunto: pergunta de novo


def test_verbo_de_outra_acao_nunca_confirma():
    """Avaliação 18: os verbos de ação contavam como palavra neutra — "Pode criar" confirmava "APAGAR 3
    item(ns) — 41 nó(s)", "Ok, cria o contato" confirmava "Apagar o contato…" e "Pode abrir a OS"
    FECHAVA a 1638. Só o verbo (ou o substantivo) da PRÓPRIA ação confirma; o de outra, nunca."""
    from app.services import assistente_helper as h

    r = h._resposta_ao_resumo
    apagar_nos = "APAGAR 3 item(ns) — 41 nó(s) no total (cascata)."
    apagar_contato = "Apagar o contato 'Michel Renan' (#412)."
    fechar = "Fechar a OS 1638 (Roçagem): as 1 tarefa(s) estão concluídas."
    criar = "Criar OS em UFV Ibitinga com 1 tarefa(s), programada para 2026-10-23 com Michel."
    desinstalar = "Desinstalar o equipamento de 1 ponto(s)."
    remover = "Remover o material 'Fusível 15A' de INV-13."
    for t, resumo in (("Pode criar", apagar_nos), ("Sim, crie", apagar_nos), ("Pode fechar", apagar_nos),
                      ("Ok, registra", apagar_nos), ("Ok, cria o contato", apagar_contato),
                      ("Pode registrar", apagar_contato), ("Sim, lança", apagar_contato), ("Pode abrir a OS", fechar),
                      ("Ok, lança o dia", fechar), ("Sim, conclua a OS", criar), ("Pode trocar", desinstalar),
                      ("Pode criar", remover), ("Pode concluir", fechar)):
        assert r(t, resumo) != "sim", (t, resumo)
    for t, resumo in (("Pode apagar", apagar_nos), ("Apaga", apagar_contato), ("Exclua", apagar_contato),
                      ("Confirmo o fechamento", fechar), ("Confirmo a criação", criar), ("Pode abrir", criar),
                      ("Pode desinstalar", desinstalar), ("Remove", remover),
                      ("Edita", "Editar 5 nó(s) — 5 alteração(ões) no total."), ("Concordo", fechar),
                      ("Vamos lá", fechar), ("Vamos", fechar), ("Por mim pode", fechar), ("Pode fechar já", fechar),
                      ("Não tem problema nenhum", fechar), ("Manda brasa", fechar), ("Pode executar", apagar_contato)):
        assert r(t, resumo) == "sim", (t, resumo)
    assert r("Ok, vamos ver", fechar) == "duvida" and r("Vamos ver", fechar) == "outra"      # hesitar não confirma
    # o verbo de outra ação não confirma nem quando o resumo o cita: a ação é a do PRIMEIRO verbo
    assert r("Pode criar", "Fechar a OS 1638 e criar a próxima.") == "duvida"
    # e nenhum verbo de ação mora nas listas de palavras neutras (era assim que "Pode criar" passava)
    assert not set(h._VERBOS) & (h._NEUTRAS | h._AFIRMA | h._CIENCIA | h._SEM_ASSUNTO)


def test_citar_parte_dos_itens_ou_das_pessoas_e_hesitar_nao_confirma():
    """Avaliação 19: com "APAGAR 3 item(ns) — 41 nó(s)" esperando, "Apaga o INV-13" e "Sim, o inversor 13"
    confirmavam os TRÊS; "Sim, o Michel" confirmava a conclusão "por Michel…, Diogo…"; "Bem...", "Bom..."
    e 🙏 confirmavam. Agora é dúvida: o sistema pergunta de novo."""
    from app.services import assistente_helper as h

    r = h._resposta_ao_resumo
    apagar = ("APAGAR 3 item(ns) — 41 nó(s) no total (cascata).",
              ("Inversor 13 (INV-13)", "Inversor 14 (INV-14)", "Inversor 15 (INV-15)"))
    acessos = ("Apagar 3 acesso(s)", ("SmartLogger 1 · rede/admin", "SmartLogger 2 · rede/admin", "Relé 52 · rede/admin"))
    concluir = ("Concluir Roçagem na OS 1638 — 23/10 a 24/10/2026, por Michel Renan Soares Ferreira, Diogo Dardani.",
                ("OS 1638 · tarefa 8873 Roçagem", "Feito em 23/10 a 24/10/2026 (2 dia(s))"))
    fechar = ("Fechar a OS 1638 (Roçagem): as 1 tarefa(s) estão concluídas.", ("#8873 Roçagem — realizada",))
    for t, (resumo, itens) in (("Apaga o INV-13", apagar), ("Sim, o inversor 13", apagar), ("Ok, o INV-14", apagar),
                               ("Pode apagar o 13 e o 14", apagar), ("Apaga o do relé 52", acessos),
                               ("Sim, o Michel", concluir), ("Bem...", fechar), ("Bom...", fechar), ("Hmm", fechar),
                               ("🙏", fechar), ("🙏🏽", fechar)):
        assert r(t, resumo, itens) == "duvida", t
    for t, (resumo, itens) in (("Pode apagar", apagar), ("Pode apagar os 3", apagar), ("Apaga", acessos),
                               ("Sim, o Michel e o Diogo", concluir), ("Pode concluir", concluir), ("Tá bom", fechar),
                               ("Tudo bem", fechar), ("Muito bem, pode fechar", fechar), ("Sim, a 8873", fechar),
                               ("Sim, com o Michel", ("Criar OS em UFV Ibitinga, programada com Michel Renan.", ()))):
        assert r(t, resumo, itens) == "sim", t
    assert h._pessoas_do_resumo("Criar OS em UFV Ibitinga com 1 tarefa(s), programada com Michel Renan.") == []


def test_numa_acao_de_varios_alvos_so_confirma_quem_cita_todos():
    """Avaliação 20: "Apaga o 3" diante de "APAGAR 3 item(ns)" (com o INV-3 entre eles) apagava os TRÊS —
    a palavra estava no resumo e contava como neutra. Numa ação de vários alvos (ou que apaga), o alvo
    citado só confirma se alcança todas as linhas; "todos", "os 3", "os inversores" confirmam."""
    from app.services import assistente_helper as h

    r = h._resposta_ao_resumo
    apagar = ("APAGAR 3 item(ns) — 41 nó(s) no total (cascata).", ("Inversor 1 (INV-1)", "Inversor 2 (INV-2)",
                                                                   "Inversor 3 (INV-3)"))
    ligacoes = ("Apagar 2 ligação(ões) de rede.", ("Switch 1 —[fibra]→ SmartLogger 1", "Switch 1 —[fibra]→ SmartLogger 2"))
    editar = ("Editar 4 nó(s) em Ibitinga, Pereiras — 4 alteração(ões) no total.",
              ("Usina: Ibitinga, Pereiras", "INV-01: nome 'INV 01' → 'Inversor 01'", "INV-02: nome 'INV 02' → 'Inversor 02'"))
    desinstalar = ("Desinstalar o equipamento de 2 ponto(s).", ("Ponto 1 · INV-01", "Ponto 2 · INV-02"))
    real = ("Concluir Roçagem na OS 1638 — 23/10 a 24/10/2026, por Michel Renan Soares Ferreira, Diogo Dardani.",
            ("OS 1638 · tarefa 8873 Roçagem", "Feito em 23/10 a 24/10/2026 (2 dia(s))", "Dias já lançados: 21/09",
             "Por: Michel Renan Soares Ferreira, Diogo Dardani", "Parecer: aprovado"))
    fechar = ("Fechar a OS 1638 (Roçagem): as 1 tarefa(s) estão concluídas.", ("#8873 Roçagem — realizada",))
    for t, (resumo, itens) in (("Apaga o 3", apagar), ("Pode apagar o 3", apagar), ("Sim, o 3", apagar),
                               ("Apaga a 2", ligacoes), ("Pode editar em Ibitinga", editar), ("Sim, em Ibitinga", editar),
                               ("Desinstala o 2", desinstalar), ("Sim, o Diogo", real)):
        assert r(t, resumo, itens) == "duvida", t
    for t, (resumo, itens) in (("Pode apagar todos", apagar), ("Pode apagar os três", apagar),
                               ("Pode apagar os 3", apagar), ("Apaga os 3 inversores", apagar),
                               ("Pode apagar os inversores", apagar), ("Apaga INV-1, INV-2 e INV-3", apagar),
                               ("Pode apagar as duas", ligacoes), ("Pode desinstalar os dois", desinstalar),
                               ("Sim, os dois", real), ("Sim, Michel e Diogo", real), ("Sim, é isso", real),
                               ("Sim, aprovado", real), ("Pode concluir a tarefa", real), ("Sim e obrigado", real),
                               ("Sim, já pode", real), ("s", real), ("Tá", real), ("Então tá", real), ("Pode crer", real),
                               ("Demorou", real), ("Pode fechar a OS 1638", fechar)):
        assert r(t, resumo, itens) == "sim", t
    assert r("Pode fechar todas", *fechar) != "sim"         # "todas" numa ação de um alvo só não é ela


def test_o_plural_de_um_tipo_numa_lista_mista_e_a_pergunta_com_emoji_nao_confirmam():
    """Avaliação 21: com a prévia REAL de Ibitinga («APAGAR 3 item(ns) — 12 nó(s)»: dois inversores e a
    Medição), "Pode apagar os inversores" apagava a Medição junto — o plural de UM tipo valia como "todos".
    Só vale quando é o que o resumo conta ("os itens", "os 12 nós") ou quando todos os itens são daquele
    tipo. E "Apaga?!", "Apagar? 🤔", "Fecha?..." confirmavam: pergunta nunca confirma."""
    from app.services import assistente_helper as h

    r = h._resposta_ao_resumo
    resumo = "APAGAR 3 item(ns) — 12 nó(s) no total (cascata)."
    misto = ("Inversor 1 (Inversor1)", "Inversor 2 (Inversor2)", "Medição (AGR01)")
    inversores = ("Inversor 1 (Inversor1)", "Inversor 2 (Inversor2)", "Inversor 3 (Inversor3)")
    for t in ("Pode apagar os inversores", "Sim, os inversores", "Pode apagar ambos os inversores", "Apaga ambos",
              "Pode apagar todos os inversores", "Apaga os inversores", "Pode apagar o inversor 1 e o 2"):
        assert r(t, resumo, misto) == "duvida", t
    for t in ("Pode apagar todos", "Pode apagar os itens", "Sim, os três", "Pode apagar os 3", "Apaga tudo",
              "Pode apagar os 12 nós", "Apaga o 1, o 2 e a medição"):
        assert r(t, resumo, misto) == "sim", t
    for t in ("Pode apagar os inversores", "Sim, todos os inversores"):
        assert r(t, resumo, inversores) == "sim", t
    assert r("Pode apagar ambas", "Apagar 2 ligação(ões) de rede.", ("Switch 1 → SL 1", "Switch 1 → SL 2")) == "sim"
    assert r("Sim, crie a OS 1639", "Abrir a OS 1639") == "sim"            # "a OS 1639" não é quantidade
    for t in ("Apagar? 🤔", "Apaga? 😳", "Apaga?!", "Sim? 😅", "Sim?!", "Pode fechar?!", "Fecha?..."):
        assert r(t, resumo, inversores) == "outra" and r(t, "Fechar a OS 1638") == "outra", t
    # a pergunta escrita com outro sinal e o emoji de dúvida (avaliação 22: "Apaga❓" e "Sim 🤔" apagavam)
    for t in ("Apaga❓", "Apaga⁉️", "Pode apagar❔", "Sim❓", "Apaga？", "¿Apaga", "Apaga mesmo❓"):
        assert r(t, resumo, inversores) == "outra" and r(t, "Fechar a OS 1638") == "outra", t
    for t in ("Apagar 🤔", "Sim 🤔", "Pode apagar 😬", "Fecha 😳"):
        assert r(t, resumo, inversores) == "duvida" and r(t, "Fechar a OS 1638") == "duvida", t
    # a lista fechada é a do SIM: qualquer outro emoji é dúvida (avaliação 23: "Apaga ❌" e "Sim 👎" apagavam)
    for t in ("Apaga ❌", "Sim 👎", "Pode apagar ✋", "Sim 🛑", "Apaga ⛔", "Apaga 🤷", "Sim 🙄", "🙏", "Sim 🙏"):
        assert r(t, resumo, inversores) == "duvida" and r(t, "Fechar a OS 1638") == "duvida", t
    for t in ("Sim 👍🏽", "Pode apagar ✅", "Sim ❤️", "Sim 😊", "Sim, obg", "Sim vlw", "Sim, pfv", "Pode, obg", "Sim, tmj",
              "Sim pf", "Sí", "Yep", "Simbora"):
        assert r(t, resumo, inversores) == "sim", t                  # o agradecimento abreviado é neutro
    assert r("Apaga‽", resumo, inversores) == "outra"
    # o pronome: no singular é UM alvo — numa ação de vários, qual? —; no plural, todos (avaliação 24: "Pode apagar
    # esse" apagava os três)
    for t in ("Pode apagar esse", "Apaga ele", "Apaga ela", "Pode apagar essa", "Sim, esse", "Ok, apaga esse", "Apaga este"):
        assert r(t, resumo, inversores) == "duvida", t
    for t in ("Apaga esses", "Pode apagar eles", "Pode apagar esses aí"):
        assert r(t, resumo, inversores) == "sim", t
    assert r("Pode fechar ela", "Fechar a OS 1638") == "sim" and r("Fecha essa", "Fechar a OS 1638") == "sim"
    # o emoticon de texto de dúvida pergunta de novo (confirmavam); o alegre não atrapalha
    for t in ("Apaga :/", "Sim :(", "Pode apagar :-(", "Sim -_-", "Apaga :|", "Sim ¬¬", "Apaga ._.", "Sim :'(", "Apaga D:"):
        assert r(t, resumo, inversores) == "duvida", t
    for t in ("Sim :)", "Fecha :D", "Sim ;)", "Sim ✓", "Fechou 🤙", "É pra fechar", "Isso mesmo"):
        assert r(t, "Fechar a OS 1638") == "sim", t
    assert r("Pode fechar mesmo", "Fechar a OS 1638") == "duvida"     # a pergunta sem "?"
    # o emoticon só de sinais: a lista fechada é a dos ALEGRES (avaliação 25: "Apaga ;-;" e "Sim -.-" apagavam)
    for t in ("Apaga ;-;", "Apaga ;_;", "Sim -.-", "Apaga -.-'", "Pode apagar >.<", "Apaga ¬_¬", "Sim ¬.¬", "Apaga ):",
              "Sim :<", "Pode apagar :-<", "Apaga e.e", "Apaga -__-", "Apaga isso aí"):
        assert r(t, resumo, inversores) == "duvida", t
    for t in ("Sim xD", "Sim!!", "Sim...", "Pode apagar todos ;)"):
        assert r(t, resumo, inversores) == "sim", t


async def test_a_pergunta_de_novo_diz_que_o_sim_vale_para_tudo(db, bot_local, monkeypatch):
    """Avaliação 21: "Apaga o 15" virava dúvida (certo), mas a pergunta repetia só «APAGAR 3 item(ns)…» —
    sem as linhas e sem dizer que o Sim apaga os TRÊS; o toque seguinte apagava os três."""
    from app.services import assistente_helper as h

    falso = _MeuPlanoQueRepete({"node_ids": [13, 14, 15]}, acao="apagar_nos",
                               resumo="APAGAR 3 item(ns) — 41 nó(s) no total (cascata).")
    falso.linhas = ["Inversor 13 (INV-13)", "Inversor 14 (INV-14)", "Inversor 15 (INV-15)"]
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie: apaga os inversores 13 a 15"))
    await assistente.atender(_ev(dono, 2, "Apaga o 15"))
    assert falso.aplicadas == [] and dono.id in h.PENDENTES
    de_novo = bot_local.enviados[-1]
    assert "O *Sim* vale para TUDO isto" in de_novo and "Se era só uma parte" in de_novo
    assert all(f"– Inversor {n} (INV-{n})" in de_novo for n in (13, 14, 15)), de_novo


async def test_afirmativa_ambigua_nao_cancela_e_o_sistema_pergunta_de_novo(db, bot_local, monkeypatch):
    """"Sim, pode deixar" — começa como sim, mas não é um SIM limpo — DERRUBAVA a ação: o contrário do que a
    pessoa disse. Agora ela continua esperando, e o SISTEMA (não a IA) diz como confirmar, com os botões."""
    from app.services import assistente_helper as h

    falso, vistos = _MeuPlanoDoisPassos(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, vistos)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie a OS"))
    assert "na dúvida, pergunto de novo" in bot_local.enviados[-1] and "Qualquer outra mensagem" not in bot_local.enviados[-1]
    codigo, n = h.PENDENTES[dono.id].codigo, len(vistos)
    await assistente.atender(_ev(dono, 2, "Sim, pode deixar"))
    assert dono.id in h.PENDENTES and len(vistos) == n and falso.aplicadas == []      # armada; a IA nem soube
    assert bot_local.enviados[-1] == h.DE_NOVO.format(escopo=h._escopo(h.PENDENTES[dono.id]),
                                                       limite=h._limite(h.PENDENTES[dono.id]))
    assert "• Criar OS em UFV Ibitinga com 1 tarefa(s)" in bot_local.enviados[-1]
    assert bot_local.botoes[-1] == [f"sim:{codigo}", f"nao:{codigo}"]               # os do MESMO resumo
    # só a resposta CURTA é dúvida; a longa é outro assunto (derruba e vai à IA) — perguntar de novo
    # engoliria o pedido
    acao = h.PENDENTES[dono.id]
    assert [h._resposta_ao_resumo(t, acao.resumo, acao.detalhes) for t in ("Sim, pode deixar", "Ok, pode deixar comigo",
            "Pode me mandar o relatório da Porto Ferreira", "Ok, e a geração de hoje")] == [
        "duvida", "duvida", "outra", "outra"]
    await assistente.atender(_toque(dono, 3))
    assert falso.aplicadas == ["criar_ordem_servico"]
    from time import monotonic

    h.PENDENTES[dono.id].expira = monotonic() - 1                                  # o 2º passo venceu
    await assistente.atender(_ev(dono, 4, "Sim, pode deixar"))
    assert bot_local.enviados[-1].startswith("A ação esperava a sua resposta até as") and dono.id not in h.PENDENTES


async def test_a_ia_sabe_que_a_mensagem_cancelou_a_acao(db, bot_local, monkeypatch):
    """A correção derruba a ação e vai à IA — que não sabia: podia responder "vou fechar" com "(foi
    cancelada)" logo embaixo. O sistema diz a ela, só naquela mensagem, o que foi cancelado."""
    falso, sistemas = _MeuPlanoDoisPassos(), []
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    ia = assistente._llm

    async def _llm(msgs, ferramentas=None):
        sistemas.append(msgs[0]["content"])
        return await ia(msgs, ferramentas)

    monkeypatch.setattr(assistente, "_llm", _llm)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie a OS"))
    assert not any("foi CANCELADA" in s for s in sistemas)
    await assistente.atender(_ev(dono, 2, "Não, o técnico é o Diogo"))
    assert ("a ação «Criar OS em UFV Ibitinga com 1 tarefa(s)», que esperava a confirmação da pessoa, foi CANCELADA "
            "por esta mensagem") in sistemas[-1]
    await assistente.atender(_ev(dono, 3, "e a geração de hoje?"))
    assert "foi CANCELADA" not in sistemas[-1]


async def test_o_toque_depois_de_a_propria_mensagem_cancelar_diz_isso(db, bot_local, monkeypatch):
    """A correção derrubou a ação e a pessoa, vendo que não foi feita, tocou no Sim daquele resumo: ouvia "o
    pedido venceu ou o bot foi atualizado" — quem derrubou foi a mensagem dela, um minuto antes. O trecho
    citado é o que já saiu sem a senha."""
    from app.core.security import gerar_hash_senha
    from app.services import assistente_helper as h

    falso = _MeuPlanoDoisPassos()
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    dono = _conta(db, "dono", "+5517997377626")
    dono.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    for i, (frase, trecho) in enumerate((("Não, o técnico é o Diogo", "Não, o técnico é o Diogo"),
                                         ("Não, a senha é 482913", "Não, a senha é [senha oculta]")), start=1):
        await assistente.atender(_ev(dono, 10 * i, "crie a OS"))
        sim, nao = _toque(dono, 10 * i + 1), _toque(dono, 10 * i + 2, sim=False)
        await assistente.atender(_ev(dono, 10 * i + 3, frase))
        for toque in (sim, nao):
            await assistente.atender(toque)
            assert bot_local.enviados[-1] == h.CANCELADA_PELA_MENSAGEM.format(trecho=trecho)
    assert falso.aplicadas == [] and not any("482913" in (m or "") for m in bot_local.enviados)


class _MeuPlanoQueDevolve(_MeuPlanoQueRepete):
    """Propõe desinstalar 2 pontos e, no apply, devolve o `data` dado — o resultado REAL do handler de lá."""

    def __init__(self, dados):
        super().__init__({"node_ids": [1, 2]}, acao="desinstalar_equipamento",
                         resumo="Desinstalar o equipamento de 2 ponto(s).")
        self.dados = dados

    async def assistente_aplicar(self, token, acao, args):
        self.aplicadas.append((acao, args))
        return {"ok": True, "message": "Ação aplicada.", "data": self.dados}


async def test_o_feito_diz_o_resultado_real_do_meuplano(db, bot_local, monkeypatch):
    """Avaliação 22, contra o meuPlano real: desinstalar os Inversores 1 e 2 voltou "1 equipamento(s)
    removido(s); 0 vazio(s); 1 bloqueado(s)" e o bot dizia "✅ Feito… Desinstalar o equipamento de 2
    ponto(s)", com o log verde. E o handler que recusa sem gravar responde 200 com `erro`."""
    from app.models.conversa_whatsapp import RegistroBot

    bloqueado = {"removidos": 1, "pulados_vazios": 0, "resumo": "1 equipamento(s) removido(s); 0 vazio(s); 1 bloqueado(s).",
                 "erros": [{"node_id": 1, "detail": "Inversor 1 tem 9 ensaios: não dá para desinstalar."}]}
    recusa = {"erro": "Não dá para apagar 'Huawei': está em uso por 3 equipamento(s)/modelo(s).", "total": 3}
    inteiro = {"removidos": 2, "resumo": "2 equipamento(s) removido(s); 0 vazio(s); 0 bloqueado(s)."}
    sem_resumo = {"criadas": 1, "erros": [{"source": 1}, {"source": 2}]}           # sem o motivo de cada um
    # todos falharam: nada foi feito — "EM PARTE" mentia (avaliação 23, o ensaio de lá com o nó 6539)
    nada = {"removidos": 0, "pulados_vazios": 1, "resumo": "0 equipamento(s) removido(s); 1 vazio(s); 1 bloqueado(s).",
            "erros": [{"node_id": 6539, "detail": "Inversor 1 tem 9 ensaios: não dá para desinstalar."}]}
    casos = ((bloqueado, "⚠️ Feito EM PARTE no meuPlano: Desinstalar o equipamento de 2 ponto(s). Resultado: 1 "
                         "equipamento(s) removido(s); 0 vazio(s); 1 bloqueado(s).\n• Inversor 1 tem 9 ensaios", "erro", 1),
             (recusa, "❌ O meuPlano recusou: Não dá para apagar 'Huawei': está em uso por 3 equipamento(s)/modelo(s). "
                      "Nada foi feito.", "erro", 1),
             (inteiro, "✅ Feito no meuPlano: Desinstalar o equipamento de 2 ponto(s). Resultado: 2 equipamento(s) "
                       "removido(s); 0 vazio(s); 0 bloqueado(s).", "respondeu", 2),
             (sem_resumo, "⚠️ Feito EM PARTE no meuPlano: Desinstalar o equipamento de 2 ponto(s): 2 item(ns) com "
                          "falha.\n\n", "erro", 1),
             (nada, "❌ O meuPlano recusou: Desinstalar o equipamento de 2 ponto(s). Resultado: 0 equipamento(s) "
                    "removido(s); 1 vazio(s); 1 bloqueado(s).\n• Inversor 1 tem 9 ensaios: não dá para desinstalar."
                    "\n\nNada foi feito.", "erro", 1))
    for n, (dados, comeca, resultado, perguntas) in enumerate(casos):
        falso = _MeuPlanoQueDevolve(dados)
        _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
        dono = _conta(db, f"dono{n}", f"+55179973771{n:02d}")
        await assistente.atender(_ev(dono, 10 * n + 1, "crie: desinstala os inversores 1 e 2"))
        antes = len(bot_local.enviados)
        await assistente.atender(_toque(dono, 10 * n + 2))
        assert bot_local.enviados[antes].startswith(comeca), (n, bot_local.enviados[antes])
        assert db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().resultado == resultado, n
        assert len(falso.conversas) == perguntas, n                 # em parte ou recusado: não segue para o resto


async def test_o_passo_seguinte_que_repete_o_que_acabou_de_ser_feito_nao_e_oferecido(db, bot_local, monkeypatch):
    """Num pedido de vários passos, nada impedia o meuPlano de repropor a MESMA ação que acabou de ser feita
    — e o próximo Sim a faria duas vezes. Mesma ação e mesmos argumentos: é o fim do pedido. Outros
    argumentos são outro passo."""
    from app.services import assistente_helper as h

    for i, (segundo, oferecido) in enumerate((({"os_id": 1638}, False), ({"os_id": 1640}, True)), start=1):
        h.PENDENTES.clear()
        falso, decisoes = _MeuPlanoQueRepete({"os_id": 1638}, segundo), []
        _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
        _resto(monkeypatch, *SEGUE_E_ACABA, vistos=decisoes)
        dono = _conta(db, f"dono{i}", f"+551799737000{i}")
        await assistente.atender(_ev(dono, 10 * i, "crie: feche a 1638"))
        await assistente.atender(_toque(dono, 10 * i + 1))
        assert falso.aplicadas == [("fechar_os", {"os_id": 1638})]                # uma vez só
        if oferecido:
            assert h.PENDENTES[dono.id].resumo == "Fechar a OS 1640 (Roçagem)" and len(falso.conversas) == 2
        else:
            # a IA fica sabendo que o meuPlano repetiu o passo e decide (aqui, o fim)
            assert dono.id not in h.PENDENTES and len(falso.conversas) == 2
            assert "propôs de novo o passo que acabou de ser feito" in decisoes[-1][-1]["content"]
            assert bot_local.enviados[-1].startswith("✅ Feito no meuPlano: Fechar a OS 1638")


def test_os_modulos_do_bot_nao_repetem_nome():
    """Um `_ESTADO` novo (o estado da senha, na máscara do log) sobrescreveu o `_ESTADO` da assinatura, e "a OS 1638 já
    foi assinada?" voltaria a ser pedido de assinatura (avaliação 25 — a suíte pegou). Nome repetido no módulo: um some."""
    import ast
    import collections
    from pathlib import Path

    for arq in ("assistente.py", "assistente_helper.py", "assistente_geracao.py"):
        arvore = ast.parse((Path(__file__).parents[1] / "app" / "services" / arq).read_text())
        nomes = collections.Counter(
            alvo.id for n in arvore.body if isinstance(n, (ast.Assign, ast.AnnAssign))
            for alvo in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(alvo, ast.Name))
        nomes.update(n.name for n in arvore.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        assert not [k for k, v in nomes.items() if v > 1], arq


# ── avaliação 26: a senha pelo VALOR, a máscara que só esconde o valor, o fim pelo sinal, os sins que faltavam ─────


class _MeuPlanoQueRevela:
    """O assistente do meuPlano novo: a resposta e, junto, as senhas que o turno revelou (`segredos`)."""

    def __init__(self, *respostas):
        self.respostas, self.conversas = list(respostas), []

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        return len(self.conversas)

    async def assistente_run(self, token, run_id):
        return {"status": "DONE", **self.respostas[min(run_id, len(self.respostas)) - 1]}


def _ia_roteiro(monkeypatch, mp, roteiro, vistos=None):
    """A IA de mentira: cada mensagem da pessoa vira ("ferramenta", pergunta ao meuPlano) ou ("texto", resposta);
    `vistos` recebe o que a IA viu (as mensagens de cada chamada)."""
    import json as _json

    from app.services import vinculos

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        if vistos is not None:
            vistos.append(_json.dumps(msgs, ensure_ascii=False))
        if msgs[-1]["role"] == "tool":
            return {"content": _json.loads(msgs[-1]["content"]).get("texto") or "Certo."}
        tipo, valor = roteiro[msgs[-1]["content"]]
        if tipo == "texto":
            return {"content": valor}
        return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
            "name": "manutencao", "arguments": _json.dumps({"pergunta": valor})}}]}

    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    monkeypatch.setattr(assistente.asyncio, "sleep", _nada)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)


async def test_a_senha_que_o_meuplano_revelou_some_pelo_valor_e_a_conversa_fica_cifrada(db, bot_local, monkeypatch):
    """O turno que trata de acesso ("Como eu entro no SmartLogger…") deixa o texto livre fora do log e da cópia do
    gateway; no turno seguinte ("manda de novo só ela"), a senha que o meuPlano revelou — conhecida pelo VALOR — some de
    novo, e não volta à IA nem ao meuPlano no histórico (avaliação 27: voltava em claro e ficava gravada lá). A pessoa
    recebe tudo; a conversa guardada fica CIFRADA (o turno seguinte precisa dela)."""
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot

    resposta = "Acesse https://10.1.130.2 no navegador e entre com admin / changeme2."
    p1, p2 = "Como eu entro no SmartLogger 1 de Pirapozinho?", "Manda de novo só ela, pra eu copiar"
    mp, vistos = _MeuPlanoQueRevela({"type": "message", "text": resposta, "segredos": ["changeme2"]}), []
    _ia_roteiro(monkeypatch, mp, {p1: ("ferramenta", "Como entrar no SmartLogger 1 da UFV Pirapozinho?"),
                                  p2: ("texto", "changeme2")}, vistos)
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, p1))
    await assistente.atender(_ev(dono, 2, p2))
    assert bot_local.enviados == [resposta, "changeme2"]                     # a pessoa recebe inteira
    assert bot_local.guardados == [assistente.RESPOSTA_OMITIDA, "••••"]
    assert [r.resposta for r in db.query(RegistroBot).order_by(RegistroBot.id)] == [assistente.RESPOSTA_OMITIDA, "••••"]
    assert "changeme2" not in vistos[-1]                                     # a IA do 2º turno não a recebeu
    conv = db.query(ConversaWhatsapp).one()
    assert "changeme2" not in conv.mensagens and "changeme2" in _conversa_em_claro(db)
    assert assistente._ler_conversa(conv)[1] == ["changeme2"]


async def test_o_pedido_de_senha_fica_fora_do_log_com_ou_sem_a_lista_do_meuplano(db, bot_local, monkeypatch):
    """A senha de TEXTO LIVRE (wiki, OS, relato: "o cadeado abre com 3262") não vem na lista do meuPlano: a resposta ao
    pedido de acesso fica fora do log e da cópia do gateway com o meuPlano que manda a lista (vazia) e com o que não
    manda (avaliação 27: com a lista vazia ela ia ao log). A pergunta da pessoa fica, sem nada a esconder."""
    from app.models.conversa_whatsapp import RegistroBot

    for n, revela in enumerate(({"segredos": []}, {})):
        p = "Qual a senha do cadeado do portão de Pirapozinho?"
        _ia_roteiro(monkeypatch, _MeuPlanoQueRevela({"type": "message", **revela,
                                                     "text": "Pela wiki da UFV Pirapozinho, o cadeado abre com 3262."}),
                    {p: ("ferramenta", p)})
        dono = _conta(db, f"dono{n}", f"+551799737762{n}")
        await assistente.atender(_ev(dono, n + 1, p))                    # id novo: o repetido é ignorado
        linha = db.query(RegistroBot).filter_by(gs_user_id=dono.id).one()
        assert (linha.pergunta, linha.resposta) == (p, assistente.RESPOSTA_OMITIDA)
        assert bot_local.guardados[-1] == assistente.RESPOSTA_OMITIDA and "3262" in bot_local.enviados[-1]


async def test_a_senha_mandada_gravar_some_tambem_do_que_veio_antes_quando_a_proposta_nasce(db, bot_local, monkeypatch):
    """"grava aí: SL2…, usuário admin, changeme" — sem a palavra "senha" e só de letras, nenhuma regra a reconhece. O
    meuPlano pergunta o nível; com "L1", a proposta nasce com o valor: ele some do log de antes, do gateway (das 24 h do
    número) e da resposta — e a conversa guardada o mantém, cifrada, para o meuPlano gravar o certo."""
    from app.models.conversa_whatsapp import RegistroBot

    p1, p2 = "anota pro SmartLogger 2 de Pereiras: changeme", "L1"
    proposta = {"type": "proposal", "action": "cadastrar_acesso",
                "args": {"categoria": "Login Web", "rotulo": "Admin", "nivel": 1,
                         "campos": [{"chave": "usuario", "valor": "admin", "is_segredo": False},
                                    {"chave": "senha", "valor": "changeme", "is_segredo": True}]},
                "preview": {"summary": "Gravar acesso 'Admin' em 1 equipamento(s) de UFV Pereiras",
                            "lines": [{"text": "usuario: admin"}, {"text": "senha: ••••••"}], "warnings": []}}
    mp = _MeuPlanoQueRevela({"type": "message", "text": "Qual o nível do acesso (L1–L5)?", "segredos": []}, proposta,
                            proposta)
    _ia_roteiro(monkeypatch, mp, {p1: ("ferramenta", p1), p2: ("ferramenta", "O nível é L1."),
                                  "Não, é L2": ("ferramenta", "Refaça com o nível L2.")})
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, p1))
    assert "changeme" in db.query(RegistroBot).one().pergunta          # ainda não se sabe que é a senha
    await assistente.atender(_ev(dono, 2, p2))
    assert [r.pergunta for r in db.query(RegistroBot).order_by(RegistroBot.id)] == [
        "anota pro SmartLogger 2 de Pereiras: ••••", "L1"]
    assert bot_local.mascarados == [(dono.telefone, ["changeme"])]
    assert "changeme" in str(mp.conversas[-1])                         # o meuPlano recebeu a conversa inteira
    assert "admin" in db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().resposta  # o usuário não é senha
    # a correção depois da proposta: a senha DIGITADA continua indo ao meuPlano (a revelada, não — ele a tem)
    await assistente.atender(_ev(dono, 3, "Não, é L2"))
    assert "changeme" in str(mp.conversas[-1]) and "changeme" not in db.query(RegistroBot).order_by(
        RegistroBot.id.desc()).first().pergunta + str(bot_local.guardados)


def test_os_valores_da_proposta_de_acesso_sao_as_senhas():
    assert assistente._valores_secretos({"campos": [
        {"chave": "usuario", "valor": "admin"}, {"chave": "senha", "valor": "Solar#2026x", "is_segredo": True},
        {"chave": "Chave do Wi-Fi", "valor": "wifi1234"}, {"chave": "SSID", "valor": "rede-ufv"}]}) == [
        "Solar#2026x", "wifi1234"]
    assert assistente._valores_secretos({"os_id": 1638}) == [] and assistente._valores_secretos(None) == []
    assert assistente._sem_valores("PIN 123 na OS 1234; Huawei@123", ["123", "Huawei@123", "ab"]) == (
        "PIN •••• na OS 1234; ••••")
    assert assistente._sem_valores("a OS 12 e o 12", ["12"]) == "a OS 12 e o 12"    # curto demais para ser a senha


def test_o_texto_fixo_do_bot_nunca_e_mascarado():
    """Toda frase fixa dos módulos do bot que fala de senha sai do log como foi escrita (avaliação 26: a máscara comia a
    explicação do próprio bot)."""
    import ast
    import pathlib

    import app.services.assistente as modulo

    frases = set()
    for nome in ("assistente.py", "assistente_helper.py", "assistente_geracao.py"):
        arvore = ast.parse(pathlib.Path(modulo.__file__).with_name(nome).read_text())
        documentacao = {id(c.body[0].value) for c in ast.walk(arvore)              # a docstring não vai à pessoa
                        if isinstance(c, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and c.body and isinstance(c.body[0], ast.Expr)}
        for no in ast.walk(arvore):
            if (isinstance(no, ast.Constant) and isinstance(no.value, str) and len(no.value) > 20
                    and id(no) not in documentacao
                    and assistente._CREDENCIAL.search(no.value)
                    and not any(m in no.value for m in ("(?", "\\b", "\\s", "[^", "|", "{", "%s"))):
                frases.add(no.value)
    assert len(frases) >= 10
    for frase in sorted(frases):
        assert assistente._sem_segredos(frase) == frase, frase


def test_a_mascara_esconde_so_o_valor_e_deixa_a_prosa():
    """Avaliação 26: a máscara comia a linha inteira depois de "senha …:" (10 de 10 prosas) e deixava a senha de um
    pedido de gravar (6 de 8). Agora some só o VALOR — até a primeira palavra comum."""
    from app.services.assistente import _sem_segredos

    for texto, guardado in (
        ("salve a senha do Wi-Fi da UFV Porto Ferreira: rede-ufv / Solar#2026x",
         "salve a senha do Wi-Fi da UFV Porto Ferreira: •••• / ••••"),
        ("Salva o Wi-Fi de Porto Ferreira: rede-ufv / Solar#2026x", "Salva o Wi-Fi de Porto Ferreira: ••••"),
        ("troca a senha do cadeado do portão de Tietê: agora é Solar#2026x",
         "troca a senha do cadeado do portão de Tietê: agora é ••••"),
        ("troca a senha do cadeado do portão de Tietê: agora é changeme",
         "troca a senha do cadeado do portão de Tietê: agora é ••••"),
        ("A senha do SmartLogger é changeme para o usuário admin.", "A senha do SmartLogger é •••• para o usuário admin."),
        ("salve a senha do Wi-Fi: rede-ufv / changeme", "salve a senha do Wi-Fi: •••• / ••••"),
        ("a senha é 4821x e o usuário é admin", "a senha é •••• e o usuário é ••••"),
        ("| senha | Huawei@123 |", "| senha | •••• |"),
        ("Roteador — IP 192.168.1.1 · usuário admin · Solar#2026x", "Roteador — IP 192.168.1.1 · usuário admin · ••••"),
        ("Senha: X9y8z7. Kewyn tem acesso.", "Senha: ••••. Kewyn tem acesso."),     # o fim da frase fecha o valor
    ):
        assert _sem_segredos(texto) == guardado, texto
    for prosa in (
        "Antes eu falei de senha por engano — ação no meuPlano se confirma com SIM.",
        "Sobre a senha: o meuPlano não pede senha para criar OS.",
        "Senha: você não tem nível para ver; peça ao gerente da O&M.",
        "Senha do SmartLogger: acima do seu nível (L2) — peça a quem tem acesso.",
        "Senha do SmartLogger: consulte a ficha do equipamento no meuPlano.",
        "Credenciais: ficam no cofre do meuPlano, aba Acessos.",
        "PIN do cadeado: cadastre na ficha do equipamento.",
        "A senha do Wi-Fi: o cliente troca toda semana, confirme com ele.",
        "Senhas:\n- Wi-Fi: ninguém cadastrou\n- SmartLogger: só o admin vê",
        "Senha — fale com o Kewyn, ele tem acesso.",
        "O inversor SUN2000-100KTL da OS 1638 (INV-13) mandou o e-mail para renan@splendoroem.com.br às 14:32.",
        "Veja https://meuplano.solar/os/1638?aba=2&x=1 e R$1.500,00 do contrato #665.",
    ):
        assert _sem_segredos(prosa) == prosa, prosa


async def test_o_pedido_de_um_passo_feito_nao_ganha_segunda_mensagem(db, bot_local, monkeypatch):
    """"Feche a OS 1638" → Sim → ✅, e a IA vê que o pedido acabou: nenhuma 2ª mensagem, log verde, e o meuPlano nem é
    perguntado de novo (avaliação 28: o controle C3 da avaliação 27 recebia "não confirmou se o seu pedido terminou")."""
    from app.models.conversa_whatsapp import RegistroBot

    fechar = {"status": "DONE", "type": "proposal", "action": "fechar_os", "args": {"os_id": 1638},
              "preview": {"summary": "Fechar a OS 1638 (Roçagem)", "lines": [], "warnings": []}}

    class _MP(_MeuPlanoQueEscreve):
        async def assistente_run(self, token, run_id):
            return fechar if run_id == 1 else await super().assistente_run(token, run_id)

    falso = _MP("A OS 1638 foi fechada.")
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    _resto(monkeypatch, ("fim_do_pedido", {"situacao": "feito"}))
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie: feche a OS 1638"))
    antes = len(bot_local.enviados)
    await assistente.atender(_toque(dono, 2))
    assert len(bot_local.enviados) - antes == 1 and bot_local.enviados[-1].startswith("✅ Feito no meuPlano: Fechar")
    assert len(falso.conversas) == 1 and falso.aplicadas == ["fechar_os"]
    assert db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().resultado == "respondeu"


def test_os_sins_que_faltavam_e_as_recusas_que_nao_executam():
    from app.services import assistente_helper as h

    fechar = "Fechar a OS 1638 (Roçagem): as 1 tarefa(s) estão concluídas."
    for sim in ("Sim, 100%", "100%", "Procede", "Pode proceder", "Pode efetuar", "Pode realizar", "Pode dar andamento",
                "Ok, pode dar sequência", "Sim, pode encerrar", "Encerra", "Liberado", "Pode liberar", "Valido",
                "Sim, valido", "Sim, cem por cento"):
        assert h._resposta_ao_resumo(sim, fechar) == "sim", sim
    for nao in ("Pode fechar quando o Michel voltar", "Sim, mas não agora", "Fecha amanhã cedo", "Pode, só que não",
                "Sim kkk brincadeira", "Ok, pode desconsiderar", "Pode encerrar a 1640"):
        assert h._resposta_ao_resumo(nao, fechar) != "sim", nao


# ── avaliação 27: o assunto de acesso, o próximo passo que revela, o histórico que sai, o dado técnico ─────────────


async def test_o_pedido_de_gravar_senha_fraca_ja_sai_sem_ela_no_primeiro_turno(db, bot_local, monkeypatch):
    """"Salva o Wi-Fi de Porto Ferreira: rede-ufv / changeme" — o meuPlano pergunta o nível e a proposta só vem no turno
    seguinte (se a pessoa desiste, não vem nunca): a mensagem já vai ao log e ao gateway sem a senha, porque o turno
    trata de acesso (avaliação 27: ficava em claro até a proposta chegar). A conversa guardada a mantém, cifrada."""
    from app.models.conversa_whatsapp import RegistroBot

    p = "Salva o Wi-Fi de Porto Ferreira:\nrede-ufv / changeme"                 # o valor na linha de baixo
    _ia_roteiro(monkeypatch, _MeuPlanoQueRevela({"type": "message", "text": "Qual o nível do acesso (L1–L5)?",
                                                 "segredos": []}), {p: ("ferramenta", p)})
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, p))
    assert db.query(RegistroBot).one().pergunta == "Salva o Wi-Fi de Porto Ferreira:\nrede-ufv / ••••"
    assert bot_local.textos_ocultados == ["Salva o Wi-Fi de Porto Ferreira:\nrede-ufv / ••••"]  # a cópia do gateway
    assert "changeme" in _conversa_em_claro(db)


async def test_o_assunto_vem_da_pergunta_da_ia_ao_meuplano_ou_da_pessoa(db, bot_local, monkeypatch):
    """O turno trata de acesso pela pergunta que a IA fez ao meuPlano ("Cadastrar a senha do SmartLogger 2…", a pessoa
    escreveu só "anota: …"), ou pela da pessoa ("qual era mesmo a senha?", que a IA responde de memória, sem chamar o
    meuPlano): nos dois, o que a pessoa mandou fica na máscara do assunto e o texto livre fica fora do log."""
    from app.models.conversa_whatsapp import RegistroBot

    p1, p2 = "anota pro SmartLogger 2 de Pereiras:\nchangeme", "qual era mesmo a senha do SL1?"
    _ia_roteiro(monkeypatch, _MeuPlanoQueRevela({"type": "message", "text": "Qual o nível do acesso (L1–L5)?",
                                                 "segredos": []}),
                {p1: ("ferramenta", "Cadastrar a senha do SmartLogger 2 de Pereiras: changeme"), p2: ("texto", "ufvpira")})
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, p1))
    await assistente.atender(_ev(dono, 2, p2))
    linhas = db.query(RegistroBot).order_by(RegistroBot.id).all()
    assert linhas[0].pergunta == "anota pro SmartLogger 2 de Pereiras:\n••••"
    assert (linhas[1].pergunta, linhas[1].resposta) == (p2, assistente.RESPOSTA_OMITIDA)


async def test_a_senha_revelada_no_proximo_passo_some_e_o_texto_dele_fica_fora(db, bot_local, monkeypatch):
    """O PRÓXIMO PASSO do pedido também revela (e o meuPlano conta): a senha some do log e do gateway, e o texto que a IA
    escreveu a partir dele fica fora dos dois (avaliação 27: ignorava a lista)."""
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot

    falso = _MeuPlanoQueEscreve({"status": "DONE", "type": "message", "segredos": ["roteador99"],
                                 "text": "O acesso web do roteador continua: admin / roteador99"})
    _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
    _resto(monkeypatch, ("proximo_passo", {"passo": "Conferir o acesso do roteador"}),
           ("fim_do_pedido", {"situacao": "falta", "texto": "O roteador continua com admin / roteador99"}))
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, PEDIDO_DOIS_PASSOS))
    await assistente.atender(_toque(dono, 2))
    log = db.query(RegistroBot).order_by(RegistroBot.id.desc()).first()
    assert "roteador99" in bot_local.enviados[-1]                           # a pessoa recebe
    assert "roteador99" not in log.resposta and "roteador99" not in (log.erro or "")
    assert "roteador99" not in bot_local.guardados[-1] and "fora do log" in bot_local.guardados[-1]
    assert "roteador99" in assistente._ler_conversa(db.query(ConversaWhatsapp).one())[1]


async def test_a_senha_revelada_nao_volta_ao_meuplano_no_historico(db, bot_local, monkeypatch):
    """Lá o `/assistant/chat` gravava o histórico em `assistant_runs.messages_json` (avaliação 27): a senha que ELE
    revelou não volta no turno seguinte."""
    mp = _MeuPlanoQueRevela({"type": "message", "text": "• **Senha:** changeme", "segredos": ["changeme"]},
                            {"type": "message", "text": "O IP do SmartLogger 1 é 10.1.130.2.", "segredos": []})
    p1, p2 = "Qual a senha do SmartLogger 1 de Pirapozinho?", "E qual o IP dele?"
    _ia_roteiro(monkeypatch, mp, {p1: ("ferramenta", p1), p2: ("ferramenta", p2)})
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, p1))
    await assistente.atender(_ev(dono, 2, p2))
    enviado = __import__("json").dumps(mp.conversas[1], ensure_ascii=False)
    assert "changeme" not in enviado and "**Senha:** ••••" in enviado


def test_o_dado_tecnico_nao_some_e_a_senha_forte_some_em_qualquer_texto():
    """Letra, número e símbolo some em qualquer texto só com MINÚSCULA no meio — o dado técnico é maiúsculo ou de
    medida (avaliação 27: "S3=139,5", "PR=82,5%", "MPPT1+MPPT2", "2043@INV-13", "CB-03#2" sumiam da cópia guardada)."""
    for tecnico in ("Temperatura do TR-02: S3=139,5 °C às 10:30.", "PR=82,5% em setembro (PVsyst 84,1%).",
                    "Strings MPPT1+MPPT2 do INV-13 com 12 A cada.", "Q1+Q2=10 kW no ramal 3.",
                    "Produtividade: kWh/kWp=4,21 no dia.", "Alarme 2043@INV-13 desde 08:15.",
                    "A caixa CB-03#2 está sem leitura."):
        assert assistente._sem_segredos(tecnico) == tecnico, tecnico
    assert assistente._sem_segredos("ok, o acesso ficou Huawei@123") != "ok, o acesso ficou Huawei@123"
    assert assistente._sem_segredos("deixa anotado: P@ssw0rd") == "deixa anotado: ••••"


def test_na_linha_do_acesso_a_senha_fraca_some_de_qualquer_jeito():
    """A senha fraca de TEXTO LIVRE (avaliação 27: 68 de 99 formatos passavam) — na linha que trata de acesso, depois de
    qualquer separador, de uma palavra de enchimento ("é a X", "é sempre X") e sem a palavra "senha"."""
    for texto in ("O cadeado do portão de Pirapozinho abre com 3262.", "Wi-Fi da UFV Tietê: rede ufv-tiete / changeme",
                  "Para entrar no SmartLogger 1: usuário admin, changeme.", "A senha do Wi-Fi de Tietê é a changeme.",
                  "A senha do SmartLogger é sempre changeme.", "A senha do Wi-Fi continua changeme.",
                  "A senha do portão é ainda changeme, ninguém trocou.", "Senha: a de fábrica, changeme.",
                  "Conforme a OS 1721: o Wi-Fi do container é ufv-container e a chave é changeme.",
                  "No relato de 12/10 o Michel anotou: login admin / changeme",
                  "Acesse https://10.1.130.2 e entre com admin / changeme.",
                  "o login do roteador de Tietê é admin e a senha changeme",
                  "grava aí: SmartLogger 2 de Pereiras, usuário admin, changeme"):
        guardado = assistente._sem_segredos(texto)
        assert "changeme" not in guardado and "3262" not in guardado, guardado
    assert assistente._sem_segredos("Acesse https://10.1.130.2 e entre com admin / changeme.") == (
        "Acesse https://10.1.130.2 e entre com admin / ••••.")                 # o endereço fica
    assert assistente._sem_segredos("Acesse https://meuplano.solar/os/1638 e entre com admin / changeme.") == (
        "Acesse https://meuplano.solar/os/1638 e entre com admin / ••••.")
    assert assistente._sem_segredos("Conforme a OS 1721: a chave é changeme.") == "Conforme a OS 1721: a chave é ••••."


def test_os_sins_da_avaliacao_27():
    from app.services import assistente_helper as h

    fechar = "Fechar a OS 1638 (Roçagem): as 1 tarefa(s) estão concluídas."
    for sim in ("Executa", "Execute", "Lógico", "Excelente", "Perfeitamente", "Certamente"):
        assert h._resposta_ao_resumo(sim, fechar) == "sim", sim


# ── avaliação 28: o texto livre do meuPlano fora do log sem palavra-chave, o número com cara de segredo, a linha curta ──
LIVRES_28 = [  # (a pergunta da pessoa, a resposta do meuPlano em texto livre, o segredo): perguntas sem palavra de acesso
    ("Qual o código do portão de Tietê?", "Pela OS 1721, o portão de Tietê abre com 4455.", "4455"),
    ("Como eu abro o portão da UFV Tietê?", "Digite 4455 e # no teclado do portão.", "4455"),
    ("Qual a combinação do cofre de Ibitinga?", "A combinação é 12-34-56, conforme o relato do Michel.", "12-34-56"),
    ("Como acesso o SmartLogger de Pereiras?", "Pelo wiki: https://10.1.130.2, admin / Changeme1", "Changeme1"),
    ("Como acesso o SmartLogger de Pereiras?", "Entre em https://10.1.130.2 com o usuário admin e changeme.", "changeme"),
    ("Qual o token da API do datalogger de Tietê?", "O token anotado no wiki é 9f8e7d6c5b4a.", "9f8e7d6c5b4a"),
    ("Qual o código de liberação da guarita de Pirapozinho?", "É 7781, segundo a OS 1690.", "7781"),
    ("Como desarmo o alarme da cabine de Ibitinga?", "O alarme desarma com 2468 no painel da cabine.", "2468"),
    ("O que o Michel anotou na OS 1721?", "Anotou que trocou o roteador e que o novo é admin / ufvtiete.", "ufvtiete"),
    ("O que tem no wiki da UFV Tietê?", "O wiki diz: portão 4455, SmartLogger admin/girassol.", "girassol"),
]


async def test_o_texto_livre_do_meuplano_fica_fora_do_log_sem_depender_de_palavra(db, bot_local, monkeypatch):
    """O turno que passou pelo meuPlano deixa o texto livre dele fora do log e da cópia do gateway, com qualquer pergunta:
    a regra de palavras ("assunto de acesso") deixava 10 de 14 respostas com a senha em claro (avaliação 28), e a senha só
    de letras ("ufvtiete", "girassol") nenhuma forma acharia. A pessoa recebe a resposta inteira."""
    import json as _json

    from app.models.conversa_whatsapp import RegistroBot
    from app.services import vinculos

    class _MP:
        async def assistente_chat(self, token, mensagens):
            return 1

        async def assistente_run(self, token, run_id):
            return {"status": "DONE", "type": "message", "text": self.texto}

    async def _llm(msgs, ferramentas=None):                     # toda pergunta vai ao meuPlano
        return {"content": "", "tool_calls": [{"id": "m", "type": "function", "function": {
            "name": "manutencao", "arguments": _json.dumps({"pergunta": msgs[-1]["content"]})}}]}

    async def _nada(*a, **k):
        return None

    mp = _MP()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    monkeypatch.setattr(assistente.asyncio, "sleep", _nada)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    for n, (pergunta, resposta, segredo) in enumerate(LIVRES_28):
        mp.texto = resposta
        dono = _conta(db, f"dono{n}", f"+55179973772{n:02d}")
        await assistente.atender(_ev(dono, 100 + n, pergunta))
        log = db.query(RegistroBot).order_by(RegistroBot.id.desc()).first()
        assert segredo in bot_local.enviados[-1], n                                # a pessoa recebe
        assert log.resposta == assistente.RESPOSTA_OMITIDA and log.pergunta == pergunta, n
        assert bot_local.guardados[-1] == assistente.RESPOSTA_OMITIDA, n            # e a cópia do gateway também


def test_o_numero_com_cara_de_segredo_some_da_mensagem_da_pessoa():
    """O pedido de anotar ou trocar um código, escrito sem palavra de senha (avaliação 28: 7 de 9 ficavam em claro no log
    e no gateway): o número de 3 dígitos ou mais e a palavra com minúscula e número somem; o identificador, a data, a
    hora, a medida e o código de equipamento ficam."""
    from app.services.assistente import _sem_segredos, publicos_do_turno

    for texto, guardado in (
        ("o código novo do portão de Tietê é 4455, anota no wiki", "o código novo do portão de Tietê é ••••, anota no wiki"),
        ("anota aí: o portão de Tietê agora abre com 4455", "anota aí: o portão de Tietê agora abre com ••••"),
        ("troca o token do datalogger de Tietê para 9f8e7d6c5b4a", "troca o token do datalogger de Tietê para ••••"),
        ("o alarme da cabine de Ibitinga agora desarma com 2468, registra na OS 1721",
         "o alarme da cabine de Ibitinga agora desarma com ••••, registra na OS 1721"),
        ("a combinação do cofre mudou pra 12-34-56", "a combinação do cofre mudou pra ••••"),
        ("registra no relato: roteador novo de Tietê, admin / ufvtiete9", "registra no relato: roteador novo de Tietê, "
                                                                          "admin / ••••"),
        ("guarita de Pirapozinho: liberação 7781, põe no wiki", "guarita de Pirapozinho: liberação ••••, põe no wiki"),
        ("o usuário do SmartLogger 2 é instalador e a chave sungrow88", "o usuário do SmartLogger 2 é instalador e a "
                                                                        "chave ••••"),
        ("token=9f8e7d6c5b4a e admin/Huawei2024", "token=•••• e admin/••••"),
        ("a senha do inversor sungrow88", "a senha do inversor ••••"),          # o modelo pela marca, a senha não
    ):
        assert _sem_segredos(texto) == guardado, texto
    for tecnico in ("Feche a OS 1638 hoje às 14:30", "Inversor 13: 4821 W, PR 82,5%, 4,2kWh/kWp em 09/2026",
                    "S3=139,5 °C, MPPT1+MPPT2, 2043@INV-13, CB-03#2, SUN2000-100KTL", "código de erro 2043 no inversor 13",
                    "A usina tem 5670 módulos e gerou 12.345 kWh em 2025", "R$ 1.500,00 no contrato #657, a UC é 1234567",
                    "a troca custou R$ 1500 e a placa saiu por R$1800",
                    "Quais os parametros que o rele.pextron urp6000 tem", "o inversor sun2000-100ktl de Pereiras",
                    "helper 2.17.0, IP 10.1.130.2:502, dia 24/10/2026", "5 ruas em 2 horas, ele levou 2hr",
                    "Produtividade: kWh/kWp=4,21 no dia.", "CNPJ 60.096.696/0001-23", "[senha oculta] e [número oculto]"):
        assert _sem_segredos(tecnico) == tecnico, tecnico
    # o número que o próprio turno mostra como identificador fica ("1638 pode fechar" e o resumo "Fechar a OS 1638")
    assert _sem_segredos("1638 pode fechar") == "•••• pode fechar"
    assert _sem_segredos("1638 pode fechar", publicos=publicos_do_turno("📋 Fechar a OS 1638 (Roçagem)")) == "1638 pode fechar"


async def test_o_pedido_com_o_numero_da_os_fica_legivel_no_log(db, bot_local, monkeypatch):
    """"1638 pode fechar" (o uso real de 24/10) e o resumo "Fechar a OS 1638": o número é o da OS, e fica no log; o do
    portão, mandado junto, some."""
    from app.models.conversa_whatsapp import RegistroBot

    _ia_que_pede_ao_meuplano(monkeypatch, _MeuPlanoQueRepete({"os_id": 1638}), [])     # propõe "Fechar a OS 1638"
    dono = _conta(db, "dono", "+5517997377626")
    await assistente.atender(_ev(dono, 1, "crie: 1638 pode fechar, e o portão novo abre com 4455"))
    log = db.query(RegistroBot).order_by(RegistroBot.id.desc()).first()
    assert log.pergunta == "crie: 1638 pode fechar, e o portão novo abre com ••••"
    assert bot_local.textos_ocultados[-1] == log.pergunta and "4455" not in " ".join(bot_local.textos_ocultados)


def test_numa_conversa_de_acesso_so_a_linha_de_uma_palavra_e_o_valor():
    """Na mensagem que trata de acesso, a linha curta virava •••• sem segredo nenhum ("Pereiras também", "Michel avisou",
    "urgente": avaliação 28). Só a linha de UMA palavra fora das comuns é o valor ("changeme" sozinha)."""
    from app.services.assistente import _sem_segredos

    for texto in ("O Wi-Fi de Tietê caiu de novo\nPereiras também", "Qual a senha do SmartLogger de Ibitinga?\nurgente",
                  "o cadeado do portão de Pirapozinho quebrou\nMichel avisou", "Wi-Fi de Ouro Fino fora\nInversor 3 parado"):
        assert _sem_segredos(texto, credencial=True) == texto, texto
    assert _sem_segredos("a senha nova do Wi-Fi:\nchangeme", credencial=True) == "a senha nova do Wi-Fi:\n••••"
    assert _sem_segredos("changeme", credencial=True) == "••••"


async def test_a_copia_do_gateway_sai_sem_o_numero_ja_na_chegada(db, bot_local, monkeypatch):
    """O turno que para antes (número sem conta, mídia, atrasada) também guarda a mensagem sem o número com cara de
    segredo (avaliação 28): a cópia do gateway é refeita na chegada, não só no fim do turno."""
    await assistente.atender({"id": 7, "telefone": "+5511900000001", "wa_id": "9", "tipo": "text",
                              "texto": "o portão de Tietê abre com 4455"})
    assert bot_local.ocultadas == [7] and bot_local.textos_ocultados == ["o portão de Tietê abre com ••••"]


# ── 26/10/2026: VPN das usinas parada, 18 chamadas ao helper e "a pergunta ficou grande demais" ────────────────────
async def test_com_a_vpn_parada_o_helper_responde_na_hora_sem_ir_ao_equipamento(db, helper_com_get):
    from app.services import assistente_helper as h

    contato = {"idade": 250_000}

    async def _rede():
        contato["vezes"] = contato.get("vezes", 0) + 1
        return {"ok": True, "vpn_ultimo_contato_s": contato["idade"]}

    helper_com_get.rede = _rede
    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    r = await h.usina_helper(ctx, {"rota": "/api/healthcheck/run", "corpo": {"slug": "pirapozinho"}})
    assert r["motivo"] == "vpn_parada" and "VPN das usinas está sem contato desde" in r["erro"]
    assert "não tente outra rota" in r["erro"] and helper_com_get.chamadas == []           # nem foi ao helper
    await h.usina_helper(ctx, {"rota": "/api/healthcheck/run", "corpo": {"slug": "pirapozinho"}})
    assert contato["vezes"] == 1                                                             # 1 ida ao filtro por minuto
    await h.usina_helper(ctx, {"rota": "/api/registry/plants"})                              # o cadastro vale
    assert helper_com_get.chamadas == [("POST", "/api/registry/plants")]
    h._VPN, contato["idade"] = None, 30                                                      # a VPN no ar: segue
    await h.usina_helper(ctx, {"rota": "/api/devices", "metodo": "GET"})
    assert helper_com_get.chamadas[-1] == ("GET", "/api/devices")

    async def _fora():
        raise RuntimeError("filtro fora")

    h._VPN, helper_com_get.rede = None, _fora                                                # sem conferir: segue
    await h.usina_helper(ctx, {"rota": "/api/devices", "metodo": "GET"})
    assert len(helper_com_get.chamadas) == 3


async def test_quando_as_consultas_acabam_a_ia_responde_com_o_que_leu(db, monkeypatch):
    """Esgotadas as rodadas, uma última volta SEM ferramenta (`tool_choice="none"`) responde com o que a IA já leu; só
    se ela falhar vai a frase de sempre."""
    import json as _json

    vistos = []

    async def _llm(msgs, ferramentas=None, obrigatoria=False, nenhuma=False):
        vistos.append(nenhuma)
        if nenhuma:
            return {"content": "Não consegui ler os relés: a VPN das usinas está parada."}
        return {"content": "", "tool_calls": [{"id": f"c{len(vistos)}", "type": "function", "function": {
            "name": "usina_helper", "arguments": _json.dumps({"rota": "/api/healthcheck/run"})}}]}

    async def _helper(ctx, a):
        return {"erro": "A VPN das usinas está sem contato."}

    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setitem(assistente.FERRAMENTAS, "usina_helper", (_helper, assistente.FERRAMENTAS["usina_helper"][1]))
    monkeypatch.setattr(assistente, "permitidas", lambda user: ["usina_helper"])
    dono = _conta(db, "dono", "+5517997377626")
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    texto = await assistente.responder(ctx, [{"role": "user", "content": "status dos relés de Ouro Fino?"}])
    assert texto == "Não consegui ler os relés: a VPN das usinas está parada."
    assert vistos == [False] * assistente.MAX_RODADAS + [True]

    async def _quebra(msgs, ferramentas=None, obrigatoria=False, nenhuma=False):
        if nenhuma:
            raise RuntimeError("fora")
        return await _llm(msgs, ferramentas)

    monkeypatch.setattr(assistente, "_llm", _quebra)
    assert (await assistente.responder(ctx, [{"role": "user", "content": "e agora?"}])).startswith("A pergunta ficou")


async def test_leitura_recusada_traz_o_motivo_de_dentro_da_resposta(db, helper_com_get, monkeypatch):
    """26/10/2026: o bot mandou o NOME ("Relé Geral") como device_id; o helper respondeu
    "dispositivo desconhecido" dentro de `resposta`, e o bot disse "recusado sem motivo"."""
    from app.services import assistente_helper as h

    async def chamar(rota, corpo, origem, metodo="POST"):
        return {"ok": False, "tipo": "leitura", "status_http": 400,
                "resposta": {"ok": False, "error": "dispositivo desconhecido"}}

    monkeypatch.setattr(helper_com_get, "chamar", chamar)
    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    r = await h.usina_helper(ctx, {"rota": "/api/read", "corpo": {"plant_id": "pirapozinho", "device_id": "x"}})
    assert r["erro"] == "dispositivo desconhecido"


async def test_catalogo_de_drivers_mantem_as_leituras_e_o_detalhe_vem_pelo_id(db, helper_com_get, monkeypatch):
    """26/10/2026: o `/api/devices` (~34 mil caracteres) passava pelo corte e perdia `read_commands`;
    o bot chutou "status" e não leu as bandeirolas do relé (é "status_trips")."""
    from app.services import assistente_helper as h

    acao = {"id": "reset_bandeirolas", "label": "Reset", "args": [], "danger": "high", "texto": "x" * 3000}
    drivers = [{"id": f"d{i}", "label": f"D{i}", "notes": "n" * 2000, "actions": [acao],
                "read_commands": [{"id": "status_trips", "label": "Ler bandeirolas"}]} for i in range(15)]

    async def chamar(rota, corpo, origem, metodo="POST"):
        return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": drivers}

    monkeypatch.setattr(helper_com_get, "chamar", chamar)
    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    todos = await h.usina_helper(ctx, {"rota": "/api/devices", "metodo": "GET"})
    assert todos["resposta"][14]["leituras"] == {"status_trips": "Ler bandeirolas"}
    assert "reset_bandeirolas" in todos["resposta"][14]["acoes"]
    um = await h.usina_helper(ctx, {"rota": "/api/devices?id=d3", "metodo": "GET"})
    assert um["resposta"]["actions"][0]["danger"] == "high"



_CATALOGO = [{"id": "pextron_urp6000", "read_commands": [{"id": "telemetria"}, {"id": "status_trips"}],
              "actions": [{"id": "reset_bandeirolas"}]}]


@pytest.mark.portao
async def test_nunca_chutar_driver_leitura_ou_acao_fora_do_catalogo_nao_chega_ao_helper(db, helper_com_get, monkeypatch):
    """Regra do Renan (26/10/2026): NUNCA CHUTAR. O bot mandou o nome "Relé Geral" como driver e
    o comando "status" (é "status_trips"): o pedido nem sai, e o bot recebe o que existe."""
    from app.services import assistente_helper as h

    chamadas = []

    async def chamar(rota, corpo, origem, metodo="POST"):
        chamadas.append(rota)
        if rota == "/api/devices":
            return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": _CATALOGO}
        return {"ok": True, "tipo": "leitura", "status_http": 200, "resposta": {"ok": True}}

    monkeypatch.setattr(helper_com_get, "chamar", chamar)
    dono = _dono_com_usina(db)
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)
    base = {"plant_id": "pirapozinho", "host": "10.1.130.2", "port": 5020, "slave": 1}
    nome = await h.usina_helper(ctx, {"rota": "/api/read", "corpo": {**base, "device_id": "Relé Geral", "read_cmd": "telemetria"}})
    assert "não existe" in nome["erro"] and "pextron_urp6000" in nome["erro"]
    cmd = await h.usina_helper(ctx, {"rota": "/api/read", "corpo": {**base, "device_id": "pextron_urp6000", "read_cmd": "status"}})
    assert "status_trips" in cmd["erro"]
    acao = await h.usina_helper(ctx, {"rota": "/api/act", "corpo": {**base, "device_id": "pextron_urp6000", "action_id": "desligar"}})
    assert "reset_bandeirolas" in acao["erro"]
    assert chamadas == ["/api/devices"]                    # nenhum pedido chutado saiu
    ok = await h.usina_helper(ctx, {"rota": "/api/read", "corpo": {**base, "device_id": "pextron_urp6000", "read_cmd": "status_trips"}})
    assert ok["status_http"] == 200 and chamadas == ["/api/devices", "/api/read"]
