"""Optional Vale house-style pass for critique.

Not a core dependency. Requires ``vale`` on PATH and a ``.vale.ini``. Missing
binary or config returns a skip so the pack can record ``vale_unavailable`` /
``vale_no_config``. Never runs ``vale sync``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import Config
from .critique import Finding, make_finding
from .critique_direct_quotes import line_column_span_in_direct_quote, snippet_in_direct_quote
from .critique_extract import ExtractedDoc, loc_of_span

MAX_VALE_FINDINGS = 100
_CHECK_SAFE = re.compile(r"[^a-z0-9]+")
_SKIP_DETAIL = {
    "unavailable": (
        "Optional Vale house-style pass needs the vale binary on PATH. "
        "Alerts were not run."
    ),
    "no_config": (
        "Optional Vale pass needs [critique].vale_config "
        "(or .vale.ini next to the paperful config). Alerts were not run."
    ),
}


def resolve_vale_ini(cfg: Config) -> Path | None:
    """Explicit ``vale_config``, else ``.vale.ini`` beside the paperful config."""
    path = cfg.critique_vale_config
    if path is not None:
        candidate = Path(path)
        return candidate if candidate.is_file() else None
    source = cfg.config_path
    if source is None:
        return None
    sibling = source.parent / ".vale.ini"
    return sibling if sibling.is_file() else None


def vale_code(check: str) -> str:
    raw = (check or "alert").strip().lower().replace(".", "_")
    safe = _CHECK_SAFE.sub("_", raw).strip("_") or "alert"
    return f"vale_{safe[:80]}"


def run_vale(cfg: Config, doc: ExtractedDoc) -> tuple[list[Finding], dict[str, Any]]:
    """Lint extracted text. Returns findings plus pack meta (or a skip)."""
    exe = shutil.which("vale")
    if not exe:
        return _skip("unavailable")
    ini = resolve_vale_ini(cfg)
    if ini is None:
        return _skip("no_config")
    text = doc.text or ""
    level = cfg.critique_vale_min_alert_level or "suggestion"
    timeout_s = float(cfg.critique_vale_timeout_s or 60.0)
    try:
        with tempfile.TemporaryDirectory(prefix="paperful-vale-") as tmp:
            src = Path(tmp) / "manuscript.txt"
            src.write_text(text, encoding="utf-8")
            proc = subprocess.run(
                [
                    exe,
                    "--output=JSON",
                    "--no-exit",
                    "--no-global",
                    "--ignore-syntax",
                    f"--config={ini}",
                    f"--minAlertLevel={level}",
                    str(src),
                ],
                capture_output=True,
                timeout=timeout_s,
                check=False,
                text=True,
                cwd=str(ini.parent),
            )
    except subprocess.TimeoutExpired:
        return _skip("failed", extra=f"vale timed out after {int(timeout_s)}s")
    except OSError as exc:
        return _skip("failed", extra=str(exc))
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode not in (0, 1) and not stdout:
        return _skip("failed", extra=stderr or f"vale exited {proc.returncode}")
    if not stdout:
        return [], _ok_meta(exe, ini, 0)
    try:
        raw = json.loads(stdout)
    except ValueError:
        return _skip("failed", extra=stderr or "vale JSON was not parseable")
    alerts = _alerts_from_json(raw)
    findings = [
        f
        for alert in alerts[:MAX_VALE_FINDINGS]
        for f in (_finding_from_alert(doc, alert),)
        if f is not None
    ]
    if len(alerts) > MAX_VALE_FINDINGS:
        findings.append(
            make_finding(
                code="vale_truncated",
                severity="info",
                lane="checked",
                loc="document",
                detail=(
                    f"Vale reported {len(alerts)} alerts; "
                    f"showing the first {MAX_VALE_FINDINGS}."
                ),
                source="vale",
            )
        )
    return findings, _ok_meta(exe, ini, len(alerts))


def _ok_meta(exe: str, ini: Path, alert_count: int) -> dict[str, Any]:
    return {"binary": exe, "config": str(ini), "alert_count": alert_count}


def _skip(reason: str, *, extra: str = "") -> tuple[list[Finding], dict[str, Any]]:
    if reason == "failed":
        suffix = f" ({extra})" if extra else ""
        detail = f"Optional Vale pass failed{suffix}. Alerts were not run."
    else:
        detail = _SKIP_DETAIL.get(reason, "Optional Vale pass did not run.")
        if extra:
            detail = f"{detail} {extra}"
    return (
        [
            make_finding(
                code=f"vale_{reason}",
                severity="info",
                lane="checked",
                loc="document",
                detail=detail,
                source="vale",
            )
        ],
        {"skipped": reason},
    )


def _alerts_from_json(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        out: list[dict[str, Any]] = []
        for alerts in raw.values():
            if isinstance(alerts, list):
                out.extend(a for a in alerts if isinstance(a, dict))
        return out
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, dict)]
    return []


def _finding_from_alert(doc: ExtractedDoc, alert: dict[str, Any]) -> Finding | None:
    check = str(alert.get("Check") or "alert")
    message = str(alert.get("Message") or "").strip()
    match = str(alert.get("Match") or "").strip()
    line = _int(alert.get("Line"))
    text = doc.text or ""
    span = alert.get("Span")
    if line and isinstance(span, (list, tuple)) and len(span) >= 2:
        try:
            if line_column_span_in_direct_quote(
                text, line, int(span[0]), int(span[1])
            ):
                return None
        except (TypeError, ValueError):
            pass
    if match and snippet_in_direct_quote(text, match):
        return None
    quote = match or _span_quote(text, line, span)
    if quote and not match and snippet_in_direct_quote(text, quote):
        return None
    loc = loc_of_span(doc, quote) if quote else ""
    if not loc and line:
        loc = f"line {line}"
    if not loc:
        loc = "document"
    return make_finding(
        code=vale_code(check),
        severity=_severity(str(alert.get("Severity") or "")),
        lane="checked",
        loc=loc,
        quote=quote,
        detail=message or check,
        source="vale",
        extra={"vale_check": check} if check else None,
    )


def _severity(level: str) -> str:
    if level.strip().lower() == "suggestion":
        return "info"
    return "warn"


def _span_quote(text: str, line: int | None, span: Any) -> str:
    if line is None or line < 1:
        return ""
    lines = text.splitlines()
    if line > len(lines):
        return ""
    row = lines[line - 1]
    if not isinstance(span, (list, tuple)) or len(span) < 2:
        return row.strip()[:200]
    try:
        start = max(int(span[0]) - 1, 0)
        end = max(int(span[1]), start)
    except (TypeError, ValueError):
        return row.strip()[:200]
    return row[start:end]


def _int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
