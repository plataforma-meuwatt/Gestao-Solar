"""Baixar os dados brutos da usina — a planilha que o cliente leva para o Excel.

O dono, sobre a aba Downloads que acabou de nascer no meuWatt: *"quero ter esses dados no
Gestão Solar"*. O portal não fala com a mw-api; estas duas rotas são a ponte.

Seis decisões moldam este arquivo, todas medidas contra a produção (Porto Ferreira,
7,4 MWp, 20 inversores) em 05/09/2026:

**O arquivo atravessa em FLUXO, não pela memória.** O teto absoluto do servidor é
~5,3 MiB (2.000.000 células × 2,78 bytes/célula, medidos), então o risco nunca foi *um*
arquivo — é N clientes × 5 MiB. `Response(content=…)`, o padrão dos PDFs unitários,
guardaria o corpo inteiro na memória deste processo E de novo no corpo do Starlette. É
exatamente o que `pacotes.py` recusou por escrito, e o desenho aqui é o dele:
`StreamingResponse` sobre `httpx.stream`, com a pilha aberta na função (para ler os
cabeçalhos e falhar cedo, com a frase do meuWatt) e fechada DENTRO do gerador — sem isso,
o cliente que desiste no meio deixa a conexão pendurada até o prazo de leitura.

Medido na rota REAL desta vez, e não contra a mw-api direto: o pior pedido que a mw-api
aceita (31 d × 5 min, todos os blocos) desceu 2.511.408 B (2,40 MiB) em 212 pedaços, e o
RSS do trabalhador subiu **368 KiB no pico — 15% do tamanho do arquivo**. Bufferizado, a
subida seria os 2,40 MiB inteiros, mais uma segunda cópia no corpo do Starlette.

⛔ Streaming aqui **não** serve para o cliente ver o arquivo mais cedo: medido, o cabeçalho
do meuWatt só chega em 35,6 s no pior pedido, porque a mw-api gera o XLSX inteiro
(`to_thread(write_xlsx)`) antes de responder, e o corpo transfere em 1,4 s. Serve para não
segurar os bytes.

**O pedido impossível morre AQUI, antes de queimar uma vaga do balde de todo mundo.** O
limite da mw-api é por IP (adiante), e — medido — **recusa também consome vaga**: dez
pedidos com a data invertida, que ela devolve em milissegundos sem gerar arquivo nenhum,
esgotam o minuto e o décimo primeiro pedido, perfeitamente válido, leva 429. O semáforo
abaixo não protege contra isso, porque a recusa atravessa depressa e devolve a vaga na
hora. Então o que é **aritmética nossa e certa** (`_impossivel`) é recusado antes de
qualquer ida ao upstream. O que NÃO entra nessa lista é tão importante quanto o que entra:
teto por passo, retenção e orçamento de células são do servidor, e repeti-los aqui criaria
dois números respondendo à mesma pergunta.

**As duas URLs vivem no CLIENTE, não aqui.** `MeuWattClient.export_options` e
`export_raw` montam os caminhos e carregam o prazo — que é explícito porque o padrão
REPROVA: o cliente é construído sem `timeout` em `integracoes.cliente_meuwatt` e cai nos
30 s da assinatura, contra 35,6 s medidos no pedido mais pesado que a mw-api aceita (e
28,1 s / 34,3 s em medições anteriores do MESMO pedido — a margem contra 30 s não é só
apertada, é instável, e na medição desta leva ela já não existe). Este router decide
**quem** pode pedir, **como**
a recusa é traduzida e **quantos** pedidos correm ao mesmo tempo — e nada mais. Caminho de
upstream mora em `clients/`, que é onde `tests/test_sonda.py` procura para exigir a linha no
catálogo da sonda: rota nova que nascesse aqui seria um ponto cego.

**O balde do meuWatt é por IP, não por token.** `rate_limit.py` de lá é
`Limiter(key_func=get_remote_address)` — o arquivo inteiro. Todo o portal sai pelo mesmo
egress do Railway, então são **10 exportações por minuto para todos os clientes somados**.
Medido nesta leva: o 11º POST do minuto respondeu 429, **sem `Retry-After`** e com o corpo em
`{"error": …}` — que `detalhe_do_upstream` não alcança, porque ele lê `detail`/`message`/
`erro`. Daí as três medidas deste arquivo: `_impossivel` (o pedido sem futuro nem chega
lá), `_VAGAS` (dois de cada vez, porque o `render.yaml` de lá fixa `workers=1` e as
consultas correm na sessão do pedido) e o 429 traduzido como ESPERA, nunca como erro. A
fila tem teto (`_ESPERA_MAX_SEG`): espera infinita
transforma uma vaga vazada num processo que atende dois downloads e nunca mais nenhum, sem
erro em lugar algum — foi o que aconteceu ao ensaiar a mutação que não devolvia a vaga, e a
suíte não falhou: ela parou.

⚠ **Achado para reportar ao meuWatt, e que este arquivo NÃO usa:** como o balde é por
endereço remoto e a mw-api confia no `X-Forwarded-For`, forjar esse cabeçalho zera o
balde — provado com o MESMO token, trocando só o endereço encaminhado: o 429 vira 200.
Usar isso seria abusar de um parceiro e quebraria no dia em que consertassem, então a
defesa daqui é a legítima: pedir menos (`_impossivel`) e enfileirar (`_VAGAS`).

**O `{slug}` é interpolado numa URL chamada com o PAT do dono** — a mesma forma que já custou
caro em `documents.py`, onde `../../../admin/users` normalizava e devolvia os bytes. Aqui ele
sai só de `PlantLink.mw_plant_slug`, resolvido pelo `usina_id` (int nosso) no banco, jamais do
corpo; e `_slug_do_upstream` ainda o confere contra um molde antes de montar a URL, porque
esse campo é digitado por gente no painel e a defesa tem de existir além de quem chama.

**O motivo do upstream é PRESERVADO; quem traduz é a tela.** A mw-api recusa com
`{"detail": {"motivo", "message"}}` — `motivo` num vocabulário fechado (`periodo_invalido`,
`passo_excede_limite`, `fora_da_retencao`, `bloco_indisponivel`, `sem_blocos`,
`muito_grande`) e `message` escrita para o operador DE LÁ, que fala em balde, snapshots e
SSU. O código e o `motivo` atravessam; a frase do cliente nasce no portal, como já se
decidiu para `classificacao`/`situacao`.

Router próprio, e não um bloco em `energia.py` ou `manutencao.py`: nenhum dos dois é sobre
exportação, e os dois estão sendo alterados em paralelo. Daqui só se importa o que já é fonte
única — o resolvedor de vínculo do lado meuWatt e a redução do nome a ASCII.
"""

