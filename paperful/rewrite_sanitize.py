"""Sanitize rewrite *copies*: invisible Unicode, C2PA, token-tracker channels."""

from __future__ import annotations

import hashlib
import io
import random
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as _DET

from .config import Config
from .fsio import atomic_write_bytes, atomic_write_text
from .hidden_text import fold_homoglyphs, nfc, strip_invisible
from .rewrite_grounding import freeze_tokens, thaw
from .rewrite_plan import RewriteEdit

# Closed-class / spelling variants. Not rare-thesaurus, not citation injection.
_TRACKER_PAIRS: tuple[tuple[str, str], ...] = (
    ("towards", "toward"),
    ("amongst", "among"),
    ("whilst", "while"),
    ("onwards", "onward"),
    ("afterwards", "afterward"),
    ("forwards", "forward"),
    ("besides", "beside"),
    ("amidst", "amid"),
    ("until", "till"),
)
_WORD = re.compile(r"[A-Za-z']+")
_C2PA_NAME = re.compile(r"c2pa", re.I)
_JPEG_SOI = b"\xff\xd8"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_TRACKER_PROSE = """You vary closed-class wording in one already-edited academic paragraph.
Return JSON: {"paragraph":"full paragraph"}
Copy every «PF…» placeholder unchanged. Do not add numbers, cites, URLs, or claims.
Do not mention Paperful, detectors, or watermarks. Keep the paper's voice.
"""


def parse_tracker_scope(raw: Any) -> str:
    value = str(raw or "edited").strip().lower() or "edited"
    if value not in {"edited", "all"}:
        raise ValueError("[rewrite].tracker_scope must be edited or all")
    return value


def _swap_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for a, b in _TRACKER_PAIRS:
        out[a] = b
        out[b] = a
        out[a[:1].upper() + a[1:]] = b[:1].upper() + b[1:]
        out[b[:1].upper() + b[1:]] = a[:1].upper() + a[1:]
    return out


_SWAPS = _swap_map()


def perturb_trackers(text: str, *, rate: float, seed: int) -> tuple[str, int]:
    """Swap a fraction of eligible closed-class tokens. Freeze numbers/cites first."""
    src = text or ""
    if rate <= 0 or not src.strip():
        return src, 0
    frozen, mapping = freeze_tokens(src)
    rng = random.Random(seed)  # noqa: S311 — reproducible token shatter, not crypto
    hits: list[re.Match[str]] = []
    for m in _WORD.finditer(frozen):
        if m.group(0) in _SWAPS:
            hits.append(m)
    if not hits:
        return src, 0
    k = max(1, int(round(len(hits) * min(1.0, rate)))) if hits else 0
    chosen = set(rng.sample(range(len(hits)), min(k, len(hits))))
    parts: list[str] = []
    cursor = 0
    n = 0
    for i, m in enumerate(hits):
        parts.append(frozen[cursor : m.start()])
        word = m.group(0)
        if i in chosen:
            parts.append(_SWAPS[word])
            n += 1
        else:
            parts.append(word)
        cursor = m.end()
    parts.append(frozen[cursor:])
    return thaw("".join(parts), mapping), n


def sanitize_plain_text(
    text: str,
    *,
    invisible: bool,
    trackers: bool,
    rate: float,
    seed: int,
) -> tuple[str, dict[str, int]]:
    stats = {"invisible": 0, "homoglyphs": 0, "trackers": 0}
    out = nfc(text or "")
    if invisible:
        out, n = strip_invisible(out)
        stats["invisible"] = n
        out, n = fold_homoglyphs(out)
        stats["homoglyphs"] = n
    if trackers:
        out, n = perturb_trackers(out, rate=rate, seed=seed)
        stats["trackers"] = n
    return out, stats


