"""Pull-only web search watch: re-run a grey query, remember seen URLs, propose new ones."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rich.console import Console
from rich.table import Table

from ..fsio import atomic_write_json, atomic_write_text
from ..config import Config
from ..keepup import days_until_due
from .apply import apply_candidates, mark_exists
from .run import run_search
from .store import SearchError, load_run

SCHEMA = "paperful.search.watch.v1"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DEFAULT_INTERVAL = 7


@dataclass
class WatchResult:
    run_dir: Path | None
    exit_code: int
    baseline: bool
    proposed: int
    already_seen: int
    skipped: bool = False
    days_left: int = 0
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApplyResult:
    created: int
    skipped_exists: int
    already_applied: int
    failed: int
    dry_run: bool


def watches_root(cfg: Config) -> Path:
    return cfg.state_dir / "search" / "watches"


def watch_dir(cfg: Config, name: str) -> Path:
    return watches_root(cfg) / name


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise SearchError(
            f"Invalid watch name {name!r}. "
            "Use letters, digits, '.', '_' or '-', starting with a letter or digit."
        )


def url_identity(url: str) -> str:
    """Stable URL key. Differs from snowball watch, which keys on DOI."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if not host:
        return raw.rstrip("/")
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    scheme = (parsed.scheme or "https").lower()
    return f"{scheme}://{host}{path}{query}"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _strip_built_query(query: str, hosts: list[str]) -> str:
    """Drop filetype:pdf / site: wrappers so a saved run can be watched again."""
    q = str(query or "").strip()
    q = re.sub(r"\s*filetype:\s*pdf\b", "", q, flags=re.I)
    if hosts:
        sites = " OR ".join(f"site:{h}" for h in hosts)
        q = q.replace(f"({sites})", "")
        q = q.replace(sites, "")
    return re.sub(r"\s+", " ", q).strip()


def save_watch(
    cfg: Config,
    name: str,
    *,
    terms: list[str] | None = None,
    hosts: str = "",
    filetype: str = "pdf",
    max_hits: int | None = None,
    probe: bool | None = None,
    interval_days: int | None = None,
    from_run: str | None = None,
) -> Path:
    """Remember a grey query. No scheduler; you cron `search watch run`."""
    _check_name(name)
    query_terms = [str(t).strip() for t in (terms or []) if str(t).strip()]
    host_text = str(hosts or "").strip()
    file_kind = (filetype or "pdf").strip() or "pdf"
    cap = max_hits
    do_probe = probe
    if from_run:
        bundle = load_run(cfg, from_run)
        meta = bundle.get("meta") or {}
        meta_hosts = [str(h) for h in (meta.get("hosts") or []) if h]
        if not host_text:
            host_text = ",".join(meta_hosts)
        if not query_terms:
            q = _strip_built_query(str(meta.get("query") or ""), meta_hosts)
            if q:
                query_terms = [q]
        if cap is None and meta.get("max") is not None:
            cap = int(meta.get("max") or 0) or None
        if do_probe is None and "probe" in meta:
            do_probe = bool(meta.get("probe"))
        stored_kind = str(meta.get("filetype") or "").strip()
        if stored_kind:
            file_kind = stored_kind
    if not query_terms:
        raise SearchError("search watch save needs --query or --from-run with a query.")
    interval = DEFAULT_INTERVAL if interval_days is None else int(interval_days)
    if interval < 0:
        raise SearchError("interval_days must be 0 or a positive number of days.")
    dest = watch_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "watch.json"
    if path.is_file():
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            body = {}
    else:
        body = {
            "schema": SCHEMA,
            "baseline_at": None,
            "last_run_at": None,
            "last_run_id": None,
        }
    body.update(
        {
            "schema": SCHEMA,
            "query": query_terms,
            "hosts": host_text,
            "filetype": file_kind,
            "max": cap,
            "probe": do_probe,
            "interval_days": interval,
        }
    )
    atomic_write_json(path, body)
    for leaf, payload in (
        ("seen.json", json.dumps({"urls": []}, indent=2) + "\n"),
        ("applied.json", json.dumps({"urls": []}, indent=2) + "\n"),
        ("inbox.jsonl", ""),
    ):
        target = dest / leaf
        if not target.is_file():
            atomic_write_text(target, payload)
    return path


def load_watch(cfg: Config, name: str) -> dict[str, Any]:
    _check_name(name)
    path = watch_dir(cfg, name) / "watch.json"
    if not path.is_file():
        raise SearchError(
            f"Unknown search watch {name!r}. Save one with search watch save."
        )
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise SearchError(f"Corrupt watch ledger at {path}.")
    return body


