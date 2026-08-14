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

    tem_meuwatt: bool
    tem_meuplano: bool
    #: O que não deu para buscar, em português, para a tela poder dizer por quê.
    aviso: str | None = None


class UsinasOut(BaseModel):
    usinas: list[UsinaOut]
    total_kwp: float
    potencia_agora_kw: float | None = None
    energia_hoje_kwh: float | None = None
    atualizado_em: datetime
    aviso: str | None = None


def _tom(usina: UsinaOut) -> tuple[str, str]:
    """A cor e a frase que a acompanha.

    Deliberadamente conservador: sem dado do meuWatt a resposta é "sem dados", nunca "ok".
    Uma usina que parou de comunicar não pode aparecer verde.
    """
    if usina.potencia_kw is None:
        return "semDados", "Sem comunicação"
    if usina.disponibilidade_pct is not None and usina.disponibilidade_pct < 50:
        return "parado", "Disponibilidade baixa"
    if usina.potencia_kw <= 0:
        # Fora da janela solar isto é o esperado; a tela mostra o horário do dado ao lado.
        return "semDados", "Sem geração agora"
    if usina.disponibilidade_pct is not None and usina.disponibilidade_pct < 90:
        return "alerta", "Gerando parcialmente"
    return "ok", "Gerando"


def _numero(valor: Any) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


#: Estados de inversor no `MonitoringSnapshot` do mw-api
#: (`src/monitoring/schemas.py`, campo `InverterMonitoring.status`). A lista é fechada, e
#: ler dela — em vez de adivinhar nomes plausíveis — é o que evita contar parada errada.
PARADO = {"fault", "communication_error"}
#: `bedtime` é noite, não defeito: contar como parada acenderia alarme todo fim de tarde.
DORMINDO = "bedtime"


def _potencia_da_usina(agora: dict[str, Any]) -> float | None:
    """Potência instantânea da usina, em kW, somada dos inversores.

    O `monitoring/current` **não traz um total da usina** — traz `inverters[]`, e cada um
    com `active_power` em **watts**. Somar aqui e dividir por mil é o que transforma isso
    no número que a tela mostra.

    Nulo quando não veio inversor nenhum, e não zero: sem leitura a resposta certa é "não
    sabemos", que a tela desenha como travessão. Zero se leria como "não gerou".
    """
    inversores = agora.get("inverters")
    if not isinstance(inversores, list) or not inversores:
        return None

    watts = 0.0
    vistos = 0
    for inv in inversores:
        p = _numero(inv.get("active_power"))
        if p is not None:
            watts += p
            vistos += 1

    return round(watts / 1000, 2) if vistos else None


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

        # A contagem de inversores sai da MESMA resposta: são as posições que estão
        # reportando agora. Buscá-la em `/slots` daria o cadastro — quantos deveriam
        # existir —, que é outra pergunta e não diz quantos estão de pé.
        inversores = agora.get("inverters")
        if isinstance(inversores, list):
            saida["inversores"] = len(inversores)
            saida["inversores_parados"] = _parados(inversores)
    except Exception as exc:  # noqa: BLE001 — a tela precisa abrir mesmo assim
        erros.append(f"tempo real indisponível ({type(exc).__name__})")

    try:
        diario = await cliente.geracao_diaria(link.mw_plant_slug, dia)
        saida["energia_hoje_kwh"] = _numero(
            diario.get("total_generation_kwh") or diario.get("generation_kwh")
        )
        saida["disponibilidade_pct"] = _numero(
            diario.get("plant_availability_pct")
            or diario.get("availability_real_pct")
        )
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
                *(_dados_meuwatt(cliente, l, date.today()) for l in com_mw),
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
            capacidade_kwp=link.kwp,
            potencia_kw=d.get("potencia_kw"),
            energia_hoje_kwh=d.get("energia_hoje_kwh"),
            disponibilidade_pct=d.get("disponibilidade_pct"),
            tom="semDados",
            situacao="",
            tem_meuwatt=link.tem_meuwatt,
            tem_meuplano=link.tem_meuplano,
            aviso=d.get("aviso"),
        )
        if u.potencia_kw is not None and link.kwp:
            u.pct_capacidade = max(0, min(100, round(u.potencia_kw / link.kwp * 100)))
        u.tom, u.situacao = _tom(u)
        saida.append(u)

    medidas = [u.potencia_kw for u in saida if u.potencia_kw is not None]
    energias = [u.energia_hoje_kwh for u in saida if u.energia_hoje_kwh is not None]

    return UsinasOut(
        usinas=saida,
        total_kwp=round(sum(l.kwp or 0 for l in links), 2),
        potencia_agora_kw=round(sum(medidas), 2) if medidas else None,
        energia_hoje_kwh=round(sum(energias), 2) if energias else None,
        atualizado_em=datetime.now(UTC),
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


def _parados(inversores: list[dict[str, Any]]) -> int:
    """Quantos inversores estão parados agora.

    Os estados vêm da lista fechada de `InverterMonitoring.status` no mw-api, e só `fault`
    e `communication_error` contam. `bedtime` é a usina dormindo — contá-lo encheria a
    tela de vermelho todo fim de tarde —, e `alert` é aviso com o inversor gerando.
    """
    return sum(1 for i in inversores if str(i.get("status") or "").strip().lower() in PARADO)


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
                _dados_meuwatt(cliente, link, date.today()),
                cliente.alertas(link.mw_plant_slug),
                return_exceptions=True,
            )
            if not isinstance(dados, dict):
                dados = {"aviso": "Dados de geração indisponíveis."}
            if isinstance(alertas, list):
                equipamentos["alertas_ativos"] = len(alertas)
        except Exception as exc:  # noqa: BLE001
            dados = {"aviso": f"meuWatt indisponível: {exc}"}

    detalhe = UsinaDetalheOut(
        id=link.id,
        nome=link.nome,
        cidade=link.cidade,
        uf=link.uf,
        capacidade_kwp=link.kwp,
        potencia_kw=dados.get("potencia_kw"),
        energia_hoje_kwh=dados.get("energia_hoje_kwh"),
        disponibilidade_pct=dados.get("disponibilidade_pct"),
        tom="semDados",
        situacao="",
        tem_meuwatt=link.tem_meuwatt,
        tem_meuplano=link.tem_meuplano,
        aviso=dados.get("aviso"),
        inversores=dados.get("inversores"),
        inversores_parados=dados.get("inversores_parados"),
        alertas_ativos=equipamentos.get("alertas_ativos"),
    )
    if detalhe.potencia_kw is not None and link.kwp:
        detalhe.pct_capacidade = max(0, min(100, round(detalhe.potencia_kw / link.kwp * 100)))
    detalhe.tom, detalhe.situacao = _tom(detalhe)

    if link.mp_usina_id:
        try:
            mp = await integracoes.cliente_meuplano(db)
            ordens = await mp.ordens_servico(link.mp_usina_id)
            detalhe.ordens_abertas = len(ordens)
            detalhe.ordens_recentes = [
                str(o.get("titulo") or o.get("numero") or o.get("id")) for o in ordens[:3]
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
