"""As câmeras e os alarmes das usinas pelo bot: o meuGuarda (CFTV), da família Gestão Solar (pedido do dono, 11/11/2026:
"integrar já, criar rotina de teste e ligar para todos"; especificação em `/root/DEVV/CFTV/docs/bot-gs.md`).

- Quem: a parte `bot_meuguarda` (oem-gs → Bot do WhatsApp, ligada para todos que já usavam o bot) e, LÁ, as permissões
  e as usinas da pessoa: o meuGuarda recusa com a frase dele (403/404/422), e ela vai à pessoa como veio.
- Identidade: a SESSÃO do GS da própria pessoa (gerente pelo portão da empresa, técnico pelo dele, dono de usina pelo
  do aplicativo). Nenhuma chave nova; o administrador da plataforma não usa o bot.
- Ler (estado, link de 15 min, foto de agora) volta na hora. Ligar ou desligar o alarme é AÇÃO: resumo do sistema e o
  Sim, como as do meuPlano; a parte é conferida de novo na hora (`helper._rodar`).
- O link abre a câmera ao vivo SEM login: vai ao pé da resposta pelo sistema (a IA não o escreve) e entra em
  `ctx.segredos`, que o tira do Log do bot e da cópia do gateway — quem lê o log não abre a câmera.
"""

import re
import unicodedata
from collections import Counter
from datetime import datetime

import httpx

from app.clients import whatsapp
from app.clients.meuguarda import MeuGuarda
from app.core.config import get_settings
from app.core.datas import hora_brt
from app.models.user import Perfil
from app.services import assistente_helper as helper
from app.services.integracoes import detalhe_do_upstream

PARTE = "bot_meuguarda"
PRAZO_S = 600
#: O portão de cada perfil no meuGuarda. Fora daqui (a plataforma), não há sessão: o administrador não usa o bot.
_PORTAO = {Perfil.GESTOR_EMPRESA: "empresa", Perfil.TECNICO: "tecnico", Perfil.CLIENTE: "cliente"}
#: O que a pessoa fala em volta do nome e não está nele ("a câmera do perímetro 3").
_ENCHIMENTO = {"camera", "cameras", "cam", "a", "o", "as", "os", "da", "de", "do", "das", "dos", "ufv", "usina"}


def disponivel(user) -> bool:
    return bool(get_settings().meuguarda_api_url) and user.perfil in _PORTAO


def cliente(user) -> MeuGuarda:
    """O meuGuarda falando como ESTA pessoa: uma sessão do GS dela, do portão do perfil dela."""
    from app.core.security import criar_token, criar_token_empresa, criar_token_tecnico

    portao = _PORTAO[user.perfil]
    emitir = {"empresa": criar_token_empresa, "tecnico": criar_token_tecnico, "cliente": criar_token}[portao]
    return MeuGuarda(get_settings().meuguarda_api_url, emitir(user.id)[0], portao)


def _recusa(e: httpx.HTTPError, nada_feito: bool = False) -> str:
    fim = " Nada foi feito." if nada_feito else ""
    if isinstance(e, httpx.HTTPStatusError):
        st, frase = e.response.status_code, detalhe_do_upstream(e.response)
        if st == 504:
            return "O PC da usina não respondeu a tempo (25 s). Tente de novo em instantes." + fim
        if st == 401:
            return "O meuGuarda não reconheceu a sessão desta pessoa agora." + fim
        if frase:
            return f"O meuGuarda recusou: {frase.rstrip('. ')}." + fim
        return f"O meuGuarda recusou ({st})." + fim
    return "O meuGuarda não respondeu agora." + fim


