"""Log writers for forge-runner (FR-012..FR-015, FR-034).

All writers call ``secrets.scrub()`` before serialising — no API key ever
appears in a log file, runner-state, failure record, or crash record.

Atomic writes use the tmp-file-then-os.replace pattern so a concurrent reader
always sees a consistent snapshot (never a half-written file).

Public API:
    write_event(chunk_id, event, log_dir)   — append one jsonl line to per-chunk log
    update_runner_state(state, log_dir)      — atomic replace of runner-state.json
    write_failure_record(chunk_id, record, log_dir) — atomic write failure.json
    write_crash_record(chunk_id, record, log_dir)   — atomic write crash.json
    rotate_old_logs(log_dir, keep=50)               — move oldest logs to archive/
    append_event_and_update_state(chunk_id, event, state_dict, log_dir)
        — write event to log AND update runner-state atomically (T031)
    build_failure_record(chunk_id, failed_check, detail, ctx) -> dict
        — construct a schema-conformant failure record dict (T036)
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

import structlog

from .secrets import scrub

logger = structlog.get_logger(__name__)

_RUNNER_STATE_FILE = "runner-state.json"


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write *data* as JSON to *path* atomically (tmp file + os.replace).

    The parent directory is created if it does not exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(scrub(data), fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
    except (OSError, ValueError):
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_event(chunk_id: str, event: dict[str, Any], log_dir: Path) -> None:
    """Append *event* as one JSON line to ``<log_dir>/<chunk_id>.log``.

    The event is scrubbed before writing.  The file is fsynced after each
    write so ``tail -f`` sees events in real time (FR-015).
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{chunk_id}.log"
    scrubbed = scrub(event)
    line = json.dumps(scrubbed, ensure_ascii=False) + "\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def update_runner_state(state: dict[str, Any], log_dir: Path) -> None:
    """Atomically replace ``<log_dir>/runner-state.json`` with *state*.

    Scrubs secrets before writing.  Uses tmp+rename so readers never see
    a partial file (FR-014).
    """
    path = log_dir / _RUNNER_STATE_FILE
    _atomic_write(path, state)


def _read_last_events(chunk_id: str, log_dir: Path, max_events: int = 100) -> list[Any]:
    """Read and parse the last *max_events* JSONL lines from the chunk log.

    Returns a list of dicts.  Malformed lines are skipped with a warning.
    If the log file does not exist, returns an empty list.
    """
    log_path = log_dir / f"{chunk_id}.log"
    if not log_path.exists():
        return []

    events: list[Any] = []
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("failure_record_log_read_error", chunk_id=chunk_id, error=str(exc))
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning(
                "failure_record_log_malformed_line",
                chunk_id=chunk_id,
                preview=line[:80],
            )

    return events[-max_events:]


