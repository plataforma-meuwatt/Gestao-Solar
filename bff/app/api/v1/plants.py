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
from datetime import UTC, date, datetime
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

    # 3. FALHA vem antes de desempenho, e é o ponto que estava faltando. Um inversor
    #    parado é fato; disponibilidade é média, e média esconde fato.
    if usina.inversores_parados:
        n = usina.inversores_parados
        return "parado", f"{n} {'inversor parado' if n == 1 else 'inversores parados'}"
    if usina.disponibilidade_pct is not None and usina.disponibilidade_pct < 50:
        return "parado", "Disponibilidade baixa"

    # 4. Âmbar: algo a observar, com a usina de pé.
    if usina.inversores_alerta:
        n = usina.inversores_alerta
        return "alerta", f"{n} {'inversor em alerta' if n == 1 else 'inversores em alerta'}"
    if usina.inversores_mudos:
        n = usina.inversores_mudos
        return "alerta", f"{n} {'inversor sem comunicação' if n == 1 else 'inversores sem comunicação'}"
    if usina.disponibilidade_pct is not None and usina.disponibilidade_pct < 90:
        return "alerta", "Gerando parcialmente"

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
        # Quando o dado foi MEDIDO. `datetime.now()` seria a hora da resposta — e é esse
        # valor que vira o selo do modo offline, o mecanismo que deveria tornar o cache
        # honesto. Publicar a hora da resposta como hora do dado faz o selo mentir por
        # construção, e mentir justamente onde ele existe para não mentir.
        saida["medido_em"] = agora.get("timestamp")
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
    except Exception as exc:  # noqa: BLE001 — a tela precisa abrir mesmo assim
        erros.append(f"tempo real indisponível ({type(exc).__name__})")

    try:
        diario = await cliente.geracao_diaria(link.mw_plant_slug, dia)
        # `or` mataria o zero: `total_generation_kwh` é obrigatório no schema, e uma usina
        # que de fato gerou 0 kWh viraria "não sabemos". Aqui zero é informação.
        saida["energia_hoje_kwh"] = _numero(diario.get("total_generation_kwh"))
        # O mw-api calcula `avail = soma_ponderada / peso if peso > 0 else 100.0`. Com
        # TODO inversor sem comunicar, o laço não acumula peso e o campo sai **100.0
        # fabricado** — a usina muda apareceria como "disponibilidade 100%" ao lado de
        # "energia hoje 0 kWh". O número não é do upstream mentindo: é o denominador
        # vazio. Aqui ele vira nulo, que é o que de fato se sabe.
        saida["disponibilidade_pct"] = (
            None if saida.get("sem_comunicacao") else _numero(diario.get("plant_availability_pct"))
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
            dados = {"aviso": f"meuWatt indisponível: {exc}"}

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

    descricao = {
        Produto.MEUWATT: ("meuWatt", "Geração, inversores e disponibilidade"),
        Produto.MEUPLANO: ("meuPlano", "Manutenção, cronograma e ordens de serviço"),
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
