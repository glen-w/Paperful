import hashlib
import os
from pathlib import Path

from paperful.store import (
    STATUS_ATTACHED,
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    Manifest,
    Record,
    item_dirname,
    item_filename,
    resolve_pdf_path,
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
    item = _item(paths=["BBNJ/sub", "AO"])
    primary, extras = save_pdf(tmp_path, item, content, md5)
    folder = item_dirname(item)
    name = item_filename(item)
    assert primary == tmp_path / "BBNJ" / "sub" / folder / name
    assert primary.read_bytes() == content
    assert len(extras) == 1 and extras[0] == tmp_path / "AO" / folder / name
    assert os.stat(primary).st_ino == os.stat(extras[0]).st_ino  # hardlink


def test_write_fetch_records_sits_beside_each_copy(tmp_path):
    import json

    from paperful.store import ITEM_SCHEMA, record_path, write_fetch_records

    content = b"%PDF-1.4 fake"
    md5 = hashlib.md5(content).hexdigest()
    item = _item(paths=["BBNJ/sub", "AO"])
    item.publication_title = "Marine Policy"
    item.date = "2020-03"
    primary, extras = save_pdf(tmp_path, item, content, md5)
    written = write_fetch_records(
        [primary, *extras],
        item,
        md5=md5,
        source="unpaywall",
        fetched_url="https://oa.test/a.pdf",
        pdf_doi="10.1/x",
    )
    assert written == [record_path(primary.parent), record_path(extras[0].parent)]
    cards = [json.loads(p.read_text()) for p in written]
    assert cards[0]["schema"] == ITEM_SCHEMA
    assert cards[0]["item_key"] == "ABCD1234"
    assert cards[0]["fetch"]["source"] == "unpaywall"
    assert cards[0]["fetch"]["fetched_url"] == "https://oa.test/a.pdf"
    assert cards[0]["pdf_doi"] == "10.1/x"
    assert cards[0]["fetch"]["md5"] == md5
    assert cards[0]["fetch"]["pdf"] == primary.name
    assert cards[1]["fetch"]["pdf"] == extras[0].name
    assert cards[0]["fetch"]["fetched_at"] == cards[1]["fetch"]["fetched_at"]
    assert cards[0]["publication_title"] == "Marine Policy"
    write_fetch_records(
        [primary],
        item,
        md5=md5,
        source="ezproxy",
        fetched_url="https://proxy.test/a.pdf",
        pdf_doi=None,
    )
    again = json.loads(record_path(primary.parent).read_text())
    assert again["fetch"]["source"] == "ezproxy" and again["pdf_doi"] is None


def test_save_pdf_moves_a_flat_file_into_the_item_folder(tmp_path):
    import json

    item = _item(paths=["BBNJ/sub"])
    content = b"%PDF-1.4 old"
    flat = tmp_path / "BBNJ" / "sub"
    flat.mkdir(parents=True)
    name = item_filename(item)
    (flat / name).write_bytes(content)
    (flat / f"{Path(name).stem}.paperful.json").write_text(
        json.dumps({"item_key": item.key, "source": "unpaywall", "title": item.title})
    )
    primary, extras = save_pdf(tmp_path, item, content, hashlib.md5(content).hexdigest())
    assert extras == []
    assert primary.parent.name == item_dirname(item)
    assert not (flat / name).exists()
    body = json.loads((primary.parent / "record.json").read_text())
    assert body["fetch"]["source"] == "unpaywall"
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


def test_resolve_pdf_path_rewrites_docker_data_prefix(tmp_path):
    pdf = tmp_path / "ocean" / "BBNJ" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 x")
    assert resolve_pdf_path(tmp_path, str(pdf)) == pdf
    docker = f"/data/out/ocean/BBNJ/{pdf.name}"
    assert resolve_pdf_path(tmp_path, docker) == pdf
    assert resolve_pdf_path(tmp_path, "/data/out/missing.pdf") is None
