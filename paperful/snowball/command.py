"""One snowball invocation. The CLI only parses flags and calls this."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from ..config import Config
from ..library import get_backend
from .candidate import Candidate
from .crawl import doi_candidates, search_candidates
from .expand import clamp_depth, keyword_depth, truncate
from .ingest import create_new, fill_pdfs
from .openalex import OpenAlexClient
from .queue import write_queue, write_report

Lookup = Callable[[str | None, str | None], str | None]


class SnowballError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


@dataclass
class SnowballRequest:
    gate: str = "dry-run"
    collection: str = ""
    fetch_pdfs: bool = False
    depth: int | None = None
    max_candidates: int | None = None
    per_hop_limit: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    direction: str = "refs"


def run_orcid() -> None:
    raise SnowballError("ORCID seeds are the next wave. Use snowball search or snowball doi.")


def run_search(
    cfg: Config,
    query: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> PathResult:
    _guard(cfg, request)
    depth = keyword_depth(request.depth)
    warning = "depth clamped to 1" if request.depth is not None and request.depth > 1 else None
    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
        warning=warning,
        crawl=lambda oa, run_id, gate, caps: search_candidates(
            oa,
            query,
            run_id=run_id,
            gate=gate,
            depth=depth,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            year_from=request.year_from,
            year_to=request.year_to,
        ),
    )


def run_doi(
    cfg: Config,
    dois: list[str],
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> PathResult:
    _guard(cfg, request)
    if request.direction != "refs":
        raise SnowballError("Cited-by expansion is a later wave. direction must be refs.")
    depth, warning = clamp_depth(1 if request.depth is None else request.depth)
    cleaned = [d.strip() for d in dois if d.strip()]
    if not cleaned:
        raise SnowballError("Pass at least one DOI.")

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int]) -> tuple[list[Candidate], list[str]]:
        return doi_candidates(
            oa,
            cleaned,
            run_id=run_id,
            gate=gate,
            depth=depth,
            max_candidates=caps[0],
            per_hop_limit=caps[1],
            year_from=request.year_from,
            year_to=request.year_to,
        )

    return _execute(
        cfg,
        request,
        console=console,
        client=client,
        lookup=lookup,
        backend=backend,
        warning=warning,
        crawl=crawl,
        expect_failures=True,
    )


@dataclass
class PathResult:
    run_dir: Any
    exit_code: int


def _guard(cfg: Config, request: SnowballRequest) -> None:
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    if request.gate not in {"dry-run", "auto"}:
        raise SnowballError("This wave accepts gate dry-run or auto. approve-batch is later.")
    if request.gate == "auto" and not request.collection.strip():
        raise SnowballError("gate auto needs a target collection (-C / target_collection).")


def _execute(
    cfg: Config,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None,
    lookup: Lookup | None,
    backend: Any,
    warning: str | None,
    crawl: Callable,
    expect_failures: bool = False,
) -> PathResult:
    if warning:
        console.print(f"[yellow]{warning}[/]")
    if request.fetch_pdfs and request.gate == "dry-run":
        console.print("[yellow]fetch_pdfs ignored on dry-run[/]")
    oa = client or OpenAlexClient(email=cfg.email, sleep_s=0.0 if client else 0.15)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gate = request.gate
    caps = (
        request.max_candidates if request.max_candidates is not None else cfg.snowball_max_candidates,
        request.per_hop_limit if request.per_hop_limit is not None else cfg.snowball_per_hop_limit,
    )
    failed: list[str] = []
    produced = crawl(oa, run_id, gate, caps)
    if expect_failures:
        rows, failed = produced
    else:
        rows = produced
    rows = truncate(rows, caps[0])
    library_unread = False
    finder = lookup
    lib = backend
    _unread_error: BaseException | None = None
    if finder is None and gate == "auto":
        try:
            lib = lib or get_backend(cfg)
            finder = _library_lookup(lib)
        except Exception as exc:
            library_unread = True
            finder = None
            lib = None
            _unread_error = exc
    elif finder is None:
        try:
            lib = lib or get_backend(cfg)
            finder = _library_lookup(lib)
        except Exception:
            library_unread = True
            finder = None
    if finder is not None:
        try:
            _mark_exists(rows, finder)
        except Exception:
            library_unread = True
    else:
        library_unread = True
    if finder is not None:
        try:
            _mark_exists(rows, finder)
        except Exception:
            library_unread = True
    else:
        library_unread = True
    dest = write_queue(cfg.state_dir, run_id, rows, oa, library_unread=library_unread)
    _print_table(console, rows)
    exit_code = 1 if failed else 0
    if gate == "dry-run":
        console.print("candidates ready")
        return PathResult(dest, exit_code)
    if library_unread or lib is None:
        detail = f" { _unread_error }" if _unread_error else ""
        raise SnowballError(f"Library was not read. Refusing to create items.{detail}")
    items, counts = create_new(lib, rows, request.collection)
    report = {
        "created": counts["created"],
        "skipped_exists": counts["skipped_exists"],
        "attach_ok": 0,
        "attach_deferred": 0,
    }
    if request.fetch_pdfs and items:
        stats = fill_pdfs(cfg, lib, items, console)
        downloaded = int(getattr(stats, "ok", 0)) + int(getattr(stats, "attached", 0))
        report["downloaded"] = downloaded
        report["attach_ok"] = int(getattr(stats, "attached", 0))
        report["attach_deferred"] = int(getattr(stats, "attach_failed", 0))
    write_report(dest, report)
    if request.fetch_pdfs:
        console.print(
            f"downloaded {report.get('downloaded', 0)} · attached {report['attach_ok']} · "
            f"deferred {report['attach_deferred']}"
        )
    else:
        console.print(f"items created (metadata only): {counts['created']}")
    return PathResult(dest, exit_code)


def _library_lookup(backend: Any) -> Lookup:
    zl = getattr(backend, "zl", None)

    def lookup(doi: str | None, title: str | None) -> str | None:
        if zl is None:
            return None
        return zl.find_top_item_key(doi=doi, title=title)

    return lookup


def _mark_exists(rows: list[Candidate], lookup: Lookup) -> None:
    for row in rows:
        if row.status == "error":
            continue
        key = lookup(row.ids.get("doi") or None, row.biblio.get("title") or None)
        if key:
            row.status = "exists"
            row.exists_match = {
                "item_key": key,
                "match": "doi" if row.ids.get("doi") else "title_year",
            }


def _print_table(console: Console, rows: list[Candidate]) -> None:
    ordered = sorted(rows, key=lambda row: (row.status != "new", -row.score))
    table = Table(title="Snowball", expand=True)
    for name in ("Title", "Year", "DOI", "Why", "In library", "Hop", "Backend"):
        table.add_column(name, overflow="ellipsis")
    for row in ordered:
        table.add_row(
            str(row.biblio.get("title") or ""),
            str(row.biblio.get("year") or ""),
            row.ids.get("doi") or "",
            row.why,
            row.status,
            f"{row.hop} {row.direction}",
            row.provenance.get("backend") or "",
        )
    console.print(table)
