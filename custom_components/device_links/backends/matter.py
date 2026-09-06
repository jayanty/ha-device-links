"""The Matter adapter: the only module that talks to a real Matter fabric.

Like `backends/zwave.py` and `backends/zigbee2mqtt.py`, this is meant to be thin. Everything
that can be decided without a radio already lives in `matter_protocol.py`, `compiler.py` and
`planner.py`, where it is tested against the Stage 0 M1 capture; what is left here is read,
cache, correlate, write.

Four things it does that nothing else may:

- **It reads through `read_attribute`, and unwraps the answer in one place.** The client
  answers with a mapping keyed by the attribute path rather than with the value, so an
  adapter that treated the mapping as the value would read every list as "not a list", which
  looks like "this device has no client clusters" rather than like an error. Stage 0 hit
  that; `_read` is the one place it is unwrapped.
- **It caches what it read, and reads as little as it can.** A Matter attribute read goes to
  the device, and the coordinator reads every device of every backend at setup, so a naive
  adapter would spend hundreds of radio round trips before the integration finished loading.
  So a node's descriptor lists are read once and kept, refreshed only when the fabric says
  that node changed or when a deep read asks for it, and **an endpoint's client list is read
  only where it could matter**: an endpoint that serves no Binding cluster can never be a
  control, whatever it drives. On the M1 fabric that is 96 reads at setup rather than 260.
- **It writes the access grant before the binding, and cannot do otherwise.** E27 says a
  rejected grant must leave no partial state. `matter_protocol.binding_for` will not build a
  Binding list without a `GrantReceipt`, and a receipt cannot exist without an Access Control
  list read back from the target that carries the grant, so the ordering is a property of the
  types rather than of the order two calls happen to be written in.
- **It never touches an Access Control entry with Administer privilege.** That is the
  controller's own entry: removing it orphans the device from Home Assistant entirely
  (CLAUDE.md Section 3 rule 4). The pure module refuses to build a list that drops or alters
  one, and the receipt refuses to confirm a write that did.

**Every write path here is modelled, not observed.** No Binding list and no Access Control
entry has ever been written on this fabric: Stage 0 item M1 was read-only, and every Matter
write is behind an options flag that defaults to off (FR-B7, Decision D11). See assumption A9
in `docs/open-items.md`. Each write path says so again where it is.

It takes a `MatterClient` rather than reaching into Home Assistant's `matter` integration
itself, for the same reason the other two adapters take a driver and a broker client: the
seam is what makes the adapter testable against `tests/fakes/matter.py`, and
`backends/matter_client.py` is the one place that knows how the real one is reached.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Final

from custom_components.device_links.backends import matter_protocol as mp
from custom_components.device_links.backends.base import (
    BackendDevice,
    LinkCheck,
    LinkResult,
    LinkResultStatus,
    ObservedDevice,
    SettingResult,
    SettingValue,
    SystemScope,
)
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Diagnostic,
    Link,
    LinkTarget,
    ObservedLink,
)

if TYPE_CHECKING:
    from custom_components.device_links.backends.matter_client import (
        MatterClient,
        MatterNodeView,
    )
    from custom_components.device_links.profile_db import MatterProfileEntry, ProfileDatabase

_LOGGER = logging.getLogger(__name__)

# The device registry namespace Matter's devices live in, and the two halves of the
# identifier the `matter` integration registers around the operational instance id
# (Stage 0 item P2). The fabric id is read live rather than stored, because
# re-commissioning changes it and a stored one would point at a device that no longer
# exists under that name.
UPSTREAM_DOMAIN: Final = "matter"
DEVICE_ID_PREFIX: Final = "deviceid"
DEVICE_ID_SUFFIX: Final = "MatterNodeDevice"


class MatterBackendError(Exception):
    """The fabric cannot answer, or was asked about a node it does not have.

    Raised rather than returned by the read path, exactly as `ZWaveAccessorError` and
    `ZigbeeBackendError` are: a read that answered "this device holds nothing" for a device
    it could not see is how a planner comes to remove a whole network.
    """


class MatterNodeUnavailableError(MatterBackendError):
    """The node is on the fabric and is not answering (E29).

    A separate type because a write to one is `pending` rather than `failed`: nothing has
    gone wrong, the device is asleep or out of range, and the write is worth trying again
    when it is back.
    """


@dataclass(frozen=True, slots=True)
class _Granted:
    """A confirmed access grant, and whether this attempt is the one that wrote it.

    `written` is what decides whether a binding that then fails may take the grant back
    again. A grant that was already there belongs to whatever put it there, which may be a
    link of ours that is working: rolling that back over an unrelated failure would break it.
    """

    receipt: mp.GrantReceipt
    written: bool


@dataclass(slots=True)
class _Subscription:
    """Whether a subscription is still live, for the callback already in flight.

    The client dispatches to a copy of its listener list, so a callback delivered in the
    burst being processed still arrives after the unsubscribe. At a config entry unload that
    is a callback reaching a coordinator that has already torn itself down, which is the leak
    that survives a reload and confuses everyone.
    """

    live: bool = True


class MatterBackend:
    """One Matter fabric, as the `Backend` protocol sees it.

    Constructing it does no I/O and there is nothing to start: the client already holds the
    node list, and everything else is read when it is first asked for.
    """

    def __init__(
        self,
        *,
        client: MatterClient,
        profiles: ProfileDatabase | None = None,
        writes_enabled: bool = False,
    ) -> None:
        """Hold what this adapter needs, and read nothing yet.

        `writes_enabled` is FR-B7 and Decision D11, and it defaults to off here as well as in
        the options flow. Two defaults saying the same thing is deliberate: a backend built
        by a test that forgot the flag must refuse to write, exactly as a house whose owner
        has not turned it on does.
        """
        self._client = client
        self._profiles = profiles
        self._writes_enabled = writes_enabled

        # What has been read off each node, by node id. Kept because a Matter attribute read
        # goes to the device: see the module docstring.
        self._views: dict[int, mp.Node] = {}

    # Reading.

    async def async_devices(self) -> list[BackendDevice]:
        """Return every node on this fabric that a rule could name.

        No I/O: the client holds the node list, so this is the one call in the read path
        that costs nothing. Unavailable nodes are listed too, because a node that is asleep
        is still a device somebody wrote a rule about; it is the read of one that fails.
        """
        return [BackendDevice(handle=self._handle(node)) for node in self._client.get_nodes()]

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        """Return what this node can drive and what it can be made to do."""
        node_id = self._node_id(handle)
        view = await self._view(node_id)
        warnings: list[str] = []
        emitters = mp.resolve_emitters(view, self._entry_of(view), warnings=warnings)
        for warning in warnings:
            _LOGGER.debug("%s: %s", handle.identity, warning)
        if not emitters:
            # The most surprising thing about Matter on a real fabric, said once per read
            # at debug: most Matter devices are not binding sources, including two the PRD
            # expected to be. An empty control list with no reason anywhere is what makes
            # somebody think the integration is broken rather than that their switch is
            # not one.
            #
            # Said here rather than in `derive_emitters` because of what this adapter does
            # not read: an endpoint that serves no Binding cluster never has its client
            # list read at all (see `_read_view`), so the pure module cannot tell "drives
            # nothing" from "drives something and has nowhere to keep a link" on one of
            # those, and this is the sentence that is true either way.
            _LOGGER.debug(
                "%s offers no control Device Links can bind: no endpoint of it both drives "
                "a cluster this integration understands and serves a Binding cluster, so it "
                "cannot be the source of a Matter link",
                handle.identity,
            )
        return DeviceCapabilities(
            handle=handle,
            emitters=tuple(emitters),
            receivable=mp.receivable_features(view),
            # Long Range is a Z-Wave inclusion mode and has no Matter equivalent, so this is
            # False rather than unknown: nothing about a Matter node can make it true.
            is_long_range=False,
            # A Matter node has no numbered parameter list, so there is nothing here to
            # adapt. See `async_write_setting`.
            settings={},
            # A Matter binding always names a target endpoint, so a link that reaches this
            # node has to have one even where nobody was asked which (open items T50, T56).
            receiving_endpoint=mp.receiving_endpoint(view),
        )

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        """Return the bindings really on this node now.

        `deep` re-reads the node's Binding lists from the device rather than answering from
        what this adapter last read, which is what makes it worth its radio time. There is no
        third state here, unlike the Zigbee adapter: the read either reaches the device and
        is a confirmation, or it raises and the coordinator keeps what it had and marks the
        device unavailable. Nothing is reported as verified that was not.

        Access Control entries are deliberately **not** observed links. An entry grants
        access rather than carrying a command, it lives on the other device from the binding
        it permits, and its subject is the controller rather than a device in anybody's
        registry. It is read fresh on the write path, where it decides something, and never
        cached.
        """
        node_id = self._node_id(handle)
        view = await self._view(node_id, refresh=deep)
        return ObservedDevice(
            handle=handle,
            links=tuple(self._observed_links(handle, view)),
            settings={},
            deep_verified=deep,
        )

    def _observed_links(self, handle: DeviceHandle, view: mp.Node) -> list[ObservedLink]:
        """Turn one node's Binding lists into the links the planner diffs against.

        One binding becomes **one link per feature its cluster carries**, so a bound
        LevelControl produces both a level-set link and a hold-to-dim link, exactly as a
        bound `genLevelCtrl` does on Zigbee. That is what the binding really does, and it is
        what makes a rule asking for both converge.

        `is_system` is False for every one of them, and that is a statement rather than a
        default. Matter's system entry is the controller's Administer grant, which lives in
        the Access Control list and is not a binding at all: no binding on this fabric is
        ever the controller's, so none is ever protected as one. What protects the Administer
        entry is `matter_protocol._checked`, which no write can route around.

        `managed_by` stays None. Only the coordinator knows which profile is active and which
        rule claims which fingerprint, and a guess here is what makes somebody else's binding
        removable.
        """
        links: list[ObservedLink] = []
        for endpoint in mp.endpoint_ids(view):
            for entry in mp.parse_bindings(view, endpoint):
                target = self._binding_target(entry)
                if target is None:
                    _LOGGER.debug(
                        "%s endpoint %s holds a binding naming neither a node nor a group, "
                        "so there is nothing to report it against",
                        handle.identity,
                        endpoint,
                    )
                    continue
                cluster = entry.cluster if entry.cluster is not None else 0
                links.extend(
                    ObservedLink(
                        backend=BackendId.MATTER,
                        source=handle,
                        source_endpoint=endpoint,
                        emitter_id=self._emitter_id_of(view, endpoint),
                        emitter_group=str(cluster),
                        target=target,
                        feature=feature,
                        is_system=False,
                        managed_by=None,
                    )
                    for feature in sorted(mp.features_of_binding(cluster))
                )
        return links

    def _binding_target(self, entry: mp.BindingEntry) -> LinkTarget | None:
        """Return what a binding points at, or None when it points at nothing addressable.

        A group entry gets a handle for the group, for the reason the Zigbee adapter gives:
        the entry is on the device, and a binding that produces no link is device state
        nothing in the product can see, list as unmanaged, or plan to remove. Device Links
        writes none of them, because Matter multicast needs group keys distributed at
        commissioning time, which is not a link.
        """
        if entry.node is not None and entry.endpoint is not None:
            return LinkTarget(handle=self._handle_of_node_id(entry.node), endpoint=entry.endpoint)
        if entry.group is not None:
            return LinkTarget(handle=mp.group_handle(entry.group), endpoint=None)
        return None

    def _emitter_id_of(self, view: mp.Node, endpoint: int) -> str:
        """Return the id of the control that drives from this endpoint.

        Resolved through the same path `async_capabilities` uses, so an observed link names
        the control a rule would name rather than a second spelling of it.
        """
        for emitter in mp.resolve_emitters(view, self._entry_of(view)):
            if emitter.endpoint == endpoint:
                return emitter.emitter_id
        return f"ep{endpoint}"

    async def _view(self, node_id: int, *, refresh: bool = False) -> mp.Node:
        """Return what this node reports, reading it only when there is a reason to.

        Raises for a node that is not on the fabric and for one that is not answering, told
        apart because a write to the second is `pending` rather than `failed` (E29).
        """
        node = self._node(node_id)
        if not node.available:
            raise MatterNodeUnavailableError(f"Matter node {node_id} is not reachable")
        cached = self._views.get(node_id)
        if cached is not None and not refresh:
            return cached
        # Dropped before the read rather than replaced after it. A refresh that raises part
        # way through would otherwise leave the previous view in place, and the next caller
        # that did not ask for a refresh would be served a description of the node from
        # before whatever made the read fail.
        self._views.pop(node_id, None)
        view = await self._read_view(node)
        self._views[node_id] = view
        return view

    async def _read_view(self, node: MatterNodeView) -> mp.Node:
        """Read one node's descriptor lists and Binding lists, in as few reads as possible.

        Two passes rather than one, and the saving is the whole reason for the shape. The
        server list of every endpoint is read first, because it says whether that endpoint
        has a Binding cluster; only the endpoints that do can ever be a control, so only
        those have their client list and their Binding list read. On the M1 fabric that is
        one extra pair of reads rather than 92.

        A read that fails takes the whole node with it rather than leaving a half described
        one. A node whose cluster lists are partly known would refuse links with
        "this target cannot receive that", which is a wrong answer stated confidently; a node
        that did not answer is reported as unavailable, which is true.

        Endpoint 0 is read like any other. It can never be a control and never a target, and
        the cheaper thing would be to skip it, but its server list is what a future reader of
        a diagnostic needs to see that the node really does hold an Access Control cluster.
        """
        node_id = node.node_id
        endpoints = sorted(int(endpoint) for endpoint in node.endpoints)
        servers = await asyncio.gather(
            *(self._read(node_id, mp.server_list_path(endpoint)) for endpoint in endpoints)
        )
        bindable = [
            endpoint
            for endpoint, served in zip(endpoints, servers, strict=True)
            if mp.BINDING_CLUSTER in _ints(served)
        ]
        clients = await asyncio.gather(
            *(self._read(node_id, mp.client_list_path(endpoint)) for endpoint in bindable),
            *(self._read(node_id, mp.binding_path(endpoint)) for endpoint in bindable),
        )
        client_lists = dict(zip(bindable, clients[: len(bindable)], strict=True))
        binding_lists = dict(zip(bindable, clients[len(bindable) :], strict=True))
        return mp.Node(
            node_id=node_id,
            available=node.available,
            name=node.name or "",
            vendor=_vendor(node),
            product=_product(node),
            endpoints={
                str(endpoint): mp.EndpointClusters(
                    client_list=_ints(client_lists.get(endpoint)),
                    server_list=_ints(served),
                )
                for endpoint, served in zip(endpoints, servers, strict=True)
            },
            bindings={str(endpoint): value for endpoint, value in binding_lists.items()},
        )

    async def _read(self, node_id: int, path: str) -> object:
        """Read one attribute and unwrap it.

        `read_attribute` answers with a mapping keyed by the attribute path rather than with
        the value (Stage 0 M1). **This is the only place that is unwrapped**, because reading
        the mapping as the value silently turns every list into "not a list", which reads as
        a device with no clusters rather than as an error.
        """
        answer = await self._client.read_attribute(node_id, path)
        if isinstance(answer, Mapping) and path in answer:
            return answer[path]
        return answer

    # Writing, and the refusals that come before it.
    #
    # NOTE: everything from here to the end of this section is modelled from the Matter
    # specification and from the shape the Stage 0 M1 reads came back in. No Binding list and
    # no Access Control entry has ever been written on this fabric, and every one of these
    # paths is behind an options flag that defaults to off (FR-B7, Decision D11). See
    # assumption A9 in docs/open-items.md. `tests/fakes/matter.py` is the model these are
    # proved against rather than evidence about a device.

    async def async_check_link(self, link: Link) -> LinkCheck:
        """Say whether this link could be written, without writing it.

        Matter has no equivalent of the Z-Wave driver's `checkAssociation`: nothing asks a
        node whether a binding would be allowed. So a check here is everything that can be
        answered from what has already been read, which turns out to be most of it: whether
        writes are enabled at all, whether both nodes are on the fabric and answering,
        whether the source really drives the cluster and the target really serves it.

        What it deliberately does not answer is whether the link is already there, and
        whether the target's Access Control list has room. The first is not what a check is
        about. The second would cost four reads against a device to answer a question that
        the write re-asks anyway, and the answer can change in between.
        """
        refusal = await self._refusal(link, adding=True)
        if refusal is not None:
            return LinkCheck(ok=False, reason=refusal)
        return LinkCheck(ok=True)

    async def async_add_link(self, link: Link) -> LinkResult:
        """Bind one cluster, having first granted the access it needs.

        The order of the refusals is the safety rule, and it is this and no other:

        1. Writes being turned off, because nothing else matters if they are (FR-B7).
        2. A self-binding, which can never be what the user meant.
        3. A target that names no endpoint or names a group, neither of which this
           integration can express as a Matter binding.
        4. A node the fabric does not list, or one that is not answering.
        5. Already present, which is where a state-dependent answer belongs: after the
           absolute refusals so neither can be masked by "it is already there", and before
           the capability checks so an entry that exists is never reported as blocked.
        6. Whether the source really drives the cluster, has somewhere to hold the binding,
           and the target really serves it.
        7. The Binding list being full (E28).
        8. The access grant on the **target**, which must succeed before anything is written
           to the source (E27).
        9. The binding itself, and a read-back to confirm it.

        NOTE: modelled, never observed. Assumption A9.
        """
        return await self._write(link, adding=True)

    async def async_remove_link(self, link: Link) -> LinkResult:
        """Unbind one cluster, and then take back the access it needed.

        The reverse order of the add, deliberately. Taking the binding off first means a
        failure part way through leaves a permission that permits nothing, which is untidy;
        taking the grant away first would leave a binding that the target refuses, which
        looks like a broken switch. The grant is narrowed on every removal, including one
        where the binding had already gone, so a removal interrupted half way is finished by
        the next one rather than leaving the grant behind forever.

        NOTE: modelled, never observed. Assumption A9.
        """
        return await self._write(link, adding=False)

    async def _write(self, link: Link, *, adding: bool) -> LinkResult:
        """Bind or unbind one cluster, refusing in the documented order."""
        refusal = self._absolute_refusal(link)
        if refusal is not None:
            return LinkResult(status=LinkResultStatus.BLOCKED, reason=refusal)
        source = await self._readable(link, adding=adding)
        if isinstance(source, LinkResult):
            return source
        present = self._is_present(link, source)
        if not adding:
            return await self._unbind(link, source, present=present)
        if present:
            return LinkResult(status=LinkResultStatus.ALREADY_PRESENT)
        refusal = await self._capability_refusal(link)
        if refusal is not None:
            return LinkResult(status=LinkResultStatus.BLOCKED, reason=refusal)
        return await self._bind(link, source)

    async def _readable(self, link: Link, *, adding: bool) -> mp.Node | LinkResult:
        """Return the source node as it reads now, or the result of not being able to.

        The source is re-read rather than taken from the cache: this is the moment its
        Binding list decides something, and another controller may have changed it since.

        **The target is required to answer only for an add**, and that asymmetry is the
        point. A binding whose target has been decommissioned is exactly the leftover
        somebody wants to take off their switch, and it lives entirely on the source: a
        removal that insisted on reading the departed device would leave the entry on the
        switch with nothing in the product able to remove it. The access grant on that
        target goes with the device, and `_revoke` fails to read it and says so in the log
        rather than in the result.
        """
        try:
            source = await self._view(self._node_id(link.source), refresh=True)
            if adding:
                await self._view(self._node_id(link.target.handle))
        except MatterNodeUnavailableError:
            return self._pending(link)
        except MatterBackendError:
            return LinkResult(
                status=LinkResultStatus.BLOCKED,
                reason=Diagnostic("matter_unknown_device", _about_matter(link)),
            )
        except Exception as error:  # a client may raise whatever its server raised
            # A node that is listed and answering and then does not answer this read. The
            # executor would catch it and report the link as having failed unexpectedly;
            # this reports the same thing with the fabric's own words attached, which is
            # what every other failure on this path does.
            return self._failed(link, error)
        return source

    async def _bind(self, link: Link, source: mp.Node) -> LinkResult:
        """Grant the access, then write the binding, then read it back.

        NOTE: modelled, never observed. Assumption A9.
        """
        full = self._full(link, mp.parse_bindings(source, link.source_endpoint))
        if full is not None:
            return LinkResult(status=LinkResultStatus.BLOCKED, reason=full)
        granted = await self._grant(link)
        if isinstance(granted, LinkResult):
            return granted
        result = await self._write_binding(link, granted=granted)
        if result.status is LinkResultStatus.FAILED and granted.written:
            # E27 the rest of the way: the grant was written for this binding and the
            # binding did not happen, so the grant is taken back rather than left holding
            # one of the target's few Access Control entries for a link that does not
            # exist. Only when this attempt is what wrote it: a grant that was already
            # there belongs to whatever put it there, which may be a link that works.
            await self._revoke(link)
        return result

    def _full(self, link: Link, existing: Sequence[mp.BindingEntry]) -> Diagnostic | None:
        """Return why this endpoint cannot hold another binding, or None when it can (E28)."""
        if len(existing) < mp.BINDING_TABLE_CAPACITY:
            return None
        return Diagnostic(
            "matter_binding_full", {**_about_matter(link), "used": str(len(existing))}
        )

    async def _write_binding(self, link: Link, *, granted: _Granted) -> LinkResult:
        """Write the Binding list with this link's entry in it, and read it back.

        The list is read again here rather than taken from the read that came before the
        grant. Writing an attribute replaces the whole of it, and another controller can
        have added an entry while the access grant was being written: merging into the
        older read would take that entry off the device, which is precisely what FR-B7 says
        this integration must not do.

        NOTE: modelled, never observed. Assumption A9.
        """
        wanted = self._wanted(link)
        node_id = self._node_id(link.source)
        try:
            existing = await self._bindings_now(node_id, link.source_endpoint)
        except Exception as error:  # a client may raise whatever its server raised
            return self._failed(link, error)
        full = self._full(link, existing)
        if full is not None:
            return LinkResult(status=LinkResultStatus.BLOCKED, reason=full)
        merged = mp.binding_for(
            existing,
            wanted=wanted,
            source_node_id=node_id,
            receipt=granted.receipt,
        )
        if merged is None:
            return LinkResult(status=LinkResultStatus.ALREADY_PRESENT)
        try:
            await self._client.write_attribute(
                node_id, mp.binding_path(link.source_endpoint), mp.binding_payload(merged)
            )
            written = await self._view(node_id, refresh=True)
        except Exception as error:  # a client may raise whatever its server raised
            return self._failed(link, error)
        if wanted not in mp.parse_bindings(written, link.source_endpoint):
            # The write was accepted and the entry is not there. Reported as failed rather
            # than applied, because the alternative is a rule the panel says is fine and a
            # paddle that does nothing.
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic("matter_binding_not_confirmed", _about_matter(link)),
            )
        return LinkResult(status=LinkResultStatus.APPLIED)

    async def _bindings_now(self, node_id: int, endpoint: int) -> tuple[mp.BindingEntry, ...]:
        """Return one endpoint's Binding list as it reads at this moment.

        One attribute rather than the whole node, because this is asked immediately before a
        write and re-reading twenty endpoints to learn about one would spend a round trip
        each for nothing.
        """
        return mp.parse_binding_list(await self._read(node_id, mp.binding_path(endpoint)))

    async def _unbind(self, link: Link, source: mp.Node, *, present: bool) -> LinkResult:
        """Take the binding off, then narrow the grant that permitted it.

        NOTE: modelled, never observed. Assumption A9.
        """
        wanted = self._wanted(link)
        removed = False
        if present:
            try:
                existing = await self._bindings_now(
                    self._node_id(link.source), link.source_endpoint
                )
            except Exception as error:  # a client may raise whatever its server raised
                return self._failed(link, error)
            narrowed = mp.binding_without(existing, wanted=wanted)
            if narrowed is not None:
                try:
                    await self._client.write_attribute(
                        self._node_id(link.source),
                        mp.binding_path(link.source_endpoint),
                        mp.binding_payload(narrowed),
                    )
                    written = await self._view(self._node_id(link.source), refresh=True)
                except Exception as error:  # a client may raise whatever its server raised
                    return self._failed(link, error)
                if wanted in mp.parse_bindings(written, link.source_endpoint):
                    return LinkResult(
                        status=LinkResultStatus.FAILED,
                        reason=Diagnostic("matter_binding_not_confirmed", _about_matter(link)),
                    )
                removed = True
        await self._revoke(link)
        if removed:
            return LinkResult(status=LinkResultStatus.APPLIED)
        return LinkResult(status=LinkResultStatus.ALREADY_PRESENT)

    async def _grant(self, link: Link) -> _Granted | LinkResult:
        """Make sure the target lets this control operate it, and prove that it does.

        Answers with a receipt or with the result the caller should return. The receipt is
        the only way to build a Binding list (E27), and it can only be made from an Access
        Control list read back from the device after the write, so an unwritten or rejected
        grant makes the binding impossible rather than merely unwise.

        The list is read fresh every time and never cached. It is a security boundary, it is
        two entries from full on the fixture's Eve Energy, and another controller can have
        changed it since the last read.

        NOTE: modelled, never observed. Assumption A9.
        """
        node_id = self._node_id(link.target.handle)
        subject = self._node_id(link.source)
        target = self._acl_target(link)
        try:
            before = mp.parse_acl(await self._read(node_id, mp.ACL_PATH))
            capacity = await self._acl_capacity(node_id)
            # Inside the try, and not merely near it: `grant_for` is what refuses to build a
            # list that would drop the controller's own Administer entry, and that refusal
            # arrives as an `AclError` which has to become a failed link rather than an
            # exception out of the adapter.
            outcome = mp.grant_for(before, subject=subject, target=target, capacity=capacity)
            if outcome.refusal is not None:
                return LinkResult(
                    status=LinkResultStatus.BLOCKED, reason=self._acl_refusal(link, outcome)
                )
            after = before
            if outcome.changed and outcome.entries is not None:
                await self._client.write_attribute(
                    node_id, mp.ACL_PATH, mp.acl_payload(outcome.entries)
                )
                after = mp.parse_acl(await self._read(node_id, mp.ACL_PATH))
            return _Granted(
                receipt=mp.confirm_grant(
                    node_id=node_id, subject=subject, target=target, before=before, after=after
                ),
                written=outcome.changed,
            )
        except mp.AclError as error:
            # Includes the two that matter most: a write that lost the controller's own
            # Administer entry, and one that was not scoped to this fabric. Reported as a
            # failure of this link, and the binding that would have followed it is never
            # written, which is the whole of E27.
            _LOGGER.exception(
                "the access grant on Matter node %s was not confirmed, so no binding was written",
                node_id,
            )
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic("matter_grant_not_confirmed", _about_matter(link)),
                raw_error=str(error),
            )
        except Exception as error:  # a client may raise whatever its server raised
            return self._failed(link, error)

    async def _revoke(self, link: Link) -> None:
        """Take this control's access to the target back, as far as it can be taken back.

        Never fails a link. The binding is already gone by the time this runs, which is what
        the user asked for; what is left if this does not finish is a permission that permits
        nothing, and reporting the removal as failed would make the planner offer to remove a
        link that is not there any more. It is logged, and the next removal of the same link
        tries again.

        NOTE: modelled, never observed. Assumption A9.
        """
        node_id = self._node_id(link.target.handle)
        try:
            before = mp.parse_acl(await self._read(node_id, mp.ACL_PATH))
            outcome = mp.revoke_for(
                before, subject=self._node_id(link.source), target=self._acl_target(link)
            )
            if outcome.changed and outcome.entries is not None:
                await self._client.write_attribute(
                    node_id, mp.ACL_PATH, mp.acl_payload(outcome.entries)
                )
        except Exception as error:  # a client may raise whatever its server raised
            _LOGGER.warning(
                "the binding was removed but the access grant on Matter node %s was left "
                "behind, because it could not be narrowed: %s",
                node_id,
                error,
            )

    async def _acl_capacity(self, node_id: int) -> mp.AclCapacity:
        """Read what this node says it can hold in its Access Control list.

        Read on the write path only. It costs three round trips and decides nothing until
        something is about to be written, and a device's answer is not the kind of thing
        that changes.
        """
        entries, subjects, targets = await asyncio.gather(
            self._read(node_id, mp.ACL_ENTRIES_PER_FABRIC_PATH),
            self._read(node_id, mp.ACL_SUBJECTS_PER_ENTRY_PATH),
            self._read(node_id, mp.ACL_TARGETS_PER_ENTRY_PATH),
        )
        return mp.AclCapacity(
            entries_per_fabric=_count(entries),
            subjects_per_entry=_count(subjects),
            targets_per_entry=_count(targets),
        )

    def _acl_refusal(self, link: Link, outcome: mp.AclOutcome) -> Diagnostic:
        """Turn a refusal from the Access Control merge into something a user can act on.

        E27 asks for "n of m entries used" rather than "capacity exceeded", and each of these
        says what to do about it. They are told apart because the answers are different: a
        full list is fixed by removing a controller the device no longer needs, and a full
        entry is fixed by pointing fewer controls at that one device.
        """
        counts = {
            **_about_matter(link),
            "used": str(outcome.used),
            "capacity": str(outcome.capacity),
        }
        if outcome.refusal is mp.AclRefusal.SUBJECTS_FULL:
            return Diagnostic("matter_acl_subjects_full", counts)
        if outcome.refusal is mp.AclRefusal.NO_TARGETED_ENTRIES:
            return Diagnostic("matter_acl_not_targetable", _about_matter(link))
        if outcome.refusal is mp.AclRefusal.FABRIC_UNKNOWN:
            return Diagnostic("matter_acl_unreadable", _about_matter(link))
        if outcome.refusal is mp.AclRefusal.UNREADABLE_ENTRY:
            return Diagnostic("matter_acl_entry_unreadable", _about_matter(link))
        return Diagnostic("matter_acl_full", counts)

    def _absolute_refusal(self, link: Link) -> Diagnostic | None:
        """Return why this link may never be written, whatever the fabric currently says."""
        if not self._writes_enabled:
            return Diagnostic("matter_writes_disabled", _about_matter(link))
        if link.source.identity == link.target.handle.identity:
            return Diagnostic("matter_self_binding", _about_matter(link))
        if mp.group_id_of(link.target.handle) is not None:
            return Diagnostic("matter_group_target", _about_matter(link))
        if link.target.endpoint is None:
            return Diagnostic("matter_target_endpoint_required", _about_matter(link))
        if _cluster_of(link) is None:
            return Diagnostic("matter_unknown_cluster", _about_matter(link))
        return None

    async def _capability_refusal(self, link: Link) -> Diagnostic | None:
        """Return why this binding would not do anything, asked before it is spent.

        A binding whose source endpoint does not drive the cluster sends nothing, and one
        whose target endpoint does not serve it is accepted and dead forever. Neither shows
        up afterwards as anything but a binding that is present and useless, which is the
        worst outcome available: it looks applied. The Binding cluster is checked as well,
        because an endpoint without one has nowhere to hold the entry at all.
        """
        cluster = _cluster_of(link)
        if cluster is None:  # pragma: no cover - `_absolute_refusal` has already answered
            return Diagnostic("matter_unknown_cluster", _about_matter(link))
        try:
            source = await self._view(self._node_id(link.source))
            target = await self._view(self._node_id(link.target.handle))
        except MatterBackendError:
            return Diagnostic("matter_unknown_device", _about_matter(link))
        # The Binding cluster is asked about first, and the order is not arbitrary: an
        # endpoint that serves no Binding cluster never has its client list read at all
        # (see `_read_view`), so asking whether it drives the cluster would answer "no" for
        # a control that does drive it, and say the wrong thing about why it cannot be
        # used. "There is nowhere on it to keep a link" is what is actually known.
        if not mp.has_binding_cluster(source, link.source_endpoint):
            return Diagnostic("matter_no_binding_cluster", _about_matter(link))
        if not mp.emits(source, link.source_endpoint, cluster):
            return Diagnostic("matter_source_cannot_send", _about_matter(link))
        if link.target.endpoint is None or not mp.accepts(target, link.target.endpoint, cluster):
            return Diagnostic("matter_target_cannot_receive", _about_matter(link))
        return None

    async def _refusal(self, link: Link, *, adding: bool) -> Diagnostic | None:
        """Return every refusal that does not depend on what is already on the device."""
        refusal = self._absolute_refusal(link)
        if refusal is not None or not adding:
            return refusal
        return await self._capability_refusal(link)

    def _is_present(self, link: Link, source: mp.Node) -> bool:
        """Say whether this exact link is already on the node.

        Compared by fingerprint against the observed links, so it asks the same question the
        planner asked and gets the same answer: a bound LevelControl counts for both the
        features it carries.
        """
        return any(
            observed.fingerprint == link.fingerprint
            for observed in self._observed_links(link.source, source)
        )

    def _wanted(self, link: Link) -> mp.BindingEntry:
        """Return the Binding entry that expresses this link."""
        return mp.BindingEntry(
            node=self._node_id(link.target.handle),
            endpoint=link.target.endpoint,
            cluster=_cluster_of(link),
        )

    def _acl_target(self, link: Link) -> mp.AclTarget:
        """Return the narrowest access this link needs: one cluster on one endpoint."""
        return mp.AclTarget(cluster=_cluster_of(link), endpoint=link.target.endpoint)

    def _pending(self, link: Link) -> LinkResult:
        """Report a node that is on the fabric and not answering (E29).

        Not a failure and not a success: the write has not happened and nothing has gone
        wrong. `pending_wakeup` is what the rest of the system already means by that, and it
        is what the Repairs issue for a device that has to be woken is built on.
        """
        return LinkResult(
            status=LinkResultStatus.PENDING_WAKEUP,
            reason=Diagnostic("matter_node_offline", _about_matter(link)),
        )

    def _failed(self, link: Link, error: Exception) -> LinkResult:
        """Report a write the fabric would not carry out, keeping its own words for the log."""
        return LinkResult(
            status=LinkResultStatus.FAILED,
            reason=Diagnostic("matter_write_failed", _about_matter(link)),
            raw_error=f"{type(error).__name__}: {error}",
        )

    # Settings.

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        """Refuse to read a named setting, because Matter has none of the kind meant here.

        A Matter device is configured through the attributes of its own clusters, not through
        a numbered parameter list, and the profile database's Matter shape carries no
        adapters at all. Raising is the same contract the other two adapters have for a
        setting nobody has described: a read has no shape to report a refusal in, and
        inventing a value would be worse.
        """
        raise MatterBackendError(
            f"Matter node {handle.protocol_id} has no {capability} setting: a Matter device "
            "is configured through its own cluster attributes rather than through numbered "
            "parameters, and Device Links writes none of them"
        )

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        """Refuse to write a named setting, and say why rather than pretending. See above."""
        del value
        return SettingResult(
            ok=False,
            reason=Diagnostic(
                "settings_not_available",
                {"device": handle.name_at_authoring, "setting": capability},
            ),
        )

    async def async_read_indication(self, handle: DeviceHandle, emitter_id: str) -> bool | None:
        """Report that nothing here has a per-button light this integration can address.

        What actually refuses hybrid leg kind (c) on this protocol is the compiler, which
        needs an `indicator_id` on the emitter and no Matter profile entry has one; this is
        the second half of the same fact, so that a leg reaching here anyway records a
        failure rather than reporting a write that did not happen.
        """
        del handle, emitter_id
        return None

    async def async_write_indication(
        self, handle: DeviceHandle, emitter_id: str, lit: bool
    ) -> bool:
        """Report that there was nothing to write. See `async_read_indication`."""
        del handle, emitter_id, lit
        return False

    # Change subscriptions.

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Call `callback` with a device identity whenever that node's state changes.

        Subscribed without an event filter, deliberately: naming one would mean importing
        the client library's `EventType`, and this integration cannot import it at all on a
        house with no Matter fabric. So every event arrives here and is sorted out below.

        **A notification is cheap and an invalidation is not.** Every attribute of every node
        arrives on this subscription, so a light being switched on is an event. Answering it
        by re-reading the node would put a burst of radio traffic behind every button press
        in the house, so what happens instead is that the coordinator is told the device is
        worth re-reading, and its re-read is served from what this adapter already holds. The
        cache is dropped only when the event names an attribute this adapter actually reads:
        a Binding list or an Access Control list.

        There is no debounce, unlike the Z-Wave adapter, because there is nothing expensive
        behind the callback to protect: the coordinator has its own.

        Each subscription owns its callback and its client registration, rather than sharing
        a list of listeners: a second subscriber would otherwise be told about every event
        twice, once through each registration.
        """
        subscription = _Subscription()

        def _on_event(event: object, data: object) -> None:
            del event
            if not subscription.live:
                return
            node_id = _node_id_of_event(data)
            if node_id is None:
                return
            path = _path_of_event(data)
            if path is not None and _is_ours(path):
                self._views.pop(node_id, None)
            callback(f"{BackendId.MATTER}:{node_id}")

        remove = self._client.subscribe_events(callback=_on_event)

        def _unsubscribe() -> None:
            subscription.live = False
            remove()

        return _unsubscribe

    # Nodes and their identity.

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        """Return how a user wakes this node, or None when it is always listening."""
        try:
            view = self._views.get(self._node_id(handle))
        except MatterBackendError:
            return None
        if view is None:
            return None
        entry = self._entry_of(view)
        return None if entry is None else entry.wake_instruction

    def system_scope(self) -> SystemScope:
        """Report that a Matter system entry reserves itself and not the slot it is in.

        Both of Matter's tables are lists of independent entries: an endpoint's Binding list
        holds one target per entry, and a node's Access Control list holds one grant per
        entry. Protecting one of them protects that one and nothing beside it, which is what
        `ENTRY` means. Answering `SLOT` would mean that one protected entry on an endpoint
        refused every other binding on the same endpoint and cluster, which is exactly the
        bug open item T49 was on Zigbee.

        The `SystemScope` docstring says a backend that is unsure answers `SLOT`, and this
        one is not unsure: it is a fact about the shape of the two attributes rather than a
        judgement about a device. What it does not depend on is anything being marked as a
        system link today, because nothing is: Matter's system entry is the controller's
        Administer grant, which is not a binding, is never an observed link, and is protected
        by `matter_protocol._checked` rather than by this flag.
        """
        return SystemScope.ENTRY

    def registry_identifier(self, handle: DeviceHandle) -> tuple[str, str] | None:
        """Return the `matter` device registry identifier for this node.

        Stage 0 item P2 captured the format: `deviceid_<compressed fabric id>-<node id>-
        MatterNodeDevice`, both numbers as 16 hexadecimal digits in upper case. **The
        compressed fabric id is part of it**, which is why this is the adapter's answer and
        not a constant anywhere above: it changes when a fabric is re-commissioned, so it is
        read live and a handle keyed on it would have gone stale (which is why a handle keys
        on the node id alone).

        None when the fabric has not said what it is yet, and none for a handle naming a
        group: a group is an address a binding can point at rather than a device somebody
        added, and the `matter` integration registers nothing for one.
        """
        info = self._client.server_info
        node_id = mp.node_id_of(handle)
        if info is None or node_id is None:
            return None
        instance = f"{info.compressed_fabric_id:016X}-{node_id:016X}"
        return (UPSTREAM_DOMAIN, f"{DEVICE_ID_PREFIX}_{instance}-{DEVICE_ID_SUFFIX}")

    def server_version(self) -> str | None:
        """Return the Matter server version the client last reported.

        Read live rather than snapshotted at setup, for the reason the Zigbee bridge version
        is: the Matter server is an add-on, so upgrading it reconnects the client and reloads
        nothing of ours, and a version snapshotted months ago is the version that gets quoted
        in an issue report.
        """
        info = self._client.server_info
        return None if info is None else info.sdk_version

    def _node(self, node_id: int) -> MatterNodeView:
        """Return the node the fabric holds under this id, or say which one is missing."""
        for node in self._client.get_nodes():
            if node.node_id == node_id:
                return node
        raise MatterBackendError(f"{node_id} is not a node this Matter fabric reports")

    def _node_id(self, handle: DeviceHandle) -> int:
        """Return the node a handle names, or refuse a handle that names no node."""
        node_id = mp.node_id_of(handle)
        if node_id is None:
            raise MatterBackendError(f"{handle.protocol_id} is not a Matter node address")
        return node_id

    def _handle(self, node: MatterNodeView) -> DeviceHandle:
        """Return the handle a rule refers to this node by."""
        return mp.handle_of(
            mp.Node(
                node_id=node.node_id,
                name=node.name or "",
                vendor=_vendor(node),
                product=_product(node),
            )
        )

    def _handle_of_node_id(self, node_id: int) -> DeviceHandle:
        """Return a handle for a node a binding points at, listed or not.

        A binding can name a node the fabric no longer lists, which is what is left behind
        when a device is decommissioned while a binding to it is still on somebody's switch.
        Such a target still needs a handle, because the link it is part of is real.
        """
        try:
            return self._handle(self._node(node_id))
        except MatterBackendError:
            return mp.handle_of(mp.Node(node_id=node_id, name="", vendor="", product=""))

    def _entry_of(self, view: mp.Node) -> MatterProfileEntry | None:
        """Return the curated entry for this model, or None when none claims it."""
        if self._profiles is None:
            return None
        return self._profiles.lookup_matter(mp.fingerprint_of(view))


