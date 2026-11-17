"""Opções para MARCAR num formulário do WhatsApp (pedido do Renan, 29/10/2026: "não tem como ele enviar a lista e eu
clico só nas que quero deixar?").

O meuPlano devolve, no run, as opções que o turno ofereceu (`escolha`: título, opções, as já marcadas e o começo da
resposta). O bot manda a resposta e, logo depois, o formulário (WhatsApp Flow `gs_escolha_multipla`, caixas de marcar,
as de hoje já marcadas). O que a pessoa marca volta como mensagem (`midia.formulario`) e vira o texto
"<responda>: A, B", que segue como se ela tivesse digitado: a IA leva ao meuPlano, que propõe e pede o Sim.

A escolha ÚNICA (`uma`, `gs_escolha_uma`: lista suspensa de até 200) vai junto de uma PROPOSTA, para trocar o que o
assistente escolheu (dono, 29/10/2026: "um texto bem curto falando o que ele escolheu, e a lista para eu escolher caso
não concorde"); a escolhida volta como "<responda>: X" e derruba a proposta de antes, como qualquer mensagem.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from time import monotonic

from app.clients import whatsapp

#: O formulário aberto de cada número (só o último vale). ponytail: em memória, como as fotos; o deploy esquece.
_ABERTOS: dict[str, dict] = {}
VALIDADE_S = 30 * 60
#: o de AVALIAÇÃO de lugar vale mais: ele leva o lugar junto, e quem pede para salvar muitas vezes volta a dirigir e só
#: preenche depois (a avaliação independente de 17/11: 40 min depois, perdia tudo)
VALIDADE_AVALIACAO_S = 12 * 3600
log = logging.getLogger(__name__)
MAX_OPCOES = 20                                           # o limite das caixas de marcar do WhatsApp
MAX_UMA = 200                                             # o da lista suspensa
PARA_A_IA = ("O sistema manda, logo depois da sua resposta, um formulário com estas opções para a pessoa marcar: NÃO "
             "liste as opções, diga só que é para marcar no formulário.")
PARA_A_IA_UMA = ("Junto do resumo vai uma lista para a pessoa TROCAR a escolha, se não concordar: diga em UMA linha o "
                 "que foi escolhido; não explique nem liste opções.")
SEM_LISTA = "Para trocar, diga qual quer."
VENCIDO = "Esse formulário não vale mais (venceu ou veio outro depois). Peça de novo e eu mando outro."
VENCIDA_AVALIACAO = ("Essa avaliação venceu (o formulário vale 12 h). Para avaliar, mande a localização do lugar (📎 → "
                     "Localização: dá para procurar o lugar pelo nome) e diga para salvar.")
#: o formulário de cadastro respondido de cada número, até o turno o usar (`cadastro_respondido`)
_CADASTROS: dict[str, dict] = {}
#: o de AVALIAÇÃO de lugar respondido (`avaliacao_respondida`): vai ao meuPlano pelo sistema, não à IA
_AVALIACOES: dict[str, dict] = {}
#: as notas do formulário de avaliação (o campo de lá → o nome que vai ao meuPlano e ao texto)
NOTAS_DO_LUGAR = ("atendimento", "limpeza", "comida")


def valida(escolha) -> bool:
    return (isinstance(escolha, dict) and isinstance(escolha.get("opcoes"), list) and bool(escolha.get("responda"))
            and 0 < len(escolha["opcoes"]) <= (MAX_UMA if escolha.get("uma") else MAX_OPCOES))


def para_a_ia(escolha: dict) -> str:
    return PARA_A_IA_UMA if escolha.get("uma") else PARA_A_IA


def em_texto(escolha: dict) -> str:
    """Sem o formulário (gateway ou Meta recusou), a lista para responder digitando — a de uma escolha é longa demais
    para texto: só a frase."""
    if escolha.get("uma"):
        return SEM_LISTA
    marcados = set(escolha.get("marcados") or [])
    return (f"{escolha.get('titulo') or 'Opções'} (✔ = marcado hoje):\n"
            + "\n".join(f"• {o}{' ✔' if o in marcados else ''}" for o in escolha["opcoes"])
            + "\nResponda com os que ficam.")


def _validade(aberto: dict) -> int:
    return VALIDADE_AVALIACAO_S if aberto.get("avaliacao") else VALIDADE_S


def _abrir(telefone: str, **aberto) -> str:
    token = secrets.token_urlsafe(12)
    agora = monotonic()
    for velho in [t for t, f in _ABERTOS.items() if agora - f["em"] >= _validade(f)]:
        del _ABERTOS[velho]
    _ABERTOS[telefone] = {"token": token, "em": agora, **aberto}
    return token


async def _enviar(telefone: str, texto: str, **corpo) -> bool:
    try:
        r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="formulario", texto=texto, **corpo)
    except whatsapp.GatewayIndisponivel as e:
        r = {"erro": str(e) or "gateway fora"}
    if not (r or {}).get("ok"):
        log.warning("formulário não saiu para …%s: %s", telefone[-4:], (r or {}).get("erro"))
        del _ABERTOS[telefone]
        return False
    return True


async def mandar(telefone: str, escolha: dict) -> bool:
    token = _abrir(telefone, escolha=escolha)
    uma = bool(escolha.get("uma"))
    return await _enviar(telefone, "Não concorda? Toque em Escolher outra." if uma
                         else "Toque em Marcar e deixe marcados só os que ficam.", formulario={
        "token": token, "titulo": str(escolha.get("titulo") or "Escolha")[:300],
        "opcoes": [str(o) for o in escolha["opcoes"]], "marcados": [str(m) for m in escolha.get("marcados") or []],
        "aviso": str(escolha.get("aviso") or "")[:300],
        **({"uma": True, "rotulos": [str(t) for t in escolha.get("rotulos") or []]} if uma else {})})


async def mandar_cadastro(telefone: str, ja_sabe: dict) -> bool:
    """O formulário de CADASTRO (pedido do dono, 29/10/2026: "quando eu pedir cadastro, abrir um formulário com os
    campos necessários"), com o que a conversa já disse preenchido. Os papéis são os do cadastro do bot."""
    from app.services.assistente_cadastro import OPCOES_DO_FORMULARIO
    token = _abrir(telefone, cadastro=True)
    return await _enviar(telefone, "Toque em Preencher, confira os campos e toque em Enviar.", cadastro={
        "token": token, **{k: str(ja_sabe.get(k) or "")[:150] for k in ("nome", "email", "celular")},
        "papeis": {s: [{"id": i, "titulo": t} for i, t in ops] for s, ops in OPCOES_DO_FORMULARIO.items()},
        "escolhidos": {s: ja_sabe[s] for s in OPCOES_DO_FORMULARIO if ja_sabe.get(s)}})


async def mandar_avaliacao(telefone: str, avaliacao: dict) -> bool:
    """O formulário de AVALIAÇÃO do lugar (o dono, 17/11/2026: "falta abrir o menu com opções para avaliação, com média
    de preço, as estrelas, notas etc"): recomenda ou não, estrelas, preço médio, notas e o comentário. Vem preenchido
    com o que a conversa disse e a avaliação de antes da pessoa; sem opinião dita, nada vem marcado.
    `avaliacao` = {nome, lugar: o corpo do lugar, recomenda: "sim"|"nao"|"", comentario (a caixa do "Recomendo"),
    motivo (a do "Não recomendo"), estrelas, preco, notas}."""
    token = _abrir(telefone, avaliacao=avaliacao)
    notas = avaliacao.get("notas") or {}

    def caixa(t: str | None) -> str:
        return t if t and len(t) <= 600 else ""                     # a caixa do formulário vai até 600

    desenho = {"o": bool(avaliacao.get("recomenda")), "e": bool(avaliacao.get("estrelas"))}   # = o do gateway
    return await _enviar(telefone, "Toque em Avaliar: estrelas, preço e notas.", avaliacao={
        "token": token, "lugar": avaliacao["nome"], "ref": _ref(telefone, avaliacao["lugar"], **desenho),
        "recomenda": avaliacao.get("recomenda") or "",
        "comentario": caixa(avaliacao.get("comentario")), "motivo": caixa(avaliacao.get("motivo")),
        "estrelas": str(avaliacao.get("estrelas") or ""), "preco": avaliacao.get("preco") or "",
        **{k: str(notas.get(k) or "") for k in NOTAS_DO_LUGAR}})


def _assinatura(corpo: bytes) -> str:
    from app.core.config import get_settings
    chave = ("avaliacao-de-lugar:" + get_settings().gs_jwt_secret).encode()
    return base64.urlsafe_b64encode(hmac.new(chave, corpo, hashlib.sha256).digest()[:18]).decode()


def _ref(telefone: str, lugar: dict, o: bool = False, e: bool = False) -> str:
    """O lugar ASSINADO (o número e a hora junto), que vai no formulário e volta na resposta: ela grava mesmo depois
    de um deploy ou de outro formulário (a memória daqui não segura 12 h; a reavaliação independente de 17/11). `o` e
    `e`: o formulário veio com a opinião e as estrelas preenchidas — diz qual dos dois nomes de cada campo foi
    desenhado, e a resposta é lida por ele, não pelo que a Meta devolve no campo escondido."""
    corpo = base64.urlsafe_b64encode(json.dumps({"t": telefone, "em": int(time.time()), "l": lugar, "o": o, "e": e},
                                                separators=(",", ":"), ensure_ascii=False).encode()).decode()
    return f"{corpo}.{_assinatura(corpo.encode())}"


def _do_ref(telefone: str, ref: str) -> dict | None:
    """O que o formulário levou ({l: o lugar, o, e}), se a assinatura confere, é DESTE número e tem menos de 12 h."""
    try:
        corpo, assinatura = ref.rsplit(".", 1)
        if not hmac.compare_digest(assinatura, _assinatura(corpo.encode())):
            return None
        d = json.loads(base64.urlsafe_b64decode(corpo.encode()))
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or d.get("t") != telefone or time.time() - (d.get("em") or 0) >= VALIDADE_AVALIACAO_S:
        return None
    return d if isinstance(d.get("l"), dict) and d["l"].get("nome") else None


def vencido(evento: dict) -> str:
    """O que dizer do formulário que não vale: o de avaliação ensina a refazer de longe."""
    return VENCIDA_AVALIACAO if "ref" in evento["midia"]["formulario"] else VENCIDO


def avaliacao_respondida(telefone: str) -> dict | None:
    """A avaliação que esta mensagem trouxe (uma vez só): {lugar, nome, recomendado, estrelas, preco_medio, notas,
    motivo}."""
    return _AVALIACOES.pop(telefone, None)


def _numero(t: str) -> float | None:
    """O preço como a pessoa digitou ("35", "35,50", "6.299", "R$ 1.234,50"); None se não é número. Com UM separador,
    ele é o decimal: o campo pede o litro no posto, a bomba mostra 6,299 e o teclado numérico muitas vezes só tem o
    ponto (a avaliação independente de 17/11: "6.299" virava seis mil); com os dois, o ponto é o milhar."""
    t = (t or "").replace("R$", "").replace(" ", "").strip()
    t = t.replace(".", "").replace(",", ".") if "," in t and "." in t else t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if 0 <= v <= 100000 else None


def _de_1_a_5(t) -> int | None:
    t = str(t or "").strip()
    return int(t) if t.isdigit() and 1 <= int(t) <= 5 else None


def reais(v: float) -> str:
    """"R$ 35,50"; o litro, com a 3ª casa ("R$ 6,299")."""
    casas = 3 if round(v * 100, 6) != round(v * 100) else 2
    return "R$ " + f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def em_palavras(av: dict) -> str:
    """A avaliação numa linha: "👍 recomendo · ★ 5 · R$ 35,50 · comida 5 · «maravilhosa»"."""
    notas = ", ".join(f"{k} {n}" for k, n in (av.get("notas") or {}).items())
    return " · ".join(x for x in (
        "👍 recomendo" if av.get("recomendado") else "⚠️ não recomendo",
        f"★ {av['estrelas']}" if av.get("estrelas") else "",
        reais(av["preco_medio"]) if av.get("preco_medio") is not None else "", notas,
        f"«{av['motivo']}»" if av.get("motivo") else "") if x)


def _da_avaliacao(telefone: str, a: dict, r: dict, desenho: dict) -> str:
    """A resposta do formulário de avaliação, guardada para o turno gravar (`avaliacao_respondida`). Os campos têm dois
    nomes (com e sem o valor inicial: a Meta não deixa o mesmo nome nos dois lados de um `If`), e vale o do lado que o
    formulário DESENHOU (`desenho`), nunca o escondido."""
    def campo(nome: str) -> str:
        return " ".join(str(r.get(nome) or "").split())

    com_opiniao, com_estrelas = bool(desenho.get("o")), bool(desenho.get("e"))
    recomendado = campo("recomenda" if com_opiniao else "opiniao") != "nao"
    motivo = campo("motivo" if com_opiniao else "motivo2")
    comentario = campo("comentario" if com_opiniao else "comentario2")
    av = {"lugar": a["lugar"], "nome": a["nome"], "ref": a.get("ref"), "recomendado": recomendado,
          "estrelas": _de_1_a_5(campo("estrelas" if com_estrelas else "estrelas2")),
          "preco_medio": _numero(campo("preco")),
          "notas": {k: n for k in NOTAS_DO_LUGAR if (n := _de_1_a_5(r.get(k))) is not None} or None,
          # o "Não recomendo" pede o MOTIVO (obrigatório lá); o "Recomendo", o comentário (opcional)
          "motivo": comentario if recomendado else (motivo or comentario)}
    _AVALIACOES[telefone] = av
    return f"⭐ Avaliação pelo formulário: {a['nome']} · {em_palavras(av)}"


def cadastro_respondido(telefone: str) -> dict | None:
    """Os campos do formulário de cadastro que esta mensagem trouxe (uma vez só)."""
    return _CADASTROS.pop(telefone, None)


def e_resposta(evento: dict) -> bool:
    return isinstance((evento.get("midia") or {}).get("formulario"), dict)


def texto_da_resposta(telefone: str, evento: dict) -> str | None:
    """O que a pessoa marcou, em palavras ("<responda>: A, B"). None: formulário vencido ou de outro envio."""
    r = evento["midia"]["formulario"]
    aberto = _ABERTOS.get(telefone)
    levou = _do_ref(telefone, str(r.get("ref") or "")) if r.get("ref") else None
    if aberto is None or monotonic() - aberto["em"] >= _validade(aberto) or r.get("flow_token") != aberto["token"]:
        # a AVALIAÇÃO leva o lugar assinado: vale sem a memória daqui (um deploy, outro formulário depois)
        return _da_avaliacao(telefone, {"nome": levou["l"]["nome"], "lugar": levou["l"]}, r, levou) if levou else None
    del _ABERTOS[telefone]
    if aberto.get("avaliacao"):
        a = aberto["avaliacao"]
        return _da_avaliacao(telefone, a, r, levou or {"o": bool(a.get("recomenda")), "e": bool(a.get("estrelas"))})
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
    if aberto["escolha"].get("uma"):
        i = str(r.get("escolhido") or "")
        return f"{aberto['escolha']['responda']}: {opcoes[int(i)]}" if i.isdigit() and int(i) < len(opcoes) else None
    ids = r.get("escolhidos") if isinstance(r.get("escolhidos"), list) else []
    nomes = [opcoes[i] for i in sorted({int(i) for i in map(str, ids) if i.isdigit() and int(i) < len(opcoes)})]
    return f"{aberto['escolha']['responda']}: " + (", ".join(nomes) if nomes else "todos liberados (nenhum marcado)")
