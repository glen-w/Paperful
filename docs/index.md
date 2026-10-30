# Paperful documentation

New here? [paperful.app](https://paperful.app/), then
[Walkthroughs](walkthroughs.md). Four ways to wire it up:
[Example setups](example-setups.md). Search order:
[How it works](how-it-works.md).

Paperful is a **local workbench** for a Zotero library you already keep.
Open access first; campus EZProxy when you have it. **Zotero is well tested.**
Mendeley and EndNote are seeking testers. You keep a folder copy on this
machine and attach the PDFs you trust. [Terms](TERMS.md).

Clone the repo, then `docker compose build` and `docker compose up` →
`http://127.0.0.1:8765` ([GUI](gui.md)).
[Docker](docker.md) (light / heavy packs). CLI: `docker compose run --rm paperful …`.
Host CLI without Docker: `pip install paperful` ([releases](releases.md#releases-and-stability)).
Contributors: [`uv`](https://docs.astral.sh/uv/). Stability: [releases](releases.md).
Why this shape: [Why Paperful](why.md).

```{toctree}
:maxdepth: 2
:caption: Start here

how-it-works
walkthroughs
example-setups
first-fill
grow-library
tidy-library
gui
why
docker
zotero
commands
firefox
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
screen
critique
rewrite
ezproxy
research-ops
sessions
scihub
serpapi
camofox
grobid
ai
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
network
keepup
bbnj-author-lanes
e2e-stack
e2e-nba
ROADMAP
```
