"""Repair and Mirror job runners (Preview dry-run → Apply write)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..store import Manifest
from . import commands
from .pages import queue_fingerprint

# Test hooks
repair_run_fn: Callable[..., dict[str, Any]] | None = None
mirror_run_fn: Callable[..., dict[str, Any]] | None = None


def _attach_result(cfg: Config, cmd_id: str, result: dict[str, Any]) -> None:
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["result"] = result
    commands.write_command(cfg, rec)


def _open_scope(cfg: Config, collection: str) -> tuple[Any, list[Any], str]:
    from ..catalogue import open_library
    from ..scope import load_scope

    backend = open_library(cfg)
    coll = (collection or "").strip()
    loaded = load_scope(
        backend,
        collections=[coll] if coll else [],
        library=not bool(coll),
    )
    return backend, list(loaded.items), loaded.label


def _mint(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    fingerprint: str,
    flags: dict[str, Any],
) -> str:
    token = commands.create_review_token(
        cfg,
        verb=verb,
        collection=collection,
        preset="oa",
        keys=[verb],
        fingerprint=fingerprint,
        command_id=cmd_id,
        flags=flags,
    )
    return token


def repair_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    flags: dict[str, Any] | None = None,
) -> str:
    flags = dict(flags or {})
    if repair_run_fn is not None:
        result = repair_run_fn(cfg, verb=verb, collection=collection, apply=False, flags=flags)
        _attach_result(cfg, cmd_id, result)
        fp = queue_fingerprint(cfg, verb)
        return _mint(cfg, cmd_id, verb=verb, collection=collection, fingerprint=fp, flags=flags)
    result = _repair_run(cfg, verb=verb, collection=collection, apply=False, flags=flags)
    _attach_result(cfg, cmd_id, result)
    fp = queue_fingerprint(cfg, verb)
    return _mint(cfg, cmd_id, verb=verb, collection=collection, fingerprint=fp, flags=flags)


def repair_apply(
    cfg: Config,
    *,
    token: str,
    flags: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    verb = str(review.get("verb") or "")
    collection = str(review.get("collection") or "")
    merged = dict(review.get("flags") or {})
    if flags:
        merged.update(flags)
    fp = queue_fingerprint(cfg, verb)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg
    if verb == "lint":
        return True, ""
    if repair_run_fn is not None:
        repair_run_fn(cfg, verb=verb, collection=collection, apply=True, flags=merged)
        return True, ""
    _repair_run(cfg, verb=verb, collection=collection, apply=True, flags=merged)
    return True, ""


def mirror_fingerprint(cfg: Config, verb: str, collection: str, flags: dict[str, Any]) -> str:
    payload = json.dumps(
        {"verb": verb, "collection": collection, "flags": flags},
        sort_keys=True,
        default=str,
    )
    # Include a coarse out/ mtime so a changed mirror invalidates the token.
    out_marker = ""
    out = cfg.out_dir
    if out.is_dir():
        try:
            out_marker = str(int(out.stat().st_mtime_ns))
        except OSError:
            out_marker = ""
    return hashlib.sha256(f"{payload}|{out_marker}".encode("utf-8")).hexdigest()


def mirror_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    flags: dict[str, Any] | None = None,
) -> str:
    flags = dict(flags or {})
    if mirror_run_fn is not None:
        result = mirror_run_fn(cfg, verb=verb, collection=collection, apply=False, flags=flags)
        _attach_result(cfg, cmd_id, result)
    else:
        result = _mirror_run(cfg, verb=verb, collection=collection, apply=False, flags=flags)
        _attach_result(cfg, cmd_id, result)
    fp = mirror_fingerprint(cfg, verb, collection, flags)
    return _mint(cfg, cmd_id, verb=verb, collection=collection, fingerprint=fp, flags=flags)


def mirror_apply(
    cfg: Config,
    *,
    token: str,
    collection: str = "",
    flags: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token"
    verb = str(review.get("verb") or "")
    coll = str(review.get("collection") or collection or "")
    merged = dict(review.get("flags") or {})
    if flags:
        merged.update(flags)
    fp = mirror_fingerprint(cfg, verb, coll, merged)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg
    if mirror_run_fn is not None:
        mirror_run_fn(cfg, verb=verb, collection=coll, apply=True, flags=merged)
        return True, ""
    _mirror_run(cfg, verb=verb, collection=coll, apply=True, flags=merged)
    return True, ""


def _repair_run(
    cfg: Config,
    *,
    verb: str,
    collection: str,
    apply: bool,
    flags: dict[str, Any],
) -> dict[str, Any]:
    if verb == "lint":
        return _lint(cfg, collection)
    if verb == "fix-metadata":
        return _fix_metadata(cfg, collection, apply=apply, overwrite=bool(flags.get("overwrite")))
    if verb == "dedupe":
        return _dedupe(
            cfg,
            collection,
            apply=apply,
            apply_medium=bool(flags.get("apply_medium")),
            phase=str(flags.get("phase") or "all"),
        )
    if verb == "versions":
        return _versions(cfg, collection, apply=apply)
    if verb == "attachments":
        return _attachments(
            cfg,
            collection,
            apply=apply,
            fix_broken=bool(flags.get("fix_broken")),
            merge_files=bool(flags.get("merge_files")),
            rename=bool(flags.get("rename")),
            link=bool(flags.get("link")),
        )
    if verb == "ocr":
        return _ocr(cfg, collection, apply=apply, attach=bool(flags.get("attach")))
    raise ValueError(f"unknown repair verb {verb!r}")


def _mirror_run(
    cfg: Config,
    *,
    verb: str,
    collection: str,
    apply: bool,
    flags: dict[str, Any],
) -> dict[str, Any]:
    if verb == "sync":
        return _sync(
            cfg,
            apply=apply,
            full=bool(flags.get("full")),
            pdfs=str(flags.get("pdfs") or "") or None,
            accept_gone=bool(flags.get("accept_gone")),
        )
    if verb == "snapshot":
        return _snapshot(cfg, collection, apply=apply, pdfs=str(flags.get("pdfs") or "") or None)
    if verb == "restore":
        return _restore(cfg, collection, apply=apply)
    if verb == "cache clean":
        return _cache_clean(cfg, apply=apply)
    raise ValueError(f"unknown mirror verb {verb!r}")


def _lint(cfg: Config, collection: str) -> dict[str, Any]:
    from ..lint import lint_items
    from ..pipeline import make_client
    from ..runreport import write_command_report

    backend, items, scope = _open_scope(cfg, collection)
    started = time.time()
    client = make_client(cfg)
    try:
        findings = lint_items(
            client, cfg, items, backend=backend, manifest=Manifest(cfg.manifest_path)
        )
    finally:
        client.close()
    by_code: dict[str, int] = {}
    for f in findings:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    write_command_report(
        cfg,
        command="lint",
        scope=scope,
        summary={"items": len(items), "findings": len(findings), "findings_by_code": by_code},
        items=[
            {"itemKey": f.itemKey, "code": f.code, "detail": f.detail, "title": f.title}
            for f in findings[:200]
        ],
        flags={"apply": False},
        started=started,
    )
    return {"verb": "lint", "scope": scope, "findings": len(findings), "items": len(items)}


def _fix_metadata(
    cfg: Config, collection: str, *, apply: bool, overwrite: bool
) -> dict[str, Any]:
    from ..metadata import apply_patches, collect_patches, write_patches
    from ..pipeline import make_client
    from ..runreport import write_command_report

    backend, items, scope = _open_scope(cfg, collection)
    started = time.time()
    client = make_client(cfg)
    try:
        patches = collect_patches(
            client,
            cfg,
            items,
            backend=backend,
            manifest=Manifest(cfg.manifest_path),
            overwrite=overwrite,
        )
    finally:
        client.close()
    write_patches(cfg.patches_path, patches)
    applied_n = 0
    errors: list[str] = []
    if apply:
        applied_n, errors = apply_patches(backend, patches)
        flush = getattr(backend, "flush", None)
        if callable(flush):
            flush()
    write_command_report(
        cfg,
        command="fix-metadata",
        scope=scope,
        summary={
            "patches_proposed": len(patches),
            **({"patches_applied": applied_n} if apply else {}),
            "errors": len(errors),
        },
        items=[
            {"itemKey": p.itemKey, "title": p.title, "after": p.after} for p in patches[:200]
        ],
        flags={"apply": apply, "overwrite": overwrite},
        started=started,
        errors=errors or None,
    )
    return {
        "verb": "fix-metadata",
        "scope": scope,
        "patches": len(patches),
        "applied": applied_n if apply else None,
    }


def _dedupe(
    cfg: Config,
    collection: str,
    *,
    apply: bool,
    apply_medium: bool,
    phase: str,
) -> dict[str, Any]:
    from ..dedupe import (
        apply_merge,
        attach_merge_previews,
        classify,
        pack_counts,
        write_pack,
    )

    backend, items, scope = _open_scope(cfg, collection)
    groups = classify(items, phase)
    attach_merge_previews(backend, groups)
    json_path, _md = write_pack(
        cfg.state_dir, scope, groups, phase=phase, n_items=len(items)
    )
    counts = pack_counts(groups, len(items))
    applied = 0
    errors: list[str] = []
    if apply:
        from ..remarks import remark_duplicates

        remark_duplicates(backend, groups, items, surface=cfg.remarks_surface)
        applied, errors = apply_merge(
            backend,
            groups,
            apply_medium=apply_medium,
            audit_path=cfg.dedupe_applied_path,
            scope=scope,
            pack=json_path,
        )
        flush = getattr(backend, "flush", None)
        if callable(flush):
            flush()
    return {
        "verb": "dedupe",
        "scope": scope,
        "pack": str(json_path),
        "counts": counts,
        "applied": applied if apply else None,
        "errors": errors,
    }


def _versions(cfg: Config, collection: str, *, apply: bool) -> dict[str, Any]:
    import httpx

    from ..versions import (
        apply_versions,
        classify_versions,
        http_fetch_published,
        pack_counts,
        resolver_for,
        write_pack,
    )

    backend, items, scope = _open_scope(cfg, collection)
    client = httpx.Client(follow_redirects=True, timeout=30)
    applied = 0
    errors: list[str] = []
    try:
        proposals = classify_versions(items, resolver_for(client, cfg.email))
        json_path, _md = write_pack(cfg.state_dir, scope, proposals, n_items=len(items))
        counts = pack_counts(proposals, len(items))
        if apply:
            applied, errors = apply_versions(
                backend,
                proposals,
                fetch_published=http_fetch_published(client, cfg.email),
                audit_path=cfg.versions_applied_path,
                scope=scope,
                pack=json_path,
            )
            flush = getattr(backend, "flush", None)
            if callable(flush):
                flush()
    finally:
        client.close()
    return {
        "verb": "versions",
        "scope": scope,
        "pack": str(json_path),
        "counts": counts,
        "applied": applied if apply else None,
        "errors": errors,
    }


def _attachments(
    cfg: Config,
    collection: str,
    *,
    apply: bool,
    fix_broken: bool,
    merge_files: bool,
    rename: bool,
    link: bool,
) -> dict[str, Any]:
    from ..attachments import (
        SurgeryFlags,
        apply_actions,
        apply_refusal,
        mirror_pdfs_for,
        pdf_children,
        plan_actions,
        stem_filename,
        summarize,
    )
    from ..library import LibraryError
    from ..runreport import write_command_report

    backend, items, scope = _open_scope(cfg, collection)
    flags = SurgeryFlags(
        fix_broken=fix_broken or cfg.attachments_fix_broken,
        merge_files=merge_files or cfg.attachments_merge_files,
        rename=rename or cfg.attachments_rename,
        link=link or cfg.attachments_link,
    )
    started = time.time()
    children = []
    mirrors: dict = {}
    stems: dict = {}
    unread: list[str] = []

    def _child_bytes(child: dict[str, Any]) -> bool:
        from pathlib import Path as _Path

        data = child.get("data") or {}
        key = str(child.get("key") or data.get("key") or "")
        if data.get("linkMode") == "linked_file":
            path = data.get("path")
            return bool(path) and _Path(str(path)).is_file()
        probe = getattr(backend, "attachment_has_bytes", None)
        if probe is None or not key:
            return True
        try:
            return bool(probe(key))
        except Exception:
            return False

    for item in items:
        try:
            raw = backend.children(item.key) or []
        except LibraryError:
            unread.append(item.key)
            continue
        present = {
            str(ch.get("key") or (ch.get("data") or {}).get("key") or ""): _child_bytes(ch)
            for ch in raw
            if isinstance(ch, dict)
        }
        children.extend(pdf_children(item.key, raw, present=present))
        mirrors[item.key] = mirror_pdfs_for(cfg.out_dir, item)
        stems[item.key] = stem_filename(item)
    scan = plan_actions(
        children,
        mirrors,
        stems,
        flags,
        out_dir=cfg.out_dir,
        library_type=str(getattr(backend, "library_type", "user")),
    )
    applied = 0
    errors: list[str] = list(scan.refusals)
    if unread:
        errors.append(f"{len(unread)} item(s) could not be read and were skipped")
    if apply and flags.any:
        refusal = apply_refusal(
            manager=cfg.manager,
            library_type=str(getattr(backend, "library_type", "user")),
            link=flags.link,
        )
        if refusal:
            errors.append(refusal)
        else:
            applied, apply_errors = apply_actions(
                backend, scan.actions, out_dir=cfg.out_dir
            )
            errors.extend(apply_errors)
            flush = getattr(backend, "flush", None)
            if callable(flush):
                flush()
    counts = summarize(scan.findings)
    write_command_report(
        cfg,
        command="attachments",
        scope=scope,
        summary={
            "items": len(items),
            "findings": counts,
            "actions": len(scan.actions) if apply and flags.any else 0,
            "applied": applied,
        },
        items=[
            {
                "kind": f.kind,
                "parent": f.parent_key,
                "attachment": f.attachment_key,
                "detail": f.detail,
            }
            for f in scan.findings
            if f.kind != "ok"
        ][:200],
        flags={
            "apply": apply,
            "fix_broken": flags.fix_broken,
            "merge_files": flags.merge_files,
            "rename": flags.rename,
            "link": flags.link,
        },
        started=started,
        errors=errors or None,
    )
    return {
        "verb": "attachments",
        "scope": scope,
        "findings": counts,
        "applied": applied if apply else None,
        "errors": errors,
    }


def _ocr(cfg: Config, collection: str, *, apply: bool, attach: bool) -> dict[str, Any]:
    from ..ocr import OcrUnavailable, ocr_items
    from ..runreport import write_command_report

    backend, items, scope = _open_scope(cfg, collection)
    started = time.time()
    try:
        batch = ocr_items(
            cfg,
            items,
            Manifest(cfg.manifest_path),
            backend,
            apply=apply,
            attach=attach and apply,
        )
    except OcrUnavailable as exc:
        raise ValueError(str(exc)) from exc
    write_command_report(
        cfg,
        command="ocr",
        scope=scope,
        summary={
            "items": len(items),
            "ocr": batch.ocr,
            "would": batch.would,
            "failed": batch.failed,
            "skipped": batch.skipped,
            "not_reached": batch.not_reached,
        },
        items=[
            {
                "itemKey": r.key,
                "title": r.title,
                "status": r.status,
                "detail": r.reason,
            }
            for r in batch.rows[:200]
        ],
        flags={"apply": apply, "attach": attach},
        started=started,
    )
    return {
        "verb": "ocr",
        "scope": scope,
        "ocr": batch.ocr,
        "would": batch.would,
        "failed": batch.failed,
        "skipped": batch.skipped,
    }


def _sync(
    cfg: Config,
    *,
    apply: bool,
    full: bool,
    pdfs: str | None,
    accept_gone: bool,
) -> dict[str, Any]:
    from ..catalogue import open_library
    from ..sync import run_sync

    backend = open_library(cfg)
    stats = run_sync(
        cfg,
        backend,
        full=full,
        dry_run=not apply,
        pdfs=pdfs,
        accept_gone=accept_gone,
    )
    return {
        "verb": "sync",
        "written": stats.written,
        "full": stats.full,
        "dry_run": not apply,
    }


def _snapshot(
    cfg: Config, collection: str, *, apply: bool, pdfs: str | None
) -> dict[str, Any]:
    from ..snapshot import run_snapshot

    backend, items, scope = _open_scope(cfg, collection)
    mode = pdfs or cfg.mirror_pdfs
    stats = run_snapshot(
        cfg,
        backend,
        items,
        pdfs=mode,
        dry_run=not apply,
        manifest=Manifest(cfg.manifest_path),
    )
    return {
        "verb": "snapshot",
        "scope": scope,
        "records": stats.records,
        "pdf_exports": stats.pdf_exports,
        "dry_run": not apply,
    }


def _restore(cfg: Config, collection: str, *, apply: bool) -> dict[str, Any]:
    from ..catalogue import open_library
    from ..restore import apply_restore, dedupe_restore_records, iter_records, plan_restore

    backend = open_library(cfg)
    coll = (collection or "").strip()
    prefixes = [coll] if coll else None
    paths = iter_records(cfg.out_dir, prefixes)
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict):
            records.append((path, data))
    records = dedupe_restore_records(records)
    library_items = list(backend.items_in_scope(None)) if hasattr(backend, "items_in_scope") else []
    if not library_items and coll:
        from ..scope import load_scope

        loaded = load_scope(backend, collections=[coll], library=False)
        library_items = list(loaded.items)
    note_tags: dict[str, set[str]] = {}
    planned = plan_restore(records, library_items, note_tags_for=note_tags)
    counts = planned.counts()
    done: dict[str, int] = {}
    if apply:
        done = apply_restore(planned, backend, backend)
        flush = getattr(backend, "flush", None)
        if callable(flush):
            flush()
    return {
        "verb": "restore",
        "counts": counts,
        "applied": done if apply else None,
        "dry_run": not apply,
    }


def _cache_clean(cfg: Config, *, apply: bool) -> dict[str, Any]:
    from ..sync import clean_pdf_cache

    report = clean_pdf_cache(cfg, apply=apply)
    report["verb"] = "cache clean"
    report["dry_run"] = not apply
    return report
