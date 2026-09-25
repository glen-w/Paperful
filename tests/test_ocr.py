"""Text-layer OCR: classify scans, rewrite the out/ PDF, leave the cache alone."""

from __future__ import annotations

from pathlib import Path

from paperful.attach import AttachResult
from paperful.config import Config, _from_dict
from paperful.ocr import (
    OcrUnavailable,
    needs_text_layer,
    ocr_items,
    tesseract_langs,
)
from paperful.store import Manifest
from paperful.zot import Item


def _blank_pdf(path: Path) -> Path:
    from pypdf import PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(path)
    return path


def _item(path: Path | None, *, key: str = "FAO2019A") -> Item:
    return Item(
        key=key,
        item_type="report",
        title="State of world fisheries",
        doi=None,
        arxiv_id=None,
        url=None,
        year=2019,
        first_author="FAO",
        collection_paths=["Grey"],
        has_pdf=True,
        pdf_path=str(path) if path else None,
    )


def _cfg(tmp_path: Path) -> Config:
    cfg = Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")
    cfg.out_dir.mkdir(exist_ok=True)
    cfg.state_dir.mkdir(exist_ok=True)
    return cfg


def test_needs_text_layer_thresholds():
    assert needs_text_layer("") == "no text"
    assert needs_text_layer("p. 1") == "thin text"
    assert needs_text_layer("Marine governance " * 10) is None


def test_tesseract_langs_normalises():
    assert tesseract_langs("eng") == "eng"
    assert tesseract_langs("eng+fra") == "eng+fra"
    assert tesseract_langs("eng fra") == "eng+fra"
    assert tesseract_langs("") == "eng"


def test_ocr_languages_from_config(tmp_path):
    cfg = _from_dict(
        {"ocr": {"languages": "eng+spa", "timeout_s": 30}},
        tmp_path / "config.toml",
    )
    assert cfg.ocr_languages == "eng+spa"
    assert cfg.ocr_timeout_s == 30


def test_text_pdf_is_skipped(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "born.pdf")
    monkeypatch.setattr(
        "paperful.ocr.text_from_pdf", lambda *a, **k: "A full page of report text." * 5
    )
    batch = ocr_items(
        _cfg(tmp_path),
        [_item(pdf)],
        Manifest(tmp_path / "state" / "manifest.jsonl"),
        None,
        apply=False,
    )
    assert batch.skipped == 1
    assert batch.rows[0].status == "skip"
    assert batch.would == 0


def test_apply_without_ocrmypdf_raises(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.setattr("paperful.ocr.shutil.which", lambda name: None)
    monkeypatch.setattr("paperful.ocr.text_from_pdf", lambda *a, **k: "")
    try:
        ocr_items(
            _cfg(tmp_path),
            [_item(pdf)],
            Manifest(tmp_path / "state" / "manifest.jsonl"),
            None,
            apply=True,
        )
    except OcrUnavailable as exc:
        assert "ocrmypdf" in str(exc)
    else:
        raise AssertionError("expected OcrUnavailable")


def test_dry_run_lists_image_without_rewriting(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "scan.pdf")
    before = pdf.read_bytes()
    monkeypatch.setattr("paperful.ocr.text_from_pdf", lambda *a, **k: "  ")
    batch = ocr_items(
        _cfg(tmp_path),
        [_item(pdf)],
        Manifest(tmp_path / "state" / "manifest.jsonl"),
        None,
        apply=False,
    )
    assert batch.would == 1
    assert batch.rows[0].reason == "no text"
    assert pdf.read_bytes() == before


def test_apply_replaces_out_pdf(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.setattr("paperful.ocr.text_from_pdf", lambda *a, **k: "")
    monkeypatch.setattr("paperful.ocr.shutil.which", lambda name: "/usr/bin/ocrmypdf")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"%PDF-1.4 text-layer")

        class Proc:
            returncode = 0
            stderr = b""
            stdout = b""

        return Proc()

    monkeypatch.setattr("paperful.ocr.subprocess.run", fake_run)
    manifest = Manifest(tmp_path / "state" / "manifest.jsonl")
    batch = ocr_items(_cfg(tmp_path), [_item(pdf)], manifest, None, apply=True)
    assert batch.ocr == 1
    assert batch.failed == 0
    assert pdf.read_bytes() == b"%PDF-1.4 text-layer"
    assert manifest.get("FAO2019A").path == str(pdf)


def test_thin_text_uses_redo_ocr(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "thin.pdf")
    monkeypatch.setattr("paperful.ocr.text_from_pdf", lambda *a, **k: "p. 1")
    monkeypatch.setattr("paperful.ocr.shutil.which", lambda name: "/usr/bin/ocrmypdf")
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        Path(cmd[-1]).write_bytes(b"%PDF-1.4 redo")

        class Proc:
            returncode = 0
            stderr = b""
            stdout = b""

        return Proc()

    monkeypatch.setattr("paperful.ocr.subprocess.run", fake_run)
    batch = ocr_items(
        _cfg(tmp_path),
        [_item(pdf)],
        Manifest(tmp_path / "state" / "manifest.jsonl"),
        None,
        apply=True,
    )
    assert batch.ocr == 1
    assert "--redo-ocr" in seen[0]
    assert "--skip-text" not in seen[0]
    assert "-l" in seen[0]


def test_cache_export_is_copied_to_out_before_ocr(tmp_path, monkeypatch):
    cache = _blank_pdf(tmp_path / "state" / "pdf-cache" / "FAO2019A.pdf")
    cfg = _cfg(tmp_path)
    item = _item(cache)
    monkeypatch.setattr("paperful.ocr.text_from_pdf", lambda *a, **k: "")
    monkeypatch.setattr("paperful.ocr.shutil.which", lambda name: "/usr/bin/ocrmypdf")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"%PDF-1.4 from-cache")

        class Proc:
            returncode = 0
            stderr = b""
            stdout = b""

        return Proc()

    monkeypatch.setattr("paperful.ocr.subprocess.run", fake_run)
    manifest = Manifest(cfg.manifest_path)
    batch = ocr_items(cfg, [item], manifest, None, apply=True)
    assert batch.ocr == 1
    written = Path(manifest.get("FAO2019A").path)
    assert cfg.pdf_cache_dir not in written.parents
    assert written.read_bytes() == b"%PDF-1.4 from-cache"
    assert cache.read_bytes() != b"%PDF-1.4 from-cache"


def test_attach_uploads_without_removing_the_disk_file(tmp_path, monkeypatch):
    pdf = _blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.setattr("paperful.ocr.text_from_pdf", lambda *a, **k: "")
    monkeypatch.setattr("paperful.ocr.shutil.which", lambda name: "/usr/bin/ocrmypdf")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"%PDF-1.4 attached")

        class Proc:
            returncode = 0
            stderr = b""
            stdout = b""

        return Proc()

    class Backend:
        def __init__(self):
            self.calls = []

        def attach(self, item_key, pdf_path, title=None, note=None):
            self.calls.append((item_key, title, note, Path(pdf_path).is_file()))
            return AttachResult(True, attachment_key="ATT1")

    monkeypatch.setattr("paperful.ocr.subprocess.run", fake_run)
    backend = Backend()
    batch = ocr_items(
        _cfg(tmp_path),
        [_item(pdf)],
        Manifest(tmp_path / "state" / "manifest.jsonl"),
        backend,
        apply=True,
        attach=True,
    )
    assert batch.ocr == 1
    assert "attached" in batch.rows[0].reason
    assert backend.calls == [("FAO2019A", "PDF (OCR)", "paperful ocr", True)]
    assert pdf.read_bytes() == b"%PDF-1.4 attached"
