# Co-author network

An **ORCID ego** co-authorship graph: who wrote with one person, sliced by
named year windows, with optional SNA metrics. Distinct from the Discover
**Queue citation map** (works, not people) and from snowball
`--author-site-preflight` `coauthors.json` (PDF-pack ranking, not brokerage).

Writes `state/network/<run-id>/` (`paperful.network.v1`). That directory is
already gitignored with the rest of `state/`.

## CLI

```text
uv sync --extra network          # NetworkX + matplotlib (betweenness, brokerage, --figures)
paperful network orcid 0000-0001-9025-7632 --phases bbnj --partition region
paperful network orcid 0000-0001-9025-7632 --out-dir /tmp/gjerde-network
paperful network show <run-id> --phase igc
paperful network list
paperful network export <run-id> --format csv
paperful network attributes <run-id> --write-template
# edit state/network/<run-id>/attributes.csv, then:
paperful network attributes <run-id>
```

`--phases bbnj` is the BBNJ negotiation windows used in the Gjerde tribute
paper: pre-2006, Ad Hoc Working Group (2006–2015), PrepCom (2016–2017),
IGC (2018–2023), post-adoption (2023–2025). Pass a TOML file instead:

```toml
[[phases]]
id = "adhoc"
label = "Ad Hoc Working Group"
year_from = 2006
year_to = 2015
```

`--partition region|discipline|sector` classifies Gould–Fernandez brokerage
roles on ego’s alter pairs. Undirected co-authorship cannot tell gatekeeper
from representative: mixed triads increment both. `--partition none` (default)
skips brokerage.

Without `paperful[network]`, the run still writes the graph plus **degree**
and **frequency**. Betweenness, Burt constraint, brokerage, GEXF/GraphML, and
`--figures` need the extra.

`--format json` on `orcid` / `show` / `list` is `paperful.agent.json.v1`.

## GUI

Discover → **People** → **Network**. Paste an ORCID, pick a phase preset and
optional partition, **Build network**. Saved runs load from
`state/network/` (no OpenAlex). The canvas is D3 v7, same drawing library as
the citation map; it does not add papers to the library.

Hide the panel with `[ui].coauthor_network = "off"` (Settings checkbox).

## Attributes

`attributes.csv` is the hand-coding overlay (discipline, sector, region,
career stage). OpenAlex seeds country → region, institution type → sector,
work topics → discipline, and year span → career stage. Overlay values win
on reload (`network attributes <run-id>`).

Grey literature is **not** merged into the graph in v1. Add those edges by
hand in the paper workflow; the CSV is for node attributes only.

## Live dogfood (Gjerde)

```text
PAPERFUL_E2E=1 paperful network orcid 0000-0001-9025-7632 \
  --phases bbnj --partition region --max-works 200 --max-alters 80
```

Copy [templates/network-watch-assessment.md](templates/network-watch-assessment.md)
to gitignored `assessments/YYYY-MM-DD-gjerde-network.md`. No Zotero writes.
See [BBNJ author lanes](bbnj-author-lanes.md).

## Schema

`paperful.network.v1` under `state/network/<run-id>/`:

| File | Contents |
| --- | --- |
| `meta.json` | ORCID, OpenAlex id, phase defs, caps, run date |
| `graph.json` | Ego, nodes, edges (`years[]`, weight) |
| `phases/<id>.json` | Subgraph + metrics for one window |
| `metrics.json` | Ego summary, per-node rows, `by_phase` |
| `attributes.csv` | Editable overlay |
| `figures/*.png` | Optional `--figures` |

Identity keys reuse `AuthorRecord.identity()` (`openalex:` / `orcid:` / `name:`).
