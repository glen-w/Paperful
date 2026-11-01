"""``paperful.stuff.pack.v1``: extra library cites per claim. No LLM prose."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .critique_extract import ExtractedDoc, loc_of_span
from .critique_metrics import split_sentences
from .critique_overlap import _BIBLIO_HEAD, _drop_biblio
from .store import write_json

SCHEMA = "paperful.stuff.pack.v1"
# Required on every pack.json from write_pack(). Extra keys (outline) may be added.
STUFF_PACK_KEYS = frozenset(
    {
        "schema",
        "stuff_id",
        "created_at",
        "scope",
        "lane",
        "k",
        "input",
        "counts",
        "rows",
        "skips",
    }
)
KNOWN_LANES = ("manuscript", "outline")
SKIP_OUTLINE_CANON = frozenset({"references", "acknowledgements"})
QUERY_MAX = 1500
PASSAGE_MAX = 400
HONESTY_BANNER = (
    "Each row is a sentence or outline section from the input plus the closest "
    "passages already in your library index. Similarity is not proof the source "
    "supports the claim. Extra cites belong in Zotero before \\cite; this pack "
    "does not invent BibTeX."
)


@dataclass
class StuffHit:
    item_key: str
    title: str = ""
    pages: str = ""
    score: float | None = None
    passage: str = ""
    doi: str = ""
    year: int | None = None


@dataclass
class StuffRow:
    quote: str
    loc: str = ""
    hits: list[StuffHit] = field(default_factory=list)
    heading: str = ""


@dataclass
class StuffSkip:
    reason: str
    quote: str = ""
    loc: str = ""
    heading: str = ""


def canonical_lane(name: str) -> str:
    raw = str(name or "").strip().lower()
    if raw not in KNOWN_LANES:
        raise ValueError(f"unknown stuff lane {name!r} (want {', '.join(KNOWN_LANES)})")
    return raw


def resolve_lane(cfg: Config, lane: str | None) -> str:
    if lane and str(lane).strip():
        return canonical_lane(lane)
    return canonical_lane(getattr(cfg, "stuff_lane", None) or "manuscript")


def resolve_k(cfg: Config, k: int | None) -> int:
    want = int(k) if k is not None else int(getattr(cfg, "stuff_k", 3) or 3)
    want = max(1, want)
    ceiling = max(1, int(getattr(cfg, "rag_top_k", 10) or 10))
    return min(want, ceiling)


def stuff_id(*, kind: str, item_key: str = "", original_name: str = "") -> str:
    """Stable id: item key, or ``file-<stem>`` like critiques."""
    from .critique import critique_id

    return critique_id(kind=kind, item_key=item_key, original_name=original_name)


def truncate_passage(text: str, limit: int = PASSAGE_MAX) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _word_count(text: str) -> int:
    return len((text or "").split())


def _trim_query(text: str) -> str:
    blob = " ".join((text or "").split())
    if len(blob) <= QUERY_MAX:
        return blob
    return blob[: QUERY_MAX - 1].rstrip() + "…"


def _biblio_heading(text: str) -> str | None:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and _BIBLIO_HEAD.match(stripped):
            return stripped
    return None


def _hit_from_raw(raw: Any, *, exclude_key: str = "") -> StuffHit | None:
    key = str(getattr(raw, "item_key", "") or "").strip()
    if not key:
        return None
    if exclude_key and key == exclude_key:
        return None
    score = getattr(raw, "score", None)
    try:
        score_f = round(float(score), 4) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    year = getattr(raw, "year", None)
    try:
        year_i = int(year) if year is not None else None
    except (TypeError, ValueError):
        year_i = None
    pages = ""
    if hasattr(raw, "pages"):
        pages = str(getattr(raw, "pages") or "")
    return StuffHit(
        item_key=key,
        title=str(getattr(raw, "title", "") or ""),
        pages=pages,
        score=score_f,
        passage=truncate_passage(str(getattr(raw, "text", "") or "")),
        doi=str(getattr(raw, "doi", "") or ""),
        year=year_i,
    )


def _row_to_dict(row: StuffRow) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "quote": row.quote,
        "loc": row.loc,
        "hits": [asdict(hit) for hit in row.hits],
    }
    if row.heading:
        payload["heading"] = row.heading
    return payload


def _skip_to_dict(skip: StuffSkip) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": skip.reason, "quote": skip.quote}
    if skip.loc:
        payload["loc"] = skip.loc
    if skip.heading:
        payload["heading"] = skip.heading
    return payload


def manuscript_units(
    doc: ExtractedDoc,
    *,
    min_sentence_words: int,
) -> tuple[list[StuffRow], list[StuffSkip]]:
    """Sentence units after dropping the bibliography window."""
    text = doc.text or ""
    skips: list[StuffSkip] = []
    heading = _biblio_heading(text)
    if heading:
        skips.append(
            StuffSkip(
                reason="biblio",
                quote=heading,
                loc=loc_of_span(doc, heading),
            )
        )
    body = _drop_biblio(text)
    rows: list[StuffRow] = []
    for sent in split_sentences(body):
        loc = loc_of_span(doc, sent)
        if _word_count(sent) < min_sentence_words:
            skips.append(StuffSkip(reason="short", quote=sent, loc=loc))
            continue
        rows.append(StuffRow(quote=sent, loc=loc))
    return rows, skips


def outline_units(
    doc: ExtractedDoc,
    cfg: Config | None,
    *,
    min_query_words: int,
) -> tuple[list[StuffRow], list[StuffSkip], list[dict[str, Any]]]:
    """One unit per outline section. Thin headings still search."""
    from .critique_outline import outline_ledger, outline_slices
    from .sections.headings import canonical_for_heading

    slices = outline_slices(doc.text or "", cfg)
    ledger = outline_ledger(slices, cfg)
    rows: list[StuffRow] = []
    skips: list[StuffSkip] = []
    for heading, body in slices:
        raw_heading = (heading or "").strip()
        label = raw_heading or "Preamble"
        body_text = (body or "").strip()
        loc = loc_of_span(doc, raw_heading or body_text[:80])
        canon = canonical_for_heading(raw_heading, cfg) if raw_heading else None
        if canon in SKIP_OUTLINE_CANON:
            skips.append(
                StuffSkip(
                    reason="biblio",
                    quote=raw_heading or body_text,
                    loc=loc,
                    heading=label,
                )
            )
            continue
        query = _trim_query(
            f"{raw_heading}\n{body_text}".strip() if raw_heading else body_text
        )
        if not query:
            skips.append(
                StuffSkip(
                    reason="empty",
                    quote=raw_heading or body_text,
                    loc=loc,
                    heading=label,
                )
            )
            continue
        if _word_count(query) < min_query_words:
            skips.append(
                StuffSkip(
                    reason="short",
                    quote=raw_heading or body_text,
                    loc=loc,
                    heading=label,
                )
            )
            continue
        rows.append(
            StuffRow(
                quote=body_text or label,
                loc=loc,
                heading=label,
            )
        )
    return rows, skips, ledger


def _query_for(row: StuffRow) -> str:
    if row.heading and row.heading != "Preamble":
        return _trim_query(f"{row.heading}\n{row.quote}".strip())
    return _trim_query(row.quote)


def collect_pack(
    cfg: Config,
    doc: ExtractedDoc,
    *,
    lane: str,
    k: int,
    keys: set[str] | None = None,
    exclude_key: str = "",
    search_fn: Callable[..., Any] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[StuffRow], list[StuffSkip], list[dict[str, Any]] | None]:
    """Build stuffed rows. ``search_fn(query, k, keys)`` is injectable for tests."""
    say = on_status or (lambda _msg: None)
    lane = canonical_lane(lane)
    k = max(1, int(k))
    min_sent = max(1, int(getattr(cfg, "stuff_min_sentence_words", 8) or 8))
    min_query = max(1, int(getattr(cfg, "stuff_min_query_words", 4) or 4))
    max_units = max(1, int(getattr(cfg, "stuff_max_units", 200) or 200))
    ledger: list[dict[str, Any]] | None = None
    if lane == "outline":
        rows, skips, ledger = outline_units(doc, cfg, min_query_words=min_query)
    else:
        rows, skips = manuscript_units(doc, min_sentence_words=min_sent)

    if len(rows) > max_units:
        extra = rows[max_units:]
        rows = rows[:max_units]
        for row in extra:
            skips.append(
                StuffSkip(
                    reason="over_cap",
                    quote=row.quote,
                    loc=row.loc,
                    heading=row.heading,
                )
            )

    say(f"{len(rows)} unit(s) to search")
    scoped = set(keys) if keys is not None else None
    if scoped is not None and exclude_key:
        scoped.discard(exclude_key)

    def _search(query: str) -> list[Any]:
        if search_fn is not None:
            return list(search_fn(query, k=k, keys=scoped) or [])
        from .rag.retrieve import search

        return list(search(cfg, query, k=k, keys=scoped) or [])

    stuffed: list[StuffRow] = []
    total = len(rows)
    for i, row in enumerate(rows, start=1):
        say(f"Search {i}/{total}")
        query = _query_for(row)
        if not query:
            skips.append(
                StuffSkip(
                    reason="empty",
                    quote=row.quote,
                    loc=row.loc,
                    heading=row.heading,
                )
            )
            continue
        raw_hits = _search(query)
        hits: list[StuffHit] = []
        for raw in raw_hits:
            hit = _hit_from_raw(raw, exclude_key=exclude_key)
            if hit is None:
                continue
            hits.append(hit)
            if len(hits) >= k:
                break
        stuffed.append(
            StuffRow(quote=row.quote, loc=row.loc, hits=hits, heading=row.heading)
        )
    return stuffed, skips, ledger


def counts_of(rows: list[StuffRow], skips: list[StuffSkip]) -> dict[str, int]:
    unique = {hit.item_key for row in rows for hit in row.hits if hit.item_key}
    return {
        "units": len(rows),
        "hits": sum(len(row.hits) for row in rows),
        "skips": len(skips),
        "unique_sources": len(unique),
    }


def pack_payload(
    *,
    cid: str,
    scope: str,
    lane: str,
    k: int,
    inp: dict[str, Any],
    rows: list[StuffRow],
    skips: list[StuffSkip],
    ledger: list[dict[str, Any]] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "stuff_id": cid,
        "created_at": created_at or datetime.now(tz=timezone.utc).isoformat(),
        "scope": scope,
        "lane": lane,
        "k": k,
        "input": inp,
        "counts": counts_of(rows, skips),
        "rows": [_row_to_dict(row) for row in rows],
        "skips": [_skip_to_dict(skip) for skip in skips],
    }
    if ledger is not None:
        payload["outline"] = ledger
    return payload


def render_markdown(pack: dict[str, Any]) -> str:
    inp = pack.get("input") or {}
    title = inp.get("title") or inp.get("item_key") or inp.get("path") or "draft"
    counts = pack.get("counts") or {}
    lines = [
        f"# Stuff pack — {title}",
        "",
        HONESTY_BANNER,
        "",
        f"Lane: {pack.get('lane') or 'manuscript'}",
        f"Scope: {pack.get('scope') or ''}",
        f"k: {pack.get('k') or 0}",
        "",
        f"Units {counts.get('units', 0)}; hits {counts.get('hits', 0)}; "
        f"unique sources {counts.get('unique_sources', 0)}; "
        f"skips {counts.get('skips', 0)}.",
        "",
    ]
    ledger = pack.get("outline")
    if isinstance(ledger, list) and ledger:
        lines.extend(["## Outline", ""])
        for row in ledger:
            if not isinstance(row, dict):
                continue
            heading = str(row.get("heading") or "Preamble")
            words = row.get("words", "")
            extra = f" [{row['canonical']}]" if row.get("canonical") else ""
            lines.append(f"- {heading} ({words} words){extra}")
        lines.append("")

    unique: dict[str, dict[str, Any]] = {}
    for row in pack.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for hit in row.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            key = str(hit.get("item_key") or "")
            if not key:
                continue
            rec = unique.setdefault(key, {"title": hit.get("title") or key, "n": 0})
            rec["n"] += 1
            if not rec["title"] and hit.get("title"):
                rec["title"] = hit["title"]
    if unique:
        lines.extend(["## Unique sources", ""])
        for key, rec in sorted(unique.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
            title_s = str(rec["title"] or key).replace("|", "/")
            lines.append(f"- `{key}` {title_s} ({rec['n']} claim(s))")
        lines.append("")

    lines.extend(["## Claims", ""])
    rows = [r for r in (pack.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        lines.append("_None._")
        lines.append("")
    for i, row in enumerate(rows, start=1):
        heading = str(row.get("heading") or "").strip()
        loc = str(row.get("loc") or "").strip()
        quote = str(row.get("quote") or "").strip()
        head = f"### {i}."
        if heading:
            head += f" {heading}"
        if loc:
            head += f" ({loc})"
        lines.append(head)
        lines.append("")
        if quote:
            clip = quote if len(quote) <= 280 else quote[:279].rstrip() + "…"
            lines.append(f"> {clip}")
            lines.append("")
        hits = [h for h in (row.get("hits") or []) if isinstance(h, dict)]
        if not hits:
            lines.append("_No library hits._")
            lines.append("")
            continue
        for hit in hits:
            key = hit.get("item_key") or ""
            title_s = (hit.get("title") or "").replace("|", "/")
            pages = hit.get("pages") or ""
            score = hit.get("score")
            score_s = f"{score}" if score is not None else ""
            bits = [f"`{key}`", title_s]
            if pages:
                bits.append(str(pages))
            if score_s:
                bits.append(score_s)
            lines.append("- " + " · ".join(b for b in bits if b))
            passage = str(hit.get("passage") or "").strip()
            if passage:
                lines.append(f"  > {passage}")
        lines.append("")

    skips = [s for s in (pack.get("skips") or []) if isinstance(s, dict)]
    if skips:
        lines.extend(["## Skips", ""])
        for skip in skips:
            reason = skip.get("reason") or ""
            heading = skip.get("heading") or ""
            quote = skip.get("quote") or ""
            loc = skip.get("loc") or ""
            label = heading or quote[:80]
            extra = f" ({loc})" if loc else ""
            lines.append(f"- `{reason}`{extra}: {label}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_pack(
    cfg: Config,
    payload: dict[str, Any],
    *,
    stamp: str | None = None,
) -> Path:
    cid = str(payload.get("stuff_id") or "file")
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = cfg.state_dir / "stuff" / cid / stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload.setdefault("schema", SCHEMA)
    payload["created_at"] = (
        payload.get("created_at") or datetime.now(tz=timezone.utc).isoformat()
    )
    write_json(folder / "pack.json", payload)
    (folder / "pack.md").write_text(render_markdown(payload), encoding="utf-8")
    return folder


def load_pack(folder: Path) -> dict[str, Any] | None:
    path = folder / "pack.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
