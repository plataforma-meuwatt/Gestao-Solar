"""A FOTO do mapa único pelo bot (o dono, 18/11/2026: "se uma string der problema quero que pinte lá, e aí, o bot manda
um print com a string pintada e a posição dela, nome etc.").

A foto é a da PRÓPRIA página do mapa (`<portal>/usinas/<id>/mapa?destaque=<objeto>&print=1`, o bloco `#mapa-unico-foto`):
a cor, o destaque e a legenda são os de lá, nunca uma segunda pintura feita aqui — e a legenda da foto no WhatsApp é a
que a página desenhou. Ela abre num Chromium sem tela que só existe durante a foto, com uma sessão do portal da pessoa de
5 minutos (`criar_token(minutos=)`, que o `usuario_atual` aceita para qualquer conta ativa; o `quem_abre` da página decide
as usinas pelo perfil), gravada só na origem do portal. A aba só LÊ a API: o que não é GET é recusado (nem renovar a
sessão, nem mexer no mapa). A foto só sai se a página puser o equipamento pedido na legenda (senão seria a usina inteira
com o nome errado embaixo) e se o desenho tiver posição (sem ela não há o que destacar).

O objeto é achado no mapa lido com o token PRÓPRIO da pessoa (a regra do bot) — por isso a ferramenta pede as partes do
meuPlano E do meuWatt: com os dois tokens dela, a página também lê com eles. O nome casa palavra a palavra, NA ORDEM
("U1-3S22" não é "U3-1S22"; "câmera 7" não é o "Inversor 7"); a palavra do tipo dita junto ("a string U1-3S22", "trafo
2") procura só entre os daquele tipo; sem achado, o meuPlano procura pelo nome e pelos apelidos do equipamento. A
posição (o centro do desenho) vai ao pé da resposta em Google Maps e Waze, como a `local_da_usina`, e sai também quando
a foto não sai. À IA vai o estado com o porquê e a hora do dado: "Normal" só com dado de até 2 h (a regra "nunca
enganar").
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from app.clients import whatsapp
from app.core.config import get_settings
from app.core.datas import hora_brt
from app.services.assistente_local import _mapa, _waze
from app.services.assistente_meuguarda import escolher

log = logging.getLogger("gs.assistente.mapa")

#: Uma foto por vez no contêiner: o Chromium sem tela usa uns 250 MB, e o teto da API é 2 GB.
_UMA_POR_VEZ = asyncio.Semaphore(1)
#: A página marca `data-pronto` com o satélite E o voo carregados; mais que isso, a foto não sai.
ESPERA_S = 40
FECHAR_S = 10
SESSAO_MIN = 5
#: Dado mais velho que isto não pinta "Normal": diz de quando é o último.
FRESCO = timedelta(hours=2)
#: Os rótulos da própria página (`ROTULO_ESTADO` de portal/src/features/mapa/Pagina.tsx).
ROTULO_ESTADO = {"alarme": "Em alarme", "problema": "Com problema", "sem_dado": "Sem dado", "ok": "Normal"}
#: Aqui "câmera" conta (distingue a câmera 7 do inversor 7): não é o enchimento do meuGuarda, onde tudo é câmera.
_ENCHIMENTO = {"a", "o", "as", "os", "da", "de", "do", "das", "dos", "no", "na", "ufv", "usina"}
#: O tipo que a palavra dita pede (`tipo` do mapa do meuWatt ou `node_tipo` do meuPlano).
_TIPO_FALADO = {"string": "string", "strings": "string", "inversor": "inversor", "inv": "inversor",
                "trafo": "transformador", "transformador": "transformador", "mesa": "mesa", "camera": "camera",
                "subestacao": "subestacao", "estacao": "estacao", "caixa": "caixa_juncao"}

FERRAMENTA = {"type": "function", "function": {
    "name": "mapa_equipamento",
    "description": ("A FOTO do mapa da usina com UM equipamento em destaque (uma string, um inversor, um trafo, uma "
                    "câmera, uma mesa), com o nome e a cor do estado; o sistema manda a imagem e, ao pé da sua "
                    "resposta, os links do Google Maps e do Waze de onde ele fica (não escreva os links). Use quando "
                    "perguntarem ONDE FICA um equipamento ou pedirem para mostrá-lo no mapa. NÃO é para documento: "
                    "planta (a planta de strings), projeto, diagrama, unifilar ou PDF vão à `manutencao`."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "nome da usina"},
        "equipamento": {"type": "string",
                        "description": "o nome como a pessoa disse (\"U1-3S22\", \"câmera 1\", \"Inv 13 string 26\")"}},
        "required": ["usina", "equipamento"]}}}

#: A linha do prompt: só para quem tem a ferramenta (os outros seguem perguntando à `manutencao`, como antes).
PROMPT = """- ONDE FICA um equipamento da usina (string, inversor, trafo, câmera, mesa), "mostra no mapa", a foto do mapa dele →
  `mapa_equipamento`, com a usina e o nome como a pessoa disse: o sistema manda a foto do mapa com ele em destaque e
  os links de onde fica; você só diz uma linha, sem os links. A localização da USINA continua `local_da_usina`; um
  DOCUMENTO (planta de strings, projeto, diagrama, unifilar, PDF) continua `manutencao`."""


def centro(geometria: dict | None) -> tuple[float, float] | None:
    """(lat, lng) do meio do desenho: o ponto, a média dos vértices da linha ou do contorno (sem o vértice que fecha)."""
    g = geometria or {}
    tipo, c = g.get("type"), g.get("coordinates")
    try:
        if tipo == "Point":
            pontos = [c]
        elif tipo == "LineString":
            pontos = c
        elif tipo == "Polygon":
            anel = c[0]
            pontos = anel[:-1] if len(anel) > 1 and anel[0] == anel[-1] else anel
        else:
            return None
        lng = sum(float(p[0]) for p in pontos) / len(pontos)
        lat = sum(float(p[1]) for p in pontos) / len(pontos)
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None
    return lat, lng


def palavras(texto) -> list[str]:
    """O nome como se fala, na ordem: sem acento, minúsculo, número sem o zero da frente ("Câmera 01" → camera, 1)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return [str(int(p)) if p.isdigit() else p for p in re.findall(r"[a-z]+|\d+", t) if p not in _ENCHIMENTO]


