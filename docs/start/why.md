# Why Paperful

A local sidecar beside your citation manager. The job is to keep the library
organised, the PDFs complete, the metadata honest, and a folder tree you own
under `out/` and `state/`. **Zotero is the well-tested catalogue. Use that.**
Mendeley and EndNote adapters are in the tree and **seeking testers**. They
are not the supported path.

## Three jobs

**Complete.** Fill missing PDFs (open access first, campus EZProxy when you
have a subscription, Sci-Hub only if you opt in). Lint identifiers and
propose metadata patches on disk; apply them only when you say so. Review
duplicates, then trash extras.

**Portable.** `snapshot` writes one folder per item: `record.json`
(`paperful.item.v1`), an optional PDF, and notes. `restore --apply` creates
only what Zotero is missing and does not overwrite fields already there.
Copy `out/` (or sync it with something like Syncthing). That sync is house
transport, not a Paperful service. See [Quiet mirror](../paths/quiet-mirror.md).

**Grey literature.** Zotero’s PDF ingest is fine for a structured journal
article. Reports, scans, and landing-page junk often come back with a
garbled title or no usable text. Paperful keeps the original file, uses
[grey-lit playbooks](../reference/sources.md) for UN, FAO, ISA, and similar landings, and
can ask a local model for a grounded title, an identity check, or a summary
— from a text layer. OCR is not in scope.

## Storage, not WebDAV

Zotero cloud storage is small. WebDAV works, and it is more ops than most
people want. Paperful’s answer is the folder tree: attach into Zotero when
you want the citation UI; if the quota is full, the PDF is still under
`out/` and `attach` can retry later. Paperful is not a WebDAV client. Phone
and WebDAV sync stay Zotero’s job. See [Zotero](../howto/zotero.md).

## What is true today

| Claim | Status |
| --- | --- |
| Zotero read, fetch, lint, attach, snapshot, restore | Well tested. This is the adapter to use |
| Disk ledger you can copy without the manager | Shipped (`out/` + `state/`) |
| Mendeley (`manager = "mendeley"`, REST at api.mendeley.com) | Seeking testers. Needs an app at dev.mendeley.com and `paperful session login mendeley`. Not proven against a real library here |
| EndNote (`manager = "endnote"`, local `.enl`) | Seeking testers. Reads `sdb.eni`. Writes stage `state/endnote-import/` for File → Import. Paperful does not edit the EndNote database, and it cannot trash items there |
| OCR, linked-file cutover, hosted multi-user service | Not the product |

## Related

- [Quiet mirror](../paths/quiet-mirror.md) — folder contract
- [How Paperful compares](../explain/comparison.md)
- [Roadmap](../contribute/ROADMAP.md) — Zotero is the tested path; Mendeley and EndNote are seeking testers
