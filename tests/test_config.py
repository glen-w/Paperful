from pathlib import Path

import pytest

from paperful.config import DEFAULT_MIRRORS, DEFAULT_SOURCES, Config, load_config


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        "paperful.config._candidate_paths", lambda explicit: [tmp_path / "nope.toml"]
    )
    cfg = load_config()
    assert cfg.sources == DEFAULT_SOURCES and cfg.scihub_mirrors == DEFAULT_MIRRORS
    assert cfg.ezproxy_cookie_path == cfg.state_dir / "ezproxy-cookies.txt"
    assert cfg.scholar_cookie_path == cfg.state_dir / "scholar-cookies.txt"
    assert "scihub" not in cfg.sources
    assert cfg.attach is True and cfg.concurrency_oa == 4
    assert cfg.ezproxy_relogin is True
    assert cfg.mirror_pdfs == "all"
    assert cfg.mirror_gone == "mark" and cfg.mirror_refresh == "auto"


def test_load_explicit_file_resolves_relative_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
out_dir = "pdfs"
state_dir = "~/.scihub-state"
sources = ["unpaywall", "scihub"]
scihub_mirrors = ["a.test"]
delay_scihub_s = [1, 2]
concurrency_oa = 0
min_pdf_bytes = 5
crossref_min_score = 0.8
attach = false
app_name = "custom"
mirror_failures_before_skip = 7
""")
    cfg = load_config(p)
    assert cfg.email == "me@example.org"
    assert cfg.out_dir == (tmp_path / "pdfs").resolve()
    assert cfg.state_dir == Path("~/.scihub-state").expanduser()
    assert cfg.sources == ["unpaywall", "scihub"] and cfg.scihub_mirrors == ["a.test"]
    assert cfg.delay_scihub_s == (1.0, 2.0)
    assert cfg.concurrency_oa == 1  # clamped to >= 1
    assert (
        cfg.attach is False
        and cfg.app_name == "custom"
        and cfg.mirror_failures_before_skip == 7
    )
    assert cfg.gate_short_pdfs is True and cfg.short_pdf_min_words == 200


def test_load_short_pdf_gate_knobs(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
gate_short_pdfs = false
short_pdf_min_words = 50
""")
    cfg = load_config(p)
    assert cfg.gate_short_pdfs is False
    assert cfg.short_pdf_min_words == 50
    assert cfg.manifest_path == cfg.state_dir / "manifest.jsonl"
    assert cfg.local_key_path.parent == cfg.state_dir


def test_missing_explicit_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")


def test_ezproxy_relogin_can_be_turned_off(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
ezproxy_relogin = false
""")
    cfg = load_config(p)
    assert cfg.ezproxy_relogin is False


def test_load_routing_and_scholar_cookie_paths(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
source_routing = false
circuit_breaker_threshold = 5
scholar_cookies = "cookies/scholar.txt"
state_dir = "state"
""")
    cfg = load_config(p)
    assert cfg.source_routing is False
    assert cfg.circuit_breaker_threshold == 5
    assert cfg.scholar_cookies == (tmp_path / "cookies" / "scholar.txt").resolve()
    assert cfg.scholar_cookie_path == cfg.scholar_cookies
    assert cfg.ezproxy_cookie_path == cfg.state_dir / "ezproxy-cookies.txt"


