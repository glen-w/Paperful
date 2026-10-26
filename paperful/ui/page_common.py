"""Shared workbench row helpers (no HTML)."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..store import Manifest, STATUS_ATTACHED, STATUS_OK


def _has_summary(cfg: Config, key: str) -> bool:
    return (cfg.summaries_dir / f"{key}.html").is_file()


def _item_row_base(cfg: Config, item: Any) -> dict[str, Any]:
    return {
        "key": item.key,
        "title": item.title or "",
        "doi": item.doi or "",
        "year": getattr(item, "year", None),
        "has_summary": _has_summary(cfg, item.key),
    }


def library_has_attached_pdf(cfg: Config) -> bool:
    """True after at least one PDF has been written back to the library."""
    from ..store import STATUS_ATTACHED, Manifest

    manifest = Manifest(cfg.manifest_path)
    return any(r.status == STATUS_ATTACHED for r in manifest.records.values())


def scope_fingerprint(items: list[Any], manifest: Manifest) -> str:
    import hashlib

    records = getattr(manifest, "records", None) or {}
    lines: list[str] = []
    for item in sorted(items, key=lambda i: i.key):
        rec = records.get(item.key) if hasattr(records, "get") else None
        status = rec.status if rec else "none"
        doi = item.doi or ""
        lines.append(f"{item.key}|{doi}|{status}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest


def nest_collection_rows(
    rows: list[dict[str, Any]], *, active: str = ""
) -> list[dict[str, Any]]:
    """Nest flat ``path`` rows so Library can render ``<details>`` groups.

    ``item_count`` is used instead of ``items`` so Jinja does not shadow the
    dict ``.items`` method.
    """
    by_path: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        name = str(row.get("name") or "").strip() or path.rsplit("/", 1)[-1]
        by_path[path] = {
            "path": path,
            "name": name,
            "key": str(row.get("key") or ""),
            "item_count": int(row.get("items") or 0),
            "missing_pdf": int(row.get("missing_pdf") or 0),
            "children": [],
            "open": False,
        }
    for path in list(by_path):
        parts = path.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            if parent in by_path:
                continue
            by_path[parent] = {
                "path": parent,
                "name": parts[i - 1],
                "key": "",
                "item_count": 0,
                "missing_pdf": 0,
                "children": [],
                "open": False,
            }
    roots: list[dict[str, Any]] = []
    for path, node in sorted(by_path.items(), key=lambda kv: kv[0].lower()):
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent in by_path:
            by_path[parent]["children"].append(node)
        else:
            roots.append(node)

    active = (active or "").strip()

    def _finish(nodes: list[dict[str, Any]]) -> None:
        nodes.sort(key=lambda n: str(n["name"]).lower())
        for node in nodes:
            path = str(node["path"])
            node["open"] = bool(
                active and (active == path or active.startswith(path + "/"))
            )
            _finish(node["children"])

    _finish(roots)
    return roots


def _library_item_sort_key(item: Any) -> tuple[int, str]:
    return (item.year or 9999, (item.title or "").lower())


def library_page_size_options(cfg: Config) -> tuple[int, ...]:
    from ..config import normalize_ui_library_page_sizes

    _, sizes = normalize_ui_library_page_sizes(
        cfg.ui_library_page_size, cfg.ui_library_page_sizes
    )
    return sizes


def coerce_library_per_page(
    value: int, cfg: Config, *, allowed: tuple[int, ...] | None = None
) -> int:
    options = allowed or library_page_size_options(cfg)
    n = max(1, int(value))
    if n in options:
        return n
    return (
        cfg.ui_library_page_size if cfg.ui_library_page_size in options else options[0]
    )


def library_per_page_from_request(request: Any, cfg: Config) -> int:
    raw = request.query_params.get("per_page")
    if raw is not None:
        text = str(raw).strip()
        if text.isdigit():
            return coerce_library_per_page(int(text), cfg)
    from .prefs import COOKIE_LIBRARY_PER_PAGE

    cookie = (request.cookies.get(COOKIE_LIBRARY_PER_PAGE) or "").strip()
    if cookie.isdigit():
        return coerce_library_per_page(int(cookie), cfg)
    return coerce_library_per_page(cfg.ui_library_page_size, cfg)


def library_page_from_request(request: Any) -> int:
    raw = request.query_params.get("page")
    if raw is not None and str(raw).strip().isdigit():
        return max(1, int(str(raw).strip()))
    return 1


def paginate_rows(
    rows: list[Any], *, page: int, per_page: int
) -> tuple[list[Any], int, int, int]:
    """Return one page of ``rows`` plus total, clamped page, and page count."""
    total = len(rows)
    per_page = max(1, int(per_page))
    page_count = max(1, (total + per_page - 1) // per_page) if total else 1
    page = min(max(1, int(page)), page_count)
    start = (page - 1) * per_page
    return rows[start : start + per_page], total, page, page_count


def pagination_meta(
    *,
    page: int,
    per_page: int,
    page_count: int,
    total: int,
    page_sizes: tuple[int, ...],
) -> dict[str, Any]:
    range_start = (page - 1) * per_page + 1 if total else 0
    range_end = min(page * per_page, total)
    return {
        "page": page,
        "per_page": per_page,
        "page_count": page_count,
        "total": total,
        "range_start": range_start,
        "range_end": range_end,
        "page_sizes": page_sizes,
        "prev_url": "",
        "next_url": "",
    }


def library_item_rows(
    cfg: Config, items: list[Any], manifest: Manifest
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(items, key=_library_item_sort_key):
        rec = manifest.records.get(item.key)
        base = _item_row_base(cfg, item)
        has_pdf = bool(
            item.has_pdf
            or (rec is not None and rec.status in {STATUS_OK, STATUS_ATTACHED})
        )
        rows.append({**base, "has_pdf": has_pdf})
    return rows


def library_items_page(
    cfg: Config,
    items: list[Any],
    manifest: Manifest,
    *,
    page: int,
    per_page: int,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return rows for one page plus total count and clamped page index."""
    sorted_items = sorted(items, key=_library_item_sort_key)
    chunk, total, page, page_count = paginate_rows(
        sorted_items, page=page, per_page=per_page
    )
    rows = library_item_rows(cfg, chunk, manifest)
    return rows, total, page, page_count


