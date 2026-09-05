"""P2: rule entities attach to existing devices, so identifier formats must be exact.

FR-E1 attaches each rule's switch and status sensor to the source device's own Home
Assistant device entry, which is how per-rule state appears on the device page without a
custom device panel hook. That only works if DeviceInfo.identifiers exactly matches what
the upstream integration already registered: a near miss silently creates a second,
orphaned device rather than failing.

Captured read-only from the device registry on 2026-09-05. The network-identifying parts
of each identifier are masked because the repository is public; the structure around them
is what these tests pin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "p2_device_identifiers.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="P2 fixture not captured yet")


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


def test_every_backend_has_a_recorded_identifier_format() -> None:
    samples = _data()["samples"]

    for backend in ("zwave_js", "mqtt", "matter"):
        assert samples.get(backend), f"no identifier sample captured for {backend}"
        assert samples[backend]["identifiers"], f"{backend} sample has no identifiers"


def test_all_three_backends_have_devices_to_manage() -> None:
    """If a backend had no devices, its half of Stage 0 would prove nothing."""
    counts = _data()["device_counts"]

    assert counts["zwave_js"] >= 30
    assert counts["mqtt"] >= 20
    assert counts["matter"] >= 15


def test_zwave_devices_carry_both_a_short_and_an_extended_identifier() -> None:
    """The short one is for attachment; the extended one changes on a model swap."""
    identifiers = [value for domain, value in _data()["samples"]["zwave_js"]["identifiers"]]

    short = [i for i in identifiers if i.count("-") == 1]
    extended = [i for i in identifiers if ":" in i]

    assert short, f"no <home_id>-<node_id> identifier found in {identifiers}"
    assert extended, f"no fingerprint-bearing identifier found in {identifiers}"
    assert short[0] == "<home_id>-36", "the short identifier shape changed"
    assert extended[0].startswith(short[0] + "-"), (
        "the extended identifier no longer extends the short one, so FR-S3 cannot detect "
        "a replaced device by comparing them"
    )


def test_every_identifier_is_namespaced_by_its_integration_domain() -> None:
    """Attaching means reusing the upstream domain, never inventing a device_links one."""
    for backend, sample in _data()["samples"].items():
        for domain, _value in sample["identifiers"]:
            assert domain == backend, (
                f"{backend} device carries a {domain!r}-namespaced identifier; entity "
                "attachment must reuse the upstream domain exactly"
            )


def test_zigbee_identifiers_are_prefixed_by_the_mqtt_base_topic() -> None:
    """A second Zigbee2MQTT instance uses a different base topic and different ids."""
    value = _data()["samples"]["mqtt"]["identifiers"][0][1]

    assert value.startswith("zigbee2mqtt_"), f"unexpected Zigbee identifier shape: {value}"
    assert "0x" in value, "the IEEE address is no longer part of the identifier"
    assert "base_topic" in _data()["formats"]["mqtt"]["pattern"][0]


def test_matter_identifiers_embed_the_fabric_id() -> None:
    """Re-commissioning the fabric changes this and would orphan every stored handle."""
    value = _data()["samples"]["matter"]["identifiers"][0][1]

    assert value.startswith("deviceid_")
    assert value.endswith("-MatterNodeDevice")
    assert "<compressed_fabric_id>" in value, "the fabric id was not masked"


def test_no_sampled_device_uses_composite_identifiers() -> None:
    """Composite devices are new in 2026.x and would change how attachment works."""
    for backend, sample in _data()["samples"].items():
        assert sample["has_composite_identifiers"] is False, (
            f"{backend} now uses composite identifiers; re-check FR-E1 attachment before "
            "assuming a single device entry per protocol device"
        )


def test_the_registry_schema_note_is_recorded() -> None:
    """The record shape changed in 2026.8 and code that walks it must know."""
    note = _data()["registry_schema_note"]

    assert "config_entry_id" in note
    assert "primary_config_entry" in note


def test_the_fixture_leaks_no_network_identifiers() -> None:
    raw = FIXTURE.read_text()

    assert "<home_id>" in raw, "the Z-Wave home id should be masked, not absent"
    assert "0x<ieee>" in raw
    assert "<compressed_fabric_id>" in raw
