"""Author layer for Discover maps: who wrote the papers on this map.

Authors are keyed by OpenAlex author id, then ORCID, then a last-name +
initial fingerprint, so the same person merges across papers even when one
record lacks an id. Followed people (authorwatch lists) are marked by the
route, which has the config.
"""

from __future__ import annotations

from typing import Any

from .candidate import Candidate

# Names kept on each node for the side panel.
NODE_AUTHOR_CAP = 12


def _key(record: dict[str, Any]) -> str:
    oa = str(record.get("openalex") or "").strip()
    if oa:
        return f"openalex:{oa}"
    orcid = str(record.get("orcid") or "").strip()
    if orcid:
        return f"orcid:{orcid}"
    fp = str(record.get("fingerprint") or "").strip()
    if fp:
        return f"name:{fp}"
    name = str(record.get("display_name") or "").strip().lower()
    return f"name:{name}" if name else ""


def _fingerprint(name: str) -> str:
    parts = [p for p in name.replace(",", " ").split() if p]
    if not parts:
        return ""
    return f"{parts[-1].lower()}|{parts[0][:1].lower()}"


def row_author_records(row: Candidate) -> list[dict[str, Any]]:
    """Author records for a queue row; plain names when no records were saved."""
    raw = row.biblio.get("author_records")
    records = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
    if records:
        return records
    names = row.biblio.get("authors")
    out: list[dict[str, Any]] = []
    if isinstance(names, list):
        for name in names:
            text = str(name or "").strip()
            if text:
                out.append({"display_name": text, "fingerprint": _fingerprint(text)})
    return out


def node_authors(row: Candidate) -> tuple[list[str], list[str]]:
    """Names (capped) and keys for one node."""
    names: list[str] = []
    keys: list[str] = []
    for record in row_author_records(row):
        key = _key(record)
        if not key or key in keys:
            continue
        keys.append(key)
        if len(names) < NODE_AUTHOR_CAP:
            names.append(str(record.get("display_name") or "").strip() or key)
    return names, keys


