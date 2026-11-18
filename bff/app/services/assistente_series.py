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
            "temps4": "sonda 4", "tempambient": "ambiente do skid", "temperature": "temperatura"}.get(c, campo)


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
    componentes: tuple = ()                # na soma: os números de série somados (a energia é a soma dos contadores)


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
        out = [Serie(rotulo or f"soma de {len(out)} séries", out[0].unidade, sorted(soma.items()), eqs,
                     componentes=tuple(s.serial for s in out if s.serial))]
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


def agora_brt() -> datetime:
    return datetime.now(BRT)


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
    máximo dentro do teto não diz nada; os trechos, sim (todos de 10 min ou mais: 17/11/2026, o Inv 13 voltou a 250 kW
    das 12:05 às 12:20 e só o 1º trecho era dito), o total e as quedas no meio (uma nuvem: 188 kW às 12:25)."""
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
    trechos = [(i, j) for i, j in trechos if pts[j][0] - pts[i][0] >= timedelta(minutes=10)]
    minutos = sum(int((pts[j][0] - pts[i][0]).total_seconds() // 60) for i, j in trechos)
    if minutos < 30:
        return None
    quedas = []
    for i, j in trechos:
        k = i
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
    return {"valor": arred(mx), "trechos": [[pts[i][0].strftime("%H:%M"), pts[j][0].strftime("%H:%M")]
                                            for i, j in trechos],
            "minutos": minutos, **({"quedas": quedas[:3]} if quedas else {})}


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
        j, soltas = i, []
        while True:
            if j + 1 < len(pts) and pts[j + 1][0] - pts[j][0] <= junto and abs(pts[j + 1][1] - pts[i][1]) <= 0.05:
                j += 1
            elif j + 2 < len(pts) and pts[j + 2][0] - pts[j][0] <= 2 * junto and \
                    abs(pts[j + 2][1] - pts[i][1]) <= 0.05:
                soltas.append(j + 1)      # uma leitura solta no meio do valor parado
                j += 2
            else:
                break
        dur = pts[j][0] - pts[i][0]
        if dur >= timedelta(minutes=45) and pts[i][1] >= alto and (melhor is None or dur > melhor[2]):
            melhor = (i, j, dur, soltas)
        i = j + 1
    if melhor is None:
        return None
    i, j, dur, soltas = melhor
    return {"valor": round(pts[i][1], 1), "de": pts[i][0].strftime("%H:%M"), "ate": pts[j][0].strftime("%H:%M"),
            "minutos": int(dur.total_seconds() // 60),
            **({"exceto": [[pts[k][0].strftime("%H:%M"), round(pts[k][1], 1)] for k in soltas]} if soltas else {})}


def _quedas(pts: list[tuple[datetime, float]]) -> list[str]:
    """As maiores quedas do dia (nuvem), já escritas ("às 08:45 caiu de 170 para 98 kW"): um vale — a potência cai a
    menos de 60% do que era nos 15 min antes e VOLTA a 80% disso nos 30 min seguintes. A descida da tarde não volta, não
    é queda (17/11/2026: "a de 14:40 foi a maior" era a tarde descendo, e a de 08:45 ficava de fora). As 3 mais fundas,
    uma por episódio."""
    mx = max(v for _t, v in pts)
    achadas = []
    for i in range(1, len(pts) - 1):
        t, v = pts[i]
        antes = [x for tt, x in pts[max(0, i - 3):i] if t - tt <= timedelta(minutes=20)]
        depois = [x for tt, x in pts[i + 1:i + 7] if tt - t <= timedelta(minutes=35)]
        if antes and depois and (a := max(antes)) >= 0.2 * mx and v < 0.6 * a and max(depois) >= 0.8 * a:
            achadas.append((a - v, t, a, v))
    out: list[tuple] = []
    for q in sorted(achadas, key=lambda q: -q[0]):
        if all(abs((q[1] - o[1]).total_seconds()) > 1800 for o in out):
            out.append(q)
    return [f"às {t:%H:%M} caiu de {_num(a)} para {_num(v)} kW" for _d, t, a, v in sorted(out[:3], key=lambda o: o[1])]


def _de_quem(s: Serie) -> str:
    """De quem é o teto: o limite do inversor, do skid ou da usina (17/11/2026: os 5.005 kW de Porto Ferreira são o
    limite de 5 MW da usina, não "do equipamento")."""
    c = chave(s.equipamento)
    if s.serial:
        return "do inversor"
    if s.componentes:
        return "dos inversores somados"
    return "do skid" if re.search(r"skid|tr\d", c) and "geral" not in c else "da usina"


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


def _num(v: float) -> str:
    """O número arredondado como se escreve, no formato do Brasil: 5.005; 6,95; 0,052 (o `_br` dos eixos corta 0,052
    para 0,05)."""
    v = arred(v)
    return f"{v:,.0f}".replace(",", ".") if abs(v) >= 100 else str(v).replace(".", ",")


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
        return f"{n1} somou {_num(v1)} kWh, {pct}% menos que {n2} ({_num(v2)} kWh), nos mesmos horários"
    sol = " com sol" if a.unidade in _DE_SOL else ""
    return (f"{n1} teve média{sol} de {_num(v1)} {a.unidade}, {pct}% menos que {n2} ({_num(v2)} "
            f"{a.unidade})" + ("" if sol else ", nos mesmos horários"))


def analise(series: list[Serie]) -> dict:
    """O que a IA comenta, já com os números certos para cada coisa: o máximo e o mínimo com a hora (no teto, o trecho);
    nas grandezas de sol, quando começou e parou, a média só com sol, o tempo no teto e a energia (a do contador do
    inversor, quando a consulta traz); a sonda que travou; os limites do relé do trafo e a folga; os trechos abaixo do
    mínimo ou acima do limite; os dias incompletos e os dias no teto; e, entre equipamentos ou pedidos diferentes, se
    as curvas andam juntas e a comparação NOS MESMOS horários, já escrita."""
    diario = e_diario(series)
    dias = {t.date() for s in series for t, _ in s.pontos}
    varios = len(dias) > 1
    limites = [s for s in series if s.estilo == "limite" and not s.campo.startswith("limite_")]
    out = []
    for s in series:
        if s.estilo == "limite":
            out.append({"serie": s.rotulo, "unidade": s.unidade, "limite": arred(s.pontos[0][1])})
            continue

        def r(v: float, _u: str = s.unidade) -> float:
            return round(v, 1) if _u == "°C" else arred(v)
        hoje = ger.hoje() if diario and agora_brt().hour < 19 else None     # o dia de hoje ainda não acabou
        base = [p for p in s.pontos if p[0].date() not in s.incompletos and p[0].date() != hoje] if diario else s.pontos
        base = base or s.pontos
        vals = [v for _t, v in base]
        mn = min(base, key=lambda p: p[1])
        mx = max(base, key=lambda p: p[1])
        item = {"serie": s.rotulo, **({"equipamento": s.equipamento} if s.equipamento else {}), "unidade": s.unidade,
                "maximo": [r(mx[1]), _quando(mx[0], diario, varios)],
                "minimo": [r(mn[1]), _quando(mn[0], diario, varios)]}
        if diario and s.incompletos & {t.date() for t, _ in s.pontos}:
            item["dias_incompletos"] = sorted({t.strftime("%d/%m") for t, _ in s.pontos if t.date() in s.incompletos})
            item["por_que"] = ("parte dos inversores sem comunicação nesses dias: o número deles está abaixo do real "
                               "e ficou fora do máximo, do mínimo e da média")
        if hoje and any(t.date() == hoje for t, _ in s.pontos):
            item["dia_em_andamento"] = f"{hoje:%d/%m}: o dia ainda não acabou; fica fora do máximo, do mínimo e da média"
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
                    item["no_teto"] = {**teto, "de_quem": _de_quem(s)}
                    item["maximo"] = [teto["valor"], f"no teto por {teto['minutos']} min: " + ", ".join(
                        f"{a}–{b}" for a, b in teto["trechos"])]
                if quedas := _quedas(s.pontos):
                    item["maiores_quedas"] = quedas
                item.update(_energia_item(s.energia_contador or _energia(s.pontos)))
                if s.energia_contador:
                    item["energia_fonte"] = ("contador do inversor (o número da tela)" if s.serial else
                                             "a soma dos contadores dos inversores (a mesma conta de cada um)")
        elif s.unidade == "MΩ":
            primeiras = {}
            for t, v in s.pontos:
                primeiras.setdefault(t.date(), v)
            item["media_da_1a_leitura_do_dia"] = r(statistics.fmean(primeiras.values()))
        else:
            item["media"] = r(statistics.fmean(vals))
            if not diario and s.unidade == "°C" and (parada := _leitura_parada(s.pontos)):
                item["leitura_parada"] = parada
            if not diario and s.unidade == "°C" and (saltos := [
                    f"às {t1:%H:%M} pulou de {_c(a)} para {_c(b)} °C" for (t0, a), (t1, b) in itertools.pairwise(s.pontos)
                    if abs(b - a) >= 5 and t1 - t0 <= timedelta(minutes=10)]):
                item["leitura_suspeita"] = saltos[:3]                   # 5 °C em 5 min não é temperatura de verdade
        if diario and s.unidade == "kW" and len(no := [(t, v) for t, v in base if v >= 0.995 * mx[1]]) >= 2:
            item["dias_no_teto"] = {"de_quem": _de_quem(s), "dias": [[t.strftime("%d/%m"), r(v)] for t, v in no]}
        if s.unidade in ("kWh", "kWh/m²"):
            tot = sum(v for _t, v in s.pontos)
            item.update({"soma_mwh": round(tot / 1000, 1)} if s.unidade == "kWh" and tot >= 10_000 else
                        {"soma": arred(tot)})
        for lim in limites:
            if lim.unidade == s.unidade:
                ref = lim.pontos[0][1]
                if s.unidade == "MΩ":
                    item["abaixo_do_minimo"] = _janelas(s.pontos, lambda v, ref=ref: v < ref)
                    if not item["abaixo_do_minimo"] and mn[1] < 1.1 * ref:
                        item["perto_do_minimo"] = f"{_num(mn[1])} MΩ em {_quando(mn[0], False, True)}, " \
                                                  f"{(mn[1] / ref - 1) * 100:.0f}% acima do mínimo"
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
                lim, qual = (dl, "desligamento") if dl is not None and g >= dl else (al, "alarme")
                item["maxima_guardada_no_rele"] = (f"{_c(g)} °C, {'acima do' if g > lim else 'igual ao'} {qual} "
                                                   f"({_br(lim)} °C); o relé não diz quando foi")
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
                    cheio = len(comum) >= 0.95 * max(len(da), len(db))     # as leituras são as mesmas: vale o item
                    va = a.energia_contador if a.energia_contador and cheio else _energia([(t, da[t]) for t in comum])
                    vb = b.energia_contador if b.energia_contador and cheio else _energia([(t, db[t]) for t in comum])
                    par["energia_kwh_nos_mesmos_horarios"] = [arred(va), arred(vb)]
                elif a.unidade in _DE_SOL and not diario and (sa := _sol(a.pontos)) and (sb := _sol(b.pontos)):
                    va = statistics.fmean(v for _t, v in a.pontos[sa[0]:sa[1] + 1])
                    vb = statistics.fmean(v for _t, v in b.pontos[sb[0]:sb[1] + 1])
                else:
                    va, vb = statistics.fmean(x), statistics.fmean(y)
                    par["medias_nos_mesmos_horarios"] = [arred(va), arred(vb)]
                if frase := _frase(a, b, va, vb, energia):
                    par["frase"] = frase
                rele = next((s for s in (a, b) if s.campo == "total_active_power"), None)
                soma = next((s for s in (a, b) if s is not rele and s.componentes), None)
                if energia and rele and soma:
                    dr, ds = dict(rele.pontos), dict(soma.pontos)
                    mr, ms = max(dr.values()), max(ds.values())
                    alto = [t for t in comum if dr[t] >= 0.99 * mr and ds[t] >= 0.99 * ms]
                    if len(alto) < 6:
                        alto = [t for t in comum if dr[t] >= 0.9 * mr and ds[t] >= 0.9 * ms]
                    if len(alto) >= 6:
                        d = (statistics.fmean(dr[t] for t in alto) / statistics.fmean(ds[t] for t in alto) - 1) * 100
                        pct = f"{abs(d):.1f}".replace(".", ",")
                        par["no_trecho_alto"] = (
                            f"com a potência alta (entre {alto[0]:%H:%M} e {alto[-1]:%H:%M}), {rele.rotulo} mediu "
                            f"{pct}% {'a mais' if d > 0 else 'a menos'} que {soma.rotulo}" if abs(d) >= 0.05 else
                            f"com a potência alta, {rele.rotulo} e {soma.rotulo} mediram igual")
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
                if t.date() in s.incompletos or (t.date() == ger.hoje() and agora_brt().hour < 19):
                    barra.set_hatch("//")
                    barra.set_alpha(0.45)
            linhas_leg.append(bs)
        if any(s.incompletos & set(dias) for s in nas_barras) or (ger.hoje() in dias and agora_brt().hour < 19):
            from matplotlib.patches import Patch
            linhas_leg.append(Patch(facecolor="white", edgecolor="#555555", hatch="//",
                                    label="dia incompleto (sem comunicação ou ainda em andamento)"))
        for s in series:
            if s in nas_barras:
                continue
            if s.estilo == "limite":
                (ln,) = eixos[s.unidade].plot([-0.5, len(dias) - 0.5], [s.pontos[0][1]] * 2, s.traco or "--",
                                              color="#222222", linewidth=1.3, label=s.rotulo)
            else:
                (ln,) = eixos[s.unidade].plot([pos[t.date()] for t, _ in s.pontos], [v for _t, v in s.pontos], "o-",
                                              color=cor[id(s)], label=s.rotulo)
            linhas_leg.append(ln)
        ax.set_ylim(top=ax.get_ylim()[1] * 1.18)       # a legenda cabe em cima, sem cobrir barra (17/11/2026)
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
            (ln,) = eixos[s.unidade].plot(px, py, "-", linewidth=1.4, color=cor[id(s)],
                                          label=s.rotulo, marker="." if len(xs) < 400 else None, markersize=3)
            linhas_leg.append(ln)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m" if varios_dias else "%H:%M", tz=BRT))
        fig.autofmt_xdate()
    if len(unidades) > 1 and not barras:
        eixos[unidades[1]].set_ylim(bottom=min(0, eixos[unidades[1]].get_ylim()[0]),
                                    top=max(v for s in series if s.unidade == unidades[1] for _t, v in s.pontos) * 1.3)
    for u, eixo in eixos.items():
        eixo.set_ylabel(u)
        if u == "MΩ":
            eixo.set_yscale("symlog", linthresh=0.01)    # o limite (0,05) e o 2,7 no mesmo gráfico; o zero cabe
            eixo.set_ylim(bottom=0)                        # sem a faixa negativa, que não existe
        eixo.yaxis.set_major_formatter(FuncFormatter(_br))
    ax.set_title(titulo, fontsize=11)
    ax.grid(axis="y", alpha=.3)
    if len(linhas_leg) > 6:                              # muitas linhas: a legenda embaixo, fora das curvas
        ax.legend(linhas_leg, [h.get_label() for h in linhas_leg], fontsize=7.5, loc="upper center",
                  bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False)
    elif linhas_leg:                                     # legenda sempre: o gráfico encaminhado diz o que é cada linha
        ax.legend(linhas_leg, [h.get_label() for h in linhas_leg], fontsize=8, loc="best")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
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
        "titulo": {"type": "string", "description": "a usina e o que é: \"Pirapozinho: temperatura do trafo 1 × "
                                                    "potência do Inv 12\""}},
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
    out = {"sem_com": sem_com, "reles": dict(reles), "temps": temps,
           "trafo_do_sensor": {str(x["name"]): str(x.get("transformer_name") or "")
                               for x in d.get("temp_sensors") or [] if x.get("name")}}
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
            buraco = max(itertools.pairwise(pts), key=lambda ab: ab[1][0] - ab[0][0], default=None)
            out.append(f"o relé {nome} mediu {_num(_energia(pts))} kWh em {dia:%d/%m} (pico de "
                       f"{_num(mx[1])} kW às {mx[0]:%H:%M})" + (
                           f"; leitura incompleta: sem dado das {buraco[0][0]:%H:%M} às {buraco[1][0]:%H:%M}"
                           if buraco and buraco[1][0] - buraco[0][0] > timedelta(hours=1) else ""))
    return out


async def _sem_leitura(ctx, nome: str, slug: str, dia: date, mudos: dict, mapa: Apelidos, sit: dict) -> dict:
    texto, rels = _aviso_sem_com(mudos, mapa, sit.get("reles") or {}, sit.get("sem_com") or {})
    provas = await _o_rele_mediu(ctx, slug, dia, rels) if rels else []
    return {"consulta": nome, "erro": texto, **({"o_rele_do_skid_mediu": provas} if provas else {}),
            **({"como_seguir": f"Para mostrar o skid, desenhe a potência do relé dele (consulta reles_dia, campo "
                               f"total_active_power, so={rels}). À pessoa, sem o nome da consulta."} if rels else {})}


def _exibir_do(nome: str, mapa: Apelidos) -> str:
    return next((eq.exibir for (k, v), eq in mapa.items() if k == "label" and v == nome), nome)


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
    pvs = sorted({int(n) for x in [*campos, str(spec.get("rotulo") or "")]
                  for n in re.findall(r"(?:\bpv|\bstring)\s*(\d{1,2})\b", x, re.IGNORECASE)})
    if pvs and any(re.fullmatch(r"pv\d+", c) for _e, c in obs):
        campos = [f"pv{n}" for n in pvs]   # a string pedida pelo número, mesmo quando ele veio só no rótulo
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
        elif s.unidade == "kW" and s.componentes and all(contador.get(x) for x in s.componentes):
            s.energia_contador = sum(contador[x] for x in s.componentes)   # a soma: a mesma conta do item de cada um
    series = [s for s in series if s.pontos]
    mudos = {} if series or not com else {
        eq.serial: com[eq.serial] for ent, _c in obs if (eq := equipamento(ent, mapa)).serial in com
        and (not so or any(casa_equipamento(x, eq) for x in so))}
    if mudos:
        return [], await _sem_leitura(ctx, nome, slug, dia, mudos, mapa, sit)
    agregados = [s for s in series if "grandezas" in nome and s.unidade == "kW" and s.serial is None and not
                 s.componentes and len({t.date() for t, _v in s.pontos}) == 1]
    if agregados and slug:
        gen = await _geracao_do_dia(ctx, slug, agregados[0].pontos[0][0].date())
        skid = {sn: _skid_do(eq.exibir.split(" (")[0], mapa) for (k, sn), eq in mapa.items() if k == "serial_number"}
        todos_sk = {m[1] for eq in mapa.values() if (m := re.search(r"\(([^)]+)\)", eq.exibir))}
        for s in agregados:
            sk = next((x for x in todos_sk if x in s.equipamento), None)       # o skid; sem skid no nome, a usina
            kwh = [v[1] for sn, v in gen.items() if sk is None or skid.get(sn) == sk]
            if kwh:
                s.energia_contador = sum(kwh)
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
                ordem = sorted(reg)
                pela_ordem = ordem[n - 1] if 0 < n <= len(ordem) and ordem[n - 1] not in perto else None
                sem_string.append(
                    f"A entrada PV{n} do {s.equipamento} está vazia, sem string ligada (não é string zerada; as "
                    f"ligadas são {_faixas(ordem)})" + (("; a mais próxima é " if len(perto) == 1 else
                                                          "; as mais próximas são ") + " e ".join(
                        f"a PV{x} ({reg[x]})" for x in perto) if perto else "")
                    + (f"; contando pela ordem das ligadas, a {n}ª é a PV{pela_ordem} ({reg[pela_ordem]})"
                       if pela_ordem else "") + ".")
        series = fica
        if sem_string:     # pergunta antes: a pessoa pode chamar de "string 1" a 1ª string ligada, que é outra entrada
            return [], {"consulta": nome, "erro": " ".join(sem_string),
                        "pergunte": "qual entrada a pessoa quer no lugar"}
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


_NOTA = ("O gráfico já está no chat: não o desminta. Escreva à pessoa em NO MÁXIMO 10 linhas curtas, nesta ordem, e "
         "deixe de fora o que não couber: (1) o que responde ao pedido; (2) o alerta — limite do relé e a folga até o "
         "alarme, `leitura_parada`/`leitura_suspeita` (a sonda repetiu o valor ou pulou: não suponha o que ela "
         "mediria), `strings_com_problema` (quais, desde quando, a perda medida no dia e a estimada), "
         "`naquele_dia` da isolação, `dias_incompletos`; (3) a comparação: as `frase` prontas (não refaça "
         "porcentagem), `no_teto_da_potencia`, `no_trecho_alto`, `trafos_no_dia` (a carga em % do trafo). Use os "
         "números da `analise`, já arredondados, no formato do Brasil (5.005 kW; 6,9 A), e um número só por coisa. No "
         "teto (o limite `de_quem`, não defeito), os trechos; as `maiores_quedas` como vieram. Relé MEDE, não gera. "
         "Num período: o total, o melhor e o pior dia completos. Datas dd/mm/aaaa. Repita os `avisos` e a "
         "`comunicacao` (sem comunicação não é parada). Chame o sistema de \"monitoramento\". Sem as palavras "
         "correlação, r, pontos, leituras, série, consulta, campo, ferramenta ou sonda de diagnóstico, e sem nome "
         "entre crases.")
_ISOLACAO = ("Cada ponto é a isolação que o inversor mede antes de ligar, de manhã; abaixo do mínimo ele não liga e "
             "repete a medida até a isolação subir. O que aconteceu de fato no dia (ligou a que horas, quanto gerou) "
             "está em `naquele_dia`. A comparação justa entre inversores é a `media_da_1a_leitura_do_dia`. A isolação "
             "costuma cair com a umidade da madrugada (causa provável, não medida).")


async def _leituras_strings(ctx, slug: str, dia: date) -> list[dict]:
    """Os inversores da tela Leituras do meuWatt (`readings/strings`): as strings ligadas de cada um, o estado (a regra
    é a de lá: zerada, intermitente, fraca), desde quando está zerada, a perda do dia e a marca da equipe."""
    k = (ctx.user.id, slug, dia.isoformat())
    if (c := _STRINGS.get(k)) and time.monotonic() - c[0] < CACHE_S:
        return c[1]
    r = await chamar(ctx, "monitoramento_leituras_strings", {"slug": slug, "date": dia.isoformat()})
    d = dados_de(r) if not r.get("isError") else None
    out = [i for i in (d.get("inverters") or [] if isinstance(d, dict) else []) if i.get("serial_number")]
    _STRINGS[k] = (time.monotonic(), out)
    return out


async def strings_ligadas(ctx, slug: str, dia: date) -> dict[str, dict[int, str]]:
    """{número de série: {entrada PV: etiqueta}} das strings que o cadastro do meuWatt tem LIGADAS em cada inversor. A
    entrada sem string lê 0 A o dia todo e não é string zerada (17/11/2026: a PV1 não tem string em Pirapozinho)."""
    return {str(i["serial_number"]): {int(x["number"]): str(x.get("tag") or "") for x in i.get("strings") or []
                                      if x.get("registered") and x.get("number") is not None}
            for i in await _leituras_strings(ctx, slug, dia)}


_ESTADO = {"zero": "zerada", "intermittent": "intermitente", "weak": "fraca"}


async def strings_com_problema(ctx, slug: str, dia: date, serial: str) -> dict | None:
    """As strings ligadas do inversor que a regra do meuWatt dá como zeradas, intermitentes ou fracas, desde quando,
    a perda do dia e o que a equipe já marcou — a fonte da tela Leituras, nada calculado aqui (17/11/2026: o Inv 13 de
    Pirapozinho com a 6S27 e a 6S28 zeradas desde 19/10, 174,5 kWh por dia)."""
    inv = next((i for i in await _leituras_strings(ctx, slug, dia) if str(i["serial_number"]) == serial), {})
    ruins = [x for x in inv.get("strings") or [] if x.get("registered") and x.get("status") in _ESTADO]
    if not ruins:
        return None
    textos = []
    for x in ruins:
        t = f"{x.get('tag') or 'PV' + str(x.get('number'))} {_ESTADO[x['status']]}"
        if x.get("zero_since"):
            t += f" desde {date.fromisoformat(str(x['zero_since'])[:10]):%d/%m/%Y}" + (
                " ou antes" if x.get("zero_since_before_window") else "")
        if (m := x.get("mark") or {}).get("note"):
            t += f" (a equipe já marcou: {m['note']})"
        textos.append(t)
    return {"strings": textos, **({"perda_kwh_dia": inv["loss_kwh_day"]} if inv.get("loss_kwh_day") else {})}


_GERACAO: dict[tuple[int, str, str], tuple[float, dict]] = {}


async def _geracao_do_dia(ctx, slug: str, dia: date) -> dict[str, tuple[datetime | None, float]]:
    """{número de série: (quando ligou, kWh do dia)} pela curva de 5 min do meuWatt (o kWh é o do contador)."""
    k = (ctx.user.id, slug, dia.isoformat())
    if (c := _GERACAO.get(k)) and time.monotonic() - c[0] < 120:
        return c[1]
    r = await chamar(ctx, "monitoramento_curva_5min", {"slug": slug, "date": dia.isoformat()})
    d = dados_de(r) if not r.get("isError") else None
    pot: dict[str, list] = {}
    cont: dict[str, float] = {}
    for (ent, c), pts in (observacoes(d, dia) if d else {}).items():
        if (sn := dict(ent).get("serial_number")) and pts:
            if c == "power_kw":
                pot[sn] = sorted(pts)
            elif c == "daily_gen_kwh":
                cont[sn] = max(v for _t, v in pts)
    out = {}
    for sn, pts in pot.items():
        ij = _sol(pts)
        out[sn] = (pts[ij[0]][0] if ij else None, cont.get(sn) or _energia(pts))
    _GERACAO[k] = (time.monotonic(), out)
    return out


def _o_dia_do_inversor(serial: str, g: dict[str, tuple[datetime | None, float]]) -> str:
    ligou, kwh = g[serial]
    outros = [v for sn, v in g.items() if sn != serial]
    horas = sorted(t for t, _k in outros if t)
    cmp = (f" (os outros: {_num(statistics.median(k for _t, k in outros))} kWh" +
           (f", ligaram por volta das {horas[len(horas) // 2]:%H:%M}" if horas else "") + ")") if outros else ""
    return ("não ligou o dia todo (0 kWh)" if ligou is None else
            f"ligou às {ligou:%H:%M} e gerou {_num(kwh)} kWh") + cmp


async def _trafos_no_dia(ctx, slug: str, dia: date, no_grafico: set[str]) -> list[str]:
    """Cada trafo da usina no dia: a sonda mais quente e a carga dele — a soma dos inversores do skid, que é o que passa
    pelo trafo (o relé do skid pode estar mudo: 17/11/2026, o do Skid 2 de Pirapozinho parou às 08:40 com 717 kW e o
    skid ficou no teto de 1.000 kW até as 13:10). Mesma carga com 20 °C a menos diz que o problema é do trafo."""
    q = {"slug": slug, "date": dia.isoformat()}
    rt, ri, sit, mapa, ru = await asyncio.gather(chamar(ctx, "monitoramento_temperatura_trafos", q),
                                                 chamar(ctx, "monitoramento_curva_5min", q), situacao(ctx, slug),
                                                 apelidos(ctx, "monitoramento_curva_5min", q),
                                                 chamar(ctx, "monitoramento_detalhe_usina", {"slug": slug}))
    du = dados_de(ru) if not ru.get("isError") else None
    kva = {str(x.get("name")): float(x["power_kva"]) for x in (du.get("transformers") or [] if isinstance(du, dict)
                                                                else []) if x.get("power_kva")}

    def obs_de(r: dict) -> Obs:
        d = dados_de(r) if not r.get("isError") else None
        return observacoes(d, dia) if d else {}
    quente: dict[str, tuple[datetime, float, str]] = {}
    for (ent, c), pts in obs_de(rt).items():
        if (nome := dict(ent).get("name")) and re.fullmatch(r"temp_s\d", c) and pts:
            t, v = max(pts, key=lambda p: p[1])
            if nome not in quente or v > quente[nome][1]:
                quente[nome] = (t, v, nome_do_campo(c))
    carga: dict[str, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    for (ent, c), pts in obs_de(ri).items():
        if c == "power_kw" and (m := re.search(r"\(([^)]+)\)", equipamento(ent, mapa).exibir)):
            for t, v in pts:
                carga[m[1]][t] += v
    mudos = defaultdict(list)
    for d0, n in sorted((sit.get("sem_com") or {}).values()):
        if d0.date() <= dia:
            mudos[_skid_do(n, mapa)].append(f"{n} sem comunicação desde {d0:%d/%m %H:%M}")
    trafo = {nome: (sit.get("trafo_do_sensor") or {}).get(nome, "") for nome in quente}
    pico = {tr: max(v for _t, v in pts.items()) for tr, pts in carga.items() if pts}
    out = []
    for nome, (t, v, sonda) in sorted(quente.items()):
        tr = trafo[nome]
        linha = (f"{nome}{f' ({tr})' if tr else ''}{' (o do gráfico)' if nome in no_grafico else ''}: a {sonda} "
                 f"chegou a {_c(v)} °C às {t:%H:%M}")
        if pts := sorted(carga.get(tr, {}).items()):
            tt, mx = _teto(pts), max(pts, key=lambda p: p[1])
            linha += (f"; os inversores do skid ficaram no teto de {_num(tt['valor'])} kW por {tt['minutos']} min ("
                      + ", ".join(f"{x}–{y}" for x, y in tt["trechos"]) + ")" if tt else
                      f"; os inversores do skid chegaram a {_num(mx[1])} kW às {mx[0]:%H:%M}")
            if kva.get(tr):                # a carga em % do trafo (o TR-03 é de 500 kVA: 500 kW = 100%)
                linha += f" ({pico[tr] / kva[tr] * 100:.0f}% dos {_num(kva[tr])} kVA do trafo)"
            if mudos.get(tr):
                linha += f" ({', '.join(mudos[tr])}: o que gerou depois disso não está na soma)"
        out.append(linha)
    return out if len(out) > 1 else []


def _args(specs: list[dict], s: Serie) -> dict:
    a = specs[s.grupo].get("argumentos")
    return a if isinstance(a, dict) else {}


async def _o_que_explica(ctx, specs: list[dict], series: list[Serie], res: dict) -> dict:
    """O que a análise diz a mais, buscado no meuWatt: as strings do inversor que gera menos que os outros (a causa,
    não só a diferença), o que a isolação baixa custou no dia e os outros trafos da usina no mesmo dia."""
    item = {x["serie"]: x for x in res["series"]}
    extra: dict = {}
    pot = [s for s in series if s.unidade == "kW" and s.serial and s.estilo != "limite" and not s.sem_com_desde]
    if len(pot) >= 2 and not e_diario(pot):
        ens = {id(s): s.energia_contador or _energia(s.pontos) for s in pot}
        for s in [s for s in pot if (ref := statistics.median(ens[id(o)] for o in pot if o is not s))
                  and ens[id(s)] < 0.97 * ref][:3]:
            if (slug := slug_dos("monitoramento_", _args(specs, s))) and (
                    z := await strings_com_problema(ctx, slug, dia_dos(_args(specs, s)), s.serial)):
                ref = statistics.median(ens[id(o)] for o in pot if o is not s)
                z["medido_no_dia"] = (f"gerou {_num(ref - ens[id(s)])} kWh a menos que a mediana dos outros "
                                      f"({_num(ref)} kWh)")
                if "perda_kwh_dia" in z:
                    z["perda_estimada_pelo_monitoramento_kwh_dia"] = z.pop("perda_kwh_dia")
                    if _teto(s.pontos):
                        z["sobre_a_estimativa"] = ("é a conta das strings sem o teto do inversor: com ele no teto, "
                                                   "a perda real do dia é a medida (medido_no_dia)")
                item[s.rotulo]["strings_com_problema"] = z
    # a isolação abaixo do mínimo: o que aconteceu no dia. A leitura para às 10h (a sonda de diagnóstico só lê de
    # manhã): o fim do trecho NÃO é a hora em que o inversor ligou (17/11/2026: o Inv 14 não gerou nada em 03/11)
    iso = [s for s in series if s.unidade == "MΩ" and s.serial and s.estilo != "limite"]
    if iso:
        s0, (t0, v0) = min(((s, p) for s in iso for p in s.pontos), key=lambda sp: sp[1][1])
        extra["a_menor_isolacao"] = f"{_num(v0)} MΩ no {s0.equipamento}, em {t0:%d/%m %H:%M}"
    lim = next((x.pontos[0][1] for x in series if x.estilo == "limite" and x.unidade == "MΩ"), None)
    if iso and lim is not None and (slug := slug_dos("monitoramento_", _args(specs, iso[0]))):
        dias = sorted({t.date() for s in iso for t, v in s.pontos if v < lim})[-5:]
        gens = dict(zip(dias, await asyncio.gather(*(_geracao_do_dia(ctx, slug, d) for d in dias)), strict=True))
        for s in iso:
            for jan in item[s.rotulo].get("abaixo_do_minimo") or []:
                d = next((d for d in gens if d.strftime("%d/%m") == jan["dia"]), None)
                if d and s.serial in gens[d]:
                    jan["naquele_dia"] = _o_dia_do_inversor(s.serial, gens[d])
    sondas = [s for s in series if s.limites_temp]
    if sondas and (slug := slug_dos("monitoramento_", _args(specs, sondas[0]))) and (
            t := await _trafos_no_dia(ctx, slug, dia_dos(_args(specs, sondas[0])),
                                      {s.equipamento.split(" (")[0] for s in sondas})):
        extra["trafos_no_dia"] = t
    return extra


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
    if a.get("tipo") == "barras":     # barras = um valor por dia (o máximo; a energia, somada)
        series = [s if s.estilo == "limite" or e_diario([s]) else por_dia(s) for s in series]
    diario = e_diario(series)
    if not diario:   # curva no tempo com 1 ou 2 pontos: a consulta não dá curva (17/11/2026: a hora a hora "num ponto")
        problemas += [{"serie": s.rotulo, "erro": f"Só {len(s.pontos)} leitura(s): não dá curva no tempo com isso."}
                      for s in series if s.estilo != "limite" and len(s.pontos) < 3]
    if problemas:
        # nada pela metade (17/11/2026: o gráfico saiu só com o relé e a pessoa leu "os inversores ficaram de fora"):
        # volta o que errou, com o que existe, e a IA chama de novo com tudo certo — ou pergunta antes à pessoa
        return {"erro": "Nada desenhado ainda: " + ("nenhuma série saiu." if not series else
                                                     f"{len(problemas)} problema(s) nas entradas."),
                "problemas": problemas, **({"ja_deram": [s.rotulo for s in series][:12]} if series else {}),
                "como_seguir": ("Não desenhe ainda: pergunte à pessoa o que está em `pergunte` (com as opções do "
                                "erro) e desenhe tudo junto depois da resposta." if any(p.get("pergunte") for p in
                                                                                       problemas) else
                                "Corrija a consulta (veja `sugestoes`), os campos ou o equipamento pelo que existe "
                                "acima e chame de novo com TODAS as séries. Se uma delas não tem como sair, chame sem "
                                "ela e diga à pessoa por quê.")}
    fora = []
    if len(series) > MAX_SERIES:
        fora = [s.rotulo for s in series[MAX_SERIES:]]
        series = series[:MAX_SERIES]
    trafo = {}          # a ventilação, o alarme e o desligamento do relé de temperatura: uma linha de cada, no valor dele
    for s in series:
        for k, nome, traco in (("ventilacao", "ventilação", "-."), ("alarme", "alarme", ":"),
                               ("desligamento", "desligamento", "--")):
            if s.limites_temp and (v := s.limites_temp.get(k)) is not None and (k, v) not in trafo:
                trafo[(k, v)] = Serie(f"{nome} do relé de temperatura ({_br(v)} °C)", "°C", [(s.pontos[0][0], float(v))],
                                      estilo="limite", campo="limite_trafo", traco=traco)
    series += list(trafo.values())
    for s in [s for s in series if s.unidade == "kW" and s.estilo != "limite" and e_diario([s])][:1]:
        mx = max(v for _t, v in s.pontos)
        if sum(v >= 0.995 * mx for _t, v in s.pontos) >= 2:      # dois dias ou mais no mesmo máximo: é o teto
            series.append(Serie(f"teto {_de_quem(s)} ({_num(mx)} kW)", "kW", [(s.pontos[0][0], mx)], estilo="limite",
                                campo="limite_teto", traco="--"))
    unidades = list(dict.fromkeys(s.unidade for s in series))
    if len(unidades) > 2:
        return {"erro": f"Unidades demais num gráfico só ({', '.join(u or 'sem unidade' for u in unidades)}): um "
                        "gráfico tem no máximo duas (dois eixos). Divida em dois gráficos.",
                "series": [f"{s.rotulo} ({s.unidade or '—'})" for s in series]}
    titulo = titulo_com_data(str(a.get("titulo") or " × ".join(dict.fromkeys(
        s.rotulo for s in series if s.estilo != "limite")))[:120], series)
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
    extra = await _o_que_explica(ctx, specs, series, res)
    return {"grafico": titulo, "enviado_no_chat": ok, **({} if ok else {"erro": (r or {}).get("erro") or "não enviou"}),
            **({"pedido_e_achado": achados, "como_achou": "pelo cadastro do meuWatt; nos nomes Inv XY, X é o skid e Y "
                                                          "o inversor (Inv 12 = skid 1, inversor 2): já confirmado, não "
                                                          "peça para conferir"} if achados else {}),
            "analise": res, **extra,
            **({"sobre_a_isolacao": _ISOLACAO} if any(s.unidade == "MΩ" for s in series) else {}),
            **({"ficaram_de_fora": fora, "por_que": f"no máximo {MAX_SERIES} linhas num gráfico"} if fora else {}),
            **({"comunicacao": sorted(set(avisos))} if avisos else {}),
            "nota": _NOTA}


def series_para_ler(obs: Obs, mapa: Apelidos, teto: int = 30, sit: dict | None = None) -> dict:
    """O resumo das séries de uma consulta, para a IA ler sem os pontos (`consultar`): os equipamentos, os campos e,
    quando cabe, a análise de cada série (as sondas do trafo com os limites do relé)."""
    todas, _p = series_de(obs, mapa, [], [])
    for s in todas:
        s.limites_temp = (((sit or {}).get("temps") or {}).get(s.equipamento.split(" (")[0]) or {}).get(s.campo)
    equipos = list(dict.fromkeys(s.rotulo.split(" · ")[0] for s in todas if " · " in s.rotulo))
    campos = list(dict.fromkeys(c for (_e, c) in obs))
    out: dict = {"equipamentos": equipos[:40], "campos": [f"{c} ({unidade(c) or '—'})" for c in campos][:60],
                 "series": len(todas)}
    if len(todas) <= teto:
        out["analise"] = analise(todas)["series"]
    return out
