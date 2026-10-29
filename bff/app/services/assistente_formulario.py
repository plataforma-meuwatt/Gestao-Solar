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
#: o formulário de cadastro respondido de cada número, até o turno o usar (`cadastro_respondido`)
_CADASTROS: dict[str, dict] = {}


def valida(escolha) -> bool:
    return (isinstance(escolha, dict) and isinstance(escolha.get("opcoes"), list)
            and 0 < len(escolha["opcoes"]) <= MAX_OPCOES and bool(escolha.get("responda")))


def em_texto(escolha: dict) -> str:
    """Sem o formulário (gateway ou Meta recusou), a lista para responder digitando."""
    marcados = set(escolha.get("marcados") or [])
    return (f"{escolha.get('titulo') or 'Opções'} (✔ = marcado hoje):\n"
            + "\n".join(f"• {o}{' ✔' if o in marcados else ''}" for o in escolha["opcoes"])
            + "\nResponda com os que ficam.")


def _abrir(telefone: str, **aberto) -> str:
    token = secrets.token_urlsafe(12)
    agora = monotonic()
    for velho in [t for t, f in _ABERTOS.items() if agora - f["em"] >= VALIDADE_S]:
        del _ABERTOS[velho]
    _ABERTOS[telefone] = {"token": token, "em": agora, **aberto}
    return token


async def _enviar(telefone: str, texto: str, **corpo) -> bool:
    try:
        r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="formulario", texto=texto, **corpo)
    except whatsapp.GatewayIndisponivel:
        r = None
    if not (r or {}).get("ok"):
        del _ABERTOS[telefone]
        return False
    return True


async def mandar(telefone: str, escolha: dict) -> bool:
    token = _abrir(telefone, escolha=escolha)
    return await _enviar(telefone, "Toque em Marcar e deixe marcados só os que ficam.", formulario={
        "token": token, "titulo": str(escolha.get("titulo") or "Escolha")[:300],
        "opcoes": [str(o) for o in escolha["opcoes"]], "marcados": [str(m) for m in escolha.get("marcados") or []],
        "aviso": str(escolha.get("aviso") or "")[:300]})


async def mandar_cadastro(telefone: str, ja_sabe: dict) -> bool:
    """O formulário de CADASTRO (pedido do dono, 29/10/2026: "quando eu pedir cadastro, abrir um formulário com os
    campos necessários"), com o que a conversa já disse preenchido. Os papéis são os do cadastro do bot."""
    from app.services.assistente_cadastro import OPCOES_DO_FORMULARIO
    token = _abrir(telefone, cadastro=True)
    return await _enviar(telefone, "Toque em Preencher, confira os campos e toque em Enviar.", cadastro={
        "token": token, **{k: str(ja_sabe.get(k) or "")[:150] for k in ("nome", "email", "celular")},
        "papeis": {s: [{"id": i, "titulo": t} for i, t in ops] for s, ops in OPCOES_DO_FORMULARIO.items()},
        "escolhidos": {s: ja_sabe[s] for s in OPCOES_DO_FORMULARIO if ja_sabe.get(s)}})


def cadastro_respondido(telefone: str) -> dict | None:
    """Os campos do formulário de cadastro que esta mensagem trouxe (uma vez só)."""
    return _CADASTROS.pop(telefone, None)


def e_resposta(evento: dict) -> bool:
    return isinstance((evento.get("midia") or {}).get("formulario"), dict)


def texto_da_resposta(telefone: str, evento: dict) -> str | None:
    """O que a pessoa marcou, em palavras ("<responda>: A, B"). None: formulário vencido ou de outro envio."""
    r = evento["midia"]["formulario"]
    aberto = _ABERTOS.get(telefone)
    if aberto is None or monotonic() - aberto["em"] >= VALIDADE_S or r.get("flow_token") != aberto["token"]:
        return None
    del _ABERTOS[telefone]
    if aberto.get("cadastro"):
        from app.services.assistente_cadastro import NOMES_DOS_SISTEMAS, OPCOES_DO_FORMULARIO
        dados = {k: str(r.get(k) or "").strip() for k in ("nome", "email", "celular", *OPCOES_DO_FORMULARIO)}
        _CADASTROS[telefone] = dados
        rotulo = {s: dict(ops) for s, ops in OPCOES_DO_FORMULARIO.items()}
        return ("📝 Cadastro pelo formulário: " + " · ".join(
            [dados["nome"] or "(sem nome)", f"e-mail {dados['email'] or 'nenhum'}",
             f"celular {dados['celular'] or 'nenhum'}"]
            + [f"{NOMES_DOS_SISTEMAS[s]}: {rotulo[s].get(dados[s], 'Não cadastrar')}" for s in OPCOES_DO_FORMULARIO]))
    opcoes = aberto["escolha"]["opcoes"]
    ids = r.get("escolhidos") if isinstance(r.get("escolhidos"), list) else []
    nomes = [opcoes[i] for i in sorted({int(i) for i in map(str, ids) if i.isdigit() and int(i) < len(opcoes)})]
    return f"{aberto['escolha']['responda']}: " + (", ".join(nomes) if nomes else "todos liberados (nenhum marcado)")
