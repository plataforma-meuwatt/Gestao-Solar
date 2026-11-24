"""Autenticar e registrar: o GS é o único que confere senha, e guarda cada acesso (o dono, 24/11/2026: "GS é o pai,
é o autenticador" e "o GS é o detentor dos acessos, quero que ele tenha a auditoria completa dos logs de acessos de
cada pessoa").

- `autenticar`: o login OU o e-mail, e a senha. O e-mail vale quando a senha certa casa com UMA conta dele: a mesma
  pessoa pode ter duas contas com o mesmo e-mail (gestora e dona de usina), e a senha diz qual é. As duas com a mesma
  senha: a pessoa provou a senha, então a tela diz para entrar pelo login (`frase`). O tempo da resposta não conta se a
  conta existe: sem conta, confere contra uma senha falsa.
- `barrado`: 10 senhas erradas em 15 min no mesmo login VINDO do mesmo IP param esse par por 15 min. Por par, e não
  só por login: errar de longe não tranca a pessoa onde ela está. Limite: quem entra pela tela de outro sistema que
  chama o GS pelo servidor (o IP é o do servidor de lá) divide o par com quem tentar por lá — a janelinha, que vem do
  navegador da pessoa, substitui essas telas.
- 30 senhas erradas no mesmo IP em 15 min barram esse IP em todas as portas: quem tenta uma senha em cada conta para
  ali. O meuGuarda e o TermoVision repassam pelo servidor o login das pessoas de lá: com a chave do sistema
  (`X-Sistema` + `X-Chave-Interna`) eles informam o IP da pessoa (`X-Usuario-IP`) e os dois limites e o registro valem
  para ela, e o total por login vindo daquele sistema tem teto (30), para um IP inventado não furar o limite. Com a chave
  e sem o IP da pessoa, o repasse é recusado. Sem a chave, o endereço da KingHost (que roda outros projetos também: não
  é confiança) fica, na TRANSIÇÃO, só com o limite por login e lugar (`teto_ip_casa_sem_chave` = 0), que é o que havia
  antes; com teto, estranhos pela tela do meuGuarda trancariam todo mundo de lá. Adotada a chave nos dois, vira 30.
- O registro: a recusa numa conta que existe SEMPRE entra (o limite por par a segura em 10 por lugar); a de login que
  não é conta entra até 30 por IP e janela, e depois UMA linha diz que houve inundação.
- `registrar`: uma linha em `gs_acessos` por entrada, passe, troca de senha ou recusa, com IP e aparelho. Nunca a senha:
  o que foi digitado só fica quando é de uma conta (senão, um resumo que não volta ao texto).

Toda porta que confere senha passa por aqui (portal e app, painel, conector do Claude, entrada dos outros sistemas),
para a régua e o registro serem um só.
"""
import hashlib
import hmac
import ipaddress
import logging
import random
import time
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.security import conferir_senha, gerar_hash_senha
from app.models.acesso import AcessoGS
from app.models.user import User

log = logging.getLogger(__name__)

#: a frase única da recusa: quem tenta adivinhar não aprende se o login existe, se a senha errou ou se a conta está
#: desligada
RECUSA = "Login ou senha inválidos"
AMBIGUO = "e-mail de mais de uma conta com a mesma senha"
FRASE_AMBIGUO = "Este e-mail é de mais de uma conta com esta senha: entre pelo login da conta."
BARRADO = "Muitas tentativas erradas. Espere 15 minutos e tente de novo."
BARRADO_REPASSE = ("Muitas tentativas erradas por aqui. Espere 15 minutos, ou entre com o botão \"Entrar com o Gestão "
                   "Solar\" ou por gestao.solar.")
RETENCAO = timedelta(days=400)

_JANELA_S, _POR_PAR, _POR_IP, _TETO_CHAVES = 900, 10, 30, 20000
# ponytail: memória do processo (a API roda em 1 worker); com réplicas, vira tabela
_erros: dict[str, list[float]] = {}        # "login|ip" → as senhas erradas recentes
_por_ip: dict[str, list[float]] = {}       # ip → as recusas recentes (só para parar de gravar linha a linha)
_avisados: dict[str, float] = {}           # "login|ip" barrado → quando gravou a linha do bloqueio
_falso: list[str] = []


def _hash_falso() -> str:
    if not _falso:
        _falso.append(gerar_hash_senha("senha-que-nao-e-de-ninguem"))
    return _falso[0]


