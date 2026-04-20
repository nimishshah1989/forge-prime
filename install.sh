#!/usr/bin/env bash
# Forge Prime install script — one-shot, idempotent.
# Works on Ubuntu/Debian (apt), Amazon Linux / RHEL (yum/dnf), and macOS (brew).
#
# Usage:
#   bash install.sh                 # standard
#   FORGE_NONINTERACTIVE=1 bash install.sh   # for cloud-init / user-data
#   FORGE_INSTALL_CODEX=1 bash install.sh    # also install @openai/codex
#   FORGE_DASHBOARD_BIND=0.0.0.0 bash install.sh   # expose dashboard (default: 127.0.0.1)

set -euo pipefail

FORGE_HOME="$HOME/.forge-prime"
FORGE_STATE="$HOME/.forge/prime"
WIKI_DIR="$FORGE_STATE/wiki"
CLAUDE_DIR="$HOME/.claude"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_BIND="${FORGE_DASHBOARD_BIND:-127.0.0.1}"
INSTALL_CODEX="${FORGE_INSTALL_CODEX:-0}"

log() { printf "\033[1;34m[forge-prime]\033[0m %s\n" "$*"; }
ok()  { printf "\033[1;32m[forge-prime]\033[0m ✓ %s\n" "$*"; }
warn(){ printf "\033[1;33m[forge-prime]\033[0m ⚠ %s\n" "$*"; }
fail(){ printf "\033[1;31m[forge-prime]\033[0m ✗ %s\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Step 0: Platform detection
# ---------------------------------------------------------------------------
OS="$(uname -s)"
if [ "$OS" = "Linux" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MGR="apt"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MGR="dnf"
  elif command -v yum >/dev/null 2>&1; then
    PKG_MGR="yum"
  else
    PKG_MGR="none"
    warn "No apt/dnf/yum found — system packages must already be installed."
  fi
elif [ "$OS" = "Darwin" ]; then
  if command -v brew >/dev/null 2>&1; then
    PKG_MGR="brew"
  else
    PKG_MGR="none"
    warn "Homebrew not found. Install it first: https://brew.sh"
  fi
else
  PKG_MGR="none"
  warn "Unknown OS '$OS' — system packages must already be installed."
fi

SUDO=""
if [ "$PKG_MGR" = "apt" ] || [ "$PKG_MGR" = "dnf" ] || [ "$PKG_MGR" = "yum" ]; then
  if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  fi
fi

# ---------------------------------------------------------------------------
# Step 1: Install OS prerequisites
# ---------------------------------------------------------------------------
log "Installing OS prerequisites (pkg manager: $PKG_MGR)…"

install_apt() {
  export DEBIAN_FRONTEND=noninteractive
  $SUDO apt-get update -y >/dev/null
  $SUDO apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    git jq curl ca-certificates build-essential \
    nodejs npm >/dev/null || return 1
}

install_dnf_yum() {
  $SUDO "$PKG_MGR" install -y python3 python3-pip git jq curl gcc gcc-c++ make \
    nodejs npm >/dev/null || return 1
}

install_brew() {
  brew install python@3.11 git jq node >/dev/null || return 1
}

case "$PKG_MGR" in
  apt) install_apt && ok "apt packages installed" || warn "apt install had errors — continuing" ;;
  dnf|yum) install_dnf_yum && ok "$PKG_MGR packages installed" || warn "$PKG_MGR install had errors — continuing" ;;
  brew) install_brew && ok "brew packages installed" || warn "brew install had errors — continuing" ;;
  *) log "Skipping OS package install" ;;
esac

# Verify the essentials
command -v python3 >/dev/null 2>&1 || fail "python3 not found after install"
command -v git     >/dev/null 2>&1 || fail "git not found after install"
command -v jq      >/dev/null 2>&1 || warn "jq not found — guardrail hook will no-op on malformed input"

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  fail "Python 3.11+ required (found $PY_MAJOR.$PY_MINOR). Install python3.11 manually and re-run."
fi
ok "Python $PY_MAJOR.$PY_MINOR"

# ---------------------------------------------------------------------------
# Step 2: Install Claude Code CLI
# ---------------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  ok "claude cli already installed ($(command -v claude))"
else
  log "Installing Claude Code CLI via npm…"
  if command -v npm >/dev/null 2>&1; then
    $SUDO npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 \
      && ok "claude cli installed" \
      || warn "npm install @anthropic-ai/claude-code failed — install manually"
  else
    warn "npm missing — install Node.js then run: npm i -g @anthropic-ai/claude-code"
  fi
fi

# ---------------------------------------------------------------------------
# Step 2b: (optional) Install @openai/codex for the adversarial review step
# ---------------------------------------------------------------------------
if [ "$INSTALL_CODEX" = "1" ]; then
  if command -v codex >/dev/null 2>&1; then
    ok "codex already installed"
  else
    log "Installing @openai/codex…"
    $SUDO npm install -g @openai/codex >/dev/null 2>&1 \
      && ok "codex installed" \
      || warn "codex install failed — forge-ship.sh will skip review until installed"
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: Python dependencies
# ---------------------------------------------------------------------------
log "Installing Python dependencies…"
PIP_FLAGS="--quiet --upgrade"
if python3 -m pip install $PIP_FLAGS --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null; then
  ok "Python deps installed (system)"
