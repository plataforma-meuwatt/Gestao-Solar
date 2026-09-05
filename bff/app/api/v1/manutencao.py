"""Manutenção — o histórico de ordens de serviço atendidas, vindo do meuPlano.

Esta aba responde uma pergunta que nenhuma outra tela respondia: **o que já foi
feito nas minhas usinas**. As telas existentes olham para a frente (o que está em
aberto, o que está agendado); o dono também precisa olhar para trás, para saber
se o contrato de O&M está sendo cumprido.

Duas decisões que moldam o resultado:

**"Atendida" é `closed_at` preenchido, não status textual.** O status é livre no
meuPlano e varia entre instalações; a data de fechamento é um fato. O predicado
de abertura é **importado** de `notifications`, e não recopiado, porque uma OS
contada como aberta numa tela e fechada na outra é o tipo de divergência que
destrói a confiança nas duas.

**A ordenação é por `closed_at` decrescente.** Histórico se lê do mais recente
para o mais antigo, e o meuPlano não garante ordem nenhuma na lista que devolve.
"""

import asyncio
import re
import time
import unicodedata
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import _instante_medida, usinas_do_usuario
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · manutenção"])


class OrdemAtendidaOut(BaseModel):
    id: int | None = None
    usina: str
    #: O que o serviço era. `objetivo` no meuPlano — o número da OS não diz nada a
    #: quem é dono da usina e não trabalha no sistema de manutenção.
    objetivo: str
    #: PREVENTIVA, CORRETIVA… do próprio meuPlano, sem reinterpretação.
    classificacao: str | None = None
    status: str | None = None

    fechada_em: datetime | None = None
    aprovada_em: datetime | None = None
    tecnico: str | None = None
    #: Minutos de execução, quando o meuPlano souber. A tela formata.
    execucao_min: int | None = None
    tarefas: int | None = None
    tarefas_feitas: int | None = None
    resumo: str | None = None


class ManutencaoOut(BaseModel):
    #: Nulo = nenhuma usina respondeu. Zero é "nenhuma OS atendida", que é diferente.
    total: int | None = None
    ordens: list[OrdemAtendidaOut] = []
    #: Quantas usinas do escopo têm vínculo com o meuPlano. Sem nenhuma, a aba explica
    #: por que está vazia em vez de parecer quebrada.
    usinas_com_manutencao: int = 0
    aviso: str | None = None


#: Como a ponte se CHAMA para quem lê a tela.
#:
#: O dono foi explícito ao pedir o portal: *"em vez de o cliente acessar meuWatt e meuPlano,
#: ele vai acessar o Gestão Solar"* — e quem entra num portal só não deve descobrir, por uma
#: mensagem de erro, que por trás existem dois outros sistemas com nome próprio. Pior: o nome
#: não ajuda em nada, porque o cliente não tem conta neles nem a quem cobrar por eles.
#:
#: Então a REGRA é: nas rotas do cliente (`/api/v1/*`) a ponte é nomeada pelo SERVIÇO que
#: presta — "monitoramento" e "sistema de manutenção". Nas rotas do gestor (`/api/painel/*`)
#: os nomes dos produtos ficam, e devem ficar: lá o diagnóstico existe justamente para dizer
#: em QUAL produto falta o vínculo.
#:
#: Os comentários e docstrings deste arquivo continuam nomeando meuWatt e meuPlano — são para
#: quem mantém o código, e apagá-los tornaria a origem do dado um mistério.
MANUTENCAO = "sistema de manutenção"
MONITORAMENTO = "monitoramento"


