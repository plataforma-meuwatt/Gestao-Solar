"""O vocabulário do meuWatt, em português — traduzido UMA vez, aqui.

Regra da casa: **rótulo que o cliente lê é dado da API**, e código de banco não vai à
tela. O detector de paradas do meuWatt classifica a causa com um código
(`zero_active_power`), e ele vazou direto para a notificação em 30/09/2026: o dono
recebeu "Porto Ferreira: 20 inversores pararam / zero_active_power" no celular.

As frases são as mesmas que o próprio meuWatt usa nas telas dele
(`mw-fe/src/services/generationCalcLive.ts` e `src/pages/ShadowBreakdownsPage.tsx`),
escritas por extenso: quem lê aqui é o dono da usina, não quem opera o monitoramento, e
"POTÊNCIA ZERO" sozinho não diz que isso aconteceu em pleno dia.

**Código desconhecido não vira texto.** `causa_em_portugues` devolve `None`, e quem chama
usa o que tem de melhor — os nomes dos inversores, no caso do aviso. Imprimir o código cru
"porque é melhor que nada" é exatamente o defeito que este módulo existe para fechar.
"""

#: As quatro causas que o detector do meuWatt produz hoje.
CAUSA_DA_PARADA: dict[str, str] = {
    "zero_active_power": "Potência zero durante o dia",
    "communication_failure": "Falha de comunicação",
    "never_woke_up": "Não acordou pela manhã",
    # O par usina+coletor sem nenhum registro em plena luz do dia. A explicação entre
    # parênteses é do meuWatt e importa: não é o inversor que parou, é o buraco no dado.
    "no_data": "Sem dados (usina e coletor sem energia)",
}


def causa_em_portugues(codigo: str | None) -> str | None:
    """A frase, ou `None` quando o código é desconhecido — nunca o código cru."""
    if not codigo:
        return None
    return CAUSA_DA_PARADA.get(str(codigo).strip().lower())
