# How Paperful compares — reference

Vendor-by-vendor notes and longer capability tables. Most readers only need
[How Paperful compares](comparison.md).

**Last reviewed:** 2026-10-26. Feature lists for other products are based on public
docs and positioning — not paid pilots.

## Capability snapshot

### Zotero-centric (extended)

Legend: **Yes** · **Partial** · **No**.

| Capability | Paperful | Zotero built-in | zotero-zotadata | StorScan | ZotMeta | zotero-agent | zotero-mcp (typical) |
|------------|----------|-----------------|-----------------|----------|---------|--------------|----------------------|
| Bulk fetch **missing** PDFs | Yes | Partial | Yes | Partial | No | Partial (`pdf-fetch`) | Partial (Unpaywall attach) |
| Collection-scoped batch runs | Yes | No | Partial | Partial | Partial | Yes | Partial |
| Resumable manifest / retry | Yes | No | Partial | Partial | Partial | Partial | No |
| Open-access source stack | Yes | Partial | Yes | Partial | No | Partial | Partial |
| Campus **EZProxy** | Yes | No | No | No | No | No | No |
| **Sci-Hub** (explicit opt-in) | Yes | Partial | Yes | No | No | Partial | No |
| Metadata lint / verify DOI | Yes | No | Yes | No | Yes | Yes | Partial |
| Metadata apply | Yes | No | Yes | No | Yes | Yes | Partial |
| Attachment / disk repair | No | Partial | Partial | Yes | No | Partial | No |
| Dedupe / merge items | Yes (`dedupe --apply` merges children and better fields, then trashes the extra; Zotero only) | Partial | No | Partial | No | Yes | Partial |
| CLI / automation | Yes | No | No | No | No | Yes | Yes (MCP) |
| Disk-first then write-back | Yes | No | No | Partial | No | Partial | No |
| Per-item folder you can restore from | Yes | No | No | No | No | No | No |
| Copy PDFs **already in** Zotero onto disk | Partial (`snapshot --pdfs all`) | Partial (File → Export PDFs) | No | No | No | No (`export` is bibliography; `get_item_pdf_path` is a path) | Partial (`get_pdf_path`) |
| Grey-literature landing playbooks | Yes | No | No | No | No | No | No |
| Grounded summary / collection review | Partial (opt-in `summarize` / `synthesize`; text layer) | No | No | No | No | Partial (README: summarize PDFs into notes) | Yes (chat reads PDF text; the model writes the summary) |
| OCR for scanned PDFs | Partial (`paperful ocr`, OCRmyPDF text layer on disk) | No | No | No | No | Partial (`pdf-prep`, OCRmyPDF) | Partial (some forks, e.g. Docling OCR pre-step) |

### Zotero version and attach (indicative)

Verify against each project’s latest release before upgrading Zotero.

