"""Simple vs advanced Ask: mode switch, evidence scoring, retries, citation hops."""

from __future__ import annotations

import json

import pytest

from paperful.config import Config
from paperful.llm.client import LLMClientError
from paperful.rag.answer import NO_HITS, answer, looks_insufficient
from paperful.rag.cites import neighbor_keys
from paperful.rag.evidence import expand_queries, filter_evidence, summarize_hits
from paperful.rag.ledger import Ledger, LedgerRow
from paperful.rag.mode import resolve_ask_mode
from paperful.rag.prompt import CITE_CURRENT_ONLY, build_context, build_messages
from paperful.rag.retrieve import Hit, mmr_select, rrf_merge, search
from tests.ragfakes import FakeEmbedder, StubChat, TextFileParser, add_item

pytest.importorskip("lancedb")


def _hit(key="AAAA1111", text="Krill eat algae.", **over) -> Hit:
    base = dict(
        item_key=key,
        chunk_index=0,
        text=text,
        score=0.9,
        page_start=3,
        page_end=4,
        title="Krill in winter",
        authors=["Chen"],
        year=2019,
    )
    base.update(over)
    return Hit(**base)


def test_resolve_ask_mode_override_wins():
    cfg = Config()
    assert resolve_ask_mode(cfg) == "simple"
    cfg.rag_ask_mode = "advanced"
    assert resolve_ask_mode(cfg) == "advanced"
    assert resolve_ask_mode(cfg, "simple") == "simple"
    assert resolve_ask_mode(cfg, "") == "advanced"


def test_looks_insufficient():
    assert looks_insufficient(NO_HITS)
    assert looks_insufficient("The excerpts do not answer the question.")
    assert not looks_insufficient("Krill eat algae [S1].")


def test_rrf_and_mmr_helpers():
    a = _hit("A", chunk_index=0, score=0.9, vector=[1.0, 0.0])
    b = _hit("B", chunk_index=0, score=0.8, vector=[0.0, 1.0])
    c = _hit("A", chunk_index=1, score=0.7, vector=[0.9, 0.1])
    fused = rrf_merge([[a, b], [b, c]], k=3)
    assert [h.item_key for h in fused][0] in {"A", "B"}
    diverse = mmr_select([a, c, b], k=2, lambda_=0.0)
    assert {h.item_key for h in diverse} == {"A", "B"}
    assert mmr_select([a, b], k=2, lambda_=1.0) == [a, b]


def test_advanced_headers_and_cite_current_only():
    hits = [
        _hit(
            publication_title="Polar Biology",
            doi="10.1/krill",
            item_type="journalArticle",
            summary="Krill graze algae under ice.",
        )
    ]
    simple, _ = build_context(hits, 10_000)
    adv, _ = build_context(hits, 10_000, extra_headers=True, prefer_summary=True)
    assert "Polar Biology" not in simple
    assert "doi:10.1/krill" in adv
    assert "journalArticle" in adv
    assert "Krill graze algae under ice." in adv
    history = (
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1 [S1]."},
    )
    simple_msgs = build_messages("q2", "[S1] ctx", history)
    adv_msgs = build_messages("q2", "[S1] ctx", history, cite_current_only=True)
    assert CITE_CURRENT_ONLY not in simple_msgs[0]["content"]
    assert CITE_CURRENT_ONLY in adv_msgs[0]["content"]


def test_filter_evidence_cutoff_and_source_cap():
    cfg = Config()
    cfg.rag_relevance_cutoff = 1
    cfg.rag_answer_max_sources = 1
    cfg.rag_max_chunks_per_item = 2
    hits = [
        _hit("A", text="one", relevance_score=8),
        _hit("A", text="two", chunk_index=1, relevance_score=7),
        _hit("B", text="other", relevance_score=9),
        _hit("C", text="zero", relevance_score=0),
    ]
    kept = filter_evidence(cfg, hits)
    assert [h.item_key for h in kept] == ["A", "A"]


