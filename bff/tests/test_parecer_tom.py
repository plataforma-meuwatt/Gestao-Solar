"""A cor do parecer é escrita pelo servidor, não deduzida em cada tela.

O defeito que este teste impede de voltar apareceu na integração do portal (04/09/2026).
`TarefaOut` mandava só a FRASE do parecer ("Aprovado", "Aprovado com ressalva",
"Reprovado"), e três telas — Cronograma, OS e Relatórios — deduziam a cor do texto, cada
uma do seu jeito. As três discordavam, e a pior discordância era a da OS: o fallback dela
devolvia "ok". Quer dizer que um `SessionVerdict` novo, inventado no meuPlano, chegaria ao
cliente pintado de VERDE — dizendo "aprovado" sobre um veredito que ninguém tinha lido.

A régua agora mora em `TOM_DO_PARECER`, ao lado de `PARECER`, e vale para todo consumidor:
o portal, o aplicativo e o relatório (que reusa `_tarefa_out`). O que não está no mapa sai
SEM cor — a única resposta honesta.
"""

from app.api.v1.manutencao import PARECER, TOM_DO_PARECER, _tarefa_out


def _tarefa(verdict):
    return _tarefa_out({"id": 1, "name": "Ensaio", "status": "APROVADA", "verdict_status": verdict})


def test_cada_parecer_leva_a_sua_cor():
    assert _tarefa("APPROVED").parecer_tom == "ok"
    assert _tarefa("REJECTED").parecer_tom == "parado"


def test_ressalva_nao_e_aprovacao():
    """Cor própria, pela mesma razão que o cronograma se recusa a fundir feito com
    dispensado: quem lê "verde" para de ler o resto."""
    t = _tarefa("APPROVED_WITH_RESERVATION")
    assert t.parecer == "Aprovado com ressalva"
    assert t.parecer_tom == "alerta"
    assert t.parecer_tom != _tarefa("APPROVED").parecer_tom


def test_parecer_desconhecido_sai_sem_cor_e_nao_verde():
    """O caso que motivou a mudança: fallback verde é uma aprovação inventada."""
    t = _tarefa("ALGO_QUE_O_MEUPLANO_INVENTOU")
    assert t.parecer_tom is None
    assert t.parecer is None


def test_tarefa_sem_ficha_nao_tem_parecer_nem_cor():
    """Tarefa de serviço não tem veredito — forçar um seria inventar."""
    for vazio in (None, ""):
        t = _tarefa(vazio)
        assert t.parecer is None and t.parecer_tom is None


def test_os_dois_mapas_cobrem_exatamente_os_mesmos_vereditos():
    """Frase sem cor (ou cor sem frase) é como a divergência nasce."""
    assert set(PARECER) == set(TOM_DO_PARECER)


def test_as_cores_sao_do_vocabulario_de_seis_tons():
    assert set(TOM_DO_PARECER.values()) <= {"parado", "alerta", "multiplos", "tempoRuim", "ok", "semDados"}
