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
    operator: dict[str, Any] | None = None
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
        if not row.get("operator"):
            row.pop("operator", None)
        return row

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Candidate:
        # Live rows nest title/DOI. Older queue files used top-level keys;
        # fold those in so Keep, apply, and the Discover table agree.
        ids = dict(raw.get("ids") or {})
        legacy_doi = str(raw.get("doi") or "").strip()
        if legacy_doi and not str(ids.get("doi") or "").strip():
            ids["doi"] = legacy_doi
        biblio = dict(raw.get("biblio") or {})
        legacy_title = str(raw.get("title") or "").strip()
        if legacy_title and not str(biblio.get("title") or "").strip():
            biblio["title"] = legacy_title
        operator = raw.get("operator")
        if not isinstance(operator, dict):
            # Older staging lived under biblio.operator.
            nested = biblio.get("operator")
            operator = nested if isinstance(nested, dict) else None
        return cls(
            run_id=str(raw.get("run_id") or ""),
            seed=dict(raw.get("seed") or {}),
            hop=int(raw.get("hop") or 0),
            direction=str(raw.get("direction") or ""),
            ids=ids,
            biblio=biblio,
            why=str(raw.get("why") or ""),
            status=str(raw.get("status") or "new"),
            provenance=dict(raw.get("provenance") or {}),
            gate=str(raw.get("gate") or ""),
            score=float(raw.get("score") or 0),
            exists_match=raw.get("exists_match"),
            keep=raw.get("keep"),
            operator=dict(operator) if operator else None,
            schema=str(raw.get("schema") or SCHEMA),
        )
