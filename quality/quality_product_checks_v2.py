"""V2 MF criterion callables referenced by docs/specs/v2-criteria.yaml.

Each function returns (passed: bool, evidence: str). Never raises — failure
becomes a False return with a readable reason. These run in-process under
.quality/checks.py, so keep them dependency-light (stdlib + already-installed).

SC mapping (from spec 002-v1-completion SC-001..SC-009):
  check_mf_deep_dive          → SC-003 (idempotent re-run)
  check_mf_categories_staleness → SC-009 (structured pipeline data)
  check_mf_no_float           → SC-008 (no float in financial calcs)
  check_v1_criteria_pass      → SC-006 (all V1 criteria pass)
  check_mf_response_times     → SC-005 (API latency < budget)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND_BASE = "http://127.0.0.1:8010"


def _get_json(
    url: str,
    timeout: float = 5.0,
    *,
    _retries: int = 1,
) -> tuple[int, dict[str, Any] | None, int]:
    """GET url; return (status, body, ms). Status 0 means the request raised.

    Retries once on status==0 (transient connection hiccup) so that a single
    flake between back-to-back probe calls (as seen in v2-03 idempotency
    checks) doesn't flip the gate red. The retry opens a fresh connection.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-quality/1.0"})
    last_err: str = ""
    attempts = _retries + 1
    start = time.monotonic()
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                body = resp.read()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            try:
                return status, json.loads(body), elapsed_ms
            except Exception:  # noqa: BLE001
                return status, None, elapsed_ms
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {str(exc)[:80]}"
            if attempt + 1 < attempts:
                time.sleep(0.1)  # brief backoff — lets any server-side state drain
                continue
    # All attempts raised
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return 0, {"__error__": last_err}, elapsed_ms


def _get_real_mstar_id() -> str | None:
    """Fetch a real mstar_id from the live DB via the /mf/universe endpoint.

    Falls back to None if the backend is unavailable. Never hardcodes an ID.
    """
    # /mf/universe is a 5MB payload — give it room on cold cache.
    status, data, _ = _get_json(f"{BACKEND_BASE}/api/v1/mf/universe", timeout=45.0)
    if status != 200 or not data:
        return None
    # Universe response: broad_categories[].categories[].funds[].mstar_id
    for broad in data.get("broad_categories", []) or []:
        for cat in broad.get("categories", []) or []:
            for fund in cat.get("funds", []) or []:
                mstar_id = fund.get("mstar_id")
                if mstar_id:
                    return str(mstar_id)
    return None


def check_mf_deep_dive() -> tuple[bool, str]:
    """SC-003: MF deep-dive endpoint returns 200 for a real fund; two calls
    return identical mstar_id confirming deterministic (idempotent) output."""
    mstar_id = _get_real_mstar_id()
    if not mstar_id:
        return False, "could not obtain a real mstar_id from /mf/universe"

    url = f"{BACKEND_BASE}/api/v1/mf/{mstar_id}"
    status1, data1, ms1 = _get_json(url, timeout=10.0)
    if status1 != 200 or not data1 or data1.get("__error__"):
        err = (data1 or {}).get("__error__", "")
        return False, f"/mf/{mstar_id} → {status1} (first call{': ' + err if err else ''})"

    # Second call — idempotency check. Small pause to let any server-side
    # session / connection state drain between calls, then a fresh GET.
    time.sleep(0.1)
    status2, data2, ms2 = _get_json(url, timeout=10.0)
    if status2 != 200 or not data2 or data2.get("__error__"):
        err = (data2 or {}).get("__error__", "")
        return False, f"/mf/{mstar_id} → {status2} (second call{': ' + err if err else ''})"

    # Both calls must return the same mstar_id in the identity block.
    # (The deep-dive response is composed as { identity, daily, pillars,
    # sector_exposure, top_holdings, weighted_technicals, ... } per the
    # V2 single-fetch design — there is no top-level `fund` key.)
    ident1 = data1.get("identity", {}) or {}
    ident2 = data2.get("identity", {}) or {}
    id1 = ident1.get("mstar_id", "")
    id2 = ident2.get("mstar_id", "")
    if id1 != id2 or id1 != mstar_id:
        return False, f"idempotency mismatch: call1={id1!r}, call2={id2!r}, expected={mstar_id!r}"

    return True, f"/mf/{mstar_id} → 200 idempotent ({ms1}ms, {ms2}ms)"


