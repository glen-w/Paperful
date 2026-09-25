# Contributing to Paperful

## Who uses what

| Role | Install | Docs |
| --- | --- | --- |
| **Operator** | Docker Compose (`docker compose build`) | [Quick start](docs/start/quickstart.md), [Docker](docs/howto/docker.md) |
| **Contributor** | [`uv`](https://docs.astral.sh/uv/) | This file + [docs guide](docs/contribute/docs-guide.md) |

Zotero and headed `session login` always run on the host. There is no
published image and no PyPI package for operators.

## Setup (contributors)

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
uv sync --group dev
cp config.example.toml config.toml   # personal — never commit config.toml
```

Hosted docs: `uv sync --extra docs && make docs` (Sphinx HTML) or
`make pages-site` (`website/` + `/guide/` in `_site/`). Markdown under `docs/`
is the corpus — see [Documentation guide](docs/contribute/docs-guide.md).

Zotero must be running with the local API enabled for integration tests that
touch the CLI; most tests use stubs and run offline.

## Tests

```sh
uv run pytest
```

CI runs the same suite on every push and pull request (see
`.github/workflows/ci.yml`). User-facing changes: note them in
[CHANGELOG.md](CHANGELOG.md) and [docs/start/releases.md](docs/start/releases.md)
when they affect 0.x vs 1.0 promises.

## Pull requests

- Keep changes focused; match existing style in `paperful/`.
- Add or update tests for behaviour changes.
- Do not commit personal `config.toml`, `state/`, `out/`, `packs/`, `.env`,
  `compose.override.yaml`, or cookie files.
- Doc edits: change the canonical page under `docs/start|paths|howto|reference|explain|contribute/`;
  keep flat `docs/<name>.md` stubs thin (CLI and old bookmarks).

## Architecture

See [docs/explain/architecture.md](docs/explain/architecture.md). CLI
orchestrates; identifier and PDF-text work lives in `resolve` / `pdfid` /
`lint` / `metadata`; source adapters must not write `manifest` or `out_dir`.
Managers go through `LibraryBackend` in `paperful/library.py`. Default tests
stay offline. Product direction: [docs/contribute/ROADMAP.md](docs/contribute/ROADMAP.md).
