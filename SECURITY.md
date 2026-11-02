# Security

Paperful is a **local workbench** for one operator and a library they already
keep. It is not a multi-tenant SaaS. Trust boundaries assume the person who
can run `paperful` (or reach a published workbench port) is the operator.

## Threat model (local trust)

| Surface | Trust | Notes |
| --- | --- | --- |
| CLI / MCP stdio | Operator shell | Same privileges as the user process |
| `paperful serve` / Docker GUI | Loopback by default | **No HTTP authentication.** Anyone who can open the port can Preview/Grab/Attach and change Settings. Cross-site form posts from another origin are refused (`403`, see below), which stops a web page in the same browser from driving the workbench; it is not a login |
| Session vault (`state/sessions/`) | Operator disk | Cookies and campus SSO; never commit or paste |
| Outbound PDF / landing fetches | Library + playbook URLs | `is_fetchable_url` rejects loopback, RFC1918, link-local, and cloud-metadata targets; redirects are re-checked |
| Sci-Hub / Scholar / browser agent | Opt-in | Off unless enabled; legal and AUP responsibility stays with the operator — see [docs/scihub.md](docs/scihub.md) |

## Operator checklist

1. Keep `docker compose` publish on `127.0.0.1:8765` (the default). Do not
   publish `0.0.0.0:8765` on a shared network.
2. Prefer API keys in `.env` (gitignored), not in `config.toml`. Witness digests
   redact secret-looking TOML keys, but env vars are still the safer home.
   `paperful config check` lists secrets that should move to the environment.
3. Never share `state/sessions/`, cookie dumps, or Zotero/Mendeley token files.
4. `paperful serve --host 0.0.0.0` requires `--allow-remote-bind` and exposes the
   workbench **without auth by default** — only use it behind a tunnel or host
   firewall you control, and set `PAPERFUL_UI_TOKEN` (or `serve --ui-token`) so
   every request except `/health` needs `Authorization: Bearer <token>`. It is
   a single shared secret, not user accounts. (Compose already passes the flag
   inside the container while publishing localhost only.)

## Workbench request guards

- **UI token (optional).** When `PAPERFUL_UI_TOKEN` / `--ui-token` is set,
  `paperful.ui.token_guard` returns `401` for any request without a matching
  bearer token (or `X-Paperful-Token` header), except `/health`. Unset on
  loopback, behaviour is unchanged.
- **Origin check.** Every non-`GET`/`HEAD`/`OPTIONS` request is checked by
  `paperful.ui.origin_guard`: `Sec-Fetch-Site: cross-site` (or an `Origin` /
  `Referer` whose host differs from the request `Host`) returns
  `403 {"ok": false, "error": "cross-origin request blocked"}`. Same-origin
  form posts, `curl` without those headers, and the Firefox add-on talking to
  loopback are unaffected.
- **Content Security Policy.** `paperful.ui.security_headers` sends
  `script-src 'self'` (plus `frame-ancestors 'none'`, `form-action 'self'`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`) on every
  response. The templates contain **no inline scripts or `on*=` handlers**
  (behaviour hangs off `data-*` attributes in `workbench.js`), so a value
  reflected into a page cannot become executable code even if an escape is
  missed. `tests/test_build_hardening.py::test_templates_have_no_inline_handlers`
  keeps it that way. Fonts are self-hosted under `/static/fonts`; the
  workbench makes no third-party requests.
- **Reflected values.** Authorwatch list names arrive by query string and
  form field and are validated against `authorwatch._NAME_RE` before any
  render or directory access (`400` otherwise).
- **Redirects.** `Referer`-based redirects (`/prefs/advanced`) and the
  `next=` field on `/prefs/collection` accept same-host paths only.
- **Cookies.** Preference cookies are `SameSite=Strict` and suffixed with the
  port when it is not 8765, so two workbenches on one host do not share the
  collection chip or the Advanced toggle.
- **Job cap.** The GUI job queue accepts at most 20 pending jobs; a submit past
  that fails (`too many queued jobs`) instead of growing the queue. Activity
  shows the error text of failed jobs. Records left `queued`/`running` by a
  previous process are marked `failed` at startup so nothing polls them
  forever.
- **Settings writes.** `/settings` validates every field, writes TOML
  literals with proper escaping into the right table only, parses the
  result, and replaces `config.toml` atomically — or writes nothing.
- **Review tokens.** Writes still require a prior Preview whose token matches
  the current library fingerprint (stale → `409`). See
  [docs/gui.md](docs/gui.md#http-capability-api-p0--gui).

## Dependencies

CI runs `pip-audit` against the locked environment on every push and PR
(required `audit` job in `.github/workflows/ci.yml`, with a CycloneDX SBOM
artifact; direct pins such as `pypdf` and `urllib3` are kept at patched
floors), and Dependabot opens weekly update PRs for pip and GitHub Actions
(`.github/dependabot.yml`). Outbound fetch URLs are screened by
`is_fetchable_url` in `paperful/download.py`. Fetch stance, credential
handling, and privacy commitments are written down in
[docs/legal-privacy.md](docs/legal-privacy.md).

## Reporting

If you find a vulnerability in Paperful, open a private report via GitHub
Security Advisories on [glen-w/Paperful](https://github.com/glen-w/Paperful)
(or email the maintainer listed on the repo). Please do not file a public issue
for unfixed remote-exposure or secret-leak bugs.
