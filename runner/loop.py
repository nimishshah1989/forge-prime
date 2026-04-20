"""Main async loop for forge-runner (T026).

Iterates the PIPELINE: pick → implement → verify → advance.

Public API:
    run_loop(ctx: RunContext) -> int
"""

from __future__ import annotations

import asyncio

import structlog

from ._time import now_ist
from typing import Union

from .stages import (
    LocalImplementStage,
    LocalLoopAdvanceStage,
    LocalPickStage,
    LocalVerifyStage,
    RunContext,
    StageResult,
)

logger = structlog.get_logger(__name__)

_AnyStage = Union[LocalPickStage, LocalImplementStage, LocalVerifyStage, LocalLoopAdvanceStage]

PIPELINE: list[_AnyStage] = [
    LocalPickStage(),
    LocalImplementStage(),
    LocalVerifyStage(),
    LocalLoopAdvanceStage(),
]

# Exit codes aligned with halt.EXIT_CODES and cli.md contract
_EXIT_SUCCESS = 0
_EXIT_AUTH_FAILURE = 1
_EXIT_STALLED = 2
_EXIT_CHUNK_FAILED = 3
_EXIT_CRASH = 4


async def run_loop(ctx: RunContext) -> int:
    """Run the pick→implement→verify→advance loop until halt or cancellation.

    Returns an exit code per contracts/cli.md.
    """
    logger.info(
        "loop_started",
        filter_regex=ctx.filter_regex,
        once=ctx.once,
        runner_pid=ctx.runner_pid,
    )

    while not ctx.cancellation.is_set():
        iteration_chunk_id: str | None = None

        for stage in PIPELINE:
            # --- PICK STAGE ---
            if isinstance(stage, LocalPickStage):
                result = await stage.run(ctx)

                if result.status == "skipped":
                    # Halt decision
                    if result.reason == "halt-complete":
                        logger.info("loop_halt_complete")
                        return _EXIT_SUCCESS
                    # halt-stalled
                    logger.warning("loop_halt_stalled", reason=result.reason)
                    return _EXIT_STALLED

                # Picked a chunk — load it into context
                chunk_id = result.artifacts.get("chunk_id")
                iteration_chunk_id = chunk_id
                if chunk_id:
                    from .state import get_chunk

                    ctx.current_chunk = get_chunk(chunk_id, ctx.state_db_path)
                continue

            # --- IMPLEMENT STAGE ---
            if isinstance(stage, LocalImplementStage):
                result = await stage.run(ctx)

                if result.status == "failed":
                    if result.reason == "auth":
                        # Auth failure — reset chunk to PENDING, exit 1
                        _reset_current_chunk(ctx)
                        return _EXIT_AUTH_FAILURE

                    # Session error (timeout, etc.) — mark failed
                    _mark_current_failed(ctx, result.reason)
                    _write_failure_record(ctx, result)
                    return _EXIT_CHUNK_FAILED

                continue

            # --- VERIFY STAGE ---
            if isinstance(stage, LocalVerifyStage):
                result = await stage.run(ctx)

                if result.status == "needs_sync":
                    # Commit landed but post-chunk sync missed — log and continue
                    logger.warning(
                        "loop_needs_sync",
                        chunk_id=result.chunk_id,
                        reason=result.reason,
                    )
                    # Treat as continue — the sync will reconcile state.db
                    continue

                if result.status == "failed":
                    _mark_current_failed(ctx, result.reason)
                    ctx.chunks_failed += 1
                    return _EXIT_CHUNK_FAILED

                continue

            # --- ADVANCE STAGE (and any future stages) ---
            result = await stage.run(ctx)
            if result.status == "failed":
                return _EXIT_CHUNK_FAILED

        # End of pipeline for this iteration
        if ctx.once:
            logger.info("loop_once_complete", chunk_id=iteration_chunk_id)
            return _EXIT_SUCCESS

        # Reset current_chunk for next iteration
        ctx.current_chunk = None
        ctx.session_started_at = None

    # Cancellation requested
    logger.info("loop_cancelled_by_signal")
    _reset_current_chunk(ctx)
    return _EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_current_chunk(ctx: RunContext) -> None:
    """Reset ctx.current_chunk to PENDING. Best-effort."""
    chunk = ctx.current_chunk
    if chunk is None:
        return
    try:
        from .state import reset_to_pending

        reset_to_pending(chunk.id, ctx.state_db_path)
        logger.info("loop_reset_chunk_to_pending", chunk_id=chunk.id)
    except Exception as exc:
        logger.error("loop_reset_chunk_failed", chunk_id=chunk.id, error=str(exc))


def _mark_current_failed(ctx: RunContext, reason: str) -> None:
    """Mark ctx.current_chunk FAILED. Best-effort.

    Also fires a best-effort failure-article write (Enhancement D) so the
    wiki captures anti-patterns alongside successes.
    """
    chunk = ctx.current_chunk
    if chunk is None:
        return
    try:
        from .state import mark_failed

        mark_failed(chunk.id, reason, ctx.state_db_path)
    except Exception as exc:
        logger.error("loop_mark_failed_error", chunk_id=chunk.id, error=str(exc))

    try:
        from .wiki_writer import write_failure_article

        asyncio.create_task(
            asyncio.to_thread(
                write_failure_article,
                chunk.id,
                chunk.title or chunk.id,
                ctx.log_dir,
                reason,
            )
        )
    except RuntimeError:
        # No running loop (e.g. sync test path) — skip silently.
        pass
    except Exception as exc:
        logger.warning("loop_failure_article_error", chunk_id=chunk.id, error=str(exc))


def _write_failure_record(ctx: RunContext, result: StageResult) -> None:
    """Write a failure record for ctx.current_chunk. Best-effort."""
    chunk = ctx.current_chunk
    if chunk is None:
        return
    try:
        from . import logs
        from ._time import to_iso

        record = {
            "chunk_id": chunk.id,
            "failed_at": to_iso(now_ist()),
            "failed_check": result.reason,
            "failed_check_detail": result.reason,
            "runner_pid": ctx.runner_pid,
        }
        logs.write_failure_record(chunk.id, record, ctx.log_dir)
    except Exception as exc:
        logger.error("loop_failure_record_error", chunk_id=chunk.id, error=str(exc))