def _erro_do_upstream(
    exc: Exception, contexto: str, produto: str = MANUTENCAO
) -> HTTPException:
    """Traduz uma falha do upstream preservando o QUE aconteceu.

    `produto` nomeia a ponte na frase. Nasceu quando `plants.py` (meuWatt) passou a usar
    a mesma régua: sem ele, uma queda do meuWatt chegaria ao portal como "a manutenção
    respondeu 500", apontando o dedo para o serviço errado.

    O padrão antigo — `except Exception` e `HTTPException(502, ...)` — achatava tudo num só
    número. O dono viu o resultado disso em 04/09/2026: um PDF que o upstream recusava por
    PERMISSÃO chegava ao aplicativo como "o meuPlano não conseguiu gerar este PDF agora", uma
    acusação de defeito onde havia uma questão de acesso — e nenhuma pista do que fazer.

    A régua:

    - **401** do upstream vira **502**: o token de serviço é NOSSO, não do dono da usina. Se
      ele expirou, o problema é da ponte, e mandar 401 ao aplicativo o faria deslogar o
      usuário por causa de uma credencial que não é dele.
    - **403 / 404 / 413** passam com o status e a frase do upstream: são respostas que o
      usuário precisa ler literalmente ("sem acesso", "não existe", "o arquivo tem 60 MB e o
      armazenamento aceita 50").
    - **timeout** vira **504**, que é o que de fato houve — e diz para tentar de novo.
    - o resto vira 502 com o motivo anexado.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detalhe = _detalhe_da_resposta(exc.response)
        if status in (403, 404, 413):
            return HTTPException(status, detalhe or f"{contexto}: o {produto} respondeu {status}.")
        if status == 401:
            return HTTPException(502, f"{contexto}: a ponte com o {produto} perdeu a sessão.")
        return HTTPException(502, f"{contexto}: {detalhe or f'o {produto} respondeu {status}'}.")
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(504, f"{contexto}: o {produto} demorou demais para responder.")
    return HTTPException(502, f"{contexto}: {exc}")


def _detalhe_da_resposta(r: "httpx.Response") -> str | None:
    """O `detail` que o meuPlano escreveu, em uma frase. Corpo não-JSON vira texto curto."""
    try:
        corpo = r.json()
    except Exception:  # noqa: BLE001 — corpo binário ou HTML de proxy
        texto = (r.text or "").strip()
        return texto[:300] or None
    if isinstance(corpo, dict):
        detalhe = corpo.get("detail")
        if isinstance(detalhe, str) and detalhe.strip():
            return detalhe.strip()[:300]
        if isinstance(detalhe, list):
            partes = [d.get("msg") for d in detalhe
                      if isinstance(d, dict) and isinstance(d.get("msg"), str)]
            if partes:
                return " · ".join(partes)[:300]
    return None


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    limpo = str(valor).strip()
    return limpo or None


def _inteiro(valor: Any) -> int | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _atendida(o: dict[str, Any]) -> bool:
    """OS efetivamente concluída.

    Importa o predicado de abertura em vez de inventar o inverso: assim as duas
    telas não podem discordar sobre a mesma ordem.
    """
    from app.api.v1.notifications import _esta_aberta  # noqa: PLC0415

    return not _esta_aberta(o)


@router.get("/manutencao", response_model=ManutencaoOut)
async def manutencao_atendida(
    limite: int = 50,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ManutencaoOut:
    """Histórico de ordens de serviço atendidas nas usinas desta pessoa."""
    usinas = usinas_do_usuario(db, usuario)
    com_manutencao = [u for u in usinas if u.mp_usina_id]
    saida = ManutencaoOut(usinas_com_manutencao=len(com_manutencao))

    if not usinas:
        saida.aviso = "Você ainda não tem usina liberada."
        return saida
    if not com_manutencao:
        saida.aviso = "Nenhuma das suas usinas tem manutenção contratada."
        return saida

    try:
        cliente = await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Manutenção indisponível: {exc}"
        return saida

    # Uma chamada por usina, em paralelo: em série, sete usinas seriam sete latências
    # somadas numa tela que abre a frio.
    respostas = await asyncio.gather(
        *[cliente.ordens_servico(u.mp_usina_id) for u in com_manutencao],
        return_exceptions=True,
    )

    ordens: list[OrdemAtendidaOut] = []
    falharam: list[str] = []
    for link, resposta in zip(com_manutencao, respostas, strict=True):
        if not isinstance(resposta, list):
            # Uma usina fora do ar não derruba as outras — a tela mostra o que deu para
            # buscar e diz o que faltou.
            falharam.append(link.nome)
            continue
        for o in resposta:
            if not isinstance(o, dict) or not _atendida(o):
                continue
            ordens.append(_para_saida(o, link))

    # Mais recente primeiro. OS sem data de fechamento vai para o FIM, e não para o
    # topo: `datetime.min` a trataria como antiquíssima e `datetime.max` como
    # recentíssima — as duas mentem. A chave booleana a separa antes de comparar datas.
    datadas = sorted(
        (x for x in ordens if x.fechada_em is not None),
        key=lambda x: x.fechada_em,  # type: ignore[arg-type,return-value]
        reverse=True,
    )
    ordens = [*datadas, *(x for x in ordens if x.fechada_em is None)]

    # `total` nulo quando NENHUMA usina respondeu — é o contrato declarado no campo, e a
    # Visão geral do portal depende dele: com `0` aqui, uma usina com o meuPlano caído
    # saía como "0 OS em andamento", que se lê como "nada acontecendo".
    saida.total = len(ordens) if len(falharam) < len(com_manutencao) else None
    saida.ordens = ordens[: max(1, min(limite, 200))]

    if falharam:
        saida.aviso = f"Não deu para consultar: {', '.join(falharam)}."
    elif not ordens:
        saida.aviso = "Nenhuma ordem de serviço concluída até agora."
    return saida


def _para_saida(o: dict[str, Any], link: PlantLink) -> OrdemAtendidaOut:
    return OrdemAtendidaOut(
        id=_inteiro(o.get("id")),
        usina=link.nome,
        # O que descreve o serviço, na ordem em que o meuPlano costuma preencher.
        #
        # `objetivo` é o campo canônico, e nas OSs reais destas usinas ele vem VAZIO —
        # quem carrega a descrição é `name` ("Termografia", "Testes TC e TP") ou o
        # título do container ("Investigar reinício dos relés"). Parando no `objetivo`,
        # o histórico inteiro sairia como "OS 969", "OS 975", "OS 1005": números que
        # não dizem nada a quem é dono da usina e não trabalha no meuPlano.
        #
        # (A aba Notificações lê só `objetivo` e tem o mesmo buraco — fica anotado.)
        objetivo=(
            _texto(o.get("objetivo"))
            or _texto(o.get("name"))
            or _texto(o.get("container_title"))
            or f"OS {o.get('id')}"
        ),
        classificacao=_texto(o.get("classification")),
        status=_texto(o.get("status")),
        fechada_em=_instante_medida(o.get("closed_at")),
        aprovada_em=_instante_medida(o.get("approved_at")),
        tecnico=_texto(o.get("technician_name") or o.get("technician_label")),
        execucao_min=_inteiro(o.get("execution_minutes") or o.get("total_minutes")),
        tarefas=_inteiro(o.get("task_count")),
        tarefas_feitas=_inteiro(o.get("task_realized_count")),
        resumo=_texto(o.get("resumo") or o.get("conclusao_tecnico") or o.get("notes")),
    )


# ══════════════════════════════════════════════════════════════════════════════
# O que o dono da usina vê da manutenção contratada
# ══════════════════════════════════════════════════════════════════════════════
#
# A aba acima (`GET /manutencao`) responde "o que já foi feito". Falta o resto da
# pergunta, e é a parte que o dono cobra: **o que está acontecendo agora**, o que
# cada OS contém, e se o cronograma do contrato está sendo cumprido.
#
# Três decisões que moldam este bloco:
#
# **O status do meuPlano é traduzido, não repassado.** `FECHADA` não quer dizer
# "encerrada" para quem é dono: quer dizer que o técnico concluiu e o gestor ainda
# não conferiu — a própria UI do meuPlano a rotula "Em verificação"
# (`frontend/.../OSPanel.tsx`). Repassar a palavra crua faria o dono ler uma
# preventiva executada como se estivesse arquivada, e `APROVADA` — que é o
# encerramento de verdade — pareceria a mesma coisa. O mapa vive em `SITUACAO`, e o
# código cru vai junto (`status`) para quem precisar auditar.
#
# **Conformidade não se conta por OS.** É regra máxima do meuPlano: a cor da célula
# do cronograma vem do ATIVO (`asset_compliance.cell_statuses_from_assets`), não de
# contar tarefas. Então o cronograma é **repassado como vem** — este BFF não recalcula
# `cell_status`, porque recalcular seria inventar uma segunda verdade sobre a mesma
# pergunta.
#
# **Autorização por OS, não por parâmetro.** O `so_id` chega do cliente. Antes de
# devolver qualquer coisa, a OS é conferida contra as usinas do escopo dele
# (`_ordem_autorizada`) — sem isso, trocar o número na URL leria a OS de outro dono.

#: `ServiceOrderStatus` do meuPlano (`backend/app/models/tasks.py`) → a frase que o dono
#: entende. Os rótulos seguem os da UI do meuPlano para as duas telas não divergirem.
SITUACAO: dict[str, str] = {
    "ABERTA": "Em preparação",
    "PROGRAMADA": "Agendada",
    "EM_EXECUCAO": "Em execução",
    "FECHADA": "Em verificação",
    "APROVADA": "Concluída",
    "CANCELADA": "Cancelada",
}

#: Tom da tarja. É SEMPRE uma chave de `tons` em `app/src/theme/tokens.ts` —
#: `parado` · `alerta` · `multiplos` · `tempoRuim` · `ok` · `semDados`, em camelCase.
#: A tela faz `tons[tom]`, então nome fora dessa lista não pinta cor errada: não pinta
#: cor nenhuma. A regra de cor é do servidor, como já é em `plants.py`.
TOM_DA_SITUACAO: dict[str, str] = {
    # Ainda não é compromisso com o dono: a OS está sendo montada.
    "ABERTA": "semDados",
    # Data e técnico confirmados — informativo, não alarme.
    "PROGRAMADA": "tempoRuim",
    "EM_EXECUCAO": "alerta",
    "FECHADA": "tempoRuim",
    "APROVADA": "ok",
    "CANCELADA": "semDados",
}

#: `TaskStatus` do meuPlano → o que o dono lê na lista de tarefas.
SITUACAO_TAREFA: dict[str, str] = {
    "PREVISTA": "Prevista",
    "PLANEJADA": "Planejada",
    "PROGRAMADA": "Programada",
    "REALIZADA": "Executada",
    "APROVADA": "Executada e verificada",
    "CANCELADA": "Cancelada",
}

#: Parecer da sessão de ensaio (`SessionVerdict`). Só aparece quando existe ficha
#: respondida — tarefa de serviço não tem parecer, e forçar um seria inventar.
PARECER: dict[str, str] = {
    "APPROVED": "Aprovado",
    "APPROVED_WITH_RESERVATION": "Aprovado com ressalva",
    "REJECTED": "Reprovado",
}

#: A COR do parecer, escrita aqui e não na tela.
#:
#: A situação da OS sempre saiu daqui com `tom`; o parecer da tarefa, não — e o preço
#: apareceu na integração do portal (04/09/2026): três telas (Cronograma, OS e Relatórios)
#: tinham cada uma a SUA cópia da régua, deduzida da frase já traduzida, e as três
#: discordavam. A da OS devolvia "ok" no que não reconhecia: um parecer novo que o meuPlano
#: inventasse sairia VERDE para o cliente — "aprovado" sobre um veredito que ninguém leu.
#: Aqui, o que não está no mapa fica SEM cor, que é a única resposta honesta.
#:
#: Ressalva não é aprovação: cor própria, pela mesma razão que o cronograma se recusa a
#: fundir "feito" com "dispensado".
TOM_DO_PARECER: dict[str, str] = {
    "APPROVED": "ok",
    "APPROVED_WITH_RESERVATION": "alerta",
    "REJECTED": "parado",
}


def _situacao(status: Any) -> tuple[str | None, str, str]:
    """`(código cru, frase para o dono, tom)`.

    Status desconhecido não vira "—": vira o próprio código, capitalizado. O meuPlano
    pode ganhar um estado novo, e engolir isso deixaria a OS sem situação na tela sem
    ninguém saber por quê.
    """
    cru = _texto(status)
    if cru is None:
        return None, "Sem situação", "semDados"
    chave = cru.strip().upper()
    return cru, SITUACAO.get(chave, chave.replace("_", " ").capitalize()), TOM_DA_SITUACAO.get(chave, "semDados")


class TarefaOut(BaseModel):
    """Uma tarefa dentro da OS — o item que o técnico marca como feito."""

    id: int | None = None
    #: O que fazer. `plan_item_name` é o nome do item do plano ("Termografia"); o
    #: fallback percorre os nomes que o meuPlano preenche em cada tipo de tarefa.
    nome: str
    #: Seção da lista: o TIPO do item do plano ("Transformador", "Inversor"). É como a
    #: própria OS do meuPlano agrupa as tarefas.
    grupo: str | None = None
    #: Onde. `equipment_path` distingue cinco trafos de mesmo nome — sem ele o card
    #: repetido é indistinguível.
    equipamento: str | None = None

    status: str | None = None
    situacao: str = "—"
    #: Executada = o técnico concluiu (REALIZADA ou APROVADA). É o que vira ✓ na tela.
    feita: bool = False
    #: INSPECAO | SERVICO — separa "olhar" de "trabalhar" na leitura.
    natureza: str | None = None
    parecer: str | None = None
    #: A cor do parecer (`TOM_DO_PARECER`). Vai junto com a frase porque, sem ela, cada tela
    #: que pinta um parecer precisa deduzir a cor do texto — e três delas fizeram isso de
    #: três jeitos diferentes. Nulo = sem parecer OU parecer que não sabemos classificar; nos
    #: dois casos a tela mostra o texto sem cor, nunca uma cor chutada.
    parecer_tom: str | None = None
    #: A OS que executa esta tarefa. A tela da tarefa é `/ordens/{so}/tarefas/{id}`, então
    #: sem isto o X do cronograma não teria como abrir a tarefa que ele representa.
    os_id: int | None = None
    #: Mês contratual do cronograma ("YYYY-MM"). Nulo em corretiva avulsa.
    mes_contratual: str | None = None
    executada_em: date | None = None

    # ── o que o técnico registrou (só o detalhe traz; a lista não precisa) ──
    #: O que a tarefa pedia, escrito por quem programou.
    descricao: str | None = None
    #: Observações da execução — o que o técnico anotou.
    observacoes: str | None = None
    #: Quanto da ficha está respondido (0-100). Nulo = o upstream não informou;
    #: ZERO é resposta legítima ("nada preenchido ainda") e não pode virar nulo.
    preenchimento: int | None = None


class OrdemOut(BaseModel):
    """Uma OS como o dono da usina a lê."""

    id: int
    usina: str
    #: `id` do vínculo neste sistema — é por ele que o app navega, não pelo id do meuPlano.
    usina_id: int
    #: Número do CONTRATO que rege a OS. **Nunca é o número da OS** — ela não tem um: no
    #: meuPlano a ordem se identifica pelo `id`. O campo se chamava `numero`, e o drawer da
    #: pendência imprimia "OS #665" para o contrato 665 enquanto a lista chamava a MESMA
    #: ordem de "OS 1016". Toda OS daquele contrato virava "OS #665" — o nome era a causa.
    contrato_numero: int | None = None

    objetivo: str
    #: Rótulo PRONTO ("Serviços adicionais"); o código cru fica em `classificacao_codigo`.
    #: Mesmo par de `situacao`/`status`: a tela de Ordens traduzia e a de Relatórios não,
    #: então a mesma OS saía "Serviços adicionais" numa e "SERVICOS_ADICIONAIS" na outra.
    classificacao: str | None = None
    classificacao_codigo: str | None = None
    classificacao_tom: str = "semDados"

    #: Código cru do meuPlano, para auditoria.
    status: str | None = None
    #: A frase que a tela mostra ("Em verificação").
    situacao: str = "—"
    tom: str = "semDados"

    tecnico: str | None = None
    tarefas: int | None = None
    tarefas_feitas: int | None = None

    agendada_para: date | None = None
    concluida_em: date | None = None
    fechada_em: datetime | None = None
    aprovada_em: datetime | None = None
    execucao_min: int | None = None
    resumo: str | None = None

    #: Só o detalhe preenche. A lista vem sem tarefas — seriam N+1 chamadas ao upstream
    #: para uma tela que mostra a contagem, não os itens.
    itens: list[TarefaOut] | None = None


class OrdensOut(BaseModel):
    #: Nulo = nenhuma usina respondeu. Zero = não há OS, que é diferente.
    total: int | None = None
    #: A que o dono precisa ver primeiro: a mais recente que ainda não foi encerrada.
    em_andamento: OrdemOut | None = None
    ordens: list[OrdemOut] = []
    usinas_com_manutencao: int = 0
    aviso: str | None = None


class CelulaOut(BaseModel):
    """Um mês de uma linha do cronograma."""

    mes: str                      # "YYYY-MM"
    #: Quantas ocorrências o contrato prevê neste mês. 0 = mês vazio na matriz.
    previsto: int = 0
    #: `cell_status` do meuPlano, repassado: verde | azul | laranja | vermelho |
    #: verde_ressalva | None. A cor vem do ATIVO, não de contar tarefas — ver o
    #: cabeçalho deste bloco.
    estado: str | None = None
    #: O ✓ da tela. Só `verde` é executado de fato; `verde_ressalva` é dispensa, e
    #: apagar essa diferença era exatamente o risco que o meuPlano recusou correr.
    feito: bool = False
    dispensado: bool = False
    atrasado: bool = False


class LinhaCronogramaOut(BaseModel):
    """Uma atividade do contrato ao longo dos 12 meses."""

    #: O item do plano que esta linha representa. É por ele que se descobre QUAIS tarefas
    #: estão atrás do X de um mês — sem ele, a célula é uma marca sem porta.
    plan_item_id: int | None = None
    nome: str
    #: O selo da linha, JÁ EM PORTUGUÊS ("Ensaio", "Serviço", "Inspeção"). O upstream manda
    #: 'ensaio', 'SERVICO', 'INSPECAO' — caixas misturadas, vocabulário de banco. O código
    #: cru fica em `categoria_codigo` para auditoria.
    categoria: str | None = None
    categoria_codigo: str | None = None
    #: "A cada 6 meses", "Anual", "Trimestral". Vinha "6/MONTH", "1/YEAR", "3/MONTH" —
    #: periodicidade em inglês na tela de um cliente corporativo brasileiro.
    periodicidade: str | None = None
    #: Sob que bloco esta atividade aparece na tela ("Subestação", "CFTV", "Inversores"…).
    #: 94 linhas planas eram a análise de equipamento que o dono disse que o cliente NÃO
    #: quer; agrupadas e recolhidas, viram "está sendo feito?" com o detalhe atrás de um
    #: clique. Vem do grupo de equipamentos do plano, senão do agrupamento de ensaio do tipo.
    grupo: str = "Outras atividades"
    previsto_ano: int = 0
    feitos: int = 0
    meses: list[CelulaOut] = []


class ContratoOut(BaseModel):
    """Um contrato de O&M da usina — o que o seletor de contrato do portal lista."""

    #: id do container no meuPlano. É o `contrato_id` que as rotas de cronograma e
    #: relatório aceitam; o número (`numero`) é só rótulo.
    id: int
    numero: int | None = None
    titulo: str | None = None
    inicio: date | None = None
    fim: date | None = None
    #: Nulo quando o meuPlano não soube dizer (contrato sem vigência cadastrada).
    vigente: bool | None = None
    #: Versão do cronograma CONSOLIDADO. Nulo = só rascunho, ou nenhum — nos dois casos
    #: o cliente não tem cronograma para ver neste contrato.
    versao_cronograma: int | None = None


class ContratosOut(BaseModel):
    usina: str
    usina_id: int
    contratos: list[ContratoOut] = []
    aviso: str | None = None


class CronogramaOut(BaseModel):
    usina: str
    usina_id: int
    #: O contrato de onde a matriz veio (id do container no meuPlano). Vai junto para o
    #: seletor da tela saber qual está marcado quando o cliente não escolheu nenhum.
    contrato_id: int | None = None
    contrato: str | None = None
    #: Só CONSOLIDATED chega aqui — a rota de cliente do meuPlano não serve rascunho.
    #: Nulo = a equipe ainda não publicou o cronograma deste contrato.
    status: str | None = None
    versao: int | None = None
    #: 12 × "YYYY-MM", em ordem. O mês 1 é a âncora do contrato, não janeiro.
    meses: list[str] = []
    linhas: list[LinhaCronogramaOut] = []
    #: Σ previsto e Σ feito do ano — o cabeçalho "18 de 24 atividades cumpridas".
    previsto_ano: int = 0
    feitos_ano: int = 0
    #: Se a rota irmã `/cronograma/pdf` tem o que gerar. Sem consolidação o JSON responde
    #: 200 com matriz vazia e a frase, mas o PDF responde 404 — um arquivo não tem como
    #: avisar por dentro. O par ficava incoerente para quem chamasse o PDF direto (um link
    #: salvo, um relatório); com este campo, ninguém oferece o botão que só dá erro.
    pdf_disponivel: bool = False
    aviso: str | None = None


# ── helpers de leitura ──────────────────────────────────────────────────────


def _data(valor: Any) -> date | None:
    """`date` a partir do que o meuPlano manda — texto ISO, ou já um `date`."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    instante = _instante_medida(valor)
    return instante.date() if instante else None


