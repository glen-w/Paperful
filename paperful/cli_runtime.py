"""Shared CLI runtime: connect, scope, progress, agent emit.

Typer commands live in ``cli.py`` and re-export these names. Command modules
import this package as ``cli_mod`` so they never import ``cli``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .progress import Track, item_progress, tracker
from .config import (
    CAMOFOX_DISCLAIMER,
    KNOWN_MANAGERS,
    RECOVER_DISCLAIMER,
    SCIHUB_DISCLAIMER,
    SOURCE_PRESETS,
    Config,
    load_config,
)
from .catalogue import MirrorCatalogue, MirrorFirstBackend, open_library
from .library import LibraryBackend, LibraryError, get_backend, mirrored
from .pipeline import Pipeline, RunStats
from .run_config import ResolvedRunConfig, RunConfigError, resolve_run_config
from .runreport import build_report, print_run_summary, write_run_report
from .run_hooks import (
    ezproxy_headed_login_and_probe,
    ensure_ezproxy_session,
    inbox_handoff_session,
    maybe_ezproxy_relogin,
    mid_run_ezproxy_hook,
    preflight_ezproxy_session,
    run_session_handoff,
)
from .scope import ScopeError, filter_scope_items, load_scope, resolve_keys
from .store import Manifest
from .zot import ZoteroLocal, resolve_item_types

console = Console(highlight=False)

def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()

def _bind_run(cfg: Config, **kwargs: Any) -> ResolvedRunConfig:
    try:
        return resolve_run_config(cfg, **kwargs)
    except RunConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

def _scope_unset(
    collection: list[str],
    library: bool | None,
    profile: str | None,
    run_config: Path | None,
) -> bool:
    return not profile and run_config is None and not collection and library is None

def _refuse_missing_scope() -> None:
    console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
    raise typer.Exit(1)

def _inbox_library_when_unscoped(
    collection: list[str],
    library: bool | None,
    profile: str | None,
    run_config: Path | None,
) -> bool | None:
    """Shared drop folder: default to whole-library DOI match when scope is omitted."""
    if _scope_unset(collection, library, profile, run_config):
        return True
    return library

def _take_scope(
    bound: ResolvedRunConfig,
) -> tuple[list[str], bool, int | None, int | None, list[str]]:
    return (
        bound.collections,
        bound.library,
        bound.year_from,
        bound.year_to,
        bound.types,
    )

def _item_progress(*, json_out: bool = False, transient: bool = False):
    """Live bar that stays below scrolling per-item logs.

    ``json_out`` keeps stdout pure: the bar moves to stderr, and only on a
    terminal — except live E2E (``PAPERFUL_E2E=1``), which babysits over a pipe
    and still wants progress on stderr.
    """
    live = Console(stderr=True, highlight=False) if json_out else console
    e2e = os.environ.get("PAPERFUL_E2E") == "1"
    # Off a terminal a spinner has nothing to show, and JSON runs stay quiet.
    quiet = (json_out or transient) and not live.is_terminal and not e2e
    return item_progress(live, disable=quiet, transient=transient)

def _track(progress, description: str) -> Track:
    return tracker(progress, description)

@contextmanager
def _spinner(
    text: str, *, json_out: bool = False
) -> Iterator[Callable[[str], None]]:
    """Spinner and clock for one slow call that has no item count.

    Yields a function that replaces the text. The line clears when done.
    """
    with _item_progress(json_out=json_out, transient=True) as progress:
        task_id = progress.add_task(text, total=None)
        yield lambda msg: progress.update(task_id, description=msg)

def _load_scope(backend: LibraryBackend, *, json_out: bool = False, **scope: Any):
    """``_loaded_scope`` behind a spinner that shows the loader's own status."""
    with _spinner("Connecting to library scope…", json_out=json_out) as say:
        return _loaded_scope(backend, status=say, **scope)

def _cfg(path: Path | None) -> Config:
    try:
        cfg = load_config(path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg

def _typer_opt(value: Any, default: Any = None) -> Any:
    """Unwrap Typer OptionInfo/ArgumentInfo when a command is called as a function.

    ``paperful all`` dispatches verbs via ``_call_step``; omitted options then
    arrive as OptionInfo objects instead of their Python defaults.
    """
    from typer.models import ArgumentInfo, OptionInfo

    if isinstance(value, (OptionInfo, ArgumentInfo)):
        raw = value.default
        if raw is ... or isinstance(raw, (OptionInfo, ArgumentInfo)):
            return default
        return raw
    return value

def _typer_enum_value(value: Any) -> str | None:
    """``Enum.value`` after ``_typer_opt``, or None."""
    value = _typer_opt(value)
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)

