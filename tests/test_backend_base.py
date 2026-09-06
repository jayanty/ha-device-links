"""The Backend protocol is the seam that keeps core code backend-neutral."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

from custom_components.device_links.backends.base import (
    Backend,
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
)

BASE_MODULE = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "device_links"
    / "backends"
    / "base.py"
)

# Names that would mean a protocol leaked into the seam every backend implements.
PROTOCOL_SPECIFIC = ("zwave", "zigbee", "matter", "mqtt")


def test_the_protocol_is_runtime_checkable_and_names_the_expected_surface() -> None:
    """A backend that is missing a method must be detectable, not merely wrong later."""
    expected = {
        "async_devices",
        "async_capabilities",
        "async_observed",
        "async_check_link",
        "async_add_link",
        "async_remove_link",
        "async_read_setting",
        "async_write_setting",
        "subscribe",
        "wake_instructions",
    }
    actual = {name for name in dir(Backend) if not name.startswith("_")}

    assert expected <= actual, f"Backend protocol lost: {expected - actual}"


def test_link_result_statuses_cover_every_outcome_the_executor_must_handle() -> None:
    """FR-A2 lists these by name. A missing one becomes an unhandled case in a job."""
    assert {status.value for status in LinkResultStatus} == {
        "applied",
        "already_present",
        "pending_wakeup",
        "failed",
        "blocked",
    }


def test_a_result_carrying_failed_must_carry_a_reason() -> None:
    """A failure with no reason is untriageable from a job log."""
    with pytest.raises(ValueError, match="reason"):
        LinkResult(status=LinkResultStatus.FAILED, reason=None)


def test_a_result_carrying_blocked_must_carry_a_reason() -> None:
    """A refusal the user cannot be told about is a refusal they cannot act on."""
    with pytest.raises(ValueError, match="reason"):
        LinkResult(status=LinkResultStatus.BLOCKED, reason=None)


def test_a_successful_result_needs_no_reason() -> None:
    assert LinkResult(status=LinkResultStatus.APPLIED).reason is None


def test_a_failing_check_must_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        LinkCheck(ok=False)


def test_a_passing_check_needs_no_reason() -> None:
    assert LinkCheck(ok=True).reason is None


def test_a_failing_setting_write_must_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        SettingResult(ok=False)


def test_a_successful_setting_write_needs_no_reason() -> None:
    assert SettingResult(ok=True, read_back=1).reason is None


def test_the_seam_never_imports_a_single_protocol() -> None:
    """base.py is what makes Zigbee and Matter possible without touching core code.

    A Z-Wave import here would put the coupling the whole architecture is arranged to
    avoid into the one module every backend and every core caller depends on.
    """
    tree = ast.parse(BASE_MODULE.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    offenders = [
        name for name in imported if any(marker in name.lower() for marker in PROTOCOL_SPECIFIC)
    ]

    assert not offenders, f"backends/base.py imports {offenders}; the seam must stay neutral"


def test_the_protocol_and_the_backend_id_enum_are_different_things() -> None:
    """`models.Backend` names a protocol; `base.Backend` is the adapter interface.

    They share a name, so this pins that neither can pass for the other. Modules needing
    both import the enum as `BackendId`, which is the convention `backends/zwave.py` uses.
    """
    assert Backend is not BackendId
    assert not isinstance(BackendId.ZWAVE, Backend)


def test_a_complete_backend_satisfies_the_protocol() -> None:
    """The protocol has to be implementable, not merely declarable."""
    assert isinstance(_StubBackend(), Backend)


def test_a_backend_missing_a_method_does_not_satisfy_the_protocol() -> None:
    """Rebuild the stub without one method, so the gap is real and not merely shadowed."""
    namespace = {
        name: value
        for name, value in vars(_StubBackend).items()
        if not name.startswith("__") and name != "async_add_link"
    }
    incomplete = type("Incomplete", (), namespace)

    assert not isinstance(incomplete(), Backend)


class _StubBackend:
    """A minimal complete implementation, so the protocol is proven satisfiable."""

    async def async_devices(self) -> list[BackendDevice]:
        return []

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        return DeviceCapabilities(
            handle=handle, emitters=(), receivable=frozenset(), is_long_range=False
        )

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        return ObservedDevice(handle=handle, links=())

    async def async_check_link(self, link: Link) -> LinkCheck:
        return LinkCheck(ok=True)

    async def async_add_link(self, link: Link) -> LinkResult:
        return LinkResult(status=LinkResultStatus.APPLIED)

    async def async_remove_link(self, link: Link) -> LinkResult:
        return LinkResult(status=LinkResultStatus.APPLIED)

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        return SettingValue(capability=capability, parameter=1, bitmask=None, value=0)

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        return SettingResult(ok=False, reason=Diagnostic("settings_not_available"))

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        return lambda: None

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        return None

    def system_scope(self) -> SystemScope:
        return SystemScope.SLOT