elif python3 -m pip install $PIP_FLAGS -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null; then
  ok "Python deps installed (user)"
else
  fail "pip install failed — check network / pip config"
fi

# ---------------------------------------------------------------------------
# Step 4: Backup existing ~/.claude if present
# ---------------------------------------------------------------------------
if [ -d "$CLAUDE_DIR" ] && [ ! -f "$CLAUDE_DIR/.forge-prime-installed" ]; then
  BACKUP="$HOME/.claude.backup.$(date +%Y%m%d%H%M%S)"
  log "Backing up existing ~/.claude to $BACKUP"
  cp -r "$CLAUDE_DIR" "$BACKUP"
fi

# ---------------------------------------------------------------------------
# Step 5: Copy claude/ → ~/.claude/
# ---------------------------------------------------------------------------
log "Installing Claude OS layer to ~/.claude/…"
mkdir -p "$CLAUDE_DIR"
cp -r "$SCRIPT_DIR/claude/." "$CLAUDE_DIR/"
touch "$CLAUDE_DIR/.forge-prime-installed"
ok "Claude OS layer installed"

# ---------------------------------------------------------------------------
# Step 6: Wiki directory + local git repo
# ---------------------------------------------------------------------------
log "Creating wiki directory structure…"
mkdir -p "$WIKI_DIR/staging"
mkdir -p "$WIKI_DIR/articles/patterns"
mkdir -p "$WIKI_DIR/articles/anti-patterns"
mkdir -p "$WIKI_DIR/articles/decisions"
mkdir -p "$WIKI_DIR/articles/domain"
if [ ! -f "$WIKI_DIR/index.md" ]; then
  cat > "$WIKI_DIR/index.md" <<'EOF'
# Forge Prime Wiki
This wiki grows with every project. Agents read this before coding.
Index is regenerated by `forge compile`. Articles live in articles/.
EOF
fi
# Initialise as a git repo so write_article can commit locally even when no
# remote is configured (push degrades gracefully — see runner/wiki_writer.py).
if [ ! -d "$WIKI_DIR/.git" ]; then
  (
    cd "$WIKI_DIR"
    git init -q
    # Best-effort author config — only if the machine has none already.
    git config user.email >/dev/null 2>&1 || git config user.email "forge@localhost"
    git config user.name  >/dev/null 2>&1 || git config user.name  "Forge Prime"
    git add -A
    git commit -q -m "forge: initial wiki" || true
  )
fi
ok "Wiki directories + local git repo ready"

# ---------------------------------------------------------------------------
# Step 6b: Install guardrail hook
# ---------------------------------------------------------------------------
log "Installing guardrail hook to ~/.forge/prime/hooks/…"
HOOKS_DIR="$FORGE_STATE/hooks"
mkdir -p "$HOOKS_DIR"
cp "$SCRIPT_DIR/scripts/guardrail.sh" "$HOOKS_DIR/guardrail.sh"
chmod +x "$HOOKS_DIR/guardrail.sh"
ok "Guardrail hook installed"

# ---------------------------------------------------------------------------
# Step 7: Forge state directories + .env
# ---------------------------------------------------------------------------
log "Creating forge state dirs…"
mkdir -p "$FORGE_STATE/db"
mkdir -p "$FORGE_HOME"

ENV_FILE="$FORGE_HOME/.env"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
# Claude (Anthropic) auth happens through the `claude` CLI via OAuth.
# Run `claude login` once after install — no API key needed for Max users.
# Only set ANTHROPIC_API_KEY if you want to bypass OAuth for some reason.
# ANTHROPIC_API_KEY=

# Required for deepseek / gemini / other non-Anthropic model routing.
OPENROUTER_API_KEY=

FORGE_DEFAULT_MODEL=sonnet
EOF
  chmod 600 "$ENV_FILE"
  ok "Created $ENV_FILE (add OPENROUTER_API_KEY; Anthropic auth via 'claude login')"
else
  log ".env already exists — skipping"
fi

# ---------------------------------------------------------------------------
# Step 8: Install forge binary
# ---------------------------------------------------------------------------
log "Installing forge CLI…"
chmod +x "$SCRIPT_DIR/bin/forge"
if [ -w /usr/local/bin ]; then
  ln -sf "$SCRIPT_DIR/bin/forge" /usr/local/bin/forge
  ok "Installed forge → /usr/local/bin/forge"
elif [ -n "$SUDO" ]; then
  $SUDO ln -sf "$SCRIPT_DIR/bin/forge" /usr/local/bin/forge
  ok "Installed forge → /usr/local/bin/forge (via sudo)"