import asyncio
import re
from contextlib import AsyncExitStack
from datetime import date
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.manutencao import _erro_do_upstream, _nome_ascii
from app.api.v1.plants import _usina_no_escopo
from app.clients.meuwatt import MeuWattClient
from app.core.datas import hoje
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · energia"])

#: O nome do produto na frase de falha. `_erro_do_upstream` o usa para não apontar o dedo
#: para o serviço errado — uma queda do monitoramento não pode chegar como "a manutenção
#: respondeu 500".
MONITORAMENTO = "monitoramento"

#: Quantas exportações este processo deixa correr ao mesmo tempo contra o meuWatt.
#:
#: Dois, e não "quantas vierem": o `render.yaml` da mw-api fixa `workers=1`, o XLSX sai do
#: event loop por `to_thread` mas as CONSULTAS correm na sessão do pedido, e o balde de lá é
#: de 10/minuto **por IP** — todo o portal sai pelo mesmo endereço. Sem esta fila, dez
#: cliques simultâneos queimam sozinhos a cota de todos os clientes e o décimo primeiro
#: cliente do minuto leva um 429 que ninguém provocou.
#:
#: A vaga é segurada da abertura do fluxo até o último pedaço sair (entra na `AsyncExitStack`),
#: o que na prática é quase o mesmo que segurá-la até o cabeçalho: medido, o corpo transfere
#: em 1,4 s depois de 35,6 s de geração.
#:
#: ⚠ E a fila NÃO é a defesa contra o balde: uma recusa atravessa em milissegundos, devolve a
#: vaga na hora e mesmo assim gastou um dos dez pedidos do minuto. Quem cuida disso é
#: `_impossivel`, antes daqui.
_VAGAS = asyncio.Semaphore(2)

#: Quanto tempo um pedido espera NA FILA antes de desistir e pedir para tentar de novo.
#:
#: A espera não pode ser infinita. Sem teto, o terceiro cliente fica pendurado enquanto
#: houver movimento — e, se uma vaga vazar por defeito, para sempre: o processo atende dois
#: downloads e nunca mais nenhum, sem erro em lugar nenhum. Foi exatamente o que aconteceu
#: aqui ao ensaiar a mutação que não devolvia a vaga na recusa: a suíte não falhou, ela
#: PAROU.
#:
#: A conta: a geração mais pesada que a mw-api aceita levou 35,6 s de cabeçalho + 1,4 s de
#: corpo (medição desta leva; antes 28,1 s e 34,3 s), então 45 s cobrem uma geração inteira à
#: frente na fila. Somados aos 120 s de leitura, o pior caso responde em ~165 s — dentro dos
#: 180 s que o cliente espera. Estourou, sai a MESMA frase do 429 do upstream, porque é a
#: mesma coisa: espere e tente de novo.
_ESPERA_MAX_SEG = 45.0

#: O molde de um slug de usina no meuWatt (`porto-ferreira`,
#: `ufv-ouro-fino-eldorado-energia`). Confere-se o valor do NOSSO banco antes de interpolá-lo
#: na URL do upstream porque ele é digitado por gente na tela de Conexões, e a lição de
#: `documents.py` é que a defesa tem de existir também no lugar que monta a URL.
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")

#: Os motivos que a mw-api sabe dar. Lista fechada para que um valor novo lá não atravesse
#: cru até a tela, que não saberia traduzi-lo — e para que o portal possa exaurir o `switch`.
MOTIVOS = (
    "periodo_invalido",
    "passo_excede_limite",
    "fora_da_retencao",
    "bloco_indisponivel",
    "sem_blocos",
    "muito_grande",
)

