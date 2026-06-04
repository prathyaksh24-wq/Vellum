# Coding-mode Codex-style Streaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Vellum's Coding mode a faithful Codex-style live-streaming layer — JSON-RPC `thread/turn/item` frames over one multiplexed bus, model-planned task decomposition, real parallel subagent calls, optional reviewer, and a final condensing handshake — all inside the single-file preview.

**Architecture:** All code lives in the embedded `<script type="text/babel">` of `design/Velllum/uploads/vellum-workspace.html` (starts line 489). A module-level `VPROTO` defines frames + a tolerant plan parser. Inside the `App` component, per-chat `progressByChat` state holds the live task tree; an `applyFrame` reducer consumes frames; `runCodingTurn` orchestrates planner → parallel workers → reviewer → synthesis, emitting frames. The UI subscribes only to that state, so the producer can later be swapped for real backend SSE with zero UI change. General and Computer modes are untouched.

**Tech Stack:** React 18 + Babel-standalone (in-browser JSX), Fetch streaming (OpenRouter/OpenAI SSE), `crypto.randomUUID`. Verification: esbuild JSX compile (`node design/Velllum/uploads/check-jsx.mjs`) + manual browser run-through.

**Testing note (adapted TDD):** This surface is a single embedded React app with no unit-test runner, so the canonical "write a failing pytest" loop does not apply. Each task instead verifies with (a) the **automated compile gate** `node check-jsx.mjs` (must print `OK: JSX compiles`), and (b) **explicit manual browser checks** where behavior is observable. Treat a non-`OK` compile as a hard failure — fix before commit.

---

## File map

| File | Responsibility | Action |
|------|----------------|--------|
| `design/Velllum/uploads/vellum-workspace.html` | The entire app; all logic + render | Modify |
| `design/Velllum/uploads/check-jsx.mjs` | JSX compile gate (already created) | Use as-is |

Anchor reference (current line numbers, may drift as you edit — match on the quoted text, not the number):
- `489` — `<script type="text/babel" data-presets="react">`
- `559` — `const TASKS = [` (static, removed in Task 11)
- `587` — `const SUBAGENTS = [` (kept as persona pool)
- `667` — `const PROVIDER_CFG = {`
- `673` — `const MAIN_MSGS = [` (static demo, removed in Task 11)
- `910` — `const [activeMode, setActiveMode]   = useState("coding");`
- `1106` — `function setMsgsFor(chatId, fn){`
- `1112` — `async function streamChat(chatId, aid, history, model){`
- `1148` — `function sendToChat(chatId, text, atts){`
- `1346` — `const visibleTasks = tasksExpanded ? TASKS : TASKS.slice(0,6);`
- `1588` — `{/* Progress floating card */}`

---

## Task 1: Protocol module `VPROTO` (frames + routing tags + tolerant plan parser)

**Files:**
- Modify: `design/Velllum/uploads/vellum-workspace.html` (insert just above `const PROVIDER_CFG = {`, ~line 667)

- [ ] **Step 1: Insert the protocol module**

Insert this block immediately before `const PROVIDER_CFG = {`:

```jsx
/* ── Coding-mode streaming protocol (Codex-shaped, JSON-RPC 2.0 frames) ── */
const VPROTO = {
  uuid(){ try{ return crypto.randomUUID(); }catch(e){ return "id-"+Math.random().toString(36).slice(2); } },
  tag(parent, sub){ return "agent:"+parent+":subagent:"+sub; },
  masterTag(turnId){ return "agent:master:turn:"+turnId; },
  frame(method, params){ return { jsonrpc:"2.0", method, params }; },
  turnStarted(threadId, turnId){ return this.frame("turn/started", {threadId, turnId}); },
  plan(turnId, complex, reason, tasks){ return this.frame("item/plan", {turnId, complex, reason, tasks}); },
  subagentStarted(turnId, routingTag, persona, task){ return this.frame("item/subagent/started", {turnId, routingTag, persona, task}); },
  agentDelta(routingTag, text){ return this.frame("item/agentMessage/delta", {routingTag, text}); },
  reasoningDelta(routingTag, text){ return this.frame("item/reasoning/delta", {routingTag, text}); },
  subagentCompleted(routingTag, status, output){ return this.frame("item/subagent/completed", {routingTag, status, output}); },
  steer(threadId, turnId, text){ return this.frame("turn/steer", {threadId, turnId, text}); },
  turnCompleted(turnId, finalItemId){ return this.frame("turn/completed", {turnId, finalItemId}); },
  /* Tolerant parse of a planner reply. Returns {complex, reason, tasks:[{id,title,role}]}.
     Falls back to {complex:false} on any failure so callers degrade to a single answer. */
  parsePlan(text){
    if(!text) return {complex:false, reason:"", tasks:[]};
    let raw = String(text);
    const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i); if(fence) raw = fence[1];
    const s = raw.indexOf("{"), e = raw.lastIndexOf("}");
    if(s<0 || e<=s) return {complex:false, reason:"", tasks:[]};
    let obj; try{ obj = JSON.parse(raw.slice(s, e+1)); }catch(err){ return {complex:false, reason:"", tasks:[]}; }
    if(!obj || obj.complex!==true || !Array.isArray(obj.tasks) || !obj.tasks.length) return {complex:false, reason:(obj&&obj.reason)||"", tasks:[]};
    const roles = {worker:1, reviewer:1, analyst:1};
    const tasks = obj.tasks.slice(0,5).map((t,i)=>({
      id: "t"+(i+1),
      title: String((t&&t.title)||("Task "+(i+1))).slice(0,120),
      role: roles[(t&&t.role)] ? t.role : "worker",
    }));
    return {complex:true, reason:String(obj.reason||"").slice(0,200), tasks};
  },
};
```

