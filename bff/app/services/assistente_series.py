"""Séries no tempo de qualquer consulta do catálogo: achar, desenhar e analisar.

O dono, 17/11/2026, pelo bot: "Gere um gráfico da potência do relé com a potência dos inversores de Pirapozinho do
skid 1", "Plote o gráfico da string 1 do inversor 1 do skid 1 com a string 10 do inversor 2 do skid 3", "gráfico da
resistência de isolação, gráfico com temperatura do trafo com potência do inversor 2 e 3 … gráfico de barra com
potências diárias, energias, etc. Análises." O bot não fazia: o gráfico lia um formato só, de uma consulta só, e a
consulta chegava cortada em 120 mil caracteres.

Aqui: o dado inteiro de cada consulta (o conector do meuWatt o devolve com `_completo`), um leitor que entende os
formatos das consultas — por equipamento (relés, sondas), por instante (inversores e strings a cada 5 min), lista de
leituras (isolação) e colunas (grandezas) —, os equipamentos pelo nome que a pessoa usa (Inv 12, Skid 1, TR-02, Relé
Skid 1, "inversor 2 do skid 3"), o desenho (linha no tempo, barras por dia, dois eixos quando são duas unidades) e a
análise que vai à IA (mínimo e máximo com a hora, média, último e a correlação entre as séries). Os pontos nunca passam
pela IA: ela recebe a análise.
"""

import asyncio
import io
import itertools
import json
import math
import re
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.datas import BRT
from app.services import assistente_geracao as ger

# --------------------------------------------------------------------------- o leitor
_TEMPO = ("time", "timestamp", "ts", "datetime", "instante", "hora", "hour", "h", "date", "data", "dia", "t", "bucket",
          "start", "inicio")
_COLUNA_TEMPO = ("timestamps", "times", "tempos", "horas", "datas", "dates")
_COLUNA_VALOR = ("values", "valores", "y")
#: o que nomeia o equipamento de um item, na ordem em que vira o nome mostrado
_NOME = ("label", "name", "nome", "rotulo", "slot_label", "serial_number", "sn", "serial", "slot_id", "relay_id",
         "sensor_id", "inverter_id", "unidade", "id", "plant", "usina", "key")
_CAMPO_DA_COLUNA = ("grandeza", "metric", "metrica", "campo", "field")
#: número que não é medida (fica fora quando a pessoa não diz o que quer desenhar)
_NAO_MEDIDA = re.compile(r"(^|_)(id|position|posicao|slave|ordem|index|count|n|status|code|codigo|year|month|ano|mes|"
                         r"capacity|capacidade|kwp|decimals|lat|lon)$")
_LISTA_ALIAS = {"strings": "pv", "string_currents": "pv", "pvs": "pv", "pv": "pv", "mppts": "mppt", "mppt": "mppt"}

Ent = tuple[tuple[str, str], ...]          # o equipamento: (chave, valor) de cada nome que o item trouxe
Obs = dict[tuple[Ent, str], list[tuple[datetime, float]]]


def _numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def instante(v, dia: date) -> datetime | None:
    """Hora de Brasília de um valor do eixo do tempo. "HH:MM" é do `dia` da consulta; ISO sem fuso já é Brasília (regra
    da casa); com fuso, convertido."""
    if not isinstance(v, str) or not v:
        return None
    if m := re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", v):
        if int(m[1]) > 23:
            return None
        return datetime(dia.year, dia.month, dia.day, int(m[1]), int(m[2]), int(m[3] or 0), tzinfo=BRT)
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=BRT) if d.tzinfo is None else d.astimezone(BRT)


def _dia_do(dados, padrao: date) -> date:
    if isinstance(dados, dict):
        for k in ("date", "data", "dia"):
            v = dados.get(k)
            if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                return date.fromisoformat(v)
    return padrao


def observacoes(dados, dia: date) -> Obs:
    """Toda medida no tempo do JSON, por (equipamento, campo). Entende: o item com hora (`time`) e números; a lista de
    números no item com hora (`strings` = pv1…pv32); a coluna de valores alinhada a uma coluna de horas
    (`timestamps` + `values`, o campo vindo de `grandeza`); e o equipamento como o item de lista que tem nome."""
    dia = _dia_do(dados, dia)
    obs: Obs = defaultdict(list)

    def anda(no, t: datetime | None, ent: Ent, colunas: list | None, e_item: bool) -> None:
        if isinstance(no, list):
            for item in no:
                anda(item, t, ent, colunas, True)
            return
        if not isinstance(no, dict):
            return
        tempos = next((no[k] for k in _COLUNA_TEMPO if isinstance(no.get(k), list) and no[k]), None)
        if tempos is not None:
            colunas = [instante(x, dia) for x in tempos]
        t2 = next((x for k in _TEMPO if (x := instante(no.get(k), dia)) is not None), t)
        hora = next((no[k] for k in ("hour", "hora", "h") if isinstance(no.get(k), int)
                     and not isinstance(no.get(k), bool) and 0 <= no[k] <= 23), None)
        if hora is not None:    # a curva hora a hora traz a hora em número: as 24 horas do dia, não um ponto só
            t2 = datetime(dia.year, dia.month, dia.day, hora, tzinfo=BRT)
        nomes = tuple((k, str(no[k]).strip()) for k in _NOME
                      if isinstance(no.get(k), (str, int)) and not isinstance(no.get(k), bool) and str(no[k]).strip())
        ent2 = ent + nomes if e_item and nomes else ent
        campo_col = next((str(no[k]) for k in _CAMPO_DA_COLUNA if isinstance(no.get(k), str)), None)
        for k, v in no.items():
            if k in _TEMPO or k in _NOME or k in _COLUNA_TEMPO or k in _CAMPO_DA_COLUNA:
                continue
            if _numero(v):
                if t2 is not None:
                    obs[(ent2, k)].append((t2, float(v)))
            elif isinstance(v, list) and v and all(x is None or _numero(x) for x in v):
                if colunas is not None and len(v) == len(colunas) and (k in _COLUNA_VALOR or campo_col):
                    for ti, x in zip(colunas, v):
                        if ti is not None and x is not None:
                            obs[(ent2, campo_col or k)].append((ti, float(x)))
                elif t2 is not None:
                    pre = _LISTA_ALIAS.get(k, f"{k}_")
                    for i, x in enumerate(v):
                        if x is not None:
                            obs[(ent2, f"{pre}{i + 1}")].append((t2, float(x)))
            elif isinstance(v, (dict, list)):
                anda(v, t2, ent2, colunas, isinstance(v, list))

    anda(dados, None, (), None, False)
    return obs


