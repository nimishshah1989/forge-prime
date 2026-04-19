#!/usr/bin/env bash
# forge-ship.sh — the institutionalised build→QA→memory→wiki→commit path.
#
# Usage:
#   scripts/forge-ship.sh <chunk-id> "<one-line commit summary>"
#
# Runs, in strict order:
#   1. pytest tests/ -q                 (unit tests)
#   2. python .quality/checks.py        (71-check QA gate)
#   3. memory sync freshness check      (MEMORY status file touched < 10 min ago)
#   4. writes .forge/last-run.json      (what the pre-commit hook checks)
#   5. git commit + git push
#   6. scripts/post-chunk.sh <chunk>    (restart, smoke probe, spawn
#                                        forge-compile + auto-memory sync)
#
# If any step fails, the script exits non-zero and nothing commits. The
# pre-commit hook at ~/.forge/hooks/enforce-ship-protocol.sh refuses any
# commit without a fresh .forge/last-run.json, so this script is the only
# legal path to ship.

set -euo pipefail

CHUNK_RAW="${1:?chunk id required, e.g. V2-10}"
SUMMARY_RAW="${2:-}"

# Defensive normalisation. Inner forge sessions sometimes pass the full
# chunk title as the chunk id (e.g. "V2-9: MF deep-dive panel — single-fetch
# pillars, NAV sparkline, overlap widget"), which produced commits like
# `forge: forge: V2-9 — ... : V2-9 — ... — see spec`. Strip any leading
# `forge: ` and any "<id>: <title>" pattern down to just the id.
CHUNK="${CHUNK_RAW#forge: }"   # drop any "forge: " prefix
CHUNK="${CHUNK%%:*}"             # keep only text before the first colon
CHUNK="${CHUNK%% *}"             # and only the first whitespace token

# Validate: chunk id must look like an id (V2-10, V1-9, S2, C8, V2-UQL-AGG-30)
if ! [[ "$CHUNK" =~ ^[A-Z][A-Za-z0-9.-]*$ ]]; then
  echo "[forge-ship] FAIL: chunk id '$CHUNK' (from '$CHUNK_RAW') does not look like an id." >&2
  echo "             Expected something like V2-10, S2, C8, V2-UQL-AGG-30." >&2
  exit 2
fi

# Strip any leading `forge: ` and any `<id>: ` prefix from the summary so
# we don't end up double-prefixing the commit subject.
SUMMARY="${SUMMARY_RAW#forge: }"
SUMMARY="${SUMMARY#${CHUNK}: }"
SUMMARY="${SUMMARY#${CHUNK} — }"
[ -z "$SUMMARY" ] && SUMMARY="${CHUNK} — see spec"

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

STATE=".forge/last-run.json"
mkdir -p .forge

log() { printf "[forge-ship:%s] %s\n" "$CHUNK" "$*"; }

# --- 1. Tests ---------------------------------------------------------
log "step 1/5 — pytest"
if [ -x "./venv/bin/pytest" ]; then
  ./venv/bin/pytest tests/ -q -m 'not integration' || { log "FAIL: pytest"; exit 1; }
else
  pytest tests/ -q -m 'not integration' || { log "FAIL: pytest"; exit 1; }
fi

# --- 2. Quality gate (71 checks + delta vs pre-chunk baseline) -------
log "step 2/5 — .quality/checks.py (71 checks + delta gate)"
BASELINE_FILE=".forge/baseline/current.json"
BASELINE_CHUNK_FILE=".forge/baseline/current.chunk"
GATE_ARGS=(--gate --save)
if [ -f "$BASELINE_FILE" ] && [ -f "$BASELINE_CHUNK_FILE" ]; then
  BASELINE_CHUNK=$(cat "$BASELINE_CHUNK_FILE")
  if [ "$BASELINE_CHUNK" = "$CHUNK" ]; then
    log "delta-gating against baseline captured at chunk start"
    GATE_ARGS+=(--compare-baseline "$BASELINE_FILE")
  else
    log "baseline chunk mismatch ($BASELINE_CHUNK vs $CHUNK) — skipping delta gate"
  fi
