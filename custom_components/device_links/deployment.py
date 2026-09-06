"""What the dev deploy tool left behind, if anything left anything behind.

`tools/ha_deploy.py` writes `.deployed` into the deployed component directory (PRD
Section 17.5) and the Health sensor reports what is in it, so the deploy loop can end by
comparing that attribute with the SHA that was pushed. That is the whole of this module's
job, and two properties of it matter more than its size.

**Most installs have no such file.** A HACS install is a released archive and the deploy
tool never touched it, so `.deployed` is absent, and absent is not a fault: it is what a
normal install looks like. Reporting it as an error would send every remote investigation
down the wrong path on its first read, which is the one read that decides where somebody
looks next. So a missing file, an unreadable one and a half-written one all read the same
way here: there is no deployment record, and the integration is otherwise well.

**Reading a file blocks.** This is called once from the executor during setup and never
from the event loop, and it is deliberately not re-read afterwards: Python changes need a
Home Assistant restart to take effect (CLAUDE.md Section 3 rule 1), so the file cannot
describe the running code any better later than it does at startup. A value that cannot
change is read once.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Final

_LOGGER = logging.getLogger(__name__)

# Where the deploy tool writes it: alongside the code it deployed. Module level rather
# than derived at the call site so a test can point it somewhere harmless.
COMPONENT_DIR: Final = Path(__file__).parent

DEPLOYED_FILE_NAME: Final = ".deployed"


@dataclass(frozen=True, slots=True)
class Deployment:
    """The commit that is running, as the deploy tool recorded it.

    `changed_files` is a count rather than the list: the list is diagnostics material and
    an entity attribute is not the place for an unbounded one.
    """

    commit: str | None
    branch: str | None
    deployed_at: str | None
    previous_commit: str | None
    changed_files: int


def read_deployment() -> Deployment | None:
    """Return what `.deployed` says, or None when there is nothing to say.

    Blocking: call it from the executor. None covers every way there is no record, which
    a caller cannot act on differently anyway.
    """
    path = COMPONENT_DIR / DEPLOYED_FILE_NAME
    try:
        data: Any = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        _LOGGER.warning(
            "%s exists but could not be read as JSON, so no deployment record is "
            "reported. The running code is unaffected: this file only describes how it "
            "got here",
            path,
            exc_info=True,
        )
        return None
    if not isinstance(data, dict):
        return None
    changed = data.get("changed_files")
    return Deployment(
        commit=_text(data.get("commit")),
        branch=_text(data.get("branch")),
        deployed_at=_text(data.get("deployed_at")),
        previous_commit=_text(data.get("previous_commit")),
        changed_files=len(changed) if isinstance(changed, list) else 0,
    )


def _text(value: object) -> str | None:
    """Return a string field, or None when it is missing or is not one."""
    return value if isinstance(value, str) else None
