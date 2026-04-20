"""Tests for runner/wiki_writer.py"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from runner.wiki_writer import write_article, write_failure_article


def test_write_article_no_key(tmp_path):
    log = tmp_path / "V1-1.log"
    log.write_text('{"kind":"text","payload":{"content":"hello"}}\n')
    with patch.dict("os.environ", {}, clear=True):
        result = write_article("V1-1", "Test chunk", tmp_path)
    assert result is False


def test_write_article_no_log(tmp_path):
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
        result = write_article("V1-MISSING", "Missing chunk", tmp_path)
    assert result is False


def test_write_article_api_success(tmp_path, monkeypatch):
    log = tmp_path / "V1-1.log"
    log.write_text('{"kind":"session_end","payload":{"usage":{"input_tokens":100,"output_tokens":200}}}\n')

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "---\ntitle: Test\ncategory: patterns\n---\n# Test\n"}}]
    }

    # Patch the STAGING dir to tmp_path/staging
    monkeypatch.setattr("runner.wiki_writer.STAGING", tmp_path / "staging")

    with patch("httpx.post", return_value=mock_resp), \
         patch("subprocess.run") as mock_sub, \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        mock_sub.return_value = MagicMock(returncode=0)
        result = write_article("V1-1", "Test Chunk Title", tmp_path)

    assert result is True
    assert (tmp_path / "staging" / "V1-1.md").exists()


def test_write_failure_article_no_key(tmp_path):
    with patch.dict("os.environ", {}, clear=True):
        result = write_failure_article("V1-1", "Title", tmp_path, "timeout")
    assert result is False


def test_write_failure_article_success(tmp_path, monkeypatch):
    log = tmp_path / "V1-1.log"
    log.write_text('{"kind":"error","payload":{"message":"boom"}}\n')
    (tmp_path / "V1-1.failure.json").write_text('{"failed_check":"timeout"}')

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "---\ntitle: FAIL\ncategory: anti-patterns\n---\n# FAIL\n"}}]
    }

    monkeypatch.setattr("runner.wiki_writer.STAGING", tmp_path / "staging")

    with patch("httpx.post", return_value=mock_resp), \
         patch("subprocess.run") as mock_sub, \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        mock_sub.return_value = MagicMock(returncode=0)
        result = write_failure_article("V1-1", "Broken Chunk", tmp_path, "timeout")

    assert result is True
    assert (tmp_path / "staging" / "FAIL-V1-1.md").exists()