# --------------------------------------------------------------------------- os nomes que a pessoa usa
_PALAVRAS = {"inversor": "inv", "inversores": "inv", "inverter": "inv", "transformador": "tr", "trafo": "tr",
             "trafos": "tr", "posicao": "pos", "position": "pos", "rele": "rele", "reles": "rele", "relay": "rele",
             "string": "pv", "strings": "pv", "sonda": "s", "sensor": "s"}
_VAZIAS = {"o", "a", "os", "as", "do", "da", "dos", "das", "de", "e", "no", "na", "num", "numa", "com", "the", "of"}


def chave(texto: str) -> str:
    """Forma comparável de um nome: sem acento, caixa, espaço e zero à esquerda, com as palavras da casa ("Inv 12" →
    inv12, "SKID-01" → skid1, "inversor 2 do skid 3" → inv2skid3, "trafo 2" → tr2, "string 10" → pv10)."""
    partes = []
    norm = re.sub(r"\bfase\s+([abc])\b", r"fase\1", ger._norm(str(texto)))      # o "a" de "fase a" não é artigo
    for p in re.findall(r"[a-z]+|\d+", norm):
        if p.isdigit():
            partes.append(str(int(p)))
        elif p not in _VAZIAS:
            partes.append(_PALAVRAS.get(p, p))
    return "".join(partes)


def _pecas(nome: str) -> set[str]:
    """As formas de chamar um nome: ele mesmo e, se tem skid/trafo N, "skidN" e "trN" (no meuWatt o skid se chama TR-01
    em Pirapozinho e SKID-02 em Porto Ferreira; a sonda de temperatura, TEMP-SKID-02)."""
    c = chave(nome)
    out = {c} if c else set()
    for m in re.finditer(r"(?:skid|tr)(\d+)", c):
        out |= {f"skid{m[1]}", f"tr{m[1]}"}
    return out


@dataclass
class Equip:
    exibir: str
    pecas: set[str]
    serial: str | None = None


Apelidos = dict[tuple[str, str], Equip]    # (chave do nome, valor) → o equipamento


def apelidos_do_meuwatt(inversores, catalogo, slug: str) -> Apelidos:
    """Do cadastro do meuWatt: cada vaga de inversor pelo número de série, pela vaga (slot) e pelo rótulo vira
    "Inv 12 (TR-01)", chamável por inv12, skid1/tr1 e pela posição no skid (skid1pos1 = "inversor 1 do skid 1"); cada
    trafo pelo id (a `unidade` das grandezas por skid)."""
    skids = {int(s["id"]): str(s.get("name") or s["id"])
             for p in (catalogo or {}).get("plants") or [] if p.get("slug") == slug for s in p.get("skids") or []
             if s.get("id") is not None}
    mapa: Apelidos = {}
    lista = inversores.get("itens") if isinstance(inversores, dict) else inversores
    vagas = [s for s in lista or [] if isinstance(s, dict) and s.get("label")]

    def skid_de(s: dict) -> str | None:
        return next((m[1] for m in re.finditer(r"(?:skid|tr)(\d+)", chave(skids.get(s.get("transformer_id")) or ""))),
                    None)

    # "inversor 1 do skid 1": em Pirapozinho e em Porto Ferreira o rótulo já diz — Inv 11 é o skid 1, inversor 1 (a
    # POSIÇÃO no cadastro pode ser outra: lá, a 1 é o Inv 12). Vale o rótulo quando todo inversor do skid segue a regra;
    # senão, a posição.
    pelo_rotulo = {sk for sk in {skid_de(s) for s in vagas} if sk and all(
        re.fullmatch(rf"inv{sk}\d", chave(s["label"])) for s in vagas if skid_de(s) == sk)}
    for s in vagas:
        tr = skids.get(s.get("transformer_id"))
        pecas = _pecas(s["label"]) | (_pecas(tr) if tr else set())
        n = skid_de(s)
        k = chave(s["label"])[-1] if n in pelo_rotulo else s.get("position")
        if n and s.get("position") is not None:
            pecas |= {f"skid{n}pos{int(s['position'])}", f"pos{int(s['position'])}skid{n}"}
        if n and k is not None:
            pecas |= {f"skid{n}inv{k}", f"inv{k}skid{n}", f"tr{n}inv{k}", f"inv{k}tr{n}"}
        serial = (s.get("current_assignment") or {}).get("serial_number")
        eq = Equip(f"{s['label']} ({tr})" if tr else str(s["label"]), pecas, serial)
        for k, v in (("slot_id", s.get("id")), ("serial_number", serial), ("label", s["label"])):
            if v is not None and v != "":
                mapa[(k, str(v))] = eq
    for tid, nome in skids.items():
        mapa[("unidade", str(tid))] = Equip(nome, _pecas(nome))
        mapa[("transformer_id", str(tid))] = Equip(nome, _pecas(nome))
    return mapa


def equipamento(ent: Ent, apelidos: Apelidos) -> Equip:
    """O nome mostrado e as formas de chamar um equipamento do JSON (o cadastro primeiro; senão, os nomes que ele
    trouxe)."""
    achados = [apelidos[(k, v)] for k, v in ent if (k, v) in apelidos]
    pecas = set().union(*(e.pecas for e in achados)) if achados else set()
    for _k, v in ent:
        pecas |= _pecas(v) | {v.lower()}
    nome = achados[0].exibir if achados else next((v for k, v in ent if k in ("label", "name", "nome", "rotulo")),
                                                  ent[0][1] if ent else "")
    serial = next((v for k, v in ent if k == "serial_number"), None) or next((e.serial for e in achados if e.serial),
                                                                               None)
    return Equip(nome, pecas, serial)


def casa_equipamento(so: str, eq: Equip) -> bool:
    c = chave(so)
    if not c:
        return False
    if c in eq.pecas or so.strip().lower() in eq.pecas or c == chave(eq.exibir):
        return True
    antes = so.split("(")[0]                        # "Inv 12 (TR-01)", o nome que o bot mostra: vale o "Inv 12"
    return antes != so and chave(antes) in eq.pecas