| Tool | Typical Zotero | Notes |
|------|----------------|-------|
| Paperful | 7–9 download; **10+** attach and `fix-metadata --apply` | Local HTTP API |
| StorScan, Attanger, ZotMeta 2.0, zotodata | **7–9** (per upstream READMEs) | Plugin `.xpi` |
| zotero-agent | **7+** | Bridge plugin + CLI |
| ZotFile | **≤6** | [Not maintained for Zotero 7+](https://github.com/jlegewie/zotfile/issues/674) |
| Built-in Find Available PDF | **6+** | Custom resolvers in Config Editor |

### BibTeX / export fixers

| Capability | bibcite | bibtex-tidy | bibmanager | bibtex-cleaning-agent | JabRef |
|------------|---------|-------------|------------|----------------------|--------|
| Dedupe entries | Yes | Yes | Yes | Yes | Yes |
| Resolve DOI/arXiv/title → BibTeX | Yes | No | Partial (ADS) | Yes (LLM + APIs) | Partial |
| Stable citation keys | Yes | Partial | Yes | Yes (patterns) | Yes |
| Upgrade arXiv → published | Yes | No | Yes | Partial | Partial |
| Mendeley export cleanup | Partial | Partial | Partial | Partial | Yes (import) |
| Zotero library sync | No | No | No | No | Yes |
| Batch PDF download | No | No | Partial (ADS) | No | Partial |

### DOI-centric downloaders

| Capability | Paperful | paperscraper | pyzotero + custom scripts |
|------------|----------|--------------|----------------------------|
| Needs a library manager | Adapter (Zotero now) | No | Optional |
| Input | Library items / collections | DOI JSONL / dict | API keys or local DB |
| Publisher TDM APIs | No | Yes (Elsevier/Wiley, etc.) | DIY |
| Attach back to items | Yes | No | DIY |
| EZProxy / Sci-Hub | Yes / opt-in | No / DIY | DIY |

### Hosted literature MCP (global corpus)

Legend: **Yes** · **Partial** · **No**. Valency rows reflect public positioning for
[MCP Bond](https://www.valency.io/) (not a hands-on product audit). Edison
rows reflect [public docs](https://docs.edisonscientific.com/) (2026-10-26),
not a paid pilot.

| Capability | Paperful | Valency MCP Bond | Edison Scientific | zotero-mcp (typical) |
|------------|----------|------------------|-------------------|----------------------|
| Semantic search over **public** papers / preprints | Partial (`snowball` keyword / similar hops; OpenAlex-backed discovery — not a single “ask the whole web” MCP) | Yes | Yes (Literature / PaperQA3 over 175M+ papers; also trials and patents) | Partial (search library + sometimes Unpaywall) |
| Semantic search over **your** PDFs | Yes (`rag ingest` + `ask`; GUI Ask) | No | Partial (upload / workspace files; not your Zotero tree) | Yes (chat reads attached PDFs) |
| Citation graph (corpus-scale, both directions) | Partial (`snowball` `refs` / `cites` / `both`; Discover map of one queue, not the whole public corpus) | Yes | Yes (Literature: native citation-graph understanding) | Partial |
| Author profiles / co-author networks | Partial (`authorwatch briefing`, `suggest -C`) | Yes | Partial (via literature search, not a dedicated author MCP) | Partial |
| Keyword / publication **trends** | Partial (`snowball trends`, MCP `snowball_trends`; OpenAlex filters in snowball) | Yes | Partial (reviews, not a trends MCP) | No |
| Novelty / “has anyone done this?” | Partial (`refs gap`, similar hops, `ask --focus gaps` — never claims absence) | No | Yes (**Precedent**, formerly Has Anyone) | No |
| Cited literature **synthesis** / conflicting evidence | Partial (opt-in `synthesize` / Ask over held PDFs) | Partial (search/export, not a review agent) | Yes (Literature; `LITERATURE_HIGH` reasoning mode) | Partial (chat) |
| Bulk **missing-PDF** fetch into a collection | Yes | No | No | Partial |
| Disk mirror + **restore** ledger | Yes | No | No | No |
| Campus EZProxy / grey-lit PDF playbooks | Yes | No | No | No |
| Experimental-data analysis / molecular design | No | No | Yes (**Analysis**, **Molecules**; **Kosmos** joins literature + code) | No |
| Programmatic API | Partial (`paperful mcp` + `--format json`; writes stay CLI `--apply`) | Yes (MCP) | Yes (`edison-client` jobs; Kosmos **not** on the public API) | Yes (MCP) |
| MCP tools (indicative breadth) | Partial (read-only: `gaps`, `snowball_search`, `snowball_trends`, `export`, `proposal_export`, `refs_gap`, `ask`; no `--apply`) | Yes (positioning: large tool surface) | No (Python/REST client; chat sessions) | Yes (varies by fork) |
| Runs **local** / library stays on disk | Yes | No | No (hosted platform; academic free tier) | Yes |
| Corpus freshness (vendor SLA) | Partial (`snowball watch`, `authorwatch run` — you schedule polls) | Yes (positioning: index within hours) | Yes (hosted index; SLA not audited here) | N/A (local library) |

Valency **Hub** (publish, fork, public review) is a separate product; Paperful does not host papers.
Edison **Kosmos** is a separate autonomous-scientist job, not an MCP Bond analogue.

## Complementary: Zotero plugins and built-ins

### Paperful

- **Sites:** [GitHub](https://github.com/glen-w/Paperful) · this repo
- **Fit:** Research helper for a reference library: clean records, find missing PDFs, summarise papers, keep a platform-agnostic mirror. Routed OA stack (including CORE with API key), campus EZProxy, optional Scholar cookies, opt-in Sci-Hub, user playbooks for grey literature and field-specific hosts, and an opt-in AI browser after scripted lanes fail. Collection-mirrored `out/` tree (`snapshot` / `restore`, including `snapshot --pdfs all` for PDFs already in Zotero, `manifest.jsonl`), attach on Zotero 10+. Identifier verify (Crossref/OpenAlex/PubMed) + lint + `fix-metadata` on disk, then adapter write-back. `dedupe` writes a review pack and, with `--apply`, merges the extra parent's PDF, notes, and better fields onto the keeper, then trashes that parent (DOI, then title+year; Zotero only). `gaps` counts missing PDFs and DOIs. Optional local `summarize` / `synthesize` and `recover` (last `run` lane after Scholar / EZProxy / htmlpdf fail, or `recover --item`; text layer from the PDF or from `paperful ocr`; not a chat agent). **Zotero is the well-tested adapter.** Mendeley (REST) and EndNote (read-only database plus an import bundle) are seeking testers.
- **With others:** `paperful attachments` for a CLI report (and flagged repairs from `out/`); StorScan or Attanger when you want the work inside Zotero, including incoming downloads; zotero-agent for disk GC or a two-up scan split; zotero-mcp when the work is a conversation.
- **Not a substitute for:** In-app plugin UX, `.bib` hygiene tools, or two-up scan splitting.

### Zotero built-in

- **Sites:** [Zotero](https://www.zotero.org/) · [custom PDF resolvers](https://www.zotero.org/support/kb/custom_pdf_resolvers)
- **Fit:** Per-item **Find Available PDF**, identifier lookup, duplicate merge UI, File → Export PDFs (a one-off dump of files already on disk, not a restore ledger).
- **With Paperful:** Built-in capture on save; Paperful for batch backfill and for `snapshot` / `restore` when Zotero file storage is the wrong warehouse.

### zotero-zotadata

- **Sites:** [GitHub](https://github.com/ydeng11/zotero-zotadata)
- **Fit:** Plugin combining attachment validation, multi-source PDF retrieval, and metadata updates.
- **With Paperful:** Overlapping PDF mission; zotodata stays in Zotero.

### StorScan

- **Sites:** [GitHub](https://github.com/brian-j-griffith/StorScan)
- **Fit:** Attachment operations — scan, fix misplaced linked files, merge duplicate files.
- **With Paperful:** Paperful `attachments` reports broken links, ghosts, and same-file duplicates, and can repair them from `out/` when you pass a flag and `--apply`. StorScan is the in-app scan.

### ZotMeta

- **Sites:** [GitHub](https://github.com/RoadToDream/ZotMeta)
- **Fit:** Bulk metadata from DOI, ISBN, arXiv; PDF cache identifier extraction.
- **With Paperful:** Overlaps `lint` / `fix-metadata`; ZotMeta is in-app.

### Attanger and ZotMoov

- **Sites:** [Attanger](https://github.com/MuiseDestiny/zotero-attanger) · [ZotMoov](https://github.com/wileyyugioh/zotmoov)
- **Fit:** ZotFile-era workflows on Zotero 7+ — match downloads, rename/move linked files.
- **With Paperful:** Incoming-file organisation and tablet send/get. `paperful attachments --rename` and `--link` cover the mirror-stem rename and a stored-to-linked cutover under `out/`, and they stay off until `--apply`.

### zotero-agent

- **Sites:** [GitHub](https://github.com/alex-roc/zotero-agent)
- **Fit:** Local-first CLI and MCP via bridge plugin — search, dedupe, merge, enrich, `pdf-fetch`, PDF notes, and `pdf-prep` OCR (OCRmyPDF) for scans. `export` writes bibliography formats, not a PDF folder tree.
- **With Paperful:** Agent for hygiene and merge; Paperful for collection runs with a manifest, a disk text layer (`ocr`), EZProxy, grey-lit playbooks, and a folder you can restore from. zotero-agent `pdf-prep` still owns two-up page splits.

### zotero-mcp ecosystem

- **Sites:** [richardjlyon/zotero-mcp](https://github.com/richardjlyon/zotero-mcp) · [cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp) · [mcp-zotero](https://github.com/Xevos117/mcp-zotero)
- **Fit:** LLM-facing search, PDF text, create items, sometimes Unpaywall attach. Some forks OCR scans (Docling) or write reading notes from chat.
- **With Paperful:** MCP when a person is in the loop; Paperful for unattended collection runs, the disk ledger, `ocr` on image PDFs, and batch `summarize` / `synthesize`.

### Valency MCP Bond and Hub

- **Sites:** [valency.io](https://www.valency.io/)
- **Fit:** **MCP Bond** — hosted semantic access to a very large public paper/preprint corpus (search, citation graph, authors, trends, export) for LLM clients. **Hub** — open publishing, versioning, and review; out of scope for Paperful’s library/mirror jobs.
- **With Paperful:** Bond when the question is “what does the literature say?” across hundreds of millions of works. Paperful when the question is “fill, fix, mirror, and reason over **my** collection” — `run`, `snapshot`, `snowball` / `authorwatch` to grow it, `ask` / `refs_gap` / `gaps` / dry-run `snowball_search` / `snowball trends` / `export-proposals` (and optional `paperful mcp` with the same JSON envelopes) over the on-disk index. Typical stack: Bond (or similar) for discovery → snowball / `ingest-dois` / manual save → Paperful for PDFs and disk-first hygiene.
- **Not a substitute for:** EZProxy-backed fetch, grey-literature playbooks, collection-shaped `out/` restore, or unattended batch attach.

### Edison Scientific

- **Sites:** [docs.edisonscientific.com](https://docs.edisonscientific.com/) · [platform.edisonscientific.com](https://platform.edisonscientific.com) · FutureHouse spinout
- **Fit:** Hosted agents that *do research*, not a Zotero helper. **Literature** (PaperQA3) — cited Q&A and deep reviews over 175M+ papers, trials, and patents, including conflicting-evidence synthesis and figure pullouts. **Precedent** (formerly Has Anyone) — novelty / “has this been tried?”. **Kosmos** — autonomous scientist (objective + datasets; parallel literature and analysis agents; structured world model; ~1,500 papers and ~42k lines of code per run; auditable traces; not on the public API). **Analysis** and **Molecules** — experimental data and chemistry. Python **`edison-client`** (`JobNames`, task continuation, file storage); enterprise agent profiles.
- **With Paperful:** Edison when the question is a public-corpus review, a novelty search, or a Kosmos/Analysis run on a dataset. Paperful when the question is “fill, fix, mirror, and Ask **this** library.” Typical stack: Edison Literature or Precedent → snowball / `ingest-dois` → `run` / Wanted → local `ask`. Do not treat their workspace as the quiet mirror.
- **Not a substitute for:** missing-PDF fetch, EZProxy / grey playbooks, `snapshot` / `restore`, collection-scoped RAG that never leaves the machine, or unattended attach.
- **Roadmap borrow (not a clone):** precedent pack over held PDFs + OpenAlex, named MCP read jobs, conflicting-evidence briefs — [ROADMAP — Hosted AI scientists](ROADMAP.md#hosted-ai-scientists-edison-scientific).

### ZotFile (legacy)

- **Sites:** [zotfile.com](https://zotfile.com/)
- **Status:** Not compatible with Zotero 7+. Use Attanger / ZotMoov.

## BibTeX, Mendeley, and scripts

### bibcite and bibtex-tidy

- **Sites:** [bibcite](https://github.com/leo1oel/bibcite) · [bibtex-tidy](https://flamingtempura.github.io/bibtex-tidy/)
- **Fit:** Resolve papers to canonical BibTeX, dedupe, tidy, upgrade preprints.
- **With Paperful:** Orthogonal until a bib-file `LibraryBackend` exists.

### bibmanager

- **Sites:** [Read the Docs](https://bibmanager.readthedocs.io/)
- **Fit:** Unified BibTeX database, ADS integration, optional PDF fetch from ADS.

### Mendeley

- **Fit:** Reference Manager **Duplicates** smart collection; Desktop merge UI. Paperful can set `manager = "mendeley"` (REST, OAuth). That adapter is **seeking testers**. Zotero is the well-tested path.

### paperscraper

- **Sites:** [GitHub](https://github.com/jannisborn/paperscraper)
- **Fit:** Python metadata + `save_pdf` from DOIs; publisher TDM API keys.
- **With Paperful:** paperscraper when the input is a DOI list, not a collection tree.

## Choosing in one glance

```text
Need PDFs already in Zotero copied into a collection-shaped tree, with a record per item?
  → paperful snapshot --pdfs all

Need a one-off dump of those PDFs from the Zotero UI?
  → File → Export PDFs

Need tablet send/get after ZotFile died?
  → ZotMoov custom menus (+ Attanger)

Need a text layer on a scanned PDF?
  → paperful ocr. Two-up books: zotero-agent `pdf-prep`

Need LLM to fix one paper’s metadata while writing?
  → zotero-mcp

Need a grounded summary of many text-layer PDFs, then one collection review?
  → paperful summarize, then synthesize

Need reproducible .bib for a paper submission?
  → bibcite fix / bibtex-tidy

Chat agent needs the whole public literature (graph, trends, author intel), not just Zotero?
  → Valency MCP Bond (complement Paperful for *your* PDFs and mirror)

Need a hosted cited review, “has anyone done this?”, or Kosmos on a dataset?
  → Edison Scientific. Keep Paperful for PDFs, the disk ledger, and Ask over held papers

Already have a reading list on disk and want gaps vs what your PDFs cite?
  → paperful refs gap (CLI or MCP refs_gap)
```

## Related docs

- [comparison.md](comparison.md) — short routing tables
- [architecture.md](architecture.md) — Paperful internals
- [config.md](config.md) — configuration and operations
