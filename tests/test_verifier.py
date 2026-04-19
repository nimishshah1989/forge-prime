"""Tests for runner/verifier.py — the 5-check gate."""
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from runner.verifier import (
    _check_clean_tree,
    _check_commit_prefix,
    _check_pushed,
    _check_stamp_fresh,
    _check_state_db_done,
)


def test_check_pushed_ok(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, msg = _check_pushed(tmp_path)
    assert ok
    assert "pushed" in msg


def test_check_pushed_fail(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="abc123 V1-1: some commit\n", stderr="")
        ok, msg = _check_pushed(tmp_path)
    assert not ok
    assert "unpushed" in msg


def test_check_clean_tree_clean(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, msg = _check_clean_tree(tmp_path)
    assert ok


def test_check_clean_tree_dirty(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=" M some_file.py\n", stderr="")
        ok, msg = _check_clean_tree(tmp_path)
    assert not ok
    assert "dirty" in msg


def test_check_commit_prefix_found(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="V1-1: some commit message\n", stderr="")
        ok, msg = _check_commit_prefix("V1-1", tmp_path)
    assert ok


def test_check_commit_prefix_not_found(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="V1-2: different chunk\n", stderr="")
        ok, msg = _check_commit_prefix("V1-1", tmp_path)
    assert not ok


def test_check_state_db_done(tmp_path):
    import sqlite3
    db = tmp_path / "state.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE chunks (id TEXT, title TEXT, status TEXT, attempts INTEGER, last_error TEXT, plan_version TEXT, depends_on TEXT, created_at TEXT, updated_at TEXT, started_at TEXT, finished_at TEXT, runner_pid INTEGER, failure_reason TEXT)")
    conn.execute("INSERT INTO chunks VALUES ('V1-1','Test','DONE',0,NULL,'1','[]','','','',NULL,NULL,NULL)")
    conn.commit()
    conn.close()
    ok, msg = _check_state_db_done("V1-1", str(db))
    assert ok


def test_check_state_db_not_done(tmp_path):
    import sqlite3
    db = tmp_path / "state.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE chunks (id TEXT, title TEXT, status TEXT, attempts INTEGER, last_error TEXT, plan_version TEXT, depends_on TEXT, created_at TEXT, updated_at TEXT, started_at TEXT, finished_at TEXT, runner_pid INTEGER, failure_reason TEXT)")
    conn.execute("INSERT INTO chunks VALUES ('V1-1','Test','IN_PROGRESS',1,NULL,'1','[]','','','',NULL,NULL,NULL)")
    conn.commit()
    conn.close()
    ok, msg = _check_state_db_done("V1-1", str(db))
    assert not ok
