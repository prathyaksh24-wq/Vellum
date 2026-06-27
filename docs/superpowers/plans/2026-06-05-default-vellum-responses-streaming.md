# Default Vellum Responses-Style Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make default Vellum reasoning mode stream semantic Responses-style SSE events from the backend into `vellum-workspace.html`, while preserving legacy stream events during migration.

**Architecture:** Add a backend protocol adapter in `backend/agent/api.py` that emits OpenAI Responses-style lifecycle and output-item events beside the existing legacy SSE events. Update only `design/Velllum/uploads/vellum-workspace.html` so `streamBackend` consumes the semantic events and renders text, tools, sources, subagent activity, errors, and final response state.

**Tech Stack:** FastAPI `StreamingResponse`, SSE, Python tests with pytest, single-file React/Babel app in `vellum-workspace.html`, existing JSX compile gate.

---

## File Map

| Path | Responsibility | Action |
| --- | --- | --- |
| `backend/agent/api.py` | Backend SSE stream producer and LangGraph/live-dispatch adapter | Modify |
| `backend/tests/test_live_sports_api.py` | SportsAgent live-dispatch stream contract tests | Modify |
| `backend/tests/test_chat_stream_sources.py` | LangGraph tool/source streaming contract tests | Modify |
| `design/Velllum/uploads/vellum-workspace.html` | Active Vellum UI; backend stream consumer | Modify |
| `docs/AGENT_ARCHITECTURE.md` | Vellum architecture source of truth | Modify |

Do not modify:

- `frontend/ui/vellum-chat.html`
- Coding-mode JSON-RPC protocol in `vellum-workspace.html`

---

## Task 1: Backend SportsAgent Responses-Style Contract Test

**Files:**
- Modify: `backend/tests/test_live_sports_api.py`

- [ ] **Step 1: Write the failing test**

Append this test after `test_stream_agent_turn_emits_sports_dispatch_activity_and_sources`:

```python
def test_stream_agent_turn_emits_responses_style_events_for_sports_dispatch(monkeypatch):
    class FakeDispatcher:
        def maybe_handle(self, message, thread_id):
            return LiveAgentResult(
                handled=True,
                agent_name="SportsAgent",
                answer="Live sports answer",
                tools=["sports_agent", "web_search"],
                sources=[
                    {
                        "url": "https://www.formula1.com/en/latest/article/race-report",
                        "title": "Race report",
                        "snippet": "Winner and podium",
                        "domain": "formula1.com",
                    }
                ],
            )

    async def _async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "_live_dispatcher", FakeDispatcher())
    monkeypatch.setattr(api, "_background_learn", _async_noop)
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: coro.close())

    async def _collect():
        chunks = []
        async for chunk in api._stream_agent_turn(
            clean_message="Who won the last F1 race?",
            active_thread_id="thread-1",
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    events = _parse_sse(asyncio.run(_collect()))
    names = [name for name, _ in events]

    assert "response.created" in names
    assert "response.in_progress" in names
    assert "response.output_item.added" in names
    assert "response.output_text.delta" in names
    assert "response.completed" in names

    created = json.loads(next(data for name, data in events if name == "response.created"))
    assert created["type"] == "response.created"
    assert created["thread_id"] == "thread-1"
    assert created["response"]["status"] == "in_progress"

    added = [json.loads(data) for name, data in events if name == "response.output_item.added"]
    assert any(p["item"]["type"] == "subagent_call" and p["item"]["name"] == "SportsAgent" for p in added)
    assert any(p["item"]["type"] == "tool_call" and p["item"]["name"] == "web_search" for p in added)

    delta = json.loads(next(data for name, data in events if name == "response.output_text.delta"))
    assert delta["type"] == "response.output_text.delta"
    assert delta["delta"] == "Live sports answer"

    completed = json.loads(next(data for name, data in events if name == "response.completed"))
    assert completed["type"] == "response.completed"
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["output_text"] == "Live sports answer"
    assert completed["response"]["tools"] == ["sports_agent", "web_search"]
    assert completed["response"]["sources"][0]["domain"] == "formula1.com"
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
python -m pytest backend/tests/test_live_sports_api.py::test_stream_agent_turn_emits_responses_style_events_for_sports_dispatch -q
```

Expected: FAIL because `response.created` is not emitted yet.

- [ ] **Step 3: Commit the RED test**

```bash
git add backend/tests/test_live_sports_api.py
git commit -m "test(stream): specify Responses-style sports dispatch events"
```

---

## Task 2: Backend Responses-Style SSE Helper

**Files:**
- Modify: `backend/agent/api.py`

- [ ] **Step 1: Add imports**

