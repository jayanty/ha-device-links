"""A fake Zigbee2MQTT bridge, built from the Stage 0 G1 capture of Jayant's real network.

**This fake is a model of an unobserved system, and that is the most important thing about
it.** The read half is faithful: `tests/fixtures/g1_bridge.json` is a byte-for-byte capture
of the retained `bridge/devices`, `bridge/groups`, `bridge/info` and `bridge/state` topics
of Zigbee2MQTT 2.14.1, so what this serves on subscribe is what a real bridge served. The
write half is not observed at all. Stage 0 item G2 was never approved, so **no bind has ever
been performed on this network**, and every request shape, every response shape and every
failure mode below comes from the Zigbee2MQTT documentation rather than from a wire capture.
That is assumption **A2** in `docs/open-items.md` and issue **#6**.

The consequence is worth stating plainly, because it decides what a passing test means: a
test that passes against this fake proves the adapter agrees with the model, and proves
nothing whatever about the bridge. When G2 finally runs, **this file is what gets
corrected**, and the adapter and its tests are corrected with it. So nothing here is made
convenient: where the documentation says something awkward, the awkward thing is what is
reproduced.

Four documented behaviours it reproduces on purpose:

1. **A response is correlated by `transaction` and by nothing else.** MQTT is fire and
   forget and responses are not ordered, so an adapter that matched on arrival order would
   pass against a simpler fake and mismatch two concurrent binds against a real bridge.
2. **A partial failure reports success.** `status` is `error` only when every cluster
   failed; one cluster of three failing comes back as `status: "ok"` with that cluster in
   `failed`. This is the single most likely way to ship a Zigbee bug that looks like it
   works, so `fail_clusters` exists to make it happen on demand.
3. **A request can get no response at all.** `silent` drops the response, which is what a
   restarted add-on, a lost message or a bridge that never answered look like from here.
4. **A device that is not listening refuses.** `unresponsive` makes the bind come back as
   an error naming the device, which is what a sleeping battery source produces (E22).

It also does one thing deliberately **not** to protect the caller: it will happily modify a
group with no `dl_` prefix. A real bridge would. Making the fake refuse would make the
adapter's own refusal untested, and that refusal is what makes managed groups safe to ship.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Final

from custom_components.device_links.backends import zigbee_protocol as zp

FIXTURE: Final = Path(__file__).resolve().parent.parent / "fixtures" / "g1_bridge.json"

# The base topic the capture was taken from. Configurable everywhere, because a second
# Zigbee2MQTT instance uses a different one and the identifier format embeds it (E25).
DEFAULT_BASE_TOPIC: Final = "zigbee2mqtt"

# Where a group id starts when the bridge allocates one. Zigbee2MQTT picks the lowest free
# id from 1; no group exists on this network yet, so the first managed group gets 1.
FIRST_GROUP_ID: Final = 1

type Payload = Mapping[str, Any]
type MessageCallback = Callable[[str, str], None]


class FakeBridge:
    """One Zigbee2MQTT bridge, holding real state and answering real request topics.

    Holds the devices, the groups and the bridge state, applies bind, unbind and group
    requests to them, and republishes the retained topics whenever any of them changes,
    exactly as the real bridge does. Nothing here reaches a network.
    """

    def __init__(
        self,
        *,
        base_topic: str = DEFAULT_BASE_TOPIC,
        devices: Sequence[zp.Device] | None = None,
        groups: Sequence[zp.Group] = (),
        state: str = zp.STATE_ONLINE,
    ) -> None:
        """Build a bridge from the capture, or from devices a test made up."""
        self.base_topic = base_topic
        self.devices: list[MutableMapping[str, Any]] = deepcopy(
            list(devices) if devices is not None else _captured_devices()
        )
        self.groups: list[MutableMapping[str, Any]] = deepcopy(list(groups))
        self.state = state
        self.info: dict[str, Any] = deepcopy(_captured()["info"])

        # What a test asks the bridge to do wrong. Every one of these reproduces a
        # documented behaviour rather than an invented one; see the module docstring.
        self.fail_clusters: set[str] = set()
        self.silent = False
        self.unresponsive: set[str] = set()

        # Report `status: "ok"` even when every cluster failed. The documentation says that
        # cannot happen, and Device Links asks for one cluster at a time, so under the
        # documentation a failure of ours is always total and always an error. This is the
        # case where the documentation is wrong, and it is the exact case in which reading
        # `status` alone ships a bug that looks like it works. Unobserved like everything
        # else here: assumption A2, issue #6.
        self.ok_despite_total_failure = False

        # Every request that was published, so a test can assert that a refusal really
        # refused rather than merely reporting one.
        self.requests: list[tuple[str, Payload]] = []

        self._subscriptions: list[tuple[str, MessageCallback]] = []

    # The MQTT surface the adapter is written against.

    async def async_subscribe(self, topic: str, callback: MessageCallback) -> Callable[[], None]:
        """Subscribe to a topic filter, and deliver what is retained on it straight away.

        Delivering on subscribe is not a convenience: the bridge topics are retained, so a
        real broker does exactly this, and it is the whole reason the backend can come up
        knowing the network without asking anything.
        """
        self._subscriptions.append((topic, callback))
        for retained_topic, payload in self._retained():
            if _matches(topic, retained_topic):
                callback(retained_topic, payload)

        def _unsubscribe() -> None:
            entry = (topic, callback)
            if entry in self._subscriptions:
                self._subscriptions.remove(entry)

        return _unsubscribe

    async def async_publish(self, topic: str, payload: str) -> None:
        """Take one request, apply it, and answer it the way the documentation describes.

        NOTE: everything this method does is modelled from the Zigbee2MQTT documentation
        and has never been performed against hardware. Assumption A2, issue #6.
        """
        body: Payload = json.loads(payload)
        relative = topic.removeprefix(f"{self.base_topic}/")
        self.requests.append((relative, body))
        # A yield, so the adapter's wait is really a wait: a response that arrived before
        # anyone awaited would let a caller that registered its waiter too late still pass.
        await asyncio.sleep(0)
        handler = _HANDLERS.get(relative)
        if handler is None:
            return
        response_topic, response = handler(self, body)
        if self.silent:
            return
        self._deliver(f"{self.base_topic}/{response_topic}", json.dumps(response))

    # What the fake bridge is asked to do.

    def _bind(self, body: Payload) -> tuple[str, dict[str, Any]]:
        """Apply a bind request, one cluster at a time, and report each cluster's fate."""
        return zp.BIND_RESPONSE, self._apply_binding(body, adding=True)

    def _unbind(self, body: Payload) -> tuple[str, dict[str, Any]]:
        """Apply an unbind request, which also drops the reporting the bridge configured."""
        return zp.UNBIND_RESPONSE, self._apply_binding(body, adding=False)

    def _apply_binding(self, body: Payload, *, adding: bool) -> dict[str, Any]:
        """Bind or unbind each cluster the request names, and report what happened.

        Per cluster, because that is how the bridge reports it: `failed` is a list of
        cluster names and `status` is `error` only when it holds every cluster asked for.
        """
        source = self._device_named(str(body["from"]))
        if source is None:
            return _error(body, f"Device '{body['from']}' does not exist")
        if source["ieee_address"] in self.unresponsive:
            return _error(body, f"Failed to bind, {body['from']} did not respond")
        target = self._target_of(body)
        if target is None:
            return _error(body, f"Device or group '{body['to']}' does not exist")

        endpoint = int(body["from_endpoint"])
        requested = [str(cluster) for cluster in body["clusters"]]
        failed = [
            cluster
            for cluster in requested
            if cluster in self.fail_clusters
            # Only a bind consults what the endpoint drives. An unbind is a ZDO request
            # about an entry that is already there, and a device whose reported clusters
            # have changed since it was written must still be able to have it taken off.
            or (adding and not zp.emits(source, endpoint, cluster))  # type: ignore[arg-type]
        ]
        for cluster in requested:
            if cluster not in failed:
                self._write_binding(source, endpoint, cluster, target, adding=adding)
        if requested and len(failed) == len(requested) and not self.ok_despite_total_failure:
            return _error(body, "Failed to bind, no cluster could be written", failed=failed)
        self._republish(zp.DEVICES_TOPIC)
        return _ok(body, failed=failed)

    def _write_binding(
        self,
        source: MutableMapping[str, Any],
        endpoint: int,
        cluster: str,
        target: zp.BindingTarget,
        *,
        adding: bool,
    ) -> None:
        """Put one binding on the device, or take it off, leaving the rest alone."""
        bindings: list[dict[str, Any]] = source["endpoints"][str(endpoint)]["bindings"]
        entry = {"cluster": cluster, "target": dict(target)}
        present = entry in bindings
        if adding and not present:
            bindings.append(entry)
        elif not adding and present:
            bindings.remove(entry)

    def _target_of(self, body: Payload) -> zp.BindingTarget | None:
        """Return the binding target a request names, whether it is an endpoint or a group."""
        name = str(body["to"])
        device = self._device_named(name)
        if device is not None:
            return zp.EndpointTarget(
                type="endpoint",
                ieee_address=str(device["ieee_address"]),
                endpoint=int(body["to_endpoint"]),
            )
        group = self._group_named(name)
        if group is not None:
            return zp.GroupTarget(type="group", id=int(group["id"]))
        return None

    def _group_add(self, body: Payload) -> tuple[str, dict[str, Any]]:
        """Create a group, allocating the lowest free id, as the bridge does.

        Deliberately not guarded by the `dl_` prefix. A real bridge would create
        `kitchen` just as readily as `dl_kitchen`, and a fake that refused would make the
        adapter's own refusal untested.
        """
        name = str(body["friendly_name"])
        existing = self._group_named(name)
        if existing is not None:
            return zp.GROUP_ADD_RESPONSE, _error(body, f"Group '{name}' already exists")
        taken = {int(group["id"]) for group in self.groups}
        group_id = next(
            candidate
            for candidate in range(FIRST_GROUP_ID, FIRST_GROUP_ID + 1000)
            if candidate not in taken
        )
        self.groups.append({"id": group_id, "friendly_name": name, "members": []})
        self._republish(zp.GROUPS_TOPIC)
        return zp.GROUP_ADD_RESPONSE, _ok(body, extra={"friendly_name": name, "id": group_id})

    def _group_remove(self, body: Payload) -> tuple[str, dict[str, Any]]:
        """Delete a group, and drop every binding that pointed at it."""
        group = self._group_named(str(body["id"]))
        if group is None:
            return zp.GROUP_REMOVE_RESPONSE, _error(body, f"Group '{body['id']}' does not exist")
        self.groups.remove(group)
        self._drop_bindings_to_group(int(group["id"]))
        self._republish(zp.GROUPS_TOPIC)
        self._republish(zp.DEVICES_TOPIC)
        return zp.GROUP_REMOVE_RESPONSE, _ok(body)

    def _member_add(self, body: Payload) -> tuple[str, dict[str, Any]]:
        """Add one endpoint to a group."""
        return zp.GROUP_MEMBER_ADD_RESPONSE, self._member(body, adding=True)

    def _member_remove(self, body: Payload) -> tuple[str, dict[str, Any]]:
        """Take one endpoint out of a group."""
        return zp.GROUP_MEMBER_REMOVE_RESPONSE, self._member(body, adding=False)

    def _member(self, body: Payload, *, adding: bool) -> dict[str, Any]:
        """Apply one membership change, or say why it could not be applied."""
        group = self._group_named(str(body["group"]))
        if group is None:
            return _error(body, f"Group '{body['group']}' does not exist")
        device = self._device_named(str(body["device"]))
        if device is None:
            return _error(body, f"Device '{body['device']}' does not exist")
        member = {"ieee_address": str(device["ieee_address"]), "endpoint": int(body["endpoint"])}
        members: list[dict[str, Any]] = group["members"]
        if adding and member not in members:
            members.append(member)
        elif not adding and member in members:
            members.remove(member)
        self._republish(zp.GROUPS_TOPIC)
        return _ok(body)

    def _drop_bindings_to_group(self, group_id: int) -> None:
        """Remove every binding pointing at a group that has just been deleted."""
        for device in self.devices:
            for endpoint in device["endpoints"].values():
                endpoint["bindings"] = [
                    binding
                    for binding in endpoint["bindings"]
                    if not (
                        binding["target"].get("type") == zp.TARGET_GROUP
                        and binding["target"].get("id") == group_id
                    )
                ]

    # What a test reaches for.

    def device_named(self, friendly_name: str) -> MutableMapping[str, Any]:
        """Return one device by its friendly name, so a test can read its bindings."""
        device = self._device_named(friendly_name)
        assert device is not None, f"no device called {friendly_name!r}"
        return device

    def bindings_of(self, friendly_name: str, endpoint: int) -> list[dict[str, Any]]:
        """Return the bindings currently on one endpoint of one device."""
        bindings: list[dict[str, Any]] = self.device_named(friendly_name)["endpoints"][
            str(endpoint)
        ]["bindings"]
        return bindings

    def group_named(self, friendly_name: str) -> MutableMapping[str, Any] | None:
        """Return one group by name, or None when the bridge has no such group."""
        return self._group_named(friendly_name)

    def add_binding(
        self, friendly_name: str, endpoint: int, cluster: str, target: Mapping[str, Any]
    ) -> None:
        """Put a binding on a device without going through a request, and republish.

        How a test sets up a starting state, as against exercising the request path. It
        republishes, because a change the bridge did not announce is a change no subscriber
        would ever see.
        """
        self.bindings_of(friendly_name, endpoint).append(
            {"cluster": cluster, "target": dict(target)}
        )
        self._republish(zp.DEVICES_TOPIC)

    def rename(self, ieee_address: str, friendly_name: str) -> None:
        """Rename a device the way a user would, which is what E23 is about."""
        for device in self.devices:
            if device["ieee_address"] == ieee_address:
                device["friendly_name"] = friendly_name
        self._republish(zp.DEVICES_TOPIC)

    def set_power_source(self, ieee_address: str, power_source: str) -> None:
        """Make a device battery powered, which changes what a failed write means (E22)."""
        for device in self.devices:
            if device["ieee_address"] == ieee_address:
                device["power_source"] = power_source
        self._republish(zp.DEVICES_TOPIC)

    def go_offline(self) -> None:
        """Take the bridge down, as a Zigbee2MQTT restart does (E26)."""
        self.state = "offline"
        self._republish(zp.STATE_TOPIC)

    def come_back(self) -> None:
        """Bring the bridge back up, republishing everything it retains."""
        self.state = zp.STATE_ONLINE
        self._republish(zp.STATE_TOPIC)
        self._republish(zp.DEVICES_TOPIC)
        self._republish(zp.GROUPS_TOPIC)

    def add_group(self, friendly_name: str, group_id: int, members: Iterable[Payload] = ()) -> None:
        """Put a group on the bridge without going through a request.

        How a test sets up a group a user made by hand, which the adapter must never touch.
        """
        self.groups.append(
            {"id": group_id, "friendly_name": friendly_name, "members": [dict(m) for m in members]}
        )
        self._republish(zp.GROUPS_TOPIC)

    @property
    def request_count(self) -> int:
        """Return how many requests have been published, refusals included."""
        return len(self.requests)

    @property
    def write_count(self) -> int:
        """Return how many requests that would change the network were published.

        What a refusal test asserts has not moved: a blocked link must be refused before
        anything reaches the bridge, not merely reported after it did.
        """
        return sum(1 for topic, _ in self.requests if topic.startswith("bridge/request/"))

    # Publishing.

    def _retained(self) -> list[tuple[str, str]]:
        """Return every retained topic and its current payload."""
        return [
            (f"{self.base_topic}/{topic}", json.dumps(payload))
            for topic, payload in (
                (zp.DEVICES_TOPIC, self.devices),
                (zp.GROUPS_TOPIC, self.groups),
                (zp.INFO_TOPIC, self.info),
                (zp.STATE_TOPIC, {"state": self.state}),
            )
        ]

    def _republish(self, topic: str) -> None:
        """Publish one retained topic again, because its content changed."""
        full = f"{self.base_topic}/{topic}"
        for retained_topic, payload in self._retained():
            if retained_topic == full:
                self._deliver(full, payload)

    def _deliver(self, topic: str, payload: str) -> None:
        """Hand one message to every subscription whose filter matches it."""
        for filter_topic, callback in list(self._subscriptions):
            if _matches(filter_topic, topic):
                callback(topic, payload)

    def _device_named(self, friendly_name: str) -> MutableMapping[str, Any] | None:
        """Return a device by friendly name, which is how requests address one."""
        return next(
            (device for device in self.devices if device["friendly_name"] == friendly_name), None
        )

    def _group_named(self, friendly_name: str) -> MutableMapping[str, Any] | None:
        """Return a group by friendly name."""
        return next(
            (group for group in self.groups if group["friendly_name"] == friendly_name), None
        )


