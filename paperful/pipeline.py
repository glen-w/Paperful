"""Orchestrates: resolve identifier -> OA sources (parallel) -> Sci-Hub (serial) -> save -> attach."""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx
from rich.console import Console
from rich.markup import escape

from .attach import Attacher
from .circuit import CircuitBreaker
from .config import Config
from .cookies import apply_netscape_cookies
from .routing import sources_for_item
from .download import DownloadError, fetch_pdf
from .resolve import crossref_lookup
from .sources import REGISTRY, Candidate, Context, Outcome
from .store import (
    STATUS_ATTACH_FAILED,
    STATUS_ATTACHED,
    STATUS_CAPTCHA,
    STATUS_ERROR,
    STATUS_NO_IDENTIFIER,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
    Record,
    relpaths,
    save_pdf,
)
from .zot import Item

# Sources that hit publishers via a shared campus session — keep serial & polite.
_SERIAL_SOURCES = frozenset({"scihub", "ezproxy"})


def make_client(cfg: Config) -> httpx.Client:
    client = httpx.Client(
        headers={"User-Agent": cfg.user_agent, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30,
        limits=httpx.Limits(max_connections=cfg.concurrency_oa + 2),
    )
    apply_netscape_cookies(client, cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt"))
    apply_netscape_cookies(client, cfg.scholar_cookies or (cfg.state_dir / "scholar-cookies.txt"))
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
    by_source: dict[str, int] = field(default_factory=dict)

    def bump(self, status: str, source: str | None = None) -> None:
        if hasattr(self, status):
            setattr(self, status, getattr(self, status) + 1)
        if source and status in (STATUS_OK, STATUS_ATTACHED):
            self.by_source[source] = self.by_source.get(source, 0) + 1


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        manifest: Manifest,
        console: Console,
        sources: list[str] | None = None,
        attacher: Attacher | None = None,
        progress: Callable[[], None] | None = None,
        try_all: bool | None = None,
    ):
        self.cfg = cfg
        self.manifest = manifest
        self.console = console
        self.sources = sources or cfg.sources
        self.try_all = try_all if try_all is not None else not cfg.source_routing
        self.attacher = attacher
        self.progress = progress or (lambda: None)
        self.client = make_client(cfg)
        self.ctx = Context(config=cfg, client=self.client)
        self.stats = RunStats()
        self._circuit = CircuitBreaker(cfg.circuit_breaker_threshold)
        self._attach_lock = threading.Lock()
        self._print_lock = threading.Lock()
        self._stop = threading.Event()
        self._run_total = 0
        self._item_index: dict[str, int] = {}

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
        return self.stats

    def _run_batch(self, items: list[Item]) -> None:
        oa_sources = [s for s in self.sources if s not in _SERIAL_SOURCES and s in REGISTRY]
        serial = [s for s in self.sources if s in _SERIAL_SOURCES and s in REGISTRY]
        use_scihub = "scihub" in serial
        use_ezproxy = "ezproxy" in serial
        pending: list[tuple[Item, list[str]]] = []
        queue_lock = threading.Lock()

        def oa_worker(item: Item) -> None:
            if self._stop.is_set():
                return
            attempts = self._phase_oa(item, oa_sources)
            if attempts is None:
                return  # resolved (ok or terminal)
            lanes = self._lanes_for(item)
            next_serial = next((s for s in self.sources if s in _SERIAL_SOURCES and s in lanes), None)
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
            still = self._phase_serial(pending, "ezproxy") if use_ezproxy else pending
            if self._stop.is_set():
                return
            if use_scihub:
                scihub_queue = [(it, att) for it, att in still if "scihub" in self._lanes_for(it)]
                scihub_keys = {it.key for it, _ in scihub_queue}
                for item, attempts in still:
                    if item.key not in scihub_keys:
                        self._finish_miss(item, attempts)
                        self.progress()
                if scihub_queue:
                    self._phase_scihub(scihub_queue)
            else:
                for item, attempts in still:
                    self._finish_miss(item, attempts)
                    self.progress()

    # ---- phase 1: identifier + OA -------------------------------------------
    def _phase_oa(self, item: Item, oa_sources: list[str]) -> list[str] | None:
        attempts: list[str] = []
        self._log_item_label(item)
        if not item.doi and item.title and item.item_type not in {"webpage", "blogPost", "forumPost"}:
            self._log_item(item, "[dim]crossref: looking up DOI from title...[/]")
            match = crossref_lookup(
                self.client, item.title, item.first_author, item.year, self.cfg.email, self.cfg.crossref_min_score
            )
            if match:
                item.doi, item.doi_source = match.doi, "crossref"
                attempts.append(f"crossref:matched({match.score:.2f})")
                self._log_item(item, f"crossref: [green]matched[/] {escape(match.doi)} (score {match.score:.2f})")
            else:
                attempts.append("crossref:no-match")
                self._log_item(item, "crossref: [dim]no match[/]")
        lanes = self._lanes_for(item)
        self._log_item_trying_line(item, lanes)
        for name in oa_sources:
            if self._stop.is_set():
                return attempts
            if self._skip_source(item, name, lanes, attempts):
                continue
            cand = REGISTRY[name].find(item, self.ctx)
            attempts.append(f"{name}:{cand.outcome.value}" + (f"({cand.note})" if cand.note else ""))
            self._log_source_result(item, name, cand)
            self._maybe_trip_circuit(name, cand)
            if cand.outcome is Outcome.FOUND and self._try_download(item, cand, attempts):
                self.progress()
                return None
        return attempts

    # ---- phase 2: campus EZProxy, serial ------------------------------------
    def _phase_serial(self, queue: list[tuple[Item, list[str]]], name: str) -> list[tuple[Item, list[str]]]:
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
            self._log_item(item, f"[dim]{name}: checking...[/]")
            cand = REGISTRY[name].find(item, self.ctx)
            note = f"({cand.note})" if cand.note else ""
            attempts.append(f"{name}:{cand.outcome.value}{note}")
            self._log_source_result(item, name, cand)
            self._maybe_trip_circuit(name, cand)
            if cand.outcome is Outcome.FOUND and self._try_download(item, cand, attempts):
                self.progress()
                continue
            if cand.outcome is Outcome.ERROR and "session expired" in (cand.note or ""):
                self._emit("[yellow]ezproxy session expired; skipping remaining proxy attempts this batch[/]")
                still.append((item, attempts))
                still.extend(queue[idx + 1 :])
                return still
            still.append((item, attempts))
        return still

    # ---- phase 3: Sci-Hub, serial --------------------------------------------
    def _phase_scihub(self, queue: list[tuple[Item, list[str]]]) -> None:
        self._emit(f"[bold]-- scihub[/] ({len(queue)} remaining)")
        lo, hi = self.cfg.delay_scihub_s
        first = True
        for item, attempts in queue:
            if self._stop.is_set():
                return
            if not first:
                time.sleep(random.uniform(lo, hi))
            first = False
            lanes = self._lanes_for(item)
            if self._skip_source(item, "scihub", lanes, attempts):
                self._finish_miss(item, attempts)
                self.progress()
                continue
            self._log_item(item, "[dim]scihub: checking...[/]")
            cand = REGISTRY["scihub"].find(item, self.ctx)
            attempts.append(f"scihub:{cand.outcome.value}" + (f"({cand.note})" if cand.note else ""))
            self._log_source_result(item, "scihub", cand)
            self._maybe_trip_circuit("scihub", cand)
            if cand.outcome is Outcome.FOUND and self._try_download(item, cand, attempts):
                self.progress()
                continue
            if cand.outcome is Outcome.CAPTCHA:
                self._record(item, STATUS_CAPTCHA, attempts, reason=cand.note)
            elif cand.outcome is Outcome.ERROR:
                self._record(item, STATUS_ERROR, attempts, reason=cand.note)
            else:
                self._finish_miss(item, attempts)
            self.progress()

    # ---- helpers ----------------------------------------------------------------
    def _lanes_for(self, item: Item) -> list[str]:
        configured = [s for s in self.sources if s in REGISTRY]
        if self.try_all:
            routed = configured
        else:
            routed = sources_for_item(item, self.cfg, configured)
        return [s for s in routed if not self._circuit.tripped(s)]

    def _skip_source(self, item: Item, name: str, lanes: list[str], attempts: list[str]) -> bool:
        if name in lanes:
            return False
        if self._circuit.tripped(name):
            attempts.append(f"{name}:skipped(circuit open)")
            self._log_item(item, f"{escape(name)}: [dim]skipped[/] (blocked for rest of run)")
        else:
            attempts.append(f"{name}:skipped(not applicable)")
            self._log_item(item, f"{escape(name)}: [dim]skipped[/] (not applicable)")
        return True

    def _maybe_trip_circuit(self, name: str, cand: Candidate) -> None:
        if self._circuit.note(name, cand.outcome, cand.note or ""):
            self._emit(
                f"[yellow]{name} blocked {self.cfg.circuit_breaker_threshold} times; "
                f"skipping {name} for rest of run[/]"
            )

    def _try_download(self, item: Item, cand: Candidate, attempts: list[str]) -> bool:
        self._log_item(item, f"[dim]{cand.source}: downloading...[/]")
        dl = None
        for url in cand.urls[:6]:
            try:
                dl = fetch_pdf(self.client, url, referer=cand.referer, min_bytes=self.cfg.min_pdf_bytes)
                break
            except DownloadError as exc:
                attempts.append(f"{cand.source}:download-failed({exc})")
                self._log_item(item, f"{escape(cand.source)}: [yellow]download failed[/] ({escape(str(exc))})")
        if dl is None:
            return False
        primary, extras = save_pdf(self.cfg.out_dir, item, dl.content, dl.md5)
        rec = Record(
            itemKey=item.key,
            status=STATUS_OK,
            title=item.title,
            doi=item.doi,
            doi_source=item.doi_source,
            source=cand.source,
            url=dl.final_url,
            path=str(primary),
            extra_paths=relpaths(self.cfg.out_dir, extras),
            md5=dl.md5,
            attempts=attempts,
        )
        self.manifest.write(rec)
        self.stats.bump(STATUS_OK, cand.source)
        self._log_item(
            item,
            f"[green]ok[/] {escape('[' + cand.source + ']')} -> {escape(str(primary.relative_to(self.cfg.out_dir)))}",
        )
        if self.attacher:
            self.attach_record(rec)
        return True

    def attach_record(self, rec: Record) -> bool:
        if not self.attacher or not rec.path:
            return False
        with self._attach_lock:
            res = self.attacher.attach(rec.itemKey, Path(rec.path))
        if res.ok:
            rec.status = STATUS_ATTACHED
            rec.reason = res.reason
            self.stats.bump(STATUS_ATTACHED)
            self._emit(f"   [cyan]attached[/] {rec.itemKey} ({res.reason})")
        else:
            rec.status = STATUS_ATTACH_FAILED
            rec.reason = res.reason
            self.stats.bump(STATUS_ATTACH_FAILED)
            self._emit(f"   [yellow]attach failed[/] {rec.itemKey}: {res.reason}")
        self.manifest.write(rec)
        return res.ok

    def _finish_miss(self, item: Item, attempts: list[str]) -> None:
        if not item.doi and not item.arxiv_id and not item.url:
            self._record(item, STATUS_NO_IDENTIFIER, attempts, reason="no DOI, arXiv id or URL")
        elif any(a.endswith(":error") or "download-failed" in a for a in attempts) and not any(
            a.endswith(":not_found") for a in attempts
        ):
            self._record(item, STATUS_ERROR, attempts, reason="only transient failures")
        else:
            self._record(item, STATUS_NOT_FOUND, attempts, reason="no source had it")

    def _record(self, item: Item, status: str, attempts: list[str], reason: str = "") -> None:
        rec = Record(
            itemKey=item.key,
            status=status,
            title=item.title,
            doi=item.doi,
            doi_source=item.doi_source,
            url=item.url,
            reason=reason,
            attempts=attempts,
        )
        self.manifest.write(rec)
        self.stats.bump(status)
        colour = {STATUS_NOT_FOUND: "dim", STATUS_NO_IDENTIFIER: "dim", STATUS_CAPTCHA: "yellow", STATUS_ERROR: "red"}[status]
        self._log_item(item, f"[{colour}]{status}[/]" + (f" [dim]({reason})[/]" if reason else ""))

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
            else (f"arXiv:{item.arxiv_id}" if item.arxiv_id else (f"URL {item.url}" if item.url else "no identifier"))
        )
        self._log_item(item, f"[dim]{escape(ident)} · trying: {escape(', '.join(lanes))}[/]")
    def _log_item(self, item: Item, message: str) -> None:
        self._emit(f"\\[{self._item_tag(item)}] {message}")

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
