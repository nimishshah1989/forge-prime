"""Writes a wiki article after every successful chunk. Pushes to git.

Also writes failure articles (Enhancement D) when a chunk fails, so future
sessions see the anti-pattern during semantic retrieval.
"""
import json
import os
import subprocess
from pathlib import Path

import httpx

WIKI_DIR = Path.home() / ".forge" / "prime" / "wiki"
STAGING = WIKI_DIR / "staging"

PROMPT = """Write a 150-word Obsidian wiki article about this chunk.
Format:
---
title: <descriptive title>
category: patterns|anti-patterns|decisions|domain
chunk_id: <id>
created: <ISO date>
tags: [tag1, tag2]
---
# <title>
## What happened
## Key pattern
## Gotchas
## See also
[[wikilink1]], [[wikilink2]]

Be specific. 150 words max."""

FAILURE_PROMPT = """A chunk failed. Write a 150-word Obsidian wiki article
documenting WHY it failed, so future sessions avoid this pattern.

Format:
---
title: <what failed to work>
category: anti-patterns
chunk_id: <id>
created: <ISO date>
tags: [failure, <domain-tag>]
---
# <title>
## What was attempted
## Why it failed
## What to try instead
## Related
[[wikilink1]], [[wikilink2]]

Be specific. Name the actual error. 150 words max."""


def write_article(chunk_id: str, title: str, log_dir: Path) -> bool:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return False
    log = log_dir / f"{chunk_id}.log"
    if not log.exists():
        return False
    events = []
    for line in log.read_text().splitlines()[-100:]:
        try:
            e = json.loads(line)
            if e.get("kind") in ("text", "session_end"):
                events.append(e)
        except Exception:
            continue
    summary = json.dumps(events[-20:])[:2000]
    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek/deepseek-chat",
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": f"Chunk: {chunk_id} — {title}\n\n{summary}"},
                ],
            },
            timeout=30.0,
        )
        article = r.json()["choices"][0]["message"]["content"]
    except Exception:
        return False

    STAGING.mkdir(parents=True, exist_ok=True)
    (STAGING / f"{chunk_id}.md").write_text(article)
    return _commit_and_push([f"staging/{chunk_id}.md"], f"wiki: {chunk_id}")


def write_failure_article(
    chunk_id: str,
    title: str,
    log_dir: Path,
    failure_reason: str,
) -> bool:
    """Write a wiki article about a chunk failure (Enhancement D).

    Pulls context from both the per-chunk log and the failure record written
    by logs.write_failure_record. Same git-and-push flow as write_article,
    but uses the FAILURE_PROMPT and a distinct ``FAIL-<chunk_id>.md`` filename.
    """
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return False

    log = log_dir / f"{chunk_id}.log"
    failure_file = log_dir / f"{chunk_id}.failure.json"

    log_tail = ""
    if log.exists():
        try:
            lines = log.read_text().splitlines()[-30:]
            log_tail = "\n".join(lines)[:2000]
        except OSError:
            log_tail = ""

    failure_context = ""
    if failure_file.exists():
        try:
            failure_context = failure_file.read_text()[:1500]
        except OSError:
            failure_context = ""

    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek/deepseek-chat",
                "messages": [
                    {"role": "system", "content": FAILURE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Chunk: {chunk_id} — {title}\n"
                            f"Failure reason: {failure_reason}\n\n"
                            f"Log tail:\n{log_tail}\n\n"
                            f"Failure record:\n{failure_context}"
                        ),
                    },
                ],
            },
            timeout=30.0,
        )
        article = r.json()["choices"][0]["message"]["content"]
    except Exception:
        return False

    STAGING.mkdir(parents=True, exist_ok=True)
    article_path = STAGING / f"FAIL-{chunk_id}.md"
    article_path.write_text(article)
    return _commit_and_push(
        [f"staging/FAIL-{chunk_id}.md"],
        f"wiki: failure analysis for {chunk_id}",
    )


def _commit_and_push(rel_paths: list[str], message: str) -> bool:
    """Add + commit files under WIKI_DIR, push if a remote is configured.

    Returns True if the commit succeeds (with or without a remote push).
    Returns False only if the local commit itself fails — callers treat that
    as "article not persisted". Push errors are logged via warn but don't flip
    the return value: articles that committed locally are recoverable.
    """
    try:
        for rel in rel_paths:
            subprocess.run(
                ["git", "-C", str(WIKI_DIR), "add", rel],
                check=True,
                capture_output=True,
            )
        subprocess.run(
            ["git", "-C", str(WIKI_DIR), "commit", "-m", message],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False

    # Push only if a remote exists. No remote = local-only wiki, which is a
    # valid configuration (e.g. fresh install, air-gapped box).
    try:
        remotes = subprocess.run(
            ["git", "-C", str(WIKI_DIR), "remote"],
            capture_output=True,
            text=True,
            check=False,
        )
        if remotes.returncode == 0 and remotes.stdout.strip():
            subprocess.run(
                ["git", "-C", str(WIKI_DIR), "push"],
                check=False,
                capture_output=True,
            )
    except Exception:
        pass

    return True
