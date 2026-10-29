"""Collection-scoped OpenAlex citers for keepup (what cites my papers)."""

from __future__ import annotations

from typing import Any, Callable

from rich.console import Console

from .config import Config
from .resolve import normalize_doi
from .snowball.candidate import Candidate
from .snowball.command import SnowballError, _mark_exists, get_backend
from .snowball.local_openalex import store_from_config
from .snowball.openalex import OpenAlexClient, short_id, work_to_candidate
from .snowball.rank import apply_overlap

Lookup = Callable[..., Any]


class KeepupCitesError(SnowballError):
    """User-facing collection-cite failure."""


def _client(cfg: Config, client: Any = None) -> OpenAlexClient:
    if client is not None:
        return client
    return OpenAlexClient(
        email=cfg.email,
        store=store_from_config(cfg),
        store_fail_limit=int(getattr(cfg, "openalex_store_fail_limit", 3) or 3),
    )


def _seed_key(oa_id: str, doi: str) -> str:
    if doi:
        return f"doi:{doi}"
    return f"openalex:{oa_id}"


def _why_line(overlap: int, seed_titles: list[str]) -> str:
    noun = "paper" if overlap == 1 else "papers"
    line = f"cites {overlap} of your {noun}"
    if seed_titles:
        shown = "; ".join(seed_titles[:3])
        line += f" ({shown})"
    return line


def probe_cites(
    cfg: Config,
    *,
    collection: str,
    run_id: str,
    from_created_date: str | None,
    per_seed_limit: int,
    max_candidates: int,
    muted: set[str],
    seen: set[str],
    console: Console,
    client: Any = None,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> tuple[list[Candidate], int]:
    """Return new citing works and how many seeds were polled."""
    dest = collection.strip()
    if not dest:
        raise KeepupCitesError("keepup cites needs a target collection (-C).")
    lib = backend or get_backend(cfg)
    try:
        root = lib.resolve_collection(dest)
        keys = lib.subtree_keys(root)
        items = lib.items_in_scope(keys)
    except Exception as exc:
        raise KeepupCitesError(f"Could not read collection {dest!r}: {exc}") from exc
    dois = sorted({normalize_doi(item.doi) or "" for item in items if item.doi})
    dois = [d for d in dois if d]
    if not dois:
        raise KeepupCitesError(f"No DOIs in collection {dest!r}.")

    oa = _client(cfg, client)
    works = oa.works_by_dois(dois, select="id,doi,display_name,cited_by_count")
    seeds: list[tuple[str, str, str]] = []
    for work in works:
        oa_id = short_id(str(work.get("id") or ""))
        doi = normalize_doi(str(work.get("doi") or "")) or ""
        title = str(work.get("display_name") or "").strip()
        if oa_id:
            seeds.append((oa_id, doi, title))
    if not seeds:
        raise KeepupCitesError(
            f"OpenAlex resolved 0 of {len(dois)} DOIs in {dest!r}."
        )

    by_id: dict[str, Candidate] = {}
    seed_titles: dict[str, list[str]] = {}
    polled = 0
    for oa_id, doi, title in seeds:
        polled += 1
        citing = oa.works_citing(
            oa_id,
            limit=max(1, per_seed_limit),
            from_created_date=from_created_date,
            sort="cited_by_count:desc",
        )
        seed = {"type": "collection", "value": dest}
        key = _seed_key(oa_id, doi)
        for work in citing:
            row = work_to_candidate(
                work,
                run_id=run_id,
                seed=seed,
                hop=1,
                direction="cites",
                why="",
                gate="dry-run",
            )
            row.biblio["seed_keys"] = [key]
            ident = row.identity
            if not ident or ident in muted or ident in seen:
                continue
            existing = by_id.get(ident)
            if existing is None:
                by_id[ident] = row
                seed_titles[ident] = [title] if title else []
            else:
                keys = existing.biblio.setdefault("seed_keys", [])
                for token in row.biblio.get("seed_keys") or []:
                    if token not in keys:
                        keys.append(token)
                titles = seed_titles.setdefault(ident, [])
                if title and title not in titles:
                    titles.append(title)
            if max_candidates and len(by_id) >= max_candidates:
                break
        if max_candidates and len(by_id) >= max_candidates:
            console.print(f"keepup cites · capped at {max_candidates}")
            break

    rows = list(by_id.values())
    apply_overlap(rows)
    for row in rows:
        overlap = int(
            row.biblio.get("overlap")
            or len(row.biblio.get("seed_keys") or [])
            or 1
        )
        row.why = _why_line(overlap, seed_titles.get(row.identity) or [])
        row.keep = True

    if lookup is not None:
        _mark_exists(rows, lookup)
    else:
        try:
            from .snowball.command import _library_lookup

            finder = _library_lookup(lib, scope="library", collection=dest)
            _mark_exists(rows, finder)
        except Exception:
            pass

    proposed = [row for row in rows if row.status == "new"]
    proposed.sort(key=lambda row: row.score, reverse=True)
    if max_candidates and len(proposed) > max_candidates:
        proposed = proposed[:max_candidates]
    return proposed, polled


def baseline_identities(
    cfg: Config,
    *,
    collection: str,
    per_seed_limit: int,
    max_candidates: int,
    console: Console,
    client: Any = None,
    backend: Any = None,
) -> set[str]:
    """Identities currently citing the collection (for first-run seen set)."""
    dest = collection.strip()
    lib = backend or get_backend(cfg)
    try:
        root = lib.resolve_collection(dest)
        keys = lib.subtree_keys(root)
        items = lib.items_in_scope(keys)
    except Exception as exc:
        raise KeepupCitesError(f"Could not read collection {dest!r}: {exc}") from exc
    dois = sorted({normalize_doi(item.doi) or "" for item in items if item.doi})
    dois = [d for d in dois if d]
    oa = _client(cfg, client)
    works = oa.works_by_dois(dois, select="id,doi")
    seen: set[str] = set()
    for work in works:
        oa_id = short_id(str(work.get("id") or ""))
        if not oa_id:
            continue
        citing = oa.works_citing(
            oa_id,
            limit=max(1, per_seed_limit),
            sort="cited_by_count:desc",
        )
        for cited in citing:
            row = work_to_candidate(
                cited,
                run_id="keepup-baseline",
                seed={"type": "collection", "value": dest},
                hop=1,
                direction="cites",
                why="baseline",
                gate="dry-run",
            )
            if row.identity:
                seen.add(row.identity)
            if max_candidates and len(seen) >= max_candidates * 5:
                # Soft cap on baseline size so huge collections stay cheap.
                console.print("keepup cites · baseline soft-capped")
                return seen
    return seen
