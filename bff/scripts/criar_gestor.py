"""Cria (ou promove) um gestor do painel.

O painel não tem cadastro aberto: quem administra as pontes alcança as credenciais de
serviço dos dois produtos. O primeiro acesso nasce por este script, na máquina de quem
opera; daí em diante a tela de Equipe resolve.

    python scripts/criar_gestor.py renan@empresa.com.br "Renan Moraes"
    python scripts/criar_gestor.py joao@empresa.com.br "João" --atendimento

Sem `--atendimento`, o perfil é administrador. A senha é pedida no terminal — nunca por
argumento, que ficaria no histórico do shell.
"""

import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import gerar_hash_senha
from app.models.user import Perfil, User


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not argumentos:
        print(__doc__)
        return 2

    email = argumentos[0].strip().lower()
    nome = argumentos[1] if len(argumentos) > 1 else email.split("@")[0]
    perfil = Perfil.ATENDIMENTO if "--atendimento" in sys.argv else Perfil.ADMINISTRADOR

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
        usuario.perfil = perfil
        usuario.ativo = True
        db.commit()

    print(f"{perfil.value.capitalize()} {acao}: {email}")
    print("Painel em http://localhost:8100/painel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
