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
    if (item.type === "subagent_call") return { label: item.label || ("Routed to " + (item.name || "subagent")), detail: item.detail || "", name: item.name, status: item.status };
    if (item.type === "tool_call") return { label: item.label || ("Used " + (item.name || "tool")), detail: item.detail || "", name: item.name, status: item.status };
    if (item.type === "reasoning") return { label: item.label || "Thinking", detail: item.detail || "", status: item.status };
    return null;
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
    var semanticSeen = false;
    var completed = false;

    function addTool(name) {
      if (name && tools.indexOf(name) < 0) tools.push(name);
    }
    function addSource(source) {
      if (!source || !source.url) return;
      if (!sources.some(function (item) { return item.url === source.url; })) sources.push(source);
    }

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
          if ((ev === "response.created" || ev === "response.in_progress") && data.thread_id && handlers.meta) handlers.meta({ thread_id: data.thread_id });
          else if (ev === "response.output_item.added") {
            var item = data.item || {};
            if (item.type === "source" && item.source) {
              addSource(item.source);
              if (handlers.sources) handlers.sources(sources.slice());
            } else {
              var act = activityFromItem(item);
              if (act) {
                activity.push(act);
                if (item.name) addTool(item.name);
                if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
              }
            }
          } else if (ev === "response.output_text.delta") {
            if (data.delta) {
              text += data.delta;
              if (handlers.delta) handlers.delta(text, data.delta);
            }
          } else if (ev === "response.completed") {
            var finalResponse = data.response || {};
            if (finalResponse.thread_id && handlers.meta) handlers.meta({ thread_id: finalResponse.thread_id });
            text = text || finalResponse.output_text || "";
            sources = finalResponse.sources || sources;
            tools = finalResponse.tools || tools;
            completed = true;
            if (handlers.done) handlers.done({ text: text, sources: sources, tools: tools, activity: activity, thread_id: finalResponse.thread_id });
          } else if (ev === "response.output_item.done") {
            var doneItem = data.item || {};
            activity = activity.map(function (item) {
              return item.name && doneItem.name && item.name === doneItem.name ? Object.assign({}, item, { status: doneItem.status || "completed" }) : item;
            });
            if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
          } else if (ev === "error" && handlers.error) {
            completed = true;
            handlers.error((data.error && (data.error.message || data.error)) || "Backend error");
          }
          continue;
        }

        if (ev === "meta" && data.thread_id && handlers.meta) handlers.meta({ thread_id: data.thread_id });
        else if (ev === "activity" && !semanticSeen) {
          activity.push({ label: data.label || "Agent activity", detail: data.detail || "", status: "running" });
          if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
        } else if (ev === "tool" && !semanticSeen) {
          addTool(data.name);
          activity.push({ label: "Used " + (data.name || "tool"), detail: "", name: data.name || "tool", status: "running" });
          if (handlers.activity) handlers.activity(activity.slice(), tools.slice());
        } else if (ev === "source" && !semanticSeen) {
          addSource(data);
          if (handlers.sources) handlers.sources(sources.slice());
        } else if (ev === "token" && !semanticSeen && data.text) {
          text += data.text;
          if (handlers.delta) handlers.delta(text, data.text);
        } else if (ev === "final" && !semanticSeen) {
          if (data.thread_id && handlers.meta) handlers.meta({ thread_id: data.thread_id });
          text = text || data.answer || "";
          sources = data.sources || sources;
          tools = data.tools || tools;
          completed = true;
          if (handlers.done) handlers.done({ text: text, sources: sources, tools: tools, activity: activity, thread_id: data.thread_id });
        }
      }
    }
    if (!completed && handlers.done) {
      handlers.done({ text: text || "No response.", sources: sources, tools: tools, activity: activity });
    }
    return { abort: function () { controller.abort(); } };
  }

  window.VellumApi.chat = { stream: stream };
})();