#: Motivo nosso, não do upstream: o balde de 10/minuto estourou. Não é erro do pedido — é
#: espera —, e por isso tem nome próprio em vez de virar mais um 502.
MOTIVO_ESPERA = "muitos_pedidos"

#: O maior valor da tabela `MAX_DAYS` da mw-api — `{native: 7, 5m: 31, 15m: 92, 1h: 366,
#: 1d: 366}`, lido de `limites` nas opções de Porto Ferreira em 05/09/2026. Acima dele
#: **nenhum** passo aceita o pedido, então recusá-lo aqui não é adivinhar o teto do servidor:
#: é saber que não existe teto que o comporte.
#:
#: ⛔ Só se recusa ESTRITAMENTE ACIMA. Um pedido de exatamente 366 dias sobe, e é o servidor
#: quem diz se o passo escolhido o comporta — o teto POR PASSO vem em `limites` e é a tela
#: que o aplica, porque repeti-lo aqui daria dois números para a mesma pergunta.
#:
#: ⚠ Esta constante é ACOPLADA ao produto de lá, e o acoplamento tem um único sentido de
#: falha: se a mw-api SUBIR o maior teto e ninguém tocar nesta linha, um pedido que ela
#: aceitaria é recusado aqui. Se ela BAIXAR, nada quebra — o pedido sobe e ela recusa com o
#: motivo próprio. O conserto é uma linha, e o teste `test_o_maior_teto_conhecido_passa`
#: existe para o dia em que alguém vier ler.
_DIAS_TETO_CONHECIDO = 366


# ══════════════════════════════════════════════════════════════════════════════
# O pedido — espelho tipado de `RawExportRequest` (mw-api, src/exports/schemas.py)
# ══════════════════════════════════════════════════════════════════════════════
#
# Tipado, e não `dict` repassado cru: o upstream valida, mas o BFF não pode ser o lugar por
# onde entra o que ninguém olhou. Os `Literal` são os mesmos de lá — se a mw-api ganhar uma
# variável nova, esta lista tem de crescer de propósito, e não por descuido.

VarInversor = Literal["geracao", "potencia", "status", "paradas"]
VarEstacao = Literal[
    "poa", "ghi", "temp_modulo", "temp_ambiente", "vento", "temp_ambiente_rele"
]
VarFronteira = Literal["energia"]
VarSistema = Literal["pr", "produtividade"]

#: Os cinco passos, do mais fino ao mais grosso. O teto de dias de cada um vem nas opções
#: (`limites`), não daqui: quem manda no teto é o servidor, e repeti-lo aqui criaria dois
#: números respondendo à mesma pergunta.
Passo = Literal["native", "5m", "15m", "1h", "1d"]

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class InversoresIn(BaseModel):
    variaveis: list[VarInversor] = Field(min_length=1, max_length=4)
    agrupamento: Literal["lista", "skid"] = "lista"
    #: As chaves que as opções devolveram (`slot:170`, `inv:7`).
    #:
    #: ⛔ **Nulo é diferente de "listei todas".** Nulo significa "não mexi": o inversor
    #: comissionado no meio do período entra sozinho. Uma lista explícita congela o
    #: conjunto no que a tela viu. Por isso o campo é opcional e nunca ganha um default de
    #: lista vazia — que o upstream leria como "nenhuma série", um arquivo sem colunas.
    series: list[str] | None = Field(default=None, max_length=500)


class EstacaoIn(BaseModel):
    variaveis: list[VarEstacao] = Field(min_length=1, max_length=6)


class FronteiraIn(BaseModel):
    variaveis: list[VarFronteira] = Field(default=["energia"], min_length=1, max_length=1)
    agrupamento: Literal["leitor", "usina"] = "leitor"


class SistemaIn(BaseModel):
    variaveis: list[VarSistema] = Field(min_length=1, max_length=2)
    agrupamento: Literal["skid", "usina"] = "usina"


