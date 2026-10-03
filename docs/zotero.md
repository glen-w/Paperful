# Zotero

Paperful talks only to the **local** API (`http://localhost:23119/api`, library
id `0`). Official behaviour below is from Zotero support pages fetched
**2026-09-19**. Lines marked **Paperful** are client rules, not Zotero’s.

## Setup

1. **Settings → Advanced → “Allow other applications on this computer to communicate with Zotero”.**
   Off means every local request is **403**.
2. Zotero desktop must be **running on the host**. Docker does not host the GUI
   or the authorize dialog. See [Docker](docker.md).
3. Use **Show Data Directory** (Settings → Advanced → Files and Folders). The
   API can answer on `:23119` while you are pointed at the wrong library.
   Remembered write keys live in the **profile**, not the data directory
   (`zotero.sqlite` and `storage/` live in the data directory).
4. One instance per port. A second profile must change
   `extensions.zotero.httpServer.port` or it collides with **23119**.

Do not forward port 23119.

### Versions

| Capability | Version |
| --- | --- |
| Local HTTP API (read) | **7.0** (2024-08-09) |
| Extra local endpoints (annotations, `/fulltext`) | **8.0** (2026-01-22) |
| Local **write** (items, uploads, authorize) | **10.0** (2026-08-17) |

**7–9** can list the library and download. Attach, `fix-metadata --apply`, and
`dedupe --apply` need **10+**. Paperful treats a `Zotero-Server-ID` response
header as write-capable. That header and write support both arrive in 10; the
header is not defined as “write” by itself, but on a stock desktop build the
match holds.

### Host header and Docker

Zotero 10 rejects a `Host` that is not `localhost`, `127.0.0.1`, or `[::1]`
(**400**). Browser-like requests (`User-Agent` starting `Mozilla/`, or any
`Origin`) are dropped unless they carry `Zotero-Allowed-Request`.

**Paperful:** the `Host` header is always `localhost:23119`.
`PAPERFUL_ZOTERO_HOST` is only the TCP address (for example
`host.docker.internal` from Compose). Never copy that env var into `Host`.

## Write authorization

Zotero 10 writes need a local key:

```text
POST /api/local/authorize
Zotero-Server-ID: <from any API response>
{ "appName": "…" }
```

The dialog offers **Allow**, **Always Allow**, and **Deny**. The HTTP call
**blocks** until you click. Always Allow returns a reusable key (`remember`);
Allow is single-use. Deny is **403**. More than about five dialogs a minute
returns **429**.

Paperful calls `authorize_local` and, on Always Allow, stores the key in
`state/zotero-local-api-key.json` (mode `0600`). Revoke remembered keys with
**Settings → Advanced → Clear Write Authorizations**. A different database
(restore, other data directory) is a new server id: authorize again.

Writes require `Zotero-Server-ID` (**428** if missing). A mismatched id on a
read is **412**. A missing or bad key on a write is **401**.

## Attachment modes

| `linkMode` | Bytes in `storage/<key>/` | File-sync quota | Paperful “has PDF” |
| --- | --- | --- | --- |
| `imported_file` | Yes, after a finished upload | Yes | Yes, if PDF |
| `imported_url` | Yes, if the download finished | Yes | Yes, if PDF |
| `linked_file` | No (external path) | No | Yes, if PDF |
| `linked_url` | No | No | No, unless `--upgrade-linked` |

**Paperful attaches `imported_file` only:** the PDF is already under `out/`,
then uploaded (md5, filename, filesize, mtime) and registered. It builds the
attachment JSON itself and does not call `/items/new`. Summary child notes
and `synthesize` collection notes are posted the same way. Filename spaces are
encoded as `%20`, not `+`.

`linked_url` (including a quota workaround that only stores a URL) is not a
stored PDF. `--upgrade-linked` adds an `imported_file` beside it and does not
remove the link:

```sh
paperful run -C COLLECTION --upgrade-linked
```

A successful Zotero attach writes a provenance note on the PDF child
(`paperful oa:unpaywall`, `paperful campus:ezproxy`, `paperful grey:<playbook>`,
`paperful pirate:scihub`, and so on). The manifest `source` field remains the
record. A readable line ("Free copy from Unpaywall.") is also written on the
parent, as a child note unless `[remarks].surface` is `tag` or `off`. See
[Research operators](research-ops.md). Files held for **attach** (`short_pdf`,
`--strict-pdf-doi`) stay on disk under `out/` until
`paperful attach --allow-short-pdf` or `--allow-pdf-doi-mismatch`.

## Ghosts and quota

Desktop dialog (files-not-syncing KB):

> The attached file could not be found at the following path. It may have been
> moved or deleted outside of Zotero, or, if the file was added on another
> computer, it may not yet have been synced to or from zotero.org.

A **ghost** is the storage-slot case: the attachment row (and often an MD5)
exists under `storage/<key>/`, but the bytes never landed on this machine.
Creating an `imported_url` or `imported_file` row and stopping before the
upload finishes does that. `linked_url` does not.

