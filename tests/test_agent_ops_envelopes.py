"""Pure envelope builders in ``agent_ops``."""

from __future__ import annotations

from types import SimpleNamespace

from paperful.agent_ops import ask_envelope, collections_add_exit, refs_gap_envelope


def test_refs_gap_envelope_orders_by_citations():
    refs = [
        SimpleNamespace(
            doi="10.2/b",
            title="B",
            citing_keys=["a"],
            already_exists=False,
            suggested_action="add",
        ),
        SimpleNamespace(
            doi="10.1/a",
            title="A",
            citing_keys=["a", "b", "c"],
            already_exists=False,
            suggested_action="add",
        ),
        SimpleNamespace(
            doi="10.0/c",
            title="C",
            citing_keys=[],
            already_exists=True,
            suggested_action="skip",
        ),
    ]
    env = refs_gap_envelope(refs=refs, findings=[], folder="/tmp/pack")
    assert env["summary"]["missing"] == 2
    assert env["items"][0]["doi"] == "10.1/a"


def test_ask_envelope_carries_items():
    env = ask_envelope(items=[{"q": "why"}], summary={"hits": 1})
    assert env["items"][0]["q"] == "why"
    assert env["summary"]["hits"] == 1


def test_collections_add_exit_codes():
    assert collections_add_exit(apply=False, added=0, failed=0) == 0
    assert collections_add_exit(apply=True, added=2, failed=0) == 0
    assert collections_add_exit(apply=True, added=1, failed=1) == 3
