"""Halt-condition evaluator for forge-runner (FR-019..FR-021).

Determines whether the runner should CONTINUE, declare COMPLETE, or STALLED
after all eligible chunks have been exhausted by the picker.

Public API:
    HaltDecision    — enum CONTINUE | COMPLETE | STALLED
    EXIT_CODES      — module-level dict mapping decision/condition to int
    evaluate_halt(ctx) -> HaltDecision
"""

from __future__ import annotations

import enum
import subprocess
import sys
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class HaltDecision(enum.Enum):
    """Possible outcomes of evaluate_halt()."""

    CONTINUE = "continue"
    COMPLETE = "complete"
    STALLED = "stalled"


# ---------------------------------------------------------------------------
# Exit code map (authoritative, consumed by loop.py and cli.py)
# ---------------------------------------------------------------------------

EXIT_CODES: dict[str, int] = {
    "success_complete": 0,
    "auth_failure": 1,
    "stalled": 2,
    "chunk_failed": 3,
    "crash": 4,
    "dead_man_detected": 5,
    "concurrent_runner": 6,
    "startup_precondition": 7,
    # halt decisions mapped to exit codes
    HaltDecision.COMPLETE.value: 0,
    HaltDecision.STALLED.value: 2,
    HaltDecision.CONTINUE.value: 0,
}


def evaluate_halt(ctx: Any) -> HaltDecision:
    """Evaluate whether the runner should halt or continue.

    Called when the picker returns None (no eligible chunks).

    Decision logic:
      - Runs ``python .quality/checks.py`` in ctx.repo.
      - Optionally runs ``scripts/validate-v1-completion.py`` if it exists.
      - COMPLETE  = quality gate exit code 0 AND picker is None.
      - STALLED   = picker None AND quality not green.

    Args:
        ctx: RunContext-like with ``.repo`` attribute (Path or str).

    Returns:
        :class:`HaltDecision`
    """
    repo = Path(str(ctx.repo))
    quality_ok = _run_quality_gate(repo)
    criteria_ok = _run_criteria_validator(repo)

    if quality_ok and criteria_ok:
        logger.info("halt_decision_complete", repo=str(repo))
        return HaltDecision.COMPLETE

    logger.warning(
        "halt_decision_stalled",
        repo=str(repo),
        quality_ok=quality_ok,
        criteria_ok=criteria_ok,
    )
    return HaltDecision.STALLED


def _run_quality_gate(repo: Path) -> bool:
    """Run .quality/checks.py and return True if exit code is 0."""
    quality_script = repo / ".quality" / "checks.py"
    if not quality_script.exists():
        logger.warning(
            "quality_script_not_found",
            path=str(quality_script),
        )
        # If no quality script, treat as not green (conservative)
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(quality_script)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=120,
        )
        passed = result.returncode == 0
        if not passed:
            logger.warning(
                "quality_gate_failed",
                returncode=result.returncode,
                stdout=result.stdout[:500],
                stderr=result.stderr[:500],
            )
        else:
            logger.info("quality_gate_passed")
        return passed
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.error("quality_gate_error", error=str(exc))
        return False


def _run_criteria_validator(repo: Path) -> bool:
    """Run scripts/validate-v1-completion.py if it exists; return True otherwise."""
    validator = repo / "scripts" / "validate-v1-completion.py"
    if not validator.exists():
        # Optional — absence means no additional criteria to satisfy
        return True

    try:
        result = subprocess.run(
            [sys.executable, str(validator)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
        )
        passed = result.returncode == 0
        if not passed:
            logger.warning(
                "criteria_validator_failed",
                returncode=result.returncode,
                stdout=result.stdout[:500],
                stderr=result.stderr[:500],
            )
        else:
            logger.info("criteria_validator_passed")
        return passed
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.error("criteria_validator_error", error=str(exc))
        return False
