"""O catálogo do conector do Claude dentro do bot: tudo o que o Claude da pessoa lê, o bot também lê.

O dono, 17/11/2026: "E se eu fizer o bot usar o mcp do claude, ele vai ficar muito mais poderoso, né?" — "faça tudo".
As ferramentas do bot continuam na frente (geração, paradas, gêmeo, balanço, ações com Sim e senha); quando nenhuma
serve, a IA procura no catálogo do conector único (`api/v1/mcp.py`: o monitoramento, a manutenção e as câmeras que o bot
responde a esta pessoa, com o token PRÓPRIO dela) e roda a consulta. Só LEITURA: o conector não tem ação. Duas
ferramentas em vez de cem: a lista inteira em toda mensagem deixaria o bot lento, caro e confuso.
"""

import asyncio
import base64
import io
import itertools
import json
import re
import time
from datetime import datetime

from app.core.datas import BRT, hora_brt
from app.services import assistente_geracao as ger

#: O catálogo de cada pessoa, por 10 min: montar custa uma ida a cada produto.
_CACHE: dict[int, tuple[float, list[dict]]] = {}
CACHE_S = 600
TETO_TEXTO = 40_000  # o começo E o fim: numa série do dia, o "agora" mora no fim
_VAZIAS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "para", "por",
           "com", "qual", "quais", "que", "um", "uma", "me", "tem", "ha", "hoje", "agora", "como", "esta", "estao", "ta",
           "sao", "ver", "veja", "mostra", "mostre", "quero", "saber", "usina", "usinas"}

FERRAMENTA_PROCURAR = {"type": "function", "function": {
    "name": "procurar_consulta",
    "description": ("Só quando NENHUMA outra ferramenta serve: procura no catálogo completo de consultas de leitura "
                    "a que responde a pergunta."),
    "parameters": {"type": "object", "properties": {
        "assunto": {"type": "string", "description": "do que a pessoa quer saber, em poucas palavras"}},
        "required": ["assunto"]}}}

FERRAMENTA_CONSULTAR = {"type": "function", "function": {
    "name": "consultar",
    "description": ("Roda uma consulta do catálogo: o nome e os argumentos que `procurar_consulta` mostrou. Com "
                    "`grafico`, desenha as séries do resultado, manda a imagem no chat e volta só o resumo."),
    "parameters": {"type": "object", "properties": {
        "nome": {"type": "string"},
        "argumentos": {"type": "object", "description": "os parâmetros da consulta (ex.: slug da usina, datas)"},
        "grafico": {"type": "object", "description": "para pedido de gráfico; {} desenha a série no tempo com todos "
                                                     "os números",
                    "properties": {
                        "x": {"type": "string", "description": "campo do eixo x (sem ele, o de tempo)"},
                        "y": {"type": "array", "items": {"type": "string"},
                              "description": "campos a desenhar (sem eles, todos os números)"},
                        "so": {"type": "string", "description": "só o equipamento cujo nome contém isso"},
                        "titulo": {"type": "string"}, "unidade": {"type": "string"}}}},
        "required": ["nome"]}}}


def _param(v: dict) -> str:
    """O formato do parâmetro numa linha ("integer · 7–90 · padrão 30"): sem isso a IA chutava e levava 422."""
    outros = [x for x in v.get("anyOf") or [] if x.get("type") not in (None, "null")]
    tipo = v.get("type") or "/".join(x["type"] for x in outros) or "texto"
    fmt = v.get("format") or next((x.get("format") for x in outros if x.get("format")), None)
    partes = [tipo, {"date": "AAAA-MM-DD", "date-time": "ISO 8601"}.get(fmt or "", "")]
    if "minimum" in v or "maximum" in v:
        partes.append(f"{v.get('minimum', '')}–{v.get('maximum', '')}")
    if v.get("enum"):
        partes.append("um de: " + ", ".join(map(str, v["enum"][:8])))
    if v.get("default") is not None:
        partes.append(f"padrão {v['default']}")
    d = (v.get("description") or "").strip()
    return (" · ".join(p for p in partes if p) + (f" — {d}" if d else ""))[:200]


