"""Apply nested TOML tables onto Config (per-section helpers)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Config


def _mod():
    from . import config as config_mod

    return config_mod


def apply_nested_tables(raw: dict[str, Any], cfg: "Config", source: Path) -> None:
    apply_llm(raw, cfg)
    apply_browser_agent(raw, cfg)
    apply_fix_metadata(raw, cfg)
    apply_lint(raw, cfg)
    apply_screen(raw, cfg, source)
    apply_critique(raw, cfg)
    apply_rewrite(raw, cfg)
    apply_summarize(raw, cfg)
    apply_synthesize(raw, cfg)
    apply_fetch(raw, cfg)
    apply_scholar(raw, cfg)
    apply_serpapi(raw, cfg)
    apply_camofox(raw, cfg)
    apply_grobid(raw, cfg)
    apply_handoff(raw, cfg)
    apply_request(raw, cfg)
    apply_twenty(raw, cfg)
    apply_gaps(raw, cfg)
    apply_inbox(raw, cfg)
    apply_htmlpdf(raw, cfg)
    apply_ingest(raw, cfg)
    apply_playbooks(raw, cfg)
    apply_mirror(raw, cfg)
    apply_extension(raw, cfg)
    apply_remarks(raw, cfg)
    apply_oa_honesty(raw, cfg)
    apply_exclude(raw, cfg)
    apply_attachments(raw, cfg)
    apply_ocr(raw, cfg)
    apply_rag(raw, cfg, source)
    apply_extract_sections(raw, cfg, source)
    apply_mendeley(raw, cfg)
    apply_endnote(raw, cfg, source)
    apply_openalex_store(raw, cfg)
    apply_searxng(raw, cfg)
    apply_keepup(raw, cfg)
    apply_precedent(raw, cfg)
    apply_ui(raw, cfg)
    apply_prompt_paths(cfg, source)


def apply_llm(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    C._apply_config_table(
        raw.get("llm"),
        cfg,
        [
            ("enabled", "llm_enabled", bool),
            (
                "provider",
                "llm_provider",
                lambda v: str(v).strip().lower() or "ollama",
            ),
            ("model", "llm_model", lambda v: str(v).strip()),
            ("base_url", "llm_base_url", lambda v: str(v).strip()),
            ("api_base", "llm_api_base", lambda v: str(v).strip()),
            ("allow_remote", "llm_allow_remote", bool),
            ("timeout_s", "llm_timeout_s", float),
            ("max_num_ctx", "llm_max_num_ctx", lambda v: max(1024, int(v))),
        ],
    )


def apply_browser_agent(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    C._apply_config_table(
        raw.get("browser_agent"),
        cfg,
        [
            ("max_steps", "browser_agent_max_steps", lambda v: max(1, int(v))),
            ("max_wall_s", "browser_agent_max_wall_s", float),
            ("model", "browser_agent_model", lambda v: str(v).strip()),
            (
                "fallback_model",
                "browser_agent_fallback_model",
                lambda v: str(v).strip(),
            ),
            ("during_run", "browser_agent_during_run", bool),
            ("use_vision", "browser_agent_use_vision", bool),
            ("use_thinking", "browser_agent_use_thinking", bool),
        ],
    )


def apply_fix_metadata(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("fix_metadata"),
        cfg,
        [("llm_title", "fix_metadata_llm_title", bool)],
    )


def apply_lint(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    C._apply_config_table(
        raw.get("lint"),
        cfg,
        [
            ("llm_pdf_match", "lint_llm_pdf_match", bool),
            (
                "llm_pdf_match_min_confidence",
                "lint_llm_pdf_match_min_confidence",
                C._clamp01,
            ),
        ],
    )


def apply_screen(raw: dict[str, Any], cfg: "Config", source: Path) -> None:
    C = _mod()
    section = raw.get("screen")
    if not isinstance(section, dict):
        return
    C._apply_config_table(
        section,
        cfg,
        [
            ("tortured_min", "screen_tortured_min", lambda v: max(1, int(v))),
            ("pubpeer", "screen_pubpeer", bool),
            (
                "fingerprint_max_age_days",
                "screen_fingerprint_max_age_days",
                lambda v: max(1, int(v)),
            ),
            (
                "fingerprint_dir",
                "screen_fingerprint_dir",
                lambda v: Path(str(v).strip()) if str(v).strip() else None,
            ),
            ("tag", "screen_tag", lambda v: str(v).strip() or "paperful-pps"),
        ],
    )
    if (
        cfg.screen_fingerprint_dir is not None
        and not cfg.screen_fingerprint_dir.is_absolute()
    ):
        cfg.screen_fingerprint_dir = (
            source.parent / cfg.screen_fingerprint_dir
        ).resolve()
    if "detectors" in section:
        cfg.screen_detectors = C._snowball_strs(section["detectors"])


def apply_critique(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    table = raw.get("critique")
    if not isinstance(table, dict):
        return
    C._apply_config_table(
        table,
        cfg,
        [
            ("llm", "critique_llm", bool),
            ("tag", "critique_tag", lambda v: str(v).strip() or "paperful-critique"),
            ("overlap_top_k", "critique_overlap_top_k", lambda v: max(1, int(v))),
            ("overlap_n_min", "critique_overlap_n_min", lambda v: max(2, int(v))),
            ("overlap_n_max", "critique_overlap_n_max", lambda v: max(2, int(v))),
            ("overlap_df_max", "critique_overlap_df_max", lambda v: max(0, int(v))),
            ("cite_age_years", "critique_cite_age_years", lambda v: max(1, int(v))),
            (
                "max_context_chars",
                "critique_max_context_chars",
                lambda v: max(1000, int(v)),
            ),
            ("ai_model", "critique_ai_model", bool),
            ("vale", "critique_vale", bool),
            ("forensics", "critique_forensics", bool),
            ("glossary", "critique_glossary", bool),
            (
                "glossary_dir",
                "critique_glossary_dir",
                lambda v: Path(str(v).strip()).expanduser() if str(v).strip() else None,
            ),
            (
                "glossary_similarity_min",
                "critique_glossary_similarity_min",
                lambda v: min(1.0, max(0.5, float(v))),
            ),
            (
                "vale_config",
                "critique_vale_config",
                lambda v: Path(v).expanduser() if v else None,
            ),
            (
                "vale_timeout_s",
                "critique_vale_timeout_s",
                lambda v: max(1.0, float(v)),
            ),
            (
                "forensics_timeout_s",
                "critique_forensics_timeout_s",
                lambda v: max(1.0, float(v)),
            ),
            ("advanced", "critique_advanced", bool),
            (
                "advanced_max_rounds",
                "critique_advanced_max_rounds",
                lambda v: max(1, int(v)),
            ),
            (
                "advanced_max_workers",
                "critique_advanced_max_workers",
                lambda v: max(1, int(v)),
            ),
            (
                "advanced_max_comments",
                "critique_advanced_max_comments",
                lambda v: max(1, int(v)),
            ),
            ("advanced_refine", "critique_advanced_refine", bool),
            (
                "advanced_timeout_s",
                "critique_advanced_timeout_s",
                lambda v: max(0.0, float(v)),
            ),
            (
                "context_timeout_s",
                "critique_context_timeout_s",
                lambda v: max(0.0, float(v)),
            ),
            (
                "context_max_comments",
                "critique_context_max_comments",
                lambda v: max(1, int(v)),
            ),
            (
                "context_max_hits",
                "critique_context_max_hits",
                lambda v: max(1, int(v)),
            ),
            (
                "adversary_max_comments",
                "critique_adversary_max_comments",
                lambda v: max(1, int(v)),
            ),
            (
                "claims_max",
                "critique_claims_max",
                lambda v: max(1, int(v)),
            ),
            (
                "claims_max_comments",
                "critique_claims_max_comments",
                lambda v: max(1, int(v)),
            ),
            (
                "claims_timeout_s",
                "critique_claims_timeout_s",
                lambda v: max(0.0, float(v)),
            ),
            (
                "verify_timeout_s",
                "critique_verify_timeout_s",
                lambda v: max(0.0, float(v)),
            ),
            (
                "verify_max_comments",
                "critique_verify_max_comments",
                lambda v: max(1, int(v)),
            ),
            (
                "verify_max_segments",
                "critique_verify_max_segments",
                lambda v: max(1, int(v)),
            ),
        ],
    )
    if "vale_min_alert_level" in table:
        cfg.critique_vale_min_alert_level = C.parse_vale_min_alert_level(
            str(table.get("vale_min_alert_level") or ""),
            key="[critique].vale_min_alert_level",
        )
    if "lanes" in table:
        from .critique_lanes import parse_critique_lanes

        cfg.critique_lanes = parse_critique_lanes(table.get("lanes"))
    if "advanced_aspects" in table:
        from .critique_marg import parse_marg_aspects

        cfg.critique_advanced_aspects = parse_marg_aspects(
            table.get("advanced_aspects")
        )
    if "reviewers" in table:
        cfg.critique_reviewers = C.parse_critique_reviewers(table.get("reviewers"))
    if cfg.critique_overlap_n_min > cfg.critique_overlap_n_max:
        cfg.critique_overlap_n_max = cfg.critique_overlap_n_min


def apply_rewrite(raw: dict[str, Any], cfg: "Config") -> None:
    from .rewrite_areas import (
        parse_rewrite_areas_list,
        parse_rewrite_comments,
        parse_rewrite_outputs,
        parse_rewrite_specialists,
    )
    from .rewrite_openxml import parse_openxml_audit_policy

    C = _mod()
    table = raw.get("rewrite")
    if not isinstance(table, dict):
        return
    C._apply_config_table(
        table,
        cfg,
        [
            ("max_edits", "rewrite_max_edits", lambda v: max(1, int(v))),
            ("timeout_s", "rewrite_timeout_s", lambda v: max(0.0, float(v))),
            ("openxml_audit", "rewrite_openxml_audit", bool),
            (
                "openxml_audit_policy",
                "rewrite_openxml_audit_policy",
                parse_openxml_audit_policy,
            ),
        ],
    )
    if "areas" in table:
        cfg.rewrite_areas = parse_rewrite_areas_list(table.get("areas"))
    if "outputs" in table:
        cfg.rewrite_outputs = parse_rewrite_outputs(table.get("outputs"))
    if "comments" in table:
        cfg.rewrite_comments = parse_rewrite_comments(table.get("comments"))
    if "specialists" in table:
        cfg.rewrite_specialists = parse_rewrite_specialists(table.get("specialists"))


def apply_summarize(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    summ = raw.get("summarize")
    if not isinstance(summ, dict):
        return
    C._apply_config_table(
        summ,
        cfg,
        [
            ("prompt_template", "summarize_prompt_template", lambda v: str(v).strip()),
            (
                "max_context_chars",
                "summarize_max_context_chars",
                lambda v: max(1000, int(v)),
            ),
            (
                "tag",
                "summarize_tag",
                lambda v: str(v).strip() or "paperful-summary",
            ),
            (
                "ste_word_list_path",
                "ste_word_list_path",
                lambda v: Path(v).expanduser() if v else None,
            ),
        ],
    )
    if "dest" in summ:
        cfg.summarize_dest = C.parse_dest(str(summ["dest"]), key="[summarize].dest")
    if "order" in summ:
        cfg.summarize_order = C.parse_summarize_order(
            str(summ["order"]), key="[summarize].order"
        )
    if "style" in summ:
        cfg.summarize_style = C.parse_summarize_style(
            str(summ["style"]), key="[summarize].style"
        )
    if "ste_violation_policy" in summ:
        cfg.ste_violation_policy = C.parse_ste_violation_policy(
            str(summ["ste_violation_policy"]),
            key="[summarize].ste_violation_policy",
        )


def apply_synthesize(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    synth = raw.get("synthesize")
    if not isinstance(synth, dict):
        return
    C._apply_config_table(
        synth,
        cfg,
        [
            (
                "prompt_template",
                "synthesize_prompt_template",
                lambda v: str(v).strip(),
            ),
            (
                "max_context_chars",
                "synthesize_max_context_chars",
                lambda v: max(1000, int(v)),
            ),
            (
                "tag",
                "synthesize_tag",
                lambda v: str(v).strip() or "paperful-report",
            ),
            ("timeout_s", "synthesize_timeout_s", float),
        ],
    )
    if "dest" in synth:
        cfg.synthesize_dest = C.parse_dest(str(synth["dest"]), key="[synthesize].dest")


def apply_fetch(raw: dict[str, Any], cfg: "Config") -> None:
    fetch = raw.get("fetch")
    if isinstance(fetch, dict) and "order" in fetch:
        cfg.fetch_order = _mod()._one_of(
            "[fetch].order", fetch["order"], ("policy", "list")
        )


def apply_scholar(raw: dict[str, Any], cfg: "Config") -> None:
    scholar_tbl = raw.get("scholar")
    if isinstance(scholar_tbl, dict) and "when" in scholar_tbl:
        cfg.scholar_when = _mod()._one_of(
            "[scholar].when", scholar_tbl["when"], ("auto", "phase", "interleave")
        )


def apply_serpapi(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("serpapi"),
        cfg,
        [
            ("enabled", "serpapi_enabled", bool),
            ("max_calls", "serpapi_max_calls", lambda v: max(0, int(v))),
        ],
    )


def apply_camofox(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("camofox"),
        cfg,
        [
            ("enabled", "camofox_enabled", bool),
            ("during_run", "camofox_during_run", bool),
            ("base_url", "camofox_base_url", lambda v: str(v).strip()),
            ("max_wall_s", "camofox_max_wall_s", float),
        ],
    )


def apply_grobid(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("grobid"),
        cfg,
        [
            ("enabled", "grobid_enabled", bool),
            ("base_url", "grobid_base_url", lambda v: str(v).strip()),
            ("timeout_s", "grobid_timeout_s", float),
            ("allow_remote", "grobid_allow_remote", bool),
            (
                "consolidate_header",
                "grobid_consolidate_header",
                lambda v: max(0, min(3, int(v))),
            ),
            (
                "consolidate_citations",
                "grobid_consolidate_citations",
                lambda v: max(0, min(2, int(v))),
            ),
        ],
    )


def apply_handoff(raw: dict[str, Any], cfg: "Config") -> None:
    handoff_tbl = raw.get("handoff")
    if isinstance(handoff_tbl, dict) and "scholar" in handoff_tbl:
        cfg.handoff_scholar = bool(handoff_tbl["scholar"])


def apply_request(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    req = raw.get("request")
    if not isinstance(req, dict):
        return
    if "channels" in req:
        cfg.request_channels = C._one_of(
            "[request].channels",
            req["channels"],
            ("off", "rg", "email", "both", "rg_then_email_after_days"),
        )
    if "email_after_days" in req:
        cfg.request_email_after_days = max(0, int(req["email_after_days"]))


def apply_twenty(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("twenty"),
        cfg,
        [
            ("enabled", "twenty_enabled", bool),
            ("base_url", "twenty_base_url", lambda v: str(v).strip().rstrip("/")),
            ("lookup_on_preflight", "twenty_lookup_on_preflight", bool),
            ("retry_max", "twenty_retry_max", lambda v: max(0, int(v))),
            (
                "retry_base_seconds",
                "twenty_retry_base_seconds",
                lambda v: max(0.0, float(v)),
            ),
            (
                "sync_note_title",
                "twenty_sync_note_title",
                lambda v: str(v).strip() or "Paperful",
            ),
            (
                "provenance_keyword",
                "twenty_provenance_keyword",
                lambda v: str(v).strip() or "paperful",
            ),
            ("fetch_listing_max", "twenty_fetch_listing_max", lambda v: max(0, int(v))),
            ("writeback_listings", "twenty_writeback_listings", bool),
        ],
    )


def apply_gaps(raw: dict[str, Any], cfg: "Config") -> None:
    gaps = raw.get("gaps")
    if not isinstance(gaps, dict):
        return
    if "handoff" in gaps:
        from .handoff import parse_handoff

        cfg.gaps_handoff = parse_handoff(str(gaps["handoff"]))
    if "downloads_dir" in gaps:
        cfg.gaps_downloads_dir = str(gaps["downloads_dir"]).strip()


def apply_inbox(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    inbox = raw.get("inbox")
    if not isinstance(inbox, dict):
        return
    C._apply_config_table(
        inbox,
        cfg,
        [
            ("dir", "inbox_dir", lambda v: str(v).strip()),
            ("watch_after_handoff", "inbox_watch_after_handoff", bool),
            ("poll_seconds", "inbox_poll_seconds", lambda v: max(0.2, float(v))),
            ("settle_seconds", "inbox_settle_seconds", lambda v: max(0.0, float(v))),
            ("idle_seconds", "inbox_idle_seconds", lambda v: max(0.0, float(v))),
            (
                "quarantine_after_s",
                "inbox_quarantine_after_s",
                lambda v: max(0.0, float(v)),
            ),
            ("ocr_for_match", "inbox_ocr_for_match", bool),
            ("llm_match_min_confidence", "inbox_llm_match_min_confidence", C._clamp01),
            ("llm_auto_attach_min", "inbox_llm_auto_attach_min", C._clamp01),
            ("route_min_confidence", "inbox_route_min_confidence", C._clamp01),
            ("route_auto_min", "inbox_route_auto_min", C._clamp01),
            ("model", "inbox_model", lambda v: str(v).strip()),
            ("provider", "inbox_provider", lambda v: str(v).strip()),
            ("title_resolve", "inbox_title_resolve", bool),
            (
                "manager_metadata_s",
                "inbox_manager_metadata_s",
                lambda v: max(0.0, float(v)),
            ),
        ],
    )
    if "match" in inbox:
        cfg.inbox_match = C._one_of(
            "[inbox].match",
            inbox["match"],
            ("doi_only", "doi+title", "doi+title+ocr", "full"),
        )
    if "llm_match" in inbox:
        cfg.inbox_llm_match = C._one_of(
            "[inbox].llm_match",
            inbox["llm_match"],
            ("off", "when_thin", "always"),
        )
    if "create" in inbox:
        cfg.inbox_create = C._one_of(
            "[inbox].create",
            inbox["create"],
            ("attach_only", "create_gated", "create_auto"),
        )
    if "route" in inbox:
        cfg.inbox_route = C._one_of(
            "[inbox].route",
            inbox["route"],
            ("off", "gated", "auto"),
        )
    if "llm_route" in inbox:
        cfg.inbox_llm_route = C._one_of(
            "[inbox].llm_route",
            inbox["llm_route"],
            ("off", "when_thin", "always"),
        )


def apply_htmlpdf(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    htmlpdf = raw.get("htmlpdf")
    if not isinstance(htmlpdf, dict):
        return
    if "academic" in htmlpdf:
        cfg.htmlpdf_academic = C._one_of(
            "[htmlpdf].academic",
            htmlpdf["academic"],
            ("off", "gated", "auto"),
        )
    C._apply_config_table(
        htmlpdf,
        cfg,
        [
            ("upgrade", "htmlpdf_upgrade", bool),
            ("keep_snapshot", "htmlpdf_keep_snapshot", bool),
        ],
    )


def apply_ingest(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    ingest = raw.get("ingest")
    if not isinstance(ingest, dict):
        return
    if "default_tags" in ingest:
        cfg.ingest_default_tags = C._snowball_strs(ingest["default_tags"])
    if "dedupe_scope" in ingest:
        cfg.ingest_dedupe_scope = C._one_of(
            "[ingest].dedupe_scope",
            ingest["dedupe_scope"],
            ("library", "collection"),
        )


def apply_playbooks(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    learned = raw.get("playbooks")
    if not isinstance(learned, dict):
        return
    if "promote" in learned:
        cfg.playbooks_promote = C.parse_playbooks_promote(str(learned["promote"]))
    if "auto_min_hits" in learned:
        hits = int(learned["auto_min_hits"])
        if hits < 1:
            raise ValueError("[playbooks].auto_min_hits must be >= 1")
        cfg.playbooks_auto_min_hits = hits


def apply_mirror(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    mirror = raw.get("mirror")
    if not isinstance(mirror, dict):
        return
    if "pdfs" in mirror:
        cfg.mirror_pdfs = C.parse_pdfs(str(mirror["pdfs"]))
    if "gone" in mirror:
        cfg.mirror_gone = C._one_of("[mirror].gone", mirror["gone"], ("mark", "trash"))
    if "refresh" in mirror:
        cfg.mirror_refresh = C._one_of(
            "[mirror].refresh", mirror["refresh"], ("auto", "manual")
        )


def apply_extension(raw: dict[str, Any], cfg: "Config") -> None:
    """``[extension]`` — Firefox capture. Does not change ``[mirror].refresh``."""
    block = raw.get("extension")
    if not isinstance(block, dict):
        return
    C = _mod()
    if "snapshot" in block:
        cfg.extension_snapshot = C._one_of(
            "[extension].snapshot", block["snapshot"], ("auto", "off")
        )
    if "collection" in block and str(block["collection"]).strip():
        cfg.extension_collection = str(block["collection"]).strip()
    if "drop" in block:
        cfg.extension_drop = str(block["drop"] or "").strip()
    if "concurrency" in block:
        try:
            n = int(block["concurrency"])
        except (TypeError, ValueError) as exc:
            raise ValueError("[extension].concurrency must be 1–4") from exc
        if n < 1 or n > 4:
            raise ValueError("[extension].concurrency must be 1–4")
        cfg.extension_concurrency = n


def apply_remarks(raw: dict[str, Any], cfg: "Config") -> None:
    remarks = raw.get("remarks")
    if isinstance(remarks, dict) and remarks.get("surface") not in (None, ""):
        cfg.remarks_surface = _mod().parse_remarks_surface(str(remarks["surface"]))


def apply_oa_honesty(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    oa_honesty = raw.get("oa_honesty")
    if not isinstance(oa_honesty, dict):
        return
    if "stamp_fields" in oa_honesty:
        cfg.oa_honesty_stamp_fields = C._snowball_strs(oa_honesty["stamp_fields"])
    if "license_block" in oa_honesty:
        cfg.oa_honesty_license_block = C._snowball_strs(oa_honesty["license_block"])


def apply_exclude(raw: dict[str, Any], cfg: "Config") -> None:
    """Top-level ``[[exclude]]`` array — protect collection subtrees from writes."""
    if "exclude" not in raw:
        return
    from .exclude import parse_exclude_rules

    cfg.exclude_rules = parse_exclude_rules(raw.get("exclude"))


def apply_attachments(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("attachments"),
        cfg,
        [
            ("fix_broken", "attachments_fix_broken", bool),
            ("merge_files", "attachments_merge_files", bool),
            ("rename", "attachments_rename", bool),
            ("link", "attachments_link", bool),
        ],
    )


def apply_ocr(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("ocr"),
        cfg,
        [
            ("languages", "ocr_languages", lambda v: str(v).strip() or "eng"),
            ("timeout_s", "ocr_timeout_s", lambda v: max(1.0, float(v))),
            ("auto_ignore_failures", "ocr_auto_ignore_failures", bool),
        ],
    )


def apply_rag(raw: dict[str, Any], cfg: "Config", source: Path) -> None:
    C = _mod()
    rag = raw.get("rag")
    if not isinstance(rag, dict):
        return
    C._apply_config_table(
        rag,
        cfg,
        [
            ("enabled", "rag_enabled", bool),
            ("auto_ingest", "rag_auto_ingest", bool),
            ("ocr", "rag_ocr", lambda v: C.parse_rag_ocr(str(v))),
            ("parser", "rag_parser", lambda v: C.parse_rag_parser(str(v))),
            (
                "embed_provider",
                "rag_embed_provider",
                lambda v: C.parse_rag_embed_provider(str(v)),
            ),
            ("embed_base_url", "rag_embed_base_url", lambda v: str(v).strip()),
            ("embed_api_base", "rag_embed_api_base", lambda v: str(v).strip()),
            ("embed_batch_size", "rag_embed_batch_size", lambda v: max(1, int(v))),
            ("chunk_chars", "rag_chunk_chars", lambda v: max(200, int(v))),
            ("chunk_overlap", "rag_chunk_overlap", lambda v: max(0, int(v))),
            ("top_k", "rag_top_k", lambda v: max(1, int(v))),
            (
                "max_context_chars",
                "rag_max_context_chars",
                lambda v: max(1000, int(v)),
            ),
            ("hybrid", "rag_hybrid", bool),
            ("abstracts", "rag_abstracts", bool),
            ("model", "rag_model", lambda v: str(v).strip()),
            ("focus", "rag_focus", lambda v: C.parse_rag_focus(str(v))),
            ("dest", "rag_dest", lambda v: C.parse_dest(str(v), key="[rag].dest")),
            ("extract_questions_llm", "rag_extract_questions_llm", bool),
            ("ask_mode", "rag_ask_mode", lambda v: C.parse_rag_ask_mode(str(v))),
            (
                "max_chunks_per_item",
                "rag_max_chunks_per_item",
                lambda v: max(1, int(v)),
            ),
            ("overfetch", "rag_overfetch", lambda v: max(1, int(v))),
            ("evidence_k", "rag_evidence_k", lambda v: max(1, int(v))),
            (
                "answer_max_sources",
                "rag_answer_max_sources",
                lambda v: max(1, int(v)),
            ),
            (
                "relevance_cutoff",
                "rag_relevance_cutoff",
                lambda v: max(0, min(10, int(v))),
            ),
            ("summary_model", "rag_summary_model", lambda v: str(v).strip()),
            (
                "summary_concurrency",
                "rag_summary_concurrency",
                lambda v: max(1, int(v)),
            ),
            (
                "summary_length",
                "rag_summary_length",
                lambda v: str(v).strip() or "about 80 words",
            ),
            (
                "evidence_fallback",
                "rag_evidence_fallback",
                lambda v: C.parse_rag_evidence_fallback(str(v)),
            ),
            (
                "query_variants",
                "rag_query_variants",
                lambda v: max(1, min(4, int(v))),
            ),
            (
                "insufficient_retries",
                "rag_insufficient_retries",
                lambda v: max(0, min(2, int(v))),
            ),
            ("cite_hops", "rag_cite_hops", lambda v: max(0, min(2, int(v)))),
            ("cite_scope", "rag_cite_scope", lambda v: C.parse_rag_cite_scope(str(v))),
            (
                "mmr_lambda",
                "rag_mmr_lambda",
                lambda v: min(1.0, max(0.0, float(v))),
            ),
            (
                "context_neighbors",
                "rag_context_neighbors",
                lambda v: max(0, int(v)),
            ),
        ],
    )
    if "embed_model" in rag:
        model = str(rag["embed_model"]).strip()
        if not model:
            raise ValueError("config [rag].embed_model is empty")
        cfg.rag_embed_model = model
    if "prompt" in rag:
        cfg.rag_prompt = C._resolve_prompt_path(str(rag["prompt"]), source)
        if cfg.rag_prompt == "default":
            cfg.rag_prompt = ""
    cfg.rag_chunk_overlap = min(cfg.rag_chunk_overlap, cfg.rag_chunk_chars // 2)


def apply_extract_sections(raw: dict[str, Any], cfg: "Config", source: Path) -> None:
    C = _mod()
    table = raw.get("extract_sections")
    if not isinstance(table, dict):
        return
    C._apply_config_table(
        table,
        cfg,
        [
            ("llm", "extract_sections_llm", bool),
            ("raw_map", "extract_sections_raw_map", bool),
            (
                "max_field_chars",
                "extract_sections_max_field_chars",
                lambda v: max(500, int(v)),
            ),
        ],
    )
    if "headings" in table:
        cfg.extract_sections_headings = C._resolve_prompt_path(
            str(table["headings"]), source
        )
        if cfg.extract_sections_headings == "default":
            cfg.extract_sections_headings = ""
    if "fields" in table:
        cfg.extract_sections_fields = C._snowball_strs(table["fields"])


def apply_mendeley(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    men = raw.get("mendeley")
    if not isinstance(men, dict):
        return
    C._apply_config_table(
        men,
        cfg,
        [
            ("client_id", "mendeley_client_id", lambda v: str(v).strip()),
            ("client_secret", "mendeley_client_secret", lambda v: str(v).strip()),
        ],
    )
    if "redirect_uri" in men and men["redirect_uri"]:
        cfg.mendeley_redirect_uri = str(men["redirect_uri"]).strip()


def apply_endnote(raw: dict[str, Any], cfg: "Config", source: Path) -> None:
    en = raw.get("endnote")
    if isinstance(en, dict) and en.get("library"):
        lib = Path(str(en["library"])).expanduser()
        if not lib.is_absolute():
            lib = (source.parent / lib).resolve()
        cfg.endnote_library = lib


def apply_openalex_store(raw: dict[str, Any], cfg: "Config") -> None:
    _mod()._apply_config_table(
        raw.get("openalex_store"),
        cfg,
        [
            (
                "backend",
                "openalex_store_backend",
                lambda v: str(v).strip().lower(),
            ),
            ("ssh_host", "openalex_store_ssh_host", lambda v: str(v).strip()),
            ("ssh_user", "openalex_store_ssh_user", lambda v: str(v).strip()),
            ("parquet_glob", "openalex_store_parquet_glob", lambda v: str(v).strip()),
            (
                "cites_index_glob",
                "openalex_store_cites_index_glob",
                lambda v: str(v).strip(),
            ),
            (
                "snapshot_date",
                "openalex_store_snapshot_date",
                lambda v: str(v).strip()[:10],
            ),
            (
                "duckdb_bin",
                "openalex_store_duckdb_bin",
                lambda v: str(v).strip() or "duckdb",
            ),
            ("timeout_s", "openalex_store_timeout_s", lambda v: max(1.0, float(v))),
            (
                "fail_limit",
                "openalex_store_fail_limit",
                lambda v: max(1, int(v)),
            ),
            (
                "build_timeout_s",
                "openalex_store_build_timeout_s",
                lambda v: max(60.0, float(v)),
            ),
        ],
    )


def apply_searxng(raw: dict[str, Any], cfg: "Config") -> None:
    searx = raw.get("searxng")
    if isinstance(searx, dict) and searx.get("base_url"):
        cfg.searxng_base_url = str(searx["base_url"]).strip().rstrip("/")


def apply_keepup(raw: dict[str, Any], cfg: "Config") -> None:
    keepup = raw.get("keepup")
    if not isinstance(keepup, dict):
        return
    if "interval_days" in keepup:
        cfg.keepup_interval_days = max(0, int(keepup["interval_days"]))


def apply_precedent(raw: dict[str, Any], cfg: "Config") -> None:
    C = _mod()
    C._apply_config_table(
        raw.get("precedent"),
        cfg,
        [
            ("held_k", "precedent_held_k", lambda v: max(1, int(v))),
            ("public_k", "precedent_public_k", lambda v: max(1, int(v))),
            ("search_keywords", "precedent_search_keywords", bool),
        ],
    )


def _positive_int_tuple(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, int):
        return (max(1, raw),)
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        return tuple(max(1, int(part)) for part in parts)
    if isinstance(raw, list):
        return tuple(max(1, int(part)) for part in raw)
    return ()


def apply_ui(raw: dict[str, Any], cfg: "Config") -> None:
    ui = raw.get("ui")
    if not isinstance(ui, dict):
        return
    C = _mod()
    default = cfg.ui_library_page_size
    sizes = cfg.ui_library_page_sizes
    if "library_page_size" in ui:
        default = max(1, int(ui["library_page_size"]))
    if "library_page_sizes" in ui:
        parsed = _positive_int_tuple(ui["library_page_sizes"])
        if parsed:
            sizes = parsed
    cfg.ui_library_page_size, cfg.ui_library_page_sizes = (
        C.normalize_ui_library_page_sizes(default, sizes)
    )
    mode = str(ui.get("attach_mode") or "").strip().lower()
    if mode in {"manual", "auto"}:
        cfg.ui_attach_mode = mode
    edit = str(ui.get("citation_map_edit") or "").strip().lower()
    if edit in {"sidebar", "popup", "both", "off"}:
        cfg.ui_citation_map_edit = edit
    if "citation_map_auto_search" in ui:
        cfg.ui_citation_map_auto_search = bool(ui["citation_map_auto_search"])
    remove = str(ui.get("citation_map_remove") or "").strip().lower()
    if remove in {"trash", "remove_from_collection"}:
        cfg.ui_citation_map_remove = remove
    network = str(ui.get("coauthor_network") or "").strip().lower()
    if network in {"on", "off"}:
        cfg.ui_coauthor_network = network


def apply_prompt_paths(cfg: "Config", source: Path) -> None:
    C = _mod()
    cfg.summarize_prompt_template = C._resolve_prompt_path(
        cfg.summarize_prompt_template, source
    )
    cfg.synthesize_prompt_template = C._resolve_prompt_path(
        cfg.synthesize_prompt_template, source
    )
    if cfg.critique_reviewers:
        cfg.critique_reviewers = tuple(
            C.CritiqueReviewer(
                id=row.id,
                model=row.model,
                prompt=C._resolve_prompt_path(row.prompt, source),
                max_tokens=row.max_tokens,
            )
            for row in cfg.critique_reviewers
        )
    if cfg.rewrite_specialists:
        from .rewrite_areas import RewriteArea

        cfg.rewrite_specialists = tuple(
            RewriteArea(
                id=row.id,
                model=row.model,
                prompt=C._resolve_prompt_path(row.prompt, source),
                codes=row.codes,
            )
            for row in cfg.rewrite_specialists
        )
    if cfg.ste_word_list_path is not None and not cfg.ste_word_list_path.is_absolute():
        cfg.ste_word_list_path = (source.parent / cfg.ste_word_list_path).resolve()
    if (
        cfg.critique_vale_config is not None
        and not cfg.critique_vale_config.is_absolute()
    ):
        cfg.critique_vale_config = (source.parent / cfg.critique_vale_config).resolve()
