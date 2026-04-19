"""Reads session_end log event, writes tokens + cost to state.db."""
import json
import sqlite3
from pathlib import Path

from .router import cost_usd


def record(chunk_id: str, model_id: str, log_dir: Path, db_path: str) -> None:
    log = log_dir / f"{chunk_id}.log"
    if not log.exists():
        return
    in_tok = out_tok = 0
    for line in log.read_text().splitlines():
        try:
            e = json.loads(line)
            if e.get("kind") == "session_end":
                u = e.get("payload", {}).get("usage", {})
                in_tok = u.get("input_tokens", 0)
                out_tok = u.get("output_tokens", 0)
                break
        except Exception:
            continue
    usd = cost_usd(model_id, in_tok, out_tok)
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        for col in [
            "input_tokens INTEGER DEFAULT 0",
            "output_tokens INTEGER DEFAULT 0",
            "estimated_cost_usd REAL DEFAULT 0.0",
            "model_used TEXT",
        ]:
            try:
                con.execute(f"ALTER TABLE chunks ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "UPDATE chunks SET input_tokens=?,output_tokens=?,estimated_cost_usd=?,model_used=? WHERE id=?",
            (in_tok, out_tok, usd, model_id, chunk_id),
        )
        con.execute("COMMIT")
    finally:
        con.close()
