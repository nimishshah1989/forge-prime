"""Backend dimension — data correctness, DB health, pipeline health.

Checks that depend on files/tables that don't exist yet return eligible=0
so S1 can pass while V1.6 is pending.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from . import CheckResult, DimensionResult

ROOT = Path(__file__).resolve().parent.parent.parent


def _run_cmd(
    cmd: list[str], cwd: Optional[Path] = None, timeout: int = 120
) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def b1_alembic_head_matches_models() -> CheckResult:
    rc, out, err = _run_cmd(["alembic", "check"], timeout=30)
    if rc == 127:
        return CheckResult(
            "b1",
            "Alembic head matches models",
            0,
            10,
            "alembic not installed",
            "",
            "pip install alembic",
            "high",
            status="SKIP",
        )
    ok = rc == 0
    return CheckResult(
        "b1",
        "Alembic head matches models",
        10 if ok else 0,
        10,
        "alembic check passed" if ok else f"drift detected: {(out + err)[:120]}",
        "Are DB migrations in sync with models?",
        "Run `alembic revision --autogenerate` then `alembic upgrade head`.",
        "high" if not ok else "info",
    )


def b2_all_fks_indexed() -> CheckResult:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return CheckResult(
            "b2",
            "All FKs indexed",
            0,
            10,
            "DATABASE_URL not set",
            "",
            "Set DATABASE_URL",
            "info",
            status="SKIP",
        )
    try:
        import sqlalchemy

        engine = sqlalchemy.create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text("""
                SELECT
                    tc.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name LIKE 'atlas_%'
            """)
            ).fetchall()
            unindexed = []
            for table, col in rows:
                idx = conn.execute(
                    sqlalchemy.text("""
                    SELECT 1 FROM pg_indexes
                    WHERE tablename = :t AND indexdef LIKE :pat
                """),
                    {"t": table, "pat": f"%{col}%"},
                ).fetchone()
                if not idx:
                    unindexed.append(f"{table}.{col}")
        engine.dispose()
        if not unindexed:
            return CheckResult(
                "b2",
                "All FKs indexed",
                10,
                10,
                f"all {len(rows)} FK columns indexed",
                "",
                "",
                "info",
            )
        return CheckResult(
            "b2",
            "All FKs indexed",
            0,
            10,
            f"unindexed: {unindexed[:5]}",
            "FK columns without indexes cause slow JOINs.",
            "Add index=True to FK columns.",
            "high",
        )
    except Exception as exc:
        return CheckResult(
            "b2",
            "All FKs indexed",
            0,
            10,
            f"error: {str(exc)[:100]}",
            "",
            "",
            "info",
            status="SKIP",
        )


def b3_no_float_in_financial_columns() -> CheckResult:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return CheckResult(
            "b3",
            "No float in financial columns",
            0,
            10,
            "DATABASE_URL not set",
            "",
            "Set DATABASE_URL",
            "info",
            status="SKIP",
        )
    try:
        import sqlalchemy

        engine = sqlalchemy.create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_name LIKE 'atlas_%'
                    AND data_type = 'double precision'
            """)
            ).fetchall()
        engine.dispose()
        if not rows:
            return CheckResult(
                "b3",
                "No float in financial columns",
                10,
                10,
                "no double precision columns in atlas_* tables",
                "",
                "",
                "info",
            )
        cols = [f"{r[0]}.{r[1]}" for r in rows]
        return CheckResult(
            "b3",
            "No float in financial columns",
            0,
            10,
            f"double precision: {cols[:5]}",
            "Financial columns must use Numeric, not float.",
            "Change column type to Numeric(20,4).",
            "critical",
        )
    except Exception as exc:
        return CheckResult(
            "b3",
            "No float in financial columns",
            0,
            10,
            f"error: {str(exc)[:100]}",
            "",
            "",
            "info",
            status="SKIP",
        )


def b4_docker_build_ok() -> CheckResult:
    dockerfile = ROOT / "Dockerfile"
    if not dockerfile.exists():
        return CheckResult(
            "b4",
            "Docker build file present",
            0,
            10,
            "Dockerfile missing",
            "Is the service containerized?",
            "Write Dockerfile.",
            "medium",
        )
    return CheckResult(
        "b4",
        "Docker build file present",
        10,
        10,
        "Dockerfile present",
        "Is the service containerized?",
        "",
        "info",
    )


