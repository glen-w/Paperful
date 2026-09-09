"""Configuration loading for paperful."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Sci-Hub is opt-in (legal grey zone in some jurisdictions). Add "scihub" to
# `sources` or pass --scihub; it is not in the default list.
DEFAULT_SOURCES = [
    "unpaywall",
    "openalex",
    "arxiv",
    "biorxiv",
    "europepmc",
    "semanticscholar",
    "scholar",
    "direct",
    "ezproxy",
]
DEFAULT_MIRRORS = ["sci-hub.ru", "sci-hub.ren", "sci-hub.box", "sci-hub.se", "sci-hub.st"]
SCIHUB_DISCLAIMER = (
    "Sci-Hub occupies a legal grey zone in some jurisdictions. "
    "You are responsible for complying with the laws that apply to you."
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class Config:
    email: str = ""
    out_dir: Path = Path("out")
    state_dir: Path = Path("state")
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    scihub_mirrors: list[str] = field(default_factory=lambda: list(DEFAULT_MIRRORS))
    delay_scihub_s: tuple[float, float] = (3.0, 8.0)
    concurrency_oa: int = 4
    min_pdf_bytes: int = 10_000
    crossref_min_score: float = 0.90
    attach: bool = True
    app_name: str = "paperful"
    mirror_failures_before_skip: int = 3
    source_routing: bool = True  # skip sources that look inapplicable from item metadata
    circuit_breaker_threshold: int = 3  # block-like failures before skipping a source for the run
    user_agent: str = USER_AGENT
    # Campus EZProxy (e.g. Sciences Po). Empty base disables the source.
    ezproxy_base: str = ""
    ezproxy_cookies: Path | None = None  # Netscape cookies.txt; default state/ezproxy-cookies.txt
    scholar_cookies: Path | None = None  # Netscape cookies.txt; default state/scholar-cookies.txt
    config_path: Path | None = None

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.jsonl"

    @property
    def local_key_path(self) -> Path:
        return self.state_dir / "zotero-local-api-key.json"


def _candidate_paths(explicit: Path | None) -> list[Path]:
    if explicit:
        return [explicit]
    here = Path(__file__).resolve().parent.parent
    return [
        Path.cwd() / "config.toml",
        here / "config.toml",
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "paperful" / "config.toml",
    ]


def load_config(path: Path | None = None) -> Config:
    """Load config.toml from an explicit path or the usual locations; defaults otherwise."""
    for candidate in _candidate_paths(path):
        if candidate.is_file():
            with candidate.open("rb") as fh:
                raw: dict[str, Any] = tomllib.load(fh)
            return _from_dict(raw, candidate)
    if path is not None:
        raise FileNotFoundError(path)
    return Config()


def _from_dict(raw: dict[str, Any], source: Path) -> Config:
    cfg = Config(config_path=source)
    if "email" in raw:
        cfg.email = str(raw["email"])
    if "out_dir" in raw:
        cfg.out_dir = Path(str(raw["out_dir"])).expanduser()
    if "state_dir" in raw:
        cfg.state_dir = Path(str(raw["state_dir"])).expanduser()
    if "sources" in raw:
        cfg.sources = [str(s) for s in raw["sources"]]
    if "scihub_mirrors" in raw:
        cfg.scihub_mirrors = [str(m) for m in raw["scihub_mirrors"]]
    if "delay_scihub_s" in raw:
        lo, hi = raw["delay_scihub_s"]
        cfg.delay_scihub_s = (float(lo), float(hi))
    if "concurrency_oa" in raw:
        cfg.concurrency_oa = max(1, int(raw["concurrency_oa"]))
    if "min_pdf_bytes" in raw:
        cfg.min_pdf_bytes = int(raw["min_pdf_bytes"])
    if "crossref_min_score" in raw:
        cfg.crossref_min_score = float(raw["crossref_min_score"])
    if "attach" in raw:
        cfg.attach = bool(raw["attach"])
    if "app_name" in raw:
        cfg.app_name = str(raw["app_name"])
    if "mirror_failures_before_skip" in raw:
        cfg.mirror_failures_before_skip = int(raw["mirror_failures_before_skip"])
    if "source_routing" in raw:
        cfg.source_routing = bool(raw["source_routing"])
    if "circuit_breaker_threshold" in raw:
        cfg.circuit_breaker_threshold = max(1, int(raw["circuit_breaker_threshold"]))
    if "user_agent" in raw:
        cfg.user_agent = str(raw["user_agent"])
    if "ezproxy_base" in raw:
        cfg.ezproxy_base = str(raw["ezproxy_base"]).strip()
    if "ezproxy_cookies" in raw and raw["ezproxy_cookies"]:
        cfg.ezproxy_cookies = Path(str(raw["ezproxy_cookies"])).expanduser()
    if "scholar_cookies" in raw and raw["scholar_cookies"]:
        cfg.scholar_cookies = Path(str(raw["scholar_cookies"])).expanduser()
    if not cfg.out_dir.is_absolute():
        cfg.out_dir = (source.parent / cfg.out_dir).resolve()
    if not cfg.state_dir.is_absolute():
        cfg.state_dir = (source.parent / cfg.state_dir).resolve()
    if cfg.ezproxy_cookies is None:
        cfg.ezproxy_cookies = cfg.state_dir / "ezproxy-cookies.txt"
    elif not cfg.ezproxy_cookies.is_absolute():
        cfg.ezproxy_cookies = (source.parent / cfg.ezproxy_cookies).resolve()
    if cfg.scholar_cookies is None:
        cfg.scholar_cookies = cfg.state_dir / "scholar-cookies.txt"
    elif not cfg.scholar_cookies.is_absolute():
        cfg.scholar_cookies = (source.parent / cfg.scholar_cookies).resolve()
    return cfg