- [ ] **Step 2: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 3: Manual parser sanity (browser console)**

Open `vellum-workspace.html` in a browser, open DevTools console, paste:
```js
VPROTO.parsePlan('```json\n{"complex":true,"reason":"multi-step","tasks":[{"title":"A","role":"worker"},{"title":"B","role":"reviewer"}]}\n```')
VPROTO.parsePlan('just a sentence, no json')
```
Expected: first returns `{complex:true, reason:"multi-step", tasks:[{id:"t1",title:"A",role:"worker"},{id:"t2",title:"B",role:"reviewer"}]}`; second returns `{complex:false, reason:"", tasks:[]}`.

- [ ] **Step 4: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): add VPROTO streaming protocol module + tolerant plan parser"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 2: Per-chat progress state + frame reducer

**Files:**
- Modify: `vellum-workspace.html` — add state near `const [running, setRunning]` (~line 948); add reducer + helpers near `function setMsgsFor` (~line 1106)

- [ ] **Step 1: Add progress state**

After the `const [running, setRunning]         = useState(false);` line, add:

```jsx
  const [progressByChat, setProgressByChat] = useState({}); // chatId -> {status,turnId,reason,tasks:[],outputs:[],sources:[]}
  const steerRef = useRef({}); // turnId -> pending steer text
```

- [ ] **Step 2: Add the reducer + helpers**

Immediately after `function setMsgsFor(chatId, fn){ ... }` (~line 1106), add:

```jsx
  function emptyProgress(){ return { status:"idle", turnId:null, reason:"", tasks:[], outputs:[], sources:[] }; }
  function setProgFor(chatId, fn){ setProgressByChat(prev=> ({...prev, [chatId]: fn(prev[chatId]||emptyProgress())})); }
  /* Pure reducer: fold one VPROTO frame into a progress object. */
  function applyFrame(prog, f){
    const p = {...prog, tasks:[...(prog.tasks||[])]};
    const m = f.method, a = f.params||{};
    if(m==="turn/started"){ return {...emptyProgress(), status:"planning", turnId:a.turnId}; }
    if(m==="item/plan"){
      if(!a.complex) return {...p, status:"done", reason:a.reason};
      p.status = "running"; p.reason = a.reason;
      p.tasks = (a.tasks||[]).map(t=>({ id:t.id, title:t.title, role:t.role, status:"pending", routingTag:null, persona:null, output:"" }));
      return p;
    }
    if(m==="item/subagent/started"){
      const i = p.tasks.findIndex(t=>t.id===a.task.id);
      if(i>=0) p.tasks[i] = {...p.tasks[i], status:"running", routingTag:a.routingTag, persona:a.persona};
      return p;
    }
    if(m==="item/agentMessage/delta"){
      const i = p.tasks.findIndex(t=>t.routingTag===a.routingTag);
      if(i>=0) p.tasks[i] = {...p.tasks[i], output:(p.tasks[i].output||"")+a.text};
      return p;
    }
    if(m==="item/reasoning/delta"){
      const i = p.tasks.findIndex(t=>t.routingTag===a.routingTag);
      if(i>=0) p.tasks[i] = {...p.tasks[i], review:(p.tasks[i].review||"")+a.text};
      return p;
    }
    if(m==="item/subagent/completed"){
      const i = p.tasks.findIndex(t=>t.routingTag===a.routingTag);
      if(i>=0) p.tasks[i] = {...p.tasks[i], status:a.status, output:a.output!=null?a.output:p.tasks[i].output};
      return p;
    }
    if(m==="turn/completed"){ return {...p, status:"done"}; }
    return p;
  }
  /* Emit a frame: reduce it into this chat's progress. The sole UI data path. */
  function emitFrame(chatId, frame){ setProgFor(chatId, prog=> applyFrame(prog, frame)); }
```

