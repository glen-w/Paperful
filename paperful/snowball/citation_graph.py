"""Citation map for one snowball queue.

Nodes are works. Edges are references (the parent cites the neighbour) or
cited-by (the neighbour cites the parent). Roles use year and citation count
so a reading list can be sorted before anyone opens a PDF:

* older + highly cited → foundational
* recent + highly cited → influential
* recent + fewer citations → emerging
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..resolve import normalize_doi
from .candidate import Candidate
from .expand import select_works_by_citations
from .openalex import (
    OpenAlexClient,
    OpenAlexError,
    referenced_ids,
    short_id,
    work_to_candidate,
)

SCHEMA = "paperful.citation_graph.v1"
GRAPH_FILE = "citation_graph.json"
RECENT_YEARS = 5
CITATION_FLOOR = 50
MAX_NODES = 150
NEIGHBOR_CAP = 25
REF_FETCH_CAP = 200
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_SIDES = frozenset({"refs", "cites", "both"})


class CitationGraphError(Exception):
    """The map cannot be built or expanded."""


def valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID.fullmatch((run_id or "").strip()))


def work_node_id(work: dict[str, Any]) -> str:
    """Same identity string as ``Candidate.identity`` (DOI, else OpenAlex)."""
    doi = (normalize_doi(str(work.get("doi") or "")) or "").lower()
    if doi:
        return f"doi:{doi}"
    oa = short_id(str(work.get("id") or ""))
    return f"openalex:{oa}" if oa else ""


def remember_link(row: Candidate, parent_id: str, direction: str) -> None:
    """Record that ``row`` was reached from ``parent_id`` via refs or cites."""
    parent = (parent_id or "").strip()
    side = direction if direction in {"refs", "cites"} else ""
    if not parent or not side or parent == row.identity:
        return
    links = row.biblio.get("graph_links")
    if not isinstance(links, list):
        links = []
        row.biblio["graph_links"] = links
    item = {"parent": parent, "direction": side}
    if item not in links:
        links.append(item)


def merge_graph_links(existing: Candidate, incoming: Candidate) -> None:
    """Keep every citation hop that found this work."""
    for item in incoming.biblio.get("graph_links") or []:
        if not isinstance(item, dict):
            continue
        remember_link(
            existing,
            str(item.get("parent") or ""),
            str(item.get("direction") or ""),
        )


def role_for(year: int | None, cited: int, *, now_year: int, threshold: int) -> str:
    """foundational, influential, emerging, or other."""
    if year is None:
        return "other"
    recent = year >= now_year - RECENT_YEARS
    high = cited >= threshold
    if recent and high:
        return "influential"
    if recent:
        return "emerging"
    if high:
        return "foundational"
    return "other"


def build_graph(
    rows: list[Candidate],
    *,
    run_id: str,
    now_year: int | None = None,
    max_nodes: int = MAX_NODES,
    focus: str | None = None,
) -> dict[str, Any]:
    """JSON map for the Discover canvas. Caps nodes; edges stay inside that set."""
    year_now = now_year if now_year is not None else datetime.now(timezone.utc).year
    chosen = _select_nodes(rows, focus=focus, max_nodes=max_nodes)
    counts = [_cited(row) for row in chosen if row.hop != 0]
    threshold = CITATION_FLOOR if not counts else max(CITATION_FLOOR, _median(counts))
    recent_from = year_now - RECENT_YEARS
    nodes = [_node(row, now_year=year_now, threshold=threshold) for row in chosen]
    edges = _edges(chosen)
    return {
        "v": 1,
        "schema": SCHEMA,
        "run_id": run_id,
        "threshold": {
            "highly_cited": threshold,
            "recent_from_year": recent_from,
        },
        "nodes": nodes,
        "edges": edges,
    }


def write_graph(dest: Path, rows: list[Candidate], *, run_id: str) -> Path:
    graph = build_graph(rows, run_id=run_id)
    return write_graph_file(dest, graph)


def write_graph_file(dest: Path, graph: dict[str, Any]) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / GRAPH_FILE
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def graph_for_run(state_dir: Path, run_id: str) -> dict[str, Any]:
    """Rebuild the map from the queue on disk."""
    from .queue import load_queue

    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    try:
        dest, rows = load_queue(state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    graph = build_graph(rows, run_id=run_id)
    write_graph_file(dest, graph)
    return graph


def expand_queue(
    state_dir: Path,
    run_id: str,
    node_id: str,
    direction: str,
    client: OpenAlexClient,
    *,
    now_year: int | None = None,
) -> dict[str, Any]:
    """One OpenAlex hop from ``node_id``. Merges neighbours into the queue."""
    from .crawl import _dedupe
    from .queue import load_queue

    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    side = (direction or "").strip().lower()
    if side not in _SIDES:
        raise CitationGraphError("Direction must be refs, cites, or both.")
    target_id = (node_id or "").strip()
    if not target_id:
        raise CitationGraphError("Choose a paper to expand.")
    try:
        dest, rows = load_queue(state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    target = next((row for row in rows if row.identity == target_id), None)
    if target is None:
        raise CitationGraphError("That paper is not in this queue.")
    try:
        work = _load_work(client, target)
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not look up this paper.") from exc
    if work is None:
        raise CitationGraphError("OpenAlex has no record for this paper.")
    try:
        added = _neighbours(client, work, target, side)
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not expand this paper.") from exc
    merged = _dedupe(list(rows) + added)
    path = dest / "candidates.jsonl"
    path.write_text(
        "".join(json.dumps(row.to_dict(), ensure_ascii=False) + "\n" for row in merged),
        encoding="utf-8",
    )
    graph = build_graph(merged, run_id=run_id, now_year=now_year, focus=target_id)
    write_graph_file(dest, graph)
    return graph


def _neighbours(
    client: OpenAlexClient,
    work: dict[str, Any],
    target: Candidate,
    side: str,
) -> list[Candidate]:
    parent_id = target.identity
    title = str(target.biblio.get("title") or parent_id)
    added: list[Candidate] = []
    if side in {"refs", "both"}:
        ids = referenced_ids(work, REF_FETCH_CAP)
        children = client.works_by_ids(ids) if ids else []
        children = select_works_by_citations(children, NEIGHBOR_CAP, "most-cited")
        for child in children:
            row = work_to_candidate(
                child,
                run_id=target.run_id,
                seed=dict(target.seed),
                hop=(target.hop or 0) + 1,
                direction="refs",
                why=f"ref of {title}",
                gate=target.gate or "dry-run",
            )
            remember_link(row, parent_id, "refs")
            added.append(row)
    if side in {"cites", "both"}:
        oa = short_id(str(work.get("id") or "")) or (target.ids.get("openalex") or "")
        citing = client.works_citing(
            oa,
            limit=NEIGHBOR_CAP,
            sort="cited_by_count:desc",
        )
        for child in citing:
            row = work_to_candidate(
                child,
                run_id=target.run_id,
                seed=dict(target.seed),
                hop=(target.hop or 0) + 1,
                direction="cites",
                why=f"cites {title}",
                gate=target.gate or "dry-run",
            )
            remember_link(row, parent_id, "cites")
            added.append(row)
    return added


def _load_work(client: OpenAlexClient, target: Candidate) -> dict[str, Any] | None:
    oa = (target.ids.get("openalex") or "").strip()
    if oa:
        found = client.works_by_ids([oa])
        if found:
            return found[0]
    doi = (target.ids.get("doi") or "").strip()
    if doi:
        return client.work_by_doi(doi)
    return None


def _select_nodes(
    rows: list[Candidate],
    *,
    focus: str | None,
    max_nodes: int,
) -> list[Candidate]:
    linked: set[str] = set()
    focus_id = (focus or "").strip()
    if focus_id:
        linked.add(focus_id)
        for row in rows:
            if row.identity == focus_id:
                for link in _links(row):
                    linked.add(link["parent"])
            for link in _links(row):
                if link["parent"] == focus_id:
                    linked.add(row.identity)

    def score(row: Candidate) -> tuple[bool, bool, bool, int]:
        return (
            row.identity in linked,
            row.hop == 0,
            row.keep is True,
            _cited(row),
        )

    ranked = sorted(
        (row for row in rows if row.identity),
        key=score,
        reverse=True,
    )
    chosen: list[Candidate] = []
    seen: set[str] = set()
    limit = max_nodes if max_nodes > 0 else len(ranked)
    for row in ranked:
        if row.identity in seen:
            continue
        seen.add(row.identity)
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen


def _node(row: Candidate, *, now_year: int, threshold: int) -> dict[str, Any]:
    year = _year(row)
    cited = _cited(row)
    kind = role_for(year, cited, now_year=now_year, threshold=threshold)
    authors = row.biblio.get("authors") or []
    first = ""
    if isinstance(authors, list) and authors:
        first = str(authors[0] or "")
    return {
        "id": row.identity,
        "title": str(row.biblio.get("title") or ""),
        "year": year,
        "cited_by_count": cited,
        "role": kind,
        "seed": row.hop == 0,
        "in_library": row.status == "exists" or bool(row.exists_match),
        "keep": row.keep,
        "hop": row.hop,
        "occasional": kind == "other" and row.hop != 0,
        "doi": str(row.ids.get("doi") or ""),
        "openalex": str(row.ids.get("openalex") or ""),
        "why": str(row.why or ""),
        "first_author": first,
    }


def _edges(rows: list[Candidate]) -> list[dict[str, str]]:
    by_id = {row.identity for row in rows}
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: str, target: str, direction: str) -> None:
        if source not in by_id or target not in by_id or source == target:
            return
        key = (source, target, direction)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": source, "target": target, "direction": direction})

    for row in rows:
        for link in _links(row):
            parent = link["parent"]
            direction = link["direction"]
            if direction == "refs":
                add(parent, row.identity, "refs")
            elif direction == "cites":
                add(row.identity, parent, "cites")
    seeds = [row.identity for row in rows if row.hop == 0]
    if len(seeds) == 1:
        parent = seeds[0]
        for row in rows:
            if row.hop < 1 or _links(row):
                continue
            if row.direction == "refs":
                add(parent, row.identity, "refs")
            elif row.direction == "cites":
                add(row.identity, parent, "cites")
    return edges


def _links(row: Candidate) -> list[dict[str, str]]:
    raw = row.biblio.get("graph_links") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        parent = str(item.get("parent") or "").strip()
        direction = str(item.get("direction") or "").strip()
        if parent and direction in {"refs", "cites"}:
            out.append({"parent": parent, "direction": direction})
    return out


def _year(row: Candidate) -> int | None:
    raw = row.biblio.get("year")
    if raw is None or raw == "":
        return None
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    if year < 1000 or year > 3000:
        return None
    return year


def _cited(row: Candidate) -> int:
    raw = row.biblio.get("cited_by_count")
    if raw is None or raw == "":
        raw = row.score
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]
