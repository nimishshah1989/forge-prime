# Quality Standards — Source Snapshot

This directory holds a **frozen copy** of the canonical JIP quality standards
used by ATLAS. The canonical source is the `jip-command-center` repo.

## Source

- **Upstream:** https://github.com/nimishshah1989/jip-command-center
- **Path:** `QUALITY-STANDARDS.md`
- **Raw URL:** https://raw.githubusercontent.com/nimishshah1989/jip-command-center/main/QUALITY-STANDARDS.md
- **Snapshot SHA-256:** `b10a16b08aef0589939f5191125b81231a85471eaeb3177c8fdee66251090dde`
- **Snapshot taken:** 2026-04-12
- **Line count:** 834

## Why frozen

Reproducible builds. A standard that drifts beneath us would make historical
quality scores non-comparable. The orchestrator scores every chunk against the
*snapshot*, not a moving target.

## Re-sync policy

When upstream standards change:

1. Human runs `python .quality/sync.py` (verifies network, fetches, diffs)
2. Review the diff — does ATLAS need to adjust?
3. If accepted, snapshot is updated + `SOURCE.md` SHA bumped + committed
4. Orchestrator re-scores all completed chunks against the new bar
5. Any chunk that drops below 80 on any dimension opens a remediation task

Never auto-sync. Standards changes are deliberate.

## Files in this directory

- `standards.md` — the frozen canonical standards
- `checks.py` — runnable implementation of all 7 dimensions
- `SOURCE.md` — this file
- `report.json` — latest score run output (gitignored, regenerated)