def test_summarize_cache_and_failed_fallback(tmp_path):
    cfg = Config(state_dir=tmp_path / "state")
    cfg.state_dir.mkdir()
    cfg.rag_summary_concurrency = 1
    cfg.rag_evidence_fallback = "raw"
    hits = [_hit()]
    chat = StubChat(json_replies=[{"summary": "Scored krill.", "relevance_score": 9}])
    first = summarize_hits(cfg, hits, "What do krill eat?", chat)
    assert first[0].summary == "Scored krill." and first[0].relevance_score == 9
    assert len(chat.json_requests) == 1
    again = summarize_hits(cfg, hits, "What do krill eat?", chat)
    assert again[0].summary == "Scored krill."
    assert len(chat.json_requests) == 1
    fail = StubChat(error="boom")
    cfg.rag_dir.mkdir(parents=True, exist_ok=True)
    other = [_hit("BBBB2222", text="Seabed mining.")]
    # different question → new cache key; error falls back to raw
    cfg2 = Config(state_dir=tmp_path / "state2")
    cfg2.state_dir.mkdir()
    cfg2.rag_summary_concurrency = 1
    cfg2.rag_evidence_fallback = "raw"
    scored = summarize_hits(cfg2, other, "mining?", fail)
    assert scored[0].summary == "Seabed mining." and scored[0].relevance_score == 1


def test_neighbor_keys_from_local_graph(tmp_path):
    cfg = Config(state_dir=tmp_path / "state")
    graph = cfg.state_dir / "snowball" / "run1" / "citation_graph.json"
    graph.parent.mkdir(parents=True)
    graph.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "W1", "item_key": "AAAA1111"},
                    {"id": "W2", "item_key": "BBBB2222"},
                    {"id": "W3", "item_key": "CCCC3333"},
                ],
                "edges": [{"source": "W1", "target": "W2", "direction": "refs"}],
            }
        )
    )
    ledger = Ledger(tmp_path / "ingest.jsonl")
    ledger.write(LedgerRow(key="AAAA1111"))
    ledger.write(LedgerRow(key="BBBB2222"))
    found, skip = neighbor_keys(cfg, {"AAAA1111"}, ledger)
    assert skip == "" and found == {"BBBB2222"}
    empty_cfg = Config(state_dir=tmp_path / "empty")
    found, skip = neighbor_keys(empty_cfg, {"AAAA1111"}, ledger)
    assert skip == "no local graph" and found == set()


@pytest.fixture
def built(cfg):
    cfg.rag_enabled = True
    cfg.rag_hybrid = False
    cfg.rag_chunk_chars, cfg.rag_chunk_overlap = 300, 0
    cfg.rag_summary_concurrency = 1
    cfg.out_dir.mkdir(parents=True)
    add_item(cfg, "AAAA1111", pdf="Krill swarm under the winter sea ice and feed on algae. " * 12)
    add_item(
        cfg,
        "BBBB2222",
        collection="law",
        title="Seabed mining",
        author="Silva",
        year=2021,
        pdf="Seabed mining licences and royalties are set by the Authority. " * 8,
    )
    from paperful.rag.index import Index, ledger_path
    from paperful.rag.ingest import ingest_entries, select_entries
    from paperful.rag.ledger import Ledger

    embedder = FakeEmbedder()
    ingest_entries(
        cfg,
        select_entries(cfg),
        embedder=embedder,
        parser=TextFileParser(),
        ocr_available=lambda: False,
    )
    return {
        "cfg": cfg,
        "embedder": embedder,
        "index": Index.open(cfg),
        "ledger": Ledger(ledger_path(cfg)),
    }


def _tools(built):
    return {k: built[k] for k in ("embedder", "index", "ledger")}


def test_simple_mode_is_one_chat_call(built):
    chat = StubChat()
    reply = answer(built["cfg"], "What do krill eat?", client=chat, **_tools(built))
    reply.read()
    assert reply.ask_mode == "simple"
    assert chat.json_requests == []
    assert len(chat.requests) == 1
    assert CITE_CURRENT_ONLY not in chat.requests[0].messages[0]["content"]
    user = chat.requests[0].messages[-1]["content"]
    assert "doi:" not in user


def test_config_advanced_loses_to_per_run_simple(built):
    cfg = built["cfg"]
    cfg.rag_ask_mode = "advanced"
    chat = StubChat()
    reply = answer(cfg, "What do krill eat?", client=chat, ask_mode="simple", **_tools(built))
    reply.read()
    assert reply.ask_mode == "simple"
    assert chat.json_requests == []


def test_advanced_scores_then_answers(built):
    cfg = built["cfg"]
    chat = StubChat(
        json_replies=[
            {"summary": "Krill graze ice algae.", "relevance_score": 9},
            {"summary": "", "relevance_score": 0},
        ]
        + [{"summary": "also relevant", "relevance_score": 6}] * 20
    )
    reply = answer(
        cfg, "What do krill eat?", client=chat, ask_mode="advanced", **_tools(built)
    )
    text = reply.read()
    assert reply.ask_mode == "advanced"
    assert reply.evidence["candidates"] >= 1
    assert reply.evidence["kept"] >= 1
    assert len(chat.json_requests) == reply.evidence["candidates"]
    assert len(chat.requests) == 1
    user = chat.requests[0].messages[-1]["content"]
    assert "Krill graze ice algae." in user
    assert text


