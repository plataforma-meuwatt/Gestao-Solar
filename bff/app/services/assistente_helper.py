"""O helper pelo assistente do WhatsApp — atuar na usina (pedido do dono, 23/10/2026).

O helper (mw-modbus-helper) fala com os equipamentos da usina e faz pelo bot o que a web
faz, como a pessoa — identidade = o token do meuWatt DELA (regra: cada um com o SEU token).

**Ação nunca é executada pela IA, e só roda com a SENHA DE ATUAÇÃO da pessoa** (pedido do
dono, 24/10/2026: "o bot peça senha para qualquer ação que envolva atuação — desligar,
ligar, gravar; ler não precisa"). Leitura volta na hora. Escrita volta do helper como
PROPOSTA (nada rodou) e fica esperando aqui; quando a pessoa manda a senha dela — conferida
por este código, antes de qualquer modelo, contra `User.senha_atuacao_hash` — o Gestão
Solar chama `confirmar` com `confirmado_por="pin"` (o contrato do helper: quem pede a senha
é o chamador). O modelo não vê a senha nem tem ferramenta de confirmar; `assistente._atender`
tira a mensagem do log, do histórico e do gateway.

O mesmo `propor` serve à proposta do assistente do meuPlano (criar OS, lançar o dia…):
`assistente.manutencao` guarda o `/assistant/apply` de lá — e ela se confirma com SIM (os botões
Sim / Não), não com a senha: senha é para equipamento (dono, 24/10/2026).
"""
from __future__ import annotations

import asyncio
import re
import secrets
import unicodedata
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

from app.clients.helper_bot import HelperBot
from app.core.config import get_settings
from app.core.datas import BRT, hora_brt
from app.core.security import conferir_senha
from app.services import assistente_geracao as ger

#: Como a senha (6 a 8 dígitos) chega escrita — numa mensagem só dela ou no meio de uma frase:
#: - em grupos separados por espaço(s), inclusive o não separável, ou por UMA pontuação colada:
#:   "482 913", "482.913", "482/913", "4829-13", "48 29 13" ("vírgula + espaço" separa ITENS de
#:   uma lista, "as UCs 1234, 5678", e não grupos de um número);
#: - dígito a dígito, com qualquer separador curto — o ditado por voz: "4 8 2 9 1 3",
#:   "4, 8, 2, 9, 1, 3";
#: - por extenso, ou misturado com dígitos: "quatro oito dois nove um três", "quatro 8 dois 9 um 3";
#: - com parênteses: "(482) 913" (avaliação 20).
#: Data (24/10/2026, 2026-10-24) e IP nunca são a senha e ficam como estão.
_GRUPOS = r"\d+(?:(?:\s{1,2}|,|\s?[._\-/–—()]\s?)\d+)*"
_SOLETRADO = r"\d(?:(?:\s|[.,_\-/–—]){1,3}\d(?!\d)){5,7}"
_DIGITO_POR_EXTENSO = {"zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "três": "3",
                       "quatro": "4", "cinco": "5", "seis": "6", "meia": "6", "sete": "7", "oito": "8", "nove": "9"}
_PALAVRA_DIGITO = r"\b(?:" + "|".join(sorted(_DIGITO_POR_EXTENSO, key=len, reverse=True)) + r")\b"
_UM_DIGITO = rf"(?:{_PALAVRA_DIGITO}|\d(?!\d))"
_POR_EXTENSO = _UM_DIGITO + r"(?:[\s,.\-]+" + _UM_DIGITO + r"){5,7}"
#: Um número, na ordem de preferência: soletrado, por extenso, em grupos.
NUMERO = re.compile(rf"{_SOLETRADO}|{_POR_EXTENSO}|{_GRUPOS}", re.IGNORECASE)
#: A mensagem INTEIRA é a senha: o número, com ou sem "senha"/"confirmo"/"pin" e pontuação na
#: frente ("Senha:482913", "senha/482913", "*482913*", "482913?").
PURA = re.compile(r"^\s*[*_~\"'“”«»]*\s*(?:(?:confirmo|senha|pin)\s*)?[:=,./\-–—#(]?\s*[\"'“”«»]?\s*(.+?)"
                  r"\s*[\"'“”«»]?\s*[.!?*_~)]*\s*$", re.IGNORECASE | re.DOTALL)
COM_PALAVRA = re.compile(r"^\s*(?:confirmo|senha|pin)\b", re.IGNORECASE)
#: "senha", "confirmo", "pin" e o que vem até o número (o número logo depois é conferido PRIMEIRO).
PALAVRA = re.compile(r"(?i)\b(?:senha|confirmo|pin)\b[^\d\n]{0,20}?(?=\d|" + _PALAVRA_DIGITO + ")")
_DATA = re.compile(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](?:\d{2}|\d{4}))?")
_DATA_ISO = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_IP = re.compile(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})")


def _so_digitos(trecho: str) -> str:
    """Os dígitos de um número escrito de qualquer jeito (grupos, soletrado, por extenso, misturado)."""
    return "".join(_DIGITO_POR_EXTENSO.get(t.lower(), t)
                   for t in re.findall(r"\d|" + _PALAVRA_DIGITO, trecho, re.IGNORECASE))


def _data_ou_ip(trecho: str) -> bool:
    trecho = re.sub(r"\s+", "", trecho)                 # "24 / 10 / 2026" é a mesma data
    data = _DATA.fullmatch(trecho)
    if data and 1 <= int(data[1]) <= 31 and 1 <= int(data[2]) <= 12:
        return True
    ip = _IP.fullmatch(trecho)
    return bool(_DATA_ISO.fullmatch(trecho) or (ip and all(int(x) <= 255 for x in ip.groups())))


def _nao_e_senha(trecho: str, digitos: str) -> bool:
    """Data, IP, ou o que a senha não pode ser (`validar_senha_atuacao`: 6 a 8 números, sem
    repetir nem seguir em sequência) — nem é conferido."""
    if _data_ou_ip(trecho) or not 6 <= len(digitos) <= 8:
        return True
    return {int(b) - int(a) for a, b in zip(digitos, digitos[1:])} in ({0}, {1}, {-1})


#: O enfeite dos dígitos de emoji ("4️⃣" é o 4, U+FE0F e U+20E3).
_TECLA = ("\ufe0f", "\u20e3")


def _digitos_normais(texto: str) -> str:
    """Dígitos de outra escrita (os de largura cheia, "４８２９１３") viram os comuns, e o enfeite dos de
    emoji ("4️⃣8️⃣2️⃣…", avaliação 21) vira espaço — um caractere por um: as posições não mudam, e o que
    se esconde no texto original é o mesmo trecho."""
    return "".join(" " if c in _TECLA else str(unicodedata.decimal(c)) if c.isdecimal() and not c.isascii() else c
                   for c in texto or "")
#: O que a IA, o histórico, o log e o gateway veem no lugar da senha escrita numa frase.
SENHA_OCULTA = "[senha oculta]"
#: …e no lugar de todo candidato quando a pessoa passou do limite de conferências por hora.
OCULTO = "[número oculto]"
#: Conferências de números em frase por pessoa e por hora: o que separa "esconder só a senha"
#: (UC, protocolo e IP continuam legíveis) de um oráculo — mandar números numa frase até a
#: resposta mudar. Passou disso, todo candidato é escondido, sem conferir.
CONFERENCIAS_POR_HORA = 20
#: Números conferidos por mensagem: cada conferência custa ~0,45 s (pbkdf2, 600 mil voltas).
#: Os que passam disso são escondidos sem conferir ("[número oculto]") — o 4º número de uma
#: frase podia ser a senha e ia em claro (avaliação 10).
MAX_CONFERIDOS = 3
#: O que fica no log, no histórico e no gateway no lugar da senha digitada.
OCULTA = "[senha de atuação]"
TENTATIVAS = 5
BLOQUEIO_S = 15 * 60
TETO_RESPOSTA = 12000
SEM_SENHA = ("Você ainda não tem senha de atuação. Sem ela o bot não comanda equipamento pelo helper "
             "(ligar, desligar, gravar). Peça ao gerente da sua O&M para definir no oem-gs (Bot do WhatsApp). "
             "Nada foi feito.")
#: A MESMA frase para a senha certa e para a errada, sem ação esperando: senão, mandar números
#: até a frase mudar descobriria a senha.
NADA_ESPERANDO = ("Não há ação esperando senha (o pedido vale poucos minutos). Nada foi feito. Se era "
                  "outra coisa, escreva com palavras.")
BLOQUEADO = "Ações bloqueadas por senha errada por 15 minutos. Nada foi feito."
#: O que vai ao pé da resposta quando uma mensagem que não era só a senha derrubou a ação.
ACAO_CANCELADA = ("(A ação que esperava a sua senha foi cancelada. Para executar uma ação, mande só a "
                  "senha, sem outras palavras.)")
ACAO_CANCELADA_SIM = "(A ação que esperava a sua confirmação foi cancelada. Se ainda quiser, peça de novo.)"
PARTE_DESLIGADA = "Essa parte do bot foi desligada pelo gerente da O&M enquanto a ação esperava. Nada foi feito."
CANCELADO = "Cancelado: a ação não será executada. Nada foi feito."
#: O cancelamento de um passo depois de outros já feitos: "Nada foi feito" escondia a OS que o
#: passo anterior criou (avaliação 15). Vem seguido do que já foi feito (`assistente._o_que_ficou`).
CANCELADO_PASSO = "Cancelado: este passo não será executado."
#: A senha certa que a pessoa mandou ANTES de o resumo chegar: ela não sabia o que confirmava.
ANTES_DO_RESUMO_SIM = ("Esse \"sim\" foi mandado antes de o resumo da ação chegar, então não vale. Leia o resumo "
                       "acima e, se for isso mesmo, responda SIM de novo até as {limite}. Nada foi feito.")
#: A senha (certa ou errada — a mesma frase, sem oráculo) depois do prazo da ação.
VENCEU = ("A ação esperava a sua resposta até as {limite} e venceu, então não vale mais. Nada foi feito. Se "
          "ainda quiser, peça de novo.")
ANTES_DO_RESUMO = ("Essa senha foi mandada antes de o resumo da ação chegar, então não vale. Leia o resumo "
                   "acima e, se for isso mesmo, mande a senha outra vez até as {limite}. Nada foi feito.")


