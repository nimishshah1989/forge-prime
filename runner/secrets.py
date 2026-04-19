"""Secret scrubbing utilities for forge-runner (FR-040).

`scrub(obj)` recursively traverses any JSON-serialisable structure and
redacts API keys and sensitive values before they are written to log files,
runner-state.json, failure records, or crash records.

Pure function — never mutates the input.  No side effects.
"""

from __future__ import annotations

import re
from typing import Any

# Anthropic API key pattern: sk-ant-api03- followed by 20+ base64url chars.
_API_KEY_RE = re.compile(r"sk-ant-api03-[A-Za-z0-9_\-]{20,}")

# Key names (case-insensitive) whose VALUES are always redacted.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "anthropic_api_key",
        "authorization",
        "bearer_token",
    }
)


def scrub(obj: Any) -> Any:
    """Recursively redact secrets from *obj*.

    Rules (applied in order):
    1. If *obj* is a dict, return a new dict with keys preserved and values
       passed through ``scrub()`` — EXCEPT keys in ``_SENSITIVE_KEYS``
       (case-insensitive), whose values are replaced with ``"<redacted>"``.
    2. If *obj* is a list or tuple, return the same container type with every
       element passed through ``scrub()``.
    3. If *obj* is a string, replace any substring matching the API-key
       pattern with ``"<redacted-api-key>"``.
    4. All other types are returned unchanged.

    The function never mutates *obj*.
    """
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                result[k] = "<redacted>"
            else:
                result[k] = scrub(v)
        return result

    if isinstance(obj, list):
        return [scrub(item) for item in obj]

    if isinstance(obj, tuple):
        return tuple(scrub(item) for item in obj)

    if isinstance(obj, str):
        return _API_KEY_RE.sub("<redacted-api-key>", obj)

    return obj
