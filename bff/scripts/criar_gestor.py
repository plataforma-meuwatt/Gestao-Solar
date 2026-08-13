"""Cria (ou atualiza) uma conta do Gestão Solar pela linha de comando.

O painel não tem cadastro aberto: quem administra alcança os tokens de serviço dos dois
produtos. O primeiro acesso nasce por este script, na máquina de quem opera; daí em diante
a tela de Equipe resolve.

    python scripts/criar_gestor.py renanmarquezini "Renan Marquezini"
    python scripts/criar_gestor.py joao.silva "João Silva" --atendimento
    python scripts/criar_gestor.py renan.marquezini "Renan Marquezini" --cliente \
        --email renan@splendoroem.com.br

O primeiro argumento é o APELIDO — é com ele que se entra, não com o e-mail. O e-mail é
opcional e serve para achar a conta da pessoa no meuWatt e no meuPlano.

Sem sinalizador, o perfil é administrador. A senha é pedida no terminal, nunca por
argumento — argumento fica no histórico do shell e no `ps` de quem estiver na máquina.
Para automação (semear um ambiente novo), `GS_SENHA` no ambiente substitui o prompt.
"""

import getpass
import os
import sys

from sqlalchemy import select

from app.core.apelido import ApelidoInvalido
from app.core.apelido import normalizar as normalizar_apelido
from app.core.db import SessionLocal
from app.core.security import gerar_hash_senha
from app.models.user import Perfil, User

_PERFIS = {
    "--cliente": Perfil.CLIENTE,
    "--atendimento": Perfil.ATENDIMENTO,
    "--administrador": Perfil.ADMINISTRADOR,
}


def _opcao(nome: str) -> str | None:
    """Lê `--chave valor` de sys.argv. Devolve None quando a opção não foi passada."""
    if nome not in sys.argv:
        return None
    posicao = sys.argv.index(nome) + 1
    return sys.argv[posicao] if posicao < len(sys.argv) else None


def _ler_senha() -> str | None:
    """Do ambiente quando semeando; do terminal quando é uma pessoa digitando."""
    do_ambiente = os.environ.get("GS_SENHA")
    if do_ambiente:
        return do_ambiente

    senha = getpass.getpass("Senha: ")
    if len(senha) < 8:
        print("A senha precisa de pelo menos 8 caracteres.")
        return None
    if senha != getpass.getpass("Confirme: "):
        print("As senhas não conferem.")
        return None
    return senha


def main() -> int:
    # `--email x` consome o próximo argumento; sem tirá-lo daqui, o valor do e-mail seria
    # lido como o nome da pessoa.
    email_informado = _opcao("--email")
    posicionais = [
        a
        for i, a in enumerate(sys.argv[1:], start=1)
        if not a.startswith("--") and sys.argv[i - 1] != "--email"
    ]
    if not posicionais:
        print(__doc__)
        return 2

    try:
        apelido = normalizar_apelido(posicionais[0])
    except ApelidoInvalido as exc:
        print(exc)
        return 1

    nome = posicionais[1] if len(posicionais) > 1 else apelido
    perfil = next(
        (p for sinal, p in _PERFIS.items() if sinal in sys.argv), Perfil.ADMINISTRADOR
    )

    senha = _ler_senha()
    if senha is None:
        return 1

    with SessionLocal() as db:
        usuario = db.scalar(select(User).where(User.apelido == apelido))
        if usuario is None:
            usuario = User(apelido=apelido, nome=nome)
            db.add(usuario)
            acao = "criada"
        else:
            usuario.nome = nome
            acao = "atualizada"

        if email_informado:
            usuario.email = email_informado.strip().lower()

        usuario.senha_hash = gerar_hash_senha(senha)
        usuario.perfil = perfil
        usuario.ativo = True
        # Quem nasce por aqui é quem opera o sistema, e já escolheu a própria senha —
        # mandá-lo trocar no primeiro acesso seria pedir para trocar o que acabou de criar.
        usuario.trocar_senha = False
        db.commit()

    print(f"Conta {acao}: {apelido} · {perfil.value}")
    if perfil is Perfil.CLIENTE:
        print("Entra pelo aplicativo (Expo), não pelo painel.")
    else:
        print("Painel em http://localhost:8100/painel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
