# `.quality/` — CHANGES.md

Chronological log of what moved in the rubric. Future contributors read this
to understand *why* the rubric looks the way it does. The code
(`checks.py` + `dimensions/*.py`) is source-of-truth; this file records intent.

---

## S2 — 2026-04-13 — standards.md rewrite + doc↔code bidirectional gate

**Context:** S1 rewrote the scoring engine to 7 independent dimensions with
a per-dim 80% gate (no composite). S2 brings `standards.md` into line with
the engine and wires a drift check so the two can never silently diverge
again.

### Added

- **Backend dim rubric (b1–b10).** The S1 file introduced these as
  informational-until-V1.6 checks; S2 writes their plain-English rubric
  in §"Dimension 6 — Backend" of `standards.md`.
- **Product dim rubric (p0).** Framed around `docs/specs/v{N}-criteria.yaml`,
  with a worked example tied to V1 criterion 7 ("≥5 decisions per pipeline run").
  Score = `passed / eligible × 100`.
- **Architecture check 3.10 — Standards doc matches code.** Runs
  `.quality/verify_doc_matches_code.py` and scores 0/10 if any drift is found
  (missing_in_doc, missing_in_code, or name_mismatch). This is the lock that
  keeps the rubric and the engine bidirectionally honest.
- **`.quality/verify_doc_matches_code.py`.** Standalone script + library.
  `python .quality/verify_doc_matches_code.py --json` emits the drift report
  for CI consumption.

### Folded

- **DevOps dim → Backend + Architecture.** The high-value DevOps checks
  (`Dockerfile`, `alembic.ini`, CI workflows) moved to backend (b4, b5, b10).
  Architecture kept the doc-presence checks (README, CLAUDE.md, ADRs).
- **Documentation dim → Architecture.** README / CLAUDE.md / ADR recording
  are now checks 3.7 / 3.8 / 3.9 on the architecture dim.

### Dropped

- **Composite formula.** `Overall = Security×0.25 + Code×0.20 + …` is
  meaningless under the per-dim gate. Deleted from §Scoring engine.
- **Weighted sum example.** Same reason — no weights, no example.
- **50–69 orange / 0–49 red colour bands.** Under the new gate every dim is
  binary: ≥80 pass, <80 fail. Bands were decorative.
- **"Four platforms" framing.** ATLAS is one platform, not a JIP Command
  Center fleet.
- **"Fix with Claude" prompt templates.** They duplicated the per-check
  `fix` field that every `CheckResult` already carries. If they're needed
  for orchestration they belong in `orchestrator/prompts.py`.
- **Ceremony DevOps checks.** SSL cert expiry, log rotation, RDS backup
  retention — never automated, never going to be. Out.
- **Monthly API cost estimate.** Not a quality signal; belongs in the budget
  doc, not the rubric.

### Renamed / kept

- The core 53 security/code/architecture/api/frontend checks kept their IDs
  and names so git blame on `standards.md` stays useful. The S1 fold table
  was applied check-by-check with `verify_doc_matches_code.py` as the
  enforcement lever.

### Test impact

- `tests/test_quality_engine.py` — stopped expecting `overall` /
  `devops` / `docs` in the report. Now asserts the 7 S1 dims exist on the
  `dims` block.
- `tests/test_orchestrator.py` — renamed the legacy `_dims_to_dict` test to
  `_dims_map` and exercised both S1 and pre-S1 report shapes.

### Verdict after S2

```
security  100/100  [GATE]
code       85/100  [GATE]
architecture 100/100  [GATE]   ← includes new 3.10 doc↔code check
api       100/100  [GATE]
frontend  100/100  [GATE]
backend   100/100  [info]
product   100/100  [info]
VERDICT: PASS ✓ — all gating dimensions ≥ 80
```

`python .quality/verify_doc_matches_code.py` → `code checks: 56  doc checks: 56  drift: 0`.

---
