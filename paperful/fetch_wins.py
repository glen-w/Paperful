"""Local PDF-fetch wins and learned playbook propose/promote.

Wins live in ``state/fetch-wins.jsonl``. Promoted recipes live in
``{grey_playbooks_dir}/learned.toml``. Neither is part of the package.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .config import Config
from .page_signals import host_label, is_search_engine_host
from .playbooks import GreyPlaybook, load_pack_file

WINS_NAME = "fetch-wins.jsonl"
PROPOSED_NAME = "playbooks-proposed.toml"
LEARNED_NAME = "learned.toml"
_SKIP_WINS = frozenset({"body", "download"})
_warned_no_dir = False


def wins_path(cfg: Config) -> Path:
    return cfg.state_dir / WINS_NAME


def proposed_path(cfg: Config) -> Path:
    return cfg.state_dir / PROPOSED_NAME


def learned_path(cfg: Config) -> Path | None:
    if cfg.grey_playbooks_dir is None:
        return None
    return cfg.grey_playbooks_dir / LEARNED_NAME


def url_without_query(url: str) -> str:
    """Host + path only. Query strings often carry session tokens."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.split("?", 1)[0]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def promotable(win: str) -> bool:
    head = (win or "").split("+")[-1]
    if head in _SKIP_WINS or not head:
        return False
    return head.startswith(("meta", "rewrite", "click:", "viewer:"))


def append_win(cfg: Config, row: dict) -> None:
    try:
        path = wins_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        return


