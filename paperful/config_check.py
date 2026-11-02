"""Validate config.toml keys and secret placement."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .config import _candidate_paths

# Top-level keys read by ``Config._from_dict`` (keep in sync when adding fields).
KNOWN_TOP_LEVEL = frozenset(
    {
        "email",
        "manager",
        "out_dir",
        "state_dir",
        "sources",
        "scihub_mirrors",
        "delay_serial_s",
        "delay_scihub_s",
        "concurrency_oa",
        "min_pdf_bytes",
        "gate_short_pdfs",
        "short_pdf_min_words",
        "crossref_min_score",
        "doi_suspect_score",
        "verify_doi",
        "core_api_key",
        "attach",
        "app_name",
        "mirror_failures_before_skip",
        "source_routing",
        "circuit_breaker_threshold",
        "user_agent",
        "ezproxy_base",
        "ezproxy_relogin",
        "ezproxy_cookies",
        "scholar_cookies",
        "grey_playbooks_builtin",
        "grey_playbooks_dir",
        "grey_playbooks",
        "profiles",
    }
)

KNOWN_SECTIONS = frozenset(
    {
        "mirror",
        "extension",
        "zotero",
        "mendeley",
        "endnote",
        "fetch",
        "ui",
        "llm",
        "rag",
        "browser_agent",
        "camofox",
        "serpapi",
        "grobid",
        "openalex_store",
        "snowball",
        "authorwatch",
        "keepup",
        "inbox",
        "critique",
        "rewrite",
        "fix_metadata",
        "lint",
        "extract_sections",
        "remarks",
        "exclude",
        "twenty",
        "searxng",
        "network",
        "glossary",
    }
)

SECRET_TOP_KEYS = frozenset({"core_api_key"})
SECRET_SECTION_KEYS = frozenset(
    {
        ("mendeley", "client_secret"),
        ("serpapi", "api_key"),
        ("twenty", "api_key"),
        ("openalex_store", "api_key"),
    }
)


def load_raw(path: Path | None = None) -> tuple[Path | None, dict[str, Any]]:
    for candidate in _candidate_paths(path):
        if candidate.is_file():
            with candidate.open("rb") as fh:
                return candidate, tomllib.load(fh)
    return None, {}


def check_config(path: Path | None = None) -> list[str]:
    """Return human-readable problems (empty when OK)."""
    source, raw = load_raw(path)
    if source is None:
        return ["config.toml not found (copy config.minimal.toml or config.example.toml)"]
    issues: list[str] = []
    for key, val in raw.items():
        if isinstance(val, dict):
            if key == "profiles":
                continue
            if key not in KNOWN_SECTIONS:
                hint = difflib.get_close_matches(key, list(KNOWN_SECTIONS), n=1)
                suffix = f" (did you mean {hint[0]!r}?)" if hint else ""
                issues.append(f"unknown section {key!r}{suffix}")
            body = val
            for sk, sv in body.items():
                pair = (key, sk)
                if pair in SECRET_SECTION_KEYS and sv:
                    issues.append(
                        f"secret {key}.{sk} is set in config.toml; use environment variables instead"
                    )
        elif key not in KNOWN_TOP_LEVEL:
            hint = difflib.get_close_matches(key, list(KNOWN_TOP_LEVEL), n=1)
            suffix = f" (did you mean {hint[0]!r}?)" if hint else ""
            issues.append(f"unknown top-level key {key!r}{suffix}")
    if raw.get("core_api_key"):
        issues.append("core_api_key is set in config.toml; use CORE_API_KEY in the environment")
    return issues
