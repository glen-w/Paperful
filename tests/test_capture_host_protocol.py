"""Native-messaging framing and serve loop for the Firefox capture host (no browser, no library)."""

from __future__ import annotations

import io
import json
import struct

import pytest

from paperful import capture_host as host
from paperful.config import Config


class _Std:
    def __init__(self, data: bytes = b""):
        self.buffer = io.BytesIO(data)


def _frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return struct.pack("<I", len(body)) + body


@pytest.fixture
def stdio(monkeypatch):
    def install(data: bytes):
        sin, sout, serr = _Std(data), _Std(), io.StringIO()
        monkeypatch.setattr(host.sys, "stdin", sin)
        monkeypatch.setattr(host.sys, "stdout", sout)
        monkeypatch.setattr(host.sys, "stderr", serr)
        return sout.buffer, serr

    return install


def _replies(raw: bytes) -> list[dict]:
    out, buf = [], io.BytesIO(raw)
    while True:
        head = buf.read(4)
        if not head:
            return out
        (size,) = struct.unpack("<I", head)
        out.append(json.loads(buf.read(size)))


# --- _read_frame --------------------------------------------------------------------


def test_read_frame_round_trips_a_message(stdio):
    stdio(_frame({"type": "hello", "id": 3}))
    assert host._read_frame() == {"type": "hello", "id": 3}
    assert host._read_frame() is None  # clean EOF


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\x01\x00", {"type": "invalid"}),  # truncated length prefix
        (struct.pack("<I", 0), {"type": "oversize"}),
        (struct.pack("<I", host.MAX_MSG + 1), {"type": "oversize"}),
        (struct.pack("<I", 10) + b"abc", {"type": "invalid"}),  # body shorter than declared
        (struct.pack("<I", 4) + b"\xff\xfe\xfd\xfc", {"type": "invalid"}),  # not UTF-8
        (struct.pack("<I", 5) + b"{nope", {"type": "invalid"}),  # not JSON
        (struct.pack("<I", 7) + b"[1,2,3]", {"type": "invalid"}),  # JSON but not an object
    ],
)
def test_read_frame_flags_bad_input_instead_of_raising(stdio, raw, expected):
    stdio(raw)
    assert host._read_frame() == expected


def test_read_frame_never_reads_more_than_the_declared_size(stdio):
    stdio(_frame({"type": "a"}) + _frame({"type": "b"}))
    assert host._read_frame()["type"] == "a"
    assert host._read_frame()["type"] == "b"


# --- _write_frame -------------------------------------------------------------------


def test_write_frame_prefixes_length_and_keeps_unicode(stdio):
    out, _err = stdio(b"")
    host._write_frame({"ok": True, "title": "café ☕"})
    assert _replies(out.getvalue()) == [{"ok": True, "title": "café ☕"}]


def test_write_frame_replaces_oversize_payloads(stdio):
    out, _err = stdio(b"")
    host._write_frame({"ok": True, "blob": "x" * (host.MAX_MSG + 10)})
    assert _replies(out.getvalue()) == [{"ok": False, "reason": "too_large"}]


# --- id echo + clipping -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("req_id", "echoed"),
    [(7, True), (1, True), (999_999_999, True), (0, False), (-1, False), (1_000_000_000, False),
     (True, False), ("7", False), (None, False), (1.5, False)],
)
def test_echo_id_only_for_small_positive_ints(req_id, echoed):
    reply = host._echo_id({"id": req_id}, {"ok": True})
    assert ("id" in reply) is echoed
    assert reply["ok"] is True


def test_echo_id_without_id_key():
    assert host._echo_id({}, {"ok": False}) == {"ok": False}


def test_clip_message_bounds_every_untrusted_field():
    huge = "x" * 50_000
    msg = {
        "type": "capture.plan",
        "doi": huge, "url": huge, "title": huge, "abstract": huge, "note": huge,
        "collection": huge, "confirm_key": huge, "key": huge, "target": huge,
        "authors": [huge] * 50,
        "tags": [huge] * 500,
        "keys": [huge] * 1000,
        "page": {"doi": huge, "url": huge, "title": huge, "authors": [huge] * 50, "abstract": huge},
        "unrelated": "kept",
    }
    out = host._clip_message(msg)
    for key in ("doi", "url", "title", "abstract", "note", "collection", "confirm_key", "key", "target"):
        assert len(out[key]) < len(huge), key
    assert len(out["authors"]) == 20 and all(len(a) <= host.AUTHOR_MAX + 5 for a in out["authors"])
    assert len(out["keys"]) == 200 and all(len(k) <= 64 + 5 for k in out["keys"])
    assert len(out["tags"]) < 500
    page = out["page"]
    assert len(page["doi"]) < len(huge) and len(page["authors"]) == 20
    assert out["unrelated"] == "kept"
    assert msg["doi"] == huge  # the original message is not mutated
    assert host._clip_message({"authors": None})["authors"] is None


