# How it works

A fill is `run`. Paperful checks the record, searches for a PDF, and writes
the file to disk. It does not merge duplicates and it does not rewrite
titles or dates. Those jobs sit around a fill — see [Around a fill](#around-a-fill).
The landing page is the short version of this story.

**Trust the disk** before notes or Ask: `gaps` → `attachments` (honesty) →
`run` (bytes on disk under `out/`) → you read `out/` → then `summarize` /
`ask`. `attach` is the write gate into Zotero. Do not call that step
**admit**.

| Claim | Quote |
| --- | --- |
| Dry-run shows the hit | `run --dry-run` **Would-hit** column (sources in order). No download. |
| Gaps without fetch | `gaps` counts missing PDFs without filling them. |

## A fill, in order

1. **Pick the slice.** A collection, or the whole library. Year and item-type
   filters are optional. Items that already have an imported PDF are skipped.
2. **Check the record.** Before any download, Paperful verifies an existing
   DOI against Crossref or OpenAlex, and can fill a missing one from a URL,
   a PubMed id, or a title match. That check is in memory for the search.
   The original identifier stays in the log. Zotero is not rewritten here.
3. **Look for a free copy first.** Open-access indexes, then the item’s own
   URL, then campus access when you have it. News and blog items can be
   printed to PDF. Odd hosts use [playbooks](sources.md) you write, or recipes
   learned on this machine ([sessions](sessions.md)).
4. **Use your library login when you have it.** Log in once in Chrome or
   Edge. `run` reuses that campus session through EZProxy. Same pattern for
   Google Scholar if you opt in. See [Using your Scholar or library login](#using-your-scholar-or-library-login).
5. **Only try what fits.** Each item is sent only to sources that match what
   the record already knows — a DOI, an arXiv id, a publisher URL. If a site
   says slow down, Paperful waits. If a site keeps blocking, that source is
   paused. See [Slowing down](#slowing-down).
6. **Save on this machine first.** The PDF lands under `out/` with a
   **provenance stamp** on the file (`paperful oa:unpaywall`, `campus:ezproxy`,
   `grey:undocs`) and a readable source line on the parent (“Free copy from
   Unpaywall.”). On Zotero 10+ it can **attach**; older Zotero still gets the
   file on disk. A sparse one-page download (ethics stub, consent form) is
   dropped so another source can try; a denser one-pager waits for
   `paperful attach --allow-short-pdf`. Details:
   [research-ops](research-ops.md#wrong-work-pdfs). Not every paywalled
   or DOI-less item comes back.

## Where it looks

Default order: Unpaywall, OpenAlex, arXiv, bioRxiv/medRxiv, Europe PMC,
Semantic Scholar, CORE, OpenAIRE, the item’s own URL, campus EZProxy, then
print-to-PDF for web items. Google Scholar and Sci-Hub stay off until you
put them in `sources`. When Scholar is on, it runs **late** (one try before
browser recovery, or one late phase if recovery is off), not in the middle of
campus/grey. `[fetch].order = "list"` keeps the `sources` array order instead.
Sci-Hub coverage after about 2021 is thin; recent
paywalled papers are a campus-access problem when your library has the
subscription.

Open-access sources can run in parallel. Scholar, Sci-Hub, EZProxy,
print-to-PDF, and opt-in [SerpApi](serpapi.md) stay one-at-a-time — they share a browser
profile or a paid quota. SerpApi is never a silent default; when you turn it
on, `[serpapi].max_calls` (default 20, `0` unlimited) or `--serpapi-max`
limits paid searches that run.

Per-item routing is on by default: a journal article with a DOI is not sent
to every site. The log line `trying: …` is that shorter lane, not the full
list. Details: [Source routing](sources.md).

## Around a fill

Hygiene is a separate loop. Nothing is merged or rewritten until you say so.

**Before a fetch**, `gaps` counts missing PDFs. `refs gap` lists works cited
inside those PDFs that are not in the library (always dry-run). `run --dry-run` prints a
**Would-hit** column (sources in order) and does not write the library.

**Before a messy ingest**, `dedupe` writes a review pack on disk. With
`--apply` it copies the extra parent’s PDF, notes, and better fields onto
the keeper, then moves that emptied parent to the trash. [Dedupe](dedupe.md).

**After a fill**, `lint` and `fix-metadata` propose identifier and title
patches on disk; `--apply` writes them to the catalogue. `run` never writes
bibliographic fields.

**If you want notes**, `summarize` writes a grounded note from the PDF text
(local model, off until you enable it). `synthesize` reviews those notes for
a collection. Scans need a text layer first. [LLM](llm.md).

`paperful all` is gaps → **run** → lint → fix → summarise. Dedupe is not in
that chain; run it before `gaps` / `run` when the collection is messy.
[Workflows](workflows.md).

To follow **people** (not a keyword crawl), `paperful authorwatch` records a
local list and polls OpenAlex for their papers. First `run` is a cursor only.
That is not `snowball watch` and not the PDF `inbox watch`.
[Author watch](authorwatch.md).

To rank creators already in a collection and seed a proposed field author pack
for personal-site PDF fetch, use `paperful authors -C …` (then promote). See
[Workflows § field author packs](workflows.md#6-field-author-packs-corpus-frequency--author_site).

## Slowing down

If a site returns a rate limit, the HTTP client waits and retries. If a site
keeps showing a block page or a CAPTCHA (three times by default), Paperful
pauses that source, continues with the rest of the lane, and tries one later
item. A clean result opens the source again.

Items missed because a source was paused, or because the campus session
expired, are picked up on the next `run`. Items every applicable source
missed stay closed until you ask to retry them. When `ezproxy` is configured,
`run` probes the vault before batch 1. An expired session skips further proxy
wraps; on a terminal, `run` offers re-login at the next batch boundary and
again after the fetch for items left `session expired` (`ezproxy_relogin`,
default on; `--no-ezproxy-relogin` skips the pauses).

The knobs and error names: [Source routing](sources.md).

## Using your Scholar or library login

The tool never asks for or stores your institutional password. You log in
once in a headed browser (`paperful session login ezproxy` or `scholar` on
the host). `run` reuses that login until the campus session expires —
typically hours to a few days. Confirm it is still live with
`paperful doctor --probe` or `paperful session status --probe` (file presence
alone is not enough). When a publisher page is HTML, the same
browser follows the PDF link or download control before giving up. Scholar
fetches use the same browser profile, because Google often keys a CAPTCHA
to the browser, not just cookies.

Those logins live on this machine. Do not commit them or paste them into
chat. [Sessions](sessions.md) · [Campus EZProxy](ezproxy.md).

## What you get back

A PDF on disk, when a copy could be reached, with a readable source line on
the item. Optional: a grounded summary note, then a collection-level review
of those notes. A folder copy you can back up or export as RIS, BibTeX, or
EndNote XML — not a sync service.

Why this shape: [Why Paperful](why.md). Commands: [Commands](commands.md).
Architecture of the same flow: [Architecture](architecture.md).
