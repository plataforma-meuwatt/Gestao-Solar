"""'Processar <usina>' pelo WhatsApp: o TermoVision organiza o voo, roda os ortomosaicos e devolve o link (pedido do dono,
23/11/2026: "eu quero enviar no whats 'Processar ibitinga' aí o sistema vai organizar as pastas, falar que deu certo,
no meio do caminho manda um link público com os status, quando acabar, ele manda um link público com o ortomosaico").

Contrato: `docs/contrato-gs-processar.md` do repositório do TermoVision (outro projeto, outro terminal; quem muda avisa).
- Quem pede é a PESSOA: o GS assina a asserção dela (`login_externo.assinar_login`, a mesma do "Entrar com o Gestão
  Solar") e o TermoVision abre a sessão dela; a plataforma nunca. Sem o TermoVision liberado, a ferramenta não existe.
- Ler as opções volta na hora; pedir o processamento é AÇÃO com o Sim (roda horas nos PCs e pode criar a usina).
- O andamento chega no aviso (`api/v1/termovision_aviso.py`): ele só RELÊ o andamento no TermoVision pelo token de um
  pedido daqui (`gs_processamentos_tv`) e manda uma mensagem curta quando a etapa muda.
"""

import logging
import unicodedata

import httpx

from app.core.config import get_settings
from app.models.processamento_tv import ProcessamentoTV
from app.models.user import Perfil
from app.services import assistente_helper as helper
from app.services import login_externo

log = logging.getLogger(__name__)

PRAZO_S = 600
_PORTAO = {Perfil.GESTOR_EMPRESA: "empresa", Perfil.TECNICO: "tecnico", Perfil.CLIENTE: "cliente"}
AVISO = "/api/v1/interno/termovision/processar"


def _base() -> str:
    return get_settings().termovision_api_url.rstrip("/")


def disponivel(user) -> bool:
    return user.perfil in _PORTAO and bool(user.termovision_liberado)


def assercao(db, user, liberado: bool | None = None) -> str:
    """A asserção da pessoa para o TermoVision (2 min, uso único). `liberado` sobrepõe o acesso (desligar)."""
    return login_externo.assinar_login(user, login_externo.TERMOVISION, _PORTAO.get(user.perfil, "painel"),
                                       getattr(user, "empresa_da_sessao", None) or user.empresa_id,
                                       login_externo.meuplano_id_de(db, user.id), db=db, liberado=liberado)


def _detalhe(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except ValueError:
        d = None
    return d if isinstance(d, str) and d else f"o TermoVision respondeu {r.status_code}"


async def _entrar(c: httpx.AsyncClient, db, user) -> str | None:
    """Abre a sessão da pessoa no cliente `c` (o cookie fica nele). Devolve o erro em português, ou None."""
    try:
        r = await c.post(f"{_base()}/api/conta/gs", json={"assercao": assercao(db, user)})
    except login_externo.SemChave as e:
        return str(e)
    except httpx.HTTPError:
        return "O TermoVision não respondeu agora. Nada foi feito: tente de novo em alguns minutos."
    from app.services import acessos
    acessos.registrar(db, None, acao="passe", sistema="termovision", user=user, ok=r.status_code < 300,
                      motivo="pelo bot ou pelo conector do Claude", agrupar_s=600)
    return None if r.status_code < 300 else f"O TermoVision recusou a entrada desta pessoa: {_detalhe(r)}."


def _nome(s: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                            if unicodedata.category(c) != "Mn").split())


def _dona(opcoes: dict, pedida: str | None) -> tuple[dict | None, str | None]:
    empresas = opcoes.get("empresas") or []
    if pedida:
        achadas = [e for e in empresas if _nome(pedida) in _nome(e["nome"])]
        if len(achadas) == 1:
            return achadas[0], None
        return None, (f"Empresa '{pedida}' não é uma das que esta pessoa escolhe: "
                      + ", ".join(e["nome"] for e in empresas) + ". Pergunte qual.")
    if len(empresas) == 1:
        return empresas[0], None
    sugerida = next((e for e in empresas if e["id"] == opcoes.get("dona_sugerida")), None)
    if sugerida:
        return sugerida, None
    return None, "De quem é a usina nova? Pergunte, com as opções: " + ", ".join(e["nome"] for e in empresas) + "."


