"""Stage 0 P1 (static half): evidence that the ha-* components the panel needs exist.

Detection note: Home Assistant's frontend registers elements with Lit's @customElement
decorator, which minifies away from a literal customElements.define( call, so scanning
for that call finds almost nothing and is a false negative. What survives minification is
the tag name as a string literal, because the decorator takes it as one. Presence of the
literal is strong evidence the element is defined, but it is not proof of registration:
only the runtime spike can confirm that, and it needs a Home Assistant restart.
"""

import json
import pathlib
import re

import hass_frontend

root = pathlib.Path(hass_frontend.__file__).parent

WANTED = [
    "ha-top-app-bar-fixed",
    "ha-menu-button",
    "ha-tabs",
    "ha-tab-group",
    "ha-card",
    "ha-data-table",
    "ha-dialog",
    "ha-form",
    "ha-alert",
    "ha-button",
    "ha-icon-button",
    "ha-switch",
    "ha-select",
    "ha-list-item",
    "ha-expansion-panel",
    "ha-chip-set",
    "ha-assist-chip",
    "ha-spinner",
    "ha-markdown",
    "ha-svg-icon",
    "ha-textfield",
    "ha-icon",
    "ha-fab",
    "ha-checkbox",
    "ha-tooltip",
]

literals = dict.fromkeys(WANTED, 0)
all_ha_tags: set[str] = set()
tag_pattern = re.compile(rb'["\'](ha-[a-z0-9-]{2,40})["\']')
scanned = 0

for path in root.rglob("*.js"):
    try:
        blob = path.read_bytes()
    except OSError:
        continue
    scanned += 1
    for match in tag_pattern.finditer(blob):
        all_ha_tags.add(match.group(1).decode())
    for tag in WANTED:
        needle = tag.encode()
        if b'"' + needle + b'"' in blob or b"'" + needle + b"'" in blob:
            literals[tag] += 1

result = {
    "frontend_root": str(root),
    "js_files_scanned": scanned,
    "detection_method": "tag name as a string literal (see module docstring)",
    "files_mentioning_tag": literals,
    "present": {tag: count > 0 for tag, count in literals.items()},
    "missing": sorted(tag for tag, count in literals.items() if count == 0),
    "distinct_ha_tags_seen": len(all_ha_tags),
    "runtime_confirmation": "pending: needs a Home Assistant restart and a loaded panel",
}
print(json.dumps(result, indent=1))
