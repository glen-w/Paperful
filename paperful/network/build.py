"""Build an ORCID ego co-authorship graph from OpenAlex works."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..snowball.authors import AuthorRecord, name_fingerprint
from ..snowball.openalex import normalize_orcid, short_id
from .store import SCHEMA

NETWORK_SELECT = (
    "id,doi,display_name,publication_year,type,cited_by_count,language,"
    "referenced_works,authorships,primary_location,open_access,keywords,"
    "study_designs,topics"
)


def works_to_records(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten OpenAlex works into per-paper author lists plus year."""
    rows: list[dict[str, Any]] = []
    for work in works:
        if not isinstance(work, dict):
            continue
        year = work.get("publication_year")
        try:
            year_i = int(year) if year is not None else None
        except (TypeError, ValueError):
            year_i = None
        records, attrs = _paired_records(work.get("authorships") or [])
        topics = _topic_names(work.get("topics") or [])
        rows.append(
            {
                "id": short_id(str(work.get("id") or "")),
                "year": year_i,
                "authors": records,
                "attrs": attrs,
                "topics": topics,
            }
        )
    return rows


def build_ego_graph(
    works: list[dict[str, Any]],
    *,
    orcid: str,
    ego: AuthorRecord | None = None,
    max_alters: int = 150,
) -> dict[str, Any]:
    """Undirected weighted co-authorship ego graph. Nodes use AuthorRecord identities."""
    cleaned = normalize_orcid(orcid)
    papers = works_to_records(works)
    freq: Counter[str] = Counter()
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str], list[int]] = defaultdict(list)
    attr_votes: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: {
            "country": Counter(),
            "sector": Counter(),
            "discipline": Counter(),
        }
    )
    first_year: dict[str, int] = {}
    last_year: dict[str, int] = {}

    ego_key = ""
    if ego is not None:
        ego_key = ego.identity()
        nodes[ego_key] = {
            **ego.to_dict(),
            "id": ego_key,
            "ego": True,
        }

    for paper in papers:
        year = paper.get("year")
        people = paper.get("authors") or []
        paper_attrs = paper.get("attrs") or []
        topics = paper.get("topics") or []
        seen: list[str] = []
        for rec, extra in _zip_attrs(people, paper_attrs):
            key = _identity(rec)
            if not key:
                continue
            if not ego_key and cleaned and rec.get("orcid") == cleaned:
                ego_key = key
            freq[key] += 1
            node = nodes.get(key) or {**rec, "id": key, "ego": False}
            node.update({k: rec.get(k) or node.get(k) or "" for k in rec})
            nodes[key] = node
            if key not in seen:
                seen.append(key)
            _vote_attrs(attr_votes[key], extra, topics)
            if isinstance(year, int):
                first_year[key] = min(year, first_year.get(key, year))
                last_year[key] = max(year, last_year.get(key, year))
        if ego_key and ego_key not in seen:
            seen.append(ego_key)
            freq[ego_key] += 1
        for i, left in enumerate(seen):
            for right in seen[i + 1 :]:
                pair = (left, right) if left < right else (right, left)
                if isinstance(year, int):
                    edges[pair].append(year)
                else:
                    edges[pair].append(0)

    if not ego_key:
        ego_key = _fallback_ego(nodes, cleaned, freq)
    if ego_key and ego_key in nodes:
        nodes[ego_key]["ego"] = True

    degree: Counter[str] = Counter()
    for left, right in edges:
        degree[left] += 1
        degree[right] += 1

    alter_ids = [key for key in freq if key != ego_key]
    cap = max(0, int(max_alters or 0))
    ranked_alters = sorted(alter_ids, key=lambda k: (-freq[k], -degree[k], k))
    if cap:
        ranked_alters = ranked_alters[:cap]
    keep = set(ranked_alters)
    if ego_key:
        keep.add(ego_key)

    node_rows = []
    for key in sorted(keep, key=lambda k: (0 if k == ego_key else 1, -freq[k], k)):
        rec = nodes.get(key) or {"id": key}
        votes = attr_votes.get(key) or {}
        node_rows.append(
            {
                "id": key,
                "openalex": str(rec.get("openalex") or ""),
                "orcid": str(rec.get("orcid") or ""),
                "display_name": str(rec.get("display_name") or ""),
                "fingerprint": str(rec.get("fingerprint") or ""),
                "ego": bool(rec.get("ego")),
                "frequency": int(freq.get(key) or 0),
                "degree": int(degree.get(key) or 0),
                "first_year": first_year.get(key),
                "last_year": last_year.get(key),
                "country": _top(votes.get("country")),
                "sector": _top(votes.get("sector")),
                "discipline": _top(votes.get("discipline")),
            }
        )

    edge_rows = []
    for (left, right), years in sorted(edges.items(), key=lambda kv: -len(kv[1])):
        if left not in keep or right not in keep:
            continue
        real_years = [y for y in years if y]
        edge_rows.append(
            {
                "a": left,
                "b": right,
                "weight": len(years),
                "years": real_years,
            }
        )

    ego_node = next((n for n in node_rows if n["id"] == ego_key), None) or {
        "id": ego_key,
        "orcid": cleaned,
        "ego": True,
    }
    return {
        "schema": SCHEMA,
        "ego": {
            "id": ego_key,
            "orcid": cleaned,
            "openalex": str(ego_node.get("openalex") or ""),
            "display_name": str(ego_node.get("display_name") or ""),
        },
        "nodes": node_rows,
        "edges": edge_rows,
    }


