"""Tests for component state persistence endpoints."""

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


class TestPutComponentState:
    async def test_save_state(self, client):
        resp = await client.put(
            "/component-state/observe",
            json={
                "last_cursor": "2026-04-23T10:00:00Z",
                "hysteresis_state": {"fraud-detect": {"breach_count": 2}},
                "dedup_cache": {"vrd-123": True},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["component"] == "observe"

    async def test_overwrite_state(self, client):
        await client.put(
            "/component-state/measure",
            json={"last_cursor": "2026-04-23T09:00:00Z"},
        )
        resp = await client.put(
            "/component-state/measure",
            json={"last_cursor": "2026-04-23T10:00:00Z"},
        )
        assert resp.status_code == 200

        get_resp = await client.get("/component-state/measure")
        assert get_resp.json()["last_cursor"] == "2026-04-23T10:00:00Z"

    async def test_invalid_body(self, client):
        resp = await client.put(
            "/component-state/observe",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422


class TestGetComponentState:
    async def test_get_existing(self, client):
        await client.put(
            "/component-state/correlate",
            json={
                "last_cursor": "2026-04-23T10:00:00Z",
                "hysteresis_state": {"window_1": "active"},
                "dedup_cache": {},
            },
        )
        resp = await client.get("/component-state/correlate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["component"] == "correlate"
        assert body["last_cursor"] == "2026-04-23T10:00:00Z"
        assert body["hysteresis_state"] == {"window_1": "active"}

    async def test_get_nonexistent_returns_404(self, client):
        resp = await client.get("/component-state/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"

    async def test_empty_dict_roundtrip(self, client):
        """Empty dicts for hysteresis_state and dedup_cache must survive roundtrip."""
        await client.put(
            "/component-state/observe",
            json={
                "last_cursor": "2026-04-23T10:00:00Z",
                "hysteresis_state": {},
                "dedup_cache": {},
            },
        )
        resp = await client.get("/component-state/observe")
        assert resp.status_code == 200
        body = resp.json()
        assert body["hysteresis_state"] == {}
        assert body["dedup_cache"] == {}

    async def test_roundtrip_preserves_state(self, client):
        """Save state, simulate restart (no state in memory), restore state."""
        state = {
            "last_cursor": "2026-04-23T12:00:00Z",
            "hysteresis_state": {
                "fraud-detect:reversal_rate": {
                    "breach_count": 3,
                    "last_breach_at": "2026-04-23T11:55:00Z",
                },
            },
            "dedup_cache": {
                "vrd-2026-04-23-abc12345-00001": True,
                "vrd-2026-04-23-def67890-00002": True,
            },
        }
        await client.put("/component-state/respond", json=state)

        resp = await client.get("/component-state/respond")
        assert resp.status_code == 200
        restored = resp.json()
        assert restored["last_cursor"] == state["last_cursor"]
        assert restored["hysteresis_state"] == state["hysteresis_state"]
        assert restored["dedup_cache"] == state["dedup_cache"]
