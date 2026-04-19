# Forge Prime

Autonomous engineering OS. One command installs everything. Works on any project.

## Install

```bash
bash install.sh
forge doctor   # verify all green
```

## Quick Start

```bash
# New project
cd /path/to/your/project
forge init my-project

# Classify and run a task
forge do "add a health check endpoint"

# Autonomous build loop
forge run

# Watch progress
forge dashboard   # opens http://localhost:8099
```

## Commands

| Command | Description |
|---------|-------------|
| `forge init [name]` | Initialize a project with .forge/, orchestrator/, .quality/ |
| `forge run [flags]` | Start autonomous build loop (pick→implement→verify→advance) |
| `forge do "task"` | Classify task then route to appropriate pipeline |
| `forge quick "task"` | Single-chunk, skip classifier |
| `forge ship CHUNK_ID "msg"` | Ship a chunk via forge-ship.sh |
| `forge status` | Show plan state (chunk IDs, statuses, models, cost) |
| `forge compile` | Compile wiki staging/ → articles/ → index.md |
| `forge doctor` | Health check all components |
| `forge dashboard` | Open dashboard at http://localhost:8099 |

## Plan Format

```yaml
# orchestrator/plan.yaml
version: "1.0"
name: "My Project V1"
settings:
  default_model: sonnet

chunks:
  - id: V1-1
    title: "DB migration"
    model: deepseek          # cheap scaffold work
    status: PENDING

  - id: V1-2
    title: "Core service layer"
    model: sonnet
    depends_on: [V1-1]
    status: PENDING

  - id: V1-5
    title: "Intelligence pipeline"
    model: opus              # complex reasoning
    depends_on: [V1-4]
    status: PENDING
```

## Model Routing

| Alias | Model | Provider |
|-------|-------|----------|
| `sonnet` | claude-sonnet-4-6 | Anthropic (Max) |
| `opus` | claude-opus-4-7 | Anthropic (Max) |
| `haiku` | claude-haiku-4-5 | Anthropic (Max) |
| `deepseek` | deepseek/deepseek-chat | OpenRouter |
| `deepseek-reasoner` | deepseek/deepseek-reasoner | OpenRouter |
| `gemini-flash` | google/gemini-2.0-flash-exp:free | OpenRouter (free) |

Set `OPENROUTER_API_KEY` in `~/.forge-prime/.env` for OpenRouter models.

## Four Laws

1. **Prove, never claim** — run tests, show output, verify visually
2. **No synthetic data** — no hardcoded mocks in production code
3. **Backend first always** — API working before any frontend touches it
4. **See what you build** — check the browser, confirm the output

## Architecture

```
runner/         Async Python loop: pick → implement → verify → advance
dashboard/      FastAPI dashboard (port 8099), reads live from state.db
quality/        Portable quality gate (7 dimensions, configurable via quality.yaml)
wiki/           Article compiler: staging/ → articles/ → index.md
claude/         Claude OS layer: CLAUDE.md, rules, settings, implementer agent
scripts/        forge-ship.sh (only legal commit path), post-chunk.sh
bin/forge       CLI entry point
install.sh      One-command installer
```

## Dashboard

Live at `http://localhost:8099` — auto-refreshes every 30s.

- **Overview**: all projects, chunk counts, git status
- **Project view**: chunk timeline, model used, tokens, cost per chunk
- **Models**: cross-project token/cost breakdown
- **Wiki**: article growth, article viewer

## Wiki

After every successful chunk, `wiki_writer.py` synthesizes a 150-word
Obsidian article and pushes it to `forge-prime-wiki`. Agents read
`~/.forge/prime/wiki/index.md` before coding — this is how the system learns.

## Validation Project

Once `forge doctor` is green, run the Osho Wisdom Engine completion:
see `OSHO_COMPLETION_SPEC.md` for the 8-chunk plan.
