"""Trocar de papel sem sair e entrar de novo.

Uma conta é um PAPEL. A mesma pessoa tem uma conta para cada um — gestor da plataforma,
gerente de uma empresa de O&M, dono de usina — e é assim que a separação se sustenta: cada
sessão vale para um portão só, e a tela consegue dizer, o tempo todo, em qual você está.

O que faltava era o conforto: sair, lembrar do outro apelido, digitar de novo. Este módulo
resolve isso e **só isso**. Ele não funde papéis, não soma permissões e não é consultado
por nenhuma guarda.

## A regra que não pode ser "simplificada"

**Descer é livre; subir para a plataforma pede a senha.**

Provada a senha de uma conta, trocar para uma irmã de empresa ou de cliente é um clique —
são papéis de alcance menor ou lateral, e quem está ali já provou ser a pessoa. Trocar para
uma conta de PLATAFORMA (administrador ou atendimento) exige a senha daquela conta, sempre.

Sem essa exceção, o roubo de uma sessão do aplicativo — o celular emprestado, o token
copiado de um cache — viraria uma sessão de administrador sem que o ladrão precisasse
saber nenhuma senha. O conforto de não redigitar não vale o preço de transformar a conta
mais fraca na chave da mais forte.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    conferir_senha,
    criar_token,
    criar_token_empresa,
    criar_token_painel,
    criar_token_tecnico,
)
from app.models.empresa import Empresa
from app.models.pessoa import Pessoa
from app.models.user import Perfil, User

#: Os perfis que abrem o painel da plataforma. Trocar PARA um deles pede a senha.
DA_PLATAFORMA = (Perfil.ADMINISTRADOR, Perfil.ATENDIMENTO)


def contas_da_pessoa(db: Session, usuario: User) -> list[User]:
    """As contas ativas do mesmo humano, incluindo a atual, em ordem estável.

    Sem `pessoa_id` a resposta é só a conta atual — que é o estado de quem nunca agrupou
    nada, e o certo: inventar irmãs por semelhança de nome ou de e-mail seria adivinhar
    identidade, e errar aqui abre a conta de alguém para outra pessoa.
    """
    if usuario.pessoa_id is None:
        return [usuario]
    return list(
        db.scalars(
            select(User)
            .where(User.pessoa_id == usuario.pessoa_id, User.ativo)
            .order_by(User.id)
        ).all()
    )


def escopo_do_perfil(perfil: Perfil) -> str:
    """Em qual portão esta conta entra. É o que a tela usa para saber para onde ir."""
    if perfil in DA_PLATAFORMA:
        return "painel"
    if perfil is Perfil.GESTOR_EMPRESA:
        return "empresa"
    if perfil is Perfil.TECNICO:
        return "tecnico"
    return "cliente"


def emitir(usuario: User) -> tuple[str, object]:
    """O token do portão desta conta. Um lugar só, para nenhum chamador escolher errado."""
    escopo = escopo_do_perfil(usuario.perfil)
    if escopo == "painel":
        return criar_token_painel(usuario.id)
    if escopo == "empresa":
        return criar_token_empresa(usuario.id)
    if escopo == "tecnico":
        return criar_token_tecnico(usuario.id)
    return criar_token(usuario.id)


def nome_da_empresa(db: Session, usuario: User) -> str | None:
    if usuario.empresa_id is None:
        return None
    empresa = db.get(Empresa, usuario.empresa_id)
    return empresa.nome if empresa else None


def trocar(db: Session, atual: User, apelido: str, senha: str | None) -> User:
    """A conta de destino, validada. Levanta `HTTPException` quando a troca não vale.

    Três recusas, e cada uma tem um motivo próprio:

    - **conta que não é irmã** → 404, e não 403: dizer "existe, mas não é sua" confirmaria
      a existência daquele apelido a quem está tentando descobrir apelidos;
    - **conta desativada** → 403 com o motivo, porque aqui a pessoa É a dona e precisa
      saber por que não entra;
    - **subir para a plataforma sem senha** → 401 pedindo a senha, que é o ponto da regra.
    """
    destino = db.scalar(select(User).where(User.apelido == (apelido or "").strip().lower()))
    if (
        destino is None
        or destino.id == atual.id
        or atual.pessoa_id is None
        or destino.pessoa_id != atual.pessoa_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada para esta pessoa.")

    if not destino.ativo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta conta está desativada.")

    if destino.perfil in (Perfil.GESTOR_EMPRESA, Perfil.TECNICO) and destino.empresa_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta conta não está ligada a nenhuma empresa.",
        )

    if destino.perfil in DA_PLATAFORMA and not conferir_senha(senha or "", destino.senha_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Para entrar como gestor da plataforma, informe a senha desta conta.",
        )

    return destino


def agrupar(db: Session, contas: list[User], nome: str) -> Pessoa:
    """Junta contas existentes sob a mesma pessoa. Não faz commit.

    Recusa juntar contas que já pertencem a pessoas DIFERENTES: seria fundir dois humanos
    num só, e o efeito — a conta de um virando alcançável pela senha do outro — é exatamente
    o que este módulo não pode permitir por engano.
    """
    pessoas = {c.pessoa_id for c in contas if c.pessoa_id is not None}
    if len(pessoas) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Estas contas já estão agrupadas em pessoas diferentes. Desfaça antes de juntar.",
        )

    if pessoas:
        pessoa = db.get(Pessoa, pessoas.pop())
    else:
        pessoa = Pessoa(nome=nome.strip() or contas[0].nome)
        db.add(pessoa)
        db.flush()

    for conta in contas:
        conta.pessoa_id = pessoa.id
    return pessoa