Near the existing imports, add:

```python
from datetime import datetime, timezone
from uuid import uuid4
```

If `_now_iso` already imports `datetime` locally, keep the function working and
prefer the module-level import for new helper code.

- [ ] **Step 2: Add protocol helpers after `_sse`**

Insert this block immediately after `_sse`:

```python
def _stream_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _stream_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _response_event(
    event_type: str,
    *,
    response_id: str,
    thread_id: str,
    **payload: Any,
) -> str:
    body = {
        "type": event_type,
        "response_id": response_id,
        "thread_id": thread_id,
        "created_at": _stream_now(),
        **payload,
    }
    return _sse(event_type, body)
```

Then add helper wrappers for each semantic event:

```python
def _response_created(*, response_id: str, thread_id: str) -> str:
    return _response_event(
        "response.created",
        response_id=response_id,
        thread_id=thread_id,
        response={"id": response_id, "status": "in_progress", "output": []},
    )


def _response_in_progress(*, response_id: str, thread_id: str) -> str:
    return _response_event(
        "response.in_progress",
        response_id=response_id,
        thread_id=thread_id,
        response={"id": response_id, "status": "in_progress"},
    )


def _response_output_item_added(
    *,
    response_id: str,
    thread_id: str,
    item: dict[str, Any],
    output_index: int = 0,
) -> str:
    return _response_event(
        "response.output_item.added",
        response_id=response_id,
        thread_id=thread_id,
        output_index=output_index,
        item=item,
    )


def _response_output_text_delta(
    *,
    response_id: str,
    thread_id: str,
    item_id: str,
    delta: str,
    output_index: int = 0,
    content_index: int = 0,
) -> str:
    return _response_event(
        "response.output_text.delta",
        response_id=response_id,
        thread_id=thread_id,
        item_id=item_id,
        output_index=output_index,
        content_index=content_index,
        delta=delta,
    )


def _response_output_item_done(
    *,
    response_id: str,
    thread_id: str,
    item: dict[str, Any],
    output_index: int = 0,
) -> str:
    return _response_event(
        "response.output_item.done",
        response_id=response_id,
        thread_id=thread_id,
        output_index=output_index,
        item={**item, "status": "completed"},
    )


def _response_completed(
    *,
    response_id: str,
    thread_id: str,
    answer: str,
    tools: list[str],
    sources: list[dict[str, Any]],
) -> str:
    return _response_event(
        "response.completed",
        response_id=response_id,
        thread_id=thread_id,
        response={
            "id": response_id,
            "status": "completed",
            "thread_id": thread_id,
            "output_text": answer,
            "tools": tools,
            "sources": sources,
        },
    )


def _response_error(*, response_id: str, thread_id: str, message: str) -> str:
    return _response_event(
        "error",
        response_id=response_id,
        thread_id=thread_id,
        error={"message": message},
    )
```

- [ ] **Step 3: Run the focused test**

Run:

```bash
python -m pytest backend/tests/test_live_sports_api.py::test_stream_agent_turn_emits_responses_style_events_for_sports_dispatch -q
```

Expected: still FAIL because `_stream_agent_turn` does not call the helpers yet.

---

## Task 3: Emit Responses-Style Events for SportsAgent Dispatch

**Files:**
- Modify: `backend/agent/api.py`

- [ ] **Step 1: Add response IDs in `_stream_agent_turn`**

At the start of `_stream_agent_turn`, before the live dispatcher call, add:

```python
    response_id = _stream_id("resp")
    message_item_id = _stream_id("msg")
```

- [ ] **Step 2: Emit created/in-progress before dispatch results**

In the `live_result is not None and live_result.handled` branch, before the
legacy `meta` event, add:

```python
        yield _response_created(response_id=response_id, thread_id=active_thread_id)
        yield _response_in_progress(response_id=response_id, thread_id=active_thread_id)
```

- [ ] **Step 3: Emit subagent, tool, source, and message items**

Still in the live dispatch branch, add semantic events before the corresponding
legacy events.

Subagent item:

```python
        subagent_item = {
            "id": _stream_id("item"),
            "type": "subagent_call",
            "name": live_result.agent_name,
            "status": "in_progress",
            "label": f"Routed to {live_result.agent_name}",
            "detail": clean_message[:200],
        }
        yield _response_output_item_added(
            response_id=response_id,
            thread_id=active_thread_id,
            item=subagent_item,
        )
```

Tool item:

```python
            tool_item = {
                "id": _stream_id("item"),
                "type": "tool_call",
                "name": tool_name,
                "status": "in_progress",
                "label": f"Used {tool_name}",
                "detail": "",
            }
            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=tool_item)
            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=tool_item)
```

