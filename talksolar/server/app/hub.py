# -*- coding: utf-8 -*-
"""O HUB — quem avisa as telas abertas de que aconteceu algo AGORA.

Num mensageiro, "tempo real" não é enfeite: se a mensagem só aparece quando a pessoa atualiza,
ninguém troca o Teams por isto.

**DECISÃO DE INFRA, dita com todas as letras:** o registro de conexões vive NA MEMÓRIA DO
PROCESSO. Isso basta enquanto o serviço rodar como uma instância só — e é honesto dizer que, no
dia em que houver duas, duas pessoas em instâncias diferentes deixam de se ver ao vivo. A saída
nesse dia é publicar por Redis (ou pelo LISTEN/NOTIFY do próprio Postgres) em vez de um
dicionário local; **o resto do código não muda, porque tudo passa por `publicar()`**.

E a tela NÃO DEPENDE disto para estar correta: ela recarrega ao abrir e a cada 30 s. O
WebSocket ACELERA; não é a fonte da verdade. Um mensageiro que só funciona com a conexão viva
perde mensagem em túnel de elevador — e perder mensagem é a única falha que um mensageiro não
pode ter.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Set

log = logging.getLogger("talksolar.hub")


class Hub:
    def __init__(self) -> None:
        self._por_usuario: Dict[int, Set[Any]] = {}
        self._trava = asyncio.Lock()

    async def entrar(self, usuario_id: int, ws: Any) -> None:
        async with self._trava:
            self._por_usuario.setdefault(usuario_id, set()).add(ws)

    async def sair(self, usuario_id: int, ws: Any) -> None:
        async with self._trava:
            conexoes = self._por_usuario.get(usuario_id)
            if conexoes:
                conexoes.discard(ws)
                if not conexoes:
                    self._por_usuario.pop(usuario_id, None)

    async def publicar(self, usuarios: list[int], dados: dict) -> None:
        """Empurra para todas as telas daquelas pessoas.

        Falha de envio NUNCA sobe: a mensagem já está gravada, e derrubar o pedido de quem
        escreveu porque a aba de outra pessoa fechou seria trocar um problema pequeno por um
        grande. A conexão quebrada sai da lista.
        """
        async with self._trava:
            alvos = [(uid, ws) for uid in set(usuarios)
                     for ws in list(self._por_usuario.get(uid, ()))]
        for uid, ws in alvos:
            try:
                await ws.send_json(dados)
            except Exception:                  # noqa: BLE001
                await self.sair(uid, ws)

    def online(self) -> set[int]:
        return set(self._por_usuario.keys())


hub = Hub()
