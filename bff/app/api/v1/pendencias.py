"""Pendências — o que o dono da usina cobrou da equipe, e em que pé está.

O dono (texto de 09/2026): *"se tiver alguma PENDÊNCIA que ele cobrou a gente, ele quer ver
lá, a pendência, igual tem no meuPlano, mas de forma mais simples"*. No meuPlano a pendência é
um container do funil global (`kind=pendencia`) com etapa, checklist, feed, subitens e
documentos. Aqui sai só o que responde à pergunta do cliente corporativo: **em que etapa está,
quando mexeram por último, o que a equipe respondeu, o que foi publicado e que OS resolve**.
Checklist, subitens e feed ficam de fora de propósito — não é falta, é o "mais simples".

Três decisões que moldam este arquivo:

**Duas cercas, não uma.** O meuPlano corta pelo `shareable` na rota `visao-cliente`, mas o
token de serviço deste BFF é de uma conta da Splendor — e `_filtrar_compartilhaveis` do
meuPlano é no-op para quem MANDA na usina. Se um dia a rota de lá mudar (ou alguém apontar a
ponte para a rota interna do funil), as pendências internas chegariam aqui inteiras. Então
tudo é re-filtrado deste lado: `shareable is True` e `usina_id == link.mp_usina_id`. O mesmo
vale para os documentos (`visivel_cliente is True`): a pasta de uma pendência guarda rascunho
e anotação interna, e o cliente só vê o que foi publicado um a um.

**O download não confia no id.** `GET /pipelines/containers/{cid}/documents/{did}/download`
do meuPlano é público por desenho (o navegador abre sem cabeçalho) e não confere escopo:
qualquer par numérico baixa. Por aqui o arquivo só sai depois de o detalhe AUTORIZADO listar
aquele `did` entre os publicados — e a sessão viaja no cabeçalho, nunca na URL.

**O HTML rico não entra no portal.** `parecer_html` é saída do editor do meuPlano; injetá-lo
no DOM do portal do cliente seria abrir a porta para o que quer que alguém tenha colado lá.
Vira texto com as quebras preservadas, e a tela mostra com `white-space: pre-line`.
"""

import asyncio
import re
import time
import unicodedata
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.manutencao import (
    OrdemOut,
    _erro_do_upstream,
    _inteiro,
    _ordem_out,
    _texto,
    _usinas_com_manutencao,
)
from app.api.v1.plants import _instante_medida, usinas_do_usuario
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · pendências"])


# ── vocabulário ─────────────────────────────────────────────────────────────

#: `PipelineContainer.status` do meuPlano → a frase que o dono lê. É vocabulário do
#: servidor, como `SITUACAO` das ordens: a tela não reinterpreta código nenhum.
SITUACAO_PENDENCIA: dict[str, str] = {
    "ABERTO": "Aguardando",
    "EM_ANDAMENTO": "Em andamento",
    "CONCLUIDO": "Concluída",
}

#: Tom da tarja — SEMPRE uma das seis chaves de `tons` (camelCase), como em `plants.py`.
#: `ABERTO` é alerta: alguém cobrou e ninguém pegou ainda, que é o estado que o cliente quer
#: enxergar de longe. `EM_ANDAMENTO` é ok: está andando, que é a pergunta dele.
TOM_DA_PENDENCIA: dict[str, str] = {
    "ABERTO": "alerta",
    "EM_ANDAMENTO": "ok",
    "CONCLUIDO": "semDados",
}

CONCLUIDA = {"CONCLUIDO"}

#: Criticidade do container (`baixa|media|alta|critica`) → tom. Escala própria, separada da
#: situação: uma pendência crítica pode estar "Em andamento" (ok) e continuar crítica.
TOM_DA_CRITICIDADE: dict[str, str] = {
    "CRITICA": "parado",
    "ALTA": "multiplos",
    "MEDIA": "alerta",
    "BAIXA": "semDados",
}


