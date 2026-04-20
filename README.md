# Forge Prime

Autonomous engineering OS. One command installs everything. Works on any project.

## Install

`install.sh` is one-shot — it installs OS prerequisites (python3.11+, git,
jq, node, npm), the Claude Code CLI, Python deps, pre-pulls the embedding
model, sets up the wiki as a local git repo, wires the guardrail hook, and
starts the dashboard.

```bash
git clone https://github.com/nimishshah1989/forge-prime.git ~/forge-prime
cd ~/forge-prime
bash install.sh
claude login                  # Anthropic OAuth (Max plan) — no API key needed
nano ~/.forge-prime/.env      # add OPENROUTER_API_KEY (for deepseek/gemini)
forge doctor                  # verify green
```

> **Auth model:** Anthropic access uses OAuth through the `claude` CLI under
> your Max plan. You only need an `ANTHROPIC_API_KEY` if you want to bypass
> OAuth; otherwise leave it unset. `OPENROUTER_API_KEY` is what's actually
> required in the `.env` — it unlocks deepseek / gemini for cheap-scaffold
> chunks.

### EC2 (Ubuntu) — one-liner

```bash
ssh ubuntu@<ec2-host> 'sudo apt-get update && sudo apt-get install -y git curl && \
  git clone https://github.com/nimishshah1989/forge-prime.git ~/forge-prime && \
  cd ~/forge-prime && bash install.sh'
```

### Flags

- `FORGE_DASHBOARD_BIND=0.0.0.0 bash install.sh` — expose the dashboard on
  all interfaces. Default is `127.0.0.1` (tunnel via `ssh -L 8099:localhost:8099`).
- `FORGE_INSTALL_CODEX=1 bash install.sh` — also install `@openai/codex`
  for the adversarial review step in `forge-ship.sh`.
- `FORGE_NONINTERACTIVE=1 bash install.sh` — safe for cloud-init user-data.

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
