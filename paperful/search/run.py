"""Run a web grey search into ``state/search/<run-id>/``."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import Config
from ..greyid import registrable_host
from ..playbooks import looks_like_pdf_url
from ..snowball.searxng import searxng_base_url
from .rank import (
    build_query,
    doi_from_text,
    fanout_queries,
    host_allowed,
    parse_hosts,
    score_hit,
    year_from_text,
)
from .store import (
    SCHEMA,
    SearchError,
    cache_dir,
    new_run_id,
    run_dir,
    write_run,
)


def engine_host(cfg: Config) -> str:
    base = searxng_base_url(cfg)
    return (urlparse(base).hostname or "").lower()


def require_searxng(cfg: Config) -> str:
    base = searxng_base_url(cfg)
    if not base:
        raise SearchError(
            "SearXNG is unset. Set [searxng].base_url or SEARXNG_BASE_URL, then paperful doctor.",
            code=2,
        )
    return base


def probe_url(url: str, *, getter: Any = None) -> dict[str, Any]:
    """HEAD/GET enough to tell PDF vs HTML. ``getter`` is for tests."""
    if getter is not None:
        data = getter(url) or {}
        if isinstance(data, dict):
            return data
        return {"kind": "unknown"}
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            head = client.head(url)
            ctype = str(head.headers.get("content-type") or "").lower()
            if "pdf" in ctype or looks_like_pdf_url(str(head.url)):
                return {"kind": "pdf", "content_type": ctype, "status": head.status_code}
            get = client.get(url, headers={"Range": "bytes=0-15"})
            body = get.content[:8]
            ctype = str(get.headers.get("content-type") or ctype).lower()
            if body.startswith(b"%PDF") or "pdf" in ctype:
                return {"kind": "pdf", "content_type": ctype, "status": get.status_code}
            if "html" in ctype or body[:1] in {b"<", b"\xef"}:
                return {"kind": "landing", "content_type": ctype, "status": get.status_code}
            return {"kind": "unknown", "content_type": ctype, "status": get.status_code}
    except httpx.HTTPError:
        return {"kind": "unknown"}


def run_search(
    cfg: Config,
    terms: list[str],
    *,
    hosts: str | list[str] | None = None,
    filetype: str = "pdf",
    max_hits: int | None = None,
    probe: bool | None = None,
    run_id: str | None = None,
    dest: Path | None = None,
    getter: Any = None,
    probe_getter: Any = None,
    lookup: Any = None,
) -> dict[str, Any]:
    require_searxng(cfg)
    allow = parse_hosts(hosts)
    queries = fanout_queries(terms, filetype=filetype, hosts=allow)
    query = queries[0] if queries else ""
    if not query:
        raise SearchError("Pass a search query.")
    from ..snowball.searxng import search_query

    cap = max(1, int(max_hits if max_hits is not None else (cfg.search_max or 20)))
    do_probe = cfg.search_probe if probe is None else bool(probe)
    fetch_limit = max(cap * 3, cap, 80)
    page_cap = min(8, max(1, (fetch_limit + 19) // 20))
    raw: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for q in queries:
        page = search_query(
            cfg,
            q,
            limit=fetch_limit,
            getter=getter,
            cache_dir=cache_dir(cfg),
            pages=page_cap,
        )
        for row in page:
            url = str(row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            raw.append(row)
            if len(raw) >= fetch_limit:
                break
        if len(raw) >= fetch_limit:
            break
    playbooks = list(cfg.grey_playbooks or [])
    hits: list[dict[str, Any]] = []
    blocked = 0
    dropped = 0
    for row in raw:
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        if not url:
            continue
        score, playbook, rewritten = score_hit(
            url, title=title, query=query, playbooks=playbooks
        )
        host = registrable_host(rewritten) or registrable_host(url)
        if score < 0:
            blocked += 1
            hits.append(
                _hit(
                    url=url,
                    title=title,
                    score=score,
                    host=host,
                    playbook=playbook,
                    kind="blocked",
                    status="blocked",
                )
            )
            continue
        if not host_allowed(rewritten, allow) and not host_allowed(url, allow):
            dropped += 1
            continue
        kind = "pdf" if looks_like_pdf_url(rewritten) else "landing"
        hits.append(
            _hit(
                url=rewritten,
                title=title or rewritten,
                score=score,
                host=host,
                playbook=playbook,
                kind=kind,
                status="new",
                source_url=url,
            )
        )
    hits.sort(key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or "")))

    candidates: list[dict[str, Any]] = []
    for row in hits:
        if row.get("status") == "blocked":
            continue
        probed = dict(row)
        if do_probe:
            info = probe_url(str(probed.get("url") or ""), getter=probe_getter)
            kind = str(info.get("kind") or "")
            if kind == "pdf":
                probed["kind"] = "pdf"
            elif kind == "landing":
                probed["kind"] = "landing"
            if (
                probed.get("kind") == "landing"
                and not probed.get("playbook")
                and not allow
            ):
                dropped += 1
                continue
        status = "new"
        if lookup is not None:
            hit = lookup(
                doi=probed.get("doi") or None,
                title=probed.get("title"),
                year=probed.get("year"),
                url=probed.get("url"),
            )
            if hit is not None:
                status = "exists"
                probed["item_key"] = getattr(hit, "item_key", None) or (
                    hit[0] if isinstance(hit, tuple) else str(hit)
                )
        probed["status"] = status
        candidates.append(probed)
        if len(candidates) >= cap:
            break

    rid = (run_id or "").strip() or new_run_id()
    out = dest if dest is not None else run_dir(cfg, rid)
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meta = {
        "schema": SCHEMA,
        "run_id": rid,
        "query": query,
        "filetype": (filetype or "pdf").strip().lower() or "pdf",
        "hosts": allow,
        "engine_host": engine_host(cfg),
        "built_at": stamp,
        "max": cap,
        "probe": bool(do_probe),
        "partial": not raw,
    }
    summary = {
        "hits": len(hits),
        "kept": len(candidates),
        "exists": sum(1 for row in candidates if row.get("status") == "exists"),
        "blocked": blocked,
        "new": sum(1 for row in candidates if row.get("status") == "new"),
        "dropped": dropped,
    }
    write_run(out, meta=meta, hits=hits, candidates=candidates, summary=summary)
    return {
        "schema": SCHEMA,
        "run_id": rid,
        "path": str(out),
        "meta": meta,
        "hits": hits,
        "candidates": candidates,
        "summary": summary,
        "partial": bool(meta["partial"]),
    }


def _hit(
    *,
    url: str,
    title: str,
    score: int,
    host: str,
    playbook: str,
    kind: str,
    status: str,
    source_url: str = "",
) -> dict[str, Any]:
    year = year_from_text(title, url)
    doi = doi_from_text(title, url)
    row = {
        "url": url,
        "title": title,
        "score": int(score),
        "host": host or "",
        "playbook": playbook or "",
        "kind": kind,
        "status": status,
        "year": year,
        "doi": doi,
    }
    if source_url and source_url != url:
        row["source_url"] = source_url
    return row