# Which method answers which request topic. A table rather than a chain of `if`s, so a
# request topic the adapter invents goes unanswered (and times out) rather than falling
# through to the wrong handler.
_HANDLERS: Final[Mapping[str, Callable[[FakeBridge, Payload], tuple[str, dict[str, Any]]]]] = {
    zp.BIND_REQUEST: FakeBridge._bind,
    zp.UNBIND_REQUEST: FakeBridge._unbind,
    zp.GROUP_ADD_REQUEST: FakeBridge._group_add,
    zp.GROUP_REMOVE_REQUEST: FakeBridge._group_remove,
    zp.GROUP_MEMBER_ADD_REQUEST: FakeBridge._member_add,
    zp.GROUP_MEMBER_REMOVE_REQUEST: FakeBridge._member_remove,
}


def _ok(
    body: Payload, *, failed: Sequence[str] = (), extra: Payload | None = None
) -> dict[str, Any]:
    """Return a successful response, which may still carry failed clusters.

    This is the shape that makes the naive check wrong: `status` is `ok` and `failed` is
    not empty, so a bind where one cluster of two landed reports success.
    """
    data = {key: value for key, value in body.items() if key != "transaction"}
    if "clusters" in body:
        data["failed"] = list(failed)
    if extra is not None:
        data.update(extra)
    return {"data": data, "status": zp.STATUS_OK, "transaction": body.get("transaction")}


