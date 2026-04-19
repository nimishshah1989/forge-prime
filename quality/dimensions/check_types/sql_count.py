"""sql_count — run a scalar count query, assert min/max bounds.

On connection failure or missing table we return (False, evidence) rather than
raising. That's the whole point of the V1.6 R1 flip — these checks need to
fail loudly until decisions/findings are actually being written.
"""

from __future__ import annotations

import os
import re
from typing import Any

DB_URL_ENVS = ("ATLAS_DATABASE_URL", "DATABASE_URL")


def _resolve_db_url() -> str | None:
    for key in DB_URL_ENVS:
        v = os.environ.get(key)
        if v:
            return v
    # Try loading from .env file at project root
    try:
        from pathlib import Path

        env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, val = line.partition("=")
                k = k.strip()
                if k in DB_URL_ENVS:
                    return val.strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        from backend.config import get_settings

        return str(get_settings().database_url)
    except Exception:  # noqa: BLE001
        return None


def _to_sync(url: str) -> str:
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)


def run_sql_count(check: dict[str, Any]) -> tuple[bool, str]:
    url = _resolve_db_url()
    if not url:
        return False, "no DATABASE_URL — cannot run sql_count"
    try:
        import psycopg2
    except ImportError:
        return False, "psycopg2 not installed — cannot run sql_count"
    query = check["query"]
    lo = check.get("min")
    hi = check.get("max")
    try:
        conn = psycopg2.connect(_to_sync(url), connect_timeout=5)
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
                count = int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"query failed: {str(exc)[:100]}"
    bounds = []
    if lo is not None and count < int(lo):
        return False, f"count={count} < min={lo}"
    if hi is not None and count > int(hi):
        return False, f"count={count} > max={hi}"
    if lo is not None:
        bounds.append(f"≥{lo}")
    if hi is not None:
        bounds.append(f"≤{hi}")
    return True, f"count={count} ({' '.join(bounds) or 'any'})"
