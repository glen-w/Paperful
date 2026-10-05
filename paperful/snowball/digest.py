"""Frontier digest: ranked rollup of a snowball queue or watch. No library writes."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from .briefing import _group, _read_json, _rel, _row_line
from .candidate import Candidate
from .command import SnowballError
from .profile import load_profile
from .queue import load_queue
from .watch import inbox_count, load_watch, watch_dir


TOP_NEW = 25
_SECTIONS = ("new", "exists", "version", "deferred")


@dataclass(frozen=True)
class Digest:
    markdown: str
    html: str
    path: Path
    counts: dict[str, int]


def write_run_digest(cfg: Config, run_id: str) -> Digest:
    run_id = run_id.strip()
    if not run_id:
        raise SnowballError("digest needs --run-id.", code=1)
    try:
        dest, rows = load_queue(cfg.state_dir, run_id)
    except FileNotFoundError as exc:
        raise SnowballError(f"No snowball queue for run {run_id!r}.", code=1) from exc
    summary = _read_json(dest / "summary.json")
    collection = _suggested_collection(cfg, "")
    deferred = bool(summary.get("deferred"))
    intro = [f"Queue rollup for run `{run_id}`."]
    if deferred:
        intro.append(
            "OpenAlex stopped early on this run. "
            f"`paperful snowball resume {run_id}` continues it."
        )
    actions = _actions(
        cfg,
        run_id=run_id,
        collection=collection,
        queue=dest,
        deferred=deferred,
    )
    return _render(
        dest / "digest.md",
        title=f"Frontier digest {run_id}",
        intro=intro,
        rows=rows,
        collection_lines=_collection_lines(run_id, collection),
        actions=actions,
        deferred_flag=deferred,
    )


def write_watch_digest(cfg: Config, name: str) -> Digest:
    body = load_watch(cfg, name)
    dest = watch_dir(cfg, name)
    inbox = dest / "inbox.jsonl"
    pending = inbox_count(cfg, name)
    last = str(body.get("last_run_id") or "").strip()
    profile = str(body.get("profile") or "").strip()
    rows: list[Candidate] = []
    summary: dict = {}
    queue: Path | None = None
    if last:
        try:
            queue, rows = load_queue(cfg.state_dir, last)
        except FileNotFoundError as exc:
            raise SnowballError(
                f"Watch {name!r} last run {last!r} has no queue.",
                code=1,
            ) from exc
        summary = _read_json(queue / "summary.json")
    collection = _suggested_collection(cfg, profile)
    deferred = bool(summary.get("deferred"))
    intro = [
        f"Watch `{name}` · profile `{profile}`.",
        f"Inbox `{_rel(cfg, inbox)}` · pending {pending}.",
    ]
    if last and queue is not None:
        intro.append(
            f"Last run `{last}` · queue `{_rel(cfg, queue / 'candidates.jsonl')}`."
        )
        intro.append(
            "Counts below are the last run queue. "
            "The inbox stays new-only and keeps older proposals."
        )
    if body.get("baseline_at") and pending == 0 and not rows:
        intro.append("Baseline is recorded and the inbox is empty.")
    elif not body.get("baseline_at") and not last:
        intro.append("No baseline yet. `paperful snowball watch run` records one.")
    seen = summary.get("already_seen")
    if seen is not None:
        intro.append(f"Already seen {seen} (dropped from this run).")
    actions = _actions(
        cfg,
        run_id=last,
        collection=collection,
        queue=queue,
        inbox=inbox,
        watch=name,
        deferred=deferred,
    )
    digest = _render(
        dest / "digest.md",
        title=f"Frontier digest {name}",
        intro=intro,
        rows=rows,
        collection_lines=_collection_lines(last, collection),
        actions=actions,
        deferred_flag=deferred,
        inbox_pending=pending,
    )
    return digest


def _suggested_collection(cfg: Config, profile: str) -> str:
    if profile.strip():
        try:
            raw = load_profile(cfg, profile.strip())
        except SnowballError:
            raw = {}
        chosen = str(raw.get("target_collection") or "").strip()
        if chosen:
            return chosen
    return str(cfg.snowball_target_collection or "").strip()


def _collection_lines(run_id: str, collection: str) -> list[str]:
    if run_id and collection:
        return [f"`paperful snowball apply {run_id} -C {_quote(collection)}`"]
    if run_id:
        return [
            "Target collection is unset. "
            f"`paperful snowball apply {run_id}` needs `-C`."
        ]
    if collection:
        return [f"Suggested `-C` is `{collection}`. Run the watch before apply."]
    return ["Target collection is unset. Apply needs `-C` after a watch run."]


def _actions(
    cfg: Config,
    *,
    run_id: str,
    collection: str,
    queue: Path | None,
    deferred: bool,
    inbox: Path | None = None,
    watch: str = "",
) -> list[str]:
    lines: list[str] = []
    if queue is not None:
        lines.append(f"`{_rel(cfg, queue / 'candidates.jsonl')}`")
        lines.append(f"`{_rel(cfg, queue / 'summary.json')}`")
    if inbox is not None:
        lines.append(f"`{_rel(cfg, inbox)}`")
    if watch:
        lines.append(f"`paperful snowball watch show {watch}`")
        lines.append(f"`paperful snowball watch run {watch} --digest`")
    if run_id and collection:
        lines.append(f"`paperful snowball apply {run_id} -C {_quote(collection)}`")
    elif run_id:
        lines.append(f"`paperful snowball apply {run_id} -C …`")
    if deferred and run_id:
        lines.append(f"`paperful snowball resume {run_id}`")
    return lines


def _render(
    path: Path,
    *,
    title: str,
    intro: list[str],
    rows: list[Candidate],
    collection_lines: list[str],
    actions: list[str],
    deferred_flag: bool,
    inbox_pending: int | None = None,
) -> Digest:
    grouped = _group(rows)
    grouped["new"] = sorted(grouped.get("new") or [], key=lambda row: row.score, reverse=True)
    counts = {key: len(grouped.get(key) or []) for key in (*_SECTIONS, "other")}
    if deferred_flag:
        counts["deferred"] = max(counts["deferred"], 1)
    if inbox_pending is not None:
        counts["inbox"] = inbox_pending
    lines = [f"# {title}", ""]
    lines.extend(intro)
    lines.append("")
    shown = [key for key in (*_SECTIONS, "other") if key != "other" or counts[key]]
    if inbox_pending is not None:
        shown.append("inbox")
    lines.append(" · ".join(f"{key} {counts[key]}" for key in shown))
    lines.append("")
    lines.extend(_block("Suggested collection", collection_lines))
    lines.extend(_block("Next", [f"- {item}" for item in actions] or ["None."]))
    for key in _SECTIONS:
        chunk = grouped.get(key) or []
        lines.extend(_section(key, chunk, deferred_flag=deferred_flag))
    other = grouped.get("other") or []
    if other:
        lines.extend(_section("other", other, deferred_flag=False))
    markdown = "\n".join(lines).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return Digest(
        markdown=markdown,
        html=_html(title, intro, collection_lines, actions, grouped, counts, deferred_flag),
        path=path,
        counts=counts,
    )


def _block(heading: str, body: list[str]) -> list[str]:
    lines = [f"## {heading}", ""]
    lines.extend(body or ["None."])
    lines.append("")
    return lines


def _section(name: str, rows: list[Candidate], *, deferred_flag: bool) -> list[str]:
    lines = [f"## {name.capitalize()}", ""]
    if name == "deferred" and deferred_flag and not rows:
        lines.append("OpenAlex stopped early. Resume this run (see Next).")
        lines.append("")
        return lines
    if not rows:
        lines.append("None.")
        lines.append("")
        return lines
    if name == "new" and len(rows) > TOP_NEW:
        lines.append(
            f"Overlap detail for the top {TOP_NEW} by score. The rest are titles only."
        )
        lines.append("")
    for index, row in enumerate(rows):
        if name == "new" and index < TOP_NEW:
            lines.append(f"- {_detail_line(row)}")
        else:
            lines.append(f"- {_row_line(row)}")
    lines.append("")
    return lines


def _detail_line(row: Candidate) -> str:
    bits = [_row_line(row), f"score {_fmt_score(row.score)}"]
    overlap = row.biblio.get("overlap")
    if overlap:
        bits.append(f"overlap {overlap}")
    hop = f"hop {row.hop}"
    direction = (row.direction or "").strip()
    bits.append(f"{hop} {direction}".strip())
    why = (row.why or "").replace("\n", " ").strip()
    if why:
        bits.append(why)
    return " — ".join(bits)


def _fmt_score(score: float) -> str:
    if score == int(score):
        return str(int(score))
    return f"{score:g}"


def _quote(collection: str) -> str:
    if any(ch.isspace() for ch in collection):
        return f'"{collection}"'
    return collection


def _html(
    title: str,
    intro: list[str],
    collection_lines: list[str],
    actions: list[str],
    grouped: dict[str, list[Candidate]],
    counts: dict[str, int],
    deferred_flag: bool,
) -> str:
    new_n = counts.get("new", 0)
    parts = [f"<p>{html.escape(title)}: {new_n} new</p>"]
    for line in intro:
        parts.append(f"<p>{html.escape(line)}</p>")
    parts.append("<h2>Suggested collection</h2>")
    parts.append(_html_lines(collection_lines))
    parts.append("<h2>Next</h2>")
    if actions:
        items = "".join(f"<li>{html.escape(item)}</li>" for item in actions)
        parts.append(f"<ul>{items}</ul>")
    else:
        parts.append("<p>None.</p>")
    for key in _SECTIONS:
        rows = grouped.get(key) or []
        parts.append(f"<h2>{html.escape(key.capitalize())} ({len(rows)})</h2>")
        if key == "deferred" and deferred_flag and not rows:
            parts.append("<p>OpenAlex stopped early. Resume this run.</p>")
            continue
        if not rows:
            parts.append("<p>None.</p>")
            continue
        items = []
        for index, row in enumerate(rows):
            text = _detail_line(row) if key == "new" and index < TOP_NEW else _row_line(row)
            items.append(f"<li>{html.escape(text)}</li>")
        parts.append(f"<ul>{''.join(items)}</ul>")
    from ..notehtml import wrap

    return wrap(
        "\n".join(parts),
        note_type="briefing",
        verb="snowball digest",
        extra=f"{new_n} new",
    )


def _html_lines(lines: list[str]) -> str:
    if not lines:
        return "<p>None.</p>"
    return "".join(f"<p>{html.escape(line)}</p>" for line in lines)
