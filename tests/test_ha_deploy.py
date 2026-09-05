"""The deploy tool must fail safe: a bad archive never reaches custom_components."""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest
from tools import ha_deploy
from tools.ha_deploy import (
    DeployError,
    deploy,
    extract_component,
    main,
    prune_backups,
    require_https,
    rollback,
    status,
    verify_archive,
)

ROOT = "ha-device-links-abc123"
MANIFEST = json.dumps({"domain": "device_links", "version": "0.0.1"})


def _archive(files: dict[str, str], root: str = ROOT) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(f"{root}/{name}", body)
    return buf.getvalue()


def _component_archive(files: dict[str, str], root: str = ROOT) -> bytes:
    """Build a repository archive whose component subtree holds `files`."""
    payload = {f"custom_components/device_links/{name}": body for name, body in files.items()}
    payload.setdefault("custom_components/device_links/manifest.json", MANIFEST)
    payload["README.md"] = "not deployed"
    return _archive(payload, root=root)


def _snapshot(root: Path) -> dict[str, bytes]:
    """Byte-exact picture of a directory, used to prove nothing moved."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_deployment(config_dir: Path, files: dict[str, str], commit: str) -> Path:
    component = config_dir / "custom_components" / "device_links"
    component.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        target = component / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    (component / ".deployed").write_text(
        json.dumps(
            {
                "commit": commit,
                "branch": "dev",
                "deployed_at": "2026-09-05T00:00:00Z",
                "previous_commit": None,
                "changed_files": sorted(files),
            }
        )
    )
    return component


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub the two network calls. No test in this file may touch the network."""
    state: dict[str, object] = {"sha": "a" * 40, "archive": b"", "calls": []}

    def _resolve(repo: str, branch: str) -> str:
        calls = state["calls"]
        assert isinstance(calls, list)
        calls.append(("resolve", repo, branch))
        return str(state["sha"])

    def _download(repo: str, sha: str) -> bytes:
        calls = state["calls"]
        assert isinstance(calls, list)
        calls.append(("download", repo, sha))
        archive = state["archive"]
        if isinstance(archive, Exception):
            raise archive
        assert isinstance(archive, bytes)
        return archive

    monkeypatch.setattr(ha_deploy, "resolve_commit", _resolve)
    monkeypatch.setattr(ha_deploy, "download_archive", _download)
    return state


# --------------------------------------------------------------------------- #
# Archive validation
# --------------------------------------------------------------------------- #


def test_a_valid_archive_passes() -> None:
    data = _archive(
        {
            "custom_components/device_links/manifest.json": json.dumps({"domain": "device_links"}),
            "custom_components/device_links/__init__.py": "",
        }
    )
    assert verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links") == (
        "ha-device-links-abc123"
    )