Source item:

```python
            source_item = {
                "id": _stream_id("item"),
                "type": "source",
                "status": "completed",
                "source": source_record,
            }
            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=source_item)
            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=source_item)
```

Message item and delta:

```python
            message_item = {
                "id": message_item_id,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
            }
            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=message_item)
            yield _response_output_text_delta(
                response_id=response_id,
                thread_id=active_thread_id,
                item_id=message_item_id,
                delta=live_result.answer,
            )
            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=message_item)
```

Before returning, after legacy `final`, add:

```python
        yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=subagent_item)
        yield _response_completed(
            response_id=response_id,
            thread_id=active_thread_id,
            answer=live_result.answer,
            tools=live_result.tools,
            sources=live_result.sources,
        )
```

- [ ] **Step 4: Run the sports stream tests**

Run:

```bash
python -m pytest backend/tests/test_live_sports_api.py -q
```

Expected: all tests in that file pass.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/api.py backend/tests/test_live_sports_api.py
git commit -m "feat(stream): emit Responses-style events for live subagent dispatch"
```

---

## Task 4: Backend LangGraph Tool/Source Responses-Style Tests

**Files:**
- Modify: `backend/tests/test_chat_stream_sources.py`

- [ ] **Step 1: Add assertions to existing full-stream test**

In `test_stream_agent_turn_emits_source_activity_contract`, after `names` is
computed, add:

```python
    assert "response.created" in names
    assert "response.in_progress" in names
    assert "response.output_item.added" in names
    assert "response.output_text.delta" in names
    assert "response.output_item.done" in names
    assert "response.completed" in names
```

After the existing final assertions, add:

```python
    response_final = json.loads(next(data for name, data in events if name == "response.completed"))
    assert response_final["response"]["output_text"] == "Verstappen won the last race."
    assert response_final["response"]["sources"][0]["domain"] in {"formula1.com", "skysports.com"}

    response_items = [json.loads(data)["item"] for name, data in events if name == "response.output_item.added"]
    assert any(item["type"] == "tool_call" and item["name"] == "web_search" for item in response_items)
    assert any(item["type"] == "source" and item["source"]["domain"] == "formula1.com" for item in response_items)
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python -m pytest backend/tests/test_chat_stream_sources.py::test_stream_agent_turn_emits_source_activity_contract -q
```

Expected: FAIL until the normal LangGraph branch emits the new events.

---

## Task 5: Emit Responses-Style Events for Normal LangGraph Turns

**Files:**
- Modify: `backend/agent/api.py`

- [ ] **Step 1: Emit created/in-progress in the normal branch**

Inside `async with _agent_runtime_lock`, before legacy `meta`, add:

```python
        yield _response_created(response_id=response_id, thread_id=active_thread_id)
        yield _response_in_progress(response_id=response_id, thread_id=active_thread_id)
```

- [ ] **Step 2: Track output items**

Near `answer_parts`, `tool_names`, and `sources`, add:

```python
        active_tool_items: dict[str, dict[str, Any]] = {}
        message_item = {
            "id": message_item_id,
            "type": "message",
            "role": "assistant",
            "status": "in_progress",
        }
        message_item_started = False
```

- [ ] **Step 3: Emit message deltas**

In `on_chat_model_stream`, before the legacy token event, add:

```python
                        if not message_item_started:
                            yield _response_output_item_added(
                                response_id=response_id,
                                thread_id=active_thread_id,
                                item=message_item,
                            )
                            message_item_started = True
                        yield _response_output_text_delta(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item_id=message_item_id,
                            delta=text,
                        )
```

- [ ] **Step 4: Emit tool items**

In `on_tool_start`, compute `label, detail = _activity_for(...)` before building
the item. Then add:

```python
                        item = {
                            "id": _stream_id("item"),
                            "type": "tool_call",
                            "name": str(name),
                            "status": "in_progress",
                            "label": label,
                            "detail": detail,
                        }
                        active_tool_items[str(name)] = item
                        yield _response_output_item_added(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item=item,
                        )
```

- [ ] **Step 5: Emit source and tool done items**

In `on_tool_end`, for web sources, emit source output items before legacy
`source`:

```python
                            source_item = {
                                "id": _stream_id("item"),
                                "type": "source",
                                "status": "completed",
                                "source": record,
                            }
                            yield _response_output_item_added(response_id=response_id, thread_id=active_thread_id, item=source_item)
                            yield _response_output_item_done(response_id=response_id, thread_id=active_thread_id, item=source_item)
