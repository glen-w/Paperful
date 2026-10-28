"""Optional Open XML SDK / ODF audit for rewrite tracked Office files.

Not a core dependency. ``openxml-audit`` is a Python port of Microsoft's
Open XML SDK validator, plus an ODF adapter. Word-authored drafts can
already fail it (for example ``styles.xml`` vs ``stylesWithEffects``).
Paperful therefore diffs output errors against the source and only reports
**introduced** issues.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .rewrite_docx import docx_structural_issues
from .rewrite_office import odt_structural_issues, pptx_structural_issues

POLICIES = ("warn", "fail")
OOXML_SUFFIXES = frozenset(
    {
        ".docx",
        ".docm",
        ".dotx",
        ".dotm",
        ".pptx",
        ".pptm",
        ".potx",
        ".xlsx",
        ".xlsm",
        ".xltx",
        ".xltm",
    }
)
ODF_SUFFIXES = frozenset({".odt", ".ods", ".odp"})


class RewriteAuditError(RuntimeError):
    """Tracked Office output introduced schema issues under ``fail`` policy."""


def parse_openxml_audit_policy(raw: Any) -> str:
    value = str(raw or "warn").strip().lower() or "warn"
    if value not in POLICIES:
        raise ValueError("[rewrite].openxml_audit_policy must be warn or fail")
    return value


def extra_available() -> bool:
    try:
        import openxml_audit  # noqa: F401
    except ImportError:
        return False
    return True


def office_structural_issues(path: Path) -> list[str]:
    """Stdlib zip+XML checks for formats rewrite writes. Empty if unknown."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_structural_issues(path)
    if suffix == ".pptx":
        return pptx_structural_issues(path)
    if suffix == ".odt":
        return odt_structural_issues(path)
    return []


def _error_text(err: Any) -> str:
    desc = getattr(err, "description", None) or getattr(err, "message", None)
    if desc:
        return str(desc).strip()
    return str(err).strip()


def sdk_errors(path: Path) -> list[str]:
    """Validate OOXML or ODF with openxml-audit. Empty list if the extra is missing."""
    if not extra_available() or not path.is_file():
        return []
    suffix = path.suffix.lower()
    if suffix in ODF_SUFFIXES:
        from openxml_audit import FileFormat, OdfValidator

        validator = OdfValidator(file_format=FileFormat.ODF_1_3, max_errors=50)
        result = validator.validate(str(path))
    elif suffix in OOXML_SUFFIXES:
        from openxml_audit import FileFormat, OpenXmlValidator

        validator = OpenXmlValidator(file_format=FileFormat.OFFICE_2019, max_errors=50)
        result = validator.validate(str(path))
    else:
        return []
    return [_error_text(err) for err in (result.errors or []) if _error_text(err)]


def audit_office_file(
    cfg: Any,
    dest: Path,
    *,
    source: Path | None = None,
) -> dict[str, Any]:
    """Stdlib structure plus optional SDK/ODF audit. Never deletes ``dest``."""
    structural = office_structural_issues(dest)
    policy = parse_openxml_audit_policy(
        getattr(cfg, "rewrite_openxml_audit_policy", "warn")
    )
    enabled = bool(getattr(cfg, "rewrite_openxml_audit", False))
    fmt = dest.suffix.lower().lstrip(".")
    row: dict[str, Any] = {
        "enabled": enabled,
        "extra": extra_available(),
        "policy": policy,
        "format": fmt,
        "skipped": "",
        "structural": structural,
        "source_errors": [],
        "output_errors": [],
        "introduced": [],
        "fail": False,
    }
    if not enabled:
        row["fail"] = policy == "fail" and bool(structural)
        return row
    if not extra_available():
        row["skipped"] = "unavailable"
        row["fail"] = policy == "fail" and bool(structural)
        return row
    output_errors = sdk_errors(dest)
    source_ok = (
        source is not None
        and source.is_file()
        and source.suffix.lower() == dest.suffix.lower()
    )
    source_errors = sdk_errors(source) if source_ok else []
    src_set = set(source_errors)
    introduced = [err for err in output_errors if err not in src_set]
    row["source_errors"] = source_errors
    row["output_errors"] = output_errors
    row["introduced"] = introduced
    row["fail"] = policy == "fail" and bool(introduced or structural)
    return row


def audit_tracked_docx(
    cfg: Any,
    dest: Path,
    *,
    source: Path | None = None,
) -> dict[str, Any]:
    """Back-compat wrapper for Word tracked output."""
    return audit_office_file(cfg, dest, source=source)
