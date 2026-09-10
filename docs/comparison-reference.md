# How paperful compares — reference

Vendor-by-vendor notes and longer capability tables. Most readers only need
[How paperful compares](comparison.md).

**Last reviewed:** 2026-09-10. Feature lists for other products are based on public
docs and positioning — not paid pilots.

## Capability snapshot

### Zotero-centric (extended)

Legend: **Yes** · **Partial** · **No**.

| Capability | paperful | Zotero built-in | zotero-zotadata | StorScan | ZotMeta | zotero-agent | zotero-mcp (typical) |
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
| Dedupe / merge items | No | Partial | No | Partial | No | Yes | Partial |
| CLI / automation | Yes | No | No | No | No | Yes | Yes (MCP) |
| Disk-first then write-back | Yes | No | No | Partial | No | Partial | No |

### Zotero version and attach (indicative)

Verify against each project’s latest release before upgrading Zotero.

| Tool | Typical Zotero | Notes |
|------|----------------|-------|
| paperful | 7–9 download; **10+** attach and `fix-metadata --apply` | Local HTTP API |
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

| Capability | paperful | paperscraper | pyzotero + custom scripts |
|------------|----------|--------------|----------------------------|
| Needs a library manager | Adapter (Zotero now) | No | Optional |
| Input | Library items / collections | DOI JSONL / dict | API keys or local DB |
| Publisher TDM APIs | No | Yes (Elsevier/Wiley, etc.) | DIY |
| Attach back to items | Yes | No | DIY |
| EZProxy / Sci-Hub | Yes / opt-in | No / DIY | DIY |

## Complementary: Zotero plugins and built-ins

### paperful

- **Sites:** [GitHub](https://github.com/glen-w/Paperful) · this repo
- **Fit:** CLI gap-filler. Routed OA stack (including CORE with API key), optional EZProxy and Scholar cookies, opt-in Sci-Hub, collection-mirrored `out/` tree, `manifest.jsonl`, attach on Zotero 10+. Identifier verify (Crossref/OpenAlex/PubMed) + lint + `fix-metadata` on disk, then adapter write-back.
- **With others:** StorScan or Attanger when paths and linked files are wrong; zotero-agent for dedupe.
- **Not a substitute for:** In-app plugin UX, or `.bib` hygiene tools.

### Zotero built-in

- **Sites:** [Zotero](https://www.zotero.org/) · [custom PDF resolvers](https://www.zotero.org/support/kb/custom_pdf_resolvers)
- **Fit:** Per-item **Find Available PDF**, identifier lookup, duplicate merge UI.
- **With paperful:** Built-in capture on save; paperful for batch backfill.

### zotero-zotadata

- **Sites:** [GitHub](https://github.com/ydeng11/zotero-zotadata)
- **Fit:** Plugin combining attachment validation, multi-source PDF retrieval, and metadata updates.
- **With paperful:** Overlapping PDF mission; zotodata stays in Zotero.

### StorScan

- **Sites:** [GitHub](https://github.com/brian-j-griffith/StorScan)
- **Fit:** Attachment operations — scan, fix misplaced linked files, merge duplicate files.
- **With paperful:** paperful fills missing PDFs; StorScan repairs layout.

### ZotMeta

- **Sites:** [GitHub](https://github.com/RoadToDream/ZotMeta)
- **Fit:** Bulk metadata from DOI, ISBN, arXiv; PDF cache identifier extraction.
- **With paperful:** Overlaps `lint` / `fix-metadata`; ZotMeta is in-app.

### Attanger and ZotMoov

- **Sites:** [Attanger](https://github.com/MuiseDestiny/zotero-attanger) · [ZotMoov](https://github.com/wileyyugioh/zotmoov)
- **Fit:** ZotFile-era workflows on Zotero 7+ — match downloads, rename/move linked files.
- **With paperful:** Incoming-file organisation vs remote PDF hunt.

### zotero-agent

- **Sites:** [GitHub](https://github.com/alex-roc/zotero-agent)
- **Fit:** Local-first CLI and MCP via bridge plugin — search, dedupe, merge, enrich, `pdf-fetch`.
- **With paperful:** Agent for hygiene; paperful for collection runs with manifest and folder mirror.

### zotero-mcp ecosystem

- **Sites:** [richardjlyon/zotero-mcp](https://github.com/richardjlyon/zotero-mcp) · [cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp) · [mcp-zotero](https://github.com/Xevos117/mcp-zotero)
- **Fit:** LLM-facing search, PDF text, create items, sometimes Unpaywall attach.
- **With paperful:** MCP for interactive research; paperful for unattended gap fills.

### ZotFile (legacy)

- **Sites:** [zotfile.com](https://zotfile.com/)
- **Status:** Not compatible with Zotero 7+. Use Attanger / ZotMoov.

## BibTeX, Mendeley, and scripts

### bibcite and bibtex-tidy

- **Sites:** [bibcite](https://github.com/leo1oel/bibcite) · [bibtex-tidy](https://flamingtempura.github.io/bibtex-tidy/)
- **Fit:** Resolve papers to canonical BibTeX, dedupe, tidy, upgrade preprints.
- **With paperful:** Orthogonal until a bib-file `LibraryBackend` exists.

### bibmanager

- **Sites:** [Read the Docs](https://bibmanager.readthedocs.io/)
- **Fit:** Unified BibTeX database, ADS integration, optional PDF fetch from ADS.

### Mendeley

- **Fit:** Reference Manager **Duplicates** smart collection; Desktop merge UI. paperful’s `manager = "mendeley"` is not implemented yet — import or sync into Zotero first.

### paperscraper

- **Sites:** [GitHub](https://github.com/jannisborn/paperscraper)
- **Fit:** Python metadata + `save_pdf` from DOIs; publisher TDM API keys.
- **With paperful:** paperscraper when the input is a DOI list, not a collection tree.

## Choosing in one glance

```text
Need to export PDFs already in Zotero storage to a folder?
  → pyzotero dump (not paperful)

Need tablet send/get after ZotFile died?
  → ZotMoov custom menus (+ Attanger)

Need LLM to fix one paper’s metadata while writing?
  → zotero-mcp

Need reproducible .bib for a paper submission?
  → bibcite fix / bibtex-tidy
```

## Related docs

- [comparison.md](comparison.md) — short routing tables
- [architecture.md](architecture.md) — paperful internals
- [config.md](config.md) — configuration and operations
