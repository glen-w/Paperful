# Quiet mirror (`out/`)

**Who:** you want a browsable, syncable folder tree, or restore insurance.  
**Goal:** one folder per item under `out/`; later recreate only missing
catalogue rows with `restore --apply`.

Finish [Quick start](../start/quickstart.md) first. Filling PDFs first is
optional — `snapshot --pdfs all` can export files already in Zotero.

## Path

1. Confirm `doctor` is green and pick a collection scope.
2. Optional: run [Fill missing PDFs](fill-pdfs.md) so downloads already sit
   under `out/`.
3. Dry-run, then write the mirror:

```sh
docker compose run --rm paperful snapshot --collection interesting --dry-run
docker compose run --rm paperful snapshot --collection interesting
# export PDFs already in Zotero as well:
docker compose run --rm paperful snapshot --collection interesting --pdfs all
```

4. Browse `out/<collection>/<stem -- KEY>/` (`record.json`, optional PDF,
   `notes/`).
5. Copy or sync `out/` with house tools (Syncthing, rsync, …). That sync is
   **outside** this repo — paperful does not run a sync daemon.
6. Later, dry-run then apply restore (creates missing items only; never
   overwrites bibliographic fields):

```sh
docker compose run --rm paperful restore --collection interesting
docker compose run --rm paperful restore --collection interesting --apply
```

## Roles

| Layer | Role |
| --- | --- |
| **Zotero** | Catalogue, collections, citations, annotations; `storage/` holds `imported_file` attachments after attach |
| **`out/<collection>/<stem -- KEY>/`** | Quiet mirror. One folder per item: `record.json` (`paperful.item.v1`), optional PDF, `notes/` |
| **`state/`** | Append-only history plus secrets. `out/_history.json` points at ledgers and does not copy sessions or API keys |

**Dual store for now.** Attach stays **`imported_file`**: bytes land under
`out/`, then upload into Zotero `storage/`. Duplicate bytes are acceptable.
Linked-file cutover is not a 0.x goal.

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
An item in several collections gets one folder per path: the PDF is
hardlinked, `record.json` is copied.

`[mirror].pdfs` (or `snapshot --pdfs`):

| Mode | What snapshot does with bytes |
| --- | --- |
| `additional` (default) | Keeps PDFs `run` already fetched. Does not export files that were already in Zotero |
| `all` | Also exports an imported or linked-file PDF (`origin: zotero_export`). Skips a file whose MD5 is already in the folder |
| `none` | Records and notes only. Does not delete a PDF already on disk |

`run` always writes a PDF it downloads.

A flat `Author - Year - Title.pdf` with a legacy `*.paperful.json` card is
moved into the item folder by `snapshot`, or by the next `run` that saves that
file. `paperful doctor` ambers when flat PDFs and item folders are mixed.

## What “quiet” means

- No second reading UI and no replacement for Zotero desktop.
- No long-running sync service inside paperful.
- Folder tree is for browse, scripts, and tooling that want paths and a
  per-item record.

## History

`state/` stays the append-only history. Reconstructing a failed fetch still
requires `state/manifest.jsonl`. PDF annotations inside Zotero are not
exported yet.

## Non-goals (near term)

- Not a second Zotero
- Not linked-file migration in 0.x
- Not a hosted multi-user warehouse
- Not auto Sci-Hub or silent cloud defaults

## Related

- [Why paperful](../start/why.md) — portable job
- [Architecture](../explain/architecture.md) — disk-first adapters
- [Zotero](../howto/zotero.md) — attachment modes
- [Commands](../reference/commands.md) — `snapshot` / `restore`
- [Roadmap](../contribute/ROADMAP.md) — Zotero is the tested 1.0 path