def list_watch_names(cfg: Config) -> list[str]:
    root = watches_root(cfg)
    if not root.is_dir():
        return []
    names = []
    for dest in sorted(root.iterdir()):
        if dest.is_dir() and (dest / "watch.json").is_file():
            names.append(dest.name)
    return names


def load_seen(cfg: Config, name: str) -> set[str]:
    return _load_url_set(watch_dir(cfg, name) / "seen.json")


def save_seen(cfg: Config, name: str, urls: set[str]) -> None:
    _save_url_set(watch_dir(cfg, name) / "seen.json", urls)


def load_applied(cfg: Config, name: str) -> set[str]:
    return _load_url_set(watch_dir(cfg, name) / "applied.json")


def save_applied(cfg: Config, name: str, urls: set[str]) -> None:
    _save_url_set(watch_dir(cfg, name) / "applied.json", urls)


def load_inbox(cfg: Config, name: str) -> list[dict[str, Any]]:
    path = watch_dir(cfg, name) / "inbox.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def append_inbox(cfg: Config, name: str, rows: list[dict[str, Any]]) -> None:
    from ..fsio import append_jsonl

    dest = watch_dir(cfg, name)
    path = dest / "inbox.jsonl"
    append_jsonl(
        path,
        [json.dumps(row, ensure_ascii=False) for row in rows],
        lock=(cfg.state_dir, f"search-watch-{name}"),
    )


def due_watches(cfg: Config) -> list[dict[str, Any]]:
    """Watches whose interval has elapsed. Empty when nothing is due."""
    return [
        row for row in list_watches(cfg) if int(row.get("days_until_due") or 0) <= 0
    ]


def inbox_count(cfg: Config, name: str) -> int:
    return len(load_inbox(cfg, name))


def list_watches(cfg: Config) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in list_watch_names(cfg):
        body = load_watch(cfg, name)
        interval = int(body.get("interval_days") or DEFAULT_INTERVAL)
        last = str(body.get("last_run_at") or "") or None
        rows.append(
            {
                "name": name,
                "query": " ".join(str(t) for t in (body.get("query") or [])),
                "hosts": str(body.get("hosts") or ""),
                "interval_days": interval,
                "days_until_due": days_until_due(last, interval),
                "inbox": inbox_count(cfg, name),
                "seen": len(load_seen(cfg, name)),
                "baseline": bool(body.get("baseline_at")),
            }
        )
    return rows


def run_watch(
    cfg: Config,
    name: str,
    *,
    console: Console,
    force: bool = False,
    getter: Any = None,
    probe_getter: Any = None,
    backend: Any = None,
) -> WatchResult:
    body = load_watch(cfg, name)
    interval = int(body.get("interval_days") or DEFAULT_INTERVAL)
    if not force and body.get("last_run_at"):
        left = days_until_due(str(body.get("last_run_at") or ""), interval)
        if left > 0:
            console.print(
                f"skipped · next due in {left} day(s) "
                f"(interval {interval}; pass --force to run now)"
            )
            return WatchResult(
                run_dir=None,
                exit_code=0,
                baseline=bool(body.get("baseline_at")),
                proposed=0,
                already_seen=len(load_seen(cfg, name)),
                skipped=True,
                days_left=left,
                summary={"skipped": True, "days_left": left, "interval_days": interval},
            )
    terms = [str(t) for t in (body.get("query") or []) if str(t).strip()]
    if not terms:
        raise SearchError(f"Watch {name!r} has no query.")
    is_baseline = not body.get("baseline_at")
    bundle = run_search(
        cfg,
        terms,
        hosts=str(body.get("hosts") or ""),
        filetype=str(body.get("filetype") or "pdf"),
        max_hits=body.get("max"),
        probe=body.get("probe"),
        getter=getter,
        probe_getter=probe_getter,
    )
    candidates = list(bundle.get("candidates") or [])
    mark_exists(cfg, candidates, backend=backend)
    seen = load_seen(cfg, name)
    run_path = Path(str(bundle.get("path") or ""))
    if is_baseline:
        for row in candidates:
            key = url_identity(str(row.get("url") or ""))
            if key:
                seen.add(key)
        save_seen(cfg, name, seen)
        now = _now()
        body.update(
            {
                "schema": SCHEMA,
                "baseline_at": now,
                "last_run_at": now,
                "last_run_id": bundle.get("run_id"),
            }
        )
        _write_watch(cfg, name, body)
        extra = {
            "watch": name,
            "baseline": True,
            "proposed": 0,
            "already_seen": len(seen),
            "baseline_count": len(seen),
        }
        console.print(f"baseline {len(seen)} · proposed 0")
        return WatchResult(
            run_dir=run_path if run_path else None,
            exit_code=0,
            baseline=True,
            proposed=0,
            already_seen=len(seen),
            summary=extra,
        )

    proposed: list[dict[str, Any]] = []
    already = 0
    for row in candidates:
        key = url_identity(str(row.get("url") or ""))
        if not key:
            continue
        if key in seen:
            already += 1
            continue
        seen.add(key)
        if row.get("status") == "new":
            proposed.append(row)
    save_seen(cfg, name, seen)
    if proposed:
        append_inbox(cfg, name, proposed)
    now = _now()
    body.update(
        {
            "schema": SCHEMA,
            "last_run_at": now,
            "last_run_id": bundle.get("run_id"),
        }
    )
    _write_watch(cfg, name, body)
    extra = {
        "watch": name,
        "baseline": False,
        "proposed": len(proposed),
        "already_seen": already,
    }
    console.print(f"proposed {len(proposed)} · already seen {already}")
    return WatchResult(
        run_dir=run_path if run_path else None,
        exit_code=0,
        baseline=False,
        proposed=len(proposed),
        already_seen=already,
        summary=extra,
    )


