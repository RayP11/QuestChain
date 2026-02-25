"""Cron job management tools for QuestChain."""

from langchain_core.tools import tool


@tool
def cron_add(
    name: str,
    cron_expression: str,
    prompt: str,
    timezone: str = "UTC",
    agent_id: str | None = None,
) -> str:
    """Schedule a recurring cron job that will run the given prompt on a schedule.

    The cron_expression uses standard 5-field format: minute hour day month weekday.
    Examples:
      - "0 9 * * *"    = every day at 9:00 AM
      - "*/30 * * * *"  = every 30 minutes
      - "0 9 * * 1"    = every Monday at 9:00 AM
      - "0 0 1 * *"    = first day of every month at midnight

    Args:
        name: A human-readable name for this job.
        cron_expression: 5-field cron schedule (minute hour day month weekday).
        prompt: The prompt/instruction to execute when the job fires.
        timezone: IANA timezone name (default: UTC). Examples: America/New_York, Europe/London.
        agent_id: Optional ID of a custom agent to run this job with. If omitted or
            not found, the default QuestChain agent is used. Agent IDs can be found via
            the /agents command.
    """
    from questchain.scheduler import get_scheduler

    try:
        scheduler = get_scheduler()
    except RuntimeError as e:
        return str(e)

    try:
        job = scheduler.add_job(
            name=name,
            cron_expression=cron_expression,
            prompt=prompt,
            timezone_str=timezone,
            agent_id=agent_id,
        )
        agent_line = f"\n  Agent: {job['agent_id']}" if job.get("agent_id") else ""
        return (
            f"Cron job created successfully.\n"
            f"  ID: {job['id']}\n"
            f"  Name: {job['name']}\n"
            f"  Schedule: {job['cron_expression']} ({job['timezone']}){agent_line}\n"
            f"  Prompt: {job['prompt']}"
        )
    except ValueError as e:
        return f"Invalid cron expression: {e}"
    except Exception as e:
        return f"Failed to create cron job: {e}"


@tool
def cron_list() -> str:
    """List all scheduled cron jobs with their IDs, schedules, and prompts."""
    from questchain.scheduler import get_scheduler

    try:
        scheduler = get_scheduler()
    except RuntimeError as e:
        return str(e)

    jobs = scheduler.list_jobs()
    if not jobs:
        return "No cron jobs scheduled."

    lines = [f"Scheduled cron jobs ({len(jobs)}):"]
    for j in jobs:
        status = "enabled" if j.get("enabled", True) else "disabled"
        agent_line = f"\n    Agent: {j['agent_id']}" if j.get("agent_id") else ""
        lines.append(
            f"\n  [{j['id']}] {j['name']}\n"
            f"    Schedule: {j['cron_expression']} ({j.get('timezone', 'UTC')})\n"
            f"    Prompt: {j['prompt']}{agent_line}\n"
            f"    Status: {status}"
        )
    return "\n".join(lines)


@tool
def cron_remove(job_id: str) -> str:
    """Remove a scheduled cron job by its ID.

    Args:
        job_id: The ID of the cron job to remove (shown by cron_list).
    """
    from questchain.scheduler import get_scheduler

    try:
        scheduler = get_scheduler()
    except RuntimeError as e:
        return str(e)

    try:
        removed = scheduler.remove_job(job_id)
        return f"Removed cron job '{removed['name']}' (ID: {removed['id']})"
    except KeyError as e:
        return str(e)
    except Exception as e:
        return f"Failed to remove cron job: {e}"


def create_cron_tools() -> list:
    """Return all cron management tools."""
    return [cron_add, cron_list, cron_remove]