def _mesma(f: str, n: str) -> bool:
    if f.isdigit() or n.isdigit():
        return f == n
    return f == n or (min(len(f), len(n)) >= 3 and (f.startswith(n) or n.startswith(f)))


def casa(dito, nome) -> bool:
    """Palavra a palavra e na ordem: número só com o mesmo número; palavra pelo começo ("inversor 13" = "INV-13")."""
    f, n = palavras(dito) if isinstance(dito, str) else dito, palavras(nome)
    return bool(f) and len(f) == len(n) and all(_mesma(a, b) for a, b in zip(f, n))


def nomes_do_objeto(o: dict, estado_obj: dict | None) -> list[str]:
    """Os nomes que a pessoa pode dizer: o do desenho, o do nó do meuPlano e o do equipamento que o monitoramento diz que
    ele é ("Inv 13 · string 26 (6S26)" também como "Inv 13 string 26" e "string 26 do inversor 13")."""
    nomes = [o.get("nome"), o.get("node_nome")]
    eq = (estado_obj or {}).get("equipamento")
    if eq:
        partes = eq.split(" (")[0].split(" · ")
        nomes += [eq, " ".join(partes), " ".join(reversed(partes))]
    return [n for n in nomes if n]


def _nome(o: dict) -> str | None:
    return o.get("node_nome") or o.get("nome")


