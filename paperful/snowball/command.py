"""One snowball invocation. The CLI only parses flags and calls this."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from ..config import Config
from ..dedupe import normalize_dedupe_title
from ..library import LibraryError, get_backend
from ..resolve import normalize_doi
from .candidate import Candidate
from .crawl import doi_candidates, orcid_candidates, search_candidates
from .expand import apply_filters, clamp_depth, keyword_depth, normalize_direction, truncate
from .ingest import create_new, fill_pdfs
from .openalex import OpenAlexClient, normalize_orcid
from .orcid import OrcidError, orcid_dois
from .queue import load_queue, write_queue, write_report

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
    dedupe_scope: str | None = None
    tag_prefix: str | None = None
    types: tuple[str, ...] | None = None
    oa_only: bool | None = None
    venue_include: tuple[str, ...] | None = None
    venue_exclude: tuple[str, ...] | None = None


@dataclass
class PathResult:
    run_dir: Any
    exit_code: int


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
    warning = None
    if request.depth is not None and request.depth > depth:
        warning = f"depth clamped to {depth}"
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
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
            direction=direction,
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
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    depth, warning = clamp_depth(_graph_depth(cfg, request))
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
            direction=direction,
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


def run_orcid(
    cfg: Config,
    orcid: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    orcid_getter: Any = None,
) -> PathResult:
    _guard(cfg, request)
    cleaned = normalize_orcid(orcid)
    if not cleaned:
        raise SnowballError(f"Invalid ORCID iD: {orcid!r}")
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    depth, warning = clamp_depth(_graph_depth(cfg, request))
    try:
        dois = orcid_dois(cleaned, getter=orcid_getter)
    except OrcidError as exc:
        raise SnowballError(str(exc)) from exc

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int]) -> tuple[list[Candidate], list[str]]:
        return orcid_candidates(
            oa,
            cleaned,
            dois,
            run_id=run_id,
            gate=gate,
            depth=depth,
            direction=direction,
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


def run_collection(
    cfg: Config,
    seed_collection: str,
    request: SnowballRequest,
    *,
    console: Console,
    client: OpenAlexClient | None = None,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> PathResult:
    """DOIs already in ``seed_collection``, then the same expander as ``run_doi``."""
    _guard(cfg, request)
    try:
        direction = normalize_direction(request.direction)
    except ValueError as exc:
        raise SnowballError(str(exc)) from exc
    depth, warning = clamp_depth(_graph_depth(cfg, request))
    lib = backend
    try:
        lib = lib or get_backend(cfg)
        root = lib.resolve_collection(seed_collection)
        keys = lib.subtree_keys(root)
        items = lib.items_in_scope(keys)
    except Exception as exc:
        raise SnowballError(f"Could not read collection {seed_collection!r}: {exc}") from exc
    dois = sorted({item.doi for item in items if item.doi})
    if not dois:
        raise SnowballError(f"No DOIs in collection {seed_collection!r}.")

    def crawl(oa: OpenAlexClient, run_id: str, gate: str, caps: tuple[int, int]) -> tuple[list[Candidate], list[str]]:
        return doi_candidates(
            oa,
            dois,
            run_id=run_id,
            gate=gate,
            depth=depth,
            direction=direction,
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
        backend=lib,
        warning=warning,
        crawl=crawl,
        expect_failures=True,
    )


def run_apply(
    cfg: Config,
    run_id: str,
    request: SnowballRequest,
    *,
    console: Console,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> PathResult:
    """Create ``keep=true`` rows from a prior approve-batch (or edited) queue."""
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    collection = request.collection.strip()
    if not collection:
        raise SnowballError("snowball apply needs a target collection (-C / target_collection).")
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.") from exc

    kept = [row for row in rows if row.keep is True]
    if not kept:
        raise SnowballError(
            f"No keep=true rows in {run_id}. Edit candidates.jsonl, then apply again."
        )

    lib = backend
    finder = lookup
    if finder is None:
        try:
            lib = lib or get_backend(cfg)
            finder = _library_lookup(lib, scope="library", collection=collection)
        except Exception as exc:
            raise SnowballError(f"Library was not read. Refusing to create items. {exc}") from exc
    assert lib is not None and finder is not None
    _mark_exists(kept, finder)
    creatable = [row for row in kept if row.status == "new"]
    if not creatable:
        console.print("nothing to create (all keep rows already in library)")
        write_report(dest, {"created": 0, "skipped_exists": len(kept), "attach_ok": 0, "attach_deferred": 0})
        return PathResult(dest, 0)

    items, counts = create_new(lib, creatable, collection, tag_prefix=request.tag_prefix or cfg.snowball_tag_prefix)
    if counts.get("failed"):
        console.print(f"[yellow]{counts['failed']} create(s) failed; other rows continued[/]")
    report = {
        "created": counts["created"],
        "skipped_exists": counts["skipped_exists"] + (len(kept) - len(creatable)),
        "attach_ok": 0,
        "attach_deferred": 0,
    }
    if request.fetch_pdfs and items:
        stats = fill_pdfs(cfg, lib, items, console)
        downloaded = int(getattr(stats, "ok", 0)) + int(getattr(stats, "attached", 0))
        report["downloaded"] = downloaded
        report["attach_ok"] = int(getattr(stats, "attached", 0))
        report["attach_deferred"] = int(getattr(stats, "attach_failed", 0))
        console.print(
            f"downloaded {report.get('downloaded', 0)} · attached {report['attach_ok']} · "
            f"deferred {report['attach_deferred']}"
        )
    else:
        console.print(f"items created (metadata only): {counts['created']}")
    write_report(dest, report)
    return PathResult(dest, 1 if counts.get("failed") else 0)


def _guard(cfg: Config, request: SnowballRequest) -> None:
    if not cfg.snowball_enabled:
        raise SnowballError("Snowball is off. Set [snowball] enabled = true in config.toml.")
    if request.gate not in {"dry-run", "auto", "approve-batch"}:
        raise SnowballError(
            "gate must be dry-run, approve-batch, or auto. approve-each is later."
        )
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    if scope not in {"library", "collection", "none"}:
        raise SnowballError("dedupe_scope must be library, collection, or none.")
    if request.gate == "auto" and not request.collection.strip():
        raise SnowballError("gate auto needs a target collection (-C / target_collection).")


def _graph_depth(cfg: Config, request: SnowballRequest) -> int:
    """DOI, ORCID, and collection hops. Omitted depth uses [snowball] depth."""
    if request.depth is None:
        return cfg.snowball_depth
    return request.depth


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
    if request.fetch_pdfs and request.gate in {"dry-run", "approve-batch"}:
        console.print("[yellow]fetch_pdfs ignored until create (auto / apply)[/]")
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
    scope = (request.dedupe_scope or cfg.snowball_dedupe_scope or "library").strip()
    types = cfg.snowball_types if request.types is None else request.types
    oa_only = cfg.snowball_oa_only if request.oa_only is None else request.oa_only
    venue_include = cfg.snowball_venue_include if request.venue_include is None else request.venue_include
    venue_exclude = cfg.snowball_venue_exclude if request.venue_exclude is None else request.venue_exclude
    tag_prefix = request.tag_prefix or cfg.snowball_tag_prefix
    rows = apply_filters(
        rows,
        year_from=request.year_from,
        year_to=request.year_to,
        types=types,
        oa_only=oa_only,
        venue_include=venue_include,
        venue_exclude=venue_exclude,
    )
    rows = truncate(rows, caps[0])
    if gate == "approve-batch":
        for row in rows:
            if row.keep is None and row.status == "new":
                row.keep = False
    library_unread = False
    finder = lookup
    lib = backend
    _unread_error: BaseException | None = None
    if scope == "none":
        console.print("[yellow]dedupe_scope none: not checking the library[/]")
        finder = None
        if gate == "auto" and lib is None:
            try:
                lib = get_backend(cfg)
            except Exception as exc:
                lib = None
                _unread_error = exc
                library_unread = True
    elif finder is None:
        try:
            lib = lib or get_backend(cfg)
            finder = _library_lookup(lib, scope=scope, collection=request.collection)
        except Exception as exc:
            library_unread = True
            finder = None
            if gate == "auto":
                lib = None
                _unread_error = exc
    if scope != "none" and finder is not None:
        try:
            _mark_exists(rows, finder)
        except Exception:
            library_unread = True
    elif scope != "none":
        library_unread = True
    filtered = sum(1 for row in rows if row.status == "filtered")
    dest = write_queue(
        cfg.state_dir,
        run_id,
        rows,
        oa,
        library_unread=library_unread,
        meta={
            "score": "cited_by_count",
            "max_candidates": caps[0],
            "per_hop_limit": caps[1],
            "filtered": filtered,
            "dedupe_scope": scope,
        },
    )
    _print_table(console, rows)
    exit_code = 1 if failed else 0
    if gate in {"dry-run", "approve-batch"}:
        if gate == "approve-batch":
            console.print(
                f"candidates ready · mark keep=true in {dest / 'candidates.jsonl'} · "
                f"then: paperful snowball apply {run_id}"
            )
        else:
            console.print("candidates ready")
        return PathResult(dest, exit_code)
    if library_unread or lib is None:
        detail = f" { _unread_error }" if _unread_error else ""
        raise SnowballError(f"Library was not read. Refusing to create items.{detail}")
    try:
        items, counts = create_new(lib, rows, request.collection, tag_prefix=tag_prefix)
    except LibraryError as exc:
        raise SnowballError(str(exc)) from exc
    exit_code = 1 if failed or counts.get("failed") else exit_code
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


def _library_lookup(backend: Any, *, scope: str, collection: str) -> Lookup:
    items = None
    if hasattr(backend, "items_in_scope"):
        try:
            items = list(backend.items_in_scope(None))
        except Exception:
            items = None
    if items is not None:
        if scope == "collection":
            want = collection.strip()
            items = [item for item in items if want and want in (item.collection_paths or [])]
        by_doi: dict[str, str] = {}
        by_title_year: dict[tuple[str, int], str] = {}
        for item in items:
            doi = normalize_doi(item.doi) if getattr(item, "doi", None) else None
            if doi:
                by_doi.setdefault(doi, item.key)
            title = normalize_dedupe_title(getattr(item, "title", None))
            year = getattr(item, "year", None)
            if title and year is not None:
                by_title_year.setdefault((title, int(year)), item.key)

        def indexed(doi: str | None, title: str | None, year: int | None = None) -> Any:
            found = normalize_doi(doi) if doi else None
            if found and found in by_doi:
                return by_doi[found], "doi"
            key = normalize_dedupe_title(title)
            if key and year is not None and (key, int(year)) in by_title_year:
                return by_title_year[(key, int(year))], "title_year"
            return None

        return indexed

    zl = getattr(backend, "zl", None)

    def lookup(doi: str | None, title: str | None, year: int | None = None) -> str | None:
        del year
        if zl is None:
            return None
        return zl.find_top_item_key(doi=doi, title=title)

    return lookup


def _mark_exists(rows: list[Candidate], lookup: Lookup) -> None:
    for row in rows:
        if row.status in {"error", "filtered"}:
            continue
        doi = row.ids.get("doi") or None
        title = row.biblio.get("title") or None
        year = row.biblio.get("year")
        try:
            found = lookup(doi, title, year)
        except TypeError:
            found = lookup(doi, title)
        if not found:
            continue
        if isinstance(found, tuple):
            key, kind = found
        else:
            key, kind = found, ("doi" if doi else "title_year")
        row.status = "exists"
        if kind == "title_year":
            row.exists_match = {
                "item_key": key,
                "title_year": f"{normalize_dedupe_title(title)}|{year}",
            }
        else:
            row.exists_match = {"item_key": key, "doi": normalize_doi(doi) or (doi or "")}


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
