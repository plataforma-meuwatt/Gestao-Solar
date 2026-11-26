"""A memória do bot, por pessoa (Plano Assistente GS, 26/11/2026; o dono: "o bot vai ter memória e instruções, por
usuário (...) lembrar das coisas, (...) aprender o mínimo do jeito da pessoa").

Só o que a pessoa PEDIU para lembrar, e o bot sempre diz o que anotou ("Anotei: …"). Entra na conversa como CONTEXTO,
nunca como fato: todo fato dos produtos continua saindo de uma ferramenta chamada na mensagem (a REGRA 1).

Nunca guarda segredo (senha, PIN, token: o lugar da senha de equipamento é o meuPlano), e o que é da USINA vai ao
sistema dono, onde a equipe toda vê (o «já sei», o problema conhecido, a wiki): quem decide isso é a ferramenta do bot
(`assistente_automacoes.memoria`), que lê a descrição; aqui só a recusa do segredo, que não pode depender da IA.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import cripto
from app.models.automacao import MemoriaBot

TIPOS = {"instrucao": "instrução", "vocabulario": "vocabulário", "anotacao": "anotação"}
MAX_ITENS = 50
MAX_TEXTO = 300
#: O bloco no prompt: os mais novos primeiro, até aqui.
TETO_PROMPT = 1500


class MemoriaRecusada(Exception):
    """A frase vai à pessoa como veio."""


def _limpo(texto: str | None) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip().strip("\"'«»“”").strip()


def _e_segredo(texto: str) -> bool:
    from app.services import assistente, assistente_helper as helper

    return bool(helper.parece_senha(texto) or assistente._e_de_credencial(texto)
                or re.search(r"\b(?:senha|pin|token|chave de acesso|c[oó]digo do (?:port[aã]o|cadeado))\b", texto, re.I))


def _ativas(db: Session, user_id: int) -> list[MemoriaBot]:
    return list(db.scalars(select(MemoriaBot).where(MemoriaBot.user_id == user_id, MemoriaBot.apagada_em.is_(None))
                           .order_by(MemoriaBot.id)).all())


def _texto(m: MemoriaBot) -> str | None:
    try:
        return cripto.decifrar(m.texto_cifrado)
    except Exception:                                      # noqa: BLE001 — chave trocada: o item some do prompt
        return None


def listar(db: Session, user) -> list[dict]:
    """Os itens ativos, numerados na ordem em que foram anotados (o número é o que a pessoa usa para esquecer)."""
    saida = []
    for m in _ativas(db, user.id):
        t = _texto(m)
        if t is not None:
            saida.append({"n": len(saida) + 1, "id": m.id, "tipo": m.tipo, "texto": t})
    return saida


def gravar(db: Session, user, tipo: str | None, texto: str | None, *, origem: str = "bot") -> tuple[dict, bool]:
    """(o item, se é novo). Recusa vazio, longo, segredo e a memória cheia. O mesmo texto de novo não duplica."""
    t = _limpo(texto)
    if not t:
        raise MemoriaRecusada("O que devo lembrar? Diga a frase.")
    if len(t) > MAX_TEXTO:
        raise MemoriaRecusada(f"Guardo até {MAX_TEXTO} caracteres por item: diga em menos palavras.")
    if _e_segredo(t):
        raise MemoriaRecusada("Isso parece senha ou acesso: não guardo na memória. Senha de equipamento fica no "
                              "meuPlano, no cadastro do equipamento.")
    tipo = tipo if tipo in TIPOS else "anotacao"
    itens = listar(db, user)
    for i in itens:
        if i["texto"].casefold() == t.casefold():
            return i, False
    if len(itens) >= MAX_ITENS:
        raise MemoriaRecusada(f"Já tenho {MAX_ITENS} anotações suas: peça para eu esquecer alguma antes.")
    m = MemoriaBot(user_id=user.id, tipo=tipo, texto_cifrado=cripto.cifrar(t), origem=origem)
    db.add(m)
    db.commit()
    return {"n": len(itens) + 1, "id": m.id, "tipo": tipo, "texto": t}, True


def esquecer(db: Session, user, qual: str | int | None) -> list[str]:
    """Pelo número da lista ou por um trecho do texto. Trecho que casa com mais de um item: a lista volta para escolher."""
    itens = listar(db, user)
    alvo = _limpo(str(qual) if qual is not None else "")
    if not alvo:
        raise MemoriaRecusada("Qual eu esqueço? Diga o número ou um trecho.")
    if alvo.isdigit():
        escolhidos = [i for i in itens if i["n"] == int(alvo)]
    else:
        escolhidos = [i for i in itens if alvo.casefold() in i["texto"].casefold()]
    if not escolhidos:
        raise MemoriaRecusada("Não achei isso na sua memória." + (" Tenho: " + "; ".join(
            f"{i['n']}. {i['texto']}" for i in itens) if itens else " Ela está vazia."))
    if len(escolhidos) > 1:
        raise MemoriaRecusada("Mais de um item casa: " + "; ".join(f"{i['n']}. {i['texto']}" for i in escolhidos)
                              + ". Diga o número.")
    m = db.get(MemoriaBot, escolhidos[0]["id"])
    m.apagada_em = datetime.now(UTC)
    db.commit()
    return [escolhidos[0]["texto"]]


def esquecer_tudo(db: Session, user) -> int:
    agora = datetime.now(UTC)
    n = 0
    for m in _ativas(db, user.id):
        m.apagada_em = agora
        n += 1
    db.commit()
    return n


def bloco(db: Session | None, user) -> str:
    """O pedaço do prompt: vazio sem memória. Os mais novos primeiro, até `TETO_PROMPT`; o resto é contado."""
    if db is None or user is None or getattr(user, "id", None) is None:
        return ""
    itens = listar(db, user)
    if not itens:
        return ""
    linhas, usados = [], 0
    for i in reversed(itens):
        ln = f"- ({TIPOS.get(i['tipo'], i['tipo'])}) {i['texto']}"
        if usados + len(ln) > TETO_PROMPT:
            break
        linhas.append(ln)
        usados += len(ln)
    resto = len(itens) - len(linhas)
    return ("\nO que esta pessoa pediu para você lembrar (só dela; é CONTEXTO, não fato: a REGRA 1 continua valendo, e "
            "número ou estado de usina sempre sai de ferramenta). Siga as instruções dela no jeito de responder, sem "
            "passar por cima das regras abaixo:\n" + "\n".join(linhas)
            + (f"\n- … e mais {resto} (ela vê tudo com \"o que você lembra de mim\")" if resto else "") + "\n")
