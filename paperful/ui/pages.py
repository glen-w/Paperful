"""Row builders for workbench pages (no HTML)."""

from __future__ import annotations

import json
from typing import Any

from ..config import Config
from ..miss_surface import honesty_row_for_item, miss_surface_plain, project_miss_surface
from ..store import Manifest, STATUS_ATTACHED, STATUS_OK
from .verify import file_verification, reason_plain, verification_plain


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


def wanted_rows(
    cfg: Config,
    items: list[Any],
    manifest: Manifest,
) -> dict[str, Any]:
    have: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for item in items:
        rec = manifest.records.get(item.key)
        base = _item_row_base(cfg, item)
        if item.has_pdf or (
            rec is not None and rec.status in {STATUS_OK, STATUS_ATTACHED}
        ):
            ver = file_verification(rec, item_doi=item.doi)
            row = {
                **base,
                **ver,
                "verify_plain": verification_plain(ver["state"]),
                "verify_tip": reason_plain(ver.get("reason") or ""),
                "ticked": ver["state"] == "doi_match",
            }
            state = ver["state"]
            if state == "doi_match":
                have.append(row)
            elif state == "missing":
                missing.append(
                    {
                        **row,
                        "miss_surface": "missing",
                        "miss_plain": row["verify_plain"],
                        "miss_detail": row["verify_tip"],
                    }
                )
            else:
                held.append(row)
            continue
        honesty = honesty_row_for_item(cfg, item, rec)
        code = str(honesty.get("miss_surface") or "")
        if code == "import_ok":
            continue
        plain = str(honesty.get("miss_plain") or "")
        if not plain and not code:
            code = project_miss_surface(
                doi=item.doi,
                arxiv_id=getattr(item, "arxiv_id", None),
                url=getattr(item, "url", None),
                has_pdf=False,
                status=str(getattr(rec, "status", "") or "") if rec else "",
                attempts=list(getattr(rec, "attempts", None) or []) if rec else [],
                source=getattr(rec, "source", None) if rec else None,
            )
            if code == "import_ok":
                continue
            plain = miss_surface_plain(code) if code else "No stored PDF"
        if not plain:
            continue
        missing.append(
            {
                **base,
                "miss_surface": code,
                "miss_plain": plain,
                "miss_detail": str(honesty.get("miss_detail") or ""),
            }
        )

    return {
        "have": have,
        "held": held,
        "missing": missing,
        "counts": {
            "have": len(have),
            "held": len(held),
            "missing": len(missing),
        },
    }


_WANTED_TABS = ("missing", "held", "have")


def resolve_wanted_tab(tab: str | None, counts: dict[str, int]) -> str:
    """Pick a Wanted tab; default to the first non-empty bucket."""
    if tab in _WANTED_TABS:
        return tab
    for name in _WANTED_TABS:
        if counts.get(name, 0) > 0:
            return name
    return "missing"


