"""Writes a wiki article after every successful chunk. Pushes to git."""
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
    try:
        subprocess.run(["git", "-C", str(WIKI_DIR), "add", f"staging/{chunk_id}.md"], check=True)
        subprocess.run(
            ["git", "-C", str(WIKI_DIR), "commit", "-m", f"wiki: {chunk_id}"], check=True
        )
        subprocess.run(["git", "-C", str(WIKI_DIR), "push"], check=True)
        return True
    except Exception:
        return False