#: Estados em que a OS já saiu do papel e ainda não foi encerrada pelo gestor.
AGUARDA_VERIFICACAO = {"EM_EXECUCAO", "FECHADA"}


def _situacao_da_ordem(o: dict[str, Any]) -> tuple[str | None, str, str]:
    """A situação da OS já contando as tarefas.

    O status sozinho engana o dono no caso mais comum. A preventiva de agosto de Porto
    Ferreira (OS 1016) está `EM_EXECUCAO` com as **17 tarefas executadas**: pelo status
    cru a tela diria "Em execução", e o dono entenderia que o técnico ainda está na
    usina — quando o serviço acabou e o que falta é a conferência do gestor.

    Então quando todas as tarefas estão cumpridas e a OS não foi encerrada, a frase
    passa a dizer isso. Não é número inventado: `task_count` e `task_realized_count`
    são do próprio meuPlano, e o status cru continua em `status` para auditoria.

    Só vale com `tarefas > 0`. OS de zero tarefa (as canceladas de teste, por exemplo)
    cairia em `0 == 0` e sairia como "executada" sem nada ter sido feito.
    """
    cru, frase, tom = _situacao(o.get("status"))
    chave = (cru or "").strip().upper()
    total = _inteiro(o.get("task_count")) or 0
    feitas = _inteiro(o.get("task_realized_count")) or 0
    if chave in AGUARDA_VERIFICACAO and total > 0 and feitas >= total:
        return cru, "Executada · aguardando verificação", "tempoRuim"
    return cru, frase, tom


