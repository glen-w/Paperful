import hashlib
import os

from paperful.store import (
    STATUS_ATTACHED,
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
    Record,
    safe_filename,
    save_pdf,
    unique_path,
)
from paperful.zot import Item


def test_safe_filename_basic():
    assert safe_filename(
        "Ding", 2017, "Vulnerability to impacts of climate change"
    ) == ("Ding - 2017 - Vulnerability to impacts of climate change.pdf")


def test_safe_filename_strips_unsafe_and_accents():
    name = safe_filename("Müller/Schmidt", None, 'What: is "this"? <b>bold</b>')
    assert name == "MullerSchmidt - n.d. - What is this bold.pdf"
    assert "/" not in name and ":" not in name


def test_safe_filename_truncates_long_titles():
    long_title = " ".join(["word"] * 60)
    name = safe_filename("A", 2020, long_title)
    assert len(name) <= 180
    assert name.endswith(".pdf")


def _item(key="ABCD1234", paths=None):
    return Item(
        key=key,
        item_type="journalArticle",
        title="A paper",
        doi="10.1/x",
        arxiv_id=None,
        url=None,
        year=2020,
        first_author="Smith",
        collection_paths=paths or ["BBNJ/sub"],
    )


def test_save_pdf_writes_primary_and_hardlinks_extras(tmp_path):
    content = b"%PDF-1.4 fake"
    md5 = hashlib.md5(content).hexdigest()
    primary, extras = save_pdf(tmp_path, _item(paths=["BBNJ/sub", "AO"]), content, md5)
    assert primary == tmp_path / "BBNJ" / "sub" / "Smith - 2020 - A paper.pdf"
    assert primary.read_bytes() == content
    assert (
        len(extras) == 1 and extras[0] == tmp_path / "AO" / "Smith - 2020 - A paper.pdf"
    )
    assert os.stat(primary).st_ino == os.stat(extras[0]).st_ino  # hardlink


def test_unique_path_reuses_identical_and_suffixes_different(tmp_path):
    existing = tmp_path / "x.pdf"
    existing.write_bytes(b"same")
    same_md5 = hashlib.md5(b"same").hexdigest()
    assert unique_path(tmp_path, "x.pdf", same_md5) == existing
    other = unique_path(tmp_path, "x.pdf", hashlib.md5(b"other").hexdigest())
    assert other.name == "x (2).pdf"


def test_manifest_latest_record_wins_and_resume_logic(tmp_path):
    path = tmp_path / "manifest.jsonl"
    m = Manifest(path)
    m.write(Record(itemKey="K1", status=STATUS_ERROR))
    m.write(Record(itemKey="K1", status=STATUS_OK, path="/tmp/a.pdf"))
    m.write(Record(itemKey="K2", status=STATUS_NOT_FOUND))
    m.write(Record(itemKey="K3", status=STATUS_ERROR))
    m.write(Record(itemKey="K4", status=STATUS_ATTACHED, path="/tmp/b.pdf"))

    reloaded = Manifest(path)
    assert reloaded.get("K1").status == STATUS_OK
    assert not reloaded.should_process("K1", retry_failed=False)
    assert not reloaded.should_process("K4", retry_failed=True)
    assert not reloaded.should_process("K2", retry_failed=False)
    assert reloaded.should_process("K2", retry_failed=True)
    assert reloaded.should_process("K3", retry_failed=False)
    assert reloaded.should_process("NEW", retry_failed=False)
    assert [r.itemKey for r in reloaded.pending_attach()] == ["K1"]
    assert reloaded.counts() == {
        STATUS_OK: 1,
        STATUS_NOT_FOUND: 1,
        STATUS_ERROR: 1,
        STATUS_ATTACHED: 1,
    }


def test_manifest_tolerates_corrupt_lines(tmp_path):
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"itemKey": "K1", "status": "ok"}\nnot json\n{"unknown": 1}\n')
    m = Manifest(path)
    assert set(m.records) == {"K1"}


def test_manifest_loads_new_identifier_fields(tmp_path):
    path = tmp_path / "manifest.jsonl"
    rec = Record(
        itemKey="K2",
        status=STATUS_OK,
        doi="10.9/new",
        library_doi="10.1/old",
        doi_verified="swapped",
        pdf_doi="10.9/new",
    )
    m = Manifest(path)
    m.write(rec)
    m2 = Manifest(path)
    got = m2.get("K2")
    assert (
        got.library_doi == "10.1/old"
        and got.doi_verified == "swapped"
        and got.pdf_doi == "10.9/new"
    )


def test_attachment_payload_is_stored_file_with_basename():
    from pathlib import Path

    from paperful.attach import attachment_payload

    p = attachment_payload(Path("/x/y/Smith - 2020 - A paper.pdf"))
    assert p["itemType"] == "attachment" and p["linkMode"] == "imported_file"
    assert p["filename"] == "Smith - 2020 - A paper.pdf"
    assert p["contentType"] == "application/pdf"
