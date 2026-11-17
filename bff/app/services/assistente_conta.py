"""Conta de energia pelo WhatsApp (pedido do Renan, 17/11/2026: "enviar uma conta de energia, falar a usina, o bot
analisar e enviar a prova, mostrando os valores lado a lado, da conta e o que ele retirou; se o usuário aceitar, o bot
salva a conta de energia no projeto e o relatório já é atualizado"; e "veja as contas que temos e use-as como exemplo").

- O PDF é o que a pessoa mandou (`assistente_pdf`, guardado 30 min). Com senha (a da distribuidora, o CPF/CNPJ parcial
  do titular), a que a pessoa escreveu: a do meuWatt não se lê (o cliente não tem a rota da senha, de propósito).
- Ler: as linhas de cada página remontadas pela posição das letras (pdfium; a Elektro solta os rótulos de um lado e os
  números do outro) e lidas pela IA, que copia cada valor COMO ESTÁ IMPRESSO. Quem confere e soma é o código, e nada se
  salva sem: a UC que a usina já tem no meuWatt impressa na conta (a IA trocava pelo "Seu código" do boleto da Elektro);
  cada número na linha de energia INJETADA do rótulo (conta digital); a leitura do medidor × a constante dando o
  consumo (na conta digitalizada, sem texto, é a conferência que existe); nenhum posto repetido; e o período de leitura
  impresso, de 20 a 40 dias.
- A regra das contas que já estavam no meuWatt (as 5 usinas, 17/11/2026): o MWh da conta é a energia INJETADA medida
  no período (ponta + fora ponta; na CEMIG, HFP + HP), nunca a compensada. O mês é o do MEIO do período de leitura: a
  conta "Outubro/2026" da Elektro lê de 31/08 a 30/09 (setembro), e a de 31/08 a 01/10 também é setembro (pela leitura
  atual, cairia em outubro e setembro ficaria vazio; avaliação de 17/11/2026).
- A prova é UMA imagem por conta: cada valor recortado da conta ao lado do que o bot leu. O Sim grava no meuWatt
  (Projeto › Faturas, pelo salvar de lá, com o token DA PESSOA: só o administrador da usina grava valores), relendo a
  conta na hora (o que ela já tem fica; titular e tarifa nunca vêm da IA), com o PDF como nova versão. O relatório de
  geração lê dali: a resposta diz o que ele mostra agora e, se o PDF do mês já foi emitido, que esse PDF fica com o
  valor antigo até a equipe gerar de novo.
"""

import asyncio
import base64
import io
import json
import logging
import os
import re
import statistics
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from app.clients import whatsapp
from app.services import assistente_helper as helper
from app.services import assistente_pdf as pdf

log = logging.getLogger(__name__)

PRAZO_S = 600
TETO_PDFS = 6
TETO_PAGINAS = 8
#: Menos texto que isso no PDF inteiro = conta digitalizada: a IA lê a imagem das páginas.
MINIMO_DE_TEXTO = 300
#: A página desenhada para a prova (216 dpi): o número miúdo da conta fica legível no recorte.
ESCALA = 3
#: A thread única do PDFium (`no_pdfium`).
_PDFIUM = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdfium")
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


# --------------------------------------------------------------------------- números e datas como a conta imprime
def numero(texto: Any) -> float | None:
    """"143.500" (milhar), "1,5" (vírgula), ".42" e "1.68" (o ponto decimal das constantes da Elektro)."""
    t = re.sub(r"\s", "", str(texto or "")).removeprefix("+")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):
        return float(t.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d+(,\d+)?", t):
        return float(t.replace(",", "."))
    if re.fullmatch(r"-?\d*\.\d+", t):
        return float(t)
    return None


def br(valor: float, casas: int = 0) -> str:
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _digitos(t: Any) -> str:
    return re.sub(r"\D", "", str(t or ""))


def _norm(t: Any) -> str:
    sem = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", sem).strip()


def _data(texto: Any) -> tuple[int, int, int | None] | None:
    """(dia, mês, ano ou None) da 1ª data do texto: "31/08/2026", "31/08" (a CEMIG não imprime o ano ali)."""
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}))?\b", str(texto or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None) if m else None


def periodo(dados: dict) -> tuple[tuple[int, int] | None, str | None]:
    """(ano, mês) da energia e o problema, se houver. O mês é o do MEIO do período de leitura: a Elektro às vezes lê no
    dia 1º, e a conta de 31/08 a 01/10 cairia em outubro pela leitura atual, deixando setembro vazio (avaliação de
    17/11/2026). Período fora de 20 a 40 dias não é o de uma conta: a IA pegou outra data (o vencimento, a próxima
    leitura)."""
    a, b = _data(dados.get("leitura_anterior")), _data(dados.get("leitura_atual"))
    if not a or not b:
        return None, "não achei as duas datas de leitura (a anterior e a atual)"
    ano_b = b[2] or (a[2] + (1 if b[1] < a[1] else 0) if a[2] else None)
    ano_a = a[2] or (ano_b - (1 if a[1] > b[1] else 0) if ano_b else None)
    if not ano_a or not ano_b:
        return None, "as datas de leitura não trazem o ano"
    try:
        inicio, fim = date(ano_a, a[1], a[0]), date(ano_b, b[1], b[0])
    except ValueError:
        return None, f"as datas de leitura «{dados.get('leitura_anterior')}» e «{dados.get('leitura_atual')}» não são datas"
    dias = (fim - inicio).days
    if not 20 <= dias <= 40:
        return None, f"o período de leitura de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} tem {dias} dias: não é o de uma conta"
    meio = inicio + (fim - inicio) / 2
    return (meio.year, meio.month), None


def _referencia(texto: Any) -> tuple[int, int] | None:
    """(ano, mês) do mês de referência como a conta imprime: "Outubro/2026", "SET/2026", "10/2026"."""
    t = _norm(texto)
    m = re.search(r"\b(\d{1,2})[/.](\d{4})\b", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"\b([a-z]{3})[a-z]*\W*(\d{4})\b", t)
    if m and m.group(1) in MESES:
        return int(m.group(2)), MESES.index(m.group(1)) + 1
    return None


def _mes_br(am: tuple[int, int]) -> str:
    return f"{MESES[am[1] - 1]}/{am[0]}"


# --------------------------------------------------------------------------- o PDF
class SemSenha(Exception):
    """O PDF tem senha e nenhuma das conhecidas o abriu."""


@dataclass
class Linha:
    pagina: int                                           # 0, 1, …
    texto: str
    #: (texto, x0, y0, x1, y1) de cada palavra, em pontos do PDF (y para cima)
    palavras: list[tuple[str, float, float, float, float]]


@dataclass
class Documento:
    """O PDF já lido: o arquivo, a senha que o abriu e as linhas. Nenhum objeto do PDFium fica vivo aqui."""
    conteudo: bytes
    senha: str | None
    paginas: int
    linhas: list[Linha]

    @property
    def digital(self) -> bool:
        return sum(len(x.texto) for x in self.linhas) >= MINIMO_DE_TEXTO


