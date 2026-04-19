"""Chunk picker for forge-runner (FR-001..FR-004).

Selects the next eligible PENDING chunk according to:
  1. Chunk ID matches ``filter_regex`` via ``re.fullmatch``.
  2. All dependency IDs have status == 'DONE' in state.db (deps are checked
     against real state, regardless of whether they match the filter).
  3. Returns the first eligible chunk in lexicographic ID order.

Public API:
    pick_next(filter_regex, state_db_path) -> ChunkRow | None
"""

from __future__ import annotations

import re
from typing import Optional

import structlog

from .state import ChunkRow, get_chunk, list_pending_matching

logger = structlog.get_logger(__name__)


def pick_next(filter_regex: str, state_db_path: str) -> Optional[ChunkRow]:
    """Return the first eligible PENDING chunk or None.

    A chunk is eligible iff:
      - Its ID fully matches *filter_regex* (fullmatch semantics per cli.md).
      - Every ID in its ``depends_on`` list has ``status == 'DONE'`` in state.db.

    Candidates are examined in lexicographic ID order (guaranteed by
    ``list_pending_matching`` which uses ``ORDER BY id``).  The first eligible
    candidate is returned immediately.

    This function is read-only — it never writes to state.db.
    """
    # list_pending_matching uses re.search internally; we need fullmatch so we
    # pass a pattern anchored at both ends, then re-filter locally with fullmatch.
    try:
        candidates = list_pending_matching(filter_regex, state_db_path)
    except Exception:
        logger.exception("picker_list_failed", filter_regex=filter_regex)
        return None

    pattern = re.compile(filter_regex)

    for chunk in candidates:
        # Re-apply fullmatch locally (list_pending_matching uses re.search)
        if not pattern.fullmatch(chunk.id):
            logger.debug(
                "picker_skip_no_fullmatch",
                chunk_id=chunk.id,
                filter_regex=filter_regex,
            )
            continue

        if not _deps_done(chunk, state_db_path):
            continue

        logger.info(
            "picker_selected",
            chunk_id=chunk.id,
            depends_on=chunk.depends_on,
        )
        return chunk

    logger.debug("picker_no_eligible_chunk", filter_regex=filter_regex)
    return None


def _deps_done(chunk: ChunkRow, state_db_path: str) -> bool:
    """Return True iff every dependency of *chunk* is DONE in state.db."""
    for dep_id in chunk.depends_on:
        dep = get_chunk(dep_id, state_db_path)
        if dep is None:
            # Unknown dependency — treat as not satisfied (safe default).
            logger.warning(
                "picker_dep_not_found",
                chunk_id=chunk.id,
                dep_id=dep_id,
            )
            return False
        if dep.status != "DONE":
            logger.debug(
                "picker_dep_not_done",
                chunk_id=chunk.id,
                dep_id=dep_id,
                dep_status=dep.status,
            )
            return False
    return True
