"""opensrm-jmy.18 B0: Store implements VerdictStore ABC."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nthlayer_common.verdicts.models import (
    Judgment,
    Outcome,
    Producer,
    Subject,
    Verdict,
)
from nthlayer_common.verdicts.store import (
    AccuracyFilter,
    OutcomeStatusMismatch,
    VerdictFilter,
    VerdictStore,
)
from nthlayer_core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "test.db"))
    yield s
    s.close()


def _build_pending(vid: str = "dec-1", service: str = "fraud-detect") -> Verdict:
    """Construct a minimal pending Verdict."""
    return Verdict(
        id=vid,
        version=1,
        timestamp=datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc),
        producer=Producer(system="fraud-detect"),
        subject=Subject(
            type="agent_output",
            ref="fraud-detect",
            summary="test verdict",
            service=service,
        ),
        judgment=Judgment(action="approve", confidence=0.9),
        outcome=Outcome(status="pending"),
        service=service,
        verdict_type="action_request",
    )


class TestStoreIsVerdictStore:
    def test_store_inherits_verdictstore(self):
        assert issubclass(Store, VerdictStore)

    def test_store_instance_is_verdictstore(self, store):
        assert isinstance(store, VerdictStore)


class TestPutAndGet:
    def test_put_then_get_roundtrips(self, store):
        v = _build_pending("rt-1")
        store.put(v)
        got = store.get("rt-1")
        assert got is not None
        assert got.id == "rt-1"
        assert got.outcome.status == "pending"
        assert got.service == "fraud-detect"
        assert got.verdict_type == "action_request"

    def test_get_missing_returns_none(self, store):
        assert store.get("does-not-exist") is None

    def test_put_then_get_judgment_preserved(self, store):
        v = _build_pending("rt-2")
        store.put(v)
        got = store.get("rt-2")
        assert got.judgment.action == "approve"
        assert got.judgment.confidence == pytest.approx(0.9)

    def test_put_then_get_producer_preserved(self, store):
        v = _build_pending("rt-3")
        store.put(v)
        got = store.get("rt-3")
        assert got.producer.system == "fraud-detect"


class TestUpdateOutcomeUnconditional:
    def test_update_outcome_without_expected_status_overwrites(self, store):
        v = _build_pending("uo-1")
        store.put(v)
        new_outcome = Outcome(status="confirmed")
        result = store.update_outcome("uo-1", new_outcome)
        assert result.outcome.status == "confirmed"
        # Verify persisted
        assert store.get("uo-1").outcome.status == "confirmed"

    def test_update_outcome_unknown_id_raises_keyerror(self, store):
        with pytest.raises(KeyError):
            store.update_outcome("missing", Outcome(status="confirmed"))

    def test_update_outcome_returns_verdict(self, store):
        v = _build_pending("uo-2")
        store.put(v)
        result = store.update_outcome("uo-2", Outcome(status="overridden"))
        assert isinstance(result, Verdict)
        assert result.id == "uo-2"


class TestUpdateOutcomeCAS:
    def test_cas_succeeds_when_expected_matches(self, store):
        v = _build_pending("cas-1")
        store.put(v)
        new_outcome = Outcome(status="overridden")
        result = store.update_outcome("cas-1", new_outcome, expected_status="pending")
        assert result.outcome.status == "overridden"
        # Verify persisted
        assert store.get("cas-1").outcome.status == "overridden"

    def test_cas_raises_on_status_mismatch_pre_check(self, store):
        """Pre-check: expected_status does not match the current status."""
        v = _build_pending("cas-2")
        store.put(v)
        # Unconditionally transition to confirmed first
        store.update_outcome("cas-2", Outcome(status="confirmed"))
        # Now expect "pending" — should raise because status is "confirmed"
        with pytest.raises(OutcomeStatusMismatch):
            store.update_outcome("cas-2", Outcome(status="overridden"), expected_status="pending")

    def test_cas_raises_on_concurrent_race(self, store):
        """Race scenario: first writer wins, second CAS fails."""
        v = _build_pending("cas-3")
        store.put(v)
        # First writer transitions to "confirmed"
        store.update_outcome("cas-3", Outcome(status="confirmed"))
        # Second writer expected "pending" (stale read scenario)
        with pytest.raises(OutcomeStatusMismatch):
            store.update_outcome("cas-3", Outcome(status="overridden"), expected_status="pending")


class TestQuery:
    def test_query_returns_verdict_dataclasses(self, store):
        v = _build_pending("q-1", service="svc-a")
        store.put(v)
        f = VerdictFilter(subject_service="svc-a")
        results = store.query(f)
        assert len(results) >= 1
        assert all(isinstance(r, Verdict) for r in results)

    def test_query_filters_by_service(self, store):
        store.put(_build_pending("q-2", service="svc-alpha"))
        store.put(_build_pending("q-3", service="svc-beta"))
        results = store.query(VerdictFilter(subject_service="svc-alpha"))
        ids = {v.id for v in results}
        assert "q-2" in ids
        assert "q-3" not in ids

    def test_query_empty_result(self, store):
        results = store.query(VerdictFilter(subject_service="nonexistent-svc"))
        assert results == []

    def test_query_limit_respected(self, store):
        for i in range(5):
            store.put(_build_pending(f"ql-{i}", service="svc-limit"))
        results = store.query(VerdictFilter(subject_service="svc-limit", limit=3))
        assert len(results) == 3


class TestByLineage:
    def test_by_lineage_returns_list(self, store):
        v = _build_pending("ln-1")
        store.put(v)
        results = store.by_lineage("ln-1", direction="both")
        assert isinstance(results, list)

    def test_by_lineage_all_items_are_verdicts(self, store):
        v = _build_pending("ln-2")
        store.put(v)
        results = store.by_lineage("ln-2", direction="both")
        assert all(isinstance(r, Verdict) for r in results)

    def test_by_lineage_unknown_direction_raises(self, store):
        v = _build_pending("ln-3")
        store.put(v)
        with pytest.raises(ValueError):
            store.by_lineage("ln-3", direction="sideways")

    def test_by_lineage_up_direction(self, store):
        v = _build_pending("ln-4")
        store.put(v)
        # No ancestors; should return empty list
        results = store.by_lineage("ln-4", direction="up")
        assert results == []

    def test_by_lineage_down_direction(self, store):
        v = _build_pending("ln-5")
        store.put(v)
        # No descendants; should return empty list
        results = store.by_lineage("ln-5", direction="down")
        assert results == []


class TestUnimplementedSemantics:
    def test_accuracy_raises_notimplementederror(self, store):
        with pytest.raises(NotImplementedError, match="opensrm-jmy.20"):
            store.accuracy(AccuracyFilter(producer_system="anything"))

    def test_expire_raises_notimplementederror(self, store):
        with pytest.raises(NotImplementedError, match="opensrm-jmy.20"):
            store.expire()


class TestAppliesWithApplyOverrideToVerdict:
    """End-to-end: apply_override_to_verdict works against real Store."""

    def test_apply_override_to_verdict_works_on_store(self, store):
        from nthlayer_common.overrides import (
            OverrideEvent,
            OverridePrivacyConfig,
            apply_override_to_verdict,
        )

        v = _build_pending("ovr-1")
        store.put(v)

        event = OverrideEvent(
            decision_id="ovr-1",
            service="fraud-detect",
            corrected_action="approve",
            reviewer="reviewer-hash",
        )
        result = apply_override_to_verdict(
            store, event, privacy=OverridePrivacyConfig(pre_redacted=True),
        )
        assert result is not None
        assert result.outcome.status == "overridden"
        assert result.outcome.override.by == "reviewer-hash"

        # Verify persisted in DB by reading back fresh.
        got = store.get("ovr-1")
        assert got is not None
        assert got.outcome.status == "overridden"
        assert got.outcome.override.by == "reviewer-hash"

    def test_apply_override_idempotent_on_store(self, store):
        """Idempotent re-apply returns the same verdict without error."""
        from nthlayer_common.overrides import (
            OverrideEvent,
            OverridePrivacyConfig,
            apply_override_to_verdict,
        )

        v = _build_pending("ovr-2")
        store.put(v)
        event = OverrideEvent(
            decision_id="ovr-2",
            service="fraud-detect",
            corrected_action="approve",
            reviewer="reviewer-hash",
        )
        privacy = OverridePrivacyConfig(pre_redacted=True)
        r1 = apply_override_to_verdict(store, event, privacy=privacy)
        r2 = apply_override_to_verdict(store, event, privacy=privacy)
        assert r1 is not None
        assert r2 is not None
        assert r2.outcome.status == "overridden"
