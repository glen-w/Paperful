"""What changed since the last run: a read-only join of verbs that already exist.

``since`` never downloads a PDF, never writes to the manager, and omits any
row it has no prior observation for.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .dedupe import scope_slug
from .fsio import atomic_write_json, atomic_write_text
from .handoff_rank import cites_for, severity
from .sources import REGISTRY, Candidate, Context, Outcome
from .urls import UrlFinding, UrlTarget
from .versions import VersionProposal
from .zot import Item

SCHEMA = "paperful.since.v1"
SINCE_PACK_KEYS = frozenset(
    {
        "schema",
        "scope",
        "created_at",
        "baseline",
        "counts",
        "notes",
        "holdings",
        "healed",
    }
)
# Metadata API lanes only: their ``find`` returns a URL and no PDF bytes.
PROBE_LANES = (
    "unpaywall",
    "openalex",
    "arxiv",
    "biorxiv",
    "europepmc",
    "semanticscholar",
    "core",
    "openaire",
)
HEALABLE_SURFACES = frozenset({"no_oa", "paywalled", "fetch_failed"})
STATUS_CODES = ("retracted", "withdrawn", "expression_of_concern")
VERSION_KIND = "version_of_record"
DEAD_URL_CODES = frozenset({"hard_dead", "paywall_html"})
NOTHING_CHANGED = "Nothing changed."

Probe = Callable[[Item], Candidate | None]
StatusLookup = Callable[[str], list[str]]


@dataclass(frozen=True)
class Baseline:
    """The saved ``run`` report this pack is compared to."""

    path: Path
    finished_at: str
    witness_id: str
    items: list[dict[str, Any]]

    @property
    def label(self) -> str:
        return self.witness_id or self.finished_at[:10]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _newest_report(
    state_dir: Path, command: str, scope: str, *, before: date | None = None
) -> tuple[Path, dict[str, Any]] | None:
    """Newest ``state/runs/*-<command>.json`` for ``scope`` that is not a dry run."""
    runs = state_dir / "runs"
    if not runs.is_dir():
        return None
    for path in sorted(runs.glob(f"*-{command}.json"), reverse=True):
        body = _read_json(path)
        if body is None or body.get("scope") != scope:
            continue
        if (body.get("flags") or {}).get("dry_run"):
            continue
        if before is not None:
            finished = str(body.get("finished_at") or "")[:10]
            if not finished or finished > before.isoformat():
                continue
        return path, body
    return None


def find_baseline(
    state_dir: Path, scope: str, *, before: date | None = None
) -> Baseline | None:
    found = _newest_report(state_dir, "run", scope, before=before)
    if found is None:
        return None
    path, body = found
    digest = str((body.get("witness") or {}).get("config_sha256") or "")
    return Baseline(
        path=path,
        finished_at=str(body.get("finished_at") or ""),
        witness_id=digest[:12],
        items=[row for row in body.get("items") or [] if isinstance(row, dict)],
    )


def prior_holdings(
    state_dir: Path, scope: str
) -> tuple[set[tuple[str, str]], dict[str, str]]:
    """``(itemKey, kind)`` pairs already reported, and a label per verb.

    Reads the newest ``screen`` report, the newest ``versions`` pack, and the
    newest ``since`` pack for the scope, so a holdings row is news once.
    """
    seen: set[tuple[str, str]] = set()
    labels: dict[str, list[str]] = {}
    found = _newest_report(state_dir, "screen", scope)
    if found is not None:
        _, body = found
        labels["screen"] = [f"screen {str(body.get('finished_at') or '')[:10]}"]
        for row in body.get("items") or []:
            if isinstance(row, dict):
                seen.add((str(row.get("itemKey") or ""), str(row.get("status") or "")))
    packs = state_dir / "version-packs"
    if packs.is_dir():
        for path in sorted(packs.glob("*.json"), reverse=True):
            pack = _read_json(path)
            if pack is None or pack.get("scope") != scope:
                continue
            labels["versions"] = [f"versions {str(pack.get('created_at') or '')[:10]}"]
            for row in pack.get("proposals") or []:
                if isinstance(row, dict):
                    seen.add((str(row.get("item_key") or ""), VERSION_KIND))
            break
    root = state_dir / "since"
    if root.is_dir():
        for folder in sorted(root.iterdir(), reverse=True):
            pack = _read_json(folder / "since.json")
            if pack is None or pack.get("scope") != scope:
                continue
            label = f"since {str(pack.get('created_at') or '')[:10]}"
            for verb in ("screen", "versions"):
                labels.setdefault(verb, []).append(label)
            for row in pack.get("holdings") or []:
                if isinstance(row, dict):
                    seen.add(
                        (str(row.get("itemKey") or ""), str(row.get("kind") or ""))
                    )
            break
    return seen, {verb: ", ".join(names) for verb, names in labels.items()}


def prior_urls(
    state_dir: Path, scope: str
) -> tuple[dict[tuple[str, str], str], str] | None:
    """``(item_key, url)`` → code from the newest ``urls`` report, or None."""
    found = _newest_report(state_dir, "urls", scope)
    if found is None:
        return None
    _, body = found
    codes = {
        (str(row.get("item_key") or ""), str(row.get("url") or "")): str(
            row.get("code") or ""
        )
        for row in body.get("items") or []
        if isinstance(row, dict)
    }
    return codes, f"urls {str(body.get('finished_at') or '')[:10]}"


def status_rows(
    items: list[Item],
    lookup: StatusLookup,
    seen: set[tuple[str, str]],
    compared_to: str,
) -> list[dict[str, Any]]:
    """Retraction, withdrawal, or expression of concern on a library item."""
    rows: list[dict[str, Any]] = []
    for item in items:
        if not item.doi:
            continue
        for code in lookup(item.doi):
            if code not in STATUS_CODES or (item.key, code) in seen:
                continue
            rows.append(
                {
                    "kind": code,
                    "itemKey": item.key,
                    "title": item.title,
                    "doi": item.doi,
                    "verb": "screen",
                    "compared_to": compared_to or "no prior screen report",
                    "suggested_action": "paperful screen",
                }
            )
    return rows


def version_rows(
    proposals: list[VersionProposal],
    seen: set[tuple[str, str]],
    compared_to: str,
) -> list[dict[str, Any]]:
    """Preprints that now have a version of record. Nothing is merged."""
    return [
        {
            "kind": VERSION_KIND,
            "itemKey": row.item_key,
            "title": row.title,
            "doi": row.published_doi,
            "confidence": row.confidence,
            "verb": "versions",
            "compared_to": compared_to or "no prior versions pack",
            "suggested_action": "paperful versions",
        }
        for row in proposals
        if (row.item_key, VERSION_KIND) not in seen
    ]


def url_rows(
    targets: list[UrlTarget],
    titles: dict[str, str],
    prior: dict[tuple[str, str], str],
    probe: Callable[[UrlTarget], UrlFinding],
    seen: set[tuple[str, str]],
    compared_to: str,
) -> list[dict[str, Any]]:
    """URLs the last ``urls`` report could open that are now dead or paywalled.

    A URL the last report never saw is not probed.
    """
    rows: list[dict[str, Any]] = []
    for target in targets:
        was = prior.get((target.item_key, target.url))
        if not was or was in DEAD_URL_CODES:
            continue
        code = probe(target).code
        if code not in DEAD_URL_CODES or (target.item_key, code) in seen:
            continue
        rows.append(
            {
                "kind": code,
                "itemKey": target.item_key,
                "title": titles.get(target.item_key, ""),
                "url": target.url,
                "was": was,
                "verb": "urls check",
                "compared_to": compared_to,
                "suggested_action": "paperful urls check",
            }
        )
    return rows


def snapshot_rows(
    items: list[Item],
    probe: Probe,
    seen: set[tuple[str, str]],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Snapshot-only PDFs that a metadata lane can now replace."""
    todo = [
        item
        for item in items
        if item.pdf_tier == "snapshot" and (item.key, "snapshot_upgrade") not in seen
    ]
    rows: list[dict[str, Any]] = []
    for item in todo[:limit]:
        cand = probe(item)
        if cand is None:
            continue
        rows.append(
            {
                "kind": "snapshot_upgrade",
                "itemKey": item.key,
                "title": item.title,
                "doi": item.doi or "",
                "lane": cand.source,
                "url": cand.url,
                "verb": "run",
                "compared_to": "stored snapshot PDF",
                "suggested_action": "paperful run --upgrade-snapshot",
            }
        )
    return rows


def keepup_rows(
    items: list[Item], applied: set[str], seen: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Parents ``keepup apply`` created that still have no PDF."""
    return [
        {
            "kind": "keepup_no_pdf",
            "itemKey": item.key,
            "title": item.title,
            "doi": item.doi,
            "verb": "keepup apply",
            "compared_to": "keepup applied ledger",
            "suggested_action": "paperful run",
        }
        for item in items
        if item.doi
        and not item.has_pdf
        and f"doi:{item.doi.lower()}" in applied
        and (item.key, "keepup_no_pdf") not in seen
    ]


def probe_item(item: Item, ctx: Context, lanes: list[str]) -> Candidate | None:
    """First metadata lane that names a PDF URL. Never fetches the PDF."""
    for name in lanes:
        if name not in PROBE_LANES:
            continue
        cand = REGISTRY[name].find(item, ctx)
        if cand.outcome is Outcome.FOUND and cand.url and cand.content is None:
            return cand
    return None


def _was_miss(row: dict[str, Any]) -> bool:
    return (
        str(row.get("status") or "") == "not_found"
        or str(row.get("miss_surface") or "") in HEALABLE_SURFACES
    )


def healed_rows(
    baseline: Baseline,
    items: list[Item],
    probe: Probe,
    cite_counts: dict[str, int],
    *,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Baseline misses, still without a PDF, that a metadata lane now names."""
    by_key = {item.key: item for item in items}
    todo: list[tuple[int, int, Item, str]] = []
    for row in baseline.items:
        item = by_key.pop(str(row.get("itemKey") or ""), None)
        if item is None or item.has_pdf or not _was_miss(row):
            continue
        was = str(row.get("miss_surface") or row.get("status") or "")
        cites = cites_for(item, cite_counts)
        todo.append((cites * severity(was), cites, item, was))
    todo.sort(key=lambda t: (-t[0], t[2].title.lower()))
    candidates = len(todo)
    if limit is not None:
        todo = todo[:limit]
    rows: list[dict[str, Any]] = []
    for score, cites, item, was in todo:
        cand = probe(item)
        if cand is None:
            continue
        rows.append(
            {
                "kind": "healed_miss",
                "itemKey": item.key,
                "title": item.title,
                "doi": item.doi or "",
                "was": was,
                "lane": cand.source,
                "url": cand.url,
                "cites": cites,
                "score": score,
                "verb": "run",
                "compared_to": baseline.label,
                "suggested_action": "paperful run",
            }
        )
    return rows, {"healed_candidates": candidates, "probed": len(todo)}


def _markdown(payload: dict[str, Any]) -> str:
    lines = [f"# Since — {payload['scope']}", ""]
    base = payload["baseline"]
    if base:
        lines.append(
            f"Compared to run {base['finished_at'][:10]} (witness {base['witness_id'] or 'none'})."
        )
    lines += [f"- {note}" for note in payload["notes"]]
    lines.append("")
    if not payload["holdings"] and not payload["healed"]:
        lines.append(NOTHING_CHANGED)
        return "\n".join(lines) + "\n"
    if payload["holdings"]:
        lines += ["## Holdings that changed meaning", ""]
        for row in payload["holdings"]:
            lines.append(
                f"- **{row['kind']}** `{row['itemKey']}` {row['title']} "
                f"({row['verb']}; vs {row['compared_to']})"
            )
        lines.append("")
    if payload["healed"]:
        lines += ["## Misses that healed", ""]
        for row in payload["healed"]:
            lines.append(
                f"- `{row['itemKey']}` {row['title']} — was {row['was']}, "
                f"now {row['lane']}: {row['url']} "
                f"({row['verb']}; vs {row['compared_to']})"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def write_pack(
    state_dir: Path,
    scope: str,
    baseline: Baseline | None,
    holdings: list[dict[str, Any]],
    healed: list[dict[str, Any]],
    counts: dict[str, int],
    notes: list[str],
    *,
    stamp: str | None = None,
) -> Path:
    now = datetime.now(tz=timezone.utc)
    stamp = stamp or now.strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "since" / f"{stamp}-{scope_slug(scope)}"
    folder.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "scope": scope,
        "created_at": now.isoformat(),
        "baseline": (
            {
                "report": baseline.path.name,
                "finished_at": baseline.finished_at,
                "witness_id": baseline.witness_id,
            }
            if baseline
            else None
        ),
        "counts": {"holdings": len(holdings), "healed": len(healed), **counts},
        "notes": list(notes),
        "holdings": holdings,
        "healed": healed,
    }
    atomic_write_json(folder / "since.json", payload)
    atomic_write_text(folder / "since.md", _markdown(payload))
    return folder
