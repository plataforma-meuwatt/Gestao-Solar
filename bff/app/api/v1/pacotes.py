"""Baixar TODAS as fichas de um período — o pacote de PDFs da manutenção.

O dono, sobre a inspeção de agosto de Porto Ferreira: *"eu fiz a inspeção de agosto de
Porto Ferreira; de alguma forma eu preciso conseguir baixar TODOS os PDFs das tarefas. Se
eu fizer corretiva, quero poder ver também. Preciso de filtros."* Hoje o portal baixa um
arquivo por clique, e a OS 1016 tem dezessete tarefas.

Quatro decisões que moldam este arquivo:

**"Todos" é todos.** O pedido não admite pacote parcial — baixar dezessete e receber três
seria pior que não ter o botão, porque ninguém confere. Por isso o caminho tem três atos
separados: **inventariar** (quantas fichas o filtro pegou, quantas já têm PDF e em quantas
partes o pacote sai), **preparar** (mandar gerar as que faltam, no meuPlano, fora do tempo
de uma requisição) e **baixar** — e a tela só oferece o download quando o preparo terminou.
O que não coube numa parte vai para a seguinte, numerada; nada é omitido em silêncio.

**O pacote é repassado, não remontado.** O ZIP nasce no meuPlano, que é quem tem os
binários e a régua do que entra. Aqui ele atravessa em fluxo (`StreamingResponse` sobre
`httpx.stream`) — o padrão `Response(content=…)` dos PDFs unitários guardaria dezenas de
megabytes na memória deste processo antes de mandar o primeiro byte ao portal. Os
cabeçalhos de contagem (`X-Incluidos`, `X-Omitidos`) e de parte (`X-Parte`, `X-Partes`)
viajam junto e são declarados em `Access-Control-Expose-Headers`: sem isso o portal, que
roda em outro domínio, simplesmente não os enxerga.

**O escopo é conferido a cada chamada.** `usina_id` é o id do VÍNCULO neste sistema, e
passa por `_link_do_escopo` — que devolve 404, nunca 403, porque dizer "proibido"
confirmaria a existência da usina de outro cliente. O `preparo_id` também vai amarrado à
usina no upstream, senão trocar o número devolveria o andamento (e os ids de tarefa) do
preparo alheio.

**O vocabulário é o mesmo da aba Ordens.** Classificação e situação saem dos mapas de
`manutencao.py`. A mesma OS não pode sair "Serviços adicionais" numa tela e
"SERVICOS_ADICIONAIS" na outra — foi exatamente o defeito que a tradução única corrigiu.

Router próprio, e não mais um bloco em `manutencao.py`: aquele arquivo passa de mil e
quinhentas linhas e está sendo alterado em paralelo. Daqui só se importa o que já é fonte
única — o resolvedor de vínculo, a tradução de classificação, a régua de período e a
tradução de falha do upstream.
"""

from contextlib import AsyncExitStack
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.manutencao import (
    SITUACAO_TAREFA,
    _classificacao,
    _erro_do_upstream,
    _inteiro,
    _link_do_escopo,
    _nome_ascii,
    _situacao_da_ordem,
    _texto,
)
from app.api.v1.relatorio import periodo_pedido
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · manutenção"])


#: Os cabeçalhos que o portal precisa LER numa resposta de origem cruzada.
#:
#: Vive aqui, ao lado de quem os escreve, e é importado pelo CORS em `main.py` — uma
#: segunda lista divergiria no dia em que um cabeçalho fosse acrescentado. Sem esta
#: declaração o navegador entrega o corpo e esconde os cabeçalhos: o portal baixaria a
#: parte 1 de 2 sem ter como descobrir que existe uma parte 2.
CABECALHOS_EXPOSTOS = [
    "Content-Disposition",
    "X-Incluidos",
    "X-Omitidos",
    "X-Parte",
    "X-Partes",
    # O total do inventário, repetido em TODA parte. É com ele que o portal confere que a
    # soma do que baixou fecha com o que foi prometido — a garantia de que "todos" é todos.
    "X-Total-Fichas",
]

