"""Classificar as PARADAS pelo WhatsApp, passo a passo (pedido do dono, 07/11/2026: "Caíram várias usinas hoje, quero
um fluxo HIPER COMPLETO e DIDÁTICO no WhatsApp para eu classificar as paradas sem precisar ir no site").

O passo a passo é do SISTEMA, não da IA: uma máquina de estados determinística. A IA só reconhece o pedido de começar
(`classificar_paradas`); "classificar paradas", "paradas de hoje" e "o que caiu hoje" começam sem ela. O estado mora
no banco (`gs_fluxos_paradas`, um por pessoa, vale `VALIDADE` desde o último passo): sobrevive a um deploy.

De onde vem cada coisa — o meuWatt, com o token PRÓPRIO da pessoa (a régua do bot), só das usinas que ela vê:

- O que falta classificar é a aba "A classificar" da tela de Paradas de lá: `/shadow-breakdowns/queue` (o detector
  NOVO; o coletor antigo nunca) × `/shadow-breakdowns/compare` (as paradas AO VIVO casadas). `unidades` é a porta de
  `build_shadow_units` + `a_classificar` do mw-api (`src/shadow_breakdowns/units.py`, que porta o `shadowUnits.ts` do
  mw-fe; o mw-api não expõe a lista por HTTP, só a contagem do `pending-summary`). A UNIDADE é o card de lá: as
  paradas SIMULTÂNEAS que o detector agrupou (3 inversores que caíram juntos) são uma só; "um por um" separa.
- A cascata (motivo → origem → causa → causa raiz) é o `/breakdown-options`: o filho vale para o pai cujo id está em
  `parent_ids`. Grava-se o RÓTULO (o mw-fe manda o label, e a causa externa do motivo é casada pelo label lá).
- Gravar é `POST /breakdowns/classify-bulk` nos `live_id` da unidade — a parada AO VIVO, nunca o id do detector, que
  muda a cada rodada. "Não foi parada" é `POST /plants/{slug}/alerts/{live_id}/suppress` com a nota (o "Desclassificar"
  da tela). Nada é gravado sem o Confirmar (ou o "Aplicar às N", que mostra o que aplica). Antes de gravar, o par é
  lido de novo: a parada que alguém classificou no site enquanto isso não é sobrescrita.

Os botões levam `pc:<tok>:<ação>`; o `tok` muda a cada pergunta, então o toque numa pergunta antiga (o WhatsApp mantém
os botões) não responde a de agora. Todo toque `pc:` é deste módulo e nunca cai no "botão de resumo antigo" do helper.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import unicodedata
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clients import whatsapp
from app.core.datas import BRT
from app.models.fluxo_paradas import FluxoParadas
from app.services import assistente_geracao as ger

log = logging.getLogger("gs.assistente.paradas")

VALIDADE = timedelta(hours=12)
#: Quanto tempo depois da última pergunta o TEXTO digitado ainda é lido como resposta dela. Depois disso só os toques
#: valem (o fluxo vale 12 h): uma mensagem horas depois ("bom dia", "e Tietê?") é conversa, vai à IA.
TEXTO_VALE = timedelta(minutes=30)
#: A 2ª mensagem que chega até isto depois da observação é o resto dela, não a OS.
JUNTA_OBS = timedelta(seconds=60)
PREFIXO = "pc:"
MAX_DIAS = 31
LOTE = 500                                                 # o teto do classify-bulk
CAMPOS = ("motivo", "origem", "causa", "causa_raiz")
NOME = {"motivo": "Motivo", "origem": "Origem", "causa": "Causa", "causa_raiz": "Causa raiz"}
PERGUNTA = {"motivo": "o que aconteceu?", "origem": "onde aconteceu?", "causa": "como aconteceu?",
            "causa_raiz": "por que aconteceu?"}
NO_RESUMO = {"motivo": "O que aconteceu", "origem": "Onde", "causa": "Como", "causa_raiz": "Por quê"}
SEM_CONTA = (None, "", "no_peers")                         # `loss_method` de quem gravou 0,0 sem fazer conta

VENCIDO = ("Essa classificação de paradas já terminou ou venceu (vale 12 h desde o último passo). Diga «classificar "
           "paradas» para recomeçar: as que você já gravou não voltam.")
DICA = "Toque numa opção (ou escreva o nome dela), ou diga «voltar», «pular» ou «parar»."
PAPEL = ("Classificam paradas no meuWatt o administrador do sistema e o operador da usina; peça a quem administra o "
         "meuWatt para ajustar o seu papel lá.")


# =========================================================================== as unidades (porta do mw-api)
_EPOCA = datetime(1970, 1, 1, tzinfo=UTC)


def _dt(v: Any) -> datetime | None:
    """ISO 8601 → datetime com fuso (sem fuso no texto = UTC, como o mw-api grava)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _ms(d: datetime) -> int:
    return (d - _EPOCA) // timedelta(milliseconds=1)


def _cobertura(ini: datetime, fim: datetime | None, vivos: list, agora_ms: int) -> float:
    """`live_coverage_frac`: a fração de [ini, fim] coberta pela UNIÃO dos intervalos ao vivo (piso de 60 s)."""
    s0 = _ms(ini)
    s1 = _ms(fim) if fim is not None else agora_ms
    dur = max(60000, s1 - s0)
    cortados = []
    for a, b in vivos:
        if a is None:
            continue
        a2, b2 = max(s0, _ms(a)), min(s1, _ms(b) if b is not None else agora_ms)
        if b2 > a2:
            cortados.append((a2, b2))
    cortados.sort()
    total, ca, cb = 0, 0, -1
    for a, b in cortados:
        if a > cb:
            total += max(0, cb - ca)
            ca, cb = a, b
        else:
            cb = max(cb, b)
    total += max(0, cb - ca)
    return min(1.0, total / dur)


def _rotulo(label: Any, slot_id: Any, serial: Any = None) -> str:
    return label or (f"Slot {slot_id}" if slot_id is not None else (serial or "—"))


def unidades(fila: dict, casadas: dict, agora: datetime | None = None) -> list[dict]:
    """`build_shadow_units(queue, compare)`: os cards da tela de Paradas, na mesma ordem (grupos do detector → soltas →
    grupos manuais → só ao vivo). Cada um com o que decide a aba "A classificar" e os `live_ids` onde gravar."""
    agora_ms = _ms(agora or datetime.now(UTC))
    pares = list(casadas.get("pairs") or [])
    linhas = list(fila.get("rows") or [])
    grupos = {g.get("id"): g for g in fila.get("groups") or []}
    par_do = {p["shadow_id"]: p for p in pares if p.get("shadow_id") is not None}          # o último vence, como lá
    cobertos: dict[Any, list] = {}
    for p in pares:
        if p.get("covered_by_shadow_id") is not None:
            cobertos.setdefault(p["covered_by_shadow_id"], []).append(p)
    desclassificadas: dict[Any, list] = {}
    for s in casadas.get("live_suppressed_rows") or []:
        if s.get("slot_id") is not None:
            desclassificadas.setdefault(s["slot_id"], []).append((_dt(s.get("stopped_at")), _dt(s.get("resolved_at"))))
    manual = {p["shadow_id"]: p["live_manual_group_id"] for p in pares
              if p.get("shadow_id") is not None and p.get("live_id") is not None and p.get("live_manual_group_id")}

    def vivos(sid: Any) -> list:
        p = par_do.get(sid)
        return ([p] if p is not None and p.get("live_id") is not None else []) + cobertos.get(sid, [])

    def ids(ps: list) -> list[int]:
        return [p["live_id"] for p in ps if p.get("live_id") is not None]

    def classificada(ps: list) -> bool:
        return any(p.get("live_classified_at") is not None for p in ps)

    def desclassificada(r: dict) -> bool:
        if r.get("slot_id") is None:
            return False
        f = _cobertura(_dt(r["stopped_at"]), _dt(r.get("resolved_at")), desclassificadas.get(r["slot_id"], []),
                       agora_ms)
        return f >= 0.5 or (f > 0 and (par_do.get(r["id"]) or {}).get("live_id") is None)

    def tipo_vivo(sid: Any) -> Any:
        return (par_do.get(sid) or {}).get("live_kind")

    def membro(r: dict) -> dict:
        return {"inversor": _rotulo(r.get("slot_label"), r.get("slot_id"), r.get("serial_number")),
                "skid": r.get("transformer_name"), "inicio": r.get("stopped_at"), "fim": r.get("resolved_at"),
                "perda": None if r.get("loss_method") in SEM_CONTA else ger._r(r.get("shadow_loss_kwh"), 2),
                "causa": r.get("cause"), "resolucao": r.get("resolution_reason"), "live_ids": ids(vivos(r["id"])),
                "material": r.get("materiality") == "material"}

    def de_grupo(chave: str, ms: list, g: dict | None, manual_gid: Any = None) -> dict:
        tipo = "manual" if manual_gid is not None else ((g or {}).get("group_kind") or "temporal_succession")
        inicio = min(_dt(m["stopped_at"]) for m in ms)
        fim = _dt((g or {}).get("latest_end"))
        if fim is None:
            resolvidas = [_dt(m["resolved_at"]) for m in ms if m.get("resolved_at")]
            fim = max(resolvidas) if resolvidas else None
        if tipo == "manual":                               # o span do grupo manual é o das linhas ao vivo
            ls = le = None
            todas = True
            for m in ms:
                p = par_do.get(m["id"])
                if p is None or p.get("live_id") is None or not p.get("live_stopped_at"):
                    continue
                a, b = _dt(p["live_stopped_at"]), _dt(p.get("live_resolved_at"))
                ls = a if ls is None or a < ls else ls
                if b is None:
                    todas = False
                elif le is None or b > le:
                    le = b
            if ls is not None:
                inicio, fim = ls, (le if todas else None)
        live, cl, sup, mat, sup_mat = [], False, 0, 0, 0
        for m in ms:
            ps = vivos(m["id"])
            live += ids(ps)
            cl = cl or classificada(ps)
            s = desclassificada(m)
            sup += s
            if m.get("materiality") == "material":
                mat += 1
                sup_mat += s
        ativa = any(m.get("resolution_reason") == "still_open" for m in ms)
        return {"chave": chave, "grupo": tipo, "material": any(m.get("materiality") == "material" for m in ms),
                "classificada": cl, "desclassificada": (sup_mat == mat) if mat else (sup == len(ms)),
                "degradacao": all(tipo_vivo(m["id"]) == "degradation" for m in ms),
                "inicio": inicio, "fim": None if ativa else fim, "live_ids": live, "membros": [membro(m) for m in ms]}

    def solo(r: dict) -> dict:
        ps = vivos(r["id"])
        ativa = r.get("resolution_reason") == "still_open"
        return {"chave": f"s{r['id']}", "grupo": None, "material": r.get("materiality") == "material",
                "classificada": classificada(ps), "desclassificada": desclassificada(r),
                "degradacao": tipo_vivo(r["id"]) == "degradation", "inicio": _dt(r["stopped_at"]),
                "fim": None if ativa else _dt(r.get("resolved_at")), "live_ids": ids(ps), "membros": [membro(r)]}

    def membro_vivo(p: dict) -> dict:
        return {"inversor": _rotulo(p.get("slot_label"), p.get("slot_id")), "skid": p.get("transformer_name"),
                "inicio": p.get("live_stopped_at"), "fim": p.get("live_resolved_at"), "perda": None,
                "causa": p.get("live_cause"), "resolucao": None, "live_ids": [p["live_id"]], "material": True}

    def so_vivo(chave: str, ps: list) -> dict:
        abertas = any(p.get("live_resolved_at") is None for p in ps)
        inicios = [_dt(p["live_stopped_at"]) for p in ps if p.get("live_stopped_at")]
        fins = [_dt(p["live_resolved_at"]) for p in ps if p.get("live_resolved_at")]
        return {"chave": chave, "grupo": "manual" if len(ps) > 1 else None, "material": True,
                "classificada": classificada(ps), "desclassificada": False,
                "degradacao": all(p.get("live_kind") == "degradation" for p in ps),
                "inicio": min(inicios) if inicios else None, "fim": None if abertas else (max(fins) if fins else None),
                "live_ids": ids(ps), "membros": [membro_vivo(p) for p in ps]}

    saida: list[dict] = []
    baldes: dict[Any, list] = {}

    def reivindica(r: dict) -> bool:
        gid = manual.get(r["id"])
        if not gid:
            return False
        baldes.setdefault(gid, []).append(r)
        return True

    por_grupo: dict[Any, list] = {}
    for r in linhas:
        if r.get("group_id") is not None:
            por_grupo.setdefault(r["group_id"], []).append(r)
    for gid, ms in por_grupo.items():
        auto = [m for m in ms if not reivindica(m)]
        if len(auto) >= 2:
            saida.append(de_grupo(f"g{gid}", auto, grupos.get(gid)))
        elif len(auto) == 1:
            saida.append(solo(auto[0]))
    for r in linhas:
        if r.get("group_id") is None and not reivindica(r):
            saida.append(solo(r))
    for gid, ms in baldes.items():
        saida.append(de_grupo(f"mg{gid}", ms, None, gid) if len(ms) >= 2 else solo(ms[0]))
    so_ao_vivo: dict[Any, list] = {}
    for p in pares:
        if p.get("shadow_id") is not None or p.get("live_id") is None or p.get("covered_by_shadow_id") is not None:
            continue
        if p.get("live_manual_group_id"):
            so_ao_vivo.setdefault(p["live_manual_group_id"], []).append(p)
        else:
            saida.append(so_vivo(f"l{p['live_id']}", [p]))
    for gid, ps in so_ao_vivo.items():
        saida.append(so_vivo(f"mgl{gid}", ps) if len(ps) >= 2 else so_vivo(f"l{ps[0]['live_id']}", ps))
    return saida


