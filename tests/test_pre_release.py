"""Release maintainer script checks."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "pre_release.sh"
DOGFOOD_STATUS = ROOT / "scripts" / "release" / "dogfood_status.sh"


def _bash() -> str:
    """A real bash. On Windows, ``bash`` on PATH is often the WSL stub."""
    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ):
            if Path(candidate).is_file():
                return candidate
    found = shutil.which("bash")
    return found or "bash"


def _run(*args: str, root: Path) -> subprocess.CompletedProcess[str]:
    env = {"PAPERFUL_RELEASE_ROOT": str(root)}
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell, operator-configured tool
        [_bash(), str(SCRIPT), *args],  # noqa: S607 -- Git bash on Windows, PATH bash elsewhere
        cwd=root,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_dist_only_rejects_stale_artifacts(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    # Minimal fake names (content not read).
    (dist / "paperful-0.9.0-py3-none-any.whl").write_bytes(b"x")
    (dist / "paperful-1.1.1-py3-none-any.whl").write_bytes(b"x")
    (dist / "paperful-1.1.0.tar.gz").write_bytes(b"x")

    pyproject = tmp_path / "pyproject.toml"
    shutil.copy(ROOT / "pyproject.toml", pyproject)

    proc = _run("--dist-only", root=tmp_path)
    assert proc.returncode != 0
    assert "stale dist artifact" in proc.stderr + proc.stdout
    assert "0.9.0" in proc.stderr + proc.stdout


def _project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith('version = "'):
            return line.split('"', 2)[1]
    raise AssertionError("pyproject.toml has no version")


def test_dist_only_accepts_matching_version(tmp_path: Path) -> None:
    version = _project_version()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"paperful-{version}-py3-none-any.whl").write_bytes(b"x")
    (dist / f"paperful-{version}.tar.gz").write_bytes(b"x")

    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")

    proc = _run("--dist-only", root=tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_dogfood_gate_blocks_release_when_active(tmp_path: Path) -> None:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(ROOT / "CHANGELOG.md", tmp_path / "CHANGELOG.md")
    shutil.copytree(ROOT / "website", tmp_path / "website")
    (tmp_path / "docs" / "dogfood").mkdir(parents=True)
    shutil.copy(ROOT / "docs/dogfood/since-bbnj.md", tmp_path / "docs/dogfood/since-bbnj.md")

    proc = _run(root=tmp_path)
    assert proc.returncode != 0
    assert "since dogfood incomplete" in proc.stderr + proc.stdout


def test_dogfood_status_reports_incomplete(tmp_path: Path) -> None:
    (tmp_path / "docs" / "dogfood").mkdir(parents=True)
    shutil.copy(ROOT / "docs/dogfood/since-bbnj.md", tmp_path / "docs/dogfood/since-bbnj.md")
    proc = subprocess.run(  # noqa: S603
        [_bash(), str(DOGFOOD_STATUS)],
        cwd=tmp_path,
        env={**os.environ, "PAPERFUL_RELEASE_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "active" in proc.stdout
    assert "0/8" in proc.stdout


def test_dogfood_status_passes_when_verdicts_met(tmp_path: Path) -> None:
    import re

    (tmp_path / "docs" / "dogfood").mkdir(parents=True)
    tracker = tmp_path / "docs/dogfood/since-bbnj.md"
    lines: list[str] = []
    for line in (ROOT / "docs/dogfood/since-bbnj.md").read_text(encoding="utf-8").splitlines():
        if re.match(r"^\| [1-4] \|", line):
            parts = line.split("|")
            if len(parts) > 8:
                parts[7] = " actionable "
                line = "|".join(parts)
        lines.append(line)
    tracker.write_text("\n".join(lines), encoding="utf-8")

    proc = subprocess.run(  # noqa: S603
        [_bash(), str(DOGFOOD_STATUS)],
        cwd=tmp_path,
        env={**os.environ, "PAPERFUL_RELEASE_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "active 8/8" in proc.stdout


def test_dogfood_status_complete(tmp_path: Path) -> None:
    (tmp_path / "docs" / "dogfood").mkdir(parents=True)
    tracker = tmp_path / "docs/dogfood/since-bbnj.md"
    shutil.copy(ROOT / "docs/dogfood/since-bbnj.md", tracker)
    tracker.write_text(
        tracker.read_text(encoding="utf-8").replace(
            "dogfood_gate: active", "dogfood_gate: complete"
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(  # noqa: S603
        [_bash(), str(DOGFOOD_STATUS)],
        cwd=tmp_path,
        env={**os.environ, "PAPERFUL_RELEASE_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "complete"


def test_dogfood_gate_skipped_when_complete(tmp_path: Path) -> None:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(ROOT / "CHANGELOG.md", tmp_path / "CHANGELOG.md")
    shutil.copytree(ROOT / "website", tmp_path / "website")
    (tmp_path / "docs" / "dogfood").mkdir(parents=True)
    tracker = tmp_path / "docs/dogfood/since-bbnj.md"
    shutil.copy(ROOT / "docs/dogfood/since-bbnj.md", tracker)
    text = tracker.read_text(encoding="utf-8").replace(
        "dogfood_gate: active", "dogfood_gate: complete"
    )
    tracker.write_text(text, encoding="utf-8")

    proc = _run(root=tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
