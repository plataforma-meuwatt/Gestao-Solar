"""Fotos do WhatsApp anexadas numa tarefa do meuPlano (pedido do Renan, 26/10/2026).

A pessoa manda uma ou mais fotos (a legenda vale como texto). O álbum do WhatsApp chega como uma mensagem por foto, e o
bot responde uma vez só, na última (`e_a_ultima`). A IA chama `anexar_fotos` com a tarefa (ou a OS); o sistema confere a
situação da tarefa e o papel da pessoa e propõe "Anexar N foto(s) na tarefa #X", que ela confirma com Sim. Confirmada,
cada foto sai do gateway e entra em `POST /tasks/{id}/attachments` do meuPlano, a rota do app de campo, com o token DELA.

Regra do dono: o técnico anexa só em tarefa EM ABERTO (prevista, planejada, programada, em andamento); o gestor da O&M
também na EM ANÁLISE (realizada, esperando a verificação) e na CONCLUÍDA (aprovada). Cancelada não recebe foto.
"""

import asyncio
import logging
from time import monotonic
from typing import Any

import httpx

from app.clients import whatsapp
from app.models.user import Perfil
from app.services import assistente_helper as helper

log = logging.getLogger(__name__)

#: As fotos de cada número ainda não anexadas: id da mensagem no gateway, legenda, quando chegou.
#: ponytail: em memória, como as ações esperando (`helper.PENDENTES`); o deploy esquece, e a pessoa manda de novo.
_RECEBIDAS: dict[str, list[dict]] = {}
VALIDADE_S = 30 * 60
TETO = 20
#: O álbum chega como uma mensagem por foto, quase juntas: a última espera isto antes de responder.
JUNTAR_S = 4.0
PRAZO_S = 600

ABERTA = {"PREVISTA", "PLANEJADA", "PROGRAMADA", "EM_ANDAMENTO"}
DO_GESTOR = {"REALIZADA": "em análise", "APROVADA": "concluída"}


def e_foto(evento: dict) -> bool:
    mime = str((evento.get("midia") or {}).get("mime") or "")
    return evento.get("tipo") == "image" or (evento.get("tipo") == "document" and mime.startswith("image/"))


def recebidas(telefone: str) -> list[dict]:
    agora = monotonic()
    return [f for f in _RECEBIDAS.get(telefone, []) if agora - f["em"] < VALIDADE_S]


def guardar(telefone: str, evento: dict) -> None:
    """Na CHEGADA, antes da fila do número: a foto anterior do álbum precisa saber que veio outra."""
    agora = monotonic()
    for velho in [t for t, fs in _RECEBIDAS.items() if not fs or agora - fs[-1]["em"] >= VALIDADE_S]:
        del _RECEBIDAS[velho]
    legenda = str((evento.get("midia") or {}).get("legenda") or "").strip()
    _RECEBIDAS[telefone] = [*recebidas(telefone), {"id": evento.get("id"), "legenda": legenda, "em": agora}][-TETO:]


async def e_a_ultima(telefone: str, mensagem_id: Any) -> bool:
    """Do álbum, só a última foto responde; as outras ficam guardadas, caladas."""
    for espera in (0, JUNTAR_S):
        await asyncio.sleep(espera)
        fotos = recebidas(telefone)
        if not fotos or fotos[-1]["id"] != mensagem_id:
            return False
    return True


def mensagem(telefone: str) -> str:
    """O que a IA lê no lugar da foto (ela não vê a imagem)."""
    fotos = recebidas(telefone)
    legendas = "; ".join(dict.fromkeys(f["legenda"] for f in fotos if f["legenda"]))
    return f"[📷 {len(fotos)} foto(s) recebida(s), ainda não anexada(s)]" + (f" {legendas}" if legendas else "")


def _tirar(telefone: str, mensagem_id: Any) -> None:
    _RECEBIDAS[telefone] = [f for f in _RECEBIDAS.get(telefone, []) if f["id"] != mensagem_id]


def recusa(user, status: str | None) -> str | None:
    """Por que esta pessoa não anexa foto numa tarefa nesta situação; `None` = pode."""
    if status in ABERTA:
        return None
    if status in DO_GESTOR:
        return None if user.perfil == Perfil.GESTOR_EMPRESA else (
            f"está {DO_GESTOR[status]}: nela só o gestor da O&M anexa foto")
    return "está cancelada e não recebe foto" if status == "CANCELADA" else f"está em {status} e não recebe foto"