async def processar_usina(ctx, a: dict) -> dict:
    pasta = (a.get("usina") or "").strip()
    if not pasta:
        return {"erro": "Falta o nome da usina (a pasta no drive de envio). Pergunte."}
    db, user = ctx.db, ctx.user
    async with httpx.AsyncClient(timeout=30) as c:
        erro = await _entrar(c, db, user)
        if erro:
            return {"erro": erro}
        try:
            r = await c.get(f"{_base()}/api/processar/opcoes", params={"pasta": pasta})
        except httpx.HTTPError:
            return {"erro": "O TermoVision não respondeu agora. Nada foi feito."}
    if r.status_code >= 300:
        return {"erro": f"{_detalhe(r)}. Nada foi feito."}
    o = r.json()
    usina, envio = o.get("usina"), o.get("no_envio") or {}
    if (o.get("usinas_com_o_nome") or 0) > 1:
        return {"erro": f"Há {o['usinas_com_o_nome']} usinas com o nome '{pasta}' no TermoVision: diga isso, não escolha."}
    if o.get("processando"):
        nome = (usina or {}).get("nome") or pasta
        link = f" Andamento: {o['status_url']}" if o.get("status_url") else ""
        return {"erro": f"{nome} já está sendo processada: não abri outro.{link}"}
    if not usina and not envio.get("arquivos"):
        return {"erro": f"Não achei a usina nem a pasta '{pasta}' no drive de envio do TermoVision. As fotos vão numa "
                        f"pasta com o nome da usina, no drive de envio da empresa; depois é só pedir de novo."}
    ultimo, refazer = o.get("ultimo") or {}, bool(a.get("refazer"))
    if usina and not envio.get("arquivos") and ultimo.get("estado") == "concluido" and not refazer:
        # 24/11/2026: o "Processar" de uma usina já pronta reabria tudo (horas de PC). Pronta, manda o link;
        # refazer só quando a pessoa pede.
        link = f"{_base()}{ultimo['link_final']}" if ultimo.get("link_final") else ultimo.get("status_url") or ""
        return {"ja_pronta": True, "usina": usina["nome"], "link": link,
                "instrucao": "Diga que já está pronta e mande o link. Só refaça (refazer=true) se a pessoa pedir."}
    dona = None
    if not usina:
        dona, erro = _dona(o, a.get("dona"))
        if erro:
            return {"erro": erro, "empresas": [e["nome"] for e in o.get("empresas") or []]}
    nome = (usina or {}).get("nome") or pasta
    resumo = (f"REFAZER {nome} inteira no TermoVision (leva horas nos PCs)" if refazer else
              f"Processar {nome} no TermoVision" + ("" if usina else f" (usina NOVA, de {dona['nome']})"))
    detalhes = [f"{envio.get('arquivos')} arquivo(s) novos no drive de envio" if envio.get("arquivos") else "Nenhuma foto nova no drive de envio",
                "Organiza as fotos, roda os ortomosaicos e o mapa de temperatura nos PCs (pode levar horas)",
                "Mando o link do andamento agora e aviso a cada etapa"]
    slug, strings, sem = await _strings_do_meuwatt(ctx, nome)
    detalhes.append(f"Leva as {len(strings)} strings do mapa do meuWatt (a lista inteira: as que vieram de lá e "
                    "sumiram saem)" if strings else f"Sem as strings do meuWatt: {sem}")
    corpo = {"pasta": pasta, "avisar_url": get_settings().gs_api_publica.rstrip("/") + AVISO,
             **({"dona": dona["id"]} if dona else {}), **({"refazer": True} if refazer else {})}

    async def executar(db, user, telefone: str) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            erro = await _entrar(c, db, user)
            if erro:
                return f"❌ {erro}"
            try:
                r = await c.post(f"{_base()}/api/processar", json=corpo)
            except httpx.TimeoutException:
                return "⚠️ O TermoVision não respondeu a tempo: o pedido PODE ter entrado. Peça de novo em alguns minutos."
            except httpx.HTTPError:
                return "❌ O TermoVision não respondeu. Nada foi feito."
            if r.status_code == 409:
                return f"⏳ {_detalhe(r)}"
            if r.status_code >= 300:
                return f"❌ {_detalhe(r)}. Nada foi feito."
            d = r.json()
            db.add(ProcessamentoTV(token=d["token"], gs_user_id=user.id, telefone=telefone,
                                   usina=(d.get("usina") or {}).get("nome") or nome))
            db.commit()
            codigo = (d.get("usina") or {}).get("codigo")
            extra = await _mandar_strings(c, codigo, slug, strings) if strings and codigo else ""
        return (f"✅ {(d.get('usina') or {}).get('nome') or nome} entrou para processar. "
                f"Andamento: {d['status_url']}\nAviso aqui a cada etapa." + (f"\n{extra}" if extra else ""))

    return helper.propor(ctx, resumo, PRAZO_S, executar, detalhes, parte=None, confirmacao="sim")


