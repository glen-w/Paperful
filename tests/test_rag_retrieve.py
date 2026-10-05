"""Retrieval, the grounded prompt, citations, and the answer stream."""

from __future__ import annotations

import pytest

from paperful.llm.client import LLMClientError
from paperful.rag.answer import NO_HITS, answer
from paperful.rag.index import Index, ledger_path
from paperful.rag.ingest import ingest_entries, select_entries
from paperful.rag.ledger import Ledger, LedgerRow
from paperful.rag.prompt import (
    SYSTEM_PROMPT,
    Source,
    build_context,
    build_messages,
    cited_markers,
)
from paperful.rag.retrieve import MAX_CHUNKS_PER_ITEM, Hit, scope_keys, search
from tests.ragfakes import BODY, FakeEmbedder, StubChat, TextFileParser, add_item

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


# ---- Hit and Source ----------------------------------------------------------


def test_hit_pages():
    assert _hit().pages == "pp. 3-4"
    assert _hit(page_end=3).pages == "p. 3"
    assert _hit(page_start=None, page_end=None, source="abstract").pages == "abstract"
    assert _hit(page_start=None, page_end=None).pages == ""


@pytest.mark.parametrize(
    ("authors", "year", "label"),
    [
        (["Chen"], 2019, "Chen (2019)"),
        (["Chen", "Silva"], 2019, "Chen & Silva (2019)"),
        (["Chen", "Silva", "Okafor"], 2019, "Chen et al. (2019)"),
        ([], None, "Unknown (n.d.)"),
    ],
)
def test_source_citation(authors, year, label):
    assert Source("S1", "K", "T", authors, year).citation == label


# ---- prompt ------------------------------------------------------------------


def test_build_context_gives_one_marker_per_paper():
    hits = [
        _hit("AAAA1111", "First passage."),
        _hit("BBBB2222", "Other paper.", title="Whales", authors=["Silva", "Okafor"]),
        _hit("AAAA1111", "Second passage.", page_start=9, page_end=9, section="Results"),
    ]
    context, sources = build_context(hits, max_chars=10_000)
    assert [s.marker for s in sources] == ["S1", "S2"]
    assert sources[0].pages == ["pp. 3-4", "p. 9"]
    blocks = context.split("\n\n")
    assert blocks[0] == "[S1] Chen (2019), Krill in winter, pp. 3-4\nFirst passage."
    assert blocks[1].startswith("[S2] Silva & Okafor (2019), Whales, pp. 3-4\n")
    assert blocks[2] == "[S1] Chen (2019), Krill in winter, p. 9 (Results)\nSecond passage."


def test_build_context_stops_at_the_budget_but_keeps_the_first():
    hits = [_hit("AAAA1111", "x" * 500), _hit("BBBB2222", "y" * 500)]
    context, sources = build_context(hits, max_chars=600)
    assert "y" * 500 not in context and [s.item_key for s in sources] == ["AAAA1111"]
    context, sources = build_context(hits, max_chars=10)
    assert "x" * 500 in context and len(sources) == 1
    assert build_context([], 100) == ("", [])


def test_build_messages_puts_history_between_rules_and_question():
    history = (
        {"role": "user", "content": "What do krill eat?"},
        {"role": "assistant", "content": "Algae [S1]."},
    )
    messages = build_messages(" And whales? ", "[S1] ctx", history)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["content"] == "What do krill eat?"
    assert messages[-1]["content"] == "Excerpts:\n\n[S1] ctx\n\nQuestion: And whales?"
    assert len(build_messages("q", "c")) == 2


@pytest.mark.parametrize(
    ("text", "markers"),
    [
        ("Krill eat algae [S1]. Whales eat krill [S2][S1].", ["S1", "S2"]),
        ("Grouped [S3, S1] and spaced [ S2 ].", ["S3", "S1", "S2"]),
        ("The S1 protein and section S2 are prose, not citations.", []),
        ("(Chen 2019) [S10] then [S1].", ["S10", "S1"]),
        ("[see Chen] [XS1] [S]", []),
        ("", []),
    ],
)
def test_cited_markers(text, markers):
    assert cited_markers(text) == markers


# ---- scope_keys --------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path):
    ledger = Ledger(tmp_path / "ingest.jsonl")
    ledger.write(
        LedgerRow(key="A", year=2015, item_type="journalArticle", dirs=["ocean/BBNJ/x -- A"])
    )
    ledger.write(
        LedgerRow(
            key="B",
            year=2021,
            item_type="book",
            dirs=["law/y -- B", "oceanography/y -- B"],
        )
    )
    ledger.write(LedgerRow(key="C", year=None, item_type="report", dirs=["z -- C"]))
    return ledger


def test_scope_keys_none_without_filters(ledger):
    assert scope_keys(ledger) is None
    assert scope_keys(ledger, collections=[], item_keys=[]) is None


def test_scope_keys_filters(ledger):
    assert scope_keys(ledger, collections=["ocean"]) == {"A"}
    assert scope_keys(ledger, collections=["ocean/BBNJ/", "law"]) == {"A", "B"}
    assert scope_keys(ledger, item_keys=["B", "ZZ"]) == {"B"}
    assert scope_keys(ledger, year_from=2016) == {"B"}
    assert scope_keys(ledger, year_to=2015) == {"A"}
    assert scope_keys(ledger, item_types=frozenset({"report"})) == {"C"}
    assert scope_keys(ledger, collections=["nowhere"]) == set()