def a_classificar(us: list[dict]) -> list[dict]:
    """A aba "A classificar": material, sem classificação ao vivo, não desclassificada e não é Baixa Geração."""
    return [u for u in us if u["material"] and not u["classificada"] and not u["desclassificada"]
            and not u["degradacao"]]


# =========================================================================== leitura
def _meia_noite(d: date) -> str:
    from app.api.v1.paradas import _meia_noite as mn
    return mn(d)


def _falha(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403:
        return "o seu papel no meuWatt não abre o Dashboard de Paradas desta usina"
    from app.api.v1.paradas import _motivo
    return f"não consegui ler ({_motivo(e)})"


def _dia(iso: str | None) -> date | None:
    d = _dt(iso)
    return d.astimezone(BRT).date() if d else None


def _serial(u: dict, slug: str) -> dict:
    """A unidade como fica no estado (JSON): só o que o passo a passo usa."""
    iso = lambda d: d.isoformat() if isinstance(d, datetime) else d          # noqa: E731
    return {"usina": slug, "chave": u["chave"], "grupo": u["grupo"], "inicio": iso(u["inicio"]), "fim": iso(u["fim"]),
            "live_ids": u["live_ids"], "membros": u["membros"]}


async def _ler(ctx: ger.Contexto, ini: date, fim: date, so: str | None = None) -> tuple[list[dict], dict]:
    """As paradas a classificar do período (pelo dia BRT do início, como a tela de Paradas do portal), por usina, e o
    que mais o resumo diz de cada uma: já classificadas, sem parada ao vivo (não dá para gravar), erro de leitura."""
    a, b = _meia_noite(ini), _meia_noite(fim + timedelta(days=1))
    agora = datetime.now(UTC)
    alvo = {s: u for s, u in ctx.usinas.items() if so is None or s == so}
    ctx.db.commit()                                        # solta a conexão enquanto o meuWatt responde

    async def uma(slug: str, u: dict) -> tuple[str, dict, list[dict]]:
        try:
            fila, casadas = await asyncio.gather(ctx.mw.paradas_detector(u["id"], a, b),
                                                 ctx.mw.paradas_casadas(u["id"], a, b))
        except Exception as e:                             # noqa: BLE001 — uma usina não derruba as outras
            return slug, {"erro": _falha(e)}, []
        if not fila.get("run"):
            return slug, {"erro": "o detector de paradas não analisou este período"}, []
        us = [x for x in unidades(fila, casadas, agora) if x["inicio"] and ini <= x["inicio"].astimezone(BRT).date()
              <= fim]
        pend = a_classificar(us)
        return slug, {"classificadas": sum(1 for x in us if x["material"] and x["classificada"] and not x["degradacao"]),
                      "sem_vivo": sum(1 for x in pend if not x["live_ids"])}, \
            [_serial(x, slug) for x in pend if x["live_ids"]]

    lidas = await asyncio.gather(*(uma(s, u) for s, u in alvo.items()))
    todas = [x for _, _, xs in lidas for x in xs]
    todas.sort(key=lambda x: (ger._norm(ctx.usinas[x["usina"]]["nome"]), x["inicio"] or ""))
    return todas, {s: e for s, e, _ in lidas}


# =========================================================================== texto
def _n(s: str | None) -> str:
    """Sem acento, sem caixa e sem pontuação: "Não foi parada!" == "nao foi parada"."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def _num(v: float | None) -> str:
    if v is None:
        return "—"
    t = f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def _hora(iso: str | None) -> str:
    d = _dt(iso)
    return d.astimezone(BRT).strftime("%H:%M") if d else "—"


def _quando(iso: str | None) -> str:
    d = _dt(iso)
    return d.astimezone(BRT).strftime("%d/%m %H:%M") if d else "—"


def _duracao(ini: str | None, fim: str | None) -> str:
    a, b = _dt(ini), _dt(fim)
    if a is None or b is None:
        return ""
    m = max(0, int((b - a).total_seconds() // 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _e(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _inversores(u: dict) -> str:
    nomes = [m["inversor"] for m in u["membros"]]
    skids = sorted({m["skid"] for m in u["membros"] if m.get("skid")})
    txt = _e(nomes) if len(nomes) <= 6 else f"{len(nomes)} inversores ({', '.join(nomes[:3])}…)"
    return txt + (f" ({', '.join(skids)})" if skids else "")


def _perda(u: dict) -> float | None:
    """A soma só quando TODO inversor tem a conta feita (REGRA 0: ausência não é zero)."""
    v = [m.get("perda") for m in u["membros"]]
    return None if not v or any(x is None for x in v) else round(sum(v), 2)


def _detector(u: dict) -> str:
    causas = list(dict.fromkeys(ger._CAUSA.get(m.get("causa"), m.get("causa")) for m in u["membros"] if m.get("causa")))
    voltas = list(dict.fromkeys(ger._RESOLUCAO.get(m.get("resolucao"), m.get("resolucao")) for m in u["membros"]
                                if m.get("resolucao")))
    return "; ".join([*causas, *voltas])


def _cabecalho(estado: dict, u: dict) -> str:
    nome = estado["usinas"][u["usina"]]["nome"]
    if u.get("fim"):
        volta = _hora(u["fim"]) if _dia(u["fim"]) == _dia(u["inicio"]) else _quando(u["fim"])
        tempo = f"parou {_quando(u['inicio'])}, voltou {volta} ({_duracao(u['inicio'], u['fim'])})"
    else:
        tempo = f"parou {_quando(u['inicio'])} e ainda não voltou"
    return f"*{nome}* · {_inversores(u)}\n{tempo}"


# =========================================================================== mensagens
def _msg(texto: str, botoes: list[tuple[str, str]] | None = None, lista: dict | None = None,
         formulario: dict | None = None, alternativa: str = "") -> dict:
    """Uma mensagem a sair. `alternativa`: o que vai junto do texto quando o gateway (ou a Meta) recusa os botões, a
    lista ou o formulário — a pergunta não pode sumir."""
    m: dict[str, Any] = {"texto": texto}
    if botoes:
        m["botoes"] = botoes
        alternativa = alternativa or "Responda: " + _e([f"«{t}»" for _, t in botoes]).replace(" e ", " ou ") + "."
    if lista:
        m["lista"] = lista
    if formulario:
        m["formulario"] = formulario
    if alternativa:
        m["alternativa"] = alternativa
    return m


def _ids(estado: dict, botoes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Os ids dos botões desta pergunta; o TÍTULO de cada um vale também digitado ("Não, conta"), e vale antes de
    qualquer palavra solta — o texto alternativo do próprio bot manda digitar o título."""
    estado.setdefault("titulos", {}).update({_n(t): a for a, t in botoes})
    return [(f"{PREFIXO}{estado['tok']}:{a}", t) for a, t in botoes]


def _corta(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def _escolha(estado: dict, texto: str, rotulos: list[str], secao: str) -> dict:
    """A pergunta com opções: até 3 curtas → botões; até 10 → lista; mais → o formulário de UMA escolha (lista
    suspensa pesquisável, `gs_escolha_uma`). A opção também vale digitada (o nome ou o número)."""
    numeradas = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rotulos[:60]))
    alternativa = (f"{numeradas}\nResponda com o número ou o nome." if len(rotulos) <= 60
                   else "São muitas opções: escreva o nome da que quer.")
    if len(rotulos) <= 3 and all(len(r) <= 20 for r in rotulos):
        return _msg(texto, _ids(estado, [(f"o{i}", r) for i, r in enumerate(rotulos)]), alternativa=alternativa)
    if len(rotulos) <= 10:
        linhas = [{"id": f"{PREFIXO}{estado['tok']}:o{i}", "titulo": _corta(r, 24),
                   "descricao": _corta(r, 72) if len(r) > 24 else ""} for i, r in enumerate(rotulos)]
        return _msg(texto, lista={"botao": "Ver opções", "secao": _corta(secao, 24), "linhas": linhas},
                    alternativa=alternativa)
    estado["form"] = secrets.token_urlsafe(12)
    return _msg(texto, formulario={"token": estado["form"], "titulo": secao[:300], "uma": True,
                                   "opcoes": rotulos[:200], "rotulos": [_corta(r, 30) for r in rotulos[:200]],
                                   "marcados": []},
                alternativa=alternativa)


