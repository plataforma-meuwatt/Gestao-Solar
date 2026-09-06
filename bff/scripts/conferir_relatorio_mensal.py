"""Confere, ponta a ponta, que o cliente abre o RELATÓRIO MENSAL liberado — e só ele.

Não é teste automatizado, e é de propósito: bate no meuPlano de verdade, com a credencial de
serviço de verdade, e **abre os PDFs que saíram** para contar páginas e ler a capa. Os testes
de `tests/test_relatorio_mensal.py` provam a régua contra um meuPlano de fantasia; provam bem,
e não provam a única coisa que importa aqui — que o caminho feliz existe. Até 06/09/2026 ele
nunca havia existido: os 26 relatórios de agosto/2026 estavam **todos em rascunho**, a porta do
cliente respondia `{"itens": []}` nas 22 usinas, e os três `404` que se mediam eram do corte,
não de defeito. Uma entrega cujo caminho feliz nunca rodou não está entregue.

O caminho que se quer provar, inteiro, porque cada seta já quebrou neste repositório:

    JWT do cliente → `_link_do_escopo` (usina_id NOSSO → PlantLink) → `mp_usina_id`
      → PAT de serviço → `visao-cliente/…/relatorios-mensais` → `_relatorio_autorizado`
      → bytes do PDF → `Content-Disposition` que o navegador lê

**O CORTE É O REQUISITO, e é o que este script mais persegue.** O fluxo do meuPlano é
Gerado → A aprovar → **Aprovado** → Liberado p/ envio → Enviado, e só os dois últimos
(`enviado`, `expedido`) atravessam. A armadilha tem nome: o status chamado *aprovado* **não é
liberado** — ainda é conversa interna, e um relatório aprovado pode voltar para revisão com
outro número. Medido em 06/09/2026 levando um relatório real (o técnico de setembro de Porto
Ferreira) até `aprovado`: as três portas do cliente responderam `404` e a lista da usina
continuou com dois itens. Aqui isso vira conferência permanente por um caminho que não escreve
nada: um relatório **que existe, é da usina do próprio cliente e não foi liberado** tem de dar
404 — e nenhum nome do vocabulário interno pode aparecer no corpo da resposta.

**Baixa DOIS PDFs, não um**, e por uma razão que se mede: técnico e executivo são documentos
diferentes, de motores diferentes, e escrevem o mês em grafias diferentes — o técnico imprime
"AGOSTO / 2026" e o executivo "ago/26 a ago/26". Nenhum dos dois escreve "2026-08". Uma
conferência que exigisse a forma ISO reprovaria um documento correto, que é pior que não
conferir: por isso `_competencia_no_texto` aceita as três grafias e **diz qual encontrou**.

    python scripts/conferir_relatorio_mensal.py
    python scripts/conferir_relatorio_mensal.py --url https://gestao-solar-production.up.railway.app
    python scripts/conferir_relatorio_mensal.py --usina 4 --competencia 2026-08
    python scripts/conferir_relatorio_mensal.py --provar    # não fala com ninguém: ver abaixo

Sem `--url`, sobe o BFF local num uvicorn próprio, em porta livre, e fala com ele por HTTP de
verdade — não `ASGITransport`. O que se quer ver sair por um socket é o `Content-Disposition`:
cabeçalho é latin-1 no Starlette, o nome do arquivo carrega o nome da usina, e "UFV SÍTIO"
estoura o Response **antes do CORS** — o portal acusaria a internet do cliente por um defeito
nosso. Já aconteceu com o travessão das 17 tarefas da OS 1016.

`--provar` é o contrário: não fala com ninguém e alimenta as MESMAS conferências com dados
deliberadamente estragados (o nome de quem aprovou vazando, o técnico listado antes do
executivo, a capa de outro mês, o nome do arquivo colidindo com o do relatório sob demanda, o
404 do não-liberado virando 200), exigindo que cada uma REPROVE. Um gate que nunca se viu
reprovar é decoração; este se vê.

O `pypdf` não está no `requirements.txt` porque o BFF não lê PDF: ele repassa bytes. Aqui é
ferramenta de conferência, como o `openpyxl` de `conferir_exportacao.py` — `pip install pypdf`
se faltar. Sem ele o script para e diz, em vez de fingir que contou páginas.

Sai com 0 só quando TODAS as conferências passam.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

# A saída tem acento e vai para um console cp1252 no Windows. Sem isto, o primeiro "ç"
# derruba o script com UnicodeEncodeError — depois de ter passado.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# ── O que se espera de Porto Ferreira ───────────────────────────────────────────────
#
# Escrito aqui, e não calculado da própria resposta: uma conferência que deriva o esperado
# do medido concorda com qualquer coisa. Se algum destes mudar é porque o produto mudou —
# e isso merece parar o gate e ser olhado.
USINA_PADRAO = 4  # Porto Ferreira NESTE sistema (mp_usina_id 19) — a usina com dado real
COMPETENCIA_PADRAO = "2026-08"  # o primeiro mês liberado, em 06/09/2026

#: As duas espécies, na ordem em que a tela as mostra. Executivo primeiro porque a diretoria
#: é o destino declarado pelo próprio meuPlano ("nível gestor que tem cinco minutos"); a
#: ordem é ÚNICA nas duas frentes, senão o portal e o aplicativo dariam respostas diferentes
#: para "qual é o principal?".
ORDEM_ESPERADA = ("executivo", "tecnico")

#: Piso do arquivo. Medido em 06/09/2026 pela porta do cliente: técnico 263.254 B / 9 páginas,
#: executivo 403.775 B / 3 páginas. O piso é generoso de propósito — ele existe para pegar o
#: PDF de capa-só (poucos KB) que um `dados` vazio produziria, não para cravar o tamanho.
BYTES_MINIMOS = 200_000
PAGINAS_MINIMAS = 3
SEGUNDOS_MAXIMOS = 10.0

#: O vocabulário INTERNO do fluxo do meuPlano. Nenhuma destas palavras pode chegar à tela do
#: cliente: para quem recebe existe um estado só — o documento está lá. `aprovado` está na
#: lista por ser a armadilha desta leva, e `aprovado_por` porque é nome de funcionário da
#: executora: publicá-lo entrega o organograma interno e cria endereço para cobrança pessoal.
INTERNOS_PROIBIDOS = (
    "aprovado_por", "aprovado_em", "apurado_em", "status_rotulo",
    "Liberado p/ envio", "expedido", "rascunho", "revisao",
)

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")


class Falhou(Exception):
    """Uma conferência que não passou. Carrega a frase que o operador precisa ler."""


# ── Impressão ───────────────────────────────────────────────────────────────────────


class Placar:
    """Coleta as conferências.

    É objeto, e não uma lista global, porque `--provar` precisa de um placar DESCARTÁVEL por
    mutação: contar as falhas de uma mutação no mesmo balde das falhas de verdade misturaria
    "o gate pegou o defeito que plantei" com "o gate achou um defeito real", que são notícias
    opostas.
    """

    def __init__(self) -> None:
        self.falhas: list[str] = []
        self.total = 0

    def __call__(self, nome: str, ok: bool, detalhe: str) -> bool:
        """Uma conferência nomeada. Imprime sempre o valor MEDIDO, passando ou não — "ok" sem
        número não deixa ninguém desconfiar quando o número muda."""
        self.total += 1
        print(f"  {'ok  ' if ok else 'FALHOU'} {nome}: {detalhe}")
        if not ok:
            self.falhas.append(f"{nome} — {detalhe}")
        return ok


Confere = Callable[[str, bool, str], bool]


class SaidaLimpa:
    """Um `stdout` que se recusa a imprimir o token.

    A saída deste script vai parar em log de terminal e em relato de agente. O JWT emitido
    aqui abre as sete usinas do dono, e o PAT do meuPlano abre as vinte e duas — bastaria um
    `print(resposta.request.headers)` num dia de depuração para vazar, e ninguém repararia.
    A cerca é aqui, no lugar por onde tudo passa, e não na disciplina de quem escreve a linha.
    """

    def __init__(self, alvo: Any) -> None:
        self._alvo = alvo
        self._segredos: list[str] = []

    def guardar(self, segredo: str | None) -> None:
        if segredo and len(segredo) >= 8:
            self._segredos.append(segredo)

    def write(self, texto: str) -> int:
        for s in self._segredos:
            if s in texto:
                texto = texto.replace(s, "<<<SEGREDO OCULTADO>>>")
                self._alvo.write(texto)
                self._alvo.flush()
                raise Falhou(
                    "um segredo ia sair na saída do script — a linha foi ocultada e o "
                    "script parou de propósito: corrija o `print` antes de rodar de novo"
                )
        return self._alvo.write(texto)

    def flush(self) -> None:
        self._alvo.flush()

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._alvo, nome)


# ── Subir o BFF ─────────────────────────────────────────────────────────────────────


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def subir_bff() -> tuple[str, subprocess.Popen[bytes]]:
    """Um uvicorn próprio, em porta livre, com a saída engolida.

    O processo é morto no `finally` de quem chamou, sempre: um uvicorn órfão segurando porta
    é o tipo de sujeira que só aparece na terceira execução.
    """
    porta = _porta_livre()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(porta),
         "--log-level", "warning"],
        cwd=str(RAIZ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONPATH": str(RAIZ)},
    )
    url = f"http://127.0.0.1:{porta}"
    for _ in range(120):
        if proc.poll() is not None:
            raise Falhou(
                f"o uvicorn morreu ao subir (código {proc.returncode}) — "
                "rode-o à mão para ver o erro"
            )
        try:
            if httpx.get(f"{url}/health", timeout=1.0).status_code == 200:
                print(f"  BFF local no ar em {url}  (pid {proc.pid})")
                return url, proc
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.kill()
    raise Falhou("o BFF local não respondeu /health em 60 s")


def token_do_cliente(user_id: int) -> str:
    """O JWT do cliente, emitido aqui — o script não tem a senha do dono, e não deve ter."""
    from dotenv import load_dotenv

    load_dotenv(str(RAIZ / ".env"))
    from app.core.security import criar_token

    token, _expira = criar_token(user_id)
    return token


def outra_carteira(db_user_id: int) -> tuple[int, str] | None:
    """Um usuário DESTE sistema cuja carteira não contém a usina do teste, e qual é o caso.

    Serve à conferência "um id de relatório de usina fora do vínculo dá 404". Ela não pode
    ser feita com um relatório alheio de verdade, porque isso exigiria liberar o documento de
    outro cliente só para medir — e o preço de uma medição não pode ser publicar o relatório
    de quem não pediu. Então a cerca é atravessada pelo outro lado: o MESMO relatório
    liberado, pedido por uma conta que não tem aquela usina.

    Devolve também QUAL caso foi encontrado, porque os dois não provam a mesma coisa — e
    isso não é teoria, foi medido. `_relatorio_autorizado` tem duas cercas: "esta conta não
    tem usina nenhuma" (atalho, que evita a ida ao upstream) e "o relatório é de uma usina
    que não é desta conta" (a que importa). Desligar a primeira e rodar este script **não
    reprovou**, porque a segunda pegou o caso assim mesmo — defesa em profundidade, e a prova
    de que com uma conta de carteira VAZIA este script não distingue as duas. Com a base de
    hoje (duas contas: o dono, com sete usinas, e uma sem nenhuma) só existe o caso fraco. A
    cerca forte tem dono declarado: `tests/test_relatorio_mensal.py`, que monta duas usinas
    de fantasia e pede a de outro cliente.
    """
    from dotenv import load_dotenv

    load_dotenv(str(RAIZ / ".env"))
    from app.api.v1.plants import usinas_do_usuario
    from app.core.db import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        vazio: int | None = None
        for u in db.query(User).order_by(User.id).all():
            if u.id == db_user_id:
                continue
            carteira = usinas_do_usuario(db, u)
            if any(x.id == USINA_PADRAO for x in carteira):
                continue
            if carteira:  # o caso forte: tem usinas, mas não ESTA
                return int(u.id), f"carteira de {len(carteira)} usina(s), sem esta"
            if vazio is None:
                vazio = int(u.id)
        return (vazio, "carteira vazia — o caso fraco") if vazio is not None else None
    finally:
        db.close()


# ── Leitura do que saiu ─────────────────────────────────────────────────────────────


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _competencia_no_texto(competencia: str, texto: str) -> str | None:
    """Em que grafia o mês pedido aparece neste texto — ou `None`.

    Três grafias porque os dois documentos usam duas delas e nenhum usa a terceira. Medido na
    capa, em 06/09/2026: o técnico escreve "AGOSTO / 2026", o executivo escreve
    "ago/26 a ago/26", e a forma ISO "2026-08" não aparece em nenhum dos dois. Exigir a ISO
    reprovaria os dois documentos corretos.

    O separador entre o mês e o ano é regex, e não espaço literal, porque esta função já
    reprovou uma capa correta: `"agosto 2026" in "AGOSTO / 2026"` é falso, e o `--provar`
    pegou o erro antes de qualquer pessoa. Barra, hífen, vírgula e o "de" de "agosto de 2026"
    são a mesma resposta à mesma pergunta.

    O acento sai dos dois lados antes de comparar: "MARÇO" volta do extrator de PDF como
    "MAR?O" conforme a fonte embutida, e uma conferência que morre em março é uma conferência
    em que ninguém vai confiar.
    """
    ano, mes = competencia.split("-")
    nome = _sem_acento(MESES[int(mes) - 1])
    #: até três caracteres de separação (" / ", "-", ", ") e um "de" opcional
    juncao = r"(?:\W{0,3}(?:de\W{1,3})?)"
    candidatos = {
        "ISO": re.escape(competencia),
        "por extenso": rf"\b{nome}{juncao}{ano}\b",
        "abreviada": rf"\b{nome[:3]}{juncao}(?:{ano}|{ano[2:]})\b",
    }
    limpo = _sem_acento(texto).lower()
    for rotulo, forma in candidatos.items():
        if re.search(forma, limpo):
            return rotulo
    return None


@dataclass
class Arquivo:
    """Um PDF que chegou, já aberto. `paginas` e `capa` só existem se o `pypdf` leu."""

    status: int
    bytes_: int
    segundos: float
    disposicao: str
    cache: str
    paginas: int
    capa: str


#: Tentativas de baixar cada PDF. Duas, e não uma, por uma coisa MEDIDA em 06/09/2026: com
#: três medições concorrentes contra o mesmo contêiner do meuPlano, o executivo respondeu
#: **HTTP 502 depois de 46,35 s** numa passada e **200 em 2,67 s** na seguinte, sem nada ter
#: mudado. Um gate cujo veredito depende da carga de outra pessoa ensina o time a ignorá-lo.
#: A segunda tentativa não ESCONDE o tropeço — ele é impresso e contado no rodapé; ela só
#: impede que o tropeço de terceiros vire a resposta do gate.
TENTATIVAS = 2
PAUSA_ENTRE_TENTATIVAS = 3.0

#: Cada primeira tentativa perdida no caminho, para o rodapé poder dizê-lo em voz alta.
TROPECOS: list[str] = []


def baixar_pdf(url: str, cab: dict[str, str], rotulo: str) -> tuple[httpx.Response, float]:
    """Os bytes do PDF, com paciência declarada. Devolve a resposta que valeu e seu tempo."""
    ultima: httpx.Response | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        t = time.perf_counter()
        try:
            r = httpx.get(url, headers=cab, timeout=200.0)
            segundos = time.perf_counter() - t
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                if tentativa > 1:
                    print(f"    (o {rotulo} veio na {tentativa}ª tentativa)")
                return r, segundos
            ultima = r
            aviso = (f"{rotulo}: tentativa {tentativa} devolveu HTTP {r.status_code} "
                     f"em {segundos:.2f} s — {r.text[:120]!r}")
        except httpx.HTTPError as exc:
            segundos = time.perf_counter() - t
            aviso = (f"{rotulo}: tentativa {tentativa} morreu em {segundos:.2f} s "
                     f"({type(exc).__name__})")
        TROPECOS.append(aviso)
        print(f"    ⚠ {aviso}")
        if tentativa < TENTATIVAS:
            time.sleep(PAUSA_ENTRE_TENTATIVAS)
    if ultima is None:
        raise Falhou(f"o {rotulo} não respondeu em {TENTATIVAS} tentativas")
    return ultima, 0.0


def abrir_pdf(conteudo: bytes) -> tuple[int, str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # noqa: BLE001
        raise Falhou(
            "falta o `pypdf` para abrir o PDF — `pip install pypdf`. Sem ele este script "
            "não conta páginas nem lê a capa, e um gate que não abre o arquivo não prova "
            "que o arquivo abre."
        ) from exc
    leitor = PdfReader(io.BytesIO(conteudo))
    capa = leitor.pages[0].extract_text() or "" if leitor.pages else ""
    return len(leitor.pages), " ".join(capa.split())


# ── As conferências ─────────────────────────────────────────────────────────────────
#
# Cada uma recebe o MEDIDO e nada mais. É o que permite ao `--provar` alimentá-las com dado
# estragado sem falar com ninguém: se uma conferência precisasse de rede para decidir, ela
# não poderia ser vista reprovando.


def conferir_lista(c: Confere, corpo: dict[str, Any], competencia: str) -> list[dict]:
    itens = corpo.get("itens") or []
    tipos = [i.get("tipo") for i in itens]
    c("lista responde", corpo.get("usina_id") == USINA_PADRAO,
      f"usina_id={corpo.get('usina_id')} usina={corpo.get('usina')!r} "
      f"{len(itens)} item(ns)")
    c("os dois documentos do mês estão liberados",
      sorted(t for t in tipos if t) == sorted(ORDEM_ESPERADA),
      f"tipos={tipos}")
    c("todo item é do mês pedido",
      bool(itens) and all(i.get("competencia") == competencia for i in itens),
      f"competências={[i.get('competencia') for i in itens]}")
    # A ordem é conferida só entre os dois do mesmo mês: com um mês só na base, ordenar por
    # competência não prova nada, e é o empate dentro do mês que a chave dupla resolve.
    do_mes = [i.get("tipo") for i in itens if i.get("competencia") == competencia]
    c("executivo antes do técnico", tuple(do_mes) == ORDEM_ESPERADA,
      f"ordem recebida={tuple(do_mes)} esperada={ORDEM_ESPERADA}")
    c("lista com itens não inventa aviso", corpo.get("aviso") is None,
      f"aviso={corpo.get('aviso')!r}")
    return itens


def conferir_corte(c: Confere, bruto: str, onde: str) -> None:
    """Nenhum nome do vocabulário interno no corpo que sai para o cliente.

    Sobre o TEXTO da resposta, e não sobre as chaves: um campo aninhado dentro de `conteudo`
    escaparia de qualquer varredura de primeiro nível, e é exatamente ali que um "status" se
    esconderia sem ninguém notar.
    """
    achados = [p for p in INTERNOS_PROIBIDOS if p in bruto]
    c(f"o vocabulário interno não atravessa ({onde})", not achados,
      "nada de " + ", ".join(INTERNOS_PROIBIDOS[:4]) + "…" if not achados
      else f"VAZOU: {achados}")


def conferir_arquivo(c: Confere, a: Arquivo, tipo: str, competencia: str,
                     usina: str) -> None:
    c(f"PDF {tipo} chega", a.status == 200 and a.bytes_ >= BYTES_MINIMOS,
      f"HTTP {a.status}, {a.bytes_:,} B (piso {BYTES_MINIMOS:,})".replace(",", "."))
    c(f"PDF {tipo} em tempo de tela", a.segundos < SEGUNDOS_MAXIMOS,
      f"{a.segundos:.2f} s (teto {SEGUNDOS_MAXIMOS:.0f} s)")
    c(f"PDF {tipo} tem documento dentro", a.paginas >= PAGINAS_MINIMAS,
      f"{a.paginas} páginas (piso {PAGINAS_MINIMAS})")
    grafia = _competencia_no_texto(competencia, a.capa)
    c(f"PDF {tipo} é do mês pedido", grafia is not None,
      f"{competencia} lido na capa na forma {grafia!r}" if grafia
      else f"{competencia} NÃO aparece na capa: {a.capa[:120]!r}")

    # O cabeçalho, que é onde este BFF já se queimou uma vez.
    disp = a.disposicao
    nome = re.search(r'filename="([^"]*)"', disp)
    cru = nome.group(1) if nome else ""
    c(f"nome do {tipo} é ASCII no cabeçalho",
      bool(cru) and cru.isascii() and cru.endswith(".pdf"),
      f"filename={cru!r}")
    c(f"nome bonito do {tipo} viaja junto", "filename*=UTF-8''" in disp,
      f"filename* presente" if "filename*=UTF-8''" in disp else f"ausente em {disp!r}")
    c(f"{tipo} abre na tela, não na pasta", disp.strip().lower().startswith("inline"),
      disp.split(";")[0])
    # Os dois documentos respondem à mesma pergunta com dois arquivos; o nome é o que impede
    # a pergunta "qual é o certo?" de começar na pasta de Downloads do cliente.
    c(f"nome do {tipo} não colide com o do relatório sob demanda",
      cru.lower().startswith("relatorio-mensal-") and "relatorio-manutencao" not in cru.lower(),
      f"{cru!r} × Relatorio-manutencao-{_sem_acento(usina)}-….pdf")
    c(f"nome do {tipo} não carrega o id do meuPlano", "usina19" not in cru.lower(),
      f"{cru!r} (o upstream chama o próprio arquivo de Relatorio-{tipo}-usina19-….pdf)")


def conferir_404(c: Confere, nome: str, status: int, corpo: str) -> None:
    """404 e nunca 403: "proibido" confirmaria que o documento existe, e quem trocou o número
    na URL não tem por que descobrir isso."""
    c(nome, status == 404, f"HTTP {status} — {corpo[:90]}")


# ── O caminho de verdade ────────────────────────────────────────────────────────────


def rodar(url: str, usina: int, competencia: str, c: Confere) -> None:
    token = token_do_cliente(2)
    sys.stdout.guardar(token)  # type: ignore[union-attr]
    cab = {"Authorization": f"Bearer {token}"}
    api = f"{url}/api/v1"

    print("\n▸ O índice do mês")
    r = httpx.get(f"{api}/manutencao/relatorios-mensais",
                  params={"usina_id": usina, "competencia": competencia},
                  headers=cab, timeout=60.0)
    if r.status_code != 200:
        raise Falhou(f"a lista respondeu HTTP {r.status_code}: {r.text[:300]}")
    itens = conferir_lista(c, r.json(), competencia)
    conferir_corte(c, r.text, "lista")

    por_tipo = {i["tipo"]: i for i in itens if i.get("tipo")}
    for tipo in ORDEM_ESPERADA:
        if tipo not in por_tipo:
            raise Falhou(
                f"não há relatório {tipo} liberado em {competencia} para a usina {usina} — "
                "libere-o no meuPlano (Gerado → A aprovar → Aprovado → Liberado p/ envio) "
                "antes de rodar esta conferência"
            )

    print("\n▸ O documento aberto")
    for tipo in ORDEM_ESPERADA:
        rid = por_tipo[tipo]["id"]
        d = httpx.get(f"{api}/manutencao/relatorios-mensais/{rid}", headers=cab, timeout=90.0)
        c(f"detalhe do {tipo} abre", d.status_code == 200,
          f"HTTP {d.status_code} rid={rid}")
        if d.status_code == 200:
            corpo = d.json()
            conteudo = corpo.get("conteudo") or {}
            c(f"o {tipo} vem com os números dentro", bool(conteudo.get("cronograma"))
              or bool(conteudo.get("pareceres")) or bool(conteudo.get("problemas")),
              f"blocos={sorted(k for k, v in conteudo.items() if v)[:6]}")
            c(f"o {tipo} traz a data de publicação", bool(corpo.get("liberado_em")),
              f"liberado_em={corpo.get('liberado_em')!r}")
            conferir_corte(c, d.text, f"detalhe {tipo}")

    print("\n▸ Os arquivos")
    nome_usina = ""
    for tipo in ORDEM_ESPERADA:
        rid = por_tipo[tipo]["id"]
        nome_usina = por_tipo[tipo].get("usina") or ""
        p, segundos = baixar_pdf(f"{api}/manutencao/relatorios-mensais/{rid}/pdf", cab, tipo)
        paginas, capa = (0, "")
        if p.status_code == 200 and p.content[:4] == b"%PDF":
            paginas, capa = abrir_pdf(p.content)
        conferir_arquivo(c, Arquivo(p.status_code, len(p.content), segundos,
                                    p.headers.get("content-disposition", ""),
                                    p.headers.get("cache-control", ""), paginas, capa),
                         tipo, competencia, nome_usina)

    print("\n▸ O corte, e as portas que têm de continuar fechadas")
    r = httpx.get(f"{api}/manutencao/relatorios-mensais/999999", headers=cab, timeout=60.0)
    conferir_404(c, "id inexistente", r.status_code, r.text)

    # A prova do CORTE por um caminho que não escreve nada: um relatório que EXISTE, é da
    # usina do próprio cliente, e não foi liberado. O 404 aqui não pode vir do escopo — a
    # usina é dele —, então só pode vir do status. É a armadilha desta leva, medida.
    nao_liberado = achar_nao_liberado(usina)
    if nao_liberado is None:
        c("relatório não liberado dá 404", False,
          "não achei no meuPlano um relatório desta usina fora de 'enviado'/'expedido' — "
          "a conferência mais importante deste script ficou sem sujeito")
    else:
        rid, estado = nao_liberado
        r = httpx.get(f"{api}/manutencao/relatorios-mensais/{rid}", headers=cab, timeout=60.0)
        conferir_404(c, f"relatório em '{estado}' não atravessa (rid {rid})",
                     r.status_code, r.text)
        r = httpx.get(f"{api}/manutencao/relatorios-mensais/{rid}/pdf", headers=cab,
                      timeout=60.0)
        conferir_404(c, f"e o PDF dele também não (rid {rid})", r.status_code, r.text)

    achado = outra_carteira(2)
    if achado is None:
        c("relatório de usina fora do vínculo dá 404", False,
          "não há neste banco outra conta sem esta usina para atravessar a cerca pelo "
          "outro lado — conferência sem sujeito")
    else:
        vizinho, caso = achado
        outro = token_do_cliente(vizinho)
        sys.stdout.guardar(outro)  # type: ignore[union-attr]
        rid = por_tipo[ORDEM_ESPERADA[0]]["id"]
        r = httpx.get(f"{api}/manutencao/relatorios-mensais/{rid}",
                      headers={"Authorization": f"Bearer {outro}"}, timeout=60.0)
        conferir_404(c, f"o mesmo rid {rid}, pedido por conta de outra carteira "
                        f"(usuário {vizinho}, {caso})", r.status_code, r.text)

    r = httpx.get(f"{api}/manutencao/relatorios-mensais", params={"usina_id": usina},
                  timeout=60.0)
    c("sem sessão não passa", r.status_code in (401, 403), f"HTTP {r.status_code}")


def achar_nao_liberado(usina: int) -> tuple[int, str] | None:
    """Um relatório desta usina que o meuPlano NÃO liberou — o sujeito da prova do corte.

    Vai à rota INTERNA do meuPlano de propósito: é o único lugar onde o não-liberado é
    visível, e é justamente por ele ser invisível na porta do cliente que a conferência
    existe. O BFF não conhece este caminho e não deve conhecer.
    """
    import asyncio

    from dotenv import load_dotenv

    load_dotenv(str(RAIZ / ".env"))
    from app.api.v1.plants import usinas_do_usuario
    from app.core.db import SessionLocal
    from app.models.user import User
    from app.services import integracoes

    async def procurar() -> tuple[int, str] | None:
        db = SessionLocal()
        try:
            dono = db.get(User, 2)
            link = next((u for u in usinas_do_usuario(db, dono) if u.id == usina), None)
            if link is None or not link.mp_usina_id:
                return None
            cliente = await integracoes.cliente_meuplano(db)
            for mes in ("2026-09", "2026-08", "2026-07"):
                painel = await cliente._get("/api/v1/meuacesso/relatorios", competencia=mes)
                for linha in painel.get("linhas") or []:
                    if linha.get("usina_id") != link.mp_usina_id:
                        continue
                    for especie in ("tecnico", "executivo"):
                        r = linha.get(especie) or {}
                        if r.get("id") and r.get("status") not in ("enviado", "expedido"):
                            return int(r["id"]), str(r.get("status"))
            return None
        finally:
            db.close()

    try:
        return asyncio.run(procurar())
    except Exception as exc:  # noqa: BLE001 — sem sujeito é notícia, não queda
        print(f"  (não deu para procurar um não-liberado no meuPlano: {exc})")
        return None


# ── `--provar`: ver o gate reprovar ─────────────────────────────────────────────────


def provar() -> int:
    """Alimenta as conferências com dado estragado e exige que cada uma REPROVE.

    Cada mutação é um defeito que já custou caro em algum lugar deste produto, não um
    exemplo inventado.
    """
    bom_item = {"id": 61, "usina_id": USINA_PADRAO, "usina": "Porto Ferreira",
                "competencia": COMPETENCIA_PADRAO, "tipo": "executivo",
                "liberado_em": "2026-09-06T16:18:46"}
    bom_tec = {**bom_item, "id": 14, "tipo": "tecnico"}
    bom_corpo = {"usina": "Porto Ferreira", "usina_id": USINA_PADRAO,
                 "itens": [bom_item, bom_tec], "aviso": None}
    bom_arq = Arquivo(200, 263_254, 2.07,
                      'inline; filename="Relatorio-mensal-tecnico-Porto-Ferreira-2026-08.pdf"; '
                      "filename*=UTF-8''Relatorio-mensal-tecnico-Porto%20Ferreira-2026-08.pdf",
                      "private, max-age=300", 9,
                      "SPLENDOR O&M RELATORIO TECNICO DE MANUTENCAO UFV PORTO FERREIRA "
                      "AGOSTO / 2026 CONTRATO #665")

    mutacoes: list[tuple[str, Callable[[Confere], None]]] = [
        ("o nome de quem aprovou vazando para a tela",
         lambda c: conferir_corte(
             c, '{"itens":[{"id":14,"aprovado_por":"renan@splendoroem.com.br"}]}', "lista")),
        ("um 'status' escondido lá dentro do conteúdo",
         lambda c: conferir_corte(
             c, '{"id":14,"conteudo":{"cabecalho":{"status_rotulo":"Liberado p/ envio"}}}',
             "detalhe")),
        ("o técnico listado antes do executivo",
         lambda c: conferir_lista(c, {**bom_corpo, "itens": [bom_tec, bom_item]},
                                  COMPETENCIA_PADRAO)),
        ("a lista de outro mês passando por este",
         lambda c: conferir_lista(c, {**bom_corpo, "itens": [{**bom_item,
                                                              "competencia": "2026-07"}]},
                                  COMPETENCIA_PADRAO)),
        ("só um dos dois documentos liberado, e ninguém reparando",
         lambda c: conferir_lista(c, {**bom_corpo, "itens": [bom_item]},
                                  COMPETENCIA_PADRAO)),
        ("a capa de julho num arquivo pedido de agosto",
         lambda c: conferir_arquivo(
             c, Arquivo(*[*bom_arq.__dict__.values()][:6],
                        "SPLENDOR O&M RELATORIO TECNICO JULHO / 2026"),
             "tecnico", COMPETENCIA_PADRAO, "Porto Ferreira")),
        ("um PDF de capa-só, que abre em branco",
         lambda c: conferir_arquivo(
             c, Arquivo(200, 31_792, 0.4, bom_arq.disposicao, bom_arq.cache, 1,
                        bom_arq.capa),
             "tecnico", COMPETENCIA_PADRAO, "Porto Ferreira")),
        ("o acento cru no cabeçalho, que derruba a resposta antes do CORS",
         lambda c: conferir_arquivo(
             c, Arquivo(200, 263_254, 2.0,
                        'inline; filename="Relatorio-mensal-tecnico-UFV SÍTIO-2026-08.pdf"',
                        bom_arq.cache, 9, bom_arq.capa),
             "tecnico", COMPETENCIA_PADRAO, "UFV SÍTIO")),
        ("os dois PDFs com o mesmo nome na pasta de Downloads",
         lambda c: conferir_arquivo(
             c, Arquivo(200, 263_254, 2.0,
                        'inline; filename="Relatorio-manutencao-Porto-Ferreira-2026-08.pdf"; '
                        "filename*=UTF-8''x", bom_arq.cache, 9, bom_arq.capa),
             "tecnico", COMPETENCIA_PADRAO, "Porto Ferreira")),
        ("o id do meuPlano vazando no nome do arquivo",
         lambda c: conferir_arquivo(
             c, Arquivo(200, 263_254, 2.0,
                        'inline; filename="Relatorio-mensal-tecnico-usina19-2026-08.pdf"; '
                        "filename*=UTF-8''x", bom_arq.cache, 9, bom_arq.capa),
             "tecnico", COMPETENCIA_PADRAO, "Porto Ferreira")),
        ("um relatório NÃO liberado abrindo com 200 — a armadilha desta leva",
         lambda c: conferir_404(c, "relatório em 'aprovado' não atravessa", 200, "{...}")),
        ("o 403 que confirma que o documento existe",
         lambda c: conferir_404(c, "id de outra carteira", 403, "Sem permissão")),
    ]

    print("── `--provar`: cada mutação abaixo TEM de reprovar ──")
    sobreviventes: list[str] = []
    for nome, aplicar in mutacoes:
        placar = Placar()
        print(f"\n  ▸ mutação: {nome}")
        try:
            aplicar(placar)
        except Exception as exc:  # noqa: BLE001 — explodir também é reprovar
            print(f"    (a conferência explodiu: {type(exc).__name__})")
            continue
        if not placar.falhas:
            sobreviventes.append(nome)
            print("    ⚠ NINGUÉM PEGOU — esta conferência é decoração")
    print()
    if sobreviventes:
        print(f"✗ {len(sobreviventes)} mutação(ões) passaram sem ser pegas:")
        for s in sobreviventes:
            print(f"    - {s}")
        return 1
    print(f"✓ as {len(mutacoes)} mutações foram todas pegas.")
    return 0


# ── main ────────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--url", help="BFF já no ar; sem isto, sobe um local")
    ap.add_argument("--usina", type=int, default=USINA_PADRAO,
                    help=f"id do vínculo NESTE sistema (padrão {USINA_PADRAO})")
    ap.add_argument("--competencia", default=COMPETENCIA_PADRAO, help="AAAA-MM")
    ap.add_argument("--provar", action="store_true",
                    help="não fala com ninguém: vê as conferências reprovarem")
    args = ap.parse_args()

    if args.provar:
        return provar()

    sys.stdout = SaidaLimpa(sys.stdout)  # type: ignore[assignment]
    placar = Placar()
    proc: subprocess.Popen[bytes] | None = None
    print(f"Conferindo o relatório mensal — usina {args.usina}, {args.competencia}")
    try:
        if args.url:
            url = args.url.rstrip("/")
            print(f"  BFF publicado: {url}")
        else:
            url, proc = subir_bff()
        rodar(url, args.usina, args.competencia, placar)
    except Falhou as exc:
        print(f"\n✗ {exc}")
        return 1
    finally:
        if proc is not None:
            proc.kill()

    print()
    if TROPECOS:
        # Nunca em silêncio: a segunda tentativa existe para o gate não ser um cara-ou-coroa,
        # não para fingir que o upstream respondeu de primeira.
        print(f"⚠ {len(TROPECOS)} tentativa(s) perdida(s) no caminho até o meuPlano:")
        for t in TROPECOS:
            print(f"    - {t}")
        print()
    if placar.falhas:
        print(f"✗ {len(placar.falhas)} de {placar.total} conferências falharam:")
        for f in placar.falhas:
            print(f"    - {f}")
        return 1
    print(f"✓ as {placar.total} conferências passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
