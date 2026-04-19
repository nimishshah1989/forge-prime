"""SQLite CRUD layer for forge-runner against orchestrator/state.db.

All writes use ``BEGIN IMMEDIATE`` transactions (research.md §2 — prevents
concurrent writers from racing on the same row).  All timestamps use
``_time.now_ist()`` + ``to_iso()`` so the DB always stores IST ISO8601.

This module operates on the *runner* view of the chunks table — it is NOT
a replacement for orchestrator/state.py (which the orchestrator CLI uses).
They coexist safely: both speak sqlite3, both use WAL mode, and their write
paths touch disjoint columns.

Public API:
    get_chunk(chunk_id, db_path) -> ChunkRow | None
    mark_in_progress(chunk_id, pid, db_path) -> None
    mark_failed(chunk_id, reason, db_path) -> None
    reset_to_pending(chunk_id, db_path) -> None
    list_in_progress(db_path) -> list[ChunkRow]
    list_pending_matching(filter_regex, db_path) -> list[ChunkRow]
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional

import structlog

from ._time import now_ist, to_iso

logger = structlog.get_logger(__name__)


@dataclass
class ChunkRow:
    """Mirrors the columns in the chunks table that the runner cares about."""

    id: str
    title: str
    status: str
    attempts: int
    last_error: Optional[str]
    plan_version: str
    depends_on: list[str]  # parsed from JSON
    created_at: str
    updated_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    runner_pid: Optional[int]
    failure_reason: Optional[str]
    model_alias: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row_to_chunk(row: sqlite3.Row) -> ChunkRow:
    d = dict(row)
    depends_raw = d.get("depends_on", "[]")
    try:
        depends_on: list[str] = json.loads(depends_raw) if depends_raw else []
    except (json.JSONDecodeError, TypeError):
        depends_on = []
    return ChunkRow(
        id=d["id"],
        title=d["title"],
        status=d["status"],
        attempts=int(d.get("attempts", 0)),
        last_error=d.get("last_error"),
        plan_version=d.get("plan_version", ""),
        depends_on=depends_on,
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        started_at=d.get("started_at"),
        finished_at=d.get("finished_at"),
        runner_pid=d.get("runner_pid"),
        failure_reason=d.get("failure_reason"),
    )


def get_chunk(chunk_id: str, db_path: str) -> Optional[ChunkRow]:
    """Return the ChunkRow for *chunk_id*, or None if not found."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return _row_to_chunk(row) if row else None
    finally:
        conn.close()


def mark_in_progress(chunk_id: str, pid: int, db_path: str) -> None:
    """Transition *chunk_id* → IN_PROGRESS.

    Sets: status=IN_PROGRESS, started_at=now, runner_pid=pid,
          updated_at=now, attempts+=1.
    Clears: failure_reason (reset to NULL).
    Uses BEGIN IMMEDIATE to serialise concurrent runners.
    """
    now = to_iso(now_ist())
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE chunks
               SET status = 'IN_PROGRESS',
                   started_at = ?,
                   runner_pid = ?,
                   failure_reason = NULL,
                   updated_at = ?,
                   attempts = attempts + 1
               WHERE id = ?""",
            (now, pid, now, chunk_id),
        )
        conn.execute("COMMIT")
        logger.info(
            "chunk_marked_in_progress",
            chunk_id=chunk_id,
            pid=pid,
            started_at=now,
        )
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def mark_failed(chunk_id: str, reason: str, db_path: str) -> None:
    """Transition *chunk_id* → FAILED.

    Sets: status=FAILED, failure_reason=reason, runner_pid=NULL,
          updated_at=now.
    """
    now = to_iso(now_ist())
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE chunks
               SET status = 'FAILED',
                   failure_reason = ?,
                   runner_pid = NULL,
                   updated_at = ?
               WHERE id = ?""",
            (reason, now, chunk_id),
        )
        conn.execute("COMMIT")
        logger.warning(
            "chunk_marked_failed",
            chunk_id=chunk_id,
            reason=reason,
        )
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def reset_to_pending(chunk_id: str, db_path: str) -> None:
    """Reset *chunk_id* to PENDING, clearing all three runner columns.

    Used by the dead-man scan (orphan recovery), SIGTERM handler, and the
    ``--retry`` path.
    """
    now = to_iso(now_ist())
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE chunks
               SET status = 'PENDING',
                   started_at = NULL,
                   runner_pid = NULL,
                   failure_reason = NULL,
                   updated_at = ?
               WHERE id = ?""",
            (now, chunk_id),
        )
        conn.execute("COMMIT")
        logger.info("chunk_reset_to_pending", chunk_id=chunk_id)
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def list_in_progress(db_path: str) -> list[ChunkRow]:
    """Return all chunks with status=IN_PROGRESS."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM chunks WHERE status = 'IN_PROGRESS'").fetchall()
        return [_row_to_chunk(r) for r in rows]
    finally:
        conn.close()


def list_pending_matching(filter_regex: str, db_path: str) -> list[ChunkRow]:
    """Return PENDING chunks whose id matches *filter_regex*, sorted by id.

    The sort is lexicographic on the id string — the picker (T015) selects
    the first eligible row from the sorted list.
    """
    pattern = re.compile(filter_regex)
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM chunks WHERE status = 'PENDING' ORDER BY id").fetchall()
        result: list[ChunkRow] = []
        for row in rows:
            chunk = _row_to_chunk(row)
            if pattern.search(chunk.id):
                result.append(chunk)
        return result
    finally:
        conn.close()
