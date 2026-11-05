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
                    "o mais recente). escolha=novo gera AGORA com IA e manda (leva até 2 minutos): use quando a pessoa "
                    "pediu um novo ('gera outro', 'refaz'), respondeu que quer o novo, ou mandou COMO quer o relatório "
                    "(o prompt) ou imagens de apoio. O prompt dela (para quem, foco, tamanho — 'com o prompt …') vai em "
                    "`instrucao`, inteiro, e fica salvo na OS; sem ele, vale o que já estiver salvo lá ou o padrão. "
                    "Fotos que ela mandou para o relatório (a mensagem aparece como «[📷 N foto(s) recebida(s)…]»): "
                    "fotos_de_apoio=true — entram nas informações do relatório da OS e a IA as analisa; com fotos, "
                    "vira uma ação que a pessoa confirma no botão Sim (as fotos sobem e o relatório é gerado depois "
                    "dele). Não é `anexar_fotos`, que é a ficha de uma tarefa. Só registrar informação, sem gerar, é "
                    "`informacoes_do_relatorio`."),
    "parameters": {"type": "object", "properties": {
        "os": {"type": "integer", "description": "o número da OS"},
        "escolha": {"type": "string", "enum": ["auto", "salvo", "novo"]},
        "relatorio_id": {"type": "integer", "description": "qual relatório salvo (o id da lista); vazio = o mais recente"},
        "instrucao": {"type": "string", "description": "como a pessoa quer o relatório NOVO (o prompt dela, inteiro); vazio = o salvo ou o padrão"},
        "fotos_de_apoio": {"type": "boolean", "description": "as fotos que ela mandou por aqui vão às informações do relatório da OS antes de gerar"}},
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


async def _gerar(mp, os_id: int, instrucao: str) -> dict:
    """O "Novo relatório com IA" de lá até o fim, e o PDF dele pelo WordCraft de lá."""
    job = (await mp.relatorio_ia(os_id, instrucao))
    fim = monotonic() + PRAZO_GERAR_S
    while True:
        await asyncio.sleep(ESPERA_S)
        e = await mp.relatorio_ia_estado(job)
        if e.get("status") == "pronto" and e.get("doc_id"):
            break
        if e.get("status") == "erro":
            raise RuntimeError(e.get("erro") or "a IA de lá não conseguiu montar o relatório")
        if monotonic() > fim:
            raise RuntimeError(f"passou de {PRAZO_GERAR_S // 60} minutos e o relatório não ficou pronto "
                               f"(etapa: {e.get('etapa') or '—'})")
    return await mp.publicar_relatorio(int(e["doc_id"]))


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
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão: gerar leva até 2 min
    try:
        salvos = await mp.relatorios_da_os(os_id)
    except httpx.HTTPStatusError as e:
        return {"erro": _motivo(e, os_id, "lê relatório de OS")}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu agora. Nada foi enviado."}

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
            raw = await mp.relatorio_pdf(r["id"])
        except httpx.HTTPError:
            return {"erro": "Não consegui baixar o relatório salvo no meuPlano agora. Nada foi enviado."}
        return {"os": os_id, "relatorio": "salvo", "titulo": r.get("titulo"),
                "de": _de(r.get("atualizado_em") or r.get("created_at")), **(await _mandar(ctx, raw, r.get("titulo") or f"Relatório da OS #{os_id}"))}
    if escolha == "salvo":
        return {"erro": f"A OS #{os_id} não tem relatório salvo. Ofereça gerar um novo agora."}

    instrucao = (a.get("instrucao") or "").strip()[:MAX_INSTRUCAO]
    lista = fotos.recebidas(ctx.telefone) if a.get("fotos_de_apoio") else []
    if lista:
        return _propor_com_fotos(ctx, os_id, instrucao, lista)
    apoio = {"fotos_de_apoio": 0, "nota_fotos": "Não havia foto recebida (cada uma fica guardada 30 min)."} \
        if a.get("fotos_de_apoio") else {}
    try:
        rel = await _gerar(mp, os_id, instrucao)
        raw = await mp.relatorio_pdf(rel["id"])
    except httpx.HTTPStatusError as e:
        return {"erro": _motivo(e, os_id, "gera relatório de OS (precisa poder editar a OS)")}
    except httpx.HTTPError:
        return {"erro": "O meuPlano não respondeu enquanto o relatório era gerado. Confira a aba Relatórios da OS "
                        "antes de pedir de novo: ele pode ter ficado pronto lá."}
    except RuntimeError as e:
        return {"erro": f"Não consegui gerar o relatório: {e}."}
    return {"os": os_id, "relatorio": "novo", "titulo": rel.get("titulo"), **apoio,
            "salvo_na_os": "o rascunho Word e o PDF ficaram na aba Relatórios da OS; o prompt, na conversa do relatório",
            **(await _mandar(ctx, raw, rel.get("titulo") or f"Relatório da OS #{os_id}"))}


# --------------------------------------------------------------------------- informações do relatório, sem gerar
FERRAMENTA_INFO = {"type": "function", "function": {
    "name": "informacoes_do_relatorio",
    "description": ("Registra nas INFORMAÇÕES DO RELATÓRIO de uma OS do meuPlano (o que serve de evidência para o "
                    "relatório: o print da oscilografia, a foto do dano, uma observação, um valor medido) o TEXTO que a "
                    "pessoa mandou e/ou as FOTOS que ela mandou por aqui (a mensagem aparece como «[📷 N foto(s) "
                    "recebida(s)…]»). Vira uma ação que ela confirma no botão Sim. Não gera o relatório (isso é "
                    "`relatorio_da_os`) nem é a ficha de uma tarefa (`anexar_fotos`). Sem saber a OS, pergunte qual."),
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
    lista = fotos.recebidas(ctx.telefone) if a.get("fotos") else []
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
