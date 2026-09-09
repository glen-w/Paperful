"""Shared offline fixtures: a config rooted in tmp_path and an httpx client backed by MockTransport."""

from __future__ import annotations

from typing import Callable

import httpx
import pytest

from scihub_dl.config import Config
from scihub_dl.sources.base import Context
from scihub_dl.zot import Item

PDF_BYTES = b"%PDF-1.4\n" + b"x" * 20_000 + b"\n%%EOF"


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        email="test@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
        scihub_mirrors=["m1.test", "m2.test"],
        delay_scihub_s=(0.0, 0.0),
        concurrency_oa=2,
        min_pdf_bytes=1000,
        mirror_failures_before_skip=2,
    )


def make_item(**overrides) -> Item:
    base = dict(
        key="ITEM0001",
        item_type="journalArticle",
        title="A sufficiently long test title about marine governance",
        doi="10.1000/test.doi",
        arxiv_id=None,
        url="https://example.org/paper",
        year=2019,
        first_author="Smith",
        collection_paths=["Col"],
    )
    base.update(overrides)
    return Item(**base)


@pytest.fixture
def item() -> Item:
    return make_item()


Handler = Callable[[httpx.Request], httpx.Response]


def mock_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture
def ctx_factory(cfg):
    def _make(handler: Handler) -> Context:
        return Context(config=cfg, client=mock_client(handler))

    return _make