def autenticar(db: Session, login: str | None, senha: str | None) -> tuple[User | None, str]:
    """(a conta, ou None) e o motivo da recusa para o registro; a tela usa `frase(motivo)`."""
    texto = (login or "").strip().lower()
    if not texto or not senha:
        return None, "login ou senha em branco"
    if "@" not in texto:
        u = db.scalar(select(User).where(User.apelido == texto))
        certa = conferir_senha(senha, u.senha_hash if u is not None and u.senha_hash else _hash_falso())
        if u is None:
            return None, "login de conta nenhuma"
        if not u.ativo:
            return None, "conta desligada"
        return (u, "") if certa else (None, "senha errada")
    contas = list(db.scalars(select(User).where(func.lower(User.email) == texto).order_by(User.id)))
    certas = [u for u in contas if conferir_senha(senha, u.senha_hash or _hash_falso()) and u.ativo]
    for _ in range(max(0, 2 - len(contas))):              # sempre duas conferências: o tempo não conta quantas há
        conferir_senha(senha, _hash_falso())
    if len(certas) == 1:
        return certas[0], ""
    if len(certas) > 1:
        return None, AMBIGUO
    if not contas:
        return None, "e-mail de conta nenhuma"
    return None, "conta desligada" if not any(u.ativo for u in contas) else "senha errada"


def frase(motivo: str) -> str:
    """O que a tela diz. Só o e-mail de duas contas com a mesma senha tem frase própria: a senha já foi provada."""
    return FRASE_AMBIGUO if motivo == AMBIGUO else RECUSA