class PendenciaOut(BaseModel):
    id: int
    #: Número GLOBAL do container no meuPlano — é assim que a equipe e o cliente se referem a
    #: ela ("a 1042"). Nulo se o upstream não mandou; nunca inventado a partir do id.
    numero: int | None = None
    usina: str
    #: O id do VÍNCULO deste BFF (`PlantLink.id`), não a usina do meuPlano — o resto do
    #: portal navega por ele.
    usina_id: int
    titulo: str
    #: Marcada pela equipe como "cobrada pelo cliente" (`extra.cobrada_pelo_cliente`). É o
    #: recorte padrão da tela: "Compart." é padrão TRUE no meuPlano, logo compartilhável
    #: sozinho não diz que foi o cliente quem cobrou.
    cobrada_pelo_cliente: bool = False
    #: A coluna do funil, pelo nome ("A fazer", "Em andamento", "Parado"…).
    etapa: str | None = None
    #: Código cru, para auditoria. A tela lê `situacao` e `tom`.
    status: str | None = None
    situacao: str
    tom: str
    criticidade: str | None = None
    criticidade_tom: str | None = None
    responsavel: str | None = None
    aberta_em: datetime | None = None
    #: `end_date` do container. Vermelho só quando passou E a pendência não concluiu — é o
    #: `tom` que carrega essa regra, não a tela.
    prazo: date | None = None
    ultima_atividade_em: datetime | None = None
    concluida_em: datetime | None = None
    #: Quantos documentos PUBLICADOS ao cliente. Nulo = o upstream não contou.
    documentos: int | None = None
    os_count: int | None = None


class PendenciasOut(BaseModel):
    #: Nulos quando ALGUMA usina não respondeu: somar só as que responderam daria um
    #: número que parece completo e não é. Zero é "nenhuma pendência", que é outra coisa.
    total: int | None = None
    abertas: int | None = None
    concluidas: int | None = None
    prazo_vencido: int | None = None
    pendencias: list[PendenciaOut] = []
    usinas_com_manutencao: int = 0
    aviso: str | None = None


class DocumentoPendenciaOut(BaseModel):
    id: int
    nome: str
    publicado_em: datetime | None = None
    #: Caminho NESTE BFF. O portal abre com a sessão no cabeçalho — a URL do meuPlano
    #: (pública por id) nunca chega ao navegador do cliente.
    url: str


class PendenciaDetalheOut(PendenciaOut):
    descricao: str | None = None
    #: O que a equipe respondeu — `parecer_html` do meuPlano já convertido em texto.
    parecer: str | None = None
    documentos_publicados: list[DocumentoPendenciaOut] = []
    ordens: list[OrdemOut] = []


# ── tradução ────────────────────────────────────────────────────────────────


def _situacao_da_pendencia(o: dict[str, Any], hoje: date) -> tuple[str | None, str, str]:
    """`(código cru, frase, tom)` — com o prazo vencido por cima do status.

    Prazo vencido só vale para quem NÃO concluiu: uma pendência concluída depois do prazo
    já foi resolvida, e pintá-la de vermelho faria o cliente cobrar de novo o que já
    aconteceu. Status desconhecido vira o próprio código capitalizado, não "—": o meuPlano
    pode ganhar um estado novo, e engolir isso deixaria a tela sem situação sem ninguém saber.
    """
    cru = _texto(o.get("status"))
    chave = (cru or "").strip().upper()
    if not chave:
        return None, "Sem situação", "semDados"
    frase = SITUACAO_PENDENCIA.get(chave, chave.replace("_", " ").capitalize())
    tom = TOM_DA_PENDENCIA.get(chave, "semDados")
    prazo = _data(o.get("end_date"))
    if chave not in CONCLUIDA and prazo is not None and prazo < hoje:
        return cru, "Prazo vencido", "parado"
    return cru, frase, tom