def test_advanced_follow_up_cites_this_turn_only(built):
    chat = StubChat()
    first = answer(
        built["cfg"], "What do krill eat?", client=chat, ask_mode="advanced", **_tools(built)
    )
    first.read()
    follow = answer(
        built["cfg"],
        "And in summer?",
        history=first.turns("What do krill eat?"),
        client=chat,
        ask_mode="advanced",
        **_tools(built),
    )
    follow.read()
    assert CITE_CURRENT_ONLY in chat.requests[-1].messages[0]["content"]


def test_search_respects_max_chunks_per_item_config(built):
    cfg = built["cfg"]
    cfg.rag_max_chunks_per_item = 1
    hits = search(cfg, "krill under ice", k=10, **_tools(built))
    by_key: dict[str, int] = {}
    for hit in hits:
        by_key[hit.item_key] = by_key.get(hit.item_key, 0) + 1
    assert all(n <= 1 for n in by_key.values())


def test_simple_ignores_advanced_knobs(built):
    cfg = built["cfg"]
    cfg.rag_query_variants = 4
    cfg.rag_cite_hops = 1
    cfg.rag_insufficient_retries = 1
    cfg.rag_mmr_lambda = 0.5
    chat = StubChat()
    reply = answer(cfg, "What do krill eat?", client=chat, **_tools(built))
    reply.read()
    assert reply.ask_mode == "simple"
    assert chat.json_requests == []
    assert len(chat.requests) == 1


def test_expand_queries_adds_and_falls_back():
    cfg = Config()
    chat = StubChat(json_replies=[{"queries": ["krill diet", "What do krill eat?"]}])
    out = expand_queries(cfg, "What do krill eat?", chat, 3)
    assert out[0] == "What do krill eat?"
    assert "krill diet" in out
    fail = StubChat(error="boom")
    assert expand_queries(cfg, "What do krill eat?", fail, 3) == ["What do krill eat?"]


def test_advanced_query_variants_search_extra_phrasing(built):
    cfg = built["cfg"]
    cfg.rag_query_variants = 2
    cfg.rag_summary_concurrency = 1
    chat = StubChat(
        json_replies=[{"queries": ["krill algae ice"]}]
        + [{"summary": "relevant", "relevance_score": 8}] * 20
    )
    reply = answer(
        cfg, "What do krill eat?", client=chat, ask_mode="advanced", **_tools(built)
    )
    reply.read()
    assert chat.json_requests
    assert "krill algae ice" in chat.json_requests[0].prompt or any(
        "queries" in (getattr(r, "prompt", "") or "") for r in chat.json_requests
    )


def test_advanced_cite_hops_adds_in_library_neighbour(built, tmp_path):
    cfg = built["cfg"]
    cfg.rag_cite_hops = 1
    cfg.rag_cite_scope = "library"
    cfg.rag_summary_concurrency = 1
    graph = cfg.state_dir / "snowball" / "run1" / "citation_graph.json"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "W1", "item_key": "AAAA1111"},
                    {"id": "W2", "item_key": "BBBB2222"},
                ],
                "edges": [{"source": "W1", "target": "W2", "direction": "refs"}],
            }
        )
    )
    chat = StubChat(
        json_replies=[{"summary": "Krill graze ice algae.", "relevance_score": 9}] * 20
    )
    reply = answer(
        cfg,
        "What do krill eat?",
        client=chat,
        ask_mode="advanced",
        keys={"AAAA1111"},
        **_tools(built),
    )
    reply.read()
    keys = {h.item_key for h in reply.hits}
    assert "AAAA1111" in keys
    assert "BBBB2222" in keys


def test_advanced_insufficient_retry_rewrites(built, monkeypatch):
    cfg = built["cfg"]
    cfg.rag_insufficient_retries = 1
    cfg.rag_summary_concurrency = 1
    rewrites = {"n": 0}

    def fake_rewrite(_cfg, question, history, client=None):
        rewrites["n"] += 1
        return "krill diet under winter ice"

    monkeypatch.setattr("paperful.rag.thread.rewrite_query", fake_rewrite)
    chat = StubChat(pieces=["The excerpts do not contain enough information."])
    reply = answer(
        cfg, "What do whales eat?", client=chat, ask_mode="advanced", **_tools(built)
    )
    reply.read()
    assert rewrites["n"] == 1
