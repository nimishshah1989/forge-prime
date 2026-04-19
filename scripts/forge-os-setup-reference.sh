#!/bin/bash
set -e

# ╔══════════════════════════════════════════════════════════════╗
# ║  FORGE OS v3 — One-Command Complete Installation             ║
# ║                                                              ║
# ║  Installs: Forge core + gstack + obsidian-skills + rtk +    ║
# ║  ralph-claude-code + Context7 MCP + wiki + cron             ║
# ║                                                              ║
# ║  Usage: bash setup-forge.sh                                  ║
# ║                                                              ║
# ║  Official repos installed:                                   ║
# ║    1. garrytan/gstack (54K stars)                            ║
# ║    2. kepano/obsidian-skills (14.9K stars)                   ║
# ║    3. rtk-ai/rtk (token compression)                        ║
# ║    4. frankbria/ralph-claude-code (566 tests, autonomous)    ║
# ║    5. @upstash/context7-mcp (live docs)                      ║
# ╚══════════════════════════════════════════════════════════════╝

FORGE_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ! $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; }
step() { echo -e "\n${GREEN}[$1/$TOTAL]${NC} $2"; }

TOTAL=11

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          FORGE OS v3 — Complete Installation                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ──────────────────────────────────────────────────────────────────
step 1 "Checking prerequisites..."
# ──────────────────────────────────────────────────────────────────

if command -v claude &>/dev/null; then
  ok "Claude Code: $(claude --version 2>/dev/null | head -1 || echo 'installed')"
else
  fail "Claude Code not found. Install: npm install -g @anthropic-ai/claude-code"
  exit 1
fi

command -v git &>/dev/null && ok "git: $(git --version | head -1)" || { fail "git not found"; exit 1; }

if command -v bun &>/dev/null; then
  ok "bun: $(bun --version 2>/dev/null)"
else
  warn "bun not found — installing..."
  curl -fsSL https://bun.sh/install | bash 2>/dev/null
  export PATH="$HOME/.bun/bin:$PATH"
  command -v bun &>/dev/null && ok "bun installed: $(bun --version)" || warn "bun install failed"
fi

if command -v cargo &>/dev/null; then
  ok "cargo: $(cargo --version 2>/dev/null | head -1)"
else
  warn "Rust/cargo not found — installing..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y 2>/dev/null
  source "$HOME/.cargo/env" 2>/dev/null
  command -v cargo &>/dev/null && ok "cargo installed: $(cargo --version | head -1)" || warn "cargo install failed"
fi

command -v npx &>/dev/null && ok "npx: available" || warn "npx not found"
command -v jq &>/dev/null && ok "jq: available" || warn "jq not found — install with: brew install jq"
command -v tmux &>/dev/null && ok "tmux: available" || warn "tmux not found — install with: brew install tmux (needed for ralph-monitor)"

# ──────────────────────────────────────────────────────────────────
step 2 "Installing Forge OS core files to ~/.claude/ (global)..."
# ──────────────────────────────────────────────────────────────────

for f in CLAUDE.md AGENTS.md settings.json; do
  [ -f "$CLAUDE_DIR/$f" ] && cp "$CLAUDE_DIR/$f" "$CLAUDE_DIR/$f.bak.$(date +%Y%m%d)" 2>/dev/null && ok "Backed up $f"
done

cp "$FORGE_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
cp "$FORGE_DIR/AGENTS.md" "$CLAUDE_DIR/AGENTS.md"

mkdir -p "$CLAUDE_DIR/agents"
cp "$FORGE_DIR/.claude/agents/implementer.md" "$CLAUDE_DIR/agents/"

mkdir -p "$CLAUDE_DIR/rules"
cp "$FORGE_DIR/.claude/rules/"*.md "$CLAUDE_DIR/rules/"

mkdir -p "$CLAUDE_DIR/commands"
cp "$FORGE_DIR/.claude/commands/"*.md "$CLAUDE_DIR/commands/"

mkdir -p "$HOME/.forge/bin" "$HOME/.forge/logs" "$HOME/.forge/templates"
cp "$FORGE_DIR/hooks/"*.sh "$HOME/.forge/bin/"
cp "$FORGE_DIR/ralph-template/prompt.md" "$HOME/.forge/templates/ralph-prompt.md"
cp "$FORGE_DIR/ralph-template/.ralphrc" "$HOME/.forge/templates/.ralphrc"
chmod +x "$HOME/.forge/bin/"*.sh

ok "Installed: CLAUDE.md, AGENTS.md, 1 agent, 4 rules, 4 commands, 2 hooks, ralph templates"

# ──────────────────────────────────────────────────────────────────
step 3 "Installing gstack (github.com/garrytan/gstack)..."
# ──────────────────────────────────────────────────────────────────

