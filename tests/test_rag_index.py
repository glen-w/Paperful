"""The LanceDB wrapper, against a real table in tmp_path."""

from __future__ import annotations

import builtins
import math

import pytest

from paperful.rag.index import (
    Index,
    IndexMismatch,
    IndexMissing,
    RagUnavailable,
    index_dir,
    ledger_path,
    load_meta,
)

pytest.importorskip("lancedb")

DIM = 4


def _unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def _rows(key: str, texts_and_vectors) -> list[dict]:
    return [
        {
            "chunk_id": f"{key}:{i}",
            "item_key": key,
            "chunk_index": i,
            "source": "pdf",
            "section": None,
            "page_start": i + 1,
            "page_end": i + 1,
            "text": text,
            "vector": vector,
        }
        for i, (text, vector) in enumerate(texts_and_vectors)
    ]


@pytest.fixture
def rag_cfg(cfg):
    cfg.rag_enabled = True
    return cfg


@pytest.fixture
def index(rag_cfg):
    idx = Index.open(rag_cfg, dim=DIM, create=True)
    idx.replace_item(
        "AAAA1111",
        _rows(
            "AAAA1111",
            [
                ("Krill swarm near the ice edge in winter.", _unit(1, 0, 0, 0)),
                ("Whales follow the krill swarms south.", _unit(0.9, 0.1, 0, 0)),
            ],
        ),
    )
    idx.replace_item(
        "BBBB2222",
        _rows("BBBB2222", [("Seabed mining licences and royalties.", _unit(0, 0, 1, 0))]),
    )
    return idx


def test_paths_follow_the_embedding_model(rag_cfg):
    folder = rag_cfg.state_dir / "rag" / "ollama__nomic-embed-text"
    assert index_dir(rag_cfg) == folder
    assert ledger_path(rag_cfg) == folder / "ingest.jsonl"
    rag_cfg.rag_embed_model = "bge-m3"
    assert index_dir(rag_cfg).name == "ollama__bge-m3"


def test_open_without_an_index_is_missing(rag_cfg):
    with pytest.raises(IndexMissing, match="paperful rag ingest"):
        Index.open(rag_cfg)
    assert not index_dir(rag_cfg).exists()


def test_create_writes_meta_and_reopens(rag_cfg, index):
    meta = load_meta(rag_cfg)
    assert meta["model"] == "nomic-embed-text" and meta["dim"] == DIM
    assert meta["doc_prefix"] == "search_document: "
    again = Index.open(rag_cfg)
    assert again.count() == 3 and again.dim == DIM


def test_vector_search_ranks_by_similarity(index):
    hits = index.search(_unit(1, 0, 0, 0), "", k=3, hybrid=False)
    assert [h["chunk_id"] for h in hits] == ["AAAA1111:0", "AAAA1111:1", "BBBB2222:0"]
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-5)
    assert hits[0]["score"] > hits[1]["score"] > hits[2]["score"]
    assert hits[0]["page_start"] == 1 and "vector" not in hits[0]


def test_search_filters_by_item_keys(index):
    hits = index.search(_unit(1, 0, 0, 0), "", k=5, keys={"BBBB2222"}, hybrid=False)
    assert [h["item_key"] for h in hits] == ["BBBB2222"]
    assert index.search(_unit(1, 0, 0, 0), "", k=5, keys=set()) == []
    with pytest.raises(ValueError, match="unsafe item key"):
        index.search(_unit(1, 0, 0, 0), "", k=5, keys={"x' OR '1'='1"})


def test_hybrid_falls_back_to_vector_before_finish_and_uses_text_after(index):
    before = index.search(_unit(1, 0, 0, 0), "royalties", k=3, hybrid=True)
    assert before[0]["chunk_id"] == "AAAA1111:0"
    index.finish()
    after = index.search(_unit(1, 0, 0, 0), "royalties", k=3, hybrid=True)
    ids = [h["chunk_id"] for h in after]
    # The keyword match now ranks above the weaker of the two vector matches.
    assert ids.index("BBBB2222:0") < ids.index("AAAA1111:1")


def test_replace_item_is_idempotent_and_can_shrink(index):
    rows = _rows("AAAA1111", [("Only one passage now, about krill.", _unit(0, 1, 0, 0))])
    index.replace_item("AAAA1111", rows)
    index.replace_item("AAAA1111", rows)
    assert index.count() == 2
    index.replace_item("AAAA1111", [])
    assert index.count() == 1
    index.delete_items({"BBBB2222"})
    index.delete_items(set())
    assert index.count() == 0
    index.finish()


def test_finish_keeps_new_rows_searchable_by_text(index):
    index.finish()
    index.replace_item(
        "CCCC3333", _rows("CCCC3333", [("Hydrothermal vents host tubeworms.", _unit(0, 0, 0, 1))])
    )
    index.finish()
    hits = index.search(_unit(1, 0, 0, 0), "tubeworms", k=2, hybrid=True)
    assert "CCCC3333:0" in [h["chunk_id"] for h in hits]


def test_wrong_vector_width_is_rejected(index):
    with pytest.raises(IndexMismatch, match="3 dimensions"):
        index.replace_item("DDDD4444", _rows("DDDD4444", [("text", [1.0, 0.0, 0.0])]))
    assert index.count() == 3


def test_open_rejects_a_different_dim_or_prefix_scheme(rag_cfg, index, monkeypatch):
    with pytest.raises(IndexMismatch, match="dim"):
        Index.open(rag_cfg, dim=DIM + 1, create=True)
    import paperful.rag.index as mod

    monkeypatch.setattr(mod, "task_prefixes", lambda model: ("passage: ", "query: "))
    with pytest.raises(IndexMismatch, match="doc_prefix"):
        Index.open(rag_cfg)


def test_a_new_model_gets_its_own_index(rag_cfg, index):
    rag_cfg.rag_embed_model = "bge-m3"
    with pytest.raises(IndexMissing):
        Index.open(rag_cfg)
    other = Index.open(rag_cfg, dim=8, create=True)
    assert other.count() == 0 and load_meta(rag_cfg)["doc_prefix"] == ""
    rag_cfg.rag_embed_model = "nomic-embed-text"
    assert Index.open(rag_cfg).count() == 3


def test_missing_lancedb_names_the_extra(rag_cfg, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "lancedb":
            raise ImportError("no lancedb")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RagUnavailable, match=r"paperful\[rag\]"):
        Index.open(rag_cfg, dim=DIM, create=True)
