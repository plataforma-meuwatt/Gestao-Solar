"""Ferramentas de GERAÇÃO do assistente do WhatsApp — o meuWatt responde, o GS guarda a porta.

Toda leitura é pela API do meuWatt com o token DESTA pessoa (ou o da empresa que a atende,
`vinculos.token_do_cliente`), e só das usinas que o Gestão Solar concede a ela
(`usinas_do_usuario`). As duas camadas valem juntas: o token diz com que credencial, a
concessão diz o quê — usina fora da concessão não existe para o assistente.

REGRA 0: número só sai daqui. Ausência é `None` ("sem dados"), nunca zero — usina sem
estação recebe 0,0 de irradiação e de PR da API, e aqui isso vira `None`.
"""
from __future__ import annotations

import asyncio
import io
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.clients.meuwatt import MeuWattClient

_TZ = ZoneInfo("America/Sao_Paulo")

_CAUSA = {
    "zero_active_power": "inversor parado (potência zero com comunicação)",
    "communication_failure": "falha de comunicação",
    "never_woke_up": "não ligou no dia",
    "no_data": "sem dados",
}
_RESOLUCAO = {"production_resumed": "voltou a produzir", "data_ceased": "dados pararam de chegar",
              "data_resumed": "dados voltaram", "still_open": "em aberto"}
_IRR = ("irradiacao_poa_dia", "irradiacao_ghi_dia", "irradiacao_ghi_sat_dia")


class Recusa(Exception):
    """Frase que vai para o modelo como `{"erro": ...}` — ele a repassa à pessoa."""


@dataclass
class Contexto:
    db: Session
    user: Any
    telefone: str
    mw: MeuWattClient | None = None
    #: as usinas CONCEDIDAS que existem no meuWatt: {slug: {nome, id, kwp, estacao, ...}}
    usinas: dict[str, dict] = field(default_factory=dict)
    #: arquivos/imagens que as ferramentas mandaram neste turno (o texto não repete o link)
    enviados: list[str] = field(default_factory=list)
    #: as ferramentas chamadas neste turno — vão para o log do bot (`gs_bot_registros`)
    ferramentas: list[str] = field(default_factory=list)
    #: a conversa ANTES desta mensagem ({role, content}) — vai ao assistente do meuPlano
    historico: list[dict] = field(default_factory=list)
    #: o meuWatt não respondeu nesta mensagem: só a GERAÇÃO fica de fora (a frase vai à IA)
    mw_falha: str | None = None
    #: a AÇÃO que esta mensagem armou (helper ou meuPlano) — uma só; o texto dela vai pelo sistema
    proposta: Any = None
    #: a mensagem desta vez, como a IA a vê (sem a senha) — o pedido de documento ASSINADO é
    #: reconhecido nela também, não só na pergunta que a IA monta
    pedido: str = ""
    #: o bot perguntou ao meuPlano sobre ACESSO de equipamento (senha, PIN, Wi-Fi, cadeado, login…)
    credencial: bool = False
    #: as senhas que este turno conheceu pelo VALOR — as que o meuPlano REVELOU (`segredos` do run) e as que a pessoa
    #: mandou gravar (os campos da proposta de acesso, `digitados`): somem do log, do gateway e do que foi guardado antes
    segredos: list = field(default_factory=list)
    digitados: list = field(default_factory=list)
    #: as opções que o meuPlano ofereceu para MARCAR (`escolha` do run): vão num formulário depois da resposta
    escolha: dict | None = None
    #: o formulário de CADASTRO pedido neste turno (o que já se sabe, para vir preenchido): vai depois da resposta
    cadastro: dict | None = None
    #: o formulário de AVALIAÇÃO do lugar (`assistente_local.avaliar_lugar`): vai depois da resposta (e do resumo)
    avaliacao: dict | None = None
    #: texto do SISTEMA ao pé da resposta (os links do Google Maps e do Waze de `local_da_usina`): a IA não o reescreve
    rodape: list = field(default_factory=list)
    #: as mensagens da classificação de paradas que este turno começou (`assistente_paradas`): saem pelo sistema, com
    #: os botões, no lugar da resposta da IA
    fluxo: list | None = None
    #: a IA roda numa AUTOMAÇÃO (`services/automacoes`), não numa conversa: só lê; `helper.propor` recusa toda ação
    automacao: bool = False


#: A lista de usinas do meuWatt de cada pessoa, por 5 min — ela era pedida a cada "oi".
#: ponytail: em memória e por processo; uma concessão nova no GS vale na hora (o recorte é
#: refeito a cada mensagem), só a lista do meuWatt espera até 5 min.
_USINAS_MW: dict[int, tuple[float, list[dict]]] = {}
USINAS_MW_TTL_S = 300


def usinas_do_bot(db: Session, user) -> list:
    """O recorte de usinas do BOT: o do aplicativo (gerente: a carteira da empresa; dono: o
    concedido) e, para o TÉCNICO — que não recebe usina no aplicativo —, a carteira da empresa
    dele. É ele quem vai a campo, e o helper é a ferramenta dele: sem isso, geração e helper
    nunca respondiam a técnico, com a tela dizendo "Respondendo" (avaliação de 24/10/2026). O
    token do meuWatt DELE continua limitando o que ele enxerga lá."""
    from sqlalchemy import select

    from app.api.v1.plants import usinas_do_usuario
    from app.models.plant import PlantLink
    from app.models.user import Perfil
    from app.services import empresas

    if user.perfil is Perfil.TECNICO:
        minhas = empresas.empresas_da_conta(db, user)
        return list(db.scalars(
            select(PlantLink).where(PlantLink.empresa_id.in_(minhas), PlantLink.ativo).order_by(PlantLink.nome)
        ).all()) if minhas else []
    return usinas_do_usuario(db, user)


async def preparar(ctx: Contexto) -> None:
    """Liga o contexto ao meuWatt: o token PRÓPRIO da pessoa e o recorte de usinas do GS
    (gerente: a carteira da empresa; cliente: o concedido) — vale o que os dois deixam ver.
    O administrador da plataforma não usa o bot: não tem token (decisão do dono, 23/10/2026)."""
    from app.services.vinculos import SemConexao, cliente_meuwatt
    if "bot_meuwatt" not in ctx.user.bot_ativo:
        return
    concedidas = {p.mw_plant_slug: p for p in usinas_do_bot(ctx.db, ctx.user) if p.mw_plant_slug}
    if not concedidas:
        return
    try:
        ctx.mw = cliente_meuwatt(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao:
        return
    guardada = _USINAS_MW.get(ctx.user.id)
    if guardada and time.monotonic() - guardada[0] < USINAS_MW_TTL_S:
        lista = guardada[1]
    else:
        ctx.db.commit()                                   # solta a conexão enquanto o meuWatt responde
        try:
            lista = await ctx.mw.usinas()
        except Exception as e:                            # noqa: BLE001 — meuWatt fora não cala a manutenção
            from app.services.integracoes import Produto, traduzir_falha

            ctx.mw, ctx.mw_falha = None, traduzir_falha(e, Produto.MEUWATT).detalhe
            return
        _USINAS_MW[ctx.user.id] = (time.monotonic(), lista)
    for p in lista:
        link = concedidas.get(p.get("slug"))
        if link is not None:
            ctx.usinas[p["slug"]] = {"nome": link.nome or p.get("name"), "slug": p["slug"], "id": p.get("id"),
                                     "kwp": p.get("total_capacity_kwp"), "estacao": p.get("has_weather_station"),
                                     "inversores": p.get("inverter_count"), "cidade": p.get("city")}


# --------------------------------------------------------------------------- utilitários
def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("ufv", " ").replace("-", " ").split())


def _usina(ctx: Contexto, nome: str | None) -> dict:
    if ctx.mw_falha:
        raise Recusa(f"O monitoramento (meuWatt) não respondeu agora: {ctx.mw_falha} Tente de novo em instantes.")
    if ctx.mw is None or not ctx.usinas:
        raise Recusa("Não há usina com monitoramento liberada para você no Gestão Solar.")
    return escolher_usina(list(ctx.usinas.values()), nome)


def escolher_usina(todas: list[dict], nome: str | None) -> dict:
    """A usina ({nome, slug, …}) pelo nome falado ou pelo slug: a única, a exata ou a única que contém o nome."""
    if not todas:
        raise Recusa("Não há usina liberada para você no Gestão Solar.")
    if not (nome or "").strip():
        if len(todas) == 1:
            return todas[0]
        raise Recusa("Qual usina? Você tem: " + ", ".join(u["nome"] for u in todas) + ".")
    alvo = _norm(nome)
    exatas = [u for u in todas if alvo in (_norm(u["nome"]), _norm(u["slug"]))]
    cands = exatas or [u for u in todas if alvo in _norm(u["nome"]) or alvo in _norm(u["slug"])]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        raise Recusa(f"Não achei '{nome}' nas suas usinas: " + ", ".join(u["nome"] for u in todas) + ".")
    raise Recusa(f"Mais de uma usina casa '{nome}': " + ", ".join(u["nome"] for u in cands) + ".")


def hoje() -> date:
    return datetime.now(_TZ).date()


#: dado do meuWatt mais velho que isto não é "agora" (a mesma régua do unifilar do helper, `VELHO_MW_S`)
VELHO_S = 20 * 60


def dado_velho(iso: str | None) -> str | None:
    """A frase para a IA quando o último dado do meuWatt é velho demais para ser "agora" (ou não diz de quando é)."""
    from app.core.datas import hora_brt

    try:
        quando = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return "O meuWatt não disse de quando é o dado: não diga 'agora', nem 'sem falha', nem 'todos gerando'."
    quando = quando if quando.tzinfo else quando.replace(tzinfo=_TZ)
    idade = (datetime.now(UTC) - quando).total_seconds()
    if idade <= VELHO_S:
        return None
    return (f"O último dado do meuWatt é das {hora_brt(quando.isoformat())} (há {int(idade // 60)} min): diga essa hora "
            "junto dos números de hoje; não diga 'agora', 'sem falha', 'todos gerando' nem que estão comunicando.")


async def dado_de_hoje(ctx: "Contexto", slug: str) -> dict:
    """A hora do último dado do meuWatt da usina e, se velho, o aviso: o que toda leitura de HOJE leva junto ("nunca
    enganar": diga de quando é o dado). Sem a resposta, o aviso diz que não deu para conferir."""
    from app.core.datas import hora_brt

    try:
        iso = (await ctx.mw.monitoramento_atual(slug) or {}).get("data_at")
    except httpx.HTTPError:
        return {"aviso": "Não deu para conferir de quando é o último dado do meuWatt: não diga 'agora' nem 'sem falha'."}
    return {"dado_do_meuwatt": hora_brt(iso) if iso else None, **({"aviso": v} if (v := dado_velho(iso)) else {})}


def _periodo(inicio: str | None, fim: str | None) -> tuple[date, date]:
    try:
        a = date.fromisoformat(inicio) if inicio else hoje()
        b = date.fromisoformat(fim) if fim else a
    except ValueError:
        raise Recusa("Datas no formato AAAA-MM-DD.") from None
    a, b = min(a, b), min(max(a, b), hoje())
    if (b - a).days > 365:
        raise Recusa("Período máximo de 366 dias.")
    return a, b


def _r(v: Any, n: int = 1) -> float | None:
    return None if v is None else round(float(v), n)


def _pct(v: Any) -> float | None:
    return None if v is None else round(float(v) * 100, 1)


