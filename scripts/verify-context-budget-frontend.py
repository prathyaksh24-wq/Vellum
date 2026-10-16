"""Opt-in live Gemma 4 + served frontend check with isolated synthetic history.

Run from the repo: PYTHONPATH=backend .venv/Scripts/python scripts/verify-context-budget-frontend.py
Requires the Vite frontend on 5173 and local Ollama. Never publishes externally.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
QA = ROOT / ".scratch" / ("context-budget-live-" + uuid4().hex[:10])
(QA / "vault").mkdir(parents=True)
os.environ.update(OBSIDIAN_VAULT_PATH=str(QA / "vault"), PRIMARY_MODEL="ollama/gemma4:12b",
                  KNOWLEDGE_CORE_DB_PATH=str(QA / "knowledge.db"), KNOWLEDGE_BLOB_PATH=str(QA / "blobs"),
                  LLM_ROUTING_DB_PATH=str(QA / "routing.db"), ENABLE_VAULT_WATCHER="false",
                  LLM_STREAM_TIMEOUT_SECONDS="180", ENABLE_NIGHTLY_DIGEST="false")

from langchain_core.messages import AIMessage, HumanMessage
from agent.memory import runtime as memory_runtime
memory_runtime.REPO_ROOT = QA
from agent.memory import memory_context
memory_context._MEMORY_FILES_DIR = QA / "memory"
from agent import api
from agent.graph import agent as graph
from agent.master.state import MasterThreadStateStore
from agent.llm.routing.runtime import get_routing_runtime
from agent.llm.providers import get_provider_registry
from agent.profiles.execution import get_profile_execution
from agent.conversations import recall
from agent.memory.project_context import ProjectContext

graph.CHECKPOINT_DB = QA / "checkpoints.db"
api._UI_CONVERSATIONS_PATH = QA / "conversations.json"
recall.HISTORY_PATH = api._UI_CONVERSATIONS_PATH
graph._prompt_project_ctx = ProjectContext(vault_root=QA / 'vault', sessions_db=QA / 'identity.db')
api._api_ledger = api.UsageLedger(QA / "usage.db")
api._observability = api.ObservabilityService(QA / "observability.db")
api._conversation_context_store = api.ConversationContextStore(QA / "context.db")
state = MasterThreadStateStore(sessions_db=QA / "sessions.db")
api._live_dispatcher.state_store = state
api._live_dispatcher.delegation_runtime.pending_action_store = state
api._session_control_service.state_store = state


async def main():
    import uvicorn
    from playwright.async_api import async_playwright

    thread = "context-budget-qa-" + uuid4().hex[:8]
    model = "ollama/gemma4:12b"
    registry = get_provider_registry()
    await asyncio.to_thread(registry.refresh_local_models, force=True)
    registry.set_active(model)
    runtime = get_routing_runtime()
    adapter = runtime.engine.adapters["ollama"]
    original_build = adapter.build_model
    observed_requests = []

    def record_build(**kwargs):
        built = original_build(**kwargs)
        execution = get_profile_execution()
        observed_requests.append({"profile":execution.profile_id if execution else "VellumAgent",
                                  "num_ctx":built.num_ctx, "model":built.model})
        return built
    adapter.build_model = record_build

    ui_messages, checkpoint_messages = [], []
    for index in range(20):
        text = ("Project ORBIT launches on 23 November 2026 in Kochi. The invitation tone is warm and concise. "
                if index == 0 else f"Synthetic planning note {index}. ")
        text += ("The staging checklist has seats, signage, a sound check and a registration desk. " * 48)
        if index == 3:
            text = 'The staging passphrase is CEDAR-482. ' + text
        answer = "Noted for the staging checklist. " * 12
        ui_messages += [{"id":f"u{index}","role":"user","text":text},
                        {"id":f"a{index}","role":"assistant","text":answer}]
        checkpoint_messages += [HumanMessage(content=text,id=f"u{index}"),AIMessage(content=answer,id=f"a{index}")]
    conversation = {"id":thread,"thread_id":thread,"title":"Context budget QA","model":model,
                    "store_to_memory":False,"messages":ui_messages,"created":"Today"}
    previous = {'id': 'older-reference', 'title': 'Earlier badge discussion', 'updated_at': '2026-10-15T12:00:00+05:30',
        'messages': [{'id': 'old-user', 'role': 'user', 'text': 'We decided to use recycled paper for the ORBIT badges.'}]}
    api._write_ui_conversations([conversation, previous])
    api._memory_orchestrator.store.save_memory(kind='preference', text='The user prefers terse writing with no emojis.',
        source_thread_id='synthetic-memory-source', confidence=1.0)
    await graph.agent.aupdate_state(api._thread_config(thread), {"messages":checkpoint_messages}, model=model)
    listener = socket.socket()
    listener.bind(("127.0.0.1",0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app,lifespan="off",log_level="error",timeout_graceful_shutdown=2))
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        await asyncio.sleep(.02)
    browser = playwright = None
    results = []
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(channel="msedge",headless=True,args=["--mute-audio"])
        page = await browser.new_page(viewport={"width":1440,"height":1000})
        # Unrelated connector health probes are outside this context QA and can
        # initiate slow network discovery during startup. Chat/models stay live.
        await page.route("**/api/plugins", lambda route:route.fulfill(json={"plugins":[]}))
        await page.add_init_script("localStorage.setItem('vellum-active-chat-id'," + json.dumps(thread) + ");")
        errors = []
        page.on("pageerror",lambda error:errors.append(str(error)))
        await page.goto(f"http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html?backend=http://127.0.0.1:{port}",wait_until="domcontentloaded")
        composer = page.locator('textarea[data-ui-reference="composer"]')
        await composer.wait_for(timeout=90000)
        # The composer exists before startup discovery/history hydration finishes.
        # Select the seeded conversation through the sidebar, just as a user does.
        seeded_chat = page.get_by_text("Context budget QA", exact=True)
        await seeded_chat.first.wait_for(timeout=60000)
        await seeded_chat.first.click()
        print(json.dumps({"stage":"frontend_ready","qa":str(QA)}),flush=True)

        async def send(text):
            started = time.perf_counter()
            await composer.fill(text)
            async with page.expect_response(lambda r:r.url.endswith('/api/chat/stream') and r.request.method=='POST',timeout=180000) as response_event:
                await page.locator('[data-ui-reference="composer.send"]').click()
            response = await response_event.value
            raw = (await response.body()).decode()
            completed, activity = None, []
            for block in raw.split('\n\n'):
                if '\ndata: ' not in block:
                    continue
                event, data = block.split('\ndata: ',1)
                data = json.loads(data)
                if event == 'event: response.completed': completed = data.get('response') or data
                if event == 'event: agent.activity': activity.append(data.get('activity') or {})
            if completed is None:
                raise AssertionError(raw[-2500:])
            answer = completed.get('output_text','')
            rendered_answer = page.get_by_text(answer,exact=False).last
            await rendered_answer.wait_for(timeout=15000)
            await rendered_answer.scroll_into_view_if_needed()
            item = {"request":text,"answer":answer,"seconds":round(time.perf_counter()-started,2),
                    "compactions":[a.get('metadata') for a in activity if a.get('type')=='context_compacted'],
                    "tools":completed.get('tools',[])}
            results.append(item)
            (QA/'progress.json').write_text(json.dumps({"results":results,"observed_requests":observed_requests},indent=2),encoding='utf-8')
            print(json.dumps(item),flush=True)
            return item

        first = await send("Write a one-sentence launch invitation for Project ORBIT using the agreed date and city. Use only this chat and no tools.")
        assert first['compactions'], 'The real 32k budget must trigger compaction'
        assert '23' in first['answer'] and 'november' in first['answer'].lower() and 'kochi' in first['answer'].lower()
        checkpoint = await graph.agent.aget_state(api._thread_config(thread),model=model)
        assert checkpoint.values['context_budget']['context_window']==32768
        assert len(checkpoint.values['messages']) < len(checkpoint_messages)
        assert len(api._read_ui_conversations()[0]['messages']) >= len(ui_messages)

        # Rebuild cached graphs, reopening the persisted SQLite checkpoint.
        await graph.agent.aclose()
        await page.reload(wait_until='domcontentloaded')
        await composer.wait_for(timeout=30000)
        await page.get_by_text("Context budget QA",exact=True).first.wait_for(timeout=60000)
        await page.get_by_text("Context budget QA",exact=True).first.click()
        second = await send("Make that invitation even shorter, keeping its date and city.")
        assert '23' in second['answer'] and 'kochi' in second['answer'].lower()
        await page.screenshot(path=str(QA/'main-context.png'))
        if '--management' in sys.argv:
            await composer.fill('/comp')
            await page.get_by_text('Compact context', exact=True).click()
            assert await composer.input_value() == '/compact'
            manual = await send('/compact focus on ORBIT launch and staging details')
            assert 'Compacted the working context' in manual['answer']
            checkpoint = await graph.agent.aget_state(api._thread_config(thread), model=model)
            assert checkpoint.values['context_budget']['trigger'] == 'manual'
            assert checkpoint.values['context_digest']['focus'] == 'ORBIT launch and staging details'
            print(json.dumps({'manual_checkpoint': checkpoint.values['context_budget'],
                'digest_method': checkpoint.values['context_digest']['method']}), flush=True)
            await graph.agent.aclose()
            await page.reload(wait_until='domcontentloaded')
            await composer.wait_for(timeout=30000)
            await page.get_by_text('Context budget QA', exact=True).first.wait_for(timeout=60000)
            await page.get_by_text('Context budget QA', exact=True).first.click()
            original = await send('Use conversation_history to read original message u3 from this chat. What staging passphrase did I give you? One sentence.')
            assert 'CEDAR-482' in original['answer']
            remembered = await send('What do you remember about my preferred writing style? One sentence.')
            assert any(word in remembered['answer'].lower() for word in ('terse', 'concise', 'brief', 'short'))
            earlier = await send('What did we discuss in the previous chat? Use the saved chat evidence, one sentence.')
            assert 'recycled' in earlier['answer'].lower() and 'badge' in earlier['answer'].lower()
            await page.screenshot(path=str(QA/'manual-compaction-recall.png'))
        third = None
        if '--main-only' not in sys.argv:
            third = await send("Use XAgent to draft only a short post about learning something new every day. Do not publish or submit anything.")
            assert any(r['profile']=='XAgent' and r['num_ctx']==16384 for r in observed_requests), observed_requests
        assert any(r['profile']=='VellumAgent' and r['num_ctx']==32768 for r in observed_requests)
        await page.screenshot(path=str(QA/'frontend.png'))
        report = {"model":model,"results":results,"observed_requests":observed_requests,"frontend_errors":errors,
                  "checkpoint_messages_after":len(checkpoint.values['messages']),"source_messages_before":len(ui_messages),
                  "canonical_history_preserved":True,"isolated_data":str(QA),
                  "context_budget_checks_passed":True,
                  "specialist_task_succeeded":None if third is None else not any(term in third['answer'].casefold() for term in
                      ("couldn't", "could not", "timed out", "no source evidence", "unreachable"))}
        (QA/'evidence.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        assert not errors, errors
        print(json.dumps({"context_budget_checks_passed":True,
                          "specialist_task_succeeded":report['specialist_task_succeeded'],
                          "evidence":str(QA/'evidence.json')}),flush=True)
    finally:
        if browser and browser.contexts and browser.contexts[0].pages:
            await browser.contexts[0].pages[0].screenshot(path=str(QA/'last-state.png'))
        if browser: await browser.close()
        if playwright: await playwright.stop()
        server.should_exit = True
        await asyncio.wait_for(server_task,8)
        await graph.agent.aclose()


if __name__ == '__main__':
    asyncio.run(main())
