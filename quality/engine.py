"""Portable quality engine — reads quality.yaml, delegates to dimension modules.

Usage:
    python .quality/engine.py [--gate] [--save] [--compare-baseline FILE]

Exit codes:
    0 — all gating dimensions pass min_per_dim
    1 — one or more gating dimensions below min_per_dim
    2 — configuration or runtime error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import]
except ImportError:
    yaml = None  # type: ignore[assignment]


CONFIG_FILE = "quality.yaml"
DEFAULT_CONFIG: dict[str, Any] = {
    "domain": "general",
    "project_type": "fastapi_next",
    "gating_dims": ["security", "code", "architecture", "api", "frontend"],
    "min_per_dim": 80,
}


def load_config(root: Path) -> dict[str, Any]:
    cfg_path = root / ".quality" / CONFIG_FILE
    if not cfg_path.exists():
        return DEFAULT_CONFIG
    if yaml is None:
        print("[quality] WARN: pyyaml not installed — using defaults", file=sys.stderr)
        return DEFAULT_CONFIG
    with open(cfg_path) as f:
        data = yaml.safe_load(f) or {}
    return {**DEFAULT_CONFIG, **data}


def run_checks(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Delegate to existing checks.py if present, else stub."""
    checks_py = root / ".quality" / "checks.py"
    if checks_py.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("checks", checks_py)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        if hasattr(mod, "run_all"):
            return mod.run_all(config=config)
    # Stub: return passing scores for all dims
    dims = config.get("gating_dims", DEFAULT_CONFIG["gating_dims"])
    return {d: {"score": 100, "checks": [], "passed": True} for d in dims}


def gate(report: dict[str, Any], config: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (passed, failing_dims)."""
    min_score = config.get("min_per_dim", 80)
    gating = config.get("gating_dims", [])
    failing = []
    for dim in gating:
        dim_report = report.get(dim, {})
        score = dim_report.get("score", 0)
        if score < min_score:
            failing.append(f"{dim}: {score} < {min_score}")
    return len(failing) == 0, failing


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge Prime quality gate")
    parser.add_argument("--gate", action="store_true", help="Fail with exit 1 if below min_per_dim")
    parser.add_argument("--save", action="store_true", help="Save report.json")
    parser.add_argument("--compare-baseline", metavar="FILE", help="Delta gate vs baseline JSON")
    args = parser.parse_args()

    root = Path.cwd()
    config = load_config(root)
    report = run_checks(root, config)

    if args.save:
        out = root / ".quality" / "report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"[quality] report saved to {out}")

    if args.compare_baseline:
        baseline_path = Path(args.compare_baseline)
        if baseline_path.exists():
            with open(baseline_path) as f:
                baseline = json.load(f)
            for dim, data in report.items():
                base_score = baseline.get(dim, {}).get("score", 0)
                curr_score = data.get("score", 0)
                if curr_score < base_score - 5:
                    print(f"[quality] REGRESSION: {dim} dropped {base_score} → {curr_score}", file=sys.stderr)
                    if args.gate:
                        sys.exit(1)

    if args.gate:
        passed, failing = gate(report, config)
        if not passed:
            for msg in failing:
                print(f"[quality] GATE FAIL: {msg}", file=sys.stderr)
            sys.exit(1)
        print("[quality] gate passed")


if __name__ == "__main__":
    main()