@dataclass
class Pendente:
    resumo: str
    expira: float
    #: Executa a ação confirmada — (db, conta, telefone) → a frase que vai ao WhatsApp.
    executar: Callable[[Any, Any, str], Awaitable[str]]
    prazo_s: int = 120
    detalhes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    #: A parte do bot que a ação usa (`bot_helper`, `bot_meuplano`): conferida de novo na
    #: hora da senha — o gerente pode desligá-la no meio.
    parte: str = "bot_helper"
    #: Quando o resumo (o bloco 🔒) saiu para a pessoa — relógio daqui e hora UTC. `None` =
    #: ainda não saiu: senha nenhuma vale antes (`mostrada`).
    mostrada_em: tuple[float, datetime] | None = None
    #: Como a pessoa confirma: `senha` (a de atuação — equipamento, pelo helper) ou `sim`
    #: (registro no meuPlano: criar/concluir OS, lançar o dia). Pedido do dono (24/10/2026):
    #: senha é para ATUAÇÃO — "desligar, ligar, gravar"; concluir uma OS não é.
    confirmacao: str = "senha"
    #: A conversa com o meuPlano até esta proposta: depois de feita, o bot segue para o próximo
    #: passo do MESMO pedido (lá é uma proposta por vez — "crie a OS e conclua a 1638").
    conversa: list[dict] | None = None
    #: O pedido nas palavras da pessoa e o que dele já foi feito nesta sequência: se um passo
    #: falha, a resposta diz o que ficou — e não a instrução interna do bot (avaliação 13).
    pedido: str = ""
    feitos: tuple[str, ...] = ()
    #: O id dos botões Sim / Não DESTE resumo: o toque no Sim de um resumo antigo não confirma a
    #: ação de agora (avaliação 13 — o botão mandava sempre "sim").
    codigo: str = field(default_factory=lambda: secrets.token_hex(4))
    #: O que a ação confirmada deu (`_rodar`). Enquanto roda, a frase do "pode ter sido feita": se
    #: a execução estoura no meio, é ela que a pessoa recebe — nunca "tente de novo".
    desfecho: str | None = None
    #: A ação do meuPlano e os argumentos dela, (ação, args): o passo seguinte do pedido que repete
    #: o que acabou de ser feito não é oferecido (`assistente._seguir_no_meuplano`).
    acao: tuple[str, dict] | None = None


#: A ação que cada pessoa (id da conta) tem esperando a senha — uma por vez.
#: ponytail: em memória, um processo só (o uvicorn da API roda com um worker); com mais de
#: um, isto vai para o banco. A proposta vale minutos: perder no deploy é aceitável.
PENDENTES: dict[int, Pendente] = {}
#: Conferências que falharam por conta (quantas, desde quando), e até quando as ações estão
#: bloqueadas. Em memória: um reinício zera — e cada tentativa ainda exige o celular da pessoa.
_ERROS: dict[int, tuple[int, float]] = {}
_BLOQUEIO: dict[int, float] = {}


@dataclass
class Analise:
    """O que a mensagem tem de senha, olhado UMA vez por mensagem."""

    #: A mensagem é APENAS a senha ("482913", "senha 482-913") — a única que é tentativa.
    pura: bool = False
    acertou: bool = False
    bloqueada: bool = False
    #: Trechos (início, fim, marcador) a esconder numa FRASE: a senha conferida, ou todo
    #: candidato quando a pessoa passou do limite de conferências.
    trechos: list[tuple[int, int, str]] = field(default_factory=list)

    @property
    def escondeu_senha(self) -> bool:
        return any(m == SENHA_OCULTA for _, _, m in self.trechos)


#: Quando cada pessoa conferiu um número em frase (para o limite por hora).
_CONFERENCIAS: dict[int, list[float]] = {}


def digitos_da_senha(texto: str) -> str | None:
    """Os dígitos, se a mensagem INTEIRA é a senha (ver `NUMERO`); senão `None`."""
    m = PURA.match(_digitos_normais(texto))
    if m is None or not NUMERO.fullmatch(m.group(1)):
        return None
    digitos = _so_digitos(m.group(1))
    return None if _nao_e_senha(m.group(1), digitos) else digitos


def _pode_conferir(user_id: int) -> bool:
    agora = monotonic()
    recentes = [t for t in _CONFERENCIAS.get(user_id, []) if agora - t < 3600]
    _CONFERENCIAS[user_id] = recentes
    if len(recentes) >= CONFERENCIAS_POR_HORA:
        return False
    recentes.append(agora)
    return True


async def analisar(user, texto: str, tentativa: bool = True) -> Analise:
    """A senha conferida UMA vez por mensagem, fora do laço da API (`to_thread`: o pbkdf2 leva
    ~0,45 s).

    - A mensagem que é APENAS a senha é tentativa (conta erro e bloqueia).
    - Numa frase, cada número que pode ser a senha é conferido — até `CONFERENCIAS_POR_HORA`
      por pessoa —, e SÓ a senha é escondida ("[senha oculta]"): UC, protocolo, IP, data e CEP
      seguem legíveis para a IA (avaliação 9). Frase nunca conta erro nem bloqueia.
    - Conferidos no máximo `MAX_CONFERIDOS` números distintos — primeiro os que vêm depois de
      "senha"/"pin", depois na ordem do texto —; os demais são escondidos sem conferir. Passado o
      limite por hora, todo candidato é escondido sem conferir — o oráculo para ali.
    - `tentativa=False` (o número sozinho com uma ação do meuPlano esperando o SIM — `e_tentativa`):
      é conferido como numa frase, com o limite por hora, e nunca conta erro."""
    if user is None or not user.senha_atuacao_hash:
        return Analise()
    texto = texto or ""
    digitos = digitos_da_senha(texto)
    if digitos is not None and tentativa:
        if monotonic() < _BLOQUEIO.get(user.id, 0):
            return Analise(pura=True, bloqueada=True)
        acertou = await asyncio.to_thread(conferir_senha, digitos, user.senha_atuacao_hash)
        return Analise(pura=True, acertou=acertou)
    candidatos = candidatos_a_senha(texto)
    ordem = list(dict.fromkeys(d for _, _, d in candidatos))
    senha: set[str] = set()
    sem_conferir: set[str] = set()
    for i, d in enumerate(ordem):
        if i >= MAX_CONFERIDOS or not _pode_conferir(user.id):
            sem_conferir.update(ordem[i:])
            break
        if await asyncio.to_thread(conferir_senha, d, user.senha_atuacao_hash):
            senha.add(d)
    return Analise(trechos=[(a, b, SENHA_OCULTA if d in senha else OCULTO)
                            for a, b, d in candidatos if d in senha or d in sem_conferir])


def candidatos_a_senha(texto: str) -> list[tuple[int, int, str]]:
    """(início, fim, dígitos) de tudo que pode ser a senha numa frase, na ordem de conferência:
    o número logo depois de "senha"/"pin"/"confirmo" primeiro (cada começo dele que soma 6 a 8
    dígitos: "senha 482913 12"), depois os outros na ordem do texto."""
    original, texto = texto, _digitos_normais(texto)
    achados: list[tuple[int, int, int, str]] = []
    for p in PALAVRA.finditer(texto):
        m = NUMERO.match(texto, p.end())
        if m is None or _data_ou_ip(m.group()):
            continue
        partes = [g for g in re.finditer(r"\d+|" + _PALAVRA_DIGITO, m.group(), re.IGNORECASE)]
        for i in range(len(partes)):
            trecho = m.group()[:partes[i].end()]
            achados.append((0, m.start(), m.start() + partes[i].end(), _so_digitos(trecho)))
    for m in NUMERO.finditer(texto):
        achados.append((1, m.start(), m.end(), _so_digitos(m.group())))
    # O número de 6 a 8 dígitos dentro de um grupo maior também ("UC 1234567, 2345678" é um
    # número só para `NUMERO` quando a vírgula vem colada).
    achados += [(1, m.start(), m.end(), m.group()) for m in re.finditer(r"(?<!\d)\d{6,8}(?!\d)", texto)]
    def ate_o_enfeite(b: int) -> int:                   # o "️⃣" do último dígito de emoji vai junto
        while original[b:b + 1] in _TECLA:
            b += 1
        return b

    return [(a, ate_o_enfeite(b), d) for _, a, b, d in sorted(achados) if not _nao_e_senha(texto[a:b], d)]


def mascarar(texto: str, analise: Analise) -> str:
    """O texto com os trechos da análise escondidos. Trechos que se sobrepõem viram um só
    ("[senha oculta]" se algum deles é a senha)."""
    texto = texto or ""
    juntos: list[list] = []
    for ini, fim, marcador in sorted(set(analise.trechos)):
        if juntos and ini < juntos[-1][1]:
            juntos[-1][1] = max(juntos[-1][1], fim)
            if marcador == SENHA_OCULTA:
                juntos[-1][2] = SENHA_OCULTA
        else:
            juntos.append([ini, fim, marcador])
    for ini, fim, marcador in reversed(juntos):
        texto = texto[:ini] + marcador + texto[fim:]
    return texto


def desarmar(user_id: int, motivo: str | None = None) -> "Pendente | None":
    """Tira a ação que esperava a senha/o SIM. Devolve a que havia (valendo), ou `None`. `motivo`: a
    mensagem da pessoa que a derrubou (já sem a senha) — o toque depois no Sim/Não daquele resumo
    diz isso, e não "venceu ou o bot foi atualizado" (avaliação 16)."""
    p = PENDENTES.pop(user_id, None)
    if p is None or monotonic() > p.expira:
        return None
    if motivo is not None:
        _lembrar(_CANCELADAS, (user_id, p.codigo), motivo[:80] + ("…" if len(motivo) > 80 else ""))
    return p


def _contar_falhas(user_id: int, falhas: int) -> int:
    """Toda tentativa errada conta (a mensagem que é só o número), com ou sem ação esperando.
    Zera depois de `BLOQUEIO_S` sem erro. Devolve o total; no limite, bloqueia."""
    total, desde = _ERROS.get(user_id, (0, monotonic()))
    if monotonic() - desde > BLOQUEIO_S:
        total, desde = 0, monotonic()
    total += falhas
    if total >= TENTATIVAS:
        _ERROS.pop(user_id, None)
        PENDENTES.pop(user_id, None)
        _BLOQUEIO[user_id] = monotonic() + BLOQUEIO_S
    else:
        _ERROS[user_id] = (total, desde)
    return total


def parece_senha(texto: str) -> bool:
    """Para quem não tem conta conferida: a mensagem inteira parece uma senha — nunca vai em
    claro ao log."""
    return digitos_da_senha(texto) is not None


