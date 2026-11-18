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
import dataclasses
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
    for p in (catalogo or {}).get("plants") or []:      # a usina pelo nome ("porto-ferreira" → "Porto Ferreira")
        if p.get("slug") == slug and p.get("name"):
            mapa[("plant", slug)] = Equip(str(p["name"]), _pecas(str(p["name"])) | {slug})
    _GRANDEZAS.update({str(g["key"]): (str(g.get("label") or g["key"]), str(g.get("unit") or ""))
                       for g in (catalogo or {}).get("grandezas") or [] if isinstance(g, dict) and g.get("key")})
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


#: as grandezas do meuWatt (chave → nome, unidade), do catálogo delas: o mesmo para todos
_GRANDEZAS: dict[str, tuple[str, str]] = {}


def unidade(campo: str) -> str:
    if campo in _GRANDEZAS and _GRANDEZAS[campo][1]:
        return _GRANDEZAS[campo][1]
    c = chave(campo)
    return next((u for padrao, u in _UNIDADES if re.search(padrao, c)), "")


def nome_do_campo(campo: str) -> str:
    if campo in _GRANDEZAS:          # "potencia_ativa" → "Potência ativa" (17/11/2026: a chave crua na legenda)
        return _GRANDEZAS[campo][0]
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
    energia_contador: float | None = None  # kWh do dia pelo contador do próprio inversor (o número da tela do meuWatt)
    limites_temp: dict | None = None       # do relé de temperatura do trafo: ventilação, alarme e desligamento (°C)
    traco: str = ""                        # o traço da linha de referência ("--", ":"): o alarme e o desligamento
    incompletos: frozenset = frozenset()   # dias sem parte dos equipamentos (sem comunicação): a barra vem marcada


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
    elif rotulo and len(out) == 1 and not out[0].equipamento:
        # o rótulo da IA só sem equipamento (a usina); com ele, o nome do cadastro ("Inv 32 (TR-03) · string 10"),
        # que diz QUAL é (17/11/2026: "String 10 · Inv 2 · Skid 3 — Inv 32 (TR-03)" na legenda e no título)
        out[0].rotulo = rotulo
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


#: unidades de geração: começa, para, a média é só com sol, o teto e a energia
_DE_SOL = ("kW", "kW/kWp", "A", "W/m²")
_LIMITE = re.compile(r"threshold|limite|limit|alarm|trip|setpoint")


def arred(v: float) -> float:
    """O número como se escreve: 530,85 kW vira 531; 14,02 A fica 14,0; 0,0523 MΩ fica 0,052 (avaliação de 17/11/2026:
    "250,04 kW" e "122,78 kW" eram precisão falsa)."""
    a = abs(v)
    return round(v) if a >= 100 else round(v, 1) if a >= 10 else round(v, 2) if a >= 1 else round(v, 3)


def _trecho_no_teto(pts: list[tuple[datetime, float]]) -> tuple[int, int, float] | None:
    """O maior trecho no teto (≥ 99% do máximo, tolerando quedas de até 2 leituras) que dura 30 min ou mais."""
    mx = max(v for _t, v in pts)
    if mx <= 0:
        return None
    no = [i for i, (_t, v) in enumerate(pts) if v >= 0.99 * mx]
    trechos, ini, ant = [], no[0], no[0]
    for i in no[1:]:
        if i - ant > 3:
            trechos.append((ini, ant))
            ini = i
        ant = i
    trechos.append((ini, ant))
    i, j = max(trechos, key=lambda tr: pts[tr[1]][0] - pts[tr[0]][0])
    return (i, j, mx) if pts[j][0] - pts[i][0] >= timedelta(minutes=30) else None