def _data(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if texto is None:
        return None
    # `end_date` do container é uma data pura ("2026-09-30"); `_instante_medida` a leria
    # como meia-noite UTC e, convertida, poderia voltar um dia — o mesmo cuidado de
    # `dataPorExtenso` no aplicativo.
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        instante = _instante_medida(texto)
        return instante.date() if instante else None


def _criticidade(o: dict[str, Any]) -> tuple[str | None, str | None]:
    cru = _texto(o.get("criticidade"))
    if cru is None:
        return None, None
    return cru, TOM_DA_CRITICIDADE.get(cru.strip().upper())


def _responsavel(o: dict[str, Any]) -> str | None:
    pessoas = o.get("responsaveis")
    if not isinstance(pessoas, list):
        return None
    nomes = [_texto(p.get("name")) for p in pessoas if isinstance(p, dict)]
    nomes = [n for n in nomes if n]
    return ", ".join(nomes) or None


def _etapa(o: dict[str, Any]) -> str | None:
    """O nome da coluna. A rota `visao-cliente` manda `etapa` resolvida; a forma antiga do
    `ContainerOut` só traz `stage_id`, e um número não diz nada ao cliente."""
    etapa = o.get("etapa")
    if isinstance(etapa, dict):
        return _texto(etapa.get("name"))
    if etapa is not None:
        return _texto(etapa)
    stage = o.get("stage")
    if isinstance(stage, dict):
        return _texto(stage.get("name"))
    return _texto(o.get("stage_name"))


def _cobrada(o: dict[str, Any]) -> bool:
    if o.get("cobrada_pelo_cliente") is True:
        return True
    extra = o.get("extra")
    return isinstance(extra, dict) and extra.get("cobrada_pelo_cliente") is True


def _pendencia_out(o: dict[str, Any], link: PlantLink, hoje: date | None = None) -> PendenciaOut:
    cru, frase, tom = _situacao_da_pendencia(o, hoje or date.today())
    criticidade, criticidade_tom = _criticidade(o)
    return PendenciaOut(
        id=_inteiro(o.get("id")) or 0,
        numero=_inteiro(o.get("numero")),
        usina=link.nome,
        usina_id=link.id,
        titulo=_texto(o.get("title")) or f"Pendência {o.get('numero') or o.get('id')}",
        cobrada_pelo_cliente=_cobrada(o),
        etapa=_etapa(o),
        status=cru,
        situacao=frase,
        tom=tom,
        criticidade=criticidade,
        criticidade_tom=criticidade_tom,
        responsavel=_responsavel(o),
        aberta_em=_instante_medida(o.get("created_at")),
        prazo=_data(o.get("end_date")),
        ultima_atividade_em=_instante_medida(o.get("last_activity_at")),
        # O container não guarda "concluída em"; só sai quando o upstream souber dizer.
        # Usar `last_activity_at` no lugar seria inventar uma data.
        concluida_em=_instante_medida(o.get("concluida_em") or o.get("closed_at")),
        documentos=_inteiro(o.get("doc_count")),
        os_count=_inteiro(o.get("os_count")),
    )


def _compartilhavel(o: Any, link: PlantLink) -> bool:
    """A segunda cerca — ver o cabeçalho do módulo. `shareable` tem de ser LITERALMENTE
    `True`: ausente, nulo ou "true" em texto ficam de fora, porque na dúvida o erro tem de
    ser para o lado de mostrar de menos."""
    return (
        isinstance(o, dict)
        and o.get("id") is not None
        and o.get("shareable") is True
        and _inteiro(o.get("usina_id")) == link.mp_usina_id
    )


# ── HTML → texto ────────────────────────────────────────────────────────────

_QUEBRA_ANTES = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
                 "ul", "ol", "blockquote", "table", "pre"}
#: Item de lista e linha de tabela quebram só ANTES: quebrar dos dois lados abriria uma
#: linha vazia entre cada item, e o parecer da equipe viraria uma escada.
_QUEBRA_DEPOIS = _QUEBRA_ANTES - {"br", "li", "tr"}


