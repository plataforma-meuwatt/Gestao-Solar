"""O catálogo do conector do Claude dentro do bot: tudo o que o Claude da pessoa lê, o bot também lê.

O dono, 17/11/2026: "E se eu fizer o bot usar o mcp do claude, ele vai ficar muito mais poderoso, né?" — "faça tudo".
As ferramentas do bot continuam na frente (geração, paradas, gêmeo, balanço, ações com Sim e senha); quando nenhuma
serve, a IA procura no catálogo do conector único (`api/v1/mcp.py`: o monitoramento, a manutenção e as câmeras que o bot
responde a esta pessoa, com o token PRÓPRIO dela) e roda a consulta. Só LEITURA: o conector não tem ação. Duas
ferramentas em vez de cem: a lista inteira em toda mensagem deixaria o bot lento, caro e confuso.
"""

import base64
import time

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
    if len(texto) > TETO_TEXTO:
        texto = (texto[:TETO_TEXTO * 2 // 3] + "\n… (cortado no meio: peça um recorte menor, por período ou por "
                 "equipamento) …\n" + texto[-TETO_TEXTO // 3:])
    if r.get("isError"):
        return {"erro": texto or "A consulta não respondeu."}
    return {"consulta": nome, "resultado": texto, **({"imagens_enviadas_no_chat": enviadas} if enviadas else {})}


FERRAMENTAS = {"procurar_consulta": (procurar_consulta, FERRAMENTA_PROCURAR),
               "consultar": (consultar, FERRAMENTA_CONSULTAR)}


def permitidas(user) -> list[str]:
    from app.api.v1 import mcp
    return list(FERRAMENTAS) if mcp.servicos(user) else []
