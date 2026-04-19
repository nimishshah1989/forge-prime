"""Allowed tool whitelist for forge-runner inner sessions (FR-005..FR-008).

The inner Claude Code session is restricted to this fixed list.  The runner
passes it verbatim as the `allowed_tools` argument to `claude_agent_sdk.query`
and NEVER computes it from config at runtime.

References: specs/003-forge-runner/contracts/cli.md, plan.md §Project Structure.
"""

from __future__ import annotations

# Frozen tuple — immutable at module load time.
# Includes standard Claude Code tools needed for chunk implementation.
# Excludes destructive shell operations that bypass forge-ship.sh
# (e.g. raw git commit is blocked by the PreToolUse hook anyway).
ALLOWED_TOOLS: tuple[str, ...] = (
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Grep",
    "Glob",
    "TodoWrite",
    "WebFetch",
    "Agent",
)


def load_bearing() -> list[str]:
    """Return the allowed-tools list as a mutable list (SDK expects list[str]).

    Callers MUST NOT modify the returned list — create a copy if needed.
    """
    return list(ALLOWED_TOOLS)
