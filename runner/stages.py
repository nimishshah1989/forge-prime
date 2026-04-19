"""Stage protocol + concrete local stages + HostedStageBase stub (T025).

Public API:
    StageResult         — dataclass returned by every stage
    RunContext          — dataclass holding all per-run configuration
    Stage               — runtime-checkable Protocol
    LocalPickStage      — wraps picker.pick_next
    LocalImplementStage — wraps session.run_session, streams events to logs
    LocalVerifyStage    — wraps verifier.run_four_checks
    LocalLoopAdvanceStage — bookkeeping; always returns OK
    HostedStageBase     — abstract base (NotImplementedError; wired in L3-HYBRID-AGENTS)
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Protocol, runtime_checkable

import structlog

from ._time import now_ist, to_iso
from .config import RunConfig
from .session import run_session  # noqa: E402 – used in LocalImplementStage

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# StageResult
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Return value of every Stage.run() and Stage.dry_run() call."""

    stage_name: str
    status: Literal["ok", "failed", "skipped", "needs_sync"]
    chunk_id: Optional[str]
    artifacts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    started_at: datetime = field(default_factory=lambda: now_ist())
    duration_ms: int = 0

    def to_json_safe(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (for log events, failure records)."""
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "chunk_id": self.chunk_id,
            "artifacts": self.artifacts,
            "reason": self.reason,
            "started_at": to_iso(self.started_at),
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    """All per-run configuration passed between the loop and stages."""

    config: RunConfig
    repo: Path
    log_dir: Path
    state_db_path: str
    cancellation: asyncio.Event
    current_chunk: Any  # ChunkRow | None — typed Any to avoid circular import
    session_started_at: Optional[datetime]
    timeout_sec: int
    max_turns: int
    # Derived/runtime fields
    runner_pid: int = field(default_factory=os.getpid)
    loop_started_at: datetime = field(default_factory=now_ist)
    chunks_completed: int = 0
    chunks_failed: int = 0
    # Convenience accessors
    filter_regex: str = ".*"

    @property
    def once(self) -> bool:
        return self.config.once


# ---------------------------------------------------------------------------
# Stage Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Stage(Protocol):
    """Protocol satisfied by every stage in the pipeline.

    Both ``run`` and ``dry_run`` must be implemented.
    ``name`` is a class-level str attribute.
    """

    name: str

    async def run(self, ctx: RunContext) -> StageResult:
        """Execute the stage, potentially mutating state.db and filesystem."""
        ...

    async def dry_run(self, ctx: RunContext) -> StageResult:
        """Print what the stage would do; must NOT mutate persistent state."""
        ...


# ---------------------------------------------------------------------------
# LocalPickStage
# ---------------------------------------------------------------------------


class LocalPickStage:
    """Picks the next eligible PENDING chunk from state.db."""

    name: str = "pick"

    async def run(self, ctx: RunContext) -> StageResult:
        from .picker import pick_next

        t0 = now_ist()
        chunk = pick_next(ctx.filter_regex, ctx.state_db_path)
        ms = _elapsed_ms(t0)

        if chunk is not None:
            logger.info("stage_pick_ok", chunk_id=chunk.id)
            return StageResult(
                stage_name=self.name,
                status="ok",
                chunk_id=chunk.id,
                artifacts={"chunk_id": chunk.id},
                reason=f"picked {chunk.id}",
                started_at=t0,
                duration_ms=ms,
            )

        # No eligible chunk — evaluate halt
        from .halt import HaltDecision, evaluate_halt

        decision = evaluate_halt(ctx)

        if decision == HaltDecision.COMPLETE:
            return StageResult(
                stage_name=self.name,
                status="skipped",
                chunk_id=None,
                reason="halt-complete",
                started_at=t0,
                duration_ms=ms,
            )

        return StageResult(
            stage_name=self.name,
            status="skipped",
            chunk_id=None,
            reason="halt-stalled",
            started_at=t0,
            duration_ms=ms,
        )

    async def dry_run(self, ctx: RunContext) -> StageResult:
        from .picker import pick_next

        t0 = now_ist()
        chunk = pick_next(ctx.filter_regex, ctx.state_db_path)
        ms = _elapsed_ms(t0)

        if chunk is not None:
            print(f"[dry-run] would pick: {chunk.id} — {chunk.title}")  # noqa: T201 — dry-run CLI output
            return StageResult(
                stage_name=self.name,
                status="ok",
                chunk_id=chunk.id,
                artifacts={"chunk_id": chunk.id},
                reason=f"dry-run picked {chunk.id}",
                started_at=t0,
                duration_ms=ms,
            )

        from .halt import HaltDecision, evaluate_halt

        decision = evaluate_halt(ctx)
        if decision == HaltDecision.COMPLETE:
            print("[dry-run] no eligible chunk — halt-complete")  # noqa: T201 — dry-run CLI output
            return StageResult(
                stage_name=self.name,
                status="skipped",
                chunk_id=None,
                reason="halt-complete",
                started_at=t0,
                duration_ms=ms,
            )

        print("[dry-run] no eligible chunk — halt-stalled")  # noqa: T201 — dry-run CLI output
        return StageResult(
            stage_name=self.name,
            status="skipped",
            chunk_id=None,
            reason="halt-stalled",
            started_at=t0,
            duration_ms=ms,
        )


# ---------------------------------------------------------------------------
# LocalImplementStage
# ---------------------------------------------------------------------------


class LocalImplementStage:
    """Transitions chunk to IN_PROGRESS, spawns a session, streams events."""

    name: str = "implement"

    async def run(self, ctx: RunContext) -> StageResult:
        from . import logs, state
        from .session import AuthFailure

        t0 = now_ist()
        chunk = ctx.current_chunk
        if chunk is None:
            return StageResult(
                stage_name=self.name,
                status="failed",
                chunk_id=None,
                reason="no chunk in context",
                started_at=t0,
            )

        # Transition → IN_PROGRESS
        state.mark_in_progress(chunk.id, ctx.runner_pid, ctx.state_db_path)
        ctx.session_started_at = now_ist()

        # Invalidate lint/type caches before the agent sees the quality gate.
        # Why: a stale `.ruff_cache` once trapped V5-2 for 45 minutes reporting
        # a phantom `F401 sqlalchemy.text` error in a file that did not contain
        # that import on disk. The agent kept "fixing" the file, the cache kept
        # replaying the ghost, and wall-clock killed the session. A chunk must
        # start with an empty cache so the gate reflects disk truth.
        _invalidate_lint_caches(ctx.repo)

        # Snapshot quality baseline so forge-ship.sh can delta-gate this chunk
        # against the last-shipped state. Missing report.json = first chunk or
        # manual run; delta check becomes a no-op.
        import shutil as _shutil

        baseline_src = ctx.repo / ".quality" / "report.json"
        baseline_dir = ctx.repo / ".forge" / "baseline"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_dst = baseline_dir / "current.json"
        if baseline_src.exists():
            _shutil.copy2(baseline_src, baseline_dst)
            (baseline_dir / "current.chunk").write_text(chunk.id)
            logger.info(
                "baseline_snapshot_ok",
                chunk_id=chunk.id,
                baseline_path=str(baseline_dst),
            )
        else:
            # No prior report — remove stale baseline so ship script skips delta check
            baseline_dst.unlink(missing_ok=True)
            (baseline_dir / "current.chunk").unlink(missing_ok=True)
            logger.info("baseline_snapshot_skip", chunk_id=chunk.id, reason="no_prior_report")

        # Runner-state: session starting
        _update_runner_state(ctx, current_chunk=chunk.id)

        try:
            async for event in run_session(chunk, ctx):
                logs.write_event(chunk.id, event, ctx.log_dir)
                _update_runner_state(ctx, current_chunk=chunk.id, last_event=event)

        except AuthFailure:
            logger.error("implement_auth_failure", chunk_id=chunk.id)
            return StageResult(
                stage_name=self.name,
                status="failed",
                chunk_id=chunk.id,
                reason="auth",
                started_at=t0,
                duration_ms=_elapsed_ms(t0),
            )
        except asyncio.TimeoutError:
            logger.error("implement_timeout", chunk_id=chunk.id)
            return StageResult(
                stage_name=self.name,
                status="failed",
                chunk_id=chunk.id,
                reason="timeout",
                started_at=t0,
                duration_ms=_elapsed_ms(t0),
            )

        return StageResult(
            stage_name=self.name,
            status="ok",
            chunk_id=chunk.id,
            reason="session_end",
            started_at=t0,
            duration_ms=_elapsed_ms(t0),
        )

    async def dry_run(self, ctx: RunContext) -> StageResult:
        t0 = now_ist()
        chunk = ctx.current_chunk
        chunk_id = chunk.id if chunk else None
        print(f"[dry-run] would implement: {chunk_id}")  # noqa: T201 — dry-run CLI output
        return StageResult(
            stage_name=self.name,
            status="skipped",
            chunk_id=chunk_id,
            reason="dry-run",
            started_at=t0,
        )


# ---------------------------------------------------------------------------
# LocalVerifyStage
# ---------------------------------------------------------------------------


def _invoke_post_chunk_sync(chunk_id: str, ctx: RunContext) -> None:
    """Fire scripts/post-chunk.sh for the just-shipped chunk.

    Non-fatal: the script spawns a background headless claude for wiki /
    memory sync and exits fast, but if the script is missing or errors we
    log a warning and keep running rather than failing the verify stage.
    The post-chunk sync invariant stays a soft gate at the runner seam —
    the hard gate is the four checks that just passed.
    """
    import subprocess

    repo_root = Path(ctx.repo) if ctx.repo else Path.cwd()
    script_path = repo_root / "scripts" / "post-chunk.sh"
    if not script_path.exists():
        logger.warning(
            "post_chunk_sync_missing",
            chunk_id=chunk_id,
            script=str(script_path),
        )
        return

    try:
        proc = subprocess.run(
            ["bash", str(script_path), chunk_id],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("post_chunk_sync_timeout", chunk_id=chunk_id)
        return
    except Exception as exc:  # noqa: BLE001 — non-fatal hook
        logger.warning("post_chunk_sync_error", chunk_id=chunk_id, error=str(exc))
        return

    if proc.returncode != 0:
        logger.warning(
            "post_chunk_sync_nonzero",
            chunk_id=chunk_id,
            returncode=proc.returncode,
            stderr_tail=proc.stderr[-400:] if proc.stderr else "",
        )
    else:
        logger.info("post_chunk_sync_ok", chunk_id=chunk_id)


class LocalVerifyStage:
    """Runs the four post-session checks and returns OK, FAILED, or NEEDS_SYNC."""

    name: str = "verify"

    async def run(self, ctx: RunContext) -> StageResult:
        from . import logs
        from .verifier import run_four_checks

        t0 = now_ist()
        chunk = ctx.current_chunk
        if chunk is None:
            return StageResult(
                stage_name=self.name,
                status="failed",
                chunk_id=None,
                reason="no chunk in context",
                started_at=t0,
            )

        result = run_four_checks(chunk.id, ctx)

        if result.passed:
            _invoke_post_chunk_sync(chunk.id, ctx)

            # Non-blocking wiki article synthesis + cost tracking
            model_id = getattr(ctx, "model_id", "claude-sonnet-4-6")
            asyncio.create_task(
                asyncio.to_thread(
                    _write_wiki_and_cost,
                    chunk.id,
                    chunk.title,
                    ctx.log_dir,
                    model_id,
                    ctx.state_db_path,
                )
            )

            return StageResult(
                stage_name=self.name,
                status="ok",
                chunk_id=chunk.id,
                reason="all five checks passed",
                started_at=t0,
                duration_ms=_elapsed_ms(t0),
            )

        if result.needs_sync:
            logger.warning(
                "verify_needs_sync",
                chunk_id=chunk.id,
                detail=result.detail,
            )
            return StageResult(
                stage_name=self.name,
                status="needs_sync",
                chunk_id=chunk.id,
                reason=result.detail,
                started_at=t0,
                duration_ms=_elapsed_ms(t0),
            )

        # Failure — write failure record
        failure_record = {
            "chunk_id": chunk.id,
            "failed_at": to_iso(now_ist()),
            "failed_check": result.failed_check,
            "failed_check_detail": result.detail,
            "runner_pid": ctx.runner_pid,
        }
        logs.write_failure_record(chunk.id, failure_record, ctx.log_dir)

        return StageResult(
            stage_name=self.name,
            status="failed",
            chunk_id=chunk.id,
            reason=result.failed_check or "unknown",
            started_at=t0,
            duration_ms=_elapsed_ms(t0),
        )

    async def dry_run(self, ctx: RunContext) -> StageResult:
        t0 = now_ist()
        chunk = ctx.current_chunk
        chunk_id = chunk.id if chunk else None
        print(f"[dry-run] would verify: {chunk_id}")  # noqa: T201 — dry-run CLI output
        return StageResult(
            stage_name=self.name,
            status="skipped",
            chunk_id=chunk_id,
            reason="dry-run",
            started_at=t0,
        )


# ---------------------------------------------------------------------------
# LocalLoopAdvanceStage
# ---------------------------------------------------------------------------


class LocalLoopAdvanceStage:
    """Bookkeeping stage — increments counters, updates runner state.

    Always returns OK.
    """

    name: str = "advance"

    async def run(self, ctx: RunContext) -> StageResult:
        t0 = now_ist()
        chunk = ctx.current_chunk
        chunk_id = chunk.id if chunk else None
        ctx.chunks_completed += 1
        logger.info(
            "loop_advance_ok",
            chunk_id=chunk_id,
            chunks_completed=ctx.chunks_completed,
        )
        _update_runner_state(ctx, current_chunk=None)
        return StageResult(
            stage_name=self.name,
            status="ok",
            chunk_id=chunk_id,
            reason="chunk completed",
            started_at=t0,
            duration_ms=_elapsed_ms(t0),
        )

    async def dry_run(self, ctx: RunContext) -> StageResult:
        t0 = now_ist()
        return StageResult(
            stage_name=self.name,
            status="skipped",
            chunk_id=None,
            reason="dry-run",
            started_at=t0,
        )


# ---------------------------------------------------------------------------
# HostedStageBase (stub — wired in L3-HYBRID-AGENTS)
# ---------------------------------------------------------------------------


class HostedStageBase(Stage, ABC):
    """Abstract base for stages that run on Anthropic's Managed Agents API.

    Implementation deferred to chunk L3-HYBRID-AGENTS.  This class exists in
    Phase 1 only to lock the interface so the future migration is a subclass
    addition, not a loop rewrite.

    Expected request shape (documentation-only for Phase 1)::

        POST /v1/agents
        {
          "agent_definition_id": "<e.g., forge-code-reviewer>",
          "input": { "chunk_id": str, "diff": str, "spec_md": str, ... },
          "max_tokens": int,
          "timeout_ms": int
        }

    Expected response shape::

        {
          "run_id": str,
          "status": "completed" | "failed",
          "output": { ... stage-specific ... },
          "usage": { input_tokens, output_tokens, ... }
        }

    Timeout policy: client-side timeout = stage budget + 30s grace.
    Retry policy:   exponential backoff on 429 and 5xx, max 3 retries.
    Error handling: any error → StageResult(status='failed', reason=<http_status>).
    """

    @abstractmethod
    def agent_definition_id(self) -> str:
        """Return the Managed Agent definition ID for this stage."""

    @abstractmethod
    def build_request(self, chunk: Any, ctx: RunContext) -> dict[str, Any]:
        """Build the POST /v1/agents request body for this stage."""

    @abstractmethod
    def parse_response(self, response: dict[str, Any]) -> StageResult:
        """Parse the /v1/agents response into a StageResult."""

    async def run(self, ctx: RunContext) -> StageResult:
        raise NotImplementedError(
            "HostedStageBase.run is implemented in chunk L3-HYBRID-AGENTS, "
            "not L2-RUNNER. See docs/specs/prd-L2-RUNNER.md §14 for the rationale."
        )

    async def dry_run(self, ctx: RunContext) -> StageResult:
        t0 = now_ist()
        return StageResult(
            stage_name=getattr(self, "name", "hosted"),
            status="skipped",
            chunk_id=None,
            reason="hosted stage — implementation deferred to L3-HYBRID-AGENTS",
            started_at=t0,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(t0: datetime) -> int:
    delta = now_ist() - t0
    return int(delta.total_seconds() * 1000)


_LINT_CACHE_DIRS = (".ruff_cache", ".mypy_cache")


def _invalidate_lint_caches(repo: Path) -> list[Path]:
    """Delete every ``.ruff_cache`` / ``.mypy_cache`` under *repo*.

    Returns the list of directories removed (for test assertions + logging).
    Never raises — cache invalidation is best-effort; a failure here must
    not block chunk start.
    """
    import shutil as _shutil

    removed: list[Path] = []
    for cache_name in _LINT_CACHE_DIRS:
        for cache_dir in repo.rglob(cache_name):
            if not cache_dir.is_dir():
                continue
            try:
                _shutil.rmtree(cache_dir)
                removed.append(cache_dir)
            except OSError as exc:
                logger.warning(
                    "lint_cache_invalidate_failed",
                    cache_dir=str(cache_dir),
                    error=str(exc),
                )
    if removed:
        logger.info(
            "lint_cache_invalidated",
            count=len(removed),
            dirs=[str(p.relative_to(repo)) for p in removed],
        )
    return removed


def _update_runner_state(
    ctx: RunContext,
    current_chunk: Optional[str] = None,
    last_event: Optional[dict[str, Any]] = None,
) -> None:
    """Best-effort update of runner-state.json. Never raises."""
    from . import logs
    import claude_agent_sdk  # noqa: PLC0415

    try:
        sdk_version = str(claude_agent_sdk.__version__)
    except AttributeError:
        sdk_version = "unknown"

    try:
        import subprocess as _sp

        git_result = _sp.run(
            ["git", "-C", str(ctx.repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        runner_version = git_result.stdout.strip() if git_result.returncode == 0 else "unknown"
    except (OSError, _sp.SubprocessError):
        runner_version = "unknown"

    state: dict[str, Any] = {
        "schema_version": "1",
        "runner_pid": ctx.runner_pid,
        "runner_version": runner_version,
        "sdk_version": sdk_version,
        "loop_started_at": to_iso(ctx.loop_started_at),
        "current_chunk": current_chunk,
        "chunk_started_at": to_iso(ctx.session_started_at) if ctx.session_started_at else None,
        "last_event_at": to_iso(now_ist()) if last_event else None,
        "event_count": 0,
        "last_tool": None,
        "chunks_completed_this_run": ctx.chunks_completed,
        "chunks_failed_this_run": ctx.chunks_failed,
        "filter_regex": ctx.filter_regex,
        "cumulative_usage": {},
    }

    if last_event and last_event.get("kind") == "tool_use":
        from .secrets import scrub as _scrub  # noqa: PLC0415

        payload = last_event.get("payload", {})
        tool_name = payload.get("tool", "")
        # Scrub secrets BEFORE truncating so a key is never partially visible
        raw_input = _scrub(str(payload.get("input", "")))
        state["last_tool"] = {
            "name": tool_name,
            "input_preview": raw_input[:200],
        }

    try:
        logs.update_runner_state(state, ctx.log_dir)
    except Exception as exc:
        logger.warning("runner_state_update_failed", error=str(exc))


def _write_wiki_and_cost(
    chunk_id: str,
    title: str,
    log_dir: Path,
    model_id: str,
    state_db_path: str,
) -> None:
    """Sync helper: called from asyncio.to_thread after verify passes."""
    try:
        from .wiki_writer import write_article
        write_article(chunk_id, title, log_dir)
    except Exception as exc:
        logger.warning("wiki_write_failed", chunk_id=chunk_id, error=str(exc))
    try:
        from .cost_tracker import record
        record(chunk_id, model_id, log_dir, state_db_path)
    except Exception as exc:
        logger.warning("cost_record_failed", chunk_id=chunk_id, error=str(exc))
