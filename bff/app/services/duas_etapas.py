"""A verificação em duas etapas do GS (Plano Casa GS, R12: "Verificação em duas etapas no GS, obrigatória para gerente e
plataforma: depois do GS, uma senha vazada abre todos os sistemas").

- O código é o TOTP (RFC 6238: 6 números, de 30 em 30 s, HMAC-SHA1), o que os aplicativos autenticadores (Google
  Authenticator, Microsoft Authenticator, Authy) leem do QR. Aceita o passo anterior e o seguinte (o relógio do celular
  anda um pouco), e o mesmo código não vale duas vezes (`totp_ultimo_passo`).
- O segredo fica cifrado (`core.cripto`, a chave do GS). O cadastro começa no primeiro login com a senha certa e só vale
  depois do primeiro código certo; até lá, um login novo troca o segredo.
- Entre a senha e o código, a pessoa leva um DESAFIO: um token de 10 minutos, de escopo `2fa`, que nenhuma guarda de
  portão aceita, e que diz para onde a entrada vai (`para`).
- `GS_2FA_DESLIGADA=1` desliga a exigência na hora (a saída de emergência se o cadastro travar alguém da plataforma).
"""
import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from jose import JWTError, jwt

from app.core import cripto
from app.core.config import get_settings
from app.models.user import Perfil, User

DIGITOS, PASSO_S = 6, 30
#: quem tem de usar: o gerente da O&M e a plataforma (o plano)
EXIGIDA_PARA = (Perfil.ADMINISTRADOR, Perfil.ATENDIMENTO, Perfil.GESTOR_EMPRESA)
VALIDADE_DO_DESAFIO = timedelta(minutes=10)
EMISSOR = "Gestão Solar"


def exigida(u: User) -> bool:
    return not get_settings().gs_2fa_desligada and u.perfil in EXIGIDA_PARA


def ativa(u: User) -> bool:
    return u.totp_ativo_em is not None and bool(u.totp_segredo_cifrado)


#: o código errado também tem limite POR CONTA, de qualquer lugar (avaliação de 24/11/2026): com a senha vazada e
#: muitos IPs, os palpites do código param em 10 erros por 15 min, e a pessoa fica sabendo
ERROS_POR_CONTA = 10


def _chave(u: User) -> str:
    return f"2fa-conta:{u.id}"


def bloqueada(u: User) -> bool:
    from app.services import acessos
    return acessos.erros_recentes(_chave(u)) >= ERROS_POR_CONTA


def errou(db, request, u: User) -> None:
    """Um código errado: conta no limite da conta e, quando ele bate, registra e avisa a pessoa (uma vez por janela)."""
    from app.services import acessos
    if acessos.somar_erro(_chave(u)) >= ERROS_POR_CONTA and acessos._uma_vez(f"{_chave(u)}|bloqueada"):
        acessos.registrar(db, request, acao="bloqueado", user=u, ok=False,
                          motivo=f"verificação em duas etapas: {ERROS_POR_CONTA} códigos errados em 15 min, de "
                                 "qualquer lugar; o código fica bloqueado por 15 min")
        avisar(u, "⚠️ Gestão Solar: o código da verificação em duas etapas da sua conta foi errado 10 vezes agora, e "
                  "ficou bloqueado por 15 minutos. Se não foi você, troque a sua senha: mande «esqueci a senha» aqui.")


def avisar(u: User, texto: str) -> None:
    """O aviso à própria pessoa pelo WhatsApp do GS, no celular cadastrado: sem esperar e sem garantia (fora da janela
    de 24 h da conversa, a Meta recusa e ele não chega). O que vale é o Registro de acessos, que fica sempre."""
    if not u.telefone or not get_settings().whatsapp_gateway_url:
        return
    import asyncio
    import threading

    from app.clients import whatsapp
    telefone = u.telefone

    def _manda() -> None:
        try:
            asyncio.run(whatsapp.enviar_conteudo(telefone=telefone, tipo="text", texto=texto, origem="seguranca"))
        except Exception:                                  # noqa: BLE001 — o aviso é de cortesia; o registro fica
            pass
    threading.Thread(target=_manda, daemon=True).start()


def pendente(u: User) -> bool:
    """A conta exige o código e ainda não cadastrou o autenticador: nenhuma sessão dela vale (as de antes de ligar a
    exigência, ou de quando o interruptor estava desligado) até ela entrar com a senha e cadastrar."""
    return exigida(u) and not ativa(u)


