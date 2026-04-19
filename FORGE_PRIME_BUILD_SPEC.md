# FORGE PRIME — Complete Build Specification
# Handoff to Claude Code
# Date: 2026-04-19

## What You Are Building

A new standalone engineering OS called **Forge Prime** that supersedes
both `nimishshah1989/forge-os` and the `atlas` forge_runner. It lives at
`nimishshah1989/forge-prime` on GitHub. It is installed with one command
on any machine (Mac or EC2 Ubuntu) and works for any project.

This is NOT a fork. Build from scratch, using the architecture described below.
Reference the existing repos for patterns but do not copy code wholesale.

## Repo Structure to Create

```
forge-prime/
├── README.md
├── install.sh                    # one command installs everything
├── requirements.txt              # Python deps for runner + dashboard
├── pyproject.toml
├── .gitignore
│
├── bin/
│   └── forge                     # CLI: init, run, do, ship, status, doctor, compile
│
├── runner/                       # Async Python runner (core)
│   ├── __init__.py
│   ├── cli.py                    # entry point
│   ├── loop.py                   # pick→implement→verify→advance
│   ├── stages.py                 # Stage protocol + concrete stages
│   ├── state.py                  # SQLite CRUD (WAL, BEGIN IMMEDIATE, IST timestamps)
│   ├── session.py                # Claude Agent SDK wrapper (backoff, timeout, auth)
│   ├── verifier.py               # 5-check post-session gate
│   ├── picker.py                 # dependency-aware chunk selector
│   ├── deadman.py                # startup orphan scan
│   ├── halt.py                   # COMPLETE vs STALLED decision
│   ├── logs.py                   # atomic JSONL writes + runner-state
│   ├── router.py                 # NEW: model routing per chunk
│   ├── cost_tracker.py           # NEW: token/cost per chunk → state.db
│   ├── wiki_writer.py            # NEW: post-chunk article synthesis
│   ├── classifier.py             # NEW: task size classifier (QUICK/FEATURE/MILESTONE)
│   ├── git_sync.py               # NEW: pre-run and post-chunk git enforcement
│   ├── secrets.py                # secrets scrubbing
│   ├── _time.py                  # IST-aware timestamps
│   └── config.py                 # RunConfig + parse_args
│
├── dashboard/                    # FastAPI dashboard (always running, port 8099)
│   ├── app.py                    # FastAPI app + static serving
│   ├── api/
│   │   ├── projects.py           # project-level stats
│   │   ├── chunks.py             # chunk detail: model, tokens, tests, duration
│   │   ├── sessions.py           # session-level event stream viewer
│   │   ├── wiki.py               # wiki article list + growth chart
│   │   ├── models.py             # cross-project model usage breakdown
│   │   └── git_status.py         # per-project git sync status
│   └── static/
│       ├── index.html            # single-page app
│       ├── app.js                # vanilla JS, no framework
│       └── style.css
│
├── quality/                      # portable quality gate (derived from atlas)
│   ├── __init__.py
│   ├── engine.py                 # run all dims, emit report.json
│   ├── dimensions/
│   │   ├── __init__.py
│   │   ├── security.py           # 10 checks (secrets, CORS, deps, rate limit, input validation)
│   │   ├── code.py               # 11 checks (lint, types, coverage, complexity, dead code)
│   │   ├── architecture.py       # spec coverage, API standard, Decimal enforcement
│   │   ├── api.py                # UQL compliance, error envelope, response shape
│   │   ├── frontend.py           # component size, a11y, lakh/crore, no console.log
│   │   ├── backend.py            # service boundaries, N+1, idempotency
│   │   └── product.py            # feature criteria, spec coverage
│   └── templates/
│       └── quality.yaml          # project config: domain, project_type, gating
│
├── wiki/                         # wiki engine
│   ├── compiler.py               # staging → compiled articles → index.md
│   ├── writer.py                 # post-chunk article synthesis (Sonnet via API)
│   └── templates/
│       └── article.md            # Obsidian-format article template
│
├── claude/                       # Claude OS layer (copied to ~/.claude/ on install)
│   ├── CLAUDE.md                 # 42 lines max: Four Laws + wiki pointer
│   ├── AGENTS.md                 # Gemini rules for free cross-review
│   ├── settings.json             # rtk hook + pre-commit quality hook
│   ├── agents/
│   │   └── implementer.md        # context:fork, model:claude-sonnet-4-6
│   ├── rules/                    # path-scoped, loaded only for matching files
│   │   ├── python-backend.md     # globs: ["*.py","backend/**"]
│   │   ├── database.md           # globs: ["**/models/**","**/migrations/**"]
│   │   ├── testing.md            # globs: ["tests/**"]
│   │   ├── frontend.md           # globs: ["frontend/**","*.tsx","*.ts"]
│   │   ├── api-design.md         # globs: ["**/routes/**","backend/routes/**"]
│   │   └── security.md           # no globs: always loaded
│   └── commands/
│       ├── fp-build.md           # conductor: PRD → plan → implement loop
│       ├── fp-compile.md         # wiki compile command
│       ├── fp-status.md          # project status dashboard
│       └── fp-quick.md           # small task workflow
│
├── scripts/
│   ├── forge-ship.sh             # only legal commit path
│   ├── post-chunk.sh             # git push + service restart + smoke + wiki
│   ├── pre-commit-quality.sh     # blocks commit if ruff/mypy/pytest fail
│   └── git-sync-check.sh         # verifies clean tree + pushed state
│
├── templates/
│   ├── CONDUCTOR.md              # 30-line session prompt template
│   ├── plan.yaml                 # plan template with model: field per chunk
│   ├── project.yaml              # per-project config
│   └── constitution.md           # Four Laws + project non-negotiables
│
├── systemd/
│   ├── forge-dashboard.service   # dashboard runs always, restarts on crash
│   └── forge-wiki-compile.timer  # weekly wiki compile cron
│
└── tests/
    ├── test_runner.py
    ├── test_verifier.py
    ├── test_router.py
    ├── test_classifier.py
    └── test_wiki_writer.py
```

