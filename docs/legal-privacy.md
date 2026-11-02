# Legal, fetch stance, and privacy

Paperful is a local tool for one operator working with a library they
already keep. This page is the written position the Roadmap asked for:
what Paperful will fetch, what it will not do, and what never leaves the
machine. It is not legal advice.

## Fetch stance

- **Open access first.** The default lanes are publisher/open repositories
  and indexes (Unpaywall, OpenAlex, Crossref, CORE, arXiv, landing pages).
  A real contact `email` in config is sent to those APIs because their
  polite pools ask for one.
- **Your access, your responsibility.** Campus/EZProxy and session lanes
  replay *your* institution's access in *your* browser profile. Whether a
  download is permitted by a publisher's terms or your library licence is
  the operator's call; Paperful does not grant rights it does not hold.
- **Sci-Hub is opt-in only**, off by default, and never enabled by a
  playbook you did not choose. See [scihub](scihub.md).
- **No CAPTCHA bypass, no bot-wall evasion.** When a site challenges the
  fetch, Paperful stops and tells you; solving the challenge is a human
  action in your own session.
- **Polite by default.** Fetches identify with the configured email,
  honour per-host pacing and the circuit breaker, and screen every URL
  (and redirect) through `is_fetchable_url` so the workbench cannot be
  pointed at loopback, RFC1918, link-local, or cloud-metadata targets.
- **Provenance is recorded.** Run reports note which lane produced each
  PDF, so a library built with Paperful can answer "where did this come
  from?" later.

## Credentials and privacy

- **Secrets live in the environment, not the config file.**
  `paperful config check` flags secret-looking keys in `config.toml` and
  points at the env var to use instead. `.env` is gitignored. An OS
  keyring backend was evaluated for 1.7 and rejected: headless/Docker
  operators have no keyring daemon, and env vars already work everywhere
  (see `docs/plans/1.7-wave.md`).
- **On-disk tokens are owner-only.** Mendeley OAuth tokens are written
  `0600`; the session vault under `state/sessions/` holds campus cookies
  and must be treated like a password — never commit, paste, or share it.
- **Keys go only to their own API.** A Zotero key is sent to Zotero, a
  Mendeley token to Mendeley; nothing is proxied through a Paperful
  service, because there is no Paperful service.
- **No telemetry.** Paperful phones home nowhere. The only outbound calls
  are the ones a command you ran makes: reference-manager APIs, scholarly
  indexes, and fetch lanes above.
- **Update notice is opt-in.** With `[updates] check = true`, `doctor`
  fetches the latest version string from PyPI at most once a day (cached
  under `state/`) and prints a line if you are behind. It sends no usage
  data and never runs in the background.
- **Local by default.** The workbench binds loopback, the mirror and run
  reports stay on your disk, and LLM/RAG lanes use providers *you*
  configure — prompts leave the machine only to the endpoint you chose.

## Sustainability note

Paperful is maintained by one person under the licence in the repo root.
If maintenance stops, everything keeps working offline: the mirror, run
reports, and this documentation are plain files in your library folder.
