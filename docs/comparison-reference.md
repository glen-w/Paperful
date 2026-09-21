# How paperful compares — reference

Vendor-by-vendor notes and longer capability tables. Most readers only need
[How paperful compares](comparison.md).

**Last reviewed:** 2026-09-21. Feature lists for other products are based on public
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
| Dedupe / merge items | Partial (`dedupe --apply` trashes extras; no field merge) | Partial | No | Partial | No | Yes | Partial |
| CLI / automation | Yes | No | No | No | No | Yes | Yes (MCP) |
| Disk-first then write-back | Yes | No | No | Partial | No | Partial | No |
| Per-item folder you can restore from | Yes | No | No | No | No | No | No |
| Copy PDFs **already in** Zotero onto disk | Partial (`snapshot --pdfs all`) | Partial (File → Export PDFs) | No | No | No | No (`export` is bibliography; `get_item_pdf_path` is a path) | Partial (`get_pdf_path`) |
| Grey-literature landing playbooks | Yes | No | No | No | No | No | No |
| Grounded summary / collection review | Partial (opt-in `summarize` / `synthesize`; text layer) | No | No | No | No | Partial (README: summarize PDFs into notes) | Yes (chat reads PDF text; the model writes the summary) |
| OCR for scanned PDFs | No | No | No | No | No | Partial (`pdf-prep`, OCRmyPDF) | Partial (some forks, e.g. Docling OCR pre-step) |

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
- **Fit:** Local library sidecar. Routed OA stack (including CORE with API key), optional EZProxy and Scholar cookies, opt-in Sci-Hub, grey-literature landing playbooks, collection-mirrored `out/` tree (`snapshot` / `restore`, including `snapshot --pdfs all` for PDFs already in Zotero, `manifest.jsonl`), attach on Zotero 10+. Identifier verify (Crossref/OpenAlex/PubMed) + lint + `fix-metadata` on disk, then adapter write-back. `dedupe` writes a review pack and, with `--apply`, trashes extra parents (DOI, then title+year). `gaps` counts missing PDFs and DOIs. Optional local `summarize` / `synthesize` and `recover` (last `run` lane after Scholar / EZProxy / htmlpdf fail, or `recover --item`; text layer; no OCR; not a chat agent). **Zotero is the well-tested adapter.** Mendeley (REST) and EndNote (read-only database plus an import bundle) are seeking testers.
- **With others:** StorScan or Attanger when paths and linked files are wrong; zotero-agent when you need a real merge (children, notes), disk GC, or OCR of scans; zotero-mcp when the work is a conversation.
- **Not a substitute for:** In-app plugin UX, `.bib` hygiene tools, or scan OCR.

### Zotero built-in

- **Sites:** [Zotero](https://www.zotero.org/) · [custom PDF resolvers](https://www.zotero.org/support/kb/custom_pdf_resolvers)
- **Fit:** Per-item **Find Available PDF**, identifier lookup, duplicate merge UI, File → Export PDFs (a one-off dump of files already on disk, not a restore ledger).
- **With paperful:** Built-in capture on save; paperful for batch backfill and for `snapshot` / `restore` when Zotero file storage is the wrong warehouse.

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
- **Fit:** Local-first CLI and MCP via bridge plugin — search, dedupe, merge, enrich, `pdf-fetch`, PDF notes, and `pdf-prep` OCR (OCRmyPDF) for scans. `export` writes bibliography formats, not a PDF folder tree.
- **With paperful:** Agent for hygiene, merge, and scans; paperful for collection runs with a manifest, EZProxy, grey-lit playbooks, and a folder you can restore from.

### zotero-mcp ecosystem

- **Sites:** [richardjlyon/zotero-mcp](https://github.com/richardjlyon/zotero-mcp) · [cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp) · [mcp-zotero](https://github.com/Xevos117/mcp-zotero)
- **Fit:** LLM-facing search, PDF text, create items, sometimes Unpaywall attach. Some forks OCR scans (Docling) or write reading notes from chat.
- **With paperful:** MCP when a person is in the loop, or when the PDF is a scan; paperful for unattended collection runs, the disk ledger, and batch `summarize` / `synthesize` on a text layer.

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

- **Fit:** Reference Manager **Duplicates** smart collection; Desktop merge UI. paperful can set `manager = "mendeley"` (REST, OAuth). That adapter is **seeking testers**. Zotero is the well-tested path.

### paperscraper

- **Sites:** [GitHub](https://github.com/jannisborn/paperscraper)
- **Fit:** Python metadata + `save_pdf` from DOIs; publisher TDM API keys.
- **With paperful:** paperscraper when the input is a DOI list, not a collection tree.

## Choosing in one glance

```text
Need PDFs already in Zotero copied into a collection-shaped tree, with a record per item?
  → paperful snapshot --pdfs all

Need a one-off dump of those PDFs from the Zotero UI?
  → File → Export PDFs

Need tablet send/get after ZotFile died?
  → ZotMoov custom menus (+ Attanger)

Need LLM to fix one paper’s metadata while writing, or to read a scan?
  → zotero-mcp (some forks OCR); zotero-agent `pdf-prep` for a local OCR pass

Need a grounded summary of many text-layer PDFs, then one collection review?
  → paperful summarize, then synthesize

Need reproducible .bib for a paper submission?
  → bibcite fix / bibtex-tidy
```

## Related docs

- [comparison.md](comparison.md) — short routing tables
- [architecture.md](architecture.md) — paperful internals
- [config.md](config.md) — configuration and operations
