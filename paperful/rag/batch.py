"""Batch cited Q&A from a file or stdin. Resume-safe packs under ``state/ask-batch``."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm import LLMClient
from ..llm.embed import Embedder, embed_fingerprint
from ..snowball.seeds import parse_seed_lines, read_seeds_text
from .answer import answer
from .index import Index, index_dir
from .ledger import Ledger
from .prompt import PROMPT_VERSION, resolve_system_prompt

SCHEMA = "paperful.ask_batch.v1"
_STAMP = re.compile(r"^\d{8}T\d{6}Z")


@dataclass
class BatchRow:
    question: str
    question_sha: str
    answer: str = ""
    cited: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    retrieve_as: str = ""
    skipped: bool = False
    error: str = ""


@dataclass
class BatchPack:
    schema: str
    stamp: str
    focus: str
    prompt: str
    prompt_version: int
    embed_fingerprint: str
    model: str
    scope: dict[str, Any]
    questions: int
    answered: int
    skipped: int
    failed: int
    rows: list[BatchRow] = field(default_factory=list)


def question_sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def batch_dir(cfg: Config) -> Path:
    return cfg.state_dir / "ask-batch"


def cache_dir(cfg: Config) -> Path:
    return batch_dir(cfg) / "by-hash"


def index_fingerprint(cfg: Config) -> str:
    """Stable tip for resume: embed folder name + ledger mtime/size."""
    folder = index_dir(cfg)
    tip = embed_fingerprint(cfg.rag_embed_provider, cfg.rag_embed_model)
    ledger = folder / "ingest.jsonl"
    if ledger.is_file():
        st = ledger.stat()
        tip = f"{tip}:{st.st_mtime_ns}:{st.st_size}"
    return tip


def resume_key(
    *,
    question: str,
    focus: str,
    prompt_label: str,
    index_fp: str,
) -> str:
    payload = "|".join(
        [
            question_sha(question),
            focus,
            prompt_label,
            str(PROMPT_VERSION),
            index_fp,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(cfg: Config, key: str) -> Path:
    return cache_dir(cfg) / f"{key}.json"


def load_cached(cfg: Config, key: str) -> BatchRow | None:
    path = _cache_path(cfg, key)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("question"):
        return None
    return BatchRow(
        question=str(data["question"]),
        question_sha=str(data.get("question_sha") or question_sha(data["question"])),
        answer=str(data.get("answer") or ""),
        cited=list(data.get("cited") or []),
        sources=list(data.get("sources") or []),
        retrieve_as=str(data.get("retrieve_as") or data["question"]),
        skipped=True,
    )


def save_cached(cfg: Config, key: str, row: BatchRow) -> None:
    path = _cache_path(cfg, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(row), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_questions(path: str, *, stdin=None) -> list[str]:
    """One question per line from a file or ``-`` (stdin)."""
    text = read_seeds_text(path, stdin=stdin)
    return parse_seed_lines(text)


def run_batch(
    cfg: Config,
    questions: list[str],
    *,
    keys: set[str] | None = None,
    focus: str | None = None,
    prompt_path: str | None = None,
    prompt_text: str | None = None,
    k: int | None = None,
    force: bool = False,
    scope: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    embedder: Embedder | None = None,
    index: Index | None = None,
    ledger: Ledger | None = None,
) -> BatchPack:
    """Answer each question; reuse cache when the resume key matches."""
    path = prompt_path if prompt_path is not None else (cfg.rag_prompt or None)
    system, focus_name, prompt_label = resolve_system_prompt(
        focus=focus if focus is not None else cfg.rag_focus,
        prompt_path=path,
        prompt_text=prompt_text,
    )
    del system  # answer() resolves the same way
    index_fp = index_fingerprint(cfg)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows: list[BatchRow] = []
    answered = skipped = failed = 0
    for question in questions:
        q = question.strip()
        if not q:
            continue
        key = resume_key(
            question=q,
            focus=focus_name,
            prompt_label=prompt_label,
            index_fp=index_fp,
        )
        if not force:
            cached = load_cached(cfg, key)
            if cached is not None:
                rows.append(cached)
                skipped += 1
                continue
        try:
            reply = answer(
                cfg,
                q,
                k=k,
                keys=keys,
                focus=focus_name if focus_name != "custom" else "default",
                prompt_path=path,
                prompt_text=prompt_text,
                client=client,
                embedder=embedder,
                index=index,
                ledger=ledger,
            )
            text = reply.read()
            cited = reply.cited()
            row = BatchRow(
                question=q,
                question_sha=question_sha(q),
                answer=text,
                cited=[s.marker for s in cited],
                sources=[
                    {
                        "marker": s.marker,
                        "itemKey": s.item_key,
                        "title": s.title,
                        "pages": s.pages,
                    }
                    for s in reply.sources
                ],
                retrieve_as=q,
            )
            save_cached(cfg, key, row)
            rows.append(row)
            answered += 1
        except Exception as exc:  # noqa: BLE001 — pack records the failure
            rows.append(
                BatchRow(
                    question=q,
                    question_sha=question_sha(q),
                    error=str(exc),
                )
            )
            failed += 1
    return BatchPack(
        schema=SCHEMA,
        stamp=stamp,
        focus=focus_name,
        prompt=prompt_label,
        prompt_version=PROMPT_VERSION,
        embed_fingerprint=index_fp,
        model=(cfg.rag_model or cfg.llm_model).strip(),
        scope=scope or {},
        questions=len(rows),
        answered=answered,
        skipped=skipped,
        failed=failed,
        rows=rows,
    )


def write_pack(cfg: Config, pack: BatchPack) -> Path:
    """Write ``pack.json`` + ``answers.md`` under ``state/ask-batch/<stamp>/``."""
    folder = batch_dir(cfg) / pack.stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": pack.schema,
        "stamp": pack.stamp,
        "focus": pack.focus,
        "prompt": pack.prompt,
        "prompt_version": pack.prompt_version,
        "embed_fingerprint": pack.embed_fingerprint,
        "model": pack.model,
        "scope": pack.scope,
        "questions": pack.questions,
        "answered": pack.answered,
        "skipped": pack.skipped,
        "failed": pack.failed,
        "rows": [asdict(row) for row in pack.rows],
    }
    (folder / "pack.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "answers.md").write_text(_answers_md(pack), encoding="utf-8")
    return folder


def _answers_md(pack: BatchPack) -> str:
    lines = [
        f"# Ask batch {pack.stamp}",
        "",
        f"- focus: `{pack.focus}`",
        f"- answered: {pack.answered} · skipped: {pack.skipped} · failed: {pack.failed}",
        "",
    ]
    for i, row in enumerate(pack.rows, 1):
        lines.append(f"## Q{i}. {row.question}")
        lines.append("")
        if row.error:
            lines.append(f"**Error:** {row.error}")
        else:
            tag = " (cached)" if row.skipped else ""
            lines.append(row.answer + tag)
            if row.sources:
                lines.append("")
                lines.append("Sources")
                for src in row.sources:
                    pages = src.get("pages") or []
                    page_s = f" {', '.join(pages)}." if pages else ""
                    lines.append(
                        f"- [{src.get('marker')}] {src.get('title')}{page_s} "
                        f"[{src.get('itemKey')}]"
                    )
        lines.append("")
    return "\n".join(lines)