- [ ] **Step 3: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 4: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): per-chat progress state + frame reducer"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 3: Extract `streamModel` low-level helper (reused by subagents/synthesis)

**Files:**
- Modify: `vellum-workspace.html` — add `streamModel` just above `async function streamChat` (~line 1112); refactor `streamChat` to call it

- [ ] **Step 1: Add `streamModel`**

Insert immediately above `async function streamChat(chatId, aid, history, model){`:

```jsx
  /* Low-level provider stream. Returns the full text. Calls onDelta(chunk) per token.
     Does NOT touch chat messages or progress — callers decide what to do with the text. */
  async function streamModel({messages, model, signal, onDelta}){
    const cfg = PROVIDER_CFG[activeProvider] || PROVIDER_CFG.openrouter;
    const key = (apiKeys[cfg.keyId]||"").trim();
    if(!cfg.chatUrl) throw new Error("Provider has no chat endpoint in preview");
    if(!key) throw new Error("Missing API key");
    const headers = { "Authorization":"Bearer "+key, "Content-Type":"application/json" };
    if(cfg.referer){ headers["HTTP-Referer"]="https://vellum.app"; headers["X-Title"]="Vellum"; }
    const resp = await fetch(cfg.chatUrl, { method:"POST", signal, headers, body: JSON.stringify({ model, stream:true, messages }) });
    if(!resp.ok || !resp.body){
      let msg = "Request failed ("+resp.status+")";
      try{ const j = await resp.json(); if(j && j.error && j.error.message) msg = j.error.message; }catch(e){}
      throw new Error(msg);
    }
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf="", acc="";
    while(true){
      const r = await reader.read(); if(r.done) break;
      buf += dec.decode(r.value, {stream:true});
      let idx;
      while((idx = buf.indexOf("\n")) >= 0){
        const line = buf.slice(0, idx).trim(); buf = buf.slice(idx+1);
        if(!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if(data==="[DONE]") continue;
        try{ const j = JSON.parse(data); const d = j.choices && j.choices[0] && j.choices[0].delta; const c = d && d.content; if(c){ acc += c; if(onDelta) onDelta(c); } }catch(e){}
      }
    }
    return acc;
  }
```

- [ ] **Step 2: Refactor `streamChat` to use it**

Replace the entire body of `async function streamChat(chatId, aid, history, model){ ... }` (lines ~1112–1147) with:

```jsx
  async function streamChat(chatId, aid, history, model){
    const ctrl = new AbortController(); abortRef.current = ctrl;
    try{
      const text = await streamModel({
        messages: toORMessages(history), model, signal: ctrl.signal,
        onDelta: (c)=> setMsgsFor(chatId, m=> m.map(x=> x.id===aid ? {...x, text:(x.text||"")+c, thinking:false} : x)),
      });
      setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:text||x.text, streaming:false, thinking:false}:x));
    }catch(e){
      if(e && e.name==="AbortError") setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, streaming:false, thinking:false}:x));
      else setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:"⚠ "+((e&&e.message)||"Network error"), thinking:false, streaming:false}:x));
    }
    abortRef.current = null; setRunning(false);
  }
```

Note: the `onDelta` appends to `x.text` incrementally (equivalent to the old `acc` accumulation) because `streamModel` already accumulates and returns the final text; the per-delta UI update keeps the live stream feel.

- [ ] **Step 3: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 4: Manual regression — General mode still streams**

Open the file, set mode to **General** (Ctrl+1), add an OpenRouter key in Models & Compute, send "say hi in 5 words". Expected: tokens stream into the assistant bubble exactly as before; no progress panel changes.

- [ ] **Step 5: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "refactor(coding): extract streamModel; streamChat delegates to it"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 4: Planner call

