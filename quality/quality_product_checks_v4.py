"""V4 Portfolio Management criterion callables referenced by docs/specs/v4-criteria.yaml.

Each function returns (passed: bool, evidence: str). Never raises — failure
becomes a False return with a readable reason. These run in-process under
.quality/checks.py, so keep them dependency-light (stdlib only).

Checks:
  check_portfolio_create_endpoint → v4-03 (POST /portfolio/create reachable)
  check_portfolio_no_float        → v4-04 (no ': float' annotations in portfolio code)
  check_portfolio_no_print        → v4-05 (no print() calls in portfolio services/routes)
"""

from __future__ import annotations

import ast
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_BASE = "http://127.0.0.1:8010"


def check_portfolio_create_endpoint() -> tuple[bool, str]:
    """v4-03: POST /api/v1/portfolio/create must exist (any status except 404/5xx).

    The native http_contract handler is GET-only, so this callable POSTs a
    minimal shell payload. Accepts 200/201 (created), 400/422 (validation
    rejected), 501 (stub). 404 or 5xx = failure.
    """
    url = f"{BACKEND_BASE}/api/v1/portfolio/create"
    payload = {
        "name": "atlas-quality-probe",
        "portfolio_type": "manual",
        "owner_type": "retail",
        "holdings": [],
    }
    accepted = {200, 201, 400, 422, 501}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "atlas-quality/1.0"},
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:  # noqa: BLE001
        return False, f"POST {url} unreachable: {str(exc)[:80]}"
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if status not in accepted:
        return False, f"POST {url} → {status} ({elapsed_ms}ms, expected one of {sorted(accepted)})"
    return True, f"POST {url} → {status} in {elapsed_ms}ms (endpoint reachable)"


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


def check_portfolio_no_float() -> tuple[bool, str]:
    """v4-04: AST scan of portfolio model, routes, and services for float annotations.

    Scans backend/models/portfolio.py, backend/routes/portfolio.py, and all .py
    files in backend/services/portfolio/. Returns (True, evidence) if zero float
    annotations found.
    """
    scan_targets: list[Path] = []

    model_file = ROOT / "backend" / "models" / "portfolio.py"
    if model_file.exists():
        scan_targets.append(model_file)
    else:
        return False, "backend/models/portfolio.py not found"

    route_file = ROOT / "backend" / "routes" / "portfolio.py"
    if route_file.exists():
        scan_targets.append(route_file)

    services_dir = ROOT / "backend" / "services" / "portfolio"
    if services_dir.exists():
        scan_targets.extend(_iter_py_files(services_dir))

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

    return True, f"0 float annotations across {len(scan_targets)} portfolio files"


def check_portfolio_no_print() -> tuple[bool, str]:
    """v4-05: AST scan of portfolio routes and services for print() calls.

    Returns (True, evidence) if zero print() calls found in production code.
    """
    scan_targets: list[Path] = []

    route_file = ROOT / "backend" / "routes" / "portfolio.py"
    if route_file.exists():
        scan_targets.append(route_file)

    services_dir = ROOT / "backend" / "services" / "portfolio"
    if services_dir.exists():
        scan_targets.extend(_iter_py_files(services_dir))

    if not scan_targets:
        return False, "No portfolio route or service files found"

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

    return True, f"0 print() calls across {len(scan_targets)} portfolio files"
