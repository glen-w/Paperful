"""GROBID sidecar client, TEI cache, section extract, and RAG parser (offline)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from paperful import cli
from paperful.config import Config, load_config, parse_rag_parser
from paperful.grobid_client import (
    GrobidClient,
    GrobidConfigError,
    GrobidError,
    grobid_client_from_config,
    grobid_egress_is_remote,
    grobid_url_is_local,
    resolve_grobid_base_url,
    validate_grobid_url,
)
from paperful.rag.chunk import chunk_pages
from paperful.rag.extract import GrobidParser, ParserUnavailable, file_sha256, get_parser
from paperful.sections.command import SCHEMA, SECTION_KEYS, extract_item, write_item
from paperful.sections.grobid import (
    TEI_SCHEMA,
    load_cached_tei,
    process_pdf,
    save_cached_tei,
    tei_section_rows,
    tei_to_markdown_pages,
)
from paperful.store import MirrorEntry, write_json

FIX = Path(__file__).parent / "fixtures"
TEI_FULL = (FIX / "grobid" / "fulltext.tei.xml").read_text(encoding="utf-8")
TEI_PARTIAL = (FIX / "grobid" / "partial.tei.xml").read_text(encoding="utf-8")
runner = CliRunner()


def _pdf(path: Path, payload: bytes = b"%PDF-1.4\nbody\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _mock_client(
    handler, *, timeout: float = 120.0, header: int = 0, citations: int = 0
) -> GrobidClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://grobid.test")
    return GrobidClient(
        "http://grobid.test",
        client=http,
        timeout=timeout,
        consolidate_header=header,
        consolidate_citations=citations,
    )


# ---- URL / config ------------------------------------------------------------


def test_resolve_grobid_loopback_unchanged_on_host(monkeypatch):
    monkeypatch.setattr("paperful.grobid_client._in_docker", lambda: False)
    monkeypatch.delenv("PAPERFUL_GROBID_HOST", raising=False)
    assert resolve_grobid_base_url("http://127.0.0.1:8070") == "http://127.0.0.1:8070"


def test_resolve_grobid_rewrites_loopback_in_docker(monkeypatch):
    monkeypatch.setattr("paperful.grobid_client._in_docker", lambda: True)
    monkeypatch.delenv("PAPERFUL_GROBID_HOST", raising=False)
    monkeypatch.setattr("paperful.grobid_client._ipv4_literal", lambda host: None)
    assert resolve_grobid_base_url("http://127.0.0.1:8070") == (
        "http://host.docker.internal:8070"
    )


def test_resolve_grobid_env_does_not_rewrite_remote(monkeypatch):
    monkeypatch.setattr("paperful.grobid_client._in_docker", lambda: False)
    monkeypatch.setenv("PAPERFUL_GROBID_HOST", "host.docker.internal")
    assert resolve_grobid_base_url("http://192.168.1.1:8070") == (
        "http://192.168.1.1:8070"
    )


def test_grobid_url_locality():
    assert grobid_url_is_local("http://127.0.0.1:8070")
    assert grobid_url_is_local("http://localhost:8070")
    assert grobid_url_is_local("http://grobid:8070")
    assert grobid_url_is_local("http://host.docker.internal:8070")
    assert not grobid_url_is_local("http://grobid.example.com:8070")


def test_validate_grobid_remote_requires_allow():
    with pytest.raises(GrobidConfigError, match="not local"):
        validate_grobid_url("http://grobid.example.com:8070", allow_remote=False)
    assert (
        validate_grobid_url("http://grobid.example.com:8070", allow_remote=True)
        == "http://grobid.example.com:8070"
    )


def test_config_parses_grobid_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[grobid]
enabled = true
base_url = "http://127.0.0.1:9999"
timeout_s = 30
allow_remote = true
consolidate_header = 9
consolidate_citations = 5
[rag]
parser = "GROBID"
""",
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.grobid_enabled is True
    assert loaded.grobid_base_url == "http://127.0.0.1:9999"
    assert loaded.grobid_timeout_s == 30.0
    assert loaded.grobid_allow_remote is True
    assert loaded.grobid_consolidate_header == 3
    assert loaded.grobid_consolidate_citations == 2
    assert loaded.rag_parser == "grobid"


def test_parse_rag_parser_accepts_grobid():
    assert parse_rag_parser("grobid") == "grobid"
    with pytest.raises(ValueError, match="light, docling, or grobid"):
        parse_rag_parser("tei")


def test_grobid_defaults_are_off(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict({}, tmp_path / "config.toml")
    assert cfg.grobid_enabled is False
    assert cfg.grobid_base_url == "http://127.0.0.1:8070"
    assert cfg.grobid_allow_remote is False
    assert cfg.grobid_consolidate_header == 0
    assert cfg.grobid_consolidate_citations == 0


# ---- client ------------------------------------------------------------------


def test_client_health_true_and_false():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/isalive"):
            return httpx.Response(200, text="true")
        return httpx.Response(404)

    client = _mock_client(handler)
    assert client.health() is True

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="no")

    assert _mock_client(down).health() is False


