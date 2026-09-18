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


def in_docker() -> bool:
    """True when running inside a container (Compose image or similar)."""
    return Path("/.dockerenv").exists()


def remediation_text(
    check: Check, cfg: Config, *, docker: bool | None = None
) -> str | None:
    """Human steps to green a non-green check, or None if nothing actionable."""
    if check.status == "green":
        return None
    if docker is None:
        docker = in_docker()
    cfg_hint = str(cfg.config_path) if cfg.config_path else "config.toml"
    host = " on the host (not inside this container)" if docker else ""
    data_hint = (
        " Use the same PAPERFUL_DATA / state dir this container mounts."
        if docker
        else ""
    )

    if check.name == _ZOTERO_CHECK:
        return (
            f"1. Start Zotero{host}.\n"
            "2. Settings → Advanced → allow other apps to talk to Zotero (local API).\n"
            "3. Confirm :23119 is reachable, then continue."
        )
    if check.name == "Write API":
        return (
            "Zotero 7–9 is download-only here. Upgrade to Zotero 10+ for attach, "
            "fix-metadata --apply, and dedupe --apply, or keep fetching to disk."
        )
    if check.name == "email":
        return (
            f'Edit {cfg_hint}: set email = "you@example.org" '
            "(Unpaywall and polite-pool APIs need it), save, then continue."
        )
    if check.name in ("out_dir", "state_dir"):
        path = cfg.out_dir if check.name == "out_dir" else cfg.state_dir
        return (
            f"{check.name} is not writable at {path}.\n"
            "Fix ownership/permissions on the data dir"
            + (" (PAPERFUL_DATA mount)" if docker else "")
            + ", then continue."
        )
    if check.name == "EZProxy session":
        cmd = "uv run paperful session login ezproxy"
        return (
            f"Run{host}: {cmd}\n"
            f"(system Chrome/Edge when available — campus SSO).{data_hint}\n"
            "When the vault is saved, continue here to re-check."
        )
    if check.name == "Scholar session":
        cmd = "uv run paperful session login scholar"
        return (
            f"Run{host}: {cmd}\n"
            f"(system Chrome/Edge when available; solve CAPTCHA there)."
            f"{data_hint}\n"
            "When the vault is saved, continue here to re-check."
        )
    if check.name == "pdftotext":
        if docker:
            return (
                "This image should ship Poppler. Rebuild the image "
                "(docker compose build) or install poppler-utils in a custom image."
            )
        return (
            "Install Poppler so pdftotext is on PATH (e.g. brew install poppler / "
            "apt install poppler-utils). pypdf remains the fallback."
        )
    if check.name == "Playwright":
        if "missing" in check.detail:
            return (
                "Run: uv sync\n"
                "Then retry session login (Chromium downloads on first login)."
            )
        return (
            "Chromium is not installed yet. Run:\n"
            "  uv run paperful session login ezproxy\n"
            "(or: uv run playwright install chromium), then continue."
        )
    if check.name == "Docker paths":
        cfg_hint = str(cfg.config_path) if cfg.config_path else "config.toml"
        return (
            f"Edit {cfg_hint}: set out_dir = \"out\" and state_dir = \"state\" "
            "(relative to the config file / Compose /data mount). "
            "Avoid ~/… paths — they resolve to a different home inside the container."
        )
    if check.name == "Grey playbooks":
        return (
            f"Builtin grey-lit packs are incomplete. Check {cfg_hint} "
            "(grey_playbooks_builtin / grey_playbooks_dir) or update paperful."
        )
    return None


def actionable_checks(
    checks: list[Check], cfg: Config, *, docker: bool | None = None
) -> list[tuple[Check, str]]:
    """Non-green checks that have remediation text, in doctor order."""
    if docker is None:
        docker = in_docker()
    out: list[tuple[Check, str]] = []
    for ch in checks:
        text = remediation_text(ch, cfg, docker=docker)
        if text:
            out.append((ch, text))
    return out


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
                Check(
                    _ZOTERO_CHECK, "green", f"reachable at {zot_where} (Zotero {ver})"
                )
            )
        except ConnectionError as exc:
            checks.append(Check(_ZOTERO_CHECK, "red", f"{zot_where}: {exc}"))
        except Exception as exc:
            checks.append(
                Check(_ZOTERO_CHECK, "red", f"{zot_where} unreachable: {exc}")
            )

    if info is not None:
        if info.get("supports_write"):
            checks.append(Check("Write API", "green", "yes (Zotero 10+)"))
        else:
            checks.append(
                Check(
                    "Write API",
                    "amber",
                    "no — attach, fix-metadata --apply, and dedupe --apply need Zotero 10+",
                )
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

    docker_paths = _docker_paths_check(cfg)
    if docker_paths is not None:
        checks.append(docker_paths)

    checks.append(_playwright_check())

    cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    vault = cfg.state_dir / "sessions" / "cookies.txt"
    meta = cfg.state_dir / "sessions" / "meta.json"
    if cfg.ezproxy_base:
        if cookie_path.is_file() or vault.is_file() or meta.is_file():
            where = str(
                meta if meta.is_file() else (vault if vault.is_file() else cookie_path)
            )
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
            where = str(
                meta if meta.is_file() else (vault if vault.is_file() else scholar_path)
            )
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


def _playwright_check() -> Check:
    from . import session as sess

    if not sess.playwright_available():
        return Check(
            "Playwright",
            "amber",
            "missing — run: uv sync (needed for session login / htmlpdf)",
        )
    if sess.chromium_installed():
        return Check("Playwright", "green", "package + Chromium ready")
    return Check(
        "Playwright",
        "amber",
        "package ok — Chromium installs on first session login "
        "(or: uv run playwright install chromium)",
    )


def _docker_paths_check(cfg: Config) -> Check | None:
    """Warn when ~/… paths resolve outside the Compose /data mount."""
    if not in_docker():
        return None
    data = Path("/data")
    if not data.is_dir():
        return None
    data = data.resolve()
    bad: list[str] = []
    for label, path in (("out_dir", cfg.out_dir), ("state_dir", cfg.state_dir)):
        try:
            path.resolve().relative_to(data)
        except ValueError:
            bad.append(f"{label}={path}")
    if not bad:
        return Check("Docker paths", "green", "out_dir/state_dir under /data")
    return Check(
        "Docker paths",
        "amber",
        "outside /data ("
        + ", ".join(bad)
        + ") — set out_dir/state_dir to relative paths (out / state) so host "
        "session login and the container share the mount",
    )


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
