"""Workbench status icons cover frozen miss-surface and verification enums."""

from __future__ import annotations

from pathlib import Path

from paperful.miss_surface import MISS_SURFACE_PLAIN
from paperful.ui.verify import VERIFICATION_PLAIN


def test_status_icon_template_covers_all_codes():
    text = Path("paperful/ui/templates/_miss_surface.html").read_text(encoding="utf-8")
    for code in MISS_SURFACE_PLAIN:
        assert f"'{code}'" in text, f"miss-surface code {code!r} has no icon branch"
    for code in VERIFICATION_PLAIN:
        assert f"'{code}'" in text, f"verification code {code!r} has no icon branch"
