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
