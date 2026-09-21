"""Source lane routing and circuit breaker helpers."""

from __future__ import annotations

from paperful.circuit import CircuitBreaker
from paperful.routing import (
    SCIHUB_COVERAGE_THROUGH_YEAR,
    doi_from_biorxiv_url,
    ezproxy_target,
    filter_sources_for_item_types,
    filter_sources_for_year_scope,
    is_block_failure,
    is_cshl_doi,
    is_publisher_url,
    publisher_host,
    source_applicable,
    sources_for_item,
)
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
    assert source_applicable(make_item(doi="10.1000/x", year=2021), cfg, "scihub")
    assert not source_applicable(
        make_item(doi="10.1000/x", year=SCIHUB_COVERAGE_THROUGH_YEAR + 1), cfg, "scihub"
    )
    assert source_applicable(make_item(doi="10.1000/x", year=None), cfg, "scihub")
    cfg.core_api_key = "k"
    assert source_applicable(with_doi, cfg, "core")
    cfg.core_api_key = ""
    assert not source_applicable(with_doi, cfg, "core")
    web = make_item(
        key="W", doi=None, item_type="webpage", url="https://www.npr.org/story"
    )
    assert source_applicable(web, cfg, "htmlpdf")
    assert not source_applicable(with_doi, cfg, "htmlpdf")
    assert not source_applicable(
        make_item(doi=None, item_type="webpage", url="https://consensus.app/x"),
        cfg,
        "htmlpdf",
    )
    assert not source_applicable(
        make_item(doi=None, url="https://consensus.app/x"), cfg, "direct"
    )
    report = make_item(
        key="R",
        doi=None,
        item_type="report",
        url="https://undocs.org/en/A/CONF.232/2023/4",
    )
    assert source_applicable(report, cfg, "htmlpdf")
    assert source_applicable(report, cfg, "direct")
    no_url = make_item(
        key="S", doi=None, url=None, extra="A/AC.292/2024/1", title="PrepCom"
    )
    assert source_applicable(no_url, cfg, "direct")
    assert source_applicable(
        make_item(
            doi=None,
            url="https://www.youtube.com/watch?v=x",
            extra="A/CONF.232/2023/4",
        ),
        cfg,
        "direct",
    )
    assert not source_applicable(
        make_item(doi=None, url="https://www.youtube.com/watch?v=x"),
        cfg,
        "direct",
    )
    assert not source_applicable(
        make_item(
            key="RD",
            doi="10.1000/x",
            item_type="report",
            url="https://undocs.org/en/A/CONF.232/2023/4",
        ),
        cfg,
        "htmlpdf",
    )


def test_sources_for_item_preserves_config_order(cfg):
    item = make_item(doi="10.1000/x")
    cfg.email = "test@example.org"
    ordered = ["openalex", "unpaywall", "scihub", "direct"]
    assert sources_for_item(item, cfg, ordered) == [
        "openalex",
        "unpaywall",
        "scihub",
        "direct",
    ]


def test_filter_sources_for_item_types_drops_htmlpdf_on_journals():
    sources = ["unpaywall", "direct", "ezproxy", "htmlpdf", "scihub"]
    assert filter_sources_for_item_types(sources, None) == sources
    assert filter_sources_for_item_types(sources, frozenset()) == sources
    assert filter_sources_for_item_types(
        sources, frozenset({"journalArticle"})
    ) == ["unpaywall", "direct", "ezproxy", "scihub"]
    assert filter_sources_for_item_types(
        sources, frozenset({"journalArticle", "report"})
    ) == sources
    assert filter_sources_for_item_types(
        sources, frozenset({"webpage"})
    ) == sources


def test_filter_sources_for_year_scope_drops_scihub_past_coverage():
    sources = ["unpaywall", "ezproxy", "scihub"]
    assert filter_sources_for_year_scope(sources, None) == sources
    assert filter_sources_for_year_scope(sources, SCIHUB_COVERAGE_THROUGH_YEAR) == sources
    assert filter_sources_for_year_scope(sources, 2019) == sources
    assert filter_sources_for_year_scope(
        sources, SCIHUB_COVERAGE_THROUGH_YEAR + 1
    ) == ["unpaywall", "ezproxy"]
    assert filter_sources_for_year_scope(sources, 2023) == ["unpaywall", "ezproxy"]


def test_is_block_failure():
    assert is_block_failure(Outcome.CAPTCHA)
    assert is_block_failure(Outcome.ERROR, "scholar blocked/captcha")
    assert not is_block_failure(Outcome.ERROR, "HTTP 502")
    assert not is_block_failure(Outcome.NOT_FOUND)


