"""A conexão com os upstreams, reaproveitada.

Cada cliente abria um `httpx.AsyncClient` por chamada (`async with`), o que significa um
handshake TCP+TLS por requisição. Enquanto cada tela pedia uma coisa isso era invisível;
a Visão geral do portal pede seis blocos por usina para sete usinas de uma vez — 64 idas
aos upstreams no mesmo instante, 64 handshakes — e o efeito medido foi brutal: o mesmo
`breakdowns/range` que responde em **1,1 s** sozinho levava **21 s** dentro do lote, e a
tela inteira passava de 30 s (o teto do navegador) sem que nenhum upstream tivesse
demorado de verdade.

Aqui a conexão é guardada e reusada: keep-alive de verdade, o handshake acontece uma vez
por destino e o resto das chamadas entra por uma conexão já aberta.

Duas cautelas que o cache exige:

- **Uma sessão por event loop.** O `pytest-asyncio` cria um loop por teste e o Uvicorn
  reinicia o seu num reload; um `AsyncClient` criado num loop e usado noutro estoura em
  tempo de execução. A chave inclui o loop, então cada um tem o seu.
- **O `timeout` não entra na chave.** Ele é por requisição (`client.request(timeout=…)`),
  e é assim que a fonte de paradas consegue um teto curto sem abrir sessão própria.
"""

import asyncio

import httpx

#: `(id do event loop, base_url, follow_redirects)` → sessão viva.
_sessoes: dict[tuple[int, str, bool], httpx.AsyncClient] = {}

#: Teto de conexões simultâneas por destino. Alto o bastante para a Visão geral inteira
#: caber sem fila, baixo o bastante para não parecer um ataque ao upstream.
_LIMITES = httpx.Limits(max_connections=40, max_keepalive_connections=20)


def sessao(
    base_url: str, timeout: float = 30.0, follow_redirects: bool = False
) -> httpx.AsyncClient:
    """A sessão HTTP deste destino no loop corrente, criada na primeira vez.

    O `timeout` recebido é só o padrão da sessão; quem precisa de outro passa na chamada.
    """
    try:
        chave = (id(asyncio.get_running_loop()), base_url, follow_redirects)
    except RuntimeError:  # noqa: BLE001 — fora de loop, sessão descartável
        return httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects)

    viva = _sessoes.get(chave)
    if viva is not None and not viva.is_closed:
        return viva

    nova = httpx.AsyncClient(
        timeout=timeout, follow_redirects=follow_redirects, limits=_LIMITES
    )
    _sessoes[chave] = nova
    return nova


async def fechar_sessoes() -> None:
    """Fecha o que estiver aberto no loop corrente. Para o desligamento do processo e
    para o teste que quer terminar sem conexão pendurada."""
    try:
        atual = id(asyncio.get_running_loop())
    except RuntimeError:
        return
    for chave in [k for k in _sessoes if k[0] == atual]:
        cliente = _sessoes.pop(chave)
        if not cliente.is_closed:
            await cliente.aclose()