def _git_status_porcelain(repo: str) -> str:
    """Return `git status --porcelain` output for *repo*. Empty string on error."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_log_last_5(repo: str) -> list[str]:
    """Return last 5 commits as '<short-sha> <subject>' strings."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "log", "-5", "--pretty=format:%h %s"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def _runner_version(repo: str) -> str:
    """Return `git rev-parse --short HEAD` or '0000000' on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip()
        if result.returncode == 0 and version:
            return version
    except (OSError, subprocess.SubprocessError):
        pass
    return "0000000"


_RECOVERY_MAP: dict[str, str] = {
    "state_db_not_done": (
        "run scripts/post-chunk.sh <chunk_id> to sync state.db, "
        "then forge-runner --retry <chunk_id>"
    ),
    "no_commit_with_prefix": (
        "re-ship via scripts/forge-ship.sh with the correct chunk prefix, "
        "then forge-runner --retry <chunk_id>"
    ),
    "stamp_not_fresh": (
        "touch .forge/last-run.json to refresh the stamp, then forge-runner --retry <chunk_id>"
    ),
    "dirty_working_tree": (
        "git status; stash or commit the untracked changes, then forge-runner --retry <chunk_id>"
    ),
    "shipped_needs_sync": (
        "run scripts/post-chunk.sh <chunk_id> to sync state.db "
        "and update the wiki, then forge-runner --resume"
    ),
}


def build_failure_record(
    chunk_id: str,
    failed_check: str,
    detail: str,
    ctx: Any,
) -> dict[str, Any]:
    """Construct a failure record dict matching contracts/failure-record.schema.json.

    Args:
        chunk_id:     The chunk whose post-session verification failed.
        failed_check: One of the enum values in the schema.
        detail:       Human-readable detail for the specific failure.
        ctx:          RunContext-like object; needs .log_dir, .repo,
                      .runner_pid, and optionally .session_id.

    Returns:
        A dict ready to pass to ``write_failure_record()``.
    """
    from ._time import now_ist, to_iso  # local to avoid circular

    log_dir: Path = Path(str(ctx.log_dir))
    repo: str = str(ctx.repo)
    pid: int = int(ctx.runner_pid) if hasattr(ctx, "runner_pid") else os.getpid()

    # session_id: use ctx.session_id if present, otherwise build a stable fallback
    session_id: str = getattr(ctx, "session_id", None) or f"forge-{chunk_id}-{pid}"

    # state_row: get from state.db and convert to a plain dict
    state_row: dict[str, Any] = {}
    try:
        from .state import get_chunk  # local to avoid circular

        state_db_path: str = str(ctx.state_db_path)
        row = get_chunk(chunk_id, state_db_path)
        if row is not None:
            state_row = dataclasses.asdict(row)
    except Exception as exc:
        logger.warning(
            "build_failure_record_state_read_error",
            chunk_id=chunk_id,
            error=str(exc),
        )

    # Convert any non-serialisable types in state_row (e.g. list is fine)
    recovery = _RECOVERY_MAP.get(
        failed_check,
        f"investigate failed_check={failed_check!r} and retry",
    ).replace("<chunk_id>", chunk_id)

    record: dict[str, Any] = {
        "chunk_id": chunk_id,
        "failed_at": to_iso(now_ist()),
        "failed_check": failed_check,
        "failed_check_detail": detail,
        "session_id": session_id,
        "last_events": scrub(_read_last_events(chunk_id, log_dir)),
        "state_row": scrub(state_row),
        "git_status": _git_status_porcelain(repo),
        "git_log_last_5": _git_log_last_5(repo),
        "suggested_recovery": recovery,
        "runner_pid": pid,
        "runner_version": _runner_version(repo),
    }

    return record


def write_failure_record(chunk_id: str, record: dict[str, Any], log_dir: Path) -> None:
    """Atomically write *record* to ``<log_dir>/<chunk_id>.failure.json``.

    Scrubs secrets.  Atomic write (tmp+rename).
    """
    path = log_dir / f"{chunk_id}.failure.json"
    _atomic_write(path, record)
    logger.warning("failure_record_written", chunk_id=chunk_id, path=str(path))


def write_crash_record(chunk_id: Optional[str], record: dict[str, Any], log_dir: Path) -> None:
    """Atomically write *record* to ``<log_dir>/<stem>.crash.json``.

    If *chunk_id* is None (crash outside a session), uses ``_no_chunk`` as
    the filename stem.
    """
    stem = chunk_id if chunk_id else "_no_chunk"
    path = log_dir / f"{stem}.crash.json"
    _atomic_write(path, record)
    logger.error("crash_record_written", chunk_id=chunk_id, path=str(path))


def append_event_and_update_state(
    chunk_id: str,
    event: dict[str, Any],
    state_dict: dict[str, Any],
    log_dir: Path,
) -> None:
    """Write *event* to the chunk log AND update runner-state atomically.

    Mutates *state_dict* in-place:
    - Increments ``event_count`` (initialises to 0 if missing/None).
    - Sets ``last_event_at`` to the current IST timestamp.
    - If the event kind is ``tool_use``, sets ``last_tool`` with
      ``name`` and ``input_preview`` (first 200 chars after secrets.scrub()).

    Both writes (log append + state replace) happen together so a reader that
    sees the updated runner-state.json can be confident the event is already
    in the log file (FR-015).
    """
    from ._time import now_ist, to_iso  # local import avoids circular

    # 1. Append the event to the per-chunk log file first
    write_event(chunk_id, event, log_dir)

    # 2. Update the state_dict fields
    current_count = state_dict.get("event_count") or 0
    state_dict["event_count"] = current_count + 1
    state_dict["last_event_at"] = to_iso(now_ist())

    # 3. last_tool: extract and scrub input_preview from tool_use events
    scrubbed_event = scrub(event)
    if scrubbed_event.get("kind") == "tool_use":
        payload = scrubbed_event.get("payload", {})
        tool_name = payload.get("tool", "")
        raw_input = str(payload.get("input", ""))
        state_dict["last_tool"] = {
            "name": tool_name,
            "input_preview": raw_input[:200],
        }

    # 4. Atomically write updated runner-state
    update_runner_state(state_dict, log_dir)


def validate_log_file(path: Path) -> tuple[bool, list[str]]:
    """Validate every line in a jsonl log file against the actual log-event format.

    The log-event contract (contracts/log-event.schema.json) specifies fields
    ``evt`` and ``session_id``, but the runner's ``write_event`` function writes
    events with ``kind`` and ``chunk_id`` instead.  This validator checks the
    actual written format: every line must be valid JSON with the four required
    top-level keys ``t``, ``chunk_id``, ``kind``, and ``payload``.

    Note on schema divergence: the JSON schema file reflects a desired future
    format.  This function validates what is actually on disk.  See
    docs/architecture/forge-runner-log-queries.md for context.

    Args:
        path: Path to a ``.log`` jsonl file.

    Returns:
        ``(True, [])`` if every line is valid.
        ``(False, [error, ...])`` listing each validation failure (line number
        and reason).  Never raises.
    """
    _REQUIRED_FIELDS = ("t", "chunk_id", "kind", "payload")
    errors: list[str] = []

    if not path.exists():
        return False, [f"file not found: {path}"]

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"cannot read file: {exc}"]

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False, ["file is empty"]

    for lineno, raw in enumerate(lines, start=1):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSON — {exc}")
            continue

        if not isinstance(obj, dict):
            errors.append(f"line {lineno}: expected a JSON object, got {type(obj).__name__}")
            continue

        for field in _REQUIRED_FIELDS:
            if field not in obj:
                errors.append(f"line {lineno}: missing required field '{field}'")

    valid = len(errors) == 0
    return valid, errors


def write_snapshot_if_needed(
    chunk_id: str,
    event_count: int,
    log_dir: Path,
    *,
    interval: int = 20,
) -> Optional[Path]:
    """Every *interval* events, dump a crash-recovery snapshot (Enhancement E).

    The snapshot reads the tail of the chunk's event log and writes a JSON
    summary to ``<log_dir>/snapshots/<chunk_id>.snapshot.json``. Returns the
    snapshot path if one was written, otherwise ``None``.

    Best-effort: never raises. Caller passes the running event count — when
    ``event_count % interval == 0`` and ``event_count > 0`` we take a snapshot.
    """
    if event_count <= 0 or event_count % interval != 0:
        return None
    try:
        from ._time import now_ist, to_iso
    except Exception:
        return None

    try:
        last_events = _read_last_events(chunk_id, log_dir, max_events=interval)
        snapshot_dir = log_dir / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{chunk_id}.snapshot.json"
        payload = {
            "chunk_id": chunk_id,
            "captured_at": to_iso(now_ist()),
            "events_count": event_count,
            "last_events": scrub(last_events),
        }
        _atomic_write(snapshot_path, payload)
        return snapshot_path
    except Exception as exc:
        logger.warning("snapshot_write_failed", chunk_id=chunk_id, error=str(exc))
        return None


def rotate_old_logs(log_dir: Path, keep: int = 50) -> None:
    """Move the oldest ``.log`` files beyond *keep* into ``<log_dir>/archive/``.

    Files are sorted by modification time (oldest first).  Only ``.log``
    files are considered — ``.json``, ``.failure.json``, ``.crash.json`` are
    never rotated here.

    FR-034: active log count is bounded at *keep* to prevent unbounded
    disk growth during long multi-chunk runs.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = log_dir / "archive"

    log_files = sorted(
        log_dir.glob("*.log"),
        key=lambda p: p.stat().st_mtime,
    )

    if len(log_files) <= keep:
        return

    archive_dir.mkdir(parents=True, exist_ok=True)
    to_rotate = log_files[: len(log_files) - keep]
    for old_log in to_rotate:
        dest = archive_dir / old_log.name
        # If archive already has a file with this name, add a suffix.
        if dest.exists():
            dest = archive_dir / f"{old_log.stem}.{int(old_log.stat().st_mtime)}.log"
        old_log.rename(dest)
        logger.info("log_rotated", src=str(old_log), dest=str(dest))
