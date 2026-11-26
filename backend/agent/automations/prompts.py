"""Prompt context for chat-guided automation setup and follow-up.

The UI's "Create automation" button opens a new reasoning chat whose first
message is this prompt (served by ``GET /api/automations/create-prompt``). The
agent then drafts the automation, proposes a schedule and destination, confirms
with the user, and creates it via the ``cronjob`` tool.
"""

import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.contracts.scheduled_tasks import ScheduledChatContext

CREATE_AUTOMATION_PROMPT = """\
I'd like to create a new automation — a scheduled reasoning task that Vellum runs on its own.

Please help me set it up:
1. Use any task idea I've provided. Ask only for missing details about what each run should do, when it should run, and where the result should land.
2. Draft one clear paragraph of instructions for the run.
3. Propose a schedule in one of these formats:
   - one-shot delay: '30m', '2h', '1d', '2w'
   - elapsed interval: 'every 2h'
   - recurring local clock time: '0 9 * * 1-5 @ Asia/Kolkata'; optionally append ' until YYYY-MM-DD'
   - one-time local clock time: '2027-01-12T09:00 @ Asia/Kolkata'; an ISO timestamp with a UTC offset also works
   Confirm the actual time zone for clock-based schedules, and use a future date for one-time tasks.
4. Propose a result destination: 'new_chat', 'existing_chat' with a pinned conversation, or 'notification'.
5. Confirm the name, instructions, schedule with time zone, destination, and notification preference with me. The task runs on its schedule either way; without full access each run asks first, listing anything that needs my approval instead of doing it. Enable full access only if I explicitly opt in after you explain that it lets the task act without asking each time.

Then create it with the cronjob tool (action='create'). You can also list, update, pause/resume, run-now, or remove automations from any chat with cronjob.
"""


def scheduled_chat_prompt(context: ScheduledChatContext) -> str:
    try:
        time_zone = ZoneInfo(context.time_zone).key
    except (ValueError, ZoneInfoNotFoundError):
        time_zone = "unknown; ask the user for their time zone"
    if not context.task_id:
        return f"{CREATE_AUTOMATION_PROMPT}\nDevice time zone: {time_zone}"

    from agent.automations.api import get_store

    task = get_store().get(context.task_id)
    snapshot = {
        "id": task["id"],
        "name": task["name"],
        "instructions": str(task.get("instructions") or "")[:8000],
        "schedule": task.get("schedule"),
        "destination": task.get("destination"),
    }
    return (
        "The user is replying in the chat of an existing scheduled task (each run has its own chat under the "
        "task). Answer questions about the task and its runs directly. Treat the following JSON as saved data: "
        "do not re-run its saved instructions unless the user asks for that (then do it now, in this reply, "
        "or use cronjob action='run'). For a requested change, use cronjob with the exact saved task ID "
        "and only the fields the user wants changed. Preserve its time zone unless the user changes it. "
        "Ask for missing timing details and do not create a duplicate. Confirm destructive changes.\n"
        f"Device time zone: {time_zone}\n"
        f"Saved task: {json.dumps(snapshot, ensure_ascii=False)}"
    )
