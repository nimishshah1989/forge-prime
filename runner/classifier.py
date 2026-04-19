"""Classifies task descriptions as QUICK/FEATURE/MILESTONE via free Gemini call."""
import json
import os

import httpx

PROMPT = """Classify this dev task as exactly one of:
QUICK: single change, ≤5 files, ≤2h, no new architecture
FEATURE: 1-3 chunks, needs spec, ≤1 day
MILESTONE: 3+ chunks, needs PRD and architecture review, multi-day

Return JSON only: {"type":"quick|feature|milestone","reasoning":"one sentence",
"estimated_chunks":N,"files_likely_touched":["list"]}"""


def classify(task: str) -> dict:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {
            "type": "feature",
            "reasoning": "no OpenRouter key — defaulting to feature",
            "estimated_chunks": 2,
            "files_likely_touched": [],
        }
    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "google/gemini-2.0-flash-exp:free",
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": task},
                ],
            },
            timeout=15.0,
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown code fence if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        return {
            "type": "feature",
            "reasoning": f"classifier error: {e}",
            "estimated_chunks": 2,
            "files_likely_touched": [],
        }