def achar(objetos: list[dict], estado: dict, termo: str) -> tuple[list[dict], list[str]]:
    """(os objetos que casam, os nomes do tipo pedido para a IA oferecer quando nenhum casa)."""
    def nomes(o):
        return nomes_do_objeto(o, estado.get(o.get("id")))

    achados = [o for o in objetos if any(casa(termo, n) for n in nomes(o))]
    ditas = palavras(termo)
    tipo = next((_TIPO_FALADO[p] for p in ditas if p in _TIPO_FALADO), None)
    do_tipo = [o for o in objetos if tipo and tipo in (o.get("tipo"), o.get("node_tipo"))]
    if not achados and do_tipo:
        # a palavra do tipo dita junto ("a string U1-3S22", "trafo 2"): sem ela, só entre os daquele tipo — o nome
        # inteiro na ordem, ou só os números na ordem quando a pessoa disse só números ("trafo 2" = "TR-02")
        resto = [p for p in ditas if p not in _TIPO_FALADO]
        achados = [o for o in do_tipo if any(casa(resto, n) for n in nomes(o))]
        if not achados and resto and all(p.isdigit() for p in resto):
            achados = [o for o in do_tipo if any([p for p in palavras(n) if p.isdigit()] == resto for n in nomes(o))]
    if achados:
        return achados, []
    return [], [n for n in map(_nome, do_tipo) if n]


def alvo(usina_id: int, objeto_id: int) -> str:
    return f"{get_settings().portal_web_url.rstrip('/')}/usinas/{usina_id}/mapa?destaque={objeto_id}&print=1"


def guardar_sessao(sessao: dict, url: str) -> str:
    """O script que grava a sessão no `gs_portal_sessao` — só na origem do portal, nunca em outra página da aba."""
    p = urlsplit(url)
    return (f"if (location.origin === {json.dumps(f'{p.scheme}://{p.netloc}')}) {{ try {{ localStorage.setItem("
            f"'gs_portal_sessao', {json.dumps(json.dumps(sessao))}) }} catch (e) {{}} }}")


async def _so_leitura(rota):
    """Na aba da foto, a API só é LIDA: renovar a sessão, desenhar ou apagar é recusado."""
    if rota.request.method not in ("GET", "HEAD"):
        await rota.abort()
    else:
        await rota.continue_()


async def foto(usina_id: int, objeto_id: int, sessao: dict, esperado: str | None) -> tuple[bytes, str]:
    """A página do mapa, aberta como a pessoa, com o objeto em destaque: (o JPEG do bloco `#mapa-unico-foto`, a legenda
    que a página desenhou). Falha com o motivo se a página der erro, o voo não carregar ou o objeto pedido não estiver
    na legenda."""
    from playwright.async_api import async_playwright

    url = alvo(usina_id, objeto_id)
    async with _UMA_POR_VEZ, async_playwright() as p:
        navegador = await p.chromium.launch()
        try:
            contexto = await navegador.new_context(viewport={"width": 1100, "height": 900}, locale="pt-BR")
            await contexto.add_init_script(guardar_sessao(sessao, url))
            await contexto.route("**/api/**", _so_leitura)    # só a API: o satélite e o voo não passam pelo Python
            pagina = await contexto.new_page()
            await pagina.goto(url, wait_until="domcontentloaded", timeout=ESPERA_S * 1000)
            # pronto = o satélite E o voo carregados; o voo que falha marca `data-voo="falhou"` e o pronto não sai
            pronto = pagina.locator('#mapa-unico[data-pronto="1"]')
            voo = pagina.locator('#mapa-unico[data-voo="falhou"]')
            erro = pagina.get_by_text("Não deu para carregar")
            await pronto.or_(voo).or_(erro).first.wait_for(timeout=ESPERA_S * 1000)
            if await erro.count():
                raise RuntimeError("a página do mapa deu erro: " + (await pagina.locator("body").inner_text())[:200])
            if await voo.count():
                raise RuntimeError("a imagem do voo não carregou")
            legenda = (await pagina.locator("#mapa-unico-foto > div").first.inner_text()).strip()
            # com o objeto achado, a legenda é "<usina> · <nome> (<tipo>) …"; sem ele, só a usina
            if " · " not in legenda or (esperado and esperado not in legenda):
                raise RuntimeError(f"a página não pôs {esperado!r} em destaque (legenda: {legenda[:120]!r})")
            await pagina.wait_for_timeout(600)          # o destaque e as cores por cima do fundo recém-carregado
            return await pagina.locator("#mapa-unico-foto").screenshot(type="jpeg", quality=85), legenda
        finally:
            try:
                await asyncio.wait_for(navegador.close(), FECHAR_S)
            except Exception:                                 # noqa: BLE001 — o Chromium preso não prende a trava
                log.warning("o Chromium da foto do mapa não fechou em %s s", FECHAR_S)