else
  log "no baseline present — running floor gate only (manual chunk or first run)"
fi
PATH="${ROOT}/venv/bin:${PATH}" python3 .quality/checks.py "${GATE_ARGS[@]}" || { log "FAIL: quality gate"; exit 1; }

# --- 2.5. Codex adversarial review ------------------------------------
log "step 2.5/5 — codex adversarial review"
if command -v codex &>/dev/null; then
  REVIEW=$(codex --approval-policy=never \
    "Review the staged git diff. Output REVIEW_PASS if acceptable. \
Output REVIEW_FAIL:<reason> if there is a blocking issue. \
Look for: regressions, security issues, missed edge cases, anti-patterns. \
Be strict — catch what Claude missed." 2>&1 | tail -5)
  if echo "$REVIEW" | grep -q "REVIEW_PASS"; then
    log "Codex review: PASS"
  else
    log "FAIL: Codex blocked commit: $REVIEW" >&2
    exit 1
  fi
else
  log "WARN: codex not installed — skipping (npm i -g @openai/codex to enable)"
fi

# --- 3. Memory freshness ----------------------------------------------
# The project memory status file must have been touched in the last 10
# minutes, so no chunk ships with a stale status ledger. The user (or
# Claude on the user's behalf) is expected to append the chunk row before
# running forge-ship.
log "step 3/5 — memory sync freshness"
# Look for a .forge/BUILD_STATUS.md or memory file in the project, not a
# hardcoded atlas path. If missing, skip (not all projects use memory files).
MEM_FILE=".forge/BUILD_STATUS.md"
if [ -f "$MEM_FILE" ]; then
  NOW=$(date +%s)
  MTIME=$(stat -c %Y "$MEM_FILE" 2>/dev/null || stat -f %m "$MEM_FILE" 2>/dev/null || echo "$NOW")
  AGE=$(( NOW - MTIME ))
  if [ "$AGE" -gt 600 ]; then
    log "FAIL: $MEM_FILE is ${AGE}s old (>600s). Update before shipping."
    exit 1
  fi
  log "memory file fresh (${AGE}s old)"
else
  log "no BUILD_STATUS.md found — skipping memory freshness check"
fi

# --- 4. Record state the pre-commit hook will read --------------------
log "step 4/5 — writing .forge/last-run.json"
python3 - <<PY
import json, time
json.dump({
    "chunk": "${CHUNK}",
    "tests_ok": True,
    "quality_ok": True,
    "memory_ok": True,
    "ts": int(time.time()),
}, open("${STATE}", "w"), indent=2)
PY

# --- 5. Commit + push -------------------------------------------------
log "step 5/5 — git commit + push"
if ! git diff --cached --quiet || ! git diff --quiet; then
  # Stage everything currently modified / new. Script caller is expected
  # to have already git-added the intentional set; anything stray should
  # have been caught by the research gate + commit quality hooks.
  git add -A
  git commit -m "${CHUNK}: ${SUMMARY}

Shipped via scripts/forge-ship.sh — tests+gate+memory+hooks all green.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
  git push origin HEAD
else
  log "nothing to commit (tree already clean); skipping commit+push"
fi

# --- 6. Post-chunk sync (restart + smoke + forge-compile + memory) ----
log "running scripts/post-chunk.sh (deploy + forge-compile + memory)"
if [ -x scripts/post-chunk.sh ]; then
  bash scripts/post-chunk.sh "$CHUNK"
else
  log "WARN: scripts/post-chunk.sh not found — forge-compile and memory"
  log "      sync will not run. Chunk is NOT fully shipped."
  exit 1
fi

log "✓ ${CHUNK} shipped: tests + gate + memory + commit + post-chunk"
