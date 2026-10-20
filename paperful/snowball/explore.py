"""Quick OpenAlex citation-map explore (one seed, one auto-expand hop)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import Config
from ..resolve import normalize_doi
from .candidate import Candidate
from .citation_graph import CitationGraphError, expand_queue, work_node_id
from .command import _library_lookup, _mark_exists, get_backend
from .openalex import OpenAlexBudgetExceeded, OpenAlexClient, OpenAlexError, work_to_candidate
from .queue import write_queue

PICK_LIMIT = 8


@dataclass
class ExplorePick:
    id: str
    title: str
    year: int | None
    cited_by_count: int
    doi: str


class ExploreAmbiguous(Exception):
    """Title search returned more than one OpenAlex work."""

    def __init__(self, picks: list[ExplorePick]) -> None:
        self.picks = picks


def _pick_from_work(work: dict[str, Any]) -> ExplorePick:
    year = work.get("publication_year")
    return ExplorePick(
        id=work_node_id(work),
        title=str(work.get("display_name") or "Untitled"),
        year=int(year) if year is not None else None,
        cited_by_count=int(work.get("cited_by_count") or 0),
        doi=normalize_doi(str(work.get("doi") or "")) or "",
    )


def _work_from_node_id(client: OpenAlexClient, node_id: str) -> dict[str, Any]:
    target = (node_id or "").strip()
    if not target:
        raise CitationGraphError("Choose a paper to explore.")
    if target.startswith("doi:"):
        work = client.work_by_doi(target[4:])
        if work is None:
            raise CitationGraphError("OpenAlex has no record for this DOI.")
        return work
    if target.startswith("openalex:"):
        oa = target.split(":", 1)[1].strip()
        if not oa:
            raise CitationGraphError("OpenAlex has no record for this paper.")
        found = client.works_by_ids([oa])
        if not found:
            raise CitationGraphError("OpenAlex has no record for this paper.")
        return found[0]
    raise CitationGraphError("Unknown paper id.")


def resolve_work(
    client: OpenAlexClient,
    *,
    query: str = "",
    node_id: str = "",
) -> dict[str, Any]:
    """Resolve a DOI, unique title search, or explicit map node id to one work."""
    if node_id.strip():
        return _work_from_node_id(client, node_id)
    text = (query or "").strip()
    if not text:
        raise CitationGraphError("Enter a DOI or paper name.")
    doi = normalize_doi(text)
    if doi:
        work = client.work_by_doi(doi)
        if work is None:
            raise CitationGraphError("OpenAlex has no record for this DOI.")
        return work
    try:
        works = client.search(text, limit=PICK_LIMIT, year_from=None, year_to=None)
    except OpenAlexBudgetExceeded:
        raise
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not search for this title.") from exc
    if not works:
        raise CitationGraphError("No OpenAlex hits for that title.")
    if len(works) == 1:
        return works[0]
    raise ExploreAmbiguous([_pick_from_work(item) for item in works])


def _new_explore_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"explore-{stamp}"


def start_explore(
    cfg: Config,
    client: OpenAlexClient,
    *,
    query: str = "",
    node_id: str = "",
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Seed a tiny queue, mark library overlap, expand one both-direction hop."""
    work = resolve_work(client, query=query, node_id=node_id)
    run_id = _new_explore_run_id()
    seed_label = (query or node_id or work_node_id(work)).strip()
    row = work_to_candidate(
        work,
        run_id=run_id,
        seed={"type": "explore", "value": seed_label[:200]},
        hop=0,
        direction="explore",
        why="Explore seed",
        gate="dry-run",
    )
    rows: list[Candidate] = [row]
    try:
        backend = get_backend(cfg)
        finder = _library_lookup(backend, scope="library", collection="")
        _mark_exists(rows, finder)
    except Exception:
        pass
    write_queue(
        cfg.state_dir,
        run_id,
        rows,
        client,
        library_unread=False,
        meta={
            "mode": "explore",
            "map_categories": list(map_categories or ()),
            "map_category_defs": list(map_category_defs or ()),
        },
    )
    try:
        graph = expand_queue(
            cfg.state_dir,
            run_id,
            row.identity,
            "both",
            client,
            focus=row.identity,
            map_categories=map_categories,
            map_category_defs=map_category_defs,
        )
    except OpenAlexBudgetExceeded:
        raise
    except CitationGraphError:
        graph_path = cfg.state_dir / "snowball" / run_id / "citation_graph.json"
        if graph_path.is_file():
            import json

            graph = json.loads(graph_path.read_text(encoding="utf-8"))
        else:
            from .citation_graph import build_graph, write_graph_file

            dest = cfg.state_dir / "snowball" / run_id
            graph = build_graph(
                rows,
                run_id=run_id,
                focus=row.identity,
                map_categories=map_categories,
                map_category_defs=map_category_defs,
            )
            write_graph_file(dest, graph)
    return run_id, graph
