# Default Vellum Responses-Style Streaming Design

**Date:** 2026-06-05
**Status:** Draft for review
**Surface:** `design/Velllum/uploads/vellum-workspace.html`
**Scope owner:** Default Vellum reasoning mode only

---

## 1. Purpose

Make Vellum's default reasoning mode stream like the OpenAI Responses API: a
semantic server-sent event stream with lifecycle events, output items, text
deltas, tool/subagent activity, sources, errors, and a final completion object.

The current backend stream already carries useful information, but it uses a
small legacy vocabulary: `meta`, `activity`, `tool`, `source`, `token`, `final`,
and `error`. That vocabulary is not expressive enough for a main reasoning agent
that can understand the user deeply, call tools, route to specialist subagents
such as SportsAgent, and surface what happened in the UI.

This design introduces a Responses-style semantic event contract while keeping
the legacy events during migration.

## 2. Non-goals

- Do not touch `frontend/ui/vellum-chat.html`; that surface is being retired.
- Do not touch the Coding assistant JSON-RPC protocol in `vellum-workspace.html`.
- Do not change Coding mode behavior in this slice.
- Do not build new subagent orchestration from scratch in this slice.
- Do not remove legacy SSE events yet.
- Do not migrate the backend model provider to OpenAI Responses API. This is a
  Vellum event contract shaped like OpenAI Responses streaming, not a provider
  migration.

## 3. Modes

Vellum has three UI modes:

| Mode | Streaming behavior |
| --- | --- |
| General/default Vellum | Uses backend `/chat/stream` and the new Responses-style event contract. |
| Coding | Keeps its existing Coding assistant JSON-RPC/event-bus implementation. |
| Computer | Keeps the existing computer-use stream and overlay behavior. |

The new work only applies when `vellum-workspace.html` sends to the backend in
the default Vellum reasoning path. Coding mode can still use its separate
Codex-style assistant path.

## 4. Event Contract

Backend endpoint: `POST /chat/stream`
Transport: `text/event-stream`
Compatibility: dual format during migration

Each new semantic event uses an SSE `event:` name matching the Responses-style
event type and a JSON `data:` payload that also contains `type`.

### Event sequence

For a normal streamed answer:

```text
response.created
response.in_progress
response.output_item.added
response.output_text.delta
response.output_item.done
response.completed
```

For an error:

```text
response.created
response.in_progress
error
```

### Required fields

Every Responses-style event payload includes:

```json
{
  "type": "response.output_text.delta",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "created_at": "2026-06-05T00:00:00+00:00"
}
```

Events that relate to an output item include:

```json
{
  "item_id": "item_...",
  "output_index": 0
}
```

### Payload shapes

`response.created`

```json
{
  "type": "response.created",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "response": {
    "id": "resp_...",
    "status": "in_progress",
    "output": []
  }
}
```

`response.in_progress`

```json
{
  "type": "response.in_progress",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "response": {
    "id": "resp_...",
    "status": "in_progress"
  }
}
```

`response.output_item.added`

```json
{
  "type": "response.output_item.added",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "output_index": 0,
  "item": {
    "id": "item_...",
    "type": "tool_call",
    "name": "sports_agent",
    "status": "in_progress",
    "label": "Routed to SportsAgent",
    "detail": "Who won the last F1 race?"
  }
}
```

Allowed item types for this slice:

| Item type | Meaning |
| --- | --- |
| `message` | Assistant message output. |
| `tool_call` | LangGraph tool or specialist agent tool started. |
| `subagent_call` | Vellum routed to a specialist agent such as SportsAgent. |
| `source` | A source became available. |
| `reasoning` | User-visible progress/status, not hidden chain of thought. |
| `computer_use` | Existing computer-use event adapted into the semantic stream. |

`response.output_text.delta`

```json
{
  "type": "response.output_text.delta",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "item_id": "msg_...",
  "output_index": 0,
  "content_index": 0,
  "delta": "Live sports answer"
}
```

