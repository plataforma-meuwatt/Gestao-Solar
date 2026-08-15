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
    pintar de vermelho a usina inteira toda noite é o alarme que faz o dono desinstalar.

    **Os DOIS lados são verificados aqui.** A primeira versão deste teste checava só
    `_situacao`, e por isso não pegou a divergência que existia: `_parados` contava o
    mesmo inversor como parada, e a tela da usina desenhava faixa vermelha "1 inversor
    parado" logo acima de um chip cinza "Fora da janela solar" — com o toque abrindo uma
    lista que contava zero. Três afirmações contraditórias sobre o mesmo aparelho, na
    mesma navegação. Um teste que exercita um lado só dá impressão de cobertura.
    """
    dormindo_com_parada_aberta = {"status": "bedtime", "down": True}

    tom, situacao = _situacao("bedtime", False, None, True)
    assert tom == "semDados"
    assert situacao == "Fora da janela solar"

    assert _em_falha(dormindo_com_parada_aberta) is False, "o outro lado tem de concordar"
    assert _parados([dormindo_com_parada_aberta]) == 0, "senão a faixa vermelha volta"


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


def test_codigo_de_falha_ativo_nao_sai_verde():
    """O caso mais perigoso, e o que passava: registrador de estado em `normal` com
    alarme do fabricante ou código de falha decodificado.

    O mw-fe considera três sinais — `status === 'alert'`, `alert_text` e `fault`. Lendo só
    o `status`, o inversor com código de falha ativo saía **verde "Gerando"** no card do
    equipamento E no card da usina, enquanto o meuWatt o mostrava em alerta no mesmo
    minuto.
    """
    tom, situacao = _situacao("normal", False, None, None, "Grid over-voltage", None)

    assert tom == "alerta"
    assert situacao == "Grid over-voltage", "o texto do fabricante diz mais que 'em alerta'"

    tom_codigo, situacao_codigo = _situacao("normal", False, None, None, None, 512)

    assert tom_codigo == "alerta"
    assert situacao_codigo == "Código de falha ativo"


def test_alerta_do_upstream_conta_no_rollup_da_usina():
    """A régua tem de ser a mesma nas duas telas: o que pinta o card do equipamento de
    âmbar precisa pintar o card da usina também."""
    from app.api.v1.plants import _em_alerta

    assert _em_alerta({"status": "alert"}) is True
    assert _em_alerta({"status": "normal", "alert_text": "Grid over-voltage"}) is True
    assert _em_alerta({"status": "normal", "fault": {"code": 512}}) is True
    assert _em_alerta({"status": "normal"}) is False
