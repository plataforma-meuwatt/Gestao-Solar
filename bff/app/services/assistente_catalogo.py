"""O catálogo do conector do Claude dentro do bot: tudo o que o Claude da pessoa lê, o bot também lê.

O dono, 17/11/2026: "E se eu fizer o bot usar o mcp do claude, ele vai ficar muito mais poderoso, né?" — "faça tudo".
As ferramentas do bot continuam na frente (geração, paradas, gêmeo, balanço, ações com Sim e senha); quando nenhuma
serve, a IA procura no catálogo do conector único (`api/v1/mcp.py`: o monitoramento, a manutenção e as câmeras que o bot
responde a esta pessoa, com o token PRÓPRIO dela) e roda a consulta. Só LEITURA: o conector não tem ação. Duas
ferramentas em vez de cem: a lista inteira em toda mensagem deixaria o bot lento, caro e confuso.
"""

import base64
import json
import re
import time

from app.services import assistente_geracao as ger
from app.services import assistente_series as ser

#: O catálogo de cada pessoa, por 10 min: montar custa uma ida a cada produto.
_CACHE: dict[int, tuple[float, list[dict]]] = {}
CACHE_S = 600
TETO_TEXTO = 11_000  # o que vai à IA de um resultado (o bot corta cada resultado em 14 mil caracteres)
_VAZIAS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "para", "por",
           "com", "qual", "quais", "que", "um", "uma", "me", "tem", "ha", "hoje", "agora", "como", "esta", "estao", "ta",
           "sao", "ver", "veja", "mostra", "mostre", "quero", "saber", "usina", "usinas", "grafico", "graficos",
           "plote", "plotar", "gere", "gerar", "monte", "montar", "faca", "fazer", "desenhe", "compare", "comparar"}
#: a mesma coisa com outro nome, no pedido e no catálogo (17/11/2026: "relé" não achava "relés"; "trafo" não achava
#: "transformadores")
_MESMO = {"rele": "rele", "relay": "rele", "trafo": "transf", "transformador": "transf", "transformer": "transf",
          "inversor": "inver", "inverter": "inver", "potencia": "poten", "power": "poten", "string": "strin",
          "corrente": "corre", "current": "corre", "temperatura": "tempe", "temperature": "tempe",
          "isolacao": "isola", "insulation": "isola", "resistencia": "isola", "tensao": "tensa", "tenso": "tensa",
          "voltage": "tensa", "energia": "energ", "energy": "energ", "geracao": "energ", "irradiancia": "irrad",
          "irradiacao": "irrad", "sonda": "tempe", "medidor": "medid", "meter": "medid"}

FERRAMENTA_PROCURAR = {"type": "function", "function": {
    "name": "procurar_consulta",
    "description": ("Só quando NENHUMA outra ferramenta serve: procura no catálogo completo de consultas de leitura "
                    "a que responde a pergunta."),
    "parameters": {"type": "object", "properties": {
        "assunto": {"type": "string", "description": "do que a pessoa quer saber, em poucas palavras"}},
        "required": ["assunto"]}}}

