"""Publisher prices read off a browser-agent paywall."""

from decimal import Decimal

from paperful.quotes import quoted_price


def test_quoted_price_prefers_the_pdf_over_a_subscription():
    text = (
        'Clicked button "Buy article PDF 39,95 €". '
        "Journal subscription 199,00 €. DOI 10.1007/s11276."
    )
    assert quoted_price(text) == (Decimal("39.95"), "EUR")


def test_quoted_price_reads_dollar_and_grouped_euro():
    assert quoted_price("Buy this article PDF for $29.95") == (
        Decimal("29.95"),
        "USD",
    )
    assert quoted_price("Purchase PDF 1.234,56 €") == (Decimal("1234.56"), "EUR")


def test_quoted_price_ignores_a_subscription_and_a_doi():
    assert quoted_price("Subscribe annually for 199,00 €") is None
    assert quoted_price("Opened https://doi.org/10.1007/s11276-023-03567-3") is None
