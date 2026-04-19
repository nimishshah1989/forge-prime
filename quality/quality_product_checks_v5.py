"""V5 Central Intelligence Engine criterion callables referenced by docs/specs/v5-criteria.yaml.

Each function returns (passed: bool, evidence: str). Never raises — failure
becomes a False return with a readable reason. These run in-process under
.quality/checks.py, so keep them dependency-light (stdlib only).

Checks:
  check_intelligence_findings_endpoint → v5-05 (GET /intelligence/findings reachable)
  check_intelligence_search_endpoint   → v5-06 (GET /intelligence/search reachable)
  check_global_briefing_endpoint       → v5-07 (GET /global/briefing reachable)
  check_global_regime_endpoint         → v5-08 (GET /global/regime reachable)
  check_global_rs_heatmap_endpoint     → v5-09 (GET /global/rs-heatmap reachable)
  check_v5_no_float                    → v5-10 (no ': float' annotations in V5 code)
  check_v5_no_print                    → v5-11 (no print() calls in V5 production code)
  check_cost_ledger_budget             → v5-12 (DAILY_BUDGET_USD + BudgetExhaustedError present)
"""

from __future__ import annotations

import ast
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_BASE = "http://127.0.0.1:8010"

# V5 directories and files to scan for float/print checks
_V5_SCAN_FILES = [
    ROOT / "backend" / "services" / "intelligence.py",
    ROOT / "backend" / "services" / "embedding.py",
    ROOT / "backend" / "services" / "cost_ledger.py",
]
_V5_SCAN_DIRS = [
    ROOT / "backend" / "agents",
]


def _get_endpoint(path: str, accepted: set[int]) -> tuple[bool, str]:
    """GET the given path on BACKEND_BASE; return (passed, evidence)."""
    url = f"{BACKEND_BASE}{path}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "atlas-quality/1.0"},
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:  # noqa: BLE001
        return False, f"GET {url} unreachable: {str(exc)[:80]}"
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if status not in accepted:
        return False, f"GET {url} → {status} ({elapsed_ms}ms, expected one of {sorted(accepted)})"
    return True, f"GET {url} → {status} in {elapsed_ms}ms (endpoint reachable)"


def check_intelligence_findings_endpoint() -> tuple[bool, str]:
    """v5-05: GET /api/v1/intelligence/findings must exist (any status except 404/5xx)."""
    return _get_endpoint("/api/v1/intelligence/findings", {200, 400, 422, 501})


def check_intelligence_search_endpoint() -> tuple[bool, str]:
    """v5-06: GET /api/v1/intelligence/search must exist (any status except 404/5xx)."""
    return _get_endpoint("/api/v1/intelligence/search", {200, 400, 422, 501})


def check_global_briefing_endpoint() -> tuple[bool, str]:
    """v5-07: GET /api/v1/global/briefing must exist (any status except 404/5xx)."""
    return _get_endpoint("/api/v1/global/briefing", {200, 400, 422, 501})


def check_global_regime_endpoint() -> tuple[bool, str]:
    """v5-08: GET /api/v1/global/regime must exist (any status except 404/5xx)."""
    return _get_endpoint("/api/v1/global/regime", {200, 400, 422, 501})


def check_global_rs_heatmap_endpoint() -> tuple[bool, str]:
    """v5-09: GET /api/v1/global/rs-heatmap must exist (any status except 404/5xx)."""
    return _get_endpoint("/api/v1/global/rs-heatmap", {200, 400, 422, 501})


def _iter_py_files(directory: Path) -> list[Path]:
    """Return all .py files under directory, skipping __pycache__."""
    result: list[Path] = []
    for p in directory.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        result.append(p)
    return sorted(result)


def _has_float_annotation(tree: ast.AST) -> list[str]:
    """Return list of node descriptions where float is used as a type annotation."""
    hits: list[str] = []
    for node in ast.walk(tree):
        # AnnAssign: x: float = ...
        if isinstance(node, ast.AnnAssign):
            ann = node.annotation
            if isinstance(ann, ast.Name) and ann.id == "float":
                hits.append(f"line {node.lineno}: AnnAssign -> float")
        # Function argument annotations: def f(x: float)
        elif isinstance(node, ast.arg):
            if (
                node.annotation is not None
                and isinstance(node.annotation, ast.Name)
                and node.annotation.id == "float"
            ):
                hits.append(f"line {node.lineno}: arg annotation -> float")
        # Return annotations: def f() -> float
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ret = node.returns
            if ret is not None and isinstance(ret, ast.Name) and ret.id == "float":
                hits.append(f"line {node.lineno}: return annotation -> float")
    return hits