# --------------------------------------------------------------------------- os campos e as unidades
_SINONIMOS = (
    ("potenciaativa", ("activepower", "potenciaativa", "powerkw", "power", "potencia")),
    ("potencia", ("power", "potencia", "kw")),
    ("corrente", ("current", "corrente", "pv", "mppt")),
    ("tensao", ("voltage", "tensao")),
    ("temperatura", ("temp",)),
    ("irradiancia", ("poa", "ghi", "irradi")),
    ("irradiacao", ("irradiacao", "poa", "ghi")),
    ("energia", ("kwh", "energia", "energy", "gen")),
    ("geracao", ("kwh", "energia", "energy", "gen")),
    ("isolacao", ("insulation", "isolacao", "mohm")),
    ("resistencia", ("insulation", "mohm", "resist")),
    ("frequencia", ("freq",)),
    ("produtividade", ("produtividade", "yield")),
    ("pr", ("pr",)),
)
_NAO_E_POTENCIA = ("kwh", "kwp", "fator", "factor", "pf", "reativa", "reactive", "aparente", "apparent")
_UNIDADES = (
    (r"kwhkwp|produtividade", "kWh/kWp"), (r"kwkwp|especifica", "kW/kWp"), (r"irradiacao|kwhm2", "kWh/m²"),
    (r"mohm|insulation|isolacao", "MΩ"), (r"temp", "°C"), (r"kwh|energia|energy|gen", "kWh"),
    (r"power|potencia|kw", "kW"), (r"^pv\d|^mppt\d|current|corrente", "A"), (r"voltage|tensao", "V"),
    (r"poa|ghi|irradi", "W/m²"), (r"freq", "Hz"), (r"^pr|pr$|percent|pct", "%"),
)


def unidade(campo: str) -> str:
    c = chave(campo)
    return next((u for padrao, u in _UNIDADES if re.search(padrao, c)), "")


def nome_do_campo(campo: str) -> str:
    c = chave(campo)
    if m := re.fullmatch(r"pv(\d+)", c):
        return f"string {m[1]}"
    if m := re.fullmatch(r"mppt(\d+)", c):
        return f"MPPT {m[1]}"
    return {"powerkw": "potência", "totalactivepower": "potência ativa", "insulationmohm": "isolação",
            "dailygenkwh": "energia do dia", "temps1": "sonda 1", "temps2": "sonda 2", "temps3": "sonda 3",
            "temps4": "sonda 4", "tempambient": "ambiente", "temperature": "temperatura"}.get(c, campo)


def campos_pedidos(pedidos: list[str], disponiveis: list[str]) -> list[str]:
    """Os campos do JSON que respondem ao que a pessoa pediu: o nome exato primeiro ("pv10", "temp_s1"), depois a
    palavra ("potência", "corrente", "isolação"…), depois um pedaço do nome. Sem pedido: toda medida."""
    if not pedidos:
        return [d for d in disponiveis if not _NAO_MEDIDA.search(d)]
    out: list[str] = []
    # o nome do campo inteiro, sem tirar "artigo": o "a" de active_power_a é a fase
    norm = {d: re.sub(r"[^a-z0-9]", "", ger._norm(d)) for d in disponiveis}
    for p in pedidos:
        c = chave(p)
        exatos = [d for d, n in norm.items() if n == c]
        if not exatos and (grupo := next((frags for k, frags in _SINONIMOS if c.startswith(k)), None)):
            fase = re.fullmatch(r"\D+fase([abc])", c)
            exatos = [d for d, n in norm.items() if any(f in n for f in grupo)
                      and not (c.startswith("potencia") and any(x in n for x in _NAO_E_POTENCIA))
                      and (not fase or n.endswith(fase[1]))]
        if not exatos and c:
            exatos = [d for d, n in norm.items() if c in n]
        if len(exatos) > 1 and "fase" not in c and any("total" in norm[d] for d in exatos):
            exatos = [d for d in exatos if "total" in norm[d]]      # a potência do relé é a total, não as 3 fases
        out += [d for d in exatos if d not in out]
    return out


# --------------------------------------------------------------------------- séries
@dataclass
class Serie:
    rotulo: str
    unidade: str
    pontos: list[tuple[datetime, float]]
    equipamento: str = ""
    grupo: int = 0
    campo: str = ""
    serial: str | None = None
    estilo: str = ""                       # "limite": a linha de referência (tracejada, uma só)
    achados: dict | None = None            # o nome que a pessoa usou → o equipamento do cadastro
    sem_com_desde: datetime | None = None  # o equipamento está sem comunicação: os zeros depois disto não são leitura


