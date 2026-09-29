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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr, Field
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import gestor_empresa_atual
from app.core.tokens_produto import NOME
from app.models.empresa import Empresa
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import clientes, conciliacao
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


# ---------------------------------------------------------------- os vínculos


class EmpresaDoProduto(BaseModel):
    """Uma empresa como o produto de origem a descreve."""

    id: int
    nome: str
    documento: str | None = None
    #: Quantas usinas e pessoas ela tem LÁ. Só o meuWatt responde isso; serve para
    #: reconhecer qual é qual quando dois nomes se parecem.
    usinas: int | None = None
    pessoas: int | None = None
    #: Já é a que esta empresa aponta.
    escolhida: bool = False


class CatalogoOut(BaseModel):
    meuwatt: list[EmpresaDoProduto] = []
    meuplano: list[EmpresaDoProduto] = []
    mw_enterprise_id: int | None = None
    mp_tenant_id: int | None = None
    #: Cada lado cai sozinho. A frase é a que o produto escreveu — é lá que mora
    #: "token revogado".
    avisos: list[str] = []


def _aviso(produto: Produto, exc: Exception) -> str:
    """A frase que o PRODUTO escreveu, não a da biblioteca de rede.

    `str(exc)` de um erro do httpx chega assim na tela: *"Client error '401 Unauthorized'
    for url 'https://.../admin/tenants' For more information check:
    https://developer.mozilla.org/..."* — a URL interna do upstream na tela, um convite a
    ler documentação de HTTP, e escondida a única frase que resolve.
    """
    return f"{NOME[produto]}: {integracoes.traduzir_falha(exc, produto).detalhe}"