def validar_senha_atuacao(senha: str) -> str:
    """6 a 8 números, sem repetir nem seguir em sequência (111111, 123456, 654321). Devolve
    limpa. Seis no mínimo: a senha anda numa conversa de WhatsApp, e cada dígito a mais
    multiplica por dez o trabalho de quem tentar adivinhar."""
    s = (senha or "").strip()
    if not re.fullmatch(r"\d{6,8}", s):
        raise ValueError("A senha de atuação tem de 6 a 8 números.")
    passos = {int(b) - int(a) for a, b in zip(s, s[1:])}
    if passos in ({0}, {1}, {-1}):
        raise ValueError("Senha fácil demais (número repetido ou em sequência). Escolha outra.")
    return s


def nova_senha(user_id: int) -> None:
    """Senha trocada: zera as tentativas erradas e o bloqueio."""
    _ERROS.pop(user_id, None)
    _BLOQUEIO.pop(user_id, None)


#: A resposta afirmativa ("Sim, pode", "Pode sim", "Confirmado", "Isso mesmo", "Sim, crie a OS"):
#: começa por uma destas e o resto é só palavra NEUTRA — "Sim, mas troque o técnico" é correção,
#: "Pode me mandar o relatório" é outro pedido. Avaliação 12: o jeito comum de dizer sim cancelava.
_AFIRMA = {"sim", "s", "ss", "pode", "confirmo", "confirma", "confirmar", "confirmado", "confirmada", "correto",
           "certo", "isso", "ok", "okay", "beleza", "blz", "positivo", "claro", "perfeito", "exato", "fechado",
           "show", "bora", "manda", "vai", "faz", "faça", "faca", "segue", "siga", "prossiga", "aprovado",
           "aprovada", "aprovo", "autorizo", "autorizado", "autorizada", "acordo", "fechou",
           "uhum", "aham", "exatamente", "joia", "jóia", "certeza", "ótimo", "otimo", "ótima", "otima",
           "afirmativo", "tranquilo", "top", "massa", "boa", "yes", "si", "concordo", "concordamos", "tá", "ta",
           "certinho", "combinado", "feito", "demorou", "firmeza",
           # avaliação 23: "Sí", "Yep", "Simbora" cancelavam
           "sí", "yep", "yup", "yeah", "simbora", "partiu",
           # avaliação 26: "Procede", "Liberado", "Valido" derrubavam a ação
           "procede", "proceda", "efetue", "efetua", "realize", "realiza", "liberado", "liberada", "libera", "libere",
           "valido", "válido", "validado", "validada", "valide",
           # avaliação 27: "Executa", "Lógico", "Excelente" derrubavam a ação
           "executa", "execute", "lógico", "logico", "excelente", "maravilha", "perfeitamente", "certamente",
           "obviamente"}
#: As afirmativas de mais de uma palavra, como se fala — lista FECHADA. Viram "sim" antes de olhar as
#: palavras, sem depender do resumo (avaliação 16: "Sim, com certeza", "Sim, sem problema", "Claro que
#: sim" e "Sim senhor" cancelavam; "Sim, com certeza" confirmava "Criar OS… com…" só porque o resumo
#: tinha "com").
_EXPRESSOES_SIM = re.compile(r"\b(?:com certeza|sem (?:nenhum )?problemas?(?: nenhum)?|sem d[úu]vidas?(?: nenhuma)?|"
                             r"claro que (?:sim|pode)|sim,? senhora?|pode sim|por (?:favor|gentileza)|"
                             r"n[ãa]o tem (?:problemas?|erro)(?: nenhum)?|(?:pode )?(?:ir|vai) em frente|manda ver|s[óo] isso|"
                             r"nada (?:a|pra|para) acrescentar|vamos (?:l[áa]|nessa)|por mim (?:pode|tudo bem|ok)|manda brasa|"
                             r"vamos(?=\s*[!.]*\s*$)|(?:t[áa]|est[áa]|tudo|muito) (?:bom|bem)|pode crer|"
                             r"cem por cento)\b|(?<!\d)100 ?%")
#: Hesitação sozinha ("Bem...", "Bom...", "Hmm") não é SIM: o sistema pergunta de novo (avaliação 19:
#: confirmava). Acompanhada ("tá bom", "tudo bem"), é a expressão acima.
_HESITACAO = {"bem", "bom", "hum", "hmm", "hmmm", "ah", "eh", "uhm", "pois", "então", "entao"}
#: Palavras que podem vir ANTES da afirmativa ("tá certo", "de acordo", "tudo bem", "então pode",
#: "Opa, pode", "Valeu, pode fazer").
_ANTES = {"tá", "ta", "está", "esta", "de", "então", "entao", "ah", "é", "e", "tudo", "com", "opa", "valeu",
          "obrigado", "obrigada", "pra"}
#: O resto da frase só pode ter palavra NEUTRA — lista fechada. Nunca "para" (preposição e o
#: imperativo de PARAR: "Ok, para tudo!" executava — avaliação 14), "não", "mas", "espera".
_NEUTRAS = _AFIRMA | {"a", "o", "as", "os", "e", "de", "da", "do", "também", "tambem", "por", "favor", "obrigado",
                      "obrigada", "valeu", "mesmo", "ser", "bala", "ver", "fazer", "seguir", "prosseguir", "ir", "ai",
                      "aí", "agora", "então", "entao", "tá", "ta", "bom", "certinho", "ótimo", "otimo", "tudo",
                      "executar", "execute", "executa", "aprovar", "aprove", "continuar", "continue", "pra", "assim",
                      "mandar", "mande", "lá", "la", "é", "está", "esta", "já", "ja",
                      # o agradecimento abreviado ("Sim, obg", "Sim vlw" — avaliação 23: cancelavam)
                      "vlw", "valew", "obg", "obgd", "obgda", "brigado", "brigada", "grato", "grata", "pfv", "pfvr",
                      "pf", "tmj",
                      # o "pode seguir" dito de outro jeito ("Pode proceder", "Pode dar andamento" — avaliação 26)
                      "proceder", "efetuar", "realizar", "liberar", "validar", "dar", "andamento", "sequência",
                      "sequencia", "seguimento", "prosseguimento", "continuidade"}
def _formas(infinitivo: str) -> set[str]:
    """As formas que se digitam de um verbo regular: o infinitivo, a 3ª pessoa e o imperativo
    ("apagar" → apaga, apague; "concluir" → conclui, conclua; "mover" → move, mova)."""
    raiz, fim = infinitivo[:-2], infinitivo[-2:]
    if fim == "ar":
        antes_de_e = (raiz[:-1] + "qu" if raiz.endswith("c") else raiz[:-1] + "gu" if raiz.endswith("g")
                      else raiz[:-1] + "c" if raiz.endswith("ç") else raiz)
        formas = {raiz + "a", antes_de_e + "e", antes_de_e + "em"}
    elif raiz.endswith("u"):                         # concluir, excluir, incluir
        formas = {raiz + "i", raiz + "a", raiz + "am"}
    else:
        formas = {raiz + "e", raiz + "a", raiz + "am"}
    return {unicodedata.normalize("NFKD", f).encode("ascii", "ignore").decode() for f in formas | {infinitivo}}


#: Os verbos das ações do meuPlano (o primeiro do resumo de cada uma, conferidos nas prévias de lá em
#: 24/10/2026) e os sinônimos e substantivos de cada um. Lista FECHADA. Na resposta ao resumo, o verbo
#: da PRÓPRIA ação confirma ("Fecha", "Apaga", "Confirmo o fechamento" — avaliação 17); verbo de OUTRA
#: ação nunca confirma ("Pode criar" para "APAGAR 3 itens", "Pode abrir a OS" para "Fechar a OS 1638"
#: — avaliação 18): o sistema pergunta de novo.
_FAMILIAS = {
    "apagar": ("apagar", "excluir", "deletar", "exclusao", "remocao"),
    # "abrir a OS" é criá-la (jargão da O&M): "Pode criar" confirma "Abrir a OS…", e vice-versa
    "editar": ("editar", "edicao"), "criar": ("criar", "criacao", "abrir", "abertura"),
    "cadastrar": ("cadastrar", "cadastro"),
    "adicionar": ("adicionar",), "remover": ("remover",), "gravar": ("gravar",),
    "registrar": ("registrar", "registro"), "gerar": ("gerar",), "concluir": ("concluir", "conclusao"),
    "ajustar": ("ajustar", "ajuste"), "clonar": ("clonar",), "trocar": ("trocar",),
    "desinstalar": ("desinstalar", "desinstalacao"), "instalar": ("instalar", "instalacao"),
    "definir": ("definir",), "aplicar": ("aplicar",), "comentar": ("comentar", "comentario"),
    "alterar": ("alterar", "alteracao"), "fechar": ("fechar", "fechamento", "encerrar", "encerramento"), "associar": ("associar",),
    "mover": ("mover",), "transferir": ("transferir", "transferencia"), "alocar": ("alocar",),
    "devolver": ("devolver", "devolucao"), "lancar": ("lançar", "lancamento"),
    "anexar": ("anexar",), "programar": ("programar",), "agendar": ("agendar",), "enviar": ("enviar",),
    "arquivar": ("arquivar",), "atualizar": ("atualizar", "atualizacao"), "assinar": ("assinar", "assinatura"),
}
_VERBOS = {forma: raiz for raiz, palavras in _FAMILIAS.items() for p in palavras
           for forma in (_formas(p) if p.endswith(("ar", "er", "ir")) else {p})}
#: O que pode acompanhar uma afirmativa sem trazer assunto novo, mas sem deixar claro que é SIM ("Sim,
#: pode deixar", "Ok, vou ver"): o sistema pergunta de novo. Palavra fora disto é assunto novo ("Ok, e
#: Pereiras", "Pode mandar o PDF") — vai à IA (avaliação 17: era engolido).
_SEM_ASSUNTO = {"deixar", "comigo", "vou", "ver", "vejo", "vamos", "vamo", "acho", "talvez", "pensar",
                "hum", "hmm", "né", "ne", "que", "eu"}
#: Só agradecimento ou ciência ("valeu", "obrigado", "ok, aguardo", "fico no aguardo") — lista
#: FECHADA, sem palavra de parar (há teste). É a única mensagem mandada antes do resumo que não o
#: derruba (`mandada_antes_do_resumo`).
_CIENCIA = {"valeu", "vlw", "obrigado", "obrigada", "obg", "brigado", "brigada", "ok", "okay", "beleza", "blz",
            "show", "certo", "perfeito", "ótimo", "otimo", "aguardo", "aguardando", "entendi", "entendido",
            "combinado", "joia", "jóia", "tá", "ta", "bom", "muito", "fico", "no", "e"}
