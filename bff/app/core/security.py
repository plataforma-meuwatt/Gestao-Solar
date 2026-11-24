"""Senha e sessão do Gestão Solar."""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models.empresa import Empresa
from app.models.user import User
from app.services import areas_painel

ALGORITMO = "HS256"
_bearer = HTTPBearer(auto_error=False)

# PBKDF2-SHA256 com 600 mil iterações — a recomendação do OWASP de 2023, e o mesmo
# parâmetro que o meuWatt usa. Sem dependência nova: `hashlib` basta.
_ITERACOES = 600_000


def gerar_hash_senha(senha: str) -> str:
    """Formato autodescritivo: guardar as iterações no próprio hash permite subir o custo
    no futuro sem migrar o que já está gravado."""
    sal = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, _ITERACOES)
    return (
        f"pbkdf2_sha256${_ITERACOES}$"
        f"{base64.b64encode(sal).decode()}${base64.b64encode(digest).decode()}"
    )


def gerar_senha_provisoria() -> str:
    """Senha forte que uma pessoa consegue ditar por telefone.

    O alfabeto exclui os pares que se confundem falados ou escritos à mão — `0/O`, `1/I/L`,
    `5/S`, `2/Z` — e os grupos de quatro com hífen evitam que alguém perca a conta ao
    transcrever. Três grupos do alfabeto de 26 dão ~56 bits: é provisória, será trocada no
    primeiro acesso, e o custo de errar ao ditar é maior que o de encurtar.
    """
    alfabeto = "ABCDEFGHJKMNPQRTUVWXY346789"
    grupos = ["".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3)]
    return "-".join(grupos)


def conferir_senha(senha: str, guardado: str | None) -> bool:
    """Comparação em tempo constante. Hash malformado devolve `False` em silêncio — do
    ponto de vista de quem tenta entrar, é indistinguível de senha errada, que é o que
    queremos."""
    if not guardado:
        return False
    try:
        algoritmo, iteracoes, sal_b64, digest_b64 = guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode(), base64.b64decode(sal_b64), int(iteracoes)
        )
        return hmac.compare_digest(calculado, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def _marcas(com_sid: bool = True) -> dict:
    """O que toda sessão leva para poder ser listada e encerrada (R4): quando nasceu (`iat`, que o "encerrar todas"
    confere) e o número dela (`sid`, a linha em `gs_sessoes`). A de minutos (a foto do mapa do bot) não leva `sid`:
    não é sessão de ninguém, e o "encerrar todas" a derruba pelo `iat`."""
    import uuid
    marcas: dict = {"iat": int(datetime.now(UTC).timestamp())}
    if com_sid:
        marcas["sid"] = uuid.uuid4().hex
    return marcas


def criar_token(user_id: int, *, minutos: int | None = None) -> tuple[str, datetime]:
    """A sessão do app e do portal. `minutos` encurta o prazo (a foto do mapa que o bot tira dura 5 min)."""
    s = get_settings()
    expira = datetime.now(UTC) + (timedelta(minutes=minutos) if minutos is not None else timedelta(hours=s.gs_jwt_expira_horas))
    token = jwt.encode(
        {"sub": str(user_id), "exp": expira, **_marcas(minutos is None)}, s.gs_jwt_secret, algorithm=ALGORITMO
    )
    return token, expira


#: de quanto em quanto o último uso da sessão é gravado (no resto do tempo, a guarda só lê)
_GRAVAR_USO_S = 300
ENCERRADA = "Sessão encerrada: entre de novo."


def _com_fuso(quando: datetime) -> datetime:
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


def _sessao_viva(db: Session, dados: dict, usuario: User, request: Request | None = None) -> None:
    """A sessão ainda vale: não veio de antes de um "encerrar todas" (`sessoes_desde`) nem foi encerrada. Na primeira
    vez que é usada, nasce a linha dela (é quando se sabe de onde ela fala); depois, o último uso de 5 em 5 min."""
    from sqlalchemy.exc import IntegrityError

    from app.models.sessao import SessaoGS
    from app.services import duas_etapas
    if duas_etapas.pendente(usuario):
        # a conta exige o código e não cadastrou o autenticador: a sessão é de antes da exigência (ou do interruptor
        # desligado). Nenhuma vale, nem renovada: a pessoa entra de novo com a senha e cadastra (avaliação de 24/11).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Esta conta agora usa a verificação em duas etapas: entre de novo com a senha para cadastrar "
                            "o autenticador.")
    iat = dados.get("iat")
    if usuario.sessoes_desde is not None and (
            not isinstance(iat, (int, float)) or iat < _com_fuso(usuario.sessoes_desde).timestamp()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ENCERRADA)
    sid = dados.get("sid")
    if not isinstance(sid, str) or not sid:
        return                                             # de antes das sessões (vale até vencer ou "encerrar todas")
    agora = datetime.now(UTC)
    lida = getattr(usuario, "sessao_lida", None)           # já veio na consulta da conta (`_conta_com_empresa`)
    sessao = lida[1] if lida is not None and lida[0] == sid[:32] else db.get(SessaoGS, sid[:32])
    if sessao is not None and sessao.gs_user_id != usuario.id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    if sessao is not None and sessao.encerrada_em is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ENCERRADA)
    if sessao is not None and (agora - _com_fuso(sessao.ultimo_uso_em)).total_seconds() < _GRAVAR_USO_S:
        return
    from app.services.acessos import _ip
    ip = _ip(request)[:64] if request is not None else ""
    aparelho = ((request.headers.get("user-agent") if request is not None else "") or "")[:300]
    if sessao is None:
        # a limpeza é da própria pessoa, ao abrir uma sessão: a encerrada ou vencida há mais de 90 dias sai (o registro
        # de acessos fica; a tabela das sessões não cresce sem fim)
        from sqlalchemy import delete, func
        db.execute(delete(SessaoGS).where(
            SessaoGS.gs_user_id == usuario.id,
            func.coalesce(SessaoGS.encerrada_em, SessaoGS.expira_em) < agora - timedelta(days=90)))
        exp = dados.get("exp")
        db.add(SessaoGS(id=sid[:32], gs_user_id=usuario.id, escopo=str(dados.get("escopo") or "cliente")[:20],
                        criada_em=datetime.fromtimestamp(iat, UTC) if isinstance(iat, (int, float)) else agora,
                        expira_em=datetime.fromtimestamp(exp, UTC) if isinstance(exp, (int, float)) else None,
                        ultimo_uso_em=agora, ip=ip, aparelho=aparelho))
    else:
        sessao.ultimo_uso_em = agora
        if ip:
            sessao.ip = ip
        if aparelho:
            sessao.aparelho = aparelho
    try:
        db.commit()
    except IntegrityError:                                 # dois primeiros usos ao mesmo tempo: o outro já gravou
        db.rollback()


