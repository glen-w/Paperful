"""Launch share card: Wanted heading stays in the 1200×630 crop."""

from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OG = ROOT / "website" / "images" / "og-v2.png"
INDEX = ROOT / "website" / "index.html"


def test_og_v2_is_1200x630():
    data = OG.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (1200, 630)


def test_homepage_share_card_uses_og_v2():
    text = INDEX.read_text(encoding="utf-8")
    assert "images/og-v2.png" in text
    assert 'content="https://paperful.app/images/og.png"' not in text