```

After source extraction, mark the tool done:

```python
                    done_item = active_tool_items.pop(str(event.get("name") or ""), None)
                    if done_item:
                        yield _response_output_item_done(
                            response_id=response_id,
                            thread_id=active_thread_id,
                            item=done_item,
                        )
```

- [ ] **Step 6: Emit final completion**

Before legacy `final` or immediately after it, add:

```python
            if message_item_started:
                yield _response_output_item_done(
                    response_id=response_id,
                    thread_id=active_thread_id,
                    item=message_item,
                )
            yield _response_completed(
                response_id=response_id,
                thread_id=active_thread_id,
                answer=answer,
                tools=tool_names,
                sources=sources,
            )
```

- [ ] **Step 7: Emit semantic error event**

In the normal branch `except Exception as exc`, before or after legacy `error`,
add:

```python
            yield _response_error(response_id=response_id, thread_id=active_thread_id, message=str(exc))
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
python -m pytest backend/tests/test_chat_stream_sources.py::test_stream_agent_turn_emits_source_activity_contract backend/tests/test_live_sports_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit**

```bash
git add backend/agent/api.py backend/tests/test_chat_stream_sources.py
git commit -m "feat(stream): emit Responses-style events for default Vellum turns"
```

---

## Task 6: Wire `vellum-workspace.html` to Responses-Style Backend Events

**Files:**
- Modify: `design/Velllum/uploads/vellum-workspace.html`

- [ ] **Step 1: Add helpers near `streamBackend`**

Immediately before `async function streamBackend(chatId, aid, message){`, add:

```jsx
  function normalizeResponseStreamEvent(ev, payload){
    if(!payload) return null;
    if(ev && ev.indexOf("response.")===0) return {type:ev, payload};
    if(ev==="error") return {type:"error", payload};
    return null;
  }
  function responseItemActivity(item){
    if(!item) return null;
    if(item.type==="subagent_call") return {label:item.label||("Routed to "+(item.name||"subagent")), detail:item.detail||"", name:item.name, itemId:item.id, status:item.status};
    if(item.type==="tool_call") return {label:item.label||("Used "+(item.name||"tool")), detail:item.detail||"", name:item.name, itemId:item.id, status:item.status};
    if(item.type==="reasoning") return {label:item.label||"Thinking", detail:item.detail||"", itemId:item.id, status:item.status};
    return null;
  }
  function mergeSourceList(list, source){
    if(!source || !source.url) return list || [];
    const arr = list ? list.slice() : [];
    if(!arr.some(s=>s.url===source.url)) arr.push(source);
    return arr;
  }
```

- [ ] **Step 2: Add local stream state in `streamBackend`**

After `let buf="", acc="";`, add:

```jsx
      let semanticSeen = false;
      let tools = [];
      let sources = [];
      let activity = [];
```

- [ ] **Step 3: Handle Responses-style events first**

Inside the parsed `try{ const j=JSON.parse(data); ... }`, before legacy event
handling, add:

```jsx
            const sem = normalizeResponseStreamEvent(ev, j);
            if(sem){
              semanticSeen = true;
              if(sem.type==="response.created" || sem.type==="response.in_progress"){
                if(j.thread_id) threadRef.current[chatId]=j.thread_id;
              } else if(sem.type==="response.output_item.added"){
                const item = j.item || {};
                if(item.type==="source" && item.source){
                  sources = mergeSourceList(sources, item.source);
                  setMsgsFor(chatId,m=>m.map(x=>x.id===aid?{...x,sources:sources.slice(),thinking:false}:x));
                } else {
                  const act = responseItemActivity(item);
                  if(act){
                    activity = activity.concat([act]);
                    if(item.name && item.type==="tool_call" && tools.indexOf(item.name)<0) tools.push(item.name);
                    if(item.name && item.type==="subagent_call" && tools.indexOf(item.name)<0) tools.push(item.name);
                    setMsgsFor(chatId,m=>m.map(x=>x.id===aid?{...x,activity:activity.slice(),tools:tools.slice(),thinking:false}:x));
                  }
                }
              } else if(sem.type==="response.output_text.delta"){
                if(j.delta){ acc+=j.delta; setMsgsFor(chatId,m=>m.map(x=>x.id===aid?{...x,text:acc,thinking:false}:x)); }
              } else if(sem.type==="response.completed"){
                const r = j.response || {};
                if(r.thread_id) threadRef.current[chatId]=r.thread_id;
                const fin = acc || r.output_text || "";
                setMsgsFor(chatId,m=>m.map(x=>x.id===aid?{...x,text:fin,sources:r.sources||sources,tools:r.tools||tools,activity:activity,thinking:false,streaming:false}:x));
              } else if(sem.type==="error"){
                const msg = (j.error && (j.error.message || j.error)) || "Backend error";
                setMsgsFor(chatId,m=>m.map(x=>x.id===aid?{...x,text:"Warning: "+msg,thinking:false,streaming:false}:x));
              }
              continue;
            }
```