def test_load_manager_and_verify_flags(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
email = "me@example.org"
manager = "Zotero"
verify_doi = false
doi_suspect_score = 0.5
core_api_key = "abc"
""")
    cfg = load_config(p)
    assert cfg.manager == "zotero"
    assert cfg.verify_doi is False
    assert cfg.doi_suspect_score == 0.5
    assert cfg.core_api_key == "abc"


def test_load_mendeley_and_endnote_sections(tmp_path):
    enl = tmp_path / "Lib.enl"
    enl.write_bytes(b"x")
    p = tmp_path / "config.toml"
    p.write_text(
        f"""
email = "me@example.org"
manager = "mendeley"
[mendeley]
client_id = "cid"
client_secret = "csec"
redirect_uri = "http://127.0.0.1:9999/cb"
[endnote]
library = "{enl}"
"""
    )
    cfg = load_config(p)
    assert cfg.manager == "mendeley"
    assert cfg.mendeley_client_id == "cid"
    assert cfg.mendeley_client_secret == "csec"
    assert cfg.mendeley_redirect_uri == "http://127.0.0.1:9999/cb"
    assert cfg.endnote_library == enl.resolve()


def test_attachments_flags_default_off(tmp_path):
    from paperful.config import Config

    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[attachments]\n'
        "fix_broken = true\nmerge_files = true\nrename = true\nlink = true\n"
    )
    cfg = load_config(p)
    assert cfg.attachments_fix_broken is True
    assert cfg.attachments_merge_files is True
    assert cfg.attachments_rename is True
    assert cfg.attachments_link is True
    assert Config().attachments_link is False


def test_mirror_pdfs_mode(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('email = "me@example.org"\n\n[mirror]\npdfs = "all"\n')
    cfg = load_config(p)
    assert cfg.mirror_pdfs == "all"
    bad = tmp_path / "bad.toml"
    bad.write_text('email = "me@example.org"\n\n[mirror]\npdfs = "everything"\n')
    with pytest.raises(ValueError, match="pdfs"):
        load_config(bad)


def test_snowball_default_tags(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n[snowball]\ndefault_tags = ["bbnj", "grey"]\n'
    )
    assert load_config(p).snowball_default_tags == ("bbnj", "grey")


def test_keepup_and_map_categories_from_toml(tmp_path):
    bare = Config()
    assert bare.keepup_interval_days == 7
    assert "evidence-synthesis" in bare.snowball_map_categories
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n'
        "[keepup]\ninterval_days = 3\n\n"
        "[snowball]\n"
        'map_categories = ["trials", "protocols"]\n'
        "map_category_defs = [\n"
        '  { id = "grey", label = "Grey", any_types = ["report"] },\n'
        "]\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.keepup_interval_days == 3
    assert cfg.snowball_map_categories == ("trials", "protocols")
    assert any(item.get("id") == "grey" for item in cfg.snowball_map_category_defs)


def test_ui_citation_map_defaults_and_toml(tmp_path):
    bare = Config()
    assert bare.ui_citation_map_edit == "both"
    assert bare.ui_citation_map_auto_search is False
    assert bare.ui_citation_map_remove == "trash"
    p = tmp_path / "config.toml"
    p.write_text(
        'email = "me@example.org"\n\n'
        "[ui]\n"
        'citation_map_edit = "off"\n'
        "citation_map_auto_search = true\n"
        'citation_map_remove = "trash"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.ui_citation_map_edit == "off"
    assert cfg.ui_citation_map_auto_search is True
    assert cfg.ui_citation_map_remove == "trash"


def test_remarks_surface(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('email = "me@example.org"\n\n[remarks]\nsurface = "tag"\n')
    assert load_config(p).remarks_surface == "tag"
    p.write_text('email = "me@example.org"\n\n[remarks]\nsurface = "poster"\n')
    with pytest.raises(ValueError, match="surface"):
        load_config(p)


def test_example_config_toml_parses_and_omits_scihub_by_default():
    repo_cfg = Path(__file__).resolve().parent.parent / "config.example.toml"
    cfg = load_config(repo_cfg)
    assert cfg.email == "you@example.org"
    assert "scihub" not in cfg.sources
    assert "core" in cfg.sources
    assert cfg.manager == "zotero"
    assert cfg.sources[-1] == "htmlpdf"
    assert cfg.out_dir == (repo_cfg.parent / "out").resolve()
    assert cfg.state_dir == (repo_cfg.parent / "state").resolve()
    assert isinstance(cfg, Config)


def test_extension_table_parses_and_rejects(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[extension]\nsnapshot = "off"\ncollection = "Inbox"\nconcurrency = 4\n'
    )
    cfg = load_config(p)
    assert cfg.extension_snapshot == "off"
    assert cfg.extension_collection == "Inbox"
    assert cfg.extension_concurrency == 4
    p.write_text("[extension]\nconcurrency = 9\n")
    with pytest.raises(ValueError):
        load_config(p)
    p.write_text('[extension]\nsnapshot = "always"\n')
    with pytest.raises(ValueError):
        load_config(p)


def test_mirror_modes_parse_and_reject(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[mirror]\npdfs = "additional"\ngone = "trash"\nrefresh = "manual"\n')
    cfg = load_config(p)
    # ``additional`` was the old name for copy-on-first-use.
    assert cfg.mirror_pdfs == "lazy"
    assert cfg.mirror_gone == "trash" and cfg.mirror_refresh == "manual"
    for body in ('pdfs = "some"', 'gone = "delete"', 'refresh = "always"'):
        p.write_text(f"[mirror]\n{body}\n")
        with pytest.raises(ValueError):
            load_config(p)


def test_rag_defaults_are_off(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict({}, tmp_path / "config.toml")
    assert cfg.rag_enabled is False and cfg.rag_auto_ingest is False
    assert cfg.rag_ocr == "auto" and cfg.rag_parser == "light"
    assert cfg.rag_embed_provider == "ollama"
    assert cfg.rag_embed_model == "nomic-embed-text"
    assert cfg.rag_dir == cfg.state_dir / "rag"


def test_rag_table_is_parsed_and_clamped(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "rag": {
                "enabled": True,
                "auto_ingest": True,
                "ocr": "OFF",
                "parser": "Docling",
                "embed_provider": "litellm",
                "embed_model": " openai/text-embedding-3-small ",
                "embed_batch_size": 0,
                "chunk_chars": 1000,
                "chunk_overlap": 900,
                "top_k": 0,
                "hybrid": False,
                "abstracts": False,
                "model": "qwen3:8b",
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.rag_enabled and cfg.rag_auto_ingest
    assert cfg.rag_ocr == "off" and cfg.rag_parser == "docling"
    assert cfg.rag_embed_provider == "litellm"
    assert cfg.rag_embed_model == "openai/text-embedding-3-small"
    assert cfg.rag_embed_batch_size == 1 and cfg.rag_top_k == 1
    assert cfg.rag_chunk_chars == 1000 and cfg.rag_chunk_overlap == 500
    assert cfg.rag_hybrid is False and cfg.rag_abstracts is False
    assert cfg.rag_model == "qwen3:8b"
    assert cfg.rag_ask_mode == "simple"
    assert cfg.rag_evidence_k == 8 and cfg.rag_query_variants == 1
    assert cfg.rag_cite_hops == 0 and cfg.rag_mmr_lambda == 1.0


def test_rag_ask_mode_and_advanced_knobs(tmp_path):
    from paperful.config import _from_dict, parse_rag_ask_mode

    assert parse_rag_ask_mode("") == "simple"
    assert parse_rag_ask_mode("ADVANCED") == "advanced"
    with pytest.raises(ValueError, match="simple or advanced"):
        parse_rag_ask_mode("thorough")
    cfg = _from_dict(
        {
            "rag": {
                "ask_mode": "Advanced",
                "evidence_k": 0,
                "query_variants": 9,
                "insufficient_retries": 8,
                "cite_hops": 5,
                "mmr_lambda": 1.5,
                "relevance_cutoff": 12,
                "evidence_fallback": "DROP",
                "cite_scope": "Library",
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.rag_ask_mode == "advanced"
    assert cfg.rag_evidence_k == 1
    assert cfg.rag_query_variants == 4
    assert cfg.rag_insufficient_retries == 2
    assert cfg.rag_cite_hops == 2
    assert cfg.rag_mmr_lambda == 1.0
    assert cfg.rag_relevance_cutoff == 10
    assert cfg.rag_evidence_fallback == "drop"
    assert cfg.rag_cite_scope == "library"


def test_critique_table_is_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "critique": {
                "llm": True,
                "tag": "  ",
                "overlap_top_k": 10,
                "overlap_n_min": 8,
                "overlap_n_max": 4,
                "cite_age_years": 7,
                "max_context_chars": 5000,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_llm is True
    assert cfg.critique_lanes == ()
    assert cfg.critique_tag == "paperful-critique"
    assert cfg.critique_overlap_top_k == 10
    assert cfg.critique_overlap_n_min == 8
    assert cfg.critique_overlap_n_max == 8
    assert cfg.critique_cite_age_years == 7
    assert cfg.critique_max_context_chars == 5000
    assert cfg.critique_ai_model is False
    assert cfg.critique_vale is False
    assert cfg.critique_vale_config is None
    assert cfg.critique_vale_min_alert_level == "suggestion"
    assert cfg.critique_vale_timeout_s == 60.0
    assert cfg.critique_forensics is False
    assert cfg.critique_forensics_timeout_s == 300.0
    assert cfg.critique_glossary is True
    assert cfg.critique_glossary_dir is None
    assert cfg.critique_glossary_similarity_min == 0.88
    assert cfg.glossary_dir == cfg.state_dir / "glossary"
    assert cfg.critique_advanced is False
    assert cfg.critique_advanced_max_rounds == 4
    assert cfg.critique_advanced_max_workers == 4
    assert cfg.critique_advanced_max_comments == 12
    assert cfg.critique_advanced_refine is True
    assert cfg.critique_advanced_timeout_s == 0.0
    assert cfg.critique_context_timeout_s == 0.0
    assert cfg.critique_context_max_comments == 12
    assert cfg.critique_context_max_hits == 8
    assert cfg.critique_adversary_max_comments == 12
    assert cfg.critique_claims_max == 8
    assert cfg.critique_claims_max_comments == 16
    assert cfg.critique_claims_timeout_s == 0.0
    assert cfg.critique_verify_timeout_s == 0.0
    assert cfg.critique_verify_max_comments == 16
    assert cfg.critique_verify_max_segments == 8
    assert cfg.critique_advanced_aspects == ()
    assert cfg.critique_reviewers == ()
    assert cfg.critiques_dir == cfg.state_dir / "critiques"
    assert cfg.rewrite_areas == ("style",)
    assert cfg.rewrite_outputs == ("edits", "tracked")
    assert cfg.rewrite_comments == "off"
    assert cfg.rewrite_max_edits == 80
    assert cfg.rewrite_openxml_audit is False
    assert cfg.rewrite_openxml_audit_policy == "warn"
    assert cfg.rewrites_dir == cfg.state_dir / "rewrites"


def test_rewrite_table_is_parsed(tmp_path):
    from paperful.config import _from_dict

    prompt = tmp_path / "prompts" / "rewrite-style.md"
    prompt.parent.mkdir()
    prompt.write_text("style prompt", encoding="utf-8")
    cfg = _from_dict(
        {
            "rewrite": {
                "areas": ["style", "cites"],
                "outputs": ["edits", "odt", "pdf"],
                "comments": "substantive",
                "max_edits": 12,
                "timeout_s": 30,
                "openxml_audit": True,
                "openxml_audit_policy": "fail",
                "specialists": [
                    {
                        "id": "style",
                        "model": "xtragpt:7b",
                        "prompt": "prompts/rewrite-style.md",
                    }
                ],
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.rewrite_areas == ("style", "cites")
    assert cfg.rewrite_outputs == ("edits", "odt", "pdf")
    assert cfg.rewrite_comments == "substantive"
    assert cfg.rewrite_max_edits == 12
    assert cfg.rewrite_timeout_s == 30.0
    assert cfg.rewrite_openxml_audit is True
    assert cfg.rewrite_openxml_audit_policy == "fail"
    assert cfg.rewrite_specialists[0].model == "xtragpt:7b"
    assert cfg.rewrite_specialists[0].prompt == str(prompt.resolve())


def test_critique_reviewers_and_ai_model_are_parsed(tmp_path):
    from paperful.config import CritiqueReviewer, _from_dict, parse_critique_reviewers

    prompt = tmp_path / "prompts" / "methods.md"
    prompt.parent.mkdir()
    prompt.write_text("methods prompt", encoding="utf-8")
    cfg = _from_dict(
        {
            "critique": {
                "ai_model": True,
                "reviewers": [
                    {"id": "general"},
                    {
                        "id": "methods",
                        "model": "qwen2.5:14b",
                        "prompt": "prompts/methods.md",
                    },
                ],
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_ai_model is True
    assert [r.id for r in cfg.critique_reviewers] == ["general", "methods"]
    assert cfg.critique_reviewers[0].model == ""
    assert cfg.critique_reviewers[0].prompt == "default"
    assert cfg.critique_reviewers[0].max_tokens == 2048
    assert cfg.critique_reviewers[1].model == "qwen2.5:14b"
    assert cfg.critique_reviewers[1].prompt == str(prompt.resolve())
    with pytest.raises(ValueError, match="duplicate"):
        parse_critique_reviewers([{"id": "a"}, {"id": "a"}])
    assert isinstance(cfg.critique_reviewers[0], CritiqueReviewer)
    capped = parse_critique_reviewers(
        [{"id": "openreview", "prompt": "default", "max_tokens": 1024}]
    )
    assert capped[0].max_tokens == 1024


def test_shipped_critique_prompt_resolves_outside_repo(tmp_path):
    from paperful.config import _from_dict, package_root
    from paperful.critique_llm import load_reviewer_prompt

    cfg_path = tmp_path / "paperful-data" / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg = _from_dict(
        {
            "critique": {
                "reviewers": [
                    {
                        "id": "line-editor",
                        "prompt": "prompts/critique-line-editor.md",
                    },
                ],
            }
        },
        cfg_path,
    )
    row = cfg.critique_reviewers[0]
    expected = (package_root() / "prompts/critique-line-editor.md").resolve()
    assert row.prompt == str(expected)
    assert load_reviewer_prompt(row) is not None

    cfg_legacy = _from_dict(
        {
            "critique": {
                "reviewers": [
                    {"id": "foundations", "prompt": "prompts/critique-reviewer-3.md"},
                ],
            }
        },
        cfg_path,
    )
    legacy = cfg_legacy.critique_reviewers[0]
    assert legacy.prompt == str(
        (package_root() / "prompts/critique-foundations.md").resolve()
    )


def test_critique_advanced_knobs_are_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "critique": {
                "advanced": True,
                "advanced_max_rounds": 2,
                "advanced_max_workers": 3,
                "advanced_max_comments": 5,
                "advanced_refine": False,
                "advanced_timeout_s": 90,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_advanced is True
    assert cfg.critique_advanced_max_rounds == 2
    assert cfg.critique_advanced_max_workers == 3
    assert cfg.critique_advanced_max_comments == 5
    assert cfg.critique_advanced_refine is False
    assert cfg.critique_advanced_timeout_s == 90.0


def test_critique_lanes_and_context_knobs_are_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "critique": {
                "lanes": ["marg", "reviewers", "context"],
                "llm": True,
                "advanced": True,
                "context_timeout_s": 45,
                "context_max_comments": 6,
                "context_max_hits": 3,
                "adversary_max_comments": 4,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_lanes == ("reviewers", "marg", "context")
    assert cfg.critique_context_timeout_s == 45.0
    assert cfg.critique_context_max_comments == 6
    assert cfg.critique_context_max_hits == 3
    assert cfg.critique_adversary_max_comments == 4


def test_critique_claims_verify_and_aspects_are_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "critique": {
                "claims_max": 3,
                "claims_max_comments": 5,
                "claims_timeout_s": 12,
                "verify_timeout_s": 90,
                "verify_max_comments": 7,
                "verify_max_segments": 4,
                "advanced_aspects": ["theory", "policy"],
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_claims_max == 3
    assert cfg.critique_claims_max_comments == 5
    assert cfg.critique_claims_timeout_s == 12.0
    assert cfg.critique_verify_timeout_s == 90.0
    assert cfg.critique_verify_max_comments == 7
    assert cfg.critique_verify_max_segments == 4
    assert cfg.critique_advanced_aspects == ("theory", "policy")
    with pytest.raises(ValueError, match="unknown MARG aspect"):
        _from_dict(
            {"critique": {"advanced_aspects": ["nope"]}},
            tmp_path / "config.toml",
        )


def test_critique_vale_config_resolves_relative(tmp_path):
    from paperful.config import _from_dict

    ini = tmp_path / "house" / ".vale.ini"
    ini.parent.mkdir()
    ini.write_text("MinAlertLevel = suggestion\n", encoding="utf-8")
    cfg = _from_dict(
        {
            "critique": {
                "vale": True,
                "vale_config": "house/.vale.ini",
                "vale_min_alert_level": "warning",
                "vale_timeout_s": 12,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_vale is True
    assert cfg.critique_vale_config == ini.resolve()
    assert cfg.critique_vale_min_alert_level == "warning"
    assert cfg.critique_vale_timeout_s == 12.0


def test_critique_forensics_knobs_are_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "critique": {
                "forensics": True,
                "forensics_timeout_s": 45,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_forensics is True
    assert cfg.critique_forensics_timeout_s == 45.0


def test_critique_glossary_knobs_are_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "state_dir": str(tmp_path / "state"),
            "critique": {
                "glossary": False,
                "glossary_dir": "house-terms",
                "glossary_similarity_min": 0.91,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.critique_glossary is False
    assert cfg.critique_glossary_dir == Path("house-terms")
    assert cfg.critique_glossary_similarity_min == 0.91
    assert cfg.glossary_dir == (cfg.state_dir / "house-terms").resolve()
    with pytest.raises(ValueError, match="suggestion"):
        _from_dict(
            {"critique": {"vale_min_alert_level": "loud"}},
            tmp_path / "config.toml",
        )


def test_extract_sections_table_is_parsed(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "extract_sections": {
                "llm": True,
                "raw_map": False,
                "max_field_chars": 9000,
                "fields": ["abstract", "methodology"],
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.extract_sections_llm is True
    assert cfg.extract_sections_raw_map is False
    assert cfg.extract_sections_max_field_chars == 9000
    assert cfg.extract_sections_fields == ("abstract", "methodology")


@pytest.mark.parametrize(
    "table",
    [{"ocr": "always"}, {"parser": "pymupdf"}, {"embed_provider": "openai"}, {"embed_model": " "}],
)
def test_rag_table_rejects_unknown_values(tmp_path, table):
    from paperful.config import _from_dict

    with pytest.raises(ValueError, match=r"\[rag\]"):
        _from_dict({"rag": table}, tmp_path / "config.toml")


def test_nested_tables_apply_through_config_tables(tmp_path, monkeypatch):
    from paperful import config_tables
    from paperful.config import _from_dict

    original = config_tables.apply_nested_tables
    seen: list[bool] = []

    def wrapped(raw, cfg, source):
        seen.append(True)
        return original(raw, cfg, source)

    monkeypatch.setattr(config_tables, "apply_nested_tables", wrapped)
    cfg = _from_dict({"llm": {"enabled": True}}, tmp_path / "config.toml")
    assert seen == [True]
    assert cfg.llm_enabled is True


def test_inbox_route_keys_parse(tmp_path):
    from paperful.config import _from_dict

    cfg = _from_dict(
        {
            "inbox": {
                "route": "gated",
                "llm_route": "when_thin",
                "route_min_confidence": 0.8,
                "route_auto_min": 0.99,
            }
        },
        tmp_path / "config.toml",
    )
    assert cfg.inbox_route == "gated"
    assert cfg.inbox_llm_route == "when_thin"
    assert cfg.inbox_route_min_confidence == 0.8
    assert cfg.inbox_route_auto_min == 0.99
    with pytest.raises(ValueError):
        _from_dict({"inbox": {"route": "maybe"}}, tmp_path / "config.toml")
