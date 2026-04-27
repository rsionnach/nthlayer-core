"""Tests for the unified core store."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from nthlayer.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


class TestSchema:
    """Verify all 8 tables + lineage + schema_meta exist."""

    EXPECTED_TABLES = [
        "verdicts",
        "assessments",
        "cases",
        "change_freezes",
        "heartbeats",
        "component_state",
        "suppressions",
        "rekor_anchors",
        "lineage",
        "schema_meta",
    ]

    def test_all_tables_created(self, store):
        for table in self.EXPECTED_TABLES:
            assert store.table_exists(table), f"Table {table} missing"

    def test_rekor_anchors_exists_empty(self, store):
        """v1.5 forward compat: rekor_anchors table exists but is empty."""
        conn = store._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM rekor_anchors").fetchone()[0]
        assert count == 0

    def test_schema_version(self, store):
        conn = store._get_conn()
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row["value"] == "1.5.0"

    def test_wal_mode(self, store):
        conn = store._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


class TestVerdicts:
    def _make_verdict(self, **overrides):
        now = datetime.now(timezone.utc).isoformat()
        base = {
            "id": f"vrd-test-{id(overrides):08x}",
            "type": "action_request",
            "service": "payment-api",
            "created_at": now,
            "pipeline_latency_ms": 100,
            "chain_depth": 0,
            "parent_ids": [],
            "content": "test verdict",
        }
        base.update(overrides)
        return base

    def test_put_and_get(self, store):
        v = self._make_verdict(id="vrd-test-001")
        store.put_verdict(v)
        result = store.get_verdict("vrd-test-001")
        assert result is not None
        assert result["id"] == "vrd-test-001"
        assert result["service"] == "payment-api"

    def test_get_missing_returns_none(self, store):
        assert store.get_verdict("nonexistent") is None

    def test_query_by_service(self, store):
        store.put_verdict(self._make_verdict(id="v1", service="fraud-detect"))
        store.put_verdict(self._make_verdict(id="v2", service="payment-api"))
        store.put_verdict(self._make_verdict(id="v3", service="fraud-detect"))
        results = store.query_verdicts(service="fraud-detect")
        assert len(results) == 2
        assert all(r["service"] == "fraud-detect" for r in results)

    def test_query_by_type(self, store):
        store.put_verdict(self._make_verdict(id="v1", type="action_request"))
        store.put_verdict(self._make_verdict(id="v2", type="quality_breach"))
        results = store.query_verdicts(verdict_type="quality_breach")
        assert len(results) == 1
        assert results[0]["type"] == "quality_breach"

    def test_query_limit(self, store):
        for i in range(10):
            store.put_verdict(self._make_verdict(id=f"v{i}"))
        results = store.query_verdicts(limit=3)
        assert len(results) == 3

    def test_query_by_date_range(self, store):
        store.put_verdict(self._make_verdict(id="v-old", created_at="2026-01-01T00:00:00Z"))
        store.put_verdict(self._make_verdict(id="v-mid", created_at="2026-06-01T00:00:00Z"))
        store.put_verdict(self._make_verdict(id="v-new", created_at="2026-12-01T00:00:00Z"))
        results = store.query_verdicts(created_after="2026-03-01T00:00:00Z", created_before="2026-09-01T00:00:00Z")
        assert len(results) == 1
        assert results[0]["id"] == "v-mid"

    def test_verdict_immutability(self, store):
        """Verdicts are immutable — duplicate ID raises IntegrityError."""
        v = self._make_verdict(id="vrd-immutable")
        store.put_verdict(v)
        with pytest.raises(Exception):
            store.put_verdict(v)


class TestLineage:
    def _make_verdict(self, vid, parent_ids=None):
        return {
            "id": vid,
            "type": "action_request",
            "service": "test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chain_depth": len(parent_ids or []),
            "parent_ids": parent_ids or [],
        }

    def test_direct_parent(self, store):
        store.put_verdict(self._make_verdict("A"))
        store.put_verdict(self._make_verdict("B", parent_ids=["A"]))
        ancestors = store.ancestors_of("B")
        assert len(ancestors) == 1
        assert ancestors[0]["id"] == "A"

    def test_transitive_closure(self, store):
        """A→B→C should give C ancestors [B, A]."""
        store.put_verdict(self._make_verdict("A"))
        store.put_verdict(self._make_verdict("B", parent_ids=["A"]))
        store.put_verdict(self._make_verdict("C", parent_ids=["B"]))
        ancestors = store.ancestors_of("C")
        assert len(ancestors) == 2
        ancestor_ids = [a["id"] for a in ancestors]
        assert "A" in ancestor_ids
        assert "B" in ancestor_ids

    def test_deep_chain(self, store):
        """Chain of 5: A→B→C→D→E."""
        store.put_verdict(self._make_verdict("A"))
        store.put_verdict(self._make_verdict("B", parent_ids=["A"]))
        store.put_verdict(self._make_verdict("C", parent_ids=["B"]))
        store.put_verdict(self._make_verdict("D", parent_ids=["C"]))
        store.put_verdict(self._make_verdict("E", parent_ids=["D"]))
        ancestors = store.ancestors_of("E")
        assert len(ancestors) == 4
        assert {a["id"] for a in ancestors} == {"A", "B", "C", "D"}

    def test_max_hops(self, store):
        store.put_verdict(self._make_verdict("A"))
        store.put_verdict(self._make_verdict("B", parent_ids=["A"]))
        store.put_verdict(self._make_verdict("C", parent_ids=["B"]))
        ancestors = store.ancestors_of("C", max_hops=1)
        assert len(ancestors) == 1
        assert ancestors[0]["id"] == "B"

    def test_descendants(self, store):
        store.put_verdict(self._make_verdict("A"))
        store.put_verdict(self._make_verdict("B", parent_ids=["A"]))
        store.put_verdict(self._make_verdict("C", parent_ids=["A"]))
        descendants = store.descendants_of("A")
        assert len(descendants) == 2
        assert {d["id"] for d in descendants} == {"B", "C"}

    def test_no_ancestors(self, store):
        store.put_verdict(self._make_verdict("A"))
        assert store.ancestors_of("A") == []

    def test_multiple_parents(self, store):
        """Verdict with two parents gets ancestors of both."""
        store.put_verdict(self._make_verdict("A"))
        store.put_verdict(self._make_verdict("B"))
        store.put_verdict(self._make_verdict("C", parent_ids=["A", "B"]))
        ancestors = store.ancestors_of("C")
        assert len(ancestors) == 2
        assert {a["id"] for a in ancestors} == {"A", "B"}

    def test_diamond_lineage_min_hop(self, store):
        """Diamond: Z→A, Z→B, A+B→C. C's hop to Z should be 2 (min), not 3."""
        store.put_verdict(self._make_verdict("Z"))
        store.put_verdict(self._make_verdict("A", parent_ids=["Z"]))
        store.put_verdict(self._make_verdict("B", parent_ids=["Z"]))
        store.put_verdict(self._make_verdict("C", parent_ids=["A", "B"]))
        # C has ancestors: A(1), B(1), Z(2 — min of A→Z+1=2, B→Z+1=2)
        ancestors = store.ancestors_of("C")
        assert len(ancestors) == 3
        assert {a["id"] for a in ancestors} == {"A", "B", "Z"}
        # max_hops=1 should get only direct parents
        direct = store.ancestors_of("C", max_hops=1)
        assert {a["id"] for a in direct} == {"A", "B"}
        # max_hops=2 should get Z too
        two_hops = store.ancestors_of("C", max_hops=2)
        assert {a["id"] for a in two_hops} == {"A", "B", "Z"}


