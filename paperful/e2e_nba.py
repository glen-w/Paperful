"""All-in E2E harness: topic snowball → ORCID → fetch → hygiene → CRM → reachout.

User picks **topic** and **effort** (``low`` / ``med`` / ``high``); every tier runs
the same phase stack. Opt-in live only (``PAPERFUL_E2E=1`` or ``--force``). Default
CI stays offline; see ``tests/test_e2e_nba.py`` and ``docs/e2e-stack.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "paperful.e2e_stack.report.v1"
DEFAULT_TOPIC = "NBA"
DEFAULT_EFFORT = "low"
DEFAULT_FETCH_PDFS = "full"  # snowball gate auto + ORCID hop (Sci-Hub stays off)
ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", re.I)

_EFFORT_PRESETS: dict[str, dict[str, int]] = {
    # low: short smoke (~25 new queue rows); med: single-hop growth; high: 2-hop cap ~3k
    "low": {
        "max_candidates": 25,
        "depth": 1,
        "per_hop_limit": 8,
        "max_orcids": 2,
        "twenty_limit": 5,
    },
    "med": {
        "max_candidates": 250,
        "depth": 1,
        "per_hop_limit": 30,
        "max_orcids": 3,
        "twenty_limit": 10,
    },
    "high": {
        "max_candidates": 3000,
        "depth": 2,
        "per_hop_limit": 50,
        "max_orcids": 5,
        "twenty_limit": 25,
    },
}
EFFORT_CHOICES = tuple(_EFFORT_PRESETS.keys())


@dataclass(frozen=True)
class E2EPlan:
    """Resolved topic + effort caps for one live stack run."""

    topic: str
    query: str
    collection: str
    pack_slug: str
    effort: str
    year_from: int
    year_to: int
    max_candidates: int
    depth: int
    per_hop_limit: int
    max_orcids: int
    twenty_limit: int
    fetch_pdfs: str


def default_year_window() -> tuple[int, int]:
    year = datetime.now(timezone.utc).year
    return year - 1, year


def normalize_effort(effort: str) -> str:
    key = (effort or DEFAULT_EFFORT).strip().lower()
    if key not in _EFFORT_PRESETS:
        raise ValueError(f"effort must be one of {EFFORT_CHOICES}, got {effort!r}")
    return key


def collection_for_topic(topic: str) -> str:
    raw = (topic or "").strip()
    if not raw:
        raise ValueError("topic is required")
    seg = re.sub(r"[^\w\s./-]+", "", raw, flags=re.UNICODE)
    seg = re.sub(r"\s+", " ", seg).strip().replace("/", "-")
    if not seg:
        seg = "topic"
    return f"e2e/{seg}"


def pack_slug_for_topic(topic: str) -> str:
    seg = collection_for_topic(topic).split("/", 1)[-1]
    safe = re.sub(r"[^\w-]+", "-", seg.lower()).strip("-") or "topic"
    return f"e2e-{safe}"


def build_e2e_plan(
    topic: str,
    effort: str = DEFAULT_EFFORT,
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    collection: str | None = None,
) -> E2EPlan:
    t = (topic or DEFAULT_TOPIC).strip()
    if not t:
        raise ValueError("topic is required")
    eff = normalize_effort(effort)
    preset = _EFFORT_PRESETS[eff]
    yf, yt = default_year_window()
    if year_from is not None:
        yf = year_from
    if year_to is not None:
        yt = year_to
    coll = (collection or collection_for_topic(t)).strip()
    return E2EPlan(
        topic=t,
        query=t,
        collection=coll,
        pack_slug=pack_slug_for_topic(t),
        effort=eff,
        year_from=yf,
        year_to=yt,
        max_candidates=preset["max_candidates"],
        depth=preset["depth"],
        per_hop_limit=preset["per_hop_limit"],
        max_orcids=preset["max_orcids"],
        twenty_limit=preset["twenty_limit"],
        fetch_pdfs=DEFAULT_FETCH_PDFS,
    )


_default_plan = build_e2e_plan(DEFAULT_TOPIC, DEFAULT_EFFORT)
COLLECTION = _default_plan.collection
QUERY = _default_plan.query
YEAR_FROM = _default_plan.year_from
YEAR_TO = _default_plan.year_to
MAX_CANDIDATES = _default_plan.max_candidates
MAX_ORCIDS = _default_plan.max_orcids
TWENTY_LIMIT = _default_plan.twenty_limit


def resolve_e2e_state_dir(
    root: Path, run_id: str, state_dir: Path | None = None
) -> Path:
    if state_dir is not None:
        return state_dir
    for sub in ("e2e", "e2e-nba"):
        candidate = root / "state" / sub / run_id
        if candidate.is_dir():
            return candidate
    return root / "state" / "e2e" / run_id

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
        plan: E2EPlan | None = None,
        state_dir: Path | None = None,
        run_id: str | None = None,
        from_phase: str = "doctor",
        only_phase: str | None = None,
        dry_run_search: bool = False,
        paperful: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.root = _repo_root()
        self.run_id = run_id or _utc_stamp()
        self.plan = plan or build_e2e_plan(DEFAULT_TOPIC, DEFAULT_EFFORT)
        self.dest = resolve_e2e_state_dir(self.root, self.run_id, state_dir)
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
            "topic": self.plan.topic,
            "effort": self.plan.effort,
            "collection": self.plan.collection,
            "query": self.plan.query,
            "year_from": self.plan.year_from,
            "year_to": self.plan.year_to,
            "max_candidates": self.plan.max_candidates,
            "depth": self.plan.depth,
            "per_hop_limit": self.plan.per_hop_limit,
            "pack_slug": self.plan.pack_slug,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.snowball_run_id: str | None = None
        self.orcid_run_id: str | None = None

    def _default_paperful(
        self, args: list[str], *, phase: str = "paperful", **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["uv", "run", "paperful", *args]
        cwd = str(self.root)
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            **{k: v for k, v in kwargs.items() if k not in ("phase",)},
        )
        out_chunks: list[str] = []
        err_chunks: list[str] = []
        out_path = self.dest / f"{phase}.stdout.txt"
        err_path = self.dest / f"{phase}.stderr.txt"
        out_path.write_text("", encoding="utf-8")
        err_path.write_text("", encoding="utf-8")

        def _pump(
            stream: Any, chunks: list[str], mirror: Any, log_path: Path
        ) -> None:
            if stream is None:
                return
            with log_path.open("a", encoding="utf-8") as log:
                for line in stream:
                    chunks.append(line)
                    mirror.write(line)
                    mirror.flush()
                    log.write(line)
                    log.flush()

        threads = [
            threading.Thread(
                target=_pump,
                args=(proc.stdout, out_chunks, sys.stdout, out_path),
                daemon=True,
            ),
            threading.Thread(
                target=_pump,
                args=(proc.stderr, err_chunks, sys.stderr, err_path),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        proc.wait()
        for thread in threads:
            thread.join()
        stdout = "".join(out_chunks)
        stderr = "".join(err_chunks)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)

    def _log(self, msg: str) -> None:
        line = f"[e2e {self.run_id}] {msg}"
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
        proc = self._paperful(full, phase=phase)
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

    def _snowball_search_argv(
        self, *, gate: str, fetch_pdfs: str, with_collection: bool = True
    ) -> list[str]:
        argv = [
            "snowball",
            "search",
            self.plan.query,
            "--year-from",
            str(self.plan.year_from),
            "--year-to",
            str(self.plan.year_to),
            "--max-candidates",
            str(self.plan.max_candidates),
            "--depth",
            str(self.plan.depth),
            "--per-hop-limit",
            str(self.plan.per_hop_limit),
            "--gate",
            gate,
            "--fetch-pdfs",
            fetch_pdfs,
        ]
        if with_collection:
            argv.extend(["-C", self.plan.collection])
        return argv

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
                self._snowball_search_argv(
                    gate="dry-run", fetch_pdfs="off", with_collection=False
                ),
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
            self._snowball_search_argv(gate="auto", fetch_pdfs=self.plan.fetch_pdfs),
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
                    result.reason = (
                        f"no OpenAlex hits for {self.plan.query!r} "
                        f"{self.plan.year_from}–{self.plan.year_to}"
                    )
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
        orcids = extract_orcids_from_candidates(
            queue, limit=self.plan.max_orcids
        )
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
            str(self.plan.year_from),
            "--year-to",
            str(self.plan.year_to),
            "--max-candidates",
            str(self.plan.max_candidates),
            "--depth",
            str(self.plan.depth),
            "--per-hop-limit",
            str(self.plan.per_hop_limit),
            "--gate",
            "auto",
            "--fetch-pdfs",
            self.plan.fetch_pdfs,
            "-C",
            self.plan.collection,
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
                self.plan.collection,
                "--year-from",
                str(self.plan.year_from),
                "--year-to",
                str(self.plan.year_to),
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
                self.plan.collection,
                "--year-from",
                str(self.plan.year_from),
                "--year-to",
                str(self.plan.year_to),
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
            ["authors", "-C", self.plan.collection, "--apply"],
            phase="authors_apply",
            required=False,
            want_json=True,
        )
        slug = self.plan.pack_slug
        promote, _ = self._run_cmd(
            ["snowball", "packs", "promote", slug],
            phase="authors_promote",
            required=False,
        )
        dry, _ = self._run_cmd(
            [
                "run",
                "-C",
                self.plan.collection,
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
            ["twenty", "lookup", "-C", self.plan.collection],
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
            ["twenty", "lookup", "-C", self.plan.collection, "--apply"],
            phase="twenty_lookup",
            required=False,
            want_json=False,
        )
        sync, _ = self._run_cmd(
            [
                "twenty",
                "sync",
                "-C",
                self.plan.collection,
                "--apply",
                "--limit",
                str(self.plan.twenty_limit),
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
        args = ["reachout", "-C", self.plan.collection, "--to", str(csv_path)]
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
                    self.plan.collection,
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
            f"# E2E stack report `{self.run_id}`",
            "",
            f"- Topic: `{self.plan.topic}` (effort `{self.plan.effort}`)",
            f"- Collection: `{self.plan.collection}`",
            f"- Query: `{self.plan.query}` ({self.plan.year_from}–{self.plan.year_to})",
            f"- Snowball cap: {self.plan.max_candidates} candidates, depth {self.plan.depth}",
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
    parser = argparse.ArgumentParser(
        description="Paperful all-in E2E stack (topic + effort; see docs/e2e-stack.md)"
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help=f"OpenAlex keyword seed (default: {DEFAULT_TOPIC}).",
    )
    parser.add_argument(
        "--effort",
        default=DEFAULT_EFFORT,
        choices=EFFORT_CHOICES,
        help="low (~25 rows), med (~250), high (2-hop, cap ~3000).",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        default=None,
        help="Year filter (default: previous calendar year).",
    )
    parser.add_argument(
        "--year-to",
        type=int,
        default=None,
        help="Year filter (default: current calendar year).",
    )
    parser.add_argument(
        "-C",
        "--collection",
        default=None,
        help="Zotero collection override (default: e2e/<topic>).",
    )
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
        "--dry-run-search",
        action="store_true",
        help="Run a snowball dry-run (no Zotero writes, no PDFs) before gate auto.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Reuse an existing state/e2e/<run-id> (or legacy state/e2e-nba/) directory.",
    )
    args = parser.parse_args(argv)
    if os.environ.get("PAPERFUL_E2E") != "1" and not args.force:
        print(
            "Refusing live E2E: set PAPERFUL_E2E=1 or pass --force. "
            "See docs/e2e-stack.md.",
            file=sys.stderr,
        )
        return 2
    try:
        plan = build_e2e_plan(
            args.topic,
            args.effort,
            year_from=args.year_from,
            year_to=args.year_to,
            collection=args.collection,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    runner = E2ERunner(
        plan=plan,
        run_id=args.run_id,
        from_phase=args.from_phase,
        only_phase=args.phase,
        dry_run_search=args.dry_run_search,
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
