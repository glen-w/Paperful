#!/usr/bin/env python3
"""Re-run only the ``reviewers`` lane and merge into an existing pack folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paperful.config import critique_reviewers_for, load_config
from paperful.critique import Finding, count_findings, load_pack, render_markdown
from paperful.critique_extract import extract_path
from paperful.critique_llm import suggested_from_llm
from paperful.llm import get_client
from paperful.store import write_json

_LEGACY_REVIEWER_IDS = frozenset(
    {"reviewer", "reviewer-1", "reviewer-2", "reviewer-3", "reviewer-5"}
)

_LEGACY_BY_ID: dict[str, frozenset[str]] = {
    "general": frozenset({"reviewer", "reviewer-1"}),
    "line-editor": frozenset({"reviewer-2"}),
    "foundations": frozenset({"reviewer-3"}),
    "openreview": frozenset({"reviewer-5"}),
}


def _strip_ids_for_run(run_ids: frozenset[str]) -> frozenset[str]:
    out: set[str] = set(run_ids)
    for rid in run_ids:
        out |= _LEGACY_BY_ID.get(rid, frozenset())
    return frozenset(out)


def _finding_from_dict(row: dict) -> Finding:
    core = (
        "id",
        "code",
        "lane",
        "severity",
        "loc",
        "quote",
        "source",
        "detail",
        "dismissed",
    )
    extra = {k: v for k, v in row.items() if k not in core}
    return Finding(
        id=str(row.get("id") or ""),
        code=str(row.get("code") or ""),
        lane=str(row.get("lane") or "checked"),
        severity=str(row.get("severity") or "info"),
        loc=str(row.get("loc") or ""),
        quote=str(row.get("quote") or ""),
        source=str(row.get("source") or "rule"),
        detail=str(row.get("detail") or ""),
        dismissed=bool(row.get("dismissed")),
        extra=extra,
    )


def _configured_reviewer_ids(cfg) -> frozenset[str]:
    rows = critique_reviewers_for(cfg, None)
    return frozenset({r.id for r in rows} | _LEGACY_REVIEWER_IDS)


def _is_configured_reviewer_finding(row: dict, reviewer_ids: frozenset[str]) -> bool:
    if row.get("source") != "llm":
        return False
    rid = str(row.get("reviewer") or "").strip()
    return rid in reviewer_ids


def merge_reviewers(
    pack_dir: Path,
    *,
    config: Path | None,
    reviewer_filter: list[str] | None = None,
) -> None:
    pack_dir = pack_dir.resolve()
    pack = load_pack(pack_dir)
    if not pack:
        raise SystemExit(f"No pack.json in {pack_dir}")

    cfg = load_config(config)
    cfg.state_dir = pack_dir.parent.parent.parent

    inp = pack.get("input") or {}
    src = Path(str(inp.get("staged_path") or inp.get("path") or ""))
    if not src.is_file():
        raise SystemExit(f"Manuscript not found: {src}")

    wanted = [w.strip() for w in (reviewer_filter or []) if w and str(w).strip()]
    run_rows = critique_reviewers_for(cfg, wanted or None)
    strip_ids = (
        _strip_ids_for_run(frozenset(r.id for r in run_rows))
        if wanted
        else _configured_reviewer_ids(cfg)
    )
    findings = [_finding_from_dict(r) for r in pack.get("findings") or []]
    kept = [
        f
        for f in findings
        if not _is_configured_reviewer_finding(f.to_dict(), strip_ids)
    ]
    metrics = pack.get("metrics") if isinstance(pack.get("metrics"), dict) else {}

    def say(msg: str) -> None:
        print(msg, flush=True)

    say(f"Extracting {src.name}…")
    doc = extract_path(src)
    title = str(inp.get("title") or src.name)
    say(f"Running reviewers lane ({len(run_rows)} reviewer(s))…")

    client = get_client(cfg)
    extra, llm_patch = suggested_from_llm(
        cfg,
        doc,
        kept,
        item=None,
        client=client,
        force=True,
        metrics=metrics,
        reviewer_ids=wanted or None,
        lanes=("reviewers",),
        on_status=say,
    )
    if not llm_patch:
        raise SystemExit("Reviewers lane produced no metadata (LLM disabled?)")

    merged_findings = kept + list(extra)
    llm = dict(pack.get("llm") or {})
    old_rows = list(llm.get("reviewers") or [])
    new_rows = list(llm_patch.get("reviewers") or [])
    new_ids = {str(r.get("id") or "") for r in new_rows}
    llm["reviewers"] = [r for r in old_rows if str(r.get("id") or "") not in new_ids]
    llm["reviewers"].extend(new_rows)
    if llm_patch.get("narrative"):
        llm["narrative"] = llm_patch["narrative"]
    if llm_patch.get("prompt_sha"):
        llm["prompt_sha"] = llm_patch["prompt_sha"]
    if llm_patch.get("model"):
        llm["model"] = llm_patch["model"]
    if llm_patch.get("provider"):
        llm["provider"] = llm_patch["provider"]
    llm.pop("skipped", None)

    pack["findings"] = [f.to_dict() for f in merged_findings]
    pack["counts"] = count_findings(merged_findings)
    pack["llm"] = llm

    write_json(pack_dir / "pack.json", pack)
    (pack_dir / "pack.md").write_text(
        render_markdown(pack, show_dismissed=False), encoding="utf-8"
    )
    say(f"Updated {pack_dir} ({len(extra)} new suggested finding(s)).")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pack_dir", type=Path, help="Existing stamp folder with pack.json")
    p.add_argument("--config", type=Path, default=None, help="config.toml path")
    p.add_argument(
        "--reviewer",
        action="append",
        default=[],
        help="Subset of critique.reviewers ids (repeatable). Default: all.",
    )
    args = p.parse_args(argv)
    merge_reviewers(
        args.pack_dir,
        config=args.config,
        reviewer_filter=args.reviewer or None,
    )


if __name__ == "__main__":
    main()
