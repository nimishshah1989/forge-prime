"""Tests for runner/classifier.py"""
import pytest
from unittest.mock import patch, MagicMock
from runner.classifier import classify


def test_classify_no_key_returns_feature():
    with patch.dict("os.environ", {}, clear=True):
        result = classify("add a button")
    assert result["type"] == "feature"
    assert "estimated_chunks" in result


def test_classify_returns_dict_shape():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"type":"quick","reasoning":"small","estimated_chunks":1,"files_likely_touched":["app.py"]}'}}]
    }
    with patch("httpx.post", return_value=mock_response), \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        result = classify("add a health check endpoint")
    assert result["type"] in ("quick", "feature", "milestone")
    assert "reasoning" in result
    assert "estimated_chunks" in result


def test_classify_handles_httpx_error():
    import httpx
    with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")), \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        result = classify("do something")
    assert result["type"] == "feature"
    assert "error" in result["reasoning"].lower() or "classifier" in result["reasoning"].lower()


def test_classify_strips_markdown_fence():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '```json\n{"type":"milestone","reasoning":"big","estimated_chunks":5,"files_likely_touched":[]}\n```'}}]
    }
    with patch("httpx.post", return_value=mock_response), \
         patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        result = classify("build a complete auth system")
    assert result["type"] == "milestone"
