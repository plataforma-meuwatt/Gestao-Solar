"""O telefone do cliente, num formato só.

O número chega digitado por gente: com máscara, com DDI, sem o nono dígito, com espaço no
meio. Guardar o que foi digitado faria duas linhas iguais parecerem diferentes — e o dia em
que o WhatsApp for enviar, "(16) 99999-8888" e "+5516999998888" precisam ser o mesmo
destino. Então entra normalizado, em E.164, e sai daqui como texto único.

**O nono dígito é acrescentado, não presumido.** Celular brasileiro tem nove dígitos desde
2016; número de dez dígitos que começa com 6, 7, 8 ou 9 é um celular escrito à moda antiga,
e o 9 na frente é o que ele virou. Fixo (começa com 2 a 5) fica com oito — e é aceito
porque o cadastro do cliente não é só de WhatsApp; quem envia é que confere se o destino
recebe mensagem.

Recusar é preferível a adivinhar: número curto demais, DDD impossível ou letra no meio
voltam como erro para o gestor corrigir, em vez de virarem uma linha que nunca entrega.
"""

import re

#: DDDs existentes no Brasil vão de 11 a 99 — mas não todos. A régua aqui é o formato, não
#: o mapa da Anatel: recusar um DDD válido por causa de uma lista desatualizada seria pior
#: do que aceitar um inexistente, que falha na hora do envio com a resposta da Meta.
_DDD_MIN, _DDD_MAX = 11, 99

_SO_DIGITOS = re.compile(r"\D+")


class TelefoneInvalido(ValueError):
    """Mensagem pronta para a tela: diz o que está errado, não "valor inválido"."""


def normalizar(valor: str | None) -> str | None:
    """`(16) 9 9999-8888` → `+5516999998888`. Vazio vira `None` (apagar é legítimo)."""
    if valor is None:
        return None
    bruto = valor.strip()
    if not bruto:
        return None

    digitos = _SO_DIGITOS.sub("", bruto)
    if not digitos:
        raise TelefoneInvalido("Telefone sem número nenhum.")

    # DDI do Brasil: só é retirado quando o que sobra ainda tem tamanho de telefone. Sem
    # essa checagem, "5511" viraria "11" e passaria como DDD sozinho.
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]

    if len(digitos) < 10:
        raise TelefoneInvalido(
            "Telefone curto demais. Informe com DDD — ex.: (16) 99999-8888."
        )
    if len(digitos) > 11:
        raise TelefoneInvalido(
            "Telefone longo demais. Use DDD + número, sem código de país repetido."
        )

    ddd, numero = digitos[:2], digitos[2:]
    if not (_DDD_MIN <= int(ddd) <= _DDD_MAX):
        raise TelefoneInvalido(f"DDD {ddd} não existe.")

    # Celular antigo, de oito dígitos: ganha o 9. Fixo continua com oito.
    if len(numero) == 8 and numero[0] in "6789":
        numero = "9" + numero

    return f"+55{ddd}{numero}"


def e_celular(telefone: str) -> bool:
    """Um E.164 brasileiro de celular — o que o WhatsApp alcança.

    Serve para a tela avisar antes do envio: fixo cadastrado é telefone legítimo do cliente
    e não é destino de mensagem.
    """
    if not telefone.startswith("+55"):
        return False
    numero = telefone[5:]
    return len(numero) == 9 and numero[0] == "9"


def exibir(telefone: str | None) -> str | None:
    """`+5516999998888` → `(16) 99999-8888`, para a tela não mostrar E.164 cru."""
    if not telefone or not telefone.startswith("+55"):
        return telefone
    ddd, numero = telefone[3:5], telefone[5:]
    if len(numero) == 9:
        return f"({ddd}) {numero[0]} {numero[1:5]}-{numero[5:]}"
    if len(numero) == 8:
        return f"({ddd}) {numero[:4]}-{numero[4:]}"
    return telefone
