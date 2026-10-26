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


def test_run_ask_empty_and_disabled(cfg):
    from paperful.agent_ops import run_ask

    empty = run_ask(cfg, "  ")
    assert empty["summary"]["error"] == "question is required"
    cfg.rag_enabled = False
    off = run_ask(cfg, "What do krill eat?")
    assert "rag.enabled" in off["summary"]["error"]


def test_run_ask_success(cfg, monkeypatch):
    from paperful.agent_ops import run_ask

    cfg.rag_enabled = True

    class Reply:
        def read(self):
            return "Krill eat algae."

        def cited(self):
            return []

        sources = [SimpleNamespace(marker="1", item_key="K", title="T")]
        ask_mode = "simple"
        evidence = []

    monkeypatch.setattr("paperful.rag.index.Index.open", lambda _c: SimpleNamespace())
    monkeypatch.setattr(
        "paperful.rag.index.ledger_path", lambda _c: cfg.state_dir / "l"
    )

    class Ledger:
        def __init__(self, *_a, **_k):
            pass

    monkeypatch.setattr("paperful.rag.ledger.Ledger", Ledger)
    monkeypatch.setattr("paperful.rag.retrieve.scope_keys", lambda *_a, **_k: ["K"])
    monkeypatch.setattr(
        "paperful.rag.mode.resolve_ask_mode", lambda *_a, **_k: "simple"
    )
    monkeypatch.setattr("paperful.rag.answer.answer", lambda *_a, **_k: Reply())
    env = run_ask(cfg, "What do krill eat?", collection="BBNJ", ask_mode="simple")
    assert not env.get("summary", {}).get("error"), env
    assert env["items"], env
    assert env["items"][0]["answer"].startswith("Krill")


def test_run_export_validates_format_and_scope(cfg):
    from paperful.agent_ops import run_export

    bad = run_export(cfg, collection="BBNJ", kind="csv")
    assert "format" in bad["summary"]["error"]
    missing = run_export(cfg, collection="", library=False, kind="ris")
    assert "collection" in missing["summary"]["error"]


def test_snowball_search_requires_query(cfg):
    from paperful.agent_ops import run_snowball_search

    env = run_snowball_search(cfg, "  ")
    assert env["summary"]["error"] == "query is required"


def test_collections_add_exit_codes():
    assert collections_add_exit(apply=False, added=0, failed=0) == 0
    assert collections_add_exit(apply=True, added=2, failed=0) == 0
    assert collections_add_exit(apply=True, added=1, failed=1) == 3