---

## Layer-by-Layer Build Instructions

### LAYER 1: The Runner

Port the best parts of atlas/scripts/forge_runner verbatim:
- `state.py`: WAL SQLite, BEGIN IMMEDIATE, IST timestamps, ChunkRow dataclass
- `session.py`: claude_agent_sdk wrapper, exponential backoff on 529, AuthFailure
- `deadman.py`: PID liveness check, auto-reset orphaned IN_PROGRESS rows
- `loop.py`: pick→implement→verify→advance async loop
- `logs.py`: atomic tmp+rename writes, secrets.scrub before every write
- `secrets.py`: regex-based API key scrubber
- `_time.py`: IST ZoneInfo, now_ist(), to_iso()
- `picker.py`: lexicographic order, dependency checking, fullmatch regex

NEW modules to add:

#### router.py
```python
"""Model router — reads chunk's model: field from plan.yaml.
Falls back to FORGE_DEFAULT_MODEL env var, then claude-sonnet-4-6."""

ROUTING_MAP = {
    "opus": "claude-opus-4-7",       # Anthropic API / Max plan
    "sonnet": "claude-sonnet-4-6",   # Anthropic API / Max plan (default)
    "haiku": "claude-haiku-4-5",     # Anthropic API
    "deepseek": "deepseek/deepseek-chat",        # OpenRouter
    "gemini-flash": "google/gemini-2.0-flash-exp:free",  # OpenRouter free
    "deepseek-reasoner": "deepseek/deepseek-reasoner",   # OpenRouter
}
```

plan.yaml chunk format:
```yaml
- id: V1-1
  title: "DB migration"
  model: deepseek          # cheap scaffold work
  status: PENDING

- id: V1-5
  title: "Intelligence writer pipeline"
  model: opus              # complex reasoning
  status: PENDING
```

If model is deepseek/gemini, route through OpenRouter API.
If model is sonnet/opus/haiku, route through claude_agent_sdk (Max plan).
OpenRouter key comes from OPENROUTER_API_KEY env var.

#### cost_tracker.py
After every chunk DONE, write to state.db:
- input_tokens (from session_end event usage dict)
- output_tokens
- estimated_cost_usd (calculated from model pricing table)
- model_used
- duration_seconds

Add these columns to the chunks table via Alembic migration.

#### classifier.py
```
forge do "add export button to holdings table"
→ Sonnet call (~$0.002) classifies as:
  QUICK: single chunk, no architecture change, <5 files
  FEATURE: 1-3 chunks, needs spec, <1 day
  MILESTONE: 3+ chunks, needs architecture review, multi-day
→ Returns {type, reasoning, estimated_chunks, files_likely_touched}
→ User sees reasoning + approves before anything runs
```

