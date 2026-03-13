#!/usr/bin/env bash
# QuestChain installer for macOS and Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/RayP11/QuestChain/main/install.sh | bash

set -euo pipefail

# ── Helpers ───────────────────────────────────────────────────────────────────

step()  { echo -e "\033[36m  --> $*\033[0m"; }
ok()    { echo -e "\033[32m  OK  $*\033[0m"; }
warn()  { echo -e "\033[33m  !   $*\033[0m"; }
fatal() { echo -e "\033[31m  ERR $*\033[0m"; exit 1; }

command_exists() { command -v "$1" &>/dev/null; }

# ── Banner ────────────────────────────────────────────────────────────────────

echo ""
echo -e "\033[35m  QuestChain\033[0m"
echo -e "\033[90m  ----------- Installer\033[0m"
echo ""

OS="$(uname -s)"

# ── Ollama ────────────────────────────────────────────────────────────────────

step "Checking Ollama..."
if command_exists ollama; then
    ok "Ollama already installed ($(ollama --version 2>&1 | head -1))"
else
    echo ""
    warn "Ollama is not installed."
    echo -e "  Install it from: \033[36mhttps://ollama.com/download\033[0m"
    echo -e "  Then run \033[36mollama serve\033[0m to start it, and re-run this installer."
    echo ""
    exit 1
fi

# ── uv ────────────────────────────────────────────────────────────────────────

step "Checking uv..."
if command_exists uv; then
    ok "uv already installed ($(uv --version))"
else
    step "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv installs to ~/.local/bin — add to PATH for the rest of this script
    export PATH="$HOME/.local/bin:${PATH:-}"
    if ! command_exists uv; then
        fatal "uv installation failed. Try manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi
    ok "uv installed ($(uv --version))"
fi

# Ensure uv tools directory is on PATH
export PATH="$HOME/.local/bin:${PATH:-}"

# ── QuestChain ────────────────────────────────────────────────────────────────

step "Installing QuestChain..."
uv tool install "git+https://github.com/RayP11/QuestChain" --reinstall
ok "QuestChain installed"

# ── Workspace ─────────────────────────────────────────────────────────────────

WORKSPACE_DIR="$HOME/questchain"
DATA_DIR="$HOME/.questchain"
DATA_ENV="$DATA_DIR/.env"

step "Setting up workspace at $WORKSPACE_DIR..."
mkdir -p "$WORKSPACE_DIR/workspace/memory" "$WORKSPACE_DIR/workspace/quests"
mkdir -p "$DATA_DIR"

# Pin the workspace in ~/.questchain/.env so 'questchain' finds it from any terminal.
if [ ! -f "$DATA_ENV" ] || ! grep -q "^QUESTCHAIN_WORKSPACE_DIR=" "$DATA_ENV"; then
    echo "QUESTCHAIN_WORKSPACE_DIR=$WORKSPACE_DIR" >> "$DATA_ENV"
    ok "Workspace pinned: $WORKSPACE_DIR"
else
    ok "Workspace already configured ($(grep '^QUESTCHAIN_WORKSPACE_DIR=' "$DATA_ENV" | cut -d= -f2-))"
fi

# ── Ollama running check ──────────────────────────────────────────────────────

step "Checking Ollama is running..."
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    ok "Ollama is running"
else
    echo ""
    warn "Ollama is not running."
    echo -e "  Start it with: \033[36mollama serve\033[0m"
    echo -e "  Then re-run this installer."
    echo ""
    exit 1
fi


# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "\033[35m  QuestChain is ready!\033[0m"
echo ""
echo -e "\033[90m  Run:\033[0m"
echo -e "      \033[36mquestchain start\033[0m"
echo ""
warn "If 'questchain' is not found, restart your terminal or run:"
echo -e "      \033[36msource ~/.bashrc\033[0m  (Linux)"
echo -e "      \033[36msource ~/.zshrc\033[0m   (macOS)"
echo ""
