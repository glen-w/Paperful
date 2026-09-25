# Quiet mirror (`out/`)

The folder tree under `out/` is the platform-agnostic copy of the library:
backup, and a way to leave the citation manager. One folder per item
(`record.json`, optional PDF, notes), plus a collection tree. `snapshot`
writes every scoped item; `restore` puts back only what the live catalogue
is missing and does not overwrite fields already there. RIS, BibTeX, and
EndNote XML (`import` / `export`) are the other door.

Zotero cloud storage is small, and WebDAV is more ops than most people want.
Zotero stays the bibliographic catalogue and attach target that is well
tested. Mendeley and EndNote adapters exist for a co-author on another
manager — they are **seeking testers**. This is a product stance, not a new
daemon. paperful remains a **local CLI**. House sync of `out/` (and careful
use of `state/`) lives outside this repo (e.g. Syncthing on a homeserver).
See the Toast Heaven ops plan
`docs/operations/syncthing-personal-and-research.md` in the `server` repo when
that tree is nearby. Why this shape: [Why paperful](why.md).

## Roles

| Layer | Role |
| --- | --- |
| **Zotero** | Catalogue, collections, citations, annotations; `storage/` holds `imported_file` attachments after attach; phone/WebDAV sync is Zotero’s job |
| **`out/<collection>/<stem -- KEY>/`** | Quiet mirror. One folder per item: `record.json` (`paperful.item.v1`), optional PDF, `notes/`. `snapshot` writes every scoped item, including items with no PDF |
| **`state/`** | Append-only history (manifest, patches, dedupe, runs) plus secrets. `out/_history.json` points at the ledgers and does not copy sessions, cookies, or the API key |

**Dual store for now.** Attach stays **`imported_file`**: bytes land under `out/`,
then upload into Zotero `storage/`. Duplicate bytes are acceptable. Do **not**
treat linked-file cutover (warehouse-as-only-bytes) as a 0.x goal.

```text
Zotero library  →  paperful snapshot  →  out/<collection>/<stem -- KEY>/
                 →  paperful run       →  same folder (PDF + record.json)
                                      →  attach (imported_file)
out/  →  paperful restore --apply  →  missing Zotero items only
```

## Item folder

```text
out/<collection>/<Author - Year - Title -- KEY>/
  record.json
  <human name>.pdf          # optional
  notes/<tag-or-key>.html
out/_index.jsonl
out/_collections.json
out/_history.json
```

`record.json` is the restore unit (`paperful.item.v1`, **0.x may add keys**).
It holds identity, creators, abstract, tags, Extra, leftover type-specific
fields, collection membership, attachment rows, fetch provenance, and the note
filenames. An item in several collections gets one folder per path: the PDF is
hardlinked, `record.json` is copied.

`[mirror].pdfs` (or `snapshot --pdfs`):

| Mode | What snapshot does with bytes |
| --- | --- |
| `additional` (default) | Keeps PDFs `run` already fetched. Does not export files that were already in Zotero |
| `all` | Also exports an imported or linked-file PDF (`origin: zotero_export`). Skips a file whose MD5 is already in the folder. Skips linked-URL-only items |
| `none` | Records and notes only. Does not delete a PDF that is already on disk |

`run` always writes a PDF it downloads. That setting does not turn fetching off.

A flat `Author - Year - Title.pdf` with a legacy `*.paperful.json` card is
moved into the item folder by `snapshot`, or by the next `run` that saves that
file. The card is folded into `record.json` and removed. A second pass is a
no-op. `paperful doctor` ambers when flat PDFs and item folders are mixed.

`paperful restore` reads these folders. Without `--apply` it only counts.
`--apply` creates a missing collection path and a missing parent (matched by
item key, then DOI, then title+year), attaches a local PDF when the live item
has none, and adds a note that is not already there. It does not trash items
and does not overwrite bibliographic fields.

## What “quiet” means

- No second reading UI and no replacement for Zotero desktop.
- No long-running sync service inside paperful.
- Folder tree is for browse, scripts, and RAG-adjacent tooling that want paths
  and a per-item record.

## History

`state/` stays the append-only history. `out/_history.json` names those
ledgers (manifest, metadata patches, dedupe audit, run reports) so a copy of
`out/` can be audited next to `state/`. Reconstructing a failed fetch still
requires `state/manifest.jsonl`. PDF annotations inside Zotero are not
exported yet.

## Non-goals (near term)

- Not a second Zotero
- Not linked-file migration in 0.x
- Not a hosted multi-user warehouse
- Not auto Sci-Hub or silent cloud defaults

## Related

- [architecture.md](architecture.md) — disk-first adapters and data flow
- [zotero.md](zotero.md) — attachment modes (`imported_file` vs linked)
- [mendeley.md](mendeley.md) / [endnote.md](endnote.md) — other adapters (seeking testers)
- [ROADMAP.md](ROADMAP.md) — the disk mirror is core; Zotero is the tested 1.0 path
- [why.md](why.md) — storage, grey literature, and what is true today
- [commands.md](commands.md) — `out/` path layout
