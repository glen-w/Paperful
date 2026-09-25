"""Preprint and published paper as one citeable work.

Dry-run writes a pack. ``--apply`` puts the version-of-record citation and
published PDF on the older parent, keeps the preprint id and PDF, and trashes
a sibling only after that published PDF is on the survivor.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .dedupe import scope_slug
from .download import DownloadError, fetch_pdf
from .resolve import (
    VersionLink,
    is_preprint_doi,
    normalize_doi,
    title_similarity,
    version_link,
)
from .zot import Item

SCHEMA = "paperful.version_pack.v1"
TITLE_REVIEW_MIN = 0.85
PUBLISHED_PDF_TITLE = "Published PDF"
PREPRINT_PDF_TITLE = "Preprint PDF"
ResolveFn = Callable[[str], VersionLink | None]
FetchPDF = Callable[[str], Path | None]


@dataclass
class VersionProposal:
    item_key: str
    title: str
    preprint_doi: str | None
    arxiv_id: str | None
    published_doi: str
    source: str
    confidence: str  # high | review
    title_score: float
    before: dict[str, Any]
    after: dict[str, Any]
    primary_pdf: str
    sibling_key: str | None
    sibling_keys: list[str] = field(default_factory=list)
    needs_review: bool = False


def classify_versions(
    items: list[Item],
    resolve: ResolveFn,
) -> list[VersionProposal]:
    """High-confidence edges become apply rows. Title proximity stays needs_review."""
    by_doi: dict[str, list[Item]] = {}
    for item in items:
        for doi in _item_dois(item):
            by_doi.setdefault(doi, []).append(item)

    proposals: list[VersionProposal] = []
    seen_published: set[str] = set()
    linked: set[str] = set()
    for item in items:
        for doi in _item_dois(item):
            try:
                link = resolve(doi)
            except Exception:
                link = None
            if link is None or not link.published_doi:
                continue
            published = normalize_doi(link.published_doi) or link.published_doi
            if published in seen_published:
                continue
            members = _members_for(link, by_doi)
            if item.key not in {m.key for m in members}:
                members.append(item)
            seen_published.add(published)
            linked.update(m.key for m in members)
            proposals.append(_proposal(members, link, needs_review=False))
            break

    proposals.extend(_review_pairs(items, linked))
    return proposals


def pack_counts(proposals: list[VersionProposal], n_items: int) -> dict[str, int]:
    return {
        "items": n_items,
        "proposals": len(proposals),
        "high": sum(1 for row in proposals if not row.needs_review),
        "needs_review": sum(1 for row in proposals if row.needs_review),
        "with_sibling": sum(1 for row in proposals if row.sibling_key),
    }


def write_pack(
    state_dir: Path,
    scope: str,
    proposals: list[VersionProposal],
    *,
    n_items: int,
    stamp: str | None = None,
) -> tuple[Path, Path]:
    stamp = stamp or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "version-packs"
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{stamp}-{scope_slug(scope)}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    counts = pack_counts(proposals, n_items)
    payload = {
        "schema": SCHEMA,
        "scope": scope,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "counts": counts,
        "proposals": [asdict(row) for row in proposals],
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(scope, counts, proposals), encoding="utf-8")
    return json_path, md_path


def apply_versions(
    backend: Any,
    proposals: list[VersionProposal],
    *,
    fetch_published: FetchPDF,
    audit_path: Path,
    scope: str,
    pack: Path,
) -> tuple[int, list[str]]:
    """Patch survivors. Trash a sibling only after the published PDF is attached."""
    from .library import LibraryError

    applied = 0
    errors: list[str] = []
    lines: list[str] = []
    now = datetime.now(tz=timezone.utc).isoformat()
    for row in proposals:
        if row.needs_review or row.confidence != "high":
            continue
        try:
            if row.after:
                backend.apply_patch(row.item_key, row.after)
            published_ready = _ensure_published_pdf(backend, row, fetch_published)
            _keep_preprint_pdfs(backend, row)
            linked = _link_siblings(backend, row)
        except LibraryError:
            raise
        except Exception as exc:
            errors.append(f"{row.item_key}: {exc}")
            continue
        trashed: list[str] = []
        if row.sibling_keys and published_ready and linked:
            for key in row.sibling_keys:
                try:
                    backend.trash_item(key)
                except LibraryError as exc:
                    errors.append(f"{key}: {exc}")
                    continue
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    continue
                trashed.append(key)
        elif row.sibling_keys and not published_ready:
            errors.append(
                f"{row.item_key}: published PDF missing; sibling left in place"
            )
        applied += 1
        lines.append(
            json.dumps(
                {
                    "ts": now,
                    "scope": scope,
                    "keep": row.item_key,
                    "published_doi": row.published_doi,
                    "preprint_doi": row.preprint_doi,
                    "sibling": row.sibling_key,
                    "trashed": trashed,
                    "pack": str(pack),
                },
                sort_keys=True,
            )
            + "\n"
        )
    if lines:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.writelines(lines)
    return applied, errors


def http_fetch_published(client: httpx.Client, email: str) -> FetchPDF:
    """Unpaywall, then OpenAlex ``best_oa_location``. Returns a temp PDF path."""

    def fetch(doi: str) -> Path | None:
        url = _oa_pdf_url(client, doi, email)
        if not url:
            return None
        try:
            downloaded = fetch_pdf(client, url, min_bytes=1000, retries=2)
        except DownloadError:
            return None
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.write(downloaded.content)
        handle.close()
        return Path(handle.name)

    return fetch


def resolver_for(client: httpx.Client, email: str) -> ResolveFn:
    from .resolve import IdentifierCache

    cache = IdentifierCache()

    def resolve(doi: str) -> VersionLink | None:
        return version_link(client, doi, email, cache)

    return resolve


def merge_preprint_extra(
    extra: str, *, arxiv_id: str | None, preprint_doi: str | None
) -> str:
    """Keep arXiv id and preprint DOI in Zotero extra when the DOI field becomes the VoR."""
    lines = [line for line in (extra or "").splitlines()]
    blob = extra or ""
    if arxiv_id and f"arXiv: {arxiv_id}".lower() not in blob.lower():
        from .resolve import extract_arxiv_id

        if extract_arxiv_id(blob) != arxiv_id:
            lines.append(f"arXiv: {arxiv_id}")
    if preprint_doi:
        marker = f"Preprint DOI: {preprint_doi}"
        if marker.lower() not in blob.lower():
            lines.append(marker)
    return "\n".join(line for line in lines if line).strip()


def _proposal(
    members: list[Item], link: VersionLink, *, needs_review: bool
) -> VersionProposal:
    uniq = list({item.key: item for item in members}.values())
    survivor = min(uniq, key=_age_key)
    siblings = [item.key for item in uniq if item.key != survivor.key]
    published = link.published
    after: dict[str, Any] = {}
    if not needs_review:
        after = _after_fields(survivor, link)
    title = (published.title if published and published.title else survivor.title) or ""
    score = title_similarity(survivor.title, title) if title else 0.0
    return VersionProposal(
        item_key=survivor.key,
        title=survivor.title,
        preprint_doi=link.preprint_doi,
        arxiv_id=link.arxiv_id,
        published_doi=normalize_doi(link.published_doi) or link.published_doi,
        source=link.source if not needs_review else "title",
        confidence="review" if needs_review else "high",
        title_score=round(score, 3),
        before=_before_fields(survivor),
        after=after,
        primary_pdf="published",
        sibling_key=siblings[0] if siblings else None,
        sibling_keys=siblings,
        needs_review=needs_review,
    )


def _after_fields(survivor: Item, link: VersionLink) -> dict[str, Any]:
    published = link.published
    arxiv_id = link.arxiv_id
    if not arxiv_id and survivor.arxiv_id:
        arxiv_id = survivor.arxiv_id
    extra = merge_preprint_extra(
        survivor.extra, arxiv_id=arxiv_id, preprint_doi=link.preprint_doi
    )
    after: dict[str, Any] = {
        "doi": normalize_doi(link.published_doi) or link.published_doi,
        "itemType": link.item_type or "journalArticle",
    }
    if extra and extra != (survivor.extra or "").strip():
        after["extra"] = extra
    if published:
        if published.title:
            after["title"] = published.title
        if published.date or published.year:
            after["date"] = published.date or str(published.year)
        if published.venue:
            after["publicationTitle"] = published.venue
    return after


def _before_fields(item: Item) -> dict[str, Any]:
    return {
        "doi": item.doi,
        "title": item.title,
        "date": item.date,
        "publicationTitle": item.publication_title,
        "itemType": item.item_type,
        "extra": item.extra,
    }


def _review_pairs(items: list[Item], linked: set[str]) -> list[VersionProposal]:
    rows: list[VersionProposal] = []
    pool = [item for item in items if item.key not in linked and item.doi]
    used: set[str] = set()
    for i, left in enumerate(pool):
        if left.key in used or not is_preprint_doi(left.doi):
            continue
        for right in pool[i + 1 :]:
            if right.key in used or is_preprint_doi(right.doi):
                continue
            if not _years_close(left.year, right.year):
                continue
            score = title_similarity(left.title, right.title)
            if score < TITLE_REVIEW_MIN:
                continue
            link = VersionLink(
                preprint_doi=normalize_doi(left.doi),
                published_doi=normalize_doi(right.doi) or (right.doi or ""),
                source="title",
                arxiv_id=left.arxiv_id,
                published=None,
            )
            rows.append(_proposal([left, right], link, needs_review=True))
            used.add(left.key)
            used.add(right.key)
            break
    return rows


def _years_close(a: int | None, b: int | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= 1


def _members_for(link: VersionLink, by_doi: dict[str, list[Item]]) -> list[Item]:
    found: dict[str, Item] = {}
    keys = [link.preprint_doi, link.published_doi]
    if link.arxiv_id:
        keys.append(f"10.48550/arxiv.{link.arxiv_id.lower()}")
    for raw in keys:
        doi = normalize_doi(raw) if raw else None
        if not doi:
            continue
        for item in by_doi.get(doi, []):
            found[item.key] = item
    return list(found.values())


def _item_dois(item: Item) -> list[str]:
    found: list[str] = []
    doi = normalize_doi(item.doi) if item.doi else None
    if doi:
        found.append(doi)
    if item.arxiv_id:
        arxiv_doi = normalize_doi(f"10.48550/arxiv.{item.arxiv_id}")
        if arxiv_doi and arxiv_doi not in found:
            found.append(arxiv_doi)
    return found


def _age_key(item: Item) -> tuple:
    return (item.date_added is None, item.date_added or "", item.key)


def _ensure_published_pdf(
    backend: Any, row: VersionProposal, fetch_published: FetchPDF
) -> bool:
    survivor_doi = normalize_doi(str(row.before.get("doi") or ""))
    survivor_was_preprint = is_preprint_doi(survivor_doi) or (
        row.before.get("itemType") == "preprint"
    )
    if not survivor_was_preprint and _has_pdf(backend, row.item_key):
        return True
    for key in row.sibling_keys:
        sibling_doi = _sibling_doi(backend, key)
        if is_preprint_doi(sibling_doi) or not _has_pdf(backend, key):
            continue
        if _copy_pdf(backend, key, row.item_key, PUBLISHED_PDF_TITLE):
            return True
    path = fetch_published(row.published_doi)
    if path is None:
        return False
    try:
        result = backend.attach(row.item_key, path, title=PUBLISHED_PDF_TITLE)
    finally:
        path.unlink(missing_ok=True)
    return bool(getattr(result, "ok", False))


def _keep_preprint_pdfs(backend: Any, row: VersionProposal) -> None:
    """Copy a sibling preprint file onto the survivor. Never delete an attachment."""
    for key in row.sibling_keys:
        sibling_doi = _sibling_doi(backend, key)
        if not is_preprint_doi(sibling_doi) and _item_type(backend, key) != "preprint":
            continue
        if not _has_pdf(backend, key):
            continue
        _copy_pdf(backend, key, row.item_key, PREPRINT_PDF_TITLE)


def _copy_pdf(backend: Any, source_key: str, dest_key: str, title: str) -> bool:
    dest_dir = Path(tempfile.mkdtemp(prefix="paperful-version-"))
    dest = dest_dir / f"{source_key}.pdf"
    try:
        exported = backend.export_pdf(_stub_item(source_key), dest)
        if exported is None or not Path(exported).is_file():
            return False
        result = backend.attach(dest_key, Path(exported), title=title)
        return bool(getattr(result, "ok", False))
    finally:
        for path in dest_dir.glob("*"):
            path.unlink(missing_ok=True)
        dest_dir.rmdir()


def _link_siblings(backend: Any, row: VersionProposal) -> bool:
    if not row.sibling_keys:
        return True
    relate = getattr(backend, "relate_items", None)
    if relate is None:
        return False
    for key in row.sibling_keys:
        relate(row.item_key, key)
    return True


def _has_pdf(backend: Any, key: str) -> bool:
    item = _get(backend, key)
    if item is None:
        return False
    return bool(getattr(item, "has_pdf", False))


def _sibling_doi(backend: Any, key: str) -> str | None:
    item = _get(backend, key)
    if item is None:
        return None
    return normalize_doi(getattr(item, "doi", None))


def _item_type(backend: Any, key: str) -> str:
    item = _get(backend, key)
    if item is None:
        return ""
    return str(getattr(item, "item_type", "") or "")


def _get(backend: Any, key: str) -> Item | None:
    getter = getattr(backend, "get_item", None)
    if getter is None:
        return None
    return getter(key)


def _stub_item(key: str) -> Item:
    return Item(
        key=key,
        item_type="journalArticle",
        title="",
        doi=None,
        arxiv_id=None,
        url=None,
        year=None,
        first_author=None,
    )


def _oa_pdf_url(client: httpx.Client, doi: str, email: str) -> str | None:
    if email:
        try:
            resp = client.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": email},
                timeout=30,
            )
            if resp.status_code < 400:
                data = resp.json()
                best = (data or {}).get("best_oa_location") or {}
                url = best.get("url_for_pdf")
                if url:
                    return str(url)
        except (httpx.HTTPError, ValueError, TypeError):
            pass
    try:
        params: dict[str, Any] = {}
        if email:
            params["mailto"] = email
        resp = client.get(
            f"https://api.openalex.org/works/https://doi.org/{doi}",
            params=params or None,
            timeout=30,
        )
        if resp.status_code >= 400:
            return None
        loc = (resp.json() or {}).get("best_oa_location") or {}
        url = loc.get("pdf_url")
        return str(url) if url else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def _markdown(scope: str, counts: dict[str, int], proposals: list[VersionProposal]) -> str:
    lines = [
        f"# Versions — {scope}",
        "",
        f"Items {counts['items']} · high {counts['high']} · "
        f"needs review {counts['needs_review']}",
        "",
        "High-confidence rows upgrade the older parent to the published citation.",
        "The preprint id and PDF stay. A sibling is trashed only after the published PDF is attached.",
        "Title matches are listed and are not applied.",
        "",
    ]
    if not proposals:
        lines.append("No preprint / published pairs.")
        lines.append("")
        return "\n".join(lines)
    for row in proposals:
        flag = "review" if row.needs_review else row.source
        lines.append(
            f"- `{row.item_key}` {row.title} → `{row.published_doi}` ({flag}, score {row.title_score})"
        )
        if row.preprint_doi:
            lines.append(f"  - preprint `{row.preprint_doi}`")
        if row.sibling_key:
            lines.append(f"  - sibling `{row.sibling_key}`")
    lines.append("")
    return "\n".join(lines)
