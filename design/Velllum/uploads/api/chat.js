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
    if (item.type === "tool_call") return { id: item.id, type: item.type, label: item.label || ("Used " + (item.name || "tool")), detail: item.detail || "", name: item.name, status: item.status };
    if (item.type === "reasoning") return { id: item.id, type: item.type, label: item.label || "Thinking", detail: item.detail || "", status: item.status };
    return null;
  }

  function sourceLabel(source) {
    return source && (source.provider_label || source.domain || source.title || source.url) || "source";
  }

  async function stream(payload, handlers) {
    var controller = new AbortController();
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
