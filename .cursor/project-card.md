# Project card — scihub-dl

Single place to edit instantiate values. Slash commands still need the values inlined
(Cursor injects only the command file). Re-run `/instantiate` from `cursor_commands`
(or hand-sync) after changing this card.

```yaml
project: scihub-dl
package: scihub_dl
src_package: scihub_dl
ui_kind: none
ui_port: n/a
ui_entry: n/a
sibling_ports: none
small_fixture: tests/fixtures/scihub_found.html
large_fixture_hint: a small Zotero collection the user names for --dry-run, or the full HTML fixture set under tests/fixtures/
default_test_cmd: uv run pytest -q
coverage_cmd: uv run pytest --cov=scihub_dl --cov-report=term-missing -q
architecture_rules:
  - CLI orchestrates only (no download/resolve logic in cli.py)
  - source adapters under sources/ must not write the manifest or out_dir
  - open-access sources before Sci-Hub; Sci-Hub stays serial
  - default tests stay offline (fixture HTML / mocks — no live Zotero or network)
release_governance: none
backup_hub: sibling
backup_excludes:
  - out
  - state
backup_includes:
  - scihub_dl/***
verify_paths:
  - scihub_dl
  - tests
  - pyproject.toml
  - README.md
  - .cursor/commands
staging_prefix: scihub-dl-backup
high_leverage_tests: Sci-Hub HTML parse and captcha/not-found classification; resolve/Crossref title scoring; store/manifest resume semantics; Zotero local API attach stubs; pipeline source order
probe_small: uv run pytest tests/test_scihub.py tests/test_resolve.py -q (offline fixture HTML)
probe_large: uv run scihub-dl run --collection <user-named small collection> --dry-run (requires Zotero local API); if unavailable → skipped
probe_extra: uv run scihub-dl mirrors (network); optionally collections; never touch sibling ports
doc_contracts: README.md only (light parity pass; do not invent a CONTRACT tree)
```

Skipped on instantiate (no surface): `streamlit.md`, `rebuild.md`, `dockerfile-efficiency.md`.