def _strip_jpeg_app11(data: bytes) -> tuple[bytes, int]:
    if not data.startswith(_JPEG_SOI):
        return data, 0
    out = bytearray(data[:2])
    i = 2
    n = 0
    end = len(data)
    while i < end:
        if data[i] != 0xFF:
            out.extend(data[i:])
            break
        marker = data[i + 1] if i + 1 < end else 0
        if marker in {0xD8, 0xD9}:
            out.extend(data[i : i + 2])
            i += 2
            continue
        if marker == 0xDA:
            out.extend(data[i:])
            break
        if i + 3 >= end:
            out.extend(data[i:])
            break
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        chunk = data[i : i + 2 + length]
        if marker == 0xEB:
            n += 1
        else:
            out.extend(chunk)
        i += 2 + length
    return bytes(out), n


def _strip_png_cabx(data: bytes) -> tuple[bytes, int]:
    if not data.startswith(_PNG_SIG):
        return data, 0
    out = bytearray(_PNG_SIG)
    i = 8
    n = 0
    end = len(data)
    while i + 12 <= end:
        length = int.from_bytes(data[i : i + 4], "big")
        ctype = data[i + 4 : i + 8]
        chunk = data[i : i + 12 + length]
        if ctype == b"caBX":
            n += 1
        else:
            out.extend(chunk)
        i += 12 + length
        if ctype == b"IEND":
            break
    if i < end and n == 0:
        return data, 0
    return bytes(out), n


def _sanitize_embedded_image(data: bytes) -> tuple[bytes, int]:
    if data.startswith(_JPEG_SOI):
        return _strip_jpeg_app11(data)
    if data.startswith(_PNG_SIG):
        return _strip_png_cabx(data)
    return data, 0


def strip_c2pa_zip(path: Path) -> dict[str, int]:
    """Drop C2PA parts and JUMBF in embedded images. Rewrites the zip in place."""
    stats = {"c2pa_parts": 0, "c2pa_images": 0}
    if not path.is_file():
        return stats
    try:
        raw = path.read_bytes()
        zin = zipfile.ZipFile(io.BytesIO(raw), "r")
    except (OSError, zipfile.BadZipFile):
        return stats
    names = zin.namelist()
    drop = {n for n in names if _C2PA_NAME.search(n)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            name = info.filename
            data = zin.read(name)
            if name in drop:
                stats["c2pa_parts"] += 1
                continue
            lower = name.casefold()
            if lower.endswith((".xml", ".rels")):
                text = data.decode("utf-8", errors="ignore")
                if _C2PA_NAME.search(text) and (
                    "content-types" in lower or name.endswith(".rels")
                ):
                    cleaned = []
                    for line in text.splitlines(keepends=True):
                        if _C2PA_NAME.search(line):
                            stats["c2pa_parts"] += 1
                            continue
                        cleaned.append(line)
                    data = "".join(cleaned).encode("utf-8")
            if lower.endswith((".jpg", ".jpeg", ".png")):
                data, n = _sanitize_embedded_image(data)
                stats["c2pa_images"] += n
            zout.writestr(info, data)
    zin.close()
    if stats["c2pa_parts"] or stats["c2pa_images"]:
        atomic_write_bytes(path, buf.getvalue())
    return stats


def strip_c2pa_pdf(path: Path) -> dict[str, int]:
    stats = {"c2pa_pdf": 0}
    if not path.is_file():
        return stats
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return stats
    try:
        reader = PdfReader(str(path))
    except Exception:
        return stats
    blob = path.read_bytes()
    hit = b"c2pa" in blob.lower()
    if not hit:
        return stats
    writer = PdfWriter()
    writer.append(reader)
    if writer.metadata:
        try:
            writer.add_metadata(
                {
                    k: v
                    for k, v in dict(writer.metadata).items()
                    if "c2pa" not in str(k).casefold()
                    and "c2pa" not in str(v).casefold()
                }
            )
        except Exception:
            stats["c2pa_pdf"] = 0
    try:
        tmp = path.with_suffix(path.suffix + ".c2pa-tmp")
        with tmp.open("wb") as fh:
            writer.write(fh)
        tmp.replace(path)
        stats["c2pa_pdf"] = 1
    except OSError:
        return {"c2pa_pdf": 0}
    return stats


def _walk_xml_strings(root: ET.Element) -> int:
    n = 0
    for el in root.iter():
        if el.text:
            cleaned, a = strip_invisible(el.text)
            cleaned, b = fold_homoglyphs(cleaned)
            if cleaned != el.text:
                el.text = cleaned
                n += a + b
        if el.tail:
            cleaned, a = strip_invisible(el.tail)
            cleaned, b = fold_homoglyphs(cleaned)
            if cleaned != el.tail:
                el.tail = cleaned
                n += a + b
    return n


def sanitize_office_xml_text(path: Path, *, trackers: bool, rate: float, seed: int) -> dict[str, int]:
    stats = {"invisible": 0, "trackers": 0}
    if not path.is_file() or not zipfile.is_zipfile(path):
        return stats
    try:
        zin = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile):
        return stats
    buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            lower = info.filename.casefold()
            if lower.endswith(".xml") and not lower.endswith(".rels"):
                try:
                    root = _DET.fromstring(data)
                except Exception:
                    zout.writestr(info, data)
                    continue
                n = _walk_xml_strings(root)
                if n:
                    stats["invisible"] += n
                    changed = True
                if trackers:
                    xml = ET.tostring(root, encoding="utf-8")
                    text = xml.decode("utf-8")
                    new, tn = perturb_trackers(text, rate=rate, seed=seed)
                    if tn:
                        stats["trackers"] += tn
                        data = new.encode("utf-8")
                        changed = True
                    else:
                        data = ET.tostring(root, encoding="utf-8")
                else:
                    data = ET.tostring(root, encoding="utf-8") if n else data
            zout.writestr(info, data)
    zin.close()
    if changed:
        atomic_write_bytes(path, buf.getvalue())
    return stats


