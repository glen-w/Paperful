"""Attacher against a stubbed Zotero client - exercises key handling and error mapping, no Zotero needed."""

from __future__ import annotations

import json

import pytest
from pyzotero import errors as ze

from paperful import attach as at
from paperful.attach import (
    Attacher,
    _interpret,
    attach_failure_code,
    attachment_payload,
)


class StubZot:
    def __init__(self):
        self.local_api_key = None
        self.client = type("C", (), {"timeout": 30})()
        self.authorize_calls = 0
        self.authorize_response = {"key": "KEY1", "remember": True}
        self.authorize_error = None

    def authorize_local(self, app_name):
        self.authorize_calls += 1
        if self.authorize_error:
            raise self.authorize_error
        self.local_api_key = self.authorize_response["key"]
        return self.authorize_response


class StubZL:
    def __init__(self, supports_write=True):
        self.zot = StubZot()
        self._supports = supports_write

    def ping(self):
        return {"supports_write": self._supports}


class ScriptedUpload:
    """Replacement for LocalZupload: returns scripted results or raises."""

    script: list = []
    seen: list = []

    def __init__(self, zot, payload, parentid, basedir=None):
        ScriptedUpload.seen.append(
            (
                parentid,
                payload[0]["filename"],
                basedir,
                zot.local_api_key,
                payload[0].get("note"),
            )
        )

    def upload(self):
        step = ScriptedUpload.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "Smith - 2019 - Title.pdf"
    p.write_bytes(b"%PDF-1.4 x")
    return p


@pytest.fixture
def scripted(monkeypatch):
    ScriptedUpload.script = []
    ScriptedUpload.seen = []
    monkeypatch.setattr(at, "LocalZupload", ScriptedUpload)
    return ScriptedUpload


def test_interpret_buckets():
    assert _interpret({"success": [{"key": "A"}]}).ok
    assert _interpret({"unchanged": [{"key": "A"}]}).reason == "unchanged"
    r = _interpret({"failure": [{"error": "bad"}]})
    assert not r.ok and r.reason == "bad"
    assert not _interpret({}).ok


def test_attachment_payload_shape(pdf):
    p = attachment_payload(pdf, title="Custom")
    assert (
        p["title"] == "Custom"
        and p["filename"] == pdf.name
        and p["linkMode"] == "imported_file"
    )
    assert attachment_payload(pdf)["title"] == "Full Text PDF"


def test_attachment_note_is_provenance(pdf):
    note = "paperful oa:unpaywall"
    p = attachment_payload(pdf, note=note)
    assert p["note"] == note
    assert p["title"] == "Full Text PDF"


def test_upload_auth_encodes_spaces_as_percent20(pdf):
    captured: dict[str, str] = {}

    class Z:
        endpoint = "http://localhost:23119/api"
        library_type = "users"
        library_id = "0"

        def _write(self, method, url, content, headers):
            del method, url, headers
            captured["body"] = content

            class Resp:
                def json(self):
                    return {"exists": 1}

            return Resp()

    up = at.LocalZupload.__new__(at.LocalZupload)
    up.zinstance = Z()
    up._post_with_retry = lambda fn: fn()  # type: ignore[method-assign]
    up._get_auth(str(pdf), "PARENT")
    body = captured["body"]
    assert "Smith%20-%202019%20-%20Title.pdf" in body
    assert "filename=Smith+" not in body


def test_missing_file_and_no_write_support(cfg, pdf):
    a = Attacher(cfg, StubZL(supports_write=True))
    assert "file missing" in a.attach("K", pdf.parent / "nope.pdf").reason
    b = Attacher(cfg, StubZL(supports_write=False))
    res = b.attach("K", pdf)
    assert "Zotero 10+" in res.reason and res.code == "no_write_api"


def test_attach_failure_code_classification():
    assert attach_failure_code("storage quota exceeded") == "quota"
    assert (
        attach_failure_code("Zotero local API has no write support") == "no_write_api"
    )
    assert attach_failure_code("write authorisation denied") == "auth"
    assert (
        attach_failure_code(
            "{'key': '', 'code': 400, 'message': 'Parent item 1/ABCD1234 not found'}"
        )
        == "parent_missing"
    )
    assert at.parent_missing("Parent item 1/X not found")
    assert not at.parent_missing("UploadError: boom")


def test_authorises_stores_key_and_uploads(cfg, pdf, scripted):
    scripted.script.append(
        {"success": [{"key": "ATT"}], "failure": [], "unchanged": []}
    )
    zl = StubZL()
    a = Attacher(cfg, zl)
    res = a.attach("PARENT", pdf)
    assert res.ok and res.attachment_key == "ATT"
    assert zl.zot.authorize_calls == 1
    assert json.loads(cfg.local_key_path.read_text()) == {"key": "KEY1"}
    assert scripted.seen == [("PARENT", pdf.name, str(pdf.parent), "KEY1", "")]
    assert zl.zot.client.timeout == at.DIALOG_TIMEOUT_S


def test_stored_key_is_reused_without_dialog(cfg, pdf, scripted):
    cfg.local_key_path.parent.mkdir(parents=True)
    cfg.local_key_path.write_text(json.dumps({"key": "STORED"}))
    scripted.script.append({"success": [{"key": "ATT"}]})
    zl = StubZL()
    a = Attacher(cfg, zl)
    assert a.attach("P", pdf).ok
    assert zl.zot.authorize_calls == 0 and scripted.seen[0][3] == "STORED"


def test_single_use_key_consumed_triggers_reauthorise(cfg, pdf, scripted):
    scripted.script += [
        ze.LocalAPIKeyRequiredError("consumed"),
        {"success": [{"key": "ATT2"}]},
    ]
    zl = StubZL()
    zl.zot.authorize_response = {"key": "ONCE", "remember": False}
    a = Attacher(cfg, zl)
    res = a.attach("P", pdf)
    assert res.ok and zl.zot.authorize_calls == 2
    assert not cfg.local_key_path.exists()  # one-shot keys are never persisted


def test_denied_and_transport_failures(cfg, pdf, scripted):
    zl = StubZL()
    zl.zot.authorize_error = ze.LocalAPIDeniedError("no")
    assert "denied" in Attacher(cfg, zl).attach("P", pdf).reason

    zl2 = StubZL()
    zl2.zot.authorize_error = TimeoutError("dialog")
    assert "authorisation failed" in Attacher(cfg, zl2).attach("P", pdf).reason

    scripted.script.append(ze.TooManyRequestsError("slow down"))
    assert "rate-limited" in Attacher(cfg, StubZL()).attach("P", pdf).reason

    scripted.script.append(ze.UploadError("boom"))
    assert "UploadError" in Attacher(cfg, StubZL()).attach("P", pdf).reason

    scripted.script.append(RuntimeError("transport"))
    assert "RuntimeError" in Attacher(cfg, StubZL()).attach("P", pdf).reason


def test_supports_write_swallows_ping_errors(cfg):
    class Broken(StubZL):
        def ping(self):
            raise ConnectionError("down")

    assert Attacher(cfg, Broken()).supports_write() is False
