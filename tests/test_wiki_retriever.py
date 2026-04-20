"""Tests for runner/wiki_retriever.py (Enhancement A + F)."""
import json
import sqlite3
from pathlib import Path

from runner import wiki_retriever


def test_retrieve_empty_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki_retriever, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(wiki_retriever, "EMBED_CACHE", tmp_path / ".embed-cache.json")
    assert wiki_retriever.retrieve("anything") == []


def test_log_retrieval_creates_table(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki_retriever, "WIKI_DIR", tmp_path)
    (tmp_path / "articles").mkdir()
    article = tmp_path / "articles" / "a.md"
    article.write_text("x" * 100)

    db = tmp_path / "state.db"
    sqlite3.connect(str(db)).close()

    wiki_retriever.log_retrieval("V1-1", [article], str(db))

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT chunk_id, article_path FROM wiki_retrievals"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "V1-1"
    assert rows[0][1] == "articles/a.md"


def test_log_retrieval_no_articles_noop(tmp_path):
    db = tmp_path / "state.db"
    sqlite3.connect(str(db)).close()
    # No articles → no table created, no error.
    wiki_retriever.log_retrieval("V1-1", [], str(db))
    conn = sqlite3.connect(str(db))
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_retrievals'"
    ).fetchone()
    conn.close()
    assert exists is None
