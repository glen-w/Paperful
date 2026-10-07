"""Parse Discover topic forms into snowball runs (gate dry-run only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config import Config
from ..snowball.command import SnowballError, SnowballRequest
from ..snowball.expand import compose_keyword_query
from ..snowball.seeds import dois_from_seeds, merge_tokens, orcids_from_seeds, parse_seed_lines


KINDS = frozenset({"search", "hybrid", "doi", "orcid", "collection"})


@dataclass
class DiscoverTopicPayload:
    kind: str
    query: str
    seeds: list[str]
    direction: str | None
    depth: int | None
    year_from: int | None
    year_to: int | None
    max_candidates: str | None
    per_hop_limit: str | None
    or_mode: bool
    hybrid_seeds: int | None
    per_hop_rank: str | None = None
    fetch_pdfs: str | None = None
    keyword_limit: str | None = None
    keyword_hop_limit: str | None = None
    keyword_min_score: float | None = None
    cites_query: str = ""
    languages: tuple[str, ...] | None = None
    min_seed_citations: int | None = None
    note_provenance: bool | None = None
    backends: tuple[str, ...] | None = None
    refine: bool | None = None
    tags: tuple[str, ...] = ()
    dedupe_scope: str | None = None
    dedupe_after: str | None = None
    author_site_preflight: bool | None = None
    twenty_writeback: bool | None = None


def _opt_int(raw: object) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return int(text)


def _opt_float(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return float(text)


def _opt_str(raw: object) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _opt_tuple(raw: object) -> tuple[str, ...] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    parts = tuple(p.strip() for p in text.replace(";", ",").split(",") if p.strip())
    return parts or None


def parse_discover_topic(form: Mapping[str, Any], *, advanced: bool) -> DiscoverTopicPayload:
    kind = "search"
    if advanced:
        kind = str(form.get("kind") or "search").strip().lower()
        if kind not in KINDS:
            kind = "search"
    seeds = parse_seed_lines(str(form.get("seeds") or "")) if advanced else []
    direction = _opt_str(form.get("direction")) if advanced else None
    depth = _opt_int(form.get("depth")) if advanced else None
    year_from = _opt_int(form.get("year_from")) if advanced else None
    year_to = _opt_int(form.get("year_to")) if advanced else None
    max_candidates = _opt_str(form.get("max_candidates")) if advanced else None
    per_hop_limit = _opt_str(form.get("per_hop_limit")) if advanced else None
    or_mode = advanced and form.get("or_mode") == "1"
    hybrid_seeds = _opt_int(form.get("hybrid_seeds")) if advanced else None
    if not advanced:
        return DiscoverTopicPayload(
            kind=kind,
            query=str(form.get("query") or "").strip(),
            seeds=seeds,
            direction=direction,
            depth=depth,
            year_from=year_from,
            year_to=year_to,
            max_candidates=max_candidates,
            per_hop_limit=per_hop_limit,
            or_mode=or_mode,
            hybrid_seeds=hybrid_seeds,
        )
    return DiscoverTopicPayload(
        kind=kind,
        query=str(form.get("query") or "").strip(),
        seeds=seeds,
        direction=direction,
        depth=depth,
        year_from=year_from,
        year_to=year_to,
        max_candidates=max_candidates,
        per_hop_limit=per_hop_limit,
        or_mode=or_mode,
        hybrid_seeds=hybrid_seeds,
        per_hop_rank=_opt_str(form.get("per_hop_rank")),
        fetch_pdfs=_opt_str(form.get("fetch_pdfs")),
        keyword_limit=_opt_str(form.get("keyword_limit")),
        keyword_hop_limit=_opt_str(form.get("keyword_hop_limit")),
        keyword_min_score=_opt_float(form.get("keyword_min_score")),
        cites_query=str(form.get("cites_query") or "").strip(),
        languages=_opt_tuple(form.get("languages")),
        min_seed_citations=_opt_int(form.get("min_seed_citations")),
        note_provenance=True if form.get("note_provenance") == "1" else None,
        backends=_opt_tuple(form.get("backends")),
        refine=True if form.get("refine") == "1" else None,
        tags=_opt_tuple(form.get("tags")) or (),
        dedupe_scope=_opt_str(form.get("dedupe_scope")),
        dedupe_after=_opt_str(form.get("dedupe_after")),
        author_site_preflight=True if form.get("author_site_preflight") == "1" else None,
        twenty_writeback=True if form.get("twenty_writeback") == "1" else None,
    )


def build_request(cfg: Config, payload: DiscoverTopicPayload, collection: str) -> SnowballRequest:
    return SnowballRequest(
        gate="dry-run",
        collection=collection or "",
        fetch_pdfs=payload.fetch_pdfs or False,
        depth=payload.depth,
        max_candidates=payload.max_candidates,
        per_hop_limit=payload.per_hop_limit,
        per_hop_rank=payload.per_hop_rank,
        year_from=payload.year_from,
        year_to=payload.year_to,
        direction=payload.direction or cfg.snowball_direction or "refs",
        hybrid_seeds=payload.hybrid_seeds,
        keyword_limit=payload.keyword_limit,
        keyword_hop_limit=payload.keyword_hop_limit,
        keyword_min_score=payload.keyword_min_score,
        cites_query=payload.cites_query,
        languages=payload.languages,
        min_seed_citations=payload.min_seed_citations,
        note_provenance=payload.note_provenance,
        backends=payload.backends,
        refine=payload.refine,
        tags=payload.tags,
        dedupe_scope=payload.dedupe_scope,
        dedupe_after=payload.dedupe_after,
        author_site_preflight=payload.author_site_preflight,
    )


def compose_query(payload: DiscoverTopicPayload) -> str:
    parts = [payload.query] if payload.query else []
    if not parts and payload.seeds and payload.kind in {"search", "hybrid"}:
        parts = payload.seeds[:1]
    if not parts:
        return ""
    notices: list[str] = []
    return compose_keyword_query(parts, op="or" if payload.or_mode else "and", notices=notices)


def doi_list(payload: DiscoverTopicPayload) -> list[str]:
    merged = merge_tokens([], payload.seeds)
    if payload.query and payload.kind == "doi":
        merged = merge_tokens([payload.query], merged)
    out = dois_from_seeds(merged)
    if not out:
        raise SnowballError("Pass one or more DOIs in Seeds or the query field.")
    return out


def orcid_list(payload: DiscoverTopicPayload) -> list[str]:
    merged = merge_tokens([], payload.seeds)
    if payload.query and payload.kind == "orcid":
        merged = merge_tokens([payload.query], merged)
    out = orcids_from_seeds(merged)
    if not out:
        raise SnowballError("Pass one or more ORCIDs in Seeds or the query field.")
    return out


def profile_body_from_payload(
    payload: DiscoverTopicPayload, *, collection: str
) -> dict[str, Any]:
    """TOML body for snowball profile save (kind=snowball)."""
    body: dict[str, Any] = {
        "kind": "snowball",
        "gate": "dry-run",
        "target_collection": collection or None,
        "direction": payload.direction,
        "depth": payload.depth,
        "max_candidates": payload.max_candidates,
        "per_hop_limit": payload.per_hop_limit,
        "per_hop_rank": payload.per_hop_rank,
        "year_from": payload.year_from,
        "year_to": payload.year_to,
        "hybrid_seeds": payload.hybrid_seeds,
        "fetch_pdfs": payload.fetch_pdfs,
        "cites_query": payload.cites_query or None,
        "dedupe_scope": payload.dedupe_scope,
        "dedupe_after": payload.dedupe_after,
    }
    if payload.kind == "search":
        body["query"] = payload.query or None
        if payload.or_mode:
            body["or"] = True
    elif payload.kind == "hybrid":
        body["query"] = payload.query or None
        body["hybrid"] = True
        if payload.or_mode:
            body["or"] = True
    elif payload.kind == "doi":
        body["doi"] = doi_list(payload)
    elif payload.kind == "orcid":
        body["orcid"] = orcid_list(payload)
    elif payload.kind == "collection":
        body["seed_collection"] = collection or (payload.seeds[0] if payload.seeds else None)
    if payload.languages:
        body["languages"] = list(payload.languages)
    if payload.tags:
        body["tag"] = list(payload.tags)
    if payload.backends:
        body["backends"] = list(payload.backends)
    if payload.min_seed_citations is not None:
        body["min_seed_citations"] = payload.min_seed_citations
    if payload.note_provenance:
        body["note_provenance"] = True
    if payload.refine:
        body["refine"] = True
    if payload.author_site_preflight:
        body["author_site_preflight"] = True
    return {k: v for k, v in body.items() if v is not None and v != "" and v != []}
