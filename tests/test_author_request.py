"""ResearchGate request handoff (operator clicks; no vault automation)."""

from __future__ import annotations

from paperful.author_request import (
    already_requested,
    record_request,
    researchgate_publication_url,
    rg_handoff_enabled,
)
from paperful.config import Config, load_config
from paperful.handoff import (
    HINT_AUTHOR_REQUEST,
    HINT_DOI,
    HINT_OPENABLE,
    list_missing_pdfs,
    missing_from_run_outcomes,
    open_tabs,
)
from tests.conftest import make_item

RG = "https://www.researchgate.net/publication/123456789_A_Paper"


def test_defaults_leave_request_and_twenty_off():
    cfg = Config()
    assert cfg.request_channels == "off"
    assert rg_handoff_enabled(cfg) is False
    assert cfg.twenty_enabled is False


def test_load_request_and_twenty(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
email = "me@example.org"
[request]
channels = "rg"
email_after_days = 21
[twenty]
enabled = true
base_url = "https://api.twenty.com"
lookup_on_preflight = true
"""
    )
    cfg = load_config(p)
    assert cfg.request_channels == "rg"
    assert cfg.request_email_after_days == 21
    assert rg_handoff_enabled(cfg) is True
    assert cfg.twenty_enabled is True
    assert cfg.twenty_base_url == "https://api.twenty.com"
    assert cfg.twenty_lookup_on_preflight is True


def test_cli_override_forces_rg_on_off(cfg):
    from paperful.author_request import apply_request_rg_override

    apply_request_rg_override(cfg, True)
    assert rg_handoff_enabled(cfg) is True
    apply_request_rg_override(cfg, False)
    cfg.request_channels = "rg"
    assert rg_handoff_enabled(cfg) is False


def test_researchgate_url_from_item_and_extra():
    item = make_item(url=RG, has_pdf=False)
    assert researchgate_publication_url(item) == RG
    other = make_item(
        url="https://doi.org/10.1/x",
        extra=f"See {RG} for the manuscript",
        has_pdf=False,
    )
    assert researchgate_publication_url(other) == RG
    profile = make_item(
        url="https://www.researchgate.net/profile/Ada-Lovelace",
        has_pdf=False,
    )
    assert researchgate_publication_url(profile) == ""


def test_handoff_rg_when_enabled(cfg):
    cfg.request_channels = "rg"
    item = make_item(key="RG000001", url=RG, has_pdf=False, doi="10.1/x")
    rows = list_missing_pdfs([item], cfg=cfg)
    assert len(rows) == 1
    assert rows[0].hint == HINT_AUTHOR_REQUEST
    assert rows[0].request_url == RG
    opened: list[str] = []
    n = open_tabs(rows, scholar=False, opener=lambda u: opened.append(u) or True, cfg=cfg)
    assert n == 1 and opened == [RG]
    assert already_requested(cfg, "RG000001")


def test_handoff_skips_ledgered_unless_re_request(cfg):
    cfg.request_channels = "rg"
    item = make_item(key="RG000002", url=RG, has_pdf=False, doi="10.1/x")
    record_request(cfg, key="RG000002", url=RG, doi="10.1/x", title=item.title)
    rows = list_missing_pdfs([item], cfg=cfg)
    assert rows[0].hint == HINT_DOI
    assert rows[0].request_url == ""
    again = list_missing_pdfs([item], cfg=cfg, re_request=True)
    assert again[0].hint == HINT_AUTHOR_REQUEST


def test_handoff_without_config_or_rg_url_unchanged(cfg):
    item = make_item(key="NO000001", url="https://example.org/article", has_pdf=False)
    rows = list_missing_pdfs([item], cfg=cfg)
    assert rows[0].hint != HINT_AUTHOR_REQUEST
    cfg.request_channels = "rg"
    rows = list_missing_pdfs([item], cfg=cfg)
    assert rows[0].request_url == ""


def test_openable_pdf_beats_rg(cfg):
    cfg.request_channels = "rg"
    item = make_item(
        key="PDF00001",
        url="https://example.org/a.pdf",
        extra=RG,
        has_pdf=False,
    )
    rows = list_missing_pdfs([item], cfg=cfg)
    assert rows[0].hint == HINT_OPENABLE
    opened: list[str] = []
    open_tabs(rows, opener=lambda u: opened.append(u) or True, cfg=cfg)
    assert opened == ["https://example.org/a.pdf"]


def test_missing_from_run_keeps_rg_without_scholar(cfg):
    cfg.request_channels = "rg"
    cfg.handoff_scholar = False
    item = make_item(key="RG000003", url=RG, has_pdf=False, doi="10.1/x")
    rows = missing_from_run_outcomes(
        {item.key: item},
        [
            {
                "itemKey": item.key,
                "status": "not_found",
                "reason": "closed",
                "attempts": ["unpaywall:not_found"],
            }
        ],
        cfg=cfg,
    )
    assert len(rows) == 1
    assert rows[0].hint == HINT_AUTHOR_REQUEST