else
  mkdir -p "$HOME/.local/bin"
  ln -sf "$SCRIPT_DIR/bin/forge" "$HOME/.local/bin/forge"
  ok "Installed forge → $HOME/.local/bin/forge"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) warn "Add $HOME/.local/bin to PATH: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
  esac
fi

# ---------------------------------------------------------------------------
# Step 9: Pre-pull the MiniLM embedding model (so first `forge compile` is fast)
# ---------------------------------------------------------------------------
log "Pre-pulling sentence-transformers MiniLM model (~90 MB)…"
if python3 - <<'PY' >/dev/null 2>&1
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("all-MiniLM-L6-v2")
except Exception as exc:
    raise SystemExit(str(exc))
PY
then
  ok "Embedding model cached"
else
  warn "Could not pre-pull embedding model — first 'forge compile' will download it"
fi

# ---------------------------------------------------------------------------
# Step 10: Dashboard service (systemd on Linux / LaunchAgent on macOS)
# ---------------------------------------------------------------------------
if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1 && [ -n "$SUDO" -o "$(id -u)" -eq 0 ]; then
  log "Installing forge-dashboard systemd service (bind $DASHBOARD_BIND:8099)…"
  DASHBOARD_SERVICE="$SCRIPT_DIR/systemd/forge-dashboard.service"
  if [ -f "$DASHBOARD_SERVICE" ]; then
    sed -e "s|FORGE_PRIME_DIR|$SCRIPT_DIR|g" \
        -e "s|FORGE_DASHBOARD_BIND|$DASHBOARD_BIND|g" \
        "$DASHBOARD_SERVICE" > /tmp/forge-dashboard.service
    $SUDO cp /tmp/forge-dashboard.service /etc/systemd/system/forge-dashboard.service
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now forge-dashboard 2>/dev/null \
      && ok "Dashboard running on $DASHBOARD_BIND:8099" \
      || warn "systemctl enable/start failed — start manually"
  fi
elif [ "$OS" = "Darwin" ]; then
  log "macOS: creating LaunchAgent for dashboard…"
  LAUNCH_DIR="$HOME/Library/LaunchAgents"
  mkdir -p "$LAUNCH_DIR"
  PLIST_PATH="$LAUNCH_DIR/com.forge-prime.dashboard.plist"
  cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.forge-prime.dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(which python3)</string>
    <string>-m</string><string>uvicorn</string>
    <string>dashboard.app:app</string>
    <string>--host</string><string>$DASHBOARD_BIND</string>
    <string>--port</string><string>8099</string>
  </array>
  <key>WorkingDirectory</key><string>$SCRIPT_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$FORGE_HOME/dashboard.log</string>
  <key>StandardErrorPath</key><string>$FORGE_HOME/dashboard.err</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  launchctl load "$PLIST_PATH" 2>/dev/null && ok "LaunchAgent loaded" \
    || warn "Could not load LaunchAgent — run: launchctl load $PLIST_PATH"
else
  warn "No service manager detected — start dashboard manually: python3 -m uvicorn dashboard.app:app --host $DASHBOARD_BIND --port 8099"
fi

# ---------------------------------------------------------------------------
# Step 11: Weekly wiki compile cron (best-effort)
# ---------------------------------------------------------------------------
if command -v crontab >/dev/null 2>&1; then
  log "Installing weekly wiki compile cron (Sunday 2am)…"
  CRON_LINE="0 2 * * 0 cd $SCRIPT_DIR && $HOME/.local/bin/forge compile >> $FORGE_HOME/compile.log 2>&1"
  if ! command -v /usr/local/bin/forge >/dev/null 2>&1; then :; else
    CRON_LINE="0 2 * * 0 cd $SCRIPT_DIR && /usr/local/bin/forge compile >> $FORGE_HOME/compile.log 2>&1"
  fi
  ( crontab -l 2>/dev/null | grep -v "forge compile"; echo "$CRON_LINE" ) | crontab - 2>/dev/null \
    && ok "Weekly wiki compile cron installed" \
    || warn "Could not install cron — add manually: $CRON_LINE"
fi

# ---------------------------------------------------------------------------
# Step 12: Obsidian vault symlink (best-effort)
# ---------------------------------------------------------------------------
ln -sf "$WIKI_DIR" "$HOME/.obsidian-vault" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 13: forge doctor
# ---------------------------------------------------------------------------
log "Running forge doctor…"
"$SCRIPT_DIR/bin/forge" doctor || true

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Forge Prime installed."
echo "  Dashboard:      http://$DASHBOARD_BIND:8099"
echo "  Wiki vault:     $WIKI_DIR  (Obsidian: ~/.obsidian-vault)"
echo "  Add API keys:   $ENV_FILE"
echo ""
echo "  Next:"
echo "    1. claude login          # OAuth for Anthropic (Max plan) — no API key"
echo "    2. add OPENROUTER_API_KEY to $ENV_FILE   (for deepseek/gemini routing)"
echo "    3. mkdir my-project && cd my-project && git init && forge init"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
