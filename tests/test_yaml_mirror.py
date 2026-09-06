"""The YAML mirror: files a user's git can see, and the four ways it could go wrong.

Decision D8, FR-P2, and open item T14. `.storage/device_links.profiles` is authoritative
and this is a copy in one direction: nothing here is ever read back, because a rule about
somebody's lights should not be changed by a text editor and a restart.

The four properties this file exists to hold, each of them a way the feature could hurt
somebody rather than merely fail:

- **Off unless it was turned on**, because it writes files into a configuration directory.
- **Nothing written outside that directory**, because the path is a text box in a UI form.
- **Nothing deleted that is not ours**, because pruning is how a renamed profile stops
  leaving a stale file, and the same code aimed at the wrong folder is how somebody's
  automations disappear.
- **No file I/O on the event loop**, which Home Assistant's own test harness asserts for
  us: `pytest-homeassistant-custom-component` fails a test whose code path opens a file
  from the loop, so every test here that writes a file is also that assertion.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_links.const import (
    DEFAULT_YAML_MIRROR_PATH,
    DOMAIN,
    OPTION_YAML_MIRROR,
    OPTION_YAML_MIRROR_PATH,
)
from custom_components.device_links.yaml_io import HEADER_FIRST_LINE, parse_profile
from custom_components.device_links.yaml_mirror import FLUSH_DELAY_SECONDS
from tests.conftest import a_profile, a_rule, activate


@pytest.fixture(autouse=True)
def isolated_config_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Give every test its own configuration directory.

    Autouse and first, so it is in place before any fixture sets the integration up. The
    test harness's own `testing_config` is a real directory inside the installed package,
    and a mirror writing into it would leave files behind for the next test and for the
    next run.
    """
    hass.config.config_dir = str(tmp_path)
    return tmp_path


async def settle(hass: HomeAssistant) -> None:
    """Let the mirror's debounce elapse and its executor job finish."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=FLUSH_DELAY_SECONDS + 1))
    await hass.async_block_till_done()


def mirror_dir(hass: HomeAssistant, path: str = DEFAULT_YAML_MIRROR_PATH) -> Path:
    """Return the directory the mirror writes into."""
    return Path(hass.config.config_dir) / path


def files(directory: Path) -> list[str]:
    """Return the names of the YAML files in a directory, sorted."""
    return sorted(path.name for path in directory.glob("*.yaml")) if directory.exists() else []


@pytest.fixture
async def mirrored(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_entry: MockConfigEntry,
    zwave_js_devices: dict[int, Any],
    request: pytest.FixtureRequest,
) -> Any:
    """Device Links with the mirror on, at the default path unless a test says otherwise."""
    options = getattr(request, "param", {OPTION_YAML_MIRROR: True})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links", options=options)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --------------------------------------------------------------------------------------
# Off unless it was turned on
# --------------------------------------------------------------------------------------


async def test_nothing_is_written_when_the_option_is_off(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Decision D8. An integration that writes files unasked is one that surprises people."""
    activate(device_links_entry, a_profile(a_rule()))
    await settle(hass)

    assert not mirror_dir(hass).exists()


# --------------------------------------------------------------------------------------
# What it writes
# --------------------------------------------------------------------------------------


async def test_a_profile_is_written_as_the_yaml_the_export_gives_you(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """One codec, so what is on disk is what `profiles/export` answers with, exactly."""
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)

    written = mirror_dir(hass) / "bedroom-bedroom.yaml"

    assert files(mirror_dir(hass)) == ["bedroom-bedroom.yaml"]
    text = written.read_text()
    assert text.startswith(HEADER_FIRST_LINE)
    # Readable back through the same reader an import uses, which is the whole point of
    # writing the export rather than a shape of this module's own.
    assert parse_profile(text).rules[0].id == "bedroom-main"


