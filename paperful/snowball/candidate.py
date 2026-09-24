"""Candidate rows for one snowball run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SCHEMA = "paperful.snowball.candidate.v1"


@dataclass
class Candidate:
    run_id: str
    seed: dict[str, str]
    hop: int
    direction: str
    ids: dict[str, str]
    biblio: dict[str, Any]
    why: str
    status: str
    provenance: dict[str, str]
    gate: str
    score: float = 0.0
    exists_match: dict[str, str] | None = None
    schema: str = SCHEMA

    @property
    def identity(self) -> str:
        doi = (self.ids.get("doi") or "").lower()
        if doi:
            return f"doi:{doi}"
        oa = self.ids.get("openalex") or ""
        return f"openalex:{oa}" if oa else ""

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        if not row.get("exists_match"):
            row.pop("exists_match", None)
        return row