def test_an_archive_without_the_component_is_refused() -> None:
    data = _archive({"README.md": "nothing here"})
    with pytest.raises(DeployError, match=r"manifest\.json"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_a_domain_mismatch_is_refused() -> None:
    data = _archive(
        {"custom_components/device_links/manifest.json": json.dumps({"domain": "something_else"})}
    )
    with pytest.raises(DeployError, match="domain"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_more_than_one_top_level_directory_is_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/custom_components/device_links/manifest.json", MANIFEST)
        zf.writestr("b/other.txt", "x")
    with pytest.raises(DeployError, match="one top level directory"):
        verify_archive(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "device_links")


def test_an_unparseable_manifest_is_refused() -> None:
    data = _archive({"custom_components/device_links/manifest.json": "{not json"})
    with pytest.raises(DeployError, match="valid JSON"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_path_traversal_in_the_archive_is_refused(tmp_path: Path) -> None:
    """A zip entry escaping the target directory must never be written."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "root/custom_components/device_links/manifest.json", '{"domain":"device_links"}'
        )
        zf.writestr("root/custom_components/device_links/../../../etc/evil", "pwned")

    with pytest.raises(DeployError, match="escapes"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path
        )
    assert not (tmp_path.parent / "etc" / "evil").exists()


def test_traversal_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    """Validation is a whole-archive pass, so a bad entry leaves no partial tree."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "root/custom_components/device_links/manifest.json", '{"domain":"device_links"}'
        )
        zf.writestr("root/custom_components/device_links/../escape.py", "X = 1")

    target = tmp_path / "staging"
    with pytest.raises(DeployError, match="escapes"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", target
        )
    assert _snapshot(target) == {}, "no file may be written when any entry is rejected"


def test_a_symlink_entry_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "root/custom_components/device_links/manifest.json", '{"domain":"device_links"}'
        )
        info = zipfile.ZipInfo("root/custom_components/device_links/link.py")
        info.create_system = 3
        info.external_attr = (0o120777 << 16) | 0o20
        zf.writestr(info, "/etc/passwd")

    with pytest.raises(DeployError, match="symlink"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path / "s"
        )


def test_extract_writes_only_the_component_subtree(tmp_path: Path) -> None:
    data = _archive(
        {
            "custom_components/device_links/manifest.json": '{"domain":"device_links"}',
            "custom_components/device_links/const.py": "X = 1",
            "docs/PRD.md": "should not be deployed",
            "tests/test_x.py": "should not be deployed",
        }
    )
    extract_component(
        zipfile.ZipFile(io.BytesIO(data)), "ha-device-links-abc123", "device_links", tmp_path
    )

    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "const.py").read_text() == "X = 1"
    assert not (tmp_path / "docs").exists(), "only custom_components/<domain> is deployed"


# --------------------------------------------------------------------------- #
# Transport safety
# --------------------------------------------------------------------------- #


def test_a_non_https_url_is_rejected() -> None:
    with pytest.raises(DeployError, match="non-https"):
        require_https("http://api.github.com/repos/jayanty/ha-device-links/commits/dev")
    assert require_https("https://api.github.com/x") == "https://api.github.com/x"


