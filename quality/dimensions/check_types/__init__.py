"""Declarative check-type handlers for the product dim.

Each handler takes the criterion dict and returns `(passed: bool, evidence: str)`.
Keep handlers under 50 lines. Raise nothing — return (False, msg) on failure.
"""

from __future__ import annotations

from typing import Any, Callable

from .file_exists import run_file_exists
from .http_contract import run_http_contract
from .python_callable import run_python_callable
from .sql_count import run_sql_count
from .sql_invariant import run_sql_invariant

Handler = Callable[[dict[str, Any]], tuple[bool, str]]

HANDLERS: dict[str, Handler] = {
    "http_contract": run_http_contract,
    "sql_count": run_sql_count,
    "sql_invariant": run_sql_invariant,
    "python_callable": run_python_callable,
    "file_exists": run_file_exists,
}


def dispatch(check: dict[str, Any]) -> tuple[bool, str]:
    t = check.get("type")
    handler = HANDLERS.get(t or "")
    if handler is None:
        return False, f"unknown check type: {t}"
    try:
        return handler(check)
    except Exception as exc:  # noqa: BLE001
        return False, f"{t} handler crashed: {str(exc)[:120]}"