def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Guarda do cliente (app e portal). Só aceita a sessão emitida por `criar_token`.

    A promessa "um token do app não abre o painel, e vice-versa" era cumprida pela metade:
    `gestor_atual` recusava o token do cliente, mas esta função lia só o `sub` e deixava um
    token de painel entrar em `/api/v1/*` em nome do gestor. Passou despercebido enquanto
    o gestor não tinha usina concedida — a lista vinha vazia e ninguém reclamava. Com o
    portal do cliente e o painel em domínios separados (app.gestao.solar × adm.gestao.solar),
    uma sessão não pode valer nos dois: quem cola o token do painel aqui recebe 401, e o
    portal manda a pessoa entrar com a conta de cliente.
    """
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(
            cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]
        )
        user_id = int(dados["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    # Qualquer `escopo` no JWT é sessão de outro portão — hoje só existe `painel`, e o
    # teste é pela PRESENÇA da claim de propósito: um escopo novo no futuro nasce recusado
    # aqui, em vez de entrar por omissão.
    if "escopo" in dados:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Esta sessão é do painel do gestor"
        )

    usuario = _conta_com_empresa(db, user_id, dados.get("sid") if isinstance(dados.get("sid"), str) else None)
    if usuario is None or not usuario.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida")
    _empresa_ativa(db, usuario)
    _sessao_viva(db, dados, usuario, request)
    return usuario


def _conta_com_empresa(db: Session, user_id: int, sid: str | None = None) -> User | None:
    """A conta, a empresa de origem dela e a SESSÃO do token numa ida só ao banco — eram duas, ~200 ms cada (o
    banco está nos EUA), em TODA requisição autenticada. A empresa fica presa à conta, e o
    `db.get` de `_empresa_ativa` a acha no mapa de identidade em vez de voltar ao banco; a sessão (R4) vai em
    `sessao_lida`, para `_sessao_viva` não voltar ao banco."""
    from app.models.sessao import SessaoGS
    colunas = [User, Empresa] + ([SessaoGS] if sid else [])
    consulta = select(*colunas).outerjoin(Empresa, Empresa.id == User.empresa_id)
    if sid:
        consulta = consulta.outerjoin(SessaoGS, SessaoGS.id == sid[:32])   # de quem é a sessão, `_sessao_viva` confere
    linha = db.execute(consulta.where(User.id == user_id)).first()
    if linha is None:
        return None
    usuario = linha[0]
    usuario.empresa_lida = linha[1]
    if sid:
        usuario.sessao_lida = (sid[:32], linha[2])
    return usuario


def _empresa_ativa(db: Session, usuario: User, empresa_id: int | None = None) -> None:
    """Desativar a empresa tem de parar a leitura dela — em todos os portões.

    `painel.entrar` já recusava o gerente de empresa desativada, e só ele: `auth.login`
    emitia token de aplicativo para a mesma conta, com 30 dias de validade e renovação
    sem fim, e a carteira inteira continuava respondendo. Desativar a empresa não parava
    nada — só escondia o botão.

    A conferência mora aqui porque aqui passam **todas** as requisições autenticadas,
    inclusive as de um token emitido antes da desativação. Conta da plataforma tem
    `empresa_id` nulo e não é tocada.
    """
    empresa_id = empresa_id or usuario.empresa_id
    if empresa_id is None:
        return
    empresa = db.get(Empresa, empresa_id)
    if empresa is None or not empresa.ativa:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "A empresa desta conta está desativada. Fale com quem administra a plataforma.",
        )


def criar_token_painel(user_id: int) -> tuple[str, datetime]:
    """Sessão do painel: curta, e marcada com `escopo=painel` para não ser confundida com
    a sessão do app. Um token do app não abre o painel, e vice-versa."""
    s = get_settings()
    expira = datetime.now(UTC) + timedelta(hours=s.gs_painel_sessao_horas)
    token = jwt.encode(
        {"sub": str(user_id), "escopo": "painel", "exp": expira, **_marcas()},
        s.gs_jwt_secret,
        algorithm=ALGORITMO,
    )
    return token, expira


def _token_de_escopo(user_id: int, escopo: str, empresa_id: int | None = None, *,
                     minutos: int | None = None) -> tuple[str, datetime]:
    """`minutos`: o token de servidor a servidor (o bot falando com o meuGuarda pela pessoa), curto e sem `sid`: não é
    uma sessão aberta da pessoa e não entra na lista dela (o "encerrar todas" o derruba pelo `iat`)."""
    s = get_settings()
    expira = datetime.now(UTC) + (timedelta(minutes=minutos) if minutos is not None
                                  else timedelta(hours=s.gs_painel_sessao_horas))
    dados = {"sub": str(user_id), "escopo": escopo, "exp": expira, **_marcas(minutos is None)}
    if empresa_id is not None:
        # A conta é de mais de uma empresa e está operando OUTRA que não a de origem. A
        # guarda confere a cada requisição que ela ainda é de lá.
        dados["empresa"] = empresa_id
    return jwt.encode(dados, s.gs_jwt_secret, algorithm=ALGORITMO), expira


def criar_token_empresa(user_id: int, empresa_id: int | None = None, *, minutos: int | None = None
                        ) -> tuple[str, datetime]:
    """Sessão do gerente da empresa de O&M, marcada com `escopo=empresa`.

    Um portão novo, e não um perfil a mais dentro do painel: o prefixo da rota passa a
    dizer de quem ela é, e o token de um portão é recusado nos outros — `usuario_atual`
    já recusa qualquer claim `escopo`, e `gestor_atual` exige o valor `painel`.
    """
    return _token_de_escopo(user_id, "empresa", empresa_id, minutos=minutos)


#: A sessão de ENTRADA dos produtos (meuGuarda, TermoVision): o GS como autenticador ("não quero fazer login, já estou
#: autenticado no sistema via Gestão", o dono, 12/11/2026). Só serve para `/api/sessao/{produto}` (gerar a asserção):
#: nenhuma guarda de portão a aceita (o escopo `entrada` é recusado por todas), por isso pode durar 30 dias e se
#: renovar a cada uso, guardada no navegador em gestao.solar.
DIAS_DA_ENTRADA = 30


def criar_token_entrada(user_id: int, *, sid: str | None = None) -> tuple[str, datetime]:
    """Com `sid`, a renovação a cada uso: a MESMA sessão (uma linha na lista da pessoa, não uma por uso)."""
    s = get_settings()
    expira = datetime.now(UTC) + timedelta(days=DIAS_DA_ENTRADA)
    marcas = _marcas()
    if sid:
        marcas["sid"] = sid
    return jwt.encode({"sub": str(user_id), "escopo": "entrada", "exp": expira, **marcas}, s.gs_jwt_secret,
                      algorithm=ALGORITMO), expira


#: A sessão de uma pessoa NUM SISTEMA da família (a porta dos sistemas, `interno_sistemas.py`): vai no passe
#: (`sessao_gs`) e o sistema a devolve em `X-Sessao-GS` quando fala pela pessoa. Assim a chave do sistema sozinha não
#: fala por ninguém: só por quem entrou nele pelo GS. Escopo `sistema:<nome>`, que nenhuma guarda de portão aceita;
#: lista-se e encerra-se como as outras (`_sessao_viva`, a linha nasce no primeiro uso).
DIAS_DA_SESSAO_DE_SISTEMA = 60


def criar_token_sistema(user_id: int, sistema: str, *, sid: str | None = None) -> str:
    """A sessão da pessoa NAQUELE sistema (o `sessao_gs` do passe). Com `sid`, a renovação: a MESMA sessão (encerrá-la
    no GS continua derrubando-a), com 60 dias a contar de agora."""
    s = get_settings()
    expira = datetime.now(UTC) + timedelta(days=DIAS_DA_SESSAO_DE_SISTEMA)
    marcas = _marcas()
    if sid:
        marcas["sid"] = sid
    return jwt.encode({"sub": str(user_id), "escopo": f"sistema:{sistema}", "exp": expira, **marcas},
                      s.gs_jwt_secret, algorithm=ALGORITMO)


def conferir_token_sistema(db: Session, token: str, usuario: User, sistema: str, request: Request | None = None
                           ) -> bool:
    """O `X-Sessao-GS` é desta pessoa, deste sistema, e ainda vale (não encerrado, não de antes de um "encerrar
    todas")."""
    try:
        dados = jwt.decode(token, get_settings().gs_jwt_secret, algorithms=[ALGORITMO])
    except JWTError:
        return False
    if dados.get("escopo") != f"sistema:{sistema}" or str(dados.get("sub")) != str(usuario.id):
        return False
    try:
        _sessao_viva(db, dados, usuario, request)
    except HTTPException:
        return False
    return True


def criar_token_tecnico(user_id: int, empresa_id: int | None = None, *, minutos: int | None = None
                        ) -> tuple[str, datetime]:
    """Sessão do técnico, marcada com `escopo=tecnico`.

    Portão próprio, e não a sessão de empresa com menos menu: com `escopo=empresa`, a única
    coisa entre o técnico e as rotas do gerente seria a conferência de perfil dentro de
    `gestor_empresa_atual` — um `abre_empresa` afrouxado um dia e o técnico cadastraria
    cliente. Com escopo próprio, os três portões existentes o recusam pela claim, antes
    de olhar perfil nenhum.
    """
    return _token_de_escopo(user_id, "tecnico", empresa_id, minutos=minutos)


def gestor_empresa_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Guarda de `/api/empresa/*`.

    Exige quatro coisas, e a última é a que importa no multiempresa: token válido, escopo
    de empresa, conta que ainda é gerente — e **empresa vinculada**. Uma conta de inquilino
    sem `empresa_id` não entra: se entrasse, todo filtro montado a partir dela viraria
    "sem filtro", que é o vazamento silencioso que este desenho existe para não ter.
    """
    usuario = _conta_do_escopo(cred, db, "empresa", "Esta sessão não abre a área da empresa", request)
    if not usuario.abre_empresa:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à empresa")
    _da_empresa(db, usuario)
    return usuario


def tecnico_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Guarda de `/api/tecnico/*`. As mesmas quatro exigências do gerente, com o escopo e
    o perfil do técnico — inclusive a empresa vinculada e ativa: o número dele é da
    operação de UMA empresa, e técnico sem empresa não tem de quem ser a conversa."""
    usuario = _conta_do_escopo(cred, db, "tecnico", "Esta sessão não abre a área do técnico", request)
    if not usuario.abre_tecnico:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito ao técnico")
    _da_empresa(db, usuario)
    return usuario


def _conta_do_escopo(
    cred: HTTPAuthorizationCredentials | None, db: Session, escopo: str, recusa: str, request: Request | None = None
) -> User:
    """Token válido, do escopo pedido, de conta que existe e está ativa."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(
            cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]
        )
        if dados.get("escopo") != escopo:
            raise HTTPException(status.HTTP_403_FORBIDDEN, recusa)
        user_id = int(dados["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    usuario = _conta_com_empresa(db, user_id, dados.get("sid") if isinstance(dados.get("sid"), str) else None)
    if usuario is None or not usuario.ativo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à empresa")
    if dados.get("empresa") is not None:
        # Sessão de OUTRA empresa da conta (troca de empresa no oem-gs). Confere a cada
        # requisição: tirada da empresa, a sessão para na seguinte, sem esperar expirar.
        from app.services.empresas import empresas_da_conta

        empresa = int(dados["empresa"])
        if empresa not in empresas_da_conta(db, usuario):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta conta não é mais desta empresa.")
        usuario.empresa_da_sessao = empresa
    _sessao_viva(db, dados, usuario, request)
    return usuario


def _da_empresa(db: Session, usuario: User) -> None:
    """Conta de inquilino tem de ter empresa — e ela, ativa. Sem `empresa_id`, todo filtro
    montado a partir da conta viraria "sem filtro", que é o vazamento silencioso que o
    multiempresa existe para não ter. A empresa conferida é a que a sessão OPERA."""
    empresa_id = getattr(usuario, "empresa_da_sessao", None) or usuario.empresa_id
    if empresa_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta conta não está ligada a nenhuma empresa. Peça a quem administra a "
            "plataforma para vinculá-la.",
        )
    _empresa_ativa(db, usuario, empresa_id)


def gestor_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Guarda do painel. Exige as três coisas: token válido, escopo de painel, e a conta
    ainda abrir o painel — quem perdeu o cargo perde o acesso na requisição seguinte, sem
    depender do token expirar."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        dados = jwt.decode(
            cred.credentials, get_settings().gs_jwt_secret, algorithms=[ALGORITMO]
        )
        if dados.get("escopo") != "painel":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta sessão não abre o painel")
        user_id = int(dados["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida") from exc

    usuario = db.get(User, user_id)
    if usuario is None or not usuario.ativo or not usuario.abre_painel:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à administração")
    _sessao_viva(db, dados, usuario, request)
    return usuario


def administrador_atual(gestor: User = Depends(gestor_atual)) -> User:
    """Guarda das telas que mexem no que quebra tudo: as pontes com os produtos (que
    guardam credencial de serviço) e a própria equipe. Atendimento cuida de cliente e
    diagnóstico, e não passa daqui."""
    if not gestor.e_administrador:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta área é restrita a administradores.",
        )
    return gestor


def exige_area(chave: str):
    """Guarda de uma área do painel — o que substituiu "administrador vê tudo o que é
    sensível, atendimento vê o resto".

    O administrador passa sempre, por perfil e sem linha no banco (ver
    `services/areas_painel`). Quem é atendimento passa se o acesso estiver concedido na
    tela de Usuários do sistema.

    **403 e não 404**: aqui a existência da tela não é segredo — ela está no menu de
    quem tem acesso e no manual. O que se protege é o conteúdo, e dizer "você não tem
    esta área" é o que faz a pessoa pedir o acesso a quem administra em vez de abrir
    chamado achando que o painel quebrou.
    """
    if chave not in areas_painel.CHAVES:
        # Erra na importação do módulo, não na requisição: uma área digitada errado numa
        # rota seria uma porta que ninguém abre — nem o administrador —, e o sintoma
        # chegaria como "a tela sumiu para todo mundo".
        raise ValueError(f"Área desconhecida no catálogo do painel: {chave!r}")

    def guarda(
        gestor: User = Depends(gestor_atual), db: Session = Depends(get_db)
    ) -> User:
        if not areas_painel.pode(db, gestor, chave):
            rotulo = areas_painel.area(chave).rotulo
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Seu acesso não inclui “{rotulo}”. Peça a quem administra o painel.",
            )
        return gestor

    return guarda