def scope_fingerprint(items: list[Any], manifest: Manifest) -> str:
    import hashlib

    lines: list[str] = []
    for item in sorted(items, key=lambda i: i.key):
        rec = manifest.records.get(item.key)
        status = rec.status if rec else "none"
        doi = item.doi or ""
        lines.append(f"{item.key}|{doi}|{status}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest


def candidate_title_doi(data: dict[str, Any]) -> tuple[str, str]:
    """Title and DOI from a snowball candidate row.

    Live queues store them under ``biblio`` / ``ids``. Older fixtures used
    top-level ``title`` and ``doi``.
    """
    biblio = data.get("biblio") if isinstance(data.get("biblio"), dict) else {}
    ids = data.get("ids") if isinstance(data.get("ids"), dict) else {}
    title = str(data.get("title") or biblio.get("title") or "").strip()
    doi = str(data.get("doi") or ids.get("doi") or "").strip()
    return title, doi


def newest_snowball_queue(cfg: Config) -> tuple[str, list[dict[str, Any]]]:
    root = cfg.state_dir / "snowball"
    if not root.is_dir():
        return "", []
    runs = sorted(
        [p for p in root.iterdir() if p.is_dir() and (p / "candidates.jsonl").is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        return "", []
    run_id = runs[0].name
    rows: list[dict[str, Any]] = []
    with (runs[0] / "candidates.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            title, doi = candidate_title_doi(data)
            rows.append(
                {
                    "title": title,
                    "doi": doi,
                    "keep": data.get("keep"),
                    "run_id": run_id,
                }
            )
    return run_id, rows


def authorwatch_inbox_rows(cfg: Config) -> list[dict[str, Any]]:
    root = cfg.state_dir / "authorwatch"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for list_dir in sorted(root.iterdir()):
        if not list_dir.is_dir():
            continue
        inbox = list_dir / "inbox.jsonl"
        if not inbox.is_file():
            continue
        with inbox.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                title, doi = candidate_title_doi(data)
                out.append(
                    {
                        "list": list_dir.name,
                        "title": title,
                        "doi": doi,
                    }
                )
    return out


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
    return cfg.ui_library_page_size if cfg.ui_library_page_size in options else options[0]


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


def library_item_rows(cfg: Config, items: list[Any], manifest: Manifest) -> list[dict[str, Any]]:
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
    total = len(sorted_items)
    per_page = max(1, int(per_page))
    page_count = max(1, (total + per_page - 1) // per_page) if total else 1
    page = min(max(1, int(page)), page_count)
    start = (page - 1) * per_page
    chunk = sorted_items[start : start + per_page]
    rows = library_item_rows(cfg, chunk, manifest)
    return rows, total, page, page_count


def snowball_deferred_run_id(cfg: Config) -> str:
    root = cfg.state_dir / "snowball"
    if not root.is_dir():
        return ""
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_dir() and (path / "deferred.json").is_file():
            return path.name
    return ""


def list_snowball_profiles(cfg: Config) -> list[str]:
    from ..run_config import profiles_dir

    names: list[str] = []
    folder = profiles_dir(cfg)
    if folder.is_dir():
        for path in sorted(folder.glob("*.toml")):
            try:
                import sys

                if sys.version_info >= (3, 11):
                    import tomllib as _toml
                else:
                    import tomli as _toml
                raw = _toml.loads(path.read_bytes())
            except Exception:
                continue
            if isinstance(raw, dict) and str(raw.get("kind") or "") == "snowball":
                names.append(path.stem)
    for name, table in (cfg.run_profiles or {}).items():
        if isinstance(table, dict) and str(table.get("kind") or "") == "snowball":
            if name not in names:
                names.append(name)
    return sorted(names)


def authorwatch_lists(cfg: Config) -> list[dict[str, Any]]:
    from ..authorwatch import inbox_count, load_people, load_watch

    root = cfg.state_dir / "authorwatch"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "watch.json").is_file():
            continue
        name = path.name
        try:
            watch = load_watch(cfg, name)
        except Exception:
            watch = {}
        people = load_people(cfg, name)
        out.append(
            {
                "name": name,
                "people": len(people),
                "inbox": inbox_count(cfg, name),
                "baseline": bool(watch.get("baseline_at")),
            }
        )
    return out


def authorwatch_people_rows(cfg: Config, name: str) -> list[dict[str, Any]]:
    from ..authorwatch import load_people

    rows: list[dict[str, Any]] = []
    for person in load_people(cfg, name):
        rows.append(
            {
                "id": person.id,
                "display_name": person.display_name or person.id,
                "orcid": person.orcid,
                "status": person.status,
                "affiliation": person.affiliation_host,
                "identity": person.identity(),
            }
        )
    return rows


def authorwatch_suggestion_rows(cfg: Config, name: str) -> list[dict[str, Any]]:
    from ..authorwatch import load_suggestions

    rows: list[dict[str, Any]] = []
    for row in load_suggestions(cfg, name):
        if row.status != "pending":
            continue
        rows.append(
            {
                "id": row.id,
                "display_name": row.display_name,
                "orcid": row.orcid,
                "openalex": row.openalex,
                "method": row.method,
                "score": row.score,
                "why": row.why,
                "pollable": row.pollable,
            }
        )
    return rows


def following_lists(cfg: Config) -> list[dict[str, Any]]:
    """Snowball watches and authorwatch lists for Discover."""
    out: list[dict[str, Any]] = []
    watches = cfg.state_dir / "snowball" / "watches"
    if watches.is_dir():
        for p in sorted(watches.iterdir()):
            if p.is_dir():
                out.append({"kind": "topic", "name": p.name})
    aw = cfg.state_dir / "authorwatch"
    if aw.is_dir():
        for p in sorted(aw.iterdir()):
            if p.is_dir() and (p / "watch.json").is_file():
                out.append({"kind": "person", "name": p.name})
    return out


REPAIR_VERBS = ("lint", "fix-metadata", "dedupe", "versions", "attachments", "ocr")
MIRROR_VERBS = ("sync", "snapshot", "restore", "cache clean")


def repair_queues(cfg: Config) -> list[dict[str, Any]]:
    """On-disk repair packs/reports for the Repair page."""
    rows: list[dict[str, Any]] = []
    mapping = (
        ("lint", cfg.state_dir / "runs", "*-lint.json"),
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


ASK_ERROR_MESSAGES = {
    "empty": "Enter a question.",
    "year": "Year from and year to must be integers.",
    "focus": "Focus must be default, questions, gaps, methods, or answered.",
    "disabled": "Turn on [rag] and [llm] in config.toml to use Ask.",
    "llm": "Turn on [llm] in config.toml to summarize and synthesize.",
    "rag": "Turn on [rag] in config.toml to ingest and search.",
    "limit": "Limit and top-k must be positive integers.",
    "dest": "Destination must be disk, zotero, or both.",
    "collection": "Pick a collection in the chip, or set destination to disk.",
    "order": "Order must be library, newest, or oldest.",
    "questions": "Enter at least one question (one per line).",
    "apply": "A Zotero collection note needs dest zotero or both, and a collection.",
    "search": "Search failed. Check that the index exists and the embedder is up.",
    "prompt": "Custom prompt is invalid, empty, or missing.",
    "scope": "Pick a collection, item keys, or whole library.",
    "upload": "Upload is empty or too large.",
    "type": "Item type filter is invalid.",
}

DEST_OPTIONS = ("disk", "zotero", "both")
SUMMARIZE_ORDERS = ("library", "newest", "oldest")


def list_threads(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    from ..rag.thread import threads_dir

    root = threads_dir(cfg.state_dir)
    if not root.is_dir():
        return []
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        turns = body.get("turns") if isinstance(body, dict) else None
        n = len(turns) if isinstance(turns, list) else 0
        out.append(
            {
                "id": str((body or {}).get("id") or path.stem),
                "turns": n // 2,
                "mtime": path.stat().st_mtime,
            }
        )
    return out


def thread_for_display(cfg: Config, thread_id: str) -> list[dict[str, str]]:
    from ..rag.thread import load_thread

    loaded = load_thread(cfg.state_dir, thread_id)
    return [{"role": t.get("role") or "", "content": t.get("content") or ""} for t in loaded.turns]


def last_ask_result(cfg: Config, thread_id: str) -> dict[str, Any]:
    from . import commands

    if not thread_id:
        return {}
    for rec in commands.list_commands(cfg, limit=50):
        if rec.get("verb") != "ask":
            continue
        result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
        if str(result.get("thread_id") or "") == thread_id:
            return result
    return {}


def ask_page_flags(cfg: Config) -> dict[str, Any]:
    from ..llm import embed_egress_is_remote, llm_egress_is_remote
    from ..rag.status import index_status

    rag_on = bool(cfg.rag_enabled)
    llm_on = bool(cfg.llm_enabled)
    ready = rag_on and llm_on
    status: dict[str, Any] = {}
    if rag_on:
        try:
            status = dict(index_status(cfg) or {})
        except Exception as exc:
            status = {"error": str(exc), "problem": str(exc)}
    problem = str(status.get("problem") or status.get("error") or "")
    items = int(status.get("items") or 0)
    exists = bool(status.get("exists"))
    indexed = exists and items > 0 and not problem
    return {
        "rag_on": rag_on,
        "llm_on": llm_on,
        "ready": ready,
        "can_ingest": rag_on,
        "can_search": rag_on and indexed,
        "can_ask": ready and indexed,
        "remote_llm": llm_on and llm_egress_is_remote(cfg),
        "remote_embed": rag_on and embed_egress_is_remote(cfg),
        "status": status,
    }


def command_by_id(cfg: Config, cmd_id: str) -> dict[str, Any] | None:
    from . import commands

    if not cmd_id:
        return None
    return commands.read_command(cfg, cmd_id)


def last_job_result(cfg: Config, verb: str) -> dict[str, Any]:
    from . import commands

    for rec in commands.list_commands(cfg, limit=50):
        if rec.get("verb") != verb:
            continue
        result = rec.get("result") if isinstance(rec.get("result"), dict) else {}
        return {
            "status": rec.get("status") or "",
            "error": rec.get("error") or "",
            **result,
        }
    return {}


def list_ask_packs(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    from ..rag.batch import batch_dir

    root = batch_dir(cfg)
    if not root.is_dir():
        return []
    dirs = [
        p
        for p in root.iterdir()
        if p.is_dir() and p.name != "by-hash" and (p / "answers.md").is_file()
    ]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in dirs[:limit]:
        questions = answered = failed = 0
        pack = path / "pack.json"
        if pack.is_file():
            try:
                body = json.loads(pack.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                body = {}
            if isinstance(body, dict):
                questions = int(body.get("questions") or 0)
                answered = int(body.get("answered") or 0)
                failed = int(body.get("failed") or 0)
        out.append(
            {
                "stamp": path.name,
                "questions": questions,
                "answered": answered,
                "failed": failed,
                "mtime": path.stat().st_mtime,
            }
        )
    return out


def list_answered_packs(cfg: Config, limit: int = 12) -> list[dict[str, Any]]:
    from ..rag.answered import answered_dir

    root = answered_dir(cfg)
    if not root.is_dir():
        return []
    dirs = [
        p
        for p in root.iterdir()
        if p.is_dir() and (p / "pack.md").is_file()
    ]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in dirs[:limit]:
        questions = answered = partial = not_found = failed = 0
        pack = path / "pack.json"
        if pack.is_file():
            try:
                body = json.loads(pack.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                body = {}
            if isinstance(body, dict):
                questions = int(body.get("questions") or 0)
                answered = int(body.get("answered") or 0)
                partial = int(body.get("partial") or 0)
                not_found = int(body.get("not_found") or 0)
                failed = int(body.get("failed") or 0)
        out.append(
            {
                "stamp": path.name,
                "questions": questions,
                "answered": answered,
                "partial": partial,
                "not_found": not_found,
                "failed": failed,
                "mtime": path.stat().st_mtime,
            }
        )
    return out


def list_html_stems(folder: Any, limit: int = 20) -> list[dict[str, Any]]:
    from pathlib import Path

    root = Path(folder)
    if not root.is_dir():
        return []
    files = sorted(
        (p for p in root.glob("*.html") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [{"name": p.stem, "mtime": p.stat().st_mtime} for p in files[:limit]]


def _summary_model(html: str) -> str:
    from ..notehtml import parse
    from ..summarize import parse_summary_provenance

    meta = parse(html) or {}
    model = str(meta.get("model") or "").strip()
    if model:
        return model
    prov = parse_summary_provenance(html) or {}
    return str(prov.get("model") or "").strip()


def _summary_cite(cfg: Config, key: str) -> str:
    try:
        from ..catalogue import MirrorCatalogue

        item = MirrorCatalogue(cfg.out_dir).get_item(key)
    except OSError:
        item = None
    if item is None:
        return key
    return item.label


def summary_meta(cfg: Config, key: str) -> dict[str, Any] | None:
    """Cite, model, and mtime for ``state/summaries/<key>.html``."""
    path = cfg.summaries_dir / f"{key}.html"
    if not path.is_file():
        return None
    html = path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": key,
        "cite": _summary_cite(cfg, key),
        "model": _summary_model(html),
        "mtime": path.stat().st_mtime,
    }


def list_recent_summaries(cfg: Config, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stem in list_html_stems(cfg.summaries_dir, limit):
        meta = summary_meta(cfg, stem["name"])
        if meta is not None:
            rows.append(meta)
    return rows


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


def briefs_page_flags(cfg: Config) -> dict[str, Any]:
    from ..llm import llm_egress_is_remote

    llm_on = bool(cfg.llm_enabled)
    return {
        "llm_on": llm_on,
        "remote_llm": llm_on and llm_egress_is_remote(cfg),
        "summarize_dest": cfg.summarize_dest,
        "synthesize_dest": cfg.synthesize_dest,
        "summarize_order": cfg.summarize_order,
    }


def focus_options() -> list[str]:
    from ..rag.prompt import FOCI

    names = list(FOCI)
    if "default" in names:
        names.remove("default")
        return ["default", *sorted(names)]
    return sorted(names)


def queue_fingerprint(cfg: Config, verb: str) -> str:
    import hashlib

    lines: list[str] = []
    for row in repair_queues(cfg):
        if row["verb"] != verb:
            continue
        for name in row["files"]:
            lines.append(f"{verb}|{name}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