def _seed_for(path: Path, extra: str = "") -> int:
    h = hashlib.sha256(f"{path.name}:{extra}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % (2**31)


def tracker_prose_paragraph(
    cfg: Config,
    paragraph: str,
    client: Any,
    timeout_s: float,
) -> str | None:
    """Optional LLM closed-class variation of an already-edited paragraph."""
    if client is None or not (paragraph or "").strip():
        return None
    from .llm.client import ChatRequest, chat, ctx_tokens_for, prompt_exceeds_ctx
    from .peer_review_llm import parse_llm_json
    from .rewrite_grounding import freeze_preserved, numbers_ok

    frozen, mapping = freeze_tokens(paragraph)
    user = f"<PAPER_CONTENT>\n{frozen}\n</PAPER_CONTENT>\nVary closed-class wording only."
    blob = _TRACKER_PROSE + user
    max_ctx = int(cfg.llm_max_num_ctx or 32768)
    if prompt_exceeds_ctx(blob, max_num_ctx=max_ctx):
        return None
    model = (cfg.llm_model or "").strip()
    if not model:
        return None
    req = ChatRequest(
        model=model,
        messages=(
            {"role": "system", "content": _TRACKER_PROSE},
            {"role": "user", "content": user},
        ),
        timeout_seconds=timeout_s,
        temperature=0.0,
        seed=0,
        num_ctx=ctx_tokens_for(blob, max_num_ctx=max_ctx),
    )
    try:
        raw = chat(client, req)
    except Exception:
        return None
    data = parse_llm_json(raw) or {}
    reply = str(data.get("paragraph") or "").strip()
    if not reply or not freeze_preserved(
        selected_frozen=frozen, reply=reply, mapping=mapping
    ):
        return None
    thawed = thaw(reply, mapping)
    if not numbers_ok(thawed, paragraph):
        return None
    return thawed


def apply_tracker_prose(
    cfg: Config,
    edits: list[RewriteEdit],
    *,
    client: Any,
    timeout_s: float,
) -> int:
    if not getattr(cfg, "rewrite_tracker_prose", True) or client is None:
        return 0
    n = 0
    for edit in edits:
        if edit.kind not in {"replace", "insert"}:
            continue
        para = edit.target_paragraph or ""
        if not para.strip():
            continue
        updated = tracker_prose_paragraph(cfg, para, client, timeout_s)
        if not updated or updated == para:
            continue
        edit.target_paragraph = updated
        if edit.kind == "replace" and edit.source_paragraph:
            from .rewrite_llm import paragraph_span

            diff = paragraph_span(edit.source_paragraph, updated)
            if diff is not None:
                edit.quote, edit.replacement, _, _ = diff
        n += 1
    return n


def sanitize_rewrite_folder(
    cfg: Config,
    folder: Path,
    *,
    payload: dict[str, Any],
    manuscript: Path,
) -> dict[str, Any]:
    """Run on files Paperful just wrote. Never touches ``manuscript``."""
    report: dict[str, Any] = {
        "invisible": 0,
        "homoglyphs": 0,
        "trackers": 0,
        "c2pa_parts": 0,
        "c2pa_images": 0,
        "c2pa_pdf": 0,
        "files": [],
    }
    if not getattr(cfg, "rewrite_sanitize", True):
        report["skipped"] = "off"
        return report
    invisible = bool(getattr(cfg, "rewrite_sanitize_invisible", True))
    c2pa = bool(getattr(cfg, "rewrite_sanitize_c2pa", True))
    trackers = bool(getattr(cfg, "rewrite_sanitize_trackers", True))
    rate = float(getattr(cfg, "rewrite_tracker_rate", 0.08) or 0.0)
    scope = str(getattr(cfg, "rewrite_tracker_scope", "edited") or "edited")
    if not invisible and not c2pa and not trackers:
        report["skipped"] = "layers_off"
        return report
    do_stat = trackers and scope == "all"
    for name in (
        "sidecar.md",
        "sidecar.txt",
        "tracked.docx",
        "tracked.pptx",
        "tracked.odt",
        "tracked.pdf",
    ):
        path = folder / name
        if not path.is_file():
            continue
        if path.resolve() == manuscript.resolve():
            continue
        report["files"].append(name)
        if name.startswith("sidecar") and (invisible or do_stat):
            text = path.read_text(encoding="utf-8")
            new, stats = sanitize_plain_text(
                text,
                invisible=invisible,
                trackers=do_stat,
                rate=rate,
                seed=_seed_for(path, payload.get("peer_review_id") or ""),
            )
            if new != text:
                atomic_write_text(path, new, encoding="utf-8")
            for k, v in stats.items():
                report[k] = int(report.get(k, 0) or 0) + v
        if name.endswith((".docx", ".pptx", ".odt")):
            if invisible or do_stat:
                xml_stats = sanitize_office_xml_text(
                    path,
                    trackers=do_stat,
                    rate=rate,
                    seed=_seed_for(path),
                )
                report["invisible"] = int(report["invisible"]) + int(
                    xml_stats.get("invisible") or 0
                )
                report["trackers"] = int(report["trackers"]) + int(
                    xml_stats.get("trackers") or 0
                )
            if c2pa:
                zstats = strip_c2pa_zip(path)
                report["c2pa_parts"] = int(report["c2pa_parts"]) + int(
                    zstats.get("c2pa_parts") or 0
                )
                report["c2pa_images"] = int(report["c2pa_images"]) + int(
                    zstats.get("c2pa_images") or 0
                )
        if name.endswith(".pdf") and c2pa:
            pstats = strip_c2pa_pdf(path)
            report["c2pa_pdf"] = int(report["c2pa_pdf"]) + int(pstats.get("c2pa_pdf") or 0)
        if name.endswith(".pdf") and (invisible or do_stat):
            # PDF is a print of applied text; Playwright already used sanitized sidecar
            # when we sanitize sidecar first. Extra no-op here.
            pass
    report["layers"] = {
        "invisible": invisible,
        "c2pa": c2pa,
        "trackers": trackers,
        "tracker_scope": scope,
        "tracker_rate": rate,
    }
    return report
