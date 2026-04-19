"""V6 TradingView slice criterion callables referenced by docs/specs/v6-criteria.yaml.

Each function returns (passed: bool, evidence: str). Never raises — failure
becomes a False return with a readable reason. These run in-process under
.quality/checks.py, so keep them dependency-light (stdlib only).

Checks:
  check_tv_ta_endpoint             -> v6-05
  check_tv_screener_endpoint       -> v6-06
  check_tv_fundamentals_endpoint   -> v6-07
  check_tv_ta_bulk_endpoint        -> v6-08
  check_tv_webhook_requires_secret -> v6-09
  check_sync_tv_is_404             -> v6-10
  check_watchlists_list_endpoint   -> v6-11
  check_alerts_list_endpoint       -> v6-12
  check_bridge_no_httpx            -> v6-13
  check_tradingview_screener_pinned -> v6-14
  check_v6_no_float                -> v6-15
  check_v6_no_print                -> v6-16
"""

from __future__ import annotations

import ast
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_BASE = "http://127.0.0.1:8010"

# V6 backend files to scan for float/print anti-pattern checks
_V6_SCAN_FILES = [
    ROOT / "backend" / "services" / "tv" / "bridge.py",
    ROOT / "backend" / "services" / "tv" / "cache_service.py",
    ROOT / "backend" / "models" / "alert.py",
    ROOT / "backend" / "models" / "watchlist.py",
    ROOT / "backend" / "routes" / "tv.py",
    ROOT / "backend" / "routes" / "alerts.py",
    ROOT / "backend" / "routes" / "watchlists.py",
    ROOT / "backend" / "routes" / "webhooks.py",
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
        return False, f"GET {url} -> {status} ({elapsed_ms}ms, expected one of {sorted(accepted)})"
    return True, f"GET {url} -> {status} in {elapsed_ms}ms (endpoint reachable)"


def _post_endpoint(
    path: str,
    accepted: set[int],
    data: bytes = b"{}",
    headers: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """POST the given path on BACKEND_BASE; return (passed, evidence)."""
    url = f"{BACKEND_BASE}{path}"
    h: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "atlas-quality/1.0",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, method="POST", data=data, headers=h)
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
        return False, f"POST {url} -> {status} ({elapsed_ms}ms, expected one of {sorted(accepted)})"
    return True, f"POST {url} -> {status} in {elapsed_ms}ms"


def check_tv_ta_endpoint() -> tuple[bool, str]:
    """v6-05: GET /api/tv/ta/{symbol} must exist (200/400/422/503 acceptable)."""
    return _get_endpoint("/api/tv/ta/RELIANCE", {200, 400, 422, 503})


def check_tv_screener_endpoint() -> tuple[bool, str]:
    """v6-06: GET /api/tv/screener/{symbol} must exist (200/400/422/503 acceptable)."""
    return _get_endpoint("/api/tv/screener/RELIANCE", {200, 400, 422, 503})


def check_tv_fundamentals_endpoint() -> tuple[bool, str]:
    """v6-07: GET /api/tv/fundamentals/{symbol} must exist (200/400/422/503 acceptable)."""
    return _get_endpoint("/api/tv/fundamentals/RELIANCE", {200, 400, 422, 503})


def check_tv_ta_bulk_endpoint() -> tuple[bool, str]:
    """v6-08: GET /api/tv/ta/bulk must exist and NOT return 503.

    The bulk endpoint uses cached data and must be available even when the
    TV bridge is offline. 503 is NOT acceptable here.
    """
    return _get_endpoint("/api/tv/ta/bulk?symbols=RELIANCE", {200, 400, 422})


def check_tv_webhook_requires_secret() -> tuple[bool, str]:
    """v6-09: POST /api/webhooks/tradingview without X-TV-Signature returns 403.

    Sends a valid TVWebhookPayload body but omits the X-TV-Signature header.
    The endpoint must reject it with 403 Forbidden.
    """
    body = b'{"symbol": "RELIANCE", "exchange": "NSE", "data_type": "ta_summary", "tv_payload": {}}'
    return _post_endpoint(
        "/api/webhooks/tradingview",
        accepted={403},
        data=body,
        # Intentionally no X-TV-Signature header
    )


def check_sync_tv_is_404() -> tuple[bool, str]:
    """v6-10: POST /api/v1/watchlists/{id}/sync-tv returns 404 (route removed in V6T-2)."""
    dummy_uuid = "00000000-0000-0000-0000-000000000000"
    return _post_endpoint(
        f"/api/v1/watchlists/{dummy_uuid}/sync-tv",
        accepted={404},
    )


def check_watchlists_list_endpoint() -> tuple[bool, str]:
    """v6-11: GET /api/v1/watchlists/ must return 200."""
    return _get_endpoint("/api/v1/watchlists/", {200})


def check_alerts_list_endpoint() -> tuple[bool, str]:
    """v6-12: GET /api/alerts must return 200."""
    return _get_endpoint("/api/alerts", {200})


def check_bridge_no_httpx() -> tuple[bool, str]:
    """v6-13: bridge.py must not import httpx (V6T-2 migration to asyncio.to_thread).

    Uses AST import scan for accuracy — catches both 'import httpx' and
    'from httpx import ...' patterns.
    """
    bridge_path = ROOT / "backend" / "services" / "tv" / "bridge.py"
    if not bridge_path.exists():
        return False, "backend/services/tv/bridge.py not found"

    try:
        source = bridge_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(bridge_path))
    except SyntaxError as exc:
        return False, f"syntax error in bridge.py: {exc}"
    except OSError as exc:
        return False, f"read error in bridge.py: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "httpx" or alias.name.startswith("httpx."):
                    return False, f"bridge.py imports httpx at line {node.lineno}"
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and (
                node.module == "httpx" or node.module.startswith("httpx.")
            ):
                return False, f"bridge.py imports from httpx at line {node.lineno}"

    return True, "bridge.py has no httpx imports (asyncio.to_thread bridge confirmed)"


