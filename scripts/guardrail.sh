#!/bin/bash
# guardrail.sh — blocks dangerous commands, rate-limits repeated tool calls.
#
# Runs as a PreToolUse hook on the Bash tool. Reads the JSON hook envelope on
# stdin, extracts .tool_input.command, decides:
#   - exit 0 → allow
#   - exit 2 → block (Claude sees stderr as the reason)
#
# Safeguards:
#   1. Hard-block a short list of genuinely destructive patterns (rm -rf /,
#      curl | sh, drop database, mkfs, fork bomb, etc).
#   2. Rate-limit identical commands — if the same command fires 20+ times
#      inside 60 seconds, pause the shell briefly so a runaway loop can't
#      exhaust an API budget before anyone notices.
#
# Installed by install.sh to ~/.forge/prime/hooks/guardrail.sh.

set -u

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

# If the hook envelope is malformed (no jq, no command), don't block.
if [ -z "$CMD" ]; then
    exit 0
fi

# --- Hard blocks: genuinely dangerous commands ---
DANGEROUS_PATTERNS=(
    'rm -rf /'
    'rm -rf /\*'
    'rm -rf ~'
    'rm -rf \$HOME'
    'sudo rm -rf'
    'drop database'
    'DROP DATABASE'
    'chmod -R 777 /'
    '\| *sh *$'
    '\| *bash *$'
    'curl .* \| *sh'
    'curl .* \| *bash'
    'wget .* \| *sh'
    'wget .* \| *bash'
    '> /dev/sd[a-z]'
    'mkfs\.'
    ':\(\)\{ *:\|:&'
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
    if echo "$CMD" | grep -qE "$pattern"; then
        echo "GUARDRAIL BLOCKED: command matches dangerous pattern: $pattern" >&2
        echo "Command: $CMD" >&2
        echo "If this is intentional, run it manually outside of forge." >&2
        exit 2
    fi
done

# --- Rate limiting on repeated commands within a session ---
RATE_DIR="${TMPDIR:-/tmp}/forge-guardrail-$$"
mkdir -p "$RATE_DIR" 2>/dev/null || true
if [ -d "$RATE_DIR" ]; then
    CMD_HASH=$(echo "$CMD" | md5sum 2>/dev/null | cut -d' ' -f1)
    if [ -n "$CMD_HASH" ]; then
        COUNT_FILE="$RATE_DIR/$CMD_HASH"
        NOW=$(date +%s)
        THRESHOLD_FILE="$RATE_DIR/.window"
        # Reset the window marker every 60s so we only count recent activity.
        if [ ! -f "$THRESHOLD_FILE" ] || \
           [ $(( NOW - $(stat -c %Y "$THRESHOLD_FILE" 2>/dev/null || \
                        stat -f %m "$THRESHOLD_FILE" 2>/dev/null || \
                        echo "$NOW") )) -gt 60 ]; then
            : > "$THRESHOLD_FILE"
            # Clear previous counters when the window rolls over.
            find "$RATE_DIR" -type f ! -name '.window' -delete 2>/dev/null || true
        fi
        echo "$NOW" >> "$COUNT_FILE"
        RECENT=$(wc -l < "$COUNT_FILE" 2>/dev/null || echo 0)
        if [ "${RECENT:-0}" -gt 20 ]; then
            echo "GUARDRAIL WARNING: 20+ repeats of the same command in 60s — pausing 5s" >&2
            sleep 5
        fi
    fi
fi

exit 0
