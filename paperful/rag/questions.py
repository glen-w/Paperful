"""Extract research questions posed by papers (rules + optional LLM)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import Config
from ..llm import ChatRequest, LLMClient, ctx_tokens_for, get_client
from ..store import load_json, write_json
from .extract import TEXT_SCHEMA, text_cache_path
from .ledger import Ledger
from .retrieve import scope_keys

SCHEMA = "paperful.rag.questions.v1"
_MAX_LLM_CHARS = 12_000

_HEADING = re.compile(
    r"(?im)^\s*(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(research\s+questions?|aims?(?:\s+and\s+objectives)?|objectives?|"
    r"questions?\s+addressed)\s*:?\s*$"
)
_WE_ASK = re.compile(
    r"(?i)\b(?:we|this\s+(?:paper|study|article)|the\s+present\s+study)\s+"
    r"(?:ask(?:s|ed)?(?:\s+whether)?|examine(?:s|d)?|investigate(?:s|d)?|"
    r"address(?:es|ed)?|seek(?:s|ing)?\s+to\s+(?:understand|determine))\b"
    r"[^.?!]{10,280}[.?!]"
)
_NUMBERED = re.compile(
    r"(?m)^\s*(?:\(?[RQrq]\s*\d+\)?|\d+[\).]|[-*•])\s+(.+\?)\s*$"
)
_QUESTION_LINE = re.compile(r"(?m)^\s*(.+\?)\s*$")

_LLM_SYSTEM = """\
Extract research questions the paper itself poses. Use ONLY the excerpt.
Return a JSON array of strings. Each string must be a question that appears \
in or is clearly paraphrased from the excerpt. If none, return [].
No markdown fences. No commentary."""


@dataclass
class ExtractedQuestion:
    id: str
    text: str
    provenance: str  # rule | llm
    pages: str = ""


@dataclass
class ItemQuestions:
    schema: str
    item_key: str
    title: str
    year: int | None
    questions: list[ExtractedQuestion] = field(default_factory=list)


def questions_dir(cfg: Config) -> Path:
    return cfg.state_dir / "rag" / "questions"


def item_path(cfg: Config, key: str) -> Path:
    return questions_dir(cfg) / f"{key}.json"


def _qid(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:12]


def _load_pages(cfg: Config, key: str) -> list[str]:
    stored = load_json(text_cache_path(cfg, key))
    if (
        stored
        and stored.get("schema") == TEXT_SCHEMA
        and isinstance(stored.get("pages"), list)
    ):
        return [str(p) for p in stored["pages"]]
    return []


def _section_after_heading(pages: list[str]) -> str:
    text = "\n".join(pages)
    match = _HEADING.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    # Stop at the next all-caps-ish or numbered major heading.
    stop = re.search(
        r"(?m)^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:Introduction|Methods?|Results?|"
        r"Discussion|Conclusion|References|Bibliography|Background)\b",
        rest,
    )
    return rest[: stop.start()] if stop else rest[:4000]


def extract_rules(pages: list[str], abstract: str = "") -> list[ExtractedQuestion]:
    """Deterministic RQs from headings, 'we ask', and numbered questions."""
    found: list[ExtractedQuestion] = []
    seen: set[str] = set()

    def add(text: str, pages_label: str = "") -> None:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if len(cleaned) < 12 or cleaned in seen:
            return
        if not cleaned.endswith("?"):
            cleaned = cleaned.rstrip(".!;:") + "?"
        seen.add(cleaned)
        found.append(
            ExtractedQuestion(
                id=_qid(cleaned),
                text=cleaned,
                provenance="rule",
                pages=pages_label,
            )
        )

    blob = _section_after_heading(pages)
    if blob:
        for match in _NUMBERED.finditer(blob):
            add(match.group(1))
        for match in _QUESTION_LINE.finditer(blob):
            line = match.group(1).strip()
            if len(line) < 80 or line.endswith("?"):
                add(line)

    body = "\n".join(pages[:3]) + "\n" + (abstract or "")
    for match in _WE_ASK.finditer(body):
        add(match.group(0))
    for match in _NUMBERED.finditer(abstract or ""):
        add(match.group(1), "abstract")
    for match in _QUESTION_LINE.finditer(abstract or ""):
        line = match.group(1).strip()
        if "?" in line:
            add(line, "abstract")
    return found


def extract_llm(
    cfg: Config,
    pages: list[str],
    abstract: str = "",
    *,
    client: LLMClient | None = None,
) -> list[ExtractedQuestion]:
    """LLM pass; keep only strings grounded in the excerpt."""
    excerpt = (abstract or "").strip() + "\n\n" + "\n".join(pages[:6])
    excerpt = excerpt.strip()[:_MAX_LLM_CHARS]
    if len(excerpt) < 40:
        return []
    client = client or get_client(cfg)
    request = ChatRequest(
        model=(cfg.rag_model or cfg.llm_model).strip(),
        messages=[
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": f"Excerpt:\n\n{excerpt}"},
        ],
        timeout_seconds=cfg.llm_timeout_s,
        num_ctx=ctx_tokens_for(excerpt, max_num_ctx=cfg.llm_max_num_ctx),
    )
    text = "".join(client.chat_stream(request)).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    norm = re.sub(r"\s+", " ", excerpt.lower())
    out: list[ExtractedQuestion] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        cleaned = re.sub(r"\s+", " ", item.strip())
        if len(cleaned) < 12 or cleaned in seen:
            continue
        # Grounding: enough distinctive words from the question appear in excerpt.
        words = [w for w in re.findall(r"[a-zA-Z]{4,}", cleaned.lower()) if w]
        if not words:
            continue
        hits = sum(1 for w in words if w in norm)
        if hits < max(2, len(words) // 3):
            continue
        if not cleaned.endswith("?"):
            cleaned = cleaned.rstrip(".!;:") + "?"
        seen.add(cleaned)
        out.append(
            ExtractedQuestion(id=_qid(cleaned), text=cleaned, provenance="llm")
        )
    return out


def _abstract_for(cfg: Config, row) -> str:
    for rel in row.dirs:
        record = load_json(cfg.out_dir / rel / "record.json")
        if record and str(record.get("item_key") or "") == row.key:
            return str(record.get("abstract") or "")
    return ""


def extract_item(
    cfg: Config,
    key: str,
    *,
    ledger: Ledger,
    use_llm: bool = False,
    client: LLMClient | None = None,
) -> ItemQuestions | None:
    row = ledger.get(key)
    if row is None:
        return None
    pages = _load_pages(cfg, key)
    abstract = _abstract_for(cfg, row)
    questions = extract_rules(pages, abstract)
    if use_llm:
        for q in extract_llm(cfg, pages, abstract, client=client):
            if q.text not in {x.text for x in questions}:
                questions.append(q)
    return ItemQuestions(
        schema=SCHEMA,
        item_key=key,
        title=row.title,
        year=row.year,
        questions=questions,
    )


def write_item(cfg: Config, item: ItemQuestions) -> Path:
    path = item_path(cfg, item.item_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        path,
        {
            "schema": item.schema,
            "item_key": item.item_key,
            "title": item.title,
            "year": item.year,
            "questions": [asdict(q) for q in item.questions],
        },
    )
    return path


def load_item(cfg: Config, key: str) -> ItemQuestions | None:
    data = load_json(item_path(cfg, key))
    if not data or data.get("schema") != SCHEMA:
        return None
    questions = [
        ExtractedQuestion(
            id=str(q.get("id") or _qid(str(q.get("text") or ""))),
            text=str(q.get("text") or ""),
            provenance=str(q.get("provenance") or "rule"),
            pages=str(q.get("pages") or ""),
        )
        for q in (data.get("questions") or [])
        if isinstance(q, dict) and q.get("text")
    ]
    return ItemQuestions(
        schema=SCHEMA,
        item_key=str(data.get("item_key") or key),
        title=str(data.get("title") or ""),
        year=data.get("year"),
        questions=questions,
    )


def extract_scope(
    cfg: Config,
    *,
    ledger: Ledger,
    collections: list[str] | None = None,
    item_keys: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    item_types: frozenset[str] | None = None,
    use_llm: bool = False,
    client: LLMClient | None = None,
    limit: int | None = None,
) -> list[ItemQuestions]:
    keys = scope_keys(
        ledger,
        collections=collections or (),
        item_keys=item_keys or (),
        year_from=year_from,
        year_to=year_to,
        item_types=item_types,
    )
    ordered = sorted(keys) if keys is not None else sorted(ledger.keys())
    if limit is not None:
        ordered = ordered[: max(0, limit)]
    out: list[ItemQuestions] = []
    for key in ordered:
        item = extract_item(cfg, key, ledger=ledger, use_llm=use_llm, client=client)
        if item is not None:
            out.append(item)
    return out