def _error(body: Payload, message: str, *, failed: Sequence[str] = ()) -> dict[str, Any]:
    """Return a total failure, which is the only thing `status: error` ever means."""
    data = {key: value for key, value in body.items() if key != "transaction"}
    if "clusters" in body:
        data["failed"] = list(failed) or list(body.get("clusters", []))
    return {
        "data": data,
        "status": zp.STATUS_ERROR,
        "error": message,
        "transaction": body.get("transaction"),
    }


def _matches(filter_topic: str, topic: str) -> bool:
    """Say whether an MQTT topic filter matches a topic, `+` and `#` included.

    Real filter semantics rather than string equality, because the adapter subscribes to
    `bridge/response/#` and a fake that only did exact matches would let a wrong
    subscription pass.
    """
    wanted = filter_topic.split("/")
    actual = topic.split("/")
    for position, part in enumerate(wanted):
        if part == "#":
            return True
        if position >= len(actual):
            return False
        if part != "+" and part != actual[position]:
            return False
    return len(wanted) == len(actual)


def _captured() -> dict[str, Any]:
    """Return the G1 capture's data section."""
    data: dict[str, Any] = json.loads(FIXTURE.read_text())["data"]
    return data


def _captured_devices() -> list[zp.Device]:
    """Return the 24 devices the capture recorded, exactly as the bridge reported them."""
    devices: list[zp.Device] = _captured()["devices"]
    return devices


def build_bridge_from_fixture(**kwargs: Any) -> FakeBridge:
    """Return a bridge holding Jayant's Zigbee network as the G1 capture found it."""
    return FakeBridge(**kwargs)