def _soma(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return round(sum(v), 2) if v else None


async def _range(ctx: Contexto, u: dict, a: date, b: date, atual: dict | None = None) -> dict:
    r = await ctx.mw.geracao_periodo(u["slug"], a, b)
    if b == hoje():
        _hoje_ao_vivo(r, atual if atual is not None else await ctx.mw.monitoramento_atual(u["slug"]))
    return r


def _hoje_ao_vivo(r: dict, c: dict) -> None:
    """O fechamento diário do meuWatt só consolida HOJE no dia seguinte — às 17h de 22/10
    trazia 641 kWh em Pirapozinho contra 12.375 kWh ao vivo. O dia de hoje sai do
    `monitoring/current`, no total e por inversor."""
    h = hoje().isoformat()
    vivo = {i.get("serial_number"): i.get("energy_today_kwh") for i in c.get("inverters") or []}
    cd = r.get("chart_data") or {}
    parcial = {sn: next((p.get("y") or 0 for p in pts if p.get("t") == h), 0)
               for sn, pts in (cd.get("daily_generation") or {}).items()}
    for i in r.get("inverters") or []:
        if vivo.get(i.get("sn")) is not None:
            i["total_yield_kwh"] = (i.get("total_yield_kwh") or 0) - parcial.get(i["sn"], 0) + vivo[i["sn"]]
    total = c.get("energy_today_kwh")
    if total is None:
        return
    for d in r.get("daily_summaries") or []:
        if d.get("date") == h:
            r["total_generation_kwh"] = (r.get("total_generation_kwh") or 0) - (d.get("generation_kwh") or 0) + total
            d["generation_kwh"] = total
    if r.get("total_capacity_kwp") and r.get("total_generation_kwh") is not None:
        r["productivity"] = r["total_generation_kwh"] / r["total_capacity_kwp"]
    for p in cd.get("daily_pr") or []:
        if p.get("t") == h:
            p["pr"] = c.get("plant_pr_today")
    if r.get("start_date") == h:
        r["performance_ratio"] = c.get("plant_pr_today")


def _irr_total(u: dict, r: dict) -> dict:
    irr = r.get("irradiation") or {}
    if not u.get("estacao"):
        return {"poa": None, "ghi": None}
    return {"poa": _r(irr.get("hpoa"), 2), "ghi": _r(irr.get("hghi"), 2)}


async def _irradiacao(ctx: Contexto, slugs: list[str], a: date, b: date) -> tuple[list[str], dict]:
    r = await ctx.mw.grandezas(slugs, _IRR, a, b)
    por: dict[str, dict] = {}
    for x in r.get("series") or []:
        por.setdefault(x["plant"], {})[x["grandeza"]] = x.get("values") or []
    return r.get("timestamps") or [], por


# --------------------------------------------------------------------------- ferramentas
async def listar_usinas(ctx: Contexto, a: dict) -> dict:
    if ctx.mw is None:
        raise Recusa("Não há usina com monitoramento liberada para você no Gestão Solar.")
    return {"usinas": [{"nome": u["nome"], "potencia_kwp": _r(u["kwp"]), "inversores": u["inversores"],
                        "cidade": u["cidade"], "tem_estacao": u["estacao"]} for u in ctx.usinas.values()]}


async def geracao(ctx: Contexto, a: dict) -> dict:
    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo(a.get("inicio"), a.get("fim"))
    out: dict[str, Any] = {"usina": u["nome"], "inicio": ini.isoformat(), "fim": fim.isoformat()}
    c = await ctx.mw.monitoramento_atual(u["slug"]) if fim == hoje() else None
    velho = None
    if c is not None:
        out["agora"] = {
            "energia_hoje_ate_agora_kwh": _r(c.get("energy_today_kwh")),
            "potencia_agora_kw": _r(sum((i.get("active_power") or 0) for i in c["inverters"]) / 1000)
            if c.get("inverters") else None,
            "pr_hoje_pct": _pct(c.get("plant_pr_today")) if u["estacao"] else None,
            "usina_dormindo": c.get("plant_sleeping"),
            "inversores_com_falha": len(c.get("faulty_inverters") or []), "dado_de": c.get("data_at")}
        if velho := dado_velho(c.get("data_at")):
            # 25/11/2026: "4.047,8 kWh até agora, com todos os inversores sem falha", com o último dado de 40 min antes
            out["agora"].update(potencia_agora_kw=None, inversores_com_falha=None, aviso=velho)
    r = await _range(ctx, u, ini, fim, c)
    kwp = r.get("total_capacity_kwp")
    invs, brutos = [], []
    for i in r.get("inverters") or []:
        kwh, ik = i.get("total_yield_kwh"), i.get("capacity_kwp")
        invs.append({"inversor": i.get("slot_label") or i.get("sn"), "skid": i.get("transformer_name"),
                     "energia_kwh": _r(kwh), "produtividade_kwh_kwp": _r(kwh / ik, 2) if kwh is not None and ik else None,
                     "perdido_kwh": _r(i.get("total_lost_kwh")), "com_falha": None if velho else i.get("is_faulty"),
                     **_conta_da_perda(i.get("perda_memoria"))})
        brutos.append((str(i.get("sn") or ""), kwh, ik))
    prods = [i["produtividade_kwh_kwp"] for i in invs if i["produtividade_kwh_kwp"] is not None]
    med = median(prods) if prods else None
    for i in invs:
        x = i["produtividade_kwh_kwp"]
        i["desvio_da_mediana_pct"] = _r((x / med - 1) * 100) if x is not None and med else None
    strings = await _strings_por_inversor(ctx, u["slug"], fim) if invs else {}
    if isinstance(strings, str):
        out["strings"] = strings
    else:
        for i, (sn, kwh, ik) in zip(invs, brutos):
            if sn in strings:
                i.update(_strings_na_comparacao(strings[sn], kwh, ik, med, ini, fim))
        if any("strings_com_problema" in i for i in invs):
            out["nota_strings"] = NOTA_STRINGS
    invs.sort(key=lambda i: (i["produtividade_kwh_kwp"] is None, -(i["produtividade_kwh_kwp"] or 0)))
    cd = r.get("chart_data") or {}
    pr_dia = {d["t"]: d.get("pr") for d in cd.get("daily_pr") or []}
    irr_dia = {d["t"]: d.get("hpoa") for d in cd.get("daily_irradiation") or []}
    dias = [{"data": d["date"], "energia_kwh": _r(d.get("generation_kwh")),
             "produtividade_kwh_kwp": _r(d["generation_kwh"] / kwp, 2) if d.get("generation_kwh") is not None and kwp else None,
             "pr_pct": _pct(pr_dia.get(d["date"])) if u["estacao"] else None,
             "irradiacao_poa_kwh_m2": _r(irr_dia.get(d["date"]), 2) if u["estacao"] else None}
            for d in r.get("daily_summaries") or []]
    com = [d for d in dias if d["energia_kwh"] is not None]
    s = r.get("summary") or {}
    out.update(_conhecidos(await conhecidos_abertos(ctx, u)))
    out.update({
        "energia_kwh": _r(r.get("total_generation_kwh")), "potencia_kwp": _r(kwp),
        "produtividade_kwh_kwp": _r(r.get("productivity"), 2),
        "pr_pct": _pct(r.get("performance_ratio")) if u["estacao"] else None,
        "irradiacao_estacao_kwh_m2": _irr_total(u, r),
        "disponibilidade_real_pct": _r(r.get("availability_real_pct")),
        "esperado_kwh": _r(s.get("total_expected_kwh")), "perdido_kwh": _r(s.get("total_lost_kwh")),
        "perda_pct": _r(s.get("loss_pct"), 2), "dias_com_dado": r.get("days_with_data"),
        "melhor_dia": max(com, key=lambda d: d["energia_kwh"]) if com else None,
        "pior_dia": min(com, key=lambda d: d["energia_kwh"]) if com else None,
        "meses": [{"mes": m["month"], "energia_kwh": _r(m.get("generation_kwh")), "perdido_kwh": _r(m.get("lost_kwh"))}
                  for m in r.get("monthly_summaries") or []],
        "inversores_do_melhor_ao_pior": invs, "mediana_produtividade_inversores": _r(med, 2),
        "dias": dias if len(dias) <= 62 else "período longo: use meses, melhor_dia e pior_dia",
    })
    if fim == hoje():
        out.update(esperado_kwh=None, perdido_kwh=None, perda_pct=None,
                   nota_hoje="Hoje vem da leitura ao vivo; esperado e perdido de hoje só fecham amanhã.")
    return out


async def comparar_usinas(ctx: Contexto, a: dict) -> dict:
    if ctx.mw is None or not ctx.usinas:
        raise Recusa("Não há usina com monitoramento liberada para você no Gestão Solar.")
    ini, fim = _periodo(a.get("inicio"), a.get("fim"))
    todas = list(ctx.usinas.values())

    async def uma(u: dict) -> dict:
        try:
            r = await _range(ctx, u, ini, fim)
        except Exception as e:                              # noqa: BLE001 — uma usina não derruba a lista
            return {"usina": u["nome"], "erro": str(e)[:120]}
        return {"usina": u["nome"], "potencia_kwp": _r(r.get("total_capacity_kwp")),
                "energia_kwh": _r(r.get("total_generation_kwh")), "produtividade_kwh_kwp": _r(r.get("productivity"), 2),
                "pr_pct": _pct(r.get("performance_ratio")) if u["estacao"] else None,
                "irradiacao_poa_kwh_m2": _irr_total(u, r)["poa"],
                "disponibilidade_real_pct": _r(r.get("availability_real_pct")),
                "perdido_kwh": _r((r.get("summary") or {}).get("total_lost_kwh")),
                **(await dado_de_hoje(ctx, u["slug"]) if fim == hoje() else {})}

    linhas = list(await asyncio.gather(*(uma(u) for u in todas)))
    _, irr = await _irradiacao(ctx, [u["slug"] for u in todas], ini, fim)
    for u, x in zip(todas, linhas):
        x["irradiacao_ghi_satelite_kwh_m2"] = _soma((irr.get(u["slug"]) or {}).get("irradiacao_ghi_sat_dia") or [])
    linhas.sort(key=lambda x: (x.get("produtividade_kwh_kwp") is None, -(x.get("produtividade_kwh_kwp") or 0)))
    return {"inicio": ini.isoformat(), "fim": fim.isoformat(), "usinas": linhas,
            "nota": ("Compare pela produtividade (kWh/kWp). Irradiação entre todas: a de satélite. Usina com `aviso`: o "
                     "dado dela é velho; diga a hora dele e não a compare como se fosse de agora.")}


async def irradiacao(ctx: Contexto, a: dict) -> dict:
    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo(a.get("inicio"), a.get("fim"))
    ts, irr = await _irradiacao(ctx, [u["slug"]], ini, fim)
    col = {g: (irr.get(u["slug"]) or {}).get(g) or [None] * len(ts) for g in _IRR}
    dias = [{"data": t, "poa_estacao": _r(col["irradiacao_poa_dia"][k], 2), "ghi_estacao": _r(col["irradiacao_ghi_dia"][k], 2),
             "ghi_satelite": _r(col["irradiacao_ghi_sat_dia"][k], 2)} for k, t in enumerate(ts)]
    out: dict[str, Any] = {
        "usina": u["nome"], "tem_estacao": u["estacao"], "inicio": ini.isoformat(), "fim": fim.isoformat(),
        "total_kwh_m2": {"poa_estacao": _soma(col["irradiacao_poa_dia"]), "ghi_estacao": _soma(col["irradiacao_ghi_dia"]),
                         "ghi_satelite": _soma(col["irradiacao_ghi_sat_dia"])},
        "dias": dias if len(dias) <= 62 else "período longo: veja o total",
        "fontes": "'estacao' = medida na usina. 'satelite' = estimativa externa: diga que é satélite.",
        "nao_disponivel": "Vento, chuva e umidade não estão disponíveis."}
    if fim == hoje():
        c = await ctx.mw.monitoramento_atual(u["slug"])
        out["agora"] = [{"estacao": w.get("name"), "comunicando": w.get("comm"), "poa_w_m2": _r(w.get("poa_wm2")),
                         "ghi_w_m2": _r(w.get("ghi_wm2")), "poa_hoje_kwh_m2": _r(w.get("hpoa_today_kwh"), 2),
                         "leitura_de": w.get("last_read_at")} for w in c.get("weather_stations") or []]
    return out


async def projeto(ctx: Contexto, a: dict) -> dict:
    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo(a.get("inicio"), a.get("fim"))
    r = await _range(ctx, u, ini, fim)
    proj: dict[str, dict] = {}
    for ano in range(ini.year, fim.year + 1):
        for m in (await ctx.mw.pvsyst_manual(u["slug"], ano)).get("rows") or []:
            proj[f"{ano}-{int(m['month']):02d}"] = m
    meses = []
    for m in r.get("monthly_summaries") or []:
        pj, real = proj.get(m["month"]) or {}, m.get("generation_kwh")
        d1 = date.fromisoformat(m["month"] + "-01")
        prox = (d1 + timedelta(days=32)).replace(day=1)
        a0, b0 = max(ini, d1), min(fim, prox - timedelta(days=1))
        frac = ((b0 - a0).days + 1) / (prox - timedelta(days=1)).day
        prev = pj.get("e_grid") * frac if pj.get("e_grid") is not None else None
        meses.append({"mes": m["month"], "dias_considerados": (b0 - a0).days + 1, "real_kwh": _r(real),
                      "projeto_kwh_no_periodo": _r(prev),
                      "real_vs_projeto_pct": _r((real / prev - 1) * 100) if real is not None and prev else None,
                      "pr_projeto_pct": _r(pj.get("pr")), "poa_projeto_kwh_m2": _r(pj.get("poa")),
                      "disponibilidade_real_pct": _r(m.get("availability_real_pct")), "perdido_kwh": _r(m.get("lost_kwh"))})
    return {"usina": u["nome"], "meses": meses,
            "real_periodo": {"energia_kwh": _r(r.get("total_generation_kwh")),
                             "pr_pct": _pct(r.get("performance_ratio")) if u["estacao"] else None,
                             "irradiacao_estacao_kwh_m2": _irr_total(u, r)},
            "como_explicar": ("Compare irradiação real × de projeto (sol abaixo explica geração abaixo), PR real × de "
                              "projeto, disponibilidade e perdas. Mês parcial já vem proporcional. Sem projeto: diga isso.")}


async def paradas(ctx: Contexto, a: dict) -> dict:
    """As paradas pela MESMA régua da tela de Paradas (`paradas.ler_do_detector`): só a parada
    relevante conta, perda sem conta feita é nula, período não analisado é "sem dados" — o bot e
    o portal davam números diferentes para o mesmo mês (avaliação 13)."""
    from app.api.v1.paradas import SEM_CONTA, ParadasOut, ler_do_detector

    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo(a.get("inicio"), a.get("fim"))
    saida = ParadasOut(recorte="periodo", inicio=ini.isoformat(), fim=fim.isoformat())
    linhas = await ler_do_detector(ctx.mw, u["id"], saida)
    abertas = [x for x in linhas if not x.get("resolved_at")]

    def conta(campo, rot=None):
        c: dict[str, int] = {}
        for x in linhas:
            k = (rot or {}).get(x.get(campo), x.get(campo) or "não informado")
            c[k] = c.get(k, 0) + 1
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    def item(x):
        return {"inversor": x.get("slot_label"), "skid": x.get("transformer_name"), "inicio": x.get("stopped_at"),
                "fim": x.get("resolved_at"), "minutos": x.get("off_minutes"), "causa": _CAUSA.get(x.get("cause"), x.get("cause")),
                "situacao": _RESOLUCAO.get(x.get("resolution_reason"), x.get("resolution_reason")),
                "perda_kwh": None if x.get("loss_method") in SEM_CONTA else _r(x.get("shadow_loss_kwh"), 2)}

    return {"usina": u["nome"], **_conhecidos(await conhecidos_abertos(ctx, u)), "inicio": saida.inicio, "fim": saida.fim, "total": saida.total,
            "em_aberto": saida.em_aberto if saida.total is not None else None,
            "fechadas": saida.total - saida.em_aberto if saida.total is not None else None,
            "perda_total_kwh": saida.perda_kwh, "minutos_parados_total": saida.tempo_parado_min,
            "por_causa": conta("cause", _CAUSA), "por_inversor": conta("slot_label"),
            "abertas": [item(x) for x in abertas][:20],
            "maiores_perdas": [item(x) for x in sorted(linhas, key=lambda x: -(x.get("shadow_loss_kwh") or 0))[:10]],
            "aviso": saida.aviso,
            "nota": ("Só paradas relevantes, como na tela de Paradas (piscadas curtas e buracos de leitura ficam de "
                     "fora). Total nulo = o detector não analisou o período (não é zero). Perda nula = em alguma "
                     "parada o detector não fez a conta (sem par para comparar): diga isso, não some zero.")}


def _trips(bruto: Any, desde: datetime) -> list[dict]:
    itens = bruto.get("events") if isinstance(bruto, dict) else bruto
    saida = []
    for e in itens if isinstance(itens, list) else []:
        try:
            quando = datetime.fromisoformat(str(e.get("timestamp")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if quando >= desde:
            saida.append({"quando": quando.astimezone(_TZ).strftime("%d/%m %H:%M"), "funcao": e.get("trip_code"),
                          "evento": {"TRIPPED": "disparou", "CLEARED": "limpou"}.get(e.get("event"), e.get("event"))})
    return saida


async def reles(ctx: Contexto, a: dict) -> dict:
    """Os relés de PROTEÇÃO da usina agora (comunica? tensão, corrente) e os trips que o meuWatt registrou (dono,
    31/10/2026: "Pirapozinho está parado… o skid 2 tá parado" — o bot leu só a lista de trips ATIVOS, que não traz o
    trip que já limpou nem o relé sem comunicação, e respondeu "não há trip ativo")."""
    u = _usina(ctx, a.get("usina"))
    dias = max(1, min(int(a.get("dias") or 2), 30))
    agora = await ctx.mw.monitoramento_atual(u["slug"])
    protecao = [r for r in agora.get("relays") or []
                if not r.get("is_temperature_relay") and not str(r.get("model") or "").startswith("abs")]
    desde = datetime.now(_TZ) - timedelta(days=dias)
    try:                                                  # a regra de "está ok" e o «já sei» são da tela Leituras
        lidos = {x["relay_id"]: x for x in (await ctx.mw.leituras(u["slug"])).get("relays") or []}
    except Exception:                                     # noqa: BLE001 (sem ela, fica o monitoramento)
        lidos = {}

    async def um(r: dict) -> dict:
        try:
            trips = _trips(await ctx.mw.eventos_de_trip(u["slug"], int(r["relay_db_id"]), 50), desde)
        except Exception:                                 # noqa: BLE001
            trips = None
        lido = lidos.get(r.get("relay_db_id"))
        if lido is None:                              # sem a tela Leituras: a regra de reserva do diagnóstico
            from app.services.diagnostico import _da_reserva
            lido = _da_reserva(r, agora.get("read_evidence") != "unavailable", datetime.now(UTC))
        valor = {x.get("key"): x.get("value") for x in lido.get("readings") or []}   # nulo = sem valor de AGORA
        status = {x.get("key"): x.get("status") for x in lido.get("readings") or []}
        fases = lambda k: [_r(valor.get(f"{k}_{f}")) for f in "abc"]
        return {"rele": r.get("name"), "skid": r.get("transformer_name"),
                "comunica": {"ok": True, "no_comm": False}.get(status.get("comm")),
                "tensao_v": fases("voltage"), "corrente_a": fases("current"),
                "potencia_kw": _r(valor.get("total_active_power")),
                "leituras_que_pedem_atencao": _atencao(lido) if lidos else None, "trips": trips}

    return {"usina": u["nome"], "lido_em": agora.get("data_at"), "dias": dias,
            "noite": agora.get("plant_sleeping"),         # corrente 0 à noite é normal, não é skid parado
            "reles": await asyncio.gather(*(um(r) for r in protecao)),
            "nota": ("comunica=false: o meuWatt não lê o relé há 15 min ou mais, o estado dele é DESCONHECIDO (não diga "
                     "que está ligado, desligado ou sem trip); comunica=null: não conferido. As três fases perto de zero "
                     "= sem tensão; UMA fase zerada com as outras normais = a MEDIÇÃO (veja leituras_que_pedem_atencao, "
                     "e ja_sei = a equipe já sabe: diga que é conhecido). 'disparou' e depois 'limpou' = "
                     "a bandeirola sumiu; confira na geração se o skid parou. trips nulo = não consegui ler o histórico. "
                     "Funções pelo código ANSI do relé (86, 27, 47…).")}

async def diagnostico_usina(ctx: Contexto, a: dict) -> dict:
    """A CAUSA do que parou hoje (dono, 13/11/2026: "pesquisar o motivo no helper … uma matriz"): a mesma régua da
    varredura de rotina (`services/diagnostico.py`), com a leitura ao vivo pelo helper para quem o tem. Com `codigo`,
    só a explicação da função de proteção pela matriz."""
    from dataclasses import asdict

    from app.api.v1.paradas import ParadasOut, ler_do_detector
    from app.services import diagnostico, matriz

    if a.get("codigo"):
        item = matriz.do_codigo(str(a["codigo"]))
        return asdict(item) if item else {"erro": f"O código {a['codigo']} não está na matriz de diagnóstico."}
    u = _usina(ctx, a.get("usina"))
    dia = hoje().isoformat()
    linhas = await ler_do_detector(ctx.mw, u["id"], ParadasOut(recorte="dia", inicio=dia, fim=dia))
    info: dict = {}
    achados = await diagnostico.diagnosticar(ctx.mw, u, linhas, info=info)
    if "bot_helper" in ctx.user.bot_ativo:
        from app.services.assistente_helper import _cliente
        try:
            await diagnostico.com_helper(_cliente(ctx, ctx.user), u["slug"], achados)
        except Exception:                                 # noqa: BLE001 (sem o helper, fica o que o meuWatt disse)
            pass
    return {"usina": u["nome"], "achados": [x.para_ia() for x in achados], **(await dado_de_hoje(ctx, u["slug"])),
            **_conhecidos(await conhecidos_abertos(ctx, u)),
            **({"nao_sao_parada": info["nao_paradas"]} if info.get("nao_paradas") else {}),
            "nota": (("Relés com a comunicação NÃO conferida agora: " + ", ".join(info["nao_conferidos"])
                      + " (nenhum equipamento da usina mandou leitura há pouco: não diga que estão ok nem que não há "
                      "relé mudo neles). " if info.get("nao_conferidos") else "")
                     + "Lista vazia = nenhum trip, parada, relé mudo ou fase zerada HOJE"
                     + (" nos relés conferidos" if info.get("nao_conferidos") else "")
                     + " (não quer dizer que a usina gerou bem: veja `geracao`). "
                     + ("`nao_sao_parada` = o que o detector marcou e a verificação do meuWatt (a matriz R0–R9) julgou "
                        "NÃO parada (nuvem ou fim de tarde, falha de comunicação ou para avaliar): não chame de parada, "
                        "diga o veredito. " if info.get("nao_paradas") else "")
                     + "'Helper agora' é a leitura ao vivo do "
                     "equipamento. `ja_sabido` = alguém "
                     "marcou «já sei» na tela Leituras do meuWatt: diga que é conhecido, com a observação, e que o aviso "
                     "não sai; não trate como novidade.")
            + (" A tela Leituras do meuWatt NÃO respondeu agora: relé mudo e fase zerada saíram da regra de reserva, "
               "sem o «já sei» de lá (diga isso se falar deles)." if info.get("leituras") == "reserva" else "")}


async def relatorio_pdf(ctx: Contexto, a: dict) -> dict:
    from app.clients import whatsapp
    tipo = {"executivo": "resumo", "resumo_executivo": "resumo"}.get((a.get("tipo") or "geracao").lower(),
                                                                    (a.get("tipo") or "geracao").lower())
    if tipo not in ("geracao", "paradas", "resumo"):
        raise Recusa("tipo deve ser geracao, paradas ou resumo.")
    u = _usina(ctx, a.get("usina"))
    rel = await ctx.mw.relatorio_existente(u["slug"], "MENSAL", date.fromisoformat(f"{a['mes']}-01"))
    if not rel:
        if tipo != "resumo":       # a equipe ainda não emitiu: vai o NÃO REVISADO, com a marca (o Renan, 11/11/2026)
            return await _relatorio_nao_revisado(ctx, u, a["mes"], tipo)
        return {"erro": f"Não há relatório mensal de {a['mes']} emitido para {u['nome']}."}
    arq = next((f for f in rel.get("files") or [] if f.get("kind") == tipo), None)
    if arq is None:
        return {"erro": f"O relatório de {a['mes']} não tem o arquivo '{tipo}'."}
    raw = await ctx.mw.arquivo_relatorio(rel["id"], tipo)
    nome = arq.get("filename") or f"{tipo}-{u['slug']}-{a['mes']}.pdf"
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="document", arquivo=raw, filename=nome,
                                       mime="application/pdf", texto=nome)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(nome)
    return {"arquivo": nome, "enviado_no_chat": ok, "erro": None if ok else (r or {}).get("erro")}


async def _relatorio_nao_revisado(ctx: Contexto, u: dict, mes: str, tipo: str) -> dict:
    """O mês sem relatório emitido pela equipe: o PDF NÃO REVISADO, gerado agora no meuWatt com o token DA PESSOA (o
    Renan, 11/11/2026: "somente quando pedir por WhatsApp ou bot … será enviado, porém, com marca 'relatório não
    revisado'"). O carimbo vai na capa e em toda folha; no de geração, os comentários da IA vão marcados como dela."""
    from app.clients import whatsapp
    from app.clients.helper_bot import relatorio_nao_revisado
    from app.core.config import get_settings
    from app.models.integracao import Produto
    from app.services.vinculos import SemConexao, token_do_cliente

    s = get_settings()
    try:
        token = token_do_cliente(ctx.db, ctx.user.id, Produto.MEUWATT, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"A equipe ainda não emitiu o relatório de {mes} de {u['nome']}, e a versão não revisada sai com o "
                        f"token do meuWatt da pessoa: {e}"}
    gerador = s.relatorio_pdf_url or s.helper_bot_url
    if not (gerador and s.helper_bot_chave and token):
        return {"erro": f"A equipe ainda não emitiu o relatório de {mes} de {u['nome']}, e a versão não revisada não "
                        "pode ser gerada agora."}
    if tipo == "geracao":          # leva alguns minutos quando a IA ainda não comentou o mês: avisa antes
        await whatsapp.enviar_conteudo(
            telefone=ctx.telefone, tipo="text",
            texto=f"⏳ O relatório de {mes} de {u['nome']} ainda não foi revisado pela equipe. Estou gerando a versão "
                  "NÃO REVISADA agora; leva uns 3 minutos.")
    raw, nome, erro = await relatorio_nao_revisado(gerador, s.helper_bot_chamador, s.helper_bot_chave,
                                                   token, u["slug"], mes, tipo)
    if raw is None:
        return {"erro": f"A equipe ainda não emitiu o relatório de {mes} de {u['nome']}, e não consegui gerar a versão "
                        f"não revisada: {erro}"}
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="document", arquivo=raw, filename=nome,
                                       mime="application/pdf", texto=f"⚠️ RELATÓRIO NÃO REVISADO · {nome}")
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(nome)
    return {"arquivo": nome, "enviado_no_chat": ok, "nao_revisado": True,
            "erro": None if ok else (r or {}).get("erro"),
            "nota": "Diga com destaque que este relatório NÃO FOI REVISADO pela equipe: foi gerado agora, a pedido, e os "
                    "comentários escritos pela IA não foram conferidos. A versão revisada substitui esta quando sair."}


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def excel_energia_diaria(ctx: Contexto, a: dict) -> dict:
    """O Excel do meuWatt (dia × inversor, aba por skid, Geral e Validação) como ARQUIVO no chat,
    com o veredito da validação contra a plataforma do inversor — o mesmo que a aba Relatório mostra."""
    from app.clients import whatsapp
    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo(a.get("inicio") or hoje().replace(day=1).isoformat(), a.get("fim") or hoje().isoformat())
    raw, val = await ctx.mw.energia_diaria(u["slug"], ini, fim)
    nome = f"energia-diaria-{u['slug']}-{ini}-{fim}.xlsx"
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="document", arquivo=raw, filename=nome,
                                       mime=_XLSX, texto=nome)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(nome)
    return {"arquivo": nome, "enviado_no_chat": ok, "erro": None if ok else (r or {}).get("erro"),
            "validacao": val["validacao"], "mensagem_da_validacao": val["mensagem"],
            "nota": "Repasse a mensagem_da_validacao. Se validacao = revisar, diga com destaque que os dados "
                    "PRECISAM SER REVISADOS antes de usar (diferença acima de 0,5% com a plataforma do inversor)."}


