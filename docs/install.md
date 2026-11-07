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

!!! tip "Web search without setup (experimental)"
    Fresh installs use DDGS / DuckDuckGo without a key or service setup. Queries and network IP leave the machine. Read [provider terms, privacy, and limitations](web-search.md) before production use. SearXNG and Tavily remain optional; `/tavily` saves a Tavily key.

