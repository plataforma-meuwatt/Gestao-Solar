"""O "esqueci a senha" do GS (Plano Casa GS, R12: "Esqueci a senha pelo e-mail e pelo WhatsApp do bot").

- Pelo WhatsApp: a pessoa manda "esqueci a senha" ao número do GS pelo celular CADASTRADO na conta (o número prova
  quem é, como no bot). Chega um link de 30 minutos, uma vez só, para criar a senha nova. O link não fica no Log do bot
  nem na cópia do gateway (`assistente`).
- Pelo e-mail: o mesmo link, para o e-mail da conta. Só quando houver remetente (`GS_SMTP_*`); sem ele, a página diz
  que o caminho é o WhatsApp. A resposta é a mesma exista o e-mail ou não (não confirma conta a quem tenta).
- Trocar: a senha nova (8 caracteres ou mais) entra, o link morre e as sessões abertas da pessoa acabam (inclusive as
  dos sistemas). A verificação em duas etapas continua: o link troca a senha, não o código.
"""
import hashlib
import re
import secrets
import time
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.sessao import RedefinicaoDeSenha
from app.models.user import User

VALIDADE = timedelta(minutes=30)
MINIMO = 8

#: o pedido do WhatsApp, exato (sem acento e pontuação, e com "do gs" no fim opcional): "esqueci a senha do inversor"
#: é outra conversa e vai à IA
_PEDIDOS = {"esqueci a senha", "esqueci minha senha", "esqueci a minha senha", "esqueci senha",
            "recuperar senha", "recuperar a senha", "recuperar minha senha", "redefinir senha", "redefinir a senha",
            "redefinir minha senha", "nova senha", "senha nova", "quero uma senha nova", "quero uma nova senha",
            "perdi a senha", "perdi minha senha", "esqueci a senha de entrar", "trocar a senha de entrar"}


def _limpo(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+(do|no) (gs|gestao solar|gestao)$", "", t)


def pediu(texto: str | None) -> bool:
    """A mensagem é o pedido do link (e só ele)."""
    return _limpo(texto or "") in _PEDIDOS


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def emitir(db: Session, u: User, canal: str) -> str:
    """Um link novo (os de antes, ainda não usados, morrem). Devolve o TOKEN; só o hash fica. Não confirma."""
    db.flush()                                             # o de antes, ainda não gravado nesta transação, morre junto
    db.execute(update(RedefinicaoDeSenha).where(RedefinicaoDeSenha.gs_user_id == u.id,
                                                RedefinicaoDeSenha.usada_em.is_(None))
               .values(usada_em=datetime.now(UTC)))
    token = secrets.token_urlsafe(32)
    db.add(RedefinicaoDeSenha(gs_user_id=u.id, token_hash=_hash(token), canal=canal,
                              expira_em=datetime.now(UTC) + VALIDADE))
    return token


def link(token: str) -> str:
    return f"{get_settings().portal_web_url.rstrip('/')}/nova-senha#t={token}"


class LinkInvalido(ValueError):
    """O link venceu, já foi usado ou não existe."""


def _com_fuso(q: datetime) -> datetime:
    return q if q.tzinfo else q.replace(tzinfo=UTC)


def conta_do_link(db: Session, token: str) -> tuple[RedefinicaoDeSenha, User]:
    r = db.scalar(select(RedefinicaoDeSenha).where(RedefinicaoDeSenha.token_hash == _hash(token or "")))
    u = db.get(User, r.gs_user_id) if r is not None else None
    if r is None or r.usada_em is not None or _com_fuso(r.expira_em) < datetime.now(UTC) or u is None or not u.ativo:
        raise LinkInvalido("Este link venceu ou já foi usado: peça outro (mande \"esqueci a senha\" ao WhatsApp do GS).")
    return r, u


def trocar(db: Session, token: str, senha: str) -> User:
    """A senha nova pelo link. Não confirma (quem chama encerra as sessões e confirma)."""
    from app.core.security import gerar_hash_senha
    if len(senha or "") < MINIMO:
        raise ValueError(f"A senha nova tem de ter {MINIMO} caracteres ou mais.")
    r, u = conta_do_link(db, token)
    gravou = db.execute(update(RedefinicaoDeSenha).where(RedefinicaoDeSenha.id == r.id,
                                                         RedefinicaoDeSenha.usada_em.is_(None))
                        .values(usada_em=datetime.now(UTC))).rowcount
    if gravou != 1:                                        # dois cliques: um troca, o outro recebe "já usado"
        raise LinkInvalido("Este link já foi usado: se não foi você, peça outro e troque a senha.")
    u.senha_hash = gerar_hash_senha(senha)
    u.trocar_senha = False
    return u


# ---------------------------------------------------------------- o número do bot e o e-mail

_numero: dict = {"valor": None, "em": 0.0}


async def numero_do_bot() -> str | None:
    """O número do WhatsApp do GS (o ligado ao `phone_number_id` do gateway), para a página dizer para onde mandar.
    Uma hora em memória; sem o gateway, None (a página diz que o número não pôde ser lido)."""
    if _numero["valor"] and time.time() - _numero["em"] < 3600:
        return _numero["valor"]
    from app.clients import whatsapp
    try:
        estado = await whatsapp.estado()
        numeros = await whatsapp.numeros()
    except Exception:                                      # noqa: BLE001 — o gateway fora: sem o número, dito
        return _numero["valor"]
    pid = (estado or {}).get("phone_number_id")
    achado = next((n.get("display_phone_number") for n in numeros or [] if n.get("id") == pid), None)
    if achado:
        _numero.update(valor=achado, em=time.time())
    return achado or _numero["valor"]


def email_disponivel() -> bool:
    s = get_settings()
    return bool(s.gs_smtp_host and s.gs_smtp_remetente)


def mandar_email(destino: str, endereco: str) -> None:
    """O link por e-mail, pelo remetente do GS (`GS_SMTP_*`; SSL na 465, STARTTLS nas outras)."""
    import smtplib
    from email.message import EmailMessage
    s = get_settings()
    m = EmailMessage()
    m["From"] = s.gs_smtp_remetente
    m["To"] = destino
    m["Subject"] = "Gestão Solar: crie a sua senha nova"
    m.set_content(f"Olá,\n\nPara criar a senha nova do Gestão Solar, abra este link (vale 30 minutos, uma vez só):\n\n"
                  f"{endereco}\n\nSe não foi você que pediu, ignore este e-mail: a senha de agora continua valendo.\n\n"
                  "Gestão Solar")
    if s.gs_smtp_porta == 465:
        with smtplib.SMTP_SSL(s.gs_smtp_host, s.gs_smtp_porta, timeout=20) as c:
            if s.gs_smtp_usuario:
                c.login(s.gs_smtp_usuario, s.gs_smtp_senha)
            c.send_message(m)
    else:
        with smtplib.SMTP(s.gs_smtp_host, s.gs_smtp_porta, timeout=20) as c:
            c.starttls()
            if s.gs_smtp_usuario:
                c.login(s.gs_smtp_usuario, s.gs_smtp_senha)
            c.send_message(m)


def contas_do_email(db: Session, email: str) -> list[User]:
    return list(db.scalars(select(User).where(func.lower(User.email) == (email or "").strip().lower(), User.ativo)))


if __name__ == "__main__":
    assert pediu("Esqueci a senha!") and pediu("esqueci minha senha do GS") and pediu("Nova senha.")
    assert not pediu("esqueci a senha do inversor") and not pediu("qual a senha do wifi")
    print("ok")
