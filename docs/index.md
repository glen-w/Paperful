# paperful documentation

paperful fills the gaps in your Zotero library: fetch missing PDFs, keep them
in a folder tree that mirrors your collections, and attach them back.

Work happens **on disk** (`out/`, `state/`). Zotero is a library adapter. Open
access first; campus EZProxy when you have a subscription; **Sci-Hub is opt-in
and off by default**.

Run it with [`uv`](https://docs.astral.sh/uv/) (see the GitHub
[README](https://github.com/glen-w/Paperful#readme)). [Docker](docker.md) is
an optional image that packs Python, Poppler, and Chromium; Zotero and
headed session login still run on the host.

The GitHub [README](https://github.com/glen-w/Paperful#readme) is the same
first-run story. **0.x** flags may still move; see [releases](releases.md).

```{toctree}
:maxdepth: 2
:caption: Start here

commands
config
architecture
releases
```

```{toctree}
:maxdepth: 2
:caption: Using paperful

sources
ezproxy
sessions
scihub
docker
```

```{toctree}
:maxdepth: 1
:caption: Product

comparison
comparison-reference
ROADMAP
```
