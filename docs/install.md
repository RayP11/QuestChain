<div align="center"><img src="../assets/pixel_idle.png" alt="" width="280"/></div>

# Install

## Step 1: Install Ollama

Ollama runs the AI model on your machine. Download and install it from [ollama.com/download](https://ollama.com/download), then start it:

```bash
ollama serve
```

Leave it running and open a new terminal for the next step.

---

## Step 2: Install QuestChain

=== "macOS / Linux"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/RayP11/QuestChain/master/install.sh | bash
    ```

=== "Windows (PowerShell)"

    ```powershell
    powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/RayP11/QuestChain/master/install.ps1 | iex"
    ```

That's it. The installer sets everything up automatically.

---

## Step 3: Run

```bash
questchain start --web
```

Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** in your browser and start chatting.

On first run, QuestChain walks you through a short setup — it learns your name, what you do, and how you like to work. After that, it remembers.

!!! tip "Enable web search (optional)"
    Type `/tavily` in the chat and paste in your free API key from [tavily.com](https://tavily.com) to give your agent live web search.

