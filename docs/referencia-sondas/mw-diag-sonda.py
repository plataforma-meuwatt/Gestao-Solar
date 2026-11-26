#!/usr/bin/env python3
"""Leitura PROVISÓRIA do diagnóstico dos inversores (alarmes, isolação, partida) até o mw-core ler.

Pedido do Renan (12/10/2026) depois do Inv 14 de Pirapozinho não acordar por isolação baixa.
Usa as sondas Modbus do mw-api (/admin/modbus-probes): quem lê é o PRÓPRIO coletor da usina,
só leitura (FC03), pelo mesmo soquete — nenhuma segunda conexão no logger. Manda os
registradores crus para POST /inverter-diagnostics/plants/{slug}, que decodifica pela biblioteca.

Como economiza: entre 06h e 10h (timer a cada 10 min), lê só o inversor que AINDA NÃO LIGOU hoje
(a última partida conhecida não é de hoje). Quem ligou sai da lista; quem não liga (isolação
baixa) é lido a cada 10 min — e o alarme aceso fica gravado com a isolação medida. O limite de
proteção (42097) é lido junto da primeira partida do dia.

Token: o PAT do usuário de serviço do monitor de rede (/root/.segredos/mw-netmon-token). Nunca
imprime o token. Log: journalctl -u mw-diag-sonda.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

API = "https://api.meuwatt.com.br"
TOKEN = open("/root/.segredos/mw-netmon-token").read().strip()
BRT = timezone(timedelta(hours=-3))
USINAS = ["pirapozinho", "porto-ferreira", "tiete", "ufv-ouro-fino-eldorado-energia", "ibitinga"]
BLOCO = (32008, 87)        # 32008..32094: alarmes 1–3 … isolação, status, falha, partida, parada
QUERO = list(range(32008, 32011)) + list(range(32088, 32095))
LIMITE = 42097


def req(method, path, body=None):
    r = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                               headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.load(f)


def sonda(slug, ip, slave, start, count):
    p = req("POST", f"/admin/modbus-probes/plants/{slug}", dict(
        mode="raw", device_kind="inverter", ip_address=ip, port=502, slave_id=slave,
        register_type="holding", start_address=start, register_count=count))
    for _ in range(60):
        time.sleep(3)
        p = req("GET", f"/admin/modbus-probes/{p['id']}")
        if p["status"] not in ("pending", "claimed"):
            break
    regs = (p.get("result") or {}).get("registers") or []
    return {r["address"]: int(r["value"]) for r in regs} or None


def usina(slug, todos):
    hoje = datetime.now(BRT).date()
    inv = req("GET", f"/plants/{slug}/inverters/diagnostics/summary")["inverters"]
    alvo = [i for i in inv if i["has_diagnostics_map"] and i["ip_address"] and i["slave_id"] is not None and (
        todos or not i["last_startup"]
        or datetime.fromisoformat(i["last_startup"]["at"]).astimezone(BRT).date() != hoje)]
    for i in alvo:
        regs = sonda(slug, i["ip_address"], i["slave_id"], *BLOCO)
        if not regs:
            print(f"{slug} {i['label']}: sem resposta", flush=True)
            continue
        out = {str(a): regs[a] for a in QUERO if a in regs}
        partida = (regs.get(32091, 0) << 16) | regs.get(32092, 0)
        if partida and datetime.fromtimestamp(partida, timezone.utc).date() == hoje:
            lim = sonda(slug, i["ip_address"], i["slave_id"], LIMITE, 1)
            if lim:
                out[str(LIMITE)] = lim[LIMITE]
        print(f"{slug} {i['label']}: isolação {regs.get(32088, 0) / 1000:.3f} MΩ status 0x{regs.get(32089, 0):04X} "
              f"falha {regs.get(32090)} alarmes {regs.get(32008)}/{regs.get(32009)}/{regs.get(32010)}", flush=True)
        # manda já: Porto Ferreira leva ~1 min por inversor e a rodada passava dos 20 min sem enviar nada (13/10)
        r = req("POST", f"/inverter-diagnostics/plants/{slug}", {"readings": [{
            "slot_id": i["slot_id"], "timestamp": datetime.now(timezone.utc).isoformat(), "registers": out}],
            "source": "srvclaude-sonda"})
        print(f"{slug} {i['label']}: {json.dumps(r, ensure_ascii=False)}", flush=True)
    return len(alvo)


def main():
    todos = "--todos" in sys.argv
    with ThreadPoolExecutor(len(USINAS)) as ex:  # uma linha por usina: cada coletor atende as suas sondas
        for slug, fut in [(s, ex.submit(usina, s, todos)) for s in USINAS]:
            try:
                print(f"{slug}: {fut.result()} inversor(es) lido(s)", flush=True)
            except urllib.error.HTTPError as e:
                print(f"{slug}: HTTP {e.code} {e.read()[:300]!r}", flush=True)
            except Exception as e:  # uma usina com problema não para as outras
                print(f"{slug}: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    main()
