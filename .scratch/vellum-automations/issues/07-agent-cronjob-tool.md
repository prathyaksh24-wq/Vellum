# 07 — Agent cronjob tool (chat-guided creation)

**What to build:** The reasoning agent gains a `cronjob` action-tool so a user can create, edit, pause/resume, run-now, or remove automations from any reasoning conversation. The Create button opens a new chat with a pre-filled explainer prompt; the agent drafts instructions, proposes schedule/destination, confirms with the user, then creates via the API. Validation errors come back into the conversation.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `cronjob` tool available in reasoning chats: create / update / pause / resume / remove / run-now
- [ ] Create-chat pre-filled explainer prompt flow
- [ ] Tool surfaces validation errors back into the conversation
- [ ] Tool-call tests: create + update an automation from a chat turn
