"""Grey-lit playbook pack load, merge, and custom user rules."""

from __future__ import annotations

from paperful.config import load_config
from paperful.playbooks import (
    GreyPlaybook,
    apply_rewrite,
    apply_synthesize,
    load_builtin_pack,
    merge_playbooks,
)
from paperful.sources.landing import (
    extract_pdf_urls,
    grey_target,
    rewrite_known_pdf_url,
)
from tests.conftest import make_item

_NAMED_PACKS = (
    "undocs-unga-vme",
    "bbnj-doalos-prepcom",
    "isa-deepdata",
)


def test_builtin_ocean_pack_loads():
    load_builtin_pack.cache_clear()
    pack = load_builtin_pack()
    names = {p.name for p in pack}
    for name in _NAMED_PACKS:
        assert name in names
    assert "undocs-unga-vme-symbol" in names
    assert "fao" in names
    assert "oecd_scrape" in names
    assert "who_scrape" in names


def test_undocs_unga_vme_rewrite_and_synthesize():
    """Pack 1: undocs URL rewrite + Extra A/RES|A/N/N synthesize."""
    assert (
        rewrite_known_pdf_url("https://undocs.org/A/RES/61/105")
        == "https://undocs.org/pdf?symbol=A/RES/61/105"
    )
    assert (
        rewrite_known_pdf_url("https://undocs.org/en/A/75/157")
        == "https://undocs.org/pdf?symbol=A/75/157"
    )
    item = make_item(url=None, extra="UNGA A/RES/61/105", doi=None, title="VME")
    assert grey_target(item) == "https://undocs.org/pdf?symbol=A/RES/61/105"
    assert (
        apply_synthesize("See also A/75/157 (SG report)")
        == "https://undocs.org/pdf?symbol=A/75/157"
    )


def test_bbnj_doalos_prepcom_scrape_and_symbol():
    """Pack 2: BBNJ/DOALOS landing scrape + Extra A/AC.296 → undocs."""
    html = """
    <html><body>
      <a href="/bbnjagreement/sites/default/files/2024-04/chm-study.pdf">Download</a>
      <a href="https://obis.org/api/v1/foo">OBIS API</a>
    </body></html>
    """
    urls = extract_pdf_urls(
        html, "https://www.un.org/bbnjagreement/en/content/clearing-house"
    )
    assert any("chm-study.pdf" in u for u in urls)
    assert not any("obis.org" in u for u in urls)

    hsa = """
    <html><body>
      <a href="/wp-content/uploads/2024/04/prepcom-report.pdf">PDF</a>
    </body></html>
    """
    urls2 = extract_pdf_urls(hsa, "https://www.highseasalliance.org/resources/prepcom/")
    assert any(u.endswith("prepcom-report.pdf") for u in urls2)

    # Direct PDF under bbnjagreement is already a grey target (no rewrite needed)
    pdf = "https://www.un.org/bbnjagreement/sites/default/files/2024-04/report.pdf"
    assert grey_target(make_item(url=pdf, doi=None)) == pdf

    item = make_item(
        url=None,
        extra="Symbol A/AC.296/2024/3",
        doi=None,
        title="PrepCom consolidated draft",
    )
    assert grey_target(item) == "https://undocs.org/pdf?symbol=A/AC.296/2024/3"


def test_isa_deepdata_scrape_and_isba_symbol():
    """Pack 3: isa.org.jm landing scrape + Extra ISBA symbol → undocs."""
    html = """
    <html><body>
      <a href="/documents/2024/council-decision.pdf">Council decision</a>
      <a href="https://odis.org/api/datasets">ODIS datasets</a>
    </body></html>
    """
    urls = extract_pdf_urls(html, "https://www.isa.org.jm/news/deep-data-update")
    assert any(u.endswith("council-decision.pdf") for u in urls)
    assert not any("odis.org" in u for u in urls)

    item = make_item(
        url=None,
        extra="ISBA/27/C/15",
        doi=None,
        title="Council decision",
        item_type="report",
    )
    assert grey_target(item) == "https://undocs.org/pdf?symbol=ISBA/27/C/15"


def test_merge_user_overrides_and_appends():
    user = [
        GreyPlaybook(
            name="fao",
            kind="rewrite",
            hosts=("fao.org",),
            url_re=r"(?i)fao\.org/3/(?P<code>[a-z0-9]+)/",
            pdf_template="https://cdn.example/fao/{code}.pdf",
        ),
        GreyPlaybook(
            name="my_org",
            kind="rewrite",
            hosts=("example.org",),
            url_re=r"(?i)example\.org/d/(?P<id>\d+)",
            pdf_template="https://example.org/d/{id}.pdf",
        ),
    ]
    merged = merge_playbooks(True, user)
    by_name = {p.name: p for p in merged}
    assert "https://cdn.example/fao/{code}.pdf" == by_name["fao"].pdf_template
    assert "my_org" in by_name
    assert (
        apply_rewrite("https://example.org/d/42", merged)
        == "https://example.org/d/42.pdf"
    )


