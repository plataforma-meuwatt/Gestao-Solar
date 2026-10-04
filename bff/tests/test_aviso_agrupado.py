"""Um toque por USINA, não um por inversor.

Em 30/09/2026 o dono recebeu vinte notificações seguidas — uma por inversor parado de
Porto Ferreira — e comparou com o meuPlano, que mandou uma só: "20 inversores pararam".
Ele estava certo, e a régua replicada aqui é a de lá
(`meuPlano/backend/app/services/meuacesso/paradas_notify.py`).

Vinte toques pelo mesmo problema é o tipo de ruído que faz desligar a notificação — e aí
o alarme verdadeiro da semana seguinte não chega em ninguém. Cada teste abaixo diz, na
primeira linha, qual parte do desenho ele guarda.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.plant import PlantLink
from app.models.user import Perfil, User
from app.services.avisos import AvisoDeParada, _parados, texto_do_grupo


@pytest.fixture
def pf():
    return PlantLink(id=4, nome="Porto Ferreira", mw_plant_slug="porto-ferreira")


@pytest.fixture
def dono():
    return User(apelido="dono", nome="Dono", perfil=Perfil.CLIENTE)


def _aviso(dono, usina, nome, causa=None, motivo=None):
    return AvisoDeParada(
        usuario=dono, usina=usina, inversor=nome, equipamento_id=f"slot-{nome[-1]}",
        chave=f"{usina.id}:{nome}", causa=causa, motivo=motivo,
    )


def test_o_titulo_CONTA_quando_e_mais_de_um(db, dono, pf):
    """É o título que aparece na tela bloqueada, e é a diferença entre "um inversor" e
    "a usina inteira". Vinte títulos iguais não dizem nenhuma das duas."""
    um = texto_do_grupo([_aviso(dono, pf, "INV 1")])[0]
    vinte = texto_do_grupo([_aviso(dono, pf, f"INV {i}") for i in range(20)])[0]

    assert um == "Porto Ferreira · inversor parado"
    assert vinte == "Porto Ferreira: 20 inversores pararam"


def test_o_corpo_traz_a_CAUSA_quando_o_detector_a_tem(db, dono, pf):
    """É o que a pessoa procura antes de decidir se vai à usina. Sem causa, os nomes."""
    com_causa = [
        _aviso(dono, pf, "INV 1", causa="Falha de comunicação"),
        _aviso(dono, pf, "INV 2"),
    ]
    assert texto_do_grupo(com_causa)[1] == "Falha de comunicação."

    sem_causa = [_aviso(dono, pf, f"INV {i}") for i in range(1, 6)]
    # Três cabem na tarja da notificação; o resto vira contagem.
    assert texto_do_grupo(sem_causa)[1] == "INV 1, INV 2, INV 3 e outros 2."


def test_com_VARIOS_o_toque_abre_a_usina_e_nao_um_equipamento(db, dono, pf):
    """Uma tela de equipamento não responde "quais são os outros", que é a pergunta de
    quem acabou de ser avisado de que vinte pararam."""
    _, _, de_um = texto_do_grupo([_aviso(dono, pf, "INV 1")])
    _, _, de_varios = texto_do_grupo([_aviso(dono, pf, "INV 1"), _aviso(dono, pf, "INV 2")])

    assert de_um["equipamento_id"] == "slot-1"
    assert de_varios["equipamento_id"] == ""
    assert de_varios["usina_id"] == 4
    assert de_varios["quantidade"] == 2


def test_a_micro_usina_agrupa_por_ESTACAO(db, dono):
    """O portal do fabricante reporta estação, não inversor — e não tem `slot-N`."""
    micro = PlantLink(id=9, nome="Matioli", mw_micro_plant_id=6)
    uma = texto_do_grupo([_aviso(dono, micro, "Matioli", motivo="equipamento fora")])
    tres = texto_do_grupo([_aviso(dono, micro, f"Estação {i}") for i in range(3)])

    assert uma[0] == "Matioli · parada"
    assert "equipamento fora" in uma[1]
    assert tres[0] == "Matioli: 3 estações pararam"
    assert "inversor" not in tres[0].lower()


def test_a_rota_manda_UM_push_por_usina_e_trava_por_PARADA(db):
    """O agrupamento é só da ENTREGA. A memória continua tendo uma linha por parada: um
    sexto inversor que cair depois gera aviso novo, e os cinco já avisados não voltam
    nele. Trocar a trava por "uma por usina" calaria o sexto."""
    from pathlib import Path

    fonte = Path(__file__).resolve().parents[1].joinpath("app", "api", "v1", "avisos.py")
    corpo = fonte.read_text("utf-8")

    assert "por_pessoa_e_usina" in corpo, "o agrupamento por usina sumiu"
    assert "texto_do_grupo(grupo)" in corpo, "voltou a montar o texto de um aviso só"
    assert "for aviso in grupo:\n            db.add(AvisoEnviado(" in corpo, (
        "a trava deixou de ser por parada"
    )
    assert "for aviso in lista:" not in corpo, "voltou o laço que mandava um push por inversor"


def test_parada_VELHA_nao_vira_enxurrada_no_primeiro_laco(db):
    """Ao ligar o aviso, a carteira pode ter paradas abertas há semanas. Despejá-las todas
    na primeira volta é notícia velha às três da manhã — e foi parte dos vinte toques."""
    agora = datetime.now(UTC)
    nova = (agora - timedelta(hours=2)).isoformat()  # já persistiu, e é de hoje
    velha = (agora - timedelta(days=30)).isoformat()

    monitoramento = {
        "inverters": [
            {"id": "slot-1", "name": "Nova", "down": True, "down_since": nova},
            {"id": "slot-2", "name": "Velha", "down": True, "down_since": velha},
        ]
    }
    assert {i["name"] for i in _parados(monitoramento)} == {"Nova"}


def test_a_causa_vai_em_PORTUGUES_nunca_o_codigo_do_detector(db):
    """Defeito que o dono leu no celular em 30/09/2026: o corpo da notificação de Porto
    Ferreira era `zero_active_power`. Código de banco na tela é o que a regra da casa
    proíbe, e a tradução mora no BFF — uma vez, para todas as telas.

    Código desconhecido devolve `None` de propósito: quem chama cai nos nomes dos
    inversores. Imprimir o código cru "porque é melhor que nada" é o próprio defeito.
    """
    from app.services.vocabulario_mw import causa_em_portugues

    assert causa_em_portugues("zero_active_power") == "Potência zero durante o dia"
    assert causa_em_portugues("COMMUNICATION_FAILURE") == "Falha de comunicação"
    assert causa_em_portugues("never_woke_up") == "Não acordou pela manhã"
    assert causa_em_portugues("codigo_que_o_meuwatt_criar_amanha") is None
    assert causa_em_portugues(None) is None


def test_causa_desconhecida_cai_nos_NOMES_e_nao_no_codigo(db, dono, pf):
    """O corpo tem de dizer algo útil sempre — e o código cru não é útil."""
    grupo = [_aviso(dono, pf, "INV 1", causa=None), _aviso(dono, pf, "INV 2", causa=None)]
    corpo = texto_do_grupo(grupo)[1]
    assert corpo == "INV 1, INV 2."
    assert "_" not in corpo, "código do detector vazou para o corpo"


def test_parada_de_MINUTOS_nao_vira_aviso(db):
    """Alarme falso, relatado em 04/10/2026: o dono recebeu "Pirapozinho: 8 inversores
    pararam" e a equipe em campo respondeu que não houve parada.

    Os dois tinham razão. O detector do meuWatt registrou MESMO as paradas, e as duas
    levas daquele dia foram:

    | leva  | duração     | perda por inversor |
    |-------|-------------|--------------------|
    | 10:41 | 32 a 38 min | 20 a 26 kWh        |
    | 11:38 | 7 a 16 min  | 0,01 a 0,10 kWh    |

    A segunda é oscilação: quando a equipe abriu a tela, já tinha voltado sozinha. O aviso
    saía dez minutos depois do início, sem saber se aquilo ia durar sete minutos ou três
    horas. Agora espera `PERSISTENCIA_MINUTOS` — a primeira leva ainda avisa (uma volta
    depois), a segunda não avisa nenhuma vez.
    """
    agora = datetime.now(UTC)

    def inv(nome, minutos=None, **extra):
        d = {"id": f"slot-{nome}", "name": nome, "down": True, **extra}
        if minutos is not None:
            d["down_since"] = (agora - timedelta(minutes=minutos)).isoformat()
        return d

    monitoramento = {
        "inverters": [
            inv("oscilacao", 7),       # a leva das 11:38
            inv("limite", 19),         # ainda não
            inv("parada real", 36),    # a leva das 10:41
            inv("velha", 60 * 24 * 4),  # fora da janela de 72 h
            inv("sem data"),           # não dá para afirmar que persistiu
        ]
    }
    assert {i["name"] for i in _parados(monitoramento)} == {"parada real"}


def test_o_corpo_diz_DESDE_QUANDO(db, dono, pf):
    """Sem a hora, a equipe abre a tela, vê o estado de AGORA — que pode já ter voltado —
    e conclui que o aviso estava errado. Foi o que aconteceu em 04/10/2026."""
    um = _aviso(dono, pf, "Inv 34")
    um.desde = "07:33"
    assert texto_do_grupo([um])[1] == (
        "Inv 34 parou de gerar desde 07:33. Toque para ver o equipamento."
    )

    varios = [_aviso(dono, pf, f"Inv {i}", causa="Não acordou pela manhã") for i in range(2)]
    varios[0].desde = "07:41"
    assert texto_do_grupo(varios)[1] == "Não acordou pela manhã desde 07:41."

    # Sem a hora o aviso ainda sai — só não inventa um horário.
    sem_hora = [_aviso(dono, pf, f"Inv {i}", causa="Falha de comunicação") for i in range(2)]
    assert texto_do_grupo(sem_hora)[1] == "Falha de comunicação."


def test_a_hora_de_brasilia_tem_UMA_fonte(db):
    """Morava privada em `services/motor.py`, e o aviso por push precisava dela: duas
    cópias discordariam no primeiro fuso que alguém mexesse."""
    from pathlib import Path

    from app.core.datas import hora_brt

    assert hora_brt("2026-10-04T11:41:00Z").endswith(":41")
    assert hora_brt(None) == "—"
    assert hora_brt("não é data") == "—"

    motor = Path(__file__).resolve().parents[1].joinpath("app", "services", "motor.py")
    assert "def _hora_brt" not in motor.read_text("utf-8"), "a cópia voltou"
