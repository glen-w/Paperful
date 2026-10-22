"""Write a Shields.io endpoint badge from a coverage.py JSON report."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def color_for(percent: int) -> str:
    if percent >= 90:
        return "brightgreen"
    if percent >= 80:
        return "green"
    if percent >= 70:
        return "yellowgreen"
    if percent >= 60:
        return "yellow"
    if percent >= 50:
        return "orange"
    return "red"


def badge_from_coverage(report: dict) -> dict:
    totals = report["totals"]
    percent = int(totals["percent_covered_display"])
    return {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{percent}%",
        "color": color_for(percent),
    }


def write_badge(coverage_path: Path, badge_path: Path) -> dict:
    report = json.loads(coverage_path.read_text(encoding="utf-8"))
    badge = badge_from_coverage(report)
    badge_path.parent.mkdir(parents=True, exist_ok=True)
    badge_path.write_text(json.dumps(badge, indent=2) + "\n", encoding="utf-8")
    return badge


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: coverage_badge.py COVERAGE.json BADGE.json", file=sys.stderr)
        return 2
    badge = write_badge(Path(args[0]), Path(args[1]))
    print(badge["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