Refill from the attachment URL only when the downloaded bytes match the stored
MD5. Publisher GETs that return 403 (Cambridge, Taylor & Francis, some
institutional hosts, parliamentary briefings) will not. Open those in a
browser, or with [EZProxy](ezproxy.md), and attach the PDF — or trash the empty
attachment and run `paperful attach`.

When Zotero File Storage is full, attach can fail while the PDF remains in
`out/`. That folder is the warehouse: free space in Zotero (empty the trash
permanently, upgrade, or WebDAV for the personal library) and attach later.
Paperful does not speak WebDAV. Linked URLs do not use file quota and are
not a substitute. Groups cannot use linked files; group files sync only through
Zotero Storage. See [Why Paperful](why.md) and [Quiet mirror](quiet-mirror.md).

In Zotero 10 the settings pane is **Account** (older builds still say Sync).
Turn file sync on for this data directory, or right-click the attachment →
Download File.

## Checklist

**Once per machine / profile**

1. Local API checkbox on (else 403).
2. Zotero 10+ if you need writes.
3. Always Allow once; confirm `state/zotero-local-api-key.json`.
4. Library id `0`. `Host` is `localhost:23119`. In Docker, TCP connect is
   `PAPERFUL_ZOTERO_HOST`, not the Host header.

**Each session**

5. Zotero running on the host, same data directory and profile as the key.
6. Finish the `imported_file` upload. Do not leave a row that has an MD5 and
   no bytes.
7. If file sync is on, leave storage headroom — or accept that `out/` holds
   the PDF until attach succeeds.

## Identifiers

DOI and URL are normal fields. PMID and PMCID are dedicated fields on journal
articles since **7.0.31**; older items and other types still keep
`PMID:` / `PMCID:` / `DOI:` lines in Extra. Paperful’s PubMed step reads Extra
(`PMID:`, `PubMed PMID:`, `PubMed ID:`). Add Item by Identifier accepts ISBN,
DOI, PMID, arXiv id, and ADS bibcode. There is no dedicated arXiv field in the
item-types reference.

Item lists omit the trash. Paperful merges a duplicate onto the keeper, then
trashes the emptied parent via the local write API (`DELETE` on the item).
It does not permanently delete or remove files under `out/`.
Collection **keys** are the stable ids; the
same display name can appear more than once.

## Scoping runs (Paperful)

Paperful never invents Zotero saved searches. Scope is:

1. **Collection** (`-C` / `--collection`, repeatable) or **`--library`**
2. Optional **`--year-from` / `--year-to`** (parsed publication year)
3. Optional **`--type` / `-T`** (Zotero `itemType`)

Example: journal articles in BBNJ from 2023 through 2026:

```sh
uv run paperful run -C BBNJ --year-from 2023 --year-to 2026 -T journalArticle
```

`--type` accepts the built-in Zotero type ids (`journalArticle`, `report`,
`preprint`, …) or friendly labels (`Journal Article`). See
[Commands — Scope filters](commands.md#scope-filters). Year and type also
apply to `lint`, `fix-metadata`, `dedupe`, `gaps`, `ocr`, `summarize`, `synthesize`,
`snapshot`, and `restore`.

## What Paperful asks of the API

Paperful works from its own copy under `out/` and keeps the API to three
uses ([Mirror first](architecture.md#mirror-first)).

**Refresh.** Before a command reads, six requests when nothing changed:

| Request | For |
| --- | --- |
| `GET /items?since=<version>` | Rows changed since the last refresh (every row, paged by 2,000, on a first or `--full` refresh) |
| `GET /collections` | The collection tree |
| `GET /items/trash` | What is in the trash |
| `GET /items/top?format=keys` | Every top-level key now in the library |
| `GET /items?format=keys` | Every key, children included |
| `GET /` | Version and server id |

Trashed items are left out of `/items`, and the local API has no `/deleted`
(**404**). A removal is read as a key that is no longer listed. When a child
changed and its parent did not, the parent and its children are read
(`/items/<key>`, `/items/<key>/children`): two requests per such parent.

**PDF bytes.** `GET /items/<key>/file` without following the redirect gives
the `file://` path; Paperful copies that file. In Docker the path is on the
host, so the file is downloaded through the API instead.

**Writes.** Only on attach, `--apply`, and note or tag writes. After each,
the item and its children are read once so its folder is true.

`sync`, `snapshot`, `restore`, and `attachments` read the library directly.
Nothing else does.

## Local API vs web API

Only API **v3**. Reads need no key. There is no default page size (`limit` /
`start` still work). Partial file PATCH is **405** (full upload only). File
GET is a **302** to `file://`. Saved searches execute locally
(`/searches/<id>/items`). Ordinary local reads are not rate-limited; authorize
dialogs are. Anything unimplemented is typically **501**.

Web upload docs mention **413** when a file would exceed online storage quota.
A local upload writes to this machine’s data directory first; a later sync can
still fail on quota. What the local server returns when the disk is full is
not documented.
