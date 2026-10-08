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
    apply_summarize(raw, cfg)
    apply_synthesize(raw, cfg)
    apply_fetch(raw, cfg)
    apply_scholar(raw, cfg)
    apply_serpapi(raw, cfg)
    apply_handoff(raw, cfg)
    apply_request(raw, cfg)
    apply_twenty(raw, cfg)
    apply_gaps(raw, cfg)
    apply_inbox(raw, cfg)
    apply_htmlpdf(raw, cfg)
    apply_ingest(raw, cfg)
    apply_playbooks(raw, cfg)
    apply_mirror(raw, cfg)
    apply_remarks(raw, cfg)
    apply_oa_honesty(raw, cfg)
    apply_attachments(raw, cfg)
    apply_ocr(raw, cfg)
    apply_rag(raw, cfg, source)
    apply_mendeley(raw, cfg)
    apply_endnote(raw, cfg, source)
    apply_openalex_store(raw, cfg)
    apply_searxng(raw, cfg)
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
        ],
    )
    if "dest" in summ:
        cfg.summarize_dest = C.parse_dest(str(summ["dest"]), key="[summarize].dest")
    if "order" in summ:
        cfg.summarize_order = C.parse_summarize_order(
            str(summ["order"]), key="[summarize].order"
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
                "duckdb_bin",
                "openalex_store_duckdb_bin",
                lambda v: str(v).strip() or "duckdb",
            ),
            ("timeout_s", "openalex_store_timeout_s", lambda v: max(1.0, float(v))),
        ],
    )


def apply_searxng(raw: dict[str, Any], cfg: "Config") -> None:
    searx = raw.get("searxng")
    if isinstance(searx, dict) and searx.get("base_url"):
        cfg.searxng_base_url = str(searx["base_url"]).strip().rstrip("/")


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
    cfg.ui_library_page_size, cfg.ui_library_page_sizes = C.normalize_ui_library_page_sizes(
        default, sizes
    )


def apply_prompt_paths(cfg: "Config", source: Path) -> None:
    C = _mod()
    cfg.summarize_prompt_template = C._resolve_prompt_path(
        cfg.summarize_prompt_template, source
    )
    cfg.synthesize_prompt_template = C._resolve_prompt_path(
        cfg.synthesize_prompt_template, source
    )
