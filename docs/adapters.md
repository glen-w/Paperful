# Adapter SDK

A new reference-manager adapter is a **conformance-suite submission**, not
core surgery. Implement [`LibraryBackend`](../paperful/library.py) and land
it when the kit plus a real-library field report both pass. Promotion
criteria are written down in [`docs/plans/1.7-wave.md`](plans/1.7-wave.md)
*before* reports arrive.

**Zotero is well tested.** Mendeley and EndNote stay **seeking testers**
until a completed [field assessment](templates/adapter-field-assessment.md)
is filed.

## What to implement

`LibraryBackend` is the whole surface. Reads that the on-disk mirror can
serve belong on `MirrorCatalogue`; writes go on the adapter, then
`MirroredBackend` (refresh the item after) and `MirrorFirstBackend` (pass
through, refuse offline). Identifier / lint / dedupe code must not import a
manager except through this protocol. See [architecture](architecture.md)
and [developer — Adding things](developer.md#adding-things).

The behaviour contract is `tests/test_wave17_conformance.py`:

1. Structural: every shipped backend (`ZoteroBackend`, `MendeleyBackend`,
   `EndNoteBackend`, `MirroredBackend`) exposes the protocol methods.
2. Behaviour: an in-memory fake lists collections, loads items, attaches a
   file, and round-trips notes.

Submit a new manager by adding its class to that parametrize list and
keeping the fake green. Do not add a second item type, a parallel write
path, or catalogue-unification shortcuts.

## Promotion (all three, or it stays "seeking testers")

1. The conformance suite passes against the adapter's fake.
2. A completed `docs/templates/adapter-field-assessment.md` from a real
   library (list, fetch a missing PDF, attach, notes round-trip,
   failed-auth next-steps ladder) is filed under `assessments/`.
3. Mirror-first reads work with the manager closed.

## Explicitly out

Catalogue unification and treating every manager as an equal default are
parked ([roadmap](ROADMAP.md)). EndNote never writes the `.enl` SQLite;
Mendeley tokens stay `0600` and rotate on refresh.
