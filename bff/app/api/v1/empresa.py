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
from app.core.security import gerar_hash_senha, gestor_empresa_atual
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

    Conta da plataforma é excluída pelo PERFIL, não pelo `empresa_id` nulo — que era o
    que este texto dizia e estava errado: `PUT /api/painel/empresas/{id}/carteira` grava
    empresa em qualquer conta, e um administrador com empresa gravada aparecia aqui.
    """
    usuarios = db.scalars(
        svc.no_escopo(select(User), User.empresa_id, gerente)
        .where(User.perfil.not_in(pessoas.DA_PLATAFORMA))
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
    if integracao.empresa_id != empresa_id:
        # A credencial que responde é a da PLATAFORMA (atalho da migração). O estado a
        # empresa precisa saber; QUEM gerou o token é de quem o gerou — nome, e-mail e
        # prefixo são identidade de outra conta, e a tela já diz o que importa com
        # `propria=False`.
        return ConexaoOut(
            produto=produto.value,
            configurada=True,
            estado=integracao.estado.value,
            propria=False,
        )
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
    criado.usuario.perfil = body.perfil
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

    cliente = _conta_da_empresa(db, cliente_id, empresa_id)

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
                    .where(PlantLink.empresa_id.is_(None), User.empresa_id == empresa_id)
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
        clientes.definir_usinas(db, cliente, body.plant_link_ids)
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
    #: Em quais produtos a conta DELA está conectada. Vazio é o normal: o cliente lê com
    #: o token da empresa, e o dele só existe quando ele tem conta lá.
    produtos: list[str] = []


@router.get("/usuarios/detalhados", response_model=list[UsuarioDetalhado])
def usuarios_detalhados(
    db: Session = Depends(get_db), gerente: User = Depends(gestor_empresa_atual)
) -> list[UsuarioDetalhado]:
    """Quem é da empresa, com concessões e conexões — a lista que a tela opera."""
    empresa_id = svc.empresa_exigida(gerente)
    contas = list(
        db.scalars(
            select(User)
            .where(
                User.empresa_id == empresa_id,
                User.perfil.not_in(pessoas.DA_PLATAFORMA),
            )
            .order_by(User.nome)
        ).all()
    )
    if not contas:
        return []

    ids = [c.id for c in contas]
    quantas = dict(
        db.execute(
            select(UserPlantAccess.user_id, func.count(UserPlantAccess.plant_link_id))
            .where(UserPlantAccess.user_id.in_(ids))
            .group_by(UserPlantAccess.user_id)
        ).all()
    )
    conectados: dict[int, list[str]] = {}
    for v in db.scalars(select(VinculoProduto).where(VinculoProduto.gs_user_id.in_(ids))).all():
        # `VinculoProduto.produto` é TEXTO no banco, e não o enum `Produto` — diferente de
        # `Integracao.produto`, que é `Enum(...)`. Chamar `.value` aqui estourava 500 na
        # tela inteira, e o traço dos dois modelos é parecido o bastante para enganar.
        conectados.setdefault(v.gs_user_id, []).append(str(v.produto))

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

    É opcional — sem ele, o Gestão Solar lê os dados dele com a credencial da empresa, e a
    concessão é que decide o que aparece. Com ele, a leitura passa a acontecer **como o
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
    if vinculo is not None:
        db.delete(vinculo)
        db.commit()


class ContaPatch(BaseModel):
    ativo: bool | None = None
    senha: str | None = None


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioDetalhado)
def editar_conta_da_empresa(
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

    if body.ativo is not None:
        conta.ativo = body.ativo
    if body.senha:
        if len(body.senha) < 8:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A senha precisa de pelo menos 8 caracteres."
            )
        conta.senha_hash = gerar_hash_senha(body.senha)
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
    )


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
    conta = _conta_da_empresa(db, usuario_id, empresa_id)

    linhas = db.execute(
        select(PlantLink.id, PlantLink.nome, PlantLink.empresa_id)
        .join(UserPlantAccess, UserPlantAccess.plant_link_id == PlantLink.id)
        .where(UserPlantAccess.user_id == conta.id)
        .order_by(PlantLink.nome)
    ).all()
    return [
        ConcedidaOut(plant_link_id=i, nome=n, da_empresa=(e == empresa_id))
        for i, n, e in linhas
    ]