FERRAMENTA_CONSULTAR = {"type": "function", "function": {
    "name": "consultar",
    "description": "Roda uma consulta do catálogo: o nome e os argumentos que `procurar_consulta` mostrou.",
    "parameters": {"type": "object", "properties": {
        "nome": {"type": "string"},
        "argumentos": {"type": "object", "description": "os parâmetros da consulta (ex.: slug da usina, datas)"}},
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
    """As palavras que contam, sem plural ("relés" = "relé", "inversores" = "inversor") e com os sinônimos da casa."""
    out = set()
    for p in re.findall(r"[a-z0-9]+", ger._norm(texto)):
        if len(p) <= 2 or p in _VAZIAS:
            continue
        p = p[:-2] if p.endswith("es") and len(p) > 6 else p[:-1] if p.endswith("s") and len(p) > 3 else p
        out.add(_MESMO.get(p, p)[:5])
    return out


async def _catalogo(ctx) -> list[dict]:
    from app.api.v1 import mcp
    agora = time.monotonic()
    guardado = _CACHE.get(ctx.user.id)
    if guardado and agora - guardado[0] < CACHE_S:
        return guardado[1]
    lista = await mcp._ferramentas(ctx.db, ctx.user)
    if any(t["name"] == "monitoramento_serie_grandezas" for t in lista):
        # a série de grandezas responde "potência de pico do dia", "energia do dia", "PR"… mas a descrição dela não diz
        # quais: os nomes vêm do próprio catálogo de grandezas do meuWatt (17/11/2026: "potência de pico de cada dia"
        # achava as diárias da manutenção)
        r = await mcp._chamar(ctx.db, ctx.user, "monitoramento_grandezas_catalogo", {"_completo": True})
        g = ser.dados_de(r) if not r.get("isError") else None
        nomes = [f"{x.get('label')} ({x.get('key')}, {x.get('unit')})" for x in (g or {}).get("grandezas") or []
                 if isinstance(g, dict) and x.get("key")]
        if nomes:
            lista = [{**t, "description": f"{t.get('description') or ''} Grandezas: {'; '.join(nomes)}."}
                     if t["name"] == "monitoramento_serie_grandezas" else t for t in lista]
    _CACHE[ctx.user.id] = (agora, lista)
    return lista


#: palavras de monitoramento: com elas, a consulta do monitoramento vem antes da manutenção (cuja descrição longa, cheia
#: de "equipamento" e "inversor", ganhava pela quantidade de palavras)
_DO_MONITORAMENTO = {"poten", "inver", "strin", "corre", "tempe", "trans", "rele", "isola", "energ", "irrad", "tensa",
                     "skid", "medid", "sonda", "pico", "curva", "geraç", "gerac"}
_DA_MANUTENCAO = {"ordem", "taref", "mater", "aces", "rocag", "manut", "custo", "contr", "pesso", "diari", "lugar",
                  "fatur", "pagam", "estoq", "visit", "relat", "senha"}


async def procurar_consulta(ctx, a: dict) -> dict:
    alvo = _palavras(a.get("assunto") or "")
    if not alvo:
        return {"erro": "Diga do que a pessoa quer saber (ex.: strings sem corrente, temperatura dos trafos)."}
    pontos = []
    for t in await _catalogo(ctx):
        d = t.get("description") or ""
        corpo = d if t["name"] == "monitoramento_serie_grandezas" else d[:300]
        p = 3 * len(alvo & _palavras(t["name"])) + len(alvo & _palavras(corpo))
        if p and alvo & _DO_MONITORAMENTO and not alvo & _DA_MANUTENCAO:
            p += 3 if t["name"].startswith("monitoramento_") else -2 if t["name"].startswith("manutencao_") else 0
        if p and ser.SERIE_NO_TEMPO.search(d):
            p += 1
        if p:
            pontos.append((p, t))
    pontos.sort(key=lambda x: -x[0])
    if not pontos:
        return {"erro": "Nenhuma consulta do catálogo casou com isso: diga de outro jeito, ou responda com as outras "
                        "ferramentas."}
    todas = {t["name"] for t in await _catalogo(ctx)}
    dica = (" Potência de CADA inversor: monitoramento_curva_5min (a série de grandezas é por usina ou skid, não por "
            "inversor); relé × inversores: some os inversores (somar) para comparar com o relé."
            if "monitoramento_curva_5min" in todas else "")
    dica += (" Período: 'último mês' = os últimos 30 dias até hoje (sem datas, a consulta já traz isso); 'mês passado' = o "
             "mês fechado. Pedido de ANÁLISE de relação (temperatura × potência…): grafico_de_series, que desenha e "
             "compara nos mesmos horários.")
    return {"consultas": [{"nome": t["name"], "descricao": (t.get("description") or "")[:400],
                           **({"serie_no_tempo": True} if ser.SERIE_NO_TEMPO.search(t.get("description") or "")
                              else {}),
                           "parametros": {k: _param(v)
                                          for k, v in (t.get("inputSchema") or {}).get("properties", {}).items()},
                           "obrigatorios": (t.get("inputSchema") or {}).get("required", [])}
                          for _, t in pontos[:8]],
            "como_usar": "Escolha a que responde e chame `consultar` com o nome e os argumentos; para GRÁFICO, chame "
                         "`grafico_de_series` direto com a(s) consulta(s) de `serie_no_tempo`, sem consultar antes (a curva de 5 em 5 "
                         "min traz CADA inversor: \"dos inversores\" é uma linha por inversor). A usina vai pelo slug "
                         "(o mesmo das outras ferramentas, ex.: porto-ferreira); datas AAAA-MM-DD." + dica}


async def consultar(ctx, a: dict) -> dict:
    from app.clients import whatsapp
    pedido = str(a.get("nome") or "")
    nome = await ser.nome_da_consulta(ctx, pedido) or pedido
    args = a.get("argumentos") if isinstance(a.get("argumentos"), dict) else {}
    r = await ser.chamar(ctx, nome, args)
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
    if r.get("isError"):
        return {"erro": "\n".join(textos)[:TETO_TEXTO] or "A consulta não respondeu."}
    extra = {"imagens_enviadas_no_chat": enviadas} if enviadas else {}
    dados = ser.dados_de(r)
    if dados is None:
        texto = "\n".join(textos)
        if len(texto) > TETO_TEXTO:
            texto = texto[:TETO_TEXTO * 2 // 3] + "\n… (cortado no meio) …\n" + texto[-TETO_TEXTO // 3:]
        return {"consulta": nome, "resultado": texto, **extra}
    obs = ser.observacoes(dados, ser.dia_dos(args))
    resumo = ser.series_para_ler(obs, await ser.apelidos(ctx, nome, args)) if obs else None
    return {"consulta": nome, **({"series_no_tempo": resumo} if resumo else {}),
            "dados": _enxuto(dados, 5_000 if resumo else TETO_TEXTO), **extra}


def _encurta(v, n: int = 3):
    """Lista longa vira as primeiras e as últimas, com quantas ficaram de fora no meio (por dentro, também)."""
    if isinstance(v, dict):
        return {k: _encurta(x, n) for k, x in v.items()}
    if isinstance(v, list):
        if len(v) > 2 * n + 2:
            return [_encurta(x, n) for x in v[:n]] + [f"… {len(v) - 2 * n} itens …"] + [_encurta(x, n) for x in v[-n:]]
        return [_encurta(x, n) for x in v]
    return v


def _enxuto(dados, teto: int) -> str:
    """O JSON que a IA lê: inteiro se cabe; senão encurtado (o começo e o fim de cada lista); por fim, cortado."""
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"), default=str)
    for n in (6, 3, 1):
        if len(texto) <= teto:
            return texto
        texto = json.dumps(_encurta(dados, n), ensure_ascii=False, separators=(",", ":"), default=str)
    return texto[:teto] + "…"


FERRAMENTAS = {"procurar_consulta": (procurar_consulta, FERRAMENTA_PROCURAR),
               "consultar": (consultar, FERRAMENTA_CONSULTAR),
               "grafico_de_series": (ser.grafico_de_series, ser.FERRAMENTA_GRAFICO)}


def permitidas(user) -> list[str]:
    from app.api.v1 import mcp
    return list(FERRAMENTAS) if mcp.servicos(user) else []
