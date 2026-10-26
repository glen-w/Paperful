"""Screen library items for retraction status, PubPeer, and PPS-style fingerprints.

Read-only by default; ``--apply`` writes a parent tag and one child note.
Does not scrape the PPS APEX paper list — only public APIs and fingerprint CSVs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import Config
from .library import LibraryBackend
from .lint import ensure_pdf
from .notehtml import wrap
from .pdfid import pdftotext_available
from .rag.extract import LightParser
from .resolve import IdentifierCache, normalize_doi, prepare_identifiers
from .store import Manifest
from .zot import Item

PPS_HOME = "https://www.irit.fr/~Guillaume.Cabanac/problematic-paper-screener"
PPS_METHOD = "https://doi.org/10.48550/arXiv.2210.04895"

STATUS_DETECTORS = frozenset(
    {"retracted", "withdrawn", "expression_of_concern", "pubpeer"}
)
FINGERPRINT_FAMILIES = frozenset({"tortured", "scigen", "mathgen", "suspect"})
DEFAULT_DETECTORS = (
    "retracted",
    "withdrawn",
    "expression_of_concern",
    "pubpeer",
    "tortured",
    "scigen",
    "mathgen",
    "suspect",
)

# PPS highlights a subset of tortured-phrase papers (5+ hits or one obvious phrase).
OBVIOUS_TORTURED = frozenset(
    {
        "sign to clamor",
        "flag to clamor",
        "counterfeit consciousness",
        "bosom peril",
        "mean square blunder",
        "profound neural organization",
    }
)

_TAG_PREFIX = "paperful pps:"


@dataclass
class ScreenFinding:
    itemKey: str
    code: str
    title: str
    detail: str
    doi: str | None = None
    evidence: list[str] = field(default_factory=list)
    url: str | None = None


@dataclass(frozen=True)
class FingerprintRow:
    expression: str
    expected: str


def pubpeer_devkey() -> str:
    return os.environ.get("PUBPEER_DEVKEY", "").strip()


def pubpeer_ready(cfg: Config) -> bool:
    return bool(cfg.screen_pubpeer and pubpeer_devkey())


def pps_state_dir(cfg: Config) -> Path:
    return cfg.state_dir / "pps"


def fingerprint_csv_url(family: str) -> str:
    fam = family.strip().lower()
    return f"https://dbrech.irit.fr/pls/apex/f?p=9999:5::IR[{fam}]_CSV::::"


def _cache_path(cfg: Config, kind: str, key: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", key)[:200]
    return pps_state_dir(cfg) / kind / f"{safe}.json"


def _fingerprint_cache_path(cfg: Config, family: str) -> Path:
    return pps_state_dir(cfg) / "fingerprints" / f"{family.lower()}.json"


def _fingerprint_stale(cfg: Config, family: str) -> bool:
    meta = _fingerprint_cache_path(cfg, family)
    if not meta.is_file():
        return True
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        fetched = float(data.get("fetched_at") or 0)
    except (OSError, ValueError, TypeError):
        return True
    age_s = time.time() - fetched
    return age_s > cfg.screen_fingerprint_max_age_days * 86400


def _rows_from_fingerprint_json(raw: dict[str, Any]) -> list[FingerprintRow]:
    rows = raw.get("rows") or []
    return [
        FingerprintRow(str(r[0]), str(r[1]))
        for r in rows
        if isinstance(r, (list, tuple)) and len(r) >= 2
    ]


def parse_fingerprint_csv(text: str) -> list[FingerprintRow]:
    rows: list[FingerprintRow] = []
    reader = csv.reader(io.StringIO(text))
    for i, row in enumerate(reader):
        if not row or (i == 0 and row[0].lower().startswith("fingerprint")):
            continue
        if len(row) < 2:
            continue
        expr = (row[0] or "").strip()
        expected = (row[1] or "").strip()
        if expr:
            rows.append(FingerprintRow(expr, expected))
    return rows


def _read_fingerprint_cache_file(path: Path) -> list[FingerprintRow]:
    if not path.is_file():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if path.suffix.lower() == ".csv":
        return parse_fingerprint_csv(raw_text)
    try:
        raw = json.loads(raw_text)
    except (ValueError, TypeError):
        return []
    if isinstance(raw, dict):
        return _rows_from_fingerprint_json(raw)
    return []


def _read_fingerprint_cache(cfg: Config, family: str, *, allow_stale: bool) -> list[FingerprintRow]:
    cache = _fingerprint_cache_path(cfg, family)
    if not cache.is_file():
        return []
    if not allow_stale and _fingerprint_stale(cfg, family):
        return []
    return _read_fingerprint_cache_file(cache)


def _read_fingerprint_dir(cfg: Config, family: str) -> list[FingerprintRow]:
    folder = cfg.screen_fingerprint_dir
    if folder is None:
        return []
    for name in (f"{family}.csv", f"{family}.json"):
        path = folder / name
        rows = _read_fingerprint_cache_file(path)
        if rows:
            return rows
    return []


def load_fingerprints(
    client: httpx.Client | None,
    cfg: Config,
    family: str,
    *,
    refresh: bool = False,
    offline: bool = False,
) -> list[FingerprintRow]:
    """Load PPS fingerprint rows (local cache/dir first; optional IRIT CSV fetch)."""
    fam = family.strip().lower()
    if fam not in FINGERPRINT_FAMILIES:
        return []

    def local_rows() -> list[FingerprintRow]:
        rows = _read_fingerprint_cache(cfg, fam, allow_stale=True)
        if rows:
            return rows
        return _read_fingerprint_dir(cfg, fam)

    if offline or client is None:
        return local_rows()

    cache = _fingerprint_cache_path(cfg, fam)
    if not refresh and not _fingerprint_stale(cfg, fam):
        rows = _read_fingerprint_cache(cfg, fam, allow_stale=True)
        if rows:
            return rows

    headers = {"User-Agent": f"paperful ({cfg.email or 'no-email'})"}
    try:
        resp = client.get(fingerprint_csv_url(fam), headers=headers, timeout=120)
        resp.raise_for_status()
        text = resp.text
    except httpx.HTTPError:
        rows = local_rows()
        return rows
    rows = parse_fingerprint_csv(text)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "family": fam,
                "fetched_at": time.time(),
                "rows": [[r.expression, r.expected] for r in rows],
            },
            indent=0,
        ),
        encoding="utf-8",
    )
    return rows


def tokens_in_window(text: str, tokens: list[str], window: int) -> bool:
    """True when all tokens appear in order within a ``window``-word span."""
    if not tokens:
        return False
    words = re.findall(r"\w+", text.lower())
    need = [t.lower() for t in tokens]
    span = max(window, len(need))
    for start in range(len(words)):
        pos = start
        for tok in need:
            found_at = None
            for j in range(pos, min(len(words), start + span)):
                if words[j] == tok:
                    found_at = j + 1
                    break
            if found_at is None:
                break
            pos = found_at
        else:
            return True
    return False


def match_fingerprint(text: str, expression: str) -> bool:
    expr = (expression or "").strip()
    if not expr:
        return False
    lower = text.lower()
    prox = re.match(r'^"(.+)"~(\d+)\s*$', expr, flags=re.I)
    if prox:
        phrase = prox.group(1)
        window = int(prox.group(2))
        tokens = re.findall(r"\w+", phrase.lower())
        return tokens_in_window(lower, tokens, window)
    if re.search(r"\s+AND\s+", expr, flags=re.I):
        parts = re.split(r"\s+AND\s+", expr, flags=re.I)
        return all(match_fingerprint(text, p.strip()) for p in parts if p.strip())
    if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
        return expr[1:-1].lower() in lower
    return expr.lower() in lower


def scan_text_fingerprints(
    text: str,
    rows: Iterable[FingerprintRow],
    *,
    family: str,
    tortured_min: int,
) -> list[str]:
    hits: list[str] = []
    obvious = False
    for row in rows:
        if match_fingerprint(text, row.expression):
            label = row.expression
            if row.expected:
                label = f"{row.expression} → {row.expected}"
            hits.append(label)
            if family == "tortured":
                low = row.expression.lower().strip('"')
                if low in OBVIOUS_TORTURED:
                    obvious = True
    if family != "tortured":
        return hits
    if obvious or len(hits) >= tortured_min:
        return hits
    return []


def _read_status_cache(cfg: Config, doi: str) -> dict[str, Any] | None:
    path = _cache_path(cfg, "status", doi.lower())
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_status_cache(cfg: Config, doi: str, payload: dict[str, Any]) -> None:
    path = _cache_path(cfg, "status", doi.lower())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=0), encoding="utf-8")


def crossref_update_codes(msg: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for upd in msg.get("update-to") or []:
        if not isinstance(upd, dict):
            continue
        kind = str(upd.get("type") or "").lower()
        if kind == "retraction":
            codes.append("retracted")
        elif kind == "withdrawal":
            codes.append("withdrawn")
        elif "expression" in kind and "concern" in kind:
            codes.append("expression_of_concern")
    for rel in msg.get("relation") or []:
        if not isinstance(rel, dict):
            continue
        kind = str(rel.get("relation-type") or rel.get("type") or "").lower()
        if "retract" in kind:
            codes.append("retracted")
    return list(dict.fromkeys(codes))


def lookup_crossref_status(
    client: httpx.Client,
    doi: str,
    email: str,
) -> list[str]:
    params: dict[str, Any] = {}
    if email:
        params["mailto"] = email
    try:
        resp = client.get(
            "https://api.crossref.org/works/" + quote(doi, safe="/()"),
            params=params or None,
            timeout=30,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        msg = resp.json().get("message") or {}
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    return crossref_update_codes(msg)


def lookup_openalex_retracted(
    client: httpx.Client,
    doi: str,
    email: str,
) -> bool:
    params: dict[str, Any] = {"select": "id,doi,is_retracted"}
    if email:
        params["mailto"] = email
    try:
        resp = client.get(
            "https://api.openalex.org/works/https://doi.org/" + quote(doi, safe="/()"),
            params=params,
            timeout=30,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return bool(resp.json().get("is_retracted"))
    except (httpx.HTTPError, ValueError, TypeError):
        return False


def lookup_doi_status(
    client: httpx.Client,
    cfg: Config,
    doi: str,
    *,
    refresh: bool = False,
) -> list[str]:
    cleaned = normalize_doi(doi) or doi.lower()
    if not cleaned:
        return []
    if not refresh:
        cached = _read_status_cache(cfg, cleaned)
        if cached is not None:
            return list(cached.get("codes") or [])
    codes = lookup_crossref_status(client, cleaned, cfg.email)
    if lookup_openalex_retracted(client, cleaned, cfg.email):
        if "retracted" not in codes:
            codes.append("retracted")
    _write_status_cache(
        cfg,
        cleaned,
        {"codes": codes, "fetched_at": time.time()},
    )
    return codes


def pubpeer_lookup(
    client: httpx.Client,
    dois: list[str],
) -> dict[str, dict[str, Any]]:
    key = pubpeer_devkey()
    if not key or not dois:
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunk = 80
    for i in range(0, len(dois), chunk):
        batch = [d.lower() for d in dois[i : i + chunk] if d]
        if not batch:
            continue
        body = json.dumps({"dois": batch})
        try:
            resp = client.post(
                f"https://pubpeer.com/v3/publications?devkey={quote(key)}",
                content=body,
                headers={"Content-Type": "application/json;charset=UTF-8"},
                timeout=60,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
        except (httpx.HTTPError, ValueError, TypeError):
            continue
        for fb in data.get("feedbacks") or []:
            if not isinstance(fb, dict):
                continue
            did = str(fb.get("id") or "").lower()
            if did:
                out[did] = fb
    return out


def pdf_text(cfg: Config, item: Item, manifest: Manifest | None, backend: LibraryBackend | None) -> str:
    path = ensure_pdf(cfg, item, manifest, backend)
    if path is None or not path.is_file():
        return ""
    if not pdftotext_available():
        return ""
    try:
        pages = LightParser().pages(path)
    except Exception:
        return ""
    return "\n".join(pages)


def _detector_on(cfg: Config, name: str) -> bool:
    want = {d.strip().lower() for d in cfg.screen_detectors if str(d).strip()}
    return name.lower() in want


def screen_item(
    client: httpx.Client,
    cfg: Config,
    item: Item,
    *,
    backend: LibraryBackend | None = None,
    manifest: Manifest | None = None,
    cache: IdentifierCache | None = None,
    fingerprint_rows: dict[str, list[FingerprintRow]] | None = None,
    pubpeer: dict[str, dict[str, Any]] | None = None,
    refresh: bool = False,
) -> list[ScreenFinding]:
    prepare_identifiers(
        client,
        item,
        email=cfg.email,
        min_score=cfg.crossref_min_score,
        suspect_score=cfg.doi_suspect_score,
        verify=cfg.verify_doi,
        cache=cache,
    )
    findings: list[ScreenFinding] = []
    doi = normalize_doi(item.doi) if item.doi else None

    def add(code: str, detail: str, *, evidence: list[str] | None = None, url: str | None = None) -> None:
        findings.append(
            ScreenFinding(
                itemKey=item.key,
                code=code,
                title=item.title,
                detail=detail,
                doi=doi,
                evidence=list(evidence or []),
                url=url,
            )
        )

    status_wanted = any(_detector_on(cfg, c) for c in STATUS_DETECTORS)
    if doi and status_wanted:
        codes = lookup_doi_status(client, cfg, doi, refresh=refresh)
        for code in codes:
            if _detector_on(cfg, code):
                add(code, f"Crossref/OpenAlex status for {doi}")
        if pubpeer_ready(cfg) and _detector_on(cfg, "pubpeer"):
            fb = (pubpeer or {}).get(doi.lower())
            if fb and int(fb.get("total_comments") or 0) > 0:
                n = int(fb.get("total_comments") or 0)
                add(
                    "pubpeer",
                    f"{n} PubPeer comment(s)",
                    evidence=[str(fb.get("url") or "")],
                    url=str(fb.get("url") or "") or None,
                )

    fp_wanted = any(_detector_on(cfg, f) for f in FINGERPRINT_FAMILIES)
    if fp_wanted:
        text = pdf_text(cfg, item, manifest, backend)
        if text.strip():
            rows_map = fingerprint_rows or {}
            for family in FINGERPRINT_FAMILIES:
                if not _detector_on(cfg, family):
                    continue
                rows = rows_map.get(family)
                if rows is None:
                    rows = load_fingerprints(client, cfg, family, refresh=refresh)
                hits = scan_text_fingerprints(
                    text,
                    rows,
                    family=family,
                    tortured_min=cfg.screen_tortured_min,
                )
                if hits:
                    sample = hits[:8]
                    more = len(hits) - len(sample)
                    detail = f"{len(hits)} fingerprint hit(s)"
                    if more > 0:
                        detail += f" (showing {len(sample)})"
                    add(family, detail, evidence=sample)
    return findings


def screen_items(
    client: httpx.Client,
    cfg: Config,
    items: list[Item],
    *,
    backend: LibraryBackend | None = None,
    manifest: Manifest | None = None,
    refresh: bool = False,
    on_start: Callable[[Item], None] | None = None,
    on_item: Callable[[Item, list[ScreenFinding]], None] | None = None,
) -> list[ScreenFinding]:
    cache = IdentifierCache()
    fingerprint_rows: dict[str, list[FingerprintRow]] = {}
    for family in FINGERPRINT_FAMILIES:
        if _detector_on(cfg, family):
            fingerprint_rows[family] = load_fingerprints(
                client, cfg, family, refresh=refresh
            )
    pubpeer_map: dict[str, dict[str, Any]] = {}
    if pubpeer_ready(cfg) and _detector_on(cfg, "pubpeer"):
        dois: list[str] = []
        for item in items:
            d = normalize_doi(item.doi) if item.doi else None
            if d:
                dois.append(d)
        pubpeer_map = pubpeer_lookup(client, dois)
    out: list[ScreenFinding] = []
    for item in items:
        if on_start:
            on_start(item)
        found = screen_item(
            client,
            cfg,
            item,
            backend=backend,
            manifest=manifest,
            cache=cache,
            fingerprint_rows=fingerprint_rows,
            pubpeer=pubpeer_map,
            refresh=refresh,
        )
        out.extend(found)
        if on_item:
            on_item(item, found)
    return out


def _tag_summary(findings: list[ScreenFinding]) -> str:
    by_code: dict[str, int] = {}
    for f in findings:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    parts = []
    for code in sorted(by_code):
        n = by_code[code]
        if n == 1 and code in {"retracted", "withdrawn", "expression_of_concern", "pubpeer"}:
            parts.append(code.replace("_", " "))
        else:
            parts.append(f"{code.replace('_', ' ')} ({n})")
    return "; ".join(parts)


def _note_body(findings: list[ScreenFinding], item: Item) -> str:
    lines = [
        "<p>Screening flag from <code>paperful screen</code>. "
        "This is not a misconduct finding — review the evidence.</p>",
        f"<p>Method: <a href=\"{PPS_METHOD}\">Problematic Paper Screener</a> "
        f"(<a href=\"{PPS_HOME}\">PPS</a>).</p>",
    ]
    doi = normalize_doi(item.doi) if item.doi else None
    if doi:
        pps = (
            "https://dbrech.irit.fr/pls/apex/f?p=9999:3"
            f":::::IR[DOI]:{quote(doi)}"
        )
        lines.append(f"<p>DOI: {doi} — <a href=\"{pps}\">PPS report</a></p>")
    lines.append("<ul>")
    for f in findings:
        extra = ""
        if f.url:
            extra = f' <a href="{f.url}">link</a>'
        lines.append(f"<li><strong>{f.code}</strong>: {f.detail}{extra}</li>")
        for ev in f.evidence[:10]:
            lines.append(f"<li><em>{ev}</em></li>")
    lines.append("</ul>")
    lines.append(
        f"<p><small>Checked {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</small></p>"
    )
    return "\n".join(lines)


def apply_screen(
    backend: LibraryBackend,
    cfg: Config,
    items: list[Item],
    findings: list[ScreenFinding],
) -> int:
    """Write tags and notes for items that have findings. Returns items updated."""
    by_key: dict[str, list[ScreenFinding]] = {}
    for f in findings:
        by_key.setdefault(f.itemKey, []).append(f)
    updated = 0
    tag_note = (cfg.screen_tag or "paperful-pps").strip()
    for item in items:
        group = by_key.get(item.key)
        if not group:
            continue
        summary = _tag_summary(group)
        tag_line = f"{_TAG_PREFIX} {summary}"
        try:
            backend.replace_prefixed_tag(item.key, _TAG_PREFIX, tag_line)
        except Exception:
            pass
        body = _note_body(group, item)
        html = wrap(body, note_type="screen", verb="pps", extra=summary[:80])
        try:
            backend.create_or_update_note(item.key, html, tag_note)
            updated += 1
        except Exception:
            continue
    return updated


def fingerprint_cache_age_days(cfg: Config) -> float | None:
    """Oldest fingerprint cache age in days, or None if no cache."""
    folder = pps_state_dir(cfg) / "fingerprints"
    if not folder.is_dir():
        return None
    oldest = None
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched = float(data.get("fetched_at") or 0)
        except (OSError, ValueError, TypeError):
            continue
        if oldest is None or fetched < oldest:
            oldest = fetched
    if oldest is None:
        return None
    return (time.time() - oldest) / 86400
