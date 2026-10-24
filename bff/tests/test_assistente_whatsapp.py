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


async def test_gerente_poe_celular_e_libera_o_bot_sem_repetir_numero(db):
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
    # o helper ainda não tem ferramenta no bot: liberar é recusado, com o motivo (auditoria
    # de 23/10/2026 — a caixa ligada prometia uma ação que não acontecia)
    with pytest.raises(HTTPException) as e:
        await editar_conta_da_empresa(cli.id, ContaPatch(bot_helper=True, bot_meuwatt=True), db, gerente)
    assert e.value.status_code == 400 and "helper" in e.value.detail
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
