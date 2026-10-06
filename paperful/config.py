"""Configuration loading for paperful."""

from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .playbooks import (
    GreyPlaybook,
    load_pack_dir,
    merge_playbooks,
    playbook_from_dict,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Sci-Hub is opt-in (legal grey zone in some jurisdictions). Add "scihub" to
# `sources` or pass --scihub; it is not in the default list.
# Google Scholar is also opt-in: CAPTCHA / session login ambers first-run doctor
# when it sits in the default list. Add "scholar" to `sources` when you want it.
DEFAULT_SOURCES = [
    "unpaywall",
    "openalex",
    "arxiv",
    "biorxiv",
    "europepmc",
    "semanticscholar",
    "core",
    "openaire",
    "direct",
    "ezproxy",
    "htmlpdf",
]
# Open access + campus EZProxy only (no Scholar, no Sci-Hub) — suitable for EOI / policy-sensitive runs.
# Same list as DEFAULT_SOURCES today: Scholar and Sci-Hub are already opt-in.
EOI_SOURCES = [
    "unpaywall",
    "openalex",
    "arxiv",
    "biorxiv",
    "europepmc",
    "semanticscholar",
    "core",
    "openaire",
    "direct",
    "ezproxy",
    "htmlpdf",
]
# No campus login. Drops ezproxy; htmlpdf stays (it does not need EZProxy).
OA_SOURCES = [name for name in DEFAULT_SOURCES if name != "ezproxy"]
SOURCE_PRESETS: dict[str, list[str]] = {"eoi": EOI_SOURCES, "oa": OA_SOURCES}
KNOWN_MANAGERS = ("zotero", "mendeley", "endnote")
DEFAULT_MIRRORS = [
    "sci-hub.ru",
    "sci-hub.ren",
    "sci-hub.box",
    "sci-hub.se",
    "sci-hub.st",
]
SCIHUB_DISCLAIMER = (
    "Sci-Hub occupies a legal grey zone in some jurisdictions. "
    "You are responsible for complying with the laws that apply to you. "
    "The authors and distributors of this tool do not encourage copyright infringement."
)
RECOVER_DISCLAIMER = (
    "Browser recovery is experimental. You are responsible for publisher terms "
    "and applicable law. Page content may be sent to a remote LLM; using a local "
    "LLM does not send page content off this machine."
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class Config:
    email: str = ""
    out_dir: Path = Path("out")
    state_dir: Path = Path("state")
    manager: str = "zotero"
    mendeley_client_id: str = ""
    mendeley_client_secret: str = ""
    mendeley_redirect_uri: str = "http://127.0.0.1:8765/callback"
    endnote_library: Path | None = None
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    scihub_mirrors: list[str] = field(default_factory=lambda: list(DEFAULT_MIRRORS))
    delay_scihub_s: tuple[float, float] = (3.0, 8.0)
    concurrency_oa: int = 4
    min_pdf_bytes: int = 10_000
    # One-page density gate: soft-reject sparse stubs; hold dense one-pagers for admit.
    gate_short_pdfs: bool = True
    short_pdf_min_words: int = 200
    crossref_min_score: float = 0.90
    doi_suspect_score: float = 0.70
    verify_doi: bool = True
    core_api_key: str = ""
    attach: bool = True
    app_name: str = "paperful"
    mirror_failures_before_skip: int = 3
    source_routing: bool = (
        True  # skip sources that look inapplicable from item metadata
    )
    fetch_order: str = "policy"  # policy | list
    scholar_when: str = "auto"  # auto | phase | interleave
    serpapi_enabled: bool = False
    serpapi_max_calls: int = 20  # 0 = no cap; counts paid Scholar searches this run
    handoff_scholar: bool = True
    request_channels: str = "off"  # off | rg | email | both | rg_then_email_after_days
    request_email_after_days: int = 14
    request_rg_override: bool | None = None
    twenty_enabled: bool = False
    twenty_base_url: str = ""
    twenty_lookup_on_preflight: bool = False
    twenty_retry_max: int = 8
    twenty_retry_base_seconds: float = 1.0
    twenty_sync_note_title: str = "Paperful"
    twenty_provenance_keyword: str = "paperful"
    twenty_fetch_listing_max: int = 20
    twenty_writeback_listings: bool = False
    circuit_breaker_threshold: int = (
        3  # captcha/block failures before a source pauses, then one probe
    )
    user_agent: str = USER_AGENT
    # Campus EZProxy (e.g. Sciences Po). Empty base disables the source.
    ezproxy_base: str = ""
    # After a run, pause on a TTY to re-login and retry session-expired items.
    ezproxy_relogin: bool = True
    ezproxy_cookies: Path | None = (
        None  # Netscape cookies.txt; default state/ezproxy-cookies.txt
    )
    scholar_cookies: Path | None = (
        None  # Netscape cookies.txt; default state/scholar-cookies.txt
    )
    # Grey-lit PDF playbooks: builtin ocean/gov pack + optional dir packs + [[grey_playbooks]].
    grey_playbooks_builtin: bool = True
    grey_playbooks_dir: Path | None = None
    grey_playbooks: list[GreyPlaybook] = field(default_factory=list)
    config_path: Path | None = None
    # Learned publisher recipes: gated logs wins; auto writes packs/learned.toml.
    playbooks_promote: str = "gated"  # gated | auto
    playbooks_auto_min_hits: int = 2
    # Named run configs from [profiles.*]. Not grey-lit playbooks.
    run_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    # LLM (local-first Ollama; LiteLLM optional via paperful[llm])
    llm_enabled: bool = False
    llm_provider: str = "ollama"  # ollama | litellm
    llm_model: str = "qwen2.5:7b"
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_api_base: str = ""
    llm_allow_remote: bool = False
    llm_timeout_s: float = 120.0
    llm_max_num_ctx: int = 32_768
    mirror_pdfs: str = "all"  # all | lazy | none
    mirror_gone: str = "mark"  # mark | trash: an item that left the library
    mirror_refresh: str = "auto"  # auto | manual: refresh before a command reads
    browser_agent_max_steps: int = 20
    browser_agent_max_wall_s: float = 300.0
    browser_agent_model: str = ""
    browser_agent_fallback_model: str = ""
    browser_agent_during_run: bool = True
    browser_agent_use_vision: bool = False
    browser_agent_use_thinking: bool = True
    fix_metadata_llm_title: bool = False
    lint_llm_pdf_match: bool = False
    lint_llm_pdf_match_min_confidence: float = 0.6
    summarize_prompt_template: str = "default"
    summarize_max_context_chars: int = 24_000
    summarize_tag: str = "paperful-summary"
    summarize_dest: str = "both"  # disk | zotero | both
    summarize_order: str = "library"  # library | newest | oldest
    synthesize_prompt_template: str = "default"
    synthesize_max_context_chars: int = 24_000
    synthesize_tag: str = "paperful-report"
    synthesize_dest: str = "both"  # disk | zotero | both
    synthesize_timeout_s: float = 0.0  # 0 → max(llm.timeout_s, 300)
    gaps_handoff: str = "list"  # list | tabs | walk | watch
    gaps_downloads_dir: str = ""  # empty → ~/Downloads
    # PDF drop folder for handoff watch / `paperful inbox` (not snowball inbox.jsonl).
    inbox_dir: str = ""  # empty → feature off
    inbox_watch_after_handoff: bool = True
    inbox_poll_seconds: float = 2.0
    inbox_settle_seconds: float = 1.5
    inbox_idle_seconds: float = 0.0  # 0 → wait forever (Ctrl+C)
    inbox_match: str = "doi_only"  # doi_only | doi+title | doi+title+ocr | full
    inbox_quarantine_after_s: float = 0.0  # 0 → unmatched immediately
    inbox_ocr_for_match: bool = False
    inbox_llm_match: str = "off"  # off | when_thin | always
    inbox_llm_match_min_confidence: float = 0.75
    inbox_llm_auto_attach_min: float = 0.92
    inbox_model: str = ""
    inbox_provider: str = ""
    inbox_create: str = "attach_only"  # attach_only | create_gated | create_auto
    inbox_title_resolve: bool = False
    inbox_manager_metadata_s: float = 0.0
    # Academic HTML→PDF. off leaves journals alone. gated writes a proposal.
    htmlpdf_academic: str = "off"  # off | gated | auto
    htmlpdf_upgrade: bool = False  # run retries snapshot-only items
    htmlpdf_keep_snapshot: bool = False  # leave the print beside a native PDF
    ingest_default_tags: tuple[str, ...] = ()
    ingest_dedupe_scope: str = "library"
    snowball_enabled: bool = False
    snowball_max_candidates: int = 200
    snowball_per_hop_limit: int = 50
    snowball_per_hop_rank: str = "most-cited"  # most-cited | least-cited | random
    snowball_depth: int = 1
    snowball_direction: str = "refs"
    snowball_keyword_limit: int = 3
    snowball_keyword_hop_limit: int = 50
    snowball_keyword_min_score: float = 0.0
    snowball_gate: str = "dry-run"
    snowball_target_collection: str = ""
    snowball_fetch_pdfs: str = "off"  # off | fast | full
    snowball_dedupe_scope: str = "library"  # library | collection | none
    snowball_tag_prefix: str = "paperful-snowball"
    snowball_default_tags: tuple[str, ...] = ()
    snowball_types: tuple[str, ...] = ()
    snowball_oa_only: bool = False
    # Opt-in OpenAlex snapshot store (SSH+DuckDB v1). Empty backend = API only.
    openalex_store_backend: str = ""  # ssh_duckdb | (later local_duckdb | http)
    openalex_store_ssh_host: str = ""
    openalex_store_ssh_user: str = ""
    openalex_store_parquet_glob: str = ""
    openalex_store_duckdb_bin: str = "duckdb"
    openalex_store_timeout_s: float = 120.0
    snowball_venue_include: tuple[str, ...] = ()
    snowball_venue_exclude: tuple[str, ...] = ()
    snowball_languages: tuple[str, ...] = ()
    snowball_min_seed_citations: int = 0
    snowball_note_provenance: bool = True
    snowball_backends: tuple[str, ...] = (
        "openalex",
        "crossref",
        "semanticscholar",
        "orcid",
        "europepmc",
        "pdf",
    )
    snowball_approve_each_max: int = 20
    snowball_hybrid_seeds: int = 5
    snowball_refine: bool = False
    snowball_dedupe_after: str = "off"  # off | classify | apply
    snowball_author_site_preflight: bool = False
    snowball_author_site_max_authors: int = 15
    snowball_author_site_max_queries: int = 20
    searxng_base_url: str = ""
    # Where plain-language lines are written. note | tag | off.
    remarks_surface: str = "note"
    oa_honesty_stamp_fields: tuple[str, ...] = ("license", "oa_status", "version")
    oa_honesty_license_block: tuple[str, ...] = ()
    # OCRmyPDF text layer for scanned PDFs. languages is a Tesseract -l list.
    ocr_languages: str = "eng"
    ocr_timeout_s: float = 600.0
    # Library index for `paperful rag` / `paperful ask`. Reads the mirror only.
    rag_enabled: bool = False
    rag_auto_ingest: bool = (
        False  # index new PDFs after run / attach / inbox / snapshot / ocr
    )
    rag_ocr: str = "auto"  # auto | off. auto rewrites scanned PDFs under out/
    rag_parser: str = "light"  # light | docling
    rag_embed_provider: str = "ollama"  # ollama | litellm
    rag_embed_model: str = "nomic-embed-text"
    rag_embed_base_url: str = ""  # empty → llm.base_url
    rag_embed_api_base: str = ""  # empty → llm.api_base
    rag_embed_batch_size: int = 32
    rag_chunk_chars: int = 2048
    rag_chunk_overlap: int = 256
    rag_top_k: int = 10
    rag_max_context_chars: int = 24_000
    rag_hybrid: bool = True  # vector + full-text; falls back to vector only
    rag_abstracts: bool = True  # index the abstract when an item has no readable PDF
    rag_model: str = ""  # chat model for `ask`; empty → llm.model
    rag_focus: str = "default"  # default | questions | gaps | methods | answered
    rag_prompt: str = ""  # custom system prompt file for ask; empty → focus preset
    rag_dest: str = "disk"  # disk | zotero | both — batch note writes (needs --apply)
    rag_extract_questions_llm: bool = False  # LLM lane for `rag questions`
    # Attachment hygiene. Off until `paperful attachments --apply`.
    attachments_fix_broken: bool = False
    attachments_merge_files: bool = False
    attachments_rename: bool = False
    attachments_link: bool = False

    def __post_init__(self) -> None:
        # Resolve pack+user once so Config() in tests gets the builtin examples.
        if not self.grey_playbooks and self.grey_playbooks_builtin:
            self.grey_playbooks = merge_playbooks(True, ())

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.jsonl"

    @property
    def patches_path(self) -> Path:
        return self.state_dir / "metadata-patches.jsonl"

    @property
    def dedupe_applied_path(self) -> Path:
        return self.state_dir / "dedupe-applied.jsonl"

    @property
    def versions_applied_path(self) -> Path:
        return self.state_dir / "versions-applied.jsonl"

    @property
    def pdf_cache_dir(self) -> Path:
        return self.state_dir / "pdf-cache"

    @property
    def local_key_path(self) -> Path:
        return self.state_dir / "zotero-local-api-key.json"

    @property
    def ezproxy_cookie_path(self) -> Path:
        return self.ezproxy_cookies or (self.state_dir / "ezproxy-cookies.txt")

    @property
    def scholar_cookie_path(self) -> Path:
        return self.scholar_cookies or (self.state_dir / "scholar-cookies.txt")

    @property
    def summaries_dir(self) -> Path:
        return self.state_dir / "summaries"

    @property
    def reports_dir(self) -> Path:
        return self.state_dir / "reports"

    @property
    def rag_dir(self) -> Path:
        return self.state_dir / "rag"

    @property
    def inbox_path(self) -> Path | None:
        """Resolved PDF drop folder, or None when ``[inbox].dir`` is unset."""
        raw = (self.inbox_dir or "").strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    @property
    def inbox_seen_path(self) -> Path:
        return self.state_dir / "inbox-seen.jsonl"

    @property
    def inbox_holds_path(self) -> Path:
        return self.state_dir / "inbox-holds.json"

    @property
    def inbox_proposals_dir(self) -> Path:
        return self.state_dir / "inbox" / "proposals"

    @property
    def htmlpdf_proposals_dir(self) -> Path:
        return self.state_dir / "htmlpdf" / "proposals"

    @property
    def author_requests_path(self) -> Path:
        return self.state_dir / "author-requests.jsonl"

    @property
    def author_contacts_dir(self) -> Path:
        return self.state_dir / "author-contacts"

    def effective_synthesize_timeout(self) -> float:
        if self.synthesize_timeout_s > 0:
            return self.synthesize_timeout_s
        return max(self.llm_timeout_s, 300.0)


def _candidate_paths(explicit: Path | None) -> list[Path]:
    if explicit:
        return [explicit]
    here = Path(__file__).resolve().parent.parent
    return [
        Path.cwd() / "config.toml",
        here / "config.toml",
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "paperful"
        / "config.toml",
    ]


def load_config(path: Path | None = None) -> Config:
    """Load config.toml from an explicit path or the usual locations; defaults otherwise."""
    for candidate in _candidate_paths(path):
        if candidate.is_file():
            with candidate.open("rb") as fh:
                raw: dict[str, Any] = tomllib.load(fh)
            return _from_dict(raw, candidate)
    if path is not None:
        raise FileNotFoundError(path)
    return Config()


def _from_dict(raw: dict[str, Any], source: Path) -> Config:
    cfg = Config(config_path=source)
    if "email" in raw:
        cfg.email = str(raw["email"])
    if "manager" in raw:
        cfg.manager = str(raw["manager"]).strip().lower() or "zotero"
    if "out_dir" in raw:
        cfg.out_dir = Path(str(raw["out_dir"])).expanduser()
    if "state_dir" in raw:
        cfg.state_dir = Path(str(raw["state_dir"])).expanduser()
    if "sources" in raw:
        cfg.sources = [str(s) for s in raw["sources"]]
    if "scihub_mirrors" in raw:
        cfg.scihub_mirrors = [str(m) for m in raw["scihub_mirrors"]]
    if "delay_scihub_s" in raw:
        lo, hi = raw["delay_scihub_s"]
        cfg.delay_scihub_s = (float(lo), float(hi))
    if "concurrency_oa" in raw:
        cfg.concurrency_oa = max(1, int(raw["concurrency_oa"]))
    if "min_pdf_bytes" in raw:
        cfg.min_pdf_bytes = int(raw["min_pdf_bytes"])
    if "gate_short_pdfs" in raw:
        cfg.gate_short_pdfs = bool(raw["gate_short_pdfs"])
    if "short_pdf_min_words" in raw:
        cfg.short_pdf_min_words = max(0, int(raw["short_pdf_min_words"]))
    if "crossref_min_score" in raw:
        cfg.crossref_min_score = float(raw["crossref_min_score"])
    if "doi_suspect_score" in raw:
        cfg.doi_suspect_score = float(raw["doi_suspect_score"])
    if "verify_doi" in raw:
        cfg.verify_doi = bool(raw["verify_doi"])
    if "core_api_key" in raw:
        cfg.core_api_key = str(raw["core_api_key"]).strip()
    if "attach" in raw:
        cfg.attach = bool(raw["attach"])
    if "app_name" in raw:
        cfg.app_name = str(raw["app_name"])
    if "mirror_failures_before_skip" in raw:
        cfg.mirror_failures_before_skip = int(raw["mirror_failures_before_skip"])
    if "source_routing" in raw:
        cfg.source_routing = bool(raw["source_routing"])
    if "circuit_breaker_threshold" in raw:
        cfg.circuit_breaker_threshold = max(1, int(raw["circuit_breaker_threshold"]))
    if "user_agent" in raw:
        cfg.user_agent = str(raw["user_agent"])
    if "ezproxy_base" in raw:
        cfg.ezproxy_base = str(raw["ezproxy_base"]).strip()
    if "ezproxy_relogin" in raw:
        cfg.ezproxy_relogin = bool(raw["ezproxy_relogin"])
    if "ezproxy_cookies" in raw and raw["ezproxy_cookies"]:
        cfg.ezproxy_cookies = Path(str(raw["ezproxy_cookies"])).expanduser()
    if "scholar_cookies" in raw and raw["scholar_cookies"]:
        cfg.scholar_cookies = Path(str(raw["scholar_cookies"])).expanduser()
    if "grey_playbooks_builtin" in raw:
        cfg.grey_playbooks_builtin = bool(raw["grey_playbooks_builtin"])
    if "grey_playbooks_dir" in raw and raw["grey_playbooks_dir"]:
        cfg.grey_playbooks_dir = Path(str(raw["grey_playbooks_dir"])).expanduser()
    user_playbooks: list[GreyPlaybook] = []
    for i, row in enumerate(raw.get("grey_playbooks") or []):
        if not isinstance(row, dict):
            warnings.warn(
                f"config grey_playbooks[{i}] ignored: expected a table, got {type(row).__name__}",
                UserWarning,
                stacklevel=2,
            )
            continue
        pb = playbook_from_dict(row)
        if pb:
            user_playbooks.append(pb)
        else:
            name = row.get("name", "?")
            kind = row.get("kind", "?")
            warnings.warn(
                f"config grey_playbooks entry {name!r} (kind={kind!r}) ignored: "
                "need name and kind in {{rewrite, scrape, synthesize}}",
                UserWarning,
                stacklevel=2,
            )
    if not cfg.out_dir.is_absolute():
        cfg.out_dir = (source.parent / cfg.out_dir).resolve()
    if not cfg.state_dir.is_absolute():
        cfg.state_dir = (source.parent / cfg.state_dir).resolve()
    if cfg.grey_playbooks_dir is not None and not cfg.grey_playbooks_dir.is_absolute():
        cfg.grey_playbooks_dir = (source.parent / cfg.grey_playbooks_dir).resolve()
    if cfg.ezproxy_cookies is None:
        cfg.ezproxy_cookies = cfg.state_dir / "ezproxy-cookies.txt"
    elif not cfg.ezproxy_cookies.is_absolute():
        cfg.ezproxy_cookies = (source.parent / cfg.ezproxy_cookies).resolve()
    if cfg.scholar_cookies is None:
        cfg.scholar_cookies = cfg.state_dir / "scholar-cookies.txt"
    elif not cfg.scholar_cookies.is_absolute():
        cfg.scholar_cookies = (source.parent / cfg.scholar_cookies).resolve()
    # Builtin → dir packs → inline [[grey_playbooks]]; same name wins later.
    extra = (
        load_pack_dir(cfg.grey_playbooks_dir)
        if cfg.grey_playbooks_dir is not None
        else []
    )
    cfg.grey_playbooks = merge_playbooks(
        cfg.grey_playbooks_builtin, user_playbooks, extra=extra
    )
    cfg.run_profiles = _parse_run_profiles(raw)
    _apply_snowball(raw.get("snowball"), cfg)
    _apply_nested_tables(raw, cfg, source)
    return cfg


def parse_dedupe_after(value: Any) -> str:
    """Post-create snowball hygiene: off, classify, or apply."""
    if value is None or value is False:
        return "off"
    if value is True:
        return "classify"
    text = str(value).strip().lower()
    if text in {"", "0", "false", "no", "off", "none"}:
        return "off"
    if text in {"classify", "pack", "dry-run"}:
        return "classify"
    if text in {"apply", "merge"}:
        return "apply"
    raise ValueError("dedupe_after must be off, classify, or apply")


def parse_fetch_pdfs(value: Any) -> str:
    """Snowball PDF mode: off (metadata only), fast (first pass), or full (then the run stack)."""
    if value is None or value is False:
        return "off"
    if value is True:
        return "fast"
    text = str(value).strip().lower()
    if text in {"", "0", "false", "no", "off", "none"}:
        return "off"
    if text in {"1", "true", "yes", "on", "fast"}:
        return "fast"
    if text == "full":
        return "full"
    raise ValueError("fetch_pdfs must be off, fast, or full.")


def parse_cap(value: Any) -> int:
    """Snowball numeric cap. ``all`` / ``unlimited`` / ``0`` → 0 (no cap)."""
    if value is None:
        raise ValueError("cap is required")
    if isinstance(value, bool):
        raise ValueError("cap must be a number or all")
    if isinstance(value, int):
        return 0 if value <= 0 else value
    if isinstance(value, float):
        return 0 if value <= 0 else int(value)
    text = str(value).strip().lower()
    if text in {"all", "unlimited", "0"}:
        return 0
    if text.isdigit():
        number = int(text)
        return 0 if number <= 0 else number
    raise ValueError("cap must be a positive number or all")


def parse_per_hop_rank(value: Any) -> str:
    """How a numeric per_hop_limit picks neighbours."""
    text = str(value or "most-cited").strip().lower().replace("_", "-")
    if text in {"most-cited", "most", "cited", "top"}:
        return "most-cited"
    if text in {"least-cited", "least", "bottom"}:
        return "least-cited"
    if text in {"random", "sample", "shuffle"}:
        return "random"
    raise ValueError("per_hop_rank must be most-cited, least-cited, or random")


def _apply_snowball(raw: Any, cfg: Config) -> None:
    if not isinstance(raw, dict):
        return
    if "enabled" in raw:
        cfg.snowball_enabled = bool(raw["enabled"])
    if "max_candidates" in raw:
        cfg.snowball_max_candidates = parse_cap(raw["max_candidates"])
    if "per_hop_limit" in raw:
        cfg.snowball_per_hop_limit = parse_cap(raw["per_hop_limit"])
    if "per_hop_rank" in raw and raw["per_hop_rank"]:
        cfg.snowball_per_hop_rank = parse_per_hop_rank(raw["per_hop_rank"])
    if "depth" in raw:
        cfg.snowball_depth = int(raw["depth"])
    if "direction" in raw and raw["direction"]:
        cfg.snowball_direction = str(raw["direction"]).strip()
    if "keyword_limit" in raw:
        from .snowball.expand import parse_keyword_limit

        cfg.snowball_keyword_limit = parse_keyword_limit(raw["keyword_limit"])
    if "keyword_hop_limit" in raw:
        from .snowball.expand import parse_keyword_hop_limit

        cfg.snowball_keyword_hop_limit = parse_keyword_hop_limit(
            raw["keyword_hop_limit"]
        )
    if "keyword_min_score" in raw:
        from .snowball.expand import parse_keyword_min_score

        cfg.snowball_keyword_min_score = parse_keyword_min_score(
            raw["keyword_min_score"]
        )
    if "gate" in raw and raw["gate"]:
        cfg.snowball_gate = str(raw["gate"]).strip()
    if "target_collection" in raw and raw["target_collection"]:
        cfg.snowball_target_collection = str(raw["target_collection"]).strip()
    if "fetch_pdfs" in raw:
        cfg.snowball_fetch_pdfs = parse_fetch_pdfs(raw["fetch_pdfs"])
    if "dedupe_scope" in raw and raw["dedupe_scope"]:
        cfg.snowball_dedupe_scope = str(raw["dedupe_scope"]).strip()
    if "tag_prefix" in raw and raw["tag_prefix"]:
        cfg.snowball_tag_prefix = str(raw["tag_prefix"]).strip()
    if "default_tags" in raw:
        cfg.snowball_default_tags = _snowball_strs(raw["default_tags"])
    if "types" in raw:
        cfg.snowball_types = _snowball_strs(raw["types"])
    if "oa_only" in raw:
        cfg.snowball_oa_only = bool(raw["oa_only"])
    if "venue_include" in raw:
        cfg.snowball_venue_include = _snowball_strs(raw["venue_include"])
    if "venue_exclude" in raw:
        cfg.snowball_venue_exclude = _snowball_strs(raw["venue_exclude"])
    if "languages" in raw:
        cfg.snowball_languages = _snowball_strs(raw["languages"])
    if "min_seed_citations" in raw:
        cfg.snowball_min_seed_citations = int(raw["min_seed_citations"])
    if "note_provenance" in raw:
        cfg.snowball_note_provenance = bool(raw["note_provenance"])
    if "backends" in raw:
        cfg.snowball_backends = _snowball_strs(raw["backends"])
    if "approve_each_max" in raw:
        cfg.snowball_approve_each_max = int(raw["approve_each_max"])
    if "hybrid_seeds" in raw:
        cfg.snowball_hybrid_seeds = int(raw["hybrid_seeds"])
    if "refine" in raw:
        cfg.snowball_refine = bool(raw["refine"])
    if "dedupe_after" in raw and raw["dedupe_after"] is not None:
        cfg.snowball_dedupe_after = parse_dedupe_after(raw["dedupe_after"])
    if "author_site_preflight" in raw:
        cfg.snowball_author_site_preflight = bool(raw["author_site_preflight"])
    if "author_site_max_authors" in raw:
        cfg.snowball_author_site_max_authors = int(raw["author_site_max_authors"])
    if "author_site_max_queries" in raw:
        cfg.snowball_author_site_max_queries = int(raw["author_site_max_queries"])


def _snowball_strs(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, list):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return ()


def _parse_run_profiles(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Raw `[profiles.*]` tables. Validated when a profile is selected, not at load."""
    profiles = raw.get("profiles") or {}
    if not profiles:
        return {}
    if not isinstance(profiles, dict):
        warnings.warn(
            f"config profiles ignored: expected a table, got {type(profiles).__name__}",
            UserWarning,
            stacklevel=2,
        )
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, row in profiles.items():
        if isinstance(row, dict):
            out[str(key)] = dict(row)
            continue
        warnings.warn(
            f"config profiles.{key} ignored: expected a table, got {type(row).__name__}",
            UserWarning,
            stacklevel=2,
        )
    return out


_DESTS = frozenset({"disk", "zotero", "both"})
_PDF_MODES = frozenset({"all", "lazy", "none"})
_REMARK_SURFACES = frozenset({"note", "tag", "off"})


def parse_remarks_surface(value: str) -> str:
    """Normalise ``[remarks].surface``. ``note`` is the default."""
    surface = str(value).strip().lower()
    if surface not in _REMARK_SURFACES:
        raise ValueError(
            f"config [remarks].surface {value!r} must be note, tag, or off"
        )
    return surface


def _one_of(name: str, value: Any, allowed: tuple[str, ...]) -> str:
    mode = str(value).strip().lower()
    if mode not in allowed:
        raise ValueError(f"config {name} {value!r} must be {' or '.join(allowed)}")
    return mode


def parse_pdfs(value: str) -> str:
    """Normalise ``[mirror].pdfs``. ``all`` is the default.

    ``all`` copies every PDF the manager holds into its item folder. ``lazy``
    copies one the first time a command needs it. ``none`` keeps manager PDFs
    out of the mirror. ``additional`` is the old name for ``lazy``.
    """
    mode = str(value).strip().lower()
    if mode == "additional":
        return "lazy"
    if mode not in _PDF_MODES:
        raise ValueError(f"config [mirror].pdfs {value!r} must be all, lazy, or none")
    return mode


def parse_playbooks_promote(value: str) -> str:
    key = value.strip().lower()
    if key not in {"gated", "auto"}:
        raise ValueError(f"[playbooks].promote {value!r} must be gated or auto")
    return key


def parse_dest(value: str, *, key: str = "dest") -> str:
    """Normalise a write destination. Blank means both; anything else must be known."""
    dest = str(value).strip().lower()
    if not dest:
        return "both"
    if dest not in _DESTS:
        raise ValueError(f"config {key} {value!r} must be disk, zotero, or both")
    return dest


_RAG_OCR_MODES = frozenset({"auto", "off"})
_RAG_PARSERS = frozenset({"light", "docling"})
_RAG_EMBED_PROVIDERS = frozenset({"ollama", "litellm"})
_RAG_FOCI = frozenset({"default", "questions", "gaps", "methods", "answered"})


def parse_rag_focus(value: str) -> str:
    focus = str(value).strip().lower() or "default"
    if focus not in _RAG_FOCI:
        raise ValueError(
            f"config [rag].focus {value!r} must be one of: "
            + ", ".join(sorted(_RAG_FOCI))
        )
    return focus


def parse_rag_ocr(value: str) -> str:
    """Normalise ``[rag].ocr``. ``auto`` is the default."""
    mode = str(value).strip().lower()
    if mode not in _RAG_OCR_MODES:
        raise ValueError(f"config [rag].ocr {value!r} must be auto or off")
    return mode


def parse_rag_parser(value: str) -> str:
    """Normalise ``[rag].parser``. ``light`` is the default."""
    parser = str(value).strip().lower()
    if parser not in _RAG_PARSERS:
        raise ValueError(f"config [rag].parser {value!r} must be light or docling")
    return parser


def parse_rag_embed_provider(value: str) -> str:
    provider = str(value).strip().lower()
    if provider not in _RAG_EMBED_PROVIDERS:
        raise ValueError(
            f"config [rag].embed_provider {value!r} must be ollama or litellm"
        )
    return provider


_SUMMARIZE_ORDERS = frozenset({"library", "newest", "oldest"})


def parse_summarize_order(value: str, *, key: str = "order") -> str:
    """Normalise summarize queue order. Blank means library (input) order."""
    order = str(value).strip().lower()
    if not order:
        return "library"
    if order not in _SUMMARIZE_ORDERS:
        raise ValueError(f"config {key} {value!r} must be newest, oldest, or library")
    return order


def wants_disk(dest: str) -> bool:
    return dest in ("disk", "both")


def wants_zotero(dest: str) -> bool:
    return dest in ("zotero", "both")


def _resolve_prompt_path(value: str, source: Path) -> str:
    if not value or value == "default":
        return "default"
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (source.parent / path).resolve()
    return str(path)


def _clamp01(value: Any) -> float:
    return min(1.0, max(0.0, float(value)))


def _apply_config_table(
    table: Any,
    cfg: Config,
    fields: list[tuple[str, str, Callable[[Any], Any]]],
) -> None:
    if not isinstance(table, dict):
        return
    for key, attr, coerce in fields:
        if key in table:
            setattr(cfg, attr, coerce(table[key]))


def _apply_nested_tables(raw: dict[str, Any], cfg: Config, source: Path) -> None:
    from .config_tables import apply_nested_tables

    apply_nested_tables(raw, cfg, source)