def load_wins(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def record_win(
    cfg: Config,
    *,
    item_key: str,
    source: str,
    start_url: str,
    final_url: str,
    win: str,
    playbook: str = "",
) -> None:
    """Append one vault or browser-agent success. Never raises."""
    try:
        from . import __version__

        row = {
            "ts": time.time(),
            "paperful": __version__,
            "item_key": item_key,
            "source": source,
            "host": host_label(final_url or start_url),
            "start_url": url_without_query(start_url),
            "final_url": url_without_query(final_url or start_url),
            "win": win,
        }
        if playbook:
            row["playbook"] = playbook
        append_win(cfg, row)
        if cfg.playbooks_promote == "auto":
            _auto_promote(cfg, row)
    except Exception:
        return


def _warn_no_dir() -> None:
    global _warned_no_dir
    if _warned_no_dir:
        return
    _warned_no_dir = True
    print(
        "playbooks promote=auto skipped: set grey_playbooks_dir (e.g. \"packs\")",
        flush=True,
    )


def _auto_promote(cfg: Config, row: dict) -> None:
    if cfg.grey_playbooks_dir is None:
        _warn_no_dir()
        return
    if not promotable(str(row.get("win") or "")):
        return
    books = recipes_from_wins(
        load_wins(wins_path(cfg)), min_hits=cfg.playbooks_auto_min_hits
    )
    if not books:
        return
    if write_learned(cfg.grey_playbooks_dir, books):
        refresh_playbooks(cfg)


def recipes_from_wins(rows: list[dict], *, min_hits: int) -> list[GreyPlaybook]:
    """Cluster promotable wins into playbooks that reached ``min_hits``."""
    grouped: dict[str, list[GreyPlaybook]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        book = recipe_from_row(row)
        if book is None:
            continue
        grouped.setdefault(book.name, book)
        counts[book.name] = counts.get(book.name, 0) + 1
    out: list[GreyPlaybook] = []
    for name in sorted(grouped):
        if counts[name] >= min_hits:
            out.append(grouped[name])
    return out


def recipe_from_row(row: dict) -> GreyPlaybook | None:
    win = str(row.get("win") or "")
    if not promotable(win):
        return None
    start = str(row.get("start_url") or "")
    final = str(row.get("final_url") or "")
    host = host_label(final or start)
    if not host or is_search_engine_host(host):
        return None
    if host_label(start) and host_label(start) != host and not same_enough(start, final):
        return None
    rewritten = _rewrite_between(start, final)
    slug = _slug(host, "rewrite" if rewritten else _win_slug(win))
    name = f"learned-{slug}"
    if not name.startswith("learned-"):
        return None
    if rewritten:
        url_re, template = rewritten
        return GreyPlaybook(
            name=name,
            kind="rewrite",
            hosts=(host,),
            url_re=url_re,
            pdf_template=template,
        )
    href = _href_re(final)
    if not href:
        return None
    return GreyPlaybook(name=name, kind="scrape", hosts=(host,), href_re=href)


def same_enough(start: str, final: str) -> bool:
    from .page_signals import same_site

    return same_site(start, final)


def _win_slug(win: str) -> str:
    head = win.split("+")[-1]
    head = head.split(":", 1)[0]
    return head or "hit"


def _slug(host: str, kind: str) -> str:
    raw = f"{host}-{kind}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:60] or "host"


def _rewrite_between(start: str, final: str) -> tuple[str, str] | None:
    """Stable path transform (e.g. ``/doi/abs/`` → ``/doi/pdfdirect/``)."""
    su, fu = urlparse(start), urlparse(final)
    if host_label(start) != host_label(final) or not host_label(start):
        return None
    sp, fp = su.path or "", fu.path or ""
    if not sp or not fp or sp == fp:
        return None
    i = 0
    while i < len(sp) and i < len(fp) and sp[i] == fp[i]:
        i += 1
    prefix = sp[:i]
    slash = prefix.rfind("/")
    if slash < 0:
        return None
    prefix = sp[: slash + 1]
    sp_rest, fp_rest = sp[len(prefix) :], fp[len(prefix) :]
    j = 0
    while (
        j < len(sp_rest)
        and j < len(fp_rest)
        and sp_rest[-1 - j] == fp_rest[-1 - j]
    ):
        j += 1
    if j < 2:
        return None
    code = sp_rest[-j:]
    mid_s, mid_f = sp_rest[:-j], fp_rest[:-j]
    if not mid_s or not mid_f or len(code) < 3:
        return None
    origin = f"{su.scheme}://{su.netloc}{prefix}{mid_s}"
    dest = f"{fu.scheme}://{fu.netloc}{prefix}{mid_f}"
    url_re = re.escape(origin) + r"(?P<code>.+)"
    return url_re, dest + "{code}"


def _href_re(final: str) -> str:
    path = (urlparse(final).path or "").lower()
    if path.endswith(".pdf"):
        return r"(?i)\.pdf(?:\?|$)"
    if "pdfdirect" in path:
        return "(?i)pdfdirect"
    if "pdfft" in path:
        return "(?i)pdfft"
    seg = path.rstrip("/").split("/")[-1]
    if len(seg) < 3:
        return ""
    return re.escape(seg)


def render_playbooks(books: list[GreyPlaybook]) -> str:
    chunks: list[str] = []
    for pb in books:
        if not pb.name.startswith("learned-"):
            continue
        lines = [
            "[[grey_playbooks]]",
            f'name = "{pb.name}"',
            f'kind = "{pb.kind}"',
        ]
        if pb.hosts:
            hosts = ", ".join(json.dumps(h) for h in pb.hosts)
            lines.append(f"hosts = [{hosts}]")
        if pb.url_re:
            lines.append("url_re = " + _toml_literal(pb.url_re))
        if pb.pdf_template:
            lines.append("pdf_template = " + json.dumps(pb.pdf_template))
        if pb.href_re:
            lines.append("href_re = " + _toml_literal(pb.href_re))
        chunks.append("\n".join(lines))
    body = "\n\n".join(chunks)
    return (body + "\n") if body else ""


def _toml_literal(value: str) -> str:
    escaped = value.replace("'''", "'''\"'''\"'''")
    return "'''" + escaped + "'''"


def propose_toml(rows: list[dict], *, min_hits: int = 1) -> str:
    return render_playbooks(recipes_from_wins(rows, min_hits=min_hits))


def write_learned(directory: Path, books: list[GreyPlaybook]) -> bool:
    """Atomically write ``learned.toml``. Return False when unchanged.

    Only ``learned-`` names are written. Existing learned rows are updated
    by name; other names in the file are dropped on rewrite because this
    file is reserved for promoted recipes.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LEARNED_NAME
    existing = {pb.name: pb for pb in load_pack_file(path) if pb.name.startswith("learned-")}
    for book in books:
        if book.name.startswith("learned-"):
            existing[book.name] = book
    text = render_playbooks([existing[name] for name in sorted(existing)])
    try:
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        current = ""
    if current == text:
        return False
    tmp = directory / ".learned.toml.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def refresh_playbooks(cfg: Config) -> None:
    """Reload merged playbooks so the next item sees a new learned pack."""
    if cfg.config_path is not None and cfg.config_path.is_file():
        from .config import load_config

        cfg.grey_playbooks = load_config(cfg.config_path).grey_playbooks
        return
    path = learned_path(cfg)
    if path is None:
        return
    for book in load_pack_file(path):
        if not book.name.startswith("learned-"):
            continue
        replaced = False
        updated: list[GreyPlaybook] = []
        for current in cfg.grey_playbooks:
            if current.name == book.name:
                updated.append(book)
                replaced = True
            else:
                updated.append(current)
        if not replaced:
            updated.append(book)
        cfg.grey_playbooks = updated
