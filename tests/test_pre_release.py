"""Release maintainer script checks."""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "pre_release.sh"


def _run(*args: str, root: Path) -> subprocess.CompletedProcess[str]:
    env = {"PAPERFUL_RELEASE_ROOT": str(root)}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
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


def test_dist_only_accepts_matching_version(tmp_path: Path) -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"paperful-{version}-py3-none-any.whl").write_bytes(b"x")
    (dist / f"paperful-{version}.tar.gz").write_bytes(b"x")

    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")

    proc = _run("--dist-only", root=tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
