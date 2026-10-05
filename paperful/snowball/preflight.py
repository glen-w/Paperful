"""Opt-in co-author site preflight: graph → ORCID URLs → SearXNG remainder → proposed pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from ..config import Config
from .authors import (
    AuthorPack,
    PackAuthor,
    build_coauthor_graph,
    classify_listing_url,
    host_of,
    pack_path,
    pack_slug,
    write_coauthors,
    write_pack,
)
from .candidate import Candidate
from .orcid import OrcidError, orcid_researcher_urls
from .searxng import search_author_site, searxng_base_url


def run_author_site_preflight(
    cfg: Config,
    rows: list[Candidate],
    *,
    dest: Path,
    collection: str,
    console: Console,
    orcid_getter: Any = None,
    searx_getter: Any = None,
    max_authors: int | None = None,
    max_queries: int | None = None,
) -> Path | None:
    cap = int(max_authors if max_authors is not None else cfg.snowball_author_site_max_authors)
    query_cap = int(
        max_queries if max_queries is not None else cfg.snowball_author_site_max_queries
    )
    graph = build_coauthor_graph(rows, max_authors=cap)
    write_coauthors(dest, graph)
    people: list[PackAuthor] = []
    queries = 0
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        author = PackAuthor(
            openalex=str(node.get("openalex") or ""),
            orcid=str(node.get("orcid") or ""),
            name=str(node.get("display_name") or ""),
            fingerprint=str(node.get("fingerprint") or ""),
            frequency=int(node.get("frequency") or 0),
            degree=int(node.get("degree") or 0),
        )
        url = ""
        source = ""
        if author.orcid:
            try:
                for raw in orcid_researcher_urls(author.orcid, getter=orcid_getter):
                    url = classify_listing_url(raw)
                    if url:
                        source = "orcid"
                        break
            except OrcidError:
                url = ""
        if not url and searxng_base_url(cfg) and queries < query_cap and author.name:
            queries += 1
            hits = search_author_site(
                cfg,
                name=author.name,
                surname=(author.fingerprint.split("|", 1)[0] if author.fingerprint else ""),
                getter=searx_getter,
                cache_dir=cfg.state_dir / "snowball" / "cache" / "searxng",
            )
            for hit in hits:
                url = classify_listing_url(str(hit.get("url") or ""))
                if url:
                    source = "searxng"
                    break
        if url:
            author.listing_url = url
            author.base_host = host_of(url)
            author.source = source
        people.append(author)
    slug = pack_slug(collection)
    pack = AuthorPack(
        name=slug,
        collection=collection,
        status="proposed",
        authors=people,
    )
    path = write_pack(pack_path(cfg, slug, promoted=False), pack)
    discovered = sum(1 for a in people if a.listing_url)
    console.print(
        f"author-site preflight · {len(people)} authors · {discovered} listing URLs · "
        f"proposed {path} (promote to use on fetch)"
    )
    return path


def promote_pack(cfg: Config, slug: str) -> Path:
    from .command import SnowballError

    proposed = pack_path(cfg, slug, promoted=False)
    pack = None
    from .authors import load_pack_file

    pack = load_pack_file(proposed)
    if pack is None:
        raise SnowballError(f"No proposed author pack {slug!r} at {proposed}.")
    pack.status = "promoted"
    dest = pack_path(cfg, slug, promoted=True)
    write_pack(dest, pack)
    return dest
