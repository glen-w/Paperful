# Docker

paperful is a **local CLI**. The operator install is `git clone` and
`docker compose build`. The image is **build-local only** (`paperful:local`).
There is no `docker pull` and no PyPI package. Zotero and headed browser
login live on the host. Docker does not replace them.

The Compose image is a **one-shot pack** — Python 3.12, paperful, Poppler
(`pdftotext`), Playwright Chromium — for unattended commands (`run`, `lint`,
`report`, `attach` once a write key exists). It is not a daemon and not a
complete environment. Contributors use [`uv`](https://docs.astral.sh/uv/)
(see the [README](https://github.com/glen-w/Paperful#readme) Develop section).

Durable data — config, custom playbook packs, `out/`, and `state/` — still
lives **outside** the container (and, by default, outside the git root).

## What still runs on the host

- Zotero (GUI, local API, “Always allow”)
- `paperful session login scholar|ezproxy` (headed Chrome/Edge on the host: campus SSO, Scholar CAPTCHA)
- `paperful session login mendeley` (Elsevier OAuth; the localhost redirect will not
  reach a container — see [Mendeley](mendeley.md))
- EndNote `.enl` / `.Data` (desktop library on the host; paperful never writes SQLite —
  see [EndNote](endnote.md))
- Any scripts that read `out/` / `state/` as files

The container talks to host Zotero over the local API (`:23119`). Session
vaults and the write key must be the **same** `state/` tree the container
mounts (`PAPERFUL_DATA`).

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- Zotero running on the host, local API enabled
  (Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*)
- For attach / `fix-metadata --apply`: complete the Zotero “Always allow”
  dialog once on the host (key is stored under `state/`)
- For Scholar / EZProxy sessions: a host `uv` install so you can run
  `paperful session login …`, then reuse the mounted `state/sessions/`
  from the container. Interactive `doctor` (default on a TTY) walks you
  through this and re-checks.

## Quick start

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
cp .env.example .env
```

**Keep your current repo-local setup** (no data move):

```sh
cp .env.example .env
# edit .env: PAPERFUL_DATA=.
docker compose build
docker compose run --rm paperful doctor
docker compose run --rm paperful run --collection interesting --dry-run
```

**Or migrate into a sibling data directory** (recommended if you use Compose
long-term):

```sh
cp .env.example .env   # PAPERFUL_DATA=../paperful-data
mkdir -p ../paperful-data/packs ../paperful-data/profiles ../paperful-data/out ../paperful-data/state
cp config.example.toml ../paperful-data/config.toml
# edit email / ezproxy_base / grey_playbooks_dir = "packs" as needed
# optional: move existing out/ and state/ into ../paperful-data/
docker compose build
docker compose run --rm paperful doctor
```

`PAPERFUL_DATA` in `.env` defaults to `../paperful-data`. Compose mounts that
tree at `/data` inside the container. Use **relative** `out_dir` / `state_dir` /
`grey_playbooks_dir` in config (e.g. `"out"`, `"state"`, `"packs"`) so they
resolve under the mounted data dir. Absolute host paths (e.g. `/Users/...`)
will not land on the volume.

## Environment and override

| File | Role |
| --- | --- |
| [`.env.example`](https://github.com/glen-w/Paperful/blob/main/.env.example) | Copy to `.env` — `PAPERFUL_DATA`, `PAPERFUL_ZOTERO_HOST` |
| [`compose.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.yaml) | Base service (build, Zotero host, data volume) |
| [`compose.override.example.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.override.example.yaml) | Optional local Compose tweaks |

`.env` and `compose.override.yaml` are gitignored so your machine-local paths
never land in the repo. Set `PAPERFUL_DATA=.` to keep config/`out`/`state` in the
repo; use `../paperful-data` (default) to keep packs and outputs outside the
git root.

`PAPERFUL_ZOTERO_HOST` defaults to `host.docker.internal` so Docker Desktop
(macOS/Windows) can reach host Zotero. Compose also adds
`extra_hosts: host.docker.internal:host-gateway` for Linux Docker Engine.
paperful always sends `Host: localhost:23119` — Zotero’s local API requires
that header even when the TCP peer is `host.docker.internal`.

## Optional LLM inside the image

The image ships neither `litellm` nor `browser-use`, so the `browser_agent` lane
(`run` auto-recover and `paperful recover`) is host-only (it also needs the
headed-login vault). `fix-metadata` title
proposals, the `lint` identity check, `summarize`, and `synthesize` work from the container
against an Ollama running on the host:

```toml
[llm]
enabled = true
base_url = "http://host.docker.internal:11434"
allow_remote = true    # host.docker.internal is not loopback
```

Start Ollama listening on all interfaces (`OLLAMA_HOST=0.0.0.0 ollama serve`).
`docker compose run --rm paperful doctor` shows the `LLM` row. Details:
[LLM](llm.md#docker).

## Custom playbook packs

Put extra grey-playbook TOML files in `packs/` (under the data dir) and set in
config:

```toml
grey_playbooks_dir = "packs"
```

Merge order: builtin pack → `packs/*.toml` → inline `[[grey_playbooks]]`
(same `name` wins later). See [Configuration](../reference/config.md).

## Run configs

`profiles/` next to `config.toml` holds named run configs (`paperful all
--profile`, `paperful profile save`). That directory is not the grey-lit
`packs/` folder and not `state/packs/`.

```sh
mkdir -p ../paperful-data/profiles
docker compose run --rm paperful profile list
docker compose run --rm paperful all --profile bbnj-journal --dry-run
```

See [Workflows](workflows.md).

## After doctor is green

Keep Zotero running. Bare `docker compose run --rm paperful` is `doctor`
(image `CMD`). To fetch:

```sh
docker compose run --rm paperful collections
docker compose run --rm paperful run --collection interesting --dry-run
docker compose run --rm paperful run --collection interesting
docker compose run --rm paperful report
```

`--no-attach` writes to `out/` only. `--library` walks the whole library
(resumable; Ctrl-C then rerun). Same flags as [Commands](../reference/commands.md),
including `--year-from` / `--year-to` and `--type` / `-T`.

```sh
docker compose run --rm paperful run -C BBNJ --year-from 2023 -T journalArticle --dry-run
```

## Common commands

```sh
docker compose run --rm paperful            # doctor (default)
docker compose run --rm paperful doctor --no-guide
docker compose run --rm paperful collections
docker compose run --rm paperful dedupe -C BBNJ --dry-run
docker compose run --rm paperful run --collection interesting --dry-run
docker compose run --rm paperful run --collection interesting
docker compose run --rm paperful report
make docker-build
make docker-doctor
```

Pass any CLI flag after the service name; the image `ENTRYPOINT` is `paperful`.
The same commands as [uv snippets](../reference/commands.md) — `docker compose run --rm paperful`
instead of `uv run paperful`. Headed `session login` is still host-only.

## Image contents

- Python 3.12, paperful + Playwright Chromium (htmlpdf / session vault reuse)
- Poppler (`pdftotext`)
- Non-root user `paperful` (uid 1000)

If bind-mounted `out/` / `state/` are not writable, fix ownership on the host
(`chown -R 1000:1000 …`) or run with a matching user override.

## Sessions and attach

Headed Chromium login and Zotero’s authorize dialog need the host GUI. Typical
flow:

1. `docker compose run --rm paperful doctor` — on a TTY, amber session checks
   open a guide: run `paperful session login ezproxy` / `scholar` **on the host**
   (same `PAPERFUL_DATA` / `state/` the container mounts), press Enter in the
   container to re-check. Or skip with `--no-guide`.
2. Approve attach once on the host so `state/zotero-local-api-key.json` exists.
3. Run fetch/attach from the container as above.

Without the guide:

1. On the host (`uv`): `paperful session login ezproxy` and/or `scholar`;
   approve attach once so `state/zotero-local-api-key.json` exists.
2. Ensure that `state/` is the same tree the container mounts.
3. Run fetch/attach from the container as above.

## Contributor path (`uv`)

Operators stay on Compose above. Contributors developing the package:

```sh
uv sync --group dev
uv run pytest
uv run paperful doctor
```

See [Contributing](../../CONTRIBUTING.md), [Commands](../reference/commands.md),
[Architecture](../explain/architecture.md), and [Zotero](zotero.md).