def _resolve_source_names(sources: str | None, preset: str | None) -> list[str] | None:
    """Return explicit source names from --sources or --preset, or None to use config."""
    if preset:
        key = preset.strip().lower()
        if key not in SOURCE_PRESETS:
            console.print(
                f"[red]Unknown preset '{preset}'.[/] Known: {', '.join(sorted(SOURCE_PRESETS))}"
            )
            raise typer.Exit(1)
        return list(SOURCE_PRESETS[key])
    if not sources:
        return None
    token = sources.strip().lower()
    if token in SOURCE_PRESETS:
        return list(SOURCE_PRESETS[token])
    return [s.strip() for s in sources.split(",") if s.strip()]

def _source_list(
    cfg: Config, sources: str | None, enable_scihub: bool, preset: str | None = None
) -> list[str]:
    """Configured order, optional --sources/--preset override, then optional --scihub append."""
    resolved = _resolve_source_names(sources, preset)
    listed = resolved if resolved is not None else list(cfg.sources)
    if enable_scihub and "scihub" not in listed:
        listed.append("scihub")
    return listed

def _zotero(*, quiet: bool = False) -> ZoteroLocal:
    zl = ZoteroLocal()
    try:
        info = zl.ping()
    except ConnectionError as exc:
        _exit_env(str(exc))
    except Exception as exc:  # Zotero not running
        from .zot import zotero_local_label

        _exit_env(f"Cannot reach Zotero local API at {zotero_local_label()}: {exc}")
    if not quiet:
        console.print(
            f"[dim]Zotero {info.get('zotero_version') or '?'}, local API v{info['api_version']}, write support: "
            f"{'yes' if info['supports_write'] else 'no (Zotero 10+ needed)'}[/]"
        )
    return zl

def _env_code(message: str) -> str:
    low = message.lower()
    if "no write support" in low or "needs zotero 10" in low:
        return "zotero_no_write"
    if "local api is disabled" in low or "allow other applications" in low:
        return "zotero_api_off"
    if "400" in low and "host" in low:
        return "zotero_bad_host"
    if any(
        token in low
        for token in ("nodename", "name or service not known", "name resolution")
    ):
        return "zotero_host_unresolved"
    if any(
        token in low
        for token in (
            "cannot reach",
            "connection refused",
            "unreachable",
            "timed out",
            "connect",
        )
    ):
        return "zotero_down"
    return ""

def _zotero_next_steps(code: str, *, in_doctor: bool) -> list[str]:
    host = os.environ.get("PAPERFUL_ZOTERO_HOST", "").strip()
    host_tip = (
        "Host Zotero must be running on this machine. The Host header is always "
        "localhost:23119; PAPERFUL_ZOTERO_HOST is only the TCP address. "
        "See docs/zotero.md."
    )
    if code == "zotero_api_off":
        steps = [
            "Settings → Advanced → enable “Allow other applications on this computer to communicate with Zotero”.",
            "See docs/zotero.md.",
        ]
    elif code == "zotero_no_write":
        steps = [
            "Attach needs Zotero 10+. This build can still download PDFs to out/.",
            "Upgrade, then run paperful attach. See docs/zotero.md.",
        ]
    elif code == "zotero_host_unresolved":
        configured = host or "the configured host"
        steps = [
            f"{configured} does not resolve on this machine. Unset PAPERFUL_ZOTERO_HOST when running outside Docker.",
            "The Host header is always localhost:23119. See docs/zotero.md.",
        ]
    elif code in {"zotero_down", "zotero_bad_host"}:
        steps = [
            "The local mirror does not need Zotero. This command reads the live library, which is not reachable.",
        ]
        if host or code == "zotero_bad_host":
            steps.append(host_tip)
        steps.append(
            "When you want this command to use the library, start Zotero and enable the local API."
        )
    else:
        steps = [
            "The local mirror does not need Zotero. This command reads the live library, which is not reachable.",
            "When you want this command to use the library, start Zotero and enable the local API.",
        ]
        if host:
            steps.append(host_tip)
    if not in_doctor and code != "zotero_no_write":
        steps.append("Run paperful doctor for a full check.")
    if code not in {"zotero_no_write", "zotero_api_off"}:
        steps.append(
            "If you have no config yet: cp config.example.toml config.toml and set email."
        )
    return steps

