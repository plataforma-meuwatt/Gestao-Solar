"""RELATÓRIO DA OS pelo bot (pedido do Renan, 04/11/2026: "quero que o bot gere o relatório da OS e envie o PDF" —
"tem duas opções: gerar na hora e enviar; e, se tiver, enviar o relatório salvo. Se não tiver, ele gera e envia; se
tiver, ele pede o que quer").

Tudo no meuPlano, com o token DA PESSOA (a régua de lá diz se ela vê a OS e se pode gerar). O SALVO é a aba
Relatórios da OS de lá (o PDF exportado de um rascunho Word). O NOVO é o "Novo relatório com IA" de lá: a IA lê a OS,
as tarefas, as fichas e as fotos e monta o Word, e o PDF dele sai do WordCraft do servidor de lá — o mesmo motor do
editor, nunca LibreOffice. O novo fica salvo na OS (o rascunho Word e o PDF na aba Relatórios). O arquivo vai como
DOCUMENTO no WhatsApp; os bytes não passam pela IA.

O PROMPT e as IMAGENS DE APOIO (dono, 04/11/2026: "gere o relatório da OS com o prompt xxx, segue imagens de apoio"):
o prompt vai em `instrucao` e fica salvo na OS, na conversa do relatório com IA (a mesma do site); as fotos que a
pessoa mandou por aqui entram nas INFORMAÇÕES DO RELATÓRIO da OS (no meuPlano, "fatos") antes de gerar — a IA de lá as
analisa — e saem da espera (não vão também para a ficha de uma tarefa). Com fotos, é ação: espera o Sim (05/11/2026).

E sem gerar (dono, 05/11/2026: "quero que o bot receba imagens e texto para anexar nas informações do relatório de uma
OS"): `informacoes_do_relatorio` registra o texto e/ou as fotos na OS, confirmado com o Sim (como a foto na ficha).
"""

import asyncio
import re
from types import SimpleNamespace
from time import monotonic

import httpx

from app.core.datas import hora_brt
from app.services import assistente_fotos as fotos

#: a IA de lá leva de 30 s a 2 min para montar o relatório, e o 1º link da Central gera os PDFs da OS e das tarefas
#: antes: 6 min (o turno inteiro segue com o "digitando…"); passou disso, o bot diz para conferir a aba Relatórios
PRAZO_GERAR_S = 360
ESPERA_S = 3

FERRAMENTA = {"type": "function", "function": {
    "name": "relatorio_da_os",
    "description": ("O RELATÓRIO de uma OS (ordem de serviço) do meuPlano como ARQUIVO PDF aqui no chat — o relatório "
                    "escrito do serviço, para o cliente. Não é o PDF da OS (o documento da ordem com as tarefas, que é "
                    "`manutencao`) nem relatório de geração do monitoramento. escolha=auto quando a pessoa só "
                    "pediu o relatório: se a OS já tem relatório salvo, a resposta traz a lista e você PERGUNTA se ela "
                    "quer o salvo (diga o título e a data) ou um novo — não mande nem gere antes da resposta; sem "
                    "salvo, o novo é gerado e enviado na hora. escolha=salvo manda o salvo (relatorio_id da lista, ou "
                    "o mais recente). escolha=word manda em PDF o Word (rascunho) mais recente da OS como ele está "
                    "AGORA, com as alterações e as edições feitas à mão: use quando a pessoa pede o PDF do relatório "
                    "que está sendo ajustado ('manda o PDF'). escolha=novo gera AGORA com IA e manda (leva até 2 "
                    "minutos): use quando a pessoa "
                    "pediu um novo ('gera outro', 'refaz'), respondeu que quer o novo, ou mandou COMO quer o relatório "
                    "(o prompt) ou imagens de apoio. O prompt dela (para quem, foco, tamanho — 'com o prompt …') vai em "
                    "`instrucao`, inteiro, e fica salvo na OS; sem ele, vale o que já estiver salvo lá ou o padrão. "
                    "Fotos que ela mandou para o relatório (a mensagem aparece como «[📷 N foto(s) recebida(s)…]»): "
                    "fotos_de_apoio=true — entram nas informações do relatório da OS e a IA as analisa; com fotos, "
                    "vira uma ação que a pessoa confirma no botão Sim (as fotos sobem e o relatório é gerado depois "
                    "dele). Não é `anexar_fotos`, que é a ficha de uma tarefa. Só registrar informação, sem gerar, é "
                    "`informacoes_do_relatorio`. link_publico=true quando a pessoa pede o LINK (público, para o cliente, "
                    "sem login) em vez do arquivo: vale com qualquer escolha, e o sistema põe o link embaixo."),
    "parameters": {"type": "object", "properties": {
        "os": {"type": "integer", "description": "o número da OS"},
        "escolha": {"type": "string", "enum": ["auto", "salvo", "word", "novo"]},
        "relatorio_id": {"type": "integer", "description": "qual relatório salvo (o id da lista); vazio = o mais recente"},
        "instrucao": {"type": "string", "description": "como a pessoa quer o relatório NOVO (o prompt dela, inteiro); vazio = o salvo ou o padrão"},
        "fotos_de_apoio": {"type": "boolean", "description": "as fotos que ela mandou por aqui vão às informações do relatório da OS antes de gerar"},
        "link_publico": {"type": "boolean", "description": "manda o link público do relatório (abre sem login) em vez do PDF"}},
        "required": ["os"]}}}


