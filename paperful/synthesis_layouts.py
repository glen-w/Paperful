"""Bundled ``paperful synthesize`` report shapes. Distinct from Ask ``--focus``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

KNOWN_LAYOUTS = ("default", "conflict", "review")

LAYOUT_DEFAULT = """You are writing a literature review for a personal research library.
Use ONLY the summaries below. Cite only as [Surname Year] from those blocks.
If something is not covered, say "not covered". Do not invent papers or findings.
Structure the review in simple HTML (no outer html/body tags, no Markdown, no code fences):
<h2>Corpus</h2>
<h2>Themes</h2>
<h2>Points of agreement</h2>
<h2>Disagreements and tensions</h2>
<h2>Gaps and open questions</h2>
<h2>Suggested reading order</h2>
Use <p> and <ul><li>. Keep under 1200 words."""

LAYOUT_CONFLICT = """You write a conflicting-evidence brief for a personal research library.
Use ONLY the summaries below. Cite only as [Surname Year] from those blocks.
Do not invent papers or findings. Do not smooth disagreement into one narrative.
If the summaries do not decide, say so and cite what they do show.
Structure the review in simple HTML (no outer html/body tags, no Markdown, no code fences):
<h2>Question in this set</h2>
<h2>Camps</h2>
<h2>Methods behind each camp</h2>
<h2>What agrees</h2>
<h2>What disagrees</h2>
<h2>What is undecided</h2>
Under Camps, name each camp in a heading or list item and cite both sides.
Under Methods, say which designs or data sit behind each camp.
Use <p> and <ul><li>. Keep under 1200 words."""

LAYOUT_REVIEW = """You write a review-shaped literature brief for a personal research library.
Use ONLY the summaries below. Cite only as [Surname Year] from those blocks.
If something is not covered, say "not covered". Do not invent papers or findings.
Structure the review in simple HTML (no outer html/body tags, no Markdown, no code fences):
<h2>Abstract</h2>
<h2>Research question</h2>
<h2>Methods in this set</h2>
<h2>Findings</h2>
<h2>Limits</h2>
<h2>Conclusions</h2>
Abstract is at most 120 words. Methods describe what the held summaries actually did, not an ideal protocol.
Use <p> and <ul><li>. Keep under 1200 words."""

LAYOUT_REPORT_PROMPTS: dict[str, str] = {
    "default": LAYOUT_DEFAULT,
    "conflict": LAYOUT_CONFLICT,
    "review": LAYOUT_REVIEW,
}


def canonical_layout(name: str) -> str:
    raw = str(name or "").strip().lower()
    if raw not in KNOWN_LAYOUTS:
        raise ValueError(
            f"unknown synthesize layout {name!r} (want {', '.join(KNOWN_LAYOUTS)})"
        )
    return raw


def resolve_layout(cfg: Any, layout: str | None = None) -> str:
    if layout and str(layout).strip():
        return canonical_layout(layout)
    return canonical_layout(getattr(cfg, "synthesize_layout", None) or "default")


def load_layout_prompt(cfg: Any) -> tuple[str, str, str]:
    """Return ``(text, layout_id, label)``.

    A ``[synthesize].prompt_template`` path (or CLI ``--prompt``) wins and is
    labelled ``custom``. Bundled layouts stay ``default`` / ``conflict`` /
    ``review``.
    """
    template = str(getattr(cfg, "synthesize_prompt_template", "default") or "default")
    if template != "default":
        path = Path(template)
        return path.read_text(encoding="utf-8"), "custom", str(path)
    layout_id = resolve_layout(cfg, None)
    return LAYOUT_REPORT_PROMPTS[layout_id], layout_id, layout_id
