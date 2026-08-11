"""Confere, contra os sistemas de verdade, que as credenciais e o escopo estão certos.

Não é teste automatizado: bate nas APIs reais e imprime o que voltou. É o que se roda ao
configurar um ambiente novo, ou quando alguma tela vem vazia e é preciso saber se o
problema é o BFF ou o upstream.

    python scripts/smoke.py                      # só as credenciais de serviço
    python scripts/smoke.py dono@empresa.com.br  # + o escopo desse proprietário

A senha do proprietário é pedida no terminal, nunca passada por argumento (argumento fica
no histórico do shell).
"""

import asyncio
import getpass
import sys

from app.clients.meuplano import MeuPlanoClient
from app.clients.meuwatt import MeuWattClient
from app.core.config import get_settings


def secao(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


async def checar_servico() -> None:
    secao("Credenciais de serviço")
    s = get_settings()

    print(f"meuWatt  → {s.meuwatt_api_url}")
    try:
        usinas = await MeuWattClient().usinas()
        print(f"  ok — {len(usinas)} usina(s) visíveis à conta de serviço")
        for u in usinas[:5]:
            print(f"    · {u.get('slug')} — {u.get('name')}")
    except Exception as e:  # noqa: BLE001 — aqui queremos ver qualquer falha, não tratar
        print(f"  FALHOU: {type(e).__name__}: {e}")

    print(f"\nmeuPlano → {s.meuplano_api_url}")
    try:
        await MeuPlanoClient()._token_servico()  # noqa: SLF001 — é exatamente o que se checa
        print("  ok — credencial aceita")
    except Exception as e:  # noqa: BLE001
        print(f"  FALHOU: {type(e).__name__}: {e}")


async def checar_proprietario(email: str) -> None:
    secao(f"Escopo de {email}")
    senha = getpass.getpass("Senha: ")

    mw = await MeuWattClient().autenticar(email, senha)
    if mw:
        usinas = await MeuWattClient().usinas(token=mw["access_token"])
        print(f"meuWatt  → autenticado. {len(usinas)} usina(s):")
        for u in usinas:
            print(f"    · {u.get('slug')} — {u.get('name')}")
    else:
        print("meuWatt  → credencial recusada (ou o usuário não existe lá)")

    mp = await MeuPlanoClient().autenticar(email, senha)
    if mp:
        sessao = await MeuPlanoClient().sessao(token=mp["access_token"])
        print(f"\nmeuPlano → autenticado. nivel_acesso = {sessao.get('nivel_acesso')}")
        print(f"    organizações: {sessao.get('owners') or sessao.get('organizacoes')}")
    else:
        print("\nmeuPlano → credencial recusada (ou o usuário não existe lá)")

    print(
        "\nConfira: a lista acima é EXATAMENTE o que este usuário deve ver no app."
        "\nUsina a mais aqui = vazamento; a menos = gs_plant_link incompleto."
    )


async def principal() -> None:
    await checar_servico()
    if len(sys.argv) > 1:
        await checar_proprietario(sys.argv[1])


if __name__ == "__main__":
    asyncio.run(principal())
