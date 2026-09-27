# Cron Jobs

Use the **Cron Jobs** page to automate recurring work. Enter a name and instructions, type or pick a time, choose a daily, weekday, weekly, or monthly repeat, and select a timezone and optional agent. Then choose **Save Job**. Select a saved job to edit, pause/resume, run now, or delete it. The page shows the next run and the last result or error.

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

In the terminal, `/cron` opens an interactive manager. Telegram `/cron` lists jobs and command help. Both also accept these commands (replace `ID` with the displayed job ID):

```text
/cron add Morning summary | 0 9 * * mon-fri | America/New_York | Summarize my notes
/cron edit ID | New name | 0 10 * * * | UTC | Updated instructions
/cron list
/cron show ID
/cron pause ID
/cron resume ID
/cron run ID
/cron delete ID
```

An optional final `| agent-id` assigns a specific agent. The web editor supports multiline instructions, including literal pipe characters. Results appear in the web job details and in the terminal, or on Telegram when connected. Telegram commands remain restricted to the configured owner.

## Replacing quests

The quest runner, quest menu, and `/quest` commands have been removed. Existing quest files are preserved but ignored. Recreate tasks you want automated as cron jobs. Existing cron jobs continue to load normally; historical quest progression counts are retained as completed jobs.
