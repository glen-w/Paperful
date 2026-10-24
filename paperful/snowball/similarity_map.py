"""Similarity map: place papers by shared citations, not by who cites whom.

Two papers count as similar when they cite the same works (bibliographic
coupling) or are cited together by the same works (co-citation). Each measure
is a Salton cosine, and the score is their weighted mean, from 0 to 1
(``coupling_weight`` 0.5 by default). The map keeps the
works most similar to the seed, links each one to its strongest peers, and
records the strongest route from every node back to the seed.

This module only scores and lays out. It never calls OpenAlex. The pool comes
from ``explore.start_similar_explore``. Co-citation counts only the citing
works in that pool, so it is a sample, not the whole corpus.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Iterable

from .openalex import short_id

# Papers kept on the map besides the seed.
SIM_NODES = 40
# Strongest peers each node keeps. The union of these lists gives the edges.
SIM_K = 4
# Peers below this similarity are not linked.
SIM_MIN = 0.02
# Added to every step so a long chain of weak links loses to a short strong one.
STEP_COST = 0.1


def ref_set(work: dict[str, Any]) -> set[str]:
    """OpenAlex short ids this work cites."""
    out: set[str] = set()
    for ref in work.get("referenced_works") or []:
        sid = short_id(str(ref))
        if sid:
            out.add(sid)
    return out


def citer_index(refs: dict[str, set[str]]) -> dict[str, set[str]]:
    """Invert ``{work: refs}`` into ``{cited work: works in the pool that cite it}``."""
    index: dict[str, set[str]] = {}
    for citer, cited in refs.items():
        for sid in cited:
            if sid != citer:
                index.setdefault(sid, set()).add(citer)
    return index


def _cosine(a: set[str], b: set[str]) -> tuple[float, int]:
    if not a or not b:
        return 0.0, 0
    shared = len(a & b)
    if not shared:
        return 0.0, 0
    return shared / math.sqrt(len(a) * len(b)), shared


def similarity(
    a: str,
    b: str,
    refs: dict[str, set[str]],
    citers: dict[str, set[str]],
    coupling_weight: float = 0.5,
) -> tuple[float, int, int]:
    """``(score, shared refs, co-citing works)`` for two works in the pool.

    ``coupling_weight`` 1.0 scores shared references only; 0.0 co-citation only.
    """
    if a == b:
        return 0.0, 0, 0
    w = max(0.0, min(1.0, float(coupling_weight)))
    coupling, shared_refs = _cosine(refs.get(a, set()), refs.get(b, set()))
    cocite, shared_citers = _cosine(citers.get(a, set()), citers.get(b, set()))
    return w * coupling + (1.0 - w) * cocite, shared_refs, shared_citers


def score_to_seed(
    seed: str,
    refs: dict[str, set[str]],
    citers: dict[str, set[str]],
    candidates: Iterable[str],
    *,
    coupling_weight: float = 0.5,
) -> dict[str, tuple[float, int, int]]:
    """Similarity to the seed for each candidate. Works scoring zero are left out."""
    out: dict[str, tuple[float, int, int]] = {}
    for oa in candidates:
        if oa == seed or oa in out:
            continue
        hit = similarity(seed, oa, refs, citers, coupling_weight)
        if hit[0] > 0:
            out[oa] = hit
    return out


def pick_top(
    scores: dict[str, tuple[float, int, int]],
    *,
    limit: int = SIM_NODES,
    cited_by: dict[str, int] | None = None,
) -> list[str]:
    """Most similar first. Citation count breaks ties."""
    counts = cited_by or {}
    ranked = sorted(scores, key=lambda oa: (-scores[oa][0], -counts.get(oa, 0), oa))
    return ranked[: max(0, limit)]


def pairwise_links(
    ids: list[str],
    refs: dict[str, set[str]],
    citers: dict[str, set[str]],
    *,
    k: int = SIM_K,
    floor: float = SIM_MIN,
    coupling_weight: float = 0.5,
) -> dict[tuple[str, str], tuple[float, int, int]]:
    """Undirected edges: each node's ``k`` strongest peers at or above ``floor``.

    Keys are sorted id pairs, so an edge both ends picked appears once.
    """
    best: dict[str, list[tuple[float, str]]] = {oa: [] for oa in ids}
    scored: dict[tuple[str, str], tuple[float, int, int]] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            hit = similarity(a, b, refs, citers, coupling_weight)
            if hit[0] < floor or hit[0] <= 0:
                continue
            key = (a, b) if a < b else (b, a)
            scored[key] = hit
            best[a].append((hit[0], b))
            best[b].append((hit[0], a))
    edges: dict[tuple[str, str], tuple[float, int, int]] = {}
    for a, peers in best.items():
        peers.sort(key=lambda item: (-item[0], item[1]))
        for _, b in peers[: max(0, k)]:
            key = (a, b) if a < b else (b, a)
            edges[key] = scored[key]
    return edges


def connect_to_seed(
    seed: str,
    ids: list[str],
    edges: dict[tuple[str, str], tuple[float, int, int]],
    seed_scores: dict[str, tuple[float, int, int]],
) -> None:
    """Add a direct seed edge to any node with no route to the seed."""
    adj: dict[str, set[str]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    reached = {seed}
    stack = [seed]
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, ()):
            if nxt not in reached:
                reached.add(nxt)
                stack.append(nxt)
    for oa in ids:
        if oa == seed or oa in reached or oa not in seed_scores:
            continue
        key = (seed, oa) if seed < oa else (oa, seed)
        edges[key] = seed_scores[oa]
        # Everything this node already reaches is now joined to the seed too.
        stack = [oa]
        reached.add(oa)
        while stack:
            cur = stack.pop()
            for nxt in adj.get(cur, ()):
                if nxt not in reached:
                    reached.add(nxt)
                    stack.append(nxt)


def origin_paths(
    edges: list[dict[str, Any]],
    origin: str,
) -> dict[str, list[dict[str, Any]]]:
    """Strongest route from each node to ``origin`` (Dijkstra).

    A step costs ``1 - weight + STEP_COST``, so strong links are short. The
    result maps node id to the edge dicts on its path, starting at the node and
    ending at the origin. The origin maps to ``[]``. Unreachable nodes are left out.
    """
    adj: dict[str, list[tuple[str, float, dict[str, Any]]]] = {}
    for edge in edges:
        a, b = str(edge.get("source") or ""), str(edge.get("target") or "")
        if not a or not b or a == b:
            continue
        weight = float(edge.get("weight") or 0.0)
        cost = max(0.0, 1.0 - min(weight, 1.0)) + STEP_COST
        adj.setdefault(a, []).append((b, cost, edge))
        adj.setdefault(b, []).append((a, cost, edge))
    if origin not in adj:
        return {origin: []}
    dist: dict[str, float] = {origin: 0.0}
    via: dict[str, tuple[str, dict[str, Any]]] = {}
    heap: list[tuple[float, str]] = [(0.0, origin)]
    while heap:
        d, cur = heapq.heappop(heap)
        if d > dist.get(cur, math.inf):
            continue
        for nxt, cost, edge in adj.get(cur, ()):
            nd = d + cost
            if nd < dist.get(nxt, math.inf) - 1e-12:
                dist[nxt] = nd
                via[nxt] = (cur, edge)
                heapq.heappush(heap, (nd, nxt))
    out: dict[str, list[dict[str, Any]]] = {origin: []}
    for node in dist:
        if node == origin:
            continue
        path: list[dict[str, Any]] = []
        cur = node
        while cur != origin:
            prev, edge = via[cur]
            path.append(edge)
            cur = prev
        out[node] = path
    return out


def prior_works(
    map_ids: list[str],
    refs: dict[str, set[str]],
    *,
    limit: int,
    min_count: int = 2,
) -> list[tuple[str, int]]:
    """Works the map cites most that are not on it: ``[(id, map papers citing it)]``."""
    if limit <= 0:
        return []
    on_map = set(map_ids)
    counts: dict[str, int] = {}
    for oa in map_ids:
        for ref in refs.get(oa, ()):
            if ref not in on_map:
                counts[ref] = counts.get(ref, 0) + 1
    ranked = sorted(
        (oa for oa, n in counts.items() if n >= min_count),
        key=lambda oa: (-counts[oa], oa),
    )
    return [(oa, counts[oa]) for oa in ranked[:limit]]


def derivative_works(
    map_ids: list[str],
    refs: dict[str, set[str]],
    *,
    limit: int,
    min_count: int = 2,
) -> list[tuple[str, int]]:
    """Pool works citing the most map papers, not on the map: ``[(id, map papers cited)]``."""
    if limit <= 0:
        return []
    on_map = set(map_ids)
    counts: dict[str, int] = {}
    for oa, cited in refs.items():
        if oa in on_map:
            continue
        hits = len(cited & on_map)
        if hits >= min_count:
            counts[oa] = hits
    ranked = sorted(counts, key=lambda oa: (-counts[oa], oa))
    return [(oa, counts[oa]) for oa in ranked[:limit]]
