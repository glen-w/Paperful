# SerpApi (Google Scholar search)

[SerpApi](https://serpapi.com/) is a **paid search API**. Paperful uses only
its Google Scholar engine: one HTTP call per remaining item, structured
results instead of scraping `scholar.google.com` yourself.

It is **link discovery**, not a PDF host. When a result lists a PDF URL
(author manuscript, institutional repository, preprint), Paperful downloads
that file the same way it would after Unpaywall or a local Scholar hit.
Provenance is `web:serpapi`. The download is still your httpx/browser path;
SerpApi does not fetch the PDF.

Paperful never turns this on by itself. There is no silent cloud default.

## When it can help

Local Scholar is opt-in and easy to block (CAPTCHA, 429, 503). SerpApi is a
separate quota and a JSON API, so it can still return `[PDF]` links after
those local lanes stall.

Typical useful cases:

- Unpaywall / OpenAlex missed a copy that Google indexed (IR, author page,
  society preprint).
- Title-only or weak-DOI records where Scholar’s query is a better lookup
  than a DOI resolver.
- You already burned local Scholar or the vault browser and still have misses.

Each remaining item after the free/local serial tail can cost **one** search
credit. Hits still have to download; a listed PDF that 403s is a miss.

## When it will not help

- Publisher paywalls. A Scholar snippet that points at the article landing
  page is not an OA PDF. Paperful does not treat SerpApi as a bypass.
- Soft-blocked `downloadpdf` URLs. Those still need campus EZProxy, the vault
  browser, or [handoff](how-it-works.md) in your normal session.
- Places Google does not index, or results that only show HTML.
- Exhausted SerpApi plan, HTTP 429/402 from their API (Paperful latches the
  rest of the run as `serpapi:skipped(quota)`).
- Expecting it to replace Unpaywall. Most OA PDFs already come from the
  parallel OA head.

Prefer campus access and OA indexes first. Prefer a logged-in Scholar handoff
tab when you want to click through yourself (`[handoff].scholar`).

## Setup

1. Create a SerpApi account and copy the API key.
2. Put it in a gitignored `.env` (see `.env.example`):

   ```
   SERPAPI_API_KEY=…
   ```

   `paperful` loads that file at startup. Do not put the key in `config.toml`
   or commit it.
3. Opt in:

   ```toml
   [serpapi]
   enabled = true
   max_calls = 20
   ```

`paperful doctor` greens when the key is set and does **not** spend a search
to prove it. Amber if `enabled` is true and the env var is empty.

## Order in a run

With default `[fetch].order = "policy"`, SerpApi runs in the late serial
tail: after OA, campus, grey, local Scholar, and `browser_agent`, and before
any later opt-in grey-zone source. `[fetch].order = "list"` only uses
`serpapi` if you put it in `sources` yourself.

The query is the same shape as local Scholar (DOI, else a long title).
`--try-all` still respects the paid cap below.

## Caps (`max_calls` / `--serpapi-max`)

Paid searches are easy to burn on a large `--retry-failed` or library-wide
`run`. Paperful counts **actual API calls this process** (not skipped
inapplicable items).

| Setting | Meaning |
| --- | --- |
| `[serpapi].max_calls` | Default **20**. `0` = no cap for every run that uses this config |
| `--serpapi-max N` | Override for one `run` or `all` (also `0` = unlimited) |

When the cap is reached, remaining items log `serpapi:skipped(max_calls)` and
continue through later sources. The quota latch (`skipped(quota)`) is
separate: that fires on 429/402 from SerpApi, not on your configured cap.

```sh
# stay inside a small monthly leftover
uv run paperful run -C Inbox --serpapi-max 5

# this process only; ignore the config default
uv run paperful run -C Inbox --serpapi-max 0
```

## What Paperful does not do

- Probe SerpApi on `doctor` or at startup (that would spend a credit).
- Use other SerpApi engines (Google web, Google Maps, …).
- Send your library through SerpApi unless `[serpapi].enabled` is true **and**
  `SERPAPI_API_KEY` is set.
