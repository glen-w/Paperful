"""paperful: fetch missing PDFs for Zotero items and attach them back."""

from __future__ import annotations


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("paperful")
    except Exception:
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        data = tomllib.loads(root.joinpath("pyproject.toml").read_bytes())
        return str(data["project"]["version"])


__version__ = _version()
