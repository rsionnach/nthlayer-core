"""Tests for manifest catalogue API endpoints."""

import time

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from nthlayer_core.catalogue import ManifestCatalogue
from nthlayer_core.server import app, set_catalogue, set_store
from nthlayer_core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    set_store(s)
    yield s
    s.close()
    set_store(None)


@pytest.fixture
def specs_dir(tmp_path):
    d = tmp_path / "specs"
    d.mkdir()
    return d


def _write_v1_spec(specs_dir, name, team="payments", tier="critical", svc_type="api", slos=None):
    """Write a minimal srm/v1 spec file."""
    spec = {
        "apiVersion": "srm/v1",
        "kind": "ServiceReliabilityManifest",
        "metadata": {"name": name, "team": team, "tier": tier},
        "spec": {
            "type": svc_type,
            "slos": slos or {"availability": {"target": 99.9, "window": "30d"}},
        },
    }
    path = specs_dir / f"{name}.yaml"
    path.write_text(yaml.dump(spec))
    return path


@pytest.fixture
def catalogue(specs_dir):
    _write_v1_spec(specs_dir, "fraud-detect", team="payments-ml", svc_type="ai-gate",
                   slos={"reversal_rate": {"target": 0.015, "window": "2m"},
                         "availability": {"target": 99.9}})
    _write_v1_spec(specs_dir, "payment-api", svc_type="api")
    _write_v1_spec(specs_dir, "checkout-svc", team="orders", svc_type="api")

    cat = ManifestCatalogue(specs_dir)
    cat.load()
    set_catalogue(cat)
    yield cat
    set_catalogue(None)


@pytest.fixture
async def client(store, catalogue):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


class TestGetManifests:
    async def test_list_all(self, client):
        resp = await client.get("/manifests")
        assert resp.status_code == 200
        manifests = resp.json()
        assert len(manifests) == 3
        names = {m["name"] for m in manifests}
        assert names == {"fraud-detect", "payment-api", "checkout-svc"}

    async def test_manifest_has_expected_fields(self, client):
        resp = await client.get("/manifests")
        m = next(x for x in resp.json() if x["name"] == "fraud-detect")
        assert m["team"] == "payments-ml"
        assert m["tier"] == "critical"
        assert m["type"] == "ai-gate"
        assert m["source_format"] == "srm_v1"
        assert len(m["slos"]) == 2

    async def test_slo_includes_judgment_type(self, client):
        resp = await client.get("/manifests")
        m = next(x for x in resp.json() if x["name"] == "fraud-detect")
        judgment_slos = [s for s in m["slos"] if s.get("judgment_type")]
        assert len(judgment_slos) == 1
        assert judgment_slos[0]["judgment_type"] == "reversal_rate"


# Shapes follow opensrm/spec/v2/examples/judgment-thresholds/all-five-types.yaml
# (decision 3c, opensrm-l33e), inlined rather than loaded from the sibling repo.
_V2_THRESHOLDS = [
    {"type": "segments", "segment_dimension": "customer_tier",
     "segment_values": ["enterprise", "smb", "consumer"],
     "bounds": {"maximum_variance_from_overall": 0.05}},
    {"type": "stability",
     "probe": {"frozen_input_set": "s3://probes/credit-decision-2026q1.jsonl",
               "frequency": "daily"},
     "bounds": {"maximum_drift": 0.02}},
    {"type": "calibration", "measurement": {"bins": 10, "window": "30d"},
     "bounds": {"maximum_brier_score": 0.05}},
    {"type": "audit_backlog", "bounds": {"maximum_age": "24h"}},
    {"type": "feedback_latency",
     "bounds": {"maximum_p50": "1h", "maximum_p90": "24h"}},
]


def _write_v2_spec(specs_dir, name, thresholds=None):
    spec = {
        "apiVersion": "opensrm.nthlayer.io/v2",
        "kind": "ServiceManifest",
        "metadata": {"name": name, "labels": {"tier": "critical"}},
        "spec": {
            "owner": {"group": "group:default/risk"},
            "service": {"name": name, "type": "ai-gate"},
        },
    }
    if thresholds is not None:
        spec["spec"]["judgment_threshold"] = thresholds
    (specs_dir / f"{name}.yaml").write_text(yaml.dump(spec))


