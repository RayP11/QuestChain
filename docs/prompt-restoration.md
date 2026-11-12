# Historical prompt restoration

PR21 restores the six stock prompt texts from pre-Perseus commit `036db8d`
(the parent baseline before `618cd55`). The historical text lives in
`questchain/prompts.py`; the factory resolves exact shipped stock versions at
runtime. It does **not** overwrite agents.json, user-authored text, tool selections,
identities, history, active selection, or schedules. Even whitespace-only edits,
empty overrides, CRLF, and JSON braces remain user text. Settings continue to show
the saved override; known stock text is upgraded only when constructing the agent.

## Deliberate compatibility differences

- No internal routing/delegation. Enabled optional Claude Code is still usable.
- Historical `write_todos` / Claude instructions are adapted when those tools
  are disabled. Missing web/scheduling tools are not represented as available.
- Planner gives concise reasons and tradeoffs rather than being instructed to
  expose step-by-step internal reasoning.
- Scheduler uses Cron terminology and the real `cron_list`, `cron_add`, and
  `cron_remove` names, checks duplicates, confirms timezone and schedule, and
  reports tool results. Unknown timezone requires a question, not a UTC guess.
- Current-time context includes the host timezone abbreviation and UTC offset;
  the host timezone is not assumed to be the user's IANA timezone.
- The long added Keeper appendix is removed. File boundaries, permission checks,
  interruption handling, and tool budgets remain unchanged.
- The UI still calls scheduled automations Quests. This is a prompt restoration,
  not a global product rename or an engine rollback.

## Limits

The old Scheduler prompt was already nearly identical to PR21's prompt except
for Quests wording. Restoring it is not evidence that a 4B model's thinking-token
exhaustion is fixed. Model configuration, inference budgets, and reasoning mode
are unchanged. Real-model smoke tests use isolated sessions with stub scheduling
execution; no real reminder is created by those tests.