_REDES_DA_CASA = [ipaddress.ip_network(n) for n in
                  ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")]


def _da_casa(ip: str) -> bool:
    """O endereço da KingHost ou da rede interna. NÃO é confiança (outros projetos rodam lá): só o teto mais alto."""
    from app.core.config import get_settings
    if ip in {x.strip() for x in get_settings().ips_da_casa.split(",") if x.strip()}:
        return True
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(endereco in rede for rede in _REDES_DA_CASA)


def repasse(request: Request | None) -> str | None:
    """O sistema da família que repassa o login pelo servidor, provado pela chave dele, ou None."""
    from app.core.config import get_settings
    if request is None:
        return None
    s = get_settings()
    sistema = (request.headers.get("x-sistema") or "").strip().lower()
    esperada = {"meuguarda": s.meuguarda_chave_interna, "termovision": s.termovision_chave_interna}.get(sistema)
    dada = (request.headers.get("x-chave-interna") or "").encode()      # bytes: acento na chave não derruba nada
    return sistema if esperada and hmac.compare_digest(dada, esperada.encode()) else None


def _ip_dito(request: Request | None) -> str | None:
    """O IP da pessoa que o sistema da família informou (`X-Usuario-IP`), se for um IP."""
    try:
        return str(ipaddress.ip_address((request.headers.get("x-usuario-ip") or "").strip()))[:64]
    except (ValueError, AttributeError):
        return None


def _origem(request: Request | None) -> str:
    """O IP de quem abriu a conexão, como o proxy da casa o escreveu: o ÚLTIMO do `X-Forwarded-For` (o que o proxy
    acrescenta; o primeiro pode vir inventado de fora)."""
    if request is None:
        return ""
    xff = [x.strip() for x in (request.headers.get("x-forwarded-for") or "").split(",") if x.strip()]
    return (xff[-1] if xff else (request.client.host if request.client else ""))[:64]


def _ip(request: Request | None) -> str:
    """O IP que vale para os limites e o registro: o da pessoa. Só o sistema provado pela chave pode informá-lo."""
    origem = _origem(request)
    if repasse(request):
        return _ip_dito(request) or origem
    return origem


def _teto_ip(request: Request | None, ip: str) -> int | None:
    """Quantas senhas erradas este IP aguenta em 15 min (None = sem teto por IP)."""
    from app.core.config import get_settings
    if repasse(request) is None and _da_casa(ip):
        return get_settings().teto_ip_casa_sem_chave or None
    return _POR_IP


def _recentes(tabela: dict[str, list[float]], chave: str) -> list[float]:
    agora = time.time()
    v = [t for t in tabela.get(chave, []) if t > agora - _JANELA_S]
    if v:
        tabela[chave] = v
    else:
        tabela.pop(chave, None)                            # sem lista vazia guardada: a memória não cresce à toa
    return v


def _somar(tabela: dict[str, list[float]], chave: str) -> int:
    v = [*_recentes(tabela, chave), time.time()]
    tabela[chave] = v
    if len(_erros) + len(_por_ip) + len(_avisados) > _TETO_CHAVES:
        _podar()
    return len(v)


def _podar() -> None:
    """Acima do teto: tira o que venceu e, se ainda passar, os mais antigos (a ordem de entrada), até a metade do teto.
    Assim não roda a cada chamada, e a memória fica limitada mesmo sob ataque."""
    for tabela in (_erros, _por_ip):
        for k in list(tabela):
            _recentes(tabela, k)
    corte = time.time() - _JANELA_S
    for k in [k for k, t in _avisados.items() if t < corte]:
        _avisados.pop(k, None)
    for tabela in (_erros, _por_ip, _avisados):
        sobra = len(tabela) - _TETO_CHAVES // 6
        for k in list(tabela)[:max(0, sobra)]:
            tabela.pop(k, None)


def _par(request: Request | None, login: str | None) -> str:
    return f"{(login or '').strip().lower()}|{_ip(request)}"


def _par_do_sistema(request: Request | None, login: str | None) -> str:
    return f"{(login or '').strip().lower()}|sistema:{repasse(request)}"


def _ja_entrou_daqui(db: Session | None, login: str | None, ip: str) -> bool:
    """A conta deste login já entrou com sucesso deste IP nos últimos 30 dias (o lugar de sempre da pessoa)."""
    if db is None or not ip:
        return False
    contas = [u.id for u in _contas_do_login(db, (login or "").strip().lower())]
    if not contas:
        return False
    return db.scalar(select(AcessoGS.id).where(
        AcessoGS.gs_user_id.in_(contas), AcessoGS.ip == ip, AcessoGS.ok.is_(True),
        AcessoGS.acao.in_(("entrou", "passe")), AcessoGS.em > datetime.now(UTC) - timedelta(days=30)).limit(1)) is not None


def barrado(request: Request | None, login: str | None, por_ip: bool = True, db: Session | None = None) -> str | None:
    """Por que não tentar agora (`par`: este login, deste IP, errou 10 vezes; `ip`: este IP passou do teto dele), ou
    None. `por_ip=False` só onde a chave já é por conta (a troca de papel). O teto do login por sistema (IPs inventados)
    não barra o lugar de onde a pessoa já entrou nos últimos 30 dias: estranhos não a trancam de casa."""
    if len(_recentes(_erros, _par(request, login))) >= _POR_PAR:
        return "par"
    if (repasse(request) and len(_recentes(_erros, _par_do_sistema(request, login))) >= _POR_IP
            and not _ja_entrou_daqui(db, login, _ip(request))):
        return "par"                                       # o total do login vindo daquele sistema (IPs inventados)
    ip = _ip(request)
    teto = _teto_ip(request, ip) if por_ip and ip else None
    if teto is not None and len(_recentes(_por_ip, ip)) >= teto:
        return "ip"
    return None


def _uma_vez(chave: str) -> bool:
    """Verdadeiro na primeira vez da janela: as linhas de bloqueio e de inundação entram uma vez só."""
    if time.time() - _avisados.get(chave, 0) < _JANELA_S:
        return False
    _avisados[chave] = time.time()
    return True


def contar_erro(request: Request | None, login: str | None) -> None:
    """Uma senha errada que não passa por `recusar` (a troca de papel, que registra do jeito dela)."""
    _somar(_erros, _par(request, login))


def _resumo(texto: str) -> str:
    """O que foi digitado e não é conta nenhuma (pode ser a senha no campo errado): uma assinatura com uma chave do
    servidor (derivada da do GS, só para isto), que compara tentativas iguais sem voltar ao texto."""
    from app.core.config import get_settings
    chave = hmac.new((get_settings().gs_jwt_secret or "").encode(), b"gs_acessos:resumo", hashlib.sha256).digest()
    return "? " + hmac.new(chave, texto.encode(), hashlib.sha256).hexdigest()[:12]


def _contas_do_login(db: Session, texto: str) -> list[User]:
    if not texto:
        return []
    if "@" not in texto:
        u = db.scalar(select(User).where(User.apelido == texto))
        return [u] if u is not None else []
    return list(db.scalars(select(User).where(func.lower(User.email) == texto)))


_ultimos: dict[tuple, float] = {}


def registrar(db: Session, request: Request | None, *, acao: str, sistema: str = "gs", user: User | None = None,
              login: str | None = None, ok: bool = True, motivo: str = "", agrupar_s: int | None = None) -> None:
    """Grava UMA linha e confirma na hora (a recusa levanta logo depois e não pode levar o registro junto). Falhar ao
    gravar não derruba a entrada: vai ao log do servidor. De vez em quando apaga o que passou da retenção.
    `agrupar_s`: o passe que o BOT e o conector emitem a cada consulta entra uma vez por janela (pessoa, sistema)."""
    if agrupar_s:
        chave = (user.id if user is not None else None, acao, sistema, motivo, ok)
        if time.time() - _ultimos.get(chave, 0) < agrupar_s:
            return
        _ultimos[chave] = time.time()
    ip = _ip(request)                                      # fora do try: um defeito aqui não some calado
    aparelho = ((request.headers.get("user-agent") if request is not None else "") or "")[:300]
    try:
        db.add(AcessoGS(
            gs_user_id=user.id if user is not None else None,
            login=((login if login is not None else (user.apelido if user is not None else "")) or "")[:160],
            acao=acao, sistema=sistema, ok=ok, motivo=(motivo or "")[:200], ip=ip, aparelho=aparelho))
        db.commit()
        if random.random() < 0.005:                      # noqa: S311 — limpeza, não segurança
            db.execute(delete(AcessoGS).where(AcessoGS.em < datetime.now(UTC) - RETENCAO))
            db.commit()
    except Exception:                                      # noqa: BLE001
        db.rollback()
        log.warning("acessos: não gravou %s/%s", acao, sistema, exc_info=True)


def recusar(db: Session, request: Request | None, login: str | None, motivo: str, sistema: str = "gs") -> None:
    """A recusa de senha: conta nos limites e registra. Numa conta que existe, sempre; num login que não é conta, até 30
    por IP e janela, e depois uma linha de inundação. O que foi digitado só fica quando é de uma conta (uma senha
    digitada no campo do login não pode parar no registro); a conta fica ligada quando é uma só."""
    texto, ip = (login or "").strip().lower(), _ip(request)
    _somar(_erros, _par(request, texto))
    if repasse(request):
        _somar(_erros, _par_do_sistema(request, texto))
    n_ip = _somar(_por_ip, ip) if ip else 0
    contas = _contas_do_login(db, texto)
    teto = _teto_ip(request, ip) if ip else None
    if not contas and n_ip > (teto if teto is not None else _POR_IP):
        if _uma_vez(f"inundacao|{ip}"):
            registrar(db, request, acao="recusado", sistema=sistema, ok=False, login="",
                      motivo=f"inundação: mais de {_POR_IP} senhas erradas deste IP em 15 min; as de login que não é "
                             "conta param de entrar uma a uma")
        return
    registrar(db, request, acao="recusado", sistema=sistema, user=contas[0] if len(contas) == 1 else None,
              login=texto if contas else (_resumo(texto) if texto else ""), ok=False, motivo=motivo)


def recusar_barrado(db: Session, request: Request | None, login: str | None, sistema: str = "gs",
                    porque: str = "par") -> None:
    """Quem passou do limite: UMA linha por par (ou por IP) e janela."""
    texto = (login or "").strip().lower()
    if not _uma_vez(_par(request, texto) if porque == "par" else f"ip|{_ip(request)}"):
        return
    contas = _contas_do_login(db, texto) if porque == "par" else []
    registrar(db, request, acao="recusado", sistema=sistema, user=contas[0] if len(contas) == 1 else None,
              login=texto if contas else "", ok=False,
              motivo=("bloqueado: 10 senhas erradas deste login, deste lugar, em 15 min" if porque == "par" else
                      f"bloqueado: {_POR_IP} senhas erradas deste IP em 15 min"))


def entrar_ou_recusar(db: Session, request: Request | None, login: str | None, senha: str | None,
                      sistema: str = "gs", por_ip: bool = True) -> User:
    """A porta das rotas: o limite, a senha, a frase e o registro da recusa, iguais em todas. `por_ip=False` só onde o
    limite já é por conta (hoje, nenhuma porta de senha)."""
    from fastapi import HTTPException, status

    if repasse(request) and _ip_dito(request) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "O repasse com a chave do sistema precisa do IP da pessoa em X-Usuario-IP.")
    porque = barrado(request, login, por_ip, db)
    if porque:
        recusar_barrado(db, request, login, sistema, porque)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            BARRADO_REPASSE if repasse(request) else BARRADO)
    usuario, motivo = autenticar(db, login, senha)
    if usuario is None:
        recusar(db, request, login, motivo, sistema)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, frase(motivo))
    return usuario


def senha_redefinida(db: Session, alvo: User, por: User | None, como: str) -> None:
    """A senha de entrar trocada por OUTRA pessoa (plataforma, gerente, bot): fica no registro de quem teve a senha
    trocada, com quem trocou. Chamar depois do commit da troca."""
    quem = f"{por.apelido}" if por is not None else "o sistema"
    registrar(db, None, acao="senha", user=alvo, motivo=f"redefinida por {quem} ({como})")
