"""O PDF NÃO REVISADO do relatório mensal do meuWatt, gerado AQUI, na API do GS (26/11/2026, pedido do Renan: produção
fora da VM dele). Antes era o `meuwatt-relatorio-pdf` (Node) do srvclaude, pelo túnel; esta é a mesma receita.

O Relatório de Geração e o Anexo de Paradas são React: não há versão de servidor. Abre a página só-documento do meuWatt
(`?relatorio_pdf=…`, mw-fe `RelatorioPdfBot.tsx`) num Chromium sem tela, com o token do meuWatt DE QUEM PEDIU, espera o
documento (e a IA, que escreve os comentários quando o mês não tem análise) e devolve o PDF que a própria página
capturou (`window.__mwRelatorioPdf`). Um por vez (Chromium ~400 MB), fila de até 3. Liga com `RELATORIO_PDF_URL=interno`."""
import asyncio
import base64
import json
import re
from urllib.parse import quote

APP = "https://app.meuwatt.com.br"
TETO_S = 420                 # o documento + a IA (até ~4 min) + a captura
FILA_MAX = 3
_UM_POR_VEZ = asyncio.Semaphore(1)
_esperando = 0


async def gerar(token: str, usina: str, mes: str, doc: str, espera_s: float = 560
                ) -> tuple[bytes | None, str | None, str | None]:
    """`(pdf, nome do arquivo, erro)`, como o cliente do gerador externo."""
    global _esperando
    if (not token or not re.fullmatch(r"[a-z0-9-]{2,80}", usina or "")
            or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes or "") or doc not in ("geracao", "paradas")):
        return None, None, "pedido inválido para o gerador de PDF"
    if _esperando >= FILA_MAX:
        return None, None, "já há relatórios sendo gerados; tente em alguns minutos"
    _esperando += 1
    try:
        async with _UM_POR_VEZ:
            return await asyncio.wait_for(_abrir(token, usina, mes, doc), timeout=min(espera_s, TETO_S + 60))
    except asyncio.TimeoutError:
        return None, None, "o documento não ficou pronto a tempo (token recusado ou o meuWatt lento)"
    except Exception as e:  # noqa: BLE001 — o bot diz o motivo; nada de pilha para a pessoa
        return None, None, f"o gerador de PDF falhou: {str(e)[:200]}"
    finally:
        _esperando -= 1


async def _abrir(token: str, usina: str, mes: str, doc: str) -> tuple[bytes | None, str | None, str | None]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        navegador = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        try:
            ctx = await navegador.new_context(viewport={"width": 1280, "height": 1000})
            # o token só entra na origem do meuWatt (a página pode redirecionar; nada vaza para outro site)
            await ctx.add_init_script(
                f"try {{ if (location.origin === {json.dumps(APP)}) localStorage.setItem('mw_jwt', {json.dumps(token)}) }}"
                " catch (e) {}")
            pagina = await ctx.new_page()
            await pagina.goto(f"{APP}/?relatorio_pdf={doc}&usina={quote(usina)}&mes={mes}",
                              wait_until="domcontentloaded", timeout=60_000)
            # token recusado: a página cai no login e nunca escreve o resultado; o teto responde
            await pagina.wait_for_function("() => window.__mwRelatorioPdf", timeout=TETO_S * 1000, polling=1000)
            r = await pagina.evaluate("() => window.__mwRelatorioPdf")
        finally:
            await navegador.close()
    if not r or not r.get("ok"):
        return None, None, f"o meuWatt não gerou o documento: {(r or {}).get('erro') or 'sem resultado'}"
    return base64.b64decode(r["base64"]), r.get("nome") or f"{doc}-{usina}-{mes}-NAO-REVISADO.pdf", None
