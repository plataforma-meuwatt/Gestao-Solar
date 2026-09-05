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
    Rota("mw.pvsyst", "GET", "/plants/{slug}/pvsyst",
         "A meta do projeto (diária) — o 'esperado' do portal do cliente",
         essencial=False, params={"start": "{semana_passada}", "end": "{hoje}"}),
    Rota("mw.pvsyst_manual", "GET", "/plants/{slug}/pvsyst/manual/{ano}",
         "A meta do projeto (mensal, digitada) — segunda fonte do 'esperado'",
         essencial=False),
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
    Rota("mw.alerts_historico", "GET", "/plants/{slug}/alerts",
         "Paradas do portal (fonte reserva enquanto breakdowns/range responde 500)",
         essencial=False, params={"status": "all", "limit": "50", "offset": "0"}),
    Rota("mw.breakdowns", "GET", "/plants/{slug}/breakdowns/range",
         "Paradas do portal — fonte primária; se falhar, o BFF troca sozinho para alerts",
         params={"start": "{semana_passada}", "end": "{hoje}"}),
    Rota("mw.trip_events", "GET", "/plants/{slug}/relays/{relay_id}/trip-events",
         "Histórico de flags do relé de proteção, na tela de Equipamentos",
         essencial=False, sonda=False,
         nao_sondada_porque="O id do relé só aparece dentro de `monitoring/current`, "
                            "como `relay-{id}` no meio dos equipamentos — não há campo "
                            "de topo para a sonda colher. A tela de Equipamentos "
                            "exercita este caminho com o relé escolhido."),
    Rota("mw.slots", "GET", "/plants/{slug}/slots", "Inversores da tela de Equipamentos",
         captura={"slot_id": "id"}),
    # Achada pelo teste inverso da sonda: o cliente chamava `/slots/{id}` há meses sem
    # linha aqui — a versão por prefixo do teste antigo nunca reclamou.
    Rota("mw.slot", "GET", "/plants/{slug}/slots/{slot_id}",
         "A ficha de um inversor (slot), no detalhe do equipamento", essencial=False),
    # A fronteira é MEDIÇÃO de outro aparelho, não uma conta derivada da geração: sem ela
    # o Painel esconde o "medido na fronteira", a perda até o ponto de entrega e a
    # conciliação com a conta de energia — três blocos a menos, não uma ponte quebrada.
    # Usina sem medidor responde 200 com o mapa vazio, e isso é estado normal.
    Rota("mw.ssu_mensal", "GET", "/plants/{slug}/ssu-readers/monthly-totals",
         "A energia medida na fronteira, mês a mês — o 'medido na fronteira' do Painel "
         "e a conciliação com a conta de energia",
         essencial=False, params={"year": "{ano}"}),
    Rota("mw.bills", "GET", "/plants/{slug}/utility-bills",
         "Faturas da concessionária — o MWh faturado por UC, na conciliação do Painel",
         essencial=False, params={"year": "{ano}"}),
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
    Rota("mw.portal_arquivo", "GET", "/reports/{report_id}/files/{kind}",
         "Os PDFs de geração e de paradas de um fechamento publicado", essencial=False,
         sonda=False,
         nao_sondada_porque="O id do fechamento só sai de `/reports/portal`, que a sonda "
                            "não chama (acima). E é um download de arquivo, não JSON."),
    Rota("mw.login", "POST", "/auth/login",
         "O login com a credencial do PRÓPRIO usuário, uma vez, ao entrar",
         sonda=False,
         nao_sondada_porque="Exige uma senha, e a sonda só tem o token pessoal. Se o "
                            "login sumisse, a tela de Conexões (que autentica de "
                            "verdade) avisaria antes."),
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
         "Ordens de serviço da usina", params={"plant_id": "{usina_id}"},
         captura={"so_id": "id"}),
    Rota("mp.ordem", "GET", "/api/v1/meuacesso/service-orders/{so_id}",
         "Cabeçalho da OS na tela de Manutenção — e a checagem de escopo antes do PDF"),
    Rota("mp.tarefas", "GET", "/api/v1/meuacesso/tasks",
         "As tarefas dentro da OS: o que foi feito, item por item",
         params={"os_id": "{so_id}"}, captura={"task_id": "id"}),
    # A tarefa devolve o item do plano e o mês contratual de onde ela veio — o par que a
    # rota seguinte precisa. Tarefa avulsa (fora do plano) vem com os dois vazios, e a
    # seguinte fica pulada com a razão escrita, em vez de 422 por parâmetro faltando.
    Rota("mp.tarefa", "GET", "/api/v1/meuacesso/tasks/{task_id}",
         "Cabeçalho da tarefa na tela da OS, e a checagem de escopo antes da ficha",
         captura={"plan_item_id": "usina_type_plan_item_id",
                  "mes_contratual": "contract_month"}),
    Rota("mp.tarefas_do_item", "GET", "/api/v1/meuacesso/tasks",
         "As tarefas atrás de um X do cronograma (item do plano × mês)",
         params={"usina_type_plan_item_id": "{plan_item_id}",
                 "contract_month": "{mes_contratual}"}),
    Rota("mp.tarefa_ficha", "GET", "/api/v1/meuacesso/tasks/{task_id}/ficha",
         "As respostas da tarefa: medições, checklist, parecer, por equipamento",
         sonda=False,
         nao_sondada_porque="É leitura, mas monta a ficha inteira (sessões, leituras, "
                            "fotos) a cada chamada — uma coletiva de 20 inversores leva "
                            "dezenas de segundos. A tela da tarefa exercita sob demanda."),
    Rota("mp.tarefa_foto", "GET", "/api/v1/meuacesso/tasks/{task_id}/fotos/{foto_id}",
         "Os bytes de uma foto da ficha", essencial=False,
         sonda=False,
         nao_sondada_porque="O id da foto só existe dentro da ficha, que a sonda não "
                            "monta (acima). E é imagem, não JSON."),
    Rota("mp.tarefa_pdf", "GET", "/api/v1/meuacesso/tasks/{task_id}/pdf/view",
         "O PDF da ficha respondida", essencial=False,
         sonda=False,
         nao_sondada_porque="Renderiza o PDF inteiro quando algo mudou desde a última "
                            "versão. Sondar a cada varredura gastaria o gerador do "
                            "meuPlano para conferir uma rota que a tela exercita sob "
                            "demanda."),
    # O cronograma mora dentro de um contrato, e o contrato vem daqui — do pipeline, não
    # do financeiro: são duas tabelas de container com numerações próprias, e o cronograma
    # só reconhece a do pipeline. As duas rotas são sondadas em sequência de propósito, o
    # par (usina, contrato) tem de sair do MESMO registro.
    Rota("mp.contratos", "GET", "/api/v1/meuacesso/pipelines/global/contrato/containers",
         "Os contratos de O&M — é dentro de um deles que existe cronograma",
         captura={"container_id": "id", "contrato_usina_id": "usina_id"},
         captura_exige="usina_id"),
    # O cronograma que o CLIENTE vê vem do router `visao-cliente`, não da rota interna:
    # a interna cria o rascunho v1 ao ser lida (leitura com efeito colateral) e devolve
    # DRAFT como se fosse o combinado. A lista de contratos dessa visão diz qual deles tem
    # versão consolidada — `captura_exige` escolhe um assim, senão o cronograma responderia
    # 404 por culpa da sonda (contrato só com rascunho), não do produto.
    Rota("mp.vc_contratos", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/contratos",
         "Os contratos da usina com a versão consolidada de cada um — o seletor de "
         "contrato do portal do cliente",
         captura={"vc_container_id": "id"}, captura_exige="versao_consolidada"),
    Rota("mp.cronograma", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/cronograma",
         "Cronograma consolidado do contrato, com a cor de cada célula",
         params={"container_id": "{vc_container_id}"}),
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
    # Pendências do portal do cliente: a rota `visao-cliente` recorta pelo `shareable` sempre,
    # e o BFF recorta de novo. Não essenciais — sem elas o portal perde uma aba, não a ponte.
    Rota("mp.vc_pendencias", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/pendencias",
         "As pendências compartilháveis, na aba Pendências do portal do cliente",
         essencial=False, captura={"pendencia_id": "id"}),
    Rota("mp.vc_pendencia", "GET",
         "/api/v1/meuacesso/visao-cliente/pendencias/{pendencia_id}",
         "O drawer da pendência: parecer, documentos publicados e OSs vinculadas",
         essencial=False),
    Rota("mp.vc_documento", "GET",
         "/api/v1/meuacesso/pipelines/containers/{pendencia_id}/documents/{documento_id}/download",
         "Os bytes de um documento publicado da pendência", essencial=False,
         sonda=False,
         nao_sondada_porque="Baixa um arquivo do armazenamento a cada chamada, e o id do "
                            "documento só existe dentro do detalhe de uma pendência que "
                            "tenha algo publicado. A tela exercita este caminho sob "
                            "demanda, depois de conferir que o documento é publicado."),
    Rota("mp.pdf_os", "POST", "/api/v1/meuacesso/service-orders/{so_id}/pdf",
         "PDF da ordem de serviço", essencial=False,
         sonda=False,
         nao_sondada_porque="Gera um arquivo na cesta do produto de origem. A sonda não "
                            "escreve em sistema de terceiro."),
    Rota("mp.pdf_cesta", "GET", "/api/v1/meuacesso/pdf-basket/{item_id}/download",
         "Os bytes do PDF da OS, depois de gerado", essencial=False,
         sonda=False,
         nao_sondada_porque="O id da cesta só existe depois do POST que gera o arquivo, "
                            "e esse POST escreve no produto de origem — a sonda não o "
                            "chama. Sem ele não há item para baixar."),
    Rota("mp.pdf_cronograma", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/cronograma/pdf/view",
         "Cronograma anual consolidado em PDF", essencial=False,
         params={"container_id": "{vc_container_id}"},
         sonda=False,
         nao_sondada_porque="É leitura, mas renderiza o PDF inteiro a cada chamada. "
                            "Sondar isso a cada varredura gastaria o Chromium do "
                            "meuPlano para conferir uma rota que a tela exercita "
                            "sob demanda."),
    # O relatório de manutenção do portal, por competência: do mês passado ao atual é o
    # menor período que sempre existe. Vai com o contrato consolidado colhido acima — sem
    # ele o upstream escolheria sozinho, e sem nenhum consolidado responderia 404 por um
    # estado normal ("ainda não publicado"); pulada com a razão é o retrato honesto.
    Rota("mp.vc_relatorio", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/relatorio-manutencao",
         "O relatório de manutenção do período, na tela de Relatórios do portal",
         essencial=False,
         params={"de": "{mes_passado}", "ate": "{mes_atual}",
                 "container_id": "{vc_container_id}"}),
    Rota("mp.vc_relatorio_pdf", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/relatorio-manutencao/pdf/view",
         "O mesmo relatório em PDF", essencial=False,
         params={"de": "{mes_passado}", "ate": "{mes_atual}",
                 "container_id": "{vc_container_id}"},
         sonda=False,
         nao_sondada_porque="Renderiza o PDF inteiro a cada chamada. A tela do portal "
                            "exercita sob demanda."),
    # O pacote de fichas do portal: baixar TODOS os PDFs das tarefas de um período. O
    # inventário é leitura pura e é sondado — é ele que descobre, antes do cliente, que a
    # rota mudou de lugar. Os outros três não: PREPARAR escreve (gera PDF no meuPlano), o
    # ANDAMENTO só existe depois desse POST, e o PACOTE baixa dezenas de megabytes e
    # depende de um período que tenha ficha. Declarados com o motivo, como as demais.
    Rota("mp.vc_fichas", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/fichas",
         "O índice das fichas do período — o que a tela de Relatórios lista antes de "
         "oferecer o pacote de PDFs",
         essencial=False,
         params={"de": "{mes_passado}", "ate": "{mes_atual}"}),
    Rota("mp.vc_fichas_preparar", "POST",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/fichas/preparar",
         "Manda gerar as fichas que ainda não têm PDF, antes de montar o pacote",
         essencial=False,
         sonda=False,
         nao_sondada_porque="Escreve no produto de origem (gera versões de PDF). A sonda "
                            "não escreve em sistema de terceiro."),
    Rota("mp.vc_fichas_preparo", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/fichas/preparo/{preparo_id}",
         "O andamento do preparo — o \"14 de 17\" da tela",
         essencial=False,
         sonda=False,
         nao_sondada_porque="O número do preparo só existe depois do POST que o abre — e "
                            "esse POST a sonda não chama."),
    Rota("mp.vc_fichas_pacote", "GET",
         "/api/v1/meuacesso/visao-cliente/usinas/{usina_id}/fichas/pacote/view",
         "O ZIP com todas as fichas do período, em partes numeradas",
         essencial=False,
         params={"de": "{mes_passado}", "ate": "{mes_atual}"},
         sonda=False,
         nao_sondada_porque="É download: monta um ZIP de dezenas de megabytes lendo "
                            "arquivo por arquivo do armazenamento, e só existe pacote "
                            "num período que tenha ficha pronta. A tela de Relatórios "
                            "exercita sob demanda, depois do inventário."),
    Rota("mp.assistente", "POST", "/api/v1/meuacesso/assistant/chat",
         "O assistente", essencial=False,
         sonda=False,
         nao_sondada_porque="Abre uma conversa e consome cota do modelo lá."),
    Rota("mp.assistente_run", "GET", "/api/v1/meuacesso/assistant/runs/{run_id}",
         "A resposta do assistente, por polling", essencial=False,
         sonda=False,
         nao_sondada_porque="O id do run só existe depois do POST que abre a conversa — "
                            "e esse a sonda não chama."),
    Rota("mp.login", "POST", "/api/v1/meuacesso/auth/login",
         "O login com a credencial do PRÓPRIO usuário, uma vez, ao entrar",
         sonda=False,
         nao_sondada_porque="Exige uma senha, e a sonda só tem o token pessoal. Se o "
                            "login sumisse, a tela de Conexões (que autentica de "
                            "verdade) avisaria antes."),
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
    # Competências (YYYY-MM) do relatório do portal: o mês passado até o atual é o menor
    # período que sempre existe — em janeiro inclusive, quando "este ano" é um mês só.
    primeiro_do_mes = hoje.replace(day=1)
    contexto: dict[str, Any] = {
        "hoje": hoje.isoformat(),
        "semana_passada": (hoje - timedelta(days=7)).isoformat(),
        "ano": str(hoje.year),
        "mes_atual": hoje.strftime("%Y-%m"),
        "mes_passado": (primeiro_do_mes - timedelta(days=1)).strftime("%Y-%m"),
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