#### wiki_writer.py
After every chunk DONE, call Sonnet via OpenRouter (~$0.01) with:
- session log (last 50 events)
- chunk spec
- prompt: "Write a 150-word Obsidian wiki article about the key pattern or
  decision from this chunk. Format: YAML frontmatter + markdown body.
  Include: what worked, what failed (if anything), the pattern discovered,
  and 2-3 related article links [[like this]]."

Write output to `~/.forge/prime/wiki/staging/{chunk_id}.md`.

#### git_sync.py
Pre-run gate (blocks `forge run` if fails):
```python
def check_git_clean(repo_path: Path) -> tuple[bool, str]:
    # git status --porcelain must be empty
    # git log origin/main..HEAD must be empty
    # Returns (ok, message)
```

Post-chunk gate (5th verifier check):
```python
def check_pushed(repo_path: Path) -> tuple[bool, str]:
    # git log origin/main..HEAD must be empty after chunk commit
```

### LAYER 2: The Verifier (extend from atlas)

5 checks (atlas had 4, we add git push check):
1. state.db row status == DONE
2. Latest git commit starts with chunk_id prefix
3. .forge/last-run.json mtime is fresh (within session window)
4. git status --porcelain is clean (excluding runner-owned paths)
5. NEW: git log origin/main..HEAD is empty (pushed to origin)

### LAYER 3: The Dashboard

FastAPI serving static HTML. Runs on port 8099.
Installed as systemd service so it's always running.

State.db is the single source of truth. Dashboard reads it.
Also reads wiki staging/ and wiki/ directories for wiki view.
Also runs `git status` on each registered project path.

**Dashboard pages:**

#### Overview (/) 
- Total chunks across all projects this week/month
- Model breakdown: Opus hours used, Sonnet hours used, DeepSeek/Gemini API cost
- Weekly token burn chart (line graph)
- Active projects list with status indicators

#### Project View (/project/{name})
- Chunk timeline: each chunk as a row with status chip, model badge, duration, cost
- Quality score radar chart (7 dimensions)
- Test results: for each chunk, how many tests passed/failed
- Git sync indicator: green (clean+pushed) or red (dirty/behind)
- Wiki articles created in this project

#### Chunk Detail (/chunk/{id})
- Which model ran it
- Duration, input tokens, output tokens, estimated cost
- Quality gate scores per dimension
- Test list: test name, pass/fail, duration
- Session events: abbreviated tool call log
- Git commit hash + diff summary

#### Wiki View (/wiki)
- Article count over time (line chart — this shows the system learning)
- Article list: title, chunk that created it, how many times retrieved
- Article content viewer with Obsidian wikilinks rendered

#### Model Usage (/models)
- Daily/weekly/monthly breakdown
- Opus hours (vs Max plan limit)
- Sonnet hours (vs Max plan limit)
- OpenRouter spend in USD
- Projected monthly cost

**Implementation:** FastAPI + vanilla JS + Chart.js via CDN.
No React, no build step. Single `app.py` serves everything.
Auto-refresh every 30 seconds via `setInterval`.

### LAYER 4: Quality Gate (portable from atlas)

The `quality/` directory is a self-contained quality engine.
`forge init` copies it into the project as `.quality/`.

Key design: `quality.yaml` in the project root configures it:
```yaml
domain: financial        # activates: Decimal, IST, lakh/crore checks
project_type: fastapi_next  # activates: Python + TypeScript profiles
gating_dims: [security, code, architecture, api, frontend]
```

`domain: financial` adds these mandatory checks:
- No float in financial calculations (AST scan of *.py)
- All datetime objects must be IST timezone-aware (structlog context check)
- No "million" or "billion" in user-visible strings (grep *.tsx *.ts)

`domain: general` runs standard checks without financial domain constraints.

### LAYER 5: Claude OS Layer

Files in `claude/` are copied to `~/.claude/` by install.sh.

