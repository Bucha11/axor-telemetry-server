from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    class FakePool:
        def acquire(self):
            return _FakeConn()

        async def executemany(self, _sql, _rows):
            self.last_rows = _rows

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def fetchval(self, _):
            return 1

        async def fetchrow(self, _):
            return {
                "n_records": 0, "n_contributors": 0,
                "top_signal": None, "top_signal_n": 0, "n_adjusted": 0,
            }

    fake = FakePool()

    async def _get_pool_stub():
        return fake

    from app import main as m
    monkeypatch.setattr(m, "get_pool", _get_pool_stub)
    monkeypatch.setattr(m, "init_pool", _get_pool_stub)
    monkeypatch.setattr(m, "close_pool", lambda: None)

    from app import stats as s
    monkeypatch.setattr(s, "_cache", {"t": 0.0, "html": ""})

    async with AsyncClient(transport=ASGITransport(app=m.app), base_url="http://t") as c:
        yield c


async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_empty_batch_accepted(client):
    r = await client.post("/v1/records", json=[])
    assert r.status_code == 200
    assert r.json() == {"accepted": 0}


async def test_valid_record_stored(client):
    payload = [{
        "signal_chosen": "debugging",
        "classifier_used": "heuristic",
        "confidence": 0.82,
        "tokens_spent": 4200,
        "policy_adjusted": False,
        "fingerprint_kind": "minhash_v1",
        "fingerprint": [1, 2, 3, 4],
        "axor_version": "0.3.0",
    }]
    r = await client.post("/v1/records", json=payload)
    assert r.status_code == 200
    assert r.json() == {"accepted": 1}


async def test_rejects_bad_confidence(client):
    payload = [{
        "signal_chosen": "debugging",
        "classifier_used": "heuristic",
        "confidence": 1.5,
        "tokens_spent": 100,
        "policy_adjusted": False,
    }]
    r = await client.post("/v1/records", json=payload)
    assert r.status_code == 422


async def test_rejects_oversized_batch(client):
    payload = [{
        "signal_chosen": "x",
        "classifier_used": "heuristic",
        "confidence": 0.5,
        "tokens_spent": 1,
        "policy_adjusted": False,
    }] * 1001
    r = await client.post("/v1/records", json=payload)
    assert r.status_code == 413


async def test_stats_renders(client):
    r = await client.get("/stats")
    assert r.status_code == 200
    assert "Axor telemetry" in r.text
    assert "Records this month" in r.text
