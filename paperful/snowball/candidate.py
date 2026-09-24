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
    keep: bool | None = None
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
        if row.get("keep") is None:
            row.pop("keep", None)
        return row

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Candidate:
        return cls(
            run_id=str(raw.get("run_id") or ""),
            seed=dict(raw.get("seed") or {}),
            hop=int(raw.get("hop") or 0),
            direction=str(raw.get("direction") or ""),
            ids=dict(raw.get("ids") or {}),
            biblio=dict(raw.get("biblio") or {}),
            why=str(raw.get("why") or ""),
            status=str(raw.get("status") or "new"),
            provenance=dict(raw.get("provenance") or {}),
            gate=str(raw.get("gate") or ""),
            score=float(raw.get("score") or 0),
            exists_match=raw.get("exists_match"),
            keep=raw.get("keep"),
            schema=str(raw.get("schema") or SCHEMA),
        )
