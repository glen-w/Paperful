"""Orchestrates: resolve identifier -> OA sources (parallel) -> Sci-Hub (serial) -> save -> attach."""

from __future__ import annotations

import hashlib
import random
import threading
import time
from collections.abc import Callable
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.markup import escape

from .attach import parent_missing
from .provenance import provenance_sentence, provenance_stamp
from .remarks import say
from .circuit import CircuitBreaker
from .config import Config
from .cookies import apply_netscape_cookies
from .download import (
    Download,
    DownloadError,
    fetch_pdf,
    is_fetchable_url,
    is_transport_download_error,
    looks_like_pdf,
)
from .pdfid import doi_from_pdf, probe_pdf_bytes, short_pdf_verdict
from .mirror import pdf_for_key
from .pipeline_attach import attach_after_remap
from .pipeline_browser import release_browser_for_agent, skip_recover_without_lane_failure
from .pipeline_save import commit_download
from .playbooks import looks_like_pdf_url
from .resolve import (
    IdentifierCache,
    is_preprint_doi,
    normalize_doi,
    prepare_identifiers,
    version_link,
)
from .routing import (
    academic_htmlpdf_item,
    is_publisher_url,
    order_run,
    prior_playwright_miss,
    publisher_host,
    sources_for_item,
    with_author_site_lane,
    with_serpapi_lane,
)
from .page_signals import (
    host_label,
    looks_like_dead_vault_miss,
    looks_like_vault_login_miss,
    miss_host,
)
from .session import BrowserSession, vault_cookies_path
from .sources.ezproxy import proxify
from .runreport import (
    ItemOutcome,
    bump,
    bump_nested,
    classify_enrichment,
    error_type_for,
)
from .sources import REGISTRY, Candidate, Context, Outcome
from .store import (
    STATUS_ATTACH_FAILED,
    STATUS_ATTACHED,
    STATUS_CAPTCHA,
    STATUS_ERROR,
    STATUS_NO_IDENTIFIER,
    STATUS_NOT_FOUND,
    STATUS_RETRYABLE,
    REASON_CLOSED,
    REASON_SHORT_PDF,
    REASON_STRICT_PDF_DOI,
    STATUS_OK,
    Manifest,
    Record,
    relpaths,
    resolve_pdf_path,
    save_pdf,
    write_fetch_records,
)
from .zot import Item

# Sources that share a browser/session or are heavy — keep serial & polite.
_SERIAL_SOURCES = frozenset(
    {
        "scihub",
        "ezproxy",
        "htmlpdf",
        "scholar",
        "browser_agent",
        "author_site",
        "serpapi",
    }
)
_DIRECT_PDF_CAP = 12
_LANDING_CAP = 6
# Soft-block vault retries that land on campus CAS; trip EZProxy after this many.
_VAULT_SSO_MISS_THRESHOLD = 2
# Transport blips to one host before treating it as dead for the rest of the run.
_TRANSPORT_DEAD_THRESHOLD = 3


def urls_to_fetch(urls: list[str]) -> list[str]:
    """Prefer direct PDF URLs and allow more of them than landing pages."""
    direct: list[str] = []
    landing: list[str] = []
    for url in urls:
        if not url:
            continue
        bucket = direct if _direct_pdf_url(url) else landing
        if url not in direct and url not in landing:
            bucket.append(url)
    return direct[:_DIRECT_PDF_CAP] + landing[:_LANDING_CAP]


def _direct_pdf_url(url: str) -> bool:
    low = url.lower()
    if looks_like_pdf_url(url) or "pdf=render" in low or "blobtype=pdf" in low:
        return True
    return low.split("?")[0].endswith(".pdf")


def _attach_operator_line(code: str) -> str:
    if code == "quota":
        return (
            "PDF is in out/; free Zotero Storage or empty the trash, then "
            "paperful attach."
        )
    if code == "auth":
        return (
            "Click Always Allow on the host Zotero window "
            "(Docker: the GUI is not in the container)."
        )
    return ""