def test_clip_message_leaves_missing_and_none_fields_alone():
    assert host._clip_message({"doi": None, "type": "x"}) == {"doi": None, "type": "x"}
    assert host._clip_message({"page": "not-a-dict"})["page"] == "not-a-dict"


# --- handle_message + serve loop ---------------------------------------------------------


@pytest.fixture
def cfg(tmp_path):
    return Config(out_dir=tmp_path / "out", state_dir=tmp_path / "state")


@pytest.mark.parametrize("kind", ["invalid", "oversize"])
def test_handle_message_rejects_framing_errors(cfg, kind):
    assert host.handle_message(cfg, {"type": kind, "id": 4}, []) == {"ok": False, "reason": "invalid", "id": 4}


def test_handle_message_unknown_type_is_not_executed(cfg):
    reply = host.handle_message(cfg, {"type": "rm -rf /", "id": 2}, [])
    assert reply == {"ok": False, "reason": "unknown", "id": 2}
    assert host.handle_message(cfg, {}, []) == {"ok": False, "reason": "unknown"}


def test_handle_message_mark_ignores_non_list_keys(cfg, monkeypatch):
    seen: list = []
    monkeypatch.setattr(host, "mark_session_saved", lambda c, keys: seen.append(keys) or {"ok": True})
    host.handle_message(cfg, {"type": "handoff.mark", "keys": "K1"}, [])
    host.handle_message(cfg, {"type": "handoff.mark", "keys": ["K1"]}, [])
    assert seen == [[], ["K1"]]


def test_handle_message_plan_prepares_the_index_once_and_clips(cfg, monkeypatch):
    prepared: list[int] = []
    planned: list[dict] = []
    monkeypatch.setattr(host, "prepare", lambda c: prepared.append(1) or "INDEX")

    def fake_plan(c, **kw):
        planned.append(kw)
        return {"ok": True}

    monkeypatch.setattr(host, "plan_page", fake_plan)
    index: list = []
    msg = {"type": "capture.plan", "doi": "10.1/x", "page": {"url": "https://p.test", "title": "T", "year": "2021"}}
    host.handle_message(cfg, msg, index)
    host.handle_message(cfg, msg, index)
    assert prepared == [1] and index == ["INDEX"]
    assert planned[0]["doi"] == "10.1/x" and planned[0]["url"] == "https://p.test"
    assert planned[0]["year"] == 2021 and planned[0]["index"] == "INDEX"


def test_serve_stdio_answers_each_frame_and_stops_at_eof(cfg, stdio, monkeypatch):
    monkeypatch.setattr(host, "hello_payload", lambda c: {"ok": True, "hello": True})
    out, _err = stdio(_frame({"type": "hello", "id": 1}) + _frame({"type": "nope", "id": 2}))
    host.serve_stdio(cfg)
    assert _replies(out.getvalue()) == [
        {"ok": True, "hello": True, "id": 1},
        {"ok": False, "reason": "unknown", "id": 2},
    ]


def test_serve_stdio_keeps_handler_prints_off_the_protocol_stream(cfg, stdio, monkeypatch):
    def chatty(c, msg, index):
        print("LOG LINE THAT MUST NOT REACH FIREFOX")
        return {"ok": True}

    monkeypatch.setattr(host, "handle_message", chatty)
    out, err = stdio(_frame({"type": "hello"}))
    host.serve_stdio(cfg)
    assert _replies(out.getvalue()) == [{"ok": True}]
    assert b"LOG LINE" not in out.getvalue()
    assert "LOG LINE THAT MUST NOT REACH FIREFOX" in err.getvalue()


def test_serve_stdio_ends_the_session_on_an_oversize_frame(cfg, stdio):
    out, _err = stdio(struct.pack("<I", host.MAX_MSG + 1) + _frame({"type": "hello"}))
    host.serve_stdio(cfg)
    assert _replies(out.getvalue()) == [{"ok": False, "reason": "invalid"}]  # later frames are never read
