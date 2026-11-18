#!/usr/bin/env bash
# Read since dogfood gate state from docs/dogfood/since-bbnj.md
#
# Prints one line:
#   complete
#   skipped (ci|env)
#   active COUNT/NEED tracker=REL_PATH
#
# Exit 0 when tagging is allowed (complete, enough verdicts, skip).
# Exit 1 when dogfood_gate is active and verdicts are short.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${PAPERFUL_RELEASE_ROOT:-$ROOT}"
TRACKER_REL="docs/dogfood/since-bbnj.md"
TRACKER="$WORK/$TRACKER_REL"
PRINT_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --print-only) PRINT_ONLY=1; shift ;;
    *) shift ;;
  esac
done

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  echo "skipped (ci)"
  exit 0
fi
if [[ "${PAPERFUL_SKIP_DOGFOOD:-}" == "1" ]]; then
  echo "skipped (env)"
  exit 0
fi
if [[ ! -f "$TRACKER" ]]; then
  echo "missing tracker=$TRACKER_REL"
  exit 1
fi
if grep -q '^dogfood_gate:[[:space:]]*complete' "$TRACKER"; then
  echo "complete"
  exit 0
fi

need=4
if grep -q '^target_verdicts:' "$TRACKER"; then
  need="$(grep '^target_verdicts:' "$TRACKER" | awk '{print $2}')"
fi
count=0
line= verdict=
while IFS= read -r line; do
  if [[ "$line" =~ ^\|[[:space:]]*[1-4][[:space:]]*\| ]]; then
      verdict="$(awk -F'|' '{gsub(/^ +| +$/,"",$8); print $8}' <<<"$line")"
    case "$verdict" in
      actionable|dismissed|noise) count=$((count + 1)) ;;
    esac
  fi
done <"$TRACKER"

echo "active $count/$need tracker=$TRACKER_REL"
if [[ "$count" -lt "$need" ]]; then
  exit 1
fi
exit 0