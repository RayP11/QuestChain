# Your agents

QuestChain uses a coordinator and focused specialists. Select Perseus for automatic routing, or select any specialist to speak to it directly. Direct chat skips the routing model call.

| Starter name | Role | Work |
| --- | --- | --- |
| Perseus | Coordinator | Choose a specialist, clarify requests, communicate status |
| Argus | Researcher | Research external information and cite sources |
| Athena | Workspace knowledge | Find, summarize, and organize workspace files and notes |
| Talos | Builder | Inspect code, implement changes, and test them |
| Zeus | Planning & advising | Plan projects, compare options, and advise on priorities |

Names are editable. Stable IDs identify agents and cron assignments. The scheduling and Custom role presets remain available when creating additional agents.

## Create or edit an agent

Use **Settings → New Agent** in the web UI, `/agents` in the terminal, or `/agents` in Telegram. Each interface supports name, role, local model override, explicit tools, system prompt, when-to-call guidance, routing eligibility, exclusions, and example requests.

The coordinator sees eligible agents' invocation guidance and tool names. It does not receive their system prompts. Changes take effect for new requests without restarting. An empty tool selection grants no tools; “all” is an explicit selection. Required integrations appear as availability issues when not configured.

For example, create Quill with no tools, a prompt to rewrite supplied prose, and guidance such as “Draft or polish messages and release notes from supplied text.” Enable automatic routing to let Perseus choose Quill immediately.

## Responses and follow-ups

A routed request displays **Perseus → Argus**, followed by Argus's own answer. Perseus does not rewrite that answer. Switching the selected agent while work is running does not change its owner or label. Requests share one execution queue to limit concurrent local inference.

Select a specialist in the chat agent list to speak to it directly, or keep Perseus selected for automatic routing. Implicit follow-ups depend on the local model's routing accuracy; if it chooses poorly, select the specialist directly.

Perseus receives the six most recent finished turns from the current conversation and can answer questions about that history. Telegram keeps this context within the same chat until you start a new conversation. Other chats and previous scheduled job occurrences are not included automatically.

The web UI restores saved messages after a reload, shows failures and partial responses, and supports cancellation and explicit retry. Terminal `/runs`, `/retry [run ID]`, and `/history` expose saved task records. Telegram supports `/cancel` and `/retry`. Retrying creates a new attempt; stopping a run cannot undo completed tool actions.

Chat messages keep Markdown formatting while responses stream and after a reload: headings, emphasis, lists, links, blockquotes, tables, and code blocks. Raw HTML is displayed as text, and image references appear as links.

## Legacy agents

On first launch of the new system, old agent definitions move out of the active roster into `~/.questchain/legacy/agents.json`. A backup of the original definitions remains in `agents.v1.bak`. The new Greek roster is created once. Deleting a preset does not recreate it on every launch.

Archived agents are inactive and excluded from routing. Existing transcripts and progression remain on disk under their original IDs. Legacy transcripts can be read from the terminal `/history` menu; their historical authors are not guessed.

In Settings, each archived agent also has a **Delete** action with confirmation. This removes its archived definition without removing active agents, transcripts, or progression. The Legacy agents section is hidden when no unmigrated archived agents remain.

Migration is optional:

- Web: **Settings → Legacy agents → Migrate [name]**.
- Terminal: `/legacy`, then `/legacy migrate ID`.
- Telegram: `/agents`, then **Migrate legacy: [name]**.

Migration preserves the original ID, name, model, prompt, and tools, converts the old role identifier when known, and leaves automatic routing disabled. Review the imported settings and invocation guidance before enabling it. The archived copy remains available as a backup.

Cron jobs retain their assigned IDs. A job whose agent is archived reports a missing owner until that agent is migrated or the job is explicitly reassigned. It never silently falls back to a more capable agent.

## Automation and storage

Assign a cron job to Perseus for routing at execution time, or to a specialist for direct execution. The ordinary time picker remains in the web UI. Open a job to see live progress, attributed results, execution status, delivery status, and previous runs.

Run records and event checkpoints live in `~/.questchain/tasks.sqlite3`; definitions and schedules remain in JSON files. Restarted unfinished runs are marked interrupted and require an explicit retry. Delivery failure does not execute the task again. Only one process can own a data directory at a time.

Agent tools can act on the workspace. Tool selection is enforced before each call, including revocation during a run; it is not an operating-system sandbox.
