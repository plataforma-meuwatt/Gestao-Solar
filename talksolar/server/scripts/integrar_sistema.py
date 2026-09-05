# -*- coding: utf-8 -*-
"""Cadastra (ou atualiza) um SISTEMA integrado. É o único cadastro do Talk Solar.

    python scripts/integrar_sistema.py meuplano "meuPlano" https://meuplano.exemplo/api/v1/talk

Cria o registro, GERA o segredo (ou reusa o que já existe) e imprime o que o outro lado precisa
guardar. Idempotente: rodar de novo com a mesma slug atualiza as URLs sem trocar o segredo —
trocar o segredo por engano derrubaria a integração inteira em silêncio.

Passar `--novo-segredo` força a troca (para quando ele vaza), e aí o outro lado precisa
atualizar no mesmo dia.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import sessao_direta          # noqa: E402
from app.models import App                    # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Integra um sistema ao Talk Solar")
    p.add_argument("slug", help="meuplano | meuwatt | gestaosolar")
    p.add_argument("nome", help='nome que aparece para o usuário, ex.: "meuPlano"')
    p.add_argument("base", help="raiz dos endpoints de integração do sistema")
    p.add_argument("--identidade", default="/identidade")
    p.add_argument("--busca", default="/refs/buscar")
    p.add_argument("--label", default="/refs/label")
    p.add_argument("--webhook", default=None, help="URL que RECEBE os avisos da Talk Solar")
    p.add_argument("--novo-segredo", action="store_true")
    a = p.parse_args()

    base = a.base.rstrip("/")
    db = sessao_direta()
    try:
        app = db.query(App).filter(App.slug == a.slug).first()
        criou = app is None
        if criou:
            app = App(slug=a.slug, secret=secrets.token_urlsafe(36))
            db.add(app)
        elif a.novo_segredo:
            app.secret = secrets.token_urlsafe(36)
        app.nome = a.nome
        app.identidade_url = base + a.identidade
        app.refs_busca_url = base + a.busca
        app.refs_label_url = base + a.label
        app.webhook_url = a.webhook
        app.ativo = True
        db.commit()

        print(f"\n  {'CRIADO' if criou else 'ATUALIZADO'}: {app.nome} ({app.slug})\n")
        print(f"  identidade : {app.identidade_url}")
        print(f"  busca      : {app.refs_busca_url}")
        print(f"  label      : {app.refs_label_url}")
        print(f"  webhook    : {app.webhook_url or '(não recebe avisos)'}")
        print("\n  ---------------------------------------------------------------")
        print("  SEGREDO COMPARTILHADO (guarde no sistema, como variável de ambiente):")
        print(f"\n      TALK_SECRET={app.secret}\n")
        print("  Ele faz as duas pontas: autentica a Talk Solar quando ela chama o sistema")
        print("  (cabeçalho X-Talk-Secret) e assina os webhooks que ela envia.")
        print("  ---------------------------------------------------------------\n")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
