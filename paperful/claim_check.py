"""``paperful.claim_check.v1``: per-sentence support vs the local Ask index.

No LLM. No invented citations. Similarity is not a truth verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .critique import critique_id
from .critique_claims import bind_claim, quote_in_text
from .critique_extract import ExtractedDoc
from .critique_units import Unit
from .fsio import atomic_write_text
from .store import write_json
from .stuff import StuffSkip, manuscript_units, resolve_k

SCHEMA = "paperful.claim_check.v1"
MIXED_PHRASE = "passages touch this topic and do not state the claim"

CLAIM_CHECK_PACK_KEYS = frozenset(
    {
        "schema",
        "claim_check_id",
        "created_at",
        "scope",
        "k",
        "input",
        "counts",
        "rows",
        "skips",
    }
)
HONESTY_BANNER = (
    "Each sentence is labelled against passages already in your library index. "
    "supported always includes a quote that occurs in the held chunk. "
    "mixed means passages touch this topic and do not state the claim. "
    "unsupported means no index hit. This is not a truth verdict, not "
    "accept/reject, and it does not insert citations."
)


@dataclass
class ClaimCheckHit:
    item_key: str
    title: str = ""
    pages: str = ""
    quote: str = ""
    status: str = ""
    score: float | None = None


@dataclass
class ClaimCheckRow:
    quote: str
    loc: str = ""
    status: str = "unsupported"
    note: str = ""
    hits: list[ClaimCheckHit] = field(default_factory=list)


def claim_check_id(*, kind: str, item_key: str = "", original_name: str = "") -> str:
    return critique_id(kind=kind, item_key=item_key, original_name=original_name)


def label_hits(claim: str, hits: list[Any]) -> tuple[str, str, list[ClaimCheckHit]]:
    """Deterministic supported / mixed / unsupported from retrieved passages."""
    labelled: list[ClaimCheckHit] = []
    for raw in hits:
        text = str(getattr(raw, "text", "") or "")
        if not text.strip():
            continue
        pages = str(getattr(raw, "pages", "") or "")
        unit = Unit(heading="", loc=pages, text=text)
        bound = bind_claim(claim, [unit])
        status = str(bound.get("status") or "unsupported")
        quote = str(bound.get("support_quote") or "")
        if status == "supported" and quote and not quote_in_text(quote, text):
            status = "unsupported"
            quote = ""
        labelled.append(
            ClaimCheckHit(
                item_key=str(getattr(raw, "item_key", "") or ""),
                title=str(getattr(raw, "title", "") or ""),
                pages=pages,
                quote=quote[:200],
                status=status,
                score=bound.get("score"),
            )
        )
    if any(h.status == "supported" and h.quote for h in labelled):
        keep = [h for h in labelled if h.status == "supported" and h.quote]
        return "supported", "", keep
    if labelled:
        return "mixed", MIXED_PHRASE, labelled
    return "unsupported", "", []


def collect_claim_check(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    k: int,
    keys: set[str] | None = None,
    exclude_key: str = "",
    search_fn: Callable[..., Any] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[ClaimCheckRow], list[StuffSkip]]:
    """Sentence rows labelled against retrieved library passages."""
    say = on_status or (lambda _msg: None)
    k = max(1, int(k))
    min_sent = max(1, int(getattr(cfg, "stuff_min_sentence_words", 8) or 8))
    max_units = max(1, int(getattr(cfg, "stuff_max_units", 200) or 200))
    units, skips = manuscript_units(doc, min_sentence_words=min_sent)
    if len(units) > max_units:
        extra = units[max_units:]
        units = units[:max_units]
        for row in extra:
            skips.append(
                StuffSkip(
                    reason="over_cap",
                    quote=row.quote,
                    loc=row.loc,
                    heading=row.heading,
                )
            )

    say(f"{len(units)} sentence(s) to check")
    scoped = set(keys) if keys is not None else None
    if scoped is not None and exclude_key:
        scoped.discard(exclude_key)

    def _search(query: str) -> list[Any]:
        if search_fn is not None:
            return list(search_fn(query, k=k, keys=scoped) or [])
        from .rag.retrieve import search

        return list(search(cfg, query, k=k, keys=scoped) or [])

    out: list[ClaimCheckRow] = []
    total = len(units)
    for i, unit in enumerate(units, start=1):
        say(f"Check {i}/{total}")
        query = " ".join((unit.quote or "").split())
        if not query:
            skips.append(StuffSkip(reason="empty", quote=unit.quote, loc=unit.loc))
            continue
        raw_hits = _search(query)
        filtered = []
        for raw in raw_hits:
            key = str(getattr(raw, "item_key", "") or "")
            if not key or key == exclude_key:
                continue
            filtered.append(raw)
            if len(filtered) >= k:
                break
        status, note, hits = label_hits(unit.quote, filtered)
        out.append(
            ClaimCheckRow(
                quote=unit.quote,
                loc=unit.loc,
                status=status,
                note=note,
                hits=hits,
            )
        )
    return out, skips


def counts_of(rows: list[ClaimCheckRow], skips: list[StuffSkip]) -> dict[str, int]:
    by_status = {"supported": 0, "mixed": 0, "unsupported": 0}
    for row in rows:
        if row.status in by_status:
            by_status[row.status] += 1
    return {
        "units": len(rows),
        "skips": len(skips),
        "supported": by_status["supported"],
        "mixed": by_status["mixed"],
        "unsupported": by_status["unsupported"],
    }


def pack_payload(
    *,
    cid: str,
    scope: str,
    k: int,
    inp: dict[str, Any],
    rows: list[ClaimCheckRow],
    skips: list[StuffSkip],
    created_at: str | None = None,
) -> dict[str, Any]:
    from .stuff import _skip_to_dict

    return {
        "schema": SCHEMA,
        "claim_check_id": cid,
        "created_at": created_at or datetime.now(tz=timezone.utc).isoformat(),
        "scope": scope,
        "k": k,
        "input": inp,
        "counts": counts_of(rows, skips),
        "rows": [_row_to_dict(row) for row in rows],
        "skips": [_skip_to_dict(skip) for skip in skips],
    }


def _row_to_dict(row: ClaimCheckRow) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "quote": row.quote,
        "loc": row.loc,
        "status": row.status,
        "hits": [
            {
                "item_key": hit.item_key,
                "title": hit.title,
                "pages": hit.pages,
                "quote": hit.quote,
                "status": hit.status,
                **({"score": hit.score} if hit.score is not None else {}),
            }
            for hit in row.hits
        ],
    }
    if row.note:
        payload["note"] = row.note
    return payload


def render_markdown(pack: dict[str, Any]) -> str:
    inp = pack.get("input") or {}
    title = inp.get("title") or inp.get("item_key") or inp.get("path") or "draft"
    counts = pack.get("counts") or {}
    lines = [
        f"# Claim check — {title}",
        "",
        HONESTY_BANNER,
        "",
        f"Scope: {pack.get('scope') or ''}",
        f"k: {pack.get('k') or 0}",
        "",
        (
            f"Sentences {counts.get('units', 0)}; "
            f"supported {counts.get('supported', 0)}; "
            f"mixed {counts.get('mixed', 0)}; "
            f"unsupported {counts.get('unsupported', 0)}; "
            f"skips {counts.get('skips', 0)}."
        ),
        "",
        "## Sentences",
        "",
    ]
    rows = [r for r in (pack.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        lines.append("_None._")
        lines.append("")
    for i, row in enumerate(rows, start=1):
        status = str(row.get("status") or "unsupported")
        loc = str(row.get("loc") or "").strip()
        head = f"### {i}. {status}"
        if loc:
            head += f" ({loc})"
        lines.append(head)
        lines.append("")
        quote = str(row.get("quote") or "").strip()
        if quote:
            clip = quote if len(quote) <= 280 else quote[:279].rstrip() + "…"
            lines.append(f"> {clip}")
            lines.append("")
        note = str(row.get("note") or "").strip()
        if note:
            lines.append(note)
            lines.append("")
        hits = [h for h in (row.get("hits") or []) if isinstance(h, dict)]
        if not hits:
            if status == "unsupported":
                lines.append("_No library hits._")
                lines.append("")
            continue
        for hit in hits:
            key = hit.get("item_key") or ""
            title_s = (hit.get("title") or "").replace("|", "/")
            pages = hit.get("pages") or ""
            bits = [f"`{key}`", title_s]
            if pages:
                bits.append(str(pages))
            st = hit.get("status") or ""
            if st:
                bits.append(str(st))
            lines.append("- " + " · ".join(b for b in bits if b))
            passage = str(hit.get("quote") or "").strip()
            if passage:
                lines.append(f"  > {passage}")
        lines.append("")

    skips = [s for s in (pack.get("skips") or []) if isinstance(s, dict)]
    if skips:
        lines.extend(["## Skips", ""])
        for skip in skips:
            reason = skip.get("reason") or ""
            quote = skip.get("quote") or ""
            loc = skip.get("loc") or ""
            extra = f" ({loc})" if loc else ""
            lines.append(f"- `{reason}`{extra}: {quote[:80]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_pack(
    cfg: Config,
    payload: dict[str, Any],
    *,
    stamp: str | None = None,
) -> Path:
    cid = str(payload.get("claim_check_id") or "file")
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = cfg.state_dir / "ask-claims" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload.setdefault("schema", SCHEMA)
    payload["created_at"] = (
        payload.get("created_at") or datetime.now(tz=timezone.utc).isoformat()
    )
    payload["claim_check_id"] = cid
    write_json(folder / "pack.json", payload)
    atomic_write_text(folder / "pack.md", render_markdown(payload))
    return folder


def resolve_claim_check_k(cfg: Config, k: int | None) -> int:
    return resolve_k(cfg, k)
