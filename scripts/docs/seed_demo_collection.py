#!/usr/bin/env python3
"""Seed a public-safe Zotero collection for workbench screenshots.

Needs Zotero open (local API), Unpaywall email in config.toml, and network.
Ask needs ``[llm]`` enabled. Does not opt in Sci-Hub or Scholar.

    uv run python scripts/docs/seed_demo_collection.py
    PAPERFUL_SHOT_COLLECTION="ocean/BBNJ" \\
      uv run python scripts/docs/seed_demo_collection.py

Public shots default to ``ocean/BBNJ``. If that collection already has
enough parents, snowball and ``run`` are skipped so production is not
mutated; ingest and Ask still run.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLECTION = os.environ.get("PAPERFUL_SHOT_COLLECTION", "ocean/BBNJ")
DEFAULT_QUERY = os.environ.get("PAPERFUL_SHOT_TOPIC", "BBNJ Agreement")
DEFAULT_ASK = os.environ.get(
    "PAPERFUL_SHOT_ASK", "What does the BBNJ Agreement require for EIAs?"
)
MIN_PARENTS = 20


def _paperful(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["uv", "run", "paperful", *args]
    print("+", " ".join(cmd[2:]), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def _parent_count(blob: str, collection: str) -> int | None:
    """Best-effort item count from ``collections list`` text."""
    needle = collection.split("/")[-1]
    for line in blob.splitlines():
        if needle not in line:
            continue
        digits = [int(tok) for tok in line.replace(",", " ").split() if tok.isdigit()]
        if digits:
            return digits[0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", "-C", default=DEFAULT_COLLECTION)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--ask", default=DEFAULT_ASK)
    parser.add_argument("--max-candidates", type=int, default=30)
    parser.add_argument("--year-from", type=int, default=2015)
    parser.add_argument("--skip-ask", action="store_true")
    args = parser.parse_args()
    collection = args.collection

    doctor = _paperful("doctor", check=False)
    if doctor.returncode != 0:
        print("doctor is not green. Open Zotero and set email in config.toml.", file=sys.stderr)
        raise SystemExit(doctor.returncode or 1)

    listed = _paperful("collections", "list", check=False)
    blob = (listed.stdout or "") + (listed.stderr or "")
    n = _parent_count(blob, collection)
    have_enough = n is not None and n >= MIN_PARENTS

    if have_enough:
        print(f"skip snowball and run: {collection} already has ~{n} items")
    else:
        _paperful(
            "snowball",
            "search",
            args.query,
            "--gate",
            "auto",
            "-C",
            collection,
            "--fetch-pdfs",
            "off",
            "--depth",
            "0",
            "--max-candidates",
            str(args.max_candidates),
            "--year-from",
            str(args.year_from),
            "--no-author-site-preflight",
            "--no-refine",
        )
        # Have: a few OA PDFs attached (Zotero 10+).
        _paperful(
            "run",
            "-C",
            collection,
            "--preset",
            "oa",
            "--limit",
            "5",
            "--no-browser-agent",
            check=False,
        )
        # Held: downloaded to out/, not attached.
        _paperful(
            "run",
            "-C",
            collection,
            "--preset",
            "oa",
            "--limit",
            "5",
            "--no-attach",
            "--no-browser-agent",
            check=False,
        )

    ingest = _paperful("rag", "ingest", "-C", collection, check=False)
    if ingest.returncode != 0:
        print("rag ingest failed (need PDFs on disk).", file=sys.stderr)

    if not args.skip_ask:
        ask = _paperful(
            "ask",
            args.ask,
            "-C",
            collection,
            "--thread",
            "new",
            check=False,
        )
        if ask.returncode != 0:
            print(
                "ask failed. Enable [llm] for the Ask screenshot, or re-run with --skip-ask.",
                file=sys.stderr,
            )
            raise SystemExit(ask.returncode or 1)

    listed = _paperful("collections", "list", check=False)
    print("---")
    print(f"collection: {collection}")
    print("next: workbench up, then uv run python scripts/docs/capture_workbench.py")


if __name__ == "__main__":
    main()