#: Categoria da linha do cronograma → o selo que a tela mostra. O meuPlano manda a
#: categoria da TELA de ensaio ('ensaio'/'servico', minúsculo) ou a natureza do CHECKLIST
#: ('INSPECAO', maiúsculo) — dois vocabulários, duas caixas, ambos de banco.
CATEGORIA_LINHA: dict[str, str] = {
    "ENSAIO": "Ensaio",
    "SERVICO": "Serviço",
    "INSPECAO": "Inspeção",
    "MANUTENCAO": "Manutenção",
    "LIMPEZA": "Limpeza",
}

#: Unidade de periodicidade do meuPlano → (singular, plural). O vocabulário canônico é
#: `DAY|WEEK|MONTH|YEAR` (a coluna do modelo diz isso), mas há linhas gravadas em
#: português — e o plural cai errado quando a unidade não está no mapa ("A cada 4 ano").
#: Os dois vocabulários entram porque os dois chegam.
_UNIDADE = {
    "MONTH": ("mês", "meses"), "YEAR": ("ano", "anos"),
    "WEEK": ("semana", "semanas"), "DAY": ("dia", "dias"),
    "MES": ("mês", "meses"), "MÊS": ("mês", "meses"), "ANO": ("ano", "anos"),
    "SEMANA": ("semana", "semanas"), "DIA": ("dia", "dias"),
}

#: Unidade em português → a chave canônica, para a periodicidade nomeada valer nos dois.
_UNIDADE_CANONICA = {"MES": "MONTH", "MÊS": "MONTH", "ANO": "YEAR",
                     "SEMANA": "WEEK", "DIA": "DAY"}

#: Os casos que têm nome próprio em português. Fora deles, "a cada N <unidade>".
_PERIODICIDADE_NOMEADA = {
    (1, "MONTH"): "Mensal", (2, "MONTH"): "Bimestral", (3, "MONTH"): "Trimestral",
    (4, "MONTH"): "Quadrimestral", (6, "MONTH"): "Semestral", (12, "MONTH"): "Anual",
    (1, "YEAR"): "Anual", (2, "YEAR"): "Bienal", (1, "WEEK"): "Semanal",
    (1, "DAY"): "Diária",
}


def _categoria_da_linha(r: dict[str, Any]) -> tuple[str | None, str | None]:
    """(selo em português, código cru). Código desconhecido vira Capitalizado — o cliente
    corporativo nunca lê 'INSPECAO' na tela, e o auditor ainda tem o código."""
    codigo = _texto(r.get("screen_categoria")) or _texto(r.get("checklist_natureza"))
    if codigo is None:
        return None, None
    chave = codigo.strip().upper()
    return CATEGORIA_LINHA.get(chave, chave.replace("_", " ").capitalize()), codigo


def _periodicidade(valor: int | None, unidade: str | None) -> str | None:
    """"6/MONTH" → "Semestral"; "5/MONTH" → "A cada 5 meses". Sem valor, só a unidade
    traduzida; sem unidade, nada (nunca o código cru)."""
    bruta = (unidade or "").strip().upper()
    if not bruta:
        return None
    chave = _UNIDADE_CANONICA.get(bruta, bruta)
    if valor is None:
        singular, _plural = _UNIDADE.get(chave, (chave.lower(), chave.lower()))
        return singular.capitalize()
    nomeada = _PERIODICIDADE_NOMEADA.get((valor, chave))
    if nomeada:
        return nomeada
    singular, plural = _UNIDADE.get(chave, (chave.lower(), chave.lower()))
    return f"A cada {valor} {singular if valor == 1 else plural}"


#: Código de classificação do meuPlano → como o cliente lê. É a ÚNICA tradução: quem
#: quiser o código tem `classificacao_codigo`. O `SERVICOS_ADICIONAIS` cru chegou à tela do
#: relatório com underscore e tudo, ao lado da mesma OS já traduzida na lista de ordens.
CLASSIFICACAO: dict[str, tuple[str, str]] = {
    "CORRETIVA": ("Corretiva", "alerta"),
    "PREVENTIVA": ("Preventiva", "ok"),
    "SERVICOS_ADICIONAIS": ("Serviços adicionais", "semDados"),
    "SINISTRO": ("Sinistro", "parado"),
    "GARANTIA": ("Garantia", "multiplos"),
}


def _classificacao(valor: Any) -> tuple[str | None, str | None, str]:
    """(rótulo, código cru, tom). Código desconhecido vira Frase Capitalizada sem underscore
    — nunca o código cru, que é vocabulário de banco na cara do cliente."""
    codigo = _texto(valor)
    if codigo is None:
        return None, None, "semDados"
    chave = codigo.strip().upper()
    if chave in CLASSIFICACAO:
        rotulo, tom = CLASSIFICACAO[chave]
        return rotulo, codigo, tom
    limpo = chave.replace("_", " ").capitalize()
    return limpo, codigo, "semDados"


def _ordem_out(o: dict[str, Any], link: PlantLink) -> OrdemOut:
    cru, frase, tom = _situacao_da_ordem(o)
    classificacao, classe_codigo, classe_tom = _classificacao(o.get("classification"))
    return OrdemOut(
        id=_inteiro(o.get("id")) or 0,
        usina=link.nome,
        usina_id=link.id,
        contrato_numero=_inteiro(o.get("container_numero")),
        # Mesma cascata de `_para_saida`: `objetivo` vem vazio nas OSs reais destas
        # usinas, e parar nele deixaria a lista inteira como "OS 1005".
        objetivo=(
            _texto(o.get("objetivo"))
            or _texto(o.get("name"))
            or _texto(o.get("container_title"))
            or f"OS {o.get('id')}"
        ),
        classificacao=classificacao,
        classificacao_codigo=classe_codigo,
        classificacao_tom=classe_tom,
        status=cru,
        situacao=frase,
        tom=tom,
        tecnico=_texto(o.get("technician_name") or o.get("technician_label")),
        tarefas=_inteiro(o.get("task_count")),
        tarefas_feitas=_inteiro(o.get("task_realized_count")),
        agendada_para=_data(o.get("scheduled_date")),
        concluida_em=_data(o.get("end_date")),
        fechada_em=_instante_medida(o.get("closed_at")),
        aprovada_em=_instante_medida(o.get("approved_at")),
        execucao_min=_inteiro(o.get("execution_minutes") or o.get("total_minutes")),
        resumo=_texto(o.get("resumo") or o.get("conclusao_tecnico") or o.get("notes")),
    )


#: Tarefa cumprida. `APROVADA` entra: verificada é mais que executada, não menos.
FEITAS = {"REALIZADA", "APROVADA"}


def _tarefa_out(t: dict[str, Any]) -> TarefaOut:
    status = _texto(t.get("status"))
    chave = (status or "").strip().upper()
    parecer_cru = (_texto(t.get("verdict_status")) or "").strip().upper()
    return TarefaOut(
        id=_inteiro(t.get("id")),
        nome=(
            _texto(t.get("plan_item_name"))
            or _texto(t.get("ensaio_screen_name"))
            or _texto(t.get("checklist_name"))
            or _texto(t.get("name"))
            or f"Tarefa {t.get('id')}"
        ),
        grupo=_texto(t.get("plan_type_label")) or _texto(t.get("plan_type_code")),
        equipamento=_texto(t.get("equipment_path")) or _texto(t.get("equipment_name")),
        status=status,
        situacao=SITUACAO_TAREFA.get(chave, chave.replace("_", " ").capitalize() or "—"),
        feita=chave in FEITAS,
        natureza=_texto(t.get("checklist_natureza")),
        parecer=PARECER.get(parecer_cru) if parecer_cru else None,
        parecer_tom=TOM_DO_PARECER.get(parecer_cru) if parecer_cru else None,
        os_id=_inteiro(t.get("os_id")),
        mes_contratual=_texto(t.get("contract_month")),
        executada_em=_data(t.get("scheduled_date")),
        # O dono pediu para "ver as respostas" da tarefa. O detalhe de cada medição vive no
        # PDF (é o laudo); o que dá para ler direto na tela é o que a tarefa pedia, o que o
        # técnico anotou e quanto da ficha foi respondido.
        descricao=_texto(t.get("description")),
        observacoes=_texto(t.get("notes")),
        preenchimento=_inteiro(t.get("fill_percent")),
    )


