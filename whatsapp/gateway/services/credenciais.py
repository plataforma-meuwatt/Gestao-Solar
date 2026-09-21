"""Ler, testar e gravar as credenciais da Meta.

## Testar ANTES de gravar

A ordem é a mesma de `integracoes.salvar_token` no BFF, pela mesma razão: gravar primeiro e
testar depois deixaria o gestor com a credencial nova quebrada **e** a antiga perdida, sem
caminho de volta. Aqui o teste é uma chamada à Graph perguntando pelo próprio número — se
ela responde, o token vale, o número existe e o app alcança os dois.

## Cache curto, porque o webhook precisa do segredo a cada entrega

Conferir a assinatura de cada mensagem exige o `app_secret`. Ir ao banco a cada entrega
seria uma consulta por mensagem recebida; guardar para sempre em memória faria a troca pela
tela não valer até o próximo deploy. Trinta segundos resolve os dois: o custo some e uma
credencial trocada passa a valer quase na hora.

## O que nunca sai daqui

O token em claro não volta por rota nenhuma — nem para quem o colou. O que a tela recebe é
o prefixo, o estado e a data. Quem perdeu o valor gera outro na Meta, que é o comportamento
correto quando só o cifrado fica guardado.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.core import cripto
from gateway.core.config import get_settings
from gateway.meta import graph
from gateway.models.credencial import ESCOPO_PADRAO, Credencial, CredencialEvento

TIMEOUT_S = 15.0
#: Quanto tempo o segredo fica em memória entre uma entrega do webhook e a seguinte.
CACHE_S = 30


@dataclass
class Credenciais:
    """O que o resto do serviço precisa, já decifrado."""

    phone_number_id: str | None
    token: str | None
    app_secret: str | None
    verify_token: str | None
    #: Só a listagem precisa dele: enviar usa o `phone_number_id`. É por isso que o WABA
    #: errado passou despercebido no primeiro cadastro — o teste de envio dizia "ok".
    waba_id: str | None = None

    @property
    def envio_pronto(self) -> bool:
        return bool(self.token and self.phone_number_id)

    @property
    def listagem_pronta(self) -> bool:
        return bool(self.token and self.waba_id)


@dataclass
class Resultado:
    ok: bool
    detalhe: str
    numeros_visiveis: int | None = None


_cache: tuple[float, Credenciais] | None = None


def _linha(db: Session) -> Credencial | None:
    return db.scalar(select(Credencial).where(Credencial.escopo == ESCOPO_PADRAO))


def registrar(
    db: Session,
    evento: str,
    *,
    ator: str | None = None,
    detalhe: str | None = None,
    token_prefixo: str | None = None,
    numeros_visiveis: int | None = None,
) -> None:
    """Grava o evento. NÃO faz commit — quem chama decide a transação."""
    db.add(
        CredencialEvento(
            evento=evento,
            ator=ator,
            detalhe=detalhe,
            token_prefixo=token_prefixo,
            numeros_visiveis=numeros_visiveis,
        )
    )


def invalidar_cache() -> None:
    global _cache
    _cache = None


def em_uso(db: Session) -> Credenciais:
    """As credenciais válidas agora, decifradas, com cache de `CACHE_S` segundos."""
    global _cache
    agora = time.monotonic()
    if _cache is not None and (agora - _cache[0]) < CACHE_S:
        return _cache[1]

    linha = _linha(db)
    if linha is None:
        valor = Credenciais(None, None, None, None)
    else:
        valor = Credenciais(
            waba_id=linha.waba_id,
            phone_number_id=linha.phone_number_id,
            token=cripto.decifrar(linha.token_cifrado) if linha.token_cifrado else None,
            app_secret=(
                cripto.decifrar(linha.app_secret_cifrado) if linha.app_secret_cifrado else None
            ),
            verify_token=(
                cripto.decifrar(linha.verify_token_cifrado)
                if linha.verify_token_cifrado
                else None
            ),
        )
    _cache = (agora, valor)
    return valor


def estado(db: Session) -> dict[str, Any]:
    """O que a tela mostra. Nenhum segredo sai por aqui."""
    linha = _linha(db)
    if linha is None:
        return {
            "configurada": False,
            "envio_pronto": False,
            "webhook_pronto": False,
            "estado": "nunca",
            "cifragem_disponivel": cripto.disponivel(),
        }
    return {
        "configurada": True,
        "envio_pronto": linha.envio_pronto,
        "webhook_pronto": linha.webhook_pronto,
        "phone_number_id": linha.phone_number_id,
        "waba_id": linha.waba_id,
        "app_id": linha.app_id,
        "numero_exibicao": linha.numero_exibicao,
        "token_prefixo": linha.token_prefixo,
        "token_gravado_em": linha.token_gravado_em,
        "estado": linha.estado,
        "detalhe": linha.detalhe,
        "testada_em": linha.testada_em,
        "atualizada_em": linha.atualizada_em,
        "atualizada_por": linha.atualizada_por,
        "cifragem_disponivel": cripto.disponivel(),
    }


def historico(db: Session, limite: int = 30) -> list[CredencialEvento]:
    return list(
        db.scalars(
            select(CredencialEvento).order_by(CredencialEvento.ocorrido_em.desc()).limit(limite)
        ).all()
    )


async def _exercitar(token: str, phone_number_id: str) -> Resultado:
    """Pergunta à Graph pelo próprio número. É o teste mais barato que prova as três coisas.

    Traduz a recusa da Meta para uma frase que diz o que corrigir. O erro que mais aparece é
    o token temporário de 24 h vencido, e "Error validating access token" não conta isso a
    quem está olhando a tela.
    """
    s = get_settings()
    url = f"{s.graph_url}/{phone_number_id}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            r = await cliente.get(
                url,
                params={"fields": "display_phone_number,verified_name,quality_rating"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        return Resultado(False, f"Não foi possível falar com a Meta: {e}")

    dados: Any = {}
    try:
        dados = r.json()
    except ValueError:
        pass

    if r.status_code == 401 or (isinstance(dados, dict) and dados.get("error", {}).get("code") == 190):
        return Resultado(
            False,
            "A Meta recusou o token. O token do painel do app expira em 24 h — gere um "
            "permanente, de usuário do sistema, no Gerenciador de Negócios.",
        )
    if r.status_code == 404:
        return Resultado(False, "Número não encontrado: confira o Phone Number ID.")
    if r.status_code >= 400:
        erro = dados.get("error", {}) if isinstance(dados, dict) else {}
        return Resultado(
            False,
            erro.get("error_user_msg") or erro.get("message") or f"A Meta respondeu {r.status_code}.",
        )

    numero = dados.get("display_phone_number") if isinstance(dados, dict) else None
    nome = dados.get("verified_name") if isinstance(dados, dict) else None
    partes = [p for p in (nome, numero) if p]
    return Resultado(
        True,
        "Conectado" + (f" como {' · '.join(partes)}" if partes else "") + ".",
        numeros_visiveis=1,
    )


def _gravar_resultado(linha: Credencial, r: Resultado) -> None:
    linha.estado = "ok" if r.ok else "falhou"
    linha.detalhe = r.detalhe
    linha.testada_em = datetime.now(UTC)


async def salvar(
    db: Session,
    *,
    phone_number_id: str,
    token: str | None,
    app_secret: str | None,
    verify_token: str | None,
    waba_id: str | None = None,
    app_id: str | None = None,
    ator: str | None = None,
) -> Resultado:
    """Testa e grava. Só persiste depois de a Meta confirmar o par token + número.

    Campos de segredo vazios significam "não mexer": a tela manda o formulário inteiro, e o
    gestor que só corrigiu o WABA não precisa colar o token de novo — ele não o tem mais.
    """
    if not cripto.disponivel():
        return Resultado(
            False,
            "GATEWAY_ENCRYPTION_KEY não configurada no serviço: sem ela o token iria para o "
            "banco em texto. Configure a variável e tente de novo.",
        )

    linha = _linha(db) or Credencial(escopo=ESCOPO_PADRAO)
    token_efetivo = token or (
        cripto.decifrar(linha.token_cifrado) if linha.token_cifrado else None
    )
    if not token_efetivo:
        return Resultado(False, "Cole o token de acesso da Meta.")
    if not phone_number_id.strip():
        return Resultado(False, "Informe o Phone Number ID.")

    r = await _exercitar(token_efetivo, phone_number_id.strip())
    if not r.ok:
        # A credencial anterior continua de pé: nada foi tocado.
        registrar(db, "testada_falhou", ator=ator, detalhe=r.detalhe)
        db.commit()
        return r

    linha.phone_number_id = phone_number_id.strip()
    if waba_id is not None:
        linha.waba_id = waba_id.strip() or None
    if app_id is not None:
        linha.app_id = app_id.strip() or None
    if token:
        linha.token_cifrado = cripto.cifrar(token)
        linha.token_prefixo = token[:7]
        linha.token_gravado_em = datetime.now(UTC)
    if app_secret:
        linha.app_secret_cifrado = cripto.cifrar(app_secret)
    if verify_token:
        linha.verify_token_cifrado = cripto.cifrar(verify_token)
    linha.atualizada_por = ator
    _gravar_resultado(linha, r)

    db.add(linha)
    registrar(db, "gravada", ator=ator, detalhe=r.detalhe, token_prefixo=linha.token_prefixo,
              numeros_visiveis=r.numeros_visiveis)
    db.commit()
    invalidar_cache()
    return r


async def testar(db: Session, *, ator: str | None = None) -> Resultado:
    """Reexercita o que já está gravado — o token pode ter sido revogado do outro lado."""
    linha = _linha(db)
    if linha is None or not linha.token_cifrado or not linha.phone_number_id:
        return Resultado(False, "Nenhuma credencial gravada ainda.")

    r = await _exercitar(cripto.decifrar(linha.token_cifrado), linha.phone_number_id)
    _gravar_resultado(linha, r)
    registrar(
        db,
        "testada_ok" if r.ok else "testada_falhou",
        ator=ator,
        detalhe=r.detalhe,
        token_prefixo=linha.token_prefixo,
        numeros_visiveis=r.numeros_visiveis,
    )
    db.commit()
    invalidar_cache()
    return r


def remover(db: Session, *, ator: str | None = None) -> None:
    """Apaga os segredos. O app continua existindo na Meta — revogar é lá.

    A linha fica, com os identificadores e o histórico: apagá-la inteira perderia o registro
    de que houve credencial, que é justamente o que se procura quando o envio para.
    """
    linha = _linha(db)
    if linha is None:
        return
    prefixo = linha.token_prefixo
    linha.token_cifrado = None
    linha.token_prefixo = None
    linha.token_gravado_em = None
    linha.app_secret_cifrado = None
    linha.verify_token_cifrado = None
    linha.estado = "nunca"
    linha.detalhe = "Credenciais removidas pelo painel."
    linha.atualizada_por = ator
    registrar(db, "removida", ator=ator, token_prefixo=prefixo)
    db.commit()
    invalidar_cache()


# ── o que a conta tem ───────────────────────────────────────────────────────


class ListagemIndisponivel(RuntimeError):
    """Falta token ou WABA — a tela precisa da frase, não de um 500."""


async def numeros(db: Session) -> list[dict[str, Any]]:
    """Os números da conta, para a tela deixar de pedir identificadores de cabeça.

    Existe por um episódio concreto (21/09/2026): configurar o gateway virou uma caça a
    três identificadores de dezesseis dígitos, em três telas diferentes do Gerenciador —
    e o primeiro cadastro foi feito com o número de TESTE e um WABA que nem era o do
    número. Nada acusou: o teste de envio respondeu "ok", porque enviar não usa o WABA.
    """
    cred = em_uso(db)
    if not cred.listagem_pronta:
        raise ListagemIndisponivel(
            "Para listar os números, grave o token e o WABA ID."
        )
    itens, erro = await graph.listar_numeros(token=cred.token, waba_id=cred.waba_id)
    if erro:
        raise ListagemIndisponivel(erro)
    return itens


async def templates(db: Session) -> list[dict[str, Any]]:
    """Os modelos da conta, aprovados ou não — ver `graph.listar_templates`."""
    cred = em_uso(db)
    if not cred.listagem_pronta:
        raise ListagemIndisponivel(
            "Para listar os modelos, grave o token e o WABA ID."
        )
    itens, erro = await graph.listar_templates(token=cred.token, waba_id=cred.waba_id)
    if erro:
        raise ListagemIndisponivel(erro)
    return itens
