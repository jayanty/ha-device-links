"""The `MqttClient` the Zigbee adapter is written against, over Home Assistant's `mqtt`.

`backends/zigbee2mqtt.py` takes a two-method client rather than reaching into the `mqtt`
integration itself, for the same reason `zwave.py` takes a driver: the seam is what lets the
adapter be exercised against `tests/fakes/zigbee.py` with no broker anywhere. This module is
the one place that knows how Home Assistant subscribes, and it is the Zigbee equivalent of
`zwave_accessor.py`: all the coupling to another integration, in one file, with a test.

**Everything from `homeassistant.components.mqtt` is imported inside a function**, exactly as
`zwave_accessor.async_get_node` imports `zwave_js`. Home Assistant installs an integration's
requirements when that integration is set up, so on a house with no MQTT broker the `mqtt`
package's own dependencies are absent and a module-scope import would raise
`ModuleNotFoundError` and take the whole of Device Links down with it. This integration
explicitly supports Z-Wave-only installs, so that is not a theoretical shape.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.components.mqtt.models import ReceiveMessage

__all__ = ["HomeAssistantMqttClient", "async_mqtt_is_available", "deliver_text"]


def async_mqtt_is_available(hass: HomeAssistant) -> bool:
    """Say whether the `mqtt` integration is loaded and can be subscribed to.

    A plain membership test rather than a call into `mqtt`, because it has to be answerable
    on a system where the package cannot even be imported. False is not an error: a house
    with no broker is a house with no Zigbee2MQTT, and Device Links adapts what is there
    (see `__init__.py`, which says the same thing about `zwave_js`).
    """
    return "mqtt" in hass.config.components


class HomeAssistantMqttClient:
    """Publish and subscribe through the broker the `mqtt` integration is already on.

    No second connection, no credentials of our own, and nothing to unload beyond the
    subscriptions themselves: the same shape as Decision D2 (a) for Z-Wave, for the same
    reason. `async_subscribe` returns the unsubscribe callable Home Assistant gave us, which
    the adapter keeps and calls at unload.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the Home Assistant instance whose broker this speaks through."""
        self._hass = hass

    async def async_publish(self, topic: str, payload: str) -> None:
        """Publish one message, at the integration's default QoS and not retained."""
        # Imported here, not at module scope: see the module docstring.
        from homeassistant.components import mqtt  # noqa: PLC0415

        await mqtt.async_publish(self._hass, topic, payload)

    async def async_subscribe(
        self, topic: str, callback: Callable[[str, str], None]
    ) -> Callable[[], None]:
        """Subscribe to a topic filter, returning the unsubscribe callable.

        The adapter wants a topic and text, so the `ReceiveMessage` is unwrapped by
        `deliver_text` on the way through.
        """
        # Imported here, not at module scope: see the module docstring.
        from homeassistant.components import mqtt  # noqa: PLC0415

        return await mqtt.async_subscribe(self._hass, topic, partial(deliver_text, callback))


def deliver_text(callback: Callable[[str, str], None], message: ReceiveMessage) -> None:
    """Hand one received message to the adapter as a topic and a string.

    A payload that is not text is dropped rather than decoded. Home Assistant decodes with
    UTF-8 by default and drops what will not decode, so this is the case where somebody
    subscribed us to a binary topic or asked for no encoding: guessing one would hand the
    adapter bytes it could only fail to parse, and dropping it leaves the retained payload
    it is really waiting for to arrive.

    Module level rather than a closure inside the subscription so that it can be exercised
    on its own: the branch that matters here is the one Home Assistant will not produce.
    """
    if isinstance(message.payload, str):
        callback(message.topic, message.payload)
