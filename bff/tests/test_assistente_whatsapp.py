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

    estado = types.SimpleNamespace(enviados=[], ocultadas=[], textos_ocultados=[], llm=[], tipos=[], botoes=[])

    async def _enviar(**k):
        estado.enviados.append(k.get("texto"))
        estado.tipos.append((k.get("tipo"), [b["titulo"] for b in k.get("botoes") or []]))
        estado.botoes.append([b["id"] for b in k.get("botoes") or []])
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
    from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
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
        ("senha 482 - 913 ok", "senha •••• ok"),                  # separador com espaço (avaliação 12)
        ("a senha é: 482 / 913", "a senha é: ••••"),
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
    from time import monotonic

    from app.services import assistente_helper as h

    _ia_que_desliga(monkeypatch)
    dono = _dono_com_usina(db)
    for n, senha in ((1, "482913"), (3, "111222")):
        await assistente.atender(_ev(dono, n, "desliga o inversor 13"))
        h.PENDENTES[dono.id].expira = monotonic() - 1
        await assistente.atender(_ev(dono, n + 1, senha))
        assert "venceu" in bot_local.enviados[-1] and dono.id not in h.PENDENTES
    assert bot_local.enviados[-1] == bot_local.enviados[-3]
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
                   "*482913*", "482913?", "４８２９１３", "quatro oito dois nove um três"]:
        assert h.digitos_da_senha(so_ela) == "482913", so_ela
    for nao in ["24/10/2026", "2026-10-24", "10.1.130.2", "12, 13, 14", "123456", "111111", "2026"]:
        assert h.digitos_da_senha(nao) is None, nao
    for frase in ["a senha é quatro oito dois nove um três", "pode ir 4 8 2 9 1 3", "minha senha 482/913 ok",
                  "vai 482 913 ok", "tenta ４８２９１３ aí"]:
        h._CONFERENCIAS.clear()
        visto = h.mascarar(frase, await h.analisar(dono, frase))
        assert "482913" not in re.sub(r"\D", "", visto) and "quatro" not in visto, (frase, visto)


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
    assert feito.startswith("PDF da OS 1639 assinado") and pedidos == ["PDF da OS 1639\n\n(Resposta para WhatsApp: curta, sem tabela.)"]
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
                "Confirmar", "pode confirmar", "Aprovado", "De acordo", "tá certo", "Pode lançar", "Sim, pode abrir"):
        assert h.e_sim(sim), sim
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
                   "assina a OS pra mim", "Já está assinada? Se não, assine", "Assinada?"):
        assert assistente._pede_assinatura(pedido), pedido
    for leitura in ("Foi assinada?", "Quem assinou a OS?", "As OS de ontem estão assinadas?", "Quais OS faltam assinar?",
                    "Qual o status da assinatura da OS 1638?"):
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
    assert aviso == (f"⚠️ Não consegui pedir ao meuPlano o resto do seu pedido «{PEDIDO_DOIS_PASSOS}»: O modelo "
                     "não respondeu. O resto não foi feito — confira e peça de novo o que faltar.")
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
        self.aplicadas, self.conversas = [], []

    async def assistente_chat(self, token, mensagens):
        self.conversas.append(mensagens)
        return len(self.conversas)

    async def assistente_run(self, token, run_id):
        if run_id > len(self.args_por_vez):
            return {"status": "DONE", "type": "message", "text": "Pronto."}
        args = self.args_por_vez[run_id - 1]
        return {"status": "DONE", "type": "proposal", "action": self.acao, "args": dict(args),
                "preview": {"summary": self.resumo.format(**args), "lines": [], "warnings": []}}

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
    assert bot_local.enviados[-1] == h.DE_NOVO.format(resumo="Criar OS em UFV Ibitinga com 1 tarefa(s)",
                                                       limite=h._limite(h.PENDENTES[dono.id]))
    assert bot_local.botoes[-1] == [f"sim:{codigo}", f"nao:{codigo}"]               # os do MESMO resumo
    # só a resposta CURTA é dúvida; a longa é outro assunto (derruba e vai à IA) — perguntar de novo
    # engoliria o pedido
    resumo = h._texto_da_acao(h.PENDENTES[dono.id])
    assert [h._resposta_ao_resumo(t, resumo) for t in ("Sim, pode deixar", "Ok, pode deixar comigo",
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


async def test_o_passo_seguinte_que_repete_o_que_acabou_de_ser_feito_nao_e_oferecido(db, bot_local, monkeypatch):
    """Num pedido de vários passos, nada impedia o meuPlano de repropor a MESMA ação que acabou de ser feita
    — e o próximo Sim a faria duas vezes. Mesma ação e mesmos argumentos: é o fim do pedido. Outros
    argumentos são outro passo."""
    from app.services import assistente_helper as h

    for i, (segundo, oferecido) in enumerate((({"os_id": 1638}, False), ({"os_id": 1640}, True)), start=1):
        h.PENDENTES.clear()
        falso = _MeuPlanoQueRepete({"os_id": 1638}, segundo)
        _ia_que_pede_ao_meuplano(monkeypatch, falso, [])
        dono = _conta(db, f"dono{i}", f"+551799737000{i}")
        await assistente.atender(_ev(dono, 10 * i, "crie: feche a 1638"))
        await assistente.atender(_toque(dono, 10 * i + 1))
        assert falso.aplicadas == [("fechar_os", {"os_id": 1638})] and len(falso.conversas) == 2   # perguntou
        if oferecido:
            assert h.PENDENTES[dono.id].resumo == "Fechar a OS 1640 (Roçagem)"
        else:
            assert dono.id not in h.PENDENTES
            assert bot_local.enviados[-1].startswith("✅ Feito no meuPlano: Fechar a OS 1638")