**Files:**
- Modify: `vellum-workspace.html` — add `planTask` after `streamModel`

- [ ] **Step 1: Add planner prompt + call**

Insert after `streamModel` (before `streamChat`):

```jsx
  const PLANNER_SYS = "You are Vellum's coding orchestrator. Decide if the user's request needs to be split into multiple independent sub-tasks for parallel sub-agents. "
    + "Reply with ONLY a JSON object, no prose. Schema: {\"complex\": boolean, \"reason\": string, \"tasks\": [{\"title\": string, \"role\": \"worker\"|\"reviewer\"|\"analyst\"}]}. "
    + "Set complex=false for simple asks (a question, a one-file edit, a rename). Set complex=true only for genuinely multi-step builds; then list 2-5 concrete tasks. Keep titles under 8 words.";
  async function planTask(userText, history, signal){
    const messages = [{role:"system", content:PLANNER_SYS}].concat(toORMessages(history).slice(1)).concat([{role:"user", content:userText}]);
    let text=""; try{ text = await streamModel({messages, model:selModel, signal, onDelta:null}); }catch(e){ return {complex:false, reason:"", tasks:[]}; }
    return VPROTO.parsePlan(text);
  }
```

- [ ] **Step 2: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 3: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): planner call returns model-derived task plan"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 5: Orchestrator `runCodingTurn` (planner → parallel workers → reviewer → synthesis)

**Files:**
- Modify: `vellum-workspace.html` — add `runCodingTurn` + persona assignment after `planTask`

- [ ] **Step 1: Add persona assignment + worker/reviewer/synthesis prompts**

Insert after `planTask`:

```jsx
  const REVIEW_ON = true; // reviewer gate toggle (spec §5)
  function assignPersona(i){ const a = SUBAGENTS[i % SUBAGENTS.length]; return {name:a.name, sprite:a.sprite, color:a.color, role:a.role}; }
  function workerSys(goal, task){ return "You are sub-agent \""+task.title+"\" working under Vellum's coding orchestrator. Overall goal: "+goal+". Do ONLY your task: \""+task.title+"\". Be concise and produce concrete output (code/text) for just this part. Do not restate the whole plan."; }
  function reviewerSys(task){ return "You are a reviewer sub-agent. Briefly gate the work for task \""+task.title+"\": note in 1-2 lines whether it meets the task and any fix. Start with PASS or NEEDS-FIX."; }
  function synthSys(goal){ return "You are Vellum. Combine the sub-agent outputs below into one coherent, final answer to the user's request: "+goal+". Integrate, deduplicate, and present cleanly. Do not mention sub-agents or the orchestration."; }
```

- [ ] **Step 2: Add the orchestrator**

Insert after the prompts from Step 1:

