"""O catálogo das rotas que o Gestão Solar consome, e a máquina que exercita cada uma.

O teste da tela de Conexões responde *"o token vale?"* — bate em duas rotas e volta. Esta
sonda responde outra pergunta, que só aparece quando o app já está de pé: **quais das
rotas de que dependemos ainda respondem, e com que forma?**

A diferença aparece no caso concreto: um token perfeitamente válido, uma conexão verde na
tela de Conexões, e a aba de Financeiro vazia porque `/plants/{slug}/utility-bills` mudou
de lugar num deploy do meuWatt. Sem o catálogo, isso é descoberto pelo cliente. Com ele,
a linha fica vermelha aqui.

Três decisões que valem ser ditas:

- **Só leitura.** Nenhuma rota da sonda cria, altera ou apaga coisa alguma no produto de
  origem. As que teriam efeito colateral (gerar PDF, abrir uma conversa com o assistente)
  estão no catálogo com `sonda=False` e o motivo — declaradas e não exercitadas é honesto;
  omitidas dariam a impressão de que a lista está completa.
- **As rotas com parâmetro esperam por quem os descobre.** `/plants/{slug}` não tem slug
  nenhum antes de `/plants` responder. A sonda roda em duas ondas por isso, e uma rota
  cujo parâmetro não apareceu é reportada como *pulada*, com a razão — nunca como falha,
  porque ela não falhou.
- **A forma da resposta é registrada.** Junto do status vai a lista de campos que voltaram.
  É o que faz aparecer a mudança silenciosa: a rota responde 200, o app quebra, e o
  motivo é que `total_generation_kwh` virou outra coisa.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.cripto import SegredoInvalido, decifrar
from app.core.tokens_produto import NOME
from app.models.integracao import Produto
from app.services import integracoes


@dataclass(frozen=True)
class Rota:
    """Uma rota do produto de origem e o que ela sustenta deste lado.

    `alimenta` não é documentação decorativa: é o que transforma "GET /plants/{slug}/slots
    falhou" em "a tela de Equipamentos vai abrir vazia", que é a frase que faz alguém agir.
    """

    chave: str
    metodo: str
    caminho: str
    alimenta: str
    #: Sem ela o produto é inútil para nós. Uma rota não essencial que falha é um recurso
    #: a menos, não uma ponte quebrada — e a tela precisa mostrar essa diferença.
    essencial: bool = True
    #: Parâmetros de query, com os mesmos marcadores do caminho.
    params: dict[str, str] = field(default_factory=dict)
    #: O que esta rota descobre para as seguintes: `{nome_do_marcador: campo_na_resposta}`.
    #: Vários de uma vez, e do **mesmo item**, porque às vezes os valores só valem
    #: juntos — o cronograma precisa de uma usina e de um contrato *daquela* usina, e
    #: capturá-los de respostas diferentes produziria um par que não existe.
    captura: dict[str, str] = field(default_factory=dict)
    #: Só considera itens em que este campo tem valor. Serve para pular os itens
    #: incompletos de uma lista — um contrato sem usina não ajuda ninguém.
    captura_exige: str | None = None
    #: Motivo de não exercitar. Preenchido = a rota entra na lista e sai da execução.
    sonda: bool = True
    nao_sondada_porque: str | None = None


#: Rotas da mw-api. Os caminhos são montados na raiz — a API não tem prefixo de versão.
MEUWATT: list[Rota] = [
    Rota("mw.me", "GET", "/auth/me", "De quem é o token — o nome que aparece em Conexões",
         captura={"email": "email"}),
    Rota("mw.plants", "GET", "/plants", "A lista de usinas do app",
         captura={"slug": "slug"}),
    Rota("mw.plant", "GET", "/plants/{slug}", "Cabeçalho da tela da usina"),
    Rota("mw.monitoring", "GET", "/plants/{slug}/monitoring/current",
         "Potência agora, no cartão do Início"),
    Rota("mw.daily", "GET", "/plants/{slug}/generation/daily",
         "Geração do dia e disponibilidade", params={"date": "{hoje}"}),
    Rota("mw.range", "GET", "/plants/{slug}/generation/range",
         "Gráfico do mês e do ano", params={"start": "{semana_passada}", "end": "{hoje}"}),
    Rota("mw.intraday", "GET", "/plants/{slug}/charts/intraday",
         "Curva de potência do dia, no detalhe do inversor", params={"date": "{hoje}"}),
    Rota("mw.intraday_strings", "GET", "/plants/{slug}/charts/intraday/strings",
         "Corrente por string, no detalhe do inversor", params={"date": "{hoje}"}),
    Rota("mw.intraday_rele", "GET", "/plants/{slug}/charts/intraday/relay",
         "Tensão e corrente por fase, no relé de proteção", params={"date": "{hoje}"}),
    Rota("mw.intraday_temperatura", "GET", "/plants/{slug}/charts/intraday/temperature",
         "Temperatura das bobinas, no relé de temperatura", params={"date": "{hoje}"}),
    Rota("mw.alerts", "GET", "/plants/{slug}/alerts", "Alertas ativos da usina",
         params={"status": "active"}),
    Rota("mw.breakdowns", "GET", "/plants/{slug}/breakdowns/range",
         "Paradas, e o histórico do equipamento",
         params={"start": "{semana_passada}", "end": "{hoje}"}),
    Rota("mw.slots", "GET", "/plants/{slug}/slots", "Inversores da tela de Equipamentos"),
    Rota("mw.bills", "GET", "/plants/{slug}/utility-bills",
         "Faturas da concessionária", essencial=False),
    Rota("mw.users", "GET", "/admin/users",
         "Achar a conta do cliente para vincular (o meuWatt não tem busca por e-mail)"),
    Rota("mw.user_plants", "GET", "/admin/user-plants",
         "Quais usinas cada conta enxerga — as sugestões de concessão"),
    Rota("mw.portal", "GET", "/reports/portal",
         "Relatórios publicados no Portal do Cliente", essencial=False,
         sonda=False,
         nao_sondada_porque="Exige o token do próprio dono da usina (é restrita a "
                            "plant_owner). Com o token de serviço, um 403 aqui seria o "
                            "comportamento correto e apareceria como falha."),
]

#: Rotas do meuPlano. Prefixos `/api/v1/meuacesso` e `/api/v1/maintenance`.
MEUPLANO: list[Rota] = [
    Rota("mp.profile", "GET", "/api/v1/meuacesso/auth/me/profile",
         "De quem é o token, com nome — o que Conexões mostra",
         captura={"email": "email"}),
    Rota("mp.session", "GET", "/api/v1/meuacesso/auth/me/session",
         "Permissões e nível de acesso, que limitam o assistente"),
    Rota("mp.usinas", "GET", "/api/v1/meuacesso/usinas",
         "A lista de usinas do lado da manutenção",
         captura={"usina_id": "id"}),
    Rota("mp.ordens", "GET", "/api/v1/meuacesso/service-orders",
         "Ordens de serviço da usina", params={"plant_id": "{usina_id}"}),
    # O cronograma mora dentro de um contrato, e o contrato vem daqui — do pipeline, não
    # do financeiro: são duas tabelas de container com numerações próprias, e o cronograma
    # só reconhece a do pipeline. As duas rotas são sondadas em sequência de propósito, o
    # par (usina, contrato) tem de sair do MESMO registro.
    Rota("mp.contratos", "GET", "/api/v1/meuacesso/pipelines/global/contrato/containers",
         "Os contratos de O&M — é dentro de um deles que existe cronograma",
         captura={"container_id": "id", "contrato_usina_id": "usina_id"},
         captura_exige="usina_id"),
    Rota("mp.cronograma", "GET", "/api/v1/maintenance/usinas/{contrato_usina_id}/cronograma",
         "Cronograma de manutenção, com a cor de cada célula",
         params={"container_id": "{container_id}"}),
    Rota("mp.lookup", "GET", "/api/v1/meuacesso/admin/users/lookup",
         "Achar a conta do cliente por e-mail, ao vincular",
         params={"email": "{email}"}),
    Rota("mp.usinas_do_usuario", "GET",
         "/api/v1/meuacesso/admin/users/{usuario_remoto_id}/usinas",
         "As usinas que a conta do cliente enxerga — as sugestões de concessão",
         sonda=False,
         nao_sondada_porque="Depende de um id de usuário do meuPlano, que só existe no "
                            "contexto de um cliente já vinculado. A tela de Diagnóstico "
                            "exercita este caminho com o cliente escolhido."),
    Rota("mp.notificacoes", "GET", "/api/v1/meuacesso/me/notifications",
         "Notificações do app", essencial=False),
    Rota("mp.nao_lidas", "GET", "/api/v1/meuacesso/me/notifications/unread-count",
         "O contador na aba", essencial=False),
    Rota("mp.pdf_os", "POST", "/api/v1/meuacesso/service-orders/{so_id}/pdf",
         "PDF da ordem de serviço", essencial=False,
         sonda=False,
         nao_sondada_porque="Gera um arquivo na cesta do produto de origem. A sonda não "
                            "escreve em sistema de terceiro."),
    Rota("mp.assistente", "POST", "/api/v1/meuacesso/assistant/chat",
         "O assistente", essencial=False,
         sonda=False,
         nao_sondada_porque="Abre uma conversa e consome cota do modelo lá."),
]

CATALOGO: dict[Produto, list[Rota]] = {
    Produto.MEUWATT: MEUWATT,
    Produto.MEUPLANO: MEUPLANO,
}


@dataclass
class Resultado:
    """O que aconteceu com uma rota. `situacao` decide a cor na tela."""

    chave: str
    metodo: str
    caminho: str
    alimenta: str
    essencial: bool
    #: `ok` · `falhou` · `pulada` · `nao_sondada`
    situacao: str
    status: int | None = None
    ms: int | None = None
    detalhe: str | None = None
    #: Quantos itens vieram, quando a resposta é uma lista. `None` quando é um objeto.
    itens: int | None = None
    #: Os campos que voltaram. É por aqui que uma mudança de formato aparece antes de
    #: virar tela quebrada.
    campos: list[str] = field(default_factory=list)


def _preencher(texto: str, contexto: dict[str, Any]) -> str | None:
    """Troca `{marcador}` pelo valor descoberto. `None` = ainda falta algum."""
    saida = texto
    while "{" in saida:
        inicio = saida.index("{")
        fim = saida.index("}", inicio)
        nome = saida[inicio + 1 : fim]
        if contexto.get(nome) in (None, ""):
            return None
        saida = saida[:inicio] + str(contexto[nome]) + saida[fim + 1 :]
    return saida


def _faltando(rota: Rota, contexto: dict[str, Any]) -> list[str]:
    """Quais marcadores desta rota ainda não têm valor — a razão de ela ser pulada."""
    bruto = rota.caminho + "".join(rota.params.values())
    nomes = []
    resto = bruto
    while "{" in resto:
        inicio = resto.index("{")
        fim = resto.index("}", inicio)
        nomes.append(resto[inicio + 1 : fim])
        resto = resto[fim + 1 :]
    return [n for n in dict.fromkeys(nomes) if contexto.get(n) in (None, "")]


def _resumir(corpo: Any) -> tuple[int | None, list[str]]:
    """Quantos itens e quais campos — a forma da resposta, sem o conteúdo.

    O conteúdo não entra de propósito: a sonda é uma ferramenta de diagnóstico aberta pelo
    time, e despejar dados de geração de cliente numa tela de infraestrutura é vazamento
    gratuito. A forma basta para o que ela responde.
    """
    if isinstance(corpo, list):
        primeiro = corpo[0] if corpo else None
        campos = sorted(primeiro.keys())[:12] if isinstance(primeiro, dict) else []
        return len(corpo), campos
    if isinstance(corpo, dict):
        # Envelope paginado: o interessante é o formato do item, não o do envelope.
        for chave in ("items", "results", "data"):
            if isinstance(corpo.get(chave), list):
                return _resumir(corpo[chave])
        return None, sorted(corpo.keys())[:12]
    return None, []


def _colher(corpo: Any, campos: dict[str, str], exige: str | None = None) -> dict[str, Any]:
    """Os valores pedidos, todos do **mesmo item** da resposta.

    Do mesmo item é o ponto: `usina_id` de um contrato e `container_id` de outro formariam
    um par que não existe, e a rota seguinte tomaria 404 por culpa da sonda, não do
    produto.
    """
    if isinstance(corpo, dict):
        for chave in ("items", "results", "data"):
            if isinstance(corpo.get(chave), list):
                return _colher(corpo[chave], campos, exige)
        item = corpo
    elif isinstance(corpo, list):
        candidatos = [i for i in corpo if isinstance(i, dict)]
        if exige:
            candidatos = [i for i in candidatos if i.get(exige) not in (None, "")]
        item = candidatos[0] if candidatos else {}
    else:
        return {}

    return {
        nome: item.get(campo)
        for nome, campo in campos.items()
        if item.get(campo) not in (None, "")
    }


async def _bater(
    cliente: httpx.AsyncClient, base_url: str, rota: Rota, contexto: dict[str, Any]
) -> tuple[Resultado, Any]:
    """Exercita uma rota. Devolve o resultado e o corpo, para quem chama poder capturar."""
    base = Resultado(
        chave=rota.chave,
        metodo=rota.metodo,
        caminho=rota.caminho,
        alimenta=rota.alimenta,
        essencial=rota.essencial,
        situacao="ok",
    )

    caminho = _preencher(rota.caminho, contexto)
    params = {k: _preencher(v, contexto) for k, v in rota.params.items()}

    if caminho is None or any(v is None for v in params.values()):
        base.situacao = "pulada"
        base.detalhe = (
            "Depende de " + ", ".join(_faltando(rota, contexto)) + ", que a rota anterior "
            "não forneceu."
        )
        return base, None

    inicio = time.perf_counter()
    try:
        resposta = await cliente.request(rota.metodo, f"{base_url}{caminho}", params=params)
    except httpx.TimeoutException:
        base.situacao = "falhou"
        base.ms = int((time.perf_counter() - inicio) * 1000)
        base.detalhe = "Não respondeu a tempo."
        return base, None
    except httpx.HTTPError as exc:
        base.situacao = "falhou"
        base.ms = int((time.perf_counter() - inicio) * 1000)
        base.detalhe = f"{type(exc).__name__}: {exc}"
        return base, None

    base.ms = int((time.perf_counter() - inicio) * 1000)
    base.status = resposta.status_code
    base.caminho = caminho

    if resposta.status_code >= 400:
        base.situacao = "falhou"
        base.detalhe = integracoes.detalhe_do_upstream(resposta) or _frase_do_status(
            resposta.status_code
        )
        return base, None

    try:
        corpo = resposta.json()
    except ValueError:
        base.detalhe = "Respondeu, mas o corpo não é JSON."
        base.situacao = "falhou"
        return base, None

    base.itens, base.campos = _resumir(corpo)
    if base.itens == 0:
        # 200 com lista vazia não é erro, mas é a causa mais comum de tela vazia sem
        # mensagem — merece aparecer escrito.
        base.detalhe = "Respondeu, mas sem nenhum item."
    return base, corpo


def _frase_do_status(codigo: int) -> str:
    if codigo in (401, 403):
        return "Credencial recusada nesta rota."
    if codigo == 404:
        return "Esta rota não existe neste endereço — pode ter mudado de caminho."
    if codigo == 422:
        return "Os parâmetros enviados não foram aceitos — o contrato da rota mudou."
    if codigo >= 500:
        return f"O produto respondeu {codigo} — problema do lado dele."
    return f"Respondeu {codigo}."


@dataclass
class Varredura:
    produto: str
    base_url: str | None
    ok: bool
    detalhe: str
    executada_em: datetime
    rotas: list[Resultado] = field(default_factory=list)


async def varrer(db: Session, produto: Produto) -> Varredura:
    """Passa por todo o catálogo do produto com a credencial gravada.

    A ordem do catálogo importa: as rotas que capturam parâmetros vêm antes das que os
    consomem. Percorrer em sequência (e não em paralelo) é deliberado — além de a captura
    exigir ordem, doze requisições simultâneas contra um produto de terceiro é um pico de
    carga que ninguém pediu.
    """
    agora = datetime.now(UTC)
    integracao = integracoes.obter(db, produto)

    if integracao is None or not integracao.ativa:
        return Varredura(
            produto=produto.value, base_url=None, ok=False,
            detalhe=f"A ponte com o {NOME[produto]} não está configurada. "
                    "Conecte um token em Conexões antes de sondar.",
            executada_em=agora,
        )

    if not integracao.token_cifrado:
        return Varredura(
            produto=produto.value, base_url=integracao.base_url, ok=False,
            detalhe="Esta conexão ainda é por conta de serviço. A sonda exige um token "
                    "pessoal — reconecte por token em Conexões.",
            executada_em=agora,
        )

    try:
        token = decifrar(integracao.token_cifrado)
    except SegredoInvalido as exc:
        return Varredura(
            produto=produto.value, base_url=integracao.base_url, ok=False,
            detalhe=str(exc), executada_em=agora,
        )

    hoje = date.today()
    contexto: dict[str, Any] = {
        "hoje": hoje.isoformat(),
        "semana_passada": (hoje - timedelta(days=7)).isoformat(),
    }

    resultados: list[Resultado] = []
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"Authorization": f"Bearer {token}"},
    ) as cliente:
        for rota in CATALOGO[produto]:
            if not rota.sonda:
                resultados.append(
                    Resultado(
                        chave=rota.chave, metodo=rota.metodo, caminho=rota.caminho,
                        alimenta=rota.alimenta, essencial=rota.essencial,
                        situacao="nao_sondada", detalhe=rota.nao_sondada_porque,
                    )
                )
                continue

            resultado, corpo = await _bater(cliente, integracao.base_url, rota, contexto)
            if rota.captura and corpo is not None:
                contexto.update(_colher(corpo, rota.captura, rota.captura_exige))
            resultados.append(resultado)

    exercitadas = [r for r in resultados if r.situacao in ("ok", "falhou")]
    falhas_essenciais = [r for r in exercitadas if r.situacao == "falhou" and r.essencial]
    falhas_outras = [r for r in exercitadas if r.situacao == "falhou" and not r.essencial]
    ok = len([r for r in exercitadas if r.situacao == "ok"])

    if falhas_essenciais:
        detalhe = (
            f"{len(falhas_essenciais)} rota(s) essenciais não responderam. "
            f"{ok} de {len(exercitadas)} passaram."
        )
    elif falhas_outras:
        detalhe = (
            f"As rotas essenciais passaram. {len(falhas_outras)} rota(s) secundárias "
            "falharam — recurso a menos, não ponte quebrada."
        )
    else:
        detalhe = f"As {ok} rotas exercitadas responderam."

    return Varredura(
        produto=produto.value,
        base_url=integracao.base_url,
        ok=not falhas_essenciais,
        detalhe=detalhe,
        executada_em=agora,
        rotas=resultados,
    )
