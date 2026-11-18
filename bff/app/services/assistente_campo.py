"""O técnico em CAMPO pelo WhatsApp (Renan, 18/11/2026: "o Diogo em campo vai ficar enviando as informações dos
equipamentos, marca, modelo, foto … envie a coordenada de uma câmera e fale, câmera 1, o bot veja se existe o nome,
senão existir ele guia para atualização dos nomes e aí salve a coordenada e já aloque no mapa").

- `posicionar_equipamento`: a localização recebida (📎, link do Google Maps ou coordenada escrita — `assistente_local`)
  vira a posição do equipamento que a pessoa nomeou, no MAPA ÚNICO da usina (o dono, 18/11/2026: "todos usam o mesmo
  … o meuGuarda só consome o mapa"): a posição mora no mapa do meuWatt, gravada pela rota do meuPlano
  (`POST /usinas/{id}/mapa/ponto`), o cadastro do equipamento é o do meuPlano — a câmera inclusive (as câmeras do
  meuGuarda entram no meuPlano). O nome que não existe ou repete volta com a lista (local e `node_id`), e a IA pergunta
  qual é; o nome certo dito em campo renomeia na mesma ação, com o Sim (a régua de renomear da tela de lá).
- `ler_plaqueta`: a IA COM VISÃO lê as fotos recebidas (fabricante, modelo, série, os dados elétricos) e devolve o que
  leu; quem cadastra é o meuPlano (`manutencao`), com o Sim de lá. A IA da conversa não vê foto: a leitura é esta.
- `fotos_no_equipamento`: as fotos recebidas vão para a ficha do equipamento no meuPlano (`POST /equipment/{id}/photos`).

Os números da localização NUNCA passam pela IA (um dígito trocado põe o equipamento em outra cidade): o sistema os lê
da localização guardada.
"""

import base64
import json
from time import monotonic

import httpx

from app.clients import whatsapp
from app.services import assistente_fotos as fotos
from app.services import assistente_helper as helper
from app.services import assistente_local as local

PRAZO_S = 600
_MAX_FOTOS_LIDAS = 4


def _sem_localizacao() -> dict:
    return {"erro": "Não há localização recebida (ela fica guardada 30 min). Peça que a pessoa mande pelo 📎 → "
                    "Localização, estando no equipamento."}


def _onde(lat: float, lng: float, rotulo: str = "") -> str:
    return local._ponto(lat, lng) + (f" ({rotulo})" if rotulo else "")


# ─────────────────────────────────────────────────────────────── posicionar_equipamento
FERRAMENTA_POSICIONAR = {"type": "function", "function": {
    "name": "posicionar_equipamento",
    "description": ("Põe no MAPA ÚNICO da usina (o mesmo no Gestão Solar, no meuPlano, no meuWatt e no meuGuarda) o "
                    "EQUIPAMENTO que a pessoa nomeou ('câmera 1', 'inversor 3', 'o switch da cabine'), na LOCALIZAÇÃO "
                    "que ela mandou («[📍 localização recebida…]»). Passe a usina e o nome como ela disse: os números vêm "
                    "da própria localização, nunca os escreva. Se o nome não existe ou é repetido, a ferramenta devolve "
                    "os nomes com o local e o `node_id`: mostre e pergunte qual é, e chame de novo com o `node_id` e "
                    "`apelido` = o nome que a pessoa usou (fica guardado e da próxima vez acha direto). CÂMERA: o nome é "
                    "do meuGuarda — nunca renomeie, só apelido. Outro equipamento com o nome errado: `renomear_para`."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "nome da usina"},
        "equipamento": {"type": "string", "description": "o nome como a pessoa disse ('câmera 1')"},
        "node_id": {"type": "integer", "description": "o equipamento escolhido na lista que a ferramenta devolveu"},
        "apelido": {"type": "string", "description": "o nome que a pessoa usou ('câmera 1'), guardado como apelido"},
        "renomear_para": {"type": "string", "description": "só fora da câmera: o nome certo, quando o da lista está errado"}},
        "required": ["usina", "equipamento"]}}}

#: a localização longe da usina não é dela: é a do posto onde a pessoa parou, a de ontem (o "📍" fica 30 min guardado)
LONGE_M = 3000


def _lista(itens: list[dict]) -> list[dict]:
    return [{"node_id": x["node_id"], "nome": x["nome"], "local": x.get("local")} for x in itens][:40]


