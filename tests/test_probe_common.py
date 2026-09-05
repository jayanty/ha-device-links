"""The probe harness must redact before anything is written to a fixture."""

from __future__ import annotations

import json

from tools.probe_common import envelope, redact


def test_redact_masks_home_id_and_ieee() -> None:
    payload = {
        "home_id": 3735928559,
        "nodes": [{"ieee_address": "0x00124b002e1dfd4a", "node_id": 36}],
    }
    cleaned = redact(payload)

    assert cleaned["home_id"] == "<redacted>"
    assert cleaned["nodes"][0]["ieee_address"] == "<redacted:...fd4a>"
    assert cleaned["nodes"][0]["node_id"] == 36, "node ids are not secret and must survive"


def test_envelope_records_provenance() -> None:
    out = envelope("z2_associations", {"a": 1}, versions={"homeassistant": "2026.8.3"})

    assert out["fixture"] == "z2_associations"
    assert out["data"] == {"a": 1}
    assert out["versions"]["homeassistant"] == "2026.8.3"
    assert out["captured_at"].endswith("Z"), "timestamps are UTC and comparable"
    json.dumps(out)  # must be serializable
