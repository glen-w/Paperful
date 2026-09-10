# How paperful compares

A plain-language map of where paperful sits next to Zotero plugins, bibliography
fixers, Mendeley export cleaners, and DOI-centric download scripts.

**Last reviewed:** 2026-09-10. Feature lists for other products are based on public
docs and positioning — not paid pilots or exhaustive release testing.

Vendor-by-vendor notes live in the [comparison reference](comparison-reference.md).
Prefer this page for “is this the right tool?”

## Short answer

| If you need… | Look at… |
|--------------|----------|
| Bulk **missing-PDF** fetch for a Zotero library (OA → campus proxy → optional Sci-Hub), collection-shaped folders, resumable CLI | **paperful** (this repo) |
| **In-Zotero** “find OA PDF” plus optional grey-zone sources in one plugin UI | [zotero-zotadata](https://github.com/ydeng11/zotero-zotadata) |
| **Attachment hygiene** (broken links, rename, linked-file layout, merge duplicate files) | [StorScan](https://github.com/brian-j-griffith/StorScan), [Attanger](https://github.com/MuiseDestiny/zotero-attanger), [ZotMoov](https://github.com/wileyyugioh/zotmoov) |
| **Metadata repair** (DOI/ISBN/arXiv bulk update, parent-from-PDF) | paperful `lint` / `fix-metadata`, or [ZotMeta](https://github.com/RoadToDream/ZotMeta) |
| **Scriptable library surgery** (dedupe, enrich, `pdf-fetch`, disk GC) via CLI/MCP | [zotero-agent](https://github.com/alex-roc/zotero-agent) |
| **AI assistant** read/write over the library | zotero-mcp forks ([richardjlyon](https://github.com/richardjlyon/zotero-mcp), [cookjohn](https://github.com/cookjohn/zotero-mcp), [mcp-zotero](https://github.com/Xevos117/mcp-zotero)) |
| **`.bib` normalize / dedupe / upgrade preprints** (no Zotero required) | [bibcite](https://github.com/leo1oel/bibcite), [bibtex-tidy](https://github.com/FlamingTempura/bibtex-tidy), [bibmanager](https://bibmanager.readthedocs.io/) |
| **Mendeley** dedup inside the app; clean **exported** BibTeX | Mendeley Duplicates smart collection; export cleaners such as [mendeley_bibtex_cleaner](https://gist.github.com/alexandrehuat/6d3263f73ccae87d0107977978316c02) |
| **DOI-list PDF batch** without Zotero | [paperscraper](https://github.com/jannisborn/paperscraper) |
| “Just use what ships in Zotero” | Built-in **Find Available PDF** plus [custom PDF resolvers](https://www.zotero.org/support/kb/custom_pdf_resolvers) |

paperful does **not** replace a full metadata editor, an attachment reorganiser,
or a `.bib` linter. Fetch and lint run on disk; the manager is a write-back
adapter (`manager = "zotero"` today).

Architecture: [architecture.md](architecture.md).

## Where paperful sits

Most tools in this space optimise one or more of:

1. **Acquire PDFs** — open access, proxy, optional Sci-Hub, Scholar
2. **Fix metadata** — DOI discovery, Crossref/OpenAlex fills
3. **Fix files** — rename, linked paths, broken attachments, duplicate PDFs
4. **Fix `.bib` / exports** — keys, duplicates, Mendeley-specific fields
5. **Automate / agent** — MCP, CLI, batch undo

paperful is built for **(1)**, with **(2)** as `lint` / `fix-metadata` (patches
on disk, `--apply` to the adapter; PubMed PMID→DOI, Crossref/OpenAlex verify).
Disk layout is a collection mirror plus attach — not in-library reorganisation
(**(3)**). **(4)** and **(5)** are usually other tools.

```text
Zotero library  →  paperful run  →  out/<collection>/…pdf  →  attach (Zotero 10+)
                      ↑
        OA / CORE / arXiv / EZProxy / Scholar / htmlpdf / (opt-in Sci-Hub)

Parallel tracks:
  Metadata: paperful lint/fix-metadata, ZotMeta, zotero-agent
  Attachment plugins (StorScan, Attanger)
  Bib CLI (bibcite, bibtex-tidy)
```

## Capability snapshot

Legend: **Yes** = first-class · **Partial** = adjacent or lighter · **No** = absent or out of scope.

| Capability | paperful | Zotero built-in | zotero-zotadata | StorScan | ZotMeta | zotero-agent |
|------------|----------|-----------------|-----------------|----------|---------|--------------|
| Bulk fetch **missing** PDFs | Yes | Partial | Yes | Partial | No | Partial |
| Collection-scoped batch runs | Yes | No | Partial | Partial | Partial | Yes |
| Resumable manifest / retry | Yes | No | Partial | Partial | Partial | Partial |
| Open-access source stack | Yes | Partial | Yes | Partial | No | Partial |
| Campus **EZProxy** (cookie session) | Yes | No | No | No | No | No |
| **Sci-Hub** (explicit opt-in) | Yes | Partial | Yes | No | No | Partial |
| Metadata verify / lint | Yes | No | Yes | No | Yes | Yes |
| Metadata **apply** to library | Yes (`fix-metadata --apply`) | No | Yes | No | Yes | Yes |
| Broken link / file layout repair | No | Partial | Partial | Yes | No | Partial |
| Dedupe / merge items | No | Partial | No | Partial | No | Yes |
| Runs **outside** Zotero UI (CLI) | Yes | No | No | No | No | Yes |
| Work on disk, then write-back | Yes | No | No | Partial | No | Partial |

zotero-mcp and BibTeX-cluster columns: [comparison reference](comparison-reference.md#capability-snapshot).

## What paperful does not do today

- Mendeley write-back (config key reserved)
- Attachment path surgery (author folders, stored→linked conversion)
- Item merge/dedupe
- Hosted multi-user service
- Jeffersonian transcription or qualitative coding

## Choosing in one glance

```text
Have Zotero, many items without PDFs, want a resumable CLI + folder tree?
  → paperful

Library DOI looks wrong but you already have the PDF?
  → paperful lint, then fix-metadata --apply

Want the same job but stay inside Zotero with one plugin?
  → zotero-zotadata (review legal/ToS for its extra sources)

Library is messy on disk (broken links, dup PDFs, author folders)?
  → StorScan (+ Attanger for incoming downloads)

Only a .bib from Mendeley/Zotero export?
  → bibcite / bibtex-tidy / JabRef

Just a list of DOIs, no Zotero?
  → paperscraper
```

More branches: [comparison reference](comparison-reference.md#choosing-in-one-glance).

## Related docs

- [architecture.md](architecture.md) — disk-first adapters, circuit breaker, Sci-Hub
- [ROADMAP.md](ROADMAP.md) — core vs maybe-later; optional LLM title assist
- [comparison-reference.md](comparison-reference.md) — vendor notes and extra tables
- [commands.md](commands.md) — CLI and disk artifacts
- [config.md](config.md) — `config.toml` and operations
