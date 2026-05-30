"""Manifest catalogue.

Loads OpenSRM manifests from a directory, caches them in memory, and
detects changes via polling. Workers read manifests from core's API
instead of loading YAML files directly.

Usage:
    catalogue = ManifestCatalogue("/path/to/specs")
    catalogue.load()          # initial load
    changed = catalogue.poll()  # check for changes, returns list of changed service names
    manifest = catalogue.get("fraud-detect")
    all_manifests = catalogue.list_all()
"""

from __future__ import annotations

import structlog
from pathlib import Path
from typing import Any

from nthlayer_common.manifest import (
    ManifestLoadError,
    load_manifest,
)
from nthlayer_common.manifest.models import ReliabilityManifest

logger = structlog.get_logger()


class ManifestCatalogue:
    """In-memory manifest catalogue with file-system change detection.

    Loads all .yaml/.yml files from a directory, parses them as manifests,
    and caches the parsed results keyed by service name. Polling checks
    file mtimes and reloads changed files.
    """

    def __init__(self, manifests_dir: str | Path | None = None):
        self._dir: Path | None = None
        if manifests_dir is not None:
            self._dir = Path(manifests_dir).resolve()
        self._manifests: dict[str, ReliabilityManifest] = {}
        self._mtimes: dict[str, float] = {}  # path → mtime

    @property
    def directory(self) -> Path | None:
        return self._dir

    def load(self) -> list[str]:
        """Load all manifests from the directory. Returns list of service names loaded."""
        if self._dir is None or not self._dir.is_dir():
            return []

        loaded = []
        for yaml_file in sorted(self._dir.glob("*.yaml")) + sorted(self._dir.glob("*.yml")):
            name = self._load_file(yaml_file)
            if name:
                loaded.append(name)

        logger.info("catalogue_loaded", count=len(loaded), directory=str(self._dir))
        return loaded

    def poll(self) -> list[str]:
        """Check for changed/new/deleted manifest files. Returns list of changed service names."""
        if self._dir is None or not self._dir.is_dir():
            return []

        changed: list[str] = []
        current_files: set[str] = set()

        for yaml_file in sorted(self._dir.glob("*.yaml")) + sorted(self._dir.glob("*.yml")):
            file_key = str(yaml_file)
            current_files.add(file_key)

            try:
                mtime = yaml_file.stat().st_mtime
            except OSError:
                continue

            if file_key not in self._mtimes or self._mtimes[file_key] < mtime:
                name = self._load_file(yaml_file)
                if name:
                    changed.append(name)

        # Detect deleted files
        deleted_files = set(self._mtimes.keys()) - current_files
        for file_key in deleted_files:
            # Find which service this file belonged to
            for svc_name, manifest in list(self._manifests.items()):
                if manifest.source_file == file_key:
                    del self._manifests[svc_name]
                    changed.append(svc_name)
                    break
            del self._mtimes[file_key]

        if changed:
            logger.info("catalogue_changed", changed=changed)

        return changed

    def get(self, service_name: str) -> ReliabilityManifest | None:
        """Get a manifest by service name."""
        return self._manifests.get(service_name)

    def list_all(self) -> list[ReliabilityManifest]:
        """List all loaded manifests."""
        return list(self._manifests.values())

    def to_dict_list(self) -> list[dict[str, Any]]:
        """Serialise all manifests to a list of dicts for API responses."""
        return [manifest_to_dict(m) for m in self._manifests.values()]

    def _load_file(self, yaml_file: Path) -> str | None:
        """Load a single manifest file. Returns service name or None on failure."""
        try:
            mtime = yaml_file.stat().st_mtime  # capture before parse to avoid TOCTOU
            manifest = load_manifest(yaml_file, suppress_deprecation_warning=True)
            self._manifests[manifest.name] = manifest
            self._mtimes[str(yaml_file)] = mtime
            return manifest.name
        except (ManifestLoadError, FileNotFoundError, ValueError, OSError) as e:
            logger.warning("catalogue_load_failed", file=str(yaml_file), error=str(e))
            return None


def manifest_to_dict(m: ReliabilityManifest) -> dict[str, Any]:
    """Convert a ReliabilityManifest to a JSON-serialisable dict for the API."""
    result: dict[str, Any] = {
        "name": m.name,
        "team": m.team,
        "tier": m.tier,
        "type": m.type,
        "namespace": m.namespace,
        "source_format": m.source_format.value,
    }

    if m.description:
        result["description"] = m.description
    if m.labels:
        result["labels"] = m.labels

    # SLOs
    result["slos"] = []
    for slo in m.slos:
        slo_dict: dict[str, Any] = {
            "name": slo.name,
            "target": slo.target,
            "slo_type": slo.slo_type,
            "window": slo.window,
        }
        if slo.judgment_type:
            slo_dict["judgment_type"] = slo.judgment_type
        if slo.indicator_query:
            slo_dict["indicator_query"] = slo.indicator_query
        if slo.description:
            slo_dict["description"] = slo.description
        result["slos"].append(slo_dict)

    # Dependencies
    result["dependencies"] = [
        {
            "name": d.name,
            "type": d.type,
            "critical": d.critical,
        }
        for d in m.dependencies
    ]

    # Contracts
    if m.contracts:
        result["contracts"] = [
            {
                "name": c.name,
                "promise": {
                    "availability": c.promise.availability,
                    "latency_p99": c.promise.latency_p99,
                },
            }
            for c in m.contracts
        ]

    return result