class TestCases:
    def _make_case(self, **overrides):
        base = {
            "id": f"case-{id(overrides):08x}",
            "kind": "approval_required",
            "priority": "P1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "underlying_verdict": "vrd-test-001",
            "service": "payment-api",
            "briefing": "Test case",
        }
        base.update(overrides)
        return base

    def test_put_and_get(self, store):
        c = self._make_case(id="case-001")
        store.put_case(c)
        result = store.get_case("case-001")
        assert result is not None
        assert result["kind"] == "approval_required"
        assert result["state"] == "pending"

    def test_lease_acquisition(self, store):
        store.put_case(self._make_case(id="case-lease"))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        assert store.acquire_lease("case-lease", "operator-1", expires) is True
        result = store.get_case("case-lease")
        assert result["lease_holder"] == "operator-1"
        assert result["state"] == "leased"

    def test_concurrent_lease_one_wins(self, store):
        """Two concurrent lease attempts: exactly one succeeds."""
        store.put_case(self._make_case(id="case-race"))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

        results = []

        def try_lease(holder):
            results.append(store.acquire_lease("case-race", holder, expires))

        t1 = threading.Thread(target=try_lease, args=("op-1",))
        t2 = threading.Thread(target=try_lease, args=("op-2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results.count(True) == 1
        assert results.count(False) == 1

    def test_lease_expired_can_reacquire(self, store):
        store.put_case(self._make_case(id="case-expire"))
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        store.acquire_lease("case-expire", "op-1", past)
        # Lease expired, another operator can acquire
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        assert store.acquire_lease("case-expire", "op-2", future) is True

    def test_release_lease(self, store):
        store.put_case(self._make_case(id="case-release"))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        store.acquire_lease("case-release", "op-1", expires)
        store.release_lease("case-release")
        result = store.get_case("case-release")
        assert result["lease_holder"] is None
        assert result["state"] == "pending"

    def test_resolve_case(self, store):
        store.put_case(self._make_case(id="case-resolve"))
        store.resolve_case("case-resolve", "vrd-resolution-001")
        result = store.get_case("case-resolve")
        assert result["state"] == "resolved"
        assert result["resolution_id"] == "vrd-resolution-001"

    def test_query_by_priority(self, store):
        store.put_case(self._make_case(id="c1", priority="P0"))
        store.put_case(self._make_case(id="c2", priority="P2"))
        store.put_case(self._make_case(id="c3", priority="P0"))
        results = store.query_cases(priority="P0")
        assert len(results) == 2

    def test_release_nonexistent_is_noop(self, store):
        """Releasing a nonexistent case silently does nothing."""
        store.release_lease("nonexistent")  # should not raise

    def test_resolve_nonexistent_is_noop(self, store):
        """Resolving a nonexistent case silently does nothing."""
        store.resolve_case("nonexistent", "res-1")  # should not raise


class TestChangeFreezes:
    def _make_freeze(self, **overrides):
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

    def test_put_and_get_active(self, store):
        store.put_change_freeze(self._make_freeze())
        active = store.get_active_freezes()
        assert len(active) == 1
        assert active[0]["name"] == "test-freeze"

    def test_lift_freeze(self, store):
        store.put_change_freeze(self._make_freeze())
        store.lift_change_freeze("test-freeze", "admin")
        active = store.get_active_freezes()
        assert len(active) == 0


class TestHeartbeats:
    def test_put_and_get(self, store):
        store.put_heartbeat("workers", "instance-1", {"cycles": 42})
        beats = store.get_heartbeats()
        assert len(beats) == 1
        assert beats[0]["component"] == "workers"

    def test_upsert(self, store):
        store.put_heartbeat("workers", "i1", {"cycles": 1})
        store.put_heartbeat("workers", "i1", {"cycles": 2})
        beats = store.get_heartbeats()
        assert len(beats) == 1


class TestComponentState:
    def test_put_and_get(self, store):
        store.put_component_state("observe", {
            "last_cursor": "2026-04-22T00:00:00Z",
            "hysteresis_state": {"breach_count": 3},
            "dedup_cache": {"key1": "val1"},
        })
        state = store.get_component_state("observe")
        assert state is not None
        assert state["last_cursor"] == "2026-04-22T00:00:00Z"
        assert state["hysteresis_state"] == {"breach_count": 3}
        assert state["dedup_cache"] == {"key1": "val1"}

    def test_get_missing_returns_none(self, store):
        assert store.get_component_state("nonexistent") is None
