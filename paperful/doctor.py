"""Environment checks for first-run and operator diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .config import Config

if TYPE_CHECKING:
    from .zot import ZoteroLocal

Status = str  # green | amber | red


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


def run_checks(cfg: Config, zl: ZoteroLocal | None, ping: Callable[[], dict] | None = None) -> list[Check]:
    checks: list[Check] = []
    info: dict | None = None
    if zl is None:
        checks.append(Check("Zotero :23119", "red", "not checked"))
    else:
        try:
            info = ping() if ping else zl.ping()
            ver = info.get("zotero_version") or "?"
            checks.append(Check("Zotero :23119", "green", f"reachable (Zotero {ver})"))
        except ConnectionError as exc:
            checks.append(Check("Zotero :23119", "red", str(exc)))
        except Exception as exc:
            checks.append(Check("Zotero :23119", "red", f"unreachable: {exc}"))

    if info is not None:
        if info.get("supports_write"):
            checks.append(Check("Write API", "green", "yes (Zotero 10+)"))
        else:
            checks.append(Check("Write API", "amber", "no — download-only until Zotero 10+"))

    if cfg.email.strip():
        checks.append(Check("email", "green", cfg.email))
    else:
        checks.append(Check("email", "amber", "empty — Unpaywall and polite-pool APIs need an email"))

    for label, path in (("out_dir", cfg.out_dir), ("state_dir", cfg.state_dir)):
        if _writable(path):
            checks.append(Check(label, "green", str(path)))
        else:
            checks.append(Check(label, "red", f"not writable: {path}"))

    cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    if cfg.ezproxy_base:
        if cookie_path.is_file():
            checks.append(Check("EZProxy cookies", "green", str(cookie_path)))
        else:
            checks.append(Check("EZProxy cookies", "amber", f"missing — run: paperful ezproxy ({cookie_path})"))
    else:
        checks.append(Check("EZProxy", "green", "disabled (ezproxy_base empty)"))

    scholar_path = cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt")
    if "scholar" in cfg.sources:
        if scholar_path.is_file():
            checks.append(Check("Scholar cookies", "green", str(scholar_path)))
        else:
            checks.append(Check("Scholar cookies", "amber", f"missing — run: paperful scholar ({scholar_path})"))
    else:
        checks.append(Check("Scholar", "green", "not in sources"))

    return checks


def has_red(checks: list[Check]) -> bool:
    fatal = {"Zotero :23119", "out_dir", "state_dir"}
    return any(c.status == "red" and c.name in fatal for c in checks)
