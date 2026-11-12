# QuestChain and manually selected specialists

QuestChain is the main configurable assistant. Select a specialist yourself for a focused tool loadout, just as in the original pre-Perseus flow. There is no automatic routing, delegate tool, private worker execution, or parent synthesis.

Use the chat portrait roster, Agents page or map to select an agent. In the terminal use `/agents` and Switch; Telegram `/agents` offers selection buttons. The active choice is persisted and shared across interfaces. Each interface keeps its own conversation; model context remains scoped to the selected agent. A run already submitted retains its original agent even if you switch.

## Configuration and tools

Edit each agent's name, role, model, prompt and enabled tools. The main QuestChain agent is configurable too. Empty tools means none; `all` explicitly enables the built-in integrations that are available. Specialist defaults are Researcher (web search/browse), Workspace (file tools), Builder (files/shell) and Scheduler (quests). Additional Planner and Custom roles remain available. A legacy Router profile is manually selectable, but cannot route.

Tool permissions are rechecked before execution. Missing tools are reported, not silently replaced by another agent. Tavily remains the configured web-search integration and requires its API key. Selecting a specialist never grants it another agent's tools.

Workspace has `read_file`, `write_file`, `edit_file`, `delete_file`, `ls`, `glob`, and `grep`. It verifies changes and preserves unrelated content. File paths remain inside the existing approved workspace boundary. Deletion rejects directories and symbolic links. Tool selection is not an operating-system sandbox.

Shell commands accept an integer timeout of 1–1800 seconds (60 by default).
Combined stdout and stderr may contain at most 256 KiB. Exceeding that budget
stops the command and its owned process group, and returns an error instead of
persisting oversized output. Narrow verbose commands before retrying; termination
does not undo their side effects. These limits protect output buffering, not the
command's own memory, disk, network, or OS permissions. Enabled shell and custom
Python tools still run with the application's OS privileges; detached processes
can escape process-group cleanup, and cancelling a custom Python thread does not
stop its side effects.

## Execution and migration

Scheduled quests run directly as their explicitly assigned agent. There is no second model synthesizing their output. Runs remain bounded, cancellable, and explicitly retryable. Restart interrupts unfinished runs without replaying actions. Check external effects before retrying.

Each run has a tool-call budget of 128 attempts by default; `QUESTCHAIN_MAX_TOOL_CALLS` accepts 1–10000. Every dispatch attempt counts, including denied and failed calls. The 30-iteration and 30-minute limits still apply. A retry or new scheduled occurrence has a fresh budget. A tool budget is not an operating-system sandbox.

The manual-flow migration preserves existing IDs, selected tools, custom prompts, progression, conversations and schedules. It saves the previous roster before setting routing metadata inactive. If master archived the original `default` and no main/default is currently active, its exact saved configuration is restored as main, without expanding tools. An existing active main/default takes precedence. Other archived definitions remain available for explicit import; previously paused quests stay paused. No archived data is deleted and no schedule is automatically resumed. Existing legacy routing prompts are preserved as user configuration, with runtime instructions and tool enforcement disabling delegation.