def texto_de(saidas: list[dict]) -> str:
    """O que as mensagens disseram, em texto (o log do bot e a conversa)."""
    return "\n\n".join(s["texto"] for s in saidas)


Guardar = Callable[[str], "str | None"]


def _guardada(guardar: Guardar | None, texto: str) -> str | None:
    """O que a cópia do gateway guarda no lugar do texto, no teto dele (4.096): a máscara troca «123» por «••••» e o
    texto no limite passaria — o gateway recusaria a mensagem inteira."""
    g = guardar(texto) if guardar else None
    return g[:4096] if g else None


async def _so_texto(telefone: str, texto: str, guardar: Guardar | None = None) -> bool:
    ok = True
    for i in range(0, len(texto), 3900):
        pedaco = texto[i:i + 3900]
        try:
            r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="text", texto=pedaco,
                                               guardar=_guardada(guardar, pedaco))
        except whatsapp.GatewayIndisponivel:
            r = None
        ok = ok and bool((r or {}).get("ok"))
    return ok


async def _uma(telefone: str, s: dict, texto: str, guardar: Guardar | None) -> bool:
    r = None
    g = (lambda x: _guardada(guardar, x))                  # noqa: E731
    try:
        if s.get("botoes") or s.get("formulario"):
            limite = 1024
            if len(texto) > limite:                        # o corpo da interativa vai até 1024: o resto antes
                await _so_texto(telefone, texto, guardar)
                texto = "Escolha:"
            if s.get("botoes"):
                r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="botoes", texto=texto, guardar=g(texto),
                                                   botoes=[{"id": i, "titulo": t} for i, t in s["botoes"]])
            else:
                r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="formulario", texto=texto,
                                                   guardar=g(texto), formulario=s["formulario"])
        elif s.get("lista"):
            r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="lista", texto=texto[:4096],
                                               guardar=g(texto[:4096]), lista=s["lista"])
        else:
            return await _so_texto(telefone, texto, guardar)
    except whatsapp.GatewayIndisponivel:
        log.warning("paradas: o gateway recusou a interativa; vai em texto", exc_info=True)
    if (r or {}).get("ok"):
        return True
    return await _so_texto(telefone, texto + (f"\n\n{s['alternativa']}" if s.get("alternativa") else ""), guardar)


async def enviar(telefone: str, saidas: list[dict], nota: str = "", guardar: Guardar | None = None) -> bool:
    """Manda as mensagens do passo, na ordem. `nota`: o aviso do sistema ao pé da primeira (a ação que este toque
    cancelou). `guardar(texto)`: o que a cópia do gateway guarda no lugar do texto (sem a senha que a observação
    trouxer; a pessoa recebe o inteiro) — o `assistente._guardado`, como em toda resposta do bot."""
    ok = True
    for k, s in enumerate(saidas):
        ok = await _uma(telefone, s, s["texto"] + (f"\n\n{nota}" if nota and k == 0 else ""), guardar) and ok
    return ok


# =========================================================================== estado
def _carregar(db: Session, user_id: int) -> dict | None:
    f = db.scalar(select(FluxoParadas).where(FluxoParadas.gs_user_id == user_id))
    if f is None:
        return None
    expira = f.expira_em if f.expira_em.tzinfo else f.expira_em.replace(tzinfo=UTC)
    if expira < datetime.now(UTC):
        db.delete(f)
        db.commit()
        return None
    try:
        return json.loads(f.estado)
    except ValueError:
        return None


def _salvar(db: Session, user_id: int, estado: dict) -> None:
    f = db.scalar(select(FluxoParadas).where(FluxoParadas.gs_user_id == user_id))
    if f is None:
        f = FluxoParadas(gs_user_id=user_id)
        db.add(f)
    f.estado = json.dumps(estado, ensure_ascii=False, default=str)
    f.expira_em = datetime.now(UTC) + VALIDADE
    db.commit()


def _apagar(db: Session, user_id: int) -> None:
    db.execute(delete(FluxoParadas).where(FluxoParadas.gs_user_id == user_id))
    db.commit()


def _ir(estado: dict, etapa: str) -> None:
    estado["etapa"] = etapa
    if not estado["pilha"] or estado["pilha"][-1] != etapa:
        estado["pilha"].append(etapa)


#: A ordem das etapas de uma parada e das escolhas que cada uma grava: voltar a uma etapa apaga dela em diante.
_ORDEM = {"cartao": 0, "n0": 1, "n1": 2, "n2": 3, "n3": 4, "externa": 5, "obs": 6, "os": 7, "conferir": 8,
          "naoparada": 1, "naoparada_nota": 2, "naoparada_conferir": 3}
_DA_ESCOLHA = {"motivo": 1, "motivo_id": 1, "origem": 2, "origem_id": 2, "causa": 3, "causa_id": 3, "causa_raiz": 4,
               "causa_raiz_id": 4, "externa": 5, "obs": 6, "os": 7, "nota": 2}


def _limpar_desde(estado: dict, etapa: str) -> None:
    corte = _ORDEM.get(etapa)
    if corte is not None:
        estado["esc"] = {k: v for k, v in estado["esc"].items() if _DA_ESCOLHA.get(k, 99) < corte}


# =========================================================================== as perguntas
def _resumo(estado: dict) -> list[dict]:
    todas, extras, usinas = estado["todas"], estado["extras"], estado["usinas"]
    linhas = [f"📉 *Paradas a classificar · {estado['rotulo']}*"]
    por: dict[str, list] = {}
    for u in todas:
        por.setdefault(u["usina"], []).append(u)
    if todas:
        linhas.append(f"*{len(todas)}* parada(s) em {len(por)} usina(s):")
    for slug, us in por.items():
        quais = "; ".join(f"{_inversores(u)} {_hora(u['inicio'])}" for u in us[:3]) + (
            f"; e mais {len(us) - 3}" if len(us) > 3 else "")
        conhecidas = [p for p in map(_perda, us) if p is not None]
        perda = ("" if not conhecidas else f" · perda estimada {'≥ ' if len(conhecidas) < len(us) else ''}"
                 f"{_num(sum(conhecidas))} kWh")
        linhas.append(f"• *{usinas[slug]['nome']}*: {len(us)} · {quais}{perda}")
    feitas = sum((e or {}).get("classificadas") or 0 for e in extras.values())
    sem_vivo = sum((e or {}).get("sem_vivo") or 0 for e in extras.values())
    erros = [f"{usinas[s]['nome']}: {e['erro']}" for s, e in extras.items() if (e or {}).get("erro")]
    if feitas:
        linhas.append(f"Já classificadas no período: {feitas}.")
    if sem_vivo:
        linhas.append(f"{sem_vivo} ainda sem registro ao vivo no meuWatt: não dá para classificar agora (nem no site).")
    if erros:
        linhas.append("⚠️ " + " · ".join(erros))
    linhas.append("Vou parada por parada: 4 perguntas em cada uma, e você confere antes de eu gravar no meuWatt.")
    botoes = [("todas", "Classificar agora")] + ([("uma", "Só uma usina")] if len(por) > 1 else []) + \
        [("depois", "Depois")]
    return [_msg("\n".join(linhas), _ids(estado, botoes))]


