"""Repair and Mirror workbench jobs (library cores, not Typer)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..library import LibraryError
from ..store import Manifest
from . import commands
from .preview_store import file_fingerprint, preview_path, read_preview, write_preview

# Test hooks (replace entire preview/apply when set)
repair_preview_core_fn: Callable[..., None] | None = None
repair_apply_core_fn: Callable[..., dict[str, Any]] | None = None
mirror_preview_core_fn: Callable[..., None] | None = None
mirror_apply_core_fn: Callable[..., dict[str, Any]] | None = None

READ_ONLY_REPAIR = frozenset({"lint"})


class GuiScopeError(ValueError):
    pass


def _require_collection(collection: str) -> None:
    if not collection.strip():
        raise GuiScopeError("Pick a collection in the chip first.")


def _load_scope(cfg: Config, collection: str) -> tuple[Any, list[Any], str, Manifest]:
    from ..catalogue import open_library
    from ..scope import ScopeError, load_scope

    _require_collection(collection)
    backend = open_library(cfg)
    try:
        loaded = load_scope(backend, collections=[collection], library=False)
    except ScopeError as exc:
        raise GuiScopeError(str(exc)) from exc
    manifest = Manifest(cfg.manifest_path)
    return backend, loaded.items, loaded.label, manifest


def _finish_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    report: Path,
    summary: dict[str, Any],
    keys: list[str],
    options: dict[str, Any] | None = None,
) -> str:
    fp = file_fingerprint(report)
    token = commands.create_review_token(
        cfg,
        verb=verb,
        collection=collection,
        preset="oa",
        keys=keys,
        fingerprint=fp,
        command_id=cmd_id,
    )
    rec = commands.read_command(cfg, cmd_id) or {}
    rec["review_token"] = token
    rec["verb"] = verb
    rec["report_path"] = str(report)
    rec["summary"] = summary
    rec["options"] = options or {}
    rec["read_only"] = verb in READ_ONLY_REPAIR
    commands.write_command(cfg, rec)
    return token


def _command_for_token(cfg: Config, token: str) -> dict[str, Any] | None:
    review = commands.load_review(cfg, token)
    if review is None:
        return None
    cmd_id = str(review.get("command_id") or "")
    if not cmd_id:
        return None
    return commands.read_command(cfg, cmd_id)


def run_repair_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    overwrite: bool = False,
    apply_medium: bool = False,
    surgery: dict[str, bool] | None = None,
) -> None:
    if repair_preview_core_fn is not None:
        repair_preview_core_fn(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            overwrite=overwrite,
            apply_medium=apply_medium,
            surgery=surgery,
        )
        return

    backend, items, scope, manifest = _load_scope(cfg, collection)
    started = time.time()
    options = {
        "overwrite": overwrite,
        "apply_medium": apply_medium,
        "surgery": surgery or {},
    }
    keys = [it.key for it in items]

    if verb == "lint":
        from ..lint import lint_items
        from ..pipeline import make_client
        from ..runreport import write_command_report

        client = make_client(cfg)
        findings = lint_items(
            client, cfg, items, backend=backend, manifest=manifest
        )
        by_code: dict[str, int] = {}
        for finding in findings:
            by_code[finding.code] = by_code.get(finding.code, 0) + 1
        path = write_command_report(
            cfg,
            command="lint",
            scope=scope,
            summary={"findings": len(findings), "findings_by_code": by_code},
            items=[
                {
                    "itemKey": f.itemKey,
                    "title": f.title,
                    "status": f.code,
                    "reason": f.detail,
                }
                for f in findings
            ],
            flags={"gui": True},
            started=started,
        )
        if path is None:
            raise RuntimeError("lint report not written")
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=path,
            summary={"findings": len(findings), "findings_by_code": by_code},
            keys=keys,
        )
        return

    if verb == "fix-metadata":
        from ..metadata import Patch, collect_patches
        from ..pipeline import make_client

        client = make_client(cfg)
        patches = collect_patches(
            client,
            cfg,
            items,
            backend=backend,
            manifest=manifest,
            overwrite=overwrite,
        )
        report = preview_path(cfg, cmd_id, verb)
        write_preview(
            report,
            {
                "verb": verb,
                "scope": scope,
                "options": options,
                "patches": [json.loads(p.to_json()) for p in patches],
            },
        )
        field_counts: dict[str, int] = {}
        for p in patches:
            for key in p.after:
                field_counts[key] = field_counts.get(key, 0) + 1
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=report,
            summary={"patches": len(patches), "fields": field_counts},
            keys=keys,
            options=options,
        )
        return

    if verb == "dedupe":
        from ..dedupe import classify, write_pack

        groups = classify(items, phase="all")
        json_path, _md = write_pack(
            cfg.state_dir, scope, groups, phase="all", n_items=len(items)
        )
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=json_path,
            summary={
                "groups": len(groups),
                "would_merge": sum(len(g.trash) for g in groups if g.keep and g.trash),
            },
            keys=keys,
            options=options,
        )
        return

    if verb == "versions":
        import httpx

        from ..versions import classify_versions, pack_counts, resolver_for, write_pack

        client = httpx.Client(follow_redirects=True, timeout=30)
        try:
            proposals = classify_versions(
                items, resolver_for(client, cfg.email)
            )
        finally:
            client.close()
        json_path, _md = write_pack(cfg.state_dir, scope, proposals, n_items=len(items))
        counts = pack_counts(proposals, len(items))
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=json_path,
            summary=counts,
            keys=keys,
        )
        return

    if verb == "attachments":
        from ..attachments import (
            SurgeryFlags,
            mirror_pdfs_for,
            pdf_children,
            plan_actions,
            stem_filename,
            summarize,
        )

        flags = SurgeryFlags(
            fix_broken=False,
            merge_files=False,
            rename=False,
            link=False,
        )
        children = []
        mirrors: dict[str, list] = {}
        stems: dict[str, str] = {}
        for item in items:
            try:
                raw = backend.children(item.key) or []
            except LibraryError:
                continue
            present = {
                str(ch.get("key") or (ch.get("data") or {}).get("key") or ""): True
                for ch in raw
                if isinstance(ch, dict)
            }
            kids = pdf_children(item.key, raw, present=present)
            children.extend(kids)
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
        report = preview_path(cfg, cmd_id, verb)
        write_preview(
            report,
            {
                "verb": verb,
                "scope": scope,
                "options": options,
                "findings": [asdict(f) for f in scan.findings],
                "actions": [asdict(a) for a in scan.actions],
                "refusals": list(scan.refusals),
            },
        )
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=report,
            summary={"findings": summarize(scan.findings)},
            keys=keys,
            options=options,
        )
        return

    if verb == "ocr":
        from ..ocr import ocr_items

        batch = ocr_items(cfg, items, manifest, backend, apply=False)
        from ..runreport import write_command_report

        path = write_command_report(
            cfg,
            command="ocr",
            scope=scope,
            summary={
                "would_ocr": batch.would,
                "skipped": batch.skipped,
                "failed": batch.failed,
            },
            items=[asdict(r) for r in batch.rows],
            flags={"gui": True, "apply": False},
            started=started,
        )
        if path is None:
            raise RuntimeError("ocr report not written")
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=path,
            summary={
                "would_ocr": batch.would,
                "skipped": batch.skipped,
                "failed": batch.failed,
            },
            keys=keys,
        )
        return

    raise ValueError(f"unknown repair verb {verb!r}")


def run_repair_apply(
    cfg: Config,
    *,
    token: str,
    overwrite: bool = False,
    apply_medium: bool = False,
    surgery: dict[str, bool] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    if repair_apply_core_fn is not None:
        out = repair_apply_core_fn(
            cfg,
            token=token,
            overwrite=overwrite,
            apply_medium=apply_medium,
            surgery=surgery,
        )
        ok = bool(out.get("ok", True))
        return ok, str(out.get("msg") or ""), dict(out.get("summary") or {})

    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token", {}
    verb = str(review.get("verb") or "")
    if verb in READ_ONLY_REPAIR:
        return False, "lint is read-only", {}
    cmd = _command_for_token(cfg, token)
    if cmd is None:
        return False, "unknown token", {}
    report = Path(str(cmd.get("report_path") or ""))
    if not report.is_file():
        return False, "preview file missing", {}
    fp = file_fingerprint(report)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg, {}

    stored = dict(cmd.get("options") or {})
    surg = dict(stored.get("surgery") or {})

    collection = str(review.get("collection") or "")
    backend, items, scope, manifest = _load_scope(cfg, collection)
    summary: dict[str, Any] = {}

    if verb == "fix-metadata":
        from ..metadata import Patch, apply_patches

        body = read_preview(report) or {}
        overwrite = bool(stored.get("overwrite"))
        raw_patches = body.get("patches") or []
        patches = [Patch(**row) for row in raw_patches]
        if not backend.supports_write():
            return False, "write API not available", {}
        applied, errors = apply_patches(backend, patches)
        backend.flush_writes()
        summary = {"applied": applied, "errors": len(errors)}
        return True, "", summary

    if verb == "dedupe":
        from ..dedupe import DedupeGroup, actionable_groups, apply_merge

        payload = json.loads(report.read_text(encoding="utf-8"))
        groups = [DedupeGroup(**g) for g in payload.get("groups") or []]
        apply_medium = bool(stored.get("apply_medium"))
        if not backend.supports_write():
            return False, "write API not available", {}
        merged, errors = apply_merge(
            backend,
            groups,
            apply_medium=apply_medium,
            audit_path=cfg.dedupe_applied_path,
            scope=scope,
            pack=report,
        )
        backend.flush_writes()
        summary = {"merged": merged, "errors": len(errors)}
        return True, "", summary

    if verb == "versions":
        import httpx

        from ..versions import VersionProposal, apply_versions, http_fetch_published

        payload = json.loads(report.read_text(encoding="utf-8"))
        proposals = [
            VersionProposal(**row) for row in payload.get("proposals") or []
        ]
        if not backend.supports_write():
            return False, "write API not available", {}
        client = httpx.Client(follow_redirects=True, timeout=30)
        try:
            applied, errors = apply_versions(
                backend,
                proposals,
                fetch_published=http_fetch_published(client, cfg.email),
                audit_path=cfg.versions_applied_path,
                scope=scope,
                pack=report,
            )
        finally:
            client.close()
        backend.flush_writes()
        summary = {"applied": applied, "errors": len(errors)}
        return True, "", summary

    if verb == "attachments":
        from ..attachments import (
            SurgeryFlags,
            apply_actions,
            mirror_pdfs_for,
            pdf_children,
            plan_actions,
            stem_filename,
        )

        if not surg:
            return False, "no surgery flags were set at preview", {}
        flags = SurgeryFlags(
            fix_broken=bool(surg.get("fix_broken")),
            merge_files=bool(surg.get("merge_files")),
            rename=bool(surg.get("rename")),
            link=bool(surg.get("link")),
        )
        if not flags.any:
            return False, "no surgery flags selected", {}
        children = []
        mirrors: dict[str, list] = {}
        stems: dict[str, str] = {}
        for item in items:
            try:
                raw = backend.children(item.key) or []
            except LibraryError:
                continue
            present = {
                str(ch.get("key") or (ch.get("data") or {}).get("key") or ""): True
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
        if not backend.supports_write():
            return False, "write API not available", {}
        applied, errors = apply_actions(backend, scan.actions, out_dir=cfg.out_dir)
        backend.flush_writes()
        summary = {"applied": applied, "errors": len(errors)}
        return True, "", summary

    if verb == "ocr":
        from ..ocr import ocr_items

        batch = ocr_items(cfg, items, manifest, backend, apply=True, attach=False)
        summary = {
            "ocr_applied": batch.ocr,
            "failed": batch.failed,
            "skipped": batch.skipped,
        }
        return True, "", summary

    return False, f"unknown verb {verb!r}", {}


def run_mirror_preview(
    cfg: Config,
    cmd_id: str,
    *,
    verb: str,
    collection: str,
    pdfs: str = "lazy",
    accept_gone: bool = False,
) -> None:
    if mirror_preview_core_fn is not None:
        mirror_preview_core_fn(
            cfg, cmd_id, verb=verb, collection=collection, pdfs=pdfs, accept_gone=accept_gone
        )
        return

    options = {"pdfs": pdfs, "accept_gone": accept_gone}
    report = preview_path(cfg, cmd_id, verb)

    if verb == "sync":
        from ..catalogue import open_library
        from ..sync import run_sync

        backend = open_library(cfg)
        stats = run_sync(cfg, backend, dry_run=True, pdfs=pdfs, accept_gone=accept_gone)
        write_preview(
            report,
            {
                "verb": verb,
                "options": options,
                "stats": asdict(stats),
            },
        )
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=report,
            summary={
                "written": stats.written,
                "gone": stats.gone,
                "pdf_exports": stats.pdf_exports,
            },
            keys=[verb],
            options=options,
        )
        return

    if verb == "snapshot":
        from ..snapshot import run_snapshot

        backend, items, scope, _manifest = _load_scope(cfg, collection)
        stats = run_snapshot(
            cfg, backend, items, pdfs=pdfs, dry_run=True, manifest=None
        )
        write_preview(
            report,
            {"verb": verb, "scope": scope, "options": options, "stats": asdict(stats)},
        )
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=report,
            summary={"records": stats.records, "pdf_exports": stats.pdf_exports},
            keys=[it.key for it in items],
            options=options,
        )
        return

    if verb == "restore":
        from ..restore import dedupe_restore_records, iter_records, plan_restore

        backend, items, scope, _manifest = _load_scope(cfg, collection)
        paths = iter_records(cfg.out_dir, [collection] if collection else None)
        records: list[tuple[Path, dict[str, Any]]] = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(data, dict):
                records.append((path, data))
        records = dedupe_restore_records(records)
        plan = plan_restore(records, items, note_tags_for={})
        write_preview(
            report,
            {
                "verb": verb,
                "scope": scope,
                "options": options,
                "actions": [asdict(a) for a in plan.actions],
            },
        )
        creates = sum(1 for a in plan.actions if a.kind == "create_item")
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=report,
            summary={"would_create": creates, "actions": len(plan.actions)},
            keys=[verb],
            options=options,
        )
        return

    if verb == "cache clean":
        from ..sync import clean_pdf_cache

        report_data = clean_pdf_cache(cfg, apply=False)
        write_preview(
            report,
            {
                "verb": verb,
                "options": options,
                "report": report_data,
                "removable_paths": report_data.get("paths") or [],
            },
        )
        _finish_preview(
            cfg,
            cmd_id,
            verb=verb,
            collection=collection,
            report=report,
            summary={
                "removable": report_data.get("removable", 0),
                "kept": report_data.get("kept", 0),
            },
            keys=[verb],
            options=options,
        )
        return

    raise ValueError(f"unknown mirror verb {verb!r}")


def run_mirror_apply(
    cfg: Config,
    *,
    token: str,
    collection: str,
) -> tuple[bool, str, dict[str, Any]]:
    if mirror_apply_core_fn is not None:
        out = mirror_apply_core_fn(cfg, token=token, collection=collection)
        ok = bool(out.get("ok", True))
        return ok, str(out.get("msg") or ""), dict(out.get("summary") or {})

    review = commands.load_review(cfg, token)
    if review is None:
        return False, "unknown token", {}
    cmd = _command_for_token(cfg, token)
    if cmd is None:
        return False, "unknown token", {}
    report = Path(str(cmd.get("report_path") or ""))
    if not report.is_file():
        return False, "preview file missing", {}
    fp = file_fingerprint(report)
    ok, msg = commands.consume_review(cfg, token, fingerprint=fp, keys=None)
    if not ok:
        return False, msg, {}

    verb = str(review.get("verb") or "")
    options = dict(cmd.get("options") or {})
    body = read_preview(report) or {}
    summary: dict[str, Any] = {}

    if verb == "sync":
        from ..catalogue import open_library
        from ..sync import run_sync

        backend = open_library(cfg)
        stats = run_sync(
            cfg,
            backend,
            dry_run=False,
            pdfs=str(options.get("pdfs") or "lazy"),
            accept_gone=bool(options.get("accept_gone")),
        )
        backend.flush_writes()
        summary = {"written": stats.written, "gone": stats.gone}
        return True, "", summary

    if verb == "snapshot":
        from ..snapshot import run_snapshot

        backend, items, _scope, _manifest = _load_scope(cfg, collection)
        stats = run_snapshot(
            cfg,
            backend,
            items,
            pdfs=str(options.get("pdfs") or "lazy"),
            dry_run=False,
            manifest=None,
        )
        backend.flush_writes()
        summary = {"records": stats.records, "pdf_exports": stats.pdf_exports}
        return True, "", summary

    if verb == "restore":
        from ..restore import RestoreAction, RestorePlan, apply_restore

        backend, items, _scope, _manifest = _load_scope(cfg, collection)
        actions = [RestoreAction(**row) for row in body.get("actions") or []]
        plan = RestorePlan(actions=actions)
        done = apply_restore(plan, backend, backend)
        backend.flush_writes()
        summary = done
        return True, "", summary

    if verb == "cache clean":
        from ..sync import clean_pdf_cache

        preview_report = body.get("report") or {}
        removable = list(preview_report.get("removable_paths") or [])
        result = clean_pdf_cache(cfg, apply=True)
        summary = {"removed": result.get("removed", 0), "previewed": len(removable)}
        return True, "", summary

    return False, f"unknown verb {verb!r}", {}
