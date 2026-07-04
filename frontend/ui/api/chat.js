(function () {
  var client = window.VellumApi.client;

  function parseSseBlock(block) {
    var event = "message";
    var data = "";
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) event = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
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
      .replace(/_/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\bYoutube\b/g, "YouTube")
      .replace(/\bApi\b/g, "API")
      .replace(/\b\w/g, function (letter) { return letter.toUpperCase(); });
  }

  function activityLabel(type, name, source) {
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
      if (name === "list_files") return "Browsing your vault";
      if (name === "obsidian_api" || name === "obsidian_search") return "Reading Obsidian";
      if (name === "x_action") return "Using X Agent";
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
    var label = type === "thinking_started"
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
      at: activity.at || Date.now(),
    };
  }

  async function stream(payload, handlers) {
    var controller = new AbortController();
    if (handlers && handlers.controller) handlers.controller(controller);
    var response = await fetch(client.backendBase() + "/api/chat/stream", client.jsonOptions("POST", payload, controller.signal));
    if (!response.ok || !response.body) throw new Error("Backend stream failed: HTTP " + response.status);
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var text = "";
    var tools = [];
    var sources = [];
    var activity = [];
    var firstTokenSeen = false;
    var semanticSeen = false;
    var completed = false;
    var trace = {
      status: "thinking",
      startedAt: Date.now(),
      completedAt: null,
      elapsedSeconds: 0,
      steps: [{ id: "thinking", type: "thinking", label: "Thinking", detail: "", status: "in_progress", at: Date.now() }],
      sources: [],
      tools: [],
    };

    function emitTrace(status) {
      if (status) trace.status = status;
      trace.elapsedSeconds = Math.max(0, Math.round(((trace.completedAt || Date.now()) - trace.startedAt) / 1000));
      if (handlers.trace) {
        handlers.trace({
          status: trace.status,
          startedAt: trace.startedAt,
          completedAt: trace.completedAt,
          elapsedSeconds: trace.elapsedSeconds,
          steps: trace.steps.slice(),
          sources: trace.sources.slice(),
          tools: trace.tools.slice(),
        });
      }
    }

    function upsertStep(step) {
      var next = Object.assign({ id: "step-" + trace.steps.length, type: "activity", detail: "", status: "running", at: Date.now() }, step || {});
      if (!next.id) next.id = next.name ? "step-" + next.name : "step-" + trace.steps.length;
      var key = next.id || next.name || next.label;
      var index = trace.steps.findIndex(function (item) { return (item.id || item.name || item.label) === key; });
      if (index >= 0) trace.steps[index] = Object.assign({}, trace.steps[index], next);
      else trace.steps.push(next);
    }

    function addTool(name) {
      if (name && tools.indexOf(name) < 0) tools.push(name);
      if (name && trace.tools.indexOf(name) < 0) trace.tools.push(name);
    }
    function addSource(source) {
      if (!source || !source.url) return;
      if (!sources.some(function (item) { return item.url === source.url; })) sources.push(source);
      if (!trace.sources.some(function (item) { return item.url === source.url; })) trace.sources.push(source);
      upsertStep({
        id: "source-" + source.url,
        type: "source",
        label: "Reading " + sourceLabel(source),
        detail: source.title || source.snippet || source.url || "",
        status: "completed",
        source: source,
      });
    }

    emitTrace("thinking");

    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      var sep;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        var parsed = parseSseBlock(buffer.slice(0, sep));
        buffer = buffer.slice(sep + 2);
        if (!parsed) continue;
        var ev = parsed.event;
        var data = parsed.data;
        if (ev === "organization") {
          window.dispatchEvent(new CustomEvent("vellum:organization", { detail: data }));
          if (handlers.organization) handlers.organization(data);
          continue;
        }
        if (ev === "agent.activity") {
          semanticSeen = true;
          var agentAct = normalizeAgentActivity(data.activity || data);
          if (!agentAct) continue;
          var existingIndex = activity.findIndex(function (item) { return item.id && item.id === agentAct.id; });
          if (existingIndex >= 0) activity[existingIndex] = Object.assign({}, activity[existingIndex], agentAct);
          else activity.push(agentAct);
          if (agentAct.name) addTool(agentAct.name);
          if (agentAct.source) {
            addSource(agentAct.source);
            if (handlers.sources) handlers.sources(sources.slice());
          }
          upsertStep(agentAct);
          if (agentAct.type === "thinking_started") emitTrace("thinking");
          else if (agentAct.type === "final_answer_started" || agentAct.type === "final_answer_delta") emitTrace("answering");
          else if (agentAct.type === "final_answer_completed") emitTrace("done");
          else emitTrace("researching");
          if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
          continue;
        }
        if (ev.indexOf("response.") === 0 || ev === "error") {
          semanticSeen = true;
          if ((ev === "response.created" || ev === "response.in_progress") && data.thread_id && handlers.meta) {
            handlers.meta({ thread_id: data.thread_id });
            emitTrace("thinking");
          }
          else if (ev === "response.output_item.added") {
            var item = data.item || {};
            if (item.type === "source" && item.source) {
              addSource(item.source);
              if (handlers.sources) handlers.sources(sources.slice());
              emitTrace("researching");
            } else {
              var act = activityFromItem(item);
              if (act) {
                activity.push(act);
                if (item.name) addTool(item.name);
                upsertStep(act);
                if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
                emitTrace("researching");
              }
            }
          } else if (ev === "response.output_text.delta") {
            if (data.delta) {
              if (!firstTokenSeen) {
                firstTokenSeen = true;
                upsertStep({ id: "answering", type: "answer", label: "Answering from gathered context", detail: "", status: "in_progress" });
                emitTrace("answering");
              }
              text += data.delta;
              if (handlers.delta) handlers.delta(text, data.delta);
            }
          } else if (ev === "response.function_call_arguments.delta") {
            var fnItemId = data.item_id || "function";
            var foundFn = false;
            activity = activity.map(function (item) {
              if (item.id === fnItemId) {
                foundFn = true;
                return Object.assign({}, item, { detail: ((item.detail || "") + (data.delta || "")).slice(-500), status: "in_progress" });
              }
              return item;
            });
            if (!foundFn) activity.push({ id: fnItemId, type: "tool_call", label: "Preparing function call", detail: data.delta || "", status: "in_progress" });
            upsertStep({ id: fnItemId, type: "tool_call", label: "Preparing function call", detail: data.delta || "", status: "in_progress" });
            if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
            emitTrace("researching");
          } else if (ev === "response.function_call_arguments.done") {
            var doneFnId = data.item_id || "function";
            activity = activity.map(function (item) {
              return item.id === doneFnId ? Object.assign({}, item, { detail: data.arguments || item.detail || "", status: "completed" }) : item;
            });
            upsertStep({ id: doneFnId, type: "tool_call", label: "Prepared function call", detail: data.arguments || "", status: "completed" });
            if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
            emitTrace(trace.status);
          } else if (ev === "response.completed") {
            var finalResponse = data.response || {};
            if (finalResponse.thread_id && handlers.meta) handlers.meta({ thread_id: finalResponse.thread_id });
            text = text || finalResponse.output_text || "";
            sources = finalResponse.sources || sources;
            tools = finalResponse.tools || tools;
            trace.sources = sources.slice();
            trace.tools = tools.slice();
            trace.completedAt = Date.now();
            upsertStep({ id: "thinking", status: "completed" });
            upsertStep({ id: "answering", status: "completed" });
            completed = true;
            emitTrace("done");
            if (handlers.done) handlers.done({ text: text, sources: sources, tools: tools, activity: activity, thread_id: finalResponse.thread_id });
          } else if (ev === "response.output_item.done") {
            var doneItem = data.item || {};
            activity = activity.map(function (item) {
              return (item.id && doneItem.id && item.id === doneItem.id) || (item.name && doneItem.name && item.name === doneItem.name) ? Object.assign({}, item, { status: doneItem.status || "completed" }) : item;
            });
            upsertStep({ id: doneItem.id, name: doneItem.name, status: doneItem.status || "completed" });
            if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
            emitTrace(trace.status);
          } else if (ev === "error" && handlers.error) {
            trace.completedAt = Date.now();
            upsertStep({ id: "error", type: "error", label: "Stream error", detail: (data.error && (data.error.message || data.error)) || "Backend error", status: "failed" });
            completed = true;
            emitTrace("error");
            handlers.error((data.error && (data.error.message || data.error)) || "Backend error");
          }
          continue;
        }

        if (ev === "meta" && data.thread_id && handlers.meta) handlers.meta({ thread_id: data.thread_id });
        else if (ev === "activity" && !semanticSeen) {
          var fallbackAct = { label: data.label || "Agent activity", detail: data.detail || "", status: "running" };
          activity.push(fallbackAct);
          upsertStep(fallbackAct);
          if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
          emitTrace("researching");
        } else if (ev === "tool" && !semanticSeen) {
          addTool(data.name);
          var fallbackTool = { label: "Used " + (data.name || "tool"), detail: "", name: data.name || "tool", status: "running" };
          activity.push(fallbackTool);
          upsertStep(fallbackTool);
          if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
          emitTrace("researching");
        } else if (ev === "source" && !semanticSeen) {
          addSource(data);
          if (handlers.sources) handlers.sources(sources.slice());
          emitTrace("researching");
        } else if (ev === "token" && !semanticSeen && data.text) {
          if (!firstTokenSeen) {
            firstTokenSeen = true;
            upsertStep({ id: "answering", type: "answer", label: "Answering from gathered context", detail: "", status: "in_progress" });
            emitTrace("answering");
          }
          text += data.text;
          if (handlers.delta) handlers.delta(text, data.text);
        } else if (ev === "final" && !semanticSeen) {
          if (data.thread_id && handlers.meta) handlers.meta({ thread_id: data.thread_id });
          text = text || data.answer || "";
          sources = data.sources || sources;
          tools = data.tools || tools;
          trace.sources = sources.slice();
          trace.tools = tools.slice();
          trace.completedAt = Date.now();
          upsertStep({ id: "thinking", status: "completed" });
          upsertStep({ id: "answering", status: "completed" });
          completed = true;
          emitTrace("done");
          if (handlers.done) handlers.done({ text: text, sources: sources, tools: tools, activity: activity, thread_id: data.thread_id });
        }
      }
    }
    if (!completed && handlers.done) {
      trace.completedAt = Date.now();
      emitTrace("done");
      handlers.done({ text: text || "No response.", sources: sources, tools: tools, activity: activity });
    }
    return { abort: function () { controller.abort(); } };
  }

  window.VellumApi.chat = { stream: stream };
})();
