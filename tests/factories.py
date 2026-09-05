"""Test data builders shared across the pure-core test modules.

Every test needs a `DeviceHandle` and almost none of them care what is in it, so building
one here keeps the interesting part of each test visible. Later tasks add `capabilities_for`,
`link` and `observed` alongside `handle`.
"""

from __future__ import annotations

from custom_components.device_links.models import Backend, DeviceHandle, ZWaveFingerprint

# Node 36's real fingerprint, from tests/fixtures/z2_associations.json. Every handle carries
# it, whatever node id it is given, because nothing that uses `handle` today looks at the
# model. The task that first needs a handle to describe the model it claims (building
# capabilities through the profile database) should key this by node id rather than change
# the shape of the helper.
ZEN35_FINGERPRINT = ZWaveFingerprint(
    manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
)

# The home id every fixture node is on, so two handles differ only by node id.
HOME_ID = "3538613642"


def handle(node_id: int = 36, name: str = "Bedroom Scene Controller") -> DeviceHandle:
    """Return a Z-Wave device handle for a node, identified by its protocol address."""
    return DeviceHandle(
        backend=Backend.ZWAVE,
        protocol_id=f"{HOME_ID}:{node_id}",
        ha_device_id="1f50c99924ffdc3f767cdcdb9f6b6294",
        fingerprint=ZEN35_FINGERPRINT,
        name_at_authoring=name,
    )
