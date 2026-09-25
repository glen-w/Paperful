# Why paperful

Paperful is a research helper for a reference library you already keep. It
cleans the records, finds missing PDFs, and summarises papers, then keeps a
platform-agnostic mirror you can back up and move. The work stays on this
machine.

Zotero is the catalogue that is well tested. Mendeley and EndNote adapters
are in the tree and seeking testers. The mirror does not depend on which of
those you open tomorrow.

## Five jobs

**Library.** The object is the reference library: collections, years, item
types. `collections` shows what you have. `snowball` proposes new works from
a keyword, a DOI, an ORCID, or a seed collection, and creates items only when
the gate says so. [How a hop is cut](snowball.md#how-a-hop-is-cut) shows depth,
direction, and the two caps. `import` and `export` speak RIS, BibTeX, and EndNote XML.
The live catalogue is an adapter. Zotero’s local API is the one to use.
Mendeley (REST) and EndNote (read the `.enl`; writes are an import bundle)
are seeking testers.

**Find.** Missing PDFs are searched. Open-access indexes come first
(Unpaywall, OpenAlex, arXiv, bioRxiv/medRxiv, Europe PMC, Semantic Scholar,
CORE). Campus EZProxy is next, when you have a subscription. Sites that do
not fit that pattern — grey literature, field-specific hosts, odd landing
pages — use playbooks you write, and, if you turn it on, an AI browser after
the scripted lanes fail. Google Scholar and Sci-Hub stay off until you opt
in. Paperful does not fetch every paywalled or DOI-less item. Sci-Hub
coverage after ~2021 is thin; recent paywalled papers are a campus-access
problem when your library has the subscription. See
[Sci-Hub](scihub.md).

**Completeness.** A record is in good shape when the identifier is honest,
the duplicate has been reviewed, a PDF is attached when one could be found,
and — if you want it — a grounded summary sits on the item. `gaps` counts
what is missing. `lint` and `fix-metadata` propose patches on disk;
`--apply` writes them. `dedupe` writes a review pack and, with `--apply`, writes a spare-copy line,
then merges the extra parent's PDF, notes, and better fields onto the keeper
before trashing that parent. `summarize` writes one note from a text-layer PDF;
`synthesize` reviews those notes for a collection. `paperful all` runs the
usual chain: gaps, find, lint, fix, summarise. The model is off until
`[llm].enabled`. `paperful ocr --apply` adds a text layer to scanned PDFs
on disk so those commands can read them.

**Mirror.** `out/` is a copy of the library that is not a citation manager:
one folder per item (`record.json`, optional PDF, notes) plus a collection
tree. `snapshot` writes it. `restore --apply` creates only what the live
catalogue is missing and does not overwrite fields already there. That tree
is the backup. RIS, BibTeX, and EndNote XML are the interchange. Copy `out/`
with your own sync; paperful is not a sync service and not a WebDAV client.
Phone sync stays with the catalogue. See [Quiet mirror](quiet-mirror.md).

**Control.** Downloads, patches, and summaries land on disk first.
Write-back is a separate step you ask for. Dry-run before a big fetch.
Scholar, Sci-Hub, and the local model are opt-in. Session passwords are not
stored in the config. Attachments carry a provenance stamp. The parent item
also gets a readable line ("Free copy from Unpaywall.") unless
`[remarks].surface` is `off`. Docker runs the
tool; the catalogue and a headed login stay on the host.

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
| EndNote (`manager = "endnote"`, local `.enl`) | Seeking testers. Reads `sdb.eni`. Writes stage `state/endnote-import/` for File → Import. paperful does not edit the EndNote database, and it cannot trash items there |
| Text layer for scanned PDFs | `paperful ocr` (OCRmyPDF on the disk file). Two-up page split stays with zotero-agent |
| Linked-file cutover, hosted multi-user service, a second reading app | Not the product |

## Related

- [Quiet mirror](quiet-mirror.md) — folder contract
- [How paperful compares](comparison.md)
- [Roadmap](ROADMAP.md) — Zotero is the tested path; Mendeley and EndNote are seeking testers
