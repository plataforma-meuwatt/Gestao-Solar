"""Envio de push, pelo serviço do Expo.

**Por que não falar FCM direto.** O aplicativo é Expo, e o `expo-notifications`
entrega um `ExponentPushToken[...]`, não um token do Firebase. Quem traduz um no
outro é o serviço do Expo: ele guarda a chave do FCM (subida uma vez por
`eas credentials`) e faz a entrega. O BFF só precisa de um POST — nenhuma
credencial do Google mora aqui, o que é a parte boa: chave de serviço em variável
de ambiente de aplicação é vazamento esperando acontecer.

**A resposta importa tanto quanto o envio.** O Expo responde por token, e o erro
`DeviceNotRegistered` significa aparelho trocado, app desinstalado ou permissão
revogada no sistema. Sem tratar isso, a tabela de dispositivos só cresce e todo
envio arrasta uma cauda de tokens mortos. Por isso `enviar` devolve quais tokens
devem ser apagados, em vez de engolir a resposta.

**Nada é enviado sem permissão.** Este módulo não consulta permissão — quem
chama consulta. A separação é proposital: um único ponto decide quem recebe
(`services/permissoes.py`), e este arquivo só sabe entregar.
"""

from dataclasses import dataclass, field
from typing import Any

import httpx

#: O endpoint aceita até 100 mensagens por requisição. Acima disso ele recusa o lote
#: inteiro — não entrega as 100 primeiras e descarta o resto.
LOTE_MAXIMO = 100

URL = "https://exp.host/--/api/v2/push/send"


@dataclass
class Resultado:
    enviados: int = 0
    #: Tokens que o Expo declarou mortos. Quem chama deve apagá-los do banco.
    invalidos: list[str] = field(default_factory=list)
    #: Falhas que NÃO são token morto — rede, cota, erro do serviço. Não apagar nada.
    erros: list[str] = field(default_factory=list)


def _lotes(itens: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [itens[i : i + LOTE_MAXIMO] for i in range(0, len(itens), LOTE_MAXIMO)]


async def enviar(
    tokens: list[str],
    titulo: str,
    corpo: str,
    dados: dict[str, Any] | None = None,
) -> Resultado:
    """Entrega a mesma mensagem a vários aparelhos.

    `dados` viaja junto e chega ao app mesmo com ele fechado — é por ali que o toque
    na notificação sabe qual usina abrir.
    """
    resultado = Resultado()
    tokens = [t for t in dict.fromkeys(tokens) if t]  # sem repetição, sem vazio
    if not tokens:
        return resultado

    mensagens = [
        {
            "to": t,
            "title": titulo,
            "body": corpo,
            "data": dados or {},
            # `high` é o que faz o Android acordar o aparelho em vez de agrupar a
            # entrega para depois. Usina parada é o caso que justifica.
            "priority": "high",
            "sound": "default",
            "channelId": "paradas",
        }
        for t in tokens
    ]

    async with httpx.AsyncClient(timeout=20) as cliente:
        for lote in _lotes(mensagens):
            try:
                resposta = await cliente.post(
                    URL,
                    json=lote,
                    headers={"accept": "application/json", "content-type": "application/json"},
                )
                resposta.raise_for_status()
                corpo_json = resposta.json()
            except Exception as exc:  # noqa: BLE001
                # Lote inteiro perdido: é falha de transporte, não de token. Nenhum
                # dispositivo é apagado — apagar por erro de rede desligaria o push
                # de quem está com tudo certo.
                resultado.erros.append(f"{type(exc).__name__}: {exc}")
                continue

            for token, item in zip(lote, corpo_json.get("data") or [], strict=False):
                if not isinstance(item, dict):
                    continue
                if item.get("status") == "ok":
                    resultado.enviados += 1
                    continue
                detalhe = (item.get("details") or {}).get("error")
                if detalhe == "DeviceNotRegistered":
                    resultado.invalidos.append(token["to"])
                else:
                    resultado.erros.append(str(item.get("message") or detalhe or "falha"))

    return resultado