def test_client_fulltext_sends_consolidate_flags(tmp_path):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/processFulltextDocument"):
            body = request.content.decode("latin-1")
            seen["body"] = body
            return httpx.Response(200, text=TEI_FULL)
        return httpx.Response(404)

    client = _mock_client(handler, header=0, citations=0)
    pdf = _pdf(tmp_path / "a.pdf")
    tei = client.process_fulltext(pdf)
    assert "<TEI" in tei
    assert "consolidateHeader" in seen["body"]
    assert "consolidateCitations" in seen["body"]


def test_client_timeout_and_http_error(tmp_path):
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    pdf = _pdf(tmp_path / "a.pdf")
    with pytest.raises(GrobidError, match="timeout"):
        _mock_client(timeout).process_fulltext(pdf)

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    with pytest.raises(GrobidError, match="HTTP 500"):
        _mock_client(boom).process_fulltext(pdf)


def test_client_rejects_non_tei(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>")

    with pytest.raises(GrobidError, match="not TEI"):
        _mock_client(handler).process_fulltext(_pdf(tmp_path / "a.pdf"))


# ---- TEI mapper / cache ------------------------------------------------------


def test_tei_mapper_fulltext_fields():
    pages = tei_to_markdown_pages(TEI_FULL)
    assert pages
    text = pages[0]
    assert "# Abstract" in text
    assert "# Methods" in text
    assert "# Conclusion" in text
    assert "# Research questions" in text
    rows = tei_section_rows(TEI_FULL)
    headings = [r["heading"] for r in rows]
    assert "Introduction" in headings
    assert "Background" in headings
    assert "Methods" in headings
    intro = next(r for r in rows if r["heading"] == "Introduction")
    assert intro.get("n") == "1"
    nested = next(r for r in rows if r["heading"] == "Background")
    assert nested.get("n") == "1.1"


def test_tei_mapper_partial_omits_methods():
    pages = tei_to_markdown_pages(TEI_PARTIAL)
    text = pages[0]
    assert "# Abstract" in text
    assert "# Methods" not in text
    assert "# Conclusion" not in text


def test_tei_cache_skips_http_on_sha_hit(cfg: Config, tmp_path):
    pdf = _pdf(tmp_path / "paper.pdf", b"%PDF-1.4\nunique-bytes\n")
    sha = file_sha256(pdf)
    calls = {"fulltext": 0, "version": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/version"):
            calls["version"] += 1
            return httpx.Response(200, text="0.8.2")
        if path.endswith("/api/processFulltextDocument"):
            calls["fulltext"] += 1
            return httpx.Response(200, text=TEI_FULL)
        return httpx.Response(404)

    client = _mock_client(handler)
    first = process_pdf(cfg, pdf, client=client, item_key="KEY1")
    assert first.startswith("<?xml")
    assert calls["fulltext"] == 1
    xml_path, meta_path = (
        cfg.state_dir / "grobid" / f"{sha}.tei.xml",
        cfg.state_dir / "grobid" / f"{sha}.json",
    )
    assert xml_path.is_file() and meta_path.is_file()
    meta = load_cached_tei(
        cfg,
        sha,
        grobid_version="0.8.2",
        consolidate_header=0,
        consolidate_citations=0,
    )
    assert meta is not None
    stored = meta_path.read_text(encoding="utf-8")
    assert TEI_SCHEMA in stored

    second = process_pdf(cfg, pdf, client=client, item_key="KEY1")
    assert second == first
    assert calls["fulltext"] == 1

    process_pdf(cfg, pdf, client=client, item_key="KEY1", force=True)
    assert calls["fulltext"] == 2


def test_warm_cache_without_server(cfg: Config, tmp_path):
    pdf = _pdf(tmp_path / "paper.pdf")
    sha = file_sha256(pdf)
    save_cached_tei(
        cfg,
        sha,
        TEI_FULL,
        grobid_version="0.8.2",
        consolidate_header=0,
        consolidate_citations=0,
        item_key="KEY1",
    )
    tei = process_pdf(cfg, pdf)
    assert "# Methods" in "\n".join(tei_to_markdown_pages(tei))


# ---- extract-sections --------------------------------------------------------


def test_extract_item_grobid_engine(cfg: Config, tmp_path, monkeypatch):
    pdf = _pdf(cfg.out_dir / "coll" / "item -- KEY1" / "paper.pdf", b"%PDF-1.4\n" + b"x" * 200)
    entry = MirrorEntry(
        key="KEY1",
        dirs=["coll/item -- KEY1"],
        record={"abstract": "", "title": "T", "year": 2020},
        pdfs=[pdf],
    )
    monkeypatch.setattr("paperful.sections.grobid.pdf_is_scan", lambda p: False)
    monkeypatch.setattr(
        "paperful.sections.grobid.process_pdf", lambda *a, **k: TEI_FULL
    )
    item = extract_item(cfg, entry, use_grobid=True)
    assert item is not None
    assert item.engine == "grobid"
    assert item.schema == SCHEMA
    assert item.fields["abstract"] is not None
    assert item.fields["abstract"]["provenance"] == "grobid"
    assert item.fields["methodology"] is not None
    assert item.fields["conclusion"] is not None
    assert item.pdf_sha256
    path = write_item(cfg, item)
    body = path.read_text(encoding="utf-8")
    assert '"engine": "grobid"' in body
    assert SECTION_KEYS <= set(__import__("json").loads(body))


def test_extract_item_scan_falls_back_to_rules(cfg: Config, tmp_path, monkeypatch):
    pdf = _pdf(cfg.out_dir / "coll" / "item -- KEY1" / "paper.pdf")
    entry = MirrorEntry(
        key="KEY1",
        dirs=["coll/item -- KEY1"],
        record={"abstract": "", "title": "T", "year": 2020},
        pdfs=[pdf],
    )
    from paperful.rag.extract import TEXT_SCHEMA, text_cache_path

    write_json(
        text_cache_path(cfg, "KEY1"),
        {
            "schema": TEXT_SCHEMA,
            "pages": [
                "Abstract\n\n"
                "We study ocean governance with a long abstract body that exceeds "
                "the minimum length required for a valid section extract here.\n\n"
                "Methods\n\n"
                "We surveyed twelve sites using structured interviews and coding. "
                "Each site received the same protocol, blinded coders, and checks.\n\n"
                "Conclusion\n\n"
                "Marine policy should adopt stronger monitoring frameworks soon. "
                "Future work must tie enforcement data to measurable outcomes.\n"
            ],
        },
    )
    monkeypatch.setattr("paperful.sections.grobid.pdf_is_scan", lambda p: True)

    def boom(*a, **k):
        raise AssertionError("GROBID should not run on scans")

    monkeypatch.setattr("paperful.sections.grobid.process_pdf", boom)
    item = extract_item(cfg, entry, use_grobid=True)
    assert item is not None
    assert item.engine == "rule"
    assert any("scan" in n for n in item.notes)
    assert item.fields["abstract"]["provenance"] == "rule"


def test_cli_extract_sections_grobid_dry_run(cfg: Config, tmp_path, monkeypatch):
    toml = tmp_path / "paperful.toml"
    toml.write_text(
        f'email = "{cfg.email}"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[grobid]\nenabled = false\n",
        encoding="utf-8",
    )
    coll = cfg.out_dir / "BBNJ" / "Paper -- KEY99"
    coll.mkdir(parents=True)
    write_json(
        coll / "record.json",
        {
            "schema": "paperful.item.v1",
            "item_key": "KEY99",
            "title": "Paper",
            "year": 2020,
            "abstract": "",
        },
    )
    from paperful.rag.extract import TEXT_SCHEMA, text_cache_path

    write_json(
        text_cache_path(cfg, "KEY99"),
        {
            "schema": TEXT_SCHEMA,
            "pages": [
                "Abstract\n\n"
                "We study ocean governance with a long abstract body that exceeds "
                "the minimum length required for a valid section extract here.\n"
            ],
        },
    )
    monkeypatch.setattr(
        "paperful.grobid_client.grobid_client_from_config",
        lambda cfg, **k: _mock_client(lambda r: httpx.Response(200, text="true")),
    )
    res = runner.invoke(
        cli.app,
        ["extract-sections", "-C", "BBNJ", "--grobid", "--dry-run", "-c", str(toml)],
    )
    assert res.exit_code == 0, res.stdout
    assert "GROBID on" in (res.stdout or "")
    assert not list((cfg.state_dir / "sections").glob("*.json"))


def test_cli_remote_without_allow_exits(cfg: Config, tmp_path):
    toml = tmp_path / "paperful.toml"
    toml.write_text(
        f'email = "{cfg.email}"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[grobid]\nenabled = true\n"
        'base_url = "http://grobid.example.com:8070"\n'
        "allow_remote = false\n",
        encoding="utf-8",
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    res = runner.invoke(
        cli.app,
        ["extract-sections", "--library", "--dry-run", "-c", str(toml)],
    )
    assert res.exit_code == 1
    assert "not local" in (res.stdout or "")


def test_cli_remote_grobid_notice(cfg: Config, tmp_path, monkeypatch):
    toml = tmp_path / "paperful.toml"
    toml.write_text(
        f'email = "{cfg.email}"\nout_dir = "{cfg.out_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        "[grobid]\nenabled = true\n"
        'base_url = "http://grobid.example.com:8070"\n'
        "allow_remote = true\n",
        encoding="utf-8",
    )
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "paperful.sections.command.extract_scope",
        lambda *a, **k: [],
    )
    res = runner.invoke(
        cli.app,
        ["extract-sections", "--library", "--dry-run", "-c", str(toml)],
    )
    assert res.exit_code == 0, res.stdout
    assert "PDF bytes leave this machine" in (res.stdout or "")


# ---- RAG parser --------------------------------------------------------------


def test_get_parser_grobid(cfg: Config):
    assert get_parser(cfg).name == "light"
    cfg.rag_parser = "grobid"
    with pytest.raises(ParserUnavailable, match=r"\[grobid\]"):
        get_parser(cfg)
    cfg.grobid_enabled = True
    parser = get_parser(cfg)
    assert parser.name == "grobid"
    assert isinstance(parser, GrobidParser)


def test_grobid_parser_markdown_pages_chunk(cfg: Config, tmp_path, monkeypatch):
    cfg.grobid_enabled = True
    pdf = _pdf(tmp_path / "a.pdf")
    monkeypatch.setattr("paperful.sections.grobid.pdf_is_scan", lambda p: False)
    monkeypatch.setattr(
        "paperful.sections.grobid.process_pdf", lambda *a, **k: TEI_FULL
    )
    pages = GrobidParser(cfg).pages(pdf)
    chunks = chunk_pages(pages, min_chars=20)
    sections = {c.section for c in chunks if c.section}
    assert "Abstract" in sections or "Methods" in sections
    assert any(c.section == "Methods" for c in chunks) or any(
        "Methods" in (c.section or "") for c in chunks
    )


def test_grobid_parser_uses_warm_cache(cfg: Config, tmp_path):
    cfg.grobid_enabled = True
    pdf = _pdf(tmp_path / "warm.pdf", b"%PDF-1.4\nwarm-cache\n")
    save_cached_tei(
        cfg,
        file_sha256(pdf),
        TEI_FULL,
        grobid_version="0.8.2",
        consolidate_header=0,
        consolidate_citations=0,
    )
    pages = GrobidParser(cfg).pages(pdf)
    assert pages and "# Methods" in pages[0]


# ---- doctor ------------------------------------------------------------------


def test_grobid_doctor_disabled_is_green(cfg: Config):
    from paperful.doctor import _grobid_checks, remediation_text

    cfg.grobid_enabled = False
    rows = _grobid_checks(cfg)
    assert len(rows) == 1
    assert rows[0].name == "GROBID"
    assert rows[0].status == "green"
    assert "disabled" in rows[0].detail
    assert remediation_text(rows[0], cfg) is None


def test_grobid_doctor_enabled_down_is_amber(cfg: Config, monkeypatch):
    from paperful.doctor import _grobid_checks, remediation_text

    class Down:
        def health(self):
            return False

        def close(self):
            pass

    cfg.grobid_enabled = True
    monkeypatch.setattr(
        "paperful.grobid_client.grobid_client_from_config", lambda cfg, **k: Down()
    )
    rows = _grobid_checks(cfg)
    assert rows[0].status == "amber"
    assert "unreachable" in rows[0].detail
    text = remediation_text(rows[0], cfg)
    assert text and "docs/grobid.md" in text


def test_grobid_doctor_enabled_alive_is_green(cfg: Config, monkeypatch):
    from paperful.doctor import _grobid_checks

    class Up:
        def health(self):
            return True

        def version(self):
            return "0.8.2"

        def close(self):
            pass

    cfg.grobid_enabled = True
    monkeypatch.setattr(
        "paperful.grobid_client.grobid_client_from_config", lambda cfg, **k: Up()
    )
    rows = _grobid_checks(cfg)
    assert rows[0].status == "green"
    assert "0.8.2" in rows[0].detail


def test_grobid_client_from_config_loopback(cfg: Config):
    cfg.grobid_base_url = "http://127.0.0.1:8070"
    cfg.grobid_allow_remote = False
    client = grobid_client_from_config(cfg)
    try:
        assert "127.0.0.1" in client.base_url or "host.docker.internal" in client.base_url
    finally:
        client.close()
    cfg.grobid_base_url = "http://grobid.example.com:8070"
    assert grobid_egress_is_remote(cfg) is True
    with pytest.raises(GrobidConfigError):
        grobid_client_from_config(cfg)
    cfg.grobid_allow_remote = True
    remote = grobid_client_from_config(cfg)
    try:
        assert "grobid.example.com" in remote.base_url
    finally:
        remote.close()