CLAUDE.md (42 lines max):
```markdown
# Forge Prime OS

## Four Laws (non-negotiable)
1. Prove, never claim — run tests, show output, verify visually
2. No synthetic data — ever. No hardcoded mocks in production code
3. Backend first always — API working before any frontend touches it
4. See what you build — check the browser, confirm the output

## Wiki
Before ANY implementation: read ~/.forge/prime/wiki/index.md
Identify relevant articles. Read ONLY those (1-2 max). Not end-to-end.

## Conventions (project-specific ones live in .forge/constitution.md)
- Tests: pytest (backend) + npm test (frontend). 100% of declared tests must pass.
- Commit only via forge-ship.sh. Never raw git commit.
- One chunk per session. Fresh context per chunk.
- Subagents: context:fork always. Main agent sees summaries only.

## Commands
/fp-build, /fp-compile, /fp-status, /fp-quick
```

implementer.md:
```yaml
---
name: implementer
description: Builds one chunk from spec. context:fork. Sees summaries only.
model: claude-sonnet-4-6
context: fork
tools: [Read, Write, Edit, Bash, Grep, Glob, TodoWrite, Agent]
---
[implementation instructions: Four Laws, read wiki first, scope discipline,
forge-ship.sh is only legal commit path, report summary]
```

settings.json (rtk + pre-commit hook):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "command": "bash ~/.forge/prime/hooks/pre-commit-quality.sh"
        }]
      }
    ]
  }
}
```

### LAYER 6: The Wiki Engine

`~/.forge/prime/wiki/` structure:
```
wiki/
├── staging/          # raw articles from wiki_writer, not yet compiled
│   └── V1-3.md
├── articles/         # compiled, deduped, validated articles
│   ├── patterns/
│   ├── anti-patterns/
│   ├── decisions/
│   └── domain/
└── index.md          # 200-line summary (this is what agents read)
```

`wiki/compiler.py`:
1. Read all staging/*.md
2. Deduplicate by semantic similarity (simple title matching first)
3. Write to articles/ organized by frontmatter `category:`
4. Regenerate index.md: one paragraph per article, grouped by category
5. Track article retrieval count (increment when agent reads article)

### LAYER 7: The Install Script

install.sh must do these steps in order:
1. Check Python 3.11+, git, jq, Claude Code installed
2. Install Python deps: `pip install -r requirements.txt --break-system-packages`
3. Backup existing ~/.claude/ if present
4. Copy claude/ → ~/.claude/
5. Create ~/.forge/prime/wiki/{staging,articles,articles/patterns,articles/anti-patterns,articles/decisions,articles/domain}
6. Create ~/.forge/prime/db/ (cross-project state)
7. Install `forge` binary: `ln -sf ~/.forge-prime/bin/forge /usr/local/bin/forge`
8. Install systemd service (Linux only): `systemd/forge-dashboard.service`
   On Mac: create a launchd plist instead
9. Start dashboard: `systemctl start forge-dashboard` (Linux) or LaunchAgent (Mac)
10. Install weekly cron: `forge compile` runs every Sunday at 2am
11. Run `forge doctor` and print results
12. Print: "Forge Prime installed. Dashboard: http://localhost:8099"

---

## The forge CLI

```bash
# New project
forge init [project-name]
# → creates .forge/, orchestrator/, docs/specs/
# → copies quality/, CONDUCTOR.md, plan.yaml templates
# → registers project in ~/.forge/prime/db/projects.db

# Autonomous build
forge run [--filter REGEX] [--once] [--dry-run] [--retry CHUNK_ID]

# Smart task (auto-classifies then routes to quick or full pipeline)
forge do "description of what to build"
# → classifier decides QUICK/FEATURE/MILESTONE
# → shows classification + reasoning
# → awaits your approval
# → runs appropriate pipeline

# Direct quick task (skips classifier)
forge quick "fix the export button in holdings table"

# Ship a chunk manually
forge ship CHUNK_ID "message"

# Project status
forge status

# Wiki compile
forge compile

# System health check
forge doctor

# Dashboard (opens in browser)
forge dashboard
```

---

## The plan.yaml format (new design)

```yaml
version: "1.0"
name: "My Project V1"
description: "What this milestone achieves"

settings:
  repo_root: .
  default_model: sonnet          # fallback if chunk doesn't specify
  timeout: "45m"
  max_turns: 120                 # reduced from atlas's 300
  quality:
    script: .quality/engine.py
    min_per_dim: 80
    gating_dims: [security, code, architecture, api, frontend]
  post_chunk:
    enabled: true
    script: scripts/post-chunk.sh