async def _usinas_com_manutencao(db: Session, usuario: User) -> tuple[list[PlantLink], str | None]:
    """As usinas desta pessoa que têm o outro lado do vínculo.

    Devolve o aviso junto porque as duas razões de lista vazia — "nenhuma usina
    liberada" e "nenhuma ligada ao meuPlano" — pedem frases diferentes na tela, e
    decidir isso em cada endpoint produziria três textos para o mesmo caso.
    """
    usinas = usinas_do_usuario(db, usuario)
    if not usinas:
        return [], "Você ainda não tem usina liberada."
    com = [u for u in usinas if u.mp_usina_id]
    if not com:
        return [], "Nenhuma das suas usinas tem manutenção contratada."
    return com, None


def _link_do_escopo(db: Session, usuario: User, usina_id: int) -> PlantLink:
    """O vínculo pedido, se for desta pessoa. Senão, 404.

    **404 e não 403**: dizer "proibido" confirmaria que a usina existe, e quem trocou
    o número na URL não tem por que descobrir isso.
    """
    for u in usinas_do_usuario(db, usuario):
        if u.id == usina_id:
            if not u.mp_usina_id:
                raise HTTPException(404, "Esta usina não tem manutenção contratada.")
            return u
    raise HTTPException(404, "Usina não encontrada.")


# ── ordens de serviço ───────────────────────────────────────────────────────


#: OS que ainda pede algo de alguém. `FECHADA` entra: está esperando a verificação do
#: gestor, e é justamente o estado da preventiva que o dono quer acompanhar.
EM_CURSO = {"ABERTA", "PROGRAMADA", "EM_EXECUCAO", "FECHADA"}


