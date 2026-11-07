# Your assistant and subagents

Every terminal, web, and Telegram text or voice message goes to one main assistant. Its persisted default name is **QuestChain**; rename it in onboarding or agent settings. Viewing or configuring a worker never changes the chat destination.

The main assistant owns planning, handles simple work directly, delegates bounded tasks when useful, reviews structured worker outcomes, and gives its own final answer.

| Default worker | Role | Work |
| --- | --- | --- |
| Researcher | Explorer | Research external information and cite sources |
| Workspace | Keeper | Read, create, edit, delete, summarize, and organize workspace files |
| Builder | Builder | Inspect, implement, and test software |
| Scheduler | Scheduler | Manage recurring jobs |

Planner is an optional custom/legacy role, not a built-in worker. Planning belongs to the main assistant. Custom workers, including legacy Router definitions, remain configurable.

## Configuration and tools

Use Settings in the web UI or `/agents` in terminal or Telegram to edit the assistant and create subagents. Definitions retain stable IDs, editable names, explicit tools, system prompts, invocation guidance, exclusions, examples, and model overrides. A blank model inherits the running default; an explicit override stays attached to that definition.

Enable automatic routing after providing when-to-call guidance. The main assistant receives eligible workers' guidance and tool names, not their system prompts. An empty tool selection grants no tools; `all` is an explicit selection. Unavailable integrations are reported in settings. Tool permissions are rechecked immediately before execution.

Workspace has `read_file`, `write_file`, `edit_file`, `delete_file`, `ls`, `glob`, and `grep`. It verifies changes and preserves unrelated content. File paths remain inside the existing approved workspace boundary. Deletion rejects directories and symbolic links. Tool selection is not an operating-system sandbox.

## Conversation and execution

New Chat starts fresh; reopening history restores that interface's conversation. Terminal, web, and Telegram histories remain separate. Shared profile answers in `ABOUT.md` reach the main assistant in all interfaces. Old transcripts retain their historical authors, and new replies go to the main assistant.

`delegate_to_agent` executes a bounded worker task and returns its status, result, error, run ID, and verification flag. Workers have no recursive delegation tool. Their tokens, tool events, audio, and internal run records stay out of user-facing chat and reconnect snapshots. The main assistant may show read-only progress and synthesizes its own answer.

One root execution owns the run slot; its children execute inline without queueing behind their waiting parent or reacquiring that slot. Cancel stops the root and its active child. Failures return to the parent for review. Retry is explicit and cannot undo or safely repeat already completed external effects. Restart marks unfinished runs interrupted and does not replay actions.

### Aggregate tool-call budget

Each root run has a shared budget of **128 tool-call attempts** by default. The
main assistant and every private worker use the same counter. A delegation costs
one attempt in addition to the worker's tools; the initial dispatch of an
explicitly assigned scheduled worker also costs one. Every call in a model batch
counts individually. Unknown tools, invalid arguments, permission denials, tool
errors and cancellation do not refund an admitted attempt.

Set `QUESTCHAIN_MAX_TOOL_CALLS=512` in your environment or `.env` and restart for
larger trusted workloads. Values must be integers from **1 to 10000**; invalid
values fail startup, and there is no unlimited setting. This setting does not
raise the separate 30-iteration-per-agent or 30-minute runtime deadline. Break
longer work into explicitly reviewed runs when those limits apply.

When the next attempt would exceed the limit, no tool or delegation starts for
that attempt. Exhaustion propagates out of workers and fails the root run; it is
not fed back as a recoverable tool error for the model to retry. Completed results
are retained, and undispatched calls are recorded as **not started**, not as
unknown side effects. Using exactly the allowance still permits a final text
answer, subject to the existing iteration/deadline limits. There is no automatic
retry or rollback. Review existing effects before `/retry`, which creates a new
run with a fresh budget. Each future scheduled occurrence also gets a new budget.

Run records save `tool_call_limit` and aggregate `tool_calls_used` at execution
exit, including failure and cancellation. A child's count is a snapshot of the
shared total at its exit, not that child's own usage. These are diagnostic
snapshots, not a crash-durable per-call ledger; restart still interrupts unfinished
work without replay. Standalone engine `Agent.run` calls (including the legacy
Telegram/scheduler paths) get a fresh default budget; runtime delegation passes
the existing object explicitly. Concurrent engine calls sharing that object
cannot overdraw it. Workers remain prohibited from recursively delegating.

The budget bounds engine dispatch attempts, not model tokens, response size,
database retention, wall time inside a tool, or the actions a tool performs
internally (including external coding agents). It does not cancel already
admitted concurrent work or roll back effects. Enabled shell/custom Python still
has the application's OS privileges: custom code can call functions directly or
start its own engine without sharing the budget. This is not a sandbox against
untrusted Python. Cancelling a synchronous Python tool's waiting task does not
stop its thread or undo its side effects; interrupted in-flight calls retain an
unknown-outcome warning.

## Archive-and-import upgrade

Migration is versioned and restart-safe. Before replacing the old roster, QuestChain saves the data directory under `~/.questchain/legacy/before-single-assistant-v4/`, including previous archives, definitions, selection, progression, history, and a consistent SQLite backup containing committed WAL data. Existing backups are preserved.

The latest legacy definitions move to `legacy/agents.json`, and a new main assistant and generic worker roster are seeded. No legacy agent is silently selected as the main assistant. Existing modern main definitions and user-created workers remain; an old built-in Planner is archived intact, even if customized. A user-created Planner stays active. Only an exact previous default main prompt receives the planning instruction upgrade; custom prompts remain unchanged.

Import an archived definition deliberately:

- Web: Settings → Legacy agents → Migrate.
- Terminal: `/legacy`, then `/legacy migrate ID`.
- Telegram: `/agents`, then Migrate legacy.

Import preserves ID, name, prompt, model, and tools, translates known legacy roles, and creates a subagent with automatic routing off. Review before enabling it. Import does not change the chat target or resume scheduled jobs. Archived definitions can be deleted with confirmation without deleting transcripts or progression.

## Scheduled work

Jobs retain their IDs and occurrence records. Migration pauses legacy or missing-owner jobs; review the owner and explicitly resume them. Importing an old ID never silently resumes its schedules. Missing-owner jobs cannot resume until an owner is available.

Jobs assigned to the main assistant may delegate normally. An explicitly assigned worker executes privately, then the main assistant reviews its outcome and produces the final response. Scheduled occurrences use fresh context. Delivery failures and duplicate occurrence callbacks do not rerun work.

Run records live in `tasks.sqlite3`; definitions and schedules remain JSON. Only one running process may own the data directory. `/runs`, `/history`, `/cancel`, and `/retry` expose saved work in terminal and Telegram; the web UI provides history and run controls.