def _has_print_calls(tree: ast.AST) -> list[str]:
    """Return list of line descriptions where print() is called."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "print":
                hits.append(f"line {node.lineno}: print()")
    return hits


def _collect_scan_targets() -> tuple[list[Path], list[str]]:
    """Collect all V5 scan targets. Returns (targets, missing_notices)."""
    targets: list[Path] = []
    missing: list[str] = []

    for f in _V5_SCAN_FILES:
        if f.exists():
            targets.append(f)
        else:
            missing.append(str(f.relative_to(ROOT)))

    for d in _V5_SCAN_DIRS:
        if d.exists():
            targets.extend(_iter_py_files(d))
        else:
            missing.append(str(d.relative_to(ROOT)))

    return targets, missing


def check_v5_no_float() -> tuple[bool, str]:
    """v5-10: AST scan of V5 intelligence/agent code for float annotations.

    Scans:
      - backend/services/intelligence.py
      - backend/services/embedding.py
      - backend/services/cost_ledger.py
      - backend/agents/ (all .py files)

    Returns (True, evidence) if zero float annotations found.
    """
    scan_targets, missing = _collect_scan_targets()

    if not scan_targets:
        return False, f"No V5 files found to scan. Missing: {', '.join(missing)}"

    offenders: list[str] = []
    for path in scan_targets:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            return False, f"syntax error in {path.relative_to(ROOT)}: {exc}"
        except OSError as exc:
            return False, f"read error in {path.relative_to(ROOT)}: {exc}"

        hits = _has_float_annotation(tree)
        for hit in hits:
            rel = path.relative_to(ROOT)
            offenders.append(f"{rel}: {hit}")

    if offenders:
        sample = "; ".join(offenders[:3])
        return False, f"{len(offenders)} float annotation(s): {sample}"

    suffix = f" (missing: {', '.join(missing)})" if missing else ""
    return True, f"0 float annotations across {len(scan_targets)} V5 files{suffix}"


def check_v5_no_print() -> tuple[bool, str]:
    """v5-11: AST scan of V5 backend code for print() calls.

    Scans the same directories as check_v5_no_float.
    Returns (True, evidence) if zero print() calls found.
    """
    scan_targets, missing = _collect_scan_targets()

    if not scan_targets:
        return False, f"No V5 files found to scan. Missing: {', '.join(missing)}"

    offenders: list[str] = []
    for path in scan_targets:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            return False, f"syntax error in {path.relative_to(ROOT)}: {exc}"
        except OSError as exc:
            return False, f"read error in {path.relative_to(ROOT)}: {exc}"

        hits = _has_print_calls(tree)
        for hit in hits:
            rel = path.relative_to(ROOT)
            offenders.append(f"{rel}: {hit}")

    if offenders:
        sample = "; ".join(offenders[:3])
        return False, f"{len(offenders)} print() call(s): {sample}"

    suffix = f" (missing: {', '.join(missing)})" if missing else ""
    return True, f"0 print() calls across {len(scan_targets)} V5 files{suffix}"


def check_cost_ledger_budget() -> tuple[bool, str]:
    """v5-12: Verify cost_ledger.py contains DAILY_BUDGET_USD and BudgetExhaustedError.

    Uses AST parse to find ClassDef and Assign names, not regex, to avoid
    false positives from comments or string literals.
    """
    cost_ledger_path = ROOT / "backend" / "services" / "cost_ledger.py"
    if not cost_ledger_path.exists():
        return False, "backend/services/cost_ledger.py not found"

    try:
        source = cost_ledger_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(cost_ledger_path))
    except SyntaxError as exc:
        return False, f"syntax error in cost_ledger.py: {exc}"
    except OSError as exc:
        return False, f"read error in cost_ledger.py: {exc}"

    has_budget_constant = False
    has_budget_error = False

    for node in ast.walk(tree):
        # Look for DAILY_BUDGET_USD = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DAILY_BUDGET_USD":
                    has_budget_constant = True
        # Also check AnnAssign: DAILY_BUDGET_USD: Decimal = ...
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "DAILY_BUDGET_USD":
                has_budget_constant = True
        # Look for class BudgetExhaustedError(...)
        elif isinstance(node, ast.ClassDef) and node.name == "BudgetExhaustedError":
            has_budget_error = True

    evidence_parts: list[str] = []
    if has_budget_constant:
        evidence_parts.append("DAILY_BUDGET_USD found")
    else:
        evidence_parts.append("DAILY_BUDGET_USD MISSING")

    if has_budget_error:
        evidence_parts.append("BudgetExhaustedError found")
    else:
        evidence_parts.append("BudgetExhaustedError MISSING")

    passed = has_budget_constant and has_budget_error
    return passed, "; ".join(evidence_parts)
