"""Web grey search: SearXNG query → ranked PDF/landing candidates."""

from __future__ import annotations

from .rank import build_query, fanout_queries, parse_hosts, score_hit
from .run import run_search
from .store import (
    HIT_KEYS,
    META_KEYS,
    SCHEMA,
    SUMMARY_KEYS,
    SearchError,
    list_runs,
    load_run,
    new_run_id,
    run_dir,
    search_root,
    write_run,
)

__all__ = [
    "HIT_KEYS",
    "META_KEYS",
    "SCHEMA",
    "SUMMARY_KEYS",
    "SearchError",
    "build_query",
    "fanout_queries",
    "list_runs",
    "load_run",
    "new_run_id",
    "parse_hosts",
    "run_dir",
    "run_search",
    "score_hit",
    "search_root",
    "write_run",
]