def _de(iso: object) -> str:
    """A data de lá (UTC sem fuso) em hora de Brasília."""
    if isinstance(iso, str) and iso and not re.search(r"(Z|[+-]\d\d:\d\d)$", iso):
        iso += "+00:00"
    return hora_brt(iso)


def _nome_do_arquivo(titulo: str) -> str:
    return (re.sub(r'[\\/:*?"<>|\s]+', " ", titulo or "Relatório").strip()[:120] or "Relatório") + ".pdf"


def _motivo(e: httpx.HTTPStatusError, os_id: int, acao: str, nada_feito: bool = True) -> str:
    from app.services.integracoes import detalhe_do_upstream
    st = e.response.status_code
    if st == 404:
        return f"A OS #{os_id} não existe no meuPlano ou não está no alcance desta pessoa."
    if st == 403:
        return f"O papel desta pessoa no meuPlano não {acao}{'. Nada foi feito' if nada_feito else ''}: o gestor da O&M pode liberar."
    return f"O meuPlano recusou ({st}): {detalhe_do_upstream(e.response) or 'sem detalhe'}."


async def _mandar(ctx, raw: bytes, titulo: str) -> dict:
    from app.clients import whatsapp
    nome = _nome_do_arquivo(titulo)
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="document", arquivo=raw, filename=nome,
                                       mime="application/pdf", texto=titulo)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(nome)
    return {"arquivo": nome, "enviado_no_chat": ok, "erro": None if ok else (r or {}).get("erro") or "o WhatsApp recusou"}


SEM_TEMPLATE = ("não mandei: ele foi feito sem o template da empresa (o Modelo dos documentos do meuPlano), e relatório "
                "sem template nunca é enviado")


async def _entregar(ctx, mp, r: dict, publico: bool) -> dict:
    """O relatório `r` (da lista de lá) no chat: o PDF, ou (`publico`) o link que abre sem login, para o cliente — o
    sistema o põe ao pé da resposta (dono, 07/11/2026: "quero opção de enviar o relatório com link público"). Nunca
    o que nasceu sem o template (dono, 07/11/2026: "nunca enviar sem template"; quem decide é o meuPlano)."""
    if not r.get("com_modelo"):
        return {"erro": f"O relatório «{r.get('titulo')}»: {SEM_TEMPLATE}."}
    if publico:
        link = (await mp.link_publico_relatorio(int(r["id"])))["url"]
        ctx.rodape.append(f"🔗 Link público: {link}")
        return {"link_publico": "vai embaixo, pelo sistema (abre sem login; pedir de novo atualiza o PDF no mesmo link)"}
    return await _mandar(ctx, await mp.relatorio_pdf(r["id"]), r.get("titulo") or f"Relatório da OS #{r.get('dono_id')}")


async def _esperar(mp, job: str, prazo_s: int | None = None) -> dict:
    """O trabalho da IA de lá (gerar ou alterar) até o fim: o estado final, ou RuntimeError com o motivo."""
    prazo_s = PRAZO_GERAR_S if prazo_s is None else prazo_s
    fim = monotonic() + prazo_s
    while True:
        await asyncio.sleep(ESPERA_S)
        e = await mp.relatorio_ia_estado(job)
        if e.get("status") == "pronto":
            return e
        if e.get("status") == "erro":
            raise RuntimeError(e.get("erro") or "a IA de lá não conseguiu terminar")
        if monotonic() > fim:
            raise RuntimeError(f"passou de {prazo_s // 60} minutos e não ficou pronto (etapa: {e.get('etapa') or '—'})")


async def _gerar(mp, os_id: int, instrucao: str) -> dict:
    """O "Novo relatório com IA" de lá até o fim, e o PDF dele pelo WordCraft de lá."""
    e = await _esperar(mp, await mp.relatorio_ia(os_id, instrucao))
    if not e.get("doc_id"):
        raise RuntimeError("a IA de lá terminou sem o documento")
    return await mp.publicar_relatorio(int(e["doc_id"]))


