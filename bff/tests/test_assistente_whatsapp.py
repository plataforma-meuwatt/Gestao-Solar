"""O assistente do WhatsApp: quem é a pessoa, e o atalho da manutenção.

O Gestão Solar é o guardião: o número tem de casar com UMA conta daqui, ou não há conversa.
"""

import pytest

from app.models.user import Perfil, User, VinculoProduto
from app.services import assistente
from app.services import assistente_geracao as ger


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
    assert linhas[1].resposta == "*2 OS abertas*" and linhas[1].duracao_ms is not None
    conversa = db.query(ConversaWhatsapp).one()
    assert conversa.gs_user_id == dono.id and "segredo da outra conta" not in conversa.mensagens


# ── o helper pelo bot: ação só com CONFIRMO <código>, conferido pelo Gestão Solar ──────


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


async def test_a_os_que_o_meuplano_propoe_so_e_criada_com_a_senha_da_pessoa(db, monkeypatch):
    """O bot perguntava "Confirma que eu crie assim?" e, no "sim", mandava confirmar no site:
    a proposta de lá vira o mesmo CONFIRMO do helper, e a conversa vai junto ao meuPlano."""
    from app.services import assistente_helper as h
    from app.services import vinculos

    falso = _MeuPlanoFalso()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db, uid, so_proprio=False: falso)

    async def _sem_espera(_):
        return None

    monkeypatch.setattr(assistente.asyncio, "sleep", _sem_espera)
    h.PENDENTES.clear()
    from app.core.security import gerar_hash_senha

    dono = _conta(db, "dono", "+5517997377626")
    outro = _conta(db, "outro", "+5517997370000")
    for u in (dono, outro):
        u.senha_atuacao_hash = gerar_hash_senha("482913")
    db.commit()
    antes = [{"role": "user", "content": "Serviço novo"}, {"role": "assistant", "content": "Confirma que eu crie assim?"}]
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone, historico=antes)

    proposta = await assistente.manutencao(ctx, {"pergunta": "Sim, crie a OS"})
    assert falso.conversas[0][:2] == antes and falso.conversas[0][-1]["content"].startswith("Sim, crie a OS")
    assert "NADA foi executado" in proposta["instrucao"] and proposta["detalhes"] == ["Técnico: Michel"]
    assert falso.aplicadas == []
    h.mostrada(dono.id)

    assert "não há ação" in (await h.confirmar_por_mensagem(db, outro, outro.telefone, "482913")).lower()
    feito = await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913")
    assert feito.startswith("✅ Feito no meuPlano") and "(OS 1639, PROGRAMADA)" in feito
    assert falso.aplicadas == [("criar_ordem_servico", {"usina_id": 37, "nome": "Roçagem de 5 ruas"})]
    assert "não há ação" in (await h.confirmar_por_mensagem(db, dono, dono.telefone, "482913")).lower()


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

    from app.models.conversa_whatsapp import ConversaWhatsapp

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
    conversa = [m["content"] for m in __import__("json").loads(db.query(ConversaWhatsapp).one().mensagens)]
    assert conversa == ["Serviço novo", "resposta a Serviço novo", "amanhã ele volta", "resposta a amanhã ele volta"]


# ── avaliação de 24/10/2026: empresa desligada, meuWatt fora, a senha fora do log ──────


@pytest.fixture
def bot_local(db, monkeypatch):
    """O turno inteiro (`atender`) contra o banco de teste, com o gateway e a IA de mentira."""
    import types

    estado = types.SimpleNamespace(enviados=[], ocultadas=[], textos_ocultados=[], llm=[])

    async def _enviar(**k):
        estado.enviados.append(k.get("texto"))
        return {"ok": True}

    async def _ocultar(mid, texto=None):
        estado.ocultadas.append(mid)
        estado.textos_ocultados.append(texto)

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None):
        estado.llm.append(msgs[-1]["content"])
        return {"content": "resposta da IA"}

    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente.whatsapp, "digitando", _nada)
    monkeypatch.setattr(assistente.whatsapp, "ocultar_texto", _ocultar)
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
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
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
    conversa = db.query(ConversaWhatsapp).one().mensagens
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
    assert "TEMP-SKID-01 trd: 3 → 2 s — ✅ confirmado" in texto and "já estava" in texto
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
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
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
    assert "482913" not in db.query(ConversaWhatsapp).one().mensagens


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
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot

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
    assert "482913" not in db.query(ConversaWhatsapp).one().mensagens


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
    está — sem contar erro nem bloquear ninguém."""
    from app.models.conversa_whatsapp import ConversaWhatsapp
    from app.services import assistente_helper as h

    async def _nada(*a, **k):
        return None

    monkeypatch.setattr(ger, "preparar", _nada)
    dono = _dono_com_usina(db)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "a 482913"})
    await assistente.atender({"id": 2, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "a 482914"})
    assert bot_local.llm == [f"a {h.SENHA_OCULTA}", "a 482914"] and bot_local.ocultadas == [1]
    assert "Escondi a sua senha de atuação" in bot_local.enviados[0]
    assert "482913" not in db.query(ConversaWhatsapp).one().mensagens and dono.id not in h._ERROS


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
    assert (await h.alcancavel()) == (False, "Helper responde, mas a rede até as usinas (VPN) nunca fez contato.")
    assert (await h.alcancavel())[0] is False


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
    assert bot_local.enviados == [h.CANCELADO] and helper_com_get.confirmadas == [] and bot_local.ocultadas == [1]


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
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot

    dono = _dono_com_usina(db)
    await _armar(db, dono)
    await assistente.atender({"id": 1, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": "482 913"})
    assert helper_com_get.confirmadas == [("P-1", "pin")] and bot_local.llm == [] and bot_local.ocultadas == [1]
    for i, escrita in enumerate(("senha 482-913", "482,913", "482  913", "482_913"), start=2):
        await _armar(db, dono)
        await assistente.atender({"id": i, "telefone": dono.telefone, "wa_id": "1", "tipo": "text", "texto": escrita})
    assert len(helper_com_get.confirmadas) == 5
    assert all("913" not in (r.pergunta or "") for r in db.query(RegistroBot))
    assert "913" not in db.query(ConversaWhatsapp).one().mensagens


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
                  "ok:482913", "(482913)", "pode executar 482 913", "pode ir 482.913", "executa 4829-13",
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
    ]:
        assert _sem_segredos(texto) == guardado
    for texto in ["código de erro 2043 no inversor 3", "o código da OS 1639", "Senha não confere (2 de 5). Nada foi feito.",
                  h.ANTES_DO_RESUMO.format(limite="14:32"), "mande a senha de novo até as 14:32.",
                  "Para executar, responda só com a senha até as 14:32. Qualquer outra mensagem cancela.",
                  "🔒 *Ação esperando a sua senha de atuação*\n• Desligar o inversor 3", "[senha oculta]"]:
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
