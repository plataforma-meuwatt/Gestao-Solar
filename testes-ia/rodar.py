"""Testa o bot do WhatsApp contra a IA REAL: a mesma chave, o mesmo modelo e o mesmo banco da produção.

Roda DENTRO do contêiner da API, chamado por `testar.sh`, com o `bff/app` da pasta de quem chama: testa o prompt e as
ferramentas que estão NESTA pasta (o que vai subir no próximo push), sem publicar nada. Nada vai ao WhatsApp nem ao Log
do bot. Ação para no resumo (o Sim só existe no WhatsApp) e a memória dela morre com este processo.

  escolha (padrão)  só a 1ª volta: que ferramenta a IA chama e com que dados. Nada roda.
  --inteira         a resposta inteira, como chegaria à pessoa. As LEITURAS rodam de verdade, com o token dela.
  --banco           o banco.json inteiro (só a escolha); termina com erro se alguma pergunta errar.
  --colher          os casos reais do Log do bot que ainda não estão no banco, para alimentá-lo.
"""
import argparse
import asyncio
import base64
import json
import os
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.conversa_whatsapp import RegistroBot
from app.models.user import User
from app.services import assistente as a, assistente_geracao as ger

AQUI = os.path.dirname(os.path.abspath(__file__))
PARALELO = 5


def _conta(db, apelido: str) -> User:
    u = db.scalar(select(User).where(User.apelido == apelido))
    if u is None:
        sys.exit(f"Conta '{apelido}' não existe no GS.")
    return u


def _limpo(texto: str, valores=(), credencial: bool = False) -> str:
    """O que aparece no terminal: sem senha, como no Log do bot (mas o texto fica, para ver se a IA recusou)."""
    return a._sem_segredos(texto or "", valores, credencial or a._e_de_credencial(texto or ""),
                           a.publicos_do_turno(texto or ""))


async def _turno(apelido: str, frase: str, inteira: bool) -> dict:
    db = SessionLocal()
    try:
        user = _conta(db, apelido)
        ctx = ger.Contexto(db=db, user=user, telefone=user.telefone or "", pedido=frase)
        await ger.preparar(ctx)
        if inteira:
            texto = await a.responder(ctx, [{"role": "user", "content": frase}])
            if ctx.proposta is not None:
                texto += "\n\n" + a.helper.bloco_da_proposta(ctx.proposta)
            return {"ferramentas": ctx.ferramentas,
                    "texto": _limpo(texto, [*ctx.segredos, *ctx.digitados], ctx.credencial)}
        msgs = [{"role": "system", "content": a._sistema(ctx)}, {"role": "user", "content": frase}]
        ferramentas = [a.FERRAMENTAS[n][1] for n in a.permitidas(user)]
        db.commit()                                        # solta a conexão enquanto a IA pensa
        m = await a._llm(msgs, ferramentas)
        chamadas = [{"nome": c["function"]["name"], "dados": _limpo(c["function"].get("arguments") or "")}
                    for c in m.get("tool_calls") or []]
        return {"ferramentas": [c["nome"] for c in chamadas], "chamadas": chamadas,
                "texto": _limpo(m.get("content") or "")}
    except Exception as e:                                  # noqa: BLE001 — uma pergunta não derruba as outras
        return {"ferramentas": [], "texto": "", "erro": f"{type(e).__name__}: {str(e)[:300]}"}
    finally:
        db.close()


async def _varias(casos: list[dict], inteira: bool, vezes: int) -> list[tuple[dict, dict]]:
    sem = asyncio.Semaphore(PARALELO)

    async def um(caso):
        async with sem:
            return caso, await _turno(caso.get("como", "renan.marquezini"), caso["frase"], inteira)
    return await asyncio.gather(*(um(c) for c in casos for _ in range(vezes)))


def _passou(caso: dict, r: dict) -> bool:
    """`espera` vazio = responder sem ferramenta; senão, a 1ª volta chama ao menos uma das esperadas
    (`ou_sem_ferramenta`: responder direto também vale)."""
    if r.get("erro"):
        return False
    if not r["ferramentas"]:
        return not caso["espera"] or caso.get("ou_sem_ferramenta", False)
    return bool(set(r["ferramentas"]) & set(caso["espera"]))


def _colher(banco: list[dict]) -> None:
    ja = {c["origem"] for c in banco}
    db = SessionLocal()
    try:
        linhas = db.execute(select(RegistroBot, User.apelido).join(User, User.id == RegistroBot.gs_user_id)
                            .order_by(RegistroBot.id)).all()
    finally:
        db.close()
    novos = 0
    for r, apelido in linhas:
        if f"log #{r.id}" in ja or not r.pergunta or (r.ferramentas or "") == "confirmacao":
            continue
        novos += 1
        print(json.dumps({"origem": f"log #{r.id}", "em": f"{r.em:%d/%m %H:%M}", "como": apelido,
                          "resultado": r.resultado, "o_bot_chamou": (r.ferramentas or "").split(",") if r.ferramentas
                          else [], "frase": r.pergunta}, ensure_ascii=False))
    print(f"# {novos} caso(s) real(is) fora do banco.", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("frases", nargs="*")
    p.add_argument("--inteira", action="store_true")
    p.add_argument("--banco", action="store_true")
    p.add_argument("--colher", action="store_true")
    p.add_argument("--como", default="renan.marquezini")
    p.add_argument("--vezes", type=int, default=1)
    o = p.parse_args(json.loads(base64.b64decode(sys.argv[1])) if len(sys.argv) > 1 else [])
    with open(os.path.join(AQUI, "banco.json"), encoding="utf-8") as f:
        banco = json.load(f)
    if o.colher:
        return _colher(banco)
    if o.banco:
        casos = banco
    elif o.frases:
        casos = [{"frase": fr, "como": o.como} for fr in o.frases]
    else:
        sys.exit("Passe uma ou mais frases, --banco ou --colher.")
    print(f"# modelo {a.get_settings().llm_model}", file=sys.stderr)
    erros = 0
    for caso, r in asyncio.run(_varias(casos, o.inteira, o.vezes)):
        if "espera" in caso:
            ok = _passou(caso, r)
            erros += not ok
            print(f"{'OK  ' if ok else 'ERRO'} | {caso['frase'][:70]} | esperado {caso['espera'] or 'sem ferramenta'}"
                  f" | chamou {r['ferramentas'] or 'nada'}" + ("" if ok else f" | {r.get('erro') or r['texto'][:200]}"))
            continue
        print(f"--- {caso['frase']}\nchamou: {r['ferramentas'] or 'nada'}")
        for c in r.get("chamadas", []):
            print(f"  {c['nome']}: {c['dados'][:400]}")
        if r.get("erro") or r["texto"]:
            print(r.get("erro") or r["texto"])
    if o.banco:
        total = len(casos) * o.vezes
        print(f"\n{total - erros}/{total} certas" + (f" · {erros} ERRADA(S)" if erros else ""))
        sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
