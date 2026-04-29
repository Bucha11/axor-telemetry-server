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
                "n_all": 0, "n_month": 0, "n_day": 0,
                "n_contributors_month": 0, "n_contributors_day": 0,
                "n_adjusted_month": 0, "avg_conf_month": 0.0,
                "latest_version": None,
            }

        async def fetch(self, _):
            return []

    fake = FakePool()

    async def _get_pool_stub():
        return fake

    from app import main as m
    monkeypatch.setattr(m, "get_pool", _get_pool_stub)
    monkeypatch.setattr(m, "init_pool", _get_pool_stub)
    monkeypatch.setattr(m, "close_pool", lambda: None)

    from app import stats as s
    s._reset_cache_for_tests()

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


async def test_stats_renders_empty_db(client):
    r = await client.get("/stats")
    assert r.status_code == 200
    assert "Axor community telemetry" in r.text
    # empty db → chart placeholder message present
    assert "No signals recorded yet" in r.text
    # Contract + changelog links always present
    assert "Heuristic changelog" in r.text
    assert "Data contract" in r.text


async def test_ingest_token_required_when_set(client, monkeypatch):
    monkeypatch.setenv("INGEST_SHARED_SECRET", "s3cret")
    payload = [{
        "signal_chosen": "x",
        "classifier_used": "heuristic",
        "confidence": 0.5,
        "tokens_spent": 1,
        "policy_adjusted": False,
    }]
    r = await client.post("/v1/records", json=payload)
    assert r.status_code == 401

    r = await client.post("/v1/records", json=payload, headers={"X-Axor-Token": "wrong"})
    assert r.status_code == 401

    r = await client.post("/v1/records", json=payload, headers={"X-Axor-Token": "s3cret"})
    assert r.status_code == 200


async def test_ingest_open_when_secret_unset(client, monkeypatch):
    monkeypatch.delenv("INGEST_SHARED_SECRET", raising=False)
    payload = [{
        "signal_chosen": "x",
        "classifier_used": "heuristic",
        "confidence": 0.5,
        "tokens_spent": 1,
        "policy_adjusted": False,
    }]
    r = await client.post("/v1/records", json=payload)
    assert r.status_code == 200
