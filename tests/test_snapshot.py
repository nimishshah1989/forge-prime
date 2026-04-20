"""Tests for snapshot-on-interval in runner/logs.py (Enhancement E)."""
import json
from pathlib import Path

from runner import logs


def test_snapshot_not_written_before_interval(tmp_path):
    (tmp_path / "V1-1.log").write_text('{"kind":"text","payload":{}}\n')
    path = logs.write_snapshot_if_needed("V1-1", event_count=5, log_dir=tmp_path)
    assert path is None
    assert not (tmp_path / "snapshots").exists()


def test_snapshot_written_at_interval(tmp_path):
    log_path = tmp_path / "V1-1.log"
    log_path.write_text(
        "\n".join(
            json.dumps({"t": "2026-01-01", "chunk_id": "V1-1", "kind": "text", "payload": {"i": i}})
            for i in range(25)
        )
        + "\n"
    )

    path = logs.write_snapshot_if_needed("V1-1", event_count=20, log_dir=tmp_path)
    assert path is not None
    assert path.exists()

    data = json.loads(path.read_text())
    assert data["chunk_id"] == "V1-1"
    assert data["events_count"] == 20
    assert isinstance(data["last_events"], list)
    assert len(data["last_events"]) == 20


def test_snapshot_zero_event_count_noop(tmp_path):
    path = logs.write_snapshot_if_needed("V1-1", event_count=0, log_dir=tmp_path)
    assert path is None
