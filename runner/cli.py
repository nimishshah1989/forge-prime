"""forge-runner CLI entry point (T027, T040, T042).

Replaces the Phase 2 stub.  Implements:
  - parse_args → RunContext construction
  - Precondition checks (.forge/CONDUCTOR.md, state.db, git toplevel)
  - Dead-man scan via deadman.scan_on_startup (T041/T042)
  - SIGTERM/SIGINT signal handlers via asyncio loop (T042)
  - --dry-run: LocalPickStage.dry_run() + exit
  - --retry <id>: reset_to_pending + archive failure record + single iteration
  - normal mode: asyncio.run(loop.run_loop(ctx))
  - Uncaught exception: write_crash_record + reset_to_pending + exit 4

Public API:
    main(argv=None) -> int
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import structlog

from ._time import now_ist, to_iso
from .config import RunConfig, parse_args
from .stages import RunContext, StageResult

logger = structlog.get_logger(__name__)

# Exit codes per contracts/cli.md
_EXIT_SUCCESS = 0
_EXIT_AUTH_FAILURE = 1
_EXIT_STALLED = 2
_EXIT_CHUNK_FAILED = 3
_EXIT_CRASH = 4
_EXIT_DEAD_MAN = 5
_EXIT_CONCURRENT = 6
_EXIT_PRECONDITION = 7


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for forge-runner.

    Returns an integer exit code; callers (or __main__.py) should call
    sys.exit() with this value.
    """
    config = parse_args(argv)

    # Configure structlog level
    import logging

    level = logging.DEBUG if config.verbose else logging.INFO
    logging.basicConfig(level=level, stream=sys.stderr)

    # ------------------------------------------------------------------ #
    # Resolve paths                                                        #
    # ------------------------------------------------------------------ #
    repo = Path(config.repo).resolve()
    log_dir_raw = config.log_dir
    if not Path(log_dir_raw).is_absolute():
        log_dir = repo / log_dir_raw
    else:
        log_dir = Path(log_dir_raw)
    log_dir.mkdir(parents=True, exist_ok=True)

    state_db_path = str(repo / "orchestrator" / "state.db")

    # ------------------------------------------------------------------ #
    # Precondition checks                                                  #
    # ------------------------------------------------------------------ #
    conductor_path = repo / ".forge" / "CONDUCTOR.md"
    if not conductor_path.exists():
        logger.error(
            "precondition_failed",
            reason="CONDUCTOR.md not found",
            path=str(conductor_path),
        )
        print(  # noqa: T201 — CLI stderr output, not production logging
            f"ERROR: {conductor_path} not found. "
            "Create .forge/CONDUCTOR.md (see docs/architecture/forge-runner.md).",
            file=sys.stderr,
        )
        return _EXIT_PRECONDITION

    if not Path(state_db_path).exists():
        logger.error(
            "precondition_failed",
            reason="state.db not found",
            path=state_db_path,
        )
        print(f"ERROR: {state_db_path} not found.", file=sys.stderr)  # noqa: T201 — CLI stderr
        return _EXIT_PRECONDITION

    # Verify git toplevel resolves
    try:
        git_result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if git_result.returncode != 0:
            raise RuntimeError(git_result.stderr.strip())
    except Exception as exc:
        logger.error("precondition_failed", reason="git toplevel failed", error=str(exc))
        print(f"ERROR: Not a git repo at {repo}: {exc}", file=sys.stderr)  # noqa: T201 — CLI stderr
        return _EXIT_PRECONDITION

    # ------------------------------------------------------------------ #
    # Build RunContext                                                     #
    # ------------------------------------------------------------------ #
    ctx = RunContext(
        config=config,
        repo=repo,
        log_dir=log_dir,
        state_db_path=state_db_path,
        cancellation=asyncio.Event(),
        current_chunk=None,
        session_started_at=None,
        timeout_sec=config.timeout_sec,
        max_turns=config.max_turns,
        runner_pid=os.getpid(),
        loop_started_at=now_ist(),
        chunks_completed=0,
        chunks_failed=0,
        filter_regex=config.filter_regex,
    )

    # ------------------------------------------------------------------ #
    # Dead-man scan (T041 / FR-022..FR-024)                               #
    # ------------------------------------------------------------------ #
    from .deadman import scan_on_startup

    dm_result = scan_on_startup(ctx)
    if dm_result.action == "owned_by_other":
        logger.error(
            "deadman_concurrent_runner",
            message=dm_result.message,
        )
        print(f"ERROR: {dm_result.message}", file=sys.stderr)  # noqa: T201 — CLI stderr
        return _EXIT_CONCURRENT
    if dm_result.action == "strict_halt":
        logger.error(
            "deadman_strict_halt",
            message=dm_result.message,
        )
        print(f"ERROR: {dm_result.message}", file=sys.stderr)  # noqa: T201 — CLI stderr
        return _EXIT_DEAD_MAN

    # ------------------------------------------------------------------ #
    # Branch: --dry-run                                                   #
    # ------------------------------------------------------------------ #
    if config.dry_run:
        return _run_dry_run(ctx)

    # ------------------------------------------------------------------ #
    # Branch: --retry <id>                                                #
    # ------------------------------------------------------------------ #
    if config.retry:
        return _run_retry(config.retry, ctx)

    # ------------------------------------------------------------------ #
    # Normal loop (with signal handlers, T042 / FR-025)                  #
    # ------------------------------------------------------------------ #
    try:
        from .loop import run_loop

        return asyncio.run(_run_loop_with_signals(ctx, run_loop))
    except KeyboardInterrupt:
        logger.info("runner_keyboard_interrupt")
        _reset_current_chunk_if_any(ctx)
        return _EXIT_SUCCESS
    except BaseException:
        # Catches all unexpected exceptions (RuntimeError, SystemError, etc.)
        # at the runner boundary; crash record written in _handle_crash.
        return _handle_crash(ctx)