def _cartao(estado: dict) -> list[dict]:
    i, fila = estado["i"], estado["fila"]
    u = fila[i]
    p = _perda(u)
    linhas = [f"*Parada {i + 1} de {len(fila)}*", _cabecalho(estado, u),
              f"Perda estimada: {_num(p)} kWh" if p is not None else "Perda estimada: sem conta do detector",
              *([f"O detector viu: {_detector(u)}"] if _detector(u) else []),
              ("Juntei os inversores que caíram ao mesmo tempo: a classificação vale para todos. "
               if len(u["membros"]) > 1 else "")
              + "Vou te perguntar 4 coisas: o que aconteceu, onde, como e por quê. No fim você confere e confirma."]
    if i == 0 and estado["placar"] == _PLACAR:
        linhas.append("Em qualquer pergunta: «voltar», «pular» (esta parada) ou «parar».")
    terceiro = ("sep", "Um por um") if len(u["membros"]) > 1 else ("pular", "Pular")
    return [_msg("\n".join(linhas), _ids(estado, [("cl", "Classificar"), ("np", "Não foi parada"), terceiro]))]


def _opcoes(estado: dict, k: int) -> list[dict]:
    campo = CAMPOS[k]
    if k == 0:
        return list(estado["tax"]["motivo"])
    pai = estado["esc"].get(f"{CAMPOS[k - 1]}_id")
    return [o for o in estado["tax"][campo] if pai in o["pais"]]


def _caminho(estado: dict, ate: int) -> str:
    feitas = [estado["esc"][c] for c in CAMPOS[:ate] if estado["esc"].get(c)]
    return f"({' › '.join(feitas)})\n" if feitas else ""


def _nivel(estado: dict, k: int) -> list[dict]:
    campo = CAMPOS[k]
    ops = _opcoes(estado, k)
    texto = f"{_caminho(estado, k)}*Passo {k + 1} de 4 · {NOME[campo]}:* {PERGUNTA[campo]}"
    if not ops and k == 0:
        return [_msg("O meuWatt não tem motivo de parada cadastrado: cadastre na tela de Paradas de lá.",
                     _ids(estado, [("pular", "Pular"), ("parar", "Parar")]))]
    if not ops:
        anterior = CAMPOS[k - 1]
        return [_msg(f"Não há {NOME[campo].lower()} cadastrada no meuWatt para «{estado['esc'].get(anterior)}». "
                     f"Cadastre na tela de Paradas de lá, ou volte e escolha outro(a) {NOME[anterior].lower()}.",
                     _ids(estado, [("voltar", "Voltar"), ("pular", "Pular"), ("parar", "Parar")]))]
    estado["oferecidas"] = [o["id"] for o in ops]
    return [_escolha(estado, texto, [o["label"] for o in ops], NOME[campo])]


def _externa_padrao(estado: dict) -> bool:
    """`isExternalMotivo` do mw-fe: o motivo marcado como externo no cadastro, ou chamado "Externa"/"Externo"."""
    o = next((o for o in estado["tax"]["motivo"] if o["id"] == estado["esc"].get("motivo_id")), None)
    return bool(o and o["ext"]) or _n(estado["esc"].get("motivo")) in ("externa", "externo")


def _externa(estado: dict) -> list[dict]:
    m = estado["esc"].get("motivo")
    if _externa_padrao(estado):
        return [_msg(f"*Causa externa?* Pelo motivo «{m}», esta parada é de causa EXTERNA: ela NÃO conta contra a "
                     "disponibilidade do contrato. Confere?", _ids(estado, [("ext1", "Sim, externa"),
                                                                            ("ext0", "Não, conta")]))]
    return [_msg(f"*Causa externa?* Pelo motivo «{m}», esta parada CONTA na disponibilidade do contrato (não é causa "
                 "externa). Confere?", _ids(estado, [("ext0", "Sim, conta"), ("ext1", "Não, é externa")]))]


def _conferir(estado: dict) -> list[dict]:
    u, esc = estado["fila"][estado["i"]], estado["esc"]
    linhas = ["📋 *Confere antes de gravar*", _cabecalho(estado, u),
              *[f"• {NO_RESUMO[c]}: {esc[c]}" for c in CAMPOS],
              "• Causa externa: " + ("sim, NÃO conta na disponibilidade" if esc["externa"]
                                     else "não, conta na disponibilidade"),
              f"• Observação: {esc.get('obs') or 'nenhuma'}", f"• OS: {esc.get('os') or 'nenhuma'}",
              f"Grava no meuWatt, em {len(u['live_ids'])} parada(s) ao vivo."]
    return [_msg("\n".join(linhas), _ids(estado, [("ok", "Confirmar"), ("corr", "Corrigir"), ("canc", "Cancelar")]))]


def _outras(estado: dict) -> list[dict]:
    """As paradas que faltam da MESMA usina e do MESMO dia da que acabou de ser gravada."""
    u = estado["fila"][estado["i"]]
    return [x for x in estado["fila"][estado["i"] + 1:]
            if not x.get("feita") and x["usina"] == u["usina"] and _dia(x["inicio"]) == _dia(u["inicio"])]


def _pergunta_outras(estado: dict) -> list[dict]:
    outras, esc = _outras(estado), estado["esc"]
    u = estado["fila"][estado["i"]]
    linhas = [f"Há mais {len(outras)} parada(s) de *{estado['usinas'][u['usina']]['nome']}* em "
              f"{_dia(u['inicio']):%d/%m} esperando classificação:",
              *[f"• {_inversores(x)} · {_hora(x['inicio'])}" for x in outras[:5]],
              *([f"• e mais {len(outras) - 5}"] if len(outras) > 5 else []),
              "Aplicar a mesma classificação a elas, inclusive a observação e a OS?",
              "• " + " › ".join(esc[c] for c in CAMPOS),
              "• Causa externa: " + ("sim" if esc["externa"] else "não"),
              f"• Observação: {esc.get('obs') or 'nenhuma'}", f"• OS: {esc.get('os') or 'nenhuma'}"]
    return [_msg("\n".join(linhas), _ids(estado, [("apl", f"Aplicar às {len(outras)}"), ("uma", "Uma a uma")]))]


def _naoparada(estado: dict) -> list[dict]:
    return [_msg("*Não foi parada?* Eu tiro esta parada da conta no meuWatt (desclassifico: sai das paradas e das "
                 "perdas; dá para reverter na tela de Paradas de lá). Por quê? Toque numa opção ou escreva o motivo.",
                 _ids(estado, [("np:c", "Comunicação"), ("np:s", "Sem sol / noite"), ("np:o", "Outro motivo")]))]


def _naoparada_conferir(estado: dict) -> list[dict]:
    u = estado["fila"][estado["i"]]
    return [_msg(f"📋 *Confere:* marcar como NÃO foi parada\n{_cabecalho(estado, u)}\n• Motivo: {estado['esc']['nota']}"
                 f"\nDesclassifica {len(u['live_ids'])} parada(s) ao vivo no meuWatt.",
                 _ids(estado, [("ok", "Confirmar"), ("voltar", "Voltar"), ("canc", "Cancelar")]))]


def _render(estado: dict) -> list[dict]:
    """A pergunta da etapa de agora, com um `tok` novo: os botões das perguntas anteriores deixam de valer."""
    estado["tok"] = secrets.token_hex(3)
    estado["form"], estado["titulos"], estado["em"] = None, {}, datetime.now(UTC).isoformat()
    etapa = estado["etapa"]
    if etapa == "resumo":
        return _resumo(estado)
    if etapa == "usina":
        slugs = list(dict.fromkeys(u["usina"] for u in estado["todas"]))
        estado["oferecidas"] = slugs
        cont = {s: sum(1 for u in estado["todas"] if u["usina"] == s) for s in slugs}
        return [_escolha(estado, "Qual usina?", [f"{estado['usinas'][s]['nome']} ({cont[s]})" for s in slugs],
                         "Usinas")]
    if etapa == "cartao":
        return _cartao(estado)
    if etapa.startswith("n") and etapa[1:].isdigit():
        return _nivel(estado, int(etapa[1:]))
    if etapa == "externa":
        return _externa(estado)
    if etapa == "obs":
        return [_msg("*Observação (opcional):* quer deixar uma? Escreva numa mensagem (ex.: a rede caiu e religou "
                     "sozinha), ou toque em Sem observação.", _ids(estado, [("obs0", "Sem observação"),
                                                                           ("voltar", "Voltar")]))]
    if etapa == "os":
        return [_msg("*Ordem de serviço (opcional):* tem OS para esta parada? Escreva o número, ou toque em Sem OS.",
                     _ids(estado, [("os0", "Sem OS"), ("voltar", "Voltar")]))]
    if etapa == "conferir":
        return _conferir(estado)
    if etapa == "outras":
        return _pergunta_outras(estado)
    if etapa == "naoparada":
        return _naoparada(estado)
    if etapa == "naoparada_nota":
        return [_msg("Escreva, numa mensagem, por que não foi parada.", _ids(estado, [("voltar", "Voltar")]))]
    if etapa == "naoparada_conferir":
        return _naoparada_conferir(estado)
    raise ValueError(f"etapa desconhecida: {etapa}")


def _antes(saidas: list[dict], frase: str) -> list[dict]:
    """A frase do sistema no topo da primeira mensagem (o que acabou de acontecer)."""
    if frase and saidas:
        saidas[0] = {**saidas[0], "texto": f"{frase}\n\n{saidas[0]['texto']}"}
    return saidas


# =========================================================================== o placar e o fim
_PLACAR = {"classificadas": 0, "nao": 0, "puladas": 0, "ja": 0, "fora": 0}


def _placar(p: dict) -> str:
    partes = [f"{p['classificadas']} classificada(s)", f"{p['nao']} marcada(s) como não-parada",
              f"{p['puladas']} pulada(s)"]
    extra = [*([f"{p['ja']} já classificada(s) no site enquanto isso"] if p["ja"] else []),
             *([f"{p['fora']} sem permissão para gravar"] if p["fora"] else [])]
    return ", ".join(partes) + (f" ({'; '.join(extra)})" if extra else "")


def _faltam(estado: dict) -> int:
    return estado["placar"]["puladas"] + sum(1 for x in estado["fila"][estado["i"]:] if not x.get("feita"))