async def _equipamento(mp, usina: dict, a: dict, previa: bool) -> tuple[dict | None, dict | None]:
    """(o equipamento, ou o erro para a IA): pelo `node_id` escolhido ou pelo nome dito — nunca adivinhado."""
    uid = int(usina["id"])
    r = await (mp.ponto_no_mapa_previa(uid, a["equipamento"]) if previa else mp.equipamento_pelo_nome(uid, a["equipamento"]))
    achados, parecidos = r.get("achados") or [], r.get("parecidos") or []
    if a.get("node_id") is not None:
        escolhido = [x for x in achados + parecidos if x.get("node_id") == int(a["node_id"])]
        if escolhido:
            return escolhido[0], None
        return None, {"erro": f"O equipamento {a['node_id']} não está entre os de '{a['equipamento']}' em {usina.get('name')}: "
                              "pergunte de novo.", "nomes_no_meuplano": _lista(achados or parecidos)}
    if len(achados) == 1:
        return achados[0], None
    return None, {"erro": (f"Há {len(achados)} equipamentos '{a['equipamento']}' em {usina.get('name')}: pergunte qual "
                           "(pelo local)." if achados else f"Não há '{a['equipamento']}' em {usina.get('name')}."),
                  "nomes_no_meuplano": _lista(achados or parecidos),
                  "como_seguir": ("Mostre os nomes com o local e pergunte qual é; chame de novo com o `node_id` e o "
                                  "`apelido` (o nome que ela usou). Câmera nunca se renomeia (o nome é do meuGuarda)."
                                  if (achados or parecidos) else
                                  "Diga que não existe e pergunte se é para cadastrar (pela `manutencao`).")}


