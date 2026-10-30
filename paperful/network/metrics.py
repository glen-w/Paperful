"""Degree (always) plus NetworkX betweenness, constraint, and Gould–Fernandez roles."""

from __future__ import annotations

from collections import Counter
from typing import Any

NETWORKX_HINT = (
    "Install the optional extra: uv sync --extra network  "
    "(or pip install 'paperful[network]')."
)

_ROLES = (
    "coordinator",
    "itinerant",
    "gatekeeper",
    "representative",
    "liaison",
)


def networkx_available() -> bool:
    try:
        import networkx as nx  # noqa: F401
    except ImportError:
        return False
    return True


def require_networkx() -> Any:
    try:
        import networkx as nx
    except ImportError as exc:
        raise RuntimeError(
            "Betweenness, constraint, and brokerage need NetworkX. " + NETWORKX_HINT
        ) from exc
    return nx


def compute_graph_metrics(
    graph: dict[str, Any],
    *,
    partition: str = "none",
    advanced: bool = True,
) -> dict[str, Any]:
    """Per-node metrics. Degree is always filled; SNA extras need NetworkX."""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    ego_id = str((graph.get("ego") or {}).get("id") or "")
    degree = {str(n.get("id") or ""): int(n.get("degree") or 0) for n in nodes}
    weighted: Counter[str] = Counter()
    for edge in edges:
        w = int(edge.get("weight") or 1)
        left = str(edge.get("a") or "")
        right = str(edge.get("b") or "")
        weighted[left] += w
        weighted[right] += w
        degree.setdefault(left, 0)
        degree.setdefault(right, 0)

    betweenness: dict[str, float] = {}
    constraint: dict[str, float] = {}
    advanced_ok = False
    advanced_error = ""
    if advanced:
        try:
            nx = require_networkx()
            g = _to_nx(nx, nodes, edges)
            betweenness = {
                str(k): float(v) for k, v in nx.betweenness_centrality(g).items()
            }
            raw_c = nx.constraint(g) if g.number_of_nodes() else {}
            constraint = {str(k): float(v) for k, v in raw_c.items()}
            advanced_ok = True
        except RuntimeError as exc:
            advanced_error = str(exc)

    part_field = (partition or "none").strip().lower()
    if part_field in {"", "none", "off"}:
        part_field = "none"
    brokerage: dict[str, Any] = {}
    if part_field != "none" and ego_id:
        groups = {
            str(n.get("id") or ""): str(n.get(part_field) or "").strip() or "unknown"
            for n in nodes
        }
        brokerage = gould_fernandez(ego_id, edges, groups)

    per_node = []
    for node in nodes:
        nid = str(node.get("id") or "")
        per_node.append(
            {
                "id": nid,
                "display_name": str(node.get("display_name") or ""),
                "ego": bool(node.get("ego")),
                "degree": int(degree.get(nid) or 0),
                "weighted_degree": int(weighted.get(nid) or 0),
                "betweenness": betweenness.get(nid),
                "constraint": constraint.get(nid),
                "partition": (
                    str(node.get(part_field) or "") if part_field != "none" else ""
                ),
            }
        )

    ego_row = next((row for row in per_node if row["id"] == ego_id), None)
    return {
        "ego_id": ego_id,
        "partition": part_field,
        "advanced": advanced_ok,
        "advanced_error": advanced_error,
        "nodes": len(nodes),
        "edges": len(edges),
        "ego": {
            "degree": (ego_row or {}).get("degree"),
            "weighted_degree": (ego_row or {}).get("weighted_degree"),
            "betweenness": (ego_row or {}).get("betweenness"),
            "constraint": (ego_row or {}).get("constraint"),
            "brokerage": brokerage,
        },
        "brokerage": brokerage,
        "per_node": per_node,
    }


def gould_fernandez(
    ego_id: str,
    edges: list[dict[str, Any]],
    groups: dict[str, str],
) -> dict[str, Any]:
    """Undirected Gould–Fernandez roles on ego's alter pairs.

    Gatekeeper and representative are the same without direction: each mixed
    triad (ego shares a group with exactly one alter) increments both.
    """
    neighbors: set[str] = set()
    tied: set[frozenset[str]] = set()
    for edge in edges:
        left = str(edge.get("a") or "")
        right = str(edge.get("b") or "")
        if not left or not right:
            continue
        tied.add(frozenset({left, right}))
        if left == ego_id:
            neighbors.add(right)
        elif right == ego_id:
            neighbors.add(left)
    alters = sorted(neighbors)
    counts: Counter[str] = Counter()
    ego_g = groups.get(ego_id) or "unknown"
    for i, a in enumerate(alters):
        for b in alters[i + 1 :]:
            ga = groups.get(a) or "unknown"
            gb = groups.get(b) or "unknown"
            role = _role(ego_g, ga, gb)
            counts[role] += 1
            if role == "boundary":
                counts["gatekeeper"] += 1
                counts["representative"] += 1
    total = sum(counts[r] for r in ("coordinator", "itinerant", "liaison", "boundary"))
    return {
        "partition_of_ego": ego_g,
        "alter_pairs": total,
        "open_triads": sum(
            1
            for i, a in enumerate(alters)
            for b in alters[i + 1 :]
            if frozenset({a, b}) not in tied
        ),
        "roles": {role: int(counts.get(role) or 0) for role in _ROLES},
    }


def _role(ego: str, a: str, b: str) -> str:
    if ego == a == b:
        return "coordinator"
    if a == b and ego != a:
        return "itinerant"
    if ego != a and ego != b and a != b:
        return "liaison"
    return "boundary"


def _to_nx(nx: Any, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Any:
    g = nx.Graph()
    for node in nodes:
        nid = str(node.get("id") or "")
        if nid:
            g.add_node(nid)
    for edge in edges:
        left = str(edge.get("a") or "")
        right = str(edge.get("b") or "")
        if left and right:
            g.add_edge(left, right, weight=int(edge.get("weight") or 1))
    return g
