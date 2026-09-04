"""As usinas do dono, do jeito que o aplicativo precisa.

Aqui a autorização é o assunto principal, não um detalhe: cada rota parte de
`gs_user_plant_access` — o que o gestor concedeu àquela pessoa no painel — e nunca de um
identificador que veio do cliente. Um `plant_id` do corpo da requisição é conferido contra
o escopo antes de virar uma chamada ao produto de origem; sem isso, trocar o número na URL
mostraria a usina de outro cliente.

A agregação também mora aqui, e não na tela: o aplicativo recebe número pronto e a cor já
decidida. É o que permite corrigir uma regra de negócio sem publicar versão nova na loja.

Uma ponte fora do ar **não derruba a resposta**. Cada usina traz o que deu para buscar e
diz o que faltou, porque metade dos dados com um aviso honesto é melhor do que uma tela de
erro — e muito melhor do que uma tela de zeros, que se lê como "não gerou nada".
"""

import asyncio
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import User, UserPlantAccess
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · usinas"])


# ── escopo ──────────────────────────────────────────────────────────────────


def usinas_do_usuario(db: Session, usuario: User) -> list[PlantLink]:
    """O que esta pessoa tem direito de ver. Ponto de partida de tudo neste módulo.

    `PlantLink.ativo` entra na condição: uma usina desligada no painel sai do aplicativo
    sem que ninguém precise mexer nas concessões de cada cliente.
    """
    return list(
        db.scalars(
            select(PlantLink)
            .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
            .where(UserPlantAccess.user_id == usuario.id, PlantLink.ativo)
            .order_by(PlantLink.nome)
        ).all()
    )


def _usina_no_escopo(db: Session, usuario: User, plant_link_id: int) -> PlantLink:
    """404 e não 403 para usina fora do escopo: responder "proibido" confirmaria que
    aquela usina existe, o que é uma informação que quem tentou não deveria ganhar."""
    alvo = next(
        (u for u in usinas_do_usuario(db, usuario) if u.id == plant_link_id), None
    )
    if alvo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")
    return alvo


# ── formato ─────────────────────────────────────────────────────────────────


class UsinaOut(BaseModel):
    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    capacidade_kwp: float | None = None

    #: Nulo = sem comunicação. A tela mostra travessão, nunca zero — "não sabemos" e
    #: "não gerou" são coisas diferentes, e zero se lê como a segunda.
    potencia_kw: float | None = None
    energia_hoje_kwh: float | None = None
    disponibilidade_pct: float | None = None
    #: Quanto da capacidade está sendo usada agora, 0–100. Nulo quando falta um dos dois.
    pct_capacidade: int | None = None

    #: A cor já decidida pelo servidor. Os nomes são exatamente as chaves de `tons` em
    #: `app/src/theme/tokens.ts` — a tela faz `tons[tom]`, então um nome que não existe
    #: lá não vira cor errada, vira `undefined`. Daí `semDados`, e não `sem-dados`.
    tom: str
    situacao: str

    #: Todos os inversores mudos. Vem do ESTADO deles, nunca da potência: o mw-api coage
    #: potência ausente para zero, então "sem leitura" e "não está gerando" chegariam com
    #: o mesmo número — e só o estado os separa.
    sem_comunicacao: bool = False
    #: Quantos estão mudos, mesmo que não sejam todos. Sem isto, uma usina com dois de
    #: três inversores calados parecia inteira.
    inversores_mudos: int | None = None
    #: Quantos pedem atenção sem estar parados — alarme do fabricante, código de falha
    #: ativo ou estado `alert`. Sem este campo a usina em alerta saía verde.
    inversores_alerta: int | None = None
    #: Quantos estão em falha. Vive AQUI, e não só no detalhe: sem este campo a aba Usinas
    #: e a tela inicial não tinham como saber que havia inversor parado — e `_atencao`,
    #: que só reage ao tom "parado", nunca acendia. Silêncio falso é pior que faixa falsa.
    inversores_parados: int | None = None
    #: `MonitoringSnapshot.in_solar_window` do mw-api. Fora dela, nada é defeito — e é o
    #: campo que o próprio upstream recomenda ao front, em vez de derivar de potência.
    fora_da_janela_solar: bool = False

    tem_meuwatt: bool
    tem_meuplano: bool
    #: O que não deu para buscar, em português, para a tela poder dizer por quê.
    aviso: str | None = None


class UsinasOut(BaseModel):
    usinas: list[UsinaOut]
    total_kwp: float
    potencia_agora_kw: float | None = None
    energia_hoje_kwh: float | None = None

    #: Quando o BFF respondeu. Serve para depuração, não para a tela.
    atualizado_em: datetime
    #: Quando o dado foi MEDIDO na usina — a leitura mais recente entre as que
    #: responderam. É este que vira o selo de horário; `atualizado_em` diria a hora da
    #: resposta, o que faz o selo do modo offline mentir exatamente onde ele existe para
    #: não mentir. Nulo quando nenhuma usina respondeu.
    medido_em: datetime | None = None
    aviso: str | None = None


def _tom(usina: UsinaOut) -> tuple[str, str]:
    """A cor da usina, pela mesma régua do meuWatt.

    A ordem é a de `plantStatusOf` (`mw-fe/src/pages/home/inicioData.ts`), que é a fonte da
    verdade declarada no CLAUDE.md:

        dormindo  ->  sem dados  ->  FALHA  ->  alerta  ->  gerando

    A versão anterior invertia isso: julgava desempenho e **nunca consultava falha**. O
    vermelho só saía de `disponibilidade < 50`, então uma usina com inversor em parada
    material aberta e disponibilidade de 95% saía verde "Gerando" — enquanto o meuWatt, no
    mesmo minuto, mostrava falha. Dos dois produtos, o do dono era o que mentia para menos.

    Pior ainda: a aba Notificações já dizia "Inversor parado", a partir dos alertas, e a
    aba Usinas mostrava o card verde. O aplicativo se desmentia sozinho.
    """
    # 1. Fora da janela solar nada é defeito — nem sequer se olha o resto.
    if usina.fora_da_janela_solar:
        return "semDados", "Fora da janela solar"

    # 2. Sem ninguém falando, não há o que afirmar.
    if usina.sem_comunicacao:
        return "semDados", "Sem comunicação"
    if usina.potencia_kw is None:
        return "semDados", "Sem dados de geração"

    # 3. FALHA. E **só** falha: um inversor parado é fato verificável.
    #
    #    Disponibilidade NÃO pinta vermelho, e a razão é concreta. O mw-api fabrica uma
    #    linha com rendimento zero para todo slot que ainda não reportou no dia
    #    (`build_daily_report`), e essas linhas entram no cálculo com peso — então
    #    `plant_availability_pct` vale **0.0 por construção** até o primeiro relatório
    #    chegar. Como `in_solar_window` já é verdadeiro trinta minutos após o nascer do
    #    sol, a tela inicial estampava "USINA X com problema · Disponibilidade baixa"
    #    sobre uma usina intacta, todo amanhecer.
    #
    #    A régua da fonte da verdade (`plantStatusOf`, mw-fe) nunca consulta
    #    disponibilidade: o vermelho sai de `down || status === 'fault'`, e nada mais. O
    #    critério era invenção deste lado.
    if usina.inversores_parados:
        n = usina.inversores_parados
        return "parado", f"{n} {'inversor parado' if n == 1 else 'inversores parados'}"

    # 4. Âmbar: algo a observar, com a usina de pé.
    if usina.inversores_alerta:
        n = usina.inversores_alerta
        return "alerta", f"{n} {'inversor em alerta' if n == 1 else 'inversores em alerta'}"
    if usina.inversores_mudos:
        n = usina.inversores_mudos
        return "alerta", f"{n} {'inversor sem comunicação' if n == 1 else 'inversores sem comunicação'}"
    # Disponibilidade NÃO decide cor, em nenhum tom. `plantStatusOf` (mw-fe), a fonte da
    # verdade declarada no CLAUDE.md, nunca a consulta — a cor sai de fato: parada,
    # alerta do fabricante, mudez. O critério nasceu deste lado e voltou uma vez depois de
    # eu mesmo escrever, quinze linhas acima, que era invenção.
    #
    # O número continua sendo publicado quando tem lastro, e a tela da usina o imprime com
    # o contexto ao lado. O que ele não faz é acender faixa na tela inicial.

    # 5. Sem sol declarado e sem geração: começo de manhã ou dia muito fechado.
    if usina.potencia_kw <= 0:
        return "semDados", "Sem geração agora"

    return "ok", "Gerando"


def _numero(valor: Any) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


