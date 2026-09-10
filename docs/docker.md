# Docker (preferred deploy)

Docker Compose is the **preferred** way to run paperful as an operator.
Developers still use [`uv`](https://docs.astral.sh/uv/) locally (see
[CONTRIBUTING](https://github.com/glen-w/Paperful/blob/main/CONTRIBUTING.md)).

The image is a one-shot CLI (not a daemon). Zotero stays on the host; paperful
in the container talks to it over the local API (`:23119`). Durable data —
config, custom playbook packs, `out/`, and `state/` — lives **outside** the
git root by default.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- Zotero running on the host, local API enabled
  (Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*)
- For attach / `fix-metadata --apply`: complete the Zotero “Always allow”
  dialog once on the host (key is stored under `state/`)
- For Scholar / EZProxy sessions: run `paperful session login …` on the host
  (headed browser), then reuse the mounted `state/sessions/` from the container

## Quick start

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
cp .env.example .env
```

**Keep your current repo-local setup** (no data move):

```sh
mkdir -p packs out state
cp compose.override.example.yaml compose.override.yaml
# ensure config.toml exists (copy from config.example.toml if needed)
docker compose build
docker compose run --rm paperful doctor
docker compose run --rm paperful run --collection interesting --dry-run
```

**Or migrate into a sibling data directory** (recommended long-term):

```sh
mkdir -p ../paperful-data/packs ../paperful-data/out ../paperful-data/state
cp config.example.toml ../paperful-data/config.toml
# edit email / ezproxy_base / grey_playbooks_dir = "packs" as needed
# optional: move existing out/ and state/ into ../paperful-data/
docker compose build
docker compose run --rm paperful doctor
```

`PAPERFUL_DATA` in `.env` defaults to `../paperful-data`. Compose mounts that
tree at `/data` inside the container. Relative `out_dir` / `state_dir` /
`grey_playbooks_dir` in config resolve against the config file’s folder
(`/data`).

## Environment and override

| File | Role |
| --- | --- |
| [`.env.example`](https://github.com/glen-w/Paperful/blob/main/.env.example) | Copy to `.env` — `PAPERFUL_DATA`, `PAPERFUL_ZOTERO_HOST` |
| [`compose.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.yaml) | Base service (build, Zotero host, data volume) |
| [`compose.override.example.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.override.example.yaml) | Copy to `compose.override.yaml` to bind repo-local `config.toml` / `out` / `state` / `packs` |

`.env` and `compose.override.yaml` are gitignored so your machine-local paths
never land in the repo.

`PAPERFUL_ZOTERO_HOST` defaults to `host.docker.internal` so Docker Desktop
(macOS/Windows) can reach host Zotero. Compose also adds
`extra_hosts: host.docker.internal:host-gateway` for Linux Docker Engine.
paperful always sends `Host: localhost:23119` — Zotero’s local API requires
that header even when the TCP peer is `host.docker.internal`.

## Custom playbook packs

Put extra grey-playbook TOML files in `packs/` (under the data dir) and set in
config:

```toml
grey_playbooks_dir = "packs"
```

Merge order: builtin pack → `packs/*.toml` → inline `[[grey_playbooks]]`
(same `name` wins later). See [Configuration](config.md).

## Common commands

```sh
docker compose run --rm paperful doctor
docker compose run --rm paperful collections
docker compose run --rm paperful run --collection interesting --dry-run
docker compose run --rm paperful run --collection interesting
docker compose run --rm paperful report
make docker-build
make docker-doctor
```

Pass any CLI flag after the service name; the image `ENTRYPOINT` is `paperful`.

## Image contents

- Python 3.12, paperful + `htmlpdf` (Playwright Chromium)
- Poppler (`pdftotext`)
- Non-root user `paperful` (uid 1000)

If bind-mounted `out/` / `state/` are not writable, fix ownership on the host
(`chown -R 1000:1000 …`) or run with a matching user override.

## Sessions and attach

Headed Chromium login and Zotero’s authorize dialog need the host GUI. Typical
flow:

1. On the host (uv or a previous install): `paperful session login ezproxy`
   and/or `scholar`; approve attach once so `state/zotero-local-api-key.json`
   exists.
2. Ensure that `state/` is the same tree the container mounts.
3. Run fetch/attach from Docker as above.

## Develop with uv

For hacking on the package itself:

```sh
uv sync --group dev
uv run pytest
uv run paperful doctor
```

See [Commands](commands.md) and [Architecture](architecture.md).
