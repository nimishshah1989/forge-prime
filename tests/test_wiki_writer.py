"""Tests for runner/wiki_writer.py"""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from runner.wiki_writer import write_article, write_failure_article, _commit_and_push


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


def test_commit_and_push_no_remote_still_succeeds(tmp_path, monkeypatch):
    """A fresh local-only wiki (no remote) should still return True on commit."""
    wiki = tmp_path / "wiki"
    (wiki / "staging").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(wiki)], check=True)
    subprocess.run(["git", "-C", str(wiki), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(wiki), "config", "user.name",  "t"], check=True)
    # Disable gpg signing in case the global config forces it in CI.
    subprocess.run(["git", "-C", str(wiki), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(wiki), "config", "tag.gpgsign",    "false"], check=True)
    # Seed with an initial commit so HEAD exists.
    (wiki / "README.md").write_text("seed")
    subprocess.run(["git", "-C", str(wiki), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(wiki), "commit", "-q", "-m", "seed"], check=True)

    (wiki / "staging" / "article.md").write_text("hello")
    monkeypatch.setattr("runner.wiki_writer.WIKI_DIR", wiki)

    result = _commit_and_push(["staging/article.md"], "wiki: test")
    assert result is True
    # Commit landed locally even without a remote.
    log = subprocess.run(
        ["git", "-C", str(wiki), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    )
    assert "wiki: test" in log.stdout
