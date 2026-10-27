"""Optional PaperGuard forensics extra for critique.

Not a core dependency. Requires ``paperguard`` on PATH. Missing binary or
input returns a skip so the pack can record ``paperguard_unavailable`` /
``paperguard_no_input`` / ``paperguard_failed``. Default detectors only —
never passes PaperGuard ML / LLM / paper-mill opt-in flags.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import Config
from .critique import Finding, make_finding

MAX_FORENSICS_FINDINGS = 100
SIBLING_TABLE_SUFFIXES = frozenset({".csv", ".xlsx", ".xls"})
_CHECK_SAFE = re.compile(r"[^a-z0-9]+")
_FORBIDDEN_FLAGS = frozenset(
    {
        "--ml-check",
        "--llm-review",
        "--perplexity-check",
        "--detectgpt-check",
        "--check-paper-mill",
    }
)
_SKIP_DETAIL = {
    "unavailable": (
        "Optional PaperGuard forensics pass needs the paperguard binary on PATH. "
        "Anomalies were not scanned."
    ),
    "no_input": (
        "Optional PaperGuard forensics pass had no scannable file "
        "(PDF or sibling csv/xlsx/xls). Anomalies were not scanned."
    ),
}
_PG_SEV_TO_PAPERFUL = {
    1: "info",
    2: "warn",
    3: "major",
    4: "major",
    "note": "info",
    "concern": "warn",
    "suspicious": "major",
    "critical": "major",
}
_PG_SEV_LABEL = {
    0: "PASS",
    1: "NOTE",
    2: "CONCERN",
    3: "SUSPICIOUS",
    4: "CRITICAL",
}


def paperguard_code(detector_id: str) -> str:
    raw = (detector_id or "hit").strip().lower()
    safe = _CHECK_SAFE.sub("_", raw).strip("_") or "hit"
    return f"paperguard_{safe[:80]}"


def resolve_forensics_files(src: Path | None, *, item_mode: bool) -> list[Path]:
    """Scan targets: the file itself, plus sibling tables next to an item PDF."""
    if src is None or not src.is_file():
        return []
    out = [src]
    if not item_mode:
        return out
    parent = src.parent
    if not parent.is_dir():
        return out
    seen = {src.resolve()}
    extras: list[Path] = []
    for child in parent.iterdir():
        if not child.is_file():
            continue
        if child.suffix.lower() not in SIBLING_TABLE_SUFFIXES:
            continue
        key = child.resolve()
        if key in seen:
            continue
        seen.add(key)
        extras.append(child)
    extras.sort(key=lambda p: p.name.lower())
    return out + extras


def run_forensics(
    cfg: Config,
    *,
    files: list[Path],
    doi: str | None = None,
    offline: bool = False,
) -> tuple[list[Finding], dict[str, Any], str | None]:
    """Scan files with PaperGuard. Returns findings, pack meta, raw JSON (or skip)."""
    exe = shutil.which("paperguard")
    if not exe:
        findings, meta = _skip("unavailable")
        return findings, meta, None
    paths = [p for p in files if p.is_file()]
    if not paths:
        findings, meta = _skip("no_input")
        return findings, meta, None
    timeout_s = float(cfg.critique_forensics_timeout_s or 300.0)
    doi_flag = (doi or "").strip() if not offline else ""
    try:
        with tempfile.TemporaryDirectory(prefix="paperful-paperguard-") as tmp:
            out = Path(tmp) / "report.json"
            cmd = _scan_cmd(exe, paths, out, doi=doi_flag or None)
            env = os.environ.copy()
            env["PAPERGUARD_LANG"] = "en"
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                text=True,
                env=env,
            )
            raw_text, parse_err = _read_report(out, proc)
    except subprocess.TimeoutExpired:
        findings, meta = _skip(
            "failed", extra=f"paperguard timed out after {int(timeout_s)}s"
        )
        return findings, meta, None
    except OSError as exc:
        findings, meta = _skip("failed", extra=str(exc))
        return findings, meta, None
    if parse_err:
        findings, meta = _skip("failed", extra=parse_err)
        return findings, meta, None
    assert raw_text is not None
    try:
        report = json.loads(raw_text)
    except ValueError:
        findings, meta = _skip("failed", extra="paperguard JSON was not parseable")
        return findings, meta, None
    if not isinstance(report, dict):
        findings, meta = _skip("failed", extra="paperguard JSON was not an object")
        return findings, meta, None
    hits = [
        h
        for h in _findings_from_report(report)
        if _paperful_severity(h.get("severity")) is not None
    ]
    mapped = [
        f
        for hit in hits[:MAX_FORENSICS_FINDINGS]
        for f in (_finding_from_hit(hit),)
        if f is not None
    ]
    if len(hits) > MAX_FORENSICS_FINDINGS:
        mapped.append(
            make_finding(
                code="paperguard_truncated",
                severity="info",
                lane="suggested",
                loc="document",
                detail=(
                    f"PaperGuard reported {len(hits)} findings; "
                    f"showing the first {MAX_FORENSICS_FINDINGS}."
                ),
                source="paperguard",
            )
        )
    meta = {
        "binary": exe,
        "files": [str(p) for p in paths],
        "finding_count": len(hits),
        "overall_severity": _severity_label(report.get("overall_severity")),
        "report_path": "",
    }
    return mapped, meta, raw_text


def persist_forensics_report(folder: Path, raw_json: str) -> Path:
    dest = folder / "paperguard.json"
    dest.write_text(raw_json, encoding="utf-8")
    return dest


def _scan_cmd(exe: str, paths: list[Path], out: Path, *, doi: str | None) -> list[str]:
    cmd = [exe, "scan"]
    for path in paths:
        cmd.extend(["-f", str(path)])
    cmd.extend(["--output-json", str(out), "--lang", "en"])
    if doi:
        cmd.extend(["--doi", doi])
    if _FORBIDDEN_FLAGS.intersection(cmd):
        raise RuntimeError("forensics wrapper must not pass PaperGuard opt-in flags")
    return cmd


def _read_report(
    out: Path, proc: subprocess.CompletedProcess[str]
) -> tuple[str | None, str]:
    if out.is_file():
        try:
            text = out.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return None, str(exc)
        if text:
            return text, ""
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    if proc.returncode not in (0, 1):
        return None, stderr or stdout or f"paperguard exited {proc.returncode}"
    if stdout.startswith("{") or stdout.startswith("["):
        return stdout, ""
    return None, stderr or "paperguard wrote no JSON report"


def _findings_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    raw = report.get("all_findings")
    if isinstance(raw, list):
        hits = [h for h in raw if isinstance(h, dict)]
        if hits:
            return hits
    hits = []
    for block in report.get("detector_results") or []:
        if not isinstance(block, dict):
            continue
        for hit in block.get("findings") or []:
            if isinstance(hit, dict):
                hits.append(hit)
    return hits


def _finding_from_hit(hit: dict[str, Any]) -> Finding | None:
    paperful_sev = _paperful_severity(hit.get("severity"))
    if paperful_sev is None:
        return None
    detector_id = str(hit.get("detector_id") or "hit")
    name = str(hit.get("detector_name") or "").strip()
    summary = str(hit.get("summary") or "").strip()
    detail_src = str(hit.get("detail") or "").strip()
    innocents = _innocent_explanations(hit.get("innocent_explanations"))
    parts = [p for p in (summary, detail_src) if p]
    if innocents:
        parts.append("Innocent explanations: " + "; ".join(innocents[:4]))
    evidence = hit.get("evidence") if isinstance(hit.get("evidence"), dict) else {}
    quote = ""
    loc = "document"
    column = evidence.get("column") if evidence else None
    if column:
        loc = str(column)
        quote = str(column)
    extra: dict[str, Any] = {
        "detector_id": detector_id,
        "detector_name": name,
        "paperguard_severity": _severity_label(hit.get("severity")),
    }
    adj = hit.get("p_value_adjusted")
    if isinstance(adj, (int, float)):
        extra["p_value_adjusted"] = float(adj)
    if innocents:
        extra["innocent_explanations"] = innocents[:8]
    return make_finding(
        code=paperguard_code(detector_id),
        severity=paperful_sev,
        lane="suggested",
        loc=loc,
        quote=quote,
        detail=" ".join(parts) or name or detector_id,
        source="paperguard",
        extra=extra,
    )


def _paperful_severity(raw: Any) -> str | None:
    key: Any = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.isdigit():
            key = int(stripped)
        else:
            key = stripped.lower()
    if key in (0, "pass", "0"):
        return None
    mapped = _PG_SEV_TO_PAPERFUL.get(key)
    return mapped


def _severity_label(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        if raw.strip().isdigit():
            return _PG_SEV_LABEL.get(int(raw.strip()), raw.strip().upper())
        return raw.strip().upper()
    if isinstance(raw, int):
        return _PG_SEV_LABEL.get(raw, str(raw))
    return ""


def _innocent_explanations(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if text:
            out.append(text[:200])
    return out


def _skip(reason: str, *, extra: str = "") -> tuple[list[Finding], dict[str, Any]]:
    if reason == "failed":
        suffix = f" ({extra})" if extra else ""
        detail = f"Optional PaperGuard forensics pass failed{suffix}. Anomalies were not scanned."
    else:
        detail = _SKIP_DETAIL.get(
            reason, "Optional PaperGuard forensics pass did not run."
        )
        if extra:
            detail = f"{detail} {extra}"
    return (
        [
            make_finding(
                code=f"paperguard_{reason}",
                severity="info",
                lane="suggested",
                loc="document",
                detail=detail,
                source="paperguard",
            )
        ],
        {"skipped": reason},
    )
