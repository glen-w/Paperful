"""``paperful urls`` and ``paperful htmlpdf proposals`` through the CLI, offline."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from paperful import cli, cli_runtime
from paperful.attach import AttachResult
from paperful.sources.htmlpdf import proposals_dir, write_proposal
from tests.conftest import make_item

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(cli, "console", Console(highlight=False, width=250, height=100))
    monkeypatch.setattr(cli_runtime, "console", cli.console)


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'email = "t@example.org"\nout_dir = "{tmp_path / "out"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
    )
    return p


class FakeBackend:
    def __init__(self, items, *, write=True, children=None, attach_ok=True):
        self._items = items
        self._write = write
        self._children = children or {}
        self._attach_ok = attach_ok
        self.patches: list[tuple[str, dict]] = []
        self.attached: list[tuple[str, Path]] = []
        self.flushed = False

    def supports_write(self):
        return self._write

    def items_in_scope(self, keys):
        return list(self._items)

    def children(self, key):
        return self._children.get(key, [])

    def apply_patch(self, key, fields):
        self.patches.append((key, fields))

    def attach(self, item_key, pdf, title=None, note=None):
        self.attached.append((item_key, Path(pdf)))
        if self._attach_ok:
            return AttachResult(ok=True, attachment_key="ATT1")
        return AttachResult(ok=False, reason="zotero said no")

    def flush_writes(self):
        self.flushed = True
        return None


def _wire(monkeypatch, backend):
    monkeypatch.setattr(cli_runtime, "_connect", lambda cfg, quiet=False: backend)
    monkeypatch.setattr(cli_runtime, "_scope_keys", lambda b, c, lib: (None, "library"))


def _mock_http(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )


ARTICLE = "<html><body>" + "A real article body about marine governance. " * 6 + "</body></html>"


def _http(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/ok":
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})
    if path == "/gone":
        return httpx.Response(404, text="nope", headers={"content-type": "text/html"})
    if path == "/old":
        return httpx.Response(301, headers={"location": "https://example.org/ok"})
    if path == "/stub":
        return httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"})
    if path == "/file.pdf":
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
    return httpx.Response(500, text="boom")


def _urls_items():
    return [
        make_item(key="OKAY", url="https://example.org/ok"),
        make_item(key="DEAD", url="https://example.org/gone"),
        make_item(key="MOVE", url="https://example.org/old"),
        make_item(key="STUB", url="https://example.org/stub"),
        make_item(key="NOURL", url=""),
    ]


# --- urls ---------------------------------------------------------------------


def test_urls_requires_scope(cfg_file):
    res = runner.invoke(cli.app, ["urls", "--config", str(cfg_file)])
    assert res.exit_code == 1
    assert "--collection" in res.output and "--library" in res.output


def test_urls_report_json_classifies_every_target(cfg_file, monkeypatch):
    backend = FakeBackend(
        _urls_items(),
        children={
            "OKAY": [
                {
                    "key": "CH1",
                    "data": {
                        "key": "CH1",
                        "contentType": "application/pdf",
                        "linkMode": "linked_url",
                        "url": "https://example.org/file.pdf",
                    },
                },
                {"key": "CH2", "data": {"contentType": "text/html", "url": "https://x.test"}},
            ]
        },
    )
    _wire(monkeypatch, backend)
    _mock_http(monkeypatch, _http)
    res = runner.invoke(
        cli.app, ["urls", "--library", "--format", "json", "--config", str(cfg_file)]
    )
    assert res.exit_code == 0, res.output
    body = json.loads(res.stdout)
    codes = {(r["item_key"], r["role"]): r["code"] for r in body["items"]}
    assert codes[("OKAY", "parent")] == "ok"
    assert codes[("OKAY", "linked_pdf")] == "ok"
    assert codes[("DEAD", "parent")] == "hard_dead"
    assert codes[("MOVE", "parent")] in {"redirect", "ok"}
    assert codes[("STUB", "parent")] == "soft_404"
    assert ("NOURL", "parent") not in codes
    assert body["summary"]["checked"] == len(body["items"]) == 5
    assert body["summary"]["applied"] == body["summary"]["refused"] == 0
    assert backend.patches == []  # report only without --apply


def test_urls_human_table_and_limit(cfg_file, monkeypatch):
    _wire(monkeypatch, FakeBackend(_urls_items()))
    _mock_http(monkeypatch, _http)
    res = runner.invoke(
        cli.app, ["urls", "--library", "--limit", "2", "--config", str(cfg_file)]
    )
    assert res.exit_code == 0, res.output
    assert "URL health" in res.output
    assert "OKAY" in res.output and "DEAD" in res.output
    assert "STUB" not in res.output


def test_urls_apply_rewrites_only_known_playbook_targets(cfg_file, monkeypatch):
    backend = FakeBackend(
        [
            make_item(key="OKAY", url="https://example.org/ok"),
            make_item(key="DEAD", url="https://example.org/gone"),
        ]
    )
    _wire(monkeypatch, backend)
    _mock_http(monkeypatch, _http)
    monkeypatch.setattr(
        "paperful.urls.planned_rewrite",
        lambda url, playbooks=None: "https://example.org/ok.pdf" if url.endswith("/ok") else None,
    )
    res = runner.invoke(
        cli.app,
        ["urls", "--library", "--apply", "--format", "json", "--config", str(cfg_file)],
    )
    assert res.exit_code == 0, res.output
    body = json.loads(res.stdout)
    assert backend.patches == [("OKAY", {"url": "https://example.org/ok.pdf"})]
    assert body["summary"]["applied"] == 1 and body["summary"]["refused"] == 1
    applied = {r["item_key"]: r["apply"] for r in body["items"]}
    assert applied == {"OKAY": "rewritten", "DEAD": "refused"}


def test_urls_apply_refused_when_library_is_read_only(cfg_file, monkeypatch):
    backend = FakeBackend([make_item(key="OKAY", url="https://example.org/ok")], write=False)
    _wire(monkeypatch, backend)
    _mock_http(monkeypatch, _http)
    monkeypatch.setattr(
        "paperful.urls.planned_rewrite", lambda url, playbooks=None: "https://example.org/x.pdf"
    )
    res = runner.invoke(cli.app, ["urls", "--library", "--apply", "--config", str(cfg_file)])
    assert res.exit_code == 0, res.output
    assert backend.patches == []
    assert "Refused 1" in res.output


# --- htmlpdf proposals ----------------------------------------------------------


def _cfg_obj(cfg_file):
    return cli_runtime._cfg(cfg_file)


def _proposal(cfg, key="P1", body=None, status=None):
    item = make_item(key=key, title="Marine governance of the high seas")
    text = body if body is not None else ("Marine governance of the high seas. " * 80)
    path = write_proposal(cfg, item, b"%PDF-1.4 fake", "https://example.org/article", body=text)
    if status:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = status
        path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_htmlpdf_list_empty_and_filtered(cfg_file):
    cfg = _cfg_obj(cfg_file)
    res = runner.invoke(cli.app, ["htmlpdf", "proposals", "list", "--config", str(cfg_file)])
    assert res.exit_code == 0
    assert "No HTML snapshot proposals" in res.output

    _proposal(cfg, "P1")
    _proposal(cfg, "P2", status="rejected")
    res = runner.invoke(
        cli.app,
        ["htmlpdf", "proposals", "list", "--format", "json", "--config", str(cfg_file)],
    )
    body = json.loads(res.stdout)
    assert [r["id"] for r in body["items"]] == ["P1"]
    res = runner.invoke(
        cli.app,
        ["htmlpdf", "proposals", "list", "--status", "all", "--config", str(cfg_file)],
    )
    assert "P1" in res.output and "P2" in res.output


def test_htmlpdf_reject_removes_pdf_and_marks_rejected(cfg_file):
    cfg = _cfg_obj(cfg_file)
    path = _proposal(cfg, "P1")
    pdf = proposals_dir(cfg) / "P1.pdf"
    assert pdf.is_file()
    res = runner.invoke(cli.app, ["htmlpdf", "proposals", "reject", "P1", "--config", str(cfg_file)])
    assert res.exit_code == 0, res.output
    assert "Rejected proposal P1" in res.output
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "rejected"
    assert not pdf.exists()


def test_htmlpdf_reject_unknown_id_exits_1(cfg_file):
    res = runner.invoke(
        cli.app, ["htmlpdf", "proposals", "reject", "NOPE", "--config", str(cfg_file)]
    )
    assert res.exit_code == 1
    assert "no htmlpdf proposal" in res.output


def test_htmlpdf_apply_attaches_and_marks_applied(cfg_file, monkeypatch):
    cfg = _cfg_obj(cfg_file)
    path = _proposal(cfg, "P1")
    backend = FakeBackend([])
    _wire(monkeypatch, backend)
    res = runner.invoke(
        cli.app,
        ["htmlpdf", "proposals", "apply", "P1", "--format", "json", "--config", str(cfg_file)],
    )
    assert res.exit_code == 0, res.output
    assert backend.attached and backend.attached[0][0] == "P1"
    assert backend.flushed
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "applied"
    body = json.loads(res.stdout)
    assert body["summary"] == {"id": "P1", "item_key": "P1"}


def test_htmlpdf_apply_human_message(cfg_file, monkeypatch):
    cfg = _cfg_obj(cfg_file)
    _proposal(cfg, "P1")
    _wire(monkeypatch, FakeBackend([]))
    res = runner.invoke(cli.app, ["htmlpdf", "proposals", "apply", "P1", "--config", str(cfg_file)])
    assert res.exit_code == 0, res.output
    assert "Attached snapshot P1" in res.output


def test_htmlpdf_apply_needs_write_support(cfg_file, monkeypatch):
    cfg = _cfg_obj(cfg_file)
    _proposal(cfg, "P1")
    backend = FakeBackend([], write=False)
    _wire(monkeypatch, backend)
    res = runner.invoke(cli.app, ["htmlpdf", "proposals", "apply", "P1", "--config", str(cfg_file)])
    assert res.exit_code == 2
    assert "needs library write support" in res.output
    assert backend.attached == []


def test_htmlpdf_apply_refuses_non_pending_and_failed_gate(cfg_file, monkeypatch):
    cfg = _cfg_obj(cfg_file)
    _proposal(cfg, "DONE", status="applied")
    _proposal(cfg, "EMPTY", body=" ")
    backend = FakeBackend([])
    _wire(monkeypatch, backend)
    done = runner.invoke(cli.app, ["htmlpdf", "proposals", "apply", "DONE", "--config", str(cfg_file)])
    assert done.exit_code == 1 and "is applied" in done.output
    empty = runner.invoke(cli.app, ["htmlpdf", "proposals", "apply", "EMPTY", "--config", str(cfg_file)])
    assert empty.exit_code == 1 and "failed the page gate" in empty.output
    assert backend.attached == []


def test_htmlpdf_apply_missing_pdf_and_attach_failure(cfg_file, monkeypatch):
    cfg = _cfg_obj(cfg_file)
    _proposal(cfg, "NOPDF")
    (proposals_dir(cfg) / "NOPDF.pdf").unlink()
    _proposal(cfg, "BAD")
    _wire(monkeypatch, FakeBackend([], attach_ok=False))
    missing = runner.invoke(cli.app, ["htmlpdf", "proposals", "apply", "NOPDF", "--config", str(cfg_file)])
    assert missing.exit_code == 1 and "missing a PDF" in missing.output
    bad = runner.invoke(cli.app, ["htmlpdf", "proposals", "apply", "BAD", "--config", str(cfg_file)])
    assert bad.exit_code == 1 and "zotero said no" in bad.output
    data = json.loads((proposals_dir(cfg) / "BAD.json").read_text(encoding="utf-8"))
    assert data["status"] == "pending"  # a failed attach does not consume the proposal