#: Estados de inversor no `MonitoringSnapshot` do mw-api
#: (`src/monitoring/schemas.py`, campo `InverterMonitoring.status`). A lista é fechada, e
#: ler dela — em vez de adivinhar nomes plausíveis — é o que evita contar parada errada.
PARADO = {"fault"}
#: Mudo NÃO é parado. O mw-fe o classifica em âmbar, não vermelho, e `equipamentos.py` o
#: trata como `semDados` — três lugares davam três respostas para o mesmo inversor, e a
#: faixa "1 inversor parado" levava a uma tela que contava zero.
MUDO = "communication_error"
#: `bedtime` é noite, não defeito: contar como parada acenderia alarme todo fim de tarde.
DORMINDO = "bedtime"


def _energia_de_hoje(agora: dict[str, Any]) -> float | None:
    """A geração do dia, somada dos inversores — ao vivo.

    O caminho anterior lia `DailyGenerationReport.total_generation_kwh`, e esse número
    agrega **só** `plant_inverter_daily_reports`, tabela populada pelo push de relatório
    DIÁRIO do mw-core. Enquanto o push do dia não chega, o campo é `0.0` por construção — e
    o aplicativo afirmava "hoje 0,0 kWh" com a usina gerando 8 kW no cartão de cima.

    O próprio meuWatt não usa aquela fonte para o dia corrente: `portfolio/service.py`
    soma `daily_generation_kwh` dos snapshots ao vivo e reserva os relatórios diários para
    "ontem". Aqui se faz o mesmo, com o campo que já vem na resposta de monitoramento.

    `daily_generation` é `None` quando vale zero (o schema diz isso), então ausência conta
    como zero. Nulo mesmo só quando não há inversor comunicando — e aí é "não sabemos".
    """
    falando = [i for i in _contam(agora) if not _esta_mudo(i)]
    if not falando:
        return None
    return round(sum(_numero(i.get("daily_generation")) or 0 for i in falando), 2)


def _disponibilidade_com_base(diario: Any) -> float | None:
    """A disponibilidade do dia, ou nulo quando o número não tem lastro.

    O mw-api produz DOIS valores sem base, e nenhum deles é erro dele — são consequências
    de um denominador vazio, lidas fora de contexto:

    - **0.0 ao amanhecer.** `build_daily_report` sintetiza uma linha por slot que ainda não
      reportou hoje, com `daily_yield_kwh = 0.0` e `expected_yield_kwh` ausente. No cálculo
      isso cai em `avail = 100.0 if measured > 0 else 0.0` → **zero**, com o peso cheio da
      capacidade. Até o primeiro envio do dia, toda usina saudável pontua zero.
    - **100.0 sem ninguém medindo.** Linhas com `is_communicating: False` são puladas do
      denominador; se forem todas, `avail_weight_total` fica zero e o campo sai `100.0`.

    A condição de lastro é a mesma que o upstream usa para somar: existir ao menos um
    inversor **comunicando** e com **expectativa** de geração. Sem isso, nulo — e a tela
    simplesmente não desenha a linha, em vez de imprimir 0% ou 100% como fato.

    A guarda anterior olhava se a lista estava vazia. Ao amanhecer ela não está: está
    cheia de linhas sintetizadas. Foi por isso que a correção anterior não corrigiu.
    """
    if not isinstance(diario, dict):
        return None

    inversores = diario.get("inverters")
    if not isinstance(inversores, list) or not inversores:
        return None

    # TODA linha que entra na média precisa ter lastro, não apenas uma. O upstream soma a
    # média ponderada sobre todas as linhas comunicando — e a linha sintetizada de um slot
    # que ainda não enviou o relatório sai com `expected_yield_kwh: None` e `measured: 0`,
    # o que vira `avail = 0` com PESO CHEIO de capacidade.
    #
    # Reproduzido pela auditoria: usina de 4 × 600 kWp com os quatro gerando 90 kW — 360 kW
    # reais — publicava disponibilidade de 49%, porque dois slots ainda não tinham enviado.
    # A guarda anterior exigia que UMA linha tivesse lastro: granularidade diferente da do
    # número que ela protegia. Este é o caso misto, que é justamente o caso do amanhecer.
    entram_na_media = [
        i
        for i in inversores
        if isinstance(i, dict) and i.get("is_communicating") is not False
    ]
    if not entram_na_media:
        return None
    if any((_numero(i.get("expected_yield_kwh")) or 0) <= 0 for i in entram_na_media):
        return None

    return _numero(diario.get("plant_availability_pct"))


def _numero_inteiro(total: Any, lista: Any) -> int | None:
    """O `total` do envelope, com a lista como segunda opinião."""
    if isinstance(total, int):
        return total
    return len(lista) if isinstance(lista, list) else None


def _contam(agora: dict[str, Any]) -> list[dict[str, Any]]:
    """Os inversores que entram nas somas.

    Silenciado pelo operador (`ignored`) fica de fora — é a mesma regra do meuWatt
    (`mw-fe/src/pages/home/inicioData.ts`, que soma `i.ignored ? 0 : i.active_power`).
    Divergir disso faz a mesma usina mostrar potência diferente nos dois produtos, e o
    dono não tem como saber qual acreditar.
    """
    inversores = agora.get("inverters")
    if not isinstance(inversores, list):
        return []
    return [i for i in inversores if isinstance(i, dict) and not i.get("ignored")]


