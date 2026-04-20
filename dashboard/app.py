"""Forge Prime Dashboard — FastAPI, port 8099, always running.

Reads live from:
  - orchestrator/state.db per registered project
  - ~/.forge/prime/wiki/ for article metadata
  - git status per project (live subprocess calls)
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Forge Prime Dashboard", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
WIKI_DIR = Path.home() / ".forge" / "prime" / "wiki"
PROJECTS_DB = Path.home() / ".forge" / "prime" / "db" / "projects.db"


# ---------------------------------------------------------------------------
# Projects registry
# ---------------------------------------------------------------------------

def _get_projects() -> list[dict[str, Any]]:
    if not PROJECTS_DB.exists():
        return []
    conn = sqlite3.connect(str(PROJECTS_DB), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _get_project_db(name: str) -> Optional[str]:
    projects = _get_projects()
    for p in projects:
        if p["name"] == name:
            db = Path(p["repo_root"]) / "orchestrator" / "state.db"
            if db.exists():
                return str(db)
    return None


# ---------------------------------------------------------------------------
# API routes — /api/projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    projects = _get_projects()
    result = []
    for p in projects:
        db_path = Path(p["repo_root"]) / "orchestrator" / "state.db"
        chunks_done = chunks_total = 0
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path), isolation_level=None)
                row = conn.execute("SELECT COUNT(*) FROM chunks WHERE status='DONE'").fetchone()
                chunks_done = row[0] if row else 0
                row2 = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                chunks_total = row2[0] if row2 else 0
                conn.close()
            except sqlite3.Error:
                pass
        git_ok = _git_status_clean(p["repo_root"])
        result.append({
            "name": p["name"],
            "repo_root": p["repo_root"],
            "chunks_done": chunks_done,
            "chunks_total": chunks_total,
            "git_clean": git_ok,
        })
    return result


# ---------------------------------------------------------------------------
# API routes — /api/chunks
# ---------------------------------------------------------------------------

@app.get("/api/chunks/{project_name}")
def list_chunks(project_name: str) -> list[dict[str, Any]]:
    db_path = _get_project_db(project_name)
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM chunks ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


@app.get("/api/chunk/{chunk_id}")
def chunk_detail(chunk_id: str) -> dict[str, Any]:
    projects = _get_projects()
    for p in projects:
        db_path = Path(p["repo_root"]) / "orchestrator" / "state.db"
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
            conn.close()
            if row:
                return dict(row)
        except sqlite3.Error:
            continue
    raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")


# ---------------------------------------------------------------------------
# API routes — /api/wiki
# ---------------------------------------------------------------------------

@app.get("/api/wiki/articles")
def list_wiki_articles() -> list[dict[str, Any]]:
    articles = []
    for category in ("patterns", "anti-patterns", "decisions", "domain"):
        cat_dir = WIKI_DIR / "articles" / category
        if not cat_dir.exists():
            continue
        for f in cat_dir.glob("*.md"):
            articles.append({
                "title": f.stem.replace("-", " ").title(),
                "category": category,
                "filename": f.name,
                "size": f.stat().st_size,
            })
    staging = WIKI_DIR / "staging"
    if staging.exists():
        for f in staging.glob("*.md"):
            articles.append({
                "title": f.stem,
                "category": "staging",
                "filename": f.name,
                "size": f.stat().st_size,
            })
    return articles


@app.get("/api/wiki/index")
def wiki_index() -> dict[str, Any]:
    index_path = WIKI_DIR / "index.md"
    content = index_path.read_text() if index_path.exists() else ""
    article_count = len(list_wiki_articles())
    return {"content": content, "article_count": article_count}


@app.get("/api/wiki/article/{category}/{filename}")
def wiki_article(category: str, filename: str) -> str:
    # Sanitise — no path traversal
    if ".." in category or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid path")
    if category == "staging":
        path = WIKI_DIR / "staging" / filename
    else:
        path = WIKI_DIR / "articles" / category / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Article not found")
    return path.read_text()


# ---------------------------------------------------------------------------
# API routes — /api/wiki/retrievals (Enhancement F)
# ---------------------------------------------------------------------------

@app.get("/api/wiki/retrievals")
def wiki_retrievals() -> list[dict[str, Any]]:
    """Return articles ranked by cross-project retrieval count.

    Aggregates the ``wiki_retrievals`` table (written by the runner's
    semantic retriever) across every registered project's state.db. Articles
    that get retrieved often are earning their keep; articles at zero are
    candidates for archival.
    """
    totals: dict[str, int] = {}
    for p in _get_projects():
        db_path = Path(p["repo_root"]) / "orchestrator" / "state.db"
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            # The table may not exist yet for older projects — skip silently.
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_retrievals'"
            ).fetchone()
            if not exists:
                conn.close()
                continue
            rows = conn.execute(
                "SELECT article_path, COUNT(*) FROM wiki_retrievals "
                "GROUP BY article_path"
            ).fetchall()
            conn.close()
            for article_path, count in rows:
                totals[article_path] = totals.get(article_path, 0) + int(count or 0)
        except sqlite3.Error:
            continue

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{"path": path, "retrievals": count} for path, count in ranked[:20]]


# ---------------------------------------------------------------------------
# API routes — /api/models
# ---------------------------------------------------------------------------

@app.get("/api/models")
def model_usage() -> dict[str, Any]:
    """Aggregate token/cost usage across all projects."""
    totals: dict[str, dict[str, Any]] = {}
    for p in _get_projects():
        db_path = Path(p["repo_root"]) / "orchestrator" / "state.db"
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT model_used, SUM(input_tokens) as in_tok, "
                "SUM(output_tokens) as out_tok, SUM(estimated_cost_usd) as cost "
                "FROM chunks WHERE model_used IS NOT NULL GROUP BY model_used"
            ).fetchall()
            conn.close()
            for row in rows:
                model = row["model_used"] or "unknown"
                if model not in totals:
                    totals[model] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
                totals[model]["input_tokens"] += row["in_tok"] or 0
                totals[model]["output_tokens"] += row["out_tok"] or 0
                totals[model]["cost_usd"] += row["cost"] or 0.0
        except sqlite3.Error:
            continue
    return totals


# ---------------------------------------------------------------------------
# API routes — /api/git_status
# ---------------------------------------------------------------------------

@app.get("/api/git_status/{project_name}")
def git_status(project_name: str) -> dict[str, Any]:
    projects = _get_projects()
    for p in projects:
        if p["name"] == project_name:
            repo = p["repo_root"]
            clean = _git_status_clean(repo)
            pushed = _git_pushed(repo)
            branch = _git_branch(repo)
            return {"clean": clean, "pushed": pushed, "branch": branch, "repo": repo}
    raise HTTPException(status_code=404, detail=f"Project {project_name} not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_status_clean(repo: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and not r.stdout.strip()
    except Exception:
        return False


def _git_pushed(repo: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", repo, "log", "origin/main..HEAD", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and not r.stdout.strip()
    except Exception:
        return False


def _git_branch(repo: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", repo, "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8099, reload=False)
