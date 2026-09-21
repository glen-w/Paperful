# Browser sessions (Scholar, EZProxy, publishers)

One local vault: `state/sessions/`. Playwright is a core dependency; Chromium
for the headless fallback installs automatically on first need.

`session login` **prefers your system Chrome/Edge** (launched without Playwright
automation flags) so Google SSO works, then attaches over CDP to save cookies
into the paperful profile. Use `--engine playwright` only as a fallback.

```sh
uv run paperful session login scholar
uv run paperful session login ezproxy
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

`paperful recover` (opt-in browser agent) launches its own Chromium on this same
profile, so the normal `BrowserSession` is not opened during `recover`; do not run
`run` and `recover` at the same time against one vault.

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
`circuit_breaker_threshold` (default 3) it is skipped for the rest of that
run. Items left `captcha` / `error` are retried on the next run; `not_found`
needs `--retry-failed`.