def situacao(u: User) -> str:
    """O que as telas de usuários mostram: `desligada` (o interruptor `GS_2FA_DESLIGADA` está ligado: ninguém precisa do
    código agora), `ativa`, `a_cadastrar` (exigida e ainda sem o autenticador) ou `nao_exigida` (a conta não precisa;
    se já cadastrou, `ativa`)."""
    if get_settings().gs_2fa_desligada:
        return "desligada"
    if ativa(u):
        return "ativa"
    return "a_cadastrar" if u.perfil in EXIGIDA_PARA else "nao_exigida"


def _codigo(segredo_b32: str, passo: int) -> str:
    chave = base64.b32decode(segredo_b32 + "=" * (-len(segredo_b32) % 8), casefold=True)
    h = hmac.new(chave, struct.pack(">Q", passo), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITOS:0{DIGITOS}d}"


def comecar_cadastro(u: User) -> dict:
    """Um segredo novo (o cadastro não confirmado de antes é trocado), o endereço `otpauth://` e o QR. Não confirma."""
    if ativa(u):
        raise ValueError("A verificação em duas etapas desta conta já está ativa.")
    segredo = base64.b32encode(os.urandom(20)).decode().rstrip("=")
    u.totp_segredo_cifrado = cripto.cifrar(segredo)
    u.totp_ativo_em = None
    u.totp_ultimo_passo = None
    endereco = (f"otpauth://totp/{quote(EMISSOR)}:{quote(u.apelido)}?secret={segredo}"
                f"&issuer={quote(EMISSOR)}&digits={DIGITOS}&period={PASSO_S}")
    import segno
    qr = segno.make(endereco, error="m").svg_data_uri(scale=5, border=2, dark="#000", light="#fff")
    return {"segredo": " ".join(segredo[i:i + 4] for i in range(0, len(segredo), 4)), "otpauth": endereco, "qr": qr}


def conferir(u: User, codigo: str | None) -> bool:
    """O código certo (o de agora, o de antes ou o de depois, e ainda não usado). O primeiro certo confirma o
    cadastro. Não confirma a transação."""
    digitos = "".join(c for c in (codigo or "") if c.isdigit())
    if len(digitos) != DIGITOS or not u.totp_segredo_cifrado:
        return False
    try:
        segredo = cripto.decifrar(u.totp_segredo_cifrado)
    except Exception:                                      # noqa: BLE001 — segredo ilegível: o código não confere
        return False
    agora = int(time.time()) // PASSO_S
    for passo in (agora - 1, agora, agora + 1):
        if passo > (u.totp_ultimo_passo or 0) and hmac.compare_digest(_codigo(segredo, passo), digitos):
            u.totp_ultimo_passo = passo
            if u.totp_ativo_em is None:
                u.totp_ativo_em = datetime.now(UTC)
            return True
    return False


def refazer(u: User) -> None:
    """Apaga o cadastro (o gerente ou a plataforma, quando a pessoa perdeu o celular): no próximo login, cadastra de
    novo. Não confirma."""
    u.totp_segredo_cifrado = None
    u.totp_ativo_em = None
    u.totp_ultimo_passo = None


def desafio(u: User, para: str) -> str:
    """O token entre a senha e o código: 10 minutos, escopo `2fa` (nenhuma guarda o aceita), com o destino."""
    s = get_settings()
    return jwt.encode({"sub": str(u.id), "escopo": "2fa", "para": para,
                       "exp": datetime.now(UTC) + VALIDADE_DO_DESAFIO}, s.gs_jwt_secret, algorithm="HS256")


def do_desafio(token: str | None, para: str) -> int | None:
    """O id da conta do desafio, se ele vale para este destino; senão None."""
    try:
        dados = jwt.decode(token or "", get_settings().gs_jwt_secret, algorithms=["HS256"])
    except JWTError:
        return None
    if dados.get("escopo") != "2fa" or dados.get("para") != para or not str(dados.get("sub", "")).isdigit():
        return None
    return int(dados["sub"])


if __name__ == "__main__":                                 # o vetor da RFC 6238 (SHA-1, 8 dígitos → os 6 finais)
    chave = base64.b32encode(b"12345678901234567890").decode()
    assert _codigo(chave, 59 // 30) == "287082"            # 94287082 na RFC
    assert _codigo(chave, 1111111109 // 30) == "081804"    # 07081804
    print("ok")