def test_custom_playbook_via_config_toml(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
email = "t@example.org"
out_dir = "out"
state_dir = "state"
grey_playbooks_builtin = false

[[grey_playbooks]]
name = "acme"
kind = "rewrite"
hosts = ["acme.test"]
url_re = '(?i)acme\\.test/pub/(?P<code>[a-z0-9]+)'
pdf_template = "https://acme.test/pub/{code}.pdf"

[[grey_playbooks]]
name = "acme_id"
kind = "synthesize"
match_re = '\\b(ACME-\\d+)\\b'
pdf_template = "https://acme.test/pdf/{0}"
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert len(cfg.grey_playbooks) == 2
    assert "undocs-unga-vme" not in {p.name for p in cfg.grey_playbooks}
    assert (
        rewrite_known_pdf_url("https://acme.test/pub/ab12", cfg.grey_playbooks)
        == "https://acme.test/pub/ab12.pdf"
    )
    item = make_item(url=None, extra="See ACME-99", doi=None)
    assert grey_target(item, cfg.grey_playbooks) == "https://acme.test/pdf/ACME-99"
    # Builtin FAO off when pack disabled
    assert (
        rewrite_known_pdf_url(
            "https://www.fao.org/3/ca1234en/ca1234en.htm", cfg.grey_playbooks
        )
        is None
    )


def test_who_scrape_playbook():
    html = """
    <html><body><a href="/iris/bitstream/123/file.pdf">Download</a></body></html>
    """
    urls = extract_pdf_urls(html, "https://www.who.int/publications/foo")
    assert any(u.endswith(".pdf") for u in urls)


def test_documents_fao_rewrite():
    assert (
        rewrite_known_pdf_url("https://documents.fao.org/3/ca9999en/index.html")
        == "https://www.fao.org/3/ca9999en/ca9999en.pdf"
    )


def test_core_oa_rewrites_without_builtin_pack():
    empty: list = []
    assert (
        rewrite_known_pdf_url(
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1817752/", empty
        )
        == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1817752/pdf/"
    )
    assert (
        rewrite_known_pdf_url("https://www.fao.org/3/ca1234en/ca1234en.htm", empty)
        is None
    )


def test_pack_dir_loads_and_merges(tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "acme.toml").write_text(
        """
[[grey_playbooks]]
name = "acme_pack"
kind = "rewrite"
hosts = ["acme.test"]
url_re = '(?i)acme\\.test/p/(?P<code>[a-z0-9]+)'
pdf_template = "https://acme.test/p/{code}.pdf"

[[grey_playbooks]]
name = "fao"
kind = "rewrite"
hosts = ["fao.org"]
url_re = '(?i)fao\\.org/3/(?P<code>[a-z0-9]+)/'
pdf_template = "https://cdn.example/fao/{code}.pdf"
""",
        encoding="utf-8",
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
email = "t@example.org"
out_dir = "out"
state_dir = "state"
grey_playbooks_dir = "packs"

[[grey_playbooks]]
name = "inline_only"
kind = "synthesize"
match_re = '\\b(INLINE-\\d+)\\b'
pdf_template = "https://inline.test/{0}"
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg.grey_playbooks_dir == packs.resolve()
    by_name = {p.name: p for p in cfg.grey_playbooks}
    assert "acme_pack" in by_name
    assert "inline_only" in by_name
    assert "undocs-unga-vme" in by_name  # builtin still on
    # Dir pack overrides builtin fao; inline does not touch fao.
    assert by_name["fao"].pdf_template == "https://cdn.example/fao/{code}.pdf"
    assert (
        apply_rewrite("https://acme.test/p/ab12", cfg.grey_playbooks)
        == "https://acme.test/p/ab12.pdf"
    )


def test_pack_dir_before_inline_override(tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "one.toml").write_text(
        """
[[grey_playbooks]]
name = "shared"
kind = "rewrite"
hosts = ["shared.test"]
url_re = '(?i)shared\\.test/(?P<id>\\d+)'
pdf_template = "https://packs.test/{id}.pdf"
""",
        encoding="utf-8",
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
email = "t@example.org"
out_dir = "out"
state_dir = "state"
grey_playbooks_builtin = false
grey_playbooks_dir = "packs"

[[grey_playbooks]]
name = "shared"
kind = "rewrite"
hosts = ["shared.test"]
url_re = '(?i)shared\\.test/(?P<id>\\d+)'
pdf_template = "https://inline.test/{id}.pdf"
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert (
        apply_rewrite("https://shared.test/9", cfg.grey_playbooks)
        == "https://inline.test/9.pdf"
    )


def test_invalid_playbook_rows_warn(tmp_path):
    import warnings

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
email = "t@example.org"
out_dir = "out"
state_dir = "state"
grey_playbooks_builtin = false

[[grey_playbooks]]
name = "bad"
kind = "nope"
""",
        encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = load_config(cfg_path)
    assert cfg.grey_playbooks == []
    assert any("ignored" in str(w.message) for w in caught)
