"""All-in E2E harness: NBA keyword (2025–2026) → ORCID → fetch → CRM → reachout.

Opt-in live run only (``PAPERFUL_E2E=1`` or ``--force``). Default CI stays offline;
see ``tests/test_e2e_nba.py`` and ``docs/e2e-nba.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "paperful.e2e_nba.report.v1"
COLLECTION = "e2e/NBA"
QUERY = "NBA"
YEAR_FROM = 2025
YEAR_TO = 2026
MAX_CANDIDATES = 12
MAX_ORCIDS = 3
TWENTY_LIMIT = 5
ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", re.I)

PHASES = (
    "doctor",
    "snowball_search",
    "snowball_orcid",
    "run_fetch",
    "hygiene",
    "authors_pack",
    "twenty",
    "reachout",
    "handoff_tabs",
    "report",
)


@dataclass
class PhaseResult:
    name: str
    status: str  # ok | skip | fail
    required: bool = True
    reason: str = ""
    exit_code: int | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


def extract_orcids_from_candidates(
    path: Path, *, limit: int = MAX_ORCIDS
) -> list[str]:
    """Collect unique ORCID iDs from a snowball ``candidates.jsonl`` queue."""
    from .snowball.openalex import normalize_orcid

    seen: list[str] = []
    found: set[str] = set()
    if not path.is_file():
        return seen

    def _add(raw: str) -> bool:
        oid = normalize_orcid(raw) or ""
        if not oid:
            match = ORCID_RE.search(raw or "")
            oid = normalize_orcid(match.group(0)) if match else ""
        if not oid or oid in found:
            return False
        found.add(oid)
        seen.append(oid)
        return bool(limit and len(seen) >= limit)

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            biblio = row.get("biblio") or {}
            for rec in biblio.get("author_records") or []:
                if not isinstance(rec, dict):
                    continue
                if _add(str(rec.get("orcid") or "")):
                    return seen
            blob = json.dumps(row, ensure_ascii=False)
            for match in ORCID_RE.finditer(blob):
                if _add(match.group(0)):
                    return seen
    return seen


def soft_skip_matrix(
    *,
    twenty_ready: bool,
    searx_ready: bool,
    llm_enabled: bool,
    tabs_live: bool,
) -> dict[str, str]:
    """Expected soft-skip reasons when optional services are off."""
    out: dict[str, str] = {}
    if not twenty_ready:
        out["twenty"] = "Twenty off or TWENTY_API_KEY / base_url missing"
    if not searx_ready:
        out["searxng"] = "SEARXNG_BASE_URL / [searxng].base_url unset"
    if not llm_enabled:
        out["summarize"] = "llm.enabled is false"
        out["browser_agent"] = "llm.enabled is false"
    if not tabs_live:
        out["handoff_tabs"] = "PAPERFUL_E2E_TABS unset; using handoff list"
    return out


def phase_index(name: str) -> int:
    try:
        return PHASES.index(name)
    except ValueError as exc:
        raise ValueError(f"unknown phase {name!r}") from exc


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class E2ERunner:
    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        run_id: str | None = None,
        from_phase: str = "doctor",
        only_phase: str | None = None,
        dry_run_search: bool = True,
        paperful: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.root = _repo_root()
        self.run_id = run_id or _utc_stamp()
        base = state_dir or (self.root / "state" / "e2e-nba" / self.run_id)
        self.dest = base
        self.dest.mkdir(parents=True, exist_ok=True)
        self.from_phase = from_phase
        self.only_phase = only_phase
        self.dry_run_search = dry_run_search
        self._paperful = paperful or self._default_paperful
        self.env = env if env is not None else dict(os.environ)
        self.results: list[PhaseResult] = []
        self.meta: dict[str, Any] = {
            "schema": SCHEMA,
            "run_id": self.run_id,
            "collection": COLLECTION,
            "query": QUERY,
            "year_from": YEAR_FROM,
            "year_to": YEAR_TO,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.snowball_run_id: str | None = None
        self.orcid_run_id: str | None = None

    def _default_paperful(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        cmd = ["uv", "run", "paperful", *args]
        return subprocess.run(
            cmd,
            cwd=str(self.root),
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
            **kwargs,
        )

    def _log(self, msg: str) -> None:
        line = f"[e2e-nba {self.run_id}] {msg}"
        print(line, flush=True)
        with (self.dest / "watch.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _should_run(self, name: str) -> bool:
        if self.only_phase:
            return name == self.only_phase
        return phase_index(name) >= phase_index(self.from_phase)

    def _record(self, result: PhaseResult) -> PhaseResult:
        self.results.append(result)
        path = self.dest / f"phase-{result.name}.json"
        path.write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._log(f"{result.name}: {result.status}" + (f" — {result.reason}" if result.reason else ""))
        return result

    def _parse_agent_json(self, stdout: str) -> dict[str, Any] | None:
        text = stdout.strip()
        if not text:
            return None
        # Prefer last JSON object on stdout
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.rfind("{")
        if start < 0:
            return None
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return None

    def _run_cmd(
        self,
        args: list[str],
        *,
        phase: str,
        required: bool = True,
        want_json: bool = False,
    ) -> tuple[PhaseResult, dict[str, Any] | None]:
        full = list(args)
        # Only attach --format when the verb supports AgentFormatOpt.
        if want_json and "--format" not in full:
            full.extend(["--format", "json"])
        self._log("$ uv run paperful " + " ".join(full))
        proc = self._paperful(full)
        (self.dest / f"{phase}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (self.dest / f"{phase}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
        payload = self._parse_agent_json(proc.stdout or "") if want_json else None
        ok = proc.returncode == 0 or (proc.returncode == 3 and not required)
        status = "ok" if proc.returncode in (0, 3) else "fail"
        # exit 3 = partial; treat as ok for required phases that allow partial
        if proc.returncode == 3:
            status = "ok"
        if proc.returncode not in (0, 3) and required:
            status = "fail"
        reason = ""
        if status == "fail":
            reason = (proc.stderr or proc.stdout or "").strip().splitlines()
            reason = reason[-1] if reason else f"exit {proc.returncode}"
        summary: dict[str, Any] = {"argv": full, "returncode": proc.returncode}
        if payload:
            summary["agent"] = {
                "ok": payload.get("ok"),
                "exit": payload.get("exit"),
                "summary": payload.get("summary"),
                "paths": payload.get("paths"),
            }
            paths = payload.get("paths") or {}
            run_path = paths.get("run") or paths.get("queue") or paths.get("dest")
            if run_path:
                summary["run_path"] = run_path
        result = PhaseResult(
            name=phase,
            status=status,
            required=required,
            reason=reason,
            exit_code=proc.returncode,
            summary=summary,
        )
        return result, payload

    def phase_doctor(self) -> PhaseResult:
        result, _ = self._run_cmd(["doctor", "--no-guide"], phase="doctor", required=True)
        # doctor: 0 ok, 1 warnings, 2 env/manager missing
        if result.exit_code in (0, 1):
            result.status = "ok"
            if result.exit_code == 1:
                result.reason = result.reason or "doctor warnings (exit 1)"
        else:
            result.status = "fail"
            result.reason = result.reason or f"doctor exit {result.exit_code}"
        return self._record(result)

    def phase_snowball_search(self) -> PhaseResult:
        if self.dry_run_search:
            dry, _ = self._run_cmd(
                [
                    "snowball",
                    "search",
                    QUERY,
                    "--year-from",
                    str(YEAR_FROM),
                    "--year-to",
                    str(YEAR_TO),
                    "--max-candidates",
                    str(MAX_CANDIDATES),
                    "--depth",
                    "1",
                    "--gate",
                    "dry-run",
                    "--fetch-pdfs",
                    "off",
                ],
                phase="snowball_search_dry",
                required=True,
                want_json=True,
            )
            (self.dest / "phase-snowball_search_dry.json").write_text(
                json.dumps(asdict(dry), indent=2) + "\n", encoding="utf-8"
            )
            if dry.status == "fail":
                dry.name = "snowball_search"
                return self._record(dry)

        result, payload = self._run_cmd(
            [
                "snowball",
                "search",
                QUERY,
                "--year-from",
                str(YEAR_FROM),
                "--year-to",
                str(YEAR_TO),
                "--max-candidates",
                str(MAX_CANDIDATES),
                "--depth",
                "1",
                "--gate",
                "auto",
                "--fetch-pdfs",
                "full",
                "-C",
                COLLECTION,
            ],
            phase="snowball_search",
            required=True,
            want_json=True,
        )
        run_id = self._snowball_id_from_payload(payload, result)
        if run_id:
            self.snowball_run_id = run_id
            result.artifacts["queue"] = str(
                self.root / "state" / "snowball" / run_id / "candidates.jsonl"
            )
            queue = Path(result.artifacts["queue"])
            if queue.is_file():
                n = sum(1 for line in queue.open(encoding="utf-8") if line.strip())
                result.summary["candidate_count"] = n
                if n < 1:
                    result.status = "fail"
                    result.reason = "no OpenAlex hits for NBA 2025–2026"
        elif result.status == "ok":
            # Try newest snowball dir
            newest = self._newest_snowball_run()
            if newest:
                self.snowball_run_id = newest.name
                result.artifacts["queue"] = str(newest / "candidates.jsonl")
        return self._record(result)

    def _snowball_id_from_payload(
        self, payload: dict[str, Any] | None, result: PhaseResult
    ) -> str | None:
        if not payload:
            return None
        summary = payload.get("summary") or {}
        for key in ("run_id", "run"):
            val = summary.get(key)
            if val:
                return str(val)
        paths = payload.get("paths") or {}
        for key in ("run", "queue", "dest"):
            raw = paths.get(key)
            if not raw:
                continue
            path = Path(str(raw))
            if path.name == "candidates.jsonl":
                return path.parent.name
            if (path / "candidates.jsonl").is_file() or path.is_dir():
                return path.name
        return None

    def _newest_snowball_run(self) -> Path | None:
        root = self.root / "state" / "snowball"
        if not root.is_dir():
            return None
        dirs = [p for p in root.iterdir() if p.is_dir() and (p / "candidates.jsonl").is_file()]
        if not dirs:
            return None
        return max(dirs, key=lambda p: p.stat().st_mtime)

    def phase_snowball_orcid(self) -> PhaseResult:
        queue: Path | None = None
        if self.snowball_run_id:
            queue = self.root / "state" / "snowball" / self.snowball_run_id / "candidates.jsonl"
        if queue is None or not queue.is_file():
            newest = self._newest_snowball_run()
            queue = (newest / "candidates.jsonl") if newest else None
        if queue is None or not queue.is_file():
            return self._record(
                PhaseResult(
                    name="snowball_orcid",
                    status="skip",
                    required=False,
                    reason="no candidates.jsonl to extract ORCIDs from",
                )
            )
        orcids = extract_orcids_from_candidates(queue, limit=MAX_ORCIDS)
        if not orcids:
            return self._record(
                PhaseResult(
                    name="snowball_orcid",
                    status="skip",
                    required=False,
                    reason="no ORCIDs on snowball author_records",
                    artifacts={"queue": str(queue)},
                )
            )
        args = [
            "snowball",
            "orcid",
            *orcids,
            "--year-from",
            str(YEAR_FROM),
            "--year-to",
            str(YEAR_TO),
            "--max-candidates",
            str(MAX_CANDIDATES),
            "--depth",
            "1",
            "--gate",
            "auto",
            "--fetch-pdfs",
            "full",
            "-C",
            COLLECTION,
            "--author-site-preflight",
        ]
        result, payload = self._run_cmd(
            args, phase="snowball_orcid", required=True, want_json=True
        )
        result.summary["orcids"] = orcids
        result.artifacts["queue_source"] = str(queue)
        run_id = self._snowball_id_from_payload(payload, result)
        if run_id:
            self.orcid_run_id = run_id
            result.artifacts["queue"] = str(
                self.root / "state" / "snowball" / run_id / "candidates.jsonl"
            )
        return self._record(result)

    def phase_run_fetch(self) -> PhaseResult:
        result, _ = self._run_cmd(
            [
                "run",
                "-C",
                COLLECTION,
                "--year-from",
                str(YEAR_FROM),
                "--year-to",
                str(YEAR_TO),
                "--try-all",
                "--retry-failed",
                "--upgrade-linked",
                "--browser-agent",
            ],
            phase="run_fetch",
            required=True,
            want_json=True,
        )
        return self._record(result)

    def phase_hygiene(self) -> PhaseResult:
        result, _ = self._run_cmd(
            [
                "all",
                "-C",
                COLLECTION,
                "--year-from",
                str(YEAR_FROM),
                "--year-to",
                str(YEAR_TO),
                "--steps",
                "lint,fix-metadata,summarize",
                "--apply",
            ],
            phase="hygiene",
            required=True,
            want_json=False,
        )
        # summarize may soft-skip when llm off; all still exits 0
        return self._record(result)

    def phase_authors_pack(self) -> PhaseResult:
        apply_res, _ = self._run_cmd(
            ["authors", "-C", COLLECTION, "--apply"],
            phase="authors_apply",
            required=False,
            want_json=True,
        )
        slug = "e2e-nba"
        promote, _ = self._run_cmd(
            ["snowball", "packs", "promote", slug],
            phase="authors_promote",
            required=False,
        )
        dry, _ = self._run_cmd(
            [
                "run",
                "-C",
                COLLECTION,
                "--dry-run",
                "--no-browser-agent",
                "--retry-failed",
            ],
            phase="authors_dry_run",
            required=False,
        )
        status = "ok"
        reason = ""
        if apply_res.status == "fail" and promote.status == "fail":
            status = "skip"
            reason = "authors/promote failed (no people or empty collection)"
        result = PhaseResult(
            name="authors_pack",
            status=status,
            required=False,
            reason=reason,
            summary={
                "apply": asdict(apply_res),
                "promote": asdict(promote),
                "dry_run_exit": dry.exit_code,
            },
            artifacts={"slug": slug},
        )
        return self._record(result)

    def phase_twenty(self) -> PhaseResult:
        # lookup has no --limit / --format; sync does.
        probe, _ = self._run_cmd(
            ["twenty", "lookup", "-C", COLLECTION],
            phase="twenty_probe",
            required=False,
            want_json=False,
        )
        stderr = (self.dest / "twenty_probe.stderr.txt").read_text(encoding="utf-8")
        stdout = (self.dest / "twenty_probe.stdout.txt").read_text(encoding="utf-8")
        blob = (stderr + "\n" + stdout).lower()
        not_ready = probe.exit_code not in (0, 3) and (
            "not ready" in blob
            or "twenty is off" in blob
            or "api_key" in blob
            or "twenty_api_key" in blob
        )
        if not_ready:
            return self._record(
                PhaseResult(
                    name="twenty",
                    status="skip",
                    required=False,
                    reason="Twenty not ready",
                    exit_code=probe.exit_code,
                )
            )
        lookup, _ = self._run_cmd(
            ["twenty", "lookup", "-C", COLLECTION, "--apply"],
            phase="twenty_lookup",
            required=False,
            want_json=False,
        )
        sync, _ = self._run_cmd(
            [
                "twenty",
                "sync",
                "-C",
                COLLECTION,
                "--apply",
                "--limit",
                str(TWENTY_LIMIT),
                "--yes",
            ],
            phase="twenty_sync",
            required=False,
            want_json=True,
        )
        status = "ok" if lookup.status == "ok" or sync.status == "ok" else "skip"
        if lookup.status == "fail" and sync.status == "fail":
            status = "skip"
        return self._record(
            PhaseResult(
                name="twenty",
                status=status,
                required=False,
                reason="" if status == "ok" else "lookup/sync did not succeed",
                summary={"lookup": asdict(lookup), "sync": asdict(sync)},
            )
        )

    def phase_reachout(self) -> PhaseResult:
        csv_path = self.dest / "reachout.csv"
        args = ["reachout", "-C", COLLECTION, "--to", str(csv_path)]
        # --lookup when Twenty may be ready; CLI soft-ignores if not
        args.append("--lookup")
        result, _ = self._run_cmd(args, phase="reachout", required=True, want_json=True)
        if csv_path.is_file():
            result.artifacts["csv"] = str(csv_path)
            text = csv_path.read_text(encoding="utf-8")
            rows = max(0, len(text.splitlines()) - 1)
            result.summary["csv_rows"] = rows
        else:
            # reachout may write relative to cwd; still require a file
            if result.status == "ok":
                result.status = "fail"
                result.reason = f"missing reachout CSV at {csv_path}"
        return self._record(result)

    def phase_handoff_tabs(self) -> PhaseResult:
        tabs_live = self.env.get("PAPERFUL_E2E_TABS") == "1"
        opened: list[str] = []

        if tabs_live:
            mode = "tabs"
        else:
            mode = "list"

        # Capture URLs by monkeypatching webbrowser when tabs requested
        if tabs_live:
            real_open = webbrowser.open

            def capture(url: str, *a: Any, **k: Any) -> bool:
                opened.append(url)
                return real_open(url, *a, **k)

            webbrowser.open = capture  # type: ignore[method-assign]
        try:
            result, _ = self._run_cmd(
                [
                    "gaps",
                    "-C",
                    COLLECTION,
                    "--list-missing",
                    "--handoff",
                    mode,
                ],
                phase="handoff_tabs",
                required=True,
                want_json=True,
            )
        finally:
            if tabs_live:
                webbrowser.open = real_open  # type: ignore[method-assign]

        if not tabs_live:
            result.reason = result.reason or "PAPERFUL_E2E_TABS unset; used handoff list"
            result.summary["tabs_live"] = False
        else:
            result.summary["tabs_live"] = True
            result.summary["opened"] = opened
            (self.dest / "opened_tabs.json").write_text(
                json.dumps(opened, indent=2) + "\n", encoding="utf-8"
            )
            result.artifacts["opened_tabs"] = str(self.dest / "opened_tabs.json")
        return self._record(result)

    def phase_report(self) -> PhaseResult:
        required_failed = [
            r for r in self.results if r.required and r.status == "fail"
        ]
        ok = not required_failed
        result = PhaseResult(
            name="report",
            status="ok" if ok else "fail",
            required=True,
            reason="" if ok else f"failed: {[r.name for r in required_failed]}",
            summary={"ok": ok},
        )
        # Record first so report.json includes the report phase itself.
        self._record(result)
        payload = {
            **self.meta,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "snowball_run_id": self.snowball_run_id,
            "orcid_run_id": self.orcid_run_id,
            "phases": [asdict(r) for r in self.results],
            "ok": ok,
            "failed_required": [r.name for r in required_failed],
        }
        report_json = self.dest / "report.json"
        report_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        lines = [
            f"# E2E NBA report `{self.run_id}`",
            "",
            f"- Collection: `{COLLECTION}`",
            f"- Query: `{QUERY}` ({YEAR_FROM}–{YEAR_TO})",
            f"- OK: **{payload['ok']}**",
            "",
            "| Phase | Status | Required | Reason |",
            "| --- | --- | --- | --- |",
        ]
        for r in self.results:
            reason = (r.reason or "").replace("|", "\\|")
            lines.append(
                f"| `{r.name}` | {r.status} | {r.required} | {reason} |"
            )
        lines.append("")
        lines.append(f"Machine witness: `{report_json}`")
        lines.append("")
        report_md = self.dest / "REPORT.md"
        report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result.artifacts = {
            "report_json": str(report_json),
            "report_md": str(report_md),
        }
        (self.dest / "phase-report.json").write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return result

    def run(self) -> int:
        self._log(f"dest={self.dest}")
        dispatch: dict[str, Callable[[], PhaseResult]] = {
            "doctor": self.phase_doctor,
            "snowball_search": self.phase_snowball_search,
            "snowball_orcid": self.phase_snowball_orcid,
            "run_fetch": self.phase_run_fetch,
            "hygiene": self.phase_hygiene,
            "authors_pack": self.phase_authors_pack,
            "twenty": self.phase_twenty,
            "reachout": self.phase_reachout,
            "handoff_tabs": self.phase_handoff_tabs,
            "report": self.phase_report,
        }
        for name in PHASES:
            if name == "report":
                continue
            if not self._should_run(name):
                self._log(f"skip (from-phase): {name}")
                continue
            result = dispatch[name]()
            if result.status == "fail" and result.required:
                self._log(f"required phase failed: {name}")
                self.phase_report()
                return 1
        if self._should_run("report") or self.only_phase is None:
            final = self.phase_report()
            return 0 if final.status == "ok" else 1
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paperful all-in E2E (NBA 2025–2026)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even when PAPERFUL_E2E is unset (same as PAPERFUL_E2E=1).",
    )
    parser.add_argument(
        "--from-phase",
        default="doctor",
        choices=PHASES,
        help="Resume from this phase (inclusive).",
    )
    parser.add_argument(
        "--phase",
        default=None,
        choices=PHASES,
        help="Run only this phase.",
    )
    parser.add_argument(
        "--no-dry-run-search",
        action="store_true",
        help="Skip the snowball dry-run before gate auto.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Reuse an existing state/e2e-nba/<run-id> directory.",
    )
    args = parser.parse_args(argv)
    if os.environ.get("PAPERFUL_E2E") != "1" and not args.force:
        print(
            "Refusing live E2E: set PAPERFUL_E2E=1 or pass --force. "
            "See docs/e2e-nba.md.",
            file=sys.stderr,
        )
        return 2
    runner = E2ERunner(
        run_id=args.run_id,
        from_phase=args.from_phase,
        only_phase=args.phase,
        dry_run_search=not args.no_dry_run_search,
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
