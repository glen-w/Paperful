"""Held passages plus OpenAlex works for a phrase. Always dry-run.

Empty public hits mean OpenAlex returned nothing for this query and budget —
not that the idea is new. This pack never claims absence of prior art.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dedupe import normalize_dedupe_title, scope_slug
from .identity import LibraryFingerprint
from .resolve import normalize_doi

SCHEMA = "paperful.precedent.pack.v1"
# Required on every pack.json from write_pack(). Extra keys may be added.
PRECEDENT_PACK_KEYS = frozenset(
    {"schema", "scope", "created_at", "query", "counts", "findings", "rows"}
)
EVIDENCE_HELD = "held"
EVIDENCE_PUBLIC = "public-metadata-only"
PASSAGE_MAX = 400
HONESTY_BANNER = (
    "This pack lists works that matched the phrase in your held PDFs "
    "(passages) or in OpenAlex metadata. An empty public list means OpenAlex "
    "returned nothing for this query and budget — not that the idea is new."
)


@dataclass
class PrecedentRow:
    evidence: str  # held | public-metadata-only
    doi: str = ""
    title: str = ""
    year: int | None = None
    openalex_id: str = ""
    suggested_action: str = "skip"  # ask | ingest-dois | skip
    item_key: str = ""
    chunk_index: int | None = None
    pages: str = ""
    score: float | None = None
    passage: str = ""
    cited_by_count: int | None = None
    oa_url: str = ""
    source: str = ""  # rag | openalex | similar | fingerprint


def truncate_passage(text: str, limit: int = PASSAGE_MAX) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def row_ident(row: PrecedentRow) -> str:
    doi = normalize_doi(row.doi) or ""
    if doi:
        return f"doi:{doi}"
    title = normalize_dedupe_title(row.title)
    if title and row.year is not None:
        return f"ty:{title}|{row.year}"
    if row.openalex_id:
        return f"oa:{row.openalex_id}"
    return ""


def _richer(left: PrecedentRow, right: PrecedentRow) -> PrecedentRow:
    """Prefer a passage-bearing held row over metadata-only."""
    left_pass = bool(left.passage)
    right_pass = bool(right.passage)
    if left_pass and not right_pass:
        winner, other = left, right
    elif right_pass and not left_pass:
        winner, other = right, left
    elif left.evidence == EVIDENCE_HELD and right.evidence != EVIDENCE_HELD:
        winner, other = left, right
    elif right.evidence == EVIDENCE_HELD and left.evidence != EVIDENCE_HELD:
        winner, other = right, left
    else:
        winner, other = left, right
    if not winner.doi and other.doi:
        winner.doi = other.doi
    if not winner.title and other.title:
        winner.title = other.title
    if winner.year is None and other.year is not None:
        winner.year = other.year
    if not winner.openalex_id and other.openalex_id:
        winner.openalex_id = other.openalex_id
    if not winner.item_key and other.item_key:
        winner.item_key = other.item_key
    if winner.cited_by_count is None and other.cited_by_count is not None:
        winner.cited_by_count = other.cited_by_count
    if not winner.oa_url and other.oa_url:
        winner.oa_url = other.oa_url
    return winner


def merge_rows(groups: list[list[PrecedentRow]]) -> tuple[list[PrecedentRow], int]:
    """Dedupe by DOI, then title+year. Passage rows win."""
    buckets: dict[str, PrecedentRow] = {}
    order: list[str] = []
    dropped = 0
    fallback = 0
    for group in groups:
        for row in group:
            ident = row_ident(row)
            if not ident:
                fallback += 1
                ident = f"anon:{fallback}"
            existing = buckets.get(ident)
            if existing is None:
                buckets[ident] = row
                order.append(ident)
            else:
                buckets[ident] = _richer(existing, row)
                dropped += 1
    return [buckets[key] for key in order], dropped


def rows_from_hits(hits: list[Any]) -> list[PrecedentRow]:
    rows: list[PrecedentRow] = []
    for hit in hits:
        doi = normalize_doi(getattr(hit, "doi", "") or "") or ""
        year = getattr(hit, "year", None)
        pages = ""
        pages_fn = getattr(hit, "pages", None)
        if callable(pages_fn):
            pages = str(pages_fn() or "")
        elif pages_fn:
            pages = str(pages_fn)
        rows.append(
            PrecedentRow(
                evidence=EVIDENCE_HELD,
                doi=doi,
                title=str(getattr(hit, "title", "") or ""),
                year=int(year) if isinstance(year, int) else year,
                suggested_action="ask",
                item_key=str(getattr(hit, "item_key", "") or ""),
                chunk_index=getattr(hit, "chunk_index", None),
                pages=pages,
                score=float(getattr(hit, "score", 0.0) or 0.0),
                passage=truncate_passage(getattr(hit, "text", "") or ""),
                source="rag",
            )
        )
    return rows


def _oa_url(work: dict[str, Any]) -> str:
    loc = work.get("primary_location") or {}
    if not isinstance(loc, dict):
        return ""
    return str(loc.get("pdf_url") or loc.get("landing_page_url") or "")


def row_from_work(
    work: dict[str, Any],
    fingerprint: LibraryFingerprint,
    *,
    source: str,
) -> PrecedentRow:
    from .snowball.openalex import short_id

    doi = normalize_doi(str(work.get("doi") or "")) or ""
    title = str(work.get("display_name") or "").strip()
    raw_year = work.get("publication_year")
    year = int(raw_year) if isinstance(raw_year, int) else None
    oa = short_id(str(work.get("id") or ""))
    cited = work.get("cited_by_count")
    cited_n = int(cited) if cited is not None else None
    hit = fingerprint.find(doi or None, title or None, year)
    if hit is not None:
        return PrecedentRow(
            evidence=EVIDENCE_HELD,
            doi=doi,
            title=title,
            year=year,
            openalex_id=oa,
            suggested_action="skip",
            item_key=hit.item_key,
            cited_by_count=cited_n,
            oa_url=_oa_url(work),
            source="fingerprint",
        )
    action = "ingest-dois" if doi else "skip"
    return PrecedentRow(
        evidence=EVIDENCE_PUBLIC,
        doi=doi,
        title=title,
        year=year,
        openalex_id=oa,
        suggested_action=action,
        cited_by_count=cited_n,
        oa_url=_oa_url(work),
        source=source,
    )


def fetch_openalex_works(
    client: Any,
    query: str,
    *,
    limit: int,
    year_from: int | None,
    year_to: int | None,
    search_keywords: bool,
    keyword_limit: int,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Keyword / full-text OpenAlex works. Fail-soft on network; partial on budget."""
    from .snowball.openalex import OpenAlexBudgetExceeded, short_id

    findings: list[str] = []
    partial = False
    by_oa: dict[str, dict[str, Any]] = {}

    def _store(works: list[dict[str, Any]]) -> None:
        for work in works:
            oa = short_id(str(work.get("id") or ""))
            key = oa or (normalize_doi(str(work.get("doi") or "")) or "")
            if key and key not in by_oa:
                by_oa[key] = work

    try:
        _store(client.search(query, limit=limit, year_from=year_from, year_to=year_to))
    except OpenAlexBudgetExceeded as exc:
        partial = True
        findings.append("openalex_budget")
        extra = list(getattr(exc, "partial", None) or [])
        if extra:
            _store(extra)
    except Exception:
        findings.append("openalex_skipped")
        return [], findings, False

    if search_keywords:
        slugs: list[str] = []
        try:
            slugs = client.resolve_keyword_slugs(query, limit=max(1, keyword_limit))
        except OpenAlexBudgetExceeded:
            partial = True
            findings.append("openalex_budget")
        except Exception:
            findings.append("openalex_keywords_skipped")
        if slugs:
            try:
                tagged = client.works_by_keywords(
                    slugs, limit=limit, year_from=year_from, year_to=year_to
                )
                _store(tagged)
            except OpenAlexBudgetExceeded:
                partial = True
                findings.append("openalex_budget")
            except Exception:
                findings.append("openalex_keywords_skipped")
    return list(by_oa.values())[:limit], findings, partial


