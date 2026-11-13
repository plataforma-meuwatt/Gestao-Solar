"""A MATRIZ de diagnóstico: o código (função ANSI do relé ou a condição da usina) → o que é, as causas prováveis em ordem,
o que o sistema confere sozinho, o que fazer e se dá para religar de longe.

Pedido do dono (13/11/2026, Pirapozinho: 47 às 22:48, 27 nas três fases às 03:17, oito inversores dos TR-01/TR-02 sem
ligar até o trip ser limpo às 07:34): "cria uma matriz … trip 27, 59 … você sabe muito mais que eu". É a fonte única:
a varredura de rotina (`diagnostico.py`), o bot e a página de revisão leem daqui. Texto para quem opera, não para
engenheiro de proteção: frase curta, a ação primeiro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    codigo: str
    nome: str
    o_que_e: str
    #: Em ordem de probabilidade numa usina solar em MT.
    causas: tuple[str, ...]
    #: O que a varredura confere sozinha (meuWatt e helper) antes de avisar.
    confere: tuple[str, ...]
    fazer: tuple[str, ...]
    #: "critica" (não religar sem inspeção) · "alta" (geração parada, religar depois de conferir) · "media" · "info"
    gravidade: str
    #: Religar de longe (helper, com a senha de atuação) é seguro depois do `confere`? Nunca para curto e falta à terra.
    religar_remoto: bool = False
    #: Outros códigos que caem neste item (como os relés escrevem: "27A", "27/59 PhA", "51G").
    apelidos: tuple[str, ...] = field(default_factory=tuple)


_NAO_RELIGAR = "Não religar de longe: precisa de inspeção em campo antes."

MATRIZ: dict[str, Item] = {i.codigo: i for i in (
    # ── tensão e frequência: quase sempre a REDE ────────────────────────────────────────────────────────────
    Item("27", "Subtensão", "A tensão caiu abaixo do ajuste e o relé abriu o disjuntor do skid ou da usina.",
         ("Queda ou afundamento da rede da concessionária (as três fases e vários relés no mesmo minuto; de madrugada "
          "é típico de manobra da distribuidora).",
          "Falta de uma fase na rede (só uma fase baixa, a 47 costuma vir junto).",
          "Fusível do TP de medição queimado (uma fase perto de zero com o skid gerando: é a MEDIÇÃO, não a rede).",
          "Ajuste do relé sensível demais (dispara com oscilação comum)."),
         ("Se os outros relés dispararam no mesmo minuto (rede) ou só este (local).",
          "A tensão das três fases no relé geral e no do skid agora.",
          "Se os inversores do skid estão parados ou não ligaram."),
         ("Com as três fases normais no relé geral, rearmar o relé do skid (helper, com a senha, ou em campo).",
          "Se repetir no mesmo dia: chamado na concessionária com os horários dos disparos.",
          "Se for uma fase só e o skid gera: trocar o fusível do TP de medição."),
         "alta", religar_remoto=True, apelidos=("27A", "27B", "27C", "27-1", "27-2", "27/59")),
    Item("59", "Sobretensão", "A tensão passou do ajuste e o relé abriu o disjuntor.",
         ("Rede alta no ponto de conexão (fim de linha, pouca carga, muita geração no meio do dia).",
          "Tap do transformador alto para a tensão de hoje da rede.",
          "Ajuste do relé apertado."),
         ("O horário (no pico de geração é a própria usina elevando a tensão).",
          "A tensão das três fases no relé geral.", "Se repete todo dia."),
         ("Rearmar quando a tensão voltar ao normal.",
          "Recorrente no pico: pedir à concessionária o estudo de tensão; avaliar com a engenharia o tap do trafo e o "
          "fator de potência dos inversores."),
         "alta", religar_remoto=True, apelidos=("59A", "59B", "59C", "59-1", "59-2")),
    Item("59N", "Sobretensão de neutro (residual)", "Apareceu tensão de neutro: sinal de falta à terra na média tensão.",
         ("Falta à terra em cabo, mufla, terminação ou para-raios.", "Umidade ou isolador trincado."),
         ("Se outros relés viram o mesmo evento.", "A tensão de neutro agora."),
         (_NAO_RELIGAR, "Inspecionar terminações, muflas e para-raios; teste de isolamento (megômetro) do cabo de MT."),
         "critica", apelidos=("64", "59G", "59Vo")),
    Item("47", "Sequência de fase / desequilíbrio de tensão",
         "As fases ficaram desequilibradas ou fora de ordem; costuma vir antes da 27.",
         ("Falta de uma fase ou fase baixa na rede da concessionária.", "Manobra na rede.",
          "Fusível do TP de medição queimado."),
         ("A tensão de cada fase no relé geral e no do skid.", "Se veio 27 depois."),
         ("Com as três fases equilibradas, rearmar.", "Fase faltando na rede: chamado na concessionária.",
          "Fase zerada só na medição: fusível do TP."),
         "alta", religar_remoto=True, apelidos=("46V", "47N")),
    Item("81", "Frequência (sub ou sobre)", "A frequência da rede saiu da faixa e o relé desligou.",
         ("Rede instável ou ilhamento (a usina ficou sozinha num trecho desligado da rede).",
          "Religamento automático da concessionária."),
         ("Se todos os relés dispararam juntos.", "A frequência agora."),
         ("Rearmar quando a rede estiver estável.", "Recorrente: registrar os horários e acionar a concessionária."),
         "alta", religar_remoto=True, apelidos=("81U", "81O", "81L", "81H")),
    Item("81R", "Taxa de variação de frequência (anti-ilhamento)", "Proteção anti-ilhamento: a rede saiu.",
         ("Desligamento ou religamento da rede da concessionária.",),
         ("Se o relé geral também viu.",),
         ("Rearmar com a rede estável.",), "alta", religar_remoto=True, apelidos=("78", "dfdt", "ROCOF")),
    # ── corrente: falta na instalação, NUNCA religar de longe ─────────────────────────────────────────────────
    Item("50", "Sobrecorrente instantânea de fase", "Corrente muito alta de repente: curto-circuito.",
         ("Curto em cabo, mufla ou terminação de MT.", "Falha interna do transformador.", "Animal ou objeto na cabine."),
         ("As correntes registradas no disparo.", "Se o relé geral também atuou."),
         (_NAO_RELIGAR, "Inspeção visual da cabine e do trafo; teste de isolamento antes de religar."),
         "critica", apelidos=("50P", "50A", "50B", "50C")),
    Item("51", "Sobrecorrente temporizada de fase", "Corrente acima do ajuste por tempo: sobrecarga ou falta.",
         ("Falta de alta impedância em cabo ou trafo.", "Sobrecarga (raro em usina, a geração é limitada).",
          "Ajuste errado."),
         ("A corrente antes do disparo e o carregamento do skid.",),
         (_NAO_RELIGAR, "Inspeção e teste de isolamento; conferir o ajuste do relé."),
         "critica", apelidos=("51P", "51A", "51B", "51C", "50/51")),
    Item("51N", "Sobrecorrente de neutro / terra", "Corrente indo para a terra: falta à terra.",
         ("Falta à terra em cabo, mufla ou para-raios.", "Umidade na cabine ou no cabo.", "Isolação do trafo."),
         ("A corrente de neutro no disparo.",),
         (_NAO_RELIGAR, "Teste de isolamento (megômetro) do cabo e do trafo; inspecionar muflas e para-raios."),
         "critica", apelidos=("50N", "51G", "50G", "51GS", "50/51N")),
    Item("67", "Direcional de sobrecorrente", "Falta com corrente no sentido protegido.",
         ("Falta na instalação da usina ou na rede, conforme o sentido ajustado.",),
         ("Se o relé geral também atuou.",), (_NAO_RELIGAR, "Inspeção e teste de isolamento."),
         "critica", apelidos=("67N", "67P")),
    Item("32", "Potência reversa / direcional de potência",
         "O fluxo de potência saiu do permitido (a usina consumindo da rede, ou exportando além do contratado).",
         ("Inversores desligados à noite consumindo dos trafos (normal, pequeno).", "Limitação de exportação mal "
          "ajustada.", "Ajuste do relé."),
         ("A potência no relé geral e o limite de exportação dos inversores.",),
         ("Conferir a limitação de exportação; ajustar o relé se for falso.",), "media", religar_remoto=True),
    Item("46", "Desequilíbrio de corrente", "As correntes das fases ficaram desiguais.",
         ("Falta de fase.", "Inversor ou fusível de uma fase fora."),
         ("As correntes de cada fase no relé.",), ("Achar a fase fraca (inversores, fusíveis) antes de religar.",),
         "media", apelidos=("46I",)),
    Item("49", "Sobrecarga térmica", "Aquecimento por corrente alta por muito tempo.",
         ("Carregamento alto do trafo.", "Ventilação da cabine ruim."),
         ("A corrente e a temperatura do trafo (sondas do EP4).",),
         ("Conferir ventiladores e limpeza; reduzir carga se precisar.",), "media", religar_remoto=True),
    Item("26", "Temperatura do transformador",
         "O termômetro do trafo (sondas S1–S3) passou do alarme ou do desligamento.",
         ("Ventilador parado ou com defeito.", "Filtro ou cabine suja.", "Dia quente com o trafo carregado."),
         ("As temperaturas S1–S3 e o estado dos ventiladores (EP4, pelo helper).",),
         ("Conferir os ventiladores e limpar; religar só abaixo do alarme.",), "alta", religar_remoto=False,
         apelidos=("49T", "38", "TEMP")),
    Item("63", "Buchholz / pressão / nível de óleo", "Proteção interna do trafo a óleo atuou: possível falha interna.",
         ("Falha interna do transformador (gás, arco).", "Nível de óleo baixo."),
         ("Se houve disparo de corrente junto.",),
         (_NAO_RELIGAR, "Chamar a manutenção do trafo (análise do óleo e do gás)."),
         "critica", apelidos=("71", "63P", "BUCHHOLZ")),
    Item("86", "Bloqueio", "O relé de bloqueio atuou depois de uma proteção grave e trava o religamento.",
         ("Disparo anterior de 50/51/51N/63.",),
         ("Qual função causou o bloqueio.",),
         (_NAO_RELIGAR, "Achar a função original; o reset do 86 é local e consciente."), "critica"),
    Item("50BF", "Falha de disjuntor", "O disjuntor recebeu a ordem de abrir e não abriu.",
         ("Mecanismo do disjuntor travado.", "Bobina de abertura queimada.", "Falta de tensão de comando (bateria)."),
         ("A tensão da bateria/retificador da cabine.",),
         (_NAO_RELIGAR, "Manutenção do disjuntor e do circuito de comando."), "critica", apelidos=("BF",)),
    # ── condições da usina (não são função ANSI) ────────────────────────────────────────────────────────────
    Item("NAO_LIGOU", "Inversores não ligaram no dia", "Com sol, inversores que não começaram a produzir.",
         ("Skid desarmado por trip na madrugada (ver os trips do relé do skid).",
          "Falta de tensão no AC do inversor (disjuntor de BT aberto).",
          "Isolação baixa de manhã (orvalho): o inversor espera secar e liga mais tarde.",
          "Inversor em falha.", "Só sem comunicação (gera, mas o dado não chega)."),
         ("Os trips do relé do skid nas últimas 12 h.", "O disjuntor de BT do skid (helper).",
          "A isolação e os alarmes do inversor (diagnóstico do meuWatt)."),
         ("Trip no skid: seguir a linha da função que disparou.",
          "Sem trip e com o disjuntor ligado: teste de comunicação do inversor (helper) e os alarmes dele.",
          "Isolação baixa sozinha às 6–8h: aguardar; se passar das 10h, inspecionar strings."),
         "alta"),
    Item("RELE_SEM_COMUNICACAO", "Relé sem comunicação",
         "O meuWatt não lê o relé: o estado dele é DESCONHECIDO (pode estar desarmado sem ninguém saber).",
         ("Rede/VPN até a usina.", "Gateway ou conversor do relé travado.", "Relé desligado."),
         ("A VPN e o teste de comunicação do helper.", "Se os inversores do skid estão gerando."),
         ("Teste de comunicação pelo helper; se o skid não gera, ir a campo.",), "media"),
    Item("FASE_ZERO_MEDICAO", "Uma fase zerada só na medição",
         "O relé mostra uma fase perto de zero com as outras normais e o skid gerando: é a medição (TP), não a rede.",
         ("Fusível do TP de medição queimado.", "Cabo ou borne do TP solto."),
         ("A potência do skid (se gera normal, a fase existe).",),
         ("Trocar o fusível do TP na próxima ida a campo.",
          "Risco: com a fase faltando na medição o relé pode disparar 27/47 falso."),
         "media"),
)}

_INDICE = {re.sub(r"[^0-9A-Z]", "", a.upper()): i.codigo for i in MATRIZ.values() for a in (i.codigo, *i.apelidos)}


def do_codigo(funcao: str | None) -> Item | None:
    """O item da matriz para a função como o relé a escreve ("27A", "27/59 PhB", "51G", "50/51N"), ou None."""
    t = re.sub(r"[^0-9A-Z]", "", (funcao or "").upper().replace("PH", ""))
    if not t:
        return None
    if t in _INDICE:
        return MATRIZ[_INDICE[t]]
    for n in range(len(t), 1, -1):                          # o prefixo mais longo que é código: "2759A" → "2759" → "27"
        if t[:n] in _INDICE:
            return MATRIZ[_INDICE[t[:n]]]
    return None