class PedidoIn(BaseModel):
    """A seleção: período + horário + passo + os quatro blocos, todos opcionais.

    Bloco ausente não entra no arquivo. Nenhum bloco = `sem_blocos`, e é o upstream que
    recusa — repetir a regra aqui daria duas respostas para a mesma pergunta no dia em que
    uma das duas mudasse.
    """

    inicio: date
    fim: date
    #: Horário do PRIMEIRO e do ÚLTIMO dia, em BRT. A janela é contínua e o fim é inclusivo
    #: do minuto (`23:59` = até o fim do dia). O upstream os ignora quando o passo é `1d`.
    hora_inicio: str = "00:00"
    hora_fim: str = "23:59"
    passo: Passo = "15m"

    inversores: InversoresIn | None = None
    estacao: EstacaoIn | None = None
    fronteira: FronteiraIn | None = None
    sistema: SistemaIn | None = None

    @field_validator("hora_inicio", "hora_fim")
    @classmethod
    def _hora(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("horário deve ser HH:MM (00:00–23:59)")
        return v

    def para_o_upstream(self) -> "_PedidoUpstream":
        """O mesmo pedido no vocabulário da mw-api (`RawExportRequest`).

        A tradução mora aqui, num lugar só, pelo mesmo motivo de sempre: o portal fala o
        nosso vocabulário e nunca o de lá, e o dia em que a mw-api renomear um campo há de
        ser um dia em que uma linha muda, não cinco telas.

        Devolve um MODELO e não um `dict` porque é isso que `MeuWattClient.export_raw`
        recebe — e o cliente serializa com `exclude_none=True`, que é o que faz bloco
        ausente e `series` nula sumirem da chave em vez de viajarem como `null`. Os quatro
        blocos são reaproveitados tal como estão: `variaveis`, `agrupamento` e `series` já
        são os nomes de lá, então não há nada a traduzir dentro deles — e uma segunda cópia
        "upstream" dos mesmos campos seria a régua que um dia divergiria.
        """
        return _PedidoUpstream(
            start_date=self.inicio,
            end_date=self.fim,
            start_time=self.hora_inicio,
            end_time=self.hora_fim,
            step=self.passo,
            inversores=self.inversores,
            estacao=self.estacao,
            fronteira=self.fronteira,
            sistema=self.sistema,
        )


class _PedidoUpstream(BaseModel):
    """`RawExportRequest` da mw-api, montado aqui a partir do nosso.

    Existe para que nada além do contrato de lá suba: campo que este modelo não conhece é
    descartado na porta, e o corpo do POST — a única coisa que o cliente controla livremente
    — nunca chega perto de virar URL nem de viajar como se fosse do contrato. É a segunda
    tranca do defeito de `documents.py`, ao lado do slug que só sai do `PlantLink`.
    """

    start_date: date
    end_date: date
    start_time: str
    end_time: str
    step: Passo
    inversores: InversoresIn | None = None
    estacao: EstacaoIn | None = None
    fronteira: FronteiraIn | None = None
    sistema: SistemaIn | None = None


# ══════════════════════════════════════════════════════════════════════════════
# As opções — o que ESTA usina tem
# ══════════════════════════════════════════════════════════════════════════════


class SerieOut(BaseModel):
    """Um inversor exportável."""

    #: Transporte, não texto de tela: é o que volta em `InversoresIn.series`. A tela mostra
    #: `rotulo`. Ninguém acorda querendo `slot:170`.
    chave: str
    rotulo: str
    numero_serie: str | None = None
    capacidade_kwp: float | None = None


class SkidOut(BaseModel):
    id: int | None = None
    nome: str
    capacidade_kwp: float | None = None
    series: list[SerieOut] = []


class EstacaoOut(BaseModel):
    disponivel: bool = False
    #: Coluna → tem dado. Dicionário aberto de propósito: a mw-api já devolve `umidade`, que
    #: não está entre as variáveis exportáveis (medido em 05/09/2026), e enquadrar isto num
    #: `Literal` faria a chave sumir em silêncio no dia em que ela virasse exportável.
    colunas: dict[str, bool] = {}
    #: A mesma grandeza de `temp_ambiente` vinda do relé, quando existe. Distinção de
    #: operador — vive no Avançado da tela.
    temp_ambiente_rele: bool = False


class LeitorOut(BaseModel):
    """Um medidor de fronteira. Só id e nome: `wh_per_pulse`, `rtc` e `rtp` são parâmetros
    de calibração do equipamento, não escolha de quem baixa a planilha."""

    id: int
    nome: str | None = None


class SistemaOut(BaseModel):
    pr: bool = False
    produtividade: bool = False


class RetencaoOut(BaseModel):
    """Até onde o acervo alcança — e isto NÃO é limite do arquivo, é ausência de dado.

    Antes de `snapshots_desde` a leitura fina não existe mais; antes de `ssu_desde`, a do
    medidor. Os nomes são os do upstream de propósito: quem lê o código aqui e o de lá está
    olhando a mesma coisa. A saída existe e o próprio servidor a garante — a checagem inteira
    de retenção está dentro de `if step != "1d"`, então o TOTAL POR DIA não tem prazo.
    """

    snapshots_desde: date | None = None
    ssu_desde: date | None = None


class UsinaOut(BaseModel):
    """A usina, com o nome DESTE sistema.

    O `plant.name` do meuWatt fica de fora: a mesma usina não pode sair com um nome aqui e
    outro na aba ao lado, e o nome que o cliente reconhece é o do vínculo. O `slug` também
    não sai — é transporte para o upstream, não informação de tela.
    """

    id: int
    nome: str
    capacidade_kwp: float | None = None


class OpcoesOut(BaseModel):
    """O que a aba "Baixar dados" pode oferecer nesta usina, e com que tetos.

    É o que permite à tela desabilitar o impossível **dizendo o motivo** em vez de sumir com
    a linha: usina sem estação solarimétrica não tem irradiação, e sem irradiação não há PR.
    """

    usina: UsinaOut
    skids: list[SkidOut] = []
    estacao: EstacaoOut = EstacaoOut()
    leitores: list[LeitorOut] = []
    sistema: SistemaOut = SistemaOut()
    retencao: RetencaoOut = RetencaoOut()
    #: Teto de dias por passo (`native`, `5m`, `15m`, `1h`, `1d`) e `max_celulas`. Vêm do
    #: servidor e não de uma constante nossa: dois números para a mesma pergunta divergiriam
    #: no primeiro ajuste feito do outro lado.
    limites: dict[str, int] = {}


# ══════════════════════════════════════════════════════════════════════════════
# Ferramentas
# ══════════════════════════════════════════════════════════════════════════════


def _slug_do_upstream(link: PlantLink) -> str:
    """O slug desta usina no meuWatt, conferido antes de virar URL.

    404 e não 403 para a usina sem monitoramento: é o mesmo tom de `_usina_no_escopo`, e o
    cliente que só tem manutenção contratada não precisa descobrir que existe uma ponte.
    """
    slug = (link.mw_plant_slug or "").strip()
    if not slug:
        raise HTTPException(404, "Esta usina não está ligada ao monitoramento.")
    if not _SLUG.match(slug):
        # Nunca aconteceu, e é para continuar assim: o campo é digitado no painel, e um
        # `../../../admin/users` aqui normalizaria para outra rota da mw-api chamada com o
        # token de serviço — foi literalmente o buraco que `documents.py` fechou.
        raise HTTPException(502, "O vínculo desta usina com o monitoramento está inválido.")
    return slug


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    limpo = str(valor).strip()
    return limpo or None


def _numero(valor: Any) -> float | None:
    """Número com casas, ou nada. `bool` sai fora antes: em Python `True` vira `1.0` sem
    reclamar, e uma capacidade de 1 kWp seria pior que capacidade nenhuma."""
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _inteiro(valor: Any) -> int | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _data(valor: Any) -> date | None:
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


async def _cliente(db: Session) -> MeuWattClient:
    """O cliente do meuWatt, ou a frase que diz que a ponte não está de pé.

    A montagem das duas URLs de exportação vive em `clients/meuwatt.py` (`export_options` e
    `export_raw`), e não aqui: `tests/test_sonda.py` lê a árvore sintática daquele arquivo e
    exige uma linha no catálogo da sonda para todo caminho que encontrar — é assim que uma
    rota nova não vira ponto cego. Este router só decide QUEM pode pedir, COMO a recusa é
    traduzida e QUANTOS pedidos correm ao mesmo tempo.
    """
    try:
        return await integracoes.cliente_meuwatt(db)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Monitoramento indisponível: {exc}") from exc


async def _soltar_vaga() -> None:
    """Devolve a vaga da fila. Entra na `AsyncExitStack` junto com o fluxo, e é por isso que
    ela volta em TODOS os caminhos: sucesso, recusa, falha de ponte e cliente que desistiu no
    meio do download."""
    _VAGAS.release()


def _espere() -> JSONResponse:
    """"Espere e tente de novo" — a resposta da fila cheia e a do balde do meuWatt.

    Uma frase só para as duas, porque para quem pediu é a mesma situação: nada está quebrado,
    o pedido continua válido, e repeti-lo daqui a pouco funciona. É o oposto de um
    `muito_grande`, onde repetir dá exatamente o mesmo resultado.
    """
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                "O monitoramento está atendendo muitos pedidos agora. Tente em um minuto."
            ),
            "motivo": MOTIVO_ESPERA,
        },
        # O balde do meuWatt é declarado como "10/minute" e não manda `Retry-After` (medido:
        # `None`). O que viaja aqui é o TETO da janela, não o tempo exato de espera.
        headers={"Retry-After": "60", "Cache-Control": "no-store"},
    )