# --------------------------------------------------------------------------- as strings do meuWatt (24/11/2026)
# "Pegar o projeto de strings do meuWatt e alocar no TermoVision" (o dono): quando a usina existe no meuWatt, a string
# oficial é a do mapa de lá. Vai a lista INTEIRA (a que falta é tirada lá), lida com o token do meuWatt DA PESSOA.
async def _strings_do_meuwatt(ctx, nome: str) -> tuple[str | None, list[dict] | None, str | None]:
    """(slug, strings, motivo de não ter). Sem par no meuWatt, sem strings."""
    from app.services import assistente_geracao as ger

    if ctx.mw is None or not ctx.usinas:
        return None, None, "o meuWatt desta pessoa não está ligado ao bot"
    alvo = ger._norm(nome)
    pares = [u for u in ctx.usinas.values() if alvo and (alvo == ger._norm(u["nome"]) or alvo in ger._norm(u["nome"])
                                                         or ger._norm(u["nome"]) in alvo)]
    if len(pares) != 1:
        return None, None, ("a usina não está no meuWatt desta pessoa" if not pares
                            else "mais de uma usina do meuWatt casa com o nome")
    slug = pares[0]["slug"]
    try:
        objetos = (await ctx.mw.mapa(slug)).get("objetos") or []
    except Exception:                                      # noqa: BLE001
        return slug, None, "o mapa do meuWatt não respondeu"
    nomes: dict[int, str] = {}
    try:
        def _vagas(x):
            if isinstance(x, dict):
                if x.get("slot_id") is not None and x.get("label"):
                    nomes[x["slot_id"]] = x["label"]
                for v in x.values():
                    _vagas(v)
            elif isinstance(x, list):
                for v in x:
                    _vagas(v)
        _vagas(await ctx.mw.strings_por_vaga(slug))
    except Exception:                                      # noqa: BLE001 — sem o nome da vaga, vai o número
        pass
    strings = [{"id_meuwatt": o["id"], "nome": o.get("nome") or "", "geometria": o["geometria"],
                "slot_id": o.get("slot_id"), "inversor": nomes.get(o.get("slot_id")), "entrada": o.get("string_number")}
               for o in objetos if o.get("tipo") == "string" and o.get("geometria")]
    return slug, strings, None if strings else "o mapa do meuWatt não tem string desenhada"


