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
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..resolve import normalize_doi
from .candidate import Candidate
from .expand import select_works_by_citations
from .map_categories import (
    CategoryDef,
    categories_for,
    legend_for,
    resolve_catalog,
    study_designs_of,
)
from .openalex import (
    OpenAlexBudgetExceeded,
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
    watch_seen: set[str] | None = None,
    compare_ids: set[str] | None = None,
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """JSON map for the Discover canvas. Caps nodes; edges stay inside that set."""
    year_now = now_year if now_year is not None else datetime.now(timezone.utc).year
    catalog = resolve_catalog(enabled=map_categories, custom_defs=map_category_defs)
    similar = is_similarity_queue(rows)
    chosen = (
        # The Similar map is already capped by [similar_map].nodes (plus the origin).
        select_similar_nodes(rows, max_nodes=max(max_nodes, len(rows)) if max_nodes > 0 else 0)
        if similar
        else select_nodes(rows, focus=focus, max_nodes=max_nodes)
    )
    counts = [_cited(row) for row in chosen if row.hop != 0]
    threshold = CITATION_FLOOR if not counts else max(CITATION_FLOOR, _median(counts))
    recent_from = year_now - RECENT_YEARS
    nodes = [
        _node(
            row,
            now_year=year_now,
            threshold=threshold,
            watch_seen=watch_seen,
            compare_ids=compare_ids,
            catalog=catalog,
            out_dir=out_dir,
        )
        for row in chosen
    ]
    similar_report: dict[str, Any] | None = None
    if similar:
        edges = _sim_edges(chosen)
        _attach_origin_paths(chosen, nodes, edges)
        similar_report = _similar_report(rows)
    else:
        edges = _edges(chosen)
    graph = {
        "v": 1,
        "schema": SCHEMA,
        "run_id": run_id,
        "layout": "similarity" if similar else "citation",
        "threshold": {
            "highly_cited": threshold,
            "recent_from_year": recent_from,
        },
        "thresholds": {
            "recent_years": RECENT_YEARS,
            "citation_floor": CITATION_FLOOR,
            "highly_cited": threshold,
            "recent_from_year": recent_from,
        },
        "category_legend": legend_for(catalog),
        "triage": build_triage(nodes),
        "nodes": nodes,
        "edges": edges,
    }
    if similar_report is not None:
        on_map = {node["id"] for node in nodes}
        report = dict(similar_report)
        for key in ("prior", "derivative"):
            items = report.get(key)
            report[key] = [
                item for item in items if isinstance(item, dict) and item.get("id") not in on_map
            ] if isinstance(items, list) else []
        graph["similar"] = report
    return graph


def _similar_report(rows: list[Candidate]) -> dict[str, Any]:
    """Run report saved on the origin row (settings, source, warnings, extras)."""
    for row in rows:
        report = row.biblio.get("similar_report")
        if row.hop == 0 and isinstance(report, dict):
            return report
    return {}


def write_graph(
    dest: Path,
    rows: list[Candidate],
    *,
    run_id: str,
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    out_dir: Path | None = None,
) -> Path:
    graph = build_graph(
        rows,
        run_id=run_id,
        map_categories=map_categories,
        map_category_defs=map_category_defs,
        out_dir=out_dir,
    )
    return write_graph_file(dest, graph)


def write_graph_file(dest: Path, graph: dict[str, Any]) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / GRAPH_FILE
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _summary_map_settings(
    dest: Path,
) -> tuple[list[str] | None, list[dict[str, Any]] | None]:
    """Read map category knobs persisted on the run summary, if any."""
    path = dest / "summary.json"
    if not path.is_file():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(raw, dict):
        return None, None
    cats = raw.get("map_categories")
    defs = raw.get("map_category_defs")
    cat_out = [str(item) for item in cats] if isinstance(cats, list) else None
    def_out = [dict(item) for item in defs if isinstance(item, dict)] if isinstance(defs, list) else None
    return cat_out, def_out


def graph_for_run(
    state_dir: Path,
    run_id: str,
    *,
    watch_seen: set[str] | None = None,
    compare_ids: set[str] | None = None,
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Rebuild the map from the queue on disk."""
    from .queue import load_queue

    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    try:
        dest, rows = load_queue(state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    # Run summary wins so a profile-saved map_categories set sticks on that queue.
    summary_cats, summary_defs = _summary_map_settings(dest)
    graph = build_graph(
        rows,
        run_id=run_id,
        watch_seen=watch_seen,
        compare_ids=compare_ids,
        map_categories=summary_cats if summary_cats is not None else map_categories,
        map_category_defs=summary_defs if summary_defs is not None else map_category_defs,
        out_dir=out_dir,
    )
    write_graph_file(dest, graph)
    return graph


def repair_queue_links(
    state_dir: Path,
    run_id: str,
    client: OpenAlexClient,
    *,
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Re-link queue rows to hop-0 seeds from OpenAlex refs/cites (Keep unchanged)."""
    from .queue import load_queue

    if not valid_run_id(run_id):
        raise CitationGraphError("Unknown run.")
    try:
        dest, rows = load_queue(state_dir, run_id)
    except FileNotFoundError as exc:
        raise CitationGraphError("No queue for that run.") from exc
    if is_similarity_queue(rows):
        raise CitationGraphError("Repair links is for citation maps; a Similar map has no citation links.")
    by_id = {row.identity: row for row in rows}
    seeds = [row for row in rows if row.hop == 0]
    if not seeds:
        raise CitationGraphError("This queue has no seeds to repair from.")
    for seed_row in seeds:
        try:
            work = _load_work(client, seed_row)
        except OpenAlexBudgetExceeded:
            raise
        except (OpenAlexError, httpx.HTTPError) as exc:
            raise CitationGraphError("OpenAlex could not look up a seed.") from exc
        if work is None:
            continue
        parent = seed_row.identity
        ref_ids = referenced_ids(work, REF_FETCH_CAP)
        if ref_ids:
            for child in client.works_by_ids(ref_ids):
                cid = work_node_id(child)
                if cid in by_id:
                    remember_link(by_id[cid], parent, "refs")
        oa = short_id(str(work.get("id") or "")) or (seed_row.ids.get("openalex") or "")
        if oa:
            try:
                citing = client.works_citing(oa, limit=NEIGHBOR_CAP, sort="cited_by_count:desc")
            except OpenAlexBudgetExceeded:
                raise
            except (OpenAlexError, httpx.HTTPError) as exc:
                raise CitationGraphError("OpenAlex could not repair cited-by links.") from exc
            for child in citing:
                cid = work_node_id(child)
                if cid in by_id:
                    remember_link(by_id[cid], parent, "cites")
    path = dest / "candidates.jsonl"
    path.write_text(
        "".join(json.dumps(row.to_dict(), ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    graph = build_graph(
        rows,
        run_id=run_id,
        map_categories=map_categories,
        map_category_defs=map_category_defs,
        out_dir=out_dir,
    )
    write_graph_file(dest, graph)
    return graph


def library_halo(
    client: OpenAlexClient,
    target: Candidate,
    library_dois: set[str],
    *,
    cap: int = 15,
) -> dict[str, Any]:
    """OpenAlex neighbours that are already in the library (session overlay, not queue)."""
    if not library_dois:
        return {"nodes": [], "edges": []}
    try:
        work = _load_work(client, target)
    except OpenAlexBudgetExceeded:
        raise
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not look up this paper.") from exc
    if work is None:
        raise CitationGraphError("OpenAlex has no record for this paper.")
    focus_id = target.identity
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_ghost(child: dict[str, Any], direction: str) -> None:
        doi = (normalize_doi(str(child.get("doi") or "")) or "").lower()
        if not doi or doi not in library_dois:
            return
        gid = f"doi:{doi}"
        if gid in seen or gid == focus_id:
            return
        seen.add(gid)
        year = child.get("publication_year")
        cited = int(child.get("cited_by_count") or 0)
        nodes.append(
            {
                "id": gid,
                "title": str(child.get("display_name") or ""),
                "year": year,
                "cited_by_count": cited,
                "role": "other",
                "seed": False,
                "in_library": True,
                "ghost": True,
                "keep": None,
                "hop": None,
                "occasional": False,
                "doi": doi,
                "openalex": short_id(str(child.get("id") or "")),
                "why": "Already in your library",
                "first_author": "",
            }
        )
        if direction == "refs":
            edges.append({"source": focus_id, "target": gid, "direction": "refs"})
        else:
            edges.append({"source": gid, "target": focus_id, "direction": "cites"})
        if len(nodes) >= cap:
            return

    ref_ids = referenced_ids(work, REF_FETCH_CAP)
    for child in client.works_by_ids(ref_ids) if ref_ids else []:
        add_ghost(child, "refs")
        if len(nodes) >= cap:
            break
    if len(nodes) < cap:
        oa = short_id(str(work.get("id") or "")) or (target.ids.get("openalex") or "")
        if oa:
            citing = client.works_citing(oa, limit=NEIGHBOR_CAP, sort="cited_by_count:desc")
            for child in citing:
                add_ghost(child, "cites")
                if len(nodes) >= cap:
                    break
    return {"nodes": nodes, "edges": edges}


def build_triage(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read-first ordering for the map sidebar (deterministic, no model)."""

    def bucket(node: dict[str, Any]) -> tuple[int, int]:
        if node.get("keep") is False:
            return (4, 0)
        if node.get("in_library"):
            return (4, 0)
        role = str(node.get("role") or "other")
        if role == "influential":
            return (0, -(node.get("cited_by_count") or 0))
        if role == "emerging":
            return (1, -(node.get("cited_by_count") or 0))
        if role == "foundational":
            return (2, -(node.get("cited_by_count") or 0))
        return (3, -(node.get("cited_by_count") or 0))

    def reason(node: dict[str, Any]) -> str:
        if node.get("keep") is False:
            return "Skipped on this queue"
        if node.get("in_library"):
            return "Already in your library"
        role = str(node.get("role") or "other")
        if role == "influential":
            return "Recent and highly cited — read while it is influential"
        if role == "emerging":
            return "Recent with fewer citations — may be emerging"
        if role == "foundational":
            return "Older and highly cited — likely foundational"
        return "Lower priority on this map"

    candidates = [n for n in nodes if not n.get("seed")]
    ordered = sorted(candidates, key=bucket)
    out: list[dict[str, Any]] = []
    for rank, node in enumerate(ordered, start=1):
        out.append({"id": node["id"], "rank": rank, "reason": reason(node)})
    return out


def path_between(
    edges: list[dict[str, str]],
    start: str,
    end: str,
    *,
    max_len: int = 4,
) -> list[dict[str, str]] | None:
    """Shortest citation path inside the current graph (undirected BFS)."""
    if start == end:
        return []
    if not start or not end:
        return None
    adj: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for edge in edges:
        a, b = edge.get("source"), edge.get("target")
        if not a or not b:
            continue
        adj.setdefault(a, []).append((b, edge))
        adj.setdefault(b, []).append((a, edge))
    queue: deque[tuple[str, list[dict[str, str]]]] = deque([(start, [])])
    visited = {start}
    while queue:
        node, path_edges = queue.popleft()
        if len(path_edges) > max_len:
            continue
        for nxt, edge in adj.get(node, []):
            if nxt in visited:
                continue
            step = list(path_edges) + [edge]
            if nxt == end:
                return step
            visited.add(nxt)
            queue.append((nxt, step))
    return None


def expand_queue(
    state_dir: Path,
    run_id: str,
    node_id: str,
    direction: str,
    client: OpenAlexClient,
    *,
    now_year: int | None = None,
    map_categories: list[str] | tuple[str, ...] | None = None,
    map_category_defs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
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
    if is_similarity_queue(rows):
        raise CitationGraphError(
            "Expand is for citation maps. Use New Similar map from this paper instead."
        )
    target = next((row for row in rows if row.identity == target_id), None)
    if target is None:
        raise CitationGraphError("That paper is not in this queue.")
    try:
        work = _load_work(client, target)
    except OpenAlexBudgetExceeded:
        raise
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not look up this paper.") from exc
    if work is None:
        raise CitationGraphError("OpenAlex has no record for this paper.")
    try:
        added = _neighbours(client, work, target, side)
    except OpenAlexBudgetExceeded:
        raise
    except (OpenAlexError, httpx.HTTPError) as exc:
        raise CitationGraphError("OpenAlex could not expand this paper.") from exc
    merged = _dedupe(list(rows) + added)
    path = dest / "candidates.jsonl"
    path.write_text(
        "".join(json.dumps(row.to_dict(), ensure_ascii=False) + "\n" for row in merged),
        encoding="utf-8",
    )
    graph = build_graph(
        merged,
        run_id=run_id,
        now_year=now_year,
        focus=target_id,
        map_categories=map_categories,
        map_category_defs=map_category_defs,
    )
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


def select_nodes(
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


def is_similarity_queue(rows: list[Candidate]) -> bool:
    """True when rows came from a Similar explore (they carry ``sim_links``)."""
    return any(isinstance(row.biblio.get("sim_links"), list) for row in rows)


def _similarity(row: Candidate) -> float:
    try:
        return float(row.biblio.get("similarity") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def select_similar_nodes(rows: list[Candidate], *, max_nodes: int) -> list[Candidate]:
    """Seed first, then most similar. Citation count breaks ties."""
    ranked = sorted(
        (row for row in rows if row.identity),
        key=lambda row: (row.hop == 0, _similarity(row), _cited(row)),
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


def _sim_edges(rows: list[Candidate]) -> list[dict[str, Any]]:
    """Undirected similarity edges inside ``rows``. ``weight`` is scaled to 0-1."""
    by_id = {row.identity for row in rows}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        raw = row.biblio.get("sim_links")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            peer = str(item.get("peer") or "").strip()
            if not peer or peer == row.identity or peer not in by_id:
                continue
            a, b = sorted((row.identity, peer))
            if (a, b) in found:
                continue
            try:
                score = float(item.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if score <= 0:
                continue
            found[(a, b)] = {
                "source": a,
                "target": b,
                "direction": "similar",
                "score": round(score, 4),
                "shared_refs": int(item.get("shared_refs") or 0),
                "co_citing": int(item.get("co_citing") or 0),
            }
    top = max((edge["score"] for edge in found.values()), default=0.0)
    edges = sorted(found.values(), key=lambda edge: (edge["source"], edge["target"]))
    for edge in edges:
        edge["weight"] = round(edge["score"] / top, 4) if top else 0.0
    return edges


def _attach_origin_paths(
    rows: list[Candidate],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Give each node its similarity score and strongest path to the seed."""
    from .similarity_map import origin_paths

    seed = next((row.identity for row in rows if row.hop == 0), "")
    paths = origin_paths(edges, seed) if seed else {}
    scores = {row.identity: _similarity(row) for row in rows}
    for node in nodes:
        node["similarity"] = round(scores.get(node["id"], 0.0), 4)
        node["origin_path"] = [
            {"source": edge["source"], "target": edge["target"], "direction": edge["direction"]}
            for edge in paths.get(node["id"], [])
        ]


def _node(
    row: Candidate,
    *,
    now_year: int,
    threshold: int,
    watch_seen: set[str] | None = None,
    compare_ids: set[str] | None = None,
    catalog: list[CategoryDef] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    year = _year(row)
    cited = _cited(row)
    kind = role_for(year, cited, now_year=now_year, threshold=threshold)
    authors = row.biblio.get("authors") or []
    first = ""
    if isinstance(authors, list) and authors:
        first = str(authors[0] or "")
    designs = study_designs_of(row.biblio)
    active = catalog if catalog is not None else resolve_catalog()
    in_library = row.status == "exists" or bool(row.exists_match)
    match = row.exists_match if isinstance(row.exists_match, dict) else {}
    item_key = str(match.get("item_key") or "").strip()
    op = row.operator if isinstance(row.operator, dict) else {}
    staged_tags = [str(t) for t in (op.get("tags") or []) if str(t).strip()]
    staged_note = str(op.get("note") or "").strip()
    staged_collection = str(op.get("collection") or "").strip()
    has_pdf: bool | None = None
    if out_dir is not None and item_key:
        try:
            from ..mirror import pdf_for_key

            has_pdf = pdf_for_key(out_dir, item_key) is not None
        except Exception:
            has_pdf = None
    payload: dict[str, Any] = {
        "id": row.identity,
        "title": str(row.biblio.get("title") or ""),
        "year": year,
        "cited_by_count": cited,
        "role": kind,
        "seed": row.hop == 0,
        "in_library": in_library,
        "item_key": item_key,
        "has_pdf": has_pdf,
        "keep": row.keep,
        "hop": row.hop,
        "occasional": kind == "other" and row.hop != 0,
        "doi": str(row.ids.get("doi") or ""),
        "openalex": str(row.ids.get("openalex") or ""),
        "why": str(row.why or ""),
        "first_author": first,
        "study_designs": designs,
        "categories": categories_for(row.biblio, active),
        "tags": staged_tags,
        "note": staged_note,
        "target_collection": staged_collection,
        "staged": bool(staged_tags or staged_note or staged_collection),
    }
    if watch_seen is not None:
        payload["watch_new"] = row.identity not in watch_seen
        payload["watch_seen"] = row.identity in watch_seen
    if compare_ids is not None:
        payload["compare_new"] = row.identity not in compare_ids
    return payload


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
