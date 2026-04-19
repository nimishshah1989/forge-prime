"""Tests for runner/router.py"""
import os
import pytest
from runner.router import ModelProvider, cost_usd, resolve


def test_resolve_sonnet():
    model_id, provider = resolve("sonnet")
    assert model_id == "claude-sonnet-4-6"
    assert provider == ModelProvider.ANTHROPIC


def test_resolve_opus():
    model_id, provider = resolve("opus")
    assert model_id == "claude-opus-4-7"
    assert provider == ModelProvider.ANTHROPIC


def test_resolve_deepseek():
    model_id, provider = resolve("deepseek")
    assert model_id == "deepseek/deepseek-chat"
    assert provider == ModelProvider.OPENROUTER


def test_resolve_gemini_flash():
    model_id, provider = resolve("gemini-flash")
    assert provider == ModelProvider.OPENROUTER


def test_resolve_none_uses_default():
    model_id, provider = resolve(None)
    # Default is sonnet unless env var overrides
    assert provider in (ModelProvider.ANTHROPIC, ModelProvider.OPENROUTER)


def test_resolve_unknown_falls_back_to_default():
    model_id, provider = resolve("nonexistent-model")
    # Falls back to DEFAULT (sonnet)
    assert model_id == "claude-sonnet-4-6"


def test_cost_usd_anthropic_is_zero():
    # Anthropic Max plan — no per-token cost tracked
    assert cost_usd("claude-sonnet-4-6", 1000, 1000) == 0.0


def test_cost_usd_deepseek():
    cost = cost_usd("deepseek/deepseek-chat", 1000, 1000)
    assert cost > 0.0


def test_cost_usd_unknown_model_is_zero():
    assert cost_usd("unknown-model", 9999, 9999) == 0.0
