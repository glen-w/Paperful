# How Paperful compares

A plain-language map of where Paperful sits next to Zotero plugins, bibliography
fixers, Mendeley export cleaners, and DOI-centric download scripts.

**Last reviewed:** 2026-10-07. Feature lists for other products are based on public
docs and positioning — not paid pilots or exhaustive release testing.

Vendor-by-vendor notes live in the [comparison reference](comparison-reference.md).
Prefer this page for “is this the right tool?”

## Short answer

| If you need… | Look at… |
|--------------|----------|
| A platform-agnostic **mirror** of the library (backup, and a way out if the citation manager changes). **Zotero is well tested.** Mendeley and EndNote adapters are seeking testers | **Paperful** `snapshot` / `restore` — [quiet mirror](quiet-mirror.md). Do not treat the other adapters as proven |
| Bulk **missing-PDF** fetch for a Zotero library (OA → campus proxy → optional Sci-Hub), collection-shaped folders, resumable CLI | **Paperful** (this repo) |
| **In-Zotero** “find OA PDF” plus optional grey-zone sources in one plugin UI | [zotero-zotadata](https://github.com/ydeng11/zotero-zotadata) |
| **Attachment hygiene** (broken links, rename, stored-to-linked, duplicate files on one parent) | **Paperful** `attachments` (report by default; surgery with a flag and `--apply`). In-app: [StorScan](https://github.com/brian-j-griffith/StorScan), [Attanger](https://github.com/MuiseDestiny/zotero-attanger), [ZotMoov](https://github.com/wileyyugioh/zotmoov) |
| **Metadata repair** (DOI/ISBN/arXiv bulk update, parent-from-PDF) | Paperful `lint` / `fix-metadata`, or [ZotMeta](https://github.com/RoadToDream/ZotMeta) |
| **Duplicate parents** in one collection (DOI, then title+year). Review a pack, then merge the PDF, notes, and better fields onto one item. | **Paperful** `dedupe` |
| **Grey literature** landings (UN, FAO, ISA, and similar) kept as real PDFs | **Paperful** playbooks in `direct` / `landing`. Journal-style OA fetch is the row above |
| **Batch notes** from PDFs you already have: one grounded summary per item, then a collection review. Local model, off by default. Scans need `ocr` first | **Paperful** `summarize` / `synthesize` |
| **Scriptable library surgery** (merge, enrich, disk GC, two-up scan split) via CLI/MCP | [zotero-agent](https://github.com/alex-roc/zotero-agent) |
| **AI assistant** read/write over the library, including chat and (on some forks) OCR of scans | zotero-mcp forks ([richardjlyon](https://github.com/richardjlyon/zotero-mcp), [cookjohn](https://github.com/cookjohn/zotero-mcp), [mcp-zotero](https://github.com/Xevos117/mcp-zotero)) |
| **`.bib` normalize / dedupe / upgrade preprints** (no Zotero required) | [bibcite](https://github.com/leo1oel/bibcite), [bibtex-tidy](https://github.com/FlamingTempura/bibtex-tidy), [bibmanager](https://bibmanager.readthedocs.io/) |
| **Mendeley** dedup inside the app; clean **exported** BibTeX | Mendeley Duplicates smart collection; export cleaners such as [mendeley_bibtex_cleaner](https://gist.github.com/alexandrehuat/6d3263f73ccae87d0107977978316c02) |
| **DOI-list PDF batch** without Zotero | [paperscraper](https://github.com/jannisborn/paperscraper) |
| **Grow the library** from a keyword, one or more DOIs’ references, one or more ORCIDs, a similar-paper hop, or a hybrid hop, then optionally fill PDFs. Citation maps such as Research Rabbit link out; Paperful downloads. Re-check later with **watch** (baseline once, then propose new arrivals on disk; you schedule `watch run`) | **Paperful snowball** — dry-run, `approve-each`, `approve-batch`, `--gate auto`, `--fetch-pdfs`, and `watch` ([snowball](snowball.md)). In-app one-hop browsers stay separate ([zotero-snowball](https://github.com/socratic-irony/zotero-snowball), [Citegeist](https://github.com/phdemotions/zotero-citegeist)). General harvesters without the mirror: [findpapers](https://github.com/jonatasgrosman/findpapers), [opencite](https://github.com/neuromechanist/opencite) |
| **People you follow** → their new papers (ORCID / OpenAlex; no hop; corpus `suggest`; saved social HTML/CSV, no live scrape) | **Paperful authorwatch** ([authorwatch](authorwatch.md)). Distinct from `snowball watch`. |
| **Local workbench** over the same CLI (Wanted / Discover; Advanced Repair, Mirror, Index Ask, Briefs) | **Paperful** `docker compose up` or `paperful serve` — [gui.md](gui.md). Grab fetches to disk; Attach is the library write. Not Zotero-in-the-browser. TTY login stays the CLI |
| “Just use what ships in Zotero” | Built-in **Find Available PDF** plus [custom PDF resolvers](https://www.zotero.org/support/kb/custom_pdf_resolvers) |

Paperful does **not** replace a full metadata editor, an in-app attachment
reorganiser, or a `.bib` linter. It does **not** promise phone sync, mobile
apps, or WebDAV — those stay with the citation manager. `attachments`
reports layout problems and, with a flag plus `--apply`, repairs them from
`out/`. `--link` is that surgery, not a Storage client. Incoming downloads,
author folders, and tablet send/get stay with Attanger and ZotMoov. The jobs
are library, find, completeness, mirror, and control. Fetch and lint run on
disk; the manager is a write-back adapter (`manager = "zotero"` is well
tested; Mendeley and EndNote are seeking testers).

Architecture: [architecture.md](architecture.md).

## Where Paperful sits

Most tools in this space optimise one or more of:

1. **Acquire PDFs** — open access, proxy, optional Sci-Hub, Scholar
2. **Fix metadata** — DOI discovery, Crossref/OpenAlex fills
3. **Fix files** — rename, linked paths, broken attachments, duplicate PDFs
4. **Fix `.bib` / exports** — keys, duplicates, Mendeley-specific fields
5. **Automate / agent** — MCP, CLI, batch undo

Those map onto Paperful’s jobs. **Find** is **(1)**: open access, campus
proxy, playbooks, and an opt-in AI browser after the scripted lanes fail.
**Completeness** is **(2)** (`lint` / `fix-metadata`, patches on disk,
`--apply` to the adapter) plus duplicate review (`dedupe`) and opt-in
`summarize` / `synthesize`. **Mirror** is the portable disk copy
(`snapshot` / `restore`; `snapshot --pdfs all` also copies PDFs already in
Zotero). **(3)** is `paperful attachments`: a report by default, and
`--fix-broken`, `--merge-files`, `--rename`, or `--link` only with
`--apply`. **(4)** is other tools. **(5)** here is CLI `--format json`
(`paperful.agent.json.v1` + exits) on batch verbs, plus a thin optional
`paperful mcp` for dry-run `refs_gap` and read-only `ask`. A chat agent over
the live Zotero catalogue stays with zotero-mcp.
Scanned PDFs get a text layer from `paperful ocr`; two-up split and shrink
stay with zotero-agent `pdf-prep`. **Library** is the catalogue you already
have, grown with `snowball` when you ask. **Control** is disk-first
write-back and opt-in sources.

```text
Reference library  →  paperful snapshot  →  out/<collection>/<stem -- KEY>/
                 →  paperful run       →  same folder (PDF)  →  attach (Zotero 10+)
                 →  paperful restore --apply  →  missing items only
                      ↑
        OA / CORE / arXiv / EZProxy / Scholar / htmlpdf / grey playbooks / (opt-in Sci-Hub)

Optional, off until [llm].enabled (needs a text layer; `paperful ocr` adds one):
  summarize · synthesize · recover (browser agent; last run lane after vault browsers fail)

Parallel tracks:
  Metadata: paperful lint/fix-metadata, ZotMeta, zotero-agent
  Duplicates: paperful dedupe (merge onto the keeper, then trash the extra), Zotero’s duplicate UI, zotero-agent
  Attachments: paperful attachments (CLI). In-app: StorScan, Attanger, ZotMoov
  Chat: zotero-mcp. Two-up scan split: zotero-agent pdf-prep
  Text layer for image PDFs: paperful ocr
  Bib CLI (bibcite, bibtex-tidy)
```

## Capability snapshot

Legend: **Yes** = first-class · **Partial** = adjacent or lighter · **No** = absent or out of scope.

| Capability | Paperful | Zotero built-in | zotero-zotadata | StorScan | ZotMeta | zotero-agent |
|------------|----------|-----------------|-----------------|----------|---------|--------------|
| Bulk fetch **missing** PDFs | Yes | Partial | Yes | Partial | No | Partial |
| Collection-scoped batch runs | Yes | No | Partial | Partial | Partial | Yes |
| Resumable manifest / retry | Yes | No | Partial | Partial | Partial | Partial |
| Open-access source stack | Yes | Partial | Yes | Partial | No | Partial |
| Campus **EZProxy** (cookie session) | Yes | No | No | No | No | No |
| **Sci-Hub** (explicit opt-in) | Yes | Partial | Yes | No | No | Partial |
| Metadata verify / lint | Yes | No | Yes | No | Yes | Yes |
| Metadata **apply** to library | Yes (`fix-metadata --apply`) | No | Yes | No | Yes | Yes |
| Broken link / file layout repair | Partial (`attachments`; report by default, surgery with `--apply`) | Partial | Partial | Yes | No | Partial |
| Dedupe / merge items | Yes (`dedupe --apply` merges children and better fields, then trashes the extra; Zotero only) | Partial | No | Partial | No | Yes |
| Runs **outside** Zotero UI (CLI) | Yes | No | No | No | No | Yes |
| Work on disk, then write-back | Yes | No | No | Partial | No | Partial |
| Per-item folder you can restore from | Yes (`snapshot` / `restore`; does not overwrite fields) | No | No | No | No | No |
| Copy PDFs **already in** Zotero onto disk | Partial (`snapshot --pdfs all`) | Partial (File → Export PDFs) | No | No | No | No |
| Grey-literature landing playbooks | Yes | No | No | No | No | No |
| Grounded summary / collection review | Partial (opt-in, local, text layer) | No | No | No | No | Partial (public README: summarize PDFs into notes) |
| OCR for scanned PDFs | Partial (`ocr`, OCRmyPDF text layer on disk) | No | No | No | No | Partial (`pdf-prep`, OCRmyPDF) |

zotero-mcp and BibTeX-cluster columns: [comparison reference](comparison-reference.md#capability-snapshot).

## What Paperful does not do today

- Mendeley and EndNote adapters exist and are **seeking testers**. Zotero is the well-tested path. EndNote writes are an import bundle (File → Import); Paperful does not edit the `.enl` database
- Author-folder layouts, incoming-download matching, and tablet send/get (`attachments --link` can point a personal library at `out/`; it is off unless you pass it)
- Mendeley and EndNote item merge (`dedupe --apply` is Zotero-only)
- Two-up scan split, or a chat agent over the library (`ocr` adds a text layer; it does not split pages. `summarize` / `synthesize` / `recover` are opt-in and local)
- Hosted multi-user service
- Jeffersonian transcription or qualitative coding

## Choosing in one glance

```text
Have Zotero, many items without PDFs, want a resumable CLI + folder tree?
  → paperful

Want the files and records on disk, independent of Zotero cloud quota?
  → paperful snapshot (restore recreates only missing items)

Want grounded notes, then one review of a collection, without a chat session?
  → paperful summarize, then synthesize (local model; text-layer PDFs)

Library DOI looks wrong but you already have the PDF?
  → paperful lint, then fix-metadata --apply

Want the same job but stay inside Zotero with one plugin?
  → zotero-zotadata (review legal/ToS for its extra sources)

Library is messy on disk (broken links, dup PDFs on one item, filenames)?
  → paperful attachments (report). Add --fix-broken, --merge-files, --rename, or --link with --apply to write.
  Author folders, incoming downloads, tablet send/get → StorScan, Attanger, ZotMoov

Only a .bib from Mendeley/Zotero export?
  → bibcite / bibtex-tidy / JabRef

Want a new collection from a keyword, one or more papers’ bibliographies, one or more ORCIDs, or one hop from the top hits?
  → paperful snowball (see snowball.md). Pass several DOIs or ORCID iDs in one command. One-shot PDF fill is --fetch-pdfs with --gate auto

Want new works matching a saved snowball profile, without a discovery daemon?
  → paperful snowball watch (baseline once, then propose). The rollup is `snowball watch digest` or `watch run --digest`. Schedule that yourself ([Watch](snowball.md#watch))

Want new papers from people you already follow (ORCID / OpenAlex ids, no hop)?
  → paperful authorwatch (see authorwatch.md). `suggest -C` ranks corpus people; import CSV or a saved RG/LinkedIn/Academia HTML page (`--file`). No live social scrape.

Just a list of DOIs, no Zotero?
  → paperscraper

Scanned PDFs with no text layer?
  → paperful ocr (disk text layer). Two-up books: zotero-agent pdf-prep

Want a chat agent in the loop?
  → a zotero-mcp fork
```

More branches: [comparison reference](comparison-reference.md#choosing-in-one-glance).
How far a snowball hop reaches: [How a hop is cut](snowball.md#how-a-hop-is-cut).

## Related docs

- [architecture.md](architecture.md) — disk-first adapters, circuit breaker, Sci-Hub
- [ROADMAP.md](ROADMAP.md) — mirror contract toward 1.0; optional LLM; snowball phases
- [snowball.md](snowball.md) — keyword, multi-DOI / multi-ORCID, collection, and hybrid library building
- [authorwatch.md](authorwatch.md) — people lists → new papers (suggest / accept / import; no hop)
- [comparison-reference.md](comparison-reference.md) — vendor notes and extra tables
- [commands.md](commands.md) — CLI and disk artifacts
- [config.md](config.md) — `config.toml` and operations