def _palavras(texto: str) -> list[str]:
    """O nome como se fala: sem acento, minúsculo, número sem o zero da frente ("Perímetro 03" → perimetro, 3)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return [str(int(p)) if p.isdigit() else p for p in re.findall(r"[a-z]+|\d+", t) if p not in _ENCHIMENTO]


def _bate(falado: str, nome: str) -> bool:
    return falado == nome or (falado.isalpha() and len(falado) >= 4 and nome.startswith(falado))


def escolher(itens: list[dict], termo: str) -> tuple[dict | None, list[dict]]:
    """Pelo nome falado, sem inventar: (o único que casa, ou None e os candidatos). Casa o nome exato e, senão, o que tem
    todas as palavras ditas ("perímetro 3" → "Perímetro 03"; "dome 1" → "Dome SKID 01"); "3" sozinho é ambíguo."""
    falado = _palavras(termo)
    if not falado:
        return None, []
    exatos = [i for i in itens if _palavras(i.get("nome")) == falado]
    if len(exatos) == 1:
        return exatos[0], exatos
    achados = [i for i in itens if all(any(_bate(f, n) for n in _palavras(i.get("nome"))) for f in falado)]
    return (achados[0], achados) if len(achados) == 1 else (None, exatos or achados)


def _nomes(itens: list[dict]) -> list[str]:
    return [i.get("nome") for i in itens]


def _usina(usinas: list[dict], termo: str | None) -> tuple[dict | None, dict | None]:
    """(a usina, ou None e o erro para a IA). Sem nome: a única que a pessoa vê."""
    if not usinas:
        return None, {"erro": "Nenhuma usina com câmeras está liberada para esta pessoa no meuGuarda."}
    if not (termo or "").strip():
        if len(usinas) == 1:
            return usinas[0], None
        return None, {"erro": "Falta a usina: pergunte qual.", "opcoes": _nomes(usinas)}
    u, candidatas = escolher(usinas, termo)
    if u is None:
        return None, {"erro": f"Usina '{termo}' " + ("é ambígua" if candidatas else "não tem câmeras liberadas para esta "
                      "pessoa no meuGuarda") + ": pergunte qual é.", "opcoes": _nomes(candidatas or usinas)}
    return u, None


async def _cameras(mg: MeuGuarda, usina: dict) -> list[dict]:
    return [c for c in await mg.cameras(int(usina["id"])) if c.get("tipo") == "camera"]


async def _camera(mg: MeuGuarda, termo_usina: str | None, termo: str) -> tuple[dict | None, dict | None, dict | None]:
    """(a usina, a câmera, ou o erro para a IA). Sem a usina, procura nas que a pessoa vê."""
    if not (termo or "").strip():
        return None, None, {"erro": "Falta a câmera: pergunte qual."}
    usinas = await mg.usinas()
    if (termo_usina or "").strip() or len(usinas) <= 1:
        usina, erro = _usina(usinas, termo_usina)
        if erro:
            return None, None, erro
        usinas = [usina]
    pares = [(u, c) for u in usinas for c in await _cameras(mg, u)]
    k, candidatas = escolher([{**c, "_usina": u} for u, c in pares], termo)
    if k is None:
        return None, None, {"erro": f"Câmera '{termo}' " + ("é ambígua" if candidatas else "não existe na lista") +
                            ": pergunte qual é (não invente).",
                            "opcoes": [f"{c['nome']} ({c['_usina']['nome']})" for c in candidatas]
                            or [f"{c['nome']} ({u['nome']})" for u, c in pares][:40]}
    return k.pop("_usina"), k, None


def _canal(a: dict, camera: dict) -> int:
    try:
        canal = int(a.get("canal") or 1)
    except (TypeError, ValueError):
        canal = 1
    return canal if 1 <= canal <= int(camera.get("canais") or 1) else 1


def _ate(valor) -> str | None:
    """"até 18:00" (ou "até 12/11 18:00"); None = já passou ou não há; "sem prazo" = o infinito de lá."""
    if not valor:
        return None
    try:
        ate = datetime.fromisoformat(str(valor))
    except ValueError:
        return "sem prazo"
    if ate.tzinfo is None or ate <= datetime.now(ate.tzinfo):
        return None
    return f"até {hora_brt(ate.isoformat())}"


def _desligada(c: dict) -> str | None:
    """"até 18:00 por Renan (roçagem)", ou None com o alarme ligado."""
    quando = _ate(c.get("deteccao_desligada_ate"))
    if quando is None:
        return None
    por = " ".join(x for x in (f"por {c['deteccao_por']}" if c.get("deteccao_por") else "",
                               f"({c['deteccao_motivo']})" if c.get("deteccao_motivo") else "") if x)
    return f"{quando} {por}".strip()


FERRAMENTA_ESTADO = {"type": "function", "function": {
    "name": "cameras",
    "description": ("As CÂMERAS de segurança (CFTV, meuGuarda) das usinas: quais estão online, se o alarme de cada uma "
                    "está ligado ou desligado (até quando, por quem e por quê) e os alarmes ABERTOS. Sem a usina, o "
                    "resumo de todas as que a pessoa vê."),
    "parameters": {"type": "object", "properties": {
        "usina": {"type": "string", "description": "nome da usina (opcional)"}}}}}


async def cameras(ctx, a: dict) -> dict:
    mg = cliente(ctx.user)
    ctx.db.commit()                                       # solta a conexão enquanto o meuGuarda responde
    try:
        usinas = await mg.usinas()
        if not (a.get("usina") or "").strip() and len(usinas) > 1:
            return {"usinas": [{"usina": u["nome"], "pc_da_usina_com_sinal": u.get("com_sinal"),
                                "cameras": u.get("cameras"), "online": u.get("cameras_online"),
                                "alarmes_abertos": u.get("alarmes_abertos")} for u in usinas]}
        usina, erro = _usina(usinas, a.get("usina"))
        if erro:
            return erro
        ks = await _cameras(mg, usina)
        try:
            abertos = [x for x in await mg.alarmes() if x.get("usina") == usina["nome"]]
        except httpx.HTTPStatusError as e:
            abertos = None if e.response.status_code == 403 else []
    except httpx.HTTPError as e:
        return {"erro": _recusa(e)}
    return {
        "usina": usina["nome"], "pc_da_usina_com_sinal": usina.get("com_sinal"),
        "cameras": [{"camera": c["nome"], "online": c.get("online"),
                     "alarme": "desligado " + d if (d := _desligada(c)) else "ligado",
                     "alarmes_abertos": c.get("alarmes_abertos"), "disponibilidade_24h_pct": c.get("disponibilidade_24h"),
                     "ultimo_evento": hora_brt(c["ultimo_evento"]) if c.get("ultimo_evento") else None} for c in ks],
        "alarmes_abertos": "o papel desta pessoa no meuGuarda não vê alarmes" if abertos is None else {
            "total": len(abertos), "por_tipo": dict(Counter(x.get("tipo") for x in abertos).most_common()),
            "mais_recentes": [{"camera": x.get("camera"), "tipo": x.get("tipo"), "prioridade": x.get("prioridade"),
                               "aberto_em": hora_brt(x.get("aberto_em"))}
                              for x in sorted(abertos, key=lambda x: x.get("aberto_em") or "", reverse=True)[:10]]},
    }


_PARAMS_CAMERA = {"type": "object", "properties": {
    "camera": {"type": "string", "description": "o nome da câmera como a pessoa disse (ex.: Perímetro 03, Térmica 02)"},
    "usina": {"type": "string", "description": "nome da usina (opcional)"},
    "canal": {"type": "integer", "description": "câmera térmica (bi-espectral) tem 2 canais; sem dizer, 1"}},
    "required": ["camera"]}

FERRAMENTA_VER = {"type": "function", "function": {
    "name": "ver_camera",
    "description": ("VER uma câmera de segurança AO VIVO (meuGuarda): o SISTEMA manda à pessoa, ao pé da sua resposta, "
                    "um link pessoal que abre a câmera sem login e vale 15 min. Não escreva o link."),
    "parameters": _PARAMS_CAMERA}}


async def ver_camera(ctx, a: dict) -> dict:
    mg = cliente(ctx.user)
    ctx.db.commit()
    try:
        usina, k, erro = await _camera(mg, a.get("usina"), a.get("camera"))
        if erro:
            return erro
        r = await mg.link(int(k["id"]), _canal(a, k))
    except httpx.HTTPError as e:
        return {"erro": _recusa(e)}
    ctx.segredos.append(r["url"])                         # quem lê o log não abre a câmera
    ctx.rodape.append(f"🎥 {k['nome']} ({usina['nome']}) ao vivo, só para você, até {hora_brt(r.get('expira_em'))}:\n"
                      f"{r['url']}")
    return {"camera": k["nome"], "usina": usina["nome"], "link_enviado_pelo_sistema": True,
            "vale_ate": hora_brt(r.get("expira_em")), "instrucao": "Diga uma linha; o link já vai ao pé da resposta."}


FERRAMENTA_FOTO = {"type": "function", "function": {
    "name": "foto_camera",
    "description": ("A FOTO DE AGORA de uma câmera de segurança (meuGuarda): a câmera tira na hora e a foto chega no "
                    "chat em segundos."),
    "parameters": _PARAMS_CAMERA}}


async def foto_camera(ctx, a: dict) -> dict:
    mg = cliente(ctx.user)
    ctx.db.commit()
    try:
        usina, k, erro = await _camera(mg, a.get("usina"), a.get("camera"))
        if erro:
            return erro
        jpeg, _fonte = await mg.foto(int(k["id"]), _canal(a, k))
    except httpx.HTTPError as e:
        return {"erro": _recusa(e)}
    titulo = f"📷 {k['nome']} · {usina['nome']} · {hora_brt(datetime.now().astimezone().isoformat())}"
    r = await whatsapp.enviar_conteudo(telefone=ctx.telefone, tipo="image", arquivo=jpeg, filename="camera.jpg",
                                       mime="image/jpeg", texto=titulo)
    ok = bool(r and r.get("ok"))
    if ok:
        ctx.enviados.append(titulo)
    return {"foto": titulo, "enviado_no_chat": ok, **({} if ok else {"erro": "o WhatsApp recusou a foto"})}


FERRAMENTA_ALARME = {"type": "function", "function": {
    "name": "alarme_cameras",
    "description": ("LIGAR ou DESLIGAR o alarme (a detecção) de câmeras de segurança (meuGuarda): é AÇÃO, o sistema "
                    "mostra o resumo e a pessoa confirma com Sim. Para desligar, o MOTIVO é obrigatório (fica no "
                    "histórico de cada câmera): se a pessoa não disse, pergunte antes de chamar. Sem prazo, o alarme "
                    "volta sozinho no horário de religar da usina."),
    "parameters": {"type": "object", "properties": {
        "ligar": {"type": "boolean", "description": "true = ligar de novo; false = desligar"},
        "cameras": {"type": "array", "items": {"type": "string"},
                    "description": "os nomes como a pessoa disse; vazio ou [\"todas\"] = todas as câmeras da usina"},
        "usina": {"type": "string", "description": "nome da usina (opcional)"},
        "horas": {"type": "number", "description": "por quanto tempo desligar (opcional)"},
        "motivo": {"type": "string", "description": "por que desligar, nas palavras da pessoa"}},
        "required": ["ligar", "cameras"]}}}


async def alarme_cameras(ctx, a: dict) -> dict:
    ligar = bool(a.get("ligar"))
    motivo = (a.get("motivo") or "").strip()
    if not ligar and len(motivo) < 5:
        return {"erro": "Falta o motivo para desligar o alarme (fica no histórico de cada câmera): pergunte. Nada foi "
                        "feito."}
    minutos = None
    if not ligar and a.get("horas") not in (None, ""):
        try:
            minutos = round(float(a["horas"]) * 60)
        except (TypeError, ValueError):
            return {"erro": "Não entendi por quanto tempo: pergunte em horas."}
        if not 5 <= minutos <= 30 * 24 * 60:
            return {"erro": "O prazo vai de 5 minutos a 30 dias: pergunte de novo."}
    mg = cliente(ctx.user)
    ctx.db.commit()
    try:
        if "alarmes.tratar" not in ((await mg.eu()).get("permissoes") or []):
            return {"erro": "O papel desta pessoa no meuGuarda não liga nem desliga alarme. Nada foi feito: quem "
                            "administra o meuGuarda da empresa pode liberar."}
        usina, erro = _usina(await mg.usinas(), a.get("usina"))
        if erro:
            return erro
        ks = await _cameras(mg, usina)
    except httpx.HTTPError as e:
        return {"erro": _recusa(e, nada_feito=True)}
    pedidas = [n for n in a.get("cameras") or [] if (n or "").strip() and _palavras(n) not in (["todas"], ["tudo"])]
    escolhidas = []
    for n in pedidas:
        k, candidatas = escolher(ks, n)
        if k is None:
            return {"erro": f"Câmera '{n}' " + ("é ambígua" if candidatas else f"não existe em {usina['nome']}") +
                            ": pergunte qual é (não invente). Nada foi feito.",
                    "opcoes": _nomes(candidatas or ks)}
        if k not in escolhidas:
            escolhidas.append(k)
    escolhidas = escolhidas or ks
    if not escolhidas:
        return {"erro": f"{usina['nome']} não tem câmera cadastrada no meuGuarda."}
    n = len(escolhidas)
    alvo = f"{n} câmera{'s' if n > 1 else ''} de {usina['nome']}"
    quando = (f"por {minutos // 60} h" + (f" {minutos % 60} min" if minutos % 60 else "") if minutos and minutos >= 60
              else f"por {minutos} min" if minutos else "até o horário de religar da usina")
    resumo = f"Ligar de novo o alarme de {alvo}" if ligar else f"Desligar o alarme de {alvo}, {quando}"
    detalhes = [", ".join(_nomes(escolhidas))] + ([] if ligar else [f"Motivo: {motivo}"])
    ids, uid = [int(k["id"]) for k in escolhidas], int(usina["id"])

    async def executar(db, user, telefone: str) -> str:
        try:
            r = await cliente(user).deteccao(uid, ligar, ids, minutos, None if ligar else motivo)
        except httpx.TimeoutException:
            return f"⚠️ O meuGuarda não respondeu a tempo: o alarme de {alvo} PODE ter mudado. Confira no meuGuarda."
        except httpx.HTTPError as e:
            return f"❌ {_recusa(e, nada_feito=True)}"
        if ligar:
            return f"✅ Alarme de {alvo} ligado de novo."
        return f"✅ Alarme de {alvo} desligado {_ate(r.get('desligada_ate')) or 'sem prazo'}. Motivo: {motivo}."

    return helper.propor(ctx, resumo, PRAZO_S, executar, detalhes, parte=PARTE, confirmacao="sim")


FERRAMENTAS = {
    "cameras": (cameras, FERRAMENTA_ESTADO),
    "ver_camera": (ver_camera, FERRAMENTA_VER),
    "foto_camera": (foto_camera, FERRAMENTA_FOTO),
    "alarme_cameras": (alarme_cameras, FERRAMENTA_ALARME),
}
