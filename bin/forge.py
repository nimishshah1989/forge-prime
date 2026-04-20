#!/usr/bin/env python3
"""Forge Prime CLI — entry point for all forge commands."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import webbrowser
from pathlib import Path

FORGE_HOME = Path.home() / ".forge-prime"
FORGE_STATE = Path.home() / ".forge" / "prime"


def _load_env() -> None:
    env_file = FORGE_HOME / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _require_git_repo() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Error: not inside a git repository.", file=sys.stderr)
        sys.exit(1)
    return Path(result.stdout.strip())


def cmd_init(args: argparse.Namespace) -> None:
    repo = Path.cwd()
    project_name = args.name or repo.name

    # Create .forge/ structure
    (repo / ".forge").mkdir(exist_ok=True)
    (repo / "orchestrator").mkdir(exist_ok=True)
    (repo / ".quality").mkdir(exist_ok=True)

    # Copy constitution template
    spec_dir = Path(__file__).parent.parent
    constitution_src = spec_dir / "templates" / "constitution.md"
    constitution_dst = repo / ".forge" / "constitution.md"
    if not constitution_dst.exists() and constitution_src.exists():
        constitution_dst.write_text(constitution_src.read_text())

    # Copy CONDUCTOR.md template
    conductor_src = spec_dir / "templates" / "CONDUCTOR.md"
    conductor_dst = repo / ".forge" / "CONDUCTOR.md"
    if not conductor_dst.exists() and conductor_src.exists():
        conductor_dst.write_text(conductor_src.read_text())

    # Copy plan.yaml template
    plan_src = spec_dir / "templates" / "plan.yaml"
    plan_dst = repo / "orchestrator" / "plan.yaml"
    if not plan_dst.exists() and plan_src.exists():
        plan_dst.write_text(plan_src.read_text())

    # Copy quality engine and template
    quality_src = spec_dir / "quality"
    quality_dst = repo / ".quality"
    for f in ["engine.py", "__init__.py"]:
        src = quality_src / f
        if src.exists():
            (quality_dst / f).write_text(src.read_text())
    tmpl_dst = quality_dst / "quality.yaml"
    tmpl_src = quality_src / "templates" / "quality.yaml"
    if not tmpl_dst.exists() and tmpl_src.exists():
        tmpl_dst.write_text(tmpl_src.read_text())

    # Copy scripts
    (repo / "scripts").mkdir(exist_ok=True)
    for script_name in ["forge-ship.sh", "post-chunk.sh"]:
        src = spec_dir / "templates" / script_name
        if not src.exists():
            src = spec_dir / "scripts" / script_name
        dst = repo / "scripts" / script_name
        if not dst.exists() and src.exists():
            dst.write_text(src.read_text())
            dst.chmod(0o755)

    # Create SQLite state.db
    db_path = repo / "orchestrator" / "state.db"
    if not db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            title TEXT,
            status TEXT DEFAULT 'PENDING',
            model_alias TEXT,
            depends_on TEXT DEFAULT '[]',
            punch_list TEXT DEFAULT '[]',
            plan_version TEXT DEFAULT '1.0',
            attempts INTEGER DEFAULT 0,
            last_error TEXT,
            created_at TEXT,
            updated_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            runner_pid INTEGER,
            failure_reason TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0.0,
            model_used TEXT
        )""")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        conn.close()

    # Register project in global projects.db
    FORGE_STATE.mkdir(parents=True, exist_ok=True)
    (FORGE_STATE / "db").mkdir(exist_ok=True)
    proj_db = FORGE_STATE / "db" / "projects.db"
    conn = sqlite3.connect(str(proj_db))
    conn.execute("""CREATE TABLE IF NOT EXISTS projects (
        name TEXT PRIMARY KEY,
        repo_root TEXT,
        created_at TEXT
    )""")
    from datetime import datetime, timezone
    conn.execute(
        "INSERT OR REPLACE INTO projects VALUES (?, ?, ?)",
        (project_name, str(repo), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    print(f"Forge Prime initialized: {project_name}")
    print(f"  .forge/          — session state and conductor")
    print(f"  orchestrator/    — plan.yaml and state.db")
    print(f"  .quality/        — quality engine")
    print(f"Next: edit orchestrator/plan.yaml, then run: forge run")


def cmd_run(args: argparse.Namespace) -> None:
    repo = _require_git_repo()
    _load_env()

    # Pre-run git check
    from pathlib import Path as _P
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from runner.git_sync import check_pre_run
    ok, msg = check_pre_run(repo)
    if not ok and not args.skip_git_check:
        print(f"[forge] Git pre-run check failed: {msg}", file=sys.stderr)
        print("[forge] Fix the issue or use --skip-git-check to bypass", file=sys.stderr)
        sys.exit(1)

    # Build runner args
    runner_args = [sys.executable, "-m", "runner"]
    if args.filter:
        runner_args += ["--filter", args.filter]
    if args.once:
        runner_args.append("--once")
    if args.dry_run:
        runner_args.append("--dry-run")
    if args.retry:
        runner_args += ["--retry", args.retry]

    os.execlp(sys.executable, sys.executable, "-m", "runner",
              *runner_args[2:])


def cmd_do(args: argparse.Namespace) -> None:
    _load_env()
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from runner.classifier import classify

    task = args.description
    print(f"[forge] Classifying: {task!r}")
    result = classify(task)

    print(f"\nClassification: {result['type'].upper()}")
    print(f"Reasoning:      {result['reasoning']}")
    print(f"Est. chunks:    {result['estimated_chunks']}")
    if result.get("files_likely_touched"):
        print(f"Files likely:   {', '.join(result['files_likely_touched'])}")

    print("\nProceed? [y/N] ", end="", flush=True)
    answer = sys.stdin.readline().strip().lower()
    if answer != "y":
        print("[forge] Cancelled.")
        return

    if result["type"] == "quick":
        cmd_quick(args)
    else:
        cmd_run(args)


def cmd_quick(args: argparse.Namespace) -> None:
    _load_env()
    description = getattr(args, "description", "")
    print(f"[forge] Quick task: {description!r}")
    print("[forge] (Single-chunk run — skipping classifier)")
    # For quick tasks, create a temp chunk and run once
    repo = _require_git_repo()
    db_path = repo / "orchestrator" / "state.db"
    if not db_path.exists():
        print("[forge] No state.db found. Run: forge init", file=sys.stderr)
        sys.exit(1)
    print("[forge] Launching Claude Code session for quick task…")
    subprocess.run(["claude", "--print", description], check=False)


def cmd_ship(args: argparse.Namespace) -> None:
    repo = _require_git_repo()
    script = repo / "scripts" / "forge-ship.sh"
    if not script.exists():
        print(f"[forge] forge-ship.sh not found at {script}", file=sys.stderr)
        sys.exit(1)
    subprocess.run(["bash", str(script), args.chunk_id, args.message], check=True)


def cmd_status(args: argparse.Namespace) -> None:
    repo = _require_git_repo()
    db_path = repo / "orchestrator" / "state.db"
    if not db_path.exists():
        print("No state.db. Run: forge init")
        return
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, title, status, model_alias, model_used FROM chunks ORDER BY id").fetchall()
    conn.close()
    if not rows:
        print("No chunks in plan.")
        return
    status_icon = {"DONE": "✓", "PENDING": "○", "IN_PROGRESS": "→", "FAILED": "✗"}
    print(f"{'ID':<12} {'Status':<14} {'Model':<16} Title")
    print("─" * 70)
    for r in rows:
        icon = status_icon.get(r["status"], "?")
        model = r["model_used"] or r["model_alias"] or "—"
        print(f"{icon} {r['id']:<10} {r['status']:<14} {model:<16} {r['title'] or ''}")


def cmd_compile(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from wiki.compiler import compile_wiki
    compile_wiki()
    print("[forge] Wiki compiled.")

    # Rebuild the semantic index (Enhancement A) — best-effort.
    try:
        from runner.wiki_retriever import rebuild_index
        n = rebuild_index()
        print(f"[forge] Semantic index rebuilt ({n} articles indexed).")
    except ImportError as exc:
        print(f"[forge] Skipping semantic index (sentence-transformers missing): {exc}")
    except Exception as exc:
        print(f"[forge] Semantic index rebuild failed: {exc}")


def cmd_doctor(args: argparse.Namespace) -> None:
    checks = []

    # Python version
    v = sys.version_info
    ok = v >= (3, 11)
    checks.append(("Python 3.11+", ok, f"Python {v.major}.{v.minor}"))

    # git
    r = subprocess.run(["git", "--version"], capture_output=True, text=True)
    checks.append(("git", r.returncode == 0, r.stdout.strip()))

    # claude cli
    r = subprocess.run(["which", "claude"], capture_output=True, text=True)
    checks.append(("claude cli", r.returncode == 0, r.stdout.strip() or "not found"))

    # runner imports
    sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        import runner  # noqa: F401
        checks.append(("runner module", True, "importable"))
    except ImportError as e:
        checks.append(("runner module", False, str(e)))

    # dashboard reachable
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8099/api/projects", timeout=2)
        checks.append(("dashboard :8099", True, "reachable"))
    except Exception:
        checks.append(("dashboard :8099", False, "not running (start with: forge dashboard)"))

    # API keys
    _load_env()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    checks.append(("ANTHROPIC_API_KEY", bool(anthropic_key), "set" if anthropic_key else f"missing — edit {FORGE_HOME}/.env"))
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    checks.append(("OPENROUTER_API_KEY", bool(openrouter_key), "set" if openrouter_key else f"missing (optional: for deepseek/gemini) — edit {FORGE_HOME}/.env"))

    # Semantic index (Enhancement A)
    embed_cache = FORGE_STATE / "wiki" / ".embed-cache.json"
    if embed_cache.exists():
        try:
            import json as _json
            n = len(_json.loads(embed_cache.read_text()))
            checks.append(("wiki semantic index", True, f"{n} articles indexed"))
        except Exception as exc:
            checks.append(("wiki semantic index", False, f"cache unreadable: {exc}"))
    else:
        checks.append((
            "wiki semantic index",
            False,
            "not built — run: forge compile",
        ))

    # Guardrail hook (Enhancement B)
    guardrail_path = FORGE_STATE / "hooks" / "guardrail.sh"
    checks.append((
        "guardrail hook",
        guardrail_path.exists(),
        str(guardrail_path) if guardrail_path.exists() else "not installed — re-run install.sh",
    ))

    # Codex auto-rollback (Enhancement C) — presence of rollback handling
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    )
    if r.returncode == 0:
        ship_script = Path(r.stdout.strip()) / "scripts" / "forge-ship.sh"
        if ship_script.exists():
            ship_text = ship_script.read_text()
            has_rollback = "codex-feedback-" in ship_text and "git reset --soft" in ship_text
            checks.append((
                "codex auto-rollback",
                has_rollback,
                "configured" if has_rollback else "scripts/forge-ship.sh missing rollback logic",
            ))

    print("\n  Forge Prime — Doctor Report\n")
    all_ok = True
    for name, ok, detail in checks:
        icon = "✓" if ok else "✗"
        color = "\033[32m" if ok else "\033[31m"
        print(f"  {color}{icon}\033[0m  {name:<24} {detail}")
        if not ok:
            all_ok = False
    print()
    if all_ok:
        print("  \033[32mAll checks passed.\033[0m\n")
    else:
        print("  \033[33mSome checks failed — see above.\033[0m\n")


def cmd_logs(args: argparse.Namespace) -> None:
    repo = _require_git_repo()
    log_dir = repo / "orchestrator" / "logs"
    if not log_dir.exists():
        print("No log directory found. Run: forge run", file=sys.stderr)
        sys.exit(1)

    chunk_id = args.chunk_id
    if chunk_id:
        # Find the most recent log file for this chunk
        candidates = sorted(log_dir.glob(f"{chunk_id}*.jsonl"), reverse=True)
        if not candidates:
            candidates = sorted(log_dir.glob(f"*{chunk_id}*.jsonl"), reverse=True)
        if not candidates:
            print(f"No log file found for chunk: {chunk_id}", file=sys.stderr)
            sys.exit(1)
        log_file = candidates[0]
    else:
        # Most recent log file
        candidates = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("No log files found.", file=sys.stderr)
            sys.exit(1)
        log_file = candidates[0]

    import json as _json
    lines = log_file.read_text().splitlines()
    tail = lines[-args.tail:] if args.tail else lines
    for raw in tail:
        try:
            ev = _json.loads(raw)
            kind = ev.get("kind", "?")
            t = ev.get("t", "")[:19]
            payload = ev.get("payload", {})
            if kind == "text":
                snippet = payload.get("content", "")[:120].replace("\n", " ")
                print(f"  {t}  text       {snippet}")
            elif kind == "tool_use":
                print(f"  {t}  tool_use   {payload.get('tool', '?')}")
            elif kind == "error":
                print(f"  {t}  ERROR      {payload.get('message', '')}")
            elif kind in ("session_start", "session_end"):
                print(f"  {t}  {kind:<10} {_json.dumps(payload)[:80]}")
        except Exception:
            print(f"  {raw[:120]}")


def cmd_resume(args: argparse.Namespace) -> None:
    """Resume the most recent chunk snapshot (< 1 hour old) via --retry."""
    import json as _json
    import time as _time

    repo = _require_git_repo()
    snapshot_dir = repo / "orchestrator" / "logs" / "snapshots"
    if not snapshot_dir.exists():
        # Runner may be configured to log elsewhere; also try .forge/logs.
        snapshot_dir = repo / ".forge" / "logs" / "snapshots"
    if not snapshot_dir.exists():
        print("No snapshot directory found.", file=sys.stderr)
        sys.exit(1)

    cutoff = _time.time() - 3600  # 1 hour
    candidates = [
        p for p in snapshot_dir.glob("*.snapshot.json") if p.stat().st_mtime >= cutoff
    ]
    if not candidates:
        print("No recent snapshot found (< 1 hour old).")
        print("Use 'forge run --retry <chunk_id>' instead.")
        sys.exit(1)

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        data = _json.loads(latest.read_text())
    except Exception as exc:
        print(f"Could not parse snapshot {latest}: {exc}", file=sys.stderr)
        sys.exit(1)

    chunk_id = data.get("chunk_id")
    captured_at = data.get("captured_at", "unknown")
    if not chunk_id:
        print(f"Snapshot {latest} has no chunk_id.", file=sys.stderr)
        sys.exit(1)

    print(f"Found snapshot for {chunk_id} from {captured_at}")
    print(f"Resuming chunk {chunk_id}...")
    retry_args = argparse.Namespace(
        filter=None, once=True, dry_run=False, retry=chunk_id, skip_git_check=False
    )
    cmd_run(retry_args)


def cmd_dashboard(args: argparse.Namespace) -> None:
    port = 8099
    spec_dir = Path(__file__).parent.parent
    pid_file = FORGE_STATE / "dashboard.pid"
    log_file = FORGE_STATE / "dashboard.log"
    FORGE_STATE.mkdir(parents=True, exist_ok=True)

    # Is the server already up?
    already_running = False
    try:
        import urllib.request
        urllib.request.urlopen(f"http://localhost:{port}/api/projects", timeout=1)
        already_running = True
    except Exception:
        pass

    if not already_running:
        print(f"[forge] Starting dashboard on :{port} …")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "dashboard.app:app",
             "--host", "0.0.0.0", "--port", str(port)],
            cwd=str(spec_dir),
            stdout=open(log_file, "ab"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pid_file.write_text(str(proc.pid))
        import time
        for _ in range(20):
            try:
                import urllib.request
                urllib.request.urlopen(f"http://localhost:{port}/api/projects", timeout=0.5)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print(f"[forge] Dashboard failed to start — see {log_file}", file=sys.stderr)
            sys.exit(1)
        print(f"[forge] Dashboard running (pid {proc.pid}, log: {log_file})")

    if not getattr(args, "no_browser", False):
        webbrowser.open(f"http://localhost:{port}")
    print(f"[forge] Dashboard at http://localhost:{port}")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge Prime — autonomous engineering OS",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize project")
    p_init.add_argument("name", nargs="?", help="Project name (default: cwd name)")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="Run autonomous build loop")
    p_run.add_argument("--filter", help="Regex filter for chunk IDs")
    p_run.add_argument("--once", action="store_true", help="Run one chunk then stop")
    p_run.add_argument("--dry-run", action="store_true", help="Print what would run")
    p_run.add_argument("--retry", metavar="CHUNK_ID", help="Retry specific chunk")
    p_run.add_argument("--skip-git-check", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_do = sub.add_parser("do", help="Classify and run a task description")
    p_do.add_argument("description", help="What to build")
    p_do.set_defaults(func=cmd_do)

    p_quick = sub.add_parser("quick", help="Single-chunk task (skip classifier)")
    p_quick.add_argument("description", help="What to do")
    p_quick.set_defaults(func=cmd_quick)

    p_ship = sub.add_parser("ship", help="Ship a chunk manually")
    p_ship.add_argument("chunk_id", help="Chunk ID")
    p_ship.add_argument("message", help="Commit message")
    p_ship.set_defaults(func=cmd_ship)

    p_status = sub.add_parser("status", help="Show plan status")
    p_status.set_defaults(func=cmd_status)

    p_compile = sub.add_parser("compile", help="Compile wiki")
    p_compile.set_defaults(func=cmd_compile)

    p_logs = sub.add_parser("logs", help="Tail chunk log events")
    p_logs.add_argument("chunk_id", nargs="?", help="Chunk ID (default: most recent)")
    p_logs.add_argument("--tail", type=int, default=40, metavar="N", help="Last N lines (default: 40)")
    p_logs.set_defaults(func=cmd_logs)

    p_doctor = sub.add_parser("doctor", help="Health check")
    p_doctor.set_defaults(func=cmd_doctor)

    p_dash = sub.add_parser("dashboard", help="Start dashboard server + open browser")
    p_dash.add_argument("--no-browser", action="store_true", help="Start server, don't open browser")
    p_dash.set_defaults(func=cmd_dashboard)

    p_resume = sub.add_parser(
        "resume",
        help="Resume the most recent chunk snapshot (< 1 hour old)",
    )
    p_resume.set_defaults(func=cmd_resume)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