```jsx
  async function runCodingTurn(chatId, aid, userText, history){
    const ctrl = new AbortController(); abortRef.current = ctrl;
    const turnId = VPROTO.uuid();
    emitFrame(chatId, VPROTO.turnStarted(chatId, turnId));
    try{
      const plan = await planTask(userText, history, ctrl.signal);
      emitFrame(chatId, VPROTO.plan(turnId, plan.complex, plan.reason, plan.tasks));
      if(!plan.complex){
        // simple ask → single stream into the assistant bubble
        const text = await streamModel({ messages: toORMessages([...history, {type:"user", text:userText}]), model:selModel, signal:ctrl.signal,
          onDelta:(c)=> setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:(x.text||"")+c, thinking:false}:x)) });
        setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:text||x.text, streaming:false, thinking:false}:x));
        emitFrame(chatId, VPROTO.turnCompleted(turnId, aid));
        abortRef.current=null; setRunning(false); return;
      }
      // attach plan to the assistant message so the inline plan block can render (Task 8)
      setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, turnId, plan:plan.tasks, thinking:false}:x));
      // PARALLEL workers, each a real subagent call, multiplexed via routing tags
      const results = await Promise.all(plan.tasks.map(async (task, i)=>{
        const tag = VPROTO.tag(turnId, VPROTO.uuid());
        const persona = assignPersona(i);
        emitFrame(chatId, VPROTO.subagentStarted(turnId, tag, persona, task));
        let out="";
        try{
          out = await streamModel({ messages:[{role:"system", content:workerSys(userText, task)}, {role:"user", content:task.title + (steerRef.current[turnId]?("\n\nUser steer: "+steerRef.current[turnId]):"")}], model:selModel, signal:ctrl.signal,
            onDelta:(c)=> emitFrame(chatId, VPROTO.agentDelta(tag, c)) });
          if(REVIEW_ON){
            const rv = await streamModel({ messages:[{role:"system", content:reviewerSys(task)}, {role:"user", content:out.slice(0,4000)}], model:selModel, signal:ctrl.signal,
              onDelta:(c)=> emitFrame(chatId, VPROTO.reasoningDelta(tag, c)) });
            void rv;
          }
          emitFrame(chatId, VPROTO.subagentCompleted(tag, "done", out));
        }catch(e){
          emitFrame(chatId, VPROTO.subagentCompleted(tag, "error", "⚠ "+((e&&e.message)||"failed")));
        }
        return { task, out };
      }));
      // SYNTHESIS → final consolidated answer into the assistant bubble
      const bundle = results.map(r=> "## "+r.task.title+"\n"+r.out).join("\n\n");
      let fin="";
      try{
        fin = await streamModel({ messages:[{role:"system", content:synthSys(userText)}, {role:"user", content:bundle}], model:selModel, signal:ctrl.signal,
          onDelta:(c)=> setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:(x.text||"")+c, thinking:false}:x)) });
      }catch(e){ fin = bundle; }
      setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:fin||bundle, streaming:false, thinking:false}:x));
      emitFrame(chatId, VPROTO.turnCompleted(turnId, aid));
    }catch(e){
      if(!(e && e.name==="AbortError")) setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, text:"⚠ "+((e&&e.message)||"Coding run failed"), thinking:false, streaming:false}:x));
      else setMsgsFor(chatId, m=> m.map(x=> x.id===aid?{...x, streaming:false, thinking:false}:x));
      setProgFor(chatId, prog=> ({...prog, status:"error"}));
    }
    delete steerRef.current[turnId];
    abortRef.current=null; setRunning(false);
  }
```

- [ ] **Step 3: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 4: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): runCodingTurn orchestrator — parallel subagents + synthesis"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 6: Gate orchestration into `sendToChat` (Coding mode only)

**Files:**
- Modify: `vellum-workspace.html` — `sendToChat` (~line 1148)

- [ ] **Step 1: Branch on mode**

In `sendToChat`, find the final dispatch block:
```jsx
    else { streamChat(chatId, aid, [...prevMsgs, userMsg], selModel); }
```
Replace it with:
```jsx
    else if(activeMode==="coding"){ runCodingTurn(chatId, aid, t, prevMsgs); }
    else { streamChat(chatId, aid, [...prevMsgs, userMsg], selModel); }
```
(The `useBackend` and missing-key/`!cfg.chatUrl` branches above this line are unchanged — coding orchestration only runs when a real provider key is present, since those earlier guards return first.)

- [ ] **Step 2: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 3: Manual — coding path fires**

Open file, ensure mode = **Coding** (default), add OpenRouter key, send a **simple** ask ("what is 2+2?"). Expected: single streamed answer, no task tree (planner returns complex:false). Then send a **complex** ask ("build a small Python CLI todo app with add/list/done and tests"). Expected: assistant bubble shows thinking, then (panel work appears once Task 7 lands) — for now confirm via console `progressByChat` that tasks were created and a synthesized answer streams in.

- [ ] **Step 4: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): route Coding-mode sends through runCodingTurn"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 7: Dynamic Progress panel (bar + empty state + live task tree + subagent roster)

**Files:**
- Modify: `vellum-workspace.html` — derived value near `visibleTasks` (~line 1346); panel render (~line 1588–1623)

- [ ] **Step 1: Add derived progress for the active chat**

Near `const visibleTasks = tasksExpanded ? TASKS : TASKS.slice(0,6);`, add below it:
```jsx
  const prog = progressByChat[activeChat] || emptyProgress();
  const progDone = prog.tasks.filter(t=> t.status==="done" || t.status==="error").length;
  const progPct = prog.tasks.length ? Math.round((progDone/prog.tasks.length)*100) : 0;
```

- [ ] **Step 2: Replace the Progress section markup**

