"""RELATÓRIO DA OS pelo bot (pedido do Renan, 04/11/2026: "quero que o bot gere o relatório da OS e envie o PDF" —
"tem duas opções: gerar na hora e enviar; e, se tiver, enviar o relatório salvo. Se não tiver, ele gera e envia; se
tiver, ele pede o que quer").

Tudo no meuPlano, com o token DA PESSOA (a régua de lá diz se ela vê a OS e se pode gerar). O SALVO é a aba
Relatórios da OS de lá (o PDF exportado de um rascunho Word). O NOVO é o "Novo relatório com IA" de lá: a IA lê a OS,
as tarefas, as fichas e as fotos e monta o Word, e o PDF dele sai do WordCraft do servidor de lá — o mesmo motor do
editor, nunca LibreOffice. O novo fica salvo na OS (o rascunho Word e o PDF na aba Relatórios). O arquivo vai como
DOCUMENTO no WhatsApp; os bytes não passam pela IA.
"""

import asyncio
import re
from time import monotonic

import httpx

from app.core.datas import hora_brt

#: a IA de lá leva de 30 s a 2 min para montar o relatório (o turno inteiro segue com o "digitando…")
PRAZO_GERAR_S = 240
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
                    "pediu um novo ('gera outro', 'refaz') ou respondeu que quer o novo. Como ela quer o novo (para "
                    "quem, foco, tamanho) vai em `instrucao`; sem isso, o padrão é capa, contexto e o que foi feito."),
    "parameters": {"type": "object", "properties": {
        "os": {"type": "integer", "description": "o número da OS"},
        "escolha": {"type": "string", "enum": ["auto", "salvo", "novo"]},
        "relatorio_id": {"type": "integer", "description": "qual relatório salvo (o id da lista); vazio = o mais recente"},
        "instrucao": {"type": "string", "description": "como a pessoa quer o relatório NOVO; vazio = o padrão"}},
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


async def relatorio_da_os(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        os_id = int(a.get("os"))
    except (TypeError, ValueError):
        return {"erro": "Falta o número da OS: pergunte qual é."}
    escolha = (a.get("escolha") or "auto").lower()
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
    return {"os": os_id, "relatorio": "novo", "titulo": rel.get("titulo"),
            "salvo_na_os": "o rascunho Word e o PDF ficaram na aba Relatórios da OS",
            **(await _mandar(ctx, raw, rel.get("titulo") or f"Relatório da OS #{os_id}"))}