def test_ezproxy_target_only_doi_or_publisher_host():
    doi = make_item(
        doi="10.1016/j.marpol.2025.106689", url="https://www.youtube.com/watch?v=x"
    )
    assert ezproxy_target(doi) == "https://doi.org/10.1016/j.marpol.2025.106689"

    sd = make_item(
        doi=None,
        url="https://www.sciencedirect.com/science/article/pii/S0308597X25000000",
    )
    assert ezproxy_target(sd) == sd.url

    doi_url = make_item(doi=None, url="https://doi.org/10.1038/nature12345")
    assert ezproxy_target(doi_url) == "https://doi.org/10.1038/nature12345"

    assert (
        ezproxy_target(
            make_item(doi=None, url="https://www.youtube.com/watch?v=Zv4vNEFf_qE")
        )
        is None
    )
    assert (
        ezproxy_target(make_item(doi=None, url="https://youtu.be/Zv4vNEFf_qE")) is None
    )
    assert ezproxy_target(make_item(doi=None, url="https://www.zotero.org/")) is None
    assert (
        ezproxy_target(
            make_item(
                doi=None,
                url="https://www.fao.org/in-action/vulnerable-marine-ecosystems/en/",
            )
        )
        is None
    )
    assert (
        ezproxy_target(
            make_item(
                doi=None, url="https://highseasalliance.org/2026/04/16/bbnj-prepcom-3/"
            )
        )
        is None
    )
    assert (
        ezproxy_target(
            make_item(
                doi=None,
                url="https://www.g77.org/statement/getstatement.php?id=260325c",
            )
        )
        is None
    )


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


def test_publisher_host_groups_rewritten_ezproxy_hosts():
    assert publisher_host(
        "https://www.sciencedirect.com/science/article/pii/S1/pdfft"
    ) == "sciencedirect.com"
    assert (
        publisher_host(
            "https://www-sciencedirect-com.scpo.idm.oclc.org/science/article/pii/S1/pdfft"
        )
        == "sciencedirect.com"
    )
    assert publisher_host("https://www.tandfonline.com/doi/pdf/10.1/x") == (
        "tandfonline.com"
    )
    assert is_publisher_url("https://linkinghub.elsevier.com/retrieve/pii/S1")
    assert not is_publisher_url("https://arxiv.org/pdf/1234.5678")
    assert not publisher_host("https://repository.example.edu/bitstream/1/a.pdf")


def test_biorxiv_doi_helpers_are_shared(cfg):
    assert is_cshl_doi("10.1101/2020.01.10.901900")
    assert not is_cshl_doi("10.1000/x")
    assert not is_cshl_doi(None)
    url = "https://www.biorxiv.org/content/10.1101/2020.01.10.901900v1"
    assert doi_from_biorxiv_url(url) == "10.1101/2020.01.10.901900"
    assert (
        doi_from_biorxiv_url(
            "https://www.medrxiv.org/content/10.1101/2020.03.09.20033217v2.full"
        )
        == "10.1101/2020.03.09.20033217"
    )
    assert doi_from_biorxiv_url("https://example.org/not-biorxiv") is None
    assert source_applicable(make_item(doi=None, url=url), cfg, "biorxiv")
    assert not source_applicable(
        make_item(doi="10.1000/x", url=None), cfg, "biorxiv"
    )


def test_browser_lane_failed_ignores_not_applicable():
    from paperful.routing import browser_lane_failed

    assert not browser_lane_failed(
        ["unpaywall:not_found", "scholar:skipped(not applicable)"]
    )
    assert browser_lane_failed(["scholar:not_found"])
    assert browser_lane_failed(["htmlpdf:skipped(circuit open)"])
    assert browser_lane_failed(["ezproxy:download-failed(HTTP 403)"])
    assert not browser_lane_failed(["unpaywall:not_found"])
    assert not browser_lane_failed([])


def test_with_recover_lane_inserts_after_last_browser_lane(cfg, monkeypatch):
    from paperful.routing import with_recover_lane

    monkeypatch.setattr(
        "paperful.browser_agent.browser_agent_extra_available", lambda: True
    )
    cfg.llm_enabled = True
    listed = ["unpaywall", "scholar", "htmlpdf", "scihub"]
    assert with_recover_lane(cfg, listed) == [
        "unpaywall",
        "scholar",
        "htmlpdf",
        "browser_agent",
        "scihub",
    ]
    assert with_recover_lane(cfg, listed)[0] == "unpaywall"
    cfg.llm_enabled = False
    assert "browser_agent" not in with_recover_lane(cfg, listed)
    cfg.llm_enabled = True
    cfg.browser_agent_during_run = False
    assert "browser_agent" not in with_recover_lane(cfg, listed)
    cfg.browser_agent_during_run = True
    assert with_recover_lane(cfg, ["unpaywall", "scihub"]) == ["unpaywall", "scihub"]
    already = ["scholar", "browser_agent"]
    assert with_recover_lane(cfg, already) == already
    monkeypatch.setattr(
        "paperful.browser_agent.browser_agent_extra_available", lambda: False
    )
    assert "browser_agent" not in with_recover_lane(
        cfg, ["unpaywall", "scholar", "htmlpdf"]
    )
