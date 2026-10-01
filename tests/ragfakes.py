"""Offline stand-ins for the RAG tests: an embedder, a parser, a chat client, a mirror."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from paperful.llm.client import LLMClientError
from paperful.rag.extract import ParseError
from paperful.store import write_json

DIM = 8
BODY = "Krill swarm under the winter sea ice and feed on algae. " * 8


class FakeEmbedder:
    """Deterministic vectors from a hash of the text. Counts what it was asked for."""

    provider = "ollama"
    model = "nomic-embed-text"

    def __init__(self):
        self.documents: list[str] = []
        self.queries: list[str] = []

    def check_config(self):
        return True, "ok"

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [b - 127.5 for b in digest[:DIM]]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return self._vector(text)


class TextFileParser:
    """Test PDFs are text files; form feeds separate pages."""

    name = "light"
    version = 1

    def __init__(self):
        self.parsed: list[str] = []

    def pages(self, path: Path) -> list[str]:
        self.parsed.append(path.name)
        data = path.read_bytes()
        if data.startswith(b"BROKEN"):
            raise ParseError("PDF could not be opened")
        return data.decode().split("\f")


class StubChat:
    """Chat client that replies with fixed pieces and records the requests."""

    provider = "stub"

    def __init__(self, pieces=("Krill eat algae ", "[S1]."), error: str = ""):
        self.pieces = list(pieces)
        self.error = error
        self.requests: list = []

    def check_config(self, model):
        return True, "ok"

    def chat_stream(self, request):
        self.requests.append(request)
        if self.error:
            raise LLMClientError(self.error)
        yield from self.pieces


def add_item(
    cfg,
    key,
    *,
    collection="ocean",
    title="Krill in winter",
    author="Chen",
    year=2019,
    abstract="",
    pdf=None,
):
    """Write one item folder into the mirror under ``cfg.out_dir``."""
    folder = cfg.out_dir / collection / f"{author} - {year} - {title} -- {key}"
    folder.mkdir(parents=True, exist_ok=True)
    write_json(
        folder / "record.json",
        {
            "item_key": key,
            "item_type": "journalArticle",
            "version": 1,
            "title": title,
            "creators": [{"lastName": author}],
            "year": year,
            "abstract": abstract,
        },
    )
    if pdf is not None:
        (folder / "paper.pdf").write_text(pdf)
    return folder
