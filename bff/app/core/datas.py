"""Que dia é hoje — para uma usina no Brasil.

O contêiner roda em UTC (não há `TZ` no Dockerfile, e não deve haver: servidor com fuso
local é fonte de bug pior). Mas as usinas ficam todas no Brasil, e o mw-api é explícito
sobre isso: *"Todas as plantas operam no fuso America/Sao_Paulo (BRT, UTC-3, sem horário
de verão)"* (`src/shared/timezone.py`).

Com `date.today()`, entre 21h e meia-noite de Brasília o servidor já virou o dia e passa a
pedir o relatório de **amanhã**. O `/generation/daily` não tem guarda de data futura:
sintetiza o relatório inteiro com zeros. O aplicativo então mostrava, três horas por noite,
todas as noites, **"hoje 0,0 kWh · disponibilidade 0%" em todas as usinas** — e o BFF não
tinha como distinguir esse zero fabricado de uma usina que de fato não gerou.

A ironia que confirma o descuido: `home._saudacao` já fazia o deslocamento de três horas
na mão, para não dizer "bom dia" às 21h. Quem escreveu sabia do fuso e não o levou para as
consultas.

O mesmo vale para vencimento de mensalidade: uma fatura virava "vencida" três horas antes
da hora, e a tela dizia "vencida há 0 dias".
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _fuso() -> timezone | ZoneInfo:
    """O fuso das usinas, com uma rede de proteção.

    `ZoneInfo` depende da base IANA, que não existe no Windows nem numa imagem `slim` sem
    o pacote `tzdata`. Sem a proteção abaixo, o BFF **não sobe** — e falharia no import,
    derrubando o serviço inteiro por causa de um fuso.

    O recuo é UTC-3 fixo, e é seguro: o próprio mw-api documenta o fuso das plantas como
    *"BRT, UTC-3, sem horário de verão"*, e o Brasil não o adota desde 2019. Se voltar a
    adotar, a base IANA — que é a via preferida — passa a valer sozinha.
    """
    try:
        return ZoneInfo("America/Sao_Paulo")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3), name="BRT")


#: O fuso das usinas. Igual ao do mw-api, de propósito — se um dia divergirem, é aqui que
#: se muda, e não em onze lugares.
BRT = _fuso()


def hoje() -> date:
    """O dia corrente na usina, não no servidor."""
    return datetime.now(BRT).date()


def agora() -> datetime:
    """O instante corrente no fuso da usina."""
    return datetime.now(BRT)
