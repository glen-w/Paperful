"""Render rewrite pack.md and sidecar text from a plan."""

from __future__ import annotations

from typing import Any

from .rewrite_plan import RewriteEdit, RewritePlan


def render_markdown(
    pack: dict[str, Any],
    plan: RewritePlan,
) -> str:
    title = (
        (pack.get("input") or {}).get("title")
        or pack.get("critique_id")
        or "manuscript"
    )
    worklog = plan.to_dict().get("worklog") or {}
    lines = [
        f"# Rewrite: {title}",
        "",
        "Apply-from-critique. Not a generated paper. Unflagged text is unchanged.",
        "",
        "## Worklog",
        "",
    ]
    addressed = worklog.get("addressed") or []
    skipped = worklog.get("skipped") or []
    models = worklog.get("models") or {}
    if addressed:
        for row in addressed[:80]:
            lines.append(f"- addressed: {row}")
    else:
        lines.append("- addressed: (none)")
    if skipped:
        lines.append(f"- skipped: {len(skipped)}")
        for row in skipped[:40]:
            lines.append(f"  - {row}")
    if models:
        parts = ", ".join(f"{k}={v}" for k, v in models.items() if v)
        if parts:
            lines.append(f"- models: {parts}")
    lines.extend(["", "## Edits", ""])
    if not plan.edits:
        lines.append("No edits.")
        lines.append("")
    for i, edit in enumerate(plan.edits, start=1):
        ids = ", ".join(edit.finding_ids) or "—"
        lines.append(f"### {i}. `{edit.kind}` ({edit.area}) `{ids}`")
        lines.append("")
        if edit.loc:
            lines.append(f"- loc: {edit.loc}")
        if edit.quote:
            lines.append(f"- quote: {edit.quote[:200]}")
        if edit.kind == "replace" and edit.replacement:
            lines.append(f"- replacement: {edit.replacement[:400]}")
        if edit.kind == "comment" and edit.body:
            lines.append(f"- comment: {edit.body[:400]}")
        if edit.kind == "insert" and edit.replacement:
            lines.append(f"- insert: {edit.replacement[:400]}")
        lines.append("")
    if plan.skips:
        lines.extend(["## Skips", ""])
        for row in plan.skips:
            lines.append(f"- `{row.get('finding_id')}`: {row.get('reason')}")
        lines.append("")
    return "\n".join(lines)


def apply_to_text(text: str, edits: list[RewriteEdit]) -> str:
    """Apply non-overlapping replace/insert/delete edits to plain text."""
    body = text
    ordered = sorted(
        (e for e in edits if e.kind in {"replace", "insert", "delete"} and e.quote),
        key=lambda e: e.start if e.start >= 0 else body.find(e.quote),
        reverse=True,
    )
    for edit in ordered:
        quote = edit.quote
        if not quote or quote not in body:
            continue
        start = body.find(quote) if edit.start < 0 else edit.start
        if start < 0:
            continue
        end = start + len(quote)
        if edit.kind == "replace":
            body = body[:start] + edit.replacement + body[end:]
        elif edit.kind == "delete":
            body = body[:start] + body[end:]
        elif edit.kind == "insert":
            body = body[:end] + edit.replacement + body[end:]
    return body
