"""Helpers for asserting against CLI stdout."""

from __future__ import annotations

import re

# Click/Rich help styles option names as bold segments around each "-", so
# "--dry-run" never appears as a contiguous substring when color is on.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def plain_text(text: str) -> str:
    """Strip ANSI SGR codes from CLI stdout for token assertions."""
    return _ANSI_ESCAPE.sub("", text)
