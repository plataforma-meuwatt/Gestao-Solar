"""Número em E.164, e o `wa_id` que a Meta usa.

Cópia deliberada da regra de `bff/app/core/telefone.py`. Não é descuido: o gateway é um
serviço à parte, com banco e deploy próprios, e importar código do BFF criaria um
acoplamento que o desenho inteiro existe para evitar. O preço é este arquivo — e os testes
dos dois lados cobrem os mesmos casos, então uma divergência aparece em vermelho.

**O `wa_id` não é o E.164.** A Meta identifica o contato por um número sem o `+`, e em
telefone brasileiro ele às vezes vem SEM o nono dígito, mesmo quando o número tem. Por isso
a conversa é chaveada pelo `wa_id` como a Meta manda, e o E.164 serve para casar com o
cadastro e para enviar a quem ainda não escreveu.
"""

import re

_SO_DIGITOS = re.compile(r"\D+")
_DDD_MIN, _DDD_MAX = 11, 99


class TelefoneInvalido(ValueError):
    """Mensagem pronta para quem chamou: diz o que está errado."""


def normalizar(valor: str | None) -> str | None:
    """`(16) 9 9999-8888` → `+5516999998888`. Vazio vira `None`."""
    if valor is None:
        return None
    bruto = valor.strip()
    if not bruto:
        return None

    digitos = _SO_DIGITOS.sub("", bruto)
    if not digitos:
        raise TelefoneInvalido("Telefone sem número nenhum.")

    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    if len(digitos) < 10:
        raise TelefoneInvalido("Telefone curto demais. Informe com DDD.")
    if len(digitos) > 11:
        raise TelefoneInvalido("Telefone longo demais.")

    ddd, numero = digitos[:2], digitos[2:]
    if not (_DDD_MIN <= int(ddd) <= _DDD_MAX):
        raise TelefoneInvalido(f"DDD {ddd} não existe.")
    if len(numero) == 8 and numero[0] in "6789":
        numero = "9" + numero
    return f"+55{ddd}{numero}"


def para_envio(telefone: str) -> str:
    """O que a Graph espera no campo `to`: só dígitos, com DDI, sem o `+`."""
    return _SO_DIGITOS.sub("", telefone)


def mesma_pessoa(wa_id: str, telefone: str | None) -> bool:
    """O `wa_id` da Meta e o telefone do cadastro são o mesmo número?

    Compara DDD + últimos oito dígitos, que é o que sobrevive à ausência do nono dígito dos
    dois lados. Comparar o número inteiro deixaria de casar exatamente no caso comum:
    cadastro com nove dígitos, `wa_id` com oito.
    """
    if not telefone:
        return False

    def _ddd_e_fim(valor: str) -> tuple[str, str] | None:
        d = _SO_DIGITOS.sub("", valor)
        if d.startswith("55") and len(d) >= 12:
            d = d[2:]
        if len(d) < 10:
            return None
        return d[:2], d[-8:]

    a, b = _ddd_e_fim(wa_id), _ddd_e_fim(telefone)
    return a is not None and a == b
