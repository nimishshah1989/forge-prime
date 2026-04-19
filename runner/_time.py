"""IST-aware timestamp helpers for forge-runner (research.md §8).

All timestamps emitted by the runner MUST have an explicit +05:30 offset —
never naive datetime.  This module is the single source of truth for time.

Usage::

    from ._time import now_ist, to_iso

    ts = now_ist()          # datetime(2026, 4, 13, 12, 0, 0, tzinfo=IST)
    iso = to_iso(ts)        # "2026-04-13T12:00:00+05:30"
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST: ZoneInfo = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Return the current time as a timezone-aware datetime in IST (+05:30)."""
    return datetime.now(tz=IST)


def to_iso(dt: datetime) -> str:
    """Serialise *dt* to ISO8601 with explicit +05:30 offset.

    If *dt* is UTC or another timezone it is first converted to IST so the
    offset in the output string is always ``+05:30``.

    Raises ``ValueError`` if *dt* is naive (no tzinfo).
    """
    if dt.tzinfo is None:
        raise ValueError(
            f"to_iso() received a naive datetime: {dt!r}. "
            "Always use IST-aware datetimes (now_ist())."
        )
    ist_dt = dt.astimezone(IST)
    return ist_dt.isoformat(timespec="seconds")


def utc_to_ist(dt: datetime) -> datetime:
    """Convert a UTC-aware datetime to IST.  Convenience helper."""
    return dt.astimezone(IST)


def from_iso(s: str) -> datetime:
    """Parse an ISO8601 string back to a timezone-aware datetime.

    Handles both ``+05:30`` and ``+00:00`` suffixes and converts to IST.
    """
    # Python 3.11+ fromisoformat handles timezone offsets directly.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"from_iso() parsed a naive datetime from {s!r}")
    return dt.astimezone(IST)
