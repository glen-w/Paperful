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
daemon. Paperful remains a **local CLI**. House sync of `out/` (and careful
use of `state/`) lives outside this repo (e.g. Syncthing on a homeserver).
See the Toast Heaven ops plan
`docs/operations/syncthing-personal-and-research.md` in the `server` repo when
that tree is nearby. Why this shape: [Why Paperful](why.md).

The mirror is also where Paperful does its work. A command refreshes this
tree from the manager, then reads it; the manager API is kept to that
refresh and to explicit write-back. The rule and how the code follows it:
[Mirror first](architecture.md#mirror-first).

## Roles

| Layer | Role |
| --- | --- |
| **Zotero** | Catalogue, collections, citations, annotations; `storage/` holds `imported_file` attachments after attach; phone/WebDAV sync is Zotero’s job |
| **`out/<collection>/<stem -- KEY>/`** | Quiet mirror. One folder per item: `record.json` (`paperful.item.v1`), optional PDF, `notes/`. A refresh keeps one for every item, including items with no PDF |
| **`state/`** | Append-only history (manifest, patches, dedupe, runs, authorwatch lists) plus secrets. `out/_history.json` points at the ledgers and does not copy sessions, cookies, or the API key |

**Dual store for now.** Attach stays **`imported_file`**: bytes land under `out/`,
then upload into Zotero `storage/`. Duplicate bytes are acceptable.
`paperful attachments` reports ghosts, broken links, and same-file duplicates
and does not change that default. `--link` with `--apply` is the opt-in
cutover: a personal library can point at the PDF under `out/` and drop the
stored child. Group libraries cannot use linked files, so `--link` refuses
them. Tablet send/get stays with Zotero.

```text
Zotero library  →  paperful sync       →  out/<collection>/<stem -- KEY>/
                    (and the refresh every command starts with)
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
  annotations.json          # highlights, when there are any
out/_index.jsonl
out/_collections.json
out/_sync.json              # library version last refreshed to
out/_history.json
```

`record.json` is the restore unit (`paperful.item.v1`, **0.x may add keys**).
It holds identity, creators, abstract, tags, Extra, leftover type-specific
fields, collection membership, attachment rows, fetch provenance, and the note
filenames. An item in several collections gets one folder per path: the PDF is
hardlinked, `record.json` is copied.

`[mirror].pdfs` (or `sync --pdfs`, `snapshot --pdfs`):

| Mode | What happens to a PDF the manager already holds |
| --- | --- |
| `all` (default) | Copied into the item folder. `paperful sync` works through the whole library once and can be stopped and run again; after that only changed items are looked at. Skips linked-URL-only items |
| `lazy` | Copied into the item folder the first time a command needs it (`lint`, `summarize`, `ocr`, `export`). `additional` is the old name and still loads |
| `none` | Kept out of the mirror. A command that needs one makes a throwaway copy under `state/pdf-cache/`. Does not delete a PDF that is already on disk |

`run` always writes a PDF it downloads. That setting does not turn fetching off.

An item that is trashed, merged away, or deleted in the manager keeps its
folder. `[mirror].gone` chooses how: `mark` (default) leaves the folder where
it is and writes `"library": {"state": "trashed"}` (or `gone`) in the record,
with the keeper's key after a merge; `trash` also moves the folder under
`out/_trash/`. Commands leave marked items out. An item restored in the
manager comes back on the next refresh. Paperful never deletes a file under
`out/`.

A folder is named for the item's author, year, and title; the key at the end
is what identifies it. When the title changes the folder is renamed in
place. When an item moves between collections its folder moves with it, and
anything left in a collection it has gone from is folded into a folder it is
still in.

`paperful restore` reads these folders. Without `--apply` it only counts.
`--apply` creates a missing collection path and a missing parent (matched by
item key, then DOI, then title+year), attaches a local PDF when the live item
has none, and adds a note that is not already there. It does not trash items
and does not overwrite bibliographic fields.

## What “quiet” means

- No second reading UI and no replacement for Zotero desktop.
- No long-running sync service inside Paperful.
- Folder tree is for browse, scripts, and RAG-adjacent tooling that want paths
  and a per-item record.

## History

`state/` stays the append-only history. `out/_history.json` names those
ledgers (manifest, metadata patches, dedupe audit, run reports) so a copy of
`out/` can be audited next to `state/`. Reconstructing a failed fetch still
requires `state/manifest.jsonl`. Annotations are copied as data
(`annotations.json`); they are not drawn onto the PDF. Attachments that are
not PDFs have a row in the record and no bytes in the mirror. Standalone
notes are not mirrored.

## Non-goals (near term)

- Not a second Zotero
- Not a linked-file cutover unless you pass `attachments --link --apply`
- Not a hosted multi-user warehouse
- Not auto Sci-Hub or silent cloud defaults

## Related

- [architecture.md](architecture.md) — disk-first adapters and data flow
- [zotero.md](zotero.md) — attachment modes (`imported_file` vs linked)
- [mendeley.md](mendeley.md) / [endnote.md](endnote.md) — other adapters (seeking testers)
- [ROADMAP.md](ROADMAP.md) — the disk mirror is core; Zotero is the tested 1.0 path
- [why.md](why.md) — storage, grey literature, and what is true today
- [commands.md](commands.md) — `out/` path layout
