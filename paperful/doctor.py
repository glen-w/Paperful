"""Environment checks for first-run and operator diagnostics."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Config
from .zot import zotero_local_label

if TYPE_CHECKING:
    from .zot import ZoteroLocal

Status = str  # green | amber | red
_ZOTERO_CHECK = "Zotero :23119"


@dataclass
class Check:
    name: str
    status: Status
    detail: str


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".paperful-write-test"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


def run_checks(
    cfg: Config, zl: ZoteroLocal | None, ping: Callable[[], dict] | None = None
) -> list[Check]:
    checks: list[Check] = []
    info: dict | None = None
    zot_where = zotero_local_label()
    if zl is None:
        checks.append(Check(_ZOTERO_CHECK, "red", f"not checked ({zot_where})"))
    else:
        try:
            info = ping() if ping else zl.ping()
            ver = info.get("zotero_version") or "?"
            checks.append(
                Check(_ZOTERO_CHECK, "green", f"reachable at {zot_where} (Zotero {ver})")
            )
        except ConnectionError as exc:
            checks.append(Check(_ZOTERO_CHECK, "red", f"{zot_where}: {exc}"))
        except Exception as exc:
            checks.append(Check(_ZOTERO_CHECK, "red", f"{zot_where} unreachable: {exc}"))

    if info is not None:
        if info.get("supports_write"):
            checks.append(Check("Write API", "green", "yes (Zotero 10+)"))
        else:
            checks.append(
                Check("Write API", "amber", "no — download-only until Zotero 10+")
            )

    if cfg.email.strip():
        checks.append(Check("email", "green", cfg.email))
    else:
        checks.append(
            Check(
                "email", "amber", "empty — Unpaywall and polite-pool APIs need an email"
            )
        )

    for label, path in (("out_dir", cfg.out_dir), ("state_dir", cfg.state_dir)):
        if _writable(path):
            checks.append(Check(label, "green", str(path)))
        else:
            checks.append(Check(label, "red", f"not writable: {path}"))

    cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    vault = cfg.state_dir / "sessions" / "cookies.txt"
    meta = cfg.state_dir / "sessions" / "meta.json"
    if cfg.ezproxy_base:
        if cookie_path.is_file() or vault.is_file() or meta.is_file():
            where = str(meta if meta.is_file() else (vault if vault.is_file() else cookie_path))
            checks.append(Check("EZProxy session", "green", where))
        else:
            checks.append(
                Check(
                    "EZProxy session",
                    "amber",
                    f"missing — run: paperful session login ezproxy ({cookie_path})",
                )
            )
    else:
        checks.append(Check("EZProxy", "green", "disabled (ezproxy_base empty)"))

    scholar_path = cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt")
    if "scholar" in cfg.sources:
        if scholar_path.is_file() or vault.is_file() or meta.is_file():
            where = str(meta if meta.is_file() else (vault if vault.is_file() else scholar_path))
            checks.append(Check("Scholar session", "green", where))
        else:
            checks.append(
                Check(
                    "Scholar session",
                    "amber",
                    f"missing — run: paperful session login scholar ({scholar_path})",
                )
            )
    else:
        checks.append(Check("Scholar", "green", "not in sources"))

    if shutil.which("pdftotext"):
        checks.append(Check("pdftotext", "green", "on PATH"))
    else:
        checks.append(
            Check(
                "pdftotext",
                "amber",
                "missing — install poppler for PDF DOI extraction; pypdf is fallback",
            )
        )

    checks.append(_grey_playbooks_check(cfg))

    return checks


_NAMED_GREY_PACKS = (
    "undocs-unga-vme",
    "bbnj-doalos-prepcom",
    "isa-deepdata",
)


def _grey_playbooks_check(cfg: Config) -> Check:
    """Builtin ocean packs present, or user-only / disabled."""
    names = {p.name for p in cfg.grey_playbooks}
    present = [n for n in _NAMED_GREY_PACKS if n in names]
    pack_note = ""
    if cfg.grey_playbooks_dir is not None:
        pack_note = f"; packs dir {cfg.grey_playbooks_dir}"
    if cfg.grey_playbooks_builtin:
        if len(present) == len(_NAMED_GREY_PACKS):
            return Check(
                "Grey playbooks",
                "green",
                f"UNGA/undocs · BBNJ/DOALOS · ISA{pack_note}",
            )
        missing = [n for n in _NAMED_GREY_PACKS if n not in names]
        return Check(
            "Grey playbooks",
            "amber",
            f"builtin on but missing pack entries: {', '.join(missing)}{pack_note}",
        )
    if cfg.grey_playbooks:
        return Check(
            "Grey playbooks",
            "green",
            f"builtin off — {len(cfg.grey_playbooks)} rule(s){pack_note}",
        )
    return Check("Grey playbooks", "green", f"builtin off — no rules{pack_note}")


def has_red(checks: list[Check]) -> bool:
    fatal = {_ZOTERO_CHECK, "out_dir", "state_dir"}
    return any(c.status == "red" and c.name in fatal for c in checks)