def _recusa(resposta: httpx.Response) -> JSONResponse | None:
    """A recusa do meuWatt no nosso formato — ou `None` quando não é uma recusa dele.

    Corpo achatado (`{"detail", "motivo"}`) e não `HTTPException`, que embrulharia tudo
    dentro de `detail`: a tela precisa do `motivo` no primeiro nível para escolher entre
    `Erro` (com "Tentar de novo") e `Aviso` (sem) — repetir um `muito_grande` daria
    exatamente o mesmo resultado, e oferecer o botão seria crueldade.

    ⛔ O `message` do upstream NÃO é ecoado. Ele foi escrito para o operador da mw-api e fala
    em balde, snapshots e SSU; quem escreve para o cliente é o portal.
    """
    status = resposta.status_code
    if status == 429:
        # Medido em 05/09/2026: o corpo vem em `{"error": …}` — que `detalhe_do_upstream`
        # não alcança, porque ele lê `detail`/`message`/`erro` — e SEM `Retry-After`.
        return _espere()
    if status != 400:
        return None
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    detalhe = corpo.get("detail") if isinstance(corpo, dict) else None
    if not isinstance(detalhe, dict):
        return None
    motivo = _texto(detalhe.get("motivo"))
    return JSONResponse(
        status_code=400,
        content={
            "detail": "O monitoramento recusou este pedido.",
            # Só o vocabulário conhecido atravessa: um motivo novo lá chegaria à tela como
            # uma frase que ela não sabe traduzir, e o cliente leria a palavra crua.
            "motivo": motivo if motivo in MOTIVOS else None,
        },
        headers={"Cache-Control": "no-store"},
    )