#: Situação da ORDEM, para o filtro do portal. Não é o status cru do meuPlano: o dono
#: pergunta "o que já foi entregue" e "o que ainda está andando", não `APROVADA` × `FECHADA`.
SITUACOES = ("encerradas", "em_curso", "todas")

#: Classificações que o filtro aceita. Lista fechada de propósito: o valor vai para a query
#: do upstream, e texto livre daqui seria um parâmetro nosso alimentando a rota dele.
CLASSIFICACOES = ("PREVENTIVA", "CORRETIVA", "SERVICOS_ADICIONAIS")

#: Teto do texto de busca. Nada de negócio depende dele; é só para não repassar um
#: parágrafo inteiro para a query do meuPlano.
BUSCA_MAX = 120


# ══════════════════════════════════════════════════════════════════════════════
# Saída
# ══════════════════════════════════════════════════════════════════════════════


class FichaOut(BaseModel):
    """Uma ficha do pacote — o PDF de UMA tarefa."""

    task_id: int
    nome: str
    equipamento: str | None = None
    #: Situação da tarefa, já traduzida ("Executada"). Nula quando o upstream não disse.
    situacao: str | None = None
    #: O PDF já existe e está válido. Falso = será gerado no preparo.
    pronta: bool = False
    #: Tamanho do PDF, quando ele já existe. Nulo enquanto não foi gerado — e nulo é
    #: diferente de zero, que afirmaria "arquivo vazio".
    bytes: int | None = None


class OrdemDoPacoteOut(BaseModel):
    """As fichas agrupadas pela ordem de serviço que as gerou."""

    os_id: int
    #: Número do CONTRATO que rege a OS, quando há. Nunca é o número da ordem — ela não tem.
    contrato_numero: int | None = None
    objetivo: str
    #: Rótulo pronto ("Serviços adicionais"); o código cru fica em `classificacao_codigo`.
    classificacao: str | None = None
    classificacao_codigo: str | None = None
    classificacao_tom: str = "semDados"
    #: A frase que a tela mostra ("Em verificação").
    situacao: str = "—"
    tom: str = "semDados"
    status: str | None = None
    #: A data pela qual a OS entrou neste período (aprovação, fechamento ou agendamento —
    #: a régua é do meuPlano, e é a mesma do relatório do período).
    data: str | None = None
    fichas: list[FichaOut] = []


class ParteOut(BaseModel):
    """Um arquivo do pacote. Mais de uma parte quando o total não cabe num ZIP só."""

    numero: int
    fichas: int = 0
    bytes: int | None = None


class InventarioOut(BaseModel):
    """O que o filtro pegou — respondido ANTES de qualquer download."""

    usina: str
    usina_id: int
    de: str
    ate: str

    ordens: list[OrdemDoPacoteOut] = []
    #: Quantas fichas o filtro pegou. Zero é resposta legítima ("o filtro não pegou nada").
    total: int = 0
    #: Quantas já têm PDF pronto. `prontas < total` = o botão da tela é "Preparar".
    prontas: int = 0
    #: Soma dos tamanhos conhecidos. Nulo quando nada está pronto — o portal escreve
    #: "tamanho ainda desconhecido" em vez de "0 MB", que se leria como pacote vazio.
    bytes_estimados: int | None = None
    partes: list[ParteOut] = []
    #: Quantas fichas existem no período SEM nenhum filtro. É o que permite à tela vazia
    #: dizer "o filtro escondeu 17" em vez de "não há nada aqui".
    total_sem_filtro: int | None = None
    #: Os filtros que de fato valeram, como o upstream os entendeu.
    filtros: dict[str, Any] = {}
    aviso: str | None = None