def _identity(rec: dict[str, str]) -> str:
    return AuthorRecord(
        openalex=str(rec.get("openalex") or ""),
        orcid=normalize_orcid(str(rec.get("orcid") or "")),
        display_name=str(rec.get("display_name") or ""),
        fingerprint=str(rec.get("fingerprint") or "")
        or name_fingerprint(str(rec.get("display_name") or "")),
    ).identity()


def _paired_records(
    authorships: list[Any] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    records: list[dict[str, str]] = []
    attrs: list[dict[str, str]] = []
    for row in authorships or []:
        if not isinstance(row, dict):
            continue
        author = row.get("author") or {}
        if not isinstance(author, dict):
            author = {}
        name = (author.get("display_name") or row.get("raw_author_name") or "").strip()
        rec = {
            "openalex": short_id(str(author.get("id") or "")),
            "orcid": normalize_orcid(str(author.get("orcid") or "")),
            "display_name": name,
            "fingerprint": name_fingerprint(name),
        }
        if not AuthorRecord(
            openalex=rec["openalex"],
            orcid=rec["orcid"],
            display_name=rec["display_name"],
            fingerprint=rec["fingerprint"],
        ).identity():
            continue
        records.append(rec)
        attrs.append(_authorship_attrs(row))
    return records, attrs


def _zip_attrs(
    people: list[dict[str, str]], extras: list[dict[str, str]]
) -> list[tuple[dict[str, str], dict[str, str]]]:
    out: list[tuple[dict[str, str], dict[str, str]]] = []
    for i, rec in enumerate(people):
        extra = extras[i] if i < len(extras) else {}
        out.append((rec, extra))
    return out


def _authorship_attrs(row: Any) -> dict[str, str]:
    if not isinstance(row, dict):
        return {}
    country = ""
    sector = ""
    for inst in row.get("institutions") or []:
        if not isinstance(inst, dict):
            continue
        if not country:
            country = str(inst.get("country_code") or "").strip().upper()
        if not sector:
            sector = str(inst.get("type") or "").strip().lower()
    if not country:
        countries = row.get("countries") or []
        if countries:
            country = str(countries[0] or "").strip().upper()
    return {"country": country, "sector": _sector_label(sector)}


def _topic_names(topics: list[Any]) -> list[str]:
    names: list[str] = []
    for row in topics:
        if not isinstance(row, dict):
            continue
        sub = row.get("subfield") if isinstance(row.get("subfield"), dict) else {}
        name = str((sub or {}).get("display_name") or row.get("display_name") or "").strip()
        if name:
            names.append(name)
    return names


def _vote_attrs(
    votes: dict[str, Counter[str]], extra: dict[str, str], topics: list[str]
) -> None:
    country = str(extra.get("country") or "").strip()
    if country:
        votes["country"][country] += 1
    sector = str(extra.get("sector") or "").strip()
    if sector:
        votes["sector"][sector] += 1
    for topic in topics:
        votes["discipline"][topic] += 1


def _sector_label(raw: str) -> str:
    mapping = {
        "education": "academia",
        "government": "government",
        "nonprofit": "ngo",
        "company": "industry",
        "facility": "research",
        "healthcare": "healthcare",
        "archive": "archive",
    }
    return mapping.get(raw, raw or "")


def _top(counter: Counter[str] | None) -> str:
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _fallback_ego(
    nodes: dict[str, dict[str, Any]], orcid: str, freq: Counter[str]
) -> str:
    if orcid:
        for key, rec in nodes.items():
            if rec.get("orcid") == orcid:
                return key
    if freq:
        return freq.most_common(1)[0][0]
    return next(iter(nodes), "")