- [ ] **Step 4: Keep legacy fallback**

Leave the existing `meta`, `token`, and `final` handling below the semantic
block. Do not process legacy `token` after a semantic delta for the same stream:

```jsx
            else if(ev==="token" && !semanticSeen){ ... }
            else if(ev==="final" && !semanticSeen){ ... }
```

- [ ] **Step 5: Render activity if the existing message renderer ignores it**

Find the assistant message render path. If it does not show `msg.activity`, add a
compact activity row below sources/tools using existing classes if available:

```jsx
        {msg.activity && msg.activity.length>0 && <div className="att-row" style={{marginTop:8}}>
          {msg.activity.slice(0,4).map((a,i)=><span key={i} className="att-chip"><IcCircleRun size={12}/><span className="att-name">{a.label}</span></span>)}
        </div>}
```

- [ ] **Step 6: Compile gate**

Run:

```bash
node design/Velllum/uploads/check-jsx.mjs
```

Expected: `OK: JSX compiles`

- [ ] **Step 7: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(ui): consume Responses-style backend stream events"
```

---

## Task 7: Update Vellum Architecture Docs

**Files:**
- Modify: `docs/AGENT_ARCHITECTURE.md`

- [ ] **Step 1: Add streaming contract section**

Add this section after `## 1. Interfaces`:

```markdown
### Default Vellum Streaming Contract

The active frontend surface is `design/Velllum/uploads/vellum-workspace.html`.
The retired `frontend/ui/vellum-chat.html` is not a target for new stream work.

Default Vellum reasoning mode consumes `POST /chat/stream` as `text/event-stream`.
The stream emits OpenAI Responses-style semantic events:

- `response.created`
- `response.in_progress`
- `response.output_item.added`
- `response.output_text.delta`
- `response.output_item.done`
- `response.completed`
- `error`

During migration the backend also emits the older compatibility events
`meta`, `activity`, `tool`, `source`, `token`, and `final`. New UI code should
prefer Responses-style events and treat legacy events as fallback only.

Coding mode is separate: its Codex-style JSON-RPC/event-bus protocol is scoped
to the Coding assistant mode and is not the default Vellum reasoning stream.
```

- [ ] **Step 2: Commit**

```bash
git add docs/AGENT_ARCHITECTURE.md
git commit -m "docs(stream): document default Vellum Responses-style stream"
```

---

## Task 8: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
python -m pytest backend/tests/test_live_sports_api.py backend/tests/test_chat_stream_sources.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run frontend compile gate**

Run:

```bash
node design/Velllum/uploads/check-jsx.mjs
```

Expected: `OK: JSX compiles`

- [ ] **Step 3: Manual browser checks**

Start the backend and open `design/Velllum/uploads/vellum-workspace.html`.

Run:

1. Random query: "explain what Vellum remembers about me at a high level"
2. Sports query: "who won the last F1 race?"
3. Source query: "find recent NBA finals news"
4. Backend stopped/offline path

Expected:

- assistant text streams through semantic deltas
- SportsAgent route appears as subagent/tool activity
- tools and sources populate during the stream and remain after completion
- final answer reconciles with completed response
- offline/error stops streaming cleanly

- [ ] **Step 4: Commit any final fix**

If verification required a fix:

```bash
git add backend/agent/api.py backend/tests/test_live_sports_api.py backend/tests/test_chat_stream_sources.py design/Velllum/uploads/vellum-workspace.html docs/AGENT_ARCHITECTURE.md
git commit -m "fix(stream): verify default Vellum Responses-style streaming"
```

---

## Self-Review

Spec coverage:

- Default Vellum mode only: Tasks 2-6.
- No `vellum-chat.html`: File map and Task 6 exclude it.
- No Coding JSON-RPC changes: File map and scope exclude it.
- Dual-format migration: Tasks 3-6 preserve legacy events.
- SportsAgent/subagent visibility: Tasks 1, 3, 6.
- Tool/source visibility: Tasks 4-6.
- UI wiring to `vellum-workspace.html`: Task 6.
- Vellum docs update: Task 7.
- Verification: Task 8.

Placeholder scan:

- No placeholder markers.
- Every test and code step includes exact snippets and commands.

Type consistency:

- Backend event names match the design spec.
- Frontend event parser uses the same names.
- Item types are stable: `message`, `tool_call`, `subagent_call`, `source`, `reasoning`, `computer_use`.
