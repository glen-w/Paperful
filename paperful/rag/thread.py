"""Follow-up Ask threads: rewritten retrieval query plus on-disk turns."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..llm import LLMClient, get_client

SCHEMA = "paperful.rag.thread.v1"
_REWRITE = (
    "Rewrite the follow-up as a standalone search query over a library of papers. "
    "Keep technical terms. Return only the query, no quotes.\n\n"
    "Conversation:\n{history}\n\nFollow-up: {question}\n"
)


def threads_dir(state_dir: Path) -> Path:
    return state_dir / "rag" / "threads"


@dataclass
class Thread:
    thread_id: str
    turns: list[dict[str, str]] = field(default_factory=list)
    last_query: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "id": self.thread_id,
            "turns": self.turns,
            "last_query": self.last_query,
        }


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def load_thread(state_dir: Path, thread_id: str) -> Thread:
    path = threads_dir(state_dir) / f"{thread_id}.json"
    if not path.is_file():
        return Thread(thread_id=thread_id)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Thread(thread_id=thread_id)
    turns = body.get("turns") if isinstance(body, dict) else None
    if not isinstance(turns, list):
        turns = []
    clean: list[dict[str, str]] = []
    for row in turns:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        content = str(row.get("content") or "")
        if role and content:
            clean.append({"role": role, "content": content})
    return Thread(
        thread_id=str(body.get("id") or thread_id),
        turns=clean,
        last_query=str(body.get("last_query") or ""),
    )


def save_thread(state_dir: Path, thread: Thread) -> Path:
    dest = threads_dir(state_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{thread.thread_id}.json"
    path.write_text(json.dumps(thread.to_json(), indent=2, ensure_ascii=False) + "\n")
    return path


def format_history(turns: list[dict[str, str]]) -> str:
    lines = []
    for row in turns:
        lines.append(f"{row.get('role', '')}: {row.get('content', '')}")
    return "\n".join(lines)


def rewrite_query(
    cfg: Config,
    question: str,
    history: list[dict[str, str]],
    *,
    client: LLMClient | None = None,
) -> str:
    """Standalone retrieval query. Falls back to the follow-up on empty history or error."""
    q = (question or "").strip()
    if not q:
        return q
    if not history:
        return q
    prompt = _REWRITE.format(history=format_history(history), question=q)
    used = client or get_client(cfg)
    try:
        from ..llm import CompletionRequest, ctx_tokens_for

        text = used.complete(
            CompletionRequest(
                model=(cfg.rag_model or cfg.llm_model).strip(),
                prompt=prompt,
                timeout_seconds=min(30, cfg.llm_timeout_s),
                num_ctx=ctx_tokens_for(prompt, max_num_ctx=cfg.llm_max_num_ctx),
            )
        )
    except Exception:
        return q
    line = (text or "").strip().splitlines()[0].strip().strip('"').strip("'")
    return line or q