#: Só o gesto — com o tom de pele que muita gente deixa como padrão (👍🏽 cancelava, avaliação 14).
_SO_OK = re.compile(r"^[\s👍✅👌✔️☑️🆗\U0001F3FB-\U0001F3FF]+$")
#: Pergunta, escrita com qualquer sinal: o "?" e o de largura cheia, o espanhol, os de emoji, a interrogobang
#: (avaliações 22 e 23: "Apaga❓", "Apaga⁉️", "Apaga？", "¿Apaga", "Apaga‽" apagavam).
_PERGUNTA = re.compile(r"[?？¿❓❔⁉⁈⁇‽⸮]")
#: Emoji que é "sim". Qualquer OUTRO — ❌ 👎 ✋ 🛑 ⛔ 🤷 🙄 🤔 😬 🙏… — é dúvida: o sistema pergunta de novo
#: (avaliação 23: a lista FECHADA dos de dúvida deixava "Apaga ❌" e "Sim 👎" apagarem; agora a fechada é a do sim).
_EMOJI_DE_SIM = set("👍👌✅✔✓☑🆗🙂😊☺😀😃😄😁😉👏🙌💪🤝✌🤙🫡💯🚀❤💚💙")
#: O que acompanha o emoji sem mudar o sentido: o tom de pele, o seletor de variação, a junção.
_ENFEITE_DE_EMOJI = {"\ufe0f", "\u200d", *map(chr, range(0x1F3FB, 0x1F400))}


#: Emoticon de TEXTO de dúvida, desânimo ou susto (":/", ":(", ":|", "-_-", "¬¬", "._.", ":'(", "D:"): o mesmo que
#: 😕 🙁 😑 — pergunta de novo (avaliação 24: confirmavam o APAGAR). O alegre (":)", ":D", ";)") sai antes das palavras.
_EMOTICON_DE_DUVIDA = re.compile(r"(?<![\w:])(?:[:;=]['’]?-?[/\\(|\[{@$sSoO0]|D:|-_-|¬¬|\._\.|>_<|[oO]_[oO]|T_T|u_u)(?!\w)")
_EMOTICON_ALEGRE = re.compile(r"(?<![\w:])(?:[:;=]['’]?-?[)\]DpP3*]+|\(:|\^_?\^|<3|[xX][dD])(?!\w)")


def _emoticon_que_nao_e_alegre(texto: str) -> bool:
    """O emoticon de TEXTO que não é dos alegres (";-;", "-.-", ">.<", "):", ":<", "e.e") — a lista fechada é a dos
    alegres, como a dos emojis (avaliação 25: a fechada dos de dúvida deixava "Apaga ;-;" e "Sim -.-" apagarem)."""
    for pedaco in texto.split():
        nucleo = pedaco.strip(",.!")
        if not nucleo or _EMOTICON_ALEGRE.fullmatch(nucleo):
            continue
        if re.fullmatch(r"([a-z0-9])[._]\1", nucleo, re.IGNORECASE):          # "e.e", "o_o", "u.u"
            return True
        so_sinais = not re.search(r"[^\W_]", nucleo) and not any(
            unicodedata.category(c) in ("So", "Sk", "Mn", "Cf") for c in nucleo)    # o emoji tem a regra dele
        if so_sinais and len(nucleo) >= 2:
            return True
    return False


def _emoji_que_nao_e_sim(texto: str) -> bool:
    return any(unicodedata.category(c) in ("So", "Sk") and c not in _EMOJI_DE_SIM and c not in _ENFEITE_DE_EMOJI
               for c in texto)


def _palavras(texto: str) -> list[str]:
    return re.findall(r"[a-zà-ú]+|\d+", (texto or "").lower())


def _verbo(palavra: str) -> str | None:
    return _VERBOS.get(unicodedata.normalize("NFKD", palavra).encode("ascii", "ignore").decode())


def _tem(lista, palavra: str) -> bool:
    """A palavra está na lista — também esticada no chat ("Simm", "okkk", "nããão")."""
    return palavra in lista or re.sub(r"([a-zà-ú])\1+", r"\1", palavra) in lista


def _pessoas_do_resumo(acao: str) -> list[set[str]]:
    """As pessoas que o resumo lista depois de "por"/"com" ("por Michel Renan…, Diogo Dardani"), cada
    uma como o conjunto das palavras do nome — só quando são duas ou mais."""
    grupos = []
    for m in re.finditer(r"\b(?:por|com)\s+([^.;:()]+)", acao):
        grupos += [set(_palavras(n)) for n in re.split(r",\s*|\s+e\s+", m.group(1)) if n.strip()[:1].isupper()]
    return grupos if len(grupos) >= 2 else []


#: Ação de VÁRIOS alvos ("APAGAR 3 item(ns)", "Desinstalar … de 2 ponto(s)") ou que apaga/tira: na
#: resposta DIGITADA, citar um alvo só confirma se cobre todos — é precisão ou correção ("Apaga o 3" apagava
#: os três, avaliação 20); "todos", "os 3" confirmam, e "os inversores" só se TODOS os itens forem
#: inversores (avaliação 21). Nas outras, citar o alvo do resumo confirma ("Pode fechar a OS 1638", "Sim,
#: pode criar a OS de Ibitinga").
_DESTRUTIVOS = {"apagar", "remover", "desinstalar", "transferir"}
#: O pronome: no SINGULAR é UM alvo — numa ação de vários (ou que apaga), qual? ("Pode apagar esse" apagava os três —
#: avaliação 24); numa de um alvo só, é ele ("Pode fechar ela"). No PLURAL, são todos ("Apaga esses").
_PRONOME_UM = {"esse", "essa", "este", "esta", "ele", "ela", "aquele", "aquela", "isto", "aquilo"}
_PRONOME_TODOS = {"esses", "essas", "estes", "estas", "eles", "elas", "aqueles", "aquelas"}
_NUMERAIS = {"dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
             "oito": 8, "nove": 9, "dez": 10}


def _contagens(resumo: str) -> list[tuple[int, str]]:
    """As quantidades que o resumo declara e o que elas contam ("3 item(ns)" → (3, "item"), "41 nó(s)",
    "2 ligação(ões)")."""
    return [(int(n), o_que) for n, o_que in re.findall(r"\b(\d+)\s+([a-zà-ú]+)\((?:s|ns|ões|es)\)", resumo.lower())]


def _singular(p: str) -> str:
    for fim, troca in (("ões", "ão"), ("ães", "ão"), ("ns", "m"), ("res", "r"), ("es", ""), ("s", "")):
        if p.endswith(fim) and len(p) > len(fim) + 1:
            return p[:-len(fim)] + troca
    return p


def _quantidade(p: str, anterior: str, quantos: set[int]) -> bool | None:
    """Palavra de QUANTIDADE: True = todos ("todos", "tudo", "os 3" e "os três" quando o resumo declara
    3, "ambos" quando são 2 — itens ou pessoas listadas); False = uma parte ("ambos" com 3 itens); None
    = não é. O número depois de "os" que não é a contagem segue como alvo ou assunto: "a OS 1639" é a
    ordem, não a quantidade."""
    if p in ("todos", "todas", "tudo"):
        return True
    if p in ("ambos", "ambas"):
        return 2 in quantos
    n = int(p) if p.isdigit() else _NUMERAIS.get(p)
    return True if anterior in ("os", "as") and n in quantos else None


def _plural_dos_itens(p: str, contados: set[str], linhas: list[set[str]], da_acao: set[str]) -> bool | None:
    """O plural do que os itens são ("inversores", "ligações", "nós"): True = fala de todos — é o que o
    resumo conta ("3 item(ns)" → "os itens") ou TODA linha é disso; False = só os desse tipo ("os
    inversores" com uma medição na lista: apagava a medição junto — avaliação 21); None = não é."""
    um = _singular(p)
    if not (p.endswith("s") and p not in da_acao and um in da_acao):
        return None
    return um in contados or all(um in linha for linha in linhas)


def _cobre_todos(alvos: set[str], itens: Sequence[str]) -> bool:
    """Os alvos citados alcançam TODAS as linhas da ação: cada linha tem a sua marca (o que só ela tem —
    "1" em "Inversor 1 (INV-1)") e alguma marca de cada uma foi citada ("Apaga INV-1, INV-2 e INV-3").
    Um alvo só: citá-lo é confirmá-lo. Linha sem marca própria (repetida) nunca fica coberta."""
    linhas = [set(_palavras(l)) - _NEUTRAS for l in itens]
    if len(linhas) < 2:
        return True
    return all((l - set().union(*(m for j, m in enumerate(linhas) if j != i))) & alvos for i, l in enumerate(linhas))