def _sessao(ctx) -> dict:
    """A sessão do portal desta pessoa, de 5 minutos, no formato que o portal guarda (`gs_portal_sessao`)."""
    from app.api.v1.auth import _perfil
    from app.core.security import criar_token
    token, expira = criar_token(ctx.user.id, minutos=SESSAO_MIN)
    return {"token": token, "expira_em": expira.isoformat(), "usuario": _perfil(ctx.db, ctx.user).model_dump(mode="json")}


def _quando(iso) -> datetime | None:
    if not isinstance(iso, str):
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


async def _estado(ctx, slug: str | None) -> tuple[dict, str | None]:
    """(o estado por objeto, o porquê de não haver estado)."""
    from app.services.vinculos import SemConexao, cliente_meuwatt
    if not slug:
        return {}, "o mapa desta usina não está ligado ao monitoramento"
    try:
        bruto = await cliente_meuwatt(ctx.db, ctx.user.id, so_proprio=True).mapa_estado(slug)
    except SemConexao:
        return {}, "falta o token do monitoramento desta pessoa"
    except httpx.HTTPStatusError as e:
        return {}, ("o estado dos equipamentos ainda não está disponível" if e.response.status_code == 404
                    else "o estado dos equipamentos não pôde ser lido agora")
    except httpx.HTTPError:
        return {}, "o estado dos equipamentos não pôde ser lido agora"
    objetos = bruto.get("objetos") if isinstance(bruto, dict) else None
    if not isinstance(objetos, list):
        return {}, "o estado dos equipamentos veio num formato inesperado"
    return ({int(o["objeto_id"]): {**o, "dados_de": bruto.get("dados_de")} for o in objetos
             if isinstance(o, dict) and str(o.get("objeto_id", "")).isdigit()}, None)


def situacao(e: dict | None, sem_estado: str | None, agora: datetime) -> str:
    """O estado nas palavras da página, com o motivo e a hora do dado; "Normal" só com dado fresco."""
    if e is None:
        return "sem cor: " + (sem_estado or "este equipamento ainda não está ligado ao monitoramento")
    estado = e.get("estado")
    if estado not in ROTULO_ESTADO:
        return f"sem cor: estado desconhecido ({estado})"
    t = _quando(e.get("leitura_em")) or _quando(e.get("dados_de"))
    hora = hora_brt(t.isoformat()) if t else None
    if estado == "ok" and (t is None or agora - t > FRESCO):
        return "sem cor: " + (f"o último dado é de {hora}" if t else "o estado veio sem a hora do dado")
    return ROTULO_ESTADO[estado] + (f": {e['motivo']}" if e.get("motivo") else "") + (
        f" (dado de {hora})" if hora else "")


