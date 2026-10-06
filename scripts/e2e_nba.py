#!/usr/bin/env python3
"""CLI entry for the NBA all-in E2E harness. Prefer: make e2e-nba"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paperful.e2e_nba import main

if __name__ == "__main__":
    raise SystemExit(main())
