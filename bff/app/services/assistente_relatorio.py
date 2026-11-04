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
pessoa mandou por aqui entram nos FATOS RELEVANTES da OS antes de gerar — a IA de lá as analisa — e saem da espera
(não vão também para a ficha de uma tarefa).
"""

import asyncio
import re
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
                    "fotos_de_apoio=true — entram nos fatos relevantes da OS e a IA as analisa (não é `anexar_fotos`, "
                    "que é a ficha de uma tarefa)."),
    "parameters": {"type": "object", "properties": {
        "os": {"type": "integer", "description": "o número da OS"},
        "escolha": {"type": "string", "enum": ["auto", "salvo", "novo"]},
        "relatorio_id": {"type": "integer", "description": "qual relatório salvo (o id da lista); vazio = o mais recente"},
        "instrucao": {"type": "string", "description": "como a pessoa quer o relatório NOVO (o prompt dela, inteiro); vazio = o salvo ou o padrão"},
        "fotos_de_apoio": {"type": "boolean", "description": "as fotos que ela mandou por aqui vão aos fatos relevantes da OS antes de gerar"}},
        "required": ["os"]}}}


def _de(iso: object) -> str:
    """A data de lá (UTC sem fuso) em hora de Brasília."""
    if isinstance(iso, str) and iso and not re.search(r"(Z|[+-]\d\d:\d\d)$", iso):
        iso += "+00:00"
    return hora_brt(iso)


def _nome_do_arquivo(titulo: str) -> str:
    return (re.sub(r'[\\/:*?"<>|\s]+', " ", titulo or "Relatório").strip()[:120] or "Relatório") + ".pdf"


def _motivo(e: httpx.HTTPStatusError, os_id: int, acao: str) -> str:
    from app.services.integracoes import detalhe_do_upstream
    st = e.response.status_code
    if st == 404:
        return f"A OS #{os_id} não existe no meuPlano ou não está no alcance desta pessoa."
    if st == 403:
        return f"O papel desta pessoa no meuPlano não {acao}. Nada foi feito: o gestor da O&M pode liberar."
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


async def _fotos_de_apoio(ctx, mp, os_id: int) -> dict:
    """As fotos que a pessoa mandou por aqui entram nos FATOS RELEVANTES da OS (a legenda vira o texto do fato) e saem da
    espera — a IA de lá as analisa ao gerar. Devolve o que contar à pessoa."""
    from app.clients import whatsapp
    recebidas = fotos.recebidas(ctx.telefone)
    if not recebidas:
        return {"fotos_de_apoio": 0, "nota_fotos": "Não havia foto recebida (cada uma fica guardada 30 min)."}
    feitas, falhas = 0, []
    for i, f in enumerate(recebidas, 1):
        try:
            conteudo, tipo = await whatsapp.baixar_midia(f["id"])
            await mp.criar_fato_arquivo(os_id, f"whatsapp-{i}.{(tipo or 'image/jpeg').split('/')[-1].split(';')[0]}",
                                        conteudo, tipo, f["legenda"] or "Imagem de apoio enviada pelo WhatsApp")
        except Exception as e:  # noqa: BLE001 — uma foto que não sobe não derruba o relatório; vai dita
            falhas.append(f"foto {i}: {type(e).__name__}")
            continue
        feitas += 1
        fotos._tirar(ctx.telefone, f["id"])
    out = {"fotos_de_apoio": feitas}
    if falhas:
        out["fotos_que_nao_entraram"] = falhas
    return out


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

    apoio = await _fotos_de_apoio(ctx, mp, os_id) if a.get("fotos_de_apoio") else {}
    try:
        rel = await _gerar(mp, os_id, (a.get("instrucao") or "").strip())
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