def _encerrar(estado: dict, parou: bool, antes: str = "") -> list[dict]:
    estado["encerrado"] = True
    if parou:
        texto = (f"⏸️ Parei aqui. {_placar(estado['placar'])}. Ficaram {_faltam(estado)} para classificar: diga "
                 "«classificar paradas» quando quiser continuar.")
    else:
        texto = f"🏁 Pronto: {_placar(estado['placar'])}." + (
            " As puladas continuam no meuWatt: diga «classificar paradas» para voltar a elas."
            if estado["placar"]["puladas"] else "")
    return [_msg(f"{antes}\n\n{texto}" if antes else texto)]


def _proxima(estado: dict, antes: str = "") -> list[dict]:
    fila = estado["fila"]
    estado["i"] += 1
    while estado["i"] < len(fila) and fila[estado["i"]].get("feita"):
        estado["i"] += 1
    estado["esc"], estado["pilha"] = {}, []
    if estado["i"] >= len(fila):
        return _encerrar(estado, parou=False, antes=antes)
    _ir(estado, "cartao")
    return _antes(_render(estado), antes)


# =========================================================================== o começo
def _rotulo_periodo(ini: date, fim: date) -> str:
    h = ger.hoje()
    if ini == fim:
        return {h: f"hoje ({h:%d/%m})", h - timedelta(days=1): f"ontem ({ini:%d/%m})"}.get(ini, f"{ini:%d/%m}")
    return f"{ini:%d/%m} a {fim:%d/%m}"


#: O pedido de COMEÇAR reconhecido sem a IA: só a forma imperativa, sem pergunta, com o período que se lê com certeza
#: (hoje, ontem, a semana) e, no fim, a usina exata. Pergunta ("quantas faltam classificar?", "a de ontem já foi
#: classificada?") e data que não se lê com certeza ("anteontem", "do dia 03/11", "do mês passado") vão à IA, que
#: chama `paradas_a_classificar` ou `classificar_paradas` com as datas.
_COMECO = re.compile(r"^(?:(?:vamos|bora|quero|preciso)\s+)?classific(?:ar|a|e)\s+(?:as\s+)?paradas?(?P<a>.*)$"
                     r"|^(?:e\s+)?(?:as\s+)?paradas(?P<b>\s+.+)$"
                     r"|^(?:e\s+)?o\s+que\s+caiu(?P<c>.*)$")
_RESTO = re.compile(r"^(?P<per>de hoje|hoje|de ontem|ontem|da semana|desta semana|dessa semana)?\s*"
                    r"(?:(?:de|da|do|em|na|no)\s+(?P<us>.+))?$")


def _pedido_de_comecar(cru: str) -> tuple[date, date, str | None] | None:
    """(início, fim, o texto da usina) do pedido de começar, ou `None` (não é, ou não dá para ler com certeza)."""
    if "?" in (cru or ""):
        return None
    m = _COMECO.match(_n(cru))
    if m is None:
        return None
    resto = (m.group("a") or m.group("b") or m.group("c") or "").strip()
    r = _RESTO.match(resto)
    if r is None or (m.group("b") is not None and not r.group("per")):   # "paradas de X" sozinho é leitura
        return None
    h = ger.hoje()
    per = r.group("per") or "hoje"
    ini, fim = {"hoje": (h, h), "ontem": (h - timedelta(days=1), h - timedelta(days=1))}.get(
        per.split()[-1], (h - timedelta(days=6), h))
    return ini, fim, r.group("us")


def _usina_exata(ctx: ger.Contexto, texto: str) -> str | None:
    alvo = ger._norm(texto)
    achadas = [s for s, u in ctx.usinas.items() if alvo in (ger._norm(u["nome"]), ger._norm(s))]
    return achadas[0] if len(achadas) == 1 else None


async def comecar(ctx: ger.Contexto, ini: date, fim: date, usina: str | None = None) -> list[dict]:
    """Lê as paradas e devolve o resumo (com os botões). Grava o estado se há o que classificar; uma classificação
    que estava aberta é trocada por esta (e a pessoa fica sabendo)."""
    antiga = _carregar(ctx.db, ctx.user.id) is not None
    todas, extras = await _ler(ctx, ini, fim, usina)
    rotulo = _rotulo_periodo(ini, fim) + (f" · {ctx.usinas[usina]['nome']}" if usina else "")
    aviso = "(Comecei de novo: a classificação que estava aberta foi trocada por esta.)" if antiga else ""
    if not todas:
        if antiga:
            _apagar(ctx.db, ctx.user.id)
        feitas = sum((e or {}).get("classificadas") or 0 for e in extras.values())
        erros = [f"{ctx.usinas[s]['nome']}: {e['erro']}" for s, e in extras.items() if (e or {}).get("erro")]
        sem_vivo = sum((e or {}).get("sem_vivo") or 0 for e in extras.values())
        linhas = [f"✅ Nenhuma parada a classificar · {rotulo}." + (f" Já classificadas: {feitas}." if feitas else "")]
        if sem_vivo:
            linhas.append(f"{sem_vivo} ainda sem registro ao vivo no meuWatt: não dá para classificar agora.")
        if erros:
            linhas.append("⚠️ Não conferi: " + " · ".join(erros))
        return _antes([_msg("\n".join(linhas))], aviso)
    estado = {"v": 1, "etapa": "resumo", "pilha": ["resumo"], "rotulo": rotulo, "ini": ini.isoformat(),
              "fim": fim.isoformat(),
              "janela": [_meia_noite(ini), _meia_noite(fim + timedelta(days=1))],
              "usinas": {s: {"nome": u["nome"], "id": u["id"]} for s, u in ctx.usinas.items()},
              "todas": todas, "extras": extras, "fila": [], "i": 0, "esc": {}, "tax": None,
              "placar": dict(_PLACAR), "oferecidas": [], "form": None, "tok": ""}
    saidas = _antes(_render(estado), aviso)
    _salvar(ctx.db, ctx.user.id, estado)
    return saidas


# =========================================================================== o que a pessoa disse
_PARAR = {"parar", "para", "pare", "sair", "encerrar", "encerra", "chega", "terminar", "fim", "parar tudo"}
_PULAR = {"pular", "pula", "pule", "proxima", "pular essa", "pula essa", "pular esta", "proxima parada"}
_VOLTAR = {"voltar", "volta", "volte", "anterior", "voltar um passo"}
_CONFIRMA = {"confirmar", "confirmo", "confirma", "pode gravar", "grava", "gravar", "sim", "ok", "pode", "isso"}
_NENHUMA = {"nao", "n", "sem", "nenhuma", "nenhum", "nada", "nao tem", "sem observacao", "sem obs", "sem os",
            "sem ordem", "sem ordem de servico"}
#: O que é concordância e nunca é o RESTO de uma observação.
_CURTAS = {"sim", "nao", "n", "ok", "isso", "pode", "beleza", "blz", "valeu", "obrigado", "obrigada", "certo"}
#: A OS digitada inteira como código (com ou sem "OS" na frente): "OS 1638", "os-2026-001", "#1638".
_OS = re.compile(r"(?i)^(?:(?:os|o\.s\.?|ordem(?:\s+de\s+servi[cç]o)?)\s*[:#-]?\s*)?#?\s*[a-z]{0,4}-?\d[\w\-/.]{0,20}$")
#: As palavras que acompanham o número da OS numa frase: "a OS é a 1638", "nº 1638", "1638 e 1640".
_PALAVRAS_DE_OS = {"a", "o", "os", "e", "n", "no", "numero", "num", "ordem", "de", "servico", "da", "do", "eh", "s"}
#: As ações de TEXTO LIVRE (observação, OS, motivo de não ser parada): só valem até `TEXTO_VALE` depois da pergunta.
_LIVRES = ("txt", "obs+", "os:")


def _desvia(cru: str) -> bool:
    """O texto livre que NÃO é a resposta: uma pergunta ("?") ou o pedido explícito de começar a classificar. Nunca pela
    1ª palavra — "Quando a equipe chegou o inversor já tinha religado" é observação."""
    return "?" in cru or _pedido_de_comecar(cru) is not None


def _numeros_de_os(cru: str, t: str) -> str | None:
    """A OS que o texto diz: o código inteiro ("OS 1638", "os-2026-001") ou os números de uma frase que só fala da OS
    ("a OS é a 1638", "nº 1638"; "1638 e 1640" guarda as duas, o campo do meuWatt é texto e a pessoa confere)."""
    if _OS.match(cru.strip()):
        return cru.strip()[:60]
    palavras = t.split()
    numeros = [p for p in palavras if p.isdigit()]
    if numeros and all(p.isdigit() or p in _PALAVRAS_DE_OS for p in palavras):
        return ", ".join(numeros)[:60]
    return None


def _texto_vale(estado: dict) -> bool:
    em = _dt(estado.get("em"))
    return em is not None and datetime.now(UTC) - em <= TEXTO_VALE


