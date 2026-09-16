"""Cifra os segredos da Meta guardados no banco do gateway.

O que passa por aqui: o token de acesso, o segredo do app e o token de verificação do
webhook. Nada disso pode ficar em texto no banco — um dump entregaria o direito de mandar
mensagem em nome da empresa e de forjar entregas de webhook.

Fernet (AES-128-CBC + HMAC), a mesma escolha de `bff/app/core/cripto.py`: chave única,
rotacionável, e o texto cifrado já vem autenticado, então adulteração no banco é detectada
em vez de virar lixo silencioso.

**A chave é OUTRA, e não a do BFF.** São dois serviços, dois bancos e dois deploys; dividir
a chave faria o vazamento de um entregar os segredos do outro, e rotacioná-la exigiria
parar os dois juntos.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from gateway.core.config import get_settings


class SegredoInvalido(RuntimeError):
    """O texto cifrado não abre com a chave atual — chave trocada ou dado adulterado."""


class CifragemIndisponivel(RuntimeError):
    """Sem `GATEWAY_ENCRYPTION_KEY` não se grava segredo. A tela mostra esta frase."""


@lru_cache
def _fernet() -> Fernet:
    chave = get_settings().gateway_encryption_key
    if not chave:
        raise CifragemIndisponivel(
            "GATEWAY_ENCRYPTION_KEY não configurada. Gere uma com:\n"
            '  python -c "from cryptography.fernet import Fernet;'
            ' print(Fernet.generate_key().decode())"'
        )
    return Fernet(chave.encode())


def disponivel() -> bool:
    """Dá para cifrar agora? A tela pergunta isso antes de oferecer o formulário."""
    return bool(get_settings().gateway_encryption_key)


def cifrar(valor: str) -> str:
    return _fernet().encrypt(valor.encode()).decode()


def decifrar(valor: str) -> str:
    try:
        return _fernet().decrypt(valor.encode()).decode()
    except InvalidToken as exc:
        raise SegredoInvalido(
            "Não foi possível abrir o segredo guardado. Isso acontece quando a "
            "GATEWAY_ENCRYPTION_KEY muda — grave as credenciais de novo pela tela."
        ) from exc
