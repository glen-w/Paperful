"""PDF drop-folder watch: match hand downloads to library items and attach.

Distinct from snowball's ``state/snowball/watches/*/inbox.jsonl`` proposal queue.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .handoff import MissingPdf, attach_pdf_file, openable_rows
from .identity import LibraryFingerprint, inbox_dir_tag, merge_tags
from .inbox_match import (
    HoldLedger,
    MatchResult,
    TAG_CREATED,
    build_doi_index,
    build_title_year_index,
    load_proposal,
    match_pdf,
    save_proposal,
    write_proposal,
)
from .interop.load import parent_payload
from .library import LibraryBackend, LibraryError
from .resolve import WorkMeta, normalize_doi, work_by_doi
from .store import Manifest
from .zot import Item

PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")
UNMATCHED_DIRNAME = "unmatched"
REVIEW_DIRNAME = "review"
SOURCE = "inbox"


@dataclass
class IngestEvent:
    path: str
    status: str  # attached | unmatched | error | skipped | held | proposed | created_gated | created_auto
    item_key: str = ""
    how: str = ""
    doi: str = ""
    detail: str = ""


@dataclass
class WatchStats:
    attached: int = 0
    unmatched: int = 0
    errors: int = 0
    skipped: int = 0
    held: int = 0
    proposed: int = 0
    created_gated: int = 0
    created_auto: int = 0
    events: list[IngestEvent] = field(default_factory=list)
    quit_reason: str = ""


def inbox_dir(cfg: Config) -> Path | None:
    return cfg.inbox_path


def ensure_inbox_dirs(cfg: Config) -> Path:
    """Create the drop folder and ``unmatched/``. Raises if ``[inbox].dir`` is empty."""
    root = cfg.inbox_path
    if root is None:
        raise ValueError(
            "[inbox].dir is empty. Set it in config.toml (e.g. ~/Documents/paperful_inbox)."
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / UNMATCHED_DIRNAME).mkdir(parents=True, exist_ok=True)
    (root / REVIEW_DIRNAME).mkdir(parents=True, exist_ok=True)
    return root


def wait_stable(
    path: Path,
    settle_seconds: float,
    *,
    poll: float = 0.25,
    timeout: float = 120.0,
) -> bool:
    """True when size stays unchanged for ``settle_seconds`` (or settle is 0)."""
    if settle_seconds <= 0:
        return path.is_file()
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if not path.is_file():
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        now = time.monotonic()
        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= settle_seconds:
                return True
        else:
            last_size = size
            stable_since = None
        time.sleep(poll)
    return False


def _is_partial_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suf) for suf in PARTIAL_SUFFIXES)


def list_candidate_pdfs(root: Path) -> list[Path]:
    """Non-recursive ``*.pdf`` in the inbox root (not under ``unmatched/``)."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(root.glob("*.pdf")):
        if not path.is_file():
            continue
        if _is_partial_name(path.name):
            continue
        out.append(path)
    return out


def _fingerprint(path: Path) -> str:
    try:
        st = path.stat()
        size = st.st_size
        mtime = int(st.st_mtime)
    except OSError:
        return f"{path.resolve()}|missing"
    digest = ""
    try:
        h = hashlib.md5()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
    except OSError:
        digest = "unreadable"
    return f"{path.resolve()}|{size}|{mtime}|{digest}"


