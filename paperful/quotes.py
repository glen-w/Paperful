"""Publisher prices the browser agent reads off a paywall.

One article, one price. A journal subscription on the same page is not the
price of the PDF.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_AMOUNT = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2}"
_PRICE_RE = re.compile(
    rf"(?:(?P<pre>US\$|€|£|\$)\s*(?P<num1>{_AMOUNT})(?!\d)"
    rf"|(?P<num2>{_AMOUNT})(?!\d)\s*(?P<post>€|£|\$|\b(?:EUR|USD|GBP|CHF)\b))",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"\bprice (\d+\.\d{2}) ([A-Z]{3})\b")
_CODES = {
    "€": "EUR",
    "$": "USD",
    "us$": "USD",
    "£": "GBP",
    "eur": "EUR",
    "usd": "USD",
    "gbp": "GBP",
    "chf": "CHF",
}
_ARTICLE = ("pdf", "article", "buy", "purchase")
_SUBSCRIPTION = ("subscri", "institutional", "annual", "membership")
# A single article PDF is not a four-figure institutional package.
_MAX = Decimal("2000")


def price_token(amount: Decimal, currency: str) -> str:
    """Stable note fragment, for example ``price 39.95 EUR``."""
    return f"price {amount:.2f} {currency}"


def price_token_in(text: str) -> tuple[Decimal, str] | None:
    """Read a ``price 39.95 EUR`` token, if the text has one."""
    match = _TOKEN_RE.search(text)
    if match is None:
        return None
    return Decimal(match.group(1)), match.group(2)


def quoted_price(text: str) -> tuple[Decimal, str] | None:
    """Best single-article price in ``text``, or None.

    Requires a nearby buy/PDF/article cue. ``39,95 €`` and ``$39.95`` both
    match. A DOI like ``10.1007`` does not.
    """
    best: tuple[int, int, Decimal, str] | None = None
    for match in _PRICE_RE.finditer(text):
        raw = match.group("num1") or match.group("num2")
        symbol = (match.group("pre") or match.group("post") or "").lower()
        currency = _CODES.get(symbol)
        if not raw or not currency:
            continue
        amount = _parse_amount(raw)
        if amount is None or amount > _MAX:
            continue
        window = text[max(0, match.start() - 60) : match.end() + 40].lower()
        score = _article_score(window)
        if score <= 0:
            continue
        # Higher score wins. An earlier match wins a tie.
        if best is None or score > best[0]:
            best = (score, match.start(), amount, currency)
    if best is None:
        return None
    return best[2], best[3]


def _article_score(window: str) -> int:
    """Positive when the amount looks like an article price."""
    article = any(word in window for word in _ARTICLE)
    if not article:
        return 0
    subscription = any(word in window for word in _SUBSCRIPTION)
    pdf_or_buy = any(word in window for word in ("pdf", "buy", "purchase"))
    if subscription and not pdf_or_buy:
        return 0
    score = 0
    if "pdf" in window:
        score += 3
    if "buy" in window or "purchase" in window:
        score += 2
    if "article" in window:
        score += 1
    return score


def _parse_amount(raw: str) -> Decimal | None:
    """``39,95`` and ``1.234,56`` and ``1,234.56`` to a two-decimal amount."""
    text = raw.strip()
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))