def _print_exit_ladder(
    cfg: Config | None = None, *, code: str = "", in_doctor: bool = False
) -> None:
    manager = (cfg.manager if cfg else "zotero") or "zotero"
    manager = manager.strip().lower()
    if manager == "mendeley":
        console.print(
            "\n[bold]Next steps[/]\n"
            "  1. Register an app at https://dev.mendeley.com/myapps.html\n"
            "     (redirect http://127.0.0.1:8765/callback).\n"
            "  2. Set [mendeley] client_id / client_secret in config.toml.\n"
            "  3. Run [bold]paperful session login mendeley[/].\n"
            "  4. Run [bold]paperful doctor[/].\n"
        )
        return
    if manager == "endnote":
        console.print(
            "\n[bold]Next steps[/]\n"
            '  1. Set [endnote] library = "/path/to/Library.enl".\n'
            "  2. Confirm the matching .Data folder (sdb/sdb.eni, PDF/) is beside it.\n"
            "  3. Run [bold]paperful doctor[/].\n"
        )
        return
    steps = _zotero_next_steps(code, in_doctor=in_doctor)
    body = "\n".join(f"  {i}. {step}" for i, step in enumerate(steps, start=1))
    console.print(f"\n[bold]Next steps[/]\n{body}\n")

def _exit_env(message: str, cfg: Config | None = None, *, code: str = "") -> None:
    console.print(f"[red]{message}[/]")
    _print_exit_ladder(cfg, code=code or _env_code(message))
    raise typer.Exit(2)

def _warn_if_scihub(source_list: list[str]) -> None:
    if "scihub" in source_list:
        console.print(f"[red]{SCIHUB_DISCLAIMER}[/]")

def _warn_if_recover(source_list: list[str]) -> None:
    if "browser_agent" in source_list:
        console.print(f"[orange3]{RECOVER_DISCLAIMER}[/]")

def _warn_if_camofox(source_list: list[str]) -> None:
    if "camofox" in source_list:
        console.print(f"[orange3]{CAMOFOX_DISCLAIMER}[/]")

def _require_manager(cfg: Config) -> None:
    manager = (cfg.manager or "zotero").strip().lower()
    if manager not in KNOWN_MANAGERS:
        console.print(
            f"[red]Unknown manager={manager!r}.[/] Known: zotero, mendeley, endnote."
        )
        raise typer.Exit(1)

def _manager_name(cfg: Config) -> str:
    return (cfg.manager or "zotero").strip().lower() or "zotero"

_OFFLINE = False

