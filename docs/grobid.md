# GROBID sidecar

Paperful talks to an **external**
[GROBID](https://github.com/grobidOrg/grobid) REST server to turn scholarly
PDFs into TEI with real section structure. Paperful does **not** start or
bundle the Java service (not in the light or heavy image). You run GROBID; you
point `[grobid].base_url` at it.

GROBID is off by default. The core fetch / lint / attach loop never needs it.
`paperful extract-sections` still works with heading-heuristic rules when GROBID
is down. Optional `[rag].parser = "grobid"` uses the same TEI cache for RAG
ingest. `paperful critique --advanced` reuses that cache for section-labeled
chunks and falls back to ordinary extract text when GROBID is off, the file is
not a PDF, the PDF is a scan, or the sidecar errors.

## When to use it

- Structured IMRaD fields (`abstract`, `methodology`, `conclusion`,
  `research_questions`) that heading regexes miss
- Cleaner section labels on `rag ingest` than `pdftotext`
- Section-labeled chunks for `critique --advanced` (MARG-S-style)

Skip it for scans until `paperful ocr` has added a text layer. GROBID is not
a metadata write-back path and does not edit Zotero parents.

## Setup

1. Start GROBID (CRF CPU image; several GB of RAM). Pin a release tag:

```bash
docker run --rm --init --ulimit core=0 -p 8070:8070 lfoppiano/grobid:0.8.2
```

Health: `curl http://127.0.0.1:8070/api/isalive` should return `true`.

Or add a second Compose service via
[`compose.override.example.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.override.example.yaml)
(service name `grobid`) and set `base_url = "http://grobid:8070"`.

2. Enable the client:

```toml
[grobid]
enabled = true
base_url = "http://127.0.0.1:8070"
timeout_s = 120
allow_remote = false
consolidate_header = 0
consolidate_citations = 0
```

Inside Compose, keep the loopback URL; Paperful rewrites it to
`host.docker.internal` (`PAPERFUL_GROBID_HOST`), same idea as Ollama.

3. Check readiness:

```bash
paperful doctor
```

Disabled stays green. Enabled and down is amber.

## Behaviour

`paperful extract-sections --grobid` (or `[grobid].enabled`) POSTs each mirror
PDF to `/api/processFulltextDocument` and caches TEI under
`state/grobid/<sha256>.tei.xml` (`paperful.grobid.tei.v1`). Unchanged hashes
skip the HTTP call unless `--force`. A warm cache for that PDF hash is enough
for `[rag].parser = "grobid"` and for `critique --advanced` chunks even if the sidecar is briefly down. Fields land
in `state/sections/<key>.json` with provenance `grobid` (heading rules fill
gaps; optional `--llm` still only fills missing MVP fields). Scans are skipped
with a note until `paperful ocr` has added a text layer.

`consolidateHeader` and `consolidateCitations` default to `0` so GROBID does
not call Crossref on your behalf. A non-local `base_url` needs
`allow_remote = true`; the CLI prints a yellow notice because **PDF bytes leave
this machine**. Paperful does not call public demo GROBID servers.

`[rag].parser = "grobid"` projects cached TEI to markdown pages (`# Heading`)
so the existing chunker keeps section labels. Changing the parser re-indexes
on the next ingest.

See [Section extract](config.md#section-extract-extract-sections) and
[RAG parsers](rag.md#parser).
