# paperful documentation

paperful is a local sidecar for your research library: keep collections
organised, fill missing PDFs, lint metadata, and keep a quiet copy on disk.
Zotero is the well-tested catalogue. Mendeley and EndNote adapters are seeking
testers. See [Why paperful](start/why.md).

**Operators** clone the repo and run `docker compose build` — no `docker pull`,
no PyPI. **Contributors** use [`uv`](https://docs.astral.sh/uv/). Details:
[Quick start](start/quickstart.md) and [Contributing](../CONTRIBUTING.md).

## Paths to results

Finish [Quick start](start/quickstart.md) once (`doctor` green), then choose:

1. **[Fill missing PDFs](paths/fill-pdfs.md)** — fetch and attach for a Zotero collection (open access first; campus EZProxy as a fork).
2. **[Quiet mirror](paths/quiet-mirror.md)** — snapshot a browsable `out/` tree; restore only what is missing later.
3. **[Snowball discovery](paths/snowball.md)** — grow a collection from a keyword, DOI, ORCID, or seed set.

How-to, reference, and architecture pages sit below for depth. **0.x** flags
may still move — [Releases](start/releases.md).

```{toctree}
:maxdepth: 2
:caption: Start here

start/quickstart
start/why
start/releases
```

```{toctree}
:maxdepth: 2
:caption: Paths to results

paths/fill-pdfs
paths/quiet-mirror
paths/snowball
```

```{toctree}
:maxdepth: 2
:caption: How-to

howto/docker
howto/zotero
howto/workflows
howto/dedupe
howto/ezproxy
howto/sessions
howto/research-ops
howto/scihub
howto/llm
howto/mendeley
howto/endnote
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/commands
reference/config
reference/sources
reference/comparison-reference
```

```{toctree}
:maxdepth: 2
:caption: Concepts

explain/architecture
explain/comparison
```

```{toctree}
:maxdepth: 2
:caption: Contribute

contribute/docs-guide
contribute/ROADMAP
```
