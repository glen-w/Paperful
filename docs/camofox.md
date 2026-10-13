# Camofox recover lane

Opt-in serial lane that talks to an external
[camofox-browser](https://github.com/jo-inc/camofox-browser) REST server
(Camoufox / Firefox with accessibility snapshots). It runs **after** vault
Playwright lanes (`scholar` / `ezproxy` / `htmlpdf`) and **before** the LLM
`browser_agent` lane.

This is **not** a Cloudflare-bypass product and **not** a drop-in replacement
for browser-use. It does **not** reuse the vault Chromium SSO profile.

## When to use it

- Soft bot walls or publisher landings where a scripted PDF link / download
  control is enough
- You want a cheaper try before spending LLM steps in `browser_agent`

Skip it when the PDF needs campus SSO that only lives in the vault Chrome
profile — keep using EZProxy / Scholar / `browser_agent` for those.

## Setup

1. Run the server (once per machine):

```bash
npx @askjo/camofox-browser
# -> http://127.0.0.1:9377
```

Or Docker / source install from the upstream README.

2. Enable the lane in `config.toml`:

```toml
[camofox]
enabled = true
during_run = true
base_url = "http://127.0.0.1:9377"
max_wall_s = 90
```

3. Optional: if the server sets `CAMOFOX_ACCESS_KEY`, export the same value in
   the Paperful environment so requests send `Authorization: Bearer …`.

4. Check readiness:

```bash
paperful doctor
```

## Behaviour

On `run` / `all` / snowball full-stack, Paperful injects `camofox` when
`[camofox].enabled` and `during_run` are on (override with `--camofox` /
`--no-camofox`). The same vault-miss / soft-block gate as `browser_agent`
applies: the lane is skipped unless a vault browser lane was tried and failed
(or OA soft-blocked).

For each eligible item Paperful:

1. Opens a camofox tab on the DOI or item URL
2. Tries inline PDF capture (`fetch-current-resource`) and download artifacts
3. Ranks page links with the same PDF heuristics used elsewhere
4. Clicks / navigates a few candidates and polls downloads
5. Validates `%PDF` + `min_pdf_bytes`, then stamps `source=camofox`

CAPTCHA / Cloudflare-looking snapshots return `captcha` and fall through to
`browser_agent` when that lane is also on.

## Privacy

Upstream camofox can send anonymized crash telemetry. For campus or sensitive
hosts, set `CAMOFOX_CRASH_REPORT_ENABLED=false` on the **server** process (see
upstream docs). Paperful never starts the Node process and never forwards page
HTML to a remote LLM on this lane.

## Related

- [browser-agent models](browser-agent-models.md) — LLM recover after this lane
- [config](config.md) — `[camofox]` keys
- [sources](sources.md) — routing table
- [docker.md](docker.md#optional-camofox-sidecar) — host/sidecar server from Compose
- [llm.md](llm.md#a-recover--browser-agent-pdf-recovery) — where this lane sits vs `browser_agent`