# ---- search and answer over a real index -------------------------------------


@pytest.fixture
def built(cfg):
    cfg.rag_enabled = True
    cfg.rag_hybrid = False
    cfg.rag_chunk_chars, cfg.rag_chunk_overlap = 300, 0
    cfg.out_dir.mkdir(parents=True)
    add_item(cfg, "AAAA1111", pdf=BODY * 3)  # several passages
    add_item(
        cfg,
        "BBBB2222",
        collection="law",
        title="Seabed mining",
        author="Silva",
        year=2021,
        pdf="Seabed mining licences and royalties are set by the Authority. " * 4,
    )
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


def test_search_joins_metadata_and_caps_passages_per_item(built):
    hits = search(built["cfg"], "krill under ice", k=10, **_tools(built))
    by_key: dict[str, list[Hit]] = {}
    for hit in hits:
        by_key.setdefault(hit.item_key, []).append(hit)
    assert set(by_key) == {"AAAA1111", "BBBB2222"}
    assert len(by_key["AAAA1111"]) == MAX_CHUNKS_PER_ITEM
    silva = by_key["BBBB2222"][0]
    assert (silva.title, silva.authors, silva.year) == ("Seabed mining", ["Silva"], 2021)
    assert silva.page_start == 1 and silva.source == "pdf"
    assert hits == sorted(hits, key=lambda h: -h.score)
    assert built["embedder"].queries[-1] == "krill under ice"


def test_search_respects_k_scope_and_empty_queries(built):
    cfg = built["cfg"]
    assert len(search(cfg, "krill", k=2, **_tools(built))) == 2
    scoped = search(cfg, "krill", k=5, keys={"BBBB2222"}, **_tools(built))
    assert {h.item_key for h in scoped} == {"BBBB2222"}
    assert search(cfg, "krill", keys=set(), **_tools(built)) == []
    assert search(cfg, "   ", **_tools(built)) == []
    cfg.rag_top_k = 1
    assert len(search(cfg, "krill", **_tools(built))) == 1


def test_answer_streams_and_reports_cited_sources(built):
    chat = StubChat(pieces=["Krill eat ", "algae [S1]", ". Mining pays royalties [S2]."])
    reply = answer(built["cfg"], "What do krill eat?", client=chat, **_tools(built))
    assert {s.marker for s in reply.sources} == {"S1", "S2"}
    assert reply.text == ""
    pieces = list(reply)
    assert pieces == chat.pieces and reply.text == "".join(chat.pieces)
    assert [s.marker for s in reply.cited()] == ["S1", "S2"]
    request = chat.requests[0]
    assert request.model == "qwen2.5:7b"
    assert request.messages[0]["role"] == "system"
    user = request.messages[-1]["content"]
    assert user.endswith("Question: What do krill eat?") and "[S1] " in user
    assert request.num_ctx and request.num_ctx >= 1024


def test_answer_uses_rag_model_and_passes_history(built):
    cfg = built["cfg"]
    cfg.rag_model = "qwen3:8b"
    chat = StubChat()
    first = answer(cfg, "What do krill eat?", client=chat, **_tools(built))
    first.read()
    follow = answer(
        cfg, "And in summer?", history=first.turns("What do krill eat?"), client=chat, **_tools(built)
    )
    follow.read()
    request = chat.requests[1]
    assert request.model == "qwen3:8b"
    assert [m["role"] for m in request.messages] == ["system", "user", "assistant", "user"]
    assert request.messages[1]["content"] == "What do krill eat?"
    assert request.messages[2]["content"] == first.text
    # Retrieval uses the new question alone.
    assert built["embedder"].queries[-1] == "And in summer?"


def test_answer_retrieves_on_retrieve_as_keeps_the_question(built):
    chat = StubChat()
    reply = answer(
        built["cfg"],
        "and the EIA part?",
        retrieve_as="BBNJ EIA procedure",
        client=chat,
        **_tools(built),
    )
    reply.read()
    assert built["embedder"].queries[-1] == "BBNJ EIA procedure"
    assert chat.requests[0].messages[-1]["content"].endswith("Question: and the EIA part?")


def test_answer_ignores_markers_that_were_not_offered(built):
    chat = StubChat(pieces=["Invented [S9] and real [S1]."])
    reply = answer(built["cfg"], "krill", client=chat, **_tools(built))
    reply.read()
    assert [s.marker for s in reply.cited()] == ["S1"]


def test_answer_without_hits_does_not_call_the_model(built):
    chat = StubChat()
    reply = answer(built["cfg"], "krill", keys=set(), client=chat, **_tools(built))
    assert reply.read() == NO_HITS and reply.sources == [] and chat.requests == []


def test_answer_surfaces_model_errors_on_iteration(built):
    reply = answer(built["cfg"], "krill", client=StubChat(error="model crashed"), **_tools(built))
    with pytest.raises(LLMClientError, match="model crashed"):
        reply.read()


def test_context_budget_limits_sources_and_hits(built):
    cfg = built["cfg"]
    cfg.rag_max_context_chars = 1000
    chat = StubChat()
    reply = answer(cfg, "krill under ice", k=6, client=chat, **_tools(built))
    assert len(reply.sources) == 1
    assert {h.item_key for h in reply.hits} == {reply.sources[0].item_key}
