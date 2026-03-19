<div align="center"><img src="../assets/sage2.png" alt="" width="280"/></div>

# Your Agents

QuestChain isn't one agent — it's a party. Each agent has a name, a class, a personality, and a set of tools matched to a specific kind of work.

You can create as many agents as you want, switch between them mid-conversation, and run different ones for different tasks.

---

## Agent classes

| Class | Best for |
|---|---|
| Keeper 📚 | Organizing files, taking notes, managing knowledge |
| Explorer 🔭 | Web research, finding information, summarizing sources |
| Builder ⚒️ | Writing and editing code, debugging, shipping features |
| Planner 🔮 | Planning projects, breaking down goals, strategic thinking |
| Scheduler ⏱️ | Setting up recurring tasks and automated jobs |
| Custom 🌀 | Whatever you want — you define the role and tools |

Each class comes pre-configured with the right tools and a personality tuned for that domain. A Keeper knows not to run shell commands. An Explorer knows to verify sources before drawing conclusions. A Builder knows to delegate heavy coding to Claude Code.

---

## Why have multiple agents?

A focused agent makes better decisions. An agent that only does research doesn't have to think about file editing or scheduling — it just searches, reads, and synthesizes. That focus translates directly to better results, especially on smaller local models.

It also means you can build a *team*. Have a Keeper named **Archivist** who manages your notes, an Explorer named **Scout** who handles research, and a Builder named **Jarvis** who writes code. Switch between them with `/agents`.

---

## Creating an agent

Use `/agents` in the chat to open the agent manager. From there you can:

- **Create** a new agent — give it a name, pick a class
- **Switch** to a different agent
- **Edit** an existing agent's name, class, or model

Each agent remembers its own conversation history and builds its own progression over time.

---

## Custom agents

The Custom class is a blank slate. You decide what tools it has and how it behaves. Useful for highly specific workflows — a dedicated agent for one project, a client, or a niche task.

---

## Per-agent model override

You can run different models on different agents. Run your Scheduler on a lightweight `qwen3:1.7b` to save resources, and your Builder on a more capable `qwen3:8b` for complex coding tasks. Set this when creating or editing an agent via `/agents`.
