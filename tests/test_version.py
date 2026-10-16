"""Package version single-source (pyproject.toml)."""

from __future__ import annotations

import inspect
import re
import tomllib
from pathlib import Path

from paperful import __version__


def test_version_matches_pyproject():
    root = Path(__file__).resolve().parents[1]
    expected = tomllib.load((root / "pyproject.toml").open("rb"))["project"]["version"]
    assert __version__ == expected


def test_init_has_no_stale_literal_version():
    root = Path(__file__).resolve().parents[1]
    text = (root / "paperful" / "__init__.py").read_text(encoding="utf-8")
    assert not re.search(r'__version__\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"', text)


def test_run_server_defaults_to_localhost():
    from paperful.serve import run_server

    assert inspect.signature(run_server).parameters["host"].default == "127.0.0.1"