Replace the first `<div className="prog-sec">` block (the one rendering `visibleTasks` / `TASKS`, lines ~1591–1596) with:
```jsx
                  <div className="prog-sec">
                    <div className="prog-title">Progress</div>
                    <div className="prog-bar" style={{height:4,borderRadius:3,background:"#1c1c1c",overflow:"hidden",margin:"2px 0 10px"}}>
                      <div style={{height:"100%",width:progPct+"%",background:"#e8932b",transition:"width .3s ease"}}/>
                    </div>
                    {prog.tasks.length===0 && <div className="task-empty" style={{color:"#555",fontSize:12.5,padding:"2px 0"}}>No tasks yet</div>}
                    {prog.tasks.map(t=>(
                      <div key={t.id} className="task-row">
                        {t.status==="done" ? <IcCheckCircle size={15}/> : t.status==="error" ? <IcCircle size={15}/> : t.status==="running"||t.status==="review" ? <IcCircleRun size={15}/> : <IcCircle size={15}/>}
                        <span className={"task-lbl"+(t.status==="done"?" done":"")}>{t.title}</span>
                        {t.persona && t.status==="running" && <span className="sa-working" style={{marginLeft:6}}>{t.persona.name} is working</span>}
                      </div>
                    ))}
                  </div>
```

- [ ] **Step 3: Make the Subagents section live**

Replace the Subagents `<div className="prog-sec">` block (lines ~1611–1621) with:
```jsx
                  {prog.tasks.some(t=>t.persona) && (
                  <div className="prog-sec">
                    <div className="prog-title">Subagents</div>
                    {prog.tasks.filter(t=>t.persona).map(t=>(
                      <div key={t.id} className="sa-row" onClick={()=>openTaskAgent(t)}>
                        <PixelSprite name={t.persona.sprite} color={t.persona.color} px={2}/>
                        <span className="sa-name">{t.persona.name}</span>
                        {t.status==="running" && <span className="sa-working">is working</span>}
                        {t.status==="done" && <span className="sa-working" style={{color:"#5a8f5a"}}>done</span>}
                      </div>
                    ))}
                  </div>
                  )}
```

- [ ] **Step 4: Add `openTaskAgent` near `openSubagent` (~line 1258)**

```jsx
  function openTaskAgent(task){
    setShowSub(true);
    const id = "task-"+task.id;
    setTabs(prev=> prev.find(t=>t.id===id) ? prev : [...prev, {id, kind:"taskagent", label:task.persona?task.persona.name:task.title, icon:"sprite", taskId:task.id, sprite:task.persona&&task.persona.sprite, color:task.persona&&task.persona.color}]);
    setActiveTab(id);
  }
```

- [ ] **Step 5: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 6: Manual — live panel**

Coding mode, complex ask. Expected: panel shows "No tasks yet" → bar at 0% → plan tasks appear `pending`, flip to `running` with "<Name> is working" glow, bar fills as each completes, Subagents list shows the assigned personas. Empty/new chat shows "No tasks yet" + 0% bar.

- [ ] **Step 7: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): live Progress panel — bar, empty state, task tree, subagent roster"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 8: Inline plan block in the chat stream

**Files:**
- Modify: `vellum-workspace.html` — assistant message render (~line 1352)

- [ ] **Step 1: Render the plan block above assistant text**

In the message render where an assistant message is returned (the branch handling `msg.streaming`/`msg.text` around line 1352), prepend a plan block when `msg.plan` exists. Replace the assistant `return <div className="msg-wrap">...` for the streaming/text case with a version that includes:
```jsx
      return <div className="msg-wrap">
        {msg.plan && msg.plan.length>0 && (()=>{ const pr = progressByChat[activeChat]||emptyProgress(); const byId={}; (pr.tasks||[]).forEach(t=>byId[t.id]=t); return (
          <div className="plan-block" style={{border:"1px solid #1e1e1e",borderRadius:10,padding:"8px 10px",margin:"4px 0 10px",background:"#121212"}}>
            <div className="prog-title" style={{marginBottom:4}}>Plan</div>
            {msg.plan.map(t=>{ const st=(byId[t.id]||{}).status||"pending"; return (
              <div key={t.id} className="task-row">
                {st==="done"?<IcCheckCircle size={14}/>:st==="running"||st==="review"?<IcCircleRun size={14}/>:<IcCircle size={14}/>}
                <span className={"task-lbl"+(st==="done"?" done":"")}>{t.title}</span>
                {(byId[t.id]&&byId[t.id].persona&&st==="running")&&<span className="sa-working" style={{marginLeft:6}}>{byId[t.id].persona.name}</span>}
              </div>
            ); })}
          </div>
        ); })()}
        {msg.streaming ? <div><span className="streaming-text">{msg.text}</span><span className="caret"/></div> : <div className="msg-text">{msg.text}</div>}
        {!msg.streaming && msg.sources && msg.sources.length>0 && <div className="att-row" style={{marginTop:8}}>{msg.sources.slice(0,5).map((s,i)=>(<a key={i} className="att-chip" href={s.url} target="_blank" rel="noreferrer" style={{textDecoration:"none",color:"#9bbcd6"}}><IcGlobe size={12}/><span className="att-name">{s.domain||s.title||"source"}</span></a>))}</div>}
      </div>;
```
(This merges the existing streaming-text + sources render with the new plan block. Keep the surrounding `if(msg.type==="assistant")` / key logic intact.)

