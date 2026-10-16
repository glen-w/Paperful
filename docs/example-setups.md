# Example setups

Four ways to run Paperful, from one collection of free PDFs to a workbench
that grows the library, fills what it can, and leaves you reading in Zotero.
Pick the row that matches the job. Later rows add pieces; they do not replace
the earlier ones.

Click-by-click jobs stay in [Walkthroughs](walkthroughs.md). Search order is
[How it works](how-it-works.md). Named command recipes are
[Workflows](workflows.md).


| Setup                                                                                     | You want                                          | You turn on                                                                     |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| [1. One collection, open access](#1-one-collection-open-access)                           | Missing PDFs in a collection you already keep     | Open access preset. No campus login, no model                                   |
| [2. Same collection, plus the campus library](#2-same-collection-plus-the-campus-library) | Subscription copies your library already pays for | Campus preset and one EZProxy login                                             |
| [3. A desk that can grow](#3-a-desk-that-can-grow)                                        | Fill, tidy, and add a few new works when you ask  | Setup 1 or 2, plus Discover and Repair                                          |
| [4. All-in workbench](#4-all-in-workbench)                                                | Paperful does the fetching, watching, and filing  | Every lane you are willing to opt into, a model, watches, and the folder mirror |


Paperful does not run a timer. **Wanted** shows the holes; **Grab** (or
`run`) fills them when you ask. A topic watch or an author list is the same:
you run it, or you point cron / launchd at the command. See
[Snowball watch](snowball.md#watch) and [Author watch](authorwatch.md).

Zotero stays the catalogue you browse, annotate, and cite. Paperful is the
worker: it looks for PDFs, proposes new parents, and keeps a folder copy
under `out/`. [Quiet mirror](quiet-mirror.md).

## 1. One collection, open access

Use this when the library is already in Zotero and the job is “find a free
PDF for items that do not have one.”

**Scope.** One collection (the chip on **Library**, or `-C` on the CLI).
Leave the rest of the library alone.

**Lanes.** The workbench preset chip **Open access** (`--preset oa`) is the
default source list without campus EZProxy: Unpaywall, OpenAlex, arXiv,
bioRxiv/medRxiv, Europe PMC, Semantic Scholar, CORE, OpenAIRE, the item’s
own URL, and print-to-PDF for news and blogs. Routing sends each item only
to lanes that match what the record already has. A DOI journal article
mostly hits the open-access indexes — Unpaywall and OpenAlex first — and
skips campus, Scholar, and the browser. CORE is in that list and stays
quiet until `core_api_key` is set. [Source routing](sources.md).

Google Scholar, the browser agent, and Sci-Hub stay off. Sci-Hub is off by
default; opting in is your own risk and your own compliance. See
[Sci-Hub](scihub.md).

**Loop.** [First fill](first-fill.md): **Wanted** → **Preview** → **Grab**
onto `out/` → open a couple of files → **Attach** the ones you trust
(automatic attach is a Settings switch, and it needs Zotero 10 or newer).

```sh
docker compose run --rm paperful gaps -C "My Collection"
docker compose run --rm paperful run -C "My Collection" --preset oa --dry-run
docker compose run --rm paperful run -C "My Collection" --preset oa
```

Save the slice once you like it, then repeat the same command:

```sh
docker compose run --rm paperful profile save my-collection \
  -C "My Collection" --preset oa \
  --description "Open-access fill for one collection"
docker compose run --rm paperful run --profile my-collection
```

A profile on `run` does not turn on `--try-all`. That flag is for messy
records; this setup trusts routing. [Workflows](workflows.md).

**You skip.** Campus login, a local model, snowball, author lists.

**Room to grow.** Add a campus prefix (setup 2) without changing the
collection. A CORE API key raises repository hits. Grey-lit items with no
DOI need [playbooks](config.md#grey-literature-playbooks), not another OA
index.

## 2. Same collection, plus the campus library

Same job as setup 1, plus PDFs your university or research library already
subscribes to.

### What EZProxy is

Publisher sites (Elsevier, Springer Nature, Wiley, JSTOR, and the rest)
normally sit behind a subscription. **EZProxy** is the redirect your library
uses so that, once you have signed in with the campus account, the publisher
treats you as on campus. The address usually looks like:

```text
https://<your-prefix>.idm.oclc.org/login?url=
```

Paperful never asks for or stores that password. You log in once in a
browser window it opens. Later fills reuse that session until it expires
(often hours to a few days). Being logged in in everyday Chrome does not
count — Paperful does not read that cookie jar.

The proxy is only wrapped around a DOI or a known publisher URL. It does
not turn a YouTube link, a UN page, or an NGO PDF into a subscription
download. Bulk download can still violate a campus acceptable-use policy.
Details, the publisher list, and how to find your library’s prefix:
[Campus EZProxy](ezproxy.md) · [Research operators](research-ops.md).

**Lanes.** Preset chip **Campus** (`--preset eoi`): the open-access list
from setup 1, then EZProxy. Free copies are still tried first. Set
`ezproxy_base` in `config.toml`, then log in on the **host** (campus
single sign-on needs your system Chrome or Edge, not the container):

```sh
# config.toml
# ezproxy_base = "https://YOUR-PREFIX.idm.oclc.org/login?url="

uv run paperful session login ezproxy
docker compose run --rm paperful doctor --probe
docker compose run --rm paperful run -C "My Collection" --preset eoi --dry-run
docker compose run --rm paperful run -C "My Collection" --preset eoi
```

`doctor --probe` checks that the vault is still live. A cookie file on disk
is not enough. When the session dies mid-run, `run` on a terminal offers
re-login and retries the items that missed because of it.

**You skip.** Scholar, a model, and any crawl. One collection is still the
scope.

**Room to grow.** Scholar is a later opt-in (`session login scholar`, then
add `scholar` to `sources`). It runs late, after open access and campus.
Setup 3 adds new works. Setup 4 adds the browser for landings the scripts
miss.

## 3. A desk that can grow

Setup 1 or 2, plus the jobs around a fill. Still beginner-sized: one
collection (or a small set), review before anything is written, no model
required.


| Job                          | Where                             | What you get                                                                    |
| ---------------------------- | --------------------------------- | ------------------------------------------------------------------------------- |
| Fill holes                   | **Wanted** / `run`                | PDFs on `out/`, then attach                                                     |
| See what is messy            | **Repair** / `lint`, `dedupe`     | Identifier notes and a duplicate review on disk. Nothing merges until `--apply` |
| Add works you do not have    | **Discover** / `snowball`         | A queue. **Add selected** creates metadata parents only                         |
| People you already follow    | **Discover** / `authorwatch`      | Their new papers, no citation hop                                               |
| Works cited in PDFs you hold | [Research pack](research-pack.md) | Cited-in-PDF → parents → a later fill                                           |


`paperful all` is the usual chain in one process: gaps, fill, lint,
fix-metadata, and summarize. With the model off, summarize is skipped and
the earlier steps still finish.

```sh
docker compose run --rm paperful all -C "My Collection" --preset eoi --dry-run
docker compose run --rm paperful all -C "My Collection" --preset eoi --skip summarize
```

Use `--preset oa` when you have no campus login.

On **Discover**, a topic search is dry-run until you keep rows and apply.
The first author-watch run records a baseline and proposes nothing; a later
run, or `--backfill-from`, is what fills the inbox. [Grow the library](grow-library.md)
is the click path. [Tidy a collection](tidy-library.md) is Repair.

**You skip.** Automatic crawls that create parents, a browser agent, and
paid Scholar search. Turn those on in setup 4 when the desk feels small.

**Room to grow.** Save a snowball profile and a watch so the next
**Check again** only shows unseen works. Point `grey_playbooks_dir` at a
pack when the collection is full of reports and UN documents. Enable a model when you want notes — Ollama locally or LiteLLM for a hosted
API (setup 4, or [LLM](llm.md) on its own).

## 4. All-in workbench

Use this when you want Paperful to do the repetitive work: grow a large
library from seeds and keywords, try every method available for grabbing PDFs, watch
topics and people, write grounded notes, and keep the folder copy current.

The mirror under `out/` is the copy Paperful works from and the copy you
can back up. Attach puts the PDFs you trust back into Zotero so the reader
app stays the interface. [Why Paperful](why.md) · [Quiet mirror](quiet-mirror.md).

### Grow

Snowball proposes works from a keyword, a DOI, an ORCID, or a collection,
then stops at a gate. `approve-batch` (or **Preview apply** on Discover)
is the safe default on a large crawl. `gate = auto` creates parents without
that pause — use it on a slice you already trust. `--fetch-pdfs` fills only
the keys just created. A stopping rule is separate from that gate and stays off unless you set `[snowball].stop_rule` or `--stop-rule`. Then the crawl pauses after one hop for Keep/Skip and `snowball continue`. See [Stopping rules](snowball.md#stopping-rules).

```sh
docker compose run --rm paperful snowball search "marine spatial planning" \
  --year-from 2018 --gate approve-batch -C "Inbox/Snowball"
docker compose run --rm paperful snowball hybrid "high seas EIA" \
  --hybrid-seeds 5 --direction refs --gate approve-batch -C "Inbox/Snowball"
```

A **frontier digest** ranks the queue (new, already in the library, deferred)
into `digest.md`. It does not create items. A **watch** re-runs a saved
profile and proposes only unseen works. The first watch run is a baseline.

```sh
docker compose run --rm paperful snowball watch save msp --profile keyword-scout
docker compose run --rm paperful snowball watch run msp --digest
docker compose run --rm paperful snowball apply <run-id> -C "Inbox/Snowball"
```

**Author watch** is the people list: their new papers, no hop. Suggest can
rank creators already in a collection; you accept the ones you follow.

```sh
docker compose run --rm paperful authorwatch save field-people
docker compose run --rm paperful authorwatch suggest field-people \
  -C "Inbox/Snowball" --method mix --limit 15
docker compose run --rm paperful authorwatch run field-people --backfill-from 2024-01-01
docker compose run --rm paperful authorwatch apply field-people -C "Watch/Field" --apply
```

Depth, caps, and gates: [Snowball](snowball.md). Lists and suggest:
[Author watch](authorwatch.md).

### Fill every lane you opted into

Open access and campus stay first. On a large or messy library, `--try-all`
sends each item through every configured source that can apply, and
`--retry-failed` reopens items a previous run closed. `paperful all` turns
both on, plus an upgrade of linked files and a metadata fix.

```sh
docker compose run --rm paperful all -C "Inbox/Snowball" --preset eoi \
  --try-all --retry-failed
```

Opt-in lanes, each off until you ask:


| Lane           | When it helps                                     | How                                                                                                                                                                                    |
| -------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Campus EZProxy | Subscription PDFs                                 | Setup 2. Preset `eoi`                                                                                                                                                                  |
| Google Scholar | A title the indexes missed                        | `session login scholar`, then `scholar` in `sources`. Runs **late**                                                                                                                    |
| Browser agent  | Cookie banners and odd publisher download buttons | `[llm].enabled`, the `browser-agent` extra (or the heavy Docker image), Python 3.11+. Last lane on `run`, or `recover` for one item. [LLM](llm.md) · [Models](browser-agent-models.md) |
| Camofox        | A scripted recover browser, no campus SSO         | `[camofox].enabled` and a camofox-browser server. [Camofox](camofox.md)                                                                                                                |
| SerpApi        | Paid Scholar link discovery                       | `[serpapi].enabled` and `SERPAPI_API_KEY`, with a call cap. [SerpApi](serpapi.md)                                                                                                      |
| Grey playbooks | Reports and UN documents with no DOI              | Builtin ocean pack, or your own. [Config](config.md#grey-literature-playbooks)                                                                                                         |


Sci-Hub stays off unless you opt in, at your own risk. Legal compliance is
yours. Do not put it in a default profile. [Sci-Hub](scihub.md).

Items that still miss can go to a handoff list (`gaps --handoff` or
`reachout`) so you email an author or open a page yourself. Those commands
do not download. [Workflows](workflows.md).

### Notes, a collection review, and Ask

A model is optional. **Local AI (default path):** [Ollama](https://ollama.com)
on your computer when you have enough RAM/VRAM for the job — 7B-class for
summaries and collection reviews, 14B+ for the browser agent. **Hosted APIs
(optional):** install `paperful[llm]` and set `provider = "litellm"` to call
an external service (OpenAI, Anthropic, or any LiteLLM-supported provider;
keys via environment variables). That path is an explicit opt-in; commands
print a notice when text leaves the machine. In every case the model only
sees metadata and text from PDFs already on disk. Feasibility (try-it vs a
~1.5k library, overnight local runs, hosted cost order of magnitude):
[AI for notes and Ask](ai.md). Command setup: [LLM](llm.md).

Three reading jobs, in order:


| Job                        | Command                  | What you get                                                                                                                                                              |
| -------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One summary per PDF        | `summarize`              | A grounded note on the item. `paperful all` runs this when `[llm].enabled`                                                                                                |
| Summary of those summaries | `synthesize`             | One collection review (themes, agreements, gaps) from the notes `summarize` already wrote. It does not open the PDFs again. Not in the default `all` chain — run it after |
| Cited answers              | `rag ingest`, then `ask` | An index of `out/`, then answers that name the papers and pages. **Ask** on the workbench. Needs `[rag].enabled`                                                          |


`fix-metadata` (title and identifier patches; `--apply` writes the catalogue)
is already inside `all`. `recover` is the browser agent for one stubborn
landing.

```toml
# Local (Ollama) — pull tags with `ollama pull` on the host
[llm]
enabled = true
provider = "ollama"
model = "qwen2.5:7b"

[rag]
enabled = true
embed_provider = "ollama"
embed_model = "nomic-embed-text"
```

For a hosted chat and embeddings API instead of Ollama, use
`provider = "litellm"` and LiteLLM model ids (for example
`openai/gpt-4.1-mini` and `openai/text-embedding-3-small`), after
`uv sync --extra llm` on the host or a **heavy** Docker image. See
[LiteLLM in llm.md](llm.md#litellm-paid--openai-compatible-apis).

```sh
docker compose run --rm paperful all -C "Inbox/Snowball" --preset eoi
docker compose run --rm paperful synthesize -C "Inbox/Snowball"
docker compose run --rm paperful rag ingest -C "Inbox/Snowball"
docker compose run --rm paperful ask "What do these papers agree on?" -C "Inbox/Snowball"
```

`synthesize` writes `state/reports/<slug>.html` and, with the default
destination, a standalone Zotero note tagged `paperful-report`. Re-runs
update that note when the source summaries are unchanged unless you pass
`--force`. [LLM](llm.md#e-synthesize-summary-of-summaries).

Summaries and the collection review want a 7B-class instruct model. Ask
uses that chat model plus embeddings (`ollama pull nomic-embed-text` locally,
or `embed_provider = "litellm"` with a hosted embedding model). The browser
agent wants 14B or larger on Ollama, or a capable hosted tag on LiteLLM.
The heavy Docker image includes the RAG and LiteLLM extras; the light image
does not. A full collection summarize is a multi-night or hosted-budget job —
not a laptop afternoon. [AI](ai.md) · [LLM](llm.md) · [Ask your library](rag.md).

### What you run on a schedule you own

Paperful will not poll by itself. A practical loop, in your own cron or
launchd:

1. `snowball watch run <name> --digest` — unseen works for the topic.
2. `authorwatch run <name>` — new papers from people you follow.
3. Review the digest and the inbox, then `apply` the rows you want.
4. `all -C … --preset eoi` — fill, tidy, and (if the model is on) one summary per PDF.
5. `synthesize -C …` — one summary of those summaries for the collection.
6. `rag ingest -C …` when new PDFs landed, then read in Zotero and **Ask** against the index.

**Held** rows (short PDF, DOI mismatch) still wait for you. Not every
paywalled or DOI-less item comes back.

## Which file to copy


| Starting point | File                                                                               |
| -------------- | ---------------------------------------------------------------------------------- |
| Setup 1        | `config.minimal.toml` — email, paths, open-access sources                          |
| Setup 2–4      | `config.example.toml` — same, plus the commented campus, Scholar, and model blocks |


```sh
cp config.minimal.toml config.toml   # or config.example.toml
# set email = "you@example.org"
docker compose up                    # http://127.0.0.1:8765
```

`config.toml` stays untracked. Keys and passwords stay in the environment
or in the session vault, not in that file. [Configuration](config.md) ·
[Docker](docker.md) · [Zotero](zotero.md).