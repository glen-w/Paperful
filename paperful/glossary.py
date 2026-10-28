"""House glossary for critique acronym expansions.

``state/glossary/*.json`` holds canonical long forms and optional wrong-form
aliases. Critique fuzzy-matches parenthetical expansions and bare phrases.
``paperful glossary export-vale`` writes exact alias swaps for Vale.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .config import Config

SCHEMA = "paperful.glossary.v1"
DEFAULT_SIMILARITY_MIN = 0.88
MIN_PHRASE_CONTENT_WORDS = 3
MAX_HITS_PER_CODE = 25
_LEADING_ARTICLES = frozenset({"the", "a", "an"})
_SMALL = frozenset(
    {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "by"}
)
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
# Parenthetical acronym; left-hand expansion is bounded by glossary widths
# (not a greedy multi-word span that swallows "Part IV on" / "of").
_TOKEN_PAREN_RE = re.compile(r"\(([A-Z]{2,12})\)")
# ``TOKEN (Full Name)`` — expansion is inside parens, so length is bounded.
_TOKEN_THEN_EXPANSION_RE = re.compile(
    r"\b([A-Z]{2,12})\s+\(([A-Z][A-Za-z0-9][A-Za-z0-9 '’\-]{2,80})\)"
)


@dataclass(frozen=True)
class GlossaryEntry:
    token: str
    expansion: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlossaryHit:
    code: str
    start: int
    end: int
    quote: str
    token: str
    suggested: str
    detail: str


@dataclass(frozen=True)
class GlossaryIssue:
    path: str
    message: str
    level: str = "error"  # error | warning


def resolve_glossary_dir(cfg: Config) -> Path:
    return cfg.glossary_dir


def normalize_phrase(text: str) -> str:
    """NFKC, lowercase, strip punctuation, collapse space, drop leading articles."""
    raw = unicodedata.normalize("NFKC", text or "")
    raw = raw.replace("\u2019", "'").replace("\u2018", "'")
    raw = re.sub(r"[^\w\s]+", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"\s+", " ", raw).strip().lower()
    words = raw.split()
    while words and words[0] in _LEADING_ARTICLES:
        words.pop(0)
    return " ".join(words)


def phrase_similarity(left: str, right: str) -> float:
    a = normalize_phrase(left)
    b = normalize_phrase(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def content_word_count(text: str) -> int:
    return sum(1 for word in normalize_phrase(text).split() if word not in _SMALL)


def tokenize(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in _WORD.finditer(text or "")]


def load_glossary(
    cfg: Config,
) -> tuple[tuple[GlossaryEntry, ...], tuple[GlossaryIssue, ...]]:
    """Union ``entries`` from every JSON file. Later files override a token."""
    root = resolve_glossary_dir(cfg)
    if not root.is_dir():
        return (), ()
    by_token: dict[str, GlossaryEntry] = {}
    issues: list[GlossaryIssue] = []
    for path in sorted(root.glob("*.json")):
        entries, file_issues = _parse_glossary_file(path)
        issues.extend(file_issues)
        for entry in entries:
            if entry.token in by_token:
                issues.append(
                    GlossaryIssue(
                        path=str(path),
                        message=f"token {entry.token} overrides an earlier file",
                        level="warning",
                    )
                )
            by_token[entry.token] = entry
    return tuple(by_token.values()), tuple(issues)


def _parse_glossary_file(path: Path) -> tuple[list[GlossaryEntry], list[GlossaryIssue]]:
    issues: list[GlossaryIssue] = []
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [GlossaryIssue(path=str(path), message=f"unreadable JSON: {exc}")]
    if not isinstance(body, dict):
        return [], [GlossaryIssue(path=str(path), message="root must be an object")]
    schema = str(body.get("schema") or "").strip()
    if schema and schema != SCHEMA:
        issues.append(
            GlossaryIssue(
                path=str(path),
                message=f"unexpected schema {schema!r} (expected {SCHEMA})",
                level="warning",
            )
        )
    raw_entries = body.get("entries")
    if not isinstance(raw_entries, list):
        issues.append(GlossaryIssue(path=str(path), message="missing entries array"))
        return [], issues
    entries: list[GlossaryEntry] = []
    seen: set[str] = set()
    for i, row in enumerate(raw_entries):
        if not isinstance(row, dict):
            issues.append(
                GlossaryIssue(path=str(path), message=f"entries[{i}] must be an object")
            )
            continue
        token = str(row.get("token") or "").strip().upper()
        expansion = str(row.get("expansion") or "").strip()
        if not token:
            issues.append(
                GlossaryIssue(path=str(path), message=f"entries[{i}] missing token")
            )
            continue
        if not expansion:
            issues.append(
                GlossaryIssue(
                    path=str(path), message=f"entries[{i}] {token} missing expansion"
                )
            )
            continue
        if token in seen:
            issues.append(
                GlossaryIssue(
                    path=str(path),
                    message=f"duplicate token {token} in file",
                    level="warning",
                )
            )
        seen.add(token)
        aliases: list[str] = []
        alias_seen: set[str] = set()
        for alias in row.get("aliases") or []:
            text = str(alias or "").strip()
            key = normalize_phrase(text)
            if not text or not key or key in alias_seen:
                continue
            if key == normalize_phrase(expansion):
                continue
            alias_seen.add(key)
            aliases.append(text)
        entries.append(
            GlossaryEntry(token=token, expansion=expansion, aliases=tuple(aliases))
        )
    return entries, issues


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    for other_start, other_end in spans:
        if start < other_end and other_start < end:
            return True
    return False


def _is_known_mismatch(
    text: str, entry: GlossaryEntry, *, similarity_min: float
) -> bool:
    norm = normalize_phrase(text)
    if not norm or norm == normalize_phrase(entry.expansion):
        return False
    for alias in entry.aliases:
        if norm == normalize_phrase(alias):
            return True
    if phrase_similarity(text, entry.expansion) >= similarity_min:
        return True
    return any(
        phrase_similarity(text, alias) >= similarity_min for alias in entry.aliases
    )


def _entry_phrase_widths(entry: GlossaryEntry) -> tuple[int, ...]:
    widths = {len(tokenize(entry.expansion))}
    for alias in entry.aliases:
        n = len(tokenize(alias))
        if n:
            widths.add(n)
    return tuple(sorted(w for w in widths if w >= 1))


def _window_starts_like_target(window_tokens: list[str], target: str) -> bool:
    """Reject windows that begin with a function word the target does not."""
    if not window_tokens:
        return False
    first = window_tokens[0].lower()
    if first not in _SMALL:
        return True
    target_tokens = tokenize(target)
    if not target_tokens:
        return False
    return target_tokens[0][2].lower() in _SMALL


def _best_left_expansion(
    body: str,
    tokens: list[tuple[int, int, str]],
    paren_start: int,
    entry: GlossaryEntry,
    *,
    similarity_min: float,
) -> tuple[int, int, str] | None:
    """Pick a left-hand expansion ending at ``paren_start``, width from glossary.

    Prefers a known mismatch (alias / near-miss) over a shorter suffix that
    happens to equal the canonical expansion — e.g. ``Maritime Areas … (BBNJ)``
    must not be silenced because ``Areas …`` alone is canonical.
    """
    before = [tok for tok in tokens if tok[1] <= paren_start]
    if not before:
        return None
    # (score, -width, start, exp_end, expansion_text) — higher score, then
    # fewer tokens, so we do not drag in "Part IV on" when a short match works.
    best: tuple[float, int, int, int, str] | None = None
    canonical_start: int | None = None
    for width in _entry_phrase_widths(entry):
        if width > len(before):
            continue
        chosen = before[-width:]
        words = [tok[2] for tok in chosen]
        if not _window_starts_like_target(words, entry.expansion) and not any(
            _window_starts_like_target(words, alias) for alias in entry.aliases
        ):
            continue
        expansion_text = body[chosen[0][0] : chosen[-1][1]]
        start = chosen[0][0]
        exp_end = chosen[-1][1]
        if normalize_phrase(expansion_text) == normalize_phrase(entry.expansion):
            canonical_start = start
            continue
        if not _is_known_mismatch(
            expansion_text, entry, similarity_min=similarity_min
        ):
            continue
        score = max(
            [phrase_similarity(expansion_text, entry.expansion)]
            + [phrase_similarity(expansion_text, alias) for alias in entry.aliases]
        )
        candidate = (score, -width, start, exp_end, expansion_text)
        if best is None or candidate > best:
            best = candidate
    if best is not None:
        return best[2], best[3], best[4]
    if canonical_start is not None:
        # Signal "correct expansion" to the caller via a reserved span only.
        return canonical_start, paren_start, ""
    return None


def scan_glossary(
    body: str,
    entries: tuple[GlossaryEntry, ...] | list[GlossaryEntry],
    *,
    similarity_min: float = DEFAULT_SIMILARITY_MIN,
) -> list[GlossaryHit]:
    """Find expansion and phrase mismatches. Offsets are into ``body``."""
    if not body.strip() or not entries:
        return []
    threshold = min(1.0, max(0.5, float(similarity_min)))
    by_token = {entry.token: entry for entry in entries}
    tokens = tokenize(body)
    expansion_spans: list[tuple[int, int]] = []
    hits: list[GlossaryHit] = []

    # Form: Full Name (TOKEN) — bound left span to glossary phrase widths.
    for match in _TOKEN_PAREN_RE.finditer(body):
        token = match.group(1).upper()
        entry = by_token.get(token)
        if entry is None:
            continue
        # Skip ``TOKEN (Full Name)`` handled below (token immediately before '(').
        prev = [tok for tok in tokens if tok[1] <= match.start()]
        if prev and prev[-1][2].upper() == token and prev[-1][1] < match.start():
            gap = body[prev[-1][1] : match.start()]
            if gap.strip() == "":
                continue
        picked = _best_left_expansion(
            body, tokens, match.start(), entry, similarity_min=threshold
        )
        if picked is None:
            expansion_spans.append((match.start(), match.end()))
            continue
        start, _exp_end, expansion_text = picked
        end = match.end()
        expansion_spans.append((start, end))
        if not expansion_text:
            # Canonical ``Expansion (TOKEN)`` — reserve span, no finding.
            continue
        quote = body[start:end]
        suggested = f"{entry.expansion} ({entry.token})"
        hits.append(
            GlossaryHit(
                code="acronym_expansion_mismatch",
                start=start,
                end=end,
                quote=quote,
                token=entry.token,
                suggested=suggested,
                detail=(
                    f"{entry.token} expansion {expansion_text!r} should be "
                    f"{entry.expansion!r}."
                ),
            )
        )

    # Form: TOKEN (Full Name)
    for match in _TOKEN_THEN_EXPANSION_RE.finditer(body):
        token = match.group(1).upper()
        expansion_text = match.group(2) or ""
        entry = by_token.get(token)
        if entry is None or not expansion_text.strip():
            continue
        if _overlaps(match.start(), match.end(), expansion_spans):
            continue
        expansion_spans.append((match.start(), match.end()))
        if normalize_phrase(expansion_text) == normalize_phrase(entry.expansion):
            continue
        if not _is_known_mismatch(expansion_text, entry, similarity_min=threshold):
            continue
        quote = body[match.start() : match.end()]
        suggested = f"{entry.token} ({entry.expansion})"
        hits.append(
            GlossaryHit(
                code="acronym_expansion_mismatch",
                start=match.start(),
                end=match.end(),
                quote=quote,
                token=entry.token,
                suggested=suggested,
                detail=(
                    f"{entry.token} expansion {expansion_text!r} should be "
                    f"{entry.expansion!r}."
                ),
            )
        )

    used_spans = list(expansion_spans)
    for entry in entries:
        targets: list[str] = []
        if content_word_count(entry.expansion) >= MIN_PHRASE_CONTENT_WORDS:
            targets.append(entry.expansion)
        targets.extend(entry.aliases)
        targets.sort(key=lambda text: len(tokenize(text)), reverse=True)
        seen_starts: set[int] = set()
        for target in targets:
            words = tokenize(target)
            width = len(words)
            if width < 1 or width > len(tokens):
                continue
            fuzzy = content_word_count(target) >= MIN_PHRASE_CONTENT_WORDS
            for i in range(0, len(tokens) - width + 1):
                start, _, _ = tokens[i]
                end = tokens[i + width - 1][1]
                if start in seen_starts or _overlaps(start, end, used_spans):
                    continue
                window_toks = [tok[2] for tok in tokens[i : i + width]]
                if not _window_starts_like_target(window_toks, target):
                    continue
                window = " ".join(window_toks)
                if normalize_phrase(window) == normalize_phrase(entry.expansion):
                    continue
                if fuzzy:
                    matched = phrase_similarity(window, target) >= threshold
                else:
                    matched = normalize_phrase(window) == normalize_phrase(target)
                if not matched:
                    continue
                if not _is_known_mismatch(window, entry, similarity_min=threshold):
                    continue
                seen_starts.add(start)
                used_spans.append((start, end))
                quote = body[start:end]
                hits.append(
                    GlossaryHit(
                        code="acronym_phrase_mismatch",
                        start=start,
                        end=end,
                        quote=quote,
                        token=entry.token,
                        suggested=entry.expansion,
                        detail=(
                            f"{quote!r} should be {entry.expansion!r} ({entry.token})."
                        ),
                    )
                )

    return hits


def vale_swap_yaml(entries: tuple[GlossaryEntry, ...] | list[GlossaryEntry]) -> str:
    """Vale Substitution style fragment from aliases (exact swaps only)."""
    swaps: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        canonical = entry.expansion.strip()
        token = entry.token
        for alias in entry.aliases:
            key = alias.strip()
            if not key or not canonical:
                continue
            pairs = [
                (key, canonical),
                (f"{key} ({token})", f"{canonical} ({token})"),
                (f"{token} ({key})", f"{token} ({canonical})"),
            ]
            for src, dest in pairs:
                item = (src, dest)
                if item in seen or src == dest:
                    continue
                seen.add(item)
                swaps.append(item)
    lines = [
        f"# Generated by paperful glossary export-vale ({SCHEMA}).",
        "# Merge into a Vale Substitution style. Exact aliases only; fuzzy",
        "# matches stay in paperful critique.",
        "extends: substitution",
        "message: \"Use '%s' instead of '%s'.\"",
        "level: warning",
        "ignorecase: true",
        "action:",
        "  name: replace",
    ]
    if not swaps:
        lines.append("swap: {}")
        return "\n".join(lines) + "\n"
    lines.append("swap:")
    for src, dest in swaps:
        lines.append(f"  {json.dumps(src)}: {json.dumps(dest)}")
    return "\n".join(lines) + "\n"
