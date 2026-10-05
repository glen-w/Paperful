# Browser sessions (Scholar, EZProxy, publishers)

Log in once in your normal browser; Paperful reuses that login on this
machine. The walkthrough is [How it works](how-it-works.md#using-your-scholar-or-library-login).
This page is the vault, engines, and CAPTCHA troubleshooting.

One local vault: `state/sessions/`. Playwright is a core dependency; Chromium
for the headless fallback installs automatically on first need.

`session login` **prefers your system Chrome/Edge** (launched without Playwright
automation flags) so Google SSO works, then attaches over CDP to save cookies
into the Paperful profile. Use `--engine playwright` only as a fallback.

```sh
uv run paperful session login scholar
uv run paperful session login ezproxy
uv run paperful session login mendeley   # Elsevier OAuth; not the Chromium vault
uv run paperful session login scholar --engine chrome      # force system Chrome
uv run paperful session login scholar --engine playwright  # Playwright window
uv run paperful session status
uv run paperful session status --probe  # optional Scholar / EZProxy session_ok
uv run paperful doctor --probe          # same live check inside doctor
uv run paperful session export          # refresh storage_state + Netscape (keeps tickets)
```

`session_ok` prefers the vault Chromium profile (the same path as Unpaywall
browser wraps) and falls back to httpx + Netscape cookies. Campus EZProxy /
CAS tickets are often **session cookies**. Login writes them to
`state/sessions/storage_state.json` (Playwright format, keeps `sameSite`) and
mirrors Netscape dumps for httpx (`cookies.txt`, `ezproxy-cookies.txt`). Chrome
drops session cookies from the profile when it exits; the vault browser
re-injects `storage_state` (then Netscape) on launch so probes and publisher
fetches match the httpx jar. `session export` re-injects before refreshing so
it does not wipe those tickets.

Offline `session status` / `doctor` report **proxy-host ticket** vs **CAS/IdP
only**. `doctor --probe` and `session status --probe` refuse to green-light a
CAS-only vault even if a live SSO hop would briefly succeed — re-run
`session login ezproxy` and wait until a publisher page loads through the proxy
(URL should include your `idm.oclc.org` host) before pressing Enter. File
presence without `--probe` still does not prove campus SSO is live.

Scholar fetches during `run` reuse this Chromium profile when it exists (Google
often keys CAPTCHA to the browser, not cookies). htmlpdf uses the same profile
so a publisher login can apply. EZProxy landing pages and publisher PDFs that
403 on a cookie-only GET (ScienceDirect `/pdfft`, …) are fetched in this
profile too; exported cookies remain a fallback for httpx. A landing page
that is HTML is settled, an SSO interstitial is waited out, then a playbook
rewrite, `citation_pdf_url` / PDF links, download controls (including View
PDF), and a PDF viewer iframe are tried before the miss.

Successful vault downloads and browser-agent PDFs append a line to
`state/fetch-wins.jsonl` (host and path only, no query string). Browser-agent
rows may include a `steps` trace and a promotable `win` (`click:…`, `rewrite`,
or `meta`) derived from the agent history. `paperful playbooks propose` drafts
a learned pack from those wins; `playbooks promote`
writes `{grey_playbooks_dir}/learned.toml`. Default `[playbooks].promote` is
`gated`. `auto` writes that file after `auto_min_hits` matching wins (default
2) and can still promote a fluke — a one-off URL or cookie-banner path. Prefer
`gated` unless you will edit `learned.toml` by hand. `run --promote gated|auto`
overrides the config for one process.

`paperful recover` (`--item` or `--from-last-run`) and the auto `browser_agent`
lane on `run` launch Chromium on this same profile. `run` closes the Playwright `BrowserSession` before that lane so the
agent can take the profile; do not run a second `run` or `recover` against the
same vault at the same time. Headed EZProxy re-login during `run` does the same
release first — otherwise Chrome exits with no window while the probe still holds
`state/sessions/chromium`.

`session login mendeley` is **not** this vault: it opens Elsevier’s OAuth page
and stores tokens in `state/mendeley-oauth.json`. See [Mendeley](mendeley.md).

Never commit `state/sessions/` or cookie files; never paste them into chat.

## If Google says “This browser or app may not be secure”

That is Google rejecting a Playwright-launched browser (automation flags /
`--no-sandbox`). Use the default system-Chrome login above. If an old automated
profile is stuck, remove `state/sessions/chromium/` and log in again.

## If Chrome never opens / `Chrome did not open a debug port`

Another process is using `state/sessions/chromium` (a live `run`, `doctor
--probe`, or a leftover headless Chrome). Stop that job, or quit the Chrome
whose command line includes that profile path, then retry
`paperful session login ezproxy`.

## If CDP attach fails (`Browser context management is not supported`)

Playwright connected to the debug port but could not apply its usual browser
overrides. Current Paperful uses `no_defaults` on attach (cookies only). If you
still see this, close other Chrome windows on the Paperful profile and retry,
or fall back with `--engine playwright`.

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
`--retry-failed`. An expired EZProxy session pauses proxy wraps; on a TTY
`run` offers re-login at the next batch boundary and again after the fetch for
items left `session expired`.
