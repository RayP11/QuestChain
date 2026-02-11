---
name: cron-jobs
description: Schedule recurring tasks that run automatically on a cron schedule and deliver results via Telegram
---

# Cron Jobs Skill

## When to Use

Use the cron tools when the user asks to:
- Schedule, automate, or repeat a task on a timer
- Set up a reminder or recurring notification
- Run something daily, weekly, hourly, etc.
- Create a morning briefing, evening summary, or periodic check

Look for keywords like: "schedule", "every day", "every morning", "remind me", "automate", "recurring", "cron", "at 9am", "weekly", "daily".

## When NOT to Use

Do not use cron tools for:
- One-time immediate tasks (just do them directly)
- General questions or conversation
- Tasks that don't need to repeat

## Cron Expression Reference

Cron uses a 5-field format: `minute hour day month weekday`

| Field     | Values      | Special |
|-----------|-------------|---------|
| minute    | 0-59        | * , - / |
| hour      | 0-23        | * , - / |
| day       | 1-31        | * , - / |
| month     | 1-12        | * , - / |
| weekday   | 0-6 (0=Mon) | * , - / |

### Common Examples

| Schedule              | Expression      |
|-----------------------|-----------------|
| Every day at 9 AM     | `0 9 * * *`     |
| Every Monday at 9 AM  | `0 9 * * 0`     |
| Every hour            | `0 * * * *`     |
| Every 30 minutes      | `*/30 * * * *`  |
| Weekdays at 8 AM      | `0 8 * * 0-4`   |
| First of month at noon| `0 12 1 * *`    |
| Every day at 6:30 PM  | `30 18 * * *`   |

## Workflow

1. **Create a job**: Use `cron_add` with a name, cron expression, prompt, and timezone.
2. **Verify**: Use `cron_list` to confirm the job was created.
3. **Remove**: Use `cron_remove` with the job ID to delete a job.

## Important Notes

- Always ask the user for their timezone if they don't specify one. Common timezones: `America/New_York`, `America/Chicago`, `America/Denver`, `America/Los_Angeles`, `Europe/London`, `Asia/Tokyo`.
- Write clear, detailed prompts for jobs — the prompt is what gets sent to the agent when the job fires.
- Cron jobs only work in Telegram mode (`--telegram`). If the user is in CLI mode, explain this.
- Each job gets its own conversation thread, so it won't interfere with the user's interactive chat.
