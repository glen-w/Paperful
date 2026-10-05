# Developer guide

For people changing Paperful. Setup, tests, and pull requests are in
[CONTRIBUTING](https://github.com/glen-w/Paperful/blob/main/CONTRIBUTING.md).
The design reference is [architecture](architecture.md). This page is the
rules a change has to keep, and where things go.

## The rule: mirror first

Reference managers are flaky. Paperful copies the user's files and metadata
into its own mirror (`out/`, `state/`) and works from that copy. The manager
API is a narrow door with three uses:

1. **Refresh the mirror.** One listing of what changed.
2. **Write back when asked.** Attach, `--apply`, a note. Always explicit.
3. **Check the door.** `ping`, write support, authorize.

Anything else is a call Paperful should not make. Before adding a manager
call, ask which of the three it is. If it is none, read the mirror.

## What a command gets

`cli._connect(cfg)` is how a command opens the library. It returns a
`MirrorFirstBackend` ([`catalogue.py`](../paperful/catalogue.py)):

```text
_connect
  ├─ manager answers → run_sync (what changed) → MirrorFirstBackend(catalogue, live)
  ├─ manager down, mirror on disk → MirrorFirstBackend(catalogue, None)
  └─ manager down, no mirror → exit 2 with next steps
```

| Call on the backend | Served by |
| --- | --- |
| `collections`, `resolve_collection`, `subtree_keys`, `collection_counts` | `out/_collections.json` and the item folders |
| `items_in_scope`, `get_item`, `items_lacking_pdf` | `record.json` |
| `raw_item`, `children`, `find_child_note_keys`, `read_child_note` | `record.json` and `notes/` |
| `preview_merge` | `record.json` and `annotations.json` |
| `export_pdf` | the item folder; the manager only when the folder has no PDF |
| `apply_patch`, `attach`, `merge_into`, `trash_item`, note and tag writers, `create_parent` | the manager, then that item is re-read into its folder |

With the manager down, the write calls raise `LibraryError` and
`supports_write()` is false. Check it before a batch and exit 2 with
`_no_write(backend)`.

Use `cli._live_backend(cfg)` only when comparing the manager with the mirror
is the command's job. Today that is `sync`, `snapshot`, `restore`, and
`attachments`.

## Rules for new code

- **A verb that only reads never needs the manager running.** Add it to
  `READ_VERBS` in `tests/test_mirror_first.py`; the test runs it with the
  manager closed.
- **A verb that writes goes through the backend it was given.** The
  write-through is in `MirroredBackend` ([`library.py`](../paperful/library.py)).
  A new write method on an adapter needs a matching method there, or the
  mirror goes stale until the next refresh.
- **Could not read is never "nothing there".** Adapter reads raise
  `LibraryReadError`. A missing key is `None`. Do not catch a read error and
  carry on with an empty list: skip the item, count it, and say so.
- **pyzotero and the raw client stay in `zot.py`, `library.py`, and
  `attach.py`.** A test enforces it. No `backend.zl` in command code.
- **Whole-library reads happen in `sync.py` and nowhere else.** If a feature
  seems to need a library listing, it needs `backend.items_in_scope(None)`,
  which is the mirror.
- **Nothing under `out/` is deleted.** An item that left is marked, or moved
  to `out/_trash/`. A folder the item no longer belongs in is folded into
  one it does (`mirror.fold_folder`).
- **Bytes from the manager go into the item folder,** not a side cache
  (`state/pdf-cache/` is only for `[mirror].pdfs = "none"`).
- **Sources never write `manifest` or `out/`.** The pipeline does.
- **`--apply` is explicit and dry-run is the default** on every verb that
  writes to the manager.

## Module map

| Module | Job | May import |
| --- | --- | --- |
| `zot.py` | Zotero client, `Item`, pure helpers | `resolve` |
| `attach.py` | Authorize and upload | `zot` |
| `library.py` | `LibraryBackend` protocol, `ZoteroBackend`, `MirroredBackend`, `ChangeSet` | `zot`, `attach` |
| `mendeley.py`, `endnote.py` | Other adapters (seeking testers) | `library` types |
| `store.py` | Manifest, filenames, record IO | `zot`, `attach` |
| `mirror.py` | Folders by key, records → `Item`, PDFs on disk, gone policy. Calls no manager | `store`, `zot` |
| `snapshot.py` | Write one item's folders from payloads (`write_item`); scoped full refresh | `mirror`, `library` |
| `sync.py` | The refresh: delta or full, version last | `snapshot`, `mirror`, `library` |
| `catalogue.py` | `MirrorCatalogue`, `MirrorFirstBackend`, `open_library` | `sync`, `mirror`, `library` |
| `scope.py` | Collection, year, type selection | `library` errors |
| `resolve.py`, `lint.py`, `acronyms.py`, `metadata.py`, `dedupe.py`, `pdfid.py` | Identifier and hygiene logic. Take a backend; never name a manager | the protocol |
| `sources/` | One fetch lane each. Return bytes or a miss | `sources.base` |
| `pipeline.py` | Order the lanes, save, attach, write the manifest | most things |
| `cli.py` | Flags, progress, exits. No logic of its own | everything |

## The refresh

`run_sync` ([`sync.py`](../paperful/sync.py)):

1. `backend.changes(since)` — rows changed after the stored library version
   (all rows on a first or `--full` refresh), the keys now in the library,
   the trash, the collections. Zotero's local API leaves trashed items out
   of listings and has no `/deleted`; a removal is a key that stopped being
   listed.
2. Work out which parents are affected: changed themselves, a child changed,
   or a child key the index knew is gone.
3. Rewrite each one with `snapshot.write_item` (`exact=True`: the item's
   whole collection membership is known, so folders move and fold).
4. Mark or move parents that left (`mirror.retire`). Refused when more than
   half the mirror would go: that is a different library.
5. Write `out/_sync.json`. **Last.** If any item could not be read, the
   version does not move and the next refresh covers the same ground.
6. With `[mirror].pdfs = "all"`, copy PDFs (`copy_pdfs`). Whole library until
   it has completed once, then changed items only.

Every step can be repeated. A crash leaves valid records and an old version.

## Disk schemas

| Schema | File | State |
| --- | --- | --- |
| `paperful.item.v1` | `record.json` | 0.x may add keys. Do not rename or remove one |
| `paperful.sync.v1` | `out/_sync.json` | New. Internal to the refresh |
| `paperful.annotations.v1` | `annotations.json` | New |
| `paperful.collections.v1` | `out/_collections.json` | Read by the catalogue |
| `paperful.run_report.v1` | `state/runs/*.json` | Required keys frozen |

The catalogue rebuilds an `Item` from a record. The test
`test_item_from_record_matches_the_live_listing` holds the two equal field
for field. A new `Item` field needs a home in the record and a case there.

## Adding things

**A read verb.** `backend = _connect(cfg)`, `_load_scope(backend, …)`, do
the work, write a run report. Add it to `READ_VERBS`.

**A write verb.** Same, dry-run by default. Before applying:
`if not backend.supports_write(): _exit_env(_no_write(backend), cfg)`.

**A source.** Subclass in `paperful/sources/`, register it, return a
`PageResult`. It gets a `Context`; it does not get the manifest or `out/`.

**An adapter method.** Ask first whether the mirror can serve it. If it is a
read, add it to `MirrorCatalogue`. If it is a write, add it to the adapter,
to `MirroredBackend` (refresh the item after), and to `MirrorFirstBackend`
(pass through, refuse offline).

**A manager.** Implement `LibraryBackend`. With a `changes(since)` method it
gets the mirror-first path for free. Without one, its reads stay live.

## Tests

`uv run pytest` runs offline. `tests/conftest.py` refuses every request a
real Zotero client makes, so a Zotero running on your machine is never read
by a test.

| Fake | Use |
| --- | --- |
| `tests/test_sync.py::FakeZotero` | A library with versions, a trash, and call counts. For the refresh and the catalogue |
| `tests/conftest.py::FakeListing` | Mixin for a stub client that lists `Item` objects. For CLI tests |
| `tests/test_write_through.py::FakeLibrary` | A manager with write calls. For `MirroredBackend` |

Count requests when the point of a change is fewer of them: `FakeZotero.calls`.
