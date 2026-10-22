# Security

Paperful is a **local workbench** for one operator and a library they already
keep. It is not a multi-tenant SaaS. Trust boundaries assume the person who
can run `paperful` (or reach a published workbench port) is the operator.

## Threat model (local trust)

| Surface | Trust | Notes |
| --- | --- | --- |
| CLI / MCP stdio | Operator shell | Same privileges as the user process |
| `paperful serve` / Docker GUI | Loopback by default | **No HTTP authentication.** Anyone who can open the port can Preview/Grab/Attach and change Settings |
| Session vault (`state/sessions/`) | Operator disk | Cookies and campus SSO; never commit or paste |
| Outbound PDF / landing fetches | Library + playbook URLs | `is_fetchable_url` rejects loopback, RFC1918, link-local, and cloud-metadata targets; redirects are re-checked |
| Sci-Hub / Scholar / browser agent | Opt-in | Off unless enabled; legal and AUP responsibility stays with the operator — see [docs/scihub.md](docs/scihub.md) |

## Operator checklist

1. Keep `docker compose` publish on `127.0.0.1:8765` (the default). Do not
   publish `0.0.0.0:8765` on a shared network.
2. Prefer API keys in `.env` (gitignored), not in `config.toml`. Witness digests
   redact secret-looking TOML keys, but env vars are still the safer home.
3. Never share `state/sessions/`, cookie dumps, or Zotero/Mendeley token files.
4. `paperful serve --host 0.0.0.0` requires `--allow-remote-bind` and exposes the
   workbench **without auth** — only use it behind a tunnel or host firewall you
   control (Compose already passes the flag inside the container while publishing
   localhost only).

## Reporting

If you find a vulnerability in Paperful, open a private report via GitHub
Security Advisories on [glen-w/Paperful](https://github.com/glen-w/Paperful)
(or email the maintainer listed on the repo). Please do not file a public issue
for unfixed remote-exposure or secret-leak bugs.
