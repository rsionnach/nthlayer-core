"""opensrm-jmy.18: POST /verdicts/{id}/override handler tests."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from httpx import ASGITransport

from nthlayer_common.verdicts.models import (
    Judgment,
    Outcome,
    Producer,
    Subject,
    Verdict,
)
from nthlayer_common.verdicts.store import MemoryStore
from nthlayer_core import server


def _make_verdict(vid: str, *, outcome_status: str = "pending") -> Verdict:
    """Build a Verdict dataclass for seeding into MemoryStore."""
    return Verdict(
        id=vid,
        version=1,
        timestamp=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
        producer=Producer(system="fraud-detect"),
        subject=Subject(
            type="agent_output",
            ref="fraud-detect",
            summary="test",
            service="fraud-detect",
        ),
        judgment=Judgment(action="approve", confidence=0.9),
        outcome=Outcome(status=outcome_status),
        service="fraud-detect",
    )


def _seed_pending(store: MemoryStore, vid: str) -> None:
    """Place a pending Verdict in the store keyed by vid."""
    store.put(_make_verdict(vid, outcome_status="pending"))


def _build_confirmed_verdict(vid: str) -> Verdict:
    """Build a confirmed Verdict (terminal — cannot be overridden)."""
    return _make_verdict(vid, outcome_status="confirmed")


def _body(decision_id: str = "dec-1", **overrides) -> dict:
    body = {
        "decision_id": decision_id,
        "service": "fraud-detect",
        "corrected_action": "approve",
        "reviewer": "reviewer-hash",
        "timestamp": "2026-05-20T10:33:00+00:00",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_override_happy_path_returns_200_and_mutates_outcome():
    store = MemoryStore()
    _seed_pending(store, "dec-1")
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/verdicts/dec-1/override", json=_body())

    assert resp.status_code == 200
    assert resp.json()["status"] == "overridden"
    v = store.get("dec-1")
    assert v.outcome.status == "overridden"
    assert v.outcome.override.by == "reviewer-hash"  # pre_redacted=True; no re-hash

    server.set_store(None)


@pytest.mark.asyncio
async def test_override_idempotent_reapply_returns_200():
    store = MemoryStore()
    _seed_pending(store, "dec-2")
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post("/verdicts/dec-2/override", json=_body("dec-2"))
        r2 = await client.post("/verdicts/dec-2/override", json=_body("dec-2"))

    assert r1.status_code == 200
    assert r2.status_code == 200

    server.set_store(None)


@pytest.mark.asyncio
async def test_override_verdict_not_found_returns_404():
    store = MemoryStore()
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/verdicts/dec-missing/override", json=_body("dec-missing"))

    assert resp.status_code == 404
    assert resp.json()["error"] == "verdict_not_found"

    server.set_store(None)


@pytest.mark.asyncio
async def test_override_decision_id_mismatch_returns_400():
    store = MemoryStore()
    _seed_pending(store, "dec-real")
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/verdicts/dec-real/override", json=_body("dec-different"))

    assert resp.status_code == 400
    assert resp.json()["error"] == "decision_id_mismatch"

    server.set_store(None)


@pytest.mark.asyncio
async def test_override_schema_failure_returns_422():
    store = MemoryStore()
    _seed_pending(store, "dec-3")
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bad = {
            "decision_id": "dec-3",
            "service": "fraud-detect",
            "reviewer": "h",
            "timestamp": "2026-05-20T10:33:00+00:00",
        }  # missing corrected_action
        resp = await client.post("/verdicts/dec-3/override", json=bad)

    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"

    server.set_store(None)


@pytest.mark.asyncio
async def test_override_conflict_with_existing_returns_409():
    store = MemoryStore()
    _seed_pending(store, "dec-4")
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post("/verdicts/dec-4/override", json=_body("dec-4", reviewer="alice"))
        r2 = await client.post("/verdicts/dec-4/override", json=_body("dec-4", reviewer="bob"))

    assert r1.status_code == 200
    assert r2.status_code == 409
    assert r2.json()["error"] == "conflict"

    server.set_store(None)


@pytest.mark.asyncio
async def test_override_terminal_status_returns_422():
    """A confirmed verdict cannot be overridden."""
    store = MemoryStore()
    v = _build_confirmed_verdict("dec-5")
    store.put(v)
    server.set_store(store)

    transport = ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/verdicts/dec-5/override", json=_body("dec-5"))

    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"

    server.set_store(None)