async def _word_mais_recente(mp, os_id: int) -> dict | None:
    """O rascunho Word mais recente da OS (o que está sendo ajustado) feito com o template da empresa, ou None: o Word
    antigo, de antes do template, nunca é o escolhido (o PDF dele saiu para o dono em 07/11/2026)."""
    docs = [d for d in await mp.documentos_word_da_os(os_id)
            if (d.get("formato") or "docx") == "docx" and d.get("com_modelo")]
    return max(docs, key=lambda d: d.get("updated_at") or "", default=None)


async def _subir_fotos(mp, os_id: int, telefone: str, lista: list[dict]) -> tuple[int, list[str]]:
    """As fotos do WhatsApp nas INFORMAÇÕES DO RELATÓRIO da OS (a legenda vira o texto); a que entrou sai da espera."""
    from app.clients import whatsapp
    from app.services.integracoes import detalhe_do_upstream
    feitas, falhas = 0, []
    for i, f in enumerate(lista, 1):
        # o porquê na língua de quem lê, como no `anexar_fotos`; e a que pode ter entrado é dita (senão ela manda de
        # novo e a foto fica duas vezes)
        try:
            conteudo, tipo = await whatsapp.baixar_midia(f["id"])
            await mp.criar_fato_arquivo(os_id, f"whatsapp-{i}.{(tipo or 'image/jpeg').split('/')[-1].split(';')[0]}",
                                        conteudo, tipo, f["legenda"] or "Imagem enviada pelo WhatsApp")
        except whatsapp.GatewayIndisponivel:
            falhas.append(f"foto {i}: não consegui baixar do WhatsApp")
            continue
        except httpx.HTTPStatusError as e:
            motivo = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
            falhas.append(f"foto {i}: o meuPlano recusou ({motivo})")
            continue
        except httpx.HTTPError:
            falhas.append(f"foto {i}: o meuPlano não respondeu a tempo (pode ter entrado: confira)")
            continue
        except Exception:  # noqa: BLE001 — uma foto que não sobe não derruba as outras; vai dita
            falhas.append(f"foto {i}: não entrou (erro inesperado)")
            continue
        feitas += 1
        fotos._tirar(telefone, f["id"])
    return feitas, falhas


def _propor_com_fotos(ctx, os_id: int, instrucao: str, lista: list[dict]) -> dict:
    """As fotos de apoio entram na OS — é ação no meuPlano: confirma com o Sim, e só então sobem e o relatório é gerado
    com elas (revisão adversarial, 05/11/2026: subiam sem pergunta, todas as dos últimos 30 min, para a OS que o modelo
    escolheu; e o erro ao gerar dizia "nada foi feito" com elas já lá)."""
    from app.services import assistente_helper as helper
    from app.services.vinculos import SemConexao, cliente_meuplano
    resumo = (f"Registrar {len(lista)} foto(s) nas Informações do relatório da OS #{os_id} e gerar um relatório novo "
              "com elas" + (f", com o pedido «{instrucao[:120]}{'…' if len(instrucao) > 120 else ''}»" if instrucao else ""))

    async def executar(db, user, telefone: str) -> str:
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        feitas, falhas = await _subir_fotos(mp, os_id, telefone, lista)
        motivos = "".join(f"\n• {m}" for m in falhas)
        if not feitas:          # sem as evidências o relatório sairia sem o que ela pediu: não gera
            return f"❌ Nenhuma foto entrou nas Informações do relatório da OS #{os_id}, e o relatório não foi gerado:{motivos}"
        entrou = f"{feitas} foto(s) entraram nas Informações do relatório da OS #{os_id}"
        try:
            r = await _gerar(mp, os_id, instrucao)
            raw = await mp.relatorio_pdf(r["id"])
        except httpx.HTTPStatusError as e:
            return (f"⚠️ {entrou}, mas o relatório não foi gerado. "
                    f"{_motivo(e, os_id, 'gera relatório de OS (precisa poder editar a OS)', nada_feito=False)}{motivos}")
        except httpx.HTTPError:
            return (f"⚠️ {entrou}. O meuPlano não respondeu enquanto o relatório era gerado: confira a aba Relatórios da "
                    f"OS antes de pedir de novo — ele pode ter ficado pronto lá.{motivos}")
        except RuntimeError as e:
            return f"⚠️ {entrou}, mas não consegui gerar o relatório: {e}.{motivos}"
        titulo = r.get("titulo") or f"Relatório da OS #{os_id}"
        if not r.get("com_modelo"):
            return f"⚠️ {entrou} e o relatório «{titulo}» foi gerado, mas {SEM_TEMPLATE}.{motivos}"
        env = await _mandar(SimpleNamespace(telefone=telefone, enviados=[]), raw, titulo)
        fim = "" if env["enviado_no_chat"] else f" Não consegui mandar o PDF aqui ({env['erro']}): ele está na aba Relatórios da OS."
        sinal = "✅" if env["enviado_no_chat"] and not falhas else "⚠️"
        return (f"{sinal} {entrou} e o relatório «{titulo}» foi gerado com elas (o Word e o PDF ficaram na aba "
                f"Relatórios da OS).{fim}{motivos}")

    return helper.propor(ctx, resumo, PRAZO_INFO_S, executar, [], parte="bot_meuplano", confirmacao="sim")