def _resposta_ao_resumo(texto: str, acao: str = "", itens: Sequence[str] = ()) -> str:
    """Como a mensagem responde ao resumo que espera o SIM (`acao`: o resumo; `itens`: as linhas dele):
    - "sim": o 👍/✅, ou uma afirmativa (ou o verbo da própria ação) e depois só palavra neutra — e
      palavra do resumo só numa ação de UM alvo que não apaga ("Sim, pode criar a OS de Ibitinga"); número
      só o que está nele ("Pode fechar a 1640" não confirma "Fechar a OS 1638", avaliação 15);
    - "outra": pergunta, negação, parada, restrição, troca fora do resumo, número fora dele, assunto novo,
      ou o que não começa por afirmativa — derruba a ação (e vai à IA, que fica sabendo);
    - "duvida": não confirma nem derruba — o sistema pergunta de novo: a afirmativa curta sem assunto
      novo que não é SIM limpo ("Sim, pode deixar"), o verbo de outra ação, a hesitação, e — numa ação
      de VÁRIOS alvos ou que apaga — o alvo citado ("Apaga o 3", "Sim, o INV-13"; avaliação 20), ou só
      uma das pessoas listadas ("Sim, o Michel" para "…por Michel…, Diogo…"; avaliação 19)."""
    t = (texto or "").strip()
    if t and _SO_OK.match(t):
        return "sim"
    if _PERGUNTA.search(t):                            # "Apaga? 🤔", "Fecha?!", "Apaga❓" (avaliações 21 e 22)
        return "outra"
    if _emoji_que_nao_e_sim(t) or _EMOTICON_DE_DUVIDA.search(t) or _emoticon_que_nao_e_alegre(t):
        return "duvida"
    t = _EMOTICON_ALEGRE.sub(" ", t)
    palavras = _palavras(_EXPRESSOES_SIM.sub(" sim ", t.lower()))
    da_acao = set(_palavras(acao)) | set(_palavras(" ".join(itens)))
    if palavras and all(p in _HESITACAO for p in palavras):
        return "duvida"
    verbo_da_acao = _verbo(_palavras(acao)[0]) if _palavras(acao) else None

    def mesmo_verbo(p: str) -> bool:
        return verbo_da_acao is not None and _verbo(p) == verbo_da_acao

    # A palavra de TROCAR que está no próprio resumo ("Pode trocar"/"Troque" para "Trocar o
    # equipamento…") não impede; negar, parar e restringir, nunca — nem no resumo ("Mover a OS 1638
    # PARA concluída").
    if any(_tem(_PARAR, p) and not (_tem(_TROCA, p) and (_tem(da_acao, p) or mesmo_verbo(p))) for p in palavras):
        return "outra"
    while len(palavras) > 1 and _tem(_ANTES, palavras[0]) and not _tem(_AFIRMA, palavras[0]):
        palavras = palavras[1:]
    if (not palavras or not (_tem(_AFIRMA, palavras[0]) or mesmo_verbo(palavras[0]))
            or any(p.isdigit() and p not in da_acao for p in palavras)):
        return "outra"
    pessoas = _pessoas_do_resumo(acao)
    contagens = _contagens(acao)
    varios = any(n >= 2 for n, _ in contagens) or verbo_da_acao in _DESTRUTIVOS
    quantos = {n for n, _ in contagens} | ({len(pessoas)} if pessoas else set())  # "Sim, os dois" (as pessoas)
    linhas = [set(_palavras(linha)) for linha in itens]
    # Verbo de OUTRA ação nunca confirma: "Pode criar" confirmava "APAGAR 3 itens" (avaliação 18).
    outro_verbo, parcial, alvos, novos = False, False, [], []
    for i, p in enumerate(palavras[1:], start=1):
        if p == "isso" and varios:                     # "Apaga isso aí" (avaliação 25: apagava os três)
            parcial = True
            continue
        if p in _PRONOME_UM:
            parcial = parcial or varios or bool(pessoas)
            continue
        if p in _PRONOME_TODOS:
            if not (varios or pessoas):
                novos.append(p)                        # "elas" numa ação de um alvo só não é ela
            continue
        if _tem(_NEUTRAS, p) or mesmo_verbo(p):
            continue
        quantidade = _quantidade(p, palavras[i - 1], quantos)
        if quantidade is not None:
            if not (varios or pessoas):
                novos.append(p)                        # um alvo só: "Pode fechar todas" não é a OS 1638
            parcial = parcial or not quantidade
            continue
        plural = _plural_dos_itens(p, {o for _, o in contagens}, linhas, da_acao)
        if plural is not None:
            parcial = parcial or (varios and not plural)
            continue
        if _verbo(p) is not None:
            outro_verbo = True
        elif p in da_acao:
            alvos.append(p)
        else:
            novos.append(p)
    if novos and not all(_tem(_SEM_ASSUNTO, n) for n in novos):
        return "outra"                                 # assunto novo: vai à IA
    if outro_verbo or novos:
        return "duvida" if len(palavras) <= 4 else "outra"
    if palavras[-1] in ("mesmo", "mesma") and palavras[-2] not in ("isso", "é", "sim", "certo", "exatamente"):
        return "duvida"
    if parcial or (alvos and varios and not _cobre_todos(set(alvos), itens)):
        return "duvida" if len(palavras) <= 8 else "outra"
    citadas = [g for g in pessoas if g & set(palavras)]
    if 0 < len(citadas) < len(pessoas):
        return "duvida"
    return "sim" if len(palavras) <= 8 else "outra"


def e_sim(texto: str, acao: str = "", itens: Sequence[str] = ()) -> bool:
    """A mensagem confirma a ação que espera SIM: o botão "Sim", uma afirmativa ou só o 👍/✅
    (`_resposta_ao_resumo`)."""
    return _resposta_ao_resumo(texto, acao, itens) == "sim"


def responde_sim(user_id: int, texto: str) -> bool:
    """A mensagem é o SIM da ação do meuPlano esperando (vencida ou não: o "sim" tardio ouve que
    venceu), conferida contra o que o resumo dela diz (`e_sim`)."""
    p = PENDENTES.get(user_id)
    return p is not None and p.confirmacao == "sim" and e_sim(texto, p.resumo, p.detalhes)


#: A afirmativa que não é um SIM limpo, com a ação do meuPlano esperando: nem confirma nem cancela — e
#: diz o alcance inteiro: "Apaga o 15" virava dúvida, mas a pergunta não dizia que o Sim apaga os três
#: (avaliação 21).
DE_NOVO = ("Ainda não foi feito. O *Sim* vale para TUDO isto:\n{escopo}\n\nPara fazer tudo, toque em *Sim* (ou "
           "responda só SIM) até as {limite}. Se era só uma parte, ou para mudar algo, diga o que mudar.")


def pergunta_de_novo(user_id: int, texto: str) -> str | None:
    """A afirmativa ambígua ("Sim, pode deixar") com a ação do meuPlano esperando o SIM: a ação
    continua armada e o SISTEMA pergunta de novo, sem ir à IA — antes, ela era derrubada, o
    contrário do que a pessoa disse (avaliação 16). Vencida, diz que venceu. `None` = não é o caso."""
    p = PENDENTES.get(user_id)
    if p is None or p.confirmacao != "sim" or _resposta_ao_resumo(texto, p.resumo, p.detalhes) != "duvida":
        return None
    if monotonic() > p.expira:
        PENDENTES.pop(user_id, None)
        return VENCEU.format(limite=_limite(p))
    return DE_NOVO.format(escopo=_escopo(p), limite=_limite(p))


def de_novo_para_reacao(user_id: int) -> str | None:
    """A reação (👍) ao resumo da ação do meuPlano esperando o Sim: não confirma — pode ser só "vi" —, mas
    também não fica em silêncio até a ação vencer (avaliação 22): o sistema pergunta de novo, com os botões.
    `None` = não há ação do meuPlano esperando (a reação segue ignorada)."""
    p = PENDENTES.get(user_id)
    if p is None or p.confirmacao != "sim" or p.mostrada_em is None or monotonic() > p.expira:
        return None
    return DE_NOVO.format(escopo=_escopo(p), limite=_limite(p))


def so_ciencia(texto: str) -> bool:
    """A mensagem é só agradecimento ou ciência ("valeu", "ok, aguardo", 👍). Pergunta não é."""
    t = (texto or "").strip()
    if t and _SO_OK.match(t):
        return True
    palavras = _palavras(t)
    return not _PERGUNTA.search(t) and 0 < len(palavras) <= 6 and all(_tem(_CIENCIA, p) for p in palavras)


#: Só o cancelamento ("não", "cancela", "não quero", "deixa pra lá") — curto. "Não, o técnico é o
#: Diogo" é CORREÇÃO: cancela a ação e vai à IA (avaliação 12: a correção se perdia).
_CANCELA_PALAVRAS = {"não", "nao", "n", "cancela", "cancele", "cancelar", "desisto", "desiste", "esquece",
                     "esqueça", "esqueca", "para", "pare", "deixa", "negativo"}


_CANCELA_NEUTRAS = _CANCELA_PALAVRAS | {"quero", "obrigado", "obrigada", "precisa", "pra", "lá", "la", "isso",
                                        "agora", "valeu", "mais", "nada", "por", "enquanto", "faça", "faz", "pode"}
#: Trocar ou corrigir: não confirma — a não ser a palavra que está no PRÓPRIO resumo ("Pode trocar"
#: para "Trocar o equipamento…" nunca confirmava — avaliação 16).
_TROCA = {"outro", "outra", "outros", "outras", "troca", "troque", "trocar", "muda", "mude", "mudar", "corrige",
          "corrija"}
#: Parar, negar, esperar, restringir ou trocar: com qualquer uma, a frase nunca confirma. Parar, negar
#: e esperar nem quando a palavra está no resumo ("Mover a OS 1638 PARA concluída" e "Ok, para tudo!");
#: restringir também não: "Pode, só a 1638" fecharia a 1640 de "Fechar só a OS 1638 e a 1640". Lista
#: fechada; nenhuma entra nas neutras nem na ciência (há teste).
_PARAR = _CANCELA_PALAVRAS | _TROCA | {"parar", "parem", "nem", "nunca", "nada", "jamais", "mas", "porém", "porem",
                                       "espera", "espere", "esperar", "pera", "peraí", "perai", "calma", "segura",
                                       "aguarde", "errado", "errada", "sem", "exceto", "menos", "só", "so", "apenas",
                                       "somente"}


def so_cancela(texto: str) -> bool:
    """A mensagem é SÓ o cancelamento — sem informação nova ("não é amanhã" e "não, corredores"
    são correções, e vão à IA)."""
    palavras = re.findall(r"[a-zà-ú]+|\d+", (texto or "").lower())
    return (0 < len(palavras) <= 4 and palavras[0] in _CANCELA_PALAVRAS
            and all(p in _CANCELA_NEUTRAS for p in palavras[1:]))


def cancelada(p: "Pendente | None") -> str:
    """O pé da resposta quando a mensagem derrubou a ação que esperava — sem falar de senha na
    ação do meuPlano (a queixa do dono: "parei de falar da senha e ele traz ainda")."""
    return ACAO_CANCELADA_SIM if p is not None and p.confirmacao == "sim" else ACAO_CANCELADA


def e_tentativa(user, texto: str) -> bool:
    """A mensagem é uma tentativa de SENHA: só o número, sem ação do meuPlano esperando o SIM. Com
    ela esperando, o número é conversa (a UC, o protocolo que a IA pediu) — tenha a pessoa senha ou
    não: ação do meuPlano não pede senha, e o número não conta erro nem bloqueia (avaliação 13). Se
    for a senha, some como numa frase (`analisar`, com o limite por hora)."""
    return digitos_da_senha(texto) is not None and not espera_sim(user.id)


#: O toque num botão de um resumo que não é o da ação esperando agora.
BOTAO_ANTIGO = "Esse botão é de um resumo antigo. Nada foi feito."
#: O toque quando não há ação esperando nenhuma: venceu e saiu, ou o bot foi atualizado (a ação
#: esperando vive em memória e se perde no deploy — avaliação 14: dizia "resumo antigo").
BOTAO_SEM_ACAO = ("Essa confirmação não vale mais: o pedido venceu ou o bot foi atualizado. Nada foi feito. "
                  "Se ainda quiser, peça de novo.")