async def mapa_equipamento(ctx, a: dict) -> dict:
    from app.api.v1.mapa import usinas_do_mapa
    from app.services.vinculos import SemConexao, cliente_meuplano

    usinas = [{"nome": u.nome, "link": u} for u in usinas_do_mapa(ctx.db, ctx.user)]
    if len(usinas) == 1 and not (a.get("usina") or "").strip():
        escolhida = usinas[0]                               # a única que a pessoa vê
    else:
        escolhida, opcoes = escolher(usinas, a.get("usina") or "")
        if escolhida is None:
            return {"erro": "Falta a usina, ou ela é ambígua: pergunte qual.",
                    "opcoes": [u["nome"] for u in opcoes or usinas]}
    link = escolhida["link"]
    if link.mp_usina_id is None:
        return {"erro": f"A usina {link.nome} ainda não tem o mapa (não está ligada à manutenção)."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto os produtos respondem
    try:
        mapa = await mp.mapa_da_usina(link.mp_usina_id)
    except httpx.HTTPError:
        return {"erro": f"O mapa de {link.nome} não pôde ser lido agora."}
    objetos = [o for o in mapa.get("objetos") or [] if isinstance(o, dict) and o.get("id") is not None]
    if not objetos:                                       # "vazio" só quando o mapa foi LIDO e está vazio
        if mapa.get("aviso"):
            return {"erro": f"O mapa de {link.nome} não pôde ser lido agora: {mapa['aviso']}"}
        if mapa.get("vinculado") is False:
            return {"erro": f"O mapa de {link.nome} ainda não está ligado ao monitoramento: não há voo nem marcação."}
        return {"erro": f"O mapa de {link.nome} ainda não tem nada marcado."}
    estado, sem_estado = await _estado(ctx, mapa.get("slug"))
    termo = a.get("equipamento") or ""
    achados, do_tipo = achar(objetos, estado, termo)
    if not achados:                                       # o meuPlano conhece os apelidos ("o switch da cabine")
        try:
            previa = await mp.ponto_no_mapa_previa(link.mp_usina_id, termo)
            nos = {x.get("node_id") for x in (previa or {}).get("achados") or [] if x.get("node_id")}
            achados = [o for o in objetos if o.get("node_id") in nos]
        except httpx.HTTPError:
            pass
    ctx.db.commit()
    if len(achados) != 1:
        nomes = sorted({_nome(o) or f"objeto {o['id']}" for o in achados}) or do_tipo
        mais = f" (e mais {len(nomes) - 12})" if len(nomes) > 12 else ""
        return {"erro": f"'{termo}' " + ("é ambíguo" if achados else f"não está no mapa de {link.nome}")
                        + ": pergunte qual é" + (", com os nomes de `opcoes`" if nomes else "") + mais + ".",
                "opcoes": nomes[:12]}
    objeto = achados[0]
    nome = _nome(objeto) or f"objeto {objeto['id']}"
    e = estado.get(objeto["id"])
    resposta = {"equipamento": nome, "usina": link.nome, "situacao": situacao(e, sem_estado, datetime.now(UTC))}
    if e and e.get("equipamento"):
        resposta["ligado_a"] = e["equipamento"]           # "Inv 13 · string 26 (6S26)": o "nome etc." do pedido
    ponto = centro(objeto.get("geometria"))
    if not ponto:                                         # sem posição não há o que destacar nem aonde levar
        return {**resposta, "erro": f"O desenho de {nome} não tem posição legível no mapa: sem foto e sem link."}
    ctx.rodape.append(f"📍 *{nome}*\nGoogle Maps: {_mapa(*ponto)}\nWaze: {_waze(*ponto)}")
    resposta["posicao"] = "o sistema manda os links do Google Maps e do Waze ao pé da sua resposta: não os escreva"
    if ctx.user.trocar_senha:
        return {**resposta, "erro": ("A foto abre no portal, e esta conta ainda está com a senha provisória: a pessoa "
                                     f"troca a senha no portal ({get_settings().portal_web_url}) e a foto passa a sair; "
                                     "os links vão ao pé da sua resposta.")}
    na_fila = _UMA_POR_VEZ.locked()
    sessao = _sessao(ctx)
    ctx.db.commit()                                       # a conexão não fica presa durante a foto
    try:
        jpeg, desenhada = await asyncio.wait_for(foto(link.id, int(objeto["id"]), sessao, _nome(objeto)),
                                                 timeout=ESPERA_S + FECHAR_S + 10)
    except Exception as exc:                              # noqa: BLE001 — a posição sai mesmo sem a foto
        log.warning("foto do mapa (usina %s, objeto %s) não saiu: %s", link.id, objeto["id"], exc)
        fila = " (outra foto do mapa estava saindo: peça de novo em instantes)" if na_fila else ""
        return {**resposta, "erro": f"A foto do mapa não saiu agora{fila}; os links vão ao pé da sua resposta."}
    legenda = "🗺️ " + desenhada + (f" · {resposta['ligado_a']}" if resposta.get("ligado_a") else "")
    try:
        r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=jpeg, filename="mapa.jpg",
                                           mime="image/jpeg", texto=legenda)
    except Exception as exc:                              # noqa: BLE001 — o gateway fora não apaga a resposta
        log.warning("foto do mapa: o gateway não recebeu (%s)", exc)
        r = None
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(legenda)
    return {**resposta, "foto": legenda, "enviado_no_chat": ok,
            **({} if ok else {"erro": "O WhatsApp não recebeu a foto; os links vão ao pé da sua resposta."})}
