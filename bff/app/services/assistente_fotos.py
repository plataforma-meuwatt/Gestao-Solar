"""Fotos e vídeos do WhatsApp anexados numa tarefa ou numa OS do meuPlano (pedido do Renan, 26/10/2026; vídeo e os
Anexos da OS em 06/11/2026: "Faça o bot aceitar vídeo para anexar nas tarefas e OS". O PDF de lá mostra a miniatura
do vídeo, que abre o vídeo no navegador).

A pessoa manda uma ou mais fotos (a legenda vale como texto). O álbum do WhatsApp chega como uma mensagem por foto, e o
bot responde uma vez só, na última (`e_a_ultima`). A IA chama `anexar_fotos` com a tarefa (ou a OS); o sistema confere a
situação da tarefa e o papel da pessoa e propõe "Anexar N foto(s) na tarefa #X", que ela confirma com Sim. Confirmada,
cada foto sai do gateway e entra na FICHA da tarefa (Fotos e anexos, a rota do app de campo), com o token DELA; tarefa
sem ficha recebe nos Anexos dela (`POST /tasks/{id}/attachments`).

Regra do dono: o técnico anexa só em tarefa EM ABERTO (prevista, planejada, programada, em andamento); o gestor da O&M
também na EM ANÁLISE (realizada, esperando a verificação) e na CONCLUÍDA (aprovada). Cancelada não recebe foto. Nos
Anexos da OS (`anexos_da_os`), a mesma régua com as situações da OS: aberta, programada e em execução; fechada e
aprovada só o gestor.
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
OS_ABERTA = {"ABERTA", "PROGRAMADA", "EM_EXECUCAO"}
OS_DO_GESTOR = {"FECHADA": "fechada", "APROVADA": "aprovada"}
#: A ficha que recebe anexo (a rota de lá recusa as outras com 409: emitida, aprovada, reprovada).
FICHA_RECEBE = {"IN_PROGRESS", "DRAFT"}


def _mime(evento: dict) -> str:
    return str((evento.get("midia") or {}).get("mime") or "")


def e_foto(evento: dict) -> bool:
    """Foto OU vídeo (o vídeo segue o mesmo caminho da foto: guardado, juntado ao álbum, anexado com o Sim)."""
    return evento.get("tipo") in ("image", "video") or (
        evento.get("tipo") == "document" and _mime(evento).startswith(("image/", "video/")))


def quantos(lista: list[dict]) -> str:
    """"3 foto(s)", "1 vídeo(s)", "2 foto(s) e 1 vídeo(s)"."""
    v = sum(1 for f in lista if f.get("video"))
    return " e ".join(p for p in (f"{len(lista) - v} foto(s)" if len(lista) > v else "",
                                  f"{v} vídeo(s)" if v else "") if p)


def recebidas(telefone: str, sem_video: bool = False) -> list[dict]:
    """`sem_video`: só as fotos (as Informações do relatório da OS levam imagem: a IA de lá lê a foto, não o vídeo)."""
    agora = monotonic()
    return [f for f in _RECEBIDAS.get(telefone, []) if agora - f["em"] < VALIDADE_S and not (sem_video and f.get("video"))]


def guardar(telefone: str, evento: dict) -> None:
    """Na CHEGADA, antes da fila do número: a foto anterior do álbum precisa saber que veio outra."""
    agora = monotonic()
    for velho in [t for t, fs in _RECEBIDAS.items() if not fs or agora - fs[-1]["em"] >= VALIDADE_S]:
        del _RECEBIDAS[velho]
    legenda = str((evento.get("midia") or {}).get("legenda") or "").strip()
    video = evento.get("tipo") == "video" or _mime(evento).startswith("video/")
    _RECEBIDAS[telefone] = [*recebidas(telefone),
                            {"id": evento.get("id"), "legenda": legenda, "em": agora, "video": video}][-TETO:]


async def e_a_ultima(telefone: str, mensagem_id: Any) -> bool:
    """Do álbum, só a última foto responde; as outras ficam guardadas, caladas."""
    for espera in (0, JUNTAR_S):
        await asyncio.sleep(espera)
        fotos = recebidas(telefone)
        if not fotos or fotos[-1]["id"] != mensagem_id:
            return False
    return True


def mensagem(telefone: str) -> str:
    """O que a IA lê no lugar da foto ou do vídeo (ela não vê nenhum dos dois)."""
    fotos = recebidas(telefone)
    legendas = "; ".join(dict.fromkeys(f["legenda"] for f in fotos if f["legenda"]))
    cabeca = (f"[📷 {quantos(fotos)} recebido(s), ainda não anexado(s)]" if any(f.get("video") for f in fotos)
              else f"[📷 {len(fotos)} foto(s) recebida(s), ainda não anexada(s)]")
    return cabeca + (f" {legendas}" if legendas else "")


def _tirar(telefone: str, mensagem_id: Any) -> None:
    _RECEBIDAS[telefone] = [f for f in _RECEBIDAS.get(telefone, []) if f["id"] != mensagem_id]


def recusa(user, status: str | None, na_os: bool = False) -> str | None:
    """Por que esta pessoa não anexa numa tarefa (ou na OS, `na_os`) nesta situação; `None` = pode."""
    aberta, do_gestor = (OS_ABERTA, OS_DO_GESTOR) if na_os else (ABERTA, DO_GESTOR)
    if status in aberta:
        return None
    if status in do_gestor:
        return None if user.perfil == Perfil.GESTOR_EMPRESA else (
            f"está {do_gestor[status]}: nela só o gestor da O&M anexa")
    return "está cancelada e não recebe anexo" if status == "CANCELADA" else f"está em {status} e não recebe anexo"


FERRAMENTA = {"type": "function", "function": {
    "name": "anexar_fotos",
    "description": ("Anexa as fotos e os vídeos que a pessoa mandou por aqui e ainda não foram anexados (a mensagem "
                    "dela aparece como «[📷 N foto(s)…]» ou «[📷 … vídeo(s)…]») na FICHA de uma tarefa do meuPlano "
                    "(Fotos e anexos) ou, quando ela pede NA OS e não numa tarefa, nos Anexos da OS (`anexos_da_os`). "
                    "Vira uma ação que ela confirma no botão Sim. Passe a tarefa (o número dela) ou, se a pessoa só "
                    "disse a OS, a OS. Se ela disse a usina e o serviço (\"a roçagem de Tietê\"), ache a tarefa com "
                    "`manutencao` e chame esta ferramenta NA MESMA mensagem, sem perguntar Sim/Não em texto. Sem saber "
                    "onde, pergunte em qual tarefa ou OS: não escolha por ela."),
    "parameters": {"type": "object", "properties": {
        "tarefa": {"type": "integer", "description": "número da tarefa"},
        "os": {"type": "integer", "description": "número da OS, quando a pessoa não disse a tarefa"},
        "anexos_da_os": {"type": "boolean", "description": ("true: nos Anexos da própria OS (não na ficha de uma "
                                                            "tarefa), quando a pessoa pediu na OS; precisa de `os`")}}}}}


async def anexar_fotos(ctx, a: dict) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuplano
    fotos = recebidas(ctx.telefone)
    if not fotos:
        return {"erro": "Não há foto nem vídeo recebido para anexar (cada um fica guardado 30 min). Peça que a pessoa "
                        "mande de novo."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    na_os = bool(a.get("anexos_da_os"))
    tarefa_id = a.get("tarefa")
    try:
        if na_os:
            if not a.get("os"):
                return {"erro": "Falta o número da OS: pergunte à pessoa em qual OS anexar."}
            alvo = await mp.ordem_servico(int(a["os"]))
        else:
            if not tarefa_id:
                if not a.get("os"):
                    return {"erro": "Falta a tarefa ou a OS: pergunte à pessoa onde anexar."}
                tarefas = await mp.tarefas_da_ordem(int(a["os"]))
                cabem = [t for t in tarefas if recusa(ctx.user, t.get("status")) is None]
                if len(cabem) != 1:
                    return {"erro": f"A OS {a['os']} tem {len(cabem)} tarefa(s) que podem receber anexo desta pessoa: "
                                    "pergunte em qual, ou se vai nos Anexos da própria OS (anexos_da_os).",
                            "tarefas": [{"tarefa": t.get("id"), "nome": t.get("name"), "situacao": t.get("status")}
                                        for t in tarefas]}
                tarefa_id = cabem[0]["id"]
            alvo = await mp.tarefa(int(tarefa_id))
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 404):
            return {"erro": f"A tarefa ou OS não foi encontrada no meuPlano para esta pessoa ({e.response.status_code})."}
        raise
    aid, n = int(alvo["id"]), len(fotos)
    nome_alvo = f"OS #{aid}" if na_os else f"tarefa #{aid}"
    if motivo := recusa(ctx.user, alvo.get("status"), na_os):
        return {"erro": f"A {nome_alvo} {motivo}. Nada foi anexado."}
    titulo = alvo.get("title") if na_os else alvo.get("name")
    resumo = (f"Anexar {quantos(fotos)} nos Anexos da OS #{aid}" + (f" «{titulo}»" if titulo else "") if na_os
              else f"Anexar {quantos(fotos)} na ficha da tarefa #{aid} «{titulo or 'sem nome'}»")
    lugar = " · ".join(x for x in ("" if na_os else f"OS {alvo['os_id']}" if alvo.get("os_id") else "",
                                   alvo.get("plant_name") or "") if x)
    so_fotos = not any(f.get("video") for f in fotos)
    nada = "Nenhuma foto foi anexada." if so_fotos else "Nada foi anexado."

    async def executar(db, user, telefone: str) -> str:
        from app.services.integracoes import detalhe_do_upstream
        try:
            mp = cliente_meuplano(db, user.id, so_proprio=True)
            db.commit()
            # pode ter mudado enquanto esperava o Sim
            situacao = (await (mp.ordem_servico(aid) if na_os else mp.tarefa(aid))).get("status")
        except SemConexao as e:
            return f"❌ Não executado: {e}"
        except httpx.HTTPError:
            return f"❌ Não consegui conferir a {nome_alvo} no meuPlano agora. {nada}"
        if motivo := recusa(user, situacao, na_os):
            return f"❌ A {nome_alvo} {motivo}. {nada}"
        # A foto de campo vai à FICHA (Fotos e anexos), onde a equipe a procura: nos Anexos da tarefa, que é outra
        # janela, ela parecia perdida (04/11/2026). Tarefa sem ficha (coletiva, sem equipamento) ou com a ficha
        # travada (emitida ao cliente) recebe nos Anexos, e o fim diz onde ficou.
        ficha = None
        if not na_os:
            try:
                ficha = await mp.abrir_ficha(aid, user.nome)
            except httpx.HTTPError:
                ficha = None
            if ficha is not None and ficha.get("session_status") not in FICHA_RECEBE:
                ficha = None
        onde = (f"nos Anexos da OS #{aid}" if na_os else f"na ficha da tarefa #{aid} (Fotos e anexos)"
                if ficha is not None else f"nos Anexos da tarefa #{aid}, não na ficha")
        feitas, falhas = [], []
        for i, f in enumerate(fotos, 1):
            qual = f"{'vídeo' if f.get('video') else 'foto'} {i}"
            try:
                conteudo, tipo = await whatsapp.baixar_midia(f["id"])
                tipo = tipo or ("video/mp4" if f.get("video") else "image/jpeg")
                nome = f"whatsapp-{i}.{tipo.split('/')[-1].split(';')[0]}"
                descricao = f["legenda"] or ("Vídeo enviado pelo WhatsApp" if f.get("video") else "Foto enviada pelo WhatsApp")
                if na_os:
                    await mp.anexar_na_os(aid, nome, conteudo, tipo, descricao)
                elif ficha is not None:
                    await mp.anexar_na_ficha(ficha, nome, conteudo, tipo, descricao, user.nome)
                else:
                    await mp.anexar_na_tarefa(aid, nome, conteudo, tipo, descricao, user.nome)
            except whatsapp.GatewayIndisponivel:
                falhas.append(f"{qual}: não consegui baixar do WhatsApp")
                continue
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500 and not feitas:
                    motivo = str(detalhe_do_upstream(e.response) or e.response.status_code).rstrip(". ")
                    return f"❌ O meuPlano recusou: {motivo}. {nada}"
                falhas.append(f"{qual}: o meuPlano deu erro {e.response.status_code}")
                continue
            except httpx.HTTPError:
                falhas.append(f"{qual}: o meuPlano não respondeu a tempo (pode ter entrado: confira)")
                continue
            feitas.append(f)
            _tirar(telefone, f["id"])
        motivos = "".join(f"\n• {m}" for m in falhas)
        if not feitas:
            return f"❌ {nada[:-1]} na {nome_alvo}:{motivos}"
        if falhas:
            return f"⚠️ Anexei {quantos(feitas)} de {n} {onde}:{motivos}"
        anexadas = "anexada(s)" if so_fotos else "anexado(s)"
        return f"✅ {quantos(feitas)} {anexadas} {onde}."

    from app.services.assistente import HISTORICO_MEUPLANO
    # `conversa`: depois do Sim, o resto do pedido ("…e lança ontem e hoje para o Thiago") segue no meuPlano
    return helper.propor(ctx, resumo, PRAZO_S, executar, [lugar] if lugar else [], parte="bot_meuplano",
                         confirmacao="sim",
                         conversa=[*ctx.historico[-HISTORICO_MEUPLANO:], {"role": "user", "content": ctx.pedido}])
