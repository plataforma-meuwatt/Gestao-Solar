"""O DIAGNÓSTICO de uma usina: cruza o que parou (as paradas do detector do meuWatt e os inversores que não ligaram)
com os trips dos relés de proteção do skid e com a `matriz`, e diz a causa provável e o que fazer.

Pedido do dono (13/11/2026): Pirapozinho teve 47 às 22:48 e 27 nas três fases às 03:17 nos relés dos Skids 1 e 2; os
oito inversores deles não ligaram de manhã, e o aviso que saiu (07:28) dizia só "parado", sem a causa. "O bot deveria
enviar a mensagem … pesquisar o motivo … uma varredura de rotina … uma matriz". Este módulo é a leitura e a regra; quem
manda é a varredura (`varredura.py`) e quem explica é o bot (`diagnostico_usina`).

As regras, em ordem:
0. Parada é o que a MATRIZ do meuWatt diz que é parada (o dono, 23/11/2026: "Não foi parada, só vamos mostrar no whats
   o que for realmente parada. Já temos uma matriz"). Tietê 23/11 16:41: os 10 inversores a zero com tensão nos relés,
   sem trip e sem falha do inversor, R9 "nuvem ou fim de tarde" no meuWatt, e saíram três avisos de parada. Cada
   parada do detector (o grupo, ou a linha solta) passa pela verificação de lá (`/shadow-breakdowns/verification`);
   só `kind` = "parada" segue nas regras 1 e 2. Avaliar, comunicação e não-parada ficam na tela de Paradas do
   meuWatt (e o bot diz o veredito se perguntarem). Sem resposta da verificação, a parada segue como antes, dizendo
   que não foi conferida: "não consegui conferir" não é "não é parada".
1. Parada (ou inversor sem ligar) num skid + trip no relé DAQUELE skid até 12 h antes = a função do trip é a causa (a
   última antes da parada; as de antes entram como contexto: a 47 que precede a 27). Vários relés com a mesma função no
   mesmo minuto = a REDE, não a usina.
2. Parada sem trip à vista = "não ligou" ou a causa do detector, com os alarmes do inversor. Falha de comunicação sem
   trip não é parada (faltou o dado, não a energia) e não vira achado. A causa segue o livro do bot
   (`docs/LIVRO_DO_BOT.md`, lição 1, o dono em 24/11/2026: "Dois DJ BT diferentes desligados juntos logo de manhã …
   é praticamente impossível. Se não ver trip, mas também não tiver comunicação, é bem provável que seja trip"): relé
   mudo, histórico de trips que não veio ou skid sem relé = "o trip não aparece", nunca "sem trip"; o skid inteiro
   parado sem como ver trip = provável trip; dois ou mais skids inteiros juntos = uma causa comum e um aviso só, nunca
   o DJ BT de cada um; os outros inversores do skid gerando = havia tensão, não é trip nem DJ BT (Pereiras 24/11: oito
   inversores ligaram às 05:20, quatro entre 06:35 e 06:50, e o aviso culpou o DJ BT dos dois skids).
3. Trip que disparou e não limpou = skid DESARMADO agora (antes de qualquer parada: de madrugada já se sabe que o skid
   não vai ligar). Com o PRÓPRIO relé medindo energia passando (leitura válida acima de `FLUXO_KW`), o disjuntor está
   fechado: a bandeira não desarmou nada e não vira achado (Pereiras 23/11 14:48: 27 "disparado" até 16:01 com os
   inversores do skid gerando; disjuntor aberto lê zero, fechado lê de 0 a 30 kW mesmo à noite).
4. Relé sem comunicação (estado desconhecido) e 5. fase zerada na medição com o skid gerando (fusível do TP): quem
   diz é a tela Leituras do meuWatt (`GET /plants/{slug}/readings`, a regra de lá: 15 min sem leitura válida E duas
   voltas do coletor sem medida dele, porque o `comm` sozinho fica falso numa leitura vazia de um minuto, Tietê 13/11,
   e o tempo sozinho dava alarme falso de madrugada, quando o coletor espaça as leituras; uma fase abaixo de 10% das
   outras nas duas últimas leituras).
   O X de lá ("já sei", o dono em 14/11: o relé do Skid 3 de Pirapozinho está com defeito e não lê a fase A) faz o
   achado sair `conhecido`: a varredura não avisa, o bot diz que é sabido e o que anotaram.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.datas import hoje, hora_brt
from app.services import matriz

logger = logging.getLogger(__name__)

#: Quanto antes da parada um trip ainda explica a parada (o 27 das 03:17 explica o "não ligou" das 05:46).
JANELA_TRIP = timedelta(hours=12)
#: Trips da mesma função em relés diferentes dentro disto = o mesmo evento da rede.
MESMO_EVENTO = timedelta(minutes=5)
#: Paradas sem trip em skids diferentes que começam dentro disto = o mesmo evento, um aviso (lição 1 do livro do bot).
JUNTOS = timedelta(minutes=15)
_ORDEM = {"critica": 0, "alta": 1, "media": 2, "info": 3}
#: O relé do skid medindo mais que isto (leitura válida da tela Leituras) = o disjuntor está fechado.
FLUXO_KW = 1.0
#: Verificações de uma vez no meuWatt (cada uma faz várias consultas no banco de lá, 2–5 s).
VERIFICACOES_JUNTAS = 3
#: O veredito de uma parada ENCERRADA não muda: guardado, a varredura de 10 em 10 min não refaz a conta. A aberta é
#: conferida a cada volta (a duração entra no veredito).
_VEREDITOS: dict[tuple, dict] = {}
KINDS = ("parada", "avaliar", "comunicacao", "nao_parada")


@dataclass
class Achado:
    codigo: str
    titulo: str
    gravidade: str
    usina: str
    skids: list[str]
    #: O começo do problema (a parada, ou o trip ativo), para a chave e para a mensagem.
    desde: datetime | None
    resolvido_em: datetime | None = None
    causa: str = ""
    evidencias: list[str] = field(default_factory=list)
    fazer: list[str] = field(default_factory=list)
    religar_remoto: bool = False
    #: O slug do meuWatt (a chave usa ele: o nome da usina pode mudar e passar do tamanho da trava).
    slug: str = ""
    #: O X da tela Leituras do meuWatt ("já sei"): a nota e quem marcou. Achado conhecido não vai na varredura.
    conhecido: str | None = None
    #: O que separa dois achados do mesmo código no mesmo skid (a fase zerada: a A e, depois, a B avisam cada uma).
    parte: str = ""

    @property
    def chave(self) -> str:
        """Estável por problema: a mesma queda avisa uma vez (a volta não reavisa)."""
        # O estado sem começo (relé sem comunicação, fase zerada) avisa uma vez POR DIA enquanto durar.
        quando = f"{self.desde:%Y-%m-%dT%H:%M}" if self.desde else hoje().isoformat()
        k = f"diag:{self.slug or self.usina}:{self.codigo}{':' + self.parte if self.parte else ''}:{'+'.join(sorted(self.skids))}:{quando}"
        return k if len(k) <= 120 else k[:100] + ":" + hashlib.sha1(k.encode()).hexdigest()[:19]   # a trava tem 120

    def texto(self) -> str:
        """A mensagem curta (WhatsApp e push): o problema, a causa, a prova e o que fazer."""
        sk = " e ".join(self.skids)
        estado = f" (voltou às {hora_brt(self.resolvido_em.isoformat())})" if self.resolvido_em else ""
        linhas = [f"⚠️ *{self.usina}{' · ' + sk if sk else ''}*: {self.titulo}{estado}"]
        if self.causa:
            linhas.append(f"Causa provável: {self.causa}")
        linhas += [f"• {e}" for e in self.evidencias]
        if self.fazer:
            linhas.append("O que fazer: " + " ".join(f"{i}) {f}" for i, f in enumerate(self.fazer, 1)))
        if self.conhecido:
            linhas.append(f"Já sabido (marcado no meuWatt): {self.conhecido}")
        return "\n".join(linhas)

    def push(self) -> tuple[str, str]:
        """Título e corpo do aviso no celular: o problema e a causa; o resto está no WhatsApp e no bot."""
        sk = " e ".join(self.skids)
        corpo = self.causa.rstrip(".") + "." + (f" Fazer: {self.fazer[0]}" if self.fazer else "")
        return f"{self.usina}{' · ' + sk if sk else ''}: {self.titulo}", corpo.strip()

    def para_ia(self) -> dict:
        return {"codigo": self.codigo, "titulo": self.titulo, "gravidade": self.gravidade, "skids": self.skids,
                "desde": hora_brt(self.desde.isoformat()) if self.desde else None,
                "voltou": hora_brt(self.resolvido_em.isoformat()) if self.resolvido_em else None,
                "causa": self.causa, "evidencias": self.evidencias, "fazer": self.fazer,
                "religar_de_longe": self.religar_remoto, "ja_sabido": self.conhecido}


def _quando(iso: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else None
    except ValueError:
        return None
    return t if t is None or t.tzinfo else t.replace(tzinfo=UTC)


def _n(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


def _h(t: datetime) -> str:
    return hora_brt(t.isoformat())


def _eventos(bruto: Any) -> list[dict]:
    itens = bruto.get("events") if isinstance(bruto, dict) else bruto
    saida = []
    for e in itens if isinstance(itens, list) else []:
        t = _quando(e.get("timestamp"))
        if t is not None and e.get("trip_code"):
            saida.append({"quando": t, "funcao": str(e["trip_code"]),
                          "disparou": e.get("event") == "TRIPPED", "item": matriz.do_codigo(str(e["trip_code"]))})
    return sorted(saida, key=lambda e: e["quando"])


def _ativos(eventos: list[dict]) -> list[dict]:
    """As funções cujo ÚLTIMO evento é disparou: o skid está desarmado por elas agora."""
    ultimo: dict[str, dict] = {}
    for e in eventos:
        ultimo[e["funcao"]] = e
    return [e for e in ultimo.values() if e["disparou"]]


def _sabido(linha: dict, pode: bool = True) -> str | None:
    """O X da leitura no meuWatt, em uma frase: a nota e quem marcou; None = ninguém marcou "já sei". `pode` = o
    `can_mark` da resposta: para quem não opera a usina, o meuWatt manda a nota e o autor vazios, e aí não se sabe se
    há observação."""
    m = linha.get("mark") or {}
    if not m.get("ignored"):
        return None
    if not pode and not m.get("note"):
        return "a equipe marcou que já sabe (a observação só aparece para quem opera a usina)"
    quem = ", ".join(x for x in (m.get("user_name"), hora_brt(m["created_at"]) if m.get("created_at") else None) if x)
    return (m.get("note") or "sem observação") + (f" ({quem})" if quem else "")


#: Acima disto o skid está gerando: à noite o relé mede ruído de 10 a 12 kW, e com o corte em 10 kW a "fase zerada com o
#: skid gerando" saía entre 00h e 02h30 (Pirapozinho, 15 a 18/11/2026).
GERANDO_KW = 50

#: O snapshot do relé passou disto: o valor dele não é "de agora" (o STALE_SNAPSHOT_THRESHOLD do meuWatt).
RESERVA_FRESCO = timedelta(minutes=10)


def _unidade(p: dict) -> tuple | None:
    """A parada que a matriz julga: o grupo do detector ou a linha solta. `None` = sem como perguntar."""
    if p.get("plant_id") is None:
        return None
    if p.get("group_id") is not None:
        return (int(p["plant_id"]), "g", int(p["group_id"]))
    return (int(p["plant_id"]), "r", int(p["id"])) if p.get("id") is not None else None


async def _vereditos(mw, paradas: list[dict]) -> dict[tuple, dict | None]:
    """{unidade: {row, result, kind} da matriz do meuWatt, ou `None` quando a verificação não respondeu}."""
    unidades: dict[tuple, list[dict]] = {}
    for p in paradas:
        if (u := _unidade(p)) is not None:
            unidades.setdefault(u, []).append(p)
    vagas = asyncio.Semaphore(VERIFICACOES_JUNTAS)

    async def um(u: tuple, linhas: list[dict]) -> dict | None:
        encerrada = all(p.get("resolved_at") for p in linhas)
        assinatura = tuple(sorted((str(p.get("id")), str(p.get("resolved_at"))) for p in linhas))
        guardado = _VEREDITOS.get(u)
        if encerrada and guardado and guardado["assinatura"] == assinatura:
            return guardado["veredito"]
        try:
            async with vagas:
                v = await mw.verificacao_da_parada(u[0], **({"grupo": u[2]} if u[1] == "g" else {"linha": u[2]}))
        except Exception as e:                             # noqa: BLE001 — sem o veredito, segue como antes
            logger.warning("diagnostico: a verificação do meuWatt falhou em %s (%s)", u, type(e).__name__)
            return None
        veredito = {k: v.get(k) for k in ("row", "result", "kind")}
        if veredito["kind"] not in KINDS:                  # a forma mudou lá: não cala parada nenhuma
            logger.warning("diagnostico: veredito sem kind conhecido em %s: %r", u, veredito["kind"])
            return None
        if encerrada:
            if len(_VEREDITOS) > 5000:                     # ponytail: zera tudo de vez; um dia da frota cabe com folga
                _VEREDITOS.clear()
            _VEREDITOS[u] = {"assinatura": assinatura, "veredito": veredito}
        return veredito

    pares = list(unidades.items())
    return dict(zip([u for u, _ in pares], await asyncio.gather(*(um(u, ls) for u, ls in pares))))


def _verificacao(ps: list[dict], vereditos: dict[tuple, dict | None]) -> str:
    """A linha de prova que diz o veredito da matriz (ou que não deu para conferir)."""
    vs = [vereditos.get(_unidade(p)) for p in ps]
    if any(v is None for v in vs):
        return "Verificação do meuWatt indisponível agora: avisado sem conferir se foi nuvem ou falha de leitura."
    ditos = sorted({f"{v['result']} (linha {v['row']} do mapa)" for v in vs})
    return "Verificação do meuWatt: " + "; ".join(ditos) + "."


def _da_reserva(r: dict, evidencia_ok: bool, agora: datetime) -> dict:
    """Um relé do /monitoring/current no formato da tela Leituras, só quando ela não responde. A reserva NÃO julga relé
    mudo nem fase zerada (sem a tela não há o «já sei» de lá, e o aviso que alguém já marcou sairia de novo): a
    comunicação fica "não conferida" (menos quando o monitoramento leu agora) e os trips seguem pela matriz. Valor de
    snapshot com mais de RESERVA_FRESCO sai nulo (o monitoramento manda o último, de até dias atrás)."""
    hora = _quando(r.get("timestamp"))
    fresco = hora is not None and agora - hora <= RESERVA_FRESCO
    val = (lambda k: r.get(k) if fresco else None)
    comm = "ok" if r.get("comm") is True and evidencia_ok else "unknown"
    leituras = [{"key": "comm", "status": comm}]
    leituras += [{"key": k, "status": "ok", "value": val(k)}
                 for k in ("total_active_power", *(f"{g}_{f}" for g in ("voltage", "current") for f in "abc"))]
    return {"relay_id": r["relay_db_id"], "name": r.get("name"), "transformer_name": r.get("transformer_name"),
            "last_read_at": r.get("last_read_at"), "readings": leituras}


def _da_rede(funcao_item: matriz.Item, quando: datetime, todos: dict[str, list[dict]]) -> list[str]:
    """Os relés que dispararam a MESMA função no mesmo minuto: dois ou mais = evento da rede."""
    return sorted(nome for nome, evs in todos.items()
                  if any(e["disparou"] and e["item"] is funcao_item and abs(e["quando"] - quando) <= MESMO_EVENTO
                         for e in evs))


def _nome_rele(r: dict) -> str:
    nome = str(r.get("name") or "")
    return nome if nome.lower().startswith("rel") else f"relé {nome}"


def _cegueira(r: dict, hist: list | None) -> str | None:
    """Por que este relé não deixa dizer "sem trip" (`None` = ele lê agora e o histórico de trips veio)."""
    comm = next((x for x in r.get("readings") or [] if x.get("key") == "comm"), {})
    if comm.get("status") == "ok":
        return None if hist is not None else f"o histórico de trips do {_nome_rele(r)} não veio"
    if comm.get("status") != "no_comm":
        return f"{_nome_rele(r)} com a comunicação não conferida agora"
    ultima = _quando(comm.get("last_valid_at") or r.get("last_read_at"))
    return f"{_nome_rele(r)} sem comunicação " + (f"desde {_h(ultima)}" if ultima else "nas últimas 48 h")


def _inicio(ps: list[dict]) -> datetime:
    return min(t for p in ps if (t := _quando(p.get("stopped_at"))))


def _juntos(sem_trip: list[tuple[str, list[dict]]]) -> list[list[tuple[str, list[dict]]]]:
    """Os skids sem trip à vista que começaram a parar até JUNTOS um do outro: o mesmo evento."""
    grupos: list[list[tuple[str, list[dict]]]] = []
    for par in sorted(sem_trip, key=lambda par: _inicio(par[1])):
        if grupos and _inicio(par[1]) - _inicio(grupos[-1][0][1]) <= JUNTOS:
            grupos[-1].append(par)
        else:
            grupos.append([par])
    return grupos


def _sem_trip(usina: str, juntos: list[tuple[str, list[dict]]], cegos: dict[str, list[str]],
              vereditos: dict[tuple, dict | None]) -> Achado:
    """A regra 2 pelo livro do bot (lição 1): o que parou sem trip à vista, num skid ou em vários juntos."""
    item, mudo = matriz.MATRIZ["NAO_LIGOU"], matriz.MATRIZ["RELE_SEM_COMUNICACAO"]
    ps = [p for _, rs in juntos for p in rs]
    resolvidas = [_quando(p.get("resolved_at")) for p in ps]
    nao_ligou = any(p.get("cause") == "never_woke_up" for p in ps)
    provas, inteiros, parciais = [], [], []
    for skid, rs in juntos:
        ini, fins = _inicio(rs), [_quando(p.get("resolved_at")) for p in rs]
        nomes = sorted({str(p.get("slot_label")) for p in rs}, key=lambda n: (len(n), n))
        frota = next((p["inversores_no_skid"] for p in rs if p.get("inversores_no_skid")), None)
        de_uma_vez = {str(p.get("slot_label")) for p in rs if (_quando(p.get("stopped_at")) or ini) - ini <= JUNTOS}
        if frota:
            (inteiros if len(de_uma_vez) >= frota else parciais).append(skid)
        perda = sum(p.get("shadow_loss_kwh") or 0 for p in rs)
        provas.append(f"{skid}: {len(nomes)}{f' de {frota}' if frota else ''} inversor(es) ({', '.join(nomes)}) "
                      f"parado(s) desde {_h(ini)}" + (f" até {_h(max(fins))}" if all(fins) else "")
                      + (f", {perda:.0f} kWh perdidos" if perda else "") + ".")
    skids = [s for s, _ in juntos]
    provas += [f"{c[0].upper()}{c[1:]}: o trip não aparece." for s in skids for c in cegos.get(s, [])]
    cego, livro = any(s in cegos for s in skids), "lição 1 do livro do bot"
    alarmes, minusc = "Conferir os alarmes dos inversores e o teste de comunicação.", lambda t: t[:1].lower() + t[1:]
    if len(inteiros) >= 2:
        causa = (f"{len(inteiros)} skids inteiros pararam juntos, e dois DJ BT não desligam juntos ({livro}): "
                 + ("sem trip à vista e sem comunicação, o provável é trip que o relé mudo não mostra" if cego else
                    "a causa é comum aos skids (a rede ou a proteção geral), e os relés deles leem sem trip"))
        fazer = [mudo.fazer[0], item.fazer[0]] if cego else [item.fazer[1]]
    elif inteiros and cego:
        causa = f"o skid inteiro parou e não há como ver trip: o provável é trip ({livro})"
        fazer = [mudo.fazer[0], item.fazer[0]]
    elif inteiros:
        causa = "o skid inteiro parou sem trip no relé dele, que está lendo: " + minusc(item.causas[1])
        fazer = list(item.fazer)
    elif parciais and len(parciais) == len(skids):
        outros = "dos skids" if len(skids) > 1 else "do skid"
        causa = (f"os outros inversores {outros} geravam, então havia tensão: não é trip nem DJ BT ({livro}). "
                 + (f"O mais comum: {minusc(item.causas[2])}" if nao_ligou else "É o inversor."))
        fazer = [alarmes] + ([item.fazer[2]] if nao_ligou else [])
    else:                                                  # sem a frota do skid: não separa o skid do inversor
        causa = "não há como ver trip (o porquê vem abaixo)" if cego else "sem trip no relé do skid"
        fazer = list(item.fazer) if nao_ligou else [alarmes]
    return Achado("NAO_LIGOU" if nao_ligou else f"PARADA:{ps[0].get('cause')}",
                  _titulo_sem_trip(ps, inteiros, parciais, nao_ligou), "alta", usina, skids, _inicio(ps),
                  max(resolvidas) if all(resolvidas) else None, causa, provas + [_verificacao(ps, vereditos)], fazer)


def _titulo_sem_trip(ps: list[dict], inteiros: list[str], parciais: list[str], nao_ligou: bool) -> str:
    """O título diz QUEM parou: "Inv 42 parado" não é "inversores parados" (o Renan, 25/11/2026, Porto Ferreira: o
    aviso "SKID-04: inversores parados" com um inversor de quatro parado, e o unifilar com os outros três gerando)."""
    nomes = sorted({str(p.get("slot_label")) for p in ps}, key=lambda n: (len(n), n))
    verbo = ("não ligou", "não ligaram") if nao_ligou else ("parado", "parados")
    if inteiros and not parciais:
        return f"skid inteiro {verbo[0]}" if len(inteiros) == 1 else f"skids inteiros {verbo[1]}"
    if len(nomes) == 1:
        return f"{nomes[0]} {verbo[0]}" + (" (os outros do skid geram)" if parciais else "")
    lista = ", ".join(nomes[:-1]) + " e " + nomes[-1]
    return f"{lista} {verbo[1]}" + (" (os outros do skid geram)" if parciais and not inteiros else "")


async def diagnosticar(mw, usina: dict, paradas: list[dict], agora: datetime | None = None,
                       info: dict | None = None) -> list[Achado]:
    """Os achados da usina AGORA. `usina`: {slug, nome}; `paradas`: as linhas do detector de hoje
    (`paradas.ler_do_detector`), para casar inversor e skid. `info` recebe `leituras`: "meuwatt" (a tela Leituras) ou
    "reserva" (ela não respondeu: a regra de antes, sem o «já sei»)."""
    agora = agora or datetime.now(UTC)
    # Os relés de proteção com cada leitura julgada pelo meuWatt (a tela Leituras) e o X de quem opera. Sem ela (o
    # meuWatt fora, ou a rota ainda não publicada), a reserva: a lista do monitoramento só para os trips e o skid
    # desarmado; relé mudo e fase zerada ficam "não conferidos" (quem chama recebe a lista e diz isso).
    try:
        lido = await mw.leituras(usina["slug"])
        protecao, pode, fonte = lido.get("relays") or [], bool(lido.get("can_mark")), "meuwatt"
    except Exception as e:                                 # noqa: BLE001
        logger.warning("diagnostico: a tela Leituras do meuWatt falhou em %s (%s); usando a reserva",
                       usina["slug"], type(e).__name__)
        m = await mw.monitoramento_atual(usina["slug"])
        evidencia = m.get("read_evidence") != "unavailable"
        protecao = [_da_reserva(r, evidencia, agora) for r in m.get("relays") or [] if r.get("relay_db_id") is not None
                    and not r.get("is_temperature_relay") and not str(r.get("model") or "").startswith("abs")]
        fonte, pode = "reserva", True
    if info is not None:
        info["leituras"] = fonte

    async def evs(r):
        try:
            return _eventos(await mw.eventos_de_trip(usina["slug"], int(r["relay_id"]), 50))
        except Exception:                                  # noqa: BLE001 — sem o histórico, as outras regras seguem
            return None                                    # não lido não é "sem trip" (lição 1 do livro do bot)

    historicos = await asyncio.gather(*(evs(r) for r in protecao))
    # O relé que não deixa dizer "sem trip" no skid dele: mudo, não conferido ou com o histórico que não veio.
    cegos: dict[str, list[str]] = {}
    for r, h in zip(protecao, historicos):
        if r.get("transformer_name") and (motivo := _cegueira(r, h)):
            cegos.setdefault(r["transformer_name"], []).append(motivo)
    historicos = [h or [] for h in historicos]
    por_rele = {r.get("name") or str(r.get("relay_id")): h for r, h in zip(protecao, historicos)}
    # Os trips de TODOS os relés do skid (o geral pode ter o mesmo transformador: um não apaga o outro).
    do_skid: dict[str, list[dict]] = {}
    for r, h in zip(protecao, historicos):
        if r.get("transformer_name"):
            do_skid.setdefault(r["transformer_name"], []).extend(h)
    achados: list[Achado] = []

    # ── regra 0: a matriz do meuWatt diz o que é parada ────────────────────────────────────────────────────────
    materiais = [p for p in paradas if p.get("materiality") in (None, "material")]
    vereditos = await _vereditos(mw, materiais)
    grupos: dict[str, list[dict]] = {}
    nao: dict[tuple, list[dict]] = {}
    for p in materiais:
        v = vereditos.get(_unidade(p))
        if v is not None and v.get("kind") != "parada":
            nao.setdefault(_unidade(p), []).append(p)
            continue
        grupos.setdefault(p.get("transformer_name") or "?", []).append(p)
    if info is not None and nao:                           # o bot diz o veredito em vez de calar
        info["nao_paradas"] = [{
            "skids": sorted({p.get("transformer_name") or "?" for p in ps}),
            "inversores": len({p.get("slot_label") for p in ps}),
            "desde": _h(min(_quando(p.get("stopped_at")) for p in ps)),
            "ate": _h(max(_quando(p.get("resolved_at")) for p in ps)) if all(p.get("resolved_at") for p in ps) else None,
            "veredito": f"{vereditos[u]['result']} (linha {vereditos[u]['row']} do mapa)"} for u, ps in nao.items()]

    # ── regra 1 e 2: o que parou hoje, por skid ────────────────────────────────────────────────────────────────
    causas: dict[tuple, Achado] = {}
    sem_trip: list[tuple[str, list[dict]]] = []
    for skid, ps in grupos.items():
        inicio = min(_quando(p.get("stopped_at")) for p in ps if _quando(p.get("stopped_at")))
        resolvidas = [_quando(p.get("resolved_at")) for p in ps]
        fim = max(resolvidas) if all(resolvidas) else None
        perda = sum(p.get("shadow_loss_kwh") or 0 for p in ps)
        distintos = sorted({str(p.get("slot_label")) for p in ps}, key=lambda n: (len(n), n))
        nomes = ", ".join(distintos)
        hist = sorted(do_skid.get(skid, []), key=lambda e: e["quando"])
        antes = [e for e in hist if e["disparou"] and e["item"] and inicio - JANELA_TRIP <= e["quando"] <= inicio
                 + timedelta(minutes=30)]
        parada_txt = (f"{len(distintos)} inversor(es) ({nomes}) parados desde {_h(inicio)}"
                      + (f" até {_h(fim)}" if fim else "") + (f", {perda:.0f} kWh perdidos" if perda else "") + ".")
        prova = _verificacao(ps, vereditos)
        if antes:
            principal = antes[-1]
            item = principal["item"]
            chave = (item.codigo, principal["quando"].replace(second=0, microsecond=0))
            if chave in causas:                            # o mesmo trip em outro skid: um achado só
                a = causas[chave]
                a.skids.append(skid)
                a.evidencias += [parada_txt] + ([prova] if prova not in a.evidencias else [])
                a.desde = min(a.desde, inicio)
                continue
            rede = _da_rede(item, principal["quando"], por_rele)
            contexto = sorted({e["funcao"] for e in antes[:-1] if e["item"] is not item})
            causa = (f"trip {principal['funcao']} ({item.nome.lower()}) às {_h(principal['quando'])}"
                     + (f", depois de {', '.join(contexto)}" if contexto else "")
                     + (f", em {len(rede)} relés no mesmo minuto: evento da REDE da concessionária" if len(rede) >= 2
                        else f": {item.causas[0][0].lower() + item.causas[0][1:]}") )
            a = Achado(item.codigo, "skid desarmado, inversores sem gerar" if fim is None else
                       "skid desarmou e os inversores ficaram sem gerar", item.gravidade, usina["nome"], [skid], inicio,
                       fim, causa, [parada_txt, prova], list(item.fazer), item.religar_remoto)
            causas[chave] = a
            achados.append(a)
        elif reais := [p for p in ps if p.get("cause") != "communication_failure"]:
            sem_trip.append((skid, reais))
        # Só falha de leitura e sem trip: faltou o DADO do inversor, não a energia (Pereiras, 13/11: buracos de 9 min
        # com o relé medindo corrente). Não é parada: quem avisa é o "usina sem comunicação" e a verificação do meuWatt.
    com_rele = {r.get("transformer_name") for r in protecao}
    for juntos in _juntos(sem_trip):
        for s, _ in juntos:
            if s not in com_rele:
                cegos.setdefault(s, ["o skid não tem relé de proteção no meuWatt"])
        achados.append(_sem_trip(usina["nome"], juntos, cegos, vereditos))

    # ── regra 3, 4 e 5: o estado dos relés agora ────────────────────────────────────────────────────────────────
    ja = {s for a in achados for s in a.skids if a.resolvido_em is None}
    for r, hist in zip(protecao, historicos):
        skid = r.get("transformer_name") or r.get("name")
        lido = {x.get("key"): x for x in r.get("readings") or []}
        pot = (lido.get("total_active_power") or {}).get("value")
        fluxo = (lido.get("total_active_power") or {}).get("status") == "ok" and isinstance(pot, (int, float)) \
            and pot > FLUXO_KW                             # o relé mede energia passando: o disjuntor está fechado
        for e in _ativos(hist):
            if e["item"] is None or skid in ja or fluxo or agora - e["quando"] > timedelta(days=2):
                continue
            i = e["item"]
            achados.append(Achado(i.codigo, "skid DESARMADO agora", i.gravidade, usina["nome"], [skid], e["quando"],
                                  None, f"trip {e['funcao']} ({i.nome.lower()}) disparou às {_h(e['quando'])} e não limpou.",
                                  ["Os inversores deste skid não vão gerar até rearmar."], list(i.fazer), i.religar_remoto))
            ja.add(skid)
        comm = lido.get("comm") or {}
        if comm.get("status") == "unknown" and info is not None:   # nem mudo nem ok: quem chama não pode dizer "ok"
            info.setdefault("nao_conferidos", []).append(r.get("name") or str(r.get("relay_id")))
        if comm.get("status") == "no_comm":             # um achado por skid (o geral e o do skid juntos)
            i = matriz.MATRIZ["RELE_SEM_COMUNICACAO"]
            # A última leitura VÁLIDA (48 h; nula = nenhuma nesse tempo): a da linha da comunicação, que o meuWatt
            # tira da consulta de 48 h quando o monitoramento não conferiu.
            ultima = _quando(comm.get("last_valid_at") or r.get("last_read_at"))
            nome = _nome_rele(r)
            mudo = next((a for a in achados if a.codigo == i.codigo and a.skids == [skid]), None)
            if mudo:
                mudo.titulo = mudo.titulo.replace(" sem comunicação", f" e {nome} sem comunicação")
                if not _sabido(comm, pode):             # um dos dois ainda ninguém sabia: avisa
                    mudo.conhecido = None
                elif mudo.conhecido and _sabido(comm, pode) != mudo.conhecido:
                    mudo.conhecido += f"; {nome}: {_sabido(comm, pode)}"
            else:
                achados.append(Achado(i.codigo, f"{nome} sem comunicação", i.gravidade, usina["nome"], [skid], None,
                                      None, i.o_que_e, [f"Sem leitura válida no meuWatt desde {_h(ultima)}." if ultima
                                                        else "Sem leitura válida no meuWatt nas últimas 48 h."],
                                      list(i.fazer), conhecido=_sabido(comm, pode)))
        for f in "abc":                                 # zerada com o skid gerando = a MEDIÇÃO, não a rede
            fase = lido.get(f"voltage_{f}") or {}
            if fase.get("status") != "zeroed" or not isinstance(pot, (int, float)) or pot <= GERANDO_KW:
                continue
            i = matriz.MATRIZ["FASE_ZERO_MEDICAO"]
            v = [(lido.get(f"voltage_{x}") or {}).get("value") for x in "abc"]
            achados.append(Achado(i.codigo, f"fase {f.upper()} zerada na medição", i.gravidade, usina["nome"], [skid],
                                  None, None, i.causas[0],
                                  [f"Tensões {' / '.join(_n(x) + ' V' if isinstance(x, (int, float)) else '—' for x in v)}"
                                   f" com o skid gerando {_n(pot)} kW."],
                                  list(i.fazer), conhecido=_sabido(fase, pode), parte=f.upper()))
    for a in achados:
        a.slug = usina["slug"]
    return sorted(achados, key=lambda a: (_ORDEM.get(a.gravidade, 9), a.resolvido_em is not None))


# ── o que o meuWatt não sabe: os equipamentos lidos pelo helper ─────────────────────────────────────────────────────
#: A leitura barata de cada driver no helper (a mesma sonda do teste de comunicação, `core/healthcheck.py` de lá).
_LEITURA = {"pextron_urp6000": "funcoes_ativas", "siemens_7sr51": "telemetria", "huawei_sun2000": "status_falhas",
            "goodwe_gw": "status_falhas"}
ORIGEM = "diagnostico"


async def _ler(helper, slug: str, d: dict) -> dict:
    r = await helper.chamar("/api/read", {"plant_id": slug, "device_id": d["driver"], "host": d["ip"],
                                          "port": d.get("port") or 502, "slave": d["slave"],
                                          "read_cmd": _LEITURA[d["driver"]]}, ORIGEM)
    return r.get("resposta") if isinstance(r.get("resposta"), dict) else {"ok": False, "error": r.get("error")}


def _erro(r: dict) -> str:
    """A primeira oração do erro do helper ("o equipamento (slave 3 em …) não respondeu no barramento RS-485")."""
    return str(r.get("error") or "não respondeu").split(" — ")[0].rstrip(".")


def _inversores(lidos: list[tuple[dict, dict]]) -> list[str]:
    """Os inversores juntos pelo que disseram: "Inv 21, Inv 22: Grid-On (running), partiu às 07:37, sem falha nem
    alarme"."""
    juntos: dict[str, list[str]] = {}
    for d, r in lidos:
        nome = d.get("tag") or d.get("name")
        if not r.get("ok"):
            txt = f"não respondeu ao helper ({_erro(r)})"
        else:
            p = str(r.get("hora_partida") or "")
            partida = (p[11:16] if p[:10] == hoje().isoformat() else f"{p[8:10]}/{p[5:7]} {p[11:16]}") if p else ""
            falha = f"falha {r.get('codigo_falha')}" if r.get("falha_ativa") else "sem falha"
            alarme = "COM alarme ativo" if r.get("alarmes_ativos") else "nem alarme"
            txt = (f"{r.get('estado') or 'estado desconhecido'}"
                   + (f", partiu às {partida}" if partida else "") + f", {falha} {alarme}")
        juntos.setdefault(txt, []).append(nome)
    return [f"Helper agora: {', '.join(sorted(n, key=lambda x: (len(x), x)))}: {t}." for t, n in juntos.items()]


