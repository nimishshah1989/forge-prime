"""Routes chunk model aliases to API model IDs and providers."""
import os
from enum import Enum
from typing import Optional, Tuple


class ModelProvider(Enum):
    ANTHROPIC = "anthropic"   # claude_agent_sdk, Max plan
    OPENROUTER = "openrouter" # httpx, OPENROUTER_API_KEY


MODELS: dict[str, Tuple[str, ModelProvider]] = {
    "opus":              ("claude-opus-4-7",                    ModelProvider.ANTHROPIC),
    "sonnet":            ("claude-sonnet-4-6",                  ModelProvider.ANTHROPIC),
    "haiku":             ("claude-haiku-4-5",                   ModelProvider.ANTHROPIC),
    "deepseek":          ("deepseek/deepseek-chat",             ModelProvider.OPENROUTER),
    "deepseek-reasoner": ("deepseek/deepseek-reasoner",         ModelProvider.OPENROUTER),
    "gemini-flash":      ("google/gemini-2.0-flash-exp:free",   ModelProvider.OPENROUTER),
}

COST_PER_1K: dict[str, dict[str, float]] = {
    "claude-opus-4-7":                  {"in": 0.0,     "out": 0.0},
    "claude-sonnet-4-6":                {"in": 0.0,     "out": 0.0},
    "claude-haiku-4-5":                 {"in": 0.0,     "out": 0.0},
    "deepseek/deepseek-chat":           {"in": 0.00027, "out": 0.0011},
    "deepseek/deepseek-reasoner":       {"in": 0.0014,  "out": 0.0219},
    "google/gemini-2.0-flash-exp:free": {"in": 0.0,     "out": 0.0},
}

DEFAULT = os.getenv("FORGE_DEFAULT_MODEL", "sonnet")


def resolve(alias: Optional[str]) -> Tuple[str, ModelProvider]:
    key = (alias or DEFAULT).lower()
    return MODELS.get(key, MODELS[DEFAULT])


def cost_usd(model_id: str, in_tok: int, out_tok: int) -> float:
    c = COST_PER_1K.get(model_id, {"in": 0.0, "out": 0.0})
    return (in_tok * c["in"] + out_tok * c["out"]) / 1000