#: O toque de novo no Sim/Não de um resumo JÁ confirmado (o WhatsApp deixa os botões tocáveis):
#: ouvia "Nada foi feito — peça de novo" logo abaixo do ✅, um convite a duplicar a OS (avaliação 15).
JA_CONFIRMADA = "Essa ação já foi confirmada e não roda de novo. O que houve: {desfecho}"
#: O desfecho de uma ação que estourou no meio da execução.
INCERTA = "⚠️ A ação «{resumo}» deu erro no meio: ela PODE ter sido feita. Confira antes de pedir de novo."
#: O toque no Sim/Não de um resumo que a PRÓPRIA mensagem da pessoa derrubou ("esta ação", e não "nada
#: foi feito": no pedido de vários passos, o passo anterior foi — avaliação 15).
CANCELADA_PELA_MENSAGEM = ("Essa ação foi cancelada pela sua mensagem «{trecho}» e não foi feita. Se ainda quiser, "
                           "peça de novo.")
#: O desfecho das ações já confirmadas, e a mensagem que derrubou as canceladas, pelo código do
#: resumo (conta, código).
#: ponytail: em memória, as últimas 500 de cada; o deploy esquece, e aí vale BOTAO_SEM_ACAO.
_CONFIRMADAS: OrderedDict[tuple[int, str], str] = OrderedDict()
_CANCELADAS: OrderedDict[tuple[int, str], str] = OrderedDict()


def _lembrar(guardadas: OrderedDict, chave: tuple[int, str], valor: str) -> None:
    guardadas[chave] = valor
    while len(guardadas) > 500:
        guardadas.popitem(last=False)


async def _rodar(p: Pendente, db, user, telefone: str) -> str:
    """Executa a ação confirmada — quem chama já a tirou de PENDENTES: uma vez só — e guarda o
    desfecho pelo código do resumo."""
    if p.parte not in user.bot_ativo:
        return PARTE_DESLIGADA
    chave = (user.id, p.codigo)
    p.desfecho = INCERTA.format(resumo=p.resumo)
    _lembrar(_CONFIRMADAS, chave, p.desfecho)
    _CONFIRMADAS[chave] = p.desfecho = await p.executar(db, user, telefone)
    return p.desfecho


def resposta_ao_botao(user_id: int, botao: str | None) -> str | None:
    """O que o sistema responde ao toque no Sim/Não que NÃO confirma nem cancela a ação de agora;
    `None` = é o botão do resumo esperando, e ele segue. O WhatsApp mantém os botões das mensagens
    antigas, e o id leva o código do resumo ("sim:<código>"); sem o código (botão de antes desta
    versão), não há como saber de qual resumo veio. O Não de um resumo vencido ouve que venceu,
    como o Sim (ia à IA)."""
    codigo = (botao or "").partition(":")[2]
    feita = _CONFIRMADAS.get((user_id, codigo))
    if feita is not None:
        return JA_CONFIRMADA.format(desfecho=feita.split("\n")[0])
    if (user_id, codigo) in _CANCELADAS:
        return CANCELADA_PELA_MENSAGEM.format(trecho=_CANCELADAS[(user_id, codigo)])
    p = PENDENTES.get(user_id)
    if p is None:
        return BOTAO_SEM_ACAO
    if botao not in (f"sim:{p.codigo}", f"nao:{p.codigo}"):
        return BOTAO_ANTIGO
    if monotonic() > p.expira:
        PENDENTES.pop(user_id, None)
        return VENCEU.format(limite=_limite(p))
    return None


def mandada_antes_do_resumo(user_id: int, texto: str, chegou: float | None, mandada_em: datetime | None) -> bool:
    """A mensagem de CIÊNCIA ("valeu" mandado enquanto o bot buscava o próximo passo) que saiu do
    celular antes de o resumo da ação de agora chegar: não é resposta a ele, e não o derruba
    (avaliação 14). Só ela: "cancela", "não" e a correção ("não, é o 12") derrubam como qualquer
    mensagem — poupar toda mensagem de antes deixava a senha seguinte executar o 13 (avaliação 15)."""
    p = PENDENTES.get(user_id)
    return (p is not None and p.mostrada_em is not None and so_ciencia(texto)
            and _antes_do_resumo(p, chegou, mandada_em))


def espera_sim(user_id: int) -> bool:
    """Há uma ação do meuPlano esperando o SIM desta pessoa (vencida ou não: o "sim" tardio
    ouve que venceu, não vai à IA)."""
    p = PENDENTES.get(user_id)
    return p is not None and p.confirmacao == "sim"


def propor(ctx, resumo: str, prazo_s: int, executar, detalhes=(), avisos=(), parte: str = "bot_helper",
           confirmacao: str = "senha", conversa: list[dict] | None = None, feitos: tuple[str, ...] = (),
           acao: tuple[str, dict] | None = None) -> dict:
    """Guarda a ação desta pessoa e devolve o que o modelo mostra. Nada rodou.

    - Sem senha de atuação cadastrada nem guarda: a ação não teria como ser confirmada.
    - UMA ação por mensagem: a segunda é recusada (antes, só a última ficava armada e a IA
      descrevia as duas).
    - O texto que a pessoa confirma é do SISTEMA, não da IA: `bloco_da_proposta` é acrescentado
      ao pé da resposta, com o resumo exato, os avisos e o prazo (`assistente._atender`)."""
    user = ctx.user
    if confirmacao == "senha" and not user.senha_atuacao_hash:
        PENDENTES.pop(user.id, None)
        return {"proposta_pendente": resumo, "sem_senha_de_atuacao": True,
                "instrucao": ("NADA foi executado, e não pode ser: esta pessoa ainda não tem SENHA DE ATUAÇÃO. "
                              "Mostre o resumo e diga que o gerente da O&M define a senha dela no oem-gs "
                              "(Bot do WhatsApp). Leitura continua liberada.")}
    if ctx.proposta is not None:
        if ctx.proposta.confirmacao == "sim":           # avaliação 15: a IA ouvia "senha" na do meuPlano
            seguir = (". Depois do Sim, o sistema segue sozinho para o próximo passo do pedido"
                      if ctx.proposta.conversa is not None else "")
            return {"erro": f"Uma ação por vez: já há uma esperando o Sim da pessoa nesta mensagem. Fale só dela{seguir}."}
        return {"erro": "Uma ação por vez: já há uma esperando a senha nesta mensagem. Fale só dela."}
    p = Pendente(resumo, monotonic() + prazo_s, executar, prazo_s, [d for d in detalhes if d], [a for a in avisos if a],
                 parte, confirmacao=confirmacao, conversa=conversa, pedido=getattr(ctx, "pedido", "") or "",
                 feitos=tuple(feitos), acao=acao)
    PENDENTES[user.id] = ctx.proposta = p
    if confirmacao == "sim":
        return {
            "proposta_pendente": resumo,
            "vale_por_s": prazo_s,
            "instrucao": ("NADA foi executado. O SISTEMA acrescenta ao fim da sua resposta o resumo exato da ação e "
                          "pede que a pessoa responda SIM: diga em uma linha o que será feito e não repita o resumo. "
                          "Não fale de senha (ação do meuPlano não pede senha), nunca diga que fez."),
        }
    return {
        "proposta_pendente": resumo,
        "vale_por_s": prazo_s,
        "instrucao": ("NADA foi executado. O SISTEMA acrescenta ao fim da sua resposta o resumo exato da ação e "
                      "o pedido da SENHA DE ATUAÇÃO: diga em uma linha o que será feito e não repita o resumo. "
                      "Nunca peça a senha de login, nunca escreva nem invente senha, nunca diga que fez."),
    }


def bloco_da_proposta(p: Pendente) -> str:
    """O que a pessoa confirma — escrito pelo sistema, palavra por palavra."""
    sim = p.confirmacao == "sim"
    linhas = ["📋 *Ação no meuPlano esperando a sua confirmação*" if sim else "🔒 *Ação esperando a sua senha de atuação*",
              _escopo(p)]
    linhas.append(f"Para fazer, toque em *Sim* (ou responda SIM) até as {_limite(p)}. Um não, uma correção ou "
                  "outro assunto cancela; na dúvida, pergunto de novo." if sim else
                  f"Para executar, responda só com a senha até as {_limite(p)}. Qualquer outra mensagem cancela.")
    return "\n".join(linhas)


def _escopo(p: Pendente) -> str:
    """O resumo, as linhas e os avisos da ação — o que um Sim faz."""
    return "\n".join([f"• {p.resumo}", *(f"  – {d}" for d in p.detalhes), *(f"⚠️ {a}" for a in p.avisos)])


def _limite(p: Pendente) -> str:
    """A hora-limite, e não "em até 2 min": o prazo corre desde a proposta, e a IA leva de 17 a
    65 s para responder. Da ação vencida, a hora em que venceu."""
    return f"{datetime.now(BRT) + timedelta(seconds=p.expira - monotonic()):%H:%M}"


def mostrada(user_id: int, agora: datetime | None = None) -> None:
    """O resumo da ação saiu para a pessoa: a partir de AGORA a senha dela vale. `agora` é a hora
    do BANCO (`assistente._agora_do_banco`): a deste servidor anda ~17 s atrasada, e é com a hora
    da Meta — a certa — que a senha é comparada."""
    p = PENDENTES.get(user_id)
    if p is not None and p.mostrada_em is None:
        p.mostrada_em = (monotonic(), agora or datetime.now(UTC))


def _antes_do_resumo(p: Pendente, chegou: float | None, mandada_em: datetime | None) -> bool:
    """A senha saiu do celular antes de o resumo chegar — a pessoa não sabia o que confirmava.
    Duas provas, porque cada uma falha de um jeito:
    - `chegou` (relógio daqui, ao entrar na fila do número) antes da saída do resumo: o caso
      comum — "desliga o 13" e a senha logo atrás, esperando a vez enquanto a IA pensa;
    - `mandada_em` (a hora da Meta) antes da saída do resumo, na hora do BANCO: pega a que
      chegou tarde (o gateway reenviando pela varredura)."""
    if p.mostrada_em is None:
        return True
    saiu, saiu_utc = p.mostrada_em
    return (chegou is not None and chegou < saiu) or (mandada_em is not None and mandada_em < saiu_utc)


_catalogo: tuple[float, dict[str, Any]] | None = None


def configurado() -> bool:
    s = get_settings()
    return bool(s.helper_bot_url and s.helper_bot_chave)


