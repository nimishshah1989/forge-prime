#!/usr/bin/env bash
# post-chunk.sh — forge-prime post-chunk sync hook (project stub).
#
# Called by scripts/forge-ship.sh after a chunk passes all gates.
# Customize the steps below for your project's deploy/restart needs.
#
# Usage: scripts/post-chunk.sh <chunk-id>
#
# Exit non-zero to block the next chunk from starting.

set -euo pipefail

CHUNK_ID="${1:?chunk id required}"
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"
cd "$REPO_ROOT"

log() { echo "[post-chunk:${CHUNK_ID}] $*"; }

# --- 1. Push any residual tracked changes --------------------------------
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "residual changes — committing"
  git add -u
  git commit -m "forge: ${CHUNK_ID} — post-chunk residual sync" || true
fi
if [ "$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)" -gt 0 ]; then
  log "pushing to origin"
  git push origin HEAD
else
  log "origin in sync"
fi

# --- 2. Restart services (customize for your project) -------------------
# Example: uncomment and adapt as needed
# if systemctl list-unit-files 2>/dev/null | grep -q '^YOUR-backend\.service'; then
#   log "restarting YOUR-backend.service"
#   sudo systemctl restart YOUR-backend.service
# fi

# --- 3. Smoke probe (optional) ------------------------------------------
if [ -x "$REPO_ROOT/scripts/smoke-probe.sh" ]; then
  log "running smoke probe"
  if ! REPO_ROOT="$REPO_ROOT" "$REPO_ROOT/scripts/smoke-probe.sh"; then
    log "smoke probe failed — blocking next chunk"
    exit 1
  fi
else
  log "no smoke probe — skipping"
fi

# --- 4. Context sync (wiki + memory) ------------------------------------
if command -v claude >/dev/null 2>&1; then
  log "spawning headless context sync"
  COMPILE_LOG="orchestrator/logs/${CHUNK_ID}_context_sync.log"
  mkdir -p "$(dirname "$COMPILE_LOG")"
  nohup claude -p "Run /forge-compile for chunk ${CHUNK_ID}. Do not modify project source code." \
    --dangerously-skip-permissions \
    >"$COMPILE_LOG" 2>&1 &
  disown
  log "context sync spawned (log: $COMPILE_LOG)"
else
  log "claude cli not found — skipping context sync"
fi

log "done"