async def _mandar_strings(c: httpx.AsyncClient, codigo: str, slug: str, strings: list[dict]) -> str:
    try:
        r = await c.post(f"{_base()}/api/usinas/{codigo}/strings/meuwatt", json={"slug": slug, "strings": strings})
    except httpx.HTTPError:
        return "⚠️ As strings do meuWatt não foram: o TermoVision não respondeu. Peça 'mande as strings' depois."
    if r.status_code == 409:
        return ("ℹ️ As strings do meuWatt vão quando as fotos estiverem organizadas: peça 'mande as strings de "
                "<usina> ao TermoVision' depois da primeira etapa.")
    if r.status_code >= 300:
        return f"⚠️ As strings do meuWatt não foram: {_detalhe(r)}."
    d = r.json()
    aviso = f" Avisos: {'; '.join(d['avisos'][:3])}." if d.get("avisos") else ""
    return (f"🧵 Strings do meuWatt no TermoVision: {d.get('criadas', 0)} novas, {d.get('atualizadas', 0)} atualizadas, "
            f"{d.get('removidas', 0)} tiradas.{aviso}")


FERRAMENTA = {"type": "function", "function": {
    "name": "processar_usina",
    "description": ("PROCESSAR um voo no TermoVision: 'Processar Ibitinga'. Organiza as fotos que estão no drive de "
                    "envio, roda os ortomosaicos (RGB e térmico) e o mapa de temperatura e devolve o link. É AÇÃO: o "
                    "sistema mostra o resumo e a pessoa confirma com Sim. Usina nova: se houver mais de uma empresa, "
                    "a ferramenta pede a dona; pergunte e chame de novo com `dona`."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "o nome como a pessoa disse (a pasta no drive de envio)"},
        "dona": {"type": "string", "description": "a empresa dona da usina NOVA, só quando a ferramenta pedir"},
        "refazer": {"type": "boolean", "description": "true SÓ quando a pessoa pede para refazer/reprocessar uma usina "
                                                     "que já está pronta"}},
        "required": ["usina"]}}}

async def strings_ao_termovision(ctx, a: dict) -> dict:
    pasta = (a.get("usina") or "").strip()
    if not pasta:
        return {"erro": "Falta a usina. Pergunte."}
    async with httpx.AsyncClient(timeout=30) as c:
        erro = await _entrar(c, ctx.db, ctx.user)
        if erro:
            return {"erro": erro}
        try:
            r = await c.get(f"{_base()}/api/processar/opcoes", params={"pasta": pasta})
        except httpx.HTTPError:
            return {"erro": "O TermoVision não respondeu agora. Nada foi feito."}
    usina = r.json().get("usina") if r.status_code < 300 else None
    if not usina:
        return {"erro": f"Não achei a usina '{pasta}' no TermoVision desta pessoa. Nada foi feito."}
    slug, strings, sem = await _strings_do_meuwatt(ctx, usina["nome"])
    if not strings:
        return {"erro": f"Sem strings para mandar: {sem}."}
    resumo = f"Mandar as {len(strings)} strings do mapa do meuWatt para {usina['nome']} no TermoVision"
    detalhes = ["A lista inteira: a string que veio do meuWatt e sumiu de lá sai do TermoVision",
                "As desenhadas no próprio TermoVision ficam"]

    async def executar(db, user, telefone: str) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            erro = await _entrar(c, db, user)
            if erro:
                return f"❌ {erro}"
            return await _mandar_strings(c, usina["codigo"], slug, strings)

    return helper.propor(ctx, resumo, PRAZO_S, executar, detalhes, parte=None, confirmacao="sim")


FERRAMENTA_STRINGS = {"type": "function", "function": {
    "name": "strings_ao_termovision",
    "description": ("MANDA as strings do mapa do meuWatt de uma usina para o TermoVision ('mande as strings de Ouro "
                    "Fino ao TermoVision'). O 'Processar' já as leva; use quando a pessoa pedir só as strings. AÇÃO, "
                    "com o Sim."),
    "parameters": {"type": "object", "properties": {"usina": {"type": "string"}}, "required": ["usina"]}}}