def _conta_da_perda(memoria: list[dict] | None) -> dict:
    """De onde veio a perda do inversor, dia a dia, no texto do meuWatt (o dono, 17/11/2026: "preciso de memória para
    cada cálculo"): pares × kWp − o que produziu, ou PR × irradiância × kWp. Até 6 dias; o resto vira um aviso."""
    textos = [m["texto"] for m in memoria or [] if m.get("texto")]
    if not textos:
        return {}
    extra = [f"… e mais {len(textos) - 6} dia(s)"] if len(textos) > 6 else []
    return {"como_a_perda_foi_calculada": textos[:6] + extra}


async def resumo_executivo(ctx: Contexto, a: dict) -> dict:
    u = _usina(ctx, a.get("usina"))
    ex = await ctx.mw.resumo_executivo(u["slug"], a["mes"])
    c = ((ex or {}).get("latest_generation") or {}).get("content") or {}
    if not c and not (ex or {}).get("briefing"):
        return {"erro": f"Não há resumo executivo de {a['mes']} para {u['nome']}."}
    chaves = ("veredito_titulo", "veredito_texto", "destaque", "geracao", "eficiencia_texto", "disponibilidade",
              "perdas", "acoes")
    return {"usina": u["nome"], "mes": a["mes"], "observacao_da_om": ex.get("briefing"), **{k: c[k] for k in chaves if k in c}}