class PreparoOut(BaseModel):
    """O andamento da geração das fichas que faltavam."""

    preparo_id: str
    total: int = 0
    prontas: int = 0
    concluido: bool = False
    #: `andando` · `pronto` · `falhou`. `concluido` sozinho não distingue "terminou" de
    #: "parou no meio", e a tela precisa dessa diferença para oferecer o download ou pedir
    #: para preparar de novo.
    estado: str = "andando"
    #: O que interrompeu o preparo inteiro, quando foi o caso. Diferente de `erros`, que
    #: são fichas individuais — aqui nem o pacote existe.
    erro: str | None = None
    #: Ficha que nem a regeração salvou, com o motivo. O pacote sai sem ela e a tela diz
    #: qual — omitir seria voltar ao "baixei todos e vieram três".
    erros: list[dict[str, Any]] = []
    #: Já havia um preparo IGUAL correndo, e este pedido se juntou a ele em vez de abrir
    #: outro. O portal mostra o andamento sem dizer que começou algo novo.
    ja_em_andamento: bool = False
    #: Segundos até o meuPlano esquecer este preparo. É o limite útil do acompanhamento.
    expira_em: int | None = None
    aviso: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Leitura do que o meuPlano devolve
# ══════════════════════════════════════════════════════════════════════════════


def _lista(bruto: Any, *nomes: str) -> list[dict[str, Any]]:
    """A primeira lista de dicionários entre os nomes dados. Envelope paginado incluído.

    Tolerante ao nome porque o agregado do meuPlano nasceu junto com este router: um campo
    renomeado lá não pode apagar a tela inteira aqui sem ninguém perceber.
    """
    if isinstance(bruto, list):
        return [i for i in bruto if isinstance(i, dict)]
    if not isinstance(bruto, dict):
        return []
    for nome in nomes:
        valor = bruto.get(nome)
        if isinstance(valor, list):
            return [i for i in valor if isinstance(i, dict)]
        if isinstance(valor, dict):
            return _lista(valor, "items", "results")
    return []


def _pega(d: dict[str, Any], *nomes: str) -> Any:
    for nome in nomes:
        if d.get(nome) is not None:
            return d[nome]
    return None


def _ficha_out(t: dict[str, Any]) -> FichaOut | None:
    task_id = _inteiro(_pega(t, "task_id", "id"))
    if task_id is None:
        # Ficha sem id não tem PDF endereçável: contá-la inflaria o total que a tela
        # promete baixar.
        return None
    situacao_crua = (_texto(t.get("status")) or "").strip().upper()
    return FichaOut(
        task_id=task_id,
        nome=(
            _texto(_pega(t, "nome", "name", "plan_item_name"))
            or f"Tarefa {task_id}"
        ),
        equipamento=_texto(_pega(t, "equipamento", "equipment_path", "equipment_name")),
        situacao=SITUACAO_TAREFA.get(situacao_crua) if situacao_crua else None,
        pronta=bool(t.get("pronta")),
        bytes=_inteiro(t.get("bytes")),
    )


def _ordem_out(o: dict[str, Any]) -> OrdemDoPacoteOut | None:
    os_id = _inteiro(_pega(o, "os_id", "id"))
    if os_id is None:
        return None
    rotulo, codigo, tom_classe = _classificacao(_pega(o, "classificacao", "classification"))
    # A MESMA régua da aba Ordens, inclusive o "Executada · aguardando verificação" que o
    # status cru esconde. Sem as contagens de tarefa ela degrada para a tradução simples —
    # nunca inventa. O `status` é normalizado antes porque o índice das fichas nomeia o
    # campo `situacao`, e a régua lê `status`.
    status, frase, tom = _situacao_da_ordem(
        {**o, "status": _pega(o, "situacao", "status")}
    )
    fichas = [f for f in (_ficha_out(t) for t in _lista(o, "tarefas", "fichas")) if f]
    return OrdemDoPacoteOut(
        os_id=os_id,
        # Só os nomes INEQUÍVOCOS. Um `numero` solto no índice tanto pode ser o do contrato
        # quanto o da própria ordem, e adivinhar já custou caro: o drawer da pendência
        # imprimia "OS #665" para o contrato 665 enquanto a lista chamava a MESMA ordem de
        # "OS 1016" — toda ordem daquele contrato virava a mesma. Na dúvida, sem número.
        contrato_numero=_inteiro(_pega(o, "contrato_numero", "container_numero")),
        # `titulo` é o nome que o índice do meuPlano já resolveu (ele mesmo percorre
        # name → objetivo → título do contêiner, porque a OS 969 tem os dois primeiros
        # nulos). Os outros ficam como rede para o dia em que o campo mudar de nome.
        objetivo=(
            _texto(_pega(o, "titulo", "objetivo", "name", "container_title"))
            or f"OS {os_id}"
        ),
        classificacao=rotulo,
        classificacao_codigo=codigo,
        classificacao_tom=tom_classe,
        status=status,
        situacao=frase,
        tom=tom,
        data=_texto(_pega(o, "data_efetiva", "data", "data_referencia")),
        fichas=fichas,
    )


