"""Alert loop and collection digests. Operator cron; Paperful does not schedule."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from .config import Config
from .identity import from_seed_tag
from .snowball.candidate import Candidate
from .snowball.command import SnowballError, _mark_exists, get_backend

SCHEMA = "paperful.keepup.v1"
TAG = "paperful-keepup"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_TYPES = frozenset({"watch", "authorwatch", "cites"})
Lookup = Callable[..., Any]


class KeepupError(SnowballError):
    """User-facing keepup failure."""


@dataclass
class Source:
    type: str
    name: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "name": self.name}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Source:
        kind = str(raw.get("type") or "").strip().lower()
        name = str(raw.get("name") or "").strip()
        return cls(type=kind, name=name)


@dataclass
class RunResult:
    skipped: bool
    baseline: bool = False
    proposed: int = 0
    days_left: int = 0
    digest_path: Path | None = None
    ingested_path: Path | None = None
    created: int = 0
    source_notes: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    created: int
    skipped_exists: int
    already_applied: int
    failed: int
    dry_run: bool
    ingested_path: Path | None = None


def jobs_root(cfg: Config) -> Path:
    return cfg.state_dir / "keepup"


def job_dir(cfg: Config, name: str) -> Path:
    _check_name(name)
    return jobs_root(cfg) / name


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise KeepupError(
            f"Invalid keepup name {name!r}. "
            "Use letters, digits, '.', '_' or '-', starting with a letter or digit."
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cursor_date(iso: str | None) -> str | None:
    text = str(iso or "").strip()
    if not text:
        return None
    return text[:10]


def _parse_iso(iso: str | None) -> datetime | None:
    text = str(iso or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def days_until_due(last_run_at: str | None, interval_days: int) -> int:
    """Days remaining before the next poll. 0 means due now."""
    if interval_days <= 0:
        return 0
    stamp = _parse_iso(last_run_at)
    if stamp is None:
        return 0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    due = stamp + timedelta(days=interval_days)
    now = datetime.now(timezone.utc)
    if now >= due:
        return 0
    delta = due - now
    return max(1, int(delta.total_seconds() // 86400) or 1)


def save_job(
    cfg: Config,
    name: str,
    *,
    collection: str,
    sources: list[Source],
    interval_days: int | None = None,
    per_seed_limit: int = 20,
    max_candidates: int = 100,
) -> Path:
    _check_name(name)
    dest_c = collection.strip()
    if not dest_c:
        raise KeepupError("keepup save needs -C / --collection.")
    if not sources:
        raise KeepupError(
            "keepup save needs at least one source "
            "(--watch, --authorwatch, and/or --source cites)."
        )
    cleaned: list[Source] = []
    for src in sources:
        kind = src.type.strip().lower()
        if kind not in SOURCE_TYPES:
            raise KeepupError(
                f"Unknown source type {src.type!r}. Use watch, authorwatch, or cites."
            )
        if kind in {"watch", "authorwatch"} and not src.name.strip():
            raise KeepupError(f"{kind} source needs a name.")
        cleaned.append(Source(type=kind, name=src.name.strip()))
    interval = (
        int(interval_days)
        if interval_days is not None
        else int(getattr(cfg, "keepup_interval_days", 7) or 7)
    )
    if interval < 0:
        raise KeepupError("interval_days must be >= 0 (0 = every run).")
    dest = job_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "job.json"
    if path.is_file():
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            body = {}
    else:
        body = {
            "schema": SCHEMA,
            "baseline_at": None,
            "last_run_at": None,
        }
    body.update(
        {
            "schema": SCHEMA,
            "name": name,
            "collection": dest_c,
            "interval_days": interval,
            "per_seed_limit": max(1, int(per_seed_limit)),
            "max_candidates": max(0, int(max_candidates)),
            "sources": [src.to_dict() for src in cleaned],
        }
    )
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    for leaf, content in (
        ("seen.json", json.dumps({"identities": []}, indent=2) + "\n"),
        ("applied.json", json.dumps({"identities": []}, indent=2) + "\n"),
        ("muted.json", json.dumps({"identities": []}, indent=2) + "\n"),
        ("inbox.jsonl", ""),
    ):
        target = dest / leaf
        if not target.is_file():
            target.write_text(content, encoding="utf-8")
    return path


def load_job(cfg: Config, name: str) -> dict[str, Any]:
    path = job_dir(cfg, name) / "job.json"
    if not path.is_file():
        raise KeepupError(f"Unknown keepup job {name!r}. Save one with keepup save.")
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise KeepupError(f"Corrupt keepup ledger at {path}.")
    return body


def _write_job(cfg: Config, name: str, body: dict[str, Any]) -> None:
    path = job_dir(cfg, name) / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(body)
    body["schema"] = SCHEMA
    body["name"] = name
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def list_jobs(cfg: Config) -> list[str]:
    root = jobs_root(cfg)
    if not root.is_dir():
        return []
    names = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "job.json").is_file():
            names.append(path.name)
    return names


def delete_job(cfg: Config, name: str) -> Path:
    import shutil

    dest = job_dir(cfg, name)
    if not dest.is_dir():
        raise KeepupError(f"Unknown keepup job {name!r}.")
    shutil.rmtree(dest)
    return dest


def _identities(cfg: Config, name: str, leaf: str) -> set[str]:
    path = job_dir(cfg, name) / leaf
    if not path.is_file():
        return set()
    body = json.loads(path.read_text(encoding="utf-8"))
    return {str(item) for item in (body.get("identities") or []) if item}


def _save_identities(cfg: Config, name: str, leaf: str, identities: set[str]) -> None:
    dest = job_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / leaf).write_text(
        json.dumps({"identities": sorted(identities)}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_seen(cfg: Config, name: str) -> set[str]:
    return _identities(cfg, name, "seen.json")


def save_seen(cfg: Config, name: str, identities: set[str]) -> None:
    _save_identities(cfg, name, "seen.json", identities)


def load_applied(cfg: Config, name: str) -> set[str]:
    return _identities(cfg, name, "applied.json")


def save_applied(cfg: Config, name: str, identities: set[str]) -> None:
    _save_identities(cfg, name, "applied.json", identities)


def load_muted(cfg: Config, name: str) -> set[str]:
    return _identities(cfg, name, "muted.json")


def save_muted(cfg: Config, name: str, identities: set[str]) -> None:
    _save_identities(cfg, name, "muted.json", identities)


def load_inbox(cfg: Config, name: str) -> list[Candidate]:
    path = job_dir(cfg, name) / "inbox.jsonl"
    if not path.is_file():
        return []
    rows: list[Candidate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(Candidate.from_dict(raw))
    return rows


def append_inbox(cfg: Config, name: str, rows: list[Candidate]) -> None:
    path = job_dir(cfg, name) / "inbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def dismiss(cfg: Config, name: str, *, identity: str = "", doi: str = "") -> str:
    """Mute an identity so it is never re-proposed."""
    from .resolve import normalize_doi

    load_job(cfg, name)
    key = identity.strip()
    if not key and doi.strip():
        cleaned = normalize_doi(doi) or doi.strip().lower()
        key = f"doi:{cleaned}"
    if not key:
        raise KeepupError("dismiss needs --identity or --doi.")
    muted = load_muted(cfg, name)
    muted.add(key)
    save_muted(cfg, name, muted)
    return key


def show_job(cfg: Config, name: str, *, console: Console) -> None:
    body = load_job(cfg, name)
    inbox = load_inbox(cfg, name)
    applied = load_applied(cfg, name)
    pending = sum(1 for row in inbox if row.identity and row.identity not in applied)
    console.print(f"keepup {name}")
    console.print(f"  collection · {body.get('collection')}")
    console.print(f"  interval_days · {body.get('interval_days')}")
    console.print(f"  inbox pending · {pending}")
    console.print(f"  seen · {len(load_seen(cfg, name))}")
    console.print(f"  muted · {len(load_muted(cfg, name))}")
    if body.get("baseline_at"):
        console.print(f"  baseline · {body['baseline_at']}")
    else:
        console.print("  baseline · not yet")
    if body.get("last_run_at"):
        console.print(f"  last run · {body['last_run_at']}")
        left = days_until_due(
            str(body.get("last_run_at") or ""),
            int(body.get("interval_days") or 0),
        )
        if left:
            console.print(f"  next due · in {left} day(s) (or --force)")
        else:
            console.print("  next due · now")
    for src in body.get("sources") or []:
        if isinstance(src, dict):
            label = src.get("type") or ""
            src_name = src.get("name") or ""
            console.print(f"  source · {label}" + (f" {src_name}" if src_name else ""))


def write_digest(cfg: Config, name: str) -> Path:
    body = load_job(cfg, name)
    rows = load_inbox(cfg, name)
    applied = load_applied(cfg, name)
    muted = load_muted(cfg, name)
    pending = [
        row
        for row in rows
        if row.identity
        and row.identity not in applied
        and row.identity not in muted
        and row.status == "new"
    ]
    pending.sort(key=lambda row: row.score, reverse=True)
    collection = str(body.get("collection") or "")
    quoted = f'"{collection}"' if any(ch.isspace() for ch in collection) else collection
    dest = job_dir(cfg, name)
    path = dest / "digest.md"
    lines = [
        f"# Keepup digest {name}",
        "",
        f"Collection `{collection}` · pending {len(pending)}.",
        f"Interval {body.get('interval_days')} day(s).",
        "",
        "## New",
        "",
    ]
    if not pending:
        lines.append("None.")
    else:
        for row in pending[:25]:
            title = str(row.biblio.get("title") or "").strip() or "(untitled)"
            doi = row.ids.get("doi") or ""
            why = (row.why or "").replace("\n", " ").strip()
            score = row.score
            bit = f"- {title}"
            if doi:
                bit += f" · `{doi}`"
            bit += f" — score {score:g}"
            if why:
                bit += f" — {why}"
            lines.append(bit)
        if len(pending) > 25:
            lines.append(f"- … and {len(pending) - 25} more")
    lines.extend(
        [
            "",
            "## Next",
            "",
            f"- `paperful keepup apply {name}`",
            f"- `paperful keepup apply {name} --apply`",
            f"- `paperful keepup run {name} --apply`",
            f"- `paperful run -C {quoted}` after parents land",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_ingest_briefing(
    cfg: Config,
    name: str,
    *,
    collection: str,
    created_rows: list[Candidate],
    created: int,
    skipped_exists: int,
    failed: int,
) -> Path:
    dest = job_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "ingested.md"
    quoted = f'"{collection}"' if any(ch.isspace() for ch in collection) else collection
    lines = [
        f"# Keepup ingest {name}",
        "",
        f"Collection `{collection}`.",
        f"created {created} · exists {skipped_exists} · failed {failed}",
        "",
        "## Created",
        "",
    ]
    if not created_rows:
        lines.append("None.")
    else:
        for row in created_rows:
            title = str(row.biblio.get("title") or "").strip() or "(untitled)"
            doi = row.ids.get("doi") or ""
            why = (row.why or "").replace("\n", " ").strip()
            bit = f"- {title}"
            if doi:
                bit += f" · `{doi}`"
            if why:
                bit += f" — {why}"
            lines.append(bit)
    lines.extend(
        [
            "",
            "## Next",
            "",
            f"- `paperful run -C {quoted}`",
            "- Open Wanted in the workbench for PDFs",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _sources(body: dict[str, Any]) -> list[Source]:
    out: list[Source] = []
    for raw in body.get("sources") or []:
        if isinstance(raw, dict):
            out.append(Source.from_dict(raw))
    return out


def _poll_watch(
    cfg: Config,
    src: Source,
    *,
    console: Console,
    client: Any,
    backend: Any,
    lookup: Lookup | None,
) -> tuple[list[Candidate], str]:
    from .snowball.watch import load_inbox as watch_inbox
    from .snowball.watch import load_applied as watch_applied
    from .snowball.watch import run_watch

    result = run_watch(
        cfg,
        src.name,
        console=console,
        client=client,
        backend=backend,
        lookup=lookup,
    )
    applied = watch_applied(cfg, src.name)
    rows = [
        row
        for row in watch_inbox(cfg, src.name)
        if row.identity and row.identity not in applied and row.status == "new"
    ]
    note = f"watch {src.name}: proposed {result.proposed}"
    if result.baseline:
        note += " (baseline)"
    return rows, note


def _poll_authorwatch(
    cfg: Config,
    src: Source,
    *,
    console: Console,
    client: Any,
    backend: Any,
    lookup: Lookup | None,
) -> tuple[list[Candidate], str]:
    from . import authorwatch as aw

    result = aw.run_list(
        cfg,
        src.name,
        console=console,
        client=client,
        backend=backend,
        lookup=lookup,
    )
    applied = aw.load_applied(cfg, src.name)
    rows = [
        row
        for row in aw.load_inbox(cfg, src.name)
        if row.identity and row.identity not in applied and row.status == "new"
    ]
    note = f"authorwatch {src.name}: proposed {result.proposed}"
    if result.baseline:
        note += " (baseline)"
    return rows, note


def _poll_cites(
    cfg: Config,
    body: dict[str, Any],
    name: str,
    *,
    console: Console,
    client: Any,
    backend: Any,
    lookup: Lookup | None,
    is_baseline: bool,
) -> tuple[list[Candidate], str, set[str]]:
    from .keepup_cites import baseline_identities, probe_cites

    collection = str(body.get("collection") or "")
    per_seed = int(body.get("per_seed_limit") or 20)
    max_cand = int(body.get("max_candidates") or 100)
    if is_baseline:
        seen = baseline_identities(
            cfg,
            collection=collection,
            per_seed_limit=per_seed,
            max_candidates=max_cand,
            console=console,
            client=client,
            backend=backend,
        )
        return [], f"cites: baseline {len(seen)}", seen
    proposed, polled = probe_cites(
        cfg,
        collection=collection,
        run_id=f"keepup:{name}",
        from_created_date=_cursor_date(
            str(body.get("last_run_at") or body.get("baseline_at") or "")
        ),
        per_seed_limit=per_seed,
        max_candidates=max_cand,
        muted=load_muted(cfg, name),
        seen=load_seen(cfg, name),
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
    )
    return proposed, f"cites: proposed {len(proposed)} · seeds {polled}", set()


def run_job(
    cfg: Config,
    name: str,
    *,
    console: Console,
    force: bool = False,
    apply: bool = False,
    client: Any = None,
    backend: Any = None,
    lookup: Lookup | None = None,
) -> RunResult:
    body = load_job(cfg, name)
    interval = int(body.get("interval_days") or getattr(cfg, "keepup_interval_days", 7) or 7)
    if not force and body.get("last_run_at"):
        left = days_until_due(str(body.get("last_run_at") or ""), interval)
        if left > 0:
            console.print(
                f"skipped · next due in {left} day(s) "
                f"(interval {interval}; pass --force to run now)"
            )
            return RunResult(skipped=True, days_left=left)

    is_baseline = not body.get("baseline_at")
    collection = str(body.get("collection") or "")
    notes: list[str] = []
    merged: dict[str, Candidate] = {}
    seen = load_seen(cfg, name)
    muted = load_muted(cfg, name)

    for src in _sources(body):
        if src.type == "watch":
            rows, note = _poll_watch(
                cfg, src, console=console, client=client, backend=backend, lookup=lookup
            )
            notes.append(note)
            for row in rows:
                if row.identity and row.identity not in muted:
                    merged.setdefault(row.identity, row)
        elif src.type == "authorwatch":
            rows, note = _poll_authorwatch(
                cfg, src, console=console, client=client, backend=backend, lookup=lookup
            )
            notes.append(note)
            for row in rows:
                if row.identity and row.identity not in muted:
                    merged.setdefault(row.identity, row)
        elif src.type == "cites":
            rows, note, baseline_seen = _poll_cites(
                cfg,
                body,
                name,
                console=console,
                client=client,
                backend=backend,
                lookup=lookup,
                is_baseline=is_baseline,
            )
            notes.append(note)
            if baseline_seen:
                seen |= baseline_seen
            for row in rows:
                if row.identity and row.identity not in muted:
                    merged.setdefault(row.identity, row)
        else:
            raise KeepupError(f"Unknown source type {src.type!r}.")

    proposed = list(merged.values())
    for row in proposed:
        if row.identity:
            seen.add(row.identity)
    save_seen(cfg, name, seen)

    now = _now()
    if is_baseline:
        # First keepup run advances source cursors / cites baseline only.
        body["baseline_at"] = now
        body["last_run_at"] = now
        _write_job(cfg, name, body)
        digest = write_digest(cfg, name)
        console.print(f"baseline · proposed 0 · sources: {'; '.join(notes)}")
        console.print(f"Wrote [bold]{digest}[/]")
        return RunResult(
            skipped=False,
            baseline=True,
            proposed=0,
            digest_path=digest,
            source_notes=notes,
        )

    fresh = [row for row in proposed if row.identity not in load_applied(cfg, name)]
    # Drop rows already sitting in the keepup inbox.
    inbox_ids = {row.identity for row in load_inbox(cfg, name) if row.identity}
    fresh = [row for row in fresh if row.identity not in inbox_ids]
    if fresh:
        append_inbox(cfg, name, fresh)
    body["last_run_at"] = now
    _write_job(cfg, name, body)
    digest = write_digest(cfg, name)
    console.print(f"proposed {len(fresh)} · sources: {'; '.join(notes)}")
    console.print(f"Wrote [bold]{digest}[/]")
    result = RunResult(
        skipped=False,
        baseline=False,
        proposed=len(fresh),
        digest_path=digest,
        source_notes=notes,
    )
    if apply:
        applied = apply_job(
            cfg,
            name,
            console=console,
            apply=True,
            lookup=lookup,
            backend=backend,
        )
        result.created = applied.created
        result.ingested_path = applied.ingested_path
    return result


def apply_job(
    cfg: Config,
    name: str,
    *,
    console: Console,
    apply: bool = False,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> ApplyResult:
    from .snowball.ingest import create_new

    body = load_job(cfg, name)
    collection = str(body.get("collection") or "").strip()
    if not collection:
        raise KeepupError("keepup job has no collection.")
    rows = load_inbox(cfg, name)
    applied = load_applied(cfg, name)
    muted = load_muted(cfg, name)
    pending: list[Candidate] = []
    already = 0
    for row in rows:
        key = row.identity
        if not key or key in muted:
            continue
        if key in applied:
            already += 1
            continue
        if row.status not in {"new", "exists"}:
            continue
        row.keep = True
        pending.append(row)
    finder = lookup
    lib = backend
    if finder is None:
        try:
            lib = lib or get_backend(cfg)
            from .snowball.command import _library_lookup

            finder = _library_lookup(lib, scope="library", collection=collection)
        except Exception as exc:
            raise KeepupError(f"Library was not read. Refusing to create items. {exc}") from exc
    _mark_exists(pending, finder)
    creatable = [row for row in pending if row.status == "new"]
    skipped_exists = sum(1 for row in pending if row.status in {"exists", "version"})
    if not apply:
        table = Table(title=f"keepup apply {name} (dry-run)")
        table.add_column("Title")
        table.add_column("DOI")
        table.add_column("Why")
        for row in pending[:25]:
            table.add_row(
                str(row.biblio.get("title") or "")[:60],
                row.ids.get("doi") or "",
                (row.why or "")[:40],
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
    assert lib is not None
    extra = [from_seed_tag({"type": "keepup", "value": name}) or f"from-keepup-{name}"]
    items, counts = create_new(
        lib,
        creatable,
        collection,
        tag_prefix=TAG,
        extra_tags=extra,
        note_provenance=True,
        console=console,
        remarks_surface=cfg.remarks_surface,
    )
    created = int(counts.get("created") or len(items))
    failed = int(counts.get("failed") or 0)
    skipped_exists += int(counts.get("skipped_exists") or 0)
    landed: list[Candidate] = []
    for row in creatable:
        key = row.identity
        if key and row.status != "error":
            applied.add(key)
            landed.append(row)
    save_applied(cfg, name, applied)
    # Also mark applied on nested watch/authorwatch ledgers when present.
    for src in _sources(body):
        if src.type == "watch" and src.name:
            from .snowball import watch as sw

            nested = sw.load_applied(cfg, src.name)
            nested |= {row.identity for row in landed if row.identity}
            sw.save_applied(cfg, src.name, nested)
        elif src.type == "authorwatch" and src.name:
            from . import authorwatch as aw

            nested = aw.load_applied(cfg, src.name)
            nested |= {row.identity for row in landed if row.identity}
            aw.save_applied(cfg, src.name, nested)
    ingested = write_ingest_briefing(
        cfg,
        name,
        collection=collection,
        created_rows=landed,
        created=created,
        skipped_exists=skipped_exists,
        failed=failed,
    )
    console.print(
        f"created {created} · exists {skipped_exists} · "
        f"already applied {already} · failed {failed}"
    )
    console.print(f"Wrote [bold]{ingested}[/]")
    if created:
        console.print(f"Next: paperful run -C {collection}")
    return ApplyResult(
        created=created,
        skipped_exists=skipped_exists,
        already_applied=already,
        failed=failed,
        dry_run=False,
        ingested_path=ingested,
    )
