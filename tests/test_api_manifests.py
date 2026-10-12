"""Tests for manifest catalogue API endpoints."""

import time

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
from nthlayer_common.manifest import ManifestLoadError, load_manifest

from nthlayer_core.catalogue import ManifestCatalogue
from nthlayer_core.openapi_spec import OPENAPI
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


# Threshold fixtures are inlined from the spec's own examples (core CI does not
# check out opensrm), copied entry for entry from opensrm main @ 859424a (the
# opensrm-7zpz merge); no entry is edited from its source. Each list names its
# source file under opensrm/spec/v2/examples/. Against core 2.x's copy, the
# _V2_THRESHOLDS segments entry changed with its source: it gained
# `metric: high_confidence_failure` and `measurement.confidence_threshold`,
# as OPENSRM-CORE-v2 §5.5.1 now requires; the other two lists are new.
# To refresh: diff each entry against the named opensrm file at the opensrm
# commit core targets; edit the inline copy, never load from the sibling.

# judgment-thresholds/all-five-types.yaml (decision 3c, opensrm-l33e).
_V2_THRESHOLDS = [
    {"type": "segments", "metric": "high_confidence_failure",
     "measurement": {"confidence_threshold": 0.9},
     "segment_dimension": "customer_tier",
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

# judgment-thresholds/segments-two-dimensions.yaml: reversal_rate and outcomes.
_V2_SEGMENTS_TWO_DIMENSIONS = [
    {"type": "segments", "metric": "reversal_rate",
     "measurement": {"source": "lineage"},
     "segment_dimension": "customer_tier",
     "segment_values": ["enterprise", "smb", "consumer"],
     "bounds": {"maximum_variance_from_overall": 0.05}},
    {"type": "segments", "metric": "outcomes",
     "outcome_signal": {"source": "retro-consumer", "window": "1h"},
     "measurement": {"window": "7d"},
     "segment_dimension": "region",
     "segment_values": ["eu", "us", "apac"],
     "bounds": {"maximum_variance_from_overall": 0.08}},
]

# services/ai-gate.yaml judgment_threshold: reversal_rate and escalation.
_V2_AI_GATE_THRESHOLDS = [
    {"type": "segments", "metric": "reversal_rate",
     "measurement": {"source": "lineage"},
     "segment_dimension": "customer_tier",
     "segment_values": ["enterprise", "smb", "consumer"],
     "bounds": {"maximum_variance_from_overall": 0.05}},
    {"type": "segments", "metric": "escalation",
     "segment_dimension": "customer_tier",
     "segment_values": ["enterprise", "smb", "consumer"],
     "bounds": {"maximum_variance_from_overall": 0.10}},
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


def _with_default_window(entry):
    """*entry* as served: a segments `measurement.window` defaults to 30d.

    The default is the spec's (OPENSRM-CORE-v2 §5.5.1: "window: any metric;
    population window, default 30d"), so the served entry states it.
    """
    if entry["type"] != "segments":
        return entry
    served = dict(entry)
    served["measurement"] = {"window": "30d", **entry.get("measurement", {})}
    return served


class TestJudgmentThresholds:
    async def test_all_five_types_serialised_as_v2_entries(self, client, catalogue, specs_dir):
        _write_v2_spec(specs_dir, "credit-decision-agent", _V2_THRESHOLDS)
        catalogue.load()
        resp = await client.get("/manifests/credit-decision-agent")
        assert resp.status_code == 200
        served = resp.json()["judgment_thresholds"]
        # Each item is the declared spec.judgment_threshold entry, in order:
        # segment_dimension/segment_values/probe at entry level, no empty
        # `measurement` on types that define none.
        assert served == [_with_default_window(e) for e in _V2_THRESHOLDS]
        assert served[0]["measurement"] == {"confidence_threshold": 0.9, "window": "30d"}
        assert "measurement" not in served[3]
        assert "measurement" not in served[4]

    @pytest.mark.parametrize(
        ("name", "declared"),
        [
            pytest.param("pricing-agent", _V2_SEGMENTS_TWO_DIMENSIONS,
                         id="reversal_rate+outcomes"),
            pytest.param("refund-approver", _V2_AI_GATE_THRESHOLDS,
                         id="reversal_rate+escalation"),
        ],
    )
    async def test_segments_metric_and_parameter_served(
        self, client, catalogue, specs_dir, name, declared
    ):
        _write_v2_spec(specs_dir, name, declared)
        catalogue.load()
        served = (await client.get(f"/manifests/{name}")).json()["judgment_thresholds"]
        assert served == [_with_default_window(e) for e in declared]

    async def test_outcomes_signal_window_is_not_the_population_window(
        self, client, catalogue, specs_dir
    ):
        _write_v2_spec(specs_dir, "pricing-agent", _V2_SEGMENTS_TWO_DIMENSIONS)
        catalogue.load()
        served = (await client.get("/manifests/pricing-agent")).json()["judgment_thresholds"]
        outcomes = next(t for t in served if t["metric"] == "outcomes")
        assert outcomes["outcome_signal"] == {"source": "retro-consumer", "window": "1h"}
        assert outcomes["measurement"] == {"window": "7d"}

    async def test_escalation_carries_no_parameter(self, client, catalogue, specs_dir):
        _write_v2_spec(specs_dir, "refund-approver", _V2_AI_GATE_THRESHOLDS)
        catalogue.load()
        served = (await client.get("/manifests/refund-approver")).json()["judgment_thresholds"]
        escalation = next(t for t in served if t["metric"] == "escalation")
        assert escalation["measurement"] == {"window": "30d"}
        assert "outcome_signal" not in escalation

    async def test_served_thresholds_reload_as_the_same_manifest(
        self, client, catalogue, specs_dir, tmp_path
    ):
        """A served item is a valid spec.judgment_threshold entry, not a look-alike.

        Writing the served list back as a manifest's judgment_threshold must
        load, and serve the identical list again.
        """
        declared = _V2_THRESHOLDS + _V2_SEGMENTS_TWO_DIMENSIONS + _V2_AI_GATE_THRESHOLDS
        _write_v2_spec(specs_dir, "everything", declared)
        catalogue.load()
        first = (await client.get("/manifests/everything")).json()["judgment_thresholds"]
        assert len(first) == len(declared)
        _write_v2_spec(specs_dir, "everything-again", first)
        catalogue.load()
        resp = await client.get("/manifests/everything-again")
        assert resp.status_code == 200
        assert resp.json()["judgment_thresholds"] == first

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


    async def test_srm_v1_feedback_latency_target_lifts_to_p50_seconds(
        self, client, catalogue, specs_dir
    ):
        _write_v1_spec(specs_dir, "fl-svc", svc_type="ai-gate",
                       slos={"feedback_latency": {"target": 3600}})
        catalogue.load()
        body = (await client.get("/manifests/fl-svc")).json()
        # Expected bound is nthlayer-common's srm/v1 lift
        # (nthlayer_common.manifest.thresholds.srm_v1_threshold): a whole-second
        # target becomes maximum_p50 "<n>s". feedback_latency defines no
        # measurement (OPENSRM-CORE-v2 §5.5), so the entry has none.
        assert body["judgment_thresholds"] == [{
            "type": "feedback_latency",
            "bounds": {"maximum_p50": "3600s"},
        }]


def _manifest_validator():
    """Validator for the published Manifest schema, resolving its $refs.

    The schema refers to sibling components (#/components/schemas/...), so it
    is checked with the whole OpenAPI document as the root it resolves against.
    """
    root = {"$ref": "#/components/schemas/Manifest", "components": OPENAPI["components"]}
    Draft202012Validator.check_schema(root)
    return Draft202012Validator(root)


class TestManifestSchemaConformance:
    async def test_every_served_manifest_validates_against_openapi_manifest(
        self, client, catalogue, specs_dir
    ):
        """The served body must satisfy the schema the spec publishes for it.

        test_openapi.py only proves the dict equals the checked-in JSON, so a
        wrong schema regenerated consistently passes there. This is the check
        against real output, with every threshold type, every segments metric
        and both srm/v1 lifts in play.
        """
        _write_v2_spec(specs_dir, "credit-decision-agent", _V2_THRESHOLDS)
        _write_v2_spec(specs_dir, "pricing-agent", _V2_SEGMENTS_TWO_DIMENSIONS)
        _write_v2_spec(specs_dir, "refund-approver", _V2_AI_GATE_THRESHOLDS)
        _write_v1_spec(specs_dir, "cal-svc", svc_type="ai-gate",
                       slos={"calibration": {"target": 0.05, "window": "30d"}})
        _write_v1_spec(specs_dir, "fl-svc", svc_type="ai-gate",
                       slos={"feedback_latency": {"target": 3600}})
        catalogue.load()
        manifests = (await client.get("/manifests")).json()
        # 3 from the `catalogue` fixture + the 5 written above.
        assert len(manifests) == 8
        served = [t for m in manifests for t in m["judgment_thresholds"]]
        assert {t["type"] for t in served} == {
            "segments", "stability", "calibration", "audit_backlog", "feedback_latency"
        }
        assert {t["metric"] for t in served if t["type"] == "segments"} == {
            "reversal_rate", "high_confidence_failure", "outcomes", "escalation"
        }
        validator = _manifest_validator()
        for m in manifests:
            errors = [e.message for e in validator.iter_errors(m)]
            assert not errors, (m["name"], errors)

    # Item shapes core 3.0 (common 5.0) no longer serves. Each must be refused by
    # the published schema, or a client validating against it would accept a
    # stale or misspelled threshold.
    @pytest.mark.parametrize(
        "item",
        [
            pytest.param(
                {"type": "segments", "bounds": {"maximum_variance_from_overall": 0.05},
                 "measurement": {"segment_dimension": "customer_tier",
                                 "segment_values": ["enterprise"]}},
                id="2.x-segments-shape",
            ),
            pytest.param(
                {"type": "stability", "bounds": {"maximum_drift": 0.02},
                 "measurement": {"probe": {"frozen_input_set": "s3://p.jsonl",
                                           "frequency": "daily"}}},
                id="2.x-stability-shape",
            ),
            pytest.param(
                {"type": "audit_backlog", "bounds": {"maximum_age": "24h"},
                 "measurement": {}},
                id="2.x-empty-measurement",
            ),
            pytest.param(
                {"type": "segments", "metric": "audit_sampling",
                 "measurement": {"window": "30d"},
                 "segment_dimension": "customer_tier", "segment_values": ["smb"],
                 "bounds": {"maximum_variance_from_overall": 0.05}},
                id="segments-audit_sampling-metric",
            ),
            pytest.param(
                {"type": "segments", "metric": "reversal_rate",
                 "measurement": {"window": "30d"},
                 "segment_dimension": "customer_tier", "segment_values": ["smb"],
                 "bounds": {"maximum_variance_from_overall": 0.05}},
                id="reversal_rate-without-source",
            ),
            pytest.param(
                {"type": "segments", "metric": "escalation",
                 "measurement": {"window": "30d"},
                 "outcome_signal": {"source": "s", "window": "1h"},
                 "segment_dimension": "customer_tier", "segment_values": ["smb"],
                 "bounds": {"maximum_variance_from_overall": 0.05}},
                id="outcome_signal-on-escalation",
            ),
            pytest.param(
                {"type": "calibration", "measurement": {"bins": 10, "window": "30d"},
                 "bounds": {"maximum_brier_score": 0.05}, "description": "x"},
                id="undefined-entry-key",
            ),
        ],
    )
    async def test_schema_refuses_item_shapes_not_served(self, client, item):
        validator = _manifest_validator()
        served = (await client.get("/manifests/payment-api")).json()
        # Baseline: the real served manifest is clean, so any error below is
        # the substituted item's.
        assert not list(validator.iter_errors(served))
        errors = list(validator.iter_errors({**served, "judgment_thresholds": [item]}))
        assert errors
        assert all(e.absolute_path[0] == "judgment_thresholds" for e in errors)


class TestRejectedManifests:
    async def test_calibration_under_judgment_slo_is_omitted_not_fatal(
        self, client, catalogue, specs_dir
    ):
        # Shape of opensrm/spec/v2/tests/invalid/n22-calibration-as-judgment-slo.yaml
        # as an inline spec.judgment_slo item.
        rejected = {
            "apiVersion": "opensrm.nthlayer.io/v2",
            "kind": "ServiceManifest",
            "metadata": {"name": "bad-cal", "labels": {"tier": "critical"}},
            "spec": {
                "owner": {"group": "group:default/risk"},
                "service": {"name": "bad-cal", "type": "ai-gate"},
                "judgment_slo": [{
                    "service": "bad-cal",
                    "judgment_type": "calibration",
                    "measurement": {"bins": 10, "window": "30d", "method": "brier_score"},
                    "target": {"maximum_brier_score": 0.05},
                }],
            },
        }
        rejected_path = specs_dir / "bad-cal.yaml"
        rejected_path.write_text(yaml.dump(rejected))
        # Guard against an unrelated failure standing in for the real rejection.
        with pytest.raises(ManifestLoadError) as excinfo:
            load_manifest(rejected_path)
        assert "judgment_threshold" in str(excinfo.value)

        _write_v2_spec(specs_dir, "good-v2", _V2_THRESHOLDS)
        catalogue.load()
        resp = await client.get("/manifests")
        assert resp.status_code == 200
        names = {m["name"] for m in resp.json()}
        assert "good-v2" in names
        assert "bad-cal" not in names
        assert names >= {"fraud-detect", "payment-api", "checkout-svc"}


    async def test_4x_segments_without_metric_is_omitted_not_fatal(
        self, client, catalogue, specs_dir
    ):
        # The 4.x-era segments shape: no `metric`, which OPENSRM-CORE-v2
        # §5.5.1 now requires (spec/v2/schema.json JudgmentThresholdSpec
        # segments `required`). Its siblings must still load and be served.
        stale = [{"type": "segments", "segment_dimension": "customer_tier",
                  "segment_values": ["enterprise", "smb", "consumer"],
                  "bounds": {"maximum_variance_from_overall": 0.05}}]
        _write_v2_spec(specs_dir, "stale-segments", stale)
        # Guard against an unrelated failure standing in for the real rejection.
        with pytest.raises(ManifestLoadError) as excinfo:
            load_manifest(specs_dir / "stale-segments.yaml")
        assert "metric" in str(excinfo.value)

        _write_v2_spec(specs_dir, "good-v2", _V2_THRESHOLDS)
        catalogue.load()
        resp = await client.get("/manifests")
        assert resp.status_code == 200
        names = {m["name"] for m in resp.json()}
        assert "stale-segments" not in names
        assert names == {"fraud-detect", "payment-api", "checkout-svc", "good-v2"}
        assert (await client.get("/manifests/stale-segments")).status_code == 404

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
