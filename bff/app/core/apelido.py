"""O apelido — quem a pessoa é, para efeito de entrar no sistema.

A identidade do Gestão Solar é o apelido, não o e-mail. A diferença não é cosmética: a
mesma pessoa tem papéis distintos aqui e nos produtos de origem, e amarrar a conta ao
e-mail impediria justamente isso — o gestor do sistema e o dono de usina que ele atende
podem ser o mesmo humano, com o mesmo e-mail, e ainda assim precisam ser duas contas com
poderes diferentes. Com o e-mail como chave, a segunda conta seria recusada como duplicada.

Daí as duas consequências que este módulo carrega:

- **O apelido é obrigatório e único.** É por ele que se entra.
- **O e-mail é opcional.** Vale como contato e, no caso do cliente, como a chave que
  encontra a conta dele no meuWatt e no meuPlano — mas não é o que autentica.

O formato é apertado de propósito. Um apelido é ditado por telefone, digitado no celular
em campo e comparado a olho na lista da equipe; espaço, acento e maiúscula transformam
cada uma dessas três coisas numa fonte de erro silencioso.
"""

import re

#: Um separador só, nunca na ponta. `renan.marquezini` passa; `renan..marquezini`,
#: `.renan` e `renan-` não — todos são erro de digitação disfarçado de nome válido.
_FORMATO = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")

MINIMO = 3
MAXIMO = 32


class ApelidoInvalido(ValueError):
    """A mensagem é para quem digitou o apelido, e diz o que corrigir."""


def normalizar(valor: str | None) -> str:
    """Devolve o apelido canônico ou levanta `ApelidoInvalido`.

    Minúscula e sem espaço nas pontas é a única indulgência: quem digita "Renan" na tela
    de entrada quis dizer `renan`, e recusar isso seria implicância. O resto é recusado com
    o motivo, porque um apelido quase certo é pior do que um recusado — ele cria uma
    segunda conta parecida em vez de entrar na primeira.
    """
    limpo = (valor or "").strip().lower()

    if not limpo:
        raise ApelidoInvalido("Informe o apelido.")
    if len(limpo) < MINIMO:
        raise ApelidoInvalido(f"O apelido precisa de pelo menos {MINIMO} caracteres.")
    if len(limpo) > MAXIMO:
        raise ApelidoInvalido(f"O apelido passa de {MAXIMO} caracteres.")
    if " " in limpo:
        raise ApelidoInvalido(
            "O apelido não pode ter espaço. Use ponto para separar: renan.marquezini."
        )
    if not _FORMATO.match(limpo):
        raise ApelidoInvalido(
            "O apelido aceita letras sem acento, números, ponto, hífen e sublinhado — "
            "sempre com uma letra ou número nas pontas. Exemplo: renan.marquezini."
        )
    return limpo


def sugerir(base: str) -> str:
    """Um apelido plausível a partir de um nome ou e-mail, para o campo já nascer preenchido.

    Só uma sugestão: o gestor edita antes de salvar. Devolve string vazia quando não sobra
    nada aproveitável — a tela então deixa o campo em branco em vez de propor `___`.
    """
    bruto = (base or "").strip().lower().split("@")[0]

    # Acento sai virando a letra sem acento em vez de sumir: `joão` deve virar `joao`,
    # não `joo`.
    for acentuada, simples in (
        ("áàâãä", "a"), ("éèêë", "e"), ("íìîï", "i"),
        ("óòôõö", "o"), ("úùûü", "u"), ("ç", "c"), ("ñ", "n"),
    ):
        for c in acentuada:
            bruto = bruto.replace(c, simples)

    bruto = re.sub(r"[\s_]+", ".", bruto)
    bruto = re.sub(r"[^a-z0-9._-]", "", bruto)
    bruto = re.sub(r"[._-]{2,}", ".", bruto).strip("._-")

    return bruto[:MAXIMO].rstrip("._-") if len(bruto) >= MINIMO else ""
