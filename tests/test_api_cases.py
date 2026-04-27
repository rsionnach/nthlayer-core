"""Tests for case and change-freeze HTTP API endpoints."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from nthlayer.server import app, set_store, _derive_priority
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


def _case(**overrides):
    base = {
        "id": "case-001",
        "kind": "approval_required",
        "created_at": _now(),
        "underlying_verdict": "vrd-001",
        "service": "payment-api",
        "briefing": "Test case",
    }
    base.update(overrides)
    return base


def _freeze(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "name": "test-freeze",
        "declared_by": "platform-team",
        "declared_at": now.isoformat(),
        "active_from": (now - timedelta(hours=1)).isoformat(),
        "active_until": (now + timedelta(hours=1)).isoformat(),
        "reason": "Test freeze",
    }
    base.update(overrides)
    return base


# -- Priority derivation --

class TestPriorityDerivation:
    def test_production_with_incident_is_p0(self):
        assert _derive_priority("production", True) == "P0"

    def test_production_no_incident_is_p1(self):
        assert _derive_priority("production", False) == "P1"

    def test_staging_no_incident_is_p2(self):
        assert _derive_priority("staging", False) == "P2"

    def test_dev_is_p3(self):
        assert _derive_priority("dev", False) == "P3"

    def test_ephemeral_is_p3(self):
        assert _derive_priority("ephemeral", False) == "P3"

    def test_none_blast_radius_is_p3(self):
        assert _derive_priority(None, False) == "P3"

    def test_staging_with_incident_is_p1(self):
        assert _derive_priority("staging", True) == "P1"


# -- POST /cases --

class TestPostCase:
    @pytest.mark.asyncio
    async def test_create_case_with_explicit_priority(self, client):
        r = await client.post("/cases", json=_case(priority="P0"))
        assert r.status_code == 201
        assert r.json()["id"] == "case-001"
        assert r.json()["priority"] == "P0"

    @pytest.mark.asyncio
    async def test_create_case_derives_priority_from_blast_radius(self, client):
        r = await client.post("/cases", json=_case(
            id="case-derived",
            blast_radius="production",
            has_active_incident=True,
        ))
        assert r.status_code == 201
        assert r.json()["priority"] == "P0"

    @pytest.mark.asyncio
    async def test_create_case_production_no_incident_is_p1(self, client):
        r = await client.post("/cases", json=_case(
            id="case-p1",
            blast_radius="production",
            has_active_incident=False,
        ))
        assert r.json()["priority"] == "P1"

    @pytest.mark.asyncio
    async def test_create_case_no_blast_radius_defaults_p3(self, client):
        r = await client.post("/cases", json=_case(id="case-default"))
        assert r.json()["priority"] == "P3"

    @pytest.mark.asyncio
    async def test_missing_fields_returns_422(self, client):
        r = await client.post("/cases", json={"service": "test"})
        assert r.status_code == 422
        assert "id" in r.json()["detail"]["fields"]

    @pytest.mark.asyncio
    async def test_invalid_json_returns_422(self, client):
        r = await client.post(
            "/cases",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_json"

    @pytest.mark.asyncio
    async def test_duplicate_returns_409(self, client):
        await client.post("/cases", json=_case(id="case-dup", priority="P1"))
        r = await client.post("/cases", json=_case(id="case-dup", priority="P1"))
        assert r.status_code == 409


# -- GET /cases --

class TestGetCases:
    @pytest.mark.asyncio
    async def test_get_single(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        r = await client.get("/cases/case-001")
        assert r.status_code == 200
        assert r.json()["id"] == "case-001"
        assert r.json()["state"] == "pending"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self, client):
        r = await client.get("/cases/nonexistent")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_query_by_priority(self, client):
        await client.post("/cases", json=_case(id="c1", priority="P0"))
        await client.post("/cases", json=_case(id="c2", priority="P2"))
        await client.post("/cases", json=_case(id="c3", priority="P0"))
        r = await client.get("/cases", params={"priority": "P0"})
        assert len(r.json()) == 2

    @pytest.mark.asyncio
    async def test_query_by_state(self, client):
        await client.post("/cases", json=_case(id="c-pending", priority="P1"))
        r = await client.get("/cases", params={"state": "pending"})
        assert len(r.json()) == 1

    @pytest.mark.asyncio
    async def test_invalid_limit_returns_422(self, client):
        r = await client.get("/cases", params={"limit": "abc"})
        assert r.status_code == 422


# -- Lease management --

class TestCaseLease:
    @pytest.mark.asyncio
    async def test_acquire_lease(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        r = await client.put("/cases/case-001/lease", json={"holder": "op-1", "expires_at": expires})
        assert r.status_code == 200
        assert r.json()["leased"] is True

        # Verify state changed
        case = await client.get("/cases/case-001")
        assert case.json()["state"] == "leased"
        assert case.json()["lease_holder"] == "op-1"

    @pytest.mark.asyncio
    async def test_lease_conflict_returns_409(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        await client.put("/cases/case-001/lease", json={"holder": "op-1", "expires_at": expires})
        r = await client.put("/cases/case-001/lease", json={"holder": "op-2", "expires_at": expires})
        assert r.status_code == 409
        assert r.json()["error"] == "lease_conflict"

    @pytest.mark.asyncio
    async def test_lease_on_nonexistent_returns_404(self, client):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        r = await client.put("/cases/nonexistent/lease", json={"holder": "op-1", "expires_at": future})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_lease_missing_fields_returns_422(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        r = await client.put("/cases/case-001/lease", json={"holder": "op-1"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_release_lease(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        await client.put("/cases/case-001/lease", json={"holder": "op-1", "expires_at": expires})
        r = await client.delete("/cases/case-001/lease")
        assert r.status_code == 200
        assert r.json()["released"] is True

        case = await client.get("/cases/case-001")
        assert case.json()["state"] == "pending"
        assert case.json()["lease_holder"] is None

    @pytest.mark.asyncio
    async def test_release_nonexistent_returns_404(self, client):
        r = await client.delete("/cases/nonexistent/lease")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_past_expires_at_returns_422(self, client):
        """Lease with expires_at in the past should be rejected."""
        await client.post("/cases", json=_case(priority="P1"))
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        r = await client.put("/cases/case-001/lease", json={"holder": "op-1", "expires_at": past})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_parameter"

    @pytest.mark.asyncio
    async def test_invalid_expires_at_returns_422(self, client):
        await client.post("/cases", json=_case(id="case-bad-ts", priority="P1"))
        r = await client.put("/cases/case-bad-ts/lease", json={"holder": "op-1", "expires_at": "not-a-date"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_expired_lease_shows_pending(self, client, store):
        """Case with expired lease should show state=pending when queried."""
        await client.post("/cases", json=_case(id="case-zombie", priority="P1"))
        # Directly set an expired lease in the store (bypassing API validation)
        store.acquire_lease("case-zombie", "op-1", (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        r = await client.get("/cases/case-zombie")
        assert r.json()["state"] == "pending"
        assert r.json()["lease_holder"] is None


# -- Case resolution --

class TestCaseResolve:
    @pytest.mark.asyncio
    async def test_resolve_case(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        r = await client.put("/cases/case-001/resolve", json={"resolution_id": "vrd-resolution-001"})
        assert r.status_code == 200
        assert r.json()["resolved"] is True

        case = await client.get("/cases/case-001")
        assert case.json()["state"] == "resolved"
        assert case.json()["resolution_id"] == "vrd-resolution-001"

    @pytest.mark.asyncio
    async def test_resolve_missing_returns_404(self, client):
        r = await client.put("/cases/nonexistent/resolve", json={"resolution_id": "vrd-001"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_missing_resolution_id_returns_422(self, client):
        await client.post("/cases", json=_case(priority="P1"))
        r = await client.put("/cases/case-001/resolve", json={})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_resolve_already_resolved_returns_409(self, client):
        await client.post("/cases", json=_case(id="case-re-resolve", priority="P1"))
        await client.put("/cases/case-re-resolve/resolve", json={"resolution_id": "vrd-res-1"})
        r = await client.put("/cases/case-re-resolve/resolve", json={"resolution_id": "vrd-res-2"})
        assert r.status_code == 409
        assert r.json()["error"] == "already_resolved"


# -- Change Freezes --

class TestChangeFreezes:
    @pytest.mark.asyncio
    async def test_create_freeze(self, client):
        r = await client.post("/change-freezes", json=_freeze())
        assert r.status_code == 201
        assert r.json()["name"] == "test-freeze"

    @pytest.mark.asyncio
    async def test_get_active_freezes(self, client):
        await client.post("/change-freezes", json=_freeze())
        r = await client.get("/change-freezes")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "test-freeze"

    @pytest.mark.asyncio
    async def test_expired_freeze_not_returned(self, client):
        now = datetime.now(timezone.utc)
        await client.post("/change-freezes", json=_freeze(
            name="old-freeze",
            active_from=(now - timedelta(hours=2)).isoformat(),
            active_until=(now - timedelta(hours=1)).isoformat(),
        ))
        r = await client.get("/change-freezes")
        assert len(r.json()) == 0

    @pytest.mark.asyncio
    async def test_lift_freeze(self, client):
        await client.post("/change-freezes", json=_freeze())
        r = await client.put("/change-freezes/test-freeze/lift", json={"lifted_by": "admin"})
        assert r.status_code == 200
        assert r.json()["lifted"] is True

        # No longer in active list
        active = await client.get("/change-freezes")
        assert len(active.json()) == 0

    @pytest.mark.asyncio
    async def test_missing_fields_returns_422(self, client):
        r = await client.post("/change-freezes", json={"name": "incomplete"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_lift_missing_lifted_by_returns_422(self, client):
        await client.post("/change-freezes", json=_freeze())
        r = await client.put("/change-freezes/test-freeze/lift", json={})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_inverted_range_returns_422(self, client):
        """Freeze with active_until before active_from should be rejected."""
        now = datetime.now(timezone.utc)
        r = await client.post("/change-freezes", json=_freeze(
            name="inverted",
            active_from=(now + timedelta(hours=1)).isoformat(),
            active_until=(now - timedelta(hours=1)).isoformat(),
        ))
        assert r.status_code == 422
        assert "active_until must be after active_from" in r.json()["detail"]["message"]

    @pytest.mark.asyncio
    async def test_duplicate_freeze_returns_409(self, client):
        await client.post("/change-freezes", json=_freeze())
        r = await client.post("/change-freezes", json=_freeze())
        assert r.status_code == 409
        assert r.json()["error"] == "duplicate"

    @pytest.mark.asyncio
    async def test_double_lift_returns_404(self, client):
        """Second lift of already-lifted freeze returns 404 (preserves audit trail)."""
        await client.post("/change-freezes", json=_freeze(name="lift-twice"))
        r1 = await client.put("/change-freezes/lift-twice/lift", json={"lifted_by": "admin-1"})
        assert r1.status_code == 200
        r2 = await client.put("/change-freezes/lift-twice/lift", json={"lifted_by": "admin-2"})
        assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_lift_nonexistent_returns_404(self, client):
        r = await client.put("/change-freezes/nonexistent/lift", json={"lifted_by": "admin"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_json_returns_422(self, client):
        r = await client.post(
            "/change-freezes",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422
