"""As duas portas do gateway: a da Meta e a do BFF.

**A da Meta é a assinatura.** Toda entrega do webhook vem com `X-Hub-Signature-256`, que é
o HMAC-SHA256 do CORPO CRU com o segredo do app. Conferir sobre o corpo já convertido em
objeto não funcionaria: `json.dumps` reordena e reespaça, e a assinatura passaria a falhar
por diferença de formatação, não de origem. Por isso as rotas leem `await request.body()`.

**A do BFF é uma chave em cabeçalho**, no mesmo padrão de `bff/app/api/v1/avisos.py`: quem
chama é um servidor, não um humano, e não há login. Sem a chave configurada, a porta recusa
tudo — falhar fechado é o único padrão aceitável para um endpoint que manda mensagem para o
celular de gente.

As duas comparações usam `compare_digest`. A comparação ingênua vaza o segredo pelo tempo de
resposta, um caractere por vez.
"""

import hashlib
import hmac

CABECALHO_ASSINATURA = "X-Hub-Signature-256"
CABECALHO_CHAVE_INTERNA = "X-Chave-Interna"


def assinatura_da_meta(segredo: str, corpo: bytes) -> str:
    """O valor que a Meta manda no cabeçalho, para conferência e para testes."""
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


def assinatura_confere(segredo: str, corpo: bytes, cabecalho: str | None) -> bool:
    if not segredo or not cabecalho:
        return False
    return hmac.compare_digest(assinatura_da_meta(segredo, corpo), cabecalho.strip())


def chave_interna_confere(esperada: str, recebida: str | None) -> bool:
    if not esperada:
        return False
    return hmac.compare_digest(esperada, (recebida or "").strip())
