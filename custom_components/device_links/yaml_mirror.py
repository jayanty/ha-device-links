"""The YAML mirror: the same profiles, as files a user's git can see (Decision D8, FR-P2).

`.storage/device_links.profiles` is authoritative and this is a mirror, in that direction
only. Nothing here is ever read back: a file edited by hand is imported through
`profiles/import`, deliberately, so that a rule about somebody's lights is never changed by
a text editor and a restart. This writes, and only writes.

Four things shape it, and each is a way it could otherwise go wrong.

**Off by default.** It puts files into somebody's configuration directory, and a feature
that does that unasked is one that surprises people. Decision D8 says off; the options flow
is how it goes on.

**Nothing is written outside the configuration directory.** The path is a setting in a UI
form, and this module writes files and deletes them, so an absolute path or one climbing out
with `..` is refused rather than resolved. `_resolved` is the only place a path is built,
and it checks after resolving symlinks rather than by inspecting the string, because a
string check is a check somebody's directory layout can walk around.

**A file is only ever deleted if it is one of ours.** Pruning is how a renamed or deleted
profile stops leaving a stale file behind, and it is also how a mirror pointed at the wrong
directory could delete somebody's automations. So a `.yaml` in the mirror directory is
removed only when it starts with the export header this integration writes, which is a fact
about the file rather than about what we remember writing.

**File I/O never runs on the event loop.** Every read, write and unlink goes through the
executor, in one job per flush rather than one per file: a burst of edits in the panel is
one write of one directory, not twenty round trips through a thread pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import slugify

from .const import DEFAULT_YAML_MIRROR_PATH, OPTION_YAML_MIRROR, OPTION_YAML_MIRROR_PATH
from .yaml_io import HEADER_PREFIX, dump_profile

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from . import DeviceLinksConfigEntry
    from .coordinator import DeviceLinksCoordinator
    from .models import Profile

_LOGGER = logging.getLogger(__name__)

# Editing in the panel produces a burst of small changes, and each one would otherwise be a
# directory rewrite. Two seconds coalesces a burst into one flush and is short enough that
# a user who saved a rule and switched to a terminal sees the file already changed.
FLUSH_DELAY_SECONDS: Final = 2.0

# What a mirrored file is called. The profile's name, so a diff reads as something about a
# home; its id as well, because two profiles may share a name and a file that two profiles
# both claim is a file that holds whichever was written last.
_SUFFIX: Final = ".yaml"


class MirrorPathError(ValueError):
    """The configured mirror path is not somewhere this integration may write."""


@dataclass(frozen=True, slots=True)
class MirrorSettings:
    """What the options say about the mirror, resolved once per config entry load."""

    enabled: bool
    path: str

    @classmethod
    def from_options(cls, options: Mapping[str, object]) -> MirrorSettings:
        """Return the settings this entry's options describe."""
        configured = str(options.get(OPTION_YAML_MIRROR_PATH, DEFAULT_YAML_MIRROR_PATH)).strip()
        return cls(
            enabled=bool(options.get(OPTION_YAML_MIRROR, False)),
            path=configured or DEFAULT_YAML_MIRROR_PATH,
        )


