"""Tests for heartbeat and stuck-action-request monitoring endpoints."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from nthlayer.server import app, set_store
from nthlayer.store import Store


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


# -- POST /heartbeats --

class TestPostHeartbeat:
    @pytest.mark.asyncio
    async def test_submit_heartbeat(self, client):
        r = await client.post("/heartbeats", json={
            "component": "workers",
            "instance_id": "i-001",
            "state": {"cycles": 42},
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_missing_fields_returns_422(self, client):
        r = await client.post("/heartbeats", json={"component": "workers"})
        assert r.status_code == 422
        assert "instance_id" in r.json()["detail"]["fields"]

    @pytest.mark.asyncio
    async def test_invalid_json_returns_422(self, client):
        r = await client.post(
            "/heartbeats",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_upsert_updates_last_seen(self, client):
        await client.post("/heartbeats", json={
            "component": "workers", "instance_id": "i-001", "state": {"cycles": 1},
        })
        await client.post("/heartbeats", json={
            "component": "workers", "instance_id": "i-001", "state": {"cycles": 2},
        })
        r = await client.get("/heartbeats")
        beats = r.json()
        assert len(beats) == 1
        assert beats[0]["state"]["cycles"] == 2


# -- GET /heartbeats --

class TestGetHeartbeats:
    @pytest.mark.asyncio
    async def test_healthy_heartbeat(self, client):
        await client.post("/heartbeats", json={
            "component": "workers", "instance_id": "i-001",
        })
        r = await client.get("/heartbeats")
        assert r.status_code == 200
        beats = r.json()
        assert len(beats) == 1
        assert beats[0]["health"] == "healthy"
        assert beats[0]["age_seconds"] < 5  # just created

    @pytest.mark.asyncio
    async def test_degraded_heartbeat(self, client, store):
        """Heartbeat older than threshold shows as degraded."""
        # Directly insert an old heartbeat
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        conn = store._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO heartbeats (component, instance_id, last_seen, state) VALUES (?, ?, ?, ?)",
            ("stale-worker", "i-old", old_time, None),
        )
        r = await client.get("/heartbeats")
        beats = r.json()
        stale = [b for b in beats if b["component"] == "stale-worker"]
        assert len(stale) == 1
        assert stale[0]["health"] == "degraded"
        assert stale[0]["age_seconds"] > 50

    @pytest.mark.asyncio
    async def test_custom_threshold(self, client, store):
        """Custom threshold changes what counts as degraded."""
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        conn = store._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO heartbeats (component, instance_id, last_seen, state) VALUES (?, ?, ?, ?)",
            ("marginal", "i-m", old_time, None),
        )
        # With default 30s threshold, 10s old is healthy
        r1 = await client.get("/heartbeats")
        marginal = [b for b in r1.json() if b["component"] == "marginal"]
        assert marginal[0]["health"] == "healthy"

        # With 5s threshold, 10s old is degraded
        r2 = await client.get("/heartbeats", params={"threshold": "5"})
        marginal2 = [b for b in r2.json() if b["component"] == "marginal"]
        assert marginal2[0]["health"] == "degraded"

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, client):
        r = await client.get("/heartbeats")
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_invalid_threshold_returns_422(self, client):
        r = await client.get("/heartbeats", params={"threshold": "abc"})
        assert r.status_code == 422


# -- GET /monitoring/stuck-action-requests --

class TestStuckActionRequests:
    @pytest.mark.asyncio
    async def test_no_stuck_returns_empty(self, client):
        r = await client.get("/monitoring/stuck-action-requests")
        assert r.status_code == 200
        assert r.json()["count"] == 0
        assert r.json()["stuck"] == []

    @pytest.mark.asyncio
    async def test_action_request_with_case_not_stuck(self, client):
        """action_request that has a corresponding case is not stuck."""
        await client.post("/verdicts", json={
            "id": "vrd-ar-001",
            "type": "action_request",
            "service": "payment-api",
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        })
        await client.post("/cases", json={
            "id": "case-for-ar",
            "kind": "approval_required",
            "priority": "P1",
            "created_at": _now(),
            "underlying_verdict": "vrd-ar-001",
            "service": "payment-api",
        })
        r = await client.get("/monitoring/stuck-action-requests")
        assert r.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_action_request_without_case_is_stuck(self, client):
        """action_request older than threshold with no case is stuck."""
        await client.post("/verdicts", json={
            "id": "vrd-ar-stuck",
            "type": "action_request",
            "service": "fraud-detect",
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        })
        # No case created for this action_request
        r = await client.get("/monitoring/stuck-action-requests")
        assert r.json()["count"] == 1
        assert r.json()["stuck"][0]["id"] == "vrd-ar-stuck"

    @pytest.mark.asyncio
    async def test_recent_action_request_not_stuck(self, client):
        """action_request created recently (within threshold) is not stuck yet."""
        await client.post("/verdicts", json={
            "id": "vrd-ar-fresh",
            "type": "action_request",
            "service": "payment-api",
            "created_at": _now(),
        })
        r = await client.get("/monitoring/stuck-action-requests")
        assert r.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_non_action_request_not_included(self, client):
        """Only action_request type verdicts are checked — others are ignored."""
        await client.post("/verdicts", json={
            "id": "vrd-other",
            "type": "quality_breach",
            "service": "payment-api",
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        })
        r = await client.get("/monitoring/stuck-action-requests")
        assert r.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_custom_threshold(self, client):
        """Custom threshold parameter changes detection window."""
        await client.post("/verdicts", json={
            "id": "vrd-ar-custom",
            "type": "action_request",
            "service": "payment-api",
            "created_at": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        })
        # Default 60s threshold — 30s old is not stuck yet
        r1 = await client.get("/monitoring/stuck-action-requests")
        assert r1.json()["count"] == 0

        # With 10s threshold — 30s old is stuck
        r2 = await client.get("/monitoring/stuck-action-requests", params={"threshold": "10"})
        assert r2.json()["count"] == 1
