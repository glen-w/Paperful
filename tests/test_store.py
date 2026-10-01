import hashlib
import json as _json
import os

from paperful.store import (
    STATUS_ATTACHED,
    STATUS_ERROR,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_RETRYABLE,
    REASON_CLOSED,
    REASON_SHORT_PDF,
    REASON_STRICT_PDF_DOI,
    Manifest,
    Record,
    item_dirname,
    item_filename,
    items_from_mirror,
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
    m.write(Record(itemKey="K5", status=STATUS_NOT_FOUND, reason=REASON_CLOSED))
    m.write(Record(itemKey="K6", status=STATUS_RETRYABLE, reason="source paused"))
    assert not m.should_process("K5", retry_failed=False)
    assert m.should_process("K5", retry_failed=True)
    assert m.should_process("K6", retry_failed=False)
    assert [r.itemKey for r in reloaded.pending_attach()] == ["K1"]
    assert reloaded.counts() == {
        STATUS_OK: 1,
        STATUS_NOT_FOUND: 1,
        STATUS_ERROR: 1,
        STATUS_ATTACHED: 1,
    }


def test_pending_attach_skips_gated_reasons(tmp_path):
    m = Manifest(tmp_path / "m.jsonl")
    m.write(Record(itemKey="DOI", status=STATUS_OK, path="a.pdf", reason=REASON_STRICT_PDF_DOI))
    m.write(Record(itemKey="SHORT", status=STATUS_OK, path="b.pdf", reason=REASON_SHORT_PDF))
    m.write(Record(itemKey="OK", status=STATUS_OK, path="c.pdf"))
    assert [r.itemKey for r in m.pending_attach()] == ["OK"]
    assert [r.itemKey for r in m.pending_attach(allow_pdf_doi_mismatch=True)] == [
        "DOI",
        "OK",
    ]
    assert [r.itemKey for r in m.pending_attach(allow_short_pdf=True)] == ["SHORT", "OK"]
    assert [
        r.itemKey
        for r in m.pending_attach(allow_pdf_doi_mismatch=True, allow_short_pdf=True)
    ] == ["DOI", "SHORT", "OK"]


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
    assert p["title"] == "Full Text PDF"

    img = attachment_payload(Path("/x/y/thumbnail.jpg"), title="thumbnail")
    assert img["contentType"] == "image/jpeg"
    assert img["title"] == "thumbnail"
    assert img["filename"] == "thumbnail.jpg"


def test_resolve_pdf_path_rewrites_docker_data_prefix(tmp_path):
    pdf = tmp_path / "ocean" / "BBNJ" / "paper.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 x")
    assert resolve_pdf_path(tmp_path, str(pdf)) == pdf
    docker = f"/data/out/ocean/BBNJ/{pdf.name}"
    assert resolve_pdf_path(tmp_path, docker) == pdf
    assert resolve_pdf_path(tmp_path, "/data/out/missing.pdf") is None


# ---- items_from_mirror: the catalogue `run` uses when the manager is offline ---



def _mirror_item(out, collection, key, *, pdf=True, **record):
    folder = out / collection / f"Smith - 2020 - A paper -- {key}"
    folder.mkdir(parents=True, exist_ok=True)
    body = {"item_key": key, "title": f"Paper {key}", "year": 2020, **record}
    (folder / "record.json").write_text(_json.dumps(body))
    if pdf:
        (folder / "Smith - 2020 - A paper.pdf").write_bytes(b"%PDF-1.4")
    return folder


def test_mirror_catalogue_is_empty_without_an_out_dir(tmp_path):
    assert items_from_mirror(tmp_path / "missing") == []


def test_mirror_scope_includes_subcollections_but_not_prefix_siblings(tmp_path):
    out = tmp_path / "out"
    _mirror_item(out, "BBNJ", "K1")
    _mirror_item(out, "BBNJ/sub", "K2")
    _mirror_item(out, "BBNJ-old", "K3")
    _mirror_item(out, "Other", "K4")
    keys = sorted(i.key for i in items_from_mirror(out, ["BBNJ/"]))
    assert keys == ["K1", "K2"]
    assert len(items_from_mirror(out)) == 4


def test_mirror_item_in_two_collections_is_listed_once(tmp_path):
    out = tmp_path / "out"
    _mirror_item(out, "A", "K1", collection_paths=["A", "B"])
    _mirror_item(out, "B", "K1", collection_paths=["A", "B"])
    items = items_from_mirror(out)
    assert [i.key for i in items] == ["K1"]
    assert items[0].collection_paths == ["A", "B"]


def test_mirror_skips_corrupt_records_and_non_item_folders(tmp_path):
    out = tmp_path / "out"
    good = _mirror_item(out, "A", "K1")
    bad = _mirror_item(out, "A", "K2")
    (bad / "record.json").write_text("{not json")
    stray = out / "A" / "loose folder"
    stray.mkdir()
    (stray / "record.json").write_text(_json.dumps({"item_key": "K3"}))
    assert [i.key for i in items_from_mirror(out)] == ["K1"]
    assert good.is_dir()


def test_mirror_row_fields_and_fallbacks(tmp_path):
    out = tmp_path / "out"
    _mirror_item(
        out,
        "A",
        "DIRKEY1",
        pdf=False,
        item_key=None,
        year="2020",
        creators=[{"name": "UNESCO"}],
        doi="10.1000/x",
    )
    (item,) = items_from_mirror(out)
    assert item.key == "DIRKEY1"
    assert item.year is None
    assert item.first_author == "UNESCO"
    assert item.collection_paths == ["A"]
    assert item.has_pdf is False and item.pdf_path is None
    assert item.doi == "10.1000/x"