def _acao_do_texto(estado: dict, t: str, cru: str) -> str | None:
    """O texto digitado como a ação da etapa de agora, ou `None`: não é resposta desta pergunta (vai à IA). O título de
    um botão, a opção exata, «parar» e o sim/não da pergunta da vez valem enquanto o fluxo vale; o texto LIVRE
    (`_LIVRES`) só até `TEXTO_VALE` depois da pergunta (quem confere é `tratar`)."""
    etapa = estado["etapa"]
    if t in estado.get("titulos", {}):                     # o título de um botão desta pergunta, digitado
        acao = estado["titulos"][t]
        return "uma" if acao == "pular" and etapa == "outras" else acao
    if t in _PARAR:
        return "parar"
    if t in _VOLTAR:
        return "voltar"
    if t in _PULAR:
        return {"resumo": None, "usina": None, "outras": "uma"}.get(etapa, "pular")   # "outras": a de agora já foi
    if etapa == "obs":
        return "obs0" if t in _NENHUMA else (None if _desvia(cru) else "txt")
    if etapa == "os":
        if t in _NENHUMA:
            return "os0"
        if t == "sim":
            return "os?"                                   # "tem OS?" — "sim": qual o número?
        if (os_ := _numeros_de_os(cru, t)) is not None:
            return "os:" + os_
        junta = _dt(estado.get("obs_em"))                  # a 2ª mensagem da observação, logo depois da 1ª
        if junta and datetime.now(UTC) - junta <= JUNTA_OBS and t not in _CURTAS and not _desvia(cru):
            return "obs+"
        return None
    if etapa in ("naoparada", "naoparada_nota"):
        if etapa == "naoparada":
            if "comunic" in t:
                return "np:c"
            if t in {"sem sol", "noite", "sem sol noite", "de noite", "a noite"}:
                return "np:s"
            if t in {"outro", "outro motivo"}:
                return "np:o"
        return None if _desvia(cru) or t in _CURTAS else "txt"
    if etapa == "resumo":
        if t in {"classificar", "classificar agora", "comecar", "todas"}:
            return "todas"
        if t in {"depois", "agora nao", "mais tarde"}:
            return "depois"
        if t in {"so uma usina", "uma usina", "so uma"}:
            return "uma"
        slugs = list(dict.fromkeys(u["usina"] for u in estado["todas"]))
        achada = _casar([estado["usinas"][x]["nome"] for x in slugs], t, pedaco=False)   # "boa" não é Boa Esperança
        if len(achada) == 1:
            estado["oferecidas"] = slugs
            return f"o{achada[0]}"
        return None
    if etapa == "cartao":
        if t in {"classificar", "classifica", "sim"}:
            return "cl"
        if t in {"nao foi parada", "nao foi", "nao e parada", "nao parou", "nao era parada"}:
            return "np"
        if t in {"um por um", "separar", "separado", "separa", "um a um"}:
            return "sep"
        return None
    if etapa == "externa":
        padrao = _externa_padrao(estado)
        if t in {"sim", "confere", "isso", "ok"}:
            return "ext1" if padrao else "ext0"
        if t in {"nao", "n"}:
            return "ext0" if padrao else "ext1"
        if t in {"externa", "e externa", "causa externa"}:
            return "ext1"
        if t in {"nao e externa", "interna", "nao externa"}:
            return "ext0"
        return None
    if etapa in ("conferir", "naoparada_conferir"):
        if "?" not in cru and t in _CONFIRMA:
            return "ok"
        if t in {"corrigir", "corrige", "refazer"} and etapa == "conferir":
            return "corr"
        if t in {"cancelar", "cancela", "nao", "n"}:
            return "canc"
        return None
    if etapa == "outras":
        if "?" not in cru and (t.startswith("aplica") or t in {"sim", "pode", "ok"}):
            return "apl"
        if t in {"uma a uma", "uma por uma", "um a um", "nao", "n"}:
            return "uma"
        return None
    if etapa == "usina" or (etapa.startswith("n") and etapa[1:].isdigit()):
        rotulos = (list(estado["oferecidas"]) if etapa == "usina" else
                   [o["label"] for o in _opcoes(estado, int(etapa[1:]))])
        if etapa == "usina":
            rotulos = [estado["usinas"][x]["nome"] for x in rotulos]
        achadas = _casar(rotulos, t, pedaco=etapa != "usina")
        if len(achadas) == 1:
            return f"o{achadas[0]}"
        if len(achadas) > 1:
            return "amb:" + "|".join(rotulos[i] for i in achadas[:6])
        return None
    return None


def _casar(rotulos: list[str], t: str, pedaco: bool = True) -> list[int]:
    """Os índices das opções que o texto nomeia: o nome exato (sem acento nem caixa), o número dela, ou (`pedaco`) um
    pedaço que só ela tem. Sem `pedaco` (usina), o pedaço tem de ser o COMEÇO do nome, em palavras inteiras."""
    if not t:
        return []
    nomes = [_n(r) for r in rotulos]
    exatas = [i for i, n in enumerate(nomes) if n == t or ger._norm(n) == ger._norm(t)]
    if exatas:
        return exatas[:1]
    if t.isdigit() and 1 <= int(t) <= len(rotulos):
        return [int(t) - 1]
    if not pedaco:
        return [i for i, n in enumerate(nomes) if len(t) >= 3 and re.match(rf"{re.escape(ger._norm(t))}\b", ger._norm(n))]
    return [i for i, n in enumerate(nomes) if len(t) >= 3 and t in n]


# =========================================================================== gravar
class _SemConferir(Exception):
    """Não deu para reler o meuWatt antes de gravar: nada é gravado."""


async def _ainda_pendentes(ctx: ger.Contexto, estado: dict, slug: str, ids: list[int]) -> list[int]:
    """Os `live_id` que seguem sem classificação e sem desclassificação AGORA (o site pode ter classificado enquanto a
    pessoa respondia, e o estado vale até 12 h). Sem conseguir reler, NÃO grava (`_SemConferir`): gravar por cima do
    que o site fez é pior do que pedir o Confirmar de novo.

    ponytail: entre esta leitura e a gravação sobra uma janela de segundos — o classify-bulk do meuWatt não exige
    `classified_at IS NULL`, e só lá dá para fechá-la."""
    try:
        c = await ctx.mw.paradas_casadas(ctx.usinas[slug]["id"], *estado["janela"])
    except Exception as e:                                 # noqa: BLE001
        log.warning("paradas: não reli o par antes de gravar; nada gravado", exc_info=True)
        raise _SemConferir(_motivo_http(e)) from e
    livres = {p["live_id"] for p in c.get("pairs") or [] if p.get("live_id") is not None
              and p.get("live_classified_at") is None}
    return [i for i in ids if i in livres]


def _sem_conferir(estado: dict, e: _SemConferir, botao: str) -> list[dict]:
    return _antes(_render(estado), f"❌ Não consegui conferir no meuWatt se ela ainda está sem classificação ({e}): "
                                   f"nada foi gravado. Toque em {botao} para tentar de novo.")


def _fora_da_concessao(ctx: ger.Contexto, estado: dict) -> list[dict] | None:
    """A usina saiu do alcance da pessoa no meio do fluxo (concessão tirada no GS, ou o token dela não a vê mais): as
    paradas dela que faltam não são gravadas — o estado guardado não é autorização."""
    slug = estado["fila"][estado["i"]]["usina"]
    if slug in ctx.usinas:
        return None
    dela = [x for x in estado["fila"][estado["i"]:] if x["usina"] == slug and not x.get("feita")]
    for x in dela:
        x["feita"] = True
    estado["placar"]["fora"] += len(dela)
    return _proxima(estado, f"❌ Nada foi gravado: {estado['usinas'][slug]['nome']} não está mais liberada para você "
                            f"(no Gestão Solar ou no seu token do meuWatt). Pulei as {len(dela)} parada(s) dela.")


def _classificacao(esc: dict) -> dict:
    """O corpo do classify-bulk, como o mw-fe manda: os quatro RÓTULOS, a OS e a observação (ou nulo) e a causa
    externa sempre explícita."""
    return {**{c: esc[c] for c in CAMPOS}, "ordem_servico": esc.get("os") or None,
            "observacoes": esc.get("obs") or None, "is_external_cause": bool(esc["externa"])}


def _motivo_http(e: Exception) -> str:
    from app.api.v1.paradas import _motivo
    return _motivo(e)


def _recusou(e: Exception) -> bool:
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403


async def _classificar(ctx: ger.Contexto, ids: list[int], corpo: dict) -> int:
    feitas = 0
    for k in range(0, len(ids), LOTE):
        feitas += int((await ctx.mw.classificar_paradas(ids[k:k + LOTE], corpo) or {}).get("updated") or 0)
    return feitas


def _sem_papel(estado: dict, e: Exception) -> list[dict]:
    from app.services.integracoes import detalhe_do_upstream
    dito = detalhe_do_upstream(e.response) if isinstance(e, httpx.HTTPStatusError) else None
    return _encerrar(estado, parou=True, antes=f"❌ Nada foi gravado: o meuWatt recusou{f' («{dito}»)' if dito else ''}. "
                                                f"{PAPEL} Encerrei a classificação.")


async def _gravar(ctx: ger.Contexto, estado: dict) -> list[dict]:
    if (fora := _fora_da_concessao(ctx, estado)) is not None:
        return fora
    u = estado["fila"][estado["i"]]
    nome = estado["usinas"][u["usina"]]["nome"]
    try:
        ids = await _ainda_pendentes(ctx, estado, u["usina"], u["live_ids"])
    except _SemConferir as e:
        return _sem_conferir(estado, e, "Confirmar")
    if not ids:
        u["feita"] = True
        estado["placar"]["ja"] += 1
        return _proxima(estado, "Essa parada já foi classificada (ou desclassificada) no meuWatt enquanto "
                                "conversávamos: não gravei por cima.")
    corpo = _classificacao(estado["esc"])
    try:
        feitas = await _classificar(ctx, ids, corpo)
    except Exception as e:                                 # noqa: BLE001
        if _recusou(e):
            return _sem_papel(estado, e)
        log.warning("paradas: o classify-bulk falhou", exc_info=True)
        return _antes(_render(estado), f"❌ O meuWatt não gravou agora ({_motivo_http(e)}). Nada foi gravado. Toque em "
                                       "Confirmar para tentar de novo.")
    u["feita"] = True
    if feitas == 0:
        estado["placar"]["fora"] += 1
        return _proxima(estado, f"❌ Nada foi gravado em {nome}: o seu papel no meuWatt nesta usina não classifica "
                                f"paradas. {PAPEL}")
    estado["placar"]["classificadas"] += 1
    frase = f"✅ Gravado no meuWatt: {_inversores(u)}, {nome} ({feitas} parada(s) ao vivo)."
    if feitas < len(ids):
        frase += (f"\n⚠️ Gravei em {feitas} de {len(ids)}: as outras são de usina em que o seu papel no meuWatt não "
                  "classifica.")
    if _outras(estado):
        estado["pilha"] = []                               # gravada: "voltar" não reabre o Confirmar
        _ir(estado, "outras")
        return _antes(_render(estado), frase)
    return _proxima(estado, frase)


