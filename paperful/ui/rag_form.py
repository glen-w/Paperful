"""Parse Index RAG forms (scope, prompts, questions)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config, _resolve_prompt_path
from ..zot import resolve_item_types

MAX_INLINE_PROMPT = 64 * 1024
MAX_UPLOAD_PROMPT = 256 * 1024
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class ResolvedPrompt:
    prompt_text: str | None = None
    prompt_path: str | None = None


@dataclass(frozen=True)
class RagScope:
    collection: str
    year_from: int | None
    year_to: int | None
    item_keys: list[str]
    item_types: frozenset[str] | None
    top_k: int | None
    force: bool


def prompts_dir(cfg: Config) -> Path:
    return cfg.state_dir / "prompts"


def parse_item_keys(raw: object) -> list[str]:
    text = str(raw or "")
    keys: list[str] = []
    for part in re.split(r"[\n,]+", text):
        key = part.strip()
        if key:
            keys.append(key)
    return keys


def parse_item_types_field(raw: object) -> frozenset[str] | None:
    parts = [t.strip() for t in str(raw or "").split(",") if t.strip()]
    if not parts:
        return None
    return resolve_item_types(parts)


def parse_rag_scope(
    form: Any,
    collection: str,
    *,
    year_from: int | None,
    year_to: int | None,
    include_force: bool = False,
) -> RagScope:
    return RagScope(
        collection=(collection or "").strip(),
        year_from=year_from,
        year_to=year_to,
        item_keys=parse_item_keys(form.get("item_keys")),
        item_types=parse_item_types_field(form.get("item_type")),
        top_k=_positive_int(form.get("top_k")),
        force=include_force and form.get("force") == "1",
    )


def _positive_int(raw: object) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    value = int(text)
    if value < 1:
        raise ValueError("top_k must be positive")
    return value


def scope_has_target(scope: RagScope, *, whole_library: bool = False) -> bool:
    if scope.item_keys:
        return True
    if scope.collection:
        return True
    return whole_library


def resolve_prompt_from_form(
    cfg: Config,
    form: Any,
    *,
    upload_bytes: bytes | None = None,
    upload_name: str | None = None,
) -> ResolvedPrompt:
    """Inline → upload → path field → saved select (then config/focus downstream)."""
    inline = str(form.get("prompt_inline") or "").strip()
    if len(inline) > MAX_INLINE_PROMPT:
        raise ValueError("prompt too long")
    if inline:
        return ResolvedPrompt(prompt_text=inline)

    if upload_bytes:
        if len(upload_bytes) > MAX_UPLOAD_PROMPT:
            raise ValueError("upload too large")
        text = upload_bytes.decode("utf-8", errors="replace").strip()
        if not text:
            raise ValueError("upload is empty")
        path = _persist_upload(cfg, upload_bytes, upload_name)
        if path is not None:
            return ResolvedPrompt(prompt_path=str(path), prompt_text=None)
        return ResolvedPrompt(prompt_text=text)

    path_raw = str(form.get("prompt_path") or "").strip()
    if path_raw:
        source = cfg.config_path or cfg.state_dir / "config.toml"
        resolved = _resolve_prompt_path(path_raw, source)
        if resolved == "default":
            raise ValueError("prompt path invalid")
        path = Path(resolved)
        if not path.is_file():
            raise ValueError(f"prompt file not found: {path}")
        return ResolvedPrompt(prompt_path=str(path))

    saved = str(form.get("prompt_saved") or "").strip()
    if saved and saved != "default":
        path = safe_prompt_child(prompts_dir(cfg), saved)
        if path is None:
            raise ValueError("saved prompt not found")
        return ResolvedPrompt(prompt_path=str(path))

    return ResolvedPrompt()


def _persist_upload(cfg: Config, data: bytes, name: str | None) -> Path | None:
    """Write upload under ``state/gui/uploads/``; return path or None on failure."""
    raw = Path(name or "prompt.md").name
    safe = _SAFE_NAME.sub("-", raw).strip("-") or "prompt.md"
    if not safe.endswith((".md", ".txt")):
        safe += ".md"
    dest = cfg.state_dir / "gui" / "uploads"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / safe
        path.write_bytes(data)
        return path
    except OSError:
        return None


def safe_prompt_child(root: Path, name: str) -> Path | None:
    if not name or _SAFE_NAME.sub("", name) != name or not name.endswith((".md", ".txt")):
        return None
    try:
        base = root.resolve()
        path = base.joinpath(name).resolve()
        path.relative_to(base)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def save_prompt_as(cfg: Config, name: str, text: str) -> Path | None:
    """Save prompt text under ``state/prompts/``. Empty name → no-op."""
    safe = _SAFE_NAME.sub("-", (name or "").strip()).strip("-")
    if not safe:
        return None
    if not safe.endswith((".md", ".txt")):
        safe += ".md"
    body = (text or "").strip()
    if not body:
        return None
    folder = prompts_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe
    path.write_text(body + "\n", encoding="utf-8")
    return path


def list_saved_prompts(cfg: Config) -> list[dict[str, str]]:
    root = prompts_dir(cfg)
    if not root.is_dir():
        return []
    out: list[dict[str, str]] = []
    for path in sorted(root.glob("*.md")) + sorted(root.glob("*.txt")):
        if path.is_file():
            out.append({"name": path.name, "label": path.stem})
    return out


def read_questions_upload(form: Any, upload_bytes: bytes | None) -> list[str]:
    from ..snowball.seeds import parse_seed_lines

    if upload_bytes:
        text = upload_bytes.decode("utf-8", errors="replace")
        return parse_seed_lines(text)
    return parse_seed_lines(str(form.get("questions") or ""))
