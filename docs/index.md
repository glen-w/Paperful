# Paperful documentation

New here? The landing page is
[paperful.app](https://paperful.app/). [How it works](how-it-works.md)
is the walkthrough. This guide is the rest of the reference.

Paperful fills missing PDFs, tidies records, and keeps an on-disk mirror you
can back up and move. It is not a sync, mobile, or WebDAV client. **Zotero is
well tested.** Mendeley and EndNote adapters are seeking testers. Open access
first; campus EZProxy when you have a subscription. Scholar and Sci-Hub stay
off until you opt in. Not every paywalled or DOI-less item comes back.
Vocabulary: [Terms](TERMS.md).

Operators clone the repo and run `docker compose build`. The image is
build-local only: no `docker pull`, no PyPI. [Docker](docker.md).
Contributors use [`uv`](https://docs.astral.sh/uv/). **0.x** flags may still
move; see [releases](releases.md). Why this shape: [Why Paperful](why.md).

```{toctree}
:maxdepth: 2
:caption: Start here

how-it-works
why
docker
zotero
commands
workflows
research-pack
dedupe
config
architecture
developer
quiet-mirror
TERMS
releases
```

```{toctree}
:maxdepth: 2
:caption: Using paperful

mendeley
endnote
sources
ezproxy
research-ops
sessions
scihub
serpapi
llm
rag
```

```{toctree}
:maxdepth: 1
:caption: Product

TERMS
comparison
comparison-reference
snowball
ROADMAP
gui
```
