"""file_exists — assert path exists and (optionally) exceeds a size threshold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def run_file_exists(check: dict[str, Any]) -> tuple[bool, str]:
    path = ROOT / check["path"]
    if not path.exists():
        return False, f"missing: {check['path']}"
    if not path.is_file():
        return False, f"not a file: {check['path']}"
    size = path.stat().st_size
    min_size = int(check.get("min_size_bytes", 0))
    if size < min_size:
        return False, f"{check['path']} is {size}B < {min_size}B required"
    return True, f"{check['path']} present ({size}B)"