# ---------------------------------------------------------------------------
# --dry-run path
# ---------------------------------------------------------------------------


def _run_dry_run(ctx: RunContext) -> int:
    """Run LocalPickStage.dry_run and print result. No state mutation."""
    from .stages import LocalPickStage

    stage = LocalPickStage()

    async def _do() -> StageResult:
        return await stage.dry_run(ctx)

    result = asyncio.run(_do())

    if result.status == "ok":
        return _EXIT_SUCCESS
    if result.reason == "halt-complete":
        return _EXIT_SUCCESS
    # stalled
    return _EXIT_STALLED


# ---------------------------------------------------------------------------
# --retry path
# ---------------------------------------------------------------------------


def _run_retry(chunk_id: str, ctx: RunContext) -> int:
    """Reset chunk to PENDING, archive failure record, run one iteration."""
    from .state import get_chunk, reset_to_pending

    # Validate chunk exists
    chunk = get_chunk(chunk_id, ctx.state_db_path)
    if chunk is None:
        print(f"ERROR: chunk {chunk_id!r} not found in state.db", file=sys.stderr)  # noqa: T201 — CLI stderr
        return _EXIT_PRECONDITION

    # Reset to PENDING
    reset_to_pending(chunk_id, ctx.state_db_path)
    logger.info("retry_reset_to_pending", chunk_id=chunk_id)

    # Archive existing failure record if present
    _archive_failure_record(chunk_id, ctx.log_dir)

    # Run exactly one iteration
    ctx.config = RunConfig(
        filter_regex=f"^{re.escape(chunk_id)}$",
        timeout_sec=ctx.config.timeout_sec,
        max_turns=ctx.config.max_turns,
        repo=str(ctx.repo),
        log_dir=str(ctx.log_dir),
        once=True,
        retry=None,
        dry_run=False,
    )
    ctx.filter_regex = f"^{re.escape(chunk_id)}$"

    try:
        from .loop import run_loop

        return asyncio.run(_run_loop_with_signals(ctx, run_loop))
    except BaseException:
        # Runner boundary — catch all unexpected errors, write crash record.
        return _handle_crash(ctx)


