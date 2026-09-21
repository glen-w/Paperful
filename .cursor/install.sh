#!/usr/bin/env bash
# Cloud Agent bootstrap for paperful (host-local Zotero CLI).
# Idempotent: safe to re-run against a warm or partially prepared machine.
set -euo pipefail

# Poppler provides pdftotext for PDF-text DOI extraction (doctor ambers without it).
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends poppler-utils

# uv drives the whole project (see README / CONTRIBUTING); installer is re-run safe.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# Project deps plus the dev group (pytest) from the committed uv.lock.
uv sync --group dev

# Chromium + OS libraries for the htmlpdf source and browser session vault.
uv run playwright install --with-deps chromium

# Seed a local config.toml so `paperful doctor` and the CLI work out of the box.
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
fi
mkdir -p out state packs
