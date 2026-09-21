# Project card — paperful

Single place to edit instantiate values. Slash commands still need the values inlined
(Cursor injects only the command file). Re-run `/instantiate` from `cursor_commands`
(or hand-sync) after changing this card.

```yaml
project: paperful
package: paperful
src_package: paperful
ui_kind: none
ui_port: n/a
ui_entry: n/a
sibling_ports: none
small_fixture: tests/fixtures/scihub_found.html
large_fixture_hint: a small Zotero collection the user names for --dry-run, or the full HTML fixture set under tests/fixtures/
default_test_cmd: uv run pytest -q
coverage_cmd: uv run pytest --cov=paperful --cov-report=term-missing -q
docker_build_cmd: docker compose build
docker_smoke_cmd: docker compose run --rm paperful doctor
docker_operator_cmd: docker compose run --rm paperful
preferred_deploy: Docker Compose build-local (docs/docker.md); uv is the contributor path
architecture_rules:
  - CLI orchestrates only (no download/resolve logic in cli.py)
  - source adapters under sources/ must not write the manifest or out_dir
  - open-access sources before Sci-Hub; Sci-Hub stays serial
  - default tests stay offline (fixture HTML / mocks — no live Zotero or network)
  - Docker Compose build is the operator path (build-local only; no docker pull, no PyPI); uv is the contributor path; host Zotero + headed session login stay outside; durable data via PAPERFUL_DATA when using Compose
release_governance: none
backup_hub: "$HOME/Documents/code backups"
backup_excludes:
  - out
  - state
  - packs
backup_includes:
  - paperful/***
verify_paths:
  - paperful
  - tests
  - pyproject.toml
  - README.md
  - Dockerfile
  - compose.yaml
  - .env.example
  - .cursor/commands
staging_prefix: paperful-backup
high_leverage_tests: Sci-Hub HTML parse and captcha/not-found classification; resolve/Crossref title scoring; store/manifest resume semantics; Zotero local API attach stubs (incl. PAPERFUL_ZOTERO_HOST Host header); pipeline source order; routing lanes and circuit breaker; Scholar/EZProxy cookie session probes; grey_playbooks_dir pack merge
probe_small: uv run pytest tests/test_scihub.py tests/test_resolve.py tests/test_zot_local.py tests/test_playbooks.py -q (offline fixture HTML + Docker-related unit tests)
probe_large: uv run paperful run --collection <user-named small collection> --dry-run (requires Zotero); optional docker compose run --rm paperful run --collection <…> --dry-run; if Zotero unavailable → skipped
probe_extra: uv run paperful doctor; optionally uv run paperful mirrors / collections; docker compose equivalents are optional; never touch sibling ports
doc_contracts: README.md and docs/docker.md (build-local Compose is the operator install; uv is Develop)
```

Skipped on instantiate (no surface): `streamlit.md`, `rebuild.md`.
Docker surface exists — keep `dockerfile-efficiency.md` when instantiating from the hub.