FERRAMENTA = {"type": "function", "function": {
    "name": "anexar_fotos",
    "description": ("Anexa numa TAREFA do meuPlano as fotos que a pessoa mandou por aqui e ainda não foram anexadas "
                    "(a mensagem dela aparece como «[📷 N foto(s) recebida(s)…]»). Vira uma ação que ela confirma com "
                    "Sim. Passe a tarefa (o número dela) ou, se a pessoa só disse a OS, a OS. Sem saber onde, pergunte "
                    "em qual tarefa ou OS: não escolha por ela."),
    "parameters": {"type": "object", "properties": {
        "tarefa": {"type": "integer", "description": "número da tarefa"},
        "os": {"type": "integer", "description": "número da OS, quando a pessoa não disse a tarefa"}}}}}


async def anexar_fotos(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    fotos = recebidas(ctx.telefone)
    if not fotos:
        return {"erro": "Não há foto recebida para anexar (cada foto fica guardada 30 min). Peça que a pessoa mande de novo."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    tarefa_id = a.get("tarefa")
    try:
        if not tarefa_id:
            if not a.get("os"):
                return {"erro": "Falta a tarefa ou a OS: pergunte à pessoa onde anexar."}
            tarefas = await mp.tarefas_da_ordem(int(a["os"]))
            cabem = [t for t in tarefas if recusa(ctx.user, t.get("status")) is None]
            if len(cabem) != 1:
                return {"erro": f"A OS {a['os']} tem {len(cabem)} tarefa(s) que podem receber foto desta pessoa: "
                                "pergunte em qual.",
                        "tarefas": [{"tarefa": t.get("id"), "nome": t.get("name"), "situacao": t.get("status")}
                                    for t in tarefas]}
            tarefa_id = cabem[0]["id"]
        t = await mp.tarefa(int(tarefa_id))
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 404):
            return {"erro": f"A tarefa ou OS não foi encontrada no meuPlano para esta pessoa ({e.response.status_code})."}
        raise
    if motivo := recusa(ctx.user, t.get("status")):
        return {"erro": f"A tarefa #{t['id']} {motivo}. Nada foi anexado."}
    tid, n = int(t["id"]), len(fotos)
    resumo = f"Anexar {n} foto(s) na tarefa #{tid} «{t.get('name') or 'sem nome'}»"
    onde = " · ".join(x for x in (f"OS {t['os_id']}" if t.get("os_id") else "", t.get("plant_name") or "") if x)

    async def executar(db, user, telefone: str) -> str:
        from app.services.integracoes import detalhe_do_upstream
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
            situacao = (await mp.tarefa(tid)).get("status")          # pode ter mudado enquanto esperava o Sim
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        except httpx.HTTPError:
            return f"❌ Não consegui conferir a tarefa #{tid} no meuPlano agora. Nenhuma foto foi anexada."
        if motivo := recusa(user, situacao):
            return f"❌ A tarefa #{tid} {motivo}. Nenhuma foto foi anexada."
        feitas, falhas = 0, []
        for i, f in enumerate(fotos, 1):
            try:
                conteudo, tipo = await whatsapp.baixar_midia(f["id"])
                await mp.anexar_na_tarefa(tid, f"whatsapp-{i}.{(tipo or 'image/jpeg').split('/')[-1].split(';')[0]}",
                                          conteudo, tipo, f["legenda"] or "Foto enviada pelo WhatsApp", user.nome)
            except whatsapp.GatewayIndisponivel:
                falhas.append(f"foto {i}: não consegui baixar do WhatsApp")
                continue
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500 and not feitas:
                    motivo = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
                    return f"❌ O meuPlano recusou: {motivo}. Nenhuma foto foi anexada."
                falhas.append(f"foto {i}: o meuPlano deu erro {e.response.status_code}")
                continue
            except httpx.HTTPError:
                falhas.append(f"foto {i}: o meuPlano não respondeu a tempo (pode ter entrado: confira)")
                continue
            feitas += 1
            _tirar(telefone, f["id"])
        motivos = "".join(f"\n• {m}" for m in falhas)
        if not feitas:
            return f"❌ Nenhuma foto foi anexada na tarefa #{tid}:{motivos}"
        if falhas:
            return f"⚠️ Anexei {feitas} de {n} foto(s) na tarefa #{tid}:{motivos}"
        return f"✅ {feitas} foto(s) anexada(s) na tarefa #{tid} no meuPlano."

    return helper.propor(ctx, resumo, PRAZO_S, executar, [onde], parte="bot_meuplano",
                         confirmacao="sim")