def _partes(bruto: Any) -> list[ParteOut]:
    saida: list[ParteOut] = []
    for p in _lista(bruto, "partes"):
        numero = _inteiro(_pega(p, "numero", "parte"))
        if numero is None:
            continue
        saida.append(
            ParteOut(
                numero=numero,
                fichas=_inteiro(_pega(p, "fichas", "incluidos")) or 0,
                bytes=_inteiro(p.get("bytes")),
            )
        )
    return sorted(saida, key=lambda p: p.numero)


# ══════════════════════════════════════════════════════════════════════════════
# Filtros
# ══════════════════════════════════════════════════════════════════════════════


def _filtros(
    classificacao: str | None, situacao: str | None, os_id: int | None, busca: str | None
) -> dict[str, Any]:
    """Os filtros conferidos ANTES de ir ao upstream.

    Valor fora da lista responde 400 com a frase aqui, e não um 422 do meuPlano achatado
    em 502 sem dizer o que estava errado. E, como estes valores entram na query DELE com a
    nossa credencial de serviço, a lista fechada é também a defesa: nada de texto livre
    virando parâmetro de uma rota de outro sistema.
    """
    limpo: dict[str, Any] = {}

    if classificacao:
        chave = classificacao.strip().upper()
        if chave not in CLASSIFICACOES:
            raise HTTPException(
                400,
                "classificacao deve ser "
                + " ou ".join(c.lower() for c in CLASSIFICACOES)
                + ".",
            )
        limpo["classificacao"] = chave

    if situacao:
        chave = situacao.strip().lower()
        if chave not in SITUACOES:
            raise HTTPException(400, "situacao deve ser " + " ou ".join(SITUACOES) + ".")
        if chave != "todas":
            limpo["situacao"] = chave

    if os_id is not None:
        if os_id <= 0:
            raise HTTPException(400, "os_id deve ser um número de ordem válido.")
        limpo["os_id"] = os_id

    if busca:
        texto = " ".join(busca.split())[:BUSCA_MAX]
        if texto:
            limpo["busca"] = texto

    return limpo


def _detalhe(exc: httpx.HTTPStatusError) -> str | None:
    """A frase que o meuPlano escreveu, quando o status dele é para o cliente ler.

    Reusa a leitura pública de `integracoes` — uma segunda cópia divergiria no dia em que
    um dos produtos mudasse o nome do campo.
    """
    return integracoes.detalhe_do_upstream(exc.response)


async def _cliente(db: Session) -> Any:
    try:
        return await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Manutenção indisponível: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════════════