async def no_pdfium(fn, *args):
    """Todo uso do PDFium numa thread SÓ: ele não aguenta duas ao mesmo tempo, e o erro derrubaria o processo da API
    inteira (o bot e o aplicativo). Cada função fecha o que abriu: nada do PDFium sobra para o coletor de lixo fechar em
    outra thread. ponytail: uma conta por vez no processo; é rápido (< 1 s por conta)."""
    return await asyncio.get_running_loop().run_in_executor(_PDFIUM, fn, *args)


def abrir(conteudo: bytes, senhas: list[str]) -> Documento:
    """Abre sem senha e, se pedir, com cada senha conhecida; as linhas saem já montadas (`_linhas`). Rode por
    `no_pdfium`."""
    import pypdfium2 as pdfium

    for senha in [None, *dict.fromkeys(s for s in senhas if s)]:
        try:
            doc = pdfium.PdfDocument(conteudo, password=senha)
        except pdfium.PdfiumError as e:
            if "password" not in str(e).lower():
                raise ValueError("o arquivo não abre como PDF") from e
            continue
        try:
            n, linhas = min(len(doc), TETO_PAGINAS), []
            for i in range(n):
                pagina = doc[i]
                try:
                    linhas += _linhas(pagina, i)
                finally:
                    pagina.close()
            return Documento(conteudo, senha, n, linhas)
        finally:
            doc.close()
    raise SemSenha


def _linhas(pagina, n: int) -> list[Linha]:
    """As linhas da página pela POSIÇÃO de cada letra, como o `pdftotext -layout`: o texto corrido do pdfium solta a
    tabela da Elektro em colunas (os rótulos de um lado, os números do outro) e a IA não sabia qual número era de qual
    linha. Letras com o centro na mesma altura são uma linha; um vão maior que 1/4 da altura separa as palavras."""
    tp = pagina.get_textpage()
    try:
        letras = []
        for i in range(tp.count_chars()):
            c = tp.get_text_range(i, 1)
            if c.strip():
                letras.append((c, *tp.get_charbox(i, loose=True)))
    finally:
        tp.close()
    if not letras:
        return []
    grupos: list[list] = []                               # [centro, letras, altura]
    for c in sorted(letras, key=lambda c: (-(c[2] + c[4]) / 2, c[1])):
        meio, alto = (c[2] + c[4]) / 2, c[4] - c[2]
        junto = next((g for g in grupos[-3:] if abs(g[0] - meio) <= 0.3 * max(alto, g[2])), None)
        if junto:
            junto[1].append(c)
        else:
            grupos.append([meio, [c], alto])
    largura = statistics.median(c[3] - c[1] for c in letras) or 4
    saida = []
    for _, cs, _ in grupos:
        cs.sort(key=lambda c: c[1])
        blocos, atual = [], [cs[0]]
        for c in cs[1:]:
            if c[1] - atual[-1][3] > 0.25 * (c[4] - c[2]):
                blocos.append(atual)
                atual = [c]
            else:
                atual.append(c)
        blocos.append(atual)
        palavras = [("".join(c[0] for c in b), b[0][1], min(c[2] for c in b), b[-1][3], max(c[4] for c in b))
                    for b in blocos]
        texto, fim = "", None
        for p in palavras:
            if fim is not None:
                texto += " " if p[1] - fim <= 1.5 * largura else "   "
            texto += p[0]
            fim = p[3]
        saida.append(Linha(n, texto, palavras))
    return saida


def desenhar(d: Documento, quais: list[int], escala: float) -> dict[int, Any]:
    """As páginas pedidas como imagens PIL (cópias: o bitmap do PDFium é fechado aqui). Rode por `no_pdfium`."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(d.conteudo, password=d.senha)
    try:
        saida = {}
        for i in quais:
            if not 0 <= i < d.paginas:
                continue
            pagina = doc[i]
            try:
                bitmap = pagina.render(scale=escala)
                try:
                    saida[i] = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                pagina.close()
        return saida
    finally:
        doc.close()


def _imagens(d: Documento) -> list[bytes]:
    """As páginas da conta digitalizada para a IA ler (144 dpi). Rode por `no_pdfium`."""
    out = []
    for _, img in sorted(desenhar(d, list(range(d.paginas)), 2).items()):
        b = io.BytesIO()
        img.save(b, "PNG")
        out.append(b.getvalue())
    return out


# --------------------------------------------------------------------------- a leitura pela IA
PROMPT = """Você lê a CONTA DE ENERGIA (fatura da distribuidora) de uma usina solar de GERAÇÃO. Responda SÓ um objeto JSON:
{"distribuidora": str|null, "uc": str|null, "titular": str|null, "referencia": str|null, "leitura_anterior": str|null,
 "leitura_atual": str|null, "injetada": [{"posto": str, "rotulo": str, "kwh": str, "leitura_anterior": str|null,
 "leitura_atual": str|null, "constante": str|null, "pagina": int}]}
Regras:
- Copie cada valor EXATAMENTE como está impresso (mesmos pontos, vírgulas, barras e espaços). Não converta nem some nada.
- "uc": o número da instalação / unidade consumidora (Elektro: 9.999.999.999-99 no alto da 1ª página; CEMIG: "N.º da
  Unidade Consumidora"), nunca o código do cliente nem o do boleto. "referencia": o mês de referência, como impresso.
- "leitura_anterior" e "leitura_atual": as DATAS do período de leitura ou de medição (Elektro: "LEITURA ANTERIOR" e
  "LEITURA ATUAL"; CEMIG: "Período de Medição", que traz o ano), com o ano se a conta o trouxer. Nunca o vencimento, a
  data de emissão nem a próxima leitura.
- "injetada": a energia INJETADA MEDIDA no período, uma linha por posto horário (ponta, fora ponta, reservado ou único),
  do demonstrativo de leituras ou de medição. Na Neoenergia Elektro: as linhas "ENERGIA INJETADA PT" e "ENERGIA INJETADA
  FP" do demonstrativo de consumo (leitura de, leitura até, constante e, por último, o consumo do período em kWh, que é o
  "kwh"). Na CEMIG: "Energia Injetada" de cada segmento (HFP/único, HP, HR) no quadro ENERGIA (kWh), coluna Registrado
  (nunca a coluna Faturado), com as leituras da linha "kWh Injet." do mesmo segmento e a constante "kWh" do quadro
  CONSTANTES. NUNCA a energia compensada, o saldo ou crédito, nem os itens faturados com quantidade negativa (ex.:
  "ENERGIA INJETADA PT TE 09/2026 GDI-I ... -79"). TODOS os postos com número impresso entram (na CEMIG, o HFP E o
  HP), cada um uma vez só; posto sem número impresso não entra.
  "rotulo": o nome da linha como impresso.
