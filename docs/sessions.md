# Browser sessions (Scholar, EZProxy, publishers)

One local vault: `state/sessions/`. Requires `paperful[htmlpdf]`.

```sh
uv run paperful session login scholar
uv run paperful session login ezproxy
uv run paperful session status
uv run paperful session status --probe  # optional Scholar / EZProxy session_ok
uv run paperful session export          # refresh Netscape dumps for httpx
```

Scholar fetches during `run` use this Chromium profile when it exists (Google
often keys CAPTCHA to the browser, not cookies). htmlpdf uses the same profile
so a publisher login can apply. EZProxy PDF downloads stay on httpx using the
exported cookies.

Never commit `state/sessions/` or cookie files; never paste them into chat.

## If you see `Session not ready` (Scholar)

| What you see | Likely cause | Fix |
| --- | --- | --- |
| `No session yet` / cookie file missing | No login / export | `paperful session login scholar` |
| `blocked or CAPTCHA` | Solved CAPTCHA in a different browser | Login in the paperful Chromium window |
| Works in Chrome, fails here | Fingerprint mismatch | `session login scholar`; or drop `scholar` from `sources` |

Do **not** probe Scholar in a tight loop.

When Scholar is blocked mid-run you will see `scholar blocked/captcha`. After
`circuit_breaker_threshold` (default 3) it is skipped for the rest of that
run. Items left `captcha` / `error` are retried on the next run; `not_found`
needs `--retry-failed`.
