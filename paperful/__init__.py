"""paperful: fetch missing PDFs for Zotero items and attach them back."""

from __future__ import annotations


def _version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("paperful")
    except (PackageNotFoundError, OSError, ValueError):
        from pathlib import Path

        import tomllib

        root = Path(__file__).resolve().parents[1]
        with root.joinpath("pyproject.toml").open("rb") as fh:
            data = tomllib.load(fh)
        return str(data["project"]["version"])


__version__ = _version()
