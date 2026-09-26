"""Fill empty metadata. OpenAlex wins when a field is already set."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, NoReturn

from ..lint import usable_work_title
from .candidate import Candidate

CrossrefGet = Callable[[str], dict[str, Any] | None]
S2Get = Callable[[str], dict[str, Any] | None]


class ApiKeyRejected(RuntimeError):
    """The server refused a key that was sent. This is not an empty result."""


class FillPaused(RuntimeError):
    """A fill API asked us to stop and resume the remaining DOIs later."""

    def __init__(self, backend: str, remaining: list[str] | None = None, added: list | None = None):
        super().__init__(backend)
        self.backend = backend
        self.remaining = list(remaining or [])
        self.added = list(added or [])


def fill_crossref(
    rows: list[Candidate],
    getter: CrossrefGet,
    *,
    progress: Callable[[str], None] | None = None,
    tally: Any = None,
    per_hop_limit: int = 0,
    direction: str = "refs",
    only_dois: set[str] | None = None,
    expand_neighbors: bool = True,
) -> list[Candidate]:
    pending = _gap_rows(rows, only_dois, expand_neighbors=expand_neighbors)
    added: list[Candidate] = []
    known = {row.identity for row in rows if row.identity}
    if tally is not None and pending:
        tally.stage = "crossref"
        tally.track(len(pending))
    for row in pending:
        doi = row.ids.get("doi") or ""
        if progress is not None:
            progress(f"crossref · {doi}")
        if tally is not None:
            tally.searches += 1
        try:
            payload = getter(doi)
        except FillPaused as exc:
            raise FillPaused("crossref", _remaining_dois(pending, row)) from exc
        if not payload:
            if tally is not None:
                tally.advance(1)
            continue
        filled = _fill_empty(row, payload, backend="crossref") if not _complete(row) else 0
        if expand_neighbors:
            added.extend(
                _neighbor_rows(
                    row,
                    _ref_dicts(payload),
                    known,
                    backend="crossref",
                    per_hop_limit=per_hop_limit,
                    direction=direction,
                )
            )
        if tally is not None:
            tally.fields += filled
            tally.advance(1)
    return added


def fill_semanticscholar(
    rows: list[Candidate],
    getter: S2Get,
    *,
    per_hop_limit: int,
    direction: str,
    tally: Any = None,
    only_dois: set[str] | None = None,
    expand_neighbors: bool = True,
) -> list[Candidate]:
    """Fill holes and append reference neighbours for seeds that still cite nothing."""
    added: list[Candidate] = []
    known = {row.identity for row in rows if row.identity}
    want_refs = direction in {"refs", "both"}
    pending = _gap_rows(rows, only_dois, expand_neighbors=expand_neighbors)
    if tally is not None and pending:
        tally.stage = "semantic scholar"
        tally.track(len(pending))
    for row in pending:
        doi = row.ids.get("doi") or ""
        if tally is not None:
            tally.searches += 1
        try:
            payload = getter(doi)
        except FillPaused as exc:
            raise FillPaused("semanticscholar", _remaining_dois(pending, row)) from exc
        if not payload:
            if tally is not None:
                tally.advance(1)
            continue
        filled = _fill_empty(
            row,
            {
                "title": payload.get("title") or "",
                "year": payload.get("year"),
                "venue": payload.get("venue") or "",
                "authors": [
                    (author.get("name") or "")
                    for author in (payload.get("authors") or [])
                    if isinstance(author, dict)
                ],
            },
            backend="semanticscholar",
        )
        if tally is not None:
            tally.fields += filled
            tally.advance(1)
        if not want_refs or not expand_neighbors:
            continue
        added.extend(
            _neighbor_rows(
                row,
                _s2_refs(payload),
                known,
                backend="semanticscholar",
                per_hop_limit=per_hop_limit,
                direction=direction,
                why_prefix="s2 ref of",
            )
        )
    return added


def _remaining_dois(rows: list[Candidate], start: Candidate) -> list[str]:
    pending: list[str] = []
    seen = False
    for row in rows:
        if row is start:
            seen = True
        if seen:
            doi = row.ids.get("doi") or ""
            if doi:
                pending.append(doi)
    return pending


def _wanted(row: Candidate, only_dois: set[str] | None) -> bool:
    if only_dois is None:
        return True
    return (row.ids.get("doi") or "").lower() in only_dois


def _ref_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for ref in payload.get("references") or []:
        if isinstance(ref, dict) and (ref.get("doi") or ref.get("title")):
            refs.append(ref)
    return refs


def _s2_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for ref in payload.get("references") or []:
        if not isinstance(ref, dict):
            continue
        refs.append(
            {
                "doi": str((ref.get("externalIds") or {}).get("DOI") or ""),
                "title": ref.get("title") or "",
                "year": ref.get("year"),
            }
        )
    return refs


def _neighbor_rows(
    row: Candidate,
    refs: list[dict[str, Any]],
    known: set[str],
    *,
    backend: str,
    per_hop_limit: int,
    direction: str,
    why_prefix: str = "",
) -> list[Candidate]:
    if direction not in {"refs", "both"}:
        return []
    added: list[Candidate] = []
    kept = 0
    prefix = why_prefix or f"{backend} ref of"
    parent = row.ids.get("doi") or ""
    for ref in refs:
        if per_hop_limit > 0 and kept >= per_hop_limit:
            break
        ref_doi = str(ref.get("doi") or "").strip().lower()
        if not ref_doi:
            continue
        ident = f"doi:{ref_doi}"
        if ident in known:
            continue
        known.add(ident)
        added.append(
            Candidate(
                run_id=row.run_id,
                seed=dict(row.seed),
                hop=row.hop + 1 if row.hop else 1,
                direction="refs",
                ids={"doi": ref_doi},
                biblio={
                    "title": _reference_title(ref.get("title")),
                    "year": ref.get("year"),
                    "authors": [],
                    "venue": "",
                    "type": "article",
                    "cited_by_count": 0,
                    "seed_keys": [f"{row.seed.get('type')}:{row.seed.get('value')}"],
                },
                why=f"{prefix} {parent}".strip(),
                status="new",
                provenance={"backend": backend, "endpoint": backend, "retrieved_at": ""},
                gate=row.gate,
            )
        )
        kept += 1
    return added


def _complete(row: Candidate) -> bool:
    biblio = row.biblio
    return bool(biblio.get("title") and biblio.get("year") and biblio.get("venue") and biblio.get("authors"))


def _fill_empty(row: Candidate, payload: dict[str, Any], *, backend: str) -> int:
    biblio = row.biblio
    filled = 0
    if not biblio.get("title") and payload.get("title"):
        biblio["title"] = payload["title"]
        row.provenance["filled_by"] = backend
        filled += 1
    if not biblio.get("year") and payload.get("year"):
        biblio["year"] = int(payload["year"])
        row.provenance["filled_by"] = backend
        filled += 1
    if not biblio.get("venue") and payload.get("venue"):
        biblio["venue"] = payload["venue"]
        row.provenance["filled_by"] = backend
        filled += 1
    authors = payload.get("authors") or []
    if not biblio.get("authors") and authors:
        biblio["authors"] = [str(name) for name in authors if name]
        row.provenance["filled_by"] = backend
        filled += 1
    return filled


def crossref_work(doi: str, *, email: str = "") -> dict[str, Any] | None:
    import httpx

    params = {"mailto": email} if email else None
    try:
        resp = httpx.get(f"https://api.crossref.org/works/{doi}", params=params, timeout=30)
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            raise FillPaused("crossref")
        resp.raise_for_status()
        message = resp.json().get("message") or {}
    except FillPaused:
        raise
    except (httpx.HTTPError, ValueError):
        return None
    titles = message.get("title") or []
    venues = message.get("container-title") or []
    issued = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = issued[0] if issued else None
    authors = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
        if name:
            authors.append(name)
    return {
        "title": titles[0] if titles else "",
        "year": year,
        "venue": venues[0] if venues else "",
        "authors": authors,
        "references": crossref_references(message),
    }


def crossref_references(message: dict[str, Any]) -> list[dict[str, Any]]:
    """DOI references from a Crossref work. Unstructured citation text is not a title."""
    return [
        {
            "doi": str(ref.get("DOI") or ref.get("doi") or ""),
            "title": _reference_title(ref.get("article-title")),
            "year": ref.get("year"),
        }
        for ref in (message.get("reference") or [])
        if isinstance(ref, dict)
    ]


_S2_MIN_INTERVAL_S = 1.1
_S2_MAX_RETRIES = 5
_S2_BACKOFF_CAP_S = 30.0
_s2_next_ok = 0.0


def _s2_pace() -> None:
    """Keyed Semantic Scholar allows about one request per second."""
    global _s2_next_ok
    wait = _s2_next_ok - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _s2_next_ok = time.monotonic() + _S2_MIN_INTERVAL_S


def _retry_after_s(header: str | None) -> float | None:
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def s2_paper(doi: str, *, cache_dir: Path, api_key: str) -> dict[str, Any] | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{doi.replace('/', '_')}.json"
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            return loaded
    import httpx

    headers = {"x-api-key": api_key} if api_key else None
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    params = {"fields": "title,year,venue,authors,references.externalIds,references.title,references.year"}
    for attempt in range(_S2_MAX_RETRIES + 1):
        _s2_pace()
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=30)
        except (httpx.HTTPError, ValueError):
            if attempt < _S2_MAX_RETRIES:
                time.sleep(min(_S2_BACKOFF_CAP_S, 1.0 * (2**attempt)))
                continue
            return None
        if resp.status_code in (401, 403) and api_key:
            raise ApiKeyRejected("Semantic Scholar API key was rejected")
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = _retry_after_s(resp.headers.get("Retry-After"))
            if wait is not None and wait >= 60:
                raise FillPaused("semanticscholar")
            if attempt < _S2_MAX_RETRIES:
                delay = wait if wait is not None and wait >= 0 else min(_S2_BACKOFF_CAP_S, 1.0 * (2**attempt))
                time.sleep(min(_S2_BACKOFF_CAP_S, delay))
                continue
            raise FillPaused("semanticscholar")
        try:
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        path.write_text(json.dumps(data), encoding="utf-8")
        return data
    raise FillPaused("semanticscholar")


def s2_api_key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()


def _reference_title(value: object) -> str:
    """Structured title only. A citation string stays blank until the work is resolved."""
    text = str(value or "").strip()
    return text if usable_work_title(text) else ""


def _gap_rows(
    rows: list[Candidate],
    only_dois: set[str] | None,
    *,
    expand_neighbors: bool = True,
) -> list[Candidate]:
    """Hop-0 works that still have no outgoing references.

    Neighbours and citing works are not asked. A reference added by an earlier
    backend closes the gap for the next one. When this crawl is not hopping,
    only an incomplete hit is asked, and only so its own empty fields can be
    filled.
    """
    pending = [
        row
        for row in rows
        if row.hop == 0
        and row.direction != "cites"
        and (row.ids.get("doi") or "")
        and row.status != "error"
        and _wanted(row, only_dois)
        and not _has_outgoing(row, rows)
    ]
    if expand_neighbors:
        return pending
    return [row for row in pending if not _complete(row)]


def _raise_paused(added: list[Candidate], remaining: list[str], cause: BaseException) -> NoReturn:
    raise FillPaused("europepmc", remaining, added) from cause


def _has_outgoing(row: Candidate, rows: list[Candidate]) -> bool:
    doi = (row.ids.get("doi") or "").lower()
    if not doi:
        return False
    needle = f"ref of {doi}"
    return any(needle in (child.why or "").lower() for child in rows if child is not row)


def fill_payload_backend(
    rows: list[Candidate],
    getter: CrossrefGet,
    *,
    backend: str,
    per_hop_limit: int,
    direction: str,
    tally: Any = None,
    only_dois: set[str] | None = None,
    expand_neighbors: bool = True,
) -> list[Candidate]:
    added: list[Candidate] = []
    known = {row.identity for row in rows if row.identity}
    pending = _gap_rows(rows, only_dois, expand_neighbors=expand_neighbors)
    if tally is not None and pending:
        tally.stage = backend
        tally.track(len(pending))
    for row in pending:
        doi = row.ids.get("doi") or ""
        if tally is not None:
            tally.searches += 1
        try:
            payload = getter(doi)
        except FillPaused as exc:
            raise FillPaused(backend, _remaining_dois(pending, row)) from exc
        if not payload:
            if tally is not None:
                tally.advance(1)
            continue
        if payload.get("cached_pdf"):
            row.biblio["cached_pdf"] = str(payload["cached_pdf"])
        cached = str(payload.get("cached_pdf") or "")
        if cached:
            row.biblio["cached_pdf"] = cached
        if tally is not None:
            tally.fields += _fill_empty(row, payload, backend=backend)
            tally.advance(1)
        else:
            _fill_empty(row, payload, backend=backend)
        new_rows = (
            _neighbor_rows(
                row,
                _ref_dicts(payload),
                known,
                backend=backend,
                per_hop_limit=per_hop_limit,
                direction=direction,
            )
            if expand_neighbors
            else []
        )
        if tally is not None and backend == "europepmc":
            tally.papers += len(new_rows)
        added.extend(new_rows)
    return added


def fill_europepmc(
    rows: list[Candidate],
    *,
    cache_dir: Path,
    per_hop_limit: int,
    direction: str,
    tally: Any = None,
    only_dois: set[str] | None = None,
    expand_neighbors: bool = True,
) -> list[Candidate]:
    """Batch Europe PMC over hop-0 works that still have no outgoing references.

    A spread of that queue that misses the index skips the rest.
    """
    from .europepmc import BATCH_SIZE, PROBE_SIZE, cached_payload, lookup_dois, spread_dois

    pending = _gap_rows(rows, only_dois, expand_neighbors=expand_neighbors)
    if tally is not None and pending:
        tally.stage = "europepmc"
        tally.track(len(pending))
    if not pending:
        return []
    added: list[Candidate] = []
    known = {row.identity for row in rows if row.identity}
    uncached: list[Candidate] = []
    for row in pending:
        hit, payload = cached_payload(row.ids.get("doi") or "", cache_dir)
        if not hit:
            uncached.append(row)
            continue
        added.extend(
            _apply_europepmc_row(
                row,
                payload,
                known=known,
                per_hop_limit=per_hop_limit,
                direction=direction,
                tally=tally,
                expand_neighbors=expand_neighbors,
            )
        )
    if not uncached:
        return added
    probe = spread_dois([row.ids.get("doi") or "" for row in uncached], PROBE_SIZE)
    probe_set = {doi.lower() for doi in probe}
    try:
        found = lookup_dois(probe, cache_dir=cache_dir)
    except FillPaused as exc:
        _raise_paused(added, _remaining_dois(uncached, uncached[0]), exc)
    if tally is not None:
        tally.searches += len(probe)
    in_index = sum(1 for payload in found.values() if payload)
    for row in uncached:
        doi = (row.ids.get("doi") or "").lower()
        if doi not in probe_set:
            continue
        added.extend(
            _apply_europepmc_row(
                row,
                found.get(doi),
                known=known,
                per_hop_limit=per_hop_limit,
                direction=direction,
                tally=tally,
                expand_neighbors=expand_neighbors,
            )
        )
    rest = [row for row in uncached if (row.ids.get("doi") or "").lower() not in probe_set]
    if in_index == 0 and rest:
        if tally is not None:
            tally.emit(f"europepmc · {len(probe)} searched · 0 in index · skipped {len(rest)}")
            tally.advance(len(rest))
        return added
    for index in range(0, len(rest), BATCH_SIZE):
        chunk = rest[index : index + BATCH_SIZE]
        try:
            found = lookup_dois([row.ids.get("doi") or "" for row in chunk], cache_dir=cache_dir)
        except FillPaused as exc:
            _raise_paused(added, _remaining_dois(uncached, chunk[0]), exc)
        if tally is not None:
            tally.searches += len(chunk)
        for row in chunk:
            doi = (row.ids.get("doi") or "").lower()
            added.extend(
                _apply_europepmc_row(
                    row,
                    found.get(doi),
                    known=known,
                    per_hop_limit=per_hop_limit,
                    direction=direction,
                    tally=tally,
                    expand_neighbors=expand_neighbors,
                )
            )
    return added


def _apply_europepmc_row(
    row: Candidate,
    payload: dict[str, Any] | None,
    *,
    known: set[str],
    per_hop_limit: int,
    direction: str,
    tally: Any,
    expand_neighbors: bool = True,
) -> list[Candidate]:
    if tally is not None:
        tally.advance(1)
    if not payload:
        return []
    if tally is not None:
        tally.fields += _fill_empty(row, payload, backend="europepmc")
    else:
        _fill_empty(row, payload, backend="europepmc")
    new_rows = (
        _neighbor_rows(
            row,
            _ref_dicts(payload),
            known,
            backend="europepmc",
            per_hop_limit=per_hop_limit,
            direction=direction,
        )
        if expand_neighbors
        else []
    )
    if tally is not None:
        tally.papers += len(new_rows)
    return new_rows


def run_fill_pass(
    rows: list[Candidate],
    backends: tuple[str, ...],
    *,
    crossref_getter: CrossrefGet | None,
    s2_getter: S2Get | None,
    europepmc_getter: CrossrefGet | None,
    pdf_getter: CrossrefGet | None,
    per_hop_limit: int,
    direction: str,
    tally: Any = None,
    europepmc_cache: Path | None = None,
    expand_neighbors: bool = True,
) -> dict[str, list[str]]:
    """Walk citation backends in order. A pause continues the pass, then one retry."""
    paused: dict[str, list[str]] = {}
    order = [name for name in backends if name in {"crossref", "semanticscholar", "europepmc", "pdf"}]

    def once(names: list[str], *, retry: bool) -> None:
        for name in names:
            only = {doi.lower() for doi in paused.get(name, [])} if retry else None
            if retry and not only:
                continue
            if name == "europepmc" and europepmc_cache is not None:
                try:
                    added = fill_europepmc(
                        rows,
                        cache_dir=europepmc_cache,
                        per_hop_limit=per_hop_limit,
                        direction=direction,
                        tally=tally,
                        only_dois=only,
                        expand_neighbors=expand_neighbors,
                    )
                except FillPaused as exc:
                    rows.extend(exc.added)
                    paused[exc.backend] = list(exc.remaining)
                    continue
                rows.extend(added)
                paused.pop(name, None)
                continue
            getter = {
                "crossref": crossref_getter,
                "semanticscholar": s2_getter,
                "europepmc": europepmc_getter,
                "pdf": pdf_getter,
            }[name]
            if getter is None:
                continue
            try:
                if name == "crossref":
                    added = fill_crossref(
                        rows,
                        getter,
                        per_hop_limit=per_hop_limit,
                        direction=direction,
                        tally=tally,
                        only_dois=only,
                        expand_neighbors=expand_neighbors,
                    )
                elif name == "semanticscholar":
                    added = fill_semanticscholar(
                        rows,
                        getter,
                        per_hop_limit=per_hop_limit,
                        direction=direction,
                        tally=tally,
                        only_dois=only,
                        expand_neighbors=expand_neighbors,
                    )
                else:
                    added = fill_payload_backend(
                        rows,
                        getter,
                        backend=name,
                        per_hop_limit=per_hop_limit,
                        direction=direction,
                        tally=tally,
                        only_dois=only,
                        expand_neighbors=expand_neighbors,
                    )
            except FillPaused as exc:
                paused[exc.backend] = list(exc.remaining)
                continue
            rows.extend(added)
            paused.pop(name, None)

    once(order, retry=False)
    if paused:
        once([name for name in order if name in paused], retry=True)
    return paused
