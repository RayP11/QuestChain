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
    if [[ "$OS" == "Darwin" ]]; then
        if ! command_exists brew; then
            # Homebrew requires Xcode Command Line Tools
            if ! xcode-select -p &>/dev/null; then
                step "Installing Xcode Command Line Tools (required for Homebrew)..."
                xcode-select --install 2>/dev/null || true
                warn "A dialog may have appeared — click Install and wait for it to finish."
                warn "Press Enter here once the Command Line Tools are installed."
                read -r
            fi
            step "Installing Homebrew..."
            # Prime sudo credentials so NONINTERACTIVE=1 doesn't fail silently
            sudo -v
            NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Add Homebrew to PATH for Apple Silicon Macs (/opt/homebrew not on PATH by default)
            if [[ "$(uname -m)" == "arm64" ]] && [[ -x "/opt/homebrew/bin/brew" ]]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
            command_exists brew || fatal "Homebrew installation failed. Install it manually from https://brew.sh then re-run."
            ok "Homebrew installed"
        fi
        step "Installing Ollama via Homebrew..."
        brew install ollama
        ok "Ollama installed"
    else
        step "Installing Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installed"
    fi
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
mkdir -p "$WORKSPACE_DIR/workspace/memory" "$WORKSPACE_DIR/workspace/skills"
mkdir -p "$DATA_DIR"

# Pin the workspace in ~/.questchain/.env so 'questchain' finds it from any terminal.
if [ ! -f "$DATA_ENV" ] || ! grep -q "^QUESTCHAIN_WORKSPACE_DIR=" "$DATA_ENV"; then
    echo "QUESTCHAIN_WORKSPACE_DIR=$WORKSPACE_DIR" >> "$DATA_ENV"
    ok "Workspace pinned: $WORKSPACE_DIR"
else
    ok "Workspace already configured ($(grep '^QUESTCHAIN_WORKSPACE_DIR=' "$DATA_ENV" | cut -d= -f2-))"
fi

# ── Default model ─────────────────────────────────────────────────────────────

DEFAULT_MODEL="qwen3:8b"

step "Starting Ollama service..."
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    ok "Ollama service already running"
else
    if [[ "$OS" == "Darwin" ]]; then
        nohup ollama serve > /dev/null 2>&1 &
    else
        # On Linux the install script sets up a systemd service; fall back to
        # launching in the background if systemd didn't start it yet.
        if command_exists systemctl && systemctl is-active --quiet ollama 2>/dev/null; then
            ok "Ollama systemd service is active"
        else
            nohup ollama serve > /dev/null 2>&1 &
        fi
    fi
    # Wait up to 30 seconds for Ollama to become ready
    step "Waiting for Ollama to start..."
    for i in $(seq 1 15); do
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            ok "Ollama is ready"
            break
        fi
        if [[ $i -eq 15 ]]; then
            fatal "Ollama did not start in time. Try running 'ollama serve' manually, then re-run this installer."
        fi
        sleep 2
    done
fi

step "Pulling default model ($DEFAULT_MODEL) — this may take a few minutes..."
warn "You can change the model later with: questchain start -m <model-name>"
if ollama pull "$DEFAULT_MODEL"; then
    ok "Model '$DEFAULT_MODEL' ready"
else
    fatal "Model pull failed. Check your internet connection and try again, or run: ollama pull $DEFAULT_MODEL"
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