def check_tradingview_screener_pinned() -> tuple[bool, str]:
    """v6-14: tradingview-screener must be pinned with exact version in requirements.txt."""
    req_path = ROOT / "backend" / "requirements.txt"
    if not req_path.exists():
        return False, "backend/requirements.txt not found"

    try:
        content = req_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"read error in requirements.txt: {exc}"

    pattern = re.compile(r"^tradingview-screener==(\d+\.\d+\.\d+)\s*$", re.MULTILINE)
    match = pattern.search(content)
    if match:
        return True, f"tradingview-screener=={match.group(1)} pinned in requirements.txt"
    return False, "tradingview-screener not found or not pinned with exact version (==x.y.z)"


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


def _collect_v6_scan_targets() -> tuple[list[Path], list[str]]:
    """Collect all V6 scan targets. Returns (targets, missing_notices)."""
    targets: list[Path] = []
    missing: list[str] = []

    for f in _V6_SCAN_FILES:
        if f.exists():
            targets.append(f)
        else:
            missing.append(str(f.relative_to(ROOT)))

    return targets, missing


def check_v6_no_float() -> tuple[bool, str]:
    """v6-15: AST scan of V6 backend files for float type annotations.

    Scans:
      - backend/services/tv/bridge.py
      - backend/services/tv/cache_service.py
      - backend/models/alert.py
      - backend/models/watchlist.py
      - backend/routes/tv.py
      - backend/routes/alerts.py
      - backend/routes/watchlists.py
      - backend/routes/webhooks.py

    Returns (True, evidence) if zero float annotations found.
    """
    scan_targets, missing = _collect_v6_scan_targets()

    if not scan_targets:
        return False, f"No V6 files found to scan. Missing: {', '.join(missing)}"

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
    return True, f"0 float annotations across {len(scan_targets)} V6 files{suffix}"


def check_v6_no_print() -> tuple[bool, str]:
    """v6-16: AST scan of V6 backend files for print() calls.

    Scans the same files as check_v6_no_float.
    Returns (True, evidence) if zero print() calls found.
    """
    scan_targets, missing = _collect_v6_scan_targets()

    if not scan_targets:
        return False, f"No V6 files found to scan. Missing: {', '.join(missing)}"

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
    return True, f"0 print() calls across {len(scan_targets)} V6 files{suffix}"