async def relatorio_da_os(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        os_id = int(a.get("os"))
    except (TypeError, ValueError):
        return {"erro": "Falta o número da OS: pergunte qual é."}
    escolha = (a.get("escolha") or "auto").lower()
    if escolha == "auto" and ((a.get("instrucao") or "").strip() or a.get("fotos_de_apoio")):
        escolha = "novo"            # mandou o prompt ou imagens de apoio: é um relatório novo, não o salvo
    publico = bool(a.get("link_publico"))
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão: gerar leva até 2 min
    try:
        salvos = [r for r in await mp.relatorios_da_os(os_id) if r.get("com_modelo")]   # sem template: nunca
    except httpx.HTTPStatusError as e:
        return {"erro": _motivo(e, os_id, "lê relatório de OS")}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi enviado."}

    if escolha == "word":
        try:
            doc = await _word_mais_recente(mp, os_id)
            if doc is None:
                return {"erro": f"A OS #{os_id} não tem relatório em Word feito com o template da empresa. Ofereça "
                                "gerar um novo agora (sai com o template)."}
            r = await mp.publicar_relatorio(int(doc["id"]))
            entrega = await _entregar(ctx, mp, r, publico)
        except httpx.HTTPStatusError as e:
            return {"erro": _motivo(e, os_id, "exporta e compartilha o relatório da OS (precisa poder editar a OS)")}
        except httpx.HTTPError:
            return {"erro": "O meuPlano não respondeu enquanto o PDF era feito. Nada foi enviado."}
        return {"os": os_id, "relatorio": "o Word atual em PDF", "titulo": r.get("titulo"),
                "versao_do_word": doc.get("versao_atual"), **entrega}
    if escolha != "novo" and salvos:
        if escolha == "auto":
            return {"os": os_id, "relatorios_salvos": [
                        {"id": r["id"], "titulo": r.get("titulo"), "de": _de(r.get("atualizado_em") or r.get("created_at")),
                         "por": r.get("criado_por")} for r in salvos],
                    "nota": ("A OS já tem relatório salvo. PERGUNTE à pessoa se ela quer o salvo (diga o título e a "
                             "data) ou um novo gerado agora. Não mande nem gere nada antes da resposta.")}
        pedido = str(a.get("relatorio_id") or "")
        r = next((x for x in salvos if pedido.isdigit() and x["id"] == int(pedido)), salvos[0])
        try:
            entrega = await _entregar(ctx, mp, r, publico)
        except httpx.HTTPStatusError as e:
            return {"erro": _motivo(e, os_id, "compartilha o relatório da OS")}
        except httpx.HTTPError:
            return {"erro": "Não consegui baixar o relatório salvo no meuPlano agora. Nada foi enviado."}
        return {"os": os_id, "relatorio": "salvo", "titulo": r.get("titulo"),
                "de": _de(r.get("atualizado_em") or r.get("created_at")), **entrega}
    if escolha == "salvo":
        return {"erro": f"A OS #{os_id} não tem relatório salvo feito com o template da empresa. Ofereça gerar um novo "
                        "agora."}

    instrucao = (a.get("instrucao") or "").strip()[:MAX_INSTRUCAO]
    lista = fotos.recebidas(ctx.telefone, sem_video=True) if a.get("fotos_de_apoio") else []
    if lista:
        return _propor_com_fotos(ctx, os_id, instrucao, lista)
    apoio = {"fotos_de_apoio": 0, "nota_fotos": "Não havia foto recebida (cada uma fica guardada 30 min)."} \
        if a.get("fotos_de_apoio") else {}
    try:
        rel = await _gerar(mp, os_id, instrucao)
        entrega = await _entregar(ctx, mp, rel, publico)
    except httpx.HTTPStatusError as e:
        return {"erro": _motivo(e, os_id, "gera relatório de OS (precisa poder editar a OS)")}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu enquanto o relatório era gerado. Confira a aba Relatórios da OS "
                        "antes de pedir de novo: ele pode ter ficado pronto lá."}
    except RuntimeError as e:
        return {"erro": f"Não consegui gerar o relatório: {e}."}
    return {"os": os_id, "relatorio": "novo", "titulo": rel.get("titulo"), **apoio,
            "salvo_na_os": "o rascunho Word e o PDF ficaram na aba Relatórios da OS; o prompt, na conversa do relatório",
            **entrega}


