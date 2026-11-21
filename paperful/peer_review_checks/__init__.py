"""Deterministic checkers for ``paperful critique``."""

from .biblio import _crossref_work
from .floats import _float_kind, _glossary_acronyms
from .run import run_checks

__all__ = [
    "run_checks",
    "_crossref_work",
    "_float_kind",
    "_glossary_acronyms",
]
