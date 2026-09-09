import base64
import hashlib
import json
from pathlib import Path

from scihub_dl.sources.base import Outcome
from scihub_dl.sources.scihub import extract_altcha_urls, is_captcha_page, parse_page, solve_altcha

FIX = Path(__file__).parent / "fixtures"
BASE = "https://sci-hub.ru/10.1016/j.marpol.2017.05.011"


def test_parse_found_page_gives_absolute_pdf_url():
    res = parse_page((FIX / "scihub_found.html").read_text(), BASE)
    assert res.outcome is Outcome.FOUND
    assert res.pdf_url == "https://sci-hub.ru/storage/zero/6364/41ab8ffb30f3383b52e955640fd17dc4/ding2017.pdf"


def test_parse_not_found_page():
    res = parse_page((FIX / "scihub_not_found.html").read_text(), BASE)
    assert res.outcome is Outcome.NOT_FOUND


def test_parse_captcha_page():
    html = (FIX / "scihub_captcha.html").read_text()
    assert is_captcha_page(html)
    assert parse_page(html, BASE).outcome is Outcome.CAPTCHA
    assert extract_altcha_urls(html) == ("/captcha/challenge/91226685", "/captcha/solution/91226685")


def test_parse_legacy_embed_layout():
    html = '<html><body><div id="article"><embed id="pdf" src="//moscow.sci-hub.ru/1/abc.pdf#navpanes=0"></div>' \
           '<button onclick="location.href=\'//moscow.sci-hub.ru/1/abc.pdf?download=true\'">save</button></body></html>'
    res = parse_page(html, BASE)
    assert res.outcome is Outcome.FOUND
    assert res.pdf_url == "https://moscow.sci-hub.ru/1/abc.pdf"


def test_parse_unknown_layout_is_error_not_not_found():
    res = parse_page("<html><head><title>Sci-Hub</title></head><body>hello</body></html>", BASE)
    assert res.outcome is Outcome.ERROR


def test_solve_altcha_roundtrip():
    salt, number = "abc?expires=1&", 4242
    challenge = {
        "algorithm": "SHA-256",
        "salt": salt,
        "challenge": hashlib.sha256(f"{salt}{number}".encode()).hexdigest(),
        "maxNumber": 10000,
        "signature": "sig",
    }
    payload = json.loads(base64.b64decode(solve_altcha(challenge)))
    assert payload["number"] == number
    assert payload["salt"] == salt and payload["signature"] == "sig"


def test_parse_not_in_database_layout():
    res = parse_page((FIX / "scihub_not_in_db.html").read_text(), "https://sci-hub.ru/10.18623/rvd.v14i28.1038")
    assert res.outcome is Outcome.NOT_FOUND
