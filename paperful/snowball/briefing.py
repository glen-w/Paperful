"""Markdown export of a snowball queue or a watch inbox. No library writes."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from .candidate import Candidate
from .command import SnowballError
from .queue import load_queue
from .watch import load_watch, watch_dir


_SECTIONS = ("new", "exists", "version", "deferred")


@dataclass(frozen=True)
class Briefing:
    markdown: str
    html: str
    path: Path
    counts: dict[str, int]


def write_run_briefing(cfg: Config, run_id: str) -> Briefing:
    run_id = run_id.strip()
    if not run_id:
        raise SnowballError("briefing needs --run-id.", code=1)
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.", code=1) from exc
    summary = _read_json(dest / "summary.json")
    deferred = bool(summary.get("deferred"))
    path = dest / "briefing.md"
    title = f"Snowball briefing {run_id}"
    intro = [
        f"Queue `{_rel(cfg, dest / 'candidates.jsonl')}`.",
    ]
    if deferred:
        intro.append(
            f"OpenAlex stopped early on this run. "
            f"`paperful snowball resume {run_id}` continues it."
        )
    briefing = _render(path, title=title, intro=intro, rows=rows)
    if deferred:
        counts = dict(briefing.counts)
        counts["deferred"] = max(counts.get("deferred") or 0, 1)
        return Briefing(
            markdown=briefing.markdown,
            html=briefing.html,
            path=briefing.path,
            counts=counts,
        )
    return briefing


def write_watch_briefing(cfg: Config, name: str) -> Briefing:
    body = load_watch(cfg, name)
    dest = watch_dir(cfg, name)
    inbox = dest / "inbox.jsonl"
    rows = _read_inbox(inbox)
    path = dest / "briefing.md"
    last = str(body.get("last_run_id") or "").strip()
    intro = [
        f"Watch `{name}` · profile `{body.get('profile') or ''}`.",
        f"Inbox `{_rel(cfg, inbox)}`.",
    ]
    if last:
        intro.append(f"Last run `{last}`.")
    if body.get("baseline_at") and not rows:
        intro.append("Baseline is recorded and the inbox is empty.")
    elif not body.get("baseline_at"):
        intro.append("No baseline yet. `paperful snowball watch run` records one.")
    return _render(
        path, title=f"Snowball watch briefing {name}", intro=intro, rows=rows
    )


def _render(
    path: Path,
    *,
    title: str,
    intro: list[str],
    rows: list[Candidate],
) -> Briefing:
    grouped = _group(rows)
    counts = {key: len(grouped.get(key) or []) for key in (*_SECTIONS, "other")}
    lines = [f"# {title}", ""]
    lines.extend(intro)
    lines.append("")
    lines.append(
        " · ".join(f"{key} {counts[key]}" for key in (*_SECTIONS, "other"))
    )
    lines.append("")
    for key in _SECTIONS:
        chunk = grouped.get(key) or []
        if not chunk and key not in {"new", "exists"}:
            continue
        lines.extend(_section(key, chunk))
    other = grouped.get("other") or []
    if other:
        lines.extend(_section("other", other))
    markdown = "\n".join(lines).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return Briefing(
        markdown=markdown,
        html=_html(title, intro, grouped, counts),
        path=path,
        counts=counts,
    )


def _group(rows: list[Candidate]) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = {key: [] for key in (*_SECTIONS, "other")}
    for row in rows:
        status = (row.status or "new").strip().lower()
        if status in _SECTIONS:
            grouped[status].append(row)
        else:
            grouped["other"].append(row)
    return grouped


def _section(name: str, rows: list[Candidate]) -> list[str]:
    lines = [f"## {name.capitalize()}", ""]
    if not rows:
        lines.append("None.")
        lines.append("")
        return lines
    for row in rows:
        lines.append(f"- {_row_line(row)}")
    lines.append("")
    return lines


def _row_line(row: Candidate) -> str:
    year = row.biblio.get("year")
    when = str(year) if year else "n.d."
    title = str(row.biblio.get("title") or "(no title)").replace("\n", " ").strip()
    ident = (row.ids.get("doi") or row.ids.get("openalex") or "").strip()
    stamp = _stamp(row)
    bits = [when, title]
    if ident:
        bits.append(f"`{ident}`")
    if stamp:
        bits.append(stamp)
    return " — ".join(bits)


def _stamp(row: Candidate) -> str:
    bits: list[str] = []
    for value in row.provenance.values():
        text = str(value or "").strip()
        if text.startswith("oa:") or text.startswith("grey:"):
            bits.append(text)
    oa_status = str(row.biblio.get("oa_status") or "").strip()
    if oa_status:
        bits.append(f"oa:{oa_status}")
    elif row.biblio.get("is_oa") is True:
        bits.append("oa")
    seen: list[str] = []
    for bit in bits:
        if bit not in seen:
            seen.append(bit)
    return ", ".join(seen)


def _html(
    title: str,
    intro: list[str],
    grouped: dict[str, list[Candidate]],
    counts: dict[str, int],
) -> str:
    new_n = counts.get("new", 0)
    head = f"{title}: {new_n} new"
    parts = [f"<p>{html.escape(head)}</p>"]
    for line in intro:
        parts.append(f"<p>{html.escape(line)}</p>")
    for key in (*_SECTIONS, "other"):
        rows = grouped.get(key) or []
        if key == "other" and not rows:
            continue
        parts.append(f"<h2>{html.escape(key.capitalize())} ({len(rows)})</h2>")
        if not rows:
            parts.append("<p>None.</p>")
            continue
        items = "".join(f"<li>{html.escape(_row_line(row))}</li>" for row in rows)
        parts.append(f"<ul>{items}</ul>")
    return "\n".join(parts)


def _read_inbox(path: Path) -> list[Candidate]:
    if not path.is_file():
        return []
    rows: list[Candidate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(Candidate.from_dict(raw))
    return rows


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def _rel(cfg: Config, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(cfg.state_dir.parent.resolve()))
    except ValueError:
        return str(path)
