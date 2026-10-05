# Research operators

Short notes for people running Paperful against a real library. Setup of the
local API, the Host header, and ghost attachments is in [Zotero](zotero.md).

## Unpaywall email

`email` in `config.toml` is a contact address for Unpaywall, Crossref, and NCBI.
It is not a login and it does not raise the OpenAlex quota. Use a real address
you read. OpenAlex meters a free API key (`OPENALEX_API_KEY`, about $1/day) or,
with no key, the public IP. Heavier use is [pay-as-you-go or a subscription](https://openalex.org/pricing). A VPN exit shares that keyless budget with everyone
else on it.
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
not match the library item adds `warn:pdf_doi_mismatch`. That stamp stays on
the PDF. The parent item also gets a readable line ("Free copy from
Unpaywall.", or "This PDF's DOI does not match the record.").
`[remarks].surface` chooses a child note (default), a parent tag, or `off`.
The source of record remains the manifest `source` field (and `attempts`).
Unpaywall and OpenAlex hits also stamp `license`, `oa_status`, and `version`
on `out/.../record.json` (`fetch.oa`) and on the manifest row when configured
in `[oa_honesty].stamp_fields`.

Miss taxonomy (dry-run, `gaps --list-missing`, `--handoff list`) uses a frozen
surface code: `no_doi`, `paywalled`, `no_oa`, `fetch_failed`, `license_blocked`,
or `import_ok`, plus a plain-string column and optional `oa_status` / `license`
when stamped. Rich detail stays on `attempts[]` as `miss_detail`.

Until you are looking at that note, reconstruct origin from disk:

```sh
paperful report
# or, for one item key:
jq -c 'select(.itemKey=="ITEMKEY") | {source, attempts, pdf_doi, doi}' state/manifest.jsonl
```

`paperful attach` after `--no-attach` stamps from the manifest `source`.
Mendeley and EndNote do not get the PDF stamp. They do get the readable
parent line, as an annotation or an import-bundle note, or as a tag when
`[remarks].surface` is `tag`.

New metadata parents from `ingest-dois`, snowball `--gate auto` / `apply`,
and inbox create take tags: `--tag`, `[ingest]` / `[snowball].default_tags`,
`from-<seed-slug>` (DOI list stem or snowball seed), plus `inbox-created` and
`inbox:<dirname>` on inbox create. Those are library tags, not the PDF stamp
above. See [config](config.md) and [snowball](snowball.md).

## Wrong-work PDFs

By default `run` still saves and attaches when the PDF’s DOI differs from the
library item, and the note carries `warn:pdf_doi_mismatch`.

```sh
paperful run -C COLLECTION --strict-pdf-doi
paperful attach --allow-pdf-doi-mismatch
```

That saves the file as `ok` and does not attach it. A later `paperful attach`
skips those rows unless you pass `--allow-pdf-doi-mismatch`.

One-page PDFs are gated by text density (default on; `gate_short_pdfs`,
`short_pdf_min_words` in [config](config.md)). A sparse one-pager (ethics
declaration, consent form) is soft-rejected so other sources can still run. A
denser one-pager (letter, short comment) is saved as `ok` with reason
`short_pdf` and skipped by `attach` until you pass `--allow-short-pdf`. Set
`gate_short_pdfs = false` to disable.

```sh
paperful attach --allow-short-pdf
```

Open the file under `out/` first if you need to decide whether it is a real
letter or still junk. Manual `attach --item --file` and handoff walk/inbox
reject sparse one-pagers but attach denser ones (you already chose the file).
`inbox watch` / `drain` (shared `[inbox].dir`) default to whole-library DOI
match; set `[inbox].match` for title/OCR/LLM, `[inbox].create` for gated
proposals. Use `-C` only when you want a narrower index. See [sources](sources.md).

An in-memory DOI swap during fetch changes which work is requested. It does
not write the library until `fix-metadata --apply`. Run `lint` before a large
`--apply`. `--overwrite` can replace a title, date, or venue you edited by
hand; dry-run the patches first.

## What a fill is not

Open-access indexes, campus EZProxy, and the configured grey playbooks. Not a
completeness rate. Sci-Hub stays off unless you opt in, and coverage after
about 2021 is thin. A full Zotero file quota can leave the PDF only in `out/`.