def _about_matter(link: Link) -> dict[str, str]:
    """Return the placeholders every message about a Matter binding needs to be actionable.

    `cluster` rather than `group`, because that is what a Matter link is written to and a
    message calling it a group would be describing Z-Wave. `tests/test_translations.py` knows
    this helper by name, so a message using one of these three is checked against what is
    really supplied wherever it is raised.
    """
    return {
        "device": link.source.name_at_authoring,
        "cluster": _cluster_name(link),
        "target": link.target.handle.name_at_authoring,
    }


# What each control cluster is called in a sentence. The number is what reaches the fabric
# and is meaningless to a user, so a message says "on/off" and the job log carries the id.
_CLUSTER_NAMES: Final[Mapping[int, str]] = {
    mp.ON_OFF_CLUSTER: "on/off",
    mp.LEVEL_CONTROL_CLUSTER: "brightness",
    mp.SCENES_MANAGEMENT_CLUSTER: "scenes",
    mp.COLOR_CONTROL_CLUSTER: "colour",
}


def _cluster_name(link: Link) -> str:
    """Return what to call this link's cluster in a message shown to a person."""
    cluster = _cluster_of(link)
    if cluster is None:
        return link.emitter_group
    return _CLUSTER_NAMES.get(cluster, f"cluster {cluster}")