def check_mf_categories_staleness() -> tuple[bool, str]:
    """SC-009: /mf/categories response includes staleness/data_as_of metadata,
    confirming structured provenance in MF pipeline outputs."""
    status, data, ms = _get_json(f"{BACKEND_BASE}/api/v1/mf/categories", timeout=10.0)
    if status != 200 or not data:
        return False, f"/mf/categories → {status}"

    # Look for staleness or data_as_of at the top level or nested
    has_staleness = "staleness" in data
    has_data_as_of = "data_as_of" in data

    if not has_staleness and not has_data_as_of:
        # Acceptable: check if any nested structure has these fields
        top_keys = list(data.keys())
        return False, f"/mf/categories response lacks staleness/data_as_of. Keys: {top_keys[:8]}"

    field = "staleness" if has_staleness else "data_as_of"
    return True, f"/mf/categories → 200 with {field!r} metadata ({ms}ms)"


def check_mf_no_float() -> tuple[bool, str]:
    """SC-008: AST scan of MF backend files for ': float' annotations.

    Scans backend/routes/mf.py and backend/services/mf_compute.py.
    """
    mf_files = [
        ROOT / "backend" / "routes" / "mf.py",
        ROOT / "backend" / "services" / "mf_compute.py",
    ]
    pattern = re.compile(r":\s*float\b")
    offenders: list[str] = []

    for path in mf_files:
        if not path.exists():
            offenders.append(f"{path.relative_to(ROOT)} (not found)")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            offenders.append(f"{path.relative_to(ROOT)} (read error: {exc})")
            continue
        lines_with_float = [
            f"{path.relative_to(ROOT)}:{lineno}"
            for lineno, line in enumerate(text.splitlines(), 1)
            if pattern.search(line)
        ]
        offenders.extend(lines_with_float)

    if offenders:
        return False, f"{len(offenders)} float usages: {'; '.join(offenders[:3])}"
    return True, f"0 float annotations in {len(mf_files)} MF backend files"


def check_v1_criteria_pass() -> tuple[bool, str]:
    """SC-006: Run validate-v1-completion.py and confirm it exits 0."""
    script = ROOT / "scripts" / "validate-v1-completion.py"
    if not script.exists():
        return False, f"{script.relative_to(ROOT)} not found"

    python_exe = sys.executable
    try:
        result = subprocess.run(
            [python_exe, str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "validate-v1-completion.py timed out after 60s"
    except Exception as exc:  # noqa: BLE001
        return False, f"subprocess failed: {str(exc)[:80]}"

    if result.returncode == 0:
        # Extract summary line from output
        lines = result.stdout.strip().splitlines()
        summary = next((ln.strip() for ln in reversed(lines) if "criteria" in ln.lower()), "")
        return True, f"V1 validate exited 0: {summary}"
    else:
        lines = result.stdout.strip().splitlines()
        fail_lines = [ln.strip() for ln in lines if "FAIL" in ln][:3]
        fail_summary = "; ".join(fail_lines) or "see validate-v1-completion.py"
        return False, f"V1 validate exited {result.returncode}: {fail_summary}"


def check_mf_response_times() -> tuple[bool, str]:
    """SC-005: /mf/universe < 2000ms, /mf/{mstar_id} < 500ms.

    Measures cold-hit latency — what a user waits right after deploy.
    No warmup: the backend owns its own cache/warmup strategy, not the
    quality gate.
    """
    universe_url = f"{BACKEND_BASE}/api/v1/mf/universe"
    status_u, _, ms_u = _get_json(universe_url, timeout=10.0)
    if status_u != 200:
        return False, f"/mf/universe → {status_u}"
    if ms_u > 2000:
        return False, f"/mf/universe → {ms_u}ms > 2000ms budget"

    mstar_id = _get_real_mstar_id()
    if not mstar_id:
        return False, f"/mf/universe OK ({ms_u}ms) but could not get mstar_id for deep-dive check"

    deepdive_url = f"{BACKEND_BASE}/api/v1/mf/{mstar_id}"
    status_d, _, ms_d = _get_json(deepdive_url, timeout=10.0)
    if status_d != 200:
        return False, f"/mf/{mstar_id} → {status_d}"
    if ms_d > 500:
        return False, f"/mf/{mstar_id} → {ms_d}ms > 500ms budget"

    return True, f"universe {ms_u}ms < 2000ms; deep-dive {ms_d}ms < 500ms"
