"""Storage: the one place the user's work lives, and the versioning that protects it.

`.storage/device_links.profiles` is authoritative (CLAUDE.md Section 4); the YAML export is
a mirror. Everything a user built by hand is in this file, and there is no undo, so this
module is written around two rules.

**A version this code does not understand is refused, never guessed at.** A store written
by a newer Device Links is read-only to us: Home Assistant's own `Store` raises before any
of our code sees it, and that is translated here into one domain error naming both versions
so the Home Assistant layer can come up read-only with a Repairs issue rather than crash
(E18). An older version is migrated by a chain of steps, and a version with no step is an
error too: losing the file is not an acceptable way to handle a gap in the chain.

**The migration mechanism exists before the first migration does.** `_MIGRATIONS` is empty,
because `STORAGE_VERSION` is 1 and nothing has ever been written at any other version. The
runner that walks it is real, tested code (`tests/test_storage.py` registers a synthetic
step into it), so the first real migration is one entry in a dict rather than a mechanism
invented at the moment when getting it wrong destroys somebody's configuration.

What is stored is `StoredState`, and the caps live on it rather than in the writer: a
snapshot list that grows forever is a file that grows forever, and a cap applied at one of
two call sites is a cap that is missing at the other.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import logging
from typing import Any, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, UnsupportedStorageVersionError
from homeassistant.helpers.storage import Store

from custom_components.device_links.const import DOMAIN, STORAGE_KEY, STORAGE_VERSION
from custom_components.device_links.models import ObservedLink, Profile
from custom_components.device_links.yaml_io import (
    ProfileFormatError,
    observed_link_from_data,
    observed_link_to_data,
    profile_from_data,
    profile_to_data,
)

_LOGGER = logging.getLogger(__name__)

# FR-P3: the last 20 snapshots, and PRD Section 8.2: the last 50 job summaries. Both are
# working history rather than an archive, and both are written by machines rather than by
# people, so both need a ceiling that is enforced where the list is appended to.
MAX_SNAPSHOTS: Final = 20
MAX_JOBS: Final = 50

# Editing a profile in the panel produces a burst of small changes, and each one is a
# whole-file write. Ten seconds is Home Assistant's own registry delay: long enough that a
# burst is one write, short enough that a crash loses nothing a user would notice.
SAVE_DELAY_SECONDS: Final = 10


class StorageSchemaError(HomeAssistantError):
    """The stored data cannot be read, and exactly why it cannot.

    Carries a translation key as well as a message: the message is for the log and for a
    developer, and the key is what the Home Assistant layer shows the user alongside the
    Repairs issue E18 asks for.
    """


# One migration step: given the version it is migrating from and that version's payload,
# return the payload at the next version. Steps are pure and synchronous, so a migration
# can be reasoned about and tested without Home Assistant running.
type MigrationStep = Callable[[int, dict[str, Any]], dict[str, Any]]

# From-version to the step that moves it forward by one. Empty on purpose: version 1 is the
# first version there has ever been. The first real migration adds `1: _one_to_two` here.
_MIGRATIONS: Final[dict[int, MigrationStep]] = {}


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What a set of devices held before an apply, kept so it can be put back (FR-P3).

    `links` are whole observed links rather than fingerprints, because a rollback is
    re-applied as a plan and a plan needs to know what each entry was: a snapshot that kept
    only fingerprints would come back as links nobody could tell apart from foreign ones.
    `created_at` is supplied by the caller rather than read from a clock here, so nothing in
    this module depends on the time it runs at.
    """

    id: str
    created_at: str
    reason: str
    links: tuple[ObservedLink, ...] = ()