async def grafico(ctx: Contexto, a: dict) -> dict:
    from app.clients import whatsapp
    tipo = (a.get("tipo") or "geracao_diaria").lower()
    if tipo == "usinas":
        d = await comparar_usinas(ctx, a)
        pts = [(x["usina"], x.get("produtividade_kwh_kwp")) for x in d["usinas"] if x.get("produtividade_kwh_kwp") is not None]
        titulo, unid = f"Produtividade por usina · {d['inicio']} a {d['fim']}", "kWh/kWp"
    elif tipo == "irradiacao":
        d = await irradiacao(ctx, a)
        ds = d["dias"] if isinstance(d["dias"], list) else []
        k, unid = ("poa_estacao", "kWh/m² (POA, estação)") if d["tem_estacao"] else ("ghi_satelite", "kWh/m² (GHI, satélite)")
        pts = [(_dm(x["data"]), x[k]) for x in ds if x[k] is not None]
        titulo = f"{d['usina']} · irradiação · {_periodo_br(d['inicio'], d['fim'])}"
    else:
        d = await geracao(ctx, a)
        ds = d["dias"] if isinstance(d["dias"], list) else []
        if tipo == "inversores":
            pts, unid = [(i["inversor"], i["produtividade_kwh_kwp"]) for i in d["inversores_do_melhor_ao_pior"]
                         if i["produtividade_kwh_kwp"] is not None], "kWh/kWp"
        elif tipo == "pr_diario":
            pts, unid = [(_dm(x["data"]), x["pr_pct"]) for x in ds if x["pr_pct"] is not None], "PR %"
        else:
            pts, unid = [(_dm(x["data"]), x["energia_kwh"]) for x in ds if x["energia_kwh"] is not None], "kWh"
        o_que = {"kWh": "energia por dia", "PR %": "PR por dia", "kWh/kWp": "produtividade por inversor"}[unid]
        titulo = f"{d['usina']} · {o_que} ({unid}) · {_periodo_br(d['inicio'], d['fim'])}"
    if not pts:
        return {"erro": "Sem dados no período para desenhar."}
    velhos = ([f"{x['usina']} até {x.get('dado_do_meuwatt')}" for x in d.get("usinas") or [] if x.get("aviso")]
              if tipo == "usinas" else [f"dado até {_hora(d['agora'].get('dado_de'))}"]
              if (d.get("agora") or {}).get("aviso") else [])
    if velhos:                                            # o gráfico de hoje com dado velho diz de quando é
        titulo += " · " + ", ".join(velhos)
    png = await asyncio.to_thread(_desenhar, pts, titulo, unid)
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=png, filename="grafico.png",
                                       mime="image/png", texto=titulo)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(titulo)
    mx, mn = max(pts, key=lambda p: p[1]), min(pts, key=lambda p: p[1])
    # o texto que acompanha o gráfico tem números (a avaliação de 17/11/2026: barras de energia e nenhum número)
    tot = sum(v for _r, v in pts)
    return {"grafico": titulo, "enviado_no_chat": ok, "unidade": unid, "maior": [mx[0], _arred(mx[1])],
            "menor": [mn[0], _arred(mn[1])],
            **(({"total_mwh": round(tot / 1000, 1)} if tot >= 10_000 else {"total": _arred(tot)}) if unid == "kWh"
               else {"media": _arred(tot / len(pts))}),
            **({"aviso": "Dado velho do meuWatt: " + ", ".join(velhos) + ". Diga isso junto dos números."} if velhos else {}),
            "nota": "Comente com 1 a 3 números: o total (ou a média), o melhor e o pior; datas em dd/mm."}


def _hora(iso: str | None) -> str:
    from app.core.datas import hora_brt
    return hora_brt(iso)


def _arred(v: float) -> float:
    """Sem precisão falsa: 21.239,5 kWh vira 21.240; 82,37 % fica 82,4."""
    return round(v) if abs(v) >= 100 else round(v, 1) if abs(v) >= 10 else round(v, 2)


def _dm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def _periodo_br(ini: str, fim: str) -> str:
    """"2026-11-01", "2026-11-17" → "01/11 a 17/11/2026" (a data do Brasil no título, nunca a ISO)."""
    a, b = date.fromisoformat(str(ini)[:10]), date.fromisoformat(str(fim)[:10])
    return f"{a:%d/%m/%Y}" if a == b else f"{a:%d/%m} a {b:%d/%m/%Y}"


def _milhar(ax) -> None:
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _p: f"{v:,.0f}".replace(",", ".") if abs(v) >= 100 else f"{v:g}".replace(".", ",")))


