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

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr, Field
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.painel_whatsapp import RegistroBotOut, registros_do_bot, saude_atual
from app.core.db import get_db
from app.core.security import gerar_hash_senha, gestor_empresa_atual
from app.core.telefone import exibir as exibir_telefone
from app.core.tokens_produto import NOME
from app.models.empresa import Empresa
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.usina_oculta import UsinaOculta
from app.models.user import Perfil, User, UserPlantAccess, VinculoProduto
from app.services import clientes, conciliacao, pessoas, vinculos
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
            select(User)
            .where(User.perfil == Perfil.CLIENTE, svc.contas_da_empresa(svc.empresa_exigida(gerente)))
            .order_by(User.nome)
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

    Conta da plataforma é excluída pelo PERFIL, não pelo `empresa_id` nulo — que era o
    que este texto dizia e estava errado: `PUT /api/painel/empresas/{id}/carteira` grava
    empresa em qualquer conta, e um administrador com empresa gravada aparecia aqui.
    """
    usuarios = db.scalars(
        select(User)
        .where(svc.contas_da_empresa(svc.empresa_exigida(gerente)), User.perfil.not_in(pessoas.DA_PLATAFORMA))
        .order_by(User.nome)
    ).all()
    return [
        UsuarioOut(
            id=u.id, nome=u.nome, apelido=u.apelido, perfil=u.perfil.value, ativo=u.ativo
        )
        for u in usuarios
    ]


# --------------------------------------------------------------------- conexões


def _conta_da_empresa(db: Session, usuario_id: int, empresa_id: int) -> User:
    """A conta que este gerente administra — ou 404.

    Conferir a empresa NÃO basta, e a assimetria com a rota-irmã da plataforma
    (`painel_empresas.py`, que recusa perfil de plataforma desde sempre) era escalada de
    privilégio completa: um administrador com `empresa_id` gravado — estado real, o
    comentário de lá diz "acontece" — aparecia na lista do gerente, e
    `PATCH /usuarios/{id}` trocava a senha dele. Com a senha, o gerente entrava em
    `/api/painel/entrar` como administrador, que é quem guarda as credenciais de TODOS os
    inquilinos. Descoberto por revisão adversarial em 30/09/2026.

    404 e não 400: quem administra a plataforma não é da empresa, e a frase "essa é da
    plataforma" confirmaria a existência da conta a quem chuta números.
    """
    conta = db.get(User, usuario_id)
    if (
        conta is None
        or conta.empresa_id != empresa_id
        or conta.perfil in pessoas.DA_PLATAFORMA
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada nesta empresa.")
    return conta


def _membro_da_empresa(db: Session, usuario_id: int, empresa_id: int) -> User:
    """A conta é DESTA empresa — de origem OU membro (`gs_usuario_empresas`). Serve ao que a
    empresa faz com quem também é de outra: conceder as usinas DELA. O resto da conta
    (senha, celular, tokens, bot) é de quem cuida dela, a empresa de origem
    (`_conta_da_empresa`) — duas empresas trocando a senha da mesma pessoa abririam a
    carteira de uma para o gerente da outra."""
    conta = db.get(User, usuario_id)
    if (
        conta is None
        or conta.perfil in pessoas.DA_PLATAFORMA
        or empresa_id not in svc.empresas_da_conta(db, conta)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada nesta empresa.")
    return conta


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
    #: A conta é DESTA empresa. Sempre verdadeiro quando configurada: a plataforma não tem
    #: token (regra do dono, 23/10/2026) e o atalho para a credencial dela acabou.
    propria: bool = False


def _conexao_out(produto: Produto, integracao, empresa_id: int) -> ConexaoOut:
    if integracao is None or integracao.empresa_id != empresa_id:
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
async def salvar_vinculos(
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
    if not empresa.documento:
        await documento_do_produto(db, empresa)
    return VinculoOut(
        mw_enterprise_id=empresa.mw_enterprise_id, mp_tenant_id=empresa.mp_tenant_id
    )


async def documento_do_produto(db: Session, empresa: Empresa) -> None:
    """Base única: o CNPJ vem da empresa casada lá (meuPlano primeiro, depois meuWatt). Só
    preenche o vazio — o que alguém digitou aqui não é sobrescrito. Produto fora do ar não
    impede o vínculo: o CNPJ entra no próximo."""
    for ler, id_, chave in (
        (integracoes.cliente_meuplano, empresa.mp_tenant_id, "document"),
        (integracoes.cliente_meuwatt, empresa.mw_enterprise_id, "cnpj"),
    ):
        if id_ is None:
            continue
        try:
            orgs = await (await ler(db, empresa.id)).empresas_om()
        except Exception:  # noqa: BLE001
            continue
        doc = next((o.get(chave) for o in orgs if o.get("id") == id_), None)
        if doc:
            empresa.documento = str(doc).strip()[:20]
            db.commit()
            return


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
    #: `ambos`, `meuwatt`, `meuplano` ou `micro` — a usina que só existe no MICRO.
    origem: str
    no_app: bool = False
    mw_micro_plant_id: int | None = None
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
    #: Quantas a empresa escolheu não ver. A tela mostra o número: uma lista que encolhe
    #: sem contador faz procurar a usina que "sumiu", e a resposta ("você a ocultou")
    #: precisa estar na mesma tela.
    ocultas: int = 0
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
    # Casada a organização da empresa no meuPlano (Vínculos), só as usinas em que ELA é a
    # prestadora ou a gestora: o token de quem é admin do sistema lá enxerga todas, e o
    # gerente só deve ver as dele ("respectivamente somente as usinas dele").
    organizacao = svc.por_id(db, empresa_id).mp_tenant_id
    if organizacao is not None:
        usinas_mp = [
            u for u in usinas_mp
            if organizacao in (u.get("prestadora_owner_id"), u.get("gestora_owner_id"))
        ]

    links = list(
        db.scalars(select(PlantLink).where(PlantLink.empresa_id == empresa_id)).all()
    )

    # "Não mostrar esta usina": preferência de TELA desta empresa. A usina some da lista de
    # trazer e nada mais muda — o dono dela, no aplicativo, continua vendo o que foi
    # concedido. Só as que AINDA NÃO foram trazidas são escondidas: esconder uma que já
    # está aqui faria a linha sumir com os vínculos dela dentro.
    ocultas = {
        (o.produto, o.identificador)
        for o in db.scalars(
            select(UsinaOculta).where(UsinaOculta.empresa_id == empresa_id)
        ).all()
    }

    def esta_oculta(l) -> bool:
        if l.plant_link_id is not None:
            return False
        if l.mw_slug and (Produto.MEUWATT, l.mw_slug) in ocultas:
            return True
        return bool(l.mp_usina_id and (Produto.MEUPLANO, str(l.mp_usina_id)) in ocultas)

    _por_link = {l.id: l for l in links}
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
            # A origem vem do LINK quando a usina já está aqui: `conciliacao.montar` só
            # conhece os dois produtos e classifica como "meuPlano" tudo o que não tem
            # slug — foi assim que as 5 micro apareceram no grupo errado.
            origem=_origem(_por_link.get(l.plant_link_id)) if l.plant_link_id else l.origem,
            no_app=l.no_app,
            mw_micro_plant_id=(
                _por_link[l.plant_link_id].mw_micro_plant_id if l.plant_link_id else None
            ),
            par_provavel_mw=l.par_provavel_mw,
            par_provavel_nome=l.par_provavel_nome,
            candidatos=[
                CandidataOut(mp_usina_id=c.mp_usina_id, nome=c.nome, motivos=c.motivos)
                for c in l.candidatos
            ],
        )
        for l in conciliacao.montar(usinas_mw, usinas_mp, links)
        if not esta_oculta(l)
    ]
    # As micro usinas entram na MESMA lista, como origem `micro`: uma usina que só existe
    # no portal do fabricante é uma usina, não o complemento de outra. As já trazidas saem
    # daqui porque já vieram como `PlantLink` acima.
    ja_trazidas = {l.mw_micro_plant_id for l in links if l.mw_micro_plant_id}
    try:
        cru = await (await integracoes.cliente_meuwatt(db, empresa_id)).micro_usinas()
        for m in (cru.get("plants", []) if isinstance(cru, dict) else (cru or [])):
            mid = m.get("id")
            if mid is None or mid in ja_trazidas:
                continue
            if (Produto.MEUWATT, f"micro:{mid}") in ocultas:
                continue
            linhas.append(
                LinhaDeUsina(
                    chave=f"micro:{mid}",
                    nome=m.get("name") or "sem nome",
                    kwp=m.get("capacity_kwp"),
                    origem="micro",
                    mw_micro_plant_id=mid,
                )
            )
    except Exception as exc:  # noqa: BLE001 — o MICRO é leitura de administrador lá
        # O meuWatt é lido duas vezes aqui (usinas e micro). Com o token revogado, as duas
        # falham com a MESMA frase — e a tela desenha `avisos.map(key={a})`: chave
        # repetida no React e o erro impresso em dobro.
        aviso = _aviso(Produto.MEUWATT, exc)
        if aviso not in avisos:
            avisos.append(aviso)

    return CatalogoDeUsinas(
        linhas=linhas,
        ocultas=len(ocultas),
        usinas_do_meuplano=[
            UsinaDoMeuPlano(id=u["id"], nome=conciliacao.nome_de(u))
            for u in usinas_mp
            if u.get("id") is not None
        ],
        avisos=avisos,
    )


def _origem(link: PlantLink) -> str:
    """De onde esta usina vem. A ordem importa: uma usina que está nos dois produtos é
    "ambos" mesmo tendo micro, porque a micro é um detalhe do monitoramento dela — e uma
    que SÓ tem micro é "micro", que é o caso do cliente cujo único monitoramento é o
    portal do fabricante."""
    if link.mw_plant_slug and link.mp_usina_id:
        return "ambos"
    if link.mw_plant_slug:
        return "meuwatt"
    if link.mp_usina_id:
        return "meuplano"
    return "micro"


class UsinaIn(BaseModel):
    plant_link_id: int | None = None
    mw_slug: str | None = None
    mp_usina_id: int | None = None
    #: A usina do MICRO (Solis, Canadian, TSUN). **Sozinha ela já é uma usina**: há
    #: cliente cujo único monitoramento é o portal do fabricante, e exigir par no meuWatt
    #: o deixaria de fora. Junto de um `mw_slug`, é a mesma usina vista nos dois lugares.
    mw_micro_plant_id: int | None = None
    nome: str = Field(min_length=1)
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    #: Se ela entra no aplicativo. Desligada continua aqui, com vínculos e concessões
    #: intactos — o gerente religa sem refazer nada.
    no_app: bool = True


async def _ler(cliente_esperado):
    """`(await cliente).usinas()` em uma linha, para o chamador ficar legível."""
    return await (await cliente_esperado).usinas()


async def _o_seu_token_enxerga(db: Session, empresa_id: int, body: "UsinaIn") -> None:
    """O identificador que veio no corpo tem de estar no catálogo do SEU token.

    A tela só oferece o que o catálogo devolveu, mas o corpo é JSON: sem esta conferência,
    um `mw_slug` digitado à mão gravava na carteira desta empresa a usina de outra. Não
    vazava leitura — quem lê é o token —, mas ocupava o identificador: a empresa dona
    passava a receber "já pertence a outra empresa" ao trazer a própria usina, e o par
    201 × 409 virava um oráculo de quem tem o quê.

    **Só confere o que ENTRA.** Renomear, ligar e desligar não mexem em identificador e
    não pagam ida ao upstream — nem ficam reféns de um produto fora do ar.
    """
    ja_da_empresa = {
        (l.mw_plant_slug, l.mp_usina_id, l.mw_micro_plant_id)
        for l in db.scalars(select(PlantLink).where(PlantLink.empresa_id == empresa_id)).all()
    }
    slugs = {a for a, _, _ in ja_da_empresa}
    mps = {b for _, b, _ in ja_da_empresa}
    micros = {c for _, _, c in ja_da_empresa}

    async def confere(valor, ja_tem, ler, chave, frase):
        if valor is None or valor in ja_tem:
            return
        try:
            itens = await ler()
        except Exception:  # noqa: BLE001
            # Upstream mudo, ou empresa ainda sem credencial própria: não há o que
            # afirmar, e travar aqui impediria o gerente de trabalhar por causa de um
            # produto fora do ar. A trava existe contra corpo forjado, não contra
            # instabilidade — e o que ele reivindicar sem credencial não lê nada.
            return
        if valor not in {i.get(chave) for i in itens}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, frase)

    async def micro():
        cru = await (await integracoes.cliente_meuwatt(db, empresa_id)).micro_usinas()
        return cru.get("plants", []) if isinstance(cru, dict) else (cru or [])

    await confere(
        body.mw_slug, slugs,
        lambda: _ler(integracoes.cliente_meuwatt(db, empresa_id)),
        "slug", "Esta usina não está no seu meuWatt.",
    )
    await confere(
        body.mp_usina_id, mps,
        lambda: _ler(integracoes.cliente_meuplano(db, empresa_id)),
        "id", "Esta usina não está no seu meuPlano.",
    )
    await confere(
        body.mw_micro_plant_id, micros, micro, "id",
        "Esta micro usina não está no seu meuWatt.",
    )


@router.put("/usinas", response_model=LinhaDeUsina)
async def salvar_usina(
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
    if body.mw_slug is None and body.mp_usina_id is None and body.mw_micro_plant_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A usina precisa existir em pelo menos um dos produtos.",
        )

    await _o_seu_token_enxerga(db, empresa_id, body)

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
    for campo, valor in (
        (PlantLink.mw_plant_slug, body.mw_slug),
        (PlantLink.mp_usina_id, body.mp_usina_id),
        (PlantLink.mw_micro_plant_id, body.mw_micro_plant_id),
    ):
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
    # Só mexe na micro se o chamador a mandou: um painel publicado antes deste campo não
    # o manda, e cada "Ligar/Desligar" dele apagaria o par em silêncio. Mesma guarda do
    # gêmeo em `painel.py`, que só ela tinha.
    if "mw_micro_plant_id" in body.model_fields_set:
        link.mw_micro_plant_id = body.mw_micro_plant_id
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
        origem=_origem(link),
        no_app=link.ativo,
        mw_micro_plant_id=link.mw_micro_plant_id,
    )


# ------------------------------------------------------ cadastrar cliente aqui


class ClienteIn(BaseModel):
    nome: str = Field(min_length=2)
    apelido: str = Field(min_length=3)
    email: EmailStr | None = None
    #: `cliente` (dono de usina, entra no app), `gestor_empresa` (opera a empresa com
    #: você) ou `tecnico` (entra no painel só para conectar o WhatsApp dele). São os
    #: únicos papéis que existem dentro de uma empresa — os da plataforma não se criam
    #: daqui, e pedi-los aqui seria dar a um inquilino a chave do sistema inteiro.
    perfil: Perfil = Perfil.CLIENTE
    #: Celular (opcional). É o que o assistente do WhatsApp usa para reconhecer a pessoa.
    telefone: str | None = None
    #: Puxar do meuPlano: a pessoa de lá a que esta conta nasce LIGADA (nome, e-mail e
    #: celular vêm de lá, e mudanças passam a valer nos dois). Vazio = cadastro do zero.
    mp_user_id: int | None = None


class ClienteCriadoOut(BaseModel):
    id: int
    nome: str
    apelido: str
    #: A senha provisória, mostrada UMA vez. Entregue com o APELIDO, que é o que autentica
    #: — mandar o e-mail junto convida a tentar entrar com ele, que é o que não funciona.
    senha: str
    #: o que não pôde vir do meuPlano ao puxar o cadastro
    avisos: list[str] = []


@router.post("/clientes", response_model=ClienteCriadoOut, status_code=201)
async def criar_cliente(
    body: ClienteIn, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> ClienteCriadoOut:
    """Cadastra alguém DESTA empresa: um dono de usina, outro gerente ou um técnico.

    Reusa `services/clientes.criar`, que é onde moram as regras do cadastro (apelido
    normalizado, e-mail repetido entre clientes, senha provisória). Uma segunda cópia aqui
    divergiria no primeiro dia em que alguém melhorasse uma delas.

    A empresa vem da sessão e é gravada no cliente: é ela que faz a conta aparecer para
    este gerente e para mais ninguém.
    """
    empresa_id = svc.empresa_exigida(gerente)
    if body.perfil not in (Perfil.CLIENTE, Perfil.GESTOR_EMPRESA, Perfil.TECNICO):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Dentro da empresa só existem dono de usina, gerente e técnico.",
        )
    from app.services import cadastro
    # O celular é conferido ANTES de criar: recusado depois, a conta já existiria pela metade.
    telefone = cadastro.celular_livre(db, body.telefone, None) if body.telefone else None
    from app.core.security import gerar_senha_provisoria

    provisoria = gerar_senha_provisoria()
    try:
        criado = clientes.criar(
            db,
            nome=body.nome,
            apelido=body.apelido,
            email=str(body.email) if body.email else None,
            empresa=None,
            criado_por=gerente,
            senha_pronta=(provisoria, await asyncio.to_thread(gerar_hash_senha, provisoria)),
        )
    except clientes.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    criado.usuario.empresa_id = empresa_id
    criado.usuario.perfil = body.perfil
    criado.usuario.telefone = telefone
    cadastro.adotar_mensagens(db, criado.usuario)
    db.commit()

    avisos: list[str] = []
    if body.mp_user_id is not None:
        avisos = await cadastro.ligar(db, criado.usuario, empresa_id, body.mp_user_id)
        if telefone and criado.usuario.telefone != telefone:
            await cadastro.gravar(db, criado.usuario, empresa_id, telefone=body.telefone)
            db.commit()

    return ClienteCriadoOut(
        id=criado.usuario.id,
        nome=criado.usuario.nome,
        apelido=criado.usuario.apelido,
        senha=criado.senha_provisoria,
        avisos=avisos,
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

    cliente = _membro_da_empresa(db, cliente_id, empresa_id)

    # Conceder usina a um GERENTE não existe: ele vê a carteira inteira da empresa por ser
    # gerente. Com concessão, ele competia com os clientes pela mesma usina — a regra da
    # casa é "cada usina pertence a UM cliente só" —, e conceder-lhe o que já era de um
    # dono era recusado com razão. O erro estava na premissa, não na regra.
    if cliente.abre_empresa:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "O gerente já vê todas as usinas da empresa — não há o que conceder a ele.",
        )
    # O técnico não entra no aplicativo do dono: conceder-lhe usina disputaria a usina com
    # o cliente dela ("cada usina pertence a UM cliente só") por uma tela que ele não abre.
    if cliente.abre_tecnico:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "O técnico não recebe usinas: ele entra no painel só para o WhatsApp dele.",
        )

    if body.plant_link_ids:
        minhas = {
            u.id
            for u in db.scalars(
                select(PlantLink).where(PlantLink.empresa_id == empresa_id)
            ).all()
        }
        fora = [pid for pid in body.plant_link_ids if pid not in minhas]
        if fora:
            # HERDADA é ADOTADA, não recusada — e essa é a correção de raiz.
            #
            # Usina sem dono (`empresa_id` nulo) é de antes do multiempresa. Esta tela a
            # mostra marcada, porque alguém DESTA empresa já a recebia; mandá-la de volta
            # no "salvar" é o caminho normal, e a versão anterior respondia
            # "Esta usina ainda não é da sua empresa: <nome>. Traga em Usinas" — um erro
            # no clique mais comum da tela, com a instrução para um lugar onde a usina não
            # aparecia (o catálogo sai do upstream, e uma herdada sem `mw_slug` não está
            # lá). Quem já a enxerga é dono dela: adotar é gravar o que já era verdade.
            #
            # A adoção é ESTREITA de propósito: só a usina que esta empresa já concede a
            # alguém dela. Um id chutado que nunca foi concedido continua 404 sem nome —
            # senão o campo viraria "reivindique qualquer usina órfã por número".
            orfas_que_ja_vejo = {
                pid
                for pid in db.scalars(
                    select(PlantLink.id)
                    .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
                    .join(User, User.id == UserPlantAccess.user_id)
                    .where(PlantLink.empresa_id.is_(None), svc.contas_da_empresa(empresa_id))
                ).all()
            }
            if [pid for pid in fora if pid not in orfas_que_ja_vejo]:
                # De OUTRA empresa, ou inexistente: 404 sem nome, para não entregar a
                # carteira do vizinho a quem chuta números.
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "Usina não encontrada nesta empresa."
                )
            for pid in fora:
                db.get(PlantLink, pid).empresa_id = empresa_id

    try:
        clientes.definir_usinas(db, cliente, body.plant_link_ids, empresa_id=empresa_id)
    except clientes.RegraDeNegocio as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()


# ------------------------------------------------------------- as micro usinas


class MicroUsinaOut(BaseModel):
    """Uma usina do MICRO do meuWatt — os portais dos fabricantes (Solis, Canadian, TSUN).

    Não é um quarto formato de usina: ela se **casa** com uma usina que já está aqui, e
    serve a uma coisa — o aviso de usina parada dela chega ao dono. Por isso o que se
    escolhe é "esta micro é aquela usina", nunca "traga a micro para dentro".
    """

    id: int
    nome: str
    kwp: float | None = None
    #: As estações dos portais que a formam ("UFV Sitio Solis + UFV Sitio Canadian").
    estacoes: list[str] = []
    #: A usina desta empresa já casada com ela, se houver.
    plant_link_id: int | None = None
    usina_nome: str | None = None


class MicroCatalogoOut(BaseModel):
    micro: list[MicroUsinaOut] = []
    aviso: str | None = None


@router.get("/micro-usinas", response_model=MicroCatalogoOut)
async def micro_usinas(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> MicroCatalogoOut:
    """As micro usinas que o SEU token alcança no MICRO do meuWatt.

    O MICRO é leitura de administrador lá: um token de escopo menor não o enxerga, e a
    resposta vem com o aviso em vez de uma lista vazia — vazio diria "não existe nenhuma",
    que é outra coisa.
    """
    empresa_id = svc.empresa_exigida(gerente)
    casadas = {
        u.mw_micro_plant_id: u
        for u in db.scalars(
            select(PlantLink).where(
                PlantLink.empresa_id == empresa_id, PlantLink.mw_micro_plant_id.is_not(None)
            )
        ).all()
    }

    try:
        cliente = await integracoes.cliente_meuwatt(db, empresa_id)
        cru = await cliente.micro_usinas()
    except Exception as exc:  # noqa: BLE001
        return MicroCatalogoOut(aviso=_aviso(Produto.MEUWATT, exc))

    lista = cru.get("plants", []) if isinstance(cru, dict) else (cru or [])
    saida = []
    for m in lista:
        mid = m.get("id")
        if mid is None:
            continue
        casada = casadas.get(mid)
        saida.append(
            MicroUsinaOut(
                id=mid,
                nome=m.get("name") or "sem nome",
                kwp=m.get("capacity_kwp"),
                estacoes=[e.get("name") for e in (m.get("stations") or []) if e.get("name")],
                plant_link_id=casada.id if casada else None,
                usina_nome=casada.nome if casada else None,
            )
        )
    return MicroCatalogoOut(micro=saida)


class MicroVinculoIn(BaseModel):
    #: A usina DESTA empresa que recebe a micro. `null` descasa.
    plant_link_id: int | None = None


@router.put("/micro-usinas/{micro_id}", response_model=MicroUsinaOut)
def casar_micro_usina(
    micro_id: int,
    body: MicroVinculoIn,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> MicroUsinaOut:
    """Diz que esta micro usina é aquela usina daqui — ou desfaz o par.

    Uma micro pertence a UMA usina: casá-la com a segunda desfaria o primeiro par em
    silêncio, e o aviso de parada passaria a chegar em nome da usina errada. Por isso o
    par anterior é recusado com o nome de quem o tem.
    """
    empresa_id = svc.empresa_exigida(gerente)

    # A busca é GLOBAL, não só nesta empresa: duas empresas apontando para a mesma micro
    # fazem `motor._coletar_parada_micro` distribuir o alerta real de uma como se fosse da
    # outra — ele lê o MICRO com a credencial da plataforma e mapeia por `mw_micro_plant_id`
    # sem recorte. `salvar_usina` já confere assim; aqui faltava.
    ja_casada = db.scalar(
        select(PlantLink).where(PlantLink.mw_micro_plant_id == micro_id)
    )
    if ja_casada is not None and ja_casada.empresa_id != empresa_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Esta micro usina já está em uma usina de outra empresa da plataforma.",
        )

    if body.plant_link_id is None:
        if ja_casada is not None:
            ja_casada.mw_micro_plant_id = None
            db.commit()
        return MicroUsinaOut(id=micro_id, nome="")

    usina = db.get(PlantLink, body.plant_link_id)
    if usina is None or usina.empresa_id != empresa_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada nesta empresa.")

    if ja_casada is not None and ja_casada.id != usina.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Esta micro usina já está em “{ja_casada.nome}”. Desfaça lá antes.",
        )
    if usina.mw_micro_plant_id is not None and usina.mw_micro_plant_id != micro_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{usina.nome}” já tem outra micro usina. Desfaça aquele par antes.",
        )

    usina.mw_micro_plant_id = micro_id
    db.commit()
    return MicroUsinaOut(
        id=micro_id, nome="", plant_link_id=usina.id, usina_nome=usina.nome
    )


class OcultarIn(BaseModel):
    """Qual usina sumir da lista. Um dos três, o mesmo que a identifica no produto."""

    mw_slug: str | None = None
    mp_usina_id: int | None = None
    mw_micro_plant_id: int | None = None


def _chave_oculta(body: OcultarIn) -> tuple[Produto, str]:
    if body.mw_slug:
        return (Produto.MEUWATT, body.mw_slug)
    if body.mp_usina_id is not None:
        return (Produto.MEUPLANO, str(body.mp_usina_id))
    if body.mw_micro_plant_id is not None:
        return (Produto.MEUWATT, f"micro:{body.mw_micro_plant_id}")
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Diga qual usina ocultar.")


@router.post("/usinas/ocultar", status_code=204)
def ocultar_usina(
    body: OcultarIn, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> None:
    """Tira esta usina da lista de trazer — só para esta empresa, e só nesta tela.

    Não apaga nada, não sai do produto de origem e não muda o que ninguém vê no
    aplicativo. É preferência de tela, e é reversível.
    """
    empresa_id = svc.empresa_exigida(gerente)
    produto, identificador = _chave_oculta(body)

    ja = db.scalar(
        select(UsinaOculta).where(
            UsinaOculta.empresa_id == empresa_id,
            UsinaOculta.produto == produto,
            UsinaOculta.identificador == identificador,
        )
    )
    if ja is None:
        db.add(
            UsinaOculta(empresa_id=empresa_id, produto=produto, identificador=identificador)
        )
        db.commit()


class UsinaOcultaOut(BaseModel):
    produto: str
    identificador: str
    ocultada_em: datetime


@router.get("/usinas/ocultas", response_model=list[UsinaOcultaOut])
def listar_ocultas(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[UsinaOcultaOut]:
    """O que foi escondido, para poder voltar. Sem esta lista, ocultar seria definitivo na
    prática — e ninguém lembraria o nome do que escondeu."""
    empresa_id = svc.empresa_exigida(gerente)
    return [
        UsinaOcultaOut(
            produto=o.produto.value, identificador=o.identificador, ocultada_em=o.ocultada_em
        )
        for o in db.scalars(
            select(UsinaOculta)
            .where(UsinaOculta.empresa_id == empresa_id)
            .order_by(UsinaOculta.identificador)
        ).all()
    ]


@router.delete("/usinas/ocultas", status_code=204)
def mostrar_todas(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> None:
    """Volta a mostrar TODAS. Uma só de cada vez exigiria a tela guardar o identificador de
    cada oculta; trazer tudo de volta e esconder de novo o que não serve é menos passos
    para quem se arrependeu."""
    empresa_id = svc.empresa_exigida(gerente)
    for o in db.scalars(select(UsinaOculta).where(UsinaOculta.empresa_id == empresa_id)).all():
        db.delete(o)
    db.commit()


# ------------------------------- o gerente cuida das contas da empresa dele


class UsuarioDetalhado(BaseModel):
    """Uma conta da empresa, com o que o gerente precisa para operá-la."""

    id: int
    nome: str
    apelido: str
    perfil: str
    ativo: bool
    email: str | None = None
    #: Quantas usinas esta pessoa recebe no aplicativo.
    usinas: int = 0
    #: Em quais produtos a conta DELA está conectada. Vazio é o normal no aplicativo (o
    #: cliente lê com o token da empresa); o ASSISTENTE só responde com o token dela.
    produtos: list[str] = []
    #: De quem é cada token, como o PRODUTO respondeu ao conferi-lo (`{"meuwatt": "Renan"}`):
    #: é o que torna visível um token colado na conta da pessoa errada.
    tokens_de: dict[str, str] = {}
    #: Celular, para a tela: `(17) 9 9737-7626`.
    telefone: str | None = None
    #: O que o assistente do WhatsApp responde a esta pessoa, por produto.
    bot_meuplano: bool = False
    bot_meuwatt: bool = False
    bot_helper: bool = False
    #: Tem a SENHA DE ATUAÇÃO que o bot pede antes de ação no equipamento (helper); o meuPlano confirma com SIM.
    tem_senha_atuacao: bool = False
    #: A pessoa do meuPlano a que o cadastro está ligado (nome), ou nulo: cadastro só daqui.
    meuplano: str | None = None
    #: A conta é de OUTRA empresa e também desta (usuário em mais de uma empresa): o nome
    #: da empresa que cuida dela. Daqui só se concedem as usinas desta empresa; senha,
    #: celular, tokens e bot são de lá. Nulo = a conta é desta empresa.
    cuidada_por: str | None = None
    #: Cadastro ainda sem ligação, e há na organização da empresa no meuPlano uma pessoa
    #: livre com o MESMO e-mail: o "ligar" sugerido (puxa nome, e-mail e celular de lá).
    sugestao_meuplano: str | None = None
    sugestao_meuplano_id: int | None = None


def _contas_detalhadas(db: Session, empresa_id: int):
    """O que a lista de Usuários lê do banco, em três idas: as contas da empresa com quantas
    usinas cada uma recebe, as empresas e os vínculos (os das contas daqui — tokens, ligação —
    e TODOS os do meuPlano: quem lá já está ligado a alguém não é sugerido de novo)."""
    # Só as usinas DESTA empresa (e as sem dono): a que o dono recebe de outra não é daqui.
    n_usinas = (
        select(func.count(UserPlantAccess.plant_link_id))
        .join(PlantLink, PlantLink.id == UserPlantAccess.plant_link_id)
        .where(UserPlantAccess.user_id == User.id,
               (PlantLink.empresa_id == empresa_id) | PlantLink.empresa_id.is_(None))
        .correlate(User)
        .scalar_subquery()
    )
    linhas = db.execute(
        select(User, n_usinas)
        .where(svc.contas_da_empresa(empresa_id), User.perfil.not_in(pessoas.DA_PLATAFORMA))
        .order_by(User.nome)
    ).all()
    if not linhas:
        return [], {}, [], []
    contas = [u for u, _ in linhas]
    vinculos = db.scalars(select(VinculoProduto).where(
        VinculoProduto.gs_user_id.in_([c.id for c in contas])
        | (VinculoProduto.produto == Produto.MEUPLANO.value))).all()
    return contas, {u.id: n for u, n in linhas}, db.scalars(select(Empresa)).all(), vinculos


@router.get("/usuarios/detalhados", response_model=list[UsuarioDetalhado])
async def usuarios_detalhados(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[UsuarioDetalhado]:
    """Quem é da empresa, com concessões e conexões — a lista que a tela opera. Antes, traz
    do meuPlano o que mudou lá no cadastro de quem está ligado (base única)."""
    from app.services import cadastro
    empresa_id = svc.empresa_exigida(gerente)
    # O meuPlano (rede) corre enquanto o banco é lido numa thread: as duas esperas se
    # sobrepõem em vez de somar (a tela levava 3,6 s — avaliação 10; cada ida ao banco, nos
    # EUA, custa ~200 ms).
    pessoas_t = await cadastro.pessoas_ao_fundo(db, empresa_id)
    contas, quantas, empresas, vinculos = await asyncio.to_thread(_contas_detalhadas, db, empresa_id)
    pessoas_mp = await pessoas_t
    if not contas:
        return []
    por_id = {c.id: c for c in contas}
    # `empresas` fica viva até o fim: sem ela no mapa de identidade, o `db.get` de `sugestoes`
    # voltava ao banco.
    nomes = {e.id: e.nome for e in empresas}
    do_mp = [v for v in vinculos if v.produto == Produto.MEUPLANO.value]
    # Base única: o que mudou no meuPlano chega às contas ANTES de a lista sair.
    await cadastro.sincronizar(db, empresa_id, pessoas_mp, ligadas=[
        (por_id[v.gs_user_id], v.usuario_remoto_id) for v in do_mp
        if v.gs_user_id in por_id and por_id[v.gs_user_id].empresa_id == empresa_id])
    sugeridas = cadastro.sugestoes(db, empresa_id, pessoas_mp, [c for c in contas if c.empresa_id == empresa_id],
                                   ligadas=[(v.usuario_remoto_id, v.gs_user_id) for v in do_mp])

    conectados: dict[int, list[str]] = {}
    tokens_de: dict[int, dict[str, str]] = {}
    ligado_mp: dict[int, str] = {}
    for v in vinculos:
        if v.gs_user_id not in por_id:
            continue
        if v.produto == Produto.MEUPLANO.value:
            ligado_mp[v.gs_user_id] = v.usuario_remoto_nome or v.usuario_remoto_email or v.usuario_remoto_id
        # Só TOKEN é conta própria: ligar o cadastro à pessoa do meuPlano não muda com que
        # credencial se lê (continua a da empresa).
        if not v.token_cifrado:
            continue
        # `VinculoProduto.produto` é TEXTO no banco, e não o enum `Produto` — diferente de
        # `Integracao.produto`, que é `Enum(...)`. Chamar `.value` aqui estourava 500 na
        # tela inteira, e o traço dos dois modelos é parecido o bastante para enganar.
        conectados.setdefault(v.gs_user_id, []).append(str(v.produto))
        tokens_de.setdefault(v.gs_user_id, {})[str(v.produto)] = (
            v.usuario_remoto_nome or v.usuario_remoto_email or f"id {v.usuario_remoto_id}"
        )

    return [
        UsuarioDetalhado(
            id=c.id,
            nome=c.nome,
            apelido=c.apelido,
            perfil=c.perfil.value,
            ativo=c.ativo,
            email=c.email,
            usinas=quantas.get(c.id, 0),
            produtos=sorted(conectados.get(c.id, [])),
            tokens_de=tokens_de.get(c.id, {}),
            telefone=exibir_telefone(c.telefone),
            bot_meuplano=c.bot_meuplano, bot_meuwatt=c.bot_meuwatt, bot_helper=c.bot_helper,
            tem_senha_atuacao=bool(c.senha_atuacao_hash),
            meuplano=ligado_mp.get(c.id),
            cuidada_por=nomes.get(c.empresa_id) if c.empresa_id != empresa_id else None,
            sugestao_meuplano=(
                " · ".join(x for x in (sugeridas[c.id].get("name"), sugeridas[c.id].get("phone")) if x)
                or sugeridas[c.id].get("email")
            ) if c.id in sugeridas else None,
            sugestao_meuplano_id=sugeridas[c.id].get("id") if c.id in sugeridas else None,
        )
        for c in contas
    ]


class ConectarClienteIn(BaseModel):
    token: str = Field(min_length=1)


class ConexaoDoClienteOut(BaseModel):
    ok: bool
    detalhe: str


@router.put("/usuarios/{usuario_id}/conexoes/{produto}", response_model=ConexaoDoClienteOut)
async def conectar_conta_do_cliente(
    usuario_id: int,
    produto: Produto,
    body: ConectarClienteIn,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> ConexaoDoClienteOut:
    """Cola o token PESSOAL deste cliente no produto.

    Opcional no aplicativo — sem ele, o Gestão Solar lê os dados dele com a credencial da
    empresa, e a concessão é que decide o que aparece. OBRIGATÓRIO no assistente do
    WhatsApp, que só lê com o token da própria pessoa (`cadastro.liberar_bot`). Com ele, a leitura passa a acontecer **como o
    cliente**: as usinas que ele enxergaria lá, pela regra de lá, e o produto passa a
    aceitar que ele ENTRE com a senha daqui.

    Responde 200 mesmo quando o token é recusado, com `ok: false` e o motivo: o erro é do
    valor colado, não da requisição, e a tela precisa da frase inteira — um 400 viraria
    "Erro 400" em qualquer tratamento genérico pelo caminho.
    """
    empresa_id = svc.empresa_exigida(gerente)
    conta = _conta_da_empresa(db, usuario_id, empresa_id)

    r = await vinculos.conectar(db, conta, produto, body.token, por=gerente)
    return ConexaoDoClienteOut(ok=r.ok, detalhe=r.detalhe)


@router.delete("/usuarios/{usuario_id}/conexoes/{produto}", status_code=204)
def desconectar_conta_do_cliente(
    usuario_id: int,
    produto: Produto,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> None:
    """Para de usar o token pessoal dele — a leitura volta a ser com a credencial da
    empresa. **Não revoga nada** no produto de origem."""
    empresa_id = svc.empresa_exigida(gerente)
    conta = _conta_da_empresa(db, usuario_id, empresa_id)

    vinculo = vinculos.obter(db, conta.id, produto)
    if vinculo is None:
        return
    if produto is Produto.MEUPLANO:
        # A MESMA linha guarda a ligação do cadastro com a pessoa do meuPlano (base única):
        # tirar o token não desfaz a ligação — para isso há "Desligar", no Cadastro.
        vinculo.token_cifrado = vinculo.token_prefixo = vinculo.token_gravado_em = None
        vinculo.estado, vinculo.detalhe, vinculo.usinas_visiveis = "nunca", None, None
        vinculo.login_externo_em = None
    else:
        db.delete(vinculo)
    db.commit()


class ContaPatch(BaseModel):
    ativo: bool | None = None
    senha: str | None = None
    #: Cadastro. Ligado ao meuPlano, grava lá também (ver services/cadastro).
    nome: str | None = Field(default=None, min_length=2)
    email: EmailStr | None = None
    #: Celular. Vazio ("") apaga — e apagar o celular desliga o bot junto.
    telefone: str | None = None
    #: Acesso ao assistente do WhatsApp, por produto. Só liga com celular cadastrado.
    bot_meuplano: bool | None = None
    bot_meuwatt: bool | None = None
    bot_helper: bool | None = None
    #: A SENHA DE ATUAÇÃO (6 a 8 números) que o bot pede antes de ligar, desligar, gravar ou
    #: criar. O gerente define e entrega à pessoa, como a senha provisória.
    senha_atuacao: str | None = None


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioDetalhado)
async def editar_conta_da_empresa(
    usuario_id: int,
    body: ContaPatch,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> UsuarioDetalhado:
    """Desativa, reativa ou redefine a senha de quem é da empresa.

    A própria conta é recusada: desativar a si mesmo tranca o gerente para fora no mesmo
    instante, e a saída seria a plataforma.
    """
    empresa_id = svc.empresa_exigida(gerente)
    conta = _conta_da_empresa(db, usuario_id, empresa_id)
    if conta.id == gerente.id and body.ativo is False:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Você ficaria sem acesso no mesmo instante."
        )
    if body.ativo is False:
        # A conta pode ser a única gerente de OUTRA empresa em que também está.
        svc.exigir_outro_gerente_em_todas(db, conta)

    if body.ativo is not None:
        conta.ativo = body.ativo
    if body.senha:
        if len(body.senha) < 8:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A senha precisa de pelo menos 8 caracteres."
            )
        conta.senha_hash = await asyncio.to_thread(gerar_hash_senha, body.senha)
    if body.senha_atuacao is not None:
        from app.services import assistente_helper

        try:
            limpa = assistente_helper.validar_senha_atuacao(body.senha_atuacao)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        conta.senha_atuacao_hash = await asyncio.to_thread(gerar_hash_senha, limpa)
        assistente_helper.nova_senha(conta.id)
    if body.nome is not None or body.email is not None or body.telefone is not None:
        from app.services import cadastro
        await cadastro.gravar(db, conta, empresa_id, nome=body.nome,
                              email=str(body.email) if body.email else None, telefone=body.telefone)
    from app.services import cadastro
    for campo in ("bot_meuplano", "bot_meuwatt", "bot_helper"):
        if getattr(body, campo) is not None:
            cadastro.liberar_bot(conta, campo, getattr(body, campo))
    db.commit()

    return UsuarioDetalhado(
        id=conta.id,
        nome=conta.nome,
        apelido=conta.apelido,
        perfil=conta.perfil.value,
        ativo=conta.ativo,
        email=conta.email,
        usinas=db.scalar(
            select(func.count())
            .select_from(UserPlantAccess)
            .where(UserPlantAccess.user_id == conta.id)
        )
        or 0,
        telefone=exibir_telefone(conta.telefone),
        bot_meuplano=conta.bot_meuplano, bot_meuwatt=conta.bot_meuwatt, bot_helper=conta.bot_helper,
        tem_senha_atuacao=bool(conta.senha_atuacao_hash),
        meuplano=_nome_no_meuplano(db, conta.id),
    )


def _nome_no_meuplano(db: Session, conta_id: int) -> str | None:
    from app.services import cadastro
    v = cadastro.vinculo_meuplano(db, conta_id)
    return (v.usuario_remoto_nome or v.usuario_remoto_email or v.usuario_remoto_id) if v else None


# ── cadastro com o meuPlano como base (ver services/cadastro) ────────────────


class PessoaMeuPlanoOut(BaseModel):
    id: int
    nome: str | None = None
    email: str | None = None
    telefone: str | None = None
    ativo: bool = True
    #: apelido da conta daqui já ligada a esta pessoa, ou nulo
    ligada_a: str | None = None


@router.get("/meuplano/pessoas", response_model=list[PessoaMeuPlanoOut])
async def pessoas_do_meuplano(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[PessoaMeuPlanoOut]:
    """As pessoas que a empresa administra no meuPlano — para puxar o cadastro."""
    from app.services import cadastro
    return [PessoaMeuPlanoOut(**p) for p in await cadastro.pessoas_do_meuplano(db, svc.empresa_exigida(gerente))]


class LigarIn(BaseModel):
    mp_user_id: int


class LigarOut(BaseModel):
    usuario: UsuarioDetalhado
    #: o que não pôde vir do meuPlano (ex.: celular já usado por outra conta)
    avisos: list[str] = []


@router.put("/usuarios/{usuario_id}/meuplano", response_model=LigarOut)
async def ligar_ao_meuplano(
    usuario_id: int, body: LigarIn, db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> LigarOut:
    """Liga o cadastro desta conta à pessoa do meuPlano e puxa nome, e-mail e celular de lá."""
    from app.services import cadastro
    empresa_id = svc.empresa_exigida(gerente)
    conta = _conta_da_empresa(db, usuario_id, empresa_id)
    avisos = await cadastro.ligar(db, conta, empresa_id, body.mp_user_id)
    return LigarOut(usuario=await editar_conta_da_empresa(usuario_id, ContaPatch(), db, gerente), avisos=avisos)


@router.delete("/usuarios/{usuario_id}/meuplano", response_model=UsuarioDetalhado)
async def desligar_do_meuplano(
    usuario_id: int, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual),
) -> UsuarioDetalhado:
    """Desfaz a ligação do cadastro (o cadastro daqui fica como está)."""
    from app.services import cadastro
    conta = _conta_da_empresa(db, usuario_id, svc.empresa_exigida(gerente))
    cadastro.desligar(db, conta)
    return await editar_conta_da_empresa(usuario_id, ContaPatch(), db, gerente)


class ConcedidaOut(BaseModel):
    plant_link_id: int
    nome: str
    #: É da empresa de quem concede. `false` é uma concessão herdada: a usina foi dada
    #: antes do multiempresa e nunca foi trazida para empresa nenhuma. A tela precisa
    #: mostrá-la — senão ela vai junto no "salvar" e volta como erro sem nome.
    da_empresa: bool


@router.get("/usuarios/{usuario_id}/usinas", response_model=list[ConcedidaOut])
def usinas_do_usuario(
    usuario_id: int, db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[ConcedidaOut]:
    """As usinas que esta pessoa recebe hoje, e se cada uma é mesmo da empresa.

    A tela precisa disto antes de salvar: a gravação é a lista COMPLETA, e uma tela que
    abrisse com tudo desmarcado apagaria a concessão inteira no primeiro clique.

    E precisa do `da_empresa` porque existe concessão HERDADA — usina concedida antes de o
    sistema ser multiempresa, que nunca foi trazida para ninguém. Ela aparece marcada como
    tal, para o gerente resolver: trazer a usina, ou tirar a concessão.
    """
    empresa_id = svc.empresa_exigida(gerente)
    conta = _membro_da_empresa(db, usuario_id, empresa_id)

    # A usina que ela recebe de OUTRA empresa não aparece aqui — nem o nome: não é deste
    # gerente, e o "salvar" desta tela não mexe nela (`clientes.definir_usinas`).
    linhas = db.execute(
        select(PlantLink.id, PlantLink.nome, PlantLink.empresa_id)
        .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
        .where(
            UserPlantAccess.user_id == conta.id,
            (PlantLink.empresa_id == empresa_id) | PlantLink.empresa_id.is_(None),
        )
        .order_by(PlantLink.nome)
    ).all()
    return [
        ConcedidaOut(plant_link_id=i, nome=n, da_empresa=(e == empresa_id))
        for i, n, e in linhas
    ]


# ------------------------------------------------------------- o bot da empresa


class BotOuvindoOut(BaseModel):
    ouvindo: bool
    resumo: str
    #: O helper (ler e comandar as usinas pelo bot) responde agora? `None` = não configurado.
    helper_alcancavel: bool | None = None
    helper_resumo: str | None = None


@router.get("/bot/saude", response_model=BotOuvindoOut)
async def bot_ouvindo(
    db: Session = Depends(get_db), _gerente: User = Depends(gestor_empresa_atual)
) -> BotOuvindoOut:
    """Se o bot está recebendo as mensagens. O número é da plataforma, e o conserto também:
    ao gerente basta saber que a falta de resposta NÃO é o cadastro dele (o detalhe técnico
    fica no Log do bot do adm-gs)."""
    s = await saude_atual(db)
    helper = {"helper_alcancavel": s.helper_alcancavel, "helper_resumo": s.helper_resumo}
    if s.ouvindo:
        return BotOuvindoOut(ouvindo=True, resumo="O bot está recebendo as mensagens.", **helper)
    return BotOuvindoOut(
        ouvindo=False,
        resumo=("O bot não está recebendo as mensagens agora. É o canal da plataforma, não o "
                "cadastro de vocês — a administração do Gestão Solar vê o mesmo aviso."),
        **helper,
    )


@router.get("/bot/registros", response_model=list[RegistroBotOut])
def log_do_bot_da_empresa(
    limite: int = 100,
    db: Session = Depends(get_db),
    gerente: User = Depends(gestor_empresa_atual),
) -> list[RegistroBotOut]:
    """O que o assistente do WhatsApp recebeu e respondeu às pessoas que ESTA empresa cuida
    (a de origem da conta na hora da mensagem) — é o gerente que libera o bot, e é aqui que
    ele vê por que alguém ficou sem resposta. Conversa de outra empresa não aparece."""
    return registros_do_bot(db, empresa_id=svc.empresa_exigida(gerente), limite=limite)
