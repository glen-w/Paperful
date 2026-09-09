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
  - paperful/***
verify_paths:
  - paperful
  - tests
  - pyproject.toml
  - README.md
  - .cursor/commands
staging_prefix: paperful-backup
high_leverage_tests: Sci-Hub HTML parse and captcha/not-found classification; resolve/Crossref title scoring; store/manifest resume semantics; Zotero local API attach stubs; pipeline source order; routing lanes and circuit breaker; Scholar/EZProxy cookie session probes
probe_small: uv run pytest tests/test_scihub.py tests/test_resolve.py -q (offline fixture HTML)
probe_large: uv run paperful run --collection <user-named small collection> --dry-run (requires Zotero local API); if unavailable → skipped
probe_extra: uv run paperful mirrors (network); optionally collections; never touch sibling ports
doc_contracts: README.md only (light parity pass; do not invent a CONTRACT tree)
```

Skipped on instantiate (no surface): `streamlit.md`, `rebuild.md`, `dockerfile-efficiency.md`.