# Rotas
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/manutencao/fichas", response_model=InventarioOut)
async def inventario_de_fichas(
    usina_id: int,
    de: str | None = None,
    ate: str | None = None,
    classificacao: str | None = None,
    situacao: str | None = None,
    os_id: int | None = None,
    busca: str | None = None,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> InventarioOut:
    """Quais fichas o filtro pega no período — e quantas já estão prontas para baixar.

    Responde ANTES do download de propósito: o pacote de uma inspeção mensal passa de
    dezenas de megabytes, e oferecer um botão que baixa "algo" de tamanho desconhecido é o
    que faz o cliente desistir no meio.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    inicio, fim = periodo_pedido(de, ate)
    filtros = _filtros(classificacao, situacao, os_id, busca)

    saida = InventarioOut(usina=link.nome, usina_id=link.id, de=inicio, ate=fim)
    cliente = await _cliente(db)

    try:
        bruto = await cliente.vc_fichas(
            link.mp_usina_id, inicio, fim, container_id=contrato_id, **filtros
        )
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para listar as fichas do período") from exc

    if not isinstance(bruto, dict):
        raise HTTPException(502, "O índice das fichas veio num formato desconhecido.")

    saida.ordens = [o for o in (_ordem_out(o) for o in _lista(bruto, "ordens")) if o]
    contadas = sum(len(o.fichas) for o in saida.ordens)
    # O total do upstream manda; a soma das ordens é a rede de segurança para o caso de o
    # índice vir sem o agregado. Contar por baixo faria a tela prometer menos do que baixa.
    saida.total = _inteiro(_pega(bruto, "total_fichas", "total")) or contadas
    saida.prontas = _inteiro(bruto.get("prontas")) or 0
    saida.bytes_estimados = _inteiro(_pega(bruto, "bytes_estimados", "bytes"))
    saida.partes = _partes(bruto)
    saida.total_sem_filtro = _inteiro(bruto.get("total_sem_filtro"))
    saida.filtros = {"de": inicio, "ate": fim, **filtros}
    if contrato_id is not None:
        saida.filtros["contrato_id"] = contrato_id

    # Uma parte sempre existe quando há ficha: sem esta linha, um upstream que não calcule
    # partes deixaria o portal sem nenhum botão de download.
    if saida.total and not saida.partes:
        saida.partes = [ParteOut(numero=1, fichas=saida.total, bytes=saida.bytes_estimados)]

    if not saida.total:
        saida.aviso = (
            "Nenhuma ficha neste filtro."
            if saida.total_sem_filtro
            else "Nenhuma ficha registrada neste período."
        )
    return saida


@router.post("/manutencao/fichas/preparar", response_model=PreparoOut)
async def preparar_fichas(
    usina_id: int,
    de: str | None = None,
    ate: str | None = None,
    classificacao: str | None = None,
    situacao: str | None = None,
    os_id: int | None = None,
    busca: str | None = None,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> PreparoOut:
    """Manda o meuPlano gerar as fichas que ainda não têm PDF, e devolve o número do preparo.

    Não gera nada aqui dentro: dezessete fichas frias, uma delas com sessenta e uma fotos,
    passam de qualquer prazo de proxy. O trabalho corre lá, e a tela acompanha em
    `/manutencao/fichas/preparo/{id}`.

    Repetir é seguro: o meuPlano versiona por impressão digital e reaproveita o que já
    existe — pedir de novo num período pronto termina na hora, sem regerar nada.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    inicio, fim = periodo_pedido(de, ate)
    filtros = _filtros(classificacao, situacao, os_id, busca)

    cliente = await _cliente(db)
    try:
        bruto = await cliente.vc_fichas_preparar(
            link.mp_usina_id, inicio, fim, container_id=contrato_id, **filtros
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            # Um preparo por usina de cada vez, com OUTRO recorte já em curso. É uma frase
            # que o cliente precisa ler literalmente ("espere terminar"), não um erro de
            # ponte — e `_erro_do_upstream` a achataria num 502 sem sentido para ele.
            raise HTTPException(
                409,
                _detalhe(exc)
                or "Já há um preparo de fichas em andamento nesta usina, com outro filtro. "
                "Espere ele terminar antes de pedir outro.",
            ) from exc
        raise _erro_do_upstream(exc, "Não deu para preparar as fichas") from exc
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para preparar as fichas") from exc

    preparo_id = _texto((bruto or {}).get("preparo_id")) if isinstance(bruto, dict) else None
    if not preparo_id:
        raise HTTPException(502, "O preparo das fichas não devolveu um número de acompanhamento.")

    total = _inteiro(bruto.get("total")) or 0
    prontas = _inteiro(bruto.get("prontas")) or 0
    concluido = bool(bruto.get("concluido")) or (total > 0 and prontas >= total)
    return PreparoOut(
        preparo_id=preparo_id,
        total=total,
        prontas=prontas,
        concluido=concluido,
        estado="pronto" if concluido else "andando",
        ja_em_andamento=bool(bruto.get("ja_em_andamento")),
    )


@router.get("/manutencao/fichas/preparo/{preparo_id}", response_model=PreparoOut)
async def andamento_do_preparo(
    preparo_id: str,
    usina_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> PreparoOut:
    """Quantas fichas já ficaram prontas — o "14 de 17" da tela.

    O `usina_id` é exigido e vai amarrado ao preparo no upstream: sem ele, trocar o número
    do preparo devolveria o andamento (e os ids de tarefa) do pacote de outro cliente.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    cliente = await _cliente(db)

    try:
        bruto = await cliente.vc_fichas_preparo(link.mp_usina_id, preparo_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Preparo esquecido (o meuPlano guarda em memória, com prazo) não é defeito: o
            # portal manda preparar de novo, e o que já foi gerado é reaproveitado.
            raise HTTPException(
                404, "Este preparo expirou. Peça para preparar as fichas de novo."
            ) from exc
        raise _erro_do_upstream(exc, "Não deu para acompanhar o preparo") from exc
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para acompanhar o preparo") from exc

    if not isinstance(bruto, dict):
        raise HTTPException(502, "O andamento do preparo veio num formato desconhecido.")

    total = _inteiro(bruto.get("total")) or 0
    prontas = _inteiro(bruto.get("prontas")) or 0
    erros = [e for e in _lista(bruto, "erros") if e]
    erro = _texto(bruto.get("erro"))
    # O meuPlano diz `running` | `ok` | `error`; aqui vira o vocabulário do produto. Sem
    # esta distinção, um preparo que PAROU no meio chegaria à tela como "concluído" — e o
    # cliente baixaria um pacote com menos fichas do que pediu, sem nenhum aviso.
    concluido = bool(bruto.get("concluido")) or (total > 0 and prontas >= total)
    estado = "falhou" if erro else ("pronto" if concluido else "andando")
    return PreparoOut(
        preparo_id=preparo_id,
        total=total,
        prontas=prontas,
        concluido=concluido or bool(erro),
        estado=estado,
        erro=erro,
        erros=erros,
        expira_em=_inteiro(bruto.get("expira_em")),
        aviso=(
            erro
            or (
                f"{len(erros)} ficha(s) não puderam ser geradas — o pacote sai sem elas."
                if erros
                else None
            )
        ),
    )


def _nome_do_pacote(link: PlantLink, de: str, ate: str, parte: int, partes: int) -> str:
    """`fichas-porto-ferreira-2026-08.zip`, ou `…-2026-01_2026-08-parte2de4.zip`.

    O nome do vínculo é reduzido a ASCII pela mesma razão do PDF da tarefa: cabeçalho HTTP
    é latin-1 no Starlette, e "Ribeirão Bonito" derrubaria a resposta inteira ao montar o
    `Content-Disposition` — antes do CORS, então o portal acusaria a internet do cliente.
    """
    usina = _nome_ascii(link.nome).removesuffix(".pdf").lower() or "usina"
    periodo = de if de == ate else f"{de}_{ate}"
    sufixo = f"-parte{parte}de{partes}" if partes > 1 else ""
    return f"fichas-{usina}-{periodo}{sufixo}.zip"


@router.get("/manutencao/fichas/pacote")
async def pacote_de_fichas(
    usina_id: int,
    de: str | None = None,
    ate: str | None = None,
    parte: int = Query(1, ge=1),
    classificacao: str | None = None,
    situacao: str | None = None,
    os_id: int | None = None,
    busca: str | None = None,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> StreamingResponse:
    """O ZIP com as fichas do filtro — uma parte por vez quando não cabe num arquivo só.

    Atravessa em fluxo: o corpo do meuPlano vira o corpo desta resposta pedaço a pedaço,
    sem passar inteiro pela memória. `Content-Length` é repassado quando o upstream o
    informa, para a barra do navegador não ficar cega.

    O ZIP não é reembalado. Remontá-lo aqui significaria abrir cada PDF, e o pacote é o
    documento que o cliente arquiva — os bytes que ele recebe são os que o meuPlano gerou.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    inicio, fim = periodo_pedido(de, ate)
    filtros = _filtros(classificacao, situacao, os_id, busca)
    cliente = await _cliente(db)

    # O contexto do fluxo tem de sobreviver a esta função: ele só fecha quando o último
    # pedaço sair. Daí a pilha ser aberta aqui (para ler os cabeçalhos e falhar cedo, com
    # a frase do meuPlano) e fechada dentro do gerador.
    pilha = AsyncExitStack()
    try:
        resposta = await pilha.enter_async_context(
            cliente.vc_fichas_pacote(
                link.mp_usina_id,
                inicio,
                fim,
                parte=parte,
                container_id=contrato_id,
                **filtros,
            )
        )
    except httpx.HTTPStatusError as exc:
        await pilha.aclose()
        if exc.response.status_code == 404:
            # A frase do meuPlano primeiro: o 404 dele tanto pode ser "nenhuma ficha neste
            # filtro" quanto "esta parte não existe" (parte 5 de 2), e escolher uma delas
            # aqui mandaria metade dos casos procurar a coisa errada.
            raise HTTPException(
                404, _detalhe(exc) or "Não há ficha neste filtro para baixar."
            ) from exc
        raise _erro_do_upstream(exc, "Não deu para baixar as fichas") from exc
    except Exception as exc:  # noqa: BLE001
        await pilha.aclose()
        raise _erro_do_upstream(exc, "Não deu para baixar as fichas") from exc

    partes = _inteiro(resposta.headers.get("x-partes")) or 1
    nome = _nome_do_pacote(link, inicio, fim, parte, partes)
    cabecalhos = {
        # `attachment`: o destino de um pacote é a pasta de downloads, não um visualizador.
        # Dois nomes pelo mesmo motivo do PDF da tarefa — o ASCII para qualquer cliente, o
        # `filename*` em UTF-8 para quem sabe lê-lo.
        "Content-Disposition": (
            f'attachment; filename="{nome}"; filename*=UTF-8\'\'{quote(nome, safe="")}'
        ),
        "X-Parte": str(parte),
        "X-Partes": str(partes),
        "Access-Control-Expose-Headers": ", ".join(CABECALHOS_EXPOSTOS),
        # Pacote é montado sob demanda e muda quando uma ficha é regerada: guardá-lo
        # entregaria um ZIP velho a quem acabou de preparar de novo.
        "Cache-Control": "no-store",
    }
    for cru, nosso in (
        ("x-incluidos", "X-Incluidos"),
        ("x-omitidos", "X-Omitidos"),
        ("x-total-fichas", "X-Total-Fichas"),
    ):
        valor = resposta.headers.get(cru)
        if valor is not None:
            cabecalhos[nosso] = valor
    # `Content-Length` só é repassado quando o corpo sai daqui do mesmo tamanho que entrou.
    # `aiter_bytes()` devolve os bytes JÁ DECODIFICADOS: se um proxy no meio comprimiu o
    # ZIP, o comprimento do cabeçalho é o do comprimido e o corpo é o do original — o
    # navegador cortaria o arquivo no número prometido, ou ficaria esperando por bytes que
    # não vêm. Sem o cabeçalho a barra de progresso fica cega, que é o mal menor.
    codificacao = (resposta.headers.get("content-encoding") or "identity").strip().lower()
    tamanho = resposta.headers.get("content-length")
    if tamanho and codificacao in ("", "identity"):
        cabecalhos["Content-Length"] = tamanho

    async def corpo():
        # `async with` e não um `aclose()` no fim: quando o cliente desiste no meio de um
        # pacote grande — e num arquivo de dezenas de megabytes isso acontece —, o gerador
        # é fechado à força, e sem o contexto a conexão com o meuPlano ficaria pendurada
        # até o prazo de leitura de cinco minutos, ocupando uma vaga do keep-alive.
        async with pilha:
            async for pedaco in resposta.aiter_bytes():
                yield pedaco

    return StreamingResponse(
        corpo(),
        media_type=resposta.headers.get("content-type") or "application/zip",
        headers=cabecalhos,
    )
