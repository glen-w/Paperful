"""Add an OCRmyPDF text layer to image PDFs on disk.

Readers (``text_from_pdf``, summarize, PDF-DOI) follow the ``out/`` path.
This module rewrites that file. It does not edit the manager's storage.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .library import LibraryBackend
from .lint import resolve_pdf_path
from .pdfid import text_from_pdf
from .snapshot import item_dirs
from .store import STATUS_ATTACHED, STATUS_OK, Manifest, Record, item_filename
from .zot import Item

# First pages with fewer alphanumeric characters than this are a scan
# (blank, or only a page number / watermark).
_MIN_ALNUM = 40
_DEFAULT_TIMEOUT_S = 600.0


class OcrUnavailable(RuntimeError):
    """``--apply`` was asked and ``ocrmypdf`` is not on PATH."""


@dataclass
class OcrRow:
    key: str
    title: str
    path: str
    status: str  # skip | would | ocr | failed | missing
    reason: str


@dataclass
class OcrBatch:
    rows: list[OcrRow] = field(default_factory=list)
    ocr: int = 0
    skipped: int = 0
    failed: int = 0
    would: int = 0


def ocrmypdf_available() -> bool:
    return bool(shutil.which("ocrmypdf"))


def tesseract_langs(raw: str) -> str:
    """Normalise ``eng``, ``eng+fra``, or ``eng fra`` to a ``-l`` value."""
    parts: list[str] = []
    for bit in raw.replace(",", " ").replace("+", " ").split():
        if bit and bit not in parts:
            parts.append(bit)
    return "+".join(parts) or "eng"


def needs_text_layer(text: str) -> str | None:
    """``no text`` or ``thin text`` when OCR should run. None when the layer is enough."""
    alnum = sum(1 for ch in text if ch.isalnum())
    if alnum == 0:
        return "no text"
    if alnum < _MIN_ALNUM:
        return "thin text"
    return None


def _under_cache(cfg: Config, path: Path) -> bool:
    try:
        path.resolve().relative_to(cfg.pdf_cache_dir.resolve())
    except ValueError:
        return False
    return True


def _remember(manifest: Manifest, item: Item, path: Path) -> None:
    rec = manifest.get(item.key)
    if rec is None:
        rec = Record(
            itemKey=item.key,
            status=STATUS_ATTACHED if item.has_pdf else STATUS_OK,
            title=item.title,
            doi=item.doi,
            path=str(path),
            source="ocr",
        )
    else:
        rec.path = str(path)
    manifest.write(rec)
    item.pdf_path = str(path)


def _materialize(cfg: Config, item: Item, probe: Path) -> Path:
    primary = item_dirs(cfg.out_dir, item)[0]
    primary.mkdir(parents=True, exist_ok=True)
    dest = primary / item_filename(item)
    if probe.resolve() != dest.resolve():
        shutil.copyfile(probe, dest)
    return dest


def _probe_pdf(
    cfg: Config,
    item: Item,
    manifest: Manifest | None,
    backend: LibraryBackend | None,
) -> tuple[Path | None, Path | None]:
    """Return ``(durable, probe)``. A cache export is a probe, not the file we rewrite."""
    found = resolve_pdf_path(cfg, item, manifest)
    if found is not None and found.is_file() and not _under_cache(cfg, found):
        return found, found
    probe = found if found is not None and found.is_file() else None
    if probe is None and item.has_pdf and backend is not None:
        dest = cfg.pdf_cache_dir / f"{item.key}.pdf"
        probe = backend.export_pdf(item, dest)
    return None, probe


def _run_ocrmypdf(src: Path, dest: Path, *, langs: str, thin: bool, timeout_s: float) -> tuple[int, str]:
    exe = shutil.which("ocrmypdf")
    if not exe:
        return 127, "ocrmypdf is not on PATH"
    # Thin layers (a page number, a watermark) still count as text to OCRmyPDF,
    # so --skip-text would leave the page as an image. --redo-ocr replaces that
    # stub. Born-digital files never reach here: needs_text_layer skips them.
    mode = "--redo-ocr" if thin else "--skip-text"
    cmd = [exe, mode, "-l", langs, "--output-type", "pdf", "-q", str(src), str(dest)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"ocrmypdf timed out after {int(timeout_s)}s"
    except OSError as exc:
        return 127, str(exc)
    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    if not err:
        err = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    return proc.returncode, err.splitlines()[-1] if err else ""


def _apply_one(
    cfg: Config,
    item: Item,
    manifest: Manifest,
    backend: LibraryBackend | None,
    durable: Path | None,
    probe: Path | None,
    *,
    why: str,
    attach: bool,
) -> OcrRow:
    if durable is None:
        if probe is None:
            return OcrRow(item.key, item.title, "", "missing", "no PDF on disk")
        durable = _materialize(cfg, item, probe)
        _remember(manifest, item, durable)
    elif manifest is not None:
        _remember(manifest, item, durable)
    langs = tesseract_langs(cfg.ocr_languages)
    timeout_s = cfg.ocr_timeout_s or _DEFAULT_TIMEOUT_S
    tmp = durable.with_name(durable.stem + ".ocr-tmp.pdf")
    try:
        code, err = _run_ocrmypdf(
            durable,
            tmp,
            langs=langs,
            thin=why == "thin text",
            timeout_s=timeout_s,
        )
        if code != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            return OcrRow(item.key, item.title, str(durable), "failed", err or f"ocrmypdf exited {code}")
        os.replace(tmp, durable)
    finally:
        tmp.unlink(missing_ok=True)
    reason = why
    if attach and backend is not None:
        result = backend.attach(item.key, durable, title="PDF (OCR)", note="paperful ocr")
        if result.ok:
            reason = f"{why}; attached"
        else:
            reason = f"{why}; attach failed: {result.reason}"
    return OcrRow(item.key, item.title, str(durable), "ocr", reason)


def ocr_items(
    cfg: Config,
    items: list[Item],
    manifest: Manifest,
    backend: LibraryBackend | None,
    *,
    apply: bool,
    attach: bool = False,
) -> OcrBatch:
    """Classify each PDF. With ``apply``, rewrite image files under ``out/``."""
    if apply and not ocrmypdf_available():
        raise OcrUnavailable(
            "ocrmypdf is not on PATH. "
            "brew install ocrmypdf tesseract-lang, "
            "or apt install ocrmypdf tesseract-ocr-eng."
        )
    batch = OcrBatch()
    for item in items:
        durable, probe = _probe_pdf(cfg, item, manifest, backend)
        sample = probe or durable
        if sample is None:
            row = OcrRow(item.key, item.title, "", "missing", "no PDF on disk")
            batch.rows.append(row)
            batch.failed += 1
            continue
        why = needs_text_layer(text_from_pdf(sample))
        shown = str(durable or sample)
        if why is None:
            row = OcrRow(item.key, item.title, shown, "skip", "has text")
            batch.rows.append(row)
            batch.skipped += 1
            continue
        if not apply:
            row = OcrRow(item.key, item.title, shown, "would", why)
            batch.rows.append(row)
            batch.would += 1
            continue
        row = _apply_one(
            cfg,
            item,
            manifest,
            backend,
            durable,
            probe,
            why=why,
            attach=attach,
        )
        batch.rows.append(row)
        if row.status == "ocr":
            batch.ocr += 1
        else:
            batch.failed += 1
    return batch