# --------------------------------------------------------------------------- usina SEM CADASTRO e o ajuste do Word
# Dono, 07/11/2026: "tem usinas que não têm cadastro e eu faço serviço. Quero enviar um link público de drive, e você
# analisa as fotos, salva elas… eu mando a msg pro bot: quero um relatório de usina sem cadastro, aí eu envio as fotos,
# e preciso enviar o contexto, senão tiver no drive ele pede, e aí você gera um Word público, com as fotos que julgar
# ok, link com todas as fotos, usa o contexto. Se eu não gostar eu comento e você altera até convergir, aí eu falo manda
# o PDF e você manda. Eu posso também editar o Word, salvar, pedir alteração, você altera e respeita o que editei."
# Escolhas dele: a usina "Usinas sem cadastro" do meuPlano guarda cada serviço (um item em Serviços Adicionais e a OS
# dele); o Word é o Word meuPlano (o link abre no editor do site, com o login dele).

PRAZO_DRIVE_S = 900         # baixar as fotos, a IA olhar cada uma e escrever: de 5 a 10 min numa pasta de 60 fotos
USINA_GUARDA = "sem cadastro"
_DRIVE = re.compile(r"https?://drive\.google\.com/(?:drive/(?:u/\d+/)?folders/|open\?id=)([\w-]{10,})")

FERRAMENTA_SEM_CADASTRO = {"type": "function", "function": {
    "name": "relatorio_sem_cadastro",
    "description": ("RELATÓRIO de um serviço numa usina SEM CADASTRO no meuPlano, a partir de uma PASTA do Google Drive "
                    "com as fotos (link drive.google.com/drive/folders/…). O sistema cria o serviço e a OS na usina "
                    "«Usinas sem cadastro», traz as fotos (a IA olha cada uma) e os documentos da pasta e escreve o "
                    "Word; a pessoa confirma com o Sim e recebe o LINK do Word para revisar. Passe o CONTEXTO que a "
                    "pessoa escreveu (onde foi, o que se fez, o que se achou), inteiro; sem contexto, o sistema diz se "
                    "a pasta traz documento que o substitua, senão você pergunta. Não use para usina que tem cadastro "
                    "(essa é `relatorio_da_os`, na OS dela)."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "o nome da usina do serviço, como a pessoa disse (vazio: o nome da pasta)"},
        "servico": {"type": "string", "description": "o serviço em poucas palavras, para o nome da OS (ex.: 'ensaio do trafo e da proteção do SKID 3')"},
        "contexto": {"type": "string", "description": "o contexto que a pessoa escreveu, inteiro (vazio se ela não escreveu)"},
        "instrucao": {"type": "string", "description": "como ela quer o relatório (para quem, foco, tamanho), se disse"},
        "link": {"type": "string", "description": "o link da pasta do Drive que a pessoa mandou"},
        "nova": {"type": "boolean", "description": ("true só quando a pessoa disse que quer OUTRA OS, depois de saber "
                                                    "que já existe OS desta pasta")}},
        "required": []}}}

FERRAMENTA_LISTA = {"type": "function", "function": {
    "name": "os_sem_cadastro",
    "description": ("LISTA as OS da usina «Usinas sem cadastro» do meuPlano (um serviço em usina sem cadastro por OS, "
                    "como os relatórios feitos de uma pasta do Drive): número, nome, situação, data e se veio de uma "
                    "pasta. Use quando a pessoa pede a lista, e SEMPRE antes de dizer que uma OS ou um relatório de "
                    "usina sem cadastro existe (ou não existe): vale o meuPlano de agora, nunca a memória da conversa "
                    "(alguém pode ter apagado ou criado)."),
    "parameters": {"type": "object", "properties": {
        "busca": {"type": "string", "description": "parte do nome da OS (a usina do serviço) para filtrar; vazio = todas"}},
        "required": []}}}
MAX_LISTA = 30


async def _da_usina_guarda(mp) -> tuple[dict | None, list[dict]]:
    """A usina «Usinas sem cadastro» e as OS dela, lidas agora no meuPlano com o token da pessoa."""
    from app.services.assistente_local import escolher
    guarda, _ = escolher(await mp.usinas(), USINA_GUARDA)
    return (guarda, await mp.ordens_servico(int(guarda["id"]))) if guarda else (None, [])


def _linha_os(o: dict) -> dict:
    return {"os": o.get("id"), "nome": o.get("name"), "situacao": o.get("status"), "criada_em": _de(o.get("created_at")),
            "da_pasta_do_drive": bool(_DRIVE.search(o.get("notes") or ""))}


