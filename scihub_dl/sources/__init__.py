"""PDF-location sources. Each exposes `find(item, ctx) -> Candidate | None` (or a Result for Sci-Hub)."""

from __future__ import annotations

from .base import Candidate, Context, Outcome, Source
from . import arxiv, direct, ezproxy, openalex, scholar, scihub, semanticscholar, unpaywall

REGISTRY: dict[str, Source] = {
    "unpaywall": unpaywall,
    "openalex": openalex,
    "arxiv": arxiv,
    "semanticscholar": semanticscholar,
    "scholar": scholar,
    "direct": direct,
    "ezproxy": ezproxy,
    "scihub": scihub,
}

__all__ = ["Candidate", "Context", "Outcome", "Source", "REGISTRY"]
