"""`quality_scale.yaml` is a checklist, and a checklist nobody checks goes stale.

PRD Section 11 is the list of rules this project holds itself to. This file makes the
shipped `quality_scale.yaml` account for exactly that list: a rule the PRD names and the
file omits is a rule that has quietly stopped being tracked, and a rule the file names and
the PRD does not is one nobody agreed to.

It also holds the shape to something a reader can rely on. A `todo` says what is missing and
an `exempt` says why the rule cannot apply, because a status with no reason beside it is the
thing that turns into "it says exempt, so presumably somebody thought about it".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "device_links"
QUALITY_SCALE = COMPONENT / "quality_scale.yaml"

# The three statuses Home Assistant's own quality scale files use.
STATUSES = frozenset({"done", "exempt", "todo"})


def rules() -> dict[str, Any]:
    """Return the shipped file's rules, by name."""
    loaded: dict[str, Any] = yaml.safe_load(QUALITY_SCALE.read_text())["rules"]
    return loaded


def prd_rules() -> list[str]:
    """Return every rule PRD Section 11's table names, in the order it names them.

    Read out of the document rather than listed here, for the reason
    `tests/test_translations.py` reads translation keys out of the source: a list written
    twice is a list that disagrees with itself the first time somebody is in a hurry.
    """
    text = (REPO_ROOT / "docs" / "PRD.md").read_text()
    start = text.index("## 11. Engineering standards")
    section = text[start : text.index("## 12. HACS packaging")]
    named: list[str] = []
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith(("| Rule", "|---")):
            continue
        for name in line.split("|")[1].strip().split(","):
            cleaned = name.strip().strip("`")
            if cleaned:
                named.append(cleaned)
    return named


def test_the_prd_table_is_still_readable() -> None:
    """A reader that quietly found nothing would make every test below pass."""
    named = prd_rules()

    assert len(named) > 40
    assert "action-setup" in named
    assert "strict-typing" in named


def test_every_rule_the_prd_names_is_accounted_for() -> None:
    """This is the whole point of the file: a checklist that cannot silently shrink."""
    missing = sorted(set(prd_rules()) - set(rules()))

    assert not missing, f"quality_scale.yaml does not account for: {missing}"


def test_no_rule_is_tracked_that_nobody_agreed_to() -> None:
    """The other direction: a rule in the file that the PRD's checklist does not name."""
    extra = sorted(set(rules()) - set(prd_rules()))

    assert not extra, f"quality_scale.yaml tracks rules PRD Section 11 does not name: {extra}"


@pytest.mark.parametrize("rule", sorted(rules()))
def test_every_rule_has_a_status_and_a_reason(rule: str) -> None:
    """A status with no reason beside it is a status nobody can act on or trust."""
    entry = rules()[rule]

    assert isinstance(entry, dict), f"{rule} has no status"
    assert entry["status"] in STATUSES, f"{rule} has an unknown status {entry['status']!r}"
    comment = entry.get("comment", "")
    assert comment.strip(), f"{rule} is {entry['status']} and says nothing about why"
    assert "\u2014" not in comment, f"{rule} uses an em dash"


@pytest.mark.parametrize("rule", sorted(rules()))
def test_a_todo_says_what_is_missing_rather_than_that_it_is_missing(rule: str) -> None:
    """The failure this guards against is a file full of bare `todo`s nobody can plan from."""
    entry = rules()[rule]
    if entry["status"] != "todo":
        pytest.skip(f"{rule} is {entry['status']}")

    assert len(entry["comment"].split()) >= 10, f"{rule}: say what is missing"


def test_the_manifest_claims_no_tier() -> None:
    """The scale awards nothing to a custom integration, so claiming a tier would be a lie.

    PRD Section 12 says the key is omitted, and this is where that decision is enforced
    rather than remembered: adding `quality_scale` to the manifest of a custom integration
    is a natural thing to reach for the moment a `quality_scale.yaml` exists beside it.
    """
    manifest = json.loads((COMPONENT / "manifest.json").read_text())

    assert "quality_scale" not in manifest


def test_the_exemptions_are_the_ones_that_were_argued_for() -> None:
    """Six rules cannot apply here, each for a reason in the PRD or in Section 10.

    Pinned by name because an exemption is the one status that cannot be checked by reading
    the code: adding a sixth is a decision, and it should be one somebody makes deliberately
    rather than one that appears in a diff.
    """
    exempt = {rule for rule, entry in rules().items() if entry["status"] == "exempt"}

    assert exempt == {
        "docs-triggers",
        "docs-conditions",
        "discovery",
        "discovery-update-info",
        "reauthentication-flow",
        "inject-websession",
    }
