"""Route unmatched inbox PDFs to an existing collection.

Deterministic signals first (snowball / watches, last ``-C``, DOI already in
the library, filename and PDF text vs collection titles), then an optional
LLM ranker. Never invents a collection path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .dedupe import normalize_dedupe_title
from .inbox_match import MatchResult, _JUNK_STEMS
from .resolve import normalize_doi
from .zot import Collection, Item

TIE_EPSILON = 0.08
SCORE_SNOWBALL_DOI = 0.95
SCORE_WATCH_DOI = 0.93
SCORE_DOI_LIBRARY = 0.90
SCORE_SNOWBALL_RECENCY = 0.78
SCORE_LAST_SCOPE = 0.76
RECENT_RUNS = 8
LLM_CANDIDATE_CAP = 8
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "into",
        "over",
        "under",
        "about",
        "after",
        "before",
        "between",
        "among",
        "review",
        "article",
        "journal",
        "volume",
        "issue",
        "pages",
        "http",
        "https",
        "www",
        "pdf",
        "full",
        "text",
        *_JUNK_STEMS,
    }
)
_SKIP_SNOWBALL_DIRS = frozenset({"cache", "watches"})


@dataclass
class RouteResult:
    collection: str = ""
    how: str = "none"  # snowball | watch | last_scope | doi_library | title | llm | none
    confidence: float = 0.0
    reason: str = ""
    candidates: list[tuple[str, float, str]] = field(default_factory=list)


def route_proposal_fields(routed: RouteResult) -> dict[str, Any]:
    return {
        "route_how": routed.how,
        "route_confidence": routed.confidence,
        "route_reason": routed.reason,
        "route_candidates": [
            {"collection": path, "score": score, "signal": signal}
            for path, score, signal in routed.candidates[:LLM_CANDIDATE_CAP]
        ],
    }


def route_collection(
    cfg: Config,
    backend: Any,
    matched: MatchResult,
    *,
    text: str = "",
    filename: str = "",
    items: list[Item] | None = None,
    llm_route: Callable[..., RouteResult | None] | None = None,
) -> RouteResult:
    existing = _existing_collections(backend)
    if not existing:
        return RouteResult(reason="no collections")
    votes = _collapse(
        [
            *_snowball_votes(cfg, matched, existing),
            *_watch_votes(cfg, matched, existing),
            *_last_scope_votes(cfg, existing),
            *_doi_library_votes(matched, items or [], existing),
            *_title_votes(matched, filename, text, existing),
        ]
    )
    thin, winner = _unique_winner(votes, cfg.inbox_route_min_confidence)
    if winner is not None and not _want_llm(cfg, thin=False):
        path, score, signal = winner
        return RouteResult(
            collection=path,
            how=signal,
            confidence=score,
            reason=f"{signal} {score:.2f}",
            candidates=votes,
        )
    llm_hit: RouteResult | None = None
    if _want_llm(cfg, thin=thin or winner is None):
        ranker = llm_route or _llm_route
        llm_hit = ranker(
            cfg,
            matched,
            text=text,
            filename=filename,
            candidates=votes,
            existing=existing,
        )
        if llm_hit is not None and llm_hit.collection:
            llm_hit.candidates = votes or llm_hit.candidates
            return llm_hit
    if winner is not None:
        path, score, signal = winner
        return RouteResult(
            collection=path,
            how=signal,
            confidence=score,
            reason=f"{signal} {score:.2f}",
            candidates=votes,
        )
    if llm_hit is not None:
        return llm_hit
    reason = "conflict" if votes and thin else "thin"
    return RouteResult(how="none", reason=reason, candidates=votes)


def _existing_collections(backend: Any) -> dict[str, Collection]:
    if backend is None or not hasattr(backend, "collections"):
        return {}
    try:
        raw = backend.collections()
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Collection] = {}
    for col in raw.values():
        path = str(getattr(col, "path", "") or "").strip().strip("/")
        if path:
            out[path] = col
    return out


def _resolve_existing(spec: str, existing: dict[str, Collection]) -> str:
    want = (spec or "").strip().strip("/")
    if not want:
        return ""
    if want in existing:
        return want
    hits = [
        path
        for path, col in existing.items()
        if col.name == want or path.endswith(f"/{want}")
    ]
    if len(hits) == 1:
        return hits[0]
    return ""


def _collapse(
    votes: Iterable[tuple[str, float, str]],
) -> list[tuple[str, float, str]]:
    best: dict[str, tuple[float, str]] = {}
    for path, score, signal in votes:
        if not path or score <= 0:
            continue
        prev = best.get(path)
        if prev is None or score > prev[0]:
            best[path] = (score, signal)
    return sorted(
        ((path, score, signal) for path, (score, signal) in best.items()),
        key=lambda row: -row[1],
    )


def _unique_winner(
    votes: list[tuple[str, float, str]], min_confidence: float
) -> tuple[bool, tuple[str, float, str] | None]:
    if not votes:
        return True, None
    best = votes[0]
    if best[1] < min_confidence:
        return True, None
    if len(votes) > 1 and (best[1] - votes[1][1]) < TIE_EPSILON:
        return True, None
    return False, best


def _want_llm(cfg: Config, *, thin: bool) -> bool:
    if not cfg.llm_enabled:
        return False
    if cfg.inbox_llm_route == "always":
        return True
    if cfg.inbox_llm_route == "when_thin":
        return thin
    return False


def _snowball_votes(
    cfg: Config, matched: MatchResult, existing: dict[str, Collection]
) -> list[tuple[str, float, str]]:
    root = cfg.state_dir / "snowball"
    if not root.is_dir():
        return []
    votes: list[tuple[str, float, str]] = []
    runs = [
        child
        for child in root.iterdir()
        if child.is_dir() and child.name not in _SKIP_SNOWBALL_DIRS
    ]
    runs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for child in runs[:RECENT_RUNS]:
        summary = _read_json(child / "summary.json")
        target = _resolve_existing(
            str(summary.get("target_collection") or ""), existing
        )
        if not target:
            continue
        if _jsonl_hit(child / "candidates.jsonl", matched):
            votes.append((target, SCORE_SNOWBALL_DOI, "snowball"))
        else:
            votes.append((target, SCORE_SNOWBALL_RECENCY, "snowball"))
    return votes


def _watch_votes(
    cfg: Config, matched: MatchResult, existing: dict[str, Collection]
) -> list[tuple[str, float, str]]:
    root = cfg.state_dir / "snowball" / "watches"
    if not root.is_dir():
        return []
    votes: list[tuple[str, float, str]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        body = _read_json(child / "watch.json")
        target = _resolve_existing(_watch_target(cfg, body), existing)
        if not target:
            continue
        if _jsonl_hit(child / "inbox.jsonl", matched):
            votes.append((target, SCORE_WATCH_DOI, "watch"))
        else:
            votes.append((target, SCORE_SNOWBALL_RECENCY, "watch"))
    return votes


def _watch_target(cfg: Config, body: dict[str, Any]) -> str:
    profile = str(body.get("profile") or "").strip()
    if profile:
        try:
            from .snowball.profile import load_profile

            raw = load_profile(cfg, profile)
            chosen = str(raw.get("target_collection") or "").strip()
            if chosen:
                return chosen
        except Exception:
            pass
    return str(cfg.snowball_target_collection or "").strip()


def _last_scope_votes(
    cfg: Config, existing: dict[str, Collection]
) -> list[tuple[str, float, str]]:
    votes: list[tuple[str, float, str]] = []
    last = cfg.state_dir / "last-run.json"
    if last.is_file():
        path = _resolve_existing(
            _scope_collection(_read_json(last).get("scope")), existing
        )
        if path:
            votes.append((path, SCORE_LAST_SCOPE, "last_scope"))
    runs = cfg.state_dir / "runs"
    if runs.is_dir() and not votes:
        files = sorted(
            runs.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
        )
        for path in files[:12]:
            scope = _resolve_existing(
                _scope_collection(_read_json(path).get("scope")), existing
            )
            if scope:
                votes.append((scope, SCORE_LAST_SCOPE, "last_scope"))
                break
    target = _resolve_existing(str(cfg.snowball_target_collection or ""), existing)
    if target:
        votes.append((target, SCORE_LAST_SCOPE - 0.02, "last_scope"))
    return votes


def _scope_collection(scope: Any) -> str:
    raw = str(scope or "").strip()
    if not raw or raw.startswith("whole library"):
        return ""
    first = raw.split(",")[0].strip()
    if first.startswith("years ") or first.startswith("types "):
        return ""
    return first


def _doi_library_votes(
    matched: MatchResult, items: list[Item], existing: dict[str, Collection]
) -> list[tuple[str, float, str]]:
    doi = normalize_doi(matched.doi)
    if not doi:
        return []
    hits = [
        item
        for item in items
        if normalize_doi(item.doi) == doi
    ]
    if len(hits) != 1:
        return []
    paths = [
        _resolve_existing(path, existing)
        for path in (hits[0].collection_paths or [])
        if path and path != "_uncollected"
    ]
    paths = [path for path in paths if path]
    unique = sorted(set(paths))
    if len(unique) != 1:
        return []
    return [(unique[0], SCORE_DOI_LIBRARY, "doi_library")]


def _title_votes(
    matched: MatchResult,
    filename: str,
    text: str,
    existing: dict[str, Collection],
) -> list[tuple[str, float, str]]:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    query = _tokens(" ".join(part for part in (matched.title, stem, matched.host) if part))
    body = _tokens((text or matched.text or "")[:2000])
    if not query and not body:
        return []
    votes: list[tuple[str, float, str]] = []
    for path, col in existing.items():
        target = _tokens(f"{path.replace('/', ' ')} {col.name}")
        if not target:
            continue
        coverage = _coverage(query, target)
        if coverage < 0.4:
            coverage = 0.6 * _coverage(body, target)
        if coverage < 0.4:
            continue
        score = 0.86 if coverage >= 0.99 else 0.50 + 0.30 * coverage
        votes.append((path, min(score, 0.88), "title"))
    return votes


def _tokens(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOP}


def _coverage(query: set[str], target: set[str]) -> float:
    if not query or not target:
        return 0.0
    return len(query & target) / len(target)


def _jsonl_hit(path: Path, matched: MatchResult) -> bool:
    if not path.is_file():
        return False
    doi = normalize_doi(matched.doi)
    title = normalize_dedupe_title(matched.title) if matched.title else ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        ids = row.get("ids") if isinstance(row.get("ids"), dict) else {}
        if doi and normalize_doi(str(ids.get("doi") or row.get("doi") or "")) == doi:
            return True
        biblio = row.get("biblio") if isinstance(row.get("biblio"), dict) else {}
        row_title = str(biblio.get("title") or row.get("title") or "")
        if title and normalize_dedupe_title(row_title) == title:
            return True
    return False


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _llm_route(
    cfg: Config,
    matched: MatchResult,
    *,
    text: str,
    filename: str,
    candidates: list[tuple[str, float, str]],
    existing: dict[str, Collection],
) -> RouteResult | None:
    if not cfg.llm_enabled:
        return None
    short = [row[0] for row in candidates if row[0] in existing][:LLM_CANDIDATE_CAP]
    if not short:
        short = list(existing)[:LLM_CANDIDATE_CAP]
    excerpt = (text or matched.text or matched.title or filename or "").strip()
    if not short or not excerpt:
        return None
    try:
        from .llm import CompletionRequest, get_client
    except Exception:
        return None
    client = get_client(cfg)
    model = cfg.inbox_model or cfg.llm_model
    listing = "\n".join(f"- {path}" for path in short)
    prompt = (
        "Which existing collection should this PDF be filed in? "
        'Reply JSON only: {"collection": "...", "match": true|false, '
        '"confidence": 0-1, "reason": "..."}. Use a path from the list. '
        "If none fit, match=false.\n\n"
        f"Collections:\n{listing}\n\n"
        f"Title: {matched.title}\nDOI: {matched.doi or ''}\n"
        f"Filename: {filename}\n\nPDF excerpt:\n{excerpt[:6000]}"
    )
    try:
        data = client.complete_json(
            CompletionRequest(
                model=model,
                prompt=prompt,
                timeout_seconds=cfg.llm_timeout_s,
                json_mode=True,
            )
        )
    except Exception:
        return None
    if data.get("match") is not True:
        return None
    try:
        conf = float(data.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < cfg.inbox_route_min_confidence:
        return RouteResult(
            how="llm",
            confidence=conf,
            reason=f"low confidence {conf:.2f}",
            candidates=candidates,
        )
    path = _resolve_existing(str(data.get("collection") or ""), existing)
    if not path:
        return RouteResult(how="none", reason="llm path not in library", candidates=candidates)
    return RouteResult(
        collection=path,
        how="llm",
        confidence=conf,
        reason=str(data.get("reason") or "llm"),
        candidates=candidates,
    )
