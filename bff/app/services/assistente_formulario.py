"""Opções para MARCAR num formulário do WhatsApp (pedido do Renan, 29/10/2026: "não tem como ele enviar a lista e eu
clico só nas que quero deixar?").

O meuPlano devolve, no run, as opções que o turno ofereceu (`escolha`: título, opções, as já marcadas e o começo da
resposta). O bot manda a resposta e, logo depois, o formulário (WhatsApp Flow `gs_escolha_multipla`, caixas de marcar,
as de hoje já marcadas). O que a pessoa marca volta como mensagem (`midia.formulario`) e vira o texto
"<responda>: A, B", que segue como se ela tivesse digitado: a IA leva ao meuPlano, que propõe e pede o Sim.
"""

import secrets
from time import monotonic

from app.clients import whatsapp

#: O formulário aberto de cada número (só o último vale). ponytail: em memória, como as fotos; o deploy esquece.
_ABERTOS: dict[str, dict] = {}
VALIDADE_S = 30 * 60
MAX_OPCOES = 20                                           # o limite das caixas de marcar do WhatsApp
PARA_A_IA = ("O sistema manda, logo depois da sua resposta, um formulário com estas opções para a pessoa marcar: NÃO "
             "liste as opções, diga só que é para marcar no formulário.")
VENCIDO = "Esse formulário não vale mais (venceu ou veio outro depois). Peça de novo e eu mando outro."


def valida(escolha) -> bool:
    return (isinstance(escolha, dict) and isinstance(escolha.get("opcoes"), list)
            and 0 < len(escolha["opcoes"]) <= MAX_OPCOES and bool(escolha.get("responda")))


def em_texto(escolha: dict) -> str:
    """Sem o formulário (gateway ou Meta recusou), a lista para responder digitando."""
    marcados = set(escolha.get("marcados") or [])
    return (f"{escolha.get('titulo') or 'Opções'} (✔ = marcado hoje):\n"
            + "\n".join(f"• {o}{' ✔' if o in marcados else ''}" for o in escolha["opcoes"])
            + "\nResponda com os que ficam.")


async def mandar(telefone: str, escolha: dict) -> bool:
    token = secrets.token_urlsafe(12)
    agora = monotonic()
    for velho in [t for t, f in _ABERTOS.items() if agora - f["em"] >= VALIDADE_S]:
        del _ABERTOS[velho]
    _ABERTOS[telefone] = {"token": token, "escolha": escolha, "em": agora}
    try:
        r = await whatsapp.enviar_conteudo(
            telefone=telefone, tipo="formulario", texto="Toque em Marcar e deixe marcados só os que ficam.",
            formulario={"token": token, "titulo": str(escolha.get("titulo") or "Escolha")[:300],
                        "opcoes": [str(o) for o in escolha["opcoes"]],
                        "marcados": [str(m) for m in escolha.get("marcados") or []],
                        "aviso": str(escolha.get("aviso") or "")[:300]})
    except whatsapp.GatewayIndisponivel:
        r = None
    if not (r or {}).get("ok"):
        del _ABERTOS[telefone]
        return False
    return True


def e_resposta(evento: dict) -> bool:
    return isinstance((evento.get("midia") or {}).get("formulario"), dict)


def texto_da_resposta(telefone: str, evento: dict) -> str | None:
    """O que a pessoa marcou, em palavras ("<responda>: A, B"). None: formulário vencido ou de outro envio."""
    r = evento["midia"]["formulario"]
    aberto = _ABERTOS.get(telefone)
    if aberto is None or monotonic() - aberto["em"] >= VALIDADE_S or r.get("flow_token") != aberto["token"]:
        return None
    del _ABERTOS[telefone]
    opcoes = aberto["escolha"]["opcoes"]
    ids = r.get("escolhidos") if isinstance(r.get("escolhidos"), list) else []
    nomes = [opcoes[i] for i in sorted({int(i) for i in map(str, ids) if i.isdigit() and int(i) < len(opcoes)})]
    return f"{aberto['escolha']['responda']}: " + (", ".join(nomes) if nomes else "todos liberados (nenhum marcado)")
