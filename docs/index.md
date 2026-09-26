# paperful documentation

New here? The landing page is
[paperful.app](https://paperful.app/). This guide
is the reference.

Paperful cleans a reference library, finds missing PDFs, and summarises
papers, then keeps an on-disk mirror you can back up and move. It is not a
sync service. Five jobs: **library**, **find**, **completeness**, **mirror**,
**control**. `snowball` grows the library (metadata parents). `run` fills
PDFs for items already there. See [Why paperful](why.md),
[Snowball](snowball.md), and [how a hop is cut](snowball.md#how-a-hop-is-cut).

The live catalogue is an adapter. **Zotero is well tested.** Mendeley and
EndNote adapters are in the tree and seeking testers. Open access first;
campus EZProxy when you have a subscription; playbooks you write, and an
opt-in AI browser, cover grey literature and field-specific sites. Paperful
does not fetch every paywalled or DOI-less item. **Sci-Hub is opt-in and off
by default.**

Work happens **on disk** (`out/`, `state/`). `snapshot` / `restore` write
that mirror and recreate only missing items. An optional **local-first LLM**
(Ollama or LiteLLM; off until you enable it) adds grounded title proposals,
a PDF identity check, `summarize` notes, a `synthesize` report over those
notes, and `recover` (last `run` lane after other browser lanes fail, or
`paperful recover --item`) — see [LLM](llm.md).

Narrow a run with `--collection` / `--library`, plus optional `--year-from` /
`--year-to` and `--type` / `-T`. Save that slice as a profile and repeat it
with `paperful all`. Details in [Commands](commands.md#scope-filters) and
[Workflows](workflows.md).

Operators clone the repo and run `docker compose build`. The image is
build-local only: no `docker pull`, no PyPI. [Docker](docker.md) packs Python,
Poppler, and Chromium; Zotero and headed session login still run on the host.
Contributors use [`uv`](https://docs.astral.sh/uv/) (see the GitHub
[README](https://github.com/glen-w/Paperful#readme) Develop section).

The GitHub [README](https://github.com/glen-w/Paperful#readme) is the same
first-run story. **0.x** flags may still move; see [releases](releases.md).

```{toctree}
:maxdepth: 2
:caption: Start here

why
docker
zotero
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

mendeley
endnote
sources
ezproxy
research-ops
sessions
scihub
llm
```

```{toctree}
:maxdepth: 1
:caption: Product

comparison
comparison-reference
snowball
ROADMAP
```
