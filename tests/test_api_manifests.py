"""Tests for manifest catalogue API endpoints."""

import time

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from nthlayer.catalogue import ManifestCatalogue
from nthlayer.server import app, set_catalogue, set_store
from nthlayer.store import Store


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