# --------------------------------------------------------------------------- o catálogo do TermoVision (/mcp)
# 24/11/2026, o dono: "o TermoVision publica o /mcp e o GS lê sozinho, como o meuWatt". As LEITURAS entram no
# conector (`api/v1/mcp.py`, serviço termovision) e, por ele, no catálogo do bot; os comandos que mudam algo passam por
# `comando_termovision`, com o Sim onde o TermoVision pede (`_meta.confirmar`, destrutivo ou pesado).
class ClienteMcp:
    """O /mcp do TermoVision como a pessoa: cada chamada abre a sessão dela (asserção de 2 min, uso único)."""

    def __init__(self, db, user):
        self.db, self.user = db, user

    async def mcp(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120) as c:
            erro = await _entrar(c, self.db, self.user)
            if erro:                                       # a recusa de entrar chega como erro do JSON-RPC
                return {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32001, "message": erro}}
            r = await c.post(f"{_base()}/mcp", json=payload)
            r.raise_for_status()
            return r.json()


def so_le(t: dict) -> bool:
    return bool((t.get("annotations") or {}).get("readOnlyHint"))


#: o Processar tem caminho próprio (as strings do meuWatt e o aviso de cada etapa): não vai pelo comando genérico
_PROPRIOS = {"processar"}


async def _lista(c: ClienteMcp) -> list[dict]:
    r = await c.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    if r.get("error"):
        raise RuntimeError(r["error"].get("message") or "o TermoVision recusou")
    return [t for t in ((r.get("result") or {}).get("tools") or []) if isinstance(t, dict) and t.get("name")]


def _texto_do_resultado(res: dict) -> str:
    return "\n".join(x.get("text") or "" for x in res.get("content") or [] if x.get("type") == "text")[:3000]


async def comando_termovision(ctx, a: dict) -> dict:
    cli = ClienteMcp(ctx.db, ctx.user)
    try:
        comandos = [t for t in await _lista(cli) if not so_le(t) and t["name"] not in _PROPRIOS]
    except RuntimeError as e:
        return {"erro": f"{e} Nada foi feito."}
    except httpx.HTTPError:
        return {"erro": "O TermoVision não respondeu agora. Nada foi feito."}
    nome, args = (a.get("nome") or "").strip(), a.get("argumentos") if isinstance(a.get("argumentos"), dict) else {}
    t = next((x for x in comandos if x["name"] == nome), None)
    if t is None:
        return {"comandos": [{"nome": x["name"], "descricao": x.get("description"),
                              "parametros": (x.get("inputSchema") or {}).get("properties")} for x in comandos],
                "instrucao": "Escolha o comando certo e chame de novo com nome e argumentos (o 'processar' é "
                             "processar_usina)."}
    meta, anot = t.get("_meta") or {}, t.get("annotations") or {}

    async def rodar(db, user) -> dict:
        r = await ClienteMcp(db, user).mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                            "params": {"name": nome, "arguments": args}})
        return r.get("result") or {"isError": True, "content": [{"type": "text", "text": str(r.get("error"))}]}

    if not (meta.get("confirmar") or anot.get("destructiveHint") or meta.get("pesado")):
        try:
            res = await rodar(ctx.db, ctx.user)
        except httpx.HTTPError:
            return {"erro": "O TermoVision não respondeu agora."}
        return {"erro" if res.get("isError") else "resultado": _texto_do_resultado(res)}
    alvo = ", ".join(f"{k} {v}" for k, v in args.items())
    resumo = (f"{'APAGAR no' if anot.get('destructiveHint') else 'Rodar no'} TermoVision: {nome}"
              + (f" ({alvo})" if alvo else "") + (" — roda horas num PC" if meta.get("pesado") else ""))

    async def executar(db, user, telefone: str) -> str:
        try:
            res = await rodar(db, user)
        except httpx.TimeoutException:
            return "⚠️ O TermoVision não respondeu a tempo: PODE ter rodado. Confira no TermoVision."
        except httpx.HTTPError:
            return "❌ O TermoVision não respondeu. Nada foi feito."
        return ("❌ " if res.get("isError") else "✅ ") + _texto_do_resultado(res)

    return helper.propor(ctx, resumo, PRAZO_S, executar, [t.get("description") or ""], parte=None, confirmacao="sim")


