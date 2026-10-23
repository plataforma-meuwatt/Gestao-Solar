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
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

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


def da_plataforma(user) -> bool:
    """Administrador/atendimento da PLATAFORMA (sem empresa): vê todas as usinas e lê os
    produtos com a conexão da plataforma — como no painel."""
    from app.services.pessoas import DA_PLATAFORMA
    return user.perfil in DA_PLATAFORMA and user.empresa_id is None


async def preparar(ctx: Contexto) -> None:
    """Liga o contexto ao meuWatt: a credencial e o recorte de usinas do GS."""
    from sqlalchemy import select

    from app.api.v1.plants import usinas_do_usuario
    from app.models.plant import PlantLink
    from app.services import integracoes
    from app.services.vinculos import SemConexao, cliente_meuwatt
    if da_plataforma(ctx.user):
        links = ctx.db.scalars(select(PlantLink).where(PlantLink.ativo)).all()
    else:
        links = usinas_do_usuario(ctx.db, ctx.user)
    concedidas = {p.mw_plant_slug: p for p in links if p.mw_plant_slug}
    if not concedidas:
        return
    try:
        ctx.mw = (await integracoes.cliente_meuwatt(ctx.db) if da_plataforma(ctx.user)
                  else cliente_meuwatt(ctx.db, ctx.user.id))
    except (SemConexao, RuntimeError):
        return
    for p in await ctx.mw.usinas():
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
    if ctx.mw is None or not ctx.usinas:
        raise Recusa("Não há usina com monitoramento liberada para você no Gestão Solar.")
    todas = list(ctx.usinas.values())
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
    if c is not None:
        out["agora"] = {
            "energia_hoje_ate_agora_kwh": _r(c.get("energy_today_kwh")),
            "potencia_agora_kw": _r(sum((i.get("active_power") or 0) for i in c["inverters"]) / 1000)
            if c.get("inverters") else None,
            "pr_hoje_pct": _pct(c.get("plant_pr_today")) if u["estacao"] else None,
            "usina_dormindo": c.get("plant_sleeping"),
            "inversores_com_falha": len(c.get("faulty_inverters") or []), "dado_de": c.get("data_at")}
    r = await _range(ctx, u, ini, fim, c)
    kwp = r.get("total_capacity_kwp")
    invs = []
    for i in r.get("inverters") or []:
        kwh, ik = i.get("total_yield_kwh"), i.get("capacity_kwp")
        invs.append({"inversor": i.get("slot_label") or i.get("sn"), "skid": i.get("transformer_name"),
                     "energia_kwh": _r(kwh), "produtividade_kwh_kwp": _r(kwh / ik, 2) if kwh is not None and ik else None,
                     "perdido_kwh": _r(i.get("total_lost_kwh")), "com_falha": i.get("is_faulty")})
    prods = [i["produtividade_kwh_kwp"] for i in invs if i["produtividade_kwh_kwp"] is not None]
    med = median(prods) if prods else None
    for i in invs:
        x = i["produtividade_kwh_kwp"]
        i["desvio_da_mediana_pct"] = _r((x / med - 1) * 100) if x is not None and med else None
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
                "perdido_kwh": _r((r.get("summary") or {}).get("total_lost_kwh"))}

    linhas = list(await asyncio.gather(*(uma(u) for u in todas)))
    _, irr = await _irradiacao(ctx, [u["slug"] for u in todas], ini, fim)
    for u, x in zip(todas, linhas):
        x["irradiacao_ghi_satelite_kwh_m2"] = _soma((irr.get(u["slug"]) or {}).get("irradiacao_ghi_sat_dia") or [])
    linhas.sort(key=lambda x: (x.get("produtividade_kwh_kwp") is None, -(x.get("produtividade_kwh_kwp") or 0)))
    return {"inicio": ini.isoformat(), "fim": fim.isoformat(), "usinas": linhas,
            "nota": "Compare pela produtividade (kWh/kWp). Irradiação entre todas: a de satélite."}


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
        "fontes": "'estacao' = medida na usina. 'satelite' = estimativa externa — diga que é satélite.",
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
    u = _usina(ctx, a.get("usina"))
    ini, fim = _periodo(a.get("inicio"), a.get("fim"))
    q = await ctx.mw.paradas_detector(u["id"], f"{ini.isoformat()}T00:00:00-03:00", f"{fim.isoformat()}T23:59:59-03:00")
    linhas = q.get("rows") or []
    abertas = [x for x in linhas if not x.get("resolved_at")]

    def conta(campo, rot=None):
        c: dict[str, int] = {}
        for x in linhas:
            k = (rot or {}).get(x.get(campo), x.get(campo) or "—")
            c[k] = c.get(k, 0) + 1
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    def item(x):
        return {"inversor": x.get("slot_label"), "skid": x.get("transformer_name"), "inicio": x.get("stopped_at"),
                "fim": x.get("resolved_at"), "minutos": x.get("off_minutes"), "causa": _CAUSA.get(x.get("cause"), x.get("cause")),
                "situacao": _RESOLUCAO.get(x.get("resolution_reason"), x.get("resolution_reason")),
                "relevancia": x.get("materiality"), "perda_kwh": _r(x.get("shadow_loss_kwh"), 2)}

    perda = [x.get("shadow_loss_kwh") for x in linhas if x.get("shadow_loss_kwh") is not None]
    return {"usina": u["nome"], "inicio": ini.isoformat(), "fim": fim.isoformat(), "total": len(linhas),
            "relevantes": sum(x.get("materiality") == "material" for x in linhas), "em_aberto": len(abertas),
            "fechadas": len(linhas) - len(abertas), "perda_total_kwh": _r(sum(perda), 1) if perda else None,
            "minutos_parados_total": sum(x.get("off_minutes") or 0 for x in linhas),
            "por_causa": conta("cause", _CAUSA), "por_inversor": conta("slot_label"),
            "abertas": [item(x) for x in abertas][:20],
            "maiores_perdas": [item(x) for x in sorted(linhas, key=lambda x: -(x.get("shadow_loss_kwh") or 0))[:10]],
            "nota": "'material' = parada relevante; 'immaterial'/'blip' = piscadas curtas."}