async def test_a_change_to_a_rule_rewrites_the_file(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """The reason it exists: a user's git sees the change (FR-P2)."""
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)
    before = (mirror_dir(hass) / "bedroom-bedroom.yaml").read_text()

    activate(mirrored, a_profile(a_rule(name="Renamed rule")))
    await settle(hass)

    after = (mirror_dir(hass) / "bedroom-bedroom.yaml").read_text()
    assert "Renamed rule" in after
    assert after != before


async def test_two_profiles_with_one_name_get_a_file_each(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """A name is a thing people reuse, and a file two profiles claim holds one of them."""
    activate(
        mirrored,
        a_profile(a_rule(), profile_id="one", name="Home"),
        a_profile(a_rule(), profile_id="two", name="Home"),
    )
    await settle(hass)

    assert files(mirror_dir(hass)) == ["home-one.yaml", "home-two.yaml"]


async def test_a_profile_with_no_name_still_gets_a_file(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """The id is always there, so a profile nobody named is not a profile with no file."""
    activate(mirrored, a_profile(a_rule(), profile_id="abc123", name=""))
    await settle(hass)

    assert files(mirror_dir(hass)) == ["abc123.yaml"]


async def test_a_file_whose_text_has_not_changed_is_not_touched(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """A mirror that rewrote everything on every flush would put noise in a git status."""
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)
    written = mirror_dir(hass) / "bedroom-bedroom.yaml"
    stamped = written.stat().st_mtime_ns

    # A device read, which fires the same listener the mirror follows and changes nothing.
    await mirrored.runtime_data.coordinator.async_refresh()
    await settle(hass)

    assert written.stat().st_mtime_ns == stamped


# --------------------------------------------------------------------------------------
# What it deletes, and what it must not
# --------------------------------------------------------------------------------------


async def test_a_deleted_profile_takes_its_file_with_it(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """A stale file is a profile somebody thinks they still have."""
    activate(
        mirrored,
        a_profile(a_rule(), profile_id="one", name="Home"),
        a_profile(a_rule(), profile_id="two", name="Away"),
    )
    await settle(hass)
    assert files(mirror_dir(hass)) == ["away-two.yaml", "home-one.yaml"]

    activate(mirrored, a_profile(a_rule(), profile_id="one", name="Home"))
    await settle(hass)

    assert files(mirror_dir(hass)) == ["home-one.yaml"]


async def test_renaming_a_profile_leaves_no_file_behind(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """The file name carries the name, so a rename is a new file and an old one to prune."""
    activate(mirrored, a_profile(a_rule(), profile_id="one", name="Home"))
    await settle(hass)

    activate(mirrored, a_profile(a_rule(), profile_id="one", name="Downstairs"))
    await settle(hass)

    assert files(mirror_dir(hass)) == ["downstairs-one.yaml"]


async def test_a_yaml_file_this_integration_did_not_write_is_never_deleted(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """The one that matters. A mirror pointed at the wrong folder must not tidy it away.

    Asked of the file rather than of a record of what was written, because a record does
    not survive a restart: a mirror that only pruned within one session would leave a
    renamed profile's file behind for ever, and one that pruned everything would take
    somebody's automations with it.
    """
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)
    stranger = mirror_dir(hass) / "somebody-elses.yaml"
    stranger.write_text("# not ours\nalias: Turn the porch light on\n")

    activate(mirrored, a_profile(a_rule(), profile_id="other", name="Other"))
    await settle(hass)

    assert stranger.exists(), "the mirror deleted a file it did not write"
    assert files(mirror_dir(hass)) == ["other-other.yaml", "somebody-elses.yaml"]


# --------------------------------------------------------------------------------------
# Where it will not write
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/etc/device_links", "../outside", "device_links/../../outside", "."],
    ids=["absolute", "parent", "climbing", "the config directory itself"],
)
async def test_a_path_outside_the_configuration_directory_is_refused(  # noqa: PLR0913, PLR0917
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_entry: MockConfigEntry,
    zwave_js_devices: dict[int, Any],
    caplog: pytest.LogCaptureFixture,
    path: str,
) -> None:
    """A text box in a form must not be able to aim a writer and a pruner anywhere.

    The mirror stops and the integration does not: refusing to load over a setting somebody
    typed would take a house's associations away over a typo, and the profiles themselves
    are unaffected either way.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Device Links",
        options={OPTION_YAML_MIRROR: True, OPTION_YAML_MIRROR_PATH: path},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    activate(entry, a_profile(a_rule()))
    await settle(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert "is not inside the configuration directory" in caplog.text
    assert not (Path(hass.config.config_dir) / "outside").exists()


@pytest.mark.parametrize(
    "mirrored",
    [{OPTION_YAML_MIRROR: True, OPTION_YAML_MIRROR_PATH: "somewhere/else"}],
    indirect=True,
)
async def test_the_path_is_configurable(hass: HomeAssistant, mirrored: MockConfigEntry) -> None:
    """PRD Section 6.3 names a default; a user with their own layout picks their own."""
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)

    assert files(mirror_dir(hass, "somewhere/else")) == ["bedroom-bedroom.yaml"]
    assert not mirror_dir(hass).exists()


async def test_a_directory_that_cannot_be_written_is_said_once_and_then_left_alone(
    hass: HomeAssistant,
    mirrored: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fault the user has to fix is not improved by a warning every two seconds."""
    from custom_components.device_links import yaml_mirror  # noqa: PLC0415

    def _refuse(directory: Path, wanted: dict[str, str]) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(yaml_mirror, "_write_all", _refuse)
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)
    caplog.clear()

    activate(mirrored, a_profile(a_rule(name="Again")))
    await settle(hass)

    assert "could not be written" not in caplog.text, "the mirror complained twice"


# --------------------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------------------


async def test_unloading_drops_a_flush_that_had_not_happened_yet(
    hass: HomeAssistant, mirrored: MockConfigEntry
) -> None:
    """A timer that outlives its config entry writes from a component that has gone."""
    activate(mirrored, a_profile(a_rule()))
    await settle(hass)
    activate(mirrored, a_profile(a_rule(), profile_id="pending", name="Pending"))

    await hass.config_entries.async_unload(mirrored.entry_id)
    await settle(hass)

    assert files(mirror_dir(hass)) == ["bedroom-bedroom.yaml"]


async def test_the_first_flush_happens_at_setup_rather_than_at_the_first_edit(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_entry: MockConfigEntry,
    zwave_js_devices: dict[int, Any],
) -> None:
    """Turning the mirror on has to produce the files, not wait for somebody to edit one."""
    hass_storage["device_links.profiles"] = {
        "version": 1,
        "data": {
            "profiles": [_stored(a_profile(a_rule()))],
            "active_profile_id": "bedroom",
            "ignored_unmanaged": [],
            "applied_rule_ids": [],
            "snapshots": [],
            "jobs": [],
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, title="Device Links", options={OPTION_YAML_MIRROR: True}
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass)

    assert files(mirror_dir(hass)) == ["bedroom-bedroom.yaml"]


def _stored(profile: Any) -> dict[str, Any]:
    """Return one profile as the storage file holds it."""
    from custom_components.device_links.yaml_io import profile_to_data  # noqa: PLC0415

    return dict(profile_to_data(profile, keep_local_ids=True))


def test_the_settings_read_what_the_options_say() -> None:
    """The two fields, and the default an emptied path falls back to."""
    from custom_components.device_links.yaml_mirror import MirrorSettings  # noqa: PLC0415

    assert MirrorSettings.from_options({}) == MirrorSettings(
        enabled=False, path=DEFAULT_YAML_MIRROR_PATH
    )
    assert MirrorSettings.from_options(
        {OPTION_YAML_MIRROR: True, OPTION_YAML_MIRROR_PATH: "  "}
    ) == MirrorSettings(enabled=True, path=DEFAULT_YAML_MIRROR_PATH)
    assert replace(MirrorSettings(enabled=True, path="a/b"), enabled=False).path == "a/b"
