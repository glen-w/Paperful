"""Synthetic-library scale benchmark (offline, deterministic).

Builds a fake mirror of N items on disk and times the read paths operators
feel at 22k-item scale: scope listing, gaps counting, and lint over a
sample. No network, no Zotero. Used as a regression budget, not a profiler:

    uv run python scripts/bench_synthetic.py --sizes 1000,10000 --sample 200

Budgets live in tests/test_bench_synthetic.py (smoke size only); the full
sizes are run manually / in the nightly job and compared by eye.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_mirror(root: Path, count: int) -> Path:
    """Write ``count`` minimal item folders shaped like the quiet mirror."""
    out = root / "out"
    for i in range(count):
        folder = out / "Synthetic" / f"Paper {i} -- KEY{i:06d}"
        folder.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "paperful.item.v1",
            "key": f"KEY{i:06d}",
            "title": f"Paper {i}",
            "doi": f"10.1000/synth.{i}",
            "year": 2000 + i % 25,
            "item_type": "journalArticle",
            "collections": ["Synthetic"],
            "attachments": [],
        }
        (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")
    return out


def count_records(out: Path) -> int:
    """Gaps-shaped walk: how many item records the mirror holds."""
    return sum(1 for _ in out.rglob("record.json"))


def over_budget(current: float, baseline: float, *, limit: float = 0.10) -> bool:
    """True when ``current`` is more than ``limit`` above ``baseline``."""
    if baseline <= 0:
        return False
    return current > baseline * (1.0 + limit)


def timeit(label: str, fn) -> dict:
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return {"label": label, "seconds": round(elapsed, 3), "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="1000,10000")
    parser.add_argument("--root", type=Path, default=Path("/tmp/paperful-bench"))
    args = parser.parse_args()

    from paperful.mirror import MirrorIndex

    rows = []
    for size in [int(s) for s in args.sizes.split(",") if s.strip()]:
        root = args.root / str(size)
        build_mirror(root, size)
        out = root / "out"
        rows.append(
            timeit(
                f"MirrorIndex.scan[{size}]",
                lambda out=out: len(MirrorIndex.scan(out).keys()),
            )
        )
        rows.append(
            timeit(
                f"gaps.count[{size}]",
                lambda out=out: count_records(out),
            )
        )
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