def _offline() -> bool:
    """``--offline`` or ``PAPERFUL_OFFLINE=1``: leave the manager alone."""
    return _OFFLINE or os.environ.get("PAPERFUL_OFFLINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

def _try_live(cfg: Config, *, quiet: bool = False) -> tuple[LibraryBackend | None, str]:
    """The manager itself, or (None, reason) when it is not reachable."""
    manager = _manager_name(cfg)
    try:
        if manager == "zotero":
            zl = ZoteroLocal()
            info = zl.ping()
            if not quiet:
                console.print(
                    f"[dim]Zotero {info.get('zotero_version') or '?'}, "
                    f"local API v{info.get('api_version')}, write support: "
                    f"{'yes' if info.get('supports_write') else 'no'}[/]"
                )
            return mirrored(cfg, get_backend(cfg, zl)), ""
        backend = mirrored(cfg, get_backend(cfg))
        info = backend.ping()
        if not quiet and manager == "mendeley":
            console.print(
                f"[dim]Mendeley {info.get('display_name') or '?'}, write support: yes[/]"
            )
        elif not quiet and manager == "endnote":
            console.print(
                f"[dim]EndNote {info.get('library') or '?'}, "
                f"{info.get('refs', '?')} refs, writes via import bundle[/]"
            )
        return backend, ""
    except Exception as exc:
        return None, str(exc)

def _mirror_first(cfg: Config, live: LibraryBackend, *, quiet: bool) -> LibraryBackend:
    """Refresh the mirror from ``live`` and read from it."""

    def say(msg: str) -> None:
        if not quiet:
            console.print(f"[dim]{msg}[/]")

    try:
        return open_library(cfg, live=live, status=say)
    except LibraryError as exc:
        _exit_env(str(exc), cfg)

def _open_library(cfg: Config, *, quiet: bool = False) -> tuple[LibraryBackend | None, str]:
    """The library, or (None, reason) when the manager is not reachable.

    A missing manager does not stop work that can stay on the local mirror.
    """
    if _offline():
        return None, "offline was asked for"
    live, reason = _try_live(cfg, quiet=quiet)
    if live is None:
        return None, reason
    return _mirror_first(cfg, live, quiet=quiet), ""

def _live_backend(cfg: Config, *, quiet: bool = False) -> LibraryBackend:
    """The manager itself, for verbs that compare it with the mirror. Exits 2 when it is down."""
    manager = (cfg.manager or "zotero").strip().lower()
    if _offline():
        _exit_env(f"This command reads {manager} directly and cannot run offline.", cfg)
    if manager == "zotero":
        zl = _zotero(quiet=quiet)
        return mirrored(cfg, get_backend(cfg, zl))
    try:
        backend = mirrored(cfg, get_backend(cfg))
        info = backend.ping()
    except LibraryError as exc:
        _exit_env(str(exc), cfg)
    except Exception as exc:
        _exit_env(f"Cannot reach {manager}: {exc}", cfg)
    if not quiet:
        if manager == "mendeley":
            who = info.get("display_name") or "?"
            console.print(f"[dim]Mendeley {who}, write support: yes[/]")
        elif manager == "endnote":
            console.print(
                f"[dim]EndNote {info.get('library') or '?'}, "
                f"{info.get('refs', '?')} refs, writes via import bundle[/]"
            )
    return backend

def _connect(cfg: Config, *, quiet: bool = False) -> LibraryBackend:
    """The library for a command: the mirror, refreshed when the manager answers.

    With the manager down and a mirror on disk, reads carry on from the mirror
    and writes are refused. With neither, exits 2.
    """
    catalogue = MirrorCatalogue(cfg.out_dir)
    if _offline():
        if not catalogue.usable():
            _exit_env("Offline, and there is no mirror under out/ to work from.", cfg)
        if not quiet:
            console.print(f"[dim]Offline. Working from {catalogue.age_line()}.[/]")
        return MirrorFirstBackend(cfg, catalogue, None)
    if not catalogue.usable():
        # Nothing on disk yet: the manager has to be there. Exits 2 with next steps.
        return _mirror_first(cfg, _live_backend(cfg, quiet=quiet), quiet=quiet)
    live, reason = _try_live(cfg, quiet=quiet)
    if live is None:
        if not quiet:
            console.print(
                f"[yellow]{_manager_name(cfg)} is not reachable ({reason}). "
                f"Working from {catalogue.age_line()}. Nothing will be written to it.[/]"
            )
        return MirrorFirstBackend(cfg, catalogue, None)
    return _mirror_first(cfg, live, quiet=quiet)

def _no_write(backend: LibraryBackend) -> str:
    if getattr(backend, "live", backend) is None:
        return "The library is not reachable, so nothing can be written to it."
    return "This library has no write support."

def _flush(backend: LibraryBackend) -> None:
    behind = getattr(backend, "unrefreshed", None)
    err = Console(stderr=True, highlight=False)
    if behind:
        err.print(
            f"[yellow]{len(behind)} item(s) changed in the library but not yet in "
            f"the mirror. paperful snapshot brings them in.[/]"
        )
    fn = getattr(backend, "flush_writes", None)
    if not callable(fn):
        return
    path = fn()
    if path is None:
        return
    err.print(f"[green]EndNote import bundle[/] {path}")
    err.print(
        "[dim]In EndNote: File → Import → File → paperful.xml "
        "(import option: EndNote Generated XML).[/]"
    )

def _scope_error(exc: ScopeError) -> None:
    console.print(f"[red]{exc}[/]")
    raise typer.Exit(1) from exc

def _scope_keys(
    backend: LibraryBackend, collection: list[str], library: bool
) -> tuple[list[str] | None, str]:
    try:
        return resolve_keys(backend, collection, library)
    except ScopeError as exc:
        _scope_error(exc)

def _resolve_types(item_type: list[str]) -> frozenset[str] | None:
    try:
        return resolve_item_types(item_type)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

def _apply_item_filters(
    items: list,
    scope: str,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
    label: bool = True,
) -> tuple[list, str]:
    """Filter by year and/or item type; optionally append labels to scope."""
    try:
        return filter_scope_items(
            items,
            scope,
            year_from=year_from,
            year_to=year_to,
            item_types=item_types,
            annotate=label,
        )
    except ScopeError as exc:
        _scope_error(exc)

def _loaded_scope(
    backend: LibraryBackend,
    *,
    collection: list[str],
    library: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    item_keys: list[str] | None = None,
    pdfs_only: bool = False,
    status: Callable[[str], None] | None = None,
):
    try:
        return load_scope(
            backend,
            item_keys=item_keys,
            collections=collection,
            library=library,
            year_from=year_from,
            year_to=year_to,
            item_types=_resolve_types(item_type),
            pdfs_only=pdfs_only,
            status=status,
        )
    except ScopeError as exc:
        _scope_error(exc)

def _opt_bool(flag: bool | None, configured: bool) -> bool:
    return configured if flag is None else flag

def _child_bytes(backend: Any, child: dict[str, Any]) -> bool:
    data = child.get("data") or {}
    key = str(child.get("key") or data.get("key") or "")
    if data.get("linkMode") == "linked_file":
        path = data.get("path")
        return bool(path) and Path(str(path)).is_file()
    probe = getattr(backend, "attachment_has_bytes", None)
    if probe is None or not key:
        return True
    try:
        return bool(probe(key))
    except Exception:
        return False

def _print_attachment_table(counts: dict[str, int]) -> None:
    table = Table(title="Attachments")
    table.add_column("Finding")
    table.add_column("Count", justify="right")
    order = (
        "ok",
        "ghost",
        "broken_link",
        "unrepairable",
        "duplicate_file",
        "cross_parent",
        "rename_drift",
        "stored",
    )
    shown = set()
    for kind in order:
        if kind in counts:
            table.add_row(kind, str(counts[kind]))
            shown.add(kind)
    for kind, count in sorted(counts.items()):
        if kind not in shown:
            table.add_row(kind, str(count))
    console.print(table)

def _print_version_table(proposals: list) -> None:
    if not proposals:
        console.print("[green]No preprint / published pairs.[/]")
        return
    table = Table(title=f"{len(proposals)} version pairs")
    table.add_column("Keep", style="dim")
    table.add_column("Published DOI")
    table.add_column("Sibling")
    table.add_column("Note")
    for row in proposals:
        note = "needs review" if row.needs_review else row.source
        table.add_row(
            row.item_key,
            row.published_doi,
            row.sibling_key or "-",
            note,
        )
    console.print(table)

def _print_dedupe_table(groups: list) -> None:
    if not groups:
        console.print("[green]No duplicate groups.[/]")
        return
    table = Table(title=f"{len(groups)} duplicate groups")
    table.add_column("Phase")
    table.add_column("Keep", style="dim")
    table.add_column("Merge")
    table.add_column("Note")
    for group in groups:
        if group.held:
            note = group.reason
            keep = "-"
            trash = "-"
        else:
            note = "needs review" if group.needs_review else group.reason
            keep = group.keep or "-"
            trash = ", ".join(group.trash)
        table.add_row(group.phase, keep, trash, note)
    console.print(table)

def _ezproxy_headed_login_and_probe(cfg: Config, pipe: Pipeline) -> bool:
    return ezproxy_headed_login_and_probe(console, cfg, pipe)

def _ensure_ezproxy_session(
    cfg: Config,
    pipe: Pipeline,
    *,
    enabled: bool,
    prompt: str,
) -> bool:
    return ensure_ezproxy_session(
        console, cfg, pipe, enabled=enabled, prompt=prompt
    )

def _preflight_ezproxy_session(
    cfg: Config,
    pipe: Pipeline,
    source_list: list[str],
    *,
    enabled: bool,
) -> None:
    preflight_ezproxy_session(console, cfg, pipe, source_list, enabled=enabled)

def _mid_run_ezproxy_hook(
    cfg: Config, pipe: Pipeline, *, enabled: bool
) -> Callable[[], bool] | None:
    return mid_run_ezproxy_hook(console, cfg, pipe, enabled=enabled)

def _maybe_ezproxy_relogin(
    cfg: Config,
    pipe: Pipeline,
    todo: list,
    *,
    enabled: bool,
) -> None:
    maybe_ezproxy_relogin(console, cfg, pipe, todo, enabled=enabled)

def _run_session_handoff(
    cfg: Config,
    backend: LibraryBackend | None,
    manifest: Manifest,
    catalog: list,
    stats: RunStats,
    *,
    handoff: str,
    include_doi_tabs: bool,
    downloads_dir: Path | None,
    re_request: bool = False,
) -> None:
    run_session_handoff(
        console,
        cfg,
        backend,
        manifest,
        catalog,
        stats,
        handoff=handoff,
        include_doi_tabs=include_doi_tabs,
        downloads_dir=downloads_dir,
        re_request=re_request,
    )

def _inbox_handoff_session(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    items: list,
    missing: list,
    *,
    scope: str,
    once: bool,
    idle_seconds: float | None = None,
    use_fifo: bool = True,
) -> None:
    inbox_handoff_session(
        console,
        cfg,
        backend,
        manifest,
        items,
        missing,
        scope=scope,
        once=once,
        idle_seconds=idle_seconds,
        use_fifo=use_fifo,
    )

def _mirror_deferred(cfg: Config) -> None:
    manager = _manager_name(cfg)
    console.print(
        f"[yellow]Saved to the local mirror ({cfg.out_dir}). "
        f"Not copied to {manager} yet — it was not reachable. "
        f"When it is, run paperful attach.[/]"
    )

def _library_write_api(backend: LibraryBackend) -> bool | None:
    try:
        return bool(backend.supports_write())
    except Exception:
        return None

def _run_flags(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v}

def _agent_json(fmt: str) -> bool:
    if not isinstance(fmt, str):
        return False
    kind = (fmt or "text").strip().lower()
    if kind not in {"text", "json"}:
        console.print("[red]--format must be text or json.[/]")
        raise typer.Exit(1)
    return kind == "json"

def _emit_agent(payload: dict[str, Any], *, json_out: bool, human: Callable[[], None]) -> None:
    from .agent_json import emit_stdout, stdout_suppressed

    if json_out:
        emit_stdout(payload)
    elif not stdout_suppressed():
        human()
    code = int(payload.get("exit") or 0)
    if code:
        raise typer.Exit(code)

def _agent_wins(fmt: str, as_json: bool = False) -> tuple[bool, bool]:
    """``--format json`` wins over legacy ``--json``."""
    json_out = _agent_json(fmt)
    return json_out, bool(as_json) and not json_out

def _finish_run(
    cfg: Config,
    stats: RunStats,
    *,
    scope: str,
    flags: dict,
    write_api: bool | None = None,
    json_out: bool = False,
) -> None:
    from .agent_json import batch_exit, envelope

    report = build_report(
        stats, cfg, command="run", scope=scope, flags=flags, write_api=write_api
    )
    path = write_run_report(cfg, report)
    summary = report.get("summary") or {}
    attached = int(summary.get("attached") or 0)
    attach_failed = int(summary.get("attach_failed") or 0)
    code = batch_exit(ok=attached, failed=attach_failed)
    payload = envelope(
        command="run",
        summary=summary if isinstance(summary, dict) else {},
        items=list(report.get("items") or []),
        paths={"report": str(path) if path else ""},
        flags=flags,
        report=report,
        exit_code=code,
    )

    def _human() -> None:
        print_run_summary(console, report, path)

    _emit_agent(payload, json_out=json_out, human=_human)

def _load_last_run(cfg: Config) -> dict | None:
    path = cfg.state_dir / "last-run.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None

def _rag_require(cfg: Config) -> None:
    if not cfg.rag_enabled:
        console.print("[red]rag.enabled is false in config.toml[/]")
        raise typer.Exit(1)

def _rag_embedder(cfg: Config):
    """A checked embedder, or exit 1 with the reason."""
    from .llm import embed_egress_is_remote, validate_embedder
    from .llm.validate import LlmConfigError

    try:
        embedder = validate_embedder(cfg)
    except LlmConfigError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if embed_egress_is_remote(cfg):
        console.print(
            "[yellow]Remote embedding model — passage text leaves this machine.[/]"
        )
    return embedder

def _rag_open(cfg: Config):
    """The index and its ledger, or exit 1 when there is nothing to search."""
    from .rag.index import (
        Index,
        IndexMismatch,
        IndexMissing,
        RagUnavailable,
        ledger_path,
    )
    from .rag.ledger import Ledger

    try:
        return Index.open(cfg), Ledger(ledger_path(cfg))
    except (RagUnavailable, IndexMissing, IndexMismatch) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

def _rag_auto(cfg: Config, since: float, keys: Any = ()) -> None:
    """Index PDFs this command just landed, when ``[rag].auto_ingest`` is on.

    Never fails the command it follows: the index is a cache, and
    ``paperful rag ingest`` catches up later.
    """
    if not (cfg.rag_enabled and cfg.rag_auto_ingest):
        return
    from .rag.auto import auto_ingest

    try:
        with _item_progress() as progress:
            batch = auto_ingest(
                cfg,
                since=since,
                keys=keys,
                track=_track(progress, "Indexing new PDFs"),
                ocr_track=_track(progress, "Running OCR"),
            )
    except KeyboardInterrupt:
        console.print(
            "[yellow]Indexing interrupted. `paperful rag ingest` resumes it.[/]"
        )
        return
    except Exception as exc:
        console.print(f"Index not updated: {exc}", markup=False, style="yellow")
        console.print("[yellow]Run `paperful rag ingest` to catch up.[/]")
        return
    if batch is None:
        return
    done = batch.count("pdf", "ocr", "abstract")
    if done:
        console.print(
            f"[dim]Index: {done} item(s) updated, {batch.chunks} passages.[/]"
        )

def _print_hits(hits: list) -> None:
    from .rag.prompt import Source

    for n, hit in enumerate(hits, start=1):
        who = Source("", hit.item_key, hit.title, hit.authors, hit.year).citation
        where = f", {hit.pages}" if hit.pages else ""
        console.print(
            f"{n}. {hit.score:.3f}  {who}. {hit.title}{where} [{hit.item_key}]",
            markup=False,
            highlight=False,
        )
        snippet = " ".join(hit.text.split())
        if len(snippet) > 320:
            snippet = snippet[:317] + "…"
        console.print(f"   {snippet}", markup=False, highlight=False, style="dim")

def _ask_once(
    cfg: Config,
    question: str,
    *,
    stream: bool,
    show_context: bool,
    history: list[dict[str, str]] | None = None,
    retrieve_as: str | None = None,
    quiet: bool = False,
    focus: str | None = None,
    prompt_path: str | None = None,
    **retrieval: Any,
) -> dict[str, Any]:
    """Answer one question on the terminal and return it for the run report."""
    from .rag.answer import answer

    reply = answer(
        cfg,
        question,
        history=history or (),
        retrieve_as=retrieve_as,
        focus=focus,
        prompt_path=prompt_path,
        **retrieval,
    )
    if quiet:
        reply.read()
    elif show_context and reply.hits:
        console.print("[bold]Passages[/]")
        _print_hits(reply.hits)
        console.print()
    if not quiet:
        # Answers carry [S1]-style markers; Rich would read them as markup and drop them.
        if stream:
            for piece in reply:
                console.out(piece, end="", highlight=False)
            console.out("", highlight=False)
        else:
            with _spinner("Thinking…"):
                reply.read()
            console.print(reply.text, markup=False, highlight=False)
        cited = reply.cited()
        listed = cited or reply.sources
        if listed:
            heading = "Sources" if cited else "Retrieved, not cited"
            console.print(f"\n[bold]{heading}[/]")
            for source in listed:
                pages = f" {', '.join(source.pages)}." if source.pages else ""
                console.print(
                    f"[{source.marker}] {source.citation}. {source.title}.{pages} "
                    f"[{source.item_key}]",
                    markup=False,
                    highlight=False,
                )
    cited = reply.cited()
    return {
        "question": question,
        "answer": reply.text,
        "cited": [s.marker for s in cited],
        "sources": [
            {
                "marker": s.marker,
                "itemKey": s.item_key,
                "title": s.title,
                "pages": s.pages,
            }
            for s in reply.sources
        ],
        "ask_mode": getattr(reply, "ask_mode", "simple"),
        "evidence": getattr(reply, "evidence", {}) or {},
    }

def _ask_questions(first: str | None) -> Iterator[str]:
    """The question given, or a prompt loop. Piped input is one question per line."""
    if first is not None:
        yield first
        return
    interactive = sys.stdin.isatty()
    if interactive:
        console.print("[dim]Ask about your library. Empty line or :q to leave.[/]")
    while True:
        try:
            line = input("ask> " if interactive else "")
        except EOFError:
            return
        line = line.strip()
        if line in (":q", "exit", "quit") or (interactive and not line):
            return
        if line:
            yield line

