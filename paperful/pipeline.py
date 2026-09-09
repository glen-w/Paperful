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

from .attach import Attacher
from .config import Config
from .cookies import load_netscape_cookies
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
    cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    if cookie_path.is_file():
        for c in load_netscape_cookies(cookie_path).jar:
            client.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
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
    ):
        self.cfg = cfg
        self.manifest = manifest
        self.console = console
        self.sources = sources or cfg.sources
        self.attacher = attacher
        self.progress = progress or (lambda: None)
        self.client = make_client(cfg)
        self.ctx = Context(config=cfg, client=self.client)
        self.stats = RunStats()
        self._attach_lock = threading.Lock()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    # ---- public --------------------------------------------------------------
    def run(self, items: list[Item], batch_size: int = 40) -> RunStats:
        """Process in batches: OA sources in parallel, then Sci-Hub serially, per batch.

        Batching keeps the manifest current (an interrupted run loses at most one
        batch of Sci-Hub work) and interleaves fast OA hits with slow Sci-Hub polling.
        """
        total = len(items)
        for start in range(0, total, batch_size):
            if self._stop.is_set():
                break
            batch = items[start : start + batch_size]
            if total > batch_size:
                self.console.print(f"[bold]-- batch {start // batch_size + 1}/{-(-total // batch_size)} "
                                   f"(items {start + 1}-{start + len(batch)} of {total})[/]")
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
            if use_ezproxy or (use_scihub and item.doi):
                with queue_lock:
                    pending.append((item, attempts))
            else:
                self._finish_miss(item, attempts)

        with ThreadPoolExecutor(max_workers=self.cfg.concurrency_oa) as pool:
            futures = [pool.submit(oa_worker, it) for it in items]
            try:
                for fut in as_completed(futures):
                    exc = fut.exception()
                    if exc:
                        self.console.print(f"[red]worker error:[/] {type(exc).__name__}: {exc}")
            except KeyboardInterrupt:
                self._stop.set()
                pool.shutdown(wait=False, cancel_futures=True)
                raise

        if pending and not self._stop.is_set():
            still = self._phase_serial(pending, "ezproxy") if use_ezproxy else pending
            if self._stop.is_set():
                return
            if use_scihub:
                no_doi = [(it, att) for it, att in still if not it.doi]
                with_doi = [(it, att) for it, att in still if it.doi]
                for item, attempts in no_doi:
                    self._finish_miss(item, attempts)
                    self.progress()
                if with_doi:
                    self._phase_scihub(with_doi)
            else:
                for item, attempts in still:
                    self._finish_miss(item, attempts)
                    self.progress()

    # ---- phase 1: identifier + OA -------------------------------------------
    def _phase_oa(self, item: Item, oa_sources: list[str]) -> list[str] | None:
        attempts: list[str] = []
        if not item.doi and item.title and item.item_type not in {"webpage", "blogPost", "forumPost"}:
            match = crossref_lookup(
                self.client, item.title, item.first_author, item.year, self.cfg.email, self.cfg.crossref_min_score
            )
            if match:
                item.doi, item.doi_source = match.doi, "crossref"
                attempts.append(f"crossref:matched({match.score:.2f})")
            else:
                attempts.append("crossref:no-match")
        for name in oa_sources:
            if self._stop.is_set():
                return attempts
            cand = REGISTRY[name].find(item, self.ctx)
            attempts.append(f"{name}:{cand.outcome.value}" + (f"({cand.note})" if cand.note else ""))
            if cand.outcome is Outcome.FOUND and self._try_download(item, cand, attempts):
                self.progress()
                return None
        return attempts

    # ---- phase 2: campus EZProxy, serial ------------------------------------
    def _phase_serial(self, queue: list[tuple[Item, list[str]]], name: str) -> list[tuple[Item, list[str]]]:
        """Try a serial source; return items that still need Sci-Hub / finish_miss."""
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
            cand = REGISTRY[name].find(item, self.ctx)
            note = f"({cand.note})" if cand.note else ""
            attempts.append(f"{name}:{cand.outcome.value}{note}")
            if cand.outcome is Outcome.FOUND and self._try_download(item, cand, attempts):
                self.progress()
                continue
            if cand.outcome is Outcome.ERROR and "session expired" in (cand.note or ""):
                self.console.print("[yellow]ezproxy session expired; skipping remaining proxy attempts this batch[/]")
                still.append((item, attempts))
                still.extend(queue[idx + 1 :])
                return still
            still.append((item, attempts))
        return still

    # ---- phase 3: Sci-Hub, serial --------------------------------------------
    def _phase_scihub(self, queue: list[tuple[Item, list[str]]]) -> None:
        lo, hi = self.cfg.delay_scihub_s
        first = True
        for item, attempts in queue:
            if self._stop.is_set():
                return
            if not first:
                time.sleep(random.uniform(lo, hi))
            first = False
            cand = REGISTRY["scihub"].find(item, self.ctx)
            attempts.append(f"scihub:{cand.outcome.value}" + (f"({cand.note})" if cand.note else ""))
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
    def _try_download(self, item: Item, cand: Candidate, attempts: list[str]) -> bool:
        dl = None
        for url in cand.urls[:6]:
            try:
                dl = fetch_pdf(self.client, url, referer=cand.referer, min_bytes=self.cfg.min_pdf_bytes)
                break
            except DownloadError as exc:
                attempts.append(f"{cand.source}:download-failed({exc})")
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
        self.console.print(f"[green]ok[/] [{cand.source}] {item.label} -> {primary.relative_to(self.cfg.out_dir)}")
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
            self.console.print(f"   [cyan]attached[/] {rec.itemKey} ({res.reason})")
        else:
            rec.status = STATUS_ATTACH_FAILED
            rec.reason = res.reason
            self.stats.bump(STATUS_ATTACH_FAILED)
            self.console.print(f"   [yellow]attach failed[/] {rec.itemKey}: {res.reason}")
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
        self.console.print(f"[{colour}]{status}[/] {item.label}" + (f" [dim]({reason})[/]" if reason else ""))
