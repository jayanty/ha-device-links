# Dev deploy: GitHub to Home Assistant

How a change on Jayant's laptop becomes running code on Jayant's Home Assistant, and how
to get out of trouble when it does not.

Authoritative spec: `docs/PRD.md` Section 17.5, Decision D21 (b). Tool: `tools/ha_deploy.py`.
Tests: `tests/test_ha_deploy.py`.

---

## 1. The rule that shapes everything

**Home Assistant pulls from GitHub. Nothing is ever copied from the laptop into `/config`.**

The deploy tool downloads the immutable archive for one commit from `codeload.github.com`,
verifies it, byte compiles it, and swaps it into `/config/custom_components/device_links`.
So the deployed directory is always traceable to a commit, and it is the same shape as the
HACS install that eventually replaces it.

The second rule: **Claude never restarts Home Assistant.** Python modules only load on a
restart. Claude deploys, says which commit is waiting, and stops. Jayant restarts.

---

## 2. The loop

```bash
# 1. Local gates. Both must exit 0. Nothing is pushed until they do.
./scripts/lint && ./scripts/test

# 2. Commit and push to dev.
git commit -m "feat(zwave): ..."
git push origin dev

# 3. Trigger the pull on the HA side (Section 3 for the exact invocations).
#    Parse the single JSON object that comes back.

# 4a. restart_required true  -> raise a persistent notification naming the commit, then STOP.
# 4b. restart_required false and browser_reload true -> tell Jayant a hard refresh of the
#     panel is enough, and carry on.

# 5. After Jayant restarts, poll sensor.device_links_health until its `commit` attribute
#    equals the pushed sha and its state is `ok`, then run the read-only live checks.
```

Step 3 never happens before step 1 passes. A deploy is cheap; a broken home is not.

---

## 3. Invoking the tool

### Over SSH (the workhorse, and the fallback when `shell_command` is broken)

Run it **inside the HA Core container**, not in the SSH add-on. The tool byte compiles the
downloaded code with whatever interpreter it is running under, and that check is only
meaningful when it is the interpreter Home Assistant itself will use.

```bash
# deploy the head of dev
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py deploy \
  --repo jayanty/ha-device-links --branch dev --domain device_links'

# deploy one exact commit
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py deploy \
  --repo jayanty/ha-device-links --ref 4f1c0a9e... --domain device_links'

# roll back to the newest backup
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py rollback \
  --domain device_links'

# what is deployed right now
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py status \
  --domain device_links'
```

If `ssh` reports the host as unreachable, retry pinned to `en0` before concluding anything:
`ssh -b 10.10.1.157 root@10.10.1.11` (CLAUDE.md Section 2.1).

`--config-dir` defaults to `/config` and only needs to be passed in tests.

### Over MCP, through `shell_command`

`shell_command` runs inside the HA Core container already, so no `docker exec` is needed.
The one-time block in `configuration.yaml`:

```yaml
shell_command:
  deploy_device_links: >-
    python3 /config/tools/ha_deploy.py deploy
    --repo jayanty/ha-device-links --branch dev --domain device_links
  deploy_device_links_ref: >-
    python3 /config/tools/ha_deploy.py deploy
    --repo jayanty/ha-device-links --ref {{ ref }} --domain device_links
  rollback_device_links: >-
    python3 /config/tools/ha_deploy.py rollback --domain device_links
  device_links_deploy_status: >-
    python3 /config/tools/ha_deploy.py status --domain device_links
```

Then, from Claude Code:

```
ha_call_service(domain="shell_command", service="deploy_device_links", return_response=True)
ha_call_service(domain="shell_command", service="rollback_device_links", return_response=True)
ha_call_service(domain="shell_command", service="device_links_deploy_status", return_response=True)
```

`shell_command` returns `stdout`, `stderr`, and `returncode`, so a failure is visible
immediately without a second round trip.

### One-time bootstrap (Stage 0 item R2)

The tool itself arrives the same way the integration does, by pulling from GitHub:

```bash
ssh root@10.10.1.11 'mkdir -p /config/tools && \
  curl -fsSL https://raw.githubusercontent.com/jayanty/ha-device-links/dev/tools/ha_deploy.py \
    -o /config/tools/ha_deploy.py'
```

Add the `shell_command:` block above to `configuration.yaml`, then Jayant restarts once so
the services exist. Those two edits are the only changes we ever make to `/config` outside
`custom_components/device_links` and `/config/device_links/`.

Refresh the tool the same way whenever `tools/ha_deploy.py` changes in the repository. The
tool does not update itself: it deploys the integration, not itself.

---

## 4. The JSON contract

**stdout carries exactly one JSON object and nothing else, or it is empty.** Diagnostics
from `compileall` are captured, so they can never corrupt it.

Success, exit code 0:

```json
{
  "ok": true,
  "commit": "4f1c0a9e...",
  "previous_commit": "9b2d61c0...",
  "changed_files": ["const.py", "frontend/device-links-panel.js"],
  "restart_required": true,
  "browser_reload": true
}
```

| Field | Meaning |
|---|---|
| `commit` | The commit now deployed. For `status` this is what `.deployed` records. |
| `previous_commit` | What was deployed before this call, or `null` on a first deploy. |
| `changed_files` | Paths relative to `custom_components/device_links/`, added, removed, or with different bytes. `__pycache__`, `*.pyc`, and `.deployed` are excluded. |
| `restart_required` | True when any changed path is outside `frontend/`. Python only loads on a restart. |
| `browser_reload` | True when any changed path is under `frontend/`. A hard refresh of the panel picks it up. |