def author_summary(
    nodes: list[dict[str, Any]],
    rows: list[Candidate],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Top authors on the map: most papers first, then most citations."""
    if limit <= 0:
        return []
    on_map = {node["id"]: node for node in nodes}
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        node = on_map.get(row.identity)
        if node is None:
            continue
        seen: set[str] = set()
        for record in row_author_records(row):
            key = _key(record)
            if not key or key in seen:
                continue
            seen.add(key)
            entry = found.setdefault(
                key,
                {
                    "key": key,
                    "name": "",
                    "openalex": "",
                    "orcid": "",
                    "count": 0,
                    "citations": 0,
                    "node_ids": [],
                },
            )
            entry["name"] = entry["name"] or str(record.get("display_name") or "").strip()
            entry["openalex"] = entry["openalex"] or str(record.get("openalex") or "").strip()
            entry["orcid"] = entry["orcid"] or str(record.get("orcid") or "").strip()
            entry["count"] += 1
            entry["citations"] += int(node.get("cited_by_count") or 0)
            entry["node_ids"].append(row.identity)
    ranked = sorted(
        found.values(),
        key=lambda e: (-e["count"], -e["citations"], e["name"].lower(), e["key"]),
    )
    return [e for e in ranked if e["name"]][:limit]


def followed_keys(cfg: Any) -> set[str]:
    """Author keys for everyone on any authorwatch list."""
    from ..authorwatch import load_people

    root = cfg.state_dir / "authorwatch"
    keys: set[str] = set()
    if not root.is_dir():
        return keys
    for folder in root.iterdir():
        if not (folder / "watch.json").is_file():
            continue
        try:
            people = load_people(cfg, folder.name)
        except Exception:
            continue
        for person in people:
            if person.openalex:
                keys.add(f"openalex:{person.openalex}")
            if person.orcid:
                keys.add(f"orcid:{person.orcid}")
            fp = _fingerprint(person.display_name)
            if fp:
                keys.add(f"name:{fp}")
    return keys


def mark_followed(graph: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    """Set ``followed`` on each author in the side list and the author network."""
    network = graph.get("author_network") if isinstance(graph.get("author_network"), dict) else {}
    for entry in list(graph.get("authors") or []) + list(network.get("nodes") or []):
        if not isinstance(entry, dict):
            continue
        candidates = {entry.get("key")}
        if entry.get("openalex"):
            candidates.add(f"openalex:{entry['openalex']}")
        if entry.get("orcid"):
            candidates.add(f"orcid:{entry['orcid']}")
        fp = _fingerprint(str(entry.get("name") or ""))
        if fp:
            candidates.add(f"name:{fp}")
        entry["followed"] = bool(candidates & keys)
    return graph


def follow_author(
    cfg: Any,
    *,
    list_name: str = "followed",
    name: str = "",
    openalex: str = "",
    orcid: str = "",
) -> dict[str, Any]:
    """Add a map author to an authorwatch list without a network lookup.

    The map already knows the OpenAlex id, so no ORCID resolution is needed;
    an ORCID, when known, is stored alongside it.
    """
    from ..authorwatch import AuthorwatchError, add_person, load_people, save_people
    from .openalex import normalize_orcid, short_id

    list_name = (list_name or "followed").strip() or "followed"
    oa = short_id(openalex) if openalex else ""
    clean_orcid = normalize_orcid(orcid) if orcid else ""
    label = (name or "").strip()
    if not (oa or clean_orcid or label):
        raise ValueError("Nothing to follow: the author has no name or id.")
    try:
        if oa or not clean_orcid:
            person = add_person(cfg, list_name, openalex=oa, display_name=label, source="map")
        else:
            person = add_person(cfg, list_name, orcid=clean_orcid, display_name=label, source="map")
    except AuthorwatchError as exc:
        raise ValueError(str(exc)) from exc
    if clean_orcid and not person.orcid:
        people = load_people(cfg, list_name)
        for row in people:
            if row.id == person.id:
                row.orcid = clean_orcid
                person = row
        save_people(cfg, list_name, people)
    return {
        "list": list_name,
        "display_name": person.display_name,
        "openalex": person.openalex,
        "orcid": person.orcid,
        "status": person.status,
    }


# --- author network view ------------------------------------------------------

#: A shared paper counts this much more than one link between two authors' papers.
COAUTHOR_WEIGHT = 1.0
LINK_WEIGHT = 0.5


def author_network(
    nodes: list[dict[str, Any]],
    rows: list[Candidate],
    edges: list[dict[str, Any]],
    *,
    max_authors: int,
    min_papers: int = 1,
    peers: int = 5,
    links: str = "both",
) -> dict[str, Any]:
    """The map's papers redrawn as people.

    Authors are linked when they wrote a paper on the map together
    (``coauthor``) and, unless ``links`` is ``"coauthor"``, when a paper of one
    is linked to a paper of the other on the map (cites / references /
    similar). Each author keeps its ``peers`` strongest links. Weights are
    scaled to 0–1. Returns ``{"nodes": [...], "edges": [...], "truncated": n}``.
    """
    if max_authors <= 0:
        return {"nodes": [], "edges": [], "truncated": 0}
    on_map = {node["id"]: node for node in nodes}
    by_key: dict[str, dict[str, Any]] = {}
    paper_authors: dict[str, list[str]] = {}
    for row in rows:
        node = on_map.get(row.identity)
        if node is None:
            continue
        keys: list[str] = []
        for record in row_author_records(row):
            key = _key(record)
            if not key or key in keys:
                continue
            keys.append(key)
            entry = by_key.setdefault(
                key,
                {
                    "id": f"author:{key}",
                    "key": key,
                    "name": "",
                    "openalex": "",
                    "orcid": "",
                    "count": 0,
                    "citations": 0,
                    "node_ids": [],
                    "seed": False,
                    "in_library": 0,
                    "years": [],
                },
            )
            entry["name"] = entry["name"] or str(record.get("display_name") or "").strip()
            entry["openalex"] = entry["openalex"] or str(record.get("openalex") or "").strip()
            entry["orcid"] = entry["orcid"] or str(record.get("orcid") or "").strip()
            entry["count"] += 1
            entry["citations"] += int(node.get("cited_by_count") or 0)
            entry["node_ids"].append(row.identity)
            entry["seed"] = entry["seed"] or bool(node.get("seed"))
            entry["in_library"] += 1 if node.get("in_library") else 0
            if node.get("year"):
                entry["years"].append(int(node["year"]))
        paper_authors[row.identity] = keys
    ranked = sorted(
        (e for e in by_key.values() if e["name"] and (e["count"] >= min_papers or e["seed"])),
        key=lambda e: (not e["seed"], -e["count"], -e["citations"], e["name"].lower(), e["key"]),
    )
    kept = ranked[:max_authors]
    truncated = max(0, len(ranked) - len(kept))
    keep_keys = {e["key"] for e in kept}

    weights: dict[tuple[str, str], dict[str, float]] = {}

    def bump(a: str, b: str, kind: str, amount: float) -> None:
        if a == b or a not in keep_keys or b not in keep_keys:
            return
        pair = (a, b) if a < b else (b, a)
        slot = weights.setdefault(pair, {"coauthor": 0.0, "linked": 0.0})
        slot[kind] += amount

    for keys in paper_authors.values():
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                bump(a, b, "coauthor", 1)
    if links != "coauthor":
        for edge in edges:
            src = paper_authors.get(str(edge.get("source") or ""), [])
            dst = paper_authors.get(str(edge.get("target") or ""), [])
            if not src or not dst:
                continue
            strength = float(edge.get("weight") or 1.0) if edge.get("direction") == "similar" else 1.0
            for a in src:
                for b in dst:
                    bump(a, b, "linked", strength)

    def score(slot: dict[str, float]) -> float:
        return COAUTHOR_WEIGHT * slot["coauthor"] + LINK_WEIGHT * slot["linked"]

    best: dict[str, list[tuple[float, tuple[str, str]]]] = {}
    for pair, slot in weights.items():
        value = score(slot)
        if value <= 0:
            continue
        for end in pair:
            best.setdefault(end, []).append((value, pair))
    chosen: set[tuple[str, str]] = set()
    for end, items in best.items():
        items.sort(key=lambda item: (-item[0], item[1]))
        for _, pair in items[: max(1, peers)]:
            chosen.add(pair)
    top = max((score(weights[p]) for p in chosen), default=0.0)
    out_edges = []
    for a, b in sorted(chosen):
        slot = weights[(a, b)]
        out_edges.append(
            {
                "source": f"author:{a}",
                "target": f"author:{b}",
                "direction": "coauthor" if slot["coauthor"] else "linked",
                "coauthored": int(slot["coauthor"]),
                "linked": round(slot["linked"], 3),
                "weight": round(score(slot) / top, 4) if top else 0.0,
            }
        )
    out_nodes = []
    for entry in kept:
        years = entry.pop("years")
        entry["year_from"] = min(years) if years else None
        entry["year_to"] = max(years) if years else None
        entry["coauthors"] = sum(
            1 for e in out_edges if e["coauthored"] and entry["id"] in (e["source"], e["target"])
        )
        out_nodes.append(entry)
    return {"nodes": out_nodes, "edges": out_edges, "truncated": truncated}
