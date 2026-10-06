"""Fetch phase helpers used by Pipeline."""

from __future__ import annotations

import random
import time

from rich.markup import escape

from .pipeline_browser import skip_recover_without_lane_failure
from .runreport import classify_enrichment
from .store import STATUS_CAPTCHA, STATUS_ERROR
from .zot import Item


def _pl():
    from . import pipeline as pl

    return pl


def phase_oa(self, item: Item, oa_sources: list[str]) -> list[str] | None:
        attempts: list[str] = []
        self._log_item_label(item)
        notes = _pl().prepare_identifiers(
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
            cand = _pl().REGISTRY[name].find(item, self.ctx)
            attempts.append(
                f"{name}:{cand.outcome.value}" + (f"({cand.note})" if cand.note else "")
            )
            with self._stats_lock:
                self.stats.note_source(name, cand.outcome.value)
            self._log_source_result(item, name, cand)
            self._maybe_trip_circuit(name, cand)
            if cand.outcome is _pl().Outcome.FOUND and self._try_download(
                item, cand, attempts
            ):
                self.progress()
                return None
        if self._retry_published_oa(item, oa_sources, attempts):
            self.progress()
            return None
        return attempts

def phase_one(
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
        cand = _pl().REGISTRY[name].find(item, self.ctx)
        if name == "browser_agent" and cand.outcome is _pl().Outcome.FOUND:
            self._note_agent_after_playwright(item, cand, attempts)
        note = f"({cand.note})" if cand.note else ""
        attempts.append(f"{name}:{cand.outcome.value}{note}")
        with self._stats_lock:
            self.stats.note_source(name, cand.outcome.value)
        self._log_source_result(item, name, cand)
        self._maybe_trip_circuit(name, cand)
        if cand.outcome is _pl().Outcome.FOUND and self._try_download(item, cand, attempts):
            self.progress()
            return "hit", True
        if name == "scihub":
            if cand.outcome is _pl().Outcome.CAPTCHA:
                self._record(item, STATUS_CAPTCHA, attempts, reason=cand.note)
                self.progress()
                return "terminal", True
            if cand.outcome is _pl().Outcome.ERROR:
                self._record(item, STATUS_ERROR, attempts, reason=cand.note)
                self.progress()
                return "terminal", True
        if cand.outcome is _pl().Outcome.ERROR and "session expired" in (cand.note or ""):
            self._mark_ezproxy_down()
            return "ezproxy_down", True
        if name == "browser_agent" and cand.outcome is _pl().Outcome.CAPTCHA:
            self._mark_browser_agent_down()
            return "agent_down", True
        if name == "scholar" and _pl()._scholar_blocked(cand):
            self._mark_scholar_down(cand.note or cand.outcome.value)
            return "scholar_down", True
        if name == "serpapi" and _pl()._serpapi_blocked(cand):
            self._mark_serpapi_down(cand.note or cand.outcome.value)
            return "serpapi_down", True
        return "still", True

def phase_serial(
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
            status, called = phase_one(self, name, item, attempts)
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

def phase_interleave(
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
                status, called = phase_one(self, first, item, attempts)
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
                status, called_second = phase_one(self, second, item, attempts)
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

def phase_scihub(
        self, queue: list[tuple[Item, list[str]]]
    ) -> list[tuple[Item, list[str]]]:
        return phase_serial(self, queue, "scihub", scihub_delay=True)
