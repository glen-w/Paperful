"""Snowball a seed DOI through OpenAlex references and citations.

Dry-run lists neighbour DOIs. ``--apply`` creates missing library items in one
collection. PDFs stay on ``paperful run``. Not a crawler.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from .config import Config
from .resolve import normalize_doi

OPENALEX_WORKS = "https://api.openalex.org/works"
SNOWBALL_TAG = "openalex-snowball"
DEFAULT_DEPTH = 1
DEFAULT_MAX_NODES = 80
DEFAULT_MAX_PER_HOP = 25
MAX_DEPTH = 3
DIRECTIONS = frozenset({"both", "references", "citations"})
_SELECT_FIELDS = (
    "id,doi,display_name,publication_year,type,authorships,"
    "primary_location,referenced_works,cited_by_count"
)
_ZOTERO_TYPES = {
    "article": "journalArticle",
    "review": "journalArticle",
    "preprint": "preprint",
    "book": "book",
    "book-chapter": "bookSection",
    "dissertation": "thesis",
    "report": "report",
}

Fetch = Callable[[str, dict[str, Any]], dict[str, Any] | None]


class SnowballError(Exception):
    """Seed DOI missing, or depth / caps / direction are not usable."""


@dataclass
class SnowballNode:
    openalex_id: str
    doi: str | None
    title: str
    year: int | None
    item_type: str
    depth: int
    via: str  # seed | references | citations
    from_doi: str | None
    cited_by_count: int = 0
    creators: list[dict[str, str]] = field(default_factory=list)
    venue: str = ""
    url: str = ""
    abstract: str = ""
    referenced_ids: list[str] = field(default_factory=list)

    def proposal_row(self, *, status: str, item_key: str = "") -> dict[str, Any]:
        return {
            "doi": self.doi or "",
            "title": self.title,
            "year": self.year,
            "depth": self.depth,
            "via": self.via,
            "from_doi": self.from_doi or "",
            "openalex_id": self.openalex_id,
            "item_type": self.item_type,
            "status": status,
            "itemKey": item_key,
        }


@dataclass
class SnowballPlan:
    seed_doi: str
    nodes: list[SnowballNode] = field(default_factory=list)
    truncated: bool = False
    skipped_no_doi: int = 0
    errors: list[str] = field(default_factory=list)

    def by_doi(self) -> dict[str, SnowballNode]:
        out: dict[str, SnowballNode] = {}
        for node in self.nodes:
            if node.doi and node.doi not in out:
                out[node.doi] = node
        return out


def short_openalex_id(value: str | None) -> str:
    if not value:
        return ""
    return str(value).rstrip("/").split("/")[-1]


def abstract_from_inverted(index: Any) -> str:
    """Rebuild an OpenAlex abstract. Missing or odd shapes become empty."""
    if not isinstance(index, dict) or not index:
        return ""
    placed: list[tuple[int, str]] = []
    for word, locs in index.items():
        if not isinstance(locs, list):
            continue
        for loc in locs:
            if isinstance(loc, int):
                placed.append((loc, str(word)))
    placed.sort()
    return " ".join(word for _, word in placed)


def _creators(authorships: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(authorships, list):
        return out
    for row in authorships:
        if not isinstance(row, dict):
            continue
        author = row.get("author") if isinstance(row.get("author"), dict) else {}
        name = str((author or {}).get("display_name") or "").strip()
        if not name:
            continue
        parts = name.split()
        if len(parts) == 1:
            out.append({"creatorType": "author", "name": name})
        else:
            out.append(
                {
                    "creatorType": "author",
                    "firstName": " ".join(parts[:-1]),
                    "lastName": parts[-1],
                }
            )
    return out


def _year(raw: Any) -> int | None:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def node_from_work(
    work: dict[str, Any],
    *,
    depth: int,
    via: str,
    from_doi: str | None,
) -> SnowballNode | None:
    openalex_id = short_openalex_id(str(work.get("id") or ""))
    if not openalex_id:
        return None
    doi = normalize_doi(work.get("doi") if isinstance(work.get("doi"), str) else None)
    loc = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    source = loc.get("source") if isinstance(loc.get("source"), dict) else {}
    landing = str(loc.get("landing_page_url") or "")
    refs = [
        short_openalex_id(str(item))
        for item in (work.get("referenced_works") or [])
        if short_openalex_id(str(item))
    ]
    kind = str(work.get("type") or "")
    return SnowballNode(
        openalex_id=openalex_id,
        doi=doi,
        title=str(work.get("display_name") or ""),
        year=_year(work.get("publication_year")),
        item_type=_ZOTERO_TYPES.get(kind, "document"),
        depth=depth,
        via=via,
        from_doi=from_doi,
        cited_by_count=int(work.get("cited_by_count") or 0),
        creators=_creators(work.get("authorships")),
        venue=str(source.get("display_name") or ""),
        url=landing or (f"https://doi.org/{doi}" if doi else ""),
        abstract=abstract_from_inverted(work.get("abstract_inverted_index")),
        referenced_ids=refs,
    )


def _check_limits(depth: int, max_nodes: int, max_per_hop: int, direction: str) -> None:
    if depth < 1 or depth > MAX_DEPTH:
        raise SnowballError(f"depth must be 1..{MAX_DEPTH} (got {depth})")
    if max_nodes < 1:
        raise SnowballError(f"max_nodes must be >= 1 (got {max_nodes})")
    if max_per_hop < 1:
        raise SnowballError(f"max_per_hop must be >= 1 (got {max_per_hop})")
    if direction not in DIRECTIONS:
        raise SnowballError(
            f"direction must be both, references, or citations (got {direction!r})"
        )


def _select_for(depth_left: int) -> str:
    if depth_left <= 0:
        return _SELECT_FIELDS.replace(",referenced_works", "")
    return _SELECT_FIELDS


def expand(
    seed_doi: str,
    fetch: Fetch,
    *,
    depth: int = DEFAULT_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_per_hop: int = DEFAULT_MAX_PER_HOP,
    direction: str = "both",
    mailto: str = "",
) -> SnowballPlan:
    """BFS from one DOI. Stops at ``depth`` and ``max_nodes``.

    Each node contributes at most ``max_per_hop`` references and ``max_per_hop``
    citing works. Works without a DOI are counted and not expanded.
    """
    doi = normalize_doi(seed_doi)
    if not doi:
        raise SnowballError(f"not a DOI: {seed_doi!r}")
    direction = direction.strip().lower()
    _check_limits(depth, max_nodes, max_per_hop, direction)
    plan = SnowballPlan(seed_doi=doi)
    seed_raw = _get_work_by_doi(fetch, doi, mailto=mailto, select=_select_for(depth))
    if not seed_raw:
        raise SnowballError(f"OpenAlex has no work for {doi}")
    seed = node_from_work(seed_raw, depth=0, via="seed", from_doi=None)
    if seed is None:
        raise SnowballError(f"OpenAlex work for {doi} has no id")
    nodes: dict[str, SnowballNode] = {seed.openalex_id: seed}
    queue: deque[str] = deque([seed.openalex_id])
    while queue:
        current_id = queue.popleft()
        current = nodes[current_id]
        if current.depth >= depth:
            continue
        if len(nodes) >= max_nodes:
            plan.truncated = True
            break
        neighbours = _neighbours(
            fetch,
            current,
            plan,
            mailto=mailto,
            max_per_hop=max_per_hop,
            direction=direction,
            depth_left=depth - current.depth,
        )
        # A hop cap sets ``truncated`` but the kept neighbours are still expanded.
        # ``max_nodes`` is what stops the walk.
        stop = False
        for work, via in neighbours:
            if work.openalex_id in nodes:
                continue
            if len(nodes) >= max_nodes:
                plan.truncated = True
                stop = True
                break
            if not work.doi:
                plan.skipped_no_doi += 1
                continue
            work.depth = current.depth + 1
            work.via = via
            work.from_doi = current.doi
            nodes[work.openalex_id] = work
            queue.append(work.openalex_id)
        if stop:
            break
    plan.nodes = sorted(nodes.values(), key=lambda n: (n.depth, n.via, n.doi or "", n.openalex_id))
    return plan


def _neighbours(
    fetch: Fetch,
    current: SnowballNode,
    plan: SnowballPlan,
    *,
    mailto: str,
    max_per_hop: int,
    direction: str,
    depth_left: int,
) -> list[tuple[SnowballNode, str]]:
    found: list[tuple[SnowballNode, str]] = []
    select = _select_for(depth_left - 1)
    if direction in {"both", "references"}:
        ref_ids = current.referenced_ids[:max_per_hop]
        if len(current.referenced_ids) > max_per_hop:
            plan.truncated = True
        for work in _hydrate(fetch, ref_ids, plan, mailto=mailto, select=select):
            found.append((work, "references"))
    if direction in {"both", "citations"}:
        citing = _citing(
            fetch,
            current.openalex_id,
            plan,
            mailto=mailto,
            limit=max_per_hop,
            select=select,
        )
        for work in citing:
            found.append((work, "citations"))
    return found


def _params(mailto: str, **extra: Any) -> dict[str, Any]:
    params = {k: v for k, v in extra.items() if v is not None}
    if mailto:
        params["mailto"] = mailto
    return params


def _get_work_by_doi(
    fetch: Fetch, doi: str, *, mailto: str, select: str
) -> dict[str, Any] | None:
    data = fetch(
        f"{OPENALEX_WORKS}/https://doi.org/{doi}",
        _params(mailto, select=select),
    )
    if not data or data.get("results") is not None and "id" not in data:
        return None
    if "id" not in data:
        return None
    return data


def _hydrate(
    fetch: Fetch,
    ids: list[str],
    plan: SnowballPlan,
    *,
    mailto: str,
    select: str,
) -> list[SnowballNode]:
    out: list[SnowballNode] = []
    # OpenAlex OR-filters accept about 50 values per request.
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        if not chunk:
            continue
        data = fetch(
            OPENALEX_WORKS,
            _params(
                mailto,
                filter="openalex:" + "|".join(chunk),
                **{"per-page": len(chunk), "select": select},
            ),
        )
        if not data:
            plan.errors.append(f"OpenAlex id batch failed ({chunk[0]}…)")
            continue
        by_id: dict[str, SnowballNode] = {}
        for row in data.get("results") or []:
            if not isinstance(row, dict):
                continue
            node = node_from_work(row, depth=0, via="", from_doi=None)
            if node is not None:
                by_id[node.openalex_id] = node
        for openalex_id in chunk:
            node = by_id.get(openalex_id)
            if node is not None:
                out.append(node)
    return out


def _citing(
    fetch: Fetch,
    openalex_id: str,
    plan: SnowballPlan,
    *,
    mailto: str,
    limit: int,
    select: str,
) -> list[SnowballNode]:
    per_page = min(max(limit, 1), 200)
    data = fetch(
        OPENALEX_WORKS,
        _params(
            mailto,
            filter=f"cites:{openalex_id}",
            sort="cited_by_count:desc",
            **{"per-page": per_page, "select": select},
        ),
    )
    if not data:
        plan.errors.append(f"OpenAlex citations failed for {openalex_id}")
        return []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    count = meta.get("count")
    if isinstance(count, int) and count > limit:
        plan.truncated = True
    out: list[SnowballNode] = []
    for row in (data.get("results") or [])[:limit]:
        if not isinstance(row, dict):
            continue
        node = node_from_work(row, depth=0, via="citations", from_doi=None)
        if node is not None:
            out.append(node)
    return out


def parent_payload(node: SnowballNode, collection_keys: list[str], *, seed_doi: str) -> dict[str, Any]:
    """Zotero-shaped parent. Adapters translate this; snowball does not attach a PDF."""
    extra = (
        f"OpenAlex: https://openalex.org/{node.openalex_id}\n"
        f"Paperful: snowball seed={seed_doi} depth={node.depth} via={node.via}"
    )
    return {
        "itemType": node.item_type or "document",
        "title": node.title,
        "creators": list(node.creators),
        "abstractNote": node.abstract,
        "date": str(node.year) if node.year else "",
        "DOI": node.doi or "",
        "url": node.url,
        "extra": extra,
        "publicationTitle": node.venue,
        "tags": [{"tag": SNOWBALL_TAG}],
        "collections": list(collection_keys),
        "relations": {},
    }


def proposals(
    plan: SnowballPlan,
    known_dois: dict[str, str],
    *,
    include_seed: bool = True,
) -> list[dict[str, Any]]:
    """One row per DOI. ``known_dois`` maps normalised DOI → library item key."""
    rows: list[dict[str, Any]] = []
    for node in plan.nodes:
        if not node.doi:
            continue
        if node.depth == 0 and not include_seed:
            continue
        key = known_dois.get(node.doi, "")
        status = "in_library" if key else "new"
        rows.append(node.proposal_row(status=status, item_key=key))
    return rows


def apply_snowball(
    plan: SnowballPlan,
    backend: Any,
    collection_path: str,
    known_dois: dict[str, str],
    *,
    include_seed: bool = True,
) -> dict[str, int]:
    """Create items whose DOI is not already in the library. Does not fetch PDFs."""
    collection_key = backend.ensure_collection_path(collection_path)
    created = 0
    skipped = 0
    seen: set[str] = set()
    for node in plan.nodes:
        if not node.doi or node.doi in seen:
            continue
        if node.depth == 0 and not include_seed:
            continue
        seen.add(node.doi)
        if node.doi in known_dois:
            skipped += 1
            continue
        backend.create_parent(
            parent_payload(node, [collection_key], seed_doi=plan.seed_doi)
        )
        created += 1
    return {"created": created, "skipped_in_library": skipped}


def openalex_fetch(cfg: Config) -> Fetch:
    """HTTP fetch for OpenAlex. One 429 retry. None on failure."""
    mailto = (cfg.email or "").strip()
    headers = {
        "User-Agent": f"paperful (mailto:{mailto})" if mailto else "paperful",
        "Accept": "application/json",
    }
    client = httpx.Client(headers=headers, follow_redirects=True, timeout=30.0)

    def fetch(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                try:
                    delay = min(float(resp.headers.get("Retry-After", "2")), 20.0)
                except ValueError:
                    delay = 2.0
                time.sleep(delay)
                resp = client.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    return fetch