REPAIR_VERBS = (
    "lint",
    "screen",
    "fix-metadata",
    "dedupe",
    "versions",
    "attachments",
    "ocr",
)

MIRROR_VERBS = ("sync", "snapshot", "restore", "cache clean")


def repair_queues(cfg: Config) -> list[dict[str, Any]]:
    """On-disk repair packs/reports for the Repair page."""
    rows: list[dict[str, Any]] = []
    mapping = (
        ("lint", cfg.state_dir / "runs", "*-lint.json"),
        ("screen", cfg.state_dir / "runs", "*-screen.json"),
        ("fix-metadata", cfg.state_dir, "metadata-patches.jsonl"),
        ("dedupe", cfg.state_dir / "dedupe-packs", "*.json"),
        ("versions", cfg.state_dir / "version-packs", "*.json"),
        ("attachments", cfg.state_dir / "runs", "*-attachments.json"),
        ("ocr", cfg.state_dir / "runs", "*-ocr.json"),
    )
    for verb, folder, pattern in mapping:
        names: list[str] = []
        if folder.is_file() and pattern in folder.name:
            names = [folder.name]
        elif folder.is_dir():
            names = [p.name for p in sorted(folder.glob(pattern)) if p.is_file()]
        rows.append({"verb": verb, "files": names})
    return rows


DEST_OPTIONS = ("disk", "zotero", "both")

SYNTHESIZE_SKIP_MESSAGES = {
    "no_summaries": "No summaries in this scope. Summarize first, then write the report.",
    "current": "Report is already up to date. Tick Force to rewrite it.",
}


def command_by_id(cfg: Config, cmd_id: str) -> dict[str, Any] | None:
    from . import commands

    if not cmd_id:
        return None
    return commands.read_command(cfg, cmd_id)


def job_view(rec: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a GUI command record for templates (status, error, result)."""
    if not rec:
        return {}
    result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
    extra_args = rec.get("args") if isinstance(rec.get("args"), dict) else {}
    out = {
        "id": rec.get("id") or "",
        "verb": rec.get("verb") or "",
        "status": rec.get("status") or "",
        "error": rec.get("error") or "",
        "args": extra_args,
        **result,
    }
    out["detail"] = rec.get("detail") or out.get("detail") or ""
    skipped = str(out.get("skipped") or "")
    out["skip_plain"] = SYNTHESIZE_SKIP_MESSAGES.get(skipped, "")
    return out


def last_job_result(cfg: Config, verb: str, run: str = "") -> dict[str, Any]:
    from . import commands

    rec = command_by_id(cfg, (run or "").strip()) if run else None
    if rec and rec.get("verb") == verb:
        return job_view(rec)
    for rec in commands.list_commands(cfg, limit=50):
        if rec.get("verb") != verb:
            continue
        return job_view(rec)
    return {}


def safe_child(root: Any, *parts: str) -> Any:
    """Return a file under ``root``, or None if the name is unsafe or missing."""
    from pathlib import Path

    dest = Path(root)
    if not parts:
        return None
    for part in parts:
        if not part or any(ch in part for ch in "/\\") or part in {".", ".."}:
            return None
    try:
        base = dest.resolve()
        path = base.joinpath(*parts).resolve()
        path.relative_to(base)
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def dest_options() -> tuple[str, ...]:
    return DEST_OPTIONS


def dest_for_form(cfg_dest: str, collection: str) -> str:
    """Zotero dest needs a collection; fall back to disk so Write report can run."""
    from ..config import wants_zotero

    dest = (cfg_dest or "disk").strip()
    if dest not in DEST_OPTIONS:
        dest = "disk"
    if wants_zotero(dest) and not (collection or "").strip():
        return "disk"
    return dest


def queue_fingerprint(cfg: Config, verb: str) -> str:
    import hashlib

    lines: list[str] = []
    for row in repair_queues(cfg):
        if row["verb"] != verb:
            continue
        for name in row["files"]:
            lines.append(f"{verb}|{name}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
