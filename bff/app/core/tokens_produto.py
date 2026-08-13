"""Confere um token de produto SEM sair da máquina.

O gestor tem duas caixas de texto na tela de Conexões, uma para o meuWatt e outra para o
meuPlano, e dois valores longos e parecidos na área de transferência. Trocá-los de lugar
é o erro provável, e é o mais caro de diagnosticar: o servidor do outro lado responde 401,
que é exatamente o que ele responderia se o token estivesse revogado, expirado ou se a
conta tivesse sido desativada. A tela mostraria "credencial recusada" e o gestor ficaria
conferindo a coisa errada.

Os dois produtos emitem tokens autodescritivos — prefixo de produto e dígito verificador
CRC-32 sobre o sorteio. Este módulo é o lado de cá desse acordo:

    mw_pat_<32 caracteres><6 de verificação>   meuWatt   (mw-api/src/api_tokens/token_format.py)
    mp_pat_<32 caracteres><6 de verificação>   meuPlano  (backend/app/services/meuacesso/api_tokens.py)

É código duplicado de propósito: são três repositórios que sobem separados, e importar
um do outro criaria um acoplamento de deploy para economizar quarenta linhas. O que não
pode divergir é o FORMATO — mudá-lo em um produto exige mudar aqui, e os testes de
`test_tokens_produto.py` existem para que a divergência apareça como teste vermelho e
não como conexão que parou de funcionar.

Reparar no engano aqui custa zero chamadas de rede e devolve a frase certa: "este é um
token do meuPlano, você colou no campo do meuWatt".
"""

import string
import zlib

from app.models.integracao import Produto

_ALPHABET = frozenset(string.digits + string.ascii_uppercase + string.ascii_lowercase)
_BODY_LEN = 32
_CHECK_LEN = 6

#: Prefixo de cada produto. Os nomes são os que aparecem na tela.
PREFIXO: dict[Produto, str] = {
    Produto.MEUWATT: "mw_pat_",
    Produto.MEUPLANO: "mp_pat_",
}
NOME: dict[Produto, str] = {
    Produto.MEUWATT: "meuWatt",
    Produto.MEUPLANO: "meuPlano",
}

TAMANHO = len(PREFIXO[Produto.MEUWATT]) + _BODY_LEN + _CHECK_LEN


class TokenInvalido(ValueError):
    """A mensagem é escrita para quem colou o token, não para o log."""


def _base62(numero: int, largura: int) -> str:
    ordenado = string.digits + string.ascii_uppercase + string.ascii_lowercase
    saida = []
    for _ in range(largura):
        numero, resto = divmod(numero, 62)
        saida.append(ordenado[resto])
    return "".join(reversed(saida))


def _verificador(corpo: str) -> str:
    return _base62(zlib.crc32(corpo.encode("ascii")), _CHECK_LEN)


def validar(produto: Produto, token: str) -> str:
    """Devolve o token limpo ou levanta `TokenInvalido` dizendo o que está errado."""
    limpo = (token or "").strip()
    prefixo = PREFIXO[produto]

    if not limpo:
        raise TokenInvalido("Cole o token para conectar.")

    if not limpo.startswith(prefixo):
        for outro, pref_outro in PREFIXO.items():
            if outro is not produto and limpo.startswith(pref_outro):
                raise TokenInvalido(
                    f"Este é um token do {NOME[outro]}, e o campo é do {NOME[produto]}. "
                    "Confira se os dois não foram trocados de lugar."
                )
        raise TokenInvalido(
            f"Um token do {NOME[produto]} começa com '{prefixo}'. "
            "Cole o valor inteiro, como ele apareceu na hora em que foi gerado."
        )

    if len(limpo) != TAMANHO:
        raise TokenInvalido(
            f"O token tem {len(limpo)} caracteres e o formato pede {TAMANHO}. "
            "A cópia provavelmente veio cortada."
        )

    resto = limpo[len(prefixo):]
    if not set(resto) <= _ALPHABET:
        raise TokenInvalido(
            "O token tem caracteres que não pertencem ao formato — pode ter vindo com "
            "espaço, quebra de linha ou aspas junto."
        )

    corpo, verificador = resto[:_BODY_LEN], resto[_BODY_LEN:]
    if verificador != _verificador(corpo):
        raise TokenInvalido(
            "O dígito verificador não confere. Isso acontece quando falta um caractere "
            "na cópia ou quando um deles foi trocado — gere e copie o token de novo."
        )
    return limpo


def valido(produto: Produto, token: str) -> bool:
    try:
        validar(produto, token)
    except TokenInvalido:
        return False
    return True


def prefixo_visivel(token: str) -> str:
    """`mw_pat_a1b2` — identifica o token na tela sem revelá-lo. É por ele que o gestor
    confere se o que está gravado aqui é o mesmo que ele vê na lista do produto."""
    return (token or "").strip()[:11]