Failure, exit code 1: stdout is empty and **stderr** carries
`{"ok": false, "error": "<what went wrong>"}`. Nothing was swapped into place.

`status` prints the `.deployed` file itself, which has a different shape:
`{"commit", "branch", "deployed_at", "previous_commit", "changed_files"}`. The Health sensor
reads the same file and exposes `commit` and `deployed_at`.

---

## 5. What the tool will not do

- It never restarts Home Assistant and never reloads a config entry. A restart is Jayant's.
- It never reads or writes `/config/.storage`.
- It never touches any other integration, `configuration.yaml`, or anything else in `/config`.
- It executes nothing from the archive. It byte compiles, which parses without running.
- It extracts only `custom_components/<domain>/`. `docs/`, `tests/`, and the rest of the
  repository never reach the host.
- It refuses a non-HTTPS URL, a repository argument that is not a plain `owner/name`, a `--ref`
  that is not a commit sha, an archive with more than one top level directory, an archive
  whose `manifest.json` declares a different domain, an archive entry that escapes the target
  directory, and any symlink entry.
- The repository is pinned by the command line. Nothing in the archive can redirect it.

**If any step fails, the currently deployed directory is byte for byte what it was.** The new
code is assembled in `/config/custom_components/.device_links.new` and only ever reaches
`custom_components/device_links` through two renames in the same directory, after the archive
has been verified, extracted, and compiled. `tests/test_ha_deploy.py` proves this for a
download failure, a corrupt archive, a domain mismatch, and a syntax error.

---

## 6. Rolling back

```bash
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py rollback \
  --domain device_links'
```

Before every swap, the current directory is copied to
`/config/device_links/backups/<timestamp>-<oldsha>/`, and the five most recent are kept.
`rollback` restores the newest backup with the same atomic swap and prints the same JSON
shape. It consumes that backup, so a second `rollback` walks one step further back.

A rollback of Python code needs a restart to take effect, exactly like a deploy. Say so, and
stop. Then open a regression test for whatever made the rollback necessary.

---

## 7. When the deploy tool itself is broken

Symptoms: `shell_command` returns a non-zero code with unparseable output, the tool raises a
traceback instead of the error JSON, or `status` disagrees with what is on disk.

SSH in and look. All of this is read-only:

```bash
ssh root@10.10.1.11

# what is actually deployed
ls -la /config/custom_components/device_links/
cat  /config/custom_components/device_links/.deployed

# a staging directory left behind means a run died mid-flight.
# The deployed directory is still intact; this is only litter.
ls -la /config/custom_components/ | grep '^\.'

# what can be rolled back to, newest last
ls -1 /config/device_links/backups/

# run the tool by hand to see the raw error
docker exec homeassistant python3 /config/tools/ha_deploy.py status --domain device_links
echo "exit=$?"

# is the integration loading at all
ha core logs 2>&1 | grep -i device_links | tail -50
```

Recovery, in order of preference:

1. **Roll back.** If the deployed code is bad but the tool works, `rollback` and tell Jayant.
2. **Re-fetch the tool.** If the tool itself is the problem, re-run the bootstrap `curl` in
   Section 3 to pull a fixed `tools/ha_deploy.py` from `dev`, then retry. Fix the tool in the
   repository first, with a test, and push it. Never hand-edit `/config/tools/ha_deploy.py`:
   an edit that exists only on the host is invisible to everyone and to CI.
3. **Restore a backup by hand.** Only if the tool cannot run at all. Copy, do not move, so the
   backup survives a mistake:

   ```bash
   docker exec homeassistant sh -c '
     cp -a /config/device_links/backups/<timestamp>-<sha> /config/custom_components/.device_links.new &&
     mv /config/custom_components/device_links /config/custom_components/.device_links.broken &&
     mv /config/custom_components/.device_links.new /config/custom_components/device_links'
   ```

   Then tell Jayant a restart is needed, and remove `.device_links.broken` once the restart
   has proven the restore good.
4. **Remove the integration.** If `device_links` is preventing Home Assistant from starting at
   all, `mv /config/custom_components/device_links /config/device_links_quarantine`. Home
   Assistant starts without it. This is the last resort and it needs Jayant, because it means
   telling him his home automation is down.

Leftover staging directories (`.device_links.new`, `.device_links.previous`) are safe to
delete. The next deploy clears them on its own.

The Claude Terminal add-on is the fallback channel when SSH is the thing that is broken.

---

## 8. Checklist for a Claude session

- [ ] `./scripts/lint` and `./scripts/test` both exited 0.
- [ ] Committed with a conventional message and pushed to `dev`.
- [ ] Deployed, and parsed the one JSON object.
- [ ] Reported the commit and `changed_files` to Jayant.
- [ ] If `restart_required`: raised a persistent notification naming the commit, and **stopped**.
      Did not call `ha_restart`, `homeassistant.restart`, or a config entry reload.
- [ ] If only `browser_reload`: said a hard refresh of the panel is enough.
- [ ] After the restart: `sensor.device_links_health` reports the pushed sha and state `ok`,
      then read-only live checks and Repairs.
