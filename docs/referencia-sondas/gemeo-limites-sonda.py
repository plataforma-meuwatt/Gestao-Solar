#!/usr/bin/env python3
"""Leitura diária dos LIMITES de potência dos inversores das usinas com gêmeo digital (meuWatt › Gêmeos › Limites).

Pedido do Renan (06/11/2026): "a gente tem informação de leitura do inversor para saber qual potência ele está
limitada — monta uma tabela onde você confere todo dia qual é a real limitação do inversor".

Usa as sondas Modbus do mw-api (/admin/modbus-probes), como o mw-diag-sonda: quem lê é o PRÓPRIO coletor da usina,
só leitura (FC03), pelo mesmo soquete. Registradores do Huawei SUN2000 (mapa da biblioteca sun2000_modbus 3.0, a do
mw-core):
  todo dia .................. 35300–35303  o ajuste de potência ativa em vigor (modo, valor, quem mandou)
  segunda-feira e 1ª vez .... 30073–30076  potência nominal / máxima
                              40120–40127  limitação fixa (kW), percentual, fixa (W)
                              42405–42406  limite de potência ativa
Os registradores vão crus para o mw-analise (POST /gemeos/limites/leituras, assinado como o espelho), que decodifica
(app/gemeo_config.py::decodifica). As usinas vêm do próprio mw-analise (GET /gemeos/limites/alvos).

Token do meuWatt: o PAT do usuário de serviço do monitor de rede (/root/.segredos/mw-netmon-token).
Segredo do espelho: /root/.segredos/espelho-segredo. Nunca imprime nenhum dos dois. Log: journalctl -u gemeo-limites.
  gemeo-limites-sonda.py                      o que o timer roda
  gemeo-limites-sonda.py --completo           lê todos os blocos agora
  gemeo-limites-sonda.py --usina ibitinga     só uma usina (ANALISE_URL troca o endereço do mw-analise, para teste)
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.meuwatt.com.br"
ANALISE = os.environ.get("ANALISE_URL", "https://analise.meuwatt.com.br")
TOKEN = open("/root/.segredos/mw-netmon-token").read().strip()
SEGREDO = open("/root/.segredos/espelho-segredo").read().strip()
ESTADO = Path("/var/lib/gemeo-limites/completo.json")
DIARIO = [(35300, 4)]
SEMANAL = [(30073, 4), (40120, 8), (42405, 2)]


def req(method, url, body=None, headers=None):
    r = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.load(f)


def mw(method, path, body=None):
    return req(method, API + path, json.dumps(body).encode() if body else None,
               {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})


def analise(method, path, corpo=b""):
    ts = str(int(time.time()))
    assinatura = hmac.new(SEGREDO.encode(), ts.encode() + b"." + corpo, hashlib.sha256).hexdigest()
    return req(method, ANALISE + path, corpo or None, {"Content-Type": "application/json", "X-Espelho-Ts": ts,
                                                        "X-Espelho-Assinatura": assinatura})


def sonda(slug, ip, slave, start, count):
    p = mw("POST", f"/admin/modbus-probes/plants/{slug}", dict(
        mode="raw", device_kind="inverter", ip_address=ip, port=502, slave_id=slave,
        register_type="holding", start_address=start, register_count=count))
    for _ in range(60):
        time.sleep(3)
        p = mw("GET", f"/admin/modbus-probes/{p['id']}")
        if p["status"] not in ("pending", "claimed"):
            break
    regs = (p.get("result") or {}).get("registers") or []
    return {r["address"]: int(r["value"]) for r in regs}


def usina(alvo, estado, completo):
    slug = alvo["slug"]
    inv = mw("GET", f"/plants/{slug}/inverters/diagnostics/summary")["inverters"]
    inv = [i for i in inv if (i.get("model_id") or "").startswith("huawei_sun2000") and i["ip_address"] and i["slave_id"] is not None]
    feito = estado.setdefault(slug, {})
    leituras, falhas = [], 0
    for i in inv:   # o coletor atende uma sonda por vez
        chave = f"{i['ip_address']}:{i['slave_id']}"
        blocos = DIARIO + (SEMANAL if completo or datetime.now().weekday() == 0 or chave not in feito else [])
        regs = {}
        for start, n in blocos:
            try:
                regs.update(sonda(slug, i["ip_address"], i["slave_id"], start, n))
            except Exception as e:  # noqa: BLE001 — um inversor que não responde não para os outros
                print(f"{slug} {i['label']}: {start} falhou ({type(e).__name__})", flush=True)
        if not regs:
            falhas += 1
            continue
        if any(a in regs for a in (30073, 40120)):
            feito[chave] = datetime.now(timezone.utc).date().isoformat()
        leituras.append({"ip": i["ip_address"], "slave": int(i["slave_id"]),
                         "lido_em": datetime.now(timezone.utc).isoformat(), "registros": regs})
    r = analise("POST", "/gemeos/limites/leituras",
                json.dumps({"plant_id": alvo["plant_id"], "leituras": leituras}).encode()) if leituras else {"gravadas": 0}
    print(f"{slug}: {len(leituras)} inversor(es) lido(s), {falhas} sem resposta, {r['gravadas']} gravada(s)", flush=True)


def main():
    completo = "--completo" in sys.argv
    estado = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    alvos = analise("GET", "/gemeos/limites/alvos")
    if "--usina" in sys.argv:
        so = sys.argv[sys.argv.index("--usina") + 1]
        alvos = [a for a in alvos if a["slug"] == so]
    def uma(a):
        try:
            usina(a, estado, completo)
        except Exception as e:  # noqa: BLE001 — uma usina com problema não para as outras
            print(f"{a['slug']}: falhou ({type(e).__name__}: {str(e)[:200]})", flush=True)

    with ThreadPoolExecutor(max(1, len(alvos))) as ex:   # uma linha por usina: cada coletor atende as suas sondas
        list(ex.map(uma, alvos))
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado))


if __name__ == "__main__":
    main()
