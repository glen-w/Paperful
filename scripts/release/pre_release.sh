#!/usr/bin/env bash
# Maintainer gate before tagging or publishing. Run from repo root.
#   bash scripts/release/pre_release.sh           # version + changelog + clean dist/
#   bash scripts/release/pre_release.sh --dist-only   # after uv build (CI / manual publish)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${PAPERFUL_RELEASE_ROOT:-$ROOT}"
cd "$WORK"

DIST_ONLY=0
if [[ "${1:-}" == "--dist-only" ]]; then
  DIST_ONLY=1
fi

read_version() {
  python3 - <<'PY'
import tomllib
from pathlib import Path
print(tomllib.load(Path("pyproject.toml").open("rb"))["project"]["version"])
PY
}

VERSION="$(read_version)"
errors=0

note() { echo "$*"; }
fail() { echo "error: $*" >&2; errors=1; }

artifact_version() {
  local base="${1##*/}"
  if [[ "$base" =~ ^paperful-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

check_dist_artifacts() {
  local -a files=()
  shopt -s nullglob
  files=(dist/paperful-*.whl dist/paperful-*.tar.gz)
  shopt -u nullglob

  if [[ ${#files[@]} -eq 0 ]]; then
    fail "dist/ has no paperful-*.whl or paperful-*.tar.gz (run: uv build)"
    return
  fi

  local -A seen=()
  local f ver
  for f in "${files[@]}"; do
    if ! ver="$(artifact_version "$f")"; then
      fail "unrecognized artifact name: $f"
      continue
    fi
    seen["$ver"]=1
    if [[ "$ver" != "$VERSION" ]]; then
      fail "stale dist artifact for $ver (pyproject.toml is $VERSION): $f"
    fi
  done

  if [[ ${#seen[@]} -gt 1 ]]; then
    fail "dist/ mixes multiple versions: ${!seen[*]} — remove extras (e.g. rm dist/paperful-<old>* )"
  fi

  local want_wheel="dist/paperful-${VERSION}-py3-none-any.whl"
  local want_sdist="dist/paperful-${VERSION}.tar.gz"
  if [[ ! -f "$want_wheel" ]]; then
    fail "missing wheel: $want_wheel"
  fi
  if [[ ! -f "$want_sdist" ]]; then
    fail "missing sdist: $want_sdist"
  fi
}

if [[ "$DIST_ONLY" -eq 1 ]]; then
  note "Pre-release dist check (version $VERSION)"
  check_dist_artifacts
  if [[ "$errors" -ne 0 ]]; then
    note ""
    note "uv publish uploads every file in dist/ by default. Publish only this release:"
    note "  rm -f dist/paperful-[0-9]*"
    note "  uv build"
    note "  UV_PUBLISH_TOKEN=… uv publish dist/paperful-${VERSION}*"
    exit 1
  fi
  note "OK: dist/ contains only paperful-${VERSION} wheel + sdist"
  exit 0
fi

note "Pre-release checks (version $VERSION)"

if ! grep -q "^## ${VERSION}" CHANGELOG.md; then
  fail "CHANGELOG.md has no section: ## ${VERSION}"
fi

if [[ -f website/index.html ]]; then
  if ! grep -q "\"softwareVersion\": \"${VERSION}\"" website/index.html; then
    fail "website/index.html softwareVersion does not match ${VERSION}"
  fi
  if ! grep -q "· ${VERSION}</p>" website/index.html; then
    fail "website/index.html footer version does not match ${VERSION}"
  fi
fi

if [[ -f website/cleaning-service.html ]]; then
  if ! grep -q "· ${VERSION} ·" website/cleaning-service.html; then
    fail "website/cleaning-service.html footer version does not match ${VERSION}"
  fi
fi

# Stale local builds should not ride along on uv publish.
shopt -s nullglob
stale=(dist/paperful-*.whl dist/paperful-*.tar.gz)
shopt -u nullglob
if [[ ${#stale[@]} -gt 0 ]]; then
  check_dist_artifacts
else
  note "dist/: empty (run uv build before publish)"
fi

if [[ "$errors" -ne 0 ]]; then
  exit 1
fi

note "OK: pre-release checks passed"
