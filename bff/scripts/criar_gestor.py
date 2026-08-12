"""Cria (ou promove) o primeiro gestor do painel.

O painel não tem cadastro aberto de propósito: quem administra as pontes tem acesso às
credenciais de serviço dos dois produtos. O primeiro acesso nasce por este script, na
máquina de quem opera; os demais podem ser criados por ele depois.

    python scripts/criar_gestor.py renan@empresa.com.br "Renan Moraes"

A senha é pedida no terminal — nunca por argumento, que ficaria no histórico do shell.
"""

import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import gerar_hash_senha
from app.models.user import User


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    email = sys.argv[1].strip().lower()
    nome = sys.argv[2] if len(sys.argv) > 2 else email.split("@")[0]

    senha = getpass.getpass("Senha: ")
    if len(senha) < 8:
        print("A senha precisa de pelo menos 8 caracteres.")
        return 1
    if senha != getpass.getpass("Confirme: "):
        print("As senhas não conferem.")
        return 1

    with SessionLocal() as db:
        usuario = db.scalar(select(User).where(User.email == email))
        if usuario is None:
            usuario = User(email=email, nome=nome)
            db.add(usuario)
            acao = "criado"
        else:
            acao = "atualizado"

        usuario.senha_hash = gerar_hash_senha(senha)
        usuario.is_gestor = True
        usuario.ativo = True
        db.commit()

    print(f"Gestor {acao}: {email}")
    print("Painel em http://localhost:8100/painel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
