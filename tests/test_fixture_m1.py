"""M1: closes PRD assumption A4 and gives Phase 3 a go or no-go.

Captured read-only from Jayant's Matter fabric on 2026-09-05. Nothing was written:
Matter ACL writes are security relevant and stay behind an options flag that defaults
to off (Decision D11, FR-B7).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "m1_matter.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="M1 fixture not captured yet")

OTA_PROVIDER_CLUSTER = 41
BINDING_CLUSTER = 30
ON_OFF_CLUSTER = 6
LEVEL_CONTROL_CLUSTER = 8


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


def test_the_client_api_verdict_is_explicit() -> None:
    """A4 asked whether a custom integration can read and write Matter attributes."""
    data = _data()

    assert data["read_attribute_available"] is True
    assert data["write_attribute_available"] is True
    assert data["accessor_notes"], "record how the client was reached, for Phase 3"


def test_the_library_is_matter_python_client_not_python_matter_server() -> None:
    """Amends PRD Appendix C, which cited the archived python-matter-server lineage.

    Home Assistant 2026.8.3 requires matter-python-client 1.3.0. The distribution was
    renamed but still installs the `matter_server` package, so the import path is
    unchanged while the project and its issue tracker are not.
    """
    versions = json.loads(FIXTURE.read_text())["versions"]

    assert versions["matter_python_client"] == "1.3.0"
    assert "matter.js" in versions["sdk_version"], (
        "the server is no longer the matter.js lineage; re-check the binding and ACL "
        "write behavior described in FR-B7"
    )


def test_at_least_one_real_binding_source_exists() -> None:
    """Phase 3 is only worth building if this network has something to bind from."""
    sources = _data()["phase3_verdict"]["binding_sources"]

    assert sources, "no Matter device exposes control client clusters; revisit Decision D11"
    for source in sources:
        assert source["endpoint"] == 2, "the Inovelli White binding source moved off endpoint 2"


def test_the_binding_source_can_actually_control_a_light() -> None:
    """A source is only useful if it emits OnOff, and dimming needs LevelControl."""
    devices = {d["node_id"]: d for d in _data()["devices"]}
    source = devices[_data()["phase3_verdict"]["binding_sources"][0]["node_id"]]

    clusters = source["client_clusters"]["2"]
    assert ON_OFF_CLUSTER in clusters, "the source cannot send OnOff, so UC13 cannot compile"
    assert LEVEL_CONTROL_CLUSTER in clusters, "no LevelControl, so hold-to-dim is impossible"

    assert "2" in source["bindings"], "endpoint 2 has no Binding cluster to write into"


def test_the_ota_client_cluster_must_not_be_read_as_an_emitter() -> None:
    """Every node advertises cluster 41 on endpoint 0. It is firmware update, not control.

    A capability model that treats any client cluster as an emitter would offer every
    sensor and lock on the fabric as a usable remote.
    """
    data = _data()
    on_endpoint_zero = [
        d["node_id"]
        for d in data["devices"]
        if d["client_clusters"].get("0") == [OTA_PROVIDER_CLUSTER]
    ]

    assert len(on_endpoint_zero) >= 10, "expected the OTA client cluster on most nodes"
    assert data["phase3_verdict"]["ota_client_caveat"]


def test_devices_the_prd_expected_to_be_sources_are_not() -> None:
    """PRD Section 3.1 named the Aqara H2 and the BILRESA button as binding sources."""
    devices = _data()["devices"]

    for product_fragment in ("Aqara Light Switch H2", "BILRESA"):
        matches = [d for d in devices if product_fragment in str(d["product"])]
        assert matches, f"{product_fragment} is no longer on the fabric"
        for device in matches:
            control_endpoints = {
                endpoint
                for endpoint, clusters in device["client_clusters"].items()
                if clusters != [OTA_PROVIDER_CLUSTER]
            }
            assert not control_endpoints, (
                f"{product_fragment} now exposes control client clusters at "
                f"{control_endpoints}. It was not a binding source at capture time and "
                "the Phase 3 scope in docs/stage0-report.md should be widened."
            )


def test_acl_capacity_was_recorded_and_is_tight() -> None:
    """E27 and E28 need real numbers, and the numbers here are small.

    Eve Energy allows 6 ACL entries per fabric and already uses 4. Adding a grant per
    source without merging would exhaust that after two rules.
    """
    devices = _data()["devices"]
    eve = next(d for d in devices if "Eve Energy" in str(d["product"]))
    capacity = eve["acl_capacity"]

    assert capacity["entries_per_fabric"] > 0
    assert capacity["subjects_per_entry"] > 0
    assert capacity["targets_per_entry"] > 0

    used = len(eve["acl"]) if isinstance(eve["acl"], list) else 0
    assert used < capacity["entries_per_fabric"], "the target's ACL is already full"
    assert capacity["entries_per_fabric"] - used <= 4, (
        "ACL headroom grew. The merge-into-an-existing-entry strategy in FR-B7 was "
        "chosen because headroom was 2 entries; re-check whether it is still needed."
    )