def series_de(obs: Obs, apelidos: Apelidos, campos: list[str], so: list[str], somar: bool = False,
              rotulo: str | None = None) -> tuple[list[Serie], dict]:
    """As séries pedidas de uma consulta. Quando nada casa, o que existe (os equipamentos e os campos), para a IA
    acertar na próxima sem ler os dados."""
    equipos: dict[Ent, Equip] = {}
    for ent, _c in obs:
        if ent not in equipos:
            equipos[ent] = equipamento(ent, apelidos)
    escolhidos = [e for e in equipos if not so or any(casa_equipamento(s, equipos[e]) for s in so)]
    if so and not escolhidos:   # o nome pela metade ("relé" para os relés): um pedaço de alguma forma de chamar
        cs = [c for c in map(chave, so) if len(c) >= 3]
        escolhidos = [e for e in equipos if any(c in p for c in cs for p in equipos[e].pecas)]
    disponiveis = list(dict.fromkeys(c for (e, c) in obs if e in escolhidos))
    quais = campos_pedidos(campos, disponiveis)
    out = []
    for (ent, campo), pts in obs.items():
        if ent in escolhidos and campo in quais and len(pts) >= 1:
            pts = sorted({t: v for t, v in pts}.items())
            eq = equipos[ent].exibir
            nome = nome_do_campo(campo)
            out.append(Serie(f"{eq} · {nome}" if eq else nome, unidade(campo), pts, eq, campo=campo,
                             serial=equipos[ent].serial))
    out.sort(key=lambda x: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", x.rotulo)])
    if somar and out:
        soma: dict[datetime, float] = defaultdict(float)
        for s in out:
            for t, v in s.pontos:
                soma[t] += v
        eqs = ", ".join(dict.fromkeys(s.equipamento for s in out if s.equipamento))
        out = [Serie(rotulo or f"soma de {len(out)} séries", out[0].unidade, sorted(soma.items()), eqs)]
    elif rotulo and len(out) == 1:
        # o rótulo da IA, mas o nome do cadastro junto: "inversor 1 do skid 1" tem de dizer QUAL é (Inv 11 (TR-01))
        eq = out[0].equipamento
        out[0].rotulo = rotulo if not eq or chave(eq.split(" (")[0]) in chave(rotulo) else f"{rotulo} — {eq}"
    if out:
        achados = {x: sorted({equipos[e].exibir for e in escolhidos if casa_equipamento(x, equipos[e])}) for x in so}
        return out, ({"_achados": achados} if so else {})
    existe = {"equipamentos": [equipos[e].exibir for e in escolhidos or list(equipos)][:24],
              "campos": [f"{c} ({unidade(c) or '—'})" for c in disponiveis][:40]}
    if so and not escolhidos:
        sem_inversor = any(re.search(r"inv\d", chave(x)) for x in so) and not any(
            re.search(r"inv\d", p) for eq in equipos.values() for p in eq.pecas)
        return [], {"erro": f"Nenhum equipamento com {', '.join(so)} nesta consulta.",
                    "equipamentos": [eq.exibir for eq in equipos.values()][:24],
                    **({"dica": "Esta consulta não separa por inversor (só usina, skid ou sensor): a curva de 5 em 5 "
                                "min (curva_5min) traz a potência de cada inversor."} if sem_inversor else {})}
    return [], {"erro": "Nenhum campo com o que foi pedido nesta consulta.", **existe}


def _quando(t: datetime, diario: bool, varios_dias: bool) -> str:
    return t.strftime("%d/%m") if diario else (t.strftime("%d/%m %H:%M") if varios_dias else t.strftime("%H:%M"))


def e_diario(series: list[Serie]) -> bool:
    ts = sorted({t for s in series for t, _ in s.pontos})
    return bool(ts) and all(t.hour == 0 and t.minute == 0 for t in ts) and \
        all(b - a >= timedelta(hours=20) for a, b in itertools.pairwise(ts))


#: unidades de geração: começa, para, a média é só com sol e a energia é a integral
_DE_SOL = ("kW", "kW/kWp", "A", "W/m²")
_LIMITE = re.compile(r"threshold|limite|limit|alarm|trip|setpoint")


def _patamar(pts: list[tuple[datetime, float]]) -> dict | None:
    """O trecho mais longo (≥ 45 min) em que a série fica parada num valor que não é zero: o teto (1.000 kW de um skid
    de 4 × 250 kW, os 5 MW de Porto Ferreira) ou a sonda que travou (99,7 °C das 10:55 às 12:45 em Pirapozinho)."""
    if len(pts) < 4:
        return None
    vals = [v for _t, v in pts]
    faixa = max(vals) - min(vals)
    tol = max(0.3, 0.004 * faixa)
    passos = sorted(b[0] - a[0] for a, b in itertools.pairwise(pts))
    junto = max(timedelta(minutes=20), passos[len(passos) // 2] * 1.5)
    melhor, i = None, 0
    while i < len(pts):
        j = i
        while j + 1 < len(pts) and abs(pts[j + 1][1] - pts[i][1]) <= tol and pts[j + 1][0] - pts[j][0] <= junto:
            j += 1
        dur = pts[j][0] - pts[i][0]
        if dur >= timedelta(minutes=45) and abs(pts[i][1]) > 0.02 * (max(abs(v) for v in vals) or 1) and \
                (melhor is None or dur > melhor[2]):
            melhor = (i, j, dur)
        i = j + 1
    if melhor is None:
        return None
    i, j, dur = melhor
    trecho = [v for _t, v in pts[i:j + 1]]
    return {"valor": round(statistics.fmean(trecho), 2), "de": pts[i][0].strftime("%H:%M"),
            "ate": pts[j][0].strftime("%H:%M"), "minutos": int(dur.total_seconds() // 60)}


def _energia(pts: list[tuple[datetime, float]]) -> float:
    """kWh de uma potência em kW: a área sob a curva, sem atravessar buraco de leitura de mais de 30 min."""
    e = 0.0
    for (t0, v0), (t1, v1) in itertools.pairwise(pts):
        h = (t1 - t0).total_seconds() / 3600
        if 0 < h <= 0.5:
            e += (v0 + v1) / 2 * h
    return round(e, 1)


def analise(series: list[Serie]) -> dict:
    """O que a IA comenta, já com os números certos para cada coisa: o máximo e o mínimo com a hora; nas grandezas de
    sol, quando começou e parou, a média só com sol e a energia do dia; o patamar (o teto ou a sonda travada); quem
    passou do limite e quando; e, entre equipamentos ou pedidos diferentes, se as curvas andam juntas e a comparação
    NOS MESMOS horários (a avaliação de 17/11/2026 pegou médias de horários diferentes lado a lado)."""
    diario = e_diario(series)
    dias = {t.date() for s in series for t, _ in s.pontos}
    varios = len(dias) > 1
    limites = [s for s in series if s.estilo == "limite"]
    out = []
    for s in series:
        if s.estilo == "limite":
            out.append({"serie": s.rotulo, "unidade": s.unidade, "limite": s.pontos[0][1]})
            continue
        vals = [v for _t, v in s.pontos]
        mn = min(s.pontos, key=lambda p: p[1])
        mx = max(s.pontos, key=lambda p: p[1])
        item = {"serie": s.rotulo, **({"equipamento": s.equipamento} if s.equipamento else {}), "unidade": s.unidade,
                "leituras": len(vals), "maximo": [round(mx[1], 3), _quando(mx[0], diario, varios)],
                "minimo": [round(mn[1], 3), _quando(mn[0], diario, varios)],
                "primeira_leitura": _quando(s.pontos[0][0], diario, varios),
                "ultima_leitura": [round(s.pontos[-1][1], 3), _quando(s.pontos[-1][0], diario, varios)]}
        if s.unidade in _DE_SOL and not diario:
            ativos = [(t, v) for t, v in s.pontos if v > 0.01 * (mx[1] or 1)]
            if ativos:
                item.update(comecou=_quando(ativos[0][0], False, varios), parou=_quando(ativos[-1][0], False, varios),
                            media_com_sol=round(statistics.fmean(v for _t, v in ativos), 2))
            if s.unidade == "kW":
                item["energia_kwh"] = _energia(s.pontos)
        else:
            item["media"] = round(statistics.fmean(vals), 3)
        if diario or s.unidade in ("kWh", "kWh/m²"):
            item["soma"] = round(sum(vals), 2)
        if not diario and (pat := _patamar(s.pontos)):
            item["patamar"] = pat
        for lim in limites:
            if lim.unidade == s.unidade:
                ref = lim.pontos[0][1]
                fora = [t for t, v in s.pontos if (v < ref if s.unidade == "MΩ" else v > ref)]
                item["passou_do_limite"] = {"leituras": len(fora), "dias": sorted({t.strftime("%d/%m") for t in fora})}
        if s.sem_com_desde:
            item["sem_comunicacao_desde"] = s.sem_com_desde.strftime("%d/%m %H:%M")
        out.append(item)
    pares = []
    reais = [s for s in series if s.estilo != "limite"]
    for i in range(len(reais)):
        for j in range(i + 1, len(reais)):
            a, b = reais[i], reais[j]
            if a.grupo == b.grupo and a.equipamento == b.equipamento:
                continue                  # as fases do mesmo relé andam juntas: comparação que não diz nada
            da, db = dict(a.pontos), dict(b.pontos)
            comum = sorted(set(da) & set(db))
            if len(comum) < 8 or len(pares) >= 6:
                continue
            x, y = [da[t] for t in comum], [db[t] for t in comum]
            par: dict = {"entre": [a.rotulo, b.rotulo], "horarios_em_comum": len(comum)}
            if statistics.pstdev(x) > 0 and statistics.pstdev(y) > 0:
                par["andam_juntas"] = round(statistics.correlation(x, y), 2)   # 1 = sobem e descem juntas
            if a.unidade == b.unidade:
                ma, mb = statistics.fmean(x), statistics.fmean(y)
                par["medias_nos_mesmos_horarios"] = [round(ma, 2), round(mb, 2)]
                if mb:
                    par["diferenca_pct"] = round((ma / mb - 1) * 100, 2)
                if a.unidade == "kW":
                    par["energia_kwh_nos_mesmos_horarios"] = [_energia([(t, da[t]) for t in comum]),
                                                              _energia([(t, db[t]) for t in comum])]
            pares.append(par)
    return {"series": out, **({"comparacoes": pares} if pares else {})}


def titulo_com_data(titulo: str, series: list[Serie]) -> str:
    """Título com a data por extenso (dd/mm/aaaa): a data ISO da IA vira a nossa; sem data, entra a do gráfico."""
    titulo = re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda m: f"{m[3]}/{m[2]}/{m[1]}", titulo)
    titulo = re.sub(r"\s*[(·-]?\s*\bhoje\b\s*\)?", "", titulo, flags=re.IGNORECASE).strip(" ·-")
    if re.search(r"\d{1,2}/\d{1,2}", titulo) or not series:
        return titulo
    ts = [t for s in series for t, _ in s.pontos]
    a, b = min(ts).date(), max(ts).date()
    quando = a.strftime("%d/%m/%Y") if a == b else f"{a:%d/%m} a {b:%d/%m/%Y}"
    return f"{titulo} · {quando}"


def _br(v: float, _pos=None) -> str:
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- desenho
def desenhar(series: list[Serie], titulo: str, tipo: str = "auto") -> bytes:
    """Linha no tempo (o padrão) ou barras por dia (série diária, ou `tipo=barras`). Duas unidades = dois eixos: a 2ª
    à direita, tracejada (nas barras, vira linha por cima). O limite é UMA linha vermelha tracejada. Num dia, buraco de
    leitura quebra a linha (o gráfico não liga dois pontos por cima do que não foi lido); em vários dias, a leitura
    esparsa (a isolação de cada partida) vai ligada e com o ponto marcado. Até 20 cores; números no formato do Brasil."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    unidades = list(dict.fromkeys(s.unidade for s in series))
    barras = tipo == "barras" or (tipo == "auto" and e_diario(series))
    fig, ax = plt.subplots(figsize=(11, 5.4), dpi=110)
    eixos = {unidades[0]: ax}
    if len(unidades) > 1:
        eixos[unidades[1]] = ax.twinx()
    reais = [s for s in series if s.estilo != "limite"]
    paleta = plt.get_cmap("tab10" if len(reais) <= 10 else "tab20").colors
    cor = {id(s): paleta[k % len(paleta)] for k, s in enumerate(reais)}
    linhas_leg = []
    todos = [t for s in series for t, _ in s.pontos]
    if barras:
        dias = sorted({t.date() for s in series for t, _ in s.pontos})
        pos = {d: i for i, d in enumerate(dias)}
        nas_barras = [s for s in reais if s.unidade == unidades[0]]
        larg = 0.8 / max(1, len(nas_barras))
        for k, s in enumerate(nas_barras):
            xs = [pos[t.date()] + (k - (len(nas_barras) - 1) / 2) * larg for t, _ in s.pontos]
            linhas_leg.append(ax.bar(xs, [v for _t, v in s.pontos], larg, label=s.rotulo, color=cor[id(s)]))
        for s in series:
            if s in nas_barras:
                continue
            if s.estilo == "limite":
                (ln,) = eixos[s.unidade].plot([-0.5, len(dias) - 0.5], [s.pontos[0][1]] * 2, "--", color="#d62728",
                                              linewidth=1.3, label=s.rotulo)
            else:
                (ln,) = eixos[s.unidade].plot([pos[t.date()] for t, _ in s.pontos], [v for _t, v in s.pontos], "o--",
                                              color=cor[id(s)], label=s.rotulo)
            linhas_leg.append(ln)
        passo = max(1, len(dias) // 16)
        ax.set_xticks(range(0, len(dias), passo))
        ax.set_xticklabels([d.strftime("%d/%m") for d in dias][::passo], fontsize=8,
                           rotation=45 if len(dias) > 10 else 0)
    else:
        varios_dias = max(todos) - min(todos) > timedelta(days=2)
        for s in series:
            if s.estilo == "limite":
                (ln,) = eixos[s.unidade].plot([min(todos), max(todos)], [s.pontos[0][1]] * 2, "--", color="#d62728",
                                              linewidth=1.3, label=s.rotulo)
                linhas_leg.append(ln)
                continue
            xs = [t for t, _ in s.pontos]
            px, py = [], []
            passos = sorted((b - a).total_seconds() for a, b in itertools.pairwise(xs)) or [300.0]
            limite = 3 * passos[len(passos) // 2]
            for i, (t, v) in enumerate(s.pontos):
                if i and not varios_dias and (t - xs[i - 1]).total_seconds() > max(limite, 1200):
                    px.append(xs[i - 1] + (t - xs[i - 1]) / 2)
                    py.append(float("nan"))
                px.append(t)
                py.append(v)
            segundo = len(unidades) > 1 and s.unidade == unidades[1]
            (ln,) = eixos[s.unidade].plot(px, py, "--" if segundo else "-", linewidth=1.4, color=cor[id(s)],
                                          label=s.rotulo, marker="." if len(xs) < 400 else None, markersize=3)
            linhas_leg.append(ln)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m" if varios_dias else "%H:%M", tz=BRT))
        fig.autofmt_xdate()
    for u, eixo in eixos.items():
        eixo.set_ylabel(u)
        eixo.yaxis.set_major_formatter(FuncFormatter(_br))
    ax.set_title(titulo, fontsize=11)
    ax.grid(axis="y", alpha=.3)
    if len(series) > 1 or len(unidades) > 1:
        ax.legend(linhas_leg, [h.get_label() for h in linhas_leg], fontsize=7 if len(series) > 8 else 8, loc="best",
                  ncol=2 if len(series) > 8 else 1)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------------------- a ferramenta
MAX_SERIES = 16
FERRAMENTA_GRAFICO = {"type": "function", "function": {
    "name": "grafico_de_series",
    "description": ("Para pedido de GRÁFICO: desenha no chat séries no tempo (ou barras por dia) de uma ou mais "
                    "consultas do catálogo, juntas, e devolve a análise (mínimo, máximo, média, correlação)."),
    "parameters": {"type": "object", "properties": {
        "series": {"type": "array", "description": "uma entrada por consulta", "items": {
            "type": "object", "properties": {
                "consulta": {"type": "string", "description": "o nome da consulta do catálogo"},
                "argumentos": {"type": "object", "description": "os parâmetros dela (slug, date…)"},
                "campos": {"type": "array", "items": {"type": "string"},
                           "description": "o que desenhar: o nome do campo ou a palavra (potência, corrente, tensão, "
                                          "temperatura, isolação, energia, pv10…); vazio = tudo"},
                "so": {"type": "array", "items": {"type": "string"},
                       "description": "só estes equipamentos, pelo nome (Inv 12, Skid 1, TR-02, Relé Skid 1, "
                                      "inversor 2 do skid 3)"},
                "somar": {"type": "boolean", "description": "uma linha só, com a soma dos equipamentos"},
                "rotulo": {"type": "string"}},
            "required": ["consulta"]}},
        "tipo": {"type": "string", "enum": ["auto", "linha", "barras"]},
        "titulo": {"type": "string"}},
        "required": ["series"]}}}

_APELIDOS: dict[tuple[int, str], tuple[float, Apelidos]] = {}
CACHE_S = 600


def dados_de(r: dict):
    """O JSON de uma resposta do conector: o inteiro (`structuredContent`) ou o texto, se ele for JSON."""
    if isinstance(r.get("structuredContent"), (dict, list)):
        return r["structuredContent"]
    texto = "".join(c.get("text") or "" for c in r.get("content") or [] if c.get("type") == "text")
    try:
        return json.loads(texto)
    except ValueError:
        return None


async def chamar(ctx, nome: str, args: dict) -> dict:
    from app.api.v1 import mcp
    if nome.startswith("monitoramento_"):        # o inteiro: o texto do conector para nos 120 mil caracteres
        args = {**args, "_completo": True}
    return await mcp._chamar(ctx.db, ctx.user, nome, args)


async def apelidos(ctx, nome: str, args: dict) -> Apelidos:
    slug = str(args.get("slug") or "")
    if not nome.startswith("monitoramento_") or not slug:
        return {}
    k = (ctx.user.id, slug)
    if (c := _APELIDOS.get(k)) and time.monotonic() - c[0] < CACHE_S:
        return c[1]
    inv, cat = await asyncio.gather(chamar(ctx, "monitoramento_inversores", {"slug": slug}),
                                    chamar(ctx, "monitoramento_grandezas_catalogo", {}))
    mapa = apelidos_do_meuwatt(dados_de(inv) if not inv.get("isError") else None,
                               dados_de(cat) if not cat.get("isError") else None, slug)
    _APELIDOS[k] = (time.monotonic(), mapa)
    return mapa


async def nome_da_consulta(ctx, pedido: str) -> str | None:
    """O nome no catálogo: o exato ou o que termina com o que a IA escreveu ("reles_dia" → monitoramento_reles_dia)."""
    from app.services import assistente_catalogo as cat
    nomes = [t["name"] for t in await cat._catalogo(ctx)]
    if pedido in nomes:
        return pedido
    return next((n for n in nomes if n.endswith(("_" + pedido, pedido))), None)


def dia_dos(args: dict) -> date:
    """O dia de uma consulta (para as horas "HH:MM" dela): o `date`/`start` que ela levou, senão hoje."""
    return next((date.fromisoformat(str(args[k])[:10]) for k in ("date", "data", "dia", "start", "inicio")
                 if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", str(args.get(k) or ""))), ger.hoje())


def _lista(v) -> list[str]:
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v or [] if str(x).strip()]


_COMUNICACAO: dict[tuple[int, str], tuple[float, dict]] = {}
_STRINGS: dict[tuple[int, str, str], tuple[float, dict]] = {}


async def sem_comunicacao(ctx, slug: str) -> dict[str, tuple[datetime, str]]:
    """{número de série: (desde quando, nome)} dos inversores do meuWatt que estão AGORA sem comunicação. O meuWatt grava
    0 kW para eles (17/11/2026: o SKID-02 de Porto Ferreira gerou ~1 MW pelo relé e os Inv 21–24 apareciam zerados):
    zero depois do "desde" não é leitura."""
    k = (ctx.user.id, slug)
    if (c := _COMUNICACAO.get(k)) and time.monotonic() - c[0] < 120:
        return c[1]
    r = await chamar(ctx, "monitoramento_monitoramento_usina", {"slug": slug})
    d = dados_de(r) if not r.get("isError") else None
    out = {}
    for i in (d or {}).get("inverters") or [] if isinstance(d, dict) else []:
        desde = instante(str(i.get("down_since") or ""), ger.hoje())
        if i.get("down") and i.get("down_cause") == "communication_failure" and i.get("serial_number") and desde:
            out[str(i["serial_number"])] = (desde, str(i.get("name") or i["serial_number"]))
    _COMUNICACAO[k] = (time.monotonic(), out)
    return out


async def strings_ligadas(ctx, slug: str, dia: date) -> dict[str, dict[int, str]]:
    """{número de série: {entrada PV: etiqueta}} das strings que o cadastro do meuWatt tem LIGADAS em cada inversor. A
    entrada sem string lê 0 A o dia todo e não é string zerada (17/11/2026: a PV1 não tem string em Pirapozinho)."""
    k = (ctx.user.id, slug, dia.isoformat())
    if (c := _STRINGS.get(k)) and time.monotonic() - c[0] < CACHE_S:
        return c[1]
    r = await chamar(ctx, "monitoramento_leituras_strings", {"slug": slug, "date": dia.isoformat()})
    d = dados_de(r) if not r.get("isError") else None
    out = {str(i["serial_number"]): {int(x["number"]): str(x.get("tag") or "") for x in i.get("strings") or []
                                     if x.get("registered") and x.get("number") is not None}
           for i in ((d or {}).get("inverters") or [] if isinstance(d, dict) else []) if i.get("serial_number")}
    _STRINGS[k] = (time.monotonic(), out)
    return out


def _faixas(nums: list[int]) -> str:
    """[2, 3, 4, 6, 7] → "PV2–4, 6–7"."""
    partes, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        partes.append(f"{nums[i]}–{nums[j]}" if j > i else str(nums[i]))
        i = j + 1
    return "PV" + ", ".join(partes)


async def _serie(ctx, spec: dict) -> tuple[list[Serie], dict]:
    pedido = str(spec.get("consulta") or spec.get("nome") or "")
    nome = await nome_da_consulta(ctx, pedido)
    if nome is None:
        return [], {"consulta": pedido, "erro": "Essa consulta não existe no catálogo.",
                    "sugestoes": await sugestoes(ctx, spec)}
    args = spec.get("argumentos") if isinstance(spec.get("argumentos"), dict) else {}
    slug = str(args.get("slug") or "") if nome.startswith("monitoramento_") else ""
    r, mapa, com = await asyncio.gather(chamar(ctx, nome, args), apelidos(ctx, nome, args),
                                        sem_comunicacao(ctx, slug) if slug else asyncio.sleep(0, {}))
    if r.get("isError"):
        return [], {"consulta": nome, "erro": "".join(c.get("text") or "" for c in r.get("content") or [])[:400]}
    dados = dados_de(r)
    if dados is None:
        return [], {"consulta": nome, "erro": "A consulta não respondeu em JSON (veio cortada): peça um dia só."}
    dia = dia_dos(args)
    obs = observacoes(dados, dia)
    if not obs:
        return [], {"consulta": nome, "erro": "Esta consulta não traz série no tempo (é um total ou um cadastro).",
                    "sugestoes": await sugestoes(ctx, spec)}
    if com:   # zero depois do "sem comunicação desde" é falta de dado: sai do gráfico e das contas
        for (ent, campo), pts in list(obs.items()):
            if (serial := equipamento(ent, mapa).serial) in com:
                obs[(ent, campo)] = [(t, v) for t, v in pts if not (t >= com[serial][0] and v == 0)]
    campos = _lista(spec.get("campos"))
    so = _lista(spec.get("so"))
    calados = {d_n for d_n in com.values() if any(chave(x) == chave(d_n[1]) for x in so)}
    if calados and not any(casa_equipamento(x, equipamento(ent, mapa)) for x in so for ent, _c in obs):
        return [], {"consulta": nome, "erro": "Sem leitura: " + ", ".join(
            f"{n} sem comunicação desde {d:%d/%m %H:%M}" for d, n in sorted(calados)) + ". O que geraram não chegou ao "
            "monitoramento (não é parada); para o skid inteiro, a potência do relé do skid (se houver) mede o que ele "
            "gerou."}
    series, problema = series_de(obs, mapa, campos, so, bool(spec.get("somar")), spec.get("rotulo") or None)
    achados = problema.pop("_achados", None)
    if series and achados:
        for s in series:
            s.achados = achados
    for s in series:
        if s.serial in com:
            s.sem_com_desde = com[s.serial][0]
    series = [s for s in series if s.pontos]
    mudos = {} if series or not com else {
        eq.serial: com[eq.serial] for ent, _c in obs if (eq := equipamento(ent, mapa)).serial in com
        and (not so or any(casa_equipamento(x, eq) for x in so))}
    if mudos:
        return [], {"consulta": nome, "erro": "Sem leitura: " + ", ".join(
            f"{n} sem comunicação desde {d:%d/%m %H:%M}" for d, n in mudos.values()) + ". O que geraram não chegou ao "
            "monitoramento (não é parada); para o skid inteiro, a potência do relé do skid (se houver) mede o que ele "
            "gerou."}
    if slug and any(re.fullmatch(r"pv\d+", s.campo) for s in series):
        ligadas = await strings_ligadas(ctx, slug, dia)
        pedidas = {int(m[1]) for c in campos if (m := re.fullmatch(r"pv(\d+)", chave(c)))}
        sem_string, fica = [], []
        for s in series:
            n = int(s.campo[2:]) if re.fullmatch(r"pv\d+", s.campo) else None
            reg = ligadas.get(s.serial or "") if n is not None else None
            if reg is None:
                fica.append(s)
            elif n in reg:
                s.rotulo = f"{s.rotulo} ({reg[n]})" if reg[n] and reg[n] not in s.rotulo else s.rotulo
                fica.append(s)
            elif n in pedidas:
                perto = min(reg, key=lambda x: (abs(x - n), x)) if reg else None
                sem_string.append(f"A entrada PV{n} do {s.equipamento} não tem string ligada no cadastro (ligadas: "
                                  f"{_faixas(sorted(reg))})" + (f"; a mais próxima é a PV{perto} ({reg[perto]})"
                                                                if perto else "") + ".")
        series = fica
        if sem_string:
            return series, {"consulta": nome, "erro": " ".join(sem_string),
                            "como_seguir": "Não é string zerada: a entrada não tem string. Diga isso à pessoa e "
                                           "ofereça a mais próxima."}
    return series, ({"consulta": nome, **problema} if problema else {})


def _limites_juntos(series: list[Serie]) -> list[Serie]:
    """O limite (o mesmo 0,05 MΩ de cada inversor) vira UMA linha de referência, no lugar de uma por equipamento."""
    out, vistos = [], {}
    for s in series:
        if _LIMITE.search(chave(s.campo or s.rotulo)) and len({v for _t, v in s.pontos}) == 1:
            k = (s.unidade, s.pontos[0][1])
            if k not in vistos:
                vistos[k] = Serie(f"limite ({_br(s.pontos[0][1])} {s.unidade})".replace(" )", ")"), s.unidade,
                                  s.pontos[:1], estilo="limite", campo=s.campo, grupo=s.grupo)
                out.append(vistos[k])
            continue
        out.append(s)
    return out


#: o que diz, na descrição de uma consulta, que ela traz série no tempo
SERIE_NO_TEMPO = re.compile(r"5 em 5|15 min|hora a hora|s[ée]rie|no tempo|leituras|intradi", re.IGNORECASE)


async def sugestoes(ctx, spec: dict) -> list[str]:
    """As consultas de série no tempo que mais se parecem com o pedido (as palavras da consulta, dos campos e do
    rótulo), para a IA trocar a que não serve."""
    from app.services import assistente_catalogo as cat
    alvo = cat._palavras(" ".join([str(spec.get("consulta") or ""), *_lista(spec.get("campos")),
                                   str(spec.get("rotulo") or "")]))
    pontos = []
    for t in await cat._catalogo(ctx):
        desc = t.get("description") or ""
        if SERIE_NO_TEMPO.search(desc):
            pontos.append((len(alvo & (cat._palavras(t["name"]) | cat._palavras(desc))), t["name"], desc[:140]))
    return [f"{n}: {d}" for p, n, d in sorted(pontos, key=lambda x: -x[0])[:5]]


_NOTA = ("O gráfico já está no chat. Escreva à pessoa, curto, com os números da `analise`: o máximo e a hora; nas de "
         "sol, quando começou e parou (NÃO a última leitura) e a média com sol; o patamar (o teto, ou a sonda que "
         "parou num valor); quem passou do limite e em que dias; e a comparação nos mesmos horários. Num período, "
         "1 a 3 números (o total, o melhor e o pior dia). Datas em dd/mm/aaaa. Diga o que ficou sem leitura e por quê "
         "(sem comunicação não é parada). Sem as palavras correlação, r, pontos, leituras, série, consulta, campo ou "
         "ferramenta: quando andam juntas (perto de 1), diga que as duas sobem e descem juntas.")


async def grafico_de_series(ctx, a: dict) -> dict:
    from app.clients import whatsapp
    specs = [s for s in a.get("series") or [] if isinstance(s, dict)][:6]
    if not specs:
        return {"erro": "Diga ao menos uma série: a consulta e o que desenhar."}
    feitos = await asyncio.gather(*(_serie(ctx, s) for s in specs))
    for g, (ss, _p) in enumerate(feitos):
        for s in ss:
            s.grupo = g
    series = _limites_juntos([s for ss, _p in feitos for s in ss])
    problemas = [p for _ss, p in feitos if p]
    diario = e_diario(series)
    if not diario:   # curva no tempo com 1 ou 2 pontos: a consulta não dá curva (17/11/2026: a hora a hora "num ponto")
        problemas += [{"serie": s.rotulo, "erro": f"Só {len(s.pontos)} leitura(s): não dá curva no tempo com isso."}
                      for s in series if s.estilo != "limite" and len(s.pontos) < 3]
    if problemas:
        # nada pela metade (17/11/2026: o gráfico saiu só com o relé e a pessoa leu "os inversores ficaram de fora"):
        # volta o que errou, com o que existe, e a IA chama de novo com tudo certo — ou sem a série que não tem como
        return {"erro": "Nada desenhado ainda: " + ("nenhuma série saiu." if not series else
                                                     f"{len(problemas)} problema(s) nas entradas."),
                "problemas": problemas, **({"ja_deram": [s.rotulo for s in series][:12]} if series else {}),
                "como_seguir": "Corrija a consulta (veja `sugestoes`), os campos ou o equipamento pelo que existe "
                               "acima e chame de novo com TODAS as séries. Se uma delas não tem como sair, chame sem "
                               "ela e diga à pessoa por quê."}
    fora = []
    if len(series) > MAX_SERIES:
        fora = [s.rotulo for s in series[MAX_SERIES:]]
        series = series[:MAX_SERIES]
    unidades = list(dict.fromkeys(s.unidade for s in series))
    if len(unidades) > 2:
        return {"erro": f"Unidades demais num gráfico só ({', '.join(u or 'sem unidade' for u in unidades)}): um "
                        "gráfico tem no máximo duas (dois eixos). Divida em dois gráficos.",
                "series": [f"{s.rotulo} ({s.unidade or '—'})" for s in series]}
    titulo = titulo_com_data(str(a.get("titulo") or " × ".join(dict.fromkeys(s.rotulo for s in series)))[:120],
                             series)
    tipo = a.get("tipo") if a.get("tipo") in ("linha", "barras") else "auto"
    png = await asyncio.to_thread(desenhar, series, titulo, tipo)
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=png, filename="grafico.png",
                                       mime="image/png", texto=titulo)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(titulo)
    # quem está sem comunicação na usina do gráfico: num período, os dias desde então não têm o que eles geraram
    avisos = []
    for spec in specs:
        args = spec.get("argumentos") if isinstance(spec.get("argumentos"), dict) else {}
        slug = str(args.get("slug") or "")
        if slug and (com := (_COMUNICACAO.get((ctx.user.id, slug)) or (0, {}))[1]):
            ts = [t for s in series for t, _ in s.pontos]
            desde = min(d for d, _n in com.values())
            if ts and max(ts) >= desde:
                avisos.append(f"{slug}: " + ", ".join(sorted({n for _d, n in com.values()})) + " sem comunicação desde "
                              f"{desde:%d/%m %H:%M}: depois disso o que geraram não está nos números (aparece como 0 "
                              "no monitoramento), então não é parada nem produção zero.")
    achados = {k: v for s in series if s.achados for k, v in s.achados.items()}
    return {"grafico": titulo, "enviado_no_chat": ok, **({} if ok else {"erro": (r or {}).get("erro") or "não enviou"}),
            **({"pedido_e_achado": achados, "como_achou": "pelo cadastro do meuWatt; nos nomes Inv XY, X é o skid e Y "
                                                          "o inversor (Inv 12 = skid 1, inversor 2): já confirmado, não "
                                                          "peça para conferir"} if achados else {}),
            "analise": analise(series),
            **({"ficaram_de_fora": fora, "por_que": f"no máximo {MAX_SERIES} linhas num gráfico"} if fora else {}),
            **({"comunicacao": sorted(set(avisos))} if avisos else {}),
            "nota": _NOTA}


def series_para_ler(obs: Obs, mapa: Apelidos, teto: int = 30) -> dict:
    """O resumo das séries de uma consulta, para a IA ler sem os pontos (`consultar`): os equipamentos, os campos e,
    quando cabe, a análise de cada série."""
    todas, _p = series_de(obs, mapa, [], [])
    equipos = list(dict.fromkeys(s.rotulo.split(" · ")[0] for s in todas if " · " in s.rotulo))
    campos = list(dict.fromkeys(c for (_e, c) in obs))
    out: dict = {"equipamentos": equipos[:40], "campos": [f"{c} ({unidade(c) or '—'})" for c in campos][:60],
                 "series": len(todas)}
    if len(todas) <= teto:
        out["analise"] = analise(todas)["series"]
    return out
