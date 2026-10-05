"""Late Scholar tail: policy order, SerpApi helpers, handoff Scholar URLs."""

from __future__ import annotations

from paperful.config import Config, load_config
from paperful.handoff import HINT_DOI, HINT_OPENABLE, MissingPdf, handoff_targets, open_tabs
from paperful.routing import (
    SerialStep,
    order_run,
    with_recover_lane,
    with_serpapi_lane,
)
from paperful.sources.base import Outcome
from paperful.sources.serpapi_scholar import extract_pdf_links, find as serpapi_find
from tests.conftest import make_item


def test_policy_moves_early_scholar_after_campus(cfg):
    from paperful.routing import apply_fetch_order

    item = make_item(doi="10.1000/x")
    lanes = apply_fetch_order(
        cfg,
        ["scholar", "unpaywall", "ezproxy", "htmlpdf", "scihub"],
        item,
    )
    assert lanes[0] == "unpaywall"
    assert lanes.index("ezproxy") < lanes.index("scholar")
    assert lanes[-1] == "scihub"


def test_order_run_policy_interleaves_when_agent_present(cfg):
    steps = order_run(
        cfg, ["ezproxy", "scholar", "htmlpdf", "browser_agent", "scihub"]
    )
    assert steps[0] == SerialStep("ezproxy")
    assert SerialStep("scholar", partner="browser_agent") in steps
    assert steps[-1] == SerialStep("scihub")
    names = [s.name for s in steps]
    assert names.index("ezproxy") < names.index("scholar")


def test_order_run_phase_keeps_separate_scholar_and_agent(cfg):
    cfg.scholar_when = "phase"
    steps = order_run(cfg, ["scholar", "browser_agent", "scihub"])
    assert steps == [
        SerialStep("scholar"),
        SerialStep("browser_agent"),
        SerialStep("scihub"),
    ]


def test_order_run_list_keeps_with_recover_insert(cfg, monkeypatch):
    monkeypatch.setattr(
        "paperful.browser_agent.browser_agent_extra_available", lambda: True
    )
    cfg.fetch_order = "list"
    cfg.llm_enabled = True
    listed = with_recover_lane(cfg, ["unpaywall", "scholar", "htmlpdf", "scihub"])
    assert listed == [
        "unpaywall",
        "scholar",
        "htmlpdf",
        "browser_agent",
        "scihub",
    ]
    steps = order_run(cfg, listed)
    assert [s.name for s in steps] == ["scholar", "htmlpdf", "browser_agent", "scihub"]


def test_with_serpapi_lane_policy_inserts_before_scihub(cfg, monkeypatch):
    cfg.serpapi_enabled = True
    monkeypatch.setenv("SERPAPI_API_KEY", "sk-test")
    listed = with_serpapi_lane(cfg, ["unpaywall", "ezproxy", "scihub"])
    assert listed == ["unpaywall", "ezproxy", "serpapi", "scihub"]
    monkeypatch.delenv("SERPAPI_API_KEY")
    assert "serpapi" not in with_serpapi_lane(cfg, listed)


def test_with_serpapi_lane_list_mode_keeps_array_slot(cfg, monkeypatch):
    cfg.fetch_order = "list"
    cfg.serpapi_enabled = True
    monkeypatch.setenv("SERPAPI_API_KEY", "sk-test")
    assert with_serpapi_lane(cfg, ["unpaywall", "scihub"]) == ["unpaywall", "scihub"]
    assert with_serpapi_lane(cfg, ["unpaywall", "serpapi", "scihub"]) == [
        "unpaywall",
        "serpapi",
        "scihub",
    ]


def test_serpapi_extracts_organic_pdf_resources():
    pdfs = extract_pdf_links(
        {
            "organic_results": [
                {
                    "link": "https://publisher.test/abs",
                    "resources": [
                        {
                            "file_format": "PDF",
                            "link": "https://repo.test/a.pdf",
                        }
                    ],
                }
            ]
        }
    )
    assert pdfs == ["https://repo.test/a.pdf"]


def test_serpapi_find_quota_is_error(ctx_factory, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "sk-test")

    def handler(req):
        import httpx

        return httpx.Response(200, json={"error": "Your account has run out of searches."})

    cand = serpapi_find(make_item(), ctx_factory(handler))
    assert cand.outcome is Outcome.ERROR
    assert cand.note == "quota"


def test_handoff_scholar_url_on_doi_miss(cfg):
    item = make_item(key="D", doi="10.1000/x", has_pdf=False, url="")
    from paperful.handoff import list_missing_pdfs

    rows = list_missing_pdfs([item], cfg=cfg)
    assert rows[0].hint == HINT_DOI
    assert "scholar.google.com" in rows[0].scholar_url
    assert "10.1000" in rows[0].scholar_url
    opened: list[str] = []
    n = open_tabs(rows, scholar=True, opener=lambda u: opened.append(u) or True)
    assert n == 1
    assert opened[0] == rows[0].scholar_url


def test_handoff_does_not_replace_openable_pdf(cfg):
    row = MissingPdf(
        key="P",
        title="Paper",
        doi="10.1000/x",
        url="https://journals.test/downloadpdf/x.pdf",
        hint=HINT_OPENABLE,
        attempts=[],
        scholar_url="https://scholar.google.com/scholar?q=nope",
    )
    targets = handoff_targets([row], scholar=True)
    assert targets == [row]
    opened: list[str] = []
    open_tabs([row], scholar=True, opener=lambda u: opened.append(u) or True)
    assert opened == ["https://journals.test/downloadpdf/x.pdf"]


def test_load_fetch_scholar_serpapi_handoff(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
email = "me@example.org"
[fetch]
order = "list"
[scholar]
when = "phase"
[serpapi]
enabled = true
max_calls = 7
[handoff]
scholar = false
"""
    )
    cfg = load_config(p)
    assert cfg.fetch_order == "list"
    assert cfg.scholar_when == "phase"
    assert cfg.serpapi_enabled is True
    assert cfg.serpapi_max_calls == 7
    assert cfg.handoff_scholar is False


def test_config_defaults_are_policy_auto_scholar_handoff():
    cfg = Config()
    assert cfg.fetch_order == "policy"
    assert cfg.scholar_when == "auto"
    assert cfg.serpapi_enabled is False
    assert cfg.serpapi_max_calls == 20
    assert cfg.handoff_scholar is True
