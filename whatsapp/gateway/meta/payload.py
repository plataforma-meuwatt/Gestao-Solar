"""Ler o corpo do webhook da Meta sem nunca confiar no formato.

O payload é aninhado e **todos os níveis são listas**: `entry[].changes[].value.messages[]`.
Uma entrega pode trazer mensagens de duas usinas, ou uma mensagem e três status, ou nada
além de metadados. Percorrer isso com `[0]` funciona nos exemplos da documentação e falha no
segundo dia.

Este módulo é puro: recebe dicionário, devolve listas de dataclasses. Sem banco, sem rede —
é o que permite testá-lo com os payloads reais salvos em `tests/fixtures`.

O que ele NÃO faz: decidir. Tipo desconhecido vira `MensagemRecebida` com `tipo` preenchido
e `texto` nulo; status desconhecido é devolvido como veio. Quem decide o que fazer é o
serviço — aqui, engolir um campo estranho seria perder a única pista do que mudou do lado
da Meta.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class MensagemRecebida:
    wamid: str
    wa_id: str
    tipo: str
    ocorrida_em: datetime
    texto: str | None = None
    nome_perfil: str | None = None


@dataclass
class AvisoDeStatus:
    wamid: str
    status: str
    ocorrida_em: datetime
    erro_codigo: str | None = None
    erro_detalhe: str | None = None


@dataclass
class Leitura:
    mensagens: list[MensagemRecebida] = field(default_factory=list)
    status: list[AvisoDeStatus] = field(default_factory=list)


def _lista(valor: Any) -> list[dict[str, Any]]:
    """Qualquer nível pode vir ausente, nulo ou com coisa que não é dicionário."""
    if not isinstance(valor, list):
        return []
    return [item for item in valor if isinstance(item, dict)]


def _quando(valor: Any) -> datetime:
    """O `timestamp` da Meta é epoch em SEGUNDOS, e vem como texto.

    Sem hora utilizável, cai no relógio do servidor: é aproximação honesta para ordenar a
    conversa, e a alternativa (descartar a mensagem) perderia o que o cliente escreveu.
    """
    try:
        return datetime.fromtimestamp(int(str(valor)), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _texto_da_mensagem(m: dict[str, Any], tipo: str) -> str | None:
    if tipo == "text":
        corpo = m.get("text")
        return corpo.get("body") if isinstance(corpo, dict) else None
    if tipo == "button":
        corpo = m.get("button")
        return corpo.get("text") if isinstance(corpo, dict) else None
    if tipo == "interactive":
        corpo = m.get("interactive") or {}
        for chave in ("button_reply", "list_reply"):
            parte = corpo.get(chave)
            if isinstance(parte, dict):
                return parte.get("title")
        return None
    # Mídia e o que mais existir: o conteúdo não vem no corpo, e inventar texto seria
    # apagar a diferença entre "mandou áudio" e "mandou vazio".
    return None


def _erro(s: dict[str, Any]) -> tuple[str | None, str | None]:
    erros = _lista(s.get("errors"))
    if not erros:
        return None, None
    primeiro = erros[0]
    codigo = primeiro.get("code")
    detalhe = primeiro.get("title") or primeiro.get("message")
    dados = primeiro.get("error_data")
    if isinstance(dados, dict) and dados.get("details"):
        detalhe = f"{detalhe} — {dados['details']}" if detalhe else dados["details"]
    return (str(codigo) if codigo is not None else None), detalhe


def ler(corpo: dict[str, Any]) -> Leitura:
    """Tudo o que esta entrega trouxe, achatado."""
    saida = Leitura()
    if not isinstance(corpo, dict):
        return saida

    for entry in _lista(corpo.get("entry")):
        for change in _lista(entry.get("changes")):
            valor = change.get("value")
            if not isinstance(valor, dict):
                continue

            # O nome do perfil vem numa lista IRMÃ das mensagens, casada pelo `wa_id`.
            perfis: dict[str, str] = {}
            for contato in _lista(valor.get("contacts")):
                wa_id = str(contato.get("wa_id") or "")
                perfil = contato.get("profile")
                if wa_id and isinstance(perfil, dict) and perfil.get("name"):
                    perfis[wa_id] = str(perfil["name"])

            for m in _lista(valor.get("messages")):
                wamid = str(m.get("id") or "")
                wa_id = str(m.get("from") or "")
                if not wamid or not wa_id:
                    continue
                tipo = str(m.get("type") or "text")
                saida.mensagens.append(
                    MensagemRecebida(
                        wamid=wamid,
                        wa_id=wa_id,
                        tipo=tipo,
                        ocorrida_em=_quando(m.get("timestamp")),
                        texto=_texto_da_mensagem(m, tipo),
                        nome_perfil=perfis.get(wa_id),
                    )
                )

            for s in _lista(valor.get("statuses")):
                wamid = str(s.get("id") or "")
                status = str(s.get("status") or "")
                if not wamid or not status:
                    continue
                codigo, detalhe = _erro(s)
                saida.status.append(
                    AvisoDeStatus(
                        wamid=wamid,
                        status=_TRADUCAO_DO_STATUS.get(status, status),
                        ocorrida_em=_quando(s.get("timestamp")),
                        erro_codigo=codigo,
                        erro_detalhe=detalhe,
                    )
                )

    return saida


#: O vocabulário da Meta traduzido para o do banco. `sent` e `delivered` são os dois que
#: mais aparecem; `failed` é o que interrompe.
_TRADUCAO_DO_STATUS = {
    "sent": "enviada",
    "delivered": "entregue",
    "read": "lida",
    "failed": "falhou",
}
