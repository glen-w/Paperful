"""Parse Discover topic forms into snowball runs (gate dry-run only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config import Config
from ..snowball.command import SnowballRequest, SnowballError
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


def _opt_int(raw: object) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return int(text)


def _opt_str(raw: object) -> str | None:
    text = str(raw or "").strip()
    return text or None


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


def build_request(cfg: Config, payload: DiscoverTopicPayload, collection: str) -> SnowballRequest:
    return SnowballRequest(
        gate="dry-run",
        collection=collection or "",
        depth=payload.depth,
        max_candidates=payload.max_candidates,
        per_hop_limit=payload.per_hop_limit,
        year_from=payload.year_from,
        year_to=payload.year_to,
        direction=payload.direction or cfg.snowball_direction or "refs",
        hybrid_seeds=payload.hybrid_seeds,
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
