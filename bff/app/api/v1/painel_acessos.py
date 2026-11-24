"""A auditoria dos acessos na plataforma (adm-gs → Acessos): cada entrada no GS e em cada sistema pelo GS, as recusas,
as trocas de senha e de acesso, de todas as pessoas (o dono, 24/11/2026: "o GS é o detentor dos acessos, quero que ele
tenha a auditoria completa dos logs de acessos de cada pessoa"). O gerente da O&M vê o recorte da empresa dele no
oem-gs (`empresa.acessos_da_empresa`). A fonte é uma só: `services/acessos.listar`."""
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import exige_area
from app.models.user import User
from app.services import acessos, empresas

router = APIRouter(prefix="/api/painel/acessos", tags=["painel · acessos"])
EXIGE_ACESSOS = exige_area("acessos")


class AcessoOut(BaseModel):
    id: int
    em: datetime
    usuario_id: int | None = None
    #: de quem é a linha, em palavras ("Fulano (fulano)", "Login que não é conta", "Conta apagada (…)")
    quem: str
    empresa: str | None = None
    #: o que foi digitado (só quando é de uma conta; senão, um resumo que não volta ao texto)
    login: str
    acao: str
    #: o rótulo segue a ação E o resultado ("Entrou no sistema pelo GS" × "Não entrou no sistema")
    acao_rotulo: str
    sistema: str
    sistema_rotulo: str
    ok: bool
    motivo: str
    #: quem fez, quando não foi a própria pessoa (a empresa vê "equipe da plataforma" no lugar da conta de lá)
    por: str | None = None
    ip: str
    aparelho: str
    aparelho_completo: str


class Opcao(BaseModel):
    chave: str
    rotulo: str


class AcessosOut(BaseModel):
    acessos: list[AcessoOut]
    #: o catálogo dos sistemas, para o filtro (não só os que aparecem no resultado)
    sistemas: list[Opcao]
    #: de quem é o filtro por pessoa, quando ela está no alcance de quem pergunta
    pessoa: str | None = None
    #: o teto aplicado: com tantas linhas quanto ele, há mais no período
    limite: int
    #: o período aplicado (sem `de`, os últimos 30 dias pela data do servidor, em Brasília)
    de: date | None = None
    ate: date | None = None


def responder(db: Session, *, contas, usuario_id: int | None, sistema: str | None, so_recusas: bool,
              de: date | None, ate: date | None, busca: str | None, limite: int, todo_periodo: bool = False,
              empresa_vista: int | None = None) -> AcessosOut:
    """A resposta das duas telas (adm-gs e oem-gs), com o recorte de quem pergunta em `contas`. Sem `de` (e sem
    `todo_periodo`), os últimos 30 dias, pela data do servidor."""
    from datetime import timedelta

    from app.core.datas import hoje
    limite = max(1, min(limite, 1000))
    if de is None and not todo_periodo:
        de = hoje() - timedelta(days=30)
    pessoa = None
    if usuario_id is not None:
        q = select(User).where(User.id == usuario_id)
        u = db.scalar(q.where(contas) if contas is not None else q)
        pessoa = f"{u.nome} ({u.apelido})" if u is not None else None
    linhas = acessos.listar(db, contas=contas, empresa_vista=empresa_vista, usuario_id=usuario_id, sistema=sistema,
                            so_recusas=so_recusas, de=de, ate=ate, busca=busca, limite=limite)
    return AcessosOut(acessos=[AcessoOut(**x) for x in linhas], pessoa=pessoa, limite=limite, de=de, ate=ate,
                      sistemas=[Opcao(chave=k, rotulo=v) for k, v in acessos.SISTEMA.items()])


@router.get("", response_model=AcessosOut)
def acessos_da_plataforma(
    empresa_id: int | None = None,
    usuario_id: int | None = None,
    sistema: str | None = None,
    so_recusas: bool = False,
    de: date | None = None,
    ate: date | None = None,
    busca: str | None = None,
    todo_periodo: bool = False,
    limite: int = 300,
    db: Session = Depends(get_db),
    _: User = Depends(EXIGE_ACESSOS),
) -> AcessosOut:
    """Todos os acessos, ou recortados por empresa, pessoa, sistema, só as recusas, período (dias de Brasília) e busca."""
    contas = empresas.contas_da_empresa(empresa_id) if empresa_id is not None else None
    return responder(db, contas=contas, usuario_id=usuario_id, sistema=sistema, so_recusas=so_recusas, de=de,
                     ate=ate, busca=busca, limite=limite, todo_periodo=todo_periodo)
