"""Unified SQLite store for nthlayer-core.

Implements the 8-table schema from NTHLAYER-SERVE-MODE-v2.1 §3.5,
adapted for v1.5 (string IDs instead of IPLD CIDs, JSON TEXT instead of CBOR BLOB).

The store is owned exclusively by the core process. Workers and bench
access it via the core's HTTP API — never directly.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nthlayer_common.verdicts.models import AccuracyReport, Outcome, Verdict
from nthlayer_common.verdicts.serialise import from_dict, to_dict
from nthlayer_common.verdicts.store import (
    AccuracyFilter,
    OutcomeStatusMismatch,
    VerdictFilter,
    VerdictStore,
)

SCHEMA_VERSION = "1.5.0"

_SCHEMA = """
-- Verdicts (v1.5: string IDs, JSON content)
CREATE TABLE IF NOT EXISTS verdicts (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    service TEXT,
    created_at TEXT NOT NULL,
    pipeline_latency_ms INTEGER,
    chain_depth INTEGER DEFAULT 0,
    parent_ids TEXT,
    content TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verdicts_service_created ON verdicts(service, created_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_type_created ON verdicts(type, created_at);

-- Assessments (component outputs that aren't decisions)
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assessments_service ON assessments(service, created_at);
CREATE INDEX IF NOT EXISTS idx_assessments_kind ON assessments(kind, created_at);

-- Cases (Bench domain model)
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    priority TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    underlying_verdict TEXT NOT NULL,
    service TEXT,
    briefing TEXT,
    lease_holder TEXT,
    lease_expires_at TEXT,
    resolution_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(state);
CREATE INDEX IF NOT EXISTS idx_cases_priority ON cases(priority, created_at);
CREATE INDEX IF NOT EXISTS idx_cases_service ON cases(service);

-- ChangeFreeze documents (RBAC §7)
CREATE TABLE IF NOT EXISTS change_freezes (
    name TEXT PRIMARY KEY,
    declared_by TEXT NOT NULL,
    declared_at TEXT NOT NULL,
    active_from TEXT NOT NULL,
    active_until TEXT NOT NULL,
    lifted_at TEXT,
    lifted_by TEXT,
    content TEXT NOT NULL
);

-- Heartbeats (component liveness)
CREATE TABLE IF NOT EXISTS heartbeats (
    component TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    state TEXT,
    PRIMARY KEY (component, instance_id)
);

-- Component state (persistent across restarts)
CREATE TABLE IF NOT EXISTS component_state (
    component TEXT PRIMARY KEY,
    last_cursor TEXT,
    hysteresis_state TEXT,
    dedup_cache TEXT
);

-- Suppression audit trail (CRUD deferred to P2-B.1; table created for forward compat)
CREATE TABLE IF NOT EXISTS suppressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suppressed_at TEXT NOT NULL,
    component TEXT NOT NULL,
    suppressed_verdict_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    related_verdict_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_suppressions_component ON suppressions(component, suppressed_at);

-- Rekor anchor log (empty in v1.5, forward-compatible for v2)
CREATE TABLE IF NOT EXISTS rekor_anchors (
    anchor_date TEXT PRIMARY KEY,
    merkle_root TEXT NOT NULL,
    rekor_log_index INTEGER,
    rekor_uuid TEXT,
    anchored_at TEXT NOT NULL
);

-- Lineage index (pre-computed transitive closure)
CREATE TABLE IF NOT EXISTS lineage (
    descendant_id TEXT NOT NULL,
    ancestor_id TEXT NOT NULL,
    hop_distance INTEGER NOT NULL,
    PRIMARY KEY (descendant_id, ancestor_id)
);

CREATE INDEX IF NOT EXISTS idx_lineage_ancestor ON lineage(ancestor_id);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store(VerdictStore):
    """Unified SQLite store for the core process.

    WAL mode, BEGIN IMMEDIATE for writes, connection pool via thread-local storage.

    Formally implements the VerdictStore ABC (opensrm-jmy.18 B0). The
    ``accuracy`` and ``expire`` methods raise NotImplementedError: Store's
    content-blob schema lacks the denormalised columns SQLiteVerdictStore
    requires. Schema unification is tracked in opensrm-jmy.20.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )

    @contextmanager
    def write_transaction(self):
        """Context manager for write transactions using BEGIN IMMEDIATE."""
        conn = self._get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # -- VerdictStore ABC implementation (opensrm-jmy.18 B0) --
    # These methods satisfy the VerdictStore interface used by
    # apply_override_to_verdict and other nthlayer-common callers.
    # They delegate to or wrap the existing dict-based verdict methods.

    def put(self, verdict: Verdict) -> None:
        """Implement VerdictStore.put: serialise Verdict and delegate to put_verdict."""
        self.put_verdict(to_dict(verdict))

    def get(self, verdict_id: str) -> Verdict | None:
        """Implement VerdictStore.get: read via get_verdict and deserialise."""
        d = self.get_verdict(verdict_id)
        if d is None:
            return None
        return from_dict(d)

    def query(self, criteria: VerdictFilter) -> list[Verdict]:
        """Implement VerdictStore.query: map VerdictFilter to query_verdicts kwargs.

        Field mapping:
        - ``subject_service`` → ``service`` (Store's denormalised top-level column)
        - ``subject_type`` → ``verdict_type`` (the ``type`` column)
        - ``from_time`` / ``to_time`` → ``created_after`` / ``created_before``
        - ``limit`` → ``limit``

        Unmapped VerdictFilter fields (producer_system, subject_agent, status, tags)
        are not filterable at the SQL layer against Store's content-blob schema;
        they are applied as a Python post-filter pass.
        """
        created_after: str | None = None
        created_before: str | None = None
        if criteria.from_time is not None:
            created_after = criteria.from_time.isoformat()
        if criteria.to_time is not None:
            created_before = criteria.to_time.isoformat()

        rows = self.query_verdicts(
            # subject_service is the denormalised service column in Store's schema
            service=criteria.subject_service,
            verdict_type=criteria.subject_type,
            created_after=created_after,
            created_before=created_before,
            limit=criteria.limit,
        )
        verdicts = [from_dict(r) for r in rows]

        # Python post-filter for fields not expressible as Store SQL predicates.
        if criteria.producer_system:
            verdicts = [v for v in verdicts if v.producer.system == criteria.producer_system]
        if criteria.subject_agent:
            verdicts = [v for v in verdicts if v.subject.agent == criteria.subject_agent]
        if criteria.status:
            verdicts = [v for v in verdicts if v.outcome.status == criteria.status]
        if criteria.tags:
            verdicts = [
                v for v in verdicts
                if v.judgment.tags and set(criteria.tags) & set(v.judgment.tags)
            ]

        return verdicts

    def update_outcome(
        self,
        verdict_id: str,
        outcome: Outcome,
        *,
        expected_status: str | None = None,
    ) -> Verdict:
        """Implement VerdictStore.update_outcome with CAS support.

        CAS via ``json_extract(content, '$.outcome.status')`` with IFNULL
        coalescing so that verdicts stored without an explicit outcome.status
        are treated as 'pending' (the dataclass default).
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT content FROM verdicts WHERE id = ?",
            (verdict_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Verdict {verdict_id} not found")

        # Deserialise the full content blob — get_verdict returns exactly
        # json.loads(row["content"]), which is what from_dict expects.
        content_dict = json.loads(row["content"])
        verdict = from_dict(content_dict)
        verdict.outcome = outcome

        new_content = json.dumps(to_dict(verdict))

        if expected_status is None:
            # Unconditional last-writer-wins (mirrors SQLiteVerdictStore).
            conn.execute(
                "UPDATE verdicts SET content = ? WHERE id = ?",
                (new_content, verdict_id),
            )
            conn.commit()
            return verdict

        # CAS path: cheap pre-check on the value we just read.
        current_outcome = content_dict.get("outcome") or {}
        current_status = current_outcome.get("status", "pending")
        if current_status != expected_status:
            raise OutcomeStatusMismatch(
                f"Verdict {verdict_id}: outcome.status is {current_status!r}, "
                f"expected {expected_status!r}"
            )

        # Conditional UPDATE: only succeeds if outcome.status still matches.
        # IFNULL coalesces absent outcome.status to 'pending' (dataclass default).
        cursor = conn.execute(
            "UPDATE verdicts SET content = ? "
            "WHERE id = ? "
            "AND IFNULL(json_extract(content, '$.outcome.status'), 'pending') "
            "= IFNULL(?, 'pending')",
            (new_content, verdict_id, expected_status),
        )
        conn.commit()
        if cursor.rowcount == 0:
            # CAS lost — a concurrent writer transitioned the verdict.
            after = conn.execute(
                "SELECT json_extract(content, '$.outcome.status') AS s "
                "FROM verdicts WHERE id = ?",
                (verdict_id,),
            ).fetchone()
            current = after["s"] if after else "<deleted>"
            raise OutcomeStatusMismatch(
                f"Verdict {verdict_id}: outcome.status raced to {current!r}, "
                f"expected {expected_status!r}"
            )
        return verdict

    def accuracy(self, criteria: AccuracyFilter) -> AccuracyReport:
        """Not implemented: Store's content-blob schema lacks the required columns.

        Use SQLiteVerdictStore for verdict accuracy reporting.
        Schema unification is tracked in opensrm-jmy.20.
        """
        raise NotImplementedError(
            "Store does not implement accuracy queries. "
            "Use SQLiteVerdictStore for verdict accuracy reporting. "
            "Schema unification is tracked in opensrm-jmy.20."
        )

    def by_lineage(self, verdict_id: str, direction: str = "both") -> list[Verdict]:
        """Implement VerdictStore.by_lineage: wrap ancestors_of / descendants_of."""
        if direction == "up":
            rows = self.ancestors_of(verdict_id)
        elif direction == "down":
            rows = self.descendants_of(verdict_id)
        elif direction == "both":
            rows = [*self.ancestors_of(verdict_id), *self.descendants_of(verdict_id)]
        else:
            raise ValueError(f"unknown direction {direction!r}")
        return [from_dict(r) for r in rows]

    def expire(self) -> int:
        """Not implemented: Store has run_retention with a different semantic.

        Use SQLiteVerdictStore for VerdictStore.expire semantics,
        or Store.run_retention for the core retention model.
        Schema unification is tracked in opensrm-jmy.20.
        """
        raise NotImplementedError(
            "Store does not implement TTL expiration. "
            "Use SQLiteVerdictStore for VerdictStore.expire semantics, "
            "or Store.run_retention for the core retention model. "
            "Schema unification is tracked in opensrm-jmy.20."
        )

    # -- Verdict operations --

    def put_verdict(self, verdict: dict[str, Any]) -> str:
        """Write a verdict and populate lineage index. Returns verdict ID."""
        vid = verdict["id"]
        parent_ids = verdict.get("parent_ids", [])

        with self.write_transaction() as conn:
            conn.execute(
                """INSERT INTO verdicts (id, type, service, created_at,
                   pipeline_latency_ms, chain_depth, parent_ids, content)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    vid,
                    verdict["type"],
                    verdict.get("service"),
                    verdict["created_at"],
                    verdict.get("pipeline_latency_ms"),
                    verdict.get("chain_depth", 0),
                    json.dumps(parent_ids) if parent_ids else "[]",
                    json.dumps(verdict),
                ),
            )
            self._populate_lineage(conn, vid, parent_ids)
        return vid

    def _populate_lineage(
        self, conn: sqlite3.Connection, descendant_id: str, parent_ids: list[str]
    ) -> None:
        """Incrementally extend the transitive closure of the lineage graph.

        For each parent, insert a direct relationship (hop=1), then copy
        that parent's ancestor rows with hop+1. Uses ON CONFLICT to keep
        the minimum hop distance when the same ancestor is reachable via
        multiple paths (diamond lineage).
        """
        for parent_id in parent_ids:
            # Direct parent relationship
            conn.execute(
                """INSERT INTO lineage (descendant_id, ancestor_id, hop_distance)
                   VALUES (?, ?, 1)
                   ON CONFLICT(descendant_id, ancestor_id)
                   DO UPDATE SET hop_distance = MIN(hop_distance, 1)""",
                (descendant_id, parent_id),
            )
            # Transitive ancestors: copy all ancestors of parent with hop+1
            conn.execute(
                """INSERT INTO lineage (descendant_id, ancestor_id, hop_distance)
                   SELECT ?, ancestor_id, hop_distance + 1
                   FROM lineage WHERE descendant_id = ?
                   ON CONFLICT(descendant_id, ancestor_id)
                   DO UPDATE SET hop_distance = MIN(lineage.hop_distance, excluded.hop_distance)""",
                (descendant_id, parent_id),
            )

    def get_verdict(self, verdict_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT content FROM verdicts WHERE id = ?", (verdict_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["content"])

    def query_verdicts(
        self,
        *,
        service: str | None = None,
        verdict_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[Any] = []

        if service is not None:
            clauses.append("service = ?")
            params.append(service)
        if verdict_type is not None:
            clauses.append("type = ?")
            params.append(verdict_type)
        if created_after is not None:
            clauses.append("created_at >= ?")
            params.append(self._normalise_timestamp(created_after))
        if created_before is not None:
            clauses.append("created_at <= ?")
            params.append(self._normalise_timestamp(created_before))

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT content FROM verdicts WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [json.loads(r["content"]) for r in rows]

    def ancestors_of(self, verdict_id: str, max_hops: int | None = None) -> list[dict[str, Any]]:
        conn = self._get_conn()
        if max_hops is not None:
            rows = conn.execute(
                """SELECT v.content FROM lineage l
                   JOIN verdicts v ON v.id = l.ancestor_id
                   WHERE l.descendant_id = ? AND l.hop_distance <= ?
                   ORDER BY l.hop_distance""",
                (verdict_id, max_hops),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT v.content FROM lineage l
                   JOIN verdicts v ON v.id = l.ancestor_id
                   WHERE l.descendant_id = ?
                   ORDER BY l.hop_distance""",
                (verdict_id,),
            ).fetchall()
        return [json.loads(r["content"]) for r in rows]

    def descendants_of(self, verdict_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT v.content FROM lineage l
               JOIN verdicts v ON v.id = l.descendant_id
               WHERE l.ancestor_id = ?
               ORDER BY l.hop_distance""",
            (verdict_id,),
        ).fetchall()
        return [json.loads(r["content"]) for r in rows]

    # -- Assessment operations --

    def put_assessment(self, assessment: dict[str, Any]) -> str:
        aid = assessment["id"]
        with self.write_transaction() as conn:
            conn.execute(
                """INSERT INTO assessments (id, service, kind, created_at, content)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    aid,
                    assessment["service"],
                    assessment["kind"],
                    assessment["created_at"],
                    json.dumps(assessment),
                ),
            )
        return aid

    def get_assessment(self, assessment_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT content FROM assessments WHERE id = ?", (assessment_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["content"])

    def query_assessments(
        self,
        *,
        service: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[Any] = []

        if service is not None:
            clauses.append("service = ?")
            params.append(service)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT content FROM assessments WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [json.loads(r["content"]) for r in rows]

    # -- Case operations --

    def put_case(self, case: dict[str, Any]) -> str:
        cid = case["id"]
        with self.write_transaction() as conn:
            conn.execute(
                """INSERT INTO cases (id, kind, priority, state, created_at,
                   underlying_verdict, service, briefing)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cid,
                    case["kind"],
                    case["priority"],
                    case.get("state", "pending"),
                    case["created_at"],
                    case["underlying_verdict"],
                    case.get("service"),
                    case.get("briefing"),
                ),
            )
        return cid

    def acquire_lease(self, case_id: str, holder: str, expires_at: str) -> bool:
        """Atomic lease acquisition. Returns True if lease acquired.

        A lease can be acquired if the case is pending (no holder) or if
        the existing lease has expired (lease_expires_at <= now).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.write_transaction() as conn:
            result = conn.execute(
                """UPDATE cases SET lease_holder = ?, lease_expires_at = ?, state = 'leased'
                   WHERE id = ? AND state IN ('pending', 'leased')
                   AND (lease_holder IS NULL OR lease_expires_at <= ?)""",
                (holder, expires_at, case_id, now),
            )
            return result.rowcount > 0

    def release_lease(self, case_id: str) -> bool:
        """Release a lease. Only releases if case is in 'leased' state. Returns True if released."""
        with self.write_transaction() as conn:
            result = conn.execute(
                "UPDATE cases SET lease_holder = NULL, lease_expires_at = NULL, state = 'pending' WHERE id = ? AND state = 'leased'",
                (case_id,),
            )
            return result.rowcount > 0

    def resolve_case(self, case_id: str, resolution_id: str) -> bool:
        """Resolve a case. Returns True if resolved, False if already resolved or not found."""
        with self.write_transaction() as conn:
            result = conn.execute(
                "UPDATE cases SET state = 'resolved', resolution_id = ?, lease_holder = NULL, lease_expires_at = NULL WHERE id = ? AND state != 'resolved'",
                (resolution_id, case_id),
            )
            return result.rowcount > 0

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        return self._apply_effective_state(result)

    @staticmethod
    def _apply_effective_state(case: dict[str, Any]) -> dict[str, Any]:
        """Compute effective state: expired leases revert to pending."""
        if case["state"] == "leased" and case.get("lease_expires_at"):
            now = datetime.now(timezone.utc).isoformat()
            if case["lease_expires_at"] <= now:
                case["state"] = "pending"
                case["lease_holder"] = None
                case["lease_expires_at"] = None
        return case

    def query_cases(
        self,
        *,
        state: str | None = None,
        priority: str | None = None,
        service: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[Any] = []

        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        if priority is not None:
            clauses.append("priority = ?")
            params.append(priority)
        if service is not None:
            clauses.append("service = ?")
            params.append(service)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM cases WHERE {where} ORDER BY priority, created_at LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [self._apply_effective_state(dict(r)) for r in rows]

    # -- Change freeze operations --

    def put_change_freeze(self, freeze: dict[str, Any]) -> str:
        with self.write_transaction() as conn:
            conn.execute(
                """INSERT INTO change_freezes
                   (name, declared_by, declared_at, active_from, active_until, content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    freeze["name"],
                    freeze["declared_by"],
                    freeze["declared_at"],
                    freeze["active_from"],
                    freeze["active_until"],
                    json.dumps(freeze),
                ),
            )
        return freeze["name"]

    def lift_change_freeze(self, name: str, lifted_by: str) -> bool:
        """Lift a change freeze. Returns True if freeze existed and was not already lifted."""
        now = datetime.now(timezone.utc).isoformat()
        with self.write_transaction() as conn:
            result = conn.execute(
                "UPDATE change_freezes SET lifted_at = ?, lifted_by = ? WHERE name = ? AND lifted_at IS NULL",
                (now, lifted_by, name),
            )
            return result.rowcount > 0

    def get_active_freezes(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT content FROM change_freezes
               WHERE active_from <= ? AND active_until >= ? AND lifted_at IS NULL""",
            (now, now),
        ).fetchall()
        return [json.loads(r["content"]) for r in rows]

    # -- Heartbeat operations --

    def put_heartbeat(self, component: str, instance_id: str, state: dict | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.write_transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO heartbeats (component, instance_id, last_seen, state)
                   VALUES (?, ?, ?, ?)""",
                (component, instance_id, now, json.dumps(state) if state else None),
            )

    def get_heartbeats(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM heartbeats").fetchall()
        return [dict(r) for r in rows]

    def get_heartbeats_with_health(self, degraded_threshold_seconds: int = 30) -> list[dict[str, Any]]:
        """Get heartbeats with computed health status.

        Components with last_seen older than degraded_threshold_seconds are marked degraded.
        """
        now = datetime.now(timezone.utc)
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM heartbeats").fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            last_seen = datetime.fromisoformat(entry["last_seen"])
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            age_seconds = (now - last_seen).total_seconds()
            entry["health"] = "healthy" if age_seconds <= degraded_threshold_seconds else "degraded"
            entry["age_seconds"] = round(age_seconds, 1)
            if entry.get("state"):
                entry["state"] = json.loads(entry["state"])
            results.append(entry)
        return results

    # -- Stuck action_request detection --

    def get_stuck_action_requests(self, threshold_seconds: int = 60) -> list[dict[str, Any]]:
        """Find action_request verdicts that have no corresponding case.

        An action_request is "stuck" if it was created more than threshold_seconds
        ago and no case references it as underlying_verdict.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)).isoformat()
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT v.content FROM verdicts v
               WHERE v.type = 'action_request'
               AND v.created_at <= ?
               AND NOT EXISTS (
                   SELECT 1 FROM cases c WHERE c.underlying_verdict = v.id
               )""",
            (cutoff,),
        ).fetchall()
        return [json.loads(r["content"]) for r in rows]

    # -- Suppression operations --

    def put_suppression(self, component: str, reason: str, suppressed_verdict_id: str,
                        related_verdict_id: str | None = None,
                        suppressed_at: str | None = None) -> int:
        """Record a suppressed verdict with reason."""
        if suppressed_at is None:
            suppressed_at = datetime.now(timezone.utc).isoformat()
        else:
            suppressed_at = self._normalise_timestamp(suppressed_at)
        with self.write_transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO suppressions (suppressed_at, component, suppressed_verdict_id, reason, related_verdict_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (suppressed_at, component, suppressed_verdict_id, reason, related_verdict_id),
            )
            return cursor.lastrowid

    @staticmethod
    def _normalise_timestamp(ts: str) -> str:
        """Normalise an ISO timestamp for consistent string comparison.

        Handles URL-decoded '+' (space) in timezone offsets: HTTP query
        strings decode '+' as space, so '2026-04-23T12:00:00+00:00'
        arrives as '2026-04-23T12:00:00 00:00'. We restore the '+' before
        parsing.
        """
        # Restore URL-decoded '+' → space in timezone offset (e.g. " 00:00" → "+00:00")
        ts = re.sub(r" (\d{2}:\d{2})$", r"+\1", ts)
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            return ts

    def query_suppressions(self, *, component: str | None = None,
                           created_after: str | None = None,
                           created_before: str | None = None,
                           limit: int = 100) -> list[dict[str, Any]]:
        """Query suppressions with optional filters."""
        conn = self._get_conn()
        conditions = []
        params: list[Any] = []

        if component:
            conditions.append("component = ?")
            params.append(component)
        if created_after:
            conditions.append("suppressed_at >= ?")
            params.append(self._normalise_timestamp(created_after))
        if created_before:
            conditions.append("suppressed_at <= ?")
            params.append(self._normalise_timestamp(created_before))

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM suppressions {where} ORDER BY suppressed_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Component state operations --

    def put_component_state(self, component: str, state: dict[str, Any]) -> None:
        with self.write_transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO component_state (component, last_cursor, hysteresis_state, dedup_cache)
                   VALUES (?, ?, ?, ?)""",
                (
                    component,
                    state.get("last_cursor"),
                    json.dumps(state.get("hysteresis_state")) if state.get("hysteresis_state") is not None else None,
                    json.dumps(state.get("dedup_cache")) if state.get("dedup_cache") is not None else None,
                ),
            )

    def get_component_state(self, component: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM component_state WHERE component = ?", (component,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("hysteresis_state"):
            result["hysteresis_state"] = json.loads(result["hysteresis_state"])
        if result.get("dedup_cache"):
            result["dedup_cache"] = json.loads(result["dedup_cache"])
        return result

    # -- Retention maintenance --

    # Default retention windows (days).
    # Excluded tables:
    #   lineage          — cleaned as side-effect of verdict deletion
    #   component_state  — config data, not time-series
    #   schema_meta      — internal bookkeeping
    #   rekor_anchors    — permanent audit trail, never pruned
    DEFAULT_RETENTION = {
        "verdicts": 365,
        "assessments": 90,
        "cases": 365,
        "change_freezes": 90,  # only lifted freezes pruned; active freezes always preserved
        "heartbeats": 1,
        "suppressions": 90,
    }

    def run_retention(self, retention: dict[str, int] | None = None) -> dict[str, int]:
        """Prune expired rows per retention policy. Returns count of deleted rows per table.

        Verdicts with younger descendants in the lineage table are NOT deleted
        (referential integrity). Only lifted change freezes are pruned; active
        freezes are always preserved. rekor_anchors are never pruned.
        """
        ret = retention or self.DEFAULT_RETENTION
        for table, days in ret.items():
            if days < 1:
                raise ValueError(f"Retention window for '{table}' must be >= 1 day, got {days}")
        now = datetime.now(timezone.utc)
        deleted: dict[str, int] = {}

        with self.write_transaction() as conn:
            # Verdicts: delete old rows that have NO younger descendants
            # AND are not referenced by any surviving case
            cutoff = (now - timedelta(days=ret.get("verdicts", 365))).isoformat()
            result = conn.execute(
                """DELETE FROM verdicts WHERE created_at < ?
                   AND NOT EXISTS (
                       SELECT 1 FROM lineage l
                       JOIN verdicts v2 ON v2.id = l.descendant_id
                       WHERE l.ancestor_id = verdicts.id AND v2.created_at >= ?
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM cases c WHERE c.underlying_verdict = verdicts.id
                   )""",
                (cutoff, cutoff),
            )
            deleted["verdicts"] = result.rowcount
            # Clean up orphaned lineage rows for deleted verdicts
            conn.execute(
                "DELETE FROM lineage WHERE NOT EXISTS (SELECT 1 FROM verdicts WHERE verdicts.id = lineage.descendant_id)"
            )
            conn.execute(
                "DELETE FROM lineage WHERE NOT EXISTS (SELECT 1 FROM verdicts WHERE verdicts.id = lineage.ancestor_id)"
            )

            # Assessments
            cutoff = (now - timedelta(days=ret.get("assessments", 90))).isoformat()
            result = conn.execute("DELETE FROM assessments WHERE created_at < ?", (cutoff,))
            deleted["assessments"] = result.rowcount

            # Cases
            cutoff = (now - timedelta(days=ret.get("cases", 365))).isoformat()
            result = conn.execute("DELETE FROM cases WHERE created_at < ?", (cutoff,))
            deleted["cases"] = result.rowcount

            # Change freezes: only lifted ones older than retention
            cutoff = (now - timedelta(days=ret.get("change_freezes", 90))).isoformat()
            result = conn.execute(
                "DELETE FROM change_freezes WHERE lifted_at IS NOT NULL AND lifted_at < ?",
                (cutoff,),
            )
            deleted["change_freezes"] = result.rowcount

            # Heartbeats
            cutoff = (now - timedelta(days=ret.get("heartbeats", 1))).isoformat()
            result = conn.execute("DELETE FROM heartbeats WHERE last_seen < ?", (cutoff,))
            deleted["heartbeats"] = result.rowcount

            # Suppressions
            cutoff = (now - timedelta(days=ret.get("suppressions", 90))).isoformat()
            result = conn.execute("DELETE FROM suppressions WHERE suppressed_at < ?", (cutoff,))
            deleted["suppressions"] = result.rowcount

            # rekor_anchors: NEVER pruned (permanent)

        return deleted

    # -- Table existence check --

    def table_exists(self, name: str) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