def _desenhar_grupos(rot: list[str], series: dict[str, list[float | None]], titulo: str, unid: str) -> bytes:
    """Barras lado a lado por grupo (o balanço: inversores × medidor × conta em cada skid), com o valor em cima."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cores = ["#F5B700", "#2E86AB", "#6C757D"]
    fig, ax = plt.subplots(figsize=(10, 5), dpi=110)
    larg = 0.8 / max(1, len(series))
    for i, (nome, vals) in enumerate(series.items()):
        xs = [j + (i - (len(series) - 1) / 2) * larg for j in range(len(rot))]
        barras = ax.bar(xs, [v or 0 for v in vals], larg, label=nome, color=cores[i % len(cores)])
        for b, v in zip(barras, vals):
            ax.annotate("sem dado" if v is None else f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."),
                        (b.get_x() + b.get_width() / 2, b.get_height()), ha="center", va="bottom", fontsize=7,
                        rotation=90 if len(rot) > 6 else 0)
    ax.set_xticks(range(len(rot)))
    ax.set_xticklabels(rot, fontsize=9)
    ax.set_ylabel(unid)
    _milhar(ax)
    ax.set_title(titulo, fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _desenhar(pts: list[tuple[str, float]], titulo: str, unid: str) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rot, val = zip(*pts)
    fig, ax = plt.subplots(figsize=(10, 5), dpi=110)
    ax.bar(range(len(val)), val, color="#F5B700")
    ax.set_xticks(range(len(rot)))
    ax.set_xticklabels(rot, rotation=60 if len(rot) > 8 else 0, ha="right" if len(rot) > 8 else "center", fontsize=8)
    ax.set_ylabel(unid)
    _milhar(ax)
    ax.set_title(titulo, fontsize=11)
    ax.grid(axis="y", alpha=.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------------------- balanço de energia
# O dono, 17/11/2026: os inversores de cada skid × o "medidor particular" × a conta, com as perdas, o parecer e o
# gráfico, em mês fechado ou período livre. A conta e o parecer moram no meuWatt (`GET /plants/{slug}/energy-balance`, a
# mesma da aba "Balanço" do Excel de energia diária e do conector do Claude); aqui ficam o período, o gráfico e o que
# cabe a quem pergunta: só o gestor manda conta ("jamais o cliente pode enviar algo, eu gestor sim").
def _fim_do_mes(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _periodo_balanco(a: dict) -> tuple[date, date]:
    """O mês fechado (`mes`) ou o período livre (`inicio`/`fim`); sem nada, o mês até hoje."""
    if a.get("mes") and not a.get("inicio"):
        try:
            ini = date(*(int(x) for x in str(a["mes"]).split("-")[:2]), 1)
        except (TypeError, ValueError):
            raise Recusa("Mês no formato AAAA-MM.") from None
        if ini > hoje():
            raise Recusa("Esse mês ainda não começou.")
        return ini, min(_fim_do_mes(ini), hoje())
    return _periodo(a.get("inicio") or hoje().replace(day=1).isoformat(), a.get("fim") or hoje().isoformat())


async def balanco_energia(ctx: Contexto, a: dict) -> dict:
    from app.clients import whatsapp
    from app.models.user import Perfil
    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo_balanco(a)
    b = await ctx.mw.balanco_energia(u["slug"], ini, fim)
    parecer = list(b.get("parecer") or [])
    if getattr(ctx.user, "perfil", None) == Perfil.GESTOR_EMPRESA and any(
            p["texto"].startswith("Falta a conta") for p in parecer):
        parecer.append({"tom": "info", "texto": "Se tiver o PDF da conta, mande por aqui: eu leio, mostro a prova e só "
                                                "gravo com o seu Sim."})
    linhas = b.get("skids") or []
    ini, fim = date.fromisoformat(b["inicio"]), date.fromisoformat(b["fim"])
    grafico = None
    if a.get("grafico", True) and linhas:
        series = {n: [None if x[k] is None else x[k] / 1000 for x in linhas]
                  for n, k in (("Inversores", "inversores_kwh"), ("Medidor", "medidor_kwh"), ("Conta", "conta_kwh"))}
        series = {n: v for n, v in series.items() if any(x is not None for x in v)}
        grafico = f"{u['nome']} · {' × '.join(n.lower() for n in series)} por skid · {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
        png = await asyncio.to_thread(_desenhar_grupos, [x["skid"] for x in linhas], series, grafico, "MWh")
        r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=png, filename="balanco.png",
                                           mime="image/png", texto=grafico)
        if r and r.get("ok"):
            ctx.enviados.append(grafico)
        else:
            grafico = None
    return {
        "usina": b.get("usina") or u["nome"], "periodo": f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}", "ate_agora": b.get("ate_agora"),
        "meses_com_conta": b.get("meses_com_conta"), "skids": linhas, "total": b.get("total"), "parecer": parecer,
        "grafico_enviado": grafico, "fontes": b.get("fontes"),
        "como_explicar": "Mande UMA tabela: Skid · Inversores (kWh) · Medidor (kWh) · Perda até o medidor (kWh e %) · "
                         "Conta (kWh) · Medidor − conta (kWh e %), com a linha Total; coluna sem dado = 'sem leitura' "
                         "(nunca zero); na linha com falta_dado, a perda é 'falta dado'. Depois o PARECER, um item por "
                         "linha, como veio (✅ ok, ⚠️ atenção, ❌ problema, ℹ️ info), sem outros números. O gráfico já "
                         "foi enviado (grafico_enviado). O mesmo balanço está na aba Balanço do Excel de energia diária.",
    }

# --------------------------------------------------------------------------- gêmeo digital
# O gêmeo mora no módulo de análise do meuWatt (analise.meuwatt.com.br, `ctx.mw.gemeo_*`, o token da pessoa). Dono,
# 06/11/2026: "faça o bot saber tudo dos gêmeos, qualquer pergunta que eu fizer ele responde".
COMO_EXPLICAR_GEMEO = (
    "Placar: o real × o PREVISTO pelo gêmeo (com o tempo que fez e os limites reais) × o PVsyst (ano típico), em MWh. "
    "Cascata, com os MESMOS nomes do relatório: Projeto (PVsyst) → Margem do modelo (cascata_mwh.regua: o gêmeo no "
    "MESMO ano típico do PVsyst, o que ele não reproduz) → Sol do mês (clima: o tempo que fez; gêmeo contra gêmeo) → "
    "Recuo (projeto) (geometria: com o sol baixo o tracker gira o painel de volta para não sombrear a fileira de trás; "
    "o PDF do PVsyst simulou outro painel ou outras fileiras que a usina construída — geometria.pdf × geometria.construida; "
    "some quando o PVsyst é refeito com a construída) → Teto de potência (limitacao: a potência máxima real dos "
    "inversores e da usina × a do projeto; conta nas horas de sol forte) → ESPERADO (o previsto). Real − esperado = a "
    "USINA: Recuo a mais (recuo_a_mais: o controlador do tracker recua com medidas gravadas erradas — "
    "geometria.controlador × geometria.construida; corrige-se no controlador) → sol no plano (o sensor INCLINADO, no plano dos módulos, × o "
    "ESPERADO = o sensor DEITADO da estação levado ao plano dos módulos com o tracker na posição certa; diga 'o esperado "
    "pela conta do sensor deitado', nunca 'o que o tempo permitia'. A conta é uma FAIXA: Perez, o modelo do PVsyst, e "
    "isotrópico (sol_kwh_m2 e cascata_mwh trazem as duas pontas); no tracker os modelos discordam até ~6 pontos no mês. "
    "Quem decide é sol_no_plano_situacao (o mesmo que a tela mostra; NUNCA compare os números você mesmo): dentro = não "
    "dá para afirmar que faltou sol; abaixo = faltou sol no plano (tracker, sombra ou o sensor); sensor_mede_baixo = o "
    "sensor inclinado mede baixo (sujeira ou calibração), não os módulos — a usina gerou o esperado; acima; sem_sensor = "
    "a usina não tem sensor no mês: o sol veio da estação do INMET mais perto — medida, mas longe da usina — ou do "
    "satélite (fonte_do_sol diz qual), no_plano_medido é conta e não medida, e o degrau não diz nada), paradas e conversão (o resto: sujeira, módulos, inversores, trackers que o sensor "
    "não vê). parte_clima_pct = quanto da diferença para o PVsyst foi o tempo. hora_a_hora.leitura já traz o padrão "
    "(perda que cresce com o sol direto → posição de tracker, sombra ou temperatura: hipótese, quem prova a posição é o "
    "ângulo dos controladores; parecida com sol e nuvem → sujeira; um inversor que descola). Números só daqui; None = sem dado.")


async def _gemeo_ler(ctx: Contexto, u: dict, chamada: Any) -> Any:
    try:
        return await chamada
    except httpx.HTTPStatusError as e:
        st = e.response.status_code
        if st == 404:
            try:
                com = [x["nome"] for x in await ctx.mw.gemeos()]
            except Exception:                             # noqa: BLE001 — a lista é só um agrado na frase
                com = []
            raise Recusa(f"{u['nome']} não tem gêmeo digital" + (f" (têm: {', '.join(com)})." if com else ".")) from None
        if st in (401, 403):
            raise Recusa("O gêmeo digital mora no módulo de análise do meuWatt, que é só da equipe da plataforma: o "
                         "seu login do meuWatt não tem acesso a ele.") from None
        raise


def _mes_gemeo(mes: str | None) -> str:
    try:
        ano, m = (int(x) for x in (mes or hoje().strftime("%Y-%m")).split("-"))
        d = date(ano, m, 1)
    except ValueError:
        raise Recusa("Mês no formato AAAA-MM.") from None
    if d > hoje():
        raise Recusa("Esse mês ainda não começou.")
    return d.strftime("%Y-%m")


def _fonte_do_sol(f: dict) -> dict:
    """De onde veio o sol do mês e a margem de erro dele — a decisão é do módulo (`fonte_sol`), como no relatório."""
    m = f.get("margens") or {}
    nome = {"estacao": lambda x: "estação solarimétrica da usina",
            "inmet": lambda x: f"estação do INMET em {x.get('cidade')} ({x.get('codigo')}, a {x.get('km')} km da usina)",
            "open-meteo": lambda x: f"satélite: {x.get('nome')}"}
    return {"fontes": [{"fonte": nome[x["tipo"]](x), "dias": x["dias"], "margem_pct": x["margem_pct"]} for x in f.get("fontes") or []],
            "margem_de_erro_do_mes_pct": f.get("margem_pct"), "dentro_da_margem": f.get("dentro_da_margem"),
            "como_ler": (f"Margem = o quanto o sol pode errar no mês: estação da usina ±{m.get('estacao')}%, INMET "
                         f"±{m.get('inmet')}%, satélite ±{m.get('open-meteo')}% (o maior erro de mês medido trocando a estação "
                         "de Ibitinga e a de Porto Ferreira pela de fora); a do mês é a média pelos dias. dentro_da_margem = "
                         "o desvio da usina não passa dela: não afirme que a usina gerou mal, diga que está dentro da margem.")}


def _dias_tratados(s: dict) -> dict | None:
    """Os dias que a equipe tratou na tela do gêmeo (o sol escolhido ou informado, a energia completada ou informada, o
    dia fora da conta) — o relatório imprime os mesmos."""
    ts = s.get("tratamentos") or []
    if not ts:
        return None
    o_que = lambda t: (["fora da conta"] if t.get("descartar") else [  # noqa: E731
        *([f"sol informado à mão ({t.get('sol_kwh_m2')} kWh/m²)"] if t.get("sol") == "manual" else
          ["sol do satélite"] if t.get("sol") == "satelite" else
          [f"sol da estação do INMET {t['sol'][6:]}"] if (t.get("sol") or "").startswith("inmet:") else []),
        *(["energia dos inversores sem dado completada pelos outros do dia"] if t.get("energia") == "completar" else
          [f"energia informada à mão ({t.get('energia_kwh')} kWh)"] if t.get("energia") == "manual" else [])])
    return {"dias": [{"dia": t["dia"], "o_que": o_que(t), "motivo": t.get("motivo"), "aviso": t.get("aviso")} for t in ts],
            "dias_na_conta": s.get("dias_na_conta"), "dias_do_mes": s.get("dias_do_mes"),
            "como_ler": "Os números do mês já são só dos dias na conta; o projeto (PVsyst) e a régua entram na mesma proporção "
                        "dos dias. Diga quais dias foram tratados e por quê."}


async def gemeo(ctx: Contexto, a: dict) -> dict:
    """O mês no gêmeo digital: foi o clima ou a usina? (placar, cascata, dia a dia, hora a hora, inversores, limites)."""
    u = _usina(ctx, a.get("usina"))
    mes = _mes_gemeo(a.get("mes"))
    d = await _gemeo_ler(ctx, u, ctx.mw.gemeo_mes(u["id"], mes))
    s, f, hh, lim = d["resumo"], d.get("ficha") or {}, d.get("hora_a_hora") or {}, d.get("limites") or {}
    rot = {i["sn"]: i.get("rotulo") or i["sn"] for i in d.get("inversores") or []}
    ultimo = next((x for x in reversed(lim.get("dias") or []) if any(v.get("comando_kw") for v in x["inversores"].values())),
                  (lim.get("dias") or [None])[-1])
    paradas = d.get("paradas")
    return {
        "usina": u["nome"], "mes": mes, "estacao": d.get("estacao"),
        "fonte_do_sol": _fonte_do_sol(s.get("fonte_sol") or {}),
        "dias_tratados": _dias_tratados(s),
        "modelo": f"módulo {f.get('modelo_modulo')}; inversor {f.get('modelo_inversor')}",
        "geometria": {"do_pdf": f.get("geometria"), "pdf": f.get("geometria_pdf"), "construida": f.get("geometria_real"),
                      "controlador": f.get("geometria_controlador")},
        "placar_mwh": {"real": s["real_mwh"], "previsto_pelo_gemeo": s["previsto_mwh"], "pvsyst": s["pvsyst_mwh"],
                       "gemeo_no_ano_tipico_regua": s.get("regua_mwh")},
        "usina_x_previsto_pct": s["desvio_previsto_pct"],
        "cascata_mwh": {"regua": s.get("efeito_regua_mwh"), "clima": s["efeito_clima_mwh"],
                        "geometria": s.get("efeito_geometria_mwh"),
                        # o desgaste dos módulos pela garantia, além do que o PDF já desconta (mw-analise fator_desgaste)
                        "desgaste_dos_modulos": s.get("efeito_desgaste_mwh"), "desgaste": s.get("desgaste"),
                        "limitacao": s["efeito_limitacao_mwh"],
                        "recuo_a_mais": s.get("efeito_trackers_mwh"),
                        "sol_no_plano": s["efeito_plano_mwh"], "sol_no_plano_pelo_isotropico": s.get("efeito_plano_iso_mwh"),
                        "paradas": s.get("efeito_paradas_mwh"),
                        # o inversor sem gerar com sol num dia inteiro que o detector não contou (parado ou sem comunicação),
                        # pelo rendimento dele nos outros dias: sai da conversão (mw-analise paradas_pelo_gemeo)
                        "paradas_pelo_gemeo": s.get("efeito_paradas_gemeo_mwh"),
                        "paradas_pelo_gemeo_inversor_dias": (s.get("paradas_gemeo") or {}).get("inversor_dias"),
                        "conversao": s["efeito_conversao_mwh"],
                        "usina_total": s["efeito_usina_mwh"]},
        "parte_clima_pct": s["parte_clima_pct"],
        "incerteza_regua": {"pct": s["incerteza_regua_pct"], "mwh": s["incerteza_regua_mwh"]},
        "sol_kwh_m2": {"no_plano_medido": s["poa_real"], "no_plano_esperado": s["poa_tempo"],
                       "no_plano_com_o_recuo_do_controlador": s.get("poa_trackers"), "no_plano_esperado_isotropico": s.get("poa_tempo_iso"),
                       "sol_no_plano_situacao": s.get("sol_no_plano_situacao"), "pvsyst": s["poa_pvsyst"],
                       "horizontal": s["ghi_real"], "horizontal_pvsyst": s["ghi_pvsyst"]},
        "temperatura_media_c": {"real": s["t_amb_media"], "pvsyst": s["t_amb_pvsyst"]},
        "pr": {"real": s["pr_real"], "pvsyst": s["pr_pvsyst"]}, "corte_nos_limites_mwh": s["corte_mwh"],
        "hora_a_hora": {
            "leitura": hh.get("leitura"),
            "por_hora_fora_do_limite_pct": {p["hora"]: p["pct_fora_limite"] for p in hh.get("perfil") or []
                                            if p.get("pct_fora_limite") is not None},
            "rendimento_por_dia_pct": [{"dia": x["dia"][8:], "pct": x["pct"], "chuva_mm": x["chuva_mm"]}
                                       for x in hh.get("rendimento") or [] if x.get("pct") is not None],
            "nota": "real ÷ gêmeo com o sol MEDIDO no plano (só a conversão), fora das horas em que o gêmeo está no limite"},
        "dias": [{"dia": x["dia"][8:], "previsto_kwh": x["previsto_kwh"], "real_kwh": x["real_kwh"], "desvio_pct": x["desvio_pct"],
                  "sol_kwh_m2": x["poa"], "corte_kwh": x["corte_kwh"], "paradas": x.get("paradas_n")}
                 for x in d.get("dias") or [] if x.get("real_kwh") or x.get("previsto_kwh")],
        "inversores": [{"inversor": rot[i["sn"]], "real_kwh": i["real_kwh"], "previsto_kwh": i["previsto_kwh"],
                        "desvio_pct": i["desvio_pct"], "paradas": i.get("paradas_n"), "paradas_kwh": i.get("paradas_kwh")}
                       for i in d.get("inversores") or []],
        "limites": {"usina_projeto_kw": lim.get("projeto_kw"), "usina_kw": lim.get("usina_configurado_kw"),
                    "teto_medido_usina_kw": lim.get("usina_teto_medido_kw"), "dias_travados": s.get("dias_travados"),
                    "por_inversor": None if not ultimo else [
                        {"inversor": rot.get(sn, sn), "limite_kw": v.get("limite_kw"), "comando_lido_kw": v.get("comando_kw"),
                         "fonte": v.get("fonte")} for sn, v in ultimo["inversores"].items()]},
        "paradas": None if paradas is None else {
            "n": (s.get("paradas") or {}).get("n"), "minutos": (s.get("paradas") or {}).get("minutos"),
            "maiores": [{"inversor": p["inversor"], "inicio": p["ini"][5:16].replace("T", " "), "minutos": p["minutos"],
                         "perda_kwh": p.get("perda_kwh")} for p in sorted(paradas, key=lambda p: -(p.get("perda_kwh") or 0))[:5]]},
        "como_explicar": COMO_EXPLICAR_GEMEO,
    }


async def gemeo_dia(ctx: Contexto, a: dict) -> dict:
    """Um dia no gêmeo, hora a hora: o previsto × o real, o sol medido no plano × o esperado, corte e paradas."""
    u = _usina(ctx, a.get("usina"))
    dia, _ = _periodo(a.get("dia"), None)
    d = await _gemeo_ler(ctx, u, ctx.mw.gemeo_dia(u["id"], dia.isoformat()))
    horas = [{"hora": h["hora"], "previsto_kwh": h["previsto_kwh"], "real_kwh": h["real_kwh"], "desvio_pct": h["desvio_pct"],
              "sol_medido_wh_m2": h["poa_wh"], "sol_esperado_wh_m2": h["poa_tempo_wh"], "t_amb_c": h["t_amb"],
              "t_celula_max_c": h["t_cel_max"], "corte_kwh": h["corte_kwh"], "paradas_kwh": h["paradas_kwh"]}
             for h in d.get("horas") or []]
    prev = sum(h["previsto_kwh"] or 0 for h in horas)
    real = sum(h["real_kwh"] or 0 for h in horas) if any(h["real_kwh"] is not None for h in horas) else None
    return {"usina": u["nome"], "dia": dia.isoformat(), "potencia_maxima_kw": d.get("kwac"),
            "total": {"previsto_kwh": round(prev), "real_kwh": None if real is None else round(real),
                      "desvio_pct": None if real is None or not prev else round((real / prev - 1) * 100, 1)},
            "horas": horas,
            "nota": "previsto = gêmeo com o tempo que fez e os limites reais, na rede; hora de hoje que não fechou vem "
                    "parcial; corte = o que os limites tiraram; sol medido (sensor inclinado) abaixo do esperado (o sensor "
                    "deitado levado ao plano com o tracker na posição certa) = tracker fora de posição, sensor sujo "
                    "ou torto, ou erro da conta"}


async def gemeo_regua(ctx: Contexto, a: dict) -> dict:
    """A régua: o gêmeo com o clima e as premissas do PVsyst contra o próprio PVsyst."""
    u = _usina(ctx, a.get("usina"))
    d = await _gemeo_ler(ctx, u, ctx.mw.gemeo_regua(u["id"]))
    r = d["regua"]
    return {"usina": u["nome"], "gravada_em": r.get("calculado_em"), "modelo": r.get("modelo"), "k": r["k"],
            "contraste_do_ano": r.get("contraste"), "contraste_ajustado_ao_corte_do_pvsyst": r.get("contraste_ajustado"),
            "ano_desvio_pct": r["ano_desvio_pct"],
            "meses": [{"mes": m["rotulo"], "pvsyst_mwh": m["pvsyst"]["e_grid_mwh"], "gemeo_mwh": m["gemeo"]["e_grid_mwh"],
                       "desvio_pct": m["desvio_pct"]} for m in r["meses"]],
            "diagrama_de_perdas": r.get("diagrama"),
            "variantes": [{k: v for k, v in x.items() if k not in ("meses_desvio_pct", "modelo")} for x in r.get("variantes") or []],
            "versoes": [{"gravada_em": x["calculado_em"], "em_vigor": x["em_vigor"], "ano_desvio_pct": x["ano_desvio_pct"],
                         "pior_mes_pct": x["pior_mes_pct"], "k": x["k"]} for x in d.get("versoes") or []],
            "nota": "A régua roda o gêmeo com o que o PVsyst usou: o clima mensal do PDF (não a estação) e os limites do "
                    "PROJETO (não os reais). Os únicos ajustes são k (fecha a energia no MPP do ano) e o contraste do ano "
                    "sintético (fecha o corte do inversor do diagrama); origem 'calculado' = o gêmeo chegou lá sozinho. "
                    "O desvio do mês é a incerteza da régua naquele mês."}


async def gemeo_config(ctx: Contexto, a: dict) -> dict:
    """O que o gêmeo sabe da usina: geometria, módulo (.PAN), inversor (.OND), perdas do PDF, limites e leituras."""
    u = _usina(ctx, a.get("usina"))
    d = await _gemeo_ler(ctx, u, ctx.mw.gemeo_config(u["id"]))
    c = d.get("cfg")
    if not c:
        raise Recusa(f"{u['nome']} não tem gêmeo digital.")
    ond = c.get("ond")
    return {"usina": u["nome"], "origem": d.get("origem"), "pdf": c.get("pdf"), "geometria": c.get("geometria"),
            "modulo": c.get("modulo"), "bifacial": c.get("bifacial"), "inversor_projeto": c.get("inversor"),
            "limite_de_rede_projeto_kw": c.get("limite_rede_kw"), "limites_reais": c.get("limites_reais"),
            "perdas_do_pdf_pct": c.get("perdas"), "sombra_eletrica": c.get("sombra_eletrica"),
            "energia_no_mpp_do_pvsyst_mwh": c.get("pvsyst_mpp_mwh"), "diagrama_do_pvsyst": c.get("diagrama"),
            "pan": c.get("pan"),
            "ond": None if not ond else {"arquivo": ond.get("arquivo"), "pnom_kw": ond.get("pnom_kw"), "pmax_kw": ond.get("pmax_kw"),
                                         "curvas": [{"tensao_v": x["v"], "eficiencia_max_pct": round(max(
                                             (o / i * 100 for i, o in zip(x["pin_kw"], x["pout_kw"]) if i > 0.5), default=0), 2)}
                                             for x in ond.get("curvas") or []]},
            "pvsyst_mensal": {"colunas": ["GlobHor", "DiffHor", "T_Amb", "GlobInc", "GlobEff", "EArray_MWh", "E_Grid_MWh"],
                              "meses": c.get("pvsyst")},
            "inversores": [{"inversor": i.get("rotulo") or i["sn"], "sn": i["sn"], "kwp": i.get("kwp"),
                            "comando_lido_kw": (i.get("leitura") or {}).get("comando_kw"),
                            "modo": (i.get("leitura") or {}).get("modo"),
                            "lido_em": (i.get("leitura") or {}).get("comando_lido_em")} for i in d.get("inversores") or []],
            "avisos": c.get("avisos")}


_TIPO_SERVICO = {"lavagem": "lavagem", "curva_iv": "curva IV", "termografia": "termografia", "ajuste_trackers": "ajuste dos trackers",
                 "troca_equipamento": "troca de equipamento", "inspecao": "inspeção", "outro": "outro"}
_RESULTADO = {"deu_bom": "deu bom", "parcial": "em parte", "nao_deu_bom": "não deu bom"}


def _da_lista(e: httpx.HTTPError) -> str:
    """Por que a lista de problemas conhecidos do Gêmeos não veio (nunca uma lista vazia que parece "nenhum")."""
    st = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
    return ("sem acesso: a lista do Gêmeos é da equipe da plataforma" if st in (401, 403) else
            "esta usina não tem gêmeo digital, onde a lista mora" if st == 404 else
            f"o módulo de análise recusou ({st})" if st else "o módulo de análise não respondeu agora")


async def problemas_conhecidos(ctx: Contexto, a: dict) -> dict:
    """Os PROBLEMAS CONHECIDOS da usina no meuWatt (o Renan, 25/11/2026: "pendências é um termo do meuPlano … para o
    meuWatt quero outro nome"): a lista do Gêmeos (o problema, os serviços feitos com a OS do meuPlano e se deu
    resultado; 07/11: "isso vira uma caixa de conteúdo para a própria IA usar") e os «já sei» da tela Leituras."""
    u = _usina(ctx, a.get("usina"))
    out: dict[str, Any] = {"usina": u["nome"]}
    try:
        ps = await ctx.mw.gemeo_pendencias(u["id"])
        out["lista_do_gemeo"] = [
            {"titulo": p["titulo"], "situacao": p["status"], "problema": p.get("problema") or None,
             "de_onde_veio": p.get("origem") or None, "criado_em": (p.get("criada_em") or "")[:10],
             "servicos": [{"servico": _TIPO_SERVICO.get(s["tipo"], s["tipo"]), "o_que_foi_feito": s.get("descricao") or None,
                           "os_meuplano": s.get("os_meuplano"), "feito_em": s.get("feito_em"),
                           "deu_resultado": _RESULTADO.get(s.get("resultado") or "", "não anotado"),
                           "anotacao": s.get("anotacao") or None} for s in p.get("servicos") or []]}
            for p in ps or []]
    except httpx.HTTPError as e:
        out["lista_do_gemeo"] = _da_lista(e)
    ja_sei: list[str] = []
    try:
        for r in (await ctx.mw.leituras(u["slug"])).get("relays") or []:
            for x in r.get("readings") or []:
                if (m := x.get("mark") or {}).get("ignored") or m.get("note"):
                    ja_sei.append(f"{r.get('name')} · {x.get('label') or x.get('key')}: "
                                  + ("já sei" if m.get("ignored") else "observação") + (f" ({m['note']})" if m.get("note") else ""))
    except httpx.HTTPError:
        ja_sei.append("as leituras dos relés não responderam agora")
    strings = await _strings_por_inversor(ctx, u["slug"], hoje())
    if isinstance(strings, str):
        ja_sei.append(strings)
    else:
        ja_sei += [f"{i.get('label')} · {texto_da_string(x)}" for i in strings.values() for x in i.get("strings") or []
                   if (x.get("mark") or {}).get("ignored") or (x.get("mark") or {}).get("note")]
    out["ja_sei_nas_leituras"] = ja_sei
    out["nota"] = ("O que a equipe já conhece: diga que é sabido. O antes × depois de cada serviço o gêmeo mede na tela "
                   "Gêmeos › Problemas conhecidos. Pendência é outra coisa (do meuPlano: `manutencao`).")
    return out


async def conhecidos_abertos(ctx: Contexto, u: dict) -> list[str] | None:
    """Os problemas conhecidos ABERTOS da usina (a lista do Gêmeos), para toda leitura sobre ela levar o que a equipe já
    sabe (o Renan, 25/11/2026: "o BOT sempre vai olhar esses problemas conhecidos antes de dar a resposta"). Sem acesso
    ou sem gêmeo: None (quem não vê a lista não a recebe)."""
    try:
        ps = await ctx.mw.gemeo_pendencias(u["id"])
    except Exception:  # noqa: BLE001 — é contexto: a lista que não veio não derruba a resposta sobre a usina
        return None
    return [p["titulo"] + (f": {p['problema']}" if p.get("problema") else "")
            for p in ps or [] if p.get("status") == "aberta"][:10]


def _conhecidos(k: list[str] | None) -> dict:
    return {"problemas_conhecidos": k, "nota_conhecidos": NOTA_CONHECIDOS} if k else {}


NOTA_CONHECIDOS = ("`problemas_conhecidos`: o que a equipe já sabe desta usina. O que você for apontar e já estiver ali, "
                   "diga que é conhecido.")


async def registrar_problema_conhecido(ctx: Contexto, a: dict) -> dict:
    """AÇÃO (com Sim): um problema conhecido novo na lista do Gêmeos do meuWatt, com as palavras da pessoa (o Renan,
    25/11/2026: "o bot vai receber os problemas conhecidos e cadastrar"). Gravado com o token DELA (lá, só a equipe da
    plataforma e quem opera a usina cadastram); o mesmo título aberto não duplica."""
    from app.services import assistente_helper as helper
    from app.services.vinculos import cliente_meuwatt

    u = _usina(ctx, a.get("usina"))
    titulo, problema = (a.get("titulo") or "").strip()[:200], (a.get("problema") or "").strip()
    if not titulo:
        raise Recusa("Falta o problema em poucas palavras (o título): pergunte.")
    pid, nome, origem = int(u["id"]), u["nome"], f"bot do WhatsApp · {ctx.user.apelido}"

    async def executar(db, user, telefone: str) -> str:
        return await _registrar(cliente_meuwatt(db, user.id, so_proprio=True), pid, nome, titulo, problema, origem)

    return helper.propor(ctx, f"Registrar como problema conhecido no meuWatt ({nome}): {titulo}", 600, executar,
                         [f"Detalhe: {problema}" if problema else "Sem detalhe"], parte="bot_meuwatt", confirmacao="sim")


async def _registrar(mw, pid: int, nome: str, titulo: str, problema: str, origem: str) -> str:
    """Grava na lista do Gêmeos e diz o desfecho (o mesmo título ABERTO não duplica)."""
    try:
        if any(p.get("status") == "aberta" and _norm(p.get("titulo")) == _norm(titulo)
               for p in await mw.gemeo_pendencias(pid) or []):
            return f"✅ {titulo} ({nome}): já estava na lista de problemas conhecidos."
        await mw.gemeo_problema_criar(pid, titulo, problema, origem)
    except httpx.HTTPStatusError as e:
        st = e.response.status_code
        if st in (401, 403):
            return ("❌ No meuWatt, só quem opera a usina cadastra problema conhecido (quem acompanha só lê). Nada foi "
                    "gravado.")
        if st == 404:
            return f"❌ {nome} não tem gêmeo digital no meuWatt, onde a lista de problemas conhecidos mora. Nada foi gravado."
        return f"❌ O meuWatt recusou ({st}). Nada foi gravado."
    except httpx.HTTPError:
        return "⚠️ O meuWatt não respondeu: o problema PODE ter sido gravado. Confira em Gêmeos › Problemas conhecidos."
    return f"✅ Registrado como problema conhecido ({nome}): {titulo}."


# --------------------------------------------------------------------------- catálogo
_USINA = {"type": "string", "description": "Nome da usina (parcial, sem acento serve). Vazio só se houver uma."}
_INI = {"type": "string", "description": "Data inicial AAAA-MM-DD. Calcule a partir de HOJE: 'mês' = dia 1; "
                                         "'semana' = segunda-feira; 'hoje'/'até agora' = hoje."}
_FIM = {"type": "string", "description": "Data final AAAA-MM-DD (inclusive). Vazio = igual ao início."}
_MES = {"type": "string", "description": "Mês AAAA-MM."}


# ── Leituras: o "já sei" (dono, 14/11/2026: o bot avisou a fase A do Skid 3 de Pirapozinho, que ele já sabia) ──────
#: As leituras dos relés de proteção, na ordem da tela Leituras do meuWatt (a chave é a de lá).
LEITURAS_RELE = ["comm", "voltage_a", "voltage_b", "voltage_c", "current_a", "current_b", "current_c",
                 "active_power_a", "active_power_b", "active_power_c", "total_active_power", "reactive_power",
                 "frequency", "current_thd_a", "current_thd_b", "current_thd_c", "ct_ratio", "pt_ratio"]
_SITUACAO = {"ok": "ok", "zeroed": "zerada", "no_comm": "sem comunicação", "missing": "sem leitura",
             "not_read": "não lida (o relé não manda esta medida)", "blank": "vazia só na leitura de agora",
             "unknown": "não conferida"}


def _atencao(rele: dict) -> list[dict]:
    """O que pede atenção num relé, como a tela Leituras mostra: o problema (o relé mudo uma vez só, na comunicação),
    o não conferido e o que tem marcação."""
    linhas = rele.get("readings") or []
    if any(x.get("key") == "comm" and x.get("status") == "unknown" for x in linhas):
        # Sem conferir a comunicação, cada medida é "não conferida": um item só pelo relé (a tela faz o mesmo).
        linhas = [x for x in linhas if x.get("key") == "comm" or x.get("mark")]
    saida = []
    for x in linhas:
        st, m = x.get("status"), x.get("mark") or {}
        problema = st in ("zeroed", "missing", "unknown") or (st == "no_comm" and x.get("key") == "comm")
        if problema or m:
            saida.append({"leitura": x["key"], "rotulo": x.get("label"), "valor": x.get("value"), "unidade": x.get("unit"),
                          "situacao": _SITUACAO.get(st, st), "detalhe": x.get("detail"), "ja_sei": bool(m.get("ignored")),
                          "observacao": m.get("note"), "por": m.get("user_name")})
    return saida


def _o_rele(reles: list[dict], nome: str | None) -> dict:
    """O relé pelo nome ou pelo skid ("Skid 3", "TR-03", "relé geral"); ambíguo ou ausente = pergunta."""
    alvo = _norm(nome).replace("rele ", "").strip()
    if not alvo:
        raise Recusa("Qual relé? " + ", ".join(r.get("name") or "" for r in reles) + ".")
    def casa(r):
        nomes = {_norm(r.get("name")), _norm(r.get("name")).replace("rele ", ""), _norm(r.get("transformer_name"))}
        return alvo in nomes
    cands = [r for r in reles if casa(r)] or [r for r in reles if alvo in _norm(r.get("name"))]
    if len(cands) != 1:
        raise Recusa(("Mais de um relé casa" if cands else "Não achei o relé") + f" '{nome}': "
                     + ", ".join(f"{r.get('name')} ({r.get('transformer_name') or 'sem skid'})" for r in (cands or reles))
                     + ". Pergunte qual.")
    return cands[0]


async def leituras_usina(ctx: Contexto, a: dict) -> dict:
    """A tela Leituras do meuWatt: o que não está ok e o que alguém marcou "já sei" (a regra é de lá), dos relés de
    proteção e das strings dos inversores."""
    u = _usina(ctx, a.get("usina"))
    reles = (await ctx.mw.leituras(u["slug"])).get("relays") or []
    if a.get("rele"):
        reles = [_o_rele(reles, a["rele"])]
    saida = {"usina": u["nome"],
             "reles": [{"rele": r.get("name"), "skid": r.get("transformer_name"), "leituras": _atencao(r)} for r in reles],
             "nota": ("Só as leituras com problema ou com marcação (as outras estão ok). `ja_sei` = alguém marcou na tela "
                      "Leituras do meuWatt que o problema é conhecido: o aviso dela não sai. Para marcar ou tirar, "
                      "`marcar_leitura` (relé) e `marcar_strings` (strings de um inversor).")}
    if not a.get("rele"):
        strings = await _strings_por_inversor(ctx, u["slug"], hoje())
        saida["strings"] = strings if isinstance(strings, str) else [
            {"inversor": i.get("label"), "skid": i.get("transformer_name"), "strings": lista,
             **({"perda_kwh_hoje": _r(i["loss_kwh_day"])} if i.get("loss_kwh_day") else {})}
            for i in strings.values()
            if (lista := [SEM_DADO_DAS_STRINGS] if i.get("no_data") else [
                texto_da_string(x) for x in i.get("strings") or []
                if x.get("registered") and (x.get("status") in PROBLEMA_DA_STRING or x.get("mark"))])]
        hora = await dado_de_hoje(ctx, u["slug"])
        saida["strings_do_dia"] = (f"hoje, {hoje():%d/%m}: o dia ainda não fechou (vale até a última leitura do meuWatt"
                                   + (f", das {hora['dado_do_meuwatt']})" if hora.get("dado_do_meuwatt") else ")"))
        if hora.get("aviso"):
            saida["aviso"] = hora["aviso"]
    return saida


#: o estado de uma string que pede atenção, como a tela Leituras do meuWatt diz (a regra é de lá)
PROBLEMA_DA_STRING = {"zero": "zerada", "intermittent": "intermitente", "weak": "fraca"}
#: o inversor que o meuWatt marca `no_data`: sem leitura no dia OU com todas as entradas sem corrente (nunca "nenhuma")
SEM_DADO_DAS_STRINGS = ("sem leitura das strings no dia: o inversor não mandou dado ou todas as entradas estão sem "
                        "corrente (o inversor inteiro pode estar parado)")
NOTA_STRINGS = ("Inversor com string parada: diga qual, desde quando e o «já sei» da equipe (`strings_com_problema`). "
                "`energia_se_as_strings_gerassem_kwh` é o que ele geraria com elas (a perda é a que o meuWatt conta): "
                "perto da mediana (`desvio_da_mediana_se_as_strings_gerassem_pct`), o resto do inversor está ok. Se a "
                "equipe marcou «já sei» só numa parte (a string que falta por projeto), `energia_com_as_ja_sabidas_kwh` é "
                "o que ele geraria só com elas, e a perda que sobra é defeito para ver em campo.")


async def _strings_por_inversor(ctx: Contexto, slug: str, dia: date) -> dict[str, dict] | str:
    """Por número de série, o inversor da tela Leituras do meuWatt (`readings/strings`: as strings ligadas, o estado de
    cada uma pela regra de lá, a perda do dia e o «já sei» da equipe). Sem resposta, o motivo: quem compara diz que não
    leu as strings, nunca as esquece calado."""
    from app.services import assistente_series as series

    try:
        invs = await series._leituras_strings(ctx, slug, dia)
    except Exception as e:  # noqa: BLE001 — a comparação dos inversores não cai porque as strings não vieram
        return f"sem as strings do meuWatt agora ({type(e).__name__})"
    return {str(i["serial_number"]): i for i in invs} if invs else "sem as strings do meuWatt agora"


def texto_da_string(x: dict) -> str:
    """Uma string em palavras: a etiqueta, o estado, desde quando está zerada e o que a equipe marcou."""
    t = f"{x.get('tag') or 'PV' + str(x.get('number'))} {PROBLEMA_DA_STRING.get(x.get('status'), 'ok')}"
    if x.get("zero_since"):
        t += f" desde {date.fromisoformat(str(x['zero_since'])[:10]):%d/%m/%Y}" + (
            " ou antes" if x.get("zero_since_before_window") else "")
    m = x.get("mark") or {}
    if m.get("ignored"):
        t += " (a equipe marcou «já sei»" + (f": {m['note']})" if m.get("note") else ")")
    elif m.get("note"):
        t += f" (observação da equipe: {m['note']})"
    return t


def _strings_na_comparacao(inv: dict, kwh: float | None, kwp: float | None, med: float | None,
                           ini: date, fim: date) -> dict:
    """O que as strings explicam da geração do inversor. A regra e a perda são do meuWatt; aqui só a soma. Um dia: a
    energia mais a perda que o meuWatt conta das strings paradas. Vários dias: só com as strings zeradas o período
    todo, pela potência delas no cadastro (a perda do meuWatt é por dia)."""
    if inv.get("no_data"):
        return {"strings_sem_dado": SEM_DADO_DAS_STRINGS}
    ligadas = [x for x in inv.get("strings") or [] if x.get("registered")]
    ruins = [x for x in ligadas if x.get("status") in PROBLEMA_DA_STRING]
    if not ruins:
        return {}
    out: dict[str, Any] = {"strings_ligadas": len(ligadas), "strings_com_problema": [texto_da_string(x) for x in ruins]}
    zeradas = [x for x in ruins if x.get("status") == "zero"]
    if kwh is None or not zeradas:
        return out
    sabidas = [x for x in zeradas if (x.get("mark") or {}).get("ignored")]
    if ini == fim:
        if inv.get("loss_kwh_day") is None:
            return out
        com = kwh + inv["loss_kwh_day"]
        sabida = sum(x.get("loss_kwh_day") or 0 for x in sabidas)
        out.update(perda_das_strings_kwh=_r(inv["loss_kwh_day"]),
                   **({"perda_ja_sabida_kwh": _r(sabida)} if sabida else {}))
        com_sabidas = kwh + sabida if sabidas and len(sabidas) < len(zeradas) else None
    else:
        if any(not x.get("zero_since") or date.fromisoformat(str(x["zero_since"])[:10]) > ini for x in zeradas):
            return out
        todas = sum(x.get("kwp") or 0 for x in ligadas)
        gerando = todas - sum(x.get("kwp") or 0 for x in zeradas)
        if not gerando:
            return out
        com = kwh * todas / gerando
        out["como"] = (f"estimado pela potência das strings: {len(ligadas) - len(zeradas)} de {len(ligadas)} "
                       "gerando o período todo")
        com_sabidas = (kwh * (gerando + sum(x.get("kwp") or 0 for x in sabidas)) / gerando
                       if sabidas and len(sabidas) < len(zeradas) else None)
    out["energia_se_as_strings_gerassem_kwh"] = _r(com)
    if kwp and med:
        out["desvio_da_mediana_se_as_strings_gerassem_pct"] = _r((com / kwp / med - 1) * 100)
    if com_sabidas is not None:                           # só parte das paradas é conhecida: o resto é defeito
        out["energia_com_as_ja_sabidas_kwh"] = _r(com_sabidas)
        if kwp and med:
            out["desvio_da_mediana_com_as_ja_sabidas_pct"] = _r((com_sabidas / kwp / med - 1) * 100)
    return out


def _o_inversor(invs: list[dict], nome: str | None) -> dict:
    """O inversor da tela Leituras pelo nome falado ("inversor 13", "Inv 13", "13")."""
    alvo = _norm(nome)
    numeros = {int(x) for x in re.findall(r"\d+", alvo)}

    def numero(i: dict) -> int | None:                    # "Inv 13", "INV-013": um número só no rótulo
        achados = re.findall(r"\d+", _norm(i.get("label")))
        return int(achados[0]) if len(achados) == 1 else None

    cands = [i for i in invs if _norm(i.get("label")) == alvo] or [i for i in invs if numero(i) in numeros]
    if len(cands) != 1:
        raise Recusa(("Mais de um inversor casa" if cands else "Não achei o inversor") + f" '{nome or ''}': "
                     + ", ".join(i.get("label") or "" for i in (cands or invs)) + ". Pergunte qual.")
    return cands[0]


async def marcar_strings(ctx: Contexto, a: dict) -> dict:
    """O «já sei» (o X da tela Leituras do meuWatt) em strings de um inversor, com a observação: o "inversor 13 tem
    uma string a menos" do Renan (25/11/2026), que a comparação dos inversores passa a dizer, e o mesmo problema na
    lista dos problemas conhecidos do Gêmeos. Ação com o Sim, gravada com o token DA PESSOA (só a operação da usina
    marca lá). Sem `strings`, as que o meuWatt dá com problema; se a
    pessoa disse quantas e o meuWatt mede outro número, devolve a lista para ela escolher (nunca marca a mais)."""
    from app.core.datas import hora_brt
    from app.services import assistente_helper as helper
    from app.services.vinculos import cliente_meuwatt

    u = _usina(ctx, a.get("usina"))
    lido = await ctx.mw.strings_por_vaga(u["slug"])
    if not lido.get("can_mark"):                          # o papel da pessoa NESTA usina no meuWatt (o mesmo do PUT)
        raise Recusa("O seu papel nesta usina no meuWatt não marca leituras (só a operação). Nada foi feito.")
    inv = _o_inversor(lido.get("inverters") or [], a.get("inversor"))
    ligadas = {int(x["number"]): x for x in inv.get("strings") or [] if x.get("registered") and x.get("number") is not None}
    ruins = [n for n, x in ligadas.items() if x.get("status") in PROBLEMA_DA_STRING]
    pedidas = a.get("strings") or []
    if pedidas:
        numeros = []
        por_tag = {_norm(x.get("tag")).replace(" ", ""): n for n, x in ligadas.items() if x.get("tag")}
        for p in pedidas:
            if (n := por_tag.get(_norm(str(p)).replace(" ", ""))) is not None:
                numeros.append(n)
                continue
            achados = re.findall(r"\d+", str(p))
            if not achados or int(achados[-1]) not in ligadas:
                raise Recusa(f"A string '{p}' não está ligada no {inv.get('label')} no meuWatt. As ligadas: "
                             + ", ".join(x.get("tag") or str(n) for n, x in ligadas.items()) + ".")
            numeros.append(int(achados[-1]))
    else:
        # sem dizer quais: as ZERADAS (a string a menos lê zero); a fraca e a intermitente só ditas por nome
        numeros = [n for n in ruins if ligadas[n].get("status") == "zero"]
        if not numeros:
            raise Recusa(f"O meuWatt não mede string zerada no {inv.get('label')} hoje"
                         + (": com problema, " + "; ".join(texto_da_string(ligadas[n]) for n in ruins) if ruins else "")
                         + ". Pergunte qual string marcar (a etiqueta, ex.: 6S27).")
        quantas = a.get("quantas")
        quantas = int(quantas) if isinstance(quantas, str) and quantas.strip().isdigit() else quantas
        if isinstance(quantas, int) and not isinstance(quantas, bool) and quantas != len(numeros):
            raise Recusa(f"A pessoa falou em {quantas} string(s), e o meuWatt mede {len(numeros)} zerada(s) no "
                         f"{inv.get('label')}: " + "; ".join(texto_da_string(ligadas[n]) for n in numeros)
                         + ". Mostre e pergunte quais marcar (ou se são todas)."
                         + (" Diga também que, se só essa(s) falta(m) por projeto, a outra zerada é defeito para ver "
                            "em campo." if quantas < len(numeros) else ""))
    numeros = list(dict.fromkeys(numeros))
    ja_sei = a.get("ja_sei", True) is not False
    nova = (a.get("observacao") or "").strip() or None
    vence = None
    if ja_sei and a.get("dias") not in (None, ""):
        try:
            dias = int(a["dias"])
        except (TypeError, ValueError):
            raise Recusa("Não entendi o prazo: pergunte em dias (de 1 a 365).") from None
        if not 1 <= dias <= 365:
            raise Recusa("O prazo vai de 1 a 365 dias: pergunte de novo.")
        vence = (datetime.now(UTC) + timedelta(days=dias)).isoformat()
    tags = [ligadas[n].get("tag") or f"PV{n}" for n in numeros]
    onde = f"{inv.get('label')} · {' e '.join(tags) if len(tags) <= 2 else ', '.join(tags)} ({u['nome']})"
    resumo = f"Marcar «já sei» no meuWatt: {onde}" if ja_sei else f"Tirar o «já sei» no meuWatt: {onde}"
    detalhes = ["Agora: " + "; ".join(texto_da_string(ligadas[n]) for n in numeros),
                f"Observação: {nova}" if nova else "Sem observação nova (fica a que já existe)",
                (f"Vale até {hora_brt(vence)}." if vence else "Vale até alguém tirar.") if ja_sei
                else "A string volta a contar como problema."]
    slug, vaga = u["slug"], int(inv["slot_id"])

    async def executar(db, user, telefone: str) -> str:
        mw = cliente_meuwatt(db, user.id, so_proprio=True)
        try:                                              # o PUT troca a marcação inteira: relê a nota de agora
            agora = next((i for i in (await mw.strings_por_vaga(slug)).get("inverters") or []
                          if i.get("slot_id") == vaga), inv)
        except httpx.HTTPError:
            agora = inv
        marcas = {int(x["number"]): x.get("mark") or {} for x in agora.get("strings") or [] if x.get("number") is not None}
        feitas, falhas = [], []
        for n, tag in zip(numeros, tags):
            m = marcas.get(n) or {}
            try:
                await mw.marcar_leitura(slug, vaga, f"string_{n}", ja_sei, nova or m.get("note"),
                                        vence or (m.get("expires_at") if ja_sei else None), equipamento="inverter")
                feitas.append(tag)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403 and not feitas:
                    return "❌ O seu papel nesta usina no meuWatt não marca leituras (só a operação). Nada foi feito."
                falhas.append(f"{tag} (o meuWatt recusou: {e.response.status_code})")
            except httpx.HTTPError:
                falhas.append(f"{tag} (o meuWatt não respondeu: PODE ter sido gravada, confira na tela Leituras)")
        feito = "marcado «já sei»" if ja_sei else "«já sei» tirado"
        if not feitas:
            return "❌ Nada foi gravado: " + "; ".join(falhas) + "."
        texto = f"{inv.get('label')} · {' e '.join(feitas)} ({u['nome']}): {feito}" + (f". Observação: {nova}" if nova else "")
        texto = (f"⚠️ Feito EM PARTE. {texto}. Faltou: " + "; ".join(falhas) + ".") if falhas else f"✅ {texto}."
        if ja_sei:                                        # o problema contado entra também na lista dos conhecidos
            titulo = f"{inv.get('label')} · {' e '.join(feitas)}: {nova or 'string sem corrente, já sabido'}"[:200]
            texto += "\n" + await _registrar(mw, int(u["id"]), u["nome"], titulo, nova or "",
                                              f"bot do WhatsApp · {user.apelido} (o «já sei» da tela Leituras)")
        return texto

    return helper.propor(ctx, resumo, 600, executar, detalhes, parte="bot_meuwatt", confirmacao="sim")


async def marcar_leitura(ctx: Contexto, a: dict) -> dict:
    """O X ("já sei") e a observação de UMA leitura de um relé, na tela Leituras do meuWatt: ação com o Sim, gravada
    com o token DA PESSOA (o papel dela na usina decide lá)."""
    from app.core.datas import hora_brt
    from app.services import assistente_helper as helper
    from app.services.vinculos import cliente_meuwatt

    u = _usina(ctx, a.get("usina"))
    leitura = a.get("leitura")
    if leitura not in LEITURAS_RELE:
        raise Recusa(f"Leitura '{leitura}' não existe: use a chave de `leituras_usina` (ex.: voltage_a, comm).")
    ja_sei = a.get("ja_sei", True) is not False
    lido = await ctx.mw.leituras(u["slug"])
    if not lido.get("can_mark"):                          # o papel da pessoa NESTA usina no meuWatt (o mesmo do PUT)
        raise Recusa("O seu papel nesta usina no meuWatt não marca leituras (só a operação). Nada foi feito.")
    r = _o_rele(lido.get("relays") or [], a.get("rele"))
    linha = next((x for x in r.get("readings") or [] if x.get("key") == leitura), {})
    atual = linha.get("mark") or {}
    nova = (a.get("observacao") or "").strip() or None
    if not ja_sei and not atual.get("ignored") and not nova:
        raise Recusa("Esta leitura não está marcada «já sei»: não há o que tirar.")
    # O PUT troca a marcação inteira: sem observação nova, fica a que já existe (a da tela), e o prazo também.
    nota = nova or atual.get("note")
    vence = atual.get("expires_at") if ja_sei else None
    prazo_novo = None
    if ja_sei and a.get("dias") not in (None, ""):
        try:
            dias = int(a["dias"])
        except (TypeError, ValueError):
            raise Recusa("Não entendi o prazo: pergunte em dias (de 1 a 365).") from None
        if not 1 <= dias <= 365:
            raise Recusa("O prazo vai de 1 a 365 dias: pergunte de novo.")
        vence = prazo_novo = (datetime.now(UTC) + timedelta(days=dias)).isoformat()
    rotulo = linha.get("label") or leitura
    onde = f"{r.get('name')} · {rotulo} ({u['nome']})"
    resumo = (f"Marcar «já sei» no meuWatt: {onde}" if ja_sei else f"Tirar o «já sei» no meuWatt: {onde}"
              if atual.get("ignored") else f"Gravar a observação no meuWatt: {onde}")
    avisa = bool(linha.get("alert_hint"))                 # o que o bot avisa hoje (a tela mostra o sino)
    detalhes = [f"Observação: {nota}" if nota else "Sem observação",
                ((f"O aviso desta leitura deixa de sair até {hora_brt(vence)}." if vence else
                  "O aviso desta leitura deixa de sair até alguém tirar a marcação.") if avisa
                 else "Fica registrado (o bot não avisa esta leitura).") if ja_sei
                else "O aviso desta leitura continua saindo." if not atual.get("ignored")
                else "O aviso desta leitura volta a sair (a observação fica; apagar a observação, só na tela Leituras)."
                if nota else "O aviso desta leitura volta a sair."]
    slug, rid = u["slug"], int(r["relay_id"])

    async def executar(db, user, telefone: str) -> str:
        mw = cliente_meuwatt(db, user.id, so_proprio=True)
        try:
            # O PUT troca a marcação inteira: relê agora, para não apagar o que alguém editou na tela depois da proposta.
            hoje = next((x.get("mark") or {} for rel in (await mw.leituras(slug)).get("relays") or []
                         if rel.get("relay_id") == rid for x in rel.get("readings") or [] if x.get("key") == leitura),
                        atual)                            # a leitura sumiu da resposta: fica o que a proposta viu
            n, v = nova or hoje.get("note"), prazo_novo or (hoje.get("expires_at") if ja_sei else None)
            # O prazo que a proposta mostrou venceu até o Sim (o meuWatt já não o devolve): o X fica sem prazo, e diz.
            antes = atual.get("expires_at") if ja_sei and not prazo_novo else None
            venceu = bool(antes) and datetime.fromisoformat(str(antes).replace("Z", "+00:00")) <= datetime.now(UTC)
            if venceu:
                v = None
            await mw.marcar_leitura(slug, rid, leitura, ja_sei, n, v)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return "❌ O seu papel nesta usina no meuWatt não marca leituras (só a operação). Nada foi feito."
            return f"❌ O meuWatt recusou ({e.response.status_code}). Nada foi feito."
        except httpx.HTTPError:
            return f"⚠️ O meuWatt não respondeu: a marcação de {onde} PODE ter sido gravada. Confira na tela Leituras."
        feito = ("marcado «já sei»" if ja_sei else "o aviso volta a sair" if atual.get("ignored") else "observação gravada")
        return (f"✅ {onde}: {feito}" + (f". Observação: {n}" if n else "")
                + (". O prazo que havia já tinha vencido: ficou até alguém tirar" if venceu else "") + ".")

    return helper.propor(ctx, resumo, 600, executar, detalhes, parte="bot_meuwatt", confirmacao="sim")


def _f(nome, desc, props=None, req=None):
    return {"type": "function", "function": {"name": nome, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": req or []}}}


FERRAMENTAS = {
    "listar_usinas": (listar_usinas, _f("listar_usinas", "As usinas da pessoa com monitoramento (nome, kWp, estação).")),
    "geracao": (geracao, _f("geracao", "Geração de UMA usina num período: energia, produtividade (kWh/kWp), PR, "
        "disponibilidade, esperado/perdido, melhor e pior dia, dia a dia, meses e RANKING dos inversores com desvio da "
        "mediana e as strings paradas de cada um (com o que ele geraria com elas). Período de hoje traz 'agora' (até o "
        "momento).", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "comparar_usinas": (comparar_usinas, _f("comparar_usinas", "Todas as usinas da pessoa no período, da mais à menos "
        "produtiva (kWh/kWp), com PR, irradiação e disponibilidade.", {"inicio": _INI, "fim": _FIM})),
    "irradiacao": (irradiacao, _f("irradiacao", "IRRADIAÇÃO de uma usina por dia e total (estação POA/GHI quando houver; "
        "GHI de satélite sempre) e a estação agora. Vento/chuva/umidade não existem.", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "projeto": (projeto, _f("projeto", "Real × projeto PVsyst por mês (energia, PR e irradiação de projeto, "
        "disponibilidade, perdas): 'gerou conforme o PVsyst? por que não?'.", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "paradas": (paradas, _f("paradas", "Paradas de inversor no período, pela mesma régua da tela de Paradas: total, "
        "em aberto, fechadas, tempo parado, perda, por causa, por inversor, maiores perdas.",
        {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "reles": (reles, _f("reles", "TRIPS dos relés de proteção de uma usina pelo MONITORAMENTO (meuWatt): o histórico "
        "(disparou/limpou, a função e a hora) e se o relé comunica, para skid ou usina PARADA, trip, desarme ou antes "
        "de religar. Leitura AO VIVO de um relé (corrente, comunicação agora) é `usina_helper`.",
        {"usina": _USINA, "dias": {"type": "integer",
        "description": "Quantos dias de histórico de trip (padrão 2)."}})),
    "diagnostico_usina": (diagnostico_usina, _f("diagnostico_usina", "DIAGNÓSTICO da usina HOJE: POR QUE parou ou não "
        "ligou. Cruza os inversores parados com os trips dos relés de proteção (matriz ANSI: 27, 59, 47, 81, 50/51, 67, "
        "32, 86…), relé sem comunicação e fase zerada na medição, lê os equipamentos pelo helper e diz a causa provável e "
        "o que fazer. Com `codigo` (ex.: 27, 59N, 86) explica a função de proteção.",
        {"usina": _USINA, "codigo": {"type": "string", "description": "Função ANSI ou condição (27, 59N, NAO_LIGOU)."}})),
    "leituras_usina": (leituras_usina, _f("leituras_usina", "LEITURAS da tela Leituras do meuWatt: dos relés de proteção "
        "(fase zerada, sem comunicação, sem leitura) e das strings dos inversores (zerada, intermitente, fraca), as que "
        "não estão ok e as que alguém marcou «já sei» com a observação.",
        {"usina": _USINA, "rele": {"type": "string", "description": "Nome ou skid do relé (opcional)."}})),
    "marcar_strings": (marcar_strings, _f("marcar_strings", "AÇÃO (com Sim): marca «já sei» em STRINGS de um inversor "
        "na tela Leituras do meuWatt, com a observação (\"o inversor 13 tem uma string a menos\", \"a 6S27 está aberta, "
        "já sei\"): o problema passa a ser conhecido, e a comparação dos inversores diz isso. Sem `strings`, as que o "
        "meuWatt dá com problema naquele inversor; `quantas` = o número que a pessoa disse (\"uma string a menos\" = 1). "
        "`ja_sei`=false tira a marcação.",
        {"usina": _USINA, "inversor": {"type": "string", "description": "O inversor (ex.: Inv 13, 13)."},
         "strings": {"type": "array", "items": {"type": "string"},
                     "description": "As strings, pela etiqueta ou número (6S27, 27). Só se a pessoa disse quais."},
         "quantas": {"type": "integer", "description": "Quantas strings a pessoa disse (opcional)."},
         "ja_sei": {"type": "boolean", "description": "true = marcar «já sei» (padrão); false = tirar."},
         "observacao": {"type": "string", "description": "O que a pessoa disse, nas palavras dela."},
         "dias": {"type": "integer", "description": "Prazo do «já sei» em dias, só se a pessoa disser (sem = até tirar)."}},
        ["inversor"])),
    "marcar_leitura": (marcar_leitura, _f("marcar_leitura", "AÇÃO (com Sim): marca «já sei» numa leitura de um relé "
        "(o problema é conhecido, ex.: \"já sei, o relé tá com defeito\"), com a observação, na tela Leituras do "
        "meuWatt: o aviso daquela leitura deixa de sair. `ja_sei`=false tira a marcação (o aviso volta), ou, numa "
        "leitura sem marcação, grava só a observação. Use a chave da leitura que `diagnostico_usina` ou "
        "`leituras_usina` mostraram (fase A zerada = voltage_a; relé mudo = comm).",
        {"usina": _USINA, "rele": {"type": "string", "description": "Nome ou skid do relé (ex.: Skid 3, TR-03)."},
         "leitura": {"type": "string", "enum": LEITURAS_RELE},
         "ja_sei": {"type": "boolean", "description": "true = marcar «já sei» (padrão); false = tirar."},
         "observacao": {"type": "string", "description": "O que a pessoa disse do problema, nas palavras dela."},
         "dias": {"type": "integer", "description": "Prazo do «já sei» em dias, só se a pessoa disser (sem = até tirar)."}},
        ["rele", "leitura"])),
    "relatorio_pdf": (relatorio_pdf, _f("relatorio_pdf", "Manda como ARQUIVO o PDF do relatório MENSAL do monitoramento "
        "(geracao | paradas | resumo executivo).", {"usina": _USINA, "mes": _MES, "tipo": {"type": "string",
        "enum": ["geracao", "paradas", "resumo"]}}, ["mes"])),
    "excel_energia_diaria": (excel_energia_diaria, _f("excel_energia_diaria", "Manda como ARQUIVO o Excel da "
        "energia por DIA e por INVERSOR (uma aba por skid, aba Geral e aba Validação que confere com a plataforma do "
        "inversor). Sem datas = mês atual até hoje.", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "resumo_executivo": (resumo_executivo, _f("resumo_executivo", "Texto do resumo executivo do mês (veredito, "
        "destaques, perdas, ações e a observação da O&M).", {"usina": _USINA, "mes": _MES}, ["mes"])),
    "gemeo": (gemeo, _f("gemeo", "GÊMEO DIGITAL de uma usina (hoje Ibitinga, Porto Ferreira, Pirapozinho, Tietê, Ouro Fino e "
        "Pereiras) num mês: "
        "'foi o clima ou a usina?' — o real × o previsto pelo gêmeo (com o tempo que fez) × o PVsyst, a cascata (régua, "
        "clima, limitação, sol no plano, paradas, conversão), dia a dia, o hora a hora (padrão de tracker × sujeira × "
        "inversor), inversores, limites de potência lidos nos inversores e paradas. Para essas usinas, prefira esta a "
        "`projeto` quando a pergunta é por que gerou abaixo/acima.", {"usina": _USINA, "mes": {"type": "string",
        "description": "Mês AAAA-MM (o mês corrente vai até agora)."}}, ["mes"])),
    "gemeo_dia": (gemeo_dia, _f("gemeo_dia", "Um DIA no gêmeo digital, hora a hora: previsto × real, o sol medido no "
        "plano × o esperado, temperatura, corte nos limites e paradas.", {"usina": _USINA, "dia": {"type": "string",
        "description": "Dia AAAA-MM-DD (vazio = hoje)."}})),
    "gemeo_regua": (gemeo_regua, _f("gemeo_regua", "A RÉGUA do gêmeo digital: o quanto ele reproduz o PVsyst rodando com "
        "o clima e as premissas do PDF — diagrama de perdas etapa por etapa, mês a mês, ajustes (k, contraste), "
        "variantes e versões gravadas.", {"usina": _USINA})),
    "problemas_conhecidos": (problemas_conhecidos, _f("problemas_conhecidos", "Os PROBLEMAS CONHECIDOS da usina no meuWatt "
        "(o que a equipe já sabe): a lista do Gêmeos › Problemas conhecidos (cada problema, os serviços feitos para "
        "resolver, como lavagem, curva IV, termografia e ajuste dos trackers, com a data e a OS do meuPlano, se deu "
        "resultado e o que a equipe anotou) e os «já sei» da tela Leituras (relés e strings). Para 'quais os problemas "
        "conhecidos de X', 'a lavagem resolveu?'. É só o que a equipe CADASTROU: não é o estado nem o histórico do "
        "equipamento (tracker travado agora ou que costuma travar, paradas, alarmes: as outras ferramentas) e não é "
        "'pendências' (essas são do meuPlano: `manutencao`).", {"usina": _USINA})),
    "registrar_problema_conhecido": (registrar_problema_conhecido, _f("registrar_problema_conhecido", "AÇÃO (com Sim): "
        "registra um PROBLEMA CONHECIDO novo da usina no meuWatt (a lista do Gêmeos), com as palavras da pessoa ('já "
        "sabemos que o trafo 2 de Tietê esquenta mais', 'cadastre como problema conhecido'). String ou inversor com "
        "string a menos: use `marcar_strings`, que marca o «já sei» e registra aqui junto.",
        {"usina": _USINA, "titulo": {"type": "string", "description": "O problema em poucas palavras."},
         "problema": {"type": "string", "description": "O detalhe, nas palavras da pessoa (opcional)."}}, ["titulo"])),
    "gemeo_config": (gemeo_config, _f("gemeo_config", "O que o gêmeo digital sabe da usina: geometria, módulo e .PAN, "
        "inversor e .OND, perdas do PDF do PVsyst, limites reais e o comando de potência lido em cada inversor.",
        {"usina": _USINA})),
    "balanco_energia": (balanco_energia, _f("balanco_energia", "Balanço de energia por skid: inversores × medidor (o "
        "leitor da concessionária, o medidor particular) × conta de energia, com as perdas, o parecer e o gráfico.",
        {"usina": _USINA, "mes": {"type": "string", "description": "Mês fechado AAAA-MM (ou use inicio/fim)."},
         "inicio": _INI, "fim": _FIM})),
    "grafico": (grafico, _f("grafico", "Desenha e manda como IMAGEM: geracao_diaria, inversores, pr_diario, irradiacao "
        "ou usinas (produtividade de todas).", {"usina": _USINA, "inicio": _INI, "fim": _FIM, "tipo": {"type": "string",
        "enum": ["geracao_diaria", "inversores", "pr_diario", "irradiacao", "usinas"]}})),
}
