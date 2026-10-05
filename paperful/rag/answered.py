"""Corpus-wide “already answered?” reports over extracted or file questions."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm import LLMClient
from ..llm.embed import Embedder
from .batch import run_batch
from .index import Index
from .ledger import Ledger
from .questions import load_item, questions_dir

SCHEMA = "paperful.rq_answered.v1"
_VERDICT = re.compile(r"\b(ANSWERED|PARTIAL|NOT_FOUND)\b", re.I)


@dataclass
class AnsweredRow:
    question: str
    asking_key: str = ""
    asking_year: int | None = None
    verdict: str = "not_found"  # answered | partial | not_found
    answer: str = ""
    cited: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    error: str = ""


@dataclass
class AnsweredPack:
    schema: str
    stamp: str
    model: str
    scope: dict[str, Any]
    questions: int
    answered: int
    partial: int
    not_found: int
    failed: int
    rows: list[AnsweredRow] = field(default_factory=list)


def answered_dir(cfg: Config) -> Path:
    return cfg.state_dir / "rq-answered"


def parse_verdict(text: str) -> str:
    match = _VERDICT.search(text or "")
    if not match:
        return "not_found"
    return match.group(1).lower()


def keys_after_item(
    ledger: Ledger,
    asking_key: str,
    *,
    base: set[str] | None = None,
) -> set[str]:
    """Items in scope with year greater than the asking paper; exclude asker."""
    asker = ledger.get(asking_key)
    ask_year = asker.year if asker else None
    pool = base if base is not None else set(ledger.keys())
    out: set[str] = set()
    for key in pool:
        if key == asking_key:
            continue
        row = ledger.get(key)
        if row is None or row.year is None:
            continue
        if ask_year is not None and row.year <= ask_year:
            continue
        out.add(key)
    return out


def questions_from_extract(
    cfg: Config, *, item_keys: list[str] | None = None
) -> list[tuple[str, str, int | None]]:
    """``(question, asking_key, asking_year)`` from ``state/rag/questions/``."""
    folder = questions_dir(cfg)
    if not folder.is_dir():
        return []
    keys = item_keys or [p.stem for p in sorted(folder.glob("*.json"))]
    out: list[tuple[str, str, int | None]] = []
    for key in keys:
        item = load_item(cfg, key)
        if item is None:
            continue
        for q in item.questions:
            out.append((q.text, item.item_key, item.year))
    return out


def run_answered(
    cfg: Config,
    questions: list[tuple[str, str, int | None]],
    *,
    keys: set[str] | None = None,
    after_item: str | None = None,
    k: int | None = None,
    force: bool = False,
    scope: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    ledger: Ledger | None = None,
) -> AnsweredPack:
    """Run batch ask with ``focus=answered``; attach asking-item metadata."""
    if ledger is None:
        from .index import ledger_path

        ledger = Ledger(ledger_path(cfg))
    search_keys = keys
    if after_item:
        search_keys = keys_after_item(ledger, after_item, base=keys)

    # Group identical question text; keep first asking provenance.
    ordered: list[tuple[str, str, int | None]] = []
    seen: set[str] = set()
    for text, ask_key, ask_year in questions:
        q = text.strip()
        if not q or q in seen:
            continue
        seen.add(q)
        ordered.append((q, ask_key, ask_year))

    pack = run_batch(
        cfg,
        [q for q, _, _ in ordered],
        keys=search_keys,
        focus="answered",
        k=k,
        force=force,
        scope=scope,
        client=client,
        embedder=embedder,
        index=index,
        ledger=ledger,
    )
    meta = {q: (ask_key, ask_year) for q, ask_key, ask_year in ordered}
    rows: list[AnsweredRow] = []
    counts = {"answered": 0, "partial": 0, "not_found": 0}
    failed = 0
    for row in pack.rows:
        ask_key, ask_year = meta.get(row.question, ("", None))
        if after_item and not ask_key:
            ask_key = after_item
            asker = ledger.get(after_item)
            ask_year = asker.year if asker else ask_year
        if row.error:
            rows.append(
                AnsweredRow(
                    question=row.question,
                    asking_key=ask_key,
                    asking_year=ask_year,
                    error=row.error,
                )
            )
            failed += 1
            continue
        verdict = parse_verdict(row.answer)
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append(
            AnsweredRow(
                question=row.question,
                asking_key=ask_key,
                asking_year=ask_year,
                verdict=verdict,
                answer=row.answer,
                cited=list(row.cited),
                sources=list(row.sources),
                skipped=row.skipped,
            )
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return AnsweredPack(
        schema=SCHEMA,
        stamp=stamp,
        model=pack.model,
        scope=scope or {},
        questions=len(rows),
        answered=counts.get("answered", 0),
        partial=counts.get("partial", 0),
        not_found=counts.get("not_found", 0),
        failed=failed,
        rows=rows,
    )


def write_pack(cfg: Config, pack: AnsweredPack) -> Path:
    folder = answered_dir(cfg) / pack.stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": pack.schema,
        "stamp": pack.stamp,
        "model": pack.model,
        "scope": pack.scope,
        "questions": pack.questions,
        "answered": pack.answered,
        "partial": pack.partial,
        "not_found": pack.not_found,
        "failed": pack.failed,
        "rows": [asdict(row) for row in pack.rows],
    }
    (folder / "pack.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "pack.md").write_text(_pack_md(pack), encoding="utf-8")
    return folder


def _pack_md(pack: AnsweredPack) -> str:
    lines = [
        f"# RQ answered {pack.stamp}",
        "",
        f"- answered: {pack.answered} · partial: {pack.partial} · "
        f"not_found: {pack.not_found} · failed: {pack.failed}",
        "",
    ]
    for i, row in enumerate(pack.rows, 1):
        ask = f" (from {row.asking_key}"
        if row.asking_year:
            ask += f", {row.asking_year}"
        ask += ")" if row.asking_key else ""
        lines.append(f"## Q{i}. [{row.verdict}] {row.question}{ask}")
        lines.append("")
        if row.error:
            lines.append(f"**Error:** {row.error}")
        else:
            lines.append(row.answer)
        lines.append("")
    return "\n".join(lines)


def file_questions(path: str, *, stdin=None) -> list[tuple[str, str, int | None]]:
    from .batch import read_questions

    return [(q, "", None) for q in read_questions(path, stdin=stdin)]
