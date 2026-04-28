"""Tests for retention maintenance job."""

from datetime import datetime, timedelta, timezone

import pytest

from nthlayer_core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def _ts(days_ago: int) -> str:
    """ISO timestamp N days in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _verdict(store, vid, days_ago=0, parent_ids=None):
    store.put_verdict({
        "id": vid,
        "type": "action_request",
        "service": "test",
        "created_at": _ts(days_ago),
        "parent_ids": parent_ids or [],
    })


class TestVerdictRetention:
    def test_old_verdicts_deleted(self, store):
        _verdict(store, "v-old", days_ago=400)
        _verdict(store, "v-new", days_ago=10)
        deleted = store.run_retention()
        assert deleted["verdicts"] == 1
        assert store.get_verdict("v-old") is None
        assert store.get_verdict("v-new") is not None

    def test_verdict_with_young_descendant_preserved(self, store):
        """Old verdict that has a younger descendant should NOT be deleted."""
        _verdict(store, "v-ancestor", days_ago=400)
        _verdict(store, "v-descendant", days_ago=10, parent_ids=["v-ancestor"])
        deleted = store.run_retention()
        # v-ancestor is old but has a young descendant — preserved
        assert deleted["verdicts"] == 0
        assert store.get_verdict("v-ancestor") is not None

    def test_orphaned_lineage_cleaned_up(self, store):
        """Lineage rows for deleted verdicts should be cleaned up."""
        _verdict(store, "v-a", days_ago=400)
        _verdict(store, "v-b", days_ago=400, parent_ids=["v-a"])
        # Both old, no young descendants — both deleted
        deleted = store.run_retention()
        assert deleted["verdicts"] == 2
        # Lineage rows should be gone too
        assert store.ancestors_of("v-b") == []
        assert store.descendants_of("v-a") == []

    def test_custom_retention_window(self, store):
        _verdict(store, "v-30d", days_ago=30)
        _verdict(store, "v-5d", days_ago=5)
        deleted = store.run_retention({"verdicts": 10})
        assert deleted["verdicts"] == 1
        assert store.get_verdict("v-30d") is None
        assert store.get_verdict("v-5d") is not None

    def test_verdict_referenced_by_case_preserved(self, store):
        """Old verdict that is underlying_verdict of a live case should NOT be deleted."""
        _verdict(store, "v-case-ref", days_ago=400)
        store.put_case({
            "id": "case-ref", "kind": "approval_required", "priority": "P1",
            "created_at": _ts(10), "underlying_verdict": "v-case-ref",
        })
        deleted = store.run_retention()
        assert deleted["verdicts"] == 0
        assert store.get_verdict("v-case-ref") is not None

    def test_verdict_inside_window_preserved(self, store):
        """Verdict just inside the retention window is preserved."""
        _verdict(store, "v-inside", days_ago=364)  # 1 day inside 365d window
        _verdict(store, "v-outside", days_ago=366)  # 1 day outside
        deleted = store.run_retention()
        assert deleted["verdicts"] == 1
        assert store.get_verdict("v-inside") is not None
        assert store.get_verdict("v-outside") is None


class TestAssessmentRetention:
    def test_old_assessments_deleted(self, store):
        store.put_assessment({
            "id": "asm-old", "service": "test", "kind": "slo_status",
            "created_at": _ts(100),
        })
        store.put_assessment({
            "id": "asm-new", "service": "test", "kind": "slo_status",
            "created_at": _ts(10),
        })
        deleted = store.run_retention()
        assert deleted["assessments"] == 1
        assert store.get_assessment("asm-old") is None
        assert store.get_assessment("asm-new") is not None


class TestCaseRetention:
    def test_old_cases_deleted(self, store):
        store.put_case({
            "id": "case-old", "kind": "approval_required", "priority": "P1",
            "created_at": _ts(400), "underlying_verdict": "vrd-1",
        })
        store.put_case({
            "id": "case-new", "kind": "approval_required", "priority": "P1",
            "created_at": _ts(10), "underlying_verdict": "vrd-2",
        })
        deleted = store.run_retention()
        assert deleted["cases"] == 1
        assert store.get_case("case-old") is None
        assert store.get_case("case-new") is not None


class TestChangeFreezeRetention:
    def test_active_freeze_not_deleted(self, store):
        """Active (not lifted) freezes are never deleted by retention."""
        now = datetime.now(timezone.utc)
        store.put_change_freeze({
            "name": "active-freeze",
            "declared_by": "admin",
            "declared_at": _ts(200),
            "active_from": (now - timedelta(days=200)).isoformat(),
            "active_until": (now + timedelta(days=100)).isoformat(),
        })
        deleted = store.run_retention()
        assert deleted["change_freezes"] == 0

    def test_lifted_freeze_deleted_after_retention(self, store):
        now = datetime.now(timezone.utc)
        store.put_change_freeze({
            "name": "old-lifted",
            "declared_by": "admin",
            "declared_at": _ts(200),
            "active_from": (now - timedelta(days=200)).isoformat(),
            "active_until": (now - timedelta(days=150)).isoformat(),
        })
        store.lift_change_freeze("old-lifted", "admin")
        # Manually backdate the lifted_at
        conn = store._get_conn()
        conn.execute(
            "UPDATE change_freezes SET lifted_at = ? WHERE name = ?",
            (_ts(100), "old-lifted"),
        )
        deleted = store.run_retention()
        assert deleted["change_freezes"] == 1

    def test_recently_lifted_freeze_preserved(self, store):
        now = datetime.now(timezone.utc)
        store.put_change_freeze({
            "name": "recent-lifted",
            "declared_by": "admin",
            "declared_at": _ts(10),
            "active_from": (now - timedelta(days=10)).isoformat(),
            "active_until": (now - timedelta(days=5)).isoformat(),
        })
        store.lift_change_freeze("recent-lifted", "admin")
        deleted = store.run_retention()
        assert deleted["change_freezes"] == 0


class TestHeartbeatRetention:
    def test_old_heartbeats_deleted(self, store):
        store.put_heartbeat("workers", "i-1")
        # Backdate one heartbeat
        conn = store._get_conn()
        conn.execute(
            "UPDATE heartbeats SET last_seen = ? WHERE instance_id = ?",
            (_ts(2), "i-1"),
        )
        store.put_heartbeat("workers", "i-2")
        deleted = store.run_retention()
        assert deleted["heartbeats"] == 1


class TestRekorAnchorsNeverPruned:
    def test_rekor_anchors_not_touched(self, store):
        """rekor_anchors table is never pruned, even if entries are very old."""
        conn = store._get_conn()
        conn.execute(
            "INSERT INTO rekor_anchors (anchor_date, merkle_root, anchored_at) VALUES (?, ?, ?)",
            ("2020-01-01", "abc123", _ts(2000)),
        )
        deleted = store.run_retention()
        assert "rekor_anchors" not in deleted
        row = conn.execute("SELECT COUNT(*) FROM rekor_anchors").fetchone()
        assert row[0] == 1


class TestRetentionGuards:
    def test_zero_day_retention_rejected(self, store):
        with pytest.raises(ValueError, match="must be >= 1 day"):
            store.run_retention({"verdicts": 0})

    def test_negative_retention_rejected(self, store):
        with pytest.raises(ValueError, match="must be >= 1 day"):
            store.run_retention({"assessments": -1})


class TestRetentionReturnsCorrectCounts:
    def test_empty_store_returns_zeros(self, store):
        deleted = store.run_retention()
        assert all(v == 0 for v in deleted.values())
        assert set(deleted.keys()) == {
            "verdicts", "assessments", "cases",
            "change_freezes", "heartbeats", "suppressions",
        }