def fetch_similar_works(
    client: Any,
    seed_doi: str,
    *,
    limit: int,
    year_from: int | None,
    year_to: int | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Hop-1 similar neighbours of a seed DOI. Fail-soft."""
    from .snowball.openalex import OpenAlexBudgetExceeded, short_id
    from .snowball.similar import (
        collect_partners,
        fetch_recommendations,
        paper_ids,
        recommendation_work,
        reference_sample,
    )

    doi = normalize_doi(seed_doi) or ""
    if not doi or limit <= 0:
        return [], [], False
    findings: list[str] = []
    partial = False
    try:
        seed = client.work_by_doi(doi)
    except OpenAlexBudgetExceeded:
        return [], ["openalex_budget"], True
    except Exception:
        return [], ["similar_skipped"], False
    if not seed:
        return [], ["similar_unresolved"], False

    works: list[dict[str, Any]] = []
    seen: set[str] = set()
    seed_oa = short_id(str(seed.get("id") or ""))
    if seed_oa:
        seen.add(seed_oa)

    def _take(work: dict[str, Any]) -> None:
        oa = short_id(str(work.get("id") or ""))
        work_doi = normalize_doi(str(work.get("doi") or "")) or ""
        key = oa or work_doi
        if not key or key in seen or work_doi == doi:
            return
        seen.add(key)
        works.append(work)

    refs = reference_sample([seed])
    try:
        partners, _pending = collect_partners(
            client,
            refs,
            per_ref=min(25, max(limit, 1)),
            year_from=year_from,
            year_to=year_to,
        )
        for _count, work in partners:
            _take(work)
            if len(works) >= limit:
                break
    except OpenAlexBudgetExceeded as exc:
        partial = True
        findings.append("openalex_budget")
        found = getattr(exc, "coupling_works", None) or {}
        if isinstance(found, dict):
            for work in found.values():
                _take(work)
                if len(works) >= limit:
                    break

    room = max(0, limit - len(works))
    if room:
        getter = getattr(client, "recommend_getter", None)
        try:
            for paper in fetch_recommendations(
                paper_ids([seed]), limit=room, getter=getter
            ):
                rec = recommendation_work(paper)
                if rec is not None:
                    _take(rec)
                if len(works) >= limit:
                    break
        except Exception:
            findings.append("similar_recs_skipped")
    return works[:limit], findings, partial


def retrieve_held(
    cfg: Any,
    query: str,
    *,
    k: int,
    collections: list[str] | None,
    item_keys: list[str] | None,
    year_from: int | None,
    year_to: int | None,
) -> tuple[list[Any], list[str]]:
    """RAG passages. Never raises; ``rag_unavailable`` when the index is off."""
    if not getattr(cfg, "rag_enabled", False):
        return [], ["rag_unavailable"]
    from .llm import LLMClientError, validate_embedder
    from .llm.validate import LlmConfigError
    from .rag.index import (
        Index,
        IndexMismatch,
        IndexMissing,
        RagUnavailable,
        ledger_path,
    )
    from .rag.ledger import Ledger
    from .rag.retrieve import scope_keys, search

    try:
        embedder = validate_embedder(cfg)
        index = Index.open(cfg)
        ledger = Ledger(ledger_path(cfg))
    except (
        RagUnavailable,
        IndexMissing,
        IndexMismatch,
        LLMClientError,
        LlmConfigError,
    ):
        return [], ["rag_unavailable"]
    except Exception:
        return [], ["rag_unavailable"]
    keys = scope_keys(
        ledger,
        collections=collections,
        item_keys=item_keys,
        year_from=year_from,
        year_to=year_to,
    )
    try:
        hits = search(
            cfg, query, k=k, keys=keys, embedder=embedder, index=index, ledger=ledger
        )
    except (LLMClientError, Exception):
        return [], ["rag_unavailable"]
    return hits, []


def collect_pack(
    cfg: Any,
    query: str,
    fingerprint: LibraryFingerprint,
    *,
    collections: list[str] | None = None,
    item_keys: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    held_k: int | None = None,
    public_k: int | None = None,
    search_keywords: bool | None = None,
    seed_doi: str = "",
    client: Any = None,
    held_hits: list[Any] | None = None,
) -> tuple[list[PrecedentRow], list[str], dict[str, int], bool]:
    """Build stamped rows. ``held_hits`` / ``client`` inject fakes for tests."""
    phrase = (query or "").strip()
    held_n = max(
        1, int(held_k if held_k is not None else getattr(cfg, "precedent_held_k", 10))
    )
    public_n = max(
        1,
        int(
            public_k if public_k is not None else getattr(cfg, "precedent_public_k", 25)
        ),
    )
    use_keywords = (
        getattr(cfg, "precedent_search_keywords", True)
        if search_keywords is None
        else bool(search_keywords)
    )
    findings: list[str] = []
    partial = False

    if held_hits is None:
        hits, rag_findings = retrieve_held(
            cfg,
            phrase,
            k=held_n,
            collections=collections,
            item_keys=item_keys,
            year_from=year_from,
            year_to=year_to,
        )
        findings.extend(rag_findings)
    else:
        hits = held_hits

    oa_works: list[dict[str, Any]] = []
    similar_works: list[dict[str, Any]] = []
    if client is None:
        from .snowball.command import _openalex_client

        try:
            client = _openalex_client(cfg)
        except Exception:
            client = None
            findings.append("openalex_skipped")
    if client is not None:
        fetched, oa_findings, oa_partial = fetch_openalex_works(
            client,
            phrase,
            limit=public_n,
            year_from=year_from,
            year_to=year_to,
            search_keywords=use_keywords,
            keyword_limit=int(getattr(cfg, "snowball_keyword_limit", 3) or 3),
        )
        oa_works = fetched
        findings.extend(oa_findings)
        partial = partial or oa_partial
        if seed_doi.strip():
            sim, sim_findings, sim_partial = fetch_similar_works(
                client,
                seed_doi,
                limit=public_n,
                year_from=year_from,
                year_to=year_to,
            )
            similar_works = sim
            findings.extend(sim_findings)
            partial = partial or sim_partial

    held_rows = rows_from_hits(hits)
    public_rows = [row_from_work(w, fingerprint, source="openalex") for w in oa_works]
    similar_rows = [
        row_from_work(w, fingerprint, source="similar") for w in similar_works
    ]
    rows, deduped = merge_rows([held_rows, public_rows, similar_rows])
    unique_findings = list(dict.fromkeys(findings))
    counts = {
        "held": sum(1 for r in rows if r.evidence == EVIDENCE_HELD),
        "public_metadata_only": sum(1 for r in rows if r.evidence == EVIDENCE_PUBLIC),
        "openalex_fetched": len(oa_works) + len(similar_works),
        "deduped": deduped,
    }
    return rows, unique_findings, counts, partial


def write_pack(
    state_dir: Path,
    scope: str,
    query: str,
    rows: list[PrecedentRow],
    findings: list[str],
    counts: dict[str, int],
    *,
    stamp: str | None = None,
) -> Path:
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "precedent" / f"{stamp}-{scope_slug(scope)}"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "scope": scope,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "query": query,
        "counts": dict(counts),
        "findings": list(findings),
        "rows": [asdict(r) for r in rows],
    }
    (folder / "pack.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (folder / "dois.txt").write_text(
        "".join(
            f"{r.doi}\n"
            for r in rows
            if r.doi
            and r.evidence == EVIDENCE_PUBLIC
            and r.suggested_action == "ingest-dois"
        ),
        encoding="utf-8",
    )
    (folder / "pack.md").write_text(
        _markdown(scope, query, payload["counts"], findings, rows), encoding="utf-8"
    )
    return folder


def _markdown(
    scope: str,
    query: str,
    counts: dict[str, Any],
    findings: list[str],
    rows: list[PrecedentRow],
) -> str:
    lines = [
        f"# Precedent pack — {scope}",
        "",
        HONESTY_BANNER,
        "",
        f"Query: {query}",
        "",
        f"Held {counts.get('held', 0)}; public-metadata-only "
        f"{counts.get('public_metadata_only', 0)}; OpenAlex fetched "
        f"{counts.get('openalex_fetched', 0)}; deduped {counts.get('deduped', 0)}.",
        "",
    ]
    if findings:
        lines.append("Findings: " + ", ".join(findings))
        lines.append("")
    held = [r for r in rows if r.evidence == EVIDENCE_HELD]
    public = [r for r in rows if r.evidence == EVIDENCE_PUBLIC]
    lines.extend(
        [
            "## Held",
            "",
            "| Item | DOI | Title | Year | Pages | Action |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    if not held:
        lines.append("| — | | | | | |")
    for row in held:
        title = (row.title or "").replace("|", "/")
        lines.append(
            f"| {row.item_key} | {row.doi} | {title} | {row.year or ''} | "
            f"{row.pages} | {row.suggested_action} |"
        )
    lines.extend(
        [
            "",
            "## Public metadata only",
            "",
            "| DOI | Title | Year | Cited by | Action |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    if not public:
        lines.append("| — | | | | |")
    for row in public:
        title = (row.title or "").replace("|", "/")
        cited = "" if row.cited_by_count is None else str(row.cited_by_count)
        lines.append(
            f"| {row.doi} | {title} | {row.year or ''} | {cited} | {row.suggested_action} |"
        )
    lines.append("")
    return "\n".join(lines)
