"""Dead-man switch: startup orphan scan (T041, FR-022..FR-024).

Scans orchestrator state for IN_PROGRESS rows on startup and determines
whether the new runner instance should proceed, auto-reset orphaned rows,
or exit because another runner already owns a live chunk.

Public API:
    DeadmanResult   — dataclass describing the outcome of a scan
    scan_on_startup(ctx) -> DeadmanResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DeadmanResult:
    """Outcome of a startup dead-man scan.

    action values:
        "clean"           — no IN_PROGRESS rows (or all cleared)
        "auto_reset"      — one or more orphaned rows were reset to PENDING
        "owned_by_other"  — a live forge_runner process owns a row (exit 6)
        "strict_halt"     — orphan found but --strict-dead-man is set (exit 5)
    """

    action: Literal["clean", "auto_reset", "owned_by_other", "strict_halt"]
    details: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# /proc helpers
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* is currently alive.

    Uses /proc/<pid>/status existence as the liveness probe (Linux-native).
    Returns False if pid is None-like, non-positive, or /proc is unavailable.
    """
    if not pid or pid <= 0:
        return False
    try:
        from pathlib import Path

        return (Path("/proc") / str(pid) / "status").exists()
    except OSError:
        return False


def _is_forge_runner(pid: int) -> bool:
    """Return True if /proc/<pid>/cmdline contains a forge_runner token.

    cmdline is a null-byte-delimited string of argv.  We check each token
    for the substrings ``forge_runner`` or ``forge-runner``.

    Returns False on any read error (permission, race, pid disappeared).
    """
    try:
        from pathlib import Path

        cmdline_path = Path("/proc") / str(pid) / "cmdline"
        raw = cmdline_path.read_bytes()
        # null-terminated and null-separated args
        tokens = raw.rstrip(b"\x00").split(b"\x00")
        for tok in tokens:
            decoded = tok.decode("utf-8", errors="replace")
            if "forge_runner" in decoded or "forge-runner" in decoded:
                return True
        return False
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------


def scan_on_startup(ctx: Any) -> DeadmanResult:
    """Scan orchestrator state for IN_PROGRESS rows before picking any chunk.

    For each IN_PROGRESS row:
      - pid alive AND is forge_runner  → owned_by_other (exit 6)
      - pid alive but NOT forge_runner → orphan (pid reused); auto-reset
      - pid dead OR pid None           → orphan; auto-reset unless strict mode

    Returns the *first* non-clean action encountered.  If all rows were
    handled (or there were none), returns a "clean" or "auto_reset" result.

    Args:
        ctx: RunContext-like with ``.state_db_path`` (str) and
             ``.config.strict_dead_man`` (bool).
    """
    from .state import list_in_progress, reset_to_pending

    in_progress = list_in_progress(ctx.state_db_path)

    if not in_progress:
        return DeadmanResult(action="clean", message="no IN_PROGRESS rows found")

    any_reset = False
    details: list[dict[str, Any]] = []

    for row in in_progress:
        pid: int | None = row.runner_pid
        chunk_id: str = row.id

        detail: dict[str, Any] = {"chunk_id": chunk_id, "runner_pid": pid}

        if pid is not None and _pid_alive(pid):
            if _is_forge_runner(pid):
                # Another live runner owns this row — do not interfere
                detail["outcome"] = "owned_by_other"
                details.append(detail)
                logger.warning(
                    "deadman_owned_by_other",
                    chunk_id=chunk_id,
                    runner_pid=pid,
                )
                return DeadmanResult(
                    action="owned_by_other",
                    details=details,
                    message=(f"chunk {chunk_id!r} is owned by live forge_runner pid {pid}"),
                )
            # Pid alive but not a forge_runner — pid was reused by another process
            logger.warning(
                "deadman_pid_reused_orphan",
                chunk_id=chunk_id,
                old_pid=pid,
                note="pid is alive but belongs to a non-forge-runner process",
            )
            detail["outcome"] = "orphan_pid_reused"
        else:
            # Pid dead or None — genuine orphan
            logger.warning(
                "deadman_orphan_detected",
                chunk_id=chunk_id,
                runner_pid=pid,
                pid_alive=False,
            )
            detail["outcome"] = "orphan_dead_pid"

        # Orphan handling
        strict = getattr(getattr(ctx, "config", None), "strict_dead_man", False)
        if strict:
            detail["action_taken"] = "strict_halt"
            details.append(detail)
            return DeadmanResult(
                action="strict_halt",
                details=details,
                message=(
                    f"orphaned IN_PROGRESS row for {chunk_id!r} (pid={pid}) — "
                    "strict-dead-man mode: halting instead of auto-reset"
                ),
            )

        # Auto-reset
        reset_to_pending(chunk_id, ctx.state_db_path)
        detail["action_taken"] = "reset_to_pending"
        details.append(detail)
        any_reset = True
        logger.warning(
            "deadman_auto_reset",
            chunk_id=chunk_id,
            old_pid=pid,
        )

    if any_reset:
        return DeadmanResult(
            action="auto_reset",
            details=details,
            message=f"auto-reset {len(details)} orphaned IN_PROGRESS row(s) to PENDING",
        )

    return DeadmanResult(action="clean", message="all IN_PROGRESS rows verified clean")