class _SoTexto(HTMLParser):
    """Guarda o texto e troca cada bloco por uma quebra. Não tenta preservar lista ou
    negrito: o parecer é um recado da equipe, e quebra de linha é o que faz ele legível."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _QUEBRA_ANTES:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _QUEBRA_DEPOIS:
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        self.partes.append(data)


def html_para_texto(html: Any) -> str | None:
    """`parecer_html` em texto com as quebras dos blocos preservadas.

    `<p>a<br>b</p>` vira `a\\nb`. Três ou mais quebras seguidas viram duas (um parágrafo
    vazio no editor não deve abrir um buraco na tela), e espaço no fim de linha some.
    """
    bruto = _texto(html)
    if bruto is None:
        return None
    parser = _SoTexto()
    parser.feed(bruto)
    parser.close()
    texto = "".join(parser.partes)
    linhas = [re.sub(r"[ \t\r\xa0]+$", "", linha) for linha in texto.split("\n")]
    texto = "\n".join(linha.strip() if not linha.strip() else linha.lstrip() for linha in linhas)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    return texto or None


# ── escopo ──────────────────────────────────────────────────────────────────


def _link_ou_aviso(db: Session, usuario: User, usina_id: int) -> tuple[PlantLink | None, str | None]:
    """O vínculo pedido, se for desta pessoa.

    Fora do escopo é **404** (e não 403 — dizer "proibido" confirmaria que a usina existe).
    Usina desta pessoa mas SEM o lado do meuPlano não é erro: a tela recebe o aviso e
    `total=None`, para explicar por que está vazia em vez de parecer quebrada.
    """
    for u in usinas_do_usuario(db, usuario):
        if u.id == usina_id:
            if not u.mp_usina_id:
                return None, "Esta usina não tem manutenção contratada."
            return u, None
    raise HTTPException(404, "Usina não encontrada.")


# ── lista ───────────────────────────────────────────────────────────────────


@router.get("/manutencao/pendencias", response_model=PendenciasOut)
async def listar_pendencias(
    usina_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> PendenciasOut:
    """As pendências compartilháveis das usinas desta pessoa, mais recente atividade
    primeiro.

    Os contadores são do servidor porque a regra de "aberta" e de "prazo vencido" mora aqui
    (junto do tom); somar na tela duplicaria a régua. Quando alguma usina não respondeu os
    quatro ficam nulos — um total parcial parece completo e não é.
    """
    if usina_id is not None:
        alvo, aviso = _link_ou_aviso(db, usuario, usina_id)
        com_manutencao = [alvo] if alvo else []
    else:
        com_manutencao, aviso = await _usinas_com_manutencao(db, usuario)

    saida = PendenciasOut(usinas_com_manutencao=len(com_manutencao), aviso=aviso)
    if not com_manutencao:
        return saida

    try:
        cliente = await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Manutenção indisponível: {exc}"
        return saida

    respostas = await asyncio.gather(
        *[cliente.vc_pendencias(u.mp_usina_id) for u in com_manutencao],
        return_exceptions=True,
    )

    hoje = date.today()
    itens: list[PendenciaOut] = []
    falharam: list[str] = []
    for link, resposta in zip(com_manutencao, respostas, strict=True):
        if not isinstance(resposta, list):
            falharam.append(link.nome)
            continue
        itens.extend(_pendencia_out(o, link, hoje) for o in resposta if _compartilhavel(o, link))

    # Última atividade primeiro; quem não tem data nenhuma vai para o fim, e não para o
    # topo por um `datetime.min` invertido.
    def _quando(p: PendenciaOut) -> datetime | None:
        return p.ultima_atividade_em or p.aberta_em

    datadas = sorted((p for p in itens if _quando(p)), key=lambda p: _quando(p), reverse=True)  # type: ignore[arg-type,return-value]
    itens = [*datadas, *(p for p in itens if not _quando(p))]
    saida.pendencias = itens

    if falharam:
        saida.aviso = f"Não deu para consultar: {', '.join(falharam)}."
        return saida

    saida.total = len(itens)
    saida.concluidas = sum(1 for p in itens if (p.status or "").strip().upper() in CONCLUIDA)
    saida.abertas = saida.total - saida.concluidas
    saida.prazo_vencido = sum(1 for p in itens if p.tom == "parado")
    if not itens:
        saida.aviso = "Nenhuma pendência compartilhada nas suas usinas."
    return saida


# ── detalhe ─────────────────────────────────────────────────────────────────


def _corpo_do_detalhe(bruto: Any) -> dict[str, Any]:
    """O container dentro da resposta do detalhe — achatado ou num envelope `container`."""
    if not isinstance(bruto, dict):
        return {}
    interno = bruto.get("container")
    if isinstance(interno, dict):
        return {**bruto, **interno}
    return bruto


async def _pendencia_autorizada(
    db: Session, usuario: User, cid: int
) -> tuple[Any, dict[str, Any], PlantLink]:
    """O detalhe cru, o cliente do meuPlano e o vínculo — depois de checar o escopo.

    O `cid` vem do cliente, então a pendência é buscada e o `usina_id` dela conferido contra
    as usinas desta pessoa ANTES de qualquer coisa ser devolvida. Confiar no número seria
    abrir a pendência de outro dono trocando um dígito na URL. E, mesmo dentro do escopo,
    uma pendência não compartilhável responde 404 — a segunda cerca.
    """
    usinas_task = asyncio.create_task(_usinas_com_manutencao(db, usuario))
    cliente_task = asyncio.create_task(integracoes.cliente_meuplano(db))
    com_manutencao, aviso = await usinas_task
    if not com_manutencao:
        cliente_task.cancel()
        raise HTTPException(404, aviso or "Sem usina com manutenção.")

    try:
        cliente = await cliente_task
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Manutenção indisponível: {exc}") from exc

    try:
        bruto = await cliente.vc_pendencia(cid)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, "Pendência não encontrada.") from exc
        raise _erro_do_upstream(exc, "Não deu para conferir a pendência") from exc
    except Exception as exc:  # noqa: BLE001 — timeout, rede
        raise _erro_do_upstream(exc, "Não deu para conferir a pendência") from exc

    dados = _corpo_do_detalhe(bruto)
    alvo = _inteiro(dados.get("usina_id"))
    link = next((u for u in com_manutencao if u.mp_usina_id == alvo), None)
    if link is None or not _compartilhavel(dados, link):
        # 404 e não 403, pela mesma razão de `_link_ou_aviso`.
        raise HTTPException(404, "Pendência não encontrada.")
    return cliente, dados, link


def _documentos_publicados(dados: dict[str, Any], cid: int) -> list[DocumentoPendenciaOut]:
    """Só o que a equipe PUBLICOU (`visivel_cliente is True`) e só a versão vigente.

    A URL é deste BFF: o download do meuPlano é aberto por id e não confere escopo, então o
    portal nunca recebe o endereço de lá.
    """
    brutos = dados.get("documentos")
    if not isinstance(brutos, list):
        brutos = dados.get("documents") if isinstance(dados.get("documents"), list) else []
    saida: list[DocumentoPendenciaOut] = []
    for d in brutos:
        if not isinstance(d, dict) or d.get("visivel_cliente") is not True:
            continue
        if d.get("is_current") is False:
            continue
        did = _inteiro(d.get("id"))
        if did is None:
            continue
        saida.append(DocumentoPendenciaOut(
            id=did,
            nome=_texto(d.get("filename")) or _texto(d.get("name")) or f"Documento {did}",
            publicado_em=_instante_medida(d.get("publicado_em") or d.get("created_at")),
            url=f"/api/v1/manutencao/pendencias/{cid}/documentos/{did}",
        ))
    return saida


@router.get("/manutencao/pendencias/{cid}", response_model=PendenciaDetalheOut)
async def detalhar_pendencia(
    cid: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> PendenciaDetalheOut:
    """UMA pendência: o que a equipe respondeu, o que publicou e que OS a resolve.

    Sem checklist, subitens ou feed — é a versão "mais simples" que o dono pediu. Quem
    precisa do resto tem o meuPlano.
    """
    _cliente, dados, link = await _pendencia_autorizada(db, usuario, cid)
    base = _pendencia_out(dados, link)

    ordens_brutas = dados.get("ordens")
    if not isinstance(ordens_brutas, list):
        ordens_brutas = dados.get("service_orders") if isinstance(dados.get("service_orders"), list) else []
    ordens = [_ordem_out(o, link) for o in ordens_brutas if isinstance(o, dict) and o.get("id")]

    documentos = _documentos_publicados(dados, cid)
    return PendenciaDetalheOut(
        **base.model_dump(),
        descricao=html_para_texto(dados.get("description")),
        parecer=html_para_texto(dados.get("parecer_html")),
        documentos_publicados=documentos,
        ordens=ordens,
    )


# ── documento ───────────────────────────────────────────────────────────────
#
# Mesma mecânica das fotos da ficha (`manutencao._tarefa_autorizada_em_cache`): o detalhe
# autorizado fica guardado por dois minutos — o tempo de abrir o drawer e clicar em dois
# arquivos — e pedidos simultâneos com o cache frio esperam a MESMA cadeia. Falha não fica
# guardada: uma queda do upstream não vira 404 por dois minutos.

_AUTORIZACAO_TTL_S = 120.0
_Autorizacao = tuple[Any, dict[str, Any], PlantLink]
_autorizacoes: dict[tuple[int, int], tuple[float, _Autorizacao]] = {}
_em_voo: dict[tuple[int, int], "asyncio.Future[_Autorizacao]"] = {}


async def _pendencia_autorizada_em_cache(db: Session, usuario: User, cid: int) -> _Autorizacao:
    agora = time.monotonic()
    chave = (usuario.id, cid)

    guardada = _autorizacoes.get(chave)
    if guardada is not None and agora - guardada[0] < _AUTORIZACAO_TTL_S:
        return guardada[1]

    voando = _em_voo.get(chave)
    if voando is not None:
        return await voando

    fut: "asyncio.Future[_Autorizacao]" = asyncio.get_running_loop().create_future()
    _em_voo[chave] = fut
    try:
        dados = await _pendencia_autorizada(db, usuario, cid)
    except BaseException as exc:
        fut.set_exception(exc)
        raise
    else:
        fut.set_result(dados)
    finally:
        _em_voo.pop(chave, None)

    _autorizacoes[chave] = (agora, dados)
    if len(_autorizacoes) > 256:
        for k, (quando, _) in list(_autorizacoes.items()):
            if agora - quando >= _AUTORIZACAO_TTL_S:
                _autorizacoes.pop(k, None)
    return dados


@router.get("/manutencao/pendencias/{cid}/documentos/{did}")
async def documento_da_pendencia(
    cid: int,
    did: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """Os bytes de UM documento publicado da pendência.

    Passa pelo mesmo portão do detalhe e exige que o `did` esteja entre os PUBLICADOS daquela
    pendência: o download do meuPlano é aberto por id, e sem esta checagem bastaria adivinhar
    um número para ler a pasta interna de outro cliente.
    """
    cliente, dados, _link = await _pendencia_autorizada_em_cache(db, usuario, cid)
    publicado = next((d for d in _documentos_publicados(dados, cid) if d.id == did), None)
    if publicado is None:
        raise HTTPException(404, "Documento não encontrado nesta pendência.")
    try:
        conteudo, tipo = await cliente.vc_documento(cid, did)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para carregar este documento") from exc
    if not conteudo:
        raise HTTPException(502, "O documento veio vazio. Peça à equipe para publicá-lo de novo.")
    return Response(content=conteudo, media_type=tipo, headers={
        # `inline`: abre no navegador; quem quiser salvar, salva de lá.
        "Content-Disposition": _content_disposition(publicado.nome),
        # Privado: é documento de UM cliente, e nenhum proxy intermediário pode guardá-lo.
        "Cache-Control": "private, max-age=300",
    })


def _content_disposition(nome: str) -> str:
    """`inline` com o nome do arquivo em DUAS formas (RFC 5987).

    O `_pdf` das ordens monta o nome a partir do vínculo (`OS-12-Porto Ferreira.pdf`), que
    é sempre latin-1. Aqui o nome é o do UPLOAD da equipe — "Laudo – térmico.pdf", com o
    travessão que o Word coloca sozinho — e o Starlette codifica cabeçalho em latin-1: um
    caractere fora dela derruba a resposta em 500 depois de o arquivo já ter sido baixado do
    meuPlano. Então `filename=` leva a versão ASCII (acento tirado, o resto vira `_`) e
    `filename*=` leva o nome de verdade, percent-encoded, que é o que o navegador prefere.
    """
    limpo = nome.replace('"', "").replace("\r", " ").replace("\n", " ").strip()[:120]
    # NFKD separa "é" em "e" + acento; o acento (marca combinante) some e o "e" fica. O que
    # não decompõe em ASCII (travessão, aspas tipográficas) vira "_" em vez de sumir — sumir
    # colaria "Laudo  termico" e o cliente não saberia que ali havia algo.
    decomposto = unicodedata.normalize("NFKD", limpo)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    ascii_ = "".join(c if c.isascii() else "_" for c in sem_acento)
    ascii_ = re.sub(r"[^\w.\- ]", "_", ascii_).strip() or "documento"
    return f"inline; filename=\"{ascii_}\"; filename*=UTF-8''{quote(limpo, safe='')}"
