"""http_contract — hit URL, assert 200 under latency budget."""

from __future__ import annotations

import time
import urllib.request
from typing import Any


def run_http_contract(check: dict[str, Any]) -> tuple[bool, str]:
    url = check["url"]
    budget = int(check["max_latency_ms"])
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-quality/1.0"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=max(5, budget / 1000 * 2)) as resp:
            status = resp.status
            body_len = len(resp.read(4096))
    except Exception as exc:  # noqa: BLE001
        return False, f"{url} unreachable: {str(exc)[:80]}"
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if status != 200:
        return False, f"{url} → {status} ({elapsed_ms}ms)"
    if elapsed_ms > budget:
        return False, f"{url} → 200 but {elapsed_ms}ms > {budget}ms budget"
    return (
        True,
        f"{url} → 200 in {elapsed_ms}ms (budget {budget}ms, {body_len}B sampled)",
    )