@router.get("/manutencao/ordens", response_model=OrdensOut)
async def listar_ordens(
    usina_id: int | None = None,
    limite: int = 100,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> OrdensOut:
    """Todas as ordens de serviço das usinas desta pessoa, abertas e encerradas.

    Diferente de `GET /manutencao`, que é só histórico: aqui entra o que está em curso,
    porque é isso que responde "a manutenção que eu contratei está sendo feita?".

    `em_andamento` sai destacado — a OS não encerrada mais recente. Sem esse campo a
    tela teria de reproduzir a regra de "qual é a atual", e a regra mudaria em dois
    lugares.
    """
    if usina_id is not None:
        alvo = _link_do_escopo(db, usuario, usina_id)
        com_manutencao, aviso = [alvo], None
    else:
        com_manutencao, aviso = await _usinas_com_manutencao(db, usuario)

    saida = OrdensOut(usinas_com_manutencao=len(com_manutencao), aviso=aviso)
    if not com_manutencao:
        return saida

    try:
        cliente = await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Manutenção indisponível: {exc}"
        return saida

    respostas = await asyncio.gather(
        *[cliente.ordens_servico(u.mp_usina_id) for u in com_manutencao],
        return_exceptions=True,
    )

    ordens: list[OrdemOut] = []
    falharam: list[str] = []
    for link, resposta in zip(com_manutencao, respostas, strict=True):
        if not isinstance(resposta, list):
            falharam.append(link.nome)
            continue
        ordens.extend(
            _ordem_out(o, link) for o in resposta if isinstance(o, dict) and o.get("id")
        )

    # Mais recente primeiro, pela data que existe: a de conclusão quando encerrada, a
    # de agendamento quando não. OS sem data nenhuma vai para o fim — ver a nota de
    # `manutencao_atendida` sobre por que `datetime.min`/`max` mentem os dois.
    def _quando(x: OrdemOut) -> date | None:
        return x.concluida_em or x.agendada_para or (x.fechada_em.date() if x.fechada_em else None)

    datadas = sorted((x for x in ordens if _quando(x)), key=lambda x: _quando(x), reverse=True)  # type: ignore[arg-type,return-value]
    ordens = [*datadas, *(x for x in ordens if not _quando(x))]

    saida.em_andamento = next(
        (o for o in ordens if (o.status or "").strip().upper() in EM_CURSO), None
    )
    # `total` nulo quando NENHUMA usina respondeu — é o contrato declarado no campo, e a
    # Visão geral do portal depende dele: com `0` aqui, uma usina com o meuPlano caído
    # saía como "0 OS em andamento", que se lê como "nada acontecendo".
    saida.total = len(ordens) if len(falharam) < len(com_manutencao) else None
    saida.ordens = ordens[: max(1, min(limite, 300))]

    if falharam:
        saida.aviso = f"Não deu para consultar: {', '.join(falharam)}."
    elif not ordens:
        saida.aviso = "Nenhuma ordem de serviço registrada nas suas usinas."
    return saida


async def _ordem_autorizada(
    db: Session, usuario: User, so_id: int
) -> tuple[Any, dict[str, Any], PlantLink]:
    """A OS, o cliente do meuPlano e o vínculo — depois de checar o escopo.

    O `so_id` vem do cliente, então a OS é buscada e o `plant_id` dela conferido contra
    as usinas desta pessoa. Confiar no número seria abrir a OS de outro dono trocando
    um dígito na URL.
    """
    # As usinas desta pessoa e a ponte com o meuPlano são perguntas independentes: esperar
    # uma para começar a outra somava segundos numa cadeia que já tem quatro idas ao
    # upstream — e foi o bastante para a ficha de vinte inversores estourar o prazo do
    # aplicativo (04/09/2026). Nada é DEVOLVIDO antes da checagem de escopo, logo abaixo.
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
        ordem = await cliente.ordem_servico(so_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, "Ordem de serviço não encontrada.") from exc
        raise _erro_do_upstream(exc, "Não deu para conferir a ordem de serviço") from exc
    except Exception as exc:  # noqa: BLE001 — timeout, rede
        raise _erro_do_upstream(exc, "Não deu para conferir a ordem de serviço") from exc

    alvo = _inteiro(ordem.get("plant_id"))
    link = next((u for u in com_manutencao if u.mp_usina_id == alvo), None)
    if link is None:
        # Mesma razão de `_link_do_escopo`: 404, não 403.
        raise HTTPException(404, "Ordem de serviço não encontrada.")
    return cliente, ordem, link


@router.get("/manutencao/ordens/{so_id}", response_model=OrdemOut)
async def detalhar_ordem(
    so_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> OrdemOut:
    """Uma OS com as tarefas dentro — o que foi feito, item por item."""
    cliente, ordem, link = await _ordem_autorizada(db, usuario, so_id)
    saida = _ordem_out(ordem, link)

    try:
        tarefas = await cliente.tarefas_da_ordem(so_id)
    except Exception:  # noqa: BLE001
        # A OS abre mesmo assim: o cabeçalho já responde a pergunta principal, e
        # `itens=None` diz "não deu para buscar" — diferente de `[]`, que afirmaria
        # que a OS não tem tarefa nenhuma.
        return saida

    itens = [_tarefa_out(t) for t in tarefas if isinstance(t, dict)]
    # Agrupadas por seção, como na OS do meuPlano; dentro da seção, ordem do upstream.
    itens.sort(key=lambda t: (t.grupo or "￿", t.nome))
    saida.itens = itens
    return saida


# ── PDF ─────────────────────────────────────────────────────────────────────
#
# Dois passos no upstream: `POST .../pdf` põe na cesta (e reaproveita a versão quando
# nada mudou, por fingerprint) e `GET /pdf-basket/{id}/download` traz os bytes. O app
# recebe o arquivo pronto e o abre no `PdfViewer` — nunca entrega a um app externo,
# que no Android dá tela preta silenciosa (regra do CLAUDE.md).


def _nome_ascii(nome: str) -> str:
    """O mesmo nome, reduzido ao que cabe num cabeçalho HTTP.

    Cabeçalho é latin-1 no Starlette, e o meuPlano carimba o mês do contrato em TODA
    tarefa gerada pelo cronograma no formato ' — MM/AAAA', com travessão (U+2014), que
    não existe em latin-1: montar o `Content-Disposition` com o nome cru estourava
    `UnicodeEncodeError` ao construir o Response — antes do middleware de CORS, então o
    navegador via "falha de rede" e o portal acusava a internet do cliente por um defeito
    do servidor. Aconteceu nas 17 tarefas da OS 1016 (Porto Ferreira, 08/2026).

    Não basta trocar o travessão: acento também não pode viajar cru num cabeçalho. Aqui
    o nome vira ASCII (o `filename*` logo abaixo devolve o nome bonito a quem entende
    RFC 5987) e nunca fica vazio — nome sem uma letra ASCII viraria `.pdf`.
    """
    limpo = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    limpo = re.sub(r'[\\/:*?"<>|\r\n]+', "-", limpo)
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "-", limpo).strip("-._")
    limpo = re.sub(r"-{2,}", "-", limpo)
    return limpo or "documento.pdf"


def _pdf(conteudo: bytes, nome: str) -> Response:
    ascii_nome = _nome_ascii(nome)
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={
            # `inline`: o destino é o visualizador embutido, não a pasta de downloads.
            # Dois nomes de propósito: o ASCII para qualquer cliente, e o `filename*` em
            # UTF-8 para quem sabe lê-lo — assim o cliente salva "Inspeção do cercamento"
            # e não "Inspecao-do-cercamento".
            "Content-Disposition": (
                f'inline; filename="{ascii_nome}"; '
                f"filename*=UTF-8''{quote(nome, safe='')}"
            ),
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/manutencao/ordens/{so_id}/pdf")
async def pdf_da_ordem(
    so_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """O PDF da OS, com as tarefas e as fichas respondidas."""
    cliente, _ordem, link = await _ordem_autorizada(db, usuario, so_id)
    try:
        item = await cliente.gerar_pdf_os(so_id)
        conteudo = await cliente.baixar_pdf_cesta(item)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para gerar o PDF desta OS") from exc
    if not conteudo:
        raise HTTPException(502, f"O {MANUTENCAO} devolveu um PDF vazio.")
    return _pdf(conteudo, f"OS {so_id} - {link.nome}.pdf")


async def _tarefa_autorizada(
    db: Session, usuario: User, so_id: int, task_id: int
) -> tuple[Any, dict[str, Any], PlantLink]:
    """A tarefa, depois de checar que ela é DAQUELA OS e que a OS é de uma usina desta pessoa.

    Conferir só a OS não bastaria: com `so_id` legítimo e `task_id` de outra ordem, a ficha de
    outro cliente sairia por aqui. A tarefa tem de pertencer à OS autorizada.
    """
    cliente, ordem, link = await _ordem_autorizada(db, usuario, so_id)
    try:
        tarefa = await cliente.tarefa(task_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, "Tarefa não encontrada.") from exc
        # 500, 502, 503 do upstream NÃO são "não encontrada". Em 04/09/2026 o meuPlano
        # respondeu 500 (pool de conexões esgotado) e o dono leu "tarefa não encontrada"
        # numa tarefa que estava ali — a frase mandava procurar no lugar errado.
        raise _erro_do_upstream(exc, "Não deu para conferir a tarefa") from exc
    except Exception as exc:  # noqa: BLE001 — timeout, rede
        raise _erro_do_upstream(exc, "Não deu para conferir a tarefa") from exc
    # A ordem já foi conferida contra as usinas desta pessoa; falta a tarefa ser DELA.
    if _inteiro(tarefa.get("os_id")) != _inteiro(ordem.get("id")):
        # 404 (e não 403) pela mesma razão de `_ordem_autorizada`: não confirmamos a
        # existência de uma tarefa que esta pessoa não pode ver.
        raise HTTPException(404, "Tarefa não encontrada nesta ordem de serviço.")
    return cliente, tarefa, link


@router.get("/manutencao/ordens/{so_id}/tarefas/{task_id}", response_model=TarefaOut)
async def detalhar_tarefa(
    so_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> TarefaOut:
    """UMA tarefa da OS — o que era, em que equipamento, como terminou.

    O dono (03/09/2026): *"as tarefas não são clicáveis, são como checklist. Eu preciso ABRIR
    as tarefas e ver as respostas delas"*. A lista da OS mostrava nome e estado; abrir era
    impossível porque não havia nem tela nem rota. Esta é a rota.
    """
    _cliente, tarefa, _link = await _tarefa_autorizada(db, usuario, so_id, task_id)
    return _tarefa_out(tarefa)


class LinhaMedicaoOut(BaseModel):
    """Um ponto medido.

    `aprovado` é tri-estado: sim, não e "não se aplica" (nulo). `situacao` é outra coisa — o
    RÓTULO que o laudo imprime quando o item não é um julgamento, e sim um estado: "Não feito"
    num item de serviço, por exemplo. Eram o mesmo campo do lado do meuPlano, e um item de
    torque com `aprovado: "Aprovado"` derrubava a validação da ficha inteira — foi por isso
    que a manutenção mensal dos inversores de Porto Ferreira nunca abria (04/09/2026).
    """

    ponto: str
    valor: str | None = None
    unidade: str | None = None
    alvo: str | None = None
    desvio: str | None = None
    aprovado: bool | None = None
    situacao: str | None = None
    observacao: str | None = None

    #: TOLERÂNCIA DELIBERADA. Um campo novo do upstream não pode derrubar a tela: a ficha é
    #: leitura, e perder uma coluna é muito melhor que perder a página. (O padrão do Pydantic
    #: já é ignorar, mas aqui isso é decisão, não acaso — não trocar por "forbid".)
    model_config = {"extra": "ignore"}


class MedicaoOut(BaseModel):
    nome: str
    unidade: str | None = None
    linhas: list[LinhaMedicaoOut] = []


class FotoOut(BaseModel):
    """Uma evidência anexada pelo técnico.

    A `url` é do BFF, não do meuPlano: o aplicativo só tem sessão aqui, e um endereço do
    upstream chegaria ao aparelho sem credencial nenhuma. O que vem de lá é o `id`; o
    endereço é montado nesta casa.
    """

    id: int
    legenda: str | None = None
    url: str
    thumb_url: str


class PerguntaOut(BaseModel):
    pergunta: str
    #: A resposta como o técnico deu. Nulo/"— não respondida —" é ausência, não "não".
    resposta: str | None = None
    #: A resposta É o problema (a régua de polaridade é do meuPlano, não daqui).
    problema: bool = False
    observacao: str | None = None
    #: As fotos DAQUELA resposta. Numa inspeção é aqui que a evidência mora — "existem sinais
    #: de avaria?" e a foto do que se viu —, não no bloco do equipamento.
    fotos: list[FotoOut] = []


class SecaoChecklistOut(BaseModel):
    nome: str
    perguntas: list[PerguntaOut] = []


class EquipamentoFichaOut(BaseModel):
    """O que foi feito NAQUELE equipamento — numa coletiva há vários."""

    equipamento: str
    modelo: str | None = None
    fabricante: str | None = None
    numero_serie: str | None = None
    executado_em: str | None = None
    executado_por: str | None = None
    parecer: str | None = None
    parecer_motivo: str | None = None
    medicoes: list[MedicaoOut] = []
    checklist: list[SecaoChecklistOut] = []
    #: TODAS as fotos do equipamento — as da sessão e as das respostas, já reunidas.
    fotos: list[FotoOut] = []


class FichaOut(BaseModel):
    """A ficha respondida da tarefa, como a tela a lê."""

    id: int | None = None
    nome: str | None = None
    coletiva: bool = False
    parecer: str | None = None
    equipamentos: list[EquipamentoFichaOut] = []
    fotos: int = 0


@router.get("/manutencao/ordens/{so_id}/tarefas/{task_id}/ficha", response_model=FichaOut)
async def ficha_da_tarefa(
    so_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> FichaOut:
    """As RESPOSTAS da tarefa — para ler na tela, sem baixar o PDF.

    O dono (03/09/2026): *"quero ver detalhe na tela"*. O PDF continua sendo o laudo; isto é a
    leitura. Os dois saem da mesma fonte no meuPlano, então não divergem.
    """
    # Pelo cache de propósito: é a ficha que abre a tela, e as miniaturas vêm logo atrás.
    # Autorizada aqui, elas encontram a resposta pronta e não tocam no upstream.
    cliente, _tarefa, _link = await _tarefa_autorizada_em_cache(db, usuario, so_id, task_id)
    try:
        bruta = await cliente.ficha_da_tarefa(task_id)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para ler a ficha desta tarefa") from exc
    _apontar_fotos_para_ca(bruta, so_id, task_id)
    return FichaOut.model_validate(bruta)


def _apontar_fotos_para_ca(ficha: Any, so_id: int, task_id: int) -> None:
    """Troca o endereço das fotos do meuPlano pelo endereço DESTA casa.

    O meuPlano devolve caminhos relativos (`/tasks/6710/fotos/37`) exatamente para que quem
    entrega monte o endereço final. Aqui isso vira `/api/v1/manutencao/ordens/{os}/tarefas/
    {tarefa}/fotos/{foto}` — a única rota que o aplicativo consegue abrir, porque é a única
    onde a sessão dele vale.
    """
    base = f"/api/v1/manutencao/ordens/{so_id}/tarefas/{task_id}/fotos"

    def reescrever(lista: Any) -> None:
        for f in lista or []:
            if isinstance(f, dict) and f.get("id") is not None:
                f["url"] = f"{base}/{f['id']}"
                f["thumb_url"] = f"{base}/{f['id']}?variante=thumb"

    if not isinstance(ficha, dict):
        return
    for equipamento in ficha.get("equipamentos") or []:
        if not isinstance(equipamento, dict):
            continue
        reescrever(equipamento.get("fotos"))
        for secao in equipamento.get("checklist") or []:
            for pergunta in (secao or {}).get("perguntas") or []:
                reescrever((pergunta or {}).get("fotos"))


#: Autorização de tarefa guardada por instantes — (usuário, ordem, tarefa) -> (quando, dados).
#:
#: Abrir uma ficha de vinte inversores pede SESSENTA E UMA miniaturas, quase ao mesmo tempo. Sem
#: isto, cada uma refazia a cadeia inteira de autorização: as usinas do usuário, a ordem e a
#: tarefa no meuPlano — três idas ao upstream POR IMAGEM. O resultado no aparelho era o ícone
#: preto de imagem que não carrega, porque o servidor não vencia a fila.
#:
#: Trinta segundos é o suficiente para uma tela abrir e curto o bastante para um acesso
#: revogado não sobreviver a ele. E é só um ATALHO de leitura: quem não passou pela cadeia
#: completa uma vez não entra no dicionário.
_AUTORIZACAO_TTL_S = 120.0
_autorizacoes: dict[tuple[int, int, int], tuple[float, tuple[Any, dict[str, Any], PlantLink]]] = {}
#: Cadeias EM VOO, por chave: seis miniaturas que chegam juntas com o cache frio esperam a
#: MESMA autorização, em vez de disparar seis cadeias — foi exatamente o que esgotou o pool de
#: conexões do meuPlano em 04/09/2026 (cinco `GET /tasks/6804` no mesmo segundo, 30 s de fila,
#: 500 em todos).
_em_voo: dict[tuple[int, int, int], "asyncio.Future[tuple[Any, dict[str, Any], PlantLink]]"] = {}


async def _tarefa_autorizada_em_cache(
    db: Session, usuario: User, so_id: int, task_id: int
) -> tuple[Any, dict[str, Any], PlantLink]:
    """`_tarefa_autorizada`, sem repetir a cadeia a cada imagem da mesma ficha.

    Dois minutos: o tempo de abrir a ficha, rolar e tocar em "ver todas" — e curto o bastante
    para um acesso revogado não sobreviver. É só um ATALHO de leitura: quem não passou pela
    cadeia completa uma vez não entra no dicionário.
    """
    agora = time.monotonic()
    chave = (usuario.id, so_id, task_id)

    guardada = _autorizacoes.get(chave)
    if guardada is not None and agora - guardada[0] < _AUTORIZACAO_TTL_S:
        return guardada[1]

    voando = _em_voo.get(chave)
    if voando is not None:
        return await voando

    fut: "asyncio.Future[tuple[Any, dict[str, Any], PlantLink]]" = asyncio.get_running_loop().create_future()
    _em_voo[chave] = fut
    try:
        dados = await _tarefa_autorizada(db, usuario, so_id, task_id)
    except BaseException as exc:
        fut.set_exception(exc)
        raise
    else:
        fut.set_result(dados)
    finally:
        _em_voo.pop(chave, None)

    _autorizacoes[chave] = (agora, dados)
    # Poda o que venceu: sem isto o dicionário cresce com cada tarefa já vista, para sempre.
    if len(_autorizacoes) > 256:
        for k, (quando, _) in list(_autorizacoes.items()):
            if agora - quando >= _AUTORIZACAO_TTL_S:
                _autorizacoes.pop(k, None)
    return dados


@router.get("/manutencao/ordens/{so_id}/tarefas/{task_id}/fotos/{foto_id}")
async def foto_da_tarefa(
    so_id: int,
    task_id: int,
    foto_id: int,
    variante: str = "original",
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """UMA foto da ficha — a evidência que o técnico anexou.

    O dono (04/09/2026): *"as tarefas não aparece foto em nenhuma"*. Passa pelo MESMO portão da
    ficha e do PDF (`_tarefa_autorizada`): a tarefa tem de ser daquela ordem, e a ordem, de uma
    usina do usuário. O meuPlano ainda confere que a foto é daquela tarefa — duas cercas, porque
    o id vem do cliente e sozinho não prova nada.
    """
    cliente, _tarefa, _link = await _tarefa_autorizada_em_cache(db, usuario, so_id, task_id)
    try:
        conteudo, tipo = await cliente.foto_da_tarefa(task_id, foto_id, variante)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para carregar esta foto") from exc
    return Response(content=conteudo, media_type=tipo, headers={
        # A foto de uma ficha executada não muda. Sem cache, rolar a lista de evidências
        # rebaixaria a mesma imagem a cada volta — e quem está em campo paga por isso.
        "Cache-Control": "private, max-age=3600",
    })


@router.get("/manutencao/ordens/{so_id}/tarefas/{task_id}/pdf")
async def pdf_da_tarefa(
    so_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """O PDF de UMA tarefa: a ficha respondida pelo técnico, com medições e fotos.

    O PDF da OS traz tudo junto e pode ter dezenas de páginas; quem quer conferir um ensaio
    específico precisa do documento dele. O upstream só regera quando algo mudou.
    """
    cliente, tarefa, link = await _tarefa_autorizada(db, usuario, so_id, task_id)
    try:
        conteudo = await cliente.pdf_da_tarefa(task_id)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para gerar o PDF desta tarefa") from exc
    if not conteudo:
        raise HTTPException(502, f"O {MANUTENCAO} devolveu um PDF vazio.")
    nome = (tarefa.get("name") or f"tarefa-{task_id}")[:60]
    return _pdf(conteudo, f"{nome} - {link.nome}.pdf")


@router.get("/manutencao/cronograma/tarefas", response_model=list[TarefaOut])
async def tarefas_da_celula(
    usina_id: int,
    plan_item_id: int,
    mes: str,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> list[TarefaOut]:
    """As tarefas por trás de UM X do cronograma — atividade × mês.

    O dono (04/09/2026): *"quero clicar nos X com tarefa feita e abrir as informações da
    tarefa"*. A célula sabia só a cor; agora ela abre o que aconteceu ali.

    O escopo é o da usina (mesma régua de `_link_do_escopo`): o `plan_item_id` vem do
    cliente e sozinho não prova nada — as tarefas devolvidas são conferidas contra a usina
    autorizada antes de sair daqui.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    if link.mp_usina_id is None:
        raise HTTPException(404, "Esta usina não tem manutenção contratada.")
    try:
        cliente = await integracoes.cliente_meuplano(db)
        brutas = await cliente.tarefas_do_item_no_mes(plan_item_id, mes)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para ler as tarefas deste mês") from exc
    # a tarefa tem de ser DESTA usina — o item do plano veio do cliente
    minhas = [t for t in brutas
              if isinstance(t, dict) and _inteiro(t.get("plant_id")) == link.mp_usina_id]
    return [_tarefa_out(t) for t in minhas]


# ── contratos ───────────────────────────────────────────────────────────────
#
# O cronograma existe sempre DENTRO de um contrato. Até aqui este BFF escolhia o contrato
# sozinho — `contratos()[0]`, o primeiro que o banco devolvesse — e, pior, lia a rota
# interna do meuPlano, que cria o rascunho v1 ao ser lida e devolve DRAFT. O portal do
# cliente precisa do contrário: a lista para ele escolher, e só a versão CONSOLIDADA.

#: Frase única para "consolidado não existe". A tela não pode dizer "nada foi feito":
#: sem consolidação não há o que cobrar — ainda.
NAO_PUBLICADO = "A equipe ainda não publicou o cronograma deste contrato."


def _bool(valor: Any) -> bool | None:
    return valor if isinstance(valor, bool) else None


def _contrato_out(c: dict[str, Any]) -> ContratoOut | None:
    ident = _inteiro(c.get("id"))
    if ident is None:
        return None
    return ContratoOut(
        id=ident,
        numero=_inteiro(c.get("numero")),
        titulo=_texto(c.get("title")) or _texto(c.get("titulo")),
        inicio=_data(c.get("start_date")),
        fim=_data(c.get("end_date")),
        vigente=_bool(c.get("vigente")),
        versao_cronograma=_inteiro(c.get("versao_consolidada")),
    )


def _contrato_padrao(contratos: list[ContratoOut]) -> ContratoOut | None:
    """Qual contrato mostrar quando o cliente não escolheu.

    A régua, em ordem: só entre os que TÊM cronograma consolidado (um sem isso não tem o
    que mostrar); o vigente antes do encerrado; o de início mais recente; e o id maior
    desempata. Sem nenhum consolidado, vale o primeiro pela mesma ordem sem o filtro —
    para a resposta carregar `contrato_id` e o aviso de não publicado apontar um contrato
    real, e não "a usina".
    """
    def chave(c: ContratoOut) -> tuple[int, date, int]:
        return (1 if c.vigente else 0, c.inicio or date.min, c.id)

    consolidados = [c for c in contratos if c.versao_cronograma is not None]
    fonte = consolidados or contratos
    return max(fonte, key=chave) if fonte else None


async def _contratos_da_usina(cliente: Any, link: PlantLink) -> list[ContratoOut]:
    brutos = await cliente.vc_contratos(link.mp_usina_id)
    saida = [_contrato_out(c) for c in brutos if isinstance(c, dict)]
    return [c for c in saida if c is not None]


async def _resolver_contrato(
    cliente: Any, link: PlantLink, contrato_id: int | None
) -> tuple[ContratoOut | None, str | None]:
    """`(contrato, aviso)`. Com `contrato_id`, confere que ele é DESTA usina antes de
    perguntar qualquer coisa ao meuPlano — o id chega do cliente, e o 404 do upstream para
    "contrato de outra usina" é o mesmo 404 de "sem consolidação": sem esta conferência os
    dois virariam a frase de não publicado, e trocar o id na URL passaria em silêncio."""
    contratos = await _contratos_da_usina(cliente, link)
    if contrato_id is not None:
        for c in contratos:
            if c.id == contrato_id:
                return c, None
        raise HTTPException(404, "Contrato não encontrado nesta usina.")
    if not contratos:
        return None, "Esta usina não tem contrato de manutenção cadastrado."
    return _contrato_padrao(contratos), None


@router.get("/manutencao/contratos", response_model=ContratosOut)
async def listar_contratos(
    usina_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ContratosOut:
    """Os contratos de O&M da usina, com a versão consolidada do cronograma de cada um —
    é o seletor de contrato do Cronograma e do Relatório."""
    link = _link_do_escopo(db, usuario, usina_id)
    saida = ContratosOut(usina=link.nome, usina_id=link.id)
    try:
        cliente = await integracoes.cliente_meuplano(db)
        saida.contratos = await _contratos_da_usina(cliente, link)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para ler os contratos desta usina") from exc
    if not saida.contratos:
        saida.aviso = "Esta usina não tem contrato de manutenção cadastrado."
    return saida


@router.get("/manutencao/cronograma/pdf")
async def pdf_do_cronograma(
    usina_id: int,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> Response:
    """O cronograma anual CONSOLIDADO em PDF, com a letra do estado em cada célula.

    `contrato_id` é opcional pelo mesmo motivo de `cronograma_da_usina`: o app em campo
    chama só com `usina_id`, e a regra do contrato padrão vale para os dois.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    try:
        cliente = await integracoes.cliente_meuplano(db)
        contrato, aviso = await _resolver_contrato(cliente, link, contrato_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para ler os contratos desta usina") from exc
    if contrato is None:
        raise HTTPException(404, aviso or NAO_PUBLICADO)
    try:
        conteudo = await cliente.vc_cronograma_pdf(link.mp_usina_id, contrato.id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Um PDF não tem como avisar por dentro: aqui o "não publicado" É a resposta.
            raise HTTPException(404, NAO_PUBLICADO) from exc
        raise _erro_do_upstream(exc, "Não deu para gerar o cronograma em PDF") from exc
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_upstream(exc, "Não deu para gerar o cronograma em PDF") from exc
    if not conteudo:
        raise HTTPException(502, f"O {MANUTENCAO} devolveu um PDF vazio.")
    return _pdf(conteudo, f"Cronograma - {link.nome}.pdf")


# ── cronograma ──────────────────────────────────────────────────────────────

#: `cell_status` do meuPlano. `verde` é executado; `verde_ressalva` é DISPENSADO — a
#: distinção é deliberada lá (apagá-la era o risco de produto) e é preservada aqui.
FEITO = {"verde"}
DISPENSADO = {"verde_ressalva"}
ATRASADO = {"vermelho"}


@router.get("/manutencao/cronograma", response_model=CronogramaOut)
async def cronograma_da_usina(
    usina_id: int,
    contrato_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> CronogramaOut:
    """O cronograma CONSOLIDADO do contrato, mês a mês.

    Repassa `cell_status` como vem do meuPlano. Aquela cor é conformidade calculada
    contra o histórico do ATIVO, não contra tarefas — recalcular aqui produziria uma
    segunda resposta para a mesma pergunta, e o dono veria números diferentes nos dois
    produtos sem saber em qual acreditar.

    `contrato_id` é OPCIONAL de propósito: o app em campo chama só com `usina_id` e não
    recebe OTA junto com o deploy — ausente, vale o contrato com versão consolidada mais
    recente (`_contrato_padrao`). Contrato só com rascunho responde 200 com a matriz
    vazia, `status` nulo e a frase de não publicado: a tela precisa distinguir "não há
    combinado ainda" de "combinado e nada feito", e um 404 aqui derrubaria a tela inteira
    do cliente por um estado que é normal no início de um contrato.
    """
    link = _link_do_escopo(db, usuario, usina_id)
    saida = CronogramaOut(usina=link.nome, usina_id=link.id)

    try:
        cliente = await integracoes.cliente_meuplano(db)
        contrato, aviso = await _resolver_contrato(cliente, link, contrato_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Não deu para buscar os contratos: {exc}"
        return saida
    if contrato is None:
        saida.aviso = aviso
        return saida
    saida.contrato_id = contrato.id
    saida.contrato = contrato.titulo or (
        f"Contrato {contrato.numero}" if contrato.numero is not None else None
    )

    try:
        dados = await cliente.vc_cronograma(link.mp_usina_id, contrato.id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # O contrato é desta usina (conferido acima); 404 aqui é só "sem consolidado".
            saida.aviso = NAO_PUBLICADO
            return saida
        motivo = _detalhe_da_resposta(exc.response) or str(exc)
        saida.aviso = f"Não deu para buscar o cronograma: {motivo}"
        return saida
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Não deu para buscar o cronograma: {exc}"
        return saida

    meses = [m for m in (dados.get("month_labels") or []) if isinstance(m, str)]
    saida.meses = meses
    saida.status = _texto(dados.get("status"))
    saida.versao = _inteiro(dados.get("version"))

    linhas: list[LinhaCronogramaOut] = []
    for r in dados.get("rows") or []:
        if not isinstance(r, dict):
            continue
        contagens = r.get("months") or {}
        estados = r.get("cell_status") or {}
        celulas: list[CelulaOut] = []
        for i, rotulo in enumerate(meses, start=1):
            chave = str(i)
            estado = _texto(estados.get(chave))
            celulas.append(
                CelulaOut(
                    mes=rotulo,
                    previsto=_inteiro(contagens.get(chave)) or 0,
                    estado=estado,
                    feito=estado in FEITO,
                    dispensado=estado in DISPENSADO,
                    atrasado=estado in ATRASADO,
                )
            )
        categoria, categoria_codigo = _categoria_da_linha(r)
        linhas.append(
            LinhaCronogramaOut(
                plan_item_id=_inteiro(r.get("plan_item_id")),
                nome=(
                    _texto(r.get("conjunto_nome"))
                    or _texto(r.get("name"))
                    or _texto(r.get("type_code"))
                    or "Atividade"
                ),
                categoria=categoria,
                categoria_codigo=categoria_codigo,
                periodicidade=_periodicidade(
                    _inteiro(r.get("periodicity_value")), _texto(r.get("periodicity_unit"))
                ),
                grupo=(
                    _texto(r.get("group_name"))
                    or _texto(r.get("agrupamento_nome"))
                    or "Outras atividades"
                ),
                previsto_ano=_inteiro(r.get("expected_per_year")) or 0,
                # Cumprido conta `verde` E `verde_ressalva`: o dispensado saiu da conta
                # do mês por decisão registrada, então cobrá-lo como pendência seria
                # errado. Quem precisa da diferença a tem por célula.
                feitos=sum(1 for c in celulas if c.feito or c.dispensado),
                meses=celulas,
            )
        )

    saida.linhas = linhas
    saida.previsto_ano = sum(l.previsto_ano for l in linhas)
    saida.feitos_ano = sum(l.feitos for l in linhas)
    # Chegar até aqui é a prova de que existe versão consolidada: o 404 do upstream já
    # teria devolvido lá em cima com a frase de não publicado.
    saida.pdf_disponivel = bool(linhas)

    if not linhas:
        saida.aviso = "O cronograma consolidado deste contrato não tem nenhuma atividade."
    elif (saida.status or "").strip().upper() == "DRAFT":
        # Não deveria acontecer — a rota de cliente do meuPlano só serve consolidado. Se um
        # dia servir, a tela avisa em vez de vender rascunho como contrato.
        saida.aviso = "Este cronograma ainda é um rascunho, não a versão consolidada."
    return saida
