"""API do painel da plataforma (adm-gs): entrada, a sonda das rotas e o inventário de usinas.

A gestão de clientes vive em `painel_clientes.py`; empresas e seus usuários, em
`painel_empresas.py`.

**A plataforma não tem token** (regra do dono, 23/10/2026): quem lê o meuWatt e o meuPlano
é a conta de cada EMPRESA, colada pelo gerente dela no oem-gs. Por isso não há mais aqui
as "pontes com os produtos", e a sonda escolhe com a conexão de qual empresa sondar. Trazer
e casar usina também é do gerente (oem-gs → Usinas): o adm só vê o inventário, por empresa.

Tudo aqui exige uma sessão de escopo `painel`, e cada rota exige a ÁREA da tela que a
usa (`core/security.exige_area`, catálogo em `services/areas_painel`). Administrador
passa em todas por perfil; atendimento, só no que o administrador marcou em Usuários.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    conferir_senha,
    criar_token_painel,
    exige_area,
    gestor_atual,
)
from app.models.integracao import Produto
from app.models.empresa import Empresa
from app.models.plant import PlantLink
from app.models.user import Perfil, User, UserPlantAccess
from app.services import areas_painel, empresas, integracoes, pessoas, sonda

router = APIRouter(prefix="/api/painel", tags=["painel"])

#: As guardas deste arquivo, montadas uma vez: `rotas`, a sonda; `usinas`, o inventário.
EXIGE_ROTAS = exige_area("rotas")
EXIGE_USINAS = exige_area("usinas")


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
    #: Qual portão esta sessão abre: `painel` (plataforma), `empresa` (gerente da O&M) ou
    #: `tecnico` (só o WhatsApp dele).
    #: É o que o front usa para escolher o prefixo das chamadas e montar o menu — e é
    #: informação, não permissão: quem decide é o servidor, a cada requisição.
    escopo: str = "painel"
    #: O nome da empresa, quando a sessão é de empresa. Fica fixo no topo da tela: sem
    #: ele, quem opera duas contas cadastra o cliente na empresa errada e ninguém
    #: descobre no mesmo dia.
    empresa: str | None = None
    empresa_id: int | None = None
    #: As áreas que esta conta abre — já resolvidas (administrador vem com todas). É o que
    #: a barra lateral usa para montar o menu, e o que decide para onde o painel manda
    #: quem entra: sem isto, todo mundo cairia em Clientes, inclusive quem não a tem.
    areas: list[str] = []


@router.post("/entrar", response_model=EntrarOut)
def entrar(body: EntrarIn, db: Session = Depends(get_db)) -> EntrarOut:
    # Um apelido malformado é só um apelido que não existe: normaliza o que dá e deixa a
    # busca falhar. Responder "formato inválido" aqui contaria a quem tenta adivinhar que
    # o formato importa, e o `.strip().lower()` é o que faz "Renan " entrar como `renan`.
    procurado = (body.apelido or "").strip().lower()
    usuario = db.scalar(select(User).where(User.apelido == procurado))

    # Mensagem única para conta inexistente, senha errada e conta desativada: quem tenta
    # adivinhar não aprende qual das três aconteceu.
    if usuario is None or not usuario.ativo or not conferir_senha(body.senha, usuario.senha_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Apelido ou senha inválidos")

    # Senha CERTA e conta que não abre esta tela: aqui a frase muda, e de propósito.
    #
    # Quem provou a senha é o dono da conta — dizer-lhe onde entrar não ensina nada a
    # quem está adivinhando, porque adivinhar não passa da linha acima. Já o silêncio
    # custou caro: o dono criou uma conta de dono de usina, anotou a senha, tentou no
    # painel e leu "apelido ou senha inválidos". Passou a procurar defeito na senha, que
    # estava certa — só o endereço é que era outro.
    if not (usuario.abre_painel or usuario.abre_empresa or usuario.abre_tecnico):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta conta é de dono de usina: ela entra pelo aplicativo ou pelo portal do "
            "dono de usina, não por aqui. A senha está certa.",
        )

    # AUTENTICAR é uma coisa só; AUTORIZAR é que tem três portões. Por isso a porta de
    # entrada é única e o que muda é o token que sai dela: o gerente da O&M recebe uma
    # sessão de `escopo=empresa`, que `gestor_atual` recusa em toda rota de painel.
    empresa = None
    if usuario.abre_empresa or usuario.abre_tecnico:
        empresa = empresas.por_id(db, empresas.empresa_exigida(usuario))
        if not empresa.ativa:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Esta empresa está desativada na plataforma. Fale com quem a administra.",
            )

    usuario.ultimo_login = datetime.now(UTC)
    db.commit()

    if empresa is not None:
        # Gerente → `escopo=empresa`; técnico → `escopo=tecnico`. Quem escolhe é
        # `pessoas.emitir`, o mesmo da troca de papel, para as duas portas nunca divergirem.
        token, expira = pessoas.emitir(usuario)
        return EntrarOut(
            token=token,
            expira_em=expira,
            nome=usuario.nome,
            apelido=usuario.apelido,
            perfil=usuario.perfil.value,
            escopo=pessoas.escopo_do_perfil(usuario.perfil),
            empresa=empresa.nome,
            empresa_id=empresa.id,
        )

    token, expira = criar_token_painel(usuario.id)
    # Perfil e áreas vão na resposta para a barra lateral esconder o que a conta não abre.
    # É conforto de interface, não segurança: o backend recusa de qualquer forma.
    return EntrarOut(
        token=token,
        expira_em=expira,
        nome=usuario.nome,
        apelido=usuario.apelido,
        perfil=usuario.perfil.value,
        areas=sorted(areas_painel.efetivas(db, usuario)),
    )


class EuOut(BaseModel):
    nome: str
    apelido: str
    perfil: str
    areas: list[str]


@router.get("/eu", response_model=EuOut)
def eu(db: Session = Depends(get_db), gestor: User = Depends(gestor_atual)) -> EuOut:
    """Quem sou eu e o que abro, AGORA.

    Existe porque a sessão dura oito horas e o acesso muda no meio delas: sem esta rota,
    quem perdesse a área de WhatsApp continuaria vendo o item no menu até sair e entrar de
    novo — clicaria, tomaria 403 e leria isso como defeito do painel. A barra lateral
    consulta esta rota ao abrir, e o que ela responde manda no menu.
    """
    return EuOut(
        nome=gestor.nome,
        apelido=gestor.apelido,
        perfil=gestor.perfil.value,
        areas=sorted(areas_painel.efetivas(db, gestor)),
    )


# ------------------------------------------------------------------- a sonda


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
    produto: Produto, _: User = Depends(EXIGE_ROTAS)
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


@router.get("/helper/rotas", response_model=VarreduraOut)
async def rotas_do_helper(_: User = Depends(EXIGE_ROTAS)) -> VarreduraOut:
    """A porta do bot do HELPER na tela Rotas: declarada e não sondada — toda chamada dela
    exige o token da pessoa, e a plataforma não tem token. O alto diz se o túnel e a VPN até
    as usinas respondem agora (o mesmo selo do Log do bot)."""
    from app.services import assistente_helper

    alcancavel, resumo = await assistente_helper.alcancavel()
    return VarreduraOut(
        produto="helper",
        ok=bool(alcancavel),
        detalhe=resumo,
        executada_em=datetime.now(UTC),
        rotas=[
            RotaSondadaOut(chave=r.chave, metodo=r.metodo, caminho=r.caminho, alimenta=r.alimenta,
                           essencial=r.essencial, situacao="nao_sondada", detalhe=r.nao_sondada_porque)
            for r in sonda.HELPER
        ],
    )


@router.post("/integracoes/{produto}/rotas/sondar", response_model=VarreduraOut)
async def sondar_rotas(
    produto: Produto,
    empresa_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(EXIGE_ROTAS),
) -> VarreduraOut:
    """Exercita o catálogo inteiro com a conexão DESTA empresa (a plataforma não tem token).

    Só leitura, mas uma dúzia de requisições ao produto de terceiro — por isso área própria.
    Fica registrada no histórico da ponte para responder "quando foi a última vez que
    passou inteira?", que é a pergunta de quem investiga uma quebra.
    """
    empresas.por_id(db, empresa_id)
    varredura = await sonda.varrer(db, produto, empresa_id)

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


# ---------------------------------------------------------------------- usinas


class UsinaOut(BaseModel):
    id: int
    nome: str
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    tem_meuwatt: bool
    tem_meuplano: bool
    #: Monitorada só pelo portal do fabricante (MICRO do meuWatt).
    tem_micro: bool = False
    dono_id: int | None = None
    dono_nome: str | None = None
    #: A empresa de O&M dona da usina — nula é usina de antes do multiempresa, de ninguém.
    empresa_id: int | None = None
    empresa: str | None = None
    #: Ligada no aplicativo (o gerente liga e desliga no oem-gs).
    no_app: bool = True


@router.get("/usinas", response_model=list[UsinaOut])
def listar_usinas(
    db: Session = Depends(get_db), _: User = Depends(EXIGE_USINAS)
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

    nomes = {e.id: e.nome for e in db.scalars(select(Empresa)).all()}
    saida = []
    for link in db.scalars(select(PlantLink).order_by(PlantLink.nome)).all():
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
                tem_micro=link.mw_micro_plant_id is not None,
                dono_id=dono[0] if dono else None,
                dono_nome=dono[1] if dono else None,
                empresa_id=link.empresa_id,
                empresa=nomes.get(link.empresa_id) if link.empresa_id else None,
                no_app=link.ativo,
            )
        )
    return saida
