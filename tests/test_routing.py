"""Source lane routing and circuit breaker helpers."""

from __future__ import annotations

from paperful.circuit import CircuitBreaker
from paperful.routing import ezproxy_target, is_block_failure, source_applicable, sources_for_item
from paperful.sources.base import Outcome
from tests.conftest import make_item


def test_source_applicable_by_metadata(cfg):
    with_doi = make_item(doi="10.1000/x")
    no_doi = make_item(key="N", doi=None, url="https://www.npr.org/story")
    assert source_applicable(with_doi, cfg, "unpaywall")
    assert not source_applicable(no_doi, cfg, "unpaywall")
    assert source_applicable(no_doi, cfg, "direct")
    assert not source_applicable(no_doi, cfg, "scihub")
    assert source_applicable(with_doi, cfg, "scihub")
    web = make_item(key="W", doi=None, item_type="webpage", url="https://www.npr.org/story")
    assert source_applicable(web, cfg, "htmlpdf")
    assert not source_applicable(with_doi, cfg, "htmlpdf")
    assert not source_applicable(make_item(doi=None, item_type="webpage", url="https://consensus.app/x"), cfg, "htmlpdf")
    assert not source_applicable(make_item(doi=None, url="https://consensus.app/x"), cfg, "direct")


def test_sources_for_item_preserves_config_order(cfg):
    item = make_item(doi="10.1000/x")
    cfg.email = "test@example.org"
    ordered = ["openalex", "unpaywall", "scihub", "direct"]
    assert sources_for_item(item, cfg, ordered) == ["openalex", "unpaywall", "scihub", "direct"]


def test_is_block_failure():
    assert is_block_failure(Outcome.CAPTCHA)
    assert is_block_failure(Outcome.ERROR, "scholar blocked/captcha")
    assert not is_block_failure(Outcome.ERROR, "HTTP 502")
    assert not is_block_failure(Outcome.NOT_FOUND)


def test_ezproxy_target_only_doi_or_publisher_host():
    doi = make_item(doi="10.1016/j.marpol.2025.106689", url="https://www.youtube.com/watch?v=x")
    assert ezproxy_target(doi) == "https://doi.org/10.1016/j.marpol.2025.106689"

    sd = make_item(doi=None, url="https://www.sciencedirect.com/science/article/pii/S0308597X25000000")
    assert ezproxy_target(sd) == sd.url

    doi_url = make_item(doi=None, url="https://doi.org/10.1038/nature12345")
    assert ezproxy_target(doi_url) == "https://doi.org/10.1038/nature12345"

    assert ezproxy_target(make_item(doi=None, url="https://www.youtube.com/watch?v=Zv4vNEFf_qE")) is None
    assert ezproxy_target(make_item(doi=None, url="https://youtu.be/Zv4vNEFf_qE")) is None
    assert ezproxy_target(make_item(doi=None, url="https://www.zotero.org/")) is None
    assert ezproxy_target(make_item(doi=None, url="https://www.fao.org/in-action/vulnerable-marine-ecosystems/en/")) is None
    assert ezproxy_target(make_item(doi=None, url="https://highseasalliance.org/2026/04/16/bbnj-prepcom-3/")) is None
    assert ezproxy_target(make_item(doi=None, url="https://www.g77.org/statement/getstatement.php?id=260325c")) is None


def test_ezproxy_applicable_needs_cookies_and_publisher_target(cfg, tmp_path):
    cfg.ezproxy_base = "https://scpo.idm.oclc.org/login?url="
    cookies = tmp_path / "ezproxy-cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    cfg.ezproxy_cookies = cookies
    yt = make_item(doi=None, url="https://www.youtube.com/watch?v=CCK17L07V7k")
    sd = make_item(doi=None, url="https://www.sciencedirect.com/science/article/pii/S1")
    assert not source_applicable(yt, cfg, "ezproxy")
    assert source_applicable(sd, cfg, "ezproxy")
    assert source_applicable(make_item(doi="10.1000/x"), cfg, "ezproxy")


def test_circuit_breaker_trips_after_threshold():
    cb = CircuitBreaker(3)
    for _ in range(2):
        assert not cb.note("scholar", Outcome.CAPTCHA, "blocked")
        assert not cb.tripped("scholar")
    assert cb.note("scholar", Outcome.CAPTCHA, "blocked")
    assert cb.tripped("scholar")