def _impedimento(motivo: str, frase: str) -> JSONResponse:
    """A recusa que nasce AQUI, na mesma forma da que nasce lá (`{"detail", "motivo"}`).

    Mesmo formato de propósito: para a tela as duas são a mesma coisa — um pedido que não
    pode ser atendido, com um código no vocabulário fechado de `MOTIVOS` para ela traduzir.
    Um segundo formato obrigaria o portal a ter dois caminhos de leitura para a mesma
    decisão, e o segundo é sempre o que alguém esquece.

    ⛔ A frase NÃO diz "o monitoramento recusou": aqui ninguém perguntou nada a ele. A
    diferença importa no dia em que alguém ler um registro e for procurar do lado errado.
    """
    return JSONResponse(
        status_code=400,
        content={"detail": frase, "motivo": motivo},
        headers={"Cache-Control": "no-store"},
    )


def _impossivel(pedido: PedidoIn) -> JSONResponse | None:
    """O pedido que não tem futuro — recusado antes de tocar o upstream, ou `None`.

    **Por que existir, se a mw-api já valida tudo isto?** Porque a validação de lá custa uma
    das dez vagas do minuto, e o balde é **por IP**: todo o portal sai pelo mesmo egress do
    Railway. Medido em 05/09/2026: dez pedidos com a data invertida — que ela recusa em
    milissegundos, sem gerar arquivo nenhum — esgotam o minuto, e o décimo primeiro pedido,
    válido, de outro cliente, leva 429. O semáforo `_VAGAS` não protege contra isso: a recusa
    atravessa depressa e devolve a vaga na hora. A defesa tem de ser a recusa antecipada.

    **O que entra aqui é só o que é ARITMÉTICA NOSSA E CERTA** — o que não depende de
    conhecer a usina, o acervo nem a tabela de tetos do outro lado:

    - `periodo_invalido` — fim antes do início, começo no futuro, e (fora do passo diário) a
      janela que fecha antes de abrir. As três são as mesmas contas de `validate_request`, com
      o mesmo `hoje` em BRT (`core.datas`), que é o fuso das usinas e o do servidor de lá.
    - `passo_excede_limite` — acima do maior teto que QUALQUER passo tem. Ver
      `_DIAS_TETO_CONHECIDO`: recusa-se estritamente acima, nunca o teto por passo.
    - `sem_blocos` — os quatro blocos ausentes. Bloco presente e vazio (`variaveis: []`) já
      morre um degrau antes, no `min_length=1` do modelo.

    **O que NÃO entra, e é decisão, não esquecimento:** retenção (é do acervo daquela usina),
    orçamento de células (é estimativa do servidor sobre o tamanho do arquivo) e o teto por
    passo (vem em `limites`, e é a TELA que o aplica). Repetir qualquer um deles aqui criaria
    dois números respondendo à mesma pergunta — e o daqui seria o que envelhece calado.
    """
    if pedido.fim < pedido.inicio:
        return _impedimento(
            "periodo_invalido", "A data final é anterior à inicial."
        )
    if pedido.inicio > hoje():
        # `hoje()` é o dia na USINA (BRT), não no contêiner (UTC). Com `date.today()`, das
        # 21h à meia-noite de Brasília o servidor já virou o dia e passaria a recusar um
        # pedido que começa hoje — o mesmo defeito que `core/datas.py` existe para não
        # repetir.
        return _impedimento("periodo_invalido", "O período começa no futuro.")
    if pedido.passo != "1d" and pedido.inicio == pedido.fim:
        # A janela é contínua e o fim é INCLUSIVO do minuto, então a inversão de horário só
        # fecha a janela quando é o mesmo dia: com o fim um dia à frente, qualquer hora
        # produz uma janela positiva. É a mesma conta de `build_window` — feita sobre o texto
        # `HH:MM`, que o validador do modelo já garantiu, e por isso comparável como texto.
        if pedido.hora_fim < pedido.hora_inicio:
            return _impedimento(
                "periodo_invalido", "O horário final é anterior ao inicial."
            )
    dias = (pedido.fim - pedido.inicio).days + 1
    if dias > _DIAS_TETO_CONHECIDO:
        return _impedimento(
            "passo_excede_limite",
            f"Nenhum passo aceita {dias} dias num arquivo só.",
        )
    if not any(
        (pedido.inversores, pedido.estacao, pedido.fronteira, pedido.sistema)
    ):
        return _impedimento(
            "sem_blocos", "Escolha ao menos um equipamento e uma variável."
        )
    return None


