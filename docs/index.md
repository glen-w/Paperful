# paperful documentation

paperful is a local sidecar for your research library: keep collections
organised, fill missing PDFs, lint metadata, and keep a quiet copy on disk.
Zotero is the well-tested catalogue. Mendeley and EndNote adapters are in
the tree and seeking testers. See [Why paperful](why.md).

Work happens **on disk** (`out/`, `state/`). Open access first; campus
EZProxy when you have a subscription; **Sci-Hub is opt-in and off by
default**. `snapshot` / `restore` thicken that disk copy and recreate only
missing items. An optional **local-first LLM** (Ollama; off until you enable
it) adds grounded title proposals, a PDF identity check, `summarize` notes,
a `synthesize` report over those notes, and `recover` (last `run` lane after
other browser lanes fail, or `paperful recover --item`) — see [LLM](llm.md).

Narrow a run with `--collection` / `--library`, plus optional `--year-from` /
`--year-to` and `--type` / `-T`. Save that slice as a profile and repeat it
with `paperful all`. Details in [Commands](commands.md#scope-filters) and
[Workflows](workflows.md).

Run it with [`uv`](https://docs.astral.sh/uv/) (see the GitHub
[README](https://github.com/glen-w/Paperful#readme)). [Docker](docker.md) is
an optional image that packs Python, Poppler, and Chromium; Zotero and
headed session login still run on the host.

The GitHub [README](https://github.com/glen-w/Paperful#readme) is the same
first-run story. **0.x** flags may still move; see [releases](releases.md).

```{toctree}
:maxdepth: 2
:caption: Start here

why
commands
workflows
dedupe
config
architecture
quiet-mirror
releases
```

```{toctree}
:maxdepth: 2
:caption: Using paperful

zotero
mendeley
endnote
sources
ezproxy
sessions
scihub
llm
docker
```

```{toctree}
:maxdepth: 1
:caption: Product

comparison
comparison-reference
ROADMAP
```
