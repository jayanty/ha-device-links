"""The swap wizard's own payloads, through the real handlers that read them.

CLAUDE.md Section 8's sixth level, on the newest producer/consumer boundary in the product.
`tests/test_scenario_s7.py` proves the flow works; this proves that what the **wizard**
sends is what the flow accepts, and that what comes back is the shape `types.ts` declares.
The two are not the same test, and open item T50 is the standing evidence: every layer's
tests were green for two phases while the panel sent a payload the backend refused.

The steps are the wizard's own, in its order: list the devices that have gone, choose the
replacement, read its controls to build the mapping pickers, preview with the mapping the
user settled on, and apply with the token that preview answered with.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from tests.test_panel_contract import assert_shape
from tests.test_scenario_s7 import (
    REPLACEMENT,
    call,
    import_profile,
    imported_profile,
    old_identity,
    refused,
)


@pytest.fixture
async def client(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, device_links_entry: MockConfigEntry
) -> Any:
    """An admin connection to a set-up integration over the Stage 0 fake network."""
    return await hass_ws_client(hass)


@pytest.fixture
async def imported(client: Any) -> str:
    """The S7 profile, imported and active, which is a swap waiting to happen."""
    return await import_profile(client, imported_profile())


async def test_the_candidates_the_wizard_lists_match_the_replacement_interface(
    client: Any, imported: str
) -> None:
    """The wizard's first step, and the payload it builds its list from."""
    assert imported
    result = await call(client, "swap/candidates")

    assert result["replacements"], "nothing was offered, so no shape was checked"
    for replacement in result["replacements"]:
        assert_shape(replacement, "SwapReplacement")


async def test_the_preview_the_wizard_asks_for_matches_the_preview_interface(
    client: Any, imported: str, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """Every field the mapping and review steps render, all the way down.

    Sent with an explicit mapping, which is what the wizard sends the moment a user touches
    a picker: an empty mapping and an absent one are different messages, and the schema
    accepts both, so the one the panel really builds is the one worth pushing through.
    """
    assert imported
    result = await call(
        client,
        "swap/preview",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        mapping={"paddle": "paddle"},
    )

    assert_shape(result, "SwapPreview")
    assert_shape(result["proposal"], "SwapProposal")
    assert result["proposal"]["mappings"], "no control was mapped, so no shape was checked"
    for mapping in result["proposal"]["mappings"]:
        assert_shape(mapping, "SwapMapping")
    assert result["proposal"]["rewrites"], "no rule was rewritten, so no shape was checked"
    for rewrite in result["proposal"]["rewrites"]:
        assert_shape(rewrite, "SwapRewrite")


async def test_the_controls_the_mapping_step_offers_come_from_the_device_detail(
    client: Any, imported: str, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The picker is built from `devices/get` on the replacement, so it has to answer.

    The wizard filters the lifeline out of that list, so the assertion is that there is
    something left after it does: a picker with nothing selectable in it is a mapping step
    a user cannot complete.
    """
    assert imported
    detail = await call(client, "devices/get", device_id=zwave_js_devices[REPLACEMENT].id)

    selectable = [
        emitter["emitter_id"] for emitter in detail["emitters"] if not emitter["is_lifeline"]
    ]
    assert selectable
    preview = await call(
        client,
        "swap/preview",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
    )
    for mapping in preview["proposal"]["mappings"]:
        assert mapping["new_emitter_id"] is None or mapping["new_emitter_id"] in selectable


async def test_the_apply_the_wizard_sends_is_accepted_and_answers_the_applied_interface(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """The whole message: the mapping, the token from the preview, and no lossy flag.

    No `accept_lossy`, because this swap loses nothing and the wizard only sets that flag
    when a person has ticked the box under the list of what is lost.
    """
    assert imported
    preview = await call(
        client,
        "swap/preview",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        mapping={"paddle": "paddle"},
    )
    assert not preview["proposal"]["is_lossy"]

    applied = await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        mapping={"paddle": "paddle"},
        plan_token=preview["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert_shape(applied, "SwapApplied")
    assert applied["rules_rewritten"]


async def test_a_lossy_swap_needs_the_flag_the_wizard_only_sets_from_a_tick_box(
    client: Any,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """The gate the review step is built around, pushed through the real handler.

    The user picks a control that carries less than the rules ask for, which is the only
    way a swap becomes lossy from this screen. Without the flag the apply is refused, which
    is exactly what makes the tick box mean something.
    """
    await import_profile(client, imported_profile())
    new_device_id = zwave_js_devices[REPLACEMENT].id
    # The config button on a VZW32-SN carries on/off and nothing else, so choosing it in
    # the mapping step loses dimming. This is a mapping the user made, which is the only
    # way a swap becomes lossy from this screen.
    preview = await call(
        client,
        "swap/preview",
        old_identity=old_identity(),
        new_device_id=new_device_id,
        mapping={"paddle": "g7"},
    )
    assert preview["proposal"]["is_lossy"], "this fixture was supposed to lose something"

    error = await refused(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=new_device_id,
        mapping={"paddle": "g7"},
        plan_token=preview["plan"]["token"],
    )

    assert error["translation_key"] == "swap_would_lose_work"
