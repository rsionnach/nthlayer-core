"""Tests for core HTTP API endpoints."""

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


def _verdict(vid="vrd-test-001", **overrides):
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "id": vid,
        "type": "action_request",
        "service": "payment-api",
        "created_at": now,
        "pipeline_latency_ms": 100,
        "chain_depth": 0,
        "parent_ids": [],
    }
    base.update(overrides)
    return base


def _assessment(aid="asm-test-001", **overrides):
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "id": aid,
        "service": "payment-api",
        "kind": "slo_status",
        "created_at": now,
        "data": {"status": "HEALTHY"},
    }
    base.update(overrides)
    return base


# -- Health --

class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# -- POST /verdicts --

class TestPostVerdict:
    @pytest.mark.asyncio
    async def test_create_verdict(self, client):
        r = await client.post("/verdicts", json=_verdict())
        assert r.status_code == 201
        assert r.json()["id"] == "vrd-test-001"

    @pytest.mark.asyncio
    async def test_missing_fields_returns_422(self, client):
        # Raw-dict path (no envelope) — opensrm-saun.1.2 contract:
        # error="verdict_invalid", envelope_version=None to distinguish
        # from envelope-level errors (which return 400 envelope_invalid).
        r = await client.post("/verdicts", json={"service": "test"})
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "verdict_invalid"
        assert body["envelope_version"] is None
        assert "id" in body["detail"]["fields"]
        assert "type" in body["detail"]["fields"]
        assert "created_at" in body["detail"]["fields"]

    @pytest.mark.asyncio
    async def test_duplicate_id_returns_409(self, client):
        await client.post("/verdicts", json=_verdict(vid="vrd-dup"))
        r = await client.post("/verdicts", json=_verdict(vid="vrd-dup"))
        assert r.status_code == 409
        assert r.json()["error"] == "duplicate"

    @pytest.mark.asyncio
    async def test_no_put_or_patch(self, client):
        """Verdicts are immutable — PUT and PATCH should return 405."""
        await client.post("/verdicts", json=_verdict())
        r_put = await client.put("/verdicts/vrd-test-001", json={"type": "modified"})
        r_patch = await client.patch("/verdicts/vrd-test-001", json={"type": "modified"})
        assert r_put.status_code == 405
        assert r_patch.status_code == 405

    @pytest.mark.asyncio
    async def test_invalid_json_returns_422(self, client):
        r = await client.post(
            "/verdicts",
            content=b"not valid json",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_json"


# -- GET /verdicts --

class TestGetVerdicts:
    @pytest.mark.asyncio
    async def test_get_single(self, client):
        await client.post("/verdicts", json=_verdict(vid="vrd-get"))
        r = await client.get("/verdicts/vrd-get")
        assert r.status_code == 200
        assert r.json()["id"] == "vrd-get"

    @pytest.mark.asyncio
    async def test_get_missing_returns_404(self, client):
        r = await client.get("/verdicts/nonexistent")
        assert r.status_code == 404
        assert r.json()["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_query_by_service(self, client):
        await client.post("/verdicts", json=_verdict(vid="v1", service="fraud-detect"))
        await client.post("/verdicts", json=_verdict(vid="v2", service="payment-api"))
        r = await client.get("/verdicts", params={"service": "fraud-detect"})
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["service"] == "fraud-detect"

    @pytest.mark.asyncio
    async def test_query_by_type(self, client):
        await client.post("/verdicts", json=_verdict(vid="v1", type="action_request"))
        await client.post("/verdicts", json=_verdict(vid="v2", type="quality_breach"))
        r = await client.get("/verdicts", params={"type": "quality_breach"})
        results = r.json()
        assert len(results) == 1
        assert results[0]["type"] == "quality_breach"

    @pytest.mark.asyncio
    async def test_query_with_limit(self, client):
        for i in range(5):
            await client.post("/verdicts", json=_verdict(vid=f"v{i}"))
        r = await client.get("/verdicts", params={"limit": "2"})
        assert len(r.json()) == 2

    @pytest.mark.asyncio
    async def test_invalid_limit_returns_422(self, client):
        r = await client.get("/verdicts", params={"limit": "abc"})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_parameter"

    @pytest.mark.asyncio
    async def test_negative_limit_returns_422(self, client):
        r = await client.get("/verdicts", params={"limit": "-1"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_time_range_filter_with_timezone_offset(self, client):
        """Timestamps with +00:00 must work despite URL-decoding '+' as space."""
        t1 = "2026-04-23T10:00:00+00:00"
        t2 = "2026-04-23T11:00:00+00:00"
        t3 = "2026-04-23T12:00:00+00:00"
        await client.post("/verdicts", json=_verdict("vrd-t1", created_at=t1))
        await client.post("/verdicts", json=_verdict("vrd-t2", created_at=t2))
        await client.post("/verdicts", json=_verdict("vrd-t3", created_at=t3))

        r = await client.get(f"/verdicts?created_after={t1}&created_before={t2}")
        assert r.status_code == 200
        assert len(r.json()) == 2


# -- Lineage --

class TestLineage:
    @pytest.mark.asyncio
    async def test_ancestors(self, client):
        await client.post("/verdicts", json=_verdict(vid="A"))
        await client.post("/verdicts", json=_verdict(vid="B", parent_ids=["A"]))
        await client.post("/verdicts", json=_verdict(vid="C", parent_ids=["B"]))

        r = await client.get("/verdicts/C/ancestors")
        assert r.status_code == 200
        ancestor_ids = [a["id"] for a in r.json()]
        assert "A" in ancestor_ids
        assert "B" in ancestor_ids

    @pytest.mark.asyncio
    async def test_ancestors_with_max_hops(self, client):
        await client.post("/verdicts", json=_verdict(vid="X"))
        await client.post("/verdicts", json=_verdict(vid="Y", parent_ids=["X"]))
        await client.post("/verdicts", json=_verdict(vid="Z", parent_ids=["Y"]))

        r = await client.get("/verdicts/Z/ancestors", params={"max_hops": "1"})
        ancestor_ids = [a["id"] for a in r.json()]
        assert "Y" in ancestor_ids
        assert "X" not in ancestor_ids

    @pytest.mark.asyncio
    async def test_descendants(self, client):
        await client.post("/verdicts", json=_verdict(vid="root"))
        await client.post("/verdicts", json=_verdict(vid="child1", parent_ids=["root"]))
        await client.post("/verdicts", json=_verdict(vid="child2", parent_ids=["root"]))

        r = await client.get("/verdicts/root/descendants")
        assert r.status_code == 200
        desc_ids = {d["id"] for d in r.json()}
        assert desc_ids == {"child1", "child2"}

    @pytest.mark.asyncio
    async def test_invalid_max_hops_returns_422(self, client):
        await client.post("/verdicts", json=_verdict(vid="mh"))
        r = await client.get("/verdicts/mh/ancestors", params={"max_hops": "abc"})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_parameter"


# -- Outcome resolution (immutable) --

class TestOutcomeResolution:
    @pytest.mark.asyncio
    async def test_creates_new_verdict(self, client):
        """Outcome resolution creates a NEW verdict, not mutation."""
        await client.post("/verdicts", json=_verdict(vid="orig"))

        r = await client.post(
            "/verdicts/orig/outcome",
            json={"outcome_status": "confirmed", "reasoning": "Verified correct"},
        )
        assert r.status_code == 201
        outcome_id = r.json()["id"]

        # Original unchanged
        orig = await client.get("/verdicts/orig")
        assert orig.json()["id"] == "orig"
        assert orig.json()["type"] == "action_request"

        # New outcome verdict exists
        outcome = await client.get(f"/verdicts/{outcome_id}")
        assert outcome.status_code == 200
        assert outcome.json()["type"] == "outcome_resolution"
        assert outcome.json()["parent_ids"] == ["orig"]

    @pytest.mark.asyncio
    async def test_outcome_on_missing_returns_404(self, client):
        r = await client.post(
            "/verdicts/nonexistent/outcome",
            json={"outcome_status": "confirmed"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_outcome_appears_in_descendants(self, client):
        """The outcome verdict is a descendant of the original."""
        await client.post("/verdicts", json=_verdict(vid="target"))
        await client.post(
            "/verdicts/target/outcome",
            json={"outcome_status": "confirmed"},
        )
        r = await client.get("/verdicts/target/descendants")
        descs = r.json()
        assert len(descs) == 1
        assert descs[0]["type"] == "outcome_resolution"

    @pytest.mark.asyncio
    async def test_duplicate_outcome_returns_409(self, client):
        """Second outcome with same default ID returns 409."""
        await client.post("/verdicts", json=_verdict(vid="dup-target"))
        r1 = await client.post("/verdicts/dup-target/outcome", json={"outcome_status": "confirmed"})
        assert r1.status_code == 201
        r2 = await client.post("/verdicts/dup-target/outcome", json={"outcome_status": "overridden"})
        assert r2.status_code == 409
        assert r2.json()["error"] == "duplicate"


# -- POST /verdicts CloudEvents envelope contract (opensrm-saun.1.2) --

def _envelope(record: dict, *, ce_type: str = "io.nthlayer.verdict.action_request.v1") -> dict:
    """Build a minimal valid CloudEvents v1.0 envelope around a record."""
    return {
        "specversion": "1.0",
        "type": ce_type,
        "source": "urn:nthlayer:test:default",
        "id": record.get("id", "vrd-env-1"),
        "time": record.get("created_at", "2026-05-02T00:00:00Z"),
        "datacontenttype": "application/json",
        "data": record,
    }


class TestPostVerdictEnvelope:
    """Auto-detect contract: top-level ``specversion`` triggers unwrap."""

    @pytest.mark.asyncio
    async def test_envelope_unwrap_succeeds(self, client):
        r = await client.post("/verdicts", json=_envelope(_verdict(vid="vrd-env-ok")))
        assert r.status_code == 201
        assert r.json()["id"] == "vrd-env-ok"

    @pytest.mark.asyncio
    async def test_envelope_missing_specversion_falls_back_to_raw(self, client):
        # Without specversion the body is treated as a raw record. A raw
        # body that happens to look envelope-shaped (has type+source+id but
        # no specversion) goes through the raw validator, which finds the
        # record's required fields and either passes or 422s.
        env = _envelope(_verdict(vid="vrd-fallback-raw"))
        del env["specversion"]
        r = await client.post("/verdicts", json=env)
        # The raw record is the envelope dict itself, which lacks a
        # "created_at" key (envelope uses "time"). Expect 422 verdict_invalid.
        assert r.status_code == 422
        assert r.json()["error"] == "verdict_invalid"
        assert r.json()["envelope_version"] is None

    @pytest.mark.asyncio
    async def test_envelope_missing_required_attr_returns_400(self, client):
        env = _envelope(_verdict())
        del env["source"]
        r = await client.post("/verdicts", json=env)
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "envelope_invalid"
        assert body["envelope_version"] is None
        assert "source" in body["detail"]

    @pytest.mark.asyncio
    async def test_envelope_wrong_specversion_returns_400(self, client):
        env = _envelope(_verdict())
        env["specversion"] = "0.3"
        r = await client.post("/verdicts", json=env)
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "envelope_invalid"
        assert "0.3" in body["detail"]
        assert body["envelope_version"] is None

    @pytest.mark.asyncio
    async def test_envelope_non_dict_data_returns_400(self, client):
        env = _envelope(_verdict())
        env["data"] = "not-a-dict"
        r = await client.post("/verdicts", json=env)
        assert r.status_code == 400
        assert r.json()["error"] == "envelope_invalid"

    @pytest.mark.asyncio
    async def test_envelope_inner_record_invalid_returns_422(self, client):
        # Envelope unwraps successfully, but inner record is missing
        # required verdict fields. Distinguishable from envelope_invalid
        # via envelope_version="1.0".
        env = _envelope({"id": "vrd-inner-bad"})
        r = await client.post("/verdicts", json=env)
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "verdict_invalid"
        assert body["envelope_version"] == "1.0"


# -- POST /assessments --

class TestAssessments:
    @pytest.mark.asyncio
    async def test_create_assessment(self, client):
        r = await client.post("/assessments", json=_assessment())
        assert r.status_code == 201
        assert r.json()["id"] == "asm-test-001"

    @pytest.mark.asyncio
    async def test_missing_fields_returns_422(self, client):
        r = await client.post("/assessments", json={"data": "test"})
        assert r.status_code == 422
        assert "service" in r.json()["detail"]["fields"]

    @pytest.mark.asyncio
    async def test_query_by_kind(self, client):
        await client.post("/assessments", json=_assessment(aid="a1", kind="slo_status"))
        await client.post("/assessments", json=_assessment(aid="a2", kind="judgment_slo_evaluation"))
        r = await client.get("/assessments", params={"kind": "slo_status"})
        results = r.json()
        assert len(results) == 1
        assert results[0]["kind"] == "slo_status"

    @pytest.mark.asyncio
    async def test_query_by_service(self, client):
        await client.post("/assessments", json=_assessment(aid="a1", service="fraud-detect"))
        await client.post("/assessments", json=_assessment(aid="a2", service="payment-api"))
        r = await client.get("/assessments", params={"service": "fraud-detect"})
        assert len(r.json()) == 1
