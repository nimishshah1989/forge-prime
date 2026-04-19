"""python_callable — import a dotted path, call it, inspect its return."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

QUALITY_DIR = Path(__file__).resolve().parents[2]


def run_python_callable(check: dict[str, Any]) -> tuple[bool, str]:
    dotted = check["dotted_path"]
    module_path, _, func_name = dotted.rpartition(".")
    if not module_path:
        return False, f"bad dotted_path: {dotted}"
    # Ensure .quality/ is on sys.path so quality_product_checks resolves.
    if str(QUALITY_DIR) not in sys.path:
        sys.path.insert(0, str(QUALITY_DIR))
    try:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
    except Exception as exc:  # noqa: BLE001
        return False, f"import failed: {str(exc)[:100]}"
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001
        return False, f"callable raised: {str(exc)[:100]}"
    if not isinstance(out, tuple) or len(out) != 2:
        return False, f"callable returned {type(out).__name__}, expected (bool, str)"
    passed, evidence = out
    return bool(passed), str(evidence)
