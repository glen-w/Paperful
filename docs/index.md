# Paperful documentation

New here? [paperful.app](https://paperful.app/), then
[Walkthroughs](walkthroughs.md). Search order: [How it works](how-it-works.md).

Paperful is a **local workbench** for a Zotero library you already keep.
Open access first; campus EZProxy when you have it. **Zotero is well tested.**
Mendeley and EndNote are seeking testers. Not a sync client. Not every
paywalled PDF. [Terms](TERMS.md).

`docker compose build`, then `docker compose up` →
`http://127.0.0.1:8765` ([GUI](gui.md)). No `docker pull`, no PyPI.
[Docker](docker.md) (light / heavy packs). CLI: `docker compose run --rm paperful …`.
Contributors: [`uv`](https://docs.astral.sh/uv/). **0.x**: [releases](releases.md).
Why this shape: [Why Paperful](why.md).

```{toctree}
:maxdepth: 2
:caption: Start here

how-it-works
walkthroughs
first-fill
grow-library
tidy-library
gui
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
browser-agent-models
```

```{toctree}
:maxdepth: 1
:caption: Product

comparison
comparison-reference
snowball
authorwatch
bbnj-author-lanes
e2e-stack
e2e-nba
ROADMAP
```