class YamlMirror:
    """Keeps a directory of `.yaml` files matching the stored profiles, and nothing else."""

    def __init__(
        self, hass: HomeAssistant, coordinator: DeviceLinksCoordinator, settings: MirrorSettings
    ) -> None:
        """Hold what the mirror needs, and touch no disk yet."""
        self._hass = hass
        self._coordinator = coordinator
        self._settings = settings
        self._directory: Path | None = None
        self._written: dict[str, str] = {}
        self._flush_handle: CALLBACK_TYPE | None = None
        self._broken = False

    # Lifecycle.

    @callback
    def async_setup(self, entry: DeviceLinksConfigEntry) -> None:
        """Start mirroring, if the option is on, and unregister with the entry.

        A path that is not somewhere we may write stops the mirror rather than the entry:
        the rest of the integration works perfectly well without files on disk, and
        refusing to load over a setting somebody typed into a text box would take a house's
        associations away over a typo.
        """
        if not self._settings.enabled:
            return
        try:
            self._directory = self._resolved()
        except MirrorPathError:
            # No traceback: the cause is a setting somebody typed, and the message names
            # it. A stack trace here would read as a bug in the integration.
            _LOGGER.error(  # noqa: TRY400
                "the YAML mirror is on and its path %r is not inside the configuration "
                "directory, so nothing is being mirrored",
                self._settings.path,
            )
            return
        entry.async_on_unload(self._coordinator.async_add_listener(self._async_changed))
        entry.async_on_unload(self._async_cancel_flush)
        self._async_changed()

    @callback
    def _async_cancel_flush(self) -> None:
        """Drop a flush that was scheduled and will no longer happen.

        What is pending is at most the last two seconds of edits, and the authoritative
        copy of those is already in `.storage`. Writing them from a config entry that is
        being unloaded would be a write from a component that has stopped existing.
        """
        if self._flush_handle is not None:
            self._flush_handle()
            self._flush_handle = None

    # What changed, and when it is written.

    @callback
    def _async_changed(self) -> None:
        """Note that the profiles may have moved, and write them once the burst is over.

        Called on every coordinator update, which includes every device read, so the
        comparison against what was last written is what keeps this from rewriting a
        directory every two seconds on a network that is simply being watched.
        """
        directory = self._directory
        if self._broken or directory is None or self._flush_handle is not None:
            return
        if self._wanted() == self._written:
            return
        # The directory travels with the timer rather than being read again when it fires,
        # so the flush has one and cannot be reached before there is one to have.
        self._flush_handle = async_call_later(
            self._hass, FLUSH_DELAY_SECONDS, partial(self._async_flush, directory)
        )

    async def _async_flush(self, directory: Path, _now: datetime) -> None:
        """Write every profile whose text has changed, and prune what is no longer ours."""
        self._flush_handle = None
        wanted = self._wanted()
        try:
            await self._hass.async_add_executor_job(_write_all, directory, wanted)
        except OSError:
            # Once, and then stop: a directory that cannot be written is not going to
            # start working between two edits, and a warning every two seconds about a
            # mirror is noise on top of a fault the user has to fix anyway.
            self._broken = True
            _LOGGER.warning(
                "the YAML mirror at %s could not be written, so it is switched off until "
                "this config entry is reloaded; the stored profiles are unaffected",
                directory,
                exc_info=True,
            )
            return
        self._written = wanted

    def _wanted(self) -> dict[str, str]:
        """Return the file this mirror should hold for each profile, by file name."""
        return {
            name: dump_profile(profile)
            for name, profile in _file_names(self._coordinator.state.profiles).items()
        }

    def _resolved(self) -> Path:
        """Return the directory to mirror into, or refuse to name one.

        Resolved before it is checked, so a symlink out of the configuration directory is
        caught as well as a `..`. Home Assistant's own configuration directory is resolved
        the same way for the comparison, because on macOS `/config` and its real path
        differ and a string comparison would refuse every legitimate path.
        """
        configured = Path(self._settings.path)
        if configured.is_absolute():
            raise MirrorPathError("the mirror path must be relative to the configuration directory")
        root = Path(self._hass.config.config_dir).resolve()
        directory = (root / configured).resolve()
        if directory != root and root not in directory.parents:
            raise MirrorPathError(f"{directory} is not inside {root}")
        if directory == root:
            raise MirrorPathError(
                "the mirror path must name a directory of its own rather than the "
                "configuration directory itself"
            )
        return directory


def _file_names(profiles: Iterable[Profile]) -> dict[str, Profile]:
    """Return the file each profile is written to, keyed by file name.

    The name and the id, in that order: the name is what makes a diff readable and the id
    is what makes the file name unique, because two profiles may be called the same thing
    and a name is a thing people change. A name that slugifies to nothing (one written
    entirely in a script `slugify` drops) leaves the id, which is always there.
    """
    named: dict[str, Profile] = {}
    for profile in profiles:
        slug = slugify(profile.name)
        stem = f"{slug}-{profile.id}" if slug else profile.id
        named[f"{stem}{_SUFFIX}"] = profile
    return named


def _write_all(directory: Path, wanted: Mapping[str, str]) -> None:
    """Write the profiles and prune ours that are no longer wanted. Blocking, so executor.

    Written before anything is pruned, so an interruption halfway leaves a directory with
    one file too many rather than one too few. A file whose text is already right is not
    rewritten at all, because a mirror that touched every file on every flush would put a
    timestamp change into a git status for a profile nobody edited.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(wanted.items()):
        path = directory / name
        if _reads_as(path) != text:
            path.write_text(text, encoding="utf-8")
    for path in sorted(directory.glob(f"*{_SUFFIX}")):
        if path.name not in wanted and _is_ours(path):
            path.unlink()


def _reads_as(path: Path) -> str | None:
    """Return what a file already holds, or None when it cannot be read as text."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_ours(path: Path) -> bool:
    """Say whether this file is one this integration wrote, and may therefore delete.

    Asked of the file rather than of a record of what was written, because a record does
    not survive a restart and a mirror that only pruned within one session would leave a
    renamed profile's file behind for ever. The header is the first line `dump_profile`
    writes and nothing else in a configuration directory begins with it.

    Only the header is read. The mirror directory is meant to hold this integration's own
    files and may hold anything, and reading a whole file into memory to look at its first
    line is a foot-gun waiting for the day somebody keeps something large beside them.

    The prefix carries no schema version, so a file written at an older one is still ours:
    the day the schema changes, every mirror file already on disk must stay prunable.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.read(len(HEADER_PREFIX)) == HEADER_PREFIX
    except (OSError, UnicodeDecodeError):
        return False