def _palavras(texto: str) -> set[str]:
    return {p[:6] for p in ger._norm(texto).replace("_", " ").split() if len(p) > 2 and p not in _VAZIAS}


async def _catalogo(ctx) -> list[dict]:
    from app.api.v1 import mcp
    agora = time.monotonic()
    guardado = _CACHE.get(ctx.user.id)
    if guardado and agora - guardado[0] < CACHE_S:
        return guardado[1]
    lista = await mcp._ferramentas(ctx.db, ctx.user)
    _CACHE[ctx.user.id] = (agora, lista)
    return lista


async def procurar_consulta(ctx, a: dict) -> dict:
    alvo = _palavras(a.get("assunto") or "")
    if not alvo:
        return {"erro": "Diga do que a pessoa quer saber (ex.: strings sem corrente, temperatura dos trafos)."}
    pontos = []
    for t in await _catalogo(ctx):
        nome, desc = _palavras(t["name"]), _palavras(t.get("description") or "")
        p = 2 * len(alvo & nome) + len(alvo & desc)
        if p:
            pontos.append((p, t))
    pontos.sort(key=lambda x: -x[0])
    if not pontos:
        return {"erro": "Nenhuma consulta do catálogo casou com isso: diga de outro jeito, ou responda com as outras "
                        "ferramentas."}
    return {"consultas": [{"nome": t["name"], "descricao": (t.get("description") or "")[:400],
                           "parametros": {k: _param(v)
                                          for k, v in (t.get("inputSchema") or {}).get("properties", {}).items()},
                           "obrigatorios": (t.get("inputSchema") or {}).get("required", [])}
                          for _, t in pontos[:6]],
            "como_usar": "Escolha a que responde e chame `consultar` com o nome e os argumentos. A usina vai pelo slug "
                         "(o mesmo das outras ferramentas, ex.: porto-ferreira); datas AAAA-MM-DD."}


