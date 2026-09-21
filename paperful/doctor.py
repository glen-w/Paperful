"""Environment checks for first-run and operator diagnostics."""

from __future__ import annotations

import re
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
_MENDELEY_CHECK = "Mendeley API"
_ENDNOTE_CHECK = "EndNote library"
_LIBRARY_CHECKS = {_ZOTERO_CHECK, _MENDELEY_CHECK, _ENDNOTE_CHECK}


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
    if check.name == _MENDELEY_CHECK:
        return (
            "1. Register an app at https://dev.mendeley.com/myapps.html "
            "(redirect http://127.0.0.1:8765/callback, Authorization code flow).\n"
            "2. Set [mendeley] client_id / client_secret (or PAPERFUL_MENDELEY_CLIENT_*).\n"
            "3. Run: paperful session login mendeley"
        )
    if check.name == _ENDNOTE_CHECK:
        return (
            "Set [endnote] library = \"/path/to/Library.enl\". The matching "
            ".Data folder (with sdb/sdb.eni and PDF/) must sit beside it. "
            "If EndNote is open and the database is locked, close it or let "
            "paperful copy the file."
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
    if check.name == "LLM":
        return (
            f"Edit {cfg_hint} [llm]: start Ollama (ollama serve) and pull the model "
            "(ollama pull <model>), or set provider = \"litellm\" after "
            "`uv sync --extra llm` with keys in the environment. Then continue."
        )
    if check.name == "browser-agent extra":
        if "not installed" in check.detail:
            return (
                "Run: uv sync --extra browser-agent (Python 3.11+), "
                "then `paperful session login scholar` before `run` / `recover`."
            )
        return (
            f"Edit {cfg_hint} [browser_agent]: model = \"<14b+ tag>\" "
            "(small models loop on publisher pages), then continue."
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
    if check.name == "Mirror":
        return (
            "Flat PDFs are still beside collection folders. Run "
            "`paperful snapshot -C …` (or `--library`) to move them into "
            "item folders. `[mirror].pdfs` is additional, all, or none."
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
    manager = (cfg.manager or "zotero").strip().lower()
    if manager == "mendeley":
        checks.append(_mendeley_library_check(cfg))
    elif manager == "endnote":
        checks.append(_endnote_library_check(cfg))
    else:
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

    checks.append(_mirror_check(cfg))
    checks.append(_playwright_check())

    cookie_path = cfg.ezproxy_cookie_path
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

    scholar_path = cfg.scholar_cookie_path
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
    checks.extend(_llm_checks(cfg))

    return checks


_PARAM_SIZE = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)b\b", re.I)
_AGENT_FLOOR_B = 10.0


def _mirror_check(cfg: Config) -> Check:
    from .snapshot import count_layout

    flat, item_dirs = count_layout(cfg.out_dir)
    detail = f"pdfs={cfg.mirror_pdfs}"
    if flat and item_dirs:
        return Check(
            "Mirror",
            "amber",
            f"{detail}; {flat} flat PDF(s) outside item folders — run snapshot",
        )
    if item_dirs:
        return Check("Mirror", "green", f"{detail}; {item_dirs} item folder(s)")
    if flat:
        return Check("Mirror", "green", f"{detail}; {flat} flat PDF(s)")
    return Check("Mirror", "green", detail)


def _model_below_agent_floor(model: str) -> bool:
    """Name-pattern only (no probe): flag tags under ~10B params for the browsing agent."""
    m = _PARAM_SIZE.search(model)
    if not m:
        return False
    return float(m.group(1)) < _AGENT_FLOOR_B


def _llm_checks(cfg) -> list[Check]:
    from .browser_agent import browser_agent_extra_available
    from .llm.preflight import validate_llm_for_verb
    from .llm.validate import LlmConfigError

    if not cfg.llm_enabled:
        return [Check("LLM", "green", "disabled (llm.enabled false)")]
    out: list[Check] = []
    try:
        model = validate_llm_for_verb(cfg)
        out.append(
            Check(
                "LLM",
                "green",
                f"{cfg.llm_provider} · {model} — ok · num_ctx≤{cfg.llm_max_num_ctx}",
            )
        )
    except LlmConfigError as exc:
        out.append(Check("LLM", "amber", str(exc)))
    except Exception as exc:  # unreachable daemon etc.
        out.append(Check("LLM", "amber", f"{type(exc).__name__}: {exc}"))
    if browser_agent_extra_available():
        agent_model = (cfg.browser_agent_model or cfg.llm_model).strip()
        if _model_below_agent_floor(agent_model):
            out.append(
                Check(
                    "browser-agent extra",
                    "amber",
                    f"browser-use ok; {agent_model!r} is small for browsing — "
                    "set [browser_agent].model to a 14b+ class model",
                )
            )
        else:
            out.append(Check("browser-agent extra", "green", "browser-use importable"))
    else:
        out.append(
            Check(
                "browser-agent extra",
                "amber",
                "not installed — uv sync --extra browser-agent (Python 3.11+)",
            )
        )
    return out


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


def _mendeley_library_check(cfg: Config) -> Check:
    from .mendeley import MendeleyAuthError, MendeleyClient, client_id_of, client_secret_of, token_path

    if not client_id_of(cfg) or not client_secret_of(cfg):
        return Check(
            _MENDELEY_CHECK,
            "red",
            "missing client_id / client_secret — register at dev.mendeley.com/myapps.html",
        )
    if not token_path(cfg).is_file():
        return Check(
            _MENDELEY_CHECK,
            "amber",
            "app registered — run: paperful session login mendeley",
        )
    try:
        info = MendeleyClient(cfg).ping()
    except MendeleyAuthError as exc:
        return Check(_MENDELEY_CHECK, "amber", str(exc))
    except Exception as exc:
        return Check(_MENDELEY_CHECK, "red", f"{type(exc).__name__}: {exc}")
    who = info.get("display_name") or "?"
    return Check(_MENDELEY_CHECK, "green", f"authorised as {who}")


def _endnote_library_check(cfg: Config) -> Check:
    from .endnote import connect_readonly, library_paths

    if not cfg.endnote_library:
        return Check(
            _ENDNOTE_CHECK,
            "red",
            "set [endnote] library to your .enl file",
        )
    try:
        enl, data, eni = library_paths(Path(cfg.endnote_library))
    except Exception as exc:
        return Check(_ENDNOTE_CHECK, "red", str(exc))
    if not eni.is_file():
        return Check(
            _ENDNOTE_CHECK,
            "red",
            f"no sdb.eni at {eni} (need {enl.name} + matching .Data folder)",
        )
    try:
        conn = connect_readonly(eni)
        tables = {
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        n = 0
        if "refs" in tables:
            n = int(conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0])
        conn.close()
    except Exception as exc:
        return Check(_ENDNOTE_CHECK, "amber", f"readable copy failed: {exc}")
    pdfs = data / "PDF"
    pdf_note = "PDF/" if pdfs.is_dir() else "no PDF/ folder"
    return Check(_ENDNOTE_CHECK, "green", f"{enl.name} ({n} refs, {pdf_note})")


def has_red(checks: list[Check]) -> bool:
    fatal = _LIBRARY_CHECKS | {"out_dir", "state_dir"}
    return any(c.status == "red" and c.name in fatal for c in checks)