async def _aplicar(ctx: ger.Contexto, estado: dict) -> list[dict]:
    if (fora := _fora_da_concessao(ctx, estado)) is not None:
        return fora
    outras = _outras(estado)
    u = estado["fila"][estado["i"]]
    try:
        pendentes = await _ainda_pendentes(ctx, estado, u["usina"], [i for x in outras for i in x["live_ids"]])
    except _SemConferir as e:
        return _sem_conferir(estado, e, f"Aplicar às {len(outras)}")
    vale = [x for x in outras if set(x["live_ids"]) & set(pendentes)]
    try:
        feitas = await _classificar(ctx, pendentes, _classificacao(estado["esc"])) if pendentes else 0
    except Exception as e:                                 # noqa: BLE001
        if _recusou(e):
            return _sem_papel(estado, e)
        log.warning("paradas: o classify-bulk das outras falhou", exc_info=True)
        return _antes(_render(estado), f"❌ O meuWatt não gravou agora ({_motivo_http(e)}). Nada foi gravado. Toque em "
                                       "Aplicar de novo, ou em Uma a uma.")
    for x in outras:
        x["feita"] = True
    estado["placar"]["ja"] += len(outras) - len(vale)
    if not pendentes:
        return _proxima(estado, f"Nada foi gravado: as {len(outras)} já tinham sido classificadas (ou desclassificadas) "
                                "no meuWatt enquanto conversávamos.")
    if feitas == 0:
        estado["placar"]["fora"] += len(vale)
        return _proxima(estado, f"❌ Nada foi gravado: o seu papel no meuWatt nesta usina não classifica paradas. "
                                f"{PAPEL}")
    estado["placar"]["classificadas"] += len(vale)
    frase = f"✅ Mesma classificação gravada em mais {len(vale)} parada(s) ({feitas} ao vivo)."
    if feitas < len(pendentes):
        frase += f"\n⚠️ Gravei em {feitas} de {len(pendentes)}: as outras são de usina fora do seu papel no meuWatt."
    if len(vale) < len(outras):
        frase += f"\n{len(outras) - len(vale)} já tinham sido classificadas no site: não gravei por cima."
    return _proxima(estado, frase)


async def _desclassificar(ctx: ger.Contexto, estado: dict) -> list[dict]:
    if (fora := _fora_da_concessao(ctx, estado)) is not None:
        return fora
    u = estado["fila"][estado["i"]]
    try:
        ids = await _ainda_pendentes(ctx, estado, u["usina"], u["live_ids"])
    except _SemConferir as e:
        return _sem_conferir(estado, e, "Confirmar")
    if not ids:
        u["feita"] = True
        estado["placar"]["ja"] += 1
        return _proxima(estado, "Essa parada já foi classificada (ou desclassificada) no meuWatt enquanto "
                                "conversávamos: não mexi nela.")
    feitas = 0
    for i in ids:
        try:
            await ctx.mw.desclassificar_parada(u["usina"], i, estado["esc"]["nota"])
            feitas += 1
        except Exception as e:                             # noqa: BLE001
            if _recusou(e):
                return _sem_papel(estado, e) if not feitas else _encerrar(
                    estado, parou=True, antes=f"⚠️ Desclassifiquei {feitas} de {len(ids)}; o meuWatt recusou o resto. "
                                              f"{PAPEL}")
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                continue                                   # sumiu do meuWatt: nada a desclassificar
            log.warning("paradas: o suppress falhou", exc_info=True)
            return _antes(_render(estado), f"❌ O meuWatt não desclassificou agora ({_motivo_http(e)}); fiz {feitas} de "
                                           f"{len(ids)}. Toque em Confirmar para tentar o resto.")
    u["feita"] = True
    if feitas == 0:
        estado["placar"]["ja"] += 1
        return _proxima(estado, "Nada foi desclassificado: o meuWatt não achou mais essas paradas (sumiram ou foram "
                                "refeitas pelo detector).")
    estado["placar"]["nao"] += 1
    return _proxima(estado, f"✅ Marcada como NÃO foi parada no meuWatt ({feitas} parada(s) ao vivo): saiu da conta "
                            "de paradas e de perdas.")


# =========================================================================== um passo
async def _taxonomia(ctx: ger.Contexto, estado: dict) -> str | None:
    """A cascata, lida uma vez por classificação (o vocabulário quase não muda). Devolve a frase da falha."""
    if estado.get("tax"):
        return None
    try:
        bruto = await ctx.mw.opcoes_de_parada()
    except Exception as e:                                 # noqa: BLE001
        return f"Não consegui ler as opções de classificação do meuWatt agora ({_motivo_http(e)}). Toque em Classificar de novo."
    estado["tax"] = {c: [{"id": o.get("id"), "label": str(o.get("label") or "").strip(),
                          "pais": list(o.get("parent_ids") or []), "ext": bool(o.get("is_external"))}
                         for o in bruto.get(c) or [] if str(o.get("label") or "").strip()] for c in CAMPOS}
    return None


def _a_partir_do_nivel(estado: dict, k: int) -> list[dict]:
    """Vai à pergunta do nível `k`; nível com UMA opção só é escolhido sozinho (e dito)."""
    notas = []
    while k < 4:
        ops = _opcoes(estado, k)
        if len(ops) != 1:
            _ir(estado, f"n{k}")
            return _antes(_render(estado), "\n".join(notas))
        campo = CAMPOS[k]
        estado["esc"][campo], estado["esc"][f"{campo}_id"] = ops[0]["label"], ops[0]["id"]
        pai = f" para «{estado['esc'][CAMPOS[k - 1]]}»" if k else ""
        notas.append(f"✔️ {NOME[campo]}: {ops[0]['label']} (a única opção{pai}).")
        k += 1
    _ir(estado, "externa")
    return _antes(_render(estado), "\n".join(notas))


async def _passo(ctx: ger.Contexto, estado: dict, acao: str) -> list[dict]:
    etapa = estado["etapa"]
    if acao == "parar":
        return _encerrar(estado, parou=True)
    if acao == "voltar":
        pilha = estado["pilha"]
        if len(pilha) <= 1:
            return _antes(_render(estado), "Já estamos no começo" + (" desta parada." if etapa == "cartao" else "."))
        pilha.pop()
        estado["etapa"] = pilha[-1]
        _limpar_desde(estado, pilha[-1])
        return _render(estado)
    if acao == "?":
        return _antes(_render(estado), f"Não entendi. {DICA}")
    if acao.startswith("amb:"):
        return _antes(_render(estado), f"Mais de uma opção casa com o que você escreveu: {', '.join(acao[4:].split('|'))}. "
                                       "Qual delas?")
    if acao == "pular" and etapa not in ("resumo", "usina"):
        estado["placar"]["puladas"] += 1
        return _proxima(estado)
    escolhida = int(acao[1:]) if re.fullmatch(r"o\d+", acao) else None
    if etapa in ("resumo", "usina"):
        if acao == "depois":
            estado["encerrado"] = True
            return [_msg("Tudo bem. Quando quiser, diga «classificar paradas».")]
        if acao == "uma":
            _ir(estado, "usina")
            return _render(estado)
        if acao == "todas" or escolhida is not None:
            if escolhida is not None:
                if escolhida >= len(estado["oferecidas"]):
                    return _render(estado)
                slug = estado["oferecidas"][escolhida]
                estado["fila"] = [u for u in estado["todas"] if u["usina"] == slug]
            else:
                estado["fila"] = list(estado["todas"])
            estado["i"], estado["esc"], estado["pilha"] = 0, {}, []
            _ir(estado, "cartao")
            return _render(estado)
    elif etapa == "cartao":
        if acao == "cl":
            falha = await _taxonomia(ctx, estado)
            if falha:
                return _antes(_render(estado), f"❌ {falha}")
            return _a_partir_do_nivel(estado, 0)
        if acao == "np":
            _ir(estado, "naoparada")
            return _render(estado)
        if acao == "sep":
            u = estado["fila"][estado["i"]]
            # só o inversor que PAROU (a piscada que o detector juntou ao grupo não é parada a classificar) e que tem
            # parada ao vivo onde gravar
            novos = [{**u, "chave": f"{u['chave']}.{k}", "grupo": None, "inicio": m["inicio"], "fim": m["fim"],
                      "live_ids": m["live_ids"], "membros": [m]} for k, m in enumerate(u["membros"])
                     if m["live_ids"] and m.get("material", True)]
            piscadas = sum(1 for m in u["membros"] if not m.get("material", True))
            sem_vivo = len(u["membros"]) - len(novos) - piscadas
            estado["fila"][estado["i"]:estado["i"] + 1] = novos
            if not novos:
                return _proxima(estado, "Nenhum inversor desta parada tem registro ao vivo no meuWatt: não dá para "
                                        "classificar um por um. Pulei.")
            return _antes(_render(estado), f"Separei em {len(novos)} parada(s), uma por inversor." + (
                f" {piscadas} só piscou (não é parada) e ficou de fora." if piscadas else "") + (
                f" {sem_vivo} sem registro ao vivo no meuWatt ficou(aram) de fora." if sem_vivo else ""))
    elif etapa.startswith("n") and etapa[1:].isdigit() and escolhida is not None:
        k = int(etapa[1:])
        if escolhida < len(estado["oferecidas"]):
            o = next((o for o in _opcoes(estado, k) if o["id"] == estado["oferecidas"][escolhida]), None)
            if o is not None:
                estado["esc"][CAMPOS[k]], estado["esc"][f"{CAMPOS[k]}_id"] = o["label"], o["id"]
                return _a_partir_do_nivel(estado, k + 1)
    elif etapa == "externa" and acao in ("ext0", "ext1"):
        estado["esc"]["externa"] = acao == "ext1"
        _ir(estado, "obs")
        return _render(estado)
    elif etapa == "os" and acao.startswith("os:"):
        estado["esc"]["os"] = acao[3:] or None
        _ir(estado, "conferir")
        return _render(estado)
    elif etapa == "os" and acao == "os?":
        return _antes(_render(estado), "Qual o número da OS?")
    elif etapa == "os" and acao == "obs+":
        mais = (estado.pop("_cru", "") or "").strip()
        estado["esc"]["obs"] = f"{estado['esc'].get('obs') or ''} {mais}".strip()[:500]
        estado["obs_em"] = datetime.now(UTC).isoformat()
        return _antes(_render(estado), f"Juntei à observação: «{estado['esc']['obs']}».")
    elif etapa in ("obs", "os") and acao in ("obs0", "os0", "txt"):
        valor = None if acao != "txt" else (estado.pop("_cru", "") or "").strip()[:500 if etapa == "obs" else 60]
        estado["esc"][etapa] = valor or None
        if etapa == "obs":
            estado["obs_em"] = datetime.now(UTC).isoformat() if valor else None
        _ir(estado, "os" if etapa == "obs" else "conferir")
        return _render(estado)
    elif etapa == "conferir":
        if acao == "ok":
            return await _gravar(ctx, estado)
        if acao == "corr":
            estado["esc"], estado["pilha"] = {}, ["cartao"]
            return _antes(_a_partir_do_nivel(estado, 0), "Vamos refazer esta parada.")
        if acao == "canc":
            estado["placar"]["puladas"] += 1
            return _proxima(estado, "Cancelado: nada foi gravado nesta parada.")
    elif etapa == "outras":
        if acao == "apl":
            return await _aplicar(ctx, estado)
        if acao == "uma":
            return _proxima(estado)
    elif etapa in ("naoparada", "naoparada_nota"):
        notas = {"np:c": "Falha de comunicação (não foi parada)", "np:s": "Sem sol / noite (não foi parada)"}
        if acao == "np:o":
            _ir(estado, "naoparada_nota")
            return _render(estado)
        if acao in notas or acao == "txt":
            nota = notas.get(acao) or (estado.pop("_cru", "") or "").strip()[:500]
            if nota:
                estado["esc"]["nota"] = nota
                _ir(estado, "naoparada_conferir")
                return _render(estado)
    elif etapa == "naoparada_conferir":
        if acao == "ok":
            return await _desclassificar(ctx, estado)
        if acao == "canc":
            estado["placar"]["puladas"] += 1
            return _proxima(estado, "Cancelado: a parada ficou como estava.")
    return _render(estado)                                 # ação que não é desta etapa: a pergunta de novo


