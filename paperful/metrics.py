"""Citation counts for items already in the library (``paperful.metrics.v1``).

Disk cache under ``state/metrics/``. ``--apply`` writes a tagged child note
(not Extra or parent tags).
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .config import Config
from .http import client as http_client
from .resolve import normalize_doi
from .store import load_json, write_json
from .zot import Item

SCHEMA = "paperful.metrics.v1"
CACHE_SCHEMA = "paperful.metrics.cache.v1"
PACK_SCHEMA = "paperful.metrics.pack.v1"
OPENALEX_SELECT = "id,doi,cited_by_count"
IMPLEMENTED_SOURCES = frozenset({"openalex", "crossref"})
RESERVED_SOURCES = frozenset({"semantic_scholar", "alphaxiv", "google_scholar"})
DEFAULT_NOTE_TAG = "paperful-metrics"
ROW_KEYS = frozenset(
    {
        "schema",
        "item_key",
        "doi",
        "cited_by_count",
        "source",
        "openalex_id",
        "fetched_at",
        "likes",
        "sources",
    }
)
PACK_KEYS = frozenset(
    {
        "schema",
        "created_at",
        "scope",
        "wrote",
        "stale_days",
        "rows",
        "counts",
    }
)
CrossrefGetter = Callable[[str, dict[str, Any] | None], dict[str, Any] | None]


def metrics_root(cfg: Config) -> Any:
    return cfg.state_dir / "metrics"


def cache_path(cfg: Config) -> Any:
    return metrics_root(cfg) / "cache.json"


def doi_for_item(item: Item) -> str:
    """DOI used for OpenAlex / Crossref. arXiv id becomes ``10.48550/arxiv.{id}``."""
    cleaned = normalize_doi(item.doi) or ""
    if cleaned:
        return cleaned
    arxiv = (getattr(item, "arxiv_id", None) or "").strip()
    if not arxiv:
        return ""
    return normalize_doi(f"10.48550/arxiv.{arxiv}") or f"10.48550/arxiv.{arxiv}"


def empty_row(
    item: Item,
    *,
    doi: str = "",
    cited_by_count: int | None = None,
    source: str = "unresolved",
    openalex_id: str = "",
    fetched_at: str = "",
    likes: int | None = None,
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "item_key": item.key,
        "doi": doi or doi_for_item(item),
        "cited_by_count": cited_by_count,
        "source": source,
        "openalex_id": openalex_id,
        "fetched_at": fetched_at,
        "likes": likes,
        "sources": dict(sources or {}),
    }


def load_cache(cfg: Config) -> dict[str, dict[str, Any]]:
    """``item_key`` → metrics row. Missing file is empty."""
    data = load_json(cache_path(cfg)) or {}
    items = data.get("items")
    if isinstance(items, dict):
        return {
            str(key): value for key, value in items.items() if isinstance(value, dict)
        }
    if data and "schema" not in data:
        return {
            str(key): value for key, value in data.items() if isinstance(value, dict)
        }
    return {}


def cited_by_count_for(row: dict[str, Any] | None) -> int | None:
    if not row:
        return None
    raw = row.get("cited_by_count")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def write_cache(
    cfg: Config, items: dict[str, dict[str, Any]], *, now: datetime
) -> None:
    dest = cache_path(cfg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        dest,
        {
            "schema": CACHE_SCHEMA,
            "updated_at": _iso(now),
            "items": items,
        },
    )


def _iso(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_fresh(row: dict[str, Any] | None, *, stale_days: int, now: datetime) -> bool:
    if not row or stale_days <= 0:
        return False
    fetched = _parse_iso(str(row.get("fetched_at") or ""))
    if fetched is None:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return fetched >= now - timedelta(days=stale_days)


def lookup_crossref_cited_by(
    doi: str,
    email: str,
    *,
    getter: CrossrefGetter | None = None,
) -> tuple[int | None, str | None]:
    """``(count, error)``. ``error`` is set when the lookup itself failed."""
    cleaned = normalize_doi(doi) or doi
    if not cleaned:
        return None, "no doi"
    params: dict[str, Any] | None = {"mailto": email} if email else None
    url = "https://api.crossref.org/works/" + quote(cleaned, safe="/()")
    try:
        if getter is not None:
            payload = getter(url, params)
            if payload is None:
                return None, None
            msg = payload.get("message") if isinstance(payload, dict) else None
            if not isinstance(msg, dict):
                msg = payload if isinstance(payload, dict) else {}
        else:
            with http_client(follow_redirects=True, timeout=30) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 404:
                    return None, None
                resp.raise_for_status()
                msg = resp.json().get("message") or {}
        if not isinstance(msg, dict):
            return None, "bad body"
        raw = msg.get("is-referenced-by-count")
        if raw is None:
            return None, None
        return int(raw), None
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return None, str(exc) or "crossref error"


def _work_doi(work: dict[str, Any]) -> str:
    return normalize_doi(str(work.get("doi") or "")) or ""


def _openalex_map(works: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for work in works:
        key = _work_doi(work)
        if key:
            out[key] = work
    return out


def refresh(
    cfg: Config,
    items: list[Item],
    *,
    oa_client: Any | None = None,
    dry_run: bool = False,
    offline: bool = False,
    stale_days: int | None = None,
    scope: str = "",
    now: datetime | None = None,
    crossref_getter: CrossrefGetter | None = None,
) -> dict[str, Any]:
    """Look up citation counts. Writes ``cache.json`` unless ``dry_run``."""
    from .snowball.openalex import OpenAlexBudgetExceeded, OpenAlexClient
    from .snowball.local_openalex import store_from_config

    stamp = now or datetime.now(timezone.utc)
    days = cfg.metrics_stale_days if stale_days is None else max(0, int(stale_days))
    wanted = [
        str(name).strip().lower()
        for name in (cfg.metrics_sources or IMPLEMENTED_SOURCES)
        if str(name).strip()
    ]
    use_openalex = "openalex" in wanted and not offline
    use_crossref = "crossref" in wanted and not offline
    cache = load_cache(cfg)
    rows: list[dict[str, Any]] = []
    skipped_fresh = 0
    unresolved = 0
    errors = 0
    fetched = 0
    updated = 0
    pending: list[tuple[Item, str]] = []

    for item in items:
        prior = cache.get(item.key)
        if is_fresh(prior, stale_days=days, now=stamp) and not offline:
            row = dict(prior)
            row["skip"] = "fresh"
            rows.append(row)
            skipped_fresh += 1
            continue
        if offline:
            if prior:
                row = dict(prior)
                row["skip"] = "offline"
                rows.append(row)
                skipped_fresh += 1
            else:
                row = empty_row(item, source="unresolved", fetched_at=_iso(stamp))
                row["skip"] = "offline"
                rows.append(row)
                unresolved += 1
            continue
        doi = doi_for_item(item)
        if not doi:
            row = empty_row(item, source="unresolved", fetched_at=_iso(stamp))
            rows.append(row)
            unresolved += 1
            continue
        pending.append((item, doi))

    works_by_doi: dict[str, dict[str, Any]] = {}
    oa_error = ""
    if pending and use_openalex:
        client = oa_client
        if client is None:
            client = OpenAlexClient(
                email=cfg.email,
                store=store_from_config(cfg),
                store_fail_limit=int(getattr(cfg, "openalex_store_fail_limit", 3) or 3),
            )
        dois = list(dict.fromkeys(doi for _item, doi in pending))
        try:
            works_by_doi = _openalex_map(
                client.works_by_dois(dois, select=OPENALEX_SELECT)
            )
        except OpenAlexBudgetExceeded as exc:
            oa_error = str(exc)
            partial = list(getattr(exc, "partial", None) or [])
            works_by_doi = _openalex_map(partial)

    for item, doi in pending:
        work = works_by_doi.get(doi)
        cited: int | None = None
        openalex_id = ""
        sources: dict[str, Any] = {}
        source = "unresolved"
        if work:
            openalex_id = str(work.get("id") or "")
            raw = work.get("cited_by_count")
            if raw is not None:
                try:
                    cited = int(raw)
                    sources["openalex"] = cited
                    source = "openalex"
                except (TypeError, ValueError):
                    cited = None
        if source != "openalex" and use_crossref:
            count, err = lookup_crossref_cited_by(
                doi, cfg.email, getter=crossref_getter
            )
            if err:
                source = "error"
                sources["crossref_error"] = err
                errors += 1
            elif count is not None:
                cited = count
                sources["crossref"] = count
                source = "crossref"
        if (
            oa_error
            and source == "unresolved"
            and use_openalex
            and doi not in works_by_doi
        ):
            source = "error"
            sources["openalex_error"] = oa_error
            errors += 1
        if source == "unresolved":
            unresolved += 1
        elif source != "error":
            fetched += 1
        row = empty_row(
            item,
            doi=doi,
            cited_by_count=cited,
            source=source,
            openalex_id=openalex_id,
            fetched_at=_iso(stamp),
            sources=sources,
        )
        prior = cache.get(item.key)
        if cited_by_count_for(prior) != cited or (prior or {}).get("source") != source:
            updated += 1
        rows.append(row)
        if not dry_run and source != "error":
            cache[item.key] = {k: row[k] for k in ROW_KEYS}

    wrote = False
    if not dry_run and not offline:
        write_cache(cfg, cache, now=stamp)
        wrote = True

    counts = {
        "scoped": len(items),
        "fetched": fetched,
        "updated": updated,
        "skipped_fresh": skipped_fresh,
        "unresolved": unresolved,
        "error": errors,
        "wrote": int(wrote),
    }
    pack = {
        "schema": PACK_SCHEMA,
        "created_at": _iso(stamp),
        "scope": scope,
        "wrote": wrote,
        "stale_days": days,
        "rows": rows,
        "counts": counts,
    }
    run_id = stamp.strftime("%Y%m%dT%H%M%S")
    folder = metrics_root(cfg) / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "pack.json", pack)
    return {"pack": pack, "folder": folder, "counts": counts, "rows": rows}


def citation_note_html(row: dict[str, Any], *, run_id: str = "") -> str:
    """Child-note HTML. Zotero shows the first line in the item pane."""
    from .notehtml import wrap

    cited = cited_by_count_for(row)
    source = str(row.get("source") or "").strip()
    extra = f"{cited} ({source})" if cited is not None else source
    parts = [
        "<p>Citation count from <code>paperful metrics</code> "
        "(OpenAlex, then Crossref). This note is updated in place. "
        "It is not written to Extra.</p>",
        "<p>Count: <strong>"
        + html_lib.escape("—" if cited is None else str(cited))
        + "</strong> · source "
        + html_lib.escape(source or "—")
        + "</p>",
    ]
    doi = str(row.get("doi") or "").strip()
    if doi:
        parts.append(
            '<p>DOI: <a href="https://doi.org/'
            + html_lib.escape(doi)
            + '">'
            + html_lib.escape(doi)
            + "</a></p>"
        )
    oa_id = str(row.get("openalex_id") or "").strip()
    if oa_id.startswith("http"):
        parts.append(
            '<p>OpenAlex: <a href="'
            + html_lib.escape(oa_id)
            + '">'
            + html_lib.escape(oa_id)
            + "</a></p>"
        )
    fetched = str(row.get("fetched_at") or "").strip()
    if fetched:
        parts.append("<p><small>Fetched " + html_lib.escape(fetched) + "</small></p>")
    return wrap(
        "\n".join(parts),
        note_type="citations",
        verb="metrics",
        extra=extra,
        run_id=run_id,
    )


def apply_citation_notes(
    backend: Any,
    cfg: Config,
    rows: list[dict[str, Any]],
    *,
    run_id: str = "",
) -> dict[str, int]:
    """Create or update one tagged child note per row that has a count."""
    tag = (getattr(cfg, "metrics_note_tag", None) or DEFAULT_NOTE_TAG).strip()
    tag = tag or DEFAULT_NOTE_TAG
    wrote = 0
    skipped = 0
    errors = 0
    for row in rows:
        key = str(row.get("item_key") or "").strip()
        source = str(row.get("source") or "")
        if (
            not key
            or cited_by_count_for(row) is None
            or source in {"unresolved", "error"}
        ):
            skipped += 1
            continue
        html = citation_note_html(row, run_id=run_id)
        try:
            backend.create_or_update_note(key, html, tag)
            wrote += 1
        except Exception:
            errors += 1
    return {"notes_wrote": wrote, "notes_skipped": skipped, "notes_error": errors}


def show_cached(cfg: Config, item_key: str) -> dict[str, Any] | None:
    row = load_cache(cfg).get(item_key)
    return dict(row) if row else None
