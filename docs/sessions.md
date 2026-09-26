# Browser sessions (Scholar, EZProxy, publishers)

One local vault: `state/sessions/`. Playwright is a core dependency; Chromium
for the headless fallback installs automatically on first need.

`session login` **prefers your system Chrome/Edge** (launched without Playwright
automation flags) so Google SSO works, then attaches over CDP to save cookies
into the paperful profile. Use `--engine playwright` only as a fallback.

```sh
uv run paperful session login scholar
uv run paperful session login ezproxy
uv run paperful session login mendeley   # Elsevier OAuth; not the Chromium vault
uv run paperful session login scholar --engine chrome      # force system Chrome
uv run paperful session login scholar --engine playwright  # Playwright window
uv run paperful session status
uv run paperful session status --probe  # optional Scholar / EZProxy session_ok
uv run paperful session export          # refresh Netscape dumps for httpx
```

Scholar fetches during `run` reuse this Chromium profile when it exists (Google
often keys CAPTCHA to the browser, not cookies). htmlpdf uses the same profile
so a publisher login can apply. EZProxy landing pages and publisher PDFs that
403 on a cookie-only GET (ScienceDirect `/pdfft`, …) are fetched in this
profile too; exported cookies remain a fallback for httpx.

`paperful recover` and the auto `browser_agent` lane on `run` launch Chromium on this same
profile. `run` closes the Playwright `BrowserSession` before that lane so the
agent can take the profile; do not run a second `run` or `recover` against the
same vault at the same time.

`session login mendeley` is **not** this vault: it opens Elsevier’s OAuth page
and stores tokens in `state/mendeley-oauth.json`. See [Mendeley](mendeley.md).

Never commit `state/sessions/` or cookie files; never paste them into chat.

## If Google says “This browser or app may not be secure”

That is Google rejecting a Playwright-launched browser (automation flags /
`--no-sandbox`). Use the default system-Chrome login above. If an old automated
profile is stuck, remove `state/sessions/chromium/` and log in again.

## If you see `Session not ready` (Scholar)

| What you see | Likely cause | Fix |
| --- | --- | --- |
| `No session yet` / cookie file missing | No login / export | `paperful session login scholar` |
| `blocked or CAPTCHA` | Solved CAPTCHA in a different browser | Login via `session login` (same profile used during `run`) |
| Works in Chrome, fails here | Fingerprint mismatch | `session login scholar` (default system Chrome); or drop `scholar` from `sources` |

Do **not** probe Scholar in a tight loop.

When Scholar is blocked mid-run you will see `scholar blocked/captcha`. After
`circuit_breaker_threshold` (default 3) it pauses, then one later item is
tried again. A 429 does not pause it. Items left `captcha` / `error` /
`retryable` are retried on the next run; `not_found` (reason `closed`) needs
`--retry-failed`. An expired EZProxy session stops the proxy lane for the
rest of that run.