def _sem_meuwatt(ctx: ger.Contexto) -> str:
    if "bot_meuwatt" not in ctx.user.bot_ativo:
        return ("Classificar paradas usa o monitoramento (meuWatt), e essa parte do bot não está liberada para você. "
                "O gerente da sua O&M libera em oem-gs → Bot do WhatsApp, com o seu token do meuWatt.")
    if ctx.mw_falha:
        return f"O monitoramento (meuWatt) não respondeu agora: {ctx.mw_falha} Tente de novo em instantes."
    return "Não há usina com monitoramento liberada para você no Gestão Solar."


def e_do_fluxo(evento: dict) -> bool:
    """O toque é num botão (ou numa linha de lista) deste passo a passo."""
    return str(evento.get("botao") or "").startswith(PREFIXO)


async def tratar(db: Session, user, telefone: str, evento: dict, texto: str, pendente: bool = False
                 ) -> tuple[list[dict], bool] | None:
    """A mensagem é da classificação de paradas? Devolve (as mensagens a mandar, se um toque VÁLIDO fez o fluxo
    andar), ou `None` (segue o caminho de sempre: a IA). `texto` é o MASCARADO (sem a senha de atuação). `pendente`:
    há uma ação do helper/meuPlano esperando a confirmação — aí só o toque deste fluxo é dele; o texto ("sim") é da
    ação. O texto que não é desta pergunta (ou que chega mais de `TEXTO_VALE` depois dela) vai à IA: a pessoa continua
    conversando com o bot com a classificação aberta."""
    botao = str(evento.get("botao") or "")
    form = (evento.get("midia") or {}).get("formulario")
    estado = _carregar(db, user.id)
    nosso_form = (isinstance(form, dict) and estado is not None and bool(estado.get("form"))
                  and form.get("flow_token") == estado["form"])
    toque = e_do_fluxo(evento)
    t = _n(texto)
    pedido = acao = None
    if not (toque or nosso_form):
        if pendente or not t or evento.get("tipo") not in ("text", "audio", "voice"):
            return None
        pedido = _pedido_de_comecar(texto)
        if pedido is None:
            if estado is None:
                return None
            acao = _acao_do_texto(estado, t, texto)
            if acao is None or (acao.startswith(_LIVRES) and not _texto_vale(estado)):
                return None                                # texto livre horas depois da pergunta: é conversa
    if evento.get("wamid"):
        try:
            await whatsapp.digitando(evento["wamid"])      # "digitando…": ler as usinas e gravar levam segundos
        except Exception:                                  # noqa: BLE001 — é enfeite
            pass
    ctx = ger.Contexto(db=db, user=user, telefone=telefone)
    await ger.preparar(ctx)
    if ctx.mw is None or not ctx.usinas:
        return [_msg(_sem_meuwatt(ctx))], False
    if pedido is not None:
        ini, fim, us = pedido
        slug = _usina_exata(ctx, us) if us else None
        if us and slug is None:
            return None                                    # "de <algo que não é usina>": a IA lê melhor
        return await comecar(ctx, ini, fim, slug), False
    if estado is None:
        return [_msg(VENCIDO)], False
    if nosso_form:
        i = str(form.get("escolhido") or "")
        acao = f"o{i}" if i.isdigit() else "?"
    elif toque:
        tok, _, acao = botao[len(PREFIXO):].partition(":")
        if tok != estado.get("tok"):
            saidas = _antes(_render(estado), "Esse botão é de uma pergunta anterior. Sigo daqui:")
            _salvar(db, user.id, estado)
            return saidas, False
    else:
        estado["_cru"] = texto
    saidas = await _passo(ctx, estado, acao)
    estado.pop("_cru", None)
    if estado.get("encerrado"):
        _apagar(db, user.id)
    else:
        _salvar(db, user.id, estado)
    return saidas, toque or nosso_form


# =========================================================================== as ferramentas da IA
async def classificar_paradas(ctx: ger.Contexto, a: dict) -> dict:
    """Começa o passo a passo: o SISTEMA manda o resumo com os botões (`ctx.fluxo`); a IA não escreve nada."""
    if ctx.mw is None or not ctx.usinas:
        raise ger.Recusa(_sem_meuwatt(ctx))
    ini, fim = ger._periodo(a.get("inicio"), a.get("fim"))
    if (fim - ini).days >= MAX_DIAS:
        raise ger.Recusa(f"Pelo WhatsApp eu classifico até {MAX_DIAS} dias por vez.")
    slug = ger._usina(ctx, a["usina"])["slug"] if (a.get("usina") or "").strip() else None
    ctx.fluxo = await comecar(ctx, ini, fim, slug)
    return {"ok": True, "instrucao": "O SISTEMA já manda o resumo com os botões e conduz a classificação. Não escreva "
                                     "nada sobre ela."}


async def paradas_a_classificar(ctx: ger.Contexto, a: dict) -> dict:
    """Quantas paradas faltam classificar no período, por usina (a aba "A classificar" da tela de Paradas)."""
    if ctx.mw is None or not ctx.usinas:
        raise ger.Recusa(_sem_meuwatt(ctx))
    ini, fim = ger._periodo(a.get("inicio"), a.get("fim"))
    if (fim - ini).days >= MAX_DIAS:
        raise ger.Recusa(f"Conto as paradas a classificar de até {MAX_DIAS} dias por vez.")
    slug = ger._usina(ctx, a["usina"])["slug"] if (a.get("usina") or "").strip() else None
    todas, extras = await _ler(ctx, ini, fim, slug)
    return {"inicio": ini.isoformat(), "fim": fim.isoformat(), "usinas": [
        {"usina": ctx.usinas[s]["nome"], "a_classificar": sum(1 for u in todas if u["usina"] == s),
         "ja_classificadas": e.get("classificadas"), "sem_registro_ao_vivo": e.get("sem_vivo"), "erro": e.get("erro")}
        for s, e in extras.items()],
        "nota": ("Contagem da aba 'A classificar' da tela de Paradas do meuWatt (paradas simultâneas contam como uma). "
                 "erro preenchido = não conferi aquela usina (não diga zero). Para classificar pelo WhatsApp, "
                 "chame classificar_paradas.")}


_PERIODO = {"inicio": {"type": "string", "description": "AAAA-MM-DD (vazio = hoje)"},
            "fim": {"type": "string", "description": "AAAA-MM-DD (vazio = o mesmo dia do início)"},
            "usina": {"type": "string", "description": "Só esta usina (vazio = todas as da pessoa)"}}
FERRAMENTAS = {
    "classificar_paradas": (classificar_paradas, {"type": "function", "function": {
        "name": "classificar_paradas",
        "description": ("COMEÇA a classificação das paradas pelo WhatsApp, passo a passo com botões (o sistema conduz: "
                        "resumo, cada parada, motivo › origem › causa › causa raiz, causa externa, observação, OS, "
                        "conferir e gravar no meuWatt). Use quando a pessoa quer CLASSIFICAR paradas ('classificar as "
                        "paradas', 'o que caiu hoje', 'vamos classificar as de ontem'). Depois de chamar, não escreva "
                        "nada sobre a classificação."),
        "parameters": {"type": "object", "properties": _PERIODO}}}),
    "paradas_a_classificar": (paradas_a_classificar, {"type": "function", "function": {
        "name": "paradas_a_classificar",
        "description": ("QUANTAS paradas faltam classificar no período, por usina (e quantas já foram), sem começar a "
                        "classificar. Paradas em si (quantas houve, perda, causa, inversor) é `paradas`."),
        "parameters": {"type": "object", "properties": _PERIODO}}}),
}
