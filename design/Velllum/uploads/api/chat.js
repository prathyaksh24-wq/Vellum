(function () {
  var client = window.VellumApi.client;

  function parseSseBlock(block) {
    var event = "message";
    var data = "";
    block.split(/\r?\n/).forEach(function (line) {
      if (line.indexOf("event:") === 0) event = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += (data ? "\n" : "") + line.slice(5).trimStart();
    });
    if (!data) return null;
    try { return { event: event, data: JSON.parse(data) }; }
    catch (_) { return null; }
  }

  function activityFromItem(item) {
    if (!item) return null;
    if (item.type === "subagent_call") return { id: item.id, type: item.type, label: item.label || ("Routed to " + (item.name || "subagent")), detail: item.detail || "", name: item.name, status: item.status };
    if (item.type === "tool_call" || item.type === "function_call") return { id: item.id, type: item.type, label: item.label || ("Used " + (item.name || "tool")), detail: item.detail || item.arguments || "", name: item.name, status: item.status };
    if (item.type === "reasoning") return { id: item.id, type: item.type, label: item.label || "Thinking", detail: item.detail || "", status: item.status };
    return null;
  }

  function sourceLabel(source) {
    return source && (source.provider_label || source.domain || source.title || source.url) || "source";
  }

  function humanToolName(name) {
    var clean = String(name || "tool");
    var known = {
      MemoryAgent: "Memory Agent",
      SportsAgent: "Sports Agent",
      XAgent: "X Agent",
      YoutubeAgent: "YouTube Agent",
      YouTubeAgent: "YouTube Agent",
      ResearchAgent: "Research Agent",
      serpapi: "SerpAPI",
      web_search: "web",
      search_my_notes: "your notes",
      read_file: "a note",
      list_files: "your vault",
      obsidian_api: "Obsidian",
      obsidian_search: "Obsidian",
      context_mode: "Context Mode",
    };
    if (known[clean]) return known[clean];
    return clean
      .replace(/[_:.]+/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\bYoutube\b/g, "YouTube")
      .replace(/\bApi\b/g, "API")
      .replace(/\b\w/g, function (letter) { return letter.toUpperCase(); });
  }

  function activityLabel(type, name, source) {
    if (type === 'function_call_preparing') return 'Preparing ' + humanToolName(name || 'function');
    if (type === 'function_call_prepared') return 'Prepared ' + humanToolName(name || 'function') + ' arguments';
    if (type === "thinking_started") return "";
    if (String(name || "").indexOf("agent_reach_x_") === 0) return "";
    if (type === "memory_retrieved") {
      if (name === "search_my_notes") return "Searching your notes";
      if (name === "obsidian_api" || name === "obsidian_search") return "Reading Obsidian";
      return "Searching your memory";
    }
    if (type === "sub_agent_started") return "Calling " + humanToolName(name || "sub-agent");
    if (type === "source_discovered") return "Found " + sourceLabel(source);
    if (type === "source_reading") return "Reading " + sourceLabel(source);
    if (type === "final_answer_started" || type === "final_answer_delta") return "Writing answer";
    if (type === "sub_agent_completed") return "Called " + humanToolName(name || "sub-agent");
    if (type === "tool_call_completed") {
      if (name === "serpapi") return "Searched with SerpAPI";
      if (name === "web_search") return "Searched the web";
      if (String(name || "").endsWith("_agent")) return "Called " + humanToolName(name);
      if (name === "search_my_notes") return "Searched your notes";
      if (name === "obsidian_api" || name === "obsidian_search") return "Read Obsidian";
      return "Used " + humanToolName(name || "tool");
    }
    if (type === "tool_call_started" || type === "tool_call_delta") {
      if (name === "serpapi") return "Searching with SerpAPI";
      if (name === "web_search") return "Searching the web";
      if (String(name || "").endsWith("_agent")) return "Calling " + humanToolName(name);
      if (name === "search_my_notes") return "Searching your notes";
      if (name === "read_file") return "Reading a note";
      if (name === "web_extract_pages") return "Reading web pages";
      if (name === "list_files") return "Browsing your vault";
      if (name === "obsidian_api" || name === "obsidian_search") return "Reading Obsidian";
      if (name === "youtube_search") return "Searching YouTube";
      return "Using " + humanToolName(name || "tool");
    }
    return "";
  }

  function normalizeAgentActivity(activity) {
    if (!activity) return null;
    var source = activity.source || null;
    var type = activity.type || "activity";
    var name = activity.name || "";
    var label = ['failed','error','blocked','cancelled'].includes(activity.status)
      ? (humanToolName(name || 'Action') + (activity.status === 'blocked' ? ' blocked' : activity.status === 'cancelled' ? ' stopped' : ' failed'))
      : type === "thinking_started"
      ? "Thinking"
      : (activityLabel(type, name, source) || activity.label || "Agent activity");
    return {
      id: activity.id || (type + "-" + Date.now()),
      type: type,
      label: label,
      detail: activity.detail || "",
      name: name,
      status: activity.status || "in_progress",
      source: source,
      metadata: activity.metadata || {},
      at: activity.metadata?.occurred_at || activity.at || Date.now(),
    };
  }

  async function stream(payload, handlers = {}) {
    const controller = new AbortController();
    if (handlers.controller) handlers.controller(controller);
    if (handlers.playbackRequest) await handlers.playbackRequest.ready;
    if (controller.signal.aborted) throw new DOMException('Stopped.', 'AbortError');
    const options=client.jsonOptions("POST", payload, controller.signal);
    options.headers={...options.headers,Accept:'text/event-stream'};
    options.cache='no-store';
    const response = await fetch(client.backendBase() + "/api/chat/stream", options);
    if (!response.ok || !response.body) {
      const failure = new Error("Backend stream failed: HTTP " + response.status);
      failure.vellumHttpStatus = response.status;
      throw failure;
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '', text = '', sources = [], tools = [], activity = [];
    let terminal = false, semanticText = false, semanticActivity = false, threadId = payload.thread_id;
    const trace = {model:payload.model || '',status:'thinking', startedAt:Date.now(), completedAt:null, elapsedSeconds:0,
      steps:[{id:'thinking',type:'thinking',label:'Thinking',status:'in_progress',at:Date.now()}], sources:[], tools:[]};
    const ended = status => ['completed','complete','done','failed','error','cancelled','interrupted','blocked'].includes(status);
    function emitTrace(status) {
      if (status && !terminal) trace.status = status;
      trace.elapsedSeconds = Math.max(0, ((trace.completedAt || Date.now()) - trace.startedAt) / 1000);
      trace.sources = sources.slice(); trace.tools = tools.slice();
      if (handlers.trace) handlers.trace({...trace, steps:trace.steps.map(item => ({...item})), sources:sources.slice(), tools:tools.slice()});
    }
    function upsert(step) {
      const id = step.id || ('activity-' + activity.length);
      const index = activity.findIndex(item => item.id === id), old = index < 0 ? {} : activity[index];
      const metadata = {...old.metadata, ...step.metadata};
      const next = {...old, ...step, id, metadata};
      if (old.type && !step.type) next.type = old.type;
      if (old.label && !step.label) next.label = old.label;
      if (old.detail && !step.detail) next.detail = old.detail;
      next.at = old.at || step.at || Date.now(); next.updatedAt = step.at || Date.now();
      if (!old.input && step.detail && !ended(step.status)) next.input = step.detail;
      next.events = [...(old.events || [])];
      const event = {type:step.type,status:step.status,label:step.label,detail:step.detail,at:step.at || Date.now()};
      const last = next.events.at(-1);
      if (!last || last.type !== event.type || last.status !== event.status || last.detail !== event.detail) next.events.push(event);
      if (index < 0) activity.push(next); else activity[index] = next;
      const ti = trace.steps.findIndex(item => item.id === id);
      if (ti < 0) trace.steps.push(next); else trace.steps[ti] = next;
      if (next.name && !tools.includes(next.name) && /tool|function|sub.?agent|memory/.test(next.type || '')) tools.push(next.name);
      if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
      return next;
    }
    function addSource(source) {
      if (!source || !(source.url || source.id)) return;
      const index = sources.findIndex(item => (item.id || item.url) === (source.id || source.url));
      if (index < 0) sources.push(source); else sources[index] = {...sources[index],...source};
      if (handlers.sources) handlers.sources(sources.slice());
    }
    function delta(value) {
      if (!value) return;
      text += value; emitTrace('answering');
      if (handlers.delta) handlers.delta(text, value);
    }
    function settle(status, message) {
      trace.completedAt = Date.now(); trace.status = status; terminal = true;
      trace.steps = trace.steps.map(item => ended(item.status) ? item : {...item,
        status:status === 'done' && ['thinking','answer'].includes(item.type) ? 'completed' : 'interrupted'});
      activity = activity.map(item => trace.steps.find(step => step.id === item.id) || item);
      if (message) trace.error = message;
      if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
      emitTrace();
    }
    function fail(message) {
      if (/request could not finish|response was interrupted|before completion/i.test(message) && activity.some(item=>['failed','error','blocked'].includes(item.status))) message=interruptedMessage();
      settle('error', message);
      if (handlers.error) handlers.error(message);
    }
    function interruptedMessage() {
      const failed=activity.filter(item=>['failed','error','blocked'].includes(item.status)).at(-1);
      if(failed) {
        const evidence=[failed.name,failed.detail,failed.metadata?.output].map(value=>typeof value==='string'?value:JSON.stringify(value || '')).join(' ');
        if(/serpapi/i.test(evidence))return 'SerpAPI search failed. Check its connection, quota or account limits.';
        return humanToolName(failed.name || 'The tool')+' failed before the response could finish. Your partial answer is preserved.';
      }
      return 'The response stream was interrupted. Your partial answer is preserved. Try again.';
    }
    function receive(block) {
      const parsed = parseSseBlock(block);
      if (!parsed) return;
      const ev = parsed.event, data = parsed.data;
      // Receipts are independent of response rendering and retain their original ordering.
      if (ev === 'app.action.requested') {
        if (handlers.actionRequested) handlers.actionRequested(data.request || data, {turn_kind:data.turn_kind || 'action'});
        return;
      }
      if (ev === 'app.action.receipt') {
        if (handlers.actionReceipt) handlers.actionReceipt(data.receipt || data, {turn_kind:data.turn_kind || 'action'});
        return;
      }
      if (terminal) return;
      if ((ev === 'meta' || ev === 'response.created' || ev === 'response.in_progress') && data.thread_id) {
        threadId = data.thread_id;
        if (handlers.meta) handlers.meta({thread_id:threadId});
      } else if (ev === 'agent.activity') {
        semanticActivity = true;
        const act = normalizeAgentActivity(data.activity || data);
        if (!act) return;
        if (act.type==='runtime_prepared' && act.metadata?.model)trace.model=act.metadata.model;
        if (act.source) addSource(act.source);
        // Answer deltas have their own channel; do not duplicate every token in the activity ledger.
        if (act.type === 'final_answer_delta') {emitTrace('answering'); return;}
        upsert(act);
        emitTrace(act.type.startsWith('final_answer') ? 'answering' : act.type === 'thinking_started' ? 'thinking' : 'researching');
      } else if (ev === 'response.output_item.added' || ev === 'response.output_item.done') {
        const item = data.item || {};
        if (item.type === 'source') {addSource(item.source); emitTrace(); return;}
        const previous = activity.find(act => act.id === item.id);
        const act = activityFromItem(item);
        if (act) {
          // Lifecycle + output-item aliases describe the same execution, never two rows.
          upsert({...act, type:previous?.type || act.type, label:previous?.label || act.label,
            status:ev.endsWith('.done') ? (item.status || 'completed') : (previous?.status || act.status || 'in_progress')});
          emitTrace(text ? 'answering' : 'researching');
        }
      } else if (ev === 'response.output_text.delta') {
        semanticText = true; delta(data.delta);
      } else if (ev === 'response.function_call_arguments.delta' || ev === 'response.function_call_arguments.done') {
        const old = activity.find(item => item.id === data.item_id) || {};
        const detail = ev.endsWith('.done') ? data.arguments || old.detail : (old.detail || '') + (data.delta || '');
        upsert({...old, id:data.item_id, type:old.type || 'function_call', label:old.label || 'Preparing function call',
          detail, input:detail, status:ev.endsWith('.done') ? 'completed' : 'in_progress'});
        emitTrace();
      } else if (ev === 'response.reasoning_text.delta' || ev === 'response.reasoning_text.done') {
        const id=data.item_id || 'model-thinking',old=activity.find(item=>item.id===id),done=ev.endsWith('.done');
        upsert({id,type:'model_reasoning',label:'Thought process',detail:done?(data.text || old?.detail || ''):(old?.detail || '')+(data.delta || ''),status:done?'completed':'in_progress'});emitTrace();
      } else if (ev === 'response.reasoning_summary_text.delta') {
        const id = data.item_id || 'reasoning-summary';
        const old = activity.find(item => item.id === id);
        upsert({id,type:'reasoning_summary',label:'Reasoning summary',detail:(old?.detail || '') + (data.delta || ''),status:'in_progress'});
        emitTrace();
      } else if (ev === 'response.reasoning_summary_text.done') {
        const id = data.item_id || 'reasoning-summary', old = activity.find(item => item.id === id);
        upsert({id,type:'reasoning_summary',label:'Reasoning summary',detail:data.text || old?.detail || '',status:'completed'}); emitTrace();
      } else if (ev === 'response.completed' || (ev === 'final' && !semanticText)) {
        const final = data.response || data;
        threadId = final.thread_id || threadId;
        text = final.output_text ?? final.answer ?? text;
        sources = final.sources || sources; tools = final.tools || tools;
        settle('done');
        if (handlers.meta && threadId) handlers.meta({thread_id:threadId});
        if (handlers.playbackRequest) handlers.playbackRequest.complete(final).catch(() => {});
        if (handlers.done) handlers.done({text,sources,tools,activity,trace:{...trace},thread_id:threadId});
      } else if (['error','response.failed','response.incomplete'].includes(ev)) {
        fail(data.error?.message || data.error || data.response?.error?.message || 'The response was interrupted.');
      } else if (ev === 'token' && !semanticText) delta(data.text);
      else if (ev === 'source' && !semanticActivity) {addSource(data); emitTrace();}
      else if (ev === 'activity' && !semanticActivity) {
        upsert({type:'activity',label:data.label || 'Working',detail:data.detail || '',status:'in_progress'}); emitTrace('researching');
      } else if (ev === 'tool' && !semanticActivity) {
        upsert({id:'legacy-tool-' + activity.length,type:'tool_call',name:data.name,label:'Using ' + humanToolName(data.name),status:'in_progress'}); emitTrace('researching');
      }
    }
    emitTrace();
    try {
      while (!terminal) {
        const chunk = await reader.read();
        buffer += chunk.done ? decoder.decode() : decoder.decode(chunk.value, {stream:true});
        let separator;
        while ((separator = /\r?\n\r?\n/.exec(buffer))) {
          const block = buffer.slice(0, separator.index); buffer = buffer.slice(separator.index + separator[0].length);
          receive(block);
        }
        if (chunk.done) {if (buffer.trim()) receive(buffer); break;}
      }
      if (!terminal) fail(interruptedMessage());
    } catch (error) {
      if (!controller.signal.aborted) {
        // Headers arrived: this is a response interruption, not an unreachable API.
        error.vellumStreamInterrupted = true;
        error.vellumDisplayMessage = interruptedMessage();
      }
      if (!terminal) settle(controller.signal.aborted ? 'cancelled' : 'error', error.vellumDisplayMessage || error.message);
      throw error;
    } finally {
      await reader.cancel().catch(() => {}); reader.releaseLock();
    }
    return {abort:() => controller.abort()};
  }

  function failureMessage(error) {
    if (error && error.vellumPlaybackError) return error.message;
    if (error && error.vellumStreamInterrupted) return error.vellumDisplayMessage;
    if (error && error.vellumHttpStatus) return 'Vellum API returned HTTP ' + error.vellumHttpStatus + '. Try again shortly.';
    if (error && error.name === 'TypeError' && /fetch|network|load failed|terminated/i.test(error.message || '')) {
      return 'Backend unreachable. Check the Vellum API connection and try again.';
    }
    return 'Vellum could not finish this response. Try again.';
  }
  window.VellumApi.chat = { stream: stream, failureMessage: failureMessage };
})();
