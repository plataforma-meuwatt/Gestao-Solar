"""As duas telas que falam do mesmo inversor têm de dizer a mesma coisa.

Este arquivo não existia, e a ausência custou caro: `plants.py` e `equipamentos.py` são
módulos separados, cada um com seu mapa de estados, e por duas rodadas de auditoria eles
discordaram sobre o mesmo aparelho. O padrão que se produzia é o pior de todos — a tela da
usina desenhava a faixa vermelha **"1 inversor parado"**, o dono tocava, e caía numa lista
onde aquele mesmo inversor aparecia verde, "Gerando".

Corrigir num arquivo só é o erro que se repetiu. Os testes aqui comparam os dois lados
**diretamente**, para que a próxima divergência apareça em vermelho antes de chegar ao
aplicativo.
"""

from app.api.v1.equipamentos import TOM_POR_ESTADO, _situacao
from app.api.v1.plants import MUDO, PARADO, _em_falha, _parados


def test_falha_declarada_pinta_igual_nas_duas_telas():
    """O caso reproduzido pela auditoria: `status='normal'` com `down=True`.

    É um inversor com parada material aberta que o registrador Modbus ainda não reflete.
    `plants` contava como parado (certo) e `equipamentos` dizia "Gerando" (errado).
    """
    inversor = {"status": "normal", "down": True}

    assert _em_falha(inversor) is True
    assert _parados([inversor]) == 1

    tom, situacao = _situacao("normal", False, None, True)

    assert tom == "parado", "a lista de equipamentos tem de concordar com a faixa vermelha"
    assert situacao.startswith("Parado")


def test_detector_sem_sinal_cai_na_derivacao_pelo_status():
    """`down` é tri-estado: `None` é "o detector não sabe", e aí vale o `status`. Tratar
    nulo como falha encheria a tela de vermelho sempre que o detector atrasasse."""
    saudavel = {"status": "normal", "down": None}

    assert _em_falha(saudavel) is False

    tom, situacao = _situacao("normal", False, None, None)

    assert tom == "ok"
    assert situacao == "Gerando"


def test_dormindo_nao_vira_falha_nem_com_down():
    """De madrugada o detector pode manter uma parada aberta da tarde. `bedtime` vence:
    pintar de vermelho a usina inteira toda noite é o alarme que faz o dono desinstalar."""
    tom, situacao = _situacao("bedtime", False, None, True)

    assert tom == "semDados"
    assert situacao == "Fora da janela solar"


def test_silenciado_vence_tudo():
    """Ignorado é decisão de quem opera. Discutir com ela a cada leitura é ruído."""
    tom, situacao = _situacao("fault", True, 120, True)

    assert tom == "semDados"
    assert situacao == "Ignorado no monitoramento"


def test_os_dois_mapas_de_estado_concordam():
    """A régua de `plants` e a de `equipamentos` vivem em arquivos diferentes. Este teste
    existe para que continuem sendo a mesma régua."""
    for estado in PARADO:
        assert TOM_POR_ESTADO.get(estado) == "parado"

    assert TOM_POR_ESTADO.get(MUDO) == "semDados", "mudo é cinza, não vermelho"


def test_estado_desconhecido_nao_diz_gerando():
    """Estado novo do mw-api recebe cinza de "não sei". A frase tem de acompanhar: cinza
    com texto "Gerando" é o else otimista que o mapa promete evitar."""
    tom, situacao = _situacao("estado_que_nao_existe_ainda", False, None, None)

    assert tom == "semDados"
    assert situacao == "Estado desconhecido"
