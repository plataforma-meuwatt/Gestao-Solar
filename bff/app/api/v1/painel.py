"""API do painel: entrada, pontes com os produtos e conciliação de usinas.

A gestão de clientes vive em `painel_clientes.py`.

Tudo aqui exige `gestor_atual` — sessão de escopo `painel`, perfil que abre o painel. O
que mexe em credencial de serviço sobe para `administrador_atual`.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    administrador_atual,
    conferir_senha,
    criar_token_painel,
    gestor_atual,
)
from app.models.integracao import Produto
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import conciliacao, integracoes, sonda

router = APIRouter(prefix="/api/painel", tags=["painel"])


# ----------------------------------------------------------------------- entrada


class EntrarIn(BaseModel):
    apelido: str
    senha: str


class EntrarOut(BaseModel):
    token: str
    expira_em: datetime
    nome: str
    apelido: str
    perfil: str


@router.post("/entrar", response_model=EntrarOut)
def entrar(body: EntrarIn, db: Session = Depends(get_db)) -> EntrarOut:
    # Um apelido malformado é só um apelido que não existe: normaliza o que dá e deixa a
    # busca falhar. Responder "formato inválido" aqui contaria a quem tenta adivinhar que
    # o formato importa, e o `.strip().lower()` é o que faz "Renan " entrar como `renan`.
    procurado = (body.apelido or "").strip().lower()
    usuario = db.scalar(select(User).where(User.apelido == procurado))

    # Mensagem única para conta inexistente, senha errada e perfil sem acesso ao painel:
    # quem tenta adivinhar não aprende qual das três aconteceu.
    if (
        usuario is None
        or not usuario.ativo
        or not usuario.abre_painel
        or not conferir_senha(body.senha, usuario.senha_hash)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Apelido ou senha inválidos")

    usuario.ultimo_login = datetime.now(UTC)
    db.commit()

    token, expira = criar_token_painel(usuario.id)
    # O perfil vai na resposta para a barra lateral esconder o que atendimento não abre.
    # É conforto de interface, não segurança: o backend recusa de qualquer forma.
    return EntrarOut(
        token=token,
        expira_em=expira,
        nome=usuario.nome,
        apelido=usuario.apelido,
        perfil=usuario.perfil.value,
    )


# ------------------------------------------------------------------- integrações


class IntegracaoOut(BaseModel):
    produto: str
    configurada: bool
    base_url: str | None = None
    usuario_servico: str | None = None
    estado: str
    detalhe: str | None = None
    testada_em: datetime | None = None
    usinas_visiveis: int | None = None
    # Como esta ponte se autentica. `False` = linha antiga, por conta de serviço — a tela
    # mostra o aviso de migração em cima dela.
    por_token: bool = False
    token_prefixo: str | None = None
    token_dono_nome: str | None = None
    token_dono_email: str | None = None
    token_gravado_em: datetime | None = None


class IntegracaoIn(BaseModel):
    base_url: str = Field(min_length=4)
    usuario_servico: str = Field(min_length=3)
    # Vazia mantém a que já está gravada — é o que permite corrigir o endereço sem
    # redigitar a credencial.
    senha: str | None = None


class TokenIn(BaseModel):
    base_url: str = Field(min_length=4)
    #: O valor colado pelo gestor. Sem `min_length` apertado de propósito: quem valida é
    #: `core/tokens_produto`, que sabe dizer POR QUE está errado — "faltam caracteres" é
    #: uma resposta melhor do que um 422 do Pydantic dizendo "string curta".
    token: str = Field(min_length=1)


class EventoOut(BaseModel):
    evento: str
    ocorrido_em: datetime
    ator_email: str | None = None
    token_prefixo: str | None = None
    detalhe: str | None = None
    usinas_visiveis: int | None = None


def _integracao_out(produto: Produto, integracao) -> IntegracaoOut:
    if integracao is None:
        return IntegracaoOut(produto=produto.value, configurada=False, estado="nunca")
    return IntegracaoOut(
        produto=produto.value,
        configurada=True,
        base_url=integracao.base_url,
        usuario_servico=integracao.usuario_servico,
        estado=integracao.estado.value,
        detalhe=integracao.detalhe_teste,
        testada_em=integracao.testada_em,
        usinas_visiveis=integracao.usinas_visiveis,
        por_token=integracao.por_token,
        token_prefixo=integracao.token_prefixo,
        token_dono_nome=integracao.token_dono_nome,
        token_dono_email=integracao.token_dono_email,
        token_gravado_em=integracao.token_gravado_em,
    )


@router.get("/integracoes", response_model=list[IntegracaoOut])
def listar_integracoes(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[IntegracaoOut]:
    return [_integracao_out(p, i) for p, i in integracoes.listar(db).items()]


@router.put("/integracoes/{produto}", response_model=IntegracaoOut)
def salvar_integracao(
    produto: Produto,
    body: IntegracaoIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> IntegracaoOut:
    """Caminho ANTIGO, por conta de serviço. Mantido para não quebrar o que já está
    gravado; a tela oferece o token."""
    try:
        integracao = integracoes.salvar(
            db, produto, body.base_url, body.usuario_servico, body.senha,
            ator_email=usuario.identificacao,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return _integracao_out(produto, integracao)


class TesteOut(BaseModel):
    ok: bool
    detalhe: str
    usinas_visiveis: int | None = None
    #: De quem é o token que respondeu. A tela mostra isto ao lado do resultado porque
    #: "conectado" com a pessoa errada é um sucesso enganoso.
    dono_nome: str | None = None
    dono_email: str | None = None


@router.post("/integracoes/{produto}/testar", response_model=TesteOut)
async def testar_integracao(
    produto: Produto,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> TesteOut:
    resultado = await integracoes.testar(db, produto, ator_email=usuario.identificacao)
    return TesteOut(
        ok=resultado.ok,
        detalhe=resultado.detalhe,
        usinas_visiveis=resultado.usinas,
        dono_nome=resultado.dono_nome,
        dono_email=resultado.dono_email,
    )


@router.put("/integracoes/{produto}/token", response_model=TesteOut)
async def conectar_por_token(
    produto: Produto,
    body: TokenIn,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> TesteOut:
    """Cola um token pessoal e conecta.

    Responde com o resultado do teste, não com a integração: o que o gestor precisa
    saber neste instante é se funcionou e como quem. Se não funcionou, nada foi gravado
    — a conexão anterior continua de pé (ver `integracoes.salvar_token`).
    """
    resultado = await integracoes.salvar_token(
        db, produto, body.base_url, body.token, ator_email=usuario.identificacao
    )
    return TesteOut(
        ok=resultado.ok,
        detalhe=resultado.detalhe,
        usinas_visiveis=resultado.usinas,
        dono_nome=resultado.dono_nome,
        dono_email=resultado.dono_email,
    )


@router.delete("/integracoes/{produto}/token", response_model=IntegracaoOut)
def desconectar_token(
    produto: Produto,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> IntegracaoOut:
    """Para de usar o token deste lado. NÃO o revoga no produto de origem — só quem o
    emitiu pode fazer isso, lá. A tela avisa, porque a diferença importa."""
    integracoes.remover_token(db, produto, ator_email=usuario.identificacao)
    return _integracao_out(produto, integracoes.obter(db, produto))


class RotaSondadaOut(BaseModel):
    chave: str
    metodo: str
    caminho: str
    alimenta: str
    essencial: bool
    situacao: str
    status: int | None = None
    ms: int | None = None
    detalhe: str | None = None
    itens: int | None = None
    campos: list[str] = []


class VarreduraOut(BaseModel):
    produto: str
    base_url: str | None = None
    ok: bool
    detalhe: str
    executada_em: datetime
    rotas: list[RotaSondadaOut] = []


@router.get("/integracoes/{produto}/rotas", response_model=VarreduraOut)
def listar_rotas(
    produto: Produto, _: User = Depends(gestor_atual)
) -> VarreduraOut:
    """O catálogo, sem bater em nada.

    Existe separado da varredura porque a lista tem valor sozinha: é o inventário do que
    este sistema depende no produto de origem. Abre instantâneo, e serve de referência
    mesmo com a ponte fora do ar.
    """
    return VarreduraOut(
        produto=produto.value,
        ok=True,
        detalhe=f"{len(sonda.CATALOGO[produto])} rotas catalogadas. Nenhuma foi chamada.",
        executada_em=datetime.now(UTC),
        rotas=[
            RotaSondadaOut(
                chave=r.chave,
                metodo=r.metodo,
                caminho=r.caminho,
                alimenta=r.alimenta,
                essencial=r.essencial,
                situacao="nao_sondada" if not r.sonda else "pendente",
                detalhe=r.nao_sondada_porque,
            )
            for r in sonda.CATALOGO[produto]
        ],
    )


@router.post("/integracoes/{produto}/rotas/sondar", response_model=VarreduraOut)
async def sondar_rotas(
    produto: Produto,
    db: Session = Depends(get_db),
    usuario: User = Depends(administrador_atual),
) -> VarreduraOut:
    """Exercita o catálogo inteiro com o token gravado.

    Restrito a administrador, e não a qualquer gestor: a varredura é uma dúzia de
    requisições ao produto de terceiro e usa a credencial de serviço — não é uma tela de
    consulta que qualquer um abre sem consequência.

    Fica registrada no histórico da ponte para responder "quando foi a última vez que
    passou inteira?", que é a pergunta de quem investiga uma quebra.
    """
    varredura = await sonda.varrer(db, produto)

    integracoes.registrar_evento(
        db,
        produto,
        "sonda_ok" if varredura.ok else "sonda_falhou",
        ator_email=usuario.identificacao,
        detalhe=varredura.detalhe,
    )
    db.commit()

    return VarreduraOut(
        produto=varredura.produto,
        base_url=varredura.base_url,
        ok=varredura.ok,
        detalhe=varredura.detalhe,
        executada_em=varredura.executada_em,
        rotas=[RotaSondadaOut(**vars(r)) for r in varredura.rotas],
    )


@router.get("/integracoes/{produto}/eventos", response_model=list[EventoOut])
def historico_integracao(
    produto: Produto,
    db: Session = Depends(get_db),
    _: User = Depends(administrador_atual),
) -> list[EventoOut]:
    """O que já aconteceu com esta ponte. Responde "desde quando parou?", que o estado
    atual sozinho não responde."""
    return [
        EventoOut(
            evento=e.evento,
            ocorrido_em=e.ocorrido_em,
            ator_email=e.ator_email,
            token_prefixo=e.token_prefixo,
            detalhe=e.detalhe,
            usinas_visiveis=e.usinas_visiveis,
        )
        for e in integracoes.historico(db, produto)
    ]


# ---------------------------------------------------------------------- usinas


class UsinaOut(BaseModel):
    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    tem_meuwatt: bool
    tem_meuplano: bool
    dono_id: int | None = None
    dono_nome: str | None = None


@router.get("/usinas", response_model=list[UsinaOut])
def listar_usinas(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> list[UsinaOut]:
    """As usinas que o Gestão Solar conhece, e de quem é cada uma.

    Responde à pergunta que a conciliação não responde: *esta usina chega em alguém?* Uma
    usina casada nos dois lados e sem dono é invisível no aplicativo, e sem esta lista o
    gestor só descobriria isso pelo cliente reclamando.
    """
    donos = {
        pid: (uid, nome)
        for pid, uid, nome in db.execute(
            select(UserPlantAccess.plant_link_id, User.id, User.nome)
            .join(User, User.id == UserPlantAccess.user_id)
            .where(User.perfil == Perfil.CLIENTE)
        ).all()
    }

    saida = []
    for link in db.scalars(select(PlantLink).where(PlantLink.ativo).order_by(PlantLink.nome)).all():
        dono = donos.get(link.id)
        saida.append(
            UsinaOut(
                id=link.id,
                nome=link.nome,
                cidade=link.cidade,
                uf=link.uf,
                kwp=link.kwp,
                tem_meuwatt=link.tem_meuwatt,
                tem_meuplano=link.tem_meuplano,
                dono_id=dono[0] if dono else None,
                dono_nome=dono[1] if dono else None,
            )
        )
    return saida


# ------------------------------------------------------------------ conciliação


class UsinaLado(BaseModel):
    id: str
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None


class CandidatoOut(BaseModel):
    mp_usina_id: int
    nome: str
    pontos: float
    motivos: list[str]


class LinhaConciliacao(BaseModel):
    """Uma usina do inventário, com o que se sabe dela de cada lado.

    `plant_link_id` nulo = existe num produto e ainda não foi trazida para cá. É o estado
    inicial de tudo, e é o que distingue "não está no app" de "não existe".
    """

    chave: str
    nome: str
    plant_link_id: int | None = None
    mw_slug: str | None = None
    mw_nome: str | None = None
    mp_usina_id: int | None = None
    mp_nome: str | None = None
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    #: `ambos` · `meuwatt` · `meuplano`
    origem: str
    no_app: bool
    candidatos: list[CandidatoOut] = []
    #: Para uma usina só do meuPlano: de qual usina do meuWatt ela parece ser par. As duas
    #: linhas continuam separadas — o sistema não sabe que são a mesma —, mas o gestor não
    #: precisa cruzar os dois grupos a olho para descobrir.
    par_provavel_mw: str | None = None
    par_provavel_nome: str | None = None
    par_provavel_motivos: list[str] = []


class ConciliacaoOut(BaseModel):
    meuwatt: list[UsinaLado]
    meuplano: list[UsinaLado]
    linhas: list[LinhaConciliacao]
    aviso: str | None = None


def _linha_out(linha: conciliacao.Linha) -> LinhaConciliacao:
    return LinhaConciliacao(
        chave=linha.chave,
        nome=linha.nome,
        plant_link_id=linha.plant_link_id,
        mw_slug=linha.mw_slug,
        mw_nome=linha.mw_nome,
        mp_usina_id=linha.mp_usina_id,
        mp_nome=linha.mp_nome,
        cidade=linha.cidade,
        uf=linha.uf,
        kwp=linha.kwp,
        origem=linha.origem,
        no_app=linha.no_app,
        candidatos=[
            CandidatoOut(mp_usina_id=c.mp_usina_id, nome=c.nome, pontos=c.pontos, motivos=c.motivos)
            for c in linha.candidatos
        ],
        par_provavel_mw=linha.par_provavel_mw,
        par_provavel_nome=linha.par_provavel_nome,
        par_provavel_motivos=linha.par_provavel_motivos,
    )


@router.get("/conciliacao", response_model=ConciliacaoOut)
async def carregar_conciliacao(
    db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> ConciliacaoOut:
    """O inventário completo: o que já está no app, e o que existe nos produtos e não está.

    Inclui as usinas que existem **só no meuPlano** — manutenção sem monitoramento é um
    caso normal, e a versão anterior desta rota as omitia por percorrer apenas o meuWatt.
    """
    usinas_mw: list[dict[str, Any]] = []
    usinas_mp: list[dict[str, Any]] = []
    avisos: list[str] = []

    try:
        cliente_mw = await integracoes.cliente_meuwatt(db)
        usinas_mw = await cliente_mw.usinas()
    except Exception as exc:  # noqa: BLE001 — a tela precisa abrir mesmo com uma ponte fora
        avisos.append(f"meuWatt indisponível: {exc}")

    try:
        cliente_mp = await integracoes.cliente_meuplano(db)
        usinas_mp = await cliente_mp.usinas()
    except Exception as exc:  # noqa: BLE001
        avisos.append(f"meuPlano indisponível: {exc}")

    links = list(db.scalars(select(PlantLink)).all())
    linhas = conciliacao.montar(usinas_mw, usinas_mp, links)

    return ConciliacaoOut(
        meuwatt=[
            UsinaLado(
                id=u.get("slug", ""),
                nome=conciliacao.nome_de(u),
                cidade=u.get("city"),
                uf=u.get("state"),
                kwp=u.get("capacity_kwp") or u.get("total_capacity_kwp"),
            )
            for u in usinas_mw
        ],
        meuplano=[
            UsinaLado(
                id=str(u.get("id", "")),
                nome=conciliacao.nome_de(u),
                cidade=u.get("city") or u.get("cidade"),
                uf=u.get("uf") or u.get("state"),
                kwp=u.get("potencia_kwp") or u.get("capacity_kwp"),
            )
            for u in usinas_mp
        ],
        linhas=[_linha_out(l) for l in linhas],
        aviso=" · ".join(avisos) if avisos else None,
    )


class UsinaIn(BaseModel):
    """Uma usina do inventário, do jeito que o gestor a definiu.

    Os dois identificadores são opcionais e independentes: dá para gravar uma usina só do
    meuWatt, só do meuPlano, ou casada. O que não se aceita é nenhum dos dois — seria uma
    usina que não existe em lugar nenhum.
    """

    plant_link_id: int | None = None
    mw_slug: str | None = None
    mp_usina_id: int | None = None
    nome: str = Field(min_length=1)
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    #: Se ela entra no aplicativo. Desligada, continua existindo aqui com os vínculos e as
    #: concessões intactos — o gestor pode religá-la sem refazer nada.
    no_app: bool = True


def _conflito(db: Session, campo, valor, exceto_id: int | None) -> PlantLink | None:
    """Outra usina já usa este identificador? Dois vínculos apontando para a mesma usina de
    um produto misturariam os dados de duas plantas."""
    if valor is None:
        return None
    condicoes = [campo == valor]
    if exceto_id is not None:
        condicoes.append(PlantLink.id != exceto_id)
    return db.scalar(select(PlantLink).where(*condicoes))


@router.put("/conciliacao/usina", response_model=LinhaConciliacao)
def salvar_usina(
    body: UsinaIn, db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> LinhaConciliacao:
    """Cria ou atualiza uma usina do inventário — casando, descasando ou só ligando no app.

    É um endpoint só para as três coisas porque elas são a mesma operação vista de ângulos
    diferentes: gravar o estado desejado daquela usina. Separar em `vincular`,
    `desvincular` e `ativar` obrigaria a tela a chamar duas rotas para "trazer a usina do
    meuPlano para o app", com a chance de a segunda falhar depois da primeira.
    """
    if body.mw_slug is None and body.mp_usina_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A usina precisa existir em pelo menos um dos dois produtos.",
        )

    link = db.get(PlantLink, body.plant_link_id) if body.plant_link_id else None
    if body.plant_link_id and link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")

    alvo = link.id if link else None
    for campo, valor, produto in (
        (PlantLink.mw_plant_slug, body.mw_slug, "meuWatt"),
        (PlantLink.mp_usina_id, body.mp_usina_id, "meuPlano"),
    ):
        outro = _conflito(db, campo, valor, alvo)
        if outro is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Esta usina do {produto} já pertence a “{outro.nome}”. "
                "Desfaça o outro vínculo antes.",
            )

    if link is None:
        link = PlantLink(nome=body.nome)
        db.add(link)

    link.mw_plant_slug = body.mw_slug
    link.mp_usina_id = body.mp_usina_id
    link.nome = body.nome
    link.cidade = body.cidade
    link.uf = body.uf
    link.kwp = body.kwp
    link.ativo = body.no_app
    db.commit()
    db.refresh(link)

    return LinhaConciliacao(
        chave=f"link:{link.id}",
        nome=link.nome,
        plant_link_id=link.id,
        mw_slug=link.mw_plant_slug,
        mw_nome=link.nome if link.mw_plant_slug else None,
        mp_usina_id=link.mp_usina_id,
        mp_nome=link.nome if link.mp_usina_id else None,
        cidade=link.cidade,
        uf=link.uf,
        kwp=link.kwp,
        origem=("ambos" if link.mw_plant_slug and link.mp_usina_id
                else "meuwatt" if link.mw_plant_slug else "meuplano"),
        no_app=link.ativo,
    )


@router.delete("/conciliacao/usina/{plant_link_id}", status_code=204)
def remover_usina(
    plant_link_id: int, db: Session = Depends(get_db), _: User = Depends(gestor_atual)
) -> None:
    """Tira a usina do Gestão Solar de vez.

    Recusa enquanto houver cliente com ela concedida: apagar levaria junto o acesso dele
    por cascata, e o sintoma seria uma usina que sumiu do app sem ninguém ter mexido
    naquele cliente. Para tirar do ar sem perder nada, o caminho é desligar `no_app`.
    """
    link = db.get(PlantLink, plant_link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usina não encontrada.")

    donos = db.scalars(
        select(User.nome)
        .join(UserPlantAccess, UserPlantAccess.user_id == User.id)
        .where(UserPlantAccess.plant_link_id == plant_link_id)
    ).all()
    if donos:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{link.nome}” está concedida a {', '.join(donos)}. "
            "Tire a usina desse cliente antes, ou apenas desligue-a do aplicativo.",
        )

    db.delete(link)
    db.commit()