def _nome_do_arquivo(link: PlantLink, pedido: PedidoIn) -> str:
    """`dados-porto-ferreira-2026-08-01_2026-08-31-1h.xlsx`.

    O nome do vínculo é reduzido a ASCII pela mesma razão do pacote de fichas: cabeçalho HTTP
    é latin-1 no Starlette, e "Ribeirão Bonito" derrubaria a resposta ANTES do CORS — o
    navegador veria "falha de rede" e o cliente acusaria a própria internet por um defeito
    nosso. O `filename*` logo abaixo devolve o nome bonito a quem sabe lê-lo.

    O nome do upstream (`meuwatt_<slug>_…`) não é reaproveitado: o arquivo que o cliente
    arquiva leva o nome do produto que ele abriu, não o do sistema que o gerou.
    """
    usina = _nome_ascii(link.nome).removesuffix(".pdf").lower() or "usina"
    periodo = (
        pedido.inicio.isoformat()
        if pedido.inicio == pedido.fim
        else f"{pedido.inicio.isoformat()}_{pedido.fim.isoformat()}"
    )
    return f"dados-{usina}-{periodo}-{pedido.passo}.xlsx"


# ══════════════════════════════════════════════════════════════════════════════
# Rotas
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/energia/dados/opcoes", response_model=OpcoesOut)
async def opcoes_de_exportacao(
    usina_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> OpcoesOut:
    """O que esta usina tem para exportar, e com que tetos.

    Responde ANTES de qualquer pedido de arquivo, de propósito: é com isto que a tela
    desabilita o impossível **dizendo por quê** — usina sem estação solarimétrica não tem
    irradiação, e sem irradiação não se calcula PR. Sumir com a linha faria o cliente
    concluir que o portal não oferece, quando o fato é sobre a usina dele.

    ⚠ `_usina_no_escopo` (de `plants.py`) e não `_link_do_escopo` (de `manutencao.py`): o
    segundo exige `mp_usina_id` e recusa com "esta usina não tem manutenção contratada" —
    frase e regra de outro produto. Isto aqui é geração; a usina monitorada SEM contrato de
    manutenção tem direito aos próprios números. Hoje as seis usinas monitoradas do banco
    também têm meuPlano, o que faria o defeito passar despercebido por muito tempo.
    """
    link = _usina_no_escopo(db, usuario, usina_id)
    slug = _slug_do_upstream(link)
    cliente = await _cliente(db)

    try:
        bruto = await cliente.export_options(slug)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(
            exc, "Não deu para ver o que esta usina tem para exportar", MONITORAMENTO
        ) from exc

    if not isinstance(bruto, dict):
        raise HTTPException(502, "O monitoramento respondeu num formato inesperado.")
    return _opcoes(link, bruto)


def _opcoes(link: PlantLink, bruto: dict[str, Any]) -> OpcoesOut:
    """`RawExportOptions` da mw-api → o nosso formato. Fora da rota para ser testável sem rede."""
    usina_bruta = bruto.get("plant") if isinstance(bruto.get("plant"), dict) else {}
    estacao = bruto.get("estacao") if isinstance(bruto.get("estacao"), dict) else {}
    fronteira = bruto.get("fronteira") if isinstance(bruto.get("fronteira"), dict) else {}
    sistema = bruto.get("sistema") if isinstance(bruto.get("sistema"), dict) else {}
    retencao = bruto.get("retencao") if isinstance(bruto.get("retencao"), dict) else {}

    skids: list[SkidOut] = []
    for s in bruto.get("skids") or []:
        if not isinstance(s, dict):
            continue
        series = [
            SerieOut(
                chave=str(x["key"]),
                rotulo=_texto(x.get("label")) or str(x["key"]),
                numero_serie=_texto(x.get("serial_number")),
                capacidade_kwp=_numero(x.get("capacity_kwp")),
            )
            for x in (s.get("slots") or [])
            if isinstance(x, dict) and _texto(x.get("key"))
        ]
        skids.append(
            SkidOut(
                id=_inteiro(s.get("id")),
                nome=_texto(s.get("name")) or "Sem conjunto",
                capacidade_kwp=_numero(s.get("capacity_kwp")),
                series=series,
            )
        )

    colunas = estacao.get("colunas")
    leitores = [
        LeitorOut(id=int(x["id"]), nome=_texto(x.get("name")))
        for x in (fronteira.get("leitores") or [])
        if isinstance(x, dict) and _inteiro(x.get("id")) is not None
    ]
    limites = {
        str(k): v
        for k, v in (bruto.get("limites") or {}).items()
        if _inteiro(v) is not None
    }

    return OpcoesOut(
        usina=UsinaOut(
            id=link.id,
            nome=link.nome,
            capacidade_kwp=_numero(usina_bruta.get("capacity_kwp")),
        ),
        skids=skids,
        estacao=EstacaoOut(
            disponivel=bool(estacao.get("disponivel")),
            colunas={str(k): bool(v) for k, v in colunas.items()}
            if isinstance(colunas, dict)
            else {},
            temp_ambiente_rele=bool(estacao.get("temp_ambiente_rele")),
        ),
        leitores=leitores,
        sistema=SistemaOut(
            pr=bool(sistema.get("pr")), produtividade=bool(sistema.get("produtividade"))
        ),
        retencao=RetencaoOut(
            snapshots_desde=_data(retencao.get("snapshots_desde")),
            ssu_desde=_data(retencao.get("ssu_desde")),
        ),
        limites={k: int(v) for k, v in limites.items()},
    )


@router.post("/energia/dados/arquivo")
async def arquivo_de_dados(
    pedido: PedidoIn,
    usina_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """A planilha desta seleção, em fluxo.

    ⚠ **POST que só LÊ.** O método é por TAMANHO DA SELEÇÃO — quinhentas chaves de série não
    cabem numa query string —, nunca por efeito: nada é criado, alterado ou apagado aqui, nem
    deste lado nem no meuWatt (a rota de lá é `resolve_plant_access`, sem escrita). Fica dito
    para o dia em que entrar auditoria por método e este verbo mentir sozinho.

    O XLSX não é remontado. Ele nasce no meuWatt, que é quem tem as séries e a aba "Leia-me"
    com unidades, fontes e avisos — e é essa aba que permite a tela ser curta. Aqui os bytes
    só atravessam.
    """
    link = _usina_no_escopo(db, usuario, usina_id)
    slug = _slug_do_upstream(link)
    # ⛔ ANTES do cliente e ANTES da vaga. O pedido impossível não pode gastar um dos dez
    # pedidos por minuto que o meuWatt concede ao IP inteiro do portal — e a ordem é a única
    # coisa que garante isso: escopo (quem é), vínculo (existe ponte), aritmética (faz
    # sentido) e só então a rede.
    impossivel = _impossivel(pedido)
    if impossivel is not None:
        return impossivel
    cliente = await _cliente(db)

    # A pilha tem de sobreviver a esta função: ela só fecha quando o último pedaço sair. Por
    # isso é aberta aqui — para ler os cabeçalhos e falhar cedo, com a recusa do meuWatt na
    # mão — e fechada dentro do gerador. A VAGA entra na mesma pilha: solta junto, inclusive
    # quando o cliente desiste no meio.
    pilha = AsyncExitStack()
    try:
        try:
            await asyncio.wait_for(_VAGAS.acquire(), _ESPERA_MAX_SEG)
        except TimeoutError:
            # A fila deste processo está cheia. Não é defeito e não é o balde do meuWatt —
            # mas para quem pediu é a mesma coisa, e a frase é a mesma.
            return _espere()
        pilha.push_async_callback(_soltar_vaga)
        resposta = await pilha.enter_async_context(
            cliente.export_raw(slug, pedido.para_o_upstream())
        )
    except httpx.HTTPStatusError as exc:
        # O cliente já leu o corpo do erro antes de levantar — é JSON curto, e é onde mora a
        # razão. Recusa de REGRA e limite de pedidos saem com o código e o motivo do
        # upstream; o resto é falha de ponte.
        await pilha.aclose()
        recusa = _recusa(exc.response)
        if recusa is not None:
            return recusa
        raise _erro_do_upstream(exc, "Não deu para baixar os dados", MONITORAMENTO) from exc
    except Exception as exc:  # noqa: BLE001
        await pilha.aclose()
        raise _erro_do_upstream(exc, "Não deu para baixar os dados", MONITORAMENTO) from exc

    nome = _nome_do_arquivo(link, pedido)
    cabecalhos = {
        # `attachment`: o destino de uma planilha é a pasta de downloads, não um
        # visualizador. Dois nomes — o ASCII para qualquer cliente, o `filename*` em UTF-8
        # para quem sabe lê-lo. `Content-Disposition` já está exposto ao JavaScript pelo CORS
        # (`pacotes.CABECALHOS_EXPOSTOS`, em `main.py`); sem isso o portal, que roda em outro
        # domínio, receberia o corpo e não enxergaria o nome.
        "Content-Disposition": (
            f'attachment; filename="{nome}"; filename*=UTF-8\'\'{quote(nome, safe="")}'
        ),
        # A planilha é montada sob demanda e muda com o acervo: guardá-la entregaria números
        # velhos a quem acabou de pedir de novo.
        "Cache-Control": "no-store",
    }
    # `Content-Length` só é repassado quando o corpo sai daqui do mesmo tamanho que entrou.
    # `aiter_bytes()` devolve os bytes JÁ DECODIFICADOS: se um proxy no meio comprimiu o
    # XLSX, o comprimento do cabeçalho é o do comprimido e o corpo é o do original — e o
    # navegador cortaria a planilha no número prometido, arquivo corrompido e nenhum erro na
    # tela. Sem o cabeçalho a barra fica cega, que é o mal menor.
    codificacao = (resposta.headers.get("content-encoding") or "identity").strip().lower()
    tamanho = resposta.headers.get("content-length")
    if tamanho and codificacao in ("", "identity"):
        cabecalhos["Content-Length"] = tamanho

    async def corpo():
        # `async with` e não um `aclose()` no fim: o cliente desiste de um download de
        # megabytes, o gerador é fechado à força, e sem o contexto a conexão com o meuWatt
        # ficaria pendurada até o prazo de leitura — segurando também a vaga do semáforo,
        # que é o que estrangularia todo o portal.
        async with pilha:
            async for pedaco in resposta.aiter_bytes():
                yield pedaco

    return StreamingResponse(
        corpo(),
        media_type=(
            resposta.headers.get("content-type")
            or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers=cabecalhos,
    )
