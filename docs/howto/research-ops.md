# Research operators

Short notes for people running Paperful against a real library. Setup of the
local API, the Host header, and ghost attachments is in [Zotero](zotero.md).

## Unpaywall email

`email` in `config.toml` is a contact address for polite-pool APIs (Unpaywall,
OpenAlex, Crossref, NCBI). It is not a login. Use a real address you read.
`doctor` ambers when it is missing. Unpaywall only covers items that have a
DOI and an open-access location; a hit is often a landing page with no PDF
(`OA landing, no PDF`). Grey-literature reports with no DOI never reach it.
`concurrency_oa` (default 4) is the parallel cap for those sources. A source
that starts failing is skipped for the rest of the run by the circuit breaker.

## Campus acceptable use

[EZProxy](ezproxy.md) explains how a session is reused. Bulk automated
download can still break an institutional acceptable-use policy or a publisher
licence, even with a valid SSO. Prefer `--preset eoi` (open access plus
campus, no Scholar, no Sci-Hub), keep batches small, and do not share
`state/sessions/`.

## Provenance

On a successful Zotero attach, the child PDF’s note is a stamp such as
`paperful oa:unpaywall` or `paperful grey:undocs-unga-vme`. A DOI that does
not match the library item adds `warn:pdf_doi_mismatch`. The note is the
Zotero-visible copy. The source of record remains the manifest `source` field
(and `attempts`).

Until you are looking at that note, reconstruct origin from disk:

```sh
paperful report
# or, for one item key:
jq -c 'select(.itemKey=="ITEMKEY") | {source, attempts, pdf_doi, doi}' state/manifest.jsonl
```

`paperful attach` after `--no-attach` stamps from the manifest `source`.
Mendeley and EndNote do not get this note.

## Wrong-work PDFs

By default `run` still saves and attaches when the PDF’s DOI differs from the
library item, and the note carries `warn:pdf_doi_mismatch`.

```sh
paperful run -C COLLECTION --strict-pdf-doi
```

That saves the file as `ok` and does not attach it. A later `paperful attach`
skips those rows unless you pass `--allow-pdf-doi-mismatch`.

An in-memory DOI swap during fetch changes which work is requested. It does
not write the library until `fix-metadata --apply`. Run `lint` before a large
`--apply`. `--overwrite` can replace a title, date, or venue you edited by
hand; dry-run the patches first.

## What a fill is not

Open-access indexes, campus EZProxy, and the configured grey playbooks. Not a
completeness rate. Sci-Hub stays off unless you opt in, and coverage after
about 2021 is thin. A full Zotero file quota can leave the PDF only in `out/`.
