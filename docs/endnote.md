# EndNote

Clarivate has **no public API**. Paperful reads the desktop library and never
writes the SQLite file. Official write-back is EndNote’s own **File → Import**.
Schema notes below are from inspecting EndNote 20/21 library folders
(**2026-09-21**). Lines marked **paperful** are client rules.

**This adapter is seeking testers.** Zotero remains the well-tested path.
Do not treat a first EndNote run as proven.

## Setup

1. Point config at the `.enl` file. The matching `.Data` folder must sit
   beside it (EndNote’s usual pair):

   ```toml
   manager = "endnote"
   [endnote]
   library = "/path/to/Library.enl"
   ```
2. Confirm `Library.Data/sdb/sdb.eni` exists. PDFs live under
   `Library.Data/PDF/` and are referenced as `internal-pdf://…`.
3. `uv run paperful doctor` should show **EndNote library** green.

If EndNote is open, SQLite is often locked. Paperful copies `sdb.eni` plus
`-wal` / `-shm` / `-journal` to a temp file and reads that. Connections
register EndNote’s `ENCI_Base` / `ENCIN_Base` collations so SELECTs do not
fail.

## Read path

| Piece | Where |
| --- | --- |
| Catalogue | `sdb.eni` table `refs` (skipped when `trash_state` is set). `reference_type` uses a **different number space** from XML `<ref-type>` — journal is **0** in the database and **17** in XML. DOI lives in `electronic_resource_number`. |
| Groups | `groups.spec` XML for the name; `groups.members` BLOB for membership. There is no join table in a real library. Online-search groups (`TYPE;6` in spec) are skipped. Group *sets* are not in XML. |
| PDFs | `file_res.file_path` (prefer `file_type` 1 or 4), else `internal-pdf://` in URL fields, else a filename match under `PDF/` |
| Notes | `research_notes` and `notes` columns, exposed as child notes |

Item keys are integers. `out/` folder names accept them.

## Write path (import bundle)

Paperful **does not** `UPDATE` EndNote’s database. `attach`,
`fix-metadata --apply`, `restore --apply`, `import --apply`, `summarize`, and
`synthesize` accumulate a pending list. At the end of the command,
`flush_writes()` writes:

```text
state/endnote-import/<UTC-stamp>/
  paperful.xml
  PDF/
  README.txt
```

Then in EndNote:

1. File → Import → File…
2. Choose `paperful.xml`.
3. Import Option: **EndNote Generated XML** (or XML).
4. Duplicates: discard, or import into a duplicates group, as you prefer.

If PDFs do not attach automatically, File → Import → Folder on `PDF/`, or
drag files onto the matching references.

**Groups are not in EndNote XML.** Collection paths are stored in the Label
field so you can rebuild groups after import. `dedupe --apply` is refused:
EndNote cannot move a PDF or note onto the keeper. Delete the extra in
EndNote, or omit it from the next bundle.

## Paperful rules

- Never point this adapter at a library you have not copied. The reader is
  conservative, but EndNote’s schema is unpublished and can move.
- Moving a library: `snapshot --pdfs all` here, switch `manager`, then
  `restore --apply` or `import` on the other side. The hub is `out/`.
- Interchange without a live adapter: `paperful export` / `import` with
  RIS, BibTeX, or EndNote XML.

## Commands

```sh
uv run paperful doctor
uv run paperful collections
uv run paperful snapshot -C MyGroup --pdfs all
uv run paperful export bundle.xml --library --pdfs
# after a write command, import the printed state/endnote-import/… folder
```
