"""Pre-run and post-chunk git sync checks."""
import subprocess
from pathlib import Path


def check_pre_run(repo: Path) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    )
    if r.stdout.strip():
        n = len(r.stdout.strip().splitlines())
        return False, f"{n} uncommitted file(s). Commit or stash before running."
    r2 = subprocess.run(
        ["git", "-C", str(repo), "log", "origin/main..HEAD", "--oneline"],
        capture_output=True, text=True, timeout=10,
    )
    if r2.stdout.strip():
        n = len(r2.stdout.strip().splitlines())
        return False, f"{n} unpushed commit(s). Push first: git push"
    return True, "clean"


def check_post_chunk(repo: Path) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", "-C", str(repo), "log", "origin/main..HEAD", "--oneline"],
        capture_output=True, text=True, timeout=10,
    )
    if r.stdout.strip():
        return False, "chunk committed but not pushed to origin"
    return True, "pushed"