async def com_helper(helper, slug: str, achados: list[Achado]) -> None:
    """O dono (13/11/2026): "pesquisar o motivo no helper, ver o que tem lá". Lê ao vivo, pelo helper (só leitura), o
    que o meuWatt não diz: o relé que não comunica (o helper também não alcança = o relé ou o barramento; alcança = o
    coletor do meuWatt) e os inversores do skid que parou (estado, hora em que partiram, falha e alarme). Acrescenta às
    evidências; sem helper, VPN parada ou equipamento fora do registro dele, os achados ficam como estão."""
    from app.services.assistente_helper import _vpn_parada

    if helper is None or not achados or await _vpn_parada(helper):
        return
    await helper.chamar("/api/registry/plants", {}, ORIGEM)    # libera as usinas da conta para as outras rotas
    r = await helper.chamar("/api/registry/devices", {"slug": slug}, ORIGEM)
    devs = [d for d in ((r.get("resposta") or {}).get("devices") or []) if d.get("driver") in _LEITURA]
    for a in achados:
        if a.codigo == "FASE_ZERO_MEDICAO":
            continue
        cat = "relay" if a.codigo == "RELE_SEM_COMUNICACAO" else "inverter"
        alvos = [d for d in devs if d.get("category") == cat and d.get("group") in a.skids][:12]
        # Um de cada vez: os equipamentos dividem o mesmo gateway RS-485, e leituras juntas se atropelam.
        lidos = [(d, await _ler(helper, slug, d)) for d in alvos]
        if cat == "relay":
            a.evidencias += [f"Helper agora: o {d.get('name')} RESPONDE, então o relé está vivo e quem não lê é o "
                             "coletor do meuWatt." if x.get("ok") else
                             f"Helper agora: o {d.get('name')} também não responde ({_erro(x)})." for d, x in lidos]
        else:
            a.evidencias += _inversores(lidos)