def _cluster_of(link: Link) -> int | None:
    """Return the cluster this link is written to, or None when it does not name one.

    `Link.emitter_group` is text for every protocol, because Z-Wave group numbers and Zigbee
    cluster names both live in it. A Matter link carries the cluster id as digits, and
    anything else is a link this adapter cannot write rather than an error to raise: a rule
    imported from a profile written for another backend can reach here.
    """
    group = link.emitter_group
    if not group.isascii() or not group.isdecimal():
        return None
    return int(group)


def _ints(raw: object) -> tuple[int, ...]:
    """Return a read that should have been a list of numbers, as a list of numbers."""
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(item for item in raw if isinstance(item, int) and not isinstance(item, bool))


def _count(raw: object) -> int:
    """Return a capacity a node reported, or nothing when it reported something else.

    Zero rather than a guessed default, because zero refuses. A device whose capacity could
    not be read is a device this integration must not write an Access Control entry to.
    """
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0


def _vendor(node: MatterNodeView) -> str:
    """Return the vendor name a node reports, or nothing when it reports none."""
    info = node.device_info
    return "" if info is None or info.vendorName is None else info.vendorName


def _product(node: MatterNodeView) -> str:
    """Return the product name a node reports, or nothing when it reports none."""
    info = node.device_info
    return "" if info is None or info.productName is None else info.productName