chunks:
  - id: V1-1
    title: "DB schema + migration"
    model: deepseek              # cheap: just Alembic migration
    status: PENDING
    punch_list:
      - "alembic upgrade head clean"
      - "pytest tests/db/test_schema.py green"

  - id: V1-2
    title: "Core service layer"
    model: sonnet
    status: PENDING
    depends_on: [V1-1]
    punch_list:
      - "all service methods have type hints"
      - "pytest tests/unit/test_service.py green"

  - id: V1-7
    title: "Intelligence pipeline architecture"
    model: opus                  # complex: needs deep reasoning
    status: PENDING
    depends_on: [V1-6]
    punch_list:
      - "LangGraph graph handles partial data without crashing"
      - "pytest tests/integration/test_pipeline.py green"
```

---

## Critical Implementation Notes

1. **rtk integration**: settings.json must include the rtk pre-rewrite hook.
   rtk binary is installed by setup-forge.sh (Rust). If rtk not installed,
   the hook silently skips (never fails hard on missing rtk).

2. **context:fork in implementer**: This is the most important thing.
   The implementer subagent runs in isolated context. Main agent sees
   only the summary report. All grep outputs, file reads, test runs stay
   in the subagent context and never pollute the orchestrator.

3. **OpenRouter integration**: For deepseek/gemini models, the session.py
   must use httpx directly (not claude_agent_sdk) against OpenRouter API.
   Same streaming interface, same event format. Router decides which path.

4. **Dashboard persistence**: The dashboard reads live from state.db.
   It does NOT have its own database. All data comes from:
   - orchestrator/state.db (chunks, runs, token usage)
   - ~/.forge/prime/wiki/ (wiki articles)
   - git status (live checks per project)

5. **Wiki actually works**: wiki_writer.py MUST run after every successful
   chunk. This is wired into LocalVerifyStage.run() after all 5 checks pass.
   It runs async so it doesn't block the runner.

6. **Financial domain checks**: When quality.yaml has `domain: financial`,
   add these AST-level checks to the code dimension:
   - Scan all *.py for `float(` inside function bodies that also contain
     financial keywords (price, value, amount, cost, fee, pct, rate)
   - Scan all *.py for datetime.now() without timezone (naive datetime)
   - Scan *.tsx/*.ts for "million" or "billion" in string literals

---

## Testing Strategy

After building all layers, verify:

```bash
# 1. Install test (fresh EC2 / Mac)
bash install.sh
forge doctor   # all green

# 2. New project test
mkdir /tmp/test-project && cd /tmp/test-project
git init && git remote add origin <test-repo>
forge init test-project
ls .forge/ orchestrator/ .quality/   # all present

# 3. Classifier test  
forge do "add a button to the login page"
# → should classify as QUICK

forge do "build a complete notification system with email, push, and in-app alerts"
# → should classify as MILESTONE

# 4. Runner test (needs actual claude_agent_sdk or mock)
forge run --dry-run
# → should print "would pick: V1-1 — DB schema + migration"

# 5. Dashboard test
curl http://localhost:8099/api/projects
# → returns [] (empty but valid)

# 6. Wiki test
echo "---\ntitle: Test Article\ncategory: patterns\n---\n# Test" > \
  ~/.forge/prime/wiki/staging/test.md
forge compile
cat ~/.forge/prime/wiki/index.md
# → should contain the test article
```

---

## Sequence: Build This in Order

Phase 1: Foundation (runner + state + CLI skeleton)
Phase 2: Quality gate (port from atlas, make portable)
Phase 3: Claude OS layer (CLAUDE.md, rules, settings.json, implementer)
Phase 4: Wiki engine (writer + compiler)
Phase 5: Dashboard (FastAPI + vanilla JS)
Phase 6: Install script + systemd
Phase 7: Tests
Phase 8: README + docs

Do NOT skip to Phase 6 before Phase 1-5 are working. Each phase must be
individually testable before proceeding.

---

## Repositories to Reference (do not blindly copy)

- forge_runner source: https://github.com/nimishshah1989/atlas/tree/main/scripts/forge_runner
- forge-os patterns: https://github.com/nimishshah1989/forge-os
- atlas quality gate: https://github.com/nimishshah1989/atlas/blob/main/.quality/checks.py
- atlas CLAUDE.md: https://github.com/nimishshah1989/atlas/blob/main/CLAUDE.md

Once forge-prime is built and `forge doctor` is green, proceed to the
second spec: OSHO_COMPLETION_SPEC.md
