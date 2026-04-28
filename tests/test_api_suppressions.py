"""Tests for suppression audit trail endpoints."""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from nthlayer_core.server import app, set_store
from nthlayer_core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    set_store(s)
    yield s
    s.close()
    set_store(None)


@pytest.fixture
async def client(store):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


class TestPostSuppression:
    async def test_create_suppression(self, client):
        resp = await client.post("/suppressions", json={
            "component": "measure",
            "reason": "active_incident",
            "suppressed_verdict_id": "vrd-100",
            "related_verdict_id": "vrd-123",
            "suppressed_at": _now(),
        })
        assert resp.status_code == 201
        assert "id" in resp.json()

    async def test_create_without_related_verdict(self, client):
        resp = await client.post("/suppressions", json={
            "component": "correlate",
            "reason": "dedup",
            "suppressed_verdict_id": "vrd-200",
        })
        assert resp.status_code == 201

    async def test_missing_component_returns_422(self, client):
        resp = await client.post("/suppressions", json={
            "reason": "hysteresis",
            "suppressed_verdict_id": "vrd-300",
        })
        assert resp.status_code == 422
        assert "component" in resp.json()["detail"]["fields"]

    async def test_missing_reason_returns_422(self, client):
        resp = await client.post("/suppressions", json={
            "component": "measure",
            "suppressed_verdict_id": "vrd-400",
        })
        assert resp.status_code == 422
        assert "reason" in resp.json()["detail"]["fields"]

    async def test_missing_suppressed_verdict_id_returns_422(self, client):
        resp = await client.post("/suppressions", json={
            "component": "measure",
            "reason": "dedup",
        })
        assert resp.status_code == 422
        assert "suppressed_verdict_id" in resp.json()["detail"]["fields"]


class TestGetSuppressions:
    async def test_query_all(self, client):
        await client.post("/suppressions", json={
            "component": "measure", "reason": "active_incident", "suppressed_verdict_id": "vrd-1",
        })
        await client.post("/suppressions", json={
            "component": "correlate", "reason": "dedup", "suppressed_verdict_id": "vrd-2",
        })
        resp = await client.get("/suppressions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_filter_by_component(self, client):
        await client.post("/suppressions", json={
            "component": "measure", "reason": "active_incident", "suppressed_verdict_id": "vrd-1",
        })
        await client.post("/suppressions", json={
            "component": "correlate", "reason": "dedup", "suppressed_verdict_id": "vrd-2",
        })
        resp = await client.get("/suppressions?component=measure")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["component"] == "measure"

    async def test_filter_by_time_range(self, client):
        t1 = "2026-04-23T10:00:00+00:00"
        t2 = "2026-04-23T11:00:00+00:00"
        t3 = "2026-04-23T12:00:00+00:00"
        await client.post("/suppressions", json={
            "component": "measure", "reason": "r1", "suppressed_verdict_id": "vrd-1", "suppressed_at": t1,
        })
        await client.post("/suppressions", json={
            "component": "measure", "reason": "r2", "suppressed_verdict_id": "vrd-2", "suppressed_at": t2,
        })
        await client.post("/suppressions", json={
            "component": "measure", "reason": "r3", "suppressed_verdict_id": "vrd-3", "suppressed_at": t3,
        })
        # All three match >= t1 AND <= t3
        resp = await client.get(f"/suppressions?created_after={t1}&created_before={t3}")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

        # Only t1 and t2 match <= t2
        resp2 = await client.get(f"/suppressions?created_after={t1}&created_before={t2}")
        assert resp2.status_code == 200
        assert len(resp2.json()) == 2

    async def test_empty_result(self, client):
        resp = await client.get("/suppressions")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_limit_param(self, client):
        for i in range(3):
            await client.post("/suppressions", json={
                "component": "measure", "reason": "dedup", "suppressed_verdict_id": f"vrd-{i}",
            })
        resp = await client.get("/suppressions?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_suppression_contains_all_fields(self, client):
        await client.post("/suppressions", json={
            "component": "respond",
            "reason": "hysteresis",
            "suppressed_verdict_id": "vrd-500",
            "related_verdict_id": "vrd-456",
        })
        resp = await client.get("/suppressions")
        record = resp.json()[0]
        assert record["component"] == "respond"
        assert record["reason"] == "hysteresis"
        assert record["suppressed_verdict_id"] == "vrd-500"
        assert record["related_verdict_id"] == "vrd-456"