async def alcancavel() -> tuple[bool | None, str]:
    """Se o helper responde agora (túnel + filtro + serviço). `None` = não configurado aqui.
    Usa o `ferramentas`, que só confere a chave do chamador: a plataforma não tem token."""
    if not configurado():
        return None, "O helper não está configurado neste ambiente."
    s = get_settings()
    bot = HelperBot(s.helper_bot_url, s.helper_bot_chamador, s.helper_bot_chave, "")
    d = await bot.ferramentas(espera_s=6)
    if not d.get("ok"):
        return False, f"Helper fora do alcance do bot: {d.get('error') or d.get('reason') or 'sem resposta'}"
    # O túnel responder não prova que as USINAS respondem: o Modbus sai pela VPN do servidor do
    # helper, e ela ficou 11 h sem contato em 24/10/2026 com este selo verde.
    rede = await bot.rede()
    idade = rede.get("vpn_ultimo_contato_s")
    if not rede.get("ok"):
        return False, f"{_HELPER_RESPONDE} {_VPN_NAO_CONFERIDA}."
    if idade is None:
        return False, f"{_HELPER_RESPONDE} a rede até as usinas (VPN) nunca fez contato."
    if idade > VPN_PARADA_S:
        return False, (f"{_HELPER_RESPONDE} a rede até as usinas (VPN) está sem contato há {_duracao(idade)}: "
                       "leitura e comando de equipamento não chegam lá.")
    return True, "Helper e rede das usinas no ar: o bot lê e comanda as usinas por ele."


_HELPER_RESPONDE = "Helper responde, mas"
_VPN_NAO_CONFERIDA = "não deu para conferir a rede até as usinas (VPN)"


def rotulo_do_helper(alcancavel: bool | None, resumo: str | None) -> str | None:
    """A CAUSA, curta, para o selo e a linha de cada pessoa: "Helper fora do ar" quando era a VPN
    mandava o gerente procurar no lugar errado (avaliação 17). `None` = sem problema a mostrar."""
    if alcancavel is not False:
        return None
    if not (resumo or "").startswith(_HELPER_RESPONDE):
        return "Helper fora do ar"
    return "VPN das usinas não conferida" if _VPN_NAO_CONFERIDA in resumo else "VPN das usinas parada"


#: O wg0 renova o contato a cada 25 s (PersistentKeepalive); 5 min sem contato é rede parada.
VPN_PARADA_S = 300


def _duracao(segundos: int) -> str:
    return f"{segundos // 3600} h" if segundos >= 3600 else f"{max(1, segundos // 60)} min"


#: O último contato da VPN das usinas conferido (instante da conferência, contato em UTC ou None se não deu para
#: conferir): uma ida ao filtro do túnel por minuto, não uma por chamada.
_VPN: tuple[float, datetime | None] | None = None
#: As rotas do helper que não vão ao equipamento (o cadastro e a trilha guardados nele): valem com a VPN parada.
_ROTAS_LOCAIS = ("/api/registry/", "/api/audit/")


async def _vpn_parada(cliente: HelperBot) -> str | None:
    """A frase para a IA quando a VPN das usinas está parada (`VPN_PARADA_S`); None se está no ar ou se não deu para
    conferir (aí a chamada segue e o helper diz o que houve). 26/10/2026: com a VPN parada desde 23/10, a IA tentou 18
    rotas do helper em 4 minutos, uma por vez, e a pessoa leu "a pergunta ficou grande demais"."""
    global _VPN
    if _VPN is None or monotonic() - _VPN[0] > 60:
        try:
            r = await cliente.rede()
        except Exception:  # noqa: BLE001 (sem a conferência, a chamada segue)
            r = {}
        idade = r.get("vpn_ultimo_contato_s") if r.get("ok") else None
        _VPN = (monotonic(), datetime.now(UTC) - timedelta(seconds=idade) if isinstance(idade, (int, float)) else None)
    contato = _VPN[1]
    if contato is None or (datetime.now(UTC) - contato).total_seconds() <= VPN_PARADA_S:
        return None
    idade = int((datetime.now(UTC) - contato).total_seconds())
    return (f"A VPN das usinas está sem contato desde {hora_brt(contato.isoformat())} (há {_duracao(idade)}): o helper "
            "não alcança os equipamentos agora, nem para ler. Diga isso à pessoa e não tente outra rota do helper; "
            "geração e paradas seguem pelo monitoramento do meuWatt.")


def _cliente(ctx_ou_db, user) -> HelperBot:
    from app.models.integracao import Produto
    from app.services.vinculos import token_do_cliente

    db = getattr(ctx_ou_db, "db", ctx_ou_db)
    s = get_settings()
    return HelperBot(
        s.helper_bot_url, s.helper_bot_chamador, s.helper_bot_chave,
        token_do_cliente(db, user.id, Produto.MEUWATT, so_proprio=True),
    )


def _enxuga(v: Any) -> Any:
    """Item de lista fica só com os campos simples (id, nome, slug…)."""
    if isinstance(v, dict):
        return {k: _enxuga(x) for k, x in v.items()}
    if isinstance(v, list):
        return [{k: x for k, x in i.items() if not isinstance(x, (dict, list))} if isinstance(i, dict) else i
                for i in v]
    return v


def _corta(dados: Any) -> Any:
    """Cabe no modelo. O `/api/registry/plants` tem ~18 mil caracteres por 6 usinas (gateways,
    alvos): cortado no meio, o bot perdia as últimas usinas e o status. Grande, as listas
    perdem o aninhado — o detalhe de UM item se pede na rota dele."""
    import json

    if len(json.dumps(dados, ensure_ascii=False, default=str)) <= TETO_RESPOSTA:
        return dados
    enxuto = _enxuga(dados)
    texto = json.dumps(enxuto, ensure_ascii=False, default=str)
    if len(texto) <= TETO_RESPOSTA:
        return {**enxuto, "aviso": "Resposta grande: campos aninhados omitidos; peça o detalhe pela rota do item."}
    return {"status_http": dados.get("status_http"), "resposta_cortada": texto[:TETO_RESPOSTA]}


async def usina_helper_catalogo(ctx: ger.Contexto, a: dict) -> dict:
    """As rotas do helper (iguais para todo mundo): guardadas 10 min."""
    from app.services.vinculos import SemConexao

    global _catalogo
    if _catalogo is None or monotonic() - _catalogo[0] > 600:
        try:
            d = await _cliente(ctx, ctx.user).ferramentas()
        except SemConexao as e:
            return {"erro": f"Helper indisponível: {e}"}
        if not d.get("ok"):
            return {"erro": d.get("error") or d.get("reason") or "O helper não respondeu."}
        _catalogo = (monotonic(), {k: d.get(k) for k in ("rotas", "leitura_post", "escrita", "bloqueadas")})
    return _catalogo[1]


#: Campos que trazem o SLUG da usina num item de resposta do helper (o `plant_id` dele é o
#: slug; `plant`, o da trilha de auditoria `/api/audit/list` e dos mapas de bits do ABS —
#: avaliação 15). Nome de exibição não entra: "Pirapozinho" não é "pirapozinho" e o item sumiria.
_CAMPOS_DE_USINA = ("api_slug", "slug", "plant_id", "plant")


def _so_liberadas(dados: Any, liberadas: set[str]) -> Any:
    """Tira das listas os itens de usina fora do recorte (o item que diz a usina num campo de
    texto que não está em `liberadas`). O resto da resposta fica como veio."""
    if isinstance(dados, dict):
        return {k: _so_liberadas(v, liberadas) for k, v in dados.items()}
    if isinstance(dados, list):
        saida = []
        for item in dados:
            if isinstance(item, dict) and any(
                isinstance(item.get(c), str) and item[c] and item[c] not in liberadas for c in _CAMPOS_DE_USINA
            ):
                continue
            saida.append(_so_liberadas(item, liberadas))
        return saida
    return dados


def _usinas_pedidas(rota: str, corpo: dict) -> set[str]:
    """As usinas que o pedido toca (`slug`, `plant_id`, `slugs`, e o mesmo na query do GET)."""
    from urllib.parse import parse_qs, urlsplit

    nomes = [corpo.get("slug"), corpo.get("plant_id"), *(corpo.get("slugs") or [])]
    for k, v in parse_qs(urlsplit(rota).query).items():
        if k in ("slug", "plant_id", "slugs"):
            nomes += v
    return {str(n).strip() for n in nomes if n not in (None, "")}


def _tem_alvo(rota: str, corpo: dict) -> bool:
    """O pedido aponta um equipamento pelo endereço (`ip`, `ips`, `host`). Sem a usina junto, o
    helper confere o IP contra TODAS as usinas do token — mais do que o Gestão Solar liberou."""
    from urllib.parse import parse_qs, urlsplit

    consulta = parse_qs(urlsplit(rota).query)
    return any(corpo.get(k) or consulta.get(k) for k in ("ip", "ips", "host"))


async def usina_helper(ctx: ger.Contexto, a: dict) -> dict:
    rota = (a.get("rota") or "").strip()
    if not rota.startswith("/api/"):
        return {"erro": "Informe a rota do helper, começando com /api/ (veja usina_helper_catalogo)."}
    corpo = a.get("corpo") if isinstance(a.get("corpo"), dict) else {}
    # GET é leitura no helper (o catálogo `/api/devices`, `/api/healthcheck/state?id=…`): POST
    # numa rota GET virava "escrita", pedia senha e dava 404 (avaliação de 24/10/2026).
    metodo = "GET" if str(a.get("metodo") or "").upper() == "GET" else "POST"
    # O recorte do Gestão Solar vale aqui também: o token do meuWatt pode enxergar mais usinas
    # do que o gerente (ou o dono) liberou para esta conta.
    liberadas = {p.mw_plant_slug for p in ger.usinas_do_bot(ctx.db, ctx.user) if p.mw_plant_slug}
    pedidas = _usinas_pedidas(rota, corpo)
    if not pedidas and _tem_alvo(rota, corpo):
        return {"erro": ("Equipamento pelo IP só com a usina junto: mande também o slug (ou plant_id) da usina. "
                         "O bot só fala com equipamento de usina liberada para esta pessoa.")}
    fora = pedidas - liberadas
    if fora:
        return {"erro": f"Usina não liberada para você no Gestão Solar: {', '.join(sorted(fora))}."}
    from app.services.vinculos import SemConexao

    try:
        cliente = _cliente(ctx, ctx.user)
    except SemConexao as e:
        return {"erro": f"Helper indisponível: {e}"}
    if not rota.startswith(_ROTAS_LOCAIS) and (parada := await _vpn_parada(cliente)):
        return {"erro": parada, "motivo": "vpn_parada"}
    ctx.db.commit()                                       # solta a conexão enquanto o helper lê
    d = await cliente.chamar(rota, corpo, origem=f"whatsapp {ctx.telefone}", metodo=metodo)
    if not d.get("ok"):
        return {"erro": d.get("error") or d.get("reason") or "O helper recusou.", "motivo": d.get("reason")}
    if d.get("tipo") == "leitura":
        # Leitura que não nomeia a usina (`/api/alarms/feed`, a lista de usinas…) volta com o
        # que o TOKEN enxerga: os itens de usina fora do recorte do Gestão Solar saem aqui.
        d["resposta"] = _so_liberadas(d.get("resposta"), liberadas)
    if d.get("tipo") == "proposta":
        proposta, resumo = d["proposta"], d.get("resumo") or rota

        async def executar(db, user, telefone: str) -> str:
            try:
                cliente = _cliente(db, user)
            except SemConexao as e:
                return f"❌ Não executado: {e}"
            db.commit()                                   # o lote pode levar até ~150 s
            return _desfecho(resumo, await cliente.confirmar(proposta, "pin", f"whatsapp {telefone}"))

        return propor(ctx, resumo, int(d.get("expira_em_s") or 120), executar)
    return _corta({"status_http": d.get("status_http"), "resposta": d.get("resposta")})