class SeenLedger:
    """Append-only skip list so the same file is not ingested twice."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: set[str] = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    self._seen.add(line)
                    continue
                fp = row.get("fingerprint") or row.get("fp")
                if isinstance(fp, str) and fp:
                    self._seen.add(fp)

    def has(self, fingerprint: str) -> bool:
        return fingerprint in self._seen

    def add(self, fingerprint: str, *, path: str, status: str) -> None:
        if fingerprint in self._seen:
            return
        self._seen.add(fingerprint)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "fingerprint": fingerprint,
            "path": path,
            "status": status,
            "at": datetime.now(tz=timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def move_unmatched(root: Path, pdf: Path, dest_name: str = UNMATCHED_DIRNAME) -> Path:
    dest_dir = root / dest_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / pdf.name
    if dest.exists():
        stem, suf = pdf.stem, pdf.suffix
        n = 1
        while True:
            candidate = dest_dir / f"{stem}-{n}{suf}"
            if not candidate.exists():
                dest = candidate
                break
            n += 1
    pdf.replace(dest)
    return dest


def ingest_one(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    pdf: Path,
    *,
    doi_index: dict[str, Item],
    fifo_queue: deque[MissingPdf] | None = None,
    items_by_key: dict[str, Item] | None = None,
    title_index: dict[tuple[str, int], Item | None] | None = None,
    missing_items: list[Item] | None = None,
    holds: HoldLedger | None = None,
    collection: str = "",
    resolve_work: Callable[[str], WorkMeta | None] | None = None,
    extra_tags: list[str] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> IngestEvent:
    """Match one stable PDF, attach, propose, create, hold, or quarantine."""
    say = on_status or (lambda _msg: None)
    root = ensure_inbox_dirs(cfg)
    matched = match_pdf(
        pdf,
        cfg=cfg,
        doi_index=doi_index,
        fifo_queue=fifo_queue,
        items_by_key=items_by_key,
        title_index=title_index,
        missing_items=missing_items,
        llm_match=lambda path, text, cands: _llm_match(cfg, path, text, cands),
        ocr_text=lambda path: _ocr_text(cfg, path),
    )
    if matched.item is not None:
        if matched.how == "llm" and matched.confidence is not None:
            if matched.confidence < cfg.inbox_llm_auto_attach_min:
                return _propose_attach(
                    cfg, pdf, matched, collection, say, gated=True
                )
        return _attach_matched(
            cfg, backend, manifest, pdf, matched, doi_index, title_index, say
        )
    return _unmatched_path(
        cfg,
        backend,
        manifest,
        pdf,
        matched,
        holds=holds,
        collection=collection,
        resolve_work=resolve_work,
        doi_index=doi_index,
        title_index=title_index,
        say=say,
        root=root,
        extra_tags=extra_tags,
    )


def process_candidates(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    items: list[Item],
    *,
    fifo_queue: deque[MissingPdf] | None = None,
    once: bool = False,
    idle_seconds: float | None = None,
    poll_seconds: float | None = None,
    settle_seconds: float | None = None,
    on_status: Callable[[str], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    collection: str = "",
    resolve_work: Callable[[str], WorkMeta | None] | None = None,
    now_fn: Callable[[], float] | None = None,
    extra_tags: list[str] | None = None,
) -> WatchStats:
    """Drain current PDFs (``once``) or poll until idle / interrupt."""
    say = on_status or (lambda _msg: None)
    sleeper = sleep_fn or time.sleep
    clock = now_fn or time.monotonic
    root = ensure_inbox_dirs(cfg)
    poll = cfg.inbox_poll_seconds if poll_seconds is None else poll_seconds
    settle = cfg.inbox_settle_seconds if settle_seconds is None else settle_seconds
    idle = cfg.inbox_idle_seconds if idle_seconds is None else idle_seconds
    doi_index = build_doi_index(items)
    title_index = build_title_year_index(items)
    items_by_key = {it.key: it for it in items}
    missing = [it for it in items if not it.has_pdf]
    ledger = SeenLedger(cfg.inbox_seen_path)
    holds = HoldLedger(cfg.inbox_holds_path)
    stats = WatchStats()
    last_activity = clock()

    def _handle(path: Path) -> None:
        nonlocal last_activity
        fp = _fingerprint(path)
        if ledger.has(fp):
            stats.skipped += 1
            stats.events.append(
                IngestEvent(path=str(path), status="skipped", detail="seen")
            )
            return
        if not wait_stable(path, settle):
            say(f"skip unstable {path.name}")
            stats.skipped += 1
            stats.events.append(
                IngestEvent(path=str(path), status="skipped", detail="unstable")
            )
            return
        fp = _fingerprint(path)
        if ledger.has(fp):
            stats.skipped += 1
            return
        event = ingest_one(
            cfg,
            backend,
            manifest,
            path,
            doi_index=doi_index,
            fifo_queue=fifo_queue,
            items_by_key=items_by_key,
            title_index=title_index,
            missing_items=missing,
            holds=holds,
            collection=collection,
            resolve_work=resolve_work,
            extra_tags=extra_tags,
            on_status=say,
        )
        stats.events.append(event)
        if event.status == "attached":
            stats.attached += 1
            last_activity = clock()
            ledger.add(fp, path=str(path), status=event.status)
            holds.drop(fp)
        elif event.status == "unmatched":
            stats.unmatched += 1
            last_activity = clock()
            ledger.add(fp, path=str(path), status=event.status)
            holds.drop(fp)
        elif event.status == "error":
            stats.errors += 1
            last_activity = clock()
            ledger.add(fp, path=str(path), status=event.status)
        elif event.status == "held":
            stats.held += 1
        elif event.status in {"proposed", "created_gated"}:
            stats.proposed += 1
            if event.status == "created_gated":
                stats.created_gated += 1
            last_activity = clock()
            ledger.add(fp, path=str(path), status=event.status)
            holds.drop(fp)
        elif event.status == "created_auto":
            stats.created_auto += 1
            stats.attached += 1
            last_activity = clock()
            ledger.add(fp, path=str(path), status=event.status)
            holds.drop(fp)

    try:
        while True:
            candidates = list_candidate_pdfs(root)
            for path in candidates:
                _handle(path)
            if once:
                stats.quit_reason = "drain"
                break
            if idle > 0 and (clock() - last_activity) >= idle:
                stats.quit_reason = "idle"
                say(f"idle for {idle:g}s — stopping")
                break
            sleeper(poll)
    except KeyboardInterrupt:
        stats.quit_reason = "interrupt"
        say("interrupted")
    return stats


def fifo_from_missing(rows: list[MissingPdf]) -> deque[MissingPdf]:
    return deque(openable_rows(rows))


def events_as_report_items(events: list[IngestEvent]) -> list[dict]:
    return [
        {
            "path": e.path,
            "status": e.status,
            "itemKey": e.item_key,
            "how": e.how,
            "doi": e.doi,
            "detail": e.detail,
        }
        for e in events
    ]


def summary_from_stats(stats: WatchStats) -> dict:
    return {
        "attached": stats.attached,
        "unmatched": stats.unmatched,
        "errors": stats.errors,
        "skipped": stats.skipped,
        "held": stats.held,
        "proposed": stats.proposed,
        "created_gated": stats.created_gated,
        "created_auto": stats.created_auto,
        "quit_reason": stats.quit_reason,
    }


def apply_proposal(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    proposal_id: str,
    *,
    resolve_work: Callable[[str], WorkMeta | None] | None = None,
    extra_tags: list[str] | None = None,
) -> dict:
    data = load_proposal(cfg, proposal_id)
    if data.get("status") != "pending":
        raise ValueError(f"proposal {proposal_id} is {data.get('status')}")
    action = data.get("action")
    pdf = Path(str(data.get("pdf") or ""))
    if action == "attach":
        key = str(data.get("item_key") or "")
        item = _item_from_key(backend, key)
        if item is None:
            raise ValueError(f"item {key} not found")
        if pdf.is_file():
            attach_pdf_file(cfg, backend, manifest, item, pdf, source=SOURCE)
            pdf.unlink(missing_ok=True)
        data["status"] = "applied"
        save_proposal(data)
        return data
    if action == "create_parent":
        item = _create_inbox_parent(
            cfg,
            backend,
            data,
            resolve_work=resolve_work,
            extra_tags=merge_tags(data.get("extra_tags"), extra_tags),
        )
        if pdf.is_file():
            attach_pdf_file(cfg, backend, manifest, item, pdf, source=SOURCE)
            pdf.unlink(missing_ok=True)
        data["status"] = "applied"
        data["item_key"] = item.key
        save_proposal(data)
        return data
    raise ValueError(f"unknown proposal action {action!r}")


def reject_proposal(cfg: Config, proposal_id: str) -> dict:
    data = load_proposal(cfg, proposal_id)
    data["status"] = "rejected"
    save_proposal(data)
    return data


def _attach_matched(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    pdf: Path,
    matched: MatchResult,
    doi_index: dict[str, Item],
    title_index: dict[tuple[str, int], Item | None] | None,
    say: Callable[[str], None],
) -> IngestEvent:
    item = matched.item
    assert item is not None
    try:
        attach_pdf_file(cfg, backend, manifest, item, pdf, source=SOURCE)
    except (OSError, ValueError, LibraryError) as exc:
        say(f"error {pdf.name}: {exc}")
        return IngestEvent(
            path=str(pdf),
            status="error",
            item_key=item.key,
            how=matched.how,
            doi=matched.doi or "",
            detail=str(exc),
        )
    if cfg.inbox_manager_metadata_s > 0:
        time.sleep(cfg.inbox_manager_metadata_s)
    try:
        pdf.unlink(missing_ok=True)
    except OSError as exc:
        say(f"attached {item.key} ← {pdf.name} (could not remove drop file: {exc})")
    else:
        say(f"attached {item.key} ← {pdf.name} ({matched.how})")
    doi = normalize_doi(item.doi)
    if doi and doi_index.get(doi) is item:
        del doi_index[doi]
    if title_index is not None:
        from .dedupe import normalize_dedupe_title

        tkey = (normalize_dedupe_title(item.title), item.year)
        if tkey in title_index:
            del title_index[tkey]
    item.has_pdf = True
    return IngestEvent(
        path=str(pdf),
        status="attached",
        item_key=item.key,
        how=matched.how,
        doi=matched.doi or "",
        detail=SOURCE,
    )


def _propose_attach(
    cfg: Config,
    pdf: Path,
    matched: MatchResult,
    collection: str,
    say: Callable[[str], None],
    *,
    gated: bool,
) -> IngestEvent:
    item = matched.item
    dest = write_proposal(
        cfg,
        {
            "action": "attach",
            "pdf": str(pdf),
            "item_key": item.key if item else "",
            "doi": matched.doi or "",
            "title": matched.title,
            "year": matched.year,
            "how": matched.how,
            "confidence": matched.confidence,
            "collection": collection,
        },
    )
    say(f"proposed attach {pdf.name} → {dest.name} ({matched.how})")
    return IngestEvent(
        path=str(pdf),
        status="proposed",
        item_key=item.key if item else "",
        how=matched.how,
        doi=matched.doi or "",
        detail=str(dest),
    )


def _unmatched_path(
    cfg: Config,
    backend: LibraryBackend,
    manifest: Manifest,
    pdf: Path,
    matched: MatchResult,
    *,
    holds: HoldLedger | None,
    collection: str,
    resolve_work: Callable[[str], WorkMeta | None] | None,
    doi_index: dict[str, Item],
    title_index: dict[tuple[str, int], Item | None] | None,
    say: Callable[[str], None],
    root: Path,
    extra_tags: list[str] | None = None,
) -> IngestEvent:
    wait_s = cfg.inbox_quarantine_after_s
    if wait_s > 0 and holds is not None:
        fp = _fingerprint(pdf)
        first = holds.first_seen(fp, now=time.time())
        if (time.time() - first) < wait_s:
            say(f"held {pdf.name} (waiting {wait_s:g}s before unmatched)")
            return IngestEvent(
                path=str(pdf),
                status="held",
                how=matched.how,
                doi=matched.doi or "",
                detail="quarantine_after_s",
            )
    if cfg.inbox_create == "create_gated":
        parked = move_unmatched(root, pdf, REVIEW_DIRNAME)
        dest = write_proposal(
            cfg,
            {
                "action": "create_parent",
                "pdf": str(parked),
                "doi": matched.doi or "",
                "title": matched.title,
                "year": matched.year,
                "how": matched.how,
                "collection": collection,
                "extra_tags": list(extra_tags or []),
            },
        )
        say(f"proposal {dest.name} for {parked.name}")
        return IngestEvent(
            path=str(pdf),
            status="created_gated",
            how=matched.how,
            doi=matched.doi or "",
            detail=str(dest),
        )
    if cfg.inbox_create == "create_auto" and matched.doi:
        work = (resolve_work or _default_resolve(cfg))(matched.doi)
        if work is not None:
            fp = LibraryFingerprint.from_items(
                list(backend.items_in_scope(None))
                if hasattr(backend, "items_in_scope")
                else []
            )
            if fp.find(matched.doi, work.title, work.year) is None:
                data = {
                    "doi": matched.doi,
                    "title": work.title,
                    "year": work.year,
                    "collection": collection,
                }
                item = _create_inbox_parent(
                    cfg, backend, data, work=work, extra_tags=extra_tags
                )
                attached = _attach_matched(
                    cfg, backend, manifest, pdf, MatchResult(item=item, how="doi", doi=matched.doi),
                    doi_index, title_index, say,
                )
                attached.status = "created_auto"
                attached.detail = TAG_CREATED
                say(f"created {item.key} ← {pdf.name}")
                return attached
        dest = move_unmatched(root, pdf, REVIEW_DIRNAME)
        say(f"review {pdf.name} → {dest} (create_auto fail-closed)")
        return IngestEvent(
            path=str(pdf),
            status="unmatched",
            how=matched.how,
            doi=matched.doi or "",
            detail="create_auto fail-closed",
        )
    dest = move_unmatched(root, pdf)
    detail = matched.reason or "unmatched"
    say(f"unmatched {pdf.name} → {dest} ({detail})")
    return IngestEvent(
        path=str(pdf),
        status="unmatched",
        how=matched.how,
        doi=matched.doi or "",
        detail=detail,
    )


def _create_inbox_parent(
    cfg: Config,
    backend: LibraryBackend,
    data: dict,
    *,
    resolve_work: Callable[[str], WorkMeta | None] | None = None,
    work: WorkMeta | None = None,
    extra_tags: list[str] | None = None,
) -> Item:
    from .acronyms import load_acronym_allowlist
    from .lint import normalize_saved_title, usable_work_title
    from .snowball.ingest import _creators, _item_type

    doi = normalize_doi(data.get("doi")) or ""
    if work is None and doi:
        work = (resolve_work or _default_resolve(cfg))(doi)
    title = normalize_saved_title(
        str((work.title if work else "") or data.get("title") or ""),
        load_acronym_allowlist(cfg.state_dir),
    )
    if not usable_work_title(title):
        raise ValueError("unusable title for inbox create")
    collection = str(data.get("collection") or "").strip()
    if not collection:
        raise ValueError("inbox create needs -C / collection")
    collection_key = backend.ensure_collection_path(collection)
    tags = merge_tags(
        cfg.ingest_default_tags,
        extra_tags,
        [TAG_CREATED],
        [inbox_dir_tag(cfg.inbox_dir)],
    )
    year = work.year if work else data.get("year")
    record = {
        "item_type": _item_type(work.work_type if work else "") or "journalArticle",
        "title": title,
        "creators": _creators([work.first_author] if work and work.first_author else []),
        "date": (work.date if work and work.date else str(year or "")),
        "doi": doi or (work.doi if work else ""),
        "publication_title": (work.venue if work else "") or "",
        "tags": [{"tag": t} for t in tags],
    }
    key = backend.create_parent(parent_payload(record, [collection_key]))
    return Item(
        key=key,
        item_type=str(record["item_type"]),
        title=title,
        doi=record["doi"] or None,
        arxiv_id=None,
        url=None,
        year=int(year) if year else None,
        first_author=work.first_author if work else None,
        collection_paths=[collection],
        doi_source="crossref" if record["doi"] else "none",
        has_pdf=False,
    )


def _default_resolve(cfg: Config) -> Callable[[str], WorkMeta | None]:
    import httpx

    client = httpx.Client(follow_redirects=True, timeout=30)

    def resolve(doi: str) -> WorkMeta | None:
        return work_by_doi(client, doi, cfg.email)

    return resolve


def _item_from_key(backend: LibraryBackend, key: str) -> Item | None:
    if not key:
        return None
    if hasattr(backend, "items_in_scope"):
        for item in backend.items_in_scope(None):
            if item.key == key:
                return item
    return None


def _ocr_text(cfg: Config, path: Path) -> str:
    if not cfg.inbox_ocr_for_match and cfg.inbox_match not in {"doi+title+ocr", "full"}:
        return ""
    try:
        from .ocr import ocr_text_for_match

        return ocr_text_for_match(cfg, path)
    except Exception:
        return ""


def _llm_match(
    cfg: Config, path: Path, text: str, candidates: list[Item]
) -> MatchResult | None:
    if not cfg.llm_enabled:
        return None
    short = [c for c in candidates if not c.has_pdf][:8]
    if not short or not text.strip():
        return None
    try:
        from .grounding import metadata_block
        from .llm import CompletionRequest, get_client
    except Exception:
        return None
    client = get_client(cfg)
    model = cfg.inbox_model or cfg.llm_model
    blocks = "\n\n".join(f"KEY {item.key}\n{metadata_block(item)}" for item in short)
    prompt = (
        "Which library item does this PDF excerpt belong to? "
        'Reply JSON only: {"item_key": "...", "match": true|false, '
        '"confidence": 0-1, "reason": "..."}. Use item_key from the list. '
        "If none match, match=false.\n\n"
        f"{blocks}\n\nPDF excerpt:\n{text[:6000]}"
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
    if conf < cfg.inbox_llm_match_min_confidence:
        return MatchResult(
            item=None,
            how="llm",
            reason=f"low confidence {conf:.2f}",
            confidence=conf,
            text=text,
        )
    key = str(data.get("item_key") or "")
    item = next((c for c in short if c.key == key), None)
    if item is None:
        return None
    return MatchResult(
        item=item,
        how="llm",
        doi=normalize_doi(item.doi),
        confidence=conf,
        text=text,
        title=item.title,
        year=item.year,
    )
