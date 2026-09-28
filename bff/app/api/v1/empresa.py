"""O portão da empresa de O&M — `/api/empresa/*`.

O terceiro prefixo do sistema, e o prefixo é a informação: `/api/painel/*` é da
plataforma, `/api/v1/*` é do dono de usina, e o que está aqui é do **gerente da empresa
de O&M**. Quem lê um arquivo sabe de quem é a rota antes de ler a primeira função.

**O alcance sai da sessão, nunca do corpo ou da query.** Nenhuma rota aqui aceita
`empresa_id` de quem chama. Um parâmetro de empresa numa rota de empresa é a definição de
vazamento: quem trocasse o número leria a carteira do concorrente, e o servidor não teria
como saber que não devia. O recorte é aplicado por `services/empresas.no_escopo`, que é o
único lugar onde a regra existe.

**O login não mora aqui.** Autenticar é uma coisa só e acontece em `/api/painel/entrar`,
que emite o token do portão certo conforme o perfil. Duas portas de login seriam a mesma
regra escrita duas vezes — e a segunda é sempre a que esquece de conferir a conta ativa.

**Por que não é um perfil a mais dentro do painel.** O painel guarda credencial de
serviço, sonda e diagnóstico — coisas da plataforma. Pendurar o inquilino ali significaria
esconder metade das telas por perfil e torcer para nenhuma rota nova esquecer a guarda. Um
portão separado erra fechado: rota nova aqui já nasce com o recorte, e `gestor_atual`
recusa esta sessão em qualquer rota de painel.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import Field
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import gestor_empresa_atual
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import empresas as svc
from app.services import integracoes

router = APIRouter(prefix="/api/empresa", tags=["empresa · O&M"])


class EuOut(BaseModel):
    nome: str
    apelido: str
    empresa: str
    empresa_id: int


@router.get("/eu", response_model=EuOut)
def eu(db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)) -> EuOut:
    """Quem sou e de qual empresa, AGORA.

    A tela consulta isto ao abrir e mantém o nome da empresa fixo no topo. Não é enfeite:
    sem ele, quem administra a plataforma olhando a tela de suporte cadastra o cliente na
    empresa errada e ninguém descobre no mesmo dia.
    """
    empresa = svc.por_id(db, svc.empresa_exigida(gerente))
    return EuOut(
        nome=gerente.nome,
        apelido=gerente.apelido,
        empresa=empresa.nome,
        empresa_id=empresa.id,
    )


# ------------------------------------------------------------------------ usinas


class UsinaOut(BaseModel):
    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    ativo: bool
    #: Quantos clientes desta empresa já recebem esta usina no aplicativo.
    clientes: int = 0


@router.get("/usinas", response_model=list[UsinaOut])
def listar_usinas(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[UsinaOut]:
    """As usinas da empresa — inclusive as desligadas, com o estado dito.

    Desligada continua na lista de propósito: sumir seria a tela responder "não existe" a
    algo que existe e que o gerente pode religar.
    """
    usinas = list(
        db.scalars(
            svc.no_escopo(select(PlantLink), PlantLink.empresa_id, gerente).order_by(PlantLink.nome)
        ).all()
    )
    if not usinas:
        return []

    # Uma consulta para todas as contagens: uma por usina seria N+1 numa tela de lista.
    contagem = dict(
        db.execute(
            select(UserPlantAccess.plant_link_id, func.count(UserPlantAccess.user_id))
            .where(UserPlantAccess.plant_link_id.in_([u.id for u in usinas]))
            .group_by(UserPlantAccess.plant_link_id)
        ).all()
    )
    return [
        UsinaOut(
            id=u.id,
            nome=u.nome,
            cidade=u.cidade,
            uf=u.uf,
            kwp=u.kwp,
            ativo=u.ativo,
            clientes=contagem.get(u.id, 0),
        )
        for u in usinas
    ]


# ---------------------------------------------------------------------- clientes


class ClienteOut(BaseModel):
    id: int
    nome: str
    apelido: str
    email: str | None = None
    ativo: bool
    usinas: int = 0


@router.get("/clientes", response_model=list[ClienteOut])
def listar_clientes(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[ClienteOut]:
    """Os donos de usina atendidos por esta empresa."""
    clientes = list(
        db.scalars(
            svc.no_escopo(
                select(User).where(User.perfil == Perfil.CLIENTE), User.empresa_id, gerente
            ).order_by(User.nome)
        ).all()
    )
    if not clientes:
        return []

    contagem = dict(
        db.execute(
            select(UserPlantAccess.user_id, func.count(UserPlantAccess.plant_link_id))
            .where(UserPlantAccess.user_id.in_([c.id for c in clientes]))
            .group_by(UserPlantAccess.user_id)
        ).all()
    )
    return [
        ClienteOut(
            id=c.id,
            nome=c.nome,
            apelido=c.apelido,
            email=c.email,
            ativo=c.ativo,
            usinas=contagem.get(c.id, 0),
        )
        for c in clientes
    ]


# ---------------------------------------------------------------------- usuarios


class UsuarioOut(BaseModel):
    id: int
    nome: str
    apelido: str
    perfil: str
    ativo: bool


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar_usuarios(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[UsuarioOut]:
    """Quem é da empresa — gerentes e clientes, na mesma lista, com o papel dito.

    Contas da plataforma não aparecem aqui nem por engano: elas têm `empresa_id` nulo, e
    o recorte é por igualdade com a empresa da sessão.
    """
    usuarios = db.scalars(
        svc.no_escopo(select(User), User.empresa_id, gerente).order_by(User.nome)
    ).all()
    return [
        UsuarioOut(
            id=u.id, nome=u.nome, apelido=u.apelido, perfil=u.perfil.value, ativo=u.ativo
        )
        for u in usuarios
    ]


# --------------------------------------------------------------------- conexões


class ConexaoOut(BaseModel):
    """A conta da EMPRESA no produto — não a de um cliente dela, e não a da plataforma."""

    produto: str
    configurada: bool
    base_url: str | None = None
    estado: str
    detalhe: str | None = None
    testada_em: datetime | None = None
    usinas_visiveis: int | None = None
    token_prefixo: str | None = None
    token_dono_nome: str | None = None
    token_dono_email: str | None = None
    token_gravado_em: datetime | None = None
    #: `false` quando o que responde por este produto ainda é a credencial da PLATAFORMA.
    #: A tela diz isso em letras claras: enquanto for assim, o que a empresa lê depende de
    #: uma conta que não é dela, e entra mais de uma empresa no sistema o acesso para.
    propria: bool = False


def _conexao_out(produto: Produto, integracao, empresa_id: int) -> ConexaoOut:
    if integracao is None:
        return ConexaoOut(produto=produto.value, configurada=False, estado="nunca")
    return ConexaoOut(
        produto=produto.value,
        configurada=True,
        base_url=integracao.base_url,
        estado=integracao.estado.value,
        detalhe=integracao.detalhe_teste,
        testada_em=integracao.testada_em,
        usinas_visiveis=integracao.usinas_visiveis,
        token_prefixo=integracao.token_prefixo,
        token_dono_nome=integracao.token_dono_nome,
        token_dono_email=integracao.token_dono_email,
        token_gravado_em=integracao.token_gravado_em,
        propria=integracao.empresa_id == empresa_id,
    )


@router.get("/conexoes", response_model=list[ConexaoOut])
def listar_conexoes(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[ConexaoOut]:
    """O estado das duas contas da empresa. Sempre as duas, inclusive a não configurada."""
    empresa_id = svc.empresa_exigida(gerente)
    return [
        _conexao_out(p, integracoes.obter(db, p, empresa_id), empresa_id) for p in Produto
    ]


class TokenIn(BaseModel):
    base_url: str = Field(min_length=4)
    #: Sem `min_length` apertado: quem valida é `core/tokens_produto`, que sabe dizer POR
    #: QUE o token está errado — melhor resposta do que um 422 do Pydantic.
    token: str = Field(min_length=1)


class TesteOut(BaseModel):
    ok: bool
    detalhe: str
    usinas_visiveis: int | None = None
    dono_nome: str | None = None
    dono_email: str | None = None


@router.put("/conexoes/{produto}/token", response_model=TesteOut)
async def conectar(
    produto: Produto,
    body: TokenIn,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> TesteOut:
    """O gerente cola o token gerado na conta da empresa dele, naquele produto.

    O token é verificado ANTES de gravar: não servindo, a conexão anterior continua de pé.
    E ele vale exatamente o que a conta que o gerou vale lá — se aquela conta não enxerga
    uma usina no meuWatt, aqui também não, e a resposta diz quantas ela alcançou.
    """
    resultado = await integracoes.salvar_token(
        db,
        produto,
        body.base_url,
        body.token,
        ator_email=gerente.identificacao,
        empresa_id=svc.empresa_exigida(gerente),
    )
    return TesteOut(
        ok=resultado.ok,
        detalhe=resultado.detalhe,
        usinas_visiveis=resultado.usinas,
        dono_nome=resultado.dono_nome,
        dono_email=resultado.dono_email,
    )


@router.delete("/conexoes/{produto}/token", status_code=204)
def desconectar(
    produto: Produto,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> None:
    """Desconecta deste lado.

    **Não revoga nada no produto de origem**: o token continua válido lá, e é lá que a
    porta se fecha. A diferença importa o bastante para a tela dizê-la.
    """
    integracoes.remover_token(
        db,
        produto,
        ator_email=gerente.identificacao,
        empresa_id=svc.empresa_exigida(gerente),
    )
