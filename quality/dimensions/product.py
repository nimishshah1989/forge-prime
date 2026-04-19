"""Product dimension — V1 completion + API design standard.

Reads two YAML criteria files:
  - docs/specs/v1-criteria.yaml — V1 product slice completion (§24.3)
  - docs/specs/api-standard-criteria.yaml — cross-cutting API design
    standard (§17 UQL + §18 Include + §20 Principles). V2-UQL-AGG flipped
    all six green; promoting them into the product dim makes them
    standing, not one-shot.

Each criterion becomes one CheckResult. Product dim is gating once the
v1-criteria file loads cleanly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable

from . import CheckResult, DimensionResult
from .check_types import dispatch

ROOT = Path(__file__).resolve().parent.parent.parent
CRITERIA_PATH = ROOT / "docs" / "specs" / "v1-criteria.yaml"
V2_CRITERIA_PATH = ROOT / "docs" / "specs" / "v2-criteria.yaml"
V3_CRITERIA_PATH = ROOT / "docs" / "specs" / "v3-criteria.yaml"
V4_CRITERIA_PATH = ROOT / "docs" / "specs" / "v4-criteria.yaml"
V5_CRITERIA_PATH = ROOT / "docs" / "specs" / "v5-criteria.yaml"
V6_CRITERIA_PATH = ROOT / "docs" / "specs" / "v6-criteria.yaml"
SCHEMA_PATH = ROOT / "docs" / "specs" / "v1-criteria.schema.json"
API_STANDARD_PATH = ROOT / "docs" / "specs" / "api-standard-criteria.yaml"
API_STANDARD_SCRIPT = ROOT / "scripts" / "check-api-standard.py"


def _skip(reason: str) -> DimensionResult:
    return DimensionResult(
        "product",
        [
            CheckResult(
                "p0",
                "V1 criteria file",
                0,
                0,
                reason,
                "Is the V1 criteria YAML wired into the product dim?",
                "Fix docs/specs/v1-criteria.yaml or the product dim loader.",
                "info",
                status="SKIP",
            ),
        ],
        gating=False,
    )


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return None


def _validate(data: dict[str, Any]) -> str | None:
    """Lightweight schema validation. Returns None on success, else reason."""
    import json as _json

    if not isinstance(data, dict):
        return "criteria file is not a mapping"
    for required in ("version", "slice", "source", "criteria"):
        if required not in data:
            return f"missing top-level key: {required}"
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return "criteria list is empty"
    # If jsonschema is installed, do a full validation pass. Otherwise fall
    # back to the cheap required-key check above.
    try:
        import jsonschema
    except ImportError:
        return None
    if not SCHEMA_PATH.exists():
        return None
    try:
        schema = _json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(data, schema)
    except Exception as exc:  # noqa: BLE001
        return f"schema validation failed: {str(exc)[:120]}"
    return None


def _load_api_standard_probes() -> dict[str, Callable[[dict[str, Any]], tuple[bool, str]]] | None:
    """Import scripts/check-api-standard.py as a module (hyphened filename
    blocks a normal import) and return its PROBES map."""
    if not API_STANDARD_SCRIPT.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "atlas_check_api_standard", API_STANDARD_SCRIPT
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        return None
    probes = getattr(mod, "PROBES", None)
    return probes if isinstance(probes, dict) else None


def _api_standard_checks() -> list[CheckResult]:
    """Promote api-standard-criteria.yaml into the product dim. Each
    criterion contributes one CheckResult. Skips silently if the file or
    the probe harness is unavailable — v1-criteria is still the gate."""
    if not API_STANDARD_PATH.exists():
        return []
    data = _load_yaml(API_STANDARD_PATH)
    if data is None or not isinstance(data.get("criteria"), list):
        return []
    probes = _load_api_standard_probes()
    if probes is None:
        return []

    out: list[CheckResult] = []
    for criterion in data["criteria"]:
        cid = criterion["id"]
        title = criterion["title"]
        severity = criterion.get("severity", "high")
        probe = criterion.get("probe", {}) or {}
        fn = probes.get(probe.get("type", ""))
        if fn is None:
            passed, evidence = False, f"unknown probe type {probe.get('type')!r}"
        else:
            try:
                passed, evidence = fn(probe)
            except Exception as exc:  # noqa: BLE001
                passed, evidence = False, f"probe raised: {str(exc)[:120]}"
        out.append(
            CheckResult(
                cid,
                title,
                10 if passed else 0,
                10,
                evidence,
                criterion.get("description", ""),
                f"See {criterion.get('source_spec_section', '§17')} for intent.",
                "info" if passed else severity,
            )
        )
    return out


def _extra_criteria_checks(path: Path) -> list[CheckResult]:
    """Load an additional criteria YAML and dispatch its checks."""
    if not path.exists():
        return []
    data = _load_yaml(path)
    if data is None or not isinstance(data.get("criteria"), list):
        return []
    out: list[CheckResult] = []
    for criterion in data["criteria"]:
        cid = criterion["id"]
        title = criterion["title"]
        severity = criterion.get("severity", "medium")
        check_spec = criterion["check"]
        passed, evidence = dispatch(check_spec)
        out.append(
            CheckResult(
                cid,
                title,
                10 if passed else 0,
                10,
                evidence,
                criterion.get("description", ""),
                f"See {criterion.get('source_spec_section', '§8')} for intent.",
                "info" if passed else severity,
            )
        )
    return out


def dim_product() -> DimensionResult:
    if not CRITERIA_PATH.exists():
        return _skip(f"{CRITERIA_PATH.relative_to(ROOT)} not found")

    data = _load_yaml(CRITERIA_PATH)
    if data is None:
        return _skip("could not parse v1-criteria.yaml (pyyaml missing or invalid)")

    err = _validate(data)
    if err:
        return _skip(err)

    checks: list[CheckResult] = []
    for criterion in data["criteria"]:
        cid = criterion["id"]
        title = criterion["title"]
        severity = criterion.get("severity", "medium")
        check_spec = criterion["check"]
        passed, evidence = dispatch(check_spec)
        checks.append(
            CheckResult(
                cid,
                title,
                10 if passed else 0,
                10,
                evidence,
                criterion.get("description", ""),
                f"See {criterion.get('source_spec_section', '§24.3')} for intent.",
                "info" if passed else severity,
            )
        )

    checks.extend(_api_standard_checks())
    checks.extend(_extra_criteria_checks(V2_CRITERIA_PATH))
    checks.extend(_extra_criteria_checks(V3_CRITERIA_PATH))
    checks.extend(_extra_criteria_checks(V4_CRITERIA_PATH))
    checks.extend(_extra_criteria_checks(V5_CRITERIA_PATH))
    checks.extend(_extra_criteria_checks(V6_CRITERIA_PATH))

    return DimensionResult("product", checks, gating=True)
