"""sql_invariant — run a scalar query, assert value against min/max/equals."""

from __future__ import annotations

from typing import Any

from .sql_count import _resolve_db_url, _to_sync


def run_sql_invariant(check: dict[str, Any]) -> tuple[bool, str]:
    url = _resolve_db_url()
    if not url:
        return False, "no DATABASE_URL — cannot run sql_invariant"
    try:
        import psycopg2
    except ImportError:
        return False, "psycopg2 not installed — cannot run sql_invariant"
    query = check["query"]
    try:
        conn = psycopg2.connect(_to_sync(url), connect_timeout=5)
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
                value = row[0] if row else None
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"query failed: {str(exc)[:100]}"
    eq = check.get("equals")
    lo = check.get("min")
    hi = check.get("max")
    if eq is not None and value != eq:
        return False, f"value={value!r} ≠ {eq!r}"
    try:
        numeric = float(value) if value is not None else None
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None:
        if lo is not None and numeric < float(lo):
            return False, f"value={numeric} < min={lo}"
        if hi is not None and numeric > float(hi):
            return False, f"value={numeric} > max={hi}"
    return True, f"value={value}"