async def posicionar_equipamento(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    loc = local.recebida(ctx.telefone)
    if loc is None:
        return _sem_localizacao()
    if not (a.get("equipamento") or "").strip():
        return {"erro": "Falta o equipamento: pergunte qual é ('câmera 1', 'inversor 3')."}
    if not (a.get("usina") or "").strip():
        return {"erro": "Falta a usina: pergunte de qual usina é o equipamento."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    try:
        if local.PERMISSAO not in (await mp.permissoes()):
            return {"erro": "O papel desta pessoa no meuPlano não marca coordenada. Nada foi gravado: o gestor da O&M "
                            "pode liberar."}
        usina, candidatas = local.escolher(await mp.usinas(), a["usina"])
        if usina is None:
            return {"erro": f"Usina '{a['usina']}' " + ("é ambígua" if candidatas else "não está entre as dela")
                            + ": pergunte qual é.", "opcoes": [local._rotulo_da_usina(u) for u in candidatas]}
        eq, erro = await _equipamento(mp, usina, a, previa=True)
    except httpx.HTTPStatusError as e:
        from app.services.integracoes import detalhe_do_upstream
        return {"erro": f"O meuPlano recusou: {str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip('. ')}."}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi gravado."}
    if erro:
        return erro
    lat, lng = loc["lat"], loc["lng"]
    if usina.get("latitude") is not None and usina.get("longitude") is not None:
        longe = local._m(usina["latitude"], usina["longitude"], lat, lng)
        if longe > LONGE_M:
            return {"erro": f"A localização recebida está a {local._metros(longe)} da usina {usina.get('name')}: não é a do "
                            "equipamento. Peça que a pessoa mande de novo pelo 📎 → Localização, estando no equipamento. "
                            "Nada foi gravado."}
    if eq.get("desenhado_como"):
        return {"erro": f"'{eq['nome']}' já está desenhado como área ou linha no mapa: o ponto do celular não substitui o "
                        "desenho. Quem muda é o mapa do meuWatt (Editar no meuWatt)."}
    novo = (a.get("renomear_para") or "").strip()
    novo = novo if novo and novo != eq["nome"] else ""
    apelido = (a.get("apelido") or "").strip()
    if novo and eq.get("tipo") in ("camera", "dvr"):      # o nome da câmera é do meuGuarda: o dito vira apelido
        apelido, novo = apelido or novo, ""
    if apelido and (apelido == eq["nome"] or apelido in (eq.get("apelidos") or [])):
        apelido = ""
    uid, idade = int(usina["id"]), max(0, int((monotonic() - loc["em"]) // 60))
    linhas = [f"Local: {_onde(lat, lng, loc['rotulo'])} (mandada há {idade} min)", local._mapa(lat, lng)]
    if eq.get("no_mapa"):
        p = eq["no_mapa"]
        linhas.insert(0, f"Hoje no mapa: {local._ponto(p['lat'], p['lng'])} (a {local._distancia(p['lat'], p['lng'], lat, lng)} da nova)")
    if novo:
        linhas.insert(0, f"Renomear: '{eq['nome']}' → '{novo}'")
    if apelido:
        linhas.insert(0, f"Apelido: '{apelido}' (o nome '{eq['nome']}' fica)")
    nome = novo or eq["nome"]
    resumo = (f"{'Renomear e marcar' if novo else 'Marcar'} {nome} ({eq.get('tipo_rotulo') or eq.get('tipo')}) de "
              f"{usina.get('name')} no mapa da usina")

    async def executar(db, user, telefone: str) -> str:
        from app.services.integracoes import detalhe_do_upstream
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
            r = await mp.marcar_no_mapa(uid, int(eq["node_id"]), lat, lng, novo or None, apelido or None)
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        except httpx.HTTPStatusError as e:
            return f"❌ O meuPlano recusou: {str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip('. ')}. Nada foi gravado."
        except httpx.HTTPError:
            return f"⚠️ O meuPlano não respondeu a tempo: {nome} PODE ter sido marcado. Confira no mapa."
        if local._RECEBIDAS.get(telefone, {}).get("em") == loc["em"]:
            del local._RECEBIDAS[telefone]
        avisos = "".join(f"\n• {x}" for x in r.get("avisos") or [])
        return (f"✅ {nome} {'renomeado e ' if novo else ''}marcado no mapa de {usina.get('name')}: "
                f"{local._ponto(lat, lng)}.{avisos}")

    return helper.propor(ctx, resumo, PRAZO_S, executar, linhas, parte="bot_meuplano", confirmacao="sim")


# ─────────────────────────────────────────────────────────────── ler_plaqueta
FERRAMENTA_PLAQUETA = {"type": "function", "function": {
    "name": "ler_plaqueta",
    "description": ("LÊ as fotos que a pessoa mandou («[📷 N foto(s)…]») de um EQUIPAMENTO — plaqueta, etiqueta, tela, "
                    "o equipamento instalado — e devolve o que está escrito: fabricante, modelo, nº de série e os dados "
                    "(tensão, corrente, potência, IP, MAC…). Você não vê a foto: esta leitura é o que há. Depois, para "
                    "cadastrar ou completar o equipamento, chame `manutencao` com a usina, o equipamento e o que foi lido."),
    "parameters": {"type": "object", "properties": {
        "o_que_e": {"type": "string", "description": "o que a pessoa disse que é (ex.: 'plaqueta do DJ geral')"}}}}}

_PROMPT_PLAQUETA = """Fotos de equipamento de uma usina solar, tiradas em campo (plaqueta, etiqueta, tela, painel).
{o_que}Leia SÓ o que está escrito nelas — nada deduzido, nada completado. Responda APENAS um JSON, uma lista com um objeto
por foto, na ordem:
[{{"foto": 1, "legivel": true, "equipamento": "o que é (ex.: disjuntor, switch, inversor)", "fabricante": "...",
"modelo": "...", "serie": "...", "dados": {{"rótulo como impresso": "valor como impresso"}}, "observacao": "..."}}]
O que não aparece ou não dá para ler: null. Foto ilegível: "legivel": false e o porquê em "observacao"."""


async def ler_plaqueta(ctx, a: dict) -> dict:
    from app.services.assistente import _llm
    lista = fotos.recebidas(ctx.telefone, sem_video=True)
    if not lista:
        return {"erro": "Não há foto recebida para ler (cada uma fica guardada 30 min). Peça que a pessoa mande a foto "
                        "da plaqueta de novo."}
    lidas = lista[-_MAX_FOTOS_LIDAS:]
    ctx.db.commit()
    imagens = []
    for f in lidas:
        try:
            conteudo, tipo = await whatsapp.baixar_midia(f["id"])
        except whatsapp.GatewayIndisponivel:
            continue
        tipo = (tipo or "image/jpeg").split(";")[0]
        imagens.append({"type": "image_url", "image_url": {"url": f"data:{tipo};base64,"
                                                                  + base64.b64encode(conteudo).decode()}})
    if not imagens:
        return {"erro": "Não consegui baixar as fotos do WhatsApp agora. Peça que a pessoa mande de novo."}
    o_que = f"A pessoa disse que é: {a['o_que_e'].strip()}.\n" if (a.get("o_que_e") or "").strip() else ""
    legendas = "; ".join(f["legenda"] for f in lidas if f.get("legenda"))
    if legendas:
        o_que += f"Legenda das fotos: {legendas}.\n"
    try:
        msg = await _llm([{"role": "user", "content": [{"type": "text", "text": _PROMPT_PLAQUETA.format(o_que=o_que)},
                                                        *imagens]}], [], teto_s=150)
        s = msg.get("content") or ""
        leitura = json.JSONDecoder().raw_decode(s[s.index("["):])[0]
    except (ValueError, httpx.HTTPError, KeyError):
        return {"erro": "Não consegui ler a foto agora. Peça a foto de novo, de perto e com luz, ou que a pessoa digite "
                        "o que está na plaqueta."}
    return {"fotos_lidas": len(imagens), "leitura": leitura if isinstance(leitura, list) else [leitura],
            "como_seguir": ("Diga em 1–2 linhas o que leu (fabricante, modelo, série). Para cadastrar ou completar o "
                            "equipamento, chame `manutencao` com a usina, o equipamento e esses dados. Para guardar a "
                            "foto na ficha dele, `fotos_no_equipamento`.")}


# ─────────────────────────────────────────────────────────────── fotos_no_equipamento
FERRAMENTA_FOTOS = {"type": "function", "function": {
    "name": "fotos_no_equipamento",
    "description": ("Guarda as fotos que a pessoa mandou («[📷 N foto(s)…]») na FICHA de um EQUIPAMENTO do meuPlano (a "
                    "foto do equipamento: plaqueta, instalação). Para foto de SERVIÇO numa tarefa ou OS é `anexar_fotos`. "
                    "Passe a usina e o nome do equipamento como ela disse. Vira uma ação com o Sim."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string"}, "equipamento": {"type": "string", "description": "o nome como a pessoa disse"},
        "node_id": {"type": "integer", "description": "o equipamento escolhido na lista que a ferramenta devolveu"}},
        "required": ["usina", "equipamento"]}}}


async def fotos_no_equipamento(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    lista = fotos.recebidas(ctx.telefone, sem_video=True)
    if not lista:
        return {"erro": "Não há foto recebida (vídeo não vai na ficha do equipamento; cada foto fica guardada 30 min)."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        usina, candidatas = local.escolher(await mp.usinas(), a.get("usina") or "")
        if usina is None:
            return {"erro": f"Usina '{a.get('usina')}' " + ("é ambígua" if candidatas else "não está entre as dela")
                            + ": pergunte qual é.", "opcoes": [local._rotulo_da_usina(u) for u in candidatas]}
        eq, erro = await _equipamento(mp, usina, {**a, "equipamento": a.get("equipamento") or ""}, previa=False)
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi guardado."}
    if erro:
        return erro
    if not eq.get("equipment_id"):
        return {"erro": f"'{eq['nome']}' está na árvore sem equipamento instalado: peça para completar o cadastro dele "
                        "(`manutencao`) e guarde a foto depois."}
    n = len(lista)
    resumo = f"Guardar {n} foto(s) na ficha de {eq['nome']} ({usina.get('name')})"

    async def executar(db, user, telefone: str) -> str:
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        feitas, falhas = 0, []
        for i, f in enumerate(lista, 1):
            try:
                conteudo, tipo = await whatsapp.baixar_midia(f["id"])
                tipo = (tipo or "image/jpeg").split(";")[0]
                await mp.foto_no_equipamento(int(eq["equipment_id"]), f"whatsapp-{i}.{tipo.split('/')[-1]}", conteudo,
                                             tipo, f["legenda"] or "Foto enviada pelo WhatsApp")
            except whatsapp.GatewayIndisponivel:
                falhas.append(f"foto {i}: não consegui baixar do WhatsApp")
                continue
            except httpx.HTTPStatusError as e:
                from app.services.integracoes import detalhe_do_upstream
                falhas.append(f"foto {i}: {str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip('. ')}")
                continue
            except httpx.HTTPError:
                falhas.append(f"foto {i}: o meuPlano não respondeu a tempo (pode ter entrado: confira)")
                continue
            feitas += 1
            fotos._tirar(telefone, f["id"])
        motivos = "".join(f"\n• {m}" for m in falhas)
        if not feitas:
            return f"❌ Nenhuma foto foi guardada em {eq['nome']}:{motivos}"
        if falhas:
            return f"⚠️ Guardei {feitas} de {n} foto(s) na ficha de {eq['nome']}:{motivos}"
        return f"✅ {feitas} foto(s) guardada(s) na ficha de {eq['nome']}."

    return helper.propor(ctx, resumo, PRAZO_S, executar, [eq.get("local") or ""], parte="bot_meuplano", confirmacao="sim")


FERRAMENTAS = {"posicionar_equipamento": (posicionar_equipamento, FERRAMENTA_POSICIONAR),
               "ler_plaqueta": (ler_plaqueta, FERRAMENTA_PLAQUETA),
               "fotos_no_equipamento": (fotos_no_equipamento, FERRAMENTA_FOTOS)}


def permitidas(user) -> list[str]:
    """Com o meuPlano no bot: as três (o cadastro e o mapa são de lá)."""
    return list(FERRAMENTAS) if "bot_meuplano" in user.bot_ativo else []
