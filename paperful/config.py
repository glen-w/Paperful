"""Configuration loading for paperful."""

from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .playbooks import (
    GreyPlaybook,
    load_pack_dir,
    merge_playbooks,
    playbook_from_dict,
)

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
    "core",
    "scholar",
    "direct",
    "ezproxy",
    "htmlpdf",
]
# Open access + campus EZProxy only (no Scholar, no Sci-Hub) — suitable for EOI / policy-sensitive runs.
EOI_SOURCES = [
    "unpaywall",
    "openalex",
    "arxiv",
    "biorxiv",
    "europepmc",
    "semanticscholar",
    "core",
    "direct",
    "ezproxy",
    "htmlpdf",
]
SOURCE_PRESETS: dict[str, list[str]] = {"eoi": EOI_SOURCES}
KNOWN_MANAGERS = ("zotero", "mendeley")
DEFAULT_MIRRORS = [
    "sci-hub.ru",
    "sci-hub.ren",
    "sci-hub.box",
    "sci-hub.se",
    "sci-hub.st",
]
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
    manager: str = "zotero"
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    scihub_mirrors: list[str] = field(default_factory=lambda: list(DEFAULT_MIRRORS))
    delay_scihub_s: tuple[float, float] = (3.0, 8.0)
    concurrency_oa: int = 4
    min_pdf_bytes: int = 10_000
    crossref_min_score: float = 0.90
    doi_suspect_score: float = 0.70
    verify_doi: bool = True
    core_api_key: str = ""
    attach: bool = True
    app_name: str = "paperful"
    mirror_failures_before_skip: int = 3
    source_routing: bool = (
        True  # skip sources that look inapplicable from item metadata
    )
    circuit_breaker_threshold: int = (
        3  # block-like failures before skipping a source for the run
    )
    user_agent: str = USER_AGENT
    # Campus EZProxy (e.g. Sciences Po). Empty base disables the source.
    ezproxy_base: str = ""
    ezproxy_cookies: Path | None = (
        None  # Netscape cookies.txt; default state/ezproxy-cookies.txt
    )
    scholar_cookies: Path | None = (
        None  # Netscape cookies.txt; default state/scholar-cookies.txt
    )
    # Grey-lit PDF playbooks: builtin ocean/gov pack + optional dir packs + [[grey_playbooks]].
    grey_playbooks_builtin: bool = True
    grey_playbooks_dir: Path | None = None
    grey_playbooks: list[GreyPlaybook] = field(default_factory=list)
    config_path: Path | None = None

    def __post_init__(self) -> None:
        # Resolve pack+user once so Config() in tests gets the builtin examples.
        if not self.grey_playbooks and self.grey_playbooks_builtin:
            self.grey_playbooks = merge_playbooks(True, ())

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.jsonl"

    @property
    def patches_path(self) -> Path:
        return self.state_dir / "metadata-patches.jsonl"

    @property
    def pdf_cache_dir(self) -> Path:
        return self.state_dir / "pdf-cache"

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
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "paperful"
        / "config.toml",
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
    if "manager" in raw:
        cfg.manager = str(raw["manager"]).strip().lower() or "zotero"
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
    if "doi_suspect_score" in raw:
        cfg.doi_suspect_score = float(raw["doi_suspect_score"])
    if "verify_doi" in raw:
        cfg.verify_doi = bool(raw["verify_doi"])
    if "core_api_key" in raw:
        cfg.core_api_key = str(raw["core_api_key"]).strip()
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
    if "grey_playbooks_builtin" in raw:
        cfg.grey_playbooks_builtin = bool(raw["grey_playbooks_builtin"])
    if "grey_playbooks_dir" in raw and raw["grey_playbooks_dir"]:
        cfg.grey_playbooks_dir = Path(str(raw["grey_playbooks_dir"])).expanduser()
    user_playbooks: list[GreyPlaybook] = []
    for i, row in enumerate(raw.get("grey_playbooks") or []):
        if not isinstance(row, dict):
            warnings.warn(
                f"config grey_playbooks[{i}] ignored: expected a table, got {type(row).__name__}",
                UserWarning,
                stacklevel=2,
            )
            continue
        pb = playbook_from_dict(row)
        if pb:
            user_playbooks.append(pb)
        else:
            name = row.get("name", "?")
            kind = row.get("kind", "?")
            warnings.warn(
                f"config grey_playbooks entry {name!r} (kind={kind!r}) ignored: "
                "need name and kind in {{rewrite, scrape, synthesize}}",
                UserWarning,
                stacklevel=2,
            )
    if not cfg.out_dir.is_absolute():
        cfg.out_dir = (source.parent / cfg.out_dir).resolve()
    if not cfg.state_dir.is_absolute():
        cfg.state_dir = (source.parent / cfg.state_dir).resolve()
    if cfg.grey_playbooks_dir is not None and not cfg.grey_playbooks_dir.is_absolute():
        cfg.grey_playbooks_dir = (source.parent / cfg.grey_playbooks_dir).resolve()
    if cfg.ezproxy_cookies is None:
        cfg.ezproxy_cookies = cfg.state_dir / "ezproxy-cookies.txt"
    elif not cfg.ezproxy_cookies.is_absolute():
        cfg.ezproxy_cookies = (source.parent / cfg.ezproxy_cookies).resolve()
    if cfg.scholar_cookies is None:
        cfg.scholar_cookies = cfg.state_dir / "scholar-cookies.txt"
    elif not cfg.scholar_cookies.is_absolute():
        cfg.scholar_cookies = (source.parent / cfg.scholar_cookies).resolve()
    # Builtin → dir packs → inline [[grey_playbooks]]; same name wins later.
    extra = (
        load_pack_dir(cfg.grey_playbooks_dir)
        if cfg.grey_playbooks_dir is not None
        else []
    )
    cfg.grey_playbooks = merge_playbooks(
        cfg.grey_playbooks_builtin, user_playbooks, extra=extra
    )
    return cfg