def _is_ours(path: str) -> bool:
    """Say whether a changed attribute is one this adapter's cache depends on.

    The Binding list of any endpoint, the Access Control list of the root, and any endpoint's
    Descriptor. Everything else on a Matter node changes constantly (a light's level, a
    sensor's temperature) and none of it touches what Device Links reads, so it is a reason
    to look again and not a reason to read again.
    """
    parts = path.split("/")
    if len(parts) != 3:  # noqa: PLR2004 - an attribute path is endpoint, cluster, attribute
        return False
    return parts[1] in {
        str(mp.BINDING_CLUSTER),
        str(mp.ACCESS_CONTROL_CLUSTER),
        # The Descriptor as well, which is not obvious: what this adapter reads off a node
        # is decided by its server cluster lists, so an endpoint that gains a Binding
        # cluster in a firmware update would otherwise go on reading as "not a binding
        # source" until something asked for a deep read.
        str(mp.DESCRIPTOR_CLUSTER),
    }


def _node_id_of_event(data: object) -> int | None:
    """Return the node an event is about, however the client reports it.

    Defensive on purpose. The events this subscription receives were never observed: Stage 0
    M1 read attributes and subscribed to nothing, so the shape of an event payload is taken
    from the client library rather than from a capture (assumption A9). An event whose node
    cannot be identified is dropped, which costs a refresh that would have happened anyway on
    the next one, rather than raising inside somebody else's dispatch loop.
    """
    if isinstance(data, bool):
        return None
    if isinstance(data, int):
        return data
    node_id = getattr(data, "node_id", None)
    if isinstance(node_id, int) and not isinstance(node_id, bool):
        return node_id
    if isinstance(data, Mapping):
        held = data.get("node_id")
        if isinstance(held, int) and not isinstance(held, bool):
            return held
    return None


def _path_of_event(data: object) -> str | None:
    """Return the attribute an event is about, or None when it is not about one.

    Two spellings, because the client offers a composed `path` on an attribute update and the
    parts it is composed from. Modelled rather than observed, like everything else about
    these events; being wrong costs a cache that is dropped too rarely, which the next deep
    read corrects.
    """
    path = getattr(data, "path", None)
    if isinstance(path, str):
        return path
    if isinstance(data, Mapping):
        held = data.get("path")
        return held if isinstance(held, str) else None
    parts = [getattr(data, name, None) for name in ("endpoint", "cluster_id", "attribute_id")]
    if all(isinstance(part, int) for part in parts):
        return "/".join(str(part) for part in parts)
    return None


__all__ = ["MatterBackend", "MatterBackendError", "MatterNodeUnavailableError"]