def apply_watch(
    cfg: Config,
    name: str,
    *,
    console: Console,
    collection: str,
    apply: bool = False,
    backend: Any = None,
) -> ApplyResult:
    dest = (collection or "").strip()
    if not dest:
        raise SearchError("search watch apply needs a target collection (-C).")
    load_watch(cfg, name)
    inbox = load_inbox(cfg, name)
    applied = load_applied(cfg, name)
    pending = []
    already = 0
    for row in inbox:
        key = url_identity(str(row.get("url") or ""))
        if not key:
            continue
        if key in applied:
            already += 1
            continue
        pending.append(row)
    mark_exists(cfg, pending, backend=backend)
    creatable = [row for row in pending if row.get("status") == "new"]
    skipped_exists = sum(1 for row in pending if row.get("status") == "exists")
    if not apply:
        table = Table(title=f"search watch apply {name} (dry-run)")
        table.add_column("Title")
        table.add_column("URL")
        table.add_column("Status")
        for row in pending[:25]:
            table.add_row(
                str(row.get("title") or "")[:80],
                str(row.get("url") or "")[:60],
                str(row.get("status") or ""),
            )
        console.print(table)
        console.print(
            f"would create {len(creatable)} · exists {skipped_exists} · "
            f"already applied {already}"
        )
        return ApplyResult(
            created=0,
            skipped_exists=skipped_exists,
            already_applied=already,
            failed=0,
            dry_run=True,
        )
    result = apply_candidates(
        cfg,
        pending,
        dest,
        backend=backend,
        urls=[str(row.get("url") or "") for row in creatable],
    )
    created = int(result.get("created") or 0)
    failed = int(result.get("failed") or 0)
    for row in pending:
        if row.get("status") == "created":
            key = url_identity(str(row.get("url") or ""))
            if key:
                applied.add(key)
    save_applied(cfg, name, applied)
    console.print(
        f"created {created} · exists {skipped_exists} · "
        f"already applied {already} · failed {failed}"
    )
    return ApplyResult(
        created=created,
        skipped_exists=skipped_exists,
        already_applied=already,
        failed=failed,
        dry_run=False,
    )


def show_watch(cfg: Config, name: str, *, console: Console) -> None:
    body = load_watch(cfg, name)
    interval = int(body.get("interval_days") or DEFAULT_INTERVAL)
    last = str(body.get("last_run_at") or "") or None
    console.print(f"search watch {name}")
    console.print(f"  query · {' '.join(str(t) for t in (body.get('query') or []))}")
    console.print(f"  hosts · {body.get('hosts') or '(any non-blocked)'}")
    console.print(f"  inbox · {inbox_count(cfg, name)}")
    console.print(f"  seen · {len(load_seen(cfg, name))}")
    console.print(f"  interval · {interval} day(s)")
    if last:
        left = days_until_due(last, interval)
        console.print(f"  last run · {last}")
        console.print(f"  due · {'now' if left == 0 else f'in {left} day(s)'}")
    else:
        console.print("  baseline · not yet")
    if body.get("last_run_id"):
        console.print(f"  last search run · {body['last_run_id']}")


def _write_watch(cfg: Config, name: str, body: dict[str, Any]) -> None:
    path = watch_dir(cfg, name) / "watch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, body)


def _load_url_set(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(body, dict):
        return set()
    return {url_identity(str(item)) for item in (body.get("urls") or []) if item}


def _save_url_set(path: Path, urls: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {"urls": sorted(u for u in urls if u)})
