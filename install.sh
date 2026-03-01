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
mkdir -p "$WORKSPACE_DIR/workspace/memory" "$WORKSPACE_DIR/workspace/skills"
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

# ── Model selection ───────────────────────────────────────────────────────────

MODELS=(
    "qwen3:8b|~6 GB |Fast, excellent tool calling (recommended)"
    "qwen3:4b|~3 GB |Compact — good tool calling, lower VRAM"
    "qwen3:1.7b|~2 GB  |Ultra-light — runs on CPU or minimal VRAM"
    "qwen2.5:7b-instruct|~6 GB |Top-tier tool calling"
    "qwen2.5:14b-instruct|~12 GB|More capable, higher quality"
)

echo ""
echo -e "\033[36m  Choose a model:\033[0m"
echo ""
printf "  \033[90m%-3s %-22s %-8s %s\033[0m\n" "#" "Model" "VRAM" "Description"
for i in "${!MODELS[@]}"; do
    IFS='|' read -r name vram desc <<< "${MODELS[$i]}"
    printf "  %-3s %-22s %-8s %s\n" "$((i+1))." "$name" "$vram" "$desc"
done
printf "  %-3s %s\n" "$((${#MODELS[@]}+1))." "Other — enter a model name manually"
echo ""
read -rp "  Enter number (default: 1): " model_choice
model_choice="${model_choice:-1}"
if [[ "$model_choice" == "$((${#MODELS[@]}+1))" ]]; then
    read -rp "  Model name: " SELECTED_MODEL
    [[ -z "$SELECTED_MODEL" ]] && SELECTED_MODEL="qwen3:8b"
elif ! [[ "$model_choice" =~ ^[0-9]+$ ]] || (( model_choice < 1 || model_choice > ${#MODELS[@]} )); then
    model_choice=1
    IFS='|' read -r SELECTED_MODEL _ _ <<< "${MODELS[$((model_choice-1))]}"
else
    IFS='|' read -r SELECTED_MODEL _ _ <<< "${MODELS[$((model_choice-1))]}"
fi
echo ""
ok "Selected: $SELECTED_MODEL"

step "Pulling $SELECTED_MODEL — this may take a few minutes..."
if ollama pull "$SELECTED_MODEL"; then
    ok "Model '$SELECTED_MODEL' ready"
else
    fatal "Model pull failed. Check your internet connection and try again, or run: ollama pull $SELECTED_MODEL"
fi

# Save chosen model to ~/.questchain/.env
if ! grep -q "^OLLAMA_MODEL=" "$DATA_ENV" 2>/dev/null; then
    echo "OLLAMA_MODEL=$SELECTED_MODEL" >> "$DATA_ENV"
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