def make_client(cfg: Config) -> httpx.Client:
    client = httpx.Client(
        headers={"User-Agent": cfg.user_agent, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30,
        limits=httpx.Limits(max_connections=cfg.concurrency_oa + 2),
    )
    apply_netscape_cookies(client, vault_cookies_path(cfg))
    apply_netscape_cookies(client, cfg.ezproxy_cookie_path)
    apply_netscape_cookies(client, cfg.scholar_cookie_path)
    return client


@dataclass
class RunStats:
    ok: int = 0
    not_found: int = 0
    no_identifier: int = 0
    captcha: int = 0
    error: int = 0
    retryable: int = 0
    attached: int = 0
    attach_failed: int = 0
    skipped_manifest: int = 0
    linked_url_skipped: int = 0
    attach_failed_by_code: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    sources_checked: dict[str, dict[str, int]] = field(default_factory=dict)
    fields_corrected: dict[str, int] = field(default_factory=dict)
    errors_by_type: dict[str, int] = field(default_factory=dict)
    items: list[ItemOutcome] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    scope: str = ""
    sources_configured: list[str] = field(default_factory=list)
    sources_disabled: list[str] = field(default_factory=list)

    def bump(self, status: str, source: str | None = None) -> None:
        if hasattr(self, status) and status in {
            "ok",
            "not_found",
            "no_identifier",
            "captcha",
            "error",
            "retryable",
            "attached",
            "attach_failed",
        }:
            setattr(self, status, getattr(self, status) + 1)
        if source and status in (STATUS_OK, STATUS_ATTACHED):
            self.by_source[source] = self.by_source.get(source, 0) + 1

    def note_source(self, name: str, outcome: str) -> None:
        bump_nested(self.sources_checked, name, outcome)

    def note_fields(self, labels: list[str]) -> None:
        for lab in labels:
            bump(self.fields_corrected, lab)

    def note_error(self, err_type: str | None) -> None:
        if err_type:
            bump(self.errors_by_type, err_type)

    def add_item(self, outcome: ItemOutcome) -> None:
        self.items.append(outcome)
        self.note_error(outcome.error_type)

    def drop_outcomes(self, keys: set[str]) -> None:
        """Remove prior outcomes so a second pass does not double-count those items."""
        countable = {
            "ok",
            "not_found",
            "no_identifier",
            "captcha",
            "error",
            "retryable",
            "attached",
            "attach_failed",
        }
        kept: list[ItemOutcome] = []
        for outcome in self.items:
            if outcome.itemKey not in keys:
                kept.append(outcome)
                continue
            if outcome.status in countable:
                current = int(getattr(self, outcome.status, 0))
                setattr(self, outcome.status, max(0, current - 1))
            if outcome.source and outcome.status in (STATUS_OK, STATUS_ATTACHED):
                left = self.by_source.get(outcome.source, 0) - 1
                if left <= 0:
                    self.by_source.pop(outcome.source, None)
                else:
                    self.by_source[outcome.source] = left
            if outcome.error_type:
                left = self.errors_by_type.get(outcome.error_type, 0) - 1
                if left <= 0:
                    self.errors_by_type.pop(outcome.error_type, None)
                else:
                    self.errors_by_type[outcome.error_type] = left
        self.items = kept


def session_expired_items(manifest: Manifest, items: list[Item]) -> list[Item]:
    """Items this run left retryable because the EZProxy session expired."""
    expired: list[Item] = []
    for item in items:
        rec = manifest.get(item.key)
        if rec is None or rec.status != STATUS_RETRYABLE:
            continue
        if "session expired" not in (rec.reason or ""):
            continue
        expired.append(item)
    return expired


def _lane_paused(attempts: list[str]) -> bool:
    return any(
        "skipped(circuit open)" in a
        or "session expired" in a
        or "skipped(bot wall)" in a
        or a == "scholar:skipped(blocked)"
        for a in attempts
    )


def _scholar_blocked(cand: Candidate) -> bool:
    """Google has refused this client; further requests this run only dig deeper."""
    if cand.outcome is Outcome.CAPTCHA:
        return True
    note = cand.note or ""
    return cand.outcome is Outcome.ERROR and note in {"HTTP 429", "HTTP 503"}


def _serpapi_blocked(cand: Candidate) -> bool:
    """Paid Scholar search is out of quota or refused; do not burn the key."""
    if cand.outcome is Outcome.CAPTCHA:
        return True
    note = (cand.note or "").lower()
    if cand.outcome is not Outcome.ERROR:
        return False
    return "429" in note or "quota" in note or "run out" in note


def _is_soft_block_error(exc: DownloadError) -> bool:
    msg = str(exc)
    return "too small" in msg or msg.startswith("not a PDF")


def _drop_snapshot_attachments(attacher: Any, item_key: str, emit: Callable[[str], None]) -> None:
    """Trash htmlpdf snapshot children after a native PDF attaches."""
    from .greyid import is_snapshot_note
    from .zot import is_pdf_attachment

    if attacher is None or not hasattr(attacher, "children"):
        return
    trash = getattr(attacher, "trash_attachment", None)
    if trash is None:
        return
    try:
        children = attacher.children(item_key)
    except Exception as exc:
        emit(f"   [dim]snapshot cleanup skipped[/] {item_key}: {exc}")
        return
    for child in children:
        data = child.get("data") or {}
        if not is_pdf_attachment(data) or not is_snapshot_note(data.get("note")):
            continue
        key = str(child.get("key") or data.get("key") or "")
        if not key:
            continue
        try:
            trash(key)
            emit(f"   [dim]replaced snapshot[/] {item_key} ({key})")
        except Exception as exc:
            emit(f"   [dim]snapshot cleanup skipped[/] {key}: {exc}")


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        manifest: Manifest,
        console: Console,
        sources: list[str] | None = None,
        attacher: Any = None,
        progress: Callable[[], None] | None = None,
        try_all: bool | None = None,
        use_browser: bool = True,
        strict_pdf_doi: bool = False,
        on_ezproxy_down: Callable[[], bool] | None = None,
    ):
        self.cfg = cfg
        self.manifest = manifest
        self.console = console
        self.sources = with_author_site_lane(
            cfg, with_serpapi_lane(cfg, list(sources or cfg.sources))
        )
        self.try_all = try_all if try_all is not None else not cfg.source_routing
        self.attacher = attacher
        self.strict_pdf_doi = strict_pdf_doi
        self.progress = progress or (lambda: None)
        # Rich Progress while `run` is in the fetch bar; used to pause Live for prompts.
        self.live_progress: Any = None
        self.on_ezproxy_down = on_ezproxy_down
        self._use_browser = use_browser
        self.client = make_client(cfg)
        self.browser = BrowserSession(cfg) if use_browser else None
        self.ctx = Context(config=cfg, client=self.client, browser=self.browser)
        self.stats = RunStats()
        self.stats.sources_configured = list(self.sources)
        self._disable_unconfigured_sources()
        self._circuit = CircuitBreaker(cfg.circuit_breaker_threshold)
        self._ezproxy_down = False
        self._ezproxy_down_offered = False
        self._browser_agent_down = False
        self._scholar_down = False
        self._serpapi_down = False
        self._serpapi_calls = 0
        self._serpapi_capped = False
        self._blocked_hosts: set[str] = set()
        self._transport_fail_hosts: dict[str, int] = {}
        self._vault_sso_misses = 0
        self._attach_lock = threading.Lock()
        self._print_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stop = threading.Event()
        self._run_total = 0
        self._item_index: dict[str, int] = {}
        self._id_cache = IdentifierCache()
        self._item_fields: dict[str, list[str]] = {}
        self._pdf_parents: set[str] | None = None
        self._parent_by_doi: dict[str, str] | None = None
        self._parent_by_title: dict[str, str] | None = None

    def _disable_unconfigured_sources(self) -> None:
        """Remove sources with missing configuration from the run."""
        disabled = []
        if "ezproxy" in self.sources and not self.cfg.ezproxy_base:
            self.sources = [s for s in self.sources if s != "ezproxy"]
            disabled.append("ezproxy (no ezproxy_base)")
        if "core" in self.sources and not self.cfg.core_api_key:
            self.sources = [s for s in self.sources if s != "core"]
            disabled.append("core (no CORE API key)")
        if "serpapi" in self.sources:
            from .routing import serpapi_ready

            if not serpapi_ready(self.cfg):
                self.sources = [s for s in self.sources if s != "serpapi"]
                disabled.append("serpapi (disabled or no SERPAPI_API_KEY)")
        if disabled:
            self.stats.sources_disabled = disabled

    def stop(self) -> None:
        self._stop.set()

    # ---- public --------------------------------------------------------------
    def run(self, items: list[Item], batch_size: int = 40) -> RunStats:
        """Process in batches: OA sources in parallel, then Sci-Hub serially, per batch.

        Batching keeps the manifest current (an interrupted run loses at most one
        batch of Sci-Hub work) and interleaves fast OA hits with slow Sci-Hub polling.
        """
        total = len(items)
        self._run_total = total
        self._item_index = {it.key: i for i, it in enumerate(items, start=1)}
        self._circuit.reset()
        self._blocked_hosts.clear()
        self._transport_fail_hosts.clear()
        self._vault_sso_misses = 0
        self._ezproxy_down_offered = False
        try:
            for start in range(0, total, batch_size):
                if self._stop.is_set():
                    break
                if start > 0:
                    self._maybe_offer_ezproxy_relogin()
                batch = items[start : start + batch_size]
                if total > batch_size:
                    self._emit(
                        f"[bold]-- batch {start // batch_size + 1}/{-(-total // batch_size)} "
                        f"(items {start + 1}-{start + len(batch)} of {total})[/]"
                    )
                self._run_batch(batch)
        finally:
            if self.browser is not None:
                self.browser.close()
        self.stats.finished_at = time.time()
        return self.stats

    def _maybe_offer_ezproxy_relogin(self) -> None:
        """Once per run, at a batch boundary, offer mid-run EZProxy recovery."""
        if not self._ezproxy_down or self.on_ezproxy_down is None:
            return
        if self._ezproxy_down_offered:
            return
        self._ezproxy_down_offered = True
        try:
            self.on_ezproxy_down()
        except Exception as exc:
            self._emit(
                f"[yellow]EZProxy re-login failed ({escape(type(exc).__name__)}).[/] "
                "Remaining proxy attempts stay skipped."
            )

    def release_browser(self) -> None:
        """Close vault Chromium and leave a fresh lazy session.

        Headed ``session login`` and browser-agent need exclusive access to
        ``state/sessions/chromium`` (Chrome SingletonLock). Closing without
        replacing would leave a permanently closed ``BrowserSession``.
        """
        if self.browser is not None:
            self.browser.close()
        self.browser = BrowserSession(self.cfg) if self._use_browser else None
        self.ctx = Context(config=self.cfg, client=self.client, browser=self.browser)

    def refresh_session(self) -> None:
        """New HTTP client and vault browser after a headed re-login.

        ``run`` closes the browser, and a closed session cannot be reopened.
        """
        self.release_browser()
        try:
            self.client.close()
        except Exception:
            pass
        self.client = make_client(self.cfg)
        self.ctx = Context(config=self.cfg, client=self.client, browser=self.browser)
        self._ezproxy_down = False
        self._vault_sso_misses = 0
        self._transport_fail_hosts.clear()

    def _run_batch(self, items: list[Item]) -> None:
        oa_sources = [
            s for s in self.sources if s not in _SERIAL_SOURCES and s in REGISTRY
        ]
        serial = [s for s in self.sources if s in _SERIAL_SOURCES and s in REGISTRY]
        steps = order_run(self.cfg, serial)
        serial_names: list[str] = []
        for step in steps:
            serial_names.append(step.name)
            if step.partner:
                serial_names.append(step.partner)
        pending: list[tuple[Item, list[str]]] = []
        queue_lock = threading.Lock()

        def oa_worker(item: Item) -> None:
            if self._stop.is_set():
                return
            attempts = self._phase_oa(item, oa_sources)
            if attempts is None:
                return  # resolved (ok or terminal)
            lanes = self._lanes_for(item)
            next_serial = next((s for s in serial_names if s in lanes), None)
            if next_serial:
                with queue_lock:
                    pending.append((item, attempts))
                self._log_item(item, f"[dim]queued for {next_serial}[/]")
            else:
                self._finish_miss(item, attempts)
                self.progress()

        with ThreadPoolExecutor(max_workers=self.cfg.concurrency_oa) as pool:
            futures = [pool.submit(oa_worker, it) for it in items]
            try:
                for fut in as_completed(futures):
                    exc = fut.exception()
                    if exc:
                        self._emit(f"[red]worker error:[/] {type(exc).__name__}: {exc}")
            except KeyboardInterrupt:
                self._stop.set()
                pool.shutdown(wait=False, cancel_futures=True)
                raise

        if pending and not self._stop.is_set():
            still = pending
            for step in steps:
                if self._stop.is_set():
                    return
                if step.name == "browser_agent" or step.partner == "browser_agent":
                    release_browser_for_agent(self)
                if step.partner:
                    still = self._phase_interleave(still, step.name, step.partner)
                elif step.name == "scihub":
                    still = self._phase_scihub(still)
                else:
                    still = self._phase_serial(
                        still, step.name, htmlpdf_scope=step.htmlpdf_scope
                    )
            if self._stop.is_set():
                return
            for item, attempts in still:
                self._finish_miss(item, attempts)
                self.progress()

    # ---- phase 1: identifier + OA -------------------------------------------
    def _phase_oa(self, item: Item, oa_sources: list[str]) -> list[str] | None:
        attempts: list[str] = []
        self._log_item_label(item)
        notes = prepare_identifiers(
            self.client,
            item,
            email=self.cfg.email,
            min_score=self.cfg.crossref_min_score,
            suspect_score=self.cfg.doi_suspect_score,
            verify=self.cfg.verify_doi,
            cache=self._id_cache,
        )
        if notes:
            self._log_item(item, "[dim]enrich: looking up DOI...[/]")
            for note in notes:
                attempts.append(note)
                if (
                    ":matched" in note
                    or note.startswith("swap:")
                    or note.startswith("verify:ok")
                ):
                    self._log_item(item, f"enrich: [green]{escape(note)}[/]")
                else:
                    self._log_item(item, f"enrich: [dim]{escape(note)}[/]")
            labels = classify_enrichment(notes)
            if labels:
                with self._stats_lock:
                    self._item_fields[item.key] = labels
                    self.stats.note_fields(labels)
        lanes = self._lanes_for(item)
        self._log_item_trying_line(item, lanes)
        for name in oa_sources:
            if self._stop.is_set():
                return attempts
            if self._skip_source(item, name, lanes, attempts):
                continue
            cand = REGISTRY[name].find(item, self.ctx)
            attempts.append(
                f"{name}:{cand.outcome.value}" + (f"({cand.note})" if cand.note else "")
            )
            with self._stats_lock:
                self.stats.note_source(name, cand.outcome.value)
            self._log_source_result(item, name, cand)
            self._maybe_trip_circuit(name, cand)
            if cand.outcome is Outcome.FOUND and self._try_download(
                item, cand, attempts
            ):
                self.progress()
                return None
        if self._retry_published_oa(item, oa_sources, attempts):
            self.progress()
            return None
        return attempts

    # ---- phase 2: campus EZProxy, serial ------------------------------------
    def _htmlpdf_deferred(
        self, item: Item, name: str, htmlpdf_scope: str
    ) -> bool:
        if name != "htmlpdf" or htmlpdf_scope == "all":
            return False
        academic = academic_htmlpdf_item(item, self.cfg)
        if htmlpdf_scope == "web" and academic:
            return True
        return htmlpdf_scope == "academic" and not academic

    def _phase_one(
        self, name: str, item: Item, attempts: list[str]
    ) -> tuple[str, bool]:
        """Try one serial source on one item.

        Returns ``(status, called_find)``. Status is hit, still, ezproxy_down,
        scholar_down, agent_down, or serpapi_down.
        """
        lanes = self._lanes_for(item)
        if self._skip_source(item, name, lanes, attempts):
            return "still", False
        if skip_recover_without_lane_failure(self, name, item, attempts):
            return "still", False
        self._log_item(item, f"[dim]{name}: checking...[/]")
        cand = REGISTRY[name].find(item, self.ctx)
        if name == "browser_agent" and cand.outcome is Outcome.FOUND:
            self._note_agent_after_playwright(item, cand, attempts)
        note = f"({cand.note})" if cand.note else ""
        attempts.append(f"{name}:{cand.outcome.value}{note}")
        with self._stats_lock:
            self.stats.note_source(name, cand.outcome.value)
        self._log_source_result(item, name, cand)
        self._maybe_trip_circuit(name, cand)
        if cand.outcome is Outcome.FOUND and self._try_download(item, cand, attempts):
            self.progress()
            return "hit", True
        if name == "scihub":
            if cand.outcome is Outcome.CAPTCHA:
                self._record(item, STATUS_CAPTCHA, attempts, reason=cand.note)
                self.progress()
                return "terminal", True
            if cand.outcome is Outcome.ERROR:
                self._record(item, STATUS_ERROR, attempts, reason=cand.note)
                self.progress()
                return "terminal", True
        if cand.outcome is Outcome.ERROR and "session expired" in (cand.note or ""):
            self._mark_ezproxy_down()
            return "ezproxy_down", True
        if name == "browser_agent" and cand.outcome is Outcome.CAPTCHA:
            self._mark_browser_agent_down()
            return "agent_down", True
        if name == "scholar" and _scholar_blocked(cand):
            self._mark_scholar_down(cand.note or cand.outcome.value)
            return "scholar_down", True
        if name == "serpapi" and _serpapi_blocked(cand):
            self._mark_serpapi_down(cand.note or cand.outcome.value)
            return "serpapi_down", True
        return "still", True

    def _phase_serial(
        self,
        queue: list[tuple[Item, list[str]]],
        name: str,
        *,
        htmlpdf_scope: str = "all",
        scihub_delay: bool = False,
    ) -> list[tuple[Item, list[str]]]:
        """Try a serial source; return items that still need later phases."""
        label = name if htmlpdf_scope == "all" else f"{name} ({htmlpdf_scope})"
        self._emit(f"[bold]-- {label}[/] ({len(queue)} remaining)")
        if name == "ezproxy" and self._ezproxy_down:
            return self._skip_ezproxy(queue)
        if name == "browser_agent" and self._browser_agent_down:
            return self._skip_browser_agent(queue)
        if name == "scholar" and self._scholar_down:
            return self._skip_scholar(queue)
        if name == "serpapi" and self._serpapi_down:
            return self._skip_serpapi(queue, reason="quota")
        if name == "serpapi" and self._serpapi_over_budget():
            return self._skip_serpapi(queue, reason="max_calls")
        still: list[tuple[Item, list[str]]] = []
        lo, hi = self.cfg.delay_scihub_s
        first = True
        for idx, (item, attempts) in enumerate(queue):
            if self._stop.is_set():
                still.extend(queue[idx:])
                return still
            if self._htmlpdf_deferred(item, name, htmlpdf_scope):
                still.append((item, attempts))
                continue
            if not first:
                if scihub_delay:
                    time.sleep(random.uniform(lo, hi))
                else:
                    time.sleep(random.uniform(min(lo, 1.0), min(hi, 3.0)))
            first = False
            status, called = self._phase_one(name, item, attempts)
            if name == "serpapi" and called:
                self._serpapi_calls += 1
            if status in {"hit", "terminal"}:
                continue
            still.append((item, attempts))
            rest = queue[idx + 1 :]
            if status == "ezproxy_down":
                still.extend(self._skip_ezproxy(rest))
                return still
            if status == "agent_down":
                still.extend(self._skip_browser_agent(rest))
                return still
            if status == "scholar_down":
                still.extend(self._skip_scholar(rest))
                return still
            if status == "serpapi_down":
                still.extend(self._skip_serpapi(rest, reason="quota"))
                return still
            if name == "serpapi" and self._serpapi_over_budget():
                still.extend(self._skip_serpapi(rest, reason="max_calls"))
                return still
        return still

    def _phase_interleave(
        self,
        queue: list[tuple[Item, list[str]]],
        first: str,
        second: str,
    ) -> list[tuple[Item, list[str]]]:
        """One ``first`` try, then ``second`` on the same item if still missing.

        Sleep between Scholar queries only when the previous Scholar call was
        not followed by ``browser_agent`` (the agent wall clock is the backoff).
        """
        self._emit(f"[bold]-- {first}+{second}[/] ({len(queue)} remaining)")
        still: list[tuple[Item, list[str]]] = []
        lo, hi = self.cfg.delay_scihub_s
        need_gap = False
        for idx, (item, attempts) in enumerate(queue):
            if self._stop.is_set():
                still.extend(queue[idx:])
                return still
            if first == "scholar" and self._scholar_down:
                self._note_scholar_skipped(item, attempts)
            else:
                if first == "scholar" and need_gap:
                    time.sleep(random.uniform(min(lo, 1.0), min(hi, 3.0)))
                    need_gap = False
                status, called = self._phase_one(first, item, attempts)
                if status == "hit":
                    if first == "scholar" and called:
                        need_gap = True
                    continue
                if status == "ezproxy_down":
                    still.append((item, attempts))
                    still.extend(self._skip_ezproxy(queue[idx + 1 :]))
                    return still
                if status == "scholar_down":
                    pass  # still try the agent on this item
                elif first == "scholar" and called:
                    need_gap = True
            ran_second = False
            if second == "browser_agent" and self._browser_agent_down:
                self._note_agent_skipped(item, attempts)
            else:
                status, called_second = self._phase_one(second, item, attempts)
                ran_second = called_second
                if status == "hit":
                    continue
                if status == "agent_down":
                    still.append((item, attempts))
                    still.extend(self._skip_browser_agent(queue[idx + 1 :]))
                    return still
            if ran_second and first == "scholar":
                need_gap = False
            still.append((item, attempts))
        return still

    def _mark_scholar_down(self, why: str) -> None:
        if self._scholar_down:
            return
        self._scholar_down = True
        self._emit(
            f"[yellow]scholar blocked ({escape(why)}); skipping it for the rest of "
            "this run.[/] Use --handoff for the remaining misses."
        )

    def _note_scholar_skipped(self, item: Item, attempts: list[str]) -> None:
        if "scholar" not in self._applicable(item):
            return
        attempts.append("scholar:skipped(blocked)")
        with self._stats_lock:
            self.stats.note_source("scholar", "skipped")
        self._log_item(item, "scholar: [dim]skipped[/] (blocked this run)")

    def _skip_scholar(
        self, queue: list[tuple[Item, list[str]]]
    ) -> list[tuple[Item, list[str]]]:
        for item, attempts in queue:
            self._note_scholar_skipped(item, attempts)
        return queue

    def _note_agent_skipped(self, item: Item, attempts: list[str]) -> None:
        attempts.append("browser_agent:skipped(bot wall)")
        with self._stats_lock:
            self.stats.note_source("browser_agent", "skipped")
        self._log_item(item, "browser_agent: [dim]skipped[/] (bot wall)")

    def _serpapi_over_budget(self) -> bool:
        cap = self.cfg.serpapi_max_calls
        return cap > 0 and self._serpapi_calls >= cap

    def _mark_serpapi_down(self, why: str) -> None:
        if self._serpapi_down:
            return
        self._serpapi_down = True
        self._emit(
            f"[yellow]serpapi blocked ({escape(why)}); skipping it for the rest of "
            "this run.[/]"
        )

    def _skip_serpapi(
        self,
        queue: list[tuple[Item, list[str]]],
        *,
        reason: str = "quota",
    ) -> list[tuple[Item, list[str]]]:
        if reason == "max_calls" and not self._serpapi_capped:
            self._serpapi_capped = True
            cap = self.cfg.serpapi_max_calls
            self._emit(
                f"[yellow]serpapi hit max_calls ({cap}); skipping it for the rest of "
                "this run.[/]"
            )
        label = "max_calls" if reason == "max_calls" else "quota"
        for item, attempts in queue:
            if "serpapi" not in self._applicable(item):
                continue
            attempts.append(f"serpapi:skipped({label})")
            with self._stats_lock:
                self.stats.note_source("serpapi", "skipped")
            self._log_item(item, f"serpapi: [dim]skipped[/] ({label} this run)")
        return queue

    def _mark_browser_agent_down(self) -> None:
        if self._browser_agent_down:
            return
        self._browser_agent_down = True
        self._emit(
            "[yellow]browser_agent hit a bot wall; skipping it for the rest of this run.[/]"
        )

    def _skip_browser_agent(
        self, queue: list[tuple[Item, list[str]]]
    ) -> list[tuple[Item, list[str]]]:
        still: list[tuple[Item, list[str]]] = []
        for item, attempts in queue:
            self._note_agent_skipped(item, attempts)
            still.append((item, attempts))
        return still

    def _mark_ezproxy_down(self) -> None:
        if self._ezproxy_down:
            return
        self._ezproxy_down = True
        if self.cfg.ezproxy_relogin:
            self._emit(
                "[yellow]ezproxy session expired.[/] Remaining proxy attempts in this "
                "pass will be skipped. A terminal run can re-login at the end."
            )
        else:
            self._emit(
                "[yellow]ezproxy session expired. Re-login with `paperful session login`, "
                "then `paperful run` on this collection.[/]"
            )

    def _note_vault_sso_miss(self, attempts: list[str], source: str) -> None:
        """Count campus-CAS vault misses; trip EZProxy after the threshold."""
        attempts.append(f"{source}:skipped(session expired)")
        with self._stats_lock:
            self._vault_sso_misses += 1
            count = self._vault_sso_misses
        if count >= _VAULT_SSO_MISS_THRESHOLD:
            self._mark_ezproxy_down()

    def _host_keys(self, url: str) -> list[str]:
        """Normalized host keys for dead-host checks (label + publisher family)."""
        keys: list[str] = []
        label = host_label(url)
        if label:
            keys.append(label)
        pub = publisher_host(url)
        if pub and pub not in keys:
            keys.append(pub)
        return keys

    def _host_is_dead(self, url: str) -> bool:
        keys = self._host_keys(url)
        if not keys:
            return False
        with self._stats_lock:
            return any(k in self._blocked_hosts for k in keys)

    def _mark_host_dead(self, *hosts: str) -> None:
        cleaned = [h.strip().lower() for h in hosts if h and h.strip()]
        if not cleaned:
            return
        with self._stats_lock:
            for host in cleaned:
                if host.startswith("www."):
                    host = host[4:]
                self._blocked_hosts.add(host)

    def _note_dead_vault_miss(self, note: str, candidate_url: str = "") -> None:
        """Remember the final vault host after login/captcha/no-control misses.

        Do not silence the candidate publisher on an SSO bounce to federation —
        only the landing host in the miss note (or the candidate when no host
        was recorded).
        """
        final = miss_host(note)
        if final:
            self._mark_host_dead(final)
            return
        if candidate_url:
            self._mark_host_dead(*self._host_keys(candidate_url))

    def _note_fetch_failure(self, url: str, exc: DownloadError | None = None) -> None:
        """Mark hosts dead on hard fails; count transport blips until threshold."""
        keys = self._host_keys(url)
        if not keys:
            return
        if exc is not None and is_transport_download_error(exc):
            with self._stats_lock:
                for key in keys:
                    n = self._transport_fail_hosts.get(key, 0) + 1
                    self._transport_fail_hosts[key] = n
                    if n >= _TRANSPORT_DEAD_THRESHOLD:
                        self._blocked_hosts.add(key)
            return
        self._mark_host_dead(*keys)

    def _skip_ezproxy(
        self, queue: list[tuple[Item, list[str]]]
    ) -> list[tuple[Item, list[str]]]:
        still: list[tuple[Item, list[str]]] = []
        for item, attempts in queue:
            attempts.append("ezproxy:skipped(session expired)")
            with self._stats_lock:
                self.stats.note_source("ezproxy", "skipped")
            self._log_item(item, "ezproxy: [dim]skipped[/] (session expired)")
            still.append((item, attempts))
        return still

    def _retry_published_oa(
        self,
        item: Item,
        oa_sources: list[str],
        attempts: list[str],
    ) -> bool:
        """Try OA lanes once on the published DOI. The library DOI is left as it was."""
        query = item.doi or ""
        if item.arxiv_id and not is_preprint_doi(query):
            query = f"10.48550/arxiv.{item.arxiv_id}"
        if not is_preprint_doi(query):
            return False
        try:
            link = version_link(self.client, query, self.cfg.email, self._id_cache)
        except Exception:
            return False
        published = normalize_doi(getattr(link, "published_doi", None) if link else None)
        if not published or published == normalize_doi(item.doi):
            return False
        attempts.append(f"version:{published}")
        saved = item.doi
        item.doi = published
        try:
            lanes = self._lanes_for(item)
            for name in oa_sources:
                if self._stop.is_set():
                    return False
                if self._skip_source(item, name, lanes, attempts):
                    continue
                cand = REGISTRY[name].find(item, self.ctx)
                attempts.append(
                    f"{name}:{cand.outcome.value}"
                    + (f"({cand.note})" if cand.note else "")
                )
                with self._stats_lock:
                    self.stats.note_source(name, cand.outcome.value)
                self._log_source_result(item, name, cand)
                self._maybe_trip_circuit(name, cand)
                if cand.outcome is not Outcome.FOUND:
                    continue
                item.doi = saved
                if self._try_download(item, cand, attempts):
                    return True
                item.doi = published
        finally:
            item.doi = saved
        return False

    def _phase_scihub(
        self, queue: list[tuple[Item, list[str]]]
    ) -> list[tuple[Item, list[str]]]:
        return self._phase_serial(queue, "scihub", scihub_delay=True)

    # ---- helpers ----------------------------------------------------------------
    def _applicable(self, item: Item) -> list[str]:
        configured = [s for s in self.sources if s in REGISTRY]
        if self.try_all:
            from .routing import apply_fetch_order, place_academic_htmlpdf

            return apply_fetch_order(
                self.cfg,
                place_academic_htmlpdf(configured, self.cfg, item),
                item,
            )
        return sources_for_item(item, self.cfg, configured)

    def _lanes_for(self, item: Item) -> list[str]:
        return [s for s in self._applicable(item) if not self._circuit.tripped(s)]

    def _skip_source(
        self, item: Item, name: str, lanes: list[str], attempts: list[str]
    ) -> bool:
        applicable = name in self._applicable(item)
        if name == "ezproxy" and self._ezproxy_down and applicable:
            attempts.append(f"{name}:skipped(session expired)")
            with self._stats_lock:
                self.stats.note_source(name, "skipped")
            self._log_item(item, f"{escape(name)}: [dim]skipped[/] (session expired)")
            return True
        if name in lanes:
            return False
        if self._circuit.tripped(name) and applicable:
            attempts.append(f"{name}:skipped(circuit open)")
            self._circuit.consume_skip(name)
            with self._stats_lock:
                self.stats.note_source(name, "skipped")
            self._log_item(
                item, f"{escape(name)}: [dim]skipped[/] (paused after blocks)"
            )
        else:
            attempts.append(f"{name}:skipped(not applicable)")
            with self._stats_lock:
                self.stats.note_source(name, "skipped")
            self._log_item(item, f"{escape(name)}: [dim]skipped[/] (not applicable)")
        return True

    def _maybe_trip_circuit(self, name: str, cand: Candidate) -> None:
        if self._circuit.note(name, cand.outcome, cand.note or ""):
            self._emit(
                f"[yellow]{name} blocked {self.cfg.circuit_breaker_threshold} times; "
                f"pausing {name}[/]"
            )

    def _try_download(
        self,
        item: Item,
        cand: Candidate,
        attempts: list[str],
    ) -> bool:
        from .miss_surface import license_blocked_by_policy
        from .oa_locations import apply_stamp_fields

        oa_stamp = apply_stamp_fields(
            dict(cand.oa_stamp or {}), self.cfg.oa_honesty_stamp_fields
        )
        if license_blocked_by_policy(
            oa_stamp, self.cfg.oa_honesty_license_block
        ):
            lic = oa_stamp.get("license", "")
            attempts.append(f"{cand.source}:license_blocked({lic})")
            self._log_item(
                item,
                f"{escape(cand.source)}: [yellow]license blocked[/]"
                + (f" ({escape(lic)})" if lic else ""),
            )
            return False
        dl = None
        if cand.content is not None:
            self._log_item(item, f"[dim]{cand.source}: downloading...[/]")
            content = cand.content
            if (
                not content.lstrip().startswith(b"%PDF")
                or len(content) < self.cfg.min_pdf_bytes
            ):
                attempts.append(f"{cand.source}:download-failed(invalid embedded PDF)")
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [yellow]download failed[/] (invalid embedded PDF)",
                )
                return False
            dl = Download(
                content=content,
                md5=hashlib.md5(content).hexdigest(),
                final_url=cand.url or item.url or "",
            )
        else:
            urls: list[str] = []
            skipped_blocked = False
            for url in urls_to_fetch(cand.urls):
                if self._host_is_dead(url):
                    skipped_blocked = True
                    continue
                urls.append(url)
            if not urls:
                if skipped_blocked:
                    attempts.append(f"{cand.source}:skipped(host already blocked)")
                    self._log_item(
                        item,
                        f"{escape(cand.source)}: [dim]skipped[/] (host already blocked)",
                    )
                return False
            self._log_item(item, f"[dim]{cand.source}: downloading...[/]")
            for url in urls:
                dl = self._fetch_url(item, cand, url, attempts)
                if dl is not None:
                    break
                # Hard-fail marking happens inside _fetch_url / browser miss handlers.
        if dl is None:
            return False
        short_verdict = "ok"
        if self.cfg.gate_short_pdfs:
            probe = probe_pdf_bytes(dl.content)
            short_verdict = short_pdf_verdict(
                probe.pages,
                probe.words,
                min_words=self.cfg.short_pdf_min_words,
            )
            if short_verdict == "sparse_short":
                attempts.append(
                    f"{cand.source}:download-failed(sparse one-page PDF, "
                    f"{probe.words} words)"
                )
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [yellow]download failed[/] "
                    f"(sparse one-page PDF, {probe.words} words)",
                )
                return False
        return commit_download(
            self,
            item,
            cand,
            dl,
            attempts,
            oa_stamp=oa_stamp,
            short_verdict=short_verdict,
        )

    def _fetch_url(
        self, item: Item, cand: Candidate, url: str, attempts: list[str]
    ) -> Download | None:
        if not is_fetchable_url(url):
            attempts.append(f"{cand.source}:download-failed(not an http(s) URL)")
            self._log_item(
                item,
                f"{escape(cand.source)}: [yellow]download failed[/] (not an http(s) URL)",
            )
            return None
        browser_first = self._browser_first(url, cand.source)
        if browser_first:
            dl = self._browser_pdf(item, cand, url, attempts)
            if dl is not None:
                return dl
        try:
            return fetch_pdf(
                self.client,
                url,
                referer=cand.referer,
                min_bytes=self.cfg.min_pdf_bytes,
            )
        except DownloadError as exc:
            attempts.append(f"{cand.source}:download-failed({exc})")
            self._log_item(
                item,
                f"{escape(cand.source)}: [yellow]download failed[/] ({escape(str(exc))})",
            )
            soft = _is_soft_block_error(exc)
            # Soft landings still get a vault retry; do not silence the host yet.
            if not soft:
                self._note_fetch_failure(url, exc)
            # Soft-blocked OA PDF URLs need a vault browser retry even when the
            # host is not on the publisher allowlist (e.g. AMS downloadpdf).
            # Transport blips do not force a vault retry.
            if soft or (not browser_first and not is_transport_download_error(exc)):
                return self._browser_pdf(
                    item, cand, url, attempts, force=soft
                )
            return None

    def _browser_first(self, url: str, source: str) -> bool:
        if self.browser is None or not self.browser.available():
            return False
        if source == "ezproxy":
            return True
        return is_publisher_url(url)

    def _browser_pdf(
        self,
        item: Item,
        cand: Candidate,
        url: str,
        attempts: list[str],
        *,
        force: bool = False,
    ) -> Download | None:
        if self.browser is None or not self.browser.available():
            return None
        if (
            not force
            and cand.source not in {"ezproxy", "scholar"}
            and not is_publisher_url(url)
        ):
            return None
        if self._host_is_dead(url):
            attempts.append(f"{cand.source}:skipped(host already blocked)")
            self._log_item(
                item,
                f"{escape(cand.source)}: [dim]skipped[/] (host already blocked)",
            )
            return None
        targets = [url]
        can_wrap = (
            bool(self.cfg.ezproxy_base)
            and is_publisher_url(url)
            and "idm.oclc.org" not in urlparse(url).netloc
        )
        if can_wrap and self._ezproxy_down:
            attempts.append(f"{cand.source}:skipped(session expired)")
            self._log_item(
                item,
                f"{escape(cand.source)}: [dim]skipped[/] (session expired)",
            )
            # Campus is down; raw publisher pages usually bounce to the same SSO.
            return None
        elif can_wrap:
            wrapped = proxify(url, self.cfg.ezproxy_base)
            if wrapped != url:
                targets = [wrapped, url]
        for target in targets:
            if self._host_is_dead(target):
                attempts.append(f"{cand.source}:skipped(host already blocked)")
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [dim]skipped[/] (host already blocked)",
                )
                continue
            self._log_item(
                item, f"[dim]{escape(cand.source)}: downloading via browser...[/]"
            )
            try:
                content, final, win = self.browser.fetch_pdf(target)
            except Exception as exc:
                attempts.append(f"{cand.source}:browser-failed({exc})")
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [yellow]browser failed[/] ({escape(str(exc))})",
                )
                note = str(exc)
                if looks_like_dead_vault_miss(note):
                    self._note_dead_vault_miss(note, candidate_url=url)
                if looks_like_vault_login_miss(note):
                    self._note_vault_sso_miss(attempts, cand.source)
                continue
            if not looks_like_pdf(content) or len(content) < self.cfg.min_pdf_bytes:
                attempts.append(f"{cand.source}:browser-failed(not a PDF)")
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [yellow]browser failed[/] (not a PDF)",
                )
                continue
            attempts.append(f"{cand.source}:browser")
            from .fetch_wins import record_win

            record_win(
                self.cfg,
                item_key=item.key,
                source=cand.source,
                start_url=target,
                final_url=final or target,
                win=win,
            )
            return Download(
                content=content,
                md5=hashlib.md5(content).hexdigest(),
                final_url=final or target,
            )
        return None

    def attach_record(self, rec: Record) -> bool:
        if not self.attacher or not rec.path:
            return False
        pdf = resolve_pdf_path(self.cfg.out_dir, rec.path)
        if pdf is None:
            # The folder is named for the title; a retitle moves it. The key does not change.
            pdf = pdf_for_key(self.cfg.out_dir, rec.itemKey)
        if pdf is None:
            with self._attach_lock:
                rec.status = STATUS_ATTACH_FAILED
                rec.reason = f"file missing: {rec.path}"
                code = "other"
                with self._stats_lock:
                    self.stats.attach_failed_by_code[code] = (
                        self.stats.attach_failed_by_code.get(code, 0) + 1
                    )
                    self.stats.bump(STATUS_ATTACH_FAILED)
                self._emit(f"   [yellow]attach failed[/] {rec.itemKey}: {rec.reason}")
                self._add_outcome(rec, attach_code=code)
                self.manifest.write(rec)
            return False
        if str(pdf) != rec.path:
            rec.path = str(pdf)
        note = provenance_stamp(
            rec.source,
            playbook=rec.playbook or None,
            pdf_doi_mismatch=bool(rec.pdf_doi and rec.doi and rec.pdf_doi != rec.doi),
        )
        with self._attach_lock:
            res = self.attacher.attach(rec.itemKey, pdf, note=note)
            if not res.ok and parent_missing(res.reason):
                res = attach_after_remap(self, rec, pdf, res.reason, note=note)
        if res.ok:
            rec.status = STATUS_ATTACHED
            rec.reason = res.reason
            with self._stats_lock:
                self.stats.bump(STATUS_ATTACHED)
            self._emit(f"   [cyan]attached[/] {rec.itemKey} ({res.reason})")
            if rec.source != "htmlpdf" and not self.cfg.htmlpdf_keep_snapshot:
                _drop_snapshot_attachments(self.attacher, rec.itemKey, self._emit)
            self._add_outcome(rec)
            mismatch = bool(rec.pdf_doi and rec.doi and rec.pdf_doi != rec.doi)
            try:
                say(
                    self.attacher,
                    rec.itemKey,
                    "found",
                    provenance_sentence(
                        rec.source,
                        playbook=rec.playbook or None,
                        pdf_doi_mismatch=mismatch,
                    ),
                    surface=self.cfg.remarks_surface,
                )
            except Exception as exc:
                self._emit(f"   [dim]remark skipped[/] {rec.itemKey}: {exc}")
        else:
            rec.status = STATUS_ATTACH_FAILED
            rec.reason = res.reason
            code = res.code or "other"
            with self._stats_lock:
                self.stats.attach_failed_by_code[code] = (
                    self.stats.attach_failed_by_code.get(code, 0) + 1
                )
                self.stats.bump(STATUS_ATTACH_FAILED)
            self._emit(f"   [yellow]attach failed[/] {rec.itemKey}: {res.reason}")
            hint = _attach_operator_line(code)
            if hint:
                self._emit(f"   [yellow]{hint}[/]")
            self._add_outcome(rec, attach_code=code)
        self.manifest.write(rec)
        return res.ok

    def _finish_miss(self, item: Item, attempts: list[str]) -> None:
        from .routing import soft_block_miss

        if not item.doi and not item.arxiv_id and not item.url:
            self._record(
                item, STATUS_NO_IDENTIFIER, attempts, reason="no DOI, arXiv id or URL"
            )
        elif _lane_paused(attempts):
            if any("session expired" in a for a in attempts):
                reason = "session expired"
            elif any("skipped(bot wall)" in a for a in attempts):
                reason = "bot wall"
            else:
                reason = "source paused"
            self._record(item, STATUS_RETRYABLE, attempts, reason=reason)
        elif soft_block_miss(attempts):
            agent_done = any(
                a.startswith("browser_agent:")
                and not a.startswith("browser_agent:skipped")
                for a in attempts
            )
            if not agent_done:
                self._record(item, STATUS_RETRYABLE, attempts, reason="soft block")
            elif any(":captcha" in a for a in attempts):
                self._record(item, STATUS_CAPTCHA, attempts, reason="bot wall")
            else:
                self._record(item, STATUS_NOT_FOUND, attempts, reason=REASON_CLOSED)
        elif any(":license_blocked" in a for a in attempts):
            self._record(item, STATUS_NOT_FOUND, attempts, reason="license_blocked")
        elif any(":captcha" in a for a in attempts):
            self._record(item, STATUS_CAPTCHA, attempts, reason="bot wall")
        elif any(
            a.endswith(":error") or "download-failed" in a for a in attempts
        ) and not any(a.endswith(":not_found") for a in attempts):
            self._record(item, STATUS_ERROR, attempts, reason="only transient failures")
        else:
            self._record(item, STATUS_NOT_FOUND, attempts, reason=REASON_CLOSED)

    def _record(
        self, item: Item, status: str, attempts: list[str], reason: str = ""
    ) -> None:
        rec = Record(
            itemKey=item.key,
            status=status,
            title=item.title,
            doi=item.doi,
            doi_source=item.doi_source,
            library_doi=item.library_doi,
            doi_verified=item.doi_verified,
            url=item.url,
            reason=reason,
            attempts=attempts,
        )
        self.manifest.write(rec)
        with self._stats_lock:
            self.stats.bump(status)
        colour = {
            STATUS_NOT_FOUND: "dim",
            STATUS_NO_IDENTIFIER: "dim",
            STATUS_CAPTCHA: "yellow",
            STATUS_RETRYABLE: "yellow",
            STATUS_ERROR: "red",
        }[status]
        self._log_item(
            item, f"[{colour}]{status}[/]" + (f" [dim]({reason})[/]" if reason else "")
        )
        self._add_outcome(rec)

    def _add_outcome(self, rec: Record, attach_code: str | None = None) -> None:
        from .miss_surface import oa_stamp_from_record, row_from_item

        err = error_type_for(rec.status, rec.reason, attach_code)
        honesty = row_from_item(
            doi=rec.doi,
            url=rec.url,
            has_pdf=rec.status in {"ok", "attached"},
            status=rec.status,
            reason=rec.reason,
            attempts=list(rec.attempts),
            source=rec.source,
            oa_stamp=oa_stamp_from_record(rec),
            stamp_fields=self.cfg.oa_honesty_stamp_fields,
            license_block_patterns=self.cfg.oa_honesty_license_block,
        )
        with self._stats_lock:
            fields = self._item_fields.pop(rec.itemKey, [])
            self.stats.add_item(
                ItemOutcome(
                    itemKey=rec.itemKey,
                    title=rec.title,
                    status=rec.status,
                    source=rec.source,
                    reason=rec.reason,
                    doi=rec.doi,
                    doi_verified=rec.doi_verified,
                    attempts=list(rec.attempts),
                    fields_corrected=fields,
                    path=rec.path,
                    error_type=err,
                    miss_surface=honesty.get("miss_surface"),
                    miss_plain=str(honesty.get("miss_plain") or ""),
                    miss_detail=str(honesty.get("miss_detail") or ""),
                    oa_status=str(honesty.get("oa_status") or ""),
                    license=str(honesty.get("license") or ""),
                    version=str(honesty.get("version") or ""),
                )
            )

    # ---- console --------------------------------------------------------------
    def _emit(self, message: str) -> None:
        with self._print_lock:
            self.console.print(message)

    def _item_tag(self, item: Item) -> str:
        idx = self._item_index.get(item.key)
        if idx is None or not self._run_total:
            return item.key
        return f"{idx}/{self._run_total}"

    def _log_item_label(self, item: Item) -> None:
        self._emit(f"[bold]\\[{self._item_tag(item)}][/] {escape(item.label)}")

    def _log_item_trying_line(self, item: Item, lanes: list[str]) -> None:
        ident = (
            f"DOI {item.doi}"
            if item.doi
            else (
                f"arXiv:{item.arxiv_id}"
                if item.arxiv_id
                else (f"URL {item.url}" if item.url else "no identifier")
            )
        )
        self._log_item(
            item, f"[dim]{escape(ident)} · trying: {escape(', '.join(lanes))}[/]"
        )

    def _log_item(self, item: Item, message: str) -> None:
        self._emit(f"\\[{self._item_tag(item)}] {message}")

    def _note_agent_after_playwright(
        self, item: Item, cand: Candidate, attempts: list[str]
    ) -> None:
        """Record which Playwright miss the agent just beat, on the hit note."""
        prior = prior_playwright_miss(attempts)
        if not prior:
            return
        cand.note = f"{cand.note}; after {prior}" if cand.note else f"after {prior}"
        self._log_item(
            item,
            f"browser_agent: [green]succeeded after Playwright miss[/] ({escape(prior)})",
        )

    def _log_source_result(self, item: Item, name: str, cand: Candidate) -> None:
        colours = {
            Outcome.FOUND: "green",
            Outcome.NOT_FOUND: "dim",
            Outcome.SKIPPED: "dim",
            Outcome.ERROR: "yellow",
            Outcome.CAPTCHA: "yellow",
        }
        colour = colours.get(cand.outcome, "white")
        note = f" ({escape(cand.note)})" if cand.note else ""
        self._log_item(item, f"{escape(name)}: [{colour}]{cand.outcome.value}[/]{note}")