async def os_sem_cadastro(ctx, a: dict) -> dict:
    """Dono, 07/11/2026: "preciso de uma forma de listar as OS sem usina para não ter esse rolo" — o bot disse, de
    memória, que a OS 1996 existia, e ela tinha sido apagada."""
    from app.services.assistente_local import _sem_acento
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        guarda, ordens = await _da_usina_guarda(mp)
    except httpx.HTTPStatusError as e:
        return {"erro": detalhe_do_upstream(e.response) or f"O meuPlano recusou ({e.response.status_code})."}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora."}
    if guarda is None:
        return {"erro": "Não achei a usina «Usinas sem cadastro» no meuPlano desta pessoa."}
    busca = _sem_acento((a.get("busca") or "").strip())
    lista = [_linha_os(o) for o in sorted(ordens, key=lambda o: o.get("id") or 0, reverse=True)
             if busca in _sem_acento(o.get("name") or "")]
    return {"usina": guarda.get("name"), "total": len(lista), "os": lista[:MAX_LISTA],
            **({"mais": len(lista) - MAX_LISTA} if len(lista) > MAX_LISTA else {})}

FERRAMENTA_ALTERAR = {"type": "function", "function": {
    "name": "alterar_relatorio",
    "description": ("ALTERA o relatório em Word de uma OS (o rascunho mais recente, como está agora, com as edições que "
                    "a pessoa fez à mão no editor) pelo pedido dela: tirar ou pôr foto, reescrever um trecho, mudar a "
                    "conclusão, pôr um quadro de valores. A IA do meuPlano muda só o que foi pedido e o resto fica. Use "
                    "para todo comentário sobre o relatório que está sendo revisado ('tira a foto do marimbondo', 'a "
                    "conclusão está fraca'). O PDF é `relatorio_da_os` escolha=word."),
    "parameters": {"type": "object", "properties": {
        "os": {"type": "integer", "description": "o número da OS do relatório"},
        "pedido": {"type": "string", "description": "o que a pessoa pediu para mudar, inteiro, nas palavras dela"}},
        "required": ["os", "pedido"]}}}


def _link_do_drive(ctx, sugerido: str | None) -> str | None:
    """A pasta que a PESSOA mandou (esta mensagem, depois as de antes), nunca uma que a IA escreveu: o id é longo e uma
    letra trocada abriria outra pasta. A sugerida pela IA só escolhe entre as que a pessoa mandou."""
    textos = [ctx.pedido or ""] + [str(m.get("content") or "") for m in reversed(ctx.historico or [])
                                   if m.get("role") == "user"]
    ids = [m.group(1) for t in textos for m in _DRIVE.finditer(t)]
    m = _DRIVE.search(sugerido or "")
    escolhido = m.group(1) if m and m.group(1) in ids else (ids[0] if ids else None)
    return f"https://drive.google.com/drive/folders/{escolhido}" if escolhido else None


