"""CLI argument parsing and RunConfig dataclass for forge-runner.

Public API:
    parse_duration(s: str) -> int          — convert "45m"/"2700s"/"1h" to seconds
    parse_args(argv: list[str] | None) -> RunConfig
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass, field
from typing import Optional


_DURATION_PATTERN = re.compile(r"^(\d+)(m|s|h)$")

_DEFAULT_TIMEOUT = "45m"
_DEFAULT_MAX_TURNS = 300
_DEFAULT_FILTER = ".*"
_DEFAULT_LOG_DIR = ".forge/logs"


def parse_duration(s: str) -> int:
    """Convert a duration string to an integer number of seconds.

    Accepted formats:
      - ``45m``   → 2700
      - ``2700s`` → 2700
      - ``1h``    → 3600

    Raises ``argparse.ArgumentTypeError`` on unrecognised input.
    """
    m = _DURATION_PATTERN.match(s.strip())
    if not m:
        raise argparse.ArgumentTypeError(
            f"Invalid duration {s!r}. Use formats like 45m, 2700s, or 1h."
        )
    value = int(m.group(1))
    unit = m.group(2)
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    # unreachable
    raise argparse.ArgumentTypeError(f"Unknown duration unit in {s!r}")  # pragma: no cover


@dataclass
class RunConfig:
    """Parsed CLI configuration for forge-runner."""

    filter_regex: str = _DEFAULT_FILTER
    timeout_sec: int = field(default_factory=lambda: parse_duration(_DEFAULT_TIMEOUT))
    max_turns: int = _DEFAULT_MAX_TURNS
    repo: str = field(default_factory=os.getcwd)
    log_dir: str = _DEFAULT_LOG_DIR
    resume: bool = False
    retry: Optional[str] = None
    dry_run: bool = False
    once: bool = False
    strict_dead_man: bool = False
    verbose: int = 0


def parse_args(argv: Optional[list[str]] = None) -> RunConfig:
    """Parse *argv* (or ``sys.argv[1:]`` when None) into a :class:`RunConfig`."""
    parser = argparse.ArgumentParser(
        prog="forge-runner",
        description="Autonomous chunk loop for Forge OS — walks V1..VN without interactive input.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--filter",
        dest="filter_regex",
        default=_DEFAULT_FILTER,
        metavar="REGEX",
        help=(
            "Python regex applied via fullmatch to chunk IDs. "
            "Only matching chunks are eligible. Default: '.*' (all chunks)."
        ),
    )

    parser.add_argument(
        "--timeout",
        dest="timeout",
        default=_DEFAULT_TIMEOUT,
        metavar="DURATION",
        help=("Wall-clock timeout per inner session. Accepts 45m, 2700s, 1h. Default: 45m."),
    )

    parser.add_argument(
        "--max-turns",
        dest="max_turns",
        type=int,
        default=_DEFAULT_MAX_TURNS,
        metavar="INT",
        help="Turn budget passed to the inner SDK session. Default: 300.",
    )

    parser.add_argument(
        "--repo",
        dest="repo",
        default=None,
        metavar="PATH",
        help="Repository root. Default: current working directory.",
    )

    parser.add_argument(
        "--log-dir",
        dest="log_dir",
        default=_DEFAULT_LOG_DIR,
        metavar="PATH",
        help="Directory for per-chunk logs, failure records, etc. Default: .forge/logs",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help=(
            "No-op documented alias for a normal start. "
            "Picker naturally resumes whatever is PENDING with satisfied deps."
        ),
    )

    parser.add_argument(
        "--retry",
        dest="retry",
        default=None,
        metavar="CHUNK_ID",
        help=(
            "Reset the given chunk to PENDING, archive its failure record if "
            "present, and run exactly one iteration against it. "
            "Incompatible with --once."
        ),
    )

    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help=(
            "Print the chunk the picker would select and the reason. "
            "Does not touch state.db or spawn a session. "
            "Exit 0 if a chunk was picked, 2 if stalled."
        ),
    )

    parser.add_argument(
        "--once",
        dest="once",
        action="store_true",
        default=False,
        help="Run exactly one iteration then exit. Incompatible with --retry.",
    )

    parser.add_argument(
        "--strict-dead-man",
        dest="strict_dead_man",
        action="store_true",
        default=False,
        help=(
            "On startup, halt with exit 5 if any orphaned IN_PROGRESS row is "
            "detected, instead of auto-resetting."
        ),
    )

    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="count",
        default=0,
        help="Increase runner's own structlog level to DEBUG. Repeatable.",
    )

    ns = parser.parse_args(argv)

    # Mutual exclusion: --retry and --once
    if ns.retry and ns.once:
        parser.error("--retry and --once are mutually exclusive.")

    # Parse duration string to int seconds
    try:
        timeout_sec = parse_duration(ns.timeout)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    repo = ns.repo if ns.repo is not None else os.getcwd()

    return RunConfig(
        filter_regex=ns.filter_regex,
        timeout_sec=timeout_sec,
        max_turns=ns.max_turns,
        repo=repo,
        log_dir=ns.log_dir,
        resume=ns.resume,
        retry=ns.retry,
        dry_run=ns.dry_run,
        once=ns.once,
        strict_dead_man=ns.strict_dead_man,
        verbose=ns.verbose,
    )
