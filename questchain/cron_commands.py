"""Shared terminal and Telegram commands for the live cron scheduler."""

HELP = (
    "Cron jobs run while QuestChain is open. Schedules use the chosen timezone.\n"
    "Use weekday names (mon-sun); numeric weekdays are 0=Monday to 6=Sunday.\n"
    "/cron — list jobs\n"
    "/cron add Name | 0 9 * * mon | UTC | Instructions | optional-agent-id\n"
    "/cron edit ID | Name | Schedule | Timezone | Instructions | optional-agent-id\n"
    "/cron show ID\n/cron pause ID\n/cron resume ID\n/cron run ID\n/cron delete ID"
)


def execute(command: str) -> str:
    from questchain.scheduler import get_scheduler

    scheduler = get_scheduler()
    action, _, args = command.strip().partition(" ")
    if action in ("", "list"):
        jobs = scheduler.list_jobs()
        lines = ["Cron Jobs"]
        for job in jobs:
            status = "running" if job["running"] else "enabled" if job["enabled"] else "paused"
            lines.append(f"[{job['id']}] {job['name']} — {job['cron_expression']} ({job['timezone']}) · {status}")
        return "\n".join(lines + ([] if jobs else ["No cron jobs configured."]) + ["", HELP])
    if action == "help":
        return HELP
    if action in ("add", "edit"):
        fields = [part.strip() for part in args.split("|")]
        job_id = fields.pop(0) if action == "edit" else None
        if len(fields) not in (4, 5):
            raise ValueError(HELP)
        name, schedule, tz, prompt = fields[:4]
        values = dict(name=name, cron_expression=schedule, timezone_str=tz,
                      prompt=prompt, agent_id=fields[4] if len(fields) == 5 else None)
        job = scheduler.update_job(job_id, **values) if job_id else scheduler.add_job(**values)
        return f"Saved cron job [{job['id']}] {job['name']}"
    if action == "show":
        job = scheduler.get_job(args.strip())
        return "\n".join(f"{key}: {value}" for key, value in job.items())
    if action in ("pause", "resume"):
        scheduler.set_enabled(args.strip(), action == "resume")
        return "Cron job paused." if action == "pause" else "Cron job resumed."
    if action == "run":
        scheduler.run_now(args.strip())
        return "Cron job queued. Results will appear when it finishes."
    if action == "delete":
        scheduler.remove_job(args.strip())
        return "Cron job deleted. A run already in progress will finish."
    raise ValueError(HELP)