def _teto(pts: list[tuple[datetime, float]]) -> dict | None:
    """O tempo no teto da potência: o limite do inversor (250 kW), do skid (1.000 kW), da usina (5 MW). A hora do
    máximo dentro do teto não diz nada; o trecho, sim, e as quedas no meio (uma nuvem: 188 kW às 12:25)."""
    if (tr := _trecho_no_teto(pts)) is None:
        return None
    i, j, mx = tr
    quedas, k = [], i
    while k <= j:
        if pts[k][1] < 0.99 * mx:
            m = k
            while m + 1 <= j and pts[m + 1][1] < 0.99 * mx:
                m += 1
            t, v = min(pts[k:m + 1], key=lambda p: p[1])
            quedas.append([t.strftime("%H:%M"), arred(v)])
            k = m + 1
        else:
            k += 1
    return {"valor": arred(mx), "de": pts[i][0].strftime("%H:%M"), "ate": pts[j][0].strftime("%H:%M"),
            "minutos": int((pts[j][0] - pts[i][0]).total_seconds() // 60), **({"quedas": quedas[:3]} if quedas else {})}


def _leitura_parada(pts: list[tuple[datetime, float]]) -> dict | None:
    """O MESMO valor repetido por 45 min ou mais, em leituras seguidas, na parte alta do dia: a sonda que travou
    (Pirapozinho, 17/11/2026: a sonda 1 do TR-02 em 99,8 °C das 11:00 às 12:40, com UMA leitura solta de 102,6 no
    meio, enquanto as outras subiam). A madrugada parada não conta; buraco de leitura corta o trecho."""
    if len(pts) < 6:
        return None
    alto = sorted(v for _t, v in pts)[int(len(pts) * 0.75)]
    passos = sorted(b[0] - a[0] for a, b in itertools.pairwise(pts))
    junto = max(timedelta(minutes=20), passos[len(passos) // 2] * 1.5)
    melhor, i = None, 0
    while i < len(pts):
        j = i
        while True:
            if j + 1 < len(pts) and pts[j + 1][0] - pts[j][0] <= junto and abs(pts[j + 1][1] - pts[i][1]) <= 0.05:
                j += 1
            elif j + 2 < len(pts) and pts[j + 2][0] - pts[j][0] <= 2 * junto and \
                    abs(pts[j + 2][1] - pts[i][1]) <= 0.05:
                j += 2                    # uma leitura solta no meio do valor parado
            else:
                break
        dur = pts[j][0] - pts[i][0]
        if dur >= timedelta(minutes=45) and pts[i][1] >= alto and (melhor is None or dur > melhor[2]):
            melhor = (i, j, dur)
        i = j + 1
    if melhor is None:
        return None
    i, j, dur = melhor
    return {"valor": round(pts[i][1], 1), "de": pts[i][0].strftime("%H:%M"), "ate": pts[j][0].strftime("%H:%M"),
            "minutos": int(dur.total_seconds() // 60)}


def _janelas(pts: list[tuple[datetime, float]], fora) -> list[dict]:
    """Os trechos em que `fora(v)` vale, juntando as leituras de uma mesma manhã (até 30 min entre elas):
    [{"dia": "03/11", "de": "06:20", "ate": "09:50"}] (17/11/2026: as "45 vezes" da isolação eram três manhãs)."""
    trechos: list[list[datetime]] = []
    for t, v in pts:
        if fora(v):
            if trechos and t.date() == trechos[-1][1].date() and t - trechos[-1][1] <= timedelta(minutes=30):
                trechos[-1][1] = t
            else:
                trechos.append([t, t])
    return [{"dia": a.strftime("%d/%m"), "de": a.strftime("%H:%M"), "ate": b.strftime("%H:%M")} for a, b in trechos]


def _sol(pts: list[tuple[datetime, float]]) -> tuple[int, int] | None:
    """Começo e fim da geração: acima de 1% do máximo por 3 leituras seguidas (o ruído solto do relé antes do sol não
    conta; com 5%, "parou às 18:00" com 70 kW ainda saindo — avaliação de 17/11/2026)."""
    mx = max(v for _t, v in pts)
    if mx <= 0:
        return None
    acima = [v > 0.01 * mx for _t, v in pts]
    ini = next((i for i in range(len(pts) - 2) if all(acima[i:i + 3])), None)
    fim = next((i for i in range(len(pts) - 1, 1, -1) if all(acima[i - 2:i + 1])), None)
    return (ini, fim) if ini is not None and fim is not None else None


def _energia(pts: list[tuple[datetime, float]]) -> float:
    """kWh de uma potência em kW: a área sob a curva, sem atravessar buraco de leitura de mais de 30 min."""
    e = 0.0
    for (t0, v0), (t1, v1) in itertools.pairwise(pts):
        h = (t1 - t0).total_seconds() / 3600
        if 0 < h <= 0.5:
            e += (v0 + v1) / 2 * h
    return round(e, 1)


def _energia_item(kwh: float) -> dict:
    return {"energia_mwh": round(kwh / 1000, 1)} if kwh >= 10_000 else {"energia_kwh": arred(kwh)}


def por_dia(s: Serie) -> Serie:
    """A série do dia vira um valor por dia, para as barras: energia soma; potência, temperatura, corrente… o máximo
    do dia (17/11/2026: "potência de pico de cada dia" com a potência de hora em hora punha 24 barras por dia)."""
    dias: dict[date, list[float]] = defaultdict(list)
    for t, v in s.pontos:
        dias[t.date()].append(v)
    soma = s.unidade in ("kWh", "kWh/m²")
    pts = [(datetime(d.year, d.month, d.day, tzinfo=BRT), sum(vs) if soma else max(vs)) for d, vs in sorted(dias.items())]
    rot = s.rotulo if soma or "máx" in s.rotulo else f"{s.rotulo} (máx. do dia)"
    return dataclasses.replace(s, rotulo=rot, pontos=pts)


def _c(v: float) -> str:
    """Temperatura no texto: uma casa, vírgula (148,2 °C; o `_br` cortaria para 148)."""
    return f"{v:.1f}".replace(".", ",")


def _frase(a: Serie, b: Serie, va: float, vb: float, energia: bool) -> str | None:
    """A comparação já escrita, com a base certa: quem tem menos é o sujeito e a base é o outro ("Inv 13 gerou 1.570
    kWh, 5,1% menos que Inv 11"; 17/11/2026: a IA pôs a base trocada em 2 de 3 porcentagens)."""
    if not va or not vb or abs(va - vb) < 1e-9:
        return None
    (n1, v1), (n2, v2) = sorted([(a.rotulo, va), (b.rotulo, vb)], key=lambda p: p[1])
    if a.unidade == "°C":           # temperatura: a diferença em graus (porcentagem de °C não quer dizer nada)
        return f"{n1} ficou, em média, {_c(v2 - v1)} °C abaixo de {n2} nos mesmos horários"
    pct = f"{(1 - v1 / v2) * 100:.1f}".replace(".", ",")
    if energia:
        return f"{n1} gerou {_br(arred(v1))} kWh, {pct}% menos que {n2} ({_br(arred(v2))} kWh), nos mesmos horários"
    return (f"{n1} teve média de {_br(arred(v1))} {a.unidade}, {pct}% menos que {n2} ({_br(arred(v2))} {a.unidade}), "
            "nos mesmos horários")


def analise(series: list[Serie]) -> dict:
    """O que a IA comenta, já com os números certos para cada coisa: o máximo e o mínimo com a hora (no teto, o trecho);
    nas grandezas de sol, quando começou e parou, a média só com sol, o tempo no teto e a energia (a do contador do
    inversor, quando a consulta traz); a sonda que travou; os limites do relé do trafo e a folga; os trechos abaixo do
    mínimo ou acima do limite; os dias incompletos e os dias no teto; e, entre equipamentos ou pedidos diferentes, se
    as curvas andam juntas e a comparação NOS MESMOS horários, já escrita."""
    diario = e_diario(series)
    dias = {t.date() for s in series for t, _ in s.pontos}
    varios = len(dias) > 1
    limites = [s for s in series if s.estilo == "limite" and s.campo != "limite_trafo"]
    out = []
    for s in series:
        if s.estilo == "limite":
            out.append({"serie": s.rotulo, "unidade": s.unidade, "limite": arred(s.pontos[0][1])})
            continue

        def r(v: float, _u: str = s.unidade) -> float:
            return round(v, 1) if _u == "°C" else arred(v)
        base = [p for p in s.pontos if p[0].date() not in s.incompletos] if diario else s.pontos
        base = base or s.pontos
        vals = [v for _t, v in base]
        mn = min(base, key=lambda p: p[1])
        mx = max(base, key=lambda p: p[1])
        item = {"serie": s.rotulo, **({"equipamento": s.equipamento} if s.equipamento else {}), "unidade": s.unidade,
                "maximo": [r(mx[1]), _quando(mx[0], diario, varios)],
                "minimo": [r(mn[1]), _quando(mn[0], diario, varios)]}
        if diario and len(base) < len(s.pontos):
            item["dias_incompletos"] = sorted({t.strftime("%d/%m") for t, _ in s.pontos if t.date() in s.incompletos})
            item["por_que"] = ("parte dos inversores sem comunicação nesses dias: o número deles está abaixo do real "
                               "e ficou fora do máximo, do mínimo e da média")
        if not diario:
            item["ultima_leitura"] = [r(s.pontos[-1][1]), _quando(s.pontos[-1][0], diario, varios)]
        if s.unidade in _DE_SOL and not diario:
            if sol := _sol(s.pontos):
                i, j = sol
                ativos = [v for _t, v in s.pontos[i:j + 1]]
                item.update(comecou=_quando(s.pontos[i][0], False, varios), parou=_quando(s.pontos[j][0], False, varios),
                            media_com_sol=arred(statistics.fmean(ativos)))
            if s.unidade == "kW":
                if teto := _teto(s.pontos):
                    item["no_teto"] = teto
                    item["maximo"] = [teto["valor"], f"no teto de {teto['de']} a {teto['ate']}"]
                item.update(_energia_item(s.energia_contador or _energia(s.pontos)))
                if s.energia_contador:
                    item["energia_fonte"] = "contador do inversor (o número da tela)"
        else:
            item["media"] = r(statistics.fmean(vals))
            if not diario and s.unidade == "°C" and (parada := _leitura_parada(s.pontos)):
                item["leitura_parada"] = parada
                item["maximo"] = (f"não medido: a sonda repetiu {_c(parada['valor'])} °C de {parada['de']} a "
                                  f"{parada['ate']}")
        if diario and s.unidade == "kW" and len(no := [t for t, v in base if v >= 0.995 * mx[1]]) >= 2:
            item["dias_no_teto"] = {"valor": r(mx[1]), "dias": [t.strftime("%d/%m") for t in no]}
        if s.unidade in ("kWh", "kWh/m²"):
            tot = sum(v for _t, v in s.pontos)
            item.update({"soma_mwh": round(tot / 1000, 1)} if s.unidade == "kWh" and tot >= 10_000 else
                        {"soma": arred(tot)})
        for lim in limites:
            if lim.unidade == s.unidade:
                ref = lim.pontos[0][1]
                if s.unidade == "MΩ":
                    item["abaixo_do_minimo"] = _janelas(s.pontos, lambda v, ref=ref: v < ref)
                else:
                    item["acima_do_limite"] = _janelas(s.pontos, lambda v, ref=ref: v > ref)
        if (lt := s.limites_temp) and not diario:
            item["limites_do_rele"] = {k: lt[k] for k in ("ventilacao", "alarme", "desligamento")
                                       if lt.get(k) is not None}
            if (al := lt.get("alarme")) is not None:
                if acima := _janelas(s.pontos, lambda v, al=al: v >= al):
                    item["acima_do_alarme"] = acima
                elif "leitura_parada" not in item:
                    item["folga_ate_o_alarme"] = round(al - mx[1], 1)
            dl = lt.get("desligamento")
            if dl is not None and (acima := _janelas(s.pontos, lambda v, dl=dl: v >= dl)):
                item["acima_do_desligamento"] = acima
            if (g := lt.get("maxima_guardada")) is not None and al is not None and g >= al:
                passou = "desligamento" if dl is not None and g >= dl else "alarme"
                item["maxima_guardada_no_rele"] = (f"{_c(g)} °C, acima do {passou} "
                                                   f"({_br(dl if passou == 'desligamento' else al)} °C); o relé não "
                                                   "diz quando foi")
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
            if len(comum) < 8 or len(pares) >= 10:
                continue
            x, y = [da[t] for t in comum], [db[t] for t in comum]
            par: dict = {"entre": [a.rotulo, b.rotulo]}
            if statistics.pstdev(x) > 0 and statistics.pstdev(y) > 0:
                c = round(statistics.correlation(x, y), 2)       # 1 = sobem e descem juntas
                par["andam_juntas"] = c
                par["como_andam"] = ("sobem e descem juntas" if c >= 0.8 else "andam juntas em parte" if c >= 0.5
                                     else "não andam juntas")
            if a.unidade == b.unidade:
                energia = a.unidade == "kW" and not diario
                if energia:
                    if a.energia_contador and b.energia_contador and len(comum) >= 0.95 * max(len(da), len(db)):
                        va, vb = a.energia_contador, b.energia_contador    # o número da tela (o mesmo do item)
                    else:
                        va, vb = _energia([(t, da[t]) for t in comum]), _energia([(t, db[t]) for t in comum])
                    par["energia_kwh_nos_mesmos_horarios"] = [arred(va), arred(vb)]
                else:
                    va, vb = statistics.fmean(x), statistics.fmean(y)
                    par["medias_nos_mesmos_horarios"] = [arred(va), arred(vb)]
                if frase := _frase(a, b, va, vb, energia):
                    par["frase"] = frase
                rele = next((s for s in (a, b) if s.campo == "total_active_power"), None)
                if energia and rele and any(s is not rele and "," in s.equipamento for s in (a, b)):
                    par["o_que_e_a_diferenca"] = ("a perda no trafo e nos cabos entre os inversores e o relé (o normal "
                                                  "é até uns 2%)")
            quente = next((s for s in (a, b) if s.unidade == "°C"), None)
            pot = next((s for s in (a, b) if s.unidade == "kW"), None)
            if quente and pot and not diario and (tr := _trecho_no_teto(pot.pontos)):
                t0, t1 = pot.pontos[tr[0]][0], pot.pontos[tr[1]][0]
                if len(dentro := [(t, v) for t, v in quente.pontos if t0 <= t <= t1]) >= 2:
                    v0, v1 = dentro[0][1], dentro[-1][1]
                    subindo = v1 >= max(v for _t, v in dentro) - 0.5 and v1 > v0 + 2
                    par["no_teto_da_potencia"] = (
                        f"enquanto {pot.rotulo} ficou no teto ({t0:%H:%M}–{t1:%H:%M}), {quente.rotulo} foi de "
                        f"{_c(v0)} a {_c(v1)} °C" + (" e ainda subia" if subindo else ""))
            pares.append(par)
    return {"series": out, **({"comparacoes": pares} if pares else {})}


def titulo_com_data(titulo: str, series: list[Serie]) -> str:
    """Título com a data por extenso (dd/mm/aaaa): a data ISO da IA vira a nossa; sem data, entra a do gráfico."""
    titulo = re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda m: f"{m[3]}/{m[2]}/{m[1]}", titulo)
    titulo = re.sub(r"\s*[(·-]?\s*\bhoje\b\s*\)?", "", titulo, flags=re.IGNORECASE).strip(" ·-,")
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
    à direita, tracejada (nas barras, vira linha por cima). O limite é UMA linha preta (o alarme do trafo pontilhado,
    o desligamento tracejado), fora das cores das séries; a barra do dia incompleto vai hachurada. Num dia, buraco de
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
            bs = ax.bar(xs, [v for _t, v in s.pontos], larg, label=s.rotulo, color=cor[id(s)])
            for barra, (t, _v) in zip(bs, s.pontos, strict=True):
                if t.date() in s.incompletos:
                    barra.set_hatch("//")
                    barra.set_alpha(0.45)
            linhas_leg.append(bs)
        if any(s.incompletos & set(dias) for s in nas_barras):
            from matplotlib.patches import Patch
            linhas_leg.append(Patch(facecolor="white", edgecolor="#555555", hatch="//",
                                    label="dia sem parte dos inversores (sem comunicação)"))
        for s in series:
            if s in nas_barras:
                continue
            if s.estilo == "limite":
                (ln,) = eixos[s.unidade].plot([-0.5, len(dias) - 0.5], [s.pontos[0][1]] * 2, s.traco or "--",
                                              color="#222222", linewidth=1.3, label=s.rotulo)
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
                (ln,) = eixos[s.unidade].plot([min(todos), max(todos)], [s.pontos[0][1]] * 2, s.traco or "--",
                                              color="#222222", linewidth=1.3, label=s.rotulo)
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
        if u == "MΩ":
            eixo.set_yscale("symlog", linthresh=0.01)    # o limite (0,05) e o 2,7 no mesmo gráfico; o zero cabe
            eixo.set_ylim(bottom=0)                        # sem a faixa negativa, que não existe
        eixo.yaxis.set_major_formatter(FuncFormatter(_br))
    ax.set_title(titulo, fontsize=11)
    ax.grid(axis="y", alpha=.3)
    if linhas_leg:                                       # legenda sempre: o gráfico encaminhado diz o que é cada linha
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


_FIM = ("end", "fim", "ate", "until", "to")


def _e_data_hora(esquema) -> bool:
    esquema = esquema if isinstance(esquema, dict) else {}
    return esquema.get("format") == "date-time" or any(
        isinstance(x, dict) and x.get("format") == "date-time" for x in esquema.get("anyOf") or [])


def datas_inteiras(args: dict, props: dict) -> dict:
    """Data sozinha num campo de data e hora vale o dia INTEIRO de Brasília: o início à meia-noite dele, o fim à do dia
    seguinte (17/11/2026: "end": "2026-11-17" cortava a isolação em 17/11 00:00 UTC e o dia de hoje ficava de fora)."""
    out = dict(args)
    for k, v in args.items():
        if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and _e_data_hora(props.get(k)):
            d = date.fromisoformat(v) + timedelta(days=1 if k.lower() in _FIM else 0)
            out[k] = datetime(d.year, d.month, d.day, tzinfo=BRT).isoformat()
    return out


async def chamar(ctx, nome: str, args: dict) -> dict:
    from app.api.v1 import mcp
    from app.services import assistente_catalogo as cat
    if nome.startswith("monitoramento_"):        # o inteiro: o texto do conector para nos 120 mil caracteres
        props = next(((t.get("inputSchema") or {}).get("properties") or {} for t in await cat._catalogo(ctx)
                      if t["name"] == nome), {})
        args = {**datas_inteiras(args, props), "_completo": True}
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


def slug_dos(nome: str, args: dict) -> str:
    """A usina do meuWatt de uma consulta: `slug`, ou a 1ª de `plants` (a série de grandezas)."""
    if not nome.startswith("monitoramento_"):
        return ""
    return str(args.get("slug") or str(args.get("plants") or "").split(",")[0]).strip()


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


async def situacao(ctx, slug: str) -> dict:
    """O monitoramento de AGORA de uma usina do meuWatt: {"sem_com": {número de série: (desde, nome)}, "reles": {skid:
    [nomes dos relés de potência]}}. O meuWatt grava 0 kW para o inversor sem comunicação (17/11/2026: o SKID-02 de
    Porto Ferreira gerou ~1 MW pelo relé e os Inv 21–24 apareciam zerados): zero depois do "desde" não é leitura, e o
    relé do skid mede o que ele gerou."""
    k = (ctx.user.id, slug)
    if (c := _COMUNICACAO.get(k)) and time.monotonic() - c[0] < 120:
        return c[1]
    r = await chamar(ctx, "monitoramento_monitoramento_usina", {"slug": slug})
    d = dados_de(r) if not r.get("isError") else None
    d = d if isinstance(d, dict) else {}
    sem_com = {}
    for i in d.get("inverters") or []:
        desde = instante(str(i.get("down_since") or ""), ger.hoje())
        if i.get("down") and i.get("down_cause") == "communication_failure" and i.get("serial_number") and desde:
            sem_com[str(i["serial_number"])] = (desde, str(i.get("name") or i["serial_number"]))
    reles: dict[str, list[str]] = defaultdict(list)
    for x in d.get("relays") or []:
        if x.get("transformer_name") and x.get("name") and not x.get("is_temperature_relay") and \
                "temp" not in str(x["name"]).lower():
            reles[str(x["transformer_name"])].append(str(x["name"]))
    temps: dict[str, dict[str, dict]] = {}
    for x in d.get("temp_sensors") or []:
        sp = x.get("setpoints") or {}
        por_sonda = {f"temp_{str(y.get('label') or '').lower()}": y for y in sp.get("sensors") or []}
        if x.get("name") and sp:
            temps[str(x["name"])] = {
                f"temp_s{n}": {"ventilacao": (por_sonda.get(f"temp_s{n}") or sp).get("fan_c"),
                               "alarme": (por_sonda.get(f"temp_s{n}") or sp).get("alarm_c"),
                               "desligamento": (por_sonda.get(f"temp_s{n}") or sp).get("trip_c"),
                               "maxima_guardada": x.get(f"temp_max_s{n}")}
                for n in (1, 2, 3, 4) if x.get(f"temp_s{n}") is not None or f"temp_s{n}" in por_sonda}
    out = {"sem_com": sem_com, "reles": dict(reles), "temps": temps}
    _COMUNICACAO[k] = (time.monotonic(), out)
    return out


def _skid_do(nome: str, mapa: Apelidos) -> str:
    m = re.search(r"\(([^)]+)\)", _exibir_do(nome, mapa))
    return m[1] if m else ""


def _aviso_sem_com(mudos: dict, mapa: Apelidos, reles: dict[str, list[str]], com: dict) -> tuple[str, list[str]]:
    """O texto à pessoa e os relés que medem os skids: "Inv 21 e Inv 22 sem comunicação desde 16/11 16:54. O SKID-02
    inteiro (Inv 21, 22, 23 e 24) está sem comunicação…" (avaliação de 17/11/2026: dizia só os dois pedidos)."""
    skids = sorted({_skid_do(n, mapa) for _d, n in mudos.values()} - {""})
    quem = ", ".join(f"{n} sem comunicação desde {d:%d/%m %H:%M}" for d, n in sorted(mudos.values()))
    inteiros = []
    for sk in skids:
        do_skid = {eq.exibir for (k, _v), eq in mapa.items() if k == "label" and eq.serial and f"({sk})" in eq.exibir}
        mudos_sk = sorted({n for _d, n in com.values() if _skid_do(n, mapa) == sk},
                          key=lambda x: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", x)])
        if do_skid and len(mudos_sk) >= len(do_skid):
            inteiros.append(f"o {sk} inteiro ({', '.join(mudos_sk)}) está sem comunicação")
    texto = (f"Sem leitura: {quem}." + (f" {'; '.join(inteiros)[:1].upper()}{'; '.join(inteiros)[1:]}." if inteiros
                                         else "")
             + " O que geraram não chegou ao monitoramento (não é parada nem produção zero).")
    return texto, [r for sk in skids for r in reles.get(sk, [])]


async def _o_rele_mediu(ctx, slug: str, dia: date, nomes: list[str]) -> list[str]:
    """O que o relé do skid mediu no dia: a prova de que o skid gerou enquanto os inversores estavam mudos."""
    r = await chamar(ctx, "monitoramento_reles_dia", {"slug": slug, "date": dia.isoformat()})
    d = dados_de(r) if not r.get("isError") else None
    obs = observacoes(d, dia) if d else {}
    out = []
    for nome in nomes:
        ss, _p = series_de(obs, {}, ["total_active_power"], [nome])
        if ss and (pts := ss[0].pontos):
            mx = max(pts, key=lambda p: p[1])
            out.append(f"o relé {nome} mediu {_br(arred(_energia(pts)))} kWh em {dia:%d/%m} (pico de "
                       f"{_br(arred(mx[1]))} kW às {mx[0]:%H:%M})")
    return out


async def _sem_leitura(ctx, nome: str, slug: str, dia: date, mudos: dict, mapa: Apelidos, sit: dict) -> dict:
    texto, rels = _aviso_sem_com(mudos, mapa, sit.get("reles") or {}, sit.get("sem_com") or {})
    provas = await _o_rele_mediu(ctx, slug, dia, rels) if rels else []
    return {"consulta": nome, "erro": texto, **({"o_rele_do_skid_mediu": provas} if provas else {}),
            **({"como_seguir": f"Para mostrar o skid, desenhe a potência do relé dele (consulta reles_dia, campo "
                               f"total_active_power, so={rels}). À pessoa, sem o nome da consulta."} if rels else {})}


def _exibir_do(nome: str, mapa: Apelidos) -> str:
    return next((eq.exibir for (k, v), eq in mapa.items() if k == "label" and v == nome), nome)


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
    slug = slug_dos(nome, args)
    r, mapa, sit = await asyncio.gather(chamar(ctx, nome, args), apelidos(ctx, nome, {**args, "slug": slug}),
                                        situacao(ctx, slug) if slug else asyncio.sleep(0, {}))
    com = sit.get("sem_com") or {}
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
        return [], await _sem_leitura(ctx, nome, slug, dia, {n: (d, n) for d, n in calados}, mapa, sit)
    series, problema = series_de(obs, mapa, campos, so, bool(spec.get("somar")), spec.get("rotulo") or None)
    achados = problema.pop("_achados", None)
    if series and achados:
        for s in series:
            s.achados = achados
    contador = {equipamento(ent, mapa).serial: max(v for _t, v in pts) for (ent, c), pts in obs.items()
                if c in ("daily_gen_kwh", "energy_today_kwh", "daily_generation") and pts}
    for s in series:
        if s.serial in com:
            s.sem_com_desde = com[s.serial][0]
        if s.unidade == "kW" and s.serial and contador.get(s.serial):
            s.energia_contador = contador[s.serial]
    series = [s for s in series if s.pontos]
    mudos = {} if series or not com else {
        eq.serial: com[eq.serial] for ent, _c in obs if (eq := equipamento(ent, mapa)).serial in com
        and (not so or any(casa_equipamento(x, eq) for x in so))}
    if mudos:
        return [], await _sem_leitura(ctx, nome, slug, dia, mudos, mapa, sit)
    for s in series:      # as sondas do trafo levam os limites do relé de temperatura dele
        s.limites_temp = ((sit.get("temps") or {}).get(s.equipamento.split(" (")[0]) or {}).get(s.campo)
    if com and "rele" not in nome:
        # a usina ou o skid somados a partir dos inversores: sem os mudos, o dia fica abaixo do real
        desde = min(d for d, _n in com.values())
        mudos_sk = {_skid_do(n, mapa) for _d, n in com.values()} - {""}
        todos_sk = {m[1] for eq in mapa.values() if (m := re.search(r"\(([^)]+)\)", eq.exibir))}
        for s in series:
            if s.serial is None and s.unidade in ("kW", "kWh") and (
                    any(sk in s.equipamento for sk in mudos_sk) or not any(sk in s.equipamento for sk in todos_sk)):
                corte = 14 if s.unidade == "kW" else 18      # o pico é ao meio-dia; a energia, até o sol se pôr
                s.incompletos = frozenset(t.date() for t, _v in s.pontos if t.date() > desde.date() or (
                    t.date() == desde.date() and desde.hour < corte))
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
                dist = min((abs(x - n) for x in reg), default=None)
                perto = sorted(x for x in reg if abs(x - n) == dist)
                sub = next((k for k in obs if len(perto) == 1 and perto[0] not in pedidas and k[1] == f"pv{perto[0]}"
                            and equipamento(k[0], mapa).serial == s.serial), None)
                diz = f"A entrada PV{n} do {s.equipamento} não tem string ligada no cadastro (ligadas: " \
                      f"{_faixas(sorted(reg))})"
                if sub:        # a única mais próxima entra no lugar, com o nome dizendo isso (avaliação de 17/11/2026)
                    p = perto[0]
                    fica.append(Serie(f"{s.equipamento} · {nome_do_campo(sub[1])} ({reg[p]}), no lugar da PV{n} "
                                      "(sem string)", s.unidade, sorted(dict(obs[sub]).items()), s.equipamento,
                                      campo=sub[1], serial=s.serial, achados=s.achados))
                    sem_string.append(f"{diz}: no gráfico foi a mais próxima, a PV{p} ({reg[p]}).")
                else:
                    sem_string.append(diz + ("; as mais próximas são " + " e ".join(
                        f"a PV{x} ({reg[x]})" for x in perto) + ": pergunte qual" if perto else "") + ".")
        series = fica
        if sem_string:     # não barra: desenha o que existe e diz da entrada vazia
            return series, {"consulta": nome,
                            "aviso": " ".join(sem_string) + " Não é string zerada: a entrada não tem string."}
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


_NOTA = ("O gráfico já está no chat: não o desminta. Escreva à pessoa em até 10 linhas, com os números da `analise` "
         "(já arredondados) e as `frase` prontas das comparações (não refaça porcentagem): o máximo e quando (no teto — "
         "o limite de potência do equipamento, não defeito —, o trecho e as quedas); nas de sol, quando começou e parou "
         "e a energia; `strings_sem_corrente` é a causa provável de o inversor gerar menos (diga quais); "
         "`leitura_parada`: a sonda repetiu o mesmo valor nesse trecho (parece travada) e o pico dela não foi medido; "
         "trafo: os limites do relé e a folga até o alarme (ou quando passou), e `maxima_guardada_no_rele` (o relé não "
         "diz quando foi); `abaixo_do_minimo`/`acima_do_limite`: os trechos, por dia; `dias_incompletos`, "
         "`dias_no_teto`, `no_teto_da_potencia`, `o_que_e_a_diferenca`. Num período, 1 a 3 números (o total, o melhor e "
         "o pior dia completos). Números no formato do Brasil (5.005 kW; 6,9 A). Datas dd/mm/aaaa. Repita os `avisos` e a `comunicacao` (sem comunicação não é parada). "
         "Sem as palavras correlação, r, pontos, leituras, série, consulta, campo ou ferramenta, e sem nome entre "
         "crases.")
_ISOLACAO = ("O inversor mede a isolação ao ligar, de manhã, e repete a medida a cada poucos minutos enquanto não liga. "
             "Ela cai com a umidade da madrugada e sobe com o sol (todos caem juntos de manhã). Abaixo do mínimo o "
             "inversor não liga: o trecho de `abaixo_do_minimo` é o tempo em que ele ficou sem gerar.")


async def strings_sem_corrente(ctx, slug: str, dia: date, serial: str) -> list[str]:
    """As strings LIGADAS de um inversor que não deram corrente no dia (máx. abaixo de 0,2 A enquanto as outras dele
    passaram de 2 A): a causa provável de ele gerar menos que os outros (17/11/2026: o Inv 13 de Pirapozinho, 5% abaixo
    dos outros, com a 6S27 e a 6S28 zeradas desde 19/10)."""
    ligadas = (await strings_ligadas(ctx, slug, dia)).get(serial) or {}
    if not ligadas:
        return []
    r = await chamar(ctx, "monitoramento_correntes_strings_dia", {"slug": slug, "date": dia.isoformat()})
    d = dados_de(r) if not r.get("isError") else None
    maximos = {int(m[1]): max(v for _t, v in pts) for (ent, c), pts in (observacoes(d, dia) if d else {}).items()
               if pts and (m := re.fullmatch(r"pv(\d+)", c)) and int(m[1]) in ligadas and ("serial_number", serial) in ent}
    if not any(v >= 2 for v in maximos.values()):
        return []
    return [ligadas[n] or f"PV{n}" for n, v in sorted(maximos.items()) if v < 0.2]


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
    problemas = [p for _ss, p in feitos if p and "erro" in p]
    avisos_das_series = [p["aviso"] for _ss, p in feitos if p and "aviso" in p]
    if a.get("tipo") == "barras":     # barras = um valor por dia (o máximo; a energia, somada)
        series = [s if s.estilo == "limite" or e_diario([s]) else por_dia(s) for s in series]
    if not series and avisos_das_series and not problemas:
        return {"erro": "Nada para desenhar.", "avisos": avisos_das_series,
                "como_seguir": "Diga isso à pessoa e ofereça a entrada mais próxima, que tem string."}
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
    trafo = {}          # o alarme e o desligamento do relé de temperatura, uma linha de cada
    for s in series:
        for k, traco in (("alarme", ":"), ("desligamento", "--")):
            if s.limites_temp and (v := s.limites_temp.get(k)) is not None and (k, v) not in trafo:
                trafo[(k, v)] = Serie(f"{k} do relé de temperatura ({_br(v)} °C)", "°C", s.pontos[:1],
                                      estilo="limite", campo="limite_trafo", traco=traco)
    series += list(trafo.values())
    unidades = list(dict.fromkeys(s.unidade for s in series))
    if len(unidades) > 2:
        return {"erro": f"Unidades demais num gráfico só ({', '.join(u or 'sem unidade' for u in unidades)}): um "
                        "gráfico tem no máximo duas (dois eixos). Divida em dois gráficos.",
                "series": [f"{s.rotulo} ({s.unidade or '—'})" for s in series]}
    titulo = str(a.get("titulo") or "")
    if avisos_das_series or not titulo:   # o título diz o que foi desenhado, não o que se pediu e não existe
        grupos: dict[str, list[str]] = defaultdict(list)
        for x in series:
            if x.estilo != "limite":
                eq, _, o_que = x.rotulo.split(", no lugar")[0].partition(" · ")
                grupos[eq].append(o_que)
        titulo = " × ".join(f"{eq}: {', '.join(oq)}" if any(oq) else eq for eq, oq in grupos.items())
    titulo = titulo_com_data(titulo[:120], series)
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
        slug = slug_dos(str(await nome_da_consulta(ctx, str(spec.get("consulta") or "")) or ""), args)
        if slug and (com := ((_COMUNICACAO.get((ctx.user.id, slug)) or (0, {}))[1]).get("sem_com")):
            ts = [t for s in series for t, _ in s.pontos]
            desde = min(d for d, _n in com.values())
            if ts and (max(ts) >= desde or (diario and max(ts).date() >= desde.date())):
                avisos.append(f"{slug}: " + ", ".join(sorted({n for _d, n in com.values()})) + " sem comunicação desde "
                              f"{desde:%d/%m %H:%M}: depois disso o que geraram não está nos números (aparece como 0 "
                              "no monitoramento), então não é parada nem produção zero.")
    achados = {k: v for s in series if s.achados for k, v in s.achados.items()}
    res = analise(series)
    # quem gerou menos que os outros no dia: as strings dele sem corrente (a causa, não só a diferença)
    pot = [s for s in series if s.unidade == "kW" and s.serial and s.estilo != "limite" and not s.sem_com_desde]
    if len(pot) >= 2 and not e_diario(pot):
        ens = {id(s): s.energia_contador or _energia(s.pontos) for s in pot}
        baixos = [s for s in pot if (ref := statistics.median(ens[id(o)] for o in pot if o is not s))
                  and ens[id(s)] < 0.97 * ref]
        for s in baixos[:3]:
            args = specs[s.grupo].get("argumentos") if isinstance(specs[s.grupo].get("argumentos"), dict) else {}
            slug = slug_dos("monitoramento_", args)
            if slug and (tags := await strings_sem_corrente(ctx, slug, dia_dos(args), s.serial)):
                next(x for x in res["series"] if x["serie"] == s.rotulo)["strings_sem_corrente"] = tags
    return {"grafico": titulo, "enviado_no_chat": ok, **({} if ok else {"erro": (r or {}).get("erro") or "não enviou"}),
            **({"pedido_e_achado": achados, "como_achou": "pelo cadastro do meuWatt; nos nomes Inv XY, X é o skid e Y "
                                                          "o inversor (Inv 12 = skid 1, inversor 2): já confirmado, não "
                                                          "peça para conferir"} if achados else {}),
            "analise": res,
            **({"sobre_a_isolacao": _ISOLACAO} if any(s.unidade == "MΩ" for s in series) else {}),
            **({"ficaram_de_fora": fora, "por_que": f"no máximo {MAX_SERIES} linhas num gráfico"} if fora else {}),
            **({"comunicacao": sorted(set(avisos))} if avisos else {}),
            **({"avisos": avisos_das_series} if avisos_das_series else {}),
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
