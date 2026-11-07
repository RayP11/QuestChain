# Quests

Use the **Quests** page to automate recurring work. Enter a name and instructions, type or pick a time, choose a daily, weekday, weekly, or monthly repeat, and select a timezone and optional agent. Then choose **Save Quest**. Select a saved job to edit, pause/resume, run now, or delete it. The page shows the next run and the last result or error.

Jobs run only while QuestChain is open. They persist across restarts. Pausing or deleting a job stops future runs; an already running job finishes. Missed runs are not replayed after restarting.

The UI displays schedules in plain language. Existing custom schedules stay unchanged unless you select a new repeat option.

## Terminal and Telegram schedule format

Five fields: `minute hour day month weekday`. Use IANA timezones, such as `America/New_York` or `UTC`. Weekday names avoid ambiguity; numeric weekdays are Monday=0 through Sunday=6.

| Schedule | Expression |
|---|---|
| Every 30 minutes | `*/30 * * * *` |
| Every day at 9 AM | `0 9 * * *` |
| Weekdays at 9 AM | `0 9 * * mon-fri` |

## Terminal and Telegram

In the terminal, `/quests` opens an interactive manager. Telegram `/quests` lists jobs and command help. Both also accept these commands (replace `ID` with the displayed job ID):

```text
/quests add Morning summary | 0 9 * * mon-fri | America/New_York | Summarize my notes
/quests edit ID | New name | 0 10 * * * | UTC | Updated instructions
/quests list
/quests show ID
/quests pause ID
/quests resume ID
/quests run ID
/quests delete ID
```

An optional final `| agent-id` assigns a specific agent. The web editor supports multiline instructions, including literal pipe characters. Results appear in the web job details and in the terminal, or on Telegram when connected. Telegram commands remain restricted to the configured owner.

## Compatibility and the retired quest-file runner

The quest runner, quest menu, and `/quest` commands have been removed. Existing quest files are preserved but ignored. Recreate tasks you want automated as scheduled Quests. Existing cron schedules continue to load normally; historical quest progression counts are retained as completed jobs.

Quests is the new name for the persistent scheduler. `/quests` is the preferred command; `/cron` remains a compatible alias. Existing schedules, IDs, paused state, results, and history are unchanged. Technical cron expressions, `cron_*` tool names and WebSocket messages, and the `cron_jobs.json` storage file retain their names. The `cron-jobs` skill and documentation URL remain stable. This rebrand does not restore the retired quest-file runner, `/quest` commands, or `--quests` / `--no-quests` startup flags.

## Storage and recovery

Quest changes are written as a complete temporary snapshot in the same directory,
flushed and synced, then atomically replace `cron_jobs.json`. The replacement is
the commit point: only afterward are in-memory state and live schedules changed.
A failure before replacement leaves the previous file, schedule and results
unchanged and returns an error. New snapshot files use private temporary-file
permissions; existing POSIX permission bits are preserved without changing the
parent directory's permissions.

Malformed or unreadable existing files stop scheduler startup instead of being
silently replaced with an empty list. Repair or restore the file and restart.
Missing owners must be durably paused before any schedule starts. Restart loads
only the committed snapshot and schedules future occurrences; it does not replay
missed work or uncommitted temporary files.

On POSIX, the parent directory is synced after replacement. If that sync fails,
the change is already committed and a warning reports uncertain crash durability;
it is not reported as a rollback. Windows does not use this directory-sync step.
If applying committed state to the live scheduler fails, scheduling is paused and
the error explicitly says the state was saved. Repair the cause and restart;
already running tasks are not undone. These guarantees assume a single writer and
a local filesystem supporting atomic replacement; they do not guarantee behavior
under storage hardware failure, network filesystem semantics, or concurrent
external edits. Existing runtime deduplication and interrupted-run recovery remain
separate from schedule metadata persistence.