async def relatorio_pdf(ctx: Contexto, a: dict) -> dict:
    from app.clients import whatsapp
    tipo = {"executivo": "resumo", "resumo_executivo": "resumo"}.get((a.get("tipo") or "geracao").lower(),
                                                                    (a.get("tipo") or "geracao").lower())
    if tipo not in ("geracao", "paradas", "resumo"):
        raise Recusa("tipo deve ser geracao, paradas ou resumo.")
    u = _usina(ctx, a.get("usina"))
    rel = await ctx.mw.relatorio_existente(u["slug"], "MENSAL", date.fromisoformat(f"{a['mes']}-01"))
    if not rel:
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
        pts = [(x["data"][5:], x[k]) for x in ds if x[k] is not None]
        titulo = f"{d['usina']} · irradiação · {d['inicio']} a {d['fim']}"
    else:
        d = await geracao(ctx, a)
        ds = d["dias"] if isinstance(d["dias"], list) else []
        if tipo == "inversores":
            pts, unid = [(i["inversor"], i["produtividade_kwh_kwp"]) for i in d["inversores_do_melhor_ao_pior"]
                         if i["produtividade_kwh_kwp"] is not None], "kWh/kWp"
        elif tipo == "pr_diario":
            pts, unid = [(x["data"][5:], x["pr_pct"]) for x in ds if x["pr_pct"] is not None], "PR %"
        else:
            pts, unid = [(x["data"][5:], x["energia_kwh"]) for x in ds if x["energia_kwh"] is not None], "kWh"
        titulo = f"{d['usina']} · {unid} · {d['inicio']} a {d['fim']}"
    if not pts:
        return {"erro": "Sem dados no período para desenhar."}
    png = await asyncio.to_thread(_desenhar, pts, titulo, unid)
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=png, filename="grafico.png",
                                       mime="image/png", texto=titulo)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(titulo)
    return {"grafico": titulo, "enviado_no_chat": ok}


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
    ax.set_title(titulo, fontsize=11)
    ax.grid(axis="y", alpha=.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------------------- catálogo
_USINA = {"type": "string", "description": "Nome da usina (parcial, sem acento serve). Vazio só se houver uma."}
_INI = {"type": "string", "description": "Data inicial AAAA-MM-DD. Calcule a partir de HOJE: 'mês' = dia 1; "
                                         "'semana' = segunda-feira; 'hoje'/'até agora' = hoje."}
_FIM = {"type": "string", "description": "Data final AAAA-MM-DD (inclusive). Vazio = igual ao início."}
_MES = {"type": "string", "description": "Mês AAAA-MM."}


def _f(nome, desc, props=None, req=None):
    return {"type": "function", "function": {"name": nome, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": req or []}}}


FERRAMENTAS = {
    "listar_usinas": (listar_usinas, _f("listar_usinas", "As usinas da pessoa com monitoramento (nome, kWp, estação).")),
    "geracao": (geracao, _f("geracao", "Geração de UMA usina num período: energia, produtividade (kWh/kWp), PR, "
        "disponibilidade, esperado/perdido, melhor e pior dia, dia a dia, meses e RANKING dos inversores com desvio da "
        "mediana. Período de hoje traz 'agora' (até o momento).", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "comparar_usinas": (comparar_usinas, _f("comparar_usinas", "Todas as usinas da pessoa no período, da mais à menos "
        "produtiva (kWh/kWp), com PR, irradiação e disponibilidade.", {"inicio": _INI, "fim": _FIM})),
    "irradiacao": (irradiacao, _f("irradiacao", "IRRADIAÇÃO de uma usina por dia e total (estação POA/GHI quando houver; "
        "GHI de satélite sempre) e a estação agora. Vento/chuva/umidade não existem.", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "projeto": (projeto, _f("projeto", "Real × projeto PVsyst por mês (energia, PR e irradiação de projeto, "
        "disponibilidade, perdas) — 'gerou conforme o PVsyst? por que não?'.", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "paradas": (paradas, _f("paradas", "Paradas de inversor no período: total, relevantes, em aberto, fechadas, por "
        "causa, por inversor, maiores perdas.", {"usina": _USINA, "inicio": _INI, "fim": _FIM})),
    "relatorio_pdf": (relatorio_pdf, _f("relatorio_pdf", "Manda como ARQUIVO o PDF do relatório MENSAL do monitoramento "
        "(geracao | paradas | resumo executivo).", {"usina": _USINA, "mes": _MES, "tipo": {"type": "string",
        "enum": ["geracao", "paradas", "resumo"]}}, ["mes"])),
    "resumo_executivo": (resumo_executivo, _f("resumo_executivo", "Texto do resumo executivo do mês (veredito, "
        "destaques, perdas, ações e a observação da O&M).", {"usina": _USINA, "mes": _MES}, ["mes"])),
    "grafico": (grafico, _f("grafico", "Desenha e manda como IMAGEM: geracao_diaria, inversores, pr_diario, irradiacao "
        "ou usinas (produtividade de todas).", {"usina": _USINA, "inicio": _INI, "fim": _FIM, "tipo": {"type": "string",
        "enum": ["geracao_diaria", "inversores", "pr_diario", "irradiacao", "usinas"]}})),
}
