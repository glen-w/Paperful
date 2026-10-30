"""Discover grow jobs: ingest-dois preview/apply."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Config
from . import commands


def ingest_preview(
    cfg: Config,
    cmd_id: str,
    *,
    collection: str,
    source_path: str,
) -> str:
    from ..acronyms import load_acronym_allowlist
    from ..catalogue import open_library
    from ..identity import LibraryFingerprint
    from ..ingest_dois import (
        classify_rows,
        default_resolver,
        dois_from_file,
        dois_from_refs_pack,
        write_summary,
    )

    if not collection.strip():
        raise ValueError("Set the collection chip before ingest-dois.")
    if not source_path.strip():
        raise ValueError("Pass a DOI file or refs-gap pack path.")
    path = Path(source_path).expanduser()
    if not path.exists():
        raise ValueError(f"Not found: {path}")
    if path.is_dir() or path.name == "pack.json" or "refs-gap" in str(path):
        pack = path / "pack.json" if path.is_dir() else path
        dois = dois_from_refs_pack(pack)
        source = pack
    else:
        dois = dois_from_file(path)
        source = path
    if not dois:
        raise ValueError("No DOIs to ingest.")
    backend = open_library(cfg)
    all_items = list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else []
    fingerprint = LibraryFingerprint.from_items(
        all_items,
        scope=cfg.ingest_dedupe_scope,
        collection=collection,
    )
    resolver = default_resolver(cfg.email)
    allowed = load_acronym_allowlist(cfg.state_dir)
    batch = classify_rows(dois, fingerprint, resolve=resolver, allowlist=allowed)
    summary_path = write_summary(cfg.state_dir, collection, batch)
    import hashlib

    fingerprint_hex = hashlib.sha256(
        f"{collection}|{source}|{','.join(dois)}".encode("utf-8")
    ).hexdigest()
    token = commands.create_review_token(
        cfg,
        verb="ingest_dois",
        collection=collection,
        preset="oa",
        keys=dois[:200],
        fingerprint=fingerprint_hex,
        command_id=cmd_id,
        flags={"source_path": str(source), "dois": dois},
    )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["result"] = {
        "counts": batch.counts(),
        "summary": str(summary_path),
        "source": str(source),
    }
    commands.write_command(cfg, rec)
    return token


def ingest_apply(
    cfg: Config, *, token: str, collection: str
) -> tuple[bool, str]:
    from ..acronyms import load_acronym_allowlist
    from ..catalogue import open_library
    from ..identity import LibraryFingerprint
    from ..ingest_dois import (
        apply_creates,
        classify_rows,
        default_resolver,
        ingest_tags,
        write_summary,
    )

    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    flags = dict(review.get("flags") or {})
    source = str(flags.get("source_path") or "")
    dois = list(flags.get("dois") or [])
    coll = str(review.get("collection") or collection or "")
    if not coll or not dois:
        return False, "missing ingest preview data"
    import hashlib

    fingerprint_hex = hashlib.sha256(
        f"{coll}|{source}|{','.join(dois)}".encode("utf-8")
    ).hexdigest()
    ok, msg = commands.consume_review(cfg, token, fingerprint=fingerprint_hex, keys=None)
    if not ok:
        return False, msg
    backend = open_library(cfg)
    all_items = list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else []
    fingerprint = LibraryFingerprint.from_items(
        all_items,
        scope=cfg.ingest_dedupe_scope,
        collection=coll,
    )
    resolver = default_resolver(cfg.email)
    allowed = load_acronym_allowlist(cfg.state_dir)
    works: dict[str, Any] = {}

    def resolve(doi: str):
        work = resolver(doi)
        if work is not None:
            works[doi] = work
        return work

    batch = classify_rows(dois, fingerprint, resolve=resolve, allowlist=allowed)
    tags = ingest_tags(
        cli_tags=[],
        default_tags=cfg.ingest_default_tags,
        from_file=Path(source) if source else None,
    )
    apply_creates(backend, batch, coll, works=works, tags=tags, allowlist=allowed)
    write_summary(cfg.state_dir, coll, batch)
    flush = getattr(backend, "flush", None)
    if callable(flush):
        flush()
    return True, ""


def file_frontier_note(cfg: Config, html: str, collection: str) -> str:
    """File a collection note tagged paperful:frontier-briefing. Returns item key."""
    from ..catalogue import open_library

    coll = (collection or "").strip()
    if not coll:
        raise ValueError("Filing a briefing note needs a collection chip.")
    backend = open_library(cfg)
    col = backend.resolve_collection(coll)
    key = backend.create_or_update_collection_note(
        col.key, html, ["paperful:frontier-briefing"]
    )
    flush = getattr(backend, "flush", None)
    if callable(flush):
        flush()
    return str(key)


def _search_apply_fingerprint(cfg: Config, run_id: str, collection: str, urls: list[str]) -> str:
    import hashlib

    joined = ",".join(sorted(u for u in urls if u))
    return hashlib.sha256(f"search|{run_id}|{collection}|{joined}".encode()).hexdigest()


def search_apply_preview(
    cfg: Config,
    cmd_id: str,
    *,
    run_id: str,
    collection: str,
    urls: list[str],
) -> str:
    from ..search.apply import mark_exists
    from ..search.store import load_run

    coll = (collection or "").strip()
    if not coll:
        raise ValueError("Set the collection chip before adding web hits.")
    cleaned = (run_id or "").strip()
    if not cleaned:
        raise ValueError("No search run to apply.")
    selected = [u.strip() for u in urls if str(u).strip()]
    if not selected:
        raise ValueError("Tick at least one hit.")
    bundle = load_run(cfg, cleaned)
    candidates = list(bundle.get("candidates") or [])
    mark_exists(cfg, candidates)
    known = {str(row.get("url") or "") for row in candidates}
    missing = [u for u in selected if u not in known]
    if missing:
        raise ValueError("Selected URL is not in this search run.")
    token = commands.create_review_token(
        cfg,
        verb="search_apply",
        collection=coll,
        preset="oa",
        keys=selected,
        fingerprint=_search_apply_fingerprint(cfg, cleaned, coll, selected),
        command_id=cmd_id,
        flags={"run_id": cleaned, "urls": selected},
    )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["result"] = {"run_id": cleaned, "selected": len(selected), "review_token": token}
    rec["review_token"] = token
    commands.write_command(cfg, rec)
    return token


def search_apply(
    cfg: Config, *, token: str, collection: str
) -> tuple[bool, str]:
    from ..search.apply import apply_candidates, mark_exists
    from ..search.store import load_run

    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    flags = dict(review.get("flags") or {})
    run_id = str(flags.get("run_id") or "").strip()
    urls = [str(u) for u in (flags.get("urls") or []) if str(u).strip()]
    coll = str(review.get("collection") or collection or "").strip()
    if not coll or not run_id or not urls:
        return False, "missing search preview data"
    fp = _search_apply_fingerprint(cfg, run_id, coll, urls)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=urls)
    if not ok:
        return False, msg
    bundle = load_run(cfg, run_id)
    candidates = list(bundle.get("candidates") or [])
    mark_exists(cfg, candidates)
    apply_candidates(cfg, candidates, coll, urls=urls)
    return True, ""