@router.get("/vinculos/catalogo", response_model=CatalogoOut)
async def catalogo_de_vinculos(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> CatalogoOut:
    """As empresas que o SEU token enxerga em cada produto.

    **Quem casa a empresa é quem tem o token, e é você.** A plataforma cadastra a empresa e
    o usuário dela; ela não tem credencial no meuWatt nem no meuPlano, e usar a credencial
    de serviço para montar esta lista mostraria a carteira de quem a gerou — que não é a
    sua. Aqui a leitura sai com o token desta empresa, então a lista é exatamente o que a
    sua conta alcança lá.
    """
    empresa_id = svc.empresa_exigida(gerente)
    empresa = svc.por_id(db, empresa_id)
    saida = CatalogoOut(
        mw_enterprise_id=empresa.mw_enterprise_id, mp_tenant_id=empresa.mp_tenant_id
    )

    try:
        cliente = await integracoes.cliente_meuwatt(db, empresa_id)
        for e in await cliente.empresas_om():
            saida.meuwatt.append(
                EmpresaDoProduto(
                    id=e["id"],
                    nome=e.get("name") or "sem nome",
                    documento=e.get("cnpj"),
                    usinas=e.get("plants_count"),
                    pessoas=e.get("employees_count"),
                    escolhida=e["id"] == empresa.mw_enterprise_id,
                )
            )
    except Exception as exc:  # noqa: BLE001 — a tela abre com um produto fora
        saida.avisos.append(_aviso(Produto.MEUWATT, exc))

    try:
        cliente_mp = await integracoes.cliente_meuplano(db, empresa_id)
        for t in await cliente_mp.empresas_om():
            saida.meuplano.append(
                EmpresaDoProduto(
                    id=t["id"],
                    nome=t.get("name") or "sem nome",
                    documento=t.get("document"),
                    escolhida=t["id"] == empresa.mp_tenant_id,
                )
            )
    except Exception as exc:  # noqa: BLE001
        saida.avisos.append(_aviso(Produto.MEUPLANO, exc))

    return saida


class VinculoIn(BaseModel):
    """Ausente mantém; `null` explícito descasa — a mesma régua de `mw_micro_plant_id`."""

    mw_enterprise_id: int | None = None
    mp_tenant_id: int | None = None


class VinculoOut(BaseModel):
    mw_enterprise_id: int | None = None
    mp_tenant_id: int | None = None


@router.put("/vinculos", response_model=VinculoOut)
def salvar_vinculos(
    body: VinculoIn,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> VinculoOut:
    """Diz que a empresa de lá e a de lá são esta — a sua.

    A empresa vem da SESSÃO, nunca da URL: uma rota de empresa que aceitasse o id de outra
    deixaria qualquer gerente apontar a empresa do vizinho para a dele.
    """
    empresa = svc.por_id(db, svc.empresa_exigida(gerente))

    for campo in ("mw_enterprise_id", "mp_tenant_id"):
        if campo not in body.model_fields_set:
            continue
        valor = getattr(body, campo)
        if valor is not None:
            outra = db.scalar(
                select(Empresa).where(
                    getattr(Empresa, campo) == valor, Empresa.id != empresa.id
                )
            )
            if outra is not None:
                # Sem dizer QUAL empresa já tem: o gerente de um inquilino não deve
                # descobrir os nomes dos outros por tentativa.
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Essa empresa já está vinculada a outra conta da plataforma. "
                    "Fale com quem administra.",
                )
        setattr(empresa, campo, valor)

    db.commit()
    return VinculoOut(
        mw_enterprise_id=empresa.mw_enterprise_id, mp_tenant_id=empresa.mp_tenant_id
    )


# ------------------------------------------------- trazer as usinas da empresa


class CandidataOut(BaseModel):
    """Uma usina do meuPlano que PARECE ser esta do meuWatt.

    Os motivos vão junto ("mesmo nome", "a 300 m", "mesma potência") porque casar errado
    mistura a geração de uma usina com a manutenção de outra, e ninguém percebe até alguém
    questionar um relatório. Quem decide é quem lê os motivos.
    """

    mp_usina_id: int
    nome: str
    motivos: list[str] = []


class LinhaDeUsina(BaseModel):
    """Uma usina vista dos dois lados, como a conciliação do painel a descreve."""

    chave: str
    nome: str
    plant_link_id: int | None = None
    mw_slug: str | None = None
    mp_usina_id: int | None = None
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    origem: str
    no_app: bool = False
    #: Sugestão de par, quando a usina só apareceu de um lado.
    par_provavel_mw: str | None = None
    par_provavel_nome: str | None = None
    #: As candidatas do meuPlano para esta usina do meuWatt, da mais provável para a menos.
    candidatos: list[CandidataOut] = []


class UsinaDoMeuPlano(BaseModel):
    id: int
    nome: str


class CatalogoDeUsinas(BaseModel):
    linhas: list[LinhaDeUsina] = []
    #: Todas as usinas do meuPlano que o token alcança — para casar à mão quando a
    #: sugestão não serve. Sem isso, uma usina cujo nome não se parece com nada ficaria
    #: sem par para sempre, e a tela não teria como dizer que existe.
    usinas_do_meuplano: list[UsinaDoMeuPlano] = []
    avisos: list[str] = []


@router.get("/usinas/catalogo", response_model=CatalogoDeUsinas)
async def catalogo_de_usinas(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> CatalogoDeUsinas:
    """As usinas que o SEU token enxerga nos dois produtos, e o que já está aqui dentro.

    É a conciliação do painel, escopada: quem lê é o token desta empresa, então a lista é
    exatamente a carteira dela. A plataforma não monta isso — ela não tem credencial nos
    produtos, e usar a de serviço mostraria a carteira de outra gente.

    As usinas JÁ trazidas entram pelo vínculo desta empresa (`gs_plant_links.empresa_id`),
    nunca pelo inventário inteiro: um `PlantLink` de outra empresa não aparece aqui.
    """
    empresa_id = svc.empresa_exigida(gerente)
    usinas_mw: list[dict] = []
    usinas_mp: list[dict] = []
    avisos: list[str] = []

    try:
        usinas_mw = await (await integracoes.cliente_meuwatt(db, empresa_id)).usinas()
    except Exception as exc:  # noqa: BLE001 — cada lado cai sozinho
        avisos.append(_aviso(Produto.MEUWATT, exc))
    try:
        usinas_mp = await (await integracoes.cliente_meuplano(db, empresa_id)).usinas()
    except Exception as exc:  # noqa: BLE001
        avisos.append(_aviso(Produto.MEUPLANO, exc))

    links = list(
        db.scalars(select(PlantLink).where(PlantLink.empresa_id == empresa_id)).all()
    )
    linhas = [
        LinhaDeUsina(
            chave=l.chave,
            nome=l.nome,
            plant_link_id=l.plant_link_id,
            mw_slug=l.mw_slug,
            mp_usina_id=l.mp_usina_id,
            cidade=l.cidade,
            uf=l.uf,
            kwp=l.kwp,
            origem=l.origem,
            no_app=l.no_app,
            par_provavel_mw=l.par_provavel_mw,
            par_provavel_nome=l.par_provavel_nome,
            candidatos=[
                CandidataOut(mp_usina_id=c.mp_usina_id, nome=c.nome, motivos=c.motivos)
                for c in l.candidatos
            ],
        )
        for l in conciliacao.montar(usinas_mw, usinas_mp, links)
    ]
    return CatalogoDeUsinas(
        linhas=linhas,
        usinas_do_meuplano=[
            UsinaDoMeuPlano(id=u["id"], nome=conciliacao.nome_de(u))
            for u in usinas_mp
            if u.get("id") is not None
        ],
        avisos=avisos,
    )


class UsinaIn(BaseModel):
    plant_link_id: int | None = None
    mw_slug: str | None = None
    mp_usina_id: int | None = None
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    #: Se ela entra no aplicativo. Desligada continua aqui, com vínculos e concessões
    #: intactos — o gerente religa sem refazer nada.
    no_app: bool = True


@router.put("/usinas", response_model=LinhaDeUsina)
def salvar_usina(
    body: UsinaIn, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> LinhaDeUsina:
    """Traz a usina para a empresa, casa os dois lados, liga ou desliga no aplicativo.

    Uma operação só para as três coisas porque são a mesma vista de ângulos diferentes:
    gravar o estado desejado daquela usina. Separadas, a tela chamaria duas rotas para
    "trazer a usina do meuPlano para o app", com a chance de a segunda falhar depois da
    primeira.

    **A usina nasce com o dono da sessão**, e uma que já é de OUTRA empresa é recusada como
    inexistente: o gerente não deve descobrir, por tentativa, o que existe na carteira dos
    outros.
    """
    empresa_id = svc.empresa_exigida(gerente)
    if body.mw_slug is None and body.mp_usina_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A usina precisa existir em pelo menos um dos dois produtos.",
        )

    link = None
    if body.plant_link_id is not None:
        link = db.get(PlantLink, body.plant_link_id)
        if link is None or link.empresa_id != empresa_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")

    # O mesmo identificador de produto não pode pertencer a duas usinas. Três casos, e
    # confundi-los travou o dono na primeira tentativa:
    #
    # 1. a usina existe e é **de ninguém** — é o estado de tudo o que foi cadastrado antes
    #    do multiempresa. Trazer para a empresa é ADOTÁ-LA, não criar outra: criar daria
    #    duas linhas para a mesma usina, e recusar (que era o que acontecia) deixava as 7
    #    usinas reais inalcançáveis, com a mensagem "já pertence a outra empresa" — que era
    #    falsa, porque ela não pertencia a ninguém;
    # 2. a usina já é DESTA empresa por outro vínculo — aí é conflito de verdade, e a
    #    mensagem diz com qual nome ela já está aqui;
    # 3. a usina é de OUTRA empresa — recusa sem dizer de quem, para não revelar a
    #    carteira do vizinho.
    for campo, valor in ((PlantLink.mw_plant_slug, body.mw_slug), (PlantLink.mp_usina_id, body.mp_usina_id)):
        if valor is None:
            continue
        condicoes = [campo == valor]
        if link is not None:
            condicoes.append(PlantLink.id != link.id)
        outro = db.scalar(select(PlantLink).where(*condicoes))
        if outro is None:
            continue

        if outro.empresa_id is None and link is None:
            link = outro  # adoção
            continue
        if outro.empresa_id == empresa_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Esta usina já está aqui como “{outro.nome}”. Desfaça o outro vínculo antes.",
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Esta usina já pertence a outra empresa da plataforma. Fale com quem administra.",
        )

    if link is None:
        link = PlantLink(nome=body.nome, empresa_id=empresa_id)
        db.add(link)
    else:
        # Adotada ou já dela: o dono é sempre o da sessão.
        link.empresa_id = empresa_id

    link.mw_plant_slug = body.mw_slug
    link.mp_usina_id = body.mp_usina_id
    link.nome = body.nome
    link.cidade = body.cidade
    link.uf = body.uf
    link.kwp = body.kwp
    link.ativo = body.no_app
    db.commit()
    db.refresh(link)

    return LinhaDeUsina(
        chave=f"link:{link.id}",
        nome=link.nome,
        plant_link_id=link.id,
        mw_slug=link.mw_plant_slug,
        mp_usina_id=link.mp_usina_id,
        cidade=link.cidade,
        uf=link.uf,
        kwp=link.kwp,
        origem=("ambos" if link.mw_plant_slug and link.mp_usina_id
                else "meuwatt" if link.mw_plant_slug else "meuplano"),
        no_app=link.ativo,
    )


# ------------------------------------------------------ cadastrar cliente aqui


class ClienteIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None


class ClienteCriadoOut(BaseModel):
    id: int
    nome: str
    apelido: str
    #: A senha provisória, mostrada UMA vez. Entregue com o APELIDO, que é o que autentica
    #: — mandar o e-mail junto convida a tentar entrar com ele, que é o que não funciona.
    senha: str


@router.post("/clientes", response_model=ClienteCriadoOut, status_code=201)
def criar_cliente(
    body: ClienteIn, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> ClienteCriadoOut:
    """Cadastra um dono de usina DESTA empresa.

    Reusa `services/clientes.criar`, que é onde moram as regras do cadastro (apelido
    normalizado, e-mail repetido entre clientes, senha provisória). Uma segunda cópia aqui
    divergiria no primeiro dia em que alguém melhorasse uma delas.

    A empresa vem da sessão e é gravada no cliente: é ela que faz a conta aparecer para
    este gerente e para mais ninguém.
    """
    empresa_id = svc.empresa_exigida(gerente)
    try:
        criado = clientes.criar(
            db,
            nome=body.nome,
            apelido=body.apelido,
            email=str(body.email) if body.email else None,
            empresa=None,
            criado_por=gerente,
        )
    except clientes.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    criado.usuario.empresa_id = empresa_id
    db.commit()

    return ClienteCriadoOut(
        id=criado.usuario.id,
        nome=criado.usuario.nome,
        apelido=criado.usuario.apelido,
        senha=criado.senha_provisoria,
    )


class UsinasDoClienteIn(BaseModel):
    #: A lista COMPLETA: o que não vier é revogado.
    plant_link_ids: list[int] = []


@router.put("/clientes/{cliente_id}/usinas", status_code=204)
def definir_usinas_do_cliente(
    cliente_id: int,
    body: UsinasDoClienteIn,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> None:
    """Concede as usinas desta empresa a um cliente dela.

    Duas guardas, e as duas importam: o cliente tem de ser DESTA empresa, e cada usina
    também. Sem a segunda, um id na requisição concederia a usina de outra empresa — e o
    dono dela veria no aplicativo dados de uma carteira que não é a sua.
    """
    empresa_id = svc.empresa_exigida(gerente)

    cliente = db.get(User, cliente_id)
    if cliente is None or cliente.empresa_id != empresa_id or cliente.perfil is not Perfil.CLIENTE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado nesta empresa.")

    if body.plant_link_ids:
        minhas = {
            u.id
            for u in db.scalars(
                select(PlantLink).where(PlantLink.empresa_id == empresa_id)
            ).all()
        }
        fora = [pid for pid in body.plant_link_ids if pid not in minhas]
        if fora:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Usina não encontrada nesta empresa."
            )

    try:
        clientes.definir_usinas(db, cliente, body.plant_link_ids)
    except clientes.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
