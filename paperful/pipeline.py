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
from pathlib import Path
from urllib.parse import urlparse

import httpx
from rich.console import Console
from rich.markup import escape

from .attach import parent_missing
from .provenance import provenance_stamp
from .circuit import CircuitBreaker
from .config import Config
from .cookies import apply_netscape_cookies
from .download import Download, DownloadError, fetch_pdf, looks_like_pdf
from .pdfid import doi_from_pdf
from .pipeline_attach import attach_after_remap
from .pipeline_browser import release_browser_for_agent, skip_recover_without_lane_failure
from .resolve import IdentifierCache, prepare_identifiers
from .routing import (
    is_publisher_url,
    prior_playwright_miss,
    publisher_host,
    sources_for_item,
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
_SERIAL_SOURCES = frozenset({"scihub", "ezproxy", "htmlpdf", "scholar", "browser_agent"})


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

    def bump(self, status: str, source: str | None = None) -> None:
        if hasattr(self, status) and status in {
            "ok",
            "not_found",
            "no_identifier",
            "captcha",
            "error",
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
    ):
        self.cfg = cfg
        self.manifest = manifest
        self.console = console
        self.sources = sources or cfg.sources
        self.try_all = try_all if try_all is not None else not cfg.source_routing
        self.attacher = attacher
        self.strict_pdf_doi = strict_pdf_doi
        self.progress = progress or (lambda: None)
        self.client = make_client(cfg)
        self.browser = BrowserSession(cfg) if use_browser else None
        self.ctx = Context(config=cfg, client=self.client, browser=self.browser)
        self.stats = RunStats()
        self.stats.sources_configured = list(self.sources)
        self._circuit = CircuitBreaker(cfg.circuit_breaker_threshold)
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
        try:
            for start in range(0, total, batch_size):
                if self._stop.is_set():
                    break
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

    def _run_batch(self, items: list[Item]) -> None:
        oa_sources = [
            s for s in self.sources if s not in _SERIAL_SOURCES and s in REGISTRY
        ]
        serial = [s for s in self.sources if s in _SERIAL_SOURCES and s in REGISTRY]
        pending: list[tuple[Item, list[str]]] = []
        queue_lock = threading.Lock()

        def oa_worker(item: Item) -> None:
            if self._stop.is_set():
                return
            attempts = self._phase_oa(item, oa_sources)
            if attempts is None:
                return  # resolved (ok or terminal)
            lanes = self._lanes_for(item)
            next_serial = next((s for s in serial if s in lanes), None)
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
            for name in serial:
                if self._stop.is_set():
                    return
                if name == "browser_agent":
                    release_browser_for_agent(self)
                if name == "scihub":
                    still = self._phase_scihub(still)
                else:
                    still = self._phase_serial(still, name)
            if self._stop.is_set():
                return
            for item, attempts in still:
                self._finish_miss(item, attempts)
                self.progress()

    # ---- phase 1: identifier + OA -------------------------------------------
    def _phase_oa(self, item: Item, oa_sources: list[str]) -> list[str] | None:
        attempts: list[str] = []
        blocked_hosts: set[str] = set()
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
                item, cand, attempts, blocked_hosts
            ):
                self.progress()
                return None
        return attempts

    # ---- phase 2: campus EZProxy, serial ------------------------------------
    def _phase_serial(
        self, queue: list[tuple[Item, list[str]]], name: str
    ) -> list[tuple[Item, list[str]]]:
        """Try a serial source; return items that still need Sci-Hub / finish_miss."""
        self._emit(f"[bold]-- {name}[/] ({len(queue)} remaining)")
        still: list[tuple[Item, list[str]]] = []
        lo, hi = self.cfg.delay_scihub_s
        first = True
        for idx, (item, attempts) in enumerate(queue):
            if self._stop.is_set():
                still.extend(queue[idx:])
                return still
            if not first:
                time.sleep(random.uniform(min(lo, 1.0), min(hi, 3.0)))
            first = False
            lanes = self._lanes_for(item)
            if self._skip_source(item, name, lanes, attempts):
                still.append((item, attempts))
                continue
            if skip_recover_without_lane_failure(self, name, item, attempts):
                still.append((item, attempts))
                continue
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
            if cand.outcome is Outcome.FOUND and self._try_download(
                item, cand, attempts
            ):
                self.progress()
                continue
            if cand.outcome is Outcome.ERROR and "session expired" in (cand.note or ""):
                self._emit(
                    "[yellow]ezproxy session expired; skipping remaining proxy attempts this batch[/]"
                )
                still.append((item, attempts))
                still.extend(queue[idx + 1 :])
                return still
            still.append((item, attempts))
        return still

    # ---- phase 3: Sci-Hub, serial --------------------------------------------
    def _phase_scihub(
        self, queue: list[tuple[Item, list[str]]]
    ) -> list[tuple[Item, list[str]]]:
        """Try Sci-Hub. CAPTCHA and ERROR end the item; misses stay queued."""
        self._emit(f"[bold]-- scihub[/] ({len(queue)} remaining)")
        still: list[tuple[Item, list[str]]] = []
        lo, hi = self.cfg.delay_scihub_s
        first = True
        for idx, (item, attempts) in enumerate(queue):
            if self._stop.is_set():
                still.extend(queue[idx:])
                return still
            lanes = self._lanes_for(item)
            if self._skip_source(item, "scihub", lanes, attempts):
                still.append((item, attempts))
                continue
            if not first:
                time.sleep(random.uniform(lo, hi))
            first = False
            self._log_item(item, "[dim]scihub: checking...[/]")
            cand = REGISTRY["scihub"].find(item, self.ctx)
            attempts.append(
                f"scihub:{cand.outcome.value}" + (f"({cand.note})" if cand.note else "")
            )
            with self._stats_lock:
                self.stats.note_source("scihub", cand.outcome.value)
            self._log_source_result(item, "scihub", cand)
            self._maybe_trip_circuit("scihub", cand)
            if cand.outcome is Outcome.FOUND and self._try_download(
                item, cand, attempts
            ):
                self.progress()
                continue
            if cand.outcome is Outcome.CAPTCHA:
                self._record(item, STATUS_CAPTCHA, attempts, reason=cand.note)
                self.progress()
                continue
            if cand.outcome is Outcome.ERROR:
                self._record(item, STATUS_ERROR, attempts, reason=cand.note)
                self.progress()
                continue
            still.append((item, attempts))
        return still

    # ---- helpers ----------------------------------------------------------------
    def _lanes_for(self, item: Item) -> list[str]:
        configured = [s for s in self.sources if s in REGISTRY]
        if self.try_all:
            routed = configured
        else:
            routed = sources_for_item(item, self.cfg, configured)
        return [s for s in routed if not self._circuit.tripped(s)]

    def _skip_source(
        self, item: Item, name: str, lanes: list[str], attempts: list[str]
    ) -> bool:
        if name in lanes:
            return False
        if self._circuit.tripped(name):
            attempts.append(f"{name}:skipped(circuit open)")
            with self._stats_lock:
                self.stats.note_source(name, "skipped")
            self._log_item(
                item, f"{escape(name)}: [dim]skipped[/] (blocked for rest of run)"
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
                f"skipping {name} for rest of run[/]"
            )

    def _try_download(
        self,
        item: Item,
        cand: Candidate,
        attempts: list[str],
        blocked_hosts: set[str] | None = None,
    ) -> bool:
        blocked = blocked_hosts if blocked_hosts is not None else set()
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
            for url in cand.urls[:6]:
                host = publisher_host(url)
                if host and host in blocked:
                    skipped_blocked = True
                    continue
                urls.append(url)
            if not urls:
                if skipped_blocked:
                    attempts.append(f"{cand.source}:skipped(publisher already blocked)")
                    self._log_item(
                        item,
                        f"{escape(cand.source)}: [dim]skipped[/] (publisher already blocked)",
                    )
                return False
            self._log_item(item, f"[dim]{cand.source}: downloading...[/]")
            for url in urls:
                dl = self._fetch_url(item, cand, url, attempts)
                if dl is not None:
                    break
                host = publisher_host(url)
                if host:
                    blocked.add(host)
        if dl is None:
            return False
        primary, extras = save_pdf(self.cfg.out_dir, item, dl.content, dl.md5)
        pdf_doi = doi_from_pdf(primary)
        write_fetch_records(
            [primary, *extras],
            item,
            md5=dl.md5,
            source=cand.source,
            fetched_url=dl.final_url,
            pdf_doi=pdf_doi,
        )
        mismatch = bool(pdf_doi and item.doi and pdf_doi != item.doi)
        if mismatch:
            self._log_item(
                item,
                f"[yellow]pdf DOI {escape(pdf_doi)} differs from {escape(item.doi)}[/]",
            )
        defer_mismatch = mismatch and self.strict_pdf_doi
        rec = Record(
            itemKey=item.key,
            status=STATUS_OK,
            title=item.title,
            doi=item.doi,
            doi_source=item.doi_source,
            library_doi=item.library_doi,
            doi_verified=item.doi_verified,
            pdf_doi=pdf_doi,
            source=cand.source,
            playbook=cand.playbook,
            url=dl.final_url,
            path=str(primary),
            extra_paths=relpaths(self.cfg.out_dir, extras),
            md5=dl.md5,
            attempts=attempts,
            reason=REASON_STRICT_PDF_DOI if defer_mismatch else "",
        )
        self.manifest.write(rec)
        with self._stats_lock:
            self.stats.bump(STATUS_OK, cand.source)
        self._log_item(
            item,
            f"[green]ok[/] {escape('[' + cand.source + ']')} -> {escape(str(primary.relative_to(self.cfg.out_dir)))}",
        )
        if defer_mismatch:
            self._log_item(
                item,
                "[yellow]saved, not attached (--strict-pdf-doi)[/]",
            )
            self._add_outcome(rec)
        elif self.attacher:
            self.attach_record(rec)
        else:
            self._add_outcome(rec)
        return True

    def _fetch_url(
        self, item: Item, cand: Candidate, url: str, attempts: list[str]
    ) -> Download | None:
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
            if not browser_first:
                return self._browser_pdf(item, cand, url, attempts)
            return None

    def _browser_first(self, url: str, source: str) -> bool:
        if self.browser is None or not self.browser.available():
            return False
        if source == "ezproxy":
            return True
        return is_publisher_url(url)

    def _browser_pdf(
        self, item: Item, cand: Candidate, url: str, attempts: list[str]
    ) -> Download | None:
        if self.browser is None or not self.browser.available():
            return None
        if cand.source not in {"ezproxy", "scholar"} and not is_publisher_url(url):
            return None
        targets = [url]
        if (
            self.cfg.ezproxy_base
            and is_publisher_url(url)
            and "idm.oclc.org" not in urlparse(url).netloc
        ):
            wrapped = proxify(url, self.cfg.ezproxy_base)
            if wrapped != url:
                targets = [wrapped, url]
        for target in targets:
            self._log_item(
                item, f"[dim]{escape(cand.source)}: downloading via browser...[/]"
            )
            try:
                content, final = self.browser.fetch_pdf(target)
            except Exception as exc:
                attempts.append(f"{cand.source}:browser-failed({exc})")
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [yellow]browser failed[/] ({escape(str(exc))})",
                )
                continue
            if not looks_like_pdf(content) or len(content) < self.cfg.min_pdf_bytes:
                attempts.append(f"{cand.source}:browser-failed(not a PDF)")
                self._log_item(
                    item,
                    f"{escape(cand.source)}: [yellow]browser failed[/] (not a PDF)",
                )
                continue
            attempts.append(f"{cand.source}:browser")
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
            self._add_outcome(rec)
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
        if not item.doi and not item.arxiv_id and not item.url:
            self._record(
                item, STATUS_NO_IDENTIFIER, attempts, reason="no DOI, arXiv id or URL"
            )
        elif any(
            a.endswith(":error") or "download-failed" in a for a in attempts
        ) and not any(a.endswith(":not_found") for a in attempts):
            self._record(item, STATUS_ERROR, attempts, reason="only transient failures")
        else:
            self._record(item, STATUS_NOT_FOUND, attempts, reason="no source had it")

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
            STATUS_ERROR: "red",
        }[status]
        self._log_item(
            item, f"[{colour}]{status}[/]" + (f" [dim]({reason})[/]" if reason else "")
        )
        self._add_outcome(rec)

    def _add_outcome(self, rec: Record, attach_code: str | None = None) -> None:
        err = error_type_for(rec.status, rec.reason, attach_code)
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
