"""G1 closes PRD assumption A3 about the Zigbee2MQTT bridge schema on 2.14.1.

Captured read-only from the retained bridge topics on 2026-09-05. This is the read path
for all observed Zigbee state (FR-B5), so its shape is load-bearing for Phase 2.

IEEE addresses are masked to their last four characters before the fixture is committed,
because the repository is public. The masking is deterministic and was checked for
collisions across all 24 devices at capture time, so references between devices still
resolve within the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "g1_bridge.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="G1 fixture not captured yet")

COORDINATOR_IEEE = "<redacted:...fd4a>"


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


def _devices() -> list[dict[str, Any]]:
    return _data()["devices"]


def test_every_expected_topic_was_retained() -> None:
    """If a bridge topic is not retained, the backend cannot read state on startup."""
    assert _data()["missing_topics"] == [], (
        "a bridge topic did not arrive as retained; FR-B5 reads observed Zigbee state "
        "from these on every start and would come up blank"
    )


def test_endpoints_expose_bindings_clusters_and_reportings() -> None:
    """Assumption A3, stated as unverified in PRD Section 3.3. It holds."""
    with_endpoints = [d for d in _devices() if d.get("endpoints")]
    assert with_endpoints, "no device reported endpoints"

    first = next(iter(with_endpoints[0]["endpoints"].values()))
    assert "bindings" in first, "A3 is wrong: no per-endpoint bindings key"
    assert "clusters" in first, "A3 is wrong: no per-endpoint clusters key"
    assert "input" in first["clusters"]
    assert "output" in first["clusters"]
    assert "configured_reportings" in first


def test_binding_targets_carry_a_type_discriminator() -> None:
    """The backend must tell an endpoint target from a group target (FR-B6)."""
    seen: set[str] = set()
    for device in _devices():
        for endpoint in (device.get("endpoints") or {}).values():
            for binding in endpoint.get("bindings") or []:
                assert "cluster" in binding
                target = binding["target"]
                assert target["type"] in {"endpoint", "group"}, f"unknown target: {target}"
                if target["type"] == "endpoint":
                    assert "ieee_address" in target
                    assert "endpoint" in target
                seen.add(target["type"])
    assert seen, "no bindings at all were captured"


def test_inovelli_blue_paddle_endpoint_is_bindable() -> None:
    """PRD Section 3.2: VZM31-SN endpoint 2 is the paddle client endpoint.

    This is the source endpoint every "remote controls light" rule binds from on this
    model, so if it stopped emitting these clusters the template could not compile.
    """
    blues = [d for d in _devices() if (d.get("definition") or {}).get("model") == "VZM31-SN"]
    assert blues, "no Inovelli Blue VZM31-SN found"

    outputs = blues[0]["endpoints"]["2"]["clusters"]["output"]
    assert "genOnOff" in outputs, "EP2 does not emit genOnOff; the binding plan is wrong"
    assert "genLevelCtrl" in outputs, "EP2 does not emit genLevelCtrl, so hold-to-dim fails"


def test_inovelli_blue_config_button_endpoint_exists() -> None:
    """EP3 is the config button, usable as a scene-button source (UC3)."""
    blues = [d for d in _devices() if (d.get("definition") or {}).get("model") == "VZM31-SN"]

    outputs = blues[0]["endpoints"]["3"]["clusters"]["output"]
    assert "genOnOff" in outputs
    assert "genLevelCtrl" in outputs


def test_exactly_one_coordinator_is_reported() -> None:
    """PRD Section 3.1 warned of a stale second bridge device.

    The stale entry is a Home Assistant device-registry leftover, not something
    Zigbee2MQTT reports: the bridge itself knows about exactly one coordinator. The
    backend selects its base topic explicitly and should trust this list, not the
    registry.
    """
    coordinators = [d for d in _devices() if d.get("type") == "Coordinator"]

    assert len(coordinators) == 1, f"expected exactly one coordinator, got {len(coordinators)}"
    assert coordinators[0]["ieee_address"] == COORDINATOR_IEEE


def test_existing_bindings_all_target_the_coordinator() -> None:
    """Recorded starting state, and the reason FR-B5 needs a system-link classifier.

    Every binding on the network today points at the coordinator: they are Zigbee2MQTT's
    own reporting setup, not user intent. Showing them as unmanaged links would invite a
    user to delete the thing that makes their devices report at all.
    """
    non_coordinator: list[str] = []
    for device in _devices():
        for endpoint_id, endpoint in (device.get("endpoints") or {}).items():
            for binding in endpoint.get("bindings") or []:
                target = binding["target"]
                if target.get("ieee_address") != COORDINATOR_IEEE:
                    name = device.get("friendly_name")
                    non_coordinator.append(
                        f"{name} ep{endpoint_id} {binding['cluster']} -> {target}"
                    )

    assert not non_coordinator, (
        "device-to-device bindings already exist on this network, so the Phase 2 "
        f"acceptance scenarios no longer start from a clean state: {non_coordinator}"
    )


def test_no_zigbee_groups_exist_yet() -> None:
    """FR-B6 creates dl_-prefixed managed groups and must never touch foreign ones."""
    assert _data()["groups"] == [], (
        "Zigbee groups now exist. Confirm none use the dl_ prefix before Phase 2 runs, "
        "because the backend treats that prefix as its own."
    )


def test_the_bridge_is_online_and_the_version_is_recorded() -> None:
    assert _data()["state"]["state"] == "online"
    assert json.loads(FIXTURE.read_text())["versions"]["zigbee2mqtt"] == "2.14.1"


def test_the_fixture_carries_no_unmasked_ieee_addresses() -> None:
    """The repository is public."""
    raw = FIXTURE.read_text()
    assert "0x00124b" not in raw, "an unmasked Zigbee IEEE address reached the fixture"