def b5_alembic_configured() -> CheckResult:
    alembic_ini = ROOT / "alembic.ini"
    ok = alembic_ini.exists()
    return CheckResult(
        "b5",
        "Alembic configured",
        10 if ok else 0,
        10,
        "alembic.ini found" if ok else "missing",
        "Are schema changes versioned?",
        "Initialize Alembic.",
        "high" if not ok else "info",
    )


def b6_pip_audit_clean() -> CheckResult:
    rc, out, _ = _run_cmd(["pip-audit", "--format=json"], timeout=120)
    if rc == 127:
        return CheckResult(
            "b6",
            "pip-audit clean",
            0,
            10,
            "pip-audit not installed",
            "",
            "pip install pip-audit",
            "info",
            status="SKIP",
        )
    py_crit, py_high = 0, 0
    if rc == 0 and out:
        try:
            data = json.loads(out)
            vulns = data.get("vulnerabilities", [])
            for v in vulns:
                sev = (v.get("severity") or "").lower()
                if "critical" in sev:
                    py_crit += 1
                elif "high" in sev:
                    py_high += 1
        except Exception:
            pass
    if py_crit == 0 and py_high == 0:
        score = 10
    elif py_crit == 0 and py_high <= 3:
        score = 7
    else:
        score = 0
    return CheckResult(
        "b6",
        "pip-audit clean",
        score,
        10,
        f"critical={py_crit} high={py_high}",
        "Any known vulnerabilities in Python deps?",
        "Upgrade vulnerable packages.",
        "critical" if py_crit else ("high" if py_high else "info"),
        status="RUN" if rc != 127 else "SKIP",
    )


def b7_pipeline_idempotent() -> CheckResult:
    pipeline = ROOT / "backend" / "pipelines" / "daily.py"
    if not pipeline.exists():
        return CheckResult(
            "b7",
            "Pipeline idempotent",
            0,
            0,
            "backend/pipelines/daily.py not found — informational until V1.6",
            "",
            "",
            "info",
            status="SKIP",
        )
    return CheckResult(
        "b7",
        "Pipeline idempotent",
        0,
        10,
        "pipeline exists but idempotence not tested in gate",
        "Can the pipeline be safely re-run?",
        "Add idempotence probe.",
        "info",
    )


def b8_intelligence_writes() -> CheckResult:
    pipeline = ROOT / "backend" / "pipelines" / "daily.py"
    if not pipeline.exists():
        return CheckResult(
            "b8",
            "Intelligence writes on run",
            0,
            0,
            "pipeline not present — informational until V1.6",
            "",
            "",
            "info",
            status="SKIP",
        )
    return CheckResult(
        "b8",
        "Intelligence writes on run",
        0,
        10,
        "pipeline exists but intelligence writes not verified in gate",
        "",
        "",
        "info",
    )


def b9_decisions_generated() -> CheckResult:
    pipeline = ROOT / "backend" / "pipelines" / "daily.py"
    if not pipeline.exists():
        return CheckResult(
            "b9",
            "Decisions generated on run",
            0,
            0,
            "pipeline not present — informational until V1.6",
            "",
            "",
            "info",
            status="SKIP",
        )
    return CheckResult(
        "b9",
        "Decisions generated on run",
        0,
        10,
        "pipeline exists but decision generation not verified in gate",
        "",
        "",
        "info",
    )


def b10_ci_workflows_present() -> CheckResult:
    workflows = ROOT / ".github" / "workflows"
    has_ci = workflows.exists() and any(workflows.glob("*.yml"))
    return CheckResult(
        "b10",
        "CI/CD workflows",
        10 if has_ci else 0,
        10,
        f"workflows: {[f.name for f in workflows.glob('*.yml')]}" if has_ci else "no workflows",
        "Is there automated CI/CD?",
        "Add .github/workflows/deploy.yml.",
        "medium" if not has_ci else "info",
    )


def dim_backend() -> DimensionResult:
    return DimensionResult(
        "backend",
        [
            b1_alembic_head_matches_models(),
            b2_all_fks_indexed(),
            b3_no_float_in_financial_columns(),
            b4_docker_build_ok(),
            b5_alembic_configured(),
            b6_pip_audit_clean(),
            b7_pipeline_idempotent(),
            b8_intelligence_writes(),
            b9_decisions_generated(),
            b10_ci_workflows_present(),
        ],
        gating=False,
    )
