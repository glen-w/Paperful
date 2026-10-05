"""Create metadata parents from a DOI list. Dry-run unless ``--apply``."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identity import LibraryFingerprint, merge_tags, seed_slug
from .interop.load import parent_payload
from .library import LibraryBackend, LibraryError
from .lint import normalize_saved_title, usable_work_title
from .resolve import WorkMeta, normalize_doi, work_by_doi
from .snowball.ingest import _creators, _item_type

SCHEMA = "paperful.ingest_dois.v1"
ResolveFn = Callable[[str], WorkMeta | None]


@dataclass
class IngestRow:
    doi: str
    status: str  # create | exists | unresolved | held | error
    title: str = ""
    year: int | None = None
    item_key: str = ""
    detail: str = ""
    source: str = ""


@dataclass
class IngestBatch:
    rows: list[IngestRow] = field(default_factory=list)
    created: int = 0
    exists: int = 0
    unresolved: int = 0
    held: int = 0
    failed: int = 0
    applied: bool = False

    def counts(self) -> dict[str, int]:
        return {
            "rows": len(self.rows),
            "created": self.created,
            "exists": self.exists,
            "unresolved": self.unresolved,
            "held": self.held,
            "failed": self.failed,
        }


def parse_doi_lines(text: str) -> list[str]:
    """One DOI per line. ``#`` comments. Blank lines skipped. Deduped, order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        doi = normalize_doi(line) or normalize_doi(_strip_url(line))
        if not doi or doi in seen:
            continue
        seen.add(doi)
        out.append(doi)
    return out


def dois_from_file(path: Path) -> list[str]:
    return parse_doi_lines(path.read_text(encoding="utf-8"))


def dois_from_refs_pack(path: Path) -> list[str]:
    """DOIs from a ``paperful.refs_gap.pack.v1`` JSON whose action is ingest-dois."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        action = str(row.get("suggested_action") or "")
        if action and action != "ingest-dois":
            continue
        doi = normalize_doi(row.get("doi"))
        if not doi or doi in seen:
            continue
        if row.get("already_exists"):
            continue
        seen.add(doi)
        out.append(doi)
    return out


def classify_rows(
    dois: Iterable[str],
    fingerprint: LibraryFingerprint,
    *,
    resolve: ResolveFn,
    allowlist: frozenset[str] | None = None,
) -> IngestBatch:
    batch = IngestBatch()
    for doi in dois:
        work = resolve(doi)
        if work is None or not (work.title or "").strip():
            batch.rows.append(
                IngestRow(doi=doi, status="unresolved", detail="no work record")
            )
            batch.unresolved += 1
            continue
        title = normalize_saved_title(work.title, allowlist)
        if not usable_work_title(title):
            batch.rows.append(
                IngestRow(
                    doi=doi,
                    status="held",
                    title=title,
                    year=work.year,
                    source=work.source,
                    detail="unusable title",
                )
            )
            batch.held += 1
            continue
        hit = fingerprint.find(doi, title, work.year)
        if hit is not None and hit.kind == "doi":
            batch.rows.append(
                IngestRow(
                    doi=doi,
                    status="exists",
                    title=title,
                    year=work.year,
                    item_key=hit.item_key,
                    source=work.source,
                    detail="doi",
                )
            )
            batch.exists += 1
            continue
        if hit is not None and hit.kind == "title_year":
            other = fingerprint.doi_of.get(hit.item_key, "")
            if other and other != doi:
                batch.rows.append(
                    IngestRow(
                        doi=doi,
                        status="held",
                        title=title,
                        year=work.year,
                        item_key=hit.item_key,
                        source=work.source,
                        detail="title+year matches a different DOI",
                    )
                )
                batch.held += 1
                continue
            batch.rows.append(
                IngestRow(
                    doi=doi,
                    status="exists",
                    title=title,
                    year=work.year,
                    item_key=hit.item_key,
                    source=work.source,
                    detail="title_year",
                )
            )
            batch.exists += 1
            continue
        batch.rows.append(
            IngestRow(
                doi=doi,
                status="create",
                title=title,
                year=work.year,
                source=work.source,
            )
        )
    return batch


def apply_creates(
    backend: LibraryBackend,
    batch: IngestBatch,
    collection: str,
    *,
    works: dict[str, WorkMeta],
    tags: list[str],
    allowlist: frozenset[str] | None = None,
) -> IngestBatch:
    collection_key = backend.ensure_collection_path(collection)
    for row in batch.rows:
        if row.status != "create":
            continue
        work = works.get(row.doi)
        if work is None:
            row.status = "error"
            row.detail = "missing resolved work"
            batch.failed += 1
            continue
        record = _record_from_work(work, tags, allowlist=allowlist)
        payload = parent_payload(record, [collection_key])
        try:
            key = backend.create_parent(payload)
        except LibraryError as exc:
            row.status = "error"
            row.detail = str(exc)
            batch.failed += 1
            continue
        row.status = "created"
        row.item_key = key
        batch.created += 1
    batch.applied = True
    return batch


def write_summary(state_dir: Path, collection: str, batch: IngestBatch) -> Path:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = state_dir / "ingest" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "collection": collection,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "applied": batch.applied,
        "counts": batch.counts(),
        "rows": [asdict(r) for r in batch.rows],
    }
    path = folder / "summary.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    dois_path = folder / "created-dois.txt"
    dois_path.write_text(
        "".join(f"{r.doi}\n" for r in batch.rows if r.status in {"create", "created"}),
        encoding="utf-8",
    )
    return folder


def default_resolver(email: str) -> ResolveFn:
    import httpx

    client = httpx.Client(follow_redirects=True, timeout=30)

    def resolve(doi: str) -> WorkMeta | None:
        return work_by_doi(client, doi, email)

    return resolve


def _record_from_work(
    work: WorkMeta, tags: list[str], *, allowlist: frozenset[str] | None = None
) -> dict[str, Any]:
    authors = [work.first_author] if work.first_author else []
    item_type = _item_type(work.work_type or "")
    record: dict[str, Any] = {
        "item_type": item_type,
        "title": normalize_saved_title(work.title, allowlist),
        "creators": _creators(authors),
        "date": work.date or (str(work.year) if work.year else ""),
        "doi": work.doi,
        "url": "",
        "publication_title": work.venue or "",
        "tags": [{"tag": t} for t in tags],
    }
    if item_type == "bookSection":
        if work.book_title:
            record["book_title"] = work.book_title
        if work.series_title:
            record["series_title"] = work.series_title
        if work.pages:
            record["pages"] = work.pages
    return record


def _strip_url(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    return text


def ingest_tags(
    *,
    cli_tags: Iterable[str] | None,
    default_tags: Iterable[str] | None,
    from_file: Path | None,
) -> list[str]:
    extra = (
        [f"from-{seed_slug(from_file, fallback='dois')}"] if from_file is not None else []
    )
    return merge_tags(default_tags, cli_tags, extra)
