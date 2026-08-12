"""Cifra os segredos que o BFF precisa guardar para funcionar.

O que passa por aqui: a senha das contas de serviço nos upstreams e, mais adiante, os
tokens de aplicativo de cada cliente conectado. Nada disso pode ficar em texto no banco —
um dump do Postgres do BFF entregaria acesso aos dois outros sistemas de uma vez.

Fernet (AES-128-CBC + HMAC) resolve o caso: chave única, rotacionável, e o texto cifrado
já vem autenticado, então adulteração no banco é detectada em vez de virar lixo silencioso.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class SegredoInvalido(RuntimeError):
    """O texto cifrado não abre com a chave atual — chave trocada ou dado adulterado."""


@lru_cache
def _fernet() -> Fernet:
    chave = get_settings().gs_encryption_key
    if not chave:
        raise RuntimeError(
            "GS_ENCRYPTION_KEY não configurada. Gere uma com:\n"
            '  python -c "from cryptography.fernet import Fernet;'
            ' print(Fernet.generate_key().decode())"'
        )
    return Fernet(chave.encode())


def cifrar(valor: str) -> str:
    return _fernet().encrypt(valor.encode()).decode()


def decifrar(valor: str) -> str:
    try:
        return _fernet().decrypt(valor.encode()).decode()
    except InvalidToken as exc:
        raise SegredoInvalido(
            "Não foi possível abrir o segredo guardado. Isso acontece quando a "
            "GS_ENCRYPTION_KEY muda — reconfigure a integração para gravar de novo."
        ) from exc