- "pagina": a página da linha (as páginas vêm marcadas "=== Página N ===" ou, em imagem, na ordem).
- O que não está na conta: null. Nada de texto fora do JSON."""


async def extrair(d: Documento) -> dict:
    """O que a IA leu, com cada valor como impresso. A conta (a soma, o MWh, o mês) é do código, não dela."""
    from app.services.assistente import _llm
    if d.digital:
        paginas: dict[int, list[str]] = {}
        for x in d.linhas:
            paginas.setdefault(x.pagina, []).append(x.texto)
        texto = "\n".join(f"=== Página {n + 1} ===\n" + "\n".join(ls) for n, ls in sorted(paginas.items()))
        conteudo: Any = f"{PROMPT}\n\nA conta, linha a linha:\n{texto[:60000]}"
    else:
        imagens = await no_pdfium(_imagens, d)
        conteudo = [{"type": "text", "text": PROMPT + "\n\nA conta, página a página, em imagens:"}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}}
            for b in imagens]
    msg = await _llm([{"role": "user", "content": conteudo}], [], teto_s=170)
    s = msg.get("content") or ""
    try:
        dados = json.JSONDecoder().raw_decode(s[s.index("{"):])[0]
    except ValueError:
        raise ValueError("a IA não devolveu a leitura da conta") from None
    if not isinstance(dados, dict):
        raise ValueError("a IA não devolveu a leitura da conta")
    return dados


# --------------------------------------------------------------------------- conferir
@dataclass
class Leitura:
    nome: str
    conteudo: bytes
    doc: Documento
    dados: dict
    usina: dict | None = None                             # {"slug", "nome", ...} de `ctx.usinas`
    uc: str | None = None                                 # como o meuWatt a escreve
    trafo: dict | None = None                             # {"id", "nome"}
    mes: tuple[int, int] | None = None                    # (ano, mês) da energia
    #: {"posto", "rotulo", "impresso", "kwh", "onde" (página, caixa do rótulo, caixa do número) | None,
    #:  "medidor" (True/False/None), "conta" (a conta do medidor escrita) | None}
    postos: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)       # o que impede salvar
    notas: list[str] = field(default_factory=list)        # o que a pessoa confere na prova
    atual: dict | None = None                             # a conta desta UC e mês que já está no meuWatt

    @property
    def total_kwh(self) -> float | None:
        return sum(p["kwh"] for p in self.postos) if self.postos else None

    @property
    def mwh(self) -> float | None:
        return round(self.total_kwh / 1000, 3) if self.total_kwh is not None else None

    @property
    def pronta(self) -> bool:
        return not self.avisos and self.trafo is not None and self.mes is not None and self.mwh is not None


def ucs_impressas(d: Documento) -> set[str]:
    """Os números de 10 dígitos ou mais impressos na conta, só os dígitos (a UC está entre eles)."""
    return {g for x in d.linhas for p in x.palavras if len(g := _digitos(p[0])) >= 10}


def achar_uc(contas_por_usina: dict[str, list[dict]], d: Documento, lida: str | None) -> tuple[str, dict] | None:
    """(slug, conta) da UC desta conta: a que as usinas já têm no meuWatt e está IMPRESSA na conta; sem texto (conta
    digitalizada), a que a IA leu. A IA sozinha trocava a UC pelo "Seu código" do boleto da Elektro."""
    impressas, lida_d = ucs_impressas(d), _digitos(lida)
    achadas = {}
    for slug, contas in contas_por_usina.items():
        for c in contas:
            u = _digitos(c.get("installation_number"))
            if len(u) >= 10 and (u in impressas or (not d.digital and u == lida_d)):
                achadas.setdefault(u, (slug, c))
    if len(achadas) > 1 and lida_d in achadas:            # a conta cita outra UC (a geradora e a beneficiária)
        return achadas[lida_d]
    return next(iter(achadas.values())) if len(achadas) == 1 else None


def _medidor(i: dict, kwh: float) -> tuple[bool | None, str | None]:
    """(confere?, a conta escrita): (atual − anterior) × constante = o consumo, com folga de 1 kWh (a Elektro imprime 55
    para 264 × 0,21 = 55,44; nas 5 contas reais a maior diferença é 0,8; a folga de uma constante deixava passar 600 kWh
    na CEMIG). O medidor que deu a volta soma 10^dígitos. (None, None) = a conta não traz as três."""
    a, b, k = numero(i.get("leitura_anterior")), numero(i.get("leitura_atual")), numero(i.get("constante"))
    if a is None or b is None or k is None or k <= 0:
        return None, None
    volta = 10 ** len(str(int(a))) if b < a else 0
    calculado = (b + volta - a) * k
    texto = (f"({i.get('leitura_atual')} − {i.get('leitura_anterior')}) × {i.get('constante')} = "
             f"{br(calculado, 2 if round(calculado, 2) % 1 else 0)}")
    return abs(calculado - kwh) <= 1.0, texto


def conferir(l: Leitura, contas: list[dict], trafos: dict[int, str]) -> None:
    """Confere o que a IA leu contra a própria conta e o meuWatt. `contas`: as da usina da UC; `trafos`: id → nome."""
    d, doc = l.dados, l.doc
    vistos: set = set()
    for i in d.get("injetada") or []:
        if not isinstance(i, dict):
            continue
        impresso, posto = str(i.get("kwh") or "").strip(), str(i.get("posto") or "?")
        kwh = numero(impresso)
        if kwh is None or kwh < 0:
            l.avisos.append(f"não entendi a energia injetada «{impresso}» ({posto})")
            continue
        onde = _na_linha(doc, i.get("pagina"), i.get("rotulo"), impresso) if doc.digital else None
        if doc.digital and onde is None:
            l.avisos.append(f"não achei «{impresso}» numa linha de energia injetada «{i.get('rotulo') or '?'}» da conta")
        # o medidor fecha SEMPRE: a coluna errada na linha certa (o "Faturado" da CEMIG) estava impressa na linha, e na
        # conta digitalizada ele é a única conferência (avaliação de 17/11/2026)
        medidor, conta = _medidor(i, kwh)
        if medidor is False:
            l.avisos.append(f"a leitura do medidor não dá {impresso} kWh ({posto}): {conta}")
        elif medidor is None:
            l.avisos.append(f"não achei a leitura do medidor de {posto} para conferir {impresso} kWh")
        elif doc.digital and not _leituras_impressas(doc, i):
            # as leituras de outra linha fechavam com a coluna errada: a "kWh" (energia ATIVA) da CEMIG dá
            # (11 − 8) × 700 = 2.100, o "Faturado" impresso na linha da injetada (avaliação de 17/11/2026)
            medidor = False
            l.avisos.append(f"as leituras {i.get('leitura_anterior')} e {i.get('leitura_atual')} (× "
                            f"{i.get('constante')}) não estão lado a lado numa linha de energia injetada da conta")
        chave = (onde[0], onde[2]) if onde else (i.get("leitura_anterior"), i.get("leitura_atual"), impresso)
        if chave in vistos:
            l.avisos.append(f"o posto {posto} repete o mesmo número da conta: a soma dobraria")
        vistos.add(chave)
        l.postos.append({"posto": posto, "rotulo": i.get("rotulo"), "impresso": impresso, "kwh": kwh, "onde": onde,
                         "medidor": medidor, "conta": conta, "anterior": str(i.get("leitura_anterior") or "").strip(),
                         "atual": str(i.get("leitura_atual") or "").strip()})
    if not l.postos:
        l.avisos.append("não achei a energia injetada na conta")
    elif doc.digital:
        l.avisos += _postos_esquecidos(l)
    l.mes, problema = periodo(d)
    ref = _referencia(d.get("referencia"))
    if problema:
        l.avisos.append(problema)
    elif ref and l.mes not in (ref, (ref[0], ref[1] - 1) if ref[1] > 1 else (ref[0] - 1, 12)):
        # a energia é do mês de referência ou do anterior: o que passa disso é data trocada (na conta digitalizada, a IA
        # deslizando para a próxima leitura; avaliação de 17/11/2026)
        l.avisos.append(f"a energia de {_mes_br(l.mes)} não combina com a conta de referência «{d.get('referencia')}»")
    elif doc.digital and not _lado_a_lado(doc.linhas, d.get("leitura_anterior"), d.get("leitura_atual")):
        # as datas dizem em que mês a conta entra: impressas e JUNTAS (na Elektro os rótulos são desenho e a linha é
        # "31/07/2026 31/08/2026 32 01/10/2026": o par deslocado também tem 31 dias)
        l.avisos.append(f"não achei as datas «{d.get('leitura_anterior')}» e «{d.get('leitura_atual')}» lado a lado na "
                        "conta (o período de leitura)")
    if l.trafo and l.mes:
        l.atual = next((c for c in contas if c.get("transformer_id") == l.trafo["id"]
                        and (c.get("year"), c.get("month")) == l.mes), None)
    if not doc.digital:
        l.notas.append("conta digitalizada (imagem): confira os números na página")


_LIGA_DATAS = {"a", "à", "-", "ate", "até"}


def _numeros_da_linha(x: Linha) -> list[str]:
    return [p[0] for p in x.palavras if numero(p[0]) is not None]


def _lado_a_lado(linhas: list[Linha], primeiro: Any, segundo: Any) -> bool:
    """Os dois valores na mesma linha, o 2º logo depois do 1º (só "à", "a" ou "-" entre eles)."""
    a, b = str(primeiro or "").strip(), str(segundo or "").strip()
    for x in linhas:
        ps = [p[0] for p in x.palavras]
        for i, p in enumerate(ps):
            if p != a:
                continue
            j = i + 1
            while j < len(ps) and _norm(ps[j]) in _LIGA_DATAS:
                j += 1
            if j < len(ps) and ps[j] == b:
                return True
    return False


def _leituras_impressas(d: Documento, i: dict) -> bool:
    """As leituras do posto lado a lado numa linha de energia injetada (na Elektro, a própria linha do consumo; na CEMIG,
    a "kWh Injet."), e a constante impressa na conta."""
    a, b = str(i.get("leitura_anterior") or "").strip(), str(i.get("leitura_atual") or "").strip()
    k = str(i.get("constante") or "").strip()
    juntas = _lado_a_lado([x for x in d.linhas if "injet" in _norm(x.texto)], a, b)
    return juntas and any(p[0] == k for x in d.linhas for p in x.palavras)


def _postos_esquecidos(l: Leitura) -> list[str]:
    """O posto com leitura impressa que ficou fora da soma (a IA esquecer o HP dá 143,5 no lugar de 144,9: o mesmo erro
    que está hoje no meuWatt):
    - a linha só de leituras de injetada (a "kWh Injet." da CEMIG, um par anterior/atual por segmento): par andando que
      nenhum posto usou;
    - o registro TOTAL de energia injetada (a linha "ENERGIA INJETADA" da Elektro, sem posto): (atual − anterior) ×
      constante tem de bater com a soma, com a folga de um passo do medidor."""
    usados = {(str(p.get("anterior")), str(p.get("atual"))) for p in l.postos}
    avisos = []
    for x in l.doc.linhas:
        rotulo = _norm(" ".join(p[0] for p in x.palavras[:len(x.palavras) - len(_numeros_da_linha(x))]))
        ns = _numeros_da_linha(x)
        if "kwh" in rotulo and "injet" in rotulo and "energia" not in rotulo and len(ns) >= 2:
            for a, b in zip(ns[0::2], ns[1::2]):
                if (numero(b) or 0) > (numero(a) or 0) and (a, b) not in usados:
                    avisos.append(f"a linha «{x.texto}» tem leitura andando ({a} → {b}) que não entrou na soma")
        elif rotulo == "energia injetada" and len(ns) >= 3:
            a, b, k = (numero(n) for n in ns[:3])
            if a is not None and b is not None and k and b >= a and l.total_kwh is not None:
                total = (b - a) * k
                if abs(total - l.total_kwh) > max(1.0, k):
                    avisos.append(f"a soma dos postos ({br(l.total_kwh)} kWh) não bate com o registro total de energia "
                                  f"injetada da conta ({ns[1]} − {ns[0]}) × {ns[2]} = {br(total)} kWh")
    return avisos


def _na_linha(d: Documento, pagina: Any, rotulo: Any, valor: str) -> tuple[int, tuple, tuple] | None:
    """A linha de energia INJETADA com o rótulo e o número: (página, caixa do rótulo, caixa do número). A palavra
    "injet" tem de estar na linha: com o rótulo vazio da IA, qualquer linha valia (a leitura 1014 passava por kWh)."""
    alvo, pref = _norm(rotulo), (int(pagina) - 1 if str(pagina).isdigit() else -1)
    for x in sorted(d.linhas, key=lambda x: x.pagina != pref):
        texto = _norm(x.texto)
        if "injet" not in texto or (alvo and alvo not in texto):
            continue
        ps = [p for p in x.palavras if p[0] == valor]
        if not ps:
            continue
        nomes = []
        for p in x.palavras:                              # o rótulo: as palavras antes do 1º número
            if numero(p[0]) is not None:
                break
            nomes.append(p)
        nomes = nomes or x.palavras[:1]
        return (x.pagina, (nomes[0][1], min(p[2] for p in nomes), nomes[-1][3], max(p[4] for p in nomes)),
                ps[-1][1:])
    return None


def _onde(d: Documento, valor: Any) -> tuple[int, tuple] | None:
    """Onde o valor está impresso: as palavras seguidas que o formam (a 1ª ocorrência)."""
    alvo = _norm(valor)
    if len(alvo) < 3:
        return None
    for x in d.linhas:
        ps = x.palavras
        for i in range(len(ps)):
            if not alvo.startswith(_norm(ps[i][0])[:3]):
                continue
            junto = ""
            for j in range(i, min(i + 12, len(ps))):
                junto = f"{junto} {ps[j][0]}".strip()
                if alvo in _norm(junto):
                    caixa = (ps[i][1], min(p[2] for p in ps[i:j + 1]), ps[j][3], max(p[4] for p in ps[i:j + 1]))
                    return x.pagina, caixa
                if len(junto) > len(alvo) + 4:
                    break
    return None




# --------------------------------------------------------------------------- a prova (uma imagem)
def _fonte(tamanho: int, negrito: bool = False):
    import matplotlib
    from PIL import ImageFont
    nome = "DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf"
    return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", nome), tamanho)


VERDE, AMBAR, CINZA, TINTA, LINHA = (26, 127, 55), (178, 106, 0), (110, 116, 122), (24, 28, 32), (222, 226, 230)


def _caber(img, largura: int, altura: int):
    k = min(1.0, largura / img.width, altura / img.height)
    return img if k >= 1 else img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))))


def prova(l: Leitura) -> bytes:
    """Cada valor recortado da conta (à esquerda) ao lado do que o bot leu (à direita). Na energia, do rótulo até o
    número (a linha inteira da tabela, com os números do gráfico do lado, encolhia o número para 3 px no celular). Na
    conta digitalizada, a página inteira: sem a posição das letras não há onde recortar. Desenha as páginas: rode por
    `no_pdfium`."""
    from PIL import Image, ImageDraw

    medir = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    largura, esq, dir_ = 1400, 820, 480
    x_dir = 40 + esq + 40
    f_tit, f_sub, f_rot, f_val, f_nota, f_total = (_fonte(36, True), _fonte(22), _fonte(20), _fonte(26, True),
                                                    _fonte(20), _fonte(24, True))
    d = l.dados
    ondes = {c: _onde(l.doc, d.get(c)) if l.doc.digital else None
             for c in ("titular", "leitura_anterior", "leitura_atual")}
    ondes["uc"] = next(((x.pagina, p[1:]) for x in l.doc.linhas for p in x.palavras
                        if l.uc and _digitos(p[0]) == _digitos(l.uc)), None) if l.doc.digital else None
    if l.doc.digital:
        precisa = {o[0] for o in [*ondes.values(), *(p["onde"] for p in l.postos)] if o}
    else:                                                 # a 1ª página e a da energia injetada
        precisa = {0} | {int(i["pagina"]) - 1 for i in d.get("injetada") or []
                         if isinstance(i, dict) and str(i.get("pagina") or "").isdigit()}
    paginas = desenhar(l.doc, sorted(precisa), ESCALA)

    def recorte(pagina: int, caixa: tuple, margem_x: float = 0, acima: float = 0, folga: float = 4) -> Any:
        img = paginas.get(pagina)
        if img is None:
            return None
        alto_pt = img.height / ESCALA
        x0, y0, x1, y1 = caixa
        corte = img.crop((int(max(0, (x0 - margem_x - 4) * ESCALA)), int(max(0, (alto_pt - y1 - acima - folga) * ESCALA)),
                          int(min(img.width, (x1 + margem_x + 4) * ESCALA)),
                          int(min(img.height, (alto_pt - y0 + folga) * ESCALA))))
        return _caber(corte, largura - 80, 170)            # mais largo que a coluna: faixa da largura toda

    def cab(campo: str, margem: float = 60) -> Any:
        o = ondes[campo]
        return recorte(o[0], o[1], margem, 14) if o else None

    a, b = ondes["leitura_anterior"], ondes["leitura_atual"]
    if a and b and a[0] == b[0] and abs(a[1][1] - b[1][1]) < 6:   # as duas datas na mesma linha: um recorte só
        img_periodo = recorte(a[0], (min(a[1][0], b[1][0]), min(a[1][1], b[1][1]), max(a[1][2], b[1][2]),
                                     max(a[1][3], b[1][3])), 30, 14)
    else:
        img_periodo = cab("leitura_atual")

    def injetada(p: dict) -> Any:
        """Do rótulo até o número escolhido, sem o resto da linha: o que está no meio aparece (com "…" no lugar, o
        "Registrado" da CEMIG sumia justo quando a IA pegava o "Faturado"; avaliação de 17/11/2026)."""
        if not p["onde"]:
            return None
        pagina, c_rotulo, c_numero = p["onde"]
        return recorte(pagina, (c_rotulo[0], min(c_rotulo[1], c_numero[1]), c_numero[2], max(c_rotulo[3], c_numero[3])),
                       folga=2)

    def texto(t: str, fonte, cor, larg: int = dir_) -> list[tuple[str, Any, tuple]]:
        return [(x, fonte, cor) for x in _quebrar(medir, t, fonte, larg)]

    ok_periodo = (l.mes is not None and a is not None and b is not None) if l.doc.digital else (None if l.mes else False)
    valores: list[tuple[str, str, Any, bool | None, str | None]] = [
        ("Unidade consumidora", (l.uc or str(d.get("uc") or "?")) + (f" · {l.trafo['nome']}" if l.trafo else ""),
         cab("uc"), l.trafo is not None, None),
        ("Titular", str(d.get("titular") or "—"), cab("titular"), None, None),
        ("Período de leitura", f"{d.get('leitura_anterior') or '?'} a {d.get('leitura_atual') or '?'} → energia de "
         f"{_mes_br(l.mes) if l.mes else '?'}", img_periodo, ok_periodo, None),
        *((f"Injetada · {p['posto']}", f"{br(p['kwh'])} kWh", injetada(p), _conferido(p, l.doc.digital),
           f"medidor: {p['conta']}" if p["conta"] else None) for p in l.postos),
    ]

    def lado_direito(rotulo: str, valor: str, ok: bool | None, extra: str | None) -> list:
        marca = " ✔" if ok else " ⚠" if ok is False else ""
        cor = VERDE if ok else AMBAR if ok is False else TINTA
        return texto(rotulo, f_rot, CINZA) + texto(valor + marca, f_val, cor) + (texto(extra, f_nota, CINZA) if extra
                                                                                  else [])

    blocos: list[tuple[Any, list, list]] = []           # (imagem, texto da esquerda sem imagem, texto da direita)
    if l.doc.digital:
        for rotulo, valor, img, ok, extra in valores:
            vazio = [] if img is not None else texto("(não achei este valor impresso na conta)", f_nota, CINZA, esq)
            blocos.append((img, vazio, lado_direito(rotulo, valor, ok, extra)))
    else:
        direita = [x for v in valores for x in lado_direito(*v[:2], v[3], v[4])]
        for n, i in enumerate(sorted(paginas)):
            img = paginas[i]
            k = min(1.0, esq / img.width)
            blocos.append((img.resize((int(img.width * k), int(img.height * k))), [], direita if n == 0 else []))

    larga = largura - 80
    soma = " + ".join(br(p["kwh"]) for p in l.postos)
    rodape = texto(f"Energia injetada: {soma} = {br(l.total_kwh)} kWh = {br(l.mwh, 3)} MWh" if l.postos
                   else "Energia injetada: não achei", f_total, TINTA, larga)
    if l.mes and l.atual and l.atual.get("billed_mwh") is not None:
        rodape += texto(f"No meuWatt hoje ({_mes_br(l.mes)}): {br(l.atual['billed_mwh'], 3)} MWh", f_nota, CINZA, larga)
    elif l.mes:
        rodape += texto(f"No meuWatt ainda não há esta conta ({_mes_br(l.mes)}).", f_nota, CINZA, larga)
    for aviso in l.avisos:
        rodape += texto(f"⚠ {aviso}", f_nota, AMBAR, larga)
    for nota in l.notas:
        rodape += texto(f"• {nota}", f_nota, CINZA, larga)
    titulo = texto("Conta de energia" + (f" · {l.usina['nome']}" if l.usina else ""), f_tit, TINTA, larga)
    sub = texto(" · ".join(x for x in (str(d.get("distribuidora") or ""), f"UC {l.uc}" if l.uc else "") if x), f_sub,
                CINZA, larga)

    def alto(linhas: list) -> int:
        return sum(f.size + 10 for _, f, _ in linhas)

    def alto_do_bloco(img, vazio, direita) -> int:
        if img is not None and img.width > esq:             # a faixa larga: o texto do bot vem embaixo
            return img.height + 10 + alto(direita)
        return max(img.height if img is not None else 0, alto(vazio), alto(direita))

    altura = 30 + alto(titulo) + alto(sub) + 50 + sum(alto_do_bloco(*bl) + 26 for bl in blocos) + alto(rodape) + 40
    tela = Image.new("RGB", (largura, altura), "white")
    g = ImageDraw.Draw(tela)
    y = 30
    for t, f, cor in titulo + sub:
        g.text((40, y), t, font=f, fill=cor)
        y += f.size + 10
    y += 12
    g.text((40, y), "Na conta", font=f_rot, fill=CINZA)
    g.text((x_dir, y), "O bot leu", font=f_rot, fill=CINZA)
    y += 38
    for img, vazio, direita in blocos:
        if img is not None:
            tela.paste(img, (40, y))
            g.rectangle((40, y, 40 + img.width, y + img.height), outline=LINHA)
        largo = img is not None and img.width > esq
        for coluna, topo, linhas in ((40, y, vazio),
                                     (40, y + img.height + 10, direita) if largo else (x_dir, y, direita)):
            ty = topo
            for t, f, cor in linhas:
                g.text((coluna, ty), t, font=f, fill=cor)
                ty += f.size + 10
        y += alto_do_bloco(img, vazio, direita) + 26
        g.line((40, y - 13, largura - 40, y - 13), fill=LINHA)
    for t, f, cor in rodape:
        g.text((40, y), t, font=f, fill=cor)
        y += f.size + 10
    b_ = io.BytesIO()
    tela.save(b_, "PNG", optimize=True)
    return b_.getvalue()


def _conferido(p: dict, digital: bool) -> bool:
    """O ✔ da energia: a conta do medidor fechando e, na conta digital, o número impresso na linha do rótulo."""
    return p["medidor"] is True and (p["onde"] is not None or not digital)


def _quebrar(g, texto: str, fonte, largura: int) -> list[str]:
    """O texto em linhas que cabem na largura: nunca cortado nem encolhido (regra do Renan, 07/11/2026). A palavra que
    sozinha não cabe (o nome do arquivo) quebra entre as letras."""
    linhas, atual = [], ""
    for palavra in texto.split(" "):
        tenta = f"{atual} {palavra}" if atual else palavra
        if g.textlength(tenta, font=fonte) <= largura:
            atual = tenta
            continue
        if atual:
            linhas.append(atual)
        atual = ""
        for letra in palavra:
            if atual and g.textlength(atual + letra, font=fonte) > largura:
                linhas.append(atual)
                atual = ""
            atual += letra
    return [*linhas, atual] if atual else linhas




# --------------------------------------------------------------------------- a ferramenta
FERRAMENTA = {"type": "function", "function": {
    "name": "conta_de_energia",
    "description": ("Lê a CONTA DE ENERGIA (fatura da distribuidora: Elektro, CEMIG…) que a pessoa mandou em PDF — a "
                    "mensagem dela aparece como «[📄 PDF recebido: «nome»]» — e confere a unidade consumidora (UC), o mês "
                    "da energia e a energia injetada. O sistema manda a PROVA (cada valor recortado da conta ao lado do "
                    "que foi lido) e propõe salvar a conta no meuWatt (Faturas da usina, com o PDF), de onde o relatório "
                    "de geração lê; a pessoa confirma com Sim. Use quando ela mandar a conta e pedir para ler, conferir, "
                    "lançar ou salvar. Sem `arquivo` nem `todos`: os PDFs deste pedido. Assinar PDF é `assinar_pdf`."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "a usina que a pessoa disse (o sistema confere pela UC da conta)"},
        "arquivo": {"type": "string", "description": "parte do nome do PDF, quando ela apontou um que mandou antes"},
        "todos": {"type": "boolean", "description": "true só quando ela pediu para ler TODOS os PDFs que mandou"},
        "senha": {"type": "string", "description": "a senha do PDF, só quando a pessoa a escreveu (exata)"}}}}}


async def conta_de_energia(ctx, a: dict) -> dict:
    from app.services import assistente_geracao as ger
    pdfs, erro = pdf.escolher(ctx, a, "ler")
    if erro:
        return {"erro": erro}
    pdfs = pdfs[:TETO_PDFS]
    if ctx.mw is None or not ctx.usinas:
        ger._usina(ctx, None)                             # a frase de sempre: sem meuWatt ou sem usina
    dita = ger._usina(ctx, a.get("usina")) if (a.get("usina") or "").strip() else None
    senha = str(a.get("senha") or "").strip()
    if senha:
        if senha not in (ctx.pedido or ""):
            return {"erro": "Passe a senha EXATA que a pessoa escreveu nesta mensagem, sem mudar nada. Sem ela, peça."}
        ctx.segredos.append(senha)
    mw = ctx.mw
    ctx.db.commit()                                       # solta a conexão enquanto o meuWatt e a IA respondem
    usinas = [dita] if dita else list(ctx.usinas.values())
    try:
        listas = await asyncio.gather(*(mw.contas_de_energia(u["slug"]) for u in usinas))
    except httpx.HTTPStatusError as e:
        return {"erro": f"O meuWatt não mostrou as contas da usina com o seu acesso ({e.response.status_code})."}
    contas = {u["slug"]: lista for u, lista in zip(usinas, listas)}
    vez = asyncio.Semaphore(2)                            # a ponte da IA tem 3 vagas, e outras pessoas usam o bot

    async def ler(p: dict) -> Leitura | str:
        async with vez:
            return await _ler(ctx, p, senha, contas)

    leituras = await asyncio.gather(*(ler(p) for p in pdfs), return_exceptions=True)
    erros = [f"«{p['nome']}»: {x}" for p, x in zip(pdfs, leituras) if isinstance(x, (str, BaseException))]
    leituras = [x for x in leituras if isinstance(x, Leitura)]
    if not leituras:
        return {"erro": "Não consegui ler a conta. " + " ".join(erros)}
    if dita and (outras := [x for x in leituras if x.usina is None]):
        # a UC não é da usina dita: procura nas outras dela, para dizer de qual é
        resto = [u for u in ctx.usinas.values() if u["slug"] != dita["slug"]]
        mais = dict(zip([u["slug"] for u in resto], await asyncio.gather(
            *(mw.contas_de_energia(u["slug"]) for u in resto), return_exceptions=True)))
        for x in outras:
            achada = achar_uc({s: v for s, v in mais.items() if isinstance(v, list)}, x.doc, x.dados.get("uc"))
            if achada:
                x.avisos.append(f"a UC {achada[1]['installation_number']} desta conta é de "
                                f"{ctx.usinas[achada[0]]['nome']}, não de {dita['nome']}")
    enviadas = 0
    for x in leituras:
        if x.usina is None and not any("é de " in v for v in x.avisos):
            x.avisos.insert(0, f"a UC {x.dados.get('uc') or '?'} não está em nenhuma conta das suas usinas no "
                               "meuWatt (a 1ª conta de uma UC nova se cadastra no site, em Projeto › Faturas)")
        png = await no_pdfium(prova, x)
        r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=png, filename="prova.png",
                                           mime="image/png", texto="Prova da leitura da conta de energia")
        if r and r.get("ok"):
            enviadas += 1
            ctx.enviados.append("prova da conta de energia")
    prontas = [x for x in leituras if x.pronta]
    saida: dict[str, Any] = {"contas": [_resumo(x) for x in leituras], "prova_enviada_no_chat": enviadas > 0}
    if erros:
        saida["nao_lidas"] = erros
    if len(prontas) < len(leituras):
        saida["instrucao"] = ("Diga à pessoa, em uma ou duas linhas, o que impediu salvar (os avisos), que a prova "
                              "já foi no chat, e nada foi salvo.")
        return saida
    if enviadas < len(leituras):                          # sem a prova à vista, não há o que confirmar
        saida["instrucao"] = "A prova não chegou ao chat: diga que nada foi salvo e peça para mandar de novo."
        return saida
    vagas = [(x.trafo["id"], x.mes) for x in prontas]
    if len(set(vagas)) < len(vagas):
        saida["instrucao"] = "Duas das contas são da mesma UC e do mesmo mês: pergunte qual vale. Nada foi salvo."
        return saida
    if len({x.usina["slug"] for x in prontas}) > 1:
        saida["instrucao"] = "As contas são de usinas diferentes: peça para mandar uma usina por vez. Nada foi salvo."
        return saida
    usina = prontas[0].usina
    try:
        me = await mw.quem_sou_eu()
    except httpx.HTTPError:
        me = None                                         # sem conferir aqui: o meuWatt decide no Sim
    if me is not None and not _grava_valores(me, usina.get("id")):
        saida["instrucao"] = ("No meuWatt, só o administrador da usina grava os valores da conta: diga isso em uma "
                              "linha; a prova já foi no chat. Nada foi salvo.")
        return saida
    emitidos = await _emitidos(mw, usina["slug"], {x.mes for x in prontas})
    return {**saida, **_propor(ctx, prontas, usina, emitidos)}


async def _ler(ctx, p: dict, senha: str, contas: dict[str, list[dict]]) -> Leitura | str:
    try:
        conteudo, _ = await whatsapp.baixar_midia(p["id"])
    except whatsapp.GatewayIndisponivel as e:
        return f"não consegui baixar o PDF ({e})"
    try:
        doc = await no_pdfium(abrir, conteudo, [senha])
    except SemSenha:
        return ("o PDF tem senha" + (" e a que a pessoa mandou não abriu" if senha else "") + ": peça a senha do PDF "
                "(em geral, os 5 primeiros números do CPF ou do CNPJ do titular)")
    except ValueError as e:
        return str(e)
    try:
        dados = await extrair(doc)
    except (ValueError, httpx.HTTPError) as e:
        return f"a leitura pela IA falhou ({type(e).__name__}: {str(e)[:120]})"
    x = Leitura(p["nome"], conteudo, doc, dados)
    achada = achar_uc(contas, doc, dados.get("uc"))
    trafos: dict[int, str] = {}
    if achada:
        slug, conta = achada
        x.usina, x.uc = ctx.usinas.get(slug) or {"slug": slug, "nome": slug}, conta["installation_number"]
        try:
            trafos = {t["id"]: t.get("name") for t in (await ctx.mw.usina(slug)).get("transformers") or []}
        except httpx.HTTPError:
            trafos = {}
        x.trafo = {"id": conta["transformer_id"], "nome": trafos.get(conta["transformer_id"])
                   or f"UC #{conta['transformer_id']}"}
    conferir(x, contas.get(x.usina["slug"], []) if x.usina else [], trafos)
    return x


def _grava_valores(me: dict, plant_id: Any) -> bool:
    """A régua do meuWatt (`utility_bills.router.pode_editar_valores`): admin (da plataforma, root ou de alguma usina) ou
    admin O&M desta usina."""
    papeis = {r.get("plant_id"): r.get("role") for r in me.get("plant_roles") or []}
    return (bool(me.get("is_platform_admin")) or me.get("primary_role") == "admin" or "admin" in papeis.values()
            or papeis.get(plant_id) == "system_admin")


async def _emitidos(mw, slug: str, meses: set) -> set:
    """Os meses cujo relatório mensal JÁ foi emitido: o PDF de lá não muda com a conta nova até alguém gerar de novo."""
    async def um(am):
        try:
            return am if await mw.relatorio_existente(slug, "MENSAL", date(am[0], am[1], 1)) else None
        except httpx.HTTPError:
            return None
    return {am for am in await asyncio.gather(*(um(am) for am in meses)) if am}


def _resumo(x: Leitura) -> dict:
    return {"arquivo": x.nome, "usina": (x.usina or {}).get("nome"), "uc": x.uc or x.dados.get("uc"),
            "trafo": (x.trafo or {}).get("nome"), "mes_da_energia": _mes_br(x.mes) if x.mes else None,
            "energia_injetada_mwh": x.mwh, "no_meuwatt_hoje_mwh": (x.atual or {}).get("billed_mwh"),
            "avisos": x.avisos, "conferir": x.notas}


def _propor(ctx, prontas: list[Leitura], usina: dict, emitidos: set) -> dict:
    meses = sorted({x.mes for x in prontas})
    # "N conta(s)" é a contagem que o helper reconhece (`_contagens`): com duas, "Salva o TR-01" pergunta de novo em vez
    # de gravar as duas, e "as duas" confirma (avaliação de 17/11/2026)
    resumo = (f"Salvar no meuWatt {'a conta' if len(prontas) == 1 else f'{len(prontas)} conta(s)'} de energia de "
              f"{usina['nome']} ({', '.join(_mes_br(m) for m in meses)}), com o PDF")
    linhas = []
    for x in prontas:
        atual = x.atual or {}
        antes = (f" (hoje: {br(atual['billed_mwh'], 3)})" if atual.get("billed_mwh") is not None
                 else " (o mês estava marcado sem fatura)" if atual.get("no_bill") else " (nova)")
        linhas.append(f"{x.trafo['nome']} · UC {x.uc} · {_mes_br(x.mes)}: {br(x.mwh, 3)} MWh{antes}")
    grandes = [f"⚠️ {x.trafo['nome']} ({_mes_br(x.mes)}): o valor muda {br(abs(x.mwh / x.atual['billed_mwh'] - 1) * 100)}% "
               f"({br(x.atual['billed_mwh'], 3)} → {br(x.mwh, 3)} MWh). Confira na prova antes do Sim."
               for x in prontas if (x.atual or {}).get("billed_mwh")
               and abs(x.mwh / x.atual["billed_mwh"] - 1) > 0.05]
    if any(not x.doc.digital for x in prontas):
        grandes.append("⚠️ Conta digitalizada (imagem): confira na prova os números da página antes do Sim.")
    avisos = [*grandes, "A tela do relatório de geração do meuWatt passa a mostrar esta conta."] + [
        f"O PDF do relatório de {_mes_br(m)} já foi emitido: ele fica com o valor antigo até a equipe gerar de novo "
        "(Relatórios, no meuWatt)." for m in sorted(emitidos)]

    async def executar(db, quem, telefone: str) -> str:
        return await _salvar_todas(db, quem, usina, prontas)

    return helper.propor(ctx, resumo, PRAZO_S, executar, linhas, avisos, parte="bot_meuwatt", confirmacao="sim")


async def _salvar_todas(db, quem, usina: dict, prontas: list[Leitura]) -> str:
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuwatt
    try:
        mw = cliente_meuwatt(db, quem.id, so_proprio=True)
    except SemConexao as e:
        return f"❌ Sem o seu token do meuWatt ({e}). Nada foi salvo."
    db.commit()
    slug, feitas, falhas = usina["slug"], [], []

    async def de_agora(x: Leitura) -> dict | None:
        """A conta como está AGORA no meuWatt (o salvar de lá troca todos os campos: o que alguém editou no site depois
        da prova não pode voltar atrás)."""
        contas = await mw.contas_de_energia(slug, x.mes[0])
        return next((c for c in contas if c.get("transformer_id") == x.trafo["id"]
                     and (c.get("year"), c.get("month")) == x.mes), None)

    for x in prontas:
        rotulo = f"{x.trafo['nome']} ({_mes_br(x.mes)})"
        try:
            feitas.append(await _salvar(mw, slug, x, await de_agora(x)))
        except httpx.HTTPStatusError as e:
            falhas.append(f"❌ {rotulo}: o meuWatt recusou ({detalhe_do_upstream(e.response) or e.response.status_code}). "
                          "Esta não foi salva.")
        except httpx.HTTPError:
            try:                                          # pode ter gravado: relê para dizer o que ficou
                conta = await de_agora(x)
            except httpx.HTTPError:
                conta = None
            if conta and conta.get("billed_mwh") is not None and round(conta["billed_mwh"], 3) == x.mwh:
                feitas.append(f"• {rotulo}: {br(x.mwh, 3)} MWh (o meuWatt demorou, mas a conta está lá)")
            else:
                falhas.append(f"⚠️ {rotulo}: o meuWatt não respondeu. A conta PODE ter sido salva: confira em Projeto › "
                              "Faturas antes de mandar de novo.")
    relatorio = []
    if feitas:
        for ano, mes in sorted({x.mes for x in prontas}):
            try:
                relatorio.append(await o_relatorio(mw, usina, ano, mes))
            except httpx.HTTPError:
                relatorio.append(f"📊 Não consegui reler o relatório de {_mes_br((ano, mes))} agora.")
    cabeca = "✅ Conta salva no meuWatt:" if not falhas else ("⚠️ Salvo EM PARTE:" if feitas else "❌ A conta não foi salva:")
    return "\n".join([cabeca, *feitas, *falhas, *relatorio])


async def _salvar(mw, slug: str, x: Leitura, atual: dict | None) -> str:
    """Pelo salvar de lá (o upsert de UC × mês), que troca TODOS os campos: vai o que a conta do meuWatt já tem, com o
    MWh novo e a UC (conferida) se faltava. Titular e tarifa nunca vêm da IA: ninguém os conferiu e eles não estão no
    resumo que a pessoa confirmou. O PDF entra como nova versão (o mesmo arquivo não duplica); a senha que o abriu vai
    junto, para ele abrir no meuWatt também."""
    atual = atual or {}
    corpo: dict[str, Any] = {
        "transformer_id": x.trafo["id"], "year": x.mes[0], "month": x.mes[1], "billed_mwh": x.mwh,
        "installation_number": atual.get("installation_number") or x.uc, "tariff": atual.get("tariff"),
        "titular": atual.get("titular"), "pdf_filename": x.nome, "pdf_mime_type": "application/pdf",
        "pdf_base64": base64.b64encode(x.conteudo).decode()}
    if x.doc.senha:
        corpo["pdf_password"] = x.doc.senha
    gravada = await mw.salvar_conta(slug, corpo) or {}
    antes = atual.get("billed_mwh")
    valor = (f"{br(antes, 3)} → {br(x.mwh, 3)} MWh" if antes is not None and round(antes, 3) != x.mwh
             else f"{br(x.mwh, 3)} MWh")
    if not atual.get("id"):
        arquivo = "conta nova, com o PDF"
    elif gravada.get("pdf_file_id") and gravada.get("pdf_file_id") != atual.get("pdf_file_id"):
        arquivo = "PDF anexado como nova versão"
    else:
        arquivo = "o PDF já era este"
    return f"• {x.trafo['nome']} · {_mes_br(x.mes)}: {valor} ({arquivo})"


async def o_relatorio(mw, usina: dict, ano: int, mes: int) -> str:
    """O que o relatório de geração do meuWatt mostra AGORA no mês, pelas mesmas contas do card "Conta de energia" e do
    "Δ Fronteira × Conta" (mw-fe `ReportView`): a soma das UCs com valor, a fronteira (SSU) e a diferença. E se o PDF
    mensal já foi emitido: esse não muda até alguém gerar de novo."""
    async def emitido_() -> Any:                          # sem resposta, a linha do relatório sai sem esse aviso
        try:
            return await mw.relatorio_existente(usina["slug"], "MENSAL", date(ano, mes, 1))
        except httpx.HTTPError:
            return None

    contas, detalhe, fronteira, emitido = await asyncio.gather(
        mw.contas_de_energia(usina["slug"], ano), mw.usina(usina["slug"]), mw.ssu_totais_mensais(usina["slug"], ano),
        emitido_())
    do_mes = [c for c in contas if (c.get("year"), c.get("month")) == (ano, mes) and c.get("billed_mwh") is not None]
    trafos = {t["id"]: t.get("name") for t in detalhe.get("transformers") or []}
    conta = sum(c["billed_mwh"] for c in do_mes)
    com = {c["transformer_id"] for c in do_mes}
    faltam = [str(n) for i, n in trafos.items() if i not in com]
    linha = (f"📊 Relatório de geração de {usina['nome']}, {_mes_br((ano, mes))}: conta de energia {br(conta, 1)} MWh "
             f"({len(com & set(trafos)) if trafos else len(com)} de {len(trafos) or len(com)} UCs"
             + (f"; falta {', '.join(faltam)}" if faltam else "") + ")")
    fron = fronteira.get(mes)
    if not fron:                                          # sem leitor (ou zerado): o relatório não compara
        linha += " · sem medição na fronteira (SSU) para comparar."
    else:
        delta = fron - conta
        pct = delta / conta * 100 if conta > 0 else None
        sinal = "+" if delta >= 0 else ""
        linha += (f" · fronteira {br(fron, 1)} MWh · Δ {sinal}{br(delta, 2)} MWh"
                  + (f" ({sinal}{br(pct, 2)}%, {'conciliado' if abs(pct) < 1 else 'divergência'})." if pct is not None
                     else "."))
    if emitido:
        linha += (f"\nO PDF do relatório de {_mes_br((ano, mes))} já tinha sido emitido: ele continua com o valor antigo "
                  "até a equipe gerar de novo (Relatórios, no meuWatt).")
    return linha
