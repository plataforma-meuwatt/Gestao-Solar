"""Aviso instantâneo de parada: o webhook do meuWatt (api/v1/meuwatt_webhook)."""

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.v1 import meuwatt_webhook as wh
from app.main import app
from app.services import avisos


def _assinado(segredo: str, corpo: bytes, ts: int | None = None) -> dict:
    t = str(ts or int(time.time()))
    mac = hmac.new(segredo.encode(), t.encode() + b"." + corpo, hashlib.sha256).hexdigest()
    return {"X-MeuWatt-Timestamp": t, "X-MeuWatt-Signature": f"sha256={mac}", "Content-Type": "application/json"}


def test_assinatura():
    corpo = b'{"plant":{"slug":"tiete"}}'
    h = _assinado("s3", corpo)
    assert wh.assinatura_valida("s3", h["X-MeuWatt-Timestamp"], corpo, h["X-MeuWatt-Signature"])
    assert not wh.assinatura_valida("outro", h["X-MeuWatt-Timestamp"], corpo, h["X-MeuWatt-Signature"])
    assert not wh.assinatura_valida("s3", h["X-MeuWatt-Timestamp"], corpo + b" ", h["X-MeuWatt-Signature"])
    velho = _assinado("s3", corpo, int(time.time()) - 600)
    assert not wh.assinatura_valida("s3", velho["X-MeuWatt-Timestamp"], corpo, velho["X-MeuWatt-Signature"])


def test_rota_fecha_sem_segredo_e_com_assinatura_errada(monkeypatch):
    corpo = b'{"plant":{"slug":"tiete"}}'
    c = TestClient(app)
    monkeypatch.delenv("MEUWATT_WEBHOOK_SECRET", raising=False)
    assert c.post("/api/v1/interno/meuwatt/paradas", content=corpo, headers=_assinado("s3", corpo)).status_code == 503
    monkeypatch.setenv("MEUWATT_WEBHOOK_SECRET", "s3")
    assert c.post("/api/v1/interno/meuwatt/paradas", content=corpo, headers=_assinado("x", corpo)).status_code == 401


def test_rota_agenda_a_varredura_da_usina(monkeypatch):
    monkeypatch.setenv("MEUWATT_WEBHOOK_SECRET", "s3")
    varridas = []

    async def falsa():
        varridas.append(frozenset(wh._pendentes))
        wh._pendentes.clear()
        wh._agendada = None

    monkeypatch.setattr(wh, "_varrer", falsa)
    corpo = b'{"event":"breakdowns.new","plant":{"slug":"tiete"}}'
    r = TestClient(app).post("/api/v1/interno/meuwatt/paradas", content=corpo, headers=_assinado("s3", corpo))
    assert r.status_code == 200
    assert varridas == [frozenset({"tiete"})]


def test_parada_confirmada_nao_espera_os_20_min():
    inv = {"down": True, "down_since": (datetime.now(UTC) - timedelta(minutes=2)).isoformat()}
    assert avisos._parados({"inverters": [inv]}) == []
    assert avisos._parados({"inverters": [inv]}, imediata=True) == [inv]