def _archive_failure_record(chunk_id: str, log_dir: Path) -> None:
    """Move <chunk_id>.failure.json → archive/<chunk_id>.<ts>.failure.json if present."""
    src = log_dir / f"{chunk_id}.failure.json"
    if not src.exists():
        return
    archive_dir = log_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = to_iso(now_ist()).replace(":", "-").replace("+", "p")
    dest = archive_dir / f"{chunk_id}.{ts}.failure.json"
    try:
        shutil.move(str(src), str(dest))
        logger.info("failure_record_archived", src=str(src), dest=str(dest))
    except OSError as exc:
        logger.warning("failure_record_archive_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Crash handler
# ---------------------------------------------------------------------------


def _handle_crash(ctx: RunContext) -> int:
    """Write crash record, reset in-flight chunk, return exit 4."""
    import claude_agent_sdk  # noqa: PLC0415

    exc_type, exc_val, exc_tb = sys.exc_info()
    tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))

    chunk = ctx.current_chunk
    chunk_id = chunk.id if chunk else None

    try:
        sdk_version = str(claude_agent_sdk.__version__)
    except AttributeError:
        sdk_version = "unknown"

    try:
        git_result = subprocess.run(
            ["git", "-C", str(ctx.repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        runner_version = git_result.stdout.strip() if git_result.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        runner_version = "unknown"

    record = {
        "chunk_id": chunk_id,
        "crashed_at": to_iso(now_ist()),
        "exception_type": (
            f"{exc_type.__module__}.{exc_type.__qualname__}" if exc_type else "unknown"
        ),
        "exception_message": str(exc_val),
        "traceback": tb_str,
        "state_row": None,
        "runner_pid": ctx.runner_pid,
        "runner_version": runner_version,
        "python_version": sys.version,
        "sdk_version": sdk_version,
    }

    # Try to include state row
    if chunk_id:
        try:
            from .state import get_chunk

            row = get_chunk(chunk_id, ctx.state_db_path)
            if row:
                import dataclasses

                record["state_row"] = dataclasses.asdict(row)
        except (OSError, RuntimeError, ValueError):
            pass

    try:
        from .logs import write_crash_record

        write_crash_record(chunk_id, record, ctx.log_dir)
    except Exception as write_exc:
        logger.error("crash_record_write_failed", error=str(write_exc))

    _reset_current_chunk_if_any(ctx)
    return _EXIT_CRASH


def _reset_current_chunk_if_any(ctx: RunContext) -> None:
    """Reset current_chunk to PENDING if one is in-flight. Best-effort."""
    chunk = ctx.current_chunk
    if chunk is None:
        return
    try:
        from .state import reset_to_pending

        reset_to_pending(chunk.id, ctx.state_db_path)
        logger.info("crash_reset_chunk_to_pending", chunk_id=chunk.id)
    except Exception as exc:
        logger.error("crash_reset_failed", chunk_id=chunk.id, error=str(exc))


# ---------------------------------------------------------------------------
# Signal-safe loop wrapper (T042, FR-025)
# ---------------------------------------------------------------------------


async def _run_loop_with_signals(
    ctx: RunContext, run_loop_fn: Callable[..., Coroutine[Any, Any, int]]
) -> int:
    """Run *run_loop_fn(ctx)* inside an asyncio event loop with SIGTERM/SIGINT handlers.

    Handler logic (FR-025):
      1. Sets ctx.cancellation so run_loop exits cleanly at next iteration.
      2. Resets any in-flight chunk to PENDING (best-effort).
      3. Writes a final log entry.

    Signal handlers are installed via ``loop.add_signal_handler`` (Unix-only).
    On Windows (no add_signal_handler), the handlers are silently skipped —
    the KeyboardInterrupt fallback in main() still handles Ctrl-C.
    """
    loop = asyncio.get_running_loop()

    def _on_signal(sig_name: str) -> None:
        logger.warning(
            "runner_signal_received",
            signal=sig_name,
            chunk_id=(ctx.current_chunk.id if ctx.current_chunk else None),
        )
        ctx.cancellation.set()
        # Best-effort reset of in-flight chunk
        _reset_current_chunk_if_any(ctx)
        # Final log entry (best-effort, sync write is safe here)
        try:
            from .logs import write_event

            write_event(
                chunk_id=(ctx.current_chunk.id if ctx.current_chunk else "unknown"),
                event={
                    "type": "runner_signal_exit",
                    "signal": sig_name,
                    "action": "reset_to_pending",
                },
                log_dir=ctx.log_dir,
            )
        except (OSError, ValueError):
            pass

    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: _on_signal("SIGTERM"))
        loop.add_signal_handler(signal.SIGINT, lambda: _on_signal("SIGINT"))
    except AttributeError:
        # Windows: loop.add_signal_handler does not exist
        pass

    try:
        return await run_loop_fn(ctx)
    finally:
        # Remove handlers to avoid interference with test teardown
        try:
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)
        except (AttributeError, OSError):
            pass
