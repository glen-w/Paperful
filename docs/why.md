# Why Paperful

The fill pipeline — sources, campus login, tidy around a run — is
[How it works](how-it-works.md). This page is why the product is shaped this
way.

Paperful is a research helper for a reference library you already keep. It
cleans the records, finds missing PDFs, and summarises papers, then keeps a
platform-agnostic mirror you can back up and move. The work stays on this
machine.

**Ladder:** `gaps` / `attachments` honesty → `run` fills `out/` → you read
the mirror → then summarize or Ask. **attach** writes the PDF into Zotero.
Do not say **admit**. [Terms](TERMS.md).

Zotero is the catalogue that is well tested. Mendeley and EndNote adapters
are in the tree and seeking testers. The mirror does not depend on which of
those you open tomorrow.

## Five jobs

**Library.** Collections, years, and item types are the scope.

- `collections` shows what you have.
- `snowball` proposes new works; parents are created only when the gate says so. [How a hop is cut](snowball.md#how-a-hop-is-cut).
- `import` / `export` speak RIS, BibTeX, and EndNote XML.
- The PDF write gate is **attach**, not admit.
- Zotero’s local API is the adapter to use. Mendeley and EndNote are seeking testers.

**Find.** Search for a missing PDF. Open access first, campus EZProxy when you have it, playbooks (and an opt-in AI browser) for odd landings.

- Not every paywalled or DOI-less item comes back.
- Google Scholar stays off until you opt in.
- [How it works](how-it-works.md) · [Sources](sources.md).

**Completeness.** Honest identifier, reviewed duplicate, PDF when one could be found, optional grounded note.

- `gaps` counts misses. `lint` / `fix-metadata` propose patches; `--apply` writes them.
- `dedupe` reviews, then merges onto the keeper.
- `summarize` / `synthesize` need `[llm].enabled`. `ocr --apply` adds a text layer on disk.
- `paperful all` is gaps → find → lint → fix → summarise.

**Mirror.** `out/` is a folder copy, not a citation manager. One folder per item (`record.json`, optional PDF, notes). A closed manager costs write-back, not the read work.

- `restore --apply` creates only what the catalogue is missing.
- Copy `out/` yourself. Not a sync or WebDAV client. [Quiet mirror](quiet-mirror.md).

**Control.** Disk first; write-back is a separate step. Dry-run before a big fetch. Scholar and the local model are opt-in. Session passwords are not in config. PDFs keep a provenance stamp.

Python, the Zotero local API, Ollama or LiteLLM, Docker.

## What is true today

| Claim | Status |
| --- | --- |
| Zotero read, fetch, lint, attach, snapshot, restore | Well tested. This is the adapter to use |
| Open-access find, campus EZProxy, user playbooks | Shipped. Each item hits sources that match its metadata unless `--try-all` |
| AI browser for lanes the scripts miss | Opt-in. `[llm].enabled` plus `paperful[browser-agent]` (Python 3.11+). Last lane on `run`, or `recover --item` |
| Summaries and a collection review | Opt-in local model. Needs a text layer. Off until you enable it |
| Disk mirror you can copy without the manager | Shipped (`out/` + `state/`). `import` / `export` for RIS, BibTeX, EndNote XML |
| Mendeley (`manager = "mendeley"`, REST at api.mendeley.com) | Seeking testers. Needs an app at dev.mendeley.com and `paperful session login mendeley`. Not proven against a real library here |
| EndNote (`manager = "endnote"`, local `.enl`) | Seeking testers. Reads `sdb.eni`. Writes stage `state/endnote-import/` for File → Import. Paperful does not edit the EndNote database, and it cannot trash items there |
| Text layer for scanned PDFs | `paperful ocr` (OCRmyPDF on the disk file). Two-up page split stays with zotero-agent |
| Linked-file cutover, hosted multi-user service, a second reading app | Cutover is `attachments --link --apply` (off by default; personal library only). Hosted service and a second reading app are not the product |
| Local workbench (`paperful serve`) | Landed, not tagged 1.0. `docker compose up` opens Wanted first, then Discover; Advanced adds Repair, Mirror, Index, and Briefs. Grab fetches to disk; Attach is the library write. TTY stays the shell. Screenshots and click-throughs: [Walkthroughs](walkthroughs.md). [GUI](gui.md) |

## Related

- [Walkthroughs](walkthroughs.md) — first fill, grow, tidy
- [How it works](how-it-works.md) — fill pipeline
- [Quiet mirror](quiet-mirror.md) — folder contract
- [How Paperful compares](comparison.md)
- [Roadmap](ROADMAP.md) — Zotero is the tested path; Mendeley and EndNote are seeking testers (not 1.0 blockers)
- [Workbench](gui.md) — localhost HTML over the same CLI verbs
