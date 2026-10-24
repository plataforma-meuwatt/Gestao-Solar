"""Falar com a Graph API — o único lugar do sistema que toca o token da Meta.

As credenciais chegam como PARÂMETRO, não de `settings`: elas vivem cifradas no banco e são
cadastradas pela tela (`services/credenciais.py`). Ler configuração aqui dentro faria este
módulo depender do banco e, pior, esconderia de quem chama que existe um estado que pode
não estar configurado.

**Template e RESPOSTA.** Mensagem iniciada pela empresa exige modelo aprovado. Texto livre,
documento e imagem (`enviar_conteudo`) só valem dentro da janela de 24 h depois de o
cliente escrever — é o assistente respondendo, nunca puxando assunto.

As duas funções de LEITURA no fim do arquivo (`listar_numeros`, `listar_templates`)
existem para a tela não pedir que alguém saiba de cabeça os identificadores da Meta. Elas
perguntam à conta o que ela tem; sem isso, configurar o gateway virava uma caça a números
de dezesseis dígitos em três telas diferentes do Gerenciador — e escolher o errado não dá
erro nenhum, porque a conta de teste responde igualzinho à de produção.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from gateway.core.config import get_settings
from gateway.core.telefone import para_envio

TIMEOUT_S = 20.0


@dataclass
class Resposta:
    ok: bool
    wamid: str | None = None
    erro_codigo: str | None = None
    erro_detalhe: str | None = None


def _corpo_do_template(
    telefone: str, template: str, idioma: str, parametros: list[str]
) -> dict[str, Any]:
    componentes = []
    if parametros:
        componentes.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in parametros],
            }
        )
    return {
        "messaging_product": "whatsapp",
        "to": para_envio(telefone),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": idioma},
            **({"components": componentes} if componentes else {}),
        },
    }


def _ler_erro(dados: Any) -> tuple[str | None, str | None]:
    if not isinstance(dados, dict):
        return None, None
    erro = dados.get("error")
    if not isinstance(erro, dict):
        return None, None
    codigo = erro.get("code")
    detalhe = erro.get("error_user_msg") or erro.get("message")
    return (str(codigo) if codigo is not None else None), detalhe


async def enviar_template(
    *,
    token: str,
    phone_number_id: str,
    telefone: str,
    template: str,
    parametros: list[str],
    idioma: str = "pt_BR",
) -> Resposta:
    """Manda um template aprovado. Nunca levanta por recusa da Meta — devolve o motivo.

    Recusa é resultado, não erro de programa: o número pode ter bloqueado a empresa, o
    template pode ter sido pausado por qualidade. Quem chamou grava isso na linha da
    mensagem; um 500 aqui viraria "erro interno" numa tela que precisava dizer "o cliente
    bloqueou o seu número".
    """
    return await _enviar(token, phone_number_id, _corpo_do_template(telefone, template, idioma, parametros))


async def enviar_conteudo(*, token: str, phone_number_id: str, telefone: str, tipo: str,
                          conteudo: dict[str, Any]) -> Resposta:
    """Texto livre, documento ou imagem — RESPOSTA dentro da janela de 24 h."""
    return await _enviar(token, phone_number_id, {
        "messaging_product": "whatsapp", "to": para_envio(telefone), "type": tipo, tipo: conteudo})


#: O maior arquivo que o gateway baixa para alguém (nota de voz tem poucos KB).
TETO_DO_ARQUIVO = 16 * 1024 * 1024


async def baixar_midia(*, token: str, media_id: str) -> tuple[bytes | None, str | None, str | None]:
    """Baixa um arquivo RECEBIDO: a Meta devolve um endereço temporário, que pede o mesmo token.
    Devolve `(conteúdo, tipo, erro)` — recusa e rede fora são resultado, não exceção."""
    s = get_settings()
    cabecalho = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=60) as cliente:
            r = await cliente.get(f"{s.graph_url}/{media_id}", headers=cabecalho)
            dados = r.json()
            if r.status_code >= 400 or not isinstance(dados, dict) or not dados.get("url"):
                return None, None, _ler_erro(dados)[1] or f"A Meta respondeu {r.status_code}."
            if int(dados.get("file_size") or 0) > TETO_DO_ARQUIVO:
                return None, None, "Arquivo grande demais."
            arquivo = await cliente.get(dados["url"], headers=cabecalho)
    except (httpx.HTTPError, ValueError) as exc:
        return None, None, f"Não deu para baixar o arquivo da Meta: {exc}"
    if arquivo.status_code >= 400:
        return None, None, f"A Meta respondeu {arquivo.status_code} ao entregar o arquivo."
    if len(arquivo.content) > TETO_DO_ARQUIVO:
        return None, None, "Arquivo grande demais."
    return arquivo.content, dados.get("mime_type"), None


async def subir_midia(*, token: str, phone_number_id: str, raw: bytes, mime: str,
                      filename: str) -> tuple[str | None, str | None]:
    """Sobe o arquivo na Meta e devolve `(media_id, erro)` — o envio referencia o id."""
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=120) as cliente:
            r = await cliente.post(f"{s.graph_url}/{phone_number_id}/media",
                                   headers={"Authorization": f"Bearer {token}"},
                                   data={"messaging_product": "whatsapp", "type": mime},
                                   files={"file": (filename, raw, mime)})
        dados = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return None, str(e)
    if r.status_code >= 400 or not dados.get("id"):
        return None, (_ler_erro(dados)[1] or r.text[:300])
    return str(dados["id"]), None


async def digitando(*, token: str, phone_number_id: str, wamid: str) -> None:
    """Marca a mensagem recebida como LIDA e mostra "digitando…" (a Meta apaga aos 25 s
    ou quando a resposta sai). Melhor esforço: falhar aqui não pode atrasar a resposta."""
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            await cliente.post(f"{s.graph_url}/{phone_number_id}/messages",
                               headers={"Authorization": f"Bearer {token}"},
                               json={"messaging_product": "whatsapp", "status": "read",
                                     "message_id": wamid, "typing_indicator": {"type": "text"}})
    except httpx.HTTPError:
        pass


async def _enviar(token: str, phone_number_id: str, corpo: dict[str, Any]) -> Resposta:
    s = get_settings()
    url = f"{s.graph_url}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            r = await cliente.post(url, json=corpo, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        # Rede fora não é recusa: quem chamou grava `falhou` com o motivo e pode reenviar.
        return Resposta(ok=False, erro_codigo="rede", erro_detalhe=str(e))

    try:
        dados = r.json()
    except ValueError:
        dados = {}

    if r.status_code >= 400:
        codigo, detalhe = _ler_erro(dados)
        return Resposta(
            ok=False,
            erro_codigo=codigo or str(r.status_code),
            erro_detalhe=detalhe or (r.text or "")[:300],
        )

    mensagens = dados.get("messages") if isinstance(dados, dict) else None
    wamid = None
    if isinstance(mensagens, list) and mensagens and isinstance(mensagens[0], dict):
        wamid = mensagens[0].get("id")

    if not wamid:
        # 200 sem id é resposta que não dá para rastrear: melhor tratar como falha do que
        # gravar uma mensagem que nenhum aviso de status vai alcançar.
        return Resposta(ok=False, erro_codigo="sem_wamid", erro_detalhe=str(dados)[:300])

    return Resposta(ok=True, wamid=str(wamid))


# ── leitura da conta ────────────────────────────────────────────────────────
#
# Ambas devolvem `(itens, erro)` em vez de levantar: a tela precisa mostrar a frase da
# Meta ("token sem permissão", "conta não encontrada") no lugar da lista, e uma exceção
# aqui viraria 500 numa tela que só queria listar.


async def _ler(token: str, caminho: str, params: dict[str, Any]) -> tuple[list[dict], str | None]:
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            r = await cliente.get(
                f"{s.graph_url}/{caminho}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        return [], f"Não deu para falar com a Meta: {e}"

    try:
        dados = r.json()
    except ValueError:
        dados = {}

    if r.status_code >= 400:
        _, detalhe = _ler_erro(dados)
        return [], detalhe or (r.text or "")[:300]

    itens = dados.get("data") if isinstance(dados, dict) else None
    return (itens if isinstance(itens, list) else []), None


async def listar_numeros(*, token: str, waba_id: str) -> tuple[list[dict], str | None]:
    """Os números da conta, com o id que vai no campo `Phone Number ID`.

    `quality_rating` e `code_verification_status` vêm junto porque são o que distingue um
    número pronto de um número que ainda não passou pela verificação — e a tela mentiria
    ao listar os dois do mesmo jeito.
    """
    return await _ler(
        token,
        f"{waba_id}/phone_numbers",
        {
            "fields": "id,display_phone_number,verified_name,quality_rating,"
            "code_verification_status,platform_type",
            "limit": 50,
        },
    )


async def listar_templates(*, token: str, waba_id: str) -> tuple[list[dict], str | None]:
    """Os modelos de mensagem da conta, aprovados ou não.

    Os reprovados e os pendentes também vêm: esconder um template recusado faria o gestor
    procurar por que o robô não manda nada, quando a resposta está escrita na Meta.
    """
    return await _ler(
        token,
        f"{waba_id}/message_templates",
        {"fields": "name,status,category,language,components", "limit": 100},
    )


# ── Embedded Signup: o número de cada técnico ───────────────────────────────
#
# Mesma regra das leituras acima: `(dados, erro)` em vez de exceção. Cada passo da conexão
# pode ser recusado pela Meta por um motivo que o técnico precisa ler ("o código expirou",
# "o app não tem acesso a esta conta"), e um 500 esconderia exatamente isso.
#
# Fontes, conferidas em 07/10/2026 (ver docs/PLANO_WHATSAPP_TECNICOS.md §3):
# troca do code, `subscribed_apps` e `register` em "onboarding customers as a Tech
# Provider"; `smb_app_data` e a proibição do `register` na coexistência em "onboarding
# business app users".


async def _chamar(
    metodo: str,
    caminho: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    s = get_settings()
    cabecalhos = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
            r = await cliente.request(
                metodo, f"{s.graph_url}/{caminho}", params=params, json=json, headers=cabecalhos
            )
    except httpx.HTTPError as e:
        return {}, f"Não deu para falar com a Meta: {e}"

    try:
        dados = r.json()
    except ValueError:
        dados = {}
    if not isinstance(dados, dict):
        dados = {}

    if r.status_code >= 400:
        _, detalhe = _ler_erro(dados)
        return dados, detalhe or (r.text or "")[:300] or f"HTTP {r.status_code}"
    return dados, None


async def trocar_code(*, app_id: str, app_secret: str, code: str) -> tuple[str | None, str | None]:
    """O `code` do Embedded Signup vira o token do número. O code vive 30 SEGUNDOS."""
    dados, erro = await _chamar(
        "GET",
        "oauth/access_token",
        params={"client_id": app_id, "client_secret": app_secret, "code": code},
    )
    if erro:
        return None, erro
    token = dados.get("access_token")
    return (str(token), None) if token else (None, "A Meta não devolveu o token.")


async def assinar_waba(*, token: str, waba_id: str) -> str | None:
    """Liga o webhook do app da plataforma à conta do técnico. Sem isto, nada chega."""
    _, erro = await _chamar("POST", f"{waba_id}/subscribed_apps", token=token)
    return erro


async def desassinar_waba(*, token: str, waba_id: str) -> str | None:
    _, erro = await _chamar("DELETE", f"{waba_id}/subscribed_apps", token=token)
    return erro


async def registrar_numero(*, token: str, phone_number_id: str, pin: str) -> str | None:
    """Só FORA da coexistência: o número que já está no aplicativo já está registrado."""
    _, erro = await _chamar(
        "POST",
        f"{phone_number_id}/register",
        token=token,
        json={"messaging_product": "whatsapp", "pin": pin},
    )
    return erro


async def sincronizar_aplicativo(*, token: str, phone_number_id: str, tipo: str) -> str | None:
    """Pede os contatos (`smb_app_state_sync`) ou o histórico (`history`) do celular.

    Só na coexistência, e com prazo: se o sync não acontecer em 24 h, o técnico precisa
    desconectar e refazer o fluxo. O que chega vem pelo webhook, não por esta resposta.
    """
    _, erro = await _chamar(
        "POST",
        f"{phone_number_id}/smb_app_data",
        token=token,
        json={"messaging_product": "whatsapp", "sync_type": tipo},
    )
    return erro