- [ ] **Step 2: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 3: Manual — inline plan**

Complex ask in Coding mode. Expected: a "Plan" card appears inline in the assistant message; its steps check off live in sync with the side panel; the final synthesized answer streams below it.

- [ ] **Step 4: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): inline Codex-style plan block in chat stream"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 9: Subagent tab shows live streamed output

**Files:**
- Modify: `vellum-workspace.html` — the agent tab body render (~line 1661, `activeTabObj.kind==="agent"`)

- [ ] **Step 1: Add a render branch for `kind==="taskagent"`**

Immediately before the existing `{activeTabObj && activeTabObj.kind==="agent" && (()=>{` block, add:
```jsx
                {activeTabObj && activeTabObj.kind==="taskagent" && (()=>{ const pr = progressByChat[activeChat]||emptyProgress(); const t = (pr.tasks||[]).find(x=>x.id===activeTabObj.taskId) || {title:activeTabObj.label, status:"pending", output:""}; return (
                  <div className="workspace-body">
                    <div className="drawer-hdr">
                      <div><div className="drawer-title">{t.persona && <PixelSprite name={t.persona.sprite} color={t.persona.color} px={3}/>} {t.persona?t.persona.name:t.title}</div><div className="drawer-sub">{t.title}</div></div>
                      <span className={"status-pill "+(t.status==="done"?"complete":t.status==="error"?"closed":"running")}>{t.status}</span>
                    </div>
                    <div className="msgs compact-msgs" style={{padding:"10px 12px"}}>
                      <div className="msg-text" style={{whiteSpace:"pre-wrap"}}>{t.output || (t.status==="running"?"…":"No output yet")}</div>
                      {t.review && <div className="msg-text" style={{whiteSpace:"pre-wrap",marginTop:10,color:"#a78bfa"}}>Review: {t.review}</div>}
                    </div>
                  </div>
                ); })()}
```

- [ ] **Step 2: Add tab-icon support for the new kind (if needed)**

In `tabIcon(t)`, the `t.icon==="sprite"` branch currently looks up `agentById(t.agentId)`. Extend it so taskagent tabs use their stored sprite/color. Replace the sprite branch:
```jsx
    if(t.icon==="sprite"){ if(t.sprite){ return <PixelSprite name={t.sprite} color={t.color} px={2}/>; } const a = agentById(t.agentId); return a ? <PixelSprite name={a.sprite} color={a.color} px={2}/> : <IcUser size={12}/>; }
```

- [ ] **Step 3: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 4: Manual — open a subagent**

During/after a complex run, click a subagent in the panel. Expected: a tab opens showing that subagent's streamed output (and reviewer note if on), with a live status pill.

- [ ] **Step 5: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): subagent tab streams live task output + review"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 10: Steering (`turn/steer`) during a running coding turn

**Files:**
- Modify: `vellum-workspace.html` — `sendToChat` guard (~line 1149) + steer wiring

- [ ] **Step 1: Allow steer submit while running**

At the top of `sendToChat`, the guard currently is:
```jsx
    const t = (text||"").trim(); if((!t && (!atts || !atts.length)) || running) return;
```
Replace with:
```jsx
    const t = (text||"").trim();
    if(running){
      // mid-turn steer for an active coding turn
      const pr = progressByChat[chatId]; const tid = pr && pr.turnId;
      if(t && tid && activeMode==="coding" && pr.status==="running"){
        steerRef.current[tid] = t;
        emitFrame(chatId, VPROTO.steer(chatId, tid, t));
        setMsgsFor(chatId, m=> [...m, { id:nextId(), type:"system", label:"Steer: "+t, icon:"dot" }]);
        if(abortRef.current){ try{ abortRef.current.abort(); }catch(e){} }
        // re-issue: resend the original-style turn with steer appended is out of scope for v1;
        // the steer text is injected into in-flight worker prompts via steerRef (see runCodingTurn).
      }
      return;
    }
    if(!t && (!atts || !atts.length)) return;
```

