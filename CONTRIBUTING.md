# Contributing to Paperful

## Setup

Operators clone and `docker compose build`. Contributors use `uv`.
[Docker](docs/docker.md) packs Python, Poppler, and Chromium; Zotero and
headed session login still run on the host. A release checklist: version in
`pyproject.toml` matches the README badge and the website footer, CHANGELOG
has a section, and `docs/releases.md` still says install is clone plus
Compose (no pull, no pip) unless a real artifact exists.

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
uv sync --group dev
cp config.example.toml config.toml   # personal — never commit config.toml
```

Hosted docs: `uv sync --extra docs && make docs` (Sphinx HTML) or
`make pages-site` (`website/` + `/guide/` in `_site/`). The guide corpus is
only `docs/*.md`; every page must appear in `docs/index.md` toctrees
(`tests/test_sphinx_docs.py`). CI and Pages deploy use `DOCS_STRICT=1` (Sphinx
`-W`). Live site: [paperful.app](https://paperful.app/) with the guide at
[paperful.app/guide/](https://paperful.app/guide/).

Zotero must be running with the local API enabled for integration tests that touch the CLI; most tests use stubs and run offline.

## Tests

```sh
uv run pytest
DOCS_STRICT=1 make docs   # after: uv sync --extra docs
```

CI runs pytest on every push and PR (`.github/workflows/ci.yml`). The Docs
workflow (`.github/workflows/docs.yml`) runs the guide corpus tests and a strict
Sphinx build; pushes to `main` that touch `docs/` or `website/` also redeploy
Pages (`.github/workflows/pages.yml`).
User-facing changes: note them in [CHANGELOG.md](CHANGELOG.md) and
[docs/releases.md](docs/releases.md) when they affect 0.x vs 1.0 promises.

## Pull requests

- Keep changes focused; match existing style in `paperful/`.
- Add or update tests for behaviour changes.
- Do not commit personal `config.toml`, `state/`, `out/`, `packs/`, `.env`,
  `compose.override.yaml`, or cookie files.

## Architecture

See [docs/architecture.md](docs/architecture.md). CLI orchestrates; identifier
and PDF-text work lives in `resolve` / `pdfid` / `lint` / `metadata`; source
adapters must not write `manifest` or `out_dir`. Managers go through
`LibraryBackend` in `paperful/library.py`. Default tests stay offline.

**Mirror first.** Paperful copies the user's files and metadata into `out/`
and `state/` and works from that copy. The manager API is for refreshing the
mirror and for explicit write-back, nothing else. Before adding a call to
Zotero, read the [developer guide](docs/developer.md): a read verb must not
need the manager running, a write must leave `record.json` true, and a
failed read is never "nothing there". Tests enforce all three.
