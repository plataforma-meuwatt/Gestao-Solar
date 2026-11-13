"""O DIAGNÓSTICO de uma usina: cruza o que parou (as paradas do detector do meuWatt e os inversores que não ligaram)
com os trips dos relés de proteção do skid e com a `matriz`, e diz a causa provável e o que fazer.

Pedido do dono (13/11/2026): Pirapozinho teve 47 às 22:48 e 27 nas três fases às 03:17 nos relés dos Skids 1 e 2; os
oito inversores deles não ligaram de manhã, e o aviso que saiu (07:28) dizia só "parado", sem a causa. "O bot deveria
enviar a mensagem … pesquisar o motivo … uma varredura de rotina … uma matriz". Este módulo é a leitura e a regra; quem
manda é a varredura (`varredura.py`) e quem explica é o bot (`diagnostico_usina`).

As regras, em ordem:
1. Parada (ou inversor sem ligar) num skid + trip no relé DAQUELE skid até 12 h antes = a função do trip é a causa (a
   última antes da parada; as de antes entram como contexto: a 47 que precede a 27). Vários relés com a mesma função no
   mesmo minuto = a REDE, não a usina.
2. Parada sem trip no relé do skid = "não ligou" ou a causa do detector, com os alarmes do inversor.
3. Trip que disparou e não limpou = skid DESARMADO agora (antes de qualquer parada: de madrugada já se sabe que o skid
   não vai ligar).
4. Relé sem comunicação = estado desconhecido.
5. Uma fase perto de zero com as outras normais e o skid gerando = fusível do TP de medição.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.datas import hoje, hora_brt
from app.services import matriz

#: Quanto antes da parada um trip ainda explica a parada (o 27 das 03:17 explica o "não ligou" das 05:46).
JANELA_TRIP = timedelta(hours=12)
#: Trips da mesma função em relés diferentes dentro disto = o mesmo evento da rede.
MESMO_EVENTO = timedelta(minutes=5)
_ORDEM = {"critica": 0, "alta": 1, "media": 2, "info": 3}


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

    @property
    def chave(self) -> str:
        """Estável por problema: a mesma queda avisa uma vez (a volta não reavisa)."""
        # O estado sem começo (relé sem comunicação, fase zerada) avisa uma vez POR DIA enquanto durar.
        quando = f"{self.desde:%Y-%m-%dT%H:%M}" if self.desde else hoje().isoformat()
        k = f"diag:{self.slug or self.usina}:{self.codigo}:{'+'.join(sorted(self.skids))}:{quando}"
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
                "religar_de_longe": self.religar_remoto}


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


def _fase_zero(tensoes: list[Any], potencia: Any) -> int | None:
    """O índice da fase perto de zero com as outras normais e o skid gerando (a MEDIÇÃO, não a rede)."""
    v = [x if isinstance(x, (int, float)) else None for x in tensoes]
    if None in v or not isinstance(potencia, (int, float)) or potencia <= 10:
        return None
    for i, x in enumerate(v):
        outras = [y for j, y in enumerate(v) if j != i]
        if min(outras) > 1000 and x < 0.1 * min(outras):
            return i
    return None


def _da_rede(funcao_item: matriz.Item, quando: datetime, todos: dict[str, list[dict]]) -> list[str]:
    """Os relés que dispararam a MESMA função no mesmo minuto: dois ou mais = evento da rede."""
    return sorted(nome for nome, evs in todos.items()
                  if any(e["disparou"] and e["item"] is funcao_item and abs(e["quando"] - quando) <= MESMO_EVENTO
                         for e in evs))


async def diagnosticar(mw, usina: dict, paradas: list[dict], agora: datetime | None = None) -> list[Achado]:
    """Os achados da usina AGORA. `usina`: {slug, nome}; `paradas`: as linhas do detector de hoje
    (`paradas.ler_do_detector`), para casar inversor e skid."""
    agora = agora or datetime.now(UTC)
    m = await mw.monitoramento_atual(usina["slug"])
    protecao = [r for r in m.get("relays") or []
                if not r.get("is_temperature_relay") and not str(r.get("model") or "").startswith("abs")]

    async def evs(r):
        try:
            return _eventos(await mw.eventos_de_trip(usina["slug"], int(r["relay_db_id"]), 50))
        except Exception:                                  # noqa: BLE001 — sem o histórico, as outras regras seguem
            return []

    historicos = await asyncio.gather(*(evs(r) for r in protecao))
    por_rele = {r.get("name") or str(r.get("relay_db_id")): h for r, h in zip(protecao, historicos)}
    # Os trips de TODOS os relés do skid (o geral pode ter o mesmo transformador: um não apaga o outro).
    do_skid: dict[str, list[dict]] = {}
    for r, h in zip(protecao, historicos):
        if r.get("transformer_name"):
            do_skid.setdefault(r["transformer_name"], []).extend(h)
    achados: list[Achado] = []

    # ── regra 1 e 2: o que parou hoje, por skid ────────────────────────────────────────────────────────────────
    grupos: dict[str, list[dict]] = {}
    for p in paradas:
        if p.get("materiality") not in (None, "material"):
            continue
        grupos.setdefault(p.get("transformer_name") or "?", []).append(p)
    causas: dict[tuple, Achado] = {}
    for skid, ps in grupos.items():
        inicio = min(_quando(p.get("stopped_at")) for p in ps if _quando(p.get("stopped_at")))
        resolvidas = [_quando(p.get("resolved_at")) for p in ps]
        fim = max(resolvidas) if all(resolvidas) else None
        perda = sum(p.get("shadow_loss_kwh") or 0 for p in ps)
        nomes = ", ".join(sorted({str(p.get("slot_label")) for p in ps}, key=lambda n: (len(n), n)))
        hist = sorted(do_skid.get(skid, []), key=lambda e: e["quando"])
        antes = [e for e in hist if e["disparou"] and e["item"] and inicio - JANELA_TRIP <= e["quando"] <= inicio
                 + timedelta(minutes=30)]
        parada_txt = (f"{len(ps)} inversor(es) ({nomes}) parados desde {_h(inicio)}"
                      + (f" até {_h(fim)}" if fim else "") + (f", {perda:.0f} kWh perdidos" if perda else "") + ".")
        if antes:
            principal = antes[-1]
            item = principal["item"]
            chave = (item.codigo, principal["quando"].replace(second=0, microsecond=0))
            if chave in causas:                            # o mesmo trip em outro skid: um achado só
                a = causas[chave]
                a.skids.append(skid)
                a.evidencias.append(parada_txt)
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
                       fim, causa, [parada_txt], list(item.fazer), item.religar_remoto)
            causas[chave] = a
            achados.append(a)
        else:
            item = matriz.MATRIZ["NAO_LIGOU"]
            nao_ligou = any(p.get("cause") == "never_woke_up" for p in ps)
            achados.append(Achado(
                "NAO_LIGOU" if nao_ligou else f"PARADA:{ps[0].get('cause')}",
                "inversores não ligaram" if nao_ligou else "inversores parados", "alta", usina["nome"], [skid], inicio,
                fim, "sem trip no relé do skid" + (": " + item.causas[1][0].lower() + item.causas[1][1:] if nao_ligou
                                                   else ""), [parada_txt],
                list(item.fazer) if nao_ligou else ["Conferir os alarmes dos inversores e o teste de comunicação."]))

    # ── regra 3, 4 e 5: o estado dos relés agora ────────────────────────────────────────────────────────────────
    ja = {s for a in achados for s in a.skids if a.resolvido_em is None}
    for r, hist in zip(protecao, historicos):
        skid = r.get("transformer_name") or r.get("name")
        for e in _ativos(hist):
            if e["item"] is None or skid in ja or agora - e["quando"] > timedelta(days=2):
                continue
            i = e["item"]
            achados.append(Achado(i.codigo, "skid DESARMADO agora", i.gravidade, usina["nome"], [skid], e["quando"],
                                  None, f"trip {e['funcao']} ({i.nome.lower()}) disparou às {_h(e['quando'])} e não limpou.",
                                  ["Os inversores deste skid não vão gerar até rearmar."], list(i.fazer), i.religar_remoto))
            ja.add(skid)
        if r.get("comm") is False:                        # um achado por skid (o geral e o do skid podem cair juntos)
            i = matriz.MATRIZ["RELE_SEM_COMUNICACAO"]
            nome = str(r.get("name") or "")
            nome = nome if nome.lower().startswith("rel") else f"relé {nome}"
            mudo = next((a for a in achados if a.codigo == i.codigo and a.skids == [skid]), None)
            if mudo:
                mudo.titulo = mudo.titulo.replace(" sem comunicação", f" e {nome} sem comunicação")
            else:
                achados.append(Achado(i.codigo, f"{nome} sem comunicação", i.gravidade, usina["nome"], [skid], None,
                                      None, i.o_que_e, [], list(i.fazer)))
        f = _fase_zero([r.get(f"voltage_{x}") for x in "abc"], r.get("total_active_power"))
        if f is not None:
            i = matriz.MATRIZ["FASE_ZERO_MEDICAO"]
            v = [r.get(f"voltage_{x}") for x in "abc"]
            achados.append(Achado(i.codigo, f"fase {'ABC'[f]} zerada na medição", i.gravidade, usina["nome"], [skid],
                                  None, None, i.causas[0],
                                  [f"Tensões {' / '.join(_n(x) + ' V' for x in v)} com o skid gerando "
                                   f"{_n(r.get('total_active_power'))} kW."],
                                  list(i.fazer)))
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