- [ ] **Step 2: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 3: Manual — steer**

Start a complex coding run; while it's running, type "focus on error handling" and submit. Expected: a "Steer:" system line appears; remaining/queued worker prompts pick up the steer text (`steerRef`). Documented limit: already-streaming tokens are not retroactively changed.

- [ ] **Step 4: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): turn/steer — accept mid-turn user input"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Task 11: Remove static demo seed + final handshake polish

**Files:**
- Modify: `vellum-workspace.html` — `MAIN_MSGS` usage, `TASKS` usage, new-chat seeding, handshake

- [ ] **Step 1: Make Coding chats start empty**

Find where `MAIN_MSGS` is used to seed a chat's messages (search `MAIN_MSGS`). Replace the seeded initial messages for a fresh chat with an empty array so new Coding chats start blank. If `chatMsgs` is initialized from `MAIN_MSGS` for the demo chat, change that initializer to `[]`. Leave `SUBAGENTS` (persona pool) and `TASKS` definition in place but no longer rendered (panel now uses `prog.tasks`).

Concretely: locate the `useState` that holds `chatMsgs` (or the demo chat seed) and ensure a newly created chat id maps to `[]`. The `onMainSend` flow already creates messages via `sendToChat`, so no seed is required.

- [ ] **Step 2: Final handshake — condense**

The handshake is achieved by the synthesis step already writing the consolidated answer into the assistant bubble, plus collapsing per-subagent inline detail. Ensure that on `turn/completed`, the inline plan block remains but subagent live-glow stops (driven by `status!=="running"`). No extra code needed if Tasks 7–8 key animations off `status`. Verify by inspection; if any element keys glow off `running` incorrectly, fix the conditional to `t.status==="running"`.

- [ ] **Step 3: Verify the empty-state on a brand-new chat**

Confirm the `useEffect` at ~line 1041 (auto-opens Progress for a freshly created chat) now shows the empty panel (bar 0%, "No tasks yet") rather than static content.

- [ ] **Step 4: Compile gate**

Run: `node design/Velllum/uploads/check-jsx.mjs`
Expected: `OK: JSX compiles`

- [ ] **Step 5: Full manual run-through (spec §10)**

- General mode (Ctrl+1): unchanged single-stream chat.
- Coding + simple ask: single stream, panel stays "No tasks yet".
- Coding + complex ask ("build a CLI todo app with tests"): inline Plan + side panel fill, ≥2 subagents stream in parallel with glow + names, bar fills, reviewer notes appear, final synthesized answer condenses below the plan.
- Steer mid-turn: accepted, system line shown.
- New chat: empty progress bar, "No tasks yet".
- Computer mode (Ctrl+3): overlay flow untouched.

- [ ] **Step 6: Commit**

```bash
git add design/Velllum/uploads/vellum-workspace.html
git commit -m "feat(coding): empty-start chats + final condensing handshake; remove static demo"
git push origin feat/vellum-frontend-chroma-memory
```

---

## Self-review (author checklist — completed)

**Spec coverage:**
- §3 mode gating → Task 6 (coding-only branch). ✓
- §4 protocol frames + routing tags → Task 1 (`VPROTO`). ✓
- §5 planner → parallel workers → reviewer → synthesis → Tasks 4, 5. ✓
- §6 steering → Task 10. ✓
- §7 UI (bar, empty state, task tree, roster, inline plan, per-agent glow, handshake) → Tasks 7, 8, 9, 11. ✓
- §8 swap-to-real seam (`streamModel` isolates leaf call; UI reads only `progressByChat`) → Tasks 2, 3, 5. ✓
- §9 errors (planner fallback, per-task error, abort) → Tasks 1, 4, 5. ✓
- §10 testing → compile gate + manual steps every task. ✓
- Removed `MAIN_MSGS`/static `TASKS` rendering → Task 11. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `emitFrame`/`applyFrame`/`setProgFor`/`emptyProgress`/`progressByChat`/`steerRef`/`runCodingTurn`/`streamModel`/`planTask`/`assignPersona`/`openTaskAgent` names used consistently across Tasks 2–10. Task shape `{id,title,role,status,routingTag,persona,output,review}` is stable from Task 2's reducer through Tasks 7–9 render. Frame methods match `VPROTO` builders in Task 1. ✓