async def relatorio_sem_cadastro(ctx, a: dict) -> dict:
    from app.services import assistente_helper as helper
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuplano
    link = _link_do_drive(ctx, a.get("link"))
    if not link:
        return {"erro": "Falta o link da PASTA do Google Drive com as fotos (drive.google.com/drive/folders/…): peça."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()
    try:
        previa = await mp.drive_previa(link)
        guarda, ordens = await _da_usina_guarda(mp)
    except httpx.HTTPStatusError as e:
        return {"erro": f"{detalhe_do_upstream(e.response) or f'O meuPlano recusou ({e.response.status_code})'}. Nada foi feito."}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi feito."}
    docs = previa.get("documentos") or []
    if not previa.get("fotos") and not docs:
        return {"erro": f"A pasta «{previa.get('pasta')}» não tem foto nem documento que eu leia. Nada foi feito."}
    contexto = (a.get("contexto") or "").strip()[:MAX_INSTRUCAO]
    if not contexto and not docs:
        return {"erro": ("Falta o CONTEXTO do serviço e a pasta não tem documento que o traga. Pergunte à pessoa, numa "
                         "mensagem só: onde foi (a usina e o cliente), o que foi feito e o que se encontrou. Não gere "
                         "sem ele.")}
    if guarda is None:
        return {"erro": ("Não achei a usina «Usinas sem cadastro» no meuPlano desta pessoa: o gerente da O&M a cria uma "
                         "vez (ou a libera para ela). Nada foi feito.")}
    # a OS que JÁ É desta pasta, lida agora no meuPlano (o link dela fica nas notas da OS): quem diz que existe é o
    # sistema, não a memória da conversa (07/11/2026: o bot ofereceu a OS 1996, que tinha sido apagada)
    pasta = _DRIVE.search(link).group(1)
    iguais = [_linha_os(o) for o in ordens if pasta in (o.get("notes") or "")]
    if iguais and not a.get("nova"):
        return {"ja_existe": iguais, "instrucao": (
            "O meuPlano JÁ TEM OS desta pasta (acima). Diga qual (número, nome e situação) e pergunte numa linha: gerar "
            "o relatório de novo nela (`relatorio_da_os` escolha=novo, com o número dela) ou criar outra OS (chame "
            "esta ferramenta de novo com nova=true). Nada foi feito.")}
    usina = (a.get("usina") or "").strip() or str(previa.get("pasta") or "").replace("_", " ").strip()
    if not usina:
        return {"erro": "Falta o nome da usina do serviço: pergunte."}
    nome = f"{usina}: {(a.get('servico') or '').strip() or 'serviço em campo'}"[:200]
    instrucao = (a.get("instrucao") or "").strip()[:MAX_INSTRUCAO]
    extra = (f" e {len(docs)} documento(s)" if docs else "") + \
        (f"; {previa['videos']} vídeo(s) ficam só no link da pasta" if previa.get("videos") else "")
    resumo = (f"Criar na usina «{guarda['name']}» do meuPlano o serviço e a OS «{nome}», trazer da pasta "
              f"«{previa.get('pasta')}» {previa.get('fotos') or 0} foto(s){extra} e escrever o relatório com IA "
              "(de 5 a 10 minutos)")

    async def executar(db, user, telefone: str) -> str:
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        try:
            funil = await mp.funil_de_servicos_adicionais()
            card = await mp.criar_container(int(funil["id"]), {
                "title": nome, "usina_id": guarda["id"], "kind": "servico_adicional",
                "description": contexto or None, "created_by": user.nome})
        except httpx.HTTPStatusError as e:
            return (f"❌ O meuPlano recusou criar o serviço ({e.response.status_code}): "
                    f"{detalhe_do_upstream(e.response) or 'sem detalhe'}. Nada foi feito.")
        except httpx.HTTPError:
            return ("⚠️ O meuPlano não respondeu ao criar o serviço: confira em Serviços Adicionais antes de pedir de "
                    "novo (ele pode ter sido criado).")
        notas = "\n\n".join(x for x in (contexto, f"Fotos e vídeos do serviço (Google Drive): {link}") if x)
        try:
            os_id = int((await mp.criar_os({"plant_id": guarda["id"], "container_id": card["id"], "name": nome,
                                             "notes": notas}))["id"])
        except httpx.HTTPError as e:
            motivo = detalhe_do_upstream(e.response) if isinstance(e, httpx.HTTPStatusError) else "não respondeu"
            return (f"⚠️ O serviço «{nome}» foi criado em Serviços Adicionais, mas a OS não ({motivo}). Crie a OS nele "
                    "e peça o relatório de novo.")
        try:
            e = await _esperar(mp, await mp.relatorio_ia(os_id, instrucao, drive=link), PRAZO_DRIVE_S)
        except (httpx.HTTPError, RuntimeError) as e:
            motivo = (detalhe_do_upstream(e.response) if isinstance(e, httpx.HTTPStatusError)
                      else str(e) if isinstance(e, RuntimeError) else "o meuPlano não respondeu")
            return (f"⚠️ A OS #{os_id} «{nome}» foi criada, mas o relatório não ficou pronto: {motivo}. As fotos que "
                    f"já vieram ficam na OS; peça «gera o relatório da OS {os_id}» para tentar de novo.")
        return (f"✅ Relatório pronto, na OS #{os_id} «{nome}»: {e.get('link')}\n"
                "As fotos da pasta ficaram nos anexos da OS, com a legenda da IA. Diga o que mudar (ou mude no Word e "
                "salve). Quando estiver bom, peça o PDF ou o link público para o cliente.")

    return helper.propor(ctx, resumo, PRAZO_INFO_S, executar, [], parte="bot_meuplano", confirmacao="sim")


async def alterar_relatorio(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        os_id = int(a.get("os"))
    except (TypeError, ValueError):
        return {"erro": "Falta o número da OS do relatório: pergunte qual é."}
    pedido = (a.get("pedido") or "").strip()[:4000]
    if not pedido:
        return {"erro": "Falta o que mudar: pergunte."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão: a IA de lá leva até 2 min
    try:
        doc = await _word_mais_recente(mp, os_id)
        if doc is None:
            return {"erro": f"A OS #{os_id} não tem relatório em Word para alterar. Ofereça gerar um novo."}
        e = await _esperar(mp, await mp.alterar_relatorio(int(doc["id"]), pedido))
    except httpx.HTTPStatusError as e:
        return {"erro": _motivo(e, os_id, "altera relatório de OS (precisa poder editar a OS)")}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu enquanto o relatório era alterado: confira o Word antes de pedir de novo."}
    except RuntimeError as e:
        return {"erro": f"Não consegui alterar: {e}."}
    ctx.rodape.append(f"📝 Word: {e.get('link') or ''}".strip())
    return {"os": os_id, "o_que_mudou": e.get("resposta"),
            "nota": "Diga em UMA linha o que mudou (o_que_mudou); o sistema põe o link do Word embaixo."}


# --------------------------------------------------------------------------- informações do relatório, sem gerar
FERRAMENTA_INFO = {"type": "function", "function": {
    "name": "informacoes_do_relatorio",
    "description": ("Registra nas INFORMAÇÕES DO RELATÓRIO de uma OS do meuPlano (o que serve de evidência para o "
                    "relatório: o print da oscilografia, a foto do dano, uma observação, um valor medido) o TEXTO que a "
                    "pessoa mandou e/ou as FOTOS que ela mandou por aqui (a mensagem aparece como «[📷 N foto(s) "
                    "recebida(s)…]»). Vira uma ação que ela confirma no botão Sim. Não gera o relatório (isso é "
                    "`relatorio_da_os`) nem é a ficha de uma tarefa (`anexar_fotos`). Sem o NÚMERO da OS (ela disse a "
                    "usina e o assunto — 'a OS do arco de Pereiras'): ache-o com `manutencao` (continuar=true) e chame "
                    "esta em seguida, na mesma mensagem; só pergunte qual se a busca não achar uma OS só."),
    "parameters": {"type": "object", "properties": {
        "os": {"type": "integer", "description": "o número da OS"},
        "texto": {"type": "string", "description": "a informação em texto, como a pessoa disse (vazio se ela só mandou fotos)"},
        "fotos": {"type": "boolean", "description": "as fotos que ela mandou por aqui entram também"}},
        "required": ["os"]}}}

PRAZO_INFO_S = 600
MAX_INSTRUCAO = 8_000      # o que o meuPlano aceita por fala da conversa do relatório (acima disso, 422)
MAX_TEXTO_INFO = 20_000    # o que o meuPlano aceita no texto de uma informação do relatório


async def informacoes_do_relatorio(ctx, a: dict) -> dict:
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        os_id = int(a.get("os"))
    except (TypeError, ValueError):
        return {"erro": "Falta o número da OS: pergunte qual é."}
    texto = (a.get("texto") or "").strip()[:MAX_TEXTO_INFO]
    lista = fotos.recebidas(ctx.telefone, sem_video=True) if a.get("fotos") else []
    if not texto and not lista:
        return {"erro": "Não há o que registrar: nenhum texto e nenhuma foto recebida (cada foto fica guardada 30 min)."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    try:
        await mp.fatos_da_os(os_id)                       # a OS existe e está no alcance dela?
    except httpx.HTTPStatusError as e:
        return {"erro": _motivo(e, os_id, "lê a OS")}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi registrado."}
    partes = ([f"o texto «{texto[:120]}{'…' if len(texto) > 120 else ''}»"] if texto else []) + \
        ([f"{len(lista)} foto(s)"] if lista else [])
    resumo = f"Registrar nas Informações do relatório da OS #{os_id}: " + " e ".join(partes)

    async def executar(db, user, telefone: str) -> str:
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        feitos = []
        if texto:
            try:
                await mp.criar_fato(os_id, texto)
                feitos.append("o texto")
            except httpx.HTTPStatusError as e:
                motivo = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
                return f"❌ O meuPlano recusou: {motivo}. Nada foi registrado."
            except httpx.HTTPError:
                return "⚠️ O meuPlano não respondeu a tempo: o texto PODE ter entrado. Confira a OS antes de mandar de novo."
        falhas = []
        if lista:
            feitas, falhas = await _subir_fotos(mp, os_id, telefone, lista)
            if feitas:
                feitos.append(f"{feitas} foto(s)")
        motivos = "".join(f"\n• {m}" for m in falhas)
        if not feitos:
            return f"❌ Nada entrou nas Informações do relatório da OS #{os_id}:{motivos}"
        fim = f" nas Informações do relatório da OS #{os_id} — a IA usa no relatório."
        return (f"⚠️ Registrei {' e '.join(feitos)}{fim}{motivos}" if falhas else f"✅ Registrei {' e '.join(feitos)}{fim}")

    from app.services import assistente_helper as helper
    return helper.propor(ctx, resumo, PRAZO_INFO_S, executar, [], parte="bot_meuplano", confirmacao="sim")
