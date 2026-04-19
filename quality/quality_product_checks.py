"""V1 criterion callables referenced by docs/specs/v1-criteria.yaml.

Each function returns (passed: bool, evidence: str). Never raises — failure
becomes a False return with a readable reason. These run in-process under
.quality/checks.py, so keep them dependency-light (stdlib + already-installed).
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND_BASE = "http://127.0.0.1:8010"


def _get_json(url: str, timeout: float = 5.0) -> tuple[int, dict[str, Any] | None, int]:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-quality/1.0"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read()
    except Exception:  # noqa: BLE001
        return 0, None, int((time.monotonic() - start) * 1000)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    try:
        return status, json.loads(body), elapsed_ms
    except Exception:  # noqa: BLE001
        return status, None, elapsed_ms


def check_sectors_shape() -> tuple[bool, str]:
    status, data, ms = _get_json(f"{BACKEND_BASE}/api/v1/stocks/sectors")
    if status != 200 or not data:
        return False, f"/sectors → {status}"
    sectors = data.get("sectors", [])
    n = len(sectors)
    if n != 31:
        return False, f"expected 31 sectors, got {n}"
    if not sectors:
        return False, "no sectors returned"
    # Every row has a 'sector' label + metric columns. Require ≥22 metrics.
    first = sectors[0]
    metric_keys = [k for k in first if k != "sector"]
    if len(metric_keys) < 22:
        return False, f"sector row has {len(metric_keys)} metrics, need 22"
    return True, f"31 sectors × {len(metric_keys)} metrics ({ms}ms)"


def check_query_endpoint() -> tuple[bool, str]:
    url = f"{BACKEND_BASE}/api/v1/query"
    payload = json.dumps(
        {"entity": "equity", "fields": ["symbol", "rs_composite"], "filters": [], "limit": 1}
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "atlas-quality/1.0"},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
            resp.read(1024)
    except Exception as exc:  # noqa: BLE001
        return False, f"POST /query failed: {str(exc)[:80]}"
    ms = int((time.monotonic() - start) * 1000)
    if status != 200:
        return False, f"POST /query → {status}"
    return True, f"POST /query → 200 ({ms}ms)"


def check_fm_flow_files() -> tuple[bool, str]:
    required = [
        "frontend/src/app/page.tsx",
        "frontend/src/components/DeepDivePanel.tsx",
    ]
    missing = [p for p in required if not (ROOT / p).exists()]
    if missing:
        return False, f"missing: {', '.join(missing)}"
    return True, f"FM flow files present ({len(required)})"


def check_decisions_endpoint() -> tuple[bool, str]:
    status, data, ms = _get_json(f"{BACKEND_BASE}/api/v1/decisions")
    if status != 200:
        return False, f"/decisions → {status}"
    route_file = ROOT / "backend" / "routes" / "decisions.py"
    if not route_file.exists():
        return False, "backend/routes/decisions.py missing"
    return True, f"/decisions → 200, routes/decisions.py present ({ms}ms)"


def check_sector_stock_count_sum() -> tuple[bool, str]:
    status, data, ms = _get_json(f"{BACKEND_BASE}/api/v1/stocks/sectors")
    if status != 200 or not data:
        return False, f"/sectors → {status}"
    total = 0
    for s in data.get("sectors", []):
        try:
            total += int(s.get("stock_count", 0) or 0)
        except (TypeError, ValueError):
            continue
    # Universe fluctuates as corporate actions / NSE additions land. Tolerance
    # kept wide (2300–2900) — §24.3 says "~2,700" as a ballpark, not a gate.
    if not (2300 <= total <= 2900):
        return False, f"sector stock_count sum = {total}, expected ~2,700 (2300–2900)"
    return True, f"sector stock_count sum = {total} ({ms}ms)"


def check_rs_momentum_present() -> tuple[bool, str]:
    status, data, ms = _get_json(f"{BACKEND_BASE}/api/v1/stocks/RELIANCE")
    if status != 200 or not data:
        return False, f"/stocks/RELIANCE → {status}"
    stock = data.get("stock", {}) if isinstance(data, dict) else {}
    # rs_momentum may live nested; flatten the first level.
    seen: list[str] = []

    def walk(obj: dict[str, Any], path: str = "") -> float | None:
        for k, v in obj.items():
            full = f"{path}.{k}" if path else k
            if k == "rs_momentum":
                seen.append(full)
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None
            if isinstance(v, dict):
                r = walk(v, full)
                if r is not None:
                    return r
        return None

    value = walk(stock)
    if not seen:
        return False, "rs_momentum field not present on /stocks/RELIANCE"
    if value is None:
        return False, f"rs_momentum at {seen[0]} is null/non-numeric"
    return True, f"rs_momentum={value} at {seen[0]} ({ms}ms)"


def check_pct_above_200dma_bounds() -> tuple[bool, str]:
    status, data, ms = _get_json(f"{BACKEND_BASE}/api/v1/stocks/sectors")
    if status != 200 or not data:
        return False, f"/sectors → {status}"
    sectors = data.get("sectors", [])
    n = 0
    bad: list[str] = []
    for s in sectors:
        v = s.get("pct_above_200dma")
        if v is None:
            bad.append(f"{s.get('sector', '?')}=null")
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            bad.append(f"{s.get('sector', '?')}={v}")
            continue
        if not (0 <= f <= 100):
            bad.append(f"{s.get('sector', '?')}={f}")
            continue
        n += 1
    if bad:
        return False, f"{len(bad)} sectors out of bounds: {', '.join(bad[:3])}"
    return True, f"{n}/{len(sectors)} sectors in [0,100] ({ms}ms)"


def check_no_float_in_finance() -> tuple[bool, str]:
    """Walk backend/ and flag any `: float` annotations.

    Mirrors architecture check 3.4; kept here so the product dim is
    self-contained and doesn't depend on architecture running first.
    """
    backend = ROOT / "backend"
    if not backend.exists():
        return False, "backend/ not found"
    pattern = re.compile(r":\s*float\b")
    offenders: list[str] = []
    for py in backend.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(text):
            offenders.append(str(py.relative_to(ROOT)))
    if offenders:
        return False, f"{len(offenders)} files use float: {offenders[0]}"
    return True, "0 files use float in backend/"


def check_response_time_budgets() -> tuple[bool, str]:
    targets = [
        (f"{BACKEND_BASE}/api/v1/stocks/universe", 2000),
        (f"{BACKEND_BASE}/api/v1/stocks/RELIANCE", 500),
    ]
    for url, budget in targets:
        status, _, ms = _get_json(url, timeout=max(5, budget / 1000 * 2))
        if status != 200:
            return False, f"{url} → {status}"
        if ms > budget:
            return False, f"{url} → {ms}ms > {budget}ms"
    return True, "universe < 2000ms and deep-dive < 500ms"
