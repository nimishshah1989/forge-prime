#!/usr/bin/env bash
# Verifies clean tree and pushed state
set -euo pipefail
REPO="${1:-$(git rev-parse --show-toplevel)}"

if ! git -C "$REPO" status --porcelain | grep -q ''; then
  echo "[git-sync] FAIL: uncommitted changes"
  exit 1
fi

if git -C "$REPO" log origin/main..HEAD --oneline | grep -q '.'; then
  echo "[git-sync] FAIL: unpushed commits"
  exit 1
fi

echo "[git-sync] OK: clean and pushed"