if [ -d "$CLAUDE_DIR/skills/gstack" ]; then
  warn "gstack exists — pulling latest..."
  cd "$CLAUDE_DIR/skills/gstack" && git pull --quiet 2>/dev/null
else
  git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git "$CLAUDE_DIR/skills/gstack" 2>/dev/null
fi

if [ -f "$CLAUDE_DIR/skills/gstack/setup" ]; then
  cd "$CLAUDE_DIR/skills/gstack" && chmod +x setup && ./setup --no-prefix 2>/dev/null
  ok "gstack installed (25 skills — you use 12 actively)"
else
  warn "gstack setup not found. Run: cd ~/.claude/skills/gstack && ./setup"
fi

# ──────────────────────────────────────────────────────────────────
step 4 "Installing obsidian-skills (github.com/kepano/obsidian-skills)..."
# ──────────────────────────────────────────────────────────────────

if [ -d "$CLAUDE_DIR/skills/obsidian-skills" ]; then
  cd "$CLAUDE_DIR/skills/obsidian-skills" && git pull --quiet 2>/dev/null
else
  git clone --single-branch --depth 1 https://github.com/kepano/obsidian-skills.git "$CLAUDE_DIR/skills/obsidian-skills" 2>/dev/null
fi
ok "obsidian-skills installed (Obsidian-flavored markdown for wiki)"

# ──────────────────────────────────────────────────────────────────
step 5 "Installing rtk (github.com/rtk-ai/rtk)..."
# ──────────────────────────────────────────────────────────────────

if command -v rtk &>/dev/null; then
  ok "rtk already installed: $(rtk --version 2>/dev/null | head -1)"
else
  if command -v cargo &>/dev/null; then
    echo "  Compiling rtk from source (1-2 minutes)..."
    cargo install --git https://github.com/rtk-ai/rtk 2>/dev/null
    command -v rtk &>/dev/null && ok "rtk installed" || warn "rtk build failed"
  else
    warn "cargo unavailable. Install Rust, then: cargo install --git https://github.com/rtk-ai/rtk"
  fi
fi

if command -v rtk &>/dev/null; then
  rtk init -g --auto-patch 2>/dev/null
  ok "rtk hook installed globally (60-90% token savings)"
fi

# ──────────────────────────────────────────────────────────────────
step 6 "Installing ralph-claude-code (github.com/frankbria/ralph-claude-code)..."
# ──────────────────────────────────────────────────────────────────

RALPH_DIR="$HOME/.ralph"

if [ -d "$RALPH_DIR" ]; then
  warn "ralph exists — pulling latest..."
  cd "$RALPH_DIR" && git pull --quiet 2>/dev/null
else
  git clone https://github.com/frankbria/ralph-claude-code.git "$RALPH_DIR" 2>/dev/null
fi

if [ -f "$RALPH_DIR/install.sh" ]; then
  cd "$RALPH_DIR" && chmod +x install.sh && ./install.sh 2>/dev/null
  ok "ralph installed globally (566 tests, circuit breaker, rate limiting)"
  echo "  Commands: ralph, ralph-setup, ralph-enable, ralph-monitor"
else
  warn "ralph install.sh not found. Run manually: cd ~/.ralph && ./install.sh"
fi

# ──────────────────────────────────────────────────────────────────
step 7 "Installing Context7 MCP (@upstash/context7-mcp)..."
# ──────────────────────────────────────────────────────────────────

if command -v claude &>/dev/null && command -v npx &>/dev/null; then
  claude mcp add context7 --scope user -- npx -y @upstash/context7-mcp@latest 2>/dev/null
  ok "Context7 MCP registered (live docs for all libraries)"
else
  warn "Manual install: claude mcp add context7 --scope user -- npx -y @upstash/context7-mcp@latest"
fi

# ──────────────────────────────────────────────────────────────────
step 8 "Initializing knowledge wiki..."
# ──────────────────────────────────────────────────────────────────

bash "$FORGE_DIR/wiki-setup/init-wiki.sh"
ok "Wiki ready at ~/.forge/knowledge/"

# ──────────────────────────────────────────────────────────────────
step 9 "Setting up Antigravity paths..."
# ──────────────────────────────────────────────────────────────────

cp "$FORGE_DIR/AGENTS.md" "$HOME/AGENTS.md" 2>/dev/null
AG_CONFIG="$HOME/Library/Application Support/Antigravity/User"
if [ -d "$AG_CONFIG" ] 2>/dev/null; then
  cp "$FORGE_DIR/AGENTS.md" "$AG_CONFIG/AGENTS.md" 2>/dev/null
  ok "AGENTS.md copied to Antigravity config"