_ESTADO = {"ok": "✅ confirmado", "ja": "já estava", "falhou": "❌ falhou", "incerto": "⚠️ incerto",
           "nao_enviado": "não enviado"}


def _desfecho(resumo: str, r: dict) -> str:
    """O que o helper fez, em texto de WhatsApp — o ajuste em massa item por item, com a
    conferência da leitura final (o "OLHE, deu certo" da tela)."""
    if r.get("incerto") and not r.get("resultado"):
        return (f"⚠️ {resumo}: sem resposta, e a ação PODE ter chegado. Confira a leitura antes de repetir. "
                f"{r.get('error') or ''}").strip()
    res = r.get("resultado")
    if isinstance(res, dict) and res.get("itens"):
        linhas = [f"• {i.get('nome')} {i.get('sigla') or i.get('campo')}: {i.get('antes')} → {i.get('valor')} "
                  f"{i.get('unidade') or ''}: {_ESTADO.get(i.get('st'), i.get('st'))}".replace("  ", " ")
                  for i in res["itens"]]
        if (res.get("conferencia") or {}).get("tudo_confirmado"):
            fim = "✅ A leitura final confere com tudo."
        elif r.get("acompanhe"):
            fim = "⏳ O envio ainda não terminou. Peça o andamento em instantes."
        else:
            fim = "⚠️ A leitura final NÃO confere em tudo. Veja os itens."
        return "\n".join([f"{resumo}:", *linhas, fim])
    if r.get("reason") == "proposta_inexistente":
        return ("⌛ O pedido expirou no helper (ele vale 2 minutos). Nada foi feito. Peça de novo e mande "
                "a senha logo em seguida.")
    releitura = _leitura_curta((r.get("releitura") or {}).get("resposta"))
    if not r.get("ok"):
        resposta = r.get("resposta") if isinstance(r.get("resposta"), dict) else {}
        motivo = r.get("error") or resposta.get("error") or r.get("reason") or ""
        texto = f"❌ Não executado: {resumo}. {motivo}".strip()
    else:
        texto = f"✅ Executado: {r.get('resumo') or resumo}."
    return texto + (f"\nReleitura do equipamento: {releitura}" if releitura else "")


#: Chaves de leitura que não dizem nada a quem lê no celular.
_RUIDO = {"ok", "raw", "regs", "registers", "hex", "bytes", "debug", "ms", "duracao_ms", "host", "port", "slave"}


def _leitura_curta(dados: Any, limite: int = 10) -> str:
    """A releitura em uma linha: até `limite` valores simples (`chave: valor`). O formato de
    cada driver é dele; aqui só se evita mandar o JSON cru ao WhatsApp."""
    pares: list[str] = []

    def andar(v: Any, prefixo: str = "") -> None:
        if len(pares) >= limite:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                if str(k).lower() not in _RUIDO:
                    andar(x, f"{prefixo}{k}" if not prefixo else f"{prefixo}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v[:limite]):
                andar(x, f"{prefixo}[{i}]")
        elif v is not None and prefixo:
            pares.append(f"{prefixo}: {v}")

    if isinstance(dados, dict) and dados.get("ok") is False:
        return f"falhou: {dados.get('error') or 'sem detalhe'}"
    andar(dados)
    return " · ".join(pares)


async def confirmar_por_mensagem(db, user, telefone: str, texto: str, analise: Analise | None = None,
                                 esperava: bool = False, chegou: float | None = None,
                                 mandada_em: datetime | None = None, tentativa: bool | None = None) -> str | None:
    """A mensagem que é APENAS a senha de atuação → executa a ação esperando. `None` = segue
    para a conversa (com os candidatos já escondidos por quem chama).

    Quem chama (`assistente._atender`) DESARMA a ação antes, em toda mensagem que não é só a
    senha — frase, "limpar", áudio, imagem: "qualquer outra mensagem cancela" é o que o bloco
    da ação promete, e "não faça! senha 482913" executava (avaliação de 24/10/2026).

    - Bloqueada: a tentativa recebe `BLOQUEADO`, certa ou errada.
    - Certa: executa — se a parte do bot ainda estiver ligada —, ou `NADA_ESPERANDO`. Certa mas
      mandada ANTES de o resumo da ação chegar (`chegou`: quando entrou na fila do número;
      `mandada_em`: a hora da Meta): não vale, e a ação continua esperando (avaliação 10 —
      "desliga o 13" e a senha logo atrás executavam um resumo que a pessoa nunca leu).
    - Errada: conta; `TENTATIVAS` erros bloqueiam por `BLOQUEIO_S`. Sem ação esperando, a frase
      é a mesma da certa.
    - "não"/"cancela" com uma ação que acabou de ser desarmada: `CANCELADO`, pelo sistema."""
    if responde_sim(user.id, texto):
        p = PENDENTES[user.id]
        if monotonic() > p.expira:
            PENDENTES.pop(user.id, None)
            return VENCEU.format(limite=_limite(p))
        if _antes_do_resumo(p, chegou, mandada_em):
            return ANTES_DO_RESUMO_SIM.format(limite=_limite(p))
        PENDENTES.pop(user.id, None)                       # uma vez só, aconteça o que acontecer
        return await _rodar(p, db, user, telefone)
    # `tentativa` vem de quem chama, decidida ANTES de desarmar: depois, a ação do meuPlano já não
    # está esperando e o número da conversa viraria tentativa de senha.
    if not (e_tentativa(user, texto) if tentativa is None else tentativa):
        return CANCELADO if esperava and so_cancela(texto) else None
    analise = analise or await analisar(user, texto)
    pendente, vencida = PENDENTES.get(user.id), None
    if pendente is not None and monotonic() > pendente.expira:
        vencida, pendente = PENDENTES.pop(user.id, None), None
    sem_acao = VENCEU.format(limite=_limite(vencida)) if vencida else NADA_ESPERANDO
    if not user.senha_atuacao_hash:
        return SEM_SENHA if pendente is not None or COM_PALAVRA.match(texto or "") else None
    if analise.bloqueada:
        return BLOQUEADO
    if analise.acertou:
        if pendente is None:
            return sem_acao
        if _antes_do_resumo(pendente, chegou, mandada_em):
            return ANTES_DO_RESUMO.format(limite=_limite(pendente))
        PENDENTES.pop(user.id, None)      # uma vez só, aconteça o que acontecer
        _ERROS.pop(user.id, None)
        return await _rodar(pendente, db, user, telefone)
    total = _contar_falhas(user.id, 1)
    if total >= TENTATIVAS:
        return (f"Senha errada {TENTATIVAS} vezes: " + ("o pedido foi descartado e " if pendente else "")
                + f"as ações ficam bloqueadas por {BLOQUEIO_S // 60} min. Nada foi feito.")
    return f"Senha não confere ({total} de {TENTATIVAS}). Nada foi feito." if pendente else sem_acao


_ROTA = {"type": "string", "description": "Rota do helper, ex.: /api/registry/plants, /api/registry/devices, "
         "/api/read, /api/healthcheck/start, /api/alarms/feed, /api/abs/status; GET com a consulta na própria "
         "rota: /api/devices, /api/healthcheck/state?id=<id>."}

FERRAMENTAS = {
    "usina_helper_catalogo": (usina_helper_catalogo, {"type": "function", "function": {
        "name": "usina_helper_catalogo",
        "description": ("O que dá para pedir ao helper (a ferramenta de campo que fala com os equipamentos da "
                        "usina): rotas de leitura, de escrita e exemplos de corpo. Chame quando não souber a rota."),
        "parameters": {"type": "object", "properties": {}}}}),
    "usina_helper": (usina_helper, {"type": "function", "function": {
        "name": "usina_helper",
        "description": ("A USINA AO VIVO pelo helper: os equipamentos via Modbus (inversores, relés, SmartLogger, "
                        "caixas ABS, térmica): ler, testar a comunicação (healthcheck), alarmes. Comece por "
                        "/api/registry/plants (libera as usinas da pessoa) e /api/registry/devices {slug}. "
                        "AJUSTE EM MASSA (mesmos parâmetros em vários relés): /api/massa/plano {slug, plant_id} lê; "
                        "com valores e selecionados devolve o plano (mostre-o); /api/massa/start com o MESMO corpo "
                        "vira UMA ação para o lote; /api/massa/state {job} dá o andamento. "
                        "Pedido com IP/host de equipamento leva SEMPRE o slug da usina junto. "
                        "AÇÃO (ajustar, ligar, desligar, resetar, comandar, gravar) NÃO é executada: volta uma "
                        "proposta, e só roda com a SENHA DE ATUAÇÃO que a pessoa manda."),
        "parameters": {"type": "object", "properties": {
            "rota": _ROTA,
            "metodo": {"type": "string", "enum": ["POST", "GET"],
                       "description": "POST (padrão) ou GET: use o método que o catálogo diz para a rota. "
                                      "GET é sempre leitura: /api/devices (os comandos e ações de cada equipamento), "
                                      "/api/healthcheck/state?id=<id> (o resultado do teste de comunicação)."},
            "corpo": {"type": "object", "description": "O JSON que a tela da web mandaria (ex.: {\"slug\": \"pirapozinho\"})."},
        }, "required": ["rota"]}}}),
}
