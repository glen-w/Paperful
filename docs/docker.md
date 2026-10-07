# Docker

Paperful is a **local CLI**. The operator install is `git clone` and
`docker compose build`. The image is **build-local only** (`paperful:local`).
There is no `docker pull` and no PyPI package. Zotero and headed browser
login live on the host. Docker does not replace them.

The Compose image is a **one-shot pack** — Python 3.12, Paperful, Poppler
(`pdftotext`), OCRmyPDF and Tesseract (`eng`), Playwright Chromium — for unattended commands (`run`, `lint`,
`ocr`, `report`, `attach` once a write key exists). It is not a daemon.
Build mode is selected with `PAPERFUL_IMAGE_MODE` (see below). Contributors can
still use [`uv`](https://docs.astral.sh/uv/) on the host (see the
[README](https://github.com/glen-w/Paperful#readme) Develop section).

Durable data — config, custom playbook packs, `out/`, and `state/` — still
lives **outside** the container (and, by default, outside the git root).

**Mounts (stranger path):** host `PAPERFUL_DATA` → container `/data`. `out/`
and `state/` are folders **inside** that tree (`/data/out`, `/data/state`),
not extra volumes. Compose does not mount Zotero Storage writable. See
[Terms](TERMS.md).

**What CI proves:** job `docker` in `.github/workflows/ci.yml` builds the
**light** image (`PAPERFUL_IMAGE_MODE` unset) and runs `doctor --no-guide`
with **no live Zotero**. Exit **2** is required (Zotero row amber/red). That
is a first-run stranger machine, not a failed Compose install. Pytest job
`test` is not the Compose-first proof.

## What still runs on the host

- Zotero (GUI, local API, “Always allow”)
- `paperful session login scholar|ezproxy` (headed Chrome/Edge on the host: campus SSO, Scholar CAPTCHA). An everyday-browser login does not transfer — see [Sessions](sessions.md)
- `paperful session login mendeley` (Elsevier OAuth; the localhost redirect will not
  reach a container — see [Mendeley](mendeley.md))
- EndNote `.enl` / `.Data` (desktop library on the host; Paperful never writes SQLite —
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
  from the container. `doctor` prints fix steps; use `doctor --guide` via
  `docker compose run` for step-by-step re-check (not `compose up`).

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
# Without host Zotero this exits 2 (amber/red). That is expected; CI job docker
# asserts the same. Start Zotero, then re-run doctor.
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
| [`.env.example`](https://github.com/glen-w/Paperful/blob/main/.env.example) | Copy to `.env` — `PAPERFUL_DATA`, `PAPERFUL_ZOTERO_HOST`, `PAPERFUL_IMAGE_MODE` |
| [`compose.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.yaml) | Base service (build, Zotero host, data volume) |
| [`compose.override.example.yaml`](https://github.com/glen-w/Paperful/blob/main/compose.override.example.yaml) | Optional local Compose tweaks |

`.env` and `compose.override.yaml` are gitignored so your machine-local paths
never land in the repo. Set `PAPERFUL_DATA=.` to keep config/`out`/`state` in the
repo; use `../paperful-data` (default) to keep packs and outputs outside the
git root.

### Image mode: light vs heavy

| Mode | `PAPERFUL_IMAGE_MODE` | Python extras | Typical use |
| --- | --- | --- | --- |
| **light** | `light` (Compose default when unset) | `[serve]` | CI, small stranger image |
| **heavy** | `heavy` (set in `.env.example`) | `[serve]` `[llm]` `[rag]` `[browser-agent]` | Full local env |

`rag-docling` (Torch) is not in either image; use host `uv sync --extra rag-docling` if you need Docling parsing.

```sh
# Local full pack (recommended after cp .env.example .env):
PAPERFUL_IMAGE_MODE=heavy docker compose build
# or: make docker-build-heavy

# Slim pack (CI / default when the variable is unset):
PAPERFUL_IMAGE_MODE=light docker compose build
```

Rebuild after changing the mode (`docker compose build`). The image label
`paperful.image.mode` records which pack was built.

`PAPERFUL_ZOTERO_HOST` and `PAPERFUL_OLLAMA_HOST` default to
`host.docker.internal` so Docker Desktop (macOS/Windows) can reach Zotero and
Ollama on the host. Compose also adds
`extra_hosts: host.docker.internal:host-gateway` for Linux Docker Engine.
Paperful always sends `Host: localhost:23119` — Zotero’s local API requires
that header even when the TCP peer is `host.docker.internal`. Outside Docker,
`host.docker.internal` in those env vars falls back to localhost / `127.0.0.1`
so a shared `.env` does not break host `uv run`.

## Optional LLM, RAG, and browser-agent

**light** ships `[serve]` only (FastAPI/Jinja for the Compose `gui` profile).
**heavy** also installs `[llm]`, `[rag]` (LanceDB), and `[browser-agent]`
(`browser-use`), so `rag` / `ask`, LiteLLM, and the `browser_agent` lane work
inside the container. Headed `session login` still stays on the host (shared
`state/` vault).

The GUI binds in the container on `0.0.0.0:8765` and **publishes only**
`127.0.0.1:8765:8765` (no LAN). Same workbench as host `paperful serve`
([gui.md](gui.md) — Discover / Wanted; Advanced Repair / Mirror / Index / Briefs):

```sh
docker compose -f compose.yaml -f compose.gui.yaml --profile gui up paperful-gui
```

Host-only `uv run paperful serve` remains the contributor path. `fix-metadata` title
proposals, the `lint` identity check, `summarize`, and `synthesize` work from the container
against an Ollama running on the host. Keep loopback in `config.toml`
(`base_url = "http://127.0.0.1:11434"`); Paperful rewrites it to
`host.docker.internal` inside the container via `PAPERFUL_OLLAMA_HOST`.

On **Docker Desktop**, the default Ollama loopback bind is enough (same as
Zotero). On **Linux Docker Engine**, bind with
`OLLAMA_HOST=0.0.0.0 ollama serve` so `host-gateway` can connect.
`docker compose run --rm paperful doctor` shows the `LLM` row. Details:
[LLM](llm.md#docker). See [rag.md](rag.md) for the index.

## Custom playbook packs

Put extra grey-playbook TOML files in `packs/` (under the data dir) and set in
config. Optional energy and international-org copies (IEA/IRENA,
OECD/WHO/UNEP/UNDP) ship inside the package as
`paperful/data/grey_playbooks_examples/`. Copy those files into `packs/`.
That examples folder does not include the ocean builtin, which is already on
by default.

```toml
grey_playbooks_dir = "packs"
```

Merge order: builtin pack → `packs/*.toml` → inline `[[grey_playbooks]]`
(same `name` wins later). See [Configuration](config.md).

Vault and browser-agent PDF successes append `state/fetch-wins.jsonl` on this
volume (agent rows may include `steps` and promotable `click:` / `rewrite`
wins). `paperful playbooks promote` (and `[playbooks].promote = "auto"`)
writes `packs/learned.toml` when `grey_playbooks_dir = "packs"`. Both `state/`
and `packs/` are gitignored. `auto` may promote a fluke; the default is
`gated`. Headed `session login` stays on the host; a container `run` still
writes wins onto the shared `state/` mount.

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
(resumable; Ctrl-C then rerun). Same flags as [Commands](commands.md),
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
make docker-build          # uses PAPERFUL_IMAGE_MODE from .env
make docker-build-heavy    # force heavy pack
make docker-doctor
```

Pass any CLI flag after the service name; the image `ENTRYPOINT` is `paperful`.
The same commands as [uv snippets](commands.md) — `docker compose run --rm paperful`
instead of `uv run paperful`. Headed `session login` is still host-only.

## Image contents

- Python 3.12, Paperful + Playwright Chromium (htmlpdf / session vault reuse)
- Poppler (`pdftotext`), OCRmyPDF, Tesseract (`eng`)
- `[serve]` always; **heavy** also `[llm]` `[rag]` `[browser-agent]`
- Non-root user `paperful` (uid 1000)

If bind-mounted `out/` / `state/` are not writable, fix ownership on the host
(`chown -R 1000:1000 …`) or run with a matching user override.

## Sessions and attach

Headed Chromium login and Zotero’s authorize dialog need the host GUI. Typical
flow:

1. `docker compose run --rm paperful doctor` — prints fix steps for amber
   session checks. Run `paperful session login ezproxy` / `scholar` **on the
   host** (same `PAPERFUL_DATA` / `state/` the container mounts), then re-run
   doctor. For Enter-to-re-check: `doctor --guide` (use `compose run`, not
   `compose up`).
2. Approve attach once on the host so `state/zotero-local-api-key.json` exists.
3. Run fetch/attach from the container as above.

## Usual path (`uv`)

```sh
uv sync --group dev
uv run pytest
uv run paperful doctor
```

See [Commands](commands.md), [Architecture](architecture.md), and [Zotero](zotero.md).
