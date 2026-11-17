"""O medidor de tokens do bot (o dono, 17/11/2026: "Quero que você instale um medidor de tokens e deixe isso para o
gestor … dados por dia, mês e tudo"): cada mensagem grava o gasto de IA no log, e o gestor vê por dia, mês e pessoa."""

from datetime import UTC, date, datetime

from app.api.v1.painel_whatsapp import uso_do_bot
from app.models.conversa_whatsapp import RegistroBot
from app.models.empresa import Empresa
from app.models.user import Perfil, User
from app.services import assistente


def test_cada_chamada_soma_e_o_log_grava(db):
    u = User(apelido="ana", nome="Ana", perfil=Perfil.CLIENTE, telefone="+5517990000001")
    db.add(u)
    db.commit()
    assistente._USO.set({"chamadas": 0, "entrada": 0, "cache": 0, "saida": 0})
    assistente._somar_uso({"prompt_tokens": 1000, "completion_tokens": 50, "prompt_cache_hit_tokens": 800})  # DeepSeek
    assistente._somar_uso({"prompt_tokens": 2000, "completion_tokens": 70,                                   # a ponte
                           "prompt_tokens_details": {"cached_tokens": 1500}})
    assistente._registrar(db, u.telefone, u, "respondeu", pergunta="oi", resposta="olá")
    r = db.query(RegistroBot).one()
    assert (r.chamadas_ia, r.tokens_entrada, r.tokens_cache, r.tokens_saida) == (2, 3000, 2300, 120)
    assistente._USO.set(None)                                # fora de uma mensagem (script, avaliador): não mede
    assistente._somar_uso({"prompt_tokens": 9})
    assistente._registrar(db, u.telefone, u, "respondeu", pergunta="x", resposta="y")
    assert db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().tokens_entrada is None


def _linha(db, quem, em, entrada, saida, cache=0, empresa_id=None):
    db.add(RegistroBot(telefone=quem.telefone, gs_user_id=quem.id, empresa_id=empresa_id or quem.empresa_id,
                       resultado="respondeu", em=em, chamadas_ia=2, tokens_entrada=entrada, tokens_cache=cache,
                       tokens_saida=saida))


def test_por_dia_mes_e_pessoa_no_fuso_de_brasilia(db):
    a, b = Empresa(nome="Splendor"), Empresa(nome="Outra")
    db.add_all([a, b])
    db.commit()
    ana = User(apelido="ana", nome="Ana", perfil=Perfil.CLIENTE, telefone="+5517990000001", empresa_id=a.id)
    bia = User(apelido="bia", nome="Bia", perfil=Perfil.CLIENTE, telefone="+5517990000002", empresa_id=a.id)
    ze = User(apelido="ze", nome="Zé", perfil=Perfil.CLIENTE, telefone="+5517990000003", empresa_id=b.id)
    db.add_all([ana, bia, ze])
    db.commit()
    _linha(db, ana, datetime(2026, 10, 31, 12, 0, tzinfo=UTC), 1000, 100, cache=600)
    _linha(db, ana, datetime(2026, 11, 1, 2, 30, tzinfo=UTC), 500, 50)     # 23:30 de 31/10 em Brasília
    _linha(db, bia, datetime(2026, 11, 17, 15, 0, tzinfo=UTC), 3000, 300)
    _linha(db, ze, datetime(2026, 11, 17, 15, 0, tzinfo=UTC), 99999, 9999)  # outra empresa: não entra
    db.add(RegistroBot(telefone=ana.telefone, gs_user_id=ana.id, empresa_id=a.id, resultado="respondeu",
                       em=datetime(2026, 11, 2, 12, 0, tzinfo=UTC)))       # de antes do medidor: não conta
    db.commit()
    u = uso_do_bot(db, empresa_id=a.id, de=date(2026, 10, 1), ate=date(2026, 11, 30))
    assert (u.total.mensagens, u.total.entrada, u.total.saida, u.total.total) == (3, 4500, 450, 4950)
    assert [(d.chave, d.rotulo, d.total) for d in u.por_dia] == [("2026-10-31", "31/10", 1650), ("2026-11-17", "17/11", 3300)]
    assert [(m.rotulo, m.mensagens, m.total) for m in u.por_mes] == [("out/2026", 2, 1650), ("nov/2026", 1, 3300)]
    assert [(p.rotulo, p.total) for p in u.por_pessoa] == [("Bia (bia)", 3300), ("Ana (ana)", 1650)]
    assert u.por_dia[0].cache == 600 and u.medido_desde is not None
    so_nov = uso_do_bot(db, empresa_id=a.id, de=date(2026, 11, 1), ate=date(2026, 11, 30))
    assert so_nov.total.mensagens == 1                                      # a das 23:30 de 31/10 fica em outubro
    tudo = uso_do_bot(db, de=date(2026, 10, 1), ate=date(2026, 11, 30))    # o adm-gs: todas as empresas
    assert tudo.total.mensagens == 4
