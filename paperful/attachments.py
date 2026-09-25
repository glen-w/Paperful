"""Attachment hygiene. Classification is pure; Zotero writes happen only in ``apply_actions``."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import item_dirname, item_filename
from .zot import Item, is_pdf_attachment

STORED_MODES = frozenset({"imported_file", "imported_url"})


@dataclass(frozen=True)
class PdfChild:
    key: str
    parent_key: str
    filename: str
    link_mode: str
    md5: str | None
    path: str | None
    bytes_present: bool


@dataclass(frozen=True)
class MirrorPdf:
    path: str
    md5: str
    filename: str


@dataclass(frozen=True)
class Finding:
    kind: str
    parent_key: str
    attachment_key: str | None = None
    detail: str = ""
    md5: str | None = None


@dataclass(frozen=True)
class Action:
    op: str
    parent_key: str
    attachment_key: str | None = None
    source_path: str | None = None
    filename: str | None = None
    trash_keys: tuple[str, ...] = ()


@dataclass
class SurgeryFlags:
    fix_broken: bool = False
    merge_files: bool = False
    rename: bool = False
    link: bool = False

    @property
    def any(self) -> bool:
        return self.fix_broken or self.merge_files or self.rename or self.link


@dataclass
class Scan:
    findings: list[Finding] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)


def inside_out(out_dir: Path, path: str | None) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(out_dir.resolve())
    except (ValueError, OSError):
        return False
    return True


def apply_refusal(*, manager: str, library_type: str, link: bool) -> str | None:
    """Why ``--apply`` must stop. ``None`` means the write is allowed.

    Mendeley can upload and delete cloud files. EndNote is report-only: paperful
    does not edit the library database. ``--link`` is a Zotero personal library.
    """
    if link and manager != "zotero":
        return (
            "Stored-to-linked is a Zotero personal library only. "
            "Mendeley files stay in Mendeley cloud. EndNote files stay under "
            "Library.Data/PDF. The report was written; nothing was linked."
        )
    if link and library_type != "user":
        return "Stored-to-linked is refused for a group library. Groups cannot use linked files."
    if manager == "endnote":
        return (
            "EndNote attachment changes are not written into the library. "
            "The report lists missing files, duplicate PDFs, and filename drift. "
            "Nothing was staged."
        )
    if manager not in {"zotero", "mendeley"}:
        return "Attachment surgery is not available for this manager. The report was written."
    return None


def pdf_children(
    parent_key: str,
    raw_children: list[dict[str, Any]],
    *,
    present: dict[str, bool],
) -> list[PdfChild]:
    out: list[PdfChild] = []
    for ch in raw_children:
        data = ch.get("data") or {}
        if data.get("itemType") != "attachment":
            continue
        if not is_pdf_attachment(data) and data.get("contentType") != "application/pdf":
            continue
        if data.get("linkMode") == "linked_url":
            continue
        key = str(ch.get("key") or data.get("key") or "")
        if not key:
            continue
        filename = str(data.get("filename") or data.get("title") or "")
        out.append(
            PdfChild(
                key=key,
                parent_key=parent_key,
                filename=filename,
                link_mode=str(data.get("linkMode") or ""),
                md5=(str(data["md5"]) if data.get("md5") else None),
                path=(str(data["path"]) if data.get("path") else None),
                bytes_present=bool(present.get(key)),
            )
        )
    return out


def classify_parent(
    parent_key: str,
    children: list[PdfChild],
    mirror: list[MirrorPdf],
    stem_name: str,
) -> list[Finding]:
    """Findings for one parent. No filesystem or network access."""
    findings: list[Finding] = []
    by_md5: dict[str, list[PdfChild]] = {}
    for child in children:
        if child.md5:
            by_md5.setdefault(child.md5, []).append(child)
        broken = _broken_kind(child)
        mirror_hit = _mirror_for(child, mirror)
        if broken and mirror_hit is None:
            findings.append(
                Finding(
                    "unrepairable",
                    parent_key,
                    child.key,
                    "No matching PDF under out/. paperful run can fetch one.",
                    child.md5,
                )
            )
        elif broken:
            findings.append(
                Finding(broken, parent_key, child.key, _broken_detail(child), child.md5)
            )
        else:
            findings.append(
                Finding("ok", parent_key, child.key, child.filename, child.md5)
            )
        if (
            child.bytes_present
            and child.link_mode == "imported_file"
            and mirror_hit is not None
        ):
            findings.append(
                Finding(
                    "stored",
                    parent_key,
                    child.key,
                    "Stored file also exists under out/.",
                    child.md5,
                )
            )
        if child.filename and stem_name and child.filename != stem_name:
            findings.append(
                Finding(
                    "rename_drift",
                    parent_key,
                    child.key,
                    f"{child.filename} → {stem_name}",
                    child.md5,
                )
            )
    for digest, group in by_md5.items():
        if len(group) < 2:
            continue
        findings.append(
            Finding(
                "duplicate_file",
                parent_key,
                group[0].key,
                f"{len(group)} PDF children share MD5 {digest}",
                digest,
            )
        )
    return findings


def cross_parent_findings(children: list[PdfChild]) -> list[Finding]:
    """Same MD5 on more than one parent. Points at ``dedupe``; no file merge."""
    owners: dict[str, set[str]] = {}
    for child in children:
        if child.md5:
            owners.setdefault(child.md5, set()).add(child.parent_key)
    findings: list[Finding] = []
    for digest, parents in sorted(owners.items()):
        if len(parents) < 2:
            continue
        findings.append(
            Finding(
                "cross_parent",
                sorted(parents)[0],
                None,
                (
                    f"MD5 {digest} is on {len(parents)} parents. "
                    "paperful dedupe merges parents; this command does not."
                ),
                digest,
            )
        )
    return findings


def plan_actions(
    children: list[PdfChild],
    mirror_by_parent: dict[str, list[MirrorPdf]],
    stems: dict[str, str],
    flags: SurgeryFlags,
    *,
    out_dir: Path,
    library_type: str = "user",
) -> Scan:
    """Surgery list. Does not touch disk or Zotero."""
    scan = Scan()
    by_parent: dict[str, list[PdfChild]] = {}
    for child in children:
        by_parent.setdefault(child.parent_key, []).append(child)
    for parent, kids in by_parent.items():
        scan.findings.extend(
            classify_parent(
                parent, kids, mirror_by_parent.get(parent, []), stems.get(parent, "")
            )
        )
    scan.findings.extend(cross_parent_findings(children))

    link = flags.link
    if link and library_type != "user":
        scan.refusals.append(
            "Stored-to-linked is refused for a group library. Groups cannot use linked files."
        )
        link = False

    trash: set[str] = set()
    for parent, kids in by_parent.items():
        mirror = [
            m for m in mirror_by_parent.get(parent, []) if inside_out(out_dir, m.path)
        ]
        groups = _md5_groups(kids)
        if flags.fix_broken:
            for child in kids:
                if not _broken_kind(child):
                    continue
                hit = _mirror_for(child, mirror)
                if hit is None:
                    continue
                siblings = [
                    other
                    for other in groups.get(child.md5 or "", [])
                    if other.key != child.key and other.bytes_present
                ]
                if siblings:
                    continue
                if child.link_mode == "linked_file":
                    scan.actions.append(
                        Action(
                            "relink",
                            parent,
                            child.key,
                            source_path=hit.path,
                            filename=Path(hit.path).name,
                        )
                    )
                else:
                    scan.actions.append(
                        Action(
                            "refill",
                            parent,
                            child.key,
                            source_path=hit.path,
                            filename=Path(hit.path).name,
                            trash_keys=(child.key,),
                        )
                    )
                    trash.add(child.key)
        if flags.merge_files:
            for group in groups.values():
                if len(group) < 2:
                    continue
                keeper = _keeper(group, prefer_linked=link)
                for child in group:
                    if child.key == keeper.key or child.key in trash:
                        continue
                    scan.actions.append(Action("trash", parent, child.key))
                    trash.add(child.key)

        stem = stems.get(parent) or ""
        remaining = [c for c in kids if c.key not in trash]
        renamed_sources: set[str] = set()
        for child in remaining:
            hit = _mirror_for(child, mirror)
            source = hit.path if hit is not None else None
            final = source
            if (
                flags.rename
                and stem
                and source
                and Path(source).name != stem
                and source not in renamed_sources
            ):
                scan.actions.append(
                    Action("rename_file", parent, source_path=source, filename=stem)
                )
                renamed_sources.add(source)
                final = str(Path(source).with_name(stem))
            if flags.rename and not link:
                if child.filename == stem or not stem:
                    continue
                if child.link_mode == "linked_file":
                    if not (child.bytes_present and inside_out(out_dir, child.path)):
                        scan.refusals.append(
                            f"{child.key}: linked file is outside out/ and was not renamed."
                        )
                        continue
                    scan.actions.append(
                        Action(
                            "rename_linked",
                            parent,
                            child.key,
                            source_path=child.path,
                            filename=stem,
                        )
                    )
                elif (
                    child.link_mode in STORED_MODES
                    and final
                    and inside_out(out_dir, final)
                ):
                    scan.actions.append(
                        Action(
                            "rename_upload",
                            parent,
                            child.key,
                            source_path=final,
                            filename=stem,
                            trash_keys=(child.key,),
                        )
                    )
                    trash.add(child.key)
            elif link and child.link_mode in STORED_MODES:
                if not final or not inside_out(out_dir, final):
                    scan.refusals.append(
                        f"{child.key}: no matching PDF under out/ to link. "
                        "The stored file was left in place."
                    )
                    continue
                scan.actions.append(
                    Action(
                        "link",
                        parent,
                        child.key,
                        source_path=final,
                        filename=Path(final).name,
                        trash_keys=(child.key,),
                    )
                )
    return scan


def apply_actions(
    backend: Any, actions: list[Action], *, out_dir: Path
) -> tuple[int, list[str]]:
    """Run a plan. Refuses paths outside ``out_dir``. Does not delete mirror bytes."""
    done = 0
    errors: list[str] = []
    for action in actions:
        try:
            _apply_one(backend, action, out_dir)
        except Exception as exc:
            errors.append(
                f"{action.op} {action.attachment_key or action.parent_key}: {exc}"
            )
            continue
        done += 1
    return done, errors


def _trash_attachment(backend: Any, key: str | None) -> None:
    if not key:
        raise RuntimeError("missing attachment key")
    fn = getattr(backend, "trash_attachment", None)
    if callable(fn):
        fn(key)
        return
    backend.trash_item(key)


def _apply_one(backend: Any, action: Action, out_dir: Path) -> None:
    if action.op == "trash":
        _trash_attachment(backend, action.attachment_key)
        return
    if action.op == "rename_file":
        _rename_inside(out_dir, action.source_path or "", action.filename or "")
        return
    if action.op == "relink":
        path = _require_inside(out_dir, action.source_path)
        backend.relink_file(action.attachment_key, path)
        return
    if action.op == "rename_linked":
        dest = _rename_inside(out_dir, action.source_path or "", action.filename or "")
        backend.relink_file(action.attachment_key, dest)
        return
    if action.op == "refill":
        path = _require_inside(out_dir, action.source_path)
        result = backend.attach(action.parent_key, path, title="Full Text PDF")
        if not result.ok:
            raise RuntimeError(result.reason or "attach failed")
        for key in action.trash_keys:
            _trash_attachment(backend, key)
        return
    if action.op == "rename_upload":
        path = _require_inside(out_dir, action.source_path)
        result = backend.attach(action.parent_key, path, title="Full Text PDF")
        if not result.ok:
            raise RuntimeError(result.reason or "attach failed")
        for key in action.trash_keys:
            _trash_attachment(backend, key)
        return
    if action.op == "link":
        path = _require_inside(out_dir, action.source_path)
        if not path.is_file():
            raise RuntimeError(f"file missing: {path}")
        backend.create_linked_file(action.parent_key, path)
        for key in action.trash_keys:
            _trash_attachment(backend, key)
        return
    raise RuntimeError(f"unknown action {action.op}")


def _require_inside(out_dir: Path, path: str | None) -> Path:
    if not path or not inside_out(out_dir, path):
        raise RuntimeError("refusing a path outside out/")
    return Path(path)


def _rename_inside(out_dir: Path, source: str, filename: str) -> Path:
    src = _require_inside(out_dir, source)
    if not filename or "/" in filename or filename in {".", ".."}:
        raise RuntimeError("refusing a filename that leaves the item folder")
    dest = _require_inside(out_dir, str(src.with_name(filename)))
    if dest.exists() and dest.resolve() != src.resolve():
        if _md5(dest) != _md5(src):
            raise RuntimeError(f"{dest.name} already exists with different bytes")
        return dest
    if dest.resolve() != src.resolve():
        src.rename(dest)
    return dest


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.kind] = counts.get(finding.kind, 0) + 1
    return counts


def mirror_pdfs_for(out_dir: Path, item: Item) -> list[MirrorPdf]:
    """PDFs already in this item's mirror folders."""
    found: list[MirrorPdf] = []
    seen: set[str] = set()
    paths = item.collection_paths or ["_uncollected"]
    for folder in (out_dir / p / item_dirname(item) for p in paths):
        if not folder.is_dir():
            continue
        for pdf in sorted(folder.glob("*.pdf")):
            if not pdf.is_file():
                continue
            key = str(pdf.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(MirrorPdf(path=key, md5=_md5(pdf), filename=pdf.name))
    return found


def stem_filename(item: Item) -> str:
    return item_filename(item)


def _broken_kind(child: PdfChild) -> str | None:
    if child.bytes_present:
        return None
    if child.link_mode == "linked_file":
        return "broken_link"
    if child.link_mode in STORED_MODES:
        return "ghost"
    return None


def _broken_detail(child: PdfChild) -> str:
    if child.link_mode == "linked_file":
        return f"Linked path is missing: {child.path or child.filename}"
    return "Stored attachment has no local bytes."


def _mirror_for(child: PdfChild, mirror: list[MirrorPdf]) -> MirrorPdf | None:
    if not child.md5:
        return None
    for pdf in mirror:
        if pdf.md5 == child.md5:
            return pdf
    return None


def _md5_groups(children: list[PdfChild]) -> dict[str, list[PdfChild]]:
    groups: dict[str, list[PdfChild]] = {}
    for child in children:
        if child.md5:
            groups.setdefault(child.md5, []).append(child)
    return groups


def _keeper(group: list[PdfChild], *, prefer_linked: bool) -> PdfChild:
    present = [c for c in group if c.bytes_present] or list(group)
    if prefer_linked:
        linked = [c for c in present if c.link_mode == "linked_file"]
        if linked:
            return linked[0]
    stored = [c for c in present if c.link_mode in STORED_MODES and c.bytes_present]
    if stored:
        return stored[0]
    return present[0]


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