def _instante_medida(valor: Any) -> datetime | None:
    """A data do upstream chega como texto ISO, não como `datetime`."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    if not valor:
        return None
    try:
        d = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _em_alerta(inv: dict[str, Any]) -> bool:
    """Se este inversor pede atenção, sem estar parado.

    São **três** sinais, e o mw-fe considera os três
    (`inicioData.ts`: `i.status === 'alert' || i.status === 'communication_error' ||
    i.alert_text || i.fault`). Ler só o `status` deixava passar o caso mais perigoso: o
    inversor com código de falha decodificado (`fault`) ou texto de alarme do fabricante
    (`alert_text`) cujo registrador de estado ainda diz `normal` — que saía **verde** aqui
    e âmbar no meuWatt, no mesmo minuto.
    """
    if str(inv.get("status") or "").strip().lower() == "alert":
        return True
    return bool(inv.get("alert_text") or inv.get("fault"))


def _esta_mudo(inv: dict[str, Any]) -> bool:
    return str(inv.get("status") or "").strip().lower() == "communication_error"


def _sem_comunicacao(agora: dict[str, Any]) -> bool:
    """Todos os inversores que contam estão mudos.

    Não dá para inferir isso da potência: o mw-api entrega `active_power = 0` para quem
    não tem leitura, então o número é o mesmo de uma usina dormindo. O estado é o único
    lugar onde a diferença sobrevive.
    """
    considerados = _contam(agora)
    if not considerados:
        return False
    return all(
        str(i.get("status") or "").strip().lower() == "communication_error"
        for i in considerados
    )


def _capacidade_declarada(diario: Any) -> float | None:
    """A capacidade instalada da usina, como o meuWatt a declara.

    `DailyGenerationReport.total_capacity_kwp` é o valor autoritativo, e vem na MESMA
    resposta que já se lê para a energia do dia — não custa uma chamada a mais.

    A versão anterior somava `capacity_kwp` dos inversores que estavam falando, e isso
    **fabricava** o número: a capacidade da usina encolhia quando um inversor emudecia.
    Rodando o código, uma usina de 3 × 600 kWp com um inversor mudo publicava 1200 kWp; com
    todos mudos, "capacidade não informada". Capacidade instalada é característica física
    da usina — não muda com o estado do Modbus. E ela é a manchete de quatro superfícies:
    o MWp da usina, o "de N kWp" do card, o total do topo da aba e a capacidade do início.
    """
    if not isinstance(diario, dict):
        return None
    return _numero(diario.get("total_capacity_kwp")) or None


def _capacidade_dos_inversores(agora: dict[str, Any]) -> float | None:
    """Capacidade instalada somada dos inversores, quando o vínculo não a tem.

    `PlantLink.kwp` só é preenchido à mão no painel, e está NULO em todas as usinas —
    então `pct_capacidade` nunca era calculado, a barra ficava vazia e o topo da aba
    Usinas anunciava "0,0 MWp". O número existe do outro lado o tempo todo:
    `InverterMonitoring.capacity_kwp`.

    O valor do vínculo continua tendo precedência: se o gestor digitou a capacidade de
    projeto, é ela que vale — a soma dos inversores é o que sobra quando ninguém digitou.
    """
    # Mudo fica de fora TAMBÉM aqui. O numerador (`_potencia_da_usina`) já o exclui; se o
    # denominador o mantivesse, uma usina com dois de três inversores calados mostraria a
    # potência de um sobre a capacidade de três, rotulada "% da capacidade instalada" —
    # uma porcentagem sistematicamente subestimada, sem aviso nenhum.
    considerados = [i for i in _contam(agora) if not _esta_mudo(i)]
    if not considerados:
        return None
    total = sum(_numero(i.get("capacity_kwp")) or 0 for i in considerados)
    return round(total, 2) or None


def _potencia_da_usina(agora: dict[str, Any]) -> float | None:
    """Potência instantânea da usina, em kW, somada dos inversores que contam.

    O `monitoring/current` **não traz um total da usina** — traz `inverters[]`, cada um
    com `active_power` em **watts**. Somar e dividir por mil é o que produz o número da
    tela, e é a mesma conta do meuWatt.

    Nulo só quando não há inversor a considerar. Zero aqui é um zero honesto: significa que
    os inversores reportaram e não estão gerando. Quem separa "não gerou" de "não falou" é
    `_sem_comunicacao`, pelo estado — não por este número.

    **Inversor mudo não soma.** Quando o snapshot fica velho (mais de dez minutos, ver
    `STALE_SNAPSHOT_THRESHOLD` no mw-api), o upstream marca `communication_error` mas
    **mantém o `active_power` da última leitura**. Somá-lo publicaria a potência de horas
    atrás sob o título "AGORA" — um número verdadeiro de outro momento, que é pior do que
    um número inventado: nada na tela dá motivo para desconfiar dele.
    """
    considerados = [i for i in _contam(agora) if not _esta_mudo(i)]
    if not considerados:
        return None

    watts = sum(_numero(i.get("active_power")) or 0 for i in considerados)
    return round(watts / 1000, 2)


async def _dados_meuwatt(cliente, link: PlantLink, dia: date) -> dict[str, Any]:
    """Tempo real + dia da usina, com cada metade falhando por conta própria.

    O monitoramento e a geração diária são duas chamadas porque são duas rotas no
    upstream; uma pode responder e a outra não, e perder as duas por causa de uma seria
    desperdiçar dado que já chegou.
    """
    saida: dict[str, Any] = {}
    erros: list[str] = []

    try:
        agora = await cliente.monitoramento_atual(link.mw_plant_slug)
        saida["potencia_kw"] = _potencia_da_usina(agora)
        saida["sem_comunicacao"] = _sem_comunicacao(agora)
        # Quando o dado foi MEDIDO — e a fonte é o inversor, não o envelope.
        #
        # `MonitoringSnapshot.timestamp` parece ser isso e não é: o mw-api o monta com
        # `datetime.now(UTC)` (`monitoring/service.py`) e ainda o congela por cache na
        # rota. É a hora da REQUISIÇÃO. Publicá-lo como hora da medição fazia o selo do
        # modo offline mentir exatamente onde ele existe para não mentir — e o docstring
        # daqui afirmava o contrário do que o código fazia.
        #
        # `InverterMonitoring.timestamp` é a leitura de verdade. A mais recente entre os
        # inversores é o instante mais novo que se pode afirmar sobre a usina.
        leituras = [
            m
            for m in (_instante_medida(i.get("timestamp")) for i in _contam(agora))
            if m is not None
        ]
        saida["medido_em"] = max(leituras) if leituras else None
        # `in_solar_window` é o campo que o próprio mw-api recomenda ao front para saber
        # se é hora de haver geração — melhor do que derivar de potência zero, que também
        # acontece em parada diurna.
        saida["fora_da_janela_solar"] = agora.get("in_solar_window") is False

        # A contagem de inversores sai da MESMA resposta: são as posições que estão
        # reportando agora. Buscá-la em `/slots` daria o cadastro — quantos deveriam
        # existir —, que é outra pergunta e não diz quantos estão de pé.
        #
        # Silenciado não entra em nenhuma das duas contagens, pela mesma razão de sempre:
        # a tela de Equipamentos também o exclui, e as duas telas têm de concordar.
        considerados = _contam(agora)
        if considerados:
            saida["inversores"] = len(considerados)
            saida["inversores_parados"] = _parados(considerados)
            saida["inversores_mudos"] = sum(1 for i in considerados if _esta_mudo(i))
            saida["inversores_alerta"] = sum(
                1 for i in considerados if _em_alerta(i) and not _em_falha(i) and not _esta_mudo(i)
            )
        # Guardado para o caso de o relatório diário não responder; o valor declarado
        # tem precedência e é preenchido logo abaixo.
        saida["capacidade_dos_inversores"] = _capacidade_dos_inversores(agora)
        saida["energia_hoje_kwh"] = _energia_de_hoje(agora)
    except Exception as exc:  # noqa: BLE001 — a tela precisa abrir mesmo assim
        erros.append(f"tempo real indisponível ({type(exc).__name__})")

    try:
        diario = await cliente.geracao_diaria(link.mw_plant_slug, dia)
        # `or` mataria o zero: `total_generation_kwh` é obrigatório no schema, e uma usina
        # que de fato gerou 0 kWh viraria "não sabemos". Aqui zero é informação.
        # A energia do dia NÃO vem daqui — ver `_energia_de_hoje`. O relatório diário só
        # agrega o push do mw-core, e enquanto ele não chega o total é zero por
        # construção.
        # O mw-api calcula `avail = soma_ponderada / peso if peso > 0 else 100.0`. Com
        # TODO inversor sem comunicar, o laço não acumula peso e o campo sai **100.0
        # fabricado** — a usina muda apareceria como "disponibilidade 100%" ao lado de
        # "energia hoje 0 kWh". O número não é do upstream mentindo: é o denominador
        # vazio. Aqui ele vira nulo, que é o que de fato se sabe.
        saida["disponibilidade_pct"] = (
            None if saida.get("sem_comunicacao") else _disponibilidade_com_base(diario)
        )
        saida["capacidade_kwp"] = _capacidade_declarada(diario)
    except Exception as exc:  # noqa: BLE001
        erros.append(f"geração do dia indisponível ({type(exc).__name__})")

    if erros:
        saida["aviso"] = " · ".join(erros)
    return saida


@router.get("/plants", response_model=UsinasOut)
async def listar_usinas(
    db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)
) -> UsinasOut:
    """As usinas desta pessoa, com o número de agora e o do dia.

    As usinas são consultadas em paralelo: em série, seis usinas a ~700 ms por chamada
    dariam uma tela que leva quase dez segundos para abrir numa rede de usina.
    """
    links = usinas_do_usuario(db, usuario)
    if not links:
        return UsinasOut(
            usinas=[], total_kwp=0, atualizado_em=datetime.now(UTC),
            aviso="Nenhuma usina foi concedida a esta conta ainda.",
        )

    aviso_geral: str | None = None
    dados_por_usina: dict[int, dict[str, Any]] = {}

    com_mw = [l for l in links if l.mw_plant_slug]
    if com_mw:
        try:
            cliente = await integracoes.cliente_meuwatt(db)
            resultados = await asyncio.gather(
                *(_dados_meuwatt(cliente, l, hoje_na_usina()) for l in com_mw),
                return_exceptions=True,
            )
            for link, r in zip(com_mw, resultados, strict=True):
                dados_por_usina[link.id] = r if isinstance(r, dict) else {}
        except Exception as exc:  # noqa: BLE001 — ponte fora não derruba a lista
            aviso_geral = f"Dados de geração indisponíveis: {exc}"

    saida: list[UsinaOut] = []
    for link in links:
        d = dados_por_usina.get(link.id, {})
        u = UsinaOut(
            id=link.id,
            nome=link.nome,
            cidade=link.cidade,
            uf=link.uf,
            # O cadastro do painel tem precedência; a soma dos inversores é o que vale
            # quando ninguém digitou a capacidade — que é o caso de todas as usinas hoje.
            # Só a capacidade DECLARADA (do meuWatt) ou a CADASTRADA (pelo gestor). A
            # soma dos inversores que estão falando saiu daqui: ela encolhe quando um
            # aparelho emudece, e `_capacidade_declarada` chama isso de fabricar o número
            # — não pode ser fabricação só porque o relatório diário falhou. Sem nenhuma
            # das duas, "capacidade não informada", que é a verdade.
            capacidade_kwp=d.get("capacidade_kwp") or link.kwp,
            potencia_kw=d.get("potencia_kw"),
            energia_hoje_kwh=d.get("energia_hoje_kwh"),
            disponibilidade_pct=d.get("disponibilidade_pct"),
            tom="semDados",
            situacao="",
            sem_comunicacao=bool(d.get("sem_comunicacao")),
            inversores_mudos=d.get("inversores_mudos"),
            inversores_parados=d.get("inversores_parados"),
            inversores_alerta=d.get("inversores_alerta"),
            fora_da_janela_solar=bool(d.get("fora_da_janela_solar")),
            tem_meuwatt=link.tem_meuwatt,
            tem_meuplano=link.tem_meuplano,
            aviso=d.get("aviso"),
        )
        # O denominador é SEMPRE a capacidade que a tela imprime ao lado. Chegou a haver
        # três bases diferentes sob o mesmo rótulo "% da capacidade instalada" — a lista
        # usava uma, o detalhe outra, o início uma terceira —, e a barra não correspondia
        # ao número impresso a dois centímetros dela.
        #
        # Quando há inversor mudo, o percentual sai de fato menor: a potência não inclui
        # esses aparelhos. Isso é correto e é dito na tela pela faixa "N inversores sem
        # comunicação" — melhor um número honestamente menor com a explicação ao lado do
        # que dois números que não fecham.
        if u.potencia_kw is not None and u.capacidade_kwp:
            u.pct_capacidade = max(0, min(100, round(u.potencia_kw / u.capacidade_kwp * 100)))
        u.tom, u.situacao = _tom(u)
        saida.append(u)

    medidos = [
        m
        for m in (_instante_medida(d.get("medido_em")) for d in dados_por_usina.values())
        if m is not None
    ]
    medidas = [u.potencia_kw for u in saida if u.potencia_kw is not None]
    energias = [u.energia_hoje_kwh for u in saida if u.energia_hoje_kwh is not None]

    return UsinasOut(
        usinas=saida,
        total_kwp=round(sum(u.capacidade_kwp or 0 for u in saida), 2),
        potencia_agora_kw=round(sum(medidas), 2) if medidas else None,
        energia_hoje_kwh=round(sum(energias), 2) if energias else None,
        atualizado_em=datetime.now(UTC),
        medido_em=max(medidos) if medidos else None,
        aviso=aviso_geral,
    )


class UsinaDetalheOut(UsinaOut):
    #: Ordens de serviço abertas, do meuPlano. Nulo = não foi possível consultar, que é
    #: diferente de zero.
    ordens_abertas: int | None = None
    ordens_recentes: list[str] = []

    #: Inversores, do meuWatt. Nulo é "não consultamos", zero seria "usina sem inversor" —
    #: que não existe, e é por isso que os dois não podem ser o mesmo valor.
    inversores: int | None = None
    inversores_parados: int | None = None
    alertas_ativos: int | None = None


def _em_falha(inv: dict[str, Any]) -> bool:
    """Se este inversor está em falha, pela régua do produto de origem.

    `down` é o **estado canônico**: o schema do mw-api diz, no comentário do campo, que é
    o flag que o front deve consumir para o vermelho "em falha" em vez de re-derivar da
    potência ao vivo. O mw-fe faz `i.down || i.status === 'fault'` em seis lugares.

    Ignorá-lo, como era feito aqui, deixava passar o pior caso: inversor com parada
    material aberta e status Modbus ainda `normal` saía **verde "Gerando"** no aplicativo
    enquanto o meuWatt o mostrava em falha — a mesma usina, no mesmo minuto, com duas
    respostas.

    `down` é tri-estado de propósito: `None` significa que o detector não sabe (sinal
    velho ou ausente), e nesse caso vale a derivação legada pelo `status`.
    """
    estado = str(inv.get("status") or "").strip().lower()

    # De madrugada o detector pode manter aberta uma parada da tarde. `bedtime` vence,
    # aqui e em `equipamentos._situacao` — e é a MESMA exceção nos dois, senão a tela da
    # usina desenha faixa vermelha "1 inversor parado" acima de um chip cinza "Fora da
    # janela solar", e o toque abre uma lista que conta zero.
    if estado == DORMINDO:
        return False

    if inv.get("down") is True:
        return True
    return estado in PARADO


def _parados(inversores: list[dict[str, Any]]) -> int:
    """Quantos inversores estão em falha agora.

    `bedtime` é a usina dormindo — contá-lo encheria a tela de vermelho todo fim de tarde
    —, `alert` é aviso com o inversor gerando, e `communication_error` é mudo, não parado.
    """
    return sum(1 for i in inversores if _em_falha(i))


@router.get("/plants/{plant_link_id}", response_model=UsinaDetalheOut)
async def detalhe_usina(
    plant_link_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> UsinaDetalheOut:
    link = _usina_no_escopo(db, usuario, plant_link_id)

    dados: dict[str, Any] = {}
    equipamentos: dict[str, Any] = {}
    if link.mw_plant_slug:
        try:
            cliente = await integracoes.cliente_meuwatt(db)
            # Os inversores já vêm de `_dados_meuwatt`, do mesmo `monitoring/current`.
            # Só os alertas exigem uma rota a mais.
            dados, alertas = await asyncio.gather(
                _dados_meuwatt(cliente, link, hoje_na_usina()),
                cliente.alertas(link.mw_plant_slug),
                return_exceptions=True,
            )
            if not isinstance(dados, dict):
                dados = {"aviso": "Dados de geração indisponíveis."}

            # `/plants/{slug}/alerts` devolve um ENVELOPE, não uma lista:
            # `AlertListResponse{plant, total, alerts[]}` (mw-api, alerts/schemas.py).
            # Contar `len()` de um dict daria o número de chaves, e testar `isinstance(_,
            # list)` fazia o campo ficar nulo para sempre — a tela dizia "não consultamos"
            # com a resposta na mão.
            if isinstance(alertas, dict):
                equipamentos["alertas_ativos"] = _numero_inteiro(
                    alertas.get("total"), alertas.get("alerts")
                )
            elif isinstance(alertas, list):
                equipamentos["alertas_ativos"] = len(alertas)
        except Exception as exc:  # noqa: BLE001
            dados = {"aviso": f"Monitoramento indisponível: {exc}"}

    detalhe = UsinaDetalheOut(
        id=link.id,
        nome=link.nome,
        cidade=link.cidade,
        uf=link.uf,
        capacidade_kwp=dados.get("capacidade_kwp") or link.kwp,
        potencia_kw=dados.get("potencia_kw"),
        energia_hoje_kwh=dados.get("energia_hoje_kwh"),
        disponibilidade_pct=dados.get("disponibilidade_pct"),
        tom="semDados",
        situacao="",
        sem_comunicacao=bool(dados.get("sem_comunicacao")),
        inversores_mudos=dados.get("inversores_mudos"),
        fora_da_janela_solar=bool(dados.get("fora_da_janela_solar")),
        tem_meuwatt=link.tem_meuwatt,
        tem_meuplano=link.tem_meuplano,
        aviso=dados.get("aviso"),
        inversores=dados.get("inversores"),
        inversores_parados=dados.get("inversores_parados"),
        inversores_alerta=dados.get("inversores_alerta"),
        alertas_ativos=equipamentos.get("alertas_ativos"),
    )
    if detalhe.potencia_kw is not None and detalhe.capacidade_kwp:
        detalhe.pct_capacidade = max(
            0, min(100, round(detalhe.potencia_kw / detalhe.capacidade_kwp * 100))
        )
    detalhe.tom, detalhe.situacao = _tom(detalhe)

    if link.mp_usina_id:
        try:
            mp = await integracoes.cliente_meuplano(db)
            ordens = await mp.ordens_servico(link.mp_usina_id)

            # `len(ordens)` contava CANCELADA e CONCLUÍDA como "em aberto" — a mesma
            # usina dizia "8 em aberto" aqui e listava 1 em Notificações, que filtra
            # certo. Duas telas discordando sobre o mesmo fato é pior do que o número
            # errado: destrói a confiança nas duas.
            #
            # O filtro é importado de `notifications`, e não copiado, justamente para não
            # tornar a divergência possível de novo.
            from app.api.v1.notifications import _esta_aberta

            abertas = [o for o in ordens if _esta_aberta(o)]
            detalhe.ordens_abertas = len(abertas)
            detalhe.ordens_recentes = [
                str(o.get("objetivo") or f"OS {o.get('id')}") for o in abertas[:3]
            ]
        except Exception as exc:  # noqa: BLE001
            juntos = [detalhe.aviso, f"manutenção indisponível ({type(exc).__name__})"]
            detalhe.aviso = " · ".join(x for x in juntos if x)

    return detalhe


# ── as pontes, vistas de dentro do aplicativo ───────────────────────────────


class PlataformaOut(BaseModel):
    produto: str
    nome: str
    #: O que esta plataforma traz para o dono da usina — não jargão de integração.
    fornece: str
    #: `ok` · `parado` · `semDados`, pelas chaves de `tons` — mesma régua da usina.
    tom: str
    situacao: str
    detalhe: str | None = None
    #: Quantas das SUAS usinas vêm desta plataforma. É o número que importa para quem
    #: abre o aplicativo — o total que a credencial enxerga é assunto do painel.
    minhas_usinas: int
    verificado_em: datetime | None = None


class ConexoesOut(BaseModel):
    plataformas: list[PlataformaOut]
    todas_ok: bool
    resumo: str


@router.get("/conexoes", response_model=ConexoesOut)
def minhas_conexoes(
    db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)
) -> ConexoesOut:
    """De onde vem cada coisa que o aplicativo mostra, e se está chegando.

    Responde à pergunta que o dono da usina faz quando uma tela aparece vazia: "está
    quebrado ou eu não contratei isso?". Sem esta tela, as duas situações são idênticas —
    uma aba vazia — e a diferença entre elas é justamente a que decide se ele deve ligar
    reclamando ou não.

    Mostra o estado da ponte e quantas das usinas DELE vêm de cada lado. Nada de token,
    endereço ou nome de quem o gerou: isso é assunto do painel, e é o gestor quem resolve.
    """
    links = usinas_do_usuario(db, usuario)
    estado = integracoes.listar(db)

    # A ponte é nomeada pelo SERVIÇO que presta, não pelo produto que a implementa: quem
    # entra aqui é o dono da usina, que não tem conta no meuWatt nem no meuPlano e não tem
    # a quem cobrar por eles. E "Monitoramento" responde melhor a pergunta desta tela
    # ("está quebrado ou eu não contratei isso?") do que um nome próprio que ele nunca viu.
    descricao = {
        Produto.MEUWATT: ("Monitoramento", "Geração, inversores e disponibilidade"),
        Produto.MEUPLANO: ("Manutenção", "Cronograma, ordens de serviço e pendências"),
    }

    plataformas: list[PlataformaOut] = []
    for produto, (nome, fornece) in descricao.items():
        integracao = estado.get(produto)
        minhas = sum(
            1
            for l in links
            if (l.mw_plant_slug if produto is Produto.MEUWATT else l.mp_usina_id)
        )

        if integracao is None or not integracao.ativa:
            tom, situacao, detalhe = "semDados", "Não conectado", None
        elif integracao.estado.value == "ok":
            tom, situacao, detalhe = "ok", "Conectado", None
        elif integracao.estado.value == "falhou":
            # A frase técnica do upstream fica no painel. Aqui vai o que o dono da usina
            # precisa saber: não é problema dele, e alguém já consegue ver.
            tom, situacao = "parado", "Com problema"
            detalhe = "A equipe já enxerga esta falha no painel de administração."
        else:
            tom, situacao, detalhe = "semDados", "Ainda não verificado", None

        if minhas == 0 and tom == "ok":
            situacao = "Conectado, sem usinas suas"
            detalhe = "Nenhuma das suas usinas usa esta plataforma."

        plataformas.append(
            PlataformaOut(
                produto=produto.value,
                nome=nome,
                fornece=fornece,
                tom=tom,
                situacao=situacao,
                detalhe=detalhe,
                minhas_usinas=minhas,
                verificado_em=integracao.testada_em if integracao else None,
            )
        )

    com_uso = [p for p in plataformas if p.minhas_usinas > 0]
    todas_ok = bool(com_uso) and all(p.tom == "ok" for p in com_uso)

    if not links:
        resumo = "Nenhuma usina foi liberada para esta conta ainda."
    elif todas_ok:
        resumo = f"Tudo certo. {len(links)} usina(s) recebendo dados."
    elif not com_uso:
        resumo = "Suas usinas ainda não estão ligadas a nenhuma plataforma."
    else:
        ruins = [p.nome for p in com_uso if p.tom != "ok"]
        resumo = f"Com problema: {', '.join(ruins)}. Os demais dados seguem atualizando."

    return ConexoesOut(plataformas=plataformas, todas_ok=todas_ok, resumo=resumo)


# ── geração por recorte (Dia / Mês / Ano) ───────────────────────────────────
#
# O app abre a usina e oferece três recortes. `Dia` já vinha de
# `/plants/{id}` (monitoring/current). `Mês` e `Ano` não tinham endpoint e a
# tela dizia "ainda não está disponível" — que é honesto, mas não é o produto.
#
# Os dois saem de UMA chamada a `generation/range` do meuWatt: o total vem de
# `total_generation_kwh` e a série de `chart_data.daily_generation`, que é
# `{serial: [{t, y}]}`. Somar os seriais por data dá a energia do DIA; agrupar
# essas datas por mês dá a energia do MÊS. Nada é estimado: data sem leitura
# simplesmente não vira ponto, e o app desenha a lacuna em vez de um zero.


class PontoGeracao(BaseModel):
    #: `YYYY-MM-DD` no recorte mês, `YYYY-MM` no recorte ano.
    chave: str
    #: Rótulo curto já pronto para o eixo ("07", "Jul").
    rotulo: str
    kwh: float


class GeracaoOut(BaseModel):
    recorte: str
    inicio: str
    fim: str
    #: `None` = o upstream não respondeu. Zero é medição; ausência não é.
    total_kwh: float | None = None
    pontos: list[PontoGeracao] = []
    aviso: str | None = None


_MESES_CURTOS = [
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]


def _somar_por_data(chart_data: Any) -> dict[str, float]:
    """`{serial: [{t, y}]}` → `{'YYYY-MM-DD': kwh}`, somando os seriais.

    A energia da usina no dia é a soma dos inversores naquele dia. Serial que
    não reportou não entra — não é zero, é ausência.
    """
    por_data: dict[str, float] = {}
    if not isinstance(chart_data, dict):
        return por_data
    series = chart_data.get("daily_generation")
    if not isinstance(series, dict):
        return por_data
    for pontos in series.values():
        if not isinstance(pontos, list):
            continue
        for p in pontos:
            if not isinstance(p, dict):
                continue
            t, y = p.get("t"), p.get("y")
            if not isinstance(t, str) or not isinstance(y, (int, float)):
                continue
            por_data[t[:10]] = por_data.get(t[:10], 0.0) + float(y)
    return por_data


def _janela(recorte: str, referencia: date) -> tuple[date, date]:
    if recorte == "ano":
        return date(referencia.year, 1, 1), date(referencia.year, 12, 31)
    primeiro = referencia.replace(day=1)
    if primeiro.month == 12:
        ultimo = date(primeiro.year, 12, 31)
    else:
        ultimo = date(primeiro.year, primeiro.month + 1, 1) - timedelta(days=1)
    return primeiro, ultimo


def _referencia_pedida(referencia: str | None) -> date:
    """Data de referência do recorte. Ausente = hoje na usina.

    Recusa data futura: o monitoramento não tem leitura do que não aconteceu, e
    devolver uma janela vazia disfarçaria o pedido impossível de "sem dados".
    """
    if not referencia:
        return hoje_na_usina()
    try:
        pedida = date.fromisoformat(referencia)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "referencia deve estar no formato YYYY-MM-DD."
        ) from None
    if pedida > hoje_na_usina():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "referencia não pode ser futura.")
    return pedida


@router.get("/plants/{plant_link_id}/geracao", response_model=GeracaoOut)
async def geracao_da_usina(
    plant_link_id: int,
    recorte: str = "mes",
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> GeracaoOut:
    """Energia do mês (um ponto por dia) ou do ano (um ponto por mês).

    `referencia` é qualquer dia dentro do período desejado — o mês e o ano saem
    dela. Assim o app manda a data que o usuário escolheu no calendário sem
    precisar saber onde o mês começa ou termina.
    """
    if recorte not in ("mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'mes' ou 'ano'.")

    link = _usina_no_escopo(db, usuario, plant_link_id)
    inicio, fim = _janela(recorte, _referencia_pedida(referencia))
    saida = GeracaoOut(recorte=recorte, inicio=inicio.isoformat(), fim=fim.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        relatorio = await cliente.geracao_periodo(link.mw_plant_slug, inicio, fim)
    except Exception as exc:  # noqa: BLE001
        # Sem inventar número: total fica `None` e o app mostra "sem dados".
        saida.aviso = f"Monitoramento indisponível: {exc}"
        return saida

    if not isinstance(relatorio, dict):
        saida.aviso = "Dados de geração indisponíveis."
        return saida

    total = relatorio.get("total_generation_kwh")
    saida.total_kwh = float(total) if isinstance(total, (int, float)) else None

    por_data = _somar_por_data(relatorio.get("chart_data"))
    if recorte == "mes":
        saida.pontos = [
            PontoGeracao(chave=d, rotulo=d[8:10], kwh=round(kwh, 2))
            for d, kwh in sorted(por_data.items())
        ]
    else:
        por_mes: dict[str, float] = {}
        for d, kwh in por_data.items():
            por_mes[d[:7]] = por_mes.get(d[:7], 0.0) + kwh
        saida.pontos = [
            PontoGeracao(
                chave=m, rotulo=_MESES_CURTOS[int(m[5:7]) - 1], kwh=round(kwh, 2)
            )
            for m, kwh in sorted(por_mes.items())
        ]

    if not saida.pontos and saida.total_kwh is None:
        saida.aviso = "O monitoramento não devolveu geração para este período."
    return saida


# ── Curva do dia: potência da usina e irradiação ─────────────────────────────
#
# `charts/intraday` do meuWatt devolve, a cada 5 minutos, a potência de cada
# inversor e a irradiação da estação. A potência da usina é a soma dos
# inversores no bucket — não há campo pronto para ela, e somar é exato porque
# cada inversor mede a própria saída.
#
# A irradiação exige cuidado: o upstream preenche `poa` com 0 quando a usina não
# tem estação, e zero é indistinguível de meia-noite. Desenhar essa curva daria
# uma linha rasteira com cara de medição. Por isso a presença da estação é
# decidida uma vez, olhando o dia inteiro, e devolvida em `tem_estacao`.


class PontoCurvaUsina(BaseModel):
    hora: str
    #: Soma da potência dos inversores que mediram neste bucket, em kW.
    kw: float
    #: Irradiação no plano dos módulos, W/m². `None` quando não há estação.
    poa: float | None = None


class CurvaUsinaOut(BaseModel):
    dia: str
    pontos: list[PontoCurvaUsina] = []
    #: Pico de potência do dia, em kW. `None` = nada medido.
    pico_kw: float | None = None
    #: Pico de irradiação do dia, W/m². `None` = sem estação.
    pico_poa: float | None = None
    #: `False` faz o app dizer "sem estação" em vez de desenhar curva rasteira.
    tem_estacao: bool = False
    aviso: str | None = None


def _cortar_janela_solar(curva: list[PontoCurvaUsina]) -> list[PontoCurvaUsina]:
    """Remove as PONTAS mortas do dia — antes do nascer e depois do pôr do sol.

    A curva bruta começa à meia-noite e termina à meia-noite, então quase metade do
    eixo é noite: horas de linha rasteira que espremem o dia útil no meio do gráfico e
    não respondem pergunta nenhuma. Nenhuma usina gera às 3 da manhã, e mostrar isso
    como "zero" convida a interpretar como parada.

    **Só as pontas.** Um zero no MEIO do dia é a informação mais importante que este
    gráfico carrega — é o inversor que caiu às 11h — e cortá-lo esconderia justamente
    o defeito. O corte anda de fora para dentro e para no primeiro ponto com leitura.

    Ponto com irradiação conta como leitura mesmo com potência zero: sol nascendo com
    a usina ainda parada é exatamente o caso que o dono precisa ver.
    """

    def vivo(p: PontoCurvaUsina) -> bool:
        return p.kw > 0 or (p.poa is not None and p.poa > 0)

    primeiro = next((i for i, p in enumerate(curva) if vivo(p)), None)
    if primeiro is None:
        # Dia inteiro sem geração nem sol: não há janela para recortar, e devolver
        # vazio faria a tela dizer "sem leitura" quando houve leitura — de zero.
        return curva
    ultimo = len(curva) - 1 - next(i for i, p in enumerate(reversed(curva)) if vivo(p))
    return curva[primeiro : ultimo + 1]


def _curva_da_usina(intraday: Any) -> tuple[list[PontoCurvaUsina], bool]:
    """`points[]` do intraday → curva somada da usina + se há estação.

    Bucket sem nenhum inversor medindo não vira ponto: é lacuna, não zero.
    """
    if not isinstance(intraday, dict):
        return [], False
    pontos_brutos = intraday.get("points")
    if not isinstance(pontos_brutos, list):
        return [], False

    # A estação é considerada presente se em ALGUM instante do dia ela publicou
    # irradiação acima de zero. Um dia inteiro em zero é ou usina sem sensor ou
    # sensor mudo — e nos dois casos não há curva honesta para desenhar.
    tem_estacao = False
    curva: list[PontoCurvaUsina] = []

    for p in pontos_brutos:
        if not isinstance(p, dict):
            continue
        hora = p.get("time")
        if not isinstance(hora, str):
            continue

        inversores = p.get("inverters")
        if not isinstance(inversores, list) or not inversores:
            continue

        soma = 0.0
        mediu = False
        for inv in inversores:
            if not isinstance(inv, dict):
                continue
            kw = inv.get("power_kw")
            if isinstance(kw, (int, float)):
                soma += float(kw)
                mediu = True
        if not mediu:
            continue

        poa = p.get("poa")
        poa_valor = float(poa) if isinstance(poa, (int, float)) else None
        if poa_valor is not None and poa_valor > 0:
            tem_estacao = True

        curva.append(PontoCurvaUsina(hora=hora, kw=round(soma, 2), poa=poa_valor))

    if not tem_estacao:
        # Sem estação, `poa` some da resposta inteira em vez de viajar como zero.
        for ponto in curva:
            ponto.poa = None

    return _cortar_janela_solar(curva), tem_estacao


@router.get("/plants/{plant_link_id}/curva", response_model=CurvaUsinaOut)
async def curva_do_dia(
    plant_link_id: int,
    dia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> CurvaUsinaOut:
    """Potência da usina ao longo do dia, com irradiação POA quando houver estação."""
    link = _usina_no_escopo(db, usuario, plant_link_id)
    referencia = _referencia_pedida(dia)
    saida = CurvaUsinaOut(dia=referencia.isoformat())

    if not link.mw_plant_slug:
        saida.aviso = "Esta usina não está ligada ao monitoramento."
        return saida

    try:
        cliente = await integracoes.cliente_meuwatt(db)
        intraday = await cliente.intraday(link.mw_plant_slug, referencia)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"Monitoramento indisponível: {exc}"
        return saida

    saida.pontos, saida.tem_estacao = _curva_da_usina(intraday)
    if saida.pontos:
        saida.pico_kw = max(p.kw for p in saida.pontos)
        if saida.tem_estacao:
            leituras = [p.poa for p in saida.pontos if p.poa is not None]
            saida.pico_poa = max(leituras) if leituras else None
    else:
        saida.aviso = "O monitoramento não devolveu leitura para este dia."
    return saida


# ── Desempenho: medido × esperado do PROJETO ─────────────────────────────────
#
# O portal do cliente responde "gerei o que era esperado?" — e a régua não pode
# ser inventada aqui. O "esperado" é a meta de projeto CADASTRADA no meuWatt
# (PVsyst): a tabela diária `pvsyst_previewed_energy` (`/plants/{slug}/pvsyst`)
# ou, quando ela não cobre o período, a mensal digitada na aba Projeto
# (`/plants/{slug}/pvsyst/manual/{ano}`), que é a fonte que o próprio relatório
# do mw-fe usa. Sem nenhuma das duas, o portal diz "sem meta cadastrada" — nunca
# um percentual sobre um número que ninguém cadastrou.
#
# O medido sai de `generation/range`, que também traz PR, disponibilidade real
# e contratual e a perda por parada do período — os mesmos números dos cards do
# meuWatt, para os dois produtos não discordarem sobre a mesma usina.
#
# Duas fabricações do upstream que NÃO chegam ao portal:
# - `total_generation_kwh` é `0.0` e `performance_ratio` é `0.0` por construção
#   quando o período não tem dado (`days_with_data == 0`, `pr_den == 0`). Aqui
#   viram nulo, e a tela diz "sem dados" em vez de "0 kWh · 0% do projeto".
# - Meta do MÊS CORRENTE só até hoje: somar a expectativa do mês inteiro contra
#   a energia de meio mês diria "abaixo do esperado" para toda usina, todo dia 15.


class MesDesempenho(BaseModel):
    #: `YYYY-MM`.
    mes: str
    #: Nulo = o mês não tem medição no monitoramento. Zero seria "mediu zero".
    energia_kwh: float | None = None
    #: Nulo = sem meta cadastrada para o mês.
    esperado_projeto_kwh: float | None = None
    disponibilidade_contratual_pct: float | None = None
    perdas_kwh: float | None = None


class DesempenhoOut(BaseModel):
    recorte: str
    inicio: str
    fim: str
    energia_kwh: float | None = None
    esperado_projeto_kwh: float | None = None
    #: `energia / esperado × 100`, uma casa. Nulo quando falta qualquer um dos dois.
    pct_do_projeto: float | None = None
    #: PR do período, em %, do próprio meuWatt. Nulo sem POA medida (o upstream
    #: devolve 0.0 nesse caso, e 0% de PR não é uma medição).
    pr_pct: float | None = None
    disponibilidade_real_pct: float | None = None
    disponibilidade_contratual_pct: float | None = None
    #: Energia perdida em paradas no período. Zero aqui é legítimo: houve dado e
    #: não houve perda. Nulo é "não houve dado".
    perdas_paradas_kwh: float | None = None
    #: Só no recorte `ano`: um item por mês do período, com o esperado ao lado.
    meses: list[MesDesempenho] = []
    #: Régua do projeto, já decidida — ver `_situacao_do_projeto`.
    tom: str
    situacao: str
    aviso: str | None = None


class MesHistorico(BaseModel):
    mes: str
    energia_kwh: float | None = None
    esperado_projeto_kwh: float | None = None
    #: A energia do MESMO mês do ano anterior. Nulo quando aquele mês não tem dado.
    ano_anterior_kwh: float | None = None
    perdas_kwh: float | None = None


class HistoricoOut(BaseModel):
    inicio: str
    fim: str
    meses: list[MesHistorico] = []
    aviso: str | None = None


def _chave_mes(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _deslocar_mes(chave: str, delta: int) -> str:
    """`'2026-03'`, −12 → `'2025-03'`. Aritmética de calendário, sem dia."""
    ano, mes = int(chave[:4]), int(chave[5:7])
    indice = ano * 12 + (mes - 1) + delta
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def _meses_entre(primeiro: str, ultimo: str) -> list[str]:
    saida: list[str] = []
    atual = primeiro
    while atual <= ultimo:
        saida.append(atual)
        atual = _deslocar_mes(atual, 1)
    return saida


def _primeiro_dia(chave: str) -> date:
    return date(int(chave[:4]), int(chave[5:7]), 1)


def _fatias_por_ano(inicio: date, fim: date) -> list[tuple[date, date]]:
    """Quebra o intervalo em pedaços de no máximo um ano civil.

    `generation/range` recusa mais de 366 dias. Cortar no 31/12 dá pedaços que
    nunca passam disso (ano bissexto tem exatamente 366) e mantém os meses
    inteiros dentro de uma fatia só — o `monthly_summaries` de cada resposta
    vem completo, sem um mês partido entre duas chamadas.
    """
    fatias: list[tuple[date, date]] = []
    atual = inicio
    while atual <= fim:
        fim_do_ano = date(atual.year, 12, 31)
        fatias.append((atual, min(fim_do_ano, fim)))
        atual = fim_do_ano + timedelta(days=1)
    return fatias


def _tem_dado(relatorio: Any) -> bool:
    """Se o `range` mediu alguma coisa. `days_with_data` é o campo que o próprio
    upstream usa para saber se os totais têm lastro."""
    if not isinstance(relatorio, dict):
        return False
    dias = relatorio.get("days_with_data")
    return isinstance(dias, (int, float)) and not isinstance(dias, bool) and dias > 0


def _energia_do_periodo(relatorio: Any) -> float | None:
    if not _tem_dado(relatorio):
        return None
    return _numero(relatorio.get("total_generation_kwh"))


def _pr_pct(relatorio: Any) -> float | None:
    """`performance_ratio` vem como razão 0–1 (o mw-fe multiplica por 100 em
    `MetersView`). Zero é o valor por construção quando não há POA — não é PR."""
    if not _tem_dado(relatorio):
        return None
    pr = _numero(relatorio.get("performance_ratio"))
    if pr is None or pr <= 0:
        return None
    return round(pr * 100, 1)


def _perdas_do_periodo(relatorio: Any) -> float | None:
    if not _tem_dado(relatorio):
        return None
    resumo = relatorio.get("summary")
    if not isinstance(resumo, dict):
        return None
    return _numero(resumo.get("total_lost_kwh"))


def _resumo_por_mes(relatorio: Any) -> dict[str, dict[str, Any]]:
    """`monthly_summaries[]` → `{'YYYY-MM': linha}`. Mês ausente é ausência."""
    saida: dict[str, dict[str, Any]] = {}
    if not isinstance(relatorio, dict):
        return saida
    linhas = relatorio.get("monthly_summaries")
    if not isinstance(linhas, list):
        return saida
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        mes = linha.get("month")
        if isinstance(mes, str) and len(mes) >= 7:
            saida[mes[:7]] = linha
    return saida


class _Meta:
    """A meta do projeto por mês, e como ela chegou."""

    def __init__(self) -> None:
        self.por_mes: dict[str, float] = {}
        #: A fonte falhou — diferente de "não há meta", que é `por_mes` vazio.
        self.indisponivel = False
        self.aviso: str | None = None

    def total(self, meses: list[str]) -> float | None:
        valores = [self.por_mes[m] for m in meses if m in self.por_mes]
        return round(sum(valores), 2) if valores else None


def _esperado_diario_por_mes(pvsyst: Any, inicio: date, fim: date) -> dict[str, float]:
    """`rows[].{date, e_grid}` somados por mês, só entre `inicio` e `fim`.

    O corte em `fim` é o que faz a meta do mês corrente parar em hoje: a linha
    de amanhã existe na tabela, mas a energia de amanhã ainda não foi medida.
    """
    por_mes: dict[str, float] = {}
    if not isinstance(pvsyst, dict):
        return por_mes
    linhas = pvsyst.get("rows")
    if not isinstance(linhas, list):
        return por_mes
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        dia_texto, kwh = linha.get("date"), _numero(linha.get("e_grid"))
        if not isinstance(dia_texto, str) or kwh is None:
            continue
        try:
            dia = date.fromisoformat(dia_texto[:10])
        except ValueError:
            continue
        if dia < inicio or dia > fim:
            continue
        chave = _chave_mes(dia)
        por_mes[chave] = por_mes.get(chave, 0.0) + kwh
    return por_mes


def _esperado_manual_por_mes(manual: Any, ano: int, fim: date) -> dict[str, float]:
    """`rows[].{month, e_grid}` do ano → `{'YYYY-MM': kwh}`, até o mês de `fim`.

    O mês em que `fim` cai é proporcional aos dias decorridos: a meta mensal é
    um número só, e compará-la inteira com meio mês medido diria "abaixo do
    esperado" sem que nada estivesse errado. Não é estimativa nova — é a mesma
    meta cadastrada, na fração do mês que já aconteceu.
    """
    por_mes: dict[str, float] = {}
    if not isinstance(manual, dict):
        return por_mes
    linhas = manual.get("rows")
    if not isinstance(linhas, list):
        return por_mes
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        mes, kwh = linha.get("month"), _numero(linha.get("e_grid"))
        if not isinstance(mes, int) or isinstance(mes, bool) or not 1 <= mes <= 12:
            continue
        if kwh is None:
            continue
        chave = f"{ano:04d}-{mes:02d}"
        if chave > _chave_mes(fim):
            continue
        if chave == _chave_mes(fim):
            dias_no_mes = monthrange(ano, mes)[1]
            if fim.day < dias_no_mes:
                kwh = kwh * fim.day / dias_no_mes
        por_mes[chave] = round(kwh, 2)
    return por_mes


async def _meta_do_projeto(cliente, slug: str, inicio: date, fim: date) -> _Meta:
    """A meta do projeto de cada mês entre `inicio` e `fim`, das duas fontes.

    A diária tem precedência (é dia a dia, então respeita "até hoje" sem
    proporção). A mensal digitada só entra nos meses que a diária não cobre, e
    só se pede o ano que tem mês faltando — nada de uma chamada por ano por
    hábito. Uma fonte fora do ar vira `indisponivel` + aviso, e não "sem meta":
    a tela precisa distinguir "ninguém cadastrou" de "o monitoramento caiu".
    """
    meta = _Meta()
    meses = _meses_entre(_chave_mes(inicio), _chave_mes(fim))
    avisos: list[str] = []

    try:
        diario = await cliente.pvsyst(slug, inicio, fim)
        meta.por_mes.update(_esperado_diario_por_mes(diario, inicio, fim))
    except Exception as exc:  # noqa: BLE001 — a meta é acessório; o medido segue
        meta.indisponivel = True
        avisos.append(f"meta diária do projeto indisponível ({type(exc).__name__})")

    faltando = [m for m in meses if m not in meta.por_mes]
    anos = sorted({int(m[:4]) for m in faltando})
    if anos:
        respostas = await asyncio.gather(
            *(cliente.pvsyst_manual(slug, ano) for ano in anos), return_exceptions=True
        )
        for ano, resposta in zip(anos, respostas, strict=True):
            if isinstance(resposta, BaseException):
                meta.indisponivel = True
                avisos.append(
                    f"meta mensal do projeto de {ano} indisponível ({type(resposta).__name__})"
                )
                continue
            for mes, kwh in _esperado_manual_por_mes(resposta, ano, fim).items():
                meta.por_mes.setdefault(mes, kwh)

    if meta.por_mes:
        # Chegou meta por algum caminho: a queda do outro não é mais o assunto.
        meta.indisponivel = False
    if avisos:
        meta.aviso = " · ".join(avisos)
    return meta


def _situacao_do_projeto(
    energia: float | None, esperado: float | None, meta_indisponivel: bool = False
) -> tuple[float | None, str, str]:
    """A régua do portal: `(pct, tom, situacao)`.

    Os limiares são os que o dono aceita para "dentro do esperado" numa usina
    de O&M — 95% cobre a variação de irradiação de um mês normal; abaixo de 85%
    algo está parado ou degradado e não é mais variação de clima.

        sem medição       -> semDados  "Sem dados de geração no período"
        sem meta          -> semDados  "Sem meta de projeto cadastrada"
        >= 95 %           -> ok        "Dentro do esperado"
        85 % a 95 %       -> alerta    "Abaixo do esperado"
        < 85 %            -> parado    "Bem abaixo do esperado"

    Nenhum ramo devolve número onde falta fonte: sem meta o `pct` é nulo, não 0.
    """
    if energia is None:
        return None, "semDados", "Sem dados de geração no período"
    if esperado is None or esperado <= 0:
        if meta_indisponivel:
            return None, "semDados", "Meta do projeto indisponível agora"
        return None, "semDados", "Sem meta de projeto cadastrada"
    pct = round(energia / esperado * 100, 1)
    if pct >= 95:
        return pct, "ok", "Dentro do esperado"
    if pct >= 85:
        return pct, "alerta", "Abaixo do esperado"
    return pct, "parado", "Bem abaixo do esperado"


def _juntar_avisos(*partes: str | None) -> str | None:
    juntos = [p for p in partes if p]
    return " · ".join(juntos) if juntos else None


def _usina_monitorada(db: Session, usuario: User, plant_link_id: int) -> PlantLink:
    """Escopo + vínculo com o meuWatt. Sem vínculo é 404, e não uma resposta vazia:
    o portal de energia não tem o que mostrar de uma usina que não é monitorada, e
    a tela precisa dizer isso em vez de desenhar um gráfico em branco."""
    link = _usina_no_escopo(db, usuario, plant_link_id)
    if not link.mw_plant_slug:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Esta usina não está ligada ao monitoramento."
        )
    return link


def _erro_do_meuwatt(exc: BaseException, contexto: str) -> HTTPException:
    """A régua de `manutencao._erro_do_upstream`, nomeando o meuWatt.

    Importado dentro da função porque `manutencao` importa daqui; no nível do
    módulo os dois se importariam em círculo (mesmo motivo do `_esta_aberta` em
    `detalhe_usina`).
    """
    from app.api.v1.manutencao import MONITORAMENTO, _erro_do_upstream

    if not isinstance(exc, Exception):
        exc = RuntimeError(str(exc))
    return _erro_do_upstream(exc, contexto, produto=MONITORAMENTO)


@router.get("/plants/{plant_link_id}/desempenho", response_model=DesempenhoOut)
async def desempenho_da_usina(
    plant_link_id: int,
    recorte: str = "mes",
    referencia: str | None = None,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> DesempenhoOut:
    """Medido × esperado do projeto no mês ou no ano, com PR, disponibilidade e
    perdas — tudo do meuWatt, nada calculado além da divisão.

    Diferente de `/geracao`, uma queda do `range` aqui é ERRO (502/504), não um
    200 com aviso: o número central da tela é o medido, e sem ele não há o que
    mostrar. A meta é acessório — cai em aviso.
    """
    if recorte not in ("mes", "ano"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recorte deve ser 'mes' ou 'ano'.")

    link = _usina_monitorada(db, usuario, plant_link_id)
    hoje = hoje_na_usina()
    inicio, fim = _janela(recorte, _referencia_pedida(referencia))
    # Até hoje, e não até o fim do mês: o `range` fabrica dias vazios no futuro e
    # a meta do projeto, somada até o dia 31, compararia mês inteiro com meio mês.
    fim = min(fim, hoje)

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_meuwatt(exc, "Não deu para ler o desempenho") from exc

    relatorio, meta = await asyncio.gather(
        cliente.geracao_periodo(link.mw_plant_slug, inicio, fim),
        _meta_do_projeto(cliente, link.mw_plant_slug, inicio, fim),
        return_exceptions=True,
    )
    if isinstance(relatorio, BaseException):
        raise _erro_do_meuwatt(relatorio, "Não deu para ler o desempenho")
    if isinstance(meta, BaseException):
        # `_meta_do_projeto` engole as próprias falhas; isto é rede de segurança.
        meta_segura = _Meta()
        meta_segura.indisponivel = True
        meta_segura.aviso = f"meta do projeto indisponível ({type(meta).__name__})"
        meta = meta_segura

    meses = _meses_entre(_chave_mes(inicio), _chave_mes(fim))
    energia = _energia_do_periodo(relatorio)
    esperado = meta.total(meses)
    pct, tom, situacao = _situacao_do_projeto(energia, esperado, meta.indisponivel)

    saida = DesempenhoOut(
        recorte=recorte,
        inicio=inicio.isoformat(),
        fim=fim.isoformat(),
        energia_kwh=energia,
        esperado_projeto_kwh=esperado,
        pct_do_projeto=pct,
        pr_pct=_pr_pct(relatorio),
        disponibilidade_real_pct=(
            _numero(relatorio.get("availability_real_pct")) if _tem_dado(relatorio) else None
        ),
        disponibilidade_contratual_pct=(
            _numero(relatorio.get("availability_contratual_pct"))
            if _tem_dado(relatorio) else None
        ),
        perdas_paradas_kwh=_perdas_do_periodo(relatorio),
        tom=tom,
        situacao=situacao,
        aviso=_juntar_avisos(
            "O monitoramento não devolveu geração para este período." if energia is None else None,
            meta.aviso,
        ),
    )

    if recorte == "ano":
        por_mes = _resumo_por_mes(relatorio)
        for mes in meses:
            linha = por_mes.get(mes)
            saida.meses.append(
                MesDesempenho(
                    mes=mes,
                    energia_kwh=_numero(linha.get("generation_kwh")) if linha else None,
                    esperado_projeto_kwh=meta.por_mes.get(mes),
                    disponibilidade_contratual_pct=(
                        _numero(linha.get("availability_contratual_pct")) if linha else None
                    ),
                    perdas_kwh=_numero(linha.get("lost_kwh")) if linha else None,
                )
            )
    return saida


#: Teto do histórico. Três anos são quatro chamadas ao `range` (uma por ano
#: civil) mais o ano anterior para a comparação — acima disso a tela vira
#: planilha, e o custo por abertura de página deixa de fazer sentido.
HISTORICO_MAX_MESES = 36


@router.get("/plants/{plant_link_id}/historico", response_model=HistoricoOut)
async def historico_da_usina(
    plant_link_id: int,
    meses: int = 24,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> HistoricoOut:
    """Os últimos N meses: medido × esperado × o mesmo mês do ano anterior.

    O `range` é lido em fatias de um ano civil (teto de 366 dias do upstream) e
    UM ano a mais para trás — é dele que sai `ano_anterior_kwh` do começo da
    série. Mês sem `monthly_summaries` fica nulo: a tela não desenha barra, e é
    assim que "não mediu" deixa de parecer "gerou zero".

    Uma fatia que falha anula os meses dela e vira aviso; todas falhando é erro,
    porque aí não há série nenhuma para mostrar.
    """
    if not 1 <= meses <= HISTORICO_MAX_MESES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"meses deve estar entre 1 e {HISTORICO_MAX_MESES}."
        )

    link = _usina_monitorada(db, usuario, plant_link_id)
    hoje = hoje_na_usina()
    ultimo_mes = _chave_mes(hoje)
    primeiro_mes = _deslocar_mes(ultimo_mes, -(meses - 1))
    inicio = _primeiro_dia(primeiro_mes)
    inicio_leitura = _primeiro_dia(_deslocar_mes(primeiro_mes, -12))

    try:
        cliente = await integracoes.cliente_meuwatt(db)
    except Exception as exc:  # noqa: BLE001
        raise _erro_do_meuwatt(exc, "Não deu para ler o histórico") from exc

    fatias = _fatias_por_ano(inicio_leitura, hoje)
    respostas, meta = await asyncio.gather(
        asyncio.gather(
            *(cliente.geracao_periodo(link.mw_plant_slug, a, b) for a, b in fatias),
            return_exceptions=True,
        ),
        _meta_do_projeto(cliente, link.mw_plant_slug, inicio, hoje),
        return_exceptions=True,
    )
    if isinstance(respostas, BaseException):
        raise _erro_do_meuwatt(respostas, "Não deu para ler o histórico")
    if isinstance(meta, BaseException):
        meta_segura = _Meta()
        meta_segura.indisponivel = True
        meta_segura.aviso = f"meta do projeto indisponível ({type(meta).__name__})"
        meta = meta_segura

    por_mes: dict[str, dict[str, Any]] = {}
    falhas: list[str] = []
    for (a, b), resposta in zip(fatias, respostas, strict=True):
        if isinstance(resposta, BaseException):
            falhas.append(f"{_chave_mes(a)} a {_chave_mes(b)} ({type(resposta).__name__})")
            continue
        por_mes.update(_resumo_por_mes(resposta))
    if len(falhas) == len(fatias):
        primeira = next(r for r in respostas if isinstance(r, BaseException))
        raise _erro_do_meuwatt(primeira, "Não deu para ler o histórico")

    saida = HistoricoOut(inicio=inicio.isoformat(), fim=hoje.isoformat())
    for mes in _meses_entre(primeiro_mes, ultimo_mes):
        linha = por_mes.get(mes)
        anterior = por_mes.get(_deslocar_mes(mes, -12))
        saida.meses.append(
            MesHistorico(
                mes=mes,
                energia_kwh=_numero(linha.get("generation_kwh")) if linha else None,
                esperado_projeto_kwh=meta.por_mes.get(mes),
                ano_anterior_kwh=_numero(anterior.get("generation_kwh")) if anterior else None,
                perdas_kwh=_numero(linha.get("lost_kwh")) if linha else None,
            )
        )

    saida.aviso = _juntar_avisos(
        f"Sem leitura do monitoramento em: {', '.join(falhas)}." if falhas else None,
        meta.aviso,
    )
    return saida
