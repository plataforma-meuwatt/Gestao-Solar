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


def _conta(db, apelido, telefone, ativo=True, bot=True):
    u = User(apelido=apelido, email=f"{apelido}@x.com", nome=apelido.title(), perfil=Perfil.CLIENTE,
             telefone=telefone, ativo=ativo, bot_meuplano=bot, bot_meuwatt=bot)
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


async def test_acao_do_helper_so_roda_com_o_codigo_da_propria_pessoa(db, helper_ligado):
    from app.services import assistente_helper as h

    dono = _conta(db, "dono", "+5517997377626")
    outro = _conta(db, "outro", "+5517997370000")
    for u in (dono, outro):
        u.bot_helper = True
    db.commit()
    assert {"usina_helper", "usina_helper_catalogo"} <= set(assistente.permitidas(dono))
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone)

    # Leitura passa direto; ação NÃO roda — vira código.
    assert (await h.usina_helper(ctx, {"rota": "/api/registry/plants"}))["status_http"] == 200
    proposta = await h.usina_helper(ctx, {"rota": "/api/act", "corpo": {"acao": "off"}})
    assert "NADA foi executado" in proposta["instrucao"] and helper_ligado.confirmadas == []
    codigo = proposta["codigo"]

    # Outra pessoa, com o mesmo código, não executa a ação de ninguém.
    assert "Não há ação" in await h.confirmar_por_mensagem(db, outro, outro.telefone, f"CONFIRMO {codigo}")
    errado = "0000" if codigo != "0000" else "1111"
    assert "não confere" in await h.confirmar_por_mensagem(db, dono, dono.telefone, f"confirmo {errado}")
    assert helper_ligado.confirmadas == []
    # O código certo, da própria pessoa: executa UMA vez.
    assert (await h.confirmar_por_mensagem(db, dono, dono.telefone, f"CONFIRMO {codigo}")).startswith("✅")
    assert helper_ligado.confirmadas == [("P-1", "codigo_whatsapp")]
    assert "Não há ação" in await h.confirmar_por_mensagem(db, dono, dono.telefone, f"CONFIRMO {codigo}")
    # Mensagem comum não é confirmação.
    assert await h.confirmar_por_mensagem(db, dono, dono.telefone, "qual a geração de hoje?") is None


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
        return {"ok": True, "message": "Ação aplicada."}


async def test_a_os_que_o_meuplano_propoe_so_e_criada_com_o_codigo_da_pessoa(db, monkeypatch):
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
    dono = _conta(db, "dono", "+5517997377626")
    outro = _conta(db, "outro", "+5517997370000")
    antes = [{"role": "user", "content": "Serviço novo"}, {"role": "assistant", "content": "Confirma que eu crie assim?"}]
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone, historico=antes)

    proposta = await assistente.manutencao(ctx, {"pergunta": "Sim, crie a OS"})
    assert falso.conversas[0][:2] == antes and falso.conversas[0][-1]["content"].startswith("Sim, crie a OS")
    assert "NADA foi executado" in proposta["instrucao"] and proposta["detalhes"] == ["Técnico: Michel"]
    assert falso.aplicadas == []

    codigo = proposta["codigo"]
    assert "Não há ação" in await h.confirmar_por_mensagem(db, outro, outro.telefone, f"CONFIRMO {codigo}")
    assert (await h.confirmar_por_mensagem(db, dono, dono.telefone, f"CONFIRMO {codigo}")).startswith("✅ Feito no meuPlano")
    assert falso.aplicadas == [("criar_ordem_servico", {"usina_id": 37, "nome": "Roçagem de 5 ruas"})]
    assert "Não há ação" in await h.confirmar_por_mensagem(db, dono, dono.telefone, f"CONFIRMO {codigo}")


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