`response.output_item.done`

```json
{
  "type": "response.output_item.done",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "output_index": 0,
  "item": {
    "id": "item_...",
    "type": "tool_call",
    "name": "sports_agent",
    "status": "completed"
  }
}
```

`response.completed`

```json
{
  "type": "response.completed",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "response": {
    "id": "resp_...",
    "status": "completed",
    "output_text": "Final answer",
    "thread_id": "thread-1",
    "tools": ["sports_agent", "web_search"],
    "sources": []
  }
}
```

`error`

```json
{
  "type": "error",
  "response_id": "resp_...",
  "thread_id": "thread-1",
  "error": {
    "message": "Unreachable."
  }
}
```

## 5. Backend Design

Create a small protocol helper near `_sse` in `backend/agent/api.py`.

Responsibilities:

- Generate stable `response_id` and `item_id` values.
- Emit Responses-style SSE frames.
- Keep emitting legacy frames during migration.
- Translate existing runtime events:
  - live dispatcher handoff -> `subagent_call`
  - LangGraph `on_tool_start` -> `tool_call`
  - LangGraph `on_tool_end` with web sources -> `source`
  - model stream chunks -> `response.output_text.delta`
  - final answer -> `response.completed`
  - exceptions -> `error`

The adapter must not expose hidden chain of thought. Any `reasoning` item is
limited to concise user-visible status such as "Searched the web" or "Routed to
SportsAgent".

## 6. Frontend Design

Only `design/Velllum/uploads/vellum-workspace.html` is updated.

`streamBackend(chatId, aid, message)` becomes the backend stream consumer for
Responses-style events. It still accepts legacy events as a fallback while the
backend emits both.

Frontend reducer behavior:

- `response.created`: store thread/response metadata and set assistant bubble to
  thinking/streaming.
- `response.output_item.added`: append activity, tools, source records, or
  subagent status into the assistant message state.
- `response.output_text.delta`: append `delta` to the assistant message text.
- `response.output_item.done`: mark activity/subagent item complete.
- `response.completed`: reconcile final answer, tools, sources, and stop
  streaming.
- `error`: show the error and stop streaming.

The UI should render:

- streamed answer text
- sources from `source` output items and final response
- activity/tool/subagent timeline in the existing progress/sources area
- SportsAgent and other specialist routes as visible subagent activity

## 7. Compatibility

Dual-format migration is required:

- Keep existing legacy events: `meta`, `activity`, `tool`, `source`, `token`,
  `final`, `error`.
- Add Responses-style events in parallel.
- `vellum-workspace.html` should prefer Responses-style events and use legacy
  events only if no semantic event exists.

This lets older callers continue to work while the new UI uses the stronger
contract.

## 8. Testing

Backend tests:

- SportsAgent live dispatch emits:
  - `response.created`
  - `response.in_progress`
  - `response.output_item.added` for the subagent/tool
  - `response.output_text.delta`
  - `response.completed`
- LangGraph tool stream emits:
  - tool item added/done
  - source item added/done
  - text deltas
  - completed response with final tools and sources
- Errors emit `error` with response/thread identifiers.
- Legacy event tests still pass.

Frontend verification:

- JSX compile gate for `vellum-workspace.html`.
- Manual backend streaming through the new UI:
  - random query
  - sports query routed to SportsAgent
  - web-source query
  - backend error/offline path

## 9. References

- OpenAI Streaming Responses guide:
  `https://developers.openai.com/api/docs/guides/streaming-responses`
- Vellum backend stream:
  `backend/agent/api.py::_stream_agent_turn`
- Vellum frontend surface:
  `design/Velllum/uploads/vellum-workspace.html::streamBackend`
- Existing Coding-only streaming design:
  `docs/superpowers/specs/2026-06-04-coding-mode-codex-streaming-design.md`