@dataclass(frozen=True, slots=True)
class JobLinkResult:
    """What became of one link in one job (FR-A2).

    `status` and `reason` are plain strings here rather than the executor's own types: this
    is a record of something that already happened, and a history that could not be read
    back because an enum member was renamed would be worse than useless.
    """

    fingerprint: str
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class JobSummary:
    """One apply, as the Activity view and a support request need to see it afterwards."""

    id: str
    created_at: str
    scope: str
    status: str
    results: tuple[JobLinkResult, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredState:
    """Everything Device Links keeps across a restart.

    Frozen, so the coordinator cannot mutate half of it and save the other half, and so the
    caps in `with_snapshot` and `with_job` cannot be routed around by appending to a list.
    """

    profiles: tuple[Profile, ...] = ()
    active_profile_id: str | None = None
    ignored_unmanaged: frozenset[str] = frozenset()
    snapshots: tuple[Snapshot, ...] = ()
    jobs: tuple[JobSummary, ...] = field(default=())

    @property
    def active_profile(self) -> Profile | None:
        """Return the one active profile (Decision D10), or None when the id names none.

        A dangling id reads as "no active profile" rather than raising: a profile deleted
        while it was active must leave an integration that starts and says so, not one that
        fails to load.
        """
        return next(
            (profile for profile in self.profiles if profile.id == self.active_profile_id), None
        )

    def with_snapshot(self, snapshot: Snapshot) -> StoredState:
        """Return this state with one more snapshot, oldest dropped first."""
        return replace(self, snapshots=(*self.snapshots, snapshot)[-MAX_SNAPSHOTS:])

    def with_job(self, job: JobSummary) -> StoredState:
        """Return this state with one more job summary, oldest dropped first."""
        return replace(self, jobs=(*self.jobs, job)[-MAX_JOBS:])


class _ProfileStore(Store[dict[str, Any]]):
    """Home Assistant's `Store`, with this integration's migration chain attached."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Walk the stored data forward one version at a time, or refuse to.

        A gap in the chain raises rather than returning the payload unchanged. Returning it
        would hand a decoder written for this version a payload written for another one,
        which is how a migration silently drops the half of the file it did not recognise.
        """
        data = old_data
        version = old_major_version
        while version < STORAGE_VERSION:
            step = _MIGRATIONS.get(version)
            if step is None:
                raise StorageSchemaError(
                    f"{STORAGE_KEY} is at schema version {version} and this Home Assistant "
                    f"reads version {STORAGE_VERSION}, but no migration from version "
                    f"{version} exists",
                    translation_domain=DOMAIN,
                    translation_key="storage_no_migration",
                    translation_placeholders={
                        "found": str(version),
                        "supported": str(STORAGE_VERSION),
                    },
                )
            _LOGGER.info("Migrating %s from schema version %s", STORAGE_KEY, version)
            data = step(version, data)
            version += 1
        return data


class DeviceLinksStore:
    """The profiles file, as the rest of the integration works with it.

    Loading answers with a `StoredState` and never with None: an install with no file yet
    and an install with an empty file are the same thing to every caller, and making them
    the same here means no caller has to invent the difference.
    """

    def __init__(self, hass: HomeAssistant, save_delay_seconds: float = SAVE_DELAY_SECONDS) -> None:
        """Wrap the Home Assistant store for this integration's key and version."""
        self._store = _ProfileStore(hass, STORAGE_VERSION, STORAGE_KEY, atomic_writes=True)
        self._save_delay_seconds = save_delay_seconds

    async def async_load(self) -> StoredState:
        """Return what is stored, or an empty state, without writing anything.

        A fresh install must not create a file. Nothing has been decided yet, and a file
        that exists says something has.
        """
        try:
            data = await self._store.async_load()
        except UnsupportedStorageVersionError as error:
            raise StorageSchemaError(
                f"{STORAGE_KEY} was written at schema version {error.found_version} and this "
                f"Home Assistant reads version {STORAGE_VERSION}. It is left untouched: "
                f"upgrade Home Assistant or restore this file from a backup",
                translation_domain=DOMAIN,
                translation_key="storage_version_too_new",
                translation_placeholders={
                    "found": str(error.found_version),
                    "supported": str(STORAGE_VERSION),
                },
            ) from error
        if data is None:
            return StoredState()
        return _state_from_data(data)

    async def async_save(self, state: StoredState) -> None:
        """Write this state now, for a change that must not be lost to a crash."""
        await self._store.async_save(_state_to_data(state))

    @callback
    def async_schedule_save(self, state: StoredState) -> None:
        """Write this state soon, coalescing a burst of edits into one write.

        Home Assistant writes any pending delayed save on shutdown, so the delay costs
        durability only in a hard crash, and costs it for at most `SAVE_DELAY_SECONDS`.
        """
        data = _state_to_data(state)
        self._store.async_delay_save(lambda: data, self._save_delay_seconds)


def _state_to_data(state: StoredState) -> dict[str, Any]:
    """Return the stored state as the JSON the file holds.

    Sets are written sorted for the same reason the YAML export sorts them: an unordered
    collection written in iteration order makes a file that differs from itself.
    """
    return {
        "profiles": [profile_to_data(profile, keep_local_ids=True) for profile in state.profiles],
        "active_profile_id": state.active_profile_id,
        "ignored_unmanaged": sorted(state.ignored_unmanaged),
        "snapshots": [_snapshot_to_data(snapshot) for snapshot in state.snapshots],
        "jobs": [_job_to_data(job) for job in state.jobs],
    }


def _state_from_data(data: Mapping[str, Any]) -> StoredState:
    """Return the stored state this data describes, or say what could not be read.

    Everything that can go wrong reading a file that was hand-edited, truncated or written
    by a version whose migration was wrong arrives here as one error naming the part that
    could not be read, rather than as a traceback from inside a comprehension.
    """
    try:
        return StoredState(
            profiles=tuple(profile_from_data(raw) for raw in data.get("profiles", ())),
            active_profile_id=data.get("active_profile_id"),
            ignored_unmanaged=frozenset(data.get("ignored_unmanaged", ())),
            snapshots=tuple(_snapshot_from_data(raw) for raw in data.get("snapshots", ())),
            jobs=tuple(_job_from_data(raw) for raw in data.get("jobs", ())),
        )
    except (ProfileFormatError, TypeError, ValueError, KeyError, AttributeError) as error:
        raise StorageSchemaError(
            f"{STORAGE_KEY} could not be read: {error}",
            translation_domain=DOMAIN,
            translation_key="storage_unreadable",
            translation_placeholders={"error": str(error)},
        ) from error


def _snapshot_to_data(snapshot: Snapshot) -> dict[str, Any]:
    """Return one snapshot as the JSON the file holds."""
    return {
        "id": snapshot.id,
        "created_at": snapshot.created_at,
        "reason": snapshot.reason,
        "links": [observed_link_to_data(link) for link in snapshot.links],
    }


def _snapshot_from_data(data: Mapping[str, Any]) -> Snapshot:
    """Return the snapshot this data describes."""
    return Snapshot(
        id=data["id"],
        created_at=data["created_at"],
        reason=data["reason"],
        links=tuple(observed_link_from_data(raw) for raw in data["links"]),
    )


def _job_to_data(job: JobSummary) -> dict[str, Any]:
    """Return one job summary as the JSON the file holds."""
    return {
        "id": job.id,
        "created_at": job.created_at,
        "scope": job.scope,
        "status": job.status,
        "results": [
            {"fingerprint": result.fingerprint, "status": result.status, "reason": result.reason}
            for result in job.results
        ],
    }


def _job_from_data(data: Mapping[str, Any]) -> JobSummary:
    """Return the job summary this data describes."""
    return JobSummary(
        id=data["id"],
        created_at=data["created_at"],
        scope=data["scope"],
        status=data["status"],
        results=tuple(
            JobLinkResult(
                fingerprint=raw["fingerprint"], status=raw["status"], reason=raw.get("reason")
            )
            for raw in data["results"]
        ),
    )