FERRAMENTA_COMANDO = {"type": "function", "function": {
    "name": "comando_termovision",
    "description": ("COMANDOS do TermoVision que MUDAM algo: gerar zonas, o motor de mesas (ex.: 'processar mesas 1V e "
                    "criar zona' = mesas_motor com profundidade 1), apagar zonas automáticas ou propostas, link "
                    "público, cancelar um processamento, contar mesas. Sem `nome`, devolve a lista de comandos com os "
                    "parâmetros. O que pede confirmação vira ação com o Sim. Consultas (estado, andamento) estão no "
                    "catálogo (procurar_consulta); 'Processar <usina>' é processar_usina."),
    "parameters": {"type": "object", "properties": {
        "nome": {"type": "string", "description": "o comando, como a lista devolve"},
        "argumentos": {"type": "object", "description": "os parâmetros do comando (ex.: usina, profundidade)"}}}}}

FERRAMENTAS = {"processar_usina": (processar_usina, FERRAMENTA),
               "strings_ao_termovision": (strings_ao_termovision, FERRAMENTA_STRINGS),
               "comando_termovision": (comando_termovision, FERRAMENTA_COMANDO)}


def permitidas(user) -> list[str]:
    return list(FERRAMENTAS) if disponivel(user) else []


# --------------------------------------------------------------------------- o aviso de cada etapa
def mensagem(p: dict) -> tuple[str, str]:
    """(a chave do momento, a frase). A mesma chave de antes não vira mensagem nova."""
    usina, estado = p.get("usina") or "a usina", p.get("estado")
    if estado == "concluido":
        return "concluido", f"✅ {usina} pronta: {_base()}{p.get('link_final') or ''}"
    if estado == "erro":
        e = next((x for x in p.get("etapas") or [] if x.get("estado") == "erro"), {})
        onde = f" em {e['titulo']}" if e.get("titulo") else ""
        return "erro", f"❌ O processamento de {usina} parou{onde}: {p.get('erro') or e.get('erro') or 'sem motivo dito'}"
    if estado == "cancelado":
        return "cancelado", f"⏹️ O processamento de {usina} foi cancelado."
    etapas = p.get("etapas") or []
    i, e = next(((i, x) for i, x in enumerate(etapas) if x.get("estado") == "rodando"), (None, None))
    if e is None:
        return f"{estado}", ""
    texto = f" ({e['texto']})" if e.get("texto") else ""
    return f"rodando:{i}", f"🛠️ {usina}: {e['titulo']}, etapa {i + 1} de {len(etapas)}{texto}"


async def provisionar(db, user, liberado: bool) -> str | None:
    """Liga (cria ou acha) ou desliga a conta da pessoa no TermoVision. Devolve o erro, ou None. Nunca levanta: quem
    chama já gravou a mudança no GS, e a tela do gerente não pode virar erro por causa do outro lado."""
    from app.services import acessos

    if user.perfil not in _PORTAO:
        return None                                        # a plataforma nunca nasce lá
    erro = None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{_base()}/api/conta/gs/provisionar", json={"assercao": assercao(db, user, liberado)})
        if r.status_code >= 300:
            erro = _detalhe(r)
        else:
            log.info("termovision: provisionar %s → %s", user.apelido, r.json().get("acao"))
    except Exception as e:                                 # noqa: BLE001
        log.warning("termovision: provisionar %s falhou", user.apelido, exc_info=True)
        erro = "o TermoVision não respondeu" if isinstance(e, httpx.HTTPError) else f"falha aqui: {type(e).__name__}"
    acessos.registrar(db, None, acao="acesso", sistema="termovision", user=user, ok=erro is None,
                      motivo=f"acesso {'ligado' if liberado else 'desligado'} no GS" + (f"; lá: {erro}" if erro else ""))
    return erro
