# Contributing to Paperful

## Setup

```sh
git clone https://github.com/glen-w/Paperful.git
cd Paperful
uv sync --group dev
cp config.example.toml config.toml   # personal — never commit config.toml
```

Zotero must be running with the local API enabled for integration tests that touch the CLI; most tests use stubs and run offline.

## Tests

```sh
uv run pytest
```

CI runs the same suite on every push and pull request (see `.github/workflows/ci.yml`).

## Pull requests

- Keep changes focused; match existing style in `paperful/`.
- Add or update tests for behaviour changes.
- Do not commit personal `config.toml`, `state/`, `out/`, or cookie files.

## Architecture

See [docs/architecture.md](docs/architecture.md) for how the pipeline fits together.
