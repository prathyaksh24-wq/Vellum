"""Pre-filled explainer prompt for the chat-guided automation creation flow.

The UI's "Create automation" button opens a new reasoning chat whose first
message is this prompt (served by ``GET /api/automations/create-prompt``). The
agent then drafts the automation, proposes a schedule and destination, confirms
with the user, and creates it via the ``cronjob`` tool.
"""

CREATE_AUTOMATION_PROMPT = """\
I'd like to create a new automation — a scheduled reasoning task that Vellum runs on its own.

Please help me set it up:
1. Ask me what the task should do: what each run should accomplish, how often, and where the result should land. If I'm not sure, propose sensible defaults.
2. Draft one clear paragraph of instructions for the run.
3. Propose a schedule in one of these formats:
   - one-shot delay: '30m', '2h', '1d', '2w'
   - recurring interval: 'every 2h', 'every 1d at 09:00'
   - 5-field cron: '0 9 * * *' (UTC)
   - exact time: '2026-08-03T09:00:00Z'
4. Propose a destination: 'new_chat' (a standalone conversation in the Scheduled feed) or 'existing_chat' with a pinned conversation.
5. Summarize the plan — name, instructions, schedule, destination, and whether it needs full access (runs unattended, bypassing confirmation gates) — and confirm with me before creating.

Then create it with the cronjob tool (action='create'). You can also list, update, pause/resume, run-now, or remove automations from any chat with cronjob.
"""
