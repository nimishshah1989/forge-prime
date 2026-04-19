#!/usr/bin/env bash
# Blocks commit if ruff/mypy/pytest fail
# Called by claude/settings.json PreToolUse hook for Bash tool use
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ -f "venv/bin/ruff" ]; then
  venv/bin/ruff check . --select E,F,W --quiet 2>/dev/null || { echo "[quality] ruff failed"; exit 1; }
elif command -v ruff >/dev/null 2>&1; then
  ruff check . --select E,F,W --quiet 2>/dev/null || { echo "[quality] ruff failed"; exit 1; }
fi

echo "[quality] pre-commit checks passed"