async def consultar(ctx, a: dict) -> dict:
    from app.api.v1 import mcp
    from app.clients import whatsapp
    nome = str(a.get("nome") or "")
    r = await mcp._chamar(ctx.db, ctx.user, nome, a.get("argumentos") or {})
    textos, enviadas = [], 0
    for c in r.get("content") or []:
        if c.get("type") == "text":
            textos.append(c.get("text") or "")
        elif c.get("type") == "image":                     # a foto da câmera vai ao chat, não à IA
            ok = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image",
                                                arquivo=base64.b64decode(c["data"]), filename="imagem.jpg",
                                                mime=c.get("mimeType") or "image/jpeg", texto=textos[0] if textos else "")
            if ok and ok.get("ok"):
                enviadas += 1
                ctx.enviados.append(f"imagem de {nome}")
    texto = "\n".join(textos)
    if r.get("isError"):
        return {"erro": texto[:TETO_TEXTO] or "A consulta não respondeu."}
    g = {} if a.get("grafico") is True else a.get("grafico")
    if isinstance(g, dict):
        return await _grafico(ctx, nome, texto, g)
    if len(texto) > TETO_TEXTO:
        texto = (texto[:TETO_TEXTO * 2 // 3] + "\n… (cortado no meio: peça um recorte menor, por período ou por "
                 "equipamento) …\n" + texto[-TETO_TEXTO // 3:])
    return {"consulta": nome, "resultado": texto, **({"imagens_enviadas_no_chat": enviadas} if enviadas else {})}


# --------------------------------------------------------------------------- gráfico de uma consulta
# O dono, 17/11/2026: "Monte um gráfico da temperatura do trafo 2 de Pirapozinho do dia de hoje" — o bot não tinha a
# curva. Qualquer série do catálogo vira imagem: os dados vão do resultado direto ao desenho, e a IA recebe só o resumo
# (sem isso, 600 pontos de temperatura iriam e voltariam pela IA).
_X_TEMPO = ("time", "hora", "timestamp", "ts", "datetime", "data", "date", "dia", "t")
_ROTULO = ("name", "nome", "label", "rotulo")
_MAX_SERIES = 12


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _series(dados, g: dict) -> tuple[list[tuple[str, list]], dict[str, tuple[int, list[str]]], list[str], int]:
    """As séries no JSON da consulta: toda lista de objetos com o campo x e algum y (sem x, o 1º campo de tempo; sem y,
    todos os números); o nome é o do objeto de cima ("name") + o campo. Devolve também a forma das listas que achou e os
    equipamentos (e quantas listas o `so` tirou), para o erro dizer o que existe sem passar os dados."""
    x, ys = g.get("x"), [g["y"]] if isinstance(g.get("y"), str) else g.get("y")
    so = ger._norm(str(g.get("so") or ""))
    series, formas, nomes, fora = [], {}, [], 0

    def anda(no, caminho: str, rot: str) -> None:
        nonlocal fora
        if isinstance(no, dict):
            rot = next((str(no[k]) for k in _ROTULO if isinstance(no.get(k), (str, int))), rot)
            for k, v in no.items():
                anda(v, f"{caminho}.{k}" if caminho else k, rot)
            return
        if not isinstance(no, list) or not no or not all(isinstance(i, dict) for i in no):
            return
        chaves = list(dict.fromkeys(k for i in no for k in i))
        formas.setdefault(re.sub(r"\[\d+\]", "[]", caminho) or "(raiz)", (len(no), chaves))
        if rot and rot not in nomes:
            nomes.append(rot)
        cx = x if x in chaves else None if x else next((k for k in _X_TEMPO if k in chaves), None)
        auto = [c for c in chaves if c != "id" and not c.endswith("_id") and any(_num(i.get(c)) for i in no)]
        cys = [k for k in (ys or auto) if k in chaves and k != cx]
        if not (cx and cys):
            for n, item in enumerate(no):
                anda(item, f"{caminho}[{n}]", rot)
            return
        if so and so not in ger._norm(rot):
            fora += 1
            return
        for k in cys:
            if pts := [(i[cx], float(i[k])) for i in no if i.get(cx) is not None and _num(i.get(k))]:
                series.append((f"{rot} · {k}" if rot else k, pts))

    anda(dados, "", "")
    return series, formas, nomes, fora


def _eixo_x(v) -> tuple[tuple, str]:
    """(ordem, rótulo) de um valor do eixo x. Instante com fuso vira a hora de Brasília; sem fuso, já é (regra da casa)."""
    if _num(v):
        return (0, float(v)), f"{v:g}"
    s = str(v)
    if m := re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s):
        return (0, int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)), s
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return (1, s), s
    d = d if d.tzinfo else d.replace(tzinfo=BRT)
    return (0, d.timestamp()), d.strftime("%d/%m") if len(s) <= 10 else hora_brt(d.isoformat())


def _alinhar(series: list[tuple[str, list]]) -> tuple[list[str], list[float], list[tuple[str, list[float | None]]]]:
    """O eixo x comum, em ordem, e cada série nele (None onde ela não leu). Tempo e número ficam proporcionais (a
    leitura de 10 em 10 min não espreme a manhã contra a de 5 em 5); texto solto, um ao lado do outro."""
    rot: dict[tuple, str] = {}
    for _, pts in series:
        for xv, _v in pts:
            k, r = _eixo_x(xv)
            rot.setdefault(k, r)
    pos = {k: i for i, k in enumerate(sorted(rot))}
    linhas = []
    for nome, pts in series:
        ys: list[float | None] = [None] * len(pos)
        for xv, v in pts:
            ys[pos[_eixo_x(xv)[0]]] = v
        linhas.append((nome, ys))
    chaves = sorted(rot)
    xs = [float(k[1]) for k in chaves] if all(k[0] == 0 for k in chaves) else [float(i) for i in range(len(chaves))]
    return [rot[k] for k in chaves], xs, linhas


def _resumo(rotulos: list[str], linhas: list[tuple[str, list[float | None]]]) -> list[dict]:
    out = []
    for nome, ys in linhas:
        val = [(v, rotulos[i]) for i, v in enumerate(ys) if v is not None]
        mn, mx = min(val, key=lambda t: t[0]), max(val, key=lambda t: t[0])
        out.append({"serie": nome, "pontos": len(val), "minimo": {"valor": mn[0], "em": mn[1]},
                    "maximo": {"valor": mx[0], "em": mx[1]}, "ultimo": {"valor": val[-1][0], "em": val[-1][1]}})
    return out


def _desenhar_linhas(rotulos: list[str], xs: list[float], linhas: list[tuple[str, list[float | None]]], titulo: str,
                     unidade: str) -> bytes:
    """Linhas no estilo dos outros gráficos do bot. Buraco de leitura (mais de 3 passos típicos da própria série)
    quebra a linha: o gráfico não liga dois pontos por cima do que não foi lido."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5), dpi=110)
    for nome, ys in linhas:
        idx = [i for i, v in enumerate(ys) if v is not None]
        passos = sorted(xs[b] - xs[a] for a, b in itertools.pairwise(idx)) or [1.0]
        px, py = [], []
        for j, i in enumerate(idx):
            if j and xs[i] - xs[idx[j - 1]] > 3 * passos[len(passos) // 2]:
                px.append((xs[i] + xs[idx[j - 1]]) / 2)
                py.append(float("nan"))
            px.append(xs[i])
            py.append(ys[i])
        ax.plot(px, py, label=nome, linewidth=1.4, marker="." if len(idx) < 60 else None, markersize=4)
    passo = max(1, len(rotulos) // 12)
    longos = max(map(len, rotulos), default=0) > 6
    ax.set_xticks(xs[::passo])
    ax.set_xticklabels(rotulos[::passo], rotation=45 if longos else 0, ha="right" if longos else "center", fontsize=8)
    ax.set_ylabel(unidade)
    ax.set_title(titulo, fontsize=11)
    if len(linhas) > 1:
        ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


async def _grafico(ctx, nome: str, texto: str, g: dict) -> dict:
    from app.clients import whatsapp
    try:
        dados = json.loads(texto)
    except ValueError:
        return {"erro": "O resultado não veio inteiro em JSON (grande demais ou texto): peça um recorte menor (um dia, "
                        "um equipamento) ou responda sem gráfico."}
    series, formas, nomes, fora = _series(dados, g)
    if not series:
        if fora:
            return {"erro": f"Nenhum equipamento com «{g['so']}» no nome.", "equipamentos": nomes[:30]}
        return {"erro": "Nada para desenhar com esse x/y. As listas do resultado (quantos itens e os campos):",
                "listas": {c: f"{n} itens: {', '.join(k[:25])}" for c, (n, k) in list(formas.items())[:12]},
                **({"equipamentos": nomes[:30]} if nomes else {})}
    aviso = None
    if len(series) > _MAX_SERIES:
        aviso = f"{len(series)} séries: desenhei as {_MAX_SERIES} primeiras. Para escolher, use `so` ou `y`."
        series = series[:_MAX_SERIES]
    rotulos, xs, linhas = _alinhar(series)
    titulo = str(g.get("titulo") or (nome.replace("_", " ") + (f" · {g['so']}" if g.get("so") else "")))
    png = await asyncio.to_thread(_desenhar_linhas, rotulos, xs, linhas, titulo, str(g.get("unidade") or ""))
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=png, filename="grafico.png",
                                       mime="image/png", texto=titulo)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(titulo)
    return {"consulta": nome, "grafico": titulo, "enviado_no_chat": ok, "series": _resumo(rotulos, linhas),
            **({"aviso": aviso} if aviso else {}), **({} if ok else {"erro": (r or {}).get("erro") or "não enviou"})}


FERRAMENTAS = {"procurar_consulta": (procurar_consulta, FERRAMENTA_PROCURAR),
               "consultar": (consultar, FERRAMENTA_CONSULTAR)}


def permitidas(user) -> list[str]:
    from app.api.v1 import mcp
    return list(FERRAMENTAS) if mcp.servicos(user) else []