class TestJudgmentThresholds:
    async def test_all_five_types_serialised_as_declared(self, client, catalogue, specs_dir):
        _write_v2_spec(specs_dir, "credit-decision-agent", _V2_THRESHOLDS)
        catalogue.load()
        resp = await client.get("/manifests/credit-decision-agent")
        body = resp.json()
        by_type = {t["type"]: t for t in body["judgment_thresholds"]}
        assert list(by_type) == [
            "segments", "stability", "calibration", "audit_backlog", "feedback_latency"
        ]
        assert by_type["segments"] == {
            "type": "segments",
            "bounds": {"maximum_variance_from_overall": 0.05},
            "measurement": {
                "segment_dimension": "customer_tier",
                "segment_values": ["enterprise", "smb", "consumer"],
            },
        }
        assert by_type["stability"]["measurement"] == {
            "probe": {
                "frozen_input_set": "s3://probes/credit-decision-2026q1.jsonl",
                "frequency": "daily",
            }
        }
        assert by_type["calibration"]["measurement"] == {"bins": 10, "window": "30d"}
        assert by_type["calibration"]["bounds"] == {"maximum_brier_score": 0.05}
        # Duration bounds stay strings as declared; unset measurement is empty.
        assert by_type["audit_backlog"]["bounds"] == {"maximum_age": "24h"}
        assert by_type["audit_backlog"]["measurement"] == {}
        assert by_type["feedback_latency"]["bounds"] == {
            "maximum_p50": "1h", "maximum_p90": "24h"
        }

    async def test_thresholds_do_not_appear_under_slos(self, client, catalogue, specs_dir):
        _write_v2_spec(specs_dir, "credit-decision-agent", _V2_THRESHOLDS)
        catalogue.load()
        body = (await client.get("/manifests/credit-decision-agent")).json()
        slo_types = {s.get("judgment_type") for s in body["slos"]}
        assert not slo_types & {"segments", "stability", "calibration"}

    async def test_manifest_without_thresholds_has_empty_list(self, client):
        resp = await client.get("/manifests")
        assert resp.json()
        for m in resp.json():
            assert m["judgment_thresholds"] == []

    async def test_srm_v1_calibration_surfaces_as_threshold(self, client, catalogue, specs_dir):
        _write_v1_spec(specs_dir, "cal-svc", svc_type="ai-gate",
                       slos={"calibration": {"target": 0.05, "window": "30d"}})
        catalogue.load()
        body = (await client.get("/manifests/cal-svc")).json()
        # Expected bound and bins: 10 come from nthlayer-common's srm/v1 lift
        # (nthlayer_common.manifest.thresholds.srm_v1_threshold; docs/upgrading-4.0.md).
        assert body["judgment_thresholds"] == [{
            "type": "calibration",
            "bounds": {"maximum_expected_calibration_error": 0.05},
            "measurement": {"bins": 10, "window": "30d"},
        }]
        assert all(s.get("judgment_type") != "calibration" for s in body["slos"])


class TestGetManifest:
    async def test_get_existing(self, client):
        resp = await client.get("/manifests/payment-api")
        assert resp.status_code == 200
        assert resp.json()["name"] == "payment-api"
        assert resp.json()["type"] == "api"

    async def test_get_nonexistent(self, client):
        resp = await client.get("/manifests/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"


class TestManifestsReload:
    async def test_reload_detects_new_file(self, client, catalogue, specs_dir):
        _write_v1_spec(specs_dir, "order-service", team="orders")
        resp = await client.post("/manifests/-/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert "order-service" in body["changed"]
        assert body["total"] == 4

    async def test_reload_detects_modified_file(self, client, catalogue, specs_dir):
        time.sleep(0.05)  # ensure mtime changes
        _write_v1_spec(specs_dir, "payment-api", tier="high")
        resp = await client.post("/manifests/-/reload")
        assert resp.status_code == 200
        assert "payment-api" in resp.json()["changed"]

        # Verify the updated manifest
        get_resp = await client.get("/manifests/payment-api")
        assert get_resp.json()["tier"] == "high"

    async def test_reload_detects_deleted_file(self, client, catalogue, specs_dir):
        (specs_dir / "checkout-svc.yaml").unlink()
        resp = await client.post("/manifests/-/reload")
        assert resp.status_code == 200
        assert "checkout-svc" in resp.json()["changed"]
        assert resp.json()["total"] == 2

    async def test_reload_no_changes(self, client):
        resp = await client.post("/manifests/-/reload")
        assert resp.status_code == 200
        assert resp.json()["changed"] == []


class TestCatalogueUnit:
    def test_empty_catalogue(self):
        cat = ManifestCatalogue(None)
        assert cat.load() == []
        assert cat.list_all() == []

    def test_nonexistent_directory(self, tmp_path):
        cat = ManifestCatalogue(tmp_path / "nonexistent")
        assert cat.load() == []

    def test_invalid_yaml_skipped(self, specs_dir):
        (specs_dir / "bad.yaml").write_text("{{invalid")
        _write_v1_spec(specs_dir, "good-service")
        cat = ManifestCatalogue(specs_dir)
        loaded = cat.load()
        assert loaded == ["good-service"]