else
  ok "AGENTS.md placed in home directory"
fi

# ──────────────────────────────────────────────────────────────────
step 10 "Merging hook settings (rtk + forge hooks)..."
# ──────────────────────────────────────────────────────────────────

# rtk already patched settings.json with its hook.
# We need to ADD our pre-commit hook WITHOUT overwriting rtk's hook.
# Read existing settings, merge our hook if not present.
if [ -f "$CLAUDE_DIR/settings.json" ]; then
  if command -v jq &>/dev/null; then
    # Check if our forge pre-commit hook already exists
    if ! grep -q "LINT FAILED" "$CLAUDE_DIR/settings.json" 2>/dev/null; then
      # Add our pre-commit hook to existing PreToolUse array
      FORGE_HOOK='{"matcher":"Bash","hooks":[{"type":"command","command":"bash -c '\''INPUT=$(cat); CMD=$(echo \"$INPUT\" | jq -r \".tool_input.command // empty\"); if echo \"$CMD\" | grep -qE \"^git\\s+commit\"; then if command -v ruff &>/dev/null; then if ! ruff check . --select E,F,W -q 2>&1; then echo \"LINT FAILED\" >&2; exit 2; fi; fi; fi; exit 0'\''"}]}'
      # Use jq to append to PreToolUse array
      jq ".hooks.PreToolUse += [$FORGE_HOOK]" "$CLAUDE_DIR/settings.json" > "$CLAUDE_DIR/settings.json.tmp" 2>/dev/null && \
        mv "$CLAUDE_DIR/settings.json.tmp" "$CLAUDE_DIR/settings.json"
      ok "Forge pre-commit hook merged with rtk hooks"
    else
      ok "Forge hooks already present in settings.json"
    fi
  else
    warn "jq not installed — cannot merge hooks automatically"
    warn "Install jq (brew install jq) and re-run setup, or add pre-commit hook manually"
  fi
else
  cp "$FORGE_DIR/.claude/settings.json" "$CLAUDE_DIR/settings.json"
  ok "Forge settings.json installed (no existing settings found)"
fi

# ──────────────────────────────────────────────────────────────────
step 11 "Setting up automated wiki maintenance (cron)..."
# ──────────────────────────────────────────────────────────────────

CRON_MARKER="# FORGE-OS-WIKI-CRON"
EXISTING_CRON=$(crontab -l 2>/dev/null || echo "")

if echo "$EXISTING_CRON" | grep -q "$CRON_MARKER"; then
  ok "Cron jobs already installed"
else
  NEW_CRON="$EXISTING_CRON
$CRON_MARKER
# Weekly wiki compilation (Sunday 6 AM IST — off-peak)
0 6 * * 0 cd \$HOME && claude -p 'Run /forge-compile' --model claude-sonnet-4-6 >> \$HOME/.forge/logs/compile.log 2>&1
# Monthly health check (1st of month, 6 AM IST)
0 6 1 * * cd \$HOME && claude -p 'Run /forge-health-check' --model claude-sonnet-4-6 >> \$HOME/.forge/logs/health.log 2>&1"

  echo "$NEW_CRON" | crontab - 2>/dev/null
  [ $? -eq 0 ] && ok "Cron jobs installed (weekly compile + monthly health check)" || \
    warn "Add cron manually — see README for cron lines"
fi

# ──────────────────────────────────────────────────────────────────
# DONE
# ──────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                  FORGE OS v3 — INSTALLED                        ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║                                                                  ║"
echo "║  Core:       ~/.claude/ (CLAUDE.md, agents, rules, commands)    ║"
echo "║  gstack:     ~/.claude/skills/gstack/ (25 skills)              ║"
echo "║  obsidian:   ~/.claude/skills/obsidian-skills/                  ║"
echo "║  ralph:      ~/.ralph/ (autonomous loop engine)                 ║"
echo "║  rtk:        global binary + hook (token compression)          ║"
echo "║  Context7:   MCP registered (live docs)                         ║"
echo "║  Wiki:       ~/.forge/knowledge/                                ║"
echo "║  Templates:  ~/.forge/templates/ (ralph prompts)               ║"
echo "║  Cron:       weekly compile + monthly health check              ║"
echo "║                                                                  ║"
echo "║  OBSIDIAN (one time):                                            ║"
echo "║    Open Obsidian → 'Open folder as vault' → ~/.forge/knowledge/wiki/  ║"
echo "║                                                                  ║"
echo "║  USAGE:                                                          ║"
echo "║    Open project → terminal → claude → /forge-build              ║"
echo "║    For autonomous loop: ralph (after plan is approved)          ║"
echo "║    Monitor: ralph-monitor (in separate terminal)                 ║"
echo "║                                                                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
