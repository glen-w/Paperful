"""PDF-location sources. Each exposes `find(item, ctx) -> Candidate | None` (or a Result for Sci-Hub)."""

from __future__ import annotations

from . import (
    arxiv,
    biorxiv,
    core,
    direct,
    europepmc,
    ezproxy,
    htmlpdf,
    openalex,
    scholar,
    scihub,
    semanticscholar,
    unpaywall,
)
from .base import Candidate, Context, Outcome, Source

REGISTRY: dict[str, Source] = {
    "unpaywall": unpaywall,
    "openalex": openalex,
    "arxiv": arxiv,
    "biorxiv": biorxiv,
    "europepmc": europepmc,
    "semanticscholar": semanticscholar,
    "core": core,
    "scholar": scholar,
    "direct": direct,
    "ezproxy": ezproxy,
    "htmlpdf": htmlpdf,
    "scihub": scihub,
}

__all__ = ["Candidate", "Context", "Outcome", "Source", "REGISTRY"]
