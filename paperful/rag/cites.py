"""In-library citation hops from on-disk snowball graphs. No network."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from .ledger import Ledger


def _graphs(state_dir: Path) -> list[Path]:
    root = state_dir / "snowball"
    if not root.is_dir():
        return []
    return sorted(root.glob("*/citation_graph.json"))


def _doi_index(ledger: Ledger) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in ledger.rows():
        doi = (row.doi or "").strip().lower()
        if doi:
            out[doi] = row.key
    return out


def _load_graph(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def neighbor_keys(
    cfg: Config,
    from_keys: set[str],
    ledger: Ledger,
) -> tuple[set[str], str]:
    """Item keys linked to ``from_keys`` in local citation graphs.

    Returns ``(keys, skip_reason)``. ``skip_reason`` is set when nothing
    could be read; it is empty when a graph existed even if no neighbours
    fell inside the ledger.
    """
    if not from_keys:
        return set(), "no local graph"
    paths = _graphs(cfg.state_dir)
    if not paths:
        return set(), "no local graph"
    dois = _doi_index(ledger)
    node_to_key: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    for path in paths:
        data = _load_graph(path)
        for node in data.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id") or "").strip()
            if not nid:
                continue
            key = str(node.get("item_key") or "").strip()
            if not key:
                doi = str(node.get("doi") or "").strip().lower()
                key = dois.get(doi, "")
            if key:
                node_to_key[nid] = key
        for edge in data.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("source") or "").strip()
            tgt = str(edge.get("target") or "").strip()
            if src and tgt:
                edges.append((src, tgt))
    if not node_to_key:
        return set(), "no local graph"
    wanted_nodes = {nid for nid, key in node_to_key.items() if key in from_keys}
    found: set[str] = set()
    for src, tgt in edges:
        if src in wanted_nodes:
            key = node_to_key.get(tgt, "")
            if key and key not in from_keys:
                found.add(key)
        if tgt in wanted_nodes:
            key = node_to_key.get(src, "")
            if key and key not in from_keys:
                found.add(key)
    known = set(ledger.keys())
    return found & known, ""