def test_resolve_commit_refuses_a_plain_http_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a misconfigured base URL cannot make the tool fetch over plain HTTP."""
    monkeypatch.setattr(ha_deploy, "API_BASE", "http://api.github.com")
    with pytest.raises(DeployError, match="non-https"):
        ha_deploy.resolve_commit("jayanty/ha-device-links", "dev")


def test_download_archive_refuses_a_plain_http_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ha_deploy, "CODELOAD_BASE", "http://codeload.github.com")
    with pytest.raises(DeployError, match="non-https"):
        ha_deploy.download_archive("jayanty/ha-device-links", "b" * 40)


@pytest.mark.parametrize("repo", ["", "noslash", "a/b/c", "../etc", "owner/..", "own er/name"])
def test_a_malformed_repo_argument_is_refused(repo: str, tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="owner/name"):
        deploy(tmp_path, repo, "device_links", branch="dev")


def test_a_malformed_ref_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="commit sha"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", ref="dev; rm -rf /")


def test_the_module_imports_only_the_standard_library() -> None:
    """It runs inside the HA Core container, where nothing else is guaranteed."""
    source = Path(ha_deploy.__file__).read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    outside = sorted(imported - set(sys.stdlib_module_names) - {"__future__"})
    assert not outside, f"ha_deploy.py must be stdlib only, found: {outside}"


def test_the_module_never_mentions_storage_or_a_restart() -> None:
    source = Path(ha_deploy.__file__).read_text()
    body = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in (".storage", "homeassistant.restart", "ha core restart"):
        assert forbidden not in body, f"the deploy tool must never reference {forbidden}"


# --------------------------------------------------------------------------- #
# The property that matters: a failure changes nothing
# --------------------------------------------------------------------------- #


def test_a_compile_failure_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "GOOD = 1"}, "old" + "0" * 37
    )
    before = _snapshot(component)

    github["sha"] = "b" * 40
    github["archive"] = _component_archive({"const.py": "def broken(:\n"})

    with pytest.raises(DeployError, match="does not compile"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before, "a syntax error must never reach custom_components"
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()
    assert not (tmp_path / "device_links" / "backups").exists(), "no backup for a failed deploy"


def test_a_download_failure_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "c" * 40
    )
    before = _snapshot(component)

    github["archive"] = DeployError("cannot fetch https://codeload.github.com/...: timed out")
    with pytest.raises(DeployError, match="cannot fetch"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()


def test_a_bad_archive_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "d" * 40
    )
    before = _snapshot(component)

    github["archive"] = b"this is not a zip file"
    with pytest.raises(DeployError):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()


def test_a_domain_mismatch_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "e" * 40
    )
    before = _snapshot(component)

    github["archive"] = _archive(
        {"custom_components/device_links/manifest.json": json.dumps({"domain": "impostor"})}
    )
    with pytest.raises(DeployError, match="domain"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_first_deploy_creates_the_component_without_a_backup(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    component = tmp_path / "custom_components" / "device_links"
    assert (component / "const.py").read_text() == "X = 1"
    assert result["ok"] is True
    assert result["commit"] == "1" * 40
    assert result["previous_commit"] is None
    assert result["changed_files"] == ["const.py", "manifest.json"]
    assert result["restart_required"] is True
    assert not (tmp_path / "device_links" / "backups").exists()
    assert not (component / "README.md").exists(), "only the component subtree is deployed"


def test_a_successful_deploy_over_an_existing_deployment(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path,
        {"manifest.json": MANIFEST, "const.py": "X = 1", "gone.py": "OLD = 1"},
        "0" * 40,
    )
    github["sha"] = "2" * 40
    github["archive"] = _component_archive({"const.py": "X = 2", "new.py": "NEW = 1"})

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert result["changed_files"] == ["const.py", "gone.py", "new.py"]
    assert result["previous_commit"] == "0" * 40
    assert result["commit"] == "2" * 40
    assert result["restart_required"] is True
    assert result["browser_reload"] is False

    assert (component / "const.py").read_text() == "X = 2"
    assert (component / "new.py").read_text() == "NEW = 1"
    assert not (component / "gone.py").exists(), "removed files must not survive the swap"
    assert not list(component.rglob("__pycache__")), "compileall leftovers must be cleaned up"

    marker = json.loads((component / ".deployed").read_text())
    assert marker["commit"] == "2" * 40
    assert marker["branch"] == "dev"
    assert marker["previous_commit"] == "0" * 40
    assert marker["changed_files"] == ["const.py", "gone.py", "new.py"]
    assert marker["deployed_at"].endswith("Z")

    backups = sorted((tmp_path / "device_links" / "backups").iterdir())
    assert len(backups) == 1, "exactly one backup per deploy"
    assert (backups[0] / "const.py").read_text() == "X = 1"
    assert (backups[0] / "gone.py").read_text() == "OLD = 1"


def test_an_unchanged_redeploy_reports_no_changes(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "3" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", ref="3" * 40)

    assert result["changed_files"] == []
    assert result["restart_required"] is False
    assert result["browser_reload"] is False


def test_deploy_touches_nothing_else_under_the_config_directory(
    tmp_path: Path, github: dict[str, object]
) -> None:
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "device_links.profiles").write_text('{"data": "precious"}')
    (tmp_path / "configuration.yaml").write_text("default_config:\n")
    (tmp_path / "custom_components" / "spook").mkdir(parents=True)
    (tmp_path / "custom_components" / "spook" / "__init__.py").write_text("SPOOK = 1")
    outside = _snapshot(storage) | _snapshot(tmp_path / "custom_components" / "spook")

    github["sha"] = "4" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(storage) | _snapshot(tmp_path / "custom_components" / "spook") == outside
    assert (tmp_path / "configuration.yaml").read_text() == "default_config:\n"


# --------------------------------------------------------------------------- #
# restart_required and browser_reload
# --------------------------------------------------------------------------- #


def test_only_a_frontend_change_needs_a_browser_reload_not_a_restart(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "5" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 1", "frontend/device-links-panel.js": "console.log(1);"}
    )
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    github["sha"] = "6" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 1", "frontend/device-links-panel.js": "console.log(2);"}
    )
    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert result["changed_files"] == ["frontend/device-links-panel.js"]
    assert result["restart_required"] is False
    assert result["browser_reload"] is True


def test_a_python_change_requires_a_restart(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "7" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 1", "frontend/device-links-panel.js": "console.log(1);"}
    )
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    github["sha"] = "8" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 2", "frontend/device-links-panel.js": "console.log(2);"}
    )
    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert result["changed_files"] == ["const.py", "frontend/device-links-panel.js"]
    assert result["restart_required"] is True
    assert result["browser_reload"] is True


# --------------------------------------------------------------------------- #
# Backups and rollback
# --------------------------------------------------------------------------- #


def test_backup_retention_keeps_five_and_prunes_the_sixth(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    names = [f"2026090{index}T120000Z-sha{index}" for index in range(1, 7)]
    for name in names:
        (backups / name).mkdir(parents=True)

    removed = prune_backups(backups, keep=5)

    assert removed == [names[0]], "the oldest backup is the one that goes"
    assert sorted(path.name for path in backups.iterdir()) == names[1:]


def test_repeated_deploys_never_grow_past_five_backups(
    tmp_path: Path, github: dict[str, object]
) -> None:
    for index in range(7):
        github["sha"] = str(index) * 40
        github["archive"] = _component_archive({"const.py": f"X = {index}"})
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    backups = list((tmp_path / "device_links" / "backups").iterdir())
    assert len(backups) == 5, "the backups directory must not grow without bound"


def test_rollback_restores_the_previous_content_exactly(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "a" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1", "keep.py": "K = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    component = tmp_path / "custom_components" / "device_links"
    good = _snapshot(component)

    github["sha"] = "b" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    assert (component / "const.py").read_text() == "BAD = 1"

    result = rollback(tmp_path, "device_links")

    assert (component / "const.py").read_text() == "GOOD = 1"
    assert (component / "keep.py").read_text() == "K = 1"
    assert result["ok"] is True
    assert result["commit"] == "a" * 40
    assert result["previous_commit"] == "b" * 40
    assert result["changed_files"] == ["const.py", "keep.py"]
    assert result["restart_required"] is True

    restored = _snapshot(component)
    assert {name: body for name, body in restored.items() if name != ".deployed"} == {
        name: body for name, body in good.items() if name != ".deployed"
    }
    marker = json.loads((component / ".deployed").read_text())
    assert marker["commit"] == "a" * 40
    assert marker["previous_commit"] == "b" * 40


def test_rollback_without_a_backup_fails_cleanly(tmp_path: Path) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST}, "f" * 40)
    with pytest.raises(DeployError, match="no backup"):
        rollback(tmp_path, "device_links")


# --------------------------------------------------------------------------- #
# status and the command line
# --------------------------------------------------------------------------- #


def test_status_on_a_never_deployed_domain_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(DeployError, match="not installed"):
        status(tmp_path, "device_links")

    (tmp_path / "custom_components" / "device_links").mkdir(parents=True)
    with pytest.raises(DeployError, match="never deployed"):
        status(tmp_path, "device_links")

    code = main(["status", "--config-dir", str(tmp_path), "--domain", "device_links"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == "", "stdout stays clean so a caller can always parse it"
    assert json.loads(captured.err)["ok"] is False
    assert "never deployed" in json.loads(captured.err)["error"]


def test_status_prints_the_deployed_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST}, "9" * 40)

    code = main(["status", "--config-dir", str(tmp_path), "--domain", "device_links"])

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["commit"] == "9" * 40
    assert document["branch"] == "dev"


def test_the_command_line_prints_exactly_one_json_object(
    tmp_path: Path, github: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    github["sha"] = "c" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})

    code = main(
        [
            "deploy",
            "--config-dir",
            str(tmp_path),
            "--repo",
            "jayanty/ha-device-links",
            "--branch",
            "dev",
            "--domain",
            "device_links",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert len(captured.out.strip().splitlines()) == 1
    document = json.loads(captured.out)
    assert set(document) == {
        "ok",
        "commit",
        "previous_commit",
        "changed_files",
        "restart_required",
        "browser_reload",
    }
    assert document["ok"] is True
    assert github["calls"] == [
        ("resolve", "jayanty/ha-device-links", "dev"),
        ("download", "jayanty/ha-device-links", "c" * 40),
    ]


def test_an_explicit_ref_skips_the_branch_lookup(tmp_path: Path, github: dict[str, object]) -> None:
    github["archive"] = _component_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", ref="D" * 40)

    assert result["commit"] == "d" * 40
    assert github["calls"] == [("download", "jayanty/ha-device-links", "d" * 40)]
    marker = json.loads((tmp_path / "custom_components" / "device_links" / ".deployed").read_text())
    assert marker["branch"] is None


def test_deploy_needs_a_branch_or_a_ref(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="--ref or --branch"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links")


def test_the_command_line_reports_a_failure_on_stderr(
    tmp_path: Path, github: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "0" * 40)
    github["archive"] = b"not a zip"

    code = main(
        [
            "deploy",
            "--config-dir",
            str(tmp_path),
            "--repo",
            "jayanty/ha-device-links",
            "--branch",
            "dev",
            "--domain",
            "device_links",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert json.loads(captured.err)["ok"] is False
    assert (tmp_path / "custom_components" / "device_links" / "const.py").read_text() == "X = 1"


# --------------------------------------------------------------------------- #
# Error paths that only ever run when something has already gone wrong
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amount: int) -> bytes:
        return self._payload[:amount]

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_fetch_returns_the_body_over_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ha_deploy.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b"hello")
    )
    assert ha_deploy._fetch("https://example.invalid/x", timeout=1.0, accept="*/*") == b"hello"


def test_fetch_turns_a_network_error_into_a_deploy_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: object, timeout: float) -> object:
        raise ha_deploy.urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", _boom)
    with pytest.raises(DeployError, match="cannot fetch"):
        ha_deploy._fetch("https://example.invalid/x", timeout=1.0, accept="*/*")


def test_fetch_refuses_an_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ha_deploy, "MAX_ARCHIVE_BYTES", 8)
    monkeypatch.setattr(
        ha_deploy.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b"x" * 64)
    )
    with pytest.raises(DeployError, match="larger than"):
        ha_deploy._fetch("https://example.invalid/x", timeout=1.0, accept="*/*")


def test_resolve_commit_reads_the_sha_from_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ha_deploy, "_fetch", lambda url, timeout, accept: json.dumps({"sha": "A" * 40}).encode()
    )
    assert ha_deploy.resolve_commit("jayanty/ha-device-links", "dev") == "a" * 40


def test_resolve_commit_refuses_a_response_that_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ha_deploy, "_fetch", lambda url, timeout, accept: b"<html>rate limited")
    with pytest.raises(DeployError, match="not JSON"):
        ha_deploy.resolve_commit("jayanty/ha-device-links", "dev")


@pytest.mark.parametrize("body", [b"[]", b'{"message":"Not Found"}', b'{"sha":"nope"}'])
def test_resolve_commit_refuses_a_response_without_a_sha(
    body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ha_deploy, "_fetch", lambda url, timeout, accept: body)
    with pytest.raises(DeployError, match="did not return a commit sha"):
        ha_deploy.resolve_commit("jayanty/ha-device-links", "dev")


def test_a_branch_name_that_is_not_a_ref_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="valid ref name"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev; rm -rf /")


def test_an_empty_archive_is_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("  ", "")
    with pytest.raises(DeployError, match="empty"):
        verify_archive(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "device_links")


def test_an_archive_whose_component_holds_only_directories_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/custom_components/other/manifest.json", MANIFEST)
    with pytest.raises(DeployError, match="no files under"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path / "s"
        )


def test_directory_entries_in_the_archive_are_created(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/custom_components/device_links/", "")
        zf.writestr("root/custom_components/device_links/translations/", "")
        zf.writestr("root/custom_components/device_links/translations/en.json", "{}")

    target = tmp_path / "s"
    extract_component(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", target)

    assert (target / "translations" / "en.json").read_text() == "{}"


@pytest.mark.parametrize("body", ["{not json", '["a list"]'])
def test_a_damaged_deployed_marker_reads_as_never_deployed(body: str, tmp_path: Path) -> None:
    component = tmp_path / "custom_components" / "device_links"
    component.mkdir(parents=True)
    (component / ".deployed").write_text(body)

    assert ha_deploy.read_deployed(component) is None
    with pytest.raises(DeployError, match="never deployed"):
        status(tmp_path, "device_links")


def test_a_stray_file_where_staging_belongs_is_cleared(
    tmp_path: Path, github: dict[str, object]
) -> None:
    (tmp_path / "custom_components").mkdir()
    (tmp_path / "custom_components" / ".device_links.new").write_text("litter")

    github["sha"] = "e" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert (tmp_path / "custom_components" / "device_links" / "const.py").read_text() == "X = 1"


def test_two_backups_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    component = _seed_deployment(tmp_path, {"manifest.json": MANIFEST}, "f" * 40)
    backups = tmp_path / "device_links" / "backups"

    first = ha_deploy.create_backup(component, backups, "f" * 40)
    second = ha_deploy.create_backup(component, backups, "f" * 40)

    assert first != second
    assert len(list(backups.iterdir())) == 2


def test_a_failed_swap_puts_the_previous_directory_straight_back(tmp_path: Path) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "0" * 40
    )
    before = _snapshot(component)
    missing = tmp_path / "custom_components" / ".device_links.new"

    with pytest.raises(DeployError, match="could not swap"):
        ha_deploy.swap_into_place(missing, component)

    assert _snapshot(component) == before, "a failed swap must restore the previous directory"
    assert not (tmp_path / "custom_components" / ".device_links.previous").exists()


def test_rollback_over_the_command_line(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    github["sha"] = "2" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    code = main(["rollback", "--config-dir", str(tmp_path), "--domain", "device_links"])

    assert code == 0
    component = tmp_path / "custom_components" / "device_links"
    assert (component / "const.py").read_text() == "GOOD = 1"


def test_a_leftover_previous_directory_is_cleared_before_the_swap(
    tmp_path: Path, github: dict[str, object]
) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "3" * 40)
    stale = tmp_path / "custom_components" / ".device_links.previous"
    stale.mkdir()
    (stale / "junk.py").write_text("JUNK = 1")

    github["sha"] = "4" * 40
    github["archive"] = _component_archive({"const.py": "X = 2"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert not stale.exists(), "litter from an interrupted run must not survive a deploy"
    assert (tmp_path / "custom_components" / "device_links" / "const.py").read_text() == "X = 2"


def test_a_failed_first_swap_reports_cleanly(tmp_path: Path) -> None:
    components = tmp_path / "custom_components"
    components.mkdir()
    with pytest.raises(DeployError, match="could not swap"):
        ha_deploy.swap_into_place(components / ".device_links.new", components / "device_links")
    assert not (components / "device_links").exists()


def test_a_failed_rollback_leaves_the_current_deployment_intact(
    tmp_path: Path, github: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    github["sha"] = "5" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    github["sha"] = "6" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    component = tmp_path / "custom_components" / "device_links"
    before = _snapshot(component)

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(ha_deploy.shutil, "copytree", _boom)
    with pytest.raises(DeployError, match="rollback aborted"):
        rollback(tmp_path, "device_links")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()
    assert len(list((tmp_path / "device_links" / "backups").iterdir())) == 1, "backup is kept"


def test_a_rollback_that_cannot_swap_leaves_the_current_deployment_intact(
    tmp_path: Path, github: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    github["sha"] = "7" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    github["sha"] = "8" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    component = tmp_path / "custom_components" / "device_links"
    before = _snapshot(component)

    def _refuse(staging: Path, current: Path) -> None:
        raise DeployError("could not swap the new directory into place: simulated")

    monkeypatch.setattr(ha_deploy, "swap_into_place", _refuse)
    with pytest.raises(DeployError, match="could not swap"):
        rollback(tmp_path, "device_links")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()
