"""Launch share card: logo card is 1200×630 and is the live og:image."""

from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OG = ROOT / "website" / "images" / "og.png"
INDEX = ROOT / "website" / "index.html"


def test_og_png_is_1200x630():
    data = OG.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (1200, 630)


def test_homepage_share_card_uses_og_png():
    text = INDEX.read_text(encoding="utf-8")
    assert 'content="https://paperful.app/images/og.png"' in text
    assert "images/og-v2.png" not in text
    assert "Paperful logo: a cardboard box of papers" in text
